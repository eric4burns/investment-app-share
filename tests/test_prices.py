"""Price fetching, and the fallback that exists because one source is not enough.

Alpaca's free tier refuses OTC outright — "subscription does not permit querying
OTC data" — but for these symbols it does not return that error. It returns an
empty list, exactly like a symbol that simply had no trades. So two real
holdings sat in the table with no price at all, and the position showed a loss
while it was up 142%.

The tests here are mostly about that shape of failure: a source that answers
successfully with nothing, and a fallback that must not fire when the primary
actually worked.
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import prices

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())
    return conn


def epoch(day):
    # Yahoo stamps a daily bar at the opening bell, 13:30 UTC for a US market.
    return int(datetime.fromisoformat(day + "T13:30:00").replace(
        tzinfo=timezone.utc).timestamp())


def yahoo_body(rows, adj=None):
    """rows: (day, open, high, low, close, volume). adj: adjusted closes."""
    return json.dumps({"chart": {"error": None, "result": [{
        "meta": {"symbol": "TEST", "currency": "USD"},
        "timestamp": [epoch(r[0]) for r in rows],
        "indicators": {
            "quote": [{"open": [r[1] for r in rows], "high": [r[2] for r in rows],
                       "low": [r[3] for r in rows], "close": [r[4] for r in rows],
                       "volume": [r[5] for r in rows]}],
            "adjclose": [{"adjclose": adj if adj is not None else [r[4] for r in rows]}],
        }}]}})


def with_body(body):
    real = prices._get
    prices._get = lambda *a, **k: body
    return real


# ------------------------------------------------------------ parsing ----
real_get = with_body(yahoo_body([
    ("2026-08-26", 3.70, 3.90, 3.68, 3.835, 762261),
    ("2026-08-27", 3.90, 3.95, 3.01, 3.365, 4875515),
]))
try:
    bars = prices.fetch_yahoo("SIVEF", "2026-08-01", "2026-08-28")
finally:
    prices._get = real_get

check("bars come back", len(bars) == 2, f"{len(bars)} bars")
check("the epoch stamp becomes the right calendar day",
      bars and bars[0][0] == "2026-08-26", bars[0][0] if bars else None)
check("close, open, high, low and volume all land in the right slots",
      bars and bars[1] == ("2026-08-27", 3.365, 3.90, 3.95, 3.01, 4875515.0),
      bars[1] if bars else None)

# The last bar of a thin OTC name comes back with a null close and real volume:
# Yahoo has the day's trading but has not consolidated a closing print. A bar
# invented from that is a made-up price on a real holding.
real_get = with_body(yahoo_body([
    ("2026-08-27", 3.90, 3.95, 3.01, 3.365, 4875515),
    ("2026-08-28", 3.30, 3.40, 2.80, None, 2354338),
]))
try:
    bars = prices.fetch_yahoo("SIVEF", "2026-08-01", "2026-08-29")
finally:
    prices._get = real_get
check("a bar with no close is skipped, not invented", len(bars) == 1, f"{len(bars)} bars")
check("the surviving bar is the one that actually closed",
      bars and bars[0][0] == "2026-08-27", bars[0][0] if bars else None)

# Alpaca is fetched with adjustment=all, so its closes are split adjusted. Yahoo
# must match or a 2:1 split reads as a 50% overnight loss — a phantom that has
# already had to be dug out of this project's trade records once.
real_get = with_body(yahoo_body(
    [("2026-08-26", 100.0, 104.0, 98.0, 100.0, 1000),
     ("2026-08-27", 51.0, 52.0, 49.0, 50.0, 2000)],
    adj=[50.0, 50.0]))
try:
    bars = prices.fetch_yahoo("SPLITCO", "2026-08-01", "2026-08-28")
finally:
    prices._get = real_get
check("the adjusted close is used, not the raw one",
      bars and bars[0][1] == 50.0, bars[0][1] if bars else None)
check("open, high and low are scaled by the same factor as the close",
      bars and (bars[0][2], bars[0][3], bars[0][4]) == (50.0, 52.0, 49.0),
      bars[0][1:5] if bars else None)
check("an unsplit day is left alone",
      bars and bars[1][1] == 50.0 and bars[1][2] == 51.0, bars[1] if bars else None)

# An error payload must raise rather than be read as "no bars", which would be
# indistinguishable from a delisted symbol and silently cached as such.
real_get = with_body(json.dumps({"chart": {"error": {"code": "Not Found"}, "result": None}}))
try:
    prices.fetch_yahoo("NOPE", "2026-08-01", "2026-08-28")
    check("an error response raises rather than returning nothing", False)
except RuntimeError:
    check("an error response raises rather than returning nothing", True)
finally:
    prices._get = real_get


# ----------------------------------------------------------- fallback ----
def stub(alpaca, yahoo):
    a, y = prices.fetch_alpaca, prices.fetch_yahoo
    calls = {"alpaca": 0, "yahoo": 0}

    def fa(*args, **kw):
        calls["alpaca"] += 1
        if isinstance(alpaca, Exception):
            raise alpaca
        return list(alpaca)

    def fy(*args, **kw):
        calls["yahoo"] += 1
        if isinstance(yahoo, Exception):
            raise yahoo
        return list(yahoo)

    prices.fetch_alpaca, prices.fetch_yahoo = fa, fy
    return (a, y), calls


BAR = [("2026-08-27", 3.365, 3.90, 3.95, 3.01, 4875515.0)]


def run_ensure(symbol, alpaca, yahoo, fallback=True):
    conn = db()
    (a, y), calls = stub(alpaca, yahoo)
    was = prices.OTC_FALLBACK
    prices.OTC_FALLBACK = fallback
    try:
        res = prices.ensure_symbol(conn, symbol, "2018-01-01", "2030-01-01", as_equity=True)
    finally:
        prices.fetch_alpaca, prices.fetch_yahoo = a, y
        prices.OTC_FALLBACK = was
    stored = list(conn.execute(
        "SELECT p.source, COUNT(*) n FROM prices p JOIN securities s ON s.id = p.security_id "
        "WHERE s.symbol = ? GROUP BY p.source", (symbol,)))
    conn.close()
    return res, calls, {r["source"]: r["n"] for r in stored}

res, calls, stored = run_ensure("GOODSYM", BAR, BAR)
check("when the licensed source answers, the fallback is never called",
      calls["yahoo"] == 0, f"{calls['yahoo']} yahoo calls")
check("its bars are tagged with the feed that produced them",
      stored == {"alpaca-sip": 1}, stored)

# The failure that started this: a successful response carrying nothing.
res, calls, stored = run_ensure("OTCSYM", [], BAR)
check("an empty licensed response falls through to the fallback",
      calls["yahoo"] == 1, f"{calls['yahoo']} yahoo calls")
check("the fallback's bars are stored", stored == {"yahoo": 1}, stored)
check("the source is reported as the one actually used",
      res.get("source") == "yahoo", res.get("source"))

# A source is not allowed to launder its origin. Every bar records where it came
# from, so a chart drawn from an undocumented endpoint can be told apart from
# one drawn from the licensed feed.
res, calls, stored = run_ensure("ERRSYM", RuntimeError("HTTP 403"), BAR)
check("a failing licensed source also falls through", calls["yahoo"] == 1)
check("bars from the fallback are still tagged yahoo", stored == {"yahoo": 1}, stored)

res, calls, stored = run_ensure("BOTHBAD", [], [])
check("when neither source has anything, nothing is stored", stored == {}, stored)
check("and the caller is told", not res.get("ok") and res.get("error"), res)

res, calls, stored = run_ensure("NOFALL", [], BAR, fallback=False)
check("the fallback can be switched off", calls["yahoo"] == 0, f"{calls['yahoo']} yahoo calls")
check("with it off, an OTC symbol stores nothing", stored == {}, stored)


# ------------------------------------------------------------ SIP feed ----
# The daily cache moved from IEX to the consolidated feed. Three things have
# to hold: placeholder bars never reach the cache, the request never asks for
# the last fifteen minutes (the free plan answers 403 if it does), and the
# newest bar of a batch is replaced rather than frozen.
from datetime import timedelta

fixed_now = datetime(2026, 9, 2, 23, 0, 0, tzinfo=timezone.utc)
check("an end on or after today is clamped to a timestamp sixteen minutes ago",
      prices._sip_end("2026-09-02", fixed_now) == "2026-09-02T22:40:00Z",
      prices._sip_end("2026-09-02", fixed_now))
check("a far-future end is clamped the same way",
      prices._sip_end("2030-01-01", fixed_now) == "2026-09-02T22:40:00Z")
check("a past end passes through untouched",
      prices._sip_end("2024-01-01", fixed_now) == "2024-01-01")
# 03:00 UTC on the 3rd is 11 p.m. on the 2nd in New York: the 2nd is still
# today there, and a date-only end of the 2nd must be clamped, not passed.
late_evening = datetime(2026, 9, 3, 3, 0, 0, tzinfo=timezone.utc)
check("today is New York's date, not UTC's",
      prices._sip_end("2026-09-02", late_evening) == "2026-09-03T02:40:00Z",
      prices._sip_end("2026-09-02", late_evening))

check("zero volume with a single flat price is a placeholder",
      prices.is_placeholder(170.5, 170.5, 170.5, 170.5, 0))
check("a real bar with volume is not", not prices.is_placeholder(96, 96, 94.01, 94.01, 5))
check("a flat bar WITH volume is not — one print at one price is a trade",
      not prices.is_placeholder(87.73, 87.73, 87.73, 87.73, 1))

alpaca_body = json.dumps({"bars": [
    {"t": "2023-04-06T04:00:00Z", "o": 96, "h": 96, "l": 94.01, "c": 94.01, "v": 5, "n": 5},
    {"t": "2023-04-10T04:00:00Z", "o": 170.5, "h": 170.5, "l": 170.5, "c": 170.5, "v": 0, "n": 0},
    {"t": "2023-04-13T04:00:00Z", "o": 95.68, "h": 101.5, "l": 95.68, "c": 101.5, "v": 8, "n": 10},
], "next_page_token": None})
seen = {}
real_get, real_creds = prices._get, prices.alpaca_credentials
prices._get = lambda url, *a, **k: seen.setdefault("url", url) and alpaca_body or alpaca_body
prices.alpaca_credentials = lambda: ("key", "secret")
try:
    bars = prices.fetch_alpaca("ASST", "2023-04-01", "2030-01-01")
finally:
    prices._get, prices.alpaca_credentials = real_get, real_creds
check("the placeholder bar is dropped at the source",
      [b[0] for b in bars] == ["2023-04-06", "2023-04-13"], [b[0] for b in bars])
check("real bars keep their open, high, low, close and volume",
      bars and bars[0][1:] == (94.01, 96.0, 96.0, 94.01, 5.0), bars[0] if bars else None)
check("the request goes to the consolidated feed",
      "feed=sip" in seen.get("url", ""), seen.get("url"))
check("and never asks for the present",
      "end=2030" not in seen.get("url", "") and "end=20" in seen.get("url", ""), seen.get("url"))

# The newest bar is upserted; earlier ones are immutable.
conn = db()
prices.store(conn, "UPS", [("2026-09-01", 10.0, 9.0, 11.0, 8.0, 100.0),
                           ("2026-09-02", 12.0, 11.0, 12.5, 10.5, 50.0)], "alpaca-sip")
prices.store(conn, "UPS", [("2026-09-01", 99.0, 9.0, 11.0, 8.0, 100.0),
                           ("2026-09-02", 13.0, 11.0, 13.5, 10.5, 900.0)], "alpaca-sip")
rows = {r["bar_date"]: (r["close"], r["volume"]) for r in conn.execute(
    "SELECT bar_date, close, volume FROM prices p JOIN securities s ON s.id=p.security_id WHERE s.symbol='UPS'")}
check("the newest bar is replaced when fetched again — a session in progress finishes",
      rows.get("2026-09-02") == (13.0, 900.0), rows)
check("a finished bar is never overwritten",
      rows.get("2026-09-01") == (10.0, 100.0), rows)
conn.close()

# refeed replaces IEX rows only once SIP has answered, and leaves OTC alone.
conn = db()
prices.store(conn, "OLD", [("2023-04-06", 94.01, 96, 96, 94.01, 5),
                           ("2023-04-10", 170.5, 170.5, 170.5, 170.5, 0)], "alpaca")
prices.store(conn, "OTC", [("2026-08-27", 3.3, 3.3, 3.4, 3.2, 100)], "alpaca")
real_fetch = prices.fetch_alpaca
prices.fetch_alpaca = (lambda sym, a, b, feed=None:
                       [("2023-04-06", 94.11, 88, 103, 85, 1530), ("2023-04-10", 91, 95.9, 100.99, 85.51, 353)]
                       if sym == "OLD" else [])
try:
    r = prices.refeed(conn)
finally:
    prices.fetch_alpaca = real_fetch
tags = {row["symbol"]: (row["source"], row["n"]) for row in conn.execute(
    "SELECT s.symbol, p.source, COUNT(*) n FROM prices p JOIN securities s ON s.id=p.security_id GROUP BY 1,2")}
check("refeed replaces a symbol's IEX rows with SIP rows",
      tags.get("OLD") == ("alpaca-sip", 2), tags)
check("and reports how many placeholders it removed",
      r["refed"].get("OLD", {}).get("placeholders") == 1, r)
check("a symbol SIP does not serve keeps its rows and is named",
      tags.get("OTC") == ("alpaca", 1) and r["untouched"] == ["OTC"], (tags, r))
conn.close()

# ---- the nightly holdings refresh: OTC fallback and pseudo-symbols ----------
# sync_holdings went straight to Alpaca and never asked Yahoo, so SIVEF and
# KRKNF were only ever refreshed when somebody opened their chart. And the
# 401(k)'s PLAN: rows — names with spaces — were sent to Alpaca every night
# and failed with InvalidURL, six times.
conn = db()
from app import ledger as _ledger
inst = _ledger.get_or_create_institution(conn, "T")
acct = _ledger.get_or_create_account(conn, inst, "1", "Brokerage", "brokerage")
for i, sym in enumerate(("SIVEF", "NVDA", "PLAN:INDEX EQUITY FUND")):
    sid = _ledger.get_or_create_security(conn, sym)
    conn.execute("INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity, price, amount, source, source_id)"
                 " VALUES (?,?,?,?,?,?,?,?,?)", (acct, "2026-01-05", "buy", sid, 10, 1, -10, "t", f"t{i}"))
asked = []
real_a, real_y = prices.fetch_alpaca, prices.fetch_yahoo
prices.fetch_alpaca = lambda sym, a, b, feed=None: (asked.append(("alpaca", sym)) or
                                                   ([("2026-09-01", 100, 100, 101, 99, 5)] if sym == "NVDA" else []))
prices.fetch_yahoo = lambda sym, a, b: (asked.append(("yahoo", sym)) or
                                        ([("2026-09-01", 2.5, 2.5, 2.6, 2.4, 5)] if sym == "SIVEF" else []))
try:
    r = prices.sync_holdings(conn, "2026-01-01", "2026-09-02")
finally:
    prices.fetch_alpaca, prices.fetch_yahoo = real_a, real_y
check("the nightly refresh falls back to Yahoo for a name Alpaca has nothing on",
      ("yahoo", "SIVEF") in asked and r["priced"].get("SIVEF") == 1, (asked, r))
check("and stores it tagged as Yahoo's",
      conn.execute("SELECT source FROM prices p JOIN securities s ON s.id=p.security_id WHERE s.symbol='SIVEF'").fetchone()[0] == "yahoo")
check("but does not ask Yahoo when Alpaca answered", ("yahoo", "NVDA") not in asked, asked)
check("PLAN: pseudo-symbols are skipped, not sent to a price feed",
      "PLAN:INDEX EQUITY FUND" in r["skipped"] and not any(s.startswith("PLAN:") for _, s in asked), (r, asked))

# ---- load_bars(last=n) is the tail of the full read, exactly --------------
# The watchlist reads every indicator at the LAST bar, so it loads a tail; the
# tail must be the same bars the full read ends with, in the same order.
import random as _random
rnd = _random.Random(3)
long = [(f"{2018 + i // 250}-{(i // 21) % 12 + 1:02d}-{i % 21 + 1:02d}", 50 + rnd.random() * 50,
         50, 110, 40, 1000 + i) for i in range(900)]
long = sorted({b[0]: b for b in long}.values())
prices.store(conn, "TAIL", long, "alpaca-sip")
full = prices.load_bars(conn, "TAIL", "2018-01-01", "2030-01-01")
tail = prices.load_bars(conn, "TAIL", "2018-01-01", "2030-01-01", last=520)
check("load_bars(last=520) is exactly the last 520 bars of the full read",
      len(tail) == 520 and tail == full[-520:], (len(tail), len(full)))
check("a tail longer than the history is the whole history",
      prices.load_bars(conn, "TAIL", "2018-01-01", "2030-01-01", last=5000) == full)
from app import indicators as _I
check("RSI at the last bar is the same number from the tail as from the full series",
      _I.rsi(tail, 14)[-1] == _I.rsi(full, 14)[-1], (_I.rsi(tail, 14)[-1], _I.rsi(full, 14)[-1]))
check("and so is the 200-day average", _I.sma(tail, 200)[-1] == _I.sma(full, 200)[-1])
conn.close()


# ---------------------------------------------------------------- bad prints
# A low below a fifth of both the open and the close is a bad print (SPY's
# 2026-02-02 bar arrived with low 68.64 against 685.90 / 691.70) and is clipped
# to the lower of open and close; a genuine wide range is left alone.
check("a bad-print low is clipped to the lower of open and close",
      prices._plausible_low(685.90, 68.64, 691.70) == 685.90)
check("a wide but real range is kept (open 100, low 45, close 90)",
      prices._plausible_low(100.0, 45.0, 90.0) == 45.0)
check("a bar with no open or close is left as it came",
      prices._plausible_low(None, 68.64, 691.70) == 68.64)

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
