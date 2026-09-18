"""Paper trading: which orders tonight's calls imply, with no broker in the room."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import paper

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

def wk(verdict, conf="high", fifth=5, score=2.0, price=50.0, stop=45.0, insufficient=False):
    return {"weekly": {"verdict": verdict, "confidence": conf, "measured_fifth": fifth,
                       "measured_score": score, "price": price, "insufficient": insufficient,
                       "watch": {"stop_at": stop}, "because": ["why"]},
            "daily": {"price": price}}

results = {
    "AAA": wk("buy"),                              # qualifies
    "BBB": wk("add", score=3.0),                   # qualifies, ranks first
    "CCC": wk("buy", conf="medium", fifth=4),      # not top fifth
    "DDD": wk("hold"),                             # not an entry
    "EEE": wk("buy", price=0),                     # no price
    "HLD": wk("hold", price=20.0),                 # held, keep
    "SEL": wk("sell", price=20.0),                 # held, exit on the call
    "STP": wk("hold", price=9.0),                  # held, below its stop
}
held = {"HLD": 100, "SEL": 100, "STP": 100}
stops = {"STP": 10.0, "HLD": 15.0}
orders = paper.decide_orders(results, held, equity=100000.0, prices_now={}, stops=stops, max_positions=4)
by = {(o["side"], o["symbol"]): o for o in orders}
check("a held name whose weekly call turned to sell is exited", ("sell", "SEL") in by and by[("sell", "SEL")]["qty"] == 100)
check("a held name that closed below its stop is exited, saying so",
      ("sell", "STP") in by and "stop" in by[("sell", "STP")]["reason"])
check("a held name still on hold above its stop is kept", ("sell", "HLD") not in by)
check("only top-fifth high-confidence buys and adds enter",
      {s for (side, s) in by if side == "buy"} == {"AAA", "BBB"}, sorted(by))
check("entries are ranked by measured score", [o["symbol"] for o in orders if o["side"] == "buy"] == ["BBB", "AAA"])
check("each entry is sized to equity over the maximum book, in whole shares",
      by[("buy", "AAA")]["qty"] == int((100000 / 4) // 50.0))
check("the entry carries the stop it will be judged by", by[("buy", "AAA")]["stop"] == 45.0)
# room: 3 held, 2 exiting -> 1 kept -> room 3 of 4; both candidates fit. Shrink the book:
few = paper.decide_orders(results, held, 100000.0, {}, stops, max_positions=2)
check("with no room after the kept names, only the best candidate enters",
      [o["symbol"] for o in few if o["side"] == "buy"] == ["BBB"], [o["symbol"] for o in few])

# ---- the penny cap ----
pen = {
    "P1": wk("buy", price=0.5, score=9.0), "P2": wk("buy", price=1.0, score=8.0),
    "P3": wk("buy", price=1.5, score=7.0),                      # third penny name: capped out
    "P4": wk("buy", price=1.9, score=6.0),                      # penny, but with the evidence
    "N1": wk("buy", price=30.0, score=1.0),                     # normal, lowest score
}
pen_orders = paper.decide_orders(pen, {}, 100000.0, {}, {}, max_positions=10, rs_ranks={"P4": 85})
pen_by = {o["symbol"]: o for o in pen_orders}
check("at most PENNY_SLOTS names under the penny price enter without evidence",
      "P1" in pen_by and "P2" in pen_by and "P3" not in pen_by, sorted(pen_by))
check("a penny name takes half a slot", pen_by["P1"]["qty"] == int((100000 / 10 * 0.5) // 0.5), pen_by["P1"])
check("a penny name with a top-fifth relative-strength rank takes a full slot and is not capped",
      "P4" in pen_by and pen_by["P4"]["qty"] == int((100000 / 10) // 1.9), pen_by.get("P4"))
check("a capped-out penny name does not take a slot from a normal name",
      "N1" in pen_by and pen_by["N1"]["qty"] == int((100000 / 10) // 30.0), sorted(pen_by))
check("the reason says why the slot is half or full",
      "half a slot" in pen_by["P1"]["reason"] and "full slot" in pen_by["P4"]["reason"])
# held penny names beyond the cap are sold, lowest measured score first
hp = {"P1": wk("hold", price=0.5, score=9.0), "P2": wk("hold", price=1.0, score=8.0),
      "P3": wk("hold", price=1.5, score=2.0), "P4": wk("hold", price=1.9, score=1.0)}
hp_orders = paper.decide_orders(hp, {"P1": 10, "P2": 10, "P3": 10, "P4": 10}, 100000.0,
                                {"P1": 0.5, "P2": 1.0, "P3": 1.5, "P4": 1.9}, {}, rs_ranks={"P4": 90})
check("held penny names beyond the cap are sold, lowest score first, evidence exempt",
      [o["symbol"] for o in hp_orders if o["side"] == "sell"] == ["P3"], hp_orders)
check("a name no longer scored is exited",
      any(o["symbol"] == "GONE" and o["side"] == "sell" for o in paper.decide_orders(results, {"GONE": 5}, 1e5, {}, {})))

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
