"""Position books: which book a holding is in, and the flag for trading around a core."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import books
from app.ledger import connect

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

conn = connect(":memory:")
r = books.set_book(conn, "iren", "conviction", True, "core held")
check("a book is stored, upper-cased, with the flag and the note",
      r.get("ok") and r["symbol"] == "IREN" and r["trade_around"] and r["note"] == "core held", r)
check("an unknown book is refused", books.set_book(conn, "X", "yolo").get("error"))
check("trading around needs a core: the flag is dropped on a swing name",
      books.set_book(conn, "TEM", "swing", True)["trade_around"] is False)
check("changing the book keeps the note and the flag unless told otherwise",
      books.set_book(conn, "IREN", "conviction")["note"] == "core held"
      and books.set_book(conn, "IREN", "conviction")["trade_around"] is True)
pos = books.attach(conn, [{"symbol": "IREN"}, {"symbol": "TEM"}, {"symbol": "NEW"}])
by = {p["symbol"]: p for p in pos}
check("positions carry their book", by["IREN"]["book"] == "conviction" and by["IREN"]["trade_around"])
check("a name never assigned reads as swing, and says it was defaulted",
      by["NEW"]["book"] == "swing" and by["NEW"]["book_default"] and not by["TEM"]["book_default"])
conn.close()

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
