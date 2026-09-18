"""Importers and the watchlist — the paths mutation testing found undefended.

The Frost OFX importer had no tests at all: inverting the sign of every
transaction in the file went undetected. `insert_transaction`'s idempotency —
the entire "re-running an import is safe" promise in HOW_TO_RUN.md and
update.sh — was likewise unchecked. And `watchlist.remove` could be mutated to
delete every row, destroying the one dataset that cannot be rebuilt from data/,
with the whole suite still green.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ledger import connect, get_or_create_account, get_or_create_institution, \
    get_or_create_security, insert_transaction
from app.importers import frost_ofx
from app import watchlist

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def ofx(body):
    f = Path(tempfile.mkdtemp()) / "t.ofx"
    f.write_text(body)
    return f


# --- OFX: direction, and the sign that carries it ---------------------------
_f = ofx("<OFX><ACCTID>111"
         "<STMTTRN><TRNTYPE>XFER<DTPOSTED>20260101<TRNAMT>250.00<FITID>A1<NAME>IN</STMTTRN>"
         "<STMTTRN><TRNTYPE>XFER<DTPOSTED>20260102<TRNAMT>-90.00<FITID>A2<NAME>OUT</STMTTRN>"
         "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260103<TRNAMT>-40.00<FITID>A3<NAME>SHOP</STMTTRN>"
         "<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260104<TRNAMT>75.00<FITID>A4<NAME>PAY</STMTTRN>"
         "</OFX>")
_c = connect(":memory:")
_r = frost_ofx.import_file(_c, _f, "Checking")
_rows = {t["source_id"]: t for t in
         ({"source_id": r[0], "kind": r[1], "amount": r[2]} for r in
          _c.execute("SELECT source_id, kind, amount FROM transactions"))}

check("every transaction is imported", _r["inserted"] == 4, _r)
# The sign IS the direction. Inverting it made every debit a credit and went
# entirely undetected before this file existed.
check("a negative amount stays negative", _rows["A3"]["amount"] == -40.0,
      _rows["A3"]["amount"])
check("a positive amount stays positive", _rows["A4"]["amount"] == 75.0,
      _rows["A4"]["amount"])
check("an incoming XFER is a transfer IN", _rows["A1"]["kind"] == "transfer_in",
      _rows["A1"]["kind"])
check("an outgoing XFER is a transfer OUT", _rows["A2"]["kind"] == "transfer_out",
      _rows["A2"]["kind"])

# --- OFX: failures must be visible, never silent ---------------------------
_bad = ofx("<OFX><ACCTID>111"
           "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260101<TRNAMT>-10.00<FITID>B1<NAME>OK</STMTTRN>"
           "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260102<TRNAMT>bogus<FITID>B2<NAME>BAD</STMTTRN>"
           "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260103<TRNAMT><FITID>B3<NAME>EMPTY</STMTTRN>"
           "</OFX>")
_c_bad = connect(":memory:")
_r2 = frost_ofx.import_file(_c_bad, _bad, "Checking")
check("a malformed amount does not abort the import", _r2["inserted"] >= 1, _r2)
check("a malformed amount is NAMED, not silently skipped",
      any("B2" in m for m in _r2["malformed"]), _r2["malformed"])
# An empty tag short-circuits `float(raw or 0)` before float() can raise, so the
# guard added for malformed amounts could not fire on the likeliest malformation
# of all — and B3 was imported as a real $0.00 debit carrying a genuine date and
# description, leaving the cash balance short by the missing figure with nothing
# saying so.
#
# The assertion that used to stand here could not fail: its fallback branch
# queried a BRAND NEW empty in-memory database, and all() over an empty result
# is vacuously true, so the check passed whatever the importer did. It has to
# read the connection the import actually wrote to.
_bad_rows = {r[0]: r[1] for r in
             _c_bad.execute("SELECT source_id, amount FROM transactions")}
check("an EMPTY amount is reported too, not imported as $0.00",
      any("B3" in m for m in _r2["malformed"]), _r2["malformed"])
check("and the $0.00 row does not reach the ledger",
      "B3" not in _bad_rows, _bad_rows)
check("the good row either side of it still imports",
      _bad_rows.get("B1") == -10.0, _bad_rows)

_multi = ofx("<OFX><ACCTID>111<ACCTID>222"
             "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260101<TRNAMT>-1<FITID>Z</STMTTRN></OFX>")
try:
    frost_ofx.import_file(connect(":memory:"), _multi, "Checking")
    check("an export covering two accounts is refused", False, "it was accepted")
except ValueError as exc:
    check("an export covering two accounts is refused", True, str(exc)[:50])

# --- idempotency: the whole "safe to re-run" promise -------------------------
_c2 = connect(":memory:")
_first = frost_ofx.import_file(_c2, _f, "Checking")
_second = frost_ofx.import_file(_c2, _f, "Checking")
_total = list(_c2.execute("SELECT count(*) FROM transactions"))[0][0]
check("re-importing the same file inserts nothing", _second["inserted"] == 0, _second)
check("and does not duplicate rows", _total == _first["inserted"], _total)

# INSERT OR IGNORE must not become OR REPLACE: replacing would silently rewrite
# a row a later correction depends on, and the row count would not move.
_c3 = connect(":memory:")
_i = get_or_create_institution(_c3, "T")
_a = get_or_create_account(_c3, _i, "A1", "T", "brokerage", "taxable")
_s = get_or_create_security(_c3, "AAA")
_base = {"account_id": _a, "security_id": _s, "txn_date": "2026-01-01",
         "settle_date": None, "kind": "buy", "quantity": 10.0, "price": 5.0,
         "amount": -50.0, "fees": 0.0, "commission": 0.0,
         "description": "first", "source": "t", "source_id": "dup-1", "raw": None}
insert_transaction(_c3, _base)
insert_transaction(_c3, {**_base, "amount": -999.0, "description": "second"})
_got = list(_c3.execute("SELECT count(*), amount, description FROM transactions"))[0]
check("a duplicate source_id is ignored, not replaced",
      _got[0] == 1 and _got[1] == -50.0 and _got[2] == "first", tuple(_got))

# A row the ledger cannot accept must RAISE, not return the same False a
# duplicate returns — the importer counted those as "skipped", the same bucket
# as "already imported", so a bank changing its date format dropped rows while
# the import printed clean.
try:
    insert_transaction(_c3, {**_base, "source_id": "bad-1", "txn_date": None})
    check("a row with no date raises rather than looking like a duplicate", False,
          "it returned quietly")
except ValueError as _exc:
    check("a row with no date raises rather than looking like a duplicate", True,
          str(_exc)[:44])

# And the importer turns that into a NAMED malformed row.
_nodate = ofx("<OFX><ACCTID>111"
              "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260101<TRNAMT>-10.00<FITID>C1<NAME>OK</STMTTRN>"
              "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>notadate<TRNAMT>-20.00<FITID>C2<NAME>BAD</STMTTRN>"
              "</OFX>")
_r3 = frost_ofx.import_file(connect(":memory:"), _nodate, "Checking")
check("an unparseable date is reported, not silently dropped",
      _r3["malformed"] and _r3["inserted"] == 1, _r3)

# --- watchlist.remove must remove exactly one row ---------------------------
_w = connect(":memory:")
watchlist.ensure_schema(_w)
for _sym in ("AAA", "BBB", "CCC"):
    watchlist.add(_w, _sym, tags=["keep"])
watchlist.remove(_w, "BBB")
_left = sorted(r[0] for r in _w.execute("SELECT symbol FROM watchlist"))
check("remove deletes exactly the named row", _left == ["AAA", "CCC"], _left)
check("and takes its tags with it",
      not list(_w.execute("SELECT 1 FROM watchlist_tags WHERE symbol='BBB'")))
check("while leaving other rows' tags alone",
      len(list(_w.execute("SELECT 1 FROM watchlist_tags WHERE symbol='AAA'"))) == 1)

# Markup can never reach the page from a tag or a symbol.
check("a tag cannot contain markup",
      watchlist.clean_tag('<img src=x onerror=alert(1)>') == "img srcx onerroralert1")
check("a symbol cannot contain markup",
      watchlist.clean_symbol('<script>') == "SCRIPT")



# --- 401(k) plan investment options ---------------------------------------
# A plan holds OPTIONS, not listed securities: a collective trust with a daily
# NAV published to the plan and nowhere else. Fidelity leaves Symbol empty and
# puts the option's name in Description, so these rows arrived with no security
# at all and the balance sat at contributions-at-cost forever, never moving with
# the market.
from app.importers import fidelity_csv as _F                # noqa: E402

check("a plan option is recognised",
      _F.plan_fund({"Symbol": "", "Description": "INDEX EQUITY FUND",
                    "Action": "Contributions"}) == "PLAN:INDEX EQUITY FUND")
# BROKERAGELINK's "units" are dollars moving to the self-directed sleeve, which
# is a separate account here — treating it as a holding counts money twice.
check("BROKERAGELINK is not a holding",
      _F.plan_fund({"Symbol": "", "Description": "BROKERAGELINK",
                    "Action": "Contributions"}) is None)
check("a row with a real ticker is untouched",
      _F.plan_fund({"Symbol": "NVDA", "Description": "NVIDIA CORP",
                    "Action": "YOU BOUGHT"}) is None)
# A corporate action also has an empty Symbol, but its reorg marker sits on the
# SECURITY NAME rather than the action — checking the action alone let a reverse
# split through as a 26,149-unit plan holding worth $13,859 that does not exist.
check("a reverse split is not a plan option",
      _F.plan_fund({"Symbol": "", "Action": "Exchange In",
                    "Description": "STRIVE INC CL A COM 1 FOR 20 R/S INTO STRIVE "
                                   "INC COM USD0.001 CL A CUSIP #862945300"}) is None)
check("a valuation restatement is not a purchase",
      _F.plan_fund({"Symbol": "", "Description": "INDEX EQUITY FUND",
                    "Action": "Change in Market Value"}) is None)
check("a blank description is not an option",
      _F.plan_fund({"Symbol": "", "Description": "No Description",
                    "Action": "Contributions"}) is None)

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
