"""Technical read of a chart, across timeframes.

Produces observations rather than a verdict. The distinction matters: a single
"BUY" label invites you to stop thinking, while a list of what is actually
visible — where price sits against its averages, whether momentum confirms the
trend, how far the last move stretched from the mean — is something you can
argue with. Every observation carries the numbers behind it.

Multi-timeframe is the point rather than a garnish. Sector rotation is close to
unreadable on a daily chart and obvious on a weekly one, and the most useful
signal in practice is agreement or disagreement BETWEEN timeframes: a daily
oversold bounce inside a weekly downtrend is a very different proposition from
the same bounce inside a weekly uptrend.
"""
from __future__ import annotations

from . import indicators as I

TIMEFRAMES = [("D", "Daily"), ("W", "Weekly"), ("M", "Monthly")]


def _last(series) -> float | None:
    return series[-1]["value"] if series else None


def _slope(series, lookback: int = 5) -> float | None:
    """Percentage change of a series over `lookback` points — is it turning up."""
    if not series or len(series) <= lookback:
        return None
    a, b = series[-lookback - 1]["value"], series[-1]["value"]
    return (b - a) / abs(a) if abs(a) > 1e-12 else None


def swing_levels(bars: list[dict], lookback: int = 60, pivots: int = 3) -> dict:
    """Recent swing highs and lows — the levels price has actually reacted at.

    A pivot is a bar whose high (or low) exceeds its neighbours on both sides,
    which is a crude definition but the one most traders read off a chart by eye.
    """
    from . import structure

    window = bars[-lookback:] if len(bars) > lookback else bars
    # Delegated to structure.pivots, which gets the comparison right: strict on
    # the left, permissive on the right. The version here used >= on BOTH sides,
    # so on any flat stretch every interior bar was nominated as a swing high AND
    # a swing low at once, and three adjacent bars of one plateau were then
    # reported as three separate "levels".
    found = structure.pivots(window, pivots, pivots)
    highs = [{"date": p["time"], "price": p["price"]}
             for p in found if p["kind"] == "high"]
    lows = [{"date": p["time"], "price": p["price"]}
            for p in found if p["kind"] == "low"]
    close = bars[-1]["close"] if bars else None
    def merge(levels, unit):
        """Collapse pivots that sit at effectively the same price.

        Three touches of one level is one level, tested three times — reporting
        it as three separate levels fills the list with the same number and
        crowds out the next real one further away.
        """
        out = []
        for lv in levels:
            near = next((o for o in out if abs(o["price"] - lv["price"]) <= unit), None)
            if near:
                near["touches"] = near.get("touches", 1) + 1
                near["date"] = max(near["date"], lv["date"])
            else:
                out.append({**lv, "touches": 1})
        return out

    from . import structure as _S
    unit = _S.typical_range(window) * 0.5 or (abs(close or 1) * 0.005)
    above = merge(sorted((h for h in highs if h["price"] > (close or 0)),
                         key=lambda x: x["price"]), unit)
    below = merge(sorted((l for l in lows if l["price"] < (close or 0)),
                         key=lambda x: -x["price"]), unit)
    return {"resistance": above[:3], "support": below[:3],
            "swing_highs": highs[-5:], "swing_lows": lows[-5:]}


def analyse_timeframe(bars: list[dict], label: str) -> dict:
    """Everything readable off one timeframe, with the numbers attached."""
    if len(bars) < 30:
        return {"timeframe": label, "insufficient": True, "bars": len(bars)}

    close = bars[-1]["close"]
    sma20, sma50, sma200 = I.sma(bars, 20), I.sma(bars, 50), I.sma(bars, 200)
    rsi = I.rsi(bars, 14)
    macd = I.macd(bars)
    bb = I.bollinger(bars, 20, 2.0)
    atr = I.atr(bars, 14)
    willr = I.williams_r(bars, 14)

    m20, m50, m200 = _last(sma20), _last(sma50), _last(sma200)
    obs, signals = [], []

    # --- trend -------------------------------------------------------------
    # Only judge against averages we actually have. A 200-period average needs
    # 200 bars, which on a weekly chart is four years — reporting "unclear"
    # because a long average is missing describes our data, not the chart.
    available = [(n, m) for n, m in (("20", m20), ("50", m50), ("200", m200)) if m]
    have = len(available)
    above = [n for n, m in available if close > m]
    below = [n for n, m in available if close < m]
    if have < 3:
        obs.append(f"Only the {'/'.join(n for n, _ in available)}-period average"
                   f"{'s are' if have > 1 else ' is'} available on this timeframe "
                   f"({len(bars)} bars); longer averages need more history.")
    if have and len(above) == have:
        trend, score = "uptrend", 2
        obs.append(f"Price is above every available average ({', '.join(above)}) — a clean uptrend.")
    elif have and len(below) == have:
        trend, score = "downtrend", -2
        obs.append(f"Price is below every available average ({', '.join(below)}) — a clean downtrend.")
    elif m200 and close > m200:
        trend, score = "uptrend, stretched", 1
        obs.append(f"Above the 200 but below the {'/'.join(below)} — a pullback inside a longer uptrend.")
    elif m200 and close < m200:
        trend, score = "downtrend, bouncing", -1
        obs.append(f"Below the 200 but above the {'/'.join(above)} — a bounce inside a longer downtrend.")
    elif above and below:
        trend, score = "mixed", 0
        obs.append(f"Above the {'/'.join(above)} but below the {'/'.join(below)} — "
                   f"the averages disagree, which is what a range looks like.")
    else:
        trend, score = "unclear", 0
        obs.append("Not enough history on this timeframe to judge the trend.")
    signals.append(("trend", score))

    if m50 and m200:
        if m50 > m200:
            obs.append(f"The 50 sits above the 200 ({m50:,.2f} vs {m200:,.2f}) — long-term structure is constructive.")
        else:
            obs.append(f"The 50 sits below the 200 ({m50:,.2f} vs {m200:,.2f}) — long-term structure is still broken.")

    sl = _slope(sma20)
    if sl is not None:
        obs.append(f"The 20-period average is {'rising' if sl > 0.005 else 'falling' if sl < -0.005 else 'flat'} "
                   f"({sl*100:+.1f}% over 5 bars).")

    # --- momentum ----------------------------------------------------------
    r = _last(rsi)
    if r is not None:
        if r >= 70:
            obs.append(f"RSI {r:.0f} — overbought; moves from here often stall or need to consolidate.")
            signals.append(("momentum", -1))
        elif r <= 30:
            obs.append(f"RSI {r:.0f} — oversold; the level itself is not a buy signal, but it is where bounces start.")
            signals.append(("momentum", 1))
        else:
            obs.append(f"RSI {r:.0f} — in the middle of its range, so momentum is not stretched either way.")
            signals.append(("momentum", 1 if r > 50 else -1))

    if macd["macd"] and macd["signal"]:
        ml, sig = macd["macd"][-1]["value"], macd["signal"][-1]["value"]
        hist = macd["histogram"][-1]["value"] if macd["histogram"] else None
        cross = "above" if ml > sig else "below"
        obs.append(f"MACD is {cross} its signal line ({ml:+.2f} vs {sig:+.2f})"
                   + (f", histogram {hist:+.2f}." if hist is not None else "."))
        signals.append(("macd", 1 if ml > sig else -1))

    w = _last(willr)
    if w is not None:
        state = "oversold" if w <= -80 else "overbought" if w >= -20 else "mid-range"
        obs.append(f"Williams %R {w:.0f} — {state}.")

    # --- volatility and position in range ----------------------------------
    if bb["upper"] and bb["lower"]:
        up, lo, mid = bb["upper"][-1]["value"], bb["lower"][-1]["value"], bb["middle"][-1]["value"]
        width = (up - lo) / mid if mid else 0
        pctb = (close - lo) / (up - lo) if up > lo else 0.5
        where = ("above the upper band" if pctb > 1 else "at the upper band" if pctb > 0.9
                 else "below the lower band" if pctb < 0 else "at the lower band" if pctb < 0.1
                 else "mid-band")
        obs.append(f"Price is {where} (%B {pctb:.2f}); band width is {width*100:.0f}% of price"
                   f"{' — unusually tight, which often precedes an expansion' if width < 0.08 else ''}.")

    a = _last(atr)
    if a and close:
        obs.append(f"ATR {a:,.2f}, about {a/close*100:.1f}% of price — the typical bar range.")

    # --- volume ------------------------------------------------------------
    vols = [b.get("volume") or 0 for b in bars[-60:]]
    if any(vols):
        avg = sum(vols) / len(vols)
        last_v = bars[-1].get("volume") or 0
        if avg > 0:
            ratio = last_v / avg
            obs.append(f"Last bar traded {ratio:.1f}× its 60-bar average volume"
                       + (" — conviction behind the move." if ratio > 1.5
                          else " — thin, so treat the move cautiously." if ratio < 0.6 else "."))

    # --- structure ---------------------------------------------------------
    levels = swing_levels(bars)
    if levels["resistance"]:
        nearest = levels["resistance"][0]
        obs.append(f"Nearest resistance {nearest['price']:,.2f} "
                   f"({(nearest['price']/close-1)*100:+.1f}% away, from {nearest['date']}).")
    if levels["support"]:
        nearest = levels["support"][0]
        obs.append(f"Nearest support {nearest['price']:,.2f} "
                   f"({(nearest['price']/close-1)*100:+.1f}% away, from {nearest['date']}).")

    hi = max(b["high"] for b in bars[-252:]) if len(bars) >= 60 else max(b["high"] for b in bars)
    lo = min(b["low"] for b in bars[-252:]) if len(bars) >= 60 else min(b["low"] for b in bars)
    obs.append(f"{(close/hi-1)*100:+.1f}% from the period high ({hi:,.2f}), "
               f"{(close/lo-1)*100:+.1f}% from the low ({lo:,.2f}).")

    total = sum(v for _, v in signals)
    bias = ("bullish" if total >= 2 else "leaning bullish" if total == 1
            else "bearish" if total <= -2 else "leaning bearish" if total == -1 else "neutral")

    return {
        "timeframe": label, "bars": len(bars), "close": close,
        "trend": trend, "bias": bias, "score": total,
        "observations": obs,
        "levels": levels,
        "metrics": {"sma20": m20, "sma50": m50, "sma200": m200, "rsi": r,
                    "williams_r": w, "atr": a},
    }


def analyse(bars: list[dict], symbol: str) -> dict:
    """Read the same chart on daily, weekly and monthly, then compare them."""
    frames = []
    for code, label in TIMEFRAMES:
        frames.append(analyse_timeframe(I.resample(bars, code), label))

    usable = [f for f in frames if not f.get("insufficient")]
    summary = []
    if usable:
        scores = {f["timeframe"]: f["score"] for f in usable}
        biases = {f["timeframe"]: f["bias"] for f in usable}
        signs = {k: (1 if v > 0 else -1 if v < 0 else 0) for k, v in scores.items()}
        distinct = set(signs.values()) - {0}

        if len(distinct) <= 1 and distinct:
            direction = "bullish" if distinct == {1} else "bearish"
            summary.append(f"All timeframes agree — {direction}. Agreement across daily, weekly "
                           f"and monthly is the strongest configuration there is, and also the "
                           f"least common.")
        else:
            parts = ", ".join(f"{k} {biases[k]}" for k in signs)
            summary.append(f"Timeframes disagree: {parts}.")
            wk, dy = signs.get("Weekly", 0), signs.get("Daily", 0)
            if wk > 0 and dy < 0:
                summary.append("A daily pullback inside a weekly uptrend — the configuration that "
                               "produces most buyable dips, and also most failed ones.")
            elif wk < 0 and dy > 0:
                summary.append("A daily bounce inside a weekly downtrend. These fail more often "
                               "than they resolve, so the burden of proof sits on the bounce.")

        monthly = next((f for f in usable if f["timeframe"] == "Monthly"), None)
        if monthly:
            summary.append(f"The monthly chart — the one that decides whether this is a dip or a "
                           f"decline — is {monthly['bias']}, {monthly['trend']}.")

    return {"symbol": symbol, "frames": frames, "summary": summary,
            "as_of": bars[-1]["time"] if bars else None}
