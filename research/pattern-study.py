"""What followed a confirmed cup-and-handle breakout, on the record.

Walks every week-end since 2022 for every name in the replay universe (the
watchlist) and a seeded sample of the liquidity screen, runs the detector on
the bars visible that day, and records the FIRST day each base's breakout is
confirmed. Forward returns at 21, 63 and 126 trading days are reported against
SPY and against random days on the same names in the same span (the control
the Substack study used). Head-and-shoulders confirmations are measured the
same way beside it, so the two shapes can be compared.

    python3 research/pattern-study.py [--md out.md] [--screen N]
"""
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ledger, prices, replay, structure, verdicts  # noqa: E402

START = "2022-01-01"
HORIZONS = (21, 63, 126)


def forward(series, dates, i, h):
    if i + h < len(dates):
        return series[dates[i + h]] / series[dates[i]] - 1
    return None


def scan(conn, symbols, week_ends, log=print):
    spy = prices.load_series(conn, "SPY"); spy_dates = sorted(spy)
    spy_idx = {d: i for i, d in enumerate(spy_dates)}
    events = []   # {kind, symbol, date, i, pivot...}
    for n, sym in enumerate(symbols, 1):
        bars = prices.load_bars(conn, sym, "2015-01-01", "2030-01-01")
        if len(bars) < 300:
            continue
        times = [b["time"] for b in bars]
        seen = set()
        for d in week_ends:
            # bisect
            lo, hi = 0, len(times)
            while lo < hi:
                mid = (lo + hi) // 2
                if times[mid] <= d: lo = mid + 1
                else: hi = mid
            if lo < 300:
                continue
            visible = bars[:lo]
            window = visible[-400:]
            pv = structure.pivots(window, 3, 3)
            price = visible[-1]["close"]
            ch = verdicts.cup_handle(window, pv, price, 1.0)
            if ch and ch["confirmed"]:
                key = ("cup", sym, ch["left_time"], ch["right_time"])
                if key not in seen:
                    seen.add(key)
                    events.append({"kind": "cup and handle", "symbol": sym, "i": lo - 1, "date": times[lo - 1],
                                   "depth": ch["depth"], "handle_depth": ch["handle_depth"], "cup_bars": ch["cup_bars"],
                                   "volume_ratio": ch.get("volume_ratio")})
            hs = verdicts.head_shoulders(structure.pivots(visible[-120:], 3, 3), price, 1.0)
            if hs and hs["confirmed"]:
                key = ("hs", sym, hs["kind"], round(hs["neck"], 2))
                if key not in seen:
                    seen.add(key)
                    events.append({"kind": hs["kind"], "symbol": sym, "i": lo - 1, "date": times[lo - 1]})
        log(f"  [{n:>3}/{len(symbols)}] {sym:<8} {len([e for e in events if e['symbol'] == sym]):>3} events")
        # forward returns
        series = {b["time"]: b["close"] for b in bars}
        for e in events:
            if e["symbol"] != sym or "fwd" in e:
                continue
            e["fwd"] = {}
            for h in HORIZONS:
                r = forward(series, times, e["i"], h)
                si = spy_idx.get(e["date"])
                b = (spy[spy_dates[si + h]] / spy[spy_dates[si]] - 1) if si is not None and si + h < len(spy_dates) else None
                e["fwd"][h] = (r, (r - b) if r is not None and b is not None else None)
        # control: random days on the same name in the same span
        rng = random.Random(hash(sym) & 0xffff)
        starts = [i for i, t in enumerate(times) if t >= START and i + max(HORIZONS) < len(times)]
        e_ctl = {h: [] for h in HORIZONS}
        if len(starts) >= 30:
            for i in rng.sample(starts, min(20, len(starts))):
                for h in HORIZONS:
                    r = forward(series, times, i, h)
                    si = spy_idx.get(times[i])
                    b = (spy[spy_dates[si + h]] / spy[spy_dates[si]] - 1) if si is not None and si + h < len(spy_dates) else None
                    if r is not None and b is not None:
                        e_ctl[h].append(r - b)
        for e in events:
            if e["symbol"] == sym and "ctl" not in e:
                e["ctl"] = e_ctl
    return events


def summarise(events, label):
    L = [f"## {label}", ""]
    by_kind = defaultdict(list)
    for e in events:
        by_kind[e["kind"]].append(e)
    for kind, es in sorted(by_kind.items()):
        bear = "head and shoulders" == kind
        L.append(f"### {kind} — {len(es)} confirmed, {len({e['symbol'] for e in es})} names")
        L.append("")
        L.append("| Horizon | Graded | Beat SPY | Median excess | Mean excess | Control: same names, random days — beat SPY / median |")
        L.append("|---|---|---|---|---|---|")
        for h in HORIZONS:
            g = [e["fwd"][h][1] for e in es if e.get("fwd") and e["fwd"][h][1] is not None]
            c = [x for e in es for x in (e.get("ctl") or {}).get(h, [])]
            if not g:
                continue
            sign = -1 if bear else 1
            beat = sum(1 for x in g if sign * x > 0) / len(g)
            cb = sum(1 for x in c if sign * x > 0) / len(c) if c else float("nan")
            L.append(f"| {h} d | {len(g)} | {beat*100:.0f}% | {median(g)*100:+.1f}% | {sum(g)/len(g)*100:+.1f}% | "
                     f"{cb*100:.0f}% / {median(c)*100:+.1f}% |")
        L.append("")
        if kind == "cup and handle":
            deep = [e for e in es if e["depth"] >= 0.3]; shallow = [e for e in es if e["depth"] < 0.3]
            for name, grp in (("cups under 30% deep", shallow), ("cups 30% deep or more", deep)):
                g = [e["fwd"][63][1] for e in grp if e.get("fwd") and e["fwd"][63][1] is not None]
                if g:
                    L.append(f"- {name}: {len(g)} graded at 63 days, beat SPY {sum(1 for x in g if x > 0)/len(g)*100:.0f}%, median {median(g)*100:+.1f}%")
            vol = [e for e in es if (e.get("volume_ratio") or 0) >= 1.4]
            g = [e["fwd"][63][1] for e in vol if e.get("fwd") and e["fwd"][63][1] is not None]
            if g:
                L.append(f"- breakouts on 1.4x volume or more: {len(g)} graded at 63 days, beat SPY {sum(1 for x in g if x > 0)/len(g)*100:.0f}%, median {median(g)*100:+.1f}%")
            L.append("")
    return "\n".join(L)


def main():
    conn = ledger.connect()
    n_screen = int(sys.argv[sys.argv.index("--screen") + 1]) if "--screen" in sys.argv else 300
    week_ends = replay.week_ends(conn, START, __import__("datetime").date.today().isoformat())
    wl = replay.universe(conn)
    print(f"watchlist: {len(wl)} names x {len(week_ends)} week-ends")
    ev_wl = scan(conn, wl, week_ends)
    sc = [s for s in replay.screen_sample(conn, n_screen) if s not in set(wl)]
    print(f"screen sample: {len(sc)} names")
    ev_sc = scan(conn, sc, week_ends)
    text = ("# Cup and handle, and head and shoulders, on the record — 2026-09-05\n\n"
            f"Confirmed breakouts found by walking {len(week_ends)} week-ends since {START}; forward returns against SPY; "
            "controls are random days on the same names in the same span. The watchlist is names chosen for having done "
            "well; the screen sample is not.\n\n" + summarise(ev_wl, "Watchlist") + "\n" + summarise(ev_sc, "Screen sample"))
    print(text)
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(text + "\n")


if __name__ == "__main__":
    main()
