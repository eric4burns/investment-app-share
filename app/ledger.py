"""Ledger database access. Stdlib only — no install step, nothing to keep running."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Overridable so the browser smoke test can run against a throwaway copy. It
# creates and deletes drawings, and a test suite must never write to the real
# ledger — that file is thousands of imported brokerage transactions with no
# other source.
DB_PATH = Path(os.environ["INVESTMENT_APP_DB"]) if os.environ.get("INVESTMENT_APP_DB") \
    else ROOT / "ledger.db"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"


# Writes to these tables are bookkeeping, not data: nothing any cached answer
# is derived from changes when a five-minute candle is refreshed or a fetch is
# logged. Every other table counts. The dashboard's response cache used the
# ledger file's mtime as its freshness stamp, and these two tables move it on
# every chart open — so the whole cache was dropped every five minutes for a
# write that changed no answer. The epoch below moves only for the rest.
QUIET_TABLES = frozenset({"intraday_bars", "price_fetches", "meta",
                          # derived from data that already bumped the epoch
                          "verdict_cache"})


class LedgerConnection(sqlite3.Connection):
    """A connection things can be attached to.

    sqlite3.Connection has no __dict__ and cannot be weak-referenced, so the
    price cache had nowhere to live per-connection — setattr silently failed and
    the cache handed back a fresh empty dict on every call, turning what should
    be one query per symbol into 25,333 of them and a fifteen-second page load.
    A subclass has a __dict__ and costs nothing.

    It also keeps the cache epoch honest. The authorizer sees every INSERT,
    UPDATE and DELETE this connection compiles and marks it dirty when the
    table is one that answers are derived from; commit() then bumps the epoch
    inside the same transaction, so the bump and the data land together. This
    is done here rather than by asking every writer to remember a call, for
    the same reason the old scheme read the file's mtime: a writer that forgets
    is a stale page nobody can explain. The flag is sticky for the life of the
    connection — sqlite caches compiled statements, so a repeated write is not
    seen by the authorizer twice, and clearing it would miss the second commit.
    """
    _dirty = False

    def _watch(self, action, table, _col, dbname, _src):
        if (action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE)
                and table and table not in QUIET_TABLES
                and not table.startswith("sqlite_") and dbname != "temp"):
            self._dirty = True
        return sqlite3.SQLITE_OK

    def commit(self):
        if self._dirty and self.in_transaction:
            bump_epoch(self)
        super().commit()

    # `with conn:` reaches the C-level commit directly, not the override.
    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def close(self):
        # executescript() (every ensure_schema) commits whatever is pending
        # without passing through commit(). A connection that wrote, was
        # committed that way and then closed would leave the data in and the
        # epoch behind; it is caught here, where nothing is pending to lose.
        if self._dirty and not self.in_transaction:
            try:
                bump_epoch(self)
                super().commit()
            except sqlite3.Error:
                pass
            self._dirty = False
        super().close()


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    # Thirty seconds rather than the default five: the nightly job, the
    # dashboard and a background sync can all be writing, and a writer that
    # waits briefly is better than one that dies with "database is locked".
    conn = sqlite3.connect(db_path, factory=LedgerConnection, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    conn.set_authorizer(conn._watch)
    return conn


def bump_epoch(conn) -> None:
    """Advance the cache epoch: something a cached answer depends on changed.

    Called automatically by LedgerConnection on any meaningful commit; call it
    by hand only from a raw sqlite3 connection or after writing through a path
    that bypasses commit(). Cheap — one row — and safe to call repeatedly.
    """
    conn.execute(
        """INSERT INTO meta (key, value) VALUES ('cache_epoch', '1')
           ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1""")


def cache_epoch(conn) -> int:
    """The current epoch, 0 for a ledger nothing has written to yet."""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'cache_epoch'").fetchone()
    except sqlite3.OperationalError:          # no meta table: pre-schema database
        return 0
    return int(row[0]) if row else 0


def get_or_create_institution(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO institutions (name) VALUES (?)", (name,)).lastrowid


def get_or_create_account(
    conn: sqlite3.Connection,
    institution_id: int,
    external_id: str,
    name: str,
    kind: str,
    tax_status: str = "na",
) -> int:
    row = conn.execute(
        "SELECT id FROM accounts WHERE institution_id = ? AND external_id = ?",
        (institution_id, external_id),
    ).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        """INSERT INTO accounts (institution_id, external_id, name, kind, tax_status)
           VALUES (?, ?, ?, ?, ?)""",
        (institution_id, external_id, name, kind, tax_status),
    ).lastrowid


def get_or_create_security(conn: sqlite3.Connection, symbol: str, name: str | None = None) -> int | None:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return None
    row = conn.execute("SELECT id FROM securities WHERE symbol = ?", (symbol,)).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        "INSERT INTO securities (symbol, name) VALUES (?, ?)", (symbol, name)
    ).lastrowid


def insert_transaction(conn: sqlite3.Connection, txn: dict) -> bool:
    """Insert one transaction. Returns True if it was new, False if already present.

    Idempotency rests entirely on the (source, source_id) unique constraint, so
    re-importing an overlapping export costs nothing and changes nothing.

    RAISES on a constraint violation rather than reporting it as a duplicate.
    INSERT OR IGNORE swallows NOT NULL and CHECK failures too, so a row with an
    unparseable date returned the same False as a row already present — and the
    importer counted it as `skipped`, the same bucket as "already imported". A
    bank changing its date format silently dropped transactions while the import
    printed clean. A duplicate is expected and cheap; a malformed row is a gap
    in the ledger and has to be loud.
    """
    required = ("account_id", "txn_date", "kind", "source", "source_id")
    missing = [f for f in required if txn.get(f) in (None, "")]
    if missing:
        raise ValueError(
            f"transaction is missing {', '.join(missing)} "
            f"(source_id={txn.get('source_id')!r}, date={txn.get('txn_date')!r})")
    # These columns are NOT NULL with a default, and a named-parameter INSERT
    # has to supply every one it names. Passing None is not "use the default",
    # it is a constraint violation — and OR IGNORE swallows it, so the row
    # vanishes and is counted as a duplicate. A whole card import reported
    # "3 seen, 0 new, 3 dup" that way, which reads as "already imported" rather
    # than "silently discarded".
    txn = dict(txn)
    for column, default in (("fees", 0.0), ("commission", 0.0)):
        if txn.get(column) is None:
            txn[column] = default
    for column in ("settle_date", "security_id", "quantity", "price",
                   "description", "raw"):
        txn.setdefault(column, None)
    cur = conn.execute(
        """INSERT OR IGNORE INTO transactions
             (account_id, txn_date, settle_date, kind, security_id, quantity, price,
              amount, fees, commission, description, source, source_id, raw)
           VALUES (:account_id, :txn_date, :settle_date, :kind, :security_id, :quantity,
                   :price, :amount, :fees, :commission, :description, :source, :source_id, :raw)""",
        txn,
    )
    return cur.rowcount > 0


def record_import(conn, source: str, path: str, seen: int, inserted: int, skipped: int) -> None:
    conn.execute(
        """INSERT INTO import_runs (source, path, rows_seen, rows_inserted, rows_skipped)
           VALUES (?, ?, ?, ?, ?)""",
        (source, path, seen, inserted, skipped),
    )


def retry_locked(fn, tries: int = 10, wait: float = 3.0):
    """Run `fn()` again while the ledger is locked by another writer.

    The busy timeout on the connection is not enough on its own: a writer
    that commits and immediately writes again (the replay, scoring a name)
    can hold the lock for minutes in practice, and SQLite's busy handler gives
    a waiting writer no priority. A background job that dies with "database
    is locked" loses an hour of network work, so it waits and tries again.
    """
    import time
    for attempt in range(tries):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or attempt == tries - 1:
                raise
            time.sleep(wait * (attempt + 1))
