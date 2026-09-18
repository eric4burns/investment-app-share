"""What changed: refunds reduce spending, and typical is a typical month."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import trends

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def row(day, amount, cat="Groceries", kind="expense"):
    return {"txn_date": day, "amount": amount, "category": cat, "category_kind": kind, "description": cat}


rows = []
for m in range(1, 8):
    rows.append(row(f"2026-{m:02d}-05", -500.0))
    rows.append(row(f"2026-{m:02d}-10", -100.0 * m, "Amazon"))
rows.append(row("2026-07-12", 200.0))          # a refund in the newest month
spend = trends.by_category(rows)
check("a refund reduces the month's spending", abs(spend["Groceries"]["2026-07"] - 300.0) < 1e-6, spend["Groceries"])
c = trends.changes(rows, asof="2026-08-15")
check("the newest complete month is compared", c["month"] == "2026-07", c["month"])
check("typical is the median of the baseline months' totals, not a sum of medians",
      abs(c["total_typical"] - 850.0) < 1e-6, c["total_typical"])   # months 1..6 total 600..1100; median 850
failed = [x for x in CHECKS if not x[1]]
for label, ok, detail in CHECKS:
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  -> {detail}"))
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
