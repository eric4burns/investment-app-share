"""Structure detection.

A drawn line looks authoritative whether or not it means anything, so most of
these tests are about what the module REFUSES to draw: lines price has closed
through, lines projected further than they were confirmed over, lines nothing
has traded near in a year, and channels that are really just the bounding box of
the window.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspect as _inspect

from app import structure as S


def _inspect_zones_sorts() -> int:
    return _inspect.getsource(S.zones).count("out.sort(")

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def bar(i, high, low, close=None):
    return {"time": f"2026-01-{i+1:02d}" if i < 31 else f"2026-02-{i-30:02d}",
            "open": low, "high": high, "low": low,
            "close": close if close is not None else (high + low) / 2, "volume": 100}


# ---------------------------------------------------------------- pivots ----
# A clean zig-zag: peaks at 5, 15, 25 and troughs at 10, 20.
zig = []
for i in range(31):
    phase = i % 10
    level = 100 + (5 - abs(phase - 5)) * 2
    zig.append(bar(i, level + 1, level - 1))
pv = S.pivots(zig, 3, 3)
check("pivots finds both highs and lows in a zig-zag",
      any(p["kind"] == "high" for p in pv) and any(p["kind"] == "low" for p in pv))
check("every pivot carries its index for later line fitting",
      all("index" in p for p in pv))

flat = [bar(i, 100, 100) for i in range(20)]
check("a flat series produces no support pivots",
      not any(p["kind"] == "low" for p in S.pivots(flat, 3, 3)),
      "equal bars must not each be declared a turning point")

# Highs and lows are tested INDEPENDENTLY, not as a chain. One outside bar in a
# quiet stretch is genuinely both the local high and the local low, and an elif
# here would declare it a high and then never look for support at all — which
# silently halves the structure every support line is fitted from.
outside = [bar(i, 105.0, 95.0, 100.0) if i == 10 else bar(i, 101.0, 99.0, 100.0)
           for i in range(20)]
_ob = [p["kind"] for p in S.pivots(outside, 3, 3) if p["index"] == 10]
check("one outside bar is registered as both a high AND a low",
      sorted(_ob) == ["high", "low"], str(_ob))

# An oscillator series has one value per bar and no OHLC at all. This is the
# case that makes drawing on the W%R pane possible.
osc = [{"time": f"2026-01-{i+1:02d}", "value": 50 + (5 - abs(i % 10 - 5)) * 4}
       for i in range(31)]
check("pivots works on a value-only series", S.pivots(osc, 3, 3))
check("typical_range handles a value-only series", S.typical_range(osc) > 0)


# ---------------------------------------------------------------- labels ----
seq = [{"time": "a", "price": 10, "kind": "low", "index": 0},
       {"time": "b", "price": 20, "kind": "high", "index": 1},
       {"time": "c", "price": 12, "kind": "low", "index": 2},    # higher low
       {"time": "d", "price": 25, "kind": "high", "index": 3},   # higher high
       {"time": "e", "price": 11, "kind": "low", "index": 4},    # lower low
       {"time": "f", "price": 22, "kind": "high", "index": 5}]   # lower high
got = [p["label"] for p in S.labels(seq)]
check("HH / HL / LH / LL match a hand-labelled sequence",
      got == ["L", "H", "HL", "HH", "LL", "LH"], got)


# ------------------------------------------------------------ trendlines ----
# Price riding a rising support line, touching it four separate times.
rising = []
for i in range(60):
    floor = 100 + i * 0.5
    # The dip has to clear two thresholds: deeper than the line's own drift, or
    # the rising floor leaves the "touch" bar higher than the one before it; and
    # deeper than the touch band, or every bar counts as in-band and the whole
    # run collapses into a single touch.
    low = floor if i % 15 == 0 else floor + 10
    rising.append(bar(i, floor + 14, low, floor + 12))
lines = S.trendlines(rising, min_touches=2)
sup = [l for l in lines if l["side"] == "support"]
check("a rising support line is found under price riding it", sup)
check("the line records how many separate times it was touched",
      sup and sup[0]["touches"] >= 2, sup[0]["touches"] if sup else None)

# Consecutive bars sitting inside the band are one test, not one per bar.
#
# The fixture needs TWO separate low pivots or no line can be fitted at all and
# every assertion below it passes on an empty list. It also needs bars barely a
# unit tall: the touch band is half a typical bar, so on wide bars every low in
# the series falls inside it and the lean cannot be distinguished from the rest.
hugging = []
for i in range(70):
    if i in (8, 60):
        low = 100.0                  # the two anchors
    elif 25 <= i <= 45:
        low = 100.2                  # one long lean, 21 bars inside the band
    else:
        low = 103.0
    hugging.append(bar(i, low + 1.0, low, low + 0.5))
hug = [l for l in S.trendlines(hugging, min_touches=2) if l["side"] == "support"]
check("a line is fitted along the lean at all", hug, "otherwise the count below is vacuous")
check("consecutive in-band bars count as ONE touch, not one each",
      hug and max(l["touches"] for l in hug) <= 4,
      f"{[l['touches'] for l in hug]} — 21 bars leaning on the level is one test of it")

# A line price has closed decisively through must not come back as a live line.
#
# The collapse runs to the last bar on purpose. Bottoming out mid-series
# confirms a fresh low pivot, and a NEW line gets fitted through the crash low
# that was never broken — so the suite passed while the rule it names was gone.
broken = []
for i in range(70):
    line = 100 + i * 0.5
    if i < 58:
        low = line if i in (10, 30, 50) else line + 8
        close = line + 10
    else:
        low = line - 6 * (i - 57)                    # closes decisively through
        close = low + 1
    broken.append(bar(i, max(line + 14, low + 2), low, close))
check("the broken fixture has pivots a line could be fitted from",
      len([p for p in S.pivots(broken, 3, 3) if p["kind"] == "low"]) >= 2)
check("a support line price closed through is rejected outright",
      not [l for l in S.trendlines(broken, min_touches=2) if l["side"] == "support"])
check("and without asking for flipped lines, nothing broken comes back at all",
      not [l for l in S.trendlines(broken, min_touches=2) if l.get("flipped_from")])

# The identical shape without the collapse must still yield the line, or the
# check above is only proving that this fixture has no structure in it.
intact = []
for i in range(70):
    line = 100 + i * 0.5
    low = line if i in (10, 30, 50) else line + 8
    intact.append(bar(i, line + 14, low, line + 10))
_intact = [l for l in S.trendlines(intact, min_touches=2) if l["side"] == "support"]
check("the same line, never closed through, survives",
      _intact, "the break rule must reject broken lines, not all lines")

# A line is never drawn further past its second anchor than the distance it was
# confirmed over. Asserting on `span` alone tests min_touches' sibling gate, not
# this one: it is the DRAWN endpoint that has to stop early.
_at = {b["time"]: i for i, b in enumerate(intact)}
check("no line is drawn further past its anchors than it was confirmed over",
      all(_at[l["to"]["time"]] - _at[l["anchors"][1]] <= l["span"] for l in _intact),
      str([(l["span"], _at[l["anchors"][1]], _at[l["to"]["time"]]) for l in _intact]))
check("a line whose projection was cut short says so",
      any(not l["reaches_present"] for l in _intact),
      "otherwise the cap above is never exercised on this fixture")

# Two pivots close together are not enough history to draw a line from.
near_pivots = []
for i in range(60):
    high = 120.0 if i in (20, 26) else 119.0 if i == 40 else 112.0
    near_pivots.append(bar(i, high, high - 2.0, high - 1.0))
check("the min_span fixture really does have pivots closer than the floor",
      len([p for p in S.pivots(near_pivots, 3, 3) if p["kind"] == "high"]) >= 3)
# `limit` is raised past the default two, or a short line that the module wrongly
# accepted would still be sorted off the end of the list and never seen here.
_short = S.trendlines(near_pivots, min_touches=2, limit=6)
check("a line is never anchored across fewer than eight bars",
      all(l["span"] >= 8 for l in _short), str([l["span"] for l in _short]))

# A line nothing has traded near for a long time is irrelevant, not valid.
#
# Filtering the result by the same distance rule the module applies proves
# nothing — it restates the implementation and passes on an empty list. The line
# has to be one that would otherwise qualify: unbroken, two touches, wide span.
drifted = []
for i in range(90):
    line = 100 + i * 0.2
    if i < 45:
        low = line if i in (8, 30) else line + 5
        close = line + 7
    else:
        low, close = line + 120, line + 125          # price leaves the line behind
    drifted.append(bar(i, max(line + 10, low + 2), low, close))
check("a line price has drifted far away from is dropped as irrelevant",
      not [l for l in S.trendlines(drifted, min_touches=2) if l["side"] == "support"],
      str(S.trendlines(drifted, min_touches=2)))

# ...and the identical construction, with price still beside the line, keeps it.
stayed = []
for i in range(90):
    line = 100 + i * 0.2
    low = line if i in (8, 30, 60) else line + 5
    stayed.append(bar(i, line + 10, low, line + 7))
check("the same line is kept while price is still trading beside it",
      [l for l in S.trendlines(stayed, min_touches=2) if l["side"] == "support"],
      "distance is what disqualifies the drifted line, not its shape")

# Ranked by span, not by touches. The retraction is only real if the ordering
# actually follows it: the module still decides which lines a chart shows.
_ranked = S.trendlines(stayed, min_touches=2, limit=5)
check("lines are ranked longest-anchored first, not most-touched first",
      all(a["span"] >= b["span"] for a, b in zip(_ranked, _ranked[1:])
          if a["side"] == b["side"]),
      str([(l["side"], l["span"], l["touches"]) for l in _ranked]))


# -------------------------------------------------------------- typical -----
# The unit must track volatility, not price level — this is what stopped SPY
# from reporting dozens of touches on a meaningless line.
cheap = [bar(i, 10.5, 9.5) for i in range(30)]
pricey = [bar(i, 1000.5, 999.5) for i in range(30)]
check("typical_range is about movement, not price level",
      abs(S.typical_range(cheap) - S.typical_range(pricey)) < 0.01,
      (S.typical_range(cheap), S.typical_range(pricey)))


# ------------------------------------------------------------------ fib -----
leg = [bar(i, 100 + i, 100 + i - 1, 100 + i) for i in range(101)]   # 99 -> 200
f = S.fib(leg, lookback=200)
check("fib reads a rising leg as rising", f and f["direction"] == "up", f and f["direction"])
levels = {l["ratio"]: l["price"] for l in f["levels"]} if f else {}
low, high = f["from"]["price"], f["to"]["price"]
span = high - low
check("0.5 retracement is the midpoint of the leg",
      abs(levels.get(0.5, 0) - (high - span * 0.5)) < 0.01, levels.get(0.5))
check("0.618 retracement is hand-checkable",
      abs(levels.get(0.618, 0) - (high - span * 0.618)) < 0.01, levels.get(0.618))
check("1.618 extension projects beyond the high",
      levels.get(1.618, 0) > high, levels.get(1.618))
check("StonkChris's exact ratios are all present",
      {0.5, 0.618}.issubset(levels) and {1.0, 1.618, 2.0}.issubset(levels))

# The same two prices describe a completely different setup depending on order.
falling = list(reversed([dict(b, time=leg[i]["time"]) for i, b in enumerate(leg)]))
fd = S.fib(falling, lookback=200)
check("direction is set by which extreme came LAST, not by price alone",
      fd and fd["direction"] == "down", fd and fd["direction"])

# Direction alone is cheap to get right and worthless on its own: the LEVELS
# are the analysis, and on a falling leg they are built from the other end.
# A retracement out of a decline is resistance measured UP from the low; using
# the rising formula puts 0.236 at 176 instead of 123, which is a different
# trade entirely — and 0.5 lands on the same number either way, so the midpoint
# check above cannot see the difference.
dlevels = {(l["kind"], l["ratio"]): l["price"] for l in fd["levels"]}
dhigh, dlow = fd["from"]["price"], fd["to"]["price"]
dspan = dhigh - dlow
check("a falling leg retraces UP from the low, not down from the high",
      abs(dlevels[("retracement", 0.236)] - (dlow + dspan * 0.236)) < 0.01,
      f"{dlevels[('retracement', 0.236)]} vs {dlow + dspan * 0.236:.3f}")
check("a falling leg's extension projects DOWN past the low",
      dlevels[("extension", 1.618)] < dlow,
      dlevels[("extension", 1.618)])

# A deep decline pushes the far extensions below zero, and a level priced at
# -21.50 drawn beside real ones destroys trust in all of them.
deep = [bar(i, 100 - i * 0.9, 99 - i * 0.9, 100 - i * 0.9) for i in range(101)]
fdeep = S.fib(deep, lookback=200)
check("no level is ever drawn at or below zero",
      all(l["price"] > 0 for l in fdeep["levels"]),
      str([l["price"] for l in fdeep["levels"]]))
check("the impossible extensions are dropped, not clamped to zero",
      {l["ratio"] for l in fdeep["levels"] if l["kind"] == "extension"} == {1.0},
      "1.618 and 2.0 price below zero here and must simply not appear")


# -------------------------------------------------------------- channel -----
# The old fixture here was a smooth ramp with no turning points, so it produced
# no trendlines, so the loop below it never ran and channel() had no test at
# all. A channel needs price actually oscillating between two edges.
def channel_bars(n=90, slope=0.4, width=10.0, period=15, amp=1.0):
    out = []
    for i in range(n):
        phase = (i % period) / period
        tri = phase * 2 if phase < 0.5 else (1 - phase) * 2   # 0 -> 1 -> 0
        mid = 100 + i * slope + width * tri
        out.append(bar(i, mid + amp, mid - amp, mid))
    return out


noisy = channel_bars()
ch_lines = S.trendlines(noisy, min_touches=2)
check("the channel fixture produces lines to hang a channel on", ch_lines,
      "an empty list here makes every channel check below it vacuous")

_unit = S.typical_range(noisy)
_rng = max(b["high"] for b in noisy) - min(b["low"] for b in noisy)
_at_n = {b["time"]: i for i, b in enumerate(noisy)}
_chans = [(l, S.channel(noisy, l)) for l in ch_lines]
_chans = [(l, c) for l, c in _chans if c]
check("a channel is returned for a series that has two edges", _chans)

for _l, _c in _chans[:1]:
    check("a returned channel is never wider than the window's own range",
          abs(_c["offset"]) <= _rng * 0.6, abs(_c["offset"]))
    check("a returned channel is at least one typical bar wide",
          abs(_c["offset"]) >= _unit)
    # The far edge must pass through the pivot it names. This is what broke when
    # the line's endpoint was paired with the last bar instead of its own: the
    # slope flattened and the "parallel" edge missed its own anchor.
    _i0, _i1, _ia = (_at_n[_c["from"]["time"]], _at_n[_c["to"]["time"]],
                     _at_n[_c["anchor"]])
    _slope = (_c["to"]["price"] - _c["from"]["price"]) / (_i1 - _i0)
    _edge_at_anchor = _c["from"]["price"] + _slope * (_ia - _i0)
    _anchor_prices = [p["price"] for p in S.pivots(noisy, 3, 3)
                      if p["time"] == _c["anchor"]]
    check("the far edge actually passes through the pivot it names as its anchor",
          any(abs(_edge_at_anchor - p) < 0.01 for p in _anchor_prices),
          f"edge at {_edge_at_anchor:.3f}, pivots there {_anchor_prices}")

# Every line above reaches the present, so pairing the line with the last bar
# rather than with its own endpoint makes no difference to any of them. A line
# whose projection was cut short is the normal case and the one that exposed
# the bug: the slope flattens and the parallel edge misses its own anchor.
capped = []
for i in range(100):
    if i < 62:
        phase = (i % 15) / 15
        tri = phase * 2 if phase < 0.5 else (1 - phase) * 2
        mid = 100 + i * 0.4 + 10 * tri
    else:
        mid = 124.7 + (i - 61) * 0.01           # structure stops; price goes quiet
    capped.append(bar(i, mid + 1, mid - 1, mid))
_at_c = {b["time"]: i for i, b in enumerate(capped)}
_cap = [(l, S.channel(capped, l)) for l in S.trendlines(capped, min_touches=2)]
check("the capped fixture yields a line that stops short of the present",
      any(not l["reaches_present"] for l, _c in _cap), str([l for l, _ in _cap]))
for _l, _c in _cap[:1]:
    check("a projection-capped line still gets a channel", _c is not None)
    if _c:
        _i0, _i1 = _at_c[_c["from"]["time"]], _at_c[_c["to"]["time"]]
        _sl = (_c["to"]["price"] - _c["from"]["price"]) / (_i1 - _i0)
        _val = _c["from"]["price"] + _sl * (_at_c[_c["anchor"]] - _i0)
        _px = [p["price"] for p in S.pivots(capped, 3, 3) if p["time"] == _c["anchor"]]
        check("its edge is measured against its own endpoint, not the last bar",
              any(abs(_val - p) < 0.01 for p in _px),
              f"edge at {_val:.3f} but its named anchor sits at {_px}")

# The two width floors, exercised through the knobs rather than by hunting for
# a fixture that happens to violate each one.
_l0 = ch_lines[0]
check("a channel narrower than the floor is refused rather than drawn",
      S.channel(noisy, _l0, min_width=100.0) is None)
check("a channel wider than the bars-wide cap is refused",
      S.channel(noisy, _l0, max_width=0.5) is None)

# The bounding-box cap is a separate rule from the bars-wide one, and only it
# stops a "channel" that is really the whole window: a flat resistance at 120
# with one spike to 60 under it is a 58-wide gap on a 60-wide chart.
spike = []
for i in range(70):
    high = 120.0 if i in (15, 35, 55) else 116.0
    low = high - 6.0
    if i == 45:
        high, low = 66.0, 60.0
    spike.append(bar(i, high, low, (high + low) / 2))
check("the spike fixture yields a line to test the cap against",
      S.trendlines(spike, min_touches=2))
check("a channel wider than 60% of the window's own range is refused",
      all(S.channel(spike, l, max_width=1e9) is None
          for l in S.trendlines(spike, min_touches=2)),
      "max_width is lifted here so only the bounding-box rule can reject it")

# A pivot from before the line's first anchor sits on a BACKWARD extrapolation
# of it, so the "furthest" pivot becomes simply the oldest one.
early = []
for i in range(70):
    high = 120.0 if i in (20, 40, 60) else 117.0
    low = high - 3.0
    if i == 5:
        high, low = 106.0, 100.0      # deeper, but before the line existed
    if i == 30:
        high, low = 114.0, 108.0      # the real opposite edge
    early.append(bar(i, high, low, (high + low) / 2))
_elines = S.trendlines(early, min_touches=2)
check("the early-pivot fixture yields a line", _elines)
_echans = [(l, S.channel(early, l)) for l in _elines]
check("a channel is anchored inside its line's own lifetime, never before it",
      all(c is not None and c["anchor"] >= l["from"]["time"] for l, c in _echans),
      str([(l["from"]["time"], c and c["anchor"]) for l, c in _echans]))


# --------------------------------------------------------------- detect -----
d = S.detect(zig)
check("detect returns the drawable set", {"pivots", "trendlines", "channels", "fib"} <= set(d))
check("detect reports the window it actually read", d.get("window"))
check("detect refuses a series too short to have structure",
      S.detect(zig[:5]).get("insufficient"))
check("detect works unchanged on an oscillator series",
      not S.detect(osc).get("insufficient"))

# Structure is read off a window, not off all history — otherwise the widest
# bounding channel wins and it is anchored to a different company.
long_series = [bar(i % 31, 100 + i, 99 + i) for i in range(400)]
check("detect reads a bounded window rather than all history",
      S.detect(long_series, lookback=120)["bars"] == 120)

# --- the strength claim, and why it is gone ---------------------------------
# The module used to rank and thicken lines by touch count, on the stated
# grounds that "a weak line is visibly weak". Shuffling a series' own
# bar-to-bar returns — same length, same volatility, same bar shapes, order
# destroyed — showed that touch count carries no such information, and on real
# data runs backwards: a trending series gives a straight line FEWER chances to
# be retouched than a choppy one does. These guard the retraction.
import random as _random

_rng = _random.Random(11)


def _walk(n=140, sd=0.02):
    px, out = 100.0, []
    for i in range(n):
        px *= 1 + _rng.gauss(0, sd)
        out.append({"time": f"2026-{i//28+1:02d}-{i%28+1:02d}", "open": px,
                    "high": px * (1 + abs(_rng.gauss(0, sd / 2))),
                    "low": px * (1 - abs(_rng.gauss(0, sd / 2))),
                    "close": px, "volume": 1})
    return out


_noise_touches = []
for _ in range(25):
    _d = S.detect(_walk())
    if not _d.get("insufficient"):
        _noise_touches += [l["touches"] for l in _d["trendlines"]]
check("pure noise still produces lines with respectable touch counts",
      _noise_touches and max(_noise_touches) >= 4,
      f"max {max(_noise_touches) if _noise_touches else 0} touches on a random walk")

check("the output declares itself unvalidated",
      S.detect(_walk()).get("unvalidated") is True)

# `confirmations` exists to answer "what evidence is there for this line BEYOND
# the two points it was drawn through". The old check asserted
# `confirmations == max(0, touches - 2)`, which is the implementation's own
# formula copied into the test — it passes for any definition of `touches` and
# says nothing about what the number means.
#
# What is actually promised: the two anchors lie on the line by construction, so
# they were never evidence for it. That is testable by counting the touches
# independently and confirming the anchors are among them.
_cw = _walk()
_cd = S.detect(_cw)
_cwin = _cw[-120:] if len(_cw) > 120 else _cw
_cunit = S.typical_range(_cwin)


def _touch_runs(points, line, unit):
    """Touches counted from the line's geometry, not from structure.py.

    A touch is the bar's own extreme within half a typical bar of the line, and
    consecutive bars inside the band are ONE test rather than one per bar.
    """
    hi, lo = S._extremes(points)
    field = hi if line["side"] == "resistance" else lo
    times = [b["time"] for b in points]
    i1, i2 = times.index(line["from"]["time"]), times.index(line["to"]["time"])
    p1 = {"index": i1, "price": line["from"]["price"]}
    p2 = {"index": i2, "price": line["to"]["price"]}
    runs, in_band = 0, False
    for i in range(i1, min(i2, len(points) - 1) + 1):
        level = S._line_at(p1, p2, i)
        near = abs(points[i][field] - level) <= unit * 0.5
        if near and not in_band:
            runs += 1
        in_band = near
    return runs


for _l in _cd["trendlines"]:
    if _l.get("flipped_from"):
        # A flipped line's touches were earned on its ORIGINAL side before the
        # break, and each retest from the new side is a confirmation.
        check("a flipped line's confirmations are its pre-break touches plus its retests",
              _l["confirmations"] == max(0, _l["touches"] - 2) + _l["retests"],
              f"{_l['touches']} touches, {_l['retests']} retests, {_l['confirmations']} confirmations")
        continue
    _independent = _touch_runs(_cwin, _l, _cunit)
    check("touches counted independently agree with what the line reports",
          _independent == _l["touches"],
          f"recomputed {_independent} against reported {_l['touches']}")
    check("confirmations are the touches that are not the line's own anchors",
          _l["confirmations"] == max(0, _independent - 2),
          f"{_l['touches']} touches, {len(_l['anchors'])} anchors, "
          f"{_l['confirmations']} confirmations")
    check("a line reports exactly two anchors, and both are on it",
          len(_l["anchors"]) == 2 and _l["anchors"][0] != _l["anchors"][1],
          str(_l["anchors"]))

# The case the field exists for: a line through two pivots that nothing else
# ever came near has NO independent evidence, and must say zero rather than two.
_bare = [{"time": f"2026-03-{i+1:02d}", "open": 100.0, "close": 100.0,
          "high": 100.0 + (0.0 if i in (0, 19) else 9.0),
          "low": 90.0 + i * 0.0 if i in (0, 19) else 99.0,
          "volume": 1} for i in range(20)]
_bl = S.trendlines(_bare, S.pivots(_bare, 2, 2), S.typical_range(_bare),
                   min_touches=2)
check("a line touched only at its two anchors reports zero confirmations",
      all(l["confirmations"] == 0 for l in _bl if l["touches"] == 2),
      f"{[(l['touches'], l['confirmations']) for l in _bl]}")

# The shuffle helper has to preserve what makes the comparison fair.
_orig = _walk()
_shuf = S._shuffled(_orig, _random.Random(3))
check("shuffling preserves length", len(_shuf) == len(_orig))
check("shuffling preserves the times, so panes still align",
      [b["time"] for b in _shuf] == [b["time"] for b in _orig])
check("shuffling produces a genuinely different path",
      any(abs(a["close"] - b["close"]) > 1e-9 for a, b in zip(_orig, _shuf)))

# ----------------------------------------------------------------- zones ----
# Horizontal support and resistance. The failure mode here is not missing a
# level, it is inventing one: a wide band containing a lot of pivots looks
# authoritative and is useless, because price crosses the whole thing in a day.
_zp = [{"time": f"2026-01-{i+1:02d}", "price": p, "kind": k, "index": i}
       for i, (p, k) in enumerate([
           (100.0, "high"), (100.4, "high"), (99.8, "low"), (100.2, "low"),
           (80.0, "low"), (80.3, "low"), (60.0, "high")])]
_z = S.zones(_zp, unit=1.0)
check("pivots at the same price become one zone",
      any(abs(z["price"] - 100.1) < 0.5 for z in _z), str([z["price"] for z in _z]))
check("a single untouched pivot is not a level",
      all(z["touches"] >= 2 for z in _z), "60.0 was alone and must not appear")
check("a zone touched from both sides is marked flipped",
      any(z["flipped"] for z in _z if abs(z["price"] - 100.1) < 0.5),
      "the 100 cluster has both highs and lows")
check("a one-sided zone is not marked flipped",
      all(not z["flipped"] for z in _z if abs(z["price"] - 80.15) < 0.5))
check("every zone reports when it was last touched",
      all(z["last"] for z in _z))

# The IREN case: 12 pivots spread over $8 on a $36 stock clustered into one
# "level" that price traverses in a single session. Width is capped at one
# typical bar precisely so that cannot be called support.
_wide = [{"time": f"2026-02-{i+1:02d}", "price": 30.0 + i * 0.9, "kind": "high", "index": i}
         for i in range(10)]
_zw = S.zones(_wide, unit=1.0)
check("a drifting run of pivots is not merged into one wide level",
      all(z["width"] <= 1.0 + 1e-9 for z in _zw),
      f"widest {max((z['width'] for z in _zw), default=0)}")
check("...and every zone stays no wider than one typical bar",
      all(z["width"] <= 1.0 + 1e-9 for z in S.zones(_zp, unit=1.0)))

# Tolerance is measured in the instrument's own bars, not in dollars, so the
# same pivots cluster differently on a volatile name and a quiet one.
# Tolerance is in units of the instrument's own bar, so the same pivots cluster
# differently on a volatile name and a quiet one. Measured by how many pivots
# end up in the largest zone: a wider bar merges what a narrow one keeps apart.
# Zone COUNT is the wrong measure and asserting on it failed — a wider
# tolerance can create qualifying zones where a narrow one left every pivot
# alone and below the two-touch floor (0 zones at unit 0.5, three at unit 2.0).
_big = max((z["touches"] for z in S.zones(_wide, unit=6.0)), default=0)
_small = max((z["touches"] for z in S.zones(_wide, unit=2.0)), default=0)
check("a bigger typical bar merges what a smaller one separates",
      _big > _small, f"largest zone holds {_big} pivots vs {_small}")
check("pivots too far apart for the instrument form no level at all",
      S.zones(_wide, unit=0.5) == [],
      "0.9 apart on a 0.5 bar is not the same price twice")

# The neighbour tolerance (0.6 of a bar) and the total-width cap (1.0 of a bar)
# are two different rules, and only the gap between them shows that the first
# one is still doing anything. Two pivots 0.8 apart on a 1.0 bar clear the width
# cap and must still fail the tolerance: they are not the same price twice.
_gap = [{"time": "2026-01-01", "price": 100.0, "kind": "high", "index": 0},
        {"time": "2026-01-02", "price": 100.8, "kind": "high", "index": 1}]
check("two pivots inside the width cap but outside the tolerance form no level",
      S.zones(_gap, unit=1.0) == [], str(S.zones(_gap, unit=1.0)))
_close = [dict(_gap[0]), dict(_gap[1], price=100.4)]
check("...while the same pair inside the tolerance does form one",
      [z["touches"] for z in S.zones(_close, unit=1.0)] == [2],
      "otherwise the check above only proves zones() found nothing")

_near = S.nearest_zones(_z, 90.0)
check("nearest_zones finds the level below price",
      _near["support"] and _near["support"]["high"] < 90.0)
check("nearest_zones finds the level above price",
      _near["resistance"] and _near["resistance"]["low"] > 90.0)
check("standing between levels means standing on neither",
      _near["at"] is None)
_on = S.nearest_zones(_z, 100.1)
check("standing inside a zone reports it",
      _on["at"] is not None and _on["at"]["low"] <= 100.1 <= _on["at"]["high"])

check("detect() returns zones so every caller reads the same levels",
      "zones" in S.detect(_walk()))
check("no zones are claimed on a series with no pivots",
      S.zones([], unit=1.0) == [] and S.zones(_zp, unit=0.0) == [])

# zones() sorted twice, and the first sort was overwritten before anything
# could read it — dead code that read like a tie-break rule and was not one.
# The surviving rule is what has to hold: a flipped level counts as one extra
# touch, so it outranks a one-sided level tested the same number of times.
_tie = [
    {"time": "2026-01-01", "price": 10.0, "kind": "high", "index": 0},
    {"time": "2026-01-02", "price": 10.05, "kind": "high", "index": 1},
    {"time": "2026-01-03", "price": 20.0, "kind": "high", "index": 2},
    {"time": "2026-01-04", "price": 20.05, "kind": "low", "index": 3},
]
_tz = S.zones(_tie, unit=1.0)
check("a flipped level outranks a one-sided one on equal touches",
      _tz and _tz[0]["flipped"] is True,
      f"order {[(z['price'], z['flipped']) for z in _tz]}")
check("zones is ordered by exactly one rule, not sorted twice",
      _inspect_zones_sorts() == 1,
      "the first of two consecutive sorts can never be observed")


# ------------------------------------------------ the breakout level ----
# A resistance line price closes decisively above, then stays above and leans
# on from the other side, is the breakout level acting as support. It used to
# be discarded with every other broken line; DGXX's chart had exactly this
# line missing.
def _flip_fixture(reclaim=False):
    out = []
    # A falling resistance line: highs at 100, 96, 92 on bars 0, 10, 20, with
    # closes well beneath it, then a decisive close above on bar 30, then
    # price leaning on the line from above (retests) or, if reclaim, closing
    # back through it.
    line = lambda i: 100.0 - 0.4 * i
    for i in range(60):
        lv = line(i)
        if i in (0, 10, 20):
            o, h, l, c = lv - 3, lv, lv - 5, lv - 2.5
        elif i < 30:
            o, h, l, c = lv - 5, lv - 3.5, lv - 7, lv - 5
        elif i == 30:
            o, h, l, c = lv - 1, lv + 8, lv - 1, lv + 7        # the break
        elif i in (36, 44) and not reclaim:
            o, h, l, c = lv + 4, lv + 5, lv + 0.2, lv + 4      # retest from above
        elif reclaim and i >= 40:
            o, h, l, c = lv - 4, lv - 3, lv - 8, lv - 7        # back through it
        else:
            o, h, l, c = lv + 4, lv + 6, lv + 3, lv + 5
        out.append({"time": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": o,
                    "high": h, "low": l, "close": c, "volume": 100})
    return out

_flip = S.trendlines(_flip_fixture(), min_touches=2, flipped=True)
_sup = [l for l in _flip if l.get("flipped_from") == "resistance"]
check("a broken resistance line price stayed above comes back as support",
      bool(_sup) and _sup[0]["side"] == "support", [(l["side"], l.get("flipped_from")) for l in _flip])
check("it names the bar it broke on and counts the retests from above",
      bool(_sup) and _sup[0].get("broke_on") and _sup[0].get("retests", 0) >= 1,
      _sup[0] if _sup else None)
check("it is drawn to the present, since the break confirmed it",
      bool(_sup) and _sup[0]["reaches_present"], _sup[0] if _sup else None)
_back = S.trendlines(_flip_fixture(reclaim=True), min_touches=2, flipped=True)
check("a broken line price then closed back through is history and is dropped",
      not [l for l in _back if l.get("flipped_from")], [(l["side"], l.get("flipped_from")) for l in _back])
_det = S.detect(_flip_fixture(), min_touches=2)
_dsup = [l for l in _det["trendlines"] if l.get("flipped_from")]
check("detect() counts the retests as confirmations",
      bool(_dsup) and _dsup[0]["confirmations"] >= 1, _dsup[0] if _dsup else None)


# ------------------------------------------- the charts saved from X, 2026-09-03
# fib(): the deep 0.786-0.887 "reversal zone" and the 1.272/1.414/1.618
# targets, as separate fields so `levels` is unchanged.
_rise = [bar(i, 100 + i * 2 + 1, 100 + i * 2 - 1) for i in range(30)]
_f = S.fib(_rise)
check("fib still returns the same level ratios it always did",
      [l["ratio"] for l in _f["levels"]] == list(S.RETRACEMENTS + S.EXTENSIONS),
      [l["ratio"] for l in _f["levels"]])
_lo, _hi = _f["from"]["price"], _f["to"]["price"]
check("rising leg: the reversal zone sits between 0.786 and 0.887 of the way back down",
      abs(_f["reversal_zone"]["high"] - (_hi - (_hi - _lo) * 0.786)) < 1e-6
      and abs(_f["reversal_zone"]["low"] - (_hi - (_hi - _lo) * 0.887)) < 1e-6,
      (_f["reversal_zone"], _lo, _hi))
check("rising leg: targets are 1.272, 1.414 and 1.618 of the leg above its low",
      [t["ratio"] for t in _f["targets"]] == [1.272, 1.414, 1.618]
      and abs(_f["targets"][0]["price"] - (_lo + (_hi - _lo) * 1.272)) < 1e-6,
      _f["targets"])
_fall = list(reversed(_rise))
for i, b in enumerate(_fall):
    b["time"] = _rise[i]["time"]
_g = S.fib(_fall)
_lo2, _hi2 = _g["to"]["price"], _g["from"]["price"]
check("falling leg: the reversal zone is 0.786-0.887 of the way back UP",
      _g["direction"] == "down"
      and abs(_g["reversal_zone"]["low"] - (_lo2 + (_hi2 - _lo2) * 0.786)) < 1e-6
      and abs(_g["reversal_zone"]["high"] - (_lo2 + (_hi2 - _lo2) * 0.887)) < 1e-6,
      (_g["reversal_zone"], _lo2, _hi2))
check("falling leg: targets below zero are dropped rather than drawn",
      all(t["price"] > 0 for t in _g["targets"]), _g["targets"])

# zones(): the role a level plays NOW, from the order of its touches.
_pv_flip = [{"time": "2026-01-01", "price": 50.0, "kind": "low", "index": 0},
            {"time": "2026-01-10", "price": 50.2, "kind": "low", "index": 9},
            {"time": "2026-01-20", "price": 49.9, "kind": "high", "index": 19}]
_z = S.zones(_pv_flip, unit=1.0)
check("a level touched twice from above and then once from below is now resistance",
      len(_z) == 1 and _z[0]["role"] == "resistance" and _z[0]["role_flipped"]
      and _z[0]["sequence"] == ["low", "low", "high"], _z)
_pv_back = [{"time": "2026-01-01", "price": 50.0, "kind": "high", "index": 0},
            {"time": "2026-01-10", "price": 50.2, "kind": "high", "index": 9},
            {"time": "2026-01-20", "price": 49.9, "kind": "low", "index": 19}]
_z2 = S.zones(_pv_back, unit=1.0)
check("a level that capped price twice and then held it from above is now support",
      len(_z2) == 1 and _z2[0]["role"] == "support" and _z2[0]["role_flipped"], _z2)
_pv_same = [{"time": "2026-01-01", "price": 50.0, "kind": "low", "index": 0},
            {"time": "2026-01-10", "price": 50.2, "kind": "low", "index": 9}]
_z3 = S.zones(_pv_same, unit=1.0)
check("a level only ever touched from one side has not flipped",
      len(_z3) == 1 and not _z3[0]["role_flipped"] and _z3[0]["role"] == "support", _z3)
_pv_mixed = [{"time": "2026-01-01", "price": 50.0, "kind": "high", "index": 0},
             {"time": "2026-01-10", "price": 50.2, "kind": "low", "index": 9},
             {"time": "2026-01-20", "price": 49.9, "kind": "low", "index": 19}]
_z4 = S.zones(_pv_mixed, unit=1.0)
check("flipped (both sides ever) and role_flipped (latest side is new) are different facts",
      len(_z4) == 1 and _z4[0]["flipped"] and not _z4[0]["role_flipped"], _z4)

# channel_touches(): what each earlier touch of the floor produced.
# A rising channel: floor at 100 + 0.5i, ceiling 10 above; price bounces
# floor-to-ceiling every 10 bars.
_ch_pts = []
for i in range(60):
    floor = 100 + 0.5 * i
    phase = i % 20
    lvl = floor + (phase if phase <= 10 else 20 - phase)
    _ch_pts.append({"time": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": lvl,
                    "high": lvl + 0.2, "low": lvl - 0.2, "close": lvl, "volume": 100})
_line = {"side": "support", "from": {"time": _ch_pts[0]["time"], "price": 100.0},
         "to": {"time": _ch_pts[59]["time"], "price": 100 + 0.5 * 59}}
_chan = {"offset": 10.0, "from": {}, "to": {}}
_rec = S.channel_touches(_ch_pts, _line, _chan, unit=1.0, tolerance=0.5)
check("the channel record finds each floor touch",
      _rec and len(_rec["floor"]) == 3, _rec and [f["time"] for f in _rec["floor"]])
check("each completed floor touch records the rally to the next touch",
      _rec and all(f["rally_pct"] is not None and f["rally_pct"] > 8 for f in _rec["floor"][:-1]),
      _rec and _rec["floor"])
check("the last touch is marked open when nothing has followed it yet",
      _rec and _rec["floor"][-1]["open"], _rec and _rec["floor"][-1])
check("ceiling touches record the fade to the next one",
      _rec and len(_rec["ceiling"]) == 3
      and all(c["fade_pct"] is not None and c["fade_pct"] < -3 for c in _rec["ceiling"][:-1]),
      _rec and _rec["ceiling"])
check("the edges are extrapolated to the last bar",
      _rec and abs(_rec["lower_now"] - (100 + 0.5 * 59)) < 1e-6
      and abs(_rec["upper_now"] - (110 + 0.5 * 59)) < 1e-6, _rec and (_rec["lower_now"], _rec["upper_now"]))
check("a channel whose anchors are not in the window yields nothing rather than a guess",
      S.channel_touches(_ch_pts, dict(_line, **{"from": {"time": "1999-01-01", "price": 1}}), _chan, 1.0) is None)

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
