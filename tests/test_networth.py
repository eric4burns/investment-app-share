"""Everything you own minus everything you owe.

Each half of this existed separately for months — a portfolio on one tab,
spending on another — and neither is net worth. It needed a third piece that
only arrived with the card imports, because a brokerage balance rising while a
card balance rises faster is a portfolio going up and a net worth going down.

Two things here are easy to get quietly wrong, and both are tested directly. A
card balance is a running sum of charges and payments, not a column in any
export, so the sign has to be right in both directions. And a savings rate that
counts money moved to a brokerage as spending tells someone who saves 62% of
their income that they are living beyond their means.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cash, networth
from app.ledger import (connect, get_or_create_account, get_or_create_institution,
                        get_or_create_security)

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def card(day, amount, description="MERCHANT"):
    return {"txn_date": day, "amount": amount, "description": description,
            "account": "Card", "account_kind": "credit", "category_kind": "expense"}


def bank(day, amount, account="Checking", kind="debit", symbol=None):
    return {"txn_date": day, "amount": amount, "description": "X",
            "account": account, "account_kind": "checking", "kind": kind,
            "symbol": symbol, "category_kind": "expense"}


# ------------------------------------------------------------ month ends ----
ends = networth.month_ends("2026-01-15", "2026-04-10")
check("month ends land on the last day of each month",
      ends[:2] == ["2026-01-31", "2026-02-28"], ends[:2])
check("the range ends on the date asked for, not a month boundary",
      ends[-1] == "2026-04-10", ends[-1])
check("a leap February is handled",
      "2028-02-29" in networth.month_ends("2028-01-01", "2028-03-31"),
      networth.month_ends("2028-01-01", "2028-03-31")[:3])
check("a single day is one point", networth.month_ends("2026-05-05", "2026-05-05")
      == ["2026-05-05"], networth.month_ends("2026-05-05", "2026-05-05"))

# ---------------------------------------------------------- card balance ----
# A purchase increases what is owed; a payment reduces it. The stored amount is
# the account's cash effect, so both signs flip on the way in.
rows = [card("2026-01-10", -100.00), card("2026-01-20", -50.00),
        card("2026-02-05", 120.00, "PAYMENT THANK YOU"), card("2026-02-20", -30.00)]
bal = networth.card_balances(rows, ["2026-01-15", "2026-01-31", "2026-02-10", "2026-02-28"])
check("a purchase increases what is owed", bal["2026-01-15"] == 100.00, bal["2026-01-15"])
check("purchases accumulate", bal["2026-01-31"] == 150.00, bal["2026-01-31"])
check("a payment reduces it", bal["2026-02-10"] == 30.00, bal["2026-02-10"])
check("and the balance carries forward", bal["2026-02-28"] == 60.00, bal["2026-02-28"])
check("a date before any charge owes nothing",
      networth.card_balances(rows, ["2025-12-01"])["2025-12-01"] == 0.0)

# Paying a card off entirely leaves zero, not a negative balance carried on.
paid = [card("2026-01-10", -100.00), card("2026-02-01", 100.00, "AUTOPAY")]
check("paying it off leaves nothing owed",
      networth.card_balances(paid, ["2026-02-15"])["2026-02-15"] == 0.0)

# Only card accounts count. A bank transaction is not debt.
mixed = rows + [{"txn_date": "2026-01-12", "amount": -900.0, "description": "RENT",
                 "account": "Checking", "account_kind": "checking",
                 "category_kind": "expense"}]
check("bank spending is not counted as card debt",
      networth.card_balances(mixed, ["2026-01-15"])["2026-01-15"] == 100.00,
      networth.card_balances(mixed, ["2026-01-15"])["2026-01-15"])

# --------------------------------------------------------- sample dates ----
# The curve is drawn daily because month ends hid the peaks: the same portfolio
# read $598,946 at month ends and $636,634 daily, and only the second agrees
# with the broker's own screen. The end date is always the last point, so the
# chart finishes at today rather than at whenever the last whole step fell.
grid = networth.sample_dates("2026-01-01", "2026-01-05")
check("a daily grid has a point for every day",
      grid == ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"], grid)
weekly = networth.sample_dates("2026-01-01", "2026-01-20", step_days=7)
check("a wider step still ends on the date asked for, not the last whole step",
      weekly[-1] == "2026-01-20" and weekly[:3] == ["2026-01-01", "2026-01-08", "2026-01-15"],
      weekly)
check("weekends are kept, because bank and card balances move over one",
      "2026-01-03" in grid and "2026-01-04" in grid, grid)

# ---------------------------------------------------------- bank cash ----
# bank_balances exists only as a fast rewrite of "call cash.balances once per
# date", which was O(dates x transactions) and pushed /api/performance past its
# budget on a daily grid. A faster function that answers differently is not an
# optimisation, so the assertion that matters is that the two still agree —
# including through the anchor, which is the part the rewrite reimplemented.
BANK = [
    bank("2026-05-10", -200.0, kind="debit"),
    bank("2026-06-10", -300.0, kind="debit"),
    bank("2026-07-10", 50.0, kind="credit"),
    bank("2026-06-15", -75.0, account="Savings"),
]
DATES = ["2026-05-01", "2026-06-01", "2026-06-30", "2026-07-31"]
ANCHORS = {"Checking": {"as_of": "2026-06-30", "balance": 1000.0, "note": ""}}

fast = networth.bank_balances(BANK, DATES, ANCHORS)
slow = {d: round(sum(r["balance"] for r in
                     cash.balances(BANK, asof=d, anchor_map=ANCHORS).values()), 2)
        for d in DATES}
check("one forward pass agrees with cash.balances on every date",
      fast == slow, (fast, slow))

# And spelled out, so a failure says which direction broke rather than only that
# the two drifted. On the anchor date the balance IS the anchor (plus the other
# account); after it the later flows are added; before it the flows in between
# are undone, which is the half a forward-only rewrite silently loses.
check("on the anchor date the anchored account contributes the anchor itself",
      abs(fast["2026-06-30"] - (1000.0 - 75.0)) < 0.005, fast["2026-06-30"])
check("after the anchor, later flows are added",
      abs(fast["2026-07-31"] - (1050.0 - 75.0)) < 0.005, fast["2026-07-31"])
check("before the anchor, the flows in between are undone",
      abs(fast["2026-06-01"] - 1300.0) < 0.005, fast["2026-06-01"])
check("two dates before the anchor do not report the same balance",
      fast["2026-05-01"] != fast["2026-06-01"],
      (fast["2026-05-01"], fast["2026-06-01"]))

# Without an anchor the balance is the flows alone — which is exactly the figure
# that is short by the opening balance, and is why anchors exist.
noanchor = networth.bank_balances(BANK, ["2026-07-31"], {})
check("with no anchor the balance is the flows alone",
      abs(noanchor["2026-07-31"] + 525.0) < 0.005, noanchor["2026-07-31"])

# A sweep into the core fund is money moving between two names for one pool, and
# a market-value restatement moves no money at all. Both must be excluded here
# for the same reason cash.balances excludes them: if the two disagree about
# what a flow is, the fast path drifts from the slow one silently.
SWEPT = [bank("2026-01-02", 1_000.0, kind="deposit"),
         bank("2026-01-31", 19.13, kind="dividend", symbol="SPAXX"),
         bank("2026-01-31", -19.13, kind="reinvest", symbol="SPAXX"),
         bank("2026-02-01", 35.08, kind="market_value_adj", symbol="IREN")]
swept = networth.bank_balances(SWEPT, ["2026-03-01"], {})
check("a core-fund sweep is not money leaving the bank total",
      abs(swept["2026-03-01"] - 1_019.13) < 0.005, swept["2026-03-01"])

# Card rows belong to the debt half. Counting them here would subtract the same
# spending twice — once as cash gone, once as debt owed.
check("credit-account rows are not bank cash",
      networth.bank_balances(rows, ["2026-02-28"], {})["2026-02-28"] == 0.0,
      networth.bank_balances(rows, ["2026-02-28"], {})["2026-02-28"])

# --------------------------------------------------------- savings rate ----
def flow(day, amount, kind):
    return {"txn_date": day, "amount": amount, "category_kind": kind}


year = [flow("2026-01-31", 10_000.0, "income"),
        flow("2026-02-05", -3_000.0, "expense"),
        flow("2026-02-06", -5_000.0, "investment"),     # saved, not spent
        flow("2026-02-07", -1_000.0, "transfer")]       # moved, not spent
r = networth.savings_rate(year)
check("income is counted", r["income"] == 10_000.0, r["income"])
check("only expenses count as spending", r["spending"] == 3_000.0, r["spending"])
check("money moved to a brokerage is saved, not spent", r["saved"] == 7_000.0, r["saved"])
check("the rate is what is left over", abs(r["rate"] - 0.70) < 0.001, r["rate"])

# The failure this guards: counting transfers as spending turns a saver into
# someone living beyond their means.
check("a heavy saver does not read as overspending", r["rate"] > 0, r["rate"])

# No income means no rate, rather than a division by zero or a misleading zero.
check("no income gives no rate",
      networth.savings_rate([flow("2026-01-01", -50.0, "expense")])["rate"] is None)

# Spending more than you earn is a negative rate, not a floor at zero.
over = networth.savings_rate([flow("2026-01-01", 1_000.0, "income"),
                              flow("2026-01-02", -1_500.0, "expense")])
check("spending more than you earn is negative", over["rate"] < 0, over["rate"])

# Date bounds.
bounded = networth.savings_rate(
    year + [flow("2025-06-01", 99_999.0, "income")], start="2026-01-01")
check("a start date excludes earlier flows", bounded["income"] == 10_000.0, bounded["income"])

# ---------------------------------------------------------- the series ----
# The three halves assembled. This is the number the app exists to produce and
# nothing above tests it together, so the sign of the debt term — the whole
# reason a rising portfolio can still be a falling net worth — was never
# asserted anywhere.
def ledger():
    conn = connect(":memory:")
    bankinst = get_or_create_institution(conn, "Bank")
    chk = get_or_create_account(conn, bankinst, "C", "Checking", "checking", "taxable")
    cardinst = get_or_create_institution(conn, "Cards")
    crd = get_or_create_account(conn, cardinst, "V", "Visa", "credit", "taxable")
    broker = get_or_create_institution(conn, "Broker")
    brk = get_or_create_account(conn, broker, "B", "Brokerage", "brokerage", "taxable")
    sec = get_or_create_security(conn, "STK")
    for day, close in (("2026-01-01", 10.0), ("2026-01-31", 10.0)):
        conn.execute("INSERT INTO prices (security_id, bar_date, close, source)"
                     " VALUES (?,?,?,?)", (sec, day, close, "test"))

    def add(account, day, kind, amount, desc, key, sid=None, qty=None, price=None):
        conn.execute(
            """INSERT INTO transactions (account_id, txn_date, kind, security_id,
                                         quantity, price, amount, description,
                                         source, source_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (account, day, kind, sid, qty, price, amount, desc, "test", key))

    add(brk, "2026-01-02", "deposit", 1_000.0, "DEPOSIT", "b0")
    add(brk, "2026-01-05", "buy", -1_000.0, "BUY STK", "b1", sec, 100.0, 10.0)
    add(chk, "2026-01-10", "debit", -400.0, "Spotify USA", "c1")
    add(crd, "2026-01-12", "debit", -250.0, "WHOLEFDS MKT", "v1")
    conn.commit()
    return conn


conn = ledger()
s = networth.series(conn, "2026-01-01", "2026-01-31")
last = s["latest"]
check("the series ends on the date asked for", last["date"] == "2026-01-31", last["date"])
check("investments are valued at market", last["investments"] == 1_000.00, last["investments"])
# Debt is money OWED. Adding it instead of subtracting it turns a maxed-out card
# into wealth, which is the one sign error on this page that cannot be spotted
# by eye — every number involved stays perfectly plausible.
check("card debt is reported as a positive amount owed", last["debt"] == 250.00, last["debt"])
check("net worth SUBTRACTS the card debt",
      last["net"] == round(last["investments"] + last["cash"] - last["debt"], 2),
      (last["net"], last["investments"], last["cash"], last["debt"]))
check("owing more than you hold in cash is possible and is not clamped",
      last["cash"] < 0, last["cash"])

# A checking account whose imported history does not reach back to when it was
# funded derives a NEGATIVE balance, which is not a thing an account can hold.
# Saying the total is short by that much is the difference between a number that
# is low and a number that is wrong — and it silently became zero under mutation
# with every suite green.
check("a derived-negative account is named as understating the total",
      [r["account"] for r in s["understated_accounts"]] == ["Checking"],
      s["understated_accounts"])
check("and the shortfall is stated as an amount, not a caveat",
      abs(s["understated_by"] - 400.00) < 0.005, s["understated_by"])

# Before a card's first imported row its balance is assumed to be zero, which
# UNDERSTATES the debt. Where that assumption stops mattering is worth saying.
check("the date the card history begins is reported",
      s["card_history_from"] == "2026-01-12", s["card_history_from"])
check("points before the card's first row are marked partial",
      s["points"][0]["partial"] is True and last["partial"] is False,
      (s["points"][0]["partial"], last["partial"]))

# An anchor supplies the opening balance the export cannot, and the whole series
# has to move with it — not just the last point.
anchored = networth.series(conn, "2026-01-01", "2026-01-31",
                           anchors={"Checking": {"as_of": "2026-01-31",
                                                 "balance": 5_000.0, "note": None}})
check("an anchor lifts the cash side of every point, not only the last",
      anchored["latest"]["cash"] == 5_000.00
      and anchored["points"][0]["cash"] == 5_400.00,
      (anchored["latest"]["cash"], anchored["points"][0]["cash"]))
check("and once anchored nothing is reported as understated",
      anchored["understated_by"] == 0.0 and anchored["understated_accounts"] == [],
      anchored["understated_by"])
conn.close()

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
