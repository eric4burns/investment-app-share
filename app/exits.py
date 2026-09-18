"""Would any mechanical exit rule have gotten out sooner than holding did?

This answers a question the app could not: a position 68% below its own high
was still shown as a large gain on cost, and nothing said whether anything
visible on the chart would have flagged the turn.

## What this is, and what it is emphatically not

Each rule is replayed bar by bar over real history with **no lookahead**: the
decision at bar `i` uses only bars up to and including `i`, and the exit is
booked at that bar's close. A rule that peeks at tomorrow will always look
brilliant, which is the single easiest way to build a backtest that lies.

The harder honesty problem is the sample. Running one rule against one holding
that happened to collapse proves nothing — some rule always fits one path, and
picking the rule that fits it afterwards is the definition of curve-fitting. So
every rule is scored against **every** position, and the summary reports how
often it helped as well as by how much. A rule that saved 40% on one name and
cost 15% on eight others is a worse rule, and the aggregate is what says so.

Even then: fourteen positions from one investor over about two years is a tiny,
correlated sample from a single market regime. It is enough to notice that a
rule would or would not have helped **here**. It is not enough to conclude the
rule works, and this module says so rather than implying otherwise.

## What "better" means

Exiting is compared against still holding at the last price. A rule that exits
above today's price helped; below it, the rule cost money. Selling is not
free — no tax, spread or the cost of being wrong and out of a name that then
recovers is modelled, so a small edge here is not an edge at all.
"""
from __future__ import annotations

from . import indicators as I, prices


def _sma(closes: list[float], period: int) -> list[float | None]:
    out, run = [], 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= period:
            run -= closes[i - period]
        out.append(run / period if i >= period - 1 else None)
    return out


def rule_below_sma(bars, period):
    """First close below its own moving average. The plainest trend exit there is."""
    closes = [b["close"] for b in bars]
    avg = _sma(closes, period)
    for i in range(len(bars)):
        if avg[i] is not None and closes[i] < avg[i]:
            return i
    return None


def rule_trailing(bars, pct):
    """First close a given percentage below the highest close seen SO FAR.

    The running peak only ever looks backwards, which is what keeps this honest
    — a trailing stop measured from the eventual peak is not a rule, it is
    hindsight with a number attached.
    """
    peak = None
    for i, b in enumerate(bars):
        peak = b["close"] if peak is None else max(peak, b["close"])
        if b["close"] <= peak * (1 - pct):
            return i
    return None


def rule_below_kijun(bars, kijun=26):
    """First close below the Ichimoku base line — a 'lost the kijun' exit."""
    for i in range(len(bars)):
        if i < kijun - 1:
            continue
        w = bars[i - kijun + 1:i + 1]
        base = (max(b["high"] for b in w) + min(b["low"] for b in w)) / 2
        if bars[i]["close"] < base:
            return i
    return None


def rule_below_cloud(bars, tenkan=9, kijun=26, senkou=52):
    """First close beneath both Ichimoku spans, the cloud having been reclaimed.

    Uses the DISPLACED cloud, matching what is drawn: the spans in force at bar
    i were computed kijun bars earlier. Comparing price against spans computed
    from the same bar would be reading a cloud nobody plots.
    """
    def mid(i, n):
        if i < n - 1:
            return None
        w = bars[i - n + 1:i + 1]
        return (max(b["high"] for b in w) + min(b["low"] for b in w)) / 2

    for i in range(len(bars)):
        src = i - kijun
        if src < 0:
            continue
        t, k, sb = mid(src, tenkan), mid(src, kijun), mid(src, senkou)
        if t is None or k is None or sb is None:
            continue
        if bars[i]["close"] < min((t + k) / 2, sb):
            return i
    return None


# label, replay function, family, and the EARLIEST BAR THE RULE CAN FIRE.
#
# That last column is structural, not observed. A 20-bar average has nothing to
# say until bar 19 and a 50-bar one until bar 49; the displaced cloud needs 52
# bars of range displaced 26 further, so it cannot speak until bar 77. A
# trailing stop needs one bar to have a peak to fall from.
#
# It used to be derived as min(days) — the earliest bar a rule was OBSERVED to
# fire on this particular set of positions — which is a different quantity
# wearing the same name. Three positions where the 20-day rule fired at bars
# 100, 101 and 102 gave a floor of 100 and a median of 101, so the rule was
# flagged as "fires at the earliest bar it can" and greyed out in the dashboard,
# when in fact it had waited a hundred bars. Any rule whose signals clustered
# was accused of firing immediately.
RULES = [
    ("below 20-day average",  lambda b: rule_below_sma(b, 20),   "trend",    19),
    ("below 50-day average",  lambda b: rule_below_sma(b, 50),   "trend",    49),
    ("20% trailing stop",     lambda b: rule_trailing(b, 0.20),  "stop",      1),
    ("30% trailing stop",     lambda b: rule_trailing(b, 0.30),  "stop",      1),
    ("lost the kijun",        lambda b: rule_below_kijun(b),     "ichimoku", 25),
    ("fell out of the cloud", lambda b: rule_below_cloud(b),     "ichimoku", 77),
]


# What happened to names that reached this drawdown before.
#
# Measured 2026-09-10 over the liquid screened universe, 6,376 events across
# 2,787 names: any name closing a given distance below its own 126-day high,
# one event per name per year, counted only where two years of forward data
# exist. `further` is the median ADDITIONAL fall from the break to the eventual
# trough — the number that makes the case, because a break is usually not the
# end of the falling.
#
# These replace a much thinner first pass which required names to have DOUBLED
# before falling. That version had 25 events at -40% and none at all below it,
# so the two deepest positions in the book showed no number. It was also
# optimistic: it put -40% at "36% never recovered, 6.8 months", against 46% and
# 13.2 months here.
#
# One caveat that could not be resolved. The user's names did double first, and
# that subset — 93 events at -20%, 29 at -30%, too thin to publish — looks
# WORSE than the general case: a one-year median of 0.937 against 1.120 at -20%,
# and 0.712 against 1.069 at -30%. So these figures may flatter a position that
# ran hard before it broke, which is exactly the kind this book holds. Reported
# as the best-supported numbers available, not as the right ones for this book.
DRAWDOWN_ODDS = [
    # floor, n, never recovered, median months back, 75th pct, median further fall
    (0.70, 86, 0.63, 22.1, 32.0, -0.66),
    (0.60, 166, 0.56, 15.0, 25.4, -0.65),
    (0.50, 303, 0.50, 14.7, 23.7, -0.57),
    (0.40, 536, 0.46, 13.2, 21.5, -0.52),
    (0.30, 985, 0.36, 12.1, 18.3, -0.42),
    (0.20, 3084, 0.24, 7.0, 15.1, -0.29),
]


def drawdown_reading(bars: list[dict], since: str | None = None) -> dict | None:
    """Where a position sits in its own drawdown, and what usually followed.

    The peak is measured over the position's own life when `since` is given —
    what the holder actually watched it give back — rather than over a fixed
    window. A name bought near the bottom and up fourfold is not "in a
    drawdown" because it slipped under a 126-day high.

    Returns None when there is too little history or the position is at a high.
    """
    if not bars:
        return None
    held = [b for b in bars if not since or b["time"] >= since] or bars
    if len(held) < 20:
        return None
    now = held[-1]["close"]
    peak = max(held, key=lambda b: b["high"])
    if not peak["high"] or now >= peak["high"]:
        return None
    fall = 1 - now / peak["high"]
    sessions_since = len(held) - 1 - held.index(peak)
    out = {"peak": round(peak["high"], 4), "peak_date": peak["time"],
           "now": round(now, 4), "drawdown": round(fall, 4),
           "months_since_peak": round(sessions_since / 21, 1)}
    # The base rates were measured at the moment a name FIRST crossed each
    # depth, so they only describe a position standing at that line now. Two
    # ways to be outside that:
    #
    #   deeper than anything measured — nothing below -40% had enough events to
    #   report, so SIVEF at -74% gets no odds rather than the -40% row, which
    #   would read as "expect another 55% down from here" and is not what was
    #   measured.
    #
    #   already months past the crossing — IREN went under -40% long ago and has
    #   sat there. The remaining odds for a name that has held its level for ten
    #   months are not the odds on the day it broke. `stale` says so and the
    #   display must not present the figures as current.
    deepest = max(o[0] for o in DRAWDOWN_ODDS)
    if fall > deepest + 0.15:
        out["odds_note"] = ("deeper than anything measured — no base rate below "
                            f"-{deepest * 100:.0f}% had enough events to report")
        return out
    odds = next((o for o in DRAWDOWN_ODDS if fall >= o[0]), None)
    if odds:
        floor_, n, never, med, p75, further = odds
        out["odds"] = {"at_least": floor_, "n": n, "never_recovered": never,
                       "median_months_back": med, "p75_months_back": p75,
                       "median_further_fall": further,
                       "stale": out["months_since_peak"] > 6.0}
    return out


def for_position(conn, symbol: str, entry: str, end: str) -> dict | None:
    """Every rule replayed from `entry` for one symbol."""
    bars = prices.load_bars(conn, symbol, "2015-01-01", end)
    # Warm-up matters: a rule needing a 50-bar average cannot be judged on a
    # window barely longer than that, so the history BEFORE entry is loaded and
    # the replay window starts at entry.
    if len(bars) < 80:
        return None
    start_i = next((i for i, b in enumerate(bars) if b["time"] >= entry), None)
    if start_i is None or len(bars) - start_i < 40:
        return None

    held = bars[start_i:]
    now = held[-1]["close"]
    peak = max(held, key=lambda b: b["close"])
    results = []
    for label, fn, family, _floor in RULES:
        i = fn(held)
        if i is None:
            results.append({"rule": label, "family": family, "fired": False})
            continue
        px = held[i]["close"]
        results.append({
            "rule": label, "family": family, "fired": True,
            "date": held[i]["time"], "price": round(px, 4),
            # Positive means the rule exited ABOVE where the position sits now.
            "vs_holding": round(px / now - 1, 4) if now else None,
            # How much of the best available price it captured.
            "of_peak": round(px / peak["close"], 4) if peak["close"] else None,
            "days_after_entry": i,
        })
    return {"symbol": symbol, "entry": entry, "now": round(now, 4),
            "peak": round(peak["close"], 4), "peak_date": peak["time"],
            "bars": len(held), "rules": results}


def summary(conn, positions: list[dict], end: str) -> dict:
    """Every rule against every position, so no single flattering case can carry it."""
    per_symbol, tally = [], {label: [] for label, _f, _fam, _w in RULES}
    for p in positions:
        symbol, entry = p.get("symbol"), p.get("oldest_lot")
        if not symbol or not entry or prices.is_cash_like(symbol):
            continue
        got = for_position(conn, symbol, entry[:10], end)
        if not got:
            continue
        per_symbol.append(got)
        for r in got["rules"]:
            if r.get("fired") and r.get("vs_holding") is not None:
                tally[r["rule"]].append(r["vs_holding"])

    def med(xs):
        s = sorted(xs)
        return s[len(s) // 2] if s else None

    ranked = []
    for label, _fn, family, warmup in RULES:
        vals = tally[label]
        if not vals:
            continue
        fired = [r for p in per_symbol for r in p["rules"]
                 if r["rule"] == label and r.get("fired")]
        days = [r["days_after_entry"] for r in fired]
        peaks = [r["of_peak"] for r in fired if r.get("of_peak") is not None]
        helped = [v for v in vals if v > 0]
        # The earliest bar a rule CAN fire, declared alongside the rule itself
        # rather than inferred from when it happened to fire here. When the
        # median signal sits on that floor, the rule is not catching a turn, it
        # is firing at its first legal opportunity, and any apparent success is
        # a statement about the market these positions were bought into rather
        # than about the rule. That has to be visible, because "helped 9 of 13"
        # reads as skill and here it mostly is not.
        floor = warmup
        ranked.append({
            "rule": label, "family": family, "positions": len(vals),
            "helped": len(helped),
            "help_rate": round(len(helped) / len(vals), 3),
            "median": round(med(vals), 4),
            "mean": round(sum(vals) / len(vals), 4),
            "best": round(max(vals), 4), "worst": round(min(vals), 4),
            # How much of the best price available it actually captured. Far less
            # regime-dependent than "vs holding": in a market where everything
            # fell, exiting early beats holding almost by definition.
            "median_of_peak": round(med(peaks), 4) if peaks else None,
            "median_days": med(days),
            "earliest_possible": floor,
            "fires_immediately": bool(med(days) is not None
                                      and med(days) <= floor + 2),
        })
    # By how often it helped, then by median size. Ordering on the best single
    # outcome would promote exactly the rule that got lucky once.
    ranked.sort(key=lambda r: (-r["help_rate"], -r["median"]))
    return {"rules": ranked, "positions": per_symbol,
            "n_positions": len(per_symbol)}
