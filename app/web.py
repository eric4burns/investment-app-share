"""Local web dashboard.

    python3 -m app.web            then open http://localhost:8737

Stdlib only, no framework, no build step. Binds to 127.0.0.1 unless INVESTMENT_APP_HOST says otherwise so that once
Tailscale is installed this same server is reachable from a phone or a work
laptop with no port forwarding and nothing exposed to the public internet.

Mostly read-only, but NOT entirely: /api/watchlist writes and commits, and the chart endpoint caches fetched price bars. The old claim here was simply false, and a docstring asserting a safety property the code does not have is worse than none.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
import os
import time
import threading
from datetime import date, timedelta
import urllib.parse
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .ledger import DB_PATH, bump_epoch, connect
from . import config, ladder
from .importers import budget_grid, payroll_pdf
from . import (amazon, analysis, authors, backtest, budget, cash, diagnose, drawings, exits, frameworks, holdings, mailtrades, washsales,
               indicators, intermarket, methods, performance, prices, risk, sectors,
               networth, reconcile, recurring, setups, structure, taxes, theses,
               themes, trends, watchlist, journal, outlook, verdicts,
               calibration, sentiment, replay, earnings, alerts, measure, discover, books, trade_around, paper, regime)

_CFG = config.load()

# config.example.json has documented "port" and "host" since the shell was made
# shippable, and neither was ever read — the port was a module constant and the
# host came only from the environment. A setting that is documented and ignored
# is worse than one that is not offered: someone sets it, nothing happens, and
# there is nothing on screen to say why. Precedence is environment, then
# config.json, then the default, so a second instance can still be started
# without editing a file.
PORT = int(os.environ.get("INVESTMENT_APP_PORT") or _CFG.get("port") or 8737)
HERE = Path(__file__).resolve().parent

# The owner's tax profile. A wrong filing status silently distorts the standard
# deduction, every bracket threshold and the Roth phase-out band at once, and
# none of it looks like an error on screen — so the default is the real answer
# rather than the most conservative one. Both stay overridable by query string.
DEFAULT_FILING_STATUS = _CFG.get("filing_status") or "single"
DEFAULT_AGE = _CFG.get("age")

# How much intraday history to keep on screen. Seven days is enough to see the
# shape of a move without asking the feed for a month of five-minute bars every
# time a chart is opened.
INTRADAY_DAYS = 7


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def value_series(conn, txns, start: str, end: str, step_days: int = 1):
    """Portfolio value on every trading day, for the chart.

    This used to sample WEEKLY, on the stated grounds that each point re-walks
    the ledger and weekly was "plenty for a multi-year curve". Both halves were
    wrong. values_at makes one forward pass and the price series are cached per
    connection, so the whole daily curve costs about 40ms — the twenty seconds
    that justified weekly sampling only appears when the cache is bypassed by
    handing it a raw sqlite3.Connection instead of a LedgerConnection.

    And weekly did not merely lose detail, it lost the truth: the portfolio
    peaked at $629,597.62 on 2026-06-02, a Tuesday. The weekly grid sampled the
    29th of May and the 5th of June, by which point it had fallen to $512k, so
    the chart's highest point read $590,569 — understating the peak by $39,000
    and disagreeing with the broker's own screen.

    WEEKENDS ARE SKIPPED. Stepping by calendar day would put Saturday and Sunday
    on the grid at Friday's price: two flat days in seven, 28% of all samples
    carrying a zero return by construction. The risk panel derives its
    annualisation from this same grid, so that would quietly deflate volatility
    and inflate every Sharpe on the page. Market holidays still slip through —
    about nine a year against 261 trading days — which is small enough to name
    rather than to build a holiday calendar for.
    """
    grid, cur, last = [], _d(start), _d(end)
    while cur <= last:
        if cur.weekday() < 5:
            grid.append(cur.isoformat())
        cur += timedelta(days=step_days)
    if grid and grid[-1] != end:
        grid.append(end)
    valued = performance.values_at(conn, txns, grid)
    return [{"date": d, "value": round(valued[d][0], 2)} for d in grid]


def benchmark_series(conn, txns, symbol: str, start: str, end: str, dates: list[str],
                     multi_account: bool = True):
    """The same-deposits replay, valued on the same sample dates as the portfolio.

    `multi_account` must match the scope being charted. Whether a transfer counts
    as an external deposit depends on whether both of its legs are in view, so a
    replay using the wrong flag either double-counts or ignores real money.
    """
    resolved = prices.resolve_benchmark(symbol)
    if not resolved:
        return None
    series_id, label, _caveat = resolved
    series = prices.load_series(conn, series_id)
    if not series:
        return None
    p0 = performance.last_known_price(series, start)
    if not p0:
        return None

    begin_value, _ = performance.portfolio_value(conn, txns, start)
    flows = performance.external_flows(txns, start, end, multi_account)
    units = begin_value / p0
    out, fi = [], 0
    for iso in dates:
        while fi < len(flows) and flows[fi][0] <= iso:
            px = performance.last_known_price(series, flows[fi][0])
            if px:
                units += flows[fi][1] / px
            fi += 1
        px = performance.last_known_price(series, iso)
        out.append({"date": iso, "value": round(units * px, 2) if px else None,
                    # The index's OWN return over the window. Deliberately not
                    # value/first_value: the replay's value includes the same
                    # deposits the portfolio received, so that ratio would
                    # measure the deposits, not the market. Price ratio is the
                    # index return, which is what a time-weighted portfolio
                    # return is comparable against.
                    "ret": (px / p0 - 1.0) if px else None})
    return {"symbol": symbol, "label": label, "points": out}


def last_session(conn, txns, series: list[dict], scope: str) -> dict | None:
    """The change over the last trading day, flow-adjusted.

    Measured between the two most recent TRADING days rather than the last two
    points of the curve: the curve is sampled daily including weekends, so on a
    Sunday its last two points are both Friday's close and the change would
    read as zero. A deposit that landed on the day is stripped out, since money
    arriving is not the portfolio going up.
    """
    if len(series) < 2:
        return None
    by_date = {p["date"]: p["value"] for p in series}
    # The calendar comes from the equity bars, not from the FRED index: FRED
    # publishes a day late, so its last date is yesterday while the holdings
    # are already priced for today, and the "last session" was one day stale.
    trading = prices.last_sessions(conn, series[-1]["date"], 2)
    trading = sorted(d for d in trading if d in by_date)
    if len(trading) < 2:
        trading = [p["date"] for p in series]
    prev_d, last_d = trading[-2], trading[-1]
    flows = performance.external_flows(txns, prev_d, last_d,
                                       scope in performance.MULTI_ACCOUNT_SCOPES)
    flow = sum(amt for d, amt in flows if prev_d < d <= last_d)
    change = by_date[last_d] - by_date[prev_d] - flow
    base = by_date[prev_d]
    return {"date": last_d, "prev_date": prev_d,
            "change_usd": round(change, 2),
            "change_pct": (round(change / base, 6) if base else None),
            "flow": round(flow, 2)}


def freshness(conn, latest_bar: str | None) -> dict:
    """When the prices end, and when the nightly scoring last ran.

    The two can disagree — prices refresh whenever a chart is opened, verdicts
    only when the nightly job runs — and the disagreement is the thing worth
    showing: a page dated today over verdicts from two days ago reads as
    current and is not.
    """
    scored_for = scored_at = None
    try:
        journal.ensure_schema(conn)
        row = conn.execute(
            "SELECT MAX(date) d, MAX(created_at) at FROM decisions WHERE source='app'").fetchone()
        scored_for, scored_at = row["d"], row["at"]
    except sqlite3.OperationalError:
        pass
    return {"prices_to": latest_bar, "scored_for": scored_for, "scored_at": scored_at}


def build_payload(params) -> dict:
    conn = connect()
    try:
        return _build(conn, params)
    finally:
        conn.close()          # one leaked fd and sqlite handle per request otherwise


def data_end(conn) -> str:
    """The last date there is DATA for — a price or a transaction, whichever is
    later — never just the last date something was traded.

    `_build` learned this the hard way and left a comment about it: pinning a
    window to MAX(txn_date) freezes the whole view on the last import, because
    prices arrive nightly over the network while transactions arrive only when
    an export is downloaded by hand. Five other endpoints still had the
    original bug on 2026-09-10, and the Diagnose tab was reporting a drawdown
    of −41.2% as of the user's last trade while the real figure that morning
    was −38.8%. A stale number labelled CRITICAL is worse than no number.

    Carrying holdings forward is right rather than approximate: a position's
    quantity cannot change without a transaction, so valuing last week's shares
    at today's close is what the account is actually worth.
    """
    row = conn.execute("SELECT MAX(txn_date) FROM transactions").fetchone()[0]
    bar = prices.last_bar_date(conn)
    return max([d for d in (row, bar) if d] or [date.today().isoformat()])


def _build(conn, params) -> dict:
    bounds = conn.execute("SELECT MIN(txn_date) a, MAX(txn_date) b FROM transactions").fetchone()
    # MIN/MAX over an empty table are NULL, so a ledger with nothing imported
    # yet handed None straight to strptime and the whole endpoint returned a
    # 500. That is the FIRST thing a new user sees: unzip, run, open the page,
    # before importing anything. Falling back to today gives an empty window
    # that every downstream figure handles as zero, so the dashboard renders
    # its empty state and the setup instructions stay reachable.
    today = date.today().isoformat()
    # The window ENDS at the last day there is a price for, not the last day a
    # transaction was imported. Those are different dates and the gap is normal:
    # prices arrive nightly over the network, transactions only when an export
    # is downloaded by hand. Pinning the end to MAX(txn_date) meant the whole
    # dashboard froze on the last import — the curve stopped on Friday while
    # three sessions of real price movement sat in the database unused, and the
    # portfolio total silently reported a stale figure as though it were today's.
    #
    # Carrying holdings forward is exactly right rather than an approximation:
    # a position's QUANTITY cannot change without a transaction, so valuing
    # Friday's shares at Monday's close is what the account is actually worth,
    # and it is what the broker's own screen shows.
    latest_bar = prices.last_bar_date(conn)
    newest = max([d for d in (bounds["b"], latest_bar) if d] or [today])
    start = params.get("from", [bounds["a"] or today])[0]
    end = params.get("to", [newest])[0]
    scope = params.get("scope", ["investment"])[0]
    marks = [b for b in params.get("benchmarks", ["SPY,QQQ"])[0].split(",") if b.strip()]

    summary = performance.analyse(conn, start, end, scope, marks)
    start, end = summary["start"], summary["end"]      # honour the clamp
    txns = performance.load_transactions(conn, start, end, scope)
    series = value_series(conn, txns, start, end)
    dates = [p["date"] for p in series]
    benches = [b for b in (benchmark_series(conn, txns, m, start, end, dates,
                                            scope in performance.MULTI_ACCOUNT_SCOPES)
                           for m in marks) if b]

    # A percentage on the value curve has to be TIME-WEIGHTED. Value went from
    # $7,963 to $367,988, which is +4,521% if you divide one by the other and
    # almost entirely deposits — a number that would be wrong in the most
    # flattering possible direction. period_returns is flow-adjusted, so
    # chaining it gives the growth of a dollar left alone from the start, which
    # is the thing an index return can fairly be set beside.
    rets = dict(risk.period_returns(conn, txns, dates,
                                    scope in performance.MULTI_ACCOUNT_SCOPES))
    growth = 1.0
    for point in series:
        growth *= (1.0 + rets.get(point["date"], 0.0))
        point["twr"] = round(growth - 1.0, 6)

    # What the return was worth, what the last session did, and how fresh the
    # figures are. The notes on the first review asked for all three by name:
    # a return with no dollar figure, a value with no day change, and a page
    # with no date on it were the three things the Overview was missing.
    summary["gain_usd"] = round((summary.get("end_value") or 0.0)
                                - (summary.get("begin_value") or 0.0)
                                - (summary.get("net_external_flow") or 0.0), 2)
    summary["day"] = last_session(conn, txns, series, scope)
    summary["freshness"] = freshness(conn, latest_bar)

    accounts = [dict(r) for r in conn.execute("""
        SELECT a.name, a.tax_status, a.kind, COUNT(*) txns,
               MIN(t.txn_date) first, MAX(t.txn_date) last
          FROM transactions t JOIN accounts a ON a.id = t.account_id
         GROUP BY a.id ORDER BY COUNT(*) DESC""")]

    # Per-account ending value, so the chart's total can be broken down (D12).
    per_account = []
    for row in conn.execute("SELECT id, name, tax_status, kind FROM accounts"):
        if row["kind"] not in performance.INVESTMENT_ACCOUNT_KINDS:
            continue
        at = performance.load_transactions(conn, start, end, row["name"])
        if not at:
            continue
        value, _ = performance.portfolio_value(conn, at, end)
        # Cash is shown per account because that is the only form in which it
        # can be checked: the statement gives a core balance per account, and a
        # single combined figure could be wrong in two places and still add up.
        c = cash.balances(at, end, cash.anchors(conn)).get(row["name"], {})
        per_account.append({"name": row["name"], "tax_status": row["tax_status"],
                            "value": round(value, 2),
                            "cash": c.get("balance"),
                            "cash_anchored": c.get("anchored", False),
                            "cash_impossible": c.get("impossible", False)})
    per_account.sort(key=lambda a: -a["value"])

    from datetime import date as _date, timedelta as _td
    prior = (_date.fromisoformat(end) - _td(days=7)).isoformat()
    pos = holdings.positions(conn, txns, end, prior=prior)
    att = holdings.attribution(conn, txns, start, end)
    real = holdings.realised(conn, txns, start, end)

    # Risk uses the same weekly grid as the value curve, so the underwater
    # chart lines up with the portfolio chart above it.
    # Without the scope flag every deposit into a single account counts as a
    # gain across the whole risk panel: BrokerageLink Roth reported CAGR 305.80%
    # and Sharpe 4.10 against a true 23.86% and 0.42. Same defect as the +2211%
    # Modified Dietz, one call site over.
    rk = risk.metrics(conn, txns, dates, benchmark=(marks[0] if marks else None),
                      multi_account=scope in performance.MULTI_ACCOUNT_SCOPES)

    sectors.classify(conn, [p["symbol"] for p in pos])
    conn.commit()
    exposure = sectors.exposure(conn, pos)
    theme_rows, theme_untagged = themes.exposure(conn, pos)
    conc = risk.concentration(conn, pos, dates)
    corr = risk.correlation(conn, pos, dates)
    acct_risk = risk.by_account(conn, [a["name"] for a in performance.list_accounts(conn)],
                                dates, end)

    trips = holdings.excursions(conn, holdings.position_trades(txns, end))
    stats = holdings.trade_stats(trips)

    # RonnieV's DCA tier per position. Computed here rather than only in the
    # Research tab because this is the table you would act on it from.
    for p in pos:
        tier = frameworks.dca_multiplier(conn, p["symbol"], end)
        p["dca"] = None if tier.get("insufficient") else tier

    return {"summary": summary, "series": series, "benchmarks": benches,
            "holdings": pos,
            "alerts": alerts.recent(conn, 7),
            "alert_channels": {k: bool(v) for k, v in alerts.settings().items() if k != "min_level"},
            "risk": rk, "position_moves": risk.position_moves(conn, pos, end),
            # 40ms for the whole book, so it rides along with the payload
            # rather than needing a round trip of its own.
            "exits": exits.summary(conn, pos, end),
            "concentration": conc, "correlation": corr,
            "sector_exposure": exposure,
            "theme_exposure": theme_rows, "theme_untagged": theme_untagged,
            "account_risk": acct_risk,
            # Every closed round trip, newest first. This was capped at 12 and
            # not sorted at all — the list came out in symbol order, so "recent"
            # was neither recent nor complete, and with 121 round trips whole
            # names (ETHU, ASTS) were simply absent from the Trades tab with
            # nothing indicating anything had been left out.
            "wash": washsales.report(txns, {p["symbol"]: p.get("price") for p in pos if p.get("price")}, end),
            "email_trades": mailtrades.recent(conn),
            "trades": {"stats": stats,
                       "recent": sorted(
                           (t for t in trips if not t["open"]),
                           key=lambda t: t.get("exit_date") or "", reverse=True),
                       "by_symbol": holdings.by_symbol(
                           [t for t in trips if not t["open"]])},
            "attribution": {"top": att[:8], "bottom": att[-5:][::-1]},
            "realised": real[:10],
            "holdings_total": round(sum(p["value"] or 0 for p in pos), 2),
            # The number the app exists to produce, and the one it could not
            # compute until card debt arrived: a brokerage balance rising while
            # a card balance rises faster is a portfolio going up and a net
            # worth going down.
            "networth": _networth_block(conn, start, end),
            "accounts": accounts, "per_account": per_account,
            "scopes": performance.list_accounts(conn),
            "symbols": [r["symbol"] for r in conn.execute(
                """SELECT DISTINCT s.symbol FROM securities s
                     JOIN transactions t ON t.security_id = s.id
                    WHERE s.symbol NOT LIKE 'CUSIP:%' ORDER BY s.symbol""")],
            # `last` drives the page's date picker: it sets the "to" field and
            # its max. Reporting the last TRANSACTION date here meant the
            # browser then sent to=<that date> on every request, so the server
            # clamped both charts back to it — the fix one level up was invisible
            # from the page, which still stopped on the last import.
            "bounds": {"first": bounds["a"], "last": newest}}


def _chart_plan(conn, symbol: str, asof: str) -> dict | None:
    """Sell level, buy-back and ladder rung for a held name, for the chart's
    price lines. None when the name is not held or the plan cannot be read."""
    try:
        r = trade_around.plan(conn, symbol, asof)
    except Exception:                                          # noqa: BLE001
        return None
    if not r or not r.get("quantity"):
        return None
    return {"sell_at": r.get("sell_at"), "sell_why": r.get("sell_why"), "buy_back": r.get("buy_back"),
            "buy_why": r.get("buy_why"), "next_rung": r.get("next_rung"), "ladder_stage": r.get("ladder_stage"),
            "named": (r.get("named") or [])[:5]}


def chart_payload(params) -> dict:
    """Bars for one symbol, the user's own fills, indicators, and a technical read."""
    conn = connect()
    try:
        symbol = params.get("symbol", [""])[0].upper()
        scope = params.get("scope", ["investment"])[0]
        raw_tf = (params.get("timeframe", ["D"])[0] or "D").strip()
        # Intraday timeframes are a different SOURCE, not a resampling of daily
        # bars: you cannot make a 15-minute candle out of a daily one. They are
        # matched case-sensitively against the supported set before anything
        # else decides what to load.
        intraday_tf = raw_tf.lower() if raw_tf.lower() in prices.INTRADAY_TIMEFRAMES else None
        timeframe = raw_tf.upper()[:1]
        # Pivot sensitivity is exposed because the tradeoff is real: tight finds
        # every wiggle, loose misses live structure.
        pivot_left = max(1, min(10, int(params.get("pivots", ["3"])[0] or 3)))
        pivot_right = pivot_left
        try:
            fib_back = max(10, min(2000, int(params.get("fibback", ["120"])[0] or 120)))
        except ValueError:
            fib_back = 120
        compare = params.get("compare", [""])[0].upper().strip()
        mode = params.get("mode", ["overlay"])[0]        # overlay | ratio
        bounds = conn.execute("SELECT MIN(txn_date) a, MAX(txn_date) b FROM transactions").fetchone()
        # The chart ends at the last CLOSE, not at the last time you traded.
        # Defaulting to MAX(txn_date) meant every chart stopped on the date of
        # the most recent transaction in the whole ledger — CRDO was drawn to
        # 2026-08-28 while its bars ran to 09-02, and no amount of refreshing
        # prices could move it, because the price data was never the limit.
        # The same mistake was fixed in the performance payload once already:
        # when you last bought something is not when the market last closed.
        last_bar = prices.last_bar_date(conn)
        default_end = max([x for x in (bounds["b"], last_bar) if x] or
                          [date.today().isoformat()])
        end = params.get("to", [default_end])[0]

        # A chart's history is a property of the INSTRUMENT, not of when you
        # happened to start trading. Tying the start to the first transaction
        # meant a name you bought last year showed one year of history and its
        # earlier structure — the levels that explain where it is now — simply
        # was not there. `years` is how far back to draw; "all" means everything
        # cached, and the portfolio period no longer bounds it.
        span = (params.get("years", ["all"])[0] or "all").lower()
        fetch_from = "2015-01-01"
        if span in ("all", "max"):
            start = fetch_from
        else:
            try:
                start = f"{int(end[:4]) - max(1, min(30, int(float(span)))):04d}{end[4:]}"
            except ValueError:
                start = fetch_from

        # Fetch anything not already cached, so sector ETFs and watchlist names
        # can be charted and analysed without owning them first.
        fetched = prices.ensure_symbol(conn, symbol, fetch_from, end)
        conn.commit()

        chart_proxy = None
        want_own = (params.get("own", ["0"])[0] or "0") in ("1", "true", "yes")
        if intraday_tf:
            # Refresh the recent window each time an intraday chart is opened:
            # the newest bar is still forming, so a cached copy of it is stale
            # the moment it is written.
            since = (date.fromisoformat(end[:10]) - timedelta(days=INTRADAY_DAYS)).isoformat()
            try:
                fresh = prices.fetch_intraday(symbol, intraday_tf, since, end)
                if fresh:
                    prices.store_intraday(conn, symbol, intraday_tf, fresh)
            except Exception as exc:                    # noqa: BLE001
                # A feed problem must not blank the chart: fall back to whatever
                # is cached and say so rather than showing nothing.
                intraday_error = str(exc)
            else:
                intraday_error = None
            bars = prices.load_intraday(conn, symbol, intraday_tf, since)
            daily = bars
        else:
            intraday_error = None
            # A held OTC line with a home listing named in chart_proxy is drawn
            # from that listing, rescaled into its own currency — the bars the
            # verdict, the ladder and the buy-back readings use — so the chart
            # shows the company's years, not the OTC quote's months. ?own=1
            # shows the OTC line itself.
            if want_own:
                daily, chart_proxy = prices.load_bars(conn, symbol, start, end), None
            else:
                daily, chart_proxy = prices.analysis_bars(conn, symbol, start, end)
            bars = indicators.resample(daily, timeframe)

        cmp_bars, ratio = [], []
        if compare and compare != symbol:
            prices.ensure_symbol(conn, compare, "2018-01-01", end)
            conn.commit()
            cmp_daily = prices.load_bars(conn, compare, start, end)
            cmp_bars = indicators.resample(cmp_daily, timeframe)
            if mode == "ratio" and cmp_bars:
                # A ratio chart answers "which is winning", which a pair of
                # lines on different scales cannot.
                ratio = prices.ratio_bars(bars, cmp_bars)

        chart_bars = ratio if (mode == "ratio" and ratio) else bars
        _analysis_daily = (prices.load_bars(conn, symbol, "2018-01-01", end) if want_own
                           else prices.analysis_bars(conn, symbol, "2018-01-01", end)[0])
        served_tf = intraday_tf or timeframe
        specs = [x for x in params.get("indicators", ["volume,sma:20,sma:50"])[0].split(",") if x]
        inds = indicators.compute(chart_bars, specs) if chart_bars else {}

        # Structure for the price pane and for every oscillator pane. Doing the
        # oscillators here rather than in the browser is the whole point: a
        # trendline on %R is the same computation as one on price, so it should
        # not be a second implementation living in JavaScript.
        struct = {}
        if chart_bars:
            struct["price"] = structure.detect(chart_bars, left=pivot_left,
                                               right=pivot_right,
                                               fib_lookback=fib_back)
            for spec, payload in inds.items():
                data = payload.get("data")
                if payload.get("pane") != "lower" or not isinstance(data, list) or not data:
                    continue
                struct[spec] = structure.detect(data, left=pivot_left,
                                                right=pivot_right)

        txns = performance.load_transactions(conn, start, end, scope)
        marks = []
        for t in txns:
            if t["symbol"] != symbol or not t["quantity"] or t["txn_date"] < start:
                continue
            side = ("buy" if t["kind"] in holdings.ACQUIRE
                    else "sell" if t["kind"] in holdings.DISPOSE else None)
            if not side:
                continue
            # Bars are split-adjusted; the price paid is not. BKNG's fills at
            # 4,448–5,380 sat against bars at 173–219 (20-for-1), and the dot
            # "at my fill price" was off the top of the chart.
            factor = (prices.adjustment_factor(conn, symbol, t["txn_date"][:10], t["price"])
                      if t.get("price") else 1.0) or 1.0
            marks.append({"date": t["txn_date"], "side": side,
                          "qty": abs(round(t["quantity"] * factor, 4)),
                          "price": round(t["price"] / factor, 4) if t.get("price") else None,
                          "value": round(abs(t["amount"] or 0), 2),
                          "split_adjusted": factor != 1.0})
        marks.sort(key=lambda m: m["date"])
        if intraday_tf:
            # An intraday chart holds a week; a fill from last year has no bar
            # here and used to land on the first one, at last year's price.
            first_day = chart_bars[0]["time"][:10] if chart_bars else None
            marks = [m for m in marks if first_day and m["date"][:10] >= first_day]

        # Collapse fills to one marker per bar per side; on a weekly chart that
        # also snaps daily fills onto the candle that contains them.
        bar_dates = [b["time"] for b in chart_bars]
        def bucket_for(d: str) -> str | None:
            if intraday_tf:
                # a fill carries a date, not a time: the day's first bar
                return next((bd for bd in bar_dates if bd[:10] == d[:10]), None)
            prev = None
            for bd in bar_dates:
                if bd >= d:
                    return bd
                prev = bd
            return prev
        agg: dict[tuple, dict] = {}
        for m in marks:
            bd = bucket_for(m["date"]) if (timeframe != "D" or intraday_tf) else m["date"]
            key = (bd, m["side"])
            a = agg.setdefault(key, {"date": bd, "side": m["side"], "qty": 0.0,
                                     "value": 0.0, "fills": 0})
            a["qty"] += m["qty"]; a["value"] += m["value"]; a["fills"] += 1
        daily_marks = []
        for a in agg.values():
            if not a["date"]:
                continue
            a["qty"] = round(a["qty"], 4); a["value"] = round(a["value"], 2)
            a["price"] = round(a["value"] / a["qty"], 4) if a["qty"] else None
            daily_marks.append(a)
        daily_marks.sort(key=lambda m: m["date"])

        trips = [t for t in holdings.position_trades(txns, end) if t["symbol"] == symbol]
        pos = {p["symbol"]: p for p in holdings.positions(conn, txns, end)}

        return {"symbol": symbol, "timeframe": served_tf,
                "intraday": bool(intraday_tf), "intraday_error": intraday_error,
                "structure": struct,
                # Volume by price over the structure window, drawn down the
                # right edge of the price pane the way SteveUrkeldude's IREN
                # chart shows it (research/charts-2026-09-03-x-accounts.md).
                "volume_profile": (indicators.volume_profile(chart_bars)
                                   if chart_bars and not ratio else None),
                "drawings": drawings.for_chart(conn, symbol, timeframe),
                "bars": chart_bars, "marks": daily_marks, "fills": marks,
                "proxy": chart_proxy,
                # The one sell rule with a record and the buy-back under it
                # (D78), drawn on the chart the user actually trades from.
                "plan": _chart_plan(conn, symbol, end) if not ratio else None,
                "compare": ({"symbol": compare, "bars": cmp_bars, "mode": mode}
                            if cmp_bars else None),
                "trades": trips, "indicators": inds,
                "catalogue": indicators.catalogue(),
                "setups": setups.catalogue(),
                # Analysis deliberately uses its own long window rather than the
                # report's date range: a monthly chart needs years of bars, and
                # limiting it to the selected period would report "insufficient"
                # for exactly the timeframe that matters most.
                # ...and it reads the same bars the chart above it does: the
                # home listing when one is named, so SIVEF's weekly and
                # monthly are not "only 24 bars — not enough".
                "analysis": (analysis.analyse(_analysis_daily, symbol)
                             if len(_analysis_daily) > 30 else None),
                "fetch": fetched,
                "position": pos.get(symbol)}
    finally:
        conn.close()


def watchlist_payload(params) -> dict:
    conn = connect()
    try:
        watchlist.ensure_schema(conn)
        watchlist.sync_theme_tags(conn)
        end = params.get("to", [None])[0] or data_end(conn)
        action = params.get("action", [""])[0]
        sym = params.get("symbol", [""])[0]

        if action == "add":
            # Imported names arrive already organised: a theme is just a tag,
            # so the curated theme map seeds them and the user edits from there.
            given = [t for t in params.get("tags", [""])[0].split(",") if t.strip()]
            watchlist.add(conn, sym,
                          given + themes.tags_for_import(sym),
                          note=params.get("note", [None])[0],
                          target=float(params["target"][0]) if params.get("target", [""])[0] else None,
                          stop=float(params["stop"][0]) if params.get("stop", [""])[0] else None)
            prices.ensure_symbol(conn, sym, "2018-01-01", end, as_equity=True)
            sectors.classify(conn, [sym])
        elif action == "remove":
            watchlist.remove(conn, sym)
        elif action == "tags":
            watchlist.set_tags(conn, sym, params.get("tags", [""])[0].split(","))
        elif action == "sector":
            sectors.set_sector(conn, sym, params.get("sector", ["Unknown"])[0], "set from watchlist")
        elif action == "note":
            watchlist.set_note(conn, sym, params.get("note", [None])[0],
                               float(params["target"][0]) if params.get("target", [""])[0] else None,
                               float(params["stop"][0]) if params.get("stop", [""])[0] else None)
        conn.commit()

        return {"rows": watchlist.rows(conn, end),
                "tags": watchlist.tags(conn),
                "themes": [{"key": k, "label": v["label"]} for k, v in themes.THEMES.items()],
                "sectors": sorted({v for v in sectors.SECTOR_ETFS.values()} | {"Unknown"})}
    finally:
        conn.close()


def backtest_payload(params) -> dict:
    """Run a walk-forward backtest, or just list what can be run.

    The catalogue is served on its own because it used to arrive only as a field
    on a completed run — so the method picker stayed empty for the ~30 seconds a
    cold run takes, and the tab looked broken rather than busy. The list of
    methods is static data and must never be gated behind a computation.
    """
    if (params.get("catalogue", [""])[0] or "").strip() in ("1", "true", "yes"):
        return {"catalogue": methods.catalogue()}
    conn = connect()
    try:
        key = params.get("method", ["momentum-relative-strength"])[0]
        # The last completed run for this method, so the tab is never blank.
        # Opening it used to show controls and nothing else, which read as
        # broken; a result from last week with its date on it reads as a tab.
        _ensure_backtest_runs(conn)
        if (params.get("last", [""])[0] or "").strip() in ("1", "true", "yes"):
            row = conn.execute(
                """SELECT params, result, ran_at FROM backtest_runs
                    WHERE method = ? ORDER BY ran_at DESC LIMIT 1""", (key,)).fetchone()
            if not row:
                return {"none": True, "method": key}
            out = json.loads(row["result"])
            out["ran_at"] = row["ran_at"]
            out["params"] = json.loads(row["params"])
            return out
        start = params.get("from", ["2021-01-01"])[0]
        end = params.get("to", [None])[0] or data_end(conn)
        watchlist.ensure_schema(conn)
        syms = [r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]
        try:
            run_params = {"from": start, "to": end,
                          "threshold": float(params.get("threshold", ["0.75"])[0]),
                          "positions": int(params.get("positions", ["10"])[0]),
                          "cost": int(params.get("cost", ["25"])[0])}
        except ValueError:
            # A blank or fat-fingered control is a 400-shaped answer on the
            # tab, not a 500 that reads as the server being down.
            return {"error": "threshold, positions and cost must be numbers"}
        out = backtest.with_control(
            conn, key, syms, start, end,
            threshold=run_params["threshold"],
            max_positions=run_params["positions"],
            cost_bps=run_params["cost"])
        out["catalogue"] = methods.catalogue()
        if not out.get("error") and not (out.get("live") or {}).get("error"):
            ran_at = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn.execute("INSERT INTO backtest_runs (method, params, result, ran_at) VALUES (?,?,?,?)",
                         (key, json.dumps(run_params), json.dumps(out), ran_at))
            conn.commit()
            out["ran_at"] = ran_at
            out["params"] = run_params
        return out
    finally:
        conn.close()


def _ensure_backtest_runs(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS backtest_runs (
        id INTEGER PRIMARY KEY, method TEXT NOT NULL, params TEXT NOT NULL,
        result TEXT NOT NULL, ran_at TEXT NOT NULL)""")


def diagnose_payload(params) -> dict:
    conn = connect()
    try:
        bounds = conn.execute("SELECT MIN(txn_date) a, MAX(txn_date) b FROM transactions").fetchone()
        return diagnose.diagnose(
            conn,
            params.get("from", [bounds["a"]])[0],
            params.get("to", [data_end(conn)])[0],
            params.get("scope", ["investment"])[0])
    finally:
        conn.close()


def methods_payload(params) -> dict:
    conn = connect()
    try:
        key = params.get("method", ["cantonese-cat-monthly-reversion"])[0]
        end = data_end(conn)
        watchlist.ensure_schema(conn)
        syms = [r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]
        held = [p["symbol"] for p in holdings.positions(
            conn, performance.load_transactions(conn, "1900-01-01", end, "investment"), end)]
        universe = sorted(set(syms) | set(held))
        result = methods.scan(conn, universe, key, end)
        result["held"] = held
        result["catalogue"] = methods.catalogue()
        return result
    finally:
        conn.close()


def drawings_payload(params) -> dict:
    """Read, create, move and delete hand-drawn annotations.

    Writes go through the same cross-site guard as every other action, so a page
    you happen to visit cannot silently plant or erase lines on your charts.
    """
    conn = connect()
    try:
        symbol = (params.get("symbol", [""])[0] or "").strip().upper()
        timeframe = (params.get("timeframe", ["D"])[0] or "D").strip().upper()[:1]
        action = (params.get("action", [""])[0] or "").strip().lower()

        if action == "add":
            return drawings.add(
                conn, symbol, timeframe,
                params.get("kind", [""])[0],
                json.loads(params.get("points", ["[]"])[0]),
                pane=params.get("pane", ["price"])[0],
                colour=params.get("colour", [None])[0])
        if action == "move":
            return drawings.move(conn, int(params.get("id", ["0"])[0]),
                                 json.loads(params.get("points", ["[]"])[0]))
        if action == "remove":
            return drawings.remove(conn, int(params.get("id", ["0"])[0]))
        if action == "clear":
            return drawings.clear(conn, symbol, timeframe)
        return {"symbol": symbol, "timeframe": timeframe,
                "drawings": drawings.for_chart(conn, symbol, timeframe)}
    finally:
        conn.close()


def budget_upcoming(conn, classified, rec: dict | None, asof: str | None = None) -> dict:
    """The recurring charges expected before the next pay lands, and the bank
    cash they come out of. Paydays come from the salary deposits' own spacing."""
    from statistics import median
    today = date.fromisoformat(asof) if asof else date.today()
    # Two earners' deposits interleave (a 9-day median gap that is really two
    # biweekly cycles), so the cadence is read per payer and the next payday
    # is the earliest of them.
    by_payer: dict[str, set] = {}
    for t in classified:
        if t.get("category_kind") == "income" and t.get("category") == "Salary" and t.get("txn_date"):
            key = re.sub(r"[^A-Z]", "", str(t.get("description") or "").upper())[:10] or "salary"
            by_payer.setdefault(key, set()).add(str(t["txn_date"])[:10])
    nxt, step, last_pay = None, 14, None
    for key, days in by_payer.items():
        ds = sorted(date.fromisoformat(d) for d in days)
        if not ds:
            continue
        gaps = [(b - a).days for a, b in zip(ds[-7:], ds[-6:]) if 5 < (b - a).days < 60]
        st = round(median(gaps)) if gaps else 14
        cand = ds[-1]
        while cand <= today:
            cand = cand + timedelta(days=st)
        if nxt is None or cand < nxt:
            nxt, step = cand, st
        if last_pay is None or ds[-1] > last_pay:
            last_pay = ds[-1]
    pays = [last_pay] if last_pay else []
    bills = []
    for r in (rec or {}).get("subscriptions", []) + (rec or {}).get("habits", []):
        due = r.get("next_expected")
        if not due or r.get("kind") == "habit":
            continue
        d = date.fromisoformat(due[:10])
        # a charge a few days overdue is still coming; well past is a lapse
        if today - timedelta(days=5) <= d <= (nxt or today + timedelta(days=14)):
            bills.append({"merchant": r.get("merchant") or r.get("description"), "amount": r.get("typical"),
                          "due": d.isoformat(), "cadence": r.get("cadence"), "overdue": d < today})
    bills.sort(key=lambda b: b["due"])
    total = round(sum(b["amount"] or 0 for b in bills), 2)
    cash = None
    try:
        block = _networth_block(conn, (today - timedelta(days=45)).isoformat(), today.isoformat())
        pts = block.get("points") or []
        cash = pts[-1].get("cash") if pts else None
    except Exception:                                          # noqa: BLE001
        cash = None
    return {"next_payday": nxt.isoformat() if nxt else None, "pay_step_days": step, "last_pay": pays[-1].isoformat() if pays else None,
            "bills": bills, "total": total, "cash": cash,
            "after": round(cash - total, 2) if cash is not None else None}


def tax_insights(conn, classified, params) -> dict:
    """Bracket and contribution-limit arithmetic on what the ledger can see.

    Everything here is a FLOOR, and says so. A bank ledger records deposits, and
    a payroll deposit is net of tax and of pre-tax deferrals, so gross wages are
    always higher than what landed. Business receipts are revenue rather than
    profit. Neither is MAGI, which is what the Roth phase-out is measured
    against. Presenting any of it as a tax position would be wrong in a way that
    matters, so it is presented as what it is: a lower bound, useful for
    noticing that a limit is close, useless as a filing figure.
    """
    from datetime import date as _d
    year = int(params.get("year", [str(_d.today().year)])[0] or _d.today().year)
    status = (params.get("status", [DEFAULT_FILING_STATUS])[0]
              or DEFAULT_FILING_STATUS).strip()
    age_raw = (params.get("age", [""])[0] or "").strip()
    age = int(age_raw) if age_raw.isdigit() else DEFAULT_AGE
    if status not in taxes.FILING_STATUSES or year not in taxes.BRACKETS:
        return {"error": f"no table for {year} / {status}",
                "years": taxes.SUPPORTED_YEARS, "statuses": list(taxes.FILING_STATUSES)}

    received = 0.0
    by_source: dict[str, float] = {}
    for t in classified:
        if t.get("category_kind") != "income":
            continue
        if not str(t.get("txn_date") or "").startswith(str(year)):
            continue
        amount = float(t.get("amount") or 0.0)
        received += amount
        by_source[t["category"]] = round(by_source.get(t["category"], 0.0) + amount, 2)

    # Retirement contributions come from the brokerage side of the ledger, not
    # the bank: a payroll deferral never passes through checking at all.
    all_txns = performance.load_transactions(conn, f"{year}-01-01", f"{year}-12-31", "all")
    contribs = taxes.contributions(all_txns, year)

    # A pay stub, if one has been filed for this year, replaces the payroll
    # DEPOSITS with gross wages. The deposit is net of tax and of every
    # deferral, so using it as income understates the basis by tens of
    # thousands — in 2026 the deposits total about $58k against $90k of gross
    # wages through the same July stub. Business income and the rest still come
    # from the ledger; only the salary line is swapped, and only for the part of
    # the year the stub actually covers.
    stub = payroll_pdf.latest(conn, year)
    basis = received
    # The swap must replace ONLY the earner the stub belongs to. "Salary" is a
    # category, and in a two-income household it holds both people's payroll
    # deposits — so subtracting the whole category and adding one person's gross
    # back deleted the other person's wages from the basis entirely. Set
    # `stub_employer` to the payer name on the stub-holder's own deposits.
    employer = (config.load().get("stub_employer") or "").strip().lower()

    def is_stub_earner(t) -> bool:
        # The same two guards by_source applies. Without them this swept in
        # every year of history and every non-income row filed under Salary,
        # so the amount "replaced" came out at more than twice the category's
        # own total and the basis collapsed.
        if t.get("category_kind") != "income":
            return False
        if not str(t.get("txn_date") or "").startswith(str(year)):
            return False
        if t.get("category") != "Salary":
            return False
        if not employer:
            return True          # single-income: the old behaviour, unchanged
        return employer in str(t.get("description") or "").lower()

    mine = [t for t in classified if is_stub_earner(t)]
    # A name that matches NOTHING must not silently disable the swap. A typo in
    # `stub_employer`, or a payer that renames itself, would otherwise leave
    # salary_seen at zero — the stub's gross gets ADDED to deposits it was
    # supposed to replace, and the basis is overstated by a full year of net
    # pay with nothing on screen to say why. Falling back to the whole category
    # is the previous behaviour, which is wrong for two incomes but wrong by far
    # less, and it is reported rather than assumed.
    employer_matched = bool(mine)
    if employer and not employer_matched:
        mine = [t for t in classified
                if t.get("category_kind") == "income"
                and str(t.get("txn_date") or "").startswith(str(year))
                and t.get("category") == "Salary"]
    salary_seen = round(sum(float(t.get("amount") or 0.0) for t in mine), 2)
    if stub.get("gross"):
        # Deposits landing AFTER the stub's period end are still real income the
        # stub cannot know about, so they are kept rather than discarded.
        after = sum(float(t.get("amount") or 0.0) for t in mine
                    if str(t.get("txn_date") or "") > stub["pay_end"])
        basis = received - salary_seen + stub["gross"] + after
        stub = {**stub, "salary_deposits_replaced": round(salary_seen - after, 2),
                "salary_after_stub": round(after, 2),
                "employer_filter": employer or None,
                "employer_matched": employer_matched if employer else None,
                "other_salary_kept": round(
                    float(by_source.get("Salary") or 0.0) - salary_seen, 2)}

    # The taxable brokerage account's year: realised gains, dividends and
    # interest. The floor used to stop at deposits and the pay stub, so a year
    # with $80k of sales in the taxable account showed the same tax as one
    # with none — the user asked on 2026-09-13 where the tax on trades was.
    # Short-term gains, dividends and interest join ordinary income; a
    # long-term gain is taxed on top at its own rate (taxes.ltcg_tax).
    inv = taxes.investment_income(all_txns, year)
    deduction = taxes.STANDARD_DEDUCTION[year][status]
    taxable_wages_only = max(0.0, basis - deduction)
    basis = round(basis + inv["ordinary_addition"], 2)
    taxable = max(0.0, basis - deduction)
    band = taxes.bracket(taxable, year, status)
    roth = taxes.roth_allowance(basis + inv["long_term_taxed"], year, status, age)

    # Which limit a contribution counts against comes from the account's kind,
    # not from its name. Matching on the string "HSA" put the Health Savings
    # Account under the 401(k) limit, because it is not called HSA — and the
    # word "Roth" is worse than useless here: BrokerageLink Roth is a Roth 401(k)
    # SLEEVE, so it shares the employer deferral limit, while ROTH IRA is an IRA
    # with an entirely separate one. Only the plan mapping distinguishes them.
    kind_of = {r["name"]: (r["kind"], r["tax_status"])
               for r in conn.execute("SELECT name, kind, tax_status FROM accounts")}
    sleeves = reconcile.plan_sleeves(conn)
    plan_accounts = set(sleeves) | set(sleeves.values())
    roth_paid = hsa_paid = plan_paid = 0.0
    for name, amount in contribs.items():
        kind = kind_of.get(name, ("", ""))[0]
        if kind == "hsa":
            hsa_paid += amount
        elif name in plan_accounts:
            plan_paid += amount
        elif kind == "retirement":
            roth_paid += amount
    roth_paid, hsa_paid, plan_paid = round(roth_paid, 2), round(hsa_paid, 2), round(plan_paid, 2)
    # The 401(k) employee limit counts the EMPLOYEE's own deferral. What arrives
    # in the plan account is deferral plus the employer match, so measuring plan
    # inflow against the limit reports far less room than really remains — here
    # it was $20,938 of inflow against a $24,500 limit, when the employee had
    # actually deferred $14,396 and had over $10,000 still to give. A stub is
    # the only source that separates the two, so it wins when one is on file.
    #
    # The HSA is deliberately NOT switched: its limit counts employer and
    # employee contributions together, so total inflow is the right measure
    # there and the stub's employee-only figure would understate it.
    deferral_limit = taxes.RETIREMENT[year]["deferral_401k"]
    deferral_paid = plan_paid
    deferral_basis = "plan inflow, including any employer match"
    if stub.get("deferral_employee") is not None:
        deferral_paid = round(float(stub["deferral_employee"]), 2)
        deferral_basis = f"employee deferral from the {stub['pay_end']} pay stub"

    withheld = stub.get("federal_withheld")
    # Estimated payments already made this year (the Taxes category: IRS
    # USATAXPYMT and the preparer) are paid in just as withholding is. The
    # gap used to ignore them and flag a shortfall that did not exist.
    estimated_paid = round(sum(abs(float(t.get("amount") or 0.0)) for t in classified
                               if t.get("category") == "Taxes" and t.get("category_kind") == "expense"
                               and str(t.get("txn_date") or "").startswith(str(year))), 2)
    # Self-employment tax on 1099 income: 15.3% of 92.35% of it, half of which
    # comes off taxable income. A floor without it is not a floor for a
    # household with a 1099 month.
    business = round(sum(v for k, v in by_source.items() if re.search(r"business|1099|freelance|contract", k, re.I)), 2)
    se_tax = round(business * 0.9235 * 0.153, 2) if business > 0 else 0.0
    taxable_after_se = max(0.0, taxable - se_tax / 2)
    ltcg = taxes.ltcg_tax(taxable_after_se, inv["long_term_taxed"], year, status)
    owed = round(taxes.tax_owed(taxable_after_se, year, status) + se_tax + ltcg, 2)
    # What investing added to the bill: the floor with the account's year in,
    # less the floor without it. This is the one number the question asks for.
    owed_without = round(taxes.tax_owed(max(0.0, taxable_wages_only - se_tax / 2), year, status) + se_tax, 2)
    inv = {**inv, "ltcg_tax": ltcg, "tax_from_investing": round(owed - owed_without, 2)}
    paid_in = round(float(withheld or 0.0) + estimated_paid, 2) if (withheld is not None or estimated_paid) else None
    hsa_limits = taxes.HSA.get(year, {})
    hsa_coverage = (config.load().get("hsa_coverage") or "family").lower()
    hsa_limit = hsa_limits.get("family" if hsa_coverage.startswith("f") else "self")
    return {
        "estimated_paid": estimated_paid, "paid_in": paid_in,
        "investment": inv,
        "business_income": business, "se_tax": se_tax,
        "hsa_limit": hsa_limit, "hsa_coverage": hsa_coverage,
        "year": year, "status": status, "age": age,
        "received": round(basis, 2), "deposits": round(received, 2), "by_source": by_source,
        "standard_deduction": deduction,
        "taxable_floor": round(taxable, 2),
        "bracket": band,
        "tax_floor": owed,
        "payroll": stub or None,
        "federal_withheld": withheld,
        # Positive means more has been withheld than the floor figure owes. It
        # is a floor on both sides, so this is a direction, never a refund.
        "withholding_gap": (round(paid_in - owed, 2) if paid_in is not None else None),
        "roth": roth,
        # Where the year is HEADING, not just where it has got to. The figures
        # above are year-to-date and answer "am I over the line yet"; the
        # question actually being asked in September is "will I be", and by then
        # a Roth contribution made on the wrong assumption is already made.
        # Projected from BASE pay for the rest of the year, not by annualising
        # the year so far. The stub's own annual_rate is the base salary before
        # overtime; extrapolating year-to-date would multiply overtime already
        # worked across every month still to come. `spouse_annual` covers a
        # second income the stub cannot see.
        "crossings": taxes.crossings(
            basis, min(date.today().isoformat(), f"{year}-12-31"), year, status, age,
            base_annual=(float(stub["annual_rate"]) if stub.get("annual_rate")
                         else None),
            other_annual=float(config.load().get("spouse_annual") or 0.0)),
        "roth_contributed": roth_paid,
        "roth_remaining": round(max(0.0, roth["allowed"] - roth_paid), 2),
        "deferral_limit": deferral_limit,
        "deferral_contributed": deferral_paid,
        "deferral_basis": deferral_basis,
        "deferral_remaining": round(max(0.0, deferral_limit - deferral_paid), 2),
        "hsa_contributed": hsa_paid,
        "contributions": contribs,
        "years": taxes.SUPPORTED_YEARS,
        "statuses": list(taxes.FILING_STATUSES),
    }


def _networth_block(conn, start: str, end: str) -> dict:
    """Net worth over time and the savings rate, or a reason there is none."""
    try:
        block = networth.series(conn, start, end, anchors=cash.anchors(conn))
        classified = budget.classify(conn, budget.load_spending(conn, None, end))
        block["savings"] = networth.savings_rate(classified, start, end)
        # Twelve months regardless of the report window, because a savings rate
        # over three weeks is noise and the figure people mean by it is annual.
        year_start = (date.fromisoformat(end[:10]) - timedelta(days=365)).isoformat()
        block["savings_12m"] = networth.savings_rate(classified, year_start, end)
        return block
    except Exception as exc:                                   # noqa: BLE001
        # A missing half should cost the overview one panel, not the whole page.
        return {"error": f"{type(exc).__name__}: {exc}", "points": []}


def budget_payload(params) -> dict:
    """Spending, income and what is left, from the cash accounts.

    Seeded on first read rather than by a migration, so the categories exist the
    first time the tab is opened and there is no separate setup step to forget.
    """
    conn = connect()
    try:
        budget.ensure_seed(conn)
        start = (params.get("from", [""])[0] or "").strip() or None
        end = (params.get("to", [""])[0] or "").strip() or None
        account = (params.get("account", [""])[0] or "").strip() or None

        action = (params.get("action", [""])[0] or "").strip().lower()
        if action == "rule":
            # A rule written from the unmatched list, which is where the next
            # rule worth writing is always visible.
            return budget.add_rule(conn, params.get("pattern", [""])[0],
                                   params.get("category", [""])[0],
                                   int(params.get("priority", ["150"])[0] or 150))
        if action == "unrule":
            return budget.remove_rule(conn, int(params.get("id", ["0"])[0] or 0))
        if action == "dismiss":
            return recurring.dismiss(conn, params.get("merchant", [""])[0],
                                     params.get("note", [None])[0])
        if action == "undismiss":
            return recurring.undismiss(conn, params.get("merchant", [""])[0])

        txns = budget.load_spending(conn, start, end, account)
        classified = budget.classify(conn, txns)
        out = budget.summary(classified)
        # The tax year and the month's targets are questions about ALL the
        # history, not the filtered window: a from/to of January–June used to
        # drop "income counted" by $18k and blank the current month's goals.
        all_classified = budget.classify(conn, budget.load_spending(conn))
        full = budget.summary(all_classified) if (start or end or account) else out
        out["insights"] = tax_insights(conn, all_classified, params)
        out["goals"] = budget.goals(
            full.get("by_month") or [], full.get("by_category_month"),
            float(config.load().get("savings_goal") or budget.DEFAULT_SAVINGS_GOAL),
            category_months=full.get("category_months"))
        # Detected over ALL history, not the filtered window: a cadence needs
        # more than a few months to be visible at all, and a subscription does
        # not stop being one because you narrowed the date range.
        # Month-over-month, always over ALL history and never over the filtered
        # window: a category compared against three weeks of itself is noise.
        all_classified = budget.classify(conn, budget.load_spending(conn))
        out["trends"] = trends.changes(all_classified)
        # Your own spreadsheet against what the ledger computes, if one has been
        # imported. Absent until then, rather than an empty panel.
        out["reference"] = budget_grid.compare(conn, all_classified)
        month = out["trends"].get("month")
        if month:
            out["trends"]["unusual"] = trends.unusual_charges(all_classified, month)
            for row in out["trends"]["notable"]:
                row["drivers"] = trends.drivers(all_classified, month, row["category"])
        out["recurring"] = recurring.summary(
            recurring.detect(budget.classify(conn, budget.load_spending(conn))),
            hidden=recurring.dismissed(conn))
        # Bills due before the next payday, against the cash in the bank: the
        # question the Summary answered nowhere. Paydays are read off the salary
        # deposits themselves (biweekly by their own spacing).
        try:
            out["upcoming"] = budget_upcoming(conn, all_classified, out["recurring"], end)
        except Exception as exc:                               # noqa: BLE001
            out["upcoming"] = {"error": f"{type(exc).__name__}: {exc}"}
        out["accounts"] = budget.accounts(conn)
        out["categories"] = [dict(r) for r in conn.execute(
            "SELECT name, kind FROM categories ORDER BY kind, name")]
        out["rules"] = budget.load_rules(conn)
        out["from"], out["to"], out["account"] = start, end, account
        return out
    finally:
        conn.close()


def research_payload(params) -> dict:
    """The whole borrowed-technique library in one payload.

    Four kinds of artifact, kept apart on purpose because they answer different
    questions: a SETUP is how to read a chart, a FRAMEWORK is how the book should
    be shaped, an INTERMARKET signal is what regime we are probably in, and a
    THESIS is why a group of names might re-rate. Collapsing them into one list
    would make it far too easy to trade a thesis as though it were a setup.
    """
    conn = connect()
    try:
        end = data_end(conn)
        journal.ensure_schema(conn)
        out = {"as_of": end,
               "setups": setups.catalogue(),
               "frameworks": frameworks.catalogue(),
               "intermarket": intermarket.catalogue(),
               "macro": intermarket.macro_catalogue(),
               "theses": theses.catalogue(),
               # The followed accounts' calls, graded like the app's own.
               "outside": journal.outside_record(conn)}

        detail = params.get("key", [None])[0]
        kind = params.get("kind", [None])[0]
        if detail and kind == "intermarket":
            out["detail"] = intermarket.evaluate(conn, detail, end)
        elif detail and kind == "macro":
            out["detail"] = intermarket.evaluate_macro(conn, detail, date.today().isoformat())
            conn.commit()
        elif detail and kind == "thesis":
            out["detail"] = theses.exposure(conn, detail, end)
        elif detail and kind == "framework":
            txns = performance.load_transactions(conn, "1900-01-01", end, "investment")
            out["detail"] = frameworks.check(
                conn, holdings.positions(conn, txns, end), detail)
        elif detail:
            spec = setups.get(detail)
            out["detail"] = spec
            # A setup describes how to read a chart. Where a method implements it
            # as scoreable conditions, run it over holdings and watchlist so the
            # description and the names that currently satisfy it sit together.
            # ?noscan=1: the page draws this scan from /api/methods (the one
            # scanner under Stocks → New Stocks) and only links to it from
            # here, so the same scan is not run twice for one click.
            if spec and spec.get("scan") and not params.get("noscan"):
                watchlist.ensure_schema(conn)
                listed = [r["symbol"] for r in
                          conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]
                txns = performance.load_transactions(conn, "1900-01-01", end, "investment")
                held = [p["symbol"] for p in holdings.positions(conn, txns, end)]
                result = methods.scan(conn, sorted(set(listed) | set(held)),
                                      spec["scan"], end)
                result["held"] = held
                out["scan"] = result

        # The DCA ladder is a framework whose tier depends on the name, so it is
        # computed per holding rather than once.
        if params.get("dca"):
            txns = performance.load_transactions(conn, "1900-01-01", end, "investment")
            out["dca"] = [frameworks.dca_multiplier(conn, p["symbol"], end)
                          for p in holdings.positions(conn, txns, end)]
            out["dca"] = [d for d in out["dca"] if not d.get("insufficient")]
        return out
    finally:
        conn.close()


def replay_payload(params) -> dict:
    """The calibration of the replayed engine, cached against the replay itself.

    Grading eighty thousand reconstructed calls takes the better part of a
    minute, which is fine once and unacceptable on every page load. The report
    is stored keyed on the horizon and the number of replayed rows, so it is
    recomputed only when the replay has grown — after a nightly run adds a
    week, or while the first full run is still in progress.
    """
    horizon = int(params.get("horizon", ["21"])[0])
    conn = connect()
    try:
        journal.ensure_schema(conn)
        conn.execute("""CREATE TABLE IF NOT EXISTS replay_reports (
            horizon INTEGER NOT NULL, calls INTEGER NOT NULL, computed_at TEXT NOT NULL,
            report TEXT NOT NULL, PRIMARY KEY (horizon))""")
        # Where the replayed calls live is the replay module's business: they
        # move to ledger-replay.db (split_replay) and a query naming the main
        # `decisions` table would read zero once they have.
        status = replay.status(conn)
        n = status["calls"]
        if not n:
            return {"none": True, "note": "No replayed calls yet. Run python3 -m app.replay run."}
        row = conn.execute("SELECT calls, computed_at, report FROM replay_reports WHERE horizon=?",
                           (horizon,)).fetchone()
        if row and row["calls"] == n:
            out = json.loads(row["report"])
            out["computed_at"] = row["computed_at"]
            return out
        out = calibration.report(conn, horizon, source="replay")
        out["status"] = status
        out["running"] = status["running"]
        out["caveats"] = [
            "Every name is scored as if unheld, so trim and add never fire: the calls are buy, hold and sell.",
            "No market sentiment: the fear-and-greed series is only cached from August 2026.",
            "The universe is today's watchlist and everything ever traded — a list of names that were worth "
            "watching — so every hit rate here is biased upward by an amount nobody can state.",
            "Bars are truncated to each decision date before the engine sees them; nothing is scored on "
            "a bar it could not have had.",
        ]
        computed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute("""INSERT INTO replay_reports (horizon, calls, computed_at, report) VALUES (?,?,?,?)
                        ON CONFLICT(horizon) DO UPDATE SET calls=excluded.calls,
                          computed_at=excluded.computed_at, report=excluded.report""",
                     (horizon, n, computed_at, json.dumps(out)))
        conn.commit()
        out["computed_at"] = computed_at
        return out
    finally:
        conn.close()


def paper_payload(params) -> dict:
    conn = connect()
    try:
        return paper.report(conn)
    finally:
        conn.close()


def discover_payload(params) -> dict:
    conn = connect()
    try:
        out = discover.hits(conn)
        # The accumulation list rides on the same payload rather than its own
        # endpoint: it answers the same question the tab is for — what is worth
        # looking at that is not already on the list — and a second request
        # would double the page's cost for one table.
        acc = discover.describe(conn, discover.accumulation_hits(conn))
        # Volume says something is happening; the crowd reading says whether
        # anybody the user follows has noticed. Together they are the "are we
        # early?" judgement the note asked for — neither answers it alone.
        if acc:
            crowd = authors.crowd(conn, [a["symbol"] for a in acc], date.today().isoformat())
            for a in acc:
                a["crowd"] = crowd.get(a["symbol"])
        # The method lists get the same description, so a reader can tell a
        # software name from a shipping company without opening each one.
        for m in (out.get("methods") or {}).values():
            m["hits"] = discover.describe(conn, (m.get("hits") or [])[:15]) + (m.get("hits") or [])[15:]
        out["accumulation"] = acc
        out["crowd_coverage"] = authors.mention_coverage(conn)
        return out
    finally:
        conn.close()


def rotation_payload() -> dict:
    conn = connect()
    try:
        out = sectors.rotation(conn)
        # Themes measured the same way, so the Sectors tab can put "is space
        # leading" beside "is energy leading".
        out["themes"] = themes.rotation(conn).get("themes", [])
        out["theme_funds"] = themes.THEME_ETFS
        conn.commit()
        return out
    finally:
        conn.close()


# Every JSON endpoint, in one table. Adding a route here is the whole change.
# Names this server will answer to. Anything else is a rebinding attempt or a
# misconfiguration, and either way is not a request this tool should serve.
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}

# Reading is not a write. Everything else with an `action` is, including any
# action added later — defaulting to "protected" is the only ordering that
# survives someone forgetting to update this set.
READ_ONLY_ACTIONS = {"", "list", "get", "rows"}

# ------------------------------------------------------- response cache ----
# The server is CPU-bound Python behind a GIL, so two browser tabs do not share
# the machine, they queue for it. Opening a second tab while the first is
# loading starved it for half a minute — eleven panels each recomputing answers
# the other tab had just computed.
#
# Nothing here is made faster. The same answer is simply not computed twice.
#
# Freshness comes from the ledger's cache epoch (ledger.py) rather than a
# timer: any import, any daily bar, any watchlist edit bumps it, and every
# cached answer is derived from it, so one comparison invalidates exactly the
# right set. It used to be the database FILE's mtime, which had the same shape
# and one flaw: every five-minute chart open writes intraday candles and a
# fetch-log row, and each of those dropped the whole cache — eleven panels
# recomputed for a write no panel reads. The TTL is only a backstop for
# changes that somehow leave the epoch untouched.
_RESPONSE_CACHE: dict = {}
_RESPONSE_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 120.0
_CACHE_MAX = 64
CACHE_STATS = {"hits": 0, "misses": 0, "waited": 0}
# One Event per key being built, so a second identical miss waits for the
# first build instead of running its own. Without this two tabs opening the
# same panel at once both computed it — and for the watchlist outlook that is
# twice fifteen seconds of CPU behind one GIL, which is the very thing the
# cache exists to stop.
_IN_FLIGHT: dict = {}
_STAMP_CONN = None


def _db_stamp() -> int:
    """The ledger's cache epoch, read on a connection kept for the purpose.

    A read-only query on WAL costs microseconds and always sees the last
    commit; a full ledger.connect() would run the schema script per request.
    """
    global _STAMP_CONN
    from .ledger import cache_epoch
    with _RESPONSE_CACHE_LOCK:
        try:
            if _STAMP_CONN is None:
                _STAMP_CONN = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
            return cache_epoch(_STAMP_CONN)
        except sqlite3.Error:
            _STAMP_CONN = None
            return 0


# Answers that must be live every time: the health check reports on the
# cache, so an answer served from it would be describing itself.
UNCACHED_PATHS = {"/api/health"}


# Whether the request on THIS thread was served from the cache, for the log
# line. Thread-local because the server handles requests on several.
_LAST = threading.local()


def cached_payload(path: str, params: dict, build):
    """One answer per (endpoint, query, database state)."""
    _LAST.hit = False
    if path in UNCACHED_PATHS:
        return build()
    key = (path, tuple(sorted((k, tuple(v)) for k, v in params.items())))
    stamp, now = _db_stamp(), time.time()
    while True:
        with _RESPONSE_CACHE_LOCK:
            hit = _RESPONSE_CACHE.get(key)
            if hit and hit[0] == stamp and now - hit[1] < _CACHE_TTL:
                CACHE_STATS["hits"] += 1
                _LAST.hit = True
                return hit[2]
            pending = _IN_FLIGHT.get(key)
            if pending is None:
                pending = _IN_FLIGHT[key] = threading.Event()
                mine = True
            else:
                mine = False
        if mine:
            break
        # Somebody else is building this exact answer. Wait for it, then
        # re-check the cache: it is there unless the build raised or the
        # database moved underneath it, in which case the loop builds afresh.
        CACHE_STATS["waited"] += 1
        pending.wait()
        now = time.time()
    # Built OUTSIDE the lock. Holding it across the work would serialise every
    # request behind the slowest one, which is the problem this exists to fix.
    try:
        value = build()
    finally:
        with _RESPONSE_CACHE_LOCK:
            _IN_FLIGHT.pop(key, None)
            pending.set()
    with _RESPONSE_CACHE_LOCK:
        CACHE_STATS["misses"] += 1
        _RESPONSE_CACHE[key] = (stamp, now, value)
        if len(_RESPONSE_CACHE) > _CACHE_MAX:
            for stale in sorted(_RESPONSE_CACHE, key=lambda k: _RESPONSE_CACHE[k][1]
                                )[:len(_RESPONSE_CACHE) - _CACHE_MAX]:
                _RESPONSE_CACHE.pop(stale, None)
    return value


def clear_response_cache() -> None:
    with _RESPONSE_CACHE_LOCK:
        _RESPONSE_CACHE.clear()


# ----------------------------------------------------------- observability ----
# Handler.log_message is silenced (a personal tool; the default line per hit
# is noise), which left nothing at all to look at when a tab took thirty
# seconds. One line per API request instead — path, time, size, whether the
# cache served it — kept in memory for /api/health and printed when
# INVESTMENT_APP_LOG=1. do_GET calls this once per response.
STARTED = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
_LOG_TO_STDOUT = os.environ.get("INVESTMENT_APP_LOG", "0") != "0"
RECENT_REQUESTS: list = []
_RECENT_MAX = 200


def log_request(path: str, ms: float, size: int, hit: bool, status: int = 200) -> None:
    """Record one served request. Cheap; safe from any thread."""
    entry = {"at": datetime.now().strftime("%H:%M:%S"), "path": path,
             "ms": round(ms, 1), "bytes": size, "hit": hit, "status": status}
    with _RESPONSE_CACHE_LOCK:
        RECENT_REQUESTS.append(entry)
        del RECENT_REQUESTS[:-_RECENT_MAX]
    if _LOG_TO_STDOUT or ms >= 2000:
        # Anything over two seconds is printed regardless: that is the line
        # somebody will want when they ask why the page hung.
        print(f"  {entry['at']} {status} {ms:7.0f}ms {size:>9}B {'hit ' if hit else 'miss'} {path}",
              flush=True)


def source_stamp() -> float:
    """Newest mtime across the app's source and static files."""
    newest = 0.0
    for path in list(HERE.glob("**/*.py")) + list(HERE.glob("static/*")) + [HERE / "dashboard.html"]:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass
    return newest


# Taken at import. The running process serves THIS code whatever is on disk
# now; when the disk is newer, the process is stale and the page can show a
# tab whose endpoint 404s. /api/health makes that visible, and run_tests.sh
# checks it at the end of every run.
SOURCE_STAMP = source_stamp()


def health_payload(params) -> dict:
    disk = source_stamp()
    fmt = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else None
    with _RESPONSE_CACHE_LOCK:
        recent = list(RECENT_REQUESTS[-20:])
        cache = dict(CACHE_STATS, entries=len(_RESPONSE_CACHE), in_flight=len(_IN_FLIGHT))
    return {"pid": os.getpid(), "started": STARTED,
            "source_stamp": fmt(SOURCE_STAMP), "disk_stamp": fmt(disk),
            "stale": disk > SOURCE_STAMP, "epoch": _db_stamp(),
            "cache": cache, "recent": recent}


# ------------------------------------------------------------ encoding ----
# Bodies over this size are gzipped when the client allows it. The watchlist
# outlook is 2.4 MB of JSON that compresses about eight to one; below a few
# KB the headers cost more than the bytes saved.
GZIP_MIN_BYTES = 4096


def encode_body(handler, body: bytes, content_type: str,
                etag_of: Path | None = None, salt: str = "") -> tuple[bytes, list[tuple[str, str]], int]:
    """Compress and tag a response body for `handler`'s request.

    Returns (body, headers, status). Status is 304 with an empty body when
    the request's If-None-Match matches the ETag — the dashboard page and the
    vendored chart library are then never re-sent. `etag_of` is the file the
    body came from; its mtime and size make the tag, which is what changes
    when the file does, and `salt` is anything else baked into the body (the
    page carries the write token). JSON answers get no ETag: they are keyed
    on the database state already and change with it.

    The caller (Handler._send) still writes Content-Length and ends the headers.
    """
    import gzip
    import hashlib
    headers: list[tuple[str, str]] = [("Content-Type", content_type)]
    if etag_of is not None:
        try:
            st = etag_of.stat()
            tag = f'"{int(st.st_mtime)}-{st.st_size}'
            tag += ("-" + hashlib.sha1(salt.encode()).hexdigest()[:8] if salt else "") + '"'
        except OSError:
            tag = None
        if tag:
            headers.append(("ETag", tag))
            if (handler.headers.get("If-None-Match") or "").strip() == tag:
                return b"", headers, 304
    accepts = (handler.headers.get("Accept-Encoding") or "").lower()
    if len(body) >= GZIP_MIN_BYTES and "gzip" in accepts:
        body = gzip.compress(body, compresslevel=5)
        headers.append(("Content-Encoding", "gzip"))
        headers.append(("Vary", "Accept-Encoding"))
    return body, headers, 200

def rebuy_payload(params) -> dict:
    """Buying back: the readings on every name sold out of or trimmed in the
    last year, and the watchlist, with the state in words (D73)."""
    from . import rebuy
    with connect() as conn:
        asof = date.today().isoformat()
        txns = performance.load_transactions(conn, "2015-01-01", asof)
        watch = watchlist.symbols(conn) if hasattr(watchlist, "symbols") else []
        return rebuy.screen(conn, txns, asof, watch)


def plans_payload(params) -> dict:
    """Buy plans for the next session: list, add, remove."""
    from . import plans
    conn = connect()
    try:
        action = (params.get("action", [""])[0] or "").strip().lower()
        if action == "add":
            plans.add(conn, params.get("symbol", [""])[0], float(params.get("max_price", ["0"])[0] or 0),
                      float(params.get("gap_pct", ["2"])[0] or 2), params.get("note", [None])[0])
        elif action == "remove":
            plans.remove(conn, int(params.get("id", ["0"])[0] or 0))
        return {"plans": plans.active(conn)}
    except ValueError as exc:
        return {"error": str(exc)}
    finally:
        conn.close()


def setup_payload(params) -> dict:
    """What a fresh install still needs (the first-run screen)."""
    from . import setup_flow
    conn = connect()
    try:
        return setup_flow.status(conn)
    finally:
        conn.close()


def valuetrader_payload(params) -> dict:
    """The Value Trader's posts from the notification emails: read the mailbox
    when asked (cached like everything else), store what is new, list them."""
    from . import valuetrader
    conn = connect()
    try:
        r = valuetrader.sync(conn)
        return {**r, "posts": valuetrader.recent(conn, 400), "author": valuetrader.AUTHOR}
    finally:
        conn.close()


def substack_charts_payload(params) -> dict:
    """The followed Substack's charts, per symbol. Local files only, no network.

    Every chart he has posted goes out, about 1,800 rows from a year of posts:
    the Follow tab filters by name and date itself and shows at most eighty
    cards, and the body is cached and gzipped. A cap of 120 rows here used to
    hide every name older than the newest two weeks (see substack_charts).
    """
    from . import substack_charts
    sym = (params.get("symbol", [""])[0] or "").strip().upper()
    rows = substack_charts.charts()
    symbols = sorted({r["symbol"] for r in rows})
    if sym:
        rows = [r for r in rows if r["symbol"] == sym]
    return {"charts": rows, "symbols": symbols}


def x_charts_payload(params) -> dict:
    """The charts the followed accounts posted on X, saved nightly (xcharts.py).
    `symbol=` narrows to one name for the symbol page."""
    from . import xcharts
    sym = (params.get("symbol", [""])[0] or "").strip().upper()
    conn = connect()
    try:
        return {"charts": xcharts.charts(conn, symbol=sym or None)}
    finally:
        conn.close()


def amazon_payload(params) -> dict:
    """Refund emails against card credits. Reads the mailbox, so it is only
    fetched when the Loose ends panel asks, and cached like everything else."""
    conn = connect()
    try:
        return amazon.report(conn)
    finally:
        conn.close()


# Which timeframe's levels a book's holding period is read off, in order of
# preference. A position held for days to weeks is traded on levels the daily
# and weekly charts draw; one accumulated over months is not, and reading a
# months-long position off the daily produces an invalidation level it would
# trip on an ordinary week.
#
# This is the substance behind showing the holding period instead of the
# daily/weekly/monthly grid — "the values depend on the length of the trade".
# Picking by headline timeframe instead meant the levels came from whichever
# chart the engine happened to reach its call on, which is not a property of
# the trade the user is in.
WATCH_BY_BOOK = {"swing": ("daily", "weekly", "monthly"),
                 "conviction": ("weekly", "monthly", "daily")}


def _pick_watch(v: dict, book: str | None = None) -> dict | None:
    order = WATCH_BY_BOOK.get(book or "swing", WATCH_BY_BOOK["swing"])
    for tf in order:
        w = (v.get(tf) or {}).get("watch") or {}
        if w.get("buy_at") or w.get("trim_at") or w.get("stop_at"):
            return w
    # Nothing on any timeframe has a level worth acting on. Nothing is what is
    # returned — not another timeframe's levels dressed up as this trade's.
    # The reading says "no buy level, no sell level" in that case, which is a
    # finding rather than a gap.
    return None


def outlook_payload(params) -> dict:
    """Verdicts on what is held, what changed, and the record of past calls.

    Reading this endpoint never writes a verdict. The nightly `app.outlook` job
    is the only thing that records what the app called, and it has to stay that
    way: if opening the page wrote a row, the journal would fill with calls made
    at whatever moments somebody happened to look, and "what did the app say on
    the 14th" would depend on browsing history rather than on the market.

    Recording a decision of your OWN is a write, and goes through the same
    cross-site guard as every other action here.
    """
    conn = connect()
    try:
        journal.ensure_schema(conn)
        action = (params.get("action", [""])[0] or "").strip().lower()
        symbol = (params.get("symbol", [""])[0] or "").strip().upper()

        if action == "record":
            decision = (params.get("decision", [""])[0] or "").strip().lower()
            if decision not in journal.SIGN:
                return {"error": f"unknown decision {decision!r}",
                        "allowed": sorted(journal.SIGN)}
            if not symbol:
                return {"error": "a decision needs a symbol"}
            when = (params.get("date", [""])[0] or
                    date.today().isoformat())
            px = (params.get("price", [""])[0] or "").strip()
            bucket = (params.get("bucket", [""])[0] or "").strip().lower() or None
            if bucket and bucket not in journal.BUCKETS:
                return {"error": f"unknown bucket {bucket!r}", "allowed": list(journal.BUCKETS)}
            try:
                px_f = float(px) if px else None
            except ValueError:
                return {"error": "price must be a number"}
            journal.record(conn, when, symbol, "me", decision,
                           price=px_f,
                           rationale=(params.get("note", [""])[0] or None)[:1000]
                           if params.get("note", [""])[0] else None,
                           bucket=bucket)
            conn.commit()
            clear_response_cache()
            return {"ok": True, "symbol": symbol, "decision": decision,
                    "date": when,
                    "history": journal.history(conn, symbol=symbol, limit=50)}

        if action == "outside":
            # A call made by somebody the user follows, recorded so the same
            # grading that scores the app's calls scores theirs.
            author = (params.get("author", [""])[0] or "").strip()[:80]
            decision = (params.get("decision", [""])[0] or "").strip().lower()
            if not author:
                return {"error": "an outside call needs the account it came from"}
            if decision not in journal.SIGN:
                return {"error": f"unknown decision {decision!r}",
                        "allowed": sorted(journal.SIGN)}
            if not symbol:
                return {"error": "a call needs a symbol"}
            when = (params.get("date", [""])[0] or date.today().isoformat())[:10]
            px = (params.get("price", [""])[0] or "").strip()
            lvl = (params.get("level", [""])[0] or "").strip()
            try:
                px_f = float(px) if px else None
                lvl_f = float(lvl) if lvl else None
            except ValueError:
                return {"error": "price and level must be numbers"}
            note = (params.get("note", [""])[0] or "").strip()[:1000] or None
            prices.ensure_symbol(conn, symbol, "2018-01-01", date.today().isoformat(), as_equity=True)
            did = journal.record(conn, when, symbol, "outside", decision, price=px_f,
                                 flip=lvl_f, rationale=note, author=author)
            conn.commit()
            clear_response_cache()
            return {"ok": True, "id": did, "author": author, "symbol": symbol,
                    "decision": decision, "date": when,
                    "outside": journal.outside_record(conn)}

        if action == "outside_delete":
            try:
                did = int(params.get("id", [""])[0])
            except ValueError:
                return {"error": "a decision id is needed"}
            r = journal.remove_outside(conn, did)
            conn.commit()
            clear_response_cache()
            return {**r, "outside": journal.outside_record(conn)}

        if action == "setcore":
            raw = (params.get("value", [""])[0] or "").strip()
            try:
                core = float(raw) if raw else None
            except ValueError:
                return {"error": "the core must be a number of shares"}
            r = books.set_core(conn, symbol, core)
            if r.get("error"):
                return r
            conn.commit()
            clear_response_cache()
            return r

        if action == "setbook":
            value = (params.get("value", [""])[0] or "").strip().lower()
            ta_raw = (params.get("trade_around", [""])[0] or "").strip().lower()
            ta = True if ta_raw in ("1", "true", "yes") else False if ta_raw in ("0", "false", "no") else None
            r = books.set_book(conn, symbol, value, ta,
                               (params.get("note", [""])[0] or None))
            if r.get("error"):
                return r
            conn.commit()
            clear_response_cache()
            return r

        if action in ("tag", "bucket"):
            # What happened (tag) or which book it was in (bucket), on a call
            # of your own. Both are how the record becomes a finding about
            # how you trade rather than a list.
            try:
                did = int(params.get("id", [""])[0])
            except ValueError:
                return {"error": "a decision id is needed"}
            value = (params.get("value", [""])[0] or "").strip().lower() or None
            r = (journal.set_tag(conn, did, value) if action == "tag"
                 else journal.set_bucket(conn, did, value))
            if r.get("error"):
                return r
            conn.commit()
            clear_response_cache()
            return {**r, "buckets": list(journal.BUCKETS), "tags": list(journal.TAGS)}

        if action == "refresh":
            # Prices are cached and the nightly job runs after the close, so
            # during the session the app shows yesterday's bars and said nothing
            # about it. This is the manual pull.
            from datetime import date as _d
            end = _d.today().isoformat()
            out = {"ok": False}
            if prices.alpaca_credentials():
                r = prices.sync_holdings(conn, "2024-01-01", end)
                # The watchlist as well, when that is what is on screen —
                # scoring 145 names off five-day-old bars is the same defect as
                # doing it for a holding.
                w = ({"priced": [], "failed": []}
                     if (params.get("scope", [""])[0] or "") != "watchlist"
                     else prices.sync_watchlist(conn, "2024-01-01", end))
                for b in ("SPY", "QQQ"):
                    prices.sync_benchmark(conn, b)
                conn.commit()
                clear_response_cache()
                out = {"ok": True, "priced": len(r["priced"]) + len(w["priced"]),
                       "failed": len(r["failed"]) + len(w["failed"])}
            else:
                out = {"ok": False, "error": "no Alpaca credentials"}
            out["prices_asof"] = prices.last_bar_date(conn)
            return out

        if action == "forget":
            try:
                did = int(params.get("id", ["0"])[0])
            except ValueError:
                return {"error": "a decision id is needed"}
            conn.execute("DELETE FROM decisions WHERE id=? AND source='me'", (did,))
            conn.commit()
            clear_response_cache()
            return {"ok": True}

        try:
            horizon = int(params.get("horizon", ["21"])[0] or 21)
        except ValueError:
            horizon = 21
        if horizon not in journal.HORIZONS:
            horizon = 21

        if symbol:
            # `asof` is the bar-replay control on the Chart tab: everything the
            # engine sees is truncated to that date, the same rule the replay
            # lives by, so "what would it have said on the 12th" is answered
            # by the engine rather than by memory. Sentiment is left out on a
            # past date, since the series only exists from August 2026.
            asof = (params.get("asof", [""])[0] or "").strip()[:10] or date.today().isoformat()
            replaying = asof < date.today().isoformat()
            bars, _proxy = prices.analysis_bars(conn, symbol, "2015-01-01", asof)
            bars = [b for b in bars if b["time"] <= asof]
            txns = performance.load_transactions(conn, "1900-01-01", asof, "investment")
            pos = next((p for p in holdings.positions(conn, txns, asof)
                        if p["symbol"] == symbol), None)
            if pos:
                books.attach(conn, [pos])
            measured = {tf: measure.load_profile(conn, tf) for tf in ("D", "W", "M")}
            watchlist.ensure_schema(conn)
            everything = sorted({symbol} | {r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist")}
                                | {p["symbol"] for p in holdings.positions(conn, txns, asof)})
            context = {"rs_rank": watchlist.rs_ranks(conn, everything, asof).get(symbol),
                       "regime": regime.reading(conn, asof)}
            ta = (trade_around.plan(conn, symbol, asof)
                  if pos and pos.get("trade_around") else None)
            # Whether the accounts the user follows are already on the name,
            # for the symbol page's "who I follow on it" — the same reading
            # the discovery list carries per accumulation hit. Optional: an
            # empty mentions table is a reading of nothing, not a failure.
            try:
                crowd = authors.crowd(conn, [symbol], date.today().isoformat()).get(symbol)
                crowd_coverage = authors.mention_coverage(conn)
            except Exception:                                  # noqa: BLE001
                crowd, crowd_coverage = None, None
            return {"symbol": symbol, "position": pos, "asof": asof, "replaying": replaying,
                    "trade_around": ta, "crowd": crowd, "crowd_coverage": crowd_coverage,
                    "verdict": verdicts.both_timeframes(
                        bars, pos, None if replaying else sentiment.evidence(sentiment.latest(conn)),
                        measured, context)
                    if bars else None,
                    "history": journal.history(conn, symbol=symbol, limit=50)}

        scope = (params.get("scope", ["held"])[0] or "held").strip().lower()
        if scope not in ("held", "watchlist", "all"):
            scope = "held"
        # ?lite=1 leaves out the per-name detail nothing but the verdict
        # drawer's "why this call" table draws: the tally's zero-weight context
        # rows and the trendline list. The page fetches the watchlist ONCE and
        # shares it between the Outlook sub-tab, the Watchlist tab and Setups,
        # so anything Setups reads (the record, outside calls, the watch
        # levels) has to stay in — dropping those saved another 12% and
        # blanked the followed accounts' levels on every watchlist setup.
        lite = (params.get("lite", [""])[0] or "").strip().lower() in ("1", "true", "yes")
        # Every failure below that is caught lands here, by panel, and goes
        # out with the answer. A panel that quietly came back empty read as
        # "nothing to show" — a wash-sale check that raised looked like no
        # wash sales.
        problems: dict = {}
        # Watchlist names are served from verdict_cache (outlook.py) and only
        # the stale ones are scored; held names are always scored live.
        out = outlook.run(conn, dry_run=True, scope=scope, use_cache=(scope == "watchlist"))
        # Position size travels with the verdict so the table can be ordered by
        # consequence. A change on a $37k holding outranks one on $2k, and any
        # other ordering buries the row that matters — the same rule the
        # Overview attention list follows.
        held_pos = books.attach(conn, outlook._held(conn, out["asof"]))
        held = {p["symbol"]: p.get("value") for p in held_pos}
        held_book = {p["symbol"]: {"book": p["book"], "trade_around": p["trade_around"],
                                   "note": p.get("book_note"), "default": p.get("book_default")}
                     for p in held_pos}
        # The newest bar anything was scored from. A verdict computed off
        # yesterday's close during today's session is not wrong, but it is
        # answering a different question than the one being asked, and the page
        # said nothing about which.
        prices_asof = prices.last_bar_date(conn)
        # The next report date for every name scored, so a call can carry
        # "reports in 3 days" beside it. Context, not evidence.
        upcoming_earnings = earnings.upcoming(conn, list(out["results"]), out["asof"])
        # The measured weights, if the measurement has been run. The score is
        # the sum of the measured residuals of the items a call carries: what
        # calls like this one did after the universe's drift was taken out.
        mw = {tf: measure.load_weights(conn, tf) for tf in ("D", "W", "M")}
        # Buying back inside 30 days of a loss sale disallows the loss. The
        # ledger's transactions say which names were sold at a loss and when;
        # the confirmation emails add the sales the statement has not shown
        # yet. Carried per symbol so a buy or add can warn on the row.
        inv_txns = []
        try:
            inv_txns = performance.load_transactions(conn, "2015-01-01", out["asof"])
            wash_by_symbol = washsales.rebuy_warnings(conn, inv_txns, out["asof"])
        except Exception as exc:                               # noqa: BLE001
            wash_by_symbol = {}
            problems["wash"] = f"{type(exc).__name__}: {exc}"
        # The sell ladder (D69, D71) on every held name from the position's
        # entry: which rungs have fired, and the price or reading for the next.
        ladder_by_symbol: dict = {}
        drawdown_by_symbol: dict = {}
        rebuy_by_symbol: dict = {}
        try:
            from . import rebuy
            entries = ladder.entry_dates(inv_txns)
            zones_since = (date.fromisoformat(out["asof"]) - timedelta(days=180)).isoformat()
            author_zones = authors.recent(conn, zones_since, per_symbol=12)
            sold = rebuy.sales(inv_txns, (date.fromisoformat(out["asof"]) - timedelta(days=365)).isoformat(), out["asof"])
            for s in held:
                if s in out["results"]:
                    # the same bars the verdict reads: the home listing,
                    # rescaled, when chart_proxy names one (SIVEF -> SIVE.ST)
                    bars_s, _px = prices.analysis_bars(conn, s, "2015-01-01", out["asof"])
                    st = ladder.state(bars_s, entries.get(s))
                    if st:
                        ladder_by_symbol[s] = {**st, "summary": ladder.summary(st)}
                    # the buy-back readings a held name would show on the
                    # Buying back screen, on its own card instead (one list per name)
                    # Where the position sits in its own drawdown, and what
                    # followed for names that reached that depth (D98).
                    dd = exits.drawdown_reading(bars_s, entries.get(s))
                    if dd:
                        drawdown_by_symbol[s] = dd
                    rd = rebuy.readings(bars_s)
                    if rd:
                        state, have, missing = rebuy.judge(rd, sold.get(s), rebuy.zones_for(author_zones.get(s, []), rd["price"]))
                        rebuy_by_symbol[s] = {"state": state, "have": have, "missing": missing, "drawdown": rd["drawdown"], "wr": rd["wr_done"]}
        except Exception as exc:                               # noqa: BLE001
            ladder_by_symbol = ladder_by_symbol or {}
            problems["ladder"] = f"{type(exc).__name__}: {exc}"
        # Sector strength travels with the verdicts so Setups can ask whether a
        # name's sector is leading or lagging the market (StonkChris's "chart,
        # sector, etc."). Rank 1 is the strongest of the eleven.
        sector_of: dict = {}
        sector_rank: dict = {}
        try:
            sector_of = {k: (v or {}).get("sector") for k, v in sectors.lookup(conn, list(out["results"])).items()}
            rot = sectors.rotation(conn).get("sectors") or []
            for i, r in enumerate(rot):
                if r.get("score") is not None:
                    sector_rank[r[list(r.keys())[0]] if "sector" not in r else r["sector"]] = {"score": round(r["score"], 4), "rank": i + 1, "of": len(rot)}
        except Exception as exc:                               # noqa: BLE001
            sector_of, sector_rank = {}, {}
            problems["sector"] = f"{type(exc).__name__}: {exc}"
        since = (date.fromisoformat(out["asof"]) - timedelta(days=90)).isoformat()
        try:
            from . import valuetrader
            charts_by_symbol = valuetrader.by_symbol(conn, 120)
        except Exception as exc:                               # noqa: BLE001
            charts_by_symbol = {}
            problems["charts"] = f"{type(exc).__name__}: {exc}"
        outside_by_symbol: dict = {}
        for r in conn.execute("""SELECT symbol, author, date, action, flip, price, rationale FROM decisions
                                 WHERE source='outside' AND date >= ? ORDER BY date DESC""", (since,)):
            if journal.ideas_only(r["author"]):
                continue
            lst = outside_by_symbol.setdefault(r["symbol"], [])
            if len(lst) < 6:
                lst.append({"author": r["author"], "date": r["date"], "action": r["action"],
                            "level": r["flip"], "price": r["price"], "note": (r["rationale"] or "")[:160]})
        # ...and the zones and targets they named without making a call — the
        # buy zone below price that the journal does not grade (D51) but the
        # user wants to see beside the app's level (D68).
        # Taken in strict recency order this filled up on whichever kind the
        # newest source happened to name — IREN showed two targets and not one
        # level below price, which is half the question. Interleaving by kind
        # means a name always says where it goes AND where it goes if the call
        # is wrong, which is the pair the user asked for.
        LABEL = {"buy_zone": "buy zone", "downside": "downside zone", "target": "target"}
        for sym_, rows_ in authors.recent(conn, since).items():
            lst = outside_by_symbol.setdefault(sym_, [])
            by_kind: dict = {}
            for r in rows_:
                by_kind.setdefault(r["kind"], []).append(r)
            ordered = []
            for i in range(max((len(v) for v in by_kind.values()), default=0)):
                for kind in ("target", "buy_zone", "downside"):
                    if i < len(by_kind.get(kind, [])):
                        ordered.append(by_kind[kind][i])
            for r in ordered:
                if len(lst) >= 11:
                    break
                lst.append({"author": r["author"], "date": r["date"],
                            "action": LABEL.get(r["kind"], r["kind"]),
                            "level": r["lo"], "hi": r["hi"], "price": None, "note": r["note"]})
            lst.sort(key=lambda x: x["date"], reverse=True)
        def measured(v, tf):
            return measure.measured_score((v.get(tf) or {}).get("evidence"), mw[{"daily": "D", "weekly": "W", "monthly": "M"}[tf]])
        def slim(row: dict) -> dict:
            if not lite:
                return row
            t = row.get("tally")
            row["tally"] = {k: v for k, v in t.items() if k != "context"} if t else t
            row["trendlines"] = None
            return row
        # `out` is the run's own dict and is NOT what goes back — the response
        # is the literal below. Anything set on `out` after this point is
        # discarded, which is how the first attempt at `ladder_off` vanished.
        return {"asof": out["asof"], "scope": scope, "changed": out["changed"],
                "lite": lite, "problems": problems, "cache": out.get("cache"),
                # Why the ladder card is missing, when it is off, so the page
                # can say so rather than just not drawing it.
                "ladder_off": "" if ladder.ENABLED else ladder.DISABLED_NOTE,
                "prices_asof": prices_asof,
                "market": sentiment.latest(conn),
                "regime": regime.reading(conn, out["asof"]),
                "index": out.get("index"),
                "unchanged": out["unchanged"], "skipped": out["skipped"],
                "counts": out["counts"],
                "verdicts": {s: slim({"daily": v["daily"]["verdict"],
                                 "weekly": v["weekly"]["verdict"],
                                 "monthly": (None if v["monthly"]["insufficient"]
                                             else v["monthly"]["verdict"]),
                                 "monthly_confidence": v["monthly"]["confidence"],
                                 "headline": v["headline"],
                                 "headline_timeframe": v["headline_timeframe"],
                                 "headline_confidence": v["headline_confidence"],
                                 "quality": v["quality"],
                                 "confidence": v["daily"]["confidence"],
                                 "weekly_confidence": v["weekly"]["confidence"],
                                 "weekly_insufficient": v["weekly"]["insufficient"],
                                 # Why a timeframe could not be read, or read
                                 # thin: bars cached, first bar, bars needed.
                                 "monthly_bars": v["monthly"].get("bars"),
                                 "monthly_first": v["monthly"].get("first"),
                                 "monthly_needed": v["monthly"].get("needed"),
                                 "monthly_thin": v["monthly"].get("thin"),
                                 "weekly_bars": v["weekly"].get("bars"),
                                 "weekly_first": v["weekly"].get("first"),
                                 "flip": v["daily"]["flip"],
                                 "flip_note": v["daily"]["flip_note"],
                                 "price": v["daily"]["price"],
                                 "change": v["daily"]["change"],
                                 "near": v["daily"]["near"],
                                 "trendlines": v["daily"]["trendlines"],
                                 "moving_averages": v["daily"]["moving_averages"],
                                 "leg_pos": v["daily"]["leg_pos"],
                                 "cloud": v["daily"]["cloud"],
                                 "sequence": v["daily"]["sequence"],
                                 "conflict": v["conflict"],
                                 "proxy": v.get("proxy"),
                                 "value": held.get(s),
                                 "because": v["daily"]["because"],
                                 # The levels follow the timeframe that made the
                                 # call: a weekly SELL beside "worth adding nearer"
                                 # was the daily hold's levels on the weekly's row.
                                 # ...but a monthly "acting here at the price" is not a
                                 # level: when the headline's watch names no buy-at and
                                 # the daily's does, the daily's is the one to act on.
                                 "watch": _pick_watch(v, (held_book.get(s) or {}).get("book")),
                                 "watch_timeframe": next(
                                     (tf for tf in WATCH_BY_BOOK.get(
                                         (held_book.get(s) or {}).get("book") or "swing",
                                         WATCH_BY_BOOK["swing"])
                                      if _pick_watch(v, (held_book.get(s) or {}).get("book"))
                                      is (v.get(tf) or {}).get("watch")), "daily"),
                                 "tally": v["daily"].get("tally"),
                                 "against": v["daily"].get("against", []),
                                 "weekly_because": v["weekly"]["because"],
                                 "monthly_because": (v["monthly"].get("because") if not v["monthly"]["insufficient"] else None),
                                 "earnings": upcoming_earnings.get(s),
                                 "book": held_book.get(s),
                                 "measured": {"daily": v["daily"].get("measured_score"),
                                              "weekly": v["weekly"].get("measured_score"),
                                              "monthly": v["monthly"].get("measured_score")},
                                 "measured_fifth": {"weekly": v["weekly"].get("measured_fifth")},
                                 # The numbers each confidence word was read from.
                                 # What the people the user follows have said about this
                                 # name lately, with their levels, so the app's level and
                                 # theirs sit side by side.
                                 "outside": outside_by_symbol.get(s, []),
                                 "wash": wash_by_symbol.get(s),
                                 "ladder": ladder_by_symbol.get(s),
                                 "drawdown": drawdown_by_symbol.get(s),
                                 "rebuy": rebuy_by_symbol.get(s),
                                 "sector": sector_of.get(s),
                                 "charts": [{"date": c["email_date"], "subject": c["subject"], "teaser": c["teaser"], "post_id": c["post_id"],
                                             "has_image": c["has_image"], "url": c["post_url"], "action": c["action"]}
                                            for c in charts_by_symbol.get(s, [])[:4]],
                                 "record": {"daily": v["daily"].get("record"),
                                            "weekly": v["weekly"].get("record"),
                                            "monthly": v["monthly"].get("record")},
                                 "confidence_note": v["weekly"].get("confidence_note")})
                             for s, v in out["results"].items()},
                "measured_available": any(mw.values()),
                "sector_strength": sector_rank,
                "buckets": list(journal.BUCKETS), "tags": list(journal.TAGS),
                "books": list(books.BOOKS),
                "scorecard": journal.compare(conn, horizon),
                "calibration": calibration.report(conn, horizon),
                "my_calibration": calibration.report(conn, horizon, source="me"),
                "cross_check": journal.cross_check(conn, horizon),
                "recent": journal.history(conn, limit=60),
                # The user's own, on their own: the automatic outside calls
                # (D122) fill the newest sixty and pushed every 'me' and
                # 'trade' row out of Money → Trades on 2026-09-14.
                "recent_mine": sorted(journal.history(conn, source="me", limit=40)
                                      + journal.history(conn, source="trade", limit=40),
                                      key=lambda r: (r["date"], r["id"]), reverse=True)[:60]}
    finally:
        conn.close()


API_ROUTES = {
    "/api/watchlist":   lambda q: watchlist_payload(q),
    "/api/backtest":    lambda q: backtest_payload(q),
    "/api/diagnose":    lambda q: diagnose_payload(q),
    "/api/methods":     lambda q: methods_payload(q),
    "/api/research":    lambda q: research_payload(q),
    "/api/budget":      lambda q: budget_payload(q),
    "/api/drawings":    lambda q: drawings_payload(q),
    "/api/rotation":    lambda q: rotation_payload(),
    "/api/replay":      lambda q: replay_payload(q),
    "/api/discover":    lambda q: discover_payload(q),
    "/api/paper":       lambda q: paper_payload(q),
    "/api/chart":       lambda q: chart_payload(q),
    "/api/outlook":     lambda q: outlook_payload(q),
    "/api/amazon":      lambda q: amazon_payload(q),
    "/api/rebuy":       lambda q: rebuy_payload(q),
    "/api/substack-charts": lambda q: substack_charts_payload(q),
    "/api/x-charts":    lambda q: x_charts_payload(q),
    "/api/valuetrader": lambda q: valuetrader_payload(q),
    "/api/setup":       lambda q: setup_payload(q),
    "/api/plans":       lambda q: plans_payload(q),
    "/api/performance": lambda q: build_payload(q),
    "/api/health":      lambda q: health_payload(q),
}


def local_hostnames() -> set[str]:
    """Addresses this machine legitimately answers to, resolved once."""
    global _LOCAL_HOSTS
    if _LOCAL_HOSTS is None:
        import socket
        names = {"localhost"}
        try:
            host = socket.gethostname()
            names.add(host.lower())
            names.add(host.split(".")[0].lower())
            for info in socket.getaddrinfo(host, None):
                names.add(info[4][0].lower())
        except OSError:
            pass
        _LOCAL_HOSTS = names
    return _LOCAL_HOSTS


# Tailscale hands every machine an address in this range and a name under the
# tailnet's own .ts.net domain. Both are unforgeable as a Host header from
# outside: a rebinding attacker controls their own domain name, so the Host the
# browser sends is THAT domain — never a .ts.net name they do not own and never
# a bare 100.x literal. So allowing these two shapes opens the server to the
# tailnet without reopening the rebinding hole the guard exists to close.
TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def host_allowed(host: str) -> bool:
    """Whether this server should answer to the name it was reached by.

    The previous version tried to allow Tailscale with
    `names |= {n for n in names if n.endswith(".ts.net")}`, which unions a set
    with a subset of itself and therefore does nothing at all. Reaching the
    server over Tailscale fell back on the hostname happening to resolve to the
    100.x address, which it does not reliably do — so phone access, the thing
    the configurable bind exists for, would have 403'd.
    """
    if not host or host in ALLOWED_HOSTS or host in local_hostnames():
        return True
    if host == "ts.net" or host.endswith(".ts.net"):
        return True
    try:
        return ipaddress.ip_address(host) in TAILSCALE_CGNAT
    except ValueError:
        return False


_LOCAL_HOSTS = None


def host_name(header: str | None) -> str:
    """The name in a Host header, port dropped, lower-cased.

    `split(":")[0]` was how this used to be done, and it turned `[::1]:8737`
    into `[` — so reaching the server over IPv6 loopback was 403'd while the
    literal `::1` sat in ALLOWED_HOSTS doing nothing. Brackets are how an IPv6
    address carries a port, so strip those first and only then a single port.
    """
    h = (header or "").strip().lower()
    if h.startswith("["):
        end = h.find("]")
        return h[1:end] if end > 0 else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


# ---- the write token ------------------------------------------------------
# Sec-Fetch-Site was the only cross-site guard on writes, and browsers only send
# it to origins they consider potentially trustworthy — localhost and https.
# The phone reaches this server at http://100.x.x.x:8737, which is neither, so
# from there a page anywhere on the internet could <img src="/api/watchlist?
# action=remove&symbol=IREN"> or auto-submit a form at /api/upload and the
# server had nothing to refuse it with. A per-process random token, minted at
# start, is handed to the page in a <meta> tag and sent back as a header on
# every /api/ fetch; a foreign page cannot read the tag, so it cannot forge the
# header, and a bare <img> or <form> cannot set headers at all. Reads stay
# token-free so curl and smoke.sh keep working.
#
# The token lives in data/.token (owner-only, gitignored with the rest of
# data/) rather than in memory alone, because the source watcher re-execs this
# process on every saved edit — a token minted per process would leave every
# open tab, the phone's included, unable to write until it was reloaded, with
# nothing on screen to say why. A script that needs to drive a write from
# outside the page can read the same file; nothing in this repository does
# today. INVESTMENT_APP_TOKEN overrides both.
import secrets

TOKEN_FILE = DB_PATH.parent / "data" / ".token"


def _load_token() -> str:
    env = os.environ.get("INVESTMENT_APP_TOKEN")
    if env:
        return env
    try:
        saved = TOKEN_FILE.read_text().strip()
        if re.fullmatch(r"[0-9a-f]{32}", saved):
            return saved
    except OSError:
        pass
    fresh = secrets.token_hex(16)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(fresh + "\n")
    except OSError:
        pass                       # read-only checkout: per-process token, still works
    return fresh


TOKEN = _load_token()

# GET endpoints that write or reach out even without an `action`: the
# mailbox syncs log in to Gmail and insert, replay stores its report, rotation
# commits, and a backtest run inserts a row. Their reads are still cached like
# everything else; this list only decides who may ask for them.
GUARDED_PATHS = {"/api/replay", "/api/rotation", "/api/valuetrader", "/api/amazon"}


def _flag(params: dict, key: str) -> bool:
    return (params.get(key, [""])[0] or "").strip().lower() in ("1", "true", "yes")


def needs_token(path: str, params: dict) -> bool:
    """Whether a GET at this path with these parameters must carry the token.

    Decided from the parsed query, never the raw string — `action=remov%65`
    decodes to "remove" for the handler and must be guarded as such. Anything
    that is not a known read-only action is treated as a write, so a new
    mutating action is protected by default rather than needing to be
    remembered here.
    """
    action = (params.get("action", [""])[0] or "").strip().lower()
    if action and action not in READ_ONLY_ACTIONS:
        return True
    if path in GUARDED_PATHS:
        return True
    if path == "/api/backtest":
        return not (_flag(params, "last") or _flag(params, "catalogue"))
    if path == "/api/research":
        return (params.get("kind", [""])[0] or "").strip().lower() == "macro"
    return False


def token_ok(headers) -> bool:
    given = headers.get("X-App-Token") or ""
    return secrets.compare_digest(given.encode(), TOKEN.encode())


def origin_ok(headers) -> bool:
    """A request that names its Origin must name the host it was reached by.

    Browsers put Origin on every POST and on any fetch that crosses sites; a
    fetch from the app's own page carries this server's own address. Not every
    forged request has an Origin (an <img> sends none), so this is not the
    guard — the token is — but it is a cheap second refusal that also covers a
    misconfigured proxy handing the page out under one name and the API under
    another. Absent means a non-browser client, which is allowed.
    """
    origin = (headers.get("Origin") or "").strip().lower()
    if not origin:
        return True
    # Tailscale Serve fronts this server at http://erics-macbook-pro/ and may
    # hand the proxied request its own Host; the name the browser used then
    # arrives as X-Forwarded-Host, and that is the one the Origin will carry.
    reached = {(headers.get(h) or "").strip().lower() for h in ("Host", "X-Forwarded-Host")}
    return urllib.parse.urlsplit(origin).netloc in reached - {""}


def site_ok(headers) -> bool:
    """Sec-Fetch-Site, where a browser sends it, names a cross-site request
    outright. Kept beside the token because it costs nothing and is a second,
    independent refusal on the browsers that do send it."""
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    return not site or site in ("same-origin", "none")


# Symbols travel raw into a feed URL (prices.py builds the Alpaca path from
# them), so `symbol=X/../../v2/account` rewrote the request path while carrying
# the key headers. Checked once at the boundary for every route rather than in
# each builder: a ticker is letters, digits, a class dot (BRK.B) or a hyphen
# (LINK-USD); the ledger's longest real one is a 13-character crypto pair.
SYMBOL_RE = re.compile(r"[A-Z0-9.\-]{1,16}")
# The three the Overview offers. The payload builder splits the list and
# resolves each name against a FRED table, so an unknown name is harmless, but
# an allowlist is cheaper to reason about than "harmless".
BENCHMARKS_ALLOWED = {"SPY", "QQQ", "DJIA"}


def bad_symbol_params(params: dict) -> str | None:
    """The first offending symbol-shaped parameter, or None if all are clean."""
    for key in ("symbol", "compare"):
        for raw in params.get(key, []):
            val = (raw or "").strip().upper()
            if val and not SYMBOL_RE.fullmatch(val):
                return f"{key}={raw!r} is not a symbol"
    for raw in params.get("benchmarks", []):
        for name in (raw or "").split(","):
            name = name.strip().upper()
            if name and name not in BENCHMARKS_ALLOWED:
                return f"benchmark {name!r} is not offered"
    return None


# Loaded once and handed out with the token stamped in, so the page can read
# it back. Marker chosen so a missing </head> is a loud failure at start-up
# rather than a page that silently cannot write.
def dashboard_html() -> bytes:
    raw = (HERE / "dashboard.html").read_bytes()
    tag = f'<meta name="app-token" content="{TOKEN}">\n</head>'.encode()
    if b"</head>" not in raw:
        raise OSError("dashboard.html has no </head> to carry the token")
    return raw.replace(b"</head>", tag, 1)


# What the page may load, and from where. Scripts and styles are this file's
# own inline blocks and the two vendored files; images are the saved charts
# from this server plus a followed author's CDN; the page talks to nothing but
# this server. A pasted `javascript:` URL in a post therefore has nowhere to go
# even if it reaches an href.
CSP = ("default-src 'self'; img-src 'self' https: data:; "
       "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'")


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 so a browser reuses one connection for the dozens of fetches a
    # tab makes instead of opening one per request. The cost is that EVERY
    # response must carry a Content-Length, or the client waits for a body that
    # never ends — which is why all sends below go through _send/_json.
    protocol_version = "HTTP/1.1"
    # A connection that stops talking mid-request no longer holds its thread
    # forever.
    timeout = 30
    # No Python version in the Server header; nobody reading it is a friend.
    server_version = "investment-app"
    sys_version = ""

    def version_string(self):            # the base joins the two with a space
        return self.server_version

    def log_message(self, *args):        # quiet; this is a personal tool
        pass

    def do_POST(self):
        """The first-run screen's writes: a dropped export file, the price key,
        the tax profile, a price refresh. Token, Origin and Host guarded."""
        from . import setup_flow
        parsed = urllib.parse.urlparse(self.path)
        host = host_name(self.headers.get("Host"))
        if (not host_allowed(host) or not origin_ok(self.headers)
                or not site_ok(self.headers) or not token_ok(self.headers)):
            # The body is unread; with keep-alive it would be parsed as the
            # next request. Dropping the connection is the only safe answer.
            self.close_connection = True
            self._json({"error": "not allowed"}, 403); return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0:
                raise ValueError
        except ValueError:
            self.close_connection = True
            self._json({"error": "bad Content-Length"}, 400); return
        if length > 60_000_000:
            self.close_connection = True
            self._json({"error": "file too large (60 MB limit)"}, 413); return
        body = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type") or ""
        try:
            if parsed.path == "/api/upload":
                fields, files = setup_flow.parse_multipart(ctype, body)
                kind = fields.get("kind", "")
                if not files:
                    self._json({"error": "no file received"}, 400); return
                conn = connect()
                try:
                    out = [setup_flow.import_upload(conn, kind, fn, data) for _n, fn, data in files]
                finally:
                    conn.close()
                self._json({"imported": out}); return
            if parsed.path == "/api/setup":
                data = json.loads(body.decode("utf-8") or "{}")
                act = data.get("action")
                if act == "alpaca":
                    setup_flow.write_alpaca(data.get("key"), data.get("secret"))
                    self._json({"ok": True}); return
                if act == "profile":
                    self._json({"ok": True, **setup_flow.write_profile(data.get("filing_status"), data.get("age"))}); return
                if act in ("prices", "sample", "unsample"):
                    conn = connect()
                    try:
                        if act == "prices":
                            self._json({"ok": True, **setup_flow.refresh_prices(conn)})
                        else:
                            # A made-up year so a fresh copy shows the whole
                            # app before any export exists (sample.py). Into
                            # an empty ledger only; out again on request.
                            from . import sample
                            r = sample.load(conn) if act == "sample" else sample.clear(conn)
                            if not r.get("error"):
                                if act == "sample":
                                    setup_flow.refresh_prices(conn)
                                bump_epoch(conn)
                            self._json(r, 400 if r.get("error") else 200)
                    finally:
                        conn.close()
                    return
                self._json({"error": f"unknown action {act!r}"}, 400); return
            self._json({"error": "not found"}, 404)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:                               # noqa: BLE001
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None,
              etag_of: Path | None = None, salt: str = ""):
        """Every response leaves through here so none can miss Content-Length.

        Also where the body is gzipped when the client allows it, where a
        file-backed body answers 304 to a matching If-None-Match, and where
        the one log line per request is written — see encode_body and
        log_request.
        """
        if status == 200:
            body, extra, status = encode_body(self, body, content_type, etag_of, salt)
        else:
            extra = [("Content-Type", content_type)]
        self.send_response(status)
        for k, v in extra:
            self.send_header(k, v)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)
        t0 = getattr(self, "_t0", None)
        log_request(self.path.split("?", 1)[0],
                    (time.perf_counter() - t0) * 1000 if t0 else 0.0,
                    len(body), getattr(_LAST, "hit", False), status)

    def _json(self, payload: dict, status: int = 200, headers: dict | None = None):
        self._send(status, json.dumps(payload, default=str).encode(), "application/json", headers)

    def do_GET(self):
        self._t0 = time.perf_counter()
        _LAST.hit = False
        parsed = urllib.parse.urlparse(self.path)
        # Host validation defeats DNS rebinding, which loopback binding does
        # nothing about: an attacker domain with a short TTL rebinds to
        # 127.0.0.1, the browser then treats the attacker's page as same-origin,
        # and /api/performance hands over every account, balance and holding.
        # When the server is deliberately opened up, the names it is reached by
        # are legitimate — an allowlist of loopback only would 403 the phone
        # access HOW_TO_RUN.md describes in the same breath. Rebinding is what
        # this blocks, and a rebinding host is neither loopback nor this
        # machine's own address.
        host = host_name(self.headers.get("Host"))
        if not host_allowed(host):
            self._json({"error": f"Host {host!r} not allowed. Reach this server as "
                                 f"localhost, 127.0.0.1, or its Tailscale "
                                 f"name or address."}, 403)
            return
        if not origin_ok(self.headers):
            self._json({"error": "Origin does not match the host reached."}, 403)
            return

        # gzip, ETag/304 and the request log all live in _send, so every
        # branch below gets them without knowing.
        handler = API_ROUTES.get(parsed.path)
        if handler:
            # Writes are refused without the page's token. Every mutation here
            # is a GET, so a plain <img src="...action=remove&symbol=NVDA"> on
            # any page the user visits would silently delete rows — and the
            # watchlist is the one dataset that cannot be rebuilt from data/.
            # Sec-Fetch-Site used to be the whole defence; see TOKEN for why it
            # is not sent on the phone path and why the token replaces it.
            params = urllib.parse.parse_qs(parsed.query)
            if needs_token(parsed.path, params) and not (
                    token_ok(self.headers) and site_ok(self.headers)):
                self._json({"error": "Cross-site writes are refused."}, 403)
                return
            problem = bad_symbol_params(params)
            if problem:
                self._json({"error": problem}, 400)
                return
            action = (params.get("action", [""])[0] or "").strip().lower()
            mutating = bool(action) and action not in READ_ONLY_ACTIONS
            # One dispatch, not eight copies of the same try/except. Beyond the
            # seventy lines, the duplication meant any cross-cutting change — a
            # security header, an Origin check, request logging — had to be made
            # eight times, and the eighth would be the one that got missed.
            try:
                # Only reads are cached. A mutation must run every time, and its
                # write moves the database mtime, which drops every cached read.
                payload = (handler(params) if mutating
                           else cached_payload(parsed.path, params,
                                               lambda: handler(params)))
                body = json.dumps(payload, default=str).encode()
                status = 200
            except Exception as exc:                       # noqa: BLE001
                body = json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode()
                status = 500
            # Applied in ONE place now, which is the point of the table.
            self._send(status, body, "application/json",
                       {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
        elif parsed.path.startswith("/static/"):
            # Vendored, not CDN-loaded: the chart library is Apache-2.0 and
            # keeping a copy means the dashboard works with no internet at all,
            # which is the whole premise of a local-first app. cdnjs does not
            # host this package in any case.
            # Containment is checked on the RESOLVED path, not on the string.
            # The previous guard rejected ".." and trusted the rest, but pathlib
            # discards everything to the left of an absolute segment — so
            # HERE/"static"/"/etc/passwd" simply IS /etc/passwd, contains no
            # "..", and is_file() is true. That served arbitrary readable files
            # to anyone who could reach the port.
            root = (HERE / "static").resolve()
            name = parsed.path.removeprefix("/static/")
            try:
                path = (root / name).resolve()
            except OSError:
                self._send(404, b"", "text/plain"); return
            if not path.is_relative_to(root) or not path.is_file():
                self._send(404, b"", "text/plain"); return
            # Only the vendored library is cached hard. It is pinned at a
            # version and never edited; this project's own static files change,
            # and a day-long cache on those means a fix that is deployed but
            # invisible — indistinguishable from a fix that did not work.
            # Both carry an ETag, so "no-cache" costs a conditional request
            # and a 304 rather than the 350 KB library again.
            self._send(200, path.read_bytes(),
                       "application/javascript" if name.endswith(".js") else "text/plain",
                       {"Cache-Control": "max-age=86400" if name.startswith("lightweight-charts")
                        else "no-cache"}, etag_of=path)
        elif parsed.path == "/chart-image":
            # A followed author's chart, saved from their email, served back
            # from disk by post id. Local files only; nothing is fetched here.
            from . import valuetrader
            pid = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
            body = None
            if re.fullmatch(r"\d{1,12}", pid or ""):
                conn = connect()
                try:
                    body = valuetrader.image_bytes(conn, pid)
                finally:
                    conn.close()
            if not body:
                self._send(404, b"", "text/plain"); return
            self._send(200, body, "image/png", {"Cache-Control": "max-age=86400"})
        elif parsed.path == "/chart-x":
            # A chart a followed account posted on X, saved by the nightly
            # pull (xcharts.py); served from disk by tweet id and index.
            from . import xcharts
            q = urllib.parse.parse_qs(parsed.query)
            conn = connect()
            try:
                path = xcharts.image_path(conn, (q.get("id") or [""])[0], int((q.get("n") or ["0"])[0] or 0))
            finally:
                conn.close()
            if not path:
                self._send(404, b"", "text/plain"); return
            self._send(200, path.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=86400"})
        elif parsed.path in ("/", "/index.html"):
            try:
                body = dashboard_html()
            except OSError as exc:
                self._send(500, f"dashboard.html unreadable: {exc}".encode(), "text/plain")
                return
            # The page changes constantly; a cached copy silently hides every
            # update and looks exactly like a broken deploy. "no-cache" makes
            # the browser ask every time; the ETag (file mtime and size, plus
            # the token baked into the page) lets the answer be a 304 when
            # nothing changed, and a fresh page the moment the file does.
            self._send(200, body, "text/html; charset=utf-8",
                       {"Cache-Control": "no-cache, must-revalidate",
                        "Content-Security-Policy": CSP,
                        "X-Content-Type-Options": "nosniff",
                        "Referrer-Policy": "no-referrer"},
                       etag_of=HERE / "dashboard.html", salt=TOKEN)
        else:
            self._send(404, b"", "text/plain")


def _watch_sources(interval: float = 1.0) -> None:
    """Restart the server when its own source changes.

    Python does not reload code, so a server started before a feature exists
    keeps serving the version it booted with. That fails in a specifically
    confusing way: dashboard.html is sent no-cache and updates immediately, so a
    NEW tab appears in the browser while the endpoint behind it still 404s, and
    the feature looks broken rather than stale. That is exactly how the budget
    tab first appeared empty.

    Watching mtimes and re-exec'ing is a few lines and removes the whole class
    of problem, rather than requiring anyone to remember which changes need a
    restart.
    """
    import os
    import sys
    import threading
    import time

    root = HERE
    def stamp():
        newest = 0.0
        for path in list(root.glob("*.py")) + list(root.glob("static/*.js")):
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                pass
        return newest

    def loop():
        start = stamp()
        while True:
            time.sleep(interval)
            try:
                now = stamp()
            except Exception:                             # noqa: BLE001
                continue
            if now > start:
                print("\n  source changed — restarting\n", flush=True)
                # execv rather than exiting: the terminal keeps the same process
                # and the same port, so nothing has to be restarted by hand and
                # a browser reload is enough.
                os.execv(sys.executable, [sys.executable, "-m", "app.web"])

    threading.Thread(target=loop, daemon=True).start()


def main():
    import os
    import socket

    # Loopback unless explicitly opened. Binding every interface put a server
    # with no authentication — one that reads the ledger and writes the
    # watchlist — on whatever coffee-shop Wi-Fi the laptop joined. Reaching it
    # from a phone is still supported, but it is now a decision rather than the
    # default: INVESTMENT_APP_HOST=0.0.0.0, ideally only on a Tailscale address.
    # A COMMA-SEPARATED LIST, so the server can listen on loopback and on the
    # Tailscale address while listening on nothing else. 0.0.0.0 was the only
    # previous way to reach a phone, and it puts a server with no
    # authentication — one that reads the ledger and writes the watchlist — on
    # whatever coffee-shop Wi-Fi the laptop joins. Naming the two addresses
    # instead keeps localhost working for daily use and the tailnet working
    # from a phone, while the café network never has a socket to talk to.
    hosts = [h.strip() for h in
             (os.environ.get("INVESTMENT_APP_HOST")
              or _CFG.get("host") or "127.0.0.1").split(",") if h.strip()]
    # Off with INVESTMENT_APP_RELOAD=0 for a long-running instance where an
    # editor save should not interrupt anything.
    if os.environ.get("INVESTMENT_APP_RELOAD", "1") != "0":
        _watch_sources()

    servers, pending = [], []
    for h in hosts:
        try:
            servers.append((h, ThreadingHTTPServer((h, PORT), Handler)))
        except OSError as exc:
            # Almost always the Tailscale address at login: launchd starts this
            # before the tunnel is up, so the address does not exist yet. Failing
            # the whole process would take loopback down with it and, if
            # Tailscale never came up, loop forever — so serve what we can now
            # and keep trying for the rest.
            pending.append(h)
            print(f"  not yet bindable: {h}:{PORT} ({exc.strerror}) — will keep trying")

    if not servers and not pending:
        print(f"  no addresses to bind (INVESTMENT_APP_HOST={hosts})")
        return 1
    if not servers:
        # Nothing is listening at all; let launchd restart rather than sit idle.
        print(f"  could not bind any of {pending}")
        return 1

    def _retry_pending():
        while pending:
            time.sleep(15)
            for h in list(pending):
                try:
                    late = ThreadingHTTPServer((h, PORT), Handler)
                except OSError:
                    continue
                pending.remove(h)
                servers.append((h, late))
                print(f"  now also listening on http://{h}:{PORT}")
                threading.Thread(target=late.serve_forever, daemon=True).start()

    if pending:
        threading.Thread(target=_retry_pending, daemon=True).start()

    print(f"\n  Investment App dashboard")
    for h, _ in servers:
        where = "this Mac" if h in ("127.0.0.1", "localhost") else "tailnet"
        print(f"    {where:<12}  http://{h}:{PORT}")
    if all(h in ("127.0.0.1", "localhost") for h, _ in servers) and not pending:
        print(f"    this Mac only — add a Tailscale address to "
              f"INVESTMENT_APP_HOST to reach it from a phone")
    print(f"\n  Ctrl-C to stop.\n")

    # Each extra listener runs in its own thread; the first stays on the main
    # thread so Ctrl-C still lands where a person expects it.
    for _h, extra in servers[1:]:
        threading.Thread(target=extra.serve_forever, daemon=True).start()
    try:
        servers[0][1].serve_forever()
    except KeyboardInterrupt:
        print("  stopped.")
    return 0


if __name__ == "__main__":
    main()
