"""Cash balances derived from flows.

The money-market funds are the core position: uninvested money is swept into
SPAXX or FDRXX automatically, and that fund IS the account's cash. The activity
export never records the sweep, so the only core rows in this ledger are monthly
dividends and their reinvestments — summing the share quantities counted the
interest and none of the principal, showing $842 of core against roughly $11,700
actually there.

The tests below are built around the one subtraction that makes this work: a
purchase of the core fund is money moving between two names for the same pool,
not money leaving. Counting it as a spend makes every account that has ever
earned interest read slightly negative, which is how the arithmetic announces
the mistake — a brokerage account cannot hold less than nothing.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cash

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def t(day, kind, amount, symbol=None, account="ROTH IRA", quantity=0.0):
    return {"txn_date": day, "kind": kind, "amount": amount, "symbol": symbol,
            "account": account, "quantity": quantity, "price": None,
            "description": "", "tax_status": "taxable"}


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cash.ensure_schema(conn)
    return conn


# ------------------------------------------------------ the sweep rule ----
# A dividend paid into the core and immediately reinvested in it leaves the
# account with MORE cash, by exactly the dividend. Treating the reinvestment as
# a spend nets it to zero; treating it as a spend while ignoring nothing else
# drives the balance negative.
flow = [
    t("2025-01-02", "deposit", 10_000.00),
    t("2025-01-31", "dividend", 19.13, "SPAXX"),
    t("2025-01-31", "reinvest", -19.13, "SPAXX", quantity=19.13),
]
bal = cash.balances(flow)
check("a reinvested core dividend adds the dividend, once",
      abs(bal["ROTH IRA"]["balance"] - 10_019.13) < 0.005, bal["ROTH IRA"]["balance"])
check("the sweep is reported separately, not silently dropped",
      abs(bal["ROTH IRA"]["sweeps"] + 19.13) < 0.005, bal["ROTH IRA"]["sweeps"])

# Buying an actual security IS money leaving.
bal = cash.balances(flow + [t("2025-02-03", "buy", -2_500.00, "IREN", quantity=100)])
check("buying a security reduces cash",
      abs(bal["ROTH IRA"]["balance"] - 7_519.13) < 0.005, bal["ROTH IRA"]["balance"])
bal = cash.balances(flow + [t("2025-02-03", "buy", -2_500.00, "IREN", quantity=100),
                            t("2025-03-03", "sell", 3_000.00, "IREN", quantity=-100)])
check("selling it puts the proceeds back",
      abs(bal["ROTH IRA"]["balance"] - 10_519.13) < 0.005, bal["ROTH IRA"]["balance"])

# The real ledger's shape: only the dividend cycle, no principal. This is the
# case that read as -$445 before the sweep was excluded.
only_interest = [t("2025-01-31", "dividend", 19.13, "SPAXX"),
                 t("2025-01-31", "reinvest", -19.13, "SPAXX", quantity=19.13),
                 t("2025-02-28", "dividend", 20.01, "SPAXX"),
                 t("2025-02-28", "reinvest", -20.01, "SPAXX", quantity=20.01)]
bal = cash.balances(only_interest)
check("an account with only the dividend cycle is not negative",
      bal["ROTH IRA"]["balance"] >= 0, bal["ROTH IRA"]["balance"])
check("it is the interest earned", abs(bal["ROTH IRA"]["balance"] - 39.14) < 0.005,
      bal["ROTH IRA"]["balance"])

# ------------------------------------------- a valuation is not a flow ----
# Fidelity books "Change in Market Value" against a retirement plan to restate
# what a holding is worth. The row carries an amount and moves no money.
# performance.values_at has always excluded it and cash.balances did not, so the
# two disagreed by exactly its total — $35.08 on the real ledger, small enough
# to read as rounding and nothing of the sort. Counting it is how a cash balance
# drifts away from the account it describes without ever looking wrong.
valuation = [t("2025-01-02", "deposit", 1_000.00),
             t("2025-02-01", "market_value_adj", 35.08, "IREN")]
bal = cash.balances(valuation)
check("a market-value restatement is not cash",
      abs(bal["ROTH IRA"]["balance"] - 1_000.00) < 0.005, bal["ROTH IRA"]["balance"])
# The same row against the core fund must not be mistaken for a sweep either:
# excluding it as non-cash has to happen before the sweep test, or the sweep
# total picks it up and the two figures stop reconciling.
core_valuation = [t("2025-01-02", "deposit", 1_000.00),
                  t("2025-02-01", "market_value_adj", 35.08, "SPAXX")]
bal = cash.balances(core_valuation)
check("a restatement of the core fund is not counted as a sweep",
      abs(bal["ROTH IRA"]["balance"] - 1_000.00) < 0.005
      and abs(bal["ROTH IRA"]["sweeps"]) < 0.005,
      (bal["ROTH IRA"]["balance"], bal["ROTH IRA"]["sweeps"]))

# ------------------------------------------------------------ accounts ----
multi = [t("2025-01-02", "deposit", 500.00, account="A"),
         t("2025-01-02", "deposit", 900.00, account="B")]
bal = cash.balances(multi)
check("accounts are kept apart",
      bal["A"]["balance"] == 500.00 and bal["B"]["balance"] == 900.00,
      {k: v["balance"] for k, v in bal.items()})

# ------------------------------------------------------------- as-of ----
bal = cash.balances(flow, asof="2025-01-15")
check("an as-of date excludes later flows",
      abs(bal["ROTH IRA"]["balance"] - 10_000.00) < 0.005, bal["ROTH IRA"]["balance"])

# ------------------------------------------------------------ anchors ----
# Where the history does not reach back to when the account was funded, no
# arithmetic recovers the opening balance. An anchor supplies it, and everything
# before that date must then be ignored or the history counts twice.
short = [t("2025-01-02", "deposit", 100.00),
         t("2025-06-02", "deposit", 250.00)]
anchor = {"ROTH IRA": {"as_of": "2025-03-01", "balance": 5_000.00, "note": None}}
bal = cash.balances(short, anchor_map=anchor)
check("an anchor replaces everything before its date",
      abs(bal["ROTH IRA"]["balance"] - 5_250.00) < 0.005, bal["ROTH IRA"]["balance"])
check("the anchor is reported so the figure can be traced",
      bal["ROTH IRA"]["anchored"] and bal["ROTH IRA"]["anchor"]["balance"] == 5_000.00)

# A flow ON the anchor date is already inside the statement balance.
same_day = [t("2025-03-01", "deposit", 40.00), t("2025-03-02", "deposit", 7.00)]
bal = cash.balances(same_day, anchor_map=anchor)
check("a flow dated on the anchor day is not added twice",
      abs(bal["ROTH IRA"]["balance"] - 5_007.00) < 0.005, bal["ROTH IRA"]["balance"])

# ------------------------------------------------------ impossible ----
bal = cash.balances([t("2025-01-02", "buy", -900.00, "IREN", quantity=10)])
check("a negative balance is flagged as impossible", bal["ROTH IRA"]["impossible"])
check("a positive one is not", not cash.balances(flow)["ROTH IRA"]["impossible"])

# ------------------------------------------------------------- funds ----
funds = [t("2025-01-31", "dividend", 5.00, "SPAXX", account="Individual"),
         t("2025-01-31", "reinvest", -5.00, "SPAXX", account="Individual", quantity=5),
         t("2025-01-02", "deposit", 1_000.00, account="Individual"),
         t("2025-01-31", "dividend", 3.00, "FDRXX", account="HSA"),
         t("2025-01-31", "reinvest", -3.00, "FDRXX", account="HSA", quantity=3),
         t("2025-01-02", "contribution", 400.00, account="HSA")]
by = cash.by_fund(funds)
check("each account's cash reports under its own core fund",
      abs(by.get("SPAXX", 0) - 1_005.00) < 0.005 and abs(by.get("FDRXX", 0) - 403.00) < 0.005,
      by)

# An account whose core fund changed reports under the current one, not both.
switched = [t("2025-01-31", "dividend", 2.00, "SPAXX", account="X"),
            t("2025-06-30", "dividend", 2.00, "FDRXX", account="X"),
            t("2025-01-02", "deposit", 600.00, account="X")]
by = cash.by_fund(switched)
check("a changed core fund reports under the current one",
      "SPAXX" not in by and abs(by.get("FDRXX", 0) - 604.00) < 0.005, by)

# An account that has never held a core fund contributes to neither.
by = cash.by_fund([t("2025-01-02", "deposit", 50.00, account="NOCORE")])
check("an account with no core fund is not attributed to one", by == {}, by)

# A historical date must report the fund the account held THEN. Letting a later
# switch decide would file two years of history under a fund the account had not
# opened yet, which is a wrong answer that looks entirely reasonable.
by = cash.by_fund(switched, asof="2025-03-01")
check("as of a date before the switch, the earlier core fund is the one used",
      "FDRXX" not in by and abs(by.get("SPAXX", 0) - 602.00) < 0.005, by)

# --------------------------------------------------------- persistence ----
conn = db()
cash.set_anchor(conn, "ROTH IRA", "2025-03-01", 5_000.00, note="Fidelity statement")
got = cash.anchors(conn)
check("an anchor round-trips", got.get("ROTH IRA", {}).get("balance") == 5_000.00, got)
cash.set_anchor(conn, "ROTH IRA", "2025-09-01", 6_100.00)
got = cash.anchors(conn)
check("setting it again replaces rather than accumulates",
      len(got) == 1 and got["ROTH IRA"]["balance"] == 6_100.00, got)
check("clearing removes it", cash.clear_anchor(conn, "ROTH IRA")["removed"] == 1
      and cash.anchors(conn) == {})

for bad, why in [(("A", "not-a-date", 1.0), "a bad date"),
                 (("", "2025-01-01", 1.0), "no account"),
                 (("A", "2025-01-01", float("nan")), "a NaN balance")]:
    try:
        cash.set_anchor(conn, *bad)
        check(f"refuses {why}", False, "it was accepted")
    except ValueError:
        check(f"refuses {why}", True)
conn.close()

# --- an anchor has to work in BOTH directions ------------------------------
# An anchor is a balance reading on a date. Rolling only forwards from it made
# every date before the anchor report the anchor itself, so two years of net
# worth history showed an identical cash figure on every single point: each
# transaction was either filtered out for being after `asof` or skipped as
# already contained in the anchor, and flows came to exactly zero.
ANCH = {"Checking": {"as_of": "2026-06-30", "balance": 1000.0, "note": ""}}
FLOW = [
    {"account": "Checking", "txn_date": "2026-05-10", "amount": -200.0, "kind": "debit"},
    {"account": "Checking", "txn_date": "2026-06-10", "amount": -300.0, "kind": "debit"},
    {"account": "Checking", "txn_date": "2026-07-10", "amount": 50.0, "kind": "credit"},
]
on_anchor = cash.balances(FLOW, "2026-06-30", ANCH)["Checking"]["balance"]
check("on the anchor date the balance is the anchor", on_anchor == 1000.0, on_anchor)

after = cash.balances(FLOW, "2026-07-31", ANCH)["Checking"]["balance"]
check("after the anchor, later flows are added", after == 1050.0, after)

# Before 2026-06-10 the $300 had not left yet, so the balance was higher.
mid = cash.balances(FLOW, "2026-06-01", ANCH)["Checking"]["balance"]
check("before the anchor, intervening flows are undone", mid == 1300.0, mid)

early = cash.balances(FLOW, "2026-05-01", ANCH)["Checking"]["balance"]
check("rolling further back undoes more", early == 1500.0, early)

# The specific symptom: two different historical dates must not report the
# same balance simply because both precede the anchor.
check("two dates before the anchor do not report the same balance",
      mid != early, (mid, early))

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
