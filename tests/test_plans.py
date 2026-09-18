"""Buy plans: the gap rule and the max price, judged without a market."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import plans

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

P = {"symbol": "TEM", "max_price": 63.61, "gap_pct": 2.0}
check("no gap and price at the number: the buy condition is met",
      [k for k, _ in plans.judge(P, 64.62, 64.40, 63.50)] == ["at_level"], plans.judge(P, 64.62, 64.40, 63.50))
check("no gap but price above the number: nothing", plans.judge(P, 64.62, 64.40, 65.00) == [])
check("a gap over the rule says wait", [k for k, _ in plans.judge(P, 64.62, 66.50, 66.80)] == ["gapped"], plans.judge(P, 64.62, 66.50, 66.80))
check("a gap that then pulls back under the open and to the number is the pullback the plan waited for",
      [k for k, _ in plans.judge(P, 64.62, 66.50, 63.40)] == ["gapped", "pulled_back"], plans.judge(P, 64.62, 66.50, 63.40))
check("a gap that pulls back under the open but stays above the number is not a buy",
      [k for k, _ in plans.judge(P, 64.62, 66.50, 65.00)] == ["gapped"])
check("a gap inside the rule is no gap", [k for k, _ in plans.judge(P, 64.62, 65.20, 63.00)] == ["at_level"])
check("no bars yet: nothing", plans.judge(P, 64.62, None, None) == [])

mem = sqlite3.connect(":memory:"); mem.row_factory = sqlite3.Row
r = plans.add(mem, "tem", 63.61, 2, "the act level")
check("a plan is stored upper-cased with its numbers", r["symbol"] == "TEM" and r["max_price"] == 63.61, r)
plans.add(mem, "TEM", 62.0, 3)
check("a new plan on the same name replaces the old one", [p["max_price"] for p in plans.active(mem)] == [62.0], plans.active(mem))
bars = {"TEM": [("2026-09-08T09:30", 64.40, 64.9, 64.1, 64.3), ("2026-09-08T09:45", 64.3, 64.4, 61.8, 61.9)]}
got = plans.check(mem, lambda s: bars.get(s, []), lambda s: 64.62, "2026-09-08")
check("check raises the alert with a key per condition and day", len(got) == 1 and got[0]["key"] == "plan:TEM:at_level:2026-09-08", got)
got2 = plans.check(mem, lambda s: bars.get(s, []), lambda s: 64.62, "2026-09-08")
check("the same condition is not raised twice in a day", got2 == [], got2)
plans.remove(mem, plans.active(mem)[0]["id"])
check("done removes the plan", plans.active(mem) == [])
try:
    plans.add(mem, "", 0); check("an empty plan is refused", False)
except ValueError:
    check("an empty plan is refused", True)

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  -> {detail}"))
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
