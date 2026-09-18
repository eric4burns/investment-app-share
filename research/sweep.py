"""Every reading the app can compute, against a name's real tops and bottoms.

The question "how could the turn have been seen" gets one answer per reading,
not a hand-picked few. For one name, on daily and weekly bars: compute every
indicator-derived reading below, find the real turns by zigzag (a 40% fall
makes a top, a 60% rise a bottom), then for every reading:

  * its value at each turn, and where that value sits in the reading's own
    history (percentile), so "extreme" is measured against the name itself;
  * a threshold search at the reading's own extreme percentiles (top side:
    90th/95th/98th; bottom side: 10th/5th/2nd), scoring each threshold by
    precision — how often an episode above (below) it was followed by a 30%
    fall (50% rise) within 120 sessions — recall of the real turns, and how
    much further the move ran before the call was vindicated.

Output: one ranked table per side, one raw table of every reading at every
turn, and the list of readings that carried nothing. Percentiles and
thresholds are read off the same history they are scored on, and the file
says so at the top.

    python3 research/sweep.py IREN [--md out.md]
"""
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import indicators as I, ledger, prices, structure  # noqa: E402

TOP_DROP, BOTTOM_RISE = 0.40, 0.60
HORIZON = 120
NEAR = 40


def zigzag(closes):
    tops, bottoms, mode, ext = [], [], None, 0
    for i in range(1, len(closes)):
        c = closes[i]
        if mode in (None, "up"):
            if c > closes[ext]:
                ext = i
            elif c <= closes[ext] * (1 - TOP_DROP):
                tops.append(ext); mode, ext = "down", i
        if mode == "down":
            if c < closes[ext]:
                ext = i
            elif c >= closes[ext] * (1 + BOTTOM_RISE):
                bottoms.append(ext); mode, ext = "up", i
    return tops, bottoms


def aligned(bars, items, key="value"):
    d = {x["time"]: x.get(key) for x in items}
    return [d.get(b["time"]) for b in bars]


def pct_change(a, b):
    return None if a is None or b is None or b == 0 else a / b - 1


def readings(bars, spy=None):
    """name -> list of values aligned with bars (None where undefined)."""
    n = len(bars)
    closes = [b["close"] for b in bars]
    vols = [b.get("volume") or 0 for b in bars]
    R = {}
    for p in (20, 50, 200):
        s = aligned(bars, I.sma(bars, p))
        R[f"price vs {p}-bar SMA (%)"] = [pct_change(c, m) for c, m in zip(closes, s)]
    e = aligned(bars, I.ema(bars, 21))
    R["price vs 21-bar EMA (%)"] = [pct_change(c, m) for c, m in zip(closes, e)]
    s20, s50 = aligned(bars, I.sma(bars, 20)), aligned(bars, I.sma(bars, 50))
    R["20-bar SMA vs 50-bar SMA (%)"] = [pct_change(a, b) for a, b in zip(s20, s50)]
    bb = I.bollinger(bars, 20, 2.0)
    up, lo, mid = aligned(bars, bb["upper"]), aligned(bars, bb["lower"]), aligned(bars, bb["middle"])
    R["Bollinger %B (20, 2)"] = [None if u is None or l is None or u == l else (c - l) / (u - l) for c, u, l in zip(closes, up, lo)]
    R["Bollinger bandwidth (%)"] = [None if u is None or l is None or not m else (u - l) / m for u, l, m in zip(up, lo, mid)]
    kc = I.keltner(bars, 20, 2.0)
    ku, kl = aligned(bars, kc["upper"]), aligned(bars, kc["lower"])
    R["Keltner position (0 = lower, 1 = upper)"] = [None if u is None or l is None or u == l else (c - l) / (u - l) for c, u, l in zip(closes, ku, kl)]
    vw = aligned(bars, I.vwap(bars, 20))
    R["price vs 20-bar VWAP (%)"] = [pct_change(c, v) for c, v in zip(closes, vw)]
    ich = I.ichimoku(bars)
    sa, sb = aligned(bars, ich["span_a"]), aligned(bars, ich["span_b"])
    conv, base = aligned(bars, ich["conversion"]), aligned(bars, ich["base"])
    R["price vs cloud top (%)"] = [None if a is None or b is None else pct_change(c, max(a, b)) for c, a, b in zip(closes, sa, sb)]
    R["price vs cloud bottom (%)"] = [None if a is None or b is None else pct_change(c, min(a, b)) for c, a, b in zip(closes, sa, sb)]
    R["cloud thickness (% of price)"] = [None if a is None or b is None or not c else abs(a - b) / c for c, a, b in zip(closes, sa, sb)]
    R["tenkan vs kijun (%)"] = [pct_change(t, k) for t, k in zip(conv, base)]
    R["price vs kijun (%)"] = [pct_change(c, k) for c, k in zip(closes, base)]
    rsi = aligned(bars, I.rsi(bars, 14))
    R["RSI 14"] = rsi
    R["RSI 14, change over 4 bars"] = [None if i < 4 or rsi[i] is None or rsi[i - 4] is None else rsi[i] - rsi[i - 4] for i in range(n)]
    st = I.stochastic(bars, 14, 3)
    R["Stochastic %K (14, 3)"] = aligned(bars, st["k"])
    R["Williams %R 12"] = aligned(bars, I.williams_r(bars, 12, 0.0, -100.0))
    R["Williams %R 14"] = aligned(bars, I.williams_r(bars, 14, 0.0, -100.0))
    mc = I.macd(bars)
    hist, ml, sg = aligned(bars, mc["histogram"]), aligned(bars, mc["macd"]), aligned(bars, mc["signal"])
    R["MACD histogram (% of price)"] = [None if h is None or not c else h / c for h, c in zip(hist, closes)]
    R["MACD line (% of price)"] = [None if m is None or not c else m / c for m, c in zip(ml, closes)]
    atr = aligned(bars, I.atr(bars, 14))
    R["ATR 14 (% of price)"] = [None if a is None or not c else a / c for a, c in zip(atr, closes)]
    obv = aligned(bars, I.obv(bars))
    R["OBV change over 20 bars (% of 20-bar volume)"] = [None if i < 20 or obv[i] is None or obv[i - 20] is None or not sum(vols[i - 20:i]) else (obv[i] - obv[i - 20]) / sum(vols[i - 20:i]) for i in range(n)]
    R["volume vs 20-bar average (x)"] = [None if i < 20 or not sum(vols[i - 20:i]) else vols[i] / (sum(vols[i - 20:i]) / 20) for i in range(n)]
    R["volume, 5-bar vs 50-bar average (x)"] = [None if i < 50 or not sum(vols[i - 50:i]) else (sum(vols[i - 5:i + 1]) / 5) / (sum(vols[i - 50:i]) / 50) for i in range(n)]
    for lb in (10, 20, 60):
        R[f"return over {lb} bars (%)"] = [None if i < lb else closes[i] / closes[i - lb] - 1 for i in range(n)]
    R["drawdown from 250-bar high (%)"] = [closes[i] / max(closes[max(0, i - 250):i + 1]) - 1 for i in range(n)]
    R["run-up from 250-bar low (%)"] = [closes[i] / min(closes[max(0, i - 250):i + 1]) - 1 for i in range(n)]
    R["distance from 250-bar high, ATR units"] = [None if atr[i] is None or not atr[i] else (max(closes[max(0, i - 250):i + 1]) - closes[i]) / atr[i] for i in range(n)]
    # Fibonacci position inside the last 120-bar swing
    fibpos = []
    for i in range(n):
        if i < 130:
            fibpos.append(None); continue
        f = structure.fib(bars[i - 120:i + 1], 120)
        if not f:
            fibpos.append(None); continue
        hi, lo = f["from"]["price"], f["to"]["price"]
        top, bot = max(hi, lo), min(hi, lo)
        fibpos.append(None if top == bot else (closes[i] - bot) / (top - bot))
    R["position in the last 120-bar swing (0 = low, 1 = high)"] = fibpos
    if spy:
        sp = [spy.get(b["time"]) for b in bars]
        R["relative strength vs SPY, 60 bars (%)"] = [None if i < 60 or sp[i] is None or sp[i - 60] is None else (closes[i] / closes[i - 60]) / (sp[i] / sp[i - 60]) - 1 for i in range(n)]
    return R


def percentile(vals, v):
    xs = [x for x in vals if x is not None]
    if not xs or v is None:
        return None
    return sum(1 for x in xs if x <= v) / len(xs)


def quantile(vals, q):
    xs = sorted(x for x in vals if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1)))]


def score_threshold(vals, closes, turns, kind, thr, side):
    """Episodes where the reading crosses the threshold on `side` ('high' means
    value >= thr, 'low' means value <= thr). Returns precision etc."""
    n = len(closes)
    firing = [i for i in range(n) if vals[i] is not None and ((side == "high" and vals[i] >= thr) or (side == "low" and vals[i] <= thr))]
    episodes, cur = [], []
    for i in firing:
        if cur and i - cur[-1] > 10:
            episodes.append(cur); cur = []
        cur.append(i)
    if cur:
        episodes.append(cur)
    det = []
    for ep in episodes:
        i0 = ep[0]; c0 = closes[i0]; fut = closes[i0 + 1:i0 + 1 + HORIZON]
        if len(fut) < 20:
            continue
        if kind == "top":
            hit = min(fut) <= c0 * 0.70; more = max(fut) / c0 - 1
        else:
            hit = max(fut) >= c0 * 1.50; more = min(fut) / c0 - 1
        det.append((i0, hit, more))
    if not det:
        return None
    caught = set()
    for i0, _h, _m in det:
        for t in turns:
            if abs(i0 - t) <= NEAR and ((kind == "top" and closes[i0] >= closes[t] * 0.85) or (kind == "bottom" and closes[i0] <= closes[t] * 1.20)):
                caught.add(t)
    return {"episodes": len(det), "hits": sum(1 for d in det if d[1]), "precision": sum(1 for d in det if d[1]) / len(det),
            "recall": len(caught) / max(1, len(turns)), "median_more": median(d[2] for d in det)}


def analyse(bars, spy, label):
    closes = [b["close"] for b in bars]
    tops, bottoms = zigzag(closes)
    R = readings(bars, spy)
    L = [f"## {label}: {len(bars)} bars, {len(tops)} tops, {len(bottoms)} bottoms", ""]
    # raw table at the turns
    for kind, idx in (("Tops", tops), ("Bottoms", bottoms)):
        L += [f"### Every reading at each {kind[:-1].lower()} (value, and its percentile in this name's own history)", ""]
        L.append("| Reading | " + " | ".join(f"{bars[i]['time']} @ {closes[i]:.2f}" for i in idx) + " |")
        L.append("|---|" + "---|" * len(idx))
        for name, vals in R.items():
            cells = []
            for i in idx:
                v = vals[i]
                if v is None:
                    cells.append("—"); continue
                p = percentile(vals, v)
                shown = f"{v*100:+.0f}%" if "(%)" in name or "%B" in name else f"{v:.2f}" if abs(v) < 10 else f"{v:.0f}"
                cells.append(f"{shown} (p{p*100:.0f})")
            L.append(f"| {name} | " + " | ".join(cells) + " |")
        L.append("")
    # threshold search
    for kind, turns, sides in (("top", tops, (("high", (0.90, 0.95, 0.98)), ("low", (0.10, 0.05, 0.02)))),
                               ("bottom", bottoms, (("low", (0.10, 0.05, 0.02)), ("high", (0.90, 0.95, 0.98))))):
        rows = []
        for name, vals in R.items():
            best = None
            for side, qs in sides:
                for q in qs:
                    thr = quantile(vals, q)
                    if thr is None:
                        continue
                    sc = score_threshold(vals, closes, turns, kind, thr, side)
                    if not sc or sc["episodes"] < 3:
                        continue
                    key = (sc["precision"], sc["recall"])
                    if best is None or key > best[0]:
                        best = (key, name, side, q, thr, sc)
            if best:
                rows.append(best)
        rows.sort(key=lambda r: (-r[5]["precision"], -r[5]["recall"], -r[5]["episodes"]))
        what = "a 30%+ fall" if kind == "top" else "a 50%+ rise"
        L += [f"### {kind.title()} side — best threshold per reading, ranked by precision ({what} within {HORIZON} sessions)", "",
              f"| Reading | Threshold (its own percentile) | Episodes | Precision | Real {kind}s caught | Median further move before vindicated |", "|---|---|---|---|---|---|"]
        for key, name, side, q, thr, sc in rows:
            tshown = f"{'≥' if side == 'high' else '≤'} {thr*100:+.0f}%" if "(%)" in name or "%B" in name else f"{'≥' if side == 'high' else '≤'} {thr:.2f}"
            L.append(f"| {name} | {tshown} (p{q*100:.0f}) | {sc['episodes']} | {sc['precision']*100:.0f}% | {sc['recall']*100:.0f}% | {sc['median_more']*100:+.0f}% |")
        L.append("")
        nothing = [name for name in R if name not in {r[1] for r in rows}]
        if nothing:
            L.append(f"Readings with fewer than three episodes at any extreme, so nothing to score: {', '.join(nothing)}.")
            L.append("")
    return L


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "IREN"
    conn = ledger.connect()
    bars = [b for b in prices.load_bars(conn, sym, "2015-01-01", "2030-01-01") if b["time"] >= "2021-06-01"]
    spy = prices.load_series(conn, "SPY")
    weekly = I.resample(bars, "W")
    spy_w = {w["time"]: spy.get(w["time"]) for w in weekly}
    L = [f"# {sym}: every reading against the real tops and bottoms — 2026-09-05", "",
         "Turns by zigzag (a 40% fall makes a top, a 60% rise a bottom). Percentiles and thresholds are read off the same history they are scored on: "
         "this is the anatomy of this name's past, not an out-of-sample test. Precision is the share of a reading's extreme episodes followed by the turn's move; "
         "'median further move' is how much the price kept going after the first firing before the call was vindicated.", ""]
    L += analyse(bars, spy, "Daily")
    L += analyse(weekly, spy_w, "Weekly")
    text = "\n".join(L)
    print(text)
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(text + "\n")


if __name__ == "__main__":
    main()
