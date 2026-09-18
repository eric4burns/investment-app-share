"""Buying back: the readings that decide a rebuy, on the names it applies to.

The sell side has a measured ladder (D69, D72). The buy-back side does not:
no written rebuy rule beat holding on more than 19 of 36 names (D69), so
this is a decision screen, not a trigger. For every name the user has sold
out of, or sold part of, in the last year — and every held name whose ladder
has sold a rung — it puts the readings that measured best side by side, with
what each has meant on the record, and says in words which are there and
which are not. The decision stays with the user.

Readings, and where each comes from:
  drawdown        close against the 52-week high. IREN's washed-out lows sat
                  55–66% down (research/audits/anatomy-IREN-2026-09-05.md).
  weekly floor    weekly Williams %R (14) at -97 or under, 40%+ off the high.
                  On IREN since 2023 every such reading was within 8% of a low
                  that then rallied 81–590%; in the 2022 collapse it fired
                  three times and kept falling (sweep-IREN-2026-09-05.md).
  confirmed       the first weekly close above the prior week's high after a
                  floor reading — the variant that waits for the turn.
  under the sale  price against the user's own last sale on the name: buying
                  back 30% under the sale kept more shares on 9 of 36 (D69).
  authors' zones  the buy and downside zones the followed authors have named
                  on the name (D68), with price against them.
  wash window     a loss sale inside 30 days (D70).
"""
from __future__ import annotations

from datetime import date, timedelta

from . import authors, indicators as I, ladder, prices, washsales

FLOOR = -97.0
FLOOR_DRAWDOWN = -0.40
WASHED_OUT = -0.55
UNDER_SALE = -0.30
LOOKBACK_DAYS = 365
CONFIRM_WEEKS = 8

STATES = ["floor, confirmed", "at the floor", "washed out", "in a followed zone", "under your sale", "not yet"]


def sales(txns: list[dict], since: str, asof: str) -> dict[str, dict]:
    """Per symbol: the last sale in the window, the shares sold, whether the
    position is now flat, and the average sale price of that last day."""
    from .holdings import ACQUIRE, DISPOSE, apply_reorganisations
    qty: dict[str, float] = {}
    last: dict[str, dict] = {}
    for t in sorted(apply_reorganisations(txns), key=lambda x: x["txn_date"]):
        s = t.get("symbol")
        if not s or not t.get("quantity") or t.get("kind") not in ACQUIRE | DISPOSE or t["txn_date"] > asof:
            continue
        qty[s] = qty.get(s, 0.0) + t["quantity"]
        if t["quantity"] < 0 and t["txn_date"] >= since and t.get("price"):
            l = last.get(s)
            if l and l["date"] == t["txn_date"]:
                l["shares"] += -t["quantity"]; l["proceeds"] += -t["quantity"] * t["price"]
            else:
                last[s] = {"date": t["txn_date"], "shares": -t["quantity"], "proceeds": -t["quantity"] * t["price"]}
    out = {}
    for s, l in last.items():
        out[s] = {"date": l["date"], "shares": round(l["shares"], 4), "price": round(l["proceeds"] / l["shares"], 4),
                  "flat": abs(qty.get(s, 0.0)) < 1e-9, "held": round(qty.get(s, 0.0), 4)}
    return out


def readings(bars: list[dict]) -> dict | None:
    if len(bars) < 80:
        return None
    closes = [b["close"] for b in bars]
    price = closes[-1]
    hi52 = max(closes[-250:])
    weekly = I.resample(bars, "W")
    wr = I.williams_r(weekly, 14, 0.0, -100.0)
    w_rsi = I.rsi(weekly, 14)
    # weekly readings on completed weeks; the newest candle is the week in progress unless it closed on a Friday
    y, m, d = (int(x) for x in bars[-1]["time"].split("-"))
    partial = date(y, m, d).weekday() != 4
    done = wr[:-1] if partial and len(wr) > 1 else wr
    wr_now = wr[-1]["value"] if wr and wr[-1]["value"] is not None else None
    wr_done = done[-1]["value"] if done and done[-1]["value"] is not None else None
    # the last floor reading on a completed week, and whether a weekly close has since cleared the prior week's high
    floor_at, confirmed_at = None, None
    dd_at = {}
    wr_by_time = {x["time"]: x["value"] for x in wr}
    for k in range(len(weekly) - (1 if partial else 0)):
        v = wr_by_time.get(weekly[k]["time"])
        if v is None:
            continue
        wk_close = weekly[k]["close"]
        hi_so_far = max(x["close"] for x in weekly[max(0, k - 52):k + 1])
        if v <= FLOOR and wk_close / hi_so_far - 1 <= FLOOR_DRAWDOWN:
            floor_at, confirmed_at = weekly[k]["time"], None
        elif floor_at and confirmed_at is None and k >= 1 and wk_close > weekly[k - 1]["high"]:
            confirmed_at = weekly[k]["time"]
    weeks_since_floor = None
    if floor_at:
        fy, fm, fd = (int(x) for x in floor_at.split("-"))
        weeks_since_floor = (date(y, m, d) - date(fy, fm, fd)).days // 7
    return {"price": price, "hi52": hi52, "drawdown": round(price / hi52 - 1, 4),
            "wr_now": round(wr_now, 1) if wr_now is not None else None,
            "wr_done": round(wr_done, 1) if wr_done is not None else None,
            "weekly_rsi": round(w_rsi[-1]["value"], 1) if w_rsi and w_rsi[-1]["value"] is not None else None,
            "floor_at": floor_at, "weeks_since_floor": weeks_since_floor,
            "confirmed_at": confirmed_at if weeks_since_floor is not None and weeks_since_floor <= CONFIRM_WEEKS else None,
            "floor_recent": weeks_since_floor is not None and weeks_since_floor <= CONFIRM_WEEKS}


def zones_for(levels: list[dict], price: float) -> list[dict]:
    out = []
    for z in levels:
        if z["kind"] not in ("buy_zone", "downside"):
            continue
        lo, hi = z["lo"], z["hi"] or z["lo"]
        lo, hi = min(lo, hi), max(lo, hi)
        inside = lo * 0.98 <= price <= hi * 1.02
        out.append({"author": z["author"].split(" (")[0], "date": z["date"], "kind": "buy zone" if z["kind"] == "buy_zone" else "downside zone",
                    "lo": lo, "hi": hi, "inside": inside, "distance": round(lo / price - 1, 4), "note": (z["note"] or "")[:140]})
    return out


def judge(r: dict, sale: dict | None, zones: list[dict]) -> tuple[str, list[str], list[str]]:
    """The state in words, the readings that are there, and the ones that are not."""
    have, missing = [], []
    dd = r["drawdown"]
    if r["confirmed_at"]:
        have.append(f"Weekly Williams %R hit the floor {r['floor_at']} and the week of {r['confirmed_at']} closed above the prior week's high — the confirmed turn.")
    elif r["floor_recent"]:
        have.append(f"Weekly Williams %R at the floor ({r['wr_done']}) {r['weeks_since_floor']} week{'s' if r['weeks_since_floor'] != 1 else ''} ago, {dd*100:+.0f}% from the 52-week high. On IREN since 2023 every such reading was within 8% of a low; in 2022 it fired three times and kept falling.")
    else:
        missing.append(f"no weekly Williams floor: it reads {r['wr_done'] if r['wr_done'] is not None else '—'} on the last closed week (floor is −97 with 40%+ off the high).")
    if dd <= WASHED_OUT:
        have.append(f"{dd*100:+.0f}% from its 52-week high of {r['hi52']:.2f} — washed out on the IREN yardstick (its lows sat 55–66% down).")
    elif dd <= FLOOR_DRAWDOWN:
        have.append(f"{dd*100:+.0f}% from its 52-week high of {r['hi52']:.2f}.")
    else:
        missing.append(f"only {dd*100:+.0f}% from its 52-week high of {r['hi52']:.2f}; the washed-out lows were 55%+ down.")
    inside = [z for z in zones if z["inside"]]
    below = sorted([z for z in zones if not z["inside"] and z["distance"] < 0], key=lambda z: -z["distance"])
    if inside:
        z = inside[0]
        have.append(f"Inside {z['author']}'s {z['kind']} {z['lo']:.2f}–{z['hi']:.2f} ({z['date']}).")
    elif below:
        z = below[0]
        missing.append(f"{z['author']}'s {z['kind']} is {z['lo']:.2f}–{z['hi']:.2f}, {z['distance']*100:+.0f}% below here.")
    if sale:
        rel = r["price"] / sale["price"] - 1
        if rel <= UNDER_SALE:
            have.append(f"{rel*100:+.0f}% under your last sale at {sale['price']:.2f} on {sale['date']} — the 30%-under rule kept more shares on 9 of 36 names, so this alone is weak.")
        else:
            missing.append(f"{rel*100:+.0f}% against your last sale at {sale['price']:.2f} on {sale['date']}; 30% under would be {sale['price']*(1+UNDER_SALE):.2f}.")
    if r["confirmed_at"]:
        state = STATES[0]
    elif r["floor_recent"]:
        state = STATES[1]
    elif dd <= WASHED_OUT:
        state = STATES[2]
    elif inside:
        state = STATES[3]
    elif sale and r["price"] / sale["price"] - 1 <= UNDER_SALE:
        state = STATES[4]
    else:
        state = STATES[5]
    return state, have, missing


def screen(conn, txns: list[dict], asof: str, watch: list[str] | None = None) -> dict:
    since = (date.fromisoformat(asof) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    sold = sales(txns, since, asof)
    entries = ladder.entry_dates(txns)
    try:
        wash = washsales.rebuy_warnings(conn, txns, asof)
    except Exception:                                          # noqa: BLE001
        wash = {}
    author_levels = authors.recent(conn, (date.fromisoformat(asof) - timedelta(days=180)).isoformat(), per_symbol=12)
    names = set(sold) | set(watch or [])
    rows = []
    for sym in sorted(names):
        if sym.startswith("PLAN") or len(sym) > 8:
            continue
        try:
            bars, _proxy = prices.analysis_bars(conn, sym, "2015-01-01", asof)
        except Exception:                                      # noqa: BLE001
            continue
        r = readings(bars)
        if not r:
            continue
        sale = sold.get(sym)
        zones = zones_for(author_levels.get(sym, []), r["price"])
        lad = ladder.state(bars, entries.get(sym)) if sale and not sale["flat"] else None
        state, have, missing = judge(r, sale, zones)
        w = wash.get(sym)
        if w:
            have.append(f"WASH WINDOW: sold at a loss {w['date']}; buying back before {w['window_closes']} disallows it ({w['days_left']} days).")
        rows.append({"symbol": sym, "state": state, "rank": STATES.index(state), "have": have, "missing": missing,
                     "readings": r, "sale": sale, "zones": zones, "wash": w,
                     "ladder": ({"stage": lad["stage"], "summary": ladder.summary(lad)} if lad else None),
                     "why_here": ("sold out" if sale and sale["flat"] else "sold part" if sale else "watchlist")})
    rows.sort(key=lambda x: (x["rank"], x["readings"]["drawdown"]))
    return {"asof": asof, "since": since, "rows": rows,
            "note": ("No written rebuy rule beat holding on more than 19 of 36 names (D69): the floor kept more shares on 19, a 55% drawdown "
                     "on 15, a confirmed floor on 11, 30% under the sale on 9. The readings are here so the decision can be made with them; "
                     "the decision is yours.")}
