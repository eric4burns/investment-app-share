"""Credit-card CSV imports.

Every issuer exports a different CSV, and the difference that can actually hurt
you is the sign. Chase writes purchases negative; Amex and Discover write them
positive; Capital One and Citi use separate Debit and Credit columns and no
signs at all. Read an Amex file with Chase's assumption and a year of spending
imports as a year of income — and nothing in the file looks wrong, because the
dates, amounts and descriptions are all perfectly valid either way. Only the
total is backwards.

So most of what follows is about proving the sign rather than assuming it, and
about the importer saying which evidence it used.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.importers import card_csv

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def write(name, text):
    path = Path(tempfile.mkdtemp()) / name
    path.write_text(text.strip() + "\n")
    return path


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())
    return conn


# Real header shapes from each issuer.
CHASE = """
Transaction Date,Post Date,Description,Category,Type,Amount,Memo
08/14/2026,08/15/2026,STARBUCKS STORE 1234,Food & Drink,Sale,-6.85,
08/12/2026,08/13/2026,AMAZON.COM*A12BC,Shopping,Sale,-42.19,
08/01/2026,08/01/2026,Payment Thank You - Web,,Payment,1200.00,
"""
AMEX = """
Date,Description,Card Member,Account #,Amount
08/14/2026,STARBUCKS,ERIC BURNS,-12345,6.85
08/12/2026,UBER TRIP,ERIC BURNS,-12345,23.40
08/02/2026,ONLINE PAYMENT - THANK YOU,ERIC BURNS,-12345,-800.00
"""
CAPITAL_ONE = """
Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
2026-08-14,2026-08-15,1234,WHOLEFDS MKT,Grocery,88.12,
2026-08-10,2026-08-11,1234,SPOTIFY,Entertainment,18.99,
2026-08-01,2026-08-01,1234,CAPITAL ONE MOBILE PYMT,Payment/Credit,,450.00
"""
DISCOVER = """
Trans. Date,Post Date,Description,Amount,Category
08/14/2026,08/15/2026,TARGET 00012,55.20,Merchandise
08/11/2026,08/12/2026,SHELL OIL,41.00,Gasoline
08/03/2026,08/03/2026,DIRECTPAY FULL BALANCE,-310.00,Payments and Credits
"""

# The heart of it: whatever the issuer's convention, a purchase must come out
# negative and a payment positive, because that is the convention every other
# number in this ledger is expressed in.
for name, text, expect_sign in [
    ("chase.csv", CHASE, "positive"),
    ("amex.csv", AMEX, "negative"),
    ("capital_one.csv", CAPITAL_ONE, "debit and credit"),
    ("discover.csv", DISCOVER, "negative"),
]:
    parsed = card_csv.parse(write(name, text))
    label = name.split(".")[0]
    if parsed.get("error"):
        check(f"{label}: parses", False, parsed["error"])
        continue
    purchases = [r for r in parsed["rows"] if r["amount"] < 0]
    payments = [r for r in parsed["rows"] if r["amount"] > 0]
    check(f"{label}: purchases come out negative", len(purchases) == 2,
          f"{len(purchases)} of 2")
    check(f"{label}: the payment comes out positive", len(payments) == 1,
          f"{len(payments)} of 1")
    check(f"{label}: the sign is decided from evidence, not assumed",
          expect_sign in parsed["sign"]["basis"], parsed["sign"]["basis"])

# Amex is the case that inverts. Stated separately because it is the one a
# Chase-shaped assumption gets exactly backwards.
amex = card_csv.parse(write("amex2.csv", AMEX))
starbucks = [r for r in amex["rows"] if "STARBUCKS" in r["description"]][0]
check("a positive Amex charge becomes a negative amount",
      starbucks["amount"] == -6.85, starbucks["amount"])

# Capital One and Citi carry no sign at all: the direction is which COLUMN the
# number sits in. Counting how many rows come out on each side cannot tell a
# correct reading from one that swapped the two columns and happens to produce
# the same split, so the amounts themselves are checked.
cap1 = card_csv.parse(write("capone2.csv", CAPITAL_ONE))
amounts = {r["description"]: r["amount"] for r in cap1["rows"]}
check("a Debit-column figure becomes a negative amount",
      amounts.get("WHOLEFDS MKT") == -88.12, amounts.get("WHOLEFDS MKT"))
check("a Credit-column figure becomes a positive amount",
      amounts.get("CAPITAL ONE MOBILE PYMT") == 450.00,
      amounts.get("CAPITAL ONE MOBILE PYMT"))
# And Chase, the one convention everything else is expressed in, keeps its
# magnitudes rather than merely its signs.
chase = card_csv.parse(write("chase2.csv", CHASE))
chase_amounts = {r["description"]: r["amount"] for r in chase["rows"]}
check("a Chase purchase keeps its size as well as its sign",
      chase_amounts.get("STARBUCKS STORE 1234") == -6.85,
      chase_amounts.get("STARBUCKS STORE 1234"))
check("and the payment keeps its size too",
      chase_amounts.get("Payment Thank You - Web") == 1200.00,
      chase_amounts.get("Payment Thank You - Web"))

# --------------------------------------------------------------- sniffing ----
check("the transaction date beats the posting date",
      card_csv.sniff(["Transaction Date", "Post Date", "Description", "Amount"])["date"]
      == "Transaction Date")
check("split debit/credit columns are recognised",
      card_csv.sniff(["Date", "Description", "Debit", "Credit"])["split"])
check("a single amount column is not treated as split",
      not card_csv.sniff(["Date", "Description", "Amount"])["split"])

missing = card_csv.parse(write("bad.csv", "Foo,Bar,Baz\n1,2,3"))
check("a file with no recognisable columns is an error, not an empty import",
      "error" in missing and not missing["rows"], missing.get("error", "")[:40])

# ------------------------------------------------------------- numbers ----
check("accounting negatives are understood", card_csv._number("(12.34)") == -12.34)
check("currency symbols and separators are stripped",
      card_csv._number("$1,234.56") == 1234.56)
check("a blank amount is not zero", card_csv._number("") is None)
check("dates in several formats are read",
      card_csv._date("08/14/2026") == "2026-08-14"
      and card_csv._date("2026-08-14") == "2026-08-14")
check("an unreadable date is refused, not guessed", card_csv._date("last tuesday") is None)

# ------------------------------------------------------- sign refusal ----
# When the evidence contradicts itself the import stops. Importing half a year
# backwards is worse than importing nothing.
conflict = card_csv.parse(write("conflict.csv", """
Date,Description,Amount
08/01/2026,ONLINE PAYMENT THANK YOU,500.00
08/02/2026,AUTOPAY PAYMENT,-500.00
08/03/2026,STARBUCKS,-6.85
"""))
check("contradictory payment rows stop the import",
      "error" in conflict and "sign" in conflict["error"], conflict.get("error", "")[:60])
check("and no rows come back to be inserted", conflict["rows"] == [], conflict["rows"])

# The refusal has to survive the trip through import_file, because that is the
# path a person actually runs. A parse that refuses and an importer that writes
# the rows anyway is the same wrong year of spending, arrived at more politely.
_conflict_path = write("conflict2.csv", """
Date,Description,Amount
08/01/2026,ONLINE PAYMENT THANK YOU,500.00
08/02/2026,AUTOPAY PAYMENT,-500.00
08/03/2026,STARBUCKS,-6.85
""")
_cdb = db()
_res = card_csv.import_file(_cdb, _conflict_path)
check("importing a file with no provable sign inserts nothing",
      _res["inserted"] == 0 and "error" in _res, _res)
check("and leaves the ledger untouched rather than half-written",
      _cdb.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0)
_cdb.close()

# With no payment row at all it falls back to the majority, and says so.
nopay = card_csv.parse(write("nopay.csv", """
Date,Description,Amount
08/01/2026,STARBUCKS,6.85
08/02/2026,TARGET,55.20
08/03/2026,SHELL,41.00
"""))
check("with no payment row it still imports", not nopay.get("error"))
check("but reports that the sign was assumed",
      "assumed" in nopay["sign"]["basis"], nopay["sign"]["basis"])

# ---------------------------------------------------------- account name ----
check("the account name comes from the filename",
      card_csv.account_name_from(Path("chase_sapphire_2026.csv")) == "Chase Sapphire",
      card_csv.account_name_from(Path("chase_sapphire_2026.csv")))
check("boilerplate in the filename is dropped",
      card_csv.account_name_from(Path("amex_transactions_2026-08-14.csv")) == "Amex",
      card_csv.account_name_from(Path("amex_transactions_2026-08-14.csv")))

# ------------------------------------------------------------- importing ----
conn = db()
path = write("chase.csv", CHASE)
first = card_csv.import_file(conn, path)
check("rows are actually inserted", first["inserted"] == 3, first)
check("nothing is silently dropped", first["skipped"] == 0, first)
check("the account is created as a credit account",
      conn.execute("SELECT kind FROM accounts WHERE name='Chase'").fetchone()["kind"] == "credit")

second = card_csv.import_file(conn, path)
check("re-importing the same file adds nothing", second["inserted"] == 0, second)
check("and reports them as already present", second["skipped"] == 3, second)
check("the ledger still holds exactly three rows",
      conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 3)

# Two identical purchases on the same day at the same merchant is an ordinary
# thing, not an edge case, and both have to survive.
twice = write("dupes.csv", """
Transaction Date,Description,Amount
08/14/2026,STARBUCKS STORE 1234,-6.85
08/14/2026,STARBUCKS STORE 1234,-6.85
08/01/2026,Payment Thank You,500.00
""")
conn2 = db()
r = card_csv.import_file(conn2, twice)
check("two identical purchases on one day both import", r["inserted"] == 3, r)
conn2.close()
conn.close()

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
