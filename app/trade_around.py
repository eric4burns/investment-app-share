"""Trading around a core: the tools the third book needs.

    python3 -m app.trade_around IREN

## The idea, in the user's words

"IREN is very volatile and I would like to be able to increase my share
count simply from selling a little when there is a high probability of
going down and then buying back in lower." The core is never sold. A slice
above it is sold into strength and bought back lower, and the measure of
success is shares gained, not the dollar profit of the round trip.

## What this computes

  * **Core and slice.** The core is a share count you set; the slice is
    everything above it, across every account that holds the name.
  * **The two levels**, from the daily verdict: the level to sell the slice
    into (the trim-into level — resistance, an extension, or an overbought
    reading) and the level to buy it back at (the nearest support below).
  * **The odds**, from this name's own history: of the past days on which
    price sat this far below a level above and this far above a level
    below, how often did it reach the lower one first? That is a plain
    first-passage count over the last two years, not a model, and it is
    reported with the number of days it was counted over.
  * **Shares gained** if the round trip completes: the slice sold at the
    upper level and the proceeds spent at the lower one buys more shares
    than were sold by exactly upper/lower − 1.
  * **Where to do it.** A round trip in a Roth, an HSA or a 401(k) has no
    tax and no wash-sale rule. In a taxable account a sale at a gain owes
    tax and a sale at a loss followed by a buy-back inside thirty days is
    disallowed. So the tool says which accounts hold the slice, and prefers
    the tax-advantaged ones; for a taxable lot it names the highest-cost lots
    first, the gain or loss on each, whether it is long-term, and whether a
    buy-back would be a wash sale.
  * **The record**: every past sale in this name followed by a buy within
    sixty days, scored in shares gained or lost.

None of this places a trade. It puts the numbers a decision needs on one
card, and the intraday poll already alerts at both levels.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import books, holdings, performance, prices, verdicts
from .ledger import connect

TAX_FREE = {"tax_free", "hsa", "tax_deferred"}
MIN_BUY_BACK_GAP = 0.30     # the swing the user trades for: a buy-back closer than 30% under the sale is not a round trip
MIN_SWING = 0.30            # a sell level closer than this above price is not a trim worth planning
MIN_BUY_BACK_BELOW_PRICE = 0.10  # a buy-back must sit under today's price by at least this
BUY_BACK_AIM = 0.50              # the buy-back aims at half the sale unless the user names a level
LOOKAHEAD = 60
HISTORY_DAYS = 504          # two years of sessions
ROUND_TRIP_WINDOW = 60
WASH_DAYS = 30


def first_passage(bars: list[dict], up: float, down: float,
                  lookahead: int = LOOKAHEAD, history: int = HISTORY_DAYS) -> dict:
    """Of the last `history` bars, how often did price fall `down` before it
    rose `up` (both fractions of that day's close) within `lookahead` bars."""
    if up <= 0 or down <= 0 or len(bars) < 30:
        return {"down_first": None, "up_first": None, "neither": None, "days": 0}
    closes = [b["close"] for b in bars]
    start = max(0, len(closes) - history - lookahead)
    end = len(closes) - lookahead
    down_first = up_first = neither = 0
    for i in range(start, end):
        base = closes[i]
        hit = None
        for j in range(i + 1, min(len(closes), i + 1 + lookahead)):
            if closes[j] <= base * (1 - down):
                hit = "down"
                break
            if closes[j] >= base * (1 + up):
                hit = "up"
                break
        if hit == "down":
            down_first += 1
        elif hit == "up":
            up_first += 1
        else:
            neither += 1
    n = down_first + up_first + neither
    return {"down_first": (down_first / n) if n else None,
            "up_first": (up_first / n) if n else None,
            "neither": (neither / n) if n else None, "days": n}


def lots_by_account(txns: list[dict], symbol: str, asof: str) -> list[dict]:
    """Open lots of one name, per account, with the account's tax status."""
    out = []
    by_account: dict[str, list[dict]] = defaultdict(list)
    tax: dict[str, str] = {}
    for t in txns:
        if t.get("symbol") == symbol:
            by_account[t["account"]].append(t)
            tax[t["account"]] = t.get("tax_status") or "taxable"
    for account, rows in by_account.items():
        lots, _ = holdings.build_lots(rows, asof)
        ls = lots.get(symbol, [])
        qty = sum(l.qty for l in ls)
        if qty < 0.0005:
            continue
        out.append({"account": account, "tax_status": tax[account],
                    "taxable": tax[account] not in TAX_FREE,
                    "quantity": round(qty, 4),
                    "avg_cost": round(sum(l.qty * l.price for l in ls) / qty, 4) if qty else None,
                    "lots": [{"date": l.date, "qty": round(l.qty, 4), "price": round(l.price, 4)} for l in ls]})
    out.sort(key=lambda a: (a["taxable"], -a["quantity"]))
    return out


def taxable_sale(lots: list[dict], shares: float, at_price: float, asof: str,
                 recent_buys: list[str]) -> dict:
    """Which taxable lots to sell for a slice, highest cost first, and what it costs."""
    remaining, picked = shares, []
    for lot in sorted(lots, key=lambda l: -l["price"]):
        if remaining <= 1e-9:
            break
        take = min(lot["qty"], remaining)
        gain = (at_price - lot["price"]) * take
        held = (date.fromisoformat(asof) - date.fromisoformat(lot["date"])).days
        picked.append({"date": lot["date"], "qty": round(take, 4), "cost": lot["price"],
                       "gain": round(gain, 2), "long_term": held > 365})
        remaining -= take
    loss_lots = [p for p in picked if p["gain"] < 0]
    since = (date.fromisoformat(asof) - timedelta(days=WASH_DAYS)).isoformat()
    bought_recently = [d for d in recent_buys if d >= since]
    wash = bool(loss_lots) and bool(bought_recently)
    return {"lots": picked, "shares": round(shares - max(remaining, 0), 4),
            "gain": round(sum(p["gain"] for p in picked), 2),
            "wash_sale_risk": wash,
            "wash_note": ("some of these lots would be sold at a loss, and shares were bought in the "
                          "last thirty days — that loss is disallowed, and buying back inside thirty "
                          "days would disallow it again" if wash else
                          "a buy-back inside thirty days of a sale AT A LOSS is a wash sale; at a gain "
                          "there is no such rule" if loss_lots else
                          "every lot here is sold at a gain, so no wash-sale rule applies")}


def past_round_trips(txns: list[dict], symbol: str, window: int = ROUND_TRIP_WINDOW) -> list[dict]:
    """Each sale followed by buying within `window` days, scored in shares.

    The shares the proceeds bought back is proceeds / average buy price over
    the window; gained is that less the shares sold. Buys are matched to the
    nearest preceding sale and never counted twice.
    """
    rows = sorted((t for t in txns if t.get("symbol") == symbol and t["kind"] in ("buy", "sell")
                   and t.get("quantity") and t.get("price")), key=lambda t: t["txn_date"])
    used = set()
    out = []
    for i, t in enumerate(rows):
        if t["kind"] != "sell":
            continue
        sold = -t["quantity"]
        proceeds = sold * t["price"]
        limit = (date.fromisoformat(t["txn_date"]) + timedelta(days=window)).isoformat()
        spent = bought = 0.0
        first = last = None
        for j in range(i + 1, len(rows)):
            u = rows[j]
            if u["txn_date"] > limit:
                break
            if u["kind"] != "buy" or j in used:
                continue
            take_dollars = min(u["quantity"] * u["price"], proceeds - spent)
            if take_dollars <= 0:
                break
            used.add(j)
            spent += take_dollars
            bought += take_dollars / u["price"]
            first = first or u["txn_date"]
            last = u["txn_date"]
        if spent <= 0:
            out.append({"sold_on": t["txn_date"], "sold": round(sold, 4), "at": t["price"],
                        "bought_back": 0.0, "gained": None, "note": "not bought back within the window"})
            continue
        out.append({"sold_on": t["txn_date"], "sold": round(sold, 4), "at": t["price"],
                    "bought_back": round(bought, 4), "avg_buy": round(spent / bought, 4),
                    "between": f"{first} to {last}",
                    "gained": round(bought - sold * (spent / proceeds), 4),
                    "note": None})
    return out


def plan(conn, symbol: str, asof: str | None = None) -> dict:
    symbol = symbol.strip().upper()
    asof = asof or date.today().isoformat()
    txns = performance.load_transactions(conn, "1900-01-01", asof, "investment")
    pos = next((p for p in holdings.positions(conn, txns, asof) if p["symbol"] == symbol), None)
    if not pos:
        return {"error": f"{symbol} is not held"}
    books.attach(conn, [pos])
    book = books.lookup(conn).get(symbol) or {}
    qty = pos["quantity"]
    core = book.get("core_shares")
    core_default = core is None
    if core is None:
        core = round(qty * 0.75, 4)
    slice_ = max(0.0, round(qty - core, 4))

    bars, _proxy = prices.analysis_bars(conn, symbol, "2015-01-01", asof)
    bars = [b for b in bars if b["time"] <= asof]
    daily = verdicts.for_symbol(bars, "D", pos, None) if bars else {}
    w = daily.get("watch") or {}
    price = w.get("price") or (bars[-1]["close"] if bars else None)
    stop = w.get("stop_at")
    # The sell level is the ladder's next rung (D69, D72): the one sell rule
    # with a measured record. The verdict's "resistance above" is a level, not
    # a trim (D52), and it was what this card sold into before. The user
    # trades for 30%+ swings on these names, so a level nearer than that is
    # not a trim worth planning either.
    from . import authors, ladder
    entries = ladder.entry_dates(txns)
    lad = ladder.state(bars, entries.get(symbol)) if bars else None
    sell_at, sell_why, next_rung = None, None, None
    if lad:
        r1 = lad["rungs"][0]
        if lad["stage"] == 0 and r1.get("level") and price and r1["level"] / price - 1 >= MIN_SWING:
            sell_at, sell_why = r1["level"], "the ladder's first rung: 60% above the 50-day average"
        elif lad["stage"] == 0 and r1.get("level"):
            sell_at, sell_why = r1["level"], "the ladder's first rung, 60% above the 50-day — nearer than a 30% swing today, so a rung to watch, not a trade to plan"
        else:
            nxt = next((r for r in lad["rungs"] if not r["fired"]), None)
            next_rung = (f"rung {nxt['n']}: {nxt['name']} (weekly RSI now {lad['weekly_rsi']})" if nxt else "the ladder has sold its three rungs on this run")
    if sell_at is None and w.get("trim_at") and price and w["trim_at"] / price - 1 >= MIN_SWING and (w.get("trim_strength") or 0) > 0:
        sell_at, sell_why = w["trim_at"], w.get("trim_why") or "a level price has turned at before, with shown strength"
    # The buy-back: every level named below, and the one chosen is the highest
    # that sits at least 30% under the sale. Named, not measured: no rebuy rule
    # beat holding on more than 19 of 36 names (D69), so these are places to
    # start, with their source, and the decision is the user's.
    named = []
    if price:
        for z in (daily.get("zones") or []):
            if z.get("high") and z["high"] < price:
                named.append({"level": z["high"], "source": "a zone price has turned at (the app)"})
        if stop and stop < price:
            named.append({"level": stop, "source": "the trend-break level (the app)"})
        if w.get("buy_at") and w["buy_at"] < price:
            named.append({"level": w["buy_at"], "source": "the app's buy-at level"})
        try:
            since = (date.fromisoformat(asof) - timedelta(days=180)).isoformat()
            for z in authors.recent(conn, since).get(symbol, []):
                if z["kind"] in ("buy_zone", "downside") and z["lo"] < price:
                    top = max(z["lo"], z["hi"] or z["lo"])
                    if top < price:
                        named.append({"level": top, "source": f"{z['author'].split(' (')[0]}'s {'buy' if z['kind'] == 'buy_zone' else 'downside'} zone ({z['date']})"})
        except Exception:                                      # noqa: BLE001
            pass
        hi52 = max(b["close"] for b in bars[-250:]) if bars else None
        if hi52:
            named.append({"level": round(hi52 * 0.45, 2), "source": "55% off the 52-week high — where IREN's washed-out lows sat (D65)"})
    # One entry per level, the first source named for it kept.
    seen, uniq = set(), []
    for n in sorted(named, key=lambda n: -n["level"]):
        k = round(n["level"], 2)
        if k not in seen and price and n["level"] < price * (1 - MIN_BUY_BACK_BELOW_PRICE):
            seen.add(k); uniq.append(n)
    named = uniq
    # At least 30% under the sale, and at least 10% under today's price — a
    # "buy-back" above where the stock trades now is not one. Among the
    # eligible levels the one NEAREST THE AIM is chosen, not the highest: the
    # aim is half the sale (the user's "sell in the 60s, buy back in the low
    # 30s" on IREN), or the level the user has stated for the name in
    # config.json under buy_back_targets.
    from . import config as _config
    targets = (_config.load().get("buy_back_targets") or {})
    user_aim = targets.get(symbol) or targets.get(symbol.upper())
    aim = float(user_aim) if user_aim else ((sell_at or price or 0) * BUY_BACK_AIM)
    ceiling = (sell_at or price or 0) * (1 - MIN_BUY_BACK_GAP)
    eligible = [n for n in named if n["level"] <= ceiling]
    chosen = min(eligible, key=lambda n: abs(n["level"] - aim)) if eligible else None
    if user_aim and (not chosen or abs(chosen["level"] / aim - 1) > 0.10) and price and aim < price * (1 - MIN_BUY_BACK_BELOW_PRICE):
        chosen = {"level": round(aim, 2), "source": "your stated buy-back for this name (config.json, buy_back_targets)"}
        named.append(chosen); named.sort(key=lambda n: -n["level"])
    buy_back = chosen["level"] if chosen else None
    buy_why = chosen["source"] if chosen else None
    buy_aim = round(aim, 2) if aim else None

    odds = None
    if price and sell_at and buy_back and sell_at > price > buy_back:
        odds = first_passage(bars, sell_at / price - 1, 1 - buy_back / price)
    gained = None
    if sell_at and buy_back and slice_ > 0:
        gained = round(slice_ * (sell_at / buy_back - 1), 4)

    accounts = lots_by_account(txns, symbol, asof)
    tax_free_shares = sum(a["quantity"] for a in accounts if not a["taxable"])
    taxable_shares = sum(a["quantity"] for a in accounts if a["taxable"])
    # Where to take the slice from: tax-advantaged accounts first.
    taxable_needed = max(0.0, slice_ - tax_free_shares)
    recent_buys = [t["txn_date"] for t in txns if t.get("symbol") == symbol and t["kind"] == "buy"]
    taxable_plan = None
    if taxable_needed > 0 and sell_at:
        lots = [l for a in accounts if a["taxable"] for l in a["lots"]]
        taxable_plan = taxable_sale(lots, taxable_needed, sell_at, asof, recent_buys)

    return {
        "symbol": symbol, "asof": asof, "price": price,
        "book": book.get("book"), "trade_around": book.get("trade_around"),
        "quantity": qty, "core": core, "core_default": core_default, "slice": slice_,
        "sell_at": sell_at, "buy_back": buy_back, "stop": stop,
        "sell_why": sell_why, "buy_why": buy_why, "buy_aim": buy_aim, "next_rung": next_rung, "named": named,
        "ladder_stage": lad["stage"] if lad else None,
        "sell_pct": round((sell_at / price - 1) * 100, 1) if sell_at and price else None,
        "buy_pct": round((buy_back / price - 1) * 100, 1) if buy_back and price else None,
        "odds": odds, "shares_gained": gained,
        "gained_pct": round((sell_at / buy_back - 1) * 100, 1) if sell_at and buy_back else None,
        "accounts": accounts,
        "tax_free_shares": round(tax_free_shares, 4), "taxable_shares": round(taxable_shares, 4),
        "taxable_needed": round(taxable_needed, 4), "taxable_plan": taxable_plan,
        "past": past_round_trips(txns, symbol),
        "daily_verdict": daily.get("verdict"),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.trade_around")
    p.add_argument("symbol")
    args = p.parse_args(argv)
    r = plan(connect(), args.symbol)
    if r.get("error"):
        print(r["error"]); return 1
    print(f"{r['symbol']} at {r['price']:,.2f}: {r['quantity']:,.2f} shares, core {r['core']:,.2f}"
          f"{' (default: three quarters)' if r['core_default'] else ''}, slice {r['slice']:,.2f}")
    if r["sell_at"] and r["buy_back"]:
        print(f"  sell the slice into {r['sell_at']:,.2f} ({r['sell_pct']:+.1f}%), buy back at "
              f"{r['buy_back']:,.2f} ({r['buy_pct']:+.1f}%): +{r['shares_gained']:,.2f} shares "
              f"(+{r['gained_pct']:.1f}%) if it completes")
        if r["odds"] and r["odds"]["days"]:
            o = r["odds"]
            print(f"  over the last {o['days']} sessions, from a spot like this price reached the lower "
                  f"level first {o['down_first']*100:.0f}% of the time, the upper first "
                  f"{o['up_first']*100:.0f}%, neither within {LOOKAHEAD} days {o['neither']*100:.0f}%")
    else:
        print("  the daily call names no upper or lower level to trade between today")
    print(f"  tax-free shares {r['tax_free_shares']:,.2f}, taxable {r['taxable_shares']:,.2f}")
    for a in r["accounts"]:
        print(f"    {a['account']:<28} {a['tax_status']:<13} {a['quantity']:>10,.2f} @ {a['avg_cost']:,.2f}")
    if r["taxable_plan"]:
        tp = r["taxable_plan"]
        print(f"  the slice needs {r['taxable_needed']:,.2f} taxable shares: {tp['note'] if 'note' in tp else ''}"
              f"gain {tp['gain']:+,.0f}; {tp['wash_note']}")
    if r["past"]:
        print("  past round trips:")
        for t in r["past"][-8:]:
            print(f"    sold {t['sold']:,.2f} on {t['sold_on']} at {t['at']:,.2f}: "
                  + (f"bought back {t['bought_back']:,.2f} ({t['between']}), {t['gained']:+,.2f} shares"
                     if t["gained"] is not None else t["note"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
