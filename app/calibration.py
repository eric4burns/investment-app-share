"""Is the verdict engine any good, and if not, which part of it is wrong?

`journal.py` answers the first question: what share of calls were right, and by
how much against the index. That is enough to know whether to trust the thing.
It is not enough to know what to change, because a single hit rate cannot say
whether the Ichimoku condition is carrying the engine or dragging it down.

This module answers the second question by slicing the same graded calls four
ways:

  by action      — are the sells wrong while the buys are fine?
  by confidence  — this is the important one, see below
  by timeframe   — is the weekly reading worth computing at all?
  by condition   — which individual pieces of evidence actually predict

## Confidence is the most useful slice

A verdict labelled "high" should outperform one labelled "low". If it does not,
the confidence formula is measuring nothing, and that is a specific, fixable
defect rather than a vague sense that the engine is off. It is also the slice
most likely to be wrong first, because confidence here is a share of evidence
weight and those weights were assigned by hand.

## Why this refuses to speak more often than it speaks

Two sampling problems, and neither is cosmetic.

**Calls are not independent.** Sixteen holdings scored on one evening is close
to ONE observation of one market day, not sixteen — the names move together and
the conditions fire together. So every bucket reports the number of distinct
DAYS alongside the number of calls, and the day count is what gates a verdict.
A hundred calls from four days says almost nothing.

**Slicing invites false findings.** Thirty conditions sliced by stance is sixty
comparisons, and at any ordinary threshold a few will look significant purely by
chance. The output therefore ranks conditions and states their edge, but never
calls one "good" or "bad" on the strength of the ranking alone — and it says so
in the payload rather than only in this docstring.

The honest use of this tool is: run it monthly, look for something large and
persistent across several months, and change one thing at a time.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from . import journal, measure
from .ledger import connect

# Floors below which a bucket is reported but never characterised. The day
# count matters more than the call count for the reason given above.
MIN_CALLS = 20
MIN_DAYS = 10


def _graded(conn, horizon: int, source: str = "app") -> list[dict]:
    """Every call from `source` that has had time to be scored, with evidence."""
    # Through measure.history rather than journal.history: the replayed
    # sources live in the attached replay file once it exists, and only that
    # fetch knows which schema to read a source from.
    journal.ensure_schema(conn)
    pfx, rows = measure.history(conn, source)
    out = []
    for g in rows:
        h = g["horizons"].get(horizon) or {}
        if h.get("status") != "scored" or h.get("score") is None:
            continue
        ev = conn.execute(
            f"SELECT name, stance, weight FROM {pfx}decision_evidence WHERE decision_id = ?",
            (g["id"],)).fetchall()
        out.append({**g, "score": h["score"], "right": bool(h["right"]),
                    "excess": h["excess"], "asof": h.get("asof"),
                    "evidence": [(r["name"], r["stance"]) for r in ev]})
    return out


def _bucket(calls: list[dict]) -> dict:
    n = len(calls)
    days = len({c["date"] for c in calls})
    if not n:
        return {"n": 0, "days": 0, "hit_rate": None, "mean_score": None,
                "enough": False}
    return {
        "n": n,
        "days": days,
        "hit_rate": sum(1 for c in calls if c["right"]) / n,
        "mean_score": round(sum(c["score"] for c in calls) / n, 4),
        # Both floors, deliberately. Either alone is easy to satisfy without
        # having seen enough different market conditions to mean anything.
        "enough": n >= MIN_CALLS and days >= MIN_DAYS,
    }


def _split(calls: list[dict], key) -> dict:
    groups = defaultdict(list)
    for c in calls:
        groups[key(c)].append(c)
    return {str(k): _bucket(v) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}


def by_confidence(conn, horizon: int = 21, source: str = "app") -> dict:
    """Does a high-confidence call actually beat a low-confidence one?"""
    calls = _graded(conn, horizon, source)
    buckets = _split(calls, lambda c: c["confidence"] or "none")
    order = [b for b in ("high", "medium", "low") if b in buckets]
    ranked = [(b, buckets[b]["mean_score"]) for b in order
              if buckets[b]["enough"] and buckets[b]["mean_score"] is not None]

    if len(ranked) < 2:
        finding = ("Not enough graded calls in at least two confidence levels to "
                   "say whether the label means anything yet.")
        ok = None
    else:
        scores = [s for _b, s in ranked]
        ok = scores == sorted(scores, reverse=True)
        finding = ("Confidence is ordered correctly: "
                   + " > ".join(f"{b} {s * 100:+.2f}" for b, s in ranked)
                   + ". The label is carrying real information."
                   ) if ok else (
                   "Confidence is NOT ordered correctly: "
                   + ", ".join(f"{b} {s * 100:+.2f}" for b, s in ranked)
                   + ". A high-confidence call is not beating a low-confidence one, "
                     "which means the evidence weights in verdicts.py are measuring "
                     "something other than reliability. That is the first thing to fix.")
    return {"buckets": buckets, "ordered": ok, "finding": finding}


def by_condition(conn, horizon: int = 21, source: str = "app") -> dict:
    """For each condition, how calls carrying it did against calls that did not.

    `edge` is the difference in mean score between the two. Positive means the
    condition is associated with better outcomes. Association, not cause: these
    conditions fire together constantly, so a strong number here is a place to
    look rather than a result.
    """
    calls = _graded(conn, horizon, source)
    names = sorted({e for c in calls for e in c["evidence"]},
                   key=lambda t: (t[0], t[1] or ""))
    out = []
    for name, stance in names:
        with_ = [c for c in calls if (name, stance) in c["evidence"]]
        without = [c for c in calls if (name, stance) not in c["evidence"]]
        wb, ob = _bucket(with_), _bucket(without)
        edge = (None if wb["mean_score"] is None or ob["mean_score"] is None
                else round(wb["mean_score"] - ob["mean_score"], 4))
        out.append({"condition": name, "stance": stance,
                    "with": wb, "without": ob, "edge": edge,
                    "enough": wb["enough"] and ob["enough"]})
    out.sort(key=lambda r: (r["edge"] is None, -(r["edge"] or 0)))
    return {"conditions": out,
            "comparisons": len(out),
            "caveat":
                f"{len(out)} conditions compared. At any ordinary threshold a few "
                f"will look significant by chance alone, and these conditions fire "
                f"together, so an edge here is a place to look rather than a "
                f"finding. Change one thing at a time and re-measure."}


def flip_levels(conn, horizon: int = 21, source: str = "app") -> dict:
    """Did naming an invalidation price turn out to mean anything?

    A verdict that names a flip level is making a sharper claim than one that
    does not, so the calls carrying a level should do better. If they do not,
    the levels are decoration.
    """
    calls = _graded(conn, horizon, source)
    with_ = [c for c in calls if c.get("flip") is not None]
    without = [c for c in calls if c.get("flip") is None]
    wb, ob = _bucket(with_), _bucket(without)
    edge = (None if wb["mean_score"] is None or ob["mean_score"] is None
            else round(wb["mean_score"] - ob["mean_score"], 4))
    return {"with_flip": wb, "without_flip": ob, "edge": edge,
            "finding": ("Not enough graded calls on both sides yet."
                        if not (wb["enough"] and ob["enough"]) else
                        f"Calls naming an invalidation level score "
                        f"{abs(edge) * 100:.2f} points "
                        f"{'better' if edge > 0 else 'worse'} than calls without one.")}


def report(conn, horizon: int = 21, source: str = "app") -> dict:
    calls = _graded(conn, horizon, source)
    overall = _bucket(calls)
    conf = by_confidence(conn, horizon, source)
    cond = by_condition(conn, horizon, source)
    actionable = [c for c in cond["conditions"] if c["enough"]]

    if not overall["enough"]:
        headline = (f"{overall['n']} graded call{'s' if overall['n'] != 1 else ''} "
                    f"across {overall['days']} day"
                    f"{'s' if overall['days'] != 1 else ''}. "
                    f"Nothing is measurable yet — this needs at least "
                    f"{MIN_CALLS} calls spanning {MIN_DAYS} separate days, and the "
                    f"day count matters more, because every holding scored on one "
                    f"evening is close to a single observation of a single market.")
    else:
        headline = (f"{overall['n']} calls across {overall['days']} days. "
                    f"Hit rate {overall['hit_rate'] * 100:.0f}%, average "
                    f"{overall['mean_score'] * 100:+.2f} points against SPY over "
                    f"{horizon} trading days.")

    return {
        "horizon": horizon, "overall": overall, "headline": headline,
        "by_action": _split(calls, lambda c: c["action"]),
        "by_timeframe": _split(calls, lambda c: c["timeframe"] or "?"),
        # Your own record, sliced by the book a call was in and by what you
        # said happened afterwards. Empty for app and replay calls, which carry
        # neither.
        "by_bucket": _split([c for c in calls if c.get("bucket")], lambda c: c["bucket"]),
        "by_tag": _split([c for c in calls if c.get("tag")], lambda c: c["tag"]),
        "by_confidence": conf,
        "by_condition": cond,
        "flip_levels": flip_levels(conn, horizon, source),
        "best": actionable[:5],
        "worst": list(reversed(actionable[-5:])) if actionable else [],
        "min_calls": MIN_CALLS, "min_days": MIN_DAYS,
    }


def _row(label: str, b: dict) -> str:
    if not b["n"]:
        return f"  {label:<28} —"
    mark = "" if b["enough"] else "   (too few to judge)"
    return (f"  {label:<28} {b['n']:>4} calls / {b['days']:>3} days   "
            f"hit {b['hit_rate'] * 100:>3.0f}%   "
            f"{b['mean_score'] * 100:>+7.2f} pts{mark}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.calibration")
    p.add_argument("--horizon", type=int, default=21, choices=journal.HORIZONS)
    p.add_argument("--source", default="app")
    args = p.parse_args(argv)

    conn = connect()
    r = report(conn, args.horizon, args.source)
    print(f"Verdict engine calibration — {args.source} calls, "
          f"{args.horizon} trading days\n")
    print(r["headline"])
    print()
    print("BY ACTION")
    for k, b in r["by_action"].items():
        print(_row(k, b))
    print("\nBY TIMEFRAME")
    for k, b in r["by_timeframe"].items():
        print(_row(k, b))
    print("\nBY CONFIDENCE")
    for k, b in r["by_confidence"]["buckets"].items():
        print(_row(k, b))
    print(f"\n  {r['by_confidence']['finding']}")
    print("\nCONDITIONS")
    shown = [c for c in r["by_condition"]["conditions"] if c["with"]["n"]]
    for c in shown[:20]:
        name = f"{c['condition']}" + (f" ({c['stance']})" if c["stance"] else "")
        edge = "—" if c["edge"] is None else f"{c['edge'] * 100:+7.2f} pts"
        flag = "" if c["enough"] else "  (too few)"
        print(f"  {name:<30} {c['with']['n']:>4} calls   edge {edge}{flag}")
    print(f"\n  {r['by_condition']['caveat']}")
    print(f"\n  {r['flip_levels']['finding']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
