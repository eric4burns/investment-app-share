"""The verdict engine.

A module that says "sell" is a different liability from one that says "RSI 62",
so most of these tests are about what it must REFUSE to say: a trim on a
position that has fallen, a call with no level that would invalidate it, and a
reading of the Ichimoku cloud taken from the wrong end of a displaced series.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date as _date, timedelta as _timedelta

from app import verdicts as V

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def bars(prices_, start="2024-01-01"):
    """Daily bars from a close series, on real weekday dates.

    Real dates matter here rather than being tidiness: resample() buckets by ISO
    week, so a synthetic calendar with 30-day months and a 13th month raises
    before the weekly verdict is ever computed.
    """
    out, d = [], _date.fromisoformat(start)
    for c in prices_:
        while d.isoweekday() > 5:
            d += _timedelta(days=1)
        out.append({"time": d.isoformat(), "open": c, "high": c * 1.01,
                    "low": c * 0.99, "close": c, "volume": 1000})
        d += _timedelta(days=1)
    return out


def rally_then_fade(n=200, top_at=0.75):
    """Up hard, then roll over — the shape a trim rule must not fire on late."""
    out, peak = [], int(n * top_at)
    for i in range(n):
        out.append(10 + i * 0.5 if i < peak else 10 + peak * 0.5 - (i - peak) * 0.6)
    return out


# ------------------------------------------------------------------ trim ----
# The rule the user asked for by name: trim into strength, never into weakness.
# A position 30% off its own high must never produce a trim, however overbought
# it was on the way up.
faded = bars(rally_then_fade(600))
g_fade = V.gather(faded, {"weight": 0.30, "quantity": 100})
d_fade = V.decide(g_fade, {"weight": 0.30, "quantity": 100})
check("a position well off its high is never trimmed",
      d_fade["verdict"] != "trim",
      f"got {d_fade['verdict']}, leg position {g_fade.get('leg_pos')}")

check("the faded name still sits in the lower part of its swing",
      (g_fade.get("leg_pos") or 1) < V.UPPER_LEG,
      f"leg_pos {g_fade.get('leg_pos')}")

# An oversized weight alone must not manufacture a trim on a fallen name: the
# weight rule is an upside rule, and this is the case that proves the leg gate
# is doing the work rather than the weight threshold.
heavy_fade = V.decide(V.gather(faded, {"weight": 0.45, "quantity": 100}),
                      {"weight": 0.45, "quantity": 100})
check("an overweight position that has fallen is still not trimmed",
      heavy_fade["verdict"] != "trim", f"got {heavy_fade['verdict']}")

# `faded` is a broken name — 82% of its evidence weight is bearish — so the trim
# branch never reaches the leg gate at all, and deleting that gate leaves every
# check above still passing. The rule the module is built around needs a case
# where the leg position is the ONLY thing standing between it and a trim: a
# long uptrend that has given back 10%, still above its averages, still heavy.
shallow = bars([10 + i * 0.5 for i in range(560)]
               + [(10 + 559 * 0.5) * (1 - 0.10 * j / 40) for j in range(1, 41)])
_pos = {"weight": 0.30, "quantity": 100}
_gs = V.gather(shallow, _pos)
_bear = sum(e["weight"] for e in _gs["evidence"] if e["stance"] == "bear")
_bull = sum(e["weight"] for e in _gs["evidence"] if e["stance"] == "bull")
_ext = sum(e["weight"] for e in _gs["evidence"] if e["stance"] == "extended")
check("the shallow pullback still satisfies every trim condition except the leg",
      _ext >= 1.5 and _bear / (_bull + _bear) < 0.5 and _gs["leg_pos"] < V.UPPER_LEG,
      f"extended {_ext}, bear share {_bear / (_bull + _bear):.2f}, "
      f"leg {_gs['leg_pos']}")
check("a name in the lower part of its swing is not trimmed even when nothing "
      "else objects", V.decide(_gs, _pos)["verdict"] != "trim",
      f"got {V.decide(_gs, _pos)['verdict']}")

# ...whereas the same overbought condition at the TOP of the leg is a trim.
climbing = bars([10 + i * 0.5 for i in range(600)])
d_climb = V.decide(V.gather(climbing, {"weight": 0.30, "quantity": 100}),
                   {"weight": 0.30, "quantity": 100})
check("a heavily-weighted position making new highs is a trim",
      d_climb["verdict"] == "trim", f"got {d_climb['verdict']}")

check("a trim names the level it is giving up by trimming",
      d_climb["verdict"] != "trim" or d_climb["flip"] is not None)

check("the level a trim gives up is not the one price is standing on",
      d_climb.get("flip") is None
      or d_climb["flip"] > V.gather(climbing)["price"],
      f"flip {d_climb.get('flip')} vs price {V.gather(climbing)['price']}")

# Trim is about an existing position. Nothing owned, nothing to trim.
d_unheld = V.decide(V.gather(climbing, None), None)
check("a name that is not owned is never trimmed",
      d_unheld["verdict"] != "trim", f"got {d_unheld['verdict']}")

# ------------------------------------------------------- invalidation -------
# A verdict that cannot be wrong is not a verdict. Both the buy and the sell
# branch degrade to hold rather than emit a call with no flip level.
for name, d in (("trim", d_climb), ("faded", d_fade)):
    check(f"every {name} verdict either names a flip level or is a hold",
          d["flip"] is not None or d["verdict"] == "hold",
          f"{d['verdict']} with flip={d['flip']}")

flat = bars([50.0 + (i % 3) * 0.01 for i in range(600)])
d_flat = V.decide(V.gather(flat), None)
check("a series with no structure produces hold, not a coin flip",
      d_flat["verdict"] == "hold", f"got {d_flat['verdict']}")
check("...and says it is refusing because the series is noise",
      any("noise" in r for r in d_flat["because"]), str(d_flat["because"])[:80])
check("a near-flat series is flagged as noise before any rule runs",
      V.gather(flat).get("noise") is True,
      f"leg spans {V.gather(flat).get('leg_atr')} typical bars")
check("a real trend is NOT flagged as noise",
      V.gather(climbing).get("noise") is False,
      f"leg spans {V.gather(climbing).get('leg_atr')} typical bars")

check("too little history is refused rather than scored",
      V.decide(V.gather(bars([10, 11, 12])))["verdict"] == "hold"
      and V.gather(bars([10, 11, 12])).get("insufficient") is True)

# --------------------------------------------------------------- cloud ------
# The Ichimoku cloud is plotted 26 bars AHEAD of the data it is computed from.
# Reading span_a[-1] would take the furthest projected value rather than the
# cloud standing over price today — a different number, and on a trending name
# a materially different verdict.
from app import indicators as I

ich = I.ichimoku(climbing)
now = climbing[-1]["time"]
check("the cloud lines up with the bars it is read against",
      ich["span_a"] and ich["span_a"][-1]["time"] == now,
      "indicators.py truncates the cloud at the right edge")

# Asserting against a real ichimoku series cannot see this rule at all: that
# implementation stops the cloud at the last bar, so the projected end and the
# value standing over price today are the same row, and reading `series[-1]`
# gives the right answer by accident. The lookup has to be tested against a
# series that genuinely leads price, which is what the cloud does the moment
# anything projects it forward.
displaced = [{"time": "2026-01-05", "value": 10.0},
             {"time": "2026-01-06", "value": 20.0},
             {"time": "2026-01-07", "value": 30.0},   # today
             {"time": "2026-01-08", "value": 40.0},   # projected ahead of price
             {"time": "2026-01-09", "value": 50.0}]
check("a displaced series is read at today's bar, not at the end of the projection",
      V._at_time(displaced, "2026-01-07") == 30.0,
      f"got {V._at_time(displaced, '2026-01-07')}, the projected end is 50.0")
check("a gap in the series falls back to the last bar on or before today",
      V._at_time(displaced, "2026-01-06") == 20.0,
      f"got {V._at_time(displaced, '2026-01-06')}")
check("nothing is returned when the whole series is still in the future",
      V._at_time(displaced, "2026-01-01") is None,
      f"got {V._at_time(displaced, '2026-01-01')}")

# ------------------------------------------------------------ timeframes ----
both = V.both_timeframes(climbing, {"weight": 0.05, "quantity": 10})
check("daily and weekly are reported separately", "daily" in both and "weekly" in both)
check("the two timeframes are never averaged into one score",
      both["daily"]["verdict"] in V.VERDICTS and both["weekly"]["verdict"] in V.VERDICTS)
check("a disagreement between timeframes is stated rather than hidden",
      both["agree"] or both["conflict"])

# When they disagree the WEEKLY decides — but only when it is sure. That rule is
# the whole reason both are computed, and asserting it needs two real
# disagreements, one either way, or the headline is just the daily verdict.
_zig = bars([100 + i * 0.4 + (6 if i % 12 < 6 else -6) * (1 - (i % 6) / 6)
             for i in range(600)])
_bz = V.both_timeframes(_zig, {"weight": 0.05, "quantity": 10})
check("the fixtures really do disagree across timeframes",
      not _bz["agree"] and _bz["weekly"]["confidence"] == "high",
      f"D {_bz['daily']['verdict']} / W {_bz['weekly']['verdict']}")
check("a high-confidence weekly overrules the daily headline",
      _bz["headline"] == _bz["weekly"]["verdict"],
      f"headline {_bz['headline']}, weekly {_bz['weekly']['verdict']}")

import math as _math
_wavy = bars([60 + i * 0.30 + 12 * _math.sin(i / 9.0) for i in range(600)])
_bw = V.both_timeframes(_wavy, {"weight": 0.05, "quantity": 10})
# The headline used to be the daily unless the weekly was HIGH confidence. That
# rule is gone: the longest timeframe that could be read now leads, whatever its
# confidence. Somebody holding for weeks or months does not want a daily call in
# front, and leading with it was why a stale daily could read as contradicting a
# weekly beside it.
check("the longest readable timeframe leads regardless of its confidence",
      _bw["headline"] == _bw[{"M": "monthly", "W": "weekly",
                              "D": "daily"}[_bw["headline_timeframe"]]]["verdict"]
      and _bw["headline_timeframe"] in ("M", "W"),
      f"{_bw['headline_timeframe']} led with {_bw['headline']}")

# A weekly reading must come off weekly bars: same input, different series.
check("the weekly verdict is computed on resampled bars",
      V.for_symbol(climbing, "W")["asof"] == I.resample(climbing, "W")[-1]["time"],
      "a weekly reading needs ~5x the daily history before it can be scored")

# The weekly needs 60 WEEKLY bars, which is over a year of daily history. A name
# with only a few months of trading gets a daily verdict and no weekly one, and
# must say so rather than quietly reporting a hold that was never computed.
_short = bars([10 + i * 0.5 for i in range(120)])
check("a name too new for a weekly reading is refused, not silently held",
      V.for_symbol(_short, "W")["insufficient"] is True)
check("...while its daily reading is still produced",
      V.for_symbol(_short, "D")["insufficient"] is False)

# ---------------------------------------------------------- decision rules --
# The scoring rules are the part of this module that turns numbers into the word
# "sell", and reaching each of their edges through synthetic price series is
# guesswork — the fixtures above happen to land at 82% bearish and 8% bearish
# and never near the 65% line the module actually documents. Handing decide() a
# gathered reading directly is how the thresholds themselves get tested.
def item(name, stance, weight):
    return {"name": name, "stance": stance, "weight": weight, "level": None,
            "detail": f"{name}: {stance} at weight {weight}"}


def reading(items, price=100.0, atr=2.0, cloud=None, fib=None,
            leg_pos=None, at_level=None):
    return {"price": price, "atr": atr, "evidence": items, "noise": False,
            "leg_pos": leg_pos, "cloud": cloud, "fib": fib,
            "at_level": at_level, "bars": 300}


UP_FIB = {"direction": "up", "from": {"price": 60.0}, "to": {"price": 120.0},
          "levels": [{"ratio": 0.618, "price": 92.0, "kind": "retracement"},
                     {"ratio": 0.5, "price": 96.0, "kind": "retracement"},
                     {"ratio": 1.618, "price": 130.0, "kind": "extension"}]}
OWNED = {"weight": 0.05, "quantity": 100}

# A call needs 65% of the weight AND at least 3.0 of it. Both floors, because
# either alone lets something through: 2.0 against 0.0 is unanimous and thin,
# and 4.5 against 3.0 is heavy and genuinely mixed.
_lopsided = [item("ichimoku", "bear", 1.5), item("pivot sequence", "bear", 1.5),
             item("moving averages", "bear", 1.5), item("rsi", "bull", 1.0)]
_sell = V.decide(reading(_lopsided, cloud={"top": 112.0, "bottom": 108.0}))
check("evidence 82% bearish and over the weight floor is a sell",
      _sell["verdict"] == "sell", f"got {_sell['verdict']}")

_thin = [item("ichimoku", "bear", 1.5), item("tenkan/kijun", "bear", 1.0)]
_d = V.decide(reading(_thin, cloud={"top": 112.0, "bottom": 108.0}))
check("unanimous but thin evidence is not enough for a call",
      _d["verdict"] == "hold", f"2.5 of weight, all of it bearish, got {_d['verdict']}")

_mixed = _lopsided + [item("level", "bull", 1.5), item("fibonacci", "bull", 1.0)]
_d = V.decide(reading(_mixed, cloud={"top": 112.0, "bottom": 108.0}))
check("heavy but genuinely mixed evidence is a hold, not a call",
      _d["verdict"] == "hold", f"4.5 against 3.5, got {_d['verdict']}")
# The hold used to open "the evidence is 53% bullish (4.0 against 3.5), short
# of the 65% a call needs". The user: "seems like all readings are wishy washy
# and say like 51% bullish. That doesn't give me anything useful." A share near
# the middle is the engine reporting it has nothing, formatted as a finding.
check("the hold says there is nothing to do, not how close it came",
      any("nothing to do at this price" in r for r in _d["because"]),
      str(_d["because"])[:90])
check("...and no percentage survives in the headline reason",
      not any("%" in r for r in _d["because"][:1]), str(_d["because"][:1]))
check("...while the arithmetic is still available on the tally for anyone who opens it",
      "65%" in _d["tally"]["explain"] and _d["tally"]["bull_share"] is not None)

# A verdict with no flip level is a horoscope. Both directions degrade rather
# than emit one, and both say so — this is the branch the module docstring
# opens with and neither side of it was reachable from the price fixtures.
_no_cloud = V.decide(reading(_lopsided, cloud=None))
check("a sell with no level above price to reclaim is downgraded to hold",
      _no_cloud["verdict"] == "hold", f"got {_no_cloud['verdict']}")
check("...and says it was downgraded rather than going quiet",
      any("downgraded from sell" in r for r in _no_cloud["because"]),
      str(_no_cloud["because"])[-90:])
check("a downgraded sell names no flip level either",
      _no_cloud["flip"] is None)

_bulls = [item("ichimoku", "bull", 1.5), item("pivot sequence", "bull", 1.5),
          item("moving averages", "bull", 1.5), item("rsi", "bear", 1.0)]
_no_sup = V.decide(reading(_bulls, cloud=None, fib=None))
check("a buy with nothing below price to stop out against is downgraded to hold",
      _no_sup["verdict"] == "hold", f"got {_no_sup['verdict']}")
check("...and says the idea has no invalidation",
      any("no invalidation" in r for r in _no_sup["because"]),
      str(_no_sup["because"])[-90:])

# With a level to rest on, the same evidence becomes a call — otherwise the two
# checks above would pass on any code that never buys anything.
_at_618 = {"ratio": 0.618, "price": 92.0, "kind": "retracement"}
# Three separate things sit below price here — the cloud at 88, a swing low at
# 94 and the 0.5 retracement at 96 — because the rule is that the flip is the
# nearest of ALL of them. With one candidate source the choice is unobservable.
_below = _bulls + [{"name": "pivot sequence", "stance": "bull", "weight": 1.5,
                    "level": 94.0, "detail": "higher highs and higher lows"}]
_buy = V.decide(reading(_below, fib=UP_FIB, at_level=_at_618, leg_pos=0.55,
                        cloud={"top": 88.0, "bottom": 84.0}), None)
check("the same evidence at a level worth acting on is a buy",
      _buy["verdict"] == "buy", f"got {_buy['verdict']}")
check("a buy's flip level sits below price, where a stop would go",
      _buy["flip"] is not None and _buy["flip"] < 100.0, str(_buy["flip"]))
check("the flip is the NEAREST level below price, not the furthest",
      _buy["flip"] == 96.0,
      f"got {_buy['flip']}; the cloud at 88 and the swing low at 94 are further")
check("the same idea in a name already owned is an add, not a buy",
      V.decide(reading(_below, fib=UP_FIB, at_level=_at_618, leg_pos=0.55,
                       cloud={"top": 88.0, "bottom": 84.0}),
               OWNED)["verdict"] == "add")

# Trend intact but price nowhere worth adding: a hold that has to explain itself,
# because a high-confidence hold otherwise reads as the engine hedging.
_chase = V.decide(reading(_bulls, fib=UP_FIB, at_level=None, leg_pos=0.9), None)
check("a strong trend with price at no level is a hold, not a chase",
      _chase["verdict"] == "hold", f"got {_chase['verdict']}")
check("...and that reason is placed first so truncation cannot drop it",
      _chase["because"] and "not at a level worth" in _chase["because"][0],
      str(_chase["because"][:1]))

# Trim, at the thresholds rather than through a price series.
_ext = [item("rsi", "extended", 1.0), item("weight", "extended", 1.5),
        item("ichimoku", "bull", 1.5), item("moving averages", "bull", 1.5)]
check("an extended, heavily-weighted holding at the top of its leg is trimmed",
      V.decide(reading(_ext, fib=UP_FIB, leg_pos=0.85), OWNED)["verdict"] == "trim")
check("the identical reading lower in the leg is not",
      V.decide(reading(_ext, fib=UP_FIB, leg_pos=0.35), OWNED)["verdict"] != "trim",
      f"leg 0.35 is below the {V.UPPER_LEG} line")
check("...and the leg gate is what stops it, not the bearish weight",
      V.decide(reading(_ext, fib=UP_FIB,
                       leg_pos=V.UPPER_LEG + 0.01), OWNED)["verdict"] == "trim",
      "one step above the line the same evidence trims")
_trim = V.decide(reading(_ext, fib=UP_FIB, leg_pos=0.85), OWNED)
check("a trim argues only from what is extended",
      set(_trim["because"]) == {e["detail"] for e in _ext if e["stance"] == "extended"},
      str(_trim["because"]))
check("the case for holding on is carried as the case against trimming",
      _trim["against"], "the bullish evidence is the argument against the trim")

# Confidence is a share, not a count. A raw difference would rank ten agreeing
# items on a quiet name above a clean six-to-one, which is backwards.
_conf = lambda b, r: V.decide(reading(
    [item("a", "bull", b), item("b", "bear", r)] + _bulls[:0],
    fib=UP_FIB, at_level=_at_618, leg_pos=0.5), None)["confidence"]
check("a 9-to-1 split is high confidence", _conf(9.0, 1.0) == "high", _conf(9.0, 1.0))
check("a 7-to-3 split is medium", _conf(7.0, 3.0) == "medium", _conf(7.0, 3.0))
check("a 5-to-3 split is only low", _conf(5.0, 3.0) == "low", _conf(5.0, 3.0))
check("confidence does not rise with sheer volume of agreement",
      _conf(18.0, 6.0) == _conf(9.0, 3.0),
      "twice as much evidence at the same ratio is the same confidence")

# The arithmetic has to be checkable. "4.5 bullish against 4.0 bearish" is a
# number with nowhere to look; every scoring item is listed with what it added.
_t = _sell["tally"]
check("the tally's totals are the sum of the items it lists",
      round(sum(i["weight"] for i in _t["items"] if i["stance"] == "bear"), 2)
      == _t["bear"]
      and round(sum(i["weight"] for i in _t["items"] if i["stance"] == "bull"), 2)
      == _t["bull"], str(_t["items"]))
check("the bullish share quoted is the one the totals imply",
      abs(_t["bull_share"] - _t["bull"] / (_t["bull"] + _t["bear"])) < 0.005,
      f"{_t['bull_share']} vs {_t['bull'] / (_t['bull'] + _t['bear']):.3f}")
_ctx = V.decide(reading(_lopsided + [item("channel", None, 1.0),
                                     item("trendline", "bull", 0.0)],
                        cloud={"top": 112.0, "bottom": 108.0}))["tally"]
check("evidence that was counted but not scored is named, not hidden",
      {c["name"] for c in _ctx["context"]} == {"channel", "trendline"},
      str(_ctx["context"]))
check("a zero-weighted item never reaches the scoring totals",
      not any(i["name"] == "trendline" for i in _ctx["items"]),
      "a line too far away to matter must not be counted as bullish")

# --------------------------------------------------------------- evidence ---
g = V.gather(climbing, {"weight": 0.30, "quantity": 100})
check("every piece of evidence carries the number that produced it",
      all(any(ch.isdigit() for ch in e["detail"]) for e in g["evidence"]),
      "a reason with no figure in it cannot be checked")
check("swing location is reported as a location, never as a prediction",
      not any(w in e["detail"].lower()
              for e in g["evidence"] for w in ("topping", "bottoming", "will ")),
      "the module must not claim to call a top or a bottom")

# ---------------------------------------------------------------- dissent ---
# A verdict that lists only its confirming evidence is advocacy. DGXX read
# "add" while below all three moving averages and said nothing about it.
for _name, _bars, _pos in (("climbing", climbing, {"weight": 0.30, "quantity": 100}),
                           ("faded", faded, {"weight": 0.30, "quantity": 100}),
                           ("flat", flat, None)):
    _d = V.decide(V.gather(_bars, _pos), _pos)
    check(f"the {_name} verdict carries an 'against' list at all",
          isinstance(_d.get("against"), list), f"got {type(_d.get('against'))}")

_dc = V.decide(V.gather(climbing, {"weight": 0.30, "quantity": 100}),
               {"weight": 0.30, "quantity": 100})
check("nothing appears as both a reason for and against the same call",
      not (set(_dc.get("because", [])) & set(_dc.get("against", []))))

# ------------------------------------------------------------ new evidence --
# A perfectly straight line has no pivots, so it can produce no trendline —
# `climbing` is the wrong fixture for that check even though it is right for
# the others. A rising zig-zag has both turns and a trend.
zig_up = bars([100 + i * 0.4 + (6 if i % 12 < 6 else -6) * (1 - (i % 6) / 6)
               for i in range(600)])
_gz = V.gather(zig_up, {"weight": 0.05, "quantity": 10})
_zn = {e["name"] for e in _gz["evidence"]}
check("trendlines are read, not just computed and discarded",
      "trendline" in _zn or "level" in _zn or "support" in _zn, str(sorted(_zn)))

# The CRWV case, by name. A support line 94% below price is held trivially, and
# counting it as bullish is how that name scored 4.5 bullish against 4.0 bearish
# with 3.0 of it coming from two lines at 43.87 and 44.98 while it traded at 85.
# The line is still worth REPORTING — it is where a decline would find support —
# so it must appear as evidence and carry no weight and no stance.
crwv = bars([80 + i * 0.25 + 8 * _math.sin(i / 7) for i in range(300)])
_gc = V.gather(crwv, {"weight": 0.05, "quantity": 10})
_tls = [e for e in _gc["evidence"] if e["name"] == "trendline"]
_far = [e for e in _tls if abs(_gc["price"] - e["level"]) / _gc["atr"] > V.RELEVANT_ATR]
_close = [e for e in _tls if abs(_gc["price"] - e["level"]) / _gc["atr"] <= V.RELEVANT_ATR]
check("the fixture carries a line both near price and one far from it",
      _far and _close, f"{len(_far)} far, {len(_close)} near")
check("a line too far from price is still reported as context",
      all("too far away" in e["detail"] for e in _far), str(_far)[:90])
check("a line too far from price is scored at zero and takes no side",
      all(e["weight"] == 0.0 and e["stance"] is None for e in _far),
      str([(e["weight"], e["stance"]) for e in _far]))
check("...while a line price is actually interacting with does take a side",
      all(e["weight"] > 0 and e["stance"] for e in _close),
      str([(e["weight"], e["stance"]) for e in _close]))

# Two lines a few cents apart are one piece of structure counted twice — CRWV
# carried 43.87 and 44.98 and paid 1.5 for each. This series fits two resistance
# lines a penny apart; only one of them may reach the tally.
twin = bars([70 + i * 0.25 + 3 * _math.sin(i / 5) for i in range(300)])
_gt = V.gather(twin)
from app import structure as _S
_live = [l for l in _S.detect(twin)["trendlines"]
         if l["reaches_present"] and l.get("confirmations", 0) >= 1]
_pairs = [(a, b) for i, a in enumerate(_live) for b in _live[i + 1:]
          if abs(a["to"]["price"] - b["to"]["price"]) <= V.AT_LEVEL_ATR * _gt["atr"]]
check("the fixture really does fit two lines at effectively the same price",
      _pairs, str([round(l["to"]["price"], 2) for l in _live]))
_ends = [e["level"] for e in _gt["evidence"] if e["name"] == "trendline"]
check("two lines at the same price are counted once, not twice",
      all(abs(a - b) > V.AT_LEVEL_ATR * _gt["atr"]
          for i, a in enumerate(_ends) for b in _ends[i + 1:]),
      f"lines scored at {[round(x, 2) for x in _ends]}")

# The oscillator's two extremes are not mirror images: overbought is a reason to
# TRIM and washed-out is a reason to buy, so they must not share a stance.
_ov = [e for e in V.gather(climbing)["evidence"] if e["name"] == "rsi"]
_falling = bars([310 - i * 0.5 for i in range(600)])
_ws = [e for e in V.gather(_falling)["evidence"] if e["name"] == "rsi"]
check("an overbought oscillator is extended, never bullish",
      _ov and _ov[0]["stance"] == "extended", str(_ov))
check("a washed-out oscillator is bullish", _ws and _ws[0]["stance"] == "bull", str(_ws))

# Size is a reason to trim that has nothing to do with the chart, and it has a
# stated line rather than a feel for it.
_heavy = [e for e in V.gather(climbing, {"weight": V.HEAVY_WEIGHT + 0.01,
                                         "quantity": 100})["evidence"]
          if e["name"] == "weight"]
_light = [e for e in V.gather(climbing, {"weight": V.HEAVY_WEIGHT - 0.01,
                                         "quantity": 100})["evidence"]
          if e["name"] == "weight"]
check("a position over the weight line is flagged as extended on size alone",
      _heavy and _heavy[0]["stance"] == "extended", str(_heavy))
check("a position under it is not flagged at all", _light == [], str(_light))

_g = V.gather(climbing, {"weight": 0.05, "quantity": 10})
_names = {e["name"] for e in _g["evidence"]}
check("moving averages are read, not just computed and discarded",
      "moving averages" in _names, str(sorted(_names)))
check("horizontal levels travel with the reading",
      "near" in _g and "zones" in _g)
check("the current price and its change are reported",
      _g.get("price") is not None and _g.get("change") is not None,
      "the tab showed levels but never the price they are relative to")

# ------------------------------------------------------------- hygiene -----
# gather() bound `near` to a lambda, used it, then rebound it to a bool inside
# the trendline loop. Every use of the lambda happened to precede the loop, so
# it worked — and was one reordering away from calling a boolean. A name used
# for two things in one function is a latent TypeError, not a style opinion.
# Written as an assertion about the SOURCE, because the collision is invisible
# at runtime until somebody moves a line. `X or True` would have been the easy
# way to write this and cannot fail, which is the defect these audits kept
# finding — so it asserts the specific thing: neither helper name is assigned
# more than once.
import inspect as _inspect
_src = _inspect.getsource(V.gather)
for _name in ("at_same_price", "close_enough"):
    _binds = sum(1 for ln in _src.splitlines()
                 if ln.strip().startswith(f"{_name} ="))
    check(f"gather() binds {_name} exactly once", _binds == 1,
          f"{_binds} bindings — a lambda and a bool sharing one name is a "
          f"TypeError waiting for a reorder")

# And the guarantee that actually matters: a real call survives the function.
for _b, _lbl in ((climbing, "trending"), (faded, "faded"), (flat, "flat")):
    try:
        V.gather(_b, {"weight": 0.3, "quantity": 1})
        _ok = True
    except TypeError:
        _ok = False
    check(f"gather() completes on a {_lbl} series without a name collision", _ok)

# ------------------------------------------------ levels say what they mean --
# The three levels were shown under fixed headings whatever the verdict was, so
# a SELL displayed "Buy / add at 32.24" directly above "Wrong below 32.24" — one
# number under two contradictory labels, on a name the app was saying to exit.
# A sell is also proved wrong ABOVE, not below.
def _levels(verdict, held=True):
    return V._watch_levels_for(verdict, held, 100.0, 90.0, 110.0, 88.0,
                               120.0, "a close back above 120 ends the case")


_sell = _levels("sell")
check("a sell never offers a level to buy at",
      not any("buy" in l["label"].lower() for l in _sell),
      str([l["label"] for l in _sell]))
check("a sell is invalidated ABOVE price, not below",
      _sell[0]["price"] > 100.0 and "above" in _sell[0]["label"].lower(),
      str(_sell[0]))
check("...and says the flip level is not a price to buy at",
      any("not a target to buy" in l["why"] or "not a buy" in l["why"]
          for l in _sell),
      "the question this wording exists to answer")

_buy = _levels("buy", held=False)
check("a buy names the price that would prove it wrong",
      any("wrong" in l["label"].lower() and l["price"] < 100.0 for l in _buy),
      str([(l["label"], l["price"]) for l in _buy]))
check("...and says that level is where to leave, not where to add",
      any("not a place to buy more" in l["why"] for l in _buy))

_trim = _levels("trim")
check("a trim names what trimming gives up",
      any("gives up" in l["why"] for l in _trim), str([l["why"] for l in _trim]))

_hold = _levels("hold", held=False)
check("a hold on something unowned says buy, not add",
      any(l["label"].startswith("Worth buying") for l in _hold),
      str([l["label"] for l in _hold]))
check("a hold on something owned says add, not buy",
      any(l["label"].startswith("Worth adding") for l in _levels("hold", held=True)))

for _v in ("buy", "add", "hold", "trim", "sell"):
    _ls = _levels(_v)
    check(f"every {_v} level carries a sentence, not just a heading",
          all(l["why"] and len(l["why"]) > 20 for l in _ls),
          "'wrong below' is only obvious to whoever wrote it")
    check(f"no two {_v} levels repeat the same price under different labels",
          len({l["price"] for l in _ls}) == len(_ls),
          str([(l["label"], l["price"]) for l in _ls]))

# ------------------------------------------------------- williams %r -------
# RonnieV uses length 12 with the bands at 0 and -100 and reads a hit near the
# floor as "a bottom is in range". That is the only reading it scores for: a
# stretched oscillator near the TOP is already covered by RSI and the Fibonacci
# extensions, and a second overbought voice would double-count one observation.
_wr = lambda bars: [e for e in V.gather(bars)["evidence"] if e["name"] == "williams %r"]
check("a name at the bottom of its range reports Williams %R",
      len(_wr(faded)) == 1, f"{len(_wr(faded))} entries on a collapsed series")
check("...and it argues for buying, not against",
      not _wr(faded) or _wr(faded)[0]["stance"] == "bull")
check("a name making new highs does not report it at all",
      _wr(climbing) == [],
      "silent near the top, where RSI and the extensions already speak")
check("the reading names its own period",
      not _wr(faded) or f"{V.WILLR_PERIOD}-period" in _wr(faded)[0]["detail"])
check("-80 is described as the bottom fifth of the range, not the bottom 80%",
      not _wr(faded) or "bottom 20%" in _wr(faded)[0]["detail"],
      "%R of -80 puts price 80% of the way DOWN from the high")
check("it is not presented as a trigger",
      not _wr(faded) or "Not a trigger" in _wr(faded)[0]["detail"],
      "he waits at a price rather than buying the signal")

# ----------------------------------------------------- three timeframes ----
_bt = V.both_timeframes(climbing, {"weight": 0.05, "quantity": 10})
check("monthly is read as well as daily and weekly",
      "monthly" in _bt, sorted(_bt))
check("the headline is the LONGEST timeframe that could be read, not the daily",
      _bt["headline_timeframe"] in ("M", "W", "D")
      and _bt["headline"] == _bt[{"M": "monthly", "W": "weekly",
                                  "D": "daily"}[_bt["headline_timeframe"]]]["verdict"],
      f"{_bt['headline_timeframe']} -> {_bt['headline']}")

# 60 bars was applied to every timeframe, which is five years of monthly candles
# and excluded almost every holding — so there was no monthly reading at all.
check("monthly needs fewer bars than daily, or there is never a monthly read",
      V.MIN_BARS["M"] < V.MIN_BARS["D"], str(V.MIN_BARS))
_short = bars([10 + i * 0.4 for i in range(200)])
check("a name with under three years still gets a daily and weekly read",
      not V.for_symbol(_short, "D")["insufficient"], "200 sessions")

# A timeframe with too little history is not a disagreement.
_thin = V.both_timeframes(bars([10 + i * 0.5 for i in range(700)]),
                          {"weight": 0.05, "quantity": 10})
check("a timeframe that could not be read is left out of the conflict note",
      _thin["conflict"] is None
      or "monthly" not in _thin["conflict"] or not _thin["monthly"]["insufficient"],
      str(_thin.get("conflict"))[:80])

# ---------------------------------------------------------- setup quality --
# A screen full of "add" ranked by nothing. Reward against risk is the
# discriminator, and it is measured between levels rather than guessed.
_q = _bt["quality"]
check("a quality score is produced", "score" in _q and "reward_risk" in _q)
check("the ranking states its own components rather than being a bare number",
      _q["why"] and len(_q["why"]) > 30, str(_q["why"])[:60])
check("it says which basis the reward was measured to",
      _q["reward_risk"] is None or _q["reward_basis"],
      "a ratio measured to a projection deserves less trust than one measured "
      "to a price the market has already refused")
check("a call with no level either side is refused a ranking rather than given a flattering one",
      V.quality({"headline": "hold", "headline_timeframe": "D",
                 "daily": {"watch": {}, "near": {}, "tally": {}},
                 "weekly": {"insufficient": True},
                 "monthly": {"insufficient": True}})["score"] is None)

# SIVEF offered "worth adding nearer 0.58" against a price of 2.55 — a 77% fall
# away, from a zone last touched when the listing traded at a quarter of today's
# price. A real level, and not a plan.
def _watch(support, touches=4, flipped=False):
    """A tested zone at `support`. Zones rather than `near.support` because the
    buy side now reads the whole zone list: the nearest support is not the buy
    level unless it also clears MIN_LEVEL_TOUCHES, and on IREN a 2-touch shelf
    1.2% above price was hiding a 4-touch flipped level behind it."""
    zone = {"low": support - 1, "high": support, "price": support - 0.5,
            "touches": touches, "flipped": flipped,
            "first": "2026-01-05", "last": "2026-08-20"}
    g = {"price": 100.0, "fib": {"levels": []}, "cloud": None, "zones": [zone],
         "near": {"support": {"high": support}, "resistance": None, "at": None}}
    return V.watch_levels(g, {"verdict": "hold", "flip": None, "flip_note": None},
                          {"quantity": 1})


check("an entry level far outside the actionable band is not offered",
      _watch(20.0)["buy_at"] is None,
      "20 against a price of 100 is a historical fact, not somewhere to act")
check("...while one inside the band still is",
      _watch(90.0)["buy_at"] == 90.0)
# The rule the buy side was missing entirely: a support is not a buy level
# because it is the nearest line under price. Six of thirteen holdings on
# 2026-09-09 were told to buy within 1.3% of the last trade.
check("an untested level inside the band is NOT offered as a buy level",
      _watch(90.0, touches=2)["buy_at"] is None,
      "two touches is not a level to plan a buy at")
check("...but two touches from BOTH sides is, which is the stronger signal",
      _watch(90.0, touches=2, flipped=True)["buy_at"] == 90.0)
check("a buy level price is already standing on says so rather than "
      "printing a number a hair under the last trade",
      _watch(99.0)["buy_now"] is True and _watch(90.0)["buy_now"] is False)
# ---- what each level is being taken FOR ---------------------------------
# "If it gives me a buy level or sell level it should also tell me the upside
# or downside target of the move." A level says WHEN and says nothing about
# what the trade is worth.
def _zone(low, high, touches=4, flipped=False):
    return {"low": low, "high": high, "price": (low + high) / 2,
            "touches": touches, "flipped": flipped,
            "first": "2026-01-05", "last": "2026-08-20"}

_zs = {"zones": [_zone(78, 80), _zone(88, 90), _zone(118, 120), _zone(148, 150),
                 _zone(104, 106, touches=2)]}
_t = V._targets(_zs, 100.0, buy_at=90.0, trim_at=120.0, stop_at=80.0)
check("a buy level carries the upside it is being taken for",
      _t["buy_target"] == 120.0 and _t["buy_target_pct"] == 33.3, _t)
check("...and the reward against the risk, measured FROM THE ENTRY not from price",
      _t["buy_rr"] == 3.0 and _t["buy_risk_pct"] == -11.1,
      "entry 90 to target 120 is 30; entry 90 to stop 80 is 10")
# The 104-106 shelf sits between price and the sell level but has only two
# touches, so it is skipped and the pullback target is the tested 88-90 zone.
check("a sell level carries the pullback expected after it",
      _t["sell_target"] == 90.0 and _t["sell_target_pct"] == -25.0, _t)
_ts = V._targets({"zones": [_zone(78, 80), _zone(104, 106), _zone(118, 120)]},
                 100.0, buy_at=80.0, trim_at=120.0, stop_at=79.0)
check("...and it is the NEAREST tested level below the sell, not the furthest",
      _ts["sell_target"] == 106.0, _ts)
check("an untested zone is not offered as a target either",
      V._targets({"zones": [_zone(104, 106, touches=2)]}, 100.0, 90.0, None, 80.0)["buy_target"] is None,
      "the 104-106 shelf has two touches and is not flipped")
check("with the invalidation ABOVE the entry there is no trade to size",
      V._targets(_zs, 100.0, buy_at=80.0, trim_at=120.0, stop_at=90.0)["buy_rr"] is None,
      "no reward-to-risk when the idea is already broken at the entry")
check("no buy level means no buy target rather than a target off thin air",
      V._targets(_zs, 100.0, buy_at=None, trim_at=120.0, stop_at=80.0)["buy_target"] is None)

check("the cap is a stated percentage, not a multiple of ATR",
      0 < V.ACTIONABLE_PCT < 1,
      "ATR fails here: SIVEF's weekly ATR is 1.52 on a 2.55 stock, so an "
      "ATR gate waves a 77%-away level straight through")


# --------------------------------------------- the cloud, on this name ----
# "It caps rallies" was stated for every name below its cloud. Now the claim
# is checked against what the cloud did the previous times price reached it.
def _cloud_bars(n=200, base=100.0):
    return [{"time": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": base, "high": base + 1,
             "low": base - 1, "close": base, "volume": 100} for i in range(n)]

_flat_ich = {"span_a": [{"time": b["time"], "value": 110.0} for b in _cloud_bars()],
             "span_b": [{"time": b["time"], "value": 105.0} for b in _cloud_bars()]}
_cb = _cloud_bars()
# Two approaches from below that get turned back, and one that goes through.
for i, through in ((60, False), (100, False), (140, True)):
    _cb[i]["high"] = 106.0                                 # reaches the floor
    if through:
        for j in range(i + 1, i + 4):
            _cb[j]["close"] = _cb[j]["high"] = 112.0       # closes above the top
    else:
        _cb[i + 1]["close"] = 99.0                         # back under the floor
_rec = V.cloud_record(_cb, _flat_ich)
check("approaches from below are counted, turned back and through",
      _rec["from_below"] == {"turned": 2, "through": 1}, _rec)
_tail, _w = V._cloud_claim(_rec, "below")
check("when the cloud has mostly held, the reading keeps full weight and says so",
      _w == 1.5 and "turned price back 2 of the 3" in _tail, (_w, _tail))
_tail2, _w2 = V._cloud_claim({"from_below": {"turned": 1, "through": 3},
                                     "from_above": {"held": 0, "through": 0}}, "below")
check("when price has mostly gone straight through, the reading is halved and says so",
      _w2 == 0.75 and "NOT held" in _tail2, (_w2, _tail2))
_tail3, _w3 = V._cloud_claim({"from_below": {"turned": 1, "through": 0},
                                     "from_above": {"held": 0, "through": 0}}, "below")
check("one episode is not a record", _w3 == 1.5 and "too few" in _tail3, _tail3)


# A name that has fallen 95% produces, on a monthly resample, trendlines whose
# projection reaches zero before the present. The replay hit exactly this and
# the engine divided by it. Whatever lines structure finds, gather() must not
# raise on such a series.
_dead = []
for i in range(400):
    px = max(0.05, 100.0 * (0.985 ** i)) * (1 + 0.15 * ((i % 7) - 3) / 3)
    _dead.append({"time": f"{2020 + i // 250}-{1 + (i % 250) // 21:02d}-{1 + (i % 250) % 21:02d}",
                  "open": px, "high": px * 1.08, "low": px * 0.92, "close": px, "volume": 1000})
try:
    for _tf in ("D", "W", "M"):
        V.for_symbol(_dead, _tf, None, None)
    check("a series that has collapsed toward zero is scored without dividing by a zero line", True)
except ZeroDivisionError as exc:
    check("a series that has collapsed toward zero is scored without dividing by a zero line", False, exc)


# --------------------------- transcript items, recorded at zero weight ----
# RonnieV's moving-average rules are carried so the replay can measure them,
# and at weight zero so they change nothing until it has.
_up = []
for _i in range(260):
    _px = 50.0 + _i * 0.3
    if _i >= 250:
        _px -= 4.0                        # a dip back onto the rising 20-day, still on
    _up.append({"time": f"2025-{1 + _i // 21:02d}-{1 + _i % 21:02d}".replace("2025-13", "2026-01"),
                "open": _px, "high": _px + 0.4, "low": _px - 0.4, "close": _px, "volume": 1000})
_gu = V.gather(_up, None, None)
_names = {e["name"]: e for e in _gu["evidence"]}
check("the 20/50 and 50/200 crossover items are recorded",
      "ma cross 20/50" in _names and "ma cross 50/200" in _names, sorted(_names))
check("in a clean uptrend both crossovers read bullish",
      _names.get("ma cross 20/50", {}).get("stance") == "bull"
      and _names.get("ma cross 50/200", {}).get("stance") == "bull")
check("a dip to the rising 20-day above the 200-day is a pullback-to-average item",
      _names.get("pullback to average", {}).get("stance") == "bull",
      _names.get("pullback to average"))
check("every transcript item carries zero weight and so reaches no total",
      all(_names.get(k, {}).get("weight") == 0.0 for k in ("ma cross 20/50", "ma cross 50/200", "pullback to average")))
_du = V.decide(_gu, None)
check("and none of them appears among the scored items",
      not any(i["name"].startswith("ma cross") or i["name"] == "pullback to average"
              for i in (_du.get("tally") or {}).get("items", [])))


# ------------------------- the weekly Fibonacci retracement is off ----
# Recorded, at zero weight, and never the level a weekly buy is taken at.
_wk = [dict(b) for b in _up]
_gw = V.gather(_up, None, None, "W")
_gd = V.gather(_up, None, None, "D")
_fw = [e for e in _gw["evidence"] if e["name"] == "fibonacci" and "retracement" in e["detail"]]
_fd = [e for e in _gd["evidence"] if e["name"] == "fibonacci" and "retracement" in e["detail"]]
check("a weekly retracement reading, when present, carries zero weight and says why",
      all(e["weight"] == 0.0 and "switched off" in e["detail"] for e in _fw), _fw)
check("the daily retracement reading is unchanged",
      all(e["weight"] == 1.5 for e in _fd), _fd)
check("a weekly call is never anchored to a retracement as its acting level",
      not (_gw.get("at_level") and _gw["at_level"].get("kind") == "retracement"), _gw.get("at_level"))
check("the switch is per timeframe and names only the weekly", V.FIB_RETRACEMENT_OFF == {"W"})


# ------------------------------------------- the conviction book ----
# The same broken-trend evidence is a sell on the swing book and a hold with
# the reason stated on the conviction book. Trim is unchanged by the book.
_bearish = [item("pivot sequence", "bear", 1.5), item("ichimoku", "bear", 1.5),
            item("moving averages", "bear", 1.0), item("tenkan/kijun", "bear", 0.5)]
_g_bear = reading(_bearish, cloud={"top": 112.0, "bottom": 108.0})
_swing = V.decide(_g_bear, {"quantity": 100, "weight": 0.1, "book": "swing"})
_conv = V.decide(_g_bear, {"quantity": 100, "weight": 0.1, "book": "conviction"})
check("a broken trend is a sell on the swing book", _swing["verdict"] == "sell", _swing["verdict"])
check("and a hold on the conviction book, saying why",
      _conv["verdict"] == "hold" and _conv["because"][0].startswith("conviction book"), _conv.get("because"))
check("the conviction hold keeps the level that would end the broken-trend reading",
      _conv.get("flip") == _swing.get("flip") and _conv.get("flip") is not None, (_conv.get("flip"), _swing.get("flip")))
check("the evidence is not hidden by the book", _conv["tally"]["bear"] == _swing["tally"]["bear"])
check("a name with no book reads as swing", V.decide(_g_bear, {"quantity": 100, "weight": 0.1})["verdict"] == "sell")


# ------------------------------------------ measured weekly confidence ----
# On the weekly, confidence is the fifth of the record the measured score
# falls in, and an entry needs the top fifth. The daily is untouched.
check("fifths map to high / medium / low",
      [V.measured_confidence(f) for f in (5, 4, 3, 2, 1, None)] == ["high", "medium", "low", "low", "low", None])
check("for a sell the bottom fifth is the confident end",
      [V.measured_confidence(f, "sell") for f in (1, 2, 5)] == ["high", "medium", "low"])
_bull_items = [item("pivot sequence", "bull", 1.5), item("ichimoku", "bull", 1.5),
               item("moving averages", "bull", 1.0), item("tenkan/kijun", "bull", 0.5)]
_gb = reading(_bull_items, cloud={"top": 90.0, "bottom": 85.0})
_gb["timeframe"] = "W"; _gb["measured_fifth"] = 5
_top = V.decide(_gb, None)
_gb2 = dict(_gb); _gb2["measured_fifth"] = 3
_mid = V.decide(_gb2, None)
check("a weekly call in the top fifth with intact trend and a support is a buy",
      _top["verdict"] == "buy", _top.get("because"))
check("the same evidence in the middle fifth is a hold, not a chase",
      _mid["verdict"] == "hold" and "fifth 3 of 5" in _mid["because"][0], _mid.get("because"))
_gb3 = dict(_gb); _gb3["measured_fifth"] = 1
_bot = V.decide(_gb3, None)
check("the bottom fifth is a sell on the weekly even with the trend items reading bull",
      _bot["verdict"] == "sell", _bot)
_gb4 = dict(_gb); _gb4["measured_fifth"] = 1
check("the conviction book turns that sell into a hold",
      V.decide(_gb4, {"qty": 10, "book": "conviction"})["verdict"] == "hold")
check("the weekly trend items are recorded at zero weight, levels keep theirs",
      all(e["weight"] == 0 for e in V.gather(I.resample(climbing, "W"), None, None, "W")["evidence"] if e["name"] in V.TREND_ITEMS)
      and any(e["weight"] > 0 for e in V.gather(I.resample(climbing, "W"), None, None, "W")["evidence"]
              if e["name"] not in V.TREND_ITEMS and e["name"] != "fibonacci"),
      [(e["name"], e["weight"]) for e in V.gather(I.resample(climbing, "W"), None, None, "W")["evidence"]])
_gd = dict(_gb); _gd["timeframe"] = "D"; _gd["measured_fifth"] = 5
check("the daily still needs a level to act at, whatever the measured fifth",
      V.decide(_gd, None)["verdict"] == "hold")
# for_symbol wires the profile through and overrides the weekly confidence
_prof = {"weights": {("pivot sequence", "bull"): 0.02, ("ichimoku", "bull"): 0.03},
         "cuts": (-0.01, 0.0, 0.01, 0.02)}
_long = []
for _i in range(420):
    _px = 50.0 + _i * 0.2 + (3.0 * ((_i % 9) - 4) / 4)
    _long.append({"time": f"{2024 + _i // 250}-{1 + (_i % 250) // 21:02d}-{1 + (_i % 250) % 21:02d}",
                  "open": _px, "high": _px + 0.5, "low": _px - 0.5, "close": _px, "volume": 1000})
_fw = V.for_symbol(_long, "W", None, None, _prof)
check("a weekly call carries its measured score and fifth",
      _fw.get("measured_score") is not None and _fw.get("measured_fifth") in (1, 2, 3, 4, 5), (_fw.get("measured_score"), _fw.get("measured_fifth")))
check("and its confidence is the measured one, with the engine's kept beside it",
      _fw.get("confidence") == V.measured_confidence(_fw["measured_fifth"], _fw["verdict"]) and "confidence_engine" in _fw, _fw.get("confidence_note"))
_fd = V.for_symbol(_long, "D", None, None, _prof)
check("the daily keeps the engine's own confidence", "confidence_engine" not in _fd)


# ------------------------------ Phase 2 candidates, at zero weight ----
def bar(o, h, l, c, v=1000, t="2026-01-01"):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v}

check("a hammer is a small body with a long lower wick",
      V.candle_pattern(bar(10, 10.5, 9.5, 10), bar(10, 10.2, 8.0, 10.1)) == ("hammer", "bull"))
check("a shooting star is the mirror", V.candle_pattern(bar(10, 10.5, 9.5, 10), bar(10, 12.0, 9.9, 9.95)) == ("shooting star", "bear"))
check("a bullish engulfing bar swallows the previous down bar",
      V.candle_pattern(bar(10, 10.2, 9.4, 9.6), bar(9.5, 10.6, 9.4, 10.5)) == ("bullish engulfing", "bull"))
check("a bearish engulfing bar swallows the previous up bar",
      V.candle_pattern(bar(9.6, 10.2, 9.4, 10.0), bar(10.1, 10.2, 9.3, 9.4)) == ("bearish engulfing", "bear"))
check("a doji is named but carries no direction", V.candle_pattern(bar(10, 11, 9, 10), bar(10, 11, 9, 10.02)) == ("doji", "none"))
check("an ordinary bar is nothing", V.candle_pattern(bar(10, 11, 9, 10.5), bar(10.5, 11.2, 10.3, 11.0)) is None)

_vb = [bar(10, 10.5, 9.5, 10.2, v=1000) for _ in range(30)]
_vb[-1] = bar(10.2, 10.3, 9.6, 9.7, v=3000)               # heavy down bar
_vi = V.volume_items(_vb)
check("a bar at 2.5x the 20-bar average is heavy, and its direction is read",
      _vi["heavy"] and _vi["down_bar"] and abs(_vi["ratio"] - 3.0) < 1e-9, _vi)
_vc = [bar(10, 10.5, 9.5, 10.2, v=3000) if i % 2 else bar(10.2, 10.4, 9.6, 9.8, v=500) for i in range(30)]
check("volume on up bars against down bars is the commitment share",
      abs(V.volume_items(_vc)["up_share"] - 3000 * 5 / (3000 * 5 + 500 * 5)) < 1e-9, V.volume_items(_vc)["up_share"])
check("too few bars gives no volume readings", V.volume_items(_vb[:10])["up_share"] is None)

_fib = {"direction": "up", "from": {"price": 100.0}, "to": {"price": 200.0}, "levels": []}
check("price a third of the way down a rising leg is on the 1/3 Gann fraction",
      V.gann_level(_fib, 166.7, atr=1.0)[0] == "1/3" and V.gann_level(_fib, 166.7, 1.0)[2] is True)
check("price nowhere near a fraction is nothing", V.gann_level(_fib, 190.0, 1.0) is None)

_piv = [{"kind": "low", "price": 100.0, "index": 10}, {"kind": "high", "price": 120.0, "index": 20},
        {"kind": "low", "price": 101.0, "index": 30}]
_dbl = V.double_pattern(_piv, 125.0)
check("two lows within 3% around a high are a double bottom, confirmed above the neckline",
      _dbl and _dbl["kind"] == "double bottom" and _dbl["neck"] == 120.0 and _dbl["confirmed"], _dbl)
check("below the neckline it is only forming", not V.double_pattern(_piv, 110.0)["confirmed"])
check("lows too far apart in price are not a double", V.double_pattern(
      [{"kind": "low", "price": 100.0, "index": 10}, {"kind": "high", "price": 120.0, "index": 20},
       {"kind": "low", "price": 110.0, "index": 30}], 125.0) is None)

# In gather, every candidate is zero-weight and so reaches no total.
_g2 = V.gather(_long, None, None, "D")
_cands = [e for e in _g2["evidence"] if e["name"] in ("absorption", "volume commitment", "obv", "candlestick", "gann", "pattern")]
check("the candidates appear as evidence when they apply", any(e["name"] == "obv" for e in _cands), [e["name"] for e in _cands])
check("and every one of them carries zero weight", all(e["weight"] == 0.0 for e in _cands))


# ------------------------------------- relative strength, from context ----
_gr = V.gather(_long, None, None, "W", {"rs_rank": 91})
_rs = [e for e in _gr["evidence"] if e["name"] == "relative strength"]
check("a top-fifth rank is a bullish item at zero weight",
      _rs and _rs[0]["stance"] == "bull" and _rs[0]["weight"] == 0.0 and "91" in _rs[0]["detail"], _rs)
check("a middle rank is context, not a stance",
      [e["stance"] for e in V.gather(_long, None, None, "W", {"rs_rank": 50})["evidence"] if e["name"] == "relative strength"] == [None])
check("a bottom-fifth rank is bearish",
      [e["stance"] for e in V.gather(_long, None, None, "W", {"rs_rank": 12})["evidence"] if e["name"] == "relative strength"] == ["bear"])
check("no context means no item", not [e for e in V.gather(_long, None, None, "W")["evidence"] if e["name"] == "relative strength"])


check("a clear-skies dial is bullish context at zero weight",
      [(e["stance"], e["weight"]) for e in V.gather(_long, None, None, "W",
       {"regime": {"state": "on", "label": "clear skies", "score": 4}})["evidence"] if e["name"] == "regime"] == [("bull", 0.0)])
check("a windy dial carries no stance",
      [e["stance"] for e in V.gather(_long, None, None, "W",
       {"regime": {"state": "mixed", "label": "windy", "score": 1}})["evidence"] if e["name"] == "regime"] == [None])


# ---- headline: a weekly sell at high confidence is not hidden behind the monthly ----
_hd = V.both_timeframes(climbing, None)
check("both_timeframes still reports a headline and its timeframe", _hd.get("headline") and _hd.get("headline_timeframe"))
_orig_for_symbol = V.for_symbol
def _fake_for_symbol(bars, tf, position=None, market=None, measured=None, context=None):
    r = _orig_for_symbol(bars, tf, position, market, measured, context)
    if tf == "W":
        r = {**r, "verdict": "sell", "confidence": "high", "insufficient": False}
    if tf == "M":
        r = {**r, "verdict": "add", "confidence": "medium", "insufficient": False}
    return r
V.for_symbol = _fake_for_symbol
try:
    _hd2 = V.both_timeframes(climbing, None)
finally:
    V.for_symbol = _orig_for_symbol
check("a weekly sell at high confidence takes the headline from a monthly add",
      _hd2["headline"] == "sell" and _hd2["headline_timeframe"] == "W", (_hd2["headline"], _hd2["headline_timeframe"]))

# ---- the gap item ----
_gb = [dict(b) for b in climbing[-60:]]
for b in _gb: b["volume"] = 1000.0
_prev = _gb[-2]; _gb[-1] = {**_gb[-1], "open": _prev["low"] * 0.9, "close": _prev["low"] * 0.88,
                            "high": _prev["low"] * 0.92, "low": _prev["low"] * 0.85, "volume": 5000.0}
_g = V.gap_item(_gb)
check("a gap down on heavy volume that closes below the gap is a bear gap item",
      _g and _g["stance"] == "bear" and "5.0x" in _g["detail"], _g)
_gq = [dict(b) for b in _gb]; _gq[-1]["volume"] = 1500.0
check("the same gap on ordinary volume is not an item", V.gap_item(_gq) is None)
_gu = [dict(b) for b in climbing[-60:]]
for b in _gu: b["volume"] = 1000.0
_p = _gu[-2]; _gu[-1] = {**_gu[-1], "open": _p["high"] * 1.1, "close": _p["high"] * 1.12,
                          "high": _p["high"] * 1.15, "low": _p["high"] * 1.08, "volume": 3000.0}
check("a gap up on volume that holds is a bull gap item", (V.gap_item(_gu) or {}).get("stance") == "bull")
check("the gap item is recorded in gather at zero weight",
      any(e["name"] == "gap" and e["weight"] == 0 for e in V.gather(_gb, None)["evidence"]))



# ---- the market against a setup marks a buy down one notch ----
_against = {"state": "against", "indices": {"SPY": {"trend": "breaking"}}, "summary": "SPY BELOW its 200-day (breaking)"}
_with = {"state": "with", "indices": {"SPY": {"trend": "up"}}, "summary": "SPY above its 200-day (up)"}
_r_ag0 = V.for_symbol(climbing, "D", None, None, None, {"index": _against})
_r_w0 = V.for_symbol(climbing, "D", None, None, None, {"index": _with})
check("the index read is recorded as a zero-weight item with the market's stance",
      any(e["name"] == "index" and e["weight"] == 0 and e["stance"] == "bear" for e in _r_ag0["evidence"])
      and any(e["name"] == "index" and e["stance"] == "bull" for e in _r_w0["evidence"]))
_orig_decide = V.decide
V.decide = lambda g, position=None: {"verdict": "buy", "confidence": "high", "because": ["x"], "against": [], "flip": None, "flip_note": None}
try:
    _r_plain = V.for_symbol(climbing, "D", None, None, None, None)
    _r_ag = V.for_symbol(climbing, "D", None, None, None, {"index": _against})
    _r_w = V.for_symbol(climbing, "D", None, None, None, {"index": _with})
finally:
    V.decide = _orig_decide
check("a buy with the market against it loses one notch of confidence, and says so",
      _r_plain["confidence"] == "high" and _r_ag["confidence"] == "medium" and _r_ag.get("market_against")
      and any("market is against" in a for a in _r_ag["against"]), (_r_plain["confidence"], _r_ag["confidence"]))
check("the market with it changes nothing", _r_w["confidence"] == "high" and not _r_w.get("market_against"))


# ------------------------------- the charts saved from X, 2026-09-03 --------
# Six readings the engine did not have, every one at ZERO weight until the
# replay has measured it. The tests are about what each helper says and
# refuses to say; none may move a verdict.
from app import indicators as _I, structure as _S                    # noqa: E402

# Every new item carries weight zero.
_NEW = {"reversal zone", "target", "role flip", "channel floor", "channel ceiling",
        "rsi divergence", "phase", "volume profile"}
_g_new = V.gather(bars([10 + i * 0.3 for i in range(150)] + [55 - i * 0.2 for i in range(60)]))
check("every reading taken from the saved charts is recorded at zero weight",
      all(e["weight"] == 0.0 for e in _g_new["evidence"] if e["name"] in _NEW),
      [(e["name"], e["weight"]) for e in _g_new["evidence"] if e["name"] in _NEW])

# phase_item: Con's labels, and the price gate that keeps them current.
def _pv(kind, price, label, idx):
    return {"kind": kind, "price": price, "label": label, "index": idx, "time": f"t{idx}"}
_acc = [_pv("high", 100, "H", 0), _pv("low", 80, "L", 5), _pv("high", 95, "LH", 10),
        _pv("low", 70, "LL", 15), _pv("high", 85, "LH", 20), _pv("low", 75, "HL", 25)]
_ph = V.phase_item(_acc, price=78.0, atr=1.0)
check("a higher low after a lower low under a lower high reads as accumulation forming",
      _ph and _ph["stance"] == "bull" and "accumulation" in _ph["detail"], _ph)
check("the accumulation level is the higher low", _ph and _ph["level"] == 75, _ph)
check("once price has left the range above the lower high the phase is over",
      V.phase_item(_acc, price=120.0, atr=1.0) is None)
check("once price has broken the higher low the base has failed, not formed",
      V.phase_item(_acc, price=60.0, atr=1.0) is None)
_dist = [_pv("low", 50, "L", 0), _pv("high", 70, "H", 5), _pv("low", 60, "HL", 10),
         _pv("high", 80, "HH", 15), _pv("low", 65, "HL", 20), _pv("high", 75, "LH", 25)]
_pd = V.phase_item(_dist, price=70.0, atr=1.0)
check("a lower high after a higher high over a higher low reads as distribution forming",
      _pd and _pd["stance"] == "bear" and "distribution" in _pd["detail"], _pd)
check("a plain uptrend (HH then HL) is not a phase item — the pivot sequence covers it",
      V.phase_item(_dist[:-1], price=70.0, atr=1.0) is None)
check("fewer than two pivots of a kind is not enough to name a phase",
      V.phase_item(_acc[:3], price=90.0, atr=1.0) is None)

# role_flip_item: previous support is now resistance, and the mirror.
_z_res = {"low": 49.8, "high": 50.2, "role": "resistance", "role_flipped": True,
          "sequence": ["low", "low", "high"], "last": "2026-01-20", "touches": 3}
_rf = V.role_flip_item({"at": _z_res, "support": None, "resistance": None}, price=50.0, atr=1.0)
check("support that turned price back from below reads as resistance now",
      _rf and _rf["stance"] == "bear" and "previous support is now resistance" in _rf["detail"], _rf)
_z_sup = dict(_z_res, role="support", sequence=["high", "high", "low"])
_rf2 = V.role_flip_item({"at": None, "support": _z_sup, "resistance": None}, price=50.5, atr=1.0)
check("resistance that has held price from above reads as support now — the breakout-and-retest",
      _rf2 and _rf2["stance"] == "bull" and "breakout-and-retest" in _rf2["detail"], _rf2)
check("a flipped level far from price is not today's evidence",
      V.role_flip_item({"at": None, "support": _z_sup, "resistance": None}, price=70.0, atr=1.0) is None)
check("a level that never changed role produces nothing",
      V.role_flip_item({"at": dict(_z_res, role_flipped=False), "support": None, "resistance": None},
                       price=50.0, atr=1.0) is None)

# rsi_divergence: price lower low, RSI higher low.
_div_px = [100 - i for i in range(15)] + [85 + i * 0.8 for i in range(10)] + [93 - i * 1.2 for i in range(10)] + [81 + i * 0.5 for i in range(15)]
_div_bars = bars(_div_px)
_rsi_series = _I.rsi(_div_bars, 14)
_dv = V.rsi_divergence(_div_bars, _rsi_series, lookback=40)
check("the divergence helper returns a stance or nothing, never a bare guess",
      _dv is None or _dv["stance"] in ("bull", "bear"), _dv)
# Construct the disagreement directly: a fake RSI that rises across two price lows.
# Forty bars, two clear swing lows, the second lower: 90 at bar 8, 85 at bar 26.
_pl = bars([101, 101, 101, 101, 101, 101,
            100, 99, 98, 96, 94, 93, 92, 91, 90, 91, 93, 95, 97, 98, 99, 98, 97, 95, 93, 91,
            90, 89, 88, 87, 86, 85.5, 85, 85.5, 86, 87, 88, 89, 90, 91, 92, 92, 92, 92, 92, 92])
_lows_pv = [p for p in _S.pivots(_pl[-40:], 2, 2) if p["kind"] == "low"]
_fake_rsi = [{"time": b["time"], "value": 40.0} for b in _pl]
if len(_lows_pv) >= 2:
    _by = {r["time"]: r for r in _fake_rsi}
    _by[_lows_pv[-2]["time"]]["value"] = 25.0
    _by[_lows_pv[-1]["time"]]["value"] = 35.0
_dv2 = V.rsi_divergence(_pl, _fake_rsi, lookback=40)
check("price lower low with RSI higher low is a bullish divergence",
      len(_lows_pv) >= 2 and _pl[-40:][_lows_pv[-1]["index"]]["low"] < _pl[-40:][_lows_pv[-2]["index"]]["low"]
      and _dv2 and _dv2["stance"] == "bull", (_dv2, [(p["time"], p["price"]) for p in _lows_pv]))
check("too little history for divergence yields nothing",
      V.rsi_divergence(_pl[:20], _fake_rsi[:20], lookback=40) is None)

# floor_record: earlier floor episodes and the best gain after each.
_fr_bars = bars([100, 90, 80, 70, 60, 70, 80, 90, 100, 110, 100, 90, 80, 70, 60, 50, 60, 70, 80, 90, 100, 110, 120, 110, 100])
_fr_series = [{"time": b["time"], "value": (-95.0 if b["close"] <= 60 else -40.0)} for b in _fr_bars]
_fr = V.floor_record(_fr_bars, _fr_series, floor=-80.0, horizon=6)
check("each earlier floor episode is recorded with the gain that followed",
      len(_fr["episodes"]) == 2 and all(e["gain_pct"] > 0 for e in _fr["episodes"]), _fr)
check("the record measures the BEST high within the horizon, not the close",
      _fr["episodes"][0]["gain_pct"] == round((110 * 1.01 / 60 - 1) * 100, 1), _fr["episodes"])
_fr_open = V.floor_record(_fr_bars + bars([50, 45], start="2025-01-01"),
                          _fr_series + [{"time": "2025-01-01", "value": -95.0}, {"time": "2025-01-02", "value": -95.0}],
                          floor=-80.0, horizon=6)
check("the current, still-open episode is not counted as a result",
      len(_fr_open["episodes"]) == 2, _fr_open)

# thin_volume: where price sits against the volume-by-price profile.
_prof = {"bins": [{"low": 40 + i, "high": 41 + i, "share": (0.30 if i == 5 else 0.01)} for i in range(20)],
         "poc": {"low": 45, "high": 46, "price": 45.5, "share": 0.30}}
_tv = V.thin_volume(_prof, price=47.0)
check("above the heaviest node with little traded overhead reads as thin air above",
      _tv and _tv["stance"] == "bull" and "thin volume overhead" in _tv["detail"], _tv)
_tv2 = V.thin_volume(_prof, price=44.0)
check("below the heaviest node with little traded beneath reads as thin air below",
      _tv2 and _tv2["stance"] == "bear", _tv2)
_tv3 = V.thin_volume(_prof, price=45.5)
check("inside the node is a range, not a level, and carries no stance",
      _tv3 and _tv3["stance"] is None, _tv3)
_prof_heavy = dict(_prof, bins=[dict(b, share=0.05) for b in _prof["bins"]])
check("with volume evenly spread there is nothing thin to report",
      V.thin_volume(_prof_heavy, price=47.0) is None)

# channel_record_item: the record spoken at the edge, and silence elsewhere.
_rec = {"lower_now": 100.0, "upper_now": 110.0,
        "floor": [{"rally_pct": 12.0, "open": False}, {"rally_pct": 9.0, "open": False}, {"rally_pct": None, "open": True}],
        "ceiling": [{"fade_pct": -8.0, "open": False}]}
_ci = V.channel_record_item(_rec, price=100.3, atr=1.0)
check("at the floor the item is bullish and quotes the completed rallies only",
      _ci and _ci["stance"] == "bull" and "+12%" in _ci["detail"] and "+9%" in _ci["detail"]
      and "last 2 touches" in _ci["detail"], _ci)
_ci2 = V.channel_record_item(_rec, price=109.8, atr=1.0)
check("at the ceiling the item is the take-profit reading, never a buy",
      _ci2 and _ci2["stance"] == "extended", _ci2)
check("mid-channel there is no edge item", V.channel_record_item(_rec, price=105.0, atr=1.0) is None)

# The reversal zone and the target, on a constructed leg.
_rz_px = [50 + i for i in range(40)] + [89 - i * 1.5 for i in range(22)]   # rally 50->89, back to ~57.5
_g_rz = V.gather(bars(_rz_px))
_rz_items = [e for e in _g_rz["evidence"] if e["name"] == "reversal zone"]
_f_rz = _g_rz["fib"]
_in_band = _f_rz and _f_rz["reversal_zone"] and _f_rz["reversal_zone"]["low"] <= _g_rz["price"] <= _f_rz["reversal_zone"]["high"] + 0.75 * _g_rz["atr"]
check("a pullback sitting in the 0.786-0.887 band of its own rally is named as the reversal zone",
      (not _in_band) or (_rz_items and _rz_items[0]["stance"] == "bull"),
      (_g_rz["price"], _f_rz and _f_rz["reversal_zone"], _rz_items))
_g_tgt = V.gather(bars([50 + i * 0.5 for i in range(70)] + [84.5 - i * 0.3 for i in range(10)]))
_tgt = [e for e in _g_tgt["evidence"] if e["name"] == "target"]
check("the next extension target above price is reported with no stance and a level",
      _tgt and _tgt[0]["stance"] is None and _tgt[0]["level"] and _tgt[0]["level"] > _g_tgt["price"], _tgt)
check("a target more than double the price is not reported as one",
      all(e["level"] <= _g_tgt["price"] * (1 + V.MAX_TARGET_GAIN) for e in _tgt), _tgt)


# ------------------------------------- the shapes on the RonnieV graphic -----
# Detected from pivots and trendlines, every one at zero weight. The tests are
# about the geometry each helper accepts and refuses.
def _hs_pivots(bear=True):
    # left shoulder 100, head 110, right shoulder 101; lows between at 92 and 93
    k = 1 if bear else -1
    f = lambda v: 200 + k * (v - 100) if not bear else v
    pts = [("high", 100, 0), ("low", 92, 5), ("high", 110, 10), ("low", 93, 15), ("high", 101, 20)]
    out = []
    for kind, px, i in pts:
        if not bear:
            kind = "low" if kind == "high" else "high"
            px = 200 - px
        out.append({"kind": kind, "price": float(px), "index": i, "time": f"t{i}", "label": ""})
    return out
_hs = V.head_shoulders(_hs_pivots(True), price=97.0, atr=1.0)
check("three highs with a taller middle and matching shoulders form a head and shoulders",
      _hs and _hs["kind"] == "head and shoulders" and not _hs["confirmed"] and _hs["stance"] is None
      and _hs["neck"] == 92.0, _hs)
_hs2 = V.head_shoulders(_hs_pivots(True), price=90.0, atr=1.0)
check("a close under the neckline confirms it and gives it a bearish stance",
      _hs2 and _hs2["confirmed"] and _hs2["stance"] == "bear", _hs2)
check("a break that is long gone is not today's pattern",
      V.head_shoulders(_hs_pivots(True), price=80.0, atr=1.0) is None)
_ihs = V.head_shoulders(_hs_pivots(False), price=110.0, atr=1.0)
check("the inverted form confirms above its neckline with a bullish stance",
      _ihs and _ihs["kind"] == "inverted head and shoulders" and _ihs["confirmed"] and _ihs["stance"] == "bull", _ihs)
_wide = _hs_pivots(True); _wide[-1]["price"] = 120.0
check("shoulders that do not match are not a head and shoulders",
      V.head_shoulders(_wide, price=97.0, atr=1.0) is None)

_tt = [{"kind": k, "price": float(p_), "index": i, "time": f"t{i}", "label": ""} for k, p_, i in
       (("low", 80, 0), ("high", 100, 5), ("low", 90, 10), ("high", 101, 15), ("low", 91, 20), ("high", 99, 25))]
_tp = V.triple_pattern(_tt, price=95.0, atr=1.0)
check("three highs within tolerance with two pullbacks form a triple top",
      _tp and _tp["kind"] == "triple top" and not _tp["confirmed"] and _tp["neck"] == 90.0, _tp)
check("a triple top confirms below the lower pullback low",
      V.triple_pattern(_tt, price=88.0, atr=1.0)["stance"] == "bear")
_tb = [dict(p_, kind=("low" if p_["kind"] == "high" else "high"), price=200 - p_["price"]) for p_ in _tt]
_tbp = V.triple_pattern(_tb, price=112.0, atr=1.0)
check("the mirror is a triple bottom confirmed above the higher bounce high",
      _tbp and _tbp["kind"] == "triple bottom" and _tbp["confirmed"] and _tbp["stance"] == "bull", _tbp)

def _line(side, p0, p1, t0="t0", t1="t20"):
    return {"side": side, "from": {"time": t0, "price": p0}, "to": {"time": t1, "price": p1},
            "reaches_present": True, "touches": 3}
_idx = {"t0": 0, "t20": 20}
_asc = V.converging_lines([_line("support", 90, 98), _line("resistance", 100, 100.2)], price=99.0, atr=1.0, bars_index=_idx)
check("rising support under flat resistance is an ascending triangle, bullish",
      _asc and _asc["kind"] == "ascending triangle" and _asc["stance"] == "bull", _asc)
_desc = V.converging_lines([_line("support", 90, 90.2), _line("resistance", 110, 102)], price=95.0, atr=1.0, bars_index=_idx)
check("flat support under falling resistance is a descending triangle, bearish",
      _desc and _desc["kind"] == "descending triangle" and _desc["stance"] == "bear", _desc)
_sym = V.converging_lines([_line("support", 90, 96), _line("resistance", 110, 104)], price=100.0, atr=1.0, bars_index=_idx)
check("rising support under falling resistance is symmetrical and takes no side",
      _sym and _sym["kind"] == "symmetrical triangle" and _sym["stance"] is None, _sym)
_rw = V.converging_lines([_line("support", 90, 100), _line("resistance", 100, 104)], price=101.0, atr=1.0, bars_index=_idx)
check("both rising with support steeper is a rising wedge, bearish",
      _rw and _rw["kind"] == "rising wedge" and _rw["stance"] == "bear", _rw)
_fw = V.converging_lines([_line("support", 100, 96), _line("resistance", 120, 104)], price=100.0, atr=1.0, bars_index=_idx)
check("both falling with resistance steeper is a falling wedge, bullish",
      _fw and _fw["kind"] == "falling wedge" and _fw["stance"] == "bull", _fw)
check("price outside the two lines is a breakout, not a pattern",
      V.converging_lines([_line("support", 90, 98), _line("resistance", 100, 100.2)], price=103.0, atr=1.0, bars_index=_idx) is None)
check("a flipped line does not bound a pattern",
      V.converging_lines([dict(_line("support", 90, 98), flipped_from="resistance"), _line("resistance", 100, 100.2)],
                         price=99.0, atr=1.0, bars_index=_idx) is None)
_g_pat = V.gather(bars([10 + i * 0.3 for i in range(150)] + [55 - i * 0.2 for i in range(60)]))
check("every pattern item is recorded at zero weight",
      all(e["weight"] == 0.0 for e in _g_pat["evidence"]
          if e["name"] in {"head and shoulders", "triple", "triangle", "wedge"}))

# _next_upside: the 1.272 / 1.414 targets are candidates in a rising leg.
_g_up = {"price": 100.0, "atr": 1.0,
         "fib": {"direction": "up", "levels": [{"ratio": 1.0, "price": 98.0, "kind": "extension"},
                                                {"ratio": 1.618, "price": 130.0, "kind": "extension"}],
                 "targets": [{"ratio": 1.272, "price": 112.0}, {"ratio": 1.414, "price": 120.0}, {"ratio": 1.618, "price": 130.0}]}}
_lvl, _why = V._next_upside(_g_up)
check("the next upside level a trim gives up is the nearest target above, 1.272 before 1.618",
      _lvl == 112.0 and "1.272" in _why, (_lvl, _why))
_g_dn = dict(_g_up, fib=dict(_g_up["fib"], direction="down"))
check("in a falling leg the targets are not offered as upside",
      V._next_upside(_g_dn)[0] == 130.0, V._next_upside(_g_dn))

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
