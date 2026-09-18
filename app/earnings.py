"""Earnings dates, so a verdict two days before a report can say so.

    python3 -m app.earnings sync            # the next ~100 days
    python3 -m app.earnings show            # what is coming, for held and watched names

## The source, and what it is

Nasdaq publishes a daily earnings calendar behind an undocumented JSON
endpoint — one request per calendar date, keyless, answering with every
company reporting that day, whether before the open or after the close, and
the consensus estimate. It is on the same footing as the Yahoo fallback in
prices.py: it works, it is not a supported API, and it can change without
notice. Every row it produces is tagged with its source, and switching it off
is one constant.

Nothing free and official gives FORWARD dates. EDGAR knows when a 10-Q was
filed, which is after the fact. So this is the honest trade: an unofficial
source for the one piece of context every commercial tool has and this one
had none of.

## What it is used for

Context and alerts, not scoring. An earnings date is not evidence about the
chart; it is a reason a chart is about to stop mattering for a day. The
Outlook tab shows days-to-earnings beside every call, the alerts fire inside
five days, and the chart marks the date. Whether calls made into earnings do
worse is a question the replay can answer once a year of dates has been
stored — which is why past dates are kept rather than pruned.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta

from .ledger import connect

ENABLED = True
NASDAQ_CALENDAR = "https://api.nasdaq.com/api/calendar/earnings?date={day}"
PAUSE = 0.4                       # be a polite, slow client of an unofficial endpoint
DEFAULT_DAYS_AHEAD = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS earnings_dates (
    symbol      TEXT NOT NULL,
    report_date TEXT NOT NULL,
    timing      TEXT,                 -- pre-market | after-hours | unknown
    eps_estimate REAL,
    fiscal_quarter TEXT,
    source      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (symbol, report_date)
);
CREATE TABLE IF NOT EXISTS earnings_fetches (
    day TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, rows INTEGER
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"})
    return urllib.request.urlopen(req, timeout=30).read()


def _money(s: str | None):
    if not s:
        return None
    neg = s.strip().startswith("(")
    digits = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    try:
        v = float(digits)
    except ValueError:
        return None
    return -v if neg else v


def fetch_day(day: str) -> list[dict]:
    """Every company Nasdaq lists as reporting on `day`."""
    data = json.loads(_get(NASDAQ_CALENDAR.format(day=day)))
    rows = (data.get("data") or {}).get("rows") or []
    out = []
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        t = (r.get("time") or "").lower()
        timing = ("pre-market" if "pre" in t else "after-hours" if "after" in t else "unknown")
        out.append({"symbol": sym, "report_date": day, "timing": timing,
                    "eps_estimate": _money(r.get("epsForecast")),
                    "fiscal_quarter": r.get("fiscalQuarterEnding")})
    return out


def sync(conn, days_ahead: int = DEFAULT_DAYS_AHEAD, refresh_hours: int = 20,
         log=None) -> dict:
    """Pull the calendar day by day. A day already fetched recently is skipped."""
    say = log or (lambda *a: None)
    if not ENABLED:
        return {"error": "earnings source disabled"}
    ensure_schema(conn)
    today = date.today()
    fetched, skipped, failed, stored = 0, 0, [], 0
    for i in range(days_ahead + 1):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        day = d.isoformat()
        row = conn.execute("SELECT fetched_at FROM earnings_fetches WHERE day=?", (day,)).fetchone()
        if row:
            try:
                age = datetime.now() - datetime.fromisoformat(row["fetched_at"])
                if age < timedelta(hours=refresh_hours):
                    skipped += 1
                    continue
            except ValueError:
                pass
        try:
            rows = fetch_day(day)
            time.sleep(PAUSE)
        except Exception as exc:                               # noqa: BLE001
            failed.append((day, type(exc).__name__))
            continue
        now = datetime.now().isoformat(timespec="seconds")
        # Replace the day: a company that moved its date off this day should
        # disappear from it, which insert-or-ignore would never do.
        conn.execute("DELETE FROM earnings_dates WHERE report_date=? AND source='nasdaq'", (day,))
        for r in rows:
            conn.execute("""INSERT OR REPLACE INTO earnings_dates
                (symbol, report_date, timing, eps_estimate, fiscal_quarter, source, fetched_at)
                VALUES (?,?,?,?,?,?,?)""",
                         (r["symbol"], day, r["timing"], r["eps_estimate"],
                          r["fiscal_quarter"], "nasdaq", now))
        conn.execute("""INSERT INTO earnings_fetches (day, fetched_at, rows) VALUES (?,?,?)
                        ON CONFLICT(day) DO UPDATE SET fetched_at=excluded.fetched_at, rows=excluded.rows""",
                     (day, now, len(rows)))
        conn.commit()
        fetched += 1
        stored += len(rows)
        say(f"  {day}  {len(rows):>3} reports")
    return {"days_fetched": fetched, "days_skipped": skipped, "failed": failed, "rows": stored}


def upcoming(conn, symbols: list[str], asof: str | None = None,
             within: int = 400) -> dict[str, dict]:
    """The next report for each symbol on or after `asof`, with days to go."""
    ensure_schema(conn)
    asof = asof or date.today().isoformat()
    want = {s.upper() for s in symbols}
    out: dict[str, dict] = {}
    for r in conn.execute(
        """SELECT symbol, report_date, timing, eps_estimate, fiscal_quarter FROM earnings_dates
            WHERE report_date >= ? ORDER BY report_date""", (asof,)):
        if r["symbol"] not in want or r["symbol"] in out:
            continue
        days = (date.fromisoformat(r["report_date"]) - date.fromisoformat(asof)).days
        if days > within:
            continue
        out[r["symbol"]] = {"date": r["report_date"], "days": days, "timing": r["timing"],
                            "eps_estimate": r["eps_estimate"], "fiscal_quarter": r["fiscal_quarter"]}
    return out


def history(conn, symbol: str) -> list[str]:
    ensure_schema(conn)
    return [r[0] for r in conn.execute(
        "SELECT report_date FROM earnings_dates WHERE symbol=? ORDER BY report_date", (symbol.upper(),))]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.earnings")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--days", type=int, default=DEFAULT_DAYS_AHEAD)
    sub.add_parser("show")
    args = p.parse_args(argv)
    conn = connect()
    if args.cmd == "sync":
        r = sync(conn, args.days, log=print)
        if r.get("error"):
            print(r["error"])
            return 1
        print(f"\n{r['days_fetched']} days fetched, {r['days_skipped']} already fresh, "
              f"{r['rows']} reports stored, {len(r['failed'])} failed")
        return 0
    if args.cmd == "show":
        from . import replay
        up = upcoming(conn, replay.universe(conn))
        for sym, e in sorted(up.items(), key=lambda kv: kv[1]["days"]):
            est = f"est {e['eps_estimate']:+.2f}" if e["eps_estimate"] is not None else ""
            print(f"  {sym:<7} {e['date']}  in {e['days']:>3} days  {e['timing']:<12} {est}")
        if not up:
            print("  nothing on the calendar for held or watched names")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
