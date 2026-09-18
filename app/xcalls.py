"""Read the followed accounts' calls out of the nightly X pull, and keep them.

    python3 -m app.xcalls                          # every pull on disk
    python3 -m app.xcalls research/x/pulls/2026-09-13.json
    python3 -m app.xcalls --dry-run                # show, write nothing

## Why this exists

The calls of the people the user follows were graded only when somebody sat
down with a pull file and wrote research/x/calls/<date>.json by hand
(seed-x-calls.py). That happened twice. The user on 2026-09-13: "we should be
keeping a record of calls made by who I follow and how they are doing. It has
to be going forward, so if they delete old posts the numbers aren't skewed."

So the record is written the night the post is pulled, from the pull file the
app keeps on disk, into the journal the app already grades. A post deleted
from X afterwards changes nothing here: the tweet id, the day, the name, the
call and the words are ours from that night on. Nothing is ever backfilled
from a feed that a poster can edit.

## What counts as a call

A post that names ONE OR TWO tickers as cashtags and says, in words this
module recognises, that the poster is long, buying, or expects higher — or
short, selling, trimming, or expects lower first. A post that only mentions a
name ("nice week for $SYM") is a mention, counted by x-mentions.py, and is not
a call; a post that says both things is ambiguous and is skipped rather than
guessed. The matched words are kept in the rationale so a wrong reading can be
seen and removed with the × on the graded table.

A reading of text is not a reading of a chart image, and the accounts that
post charts with no words are invisible to this. That is a floor on the
record, and the graded table says how many calls came from here.

A hand-recorded call for the same author, name and day is never overwritten
by an automatic one.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from . import journal, prices
from .ledger import connect

ROOT = Path(__file__).resolve().parent.parent
PULL_DIR = ROOT / "research" / "x" / "pulls"

# The words. Each pattern is a claim about the NEXT MOVE, which is what the
# journal grades. "bottomed" and "higher low" are buys because that is the
# claim they make; "lower first" and "wait for a pullback" are sells for the
# same reason, the rule every seed has used.
BUY_WORDS = re.compile(
    r"\b(bought|buying|buy(?:s|ing)? (?:zone|here|the dip|more|back)|added|adding|accumulat(?:e|ed|ing)|"
    r"long(?:ed|ing)?|starter position|nibbl\w*|scal(?:e|ing) in|bottom(?:ed|ing)|"
    r"higher low|breaking out|breakout|reclaim(?:ed|ing|s)?|looks? (?:great|strong|ready)|"
    r"re-?enter(?:ed|ing)?|going higher|new highs? (?:coming|ahead|next)|"
    r"buy zone|entry (?:zone|here)|dip buy|be a buyer)\b", re.I)
SELL_WORDS = re.compile(
    r"\b(sold|selling|sell(?:ing)? (?:here|into|some|half|the rip)|trim(?:med|ming|s)?|"
    r"t(?:ake|aking|ook) (?:some )?profits?|short(?:ed|ing|s)?|lower first|wait for (?:a )?(?:lower|pullback|dip)|"
    r"pull ?back (?:first|coming|likely|next)|topp(?:ed|ing)|overextended|rejected|rejection|"
    r"breaking down|breakdown|lower high|going lower|cut(?:ting)? (?:it|the loss)|stopped out|"
    r"exit(?:ed|ing)? (?:the|my|this|here)|no longer (?:hold|own))\b", re.I)
# A claim has to be made near the name. "Adding presets to the app … this
# $NVDA base" is not a call on NVDA; the word and the cashtag are far apart.
NEAR = 90
# Things a cashtag is not: crypto, indices and the words people write with a
# dollar sign in front.
NOT_TICKERS = {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "SPX", "NDX", "VIX", "DXY", "USD",
               "K", "M", "B", "T"}
CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")
# A price beside a level word: "buy zone 12-14", "target $20", "support at 46".
PRICE = re.compile(r"\$?(\d{1,5}(?:\.\d{1,2})?)\s*(?:-|–|to)\s*\$?(\d{1,5}(?:\.\d{1,2})?)|\$?(\d{1,5}(?:\.\d{1,2})?)")
LEVEL_WORDS = re.compile(r"\b(zone|target|support|resistance|at|above|below|under|over|to)\b", re.I)


def iso_date(raw: str) -> str:
    raw = (raw or "").strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    try:
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").date().isoformat()
    except ValueError:
        return ""


def read(text: str) -> dict | None:
    """One post → {symbols, action, words, level} or None when it is not a call."""
    tickers, spots = [], []
    for m in CASHTAG.finditer(text or ""):
        t = m.group(1)
        if t not in NOT_TICKERS and t not in tickers:
            tickers.append(t)
            spots.append(m.start())
    if not tickers or len(tickers) > 2:
        return None
    near = lambda m: any(abs(m.start() - s) <= NEAR for s in spots)  # noqa: E731
    buys = [m.group(0).lower() for m in BUY_WORDS.finditer(text) if near(m)]
    sells = [m.group(0).lower() for m in SELL_WORDS.finditer(text) if near(m)]
    if bool(buys) == bool(sells):
        return None                      # nothing said, or both things said
    action = "buy" if buys else "sell"
    words = sorted(set(buys or sells))
    level = None
    # The first price that follows a level word is the level; a bare number
    # ("up 20%") is not.
    for m in LEVEL_WORDS.finditer(text):
        tail = text[m.end():m.end() + 24]
        p = PRICE.search(tail)
        if p and p.start() <= 3 and not tail[p.end():p.end() + 1] == "%":
            level = float(p.group(3) or p.group(1))
            break
    return {"symbols": tickers, "action": action, "words": words, "level": level}


def author_for(conn, handle: str) -> str:
    """The name the journal already files this handle under, so the automatic
    calls land in the same row of the graded table as the hand-seeded ones."""
    canon = journal.canonical_author(f"@{handle}")
    if not canon.startswith("@"):
        return canon
    row = conn.execute("""SELECT author FROM decisions WHERE source='outside'
                          AND lower(author) LIKE ? ORDER BY id DESC LIMIT 1""",
                       (f"%(@{handle.lower()})",)).fetchone()
    return row["author"] if row else f"{handle} (@{handle})"


def ensure_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS x_calls (
        tweet_id TEXT NOT NULL, handle TEXT NOT NULL, symbol TEXT NOT NULL,
        date TEXT NOT NULL, action TEXT NOT NULL, decision_id INTEGER,
        note TEXT, seen_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (tweet_id, symbol))""")


def _close_on(conn, symbol: str, day: str, cache: dict) -> float | None:
    if symbol not in cache:
        try:
            series = prices.load_series(conn, symbol)
            if not series:
                prices.ensure_symbol(conn, symbol, "2024-01-01", "2100-01-01", as_equity=True)
                conn.commit()
                series = prices.load_series(conn, symbol)
        except Exception:                                      # noqa: BLE001
            series = {}
        cache[symbol] = series
    dates = [d for d in cache[symbol] if d <= day]
    return cache[symbol][max(dates)] if dates else None


def seed(conn, pull: dict, dry_run: bool = False, log=None) -> dict:
    """Record every call in one pull file, once per tweet id."""
    ensure_schema(conn)
    say = log or (lambda *_: None)
    seen = {(r["tweet_id"], r["symbol"]) for r in conn.execute("SELECT tweet_id, symbol FROM x_calls")}
    cache: dict = {}
    n_calls = n_posts = n_kept = 0
    for handle, posts in (pull.get("tweets") or {}).items():
        author = author_for(conn, handle)
        if journal.ideas_only(author):
            continue
        for p in posts or []:
            n_posts += 1
            call = read(p.get("text") or "")
            if not call:
                continue
            day = iso_date(p.get("date") or "")
            if not day:
                continue
            for sym in call["symbols"]:
                if (str(p.get("id")), sym) in seen:
                    continue
                n_calls += 1
                note = f"[auto: {', '.join(call['words'])}] {(p.get('text') or '')[:260]}"
                say(f"  {day} {author:<34} {sym:<6} {call['action']:<4} {call['level'] or '':>8}  {note[:90]}")
                if dry_run:
                    n_kept += 1
                    continue
                # A hand-recorded call for the same author, name and day wins.
                have = conn.execute(
                    """SELECT id, confidence FROM decisions WHERE source='outside'
                       AND date=? AND symbol=? AND author=?""", (day, sym, author)).fetchone()
                if have and have["confidence"] != "auto":
                    did = have["id"]
                else:
                    did = journal.record(conn, day, sym, "outside", call["action"],
                                         price=_close_on(conn, sym, day, cache), flip=call["level"],
                                         rationale=note, author=author, confidence="auto")
                conn.execute("""INSERT OR IGNORE INTO x_calls (tweet_id, handle, symbol, date, action, decision_id, note)
                                VALUES (?,?,?,?,?,?,?)""",
                             (str(p.get("id")), handle, sym, day, call["action"], did, note[:300]))
                seen.add((str(p.get("id")), sym))
                n_kept += 1
    if not dry_run:
        conn.commit()
    return {"posts": n_posts, "calls": n_calls, "recorded": n_kept}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pulls", nargs="*", help="pull files; default every one on disk")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    files = [Path(p) for p in args.pulls] or sorted(PULL_DIR.glob("*.json"))
    conn = connect()
    total = {"posts": 0, "calls": 0, "recorded": 0}
    for f in files:
        try:
            pull = json.loads(f.read_text())
        except (ValueError, OSError) as exc:
            print(f"{f}: {exc}")
            continue
        print(f"{f.name}:")
        r = seed(conn, pull, dry_run=args.dry_run, log=print)
        for k in total:
            total[k] += r[k]
    print(f"{total['posts']} posts read, {total['calls']} calls found, "
          f"{total['recorded']} {'would be ' if args.dry_run else ''}recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
