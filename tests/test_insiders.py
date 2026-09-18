"""Insider filings and the relative-strength rank.

The Form 4 parser is tested against a filing-shaped fixture rather than the
network, and the summary is tested for the one rule that matters: only
open-market purchases and sales are money, awards and exercises are not.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import insiders, watchlist
from app.ledger import connect

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Lewis Anthony J</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector><isOfficer>1</isOfficer>
      <officerTitle>Chief Financial Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-07-01</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>26968</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>221483</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-07-02</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>12.5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>222483</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

parsed = insiders.parse_form4(FORM4)
check("the reporting person and title are read", parsed["owner"] == "Lewis Anthony J"
      and parsed["title"] == "Chief Financial Officer", parsed)
check("every non-derivative transaction is read, in order",
      [t["code"] for t in parsed["transactions"]] == ["A", "P"], parsed["transactions"])
check("shares, price and post-transaction holding are numbers",
      parsed["transactions"][1]["shares"] == 1000.0 and parsed["transactions"][1]["price"] == 12.5
      and parsed["transactions"][1]["post"] == 222483.0, parsed["transactions"][1])
check("a director with no title is labelled as one",
      insiders.parse_form4(FORM4.replace("<isDirector>0</isDirector>", "<isDirector>1</isDirector>")
                           .replace("<officerTitle>Chief Financial Officer</officerTitle>", ""))["title"]
      == "Director")
check("the rendered path EDGAR lists resolves to the raw XML",
      insiders._raw_doc("xslF345X06/ownership.xml") == "ownership.xml")

# ---- summary: only open-market money counts ----
conn = connect(":memory:")
insiders.ensure_schema(conn)
from datetime import date, timedelta
recent = (date.today() - timedelta(days=10)).isoformat()
old = (date.today() - timedelta(days=200)).isoformat()
rows = [
    ("X", "a1", 0, recent, recent, "Buyer One", "CEO", "P", "A", 1000, 10.0, 5000),
    ("X", "a2", 0, recent, recent, "Seller Two", "CFO", "S", "D", 200, 12.0, 4800),
    ("X", "a3", 0, recent, recent, "Granted Three", "Director", "A", "A", 5000, 0.0, 9000),
    ("X", "a4", 0, recent, recent, "Exerciser", None, "M", "A", 3000, 1.0, 9000),
    ("X", "a5", 0, old, old, "Buyer One", "CEO", "P", "A", 9999, 10.0, 5000),   # outside the window
    ("Y", "b1", 0, recent, recent, "Someone", None, "S", "D", 100, 50.0, 100),
]
conn.executemany("""INSERT INTO insider_trades (symbol, accession, seq, filed, txn_date, owner,
    title, code, acquired, shares, price, post) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
s = insiders.summary(conn, ["X", "Y", "Z"], days=90)
check("purchases and sales are summed in dollars; awards and exercises are not",
      s["X"]["bought_usd"] == 10000.0 and s["X"]["sold_usd"] == 2400.0 and s["X"]["net_usd"] == 7600.0, s.get("X"))
check("a transaction outside the window is not counted", s["X"]["buys"] == 1, s.get("X"))
check("buyers and sellers are named with their role",
      s["X"]["buyers"] == ["Buyer One (CEO)"] and s["X"]["sellers"] == ["Seller Two (CFO)"], s.get("X"))
check("a name with no filings is simply absent", "Z" not in s and "Y" in s, sorted(s))
conn.close()

# ---- relative-strength rank ----
names = [{"symbol": "A", "chg_1m": 0.10, "chg_3m": 0.50, "chg_6m": 0.60, "chg_12m": 1.00},
         {"symbol": "B", "chg_1m": 0.00, "chg_3m": 0.00, "chg_6m": 0.05, "chg_12m": 0.10},
         {"symbol": "C", "chg_1m": -0.10, "chg_3m": -0.30, "chg_6m": -0.20, "chg_12m": -0.50},
         {"symbol": "D", "chg_1m": None, "chg_3m": None, "chg_6m": None, "chg_12m": 0.90}]
watchlist.rank_relative_strength(names)
by = {r["symbol"]: r for r in names}
check("the strongest name ranks highest and the weakest lowest",
      by["A"]["rs_rank"] > by["B"]["rs_rank"] > by["C"]["rs_rank"], {k: v["rs_rank"] for k, v in by.items()})
check("ranks stay inside 1 to 99", all(1 <= r["rs_rank"] <= 99 for r in names if r["rs_rank"] is not None))
check("a name with too few windows is unranked rather than ranked on one number",
      by["D"]["rs_rank"] is None and by["D"]["rs_score"] is None, by["D"])
check("the most recent quarter carries double weight",
      abs(by["A"]["rs_score"] - (0.4 * 0.5 + 0.2 * 0.6 + 0.2 * 1.0 + 0.2 * 0.1)) < 1e-9, by["A"]["rs_score"])


# ---- momentum as of a past date ----
_ser = {f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}": 100.0 + i for i in range(300)}
_dts = sorted(_ser)
_m = watchlist.momentum_at(_ser, _dts, _dts[-1])
check("momentum windows are measured from the last bar on or before the date",
      abs(_m["chg_1m"] - ((100 + 299) / (100 + 278) - 1)) < 1e-9, _m)
check("an earlier as-of date reads the series as it stood then",
      abs(watchlist.momentum_at(_ser, _dts, _dts[100])["chg_1m"] - ((200.0) / (179.0) - 1)) < 1e-9)
check("too little history gives no windows", watchlist.momentum_at(_ser, _dts, _dts[5]) == {})

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
