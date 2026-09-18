"""Tests for the diagnosis engine.

The engine's whole value is that its findings are trustworthy, so the things
tested here are the ones that would quietly make it wrong: emitting a price
level nothing could ever reach, claiming a finding without the numbers behind
it, or presenting a recommendation when it is supposed to present an
observation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ledger import connect
from app import diagnose
from app import sectors as sectors_mod

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


conn = connect()
d = diagnose.diagnose(conn, "2024-06-07", "2026-08-28")

check("diagnosis runs on the real ledger", "error" not in d, d.get("error"))
check("it reports a portfolio value", d.get("value", 0) > 0, d.get("value"))
check("it produces findings", len(d.get("findings", [])) > 0, len(d.get("findings", [])))

# Every finding must carry its evidence and be readable on its own.
for f in d["findings"]:
    if not f.get("headline") or not f.get("detail"):
        check("every finding has a headline and detail", False, f.get("kind"))
        break
else:
    check("every finding has a headline and detail", True)

check("severities are from the known set",
      all(f["severity"] in diagnose.SEVERITY for f in d["findings"]),
      {f["severity"] for f in d["findings"]})
check("findings are ordered most severe first",
      [diagnose.SEVERITY[f["severity"]] for f in d["findings"]] ==
      sorted([diagnose.SEVERITY[f["severity"]] for f in d["findings"]], reverse=True))

# The engine reports, it does not instruct. If this ever fails, the engine has
# started giving advice, which is not what it is for.
ADVICE = ["you should", "we recommend", "buy now", "sell now", "i recommend",
          "you must", "advise you"]
text = " ".join(f["headline"] + " " + f["detail"] + " " + (f.get("why") or "")
                + " " + (f.get("action") or "") for f in d["findings"]).lower()
found = [w for w in ADVICE if w in text]
check("findings state observations rather than instructions", not found, found)

# Every finding says what it means and what could be done about it, in words
# a reader does not have to derive from the numbers.
check("every finding carries a plain-words meaning and a possible action",
      all(f.get("why") and f.get("action") for f in d["findings"]),
      [f["kind"] for f in d["findings"] if not (f.get("why") and f.get("action"))])
_conc = [f for f in d["findings"] if f["kind"] == "concentration" and "of the risk" in f["headline"]]
check("a risk-share finding names the window it was measured over",
      all("Measured over the whole range from" in f["detail"] for f in _conc),
      [f["detail"][:80] for f in _conc])
check("the diagnosis carries the concentration table it is now the home of",
      isinstance(d.get("concentration"), dict) and "rows" in d["concentration"])

# Price levels must be reachable — a negative or absurd level is worse than none.
for l in d.get("levels", []):
    for key in ("ma20", "lower_band", "kijun"):
        v = l.get(key)
        if v is not None:
            if v <= 0:
                check(f"{l['symbol']} {key} is a positive price", False, v)
                break
            if abs(v / l["close"] - 1) > 0.8:
                check(f"{l['symbol']} {key} is within reach of price", False,
                      f"{v} vs close {l['close']}")
                break
    else:
        continue
    break
else:
    check("every emitted level is a positive, reachable price", True)

check("a suppressed band explains why it is missing",
      all(l.get("note") for l in d.get("levels", []) if l.get("lower_band") is None))

check("drawdown is a fraction, not a percentage",
      -1 <= (d["risk"]["current_drawdown"] or 0) <= 0, d["risk"]["current_drawdown"])
check("themes and sectors are both reported",
      bool(d.get("themes")) and bool(d.get("sectors")))
check("an empty scope errors rather than inventing a diagnosis",
      "error" in diagnose.diagnose(conn, "2024-06-07", "2026-08-28", "Nonexistent Account"))


# ------------------------------------------------------ theme rotation ----
# Each theme is measured by one fund, the same way the eleven sectors are.
from app import themes as _themes
check("every theme fund maps to a theme that exists",
      set(_themes.THEME_ETFS) <= set(_themes.THEMES),
      sorted(set(_themes.THEME_ETFS) - set(_themes.THEMES)))
_tr = _themes.rotation(conn)
check("theme rotation returns one row per fund with the theme's key on it",
      "themes" in _tr and all(r.get("key") in _themes.THEME_ETFS and "relative" in r
                              for r in _tr["themes"]),
      [r.get("key") for r in _tr.get("themes", [])])
check("theme rotation measures the same windows as sector rotation",
      _tr.get("windows") == sectors_mod.rotation(conn).get("windows"),
      (_tr.get("windows")))


# The grid behind "Drawdown now" must be the report's grid: every weekday. A
# weekly grid never lands on the peak and so understates the drawdown from
# it — which is how the Diagnose and Risk tabs came to disagree.
from app import diagnose as _dx                                   # noqa: E402
_g = _dx._grid("2026-06-01", "2026-06-12")
check("the diagnose grid samples every weekday, not every seventh day",
      _g == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
             "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"], _g)
check("the grid always ends on the requested end date even when it is a weekend",
      _dx._grid("2026-06-01", "2026-06-07")[-1] == "2026-06-07")


# The grid behind "Drawdown now" must be the report's grid: every weekday. A
# weekly grid never lands on the peak and so understates the drawdown from
# it — which is how the Diagnose and Risk tabs came to disagree.
from app import diagnose as _dx                                   # noqa: E402
_g = _dx._grid("2026-06-01", "2026-06-12")
check("the diagnose grid samples every weekday, not every seventh day",
      _g == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
             "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"], _g)
check("the grid always ends on the requested end date even when it is a weekend",
      _dx._grid("2026-06-01", "2026-06-07")[-1] == "2026-06-07")

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<56} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
