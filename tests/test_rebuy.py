"""The buy-back screen: the last sale, the readings, and the state in words."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import rebuy

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def tx(day, sym, qty, price, kind=None):
    return {"txn_date": day, "symbol": sym, "quantity": qty, "price": price, "kind": kind or ("buy" if qty > 0 else "sell"), "account": "B"}


def bars_from(closes, start="2025-01-06"):
    d = date.fromisoformat(start); out = []
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"time": d.isoformat(), "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1000})
        d += timedelta(days=1)
    return out


T = [tx("2025-06-20", "IREN", 100, 14.0), tx("2025-11-14", "IREN", -50, 46.0), tx("2025-11-14", "IREN", -10, 47.0),
     tx("2025-03-01", "OKLO", 10, 30.0), tx("2026-07-29", "OKLO", -10, 39.44),
     tx("2024-01-01", "OLD", 10, 5.0), tx("2024-06-01", "OLD", -10, 4.0)]
s = rebuy.sales(T, "2025-09-05", "2026-09-05")
check("a partial sale is kept with the shares still held", "IREN" in s and not s["IREN"]["flat"] and s["IREN"]["held"] == 40, s.get("IREN"))
check("two fills on one day are one sale at the average price", abs(s["IREN"]["price"] - (50*46 + 10*47) / 60) < 1e-3 and s["IREN"]["shares"] == 60, s["IREN"])
check("a sale to zero is flat", s["OKLO"]["flat"], s.get("OKLO"))
check("a sale before the window is not a candidate", "OLD" not in s)

# a run to 100, then a collapse to 30 over ~20 weeks: the floor and the drawdown
closes = [10.0 + i * 0.9 for i in range(100)] + [100.0 * (0.985 ** i) for i in range(1, 100)]
bars = bars_from(closes)
r = rebuy.readings(bars)
check("drawdown is read against the 52-week high", r["drawdown"] < -0.5, r["drawdown"])
check("a weekly Williams floor is found on a completed week", r["floor_at"] is not None and r["floor_recent"], (r["floor_at"], r["wr_done"]))
state, have, missing = rebuy.judge(r, {"date": "2026-01-01", "price": 90.0}, [])
check("state reads at the floor", state == "at the floor", state)
check("the sale is 30%+ under, so it counts as there", any("under your last sale" in h for h in have), have)
# then a bounce: two weeks up clears the prior week's high -> confirmed
closes2 = closes + [closes[-1] * 1.03 ** i for i in range(1, 11)]
r2 = rebuy.readings(bars_from(closes2))
check("a weekly close over the prior week's high after the floor confirms it", r2["confirmed_at"] is not None, (r2["floor_at"], r2["confirmed_at"]))
check("the confirmed state ranks first", rebuy.judge(r2, None, [])[0] == "floor, confirmed")
# a quiet name near its high: nothing in place
flat = rebuy.readings(bars_from([50 + (i % 7) * 0.2 for i in range(200)]))
st, hv, ms = rebuy.judge(flat, None, [])
check("a name near its high reads not yet, with the missing readings named", st == "not yet" and len(ms) >= 2 and not hv, (st, ms))
# zones
z = rebuy.zones_for([{"author": "StonkChris (x)", "date": "2026-08-01", "kind": "buy_zone", "lo": 44.0, "hi": 47.0, "note": "n"},
                     {"author": "A", "date": "2026-08-01", "kind": "target", "lo": 90.0, "hi": None, "note": ""}], 45.0)
check("only buy and downside zones count, and a price inside reads inside", len(z) == 1 and z[0]["inside"] and z[0]["author"] == "StonkChris", z)
st3 = rebuy.judge(flat, None, [{"author": "S", "date": "d", "kind": "buy zone", "lo": 49.0, "hi": 51.5, "inside": True, "distance": -0.02, "note": ""}])[0]
check("inside a followed zone is its own state", st3 == "in a followed zone", st3)

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  -> {detail}"))
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
