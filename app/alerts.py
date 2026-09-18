"""Alerts: what changed, what is at a level, what is about to report — sent to you.

    python3 -m app.alerts nightly      # after the nightly scoring; update.sh runs this
    python3 -m app.alerts poll         # during market hours, every 15 minutes (launchd)
    python3 -m app.alerts test         # send one test message to every channel
    python3 -m app.alerts show         # the last week of alerts

## Why

Every commercial tool the September review looked at can reach you when
something happens; this app could only be looked at. A verdict that flips
at 10 a.m. on a Tuesday, a position that closes through its stop, a report
tomorrow morning — none of it was worth anything if the page was not open.

## What fires

Nightly, from the same scoring run the Outlook tab shows:

  * a verdict that CHANGED since the last recorded call
  * price THROUGH the stop or the trim level the call named
  * a DCA tier that moved (the weekly Williams %R ladder)
  * an earnings report inside five days, once per report

Intraday, from the last 15-minute bar of every holding, only while the
market is open: price through the stop or the trim level of the most recent
nightly call, or below the level that flips its call. Once per level per day.

## What deliberately does NOT fire

**Price being NEAR a level.** Approaching a number is an event, not a reason to
do anything: the level has not been reached, nothing is decided, and there is
no action attached. It used to fire at 1.5% on the engine's buy-at, trim and
stop, on the user's own drawn levels, and on the buy-at intraday — together
**103 of the last 138 alerts**, which is most of what arrived at the open. The
levels are on the Outlook and drawn on the chart for when the user looks.

Reaching the buy-at intraday is gone for a second reason as well: the buy level
sits close to price by construction, so it fired on most names on most days,
and buying is a decision made at the desk rather than something to be
interrupted for.

## Where it goes

Everything is stored in the `alerts` table and shown on the Overview whether
or not it was sent anywhere. Sending is by channel, from config.json:

    "alerts": {"ntfy_topic": "some-long-random-name", "macos": true,
               "min_level": "warn"}

ntfy.sh is a free, open-source push service: install the ntfy app on the
phone, subscribe to a topic name you make up, and any HTTP POST to that
topic arrives as a notification. There is no account. The topic name IS the
secret — anyone who knows it can read the alerts — so make it long and keep
it out of anything shared. The macOS channel is a local notification on this
Mac, on by default, useful when the laptop is open and nothing else.

Levels: `info` (a first reading), `warn` (earnings, a tier change), `act` (a
verdict change, a level reached). `min_level` is the least serious level
that gets SENT; everything is stored regardless.

## How few get pushed

At most `max_push` (default 4) notifications leave the machine per run, ranked
by severity and then by the dollar value of the position — a level touched on a
$190,000 holding outranks the same event on a $2,000 one. Everything above the
cap arrives as ONE digest naming the symbols, and everything is on the Overview
either way.

This exists because it was not there: 17 to 26 alerts fired daily through early
September and every one was sent. "When market opens i get smacked with like 20
notifications and i dont have time to read them all" — twenty individually
well-worded alerts are functionally zero alerts, and the wording never reached
the reader at all.

## Dedup

Every alert carries a key — kind, symbol, level, date — and the store is
unique on it. The nightly job re-run twice sends nothing twice; the poll
that finds price still below the stop at 10:15 and 10:30 sends it once.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import watchlist, config, earnings, prices, books
from .ledger import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    day        TEXT NOT NULL,
    kind       TEXT NOT NULL,         -- verdict | level | tier | earnings | intraday
    symbol     TEXT,
    level      TEXT NOT NULL,         -- info | warn | act
    message    TEXT NOT NULL,
    key        TEXT NOT NULL UNIQUE,
    sent_at    TEXT,
    channel    TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_day ON alerts (day);
-- The levels each nightly call named, so the intraday poll has something to
-- compare a live price against without re-running the engine.
CREATE TABLE IF NOT EXISTS watch_levels (
    day     TEXT NOT NULL, symbol TEXT NOT NULL,
    verdict TEXT, price REAL, buy_at REAL, trim_at REAL, stop_at REAL, flip REAL,
    PRIMARY KEY (day, symbol)
);
"""

NEAR_PCT = 0.015
EARNINGS_WINDOW = 5
LEVELS = {"info": 0, "warn": 1, "act": 2}
NY = ZoneInfo("America/New_York")


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(alerts)")}
    if "detail" not in cols:
        conn.execute("ALTER TABLE alerts ADD COLUMN detail TEXT")


def settings() -> dict:
    cfg = (config.load().get("alerts") or {}) if hasattr(config, "load") else {}
    return {"ntfy_topic": (cfg.get("ntfy_topic") or "").strip() or None,
            "macos": bool(cfg.get("macos", True)),
            "min_level": cfg.get("min_level", "warn"),
            "max_push": int(cfg.get("max_push", MAX_PUSH))}


def market_open(now: datetime | None = None) -> bool:
    """Regular session, New York time. Holidays are not known here; a poll on
    a holiday fetches nothing new and stays quiet, which is the right outcome."""
    now = (now or datetime.now(NY)).astimezone(NY)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def _alert(kind, symbol, level, message, key, day, detail: str | None = None):
    return {"kind": kind, "symbol": symbol, "level": level, "message": message,
            "key": key, "day": day, "detail": detail}


# ----------------------------------------------------------- your levels ----

def user_levels(conn, symbol: str | None = None) -> dict[str, list[float]]:
    """Horizontal levels drawn by hand on the Chart tab (drawings of kind
    'level'), by symbol. These are the user's own shelves — the levels they
    trade off — and the record supports levels over every other drawing, so
    they get their own alerts."""
    q = "SELECT symbol, points FROM drawings WHERE kind='level'"
    rows = conn.execute(q + (" AND symbol=?" if symbol else ""), (symbol,) if symbol else ()).fetchall()
    out: dict[str, list[float]] = {}
    for sym, pts in rows:
        try:
            lvl = float(json.loads(pts)[0][1])
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            continue
        out.setdefault(sym, []).append(lvl)
    return out


def level_detail(sym: str, lvl: float, price: float, call: dict | None, crossed: bool = False) -> str:
    """What reaching a level means, in the words the phone shows when the
    alert is opened: which way the level now faces, what the app's own call
    on the name is and why, and the next levels either side. The user asked
    for exactly this — "ok it's above my level, but what does that mean, is
    it a buy, sell or trim?"."""
    parts = []
    if crossed and price > lvl or price > lvl * (1 + NEAR_PCT):
        parts.append(f"Above {lvl:,.2f}: the level now acts as support; a close back below it undoes that.")
    elif crossed and price < lvl or price < lvl * (1 - NEAR_PCT):
        parts.append(f"Below {lvl:,.2f}: the level now acts as resistance; a close back above it undoes that.")
    else:
        parts.append(f"At {lvl:,.2f}: the level is being tested — a close clearly either side decides it.")
    if call:
        # The plan, in the three numbers the reader asked for, before anything
        # else. This used to open "App call: daily HOLD (low), weekly HOLD
        # (medium), headline HOLD on the weekly" — three verdicts and no plan,
        # which is what "the day week month thing doesn't really click" was
        # about. The holding period from the book replaces the timeframe grid,
        # and each level is named for what you would DO at it rather than for
        # which side of price it sits on ("next above" is a direction, not an
        # instruction).
        if call.get("book"):
            parts.append(f"Held as a {call['book']} ({call['horizon']}).")
        plan = []
        if call.get("buy_now") and call.get("buy_at"):
            plan.append(f"BUY AT {call['buy_at']:,.2f} — price is at it now")
        elif call.get("buy_at"):
            plan.append(f"BUY AT {call['buy_at']:,.2f}")
        if call.get("sell_into"):
            # On a trade-around name the core is never sold — what goes into
            # strength is the slice traded against it. Saying "SELL INTO" flat
            # on IREN would read as an instruction to sell the position the
            # whole book exists to keep.
            plan.append((f"SELL THE SLICE INTO {call['sell_into']:,.2f}"
                         if call.get("trade_around") else
                         f"SELL INTO {call['sell_into']:,.2f}"))
        if call.get("stop_at"):
            plan.append(f"WRONG BELOW {call['stop_at']:,.2f}")
        if plan:
            parts.append("Plan: " + " · ".join(plan) + ".")
        # What each level is being taken FOR. A level says when; on its own it
        # does not say what the trade is worth, so it cannot be weighed against
        # another name or against doing nothing. One sentence per level, and
        # both measured from the LEVEL rather than from today's price.
        if call.get("buy_at") and call.get("buy_target"):
            s = (f"Buying {call['buy_at']:,.2f} targets {call['buy_target']:,.2f} "
                 f"({call['buy_target_pct']:+.0f}%)")
            if call.get("buy_rr"):
                s += (f" against {call['stop_at']:,.2f} "
                      f"({call['buy_risk_pct']:+.0f}%) — {call['buy_rr']:.1f} to 1")
            parts.append(s + ".")
        if call.get("sell_into") and call.get("sell_target"):
            parts.append(f"Selling into {call['sell_into']:,.2f} targets a pullback "
                         f"to {call['sell_target']:,.2f} "
                         f"({call['sell_target_pct']:+.0f}%).")
        # The gap between the two levels IS the instruction most days, and
        # saying it outright stops a reading with no action in it from looking
        # like one that has an action the reader has failed to spot.
        if call.get("stop_at") and call.get("sell_into"):
            parts.append(f"Nothing to do between {call['stop_at']:,.2f} "
                         f"and {call['sell_into']:,.2f}.")
        # An add level UNDER the invalidation level is worth saying out loud:
        # by the time price prints it, the reason to own the name has gone.
        if (call.get("buy_at") and call.get("stop_at")
                and call["buy_at"] < call["stop_at"]):
            parts.append(f"Note the add level sits below the invalidation level — "
                         f"if it reaches {call['buy_at']:,.2f}, the reason to own "
                         f"it has already broken.")
        # What is missing is said out loud rather than left blank, because a
        # blank reads as an oversight and this is a finding: there is no level
        # on that side worth acting on.
        missing = [w for w, k in (("buy level", "buy_at"),
                                  ("sell level", "sell_into"),
                                  ("invalidation level", "stop_at"))
                   if not call.get(k)]
        if missing:
            parts.append("No " + ", no ".join(missing)
                         + " — nothing tested enough on that side to trade.")
        if call.get("because"):
            parts.append(f"Why: {call['because']}")
    return " ".join(parts)


def calls_from_results(results: dict, book_lookup: dict | None = None) -> dict[str, dict]:
    """The per-symbol call summary level alerts carry, from outlook.run's results.

    Carries the three levels the reading resolves to and the book that says how
    long the position is meant to be held. The per-timeframe verdicts are still
    here for callers that want them; they are no longer what an alert leads on.
    """
    from . import books as _books
    out = {}
    for sym, both in (results or {}).items():
        d, w = both.get("daily") or {}, both.get("weekly") or {}
        watch = d.get("watch") or {}
        names = {"D": "daily", "W": "weekly", "M": "monthly"}
        book = ((book_lookup or {}).get(sym) or {}).get("book") or "swing"
        out[sym] = {"daily": d.get("verdict"), "daily_confidence": d.get("confidence"),
                    "weekly": w.get("verdict"), "weekly_confidence": w.get("confidence"),
                    "headline": both.get("headline"), "headline_tf": names.get(both.get("headline_timeframe")),
                    "because": (d.get("because") or [None])[0],
                    "book": book, "horizon": _books.horizon(book),
                    "trade_around": bool(((book_lookup or {}).get(sym) or {}).get("trade_around")),
                    "buy_at": watch.get("buy_at"), "buy_now": watch.get("buy_now"),
                    "sell_into": watch.get("trim_at"),
                    "buy_target": watch.get("buy_target"),
                    "buy_target_pct": watch.get("buy_target_pct"),
                    "buy_risk_pct": watch.get("buy_risk_pct"),
                    "buy_rr": watch.get("buy_rr"),
                    "sell_target": watch.get("sell_target"),
                    "sell_target_pct": watch.get("sell_target_pct"),
                    "next_up": watch.get("trim_at"), "next_down": watch.get("buy_at"),
                    "stop_at": watch.get("stop_at")}
    return out


def from_levels(levels: dict[str, list[float]], closes: dict[str, tuple],
                asof: str, intraday: bool = False, calls: dict | None = None) -> list[dict]:
    """Alerts where price has reached or closed through a hand-drawn level.

    `closes` maps symbol to (price now, previous close). Pure. A level is
    'reached' within NEAR_PCT, and 'through' when the previous close and the
    price now sit on opposite sides of it — a crossing, whichever way.
    `calls` (see calls_from_results) fills the detail the phone shows on
    opening the alert: the app's call on the name and the next levels."""
    out = []
    kind = "intraday" if intraday else "level"
    verb = "is trading" if intraday else "closed"
    calls = calls or {}
    for sym, lvls in levels.items():
        price, prev = closes.get(sym) or (None, None)
        if not price:
            continue
        for lvl in sorted(set(lvls)):
            if not lvl:
                continue
            key = f"{'intraday:' if intraday else ''}mylevel:{sym}:{lvl:.4f}:{asof}"
            crossed = bool(prev and (prev - lvl) * (price - lvl) < 0)
            detail = level_detail(sym, lvl, price, calls.get(sym), crossed)
            if crossed:
                side = "ABOVE" if price > lvl else "BELOW"
                out.append(_alert(kind, sym, "act",
                                  f"{sym} {verb} at {price:,.2f}, {side} your {lvl:,.2f} level "
                                  f"(previous close {prev:,.2f})", key, asof, detail))
            # Approaching one of the user's own levels is not an alert either.
            # Crossing it is. The same reasoning as the engine's levels above:
            # near is not reached, and a notification with no action in it
            # spends attention it cannot repay. Their levels are drawn on the
            # chart and they know where they are.
    return out


def _prev_close(conn, sym: str, today: str) -> float | None:
    """The last daily close strictly before `today` (the newest bar may already
    be today's, upserted during the session)."""
    bars = [b for b in prices.load_bars(conn, sym, "2020-01-01", today) if b["time"] < today]
    return bars[-1]["close"] if bars else None


STALE_DAYS = 3        # a newest bar older than this is not "price now" — no level alert on it


def _closes(conn, symbols, asof: str) -> dict[str, tuple]:
    """(close, previous close) per symbol, only where the newest bar is recent.
    An OTC name on the Yahoo fallback can sit days behind (SIVEF stopped at
    2026-08-28 while the market traded on), and a level alert on a stale
    close is a false alarm on the phone."""
    out = {}
    cutoff = (date.fromisoformat(asof) - timedelta(days=STALE_DAYS)).isoformat()
    for sym in symbols:
        bars = prices.load_bars(conn, sym, "2020-01-01", asof)
        if bars and bars[-1]["time"] >= cutoff:
            out[sym] = (bars[-1]["close"], bars[-2]["close"] if len(bars) > 1 else None)
    return out


# --------------------------------------------------------------- nightly ----

def from_outlook(run: dict, earnings_map: dict, asof: str) -> list[dict]:
    """Alerts implied by one scoring run. Pure: no database, no network."""
    out = []
    for e in run.get("changed", []):
        tf = {"D": "daily", "W": "weekly", "M": "monthly"}.get(e.get("timeframe"), "")
        sym, v = e["symbol"], (e.get("verdict") or "").upper()
        why = (e.get("because") or [""])[0]
        if e.get("kind") == "changed":
            out.append(_alert(
                "verdict", sym, "act",
                f"{sym} {tf}: {(e.get('from') or '?').upper()} → {v}"
                + (f" at {e['price']:,.2f}" if e.get("price") else "")
                + (f". {why}" if why else ""),
                f"verdict:{sym}:{e.get('timeframe')}:{asof}", asof))
        elif e.get("kind") == "new":
            out.append(_alert(
                "verdict", sym, "info",
                f"{sym} {tf}: first reading is {v}"
                + (f" at {e['price']:,.2f}" if e.get("price") else ""),
                f"first:{sym}:{e.get('timeframe')}:{asof}", asof))

    for sym, both in (run.get("results") or {}).items():
        d = both.get("daily") or {}
        w = d.get("watch") or {}
        price = w.get("price") or d.get("price")
        if not price:
            continue
        for label, key in (("buy-at", "buy_at"), ("trim", "trim_at"), ("stop", "stop_at")):
            lvl = w.get(key)
            if not lvl:
                continue
            # The engine can name the same price as the buy-at and the stop —
            # the nearest support under price is both — and one price near
            # one level is one alert, not two.
            if key == "stop_at" and w.get("buy_at") == lvl and not price < lvl:
                continue
            if key == "stop_at" and price < lvl:
                out.append(_alert("level", sym, "act",
                                  f"{sym} closed at {price:,.2f}, BELOW its stop level {lvl:,.2f}",
                                  f"level:{sym}:stop-through:{asof}", asof))
            elif key == "trim_at" and price > lvl:
                out.append(_alert("level", sym, "act",
                                  f"{sym} closed at {price:,.2f}, THROUGH its trim level {lvl:,.2f}",
                                  f"level:{sym}:trim-through:{asof}", asof))
            # "Price is within 1.5% of a level" is deliberately NOT an alert.
            #
            # It was, and it was 103 of the last 138 — the bulk of what arrived
            # at the open. Being near a number is an event, not a reason to do
            # anything: the level has not been reached, nothing has been
            # decided, and there is no action attached. The levels are on the
            # Outlook and the chart for when the user looks. Only a level
            # actually GIVEN UP interrupts them.

        e = earnings_map.get(sym)
        if e and e.get("days") is not None and 0 <= e["days"] <= EARNINGS_WINDOW:
            when = ("today" if e["days"] == 0 else "tomorrow" if e["days"] == 1
                    else f"in {e['days']} days")
            timing = f", {e['timing']}" if e.get("timing") and e["timing"] != "unknown" else ""
            out.append(_alert("earnings", sym, "warn",
                              f"{sym} reports earnings {when} ({e['date']}{timing})",
                              f"earnings:{sym}:{e['date']}", asof))
    return out


def tier_changes(conn, symbols: list[str], asof: str) -> list[dict]:
    """A DCA tier that moved since a week ago, per holding."""
    from . import frameworks
    out = []
    week_ago = (date.fromisoformat(asof) - timedelta(days=7)).isoformat()
    for sym in symbols:
        now = frameworks.dca_multiplier(conn, sym, asof)
        then = frameworks.dca_multiplier(conn, sym, week_ago)
        if now.get("insufficient") or then.get("insufficient"):
            continue
        if now["multiplier"] != then["multiplier"]:
            out.append(_alert("tier", sym, "warn",
                              f"{sym} DCA tier {then['multiplier']}x → {now['multiplier']}x "
                              f"({now['tier']}; Williams %R {now['williams_r']:.0f} weekly)",
                              f"tier:{sym}:{now['multiplier']}:{asof[:7]}", asof))
    return out


# ------------------------------------------------------ statement reminders ----

# How old an account's newest transaction may be before the export is due. A
# card statement closes monthly and the bank's export is a month at a time,
# so five weeks is one cycle plus the slack of a late pull; a pay stub is
# every two weeks, so six weeks is three missed.
STATEMENT_DUE_DAYS = 35
STUB_DUE_DAYS = 45


def statement_reminders(conn, asof: str) -> list[dict]:
    """What has to be pulled by hand, once it is overdue.

    X, the Substack and YouTube pull themselves overnight; cards, the bank,
    Fidelity and the pay stubs have no API and no cookie, so a person exports
    them (SETUP.md, "Monthly statement pull"). The user asked on 2026-09-13
    for a reminder for exactly that set. One alert per account, re-keyed each
    week so it comes back while the export is still missing and stops the
    night the file lands. Brokerage, retirement and HSA accounts come from the
    one Fidelity export, so they are one reminder, dated by the newest of
    them; Robinhood is its own.
    """
    day = date.fromisoformat(asof)
    week = day.isocalendar()[1]
    out = []
    rows = conn.execute("""SELECT a.name, a.kind, MAX(t.txn_date) AS last
                             FROM accounts a JOIN transactions t ON t.account_id = a.id
                            WHERE a.is_active = 1 GROUP BY a.id""").fetchall()
    fidelity = [r for r in rows if r["kind"] in ("brokerage", "retirement", "hsa") and "robinhood" not in r["name"].lower()]
    singles = [r for r in rows if r not in fidelity]
    groups = [("Fidelity (all accounts)", max((r["last"] for r in fidelity), default=None), "data/fidelity/")] if fidelity else []
    groups += [(r["name"], r["last"], "data/bank/" if r["kind"] == "checking" else "data/cards/" if r["kind"] == "credit" else "data/robinhood/")
               for r in singles]
    for name, last, folder in groups:
        if not last:
            continue
        age = (day - date.fromisoformat(last[:10])).days
        if age < STATEMENT_DUE_DAYS:
            continue
        out.append(_alert("statement", None, "warn",
                          f"{name}: the last export ends {last[:10]}, {age} days ago — pull a new one into {folder}",
                          f"statement:{name}:{day.year}w{week:02d}", asof,
                          "SETUP.md, \"Monthly statement pull\", has the route that works for each site; "
                          "then python3 -m app.import_all. Until it lands, spending, cash and net worth stop at that date."))
    try:
        from .importers import payroll_pdf
        payroll_pdf.ensure_schema(conn)
        stub = conn.execute("SELECT MAX(pay_end) FROM payroll_reference").fetchone()[0]
    except Exception:                                          # noqa: BLE001
        stub = None
    if stub:
        age = (day - date.fromisoformat(stub[:10])).days
        if age >= STUB_DUE_DAYS:
            out.append(_alert("statement", None, "warn",
                              f"Pay stub: the newest on file covers to {stub[:10]}, {age} days ago — drop the latest PDF into data/payroll/",
                              f"statement:paystub:{day.year}w{week:02d}", asof,
                              "The stub is where gross wages, withholding and the 401(k) deferral come from; "
                              "without a current one the tax floor and the deferral room are read from an old total."))
    return out


def wash_warnings(conn, run: dict, asof: str) -> list[dict]:
    """A buy or add tonight on a name sold at a loss in the last 30 days."""
    from . import performance, washsales
    try:
        txns = performance.load_transactions(conn, "2015-01-01", asof)
        warn = washsales.rebuy_warnings(conn, txns, asof)
    except Exception:                                          # noqa: BLE001
        return []
    out = []
    for sym, both in (run.get("results") or {}).items():
        w = warn.get(sym)
        if not w:
            continue
        heads = [both.get("headline")] + [(both.get(k) or {}).get("verdict") for k in ("daily", "weekly", "monthly")]
        if not any(h in ("buy", "add") for h in heads):
            continue
        if w.get("possible"):
            msg = (f"{sym}: the app reads buy/add, but you sold it on {w['date']} (confirmation email; shares and cost not "
                   f"in yet). If that sale was at a loss, buying back before {w['window_closes']} is a wash sale — "
                   f"{w['days_left']} day{'s' if w['days_left'] != 1 else ''} to wait.")
        else:
            msg = (f"{sym}: the app reads buy/add, but you sold {abs(w['quantity']):g} shares at a loss of {money(w['loss'])} "
                   f"on {w['date']}. Buying back before {w['window_closes']} disallows that loss this year — "
                   f"{w['days_left']} day{'s' if w['days_left'] != 1 else ''} to wait.")
        out.append(_alert("wash", sym, "warn", msg, f"wash:{sym}:{w['date']}:{asof}", asof))
    return out


def ladder_rungs(conn, run: dict, asof: str) -> list[dict]:
    """A sell-ladder rung fired on a held name (D69, D71): a third at 60%
    above the 50-day, a third at weekly RSI 85, the rest when the weekly RSI
    closes back under 70 after 80+. One alert per rung per run, keyed by the
    day it fired, so a rung that fired last week is not repeated tonight."""
    from . import ladder, performance
    try:
        txns = performance.load_transactions(conn, "2015-01-01", asof)
        entries = ladder.entry_dates(txns)
    except Exception:                                          # noqa: BLE001
        return []
    out = []
    recent = (date.fromisoformat(asof) - timedelta(days=4)).isoformat()
    for sym in sorted(run.get("results") or {}):
        try:
            bars, _proxy = prices.analysis_bars(conn, sym, "2015-01-01", asof)
            st = ladder.state(bars, entries.get(sym))
        except Exception:                                      # noqa: BLE001
            continue
        if not st:
            continue
        for r in st["rungs"]:
            if not r["fired"] or r["fired"] < recent:
                continue
            share = "the rest of the trading half" if r["n"] == 3 else "a third of the trading half"
            what = {1: f"closed {r['reading']*100:.0f}% above its 50-day average",
                    2: f"weekly RSI closed at {r['reading']}",
                    3: f"weekly RSI closed back under 70 (at {r['reading']}) after reaching {r.get('peak8')}"}[r["n"]]
            out.append(_alert("ladder", sym, "act",
                              f"{sym} ladder rung {r['n']}: {what} on {r['fired']} at {r['fired_at']:.2f} — sell {share}. "
                              f"On 36 names it was not read from, 78% of these sells landed within 25% of a real top; on your own "
                              f"trades since 2022 the ladder kept the winners you sold early (D71).",
                              f"ladder:{sym}:{r['n']}:{r['fired']}", asof, detail=st.get("summary")))
    return out


def money(x) -> str:
    try:
        return f"${abs(float(x)):,.0f}"
    except (TypeError, ValueError):
        return "—"


def williams_floor(conn, symbols: list[str], asof: str) -> list[dict]:
    """The weekly Williams %R (14) at the floor, -97 or under, on a held or
    watched name — the buy-side reading that measured best on the user's own
    names (research/audits/sweep-IREN-2026-09-05.md). One alert per name per
    week while it stays there; the message carries the record so the reader
    knows what it has and has not meant."""
    from . import indicators as I
    out = []
    week = date.fromisoformat(asof).isocalendar()
    for sym in symbols:
        try:
            bars = prices.load_bars(conn, sym, "2015-01-01", asof)
        except Exception:                                      # noqa: BLE001
            continue
        if len(bars) < 200:
            continue
        weekly = I.resample(bars, "W")
        wr = I.williams_r(weekly, 14, 0.0, -100.0)
        if not wr or wr[-1]["value"] is None or wr[-1]["value"] > -97.0:
            continue
        v = wr[-1]["value"]
        drawdown = bars[-1]["close"] / max(b["close"] for b in bars[-250:]) - 1
        out.append(_alert("floor", sym, "act",
                          f"{sym} weekly Williams %R at {v:.0f} — the floor, {drawdown*100:+.0f}% from its 52-week high. "
                          f"On IREN since 2023 every reading this low was within 8% of a low that then rallied 81–590%; "
                          f"in IREN's 2022 collapse it fired three times and kept falling. A place to start buying if "
                          f"the business is intact, not a trigger on its own.",
                          f"floor:{sym}:{week[0]}-{week[1]}", asof))
    return out


def regime_change(conn, asof: str) -> list[dict]:
    """The exposure dial moved since a week ago."""
    from . import regime
    try:
        now = regime.reading(conn, asof)
        then = regime.reading(conn, (date.fromisoformat(asof) - timedelta(days=7)).isoformat())
    except Exception:                                           # noqa: BLE001
        return []
    if now["state"] == then["state"]:
        return []
    return [_alert("regime", None, "warn",
                   f"Exposure dial: {then['label']} → {now['label']} ({now['score']:+d} of 4). {now['summary']}",
                   f"regime:{now['state']}:{asof[:7]}", asof)]


def store_levels(conn, day: str, symbol: str, verdict: str | None, watch: dict | None) -> None:
    ensure_schema(conn)
    w = watch or {}
    conn.execute("""INSERT INTO watch_levels (day, symbol, verdict, price, buy_at, trim_at, stop_at, flip)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(day, symbol) DO UPDATE SET verdict=excluded.verdict, price=excluded.price,
                      buy_at=excluded.buy_at, trim_at=excluded.trim_at, stop_at=excluded.stop_at,
                      flip=excluded.flip""",
                 (day, symbol, verdict, w.get("price"), w.get("buy_at"), w.get("trim_at"),
                  w.get("stop_at"), w.get("flip") if "flip" in w else None))


def latest_levels(conn, symbol: str, upto: str) -> dict | None:
    ensure_schema(conn)
    row = conn.execute("""SELECT * FROM watch_levels WHERE symbol=? AND day<=?
                          ORDER BY day DESC LIMIT 1""", (symbol, upto)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------- delivery ---

def send_ntfy(topic: str, title: str, body: str, priority: str = "default") -> bool:
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
        headers={"Title": title, "Priority": priority, "Content-Type": "text/plain"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return 200 <= resp.status < 300


def send_macos(title: str, body: str) -> bool:
    # Backslash first, then the quote: a `\` before a swapped-in `'` is
    # harmless, but a `\"` left in the text would end the AppleScript string.
    # Truncated BEFORE escaping so the cut cannot land between a pair.
    def q(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', "'")
    script = 'display notification "{}" with title "{}"'.format(q(body[:200]), q(title))
    r = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    return r.returncode == 0


# How many alerts may be PUSHED in one run. Everything else is still stored and
# still on the Overview; it just does not interrupt.
#
# The user, 2026-09-10: "When market opens i get smacked with like 20
# notifications and i dont have time to read them all." The record agrees — 17
# to 26 a day for the last week, every one of them sent, because nothing capped
# it. Twenty alerts that are individually well-worded are functionally zero
# alerts, so the wording work never reached them.
#
# Four is what fits on a lock screen at 9:30 and can actually be read. The rest
# arrive as ONE digest naming the symbols, so nothing is hidden.
MAX_PUSH = 4


def _consequence(conn, alerts: list[dict]) -> dict[str, float]:
    """Dollar value of the position each alert is about, for ranking.

    A level touched on a $190,000 position outranks the same event on a $2,000
    one, which is the ordering the Overview's attention list already uses.
    Anything not held ranks below everything held rather than being dropped —
    a watchlist name reaching a level is still worth knowing, just not first.
    """
    try:
        from . import holdings, performance
        txns = performance.load_transactions(conn, "1900-01-01", date.today().isoformat(), "investment")
        return {p["symbol"]: (p.get("value") or 0)
                for p in holdings.positions(conn, txns, date.today().isoformat())}
    except Exception:                                           # noqa: BLE001
        return {}


def rank(conn, alerts: list[dict]) -> list[dict]:
    """Most consequential first: severity, then the size of the position."""
    value = _consequence(conn, alerts)
    return sorted(alerts,
                  key=lambda a: (-LEVELS.get(a.get("level"), 0),
                                 -value.get(a.get("symbol") or "", 0.0),
                                 a.get("symbol") or ""))


def digest(rest: list[dict]) -> str:
    """One line for everything that did not make the cut."""
    syms = []
    for a in rest:
        s = a.get("symbol") or "portfolio"
        if s not in syms:
            syms.append(s)
    head = ", ".join(syms[:8]) + (f" and {len(syms) - 8} more" if len(syms) > 8 else "")
    return (f"{len(rest)} more alert{'s' if len(rest) != 1 else ''}: {head}. "
            f"They are on the Overview — nothing here needs you in the next minute.")


def deliver(conn, alerts: list[dict], cfg: dict | None = None,
            senders: dict | None = None) -> dict:
    """Store every alert; push the most consequential few, digest the rest.

    `senders` exists for tests: a map of channel name to a callable taking
    (title, body) and returning True on success.
    """
    ensure_schema(conn)
    cfg = cfg or settings()
    min_level = LEVELS.get(cfg.get("min_level", "warn"), 1)
    max_push = int(cfg.get("max_push", MAX_PUSH))
    senders = senders if senders is not None else _default_senders(cfg)
    now = datetime.now().isoformat(timespec="seconds")
    stored, sent, failed = 0, 0, []
    pushable, held_back = [], []
    for a in alerts:
        cur = conn.execute(
            """INSERT OR IGNORE INTO alerts (created_at, day, kind, symbol, level, message, key, detail)
               VALUES (?,?,?,?,?,?,?,?)""",
            (now, a["day"], a["kind"], a.get("symbol"), a["level"], a["message"], a["key"], a.get("detail")))
        if cur.rowcount == 0:
            continue                       # already stored: already sent or judged
        stored += 1
        if LEVELS.get(a["level"], 0) < min_level or not senders:
            continue
        pushable.append(a)

    # Rank AFTER the whole batch is known, so the cap keeps the four that matter
    # rather than the first four to arrive.
    ordered = rank(conn, pushable)
    to_push, held_back = ordered[:max_push], ordered[max_push:]

    def _push(title, body, keys):
        nonlocal sent
        used = []
        for name, fn in senders.items():
            try:
                if fn(title, body):
                    used.append(name)
            except Exception as exc:                            # noqa: BLE001
                failed.append((name, f"{type(exc).__name__}"))
        if used:
            sent += 1
            for k in keys:
                conn.execute("UPDATE alerts SET sent_at=?, channel=? WHERE key=?",
                             (now, ",".join(used), k))

    for a in to_push:
        _push(f"{(a.get('symbol') or 'Portfolio')} · {a['kind']}",
              a["message"] + (f"\n\n{a['detail']}" if a.get("detail") else ""),
              [a["key"]])
    if held_back:
        # Marked sent because it DID reach them, inside the digest. Leaving them
        # unsent would make them fire again on the next run, which is the flood
        # this exists to stop.
        _push("Portfolio · also today", digest(held_back), [a["key"] for a in held_back])
    conn.commit()
    return {"stored": stored, "sent": sent, "failed": failed, "total": len(alerts),
            "pushed": len(to_push), "digested": len(held_back)}


def _default_senders(cfg: dict) -> dict:
    out = {}
    if cfg.get("ntfy_topic"):
        topic = cfg["ntfy_topic"]
        out["ntfy"] = lambda title, body: send_ntfy(topic, title, body)
    if cfg.get("macos") and sys.platform == "darwin":
        out["macos"] = send_macos
    return out


# ------------------------------------------------------------------ runs ----

def sentiment_extremes(conn, asof: str) -> list[dict]:
    """Market fear and greed at an extreme, or moving fast toward one.

    The user's own rule — buy when others are fearful, when there is blood in
    the streets — has a number: CNN's index under 25. Nothing alerted on it,
    so a reading the whole verdict layer weights could arrive and leave
    without a word. One alert per day per state, keyed so a market that stays
    extreme is not re-announced every night."""
    from . import sentiment
    m = sentiment.latest(conn, asof)
    if not m or m.get("score") is None:
        return []
    score, prev = m["score"], m.get("previous")
    out = []
    if score < 25:
        out.append(_alert("sentiment", None, "high",
                          f"Extreme fear: fear and greed at {score:.0f}. Blood in the streets — "
                          f"the contrarian case is to buy, and it is adding weight to every "
                          f"holding's verdict tonight.", f"sentiment-extreme-fear-{asof}", asof))
    elif score > 75:
        out.append(_alert("sentiment", None, "high",
                          f"Extreme greed: fear and greed at {score:.0f}. The contrarian case "
                          f"is to take something off.", f"sentiment-extreme-greed-{asof}", asof))
    elif prev is not None and abs(score - prev) >= 10:
        out.append(_alert("sentiment", None, "info",
                          f"Fear and greed moved {score - prev:+.0f} in a day, to {score:.0f} "
                          f"({m.get('rating')}). Not extreme yet; extreme is under 25.",
                          f"sentiment-move-{asof}", asof))
    return out


def nightly(conn, asof: str | None = None, log=None) -> dict:
    """Score (without recording — the outlook job did that), derive, deliver."""
    from . import outlook
    say = log or (lambda *a: None)
    asof = asof or date.today().isoformat()
    # A Saturday run scores Friday's close again; with Saturday in the key it
    # re-sent every one of Friday's alerts. Key the weekend to the session.
    y, m, d = (int(x) for x in asof.split("-"))
    while date(y, m, d).weekday() >= 5:
        y, m, d = (date(y, m, d) - timedelta(days=1)).timetuple()[:3]
    asof = date(y, m, d).isoformat()
    run = outlook.run(conn, asof, dry_run=True, scope="held")
    held = sorted(run.get("results") or {})
    ups = earnings.upcoming(conn, held, asof)
    mine = user_levels(conn)
    watched = sorted(set(held) | set(watchlist.symbols(conn) if hasattr(watchlist, "symbols") else []))
    alerts = (from_outlook(run, ups, asof) + tier_changes(conn, held, asof) + regime_change(conn, asof)
              + sentiment_extremes(conn, asof) + williams_floor(conn, watched, asof) + wash_warnings(conn, run, asof)
              + ladder_rungs(conn, run, asof) + statement_reminders(conn, asof)
              + from_levels(mine, _closes(conn, sorted(mine), asof), asof,
                            calls=calls_from_results(run.get("results"), books.lookup(conn))))
    for sym, both in (run.get("results") or {}).items():
        d = both.get("daily") or {}
        store_levels(conn, asof, sym, d.get("verdict"), {**(d.get("watch") or {}), "flip": d.get("flip")})
    res = deliver(conn, alerts)
    for a in alerts:
        say(f"  [{a['level']:<4}] {a['message']}")
    say(f"  {res['stored']} new, {res['sent']} sent, {len(alerts)} in all")
    return {**res, "alerts": alerts}


def poll(conn, now: datetime | None = None, log=None) -> dict:
    """Intraday: the last 15-minute bar of every holding against its levels."""
    from . import outlook
    say = log or (lambda *a: None)
    now = now or datetime.now(NY)
    if not market_open(now):
        return {"skipped": "market closed"}
    today = now.astimezone(NY).date().isoformat()
    held = [p["symbol"] for p in outlook._held(conn, today)]
    mine = user_levels(conn)
    alerts, checked = [], 0
    for sym in sorted(set(held) | set(mine)):
        lv = latest_levels(conn, sym, today)
        if not lv and sym not in mine:
            continue
        try:
            bars = prices.fetch_intraday(sym, "15m", today, today)
        except Exception:                                       # noqa: BLE001
            continue
        if not bars:
            continue
        checked += 1
        price = bars[-1][4]
        if sym in mine:
            call = ({"daily": lv.get("verdict"), "next_up": lv.get("trim_at"),
                     "next_down": lv.get("buy_at"), "stop_at": lv.get("stop_at")} if lv else None)
            alerts += from_levels({sym: mine[sym]}, {sym: (price, _prev_close(conn, sym, today))},
                                  today, intraday=True, calls={sym: call} if call else None)
        if not lv:
            continue
        if lv.get("stop_at") and price < lv["stop_at"]:
            alerts.append(_alert("intraday", sym, "act",
                                 f"{sym} is trading at {price:,.2f}, below its stop level "
                                 f"{lv['stop_at']:,.2f} from the {lv['day']} call",
                                 f"intraday:{sym}:stop:{today}", today))
        if lv.get("trim_at") and price > lv["trim_at"]:
            alerts.append(_alert("intraday", sym, "act",
                                 f"{sym} is trading at {price:,.2f}, through its trim level "
                                 f"{lv['trim_at']:,.2f} from the {lv['day']} call",
                                 f"intraday:{sym}:trim:{today}", today))
        # Reaching the buy-at level intraday is not an alert. It fires on most
        # names on most days — the buy level sits close to price by
        # construction — and a buy is a decision the user makes at the desk,
        # not something to be interrupted for. Only a level GIVEN UP (the stop,
        # the flip) or one REACHED on the upside (the trim) still fires.
        if lv.get("flip") and lv.get("verdict") in ("buy", "add", "hold") and price < lv["flip"]:
            alerts.append(_alert("intraday", sym, "act",
                                 f"{sym} is trading at {price:,.2f}, below the {lv['flip']:,.2f} "
                                 f"that flips its {lv['verdict'].upper()} call",
                                 f"intraday:{sym}:flip:{today}", today))
    # The buy plans set the night before: gap rule and max price against
    # today's first bar and the last price.
    try:
        from . import plans
        cache: dict = {}
        def bars_for(sym):
            if sym not in cache:
                try:
                    cache[sym] = prices.fetch_intraday(sym, "15m", today, today)
                except Exception:                              # noqa: BLE001
                    cache[sym] = []
            return cache[sym]
        for a in plans.check(conn, bars_for, lambda sym: _prev_close(conn, sym, today), today):
            alerts.append(_alert(a["kind"], a["symbol"], a["level"], a["message"], a["key"], today, a.get("detail")))
    except Exception:                                          # noqa: BLE001
        pass
    res = deliver(conn, alerts)
    for a in alerts:
        say(f"  [{a['level']:<4}] {a['message']}")
    return {**res, "checked": checked, "alerts": alerts}


def recent(conn, days: int = 7) -> list[dict]:
    ensure_schema(conn)
    since = (date.today() - timedelta(days=days)).isoformat()
    return [dict(r) for r in conn.execute(
        """SELECT * FROM alerts WHERE day >= ? ORDER BY created_at DESC, id DESC LIMIT 200""",
        (since,))]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.alerts")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("nightly"); n.add_argument("--asof", default=None)
    sub.add_parser("poll")
    sub.add_parser("test")
    s = sub.add_parser("show"); s.add_argument("--days", type=int, default=7)
    args = p.parse_args(argv)
    conn = connect()
    if args.cmd == "nightly":
        r = nightly(conn, args.asof, log=print)
        return 0
    if args.cmd == "poll":
        r = poll(conn, log=print)
        if r.get("skipped"):
            # Every 15 minutes round the clock the poll runs and finds the
            # market shut; one line an hour keeps poll.log readable.
            if datetime.now(NY).minute < 15:
                print(f"{r['skipped']} ({datetime.now(NY):%H:%M} NY)")
        else:
            print(f"  checked {r['checked']}, {r['stored']} new, {r['sent']} sent")
        return 0
    if args.cmd == "test":
        cfg = settings()
        senders = _default_senders(cfg)
        if not senders:
            print("  no channel configured: set alerts.ntfy_topic in config.json, or run on a Mac")
            return 1
        for name, fn in senders.items():
            ok = False
            try:
                ok = fn("Investment app", "Test alert. If you can read this, alerts reach you here.")
            except Exception as exc:                            # noqa: BLE001
                print(f"  {name}: failed ({type(exc).__name__}: {exc})")
                continue
            print(f"  {name}: {'sent' if ok else 'failed'}")
        return 0
    if args.cmd == "show":
        for a in recent(conn, args.days):
            print(f"  {a['day']}  [{a['level']:<4}] {a['message']}"
                  f"{'  (sent ' + a['channel'] + ')' if a['sent_at'] else ''}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
