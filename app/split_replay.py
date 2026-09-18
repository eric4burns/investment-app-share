"""Move the replayed calls out of the ledger into their own file, and keep
them there.

    python3 -m app.split_replay             # dry run: what would move, and the sizes
    python3 -m app.split_replay --apply     # move the rows (server stopped)
    python3 -m app.split_replay --vacuum    # give the freed space back, afterwards

## Why

The replay (`app/replay.py`) records the engine's call at every week-end
since 2022 across every name held, watched or sampled from the liquidity
screen: 330,000 decisions and 6.6 million evidence rows, 417 MB of a 759 MB
ledger. Every one of those rows is reproducible by `python3 -m app.replay
run`, and nothing but `measure.py`, `calibration.py` and the replay itself
ever reads them. The other 340 MB — transactions, the watchlist, the live
journal, the price cache — is what the dashboard serves, what `backup.sh`
snapshots, and what has to survive.

Keeping the two in one file meant every nightly backup carried 400 MB of
reproducible rows, every `VACUUM` after a `--redo` rewrote the whole file
under an exclusive lock while the server timed out, and the size budget in
`tests/test_size.py` measured the replay rather than the ledger.

## How the split holds

`ledger-replay.db` lives beside `ledger.db`. `attach(conn)` attaches it as
`replay` when the file exists, and `prefix(conn, source)` says which schema a
given source's rows live in: replay* sources in the attached file, everything
else in main. The three readers and the one writer qualify their table names
through it, so on a fresh clone with no replay file everything still lands in
the ledger exactly as before, and after the split it lands in the replay
file. Nothing else in the app touches replay rows, so nothing else changes.

Row ids are copied as they are. They are only ever joined within the same
file (`decision_evidence.decision_id` against `decisions.id` in the same
schema), so an id the ledger later reuses for a live call cannot collide with
anything.

## What --apply does, in order

1. Refuses unless a backup was taken in the last day (`./backup.sh`), and
   refuses if any other process has the ledger open — the server, the poll,
   a replay — by taking an exclusive lock with a short timeout.
2. Creates `ledger-replay.db` with the same `decisions` and
   `decision_evidence` schema, indexes included.
3. In one transaction: copies every `source LIKE 'replay%'` decision and its
   evidence into the replay file, verifies the counts match, and only then
   deletes them from the ledger. A failed count check rolls everything back.
4. Checkpoints the ledger's write-ahead log. The file does not shrink until
   `--vacuum`, which rebuilds it with `VACUUM INTO` a new file and swaps it in
   — automatically when nobody has the ledger open, otherwise it prints the
   two commands to run.

Re-running `--apply` after a success is a no-op: there is nothing left to
move. Re-running after an interruption picks up where it stopped, because
rows already in the replay file are skipped rather than duplicated.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from . import journal
from .ledger import DB_PATH, LedgerConnection, SCHEMA as LEDGER_SCHEMA, connect

REPLAY_SUFFIX = "-replay.db"          # ledger.db -> ledger-replay.db
ALIAS = "replay"
REPLAY_SOURCE_LIKE = "replay%"
BACKUP_DIR = Path.home() / "Backups" / "investment-app"
BACKUP_MAX_AGE_HOURS = 24
LOCK_TIMEOUT_SECONDS = 2.0

# ----------------------------------------------------------------- runtime ----


def is_replay_source(source: str | None) -> bool:
    return bool(source) and source.startswith("replay")


def replay_path(conn: sqlite3.Connection) -> Path | None:
    """Where the replay file lives for this connection's ledger, or None for
    an in-memory database (the test suites), which has nowhere to put one."""
    for _seq, name, file in conn.execute("PRAGMA database_list"):
        if name == "main":
            if not file:
                return None
            p = Path(file)
            return p.with_name(p.stem + REPLAY_SUFFIX)
    return None


def attached(conn: sqlite3.Connection) -> bool:
    return any(r[1] == ALIAS for r in conn.execute("PRAGMA database_list"))


def attach(conn: sqlite3.Connection, create: bool = False) -> bool:
    """Attach `ledger-replay.db` as `replay` if it exists beside the ledger.

    Returns True when the replay file is attached. With `create`, an absent
    file is created (the split does this; nothing else should — a fresh clone
    keeps its replay rows in the ledger until someone runs the split).

    Called at the start of an entry point, before any write: SQLite refuses
    to ATTACH inside an open transaction.
    """
    if attached(conn):
        return True
    p = replay_path(conn)
    if p is None or (not p.exists() and not create):
        return False
    if conn.in_transaction:
        raise sqlite3.OperationalError(
            "attach() must run before the first write on a connection")
    fresh = not p.exists()
    conn.execute(f"ATTACH DATABASE ? AS {ALIAS}", (str(p),))
    if fresh and p.exists():
        # Created under the umask; the calls in it are private like the ledger.
        os.chmod(p, 0o600)
    # Same journal mode as the ledger, for the same reason: the replay writes
    # in small batches for forty minutes while measure.py may be reading.
    conn.execute(f"PRAGMA {ALIAS}.journal_mode = WAL")
    ensure_replay_schema(conn)
    return True


def prefix(conn: sqlite3.Connection, source: str | None) -> str:
    """The schema qualifier for `source`'s rows: 'replay.' for a replay source
    when the replay file is attached, 'main.' otherwise."""
    if is_replay_source(source) and attach(conn):
        return f"{ALIAS}."
    return "main."


def _qualified(sql: str, schema: str) -> str:
    """Rewrite journal.SCHEMA so its tables and indexes land in `schema`.

    Only the created object's name takes the qualifier: an index's ON clause
    must stay bare, since SQLite requires an index to live with its table."""
    sql = re.sub(r"CREATE TABLE IF NOT EXISTS (\w+)", rf"CREATE TABLE IF NOT EXISTS {schema}.\1", sql)
    sql = re.sub(r"CREATE (UNIQUE )?INDEX IF NOT EXISTS (\w+)",
                 rf"CREATE \1INDEX IF NOT EXISTS {schema}.\2", sql)
    sql = re.sub(r"DROP INDEX IF EXISTS (\w+)", rf"DROP INDEX IF EXISTS {schema}.\1", sql)
    return sql


def ensure_replay_schema(conn: sqlite3.Connection) -> None:
    """The journal's two tables, as journal.ensure_schema would make them,
    inside the attached replay file."""
    conn.executescript(_qualified(journal.SCHEMA, ALIAS))
    cols = {r[1] for r in conn.execute(f"PRAGMA {ALIAS}.table_info(decisions)")}
    for col in ("bucket", "tag", "author"):
        if col not in cols:
            conn.execute(f"ALTER TABLE {ALIAS}.decisions ADD COLUMN {col} TEXT")
    conn.executescript(_qualified(journal.OUTSIDE_SCHEMA, ALIAS))


# --------------------------------------------------------------- migration ----


def _open_exclusive(db: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> sqlite3.Connection:
    """A connection that owns the ledger outright, or an OperationalError.

    In WAL mode every open connection — the server sitting idle, a poll in
    progress — holds a shared lock for as long as it is open, so asking for
    an exclusive one is the direct test of "does anything else have this
    file". `timeout` bounds the wait; 'database is locked' is the answer.
    """
    conn = sqlite3.connect(db, factory=LedgerConnection, timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA locking_mode = EXCLUSIVE")
        # The lock is only taken on first access; a write is what makes it
        # exclusive rather than shared.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS _split_probe (x)")
        conn.execute("DROP TABLE _split_probe")
        conn.execute("COMMIT")
    except sqlite3.OperationalError:
        # A refused attempt must not itself keep the file open: the handle
        # holds a shared lock until it is closed, and the next attempt —
        # seconds later, in the same process — would then refuse itself.
        conn.close()
        raise
    return conn


def holders(db: Path) -> list[str]:
    """Processes with the ledger open, by lsof, for the refusal message."""
    try:
        out = subprocess.run(["lsof", "-t", "--", str(db)], capture_output=True, text=True,
                             timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for pid in out:
        try:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            cmd = ""
        names.append(f"pid {pid}: {cmd[:80]}" if cmd else f"pid {pid}")
    return names


def latest_backup(backup_dir: Path = BACKUP_DIR) -> tuple[Path | None, float | None]:
    """The newest full snapshot and its age in hours."""
    snaps = sorted(backup_dir.glob("ledger-*.db.gz"), key=lambda p: p.stat().st_mtime)
    if not snaps:
        return None, None
    return snaps[-1], (time.time() - snaps[-1].stat().st_mtime) / 3600


def _size(p: Path) -> int:
    return p.stat().st_size if p.exists() else 0


def _mb(n: int | float) -> str:
    return f"{n / 1e6:,.0f} MB"


def plan(conn: sqlite3.Connection) -> dict:
    """What would move, counted in the ledger and in the replay file."""
    journal.ensure_schema(conn)
    by_source = {r[0]: r[1] for r in conn.execute(
        "SELECT source, COUNT(*) FROM main.decisions WHERE source LIKE ? GROUP BY source",
        (REPLAY_SOURCE_LIKE,))}
    evidence = conn.execute(
        """SELECT COUNT(*) FROM main.decision_evidence
            WHERE decision_id IN (SELECT id FROM main.decisions WHERE source LIKE ?)""",
        (REPLAY_SOURCE_LIKE,)).fetchone()[0]
    keep = conn.execute("SELECT COUNT(*) FROM main.decisions WHERE source NOT LIKE ?",
                        (REPLAY_SOURCE_LIKE,)).fetchone()[0]
    out = {"move_decisions": sum(by_source.values()), "by_source": by_source,
           "move_evidence": evidence, "keep_decisions": keep, "already": None}
    if attached(conn):
        out["already"] = {
            "decisions": conn.execute(f"SELECT COUNT(*) FROM {ALIAS}.decisions").fetchone()[0],
            "evidence": conn.execute(f"SELECT COUNT(*) FROM {ALIAS}.decision_evidence").fetchone()[0]}
    return out


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def split(conn: sqlite3.Connection, say=print) -> dict:
    """Copy the replay rows across, verify, delete. One transaction."""
    journal.ensure_schema(conn)
    attach(conn, create=True)
    before = plan(conn)
    if not before["move_decisions"]:
        say("  nothing to move: the ledger holds no replay rows")
        return {"moved_decisions": 0, "moved_evidence": 0}
    dcols = [c for c in _columns(conn, "main", "decisions") if c in _columns(conn, ALIAS, "decisions")]
    ecols = _columns(conn, "main", "decision_evidence")
    dlist = ", ".join(dcols)
    elist = ", ".join(ecols)
    t0 = time.time()
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Rows already across (an interrupted earlier run) are skipped by id,
        # so the copy is safe to repeat; the evidence's primary key does the
        # same for its rows.
        conn.execute(
            f"""INSERT INTO {ALIAS}.decisions ({dlist})
                SELECT {dlist} FROM main.decisions
                 WHERE source LIKE ? AND id NOT IN (SELECT id FROM {ALIAS}.decisions)""",
            (REPLAY_SOURCE_LIKE,))
        say(f"  copied decisions ({time.time() - t0:,.0f}s)")
        conn.execute(
            f"""INSERT OR IGNORE INTO {ALIAS}.decision_evidence ({elist})
                SELECT {elist} FROM main.decision_evidence
                 WHERE decision_id IN (SELECT id FROM main.decisions WHERE source LIKE ?)""",
            (REPLAY_SOURCE_LIKE,))
        say(f"  copied evidence ({time.time() - t0:,.0f}s)")
        # Verify by source AND by evidence, against what the ledger holds.
        # A count that differs means the copy is not the record, and the
        # ledger's rows stay exactly where they were.
        for source, n in before["by_source"].items():
            got = conn.execute(f"SELECT COUNT(*) FROM {ALIAS}.decisions WHERE source=?",
                               (source,)).fetchone()[0]
            if got < n:
                raise RuntimeError(f"{source}: ledger has {n:,} rows, replay file has {got:,}")
        missing = conn.execute(
            f"""SELECT COUNT(*) FROM main.decision_evidence e
                 WHERE e.decision_id IN (SELECT id FROM main.decisions WHERE source LIKE ?)
                   AND NOT EXISTS (SELECT 1 FROM {ALIAS}.decision_evidence r
                                    WHERE r.decision_id = e.decision_id
                                      AND r.name = e.name AND r.stance IS e.stance)""",
            (REPLAY_SOURCE_LIKE,)).fetchone()[0]
        if missing:
            raise RuntimeError(f"{missing:,} evidence rows did not arrive in the replay file")
        say(f"  verified: {before['move_decisions']:,} decisions and "
            f"{before['move_evidence']:,} evidence rows are in the replay file")
        ev = conn.execute(
            """DELETE FROM main.decision_evidence
                WHERE decision_id IN (SELECT id FROM main.decisions WHERE source LIKE ?)""",
            (REPLAY_SOURCE_LIKE,)).rowcount
        de = conn.execute("DELETE FROM main.decisions WHERE source LIKE ?",
                          (REPLAY_SOURCE_LIKE,)).rowcount
        if de != before["move_decisions"] or ev != before["move_evidence"]:
            raise RuntimeError(f"deleted {de:,}/{ev:,} rows but expected "
                               f"{before['move_decisions']:,}/{before['move_evidence']:,}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    say(f"  deleted from the ledger ({time.time() - t0:,.0f}s)")
    conn.execute("PRAGMA main.wal_checkpoint(TRUNCATE)")
    conn.execute(f"PRAGMA {ALIAS}.wal_checkpoint(TRUNCATE)")
    return {"moved_decisions": de, "moved_evidence": ev, "seconds": round(time.time() - t0)}


def vacuum_into(db: Path, say=print) -> dict:
    """Rebuild the ledger into a new file and swap it in, or say how to.

    `VACUUM INTO` never touches the source, so it is safe with the server
    up; the swap is what is not. It is done here only while this process
    holds the exclusive lock — nothing else can open the old file until the
    new one is in its place — and otherwise the two commands are printed.
    """
    new = db.with_name(db.stem + "-vacuumed.db")
    if new.exists():
        new.unlink()
    try:
        conn = _open_exclusive(db)
    except sqlite3.OperationalError:
        conn = None
    if conn is None:
        # Still worth building: reading is safe. Only the swap waits.
        c = sqlite3.connect(db, timeout=30)
        c.execute("VACUUM INTO ?", (str(new),))
        c.close()
        say(f"  built {new.name}: {_mb(_size(db))} -> {_mb(_size(new))}")
        say("  something has the ledger open, so it was not swapped in. Stop the server, then:")
        say(f"    mv '{new}' '{db}'")
        say(f"    rm -f '{db}-wal' '{db}-shm'")
        return {"built": str(new), "swapped": False}
    before = _size(db)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM INTO ?", (str(new),))
    check = sqlite3.connect(new)
    ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    check.close()
    if ok != "ok":
        conn.close()
        new.unlink()
        raise RuntimeError(f"the rebuilt file failed its integrity check: {ok}")
    # The ledger is private (real brokerage history); VACUUM INTO creates the
    # new file under the umask, so put the mode back before it becomes the
    # ledger.
    os.chmod(new, 0o600)
    # Replace the directory entry while the old inode is still held open
    # and locked; whoever opens next gets the new file.
    os.replace(new, db)
    conn.close()
    # The old file's sidecars: the -shm is only a lock index and is rebuilt
    # on the next open; the -wal was truncated to nothing by the checkpoint
    # above, and a non-empty one would mean that assumption failed, so it is
    # left for a person to look at.
    shm = f"{db}-shm"
    if os.path.exists(shm):
        os.unlink(shm)
    wal = f"{db}-wal"
    if os.path.exists(wal) and os.path.getsize(wal) == 0:
        os.unlink(wal)
    say(f"  compacted: {_mb(before)} -> {_mb(_size(db))}")
    return {"built": str(db), "swapped": True, "before": before, "after": _size(db)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.split_replay", description=__doc__.split("\n\n")[0])
    p.add_argument("--apply", action="store_true", help="move the rows (default is a dry run)")
    p.add_argument("--vacuum", action="store_true",
                   help="rebuild the ledger with VACUUM INTO and swap it in")
    p.add_argument("--db", default=str(DB_PATH), help=argparse.SUPPRESS)
    p.add_argument("--skip-backup-check", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    db = Path(args.db)
    replay = db.with_name(db.stem + REPLAY_SUFFIX)
    if not db.exists():
        print(f"no ledger at {db}", file=sys.stderr)
        return 1

    if not args.apply and not args.vacuum:
        conn = connect(db)
        attach(conn)
        pl = plan(conn)
        conn.close()
        print(f"ledger      {db}  {_mb(_size(db))}"
              + (f"  (+ {_mb(_size(db.with_name(db.name + '-wal')))} write-ahead log)"
                 if _size(db.with_name(db.name + "-wal")) else ""))
        print(f"replay file {replay}  " + (_mb(_size(replay)) if replay.exists() else "(not yet created)"))
        print()
        print(f"would move {pl['move_decisions']:,} decisions and {pl['move_evidence']:,} evidence rows:")
        for s, n in sorted(pl["by_source"].items()):
            print(f"  {s:<18} {n:>9,}")
        print(f"would keep {pl['keep_decisions']:,} decisions (app, me, trade, outside) in the ledger")
        if pl["already"]:
            print(f"replay file already holds {pl['already']['decisions']:,} decisions, "
                  f"{pl['already']['evidence']:,} evidence rows")
        print()
        print("dry run. To do it, with the server stopped:")
        print("  ./backup.sh")
        print("  python3 -m app.split_replay --apply")
        print("  python3 -m app.split_replay --vacuum")
        return 0

    if args.apply:
        snap, age = latest_backup()
        if not args.skip_backup_check and (snap is None or age > BACKUP_MAX_AGE_HOURS):
            print("refusing: no full backup from the last "
                  f"{BACKUP_MAX_AGE_HOURS} hours in {BACKUP_DIR}"
                  + (f" (newest is {snap.name}, {age:.0f} h old)" if snap else ""))
            print("run this first, then try again:")
            print("  ./backup.sh")
            return 2
        try:
            conn = _open_exclusive(db)
        except sqlite3.OperationalError as exc:
            print(f"refusing: something else has the ledger open ({exc})")
            for h in holders(db):
                print(f"  {h}")
            print("stop the dashboard (launchctl bootout gui/$(id -u)/com.$USER.investment-app.serve)")
            print("and any replay or update, then try again.")
            return 3
        wal = db.with_name(db.name + "-wal")
        if _size(wal) > 1_000_000:
            print(f"  write-ahead log holds {_mb(_size(wal))}; it is checkpointed as part of the move")
        conn.executescript(LEDGER_SCHEMA.read_text())
        print(f"  ledger {_mb(_size(db))} before")
        r = split(conn, say=print)
        conn.close()
        print(f"  moved {r['moved_decisions']:,} decisions and {r['moved_evidence']:,} evidence rows "
              f"to {replay.name} ({_mb(_size(replay))})")
        print(f"  ledger {_mb(_size(db))} on disk — the freed pages come back with:")
        print("  python3 -m app.split_replay --vacuum")
        return 0

    if args.vacuum:
        vacuum_into(db, say=print)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
