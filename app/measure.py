"""Measure every evidence item against the drift of its own universe, then test
whether measured weights would order the calls — out of sample.

    python3 -m app.measure                       # daily calls, 21-day horizon
    python3 -m app.measure --horizon 63 --timeframe W
    python3 -m app.measure --split 2025-01-01    # fit before, test from

## Why the replay's own report was not enough

`calibration.by_condition` compares calls carrying an item with calls not
carrying it. On a universe that rose, every bullish item looks good and every
bearish item looks bad whether or not the item means anything, because the
calls carrying bullish items are simply long calls on names that went up.

So two corrections, both plain:

1. **Date-matched baseline.** For each week-end, the average excess return
   of EVERY call made that day is what the universe did that week. An item's
   edge is measured on the RESIDUAL — its calls' excess minus that day's
   baseline — so the drift of a rising list is taken out before anything is
   scored.

2. **Clustered standard errors.** Sixteen holdings scored on one evening are
   close to one observation. Each item's mean residual is computed per date
   first, and the spread of those per-date means is what the standard error
   comes from. The t-statistic reported is on that basis. It is still not a
   licence to believe anything under about 3, given thirty items are being
   compared at once.

## The out-of-sample test

The point of measuring is to replace hand-assigned weights with measured
ones. That is only worth doing if measured weights order the calls better
than the current confidence does, and only credible if the ordering holds
on dates the weights were not fitted on. So: fit each item's mean residual on
calls before `--split`, score every call after it by the sum of its items'
fitted values, cut the test calls into fifths by that score, and report the
mean residual of each fifth. A monotonic staircase is the result to look for.
The same staircase is printed for the engine's own confidence labels on the
same test calls, so the two can be compared directly.

Nothing here changes the engine. It writes a report.
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from datetime import date

from . import journal, split_replay
from .ledger import connect

MIN_DATES = 20


def history(conn, source: str, limit: int = 500000) -> tuple[str, list[dict]]:
    """Every call from `source`, graded, plus the schema its rows live in.

    The replayed sources sit in `ledger-replay.db` once the split has been
    run (see split_replay.py), so their table has to be named through the
    attached schema — `journal.history` reads the bare name and would find
    the ledger's empty table. The grading is the journal's own; only the
    fetch differs. The limit is far above the record on purpose: a limit
    that silently truncated would grade a subset and call it the record."""
    pfx = split_replay.prefix(conn, source)
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM {pfx}decisions WHERE source = ? ORDER BY date DESC, id DESC LIMIT ?",
        (source, limit))]
    cache: dict = {}
    # The journal's own batch preload, when it has one: each symbol's closes
    # from the first date the batch needs, rather than a full series per
    # symbol at first touch. grade() falls back to the full series without it.
    prefill = getattr(journal, "_prefill", None)
    if prefill:
        prefill(conn, rows, cache)
    return pfx, [journal.grade(conn, r, cache) for r in rows]


def graded(conn, horizon: int, timeframe: str | None, source: str = "replay") -> list[dict]:
    journal.ensure_schema(conn)
    pfx, rows = history(conn, source)
    out = []
    for g in rows:
        if timeframe and (g.get("timeframe") or "D") != timeframe:
            continue
        h = g["horizons"].get(horizon) or {}
        if h.get("status") != "scored" or h.get("excess") is None:
            continue
        ev = conn.execute(
            f"SELECT name, stance FROM {pfx}decision_evidence WHERE decision_id = ?",
            (g["id"],)).fetchall()
        out.append({"date": g["date"], "symbol": g["symbol"], "action": g["action"],
                    "confidence": g.get("confidence"), "excess": h["excess"],
                    "items": [(r["name"], r["stance"]) for r in ev if r["stance"]]})
    return out


def with_residuals(calls: list[dict]) -> list[dict]:
    """Excess minus the same-date mean excess of every call: the universe's
    drift that week taken out."""
    by_date = defaultdict(list)
    for c in calls:
        by_date[c["date"]].append(c["excess"])
    base = {d: sum(v) / len(v) for d, v in by_date.items()}
    for c in calls:
        c["baseline"] = base[c["date"]]
        c["residual"] = c["excess"] - base[c["date"]]
    return calls


def _clustered(values_by_date: dict[str, list[float]]) -> dict:
    """Mean and standard error from per-date means."""
    means = [sum(v) / len(v) for v in values_by_date.values() if v]
    n_calls = sum(len(v) for v in values_by_date.values())
    if len(means) < 2:
        return {"mean": (means[0] if means else None), "se": None, "t": None,
                "dates": len(means), "calls": n_calls}
    m = sum(means) / len(means)
    var = sum((x - m) ** 2 for x in means) / (len(means) - 1)
    se = math.sqrt(var / len(means))
    return {"mean": m, "se": se, "t": (m / se) if se > 1e-12 else None,
            "dates": len(means), "calls": n_calls}


def item_table(calls: list[dict]) -> list[dict]:
    """Every (item, stance): mean residual of the calls carrying it, clustered by date."""
    per_item: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for c in calls:
        for it in set(c["items"]):
            per_item[it][c["date"]].append(c["residual"])
    out = []
    for (name, stance), by_date in per_item.items():
        st = _clustered(by_date)
        # What the stance claims: a bull item should carry a positive residual,
        # a bear item a negative one. "extended" is the engine's take-profit
        # reading, so it claims a negative one too.
        expected = 1 if stance == "bull" else -1
        agrees = (st["mean"] is not None and (st["mean"] > 0) == (expected > 0))
        out.append({"item": name, "stance": stance, **st,
                    "claims": "positive" if expected > 0 else "negative",
                    "agrees": agrees,
                    "enough": st["dates"] >= MIN_DATES})
    out.sort(key=lambda r: -(r["mean"] or 0))
    return out


def pairs(calls: list[dict], items: list[dict] | None = None, min_calls: int = 150,
          top: int = 20, min_alone: int = 30) -> list[dict]:
    """How two items do TOGETHER against what each does alone.

    Every item's measured weight is a marginal association; items fire
    together, and the question "how do the variables work together" is
    whether a pair's joint residual is more than the sum of its parts. For
    every pair of (item, stance) that co-occurs on at least `min_calls`
    calls across enough dates: the mean residual of calls carrying both,
    the sum of the two items' individual means, and the difference — the
    lift. A large positive lift on a bull pair means the two confirm each
    other; a lift near zero means they are additive, and the separate
    weights already say everything; a negative lift means one is stealing
    the other's information. Ranked by the pair's own t, so the reader
    sees what is real before what is large."""
    # "Alone" means WITHOUT the partner. An item's overall mean includes the
    # calls where the partner was also present, so using it double-counts the
    # joint calls and reads every pair as anti-additive.
    per_pair: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    per_item: dict[tuple, list[tuple[str, float, frozenset]]] = defaultdict(list)
    for c in calls:
        its = sorted(set(c["items"]), key=lambda k: (k[0], str(k[1])))
        fs = frozenset(its)
        for k in its:
            per_item[k].append((c["date"], c["residual"], fs))
        for i in range(len(its)):
            for j in range(i + 1, len(its)):
                a, b = its[i], its[j]
                if a[0] == b[0]:
                    continue        # the same item's two stances never co-occur
                per_pair[(a, b)][c["date"]].append(c["residual"])
    out = []
    for (a, b), by_date in per_pair.items():
        n = sum(len(v) for v in by_date.values())
        if n < min_calls:
            continue
        st = _clustered(by_date)
        if st["mean"] is None or st["dates"] < MIN_DATES:
            continue
        a_only: dict[str, list[float]] = defaultdict(list)
        b_only: dict[str, list[float]] = defaultdict(list)
        for d, r, fs in per_item[a]:
            if b not in fs:
                a_only[d].append(r)
        for d, r, fs in per_item[b]:
            if a not in fs:
                b_only[d].append(r)
        # An "alone" mean from a handful of calls is noise dressed as a
        # baseline: head and shoulders (bear) read +45 points alone from 114
        # calls on a few dates — one name's run counted many times — and the
        # pair's lift was -62. Both halves need a real sample of DATES, the
        # same bar every item is held to.
        sa, sb = _clustered(a_only), _clustered(b_only)
        na, nb = sum(len(v) for v in a_only.values()), sum(len(v) for v in b_only.values())
        if (na < min_alone or nb < min_alone or sa["mean"] is None or sb["mean"] is None
                or sa["dates"] < MIN_DATES or sb["dates"] < MIN_DATES):
            continue
        a_alone, b_alone = sa["mean"], sb["mean"]
        a_only, b_only = [None] * na, [None] * nb
        additive = a_alone + b_alone
        out.append({"a": f"{a[0]} ({a[1]})", "b": f"{b[0]} ({b[1]})",
                    "calls": n, "dates": st["dates"], "mean": st["mean"], "t": st["t"],
                    "a_alone": a_alone, "b_alone": b_alone,
                    "a_alone_calls": len(a_only), "b_alone_calls": len(b_only),
                    "additive": additive, "lift": st["mean"] - additive})
    out.sort(key=lambda r: -abs(r["t"] or 0))
    return out[:top]


def fitted_weights(calls: list[dict]) -> dict[tuple, float]:
    """Each item's mean residual on the fitting set — the measured weight."""
    return {(r["item"], r["stance"]): r["mean"]
            for r in item_table(calls) if r["enough"] and r["mean"] is not None}


def score(call: dict, weights: dict[tuple, float]) -> float | None:
    vals = [weights[it] for it in set(call["items"]) if it in weights]
    return sum(vals) if vals else None


def staircase(test: list[dict], key, bins: int = 5) -> list[dict]:
    """Mean residual by fifth of `key`, lowest fifth first."""
    ranked = sorted((c for c in test if key(c) is not None), key=key)
    if len(ranked) < bins * 20:
        return []
    out = []
    size = len(ranked) // bins
    for i in range(bins):
        chunk = ranked[i * size:(i + 1) * size] if i < bins - 1 else ranked[i * size:]
        by_date = defaultdict(list)
        for c in chunk:
            by_date[c["date"]].append(c["residual"])
        st = _clustered(by_date)
        out.append({"fifth": i + 1, "calls": len(chunk), "mean_residual": st["mean"],
                    "hit": sum(1 for c in chunk if c["residual"] > 0) / len(chunk)})
    return out


def by_label(test: list[dict], label) -> dict[str, dict]:
    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for c in test:
        groups[str(label(c))][c["date"]].append(c["residual"])
    return {k: _clustered(v) for k, v in groups.items()}


def report(conn, horizon: int = 21, timeframe: str | None = "D",
           split: str = "2025-01-01", source: str = "replay") -> dict:
    calls = with_residuals(graded(conn, horizon, timeframe, source))
    if not calls:
        return {"error": "no graded replay calls; run python3 -m app.replay run first"}
    train = [c for c in calls if c["date"] < split]
    test = [c for c in calls if c["date"] >= split]
    items_all = item_table(calls)
    weights = fitted_weights(train)
    stairs = staircase(test, lambda c: score(c, weights))
    engine_conf = by_label(test, lambda c: c["confidence"] or "none")
    engine_action = by_label(test, lambda c: c["action"])
    return {"horizon": horizon, "timeframe": timeframe, "split": split,
            "calls": len(calls), "train": len(train), "test": len(test),
            "dates": len({c["date"] for c in calls}),
            "items": items_all, "weights": {f"{k[0]} ({k[1]})": round(v, 5) for k, v in weights.items()},
            "pairs": pairs(calls, items_all),
            "measured_staircase": stairs,
            "engine_confidence": engine_conf, "engine_action": engine_action}


SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_weights (
    timeframe TEXT NOT NULL, item TEXT NOT NULL, stance TEXT NOT NULL,
    horizon INTEGER NOT NULL, mean REAL, t REAL, dates INTEGER, calls INTEGER,
    fitted_through TEXT NOT NULL, computed_at TEXT NOT NULL,
    PRIMARY KEY (timeframe, item, stance, horizon)
);
"""


def save_weights(conn, horizon: int = 21, timeframes=("D", "W", "M")) -> dict:
    """Fit each item's mean residual on the WHOLE record and store it, per
    timeframe, so the Outlook tab can show a measured score beside the
    engine's own confidence. In-sample by construction — the out-of-sample
    test above is what says whether the ordering generalises — and stated as
    such wherever the score is shown."""
    from datetime import datetime
    conn.executescript(SCHEMA)
    out = {}
    for tf in timeframes:
        calls = with_residuals(graded(conn, horizon, tf))
        if not calls:
            continue
        rows = item_table(calls)
        through = max(c["date"] for c in calls)
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("DELETE FROM evidence_weights WHERE timeframe=? AND horizon=?", (tf, horizon))
        for r in rows:
            if r["mean"] is None:
                continue
            conn.execute("""INSERT INTO evidence_weights
                (timeframe, item, stance, horizon, mean, t, dates, calls, fitted_through, computed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (tf, r["item"], r["stance"], horizon, r["mean"], r["t"], r["dates"],
                          r["calls"], through, now))
        out[tf] = {"items": len(rows), "calls": len(calls), "through": through}
    conn.commit()
    return out


CUTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS measured_cuts (
    timeframe TEXT NOT NULL, horizon INTEGER NOT NULL,
    q20 REAL, q40 REAL, q60 REAL, q80 REAL, calls INTEGER, computed_at TEXT NOT NULL,
    PRIMARY KEY (timeframe, horizon)
);
"""


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def save_cuts(conn, horizon: int = 21, timeframes=("D", "W", "M")) -> dict:
    """Where the fifths of the measured score fall on the record, per
    timeframe, so a live call can be placed in a fifth without re-reading
    eighty thousand rows. Fitted on the whole record like the weights."""
    from datetime import datetime
    conn.executescript(CUTS_SCHEMA)
    out = {}
    for tf in timeframes:
        w = load_weights(conn, tf, horizon)
        calls = graded(conn, horizon, tf)
        scores = sorted(v for v in (score(c, w) for c in calls) if v is not None)
        if len(scores) < 100:
            continue
        cuts = tuple(_quantile(scores, q) for q in (0.2, 0.4, 0.6, 0.8))
        conn.execute("""INSERT INTO measured_cuts (timeframe, horizon, q20, q40, q60, q80, calls, computed_at)
                        VALUES (?,?,?,?,?,?,?,?)
                        ON CONFLICT(timeframe, horizon) DO UPDATE SET q20=excluded.q20, q40=excluded.q40,
                          q60=excluded.q60, q80=excluded.q80, calls=excluded.calls, computed_at=excluded.computed_at""",
                     (tf, horizon, *cuts, len(scores), datetime.now().isoformat(timespec="seconds")))
        out[tf] = {"cuts": cuts, "calls": len(scores)}
    conn.commit()
    return out


RECORD_SCHEMA = """
CREATE TABLE IF NOT EXISTS measured_record (
    timeframe TEXT NOT NULL, horizon INTEGER NOT NULL, fifth INTEGER NOT NULL,
    calls INTEGER, dates INTEGER, up_share REAL, mean_excess REAL, computed_at TEXT NOT NULL,
    PRIMARY KEY (timeframe, horizon, fifth)
);
"""


def save_record(conn, horizon: int = 21, timeframes=("D", "W", "M")) -> dict:
    """What calls in each fifth of the measured score actually did.

    The confidence word on a live call has to be earned on the past record —
    "if they work in the present then they should've worked in the past" — so
    for every fifth this stores how many replayed calls landed there, on how
    many dates, what share of them beat SPY, and by how much. The live call
    then carries its fifth's record and its confidence is read off it.
    Fitted on the whole record like the weights and the cuts."""
    from datetime import datetime
    conn.executescript(CUTS_SCHEMA + RECORD_SCHEMA)
    out = {}
    for tf in timeframes:
        w = load_weights(conn, tf, horizon)
        row = conn.execute("SELECT * FROM measured_cuts WHERE timeframe=? AND horizon=?",
                           (tf, horizon)).fetchone()
        if not w or not row:
            continue
        cuts = (row["q20"], row["q40"], row["q60"], row["q80"])
        calls = graded(conn, horizon, tf)
        by_fifth: dict[int, list[dict]] = defaultdict(list)
        for c in calls:
            sc = score(c, w)
            if sc is None:
                continue
            by_fifth[fifth_of(sc * 100, cuts)].append(c)
        out[tf] = {}
        for f in range(1, 6):
            g = by_fifth.get(f, [])
            if not g:
                continue
            up = sum(1 for c in g if c["excess"] > 0) / len(g)
            mean = sum(c["excess"] for c in g) / len(g)
            dates = len({c["date"] for c in g})
            conn.execute("""INSERT INTO measured_record (timeframe, horizon, fifth, calls, dates, up_share, mean_excess, computed_at)
                            VALUES (?,?,?,?,?,?,?,?)
                            ON CONFLICT(timeframe, horizon, fifth) DO UPDATE SET calls=excluded.calls, dates=excluded.dates,
                              up_share=excluded.up_share, mean_excess=excluded.mean_excess, computed_at=excluded.computed_at""",
                         (tf, horizon, f, len(g), dates, up, mean, datetime.now().isoformat(timespec="seconds")))
            out[tf][f] = {"calls": len(g), "dates": dates, "up_share": up, "mean_excess": mean}
    conn.commit()
    return out


def load_record(conn, timeframe: str, horizon: int = 21) -> dict[int, dict]:
    try:
        rows = conn.execute("SELECT * FROM measured_record WHERE timeframe=? AND horizon=?",
                            (timeframe, horizon)).fetchall()
    except Exception:                                          # noqa: BLE001
        return {}
    return {r["fifth"]: {"calls": r["calls"], "dates": r["dates"], "up_share": r["up_share"],
                         "mean_excess": r["mean_excess"]} for r in rows}


def load_profile(conn, timeframe: str, horizon: int = 21) -> dict | None:
    """Weights plus the fifth boundaries, or None if never measured."""
    w = load_weights(conn, timeframe, horizon)
    if not w:
        return None
    try:
        row = conn.execute("SELECT * FROM measured_cuts WHERE timeframe=? AND horizon=?",
                           (timeframe, horizon)).fetchone()
    except Exception:                                          # noqa: BLE001
        row = None
    return {"timeframe": timeframe, "horizon": horizon, "weights": w,
            "cuts": ((row["q20"], row["q40"], row["q60"], row["q80"]) if row else None),
            "record": load_record(conn, timeframe, horizon)}


def fifth_of(score_pts: float | None, cuts) -> int | None:
    """Which fifth of the record a score (in points) falls in, 1 to 5."""
    if score_pts is None or not cuts:
        return None
    v = score_pts / 100.0
    return 1 + sum(1 for c in cuts if v > c)


def load_weights(conn, timeframe: str, horizon: int = 21) -> dict[tuple, float]:
    try:
        rows = conn.execute("""SELECT item, stance, mean, dates FROM evidence_weights
                               WHERE timeframe=? AND horizon=?""", (timeframe, horizon)).fetchall()
    except Exception:                                          # noqa: BLE001
        return {}
    return {(r["item"], r["stance"]): r["mean"] for r in rows if r["dates"] >= MIN_DATES}


def measured_score(evidence: list[dict], weights: dict[tuple, float]) -> float | None:
    """The sum of the measured residuals of the items a verdict carries, in
    points of 21-day excess return. None when nothing it carries was measured."""
    items = {(e.get("name"), e.get("stance")) for e in (evidence or []) if e.get("stance")}
    vals = [weights[it] for it in items if it in weights]
    return round(sum(vals) * 100, 2) if vals else None


def date_level(calls: list[dict], item: str) -> dict:
    """An item that is the SAME for every name on a date — the exposure dial
    — has a residual of exactly zero by construction, since the residual
    subtracts the same-day mean. The question for such an item is whether it
    predicts that mean: the average raw excess of every call made on the
    dates it read one way against the dates it read the other. Clustered by
    date, which is the only honest unit here."""
    by_date: dict[str, tuple[str | None, list[float]]] = {}
    for c in calls:
        stance = next((st for (name, st) in c["items"] if name == item), None)
        d = c["date"]
        if d not in by_date:
            by_date[d] = (stance, [])
        by_date[d][1].append(c["excess"])
    groups: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for d, (stance, vals) in by_date.items():
        groups[str(stance)][d] = vals
    out = {}
    for stance, dd in groups.items():
        st = _clustered(dd)
        out[stance] = {**st, "dates": len(dd)}
    return out


def render(r: dict) -> str:
    if r.get("error"):
        return r["error"]
    pts = lambda v: "—" if v is None else f"{v * 100:+.2f}"
    L = [f"# Evidence items measured against the universe's drift — {date.today().isoformat()}", "",
         f"{r['calls']:,} replayed {r['timeframe'] or 'all-timeframe'} calls across {r['dates']} week-ends, "
         f"graded at {r['horizon']} trading days. Residual = a call's excess over SPY minus the mean excess "
         f"of every call made the same day. Standard errors are clustered by date. "
         f"Fitted on calls before {r['split']} ({r['train']:,}), tested on calls from it ({r['test']:,}).", "",
         "## Every item, on the whole record", "",
         "| Item | Stance | Claims | Mean residual (pts) | t | Dates | Calls | Agrees with its claim |",
         "|---|---|---|---|---|---|---|---|"]
    for it in r["items"]:
        L.append(f"| {it['item']} | {it['stance']} | {it['claims']} | {pts(it['mean'])} | "
                 f"{'—' if it['t'] is None else f'{it['t']:.1f}'} | {it['dates']} | {it['calls']:,} | "
                 f"{'yes' if it['agrees'] else 'NO'}{'' if it['enough'] else ' (too few dates)'} |")
    L += ["", "A t above about 3 is worth a look; below 2 is noise at this many comparisons.", ""]
    if r.get("pairs"):
        L += ["## How items combine", "",
              "For pairs that fire together often enough: the residual of calls carrying BOTH, against the sum of what each "
              "measures alone. Lift near zero means the two are additive and their separate weights already say everything; "
              "a positive lift on a bull pair (negative on a bear pair) means they confirm each other; the opposite sign means "
              "one is repeating the other. Ranked by the pair's own t.", "",
              "| Item A | Item B | Calls | Dates | Together (pts) | t | A alone (calls) | B alone (calls) | Additive | Lift |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for q in r["pairs"]:
            L.append(f"| {q['a']} | {q['b']} | {q['calls']:,} | {q['dates']} | {pts(q['mean'])} | "
                     f"{'—' if q['t'] is None else f'{q['t']:.1f}'} | {pts(q['a_alone'])} ({q['a_alone_calls']:,}) | "
                     f"{pts(q['b_alone'])} ({q['b_alone_calls']:,}) | {pts(q['additive'])} | {pts(q['lift'])} |")
        L.append("")
    L += [f"## Out of sample: measured weights fitted before {r['split']}, calls scored from it", "",
          "Test calls cut into fifths by the sum of their items' fitted residuals. "
          "A staircase rising from the first fifth to the fifth is the ordering the engine's confidence should give and does not.", "",
          "| Fifth by measured score | Calls | Mean residual (pts) | Share positive |", "|---|---|---|---|"]
    for s in r["measured_staircase"]:
        L.append(f"| {s['fifth']} | {s['calls']:,} | {pts(s['mean_residual'])} | {s['hit'] * 100:.0f}% |")
    if not r["measured_staircase"]:
        L.append("| (not enough test calls) | | | |")
    L += ["", "The engine's own confidence on the same test calls:", "",
          "| Confidence | Calls | Dates | Mean residual (pts) |", "|---|---|---|---|"]
    for k in ("high", "medium", "low", "none"):
        b = r["engine_confidence"].get(k)
        if b:
            L.append(f"| {k} | {b['calls']:,} | {b['dates']} | {pts(b['mean'])} |")
    L += ["", "And by the engine's action on the same test calls (a residual, so a sell 'working' reads negative):", "",
          "| Action | Calls | Mean residual (pts) |", "|---|---|---|"]
    for k, b in sorted(r["engine_action"].items()):
        L.append(f"| {k} | {b['calls']:,} | {pts(b['mean'])} |")
    L += ["", "## Caveats", "",
          "- The universe is today's watchlist and everything ever traded: survivorship inflates long readings. "
          "The date-matched baseline removes the drift but not the selection.",
          "- Items fire together; a measured weight is a marginal association, not a cause.",
          "- One split. A different split date gives different fitted values; treat the staircase's shape as the finding, not its numbers."]
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.measure")
    p.add_argument("--horizon", type=int, default=21, choices=journal.HORIZONS)
    p.add_argument("--timeframe", default="D", help="D, W, M, or 'all'")
    p.add_argument("--split", default="2025-01-01")
    p.add_argument("--out", default=None, help="write the markdown report here too")
    p.add_argument("--save", action="store_true",
                   help="store each item's mean residual per timeframe for the Outlook tab")
    p.add_argument("--source", default="replay", help="replay (the watchlist) or replay-screen (the liquidity screen)")
    p.add_argument("--date-item", default=None,
                   help="measure a date-level item (the exposure dial) by the day's mean excess")
    args = p.parse_args(argv)
    conn = connect()
    if args.save:
        saved = save_weights(conn, args.horizon)
        for tf, info in saved.items():
            print(f"  {tf}: {info['items']} items from {info['calls']:,} calls through {info['through']}")
        for tf, info in save_cuts(conn, args.horizon).items():
            print(f"  {tf}: fifths cut at " + ", ".join(f"{c*100:+.2f}" for c in info["cuts"]) + " pts")
        for tf, fifths in save_record(conn, args.horizon).items():
            print(f"  {tf}: record by fifth — " + "; ".join(
                f"{f}: {v['up_share']*100:.0f}% up of {v['calls']:,}" for f, v in sorted(fifths.items())))
        return 0
    tf = None if args.timeframe == "all" else args.timeframe
    if args.date_item:
        calls = graded(conn, args.horizon, tf, args.source)
        # `graded` keeps only items with a stance, so the dial's windy reading
        # shows up as "None" — which is the right label for it.
        res = date_level(calls, args.date_item)
        print(f"{args.date_item} on {tf or 'all'} calls, {args.horizon} trading days — the day's mean excess over SPY "
              f"when the item read each way (clustered by date):")
        for stance, st in sorted(res.items()):
            print(f"  {stance:<6} {st['dates']:>4} dates  mean {st['mean'] * 100:+.2f} pts  "
                  f"t {st['t'] if st['t'] is None else round(st['t'], 1)}")
        return 0
    r = report(conn, args.horizon, tf, args.split, args.source)
    text = render(r)
    print(text)
    if args.out and not r.get("error"):
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
    return 0 if not r.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
