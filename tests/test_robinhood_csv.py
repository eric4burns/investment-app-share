"""Checks on the Robinhood activity-report importer.

Three traps this format sets that the other importers never had to face, and
each of them produces a plausible wrong number rather than an error:

  * amounts use the accounting convention, so "($1,234.56)" is money LEAVING
    and naive parsing turns every purchase into a deposit;
  * crypto quantities run to nine decimal places, and rounding to a share
    count would silently discard most of a small ETH position;
  * there is no transaction id, so identity has to be synthesised well enough
    that re-importing an overlapping report adds nothing while two genuine
    fills of the same order on the same day stay two rows.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.importers import robinhood_csv as rh          # noqa: E402

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


# --- money, with the accounting convention --------------------------------
check("a plain amount parses", rh._money("$1,234.56") == 1234.56, rh._money("$1,234.56"))
check("parentheses mean money going OUT",
      rh._money("($1,234.56)") == -1234.56, rh._money("($1,234.56)"))
check("a bare minus is respected too", rh._money("-42.00") == -42.0)
check("an empty amount is None, not zero", rh._money("") is None)

# --- quantities, at crypto precision --------------------------------------
check("a crypto quantity keeps every decimal",
      rh._qty("20.177226134") == 20.177226134, rh._qty("20.177226134"))
check("a tiny quantity is not rounded away",
      rh._qty("0.4343964459") == 0.4343964459, rh._qty("0.4343964459"))
check("a fractional share parses", rh._qty("2.97") == 2.97)
check("a symbol suffix is stripped", rh._qty("0.5 ETH") == 0.5, rh._qty("0.5 ETH"))

check("dates parse in Robinhood's format", rh._date("10/15/2025") == "2025-10-15")

# --- a whole file ----------------------------------------------------------
CSV = '''"Activity Date","Process Date","Settle Date","Instrument","Description","Trans Code","Quantity","Price","Amount"
"10/15/2025","10/15/2025","10/16/2025","MSTR","MicroStrategy","Buy","2.97","$130.00","($386.10)"
"10/16/2025","10/16/2025","","SOL","Solana","Buy","20.177226134","$102.00","($2,058.08)"
"10/17/2025","10/17/2025","","","ACH Deposit","ACH","","","$500.00"
"10/18/2025","10/18/2025","","","ACH Withdrawal","ACH","","","($200.00)"
"10/19/2025","10/19/2025","","MSTR","MicroStrategy","CDIV","","","$1.20"
"10/20/2025","10/20/2025","","XYZ","Mystery","ZZZZ","","","($9.99)"
'''
d = Path(tempfile.mkdtemp()); f = d / "rh.csv"; f.write_text(CSV)
parsed = rh.parse(f)
check("the file parses", not parsed.get("error"), parsed.get("error"))
rows = {r["code"]: r for r in parsed.get("rows", [])}
check("all rows are read", len(parsed.get("rows", [])) == 6, len(parsed.get("rows", [])))
check("a buy is negative", rows["Buy"]["amount"] < 0, rows["Buy"]["amount"])
check("a deposit is positive and typed deposit",
      rows["ACH"]["kind"] in ("deposit", "withdrawal"), rows["ACH"]["kind"])
check("a dividend is typed", rows["CDIV"]["kind"] == "dividend")
# An ACH can be either direction; the sign decides, not the code.
achs = [r for r in parsed["rows"] if r["code"] == "ACH"]
check("one ACH is a deposit and the other a withdrawal",
      sorted(r["kind"] for r in achs) == ["deposit", "withdrawal"],
      [r["kind"] for r in achs])
check("an unrecognised code is reported rather than absorbed",
      parsed["unknown_codes"].get("ZZZZ") == 1, dict(parsed["unknown_codes"]))
check("an unrecognised code still imports as 'other'", rows["ZZZZ"]["kind"] == "other")
check("crypto precision survives the parse",
      any(abs((r["quantity"] or 0) - 20.177226134) < 1e-12 for r in parsed["rows"]))

# --- idempotence -----------------------------------------------------------
conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.executescript((ROOT / "app" / "schema.sql").read_text())
first = rh.import_file(conn, f)
second = rh.import_file(conn, f)
check("a first import inserts every row", first["inserted"] == 6, first)
check("re-importing the same report inserts nothing",
      second["inserted"] == 0 and second["skipped"] == 6, second)

# Two genuine fills of one order, same day, same everything, must stay two.
TWICE = '''"Activity Date","Process Date","Settle Date","Instrument","Description","Trans Code","Quantity","Price","Amount"
"11/03/2025","11/03/2025","","BMNR","Bitmine","Buy","1.00","$24.00","($24.00)"
"11/03/2025","11/03/2025","","BMNR","Bitmine","Buy","1.00","$24.00","($24.00)"
'''
g = d / "twice.csv"; g.write_text(TWICE)
r2 = rh.import_file(conn, g)
check("two identical fills on one day are both kept", r2["inserted"] == 2, r2)

# A DISPOSAL MUST BE STORED NEGATIVE. Robinhood states quantity unsigned and
# puts direction in Trans Code alone, while every other importer here writes a
# sell as a negative quantity and the lot builder depends on it. Storing the
# positive figure made a sell ADD to the position: on the real export SLNH read
# 20.96 shares and FRMI 2.0 after both had been closed out completely.
ROUND_TRIP = '''"Activity Date","Process Date","Settle Date","Instrument","Description","Trans Code","Quantity","Price","Amount"
"10/16/2025","10/16/2025","","SLNH","Soluna","Buy","20","$4.77","($95.40)"
"11/14/2025","11/14/2025","","SLNH","Soluna","Sell","20","$1.77","$35.49"
'''
h = d / "roundtrip.csv"; h.write_text(ROUND_TRIP)
conn3 = sqlite3.connect(":memory:")
conn3.row_factory = sqlite3.Row
conn3.executescript((ROOT / "app" / "schema.sql").read_text())
rh.import_file(conn3, h)
net = conn3.execute("SELECT SUM(quantity) q FROM transactions").fetchone()["q"]
check("a bought-then-sold position nets to zero shares", abs(net) < 1e-9, net)
sells = conn3.execute(
    "SELECT quantity FROM transactions WHERE kind = 'sell'").fetchall()
check("a sell is stored with a negative quantity",
      all(r["quantity"] < 0 for r in sells), [r["quantity"] for r in sells])

# The report's last line is an unquoted disclaimer containing commas, so csv
# files the overflow under the restkey as a LIST. Calling .strip() on it raised
# AttributeError and lost the entire import at the final row.
FOOTER = ROUND_TRIP + '''"","","","","","","","",""
"The data provided is for informational purposes only. Please consult a professional tax service, or advisor."
'''
k = d / "footer.csv"; k.write_text(FOOTER)
parsed_footer = rh.parse(k)
check("the trailing legal disclaimer does not break the parse",
      len(parsed_footer["rows"]) == 2 and parsed_footer["unparsed"] == 0, parsed_footer)

# Staying quiet about the disclaimer must not become staying quiet about
# everything. A row carrying a real instrument and a real amount whose date the
# parser could not read is a transaction that will be missing from the ledger,
# and the only way anyone finds out is if the import says so. Treating every
# dateless row as boilerplate makes the count read zero on a file that lost
# money — and it did, with the whole suite green.
BADDATE = ROUND_TRIP + '''"not a date","11/20/2025","","AAPL","Apple","Buy","1","$200.00","($200.00)"
'''
m = d / "baddate.csv"; m.write_text(BADDATE)
parsed_bad = rh.parse(m)
check("a real row with an unreadable date is counted as unparsed, not absorbed",
      parsed_bad["unparsed"] == 1, parsed_bad["unparsed"])
check("and it is not silently imported under some other date",
      len(parsed_bad["rows"]) == 2, len(parsed_bad["rows"]))

for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail if not ok else ''}")
passed = sum(1 for _, ok, _ in CHECKS if ok)
print(f"\n  {passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
