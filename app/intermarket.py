"""Signals read from the RATIO of two instruments rather than from one price.

An intermarket signal says nothing about a company. It reads one asset against
another — copper against gold, say — on the theory that the pair prices a macro
condition (industrial demand versus safety) more cleanly than either leg does
alone. That makes it a different kind of artifact from a setup or a method: it
does not tell you what to buy, it tells you what regime you are probably in.

Two things keep this honest. Every signal carries the length of history the free
data actually supports, because a claim about multiple cycles cannot be checked
against six years of ETF prices. And where a source has publicly updated their
own confidence, that update is recorded next to the original claim.
"""
from . import indicators as I, prices


def ratio_bars(conn, numerator: str, denominator: str,
               start: str, end: str) -> list[dict]:
    """Build OHLC candles for numerator/denominator on their common sessions.

    Dividing each leg field-by-field is deliberately not the same as dividing
    highs by highs in the abstract: the ratio's high for a session is taken from
    the two legs' highs on that session, which is what a charting package draws
    and therefore what the source was looking at.
    """
    return prices.ratio_bars(prices.load_bars(conn, numerator, start, end),
                             prices.load_bars(conn, denominator, start, end))


SIGNALS = {
    "copper-gold-macd": {
        "name": "Copper/Gold monthly MACD → Bitcoin",
        "attribution": "Cantonese Cat (@cantonmeow)",
        "confidence": "stated",
        "numerator": "CPER",
        "denominator": "GLD",
        "timeframe": "M",
        "indicator": "macd:12:26:9",
        "claim":
            "A bullish MACD cross on the monthly Copper/Gold ratio has tended to "
            "precede a parabolic move in Bitcoin by roughly six months to a year.",
        "reading":
            "Copper is priced by industrial demand and gold by the wish to own "
            "nothing that can default. The ratio therefore rises when the world is "
            "being built and falls when it is being insured, which is the same "
            "risk appetite that moves Bitcoin — only it shows up in metals first.",
        "quotes": [
            "\"#Bitcoin tends to go parabolic for about 6 months to a year after "
            "Copper/Gold ratio MACD goes through a monthly bullish cross.\" (9 May 2026)",
            "\"Either it stops working, or we're just delayed.\" (23 Aug 2026, "
            "his own follow-up on the same chart)",
        ],
        "caveats": [
            "He posted the doubt himself. The August update is part of the signal, "
            "not a footnote to it.",
            "Copper is proxied by CPER and gold by GLD because free daily history "
            "for the futures themselves is not available here. The ETFs track the "
            "metals with tracking error and their own roll costs.",
            "The claim spans several Bitcoin cycles; the free data does not. See "
            "the coverage note on any evaluation — the usable history begins well "
            "after the MACD burn-in, leaving too few crosses to test the claim.",
            "'Parabolic' is not defined, so nothing here scores whether a past "
            "cross worked. The signal reports state, not a verdict.",
        ],
    },
}


def evaluate(conn, key: str, end: str, start: str = "2010-01-01") -> dict:
    """Current state of one intermarket signal, with its own history honestly sized."""
    spec = SIGNALS.get(key)
    if not spec:
        return {"error": f"unknown signal {key!r}"}
    bars = I.resample(ratio_bars(conn, spec["numerator"], spec["denominator"],
                                 start, end), spec["timeframe"])
    name, params = I.parse(spec["indicator"])
    slow = int(params[1]) if len(params) > 1 else 26
    signal_len = int(params[2]) if len(params) > 2 else 9
    result = {"key": key, "name": spec["name"], "attribution": spec["attribution"],
              "confidence": spec["confidence"], "claim": spec["claim"],
              "reading": spec["reading"], "quotes": spec["quotes"],
              "caveats": list(spec["caveats"]),
              "pair": f'{spec["numerator"]}/{spec["denominator"]}',
              "timeframe": spec["timeframe"], "bars": len(bars)}
    if len(bars) < slow + signal_len + 2:
        result["insufficient"] = True
        return result

    out = I.macd(bars, *[int(p) for p in params])
    line = {p["time"]: p["value"] for p in out["macd"]}
    sig = {p["time"]: p["value"] for p in out["signal"]}
    times = [t for t in sorted(line) if t in sig]
    crosses, prev = [], None
    for t in times:
        hist = line[t] - sig[t]
        if prev is not None and prev < 0 <= hist:
            crosses.append({"time": t, "direction": "bullish"})
        elif prev is not None and prev > 0 >= hist:
            crosses.append({"time": t, "direction": "bearish"})
        prev = hist

    last = times[-1]
    hist = line[last] - sig[last]
    bullish = [c for c in crosses if c["direction"] == "bullish"]
    result.update({
        "as_of": last, "macd": round(line[last], 6), "signal": round(sig[last], 6),
        "histogram": round(hist, 6), "state": "above signal" if hist >= 0 else "below signal",
        "crosses": crosses, "usable_from": times[0],
        "last_bullish_cross": bullish[-1]["time"] if bullish else None,
        # The window is his, not this app's: six months to a year after a cross.
        "window": ({"opens": _add_months(bullish[-1]["time"], 6),
                    "closes": _add_months(bullish[-1]["time"], 12)} if bullish else None),
    })
    if len(bullish) < 4:
        result["caveats"].insert(0,
            f"Only {len(bullish)} bullish cross(es) exist in the usable history "
            f"(from {times[0]}). That is far too few to say anything about a hit "
            f"rate, and none is claimed.")
    return result


def _add_months(iso: str, months: int) -> str:
    y, m = int(iso[:4]), int(iso[5:7])
    total = (y * 12 + m - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


# ------------------------------------------------------------ macro series ---
# A single series read for its structure rather than a ratio — the one
# non-equity chart in the set the user saved from X on 2026-09-03: the US
# 30-year mortgage rate with a 33-year descending trendline broken in 2022 and
# a short descending line from the 2023 high being tested. The chart's
# author is not shown, so the reading is attributed to nobody.
MACRO = {
    "mortgage-30y": {
        "name": "US 30-year mortgage rate — the descending line from 2023",
        "attribution": "Nobody; a chart the user saved from X on 2026-09-03 (author not shown)",
        "confidence": "proposed",
        "series": "MORTGAGE30US",
        "timeframe": "W",
        "claim":
            "The 30-year mortgage rate broke a 33-year descending trendline in 2022 "
            "and has since been falling under a shorter line drawn from the 2023 "
            "high. While it stays under that line, rates are drifting down; a weekly "
            "close above it says the 2023-26 decline is over.",
        "reading":
            "Read on the weekly. The line that matters is the falling resistance "
            "line the structure engine finds from the 2023 high; the state is "
            "whether the latest reading is under it and how far. It is macro "
            "context for housing and the long end of the curve, not a call on any "
            "name.",
        "quotes": [],
        "caveats": [
            "FRED's MORTGAGE30US is Freddie Mac's weekly survey rate, one print a "
            "week on Thursdays; there is no daily series.",
            "A trendline on a rate series is the same geometry as on price and "
            "carries the same warning: measured on this project's shuffled-series "
            "test, touch count says nothing about a line's strength.",
        ],
    },
}


def _sync_series(conn, series: str, fetch: bool = True) -> int:
    """Cache a FRED series if it is more than a week stale."""
    have = prices.load_series(conn, series)
    newest = max(have) if have else None
    from datetime import date as _date, timedelta as _td
    if newest and _date.fromisoformat(newest) >= _date.today() - _td(days=8):
        return 0
    if not fetch:
        return 0
    try:
        bars = prices.fetch_fred(series)
    except Exception:                      # noqa: BLE001 - offline is not an error here
        return 0
    added = prices.store(conn, series, bars, "fred")
    prices.invalidate_series_cache(conn, series)
    return added


def evaluate_macro(conn, key: str, end: str, start: str = "1990-01-01",
                   fetch: bool = True) -> dict:
    """The latest reading of a macro series against its own structure."""
    from . import structure as S
    spec = MACRO.get(key)
    if not spec:
        return {"error": f"unknown macro series {key!r}"}
    _sync_series(conn, spec["series"], fetch=fetch)
    daily = prices.load_bars(conn, spec["series"], start, end)
    bars = I.resample(daily, spec["timeframe"]) if daily else []
    result = {"key": key, "name": spec["name"], "attribution": spec["attribution"],
              "confidence": spec["confidence"], "claim": spec["claim"],
              "reading": spec["reading"], "quotes": spec["quotes"],
              "caveats": list(spec["caveats"]), "series": spec["series"],
              "timeframe": spec["timeframe"], "bars": len(bars)}
    if len(bars) < 30:
        result["insufficient"] = True
        result["state"] = "no cached history yet — open this once online to fetch it"
        return result
    last = bars[-1]
    value = last["close"]
    # The structure window is the last 200 weekly bars — about four years,
    # which covers the 2023 high the chart's line is drawn from. The series
    # is one print a week, so every bar's high equals its low and the OHLC
    # path measures a typical range of zero and draws nothing; read as a
    # plain value series the unit is the week-to-week change, as for an
    # oscillator pane.
    st = S.detect([{"time": b["time"], "value": b["close"]} for b in bars],
                  lookback=200, min_touches=2)
    lines = [l for l in st.get("trendlines", []) if l.get("reaches_present")]
    falling_res = [l for l in lines if l["side"] == "resistance"
                   and l["to"]["price"] < l["from"]["price"]]
    year = bars[-52:]
    hi52, lo52 = max(b["high"] for b in year), min(b["low"] for b in year)
    line = None
    if falling_res:
        l = max(falling_res, key=lambda x: x["touches"])
        at = l["to"]["price"]
        line = {"from": l["from"], "at": round(at, 4), "touches": l["touches"],
                "under": value < at, "gap_pct": round((value / at - 1) * 100, 2)}
    if line:
        state = (f"{value:.2f}% on {last['time']}, "
                 f"{'under' if line['under'] else 'ABOVE'} the falling line from "
                 f"{line['from']['time']} (now {line['at']:.2f}%, {line['gap_pct']:+.2f}%); "
                 f"52-week range {lo52:.2f}–{hi52:.2f}")
    else:
        state = (f"{value:.2f}% on {last['time']}; no falling resistance line reaches the "
                 f"present in the last four years of weekly bars; 52-week range "
                 f"{lo52:.2f}–{hi52:.2f}")
    result.update({"as_of": last["time"], "value": value, "line": line,
                   "high_52w": hi52, "low_52w": lo52, "state": state,
                   "recent": [{"time": b["time"], "value": b["close"]} for b in bars[-26:]]})
    return result


def macro_catalogue() -> list[dict]:
    return [{"key": k, "name": v["name"], "attribution": v["attribution"],
             "confidence": v["confidence"], "claim": v["claim"],
             "pair": v["series"], "timeframe": v["timeframe"]} for k, v in MACRO.items()]


def catalogue() -> list[dict]:
    return [{"key": k, "name": v["name"], "attribution": v["attribution"],
             "confidence": v["confidence"], "claim": v["claim"],
             "pair": f'{v["numerator"]}/{v["denominator"]}',
             "timeframe": v["timeframe"]} for k, v in SIGNALS.items()]
