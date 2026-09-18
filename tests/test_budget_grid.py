"""A budget spreadsheet: categories down the side, months across the top.

This is not transactions and must never be loaded as if it were. What it is good
for is the one thing the bank export cannot do — a hand-kept budget records what
was actually spent, including everything bought on a card, while the app sees
only the payment to the card and nothing beneath it. The gap between the two
measures the blind spot.

The failure this is mostly written against is the year. A column headed "Jan" is
obvious to a person looking at the sheet and completely ambiguous in a file, and
a two-year sheet has two columns called Jan. Filing last January's grocery bill
under this January would corrupt the exact comparison the import exists to make,
so an unresolvable year refuses rather than picks.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.importers import budget_grid as bg

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def write(name, text):
    path = Path(tempfile.mkdtemp()) / name
    path.write_text(text.strip() + "\n")
    return path


# ------------------------------------------------------------ month names ----
check("an ISO month is understood", bg.parse_month("2026-01") == "2026-01")
check("a month name with a year is understood", bg.parse_month("Jan 2026") == "2026-01")
check("a full month name works", bg.parse_month("January 2026") == "2026-01")
check("a two-digit year works", bg.parse_month("Jan '26") == "2026-01")
check("slash order is disambiguated by which number is the year",
      bg.parse_month("01/2026") == "2026-01" and bg.parse_month("2026/01") == "2026-01")
check("a bare month with a supplied year uses it",
      bg.parse_month("Feb", default_year=2025) == "2025-02")
check("a bare month with NO year is refused, not guessed",
      bg.parse_month("Feb") is None)
check("a non-month heading is not a month",
      bg.parse_month("Category") is None and bg.parse_month("Total") is None)

check("a year in the filename supplies the default",
      bg.year_from_name(Path("budget_2025.csv")) == 2025)
check("two different years in the filename supply nothing",
      bg.year_from_name(Path("budget_2024_2026.csv")) is None)

# ---------------------------------------------------------------- parsing ----
grid = write("budget_2025.csv", """
Category,Jan,Feb,Mar
Rent,2364,2364,2364
Groceries,310.50,288,402
Dining,190,240,
Total,2864.50,2892,2766
""")
p = bg.parse(grid)
check("the grid parses", not p.get("error"), p.get("error"))
check("every filled cell becomes a row", len(p["cells"]) == 8, len(p["cells"]))
check("the year comes from the filename",
      p["months"] == ["2025-01", "2025-02", "2025-03"], p["months"])
check("a blank cell is not a zero",
      not any(c["category"] == "Dining" and c["month"] == "2025-03" for c in p["cells"]))
check("decimals survive",
      any(c["category"] == "Groceries" and c["amount"] == 310.50 for c in p["cells"]))

# A Total row is arithmetic on the others. Importing it would double everything.
check("a Total row is not imported as a category",
      "Total" not in p["categories"], p["categories"])
check("and it is reported as ignored rather than dropped silently",
      "Total" in p["skipped_rows"], p["skipped_rows"])

# Real sheets have a title line, a blank row, or notes above the grid.
messy = write("budget_2025.csv", """
My Budget
,,,
Category,Jan 2025,Feb 2025
Rent,2364,2364
""")
p = bg.parse(messy)
check("a title and blank rows above the grid are skipped",
      not p.get("error") and len(p["cells"]) == 2, p.get("error") or len(p["cells"]))

# The refusal that matters.
noyear = write("budget.csv", """
Category,Jan,Feb,Mar
Rent,2364,2364,2364
""")
p = bg.parse(noyear)
check("bare months with no year anywhere refuse the import", "error" in p, p.get("error", "")[:40])
check("and the error says how to fix it",
      "year" in p.get("error", "").lower(), p.get("error", "")[:70])
check("supplying the year explicitly resolves it",
      len(bg.parse(noyear, default_year=2024)["cells"]) == 3)

# Columns carrying their own year beat the filename, so a sheet spanning a year
# boundary lands correctly.
spanning = write("budget_2025.csv", """
Category,Nov 2025,Dec 2025,Jan 2026
Rent,2364,2364,2450
""")
p = bg.parse(spanning)
check("a column's own year wins over the filename's",
      p["months"] == ["2025-11", "2025-12", "2026-01"], p["months"])

# Amounts are magnitudes: a budget sheet writes spending as a positive number,
# and some people write it negative. Both mean the same thing.
signs = write("budget_2025.csv", """
Category,Jan,Feb
Rent,-2364,2364
""")
p = bg.parse(signs)
check("spending written negative and positive both come out as magnitudes",
      all(c["amount"] == 2364 for c in p["cells"]), [c["amount"] for c in p["cells"]])

# --------------------------------------------------------------- storing ----
conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
r = bg.import_file(conn, grid)
check("cells are stored", r["inserted"] == 8, r)
check("stored rows come back", len(bg.reference(conn)) == 8)

# Re-importing a corrected sheet updates rather than duplicating: the numbers
# get edited, and two versions of one month would silently double the reference.
corrected = write("budget_2025.csv", """
Category,Jan,Feb,Mar
Rent,2400,2364,2364
Groceries,310.50,288,402
Dining,190,240,
""")
bg.import_file(conn, corrected)
rows = bg.reference(conn)
check("re-importing does not duplicate", len(rows) == 8, len(rows))
jan_rent = [x for x in rows if x["category"] == "Rent" and x["month"] == "2025-01"][0]
check("and the corrected number replaces the old one", jan_rent["amount"] == 2400,
      jan_rent["amount"])

# Two different sheets are two sources and coexist.
other = write("partner_2025.csv", "Category,Jan\nRent,900\n")
bg.import_file(conn, other)
check("a second sheet is kept separately, not merged",
      len(bg.reference(conn)) == 9 and len(bg.reference(conn, source="partner_2025")) == 1)
conn.close()

# --------------------------------------------------------- comparison ----
# The differences ARE the point. A hand-kept budget records cash spending and
# anything bought on a card whose export is not imported; the ledger records
# everything that moved through an account whether or not it was written down.
# So a gap in either direction says which source knows something the other does
# not, and neither side is "the error".
conn2 = sqlite3.connect(":memory:")
conn2.row_factory = sqlite3.Row
conn2.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())
bg.ensure_schema(conn2)


def txn(month, category, amount):
    return {"txn_date": f"{month}-15", "amount": -abs(amount), "category": category,
            "category_kind": "expense", "description": "X"}


check("with no sheet imported there is nothing to compare",
      bg.compare(conn2, [txn("2026-01", "Rent", 100)])["available"] is False)

bg.import_file(conn2, write("sheet_2026.csv", """
Category,Jan,Feb
Rent,2000,2000
Eating out,300,200
"""))
ledger = [txn("2026-01", "Rent", 2000), txn("2026-02", "Rent", 2100),
          txn("2026-01", "Dining", 250), txn("2026-02", "Dining", 200),
          txn("2026-01", "Pets", 90)]
cmp = bg.compare(conn2, ledger)
check("a sheet makes a comparison available", cmp["available"])
rent = [r for r in cmp["rows"] if r["category"] == "Rent"][0]
check("matching categories are compared", rent["sheet"] == 4000 and rent["app"] == 4100,
      (rent["sheet"], rent["app"]))
check("the difference is the ledger minus the sheet", rent["difference"] == 100,
      rent["difference"])

# "Eating out" and "Dining" are the same thing written by two people.
dining = [r for r in cmp["rows"] if r["category"] == "Eating out"][0]
check("a differently worded category still matches",
      dining["app"] == 450 and dining["matched"], dining)

check("a category only the ledger has is reported separately",
      "pets" in cmp["not_in_sheet"], cmp["not_in_sheet"])

# A month the sheet covers and the ledger does not would report the whole sheet
# as a discrepancy, which says nothing about either.
bg.import_file(conn2, write("future_2027.csv", "Category,Jan\nRent,9999\n"))
cmp = bg.compare(conn2, ledger)
check("months the ledger has no data for are left out",
      "2027-01" not in cmp["months"], cmp["months"])

# A category the sheet has and the app has never heard of is flagged rather than
# silently compared against zero.
bg.import_file(conn2, write("odd_2026.csv", "Category,Jan\nBoat maintenance,500\n"))
cmp = bg.compare(conn2, ledger)
check("a category the app does not have is marked unmatched",
      any("Boat" in c for c in cmp["unmatched_categories"]), cmp["unmatched_categories"])

conn2.close()

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
