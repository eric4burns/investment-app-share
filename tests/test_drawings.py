"""Hand-drawn chart annotations.

A drawing you cannot delete is worse than no drawing at all, and a drawing that
stores nonsense takes the whole price pane down with it when the renderer tries
to paint it. So these tests are mostly about the two failures that actually
happened: geometry that cannot be drawn being accepted, and a drawing surviving
the delete that was supposed to remove it.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import drawings as D

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    D.ensure_schema(conn)
    return conn


def refuses(conn, kind, points, why):
    try:
        D.add(conn, "IREN", "D", kind, points)
        check(f"refuses {why}", False, "it was accepted")
    except ValueError as exc:
        check(f"refuses {why}", True, str(exc)[:60])


# ------------------------------------------------------------ round trip ----
conn = db()
made = D.add(conn, "iren", "d", "trend", [["2026-01-02", 10.0], ["2026-03-02", 20.0]])
check("add returns the new id", isinstance(made["id"], int) and made["id"] > 0, made["id"])

got = D.for_chart(conn, "IREN", "D")
check("the drawing comes back on its own chart", len(got) == 1, f"{len(got)} found")
check("its anchors survive the round trip",
      got and got[0]["points"] == [["2026-01-02", 10.0], ["2026-03-02", 20.0]],
      got[0]["points"] if got else None)

# Symbol and timeframe are normalised on the way in, so a lowercase lookup and a
# lowercase save have to land on the same chart.
check("lowercase symbol is stored uppercased",
      len(D.for_chart(conn, "iren", "d")) == 1)
check("a drawing does not leak onto another symbol",
      D.for_chart(conn, "NVDA", "D") == [])
check("a drawing does not leak onto another timeframe",
      D.for_chart(conn, "IREN", "W") == [])

# ---------------------------------------------------------------- geometry --
# Every one of these renders as either an invisible line or a line that drags
# the price scale to infinity, which is what "the whole chart disappeared"
# looked like from the outside.
refuses(conn, "trend", [["2026-01-02", 10.0]], "a trend with one anchor")
refuses(conn, "trend", [["2026-01-02", 10.0], ["2026-01-02", 20.0]],
        "a vertical trend (both anchors same time)")
refuses(conn, "channel", [["2026-01-02", 1.0], ["2026-02-02", 2.0]],
        "a channel missing its offset anchor")
refuses(conn, "trend", [["2026-01-02", 10.0], ["2026-03-02", float("inf")]],
        "an infinite price")
refuses(conn, "trend", [["2026-01-02", 10.0], ["2026-03-02", float("nan")]],
        "a NaN price")
refuses(conn, "trend", [["2026-01-02", 10.0], ["", 20.0]], "an empty timestamp")
refuses(conn, "trend", [["2026-01-02", 10.0], ["2026-03-02", "abc"]],
        "a non-numeric price")
refuses(conn, "scribble", [["2026-01-02", 10.0], ["2026-03-02", 20.0]],
        "a kind the renderer does not know")

# A level has one anchor; a second one would silently be ignored, which means a
# drawing that does not match what was placed.
refuses(conn, "level", [["2026-01-02", 10.0], ["2026-03-02", 20.0]],
        "a level with two anchors")

check("nothing invalid was stored", len(D.for_chart(conn, "IREN", "D")) == 1,
      f"{len(D.for_chart(conn, 'IREN', 'D'))} rows")

# ------------------------------------------------------------------- ray ----
# A ray is a trend the renderer keeps extending. The anchors are identical, so
# the same geometry rules have to apply to both — a vertical ray is exactly as
# undrawable as a vertical trend.
ray = D.add(conn, "IREN", "D", "ray", [["2026-01-02", 5.0], ["2026-02-02", 7.0]])
check("a ray is accepted", ray["kind"] == "ray", ray["kind"])
refuses(conn, "ray", [["2026-01-02", 5.0], ["2026-01-02", 7.0]], "a vertical ray")

# ------------------------------------------------------------------ move ----
moved = D.move(conn, made["id"], [["2026-01-02", 11.0], ["2026-03-02", 21.0]])
check("move keeps the id", moved.get("id") == made["id"], moved.get("id"))
after = [d for d in D.for_chart(conn, "IREN", "D") if d["id"] == made["id"]][0]
check("move rewrites the anchors",
      after["points"] == [["2026-01-02", 11.0], ["2026-03-02", 21.0]], after["points"])
check("move did not create a second drawing",
      len(D.for_chart(conn, "IREN", "D")) == 2,
      f"{len(D.for_chart(conn, 'IREN', 'D'))} rows")

# Dragging an endpoint on top of the other is the easy way to make a vertical
# line by accident, and it has to be refused on the way in like any other.
try:
    D.move(conn, made["id"], [["2026-01-02", 11.0], ["2026-01-02", 21.0]])
    check("move refuses geometry add would refuse", False, "it was accepted")
except ValueError:
    check("move refuses geometry add would refuse", True)
still = [d for d in D.for_chart(conn, "IREN", "D") if d["id"] == made["id"]][0]
check("a refused move leaves the drawing as it was",
      still["points"] == [["2026-01-02", 11.0], ["2026-03-02", 21.0]], still["points"])

check("moving a drawing that does not exist is an error, not a crash",
      "error" in D.move(conn, 999999, [["2026-01-02", 1.0], ["2026-02-02", 2.0]]))

# ---------------------------------------------------------------- delete ----
# The reported failure was a drawing with no way to remove it. Deleting has to
# actually reduce what the chart hands back, not just report success.
before = len(D.for_chart(conn, "IREN", "D"))
D.remove(conn, made["id"])
gone = D.for_chart(conn, "IREN", "D")
check("remove deletes exactly one drawing", len(gone) == before - 1,
      f"{before} -> {len(gone)}")
check("remove deletes the one asked for",
      all(d["id"] != made["id"] for d in gone))
check("removing it twice is harmless", D.remove(conn, made["id"])["removed"] == made["id"])

# Clear is per chart. Wiping every drawing everywhere from a button labelled
# "clear" would be unrecoverable, since there is no undo.
D.add(conn, "IREN", "D", "level", [["2026-01-02", 12.0]])
D.add(conn, "NVDA", "D", "level", [["2026-01-02", 90.0]])
D.add(conn, "IREN", "W", "level", [["2026-01-02", 12.0]])
cleared = D.clear(conn, "IREN", "D")
check("clear reports how many it removed", cleared["removed"] >= 1, cleared)
check("clear empties this chart", D.for_chart(conn, "IREN", "D") == [])
check("clear spares other symbols", len(D.for_chart(conn, "NVDA", "D")) == 1)
check("clear spares other timeframes", len(D.for_chart(conn, "IREN", "W")) == 1)

# ------------------------------------------------------------- durability ----
# The price cache once read back correctly in-process and evaporated on exit
# because nothing committed. A drawing that vanishes when you close the tab is
# the same bug with a more visible symptom.
tmp = Path(__file__).resolve().parent / "_drawings_tmp.db"
tmp.unlink(missing_ok=True)
try:
    one = sqlite3.connect(tmp); one.row_factory = sqlite3.Row
    D.add(one, "IREN", "D", "level", [["2026-01-02", 33.0]])
    one.close()
    two = sqlite3.connect(tmp); two.row_factory = sqlite3.Row
    check("a drawing survives the process that made it",
          len(D.for_chart(two, "IREN", "D")) == 1)
    two.close()
finally:
    tmp.unlink(missing_ok=True)

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
