"""Discovery: the encoded methods run across the whole market, not just the watchlist.

    python3 -m app.discover screen        # weekly: every listed name, kept if liquid enough
    python3 -m app.discover scan          # nightly: the methods across the kept names
    python3 -m app.discover show          # what qualifies that you are not watching

## Why

The scanner only ever saw the 164 names on the watchlist, so it could
confirm what was already being watched and never find anything. Every
commercial screener starts from the whole market. This one now does too,
at zero cost: Alpaca's asset list is free with the same key the prices use,
and the consolidated daily bars are the same feed.

## Two passes, because the market is mostly noise

The listed universe is about eight thousand plain NASDAQ and NYSE symbols
once warrants, rights, units and blank-cheque shells are dropped by name.
Most of that is untradeable at any size. So the SCREEN fetches thirty days
of bars for each and keeps a name only if it averages at least $5 million a
day in dollar volume above $2 a share — the floor under which a fill on a
swing-sized position moves the price. That leaves on the order of two
thousand, and it is run weekly, because liquidity does not change overnight
and eight thousand requests is half an hour at the free plan's limit.

The SCAN runs nightly on the kept names: two years of bars kept current, the
same `methods.scan` the Research tab uses, and a relative-strength rank
across the whole kept universe rather than the watchlist. Anything that
clears a method's threshold and is not on the watchlist is a hit, stored
with the date so the same name surfacing five nights running reads as one
idea rather than five.

## What it is not

It is not a recommendation engine and it does not add anything to the
watchlist on its own. It surfaces names for you to look at, with the method
that flagged them and the numbers, and one click puts one on the list where
the verdict engine will read it properly. The methods' own caveats apply —
a name that scores 0.9 on a momentum method is a name that has already gone
up — and the replay's finding about the engine's edge applies here too.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta

from . import methods, netsafe, prices, watchlist
from .ledger import connect, retry_locked

ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets?status=active&asset_class=us_equity"
EXCHANGES = {"NASDAQ", "NYSE"}
MIN_DOLLAR_VOLUME = 5_000_000
MIN_PRICE = 2.0
SCREEN_DAYS = 45
# How far back the scan keeps bars for the kept names: two years, as of
# today. This was a fixed "2023-01-01", which the docstring above called
# "two years" and which grew by a day every day — by 2026 it was three years
# and nine months of bars for 2,700 names nobody holds, 87% of the price
# cache. A sliding window is what the methods need (the longest lookback is
# ACC_BASE + ACC_WIN sessions, well inside two years), and it is the window
# app/retention.py prunes back to nightly, so the two agree by construction.
# The fetch log's `earliest` is only ever pushed earlier by a request, so a
# start that moves later never triggers a re-fetch.
HISTORY_YEARS = 2


def history_from(today: date | None = None) -> str:
    today = today or date.today()
    try:
        return today.replace(year=today.year - HISTORY_YEARS).isoformat()
    except ValueError:                       # 29 February
        return today.replace(year=today.year - HISTORY_YEARS, day=28).isoformat()


THRESHOLD = 0.75

# ---- accumulation: volume expanding BEFORE the price has run ---------------
#
# Measured 2026-09-09 over 2,643 cached symbols (research/audits/edge-log.md).
# Mean dollar volume over ACC_WIN sessions against the ACC_BASE sessions before
# it, on names still near their own base. Names in the band below went on to
# quadruple within a year 11.5% of the time against a 1.5% base rate — a 7.7x
# lift, present in 2020-22, 2023-24 and 2025-26 separately and surviving the
# injection of 50% delisted-to-zero names.
#
# Every bound is there because leaving it off broke the measurement:
#
#   ACC_MAX exists because the first cut had no ceiling and filled with
#   corporate actions — CLRO at 1,900x its base, JWEL at 713x. Those are
#   reverse splits, not accumulation, and they inflated the headline from
#   11.5% to 15.1%.
#   ACC_RUNUP_MIN exists for the same reason from the other side: a 126-day
#   run-up near zero is an unadjusted split, not a quiet base.
#   ACC_RUNUP_MAX is the whole point of the signal. Above it the move has
#   already happened and this becomes an ordinary momentum screen, which the
#   same study found is worth much less.
ACC_WIN = 20
ACC_BASE = 126
ACC_MIN = 4.0
ACC_MAX = 20.0
ACC_RUNUP_MIN = 0.5
ACC_RUNUP_MAX = 1.25
ACC_METHOD = "accumulation"
# Names that are not operating companies, by the words their own listing uses.
NOT_A_COMPANY = re.compile(
    r"\b(acquisition|warrant|warrants|right|rights|unit|units|etf|etn|trust|fund|"
    r"depositary|preferred|notes?|debentures?|spac|blank check|capital corp\b)",
    re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS discover_universe (
    symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT,
    price REAL, dollar_volume REAL, kept INTEGER NOT NULL, screened_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discover_hits (
    day TEXT NOT NULL, method TEXT NOT NULL, symbol TEXT NOT NULL,
    pct REAL, coverage REAL, rs_rank INTEGER, price REAL,
    PRIMARY KEY (day, method, symbol)
);
-- The accumulation scan's own numbers. Separate from discover_hits because a
-- hit there is "a method scored this name above its threshold" and carries a
-- pct; this carries a volume ratio and a run-up, and squeezing them into `pct`
-- would make the two unreadable side by side.
CREATE TABLE IF NOT EXISTS accumulation_hits (
    day TEXT NOT NULL, symbol TEXT NOT NULL, price REAL,
    surge REAL, runup REAL, dollar_volume REAL,
    first_day TEXT,
    PRIMARY KEY (day, symbol)
);
CREATE INDEX IF NOT EXISTS ix_discover_hits_day ON discover_hits (day);
-- Every screen's kept set, by the day it was taken. The point-in-time universe
-- nobody chose with hindsight: replaying the engine on the names that were
-- liquid on a given date, whether or not they went on to matter, is the test
-- that separates the market from the watchlist's survivorship.
CREATE TABLE IF NOT EXISTS discover_universe_log (
    day TEXT NOT NULL, symbol TEXT NOT NULL, kept INTEGER NOT NULL,
    price REAL, dollar_volume REAL, PRIMARY KEY (day, symbol)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def assets() -> list[dict]:
    creds = prices.alpaca_credentials()
    if not creds:
        raise RuntimeError("No Alpaca credentials; see data/.alpaca")
    key, secret = creds
    req = urllib.request.Request(ASSETS_URL, headers={"APCA-API-KEY-ID": key,
                                                      "APCA-API-SECRET-KEY": secret})
    return json.loads(netsafe.urlopen(req, timeout=60).read())


def candidates(asset_list: list[dict]) -> list[dict]:
    """Plain common stock on the two main exchanges, by the listing's own words."""
    out = []
    for a in asset_list:
        sym = (a.get("symbol") or "").upper()
        if not a.get("tradable") or a.get("exchange") not in EXCHANGES:
            continue
        if not sym.isalpha() or len(sym) > 5:
            continue
        if NOT_A_COMPANY.search(a.get("name") or ""):
            continue
        out.append({"symbol": sym, "name": (a.get("name") or "").strip(), "exchange": a["exchange"]})
    return out


def _dollar_volume(bars) -> tuple[float | None, float | None]:
    """Average daily dollar volume over the bars, and the last close."""
    if not bars:
        return None, None
    dv = [b[1] * b[5] for b in bars if b[1] and b[5]]
    return (sum(dv) / len(dv) if dv else 0.0), bars[-1][1]


def screen(conn, log=None, limit: int | None = None) -> dict:
    """Fetch thirty days for every candidate; keep the liquid ones."""
    say = log or (lambda *a: None)
    ensure_schema(conn)
    cands = candidates(assets())
    if limit:
        cands = cands[:limit]
    start = (date.today() - timedelta(days=SCREEN_DAYS)).isoformat()
    end = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    kept, dropped, failed, t0 = 0, 0, 0, time.time()
    # Resumable: a name screened in the last six days is not fetched again,
    # so an interrupted run picks up where it stopped and the weekly run only
    # touches what has aged out.
    fresh_since = (datetime.now() - timedelta(days=6)).isoformat(timespec="seconds")
    already = {r[0]: r[1] for r in conn.execute(
        "SELECT symbol, kept FROM discover_universe WHERE screened_at >= ?", (fresh_since,))}
    say(f"screen: {len(cands)} candidates on {', '.join(sorted(EXCHANGES))}, "
        f"{len(already)} already screened this week")
    for i, c in enumerate(cands, 1):
        if c["symbol"] in already:
            kept += bool(already[c["symbol"]])
            continue
        bars, err = [], None
        for attempt in range(3):
            try:
                bars = prices.fetch_alpaca(c["symbol"], start, end, feed="sip")
                time.sleep(0.31)             # under the free plan's 200 a minute
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    time.sleep(20)
                    continue
                err = exc.code
                break
            except Exception as exc:                            # noqa: BLE001
                err = type(exc).__name__
                break
        if err:
            failed += 1
            continue
        dv, px = _dollar_volume(bars)
        keep = bool(dv and px and dv >= MIN_DOLLAR_VOLUME and px >= MIN_PRICE)

        def _write():
            conn.execute("""INSERT INTO discover_universe (symbol, name, exchange, price, dollar_volume, kept, screened_at)
                            VALUES (?,?,?,?,?,?,?)
                            ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, exchange=excluded.exchange,
                              price=excluded.price, dollar_volume=excluded.dollar_volume,
                              kept=excluded.kept, screened_at=excluded.screened_at""",
                         (c["symbol"], c["name"], c["exchange"], px, dv, int(keep), now))
            # Commit every row. Holding the write lock across 250 network
            # round-trips locked every other writer out of the ledger for
            # minutes at a time, and the insider sync died of it.
            conn.commit()
        retry_locked(_write)
        kept += keep
        dropped += (not keep)
        if i % 250 == 0:
            say(f"  {i:>5}/{len(cands)}  kept {kept}  ({time.time() - t0:,.0f}s)")
    conn.commit()
    log_universe(conn)
    say(f"  done: kept {kept}, dropped {dropped}, failed {failed} in {time.time() - t0:,.0f}s")
    return {"candidates": len(cands), "kept": kept, "dropped": dropped, "failed": failed}


def log_universe(conn, day: str | None = None) -> int:
    """Copy the current screen into the dated log, once per day."""
    ensure_schema(conn)
    day = day or date.today().isoformat()
    n = 0
    for r in conn.execute("SELECT symbol, kept, price, dollar_volume FROM discover_universe"):
        cur = conn.execute("""INSERT OR IGNORE INTO discover_universe_log (day, symbol, kept, price, dollar_volume)
                              VALUES (?,?,?,?,?)""", (day, r["symbol"], r["kept"], r["price"], r["dollar_volume"]))
        n += cur.rowcount
    conn.commit()
    return n


def universe_on(conn, day: str) -> list[str]:
    """The names that were kept on the latest screen on or before `day`."""
    ensure_schema(conn)
    latest = conn.execute("SELECT MAX(day) FROM discover_universe_log WHERE day <= ?", (day,)).fetchone()[0]
    if not latest:
        return []
    return [r[0] for r in conn.execute(
        "SELECT symbol FROM discover_universe_log WHERE day=? AND kept=1 ORDER BY symbol", (latest,))]


def kept(conn) -> list[dict]:
    ensure_schema(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM discover_universe WHERE kept=1 ORDER BY dollar_volume DESC")]


def scan(conn, log=None, refresh: bool = True) -> dict:
    """Keep the kept names' bars current, then run every method across them."""
    say = log or (lambda *a: None)
    ensure_schema(conn)
    watchlist.ensure_schema(conn)
    names = kept(conn)
    if not names:
        return {"error": "nothing screened yet; run python3 -m app.discover screen"}
    end = date.today().isoformat()
    watched = {r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist")}
    t0 = time.time()
    if refresh:
        done = failed = 0
        for n in names:
            try:
                r = prices.ensure_symbol(conn, n["symbol"], history_from(), end, as_equity=True)
                done += bool(r.get("ok"))
                failed += (not r.get("ok"))
            except Exception:                                   # noqa: BLE001
                failed += 1
        conn.commit()
        say(f"  bars current for {done} names, {failed} failed ({time.time() - t0:,.0f}s)")

    syms = [n["symbol"] for n in names]
    # Relative strength across the whole kept universe, not the watchlist.
    rows = []
    for s in syms:
        series = prices.load_series(conn, s)
        dates = prices.sorted_dates(conn, s)
        rows.append({"symbol": s,
                     "chg_1m": watchlist._pct_from(series, dates, 21),
                     "chg_3m": watchlist._pct_from(series, dates, 63),
                     "chg_6m": watchlist._pct_from(series, dates, 126),
                     "chg_12m": watchlist._pct_from(series, dates, 252)})
    watchlist.rank_relative_strength(rows)
    rs = {r["symbol"]: r.get("rs_rank") for r in rows}

    hits = 0
    conn.execute("DELETE FROM discover_hits WHERE day=?", (end,))
    for key in methods.METHODS:
        res = methods.scan(conn, syms, key, end)
        for r in res.get("rows", []):
            if r.get("pct", 0) >= THRESHOLD and r.get("coverage", 1.0) >= 0.6:
                if r.get("price") is None:
                    # the scan rows carry no price; every hit rendered "—"
                    try:
                        series = prices.load_series(conn, r["symbol"])
                        ds = [x for x in sorted(series) if x <= end]
                        r["price"] = series[ds[-1]] if ds else None
                    except Exception:                          # noqa: BLE001
                        r["price"] = None
                conn.execute("""INSERT OR REPLACE INTO discover_hits
                                (day, method, symbol, pct, coverage, rs_rank, price)
                                VALUES (?,?,?,?,?,?,?)""",
                             (end, key, r["symbol"], r["pct"], r.get("coverage"),
                              rs.get(r["symbol"]), r.get("price")))
                hits += 1
        say(f"  {key}: {sum(1 for r in res.get('rows', []) if r.get('pct', 0) >= THRESHOLD)} pass")
    conn.commit()
    say(f"  {hits} hits across {len(methods.METHODS)} methods ({time.time() - t0:,.0f}s)")
    # The names the page will show get their sector and business line now,
    # one SEC call each and cached, so the tab never fetches on read.
    try:
        from . import sectors
        shown = {x["symbol"] for m in hits_payload(conn).values() for x in m["hits"][:15]}
        sectors.classify(conn, sorted(shown))
        conn.commit()
    except Exception as exc:                                   # noqa: BLE001
        say(f"  sector lookup skipped: {type(exc).__name__}: {exc}")
    return {"names": len(syms), "hits": hits, "watched_excluded": len(watched)}


def hits_payload(conn) -> dict:
    return hits(conn).get("methods") or {}


def accumulation_at(bars: list[dict], i: int | None = None) -> dict | None:
    """Is this name being accumulated, on the bar at `i` (default the last)?

    Returns the numbers when it qualifies and None when it does not, so the
    caller never has to repeat the bounds. `first_day` is left to the caller:
    whether a hit is new or the fifth night running is a question about the
    stored history, not about the bars.
    """
    if i is None:
        i = len(bars) - 1
    need = ACC_WIN + ACC_BASE
    if i < need:
        return None
    dv = [(b.get("volume") or 0) * b["close"] for b in bars]
    base = sum(dv[i - ACC_WIN - ACC_BASE:i - ACC_WIN]) / ACC_BASE
    recent = sum(dv[i - ACC_WIN:i]) / ACC_WIN
    price = bars[i]["close"]
    if base <= 0 or price < MIN_PRICE or recent < MIN_DOLLAR_VOLUME:
        return None
    surge = recent / base
    runup = price / bars[i - ACC_BASE]["close"]
    if not (ACC_MIN <= surge <= ACC_MAX and ACC_RUNUP_MIN <= runup < ACC_RUNUP_MAX):
        return None
    return {"price": round(price, 4), "surge": round(surge, 2),
            "runup": round(runup, 3), "dollar_volume": round(recent, 0)}


def accumulation(conn, log=None, day: str | None = None, backfill: int = 0) -> dict:
    """Run the accumulation scan over the kept universe and store the hits.

    Reads only bars already cached — `scan` keeps them current — so this costs
    nothing and can run as often as wanted.
    """
    ensure_schema(conn)
    say = log or (lambda *_: None)
    names = [k["symbol"] for k in kept(conn)]
    found, skipped = [], 0
    for sym in names:
        bars = prices.load_bars(conn, sym, history_from(), day or "2100-01-01")
        if len(bars) < ACC_WIN + ACC_BASE + 1:
            skipped += 1
            continue
        # backfill walks the last N bars so the list is useful on the first
        # run instead of filling up over the following month. It is the same
        # computation at each bar, using only data available on that bar.
        for i in range(len(bars) - 1 - max(0, backfill), len(bars)):
            hit = accumulation_at(bars, i)
            if hit:
                found.append({"symbol": sym, "day": bars[i]["time"], **hit})
    for f in found:
        prior = conn.execute(
            "SELECT MIN(day) FROM accumulation_hits WHERE symbol=? AND day > date(?, '-90 day')",
            (f["symbol"], f["day"])).fetchone()[0]
        row = (f["day"], f["symbol"], f["price"], f["surge"], f["runup"],
               f["dollar_volume"], prior or f["day"])
        retry_locked(lambda r=row: conn.execute(
            """INSERT INTO accumulation_hits
               (day, symbol, price, surge, runup, dollar_volume, first_day)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(day, symbol) DO UPDATE SET
                 price=excluded.price, surge=excluded.surge, runup=excluded.runup,
                 dollar_volume=excluded.dollar_volume""", r))
    retry_locked(conn.commit)
    say(f"  accumulation: {len(found)} of {len(names)} names ({skipped} too little history)")
    # What each flagged company IS comes from its SEC filing (the SIC line):
    # one call per new name, cached for good, so the page never waits on it.
    # A ticker, a volume multiple and a price were the whole row before and
    # the user's reading of the tab was "nothing useful" (2026-09-13).
    try:
        from . import sectors
        sectors.classify(conn, sorted({f["symbol"] for f in found}))
        retry_locked(conn.commit)
    except Exception as exc:                                   # noqa: BLE001
        say(f"  sector lookup skipped: {type(exc).__name__}: {exc}")
    return {"found": found, "scanned": len(names), "skipped": skipped}


def describe(conn, rows: list[dict]) -> list[dict]:
    """Put beside each scan row what a reader needs to decide whether to look.

    From the bars already cached by the scan: the week, month and quarter
    moves, how far under the 52-week high it sits, and the last close's date.
    From security_meta: the sector and the SIC description, which is the one
    line the SEC has on what the company does. From the method scan: the
    relative-strength rank if the name made a method list. Nothing here is
    fetched at read time; a name with no bars keeps its row and says so.
    """
    from . import sectors
    if not rows:
        return rows
    meta = sectors.lookup(conn, [r["symbol"] for r in rows])
    latest_hits: dict[str, dict] = {}
    for h in conn.execute("""SELECT symbol, method, rs_rank, pct FROM discover_hits
                             WHERE day = (SELECT MAX(day) FROM discover_hits)"""):
        cur = latest_hits.get(h["symbol"])
        if cur is None or (h["rs_rank"] or 0) > (cur.get("rs_rank") or 0):
            latest_hits[h["symbol"]] = dict(h)
    for r in rows:
        m = meta.get(r["symbol"]) or {}
        r["sector"] = m.get("sector") if m.get("sector") not in (None, "Unknown") else None
        r["business"] = (m.get("sic_description") or "").split(" — reclassified")[0].strip().title() or None
        h = latest_hits.get(r["symbol"])
        r["rs_rank"] = h.get("rs_rank") if h else None
        r["method"] = h.get("method") if h else None
        try:
            bars = prices.load_bars(conn, r["symbol"], "2000-01-01", "2100-01-01", last=260)
        except Exception:                                      # noqa: BLE001
            bars = []
        closes = [b["close"] for b in bars if b.get("close")]
        if not closes:
            r.update({"chg_1w": None, "chg_1m": None, "chg_3m": None, "from_52w_high": None, "asof": None})
            continue
        last = closes[-1]
        back = lambda n: (last / closes[-1 - n] - 1) if len(closes) > n and closes[-1 - n] else None  # noqa: E731
        hi = max(b.get("high") or b["close"] for b in bars if b.get("close"))
        r.update({"chg_1w": back(5), "chg_1m": back(21), "chg_3m": back(63),
                  "from_52w_high": (last / hi - 1) if hi else None, "asof": bars[-1]["time"]})
    return rows


def accumulation_hits(conn, days: int = 40, exclude_watched: bool = True) -> list[dict]:
    """Recent accumulation hits, newest first, one row per name.

    One row per NAME rather than per day: a name flagged five nights running is
    one idea, and the date shown is when it first qualified. That is the same
    rule `hits` follows and it exists for the same reason — a list that repeats
    itself buries whatever is new.
    """
    ensure_schema(conn)
    watchlist.ensure_schema(conn)
    latest = conn.execute("SELECT MAX(day) FROM accumulation_hits").fetchone()[0]
    if not latest:
        return []
    since = (date.fromisoformat(latest) - timedelta(days=days)).isoformat()
    watched = {r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist")}
    held = {r["symbol"] for r in conn.execute(
        """SELECT DISTINCT s.symbol FROM transactions t JOIN securities s ON s.id=t.security_id
           WHERE t.quantity > 0""")}
    meta = {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM discover_universe")}
    out = []
    for r in conn.execute("""SELECT symbol, MAX(day) day, MIN(first_day) first_day,
                                    COUNT(*) nights
                             FROM accumulation_hits WHERE day > ?
                             GROUP BY symbol ORDER BY MIN(first_day) DESC""", (since,)):
        if exclude_watched and (r["symbol"] in watched or r["symbol"] in held):
            continue
        last = conn.execute("""SELECT * FROM accumulation_hits WHERE symbol=? AND day=?""",
                            (r["symbol"], r["day"])).fetchone()
        m = meta.get(r["symbol"]) or {}
        out.append({"symbol": r["symbol"], "name": m.get("name"), "exchange": m.get("exchange"),
                    "first_day": r["first_day"], "day": r["day"], "nights": r["nights"],
                    "price": last["price"], "surge": last["surge"], "runup": last["runup"],
                    "dollar_volume": last["dollar_volume"]})
    return out


def hits(conn, days: int = 7, exclude_watched: bool = True) -> dict:
    """The latest scan's hits, with how many of the last N scans each name made."""
    ensure_schema(conn)
    watchlist.ensure_schema(conn)
    latest = conn.execute("SELECT MAX(day) FROM discover_hits").fetchone()[0]
    if not latest:
        return {"day": None, "methods": {}}
    since = (date.fromisoformat(latest) - timedelta(days=days)).isoformat()
    watched = {r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist")}
    meta = {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM discover_universe")}
    streak = {}
    for r in conn.execute("""SELECT method, symbol, COUNT(DISTINCT day) n FROM discover_hits
                             WHERE day > ? GROUP BY method, symbol""", (since,)):
        streak[(r["method"], r["symbol"])] = r["n"]
    out: dict[str, list] = {}
    for r in conn.execute("SELECT * FROM discover_hits WHERE day=? ORDER BY method, pct DESC, rs_rank DESC",
                          (latest,)):
        if exclude_watched and r["symbol"] in watched:
            continue
        m = meta.get(r["symbol"]) or {}
        out.setdefault(r["method"], []).append({
            "symbol": r["symbol"], "name": m.get("name"), "exchange": m.get("exchange"),
            "pct": r["pct"], "coverage": r["coverage"], "rs_rank": r["rs_rank"],
            "price": r["price"], "dollar_volume": m.get("dollar_volume"),
            "days_flagged": streak.get((r["method"], r["symbol"]), 1)})
    names = {k: v["name"] for k, v in methods.METHODS.items()}
    return {"day": latest, "methods": {k: {"name": names.get(k, k), "hits": v} for k, v in out.items()},
            "universe": conn.execute("SELECT COUNT(*) FROM discover_universe WHERE kept=1").fetchone()[0],
            "screened_at": (conn.execute("SELECT MAX(screened_at) FROM discover_universe").fetchone()[0] or "")[:10]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.discover")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("screen"); s.add_argument("--limit", type=int, default=None)
    sc = sub.add_parser("scan"); sc.add_argument("--no-refresh", action="store_true")
    sub.add_parser("show")
    ac = sub.add_parser("accumulation")
    ac.add_argument("--backfill", type=int, default=0,
                    help="also score the last N sessions, so the list is useful immediately")
    args = p.parse_args(argv)
    conn = connect()
    if args.cmd == "screen":
        r = screen(conn, log=print, limit=args.limit)
        return 0
    if args.cmd == "scan":
        r = scan(conn, log=print, refresh=not args.no_refresh)
        if r.get("error"):
            print(r["error"]); return 1
        # The accumulation pass rides along with the nightly scan: it reads only
        # bars the scan has just refreshed, so it costs nothing extra.
        accumulation(conn, log=print)
        return 0
    if args.cmd == "accumulation":
        accumulation(conn, log=print, backfill=args.backfill)
        rows = accumulation_hits(conn)
        print(f"\n{len(rows)} names accumulating and not already held or watched")
        print(f"  {'sym':<7}{'first seen':<12}{'price':>9}{'vol x base':>11}"
              f"{'$vol/day':>11}{'runup':>7}{'nights':>7}  name")
        for x in rows:
            print(f"  {x['symbol']:<7}{x['first_day']:<12}{x['price']:>9.2f}{x['surge']:>11.1f}"
                  f"{(x['dollar_volume'] or 0)/1e6:>10.1f}M{x['runup']:>7.2f}{x['nights']:>7}  "
                  f"{(x['name'] or '')[:38]}")
        return 0
    if args.cmd == "show":
        h = hits(conn)
        print(f"scan of {h['day']} over {h.get('universe')} names screened {h.get('screened_at')}")
        for key, m in h["methods"].items():
            print(f"\n{m['name']}")
            for x in m["hits"][:15]:
                print(f"  {x['symbol']:<6} {x['pct']:.2f}  RS {x['rs_rank'] or '—':>3}  "
                      f"${(x['dollar_volume'] or 0)/1e6:,.0f}M/day  {x['days_flagged']}d  {x['name'][:40] if x['name'] else ''}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
