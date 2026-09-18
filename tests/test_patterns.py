"""Cup and handle: the base the user has had the most success with."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import structure, verdicts

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def bars_from(closes, vol=1_000_000):
    out = []
    for i, c in enumerate(closes):
        out.append({"time": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": c, "high": c * 1.01,
                    "low": c * 0.99, "close": c, "volume": vol})
    return out


def cup(depth=0.25, cup_bars=60, handle_depth=0.08, handle_bars=10, breakout=True, v_shape=False):
    """Left rim 100, rounded cup, right rim ~99, handle, then a breakout close."""
    closes = [90 + i * 0.5 for i in range(20)]          # run-up into the left rim (~99.5)
    closes.append(100.0)                                  # left rim
    low = 100 * (1 - depth)
    half = cup_bars // 2
    for i in range(1, cup_bars + 1):
        if v_shape:
            frac = abs(i - half) / half                   # straight down, straight up
        else:
            import math
            frac = (1 - math.cos(math.pi * i / cup_bars)) / 2   # 0 → 1 → 0 shape via cosine
            frac = 1 - abs(2 * frac - 1)                  # rounded bowl
            frac = 1 - frac
        closes.append(low + (100 - low) * (1 - frac if not v_shape else frac) * 0 + (low if not v_shape else low) if False else None)
    # simpler explicit bowl: cosine from rim to low and back
    import math
    closes = [90 + i * 0.5 for i in range(20)] + [100.0]
    for i in range(1, cup_bars + 1):
        if v_shape:
            f = 1 - abs(i - half) / half                  # V: linear down then up
        else:
            f = (1 - math.cos(2 * math.pi * i / cup_bars)) / 2   # smooth bowl, 0 at rims, 1 at the middle
        closes.append(100 - (100 - low) * f)
    closes[-1] = 99.0                                     # right rim
    h_low = 99 * (1 - handle_depth)
    for i in range(1, handle_bars + 1):
        closes.append(99 - (99 - h_low) * (i / handle_bars))
    for i in range(3):
        closes.append(h_low + (99 - h_low) * (i + 1) / 3)
    if breakout:
        closes.append(101.5)
    else:
        closes.append(98.0)
    return bars_from(closes)


def detect(b):
    pv = structure.pivots(b, 3, 3)
    return verdicts.cup_handle(b, pv, b[-1]["close"], 1.0)


r = detect(cup())
check("a textbook cup and handle with a breakout close is detected", r is not None, r)
check("it is confirmed and reads bull", r and r["confirmed"] and r["stance"] == "bull", r)
check("the pivot is the handle's high, near the right rim", r and 98.5 <= r["pivot"] <= 101, r and r["pivot"])
check("the cup depth is measured", r and 0.2 <= r["depth"] <= 0.3, r and r["depth"])

f = detect(cup(breakout=False))
check("inside the handle it is forming, with no stance yet", f is not None and not f["confirmed"] and f["stance"] is None, f)

check("a V-shaped drop and recovery is not a cup", detect(cup(v_shape=True)) is None, detect(cup(v_shape=True)))
check("a cup less than 12% deep does not count", detect(cup(depth=0.08)) is None)
check("a cup more than half deep does not count", detect(cup(depth=0.6)) is None)
check("a handle that falls into the lower half of the cup does not count", detect(cup(handle_depth=0.2, depth=0.3)) is None)
check("a cup shorter than seven weeks does not count", detect(cup(cup_bars=20)) is None)

# It is wired into the evidence at zero weight, named for the replay.
g = verdicts.gather(cup(), None, None, "D", None)
items = [e for e in g["evidence"] if e["name"] == "cup and handle"]
check("the evidence carries a 'cup and handle' item", len(items) == 1, [e["name"] for e in g["evidence"]][:20])
check("at zero weight until measured", items and items[0]["weight"] == 0.0, items and items[0]["weight"])
check("with the pivot as its level", items and abs(items[0]["level"] - r["pivot"]) < 0.01, items and items[0].get("level"))

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -> {detail}"))
print(f"\n  {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
