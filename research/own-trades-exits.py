"""The sell ladder against the user's own exits since 2022.

For every closed position trade in the ledger (one round trip per name, the
way the Trades tab counts them), on a name with daily bars: where would the
ladder have sold instead? The ladder is the one the anatomy gave and the
out-of-sample study kept (D69): a third at 60% above the 50-day average, a
third at weekly RSI 85, the rest when the weekly RSI closes back under 70
after being 80 or more in the last eight weeks. The rungs are evaluated from
the entry date forward, through the actual exit and on for 126 sessions, so
a rung the user left on the table shows up too.

Reported per trade: the actual exit against the ladder's average exit, in
percent, and what holding to today would have done. Percent per trade, as
asked.

    python3 research/own-trades-exits.py [--md out.md]
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import holdings, ladder, ledger, performance, prices  # noqa: E402


def ladder_points(bars, start_i):
    return ladder.rungs(bars, start_i)


def main():
    conn = ledger.connect()
    today = datetime.date.today().isoformat()
    txns = performance.load_transactions(conn, "2015-01-01", today)
    trips = [t for t in holdings.position_trades(txns, today) if t.get("exit_date") and not t["symbol"].startswith("PLAN") and t["entry_date"] >= "2022-01-01"]
    L = ["# The sell ladder against your own exits — 2026-09-05", "",
         "Every closed round trip since 2022 on a name with daily bars. 'Ladder exit' is the average price of the ladder's rungs that fired "
         "from your entry date onward (through your exit and 126 sessions past it), weighted by the third each rung sells; a rung that fired after "
         "your exit is a sale you would still have had coming. 'Held to today' is the last close. All in percent against your actual exit price.", "",
         "| Symbol | Entry | Exit | Shares | Your exit | Ladder exit | Ladder vs yours | Rungs fired (date @ price) | Held to today vs yours |", "|---|---|---|---|---|---|---|---|---|"]
    rows, skipped = [], []
    for t in sorted(trips, key=lambda t: t["exit_date"]):
        sym = t["symbol"]
        bars = prices.load_bars(conn, sym, "2015-01-01", today)
        if len(bars) < 120 or not t.get("shares_out"):
            continue
        idx = {b["time"]: i for i, b in enumerate(bars)}
        start_i = next((i for i, b in enumerate(bars) if b["time"] >= t["entry_date"]), None)
        if start_i is None or start_i < 60:
            continue
        your_exit = t["sold"] / t["shares_out"] if t["shares_out"] else None
        if not your_exit:
            continue
        # a split between the trade and today leaves the ledger's price on a different scale from the adjusted bars
        exit_close = bars[idx[t["exit_date"]]]["close"] if t["exit_date"] in idx else None
        if exit_close and not 0.6 < your_exit / exit_close < 1.6:
            skipped.append(f"{sym} {t['entry_date']}→{t['exit_date']} (ledger {your_exit:.2f} vs bar {exit_close:.2f})")
            continue
        rungs = ladder_points(bars, start_i)
        # only rungs up to 126 sessions after the exit count
        exit_i = idx.get(t["exit_date"], start_i)
        rungs = [r for r in rungs if idx.get(r[0], 10**9) <= exit_i + 126]
        ladder_exit = (sum(p * w for _, p, _, w in rungs) / sum(w for *_, w in rungs)) if rungs else None
        held = bars[-1]["close"]
        rows.append({"sym": sym, "entry": t["entry_date"], "exit": t["exit_date"], "shares": t["shares_out"], "yours": your_exit,
                     "ladder": ladder_exit, "rungs": rungs, "held": held,
                     "vs": (ladder_exit / your_exit - 1) if ladder_exit else None, "held_vs": held / your_exit - 1})
    for r in rows:
        L.append(f"| {r['sym']} | {r['entry']} | {r['exit']} | {r['shares']:g} | {r['yours']:.2f} | {('%.2f' % r['ladder']) if r['ladder'] else 'no rung fired'} | "
                 f"{('%+.0f%%' % (r['vs']*100)) if r['vs'] is not None else '—'} | {'; '.join(f'{d} @ {p:.2f} ({why})' for d, p, why, _ in r['rungs']) or '—'} | {r['held_vs']*100:+.0f}% |")
    fired = [r for r in rows if r["vs"] is not None]
    at_entry = [r for r in fired if r["rungs"][0][0] <= r["entry"]]
    after_exit = [r for r in fired if all(d > r["exit"] for d, *_ in r["rungs"])]
    L.append("")
    if skipped:
        L.append(f"- Left out, prices not on the same scale as the bars (a split since): {'; '.join(skipped)}")
    L.append(f"- Bought already at a rung (the ladder was selling on your entry day): {len(at_entry)} trades — " + ", ".join(f"{r['sym']} {r['entry']}" for r in at_entry))
    L.append(f"- Every rung fired only after you had already sold: {len(after_exit)} trades — " + ", ".join(f"{r['sym']} {r['exit']} ({r['vs']*100:+.0f}%)" for r in after_exit))
    inside = [r for r in fired if r not in at_entry and r not in after_exit]
    if inside:
        L.append(f"- Rung fired while you held (a sell signal you could have acted on): {len(inside)} trades, ladder vs yours median {sorted(r['vs'] for r in inside)[len(inside)//2]*100:+.0f}% — "
                 + ", ".join(f"{r['sym']} {r['exit']} ({r['vs']*100:+.0f}%)" for r in inside))
    none = [r for r in rows if r["vs"] is None]
    if none:
        hv = sorted(r["held_vs"] for r in none)
        L.append(f"- No rung fired, ladder keeps you in: {len(none)} trades; holding to today vs your exit median {hv[len(hv)//2]*100:+.0f}%, "
                 f"better than your exit on {sum(1 for x in hv if x > 0)} of {len(none)}")
    L.append("")
    if fired:
        med = sorted(r["vs"] for r in fired)[len(fired) // 2]
        better = sum(1 for r in fired if r["vs"] > 0)
        L.append(f"**{len(rows)} closed trades since 2022; the ladder fired on {len(fired)}.** Where it fired, its exit was above yours on {better} of {len(fired)}, "
                 f"median {med*100:+.0f}% against your exit price. On the other {len(rows) - len(fired)} no rung fired: the ladder would have kept you in, "
                 f"and holding those to today is {'better' if sorted(r['held_vs'] for r in rows if r['vs'] is None)[len([r for r in rows if r['vs'] is None]) // 2] > 0 else 'worse'} than your exit in median.")
    text = "\n".join(L)
    print(text)
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(text + "\n")


if __name__ == "__main__":
    main()
