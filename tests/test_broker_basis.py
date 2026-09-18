"""The broker's cost basis overrides FIFO — and refuses to when it cannot.

FIFO is a guess about which lots were sold. The statement is a fact. On
2026-09-10 Fidelity reported IREN at $19.63 a share against the app's FIFO
$25.69 — $25,633 of basis and about $18,000 of unrealised gain on the largest
position in the book. No lot rule reproduces the broker's figure, because the
user selects lots per sale; so it is imported, not derived.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import broker_basis
from app.ledger import connect

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


conn = connect(":memory:")
broker_basis.ensure_schema(conn)
broker_basis.store(conn, [
    {"symbol": "IREN", "quantity": 4227.912, "basis": 82987.98, "as_of": "2026-09-10"},
    {"symbol": "DGXX", "quantity": 20226.55, "basis": 85442.08, "as_of": "2026-09-10"},
])
book = broker_basis.lookup(conn)
check("what was imported reads back", set(book) == {"IREN", "DGXX"}, sorted(book))
check("re-importing the same symbol replaces rather than duplicates",
      broker_basis.store(conn, [{"symbol": "IREN", "quantity": 4227.912,
                                 "basis": 80000.0, "as_of": "2026-09-11"}]) == 1
      and len(broker_basis.lookup(conn)) == 2
      and broker_basis.lookup(conn)["IREN"]["basis"] == 80000.0)

broker_basis.store(conn, [{"symbol": "IREN", "quantity": 4227.912,
                           "basis": 82987.98, "as_of": "2026-09-10"}])
book = broker_basis.lookup(conn)

# The share count is what says the two are describing the same position.
pos = [
    {"symbol": "IREN", "quantity": 4227.912, "cost_basis": 108627.31, "value": 191820.0},
    {"symbol": "DGXX", "quantity": 18125.33, "cost_basis": 76139.0, "value": 68876.0},
    {"symbol": "AEVA", "quantity": 1154.12, "cost_basis": 29326.0, "value": 18027.0},
]
out = {p["symbol"]: p for p in broker_basis.apply_to(pos, book)}

check("a matching share count takes the broker's basis",
      out["IREN"]["cost_basis"] == 82987.98 and out["IREN"]["basis_source"] == "broker",
      out["IREN"])
check("...and the per-share figure is the one on the statement",
      abs(out["IREN"]["avg_cost"] - 19.63) < 0.01, out["IREN"]["avg_cost"])
check("...and the unrealised gain is recomputed from it",
      abs(out["IREN"]["unrealised"] - (191820.0 - 82987.98)) < 0.01, out["IREN"].get("unrealised"))
# The percent was the one figure left on FIFO: the live page showed IREN at
# +$102,321 beside +70.6% when the broker's basis makes it +131%. The dollar
# figure and the percent must describe the same basis.
check("...and the unrealised percent agrees with the unrealised dollars",
      out["IREN"].get("unrealised_pct") is not None
      and abs(out["IREN"]["unrealised"] / out["IREN"]["cost_basis"]
              - out["IREN"]["unrealised_pct"]) < 1e-9,
      out["IREN"].get("unrealised_pct"))
check("...and it is the broker-basis percent, not the FIFO one",
      abs(out["IREN"]["unrealised_pct"] - (191820.0 - 82987.98) / 82987.98) < 1e-9,
      out["IREN"].get("unrealised_pct"))
zero = broker_basis.apply_to(
    [{"symbol": "IREN", "quantity": 4227.912, "cost_basis": 1.0, "value": None,
      "unrealised_pct": 0.5}], book)[0]
check("no price means no unrealised figure, not a stale FIFO one",
      zero["unrealised"] is None and zero["unrealised_pct"] is None, zero)

# DGXX is the case that matters most: the broker holds 20,226 shares and the
# ledger 18,125, because a week of transactions was never exported. Applying a
# basis for shares the ledger does not have would overstate the cost of every
# one of them.
check("a disagreeing share count REFUSES the broker basis rather than misapplying it",
      out["DGXX"]["cost_basis"] == 76139.0 and out["DGXX"]["basis_source"] == "fifo",
      out["DGXX"])
check("...and says why, so the interface can explain instead of showing a wrong number",
      out["DGXX"]["basis_stale"]["broker_qty"] == 20226.55
      and out["DGXX"]["basis_stale"]["ledger_qty"] == 18125.33, out["DGXX"].get("basis_stale"))

check("a symbol the broker never reported keeps FIFO and says so",
      out["AEVA"]["cost_basis"] == 29326.0 and out["AEVA"]["basis_source"] == "fifo")
check("every position states which basis it is carrying",
      all("basis_source" in p for p in out.values()))
conn.close()

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<72} {detail if not ok else ''}")
print(f"\n  {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
