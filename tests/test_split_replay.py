"""The replay's rows move to their own file and every reader still finds them.

Built on a temp-directory ledger rather than :memory:, because the whole
point is a second FILE beside the first: where it is looked for, what happens
when it is absent, and that a fresh clone with no replay file still works.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import calibration, journal, ledger, measure, replay, split_replay  # noqa: E402

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


TMP = Path(tempfile.mkdtemp(prefix="split-replay-"))
DB = TMP / "ledger.db"
REPLAY = TMP / "ledger-replay.db"


def fresh():
    conn = ledger.connect(DB)
    journal.ensure_schema(conn)
    return conn


def seed_prices(conn, sym, start, days, first, step):
    sid = conn.execute("INSERT INTO securities (symbol, kind) VALUES (?, 'equity')", (sym,)).lastrowid
    d0 = date.fromisoformat(start)
    for i in range(days):
        c = first + step * i
        conn.execute("""INSERT INTO prices (security_id, bar_date, close, open, high, low, volume, source)
                        VALUES (?,?,?,?,?,?,0,'test')""", (sid, (d0 + timedelta(days=i)).isoformat(), c, c, c, c))


START = (date.today() - timedelta(days=200)).isoformat()
conn = fresh()
seed_prices(conn, "SPY", START, 200, 100.0, 0.0)
seed_prices(conn, "UP", START, 200, 10.0, 0.05)
seed_prices(conn, "DN", START, 200, 10.0, -0.02)
# Replayed calls on three sources, plus live rows that must never move.
d0 = date.fromisoformat(START)
n_replay = 0
for i in range(0, 120, 7):
    d = (d0 + timedelta(days=i)).isoformat()
    for src in ("replay", "replay-screen", "replay-confirm2"):
        for sym in ("UP", "DN"):
            journal.record(conn, d, sym, src, "buy", price=10.0, timeframe="D", confidence="high",
                           evidence=[{"name": "x", "stance": "bull"}, {"name": "y", "stance": "bear"}])
            n_replay += 1
journal.record(conn, START, "UP", "app", "buy", price=10.0, timeframe="D",
               evidence=[{"name": "x", "stance": "bull", "detail": "kept"}])
journal.record(conn, START, "DN", "me", "sell", price=10.0)
journal.record(conn, START, "UP", "trade", "buy", price=10.0)
conn.commit()
live_before = {r[0]: r[1] for r in conn.execute(
    "SELECT source, COUNT(*) FROM decisions WHERE source NOT LIKE 'replay%' GROUP BY source")}
ev_before = conn.execute("SELECT COUNT(*) FROM decision_evidence").fetchone()[0]

# ---- before the split: no replay file, everything in main -----------------
check("no replay file means the ledger's own table is read",
      split_replay.prefix(conn, "replay") == "main." and not REPLAY.exists())
check("a live source is always the ledger's table", split_replay.prefix(conn, "app") == "main.")
check("an in-memory ledger has nowhere for a replay file and says so",
      split_replay.replay_path(sqlite3.connect(":memory:")) is None)
before_cal = calibration.report(conn, 21, source="replay")
before_meas = measure.graded(conn, 21, "D", "replay-screen")
before_status = replay.status(conn, "replay-confirm2")
check("the fixture grades: the split has something to preserve",
      before_cal["by_action"]["buy"]["n"] > 0 and len(before_meas) > 0 and before_status["calls"] > 0,
      (before_cal["by_action"], len(before_meas), before_status))

# ---- the plan, and a refusal --------------------------------------------------
pl = split_replay.plan(conn)
check("the plan counts every replay row and no live row",
      pl["move_decisions"] == n_replay and pl["move_evidence"] == n_replay * 2
      and pl["keep_decisions"] == sum(live_before.values()), pl)
try:
    split_replay._open_exclusive(DB, timeout=0.5)
    refused = False
except sqlite3.OperationalError:
    refused = True
check("with another connection open, the exclusive lock is refused", refused)
conn.close()

# ---- the split ----------------------------------------------------------------
excl = split_replay._open_exclusive(DB)
excl.executescript(ledger.SCHEMA.read_text())
log = []
r = split_replay.split(excl, say=log.append)
excl.close()
check("the split moves exactly the replay rows and their evidence",
      r["moved_decisions"] == n_replay and r["moved_evidence"] == n_replay * 2, r)
check("the replay file now exists beside the ledger", REPLAY.exists())

conn = fresh()
check("the ledger keeps the live rows, untouched",
      {r[0]: r[1] for r in conn.execute("SELECT source, COUNT(*) FROM decisions GROUP BY source")} == live_before)
check("and only their evidence",
      conn.execute("SELECT COUNT(*) FROM decision_evidence").fetchone()[0] == ev_before - n_replay * 2
      and conn.execute("SELECT detail FROM decision_evidence").fetchone()[0] == "kept")
check("with the file present, a replay source resolves to it",
      split_replay.prefix(conn, "replay") == "replay." and split_replay.prefix(conn, "app") == "main.")
check("the replay file holds every source, with its evidence",
      {r[0]: r[1] for r in conn.execute("SELECT source, COUNT(*) FROM replay.decisions GROUP BY source")}
      == {"replay": n_replay // 3, "replay-screen": n_replay // 3, "replay-confirm2": n_replay // 3}
      and conn.execute("SELECT COUNT(*) FROM replay.decision_evidence").fetchone()[0] == n_replay * 2)
check("the replay file carries the journal's indexes",
      {r[0] for r in conn.execute("SELECT name FROM replay.sqlite_master WHERE type='index'")}
      >= {"ux_decisions_replay", "ux_decisions_replay_screen", "ux_decisions_replay_confirm2", "ix_decisions_symbol"})
check("and the columns the journal added later (bucket, tag, author)",
      {"bucket", "tag", "author"} <= {r[1] for r in conn.execute("PRAGMA replay.table_info(decisions)")})

after_cal = calibration.report(conn, 21, source="replay")
after_meas = measure.graded(conn, 21, "D", "replay-screen")
after_status = replay.status(conn, "replay-confirm2")
check("calibration reads the same record from the replay file",
      after_cal["by_action"] == before_cal["by_action"] and after_cal["headline"] == before_cal["headline"])
check("measure reads the same calls from the replay file",
      sorted((c["date"], c["symbol"], c["excess"]) for c in after_meas)
      == sorted((c["date"], c["symbol"], c["excess"]) for c in before_meas))
check("replay.status reads the same counts, and says where from",
      {k: v for k, v in after_status.items() if k != "where"} == {k: v for k, v in before_status.items() if k != "where"}
      and after_status["where"] == "replay" and before_status["where"] == "main", (before_status, after_status))
check("the live sources still calibrate from the ledger",
      calibration.report(conn, 21, source="app")["by_action"]["buy"]["n"] == 1)

# ---- idempotent ---------------------------------------------------------------
conn.close()
excl = split_replay._open_exclusive(DB)
r2 = split_replay.split(excl, say=lambda *a: None)
excl.close()
check("a second run moves nothing", r2["moved_decisions"] == 0 and r2["moved_evidence"] == 0, r2)

# ---- the replay writes to the file from now on -----------------------------------
conn = fresh()
pfx = split_replay.prefix(conn, "replay")
did = replay._record(conn, pfx, "2030-01-03", "UP", "replay", "hold", 12.0, "W", "low", None,
                     [{"name": "z", "stance": "bull", "detail": "dropped"}, {"name": "z", "stance": "bull"}])
conn.commit()
check("a new replayed call lands in the replay file, not the ledger",
      conn.execute("SELECT COUNT(*) FROM replay.decisions WHERE date='2030-01-03'").fetchone()[0] == 1
      and conn.execute("SELECT COUNT(*) FROM main.decisions WHERE date='2030-01-03'").fetchone()[0] == 0)
check("with its evidence deduplicated and its detail dropped, as the journal does",
      [tuple(r) for r in conn.execute(
          "SELECT name, stance, detail FROM replay.decision_evidence WHERE decision_id=?", (did,))] == [("z", "bull", None)])
did2 = replay._record(conn, pfx, "2030-01-03", "UP", "replay", "sell", 13.0, "W", "high", None, [])
check("re-recording the same day replaces the row rather than adding one",
      did2 == did and conn.execute("SELECT action FROM replay.decisions WHERE id=?", (did,)).fetchone()[0] == "sell")
check("_done sees the replay file", "2030-01-03" not in replay._done(conn, "UP")
      and "2030-01-03" in {r[0] for r in conn.execute("SELECT date FROM replay.decisions WHERE symbol='UP'")})
check("clear() empties one source in the replay file and leaves the others",
      replay.clear(conn, source="replay") == n_replay // 3 + 1
      and conn.execute("SELECT COUNT(*) FROM replay.decisions WHERE source='replay-screen'").fetchone()[0] == n_replay // 3
      and conn.execute("SELECT COUNT(*) FROM replay.decision_evidence WHERE decision_id NOT IN "
                       "(SELECT id FROM replay.decisions)").fetchone()[0] == 0)
mid = ledger.connect(DB)
mid.execute("INSERT INTO institutions (name) VALUES ('t')")       # a transaction is now open
try:
    split_replay.attach(mid)
    refused_mid = False
except sqlite3.OperationalError:
    refused_mid = True
mid.rollback()
mid.close()
check("attach() refuses to run inside an open transaction rather than failing later", refused_mid)

# ---- vacuum into ----------------------------------------------------------------
conn.close()
before_size = DB.stat().st_size
v = split_replay.vacuum_into(DB, say=lambda *a: None)
check("vacuum rebuilds the ledger in place when nothing has it open",
      v["swapped"] and DB.exists() and not DB.with_name("ledger-vacuumed.db").exists(), v)
conn = fresh()
check("and the rebuilt ledger opens with its live rows and the replay still attached",
      {r[0]: r[1] for r in conn.execute("SELECT source, COUNT(*) FROM decisions GROUP BY source")} == live_before
      and split_replay.prefix(conn, "replay-screen") == "replay."
      and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
hold = ledger.connect(DB)
logs = []
v2 = split_replay.vacuum_into(DB, say=logs.append)
check("with the ledger open elsewhere, vacuum builds the file but prints the swap instead of doing it",
      not v2["swapped"] and Path(v2["built"]).exists() and any("mv " in l for l in logs), logs)
hold.close()
conn.close()


# tidy the temp dir
for p in TMP.iterdir():
    try:
        os.unlink(p)
    except OSError:
        pass

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
