"""The sell ladder, live: rungs in order, weekly readings on the week's close
only, re-arming after a run, and the entry date of an open position."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ladder

# The ladder was SWITCHED OFF on 2026-09-10 (D97) because it loses to holding.
# The rungs are still computed and still have to be correct — turning it back
# on is one constant, and a broken implementation waiting behind that constant
# is worse than no implementation. So the mechanics below run with it forced
# on, and the switch itself is pinned at the bottom of this file.
SHIPPED_DEFAULT = ladder.ENABLED
ladder.ENABLED = True

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def bars_from(closes, start="2025-01-06"):
    d = date.fromisoformat(start); out = []
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"time": d.isoformat(), "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1000})
        d += timedelta(days=1)
    return out


# 120 flat sessions, then a run: +3% a day for 45 sessions (weekly RSI runs to the 90s),
# then -3% a day for 40 sessions (RSI rolls under 70, price back under the 50-day).
closes = [10.0] * 120
for _ in range(45):
    closes.append(closes[-1] * 1.03)
for _ in range(40):
    closes.append(closes[-1] * 0.97)
bars = bars_from(closes)
fired = ladder.rungs(bars, 60)
names = [f[2] for f in fired]
check("the three rungs fire in order", names[:3] == [ladder.NAMES[1], ladder.NAMES[2], ladder.NAMES[3]], names)
check("rung 1 fires when the close is 60% above the 50-day", fired[0][1] >= 1.6 * 10.0 * 0.9, fired[0])
check("the shares sold add up to the whole slice", abs(sum(f[3] for f in fired[:3]) - 1.0) < 1e-9, fired)
check("without cycles the ladder stops at the third rung", len(fired) == 3, len(fired))
# weekly rungs only on a week's last session
check("the RSI rungs fire on a Friday, the week's last session", all(date.fromisoformat(f[0]).weekday() == 4 for f in fired[1:3]), fired[1:3])
# a partial week does not fire a weekly rung: cut the series on a Wednesday inside the roll
cut = next(i for i, b in enumerate(bars) if b["time"] > fired[1][0] and date.fromisoformat(b["time"]).weekday() == 2 and i > 0)
part = ladder.rungs(bars[:cut + 1], 60)
check("a weekly rung never fires on a partial week", all(date.fromisoformat(f[0]).weekday() == 4 for f in part[1:]), part)

# a second run re-arms once price closed back under the 50-day
closes2 = closes + [closes[-1] * 1.03 ** i for i in range(1, 46)]
bars2 = bars_from(closes2)
hist = ladder.rungs(bars2, 60, cycles=True)
check("with cycles a re-arm marker follows the run", any(h[3] is None for h in hist), [h[2] for h in hist])
check("the next run fires rung 1 again", sum(1 for h in hist if h[2] == ladder.NAMES[1]) == 2, [h[2] for h in hist])
st = ladder.state(bars2, bars2[60]["time"])
check("state reports the current run only, with earlier runs counted", st["runs_done"] == 1 and st["stage"] >= 1, (st["runs_done"], st["stage"]))
check("state names the next rung", st["next"] in (2, 3), st["next"])

# nothing fired: the first rung's price and distance are given
flat = bars_from([10.0 + ((i * 7) % 11 - 5) * 0.03 for i in range(200)])
st0 = ladder.state(flat, flat[60]["time"])
check("a quiet name shows rung 1 as a price about 60% above the 50-day", st0["stage"] == 0 and 15.9 < st0["rungs"][0]["level"] < 16.2, st0["rungs"][0])
check("its distance to rung 1 is about -37%", -0.40 < st0["rungs"][0]["distance"] < -0.35, st0["rungs"][0])
check("the summary is a sentence naming the first rung", "first rung" in (ladder.summary(st0) or ""), ladder.summary(st0))
check("too little history reads as None", ladder.state(flat[:40]) is None)

# entry dates: the current position's first buy after the last flat
def tx(day, sym, qty, kind):
    return {"txn_date": day, "symbol": sym, "quantity": qty, "kind": kind, "price": 1.0, "account": "B"}
T = [tx("2025-01-05", "IREN", 100, "buy"), tx("2025-03-01", "IREN", -100, "sell"),
     tx("2025-06-20", "IREN", 50, "buy"), tx("2025-07-01", "IREN", 25, "buy"),
     tx("2025-02-01", "SOFI", 10, "buy"), tx("2025-02-02", "SOFI", -10, "sell")]
ent = ladder.entry_dates(T)
check("the entry is the buy that took the position off zero, not the first ever", ent.get("IREN") == "2025-06-20", ent)
check("a name sold to zero has no entry", "SOFI" not in ent, ent)


# ---- the switch (D97) ----------------------------------------------------
# Off because it was measured against the wrong baseline: D71 compared it to
# the user's own exits and it won; against buy-and-hold over 3,613 momentum
# entries it costs 2.4% of the book, and rung 1 alone costs 8% of the mean by
# cutting winners early (it sold IREN at 14.00 seven days into a move to 76.87).
check("the shipped default is OFF", SHIPPED_DEFAULT is False,
      "flipping this back on re-enables the alerts, the Outlook card, the "
      "trade-around sell level and the buy-back ladder stage together")
check("and it ships with the reason attached, not just a flag",
      "buy-and-hold" in ladder.DISABLED_NOTE and "IREN" in ladder.DISABLED_NOTE)
ladder.ENABLED = False
check("with the ladder off, state() is None however good the history",
      ladder.state(bars2, bars2[60]["time"]) is None,
      "the same bars that produce a full ladder above")
check("rungs() still computes, so the research scripts and the audit keep working",
      len(ladder.rungs(bars2, 60, cycles=True)) > 0)
ladder.ENABLED = True

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  -> {detail}"))
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
