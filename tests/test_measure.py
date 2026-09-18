"""The measurement: drift removed by date, errors clustered by date, weights that score a verdict."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import measure

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

# Two dates. On the first every call did +10 (the universe ran); on the second
# every call did -10. An item present on both days carries no information —
# its residual must be zero — however good its raw excess looks.
calls = [
    {"date": "2026-01-02", "symbol": "A", "action": "buy", "confidence": "high", "excess": 0.12, "items": [("x", "bull")]},
    {"date": "2026-01-02", "symbol": "B", "action": "hold", "confidence": "low", "excess": 0.08, "items": [("y", "bear")]},
    {"date": "2026-01-09", "symbol": "A", "action": "buy", "confidence": "high", "excess": -0.08, "items": [("x", "bull")]},
    {"date": "2026-01-09", "symbol": "B", "action": "hold", "confidence": "low", "excess": -0.12, "items": [("y", "bear")]},
]
measure.with_residuals(calls)
check("the same-date mean is the baseline", abs(calls[0]["baseline"] - 0.10) < 1e-9 and abs(calls[2]["baseline"] + 0.10) < 1e-9)
check("residuals are excess minus that day's baseline",
      abs(calls[0]["residual"] - 0.02) < 1e-9 and abs(calls[1]["residual"] + 0.02) < 1e-9)
tbl = {(r["item"], r["stance"]): r for r in measure.item_table(calls)}
check("an item that always did +2 over the day's mean measures +2, whatever the market did",
      abs(tbl[("x", "bull")]["mean"] - 0.02) < 1e-9, tbl.get(("x", "bull")))
check("and one that always did -2 measures -2, and is flagged as agreeing with a bear claim",
      abs(tbl[("y", "bear")]["mean"] + 0.02) < 1e-9 and tbl[("y", "bear")]["agrees"], tbl.get(("y", "bear")))
check("two dates is too few to trust", not tbl[("x", "bull")]["enough"])

# Clustering: ten calls on one day and one call on another are two observations.
by_date = {"d1": [0.05] * 10, "d2": [-0.05]}
st = measure._clustered(by_date)
check("the clustered mean weights each date equally", abs(st["mean"]) < 1e-9 and st["dates"] == 2 and st["calls"] == 11, st)

w = {("x", "bull"): 0.02, ("y", "bear"): -0.02}
check("a verdict's measured score sums the residuals of the items it carries, in points",
      measure.measured_score([{"name": "x", "stance": "bull"}, {"name": "y", "stance": "bear"},
                              {"name": "z", "stance": None}], w) == 0.0)
check("an unmeasured item contributes nothing, and no measured item means no score",
      measure.measured_score([{"name": "q", "stance": "bull"}], w) is None
      and measure.measured_score([{"name": "x", "stance": "bull"}, {"name": "q", "stance": "bull"}], w) == 2.0)

# The staircase needs enough calls and cuts into equal fifths.
test = [{"date": f"2026-0{1 + i % 9}-{1 + i % 27:02d}", "residual": (i % 5 - 2) * 0.01, "s": i % 5}
        for i in range(500)]
stairs = measure.staircase(test, lambda c: c["s"])
check("fifths rise with the score when the score is the outcome",
      len(stairs) == 5 and all(stairs[i]["mean_residual"] < stairs[i + 1]["mean_residual"] for i in range(4)),
      [round(s["mean_residual"] or 0, 3) for s in stairs])
check("too few calls gives no staircase rather than a misleading one", measure.staircase(test[:50], lambda c: c["s"]) == [])


cuts = (-0.02, -0.005, 0.01, 0.03)
check("a score is placed in its fifth against the record's cut points",
      [measure.fifth_of(v, cuts) for v in (-5.0, -1.0, 0.0, 2.0, 4.0)] == [1, 2, 3, 4, 5])
check("no score or no cuts means no fifth", measure.fifth_of(None, cuts) is None and measure.fifth_of(1.0, None) is None)


# ---- pairs: how two items do together against each alone
def _call(d, items, res):
    return {"date": d, "items": items, "residual": res}
_pc = []
for i in range(40):
    d = f"2025-01-{(i % 28) + 1:02d}" if i < 28 else f"2025-02-{(i - 28) + 1:02d}"
    _pc.append(_call(d, [("x", "bull")], 0.02))
    _pc.append(_call(d, [("y", "bull")], 0.01))
    _pc.append(_call(d, [("x", "bull"), ("y", "bull")], 0.06))     # together: more than 0.03
    _pc.append(_call(d, [("z", "bear")], -0.01))
_pairs = measure.pairs(_pc, min_calls=10)
_xy = next((q for q in _pairs if q["a"] == "x (bull)" and q["b"] == "y (bull)"), None)
check("a pair that fires together often enough is reported",
      _xy is not None and _xy["calls"] == 40, _pairs)
check("the pair's lift is what the two do together minus the sum of what each does alone",
      _xy and abs(_xy["additive"] - (_xy["a_alone"] + _xy["b_alone"])) < 1e-9
      and abs(_xy["lift"] - (_xy["mean"] - _xy["additive"])) < 1e-9, _xy)
check("a positive lift means they confirm each other, and the numbers say so here",
      _xy and _xy["lift"] > 0.005, _xy and _xy["lift"])
check("a pair that never co-occurs is not invented",
      not any(q["a"].startswith("z") or q["b"].startswith("z") for q in _pairs))
check("too few co-occurrences is not a pair",
      not any(q["a"] == "x (bull)" for q in measure.pairs(_pc, min_calls=100)))

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
