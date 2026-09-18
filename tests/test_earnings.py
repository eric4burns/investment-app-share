"""The earnings calendar: parsing what the source returns, and "days to go"."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import earnings
from app.ledger import connect

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

check("a bracketed estimate is negative", earnings._money("($0.04)") == -0.04)
check("a plain estimate is positive", earnings._money("$1.46") == 1.46)
check("an empty estimate is None", earnings._money("") is None and earnings._money(None) is None)

conn = connect(":memory:")
earnings.ensure_schema(conn)
today = date.today()
rows = [("IREN", (today + timedelta(days=3)).isoformat(), "after-hours", 0.12),
        ("IREN", (today + timedelta(days=95)).isoformat(), "unknown", None),   # the one after next
        ("DGXX", (today - timedelta(days=2)).isoformat(), "pre-market", -0.05), # already reported
        ("AMD",  (today + timedelta(days=40)).isoformat(), "after-hours", 1.10)]
conn.executemany("""INSERT INTO earnings_dates (symbol, report_date, timing, eps_estimate, source, fetched_at)
                    VALUES (?,?,?,?,'test','now')""", rows)
up = earnings.upcoming(conn, ["IREN", "DGXX", "AMD", "NOPE"])
check("the NEXT report is returned, not the one after it",
      up["IREN"]["date"] == rows[0][1] and up["IREN"]["days"] == 3, up.get("IREN"))
check("a report already past is not upcoming", "DGXX" not in up, sorted(up))
check("timing and the consensus travel with the date",
      up["AMD"]["timing"] == "after-hours" and up["AMD"]["eps_estimate"] == 1.10, up.get("AMD"))
check("a name with nothing on the calendar is absent rather than guessed", "NOPE" not in up)
check("as-of moves the clock: from a week ago the past report was still ahead",
      earnings.upcoming(conn, ["DGXX"], (today - timedelta(days=7)).isoformat())["DGXX"]["days"] == 5)

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
