"""The sell ladder and the floor rebuy, read off IREN's anatomy, tested on
IREN and on high-beta names they were NOT read from.

Rules (research/audits/sweep-IREN-2026-09-05.md):

  sell ladder   half the position is a core that is never sold; the other half
                is sold in thirds — a third when price closes 60% or more above
                its 50-day average, a third when the weekly RSI (14) reaches
                85, the rest when the weekly RSI, having been 80 or more in the
                last eight weeks, closes back under 70.
  floor rebuy   all cash goes back in when the weekly Williams %R (14) is at
                -97 or under AND price is 40% or more below its 52-week high.
                Variant "confirmed" waits for the first weekly close above the
                prior week's high after that.

Scored on shares at the end against holding 1,000, plus how many sells fell
within 25% of a real top and how many rebuys within 15% of a real bottom
(turns by zigzag, 40% / 60%). Closes only, no costs or tax.

    python3 research/ladder-study.py [--md out.md]
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import indicators as I, ledger, prices  # noqa: E402

START = "2022-01-01"
DERIVED_FROM = ["IREN"]
NAMES = ["IREN", "CIFR", "SIVE.ST", "MSTR", "COIN", "HOOD", "PLTR", "SMCI", "MARA", "RIOT", "CLSK", "WULF",
         "HUT", "TSLA", "NVDA", "AMD", "SOFI", "RKLB", "ASTS", "APLD", "BE", "IONQ", "RGTI", "UPST", "AFRM",
         "SOUN", "BBAI", "LUNR", "RDW", "OKLO", "SMR", "NNE", "CRWV", "NBIS", "TEM", "HIMS", "OSCR", "ZETA"]


def zigzag(closes, drop=0.40, rise=0.60):
    tops, bottoms, mode, ext = [], [], None, 0
    for i in range(1, len(closes)):
        c = closes[i]
        if mode in (None, "up"):
            if c > closes[ext]:
                ext = i
            elif c <= closes[ext] * (1 - drop):
                tops.append(ext); mode, ext = "down", i
        if mode == "down":
            if c < closes[ext]:
                ext = i
            elif c >= closes[ext] * (1 + rise):
                bottoms.append(ext); mode, ext = "up", i
    return tops, bottoms


def run(bars, confirmed=False, rebuy="floor"):
    closes = [b["close"] for b in bars]
    n = len(bars)
    sma50 = {x["time"]: x["value"] for x in I.sma(bars, 50)}
    weekly = I.resample(bars, "W")
    w_rsi = {x["time"]: x["value"] for x in I.rsi(weekly, 14)}
    w_wr = {x["time"]: x["value"] for x in I.williams_r(weekly, 14, 0.0, -100.0)}
    widx = {w["time"]: k for k, w in enumerate(weekly)}
    # the weekly reading that applies on any day: the last completed week's
    wk_of_day, j = {}, 0
    for b in bars:
        while j + 1 < len(weekly) and weekly[j + 1]["time"] <= b["time"]:
            j += 1
        wk_of_day[b["time"]] = j
    core, slice_, cash = 500.0, 500.0, 0.0
    stage = 0          # 0 none sold, 1 first third, 2 second third, 3 all
    log = []
    waiting_confirm = False
    for i in range(60, n):
        b = bars[i]; c = closes[i]; k = wk_of_day[b["time"]]
        wt = weekly[k]["time"]
        rsi_now = w_rsi.get(wt); wr_now = w_wr.get(wt)
        recent = [w_rsi.get(weekly[q]["time"]) for q in range(max(0, k - 8), k)]
        recent = [x for x in recent if x is not None]
        m50 = sma50.get(b["time"])
        hi52 = max(closes[max(0, i - 250):i + 1])
        # ---- sells, in order, only while the slice has shares ----
        if slice_ > 0:
            sold = None
            if stage == 0 and m50 and c / m50 - 1 >= 0.60:
                sold = ("a third: 60% above the 50-day", slice_ / 3)
            elif stage == 1 and rsi_now is not None and rsi_now >= 85:
                sold = ("a third: weekly RSI 85", slice_ / 2)
            elif stage in (1, 2) and rsi_now is not None and recent and max(recent) >= 80 and rsi_now < 70:
                sold = ("the rest: weekly RSI back under 70 after 80+", slice_)
            elif stage == 0 and rsi_now is not None and recent and max(recent) >= 80 and rsi_now < 70:
                sold = ("all at once: weekly RSI back under 70 after 80+ (ladder never started)", slice_)
            if sold:
                why, qty = sold
                cash += qty * c; slice_ -= qty; stage = 3 if slice_ <= 1e-9 else stage + 1
                log.append((b["time"], "sell", round(qty, 1), c, why))
        # ---- rebuy ----
        if cash > 0:
            floor = wr_now is not None and wr_now <= -97 and c / hi52 - 1 <= -0.40
            if rebuy == "drawdown":
                floor = c / hi52 - 1 <= -0.55
            elif rebuy == "below_sale":
                sold_px = [x[3] for x in log if x[1] == "sell"]
                avg_sale = sum(sold_px) / len(sold_px) if sold_px else None
                floor = avg_sale is not None and c <= avg_sale * 0.70
            if floor and not confirmed:
                qty = cash / c; slice_ += qty; cash = 0.0; stage = 0
                log.append((b["time"], "buy", round(qty, 1), c, "weekly Williams %R at the floor, 40%+ off the high"))
            elif floor:
                waiting_confirm = True
            elif waiting_confirm and weekly[k]["time"] == b["time"] and k >= 1:
                w, pw = weekly[k], weekly[k - 1]
                if w["close"] > pw["high"]:
                    qty = cash / c; slice_ += qty; cash = 0.0; stage = 0; waiting_confirm = False
                    log.append((b["time"], "buy", round(qty, 1), c, "first weekly close over the prior week's high after the floor"))
    tops, bottoms = zigzag(closes)
    def near(i_, turns, tol):
        return any(abs(closes[i_] / closes[t] - 1) <= tol for t in turns)
    idx = {b["time"]: i for i, b in enumerate(bars)}
    sells = [x for x in log if x[1] == "sell"]; buys = [x for x in log if x[1] == "buy"]
    good_sells = sum(1 for x in sells if near(idx[x[0]], tops, 0.25))
    good_buys = sum(1 for x in buys if near(idx[x[0]], bottoms, 0.15))
    end = closes[-1]
    return {"shares": core + slice_, "cash": cash, "value": (core + slice_) * end + cash, "hold": 1000 * end,
            "sells": len(sells), "good_sells": good_sells, "buys": len(buys), "good_buys": good_buys,
            "tops": len(tops), "bottoms": len(bottoms), "log": log}


def main():
    conn = ledger.connect()
    today = datetime.date.today().isoformat()
    L = ["# The sell ladder and the floor rebuy — 2026-09-05", "",
         "Read off IREN's own anatomy, then run on IREN and on high-beta names it was not read from. Half the position is a core never sold; "
         "the other half is sold in thirds up the ladder and bought back at the weekly Williams %R floor. 1,000 shares at the start, closes only, "
         "no costs or tax. **Shares** against 1,000 is the number that matters; a sell 'near a top' is within 25% of a zigzag top, a buy 'near a bottom' within 15%.", "",
         "| Name | Shares (floor rebuy) | vs hold | Shares (confirmed) | vs hold | Shares (rebuy 55% off the high) | vs hold | Shares (rebuy 30% under the sale) | vs hold | Sells near a top | Floor rebuys near a bottom | Cash idle (floor) |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    agg = {"in": [], "out": []}
    for sym in NAMES:
        s = prices.load_series(conn, sym)
        if len(s) < 700:
            prices.ensure_symbol(conn, sym, "2018-01-01", today, as_equity=True); conn.commit()
            prices.invalidate_series_cache(conn, sym)
        bars = [b for b in prices.load_bars(conn, sym, "2015-01-01", today) if b["time"] >= START]
        if len(bars) < 500:
            L.append(f"| {sym} | — | only {len(bars)} bars since {START} | | | | | |"); continue
        a = run(bars, confirmed=False); b = run(bars, confirmed=True)
        dd = run(bars, rebuy="drawdown"); bs = run(bars, rebuy="below_sale")
        tag = " (derived from)" if sym in DERIVED_FROM else ""
        L.append(f"| {sym}{tag} | {a['shares']:,.0f} | {(a['value']/a['hold']-1)*100:+.0f}% | {b['shares']:,.0f} | {(b['value']/b['hold']-1)*100:+.0f}% | "
                 f"{dd['shares']:,.0f} | {(dd['value']/dd['hold']-1)*100:+.0f}% | {bs['shares']:,.0f} | {(bs['value']/bs['hold']-1)*100:+.0f}% | "
                 f"{a['good_sells']} of {a['sells']} | {a['good_buys']} of {a['buys']} | ${a['cash']:,.0f} |")
        agg["in" if sym in DERIVED_FROM else "out"].append({"floor": a, "confirmed": b, "drawdown": dd, "below_sale": bs})
        if sym in ("IREN", "CIFR", "SIVE.ST", "MSTR", "COIN"):
            L.append(f"<!-- {sym} log -->")
            for d, side, q, px, why in a["log"][-12:]:
                L.append(f"<!--   {d} {side} {q:,.0f} @ {px:.2f}: {why} -->")
    out = agg["out"]
    if out:
        med = lambda xs: sorted(xs)[len(xs) // 2]
        L += ["", f"**Out of sample, {len(out)} names not used to derive the rules** (more shares than holding / median value against hold):", ""]
        for key, label in (("floor", "floor rebuy"), ("confirmed", "confirmed rebuy"), ("drawdown", "rebuy 55% off the high"), ("below_sale", "rebuy 30% under the sale")):
            L.append(f"- {label}: {sum(1 for x in out if x[key]['shares'] >= 1000)} of {len(out)}, median {med([x[key]['value']/x[key]['hold']-1 for x in out])*100:+.0f}%")
        sells = sum(x["floor"]["sells"] for x in out); good = sum(x["floor"]["good_sells"] for x in out)
        L.append(f"- the sell ladder itself: {good} of {sells} sells within 25% of a real top ({good/max(1,sells)*100:.0f}%)")
    text = "\n".join(L)
    print("\n".join(l for l in L if not l.startswith("<!--")))
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(text + "\n")


if __name__ == "__main__":
    main()
