"""Technical indicators, computed server-side.

Deliberately Python rather than a charting-library plugin. The Method Library,
the scanner and the backtester all need the same numbers, and if the chart drew
them from a JavaScript library while the backtest computed its own, the two
would drift and a strategy would stop behaving like the picture of it. One
implementation, four consumers.

Stdlib only — these are all a few lines, and a dependency here would buy nothing.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache


def _closes(bars: list[dict]) -> list[float]:
    return [b["close"] for b in bars]


@lru_cache(maxsize=None)
def _period_key(iso: str, tf: str) -> str:
    """Which weekly/monthly/quarterly candle a date belongs to.

    Memoised on the date string: there are a few thousand distinct trading
    days and this was being computed — a strptime-equivalent and an ISO
    calendar lookup — 325,000 times per Methods request, once per bar per
    symbol. The cache is bounded by the calendar, not by traffic.
    """
    y, m, d = (int(x) for x in iso[:10].split("-"))
    if tf == "M":
        return f"{y:04d}-{m:02d}"
    if tf == "Q":
        return f"{y:04d}Q{(m - 1) // 3 + 1}"
    wy, wk, _ = date(y, m, d).isocalendar()
    return f"{wy:04d}W{wk:02d}"


def resample(bars: list[dict], timeframe: str) -> list[dict]:
    """Aggregate daily bars into weekly, monthly or quarterly candles.

    A weekly chart is not a smoothed daily chart — it is a different series with
    its own highs, lows and closes, and an indicator computed on it gives a
    different (often much steadier) reading. Sector rotation in particular is
    close to unreadable on a daily chart and obvious on a weekly one.
    """
    tf = (timeframe or "D").upper()[0]
    if tf == "D" or not bars:
        return bars

    out, cur, bucket = [], None, None
    for b in bars:
        k = _period_key(b["time"], tf)
        if k != cur:
            if bucket:
                out.append(bucket)
            cur = k
            bucket = {"time": b["time"], "open": b["open"], "high": b["high"],
                      "low": b["low"], "close": b["close"], "volume": b.get("volume") or 0}
        else:
            bucket["high"] = max(bucket["high"], b["high"])
            bucket["low"] = min(bucket["low"], b["low"])
            bucket["close"] = b["close"]
            bucket["volume"] += b.get("volume") or 0
            # A weekly candle is dated by its LAST session, so the final bar of
            # a partial week sits at today rather than at last Monday.
            bucket["time"] = b["time"]
    if bucket:
        out.append(bucket)
    return out


def sma(bars: list[dict], period: int) -> list[dict]:
    """Simple moving average."""
    out, closes, run = [], _closes(bars), 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= period:
            run -= closes[i - period]
        if i >= period - 1:
            out.append({"time": bars[i]["time"], "value": round(run / period, 4)})
    return out


def ema(bars: list[dict], period: int) -> list[dict]:
    """Exponential moving average, seeded with the first `period` SMA."""
    closes = _closes(bars)
    if len(closes) < period:
        return []
    k = 2.0 / (period + 1)
    val = sum(closes[:period]) / period
    out = [{"time": bars[period - 1]["time"], "value": round(val, 4)}]
    for i in range(period, len(closes)):
        val = closes[i] * k + val * (1 - k)
        out.append({"time": bars[i]["time"], "value": round(val, 4)})
    return out


def rsi(bars: list[dict], period: int = 14) -> list[dict]:
    """Wilder's RSI — smoothed averages, not a plain mean of the last N moves."""
    closes = _closes(bars)
    if len(closes) <= period:
        return []
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period
    out = []
    for i in range(period, len(closes)):
        if i > period:
            d = closes[i] - closes[i - 1]
            avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
            avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        rs = (avg_g / avg_l) if avg_l > 1e-12 else float("inf")
        value = 100.0 if rs == float("inf") else 100.0 - (100.0 / (1.0 + rs))
        out.append({"time": bars[i]["time"], "value": round(value, 2)})
    return out


def macd(bars: list[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    fast_e, slow_e = ema(bars, fast), ema(bars, slow)
    if not fast_e or not slow_e:
        return {"macd": [], "signal": [], "histogram": []}
    fast_by = {p["time"]: p["value"] for p in fast_e}
    line = [{"time": p["time"], "value": round(fast_by[p["time"]] - p["value"], 4)}
            for p in slow_e if p["time"] in fast_by]
    sig = ema([{"time": p["time"], "close": p["value"]} for p in line], signal)
    sig_by = {p["time"]: p["value"] for p in sig}
    hist = [{"time": p["time"], "value": round(p["value"] - sig_by[p["time"]], 4)}
            for p in line if p["time"] in sig_by]
    return {"macd": line, "signal": sig, "histogram": hist}


def bollinger(bars: list[dict], period: int = 20, mult: float = 2.0) -> dict:
    closes = _closes(bars)
    mid, upper, lower = [], [], []
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        m = sum(window) / period
        var = sum((x - m) ** 2 for x in window) / period
        sd = var ** 0.5
        t = bars[i]["time"]
        mid.append({"time": t, "value": round(m, 4)})
        upper.append({"time": t, "value": round(m + mult * sd, 4)})
        lower.append({"time": t, "value": round(m - mult * sd, 4)})
    return {"middle": mid, "upper": upper, "lower": lower}


def atr(bars: list[dict], period: int = 14) -> list[dict]:
    """Average true range — Wilder smoothing. Useful for position sizing."""
    if len(bars) <= period:
        return []
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    val = sum(trs[:period]) / period
    out = [{"time": bars[period]["time"], "value": round(val, 4)}]
    for i in range(period, len(trs)):
        val = (val * (period - 1) + trs[i]) / period
        out.append({"time": bars[i + 1]["time"], "value": round(val, 4)})
    return out


def keltner(bars: list[dict], period: int = 20, mult: float = 2.0,
            atr_period: int = 10) -> dict:
    """Keltner channels: an EMA with ATR-width bands.

    Distinct from Bollinger despite looking alike — Bollinger measures the
    dispersion of closes, Keltner measures true range, so it accounts for gaps
    and intrabar swing. A close outside the upper band is the "Keltner channel
    breakout" Cantonese Cat reads on the quarterly $SPX chart.
    """
    mid = ema(bars, period)
    rng = atr(bars, atr_period)
    if not mid or not rng:
        return {"middle": [], "upper": [], "lower": []}
    width = {r["time"]: r["value"] for r in rng}
    middle, upper, lower = [], [], []
    for point in mid:
        w = width.get(point["time"])
        if w is None:
            continue
        middle.append(point)
        upper.append({"time": point["time"], "value": round(point["value"] + mult * w, 4)})
        lower.append({"time": point["time"], "value": round(point["value"] - mult * w, 4)})
    return {"middle": middle, "upper": upper, "lower": lower}


def _window_extremes(bars: list[dict], n: int) -> tuple[list, list]:
    """Rolling highest high and lowest low over the last `n` bars, per bar.

    Returns two lists aligned with `bars`; entries before the window is full
    are None. Monotonic deques make this O(len(bars)) — the previous version
    rescanned the whole window for every bar, O(n·period), and Ichimoku does
    it three times (9, 26, 52) on every chart, watchlist name and backtest
    step. max()/min() over a window are pure selections, so the values here
    are bit-for-bit what a rescan returns.
    """
    from collections import deque
    highs, lows = [None] * len(bars), [None] * len(bars)
    if n <= 0:
        return highs, lows
    hi_q: deque = deque()          # indices, highs non-increasing
    lo_q: deque = deque()          # indices, lows non-decreasing
    for i, b in enumerate(bars):
        h, l = b["high"], b["low"]
        while hi_q and bars[hi_q[-1]]["high"] <= h:
            hi_q.pop()
        hi_q.append(i)
        while lo_q and bars[lo_q[-1]]["low"] >= l:
            lo_q.pop()
        lo_q.append(i)
        if hi_q[0] <= i - n:
            hi_q.popleft()
        if lo_q[0] <= i - n:
            lo_q.popleft()
        if i >= n - 1:
            highs[i] = bars[hi_q[0]]["high"]
            lows[i] = bars[lo_q[0]]["low"]
    return highs, lows


def williams_r(bars: list[dict], period: int = 14,
               upper: float = -20.0, lower: float = -80.0) -> list[dict]:
    """Williams %R — where the close sits in the recent high/low range.

    Scaled -100 (at the period low) to 0 (at the period high). Below -80 is
    conventionally oversold, above -20 overbought — but the bands are arguments
    rather than constants, because not everyone uses the textbook levels. Setting
    them to 0 and -100 removes the intermediate guides entirely and reads the
    oscillator against its true extremes, which is a materially different way of
    using it: a signal then requires price at the actual high or low of the
    lookback, not merely near it.
    """
    out = []
    highs, lows = _window_extremes(bars, period)
    for i in range(period - 1, len(bars)):
        hh, ll = highs[i], lows[i]
        rng = hh - ll
        val = -50.0 if rng < 1e-12 else -100.0 * (hh - bars[i]["close"]) / rng
        out.append({"time": bars[i]["time"], "value": round(val, 2)})
    return out


def stochastic(bars: list[dict], period: int = 14, smooth: int = 3) -> dict:
    """Stochastic oscillator: %K and its moving average %D."""
    raw = []
    highs, lows = _window_extremes(bars, period)
    for i in range(period - 1, len(bars)):
        hh, ll = highs[i], lows[i]
        rng = hh - ll
        val = 50.0 if rng < 1e-12 else 100.0 * (bars[i]["close"] - ll) / rng
        raw.append({"time": bars[i]["time"], "value": round(val, 2)})
    d = sma([{"time": p["time"], "close": p["value"]} for p in raw], smooth)
    return {"k": raw, "d": d}


def obv(bars: list[dict]) -> list[dict]:
    """On-balance volume — volume signed by the day's direction."""
    out, run = [], 0.0
    for i, b in enumerate(bars):
        if i:
            v = b.get("volume") or 0
            run += v if b["close"] > bars[i - 1]["close"] else (-v if b["close"] < bars[i - 1]["close"] else 0)
        out.append({"time": b["time"], "value": round(run, 0)})
    return out


def vwap(bars: list[dict], period: int = 20) -> list[dict]:
    """Rolling volume-weighted average price."""
    out = []
    for i in range(period - 1, len(bars)):
        window = bars[i - period + 1:i + 1]
        vol = sum((b.get("volume") or 0) for b in window)
        if vol <= 0:
            continue
        tp = sum(((b["high"] + b["low"] + b["close"]) / 3) * (b.get("volume") or 0) for b in window)
        out.append({"time": bars[i]["time"], "value": round(tp / vol, 4)})
    return out


def ichimoku(bars: list[dict], tenkan: int = 9, kijun: int = 26, senkou: int = 52) -> dict:
    """Ichimoku Kinko Hyo — conversion, base, cloud and lagging span.

    Each line is the midpoint of a period's high/low range rather than an
    average of closes, which is why the cloud behaves like support and
    resistance instead of like a smoothed price.

    THE CLOUD IS DISPLACED. Senkou A and B are plotted `kijun` bars AHEAD of the
    data they are computed from — that lead is the whole idea, and it is why the
    cloud can act as support before price arrives at it. This previously plotted
    both spans at the bar they were computed on, so the cloud sat 26 bars to the
    left of where every other charting package draws it and disagreed with the
    thing a "reclaim the cloud" setup is actually looking at.

    The portion that would fall beyond the last bar is not drawn, because the
    series carries no future timestamps to hang it on; the cloud therefore ends
    at the right edge rather than leading it.
    """
    # One rolling pass per period rather than a rescan per bar; see
    # _window_extremes for why. Same values, ~period times less work.
    ext = {n: _window_extremes(bars, n) for n in {tenkan, kijun, senkou}}

    def midpoint(i: int, n: int) -> float | None:
        if i < n - 1:
            return None
        highs, lows = ext[n]
        return (highs[i] + lows[i]) / 2

    conv, base, span_a, span_b, lag = [], [], [], [], []
    for i, b in enumerate(bars):
        t, k = midpoint(i, tenkan), midpoint(i, kijun)
        if t is not None:
            conv.append({"time": b["time"], "value": round(t, 4)})
        if k is not None:
            base.append({"time": b["time"], "value": round(k, 4)})
        ahead = i + kijun
        future = bars[ahead]["time"] if ahead < len(bars) else None
        if t is not None and k is not None and future:
            span_a.append({"time": future, "value": round((t + k) / 2, 4)})
        sb = midpoint(i, senkou)
        if sb is not None and future:
            span_b.append({"time": future, "value": round(sb, 4)})
        if i >= kijun:
            lag.append({"time": bars[i - kijun]["time"], "value": b["close"]})
    return {"conversion": conv, "base": base, "span_a": span_a,
            "span_b": span_b, "lagging": lag}


def volume(bars: list[dict]) -> list[dict]:
    """Volume bars, coloured by whether the day closed up or down."""
    out = []
    for i, b in enumerate(bars):
        up = b["close"] >= (bars[i - 1]["close"] if i else b["open"])
        out.append({"time": b["time"], "value": b.get("volume") or 0,
                    "color": "rgba(46,111,73,.45)" if up else "rgba(156,59,46,.45)"})
    return out


# Every indicator is addressed as "name:p1:p2", so any period is adjustable
# from the UI rather than a handful being frozen at whatever default was
# hard-coded. `params` lists each numeric argument with a label and sane bounds
# so the front end can build its own controls without duplicating this table.
def volume_profile(bars: list[dict], lookback: int = 120, bins: int = 24) -> dict | None:
    """Volume by PRICE rather than by time: how much traded at each level.

    The IREN chart SteveUrkeldude posted (research/charts-2026-09-03-x-accounts.md)
    carries this on the right edge: a thick node around 40-44 where most of
    the summer's volume changed hands, and thin bars above 47. His arrow
    through the descending trendline is drawn INTO the thin part, and that is
    the whole argument — a breakout above a heavy node travels fast because
    little was ever traded there to get in the way.

    Each bar's volume is spread evenly across the price bins its high-low
    range covers, which is the standard approximation when there is no
    tick data. Returns the bins, the point of control (heaviest bin) and the
    value area (the contiguous 70% of volume around it). Not registered as a
    chart indicator: it is a histogram by price, which the renderer does not
    draw yet; the verdict engine reads it directly.
    """
    window = bars[-lookback:] if len(bars) > lookback else bars
    if len(window) < 10 or bins < 2:
        return None
    top = max(b["high"] for b in window)
    bottom = min(b["low"] for b in window)
    if top <= bottom:
        return None
    step = (top - bottom) / bins
    vol = [0.0] * bins
    total = 0.0
    for b in window:
        v = float(b.get("volume") or 0)
        if v <= 0:
            continue
        total += v
        lo_i = int((b["low"] - bottom) / step)
        hi_i = int((b["high"] - bottom) / step)
        lo_i = max(0, min(bins - 1, lo_i))
        hi_i = max(0, min(bins - 1, hi_i))
        n = hi_i - lo_i + 1
        for i in range(lo_i, hi_i + 1):
            vol[i] += v / n
    if total <= 0:
        return None
    poc_i = max(range(bins), key=lambda i: vol[i])
    # Value area: grow outward from the point of control, taking the heavier
    # neighbour each step, until 70% of the volume is inside.
    lo_i = hi_i = poc_i
    inside = vol[poc_i]
    while inside < 0.70 * total and (lo_i > 0 or hi_i < bins - 1):
        below = vol[lo_i - 1] if lo_i > 0 else -1
        above = vol[hi_i + 1] if hi_i < bins - 1 else -1
        if above >= below:
            hi_i += 1
            inside += vol[hi_i]
        else:
            lo_i -= 1
            inside += vol[lo_i]
    out_bins = [{"low": round(bottom + i * step, 4), "high": round(bottom + (i + 1) * step, 4),
                 "volume": round(vol[i], 2), "share": round(vol[i] / total, 4)}
                for i in range(bins)]
    return {"bins": out_bins, "step": round(step, 4), "total": round(total, 2),
            "poc": {"low": out_bins[poc_i]["low"], "high": out_bins[poc_i]["high"],
                    "price": round(bottom + (poc_i + 0.5) * step, 4),
                    "share": out_bins[poc_i]["share"]},
            "value_area": {"low": out_bins[lo_i]["low"], "high": out_bins[hi_i]["high"]},
            "window": {"from": window[0]["time"], "to": window[-1]["time"]}}


REGISTRY = {
    "sma":       {"fn": sma,        "pane": "price",  "label": "SMA",
                  "params": [("period", 20, 2, 400)]},
    "ema":       {"fn": ema,        "pane": "price",  "label": "EMA",
                  "params": [("period", 21, 2, 400)]},
    "bollinger": {"fn": bollinger,  "pane": "price",  "label": "Bollinger",
                  "params": [("period", 20, 2, 200), ("mult", 2.0, 0.5, 5.0)]},
    "keltner":   {"fn": keltner,    "pane": "price",  "label": "Keltner",
                  "params": [("period", 20, 2, 200), ("mult", 2.0, 0.5, 5.0),
                             ("atr_period", 10, 2, 100)]},
    "vwap":      {"fn": vwap,       "pane": "price",  "label": "VWAP",
                  "params": [("period", 20, 2, 400)]},
    "ichimoku":  {"fn": ichimoku,   "pane": "price",  "label": "Ichimoku",
                  "params": [("tenkan", 9, 2, 60), ("kijun", 26, 2, 200),
                             ("senkou", 52, 2, 400)]},
    "rsi":       {"fn": rsi,        "pane": "lower",  "label": "RSI",
                  "params": [("period", 14, 2, 100)], "bounds": [30, 70], "range": [0, 100]},
    "willr":     {"fn": williams_r, "pane": "lower",  "label": "Williams %R",
                  "params": [("period", 14, 2, 100), ("upper", -20.0, -100.0, 0.0),
                             ("lower", -80.0, -100.0, 0.0)],
                  "bounds": [-80, -20], "range": [-100, 0]},
    "stoch":     {"fn": stochastic, "pane": "lower",  "label": "Stochastic",
                  "params": [("period", 14, 2, 100), ("smooth", 3, 1, 20)],
                  "bounds": [20, 80], "range": [0, 100]},
    "macd":      {"fn": macd,       "pane": "lower",  "label": "MACD",
                  "params": [("fast", 12, 2, 100), ("slow", 26, 3, 200), ("signal", 9, 2, 50)]},
    "atr":       {"fn": atr,        "pane": "lower",  "label": "ATR",
                  "params": [("period", 14, 2, 100)]},
    "obv":       {"fn": obv,        "pane": "lower",  "label": "OBV", "params": []},
    "volume":    {"fn": volume,     "pane": "volume", "label": "Volume", "params": []},
}


def parse(spec: str) -> tuple[str, list[float]]:
    """'bollinger:20:2.5' -> ('bollinger', [20, 2.5])."""
    parts = spec.split(":")
    name, args = parts[0], []
    for a in parts[1:]:
        try:
            args.append(float(a) if "." in a else int(a))
        except ValueError:
            pass
    return name, args


def compute(bars: list[dict], specs: list[str]) -> dict:
    """Compute each requested indicator, keyed by its full spec string.

    A failure is reported against that one indicator rather than raised: a bad
    parameter should grey out a single line, never blank the whole chart.
    """
    out = {}
    for spec in specs:
        name, args = parse(spec)
        entry = REGISTRY.get(name)
        if not entry:
            continue
        defaults = [p[1] for p in entry["params"]]
        merged = [args[i] if i < len(args) else defaults[i] for i in range(len(defaults))]
        # Clamp to the declared bounds so a hostile or fat-fingered value cannot
        # ask for a 10-million-period average.
        for i, (_n, _d, lo, hi) in enumerate(entry["params"]):
            merged[i] = type(_d)(max(lo, min(hi, merged[i])))
        try:
            data = entry["fn"](bars, *merged)
        except Exception as exc:                    # noqa: BLE001 - never break a chart
            out[spec] = {"pane": entry["pane"], "data": [], "error": f"{type(exc).__name__}: {exc}"}
            continue
        # If an indicator takes its band levels as arguments, the chart should
        # draw the bands the user configured rather than the textbook defaults.
        bounds = entry.get("bounds")
        names = [p2[0] for p2 in entry["params"]]
        if "upper" in names and "lower" in names:
            bounds = sorted([merged[names.index("lower")], merged[names.index("upper")]])
        out[spec] = {"pane": entry["pane"], "data": data, "label": entry["label"],
                     "args": merged, "bounds": bounds,
                     "range": entry.get("range")}
    return out


def catalogue() -> list[dict]:
    """The indicator menu, for the UI to render controls from."""
    return [{"name": k, "label": v["label"], "pane": v["pane"],
             "params": [{"name": n, "default": d, "min": lo, "max": hi}
                        for n, d, lo, hi in v["params"]]}
            for k, v in REGISTRY.items()]
