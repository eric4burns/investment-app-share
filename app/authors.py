"""Levels the followed authors have named on a symbol — zones and targets.

The journal grades CALLS: a buy made while price is in the zone, a sell. A
buy zone named below price is not a call and is not graded there (D51), but
it is exactly what the user wants to see beside the app's own level:
StonkChris had MP at $44–47 and SOFI under $15 while the app said "buy here".
So zones and targets live in their own table, dated and attributed, and the
Outlook shows the recent ones on each name.

Fed by research/seed-author-levels.py from the Substack extraction and the X
reads; idempotent on (author, symbol, date, kind, lo).
"""
from __future__ import annotations

from . import journal

SCHEMA = """
CREATE TABLE IF NOT EXISTS author_levels (
    id INTEGER PRIMARY KEY,
    author TEXT NOT NULL,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    kind TEXT NOT NULL,             -- buy_zone | target | downside
    lo REAL NOT NULL,
    hi REAL,
    note TEXT,
    source TEXT,
    UNIQUE (author, symbol, date, kind, lo)
);
CREATE INDEX IF NOT EXISTS ix_author_levels_symbol ON author_levels (symbol, date);
-- Raw MENTIONS, as opposed to levels: who said a ticker's name, and when.
-- A level is a considered call; a mention is only evidence that a name has
-- reached somebody's timeline, which is the question "are we early?" needs.
CREATE TABLE IF NOT EXISTS x_mentions (
    handle TEXT NOT NULL, symbol TEXT NOT NULL, date TEXT NOT NULL,
    tweet_id TEXT NOT NULL,
    PRIMARY KEY (handle, symbol, tweet_id)
);
CREATE INDEX IF NOT EXISTS ix_x_mentions_symbol ON x_mentions (symbol, date);
"""

# Cashtags only. A bare word that happens to match a ticker ("IT", "ALL", "ON")
# would swamp the count, and the accounts being read write $IREN by convention.
CASHTAG = __import__("re").compile(r"\$([A-Z][A-Z.\-]{0,5})\b")

# How many DISTINCT accounts have to be talking before a name stops being early.
#
# Unmeasured, and labelled as such wherever it is shown. Testing these would
# need the followed accounts' post history from before each name ran, which is
# not on disk — the seeded record only starts 2025-09-24, after every purchase
# it would have to judge. These are a starting point to be replaced by measured
# ones once that history exists, not a finding.
CROWD_WARMING = 2
CROWD_CROWDED = 4


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def store(conn, rows: list[dict]) -> int:
    ensure_schema(conn)
    n = 0
    for r in rows:
        cur = conn.execute("""INSERT OR IGNORE INTO author_levels (author, symbol, date, kind, lo, hi, note, source)
                              VALUES (?,?,?,?,?,?,?,?)""",
                           (journal.canonical_author(r["author"]), r["symbol"].upper(), r["date"], r["kind"], r["lo"], r.get("hi"),
                            (r.get("note") or "")[:200], r.get("source")))
        n += cur.rowcount
    conn.commit()
    return n


def recent(conn, since: str, per_symbol: int = 6) -> dict[str, list[dict]]:
    ensure_schema(conn)
    out: dict[str, list[dict]] = {}
    for r in conn.execute("""SELECT author, symbol, date, kind, lo, hi, note FROM author_levels
                             WHERE date >= ? ORDER BY date DESC""", (since,)):
        lst = out.setdefault(r["symbol"], [])
        if len(lst) < per_symbol:
            lst.append({"author": r["author"], "date": r["date"], "kind": r["kind"], "lo": r["lo"], "hi": r["hi"],
                        "note": r["note"]})
    return out


def store_mentions(conn, rows: list[dict]) -> int:
    """Rows of {handle, symbol, date, tweet_id}. Idempotent on the tweet."""
    ensure_schema(conn)
    n = 0
    for r in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO x_mentions (handle, symbol, date, tweet_id) VALUES (?,?,?,?)",
            (r["handle"].lstrip("@"), r["symbol"].upper(), r["date"][:10], str(r["tweet_id"])))
        n += cur.rowcount
    conn.commit()
    return n


def mentions_in(text: str) -> set[str]:
    """The cashtags in one post."""
    return {m.upper() for m in CASHTAG.findall(text or "")}


def crowd(conn, symbols: list[str], asof: str, window: int = 30) -> dict[str, dict]:
    """Is the crowd already here on each name?

    Counts DISTINCT accounts rather than posts: one person posting twelve times
    about a name is one person, and a mention count would read it as a wave.

    `state` is early / warming / crowded against the thresholds above, and it
    carries `measured: False` because those thresholds are a judgement, not a
    measurement — see the note on CROWD_WARMING. A name with no mentions at all
    reads `early`, which is also what a name nobody has heard of reads, and the
    two are not distinguishable from this data.
    """
    ensure_schema(conn)
    if not symbols:
        return {}
    from datetime import date, timedelta
    since = (date.fromisoformat(asof) - timedelta(days=window)).isoformat()
    prior = (date.fromisoformat(asof) - timedelta(days=window * 2)).isoformat()
    marks = ",".join("?" * len(symbols))
    syms = [s.upper() for s in symbols]
    now = {r["symbol"]: (r["n"], r["who"]) for r in conn.execute(
        f"""SELECT symbol, COUNT(DISTINCT handle) n, GROUP_CONCAT(DISTINCT handle) who
            FROM x_mentions WHERE symbol IN ({marks}) AND date > ? AND date <= ?
            GROUP BY symbol""", (*syms, since, asof))}
    before = {r["symbol"]: r["n"] for r in conn.execute(
        f"""SELECT symbol, COUNT(DISTINCT handle) n FROM x_mentions
            WHERE symbol IN ({marks}) AND date > ? AND date <= ?
            GROUP BY symbol""", (*syms, prior, since))}
    first = {r["symbol"]: r["d"] for r in conn.execute(
        f"SELECT symbol, MIN(date) d FROM x_mentions WHERE symbol IN ({marks}) GROUP BY symbol", syms)}
    out = {}
    for s in syms:
        n, who = now.get(s, (0, ""))
        was = before.get(s, 0)
        state = "crowded" if n >= CROWD_CROWDED else "warming" if n >= CROWD_WARMING else "early"
        out[s] = {"accounts": n, "accounts_before": was, "handles": (who or "").split(",") if who else [],
                  "first_seen": first.get(s), "state": state, "rising": n > was,
                  "measured": False}
    return out


def mention_coverage(conn) -> dict:
    """How much post history the crowd reading is actually standing on.

    Reported alongside every crowd verdict because the two look identical and
    are not: a name nobody is discussing and a name from a week the pull never
    covered both come back with zero accounts. With one pull on disk the honest
    label for every "early" is "no data", and the panel has to say so.
    """
    ensure_schema(conn)
    r = conn.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT date) days, MIN(date) first, MAX(date) last, "
        "COUNT(DISTINCT handle) handles FROM x_mentions").fetchone()
    return {"mentions": r["n"], "days": r["days"], "first": r["first"],
            "last": r["last"], "handles": r["handles"],
            "thin": (r["days"] or 0) < 20}
