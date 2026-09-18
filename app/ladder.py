"""The sell ladder — SWITCHED OFF on 2026-09-10. See ENABLED below.

It is off because it was measured against the wrong baseline. D71 checked it
against the user's OWN exits and it beat them on 35 of 51 fires; nobody
checked it against simply holding, and against holding it loses. Turned off by
the user on the evidence in D97, not deleted: the rungs are still computed by
`rungs()`, the research scripts still import it, and turning it back on is one
constant.

Read off IREN's anatomy and kept after testing on 36 names it was not read
from (D64, D65, D69), then checked against the user's own exits since 2022
(D71): half a position is a core; the other half is sold in thirds up three
rungs, in order —

  1. price closes 60% or more above its 50-day average
  2. the weekly RSI (14) closes at 85 or more
  3. the weekly RSI, having been 80 or more in the last eight weeks, closes
     back under 70 — the rest goes, and if the ladder never started, all of
     the slice goes at once

Weekly readings count only on the week's last session, so nothing here is
read before it printed. `state()` gives the rungs for one name from a start
date (the position's entry) to the newest bar: which have fired and when, and
for the ones still ahead, the price or the reading that fires them. The
research script that measured the ladder imports `rungs()` so the live app
and the audit are one implementation.
"""
from __future__ import annotations

from datetime import date

from . import indicators as I

ABOVE_50 = 0.60
RSI_HOT = 85.0
RSI_ARMED = 80.0
RSI_ROLL = 70.0
ARM_WEEKS = 8
NAMES = {1: "60% above the 50-day", 2: "weekly RSI 85", 3: "weekly RSI back under 70 after 80+"}

# Whether the ladder may tell anybody to sell anything.
#
# False since 2026-09-10, on the user's instruction, from this measurement
# (research/audits/edge-log.md, iterations 2-6):
#
#   * Against BUY-AND-HOLD over 3,613 momentum entries in 2,643 symbols, the
#     full ladder costs 2.4% of the book and rung 1 alone costs 8% of the mean.
#     No variant beat holding: rung 3 alone +0.3%, rung 1 alone -1.3%, ladder
#     without rung 1 -1.0%. Robust to injecting 20% delisted-to-zero names.
#   * The mechanism is visible in the mean/median split. The rungs are right
#     about half the time and still destroy the average, because the half they
#     get wrong contains every large winner. Holding's distribution runs p90
#     2.35x, p95 3.13x, p99 6.23x; a rung truncates that tail and keeps the
#     losses.
#   * On this book specifically, rung 1 fired on IREN on 2025-06-27 at 14.00 —
#     seven days after the entry at 10.47, into a move that reached 76.87.
#
# D71 is not wrong and is not in conflict: it measured the ladder against the
# user's OWN exits, which it did beat. Both are true. The rule was validated
# against the wrong baseline, and "better than what you did" is not the same
# claim as "better than doing nothing".
#
# `state()` returns None while this is False, which is the shape every caller
# already handles for "too little history" — so the alerts go quiet, the
# Outlook card disappears, the trade-around sell level falls back to the
# strength-gated SELL INTO level, and the buy-back screen stops reporting a
# ladder stage. Setting it back to True restores all four.
ENABLED = False

DISABLED_NOTE = (
    "The sell ladder is off (2026-09-10). Measured against buy-and-hold over "
    "3,613 momentum entries it cost 2.4% of the book, and rung 1 — 60% above "
    "the 50-day — cost 8% of the mean on its own by cutting winners early: it "
    "sold IREN at 14.00 seven days into a move to 76.87. The earlier finding "
    "that it beat your own exits still stands; it was measured against the "
    "wrong baseline.")


def _isoweek(iso: str) -> tuple:
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d).isocalendar()[:2]


def _weekly(bars):
    """Weekly candles are dated by their last session, so a day maps to the
    week that closed on or before it — its own week on that week's last
    session, the previous one on the other days."""
    weekly = I.resample(bars, "W")
    w_rsi = {x["time"]: x["value"] for x in I.rsi(weekly, 14)}
    wk_of_day, j = {}, 0
    for b in bars:
        while j + 1 < len(weekly) and weekly[j + 1]["time"] <= b["time"]:
            j += 1
        wk_of_day[b["time"]] = j
    return weekly, w_rsi, wk_of_day


def _week_end(bars, i) -> bool:
    """Is bar i the last session of its week? The newest bar only counts on a
    Friday: a partial week's reading can still change before it closes."""
    if i + 1 < len(bars):
        return _isoweek(bars[i + 1]["time"]) != _isoweek(bars[i]["time"])
    y, m, d = (int(x) for x in bars[i]["time"].split("-"))
    return date(y, m, d).weekday() == 4


def rungs(bars: list[dict], start_i: int, cycles: bool = False) -> list[tuple]:
    """The rungs that fired from bar `start_i` on, in order, as
    (date, close, why, share-of-the-slice). Stops after the third unless
    `cycles`: then a run is over once price closes back under its 50-day and
    either the ladder is finished or the roll rung can no longer fire (no
    weekly RSI of 80+ in the last eight weeks); the ladder re-arms for the
    next run. The study (D69) held a run open until the rebuy instead, so a
    rung sold in 2023 would still count in 2025; live, a new run gets its own
    rungs. Not measured separately — it changes which run a rung belongs to,
    never the readings that fire one, and it cannot pre-empt a rung."""
    closes = [b["close"] for b in bars]
    sma50 = {x["time"]: x["value"] for x in I.sma(bars, 50)}
    weekly, w_rsi, wk_of_day = _weekly(bars)
    stage, out = 0, []
    armed_from = 0      # weeks before this cannot arm the roll rung: a new run needs its own 80+
    for i in range(start_i, len(bars)):
        b = bars[i]; c = closes[i]
        week_end = _week_end(bars, i)
        # on a week's last session the day maps to its own week; that is the
        # candle whose RSI a weekly rung reads, and the only day it reads one
        k = wk_of_day[b["time"]] if week_end else max(0, wk_of_day[b["time"]] - (1 if weekly[wk_of_day[b["time"]]]["time"] > b["time"] else 0))
        r = w_rsi.get(weekly[k]["time"]) if week_end else None
        recent = [w_rsi.get(weekly[q]["time"]) for q in range(max(armed_from, k - ARM_WEEKS), k)]
        recent = [x for x in recent if x is not None]
        m = sma50.get(b["time"])
        if stage >= 1 and cycles and m and c < m and (stage == 3 or not recent or max(recent) < RSI_ARMED):
            # the run is over: price has closed back under its 50-day and either
            # the ladder is finished or the roll rung can no longer fire (no 80+
            # in the last eight weeks). Whatever was sold stays sold; the ladder
            # re-arms for the next run. Never pre-empts a rung that could still fire.
            stage, armed_from = 0, k + 1
            out.append((b["time"], c, "re-armed: closed back under the 50-day", None))
            continue
        if stage == 3:
            continue
        roll = r is not None and recent and max(recent) >= RSI_ARMED and r < RSI_ROLL
        if stage == 0 and m and c / m - 1 >= ABOVE_50:
            out.append((b["time"], c, NAMES[1], 1 / 3)); stage = 1
        elif stage == 1 and r is not None and r >= RSI_HOT:
            out.append((b["time"], c, NAMES[2], 1 / 3)); stage = 2
        elif stage in (1, 2) and roll:
            out.append((b["time"], c, NAMES[3], 1 - sum(x[3] for x in current_run(out) if x[3] is not None))); stage = 3
        elif stage == 0 and roll:
            out.append((b["time"], c, NAMES[3] + " (whole slice)", 1.0)); stage = 3
        if stage == 3 and not cycles:
            break
    return out


def current_run(fired: list[tuple]) -> list[tuple]:
    """The rungs of the latest run only (after the last re-arm marker)."""
    cut = max((i for i, x in enumerate(fired) if x[3] is None), default=-1)
    return [x for x in fired[cut + 1:]]


def entry_dates(txns: list[dict]) -> dict[str, str]:
    """For every name still held, the date the current position left zero."""
    from .holdings import ACQUIRE, DISPOSE, apply_reorganisations
    qty: dict[str, float] = {}
    entry: dict[str, str] = {}
    for t in sorted(apply_reorganisations(txns), key=lambda x: x["txn_date"]):
        s = t.get("symbol")
        if not s or not t.get("quantity") or t.get("kind") not in ACQUIRE | DISPOSE:
            continue
        q = qty.get(s, 0.0)
        if abs(q) < 1e-9:
            entry[s] = t["txn_date"]
        q += t["quantity"]
        qty[s] = q
        if abs(q) < 1e-9:
            entry.pop(s, None)
    return entry


def state(bars: list[dict], since: str | None = None) -> dict | None:
    """The ladder for one name, from `since` (the position's entry) to the
    newest bar. None when the ladder is switched off, or when there is too
    little history to read it."""
    if not ENABLED:
        return None
    if len(bars) < 80:
        return None
    start_i = next((i for i, b in enumerate(bars) if since and b["time"] >= since), None)
    if start_i is None:
        start_i = max(60, len(bars) - 250)
    start_i = max(start_i, 50)
    history = rungs(bars, start_i, cycles=True)
    fired = current_run(history)
    runs_done = sum(1 for x in history if x[3] is None)
    last = bars[-1]
    closes = [b["close"] for b in bars]
    sma50 = I.sma(bars, 50)
    m = sma50[-1]["value"] if sma50 else None
    weekly, w_rsi, wk_of_day = _weekly(bars)
    k = wk_of_day[last["time"]]
    r_now = w_rsi.get(weekly[k]["time"])            # this week so far, or the completed week on a Friday
    r_prev = w_rsi.get(weekly[k - 1]["time"]) if k >= 1 else None
    recent = [w_rsi.get(weekly[q]["time"]) for q in range(max(0, k - ARM_WEEKS), k)]
    recent = [x for x in recent if x is not None]
    armed = bool(recent) and max(recent) >= RSI_ARMED
    stage = 3 if any(f[2].startswith(NAMES[3]) for f in fired) else len(fired)
    price = last["close"]
    out_rungs = []
    for n in (1, 2, 3):
        f = next((x for x in fired if x[2].startswith(NAMES[n])), None)
        row = {"n": n, "name": NAMES[n], "fired": f[0] if f else None, "fired_at": round(f[1], 4) if f else None}
        if n == 1:
            row["level"] = round(m * (1 + ABOVE_50), 4) if m else None
            row["reading"] = round(price / m - 1, 4) if m else None
            row["distance"] = round(price / (m * (1 + ABOVE_50)) - 1, 4) if m else None
        elif n == 2:
            row["reading"] = round(r_now, 1) if r_now is not None else None
            row["target"] = RSI_HOT
        else:
            row["reading"] = round(r_now, 1) if r_now is not None else None
            row["armed"] = armed
            row["peak8"] = round(max(recent), 1) if recent else None
            row["target"] = RSI_ROLL
        out_rungs.append(row)
    nxt = next((r for r in out_rungs if not r["fired"]), None)
    if stage == 0 and nxt and armed:
        # the ladder has not started but the roll rung would take the whole slice
        nxt = out_rungs[2]
    return {"since": bars[start_i]["time"], "asof": last["time"], "price": price, "sma50": round(m, 4) if m else None,
            "stage": stage, "rungs": out_rungs, "next": nxt["n"] if nxt else None,
            "weekly_rsi": round(r_now, 1) if r_now is not None else None,
            "weekly_rsi_prev": round(r_prev, 1) if r_prev is not None else None,
            "runs_done": runs_done,
            "armed": armed,
            "near": bool(m) and price / (m * (1 + ABOVE_50)) - 1 >= -0.10 and stage == 0}


def summary(st: dict | None) -> str | None:
    """One sentence for a row or an alert."""
    if not st:
        return None
    price = st["price"]
    r1 = st["rungs"][0]
    if st["stage"] >= 3:
        f = st["rungs"][2]
        return (f"Ladder done: the rest sold {f['fired']} at {f['fired_at']:.2f} on the weekly RSI rolling under 70. "
                f"It re-arms when price closes back under its 50-day ({st['sma50']:.2f}).")
    if st["stage"] == 2:
        return (f"Two rungs sold ({st['rungs'][0]['fired']}, {st['rungs'][1]['fired']}); the rest goes when the weekly RSI "
                f"closes under 70 — it is {st['weekly_rsi']}.")
    if st["stage"] == 1:
        return (f"A third sold {r1['fired']} at {r1['fired_at']:.2f}, 60% above the 50-day. Next third at weekly RSI 85 "
                f"(now {st['weekly_rsi']})" + (f"; the rest when it closes under 70, which is armed." if st["armed"] else "."))
    if st["armed"]:
        return (f"Weekly RSI was {st['rungs'][2]['peak8']} in the last eight weeks; a weekly close under 70 sells the whole slice "
                f"(now {st['weekly_rsi']}). Rung 1 is {r1['level']:.2f}, {r1['distance']*100:+.0f}% away.")
    if r1["level"]:
        return f"Nothing fired. The first rung is {r1['level']:.2f} (60% above the 50-day), {r1['distance']*100:+.0f}% from here; weekly RSI {st['weekly_rsi']}."
    return "Nothing fired."
