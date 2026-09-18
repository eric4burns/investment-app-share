"""What the tops and the washed-out lows of a name actually looked like.

Not a rule menu. For one name: find the real peaks (a high followed by a fall
of at least 40%) and the real troughs (a low followed by a rise of at least
60%), print the state of the tape at each — how far above its averages, the
weekly RSI, the run into it, the drawdown into it, volume — and then, for a
set of candidate top and bottom signals, count on THIS name's own history how
many times each fired, how many of those firings were within reach of a real
turn, and how many were false alarms. Precision on the name is the number the
user needs: a signal that fired at the top and forty other times is useless.

    python3 research/anatomy.py IREN [--md out.md]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import indicators as I, ledger, prices  # noqa: E402

TOP_DROP, BOTTOM_RISE = 0.40, 0.60
NEAR_TOP, NEAR_BOTTOM = 0.15, 0.20    # a signal "near" a turn: within this of the extreme price
WINDOW = 40                            # ...and within this many sessions of it


def turns(bars):
    """Zigzag: a top is a high that the next decline undoes by TOP_DROP; a
    bottom is a low that the next rise undoes by BOTTOM_RISE. Alternating."""
    closes = [b["close"] for b in bars]
    tops, bottoms = [], []
    mode, ext_i = None, 0            # mode: "up" while tracking a running high
    for i in range(1, len(closes)):
        c = closes[i]
        if mode in (None, "up"):
            if c > closes[ext_i]:
                ext_i = i
            elif c <= closes[ext_i] * (1 - TOP_DROP):
                if mode == "up" or tops or bottoms or True:
                    tops.append(ext_i)
                mode, ext_i = "down", i
        if mode == "down":
            if c < closes[ext_i]:
                ext_i = i
            elif c >= closes[ext_i] * (1 + BOTTOM_RISE):
                bottoms.append(ext_i)
                mode, ext_i = "up", i
    return tops, bottoms


def state(bars, i, weekly, wk_of_day, w_rsi, w_sma10, sma20, sma50, sma200, rsi14):
    b = bars[i]
    c = b["close"]
    k = wk_of_day[b["time"]]
    lo52 = min(x["close"] for x in bars[max(0, i - 250):i + 1]); hi52 = max(x["close"] for x in bars[max(0, i - 250):i + 1])
    run = c / min(x["close"] for x in bars[max(0, i - 60):i + 1]) - 1
    vol20 = sum((x.get("volume") or 0) for x in bars[max(0, i - 20):i]) / max(1, min(20, i))
    return {
        "date": b["time"], "close": round(c, 2),
        "vs20": round(c / sma20[i] - 1, 3) if sma20[i] else None,
        "vs50": round(c / sma50[i] - 1, 3) if sma50[i] else None,
        "vs200": round(c / sma200[i] - 1, 3) if sma200[i] else None,
        "rsi_d": round(rsi14[i], 1) if rsi14[i] else None,
        "rsi_w": round(w_rsi[k], 1) if w_rsi[k] else None,
        "run60": round(run, 3), "from_hi52": round(c / hi52 - 1, 3), "from_lo52": round(c / lo52 - 1, 3),
        "vol_x": round((b.get("volume") or 0) / vol20, 2) if vol20 else None,
    }


def series_arrays(bars):
    n = len(bars)
    def arr(items, key="value"):
        d = {x["time"]: x[key] for x in items}
        return [d.get(b["time"]) for b in bars]
    sma20, sma50, sma200 = arr(I.sma(bars, 20)), arr(I.sma(bars, 50)), arr(I.sma(bars, 200))
    rsi14 = arr(I.rsi(bars, 14))
    weekly = I.resample(bars, "W")
    w_rsi_map = {x["time"]: x["value"] for x in I.rsi(weekly, 14)}
    w_sma10_map = {x["time"]: x["value"] for x in I.sma(weekly, 10)}
    w_rsi = [w_rsi_map.get(w["time"]) for w in weekly]
    w_sma10 = [w_sma10_map.get(w["time"]) for w in weekly]
    wk_of_day, j = {}, 0
    for b in bars:
        while j + 1 < len(weekly) and weekly[j]["time"] < b["time"]:
            j += 1
        wk_of_day[b["time"]] = j
    return weekly, wk_of_day, w_rsi, w_sma10, sma20, sma50, sma200, rsi14


def candidate_signals(bars, arrays):
    weekly, wk_of_day, w_rsi, w_sma10, sma20, sma50, sma200, rsi14 = arrays
    n = len(bars)
    closes = [b["close"] for b in bars]
    sig = {}

    def add(name, kind, idx):
        sig.setdefault((kind, name), []).append(idx)

    week_end = {weekly[k]["time"]: k for k in range(len(weekly))}
    # RonnieV's Williams %R, length 12, bands 0 / -100. The "bearish box" is a
    # run of weeks pinned in the bottom fifth; the "breakout" is the first
    # week back above -80. The floor (his Green Barrier) is a reading at or
    # under -95. The ceiling box is the mirror at the top.
    w_wr = {x["time"]: x["value"] for x in I.williams_r(weekly, 12, 0.0, -100.0)}
    d_wr = {x["time"]: x["value"] for x in I.williams_r(bars, 12, 0.0, -100.0)}
    wr_w = [w_wr.get(w["time"]) for w in weekly]
    prev_wrsi_max = None
    for i in range(60, n):
        b = bars[i]; c = closes[i]; k = wk_of_day[b["time"]]
        is_week_end = b["time"] in week_end
        # ---- top candidates ----
        if sma50[i] and c / sma50[i] - 1 >= 0.60:
            add("price 60%+ above the 50-day", "top", i)
        if sma200[i] and c / sma200[i] - 1 >= 1.50:
            add("price 150%+ above the 200-day", "top", i)
        if is_week_end and w_rsi[k] is not None and w_rsi[k] >= 85:
            add("weekly RSI 85 or more", "top", i)
        if is_week_end and k >= 8 and w_rsi[k] is not None:
            recent = [x for x in w_rsi[max(0, k - 8):k] if x is not None]
            if recent and max(recent) >= 80 and w_rsi[k] < 70:
                add("weekly RSI back under 70 after 80+", "top", i)
        if is_week_end and k >= 3:
            w, pw = weekly[k], weekly[k - 1]
            if pw["close"] / pw["open"] - 1 >= 0.25 and w["close"] < pw["open"]:
                add("25% week fully given back the next week", "top", i)
        if is_week_end and k >= 12 and w_rsi[k] is not None:
            # bearish divergence: weekly close at a 12-week high, RSI below its 12-week high by 8+
            wc = [weekly[q]["close"] for q in range(k - 12, k + 1)]
            wr = [w_rsi[q] for q in range(k - 12, k + 1) if w_rsi[q] is not None]
            if weekly[k]["close"] >= max(wc) and wr and w_rsi[k] <= max(wr) - 8:
                add("weekly bearish RSI divergence", "top", i)
        if i >= 10:
            run10 = c / min(closes[i - 10:i]) - 1
            if run10 >= 0.50:
                add("+50% in ten sessions", "top", i)
        if is_week_end and k >= 4 and wr_w[k] is not None:
            box = [wr_w[q] for q in range(k - 3, k) if wr_w[q] is not None]
            if len(box) == 3 and min(box) >= -10 and wr_w[k] < -20:
                add("weekly W%R ceiling box breaks down (3+ weeks at -10 or above, then under -20)", "top", i)
            if wr_w[k] >= -2 and k >= 1 and (wr_w[k - 1] or -100) >= -2:
                add("weekly W%R pinned at the ceiling two weeks (-2 or above)", "top", i)
        # ---- bottom candidates ----
        hi52 = max(closes[max(0, i - 250):i + 1])
        dd = c / hi52 - 1
        if is_week_end and w_rsi[k] is not None and w_rsi[k] <= 30:
            add("weekly RSI 30 or under", "bottom", i)
        if is_week_end and w_rsi[k] is not None and w_rsi[k] <= 35 and dd <= -0.50:
            add("weekly RSI under 35 with a 50%+ drawdown", "bottom", i)
        if dd <= -0.60:
            add("60%+ under the 52-week high", "bottom", i)
        if sma200[i] and c / sma200[i] - 1 <= -0.35:
            add("35%+ under the 200-day", "bottom", i)
        if rsi14[i] is not None and rsi14[i] <= 22:
            add("daily RSI 22 or under", "bottom", i)
        if is_week_end and k >= 4 and dd <= -0.40:
            w, pw = weekly[k], weekly[k - 1]
            if w["close"] > pw["high"] and w["low"] >= pw["low"]:
                add("first weekly close over the prior week's high, 40%+ down", "bottom", i)
        if is_week_end and k >= 4 and wr_w[k] is not None:
            if wr_w[k] <= -95:
                add("weekly W%R at the floor (-95 or under) — the Green Barrier", "bottom", i)
            box = [wr_w[q] for q in range(k - 3, k) if wr_w[q] is not None]
            if len(box) == 3 and max(box) <= -80 and wr_w[k] > -80:
                add("weekly W%R bearish box breakout (3+ weeks under -80, then above)", "bottom", i)
        dwr = d_wr.get(b["time"])
        if dwr is not None and dwr <= -95 and dd <= -0.40:
            add("daily W%R at the floor with a 40%+ drawdown", "bottom", i)
        if is_week_end and k >= 12 and w_rsi[k] is not None and dd <= -0.40:
            wc = [weekly[q]["close"] for q in range(k - 12, k + 1)]
            wr = [w_rsi[q] for q in range(k - 12, k + 1) if w_rsi[q] is not None]
            if weekly[k]["close"] <= min(wc) and wr and w_rsi[k] >= min(wr) + 6:
                add("weekly bullish RSI divergence at a 12-week low", "bottom", i)
    return sig


def evaluate(bars, sig, tops, bottoms):
    closes = [b["close"] for b in bars]
    rows = []
    for (kind, name), idxs in sorted(sig.items()):
        episodes, cur = [], []
        for i in idxs:
            if cur and i - cur[-1] > 10:
                episodes.append(cur); cur = []
            cur.append(i)
        if cur:
            episodes.append(cur)
        details = []
        for ep in episodes:
            i0 = ep[0]; c0 = closes[i0]
            fut = closes[i0 + 1:i0 + 121]
            if len(fut) < 20:
                continue
            if kind == "top":
                more = max(fut) / c0 - 1                   # further upside given up by acting here
                peak_i = i0 + 1 + fut.index(max(fut))
                after_peak = closes[peak_i:i0 + 121]
                fall = min(fut) / c0 - 1                   # worst level reached from here
                hit = min(fut) <= c0 * 0.70                # a 30% fall followed within 120 sessions
                details.append((bars[i0]["time"], round(c0, 2), hit, more, fall))
            else:
                more = min(fut) / c0 - 1                   # further downside before the low
                rise = max(fut) / c0 - 1
                hit = max(fut) >= c0 * 1.50                # a 50% rise followed within 120 sessions
                details.append((bars[i0]["time"], round(c0, 2), hit, more, rise))
        if not details:
            continue
        hits = sum(1 for d in details if d[2])
        med = lambda xs: sorted(xs)[len(xs) // 2]
        rows.append({"kind": kind, "name": name, "episodes": len(details), "hits": hits,
                     "med_more": med([d[3] for d in details]), "med_out": med([d[4] for d in details]),
                     "details": details})
    return rows


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "IREN"
    conn = ledger.connect()
    bars = [b for b in prices.load_bars(conn, sym, "2015-01-01", "2030-01-01") if b["time"] >= "2021-06-01"]
    arrays = series_arrays(bars)
    tops, bottoms = turns(bars)
    L = [f"# {sym}: what the tops and the washed-out lows looked like", "",
         f"{bars[0]['time']} to {bars[-1]['time']}. A top is a close followed by a fall of {TOP_DROP*100:.0f}% or more before any higher close; "
         f"a bottom is a close followed by a rise of {BOTTOM_RISE*100:.0f}% or more before any lower close. A signal is 'near' a turn if it fired within "
         f"{WINDOW} sessions and within {NEAR_TOP*100:.0f}% of the top price (or {NEAR_BOTTOM*100:.0f}% of the bottom).", ""]
    for label, idx in (("Tops", tops), ("Bottoms", bottoms)):
        L += [f"## {label}", "", "| Date | Close | vs 20-day | vs 50-day | vs 200-day | Daily RSI | Weekly RSI | Run, 60 sessions | From 52-wk high | Above 52-wk low | Volume vs 20-day |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for i in idx:
            s = state(bars, i, *arrays)
            pct = lambda v: "—" if v is None else f"{v*100:+.0f}%"
            L.append(f"| {s['date']} | {s['close']} | {pct(s['vs20'])} | {pct(s['vs50'])} | {pct(s['vs200'])} | {s['rsi_d']} | {s['rsi_w']} | {pct(s['run60'])} | {pct(s['from_hi52'])} | {pct(s['from_lo52'])} | {s['vol_x']}x |")
        L.append("")
    sig = candidate_signals(bars, arrays)
    rows = evaluate(bars, sig, tops, bottoms)
    for kind, title in (("top", "Top signals, on this name's own history"), ("bottom", "Bottom signals, on this name's own history")):
        L += [f"## {title}", ""]
        if kind == "top":
            L += ["| Signal | Times it fired | Followed by a 30%+ fall within 120 sessions | Median further rise before acting was vindicated | Median worst level after |", "|---|---|---|---|---|"]
        else:
            L += ["| Signal | Times it fired | Followed by a 50%+ rise within 120 sessions | Median further fall before the low | Median best level after |", "|---|---|---|---|---|"]
        for r in sorted((r for r in rows if r["kind"] == kind), key=lambda r: -(r["hits"] / r["episodes"])):
            L.append(f"| {r['name']} | {r['episodes']} | {r['hits']} ({r['hits']/r['episodes']*100:.0f}%) | {r['med_more']*100:+.0f}% | {r['med_out']*100:+.0f}% |")
        L.append("")
        L.append("<details><summary>Every firing</summary>\n")
        for r in sorted((r for r in rows if r["kind"] == kind), key=lambda r: r["name"]):
            L.append(f"**{r['name']}**: " + "; ".join(f"{d} @ {c}{' ✓' if hit else ''} ({m*100:+.0f}% / {o*100:+.0f}%)" for d, c, hit, m, o in r["details"]))
            L.append("")
        L.append("</details>\n")
    text = "\n".join(L)
    print(text)
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(text + "\n")


if __name__ == "__main__":
    main()
