"""Buy plans for the next session, set the night before.

The user names the buys for tomorrow ("I like TEM and DGXX as buys tomorrow
as long as they don't gap up at the open — then I'd wait to see if they sell
off a bit"). A plan holds that rule as numbers: the most to pay, and the gap
above the prior close past which the buy waits for a pullback under the open.
The intraday poll (every 15 minutes in the session) checks each plan against
the day's first bar and the last price and raises an alert when the plan's
condition is met, once per day per condition. Nothing here places an order.
"""
from __future__ import annotations

from datetime import date

SCHEMA = """
CREATE TABLE IF NOT EXISTS buy_plans (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    max_price REAL NOT NULL,
    gap_pct REAL NOT NULL DEFAULT 2.0,
    note TEXT,
    created TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS buy_plan_events (
    plan_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,          -- gapped | at_level | pulled_back
    price REAL,
    PRIMARY KEY (plan_id, day, kind)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def add(conn, symbol: str, max_price: float, gap_pct: float = 2.0, note: str | None = None) -> dict:
    ensure_schema(conn)
    symbol = (symbol or "").strip().upper()
    if not symbol or not max_price or max_price <= 0:
        raise ValueError("a symbol and a positive maximum price are needed")
    gap_pct = float(gap_pct if gap_pct is not None else 2.0)
    # one live plan per name: a new one replaces it
    conn.execute("UPDATE buy_plans SET active=0 WHERE symbol=? AND active=1", (symbol,))
    cur = conn.execute("INSERT INTO buy_plans (symbol, max_price, gap_pct, note, created) VALUES (?,?,?,?,?)",
                       (symbol, float(max_price), gap_pct, (note or "").strip() or None, date.today().isoformat()))
    conn.commit()
    return {"id": cur.lastrowid, "symbol": symbol, "max_price": float(max_price), "gap_pct": gap_pct}


def remove(conn, plan_id: int) -> dict:
    ensure_schema(conn)
    conn.execute("UPDATE buy_plans SET active=0 WHERE id=?", (int(plan_id),))
    conn.commit()
    return {"ok": True}


def active(conn, today: str | None = None) -> list[dict]:
    ensure_schema(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM buy_plans WHERE active=1 ORDER BY symbol")]
    today = today or date.today().isoformat()
    for r in rows:
        r["today"] = {e["kind"]: e["price"] for e in conn.execute(
            "SELECT kind, price FROM buy_plan_events WHERE plan_id=? AND day=?", (r["id"], today))}
    return rows


def judge(plan: dict, prev_close: float | None, day_open: float | None, price: float | None) -> list[tuple[str, str]]:
    """What the plan says right now, as (kind, message) pairs. Pure, so it can
    be tested without a market."""
    out = []
    if not price or not day_open:
        return out
    gapped = bool(prev_close) and day_open > prev_close * (1 + plan["gap_pct"] / 100.0)
    gap = (day_open / prev_close - 1) * 100 if prev_close else 0.0
    if gapped:
        out.append(("gapped", f"{plan['symbol']} opened {day_open:,.2f}, up {gap:.1f}% on the prior close — over the plan's "
                              f"{plan['gap_pct']:g}% gap rule. The plan says wait and see if it sells off: watch for a pullback under the open."))
        if price < day_open and price <= plan["max_price"]:
            out.append(("pulled_back", f"{plan['symbol']} is back at {price:,.2f}, under the {day_open:,.2f} open and at or below the plan's "
                                       f"{plan['max_price']:,.2f} — the pullback the plan waited for."))
    elif price <= plan["max_price"]:
        out.append(("at_level", f"{plan['symbol']} is trading at {price:,.2f}, at or below the plan's {plan['max_price']:,.2f} "
                                f"with no gap at the open ({gap:+.1f}%). The plan's buy condition is met."))
    return out


def check(conn, bars_for, prev_close_for, today: str) -> list[dict]:
    """Run every active plan against today's bars; returns alert dicts (kind,
    symbol, message, key) for conditions not yet raised today."""
    ensure_schema(conn)
    out = []
    for plan in active(conn, today):
        bars = bars_for(plan["symbol"])
        if not bars:
            continue
        day_open, price = bars[0][1], bars[-1][4]
        prev = prev_close_for(plan["symbol"])
        for kind, msg in judge(plan, prev, day_open, price):
            if kind in plan["today"]:
                continue
            conn.execute("INSERT OR IGNORE INTO buy_plan_events (plan_id, day, kind, price) VALUES (?,?,?,?)",
                         (plan["id"], today, kind, price))
            out.append({"kind": "plan", "symbol": plan["symbol"], "level": "act", "message": msg,
                        "key": f"plan:{plan['symbol']}:{kind}:{today}", "day": today,
                        "detail": plan.get("note")})
    conn.commit()
    return out
