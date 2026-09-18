"""Drawdown and risk metrics.

Return alone is half the picture. A portfolio that gained 90% by way of a 50%
drawdown is a different proposition from one that gained 70% smoothly, and the
difference decides whether a strategy is survivable in practice — most people
abandon a method during the drawdown, not after it.

Every return here is FLOW-ADJUSTED. A deposit is not a gain, so each period's
return subtracts the money that arrived in it before dividing. Skipping that
would turn every payday into a spike of apparent volatility and make Sharpe
meaningless.
"""
from __future__ import annotations

import math
from datetime import datetime

from . import performance, prices

TRADING_DAYS = 252
RISK_FREE_SERIES = "DGS3MO"      # 3-month Treasury, free from FRED, no key


def _d(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def risk_free_rate(conn, start: str, end: str) -> float:
    """Average annualised 3-month Treasury yield over the period, as a decimal.

    Returns None when the series is not cached, rather than 0.0. The docstring
    used to claim "the caller is told", and no caller was: an uncached series
    silently became a zero risk-free rate while risk.py reported "excess over
    cash" and backtest.py shipped a caveat asserting excess over the 3-month
    Treasury. A Sharpe computed against an assumed zero is a different number
    with the same name.

    FRED publishes this as a percent, so the /100 is what makes it a decimal —
    omitting it inflates the rate a hundredfold and drives every Sharpe deeply
    negative.
    """
    series = prices.load_series(conn, RISK_FREE_SERIES)
    if not series:
        return None
    vals = [v for d, v in series.items() if start <= d <= end]
    return (sum(vals) / len(vals) / 100.0) if vals else None


def period_returns(conn, txns, dates: list[str],
                   multi_account: bool = True) -> list[tuple[str, float]]:
    """Flow-adjusted return for each consecutive pair of dates."""
    # An empty ledger opened on a weekend has no valued dates at all; there
    # is nothing to return between, and indexing dates[0] threw a 500 that
    # left a fresh install on "Loading your portfolio" forever.
    if len(dates) < 2:
        return []
    valued = performance.values_at(conn, txns, dates)
    flows = dict(performance.external_flows(txns, dates[0], dates[-1], multi_account))

    out, prev_v, prev_d = [], valued[dates[0]][0], dates[0]
    for d in dates[1:]:
        v = valued[d][0]
        # Every external flow strictly after the previous point, up to and
        # including this one, belongs to this period.
        flow = sum(amt for fd, amt in flows.items() if prev_d < fd <= d)
        if prev_v > 1e-6:
            out.append((d, (v - flow) / prev_v - 1.0))
        prev_v, prev_d = v, d
    return out


def drawdown_curve(conn, txns, dates: list[str],
                   multi_account: bool = True) -> tuple[list[dict], dict]:
    """Underwater curve from a flow-adjusted growth index, plus the worst episode.

    Built from compounded returns rather than raw account value: otherwise a
    withdrawal reads as a drawdown and a deposit as a recovery, which is exactly
    backwards.
    """
    rets = period_returns(conn, txns, dates, multi_account)
    curve, peak, growth = [], 1.0, 1.0
    worst = {"depth": 0.0, "peak_date": None, "trough_date": None,
             "recovered_date": None, "days": 0}
    cur_peak_date = dates[0]

    for d, r in rets:
        growth *= (1.0 + r)
        # A drawdown is over when the portfolio is back AT its prior peak, not
        # when it makes a new high — getting back to even is the recovery, and
        # requiring a fresh high dated recoveries late (or never, for a
        # portfolio still below its old peak).
        if growth >= peak - 1e-12:
            if worst["trough_date"] and not worst["recovered_date"]:
                worst["recovered_date"] = d
            peak, cur_peak_date = max(peak, growth), d
        dd = growth / peak - 1.0
        curve.append({"date": d, "drawdown": round(dd, 6), "growth": round(growth, 6)})
        if dd < worst["depth"]:
            worst = {"depth": dd, "peak_date": cur_peak_date, "trough_date": d,
                     "recovered_date": None, "days": 0}

    if worst["peak_date"] and worst["trough_date"]:
        worst["days"] = (_d(worst["trough_date"]) - _d(worst["peak_date"])).days
        worst["recovery_days"] = ((_d(worst["recovered_date"]) - _d(worst["trough_date"])).days
                                  if worst["recovered_date"] else None)
    return curve, worst


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def metrics(conn, txns, dates: list[str], benchmark: str | None = None,
            multi_account: bool = True) -> dict:
    """Volatility, Sharpe, Sortino, drawdown, Calmar, beta and capture ratios."""
    rets = period_returns(conn, txns, dates, multi_account)
    if len(rets) < 3:
        return {"insufficient_data": True, "periods": len(rets)}

    vals = [r for _, r in rets]
    span_days = max((_d(dates[-1]) - _d(dates[0])).days, 1)
    per_year = len(vals) / (span_days / 365.25)          # sampling frequency
    scale = math.sqrt(per_year)

    total_growth = 1.0
    for v in vals:
        total_growth *= (1.0 + v)
    years = span_days / 365.25
    cagr = (total_growth ** (1 / years) - 1.0) if years > 0 and total_growth > 0 else None

    vol = _stdev(vals) * scale
    rf = risk_free_rate(conn, dates[0], dates[-1])
    rf_known = rf is not None
    rf = rf or 0.0
    excess_cagr = (cagr - rf) if cagr is not None else None
    sharpe = (excess_cagr / vol) if vol > 1e-9 and excess_cagr is not None else None

    # Sortino penalises only downside deviation — upside volatility is not risk.
    downside = [v for v in vals if v < 0]
    dstd = (math.sqrt(sum(v * v for v in downside) / len(vals)) * scale) if downside else 0.0
    sortino = (excess_cagr / dstd) if dstd > 1e-9 and excess_cagr is not None else None

    curve, worst = drawdown_curve(conn, txns, dates, multi_account)
    max_dd = min((p["drawdown"] for p in curve), default=0.0)
    current_dd = curve[-1]["drawdown"] if curve else 0.0
    calmar = (cagr / abs(max_dd)) if cagr is not None and abs(max_dd) > 1e-9 else None

    out = {
        "periods": len(vals), "samples_per_year": round(per_year, 1),
        "cagr": cagr, "volatility": vol,
        "risk_free": rf if rf_known else None,
        "risk_free_source": RISK_FREE_SERIES if rf_known else None,
        # So a reader can tell "cash paid nothing" from "we could not find out".
        "risk_free_assumed_zero": not rf_known,
        "sharpe": sharpe, "sortino": sortino,
        "max_drawdown": max_dd, "current_drawdown": current_dd,
        "calmar": calmar,
        "worst_episode": worst,
        "best_period": max(rets, key=lambda r: r[1]),
        "worst_period": min(rets, key=lambda r: r[1]),
        "positive_periods": sum(1 for v in vals if v > 0) / len(vals),
        "curve": curve,
    }

    if benchmark:
        resolved = prices.resolve_benchmark(benchmark)
        if resolved:
            bser = prices.load_series(conn, resolved[0])
            bdates = prices.sorted_dates(conn, resolved[0])
            bvals = []
            for i in range(1, len(dates)):
                p0 = performance.last_known_price(bser, dates[i - 1], bdates)
                p1 = performance.last_known_price(bser, dates[i], bdates)
                bvals.append((p1 / p0 - 1.0) if p0 and p1 else 0.0)
            pairs = list(zip(vals, bvals))
            bm_mean = sum(bvals) / len(bvals)
            var = sum((b - bm_mean) ** 2 for b in bvals) / len(bvals)
            mean = sum(vals) / len(vals)
            cov = sum((p - mean) * (b - bm_mean) for p, b in pairs) / len(pairs)
            beta = (cov / var) if var > 1e-12 else None
            ups = [(p, b) for p, b in pairs if b > 0]
            downs = [(p, b) for p, b in pairs if b < 0]
            out["benchmark"] = {
                "symbol": benchmark, "label": resolved[1],
                "beta": beta,
                "volatility": _stdev(bvals) * scale,
                # Alpha here is annualised excess over what beta alone predicts.
                "alpha": ((cagr - rf) - beta * ((1 + bm_mean) ** per_year - 1 - rf)
                          if beta is not None and cagr is not None else None),
                "up_capture": (sum(p for p, _ in ups) / sum(b for _, b in ups)
                               if ups and sum(b for _, b in ups) else None),
                "down_capture": (sum(p for p, _ in downs) / sum(b for _, b in downs)
                                 if downs and sum(b for _, b in downs) else None),
            }
    return out


# ---------------------------------------------------------------- concentration

def _returns_from_series(series: dict[str, float], dates: list[str],
                         sorted_dates_: list[str],
                         unknown=0.0) -> list[float | None]:
    """Period returns, with `unknown` standing in where a price is missing.

    Pass unknown=None to get an honest gap. Substituting 0.0 says "this holding
    did not move", which is a statement about the market rather than about the
    data — it drives volatility, beta and risk contribution to zero while the
    position keeps its full weight, so a name nobody has a price for looks like
    the safest thing in the book.
    """
    out = []
    for i in range(1, len(dates)):
        p0 = performance.last_known_price(series, dates[i - 1], sorted_dates_)
        p1 = performance.last_known_price(series, dates[i], sorted_dates_)
        out.append((p1 / p0 - 1.0) if p0 and p1 else unknown)
    return out


MIN_MEASURED = 60      # periods of prices a holding needs before its risk share is measured


def concentration(conn, positions: list[dict], dates: list[str]) -> dict:
    """How concentrated the portfolio is, and where its risk actually sits.

    Weight alone understates the problem: a 45% position in something three
    times as volatile as the rest of the book carries far more than 45% of the
    risk. Risk contribution is therefore computed properly, from the covariance
    of each holding with the portfolio, so the shares sum to 100% and a
    position's correlation with everything else is accounted for rather than
    ignored.
    """
    held = [p for p in positions if p.get("value")]
    total = sum(p["value"] for p in held)
    if not held or total <= 0:
        return {"positions": 0}

    weights = {p["symbol"]: p["value"] / total for p in held}

    # Herfindahl index; its reciprocal is the "effective number of holdings" —
    # how many equally-sized positions would be as concentrated as this book.
    hhi = sum(w * w for w in weights.values())
    effective_n = (1.0 / hhi) if hhi > 0 else 0.0

    # A holding with no usable price history cannot have a risk contribution
    # computed. It is set aside and REPORTED, rather than handed a fabricated
    # run of 0.00% returns which would rank it as the least risky thing held.
    n_full = len(dates) - 1
    raw_by: dict[str, list] = {}
    unmeasured = []
    for p in held:
        sym = p["symbol"]
        series = prices.load_series(conn, sym)
        raw = (_returns_from_series(series, dates, prices.sorted_dates(conn, sym),
                                    unknown=None) if series else [None] * n_full)
        known = sum(1 for r in raw if r is not None)
        # A name needs a real run of prices to be measured. Sixty periods is
        # the floor; a holding bought this spring on a thin listing (SIVEF)
        # used to fall out for having less than half the range, which left the
        # book's second-largest position out of the table it belongs in.
        if known < max(2, min(MIN_MEASURED, n_full // 2)):
            unmeasured.append({"symbol": sym, "weight": weights.get(sym, 0.0),
                               "periods_priced": known, "periods": n_full})
            continue
        raw_by[sym] = raw
    # The common window: the last K periods, K being the shortest priced run
    # among the measured names, so covariances are all taken over the same
    # dates. Everything below is over that window, and its length is reported.
    def _run(raw):
        k = 0
        for r in reversed(raw):
            if r is None:
                break
            k += 1
        return k
    n = min([_run(r) for r in raw_by.values()] or [n_full])
    n = max(min(n, n_full), 2)
    dates = dates[-(n + 1):]
    rets: dict[str, list[float]] = {}
    for sym, raw in raw_by.items():
        tail = raw[-n:]
        # Gaps inside an otherwise-priced series are carried as flat, which is
        # what a stale quote actually implies for one or two periods.
        rets[sym] = [0.0 if r is None else r for r in tail]

    syms = [p["symbol"] for p in held if p["symbol"] in rets]
    # Weights are renormalised across what CAN be measured, so the risk shares
    # sum over the measured book rather than silently under-summing.
    measured_weight = sum(weights.get(s, 0.0) for s in syms)
    if measured_weight > 0:
        weights = {s: weights[s] / measured_weight for s in syms}
    means = {s: (sum(rets[s]) / n if n else 0.0) for s in syms}

    # Portfolio return per period, then each holding's covariance with it.
    port = [sum(weights[s] * rets[s][i] for s in syms) for i in range(n)]
    pmean = sum(port) / n if n else 0.0
    pvar = sum((x - pmean) ** 2 for x in port) / n if n else 0.0

    span_days = max((_d(dates[-1]) - _d(dates[0])).days, 1)
    per_year = n / (span_days / 365.25) if span_days else TRADING_DAYS
    scale = math.sqrt(per_year)

    rows = []
    for s in syms:
        cov = (sum((rets[s][i] - means[s]) * (port[i] - pmean) for i in range(n)) / n) if n else 0.0
        share = (weights[s] * cov / pvar) if pvar > 1e-14 else 0.0
        own_vol = _stdev(rets[s]) * scale
        pos = next(p for p in held if p["symbol"] == s)

        # Volatility measured only over the stretch actually owned, alongside
        # the full-window figure the covariance uses. They can differ wildly:
        # a name whose history contains a regime you were never exposed to
        # looks far riskier than your experience of it, and the reverse is
        # equally possible. Reporting both keeps the attribution standard
        # (a common window, as every risk system uses) without implying the
        # full-window number describes what you lived through.
        since = pos.get("oldest_lot")
        held_idx = [i for i in range(n) if dates[i + 1] >= (since or dates[0])]
        vol_held = (_stdev([rets[s][i] for i in held_idx]) * scale
                    if len(held_idx) > 2 else None)

        rows.append({"symbol": s, "weight": weights[s], "risk_share": share,
                     "volatility": own_vol, "volatility_held": vol_held,
                     "held_since": since,
                     "history_predates_holding": bool(
                         vol_held is not None and own_vol > 1e-9
                         and abs(vol_held - own_vol) / own_vol > 0.25),
                     # >1 means it carries more risk than its size suggests.
                     "risk_vs_weight": (share / weights[s]) if weights[s] > 1e-9 else None,
                     "value": pos["value"]})
    rows.sort(key=lambda r: -r["risk_share"])

    ranked = sorted(weights.values(), reverse=True)
    return {
        "positions": len(held), "total": round(total, 2),
        "hhi": round(hhi, 4), "effective_holdings": round(effective_n, 1),
        "top1": ranked[0], "top3": sum(ranked[:3]), "top5": sum(ranked[:5]),
        "portfolio_volatility": math.sqrt(pvar) * scale,
        "rows": rows,
        # Named, not silently dropped: these carry weight in the book but no
        # risk figure, so any reader of `rows` knows what the shares cover.
        "unmeasured": unmeasured,
        "unmeasured_weight": round(sum(u["weight"] for u in unmeasured), 4),
        # The window the shares were measured over: shorter than the range
        # when a measured holding has a short price history.
        "window_periods": n, "window_from": dates[0], "range_periods": n_full,
    }


def by_account(conn, scopes: list[str], dates: list[str], end: str) -> list[dict]:
    """Drawdown and volatility per account, so a portfolio-level figure can be
    traced to the account actually producing it."""
    out = []
    for name in scopes:
        txns = performance.load_transactions(conn, dates[0], end, name)
        if not txns:
            continue
        first = min(t["txn_date"] for t in txns)
        # Start where the account holds real money. A $0.50 deposit followed
        # by $500 a week later gave Robinhood a 1,005% volatility and a 957%
        # CAGR; the portfolio path merges such sub-periods, this one did not.
        end_value, _ = performance.portfolio_value(conn, txns, end)
        floor_value = max(500.0, 0.10 * abs(end_value or 0))
        running = 0.0
        for day, flow in sorted(performance.external_flows(txns, first, end, False)):
            running += flow
            if running >= floor_value:
                first = max(first, day)
                break
        grid = [d for d in dates if d >= first]
        if len(grid) < 4:
            continue
        m = metrics(conn, txns, grid, multi_account=False)   # single account
        if m.get("insufficient_data"):
            continue
        value, _ = performance.portfolio_value(conn, txns, end)

        # An account whose rows carry no ticker — an employer plan exporting
        # fund names only — has a "value" that is contributions at cost. It never
        # moves with the market, so volatility collapses toward zero and Sharpe
        # explodes: the L3Harris plan reported -8.98 beside genuine figures.
        # `analyse` already detects exactly this case and surfaces it; this
        # function had no equivalent guard and printed the number anyway.
        priced = performance.positions_asof(txns, end)
        at_cost = not priced and abs(performance.cash_asof(txns, end)) > 1.0
        out.append({"account": name, "value": round(value, 2),
                    "at_cost": at_cost,
                    "note": ("Value is contributions at cost — this account "
                             "reports no tickers, so these figures describe the "
                             "contribution schedule, not the market."
                             if at_cost else None),
                    "max_drawdown": m["max_drawdown"],
                    "current_drawdown": m["current_drawdown"],
                    "volatility": None if at_cost else m["volatility"],
                    "sharpe": None if at_cost else m["sharpe"],
                    "cagr": None if at_cost else m["cagr"]})
    out.sort(key=lambda r: r["max_drawdown"])
    return out


def correlation(conn, positions: list[dict], dates: list[str], top: int = 14) -> dict:
    """Pairwise correlation between holdings, plus greedy clusters.

    The point is not the matrix, it is the answer to "how many bets is this
    really". Sixteen positions that all move together are one position with
    extra steps, and the effective-holdings figure hints at that without saying
    which names are the duplicates.

    Clustering is deliberately simple and greedy — seed on the largest unassigned
    holding, absorb anything correlated above the threshold — because the goal is
    a readable grouping, not a taxonomy.
    """
    held = [p for p in positions if p.get("value")]
    held.sort(key=lambda p: -p["value"])
    held = held[:top]
    if len(held) < 2:
        return {"symbols": [], "matrix": [], "clusters": []}

    total = sum(p["value"] for p in held)
    rets: dict[str, list[float]] = {}
    for p in held:
        sym = p["symbol"]
        series = prices.load_series(conn, sym)
        rets[sym] = (_returns_from_series(series, dates, prices.sorted_dates(conn, sym))
                     if series else [])

    syms = [p["symbol"] for p in held if len(rets[p["symbol"]]) > 2]
    if len(syms) < 2:
        # Fewer than two measurable series is not a correlation matrix. min() on
        # an empty sequence used to raise ValueError and take the whole request
        # with it.
        return {"symbols": [], "matrix": [], "pairs": [],
                "note": "Not enough priced history to compute correlations."}
    n = min(len(rets[s]) for s in syms)
    means = {s: sum(rets[s][:n]) / n for s in syms}
    sds = {s: _stdev(rets[s][:n]) for s in syms}

    def corr(a: str, b: str) -> float | None:
        if sds[a] < 1e-12 or sds[b] < 1e-12:
            return None
        cov = sum((rets[a][i] - means[a]) * (rets[b][i] - means[b]) for i in range(n)) / (n - 1)
        return max(-1.0, min(1.0, cov / (sds[a] * sds[b])))

    matrix = [[1.0 if a == b else corr(a, b) for b in syms] for a in syms]

    pairs = []
    for i, a in enumerate(syms):
        for j, b in enumerate(syms):
            if j > i and matrix[i][j] is not None:
                pairs.append({"a": a, "b": b, "r": round(matrix[i][j], 3)})
    offdiag = [p["r"] for p in pairs]
    pairs.sort(key=lambda p: -p["r"])

    # Weighted average pairwise correlation — the single number that says how
    # much diversification the position count is actually buying.
    weights = {p["symbol"]: p["value"] / total for p in held}
    wsum = num = 0.0
    for i, a in enumerate(syms):
        for j, b in enumerate(syms):
            if j > i and matrix[i][j] is not None:
                w = weights[a] * weights[b]
                num += w * matrix[i][j]
                wsum += w

    threshold = 0.6
    clusters, assigned = [], set()
    for s in syms:                                   # syms is value-ordered
        if s in assigned:
            continue
        group = [s]
        assigned.add(s)
        si = syms.index(s)
        for other in syms:
            if other in assigned:
                continue
            r = matrix[si][syms.index(other)]
            if r is not None and r >= threshold:
                group.append(other)
                assigned.add(other)
        clusters.append({"members": group,
                         "weight": sum(weights[m] for m in group),
                         "value": round(sum(weights[m] * total for m in group), 2)})
    clusters.sort(key=lambda c: -c["weight"])

    return {
        "symbols": syms, "matrix": matrix,
        "average": (sum(offdiag) / len(offdiag)) if offdiag else None,
        "weighted_average": (num / wsum) if wsum > 1e-12 else None,
        "most_correlated": pairs[:6],
        "least_correlated": pairs[-6:][::-1],
        "clusters": clusters, "threshold": threshold,
        "periods": n,
    }


# --------------------------------------------------------- per position ----
# Everything above is portfolio-level: one Sharpe, one drawdown, one beta for
# the whole book. That is the right shape for "how am I doing" and the wrong
# shape for "what is happening to my things", and the app had only the first.
#
# The gap was concrete. A holding could be 68% below its own high while still
# showing a large gain against cost, and nothing on any screen would say so,
# because unrealised P/L is measured from what you paid and says nothing about
# what you have given back. Another could rise 82% in a month without a single
# panel noticing. Both are facts about a position that a portfolio-level
# statistic structurally cannot express.

# How far below its own peak before a position is worth calling out. Chosen to
# be well outside ordinary volatility for these names — the book's own
# portfolio-level max drawdown is 46%, so a 25% position drawdown is common
# enough not to be noise-free, but past that it is a real give-back.
GIVEBACK = 0.25
# A move this large in a month is a regime change worth a second look, in
# either direction.
SURGE = 0.25
LOOKBACKS = [("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252)]


def _change(bars: list[dict], n: int) -> float | None:
    if len(bars) <= n:
        return None
    then = bars[-1 - n]["close"]
    return (bars[-1]["close"] / then - 1) if then else None


def position_moves(conn, positions: list[dict], end: str) -> list[dict]:
    """Per-holding peak while held, what has been handed back from it, and momentum.

    The peak is the highest intraday price since the day the oldest open lot
    was bought — not the highest close, and not over the whole cached history. The all-history figure was what this reported
    first, and it produced AEVA "85% below its high" against a high from
    February 2021, five years before the position existed, and ASST against a
    2023 print three years before its first lot. Neither is something the
    holder gave back. What they want to know is the SIVEF shape: at the June
    high the position was up nearly 800% on cost, and today it is up 104% — so
    the give-back is stated three ways, as price from the held peak, as gain on
    cost at the peak against gain on cost now, and in dollars. The all-history
    high is kept as its own field, labelled, for the chart reader.

    Cost per share is derived from the position's own unrealised figure rather
    than read from the lots, so it is in the same terms as the bars — which are
    split-adjusted — without repeating the reconciliation holdings.py already
    did.
    """
    out = []
    for p in positions:
        symbol = p.get("symbol")
        # Money-market sweeps are not positions in any meaningful sense.
        if not symbol or prices.is_cash_like(symbol):
            continue
        bars = prices.load_bars(conn, symbol, "2015-01-01", end)
        if len(bars) < 30:
            continue
        last = bars[-1]["close"]
        since = (p.get("oldest_lot") or "")[:10] or None
        held = [b for b in bars if b["time"] >= since] if since else bars
        if not held:
            held = bars[-1:]
        # The peak is the day's HIGH, not its close: the position was worth
        # that much at that moment, and it is the figure the broker showed.
        # SIVEF touched 11.15 on 2026-06-17 and closed at 10.49 — +695% on
        # cost against +648% — and the user remembered the first number,
        # rightly. Bars without a high (an older cache row) fall back to the
        # close, so the peak can never be below what the close-only reading
        # gave.
        def _hi(b):
            return b.get("high") or b["close"]
        peak = max(held, key=_hi)
        peak = {**peak, "close": _hi(peak)}
        trough_after = min((b for b in held if b["time"] >= peak["time"]),
                           key=lambda b: b["close"], default=None)
        ath = max(bars, key=lambda b: b["close"])
        year = [b for b in bars if b["time"] >= _year_before(end)]
        hi52 = max((b["close"] for b in year), default=None)
        lo52 = min((b["close"] for b in year), default=None)

        upct = p.get("unrealised_pct")
        price_now = p.get("price") or last
        cost = (price_now / (1 + upct)) if (upct is not None and upct > -1 and price_now) else None
        qty = p.get("quantity") or 0
        gain_at_peak = (peak["close"] / cost - 1) if cost else None
        given_back_pct = ((gain_at_peak - upct) if (gain_at_peak is not None and upct is not None)
                          else None)
        given_back_usd = (peak["close"] - last) * qty if qty else None

        row = {
            "symbol": symbol,
            "price": round(last, 4),
            "weight": p.get("weight"),
            "value": p.get("value"),
            "held_since": since,
            # Against cost — what the app already showed.
            "unrealised_pct": upct,
            # Against its own high WHILE HELD — what it did not.
            "peak": round(peak["close"], 4),
            "peak_date": peak["time"],
            "from_peak": round(last / peak["close"] - 1, 4) if peak["close"] else None,
            "worst_since_peak": (round(trough_after["close"] / peak["close"] - 1, 4)
                                 if trough_after and peak["close"] else None),
            "gain_at_peak_pct": round(gain_at_peak, 4) if gain_at_peak is not None else None,
            "given_back_pct": round(given_back_pct, 4) if given_back_pct is not None else None,
            "given_back_usd": round(given_back_usd, 2) if given_back_usd is not None else None,
            # The whole cached history, kept apart so it cannot be read as a
            # give-back.
            "all_time_high": round(ath["close"], 4),
            "all_time_high_date": ath["time"],
            "from_all_time_high": round(last / ath["close"] - 1, 4) if ath["close"] else None,
            "high_52w": round(hi52, 4) if hi52 else None,
            "low_52w": round(lo52, 4) if lo52 else None,
            "from_52w_high": (round(last / hi52 - 1, 4) if hi52 else None),
            "history_from": bars[0]["time"],
        }
        for label, n in LOOKBACKS:
            row[label] = (round(_change(bars, n), 4)
                          if _change(bars, n) is not None else None)

        notes = []
        if row["from_peak"] is not None and row["from_peak"] <= -GIVEBACK:
            notes.append(f"{abs(row['from_peak'])*100:.0f}% below its "
                         f"{peak['time']} high of {peak['close']:,.2f}"
                         + (f" — was {gain_at_peak*100:+.0f}% on cost there, "
                            f"{upct*100:+.0f}% now" if gain_at_peak is not None
                            and upct is not None else ""))
        if row["1m"] is not None and abs(row["1m"]) >= SURGE:
            notes.append(f"{row['1m']*100:+.0f}% in a month")
        # Up hard recently AND still far below the high is the specific shape
        # that reads as a recovery rather than as either one alone.
        if (row["1m"] or 0) >= SURGE and (row["from_peak"] or 0) <= -GIVEBACK:
            notes.append("rising off a deep drawdown")
        row["notes"] = notes
        row["notable"] = bool(notes)
        out.append(row)

    # Most dollars handed back first: that is the row most worth looking at,
    # and it is the question the book could not previously answer at all.
    out.sort(key=lambda r: (-(r["given_back_usd"] or 0),
                            r["from_peak"] if r["from_peak"] is not None else 0))
    return out


def _year_before(end: str) -> str:
    y, m, d = (int(x) for x in end[:10].split("-"))
    return f"{y-1:04d}-{m:02d}-{d:02d}"
