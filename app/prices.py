"""Price sources.

Deliberately behind one interface so a source can be swapped in an afternoon
rather than a rewrite — free tiers change terms and endpoints break.

Current state (2026-08-29):
  FRED      WORKING, free, no API key, no signup. Daily index levels for the
            major benchmarks. This is what makes benchmark comparison possible
            today. Caveat: these are PRICE indices, not total return, so they
            understate the real benchmark by roughly the dividend yield
            (~1.3%/yr for the S&P). Reported honestly rather than silently.
  Alpaca    WORKING with a free paper account's key. Put the key id and
            secret in data/.alpaca (gitignored) as two lines and it activates.
            Daily bars come from the SIP (consolidated) feed — see ALPACA_FEED
            for why, and for the fifteen-minute rule that comes with it.
  CSV       Drop <SYMBOL>.csv (date,close) into data/prices/ for anything else.
  Stooq     UNAVAILABLE. Now serves a JavaScript proof-of-work bot challenge;
            defeating it is out of bounds, so this source is simply closed.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config, netsafe
from .ledger import ROOT, get_or_create_security

# Benchmark alias -> (FRED series id, human label, caveat)
FRED_BENCHMARKS = {
    "SP500":     ("SP500",     "S&P 500",           "price index, excludes dividends"),
    "SPX":       ("SP500",     "S&P 500",           "price index, excludes dividends"),
    "SPY":       ("SP500",     "S&P 500 (via index)", "proxy: SPY tracks this index; price only"),
    "NASDAQ100": ("NASDAQ100", "Nasdaq 100",        "price index, excludes dividends"),
    "NDX":       ("NASDAQ100", "Nasdaq 100",        "price index, excludes dividends"),
    "QQQ":       ("NASDAQ100", "Nasdaq 100 (via index)", "proxy: QQQ tracks this index; price only"),
    "NASDAQ":    ("NASDAQCOM", "Nasdaq Composite",  "price index, excludes dividends"),
    "DJIA":      ("DJIA",      "Dow Jones Industrial Average", "price index, excludes dividends"),
    "DOW":       ("DJIA",      "Dow Jones Industrial Average", "price index, excludes dividends"),
}

# Money market / core cash funds hold a stable $1.00 NAV by design, so they
# need no price feed — but they DO need to be valued, or the cash sitting in
# Fidelity's core position silently reads as zero.
#
# The yield itself is already captured correctly: Fidelity books the monthly
# payout as a DIVIDEND (cash in) and the sweep back as a REINVESTMENT (cash
# out, shares in). Those net to the dividend amount, so valuing the shares at
# $1.00 counts the yield exactly once — no double count.
MONEY_MARKET_NAV = 1.00
MONEY_MARKET_FUNDS = {
    "SPAXX",   # Fidelity Government Money Market (default core position)
    "FDRXX",   # Fidelity Government Cash Reserves
    "FZFXX",   # Fidelity Treasury Money Market
    "SPRXX",   # Fidelity Money Market Fund
    "FCASH",   # Fidelity cash
    "FDIC",    # FDIC-insured deposit sweep
    "QACDS",   # Fidelity HSA cash sweep
}


def is_cash_like(symbol: str | None) -> bool:
    """A money-market sweep or the ledger's own unswept-cash row ("CASH"),
    which is not the bank ticker CASH and must never be priced as one."""
    return bool(symbol) and (is_money_market(symbol) or symbol.strip().upper() == "CASH")


def is_money_market(symbol: str) -> bool:
    return (symbol or "").strip().upper() in MONEY_MARKET_FUNDS


FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
ALPACA_KEY_FILE = ROOT / "data" / ".alpaca"
PRICE_CSV_DIR = ROOT / "data" / "prices"


def _get(url: str, headers: dict | None = None, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "investment-app/0.1"})
    # Alpaca calls pass the key in `headers`; netsafe keeps them on Alpaca's host.
    with netsafe.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def resolve_benchmark(name: str) -> tuple[str, str, str] | None:
    """Map a user-typed benchmark ('spy', 'QQQ', 'S&P 500') to a FRED series."""
    key = name.strip().upper().replace("&", "").replace(" ", "").replace("-", "")
    return FRED_BENCHMARKS.get(key)


def fetch_fred(series: str) -> list[tuple[str, float]]:
    """Daily observations for a FRED series. Missing days (holidays) are dropped."""
    text = _get(FRED_URL.format(series=series))
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not row[0][:1].isdigit():
            continue
        try:
            out.append((row[0], float(row[1])))
        except ValueError:
            continue  # FRED writes '.' for non-trading days
    return out


def alpaca_credentials() -> tuple[str, str] | None:
    """Key id and secret from data/.alpaca.

    Comment lines are skipped. The template ships with instructions in it and
    tells the reader to delete them — but the parser used to take the first two
    non-empty lines whatever they were, so leaving a comment in place fed "# Line
    1: Key ID" to the API as a credential and produced an authentication error
    that said nothing about the real cause.
    """
    if not ALPACA_KEY_FILE.exists():
        return None
    lines = [l.strip() for l in ALPACA_KEY_FILE.read_text().splitlines()
             if l.strip() and not l.strip().startswith("#")]
    return (lines[0], lines[1]) if len(lines) >= 2 else None


# Which Alpaca feed the daily cache is built from.
#
# The free plan offers two. IEX is one exchange: on a large name it sees a
# slice of the tape, and on a small one it can see almost nothing. ASST in
# April 2023 is the case that exposed it — IEX printed 1 to 8 shares on the
# days it printed at all, and on the days it saw NO trade Alpaca emitted a bar
# with zero volume and open, high, low and close all equal to the same stale
# number (170.50, ten times in a month) while the consolidated tape showed
# hundreds to thousands of shares trading between 85 and 122. Those
# placeholder bars flicker against the real ones and made the series look 80%
# volatile from one day to the next, which is what turned a 6% position into
# "33% of the portfolio's risk" on the Diagnose tab.
#
# SIP is every exchange, consolidated. The free plan serves it for history but
# refuses anything within the last fifteen minutes — a request whose end is
# now, today, or in the future is answered 403 "subscription does not permit
# querying recent SIP data". So the end is clamped to just over fifteen minutes
# ago whenever the caller asks for the present. For end-of-day bars that costs
# nothing; the last session's bar is hours old by the time anything here reads
# it. OTC names are served by neither feed and still fall through to Yahoo.
ALPACA_FEED = "sip"
# Rows are tagged by the feed that produced them, so a cache built before the
# switch is distinguishable from one built after it, and refeed() knows what
# is left to replace.
ALPACA_SOURCE = {"sip": "alpaca-sip", "iex": "alpaca"}
SIP_DELAY_MINUTES = 20


def _sip_end(end: str, now: datetime | None = None) -> str:
    """The latest end the free plan will answer for SIP.

    A date-only end is inclusive, so "today" reaches into the future and is
    refused. Anything on or after today's date becomes an explicit timestamp
    twenty minutes ago — Alpaca reads "fifteen" with its own clock and the request latency, and sixteen was refused — and a past date passes through untouched.

    "Today" is New York's date, not UTC's. Between 8 p.m. and midnight
    Eastern the UTC date has already rolled over, so a date-only end of the
    Eastern date read as "yesterday" here, was passed through unclamped, and
    Alpaca refused it as recent — every request the market-wide screen made
    at 11 p.m. came back 403 and it looked like the key had been throttled.
    """
    from zoneinfo import ZoneInfo
    now = now or datetime.now(timezone.utc)
    today_ny = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if (end or "")[:10] >= today_ny:
        return (now - timedelta(minutes=SIP_DELAY_MINUTES)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return end


def is_placeholder(o, h, l, c, v) -> bool:
    """A bar that records no trade: zero volume and a single flat price.

    Alpaca emits these on days a feed saw nothing. They are not prices, and
    kept in a series they read as a real close that then reverses, which is
    volatility that never happened.
    """
    return (not v) and o == h == l == c


def fetch_alpaca(symbol: str, start: str, end: str, feed: str | None = None) -> list[tuple[str, float]]:
    """Daily bars from Alpaca. Free tier covers 7+ years of history.

    Placeholder bars are dropped here, at the source, so nothing downstream has
    to know they exist.
    """
    feed = feed or ALPACA_FEED
    if feed == "sip":
        end = _sip_end(end)
    creds = alpaca_credentials()
    if not creds:
        raise RuntimeError(
            "No Alpaca credentials. Create a free paper account (email only — no SSN, "
            "no funding) and put the key id and secret on two lines in data/.alpaca"
        )
    key, secret = creds
    url = (f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
           f"?timeframe=1Day&start={start}&end={end}&limit=10000&adjustment=all&feed={feed}")
    out, page = [], None
    while True:
        full = url + (f"&page_token={page}" if page else "")
        data = json.loads(_get(full, headers={"APCA-API-KEY-ID": key,
                                              "APCA-API-SECRET-KEY": secret}))
        for bar in data.get("bars") or []:
            c = float(bar["c"])
            o, h, l = (float(bar.get("o", c)), float(bar.get("h", c)), float(bar.get("l", c)))
            v = float(bar.get("v", 0) or 0)
            if is_placeholder(o, h, l, c, v):
                continue
            out.append((bar["t"][:10], c, o, h, l, v))
        page = data.get("next_page_token")
        if not page:
            return out


# Alpaca's free tier answers OTC requests with "subscription does not permit
# querying OTC data" — a plan limit, not a missing capability, so this is a cost
# barrier rather than a technical one. Everything else on the free tier returns
# an empty list for these symbols rather than an error, which is why they showed
# as holdings with no price at all instead of as a failure anyone would notice.
#
# Yahoo's chart endpoint carries them, in USD, with no key and no account. Two
# things to be honest about: it is not a documented public API and Yahoo's terms
# do not permit automated collection, so this is a terms question rather than a
# technical one, and it can change or disappear without notice. It is used ONLY
# where the licensed source returns nothing, every bar it produces is tagged
# "yahoo" in the database, and switching it off is one constant below.
OTC_FALLBACK = True

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"


def fetch_yahoo(symbol: str, start: str, end: str) -> list[tuple[str, float]]:
    """Daily bars from Yahoo's chart endpoint, adjusted to match Alpaca's."""
    p1 = int(datetime.fromisoformat(start[:10]).replace(tzinfo=timezone.utc).timestamp())
    p2 = int(datetime.fromisoformat(end[:10]).replace(tzinfo=timezone.utc).timestamp()) + 86400
    url = (f"{YAHOO_CHART}{urllib.parse.quote(symbol.upper())}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit")
    # Yahoo answers a bare request with an empty body, so a browser-shaped
    # User-Agent is required to get any data at all.
    raw = _get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    data = json.loads(raw)
    chart = data.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(str(chart["error"])[:120])
    results = chart.get("result") or []
    if not results:
        return []
    res = results[0]
    stamps = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((res.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    closes = quote.get("close") or []
    opens, highs = quote.get("open") or [], quote.get("high") or []
    lows, vols = quote.get("low") or [], quote.get("volume") or []

    out = []
    for i, ts in enumerate(stamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue                       # a halted or untraded day
        # Alpaca is fetched with adjustment=all, so its close is split and
        # dividend adjusted. Matching that here matters: a split in an
        # unadjusted series looks like a 50% overnight loss, which is exactly
        # the phantom that had to be dug out of the trade records already.
        a = adj[i] if i < len(adj) and adj[i] is not None else close
        f = (a / close) if close else 1.0
        day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
        def sc(seq):
            v = seq[i] if i < len(seq) else None
            return float(v) * f if v is not None else float(a)
        out.append((day, float(a), sc(opens), sc(highs), sc(lows),
                    float(vols[i]) if i < len(vols) and vols[i] is not None else 0.0))
    return out


def fetch_csv(symbol: str) -> list[tuple[str, float]]:
    path = PRICE_CSV_DIR / f"{symbol.upper()}.csv"
    if not path.exists():
        return []
    out = []
    for row in csv.DictReader(path.open()):
        keys = {k.lower(): v for k, v in row.items()}
        d, c = keys.get("date"), keys.get("close") or keys.get("adj_close")
        if d and c:
            try:
                out.append((d[:10], float(c)))
            except ValueError:
                pass
    return out


# Intraday bars live in their OWN table. The prices table is keyed by
# (security_id, bar_date) with a DATE, so writing "2026-08-31T14:35:00" into it
# would both violate what that column means and pollute every daily series --
# load_series would start returning intraday timestamps to code that expects one
# row per day, and last_known_price would silently pick a 14:35 bar as "the
# close".
INTRADAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS intraday_bars (
    security_id INTEGER NOT NULL REFERENCES securities(id),
    timeframe   TEXT NOT NULL,          -- 5Min, 15Min, 1Hour
    ts          TEXT NOT NULL,          -- ISO 8601, UTC
    open        REAL, high REAL, low REAL, close REAL, volume REAL,
    source      TEXT NOT NULL,
    PRIMARY KEY (security_id, timeframe, ts)
);
"""

# What the UI may ask for, mapped to Alpaca's own vocabulary. A closed set
# because it goes into a URL, and because an arbitrary timeframe would let the
# cache fill with one-off series nothing ever reads again.
INTRADAY_TIMEFRAMES = {"5m": "5Min", "15m": "15Min", "1h": "1Hour"}


def ensure_intraday_schema(conn) -> None:
    conn.executescript(INTRADAY_SCHEMA)


def fetch_intraday(symbol: str, timeframe: str, start: str, end: str) -> list[tuple]:
    """Intraday bars from Alpaca's IEX feed.

    IEX is the free feed and covers one exchange rather than the consolidated
    tape, so on thinly traded names — KRKNF and SIVEF here — a bar can be
    missing or wider than the consolidated print. The prices are real; they are
    not the whole market. That is a fair trade for a personal tool and a bad one
    to forget about.
    """
    tf = INTRADAY_TIMEFRAMES.get(timeframe)
    if not tf:
        raise ValueError(f"unsupported intraday timeframe {timeframe!r}")
    creds = alpaca_credentials()
    if not creds:
        raise RuntimeError("No Alpaca credentials; see data/.alpaca")
    key, secret = creds
    url = (f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
           f"?timeframe={tf}&start={start}&end={end}&limit=10000&adjustment=all&feed=iex")
    out, page = [], None
    while True:
        full = url + (f"&page_token={page}" if page else "")
        data = json.loads(_get(full, headers={"APCA-API-KEY-ID": key,
                                              "APCA-API-SECRET-KEY": secret}))
        for bar in data.get("bars") or []:
            out.append((bar["t"], float(bar.get("o", bar["c"])), float(bar.get("h", bar["c"])),
                        float(bar.get("l", bar["c"])), float(bar["c"]),
                        float(bar.get("v", 0) or 0)))
        page = data.get("next_page_token")
        if not page:
            return out


def store_intraday(conn, symbol: str, timeframe: str, bars, source: str = "alpaca") -> int:
    """Cache intraday bars. The most recent one is REPLACED, not ignored.

    A daily bar is immutable once the day is over, which is why store() can
    insert-or-ignore. The bar covering the current five minutes is not: it is
    re-fetched while it is still forming and its close moves. Ignoring the
    conflict would freeze the newest candle at whatever it read the first time
    the chart was opened, which is exactly the number a live view exists to show.
    """
    ensure_intraday_schema(conn)
    sec_id = get_or_create_security(conn, symbol)
    n = 0
    for ts, o, h, l, c, v in bars:
        cur = conn.execute(
            """INSERT INTO intraday_bars
                 (security_id, timeframe, ts, open, high, low, close, volume, source)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(security_id, timeframe, ts) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume""",
            (sec_id, timeframe, ts, o, h, l, c, v, source))
        n += cur.rowcount
    conn.commit()
    return n


def load_intraday(conn, symbol: str, timeframe: str, since: str | None = None) -> list[dict]:
    """Cached intraday bars, oldest first."""
    ensure_intraday_schema(conn)
    sec = conn.execute("SELECT id FROM securities WHERE symbol = ?",
                       ((symbol or "").upper(),)).fetchone()
    if not sec:
        return []
    rows = conn.execute(
        """SELECT ts, open, high, low, close, volume FROM intraday_bars
            WHERE security_id = ? AND timeframe = ? AND (? IS NULL OR ts >= ?)
         ORDER BY ts""", (sec["id"], timeframe, since, since)).fetchall()
    return [{"time": r["ts"], "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"], "volume": r["volume"]} for r in rows]


def _weekday(iso: str) -> bool:
    try:
        y, m, d = (int(x) for x in str(iso)[:10].split("-"))
        return date(y, m, d).weekday() < 5
    except (TypeError, ValueError):
        return True


def _plausible_low(o, l, close):
    """A bar's low that sits below a fifth of both its open and its close is a
    bad print, not a trade anyone could have made: SPY's consolidated bar for
    2026-02-02 came from Alpaca with low 68.64 against an open of 685.90 and a
    close of 691.70 (Yahoo: 685.78), and that one wick squashed a year of SPY
    into the top tenth of the chart. A real crash moves the close too, so the
    test cannot fire on one. The wick is clipped to the lower of open and close
    — the least the bar is known to have traded at — rather than dropped, so
    the bar still exists and the day's range is not invented."""
    if l is None or o is None or close is None:
        return l
    floor = min(o, close)
    if floor > 0 and l < 0.2 * floor:
        return floor
    return l


def store(conn, symbol: str, bars, source: str) -> int:
    """Cache bars. A finished bar is immutable — fetched once, kept forever.

    The NEWEST bar in a batch is the exception and is replaced. A daily bar
    fetched during the session is the session so far, not the close, and
    insert-or-ignore froze whatever it read first: a chart opened at ten in the
    morning kept that morning's print as "the close" for good, and the nightly
    refresh — which fetches with a few days of overlap precisely to pick up the
    finished bar — was ignored on exactly the row it existed to correct. Every
    earlier bar in the batch is complete and is still never overwritten.

    Accepts either (date, close) or (date, close, open, high, low, volume);
    FRED serves index levels with no intraday detail, Alpaca serves full bars.
    """
    sec_id = get_or_create_security(conn, symbol)
    invalidate_series_cache(conn, symbol)
    # Exchanges do not trade on Saturday or Sunday, but a money-market fund's
    # feed prints its $1.00 on them (FDRXX did), and one such bar pushed the
    # whole book's "last session" onto a Saturday. Crypto trades every day and
    # keeps its weekend bars.
    bars = [b for b in bars if symbol.upper().endswith("-USD") or _weekday(b[0])]
    newest = max((b[0] for b in bars), default=None)
    n = 0
    for bar in bars:
        d, close = bar[0], bar[1]
        o, h, l, v = (bar[2], bar[3], bar[4], bar[5]) if len(bar) >= 6 else (None, None, None, None)
        l = _plausible_low(o, l, close)
        if d == newest:
            cur = conn.execute(
                """INSERT INTO prices
                     (security_id, bar_date, open, high, low, close, adj_close, volume, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(security_id, bar_date) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, adj_close=excluded.adj_close,
                     volume=excluded.volume, source=excluded.source""",
                (sec_id, d, o, h, l, close, close, v, source))
        else:
            cur = conn.execute(
                """INSERT OR IGNORE INTO prices
                     (security_id, bar_date, open, high, low, close, adj_close, volume, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sec_id, d, o, h, l, close, close, v, source))
        n += cur.rowcount
    # Commit here rather than leaving it to callers. A bar is immutable, so
    # persisting one is always safe and never needs rolling back — and without
    # this the cache silently evaporates on process exit while still reading
    # back correctly in-process, so a fetch looks cached and is re-downloaded
    # on every run.
    conn.commit()
    return n


def adjustment_factor(conn, symbol: str, on_date: str,
                      observed_price: float) -> float:
    """How far a recorded fill price sits from the adjusted bar of the same day.

    Bars are fetched with adjustment=all, so a split restates all of a symbol's
    history downward while the price you actually paid stays what you paid. On
    BKNG, fills between $4,448 and $5,380 sit against bars ranging $162 to $230
    — a 20-for-1 split — and NFLX shows the same at 10-for-1. Comparing the two
    without reconciling them makes a winning trade look 96% underwater.

    The factor is derived from the data rather than from a split table, so it
    needs no second source and handles any ratio. A factor near 1 means no
    adjustment happened and the price is returned untouched.
    """
    if not observed_price:
        return 1.0
    series = load_series(conn, symbol)
    if not series:
        return 1.0
    from . import performance
    point = performance.last_known_point(series, on_date, sorted_dates(conn, symbol))
    if not point or not point[0]:
        return 1.0
    factor = observed_price / point[0]
    # Only treat it as a corporate adjustment when it is far from 1 — a fill
    # anywhere inside the day's range is normal and must not be "corrected".
    return factor if (factor > 1.5 or factor < 0.667) else 1.0


def ratio_bars(numerator: list[dict], denominator: list[dict]) -> list[dict]:
    """Candles for one series divided by another, on their common sessions.

    The extremes are the ratio's OWN extremes, not a field-by-field division.
    Dividing high by high is wrong and visibly so: the ratio is at its highest
    when the numerator is high and the denominator LOW, so high/high understates
    the top and low/low overstates the bottom. On real CPER/GLD data that
    inverted 1002 of 1449 candles — high below low — which the candle renderer
    happily drew and which pushed Williams %R computed on the result to +34 and
    -131 on an axis that only runs 0 to -100.

    Taking high = num.high / den.low and low = num.low / den.high gives the true
    envelope, and guarantees low <= open, close <= high for any positive inputs.
    """
    den = {b["time"]: b for b in denominator}
    out = []
    for a in numerator:
        b = den.get(a["time"])
        if not b or not b.get("close") or not b.get("open") or not b.get("high") or not b.get("low"):
            continue
        out.append({"time": a["time"], "open": a["open"] / b["open"],
                    "high": a["high"] / b["low"], "low": a["low"] / b["high"],
                    "close": a["close"] / b["close"], "volume": 0})
    return out


def last_bar_date(conn) -> str | None:
    """The newest bar date in the whole cache, in milliseconds not hundreds.

    `SELECT MAX(bar_date) FROM prices` reads as an index lookup and is not
    one: the primary key is (security_id, bar_date), so a MAX over the second
    column walks all 2.8 million entries — 175 ms, and five endpoints did it
    on every request. Asking each security for its own newest bar is a seek
    per security along the same index, 6 ms for three thousand of them, and
    returns exactly the same date. None on an empty cache.
    """
    try:
        return conn.execute(
            """SELECT MAX((SELECT MAX(bar_date) FROM prices p WHERE p.security_id = s.id))
                 FROM securities s""").fetchone()[0]
    except sqlite3.OperationalError:
        # A database without the securities table (a bare fixture): the scan.
        return conn.execute("SELECT MAX(bar_date) FROM prices").fetchone()[0]


def last_sessions(conn, before: str, n: int = 2, symbol: str = "SPY") -> list[str]:
    """The `n` most recent trading days on or before `before`, newest first.

    Read off one liquid symbol's own bars, which is a seek on the primary
    key. Reading DISTINCT bar_date across the whole table was a full scan
    through two temporary b-trees — a second per request. Falls back to the
    scan when that symbol has too little history, which is only the case on
    a ledger nothing has been priced into yet.
    """
    sec = conn.execute("SELECT id FROM securities WHERE symbol = ?", (symbol,)).fetchone()
    rows = [] if not sec else [r[0] for r in conn.execute(
        """SELECT bar_date FROM prices WHERE security_id = ? AND source LIKE 'alpaca%'
             AND bar_date <= ? ORDER BY bar_date DESC LIMIT ?""", (sec["id"], before, n))]
    if len(rows) < n:
        rows = [r[0] for r in conn.execute(
            """SELECT DISTINCT bar_date FROM prices WHERE source LIKE 'alpaca%'
                 AND bar_date <= ? ORDER BY bar_date DESC LIMIT ?""", (before, n))]
    return rows


def load_bars(conn, symbol: str, start: str, end: str, last: int | None = None) -> list[dict]:
    """OHLCV bars for charting. Falls back to close-only where that is all we have.

    `last` keeps only the newest that many bars of the range, read off the
    primary key from the end so the rest is never fetched. A reading that is
    only ever taken at the last bar — the watchlist's RSI and 50/200-day
    averages, 202 names per request — does not need eight years loaded and
    walked to produce it.
    """
    sec = conn.execute("SELECT id FROM securities WHERE symbol = ?",
                       ((symbol or "").upper(),)).fetchone()
    if not sec:
        return []
    if last:
        rows = conn.execute(
            """SELECT bar_date, open, high, low, close, volume FROM prices
                WHERE security_id = ? AND bar_date BETWEEN ? AND ?
                ORDER BY bar_date DESC LIMIT ?""", (sec["id"], start, end, last)).fetchall()
        rows.reverse()
    else:
        rows = conn.execute(
            """SELECT bar_date, open, high, low, close, volume FROM prices
                WHERE security_id = ? AND bar_date BETWEEN ? AND ? ORDER BY bar_date""",
            (sec["id"], start, end))
    out = []
    for r in rows:
        c = r["close"]
        out.append({"time": r["bar_date"],
                    "open": r["open"] if r["open"] is not None else c,
                    "high": r["high"] if r["high"] is not None else c,
                    "low": r["low"] if r["low"] is not None else c,
                    "close": c, "volume": r["volume"] or 0})
    return out


# A price bar is immutable, so a loaded series is safe to keep for the life of
# the process. Without this, valuing a portfolio at 173 break dates reloaded the
# same 87 series 2,919 times — 97% redundant, and 77% of total runtime.
# Keyed by the identity of the connection, not by symbol alone: an earlier
# version cached on symbol only, so two different databases sharing a ticker
# handed each other the wrong prices — which showed up immediately as a failing
# test against an in-memory fixture. Only the most recent connection's entries
# are kept, which suits one-connection-at-a-time use and cannot grow unbounded.
# The cache lives ON THE CONNECTION, not in a module global.
#
# Two previous keys both failed. id(conn) is recycled by CPython the moment a
# connection is freed, so a new connection to a different database inherited the
# old one's rows. Replacing it with (path, PRAGMA data_version) fixed that for a
# long-lived connection but not for this server, which opens a fresh connection
# per request — data_version is a per-connection counter that a new connection
# always reports at baseline, so a write from update.sh stayed invisible anyway.
# And the in-memory fallback still keyed on id(conn), reintroducing the original
# bug on exactly the test-fixture path.
#
# Hanging the dict off the connection makes all of that structurally impossible:
# a per-request connection starts empty (correct, never stale), a long-lived one
# caches for its own lifetime, and two connections cannot share anything. It
# also removes two PRAGMAs from the hot path.
_CACHE_ATTR = "_investment_app_series_cache"


def _cache_for(conn) -> dict:
    cache = getattr(conn, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        try:
            setattr(conn, _CACHE_ATTR, cache)
        except AttributeError:
            # A raw sqlite3.Connection rather than ledger.LedgerConnection. Do
            # not pretend to cache — returning a throwaway dict here is what
            # made every lookup a fresh query.
            return {}
    return cache


def invalidate_series_cache(conn=None, symbol: str | None = None) -> None:
    """Drop cached series for one connection. Called whenever new bars are stored."""
    if conn is None:
        return
    cache = _cache_for(conn)
    if symbol is None:
        cache.clear()
    else:
        cache.pop(symbol.upper(), None)
        cache.pop(f"\x00dates\x00{symbol.upper()}", None)


def load_series(conn, symbol: str) -> dict[str, float]:
    # Callers already pass tickers upper-cased; skip the copy on the hot path
    # (this runs once per symbol per break date when valuing a portfolio).
    sym = symbol if (symbol and symbol.isupper()) else (symbol or "").upper()
    cache = _cache_for(conn)
    cached = cache.get(sym)
    if cached is not None:
        return cached
    sec = conn.execute("SELECT id FROM securities WHERE symbol = ?", (sym,)).fetchone()
    series = {} if not sec else {r["bar_date"]: r["close"] for r in conn.execute(
        "SELECT bar_date, close FROM prices WHERE security_id = ? ORDER BY bar_date", (sec["id"],))}
    cache[sym] = series
    return series


def load_closes_since(conn, symbol: str, since: str) -> tuple[dict[str, float], list[str]]:
    """(series, sorted dates) from the last bar on or before `since` onward.

    For a reading that needs prices at a handful of recent dates — grading a
    call made last month at its 5, 10 and 21-day marks — the full eight-year
    series is 2,000 rows loaded to read five. Starting at the last bar before
    the first date needed keeps last_known_price exact for every later date
    and loads a few dozen rows instead. Not cached on the connection: the
    window is the caller's, and load_series keeps the whole-series cache.
    """
    sym = (symbol or "").upper()
    sec = conn.execute("SELECT id FROM securities WHERE symbol = ?", (sym,)).fetchone()
    if not sec:
        return {}, []
    floor = conn.execute(
        "SELECT MAX(bar_date) FROM prices WHERE security_id = ? AND bar_date <= ?",
        (sec["id"], since)).fetchone()[0] or since
    rows = conn.execute(
        "SELECT bar_date, close FROM prices WHERE security_id = ? AND bar_date >= ? ORDER BY bar_date",
        (sec["id"], floor)).fetchall()
    series = {r[0]: r[1] for r in rows}
    return series, [r[0] for r in rows]


def sorted_dates(conn, symbol: str) -> list[str]:
    """Sorted bar dates for a symbol, cached alongside the series."""
    key = f"\x00dates\x00{(symbol or '').upper()}"
    cache = _cache_for(conn)
    cached = cache.get(key)
    if cached is None:
        cached = sorted(load_series(conn, symbol))
        cache[key] = cached
    return cached


def sync_benchmark(conn, name: str) -> dict:
    """Fetch and cache a benchmark. Returns what happened, including its caveat."""
    resolved = resolve_benchmark(name)
    if not resolved:
        return {"name": name, "ok": False,
                "error": f"Unknown benchmark. Known: {', '.join(sorted(set(FRED_BENCHMARKS)))}"}
    series, label, caveat = resolved
    try:
        bars = fetch_fred(series)
    except (urllib.error.URLError, OSError) as exc:
        return {"name": name, "ok": False, "error": f"FRED fetch failed: {exc}"}
    added = store(conn, series, bars, "fred")
    return {"name": name, "ok": True, "symbol": series, "label": label,
            "caveat": caveat, "bars": len(bars), "added": added,
            "first": bars[0][0] if bars else None, "last": bars[-1][0] if bars else None}


def sync_watchlist(conn, start: str, end: str) -> dict:
    """Refresh the watchlist too, which nothing was doing.

    `sync_holdings` covers what the ledger has TRADED, which is the right set
    for valuing a portfolio and the wrong one for scoring ideas: 108 watchlist
    names were sitting up to five days behind while the Outlook tab scored all
    of them and said nothing about it. A name you are deciding whether to buy
    needs current data at least as much as one you already own.
    """
    from . import watchlist as _wl
    _wl.ensure_schema(conn)
    syms = [r["symbol"] for r in
            conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]
    # And every chart_proxy TARGET. A proxy is what actually gets scored — a
    # holding reading from SIVE.ST is analysed entirely off that series — so
    # leaving it out would keep the thing being measured stale while the symbol
    # it stands in for looked fresh.
    for target in (config.load().get("chart_proxy") or {}).values():
        if target and target not in syms:
            syms.append(target)
    done, failed = [], []
    for sym in syms:
        try:
            r = ensure_symbol(conn, sym, start, end, as_equity=True)
            (done if r.get("ok") else failed).append(sym)
        except Exception:                                    # noqa: BLE001
            failed.append(sym)
    conn.commit()
    return {"priced": done, "failed": failed, "symbols": len(syms)}


def sync_holdings(conn, start: str, end: str) -> dict:
    """Fetch and cache daily bars for every security the ledger has traded.

    Full history is needed, not just current holdings: time-weighted return
    values the portfolio at every past cash-flow date, which means pricing
    positions that have since been closed.
    """
    symbols = [r["symbol"] for r in conn.execute(
        """SELECT DISTINCT s.symbol FROM securities s
             JOIN transactions t ON t.security_id = s.id
            ORDER BY s.symbol""")]
    done, skipped, failed = {}, [], {}
    for sym in symbols:
        # PLAN: rows are the 401(k)'s own funds, valued at contributions; they
        # have no ticker and the space in the name made Alpaca raise
        # InvalidURL for all six of them every single night.
        if (is_money_market(sym) or sym.startswith(("CUSIP:", "PLAN:"))
                or sym in FRED_BENCHMARKS):
            skipped.append(sym)
            continue
        source, err = ALPACA_SOURCE[ALPACA_FEED], None
        try:
            bars = fetch_alpaca(sym, start, end)
        except Exception as exc:                      # noqa: BLE001 - report, don't abort
            bars, err = [], f"{type(exc).__name__}: {str(exc)[:60]}"
        # The same OTC fallback ensure_symbol has. Without it the nightly
        # refresh — this path — never asked Yahoo, so SIVEF and KRKNF were
        # only ever refreshed by somebody opening their chart, and the
        # holdings table valued them days behind the OTC print.
        if not bars and OTC_FALLBACK:
            try:
                bars = fetch_yahoo(sym, start, end)
                if bars:
                    source = "yahoo"
            except Exception as exc:                  # noqa: BLE001
                err = err or f"{type(exc).__name__}: {str(exc)[:60]}"
        # Logged like any other fetch. This is the explicit refresh path and it
        # goes straight to the provider by design, but not recording it would
        # leave every symbol looking unchecked, so the next page load would
        # quietly fetch them all over again.
        record_fetch(conn, sym, "ok" if bars else (err or "empty"), since=start)
        if not bars:
            failed[sym] = err or "no bars returned"
            continue
        store(conn, sym, bars, source)
        done[sym] = len(bars)
    return {"priced": done, "skipped": skipped, "failed": failed}


FETCH_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_fetches (
    symbol       TEXT PRIMARY KEY,
    attempted_at TEXT NOT NULL,
    outcome      TEXT,
    -- The earliest start date ever requested for this symbol. Freshness alone
    -- is not enough to skip a fetch: the backtest asks from 2015 while the
    -- chart asks from 2018, and a symbol checked ten minutes ago for the chart
    -- still has nothing before 2018 to give the backtest. Recording what was
    -- ASKED FOR rather than what came back is what makes this answerable for a
    -- young ticker, which will never hold bars as old as the request.
    earliest     TEXT
);
"""

# How long a symbol counts as recently checked.
#
# The previous test was "do we hold a bar dated on or after `end`", and callers
# pass an `end` that is today or later — sectors.rotation passes 2030-01-01. A
# daily bar for today does not exist until the session closes, and never exists
# for a Saturday, so that condition was either rarely or never true and the
# fetch ran again on every single request: thirteen symbols, eight years of bars
# each, four seconds, every time the diagnose tab was opened.
#
# Six hours is chosen against the data, not the clock: these are end-of-day
# bars, they change once a day after the close, and this project is explicitly
# a swing-trading tool where delayed data is acceptable. Anything that needs
# bars fresher than the last close is asking the wrong cache.
FRESH_SECONDS = 6 * 3600
RETRY_SECONDS = 20 * 60     # how long a failed or empty fetch holds off the next try


def _ensure_fetch_log(conn) -> None:
    conn.executescript(FETCH_LOG_SCHEMA)
    # Added after the table shipped, so databases in the wild have it without it.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(price_fetches)")}
    if "earliest" not in cols:
        conn.execute("ALTER TABLE price_fetches ADD COLUMN earliest TEXT")


def checked_recently(conn, symbol: str, within: int = FRESH_SECONDS,
                     since: str | None = None) -> bool:
    """Have we already asked the provider about this symbol, lately and this far back?

    Failures count. A delisted or unsupported ticker returns nothing however
    often it is asked, and retrying it on every request is how one bad symbol in
    a watchlist adds a network round trip to every page load.

    `since` is the start date the caller needs. A symbol checked minutes ago for
    a chart starting in 2018 is not covered for a backtest starting in 2015, and
    answering yes there would silently hand the backtest a shorter history than
    it asked for.
    """
    _ensure_fetch_log(conn)
    row = conn.execute(
        "SELECT attempted_at, earliest, outcome FROM price_fetches WHERE symbol = ?",
        ((symbol or "").strip().upper(),)).fetchone()
    if not row or not row[0]:
        return False
    if since:
        earliest = row[1]
        if not earliest or since[:10] < earliest:
            return False
    try:
        when = datetime.fromisoformat(row[0])
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    # A failed or empty answer counts for much less time than a good one. On
    # 2026-09-03 Yahoo answered one nightly request for SIVEF with an empty
    # body, and the "empty" outcome then blocked every retry for the rest of
    # the evening, so the OTC name sat four sessions behind the market.
    if (row[2] or "ok") != "ok":
        within = min(within, RETRY_SECONDS)
    return (datetime.now(timezone.utc) - when).total_seconds() < within


def record_fetch(conn, symbol: str, outcome: str, since: str | None = None) -> None:
    _ensure_fetch_log(conn)
    conn.execute(
        """INSERT INTO price_fetches (symbol, attempted_at, outcome, earliest)
           VALUES (?,?,?,?)
           ON CONFLICT(symbol) DO UPDATE SET
               attempted_at = excluded.attempted_at,
               outcome = excluded.outcome,
               -- Keep the furthest back we have ever asked, so widening the
               -- window is remembered and narrowing it does not undo that.
               earliest = MIN(COALESCE(price_fetches.earliest, excluded.earliest),
                              COALESCE(excluded.earliest, price_fetches.earliest))""",
        ((symbol or "").strip().upper(),
         datetime.now(timezone.utc).isoformat(timespec="seconds"), outcome,
         since[:10] if since else None))
    conn.commit()


def analysis_bars(conn, symbol: str, start: str, end: str) -> tuple[list[dict], dict | None]:
    """Bars to read the chart from, which are not always the bars you hold.

    A foreign company's US OTC line and its home listing are the same business
    and a completely different chart. SIVEF prints about a million shares a day
    against 8.5 million on Stockholm, gaps constantly, and its last bar can be
    days stale — structure read off it is structure of the OTC quote, not of the
    company. `chart_proxy` in config.json maps the ticker you hold to the
    listing worth reading: {"SIVEF": "SIVE.ST"}.

    The proxy's bars are RESCALED into the held symbol's own currency before
    anything reads them. Sivers trades near 24.62 SEK and 2.50 USD, so support
    quoted off Stockholm would come out around 22.50 — a number that means
    nothing against a position priced in dollars, and one somebody could act on.
    Scaling is linear, so every scale-invariant reading (RSI, pivot sequence,
    where price sits in its range, the shape of a trendline) is untouched, and
    every level lands in the currency of the position it is about.

    The factor is today's ratio between the two listings, so historical levels
    are expressed at today's exchange rate rather than the rate on the day. That
    is an approximation, and it is named in the returned note rather than left
    for somebody to discover.
    """
    own = load_bars(conn, symbol, start, end)
    target = (config.load().get("chart_proxy") or {}).get((symbol or "").upper())
    if not target:
        return own, None
    proxy = load_bars(conn, target, start, end)
    if not proxy or not own:
        return own, None
    # The ratio must come from a date BOTH listings traded. Taking the last
    # close of each compared SIVEF's stale 2026-08-27 print against Stockholm's
    # 2026-09-01 one and folded four days of the stock's own movement into what
    # is supposed to be a currency conversion — and the staler the OTC line, the
    # worse the error, which is exactly when a proxy is most wanted.
    by_date = {b["time"]: b["close"] for b in proxy}
    shared = [(b["time"], b["close"], by_date[b["time"]])
              for b in own if b["time"] in by_date and by_date[b["time"]]]
    if not shared:
        return own, None
    on, own_px, proxy_px = shared[-1]
    factor = own_px / proxy_px
    if factor <= 0:
        return own, None
    scaled = [{"time": b["time"],
               "open": b["open"] * factor, "high": b["high"] * factor,
               "low": b["low"] * factor, "close": b["close"] * factor,
               "volume": b["volume"]} for b in proxy]
    return scaled, {
        "symbol": target, "factor": round(factor, 6), "ratio_date": on,
        "own_bars": len(own), "proxy_bars": len(scaled),
        "note": (f"Read from {target}, the primary listing — {len(scaled)} bars "
                 f"against {len(own)} on {symbol.upper()}. Prices are rescaled "
                 f"by {factor:.4f}, the ratio between the two listings on "
                 f"{on}, the most recent day both traded. Every level is "
                 f"therefore in {symbol.upper()}'s own currency and comparable "
                 f"to what you paid. Historical levels use that one rate, not "
                 f"the rate on the day."),
    }


def ensure_symbol(conn, symbol: str, start: str, end: str, as_equity: bool = False) -> dict:
    """Fetch and cache a symbol we do not already hold.

    Without this only holdings could be charted, which makes the whole app
    inward-looking — sector ETFs, indices and anything on a watchlist are
    exactly the things worth analysing before buying.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "no symbol"}
    # Several tickers double as benchmark aliases: "SPY" means the S&P index
    # when overlaying a portfolio, and the actual ETF when it is one series
    # among many being compared. Callers that need the tradeable instrument say
    # so, rather than silently getting an index with no volume and no OHLC.
    if resolve_benchmark(sym) and not as_equity:
        r = sync_benchmark(conn, sym)
        return {"ok": r["ok"], "cached": r.get("bars", 0), "source": "fred",
                "symbol": r.get("symbol", sym)}

    have = load_series(conn, sym)
    newest = max(have) if have else None
    if have and newest >= end[:10]:
        return {"ok": True, "cached": len(have), "source": "cache", "symbol": sym}
    # We hold bars and asked the provider recently: nothing has closed since.
    if have and checked_recently(conn, sym, since=start):
        return {"ok": True, "cached": len(have), "source": "cache", "symbol": sym}
    if not alpaca_credentials():
        return {"ok": bool(have), "cached": len(have), "source": "cache",
                "error": None if have else "no Alpaca credentials and nothing cached"}
    # Ask only for what is missing. Re-requesting eight years to learn about one
    # new day is most of the cost of a refresh. A few days of overlap is free —
    # bars are inserted with OR IGNORE — and covers a bar corrected after the
    # close, plus any weekend or holiday sitting between the two dates.
    fetch_from = start
    covered = checked_recently(conn, sym, within=10 ** 9, since=start)
    if newest and covered:
        try:
            fetch_from = max(start, (date.fromisoformat(newest) - timedelta(days=5)).isoformat())
        except ValueError:
            fetch_from = start
    source, err = ALPACA_SOURCE[ALPACA_FEED], None
    try:
        bars = fetch_alpaca(sym, fetch_from, end)
    except Exception as exc:                        # noqa: BLE001
        bars, err = [], f"{type(exc).__name__}: {str(exc)[:80]}"

    # The licensed source came back with nothing. For an OTC symbol that is not
    # an error and never will be — the free tier refuses OTC outright — so the
    # position sat in the holdings table with no price at all rather than
    # anything anyone would notice as a failure.
    if not bars and OTC_FALLBACK:
        try:
            bars = fetch_yahoo(sym, fetch_from, end)
            if bars:
                source = "yahoo"
        except Exception as exc:                    # noqa: BLE001
            err = err or f"{type(exc).__name__}: {str(exc)[:80]}"

    record_fetch(conn, sym, "ok" if bars else (err or "empty"), since=start)
    if not bars:
        return {"ok": bool(have), "cached": len(have),
                "error": err or f"no bars returned for {sym}"}
    added = store(conn, sym, bars, source)
    return {"ok": True, "cached": len(bars), "added": added, "source": source,
            "symbol": sym}


# ------------------------------------------------------------------ refeed ----

def refeed(conn, symbols: list[str] | None = None, start: str = "2015-01-01",
           log=None) -> dict:
    """Rebuild the daily cache for every symbol still carrying IEX bars.

    One symbol at a time, and the old rows are deleted only AFTER the SIP fetch
    has returned bars, so a symbol the consolidated feed does not serve — the
    OTC names — keeps whatever it had. Each symbol is committed on its own, so
    an interruption leaves a cache that is a mixture of feeds rather than a
    hole, and running again picks up where it stopped: a symbol whose rows are
    already tagged "alpaca-sip" is not in the list.

    Returns, per symbol, how many rows were replaced and how many of those were
    placeholder bars, because that count is the size of the defect the switch
    is correcting and belongs in the record of the run.
    """
    import time
    say = log or (lambda *a: None)
    old_tag = ALPACA_SOURCE["iex"]
    if symbols is None:
        symbols = [r["symbol"] for r in conn.execute(
            """SELECT DISTINCT s.symbol FROM prices p JOIN securities s ON s.id = p.security_id
                WHERE p.source = ? ORDER BY s.symbol""", (old_tag,))]
    today = date.today().isoformat()
    done, untouched, failed = {}, [], {}
    for sym in symbols:
        sec = conn.execute("SELECT id FROM securities WHERE symbol = ?", (sym,)).fetchone()
        if not sec:
            continue
        row = conn.execute(
            """SELECT COUNT(*) n, MIN(bar_date) first,
                      SUM(CASE WHEN (volume IS NULL OR volume = 0)
                                AND open = close AND high = low THEN 1 ELSE 0 END) flat
                 FROM prices WHERE security_id = ? AND source = ?""", (sec["id"], old_tag)).fetchone()
        fetch_from = min(start, row["first"] or start)
        bars, err = [], None
        for attempt in range(3):
            try:
                bars = fetch_alpaca(sym, fetch_from, today, feed="sip")
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    time.sleep(20)            # the free plan's per-minute limit
                    continue
                err = f"HTTP {exc.code}"
                break
            except Exception as exc:                        # noqa: BLE001
                err = f"{type(exc).__name__}: {str(exc)[:80]}"
                break
        if err:
            failed[sym] = err
            say(f"  {sym:<8} FAILED {err}")
            continue
        if not bars:
            untouched.append(sym)
            say(f"  {sym:<8} not served by SIP; {row['n']} IEX bars kept")
            continue
        conn.execute("DELETE FROM prices WHERE security_id = ? AND source = ?",
                     (sec["id"], old_tag))
        store(conn, sym, bars, ALPACA_SOURCE["sip"])
        record_fetch(conn, sym, "ok", since=fetch_from)
        conn.commit()
        done[sym] = {"old": row["n"], "placeholders": row["flat"] or 0, "new": len(bars)}
        say(f"  {sym:<8} {row['n']:>5} IEX bars ({row['flat'] or 0} placeholders) -> {len(bars):>5} SIP bars")
    return {"refed": done, "untouched": untouched, "failed": failed}
