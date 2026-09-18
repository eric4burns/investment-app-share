"""Known-answer tests for the indicator library.

These matter more than they look: the same functions will drive the scanner and
the backtester, so an off-by-one in a moving average would not just draw a
slightly wrong line, it would silently change which names a strategy selects.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import indicators

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def bars(closes, highs=None, lows=None):
    return [{"time": f"2026-01-{i+1:02d}", "close": c,
             "open": c, "high": (highs or closes)[i], "low": (lows or closes)[i],
             "volume": 100} for i, c in enumerate(closes)]


# SMA — hand-computable.
s = indicators.sma(bars([1, 2, 3, 4, 5]), 3)
check("SMA(3) of 1..5 is [2,3,4]", [p["value"] for p in s] == [2.0, 3.0, 4.0],
      [p["value"] for p in s])
check("SMA emits len-period+1 points", len(s) == 3, len(s))
check("SMA's first point is dated at the END of its window",
      s[0]["time"] == "2026-01-03", s[0]["time"])

# EMA — seeded with the SMA of the first `period`, then k = 2/(n+1).
e = indicators.ema(bars([1, 2, 3, 4, 5]), 3)
# seed = mean(1,2,3) = 2; k = 0.5; next = 4*0.5 + 2*0.5 = 3; then 5*0.5 + 3*0.5 = 4
check("EMA(3) of 1..5 is [2,3,4]", [p["value"] for p in e] == [2.0, 3.0, 4.0],
      [p["value"] for p in e])
check("EMA returns nothing when the series is shorter than the period",
      indicators.ema(bars([1, 2]), 5) == [])

# RSI — the two limiting cases are exact.
up = indicators.rsi(bars(list(range(1, 40))), 14)
check("RSI of a monotonic rise is 100", all(abs(p["value"] - 100) < 1e-6 for p in up),
      up[-1]["value"] if up else None)
down = indicators.rsi(bars(list(range(40, 1, -1))), 14)
check("RSI of a monotonic fall is 0", all(abs(p["value"]) < 1e-6 for p in down),
      down[-1]["value"] if down else None)
mixed = indicators.rsi(bars([10, 11, 10, 11] * 12), 14)
check("RSI stays within 0..100 on choppy data",
      all(0 <= p["value"] <= 100 for p in mixed))

# Bollinger — the middle band must BE the SMA, and the bands symmetric.
b = indicators.bollinger(bars([10, 12, 14, 12, 10] * 8), 20, 2.0)
m = indicators.sma(bars([10, 12, 14, 12, 10] * 8), 20)
check("Bollinger middle band equals SMA of the same period",
      all(abs(x["value"] - y["value"]) < 1e-9 for x, y in zip(b["middle"], m)))
check("Bollinger bands are symmetric about the middle",
      all(abs((u["value"] - mid["value"]) - (mid["value"] - lo["value"])) < 1e-9
          for u, mid, lo in zip(b["upper"], b["middle"], b["lower"])))
check("Bollinger bands collapse to the mean on a flat series",
      all(abs(u["value"] - lo["value"]) < 1e-9
          for u, lo in zip(indicators.bollinger(bars([5] * 30))["upper"],
                           indicators.bollinger(bars([5] * 30))["lower"])))

# ATR — with high==low==close every true range is the gap between closes.
a = indicators.atr(bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25]), 14)
check("ATR of a series rising 1/day is 1.0", a and abs(a[0]["value"] - 1.0) < 1e-9,
      a[0]["value"] if a else None)

# MACD — on a flat series every component is zero.
mac = indicators.macd(bars([10] * 60))
check("MACD of a flat series is zero", all(abs(p["value"]) < 1e-9 for p in mac["macd"]))
# The label used to promise a relationship the assertion never touched — it
# only checked the list was non-empty, so corrupting the histogram left it green.
_line = {p["time"]: p["value"] for p in mac["macd"]}
_sig = {p["time"]: p["value"] for p in mac["signal"]}
_rising = indicators.macd(bars([10 + i * 0.7 for i in range(80)]))
_rl = {p["time"]: p["value"] for p in _rising["macd"]}
_rs = {p["time"]: p["value"] for p in _rising["signal"]}
check("MACD histogram equals macd minus signal, bar for bar",
      _rising["histogram"] and all(
          abs(h["value"] - (_rl[h["time"]] - _rs[h["time"]])) < 1e-6
          for h in _rising["histogram"]),
      next((h["time"] for h in _rising["histogram"]
            if abs(h["value"] - (_rl[h["time"]] - _rs[h["time"]])) >= 1e-6), ""))

# Registry contract — the UI builds its controls from this, so every entry must
# declare a pane and describe its parameters with usable bounds.
check("every registry entry declares a valid pane",
      all(v["pane"] in {"price", "lower", "volume"} for v in indicators.REGISTRY.values()))
check("every parameter declares default, min and max",
      all(len(p) == 4 and p[2] <= p[1] <= p[3]
          for v in indicators.REGISTRY.values() for p in v["params"]),
      [(k, v["params"]) for k, v in indicators.REGISTRY.items()
       if any(not (p[2] <= p[1] <= p[3]) for p in v["params"])])
check("catalogue exposes every registry entry",
      {c["name"] for c in indicators.catalogue()} == set(indicators.REGISTRY))
bad = indicators.compute(bars([1, 2, 3]), ["does_not_exist"])
check("unknown indicator names are ignored, not fatal", bad == {}, bad)

# Parameterisation — the point of the rewrite.
check("spec parsing splits name and numeric args",
      indicators.parse("bollinger:20:2.5") == ("bollinger", [20, 2.5]),
      indicators.parse("bollinger:20:2.5"))
d = bars(list(range(1, 60)))
check("an omitted parameter falls back to its default",
      indicators.compute(d, ["sma"])["sma"]["args"] == [20])
check("a supplied parameter is used",
      indicators.compute(d, ["sma:5"])["sma:5"]["args"] == [5])
check("an out-of-range parameter is clamped, not passed through",
      indicators.compute(d, ["sma:99999"])["sma:99999"]["args"] == [400],
      indicators.compute(d, ["sma:99999"])["sma:99999"]["args"])
check("a failing indicator reports an error without breaking the rest",
      "sma:20" in indicators.compute(d, ["sma:20", "rsi:2"]))

# Williams %R is bounded by construction; the extremes are exact.
w_up = indicators.williams_r(bars(list(range(1, 40))), 14)
w_dn = indicators.williams_r(bars(list(range(40, 1, -1))), 14)
check("Williams %R is 0 at the top of its range",
      all(abs(p["value"]) < 1e-9 for p in w_up), w_up[-1]["value"])
check("Williams %R is -100 at the bottom of its range",
      all(abs(p["value"] + 100) < 1e-9 for p in w_dn), w_dn[-1]["value"])
check("Williams %R never leaves -100..0",
      all(-100 <= p["value"] <= 0 for p in indicators.williams_r(bars([10, 12, 9, 14, 11] * 8), 14)))

# Stochastic mirrors Williams %R: %K = 100 + %R.
st = indicators.stochastic(bars([10, 12, 9, 14, 11] * 8), 14, 3)
wr = indicators.williams_r(bars([10, 12, 9, 14, 11] * 8), 14)
check("Stochastic %K is Williams %R shifted by 100",
      all(abs(k["value"] - (r["value"] + 100)) < 0.011 for k, r in zip(st["k"], wr)))

# Resampling must preserve the extremes, not average them away.
daily = [{"time": f"2026-01-{d:02d}", "open": 10.0, "high": 10 + d, "low": 10 - d,
          "close": 10.0 + d, "volume": 100} for d in range(1, 29)]
wk = indicators.resample(daily, "W")
mo = indicators.resample(daily, "M")
check("weekly resample produces fewer bars than daily", 0 < len(wk) < len(daily), len(wk))
check("monthly resample of one month is a single bar", len(mo) == 1, len(mo))
check("resampled high is the max of its constituents",
      abs(mo[0]["high"] - max(b["high"] for b in daily)) < 1e-9)
check("resampled low is the min of its constituents",
      abs(mo[0]["low"] - min(b["low"] for b in daily)) < 1e-9)
check("resampled volume is the sum of its constituents",
      abs(mo[0]["volume"] - sum(b["volume"] for b in daily)) < 1e-9)
check("resampled close is the LAST close, not the highest",
      abs(mo[0]["close"] - daily[-1]["close"]) < 1e-9)
check("a resampled bar is dated by its final session",
      mo[0]["time"] == daily[-1]["time"], mo[0]["time"])
check("daily resample is a no-op", indicators.resample(daily, "D") is daily)

# The fixture above rises every session, so its LAST high is also its highest
# and its LAST low its lowest — which means "high is the max" passed even with
# the running max replaced by plain assignment. A bucket whose extremes sit in
# the middle is the only shape that can tell those apart.
_humped = [{"time": f"2026-03-{d:02d}", "open": 10.0, "high": h, "low": l, "close": 10.0,
            "volume": 1}
           for d, (h, l) in enumerate(zip([11, 19, 12, 13, 14], [9, 1, 8, 7, 6]), start=2)]
_hm = indicators.resample(_humped, "M")
check("a resampled high is the highest of the bucket, not the last one",
      abs(_hm[0]["high"] - 19) < 1e-9, _hm[0]["high"])
check("a resampled low is the lowest of the bucket, not the last one",
      abs(_hm[0]["low"] - 1) < 1e-9, _hm[0]["low"])
check("a resampled bar opens at the FIRST session of its bucket",
      abs(_hm[0]["open"] - _humped[0]["open"]) < 1e-9, _hm[0]["open"])

# Weekly buckets are ISO weeks, which is the only reason a week straddling New
# Year holds together. Bucketing on day-of-month instead looks right all year
# and silently splits every year-end week into two half-weeks.
_yearend = [{"time": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}
            for t in ("2025-12-29", "2025-12-30", "2025-12-31", "2026-01-01", "2026-01-02")]
check("a week straddling the year boundary stays one bar",
      len(indicators.resample(_yearend, "W")) == 1,
      [b["time"] for b in indicators.resample(_yearend, "W")])
# ...and a genuine week boundary still splits. Both halves of that statement
# are needed: "always one bucket" would also pass the check above.
_twoweeks = [{"time": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}
             for t in ("2026-01-02", "2026-01-05")]     # Friday, then Monday
check("two calendar weeks resample to two bars",
      len(indicators.resample(_twoweeks, "W")) == 2,
      [b["time"] for b in indicators.resample(_twoweeks, "W")])

# --- OHLC-aware fixtures -----------------------------------------------------
# Everything above builds bars with open == high == low == close, so any
# indicator reading the wrong one of the four is indistinguishable from a
# correct one. These bars keep all four apart.
def ohlc(rows):
    """rows are (high, low, close); open is deliberately unlike all three."""
    return [{"time": f"2026-01-{i+1:02d}", "open": -1.0, "high": h, "low": l,
             "close": c, "volume": 100} for i, (h, l, c) in enumerate(rows)]


# --- ICHIMOKU ----------------------------------------------------------------
# The cloud is the one indicator here with a DISPLACEMENT, and getting it wrong
# is a past bug in this file: both spans were plotted at the bar they were
# computed on, so the cloud sat 26 bars left of where every other charting
# package draws it. Nothing in this suite touched ichimoku at all, so that bug
# could be reintroduced in one line and the tests would stay green.
#
# Small periods so every number is checkable by hand. The close sits OFF the
# centre of each bar's range on purpose: with high = i+3, low = i, close = i+1,
# a line built from closes lands half a point below one built from the range, so
# reading the wrong field is visible. The midpoint of the last n bars is
# (i+3 + i-n+1)/2, so tenkan(2) = i+1, kijun(3) = i+0.5, senkou(4) = i.
ich_bars = [{"time": f"2026-01-{i+1:02d}", "open": -1.0, "high": i + 3, "low": i,
             "close": i + 1, "volume": 1} for i in range(12)]
ich = indicators.ichimoku(ich_bars, tenkan=2, kijun=3, senkou=4)

check("the conversion line is the midpoint of the high/low RANGE, not of closes",
      ich["conversion"][0] == {"time": "2026-01-02", "value": 2.0},
      ich["conversion"][0])
check("the base line is the midpoint of its own longer range",
      ich["base"][0] == {"time": "2026-01-03", "value": 2.5}, ich["base"][0])
check("neither line speaks before its window is full",
      ich["conversion"][0]["time"] == ich_bars[1]["time"]
      and ich["base"][0]["time"] == ich_bars[2]["time"],
      (ich["conversion"][0]["time"], ich["base"][0]["time"]))

# THE DISPLACEMENT. Senkou A computed at bar 2 is (tenkan 3 + kijun 2.5)/2 =
# 2.75, and it must be PLOTTED at bar 2+kijun = bar 5 (2026-01-06). Plotting it
# at 2026-01-03 is the old bug and is what this pins.
check("senkou A is plotted kijun bars AHEAD of the data it came from",
      ich["span_a"][0] == {"time": "2026-01-06", "value": 2.75}, ich["span_a"][0])
check("senkou B is plotted kijun bars AHEAD too",
      ich["span_b"][0] == {"time": "2026-01-07", "value": 3.0}, ich["span_b"][0])
_times = [b["time"] for b in ich_bars]
check("every cloud point leads the bar it was computed from by exactly kijun",
      all(_times.index(p["time"]) - _times.index(src) == 3
          for p, src in zip(ich["span_a"], _times[2:])),
      [(p["time"], src) for p, src in zip(ich["span_a"], _times[2:])
       if _times.index(p["time"]) - _times.index(src) != 3])
# The lead has to stop at the right edge: the series carries no future
# timestamps, so the part of the cloud that would fall beyond the last bar is
# not drawn rather than being stacked onto the final date.
check("the cloud stops at the last bar rather than piling up on it",
      len({p["time"] for p in ich["span_a"]}) == len(ich["span_a"])
      and ich["span_a"][-1]["time"] == ich_bars[-1]["time"],
      ich["span_a"][-1])

# The lagging span goes the OTHER way: today's close plotted kijun bars BACK.
check("the lagging span is today's close plotted kijun bars BEHIND",
      ich["lagging"][0] == {"time": "2026-01-01", "value": ich_bars[3]["close"]},
      ich["lagging"][0])
check("the lagging span says nothing until there is a bar to hang it on",
      len(ich["lagging"]) == len(ich_bars) - 3, len(ich["lagging"]))

# --- ATR with real gaps ------------------------------------------------------
# True range is the LARGEST of the bar's own range and the two gaps from the
# previous close. A series with no gaps cannot tell those apart, and the
# existing "rises 1/day" case has none. Both directions are here on purpose:
# bar 3 gaps UP from a close of 12 to a low of 18 (true range 8, from high vs
# previous close) and the last bar gaps DOWN from 14 to a high of 10 (true range
# 8, from low vs previous close). Dropping either term leaves the other case
# still passing. Wilder smoothing then carries those forward at a decaying
# weight no simple average reproduces.
atr_bars = ohlc([(12, 8, 10), (14, 10, 13), (15, 11, 12), (20, 18, 19),
                 (19, 15, 16), (17, 13, 14), (10, 6, 7)])
a3 = indicators.atr(atr_bars, 3)
check("ATR true range counts the gap from the previous close, either way",
      [p["value"] for p in a3] == [5.3333, 4.8889, 4.5926, 5.7284],
      [p["value"] for p in a3])
check("ATR's first reading is dated at bar `period`, not earlier",
      a3[0]["time"] == atr_bars[3]["time"], a3[0]["time"])
check("ATR returns nothing when there are fewer bars than the period",
      indicators.atr(atr_bars, 14) == [])

# --- RSI at a value that is neither 0 nor 100 --------------------------------
# The two saturated cases were the only ones asserted, and both survive any
# smoothing scheme: with no losses at all the answer is 100 however you average.
# Alternating +2 / -1 gives Wilder averages of exactly 1.0 and 0.5 over the
# first 14 moves, so RS = 2 and RSI = 100 - 100/3 = 66.67. Every value after
# that depends on the (n-1)/n recursion being right.
_alt = [100.0]
for _i in range(30):
    _alt.append(_alt[-1] + (2 if _i % 2 == 0 else -1))
rsi_mid = indicators.rsi(bars(_alt), 14)
check("RSI of a +2/-1 sawtooth is 66.67, then follows Wilder's recursion",
      [p["value"] for p in rsi_mid][:4] == [66.67, 69.77, 66.44, 69.57],
      [p["value"] for p in rsi_mid][:4])

# --- Bollinger width is a POPULATION standard deviation ----------------------
# Symmetry and "middle == SMA" both hold for any width, so neither notices a
# sample (n-1) divisor. [2,4,4,6] has mean 4 and population sd sqrt(2), so the
# 2-sigma band is 4 +/- 2.8284; a sample sd would put it at 4 +/- 3.266.
bb_known = indicators.bollinger(bars([2, 4, 4, 6]), 4, 2.0)
check("Bollinger bands are two POPULATION standard deviations wide",
      abs(bb_known["upper"][0]["value"] - 6.8284) < 1e-4
      and abs(bb_known["lower"][0]["value"] - 1.1716) < 1e-4,
      (bb_known["upper"][0]["value"], bb_known["lower"][0]["value"]))

# --- oscillators must read the CLOSE inside the period's high/low range ------
# Every fixture above has open == close, so an oscillator reading the open
# scored identically. Here the open is -1 and would be obvious.
osc = ohlc([(10, 4, 9), (12, 6, 7), (11, 5, 8), (11, 5, 6)])
check("Williams %R places the CLOSE in the period high/low range",
      [p["value"] for p in indicators.williams_r(osc, 3)] == [-50.0, -85.71],
      [p["value"] for p in indicators.williams_r(osc, 3)])
_stoch = indicators.stochastic(osc, 3, 2)
check("Stochastic %D is the moving average of %K over `smooth` bars",
      _stoch["d"] == [{"time": "2026-01-04", "value": 32.145}], _stoch["d"])

# --- VWAP weights the TYPICAL price, not the close ---------------------------
# (high+low+close)/3 is the whole point of a VWAP; weighting closes gives a
# different line that still looks plausible on a chart.
vw = [{"time": "2026-01-01", "open": 9, "high": 15, "low": 9, "close": 9, "volume": 100},
      {"time": "2026-01-02", "open": 19, "high": 25, "low": 19, "close": 19, "volume": 300}]
check("VWAP weights (high+low+close)/3 by volume, not the close",
      indicators.vwap(vw, 2) == [{"time": "2026-01-02", "value": 18.5}],
      indicators.vwap(vw, 2))

# --- OBV is volume SIGNED by direction ---------------------------------------
# Unsigned it is just cumulative volume, which rises forever and reads as
# accumulation on the way down.
obv_bars = bars([10, 11, 11, 9])
for _i, _v in enumerate([100, 200, 300, 400]):
    obv_bars[_i]["volume"] = _v
check("OBV adds volume on an up close, subtracts it on a down close, "
      "and ignores an unchanged one",
      [p["value"] for p in indicators.obv(obv_bars)] == [0.0, 200.0, 200.0, -200.0],
      [p["value"] for p in indicators.obv(obv_bars)])

# --- Keltner bands are ATR-wide, and the multiplier is a real argument -------
# Keltner and Bollinger look alike on a chart; what makes Keltner different is
# that its width is true range. Ignoring `mult` leaves a channel that still
# tracks price and is simply the wrong width.
kb = bars([10 + (i % 7) for i in range(60)])
k1 = indicators.keltner(kb, 20, 1.0, 10)
k2 = indicators.keltner(kb, 20, 2.0, 10)
check("doubling the Keltner multiplier doubles the band width",
      k1["upper"] and all(
          abs((u2["value"] - m["value"]) - 2 * (u1["value"] - m["value"])) < 1e-3
          for u1, u2, m in zip(k1["upper"], k2["upper"], k1["middle"])),
      len(k1["upper"]))
_atr_by = {p["time"]: p["value"] for p in indicators.atr(kb, 10)}
check("Keltner width is the ATR at that bar, not the close dispersion",
      all(abs((u["value"] - m["value"]) - 2 * _atr_by[m["time"]]) < 1e-3
          for u, m in zip(k2["upper"], k2["middle"])))

# --- configured oscillator bands must reach the chart ------------------------
# RonnieV's whole %R method is the bands at 0 and -100 rather than -20/-80: he
# draws structure on the oscillator itself, so leaving the textbook guides in
# place would draw somebody else's chart under his name.
_default_wr = indicators.compute(d, ["willr"])["willr"]
_ronnie_wr = indicators.compute(d, ["willr:12:0:-100"])["willr:12:0:-100"]
check("an oscillator's default bands are its textbook levels",
      _default_wr["bounds"] == [-80, -20], _default_wr["bounds"])
check("configured bands replace the textbook ones rather than being ignored",
      _ronnie_wr["bounds"] == [-100.0, 0.0], _ronnie_wr["bounds"])
check("a parameter below its minimum is clamped up, not passed through",
      indicators.compute(d, ["sma:1"])["sma:1"]["args"] == [2],
      indicators.compute(d, ["sma:1"])["sma:1"]["args"])


# ------------------------------------------------------- volume profile ----
# Volume by price. Most of the volume is placed in a narrow band so the point
# of control is known in advance; the rest is spread thin above it.
_vp_bars = []
for i in range(60):
    if i < 40:
        lvl, vol = 50.0 + (i % 3) * 0.1, 1000
    else:
        lvl, vol = 60.0 + (i - 40) * 0.5, 50
    _vp_bars.append({"time": f"2026-01-{1 + i % 28:02d}" if i < 28 else f"2026-02-{1 + (i - 28) % 28:02d}",
                     "open": lvl, "high": lvl + 0.3, "low": lvl - 0.3, "close": lvl, "volume": vol})
_vp = indicators.volume_profile(_vp_bars, lookback=60, bins=20)
check("volume profile: the bins account for all of the volume",
      _vp and abs(sum(b["volume"] for b in _vp["bins"]) - _vp["total"]) < 1e-3, _vp and _vp["total"])
check("volume profile: the point of control is where the volume actually is",
      _vp and _vp["poc"]["low"] <= 50.3 and _vp["poc"]["high"] >= 49.7, _vp and _vp["poc"])
check("volume profile: the value area holds at least 70% of volume",
      _vp and sum(b["share"] for b in _vp["bins"]
                  if b["low"] >= _vp["value_area"]["low"] and b["high"] <= _vp["value_area"]["high"]) >= 0.70,
      _vp and _vp["value_area"])
check("volume profile: too little history yields nothing rather than a histogram of noise",
      indicators.volume_profile(_vp_bars[:5]) is None)
check("volume profile is not a chart indicator (a histogram by price cannot be drawn by time)",
      "volume_profile" not in indicators.REGISTRY and "vprofile" not in indicators.REGISTRY)


# ---- Rolling window extremes must be bit-identical to a rescan ------------
# williams_r, stochastic and ichimoku were rewritten from "rescan the window
# per bar" to a monotonic deque. The verdict engine reads these, so the new
# code has to reproduce the old values exactly — same rounding, same warm-up,
# same None handling — across random, flat, gapping and too-short series.
import random as _random

def _ref_williams(bars_, period, upper=-20.0, lower=-80.0):
    out = []
    for i in range(period - 1, len(bars_)):
        w = bars_[i - period + 1:i + 1]
        hh, ll = max(b["high"] for b in w), min(b["low"] for b in w)
        rng = hh - ll
        val = -50.0 if rng < 1e-12 else -100.0 * (hh - bars_[i]["close"]) / rng
        out.append({"time": bars_[i]["time"], "value": round(val, 2)})
    return out

def _ref_stoch(bars_, period=14, smooth=3):
    raw = []
    for i in range(period - 1, len(bars_)):
        w = bars_[i - period + 1:i + 1]
        hh, ll = max(b["high"] for b in w), min(b["low"] for b in w)
        rng = hh - ll
        val = 50.0 if rng < 1e-12 else 100.0 * (bars_[i]["close"] - ll) / rng
        raw.append({"time": bars_[i]["time"], "value": round(val, 2)})
    d = indicators.sma([{"time": p["time"], "close": p["value"]} for p in raw], smooth)
    return {"k": raw, "d": d}

def _ref_ichimoku(bars_, tenkan=9, kijun=26, senkou=52):
    def midpoint(i, n):
        if i < n - 1:
            return None
        w = bars_[i - n + 1:i + 1]
        return (max(b["high"] for b in w) + min(b["low"] for b in w)) / 2
    conv, base, span_a, span_b, lag = [], [], [], [], []
    for i, b in enumerate(bars_):
        t, k = midpoint(i, tenkan), midpoint(i, kijun)
        if t is not None:
            conv.append({"time": b["time"], "value": round(t, 4)})
        if k is not None:
            base.append({"time": b["time"], "value": round(k, 4)})
        ahead = i + kijun
        future = bars_[ahead]["time"] if ahead < len(bars_) else None
        if t is not None and k is not None and future:
            span_a.append({"time": future, "value": round((t + k) / 2, 4)})
        sb = midpoint(i, senkou)
        if sb is not None and future:
            span_b.append({"time": future, "value": round(sb, 4)})
        if i >= kijun:
            lag.append({"time": bars_[i - kijun]["time"], "value": b["close"]})
    return {"conversion": conv, "base": base, "span_a": span_a,
            "span_b": span_b, "lagging": lag}

def _rand_bars(n, seed, flat=False, gaps=False):
    rnd = _random.Random(seed)
    out, px = [], 100.0
    for i in range(n):
        if not flat:
            px = max(0.5, px * (1 + rnd.gauss(0, 0.03)))
            if gaps and rnd.random() < 0.1:
                px *= rnd.choice([0.6, 1.5])          # an overnight gap
        spread = 0 if flat else abs(rnd.gauss(0, 0.02)) * px
        out.append({"time": f"2020-01-01T{i:05d}", "open": px, "close": px,
                    "high": px + spread, "low": px - spread, "volume": 1000})
    return out

_cases = [("random", _rand_bars(600, 1)), ("random 2", _rand_bars(300, 7)),
          ("gapping", _rand_bars(400, 3, gaps=True)), ("flat", _rand_bars(120, 0, flat=True)),
          ("short (one bar)", _rand_bars(1, 2)), ("short (13 bars)", _rand_bars(13, 4)),
          ("exactly the period", _rand_bars(14, 5)), ("empty", [])]
for name, bs in _cases:
    for period in (2, 5, 14):
        check(f"williams_r({period}) rolling == rescan on {name}",
              indicators.williams_r(bs, period) == _ref_williams(bs, period))
        check(f"stochastic({period}) rolling == rescan on {name}",
              indicators.stochastic(bs, period) == _ref_stoch(bs, period))
    check(f"ichimoku rolling == rescan on {name}",
          indicators.ichimoku(bs) == _ref_ichimoku(bs))
    check(f"ichimoku(3,7,20) rolling == rescan on {name}",
          indicators.ichimoku(bs, 3, 7, 20) == _ref_ichimoku(bs, 3, 7, 20))
# Ties between equal periods must not collapse the three lines into one.
_b = _rand_bars(200, 9)
check("ichimoku with tenkan == kijun still matches the rescan",
      indicators.ichimoku(_b, 9, 9, 52) == _ref_ichimoku(_b, 9, 9, 52))

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
