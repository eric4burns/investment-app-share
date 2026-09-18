"""The one-close engine against the two-close engine, on the same dates.

Both replays grade the same names at the same week-ends against SPY; the
difference is only whether an evidence item needed to read the same way for
two consecutive bars before it voted. Reported per timeframe and horizon:
graded calls, hit rate, mean excess, and the same for buys and sells alone.

    python3 research/confirm-compare.py [--md out.md]
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ledger, measure  # noqa: E402


def table(conn, source, horizon):
    # The replayed sources live in ledger-replay.db after the split; measure.history
    # reads them through the attached schema, where journal.history would find an
    # empty table.
    _, rows = measure.history(conn, source, limit=500000)
    out = defaultdict(list)
    for g in rows:
        h = g["horizons"].get(horizon) or {}
        if h.get("status") != "scored" or h.get("excess") is None:
            continue
        tf = g.get("timeframe") or "D"
        # signed by the call: a sell that fell is a hit
        sign = -1 if g["action"] in ("sell", "trim") else (1 if g["action"] in ("buy", "add") else 0)
        out[(tf, "all")].append((h["excess"], sign))
        if sign:
            out[(tf, g["action"])].append((h["excess"], sign))
    return out


def fmt(vals):
    if not vals:
        return "—"
    n = len(vals)
    scored = [(e * s if s else e) for e, s in vals]
    hit = sum(1 for e, s in vals if (e * s if s else e) > 0) / n
    mean = sum(scored) / n
    return f"{n:,} · {hit*100:.0f}% · {mean*100:+.2f}%"


def main():
    conn = ledger.connect()
    lines = ["# One close against two — replay comparison", ""]
    for horizon in (21, 63):
        a, b = table(conn, "replay", horizon), table(conn, "replay-confirm2", horizon)
        lines += [f"## {horizon} trading days", "", "| Timeframe · calls | One close (n · hit · mean) | Two closes (n · hit · mean) |", "|---|---|---|"]
        for key in sorted(set(a) | set(b)):
            lines.append(f"| {key[0]} · {key[1]} | {fmt(a.get(key))} | {fmt(b.get(key))} |")
        lines.append("")
    lines.append("Hit = the call's direction was right against SPY (a sell counts when the name lagged); "
                 "mean = the signed excess over SPY. Hold rows are unsigned excess. Same names, same dates, "
                 "same survivorship caveat as every replay.")
    text = "\n".join(lines)
    print(text)
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(text + "\n")


if __name__ == "__main__":
    main()
