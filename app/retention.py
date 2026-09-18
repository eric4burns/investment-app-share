"""Prune what the ledger accumulates and never reads again.

    python3 -m app.retention            # dry run: rows and MB per table
    python3 -m app.retention --apply    # delete them (update.sh does this nightly)

## What is pruned, and why each rule is safe

  prices                 bars older than a sliding two years, for symbols the
                         app only knows from the discovery screen. 87% of the
                         price cache is 2,700 names never held or watched;
                         the scan reads two years (discover.history_from) and
                         nothing else ever reads them. Anything held, watched,
                         graded, drawn on, planned for, named in the code, or
                         priced from anything but Alpaca/Yahoo is kept whole.
  discover_hits          older than 90 days: "surfaced five nights running"
                         needs weeks of history, not months.
  discover_universe_log  dropped names older than 30 days. The KEPT names are
                         the point-in-time universe the log exists to record
                         (see discover.py) and stay forever; a name that was
                         not liquid enough that week is not worth a row a
                         year later.
  alerts                 older than 180 days.
  intraday_bars          older than 30 days; the poll reads the last session.
  price_fetches          rows for symbols that never yielded a bar, once a day
                         old. A failed fetch holds off a retry for twenty
                         minutes (prices.RETRY_SECONDS), so a row older than a
                         day is not doing that job any more.

Every rule is a WHERE clause below, printed with its row count and an
estimate of the space, before anything is deleted. Deleting frees pages for
reuse; the file shrinks only under VACUUM, which update.sh runs when the
dashboard is not up (see the note there), or `app.split_replay --vacuum`.

## What "the app relies on" means here

The protected set is built from the database and the code together, so a
symbol added to regime.py or sectors.py is protected the day it lands. When
in doubt a symbol is kept: the cost of keeping two years of one name is a
few hundred kilobytes, the cost of pruning a benchmark is a wrong reading.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import discover, intermarket, prices, regime, sectors, themes
from .ledger import DB_PATH, connect

APP_DIR = Path(__file__).resolve().parent
# A quoted ticker-like literal anywhere in the app's source. Deliberately
# broad: it also matches "RSI" and "GET", and protecting a name that is not
# a ticker costs nothing, whereas the first cut of this list — built from
# the four modules the audit named — missed themes.py's BITQ and ARKF.
TICKER_LITERAL = re.compile(r'"([A-Z][A-Z0-9.\-]{1,5})"')

DISCOVER_HITS_DAYS = 90
UNIVERSE_LOG_DAYS = 30
ALERTS_DAYS = 180
INTRADAY_DAYS = 30
FETCH_LOG_DAYS = 1
# Price rows are deleted this many symbols per transaction, so the write
# lock is held for a moment at a time while the dashboard is up.
BATCH_SYMBOLS = 100

# Sources whose bars are a cache of a feed. Anything else (fred, plan_nav) is
# either a benchmark or the app's own construction and is never pruned.
FEED_SOURCES = ("alpaca", "alpaca-sip", "alpaca-iex", "yahoo")


def code_symbols() -> set[str]:
    """Every symbol the code names: benchmarks, sector ETFs, the dial's
    inputs, the intermarket ratios, the money-market funds, the themes —
    and, as a net under all of those, every ticker-shaped literal in app/."""
    out: set[str] = set()
    for src in APP_DIR.glob("*.py"):
        try:
            out.update(TICKER_LITERAL.findall(src.read_text()))
        except OSError:
            continue
    for theme in themes.THEMES.values():
        out.update(theme.get("symbols") or ())
    out.update(getattr(themes, "THEME_ETFS", {}).values())
    out.update(prices.FRED_BENCHMARKS)
    out.update(v[0] for v in prices.FRED_BENCHMARKS.values())
    out.update(getattr(prices, "MONEY_MARKET_FUNDS", {}))
    out.update(regime.INDICES)
    out.add(regime.DOLLAR)
    out.update(sectors.SECTOR_ETFS)
    out.add(sectors.MARKET)
    out.update(getattr(sectors, "FUND_SECTORS", {}))
    out.update(getattr(sectors, "FUND_LOOKTHROUGH", {}))
    out.update(getattr(sectors, "SIC_OVERRIDES", {}))
    for spec in intermarket.SIGNALS.values():
        out.update(s for s in (spec.get("numerator"), spec.get("denominator")) if s)
    for spec in getattr(intermarket, "MACRO", {}).values():
        if spec.get("series"):
            out.add(spec["series"])
    return {s.strip().upper() for s in out if s}


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def protected_symbols(conn) -> set[str]:
    """Symbols whose price history is never pruned.

    Union of: everything ever traded; the watchlist; every symbol with a
    decision in any source (the replay grades its calls from these bars, and
    replay-screen's sample is drawn from the discovery universe); every
    symbol drawn on, planned, booked, priced by a followed author or watched
    for a level; every non-equity security; every symbol with bars from a
    source that is not a feed; and everything the code names.
    """
    have = _tables(conn)
    out = code_symbols()
    queries = [
        ("transactions", "SELECT DISTINCT s.symbol FROM securities s JOIN transactions t ON t.security_id = s.id"),
        ("watchlist", "SELECT symbol FROM watchlist"),
        ("decisions", "SELECT DISTINCT symbol FROM decisions"),
        ("drawings", "SELECT DISTINCT symbol FROM drawings"),
        ("buy_plans", "SELECT DISTINCT symbol FROM buy_plans"),
        ("position_books", "SELECT DISTINCT symbol FROM position_books"),
        ("author_levels", "SELECT DISTINCT symbol FROM author_levels"),
        ("watch_levels", "SELECT DISTINCT symbol FROM watch_levels"),
        ("paper_orders", "SELECT DISTINCT symbol FROM paper_orders"),
        ("broker_basis", "SELECT DISTINCT symbol FROM broker_basis"),
        ("securities", "SELECT symbol FROM securities WHERE kind != 'equity' "
                       "OR symbol LIKE 'PLAN:%' OR symbol LIKE 'CUSIP:%'"),
        ("prices", "SELECT DISTINCT s.symbol FROM securities s JOIN prices p ON p.security_id = s.id "
                   f"WHERE p.source NOT IN ({','.join('?' * len(FEED_SOURCES))})"),
    ]
    for table, sql in queries:
        if table not in have:
            continue
        args = FEED_SOURCES if table == "prices" else ()
        try:
            out.update((r[0] or "").strip().upper() for r in conn.execute(sql, args))
        except sqlite3.OperationalError:
            continue        # a table without the column this expects: nothing to protect from it
    # The replay file, when it exists, holds decisions too; those symbols'
    # bars are what grades them.
    from . import split_replay
    if split_replay.attach(conn):
        out.update((r[0] or "").strip().upper() for r in conn.execute(
            "SELECT DISTINCT symbol FROM replay.decisions"))
    out.discard("")
    return out


def price_cutoff(today: date | None = None) -> str:
    """The scan's own window (discover.history_from), so what is pruned is
    exactly what the scan would not fetch again."""
    return discover.history_from(today)


def discovery_symbols(conn) -> set[str]:
    """Names the discovery screen brought in. Only these are ever pruned: a
    symbol somebody charted by hand is not the screen's to age out."""
    out: set[str] = set()
    for table in ("discover_universe", "discover_universe_log"):
        if table in _tables(conn):
            out.update((r[0] or "").strip().upper() for r in conn.execute(f"SELECT symbol FROM {table}"))
    return out


def prunable_price_symbols(conn, today: date | None = None) -> list[tuple[int, str, int]]:
    """(security_id, symbol, stale bar count) for every symbol the price rule applies to."""
    keep = protected_symbols(conn)
    screen = discovery_symbols(conn)
    cutoff = price_cutoff(today)
    rows = conn.execute(
        """SELECT p.security_id, s.symbol, COUNT(*) n
             FROM prices p JOIN securities s ON s.id = p.security_id
            WHERE p.bar_date < ?
            GROUP BY p.security_id, s.symbol""", (cutoff,)).fetchall()
    return [(r[0], r[1], r[2]) for r in rows
            if (r[1] or "").strip().upper() in screen and (r[1] or "").strip().upper() not in keep]


def _days_ago(days: int, today: date | None = None) -> str:
    return ((today or date.today()) - timedelta(days=days)).isoformat()


def rules(conn, today: date | None = None) -> list[dict]:
    """Every rule with its WHERE clause and the rows it matches now."""
    have = _tables(conn)
    out = []

    def rule(table, what, where, args=()):
        if table not in have:
            return
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]
        except sqlite3.OperationalError as exc:
            out.append({"table": table, "what": what, "rows": 0, "skipped": str(exc)})
            return
        out.append({"table": table, "what": what, "where": where, "args": tuple(args), "rows": n})

    if "prices" in have:
        syms = prunable_price_symbols(conn, today)
        out.append({"table": "prices", "cutoff": price_cutoff(today),
                    "what": f"bars before {price_cutoff(today)} for {len(syms):,} discovery-only names",
                    "symbols": syms, "rows": sum(n for _, _, n in syms)})
    rule("discover_hits", f"older than {DISCOVER_HITS_DAYS} days",
         "day < ?", (_days_ago(DISCOVER_HITS_DAYS, today),))
    rule("discover_universe_log", f"names NOT kept, older than {UNIVERSE_LOG_DAYS} days",
         "kept = 0 AND day < ?", (_days_ago(UNIVERSE_LOG_DAYS, today),))
    rule("alerts", f"older than {ALERTS_DAYS} days", "day < ?", (_days_ago(ALERTS_DAYS, today),))
    rule("intraday_bars", f"older than {INTRADAY_DAYS} days",
         "ts < ?", (_days_ago(INTRADAY_DAYS, today),))
    if "price_fetches" in have:
        since = (datetime.now(timezone.utc) - timedelta(days=FETCH_LOG_DAYS)).isoformat(timespec="seconds")
        rule("price_fetches", f"symbols with no bars, attempted over {FETCH_LOG_DAYS} day ago",
             """attempted_at < ? AND symbol NOT IN (
                    SELECT s.symbol FROM securities s WHERE EXISTS (
                        SELECT 1 FROM prices p WHERE p.security_id = s.id))""", (since,))
    return out


def bytes_per_row(conn, table: str) -> float | None:
    """Table plus its indexes, from dbstat, when the sqlite3 CLI has it."""
    cli = shutil.which("sqlite3")
    db = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    if not cli or not db:
        return None
    try:
        out = subprocess.run(
            [cli, db, f"SELECT (SELECT sum(pgsize) FROM dbstat WHERE name IN "
                      f"(SELECT name FROM sqlite_master WHERE tbl_name='{table}')), "
                      f"(SELECT count(*) FROM \"{table}\")"],
            capture_output=True, text=True, timeout=120).stdout.strip()
        size, n = out.split("|")
        return (float(size) / float(n)) if float(n) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


ROUGH_BYTES = {"prices": 105, "decision_evidence": 60, "decisions": 130}


def estimate_mb(conn, r: dict) -> float:
    per = bytes_per_row(conn, r["table"]) or ROUGH_BYTES.get(r["table"], 100)
    return r["rows"] * per / 1e6


def apply(conn, plan: list[dict], say=print) -> dict:
    """Delete what the plan lists. Prices go symbol by symbol in batches."""
    done = {}
    for r in plan:
        if r.get("skipped") or not r["rows"]:
            continue
        if r["table"] == "prices":
            cutoff = r["cutoff"]
            n = 0
            syms = r["symbols"]
            for i in range(0, len(syms), BATCH_SYMBOLS):
                for sid, _sym, _c in syms[i:i + BATCH_SYMBOLS]:
                    n += conn.execute("DELETE FROM prices WHERE security_id = ? AND bar_date < ?",
                                      (sid, cutoff)).rowcount
                conn.commit()
            done["prices"] = n
        else:
            n = conn.execute(f"DELETE FROM {r['table']} WHERE {r['where']}", r["args"]).rowcount
            conn.commit()
            done[r["table"]] = n
        say(f"  {r['table']:<22} {n:>10,} rows deleted")
    return done


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.retention")
    p.add_argument("--apply", action="store_true", help="delete (default is a dry run)")
    p.add_argument("--db", default=str(DB_PATH), help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    conn = connect(args.db)
    plan = rules(conn)
    total_rows = total_mb = 0.0
    print(f"{'table':<22} {'rows':>10} {'~MB':>7}  rule")
    for r in plan:
        if r.get("skipped"):
            print(f"{r['table']:<22} {'-':>10} {'-':>7}  skipped: {r['skipped']}")
            continue
        mb = estimate_mb(conn, r)
        total_rows += r["rows"]
        total_mb += mb
        print(f"{r['table']:<22} {r['rows']:>10,} {mb:>7.1f}  {r['what']}")
    print(f"{'total':<22} {int(total_rows):>10,} {total_mb:>7.1f}")
    if not args.apply:
        print("dry run; add --apply to delete")
        return 0
    if not total_rows:
        print("nothing to prune")
        return 0
    apply(conn, plan)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
