"""How long the app takes to answer, asserted rather than assumed.

Every endpoint here has a budget. These are not micro-benchmarks — they are wide
enough that ordinary variation never trips them, and narrow enough to catch the
kind of regression that turns a page load into something a user reports as "the
app is not working".

That is not hypothetical. Moving the price cache onto the connection object
looked correct and silently disabled caching entirely, because sqlite3.Connection
has no __dict__ and the setattr raised. One query per symbol became 25,333 of
them, /api/performance went from under a second to fifteen, and with the payload
fetched twice at startup the page sat blank for thirty seconds. Every one of the
415 other tests passed throughout, because none of them looks at time.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import web
from app.ledger import connect
from app import prices

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


# Budgets in seconds, measured against a ledger this test BUILDS.
#
# They used to run against whatever ledger happened to be on the machine, which
# meant the numbers meant something different for every person who ran them and
# nothing at all on a fresh clone: an empty database answers every endpoint in a
# hundredth of a second and the whole file went green while measuring nothing.
# Printing the row count alongside the time made that visible without fixing it.
#
# So the load is generated: 7,000 transactions and ~25,600 price bars, the scale
# of a real two-year ledger. The budget now means the same thing everywhere, and
# a regression shows up on a checkout that has never imported a statement.
SCALE_TXNS, SCALE_SYMS, SCALE_BARS = 7000, 30, 800

# Each budget is roughly FIVE TIMES the time the endpoint currently takes on the
# generated load. That multiple is the point: it catches the order-of-magnitude
# regression these exist for (a disabled cache turned one endpoint into fifteen
# seconds) while leaving so much headroom that ordinary machine-to-machine
# variation can never trip it. They are not "current time plus a bit", which is
# how a performance test becomes a flaky test.
#
# The old numbers were calibrated against the author's own ledger of about
# sixteen holdings. This load carries thirty-two, so /api/diagnose — which scores
# every holding — legitimately takes longer here than it ever did there. It is
# the slowest endpoint by a wide margin and the one that scales worst with the
# number of positions.
BUDGETS = [
    ("/api/performance", "build_payload", {}, 3.0),            # ~0.6s
    ("/api/chart", "chart_payload",
     {"symbol": ["SY01"], "timeframe": ["D"],
      "indicators": ["volume,sma:20,sma:50"]}, 1.0),           # ~0.08s
    ("/api/watchlist", "watchlist_payload", {}, 1.0),          # ~0.05s
    ("/api/diagnose", "diagnose_payload", {}, 15.0),           # ~3.7s
    # The budget endpoint classifies every transaction several times over —
    # once for the tab, again for trends, again for recurring, again for the
    # spreadsheet comparison — so it is the one most likely to creep.
    ("/api/budget", "budget_payload", {}, 1.0),                # ~0.10s
]

_RUNNER = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from app import web
out = {}
for name, fn, params in json.loads(sys.argv[2]):
    t0 = time.perf_counter()
    try:
        getattr(web, fn)(params)
        out[name] = [round(time.perf_counter() - t0, 4), None]
    except Exception as exc:
        out[name] = [None, f"{type(exc).__name__}: {exc}"]
print(json.dumps(out))
'''


def _seed(path):
    """A ledger of a known size, built from nothing."""
    import random
    from datetime import date, timedelta
    from app.ledger import (connect as _c, get_or_create_institution,
                            get_or_create_account, get_or_create_security)
    conn = _c(path)
    inst = get_or_create_institution(conn, "Test Broker")
    acc = get_or_create_account(conn, inst, "A1", "Individual - TOD",
                                "brokerage", "taxable")
    chk = get_or_create_account(conn, inst, "A2", "Checking", "checking", "na")
    rng = random.Random(7)
    syms = [f"SY{i:02d}" for i in range(SCALE_SYMS)] + ["SPY", "QQQ"]
    sids = {sym: get_or_create_security(conn, sym) for sym in syms}
    d0 = date.today() - timedelta(days=SCALE_BARS + 5)
    bars = []
    for sym in syms:
        px = 50.0
        for i in range(SCALE_BARS):
            px = max(1.0, px * (1 + rng.gauss(0, 0.02)))
            bars.append((sids[sym], (d0 + timedelta(days=i)).isoformat(),
                         px, px * 1.01, px * 0.99, px, None, 1000, "test"))
    conn.executemany("""INSERT OR IGNORE INTO prices
        (security_id,bar_date,open,high,low,close,adj_close,volume,source)
        VALUES (?,?,?,?,?,?,?,?,?)""", bars)
    txns = []
    for i in range(SCALE_TXNS):
        sym = syms[i % len(syms)]
        when = (d0 + timedelta(days=rng.randrange(SCALE_BARS))).isoformat()
        if i % 7 == 0:
            txns.append((chk, when, "income", None, None, None, 2500.0, 0, 0,
                         "L3HARRIS TECH IN PAYROLL", "test", f"t{i}"))
        elif i % 5 == 0:
            txns.append((chk, when, "expense", None, None, None, -60.0, 0, 0,
                         "HEB GROCERY", "test", f"t{i}"))
        else:
            q = 10 if i % 2 else -5
            txns.append((acc, when, "buy" if q > 0 else "sell", sids[sym], q,
                         50.0, -500.0 if q > 0 else 250.0, 0, 0,
                         f"{sym} trade", "test", f"t{i}"))
    conn.executemany("""INSERT OR IGNORE INTO transactions
        (account_id,txn_date,kind,security_id,quantity,price,amount,fees,
         commission,description,source,source_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", txns)
    conn.commit()
    n_t = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    n_b = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    conn.close()
    return n_t, n_b


_root = str(Path(__file__).resolve().parent.parent)
_tmp = tempfile.mkdtemp(prefix="perfbudget-")
_db = str(Path(_tmp) / "seeded.db")
try:
    _n_txns, _n_bars = _seed(_db)
    check("the load this measures against was actually built",
          _n_txns >= SCALE_TXNS * 0.9 and _n_bars >= SCALE_SYMS * SCALE_BARS * 0.9,
          f"{_n_txns:,} txns / {_n_bars:,} bars")

    # A separate process, because ledger.DB_PATH is resolved at import and the
    # endpoints are already imported here. This is how smoke.sh does it too.
    _env = {**os.environ, "INVESTMENT_APP_DB": _db,
            "INVESTMENT_APP_CONFIG": "/nonexistent/no-config.json"}
    _spec = json.dumps([[n, f, p] for n, f, p, _b in BUDGETS])

    def _timed_run():
        out = subprocess.run([sys.executable, "-c", _RUNNER, _root, _spec],
                             capture_output=True, text=True, env=_env, timeout=300)
        return (json.loads(out.stdout.strip().splitlines()[-1])
                if out.stdout.strip() else {}), out.stderr

    # Timed once, and again only if something missed its budget, keeping the
    # better time of the two.
    #
    # These budgets have four to five times headroom over the expected figures,
    # so an ordinary slow moment cannot reach them — but the whole suite runs a
    # server and a headless browser, and on 2026-09-10 this ran at 5.11s against
    # a 3.0s budget and 25.05s against 15.0s, then passed 37/37 alone minutes
    # later on unchanged code. A test that fails on a busy machine teaches
    # people to ignore a red suite, which costs more than the regression it was
    # guarding against.
    #
    # A genuine regression is not transient: it misses on both runs and still
    # fails. This only forgives contention.
    _times, _err_out = _timed_run()
    if not _times:
        check("the timed run produced results", False, _err_out[-160:])
    elif any(_times.get(n, [None])[0] is not None and _times[n][0] >= b
             for n, _f, _p, b in BUDGETS):
        _second, _ = _timed_run()
        for _n, _f, _p, _b in BUDGETS:
            a = _times.get(_n, [None, None])
            c = _second.get(_n, [None, None])
            if a[0] is not None and c[0] is not None:
                _times[_n] = [min(a[0], c[0]), a[1] or c[1]]
    _scale = f"{_n_txns:,} txns / {_n_bars:,} bars"
    for _name, _fn, _params, _budget in BUDGETS:
        _took, _err = _times.get(_name, [None, "not run"])
        if _err:
            check(f"{_name} responds at all", False, _err)
            continue
        check(f"{_name} answers within {_budget:g}s over {_scale}",
              _took < _budget,
              f"{_took:.2f}s — missed on BOTH runs, so this is a regression "
              f"rather than a busy machine")
        # A budget met in no time at all is the shape of a measurement that did
        # not happen — an empty ledger, a short-circuit, an endpoint that
        # returned an error dict without doing the work.
        check(f"{_name} did real work rather than short-circuiting",
              _took > 0.001, f"{_took:.4f}s over {_scale}")
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

# The cache is the thing that makes all of the above possible, so assert it
# directly rather than only through its effects. A cache that returns a fresh
# object every call is not a cache, and that is exactly what shipped.
_conn = connect()
_first = prices.load_series(_conn, "SPY")
_second = prices.load_series(_conn, "SPY")
check("repeated reads return the SAME cached object, not an equal copy",
      _first is _second,
      "load_series is re-querying; check that connect() returns a "
      "LedgerConnection, since sqlite3.Connection cannot hold attributes")

# What matters is not how often load_series is CALLED — a cheap cached call is
# fine — but how often it reaches the database. Counting calls would have failed
# on healthy code; counting misses is the assertion with meaning.
_stats = {"calls": 0, "misses": 0}
_real_cache = prices._cache_for


def _watched(conn):
    cache = _real_cache(conn)
    _stats["calls"] += 1
    return cache


_real_load = prices.load_series


def _counting(conn, symbol):
    sym = (symbol or "").upper()
    if sym not in _real_cache(conn):
        _stats["misses"] += 1
    return _real_load(conn, symbol)


prices.load_series = _counting
try:
    _payload = web.build_payload({})
finally:
    prices.load_series = _real_load

# The Overview's three additions from the September review: the return in
# dollars, the last session's change, and how fresh the page is.
_s = _payload["summary"]
check("the range's gain in dollars is value less start less net deposits",
      abs(_s["gain_usd"] - round(_s["end_value"] - _s["begin_value"] - _s["net_external_flow"], 2)) < 0.01,
      _s.get("gain_usd"))
check("the last session names both dates and a flow-adjusted change",
      _s["day"] is None or {"date", "prev_date", "change_usd", "change_pct", "flow"} <= set(_s["day"]),
      _s.get("day"))
check("the last session is the latest date on the curve",
      _s["day"] is None or _s["day"]["date"] == _payload["series"][-1]["date"],
      (_s.get("day") or {}).get("date"))
check("freshness reports the price date and the last scoring, even when unscored",
      {"prices_to", "scored_for", "scored_at"} <= set(_s["freshness"]), _s.get("freshness"))

# One payload touches a few dozen distinct symbols. A miss per lookup means the
# cache is not holding, which is precisely the regression that made this fifteen
# seconds instead of one.
check("each price series is read from the database roughly once",
      _stats["misses"] < 300, f"{_stats['misses']:,} cache misses")

# ------------------------------------------------- price fetch freshness ----
# The diagnose endpoint spent four seconds on the network on EVERY request,
# because "is this symbol up to date" was asked as "do we hold a bar dated on or
# after `end`" while callers pass an end date of today or later — sectors passes
# 2030-01-01. No daily bar exists for today until the close, and none ever
# exists for a Saturday, so the answer was almost always no and thirteen symbols
# were refetched in full each time.
#
# These tests are written against that mistake: the guard has to hold when the
# newest bar is OLDER than the end date asked for, which is the normal case, not
# the exception.
import sqlite3
from datetime import datetime, timedelta, timezone

mem = sqlite3.connect(":memory:")
mem.row_factory = sqlite3.Row
mem.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())

check("an unknown symbol has never been checked",
      not prices.checked_recently(mem, "NEVERSEEN"))

prices.record_fetch(mem, "TESTSYM", "ok", since="2018-01-01")
check("a symbol just fetched counts as fresh", prices.checked_recently(mem, "TESTSYM"))
check("freshness is case-insensitive, like every other symbol lookup",
      prices.checked_recently(mem, "testsym"))
check("a fetch older than the window is stale",
      not prices.checked_recently(mem, "TESTSYM", within=0))

# Failures are recorded too. A delisted ticker returns nothing however often it
# is asked, and retrying it every request puts a round trip on every page load.
prices.record_fetch(mem, "BADSYM", "error: HTTPError", since="2018-01-01")
check("a failed fetch also counts as checked", prices.checked_recently(mem, "BADSYM"))

# The guard has to stop the network call, not merely report a cache hit. Count
# the calls rather than making the fetcher raise: ensure_symbol catches every
# exception and turns it into a returned error, so a raising stub is swallowed
# and the test passes whether or not the network was reached.
prices.store(mem, "CACHEDSYM", [("2026-08-20", 10.0, 10.0, 10.0, 10.0, 100)], "test")
prices.record_fetch(mem, "CACHEDSYM", "ok", since="2018-01-01")
_real_fetch = prices.fetch_alpaca
_calls = []


def _counted(symbol, start, end):
    _calls.append((symbol, start, end))
    return []


prices.fetch_alpaca = _counted
# ensure_symbol returns early when there is no credentials file, so on any
# machine without data/.alpaca every assertion below about WHEN the network is
# reached was failing for a reason that has nothing to do with the guard being
# tested. The credentials are stubbed so these test the freshness logic itself
# rather than the contents of the developer's home directory. The fetcher above
# is already stubbed, so nothing leaves the machine either way.
_real_creds = prices.alpaca_credentials
prices.alpaca_credentials = lambda: ("test-key", "test-secret")
try:
    # An end date far in the future, exactly as sectors.rotation passes it.
    res = prices.ensure_symbol(mem, "CACHEDSYM", "2018-01-01", "2030-01-01", as_equity=True)
    check("a recently checked symbol never reaches the network",
          not _calls and res.get("source") == "cache", f"{len(_calls)} fetches")

    # A symbol we hold nothing for must still be fetched, or a new watchlist
    # entry would never get any data at all.
    _calls.clear()
    prices.ensure_symbol(mem, "BRANDNEW", "2018-01-01", "2030-01-01", as_equity=True)
    check("a symbol with no data is still fetched", len(_calls) == 1, f"{len(_calls)} fetches")

    # And a stale symbol asks only for the missing tail. Re-requesting eight
    # years to learn about one new day was most of the cost of a refresh.
    # Covered back to 2018, but last asked about a week ago: the tail is the
    # only thing missing.
    prices.store(mem, "STALESYM", [("2026-08-20", 10.0, 10.0, 10.0, 10.0, 100)], "test")
    mem.execute("INSERT OR REPLACE INTO price_fetches "
                "(symbol, attempted_at, outcome, earliest) VALUES (?,?,?,?)",
                ("STALESYM", (datetime.now(timezone.utc) - timedelta(days=7))
                 .isoformat(timespec="seconds"), "ok", "2018-01-01"))
    _calls.clear()
    prices.ensure_symbol(mem, "STALESYM", "2018-01-01", "2030-01-01", as_equity=True)
    check("a stale symbol is refetched", len(_calls) == 1, f"{len(_calls)} fetches")
    check("the refetch asks only for the tail, not the whole history",
          _calls and _calls[0][1] > "2026-01-01", _calls[0][1] if _calls else None)

    # Freshness alone must not stop a BACKFILL. The backtest asks from 2015
    # while the chart asks from 2018; a symbol checked minutes ago for the chart
    # has nothing before 2018 to give the backtest, and answering "fresh" there
    # would hand it a shorter history than it asked for without saying so.
    _calls.clear()
    prices.ensure_symbol(mem, "CACHEDSYM", "2015-01-01", "2030-01-01", as_equity=True)
    check("a request reaching further back than any before it still fetches",
          len(_calls) == 1, f"{len(_calls)} fetches")
    check("the backfill asks from the earlier start, not the tail",
          _calls and _calls[0][1] == "2015-01-01", _calls[0][1] if _calls else None)

    # And once that wider window has been asked for, it is remembered — asking
    # again from 2015, or from anywhere inside it, is served from cache.
    prices.record_fetch(mem, "CACHEDSYM", "ok", since="2015-01-01")
    _calls.clear()
    prices.ensure_symbol(mem, "CACHEDSYM", "2015-01-01", "2030-01-01", as_equity=True)
    prices.ensure_symbol(mem, "CACHEDSYM", "2018-01-01", "2030-01-01", as_equity=True)
    check("the widened window is remembered for later requests",
          not _calls, f"{len(_calls)} fetches")

    # And with no credentials the guard has to REFUSE rather than pretend: a
    # symbol nothing is held for cannot be answered from cache, and reporting it
    # as cached would leave a position permanently unpriced with nothing said.
    prices.alpaca_credentials = lambda: None
    _calls.clear()
    _nokey = prices.ensure_symbol(mem, "NOKEYSYM", "2018-01-01", "2030-01-01",
                                  as_equity=True)
    check("with no credentials and nothing cached the failure is reported",
          _nokey["ok"] is False and _nokey.get("error"), _nokey)
    check("and no network call is attempted", not _calls, f"{len(_calls)} fetches")
finally:
    prices.fetch_alpaca = _real_fetch
    prices.alpaca_credentials = _real_creds
mem.close()

# ---------------------------------------------------- response cache ----
# The server is CPU-bound Python behind a GIL, so two browser tabs do not share
# the machine, they queue for it: opening a second tab while the first was
# loading starved it for half a minute, eleven panels each recomputing what the
# other tab had just computed. Caching by database state took that to 0.2s.
#
# The stamp is faked here rather than touching the real ledger, which is what
# the contract actually is: same database state means the same answer, and any
# change at all means recompute.
_real_stamp = web._db_stamp
_stamp = [1]
web._db_stamp = lambda: _stamp[0]
try:
    web.clear_response_cache()
    calls = []

    def build():
        calls.append(1)
        return {"value": len(calls)}

    first = web.cached_payload("/api/thing", {}, build)
    second = web.cached_payload("/api/thing", {}, build)
    check("a repeated read is not recomputed", len(calls) == 1, f"{len(calls)} builds")
    check("and returns the same answer", first is second, (first, second))

    # A different query is a different question.
    web.cached_payload("/api/thing", {"symbol": ["IREN"]}, build)
    check("a different query is computed separately", len(calls) == 2, f"{len(calls)} builds")

    # Any change to the database invalidates everything derived from it. Without
    # this the app would serve a stale portfolio after every import.
    _stamp[0] = 2
    third = web.cached_payload("/api/thing", {}, build)
    check("a changed database recomputes", len(calls) == 3, f"{len(calls)} builds")
    check("and the new answer is served, not the old one",
          third != first, (first, third))

    # The cache must not grow without bound.
    for i in range(web._CACHE_MAX + 20):
        web.cached_payload("/api/thing", {"n": [str(i)]}, build)
    check("the cache is bounded", len(web._RESPONSE_CACHE) <= web._CACHE_MAX,
          len(web._RESPONSE_CACHE))
finally:
    web._db_stamp = _real_stamp
    web.clear_response_cache()

# ---------------------------------------------------- cache epoch ----
# The stamp used to be the ledger file's mtime, which every five-minute chart
# open moved (intraday candles, the fetch log) — the whole cache dropped for
# writes no answer reads. Now it is an epoch that only meaningful writes
# bump, automatically, from the connection itself. The property that matters
# is the second half: a real change can never leave a cached answer standing.
import tempfile as _tf
import os as _os
from app import ledger as _ledger, prices as _prices, journal as _journal, watchlist as _wl
_tmp = _tf.mkdtemp()
_real_db, _real_conn = web.DB_PATH, web._STAMP_CONN
web.DB_PATH = Path(_tmp) / "epoch.db"
web._STAMP_CONN = None
try:
    c = _ledger.connect(web.DB_PATH)
    _prices.store(c, "AAA", [("2026-09-10", 9.0)], "test")       # the symbol exists
    e0 = web._db_stamp()
    # Bookkeeping writes, on their own request's connection: no bump. This is
    # the chart-open path — a five-minute candle refresh and a fetch-log row.
    c_req = _ledger.connect(web.DB_PATH)
    _prices.store_intraday(c_req, "AAA", "5m", [("2026-09-11T14:35:00", 1, 1, 1, 1, 10)])
    _prices.record_fetch(c_req, "AAA", "ok", since="2026-01-01")
    c_req.close()
    check("intraday candles and the fetch log do not move the epoch",
          web._db_stamp() == e0, (e0, web._db_stamp()))
    # Real changes: each one bumps.
    seen = [e0]
    def bumped(label, fn):
        fn()
        now = web._db_stamp()
        check(f"{label} moves the epoch", now > seen[-1], (seen[-1], now))
        seen.append(now)
    bumped("a daily bar", lambda: _prices.store(c, "AAA", [("2026-09-11", 10.0)], "test"))
    bumped("a watchlist edit", lambda: (_wl.add(c, "AAA", ["t"]), c.commit()))
    bumped("a journal entry", lambda: (_journal.record(c, "2026-09-11", "AAA", "me", "buy"), c.commit()))
    def _txn():
        inst = _ledger.get_or_create_institution(c, "T")
        acct = _ledger.get_or_create_account(c, inst, "1", "B", "brokerage")
        _ledger.insert_transaction(c, {"account_id": acct, "txn_date": "2026-09-11", "kind": "deposit",
                                       "amount": 1.0, "source": "t", "source_id": "1"})
        c.commit()
    bumped("an import", _txn)
    def _script_commit():
        # executescript() commits implicitly, bypassing commit(); closing the
        # connection must still land the bump.
        c2 = _ledger.connect(web.DB_PATH)
        c2.execute("INSERT INTO institutions (name) VALUES ('script')")
        c2.executescript("CREATE TABLE IF NOT EXISTS zz (a)")
        c2.close()
    bumped("a write committed by executescript, then closed,", _script_commit)
    def _with_block():
        with _ledger.connect(web.DB_PATH) as c3:
            c3.execute("INSERT INTO institutions (name) VALUES ('with')")
    bumped("a write inside `with conn:`", _with_block)
    c.execute("SELECT 1").fetchall(); c.commit()
    check("a commit with nothing written does not move it", web._db_stamp() == seen[-1])
    # And the cache honours it end to end.
    web.clear_response_cache()
    n = []
    web.cached_payload("/api/x", {}, lambda: n.append(1) or len(n))
    web.cached_payload("/api/x", {}, lambda: n.append(1) or len(n))
    check("the same answer is served while nothing changed", len(n) == 1, len(n))
    _wl.add(c, "BBB", []); c.commit()
    web.cached_payload("/api/x", {}, lambda: n.append(1) or len(n))
    check("and recomputed after a real change", len(n) == 2, len(n))
    c.close()
finally:
    if web._STAMP_CONN is not None:
        web._STAMP_CONN.close()
    web.DB_PATH, web._STAMP_CONN = _real_db, _real_conn
    web.clear_response_cache()
    for f in Path(_tmp).glob("*"):
        f.unlink()
    _os.rmdir(_tmp)

# ---------------------------------------------------- single flight ----
# Two identical misses at once used to compute the answer twice — for the
# watchlist outlook, twice fifteen seconds behind one GIL.
import threading as _th
web.clear_response_cache()
_real_stamp2 = web._db_stamp
web._db_stamp = lambda: 7
try:
    builds, gate = [], _th.Event()
    def slow():
        builds.append(1); gate.wait(2.0); return {"n": len(builds)}
    got = []
    ts = [_th.Thread(target=lambda: got.append(web.cached_payload("/api/slow", {}, slow))) for _ in range(3)]
    for t in ts: t.start()
    import time as _time; _time.sleep(0.2); gate.set()
    for t in ts: t.join(5)
    check("three concurrent identical misses build once", len(builds) == 1, len(builds))
    check("and every caller gets that one answer", len(got) == 3 and all(g == {"n": 1} for g in got), got)
finally:
    web._db_stamp = _real_stamp2
    web.clear_response_cache()

# ---------------------------------------------------- verdict cache ----
# Watchlist verdicts are served from verdict_cache and only re-scored when a
# name's newest bar (or the run's context) changes. The page used to score
# all 189 names inline on every cache miss. The one thing that must never
# change: no watchlist name is ever recorded as an app decision.
from app import outlook as _outlook
from datetime import date
import random as _rnd
_tmp2 = _tf.mkdtemp()
try:
    vc = _ledger.connect(Path(_tmp2) / "vc.db")
    r = _rnd.Random(5); px = 50.0; rows = []
    d = date(2025, 1, 1)
    while len(rows) < 320:
        d += timedelta(days=1)
        if d.weekday() < 5:
            px = max(1.0, px * (1 + r.gauss(0.0005, 0.02)))
            rows.append((d.isoformat(), px, px * 0.99, px * 1.02, px * 0.98, 1000))
    _prices.store(vc, "WLA", rows, "test")
    _wl.add(vc, "WLA", []); vc.commit()
    asof = rows[-1][0]
    one = _outlook.run(vc, asof=asof, dry_run=True, scope="watchlist", use_cache=True)
    two = _outlook.run(vc, asof=asof, dry_run=True, scope="watchlist", use_cache=True)
    check("the first watchlist run scores and stores", one["cache"] == {"hits": 0, "stored": 1}, one["cache"])
    check("the second is served from the cache", two["cache"] == {"hits": 1, "stored": 0}, two["cache"])
    norm = lambda x: json.loads(json.dumps(x, default=str))
    check("and returns the same verdict", norm(one["results"]["WLA"]) == two["results"]["WLA"])
    check("no watchlist name is recorded as an app decision",
          vc.execute("SELECT COUNT(*) FROM decisions WHERE source='app'").fetchone()[0] == 0)
    nd = date.fromisoformat(asof) + timedelta(days=3)
    _prices.store(vc, "WLA", [(nd.isoformat(), px * 1.01, px, px * 1.03, px * 0.99, 1000)], "test")
    three = _outlook.run(vc, asof=nd.isoformat(), dry_run=True, scope="watchlist", use_cache=True)
    check("a new bar makes the cached verdict stale and it is re-scored",
          three["cache"] == {"hits": 0, "stored": 1}, three["cache"])
    plain = _outlook.run(vc, asof=nd.isoformat(), dry_run=True, scope="watchlist")
    check("a cached run and an uncached run agree",
          norm(plain["results"]["WLA"]) == norm(three["results"]["WLA"]))
    vc.close()
finally:
    for f in Path(_tmp2).glob("*"):
        f.unlink()
    _os.rmdir(_tmp2)

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
