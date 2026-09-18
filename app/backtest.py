"""Walk-forward backtesting for encoded methods.

The single thing that makes a backtest worth anything is that the decision at
each date used only what was knowable at that date. Everything here is arranged
around that: bars are truncated to the decision date before the method ever
sees them, the method is scored on the truncated series, and the resulting
position is entered at the NEXT bar's open rather than the close that produced
the signal. A backtest that scores on a bar and buys at that same bar's close
is buying with information it did not have, and it will look excellent.

Two honesty problems cannot be engineered away and are therefore reported
rather than hidden:

  * Survivorship. The universe is a watchlist assembled today, so it already
    knows which companies still exist and which names were worth adding. Every
    result is biased upward by an unknown amount. The only real fix is a
    point-in-time universe, which no free source provides.

  * Costs. Commission-free does not mean frictionless. A spread and slippage
    allowance is applied per trade, defaulting deliberately to a level that
    hurts, because the alternative is a curve that assumes free execution in
    names trading at $0.31.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import indicators as I, methods, prices, risk

DEFAULT_COST_BPS = 25          # 0.25% per side — spread plus slippage
DEFAULT_MAX_POSITIONS = 10
DEFAULT_THRESHOLD = 0.75


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def rebalance_dates(bars_by_symbol: dict, start: str, end: str, timeframe: str) -> list[str]:
    """Trading dates on which a decision is made, from the calendar we actually have."""
    every: set[str] = set()
    for bars in bars_by_symbol.values():
        every |= {b["time"] for b in bars}
    days = sorted(d for d in every if start <= d <= end)
    if not days:
        return []
    if timeframe == "D":
        return days

    out, seen = [], set()
    for d in days:
        y, m, dd = (int(x) for x in d.split("-"))
        if timeframe == "M":
            key = (y, m)
        else:
            iso = date(y, m, dd).isocalendar()
            key = (iso[0], iso[1])
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _bars_before(bars: list[dict], asof: str) -> list[dict]:
    """Only what was knowable at `asof`. The whole backtest rests on this."""
    return [b for b in bars if b["time"] <= asof]


def _next_open(bars: list[dict], after: str) -> tuple[str, float] | None:
    """The first bar strictly after the decision date — where the fill happens."""
    for b in bars:
        if b["time"] > after:
            return b["time"], b["open"] or b["close"]
    return None


def run(conn, method_key: str, symbols: list[str], start: str, end: str,
        threshold: float = DEFAULT_THRESHOLD,
        max_positions: int = DEFAULT_MAX_POSITIONS,
        cost_bps: int = DEFAULT_COST_BPS,
        starting_cash: float = 100_000.0) -> dict:
    spec = methods.METHODS.get(method_key)
    if not spec:
        return {"error": f"unknown method {method_key}"}

    daily = {}
    for s in symbols:
        b = prices.load_bars(conn, s, "2010-01-01", end)
        if len(b) > 260:
            daily[s] = b
    if not daily:
        return {"error": "no symbols with enough history"}

    tf = spec["timeframe"]
    resampled = {s: I.resample(b, tf) for s, b in daily.items()}
    dates = rebalance_dates(resampled, start, end, tf)
    if len(dates) < 4:
        return {"error": f"only {len(dates)} rebalance dates in range"}

    # The benchmark the momentum method measures relative strength against.
    # Without it `outperforming` — 2 of 9 weight, and the only thing making the
    # method RELATIVE — abstained at every rebalance, so the backtest scored a
    # different method than the live scanner does.
    bench_all = []
    resolved = prices.resolve_benchmark("SPY")
    if resolved:
        bench_all = prices.load_bars(conn, resolved[0], "2010-01-01", end)
    if not bench_all:
        bench_all = prices.load_bars(conn, "SPY", "2010-01-01", end)

    # Resampled ONCE. Truncating the resampled series per date is cheap; doing
    # the resample per symbol per date is not.
    bench_tf = I.resample(bench_all, tf) if bench_all else []

    cash = starting_cash
    holdings: dict[str, float] = {}          # symbol -> shares
    equity, trades = [], []
    cost = cost_bps / 10_000.0

    for i, dt in enumerate(dates):
        # ---- score using only data up to and including this date ----------
        # TRUNCATED like everything else. Handing evaluate() the full benchmark
        # series would leak future index levels into a past decision — the exact
        # look-ahead this loop exists to prevent.
        bench_visible = _bars_before(bench_tf, dt)
        scores = []
        for s, bars in resampled.items():
            visible = _bars_before(bars, dt)
            if len(visible) < 24:
                continue
            r = methods.evaluate(visible, method_key,
                                 benchmark_resampled=bench_visible)
            if r.get("insufficient") or r.get("error"):
                continue
            # The same coverage floor the live scanner applies. Without it a
            # name clears the threshold on whatever fraction of the method
            # happened to be computable at that date.
            if r["pct"] >= threshold and r.get("coverage", 1.0) >= 0.6:
                scores.append((r["pct"], s))
        # Sorted by score, then by symbol so equal scores break the same way
        # every run. The RANK has to survive: `wanted` used to be a set, which
        # discarded it, and since a starved entry gets whatever cash is left,
        # which names actually got funded depended on set iteration order — the
        # same backtest returned different results under different hash seeds.
        scores.sort(key=lambda ps: (-ps[0], ps[1]))
        ranked = [s for _p, s in scores[:max_positions]]
        wanted = set(ranked)

        # ---- mark the book, using this date's close ------------------------
        def price_at(sym: str, when: str) -> float | None:
            vis = _bars_before(resampled[sym], when)
            return vis[-1]["close"] if vis else None

        value = cash + sum(sh * (price_at(s, dt) or 0) for s, sh in holdings.items())
        equity.append({"date": dt, "value": round(value, 2),
                       "positions": len(holdings), "candidates": len(scores)})

        if i == len(dates) - 1:
            break

        # ---- trade at the NEXT bar's open ---------------------------------
        exits = sorted(s for s in holdings if s not in wanted)
        for s in exits:
            nxt = _next_open(resampled[s], dt)
            if not nxt:
                continue
            fill_date, px = nxt
            proceeds = holdings[s] * px * (1 - cost)
            cash += proceeds
            trades.append({"date": fill_date, "symbol": s, "side": "sell",
                           "shares": round(holdings[s], 4), "price": round(px, 4)})
            del holdings[s]

        # Best score first, so when cash runs out it is the weakest candidate
        # that goes unfunded rather than an arbitrary one.
        entries = [s for s in ranked if s not in holdings]
        if entries:
            # Equal weight across the target book, sized off current equity.
            target = (cash + sum(sh * (price_at(s, dt) or 0) for s, sh in holdings.items()))
            per = target / max(len(wanted), 1)
            for s in entries:
                nxt = _next_open(resampled[s], dt)
                if not nxt:
                    continue
                fill_date, px = nxt
                if px <= 0:
                    continue
                spend = min(per, cash)
                if spend < 1:
                    continue
                shares = (spend * (1 - cost)) / px
                cash -= spend
                holdings[s] = holdings.get(s, 0) + shares
                trades.append({"date": fill_date, "symbol": s, "side": "buy",
                               "shares": round(shares, 4), "price": round(px, 4)})

    # ---- benchmark on the same dates, same starting cash ------------------
    bench_series = prices.load_series(conn, "SPY")
    bench_dates = prices.sorted_dates(conn, "SPY")
    bench = []
    if bench_series and bench_dates:
        from .performance import last_known_price
        p0 = last_known_price(bench_series, dates[0], bench_dates)
        for e in equity:
            p = last_known_price(bench_series, e["date"], bench_dates)
            bench.append({"date": e["date"],
                          "value": round(starting_cash * p / p0, 2) if p and p0 else None})

    values = [e["value"] for e in equity]
    total = (values[-1] / values[0] - 1) if values and values[0] else None
    years = max((_d(dates[-1]) - _d(dates[0])).days / 365.25, 1e-9)
    cagr = ((values[-1] / values[0]) ** (1 / years) - 1) if values and values[0] > 0 else None

    peak, max_dd = values[0] if values else 0, 0.0
    for v in values:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1 if peak else 0)

    rets = [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1]]
    per_year = len(rets) / years if years else 0
    import math
    mean = sum(rets) / len(rets) if rets else 0
    sd = (math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
          if len(rets) > 1 else 0)
    # Excess over cash, not raw return over volatility. Omitting the risk-free
    # rate inflates the ratio by rf/sigma, which over a period when cash paid
    # 4-5% is not a rounding difference.
    rf = risk.risk_free_rate(conn, dates[0], dates[-1]) if len(dates) > 1 else None
    rf_known = rf is not None
    rf = rf or 0.0
    sharpe = (((mean * per_year - rf) / (sd * math.sqrt(per_year)))
              if sd > 1e-12 else None)

    bench_total = ((bench[-1]["value"] / bench[0]["value"] - 1)
                   if bench and bench[0]["value"] and bench[-1]["value"] else None)

    return {
        "method": method_key, "name": spec["name"], "timeframe": tf,
        "start": dates[0], "end": dates[-1], "rebalances": len(dates),
        "universe": len(daily), "threshold": threshold,
        "max_positions": max_positions, "cost_bps": cost_bps,
        "starting_cash": starting_cash, "final_value": values[-1] if values else None,
        "total_return": total, "cagr": cagr, "max_drawdown": max_dd, "sharpe": sharpe,
        "risk_free_rate": round(rf, 4),
        "benchmark_total": bench_total,
        "excess": (total - bench_total) if (total is not None and bench_total is not None) else None,
        "trades": len(trades), "turnover_per_rebalance": len(trades) / max(len(dates), 1),
        "equity": equity, "bench": bench, "trade_log": trades[-40:],
        "caveats": [
            "Survivorship: the universe is a watchlist assembled today, so it already knows "
            "which names were worth adding and which companies still exist. Results are "
            "biased upward by an unknown amount.",
            f"Costs modelled at {cost_bps} bps per side, applied to every fill.",
            "Fills are at the next bar's open after the signal, never the bar that produced it.",
            "No dividends, no borrow costs, no taxes, no position limits by liquidity.",
            "One universe and one period is a single sample, not evidence of an edge.",
        "The benchmark is a FRED price index and excludes dividends — roughly "
        "1.3%/yr for the S&P — so any excess over it is overstated by about that "
        "much. Disclosed here rather than only in the price module.",
        ("Sharpe is excess over the 3-month Treasury, not raw return over "
         "volatility.") if rf_known else
        ("Sharpe here assumes a ZERO risk-free rate — the 3-month Treasury "
         "series is not cached, so it could not be subtracted. The ratio is "
         "flattered by roughly rf/sigma."),
        ],
    }


# A universe that cannot flatter a method: sector funds do not get delisted,
# do not get added to a watchlist because they already ran, and existed for the
# whole period. Any edge that survives here is more likely to be real.
NEUTRAL_UNIVERSE = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB",
                    "XLU", "XLRE", "XLC", "SPY", "QQQ", "IWM"]


def with_control(conn, method_key: str, symbols: list[str], start: str, end: str,
                 **kw) -> dict:
    """Run a method on the chosen universe AND on a survivorship-free control.

    This exists because the first backtest of the momentum method returned
    +398% against the S&P's +123% on the user's own watchlist, and -4.0% on a
    neutral universe of sector ETFs over the identical period. A four-hundred
    point swing from changing nothing but the universe.

    That gap is not a detail to mention in a footnote — it IS the finding. A
    watchlist assembled today is a list of names that worked, so a method that
    buys strength will appear to have an edge it does not have. Reporting the
    headline number alone would have been actively misleading, so both are
    always computed and the difference is stated.
    """
    live = run(conn, method_key, symbols, start, end, **kw)
    for s in NEUTRAL_UNIVERSE:
        prices.ensure_symbol(conn, s, "2015-01-01", end, as_equity=True)
    conn.commit()
    control_kw = {**kw, "max_positions": min(kw.get("max_positions", DEFAULT_MAX_POSITIONS), 4)}
    control = run(conn, method_key, NEUTRAL_UNIVERSE, start, end, **control_kw)

    gap = None
    if live.get("excess") is not None and control.get("excess") is not None:
        gap = live["excess"] - control["excess"]

    verdict = None
    if gap is not None:
        if control.get("excess", 0) > 0.05:
            verdict = ("The method beats the benchmark on a survivorship-free universe too, "
                       "which is the version of the result worth taking seriously.")
        elif live.get("excess", 0) > 0.05:
            verdict = ("The method only beats the benchmark on the hand-picked universe. "
                       "On names that could not have been chosen with hindsight it does not, "
                       "so what the first number measured was largely the watchlist.")
        else:
            verdict = "The method beats the benchmark on neither universe."

    return {"live": live, "control": control, "universe_gap": gap, "verdict": verdict}
