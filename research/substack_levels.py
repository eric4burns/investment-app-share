"""Score the priced levels in StonkChris's Substack posts against what price did.

Two kinds of claim are checkable without deciding what a whole post "meant":

  buy zone   a level or range he says he would buy. Scored two ways: did price
             get there within 63 trading days, and — for the zones it reached —
             what did the name do over the next 21 and 63 trading days against
             SPY, and did the zone hold (no close more than 5% under its floor
             in the 63 days after the touch).
  target     an upside level. Scored as: reached within 63 / 126 trading days
             of the post, measured from the close on the post date.

Only symbols with cached daily bars are scored; the rest are counted and
listed. Nothing here is written to the database — the journal seeding is a
separate, deliberate step (research/seed-stonkchris-calls.py).

    python3 research/substack_levels.py            # summary
    python3 research/substack_levels.py --md out.md
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ledger, prices  # noqa: E402
from research.substack_extract import levels  # noqa: E402

HOLD_TOL = 0.05
HOLD_TOL_WIDE = 0.10
SYMBOL_MAP = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "XRP": "XRP-USD", "LINK": "LINK-USD", "TAO": "TAO-USD"}
CONTROL_DRAWS = 5
CONTROL_FROM = "2025-09-01"  # the first post is 12 Sep 2025


def _series(conn, sym, cache):
    if sym not in cache:
        cache[sym] = prices.load_series(conn, sym)
        cache[sym + "|dates"] = sorted(cache[sym])
    return cache[sym], cache[sym + "|dates"]


def _control_hits(series, dates, distance, horizon, rng):
    """Share of random start days in the same era as the posts (Sep 2025 on,
    with a full horizon ahead) from which a level the same distance above the
    close was reached. The era matters: these names had a very different 2023
    and 2024, and a control drawn from then would grade him against a market
    he was not writing in."""
    starts = [i for i, d in enumerate(dates) if d >= CONTROL_FROM and i + horizon < len(dates)]
    if len(starts) < 30:
        return None
    hits = 0
    for i in rng.sample(starts, CONTROL_DRAWS):
        lvl = series[dates[i]] * (1 + distance)
        hits += any(series[dates[j]] >= lvl for j in range(i + 1, i + 1 + horizon))
    return hits / CONTROL_DRAWS


def _control_returns(series, dates, horizon, rng):
    starts = [i for i, d in enumerate(dates) if d >= CONTROL_FROM and i + horizon < len(dates)]
    if len(starts) < 30:
        return None
    return [series[dates[i + horizon]] / series[dates[i]] - 1 for i in rng.sample(starts, CONTROL_DRAWS)]


def _control_after_fall(series, dates, distance, horizon, rng):
    """Forward returns from random same-era days on which the name had just
    fallen at least as far as the zone was below price — the fairer comparison
    for a zone that was 'reached later', since reaching it means the name fell
    to it first, and a fall of that size has its own tendency to bounce."""
    need = -distance if distance < 0 else 0.0
    starts = [i for i, d in enumerate(dates)
              if d >= CONTROL_FROM and i >= 20 and i + horizon < len(dates)
              and series[dates[i]] / max(series[dates[k]] for k in range(i - 20, i)) - 1 <= -need]
    if len(starts) < 30:
        return None
    return [series[dates[i + horizon]] / series[dates[i]] - 1 for i in rng.sample(starts, CONTROL_DRAWS)]


def _idx_on_or_before(dates, when):
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] <= when:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def score(conn) -> dict:
    import random
    rng = random.Random(20260904)
    ls = levels()
    cache = {}
    out = {"buy": [], "target": [], "unscored": Counter(), "n_levels": len(ls)}
    spy, spy_dates = _series(conn, "SPY", cache)
    for l in ls:
        if l["kind"] not in ("buy", "downside", "target"):
            continue
        sym = SYMBOL_MAP.get(l["symbol"], l["symbol"])
        series, dates = _series(conn, sym, cache)
        i0 = _idx_on_or_before(dates, l["date"])
        if i0 < 0 or not dates:
            out["unscored"][sym] += 1
            continue
        c0 = series[dates[i0]]
        lo = l["lo"]; hi = l["hi"] or l["lo"]
        lo, hi = min(lo, hi), max(lo, hi)
        # a "$12" level on a $300 stock or a "$80k" on a $3 one is a mis-parse
        if not (0.15 * c0 <= lo <= 6 * c0):
            out["unscored"]["mis-parsed price"] += 1
            continue
        fwd = dates[i0 + 1:i0 + 1 + 126]
        if l["kind"] in ("buy", "downside"):
            if lo > c0 * 1.03:
                continue  # a "buy zone" above price is a mis-read; skip it
            touch = None
            for j, d in enumerate(fwd[:63]):
                if series[d] <= hi:
                    touch = i0 + 1 + j
                    break
            rec = {**l, "close": c0, "in_zone_now": lo * 0.97 <= c0 <= hi * 1.03,
                   "distance": (lo + hi) / 2 / c0 - 1, "touched": touch is not None}
            if touch is not None:
                td = dates[touch]
                tp = series[td]
                after = dates[touch + 1:touch + 1 + 63]
                rec["touch_date"] = td
                rec["held"] = all(series[d] >= lo * (1 - HOLD_TOL) for d in after) if len(after) >= 20 else None
                rec["held_wide"] = all(series[d] >= lo * (1 - HOLD_TOL_WIDE) for d in after) if len(after) >= 20 else None
                # control: the same symbol's unconditional forward return from
                # random days in the same era, so "up 60%" can be read against
                # what the name did anyway
                rec["ctl63"] = _control_returns(series, dates, 63, rng)
                rec["ctl21"] = _control_returns(series, dates, 21, rng)
                rec["fall63"] = _control_after_fall(series, dates, rec["distance"], 63, rng)
                for h in (21, 63):
                    if len(after) >= h:
                        r = series[after[h - 1]] / tp - 1
                        si = _idx_on_or_before(spy_dates, td)
                        sj = _idx_on_or_before(spy_dates, after[h - 1])
                        b = spy[spy_dates[sj]] / spy[spy_dates[si]] - 1 if si >= 0 and sj >= 0 else None
                        rec[f"ret{h}"] = r
                        rec[f"excess{h}"] = (r - b) if b is not None else None
            out["buy"].append(rec)
        else:
            if lo < c0 * 0.97:
                continue  # a "target" under price is a downside read; skip it
            rec = {**l, "close": c0, "distance": lo / c0 - 1, "hit63": None, "hit126": None, "ctl_hit63": None}
            if len(fwd) >= 63:
                rec["hit63"] = any(series[d] >= lo for d in fwd[:63])
                rec["ctl_hit63"] = _control_hits(series, dates, rec["distance"], 63, rng)
            if len(fwd) >= 126:
                rec["hit126"] = any(series[d] >= lo for d in fwd[:126])
            out["target"].append(rec)
    return out


def summarise(res: dict) -> str:
    buys = res["buy"]; tg = res["target"]
    L = []
    L.append(f"Priced sentences: {res['n_levels']}. Buy zones scored: {len(buys)}. Targets scored: {len(tg)}.")
    uns = sum(res["unscored"].values())
    L.append(f"Unscored for lack of bars or a mis-parsed price: {uns} "
             f"({', '.join(f'{k} {v}' for k, v in res['unscored'].most_common(8))}).")
    # zones
    now = [b for b in buys if b["in_zone_now"]]
    below = [b for b in buys if not b["in_zone_now"]]
    L.append("")
    L.append("## Buy zones")
    L.append(f"- {len(now)} were at price when written (within 3%); {len(below)} were below price, "
             f"median {median([b['distance'] for b in below]) * 100:.0f}% under the close." if below else "")
    reached = [b for b in below if b["touched"]]
    L.append(f"- Of the {len(below)} below price, {len(reached)} were reached within 63 trading days "
             f"({len(reached) / len(below) * 100:.0f}%)." if below else "")
    for label, grp in (("At price when written", now), ("Reached later", reached)):
        g21 = [b for b in grp if b.get("ret21") is not None]
        g63 = [b for b in grp if b.get("ret63") is not None]
        held = [b for b in grp if b.get("held") is not None]
        if not g21:
            L.append(f"- {label}: nothing graded yet.")
            continue
        def stats(g, h):
            r = [b[f"ret{h}"] for b in g]; e = [b[f"excess{h}"] for b in g if b[f"excess{h}"] is not None]
            up = sum(1 for x in r if x > 0) / len(r)
            beat = sum(1 for x in e if x > 0) / len(e) if e else float("nan")
            return f"{len(g)} graded, median {median(r) * 100:+.1f}%, up {up * 100:.0f}%, beat SPY {beat * 100:.0f}%, median excess {median(e) * 100:+.1f}%"
        L.append(f"- {label}, 21 days after the touch: {stats(g21, 21)}.")
        if g63:
            L.append(f"- {label}, 63 days after the touch: {stats(g63, 63)}.")
        if held:
            L.append(f"- {label}: the zone held (no close more than 5% under its floor in the next 63 days) "
                     f"{sum(1 for b in held if b['held']) / len(held) * 100:.0f}% of the time, n={len(held)}; "
                     f"with a 10% allowance, {sum(1 for b in held if b['held_wide']) / len(held) * 100:.0f}%.")
        fall = [x for b in g63 for x in (b.get("fall63") or [])]
        if fall and label == "Reached later":
            L.append(f"- {label}, fairer control — same names, same era, random days after a fall at least as "
                     f"deep as the zone was below price (over 20 days), 63 days on: median {median(fall) * 100:+.1f}%, "
                     f"up {sum(1 for x in fall if x > 0) / len(fall) * 100:.0f}% (n={len(fall)} draws).")
        ctl = [x for b in g63 for x in (b.get("ctl63") or [])]
        if ctl:
            L.append(f"- {label}, control — the same names from random days in the same era (Sep 2025 on), 63 days on: "
                     f"median {median(ctl) * 100:+.1f}%, up {sum(1 for x in ctl if x > 0) / len(ctl) * 100:.0f}% (n={len(ctl)} draws).")
    # targets
    L.append("")
    L.append("## Upside targets")
    t63 = [t for t in tg if t["hit63"] is not None]; t126 = [t for t in tg if t["hit126"] is not None]
    if t63:
        L.append(f"- {len(t63)} old enough to grade at 63 days: {sum(t['hit63'] for t in t63) / len(t63) * 100:.0f}% reached; "
                 f"median distance asked {median([t['distance'] for t in t63]) * 100:.0f}% above the close.")
    if t126:
        L.append(f"- {len(t126)} old enough at 126 days: {sum(t['hit126'] for t in t126) / len(t126) * 100:.0f}% reached.")
    # by distance bucket
    for lo_d, hi_d in ((0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 9)):
        g = [t for t in t63 if lo_d <= t["distance"] < hi_d]
        if g:
            c = [t["ctl_hit63"] for t in g if t["ctl_hit63"] is not None]
            ctl = f"; the same distance from random days on the same names, same era: {sum(c) / len(c) * 100:.0f}%" if c else ""
            L.append(f"  - asked {lo_d * 100:.0f}–{hi_d * 100:.0f}% higher: {len(g)} targets, {sum(t['hit63'] for t in g) / len(g) * 100:.0f}% reached in 63 days{ctl}.")
    c_all = [t["ctl_hit63"] for t in t63 if t["ctl_hit63"] is not None]
    if c_all:
        L.append(f"- Control across all graded targets: {sum(c_all) / len(c_all) * 100:.0f}% of same-distance levels were reached from random days in the same era.")
    # per timeframe
    by_tf = defaultdict(list)
    for t in t63:
        by_tf[t["tf"]].append(t)
    for tf, g in sorted(by_tf.items()):
        L.append(f"  - {tf} posts: {len(g)} targets, {sum(t['hit63'] for t in g) / len(g) * 100:.0f}% reached in 63 days.")
    return "\n".join(x for x in L if x is not None)


def main() -> int:
    conn = ledger.connect()
    res = score(conn)
    text = summarise(res)
    print(text)
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
