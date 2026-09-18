"""Tests for the method library.

A method that silently mis-scores is worse than no method: it looks like
somebody else's judgement while being an artefact. Each condition is therefore
tested against a series constructed so the right answer is known by hand.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import indicators as I, methods

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def series(closes, highs=None, lows=None):
    """Monthly bars, first of each month so resampling is a no-op."""
    out = []
    for i, c in enumerate(closes):
        y, m = 2020 + i // 12, i % 12 + 1
        out.append({"time": f"{y}-{m:02d}-01", "open": c, "close": c,
                    "high": (highs or closes)[i], "low": (lows or closes)[i],
                    "volume": 1000})
    return out


spec = methods.METHODS["cantonese-cat-monthly-reversion"]

# A steadily rising series: MA rises, price above kijun, far above the 20-MA.
rising = series([100 + i * 3 for i in range(60)])
ctx = methods.build_context(rising, spec)
met, val, _ = methods.CONDITIONS["ma20_rising"](rising, ctx)
check("a rising series gives a rising 20-period MA", met is True, val)
met, val, _ = methods.CONDITIONS["above_kijun"](rising, ctx)
check("a rising series closes above the kijun", met is True, val)
met, val, _ = methods.CONDITIONS["near_20ma"](rising, ctx, tolerance=0.02)
check("a steadily rising series is NOT near its 20-period MA", met is False, val)
# "Near" is a distance, so it has to be symmetric. Testing only the stretched-
# ABOVE case leaves `abs(dist) <= tolerance` indistinguishable from
# `dist <= tolerance`, which calls a name 40% below its 20-month average "near"
# it — and near_20ma is the highest-weighted condition in the method, so that
# reading would qualify exactly the falling knives it is meant to exclude.
_below = series([300 - i * 3 for i in range(60)])
_bctx = methods.build_context(_below, spec)
_bm, _bv, _ = methods.CONDITIONS["near_20ma"](_below, _bctx, tolerance=0.10)
check("a series far BELOW its 20-period MA is not 'near' it either",
      _bm is False and _bv < -0.10, _bv)

# A falling series: MA falls, price below it.
falling = series([300 - i * 3 for i in range(60)])
ctx = methods.build_context(falling, spec)
met, _v, _ = methods.CONDITIONS["ma20_rising"](falling, ctx)
check("a falling series gives a falling 20-period MA", met is False)
met, _v, _ = methods.CONDITIONS["below_20ma"](falling, ctx)
check("a falling series closes below its 20-period MA", met is True)

# Flat series: price sits ON the MA, %B mid-band.
flat = series([100] * 60)
ctx = methods.build_context(flat, spec)
met, val, _ = methods.CONDITIONS["near_20ma"](flat, ctx, tolerance=0.01)
check("a flat series sits on its 20-period MA", met is True and abs(val) < 1e-9, val)
# A flat average is not a rising one. His argument is that a rising 20-month MA
# SUPPORTS price and a falling one REJECTS it; an average going sideways does
# neither, and scoring it as support is the more dangerous of the two errors.
_fm, _fv, _ = methods.CONDITIONS["ma20_rising"](flat, ctx)
check("a perfectly flat 20-period MA is not counted as rising",
      _fm is False and abs(_fv) < 1e-12, _fv)

# %B: at the lower band the value is 0, at the upper band 1.
wave = series([100 + (10 if i % 2 else -10) for i in range(60)])
ctx = methods.build_context(wave, spec)
_m, pb, _ = methods.CONDITIONS["percent_b"](wave, ctx)
check("%B stays within 0..1 on an oscillating series", 0 <= pb <= 1, pb)

# Divergence: price makes a lower low while RSI makes a higher low. The two
# lows must be genuine SWING lows — the old version took the two lowest BARS in
# the window, which are routinely adjacent, so two points on one descent counted
# as a divergence.
_lows = [60] * 40 + [58, 54, 48, 44, 50, 56, 58, 57, 56, 55,
                     54, 52, 50, 46, 42, 52, 58, 60, 61, 62]
div = series([l + 1 for l in _lows], lows=_lows)
ctx = methods.build_context(div, spec)
met, _v, detail = methods.CONDITIONS["rsi_bullish_divergence"](div, ctx)
check("a real divergence is detected", met is True, detail)
check("and it explains itself", "RSI" in detail, detail)

# A straight decline has no second swing low, so there is nothing to diverge.
# `_m2 is not True` was the whole assertion, which is satisfied by False and by
# None alike — so it could not tell "the logic rejected this" from "the logic
# never ran". The reason is asserted too.
_slide = series([60 - i * 0.5 for i in range(70)],
                lows=[59 - i * 0.5 for i in range(70)])
_m2, _v2, _d2 = methods.CONDITIONS["rsi_bullish_divergence"](
    _slide, methods.build_context(_slide, spec))
check("a monotonic decline is not called a divergence, for want of swing lows",
      _m2 is None and "swing lows" in _d2, (_m2, _d2))

# The condition also refuses two lows fewer than 3 bars apart as "one move, not
# two events". That branch USED to be tested with a fixture whose window held a
# single swing low, so it returned "no two swing lows" and the assertion passed
# without the distance rule ever running.
#
# It cannot be reached at all with the pivot parameters this condition uses, and
# that is worth pinning rather than faking: pivots(2,2) is strict on the left
# and permissive on the right, so a low pivot at i requires low[i] <= low[i+1]
# and low[i] <= low[i+2] while a low pivot at i+1 or i+2 requires the opposite.
# The guard is therefore a safeguard against someone loosening the window — with
# pivots(1,1) two lows CAN land two bars apart — not a live filter. If this ever
# fails, the guard has become load-bearing and needs a fixture of its own.
import random as _random                                          # noqa: E402
from app import structure as _S                                   # noqa: E402
_random.seed(11)
_closest, _closest_loose = 99, 99
for _t in range(1500):
    _pts = [{"time": f"t{i}", "high": _random.randint(0, 30),
             "low": _random.randint(0, 30)} for i in range(_random.randint(12, 40))]
    for _left, _right, _key in ((2, 2, "tight"), (1, 1, "loose")):
        _ix = [q["index"] for q in _S.pivots(_pts, _left, _right) if q["kind"] == "low"]
        for _a, _b in zip(_ix, _ix[1:]):
            if _key == "tight":
                _closest = min(_closest, _b - _a)
            else:
                _closest_loose = min(_closest_loose, _b - _a)
check("the pivot window this condition uses cannot produce lows closer than 3 bars",
      _closest >= 3, _closest)
check("a looser pivot window could, which is what the distance guard is for",
      _closest_loose < 3, _closest_loose)

# Scoring contract.
r = methods.evaluate(rising, "cantonese-cat-monthly-reversion")
check("evaluate returns a score no greater than what is possible",
      r["score"] <= r["possible"], (r["score"], r["possible"]))
check("pct is score over possible",
      abs(r["pct"] - r["score"] / r["possible"]) < 1e-9)
check("every condition reports a human-readable detail",
      all(c["detail"] for c in r["conditions"]))
check("every condition names why it is in the method",
      all(c["why"] for c in r["conditions"]))
# `missing` means FAILED, not "not met" — a condition that could not be computed
# belongs in `unavailable`, and lumping the two together is what made a young
# listing look like a chart that failed its trend filter.
check("missing lists exactly the conditions that FAILED",
      set(r["missing"]) == {c["condition"] for c in r["conditions"]
                            if c["met"] is False})
check("unavailable lists exactly the conditions that could not be computed",
      set(r["unavailable"]) == {c["condition"] for c in r["conditions"]
                                if c["met"] is None})
check("the two sets never overlap",
      not (set(r["missing"]) & set(r["unavailable"])))
check("possible counts only what could be evaluated",
      r["possible"] == sum(c["weight"] for c in r["conditions"]
                           if c["met"] is not None),
      (r["possible"], r["unavailable_weight"]))
check("coverage is the share of the method's weight that was computable",
      abs(r["coverage"] - r["possible"] / (r["possible"] + r["unavailable_weight"])) < 1e-9
      if (r["possible"] + r["unavailable_weight"]) else True,
      r["coverage"])

# A name too young for a long average must not be scored down for its age.
_young = series([100 + i * 0.4 for i in range(80)])
_y = methods.evaluate(_young, "momentum-relative-strength")
check("an uncomputable condition is excluded from the denominator, not failed",
      "ma_stack" not in _y["missing"] or _y["coverage"] < 1.0,
      (_y["missing"], _y["unavailable"], round(_y["coverage"], 3)))

short = methods.evaluate(series([100] * 6), "cantonese-cat-monthly-reversion")
check("too little history reports insufficient rather than scoring zero",
      short.get("insufficient") is True, short)
check("an unknown method errors rather than returning a score",
      "error" in methods.evaluate(rising, "nope"))

# The momentum method must behave as the opposite of the reversion one.
# `outperforming` needs something to outperform: with no benchmark it now
# abstains rather than quietly scoring "did it go up at all", so these pass a
# flat one — against which the rising series really is relatively strong.
mom = "momentum-relative-strength"
flat_bench = [dict(b, open=100.0, high=101.0, low=99.0, close=100.0) for b in rising]
r_rise = methods.evaluate(rising, mom, flat_bench)
r_fall = methods.evaluate(falling, mom, flat_bench)
check("momentum scores a rising series above a falling one",
      r_rise["pct"] > r_fall["pct"], (r_rise["pct"], r_fall["pct"]))
check("momentum scores a falling series near zero", r_fall["pct"] < 0.35, r_fall["pct"])

rev = "cantonese-cat-monthly-reversion"
# Relative strength must be RELATIVE: the same series scores differently
# depending on what it is measured against.
_vs_flat = [c for c in methods.evaluate(rising, mom, flat_bench)["conditions"]
            if c["condition"] == "outperforming"][0]
_strong_bench = [dict(b, open=b["close"] * 3, high=b["close"] * 3,
                      low=b["close"] * 3, close=b["close"] * 3) for b in rising]
_vs_strong = [c for c in methods.evaluate(rising, mom, _strong_bench)["conditions"]
              if c["condition"] == "outperforming"][0]
check("outperforming beats a flat benchmark", _vs_flat["met"] is True, _vs_flat["detail"])
check("the SAME series fails against a stronger benchmark",
      _vs_strong["met"] is False, _vs_strong["detail"])
_none = [c for c in methods.evaluate(rising, mom)["conditions"]
         if c["condition"] == "outperforming"][0]
check("with no benchmark it abstains rather than scoring 'went up at all'",
      _none["met"] is None, _none["detail"])

check("the two methods disagree on a strongly rising series",
      methods.evaluate(rising, mom, flat_bench)["pct"]
      > methods.evaluate(rising, rev)["pct"],
      (methods.evaluate(rising, mom, flat_bench)["pct"],
       methods.evaluate(rising, rev)["pct"]))

# A 200-period average needs 200 bars, so the stack test uses a longer series
# than the 60-bar fixtures above — otherwise it reports "unavailable", which is
# correct behaviour and a useless assertion.
long_rise = series([100 * (1.01 ** i) for i in range(240)])
long_fall = series([100 * (0.99 ** i) for i in range(240)])
ctx_r = methods.build_context(long_rise, methods.METHODS[mom])
met, val, _ = methods.CONDITIONS["ma_stack"](long_rise, ctx_r)
check("a rising series stacks 20 > 50 > 200", met is True, val)
met, val, _ = methods.CONDITIONS["near_high"](long_rise, ctx_r)
check("a rising series is at its own high", met is True, val)
met, _v, _ = methods.CONDITIONS["ma_stack"](long_fall, methods.build_context(long_fall, methods.METHODS[mom]))
check("a falling series does not stack", met is False)
met, _v, detail = methods.CONDITIONS["ma_stack"](rising, methods.build_context(rising, methods.METHODS[mom]))
check("too little history reports unavailable rather than guessing",
      met is None and "history" in detail, detail)
met, val, _ = methods.CONDITIONS["rsi_between"](flat, methods.build_context(flat, methods.METHODS[mom]))
check("a flat series fails the momentum RSI band", met is False, val)

# Documentation contract — a method nobody can audit is not usable.
for key, m in methods.METHODS.items():
    check(f"{key} cites its source", bool(m.get("source")))
    check(f"{key} quotes evidence for its rules", len(m.get("evidence", [])) >= 3)
    check(f"{key} states what invalidates it", bool(m.get("invalidation")))
    check(f"{key} states what it ignores", len(m.get("ignores", [])) >= 1)
    check(f"{key} states its own caveats", len(m.get("caveats", [])) >= 1)
    check(f"{key} only uses defined conditions",
          all(s["condition"] in methods.CONDITIONS for s in m["setup"]))
    check(f"{key} gives every rule a reason",
          all(s.get("why") for s in m["setup"]))
    check(f"{key} only uses registered indicators",
          all(n in I.REGISTRY for n, _a in m["indicators"].values()))

# --- scoring DIRECTION -------------------------------------------------------
# The engine adds weight when a condition is met, so a condition phrased as a
# warning rewards exactly the names it is meant to flag. Wiring
# ma_support_exhausted straight into a method ranked the worn-out names top.
# The old fixture here produced ONE touch, so `worn` was False whichever way the
# counting worked and the run-collapsing rule below was never exercised. These
# two are built so the count itself is the thing being asserted.
def _quiet_drift(n=80):
    """A quiet name creeping upward with its low inside the band on EVERY bar.

    It has not pulled back once, so this is one long test of the average, not
    eighty. Counting per bar is the bug the primitive was written to fix — it
    scored 22 touches in 22 bars and diagnose then warned that the name's
    support was about to fail.
    """
    out = []
    for i in range(n):
        c = 100 + i * 0.05
        out.append({"time": f"2026-{i//28+1:02d}-{i%28+1:02d}", "open": c,
                    "high": round(c + 0.3, 4), "low": round(c - 0.3, 4),
                    "close": round(c, 4), "volume": 100})
    return out


def _repeated_tests(n=80):
    """The same name, but actually pulling back to the average and away again."""
    out = []
    for i in range(n):
        c = 100 + i * 0.05
        near = i >= n - 22 and (i - (n - 22)) % 7 in (0, 1)
        out.append({"time": f"2026-{i//28+1:02d}-{i%28+1:02d}", "open": c,
                    "high": round(c + 0.3, 4),
                    "low": round(c - (0.3 if near else 0.02), 4),
                    "close": round(c, 4), "volume": 100})
    return out


_drift_worn, _drift_n, _ = methods.CONDITIONS["ma_support_exhausted"](_quiet_drift(), {})
check("an unbroken run inside the band is ONE test of the average, not one per bar",
      _drift_n == 1, _drift_n)
check("so a name that never pulled back is not called worn out",
      _drift_worn is False, (_drift_worn, _drift_n))

_bars = _repeated_tests()
_worn, _n1, _detail = methods.CONDITIONS["ma_support_exhausted"](_bars, {})
_intact, _n2, _ = methods.CONDITIONS["ma_support_intact"](_bars, {})
check("repeatedly testing the average and pulling away counts once per test",
      _worn is True and _n1 >= 3, (_worn, _n1))
check("and the detail says the support is weakening", "weakening" in _detail, _detail)
check("ma_support_intact is the exact inverse of ma_support_exhausted",
      _worn is not None and _intact is (not _worn), (_worn, _intact))
check("both report the same touch count", _n1 == _n2, (_n1, _n2))

# Only touches FROM ABOVE count. Price crossing up through the average from
# below is a different event — it is support being reclaimed, not worn down —
# and counting it inflates the tally exactly when the setup is turning bullish.
# This series whips across its own average every couple of bars: three of the
# crossings come from above, four from below, and counting all seven would
# report a name in the middle of a recovery as one about to break.
def _whipsaw(n=80, amp=2.0, per=3):
    out = []
    for i in range(n):
        c = 100 + amp * __import__("math").sin(i * __import__("math").pi / per)
        out.append({"time": f"2026-{i//28+1:02d}-{i%28+1:02d}", "open": c,
                    "high": round(c + 0.3, 4), "low": round(c - 0.5, 4),
                    "close": round(c, 4), "volume": 100})
    return out


_wm, _wn, _ = methods.CONDITIONS["ma_support_exhausted"](_whipsaw(), {})
check("only tests of the average from ABOVE are counted, not crossings up "
      "through it",
      _wn == 3, _wn)

# Price already BELOW the average is a different state from support being worn
# down, and saying "3 touches, support weakening" about a name that has already
# broken would be describing a level that is gone.
_broken = _repeated_tests()
_broken[-1] = dict(_broken[-1], close=90.0, low=89.0)
_bm, _bv, _bd = methods.CONDITIONS["ma_support_exhausted"](_broken, {})
check("a name already below the average abstains rather than scoring touches",
      _bm is None and "already below" in _bd, (_bm, _bd))

check("the scored method uses the intact form, not the warning form",
      all(r["condition"] != "ma_support_exhausted"
          for r in methods.METHODS["ronniev-ma-stack-trend"]["setup"]),
      "a warning condition scored positively rewards the names it warns about")

# --- stack ordering ----------------------------------------------------------
_ctx = {"ema9": [{"time": "t", "value": 30}], "ema21": [{"time": "t", "value": 20}],
        "sma50": [{"time": "t", "value": 10}], "sma200": [{"time": "t", "value": 5}]}
_keys = ["ema9", "ema21", "sma50", "sma200"]
_flat = [{"time": "t", "open": 1, "high": 1, "low": 1, "close": 40, "volume": 1}]
_ok, _v, _ = methods.CONDITIONS["ma_stack_keys"](_flat, _ctx, keys=_keys)
check("a fully ordered four-deep stack is recognised", _ok is True)
_ctx2 = dict(_ctx, ema9=[{"time": "t", "value": 15}])
_ok2, _, _ = methods.CONDITIONS["ma_stack_keys"](_flat, _ctx2, keys=_keys)
check("an out-of-order stack is not", _ok2 is False)
_ok3, _, _d3 = methods.CONDITIONS["ma_stack_keys"](_flat, {"ema9": _ctx["ema9"]}, keys=_keys)
check("a missing average reports unknown rather than false", _ok3 is None, _d3)

# Ordering and price-above are genuinely different questions: the averages can be
# perfectly stacked while price has already dropped through the fastest of them.
_below = [{"time": "t", "open": 1, "high": 1, "low": 1, "close": 25, "volume": 1}]
_stacked, _, _ = methods.CONDITIONS["ma_stack_keys"](_below, _ctx, keys=_keys)
_above, _, _ = methods.CONDITIONS["above_all"](_below, _ctx, keys=_keys)
check("stack ordering and price-above-stack can disagree",
      _stacked is True and _above is False)

# --- scored, never signalled -------------------------------------------------
# The module's first promise: a name is presented as "five of seven conditions,
# here is which two are missing", never as a buy. That only holds if every
# condition that WAS evaluated hands back the number it decided on, so the
# reader can disagree with the threshold rather than only with the verdict.
_scored = methods.evaluate(long_rise, mom, flat_bench)
check("every condition that was evaluated reports the number behind it",
      all(isinstance(c["value"], (int, float)) for c in _scored["conditions"]
          if c["met"] is not None),
      [c["condition"] for c in _scored["conditions"]
       if c["met"] is not None and not isinstance(c["value"], (int, float))])
check("a perfect score is still reported as a fraction, not as a verdict",
      set(_scored) >= {"score", "possible", "pct", "coverage", "missing", "unavailable"}
      and "verdict" not in _scored and "action" not in _scored,
      sorted(_scored))

# --- scan: the coverage floor decides the TABLE, not just the shortlist -------
# scan() had no test at all. Its ranking is what the dashboard renders, and a
# name evaluated on a third of the method's weight heading that table is the
# failure the coverage floor exists to prevent — its highest-weighted trend
# filter never having been evaluated, sitting next to a name that cleared it on
# every condition.
import math as _math                                               # noqa: E402
from datetime import date as _date, timedelta as _td               # noqa: E402
from app import prices as _prices                                  # noqa: E402
from app.ledger import connect as _connect                         # noqa: E402


def _sessions(n, start=_date(2023, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += _td(days=1)
    return out


def _path(rate, n, wobble=0.03, base=100.0):
    """A compounding series with a sawtooth on it.

    The wobble is load-bearing: a series that only rises pins RSI at 100 and
    fails the momentum method's exhaustion ceiling, so nothing would clear the
    threshold and every assertion below would pass for the wrong reason.
    """
    out, v = [], base
    for i in range(n):
        v *= (1 + rate)
        out.append(round(v * (1 + wobble * _math.sin(i / 3.0)), 4))
    return out


_ALL = _sessions(800)
_conn = _connect(":memory:")


def _store(sym, closes, dates):
    _prices.store(_conn, sym, [(t, round(c, 4), round(c, 4), round(c * 1.01, 4),
                                round(c * 0.99, 4), 100_000)
                               for t, c in zip(dates, closes)], "test")


_store("SP500", _path(0.0003, 800, 0.004), _ALL)      # the benchmark scan resolves to
_store("SPY", _path(0.0003, 800, 0.004), _ALL)
_store("FULL", _path(0.0016, 800), _ALL)              # strong, on full history
_store("DOWN", _path(-0.0010, 800), _ALL)             # weak, on full history
_store("THIN", _path(0.0016, 130), _ALL[-130:])       # strong, on 26 weekly bars
_store("TINY", _path(0.0016, 90), _ALL[-90:])         # too short to score at all
_conn.commit()

SCAN = methods.scan(_conn, ["THIN", "DOWN", "FULL", "TINY"], mom, _ALL[-1])
_by = {r["symbol"]: r for r in SCAN["rows"]}
check("a name with too little history is skipped, not scored as a zero",
      [x["symbol"] for x in SCAN["skipped"]] == ["TINY"] and "TINY" not in _by,
      (SCAN["skipped"], list(_by)))
check("the thin fixture is the trap: a perfect score on a third of the weight",
      _by["THIN"]["pct"] == 1.0 and _by["THIN"]["coverage"] < 0.6
      and _by["FULL"]["pct"] == 1.0 and _by["FULL"]["coverage"] >= 0.6,
      [(k, v["pct"], round(v["coverage"], 3)) for k, v in _by.items()])
check("only names most of the method could be evaluated on qualify",
      [q["symbol"] for q in SCAN["qualifying"]] == ["FULL"],
      [q["symbol"] for q in SCAN["qualifying"]])
# The sharp end of it. DOWN scores 0.14 on the whole method; THIN scores 1.00 on
# a third of it. The one that was actually measured has to rank higher.
check("a name scoring 1.0 on a third of the method ranks BELOW one scoring 0.14 "
      "on all of it",
      [x["symbol"] for x in SCAN["rows"]].index("DOWN")
      < [x["symbol"] for x in SCAN["rows"]].index("THIN"),
      [x["symbol"] for x in SCAN["rows"]])
check("every scanned row carries the conditions that produced it",
      all(r["conditions"] and r["total"] == len(r["conditions"]) for r in SCAN["rows"]),
      [(r["symbol"], r["total"], len(r["conditions"])) for r in SCAN["rows"]])
check("an unknown method errors rather than scanning nothing",
      "error" in methods.scan(_conn, ["FULL"], "nope", _ALL[-1]))

# --- stack: agreement BETWEEN methods, on weight that was actually measured ---
# "Several methods agree" is the strongest thing this app says about a name, and
# stack() had no test. It also had no coverage floor, which made it the worst
# place to leave one out: SMOOTH below is a 150-session listing, so RonnieV's
# whole four-deep moving-average stack and his price-above-stack check cannot be
# computed for want of a 200-day average — 29% of that method's weight is all
# that gets measured — and momentum manages 56%. Both still clear 0.75 on what
# little ran, so it came back as two methods agreeing at 0.90 while scan() would
# not have put it in either method's shortlist.
_store("SMOOTH", _path(0.0016, 150, 0.008), _ALL[-150:])
_prices.invalidate_series_cache(_conn)
_STACK_SYMS = ["FULL", "DOWN", "SMOOTH"]
_per_method = {k: {r["symbol"]: r for r in methods.scan(_conn, _STACK_SYMS, k,
                                                        _ALL[-1])["rows"]}
               for k in methods.METHODS}
_smooth_hits = [(k, round(v["SMOOTH"]["pct"], 3), round(v["SMOOTH"]["coverage"], 3))
                for k, v in _per_method.items()
                if "SMOOTH" in v and v["SMOOTH"]["pct"] >= 0.75]
check("the fixture is the trap: two methods score SMOOTH above 0.75 on a third "
      "of their weight",
      len(_smooth_hits) >= 2 and all(c < 0.6 for _k, _p, c in _smooth_hits),
      _smooth_hits)

_st2 = {x["symbol"]: x for x in methods.stack(_conn, _STACK_SYMS, _ALL[-1], minimum=2)}
check("a name whose highest-weighted conditions were never evaluated is not "
      "reported as agreement",
      "SMOOTH" not in _st2, list(_st2))
check("a name both methods measured in full still is",
      "FULL" in _st2 and len(_st2["FULL"]["methods"]) >= 2,
      {k: len(v["methods"]) for k, v in _st2.items()})
check("every method credited with agreeing reports the coverage it agreed on",
      all(h["coverage"] >= 0.6 for x in _st2.values() for h in x["methods"]),
      [(x["symbol"], h["method"], h["coverage"])
       for x in _st2.values() for h in x["methods"] if h["coverage"] < 0.6])
check("the average is taken over the methods that actually agreed",
      all(abs(x["average"] - sum(h["pct"] for h in x["methods"]) / len(x["methods"]))
          < 1e-9 for x in _st2.values()),
      [(x["symbol"], x["average"]) for x in _st2.values()])
check("raising the bar past the number of methods returns nothing",
      methods.stack(_conn, _STACK_SYMS, _ALL[-1],
                    minimum=len(methods.METHODS) + 1) == [])

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
