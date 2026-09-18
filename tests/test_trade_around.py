"""Trading around a core: the odds, the shares gained, the lots, the record."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import trade_around as T

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

# ---- first passage: a falling series reaches the lower level first, a rising one the upper ----
def series(step):
    px, out = 100.0, []
    for i in range(400):
        px *= (1 + step)
        out.append({"time": f"d{i}", "open": px, "high": px, "low": px, "close": px, "volume": 1})
    return out
fp_down = T.first_passage(series(-0.01), up=0.05, down=0.05, lookahead=20, history=300)
fp_up = T.first_passage(series(+0.01), up=0.05, down=0.05, lookahead=20, history=300)
check("a steadily falling series reaches the lower level first every time",
      fp_down["days"] == 300 and fp_down["down_first"] == 1.0, fp_down)
check("a steadily rising one reaches the upper level first every time",
      fp_up["up_first"] == 1.0, fp_up)
check("a nonsense gap gives no odds rather than a wrong one", T.first_passage(series(0.0), 0, 0.05)["down_first"] is None)

# ---- lots per account, tax status, and the taxable sale ----
txns = [
    {"txn_date": "2025-06-20", "kind": "buy", "symbol": "X", "quantity": 100, "price": 10.0, "amount": -1000, "account": "Roth", "tax_status": "tax_free"},
    {"txn_date": "2025-06-25", "kind": "buy", "symbol": "X", "quantity": 200, "price": 12.0, "amount": -2400, "account": "Taxable", "tax_status": "taxable"},
    {"txn_date": "2026-08-20", "kind": "buy", "symbol": "X", "quantity": 50, "price": 40.0, "amount": -2000, "account": "Taxable", "tax_status": "taxable"},
    {"txn_date": "2025-11-20", "kind": "sell", "symbol": "X", "quantity": -30, "price": 47.0, "amount": 1410, "account": "Roth", "tax_status": "tax_free"},
    {"txn_date": "2025-12-02", "kind": "buy", "symbol": "X", "quantity": 34, "price": 41.0, "amount": -1394, "account": "Roth", "tax_status": "tax_free"},
]
acc = T.lots_by_account(txns, "X", "2026-09-03")
by = {a["account"]: a for a in acc}
check("lots are kept per account with the account's tax status",
      by["Roth"]["tax_status"] == "tax_free" and not by["Roth"]["taxable"] and by["Taxable"]["taxable"], acc)
check("tax-free accounts are listed first, since that is where a round trip costs nothing",
      acc[0]["account"] == "Roth")
check("the Roth's own sale and buy-back are netted through its lots",
      abs(by["Roth"]["quantity"] - 104) < 1e-6, by["Roth"]["quantity"])

tp = T.taxable_sale(by["Taxable"]["lots"], 60, at_price=38.0, asof="2026-09-03",
                    recent_buys=["2026-08-20"])
check("the highest-cost lot is sold first", tp["lots"][0]["cost"] == 40.0 and tp["lots"][0]["qty"] == 50, tp["lots"])
check("the remainder comes from the next lot, at a long-term gain",
      tp["lots"][1]["cost"] == 12.0 and tp["lots"][1]["qty"] == 10 and tp["lots"][1]["long_term"], tp["lots"])
check("a loss lot plus a buy inside thirty days is flagged as a wash sale",
      tp["wash_sale_risk"] and "disallowed" in tp["wash_note"], tp["wash_note"])
tp2 = T.taxable_sale(by["Taxable"]["lots"], 60, at_price=45.0, asof="2026-09-03", recent_buys=["2026-08-20"])
check("all gains means no wash-sale rule applies", not tp2["wash_sale_risk"] and "no wash-sale" in tp2["wash_note"])

# ---- the record: shares gained on past round trips ----
past = T.past_round_trips(txns, "X")
check("a sale followed by a buy-back within the window is scored in shares",
      len(past) == 1 and past[0]["sold"] == 30 and past[0]["bought_back"] == 34, past)
check("shares gained is what the proceeds bought less what was sold, in shares",
      abs(past[0]["gained"] - (1394 / 41.0 - 30 * (1394 / 1410))) < 1e-4, past[0]["gained"])

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
