"""Current holdings, cost basis, and per-position return attribution.

Cost basis is tracked with FIFO tax lots rather than a running average, because
average cost cannot answer the questions that actually matter later — which
specific shares a sale consumed, how long they were held, and therefore whether
a gain is short or long term. Building lots now means wash-sale detection and
tax-lot reporting are additions rather than rewrites.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import cash, performance, prices

# Kinds that add or remove shares at a known price.
ACQUIRE = {"buy", "reinvest", "exchange_in"}
DISPOSE = {"sell", "exchange_out"}
LONG_TERM_DAYS = 366


class Lot:
    __slots__ = ("date", "qty", "price")

    def __init__(self, d: str, qty: float, price: float):
        self.date, self.qty, self.price = d, qty, price


# "R/S FROM 862945102#REOR ..." on the incoming leg names the security the
# shares came out of, which is what lets the two legs be paired.
_REOR_FROM = re.compile(r"R/S\s+FROM\s+(\w+)", re.I)


def reorganisations(txns: list[dict]) -> dict[tuple[str, str], str]:
    """Pair the two legs of a share-for-share reorganisation.

    Returns {(date, incoming_symbol): outgoing_symbol}.

    A reverse split is not a sale. Fidelity reports it as two corporate actions
    — shares out of the old identifier, shares into the new one — and each leg
    carries its own stated per-share price. Those prices do not reconcile: on the
    real 1-for-20 here, 26,149.378 shares left at $0.4931 ($12,894 of basis) and
    1,306 arrived at $11.9150 ($15,561), conjuring $2,667 of basis from nothing
    and booking a $22,523 realised loss on a non-taxable event.
    """
    by_date: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    refs: dict[tuple[str, str], str] = {}
    for t in txns:
        if t["kind"] != "corporate_action" or not t.get("quantity"):
            continue
        by_date[t["txn_date"]][t["symbol"]] += t["quantity"]
        m = _REOR_FROM.search(t.get("description") or "")
        if m and t["quantity"] > 0:
            refs[(t["txn_date"], t["symbol"])] = m.group(1)

    pairs: dict[tuple[str, str], str] = {}
    for day, moves in by_date.items():
        outs = [s for s, q in moves.items() if q < 0]
        ins = [s for s, q in moves.items() if q > 0]
        for sym in ins:
            ref = refs.get((day, sym))
            # Prefer the identifier the statement itself names; fall back to an
            # unambiguous single pairing on the day. Anything less certain is
            # left alone rather than guessed at.
            match = next((o for o in outs if ref and ref in o), None)
            if match is None and len(outs) == 1 and len(ins) == 1:
                match = outs[0]
            if match:
                pairs[(day, sym)] = match
    return pairs


def apply_reorganisations(txns: list[dict]) -> list[dict]:
    """Rewrite history so a share-for-share exchange reads as one position.

    The old identifier's transactions are restated in the new one at
    split-adjusted terms — quantity scaled by the ratio, price scaled inversely —
    and both reorganisation legs are dropped. Cash amounts are unchanged, since
    (q x r) x (p / r) is q x p, so realised results from before the split survive
    exactly while basis, share counts and holding periods all stay coherent.

    Doing it here, once, means every consumer agrees. Handling it only inside the
    lot builder left position_trades still reading the two legs as a real sale
    and a real purchase, which is how a non-taxable 1-for-20 became a $22,523
    realised loss that dominated the entire trade record.
    """
    pairs = reorganisations(txns)
    if not pairs:
        return txns

    totals: dict[tuple[str, str], float] = defaultdict(float)
    for t in txns:
        if t["kind"] == "corporate_action" and t.get("quantity"):
            totals[(t["txn_date"], t["symbol"])] += t["quantity"]

    plan = {}
    for (day, dst), src in pairs.items():
        out_qty = -totals.get((day, src), 0.0)
        in_qty = totals.get((day, dst), 0.0)
        if out_qty > 0 and in_qty > 0:
            plan[(day, src)] = (dst, in_qty / out_qty)

    out = []
    for t in txns:
        moves = [(d, r) for (day, src), (d, r) in plan.items()
                 if src == t["symbol"] and t["txn_date"] <= day]
        if moves:
            dst, ratio = moves[0]
            if t["kind"] == "corporate_action":
                continue                      # the outgoing leg itself
            row = dict(t)
            row["symbol"] = dst
            if row.get("quantity"):
                row["quantity"] = row["quantity"] * ratio
            if row.get("price"):
                row["price"] = row["price"] / ratio
            out.append(row)
            continue
        if any(t["txn_date"] == day and t["symbol"] == dst
               and t["kind"] == "corporate_action"
               for (day, _s), (dst, _r) in plan.items()):
            continue                          # the incoming leg itself
        out.append(t)
    return out


def build_lots(txns: list[dict], asof: str) -> tuple[dict[str, list[Lot]], dict[str, dict]]:
    """Walk the ledger once, maintaining FIFO lots per symbol.

    Returns (open lots by symbol, realised summary by symbol).
    """
    lots: dict[str, list[Lot]] = defaultdict(list)
    realised: dict[str, dict] = defaultdict(lambda: {"proceeds": 0.0, "cost": 0.0, "qty": 0.0})

    txns = apply_reorganisations(txns)

    for t in sorted(txns, key=lambda x: x["txn_date"]):
        if t["txn_date"] > asof or not t["symbol"] or not t["quantity"]:
            continue
        sym, qty, kind = t["symbol"], t["quantity"], t["kind"]
        price = t.get("price")

        if kind in ACQUIRE or (kind == "corporate_action" and qty > 0):
            # A corporate action with no price is a share transfer; carry basis
            # forward at zero rather than inventing a number.
            lots[sym].append(Lot(t["txn_date"], qty, price if price else 0.0))
        elif kind in DISPOSE or (kind == "corporate_action" and qty < 0):
            remaining = -qty
            proceeds_price = price if price else 0.0
            while remaining > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                take = min(lot.qty, remaining)
                realised[sym]["proceeds"] += take * proceeds_price
                realised[sym]["cost"] += take * lot.price
                realised[sym]["qty"] += take
                lot.qty -= take
                remaining -= take
                if lot.qty <= 1e-9:
                    lots[sym].pop(0)
            # Shares sold that we never saw bought (history starts mid-position)
            # are ignored rather than booked as free profit.

    return {s: [l for l in ls if l.qty > 1e-9] for s, ls in lots.items()}, dict(realised)


def positions(conn, txns: list[dict], asof: str, prior: str | None = None) -> list[dict]:
    """Open positions with market value, cost basis and unrealised P/L.

    The basis is FIFO unless the broker's own figure has been imported for that
    symbol and the share counts agree — see `broker_basis`. Every position says
    which one it is carrying in `basis_source`, because a number that changes
    meaning depending on whether somebody imported a file is worse than one that
    is merely wrong.
    """
    lots, _realised = build_lots(txns, asof)
    # The core funds are cash, and their share count in this ledger is only the
    # reinvested interest — the sweep of the principal is never exported. Taking
    # the balance from the cash flows instead is the difference between showing
    # $842 of core and the ~$11,700 actually there.
    core = cash.by_fund(txns, asof, cash.anchors(conn))
    out = []
    for symbol, syms in lots.items():
        qty = sum(l.qty for l in syms)
        # Dust is not a position. A stock dividend of 0.0147 shares sold as
        # 0.014679 leaves 0.000021 of UNH worth a cent, and it was listed as a
        # holding on the Sectors tab a year after the last real share went.
        if abs(qty) < 0.0005:
            continue
        cost = sum(l.qty * l.price for l in syms)
        if prices.is_money_market(symbol) and symbol.strip().upper() in core:
            qty = core[symbol.strip().upper()]
            # Cash has no cost basis apart from its face value, so the position
            # must never show a gain or a loss on it.
            cost = qty * prices.MONEY_MARKET_NAV
        if abs(qty) < 1e-9:
            continue

        series = prices.load_series(conn, symbol)
        dates = prices.sorted_dates(conn, symbol)
        if prices.is_money_market(symbol):
            px, px_prior, basis = prices.MONEY_MARKET_NAV, prices.MONEY_MARKET_NAV, "nav"
        else:
            px = performance.last_known_price(series, asof, dates) if series else None
            basis = "market"
            if px is None:
                px = performance.last_traded_price(txns, symbol, asof)
                basis = "last traded" if px is not None else "none"
            px_prior = (performance.last_known_price(series, prior, dates)
                        if prior and series else None)

        value = qty * px if px is not None else None
        oldest = min(l.date for l in syms)
        held_days = (datetime.strptime(asof, "%Y-%m-%d") - datetime.strptime(oldest, "%Y-%m-%d")).days

        out.append({
            "symbol": symbol,
            "quantity": round(qty, 4),
            "avg_cost": round(cost / qty, 4) if qty else None,
            "cost_basis": round(cost, 2),
            "price": round(px, 4) if px is not None else None,
            "price_basis": basis,
            "value": round(value, 2) if value is not None else None,
            "unrealised": round(value - cost, 2) if value is not None else None,
            "unrealised_pct": ((value - cost) / cost) if value is not None and abs(cost) > 1e-9 else None,
            "period_change": (round(qty * (px - px_prior), 2)
                              if px is not None and px_prior is not None else None),
            "lots": len(syms),
            "oldest_lot": oldest,
            "held_days": held_days,
            "long_term": held_days >= LONG_TERM_DAYS,
        })

    # Cash in an account that has NEVER traded a money-market fund has no core
    # fund to be reported under, so by_fund has nowhere to put it and it simply
    # vanished from this list. That is not a rounding difference: the L3Harris
    # plan holds $2,881.02 of it, which is why the Holdings tab and the Overview
    # card disagreed by exactly that much while each looked internally
    # consistent. Unswept cash gets a row of its own rather than being dropped.
    accounted = set(core)
    stray = 0.0
    for acct, row in cash.balances(txns, asof, cash.anchors(conn)).items():
        fund = next((f for a, f in _core_fund_of(txns, asof).items() if a == acct), None)
        if fund and fund in accounted:
            continue
        stray += row["balance"]
    if abs(stray) > 0.005:
        out.append({
            "symbol": "CASH", "quantity": round(stray, 2),
            "avg_cost": 1.0, "cost_basis": round(stray, 2),
            "price": 1.0, "price_basis": "nav",
            "value": round(stray, 2),
            # Cash cannot show a gain against itself.
            "unrealised": 0.0, "unrealised_pct": None, "period_change": None,
            "lots": 0, "oldest_lot": asof, "held_days": 0, "long_term": False,
        })

    total = sum(p["value"] or 0.0 for p in out)
    for p in out:
        p["weight"] = (p["value"] / total) if p["value"] and total else 0.0
    out.sort(key=lambda p: -(p["value"] or 0))
    # The broker's basis wins where it exists and the share counts agree. FIFO
    # is a guess about which lots were sold; the statement is the fact.
    from . import broker_basis
    try:
        out = broker_basis.apply_to(out, broker_basis.lookup(conn))
    except Exception:                                          # noqa: BLE001
        for p in out:
            p.setdefault("basis_source", "fifo")

    return out


def _core_fund_of(txns, asof: str | None) -> dict[str, str]:
    """Each account's current core fund, or absent if it has never had one."""
    seen: dict[str, tuple[str, str]] = {}
    for t in txns:
        if not prices.is_money_market(t.get("symbol")):
            continue
        acct, day = t.get("account") or "(unassigned)", (t.get("txn_date") or "")[:10]
        if asof and day > asof:
            continue
        if acct not in seen or day >= seen[acct][1]:
            seen[acct] = (t["symbol"].strip().upper(), day)
    return {a: f for a, (f, _d) in seen.items()}


def realised(conn, txns: list[dict], start: str, end: str) -> list[dict]:
    """Closed-position gains between two dates, FIFO-matched."""
    _open_start, before = build_lots(txns, start)
    _open_end, through = build_lots(txns, end)
    out = []
    for symbol, tot in through.items():
        prev = before.get(symbol, {"proceeds": 0.0, "cost": 0.0, "qty": 0.0})
        proceeds = tot["proceeds"] - prev["proceeds"]
        cost = tot["cost"] - prev["cost"]
        qty = tot["qty"] - prev["qty"]
        if abs(qty) < 1e-9 and abs(proceeds) < 0.01:
            continue
        out.append({"symbol": symbol, "quantity": round(qty, 4),
                    "proceeds": round(proceeds, 2), "cost": round(cost, 2),
                    "gain": round(proceeds - cost, 2),
                    "gain_pct": ((proceeds - cost) / cost) if abs(cost) > 1e-9 else None})
    out.sort(key=lambda r: -r["gain"])
    return out


def closed_trades(txns: list[dict], start: str, end: str) -> list[dict]:
    """Every FIFO lot closed in the period, as an individual round trip.

    A "trade" here is one lot matched to one disposal, not a whole position.
    That is deliberate: scaling into a name over four buys and out over two
    sells is six decisions, and collapsing them into one row hides which of
    them worked. Each row therefore carries its own entry date, exit date,
    holding period and result.
    """
    lots: dict[str, list[Lot]] = defaultdict(list)
    trades: list[dict] = []

    for t in sorted(txns, key=lambda x: x["txn_date"]):
        if t["txn_date"] > end or not t["symbol"] or not t["quantity"]:
            continue
        sym, qty, kind, price = t["symbol"], t["quantity"], t["kind"], t.get("price")

        if kind in ACQUIRE or (kind == "corporate_action" and qty > 0):
            lots[sym].append(Lot(t["txn_date"], qty, price if price else 0.0))
        elif kind in DISPOSE or (kind == "corporate_action" and qty < 0):
            remaining, exit_price = -qty, (price if price else 0.0)
            while remaining > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                take = min(lot.qty, remaining)
                if t["txn_date"] >= start and lot.price > 0 and exit_price > 0:
                    cost, proceeds = take * lot.price, take * exit_price
                    held = (datetime.strptime(t["txn_date"], "%Y-%m-%d")
                            - datetime.strptime(lot.date, "%Y-%m-%d")).days
                    trades.append({
                        "symbol": sym, "quantity": round(take, 4),
                        "entry_date": lot.date, "exit_date": t["txn_date"],
                        "entry_price": round(lot.price, 4), "exit_price": round(exit_price, 4),
                        "cost": round(cost, 2), "proceeds": round(proceeds, 2),
                        "pnl": round(proceeds - cost, 2),
                        "pnl_pct": (proceeds - cost) / cost,
                        "held_days": held,
                        "win": proceeds > cost,
                    })
                lot.qty -= take
                remaining -= take
                if lot.qty <= 1e-9:
                    lots[sym].pop(0)
    trades.sort(key=lambda t: t["exit_date"], reverse=True)
    return trades


def position_trades(txns: list[dict], end: str) -> list[dict]:
    """Full round trips at the POSITION level: flat -> in -> flat.

    The lot-level view above splits a single idea into one row per partial fill,
    which is right for cost basis and wrong for judging decisions — scaling into
    a name over eight fills is one trade, not eight. This walks each symbol and
    opens a trade when the position leaves zero, closing it when it returns.
    Positions still open are returned with `open: True` and marked to market by
    the caller.
    """
    events: dict[str, list[dict]] = defaultdict(list)
    for t in sorted(apply_reorganisations(txns), key=lambda x: x["txn_date"]):
        if t["txn_date"] > end or not t["symbol"] or not t["quantity"]:
            continue
        if t["kind"] in ACQUIRE | DISPOSE or t["kind"] == "corporate_action":
            events[t["symbol"]].append(t)

    out = []
    for symbol, evs in events.items():
        qty = 0.0
        cur = None
        for t in evs:
            if abs(qty) < 1e-9 and cur is None:
                cur = {"symbol": symbol, "entry_date": t["txn_date"], "bought": 0.0,
                       "sold": 0.0, "shares_in": 0.0, "shares_out": 0.0, "fills": 0}
            if cur is None:
                continue
            q, px = t["quantity"], (t.get("price") or 0.0)
            cur["fills"] += 1
            if q > 0:
                cur["bought"] += q * px
                cur["shares_in"] += q
            else:
                cur["sold"] += -q * px
                cur["shares_out"] += -q
            qty += q
            if abs(qty) < 1e-6:                     # back to flat: trade closed
                cur["exit_date"] = t["txn_date"]
                cur["pnl"] = round(cur["sold"] - cur["bought"], 2)
                cur["pnl_pct"] = ((cur["sold"] - cur["bought"]) / cur["bought"]
                                  if cur["bought"] > 1e-9 else None)
                cur["held_days"] = (datetime.strptime(cur["exit_date"], "%Y-%m-%d")
                                    - datetime.strptime(cur["entry_date"], "%Y-%m-%d")).days
                cur["win"] = cur["sold"] > cur["bought"]
                cur["open"] = False
                cur["bought"] = round(cur["bought"], 2)
                cur["sold"] = round(cur["sold"], 2)
                out.append(cur)
                cur = None
        if cur is not None:                          # still open at `end`
            cur.update({"exit_date": None, "open": True, "remaining": round(qty, 4),
                        "bought": round(cur["bought"], 2), "sold": round(cur["sold"], 2),
                        "held_days": (datetime.strptime(end, "%Y-%m-%d")
                                      - datetime.strptime(cur["entry_date"], "%Y-%m-%d")).days})
            out.append(cur)
    out.sort(key=lambda t: (t["exit_date"] or "9999", t["entry_date"]), reverse=True)
    return out


def trade_stats(trades: list[dict]) -> dict:
    """Win rate, expectancy and profit factor over closed round trips.

    Profit factor (gross wins / gross losses) is the headline rather than win
    rate, because win rate alone is easy to game: a strategy that takes many
    tiny wins and a few catastrophic losses looks excellent by win rate and
    loses money. Anything above 1.0 is profitable; below 1.0 is not.
    """
    trades = [t for t in trades if not t.get("open")]
    if not trades:
        return {"count": 0}
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    net = gross_win - gross_loss
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    return {
        "count": len(trades),
        "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(trades),
        "gross_win": round(gross_win, 2), "gross_loss": round(gross_loss, 2),
        "net": round(net, 2),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        # How many dollars won per dollar lost. The single most honest number here.
        "profit_factor": (gross_win / gross_loss) if gross_loss > 1e-9 else None,
        # Average dollars per trade taken. Negative means the edge is negative
        # regardless of how good the win rate looks.
        "expectancy": round(net / len(trades), 2),
        "payoff_ratio": (avg_win / avg_loss) if avg_loss > 1e-9 else None,
        "avg_win_days": round(sum(t["held_days"] for t in wins) / len(wins)) if wins else None,
        "avg_loss_days": round(sum(t["held_days"] for t in losses) / len(losses)) if losses else None,
        "best": max(trades, key=lambda t: t["pnl"]),
        "worst": min(trades, key=lambda t: t["pnl"]),
    }


def excursions(conn, trips: list[dict]) -> list[dict]:
    """How far each trade went against you, and for you, while it was open.

    Maximum adverse and favourable excursion. The realised result says where a
    trade ENDED; these say what it did on the way, which is the part that
    decides whether you could actually sit through it. A winner that spent a
    month 40% underwater and a winner that never dipped are the same row in a
    P/L table and are not remotely the same trade.

    Measured against the average entry price, using the extreme of each bar
    rather than closes — a stop is hit by the low, not by the close.
    """
    for t in trips:
        t["mae"] = t["mfe"] = t["mae_pct"] = t["mfe_pct"] = None
        shares = t.get("shares_in") or 0
        entry = (t["bought"] / shares) if shares else None
        if not entry:
            continue
        last = t.get("exit_date") or max(b["time"] for b in [{"time": t["entry_date"]}])
        bars = prices.load_bars(conn, t["symbol"], t["entry_date"], last)
        if not bars:
            continue
        low = min(b["low"] for b in bars)
        high = max(b["high"] for b in bars)
        # Bars are split-adjusted; the price you paid is not. Reconcile before
        # comparing, or a 20-for-1 split reads as a 95% drawdown.
        factor = prices.adjustment_factor(conn, t["symbol"], t["entry_date"], entry)
        adj_entry = entry / factor
        adj_shares = shares * factor
        t["entry_avg"] = round(entry, 4)
        t["split_adjusted"] = factor != 1.0
        t["mae_pct"] = round(low / adj_entry - 1.0, 6)
        t["mfe_pct"] = round(high / adj_entry - 1.0, 6)
        t["mae"] = round((low - adj_entry) * adj_shares, 2)
        t["mfe"] = round((high - adj_entry) * adj_shares, 2)
    return trips


def by_symbol(trades: list[dict]) -> list[dict]:
    """Per-symbol trade record — which names you actually trade well."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        groups[t["symbol"]].append(t)
    rows = []
    for sym, ts in groups.items():
        wins = [t for t in ts if t["win"]]
        rows.append({"symbol": sym, "trades": len(ts), "wins": len(wins),
                     "win_rate": len(wins) / len(ts),
                     "pnl": round(sum(t["pnl"] for t in ts), 2),
                     "avg_days": round(sum(t["held_days"] for t in ts) / len(ts))})
    rows.sort(key=lambda r: -r["pnl"])
    return rows


def attribution(conn, txns: list[dict], start: str, end: str) -> list[dict]:
    """How much of the period's dollar gain each symbol produced.

    Dollar contribution, not percentage: a 300% move on a $200 position did not
    drive the portfolio, and a table sorted by percentage would say it did.
    """
    open_start, _ = build_lots(txns, start)
    open_end, _ = build_lots(txns, end)
    real = {r["symbol"]: r for r in realised(conn, txns, start, end)}

    symbols = set(open_start) | set(open_end) | set(real)
    rows = []
    for symbol in symbols:
        def mv(lots_map, asof):
            ls = lots_map.get(symbol) or []
            qty = sum(l.qty for l in ls)
            if abs(qty) < 1e-9:
                return 0.0, 0.0
            series = prices.load_series(conn, symbol)
            if prices.is_money_market(symbol):
                px = prices.MONEY_MARKET_NAV
            else:
                px = (performance.last_known_price(series, asof, prices.sorted_dates(conn, symbol))
                      if series else None) or performance.last_traded_price(txns, symbol, asof)
            cost = sum(l.qty * l.price for l in ls)
            return (qty * px if px else 0.0), cost

        v0, c0 = mv(open_start, start)
        v1, c1 = mv(open_end, end)
        unreal_change = (v1 - c1) - (v0 - c0)
        realised_gain = real.get(symbol, {}).get("gain", 0.0)
        contribution = unreal_change + realised_gain
        if abs(contribution) < 0.01:
            continue
        rows.append({"symbol": symbol, "unrealised_change": round(unreal_change, 2),
                     "realised": round(realised_gain, 2),
                     "contribution": round(contribution, 2)})
    rows.sort(key=lambda r: -r["contribution"])
    return rows
