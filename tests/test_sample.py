"""The sample year a fresh copy can load before any export exists.

What must hold: the three files are the real export formats and go through
the real importers; the same files come out every time, so a second load is
a re-import and nothing doubles; loading refuses a ledger with anything in
it; clearing refuses a ledger not marked as sample, and leaves the tables
the importers never touched alone; every account is named Sample.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import sample  # noqa: E402

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())
    return conn


check("the files are the same every time", sample.fidelity_csv() == sample.fidelity_csv() and sample.card_csv() == sample.card_csv())
check("the Fidelity file carries the real header and the legal footer",
      sample.fidelity_csv().startswith("Run Date,Account,Account Number,Action,Symbol") and "Not a statement from any broker" in sample.fidelity_csv())
check("the bank file is one OFX account", sample.bank_ofx().count("<ACCTID>") == 1 and "<STMTTRN>" in sample.bank_ofx())
check("the card file has purchases negative and payments positive",
      ",Sale,-" in sample.card_csv() and ",Payment," in sample.card_csv())

conn = db()
r = sample.load(conn)
check("it loads into an empty ledger through the importers", not r.get("error") and r["transactions"] > 300, r)
names = [x[0] for x in conn.execute("SELECT name FROM accounts")]
check("every account is called Sample", names and all(n.startswith("Sample") for n in names), names)
kinds = {x[0] for x in conn.execute("SELECT DISTINCT kind FROM transactions")}
check("buys, sells, dividends, pay and spending are all in it", {"buy", "sell", "dividend", "credit", "debit"} <= kinds, kinds)
check("it is marked as sample", sample.loaded(conn))
check("a second load is refused", "error" in sample.load(conn))
last = conn.execute("SELECT MAX(txn_date) FROM transactions").fetchone()[0]
from datetime import date  # noqa: E402
check("nothing is dated after today", last <= date.today().isoformat(), last)

from app import watchlist as _wl  # noqa: E402
_wl.ensure_schema(conn)
conn.execute("INSERT INTO watchlist (symbol) VALUES ('IREN')")
r = sample.clear(conn)
check("clearing removes the imported rows", conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
      and conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0, r)
check("and leaves the watchlist alone", conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 1)
check("and drops the mark", not sample.loaded(conn))
check("clearing an unmarked ledger is refused", "error" in sample.clear(conn))

# A ledger with real rows never takes the sample.
conn = db()
conn.execute("INSERT INTO institutions (id, name) VALUES (1, 'Real')")
conn.execute("INSERT INTO accounts (id, institution_id, external_id, name, kind) VALUES (1, 1, 'x', 'Mine', 'checking')")
conn.execute("INSERT INTO transactions (account_id, txn_date, kind, amount, source, source_id) VALUES (1, '2026-01-01', 'debit', -1, 't', '1')")
check("a ledger with real rows refuses the sample", "error" in sample.load(conn))

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
