"""A record of calls made, and whether they turned out to be right.

## Why this is not the backtester

`backtest.py` asks a retrospective question: if this method had been followed
over history, what would have happened. It is powerful and it is also the
easiest thing in this project to fool yourself with, which is why it carries a
survivorship control — the momentum method returned +398% on a watchlist
assembled today and -4.0% on sector ETFs over the identical period.

This module asks the opposite, prospective question: here is a call that was
actually made on a date, before the outcome was known. Nothing about it can be
re-run, re-tuned or re-fitted, because the record was written before the answer
existed. That makes it a far smaller dataset and a far more honest one.

## Two sources, one table, deliberately

Rows are written by the app (`source='app'`, a verdict from `verdicts.py`) and
by the user (`source='me'`, a decision actually taken). They share a table and
are scored by identical code, so the question "does the app add anything to
what I would have done anyway" is a query rather than a project.

Keeping them in separate tables would have made that comparison a special
report someone has to remember to write. Here it is the default.

## How a call is graded

Every call is graded on the symbol's return from the call price to the horizon
price, **measured against SPY over exactly the same dates**. A buy that made 4%
in a month when the index made 6% was not a good call, and grading on raw
return alone would have recorded it as one.

The excess is then signed by what the call actually claimed:

    buy, add    +1.0   full exposure asserted
    hold        +1.0   exposure kept, which is a decision
    trim        -0.5   exposure partially removed
    sell        -1.0   exposure removed

So a sell is scored positively when the name went on to underperform, which is
what a sell is a claim about. `hold` is graded rather than skipped because
holding is a choice: a hold on a name that then fell 30% was wrong, and a
journal that only graded the trades would quietly hide that.

## The sample problem, stated rather than hidden

A dozen calls over a few months is not evidence of skill in either direction.
Runs of five correct calls happen constantly by chance. Every summary here
reports `n` alongside the number and refuses to characterise a record below
`MIN_SAMPLE`, because the single most likely way this feature does harm is by
letting a good quarter be read as a good process.
"""
from __future__ import annotations

import re

from collections import defaultdict
from datetime import datetime, timedelta

from . import performance, prices

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id         INTEGER PRIMARY KEY,
    date       TEXT NOT NULL,              -- the day the call was made
    symbol     TEXT NOT NULL,
    source     TEXT NOT NULL,              -- 'app' (a verdict) or 'me' (a decision)
    action     TEXT NOT NULL,              -- buy | add | hold | trim | sell
    timeframe  TEXT,                       -- D or W, for app rows
    price      REAL,                       -- price when the call was made
    confidence TEXT,
    flip       REAL,                       -- the level that would invalidate it
    rationale  TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- App verdicts are written by a nightly job that must be safe to re-run, so one
-- symbol/timeframe gets at most one row per day. User decisions carry no such
-- constraint: two trades in one name on one day is a real thing that happens.
CREATE UNIQUE INDEX IF NOT EXISTS ux_decisions_app
    ON decisions (date, symbol, timeframe) WHERE source = 'app';
-- Replayed verdicts: the engine run at past dates on the bars it would have
-- had then. Same shape as 'app', kept under its own source so the live
-- journal — calls made before the outcome was known — is never mixed with
-- calls reconstructed afterwards, however honestly the bars were truncated.
CREATE UNIQUE INDEX IF NOT EXISTS ux_decisions_replay
    ON decisions (date, symbol, timeframe) WHERE source = 'replay';
-- The same engine replayed on the liquidity screen's universe rather than
-- the watchlist: names chosen for trading enough, not for having gone up.
CREATE UNIQUE INDEX IF NOT EXISTS ux_decisions_replay_screen
    ON decisions (date, symbol, timeframe) WHERE source = 'replay-screen';
-- The engine with a two-close confirmation gate, replayed on the watchlist
-- to be measured against the one-close 'replay' rows on the same dates.
CREATE UNIQUE INDEX IF NOT EXISTS ux_decisions_replay_confirm2
    ON decisions (date, symbol, timeframe) WHERE source = 'replay-confirm2';
CREATE INDEX IF NOT EXISTS ix_decisions_symbol ON decisions (symbol, date);
-- "What did the app last say about this name" (outlook._prior) is asked
-- twice per symbol per run. On (symbol, date) alone that walks every replay
-- row for the symbol — 1,700 of them — before finding no app row at all,
-- which is the usual answer for a watchlist name. Partial on the source.
CREATE INDEX IF NOT EXISTS ix_decisions_app_prior
    ON decisions (symbol, timeframe, date) WHERE source = 'app';

-- One row per piece of evidence behind a recorded verdict.
--
-- `rationale` holds the same thing as prose, which is readable and useless for
-- attribution: asking "do the calls citing a flipped level do better than the
-- ones citing only Fibonacci" against a joined sentence means substring
-- matching on wording that changes whenever the wording changes. Answering
-- which CONDITIONS earn their place — the only question that says what to
-- tweak — needs them stored one per row.
--
-- This cannot be backfilled. A verdict recorded without its evidence is
-- permanently unattributable, so the table exists before there is anything to
-- ask of it.
CREATE TABLE IF NOT EXISTS decision_evidence (
    decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,      -- 'ichimoku', 'level', 'trendline', ...
    stance      TEXT,               -- bull | bear | extended | NULL for context
    weight      REAL NOT NULL DEFAULT 1.0,
    detail      TEXT,
    PRIMARY KEY (decision_id, name, stance)
);
-- There used to be an index on (name, stance) here. Nothing queries the
-- table that way — every reader asks for one decision's rows, which the
-- primary key serves — and on 4.8 million replayed rows it cost ~150 MB
-- and a second write per row. Dropped 2026-09-04; ensure_schema removes it
-- from databases that still carry it.
DROP INDEX IF EXISTS ix_devidence_name;

-- Decisions derived from trades you actually made, one per symbol per day.
-- Separate from 'me' (a call logged by hand without trading) so the two are
-- never confused: what you did and what you thought are different records.
CREATE UNIQUE INDEX IF NOT EXISTS ux_decisions_trade
    ON decisions (date, symbol) WHERE source = 'trade';
"""

# Calls made by OTHER people — the accounts the user follows on X. Same table,
# same grading, under their own source and with the author on the row, so
# "whose calls have actually held up" is a query rather than a memory. One
# row per author per symbol per day, so re-seeding a chart is safe.
OUTSIDE_SCHEMA = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_decisions_outside
    ON decisions (date, symbol, author) WHERE source = 'outside';
"""

# Kinds that represent a DECISION. Deliberately narrow.
#
# A reinvested dividend is the broker following a standing instruction, not a
# view taken on a Tuesday; a corporate action is something done TO the position;
# an exchange is an internal move. Logging any of them would flood the journal
# with non-decisions and quietly wreck the comparison against the app, because
# this ledger holds 103 reinvestments and 7 corporate actions against the trades
# that were actually chosen.
DECISION_KINDS = ("buy", "sell")

# Below this share of the position, a sale is a trim rather than an exit.
EXIT_THRESHOLD = 0.90

# Horizons a call is graded over. A swing-trading book is not judged on one day
# and is not held for five years.
HORIZONS = (5, 21, 63)

# Below this, a record is reported but never characterised as good or bad.
MIN_SAMPLE = 20

SIGN = {"buy": 1.0, "add": 1.0, "hold": 1.0, "trim": -0.5, "sell": -1.0}


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    # The human half of a decision. `bucket` is which book the position is in
    # — swing, conviction, trade-around — and is set when the call is made;
    # `tag` is what happened, set afterwards. Both exist so calibration can
    # slice your own record by them, which is what turns a list of trades
    # into a finding about how you trade. Added as columns rather than a new
    # table so a decision and its reasons can never drift apart.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(decisions)")}
    for col in ("bucket", "tag", "author"):
        if col not in cols:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {col} TEXT")
    # The index refers to `author`, so it can only exist once the column does.
    conn.executescript(OUTSIDE_SCHEMA)


BUCKETS = ("swing", "conviction", "trade-around")
# What happened, in the user's own words, chosen from a short list so the
# slices have enough calls in them to say anything.
TAGS = ("followed the plan", "chased", "held through the stop", "sold too early",
        "sized wrong", "other")


def set_bucket(conn, decision_id: int, bucket: str | None) -> dict:
    ensure_schema(conn)
    if bucket and bucket not in BUCKETS:
        return {"error": f"unknown bucket {bucket!r}", "allowed": list(BUCKETS)}
    conn.execute("UPDATE decisions SET bucket=? WHERE id=? AND source IN ('me','trade')",
                 (bucket or None, decision_id))
    return {"ok": True, "id": decision_id, "bucket": bucket}


def set_tag(conn, decision_id: int, tag: str | None) -> dict:
    ensure_schema(conn)
    if tag and tag not in TAGS:
        return {"error": f"unknown tag {tag!r}", "allowed": list(TAGS)}
    conn.execute("UPDATE decisions SET tag=? WHERE id=? AND source IN ('me','trade')",
                 (tag or None, decision_id))
    return {"ok": True, "id": decision_id, "tag": tag}


# One spelling per person. The same handle was journaled as "GreatMattsby"
# and "The Great Mattsby", "1ChartMaster" and "Elite Swing Traders", and
# StonkChris under three names, so one call became two rows and the record
# double-counted. The @handle inside the string is the identity; the display
# name is whichever was seeded first for it, or the one fixed here.
CANONICAL_AUTHORS = {
    "stonkchris": "StonkChris (@StonkChris)",
    "greatmattsby": "GreatMattsby (@GreatMattsby)",
    "1chartmaster": "1ChartMaster (@1ChartMaster)",
    "denebulord": "DeNebulord (@DeNebulord)",
    "mr_derivatives": "Mr Derivatives (@Mr_Derivatives)",
}


# Followed for what they find and explain, never for a buy, sell or trim: the
# user said so of Serenity ("great for fundamentals and finding stocks but
# should not be taken into account for buys, sells, and trims"). Their posts
# go to the idea notes; record() refuses them so nothing of theirs is graded
# or counted as a confirmation.
IDEAS_ONLY_AUTHORS = {"aleabitoreddit"}


def ideas_only(author: str | None) -> bool:
    m = re.search(r"@([A-Za-z0-9_]+)", author or "")
    return bool(m) and m.group(1).lower() in IDEAS_ONLY_AUTHORS


def canonical_author(author: str | None) -> str:
    a = (author or "").strip()
    m = re.search(r"@([A-Za-z0-9_]+)", a)
    if not m:
        return a
    return CANONICAL_AUTHORS.get(m.group(1).lower(), a)


def record(conn, date: str, symbol: str, source: str, action: str,
           price: float | None = None, timeframe: str | None = None,
           confidence: str | None = None, flip: float | None = None,
           rationale: str | None = None,
           evidence: list[dict] | None = None,
           bucket: str | None = None,
           author: str | None = None) -> int | None:
    """Write one call. App rows replace the same day's row; user rows never do.

    An `outside` row is somebody else's call — the account the user follows —
    and needs an author; one per author per symbol per day, replaced on a
    re-record so seeding the same chart twice does not double-count it."""
    ensure_schema(conn)
    symbol = symbol.strip().upper()
    if action not in SIGN:
        raise ValueError(f"unknown action {action!r}")
    if bucket and bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}")
    if source == "outside":
        author = canonical_author(author)
        if not author:
            raise ValueError("an outside call needs an author")
        if ideas_only(author):
            return None          # ideas, not calls: nothing to grade
        conn.execute(
            """INSERT INTO decisions (date, symbol, source, action, timeframe,
                                      price, confidence, flip, rationale, author)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (date, symbol, author) WHERE source = 'outside'
               DO UPDATE SET action=excluded.action, price=excluded.price,
                             flip=excluded.flip, rationale=excluded.rationale,
                             timeframe=excluded.timeframe""",
            (date, symbol, source, action, timeframe, price, confidence, flip, rationale, author))
        row = conn.execute(
            "SELECT id FROM decisions WHERE source='outside' AND date=? AND symbol=? AND author=?",
            (date, symbol, author)).fetchone()
        return row["id"] if row else None
    if source == "trade":
        # Re-deriving from the ledger must be safe to run on every import, and a
        # plain INSERT raised IntegrityError on the second pass against the
        # partial unique index — so update.sh would have failed every night
        # after the first. Only a hand-logged 'me' row may repeat in a day.
        conn.execute(
            """INSERT INTO decisions (date, symbol, source, action, timeframe,
                                      price, confidence, flip, rationale)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (date, symbol) WHERE source = 'trade'
               DO UPDATE SET action=excluded.action, price=excluded.price,
                             rationale=excluded.rationale""",
            (date, symbol, source, action, timeframe, price, confidence, flip, rationale))
        row = conn.execute(
            "SELECT id FROM decisions WHERE source='trade' AND date=? AND symbol=?",
            (date, symbol)).fetchone()
        did = row["id"] if row else None
        if did is not None:
            _save_evidence(conn, did, evidence)
        return did

    if source in ("app", "replay", "replay-screen", "replay-confirm2"):
        if source in MEASURED_ONLY:
            rationale = None
        conn.execute(
            f"""INSERT INTO decisions (date, symbol, source, action, timeframe,
                                       price, confidence, flip, rationale)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT (date, symbol, timeframe) WHERE source = '{source}'
                DO UPDATE SET action=excluded.action, price=excluded.price,
                              confidence=excluded.confidence, flip=excluded.flip,
                              rationale=excluded.rationale""",
            (date, symbol, source, action, timeframe, price, confidence, flip, rationale))
        row = conn.execute(
            """SELECT id FROM decisions WHERE source=? AND date=? AND symbol=?
               AND timeframe IS ?""", (source, date, symbol, timeframe)).fetchone()
        did = row["id"] if row else None
        if did is not None:
            _save_evidence(conn, did, evidence, keep_detail=source not in MEASURED_ONLY)
        return did
    cur = conn.execute(
        """INSERT INTO decisions (date, symbol, source, action, timeframe,
                                  price, confidence, flip, rationale, bucket)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (date, symbol, source, action, timeframe, price, confidence, flip, rationale, bucket))
    _save_evidence(conn, cur.lastrowid, evidence)
    return cur.lastrowid


# Sources whose evidence is measured, never read: the replays. Their rows
# keep name, stance and weight — everything measure.py and calibration.py
# ask for — and no sentence of detail. 4.8 million replayed evidence rows
# each carrying ~84 characters of prose nobody read is how the database
# reached 1.2 GB on 2026-09-04 with seven thousand transactions in it.
MEASURED_ONLY = ("replay", "replay-screen", "replay-confirm2")


def _save_evidence(conn, decision_id: int, evidence: list[dict] | None,
                   keep_detail: bool = True) -> None:
    """Replace the stored evidence for one decision.

    Replaced rather than appended because the nightly job re-records the same
    day's verdict on a re-run, and appending would let one day's call accumulate
    duplicate conditions and count double in every attribution query.
    """
    if evidence is None:
        return
    conn.execute("DELETE FROM decision_evidence WHERE decision_id = ?", (decision_id,))
    seen = set()
    for e in evidence:
        key = (e.get("name"), e.get("stance"))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        conn.execute(
            """INSERT INTO decision_evidence (decision_id, name, stance, weight, detail)
               VALUES (?,?,?,?,?)""",
            (decision_id, key[0], key[1], float(e.get("weight") or 1.0),
             ((e.get("detail") or "")[:400] if keep_detail else None)))


def derive_from_trades(conn) -> dict:
    """Turn the trades in the ledger into decisions, so what you DID is recorded.

    The journal could only ever compare the app against calls logged by hand,
    which meant comparing it against almost nothing. Every buy and sell already
    sitting in the ledger is a decision made on a date before the outcome was
    known — the same standard the app's own verdicts are held to, and a far
    larger sample than anybody will type in.

    Multiple fills of one order on one day are ONE decision. Four partial fills
    are not four opinions, and counting them as four would weight a single view
    four times in every average.

    A sale is classified against the position it came out of: taking most of it
    off is a `sell`, taking a slice is a `trim`. That distinction is the whole
    reason `trim` exists as a separate verdict, so a journal that recorded every
    disposal as a sell could never tell whether the app's trims were any good.
    """
    ensure_schema(conn)
    rows = conn.execute(
        f"""SELECT t.txn_date, s.symbol, t.kind, t.quantity, t.price
              FROM transactions t JOIN securities s ON s.id = t.security_id
             WHERE t.kind IN ({','.join('?' * len(DECISION_KINDS))})
               AND t.quantity IS NOT NULL
             ORDER BY t.txn_date, s.symbol""", DECISION_KINDS).fetchall()

    # Net each symbol-day, and track the running position so a sale can be
    # judged against what was held BEFORE it.
    byday: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["txn_date"], (r["symbol"] or "").strip().upper())
        if not key[1]:
            continue
        d = byday.setdefault(key, {"qty": 0.0, "value": 0.0, "shares": 0.0})
        q = r["quantity"] or 0.0
        d["qty"] += q
        if r["price"]:
            d["value"] += abs(q) * r["price"]
            d["shares"] += abs(q)

    held: dict[str, float] = defaultdict(float)
    written, skipped = 0, 0
    for (day, sym), d in sorted(byday.items()):
        before = held[sym]
        held[sym] += d["qty"]
        # A day that bought and sold the same amount is not a decision either
        # way; nothing about the position changed.
        if abs(d["qty"]) < 1e-9:
            skipped += 1
            continue
        px = (d["value"] / d["shares"]) if d["shares"] else None
        if d["qty"] > 0:
            action = "add" if before > 1e-9 else "buy"
        else:
            sold = abs(d["qty"])
            action = "sell" if (before <= 1e-9 or sold / before >= EXIT_THRESHOLD) else "trim"
        record(conn, day, sym, "trade", action, price=px,
               rationale=f"derived from {action} of {abs(d['qty']):.4f} shares")
        written += 1
    conn.commit()
    return {"decisions": written, "skipped_flat_days": skipped,
            "symbols": len({k[1] for k in byday})}


def cross_check(conn, horizon: int = 21, window_days: int = 5) -> dict:
    """For each trade you made, what had the app been saying about that name?

    This is the comparison the journal was built for and could not run: not
    "does the app score well" but "when we disagreed, who was right".

    A verdict from the same day is preferred; failing that, the most recent one
    within `window_days`. Anything older is not what the app was saying at the
    time and is left unmatched rather than stretched to fit.
    """
    trades = [g for g in history(conn, source="trade", limit=5000)]
    out, agree, disagree = [], 0, 0
    for t in trades:
        v = conn.execute(
            """SELECT date, action, confidence FROM decisions
                WHERE source='app' AND symbol=? AND timeframe='D'
                  AND date <= ? AND date >= date(?, ?)
                ORDER BY date DESC LIMIT 1""",
            (t["symbol"], t["date"], t["date"], f"-{int(window_days)} days")).fetchone()
        if not v:
            out.append({**t, "app": None, "agreed": None})
            continue
        # Same DIRECTION rather than the same word: buy and add both mean
        # adding exposure, sell and trim both mean removing it, and grading
        # "add" against "buy" as a disagreement would manufacture conflict.
        side = lambda a: ("up" if a in ("buy", "add") else
                          "down" if a in ("sell", "trim") else "flat")
        same = side(t["action"]) == side(v["action"])
        agree += 1 if same else 0
        disagree += 0 if same else 1
        out.append({**t, "app": {"action": v["action"], "date": v["date"],
                                 "confidence": v["confidence"]},
                    "agreed": same})
    matched = agree + disagree
    return {
        "trades": len(trades), "matched": matched,
        "agreed": agree, "disagreed": disagree,
        "agreement_rate": (agree / matched) if matched else None,
        "rows": out[:200],
        "note": ("No trade yet falls within a few days of a recorded verdict. "
                 "The app only began recording on 2026-09-01, so this fills in "
                 "as you trade from here."
                 if not matched else
                 f"{agree} of {matched} trades pointed the same way as the app's "
                 f"most recent verdict on that name. Agreement is not accuracy — "
                 f"the scorecard says which of you was right."),
    }


def _plus(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def _price_at(conn, symbol: str, when: str, cache: dict):
    if symbol not in cache:
        cache[symbol] = (prices.load_series(conn, symbol), prices.sorted_dates(conn, symbol))
    series, dates = cache[symbol]
    if not series or not dates:
        return None
    return performance.last_known_price(series, when, dates)


def _prefill(conn, rows: list[dict], cache: dict) -> None:
    """Load each symbol's prices once per batch, and only from the first date
    the batch needs.

    Grading is a handful of lookups per call — the entry date and a few
    horizons — but every symbol's whole series was being loaded to make
    them: 120 symbols, 2,000 rows each, a third of a second on /api/research
    to read five closes apiece. The window starts at the last bar on or
    before the earliest call on that symbol, so every lookup after it reads
    exactly what the full series would have given.
    """
    # A shared cache outlives one batch, and a later batch can need an
    # earlier date on a symbol already loaded — the window is then widened,
    # never trusted as is: a date before the window's floor would read as
    # "no price" rather than as the bar that exists before it.
    covers = cache.setdefault("\x00since", {})       # symbol -> window floor
    first: dict[str, str] = {}
    for r in rows:
        for sym in (r["symbol"], "SPY"):
            if sym in covers and covers[sym] <= r["date"]:
                continue
            if sym not in first or r["date"] < first[sym]:
                first[sym] = r["date"]
    for sym, since in first.items():
        cache[sym] = prices.load_closes_since(conn, sym, since)
        covers[sym] = since


def grade(conn, row: dict, cache: dict | None = None) -> dict:
    """One call, scored at every horizon that has actually elapsed."""
    cache = cache if cache is not None else {}
    symbol = row["symbol"]
    entry = row["price"] or _price_at(conn, symbol, row["date"], cache)
    bench_entry = _price_at(conn, "SPY", row["date"], cache)
    today = datetime.now().strftime("%Y-%m-%d")
    out = {"id": row["id"], "date": row["date"], "symbol": symbol,
           "source": row["source"], "action": row["action"],
           "timeframe": row["timeframe"], "entry": entry,
           "confidence": row["confidence"], "flip": row["flip"],
           "rationale": row["rationale"], "bucket": row.get("bucket"),
           "tag": row.get("tag"), "author": row.get("author"), "horizons": {}}

    for h in HORIZONS:
        # Calendar days, then the last known bar on or before that date — a
        # horizon that lands on a weekend must not silently score as missing.
        when = _plus(row["date"], int(h * 7 / 5))
        if when > today:
            out["horizons"][h] = {"status": "open",
                                  "note": f"{h} trading days from {row['date']} "
                                          f"has not elapsed yet"}
            continue
        px = _price_at(conn, symbol, when, cache)
        bpx = _price_at(conn, "SPY", when, cache)
        if px is None or entry in (None, 0):
            out["horizons"][h] = {"status": "no price"}
            continue
        ret = px / entry - 1
        bench = (bpx / bench_entry - 1) if bpx and bench_entry else None
        excess = (ret - bench) if bench is not None else None
        score = (SIGN[row["action"]] * excess) if excess is not None else None
        out["horizons"][h] = {
            "status": "scored", "asof": when, "price": round(px, 4),
            "return": round(ret, 4),
            "benchmark": (round(bench, 4) if bench is not None else None),
            "excess": (round(excess, 4) if excess is not None else None),
            "score": (round(score, 4) if score is not None else None),
            "right": (score > 0) if score is not None else None,
        }
    return out


def history(conn, symbol: str | None = None, source: str | None = None,
            limit: int = 200, author: str | None = None,
            cache: dict | None = None) -> list[dict]:
    """Recorded calls, newest first, each graded. `cache` lets one request
    share loaded prices across several history() calls (outside_record makes
    fifty-odd of them)."""
    ensure_schema(conn)
    where, args = [], []
    if symbol:
        where.append("symbol = ?")
        args.append(symbol.strip().upper())
    if source:
        where.append("source = ?")
        args.append(source)
    if author:
        where.append("author = ?")
        args.append(author)
    sql = "SELECT * FROM decisions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date DESC, id DESC LIMIT ?"
    args.append(limit)
    rows = [dict(r) for r in conn.execute(sql, args)]
    cache = cache if cache is not None else {}
    _prefill(conn, rows, cache)
    return [grade(conn, r, cache) for r in rows]


def scorecard(conn, source: str | None = None, horizon: int = 21,
              author: str | None = None, cache: dict | None = None) -> dict:
    """How the calls from one source (or one outside author) have actually done."""
    graded = [g for g in history(conn, source=source, limit=2000, author=author, cache=cache)]
    scored = [g for g in graded
              if g["horizons"].get(horizon, {}).get("status") == "scored"]
    n = len(scored)
    by_action: dict[str, list[float]] = {}
    for g in scored:
        by_action.setdefault(g["action"], []).append(g["horizons"][horizon]["score"])

    mean = (sum(g["horizons"][horizon]["score"] for g in scored) / n) if n else None
    hits = sum(1 for g in scored if g["horizons"][horizon]["right"])

    if n == 0 and graded:
        # "0 graded calls" next to a full list of recorded ones reads as broken.
        # It is not broken, it is early, and the difference is a date.
        soonest = min(g["date"] for g in graded)
        lands = _plus(soonest, int(horizon * 7 / 5))
        verdict = (f"{len(graded)} call{'s' if len(graded) != 1 else ''} recorded, "
                   f"none old enough to grade. A call is scored {horizon} trading "
                   f"days after it was made, so the earliest one here "
                   f"({soonest}) is first scored on {lands}.")
    elif n == 0:
        verdict = "No call from this source has been recorded yet."
    elif n < MIN_SAMPLE:
        verdict = (f"{n} graded call{'s' if n != 1 else ''} — far too few to say "
                   f"anything about the process. Runs of five in a row happen by "
                   f"chance constantly; {MIN_SAMPLE} is the point this starts "
                   f"reporting a characterisation rather than just the arithmetic.")
    elif mean and mean > 0:
        verdict = (f"Across {n} calls the average added {mean * 100:.2f} points "
                   f"against SPY over {horizon} trading days. That is a real "
                   f"record on a small sample, not an established edge.")
    else:
        verdict = (f"Across {n} calls the average cost {abs(mean or 0) * 100:.2f} "
                   f"points against SPY over {horizon} trading days.")

    return {
        "source": source or "all", "horizon": horizon, "n": n,
        "hit_rate": (hits / n) if n else None,
        "mean_score": (round(mean, 4) if mean is not None else None),
        "by_action": {a: {"n": len(v), "mean": round(sum(v) / len(v), 4)}
                      for a, v in sorted(by_action.items())},
        "open": len(graded) - n,
        "recorded": len(graded),
        "first_grade_on": (_plus(min(g["date"] for g in graded), int(horizon * 7 / 5))
                           if graded and n == 0 else None),
        "min_sample": MIN_SAMPLE,
        "verdict": verdict,
        "caveats": [
            "Graded against SPY over the same dates, so a call that made money in "
            "a month the index made more is scored as the loss it was.",
            "Hold is graded, not skipped — keeping a position is a decision, and a "
            "journal that only graded trades would hide the bad holds.",
            "No dividends, costs or taxes. A trim or sell scored positively here "
            "still cost something to make.",
        ],
    }


def remove_outside(conn, decision_id: int) -> dict:
    """Delete one outside call. Only outside rows: the app's own record and
    the user's trades are never deleted through this path."""
    ensure_schema(conn)
    cur = conn.execute("DELETE FROM decisions WHERE id=? AND source='outside'", (decision_id,))
    return {"ok": cur.rowcount == 1, "id": decision_id, "removed": cur.rowcount}


def outside_authors(conn) -> list[str]:
    ensure_schema(conn)
    return [r["author"] for r in conn.execute(
        "SELECT author, COUNT(*) n FROM decisions WHERE source='outside' "
        "GROUP BY author ORDER BY n DESC, author")]


def outside_record(conn, horizon: int = 21) -> dict:
    """Every followed account's calls, graded the way the app's own are.

    The same yardstick — the symbol against SPY over the same dates, signed by
    what the call claimed — and the same refusal to characterise a small
    sample. What this adds is the per-author cut: which of the people whose
    charts get saved have calls that held up, and which have not."""
    ensure_schema(conn)
    authors = []
    cache: dict = {}          # prices loaded once for every author's calls
    for a in outside_authors(conn):
        sc = scorecard(conn, "outside", horizon, author=a, cache=cache)
        calls = history(conn, source="outside", author=a, limit=500, cache=cache)
        authors.append({"author": a, "n": sc["n"], "hit_rate": sc["hit_rate"],
                        "mean_score": sc["mean_score"], "open": sc["open"],
                        "recorded": sc["recorded"], "verdict": sc["verdict"],
                        "first_grade_on": sc["first_grade_on"], "calls": calls})
    overall = scorecard(conn, "outside", horizon, cache=cache)
    return {"horizon": horizon, "authors": authors, "overall": overall,
            "min_sample": MIN_SAMPLE, "actions": sorted(SIGN)}


def compare(conn, horizon: int = 21) -> dict:
    """The app's calls against your own, on the same yardstick.

    "Yours" means trades actually made, derived from the ledger, rather than
    calls typed in by hand — there are hundreds of the former and almost none
    of the latter, and what you DID is the honest comparison anyway.
    """
    app, me = scorecard(conn, "app", horizon), scorecard(conn, "trade", horizon)
    both = [s for s in (app, me) if s["n"] >= MIN_SAMPLE]
    if len(both) < 2:
        note = ("Not enough graded calls on both sides to compare yet. This "
                "becomes answerable once each source has "
                f"{MIN_SAMPLE} scored calls.")
    else:
        gap = (app["mean_score"] or 0) - (me["mean_score"] or 0)
        note = (f"The app's calls are running {abs(gap) * 100:.2f} points "
                f"{'ahead of' if gap > 0 else 'behind'} your own over "
                f"{horizon} trading days.")
    return {"app": app, "me": me, "note": note}
