"""Paper trading of the app's own calls, on the Alpaca paper account.

    python3 -m app.paper run [--dry-run]     # after the nightly scoring; update.sh runs it
    python3 -m app.paper status              # equity, positions, open orders
    python3 -m app.paper orders              # the last forty orders and what became of them

## What it is for

A forward record nobody can backfill. The replay says what the engine would
have called in the past; this says what it calls from tonight on, with real
fills at the next open, in an account that starts at $100,000 of paper
money. In three months the equity curve against SPY is the one number about
the engine that has no survivorship in it and no fitting in it.

## The strategy — the app's own blend, nothing borrowed

Decided 2026-09-02: not any one analyst's method, the app's blended engine.
And on the timeframe the measurement supports: the weekly.

  * Universe: every name held or watched, scored nightly.
  * Enter when the weekly call is BUY or ADD at measured confidence HIGH —
    the top fifth of the replayed record — and the name is not held.
  * Exit when the weekly call turns to SELL, or the position's stop level
    (the level under which the idea is wrong, from the call that opened it)
    has been closed below.
  * Equal weight: target book of MAX_POSITIONS names, each sized to equity
    divided by that, whole shares only. Ranked by measured score when more
    qualify than there is room for.
  * Every order is a plain market order placed after the close, which
    Alpaca queues for the next open — the same fill rule the backtester
    uses, so the paper book and the backtest are comparable. (Market-on-open
    orders were tried first; on the paper venue they expired at the open
    unfilled on 2026-09-03.)

The books your real money is in do not apply here: the paper account trades
the engine's calls as calls, which is the point of having it.

## What it is not

It never touches a real account. The base URL is the paper host and nothing
else; the key on file is a paper key. It does not know about earnings,
sentiment, position books or the DCA ladder — it is the weekly engine, on
its own, so that what it earns or loses belongs to the engine.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

from . import measure, netsafe, outlook, prices, verdicts
from .ledger import connect, retry_locked

PAPER = "https://paper-api.alpaca.markets"
MAX_POSITIONS = 10
ENTRY_ACTIONS = ("buy", "add")
STRATEGY = "weekly-measured-top-fifth"

# Names under PENNY_PRICE are not excluded — the user wanted no floor — but
# exposure to them is limited: at most PENNY_SLOTS of the book at once, each
# at PENNY_WEIGHT of a normal slot, unless there is good evidence. The one
# piece of evidence the replayed record supports is daily relative strength
# in the top fifth of the universe (rank PENNY_EVIDENCE_RS or better), so a
# sub-$2 name with that rank takes a normal slot and does not count against
# the cap. Held names beyond the cap are sold, lowest measured score first.
PENNY_PRICE = 2.0
PENNY_SLOTS = 2
PENNY_WEIGHT = 0.5
PENNY_EVIDENCE_RS = 80

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_orders (
    id           INTEGER PRIMARY KEY,
    submitted_at TEXT NOT NULL,
    day          TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL,          -- buy | sell
    qty          REAL NOT NULL,
    reason       TEXT,
    stop         REAL,
    alpaca_id    TEXT,
    status       TEXT,                   -- submitted | filled | rejected | canceled | dry-run
    filled_qty   REAL,
    filled_price REAL,
    filled_at    TEXT
);
CREATE TABLE IF NOT EXISTS paper_snapshots (
    day TEXT PRIMARY KEY, strategy TEXT NOT NULL, equity REAL, cash REAL,
    positions TEXT, taken_at TEXT NOT NULL
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


# ------------------------------------------------------------- broker ----

class Broker:
    """The few Alpaca paper endpoints this needs. Paper host only."""

    def __init__(self, key: str, secret: str):
        self.headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                        "Content-Type": "application/json"}

    def _call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(PAPER + path, data=data, headers=self.headers, method=method)
        try:
            with netsafe.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"{method} {path}: HTTP {exc.code} {detail}") from None

    def account(self) -> dict:
        return self._call("GET", "/v2/account")

    def positions(self) -> list[dict]:
        return self._call("GET", "/v2/positions")

    def open_orders(self) -> list[dict]:
        return self._call("GET", "/v2/orders?status=open&limit=200")

    def order(self, order_id: str) -> dict:
        return self._call("GET", f"/v2/orders/{order_id}")

    def submit(self, symbol: str, side: str, qty: int) -> dict:
        return self._call("POST", "/v2/orders", {
            "symbol": symbol, "qty": str(int(qty)), "side": side,
            "type": "market", "time_in_force": "day"})

    def cancel_all(self) -> None:
        self._call("DELETE", "/v2/orders")


def broker() -> Broker:
    creds = prices.alpaca_credentials()
    if not creds:
        raise RuntimeError("No Alpaca credentials; see data/.alpaca")
    return Broker(*creds)


# ----------------------------------------------------------- decisions ----

def _penny(sym: str, px: float | None, rs_ranks: dict) -> bool:
    """Under the penny price and without the one piece of evidence that lifts it."""
    if not px or px >= PENNY_PRICE:
        return False
    rank = rs_ranks.get(sym)
    return rank is None or rank < PENNY_EVIDENCE_RS


def decide_orders(results: dict, held: dict[str, float], equity: float,
                  prices_now: dict[str, float], stops: dict[str, float],
                  max_positions: int = MAX_POSITIONS,
                  rs_ranks: dict | None = None,
                  cash_available: float | None = None) -> list[dict]:
    """The orders the strategy wants, from tonight's weekly calls.

    Pure: no broker, no database. `results` is outlook.run's per-symbol
    output, `held` is {symbol: shares} in the paper account, `stops` the
    stop level recorded when each held name was bought, `rs_ranks` the
    daily relative-strength rank (1-99) of each name across the universe.
    """
    rs_ranks = rs_ranks or {}
    orders = []
    # ---- exits ----
    for sym, shares in held.items():
        r = results.get(sym)
        w = (r or {}).get("weekly") or {}
        px = prices_now.get(sym) or w.get("price")
        reason = None
        if w.get("verdict") == "sell":
            reason = "weekly call turned to sell"
        elif stops.get(sym) and px and px < stops[sym]:
            reason = f"closed below the {stops[sym]:,.2f} stop the entry named"
        elif r is None:
            reason = "no longer scored"
        if reason and shares > 0:
            orders.append({"symbol": sym, "side": "sell", "qty": int(shares), "reason": reason})
    exiting = {o["symbol"] for o in orders}

    # ---- the penny cap on what is held ----
    def _score(sym):
        return ((results.get(sym) or {}).get("weekly") or {}).get("measured_score") or 0.0
    held_penny = sorted((s for s, q in held.items() if q > 0 and s not in exiting
                         and _penny(s, prices_now.get(s), rs_ranks)), key=_score)
    for sym in held_penny[:max(0, len(held_penny) - PENNY_SLOTS)]:
        orders.append({"symbol": sym, "side": "sell", "qty": int(held[sym]),
                       "reason": f"under ${PENNY_PRICE:.0f} without relative-strength evidence, and the "
                                 f"book already holds {PENNY_SLOTS} such names"})
        exiting.add(sym)
    penny_held = len(held_penny) - len(held_penny[:max(0, len(held_penny) - PENNY_SLOTS)])

    room = max_positions - sum(1 for s, q in held.items() if q > 0 and s not in exiting)
    if room <= 0:
        return orders
    # ---- entries: top fifth, ranked by measured score ----
    cands = []
    for sym, r in results.items():
        if sym in held and held[sym] > 0:
            continue
        w = r.get("weekly") or {}
        if w.get("insufficient") or w.get("verdict") not in ENTRY_ACTIONS:
            continue
        if w.get("confidence") != "high" or w.get("measured_fifth") != 5:
            continue
        px = prices_now.get(sym) or w.get("price")
        stop = (w.get("watch") or {}).get("stop_at") or w.get("flip")
        if not px or px <= 0:
            continue
        cands.append((w.get("measured_score") or 0.0, sym, px, stop, w.get("because", [""])[0]))
    cands.sort(key=lambda c: (-c[0], c[1]))
    per = equity / max_positions
    # Whole-share slots sized off equity alone overshot the cash on hand and
    # the account ran a margin balance against its own "paper money only"
    # rule. Buys are capped by the cash left, including tonight's sale proceeds.
    cash_left = float(cash_available) if cash_available is not None else equity
    for o in orders:
        if o["side"] == "sell":
            cash_left += o["qty"] * float(prices_now.get(o["symbol"]) or 0.0)
    taken = 0
    for score, sym, px, stop, why in cands:
        if taken >= room:
            break
        penny = _penny(sym, px, rs_ranks)
        if penny and penny_held >= PENNY_SLOTS:
            continue
        qty = int((min(per * (PENNY_WEIGHT if penny else 1.0), max(0.0, cash_left))) // px)
        if qty < 1:
            continue
        cash_left -= qty * px
        if penny:
            penny_held += 1
        taken += 1
        note = (f"; under ${PENNY_PRICE:.0f}, half a slot" if penny else
                f"; under ${PENNY_PRICE:.0f} but relative strength rank {rs_ranks.get(sym)}, a full slot"
                if px < PENNY_PRICE else "")
        orders.append({"symbol": sym, "side": "buy", "qty": qty, "stop": stop,
                       "reason": f"weekly {results[sym]['weekly']['verdict']}, measured top fifth "
                                 f"({score:+.2f}){note}; {why}"[:300]})
    return orders


# ----------------------------------------------------------------- run ----

def run(conn, dry_run: bool = False, log=None) -> dict:
    say = log or (lambda *a: None)
    ensure_schema(conn)
    b = broker()
    acct = b.account()
    equity = float(acct.get("equity") or 0)
    held = {p["symbol"]: float(p["qty"]) for p in b.positions()}
    open_orders = b.open_orders()
    if open_orders:
        # Yesterday's on-open orders that never filled (a halt, a rejection
        # nobody read) are not carried into today's decision.
        b.cancel_all()
        say(f"  cancelled {len(open_orders)} stale open order(s)")

    # Score everything held or watched, without recording — the nightly
    # outlook job is the only writer of the app's calls.
    out = outlook.run(conn, dry_run=True, scope="all")
    results = out.get("results") or {}
    prices_now = {s: (r.get("daily") or {}).get("price") for s, r in results.items()}
    stops = {r["symbol"]: r["stop"] for r in conn.execute(
        """SELECT symbol, stop FROM paper_orders WHERE side='buy' AND status IN ('submitted','filled')
             AND stop IS NOT NULL ORDER BY submitted_at""")}
    from . import watchlist
    rs_ranks = watchlist.rs_ranks(conn, sorted(results), date.today().isoformat())
    orders = decide_orders(results, held, equity, prices_now, stops, rs_ranks=rs_ranks,
                           cash_available=float(acct.get("cash") or 0))

    day = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    placed, failed = 0, []
    for o in orders:
        alpaca_id, status = None, "dry-run"
        if not dry_run:
            try:
                r = b.submit(o["symbol"], o["side"], o["qty"])
                alpaca_id, status = r.get("id"), "submitted"
                placed += 1
            except Exception as exc:                                # noqa: BLE001
                status = f"rejected: {str(exc)[:120]}"
                failed.append((o["symbol"], status))
        if not dry_run:
            retry_locked(lambda: (conn.execute(
                """INSERT INTO paper_orders (submitted_at, day, strategy, symbol, side, qty, reason, stop, alpaca_id, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (now, day, STRATEGY, o["symbol"], o["side"], o["qty"], o.get("reason"), o.get("stop"),
                 alpaca_id, status)), conn.commit()))
        say(f"  {o['side']:<4} {o['qty']:>5} {o['symbol']:<6} {status:<10} {o.get('reason', '')[:80]}")

    # Yesterday's orders: what became of them.
    reconcile(conn, b)
    # Tonight's snapshot.
    snap = {"equity": equity, "cash": float(acct.get("cash") or 0),
            "positions": [{"symbol": p["symbol"], "qty": float(p["qty"]),
                           "avg": float(p.get("avg_entry_price") or 0),
                           "value": float(p.get("market_value") or 0),
                           "pl_pct": float(p.get("unrealized_plpc") or 0)} for p in b.positions()]}
    retry_locked(lambda: (conn.execute(
        """INSERT INTO paper_snapshots (day, strategy, equity, cash, positions, taken_at) VALUES (?,?,?,?,?,?)
           ON CONFLICT(day) DO UPDATE SET equity=excluded.equity, cash=excluded.cash,
             positions=excluded.positions, taken_at=excluded.taken_at""",
        (day, STRATEGY, snap["equity"], snap["cash"], json.dumps(snap["positions"]), now)), conn.commit()))
    say(f"  equity {equity:,.0f}, {len(held)} held, {len(orders)} order(s) "
        f"{'planned (dry run)' if dry_run else 'placed'}, {len(failed)} rejected")
    return {"equity": equity, "held": held, "orders": orders, "placed": placed, "failed": failed}


def reconcile(conn, b: Broker) -> int:
    """Fill prices and statuses for every order still marked submitted."""
    n = 0
    for row in conn.execute("SELECT id, alpaca_id FROM paper_orders WHERE status='submitted' AND alpaca_id IS NOT NULL").fetchall():
        try:
            o = b.order(row["alpaca_id"])
        except Exception:                                           # noqa: BLE001
            continue
        st = o.get("status")
        if st in ("filled", "partially_filled"):
            conn.execute("""UPDATE paper_orders SET status='filled', filled_qty=?, filled_price=?, filled_at=? WHERE id=?""",
                         (float(o.get("filled_qty") or 0), float(o.get("filled_avg_price") or 0),
                          o.get("filled_at"), row["id"]))
            n += 1
        elif st in ("canceled", "expired", "rejected"):
            conn.execute("UPDATE paper_orders SET status=? WHERE id=?", (st, row["id"]))
            n += 1
    conn.commit()
    return n


# --------------------------------------------------------------- report ---

def report(conn) -> dict:
    ensure_schema(conn)
    snaps = [dict(r) for r in conn.execute("SELECT * FROM paper_snapshots ORDER BY day")]
    orders = [dict(r) for r in conn.execute("SELECT * FROM paper_orders ORDER BY submitted_at DESC, id DESC LIMIT 40")]
    curve = []
    spy = prices.load_series(conn, "SPY") or prices.load_series(conn, "SP500")
    spy_dates = sorted(spy) if spy else []
    from . import performance
    p0 = None
    for s in snaps:
        sp = performance.last_known_price(spy, s["day"], spy_dates) if spy else None
        if p0 is None and sp:
            p0 = sp
        curve.append({"day": s["day"], "equity": s["equity"],
                      "spy": (100000.0 * sp / p0) if (sp and p0) else None})
    latest = snaps[-1] if snaps else None
    return {"strategy": STRATEGY, "started": snaps[0]["day"] if snaps else None,
            "latest": latest and {**latest, "positions": json.loads(latest["positions"] or "[]")},
            "curve": curve, "orders": orders,
            "rules": ["Enter when the weekly call is buy or add at measured confidence high (the top fifth of the replayed record).",
                      "Exit when the weekly call turns to sell, or price closes below the stop the entry named.",
                      f"Equal weight across up to {MAX_POSITIONS} names, whole shares, market orders placed after the close and filled at the next open.",
                      f"No price floor, but at most {PENNY_SLOTS} names under ${PENNY_PRICE:.0f} at once, each at half a slot — unless the name's daily relative strength ranks {PENNY_EVIDENCE_RS} or better across the universe, the one piece of evidence the record supports, in which case it takes a normal slot.",
                      "Paper money only, $100,000 to start. No earnings, sentiment, books or DCA ladder: the weekly engine on its own."]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.paper")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--dry-run", action="store_true")
    sub.add_parser("status"); sub.add_parser("orders")
    args = p.parse_args(argv)
    conn = connect()
    if args.cmd == "run":
        out = run(conn, dry_run=args.dry_run, log=print)
        return 0 if not out["failed"] else 1
    b = broker()
    if args.cmd == "status":
        a = b.account()
        print(f"  equity {float(a['equity']):,.2f}  cash {float(a['cash']):,.2f}")
        for pos in b.positions():
            print(f"    {pos['symbol']:<6} {float(pos['qty']):>8,.0f} @ {float(pos['avg_entry_price']):,.2f}  "
                  f"now {float(pos['current_price']):,.2f}  {float(pos['unrealized_plpc'])*100:+.1f}%")
        for o in b.open_orders():
            print(f"    open: {o['side']} {o['qty']} {o['symbol']} ({o['status']})")
        return 0
    if args.cmd == "orders":
        ensure_schema(conn)
        reconcile(conn, b)
        for o in conn.execute("SELECT * FROM paper_orders ORDER BY submitted_at DESC LIMIT 40"):
            print(f"  {o['day']} {o['side']:<4} {o['qty']:>5.0f} {o['symbol']:<6} {o['status']:<10} "
                  f"{('@ ' + format(o['filled_price'], ',.2f')) if o['filled_price'] else ''}  {(o['reason'] or '')[:70]}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
