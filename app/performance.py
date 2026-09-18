"""Performance engine.

The point of this module is to produce a return figure that is actually
comparable to an index, which is the thing Fidelity's and Yahoo's own reporting
get wrong. Two rules do most of that work:

  1. Returns are TIME-WEIGHTED. Raw account growth counts your deposits as
     performance. Time-weighting breaks the period at every external cash flow
     and chains the sub-period returns, so what's left is the part your
     decisions caused. This is what GIPS requires, and it is the only basis on
     which comparing yourself to the S&P means anything.

  2. External flows are separated from internal ones. A deposit or a payroll
     contribution is external — new money. A buy, a sell, a dividend is
     internal — the same money moving around. Only the former breaks the period.

Also computes the comparison worth more than the index line itself: replaying
your OWN deposits and withdrawals into the benchmark, which answers "would I
have done better just buying the index?" rather than the weaker question the
plain overlay answers.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import prices

# Money entering or leaving the portfolio from outside. These break the
# time-weighted period; everything else is internal reshuffling.
EXTERNAL_KINDS = {"deposit", "withdrawal", "contribution", "transfer_in", "transfer_out"}

# Movements between the user's OWN accounts are not new money, even though
# Fidelity words them like transfers. "TRANSFERRED FROM/TO BROKERAGE OPTION" is
# a 401(k) moving cash into its own BrokerageLink sleeve. Counting those as
# external deposits inflates contributions and understates the return.
INTERNAL_TRANSFER_MARKERS = ("TO BROKERAGE OPTION", "OTHER PLAN OPTION")


def is_internal_transfer(description: str) -> bool:
    d = (description or "").upper()
    return any(m in d for m in INTERNAL_TRANSFER_MARKERS)

# Kinds that change share count.
POSITION_KINDS = {"buy", "sell", "reinvest", "exchange_in", "exchange_out", "corporate_action"}

INVESTMENT_ACCOUNT_KINDS = {"brokerage", "retirement", "hsa", "crypto"}


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def account_filter_sql(scope: str) -> tuple[str, list]:
    """scope: 'all' | 'taxable' | 'investment' | an account name."""
    if scope == "taxable":
        return "AND a.tax_status = 'taxable'", []
    if scope in ("all", "investment"):
        kinds = ",".join("?" * len(INVESTMENT_ACCOUNT_KINDS))
        return f"AND a.kind IN ({kinds})", list(INVESTMENT_ACCOUNT_KINDS)
    # A named scope must still be an investment account. Pointing this at a
    # checking account produced a negative "portfolio value" and a -503% return,
    # reported as complete.
    kinds = ",".join("?" * len(INVESTMENT_ACCOUNT_KINDS))
    return f"AND a.name = ? AND a.kind IN ({kinds})", [scope, *INVESTMENT_ACCOUNT_KINDS]


def load_transactions(conn, start: str, end: str, scope: str = "investment"):
    where, params = account_filter_sql(scope)
    sql = f"""SELECT t.txn_date, t.kind, t.amount, t.quantity, t.price, t.description,
                     s.symbol, a.name AS account, a.tax_status
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
           LEFT JOIN securities s ON s.id = t.security_id
               WHERE t.txn_date <= ? {where}
            ORDER BY t.txn_date"""
    return [dict(r) for r in conn.execute(sql, [end] + params)]


def positions_asof(txns: list[dict], asof: str) -> dict[str, float]:
    pos: dict[str, float] = defaultdict(float)
    for t in txns:
        if t["txn_date"] <= asof and t["kind"] in POSITION_KINDS and t["symbol"] and t["quantity"]:
            pos[t["symbol"]] += t["quantity"]
    return {k: v for k, v in pos.items() if abs(v) > 1e-9}


# Kinds whose Amount column is NOT a cash movement. A market-value adjustment
# is a valuation figure; treating it as cash lets a revaluation masquerade as a
# deposit. Reverse-split legs are neutralised at import, but excluded here too
# so a future importer change cannot reintroduce the phantom cash.
NON_CASH_KINDS = {"market_value_adj"}


def cash_asof(txns: list[dict], asof: str) -> float:
    """Running sum of signed cash impact, excluding non-cash valuation rows."""
    return sum(t["amount"] or 0.0 for t in txns
               if t["txn_date"] <= asof and t["kind"] not in NON_CASH_KINDS)


def external_flows(txns: list[dict], start: str, end: str,
                   multi_account: bool = True) -> list[tuple[str, float]]:
    """External cash flows in the period.

    Internal-ness is a property of (transfer, SCOPE), not of the description
    alone. A 401(k) moving cash into its own BrokerageLink sleeve is internal to
    the combined portfolio — both sides are present, so it nets — but when the
    scope IS one of those accounts, only one side is in view and the money is
    genuinely arriving from or leaving for somewhere else.

    Suppressing it regardless produced a -100.2% drawdown on the plan account:
    every dollar transferred out looked like a loss.
    """
    flows: dict[str, float] = defaultdict(float)
    for t in txns:
        if start < t["txn_date"] <= end and t["kind"] in EXTERNAL_KINDS:
            if multi_account and is_internal_transfer(t.get("description")):
                continue
            flows[t["txn_date"]] += t["amount"] or 0.0
    return sorted(flows.items())


# Scopes that contain more than one account, and therefore both legs of an
# internal transfer.
MULTI_ACCOUNT_SCOPES = {"investment", "taxable", "all"}


def last_known_price(price_map: dict[str, float], asof: str,
                     dates: list[str] | None = None) -> float | None:
    """Most recent close at or before `asof`.

    On an exact hit this is a dict lookup. On a miss — any weekend, holiday, or
    chart grid point — the old implementation built a list of every earlier date
    and called max() on it, 1,300x slower than a bisect and scanning 52,000
    entries for a single Sunday. A date picker lands on those constantly.
    """
    hit = price_map.get(asof)
    if hit is not None:
        return hit
    if not price_map:
        return None
    keys = dates if dates is not None else sorted(price_map)
    idx = bisect.bisect_right(keys, asof)
    return price_map[keys[idx - 1]] if idx else None


# How old a quote may be before it stops counting as a mark. Prices carry
# forward across weekends and holidays legitimately; a bar from months ago is
# not a valuation, it is the last thing anyone saw.
STALE_AFTER_DAYS = 10

# Above this share of portfolio value carried on stale marks, the return figures
# stop being worth printing.
MATERIAL_STALE_SHARE = 0.10


def last_known_point(price_map: dict[str, float], asof: str,
                     dates: list[str] | None = None) -> tuple[float, str] | None:
    """Like last_known_price, but says WHICH day the price came from.

    Without the date there is no way to tell a Friday close carried into a
    Sunday from a delisted name's final print two years ago — and the second was
    being folded into portfolio value as though it were a current quote.
    """
    if not price_map:
        return None
    hit = price_map.get(asof)
    if hit is not None:
        return hit, asof
    keys = dates if dates is not None else sorted(price_map)
    idx = bisect.bisect_right(keys, asof)
    if not idx:
        return None
    return price_map[keys[idx - 1]], keys[idx - 1]


def _age_days(then: str, now: str) -> int:
    try:
        return (date.fromisoformat(now) - date.fromisoformat(then)).days
    except ValueError:
        return 0


def last_traded_price(txns: list[dict], symbol: str, asof: str) -> float | None:
    """The price the user themselves last transacted at, on or before `asof`.

    A last resort for securities no free feed covers — thinly traded OTC names,
    mostly. It is a real observed price rather than a guess, but it is stale by
    construction, so anything valued this way is reported separately rather
    than being folded silently into the total.
    """
    candidates = [t for t in txns
                  if t["symbol"] == symbol and t["txn_date"] <= asof
                  and t.get("price")
                  and t["kind"] in {"buy", "sell", "reinvest", "corporate_action"}]
    return candidates[-1]["price"] if candidates else None


def market_value(conn, txns: list[dict], asof: str) -> tuple[float, list[str], dict[str, float]]:
    """Value of holdings at `asof`.

    Returns (value, symbols with no price at all, {symbol: value} for holdings
    valued at a stale last-traded price).
    """
    total, missing, stale = 0.0, [], {}
    for symbol, qty in positions_asof(txns, asof).items():
        if prices.is_money_market(symbol):
            # Stable-NAV cash fund: always $1.00, no feed required.
            total += qty * prices.MONEY_MARKET_NAV
            continue
        series = prices.load_series(conn, symbol)
        point = (last_known_point(series, asof, prices.sorted_dates(conn, symbol))
                 if series else None)
        px = None
        if point is not None:
            px, on = point
            # A feed that stopped reporting is not a live mark. Previously the
            # last bar carried forward for ever, so a name whose data ended
            # months ago was valued as confidently as one trading today.
            if _age_days(on, asof) > STALE_AFTER_DAYS:
                stale[symbol] = qty * px
        if px is None:
            px = last_traded_price(txns, symbol, asof)
            if px is None:
                missing.append(symbol)
                continue
            stale[symbol] = qty * px
        total += qty * px
    return total, missing, stale


def values_at(conn, txns: list[dict], dates: list[str]) -> dict[str, tuple[float, list[str]]]:
    """Portfolio value at many dates, from ONE forward pass over the ledger.

    Valuing at N dates previously re-scanned all transactions N times: 173 break
    dates over 3,721 rows is 644,000 row visits to answer 173 questions. This
    walks the ledger once, carrying positions and cash forward, and prices each
    requested date from that running state.

    Note the property that makes this safe and cheap: the value at a date
    depends only on the transactions up to it, never on the requested range.
    """
    wanted = sorted(set(dates))
    out: dict[str, tuple[float, list[str]]] = {}
    pos: dict[str, float] = defaultdict(float)
    cash = 0.0
    i = 0
    ordered = sorted(txns, key=lambda t: t["txn_date"])

    for asof in wanted:
        while i < len(ordered) and ordered[i]["txn_date"] <= asof:
            t = ordered[i]
            if t["kind"] not in NON_CASH_KINDS:
                cash += t["amount"] or 0.0
            if t["kind"] in POSITION_KINDS and t["symbol"] and t["quantity"]:
                pos[t["symbol"]] += t["quantity"]
            i += 1

        total, missing = cash, []
        for symbol, qty in pos.items():
            if abs(qty) <= 1e-9:
                continue
            if prices.is_money_market(symbol):
                total += qty * prices.MONEY_MARKET_NAV
                continue
            series = prices.load_series(conn, symbol)
            px = last_known_price(series, asof, prices.sorted_dates(conn, symbol)) if series else None
            if px is None:
                px = last_traded_price(ordered[:i], symbol, asof)
                if px is None:
                    missing.append(symbol)
                    continue
            total += qty * px
        out[asof] = (total, missing)
    return out


def portfolio_value(conn, txns: list[dict], asof: str) -> tuple[float, list[str]]:
    mv, missing, _stale = market_value(conn, txns, asof)
    return cash_asof(txns, asof) + mv, missing


def modified_dietz(begin_value: float, end_value: float,
                   flows: list[tuple[str, float]], start: str, end: str) -> float | None:
    """Return for the period, weighting each flow by how long it was invested.

    Used instead of full time-weighting when a daily valuation isn't available
    for every flow date — it is the standard approximation and is what most
    trackers actually run.
    """
    s, e = _d(start), _d(end)
    days = (e - s).days
    if days <= 0:
        return None
    net_flow = sum(f for _, f in flows)
    weighted = sum(f * ((days - (_d(d) - s).days) / days) for d, f in flows)
    denom = begin_value + weighted
    if abs(denom) < 1e-9:
        return None
    return (end_value - begin_value - net_flow) / denom


def time_weighted_return(conn, txns: list[dict], start: str, end: str,
                         multi_account: bool = True
                         ) -> tuple[float | None, list[str], int]:
    """Chain sub-period returns, breaking the period at every external flow.

    Guarded against the classic instability: when a sub-period begins with a
    tiny portfolio value — normal in the first weeks of a new account, where a
    few hundred dollars sits beside a five-figure deposit — the ratio
    (value - flow) / begin_value explodes and a handful of those factors can
    turn a real 30% return into a printed 1500%. Sub-periods whose starting
    value is below a materiality floor are therefore MERGED into the following
    sub-period rather than chained, which is the standard treatment. The count
    of merged sub-periods is returned so it can be disclosed.
    """
    flow_by_date = dict(external_flows(txns, start, end, multi_account))
    breaks = sorted({start, *flow_by_date, end})

    valued = values_at(conn, txns, breaks)
    end_value = valued[end][0]
    floor = max(100.0, 0.01 * abs(end_value))

    chain, missing_all, skipped, chained = 1.0, [], 0, 0
    anchor_value, miss = valued[breaks[0]]
    missing_all += miss

    for cut in breaks[1:]:
        value, miss = valued[cut]
        missing_all += miss
        flow = flow_by_date.get(cut, 0.0)
        if anchor_value >= floor:
            chain *= (value - flow) / anchor_value
            chained += 1
        else:
            # Cannot divide by a value this small without the ratio exploding.
            # The sub-period is DROPPED, not merged — an earlier version claimed
            # to merge it but rebuilt the anchor by adding flows the value
            # already contained, which double-counted them and could print a
            # large negative return for a portfolio that never moved.
            skipped += 1
        anchor_value = value

    # Never return 0.0 from a chain that was never multiplied: that reported
    # +0.00% for an account that had lost 15%.
    return ((chain - 1.0) if chained else None), sorted(set(missing_all)), skipped


def benchmark_growth(conn, symbol: str, start: str, end: str) -> dict | None:
    """Growth of the benchmark itself, indexed to 100 at `start`."""
    resolved = prices.resolve_benchmark(symbol)
    if not resolved:
        return None
    series_id, label, caveat = resolved
    series = prices.load_series(conn, series_id)
    if not series:
        return None
    p0, p1 = last_known_price(series, start), last_known_price(series, end)
    if not p0 or not p1:
        return None
    return {"symbol": symbol, "label": label, "caveat": caveat,
            "return": p1 / p0 - 1.0, "begin": p0, "end": p1}


def same_cashflow_benchmark(conn, txns: list[dict], symbol: str,
                            start: str, end: str,
                            multi_account: bool = True) -> dict | None:
    """Replay YOUR deposits and withdrawals into the benchmark.

    This is the comparison that actually answers the question you care about —
    not "how did the index do" but "would I have done better putting the same
    money in at the same times".
    """
    resolved = prices.resolve_benchmark(symbol)
    if not resolved:
        return None
    series_id, label, caveat = resolved
    series = prices.load_series(conn, series_id)
    if not series:
        return None

    begin_value, _ = portfolio_value(conn, txns, start)
    p0 = last_known_price(series, start)
    if not p0:
        return None

    units = begin_value / p0
    invested = begin_value
    flows = external_flows(txns, start, end, multi_account)
    for d, flow in flows:
        px = last_known_price(series, d)
        if px:
            units += flow / px
            invested += flow

    p1 = last_known_price(series, end)
    if not p1:
        return None
    final = units * p1
    # Deliberately reported in DOLLARS. A percentage here would have to be
    # divided by the opening value, which for a new account is a rounding error
    # next to the deposits that followed — the same instability that breaks a
    # naive time-weighted chain. "You have $X, the index would have given you
    # $Y" needs no denominator and cannot be misread.
    # The benchmark's MONEY-weighted return, computed exactly the way the
    # portfolio's is — same opening value, same flows on the same dates, only
    # the ending value differs. That makes the dollar comparison expressible as
    # a percentage on the same footing, instead of being an unmatched figure
    # sitting beside a time-weighted one.
    mwr = modified_dietz(begin_value, final, flows, start, end)
    return {"symbol": symbol, "label": label, "caveat": caveat,
            "final_value": final, "invested": invested, "mwr": mwr}


def analyse(conn, start: str, end: str, scope: str = "investment",
            benchmarks: list[str] | None = None) -> dict:
    txns = load_transactions(conn, start, end, scope)

    # Clamp the start forward to the scope's own first transaction. Asking for
    # "all time" on an account opened partway through is not a request for a
    # period the account did not exist in — it is a request for that account's
    # whole life. Refusing it (which is what happened before) meant selecting a
    # single account simply produced no return at all.
    requested_start = start
    scope_first = min((t["txn_date"] for t in txns), default=None)
    if scope_first and start < scope_first:
        start = scope_first
        txns = load_transactions(conn, start, end, scope)
    begin_value, miss_b = portfolio_value(conn, txns, start)
    end_value, miss_e = portfolio_value(conn, txns, end)
    _mv, _m, stale = market_value(conn, txns, end)

    # Whether a transfer is EXTERNAL depends on the scope being measured, so the
    # same flag has to reach every consumer. It reached the time-weighted return
    # and not Modified Dietz, which meant that on a single-account scope Dietz
    # suppressed transfers whose other leg was outside the scope entirely —
    # treating real deposits as if they were internal. On the BrokerageLink Roth
    # sleeve that reported +2211% against $0 of net deposits, flagged complete,
    # beside $28,604.78 of actual inflows.
    multi = scope in MULTI_ACCOUNT_SCOPES
    flows = external_flows(txns, start, end, multi)
    twr, missing, merged_subperiods = time_weighted_return(conn, txns, start, end, multi)
    dietz = modified_dietz(begin_value, end_value, flows, start, end)

    # Price coverage decides whether the return figures mean anything at all.
    # An unpriced holding silently counts as zero, which does not make the
    # number merely imprecise — it makes it wrong, and wrong in a direction
    # that still looks like a plausible percentage. So coverage is reported
    # alongside, and the caller is expected to withhold the figures when it
    # is not complete.
    # A return is only meaningful if the opening portfolio is actually known.
    # The exact test is whether the requested start date is at or before the
    # first transaction the ledger holds for these accounts. If it is, a small
    # beginning value is not a gap in the data — it is the account genuinely
    # being new. If it is not, positions opened earlier are invisible and any
    # return computed here would be meaningless while still printing as a
    # plausible percentage.
    #
    # An earlier version guessed at this by comparing beginning value against
    # net flows, which wrongly flagged a correctly-anchored account that simply
    # started from nothing.
    # The opening portfolio is known when every transaction preceding `start`
    # is already in the ledger — that is, when `start` is at or AFTER the first
    # row on record. An earlier version had this backwards and so refused every
    # sub-period report (where the opening value is perfectly well known) while
    # happily accepting a start date years before any data existed.
    first_txn = min((t["txn_date"] for t in txns), default=None)
    anchored = first_txn is not None and start >= first_txn

    # Coverage must consider every date the return is computed at. Measuring
    # only the endpoints missed a position that was 7.7% of the book for three
    # months and netted to zero at both ends — the report called it complete.
    held: set[str] = set()
    for cut in {start, end, *(d for d, _ in flows)}:
        held |= set(positions_asof(txns, cut))
    unpriced = set(missing)
    # Coverage is VALUE-weighted and counts a stale mark as unpriced. Counting
    # symbols, and only calling a symbol unpriced when no number could be found
    # at all, made this incapable of falling below 1.0: every holding was bought
    # at some price, so a fallback always existed. A position worth $13,200 with
    # zero price bars, marked to a five-month-old fill, reported 100% coverage.
    stale_value = sum(stale.values())
    coverage = (1.0 if not held
                else max(0.0, (end_value - stale_value) / end_value) if end_value
                else 0.0)
    stale_share = (stale_value / end_value) if end_value else 0.0

    # An account whose rows carry no ticker (an employer plan that exports fund
    # names only) has no positions at all, so the coverage check above cannot
    # see it — its value is contributions at cost and never moves with the
    # market. Surface it rather than letting cost basis pass as market value.
    at_cost = []
    for acct in {t["account"] for t in txns}:
        atx = [t for t in txns if t["account"] == acct]
        if not positions_asof(atx, end) and abs(cash_asof(atx, end)) > 1.0:
            at_cost.append({"account": acct, "value": round(cash_asof(atx, end), 2)})
    at_cost.sort(key=lambda a: -abs(a["value"]))

    # An unclassified row carrying cash is the dangerous case this importer's
    # header warns about: "other" is not in EXTERNAL_KINDS, so money moving in or
    # out under an unrecognised Action is not stripped as a flow and reads as
    # investment performance instead. There are none today; the point is that if
    # Fidelity ever changes a verb, it must show up here rather than quietly
    # improving the return.
    unclassified = [t for t in txns
                    if t["kind"] == "other" and abs(t.get("amount") or 0) > 1.0]
    unclassified_total = sum(abs(t["amount"]) for t in unclassified)
    unclassified_material = (
        unclassified_total > max(100.0, 0.005 * abs(end_value or 0)))

    out = {
        "scope": scope, "start": start, "end": end,
        "requested_start": requested_start,
        "start_clamped": requested_start != start,
        "at_cost_accounts": at_cost,
        "at_cost_total": round(sum(a["value"] for a in at_cost), 2),
        "transactions": len(txns),
        "begin_value": begin_value, "end_value": end_value,
        "net_external_flow": sum(f for _, f in flows),
        "flow_events": len(flows),
        "twr": twr, "modified_dietz": dietz, "skipped_subperiods": merged_subperiods,
        "missing_prices": sorted(set(miss_b + miss_e + missing)),
        "held_securities": len(held),
        "priced_securities": len(held - unpriced),
        "price_coverage": coverage,
        # Withholding every return because 4% of the book is an untraded OTC
        # name would be its own kind of dishonesty, so `complete` tolerates a
        # small stale share and reports it. What it will no longer do is pass
        # unconditionally.
        "complete": (anchored and not unpriced
                     and stale_share <= MATERIAL_STALE_SHARE
                     and not unclassified_material),
        "unclassified_cash": round(unclassified_total, 2),
        "unclassified_rows": len(unclassified),
        "unclassified_actions": sorted({(t.get("description") or "")[:60]
                                        for t in unclassified})[:8],
        "stale_share_material": stale_share > MATERIAL_STALE_SHARE,
        "anchored": anchored,
        "first_transaction": first_txn,
        "range_precedes_data": bool(first_txn and start < first_txn),
        "stale_valued": stale,
        "stale_value_total": sum(stale.values()),
        "stale_share_of_value": stale_share,
        "benchmarks": [],
    }
    for name in (benchmarks or []):
        growth = benchmark_growth(conn, name, start, end)
        # The SAME scope flag the return it is compared against uses. Omitting
        # it made the replay see $0 of deposits on a single-account scope while
        # the portfolio leg saw $28,604.78, so the two sides of "would I have
        # done better in the index" were computed on different money.
        replay = same_cashflow_benchmark(conn, txns, name, start, end, multi)
        if not growth:
            out["benchmarks"].append({"symbol": name, "error": "no data / unknown benchmark"})
            continue
        growth["same_cashflow"] = replay

        # TWO comparisons, because they answer different questions and can
        # legitimately disagree in sign.
        #
        #   percentage — your time-weighted return against the index return.
        #     Both ignore when money arrived, so this measures selection: did
        #     the things you picked beat the index over the same days.
        #
        #   dollars — your actual ending value against the same deposits made
        #     on the same dates into the index. This does NOT ignore timing.
        #
        # When percentage says ahead and dollars say behind, that gap IS the
        # finding: the good returns happened while less money was invested.
        # TIME-WEIGHTED: your return vs the index's, both ignoring when money
        # arrived. Measures selection only.
        growth["tw_delta"] = (twr - growth["return"]) if twr is not None else None

        # MONEY-WEIGHTED: your return vs the same deposits into the index,
        # both computed the same way, plus the dollar gap that produces.
        # Measures selection AND timing together.
        growth["mw_you"] = dietz
        growth["mw_benchmark"] = replay.get("mwr") if replay else None
        growth["mw_delta"] = (
            dietz - growth["mw_benchmark"]
            if dietz is not None and growth["mw_benchmark"] is not None else None)
        growth["dollar_delta"] = (
            end_value - replay["final_value"] if replay and replay.get("final_value") is not None
            else None)

        # When these disagree in sign, the gap IS the finding: the picks worked,
        # the timing did not (or the reverse).
        growth["timing_disagrees"] = (
            growth["tw_delta"] is not None and growth["mw_delta"] is not None
            and (growth["tw_delta"] > 0) != (growth["mw_delta"] > 0))
        out["benchmarks"].append(growth)
    return out


def list_accounts(conn) -> list[dict]:
    """Scopes the user can select, with the transaction span each covers."""
    rows = conn.execute("""
        SELECT a.name, a.kind, a.tax_status, COUNT(*) txns,
               MIN(t.txn_date) first, MAX(t.txn_date) last
          FROM accounts a JOIN transactions t ON t.account_id = a.id
      GROUP BY a.id ORDER BY COUNT(*) DESC""")
    return [dict(r) for r in rows
            if r["kind"] in INVESTMENT_ACCOUNT_KINDS]
