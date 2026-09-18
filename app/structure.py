"""Market structure, computed so the chart can draw what analysts draw by hand.

Three of the people encoded in this project — RonnieV, StonkChris and Cantonese
Cat — read charts the same unusual way: they draw structure ON the chart,
including on the oscillator pane, rather than checking an indicator against a
threshold. RonnieV sets his Williams %R bands to 0 and -100 precisely so the
pane is free to draw in.

Every function here therefore works on either OHLC bars or a plain value series,
because a trendline on RSI is the same computation as a trendline on price.

WHAT THESE LINES ARE, AND WHAT THEY ARE NOT

They are geometry: straight lines connecting recent pivots that price has not
since closed through. That is all they are, and this module used to claim more.

The original claim was that the touch count made a weak line visibly weak. It
was tested by shuffling each series' own bar-to-bar returns — same length, same
volatility, same bar shapes, order destroyed — and refitting. The result killed
the claim outright. On 400 random walks at default settings, 385 produced at
least one "confirmed" line with a median of five touches. Worse, on real data
the effect runs BACKWARDS: IREN, SPY and NVDA each score fewer touches than
their own shuffles (5-7 against a noise median of 9-10), because a trending
series gives a straight line fewer chances to be retouched than a choppy one
does. A bounce-based score — touches that price then moved away from — was tried
next and discriminates no better.

So touch count is not weak evidence of a line's strength. It is no evidence, and
in the wrong direction. Nothing here ranks or thickens a line by it, and the
count is reported as a plain fact about the drawing rather than as a grade.

What the module does still guarantee is narrower and honest: a line is anchored
across a real span, is never projected further than the distance it was
confirmed over, is dropped once price closes decisively through it, and is
dropped when price has drifted far enough away that it no longer describes
anything current.
"""
from __future__ import annotations

import random

# Retracements and extensions StonkChris uses by name: 0.5 is his trigger, and
# 1 / 1.618 / 2 are his targets.
RETRACEMENTS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSIONS = (1.0, 1.618, 2.0)

# Two further sets, read off the charts the user saved from X on 2026-09-03
# (research/charts-2026-09-03-x-accounts.md). They are kept SEPARATE from the
# lists above because those feed a weighted evidence item and a change there
# would move live calls before anything had been measured.
#
# The reversal zone is the deep end of a pullback: 0.786 to 0.887 of the leg.
# Mind Investor labels exactly this band "Reversal Zone" on SMR; Freedom By 40
# boxes 0.618-0.786 on IREN's weekly; the SIVE wave count marks 0.786 and
# 0.887 as where the correction ends. It is where a correction is nearly the
# whole prior move and either holds or the leg is over.
DEEP_RETRACEMENTS = (0.786, 0.887)
# Targets above the leg, the way AsafNaaman15 draws them on ASST (1.272,
# 1.414, 1.618) and The Analyst on ASTS (1.382, 1.618, 1.886). 1.618 is
# already in EXTENSIONS; the two intermediate ratios are where these people
# take the first trim.
TARGET_EXTENSIONS = (1.272, 1.414, 1.618)


def _extremes(points: list[dict]) -> tuple[str, str]:
    """Which fields carry the high and low.

    An indicator series has one value per bar, so its pivots are found in the
    same field twice. Keeping this in one place is what lets every function
    below serve both price and oscillator panes.
    """
    if points and "high" in points[0] and "low" in points[0]:
        return "high", "low"
    return "value", "value"


def pivots(points: list[dict], left: int = 3, right: int = 3) -> list[dict]:
    """Turning points: bars that are the extreme of their own neighbourhood.

    `left` and `right` are separate because the tradeoff is not symmetric. A
    small `right` confirms a pivot sooner and so keeps the most recent structure
    visible, at the cost of confirming some that later fail.
    """
    hi, lo = _extremes(points)
    out = []
    for i in range(left, len(points) - right):
        before, after = range(i - left, i), range(i + 1, i + right + 1)
        h, l = points[i][hi], points[i][lo]
        # Strict on the left, permissive on the right. A plateau of equal bars
        # would otherwise nominate every one of them as a turning point, and
        # requiring strictness on both sides instead discards genuine double
        # tops. Testing the two kinds independently matters too: a bar inside a
        # quiet stretch can be both the local high and the local low, and an
        # elif here silently made every such bar a high and never looked for
        # support at all.
        if (all(h > points[j][hi] for j in before)
                and all(h >= points[j][hi] for j in after)):
            out.append({"time": points[i]["time"], "price": h, "kind": "high", "index": i})
        if (all(l < points[j][lo] for j in before)
                and all(l <= points[j][lo] for j in after)):
            out.append({"time": points[i]["time"], "price": l, "kind": "low", "index": i})
    out.sort(key=lambda p: p["index"])
    return out


def labels(pivot_list: list[dict]) -> list[dict]:
    """Tag each pivot HH / HL / LH / LL against the previous pivot of its kind.

    StonkChris labels these on his charts and treats them as a precondition
    rather than commentary: a Fibonacci break only counts to him once a higher
    low has followed a lower low. The sequence is the setup, so it has to be
    computed rather than eyeballed.
    """
    out, last = [], {}
    for p in pivot_list:
        prev = last.get(p["kind"])
        if prev is None:
            tag = "H" if p["kind"] == "high" else "L"
        elif p["kind"] == "high":
            tag = "HH" if p["price"] > prev["price"] else "LH"
        else:
            tag = "HL" if p["price"] > prev["price"] else "LL"
        out.append({**p, "label": tag})
        last[p["kind"]] = p
    return out


def typical_range(points: list[dict]) -> float:
    """Average bar range — the unit everything here measures distance in.

    Tolerance cannot be a percentage of price. 1.5% of SPY is eleven dollars,
    which is several sessions of movement, so almost every bar counts as a
    touch and a meaningless line scores forty. The same 1.5% on a name that
    moves ten percent a week is far too tight to catch a real test. Measuring in
    units of the instrument's own typical bar makes one threshold work for both.
    """
    if len(points) < 2:
        return 0.0
    if "high" in points[0] and "low" in points[0]:
        spans = [b["high"] - b["low"] for b in points]
    else:
        spans = [abs(points[i]["value"] - points[i - 1]["value"])
                 for i in range(1, len(points))]
    spans = [s for s in spans if s > 0]
    return sum(spans) / len(spans) if spans else 0.0


def _line_at(p1: dict, p2: dict, index: int) -> float:
    span = p2["index"] - p1["index"]
    if span == 0:
        return p1["price"]
    slope = (p2["price"] - p1["price"]) / span
    return p1["price"] + slope * (index - p1["index"])


def _score_line(points: list[dict], p1: dict, p2: dict, side: str,
                unit: float, end: int | None = None,
                touch_k: float = 0.5, break_k: float = 1.0) -> dict | None:
    """Count touches and decide whether price has broken the line.

    A touch is the bar's own extreme coming within half a typical bar of the
    line — for a resistance line the high, for support the low. A BREAK is
    judged on the close instead, and needs a full bar's clearance, because a
    wick through a line is how a line gets tested and a close well through it is
    how it fails.
    """
    hi, lo = _extremes(points)
    field = hi if side == "resistance" else lo
    touch_band, break_band = unit * touch_k, unit * break_k
    last = len(points) - 1
    stop = last if end is None else end
    touches, broken, in_band = 0, False, False
    break_index = None
    # After a break the line is watched from the OTHER side: has price come
    # back through it (the line is simply history), or has it held there as
    # the opposite kind of level? A resistance line that price closed above
    # and then leaned on from above is the breakout level acting as support,
    # which is the line most readers of a chart draw first and this module
    # used to throw away.
    reclaimed, retests, in_retest = False, 0, False
    other = lo if side == "resistance" else hi
    # Breaks are tested all the way to the present even when the line is only
    # DRAWN to `stop`. A line whose projection was cut short is still a line
    # price may have closed through since, and drawing it as though it were
    # intact is exactly the failure this module exists to avoid.
    for i in range(p1["index"], last + 1):
        level = _line_at(p1, p2, i)
        if i <= stop and not broken:
            near = abs(points[i][field] - level) <= touch_band
            # Consecutive bars inside the band are ONE test of the line, not
            # one per bar. Counting every bar turns a single lean against a
            # level into a score of thirty.
            if near and not in_band:
                touches += 1
            in_band = near
        close = points[i].get("close", points[i].get("value"))
        if close is None:
            continue
        if not broken:
            if side == "resistance" and close > level + break_band:
                broken, break_index = True, i
            elif side == "support" and close < level - break_band:
                broken, break_index = True, i
            continue
        # Past the break. A decisive close back through it ends the story.
        if side == "resistance" and close < level - break_band:
            reclaimed = True
        elif side == "support" and close > level + break_band:
            reclaimed = True
        near = abs(points[i][other] - level) <= touch_band
        if near and not in_retest:
            retests += 1
        in_retest = near
    if broken:
        return {"touches": touches, "broken": True, "break_index": break_index,
                "reclaimed": reclaimed, "retests": retests}
    return {"touches": touches, "broken": False}


def trendlines(points: list[dict], pivot_list: list[dict] | None = None,
               unit: float | None = None, min_touches: int = 2,
               limit: int = 2, min_span: int = 8, relevance: float = 8.0,
               flipped: bool = False) -> list[dict]:
    """The best surviving trendlines, one set per side.

    A line price has closed through is dropped — unless `flipped` is set, in
    which case it is returned in its NEW role, after the intact lines. A
    resistance line broken upward, with price still above it, is the breakout
    level and comes back as support, flagged `flipped_from` so the reader
    knows it was earned by a break rather than by touches; `touches` stays the
    count that qualified it on its original side and `retests` is the count
    from the new one. A broken line that price has since closed back through
    is history and is dropped either way, since drawn on a live chart it would
    read as a level that is still holding.

    Two rules stop a line from claiming more than it earned. It must be anchored
    across at least `min_span` bars, and it is NEVER PROJECTED FURTHER THAN THE
    DISTANCE IT WAS CONFIRMED OVER. Without the second rule two pivots eight
    bars apart get extrapolated across two hundred, which on a name that has run
    hard produces a confident line at a price nothing has ever traded near.
    """
    if pivot_list is None:
        pivot_list = pivots(points)
    if unit is None:
        unit = typical_range(points)
    if not unit:
        return []
    last = len(points) - 1
    here = points[last].get("close", points[last].get("value"))
    flipped_side = {"resistance": "support", "support": "resistance"}
    cands: dict[str, list[dict]] = {"resistance": [], "support": []}
    flips: dict[str, list[dict]] = {"resistance": [], "support": []}
    for side, kind in (("resistance", "high"), ("support", "low")):
        same = [p for p in pivot_list if p["kind"] == kind]
        found = cands[side]
        for a in range(len(same)):
            for b in range(a + 1, len(same)):
                p1, p2 = same[a], same[b]
                span = p2["index"] - p1["index"]
                if span < min_span:
                    continue
                end = min(last, p2["index"] + span)
                scored = _score_line(points, p1, p2, side, unit, end)
                if not scored or scored["touches"] < min_touches:
                    continue
                if scored["broken"]:
                    # Kept only as the level it has become: price must still be
                    # on the far side, and the break itself confirms the line
                    # far enough to draw it to the present. A line reclaimed
                    # since is history.
                    if not flipped or scored["reclaimed"] or scored["break_index"] is None:
                        continue
                    end = last
                    if abs(_line_at(p1, p2, end) - here) > relevance * unit:
                        continue
                    flips[flipped_side[side]].append({
                        "side": flipped_side[side], "touches": scored["touches"],
                        "from": {"time": p1["time"], "price": round(p1["price"], 4)},
                        "to": {"time": points[end]["time"],
                               "price": round(_line_at(p1, p2, end), 4)},
                        "anchors": [p1["time"], p2["time"]],
                        "reaches_present": True,
                        "span": span,
                        "flipped_from": side,
                        "broke_on": points[scored["break_index"]]["time"],
                        "retests": scored["retests"],
                    })
                    continue
                # Judged where the line is DRAWN, not where it would be if
                # projected on. Measuring at `last` for a line that stops at
                # `end` is the same reasoning error that was fixed in channel()
                # and left here: it flipped the keep/drop verdict on 7.5% of
                # candidates, discarding lines that sit right beside price at
                # their visible endpoint.
                if abs(_line_at(p1, p2, end) - points[end].get(
                        "close", points[end].get("value", here))) > relevance * unit:
                    continue
                found.append({
                    "side": side, "touches": scored["touches"],
                    "from": {"time": p1["time"], "price": round(p1["price"], 4)},
                    "to": {"time": points[end]["time"],
                           "price": round(_line_at(p1, p2, end), 4)},
                    "anchors": [p1["time"], p2["time"]],
                    "reaches_present": end == last,
                    "span": span,
                })
    out = []
    for side in ("resistance", "support"):
        found = cands[side]
        # Ranked by SPAN, not by touches. The retraction was applied to the
        # renderer and to the docstring while this sort — and the min_touches
        # gate below — still let touch count decide which lines appear at all,
        # which is 95% of the charts. Duration is a defensible ordering in a way
        # touch count is not: a line anchored across more history is a claim
        # about a longer stretch, whatever price did in between.
        found.sort(key=lambda f: (-f["span"], f["from"]["time"]))
        out.extend(found[:limit])
    # Flipped lines come after the intact ones and do not count against their
    # limit: one per side, the longest.
    for side in ("resistance", "support"):
        flips[side].sort(key=lambda f: (-f["span"], f["from"]["time"]))
        out.extend(flips[side][:1])
    return out


def channel(points: list[dict], line: dict, pivot_list: list[dict] | None = None,
            unit: float | None = None, min_width: float = 1.0,
            max_width: float = 12.0) -> dict | None:
    """The parallel line at the furthest opposite pivot — the other edge.

    Returned only when an opposite pivot actually sits off the line. Drawing a
    channel whose second edge has never been touched invents a boundary.
    """
    if pivot_list is None:
        pivot_list = pivots(points)
    if unit is None:
        unit = typical_range(points)
    if not unit:
        return None
    want = "low" if line["side"] == "resistance" else "high"
    opposite = [p for p in pivot_list if p["kind"] == want]
    if not opposite:
        return None

    idx = {p["time"]: p["index"] for p in pivot_list}
    idx_by_time = {b["time"]: i for i, b in enumerate(points)}
    a_time, b_time = line["anchors"]
    # The line's far endpoint is at the index of line["to"], NOT at the last bar
    # — a projection-capped line stops early, which is the normal case. Pairing
    # it with len(points)-1 flattened the slope (measured: 1.0/bar became
    # 0.449/bar) and produced a "parallel" edge that missed the very pivot it
    # named as its anchor.
    end_i = idx_by_time.get(line["to"]["time"], len(points) - 1)
    p1 = {"index": idx[a_time], "price": line["from"]["price"]}
    p2 = {"index": end_i, "price": line["to"]["price"]}

    # Only pivots inside the line's own lifetime. A pivot from before the first
    # anchor sits on a backward extrapolation of the line, which on a name that
    # has run hard can be near zero or negative — and then the "furthest" pivot
    # is simply the oldest one, producing a channel wider than the chart.
    last = len(points) - 1
    end_index = end_i
    inside = [p for p in opposite if p1["index"] <= p["index"] <= end_index]
    best, best_gap = None, 0.0
    for p in inside:
        gap = p["price"] - _line_at(p1, p2, p["index"])
        if abs(gap) > abs(best_gap):
            best, best_gap = p, gap
    # A channel narrower than a bar is noise. At the other end there are two
    # caps, because either alone lets something silly through: a width in bars
    # keeps it proportionate to how the name moves, and a width as a share of
    # the window's own range stops a channel from being wider than everything
    # price did in it — which is a bounding box, not a channel.
    hi, lo = _extremes(points)
    span = max(p[hi] for p in points) - min(p[lo] for p in points)
    if not best:
        return None
    width = abs(best_gap)
    if width < min_width * unit or width > max_width * unit or width > span * 0.6:
        return None
    return {"side": "channel", "of": line["side"], "offset": round(best_gap, 4),
            "anchor": best["time"],
            "from": {"time": line["from"]["time"],
                     "price": round(line["from"]["price"] + best_gap, 4)},
            "to": {"time": line["to"]["time"],
                   "price": round(line["to"]["price"] + best_gap, 4)}}


def fib(points: list[dict], lookback: int = 120) -> dict | None:
    """Retracements and extensions from the most recent significant swing leg.

    The leg is taken between the extreme high and extreme low of the window, and
    its DIRECTION is set by which of the two happened later. That ordering is
    the whole point: the same two prices describe a rally to retrace down into
    or a fall to retrace up out of, and the levels differ completely.
    """
    window = points[-lookback:] if len(points) > lookback else points
    if len(window) < 10:
        return None
    hi, lo = _extremes(window)
    top = max(window, key=lambda b: b[hi])
    bottom = min(window, key=lambda b: b[lo])
    high, low = top[hi], bottom[lo]
    if high == low:
        return None

    rising = window.index(bottom) < window.index(top)
    span = high - low
    levels = []
    for r in RETRACEMENTS:
        price = high - span * r if rising else low + span * r
        levels.append({"ratio": r, "price": round(price, 4), "kind": "retracement"})
    for e in EXTENSIONS:
        price = low + span * e if rising else high - span * e
        levels.append({"ratio": e, "price": round(price, 4), "kind": "extension"})
    # A deep decline pushes the far extensions below zero, and a level at -21.50
    # drawn on a price chart destroys trust in the levels beside it. diagnose.py
    # already suppresses negative levels for exactly this reason.
    levels = [l for l in levels if l["price"] > 0]
    # The deep-pullback band and the trim targets, as separate fields so a
    # reader of `levels` sees exactly what it always did.
    deep = [high - span * r if rising else low + span * r for r in DEEP_RETRACEMENTS]
    reversal_zone = {"low": round(min(deep), 4), "high": round(max(deep), 4),
                     "ratios": DEEP_RETRACEMENTS}
    if reversal_zone["low"] <= 0:
        reversal_zone = None
    targets = []
    for e in TARGET_EXTENSIONS:
        price = low + span * e if rising else high - span * e
        if price > 0:
            targets.append({"ratio": e, "price": round(price, 4)})
    return {"direction": "up" if rising else "down",
            "from": {"time": (bottom if rising else top)["time"],
                     "price": round(low if rising else high, 4)},
            "to": {"time": (top if rising else bottom)["time"],
                   "price": round(high if rising else low, 4)},
            "levels": levels, "reversal_zone": reversal_zone, "targets": targets}


def zones(pivot_list: list[dict], unit: float, tolerance: float = 0.6,
          min_touches: int = 2) -> list[dict]:
    """Horizontal support and resistance: prices the market has turned at before.

    A trendline answers "where is the boundary going"; this answers the flatter
    and more commonly asked question, "what price has mattered here". They are
    different objects and neither substitutes for the other — a name can sit on
    a rising trendline and nowhere near a horizontal level, or the reverse.

    A zone is a cluster of pivots at similar prices. The clustering tolerance is
    measured in units of the instrument's own typical bar, for the same reason
    everything else here is: 1.5% of SPY is several sessions of movement, and
    the same 1.5% on a name that moves ten percent a week is far too tight.

    Two properties are worth more than the count alone:

    `flipped` marks a zone that has acted as BOTH support and resistance — it
    has turned price back from above and from below. That is the strongest kind
    of level and the one traders name out loud, and it is invisible if highs and
    lows are clustered separately.

    `last` is when the zone was last touched. A level tested four times two
    years ago and never since is a historical fact, not a live one, and sorting
    on touches alone would rank it above a level tested twice last month.
    """
    if not pivot_list or unit <= 0:
        return []
    tol = tolerance * unit
    # The total WIDTH of a zone is capped, not just the gap between neighbours.
    # Comparing each pivot against the running mean still let a chain of
    # near-misses walk one zone across the chart: IREN produced a single
    # "12-touch level" spanning 37.67 to 46.00, an $8 band on a $36 stock. That
    # is a range, not a level, and calling it support would be worse than
    # finding nothing.
    # A zone may be no wider than ONE typical bar. This is not a tuned number:
    # a band price can traverse in a single session says nothing about where to
    # act, so it is a range and not a level. IREN, which moves ~10% a day,
    # produced a "12-touch level" 8.33 wide on a $36 stock under a looser cap —
    # technically 12 pivots, and useless.
    max_width = unit
    ordered = sorted(pivot_list, key=lambda p: p["price"])
    groups: list[list[dict]] = [[ordered[0]]]
    for p in ordered[1:]:
        g = groups[-1]
        lo = min(q["price"] for q in g)
        if abs(p["price"] - g[-1]["price"]) <= tol and (p["price"] - lo) <= max_width:
            g.append(p)
        else:
            groups.append([p])

    out = []
    for g in groups:
        if len(g) < min_touches:
            continue
        prices_ = [q["price"] for q in g]
        kinds = {q["kind"] for q in g}
        # The touches in TIME order, so a reader can tell "support that became
        # resistance" from "resistance that became support". `flipped` alone
        # cannot: it says both happened, not which came last. Con's SIVE chart
        # writes the distinction out — "Previous support is now resistance" —
        # and TEM's 62 shelf was carried here as resistance after price had
        # broken above it and retested it from above, which is the other case.
        in_time = sorted(g, key=lambda q: q["time"])
        sequence = [q["kind"] for q in in_time]
        role = "resistance" if sequence[-1] == "high" else "support"
        earlier = set(sequence[:-1])
        role_flipped = bool(earlier) and sequence[-1] not in earlier
        out.append({
            "low": round(min(prices_), 4),
            "high": round(max(prices_), 4),
            "price": round(sum(prices_) / len(prices_), 4),
            "touches": len(g),
            "flipped": kinds == {"high", "low"},
            "kinds": sorted(kinds),
            "sequence": sequence,
            "role": role,
            "role_flipped": role_flipped,
            "width": round(max(prices_) - min(prices_), 4),
            "first": min(q["time"] for q in g),
            "last": max(q["time"] for q in g),
        })
    # Strongest first: a flipped level outranks a one-sided one at equal
    # touches, and touches outrank recency. Recency breaks the remaining ties.
    # One sort. There were two, and the first was overwritten by the second
    # before anything could read it — dead code that read like a tie-break rule
    # and was not one. A flipped level counts as one extra touch, so it outranks
    # a one-sided level tested the same number of times; recency breaks ties.
    out.sort(key=lambda z: (-(z["touches"] + (1 if z["flipped"] else 0)), z["last"]))
    return out


def nearest_zones(zone_list: list[dict], price: float) -> dict:
    """The zone directly below price and the one directly above it."""
    below = [z for z in zone_list if z["high"] < price]
    above = [z for z in zone_list if z["low"] > price]
    inside = [z for z in zone_list if z["low"] <= price <= z["high"]]
    return {
        "support": max(below, key=lambda z: z["high"]) if below else None,
        "resistance": min(above, key=lambda z: z["low"]) if above else None,
        "at": max(inside, key=lambda z: z["touches"]) if inside else None,
    }


def channel_touches(points: list[dict], line: dict, chan: dict, unit: float,
                    tolerance: float = 0.5, horizon: int = 60) -> dict | None:
    """What happened at each earlier touch of a channel's edges.

    The AEVA chart the user saved draws a rising channel and writes the rally
    from each touch of its floor beside the touch: +95%, +158%, +110%. That is
    the argument for buying the floor — not that the line exists, but what
    price did the last three times it was there. The cloud item already keeps
    this kind of record (`verdicts.cloud_record`); this is the same idea for a
    channel.

    A touch is a bar whose low comes within `tolerance` typical bars of the
    lower edge (or whose high reaches the upper edge). Consecutive touching
    bars are one touch. The rally after a floor touch is the highest high
    before the next floor touch, capped at `horizon` bars, as a percent of the
    touch low; the fade after a ceiling touch is the mirror.

    Edges are extrapolated from the line's anchors, because a projection-capped
    line stops before the present and the touch being asked about is usually
    today's.
    """
    if not points or not unit or not line or not chan:
        return None
    idx_by_time = {b["time"]: i for i, b in enumerate(points)}
    a_i = idx_by_time.get(line["from"]["time"])
    b_i = idx_by_time.get(line["to"]["time"])
    if a_i is None or b_i is None or b_i == a_i:
        return None
    hi, lo = _extremes(points)
    p1 = {"index": a_i, "price": line["from"]["price"]}
    p2 = {"index": b_i, "price": line["to"]["price"]}
    off = chan["offset"]
    if off < 0:
        upper_of = lambda i: _line_at(p1, p2, i)
        lower_of = lambda i: _line_at(p1, p2, i) + off
    else:
        upper_of = lambda i: _line_at(p1, p2, i) + off
        lower_of = lambda i: _line_at(p1, p2, i)
    tol = tolerance * unit

    def _runs(is_touch):
        runs, cur = [], None
        for i in range(a_i, len(points)):
            if is_touch(i):
                cur = [i] if cur is None else cur + [i]
            elif cur is not None:
                runs.append(cur)
                cur = None
        if cur is not None:
            runs.append(cur)
        return runs

    floor_runs = _runs(lambda i: points[i][lo] <= lower_of(i) + tol)
    ceil_runs = _runs(lambda i: points[i][hi] >= upper_of(i) - tol)

    floors = []
    for n, run in enumerate(floor_runs):
        touch_i = min(run, key=lambda i: points[i][lo])
        low_px = points[touch_i][lo]
        nxt = floor_runs[n + 1][0] if n + 1 < len(floor_runs) else len(points)
        end = min(nxt, touch_i + horizon, len(points))
        after = points[touch_i + 1:end]
        if not after or low_px <= 0:
            floors.append({"time": points[touch_i]["time"], "price": round(low_px, 4),
                           "rally_pct": None, "bars": 0, "open": True})
            continue
        peak = max(after, key=lambda b: b[hi])
        floors.append({"time": points[touch_i]["time"], "price": round(low_px, 4),
                       "rally_pct": round((peak[hi] / low_px - 1) * 100, 1),
                       "bars": len(after), "open": end == len(points)})
    ceilings = []
    for n, run in enumerate(ceil_runs):
        touch_i = max(run, key=lambda i: points[i][hi])
        high_px = points[touch_i][hi]
        nxt = ceil_runs[n + 1][0] if n + 1 < len(ceil_runs) else len(points)
        end = min(nxt, touch_i + horizon, len(points))
        after = points[touch_i + 1:end]
        if not after or high_px <= 0:
            ceilings.append({"time": points[touch_i]["time"], "price": round(high_px, 4),
                             "fade_pct": None, "bars": 0, "open": True})
            continue
        trough = min(after, key=lambda b: b[lo])
        ceilings.append({"time": points[touch_i]["time"], "price": round(high_px, 4),
                         "fade_pct": round((trough[lo] / high_px - 1) * 100, 1),
                         "bars": len(after), "open": end == len(points)})
    last = len(points) - 1
    return {"lower_now": round(lower_of(last), 4), "upper_now": round(upper_of(last), 4),
            "floor": floors, "ceiling": ceilings}


def _shuffled(points: list[dict], rng: random.Random) -> list[dict]:
    """Same length, same volatility, same bar shapes — structure destroyed.

    Shuffling the bar-to-bar returns keeps everything about the series except
    the ORDER, which is the only thing a trendline can be about.
    """
    closes = [p.get("close", p.get("value")) for p in points]
    rets = [closes[i] / closes[i - 1] for i in range(1, len(closes))
            if closes[i - 1]]
    if not rets:
        return points
    rng.shuffle(rets)
    hi, lo = _extremes(points)
    out, price = [], closes[0]
    for i, p in enumerate(points):
        if i:
            price *= rets[(i - 1) % len(rets)]
        base = closes[i] or 1.0
        row = {"time": p["time"], "close": price, "value": price}
        row[hi] = price * ((p[hi] / base) if base else 1.0)
        row[lo] = price * ((p[lo] / base) if base else 1.0)
        row["open"] = price
        out.append(row)
    return out


def detect(points: list[dict], left: int = 3, right: int = 3,
           min_touches: int = 3, lookback: int = 120,
           fib_lookback: int | None = None, unit_cap: float | None = None) -> dict:
    """Everything drawable for one series, price or oscillator alike.

    Structure is read off a WINDOW, not off all available history, because that
    is how it is read off a screen. Given five years of weekly bars the widest
    bounding channel is technically correct and completely useless — it is
    anchored to a low the name traded at when it was a different company. The
    window is what keeps the answer about the chart in front of you.
    """
    window = points[-lookback:] if len(points) > lookback else points
    if len(window) < (left + right + 5):
        return {"insufficient": True, "bars": len(window)}
    unit = typical_range(window)
    # The typical bar is the right unit until the window's adjusted prices dwarf
    # today's — ASST after its reverse split and long decline: an average monthly
    # range of 37 on a 27 stock, so one "zone" ran
    # from 6.70 to 34.00 and every level was a touch. `unit_cap` bounds the
    # unit as a share of the LAST price; the caller sets it per timeframe.
    last = window[-1].get("close") if "close" in window[-1] else window[-1].get("value")
    if unit_cap and last:
        unit = min(unit, abs(last) * unit_cap) or unit
    pv = pivots(window, left, right)
    lines = trendlines(window, pv, unit, min_touches, flipped=True)
    for line in lines:
        # Reported, not graded. The two anchors are on the line by construction,
        # so they were never evidence for it.
        # A flipped line adds each retest from the new side: those are the
        # touches that make a breakout level a support level.
        line["confirmations"] = max(0, line["touches"] - 2) + line.get("retests", 0)
    # A channel is a pair of parallel edges from the same stretch of price. A
    # flipped line's era is over, so it does not get one.
    channels = [c for c in (channel(window, l, pv, unit) for l in lines
                            if not l.get("flipped_from")) if c]
    pivots_labelled = labels(pv)
    return {"pivots": pivots_labelled, "trendlines": lines, "channels": channels,
            # Horizontal levels, from the same pivots the trendlines are fitted
            # to. Computed here rather than by each caller so the chart, the
            # verdict engine and the diagnosis all read the same levels.
            "zones": zones(pivots_labelled, unit),
            # Measured over its OWN window. Which move a retracement is drawn
            # from is the entire analysis — the same prices give different levels
            # depending on the leg — so it must be steerable rather than picked
            # by whatever happens to be extreme in the structure window.
            "fib": fib(points[-(fib_lookback or lookback):]
                       if len(points) > (fib_lookback or lookback) else points),
            "bars": len(window), "unit": round(unit, 4),
            # Travels with the drawing so the caller cannot present these as
            # validated. See the module docstring for how this was measured.
            "unvalidated": True,
            "window": {"from": window[0]["time"], "to": window[-1]["time"]}}
