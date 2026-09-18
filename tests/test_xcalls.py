"""The followed accounts' calls, read from the nightly X pull.

What must hold: a post that only mentions a name is not a call; a post that
says both things is skipped rather than guessed; the words that decided it
travel with the row; a percentage is never mistaken for a level; the same
tweet is never recorded twice; and a call a person recorded for the same
author, name and day is never overwritten by the automatic one — that is the
reviewed record, and this is the floor under it.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import journal as J, xcalls  # noqa: E402

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())
    J.ensure_schema(conn)
    sid = conn.execute("INSERT INTO securities (symbol, kind) VALUES ('IREN', 'equity')").lastrowid
    for d, c in {"2026-09-03": 40.0, "2026-09-04": 41.5}.items():
        conn.execute("""INSERT INTO prices (security_id, bar_date, close, open, high, low, volume, source)
                        VALUES (?,?,?,?,?,?,0,'test')""", (sid, d, c, c, c, c))
    conn.commit()
    return conn


# ------------------------------------------------------------ reading ----
r = xcalls.read("Nice week for $SYM")
check("a bare mention is not a call", r is None, r)
r = xcalls.read("$IREN Higher Low inside the wave reversal zone. Outside the downtrend.")
check("'higher low' reads as a buy", r and r["action"] == "buy", r)
check("the deciding words travel with it", r and "higher low" in r["words"], r)
r = xcalls.read("Sold my $IREN this morning, will look to buy back lower")
check("sold AND buy back is ambiguous, so skipped", r is None, r)
r = xcalls.read("4/5 $AVAV - Institutional ownership at 86.4%. Currently in a bottoming pattern, long here.")
check("a percentage after 'at' is not a level", r and r["level"] is None, r)
r = xcalls.read("$IREN buy zone at $38.50 if we get there, adding")
check("a price after a level word is the level", r and r["level"] == 38.5, r)
r = xcalls.read("$AAA $BBB $CCC all breaking out")
check("three tickers is a list, not a call", r is None, r)
r = xcalls.read("Going to be buying $CIFU next week and possibly $KEEX")
check("two tickers with one claim is a call on both", r and r["symbols"] == ["CIFU", "KEEX"], r)
r = xcalls.read("$BTC breaking out")
check("crypto cashtags are not tickers", r is None, r)
r = xcalls.read("We are adding Model Book Presets to the app for members. " + "x" * 120 + " This $NVDA base is textbook.")
check("a claim far from the name is not a claim about it", r is None, r)

# ------------------------------------------------------------- seeding ----
conn = db()
pull = {"tweets": {"StonkChris": [
    {"id": "1", "date": "Fri Sep 04 20:27:53 +0000 2026", "text": "$IREN put in a higher low. Adding."},
    {"id": "2", "date": "2026-09-04T21:00:00+00:00", "text": "Nice week for $IREN"},
]}}
r = xcalls.seed(conn, pull)
check("one call recorded from two posts", r["recorded"] == 1 and r["calls"] == 1, r)
row = conn.execute("SELECT * FROM decisions WHERE source='outside'").fetchone()
check("filed under the journal's name for the handle", row["author"] == "StonkChris (@StonkChris)", row["author"])
check("priced at that day's close", row["price"] == 41.5, row["price"])
check("marked as automatic", row["confidence"] == "auto", row["confidence"])
check("the words are in the rationale", row["rationale"].startswith("[auto: adding, higher low]"), row["rationale"])
r = xcalls.seed(conn, pull)
check("running again records nothing new", r["recorded"] == 0, r)
check("still one decision", conn.execute("SELECT COUNT(*) FROM decisions WHERE source='outside'").fetchone()[0] == 1)

# A person's call for the same author/name/day wins over the automatic one.
conn = db()
J.record(conn, "2026-09-04", "IREN", "outside", "sell", price=41.5, rationale="reviewed by hand",
         author="StonkChris (@StonkChris)")
xcalls.seed(conn, pull)
row = conn.execute("SELECT * FROM decisions WHERE source='outside'").fetchone()
check("a hand-recorded call is not overwritten", row["action"] == "sell" and row["rationale"] == "reviewed by hand", dict(row))
check("but the tweet is remembered as seen", conn.execute("SELECT COUNT(*) FROM x_calls").fetchone()[0] == 1)

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
