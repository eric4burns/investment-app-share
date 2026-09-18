"""Checks on the import-completeness warnings.

Two things have to be true of this module and they pull against each other. It
has to FIRE on a truncated file — that is the whole point, and a silent
truncation is how $45,204 of card spending stayed invisible. And it has to stay
QUIET on every file that is actually fine, because a check that cries wolf on a
routine run teaches you to skim past the line that finally matters.

Both false positives asserted below were real: the line-counting version
accused a good 229-row Amex file of losing 885 rows, and accused all ten
Fidelity exports of losing exactly nine, on every run.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import integrity                              # noqa: E402

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def write(name, text):
    d = Path(tempfile.mkdtemp())
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


# --- counting records, not lines ------------------------------------------
# Amex writes the extended merchant detail as a quoted field containing
# newlines, so one transaction spans several physical lines.
amex = write("amex.csv",
             'Date,Description,Card,Amount,Detail\n'
             '08/27/2026,AMAZON,ERIC,12.87,"BPJATMDDFHB\nAMAZON MARKETPLACE\nSEATTLE"\n'
             '08/26/2026,COSTCO,ERIC,40.00,"WHOLESALE\nROWLETT"\n')
check("a quoted field with newlines is one record, not five",
      integrity.count_records(amex) == 2, integrity.count_records(amex))

# Every Fidelity export ends with nine single-sentence legal lines.
fid = write("fidelity.csv",
            'Run Date,Action,Symbol,Amount\n'
            '08/27/2026,YOU BOUGHT,NVDA,-100.00\n'
            '08/26/2026,DIVIDEND,MSFT,3.10\n'
            '\n'
            '"The data and information in this spreadsheet is provided to you solely for your use."\n'
            '"Brokerage services are provided by Fidelity Brokerage Services LLC (FBS)."\n'
            'Date downloaded 08/29/2026 08:26 am\n')
check("single-column legal boilerplate is not a record",
      integrity.count_records(fid) == 2, integrity.count_records(fid))

ofx = write("bank.ofx", "<STMTTRN>a</STMTTRN>\n<STMTTRN>b</STMTTRN>\n<STMTTRN>c</STMTTRN>")
check("OFX records are counted by STMTTRN", integrity.count_records(ofx) == 3,
      integrity.count_records(ofx))
check("an unknown format declines to guess",
      integrity.count_records(write("x.pdf", "whatever")) is None)

# --- staying quiet on a good import ---------------------------------------
check("a complete Amex import warns about nothing",
      integrity.file_warnings({"seen": 2, "unparsed": 0}, amex) == [],
      integrity.file_warnings({"seen": 2, "unparsed": 0}, amex))
check("a complete Fidelity import warns about nothing",
      integrity.file_warnings({"seen": 2, "unparsed": 0}, fid) == [],
      integrity.file_warnings({"seen": 2, "unparsed": 0}, fid))
# A budget grid counts CELLS and a pay stub counts FIELDS, so neither can be
# compared against a record count. Both warned, confidently and wrongly.
#
# The comparison only ever fires when the file holds MORE records than the
# importer reported, so the case has to be built that way round: a sparse
# spreadsheet is thirty category rows with ten filled cells in them, and
# comparing 10 against 30 is what produced the confident wrong warning. Asserting
# it against a file with fewer records than cells proves nothing, because the
# check is already silent in that direction for every importer.
sparse = write("budget_2025.csv",
               "Category,Jan\n"
               + "".join(f"Category {i},{i * 10}\n" for i in range(1, 31)))
check("a reference importer is not compared against a record count",
      integrity.file_warnings({"seen": 10, "unparsed": 0}, sparse,
                              rows_are_transactions=False) == [],
      integrity.file_warnings({"seen": 10, "unparsed": 0}, sparse,
                              rows_are_transactions=False))
check("while the same shortfall on a TRANSACTION importer does warn",
      integrity.file_warnings({"seen": 10, "unparsed": 0}, sparse) != [],
      integrity.file_warnings({"seen": 10, "unparsed": 0}, sparse))

# --- firing when it should ------------------------------------------------
# The case this exists for: the file plainly holds more than the importer
# understood.
big = write("truncated.csv", "Date,Description,Amount\n"
            + "".join(f"08/{i:02d}/2026,MERCHANT {i},10.00\n" for i in range(1, 29)))
warnings = integrity.file_warnings({"seen": 4, "unparsed": 0}, big)
check("a file with far more records than were understood warns",
      any("unaccounted" in w for w in warnings), warnings)
# A couple of unread lines is the ordinary footer; a tenth of the file is not.
check("a two-row difference stays below the noise floor",
      integrity.file_warnings({"seen": 26, "unparsed": 0}, big) == [],
      integrity.file_warnings({"seen": 26, "unparsed": 0}, big))

# The noise floor is a PROPORTION as well as an absolute count, and on a large
# file the proportion is the half that does the work. Ten unread lines out of
# four hundred is a footer; forty is a truncated export. Only the absolute floor
# of three was pinned before, so the 5% could be widened to anything at all
# without a single test noticing.
wide = write("wide.csv", "Date,Description,Amount\n"
             + "".join(f"08/{i % 28 + 1:02d}/2026,MERCHANT {i},10.00\n" for i in range(400)))
check("ten unread lines in a four-hundred-row file is still the footer",
      integrity.file_warnings({"seen": 390, "unparsed": 0}, wide) == [],
      integrity.file_warnings({"seen": 390, "unparsed": 0}, wide))
check("forty of them is a shortfall worth naming",
      any("unaccounted" in w
          for w in integrity.file_warnings({"seen": 360, "unparsed": 0}, wide)),
      integrity.file_warnings({"seen": 360, "unparsed": 0}, wide))

check("rows the parser rejected are reported",
      any("could not be read" in w
          for w in integrity.file_warnings({"seen": 400, "unparsed": 7})),
      integrity.file_warnings({"seen": 400, "unparsed": 7}))

# Landing exactly on a provider's cap. Real activity does not stop on a round
# thousand by chance.
capped = integrity.file_warnings({"seen": 1000, "unparsed": 0})
check("hitting Chase's 1,000-row export cap exactly is called out",
      any("truncated" in w for w in capped), capped)
check("a nearby but non-cap count is not called out",
      integrity.file_warnings({"seen": 999, "unparsed": 0}) == [])

# --- holes in the ledger --------------------------------------------------
conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.executescript("""
CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT, kind TEXT);
CREATE TABLE transactions (id INTEGER PRIMARY KEY, account_id INT, txn_date TEXT);
INSERT INTO accounts VALUES (1,'Checking','checking'), (2,'Roth','retirement');
""")
# March is missing entirely -- the signature of an export never taken.
for day in ("2026-01-05", "2026-02-05", "2026-04-05", "2026-05-05"):
    conn.execute("INSERT INTO transactions (account_id, txn_date) VALUES (1,?)", (day,))
# The retirement account is quiet for months, which is entirely normal.
for day in ("2026-01-05", "2026-05-05"):
    conn.execute("INSERT INTO transactions (account_id, txn_date) VALUES (2,?)", (day,))
conn.commit()

gaps = integrity.coverage_gaps(conn)
check("a missing month in a checking account is found",
      len(gaps) == 1 and gaps[0]["missing"] == ["2026-03"], gaps)
check("a quiet retirement account is not treated as a hole",
      all(g["account"] != "Roth" for g in gaps), gaps)
# Silence before the account opened and after the last import is not a gap.
check("only months inside the account's own range count",
      gaps and "2025-12" not in gaps[0]["missing"] and "2026-06" not in gaps[0]["missing"])

check("months are enumerated across a year boundary",
      integrity._months("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"],
      integrity._months("2025-11", "2026-02"))

# --- who the server answers to -------------------------------------------
# Opening the server to a phone is the point of the configurable bind, but the
# Host guard is what stops DNS rebinding, which loopback binding does nothing
# about. Getting this wrong in either direction is bad: too strict and the
# phone 403s, too loose and any web page you visit can read the whole ledger.
#
# The bug: local_hostnames() tried to admit Tailscale with
#   names |= {n for n in names if n.endswith(".ts.net")}
# which unions a set with a subset of itself and does nothing whatsoever.
from app import web                                     # noqa: E402

HOSTS = [
    ("",                         True,  "no Host header at all (curl, a script)"),
    ("localhost",                True,  "loopback by name"),
    ("127.0.0.1",                True,  "loopback by address"),
    ("macbook.tail1a2b3.ts.net", True,  "Tailscale MagicDNS name"),
    ("100.101.102.103",          True,  "Tailscale CGNAT address"),
    ("100.63.255.255",           False, "one below the CGNAT range"),
    ("100.128.0.1",              False, "one above the CGNAT range"),
    ("8.8.8.8",                  False, "a public address"),
    ("evil.com",                 False, "a rebinding attacker's own domain"),
    ("notreally-ts.net",         False, "a lookalike domain"),
    ("evil.ts.net.attacker.com", False, "ts.net buried mid-domain"),
]
wrong = [(h, why) for h, want, why in HOSTS if web.host_allowed(h) != want]
check("the Host guard admits loopback and the tailnet, and nothing else",
      not wrong, wrong)

# ---- which chart a holding's levels are read off -------------------------
# "The day week month thing doesn't really click. The values depend on the
# length of the trade." The levels used to come from whichever timeframe the
# engine reached its headline call on, which is a property of the engine, not
# of the trade. They now follow the book's holding period.
_lv = {"buy_at": 1.0, "trim_at": 2.0, "stop_at": 0.5}
_v = {"daily": {"watch": {**_lv, "tag": "D"}},
      "weekly": {"watch": {**_lv, "tag": "W"}},
      "monthly": {"watch": {**_lv, "tag": "M"}},
      "headline_timeframe": "M"}
check("a swing position is read off the daily even when the headline is monthly",
      web._pick_watch(_v, "swing")["tag"] == "D", web._pick_watch(_v, "swing"))
check("a conviction position is read off the weekly, not the daily",
      web._pick_watch(_v, "conviction")["tag"] == "W", web._pick_watch(_v, "conviction"))
check("an unknown or missing book is treated as a swing",
      web._pick_watch(_v, None)["tag"] == "D" and web._pick_watch(_v, "nonsense")["tag"] == "D")
_empty = {"daily": {"watch": {}}, "weekly": {"watch": {**_lv, "tag": "W"}},
          "monthly": {"watch": {}}, "headline_timeframe": "D"}
check("a timeframe with no level worth acting on falls through to the next",
      web._pick_watch(_empty, "swing")["tag"] == "W", web._pick_watch(_empty, "swing"))
_none = {"daily": {"watch": {}}, "weekly": {"watch": {}}, "monthly": {"watch": {}},
         "headline_timeframe": "D"}
check("with nothing anywhere it returns nothing, not another timeframe's levels",
      web._pick_watch(_none, "conviction") is None)

# ---- windows end at the last DATA, not the last trade ---------------------
# The Diagnose tab reported a -41.2% drawdown as of the user's last trade while
# the real figure that morning was -38.8%, because five endpoints defaulted
# their window to MAX(txn_date). Prices arrive nightly; transactions arrive
# when an export is downloaded by hand. `_build` had already learned this and
# left a comment about it; the fix had never reached the other five.
# A bare sqlite3 connection, not ledger.connect: the real schema is beside the
# point here and applying it would make the fixture about the schema.
import sqlite3 as _sq  # noqa: E402
_dc = _sq.connect(":memory:")
_dc.execute("CREATE TABLE transactions (txn_date TEXT)")
_dc.execute("CREATE TABLE prices (bar_date TEXT)")
_dc.execute("INSERT INTO transactions VALUES ('2026-09-03')")
_dc.execute("INSERT INTO prices VALUES ('2026-09-10')")
check("the window ends at the newest PRICE when that is later than the last trade",
      web.data_end(_dc) == "2026-09-10", web.data_end(_dc))
_dc.execute("INSERT INTO transactions VALUES ('2026-09-12')")
check("...and at the newest TRANSACTION when that is later",
      web.data_end(_dc) == "2026-09-12", web.data_end(_dc))
_empty = _sq.connect(":memory:")
_empty.execute("CREATE TABLE transactions (txn_date TEXT)")
_empty.execute("CREATE TABLE prices (bar_date TEXT)")
check("an empty ledger falls back to today rather than None — this is the "
      "first screen a new user sees",
      len(web.data_end(_empty)) == 10, web.data_end(_empty))
_dc.close(); _empty.close()

check("no endpoint still pins its window to the last transaction",
      "SELECT MAX(txn_date) d FROM transactions" not in
      (Path(__file__).resolve().parent.parent / "app" / "web.py").read_text(),
      "use web.data_end(conn)")

for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail if not ok else ''}")
passed = sum(1 for _, ok, _ in CHECKS if ok)
print(f"\n  {passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
