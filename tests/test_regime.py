"""The exposure dial: four gauges from cached series, summed into a label."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import regime
from app.ledger import connect, get_or_create_security

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

def seed(conn, symbol, closes):
    sec = get_or_create_security(conn, symbol)
    for i, c in enumerate(closes):
        d = f"{2024 + i // 250}-{1 + (i % 250) // 21:02d}-{1 + (i % 250) % 21:02d}"
        conn.execute("INSERT INTO prices (security_id, bar_date, open, high, low, close, source) VALUES (?,?,?,?,?,?,?)",
                     (sec, d, c, c, c, c, "test"))
    conn.commit()

n = 300
conn = connect(":memory:")
seed(conn, "SPY", [100 + i * 0.2 for i in range(n)])          # rising index
seed(conn, "QQQ", [100 + i * 0.5 for i in range(n)])          # rising faster: ratio above average
seed(conn, "IWM", [100 - i * 0.1 for i in range(n)])          # falling: ratio below average
seed(conn, "DTWEXBGS", [120 - i * 0.05 for i in range(n)])    # dollar falling: helps risk
r = regime.reading(conn, "2030-01-01")
by = {g["name"]: g["score"] for g in r["gauges"]}
check("growth leading scores +1", by["QQQ / SPY"] == 1, by)
check("small caps lagging scores -1", by["IWM / SPY"] == -1, by)
check("the index above its average scores +1", by["SPY"] == 1, by)
check("a falling dollar scores +1", by["Dollar"] == 1, by)
check("the sum is the score and +2 is windy", r["score"] == 2 and r["state"] == "mixed" and r["label"] == "windy", (r["score"], r["state"]))

conn2 = connect(":memory:")
seed(conn2, "SPY", [100 + i * 0.2 for i in range(n)])
seed(conn2, "QQQ", [100 + i * 0.5 for i in range(n)])
seed(conn2, "IWM", [100 + i * 0.4 for i in range(n)])
seed(conn2, "DTWEXBGS", [120 - i * 0.05 for i in range(n)])
r2 = regime.reading(conn2, "2030-01-01")
check("+3 or more is clear skies", r2["score"] == 4 and r2["state"] == "on", (r2["score"], r2["state"]))

conn3 = connect(":memory:")
seed(conn3, "SPY", [200 - i * 0.2 for i in range(n)])
seed(conn3, "QQQ", [200 - i * 0.5 for i in range(n)])
seed(conn3, "IWM", [200 - i * 0.4 for i in range(n)])
seed(conn3, "DTWEXBGS", [100 + i * 0.05 for i in range(n)])
r3 = regime.reading(conn3, "2030-01-01")
check("everything against risk is risk-off", r3["score"] == -4 and r3["state"] == "off", (r3["score"], r3["state"]))

conn4 = connect(":memory:")
seed(conn4, "SPY", [100 + i * 0.2 for i in range(50)])
r4 = regime.reading(conn4, "2030-01-01")
check("too little history scores nothing rather than guessing",
      r4["score"] == 0 and all("not enough" in g["state"] for g in r4["gauges"]), r4["gauges"])
check("an as-of date reads the series as it stood then",
      regime.reading(conn, "2024-01-01")["score"] == 0)


# ---- the indices' own read ----
_c2 = connect(":memory:")
import math
seed(_c2, "SPY", [100 + 40 * math.sin(i / 25) + i * 0.05 for i in range(420)])
seed(_c2, "QQQ", [100 + 30 * math.sin(i / 20) + i * 0.08 for i in range(420)])
seed(_c2, "IWM", [100 - 20 * math.sin(i / 30) for i in range(420)])
_ix = regime.index_read(_c2, "2025-08-21")
check("each index gets a weekly and a daily call", set(_ix["indices"]) == {"SPY", "QQQ", "IWM"}
      and all(v["weekly"] and v["daily"] for v in _ix["indices"].values()), _ix)
check("the state is one of with / against / neutral", _ix["state"] in ("with", "against", "neutral"), _ix["state"])
check("the summary names every index", all(s in _ix["summary"] for s in ("SPY", "QQQ", "IWM")), _ix["summary"])
_c3 = connect(":memory:")
seed(_c3, "SPY", [100.0] * 50)
check("too little history reads nothing rather than guessing",
      regime.index_read(_c3, "2024-03-01")["indices"] == {} and regime.index_read(_c3, "2024-03-01")["state"] == "neutral")
passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
