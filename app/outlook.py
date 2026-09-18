"""The daily pass: score every holding, record the call, and say what CHANGED.

    python3 -m app.outlook                 # score, record, print the change log
    python3 -m app.outlook --dry-run       # score and print, write nothing
    python3 -m app.outlook --symbol AMD    # one name, with the full evidence

## The thing this is actually for

Before this existed the app could state today's condition perfectly well and had
no memory of yesterday, so it could say "five of seven conditions met" and could
not say "it was six of seven on Friday and the volume condition just failed".
Every question worth asking daily is a question about the difference, so the
difference is what this prints.

Most days the honest output is "nothing changed". That is the point, and it is
why the change log is the output rather than a freshly-worded outlook every
morning: a report that reads differently each day when nothing happened trains
you to skim it, and then you miss the day something did.

## Cadence follows the bar, not the calendar

A daily verdict is recomputed every evening. A weekly verdict is recomputed only
when a weekly bar has actually closed, because re-scoring a weekly method on a
Tuesday measures a bar that is still being formed, and the result changes again
on Wednesday for no reason anybody would act on. Four fake changes a week is how
a change log becomes noise, and noise is indistinguishable from having no change
log at all.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

from . import config, holdings, journal, performance, prices, sentiment, verdicts, watchlist
from .ledger import connect

# A weekly bar is complete on the last trading day of its week. Friday, unless
# the market was shut, which the bar data itself is the authority on.
FRIDAY = 5

# ---------------------------------------------------------- verdict cache ----
# A verdict is a pure function of a name's bars and the market-wide context
# (sentiment, regime, the measured weights, its relative-strength rank). For
# a watchlist name — no position — nothing else goes in. So it is stored,
# keyed on the newest bar it was read from and a stamp of everything else,
# and the request path serves it back until a new bar lands. Scoring 189
# names inline was fifteen seconds of CPU on every cache miss; the nightly
# run warms this table (`--warm-watchlist`) so the page rarely scores at all.
#
# Held names are never cached here: their verdict carries the position, and
# they are scored by the nightly job in any case.
CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS verdict_cache (
    symbol      TEXT NOT NULL,
    scope       TEXT NOT NULL,
    prices_to   TEXT NOT NULL,      -- newest bar (own|proxy) the verdict read
    code_stamp  TEXT NOT NULL,      -- source mtime + hash of the run's context
    json        TEXT NOT NULL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, scope)
);
"""

# The newest source file at import. A verdict computed by older code must not
# be served by newer code, and this process cannot know what changed — only
# that something did.
SOURCE_STAMP = str(max((p.stat().st_mtime for p in Path(__file__).resolve().parent.glob("*.py")),
                       default=0.0))


def ensure_cache_schema(conn) -> None:
    conn.executescript(CACHE_SCHEMA)


def _context_stamp(market, measured, dial, index) -> str:
    """One hash for the run-wide inputs every verdict shares."""
    def plain(x):
        # Tuple keys (the measured profile is keyed by (name, stance)) are
        # not JSON; repr them. Only the digest matters, not the shape.
        if isinstance(x, dict):
            return {str(k): plain(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [plain(v) for v in x]
        return x
    blob = json.dumps(plain([SOURCE_STAMP, market, measured, dial, index]),
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _prices_to(conn, symbol: str, asof: str, proxies: dict) -> str | None:
    """The newest bar date a verdict on `symbol` would read, as a key.

    A primary-key seek per name, not the bars themselves — checking the cache
    has to cost less than the load it saves. A proxied name (SIVEF read from
    SIVE.ST) keys on both listings: the rescale factor comes from the last
    day both traded, so a new bar on either changes the verdict.
    """
    def newest(sym: str) -> str | None:
        sec = conn.execute("SELECT id FROM securities WHERE symbol = ?", (sym,)).fetchone()
        if not sec:
            return None
        return conn.execute(
            "SELECT MAX(bar_date) FROM prices WHERE security_id = ? AND bar_date <= ?",
            (sec["id"], asof)).fetchone()[0]
    own = newest(symbol)
    if not own:
        return None
    target = proxies.get(symbol)
    return f"{own}|{newest(target)}" if target else own


def cached_verdict(conn, symbol: str, scope: str, prices_to: str, stamp: str) -> dict | None:
    row = conn.execute(
        """SELECT json FROM verdict_cache
            WHERE symbol=? AND scope=? AND prices_to=? AND code_stamp=?""",
        (symbol, scope, prices_to, stamp)).fetchone()
    return json.loads(row["json"]) if row else None


def store_verdict(conn, symbol: str, scope: str, prices_to: str, stamp: str, both: dict) -> None:
    conn.execute(
        """INSERT INTO verdict_cache (symbol, scope, prices_to, code_stamp, json, computed_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(symbol, scope) DO UPDATE SET
             prices_to=excluded.prices_to, code_stamp=excluded.code_stamp,
             json=excluded.json, computed_at=excluded.computed_at""",
        (symbol, scope, prices_to, stamp, json.dumps(both, default=str),
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def _held(conn, asof: str) -> list[dict]:
    txns = performance.load_transactions(conn, "1900-01-01", asof, "investment")
    pos = holdings.positions(conn, txns, asof)
    return [p for p in pos
            if p["symbol"] != "CASH"
            and not prices.is_money_market(p["symbol"])
            and (p.get("quantity") or 0) > 0]


def _watched(conn, exclude: set[str]) -> list[str]:
    """Watchlist names that are not already held.

    The two lists answer different questions and are deliberately not merged: a
    holding asks "do I add, trim or get out", and a watchlist name asks "is this
    worth starting at all". Scoring a held name under both would also record two
    app verdicts for one symbol on one day, which the unique index forbids and
    which would double-count that name in every calibration bucket.
    """
    watchlist.ensure_schema(conn)
    return [r["symbol"] for r in
            conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")
            if r["symbol"] and r["symbol"].strip().upper() not in exclude]


def _iso_week(iso: str) -> tuple[int, int]:
    y, m, d = (int(x) for x in iso.split("-"))
    c = date(y, m, d).isocalendar()
    return (c[0], c[1])


def _should_score_weekly(conn, symbol: str, bars: list[dict], asof: str) -> bool:
    """Has a weekly bar closed that has not been scored yet?

    Two conditions, and both are needed. The week must be FINISHED — either
    `asof` is a Friday or later, or the last session this name actually traded
    falls in an earlier week, which is how a holiday-shortened week and a name
    that simply did not trade both close correctly without a calendar of market
    holidays.

    And it must not already have been scored. Without that second half an
    illiquid name whose last print was a week ago would re-record a "weekly"
    reading every single evening, which is precisely the fake-change noise this
    cadence exists to prevent.
    """
    if not bars:
        return False
    last = max((b["time"] for b in bars if b["time"] <= asof), default=None)
    if not last:
        return False
    y, m, d = (int(x) for x in asof.split("-"))
    finished = (date(y, m, d).isoweekday() >= FRIDAY
                or _iso_week(last) < _iso_week(asof))
    if not finished:
        return False
    journal.ensure_schema(conn)
    row = conn.execute(
        """SELECT date FROM decisions
           WHERE source='app' AND symbol=? AND timeframe='W' AND date <= ?
           ORDER BY date DESC LIMIT 1""", (symbol, asof)).fetchone()
    return not (row and _iso_week(row["date"]) == _iso_week(asof))


def _prior(conn, symbol: str, timeframe: str, before: str) -> dict | None:
    journal.ensure_schema(conn)
    row = conn.execute(
        """SELECT * FROM decisions
           WHERE source='app' AND symbol=? AND timeframe=? AND date < ?
           ORDER BY date DESC LIMIT 1""",
        (symbol, timeframe, before)).fetchone()
    return dict(row) if row else None


def run(conn, asof: str | None = None, symbols: list[str] | None = None,
        dry_run: bool = False, force_weekly: bool = False,
        scope: str = "held", use_cache: bool = False) -> dict:
    """Score `scope` (held, watchlist, all) as of `asof`.

    `use_cache` serves unheld names from verdict_cache when their newest bar
    and the run's context match, scores and stores the rest, and reports the
    split in `cache`. Held names are always scored live.
    """
    asof = asof or datetime.now().strftime("%Y-%m-%d")
    from . import books
    positions = {p["symbol"]: p for p in books.attach(conn, _held(conn, asof))}
    if symbols:
        wanted = [s.strip().upper() for s in symbols]
    elif scope == "watchlist":
        wanted = _watched(conn, set(positions))
    elif scope == "all":
        wanted = sorted(positions) + _watched(conn, set(positions))
    else:
        wanted = sorted(positions)

    # One reading for the whole run: every symbol scored on one evening must be
    # scored against the same market, and a per-symbol lookup would also mean a
    # network call per holding.
    market = sentiment.evidence(sentiment.latest(conn, asof))
    # The measured profile per timeframe, loaded once for the run.
    from . import measure
    measured = {tf: measure.load_profile(conn, tf) for tf in ("D", "W", "M")}
    changed, unchanged, skipped, results = [], [], [], {}
    # Relative strength is a rank across the LIST, so it is computed once for
    # everything scored tonight — held and watched together, whichever scope
    # is being scored, so a name's rank does not change with the tab.
    everything = sorted(set(positions) | set(_watched(conn, set())))
    ranks = watchlist.rs_ranks(conn, everything, asof)
    from . import regime
    dial = regime.reading(conn, asof)
    index = regime.index_read(conn, asof, measured.get("W"))
    hits = stored = 0
    if use_cache:
        ensure_cache_schema(conn)
        proxies = config.load().get("chart_proxy") or {}
        ctx_stamp = _context_stamp(market, measured, dial, index)

    for sym in wanted:
        pos = positions.get(sym)
        context = {"rs_rank": ranks.get(sym), "regime": dial, "index": index}
        both = key = None
        if use_cache and pos is None:
            key = _prices_to(conn, sym, asof, proxies)
            # The rank is per name, so it rides on the key rather than the
            # run-wide stamp.
            stamp = f"{ctx_stamp}:{ranks.get(sym)}"
            both = cached_verdict(conn, sym, scope, key, stamp) if key else None
        if both is not None:
            hits += 1
            proxy = both.get("proxy")
            # Enough of the bars for the weekly-cadence check below, which
            # reads only the last session's date.
            bars = [{"time": key.split("|")[0]}]
        else:
            bars, proxy = prices.analysis_bars(conn, sym, "2015-01-01", asof)
            bars = [b for b in bars if b["time"] <= asof]
            if len(bars) < 60:
                skipped.append({"symbol": sym, "why": f"{len(bars)} bars — too little history"})
                continue
            both = verdicts.both_timeframes(bars, pos, market, measured, context)
            both["proxy"] = proxy
            if use_cache and pos is None and key:
                try:
                    store_verdict(conn, sym, scope, key, stamp, both)
                    stored += 1
                except sqlite3.OperationalError:
                    # The nightly job holds the write lock: serve the verdict
                    # and cache it next time rather than fail the page.
                    pass
        results[sym] = both

        for tf, key in (("D", "daily"), ("W", "weekly")):
            v = both[key]
            if v.get("insufficient"):
                continue
            if tf == "W" and not (force_weekly or _should_score_weekly(conn, sym, bars, asof)):
                continue

            was = _prior(conn, sym, tf, asof)
            if not dry_run:
                journal.record(
                    conn, asof, sym, "app", v["verdict"], price=v.get("price"),
                    timeframe=tf, confidence=v.get("confidence"), flip=v.get("flip"),
                    rationale="; ".join(v.get("because", []))[:1000],
                    evidence=v.get("evidence"))
                if tf == "D":
                    # The levels this call named, kept so the intraday poll can
                    # compare a live price against them without re-scoring.
                    from . import alerts as _alerts
                    _alerts.store_levels(conn, asof, sym, v["verdict"],
                                         {**(v.get("watch") or {}), "flip": v.get("flip")})

            entry = {"symbol": sym, "timeframe": tf, "verdict": v["verdict"],
                     "proxy": proxy,
                     "confidence": v["confidence"], "price": v.get("price"),
                     "flip": v.get("flip"), "flip_note": v.get("flip_note"),
                     "because": v.get("because", []),
                     "value": (pos or {}).get("value"),
                     "from": (was or {}).get("action"),
                     "since": (was or {}).get("date")}
            if was is None:
                entry["kind"] = "new"
                changed.append(entry)
            elif was["action"] != v["verdict"]:
                entry["kind"] = "changed"
                changed.append(entry)
            else:
                entry["kind"] = "same"
                unchanged.append(entry)

    if not dry_run or stored:
        try:
            conn.commit()
        except sqlite3.OperationalError:
            if not dry_run:
                raise
            conn.rollback()           # only cache rows were pending

    # Biggest consequence first, the same ordering rule the Overview attention
    # list uses: a change on a $37k position outranks one on $2k, and sorting by
    # anything else buries the row that matters.
    changed.sort(key=lambda e: -(e.get("value") or 0))
    return {"asof": asof, "market": market, "index": index, "changed": changed, "unchanged": unchanged,
            "skipped": skipped, "results": results,
            "cache": {"hits": hits, "stored": stored} if use_cache else None,
            "counts": {"changed": len(changed), "unchanged": len(unchanged),
                       "skipped": len(skipped)}}


def _fmt(e: dict) -> str:
    tf = {"D": "daily", "W": "weekly"}[e["timeframe"]]
    head = (f"  {e['symbol']:<6} {tf:<7} "
            + (f"{e['from']} -> {e['verdict'].upper()}" if e["kind"] == "changed"
               else f"{e['verdict'].upper()} (first reading)"))
    if e.get("confidence"):
        head += f"  [{e['confidence']} confidence]"
    lines = [head]
    for r in e["because"][:3]:
        lines.append(f"         - {r}")
    if e.get("flip"):
        lines.append(f"         flips at {e['flip']:,.2f}"
                     + (f" — {e['flip_note']}" if e.get("flip_note") else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.outlook")
    p.add_argument("--asof", default=None)
    p.add_argument("--symbol", action="append", dest="symbols")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force-weekly", action="store_true",
                   help="score the weekly even mid-week (it is an unfinished bar)")
    p.add_argument("--all", action="store_true", help="print unchanged names too")
    p.add_argument("--warm-watchlist", action="store_true",
                   help="also score the watchlist into verdict_cache (never journaled)")
    args = p.parse_args(argv)

    conn = connect()
    out = run(conn, args.asof, args.symbols, args.dry_run, args.force_weekly)
    if args.warm_watchlist:
        # A dry run by construction: watchlist names are never recorded as
        # app decisions — only held names are, above — and this pass exists
        # so the page finds every name already scored in the morning.
        w = run(conn, args.asof, None, True, False, scope="watchlist", use_cache=True)
        c = w.get("cache") or {}
        print(f"Watchlist cache: {c.get('stored', 0)} scored, {c.get('hits', 0)} already "
              f"current, {len(w['skipped'])} too new to score.")
        print()

    print(f"Outlook for {out['asof']}"
          + ("  (dry run — nothing written)" if args.dry_run else ""))
    print()
    if out["changed"]:
        print(f"CHANGED ({len(out['changed'])})")
        for e in out["changed"]:
            print(_fmt(e))
    else:
        print("Nothing changed. Every holding sits where it sat at the last reading.")
    print()

    if args.all and out["unchanged"]:
        print(f"UNCHANGED ({len(out['unchanged'])})")
        for e in out["unchanged"]:
            print(f"  {e['symbol']:<6} {e['timeframe']}  {e['verdict']}"
                  f"  since {e['since']}")
        print()

    if out["skipped"]:
        print(f"NOT SCORED ({len(out['skipped'])})")
        for s in out["skipped"]:
            print(f"  {s['symbol']:<6} {s['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
