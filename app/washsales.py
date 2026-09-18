"""Wash sales: losses the IRS will not let you take, and the windows to avoid.

A loss on a sale is disallowed when the same security is bought within 30
days before or after the sale (61 days in all). The disallowed loss is not
lost — it is added to the basis of the replacement shares — but it is not
deductible this year, and a swing trader who trims a loser and re-enters two
weeks later does this without noticing.

Two answers here, both from the ledger's own transactions:

  past     every loss sale that had a purchase of the same symbol inside the
           window, with the loss that was disallowed (to the extent of the
           replacement shares, which is how the rule applies).
  windows  what is live right now: symbols sold at a loss in the last 30 days
           (buying them back before the window closes disallows that loss),
           and symbols bought in the last 30 days that now show a loss
           (selling them now, then buying back inside 30 days, would too).

The rule also covers "substantially identical" securities, options and
purchases in another account including an IRA. None of that is visible here
beyond the accounts in the ledger, so the count is a floor, and says so.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

WINDOW_DAYS = 30

ACQUIRE = {"buy", "reinvest", "transfer_in"}
DISPOSE = {"sell", "transfer_out"}


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def loss_sales(txns: list[dict]) -> list[dict]:
    """FIFO-matched sales that realised a loss, one row per sale."""
    lots: dict[str, list[list]] = defaultdict(list)   # [date, qty, price]
    out = []
    for t in sorted(txns, key=lambda x: x["txn_date"]):
        sym, qty, kind, price = t.get("symbol"), t.get("quantity") or 0, t.get("kind"), t.get("price") or 0.0
        if not sym or not qty:
            continue
        if kind in ACQUIRE or (kind == "corporate_action" and qty > 0):
            lots[sym].append([t["txn_date"], qty, price])
        elif kind in DISPOSE or (kind == "corporate_action" and qty < 0):
            remaining, exit_price, cost = -qty, price, 0.0
            sold = 0.0
            while remaining > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                take = min(lot[1], remaining)
                cost += take * lot[2]
                sold += take
                lot[1] -= take
                remaining -= take
                if lot[1] <= 1e-9:
                    lots[sym].pop(0)
            if sold > 0 and exit_price > 0 and cost > 0:
                loss = sold * exit_price - cost
                if loss < 0:
                    out.append({"symbol": sym, "date": t["txn_date"][:10], "quantity": round(sold, 4),
                                "proceeds": round(sold * exit_price, 2), "cost": round(cost, 2),
                                "loss": round(loss, 2), "account": t.get("account")})
    return out


def past(txns: list[dict]) -> list[dict]:
    """Loss sales with a same-symbol purchase inside the 61-day window.

    A replacement is a purchase whose shares are still held after the sale —
    the shares sold cannot replace themselves. A buy in the thirty days
    before the sale counts only as far as the position kept those shares;
    a buy in the thirty days after counts once, across sales, until its
    shares are used up. The earlier version counted every buy in the window
    in full, so a lot bought and sold whole within a month, nothing rebought,
    showed as a wash of its entire loss."""
    from .holdings import apply_reorganisations
    txns = sorted(apply_reorganisations(txns), key=lambda t: t.get("txn_date") or "")
    buys: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        if t.get("symbol") and (t.get("kind") in ACQUIRE) and (t.get("quantity") or 0) > 0:
            buys[t["symbol"]].append({"date": t["txn_date"][:10], "quantity": float(t["quantity"]), "left": float(t["quantity"])})
    # position after each day, per symbol, to know how many shares stayed held
    held_after: dict[tuple, float] = {}
    pos: dict[str, float] = defaultdict(float)
    for t in txns:
        sym = t.get("symbol")
        if not sym or not t.get("quantity") or t.get("kind") not in ACQUIRE | DISPOSE:
            continue
        pos[sym] += float(t["quantity"])
        held_after[(sym, t["txn_date"][:10])] = pos[sym]
    out = []
    for s in sorted(loss_sales(txns), key=lambda r: r["date"]):
        d = _d(s["date"])
        sym = s["symbol"]
        remaining = max(0.0, held_after.get((sym, s["date"]), 0.0))
        before = [b for b in buys[sym] if 0 < (d - _d(b["date"])).days <= WINDOW_DAYS]
        after = [b for b in buys[sym] if 0 < (_d(b["date"]) - d).days <= WINDOW_DAYS]
        replaced, dates = 0.0, set()
        # earlier buys: only the shares that survived the sale, newest first
        budget = remaining
        for b in sorted(before, key=lambda b: b["date"], reverse=True):
            take = min(b["quantity"], budget)
            if take > 1e-9:
                replaced += take; dates.add(b["date"]); budget -= take
        # later buys: each share replaces once
        need = max(0.0, s["quantity"] - replaced)
        for b in after:
            take = min(b["left"], need)
            if take > 1e-9:
                replaced += take; b["left"] -= take; need -= take; dates.add(b["date"])
        if replaced <= 1e-9:
            continue
        share = min(1.0, replaced / s["quantity"]) if s["quantity"] else 1.0
        out.append({**s, "replacement_shares": round(replaced, 4),
                    "replacement_dates": sorted(dates),
                    "disallowed": round(s["loss"] * share, 2),
                    "partial": share < 1.0 - 1e-6})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def windows(txns: list[dict], prices: dict[str, float], asof: str) -> dict:
    """What is live: loss sales still inside their window, and recent buys underwater."""
    today = _d(asof)
    recent_loss = []
    for s in loss_sales(txns):
        days = (today - _d(s["date"])).days
        if 0 <= days <= WINDOW_DAYS:
            recent_loss.append({**s, "window_closes": (_d(s["date"]) + timedelta(days=WINDOW_DAYS + 1)).isoformat(),
                                "days_left": WINDOW_DAYS - days})
    recent_buys = []
    for t in txns:
        if t.get("symbol") and t.get("kind") in ACQUIRE and (t.get("quantity") or 0) > 0:
            days = (today - _d(t["txn_date"])).days
            px = prices.get(t["symbol"])
            if 0 <= days <= WINDOW_DAYS and px and (t.get("price") or 0) > px:
                recent_buys.append({"symbol": t["symbol"], "date": t["txn_date"][:10],
                                    "quantity": t["quantity"], "price": t["price"], "now": px,
                                    "unrealised": round((px - t["price"]) * t["quantity"], 2),
                                    "window_closes": (_d(t["txn_date"]) + timedelta(days=WINDOW_DAYS + 1)).isoformat()})
    recent_loss.sort(key=lambda r: r["days_left"])
    recent_buys.sort(key=lambda r: r["unrealised"])
    return {"do_not_rebuy": recent_loss, "underwater_recent_buys": recent_buys,
            "note": ("Counted from the accounts in this ledger only. The rule also reaches "
                     "substantially identical securities, options, and purchases in any other "
                     "account including an IRA, so this is a floor, not the whole answer.")}


def email_windows(conn, asof: str) -> list[dict]:
    """Sales seen only in Fidelity's confirmation emails, inside the window.

    The email carries no shares and no cost, so whether the sale was a loss
    is not known until the statement lands; until then it is a POSSIBLE wash
    window, and the warning says so."""
    from . import mailtrades
    out = []
    today = _d(asof)
    try:
        rows = mailtrades.recent(conn, days=WINDOW_DAYS + 1)
    except Exception:                                          # noqa: BLE001
        return out
    for r in rows:
        if r.get("action") != "sell" or r.get("confirmed") or not r.get("symbol"):
            continue
        days = (today - _d(r["trade_date"])).days
        if 0 <= days <= WINDOW_DAYS:
            out.append({"symbol": r["symbol"], "date": r["trade_date"], "price": r.get("price"),
                        "window_closes": (_d(r["trade_date"]) + timedelta(days=WINDOW_DAYS + 1)).isoformat(),
                        "days_left": WINDOW_DAYS - days, "possible": True})
    return out


def rebuy_warnings(conn, txns: list[dict], asof: str) -> dict[str, dict]:
    """symbol -> the warning to show beside a buy or add on that name.

    A loss sale in the last 30 days from the ledger is a certain wash if
    bought back; a sale seen only in an email is a possible one."""
    out: dict[str, dict] = {}
    for r in loss_sales(txns):
        days = (_d(asof) - _d(r["date"])).days
        if 0 <= days <= WINDOW_DAYS:
            cur = out.get(r["symbol"])
            if not cur or r["date"] > cur["date"]:
                out[r["symbol"]] = {"date": r["date"], "loss": r["loss"], "quantity": r["quantity"],
                                    "window_closes": (_d(r["date"]) + timedelta(days=WINDOW_DAYS + 1)).isoformat(),
                                    "days_left": WINDOW_DAYS - days, "possible": False}
    for e in email_windows(conn, asof):
        if e["symbol"] not in out:
            out[e["symbol"]] = {"date": e["date"], "loss": None, "quantity": None, "window_closes": e["window_closes"],
                                "days_left": e["days_left"], "possible": True, "price": e.get("price")}
    return out


def report(txns: list[dict], prices: dict[str, float], asof: str) -> dict:
    p = past(txns)
    return {"past": p, "disallowed_total": round(sum(r["disallowed"] for r in p), 2),
            "windows": windows(txns, prices, asof), "window_days": WINDOW_DAYS}
