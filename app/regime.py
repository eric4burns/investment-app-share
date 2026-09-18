"""The exposure dial: is this a market to be fully in, or not?

    python3 -m app.regime              # today's reading, with the gauges
    python3 -m app.regime --asof 2025-04-10

## Where it comes from

RonnieV runs a weather scale — clear skies, windy — that sets how much
capital he has at work; Cantonese Cat judges risk appetite from a few ratio
charts rather than from the news: the Nasdaq against the S&P, small caps
against large, the dollar, and whether the index itself is above its long
average. Neither is a forecast. Both are a reading of what money is doing
now. `research/transcript-notes-2026-09-03.md` has the quotes.

## The gauges

Each is +1, 0 or −1, from series already cached, with a 200-session average
standing in for the 20-month one they read on monthly charts:

  * **QQQ / SPY** above its average — growth leading, risk on.
  * **IWM / SPY** above its average — small caps leading, risk on.
  * **SPY** above its own average — the index in an uptrend.
  * **The dollar** (FRED's trade-weighted index, daily, keyless) BELOW its
    average — a falling dollar helps risk assets, in Cantonese Cat's reading.

The sum runs −4 to +4: +3 or more is *clear skies*, −2 or less is
*risk-off*, between is *windy*. The index's weekly Williams %R is reported
beside it, not scored: RonnieV's "green barrier" (the floor of the range)
is where he buys as an investor, and its consolidation "boxes" near the top
are what he watches for a break.

## What it is for

Context on the Outlook tab beside the fear-and-greed reading, an alert when
the label changes, and — because every input is a cached series — a value
the replay can compute for any past date, so whether the regime predicts
anything on this book is a question the measurement answers rather than a
belief. It is recorded on every replayed call at zero weight for exactly
that purpose.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from . import indicators as I, prices
from .ledger import connect

LOOKBACK = 200
DOLLAR = "DTWEXBGS"            # FRED: trade-weighted US dollar index, broad, daily
LABELS = {"on": "clear skies", "mixed": "windy", "off": "risk-off"}


def _series_upto(conn, symbol: str, asof: str) -> tuple[list[str], list[float]]:
    ser = prices.load_series(conn, symbol)
    dates = [d for d in prices.sorted_dates(conn, symbol) if d <= asof]
    return dates, [ser[d] for d in dates]


def _ratio(num_dates, num, den_dates, den) -> tuple[list[str], list[float]]:
    d = dict(zip(den_dates, den))
    out_d, out_v = [], []
    for t, v in zip(num_dates, num):
        if t in d and d[t]:
            out_d.append(t)
            out_v.append(v / d[t])
    return out_d, out_v


def _above_average(values: list[float], n: int = LOOKBACK) -> bool | None:
    if len(values) < n + 1:
        return None
    return values[-1] > sum(values[-n:]) / n


def reading(conn, asof: str | None = None) -> dict:
    asof = asof or date.today().isoformat()
    spy_d, spy = _series_upto(conn, "SPY", asof)
    qqq_d, qqq = _series_upto(conn, "QQQ", asof)
    iwm_d, iwm = _series_upto(conn, "IWM", asof)
    usd_d, usd = _series_upto(conn, DOLLAR, asof)
    gauges = []

    def gauge(name, above, on_when_above: bool, what: str):
        if above is None:
            gauges.append({"name": name, "score": 0, "state": "not enough history", "what": what})
            return
        on = above if on_when_above else (not above)
        gauges.append({"name": name, "score": 1 if on else -1,
                       "state": ("above" if above else "below") + " its 200-session average",
                       "what": what})

    gauge("QQQ / SPY", _above_average(_ratio(qqq_d, qqq, spy_d, spy)[1]), True,
          "growth against the whole market; above the average is risk on")
    gauge("IWM / SPY", _above_average(_ratio(iwm_d, iwm, spy_d, spy)[1]), True,
          "small caps against large; above the average is risk on")
    gauge("SPY", _above_average(spy), True, "the index against its own average; the trend")
    gauge("Dollar", _above_average(usd), False,
          "the trade-weighted dollar; below its average helps risk assets")

    score = sum(g["score"] for g in gauges)
    label = "on" if score >= 3 else "off" if score <= -2 else "mixed"

    # The index's weekly Williams %R, reported beside the dial, not in it.
    wr = None
    bars = prices.load_bars(conn, "SPY", "2015-01-01", asof)
    weekly = I.resample(bars, "W") if bars else []
    if len(weekly) > 15:
        w = I.williams_r(weekly, 12, 0.0, -100.0)
        wr = w[-1]["value"] if w else None
    note = None
    if wr is not None:
        note = (f"SPY weekly Williams %R {wr:.0f}: "
                + ("at the green barrier — the floor of its range, where RonnieV buys as an investor"
                   if wr <= -80 else
                   "near the red barrier — the top of its range; a break down out of a consolidation "
                   "box here is his warning" if wr >= -20 else "in the middle of its range"))
    return {"asof": asof, "score": score, "state": label, "label": LABELS[label],
            "gauges": gauges, "williams_r": wr, "note": note,
            "summary": (f"{LABELS[label]} ({score:+d} of 4): "
                        + ", ".join(f"{g['name']} {g['state'].split(' its')[0]}" for g in gauges
                                    if g["score"]))}


# --------------------------------------------------------- the indices ----

INDICES = ("SPY", "QQQ", "IWM")
INDEX_HISTORY = 260          # bars needed before an index is read


def index_read(conn, asof: str | None = None, measured: dict | None = None) -> dict:
    """The market's own chart, read for every stock's call.

    The user's rule (2026-09-03): the S&P, the Nasdaq and the Russell can
    override a setup — a chart that looks fine on its own is not fine when
    the index is breaking. Each index gets its price against its 50- and
    200-day averages plus the engine's weekly and daily calls, and the S&P
    sets the state:

      * `against` — the S&P closed below its 200-day, or below a falling
        50-day. The index is breaking.
      * `with`    — above a 50-day that is above the 200-day. The index is
        trending up.
      * `neutral` — anything between.

    The state comes from the averages, not from the engine's measured fifth:
    the weekly profile was fitted on stocks, where a strong uptrend reading
    was followed by underperformance, and applied to an index at its highs
    that profile reads "sell" — the inversion, not a warning. The engine's
    calls are shown beside the averages for information. Recorded on every
    call at zero weight, and while the state is `against` a buy or add is
    marked down one notch of confidence — a mark-down, not a veto, until
    the replay has measured it.
    """
    from . import verdicts
    asof = asof or date.today().isoformat()
    out = {"asof": asof, "indices": {}, "state": "neutral", "summary": ""}
    for sym in INDICES:
        bars = [b for b in prices.load_bars(conn, sym, "2015-01-01", asof) if b["time"] <= asof]
        if len(bars) < INDEX_HISTORY:
            continue
        closes = [b["close"] for b in bars]
        ma50 = sum(closes[-50:]) / 50
        ma50_prev = sum(closes[-70:-20]) / 50
        ma200 = sum(closes[-200:]) / 200
        px = closes[-1]
        trend = ("breaking" if px < ma200 or (px < ma50 and ma50 < ma50_prev)
                 else "up" if px > ma50 > ma200 else "mixed")
        w = verdicts.for_symbol(bars, "W", None, None, measured)
        d = verdicts.for_symbol(bars, "D", None, None, None)
        out["indices"][sym] = {"price": px, "ma50": round(ma50, 2), "ma200": round(ma200, 2),
                               "above_50": px > ma50, "above_200": px > ma200, "trend": trend,
                               "weekly": w.get("verdict"), "weekly_confidence": w.get("confidence"),
                               "fifth": w.get("measured_fifth"), "daily": d.get("verdict"),
                               "flip": w.get("flip")}
    spy = out["indices"].get("SPY")
    if spy:
        out["state"] = {"breaking": "against", "up": "with", "mixed": "neutral"}[spy["trend"]]
    out["summary"] = ", ".join(
        f"{sym} {'above' if v['above_200'] else 'BELOW'} its 200-day"
        + ("" if v["above_50"] else ", below its 50-day")
        + f" ({v['trend']})"
        for sym, v in out["indices"].items())
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.regime")
    p.add_argument("--asof", default=None)
    args = p.parse_args(argv)
    conn = connect()
    r = reading(conn, args.asof)
    print(f"{r['asof']}: {r['label']} ({r['score']:+d} of 4)")
    for g in r["gauges"]:
        print(f"  {g['name']:<10} {g['score']:+d}  {g['state']:<34} {g['what']}")
    if r["note"]:
        print(f"  {r['note']}")
    from . import measure
    ix = index_read(conn, args.asof, measure.load_profile(conn, "W"))
    print(f"  the indices: {ix['state']} — {ix['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
