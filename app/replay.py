"""Run the verdict engine at every past week-end, and grade what it would have said.

    python3 -m app.replay run                    # every name, 2022 to the last Friday
    python3 -m app.replay run --start 2024-01-01 --symbol IREN
    python3 -m app.replay status                 # how far it has got
    python3 -m app.replay report [--horizon 21]  # the calibration, on replayed calls

## Why

`calibration.py` can say which parts of the verdict engine work — by action,
by timeframe, by confidence, by individual condition — but only from graded
calls, and the app began recording calls on 2026-09-01. Twenty calls across
ten separate days is its floor, so the first honest reading was six weeks
away, and every change to the engine until then would have been a guess.

The engine is deterministic on the bars it is given. So it can be run at any
past date on the bars that existed then, and the call it makes is the call it
would have made. Do that at every week-end since 2022 across every name held
or watched and there are tens of thousands of graded calls tonight instead of
twenty in October. That is what this does.

## What it is not

It is not the live journal. Replayed calls go under `source='replay'`, never
`'app'`, because a call reconstructed afterwards — however honestly the bars
were truncated — is not a call made before the outcome was known, and the two
must never be averaged together.

Two things the live engine has that the replay does not, and both are named
on every report rather than left to be discovered:

  * No position. Every name is scored as if unheld, so `trim` and `add` never
    fire — those need a position — and the calls are buy, hold and sell.
  * No market sentiment. The fear-and-greed series is cached from 2026-08
    onward only, so that evidence item is absent from every replayed call.

And one thing to keep in view: the universe is the watchlist as it stands
today, which is a list of names that were worth watching. That is the same
survivorship caveat the backtester carries, and it biases every hit rate here
upward by an amount nobody can state.

## Lookahead

Bars are truncated to the decision date before the engine sees them, the
same rule `backtest.py` lives by. The weekly and monthly readings are
resampled from the truncated daily bars, so the last weekly bar on a Friday is
that week's complete bar and the last monthly bar is a partial month — which
is also what the live engine reads on a Friday.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime

from . import calibration, journal, prices, split_replay, verdicts, watchlist
from .ledger import connect

DEFAULT_START = "2022-01-01"

# Where the replayed rows live. Once `python3 -m app.split_replay --apply`
# has moved them to ledger-replay.db every read and write here goes through
# the attached `replay` schema; before that — a fresh clone — they sit in
# the ledger as they always did. split_replay.prefix() is the one place that
# decides, so this module only ever names the table through it.


def universe(conn) -> list[str]:
    """Every equity ever traded plus every watched name, deduplicated."""
    traded = [r["symbol"] for r in conn.execute(
        """SELECT DISTINCT s.symbol FROM securities s JOIN transactions t ON t.security_id = s.id
            WHERE s.kind = 'equity' AND s.symbol NOT LIKE 'PLAN:%' AND s.symbol NOT LIKE 'CUSIP:%'
            ORDER BY s.symbol""")]
    watchlist.ensure_schema(conn)
    watched = [r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]
    seen, out = set(), []
    for s in traded + watched:
        s = (s or "").strip().upper()
        if s and s not in seen and not prices.is_money_market(s):
            seen.add(s)
            out.append(s)
    return out


def week_ends(conn, start: str, end: str) -> list[str]:
    """The last trading day of every ISO week, from the bar calendar itself."""
    days = [r[0] for r in conn.execute(
        """SELECT DISTINCT bar_date FROM prices WHERE source LIKE 'alpaca%'
            AND bar_date BETWEEN ? AND ? ORDER BY bar_date""", (start, end))]
    by_week: dict[tuple[int, int], str] = {}
    for d in days:
        y, m, dd = (int(x) for x in d.split("-"))
        iso = date(y, m, dd).isocalendar()
        by_week[(iso[0], iso[1])] = d          # later days overwrite: the last one wins
    return sorted(by_week.values())


def month_ends(dates: list[str]) -> set[str]:
    last: dict[str, str] = {}
    for d in dates:
        last[d[:7]] = d
    return set(last.values())


def _done(conn, symbol: str, source: str = "replay") -> set[str]:
    pfx = split_replay.prefix(conn, source)
    return {r[0] for r in conn.execute(
        f"SELECT date FROM {pfx}decisions WHERE source=? AND symbol=? AND timeframe='D'",
        (source, symbol))}


def _record(conn, pfx: str, date: str, symbol: str, source: str, action: str,
            price, timeframe, confidence, flip, evidence) -> int | None:
    """One replayed call into `pfx`decisions, exactly as journal.record writes
    a replay source: one row per (date, symbol, timeframe), replaced on a
    re-run; evidence replaced with it; no rationale and no evidence detail
    (journal.MEASURED_ONLY — the prose was how the ledger reached 1.2 GB).
    journal.record itself cannot be used because it names the bare table,
    which is the ledger's, not the replay file's."""
    if action not in journal.SIGN:
        raise ValueError(f"unknown action {action!r}")
    conn.execute(
        f"""INSERT INTO {pfx}decisions (date, symbol, source, action, timeframe,
                                        price, confidence, flip, rationale)
            VALUES (?,?,?,?,?,?,?,?,NULL)
            ON CONFLICT (date, symbol, timeframe) WHERE source = '{source}'
            DO UPDATE SET action=excluded.action, price=excluded.price,
                          confidence=excluded.confidence, flip=excluded.flip,
                          rationale=excluded.rationale""",
        (date, symbol, source, action, timeframe, price, confidence, flip))
    row = conn.execute(
        f"""SELECT id FROM {pfx}decisions WHERE source=? AND date=? AND symbol=?
            AND timeframe IS ?""", (source, date, symbol, timeframe)).fetchone()
    did = row[0] if row else None
    if did is None or evidence is None:
        return did
    conn.execute(f"DELETE FROM {pfx}decision_evidence WHERE decision_id = ?", (did,))
    seen = set()
    for e in evidence:
        key = (e.get("name"), e.get("stance"))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        conn.execute(
            f"""INSERT INTO {pfx}decision_evidence (decision_id, name, stance, weight, detail)
                VALUES (?,?,?,?,NULL)""",
            (did, key[0], key[1], float(e.get("weight") or 1.0)))
    return did


def screen_sample(conn, n: int, seed: int = 7) -> list[str]:
    """A seeded random sample of the liquidity screen's kept names — a
    universe chosen for trading enough today, not for having gone up."""
    import random
    from . import discover
    names = [r["symbol"] for r in discover.kept(conn)]
    rng = random.Random(seed)
    rng.shuffle(names)
    return sorted(names[:n])


def clear(conn, symbols: list[str] | None = None, source: str = "replay") -> int:
    """Remove replayed calls (their evidence goes with them) so a changed
    engine can be replayed afresh. Live 'app' calls are never touched."""
    journal.ensure_schema(conn)
    pfx = split_replay.prefix(conn, source)
    if symbols:
        n = 0
        for s in symbols:
            n += conn.execute(f"DELETE FROM {pfx}decisions WHERE source=? AND symbol=?",
                              (source, s.strip().upper())).rowcount
    else:
        n = conn.execute(f"DELETE FROM {pfx}decisions WHERE source=?", (source,)).rowcount
    conn.execute(f"""DELETE FROM {pfx}decision_evidence
                     WHERE decision_id NOT IN (SELECT id FROM {pfx}decisions)""")
    conn.commit()
    return n


def run(conn, start: str = DEFAULT_START, end: str | None = None,
        symbols: list[str] | None = None, log=None, redo: bool = False,
        source: str = "replay", confirm: int = 1) -> dict:
    say = log or (lambda *a: None)
    journal.ensure_schema(conn)
    pfx = split_replay.prefix(conn, source)
    if redo:
        say(f"redo: cleared {clear(conn, symbols, source):,} replayed calls")
    end = end or date.today().isoformat()
    syms = [s.strip().upper() for s in symbols] if symbols else universe(conn)
    dates = week_ends(conn, start, end)
    # The last week-end must be a FINISHED week: a Wednesday scored as the
    # week's last bar would be a partial weekly bar recorded as if complete.
    # "Finished" means the week is over — its ISO week is earlier than the
    # end date's, or the end date itself is a Friday or later.
    if dates:
        last = date.fromisoformat(dates[-1])
        edge = date.fromisoformat(end[:10])
        same_week = last.isocalendar()[:2] == edge.isocalendar()[:2]
        if same_week and edge.isoweekday() < 5:
            dates = dates[:-1]
    m_ends = month_ends(dates)
    say(f"replay: {len(syms)} names x {len(dates)} week-ends, {dates[0] if dates else '-'} to "
        f"{dates[-1] if dates else '-'}")

    # The measured profile is passed so replayed weekly calls carry the same
    # confidence the live engine gives — fitted on this very record, so the
    # calibration of confidence on replay rows is IN SAMPLE. The honest test
    # of the ordering is measure.py's split, not calibration's by-confidence.
    from . import measure
    measured = {tf: measure.load_profile(conn, tf) for tf in ("D", "W", "M")}
    # Relative strength across the universe at every week-end, computed
    # before the loop: 44,000 rank lookups from cached series, a few seconds.
    say("ranking relative strength at every week-end...")
    series = {s: (prices.load_series(conn, s), prices.sorted_dates(conn, s)) for s in syms}
    ranks_by_date: dict[str, dict[str, int]] = {}
    for d in dates:
        rows = [{"symbol": s, **watchlist.momentum_at(ser, dts, d)} for s, (ser, dts) in series.items()]
        watchlist.rank_relative_strength(rows)
        ranks_by_date[d] = {r["symbol"]: r["rs_rank"] for r in rows if r.get("rs_rank") is not None}
    from . import regime
    dial_by_date = {d: regime.reading(conn, d) for d in dates}
    index_by_date = {d: regime.index_read(conn, d, (measured or {}).get("W")) for d in dates}
    recorded, skipped, errors, t0 = 0, [], [], time.time()
    for n, sym in enumerate(syms, 1):
        bars_all, _proxy = prices.analysis_bars(conn, sym, "2015-01-01", end)
        if len(bars_all) < 80:
            skipped.append((sym, f"{len(bars_all)} bars"))
            continue
        done = _done(conn, sym, source)
        times = [b["time"] for b in bars_all]
        wrote = 0
        for d in dates:
            if d in done:
                continue
            # bisect on the bar times: everything on or before the date.
            lo, hi = 0, len(times)
            while lo < hi:
                mid = (lo + hi) // 2
                if times[mid] <= d:
                    lo = mid + 1
                else:
                    hi = mid
            visible = bars_all[:lo]
            if len(visible) < 60 or visible[-1]["time"] < d[:8] + "01":
                continue                       # the name did not trade that month
            try:
                both = verdicts.both_timeframes(visible, None, None, measured,
                                                {"rs_rank": ranks_by_date.get(d, {}).get(sym),
                                                 "regime": dial_by_date.get(d),
                                                 "index": index_by_date.get(d)}, confirm)
            except Exception as exc:                       # noqa: BLE001
                # One bad series on one date must not end a forty-minute run.
                # It is logged and skipped, and the gap is visible in status.
                errors.append((sym, d, f"{type(exc).__name__}: {exc}"))
                say(f"  !! {sym} {d}: {type(exc).__name__}: {exc}")
                continue
            for tf, key in (("D", "daily"), ("W", "weekly"), ("M", "monthly")):
                v = both[key]
                if v.get("insufficient"):
                    continue
                if tf == "M" and d not in m_ends:
                    continue
                _record(conn, pfx, d, sym, source, v["verdict"], v.get("price"), tf,
                        v.get("confidence"), v.get("flip"), v.get("evidence"))
                wrote += 1
                # Commit in small batches. One transaction per name held the
                # ledger's write lock for the whole ten seconds of scoring,
                # and the two syncs sharing the database died of it.
                if wrote % 30 == 0:
                    conn.commit()
        conn.commit()
        recorded += wrote
        say(f"  [{n:>3}/{len(syms)}] {sym:<8} {wrote:>4} calls  "
            f"({time.time() - t0:,.0f}s elapsed)")
    return {"symbols": len(syms), "dates": len(dates), "recorded": recorded,
            "skipped": skipped, "errors": errors, "seconds": round(time.time() - t0)}


def status(conn, source: str = "replay") -> dict:
    journal.ensure_schema(conn)
    pfx = split_replay.prefix(conn, source)
    row = conn.execute(
        f"""SELECT COUNT(*) n, COUNT(DISTINCT symbol) syms, COUNT(DISTINCT date) days,
                   MIN(date) first, MAX(date) last
              FROM {pfx}decisions WHERE source=?""", (source,)).fetchone()
    by_tf = {r[0]: r[1] for r in conn.execute(
        f"SELECT timeframe, COUNT(*) FROM {pfx}decisions WHERE source=? GROUP BY timeframe",
        (source,))}
    # Written in the last few minutes: a run is in progress. Read here so the
    # dashboard never has to name the table itself.
    running = bool(conn.execute(
        f"""SELECT 1 FROM {pfx}decisions WHERE source=?
             AND created_at >= datetime('now', '-3 minutes') LIMIT 1""", (source,)).fetchone())
    return {"calls": row["n"], "symbols": row["syms"], "days": row["days"],
            "first": row["first"], "last": row["last"], "by_timeframe": by_tf,
            "running": running, "where": pfx.rstrip(".")}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.replay")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--start", default=DEFAULT_START)
    r.add_argument("--end", default=None)
    r.add_argument("--symbol", action="append", dest="symbols")
    r.add_argument("--redo", action="store_true",
                   help="clear the replayed calls first, so a changed engine is measured afresh")
    r.add_argument("--confirm", type=int, default=1, metavar="N",
                   help="an evidence item votes only if it read the same way for N consecutive bars; "
                        "recorded under source replay-confirmN so it can be measured against the one-close engine")
    r.add_argument("--from-screen", type=int, default=None, metavar="N",
                   help="replay a seeded random sample of N names from the liquidity screen, under source replay-screen")
    sub.add_parser("status")
    rep = sub.add_parser("report")
    rep.add_argument("--horizon", type=int, default=21, choices=journal.HORIZONS)
    args = p.parse_args(argv)

    conn = connect()
    if args.cmd == "run":
        symbols, source = args.symbols, "replay"
        if args.confirm and args.confirm > 1:
            source = f"replay-confirm{args.confirm}"
        if args.from_screen:
            symbols, source = screen_sample(conn, args.from_screen), "replay-screen"
            print(f"screen universe: {len(symbols)} names sampled from the liquidity screen")
        out = run(conn, args.start, args.end, symbols, log=print, redo=args.redo, source=source,
                  confirm=args.confirm)
        print(f"\nrecorded {out['recorded']:,} calls over {out['symbols']} names in "
              f"{out['seconds']:,}s; skipped {len(out['skipped'])}")
        for sym, why in out["skipped"]:
            print(f"  skipped {sym}: {why}")
        if out["errors"]:
            print(f"  {len(out['errors'])} date(s) could not be scored:")
            for sym, d, why in out["errors"][:20]:
                print(f"    {sym} {d}: {why}")
        return 0
    if args.cmd == "status":
        s = status(conn)
        print(f"{s['calls']:,} replayed calls on {s['symbols']} names across {s['days']} "
              f"week-ends, {s['first']} to {s['last']}; by timeframe {s['by_timeframe']}")
        return 0
    if args.cmd == "report":
        print("Replayed calls: no position (so no trim or add), no market sentiment, "
              "and today's watchlist as the universe. See the module docstring.\n")
        return calibration.main(["--horizon", str(args.horizon), "--source", "replay"])
    return 2


if __name__ == "__main__":
    sys.exit(main())
