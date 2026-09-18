"""Budget categorisation.

A bank account is mostly not spending. In this ledger the four largest flows are
money going to Fidelity, money going to a savings account, payroll arriving and
credit-card bills being paid — and adding those up as expenses gives two years of
"spending" at $388,943 against $377,981 of income, which describes nobody's life.

So most of these tests are about the boundary between money that LEFT and money
that merely moved, because every useful number on the page is downstream of
getting that right.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import budget

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def db(seed=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())
    if seed:
        budget.ensure_seed(conn)
    return conn


def t(day, amount, description, tid=None):
    return {"id": tid, "txn_date": day, "amount": amount,
            "description": description, "kind": "debit"}


conn = db()

# ------------------------------------------------------------ seeding ----
check("seeding creates the categories",
      conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == len(budget.DEFAULT_CATEGORIES))
before = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
again = budget.ensure_seed(conn)
check("seeding twice adds nothing",
      again["categories_added"] == 0 and again["rules_added"] == 0, again)
check("and does not duplicate the rules",
      conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0] == before)

kinds = {r["kind"] for r in conn.execute("SELECT DISTINCT kind FROM categories")}
check("every category kind is one the summary understands",
      kinds <= set(budget.KINDS), kinds)

# ------------------------------------------- transfers are not spending ----
# The whole point. Each of these is money you still have.
moves = [
    t("2025-01-05", -5000.00, "FID BKG SVC LLC MONEYLINE Zxxxxx — Electronic Debit"),
    t("2025-01-06", -3000.00, "AMERICANEXPRESS TRANSFER xxxxxxx — Electronic Debit"),
    t("2025-01-07", -1200.00, "CARDMEMBER SERV WEB PYMT ******* — Electronic Debit"),
    t("2025-01-08", -900.00,  "ROBINHOOD DEBITS xxxxx3185 — Electronic Debit"),
]
s = budget.summary(budget.classify(conn, moves))
check("moving money to a brokerage is not an expense", s["by_kind"].get("expense", 0) == 0,
      s["by_kind"])
check("a savings transfer is not an expense either",
      s["by_kind"].get("transfer", 0) == -4200.00, s["by_kind"])
check("brokerage transfers get their own line",
      s["by_kind"].get("investment", 0) == -5900.00, s["by_kind"])
check("nothing was left unmatched", s["unmatched_count"] == 0, s["unmatched_count"])

# Real spending IS counted.
spend = moves + [t("2025-01-09", -2364.06, "BILT PAYMENT BILTRENT dxxxxxxa27 — Electronic Debit"),
                 t("2025-01-10", -18.99, "Spotify USA 877-7781161 CARD: 65 — Debit")]
s = budget.summary(budget.classify(conn, spend))
check("rent and subscriptions are expenses",
      abs(s["by_kind"]["expense"] + 2383.05) < 0.005, s["by_kind"]["expense"])
check("the card blind spot is reported, not hidden",
      abs(s["card_blind_spot"] - 1200.00) < 0.005, s["card_blind_spot"])

# The blind spot is money paid to cards MINUS what those cards can now account
# for, and a payment appears TWICE in a ledger that holds both sides — leaving
# the bank and arriving at the card. Counting both legs doubles the money-out
# half and reports a blind spot roughly twice the truth. The fixture above has
# only the bank leg, so it cannot tell a correct sum from a doubled one; this
# one carries both.
def card_row(day, amount, description, category_hint=None):
    return {"id": None, "txn_date": day, "amount": amount,
            "description": description, "kind": "debit", "account_kind": "credit"}


both_legs = [
    # Out of the bank...
    t("2025-01-07", -1200.00, "CARDMEMBER SERV WEB PYMT ******* — Electronic Debit"),
    # ...and into the card, which is the same $1,200 seen from the other side.
    card_row("2025-01-07", 1200.00, "CARDMEMBER SERV WEB PYMT"),
    # What that card can actually account for.
    card_row("2025-01-04", -18.99, "Spotify USA 877-7781161"),
    # A balance transfer OFF this card: money leaving a card account, which is
    # not spending the card accounts for and is not money paid to cards either.
    # It is the only row that tells a correct blind spot from one that counted
    # the card's own side of a payment.
    card_row("2025-01-20", -500.00, "CARDMEMBER SERV WEB PYMT *******"),
]
for row in both_legs:
    row.setdefault("account_kind", "checking")
s = budget.summary(budget.classify(conn, both_legs))
check("a payment seen from both sides is only counted once as money out",
      abs(s["card_blind_spot"] - (1200.00 - 18.99)) < 0.005, s["card_blind_spot"])

# ------------------------------------------------------------- income ----
s = budget.summary(budget.classify(conn, [
    t("2025-01-31", 5000.00, "L3HARRIS TECH IN PAYROLL xxxxx92 — Electronic Deposit"),
    t("2025-01-31", 3.21, "IOD Interest Payment")]))
check("payroll is income", s["by_kind"]["income"] == 5003.21, s["by_kind"])

# ------------------------------------------------------------- rules ----
# Priority first, then the longer pattern. Without the length tiebreak two rules
# of equal priority apply in whatever order the database returns them, so a row
# would change category for no visible reason.
rules = budget.load_rules(conn)
prios = [r["priority"] for r in rules]
check("rules come back strongest first", prios == sorted(prios, reverse=True))
eats = budget.match("UBER* EATS 8005928996 CARD: 12", rules)
trip = budget.match("UBER* TRIP WWW.UBER.COM. CARD: 9", rules)
check("a more specific rule wins over a general one of the same priority",
      eats and eats["category"] == "Dining", eats and eats["category"])
check("and the general one still matches what it should",
      trip and trip["category"] == "Transport", trip and trip["category"])
check("matching ignores case",
      (budget.match("spotify usa", rules) or {}).get("category") == "Subscriptions")
check("a description matching nothing returns nothing",
      budget.match("QQQ WIDGET CO 12345", rules) is None)

# ------------------------------------------------------ unmatched bucket ----
# Unmatched is never folded into a spending category. A budget that quietly
# absorbs what it does not understand looks complete and is not.
s = budget.summary(budget.classify(conn, [t("2025-02-01", -1935.00, "1800ACCT 646-8299082 CARD: 9603")]))
check("an unrecognised row is not counted as spending", s["by_kind"].get("expense", 0) == 0)
check("it is counted as unmatched", s["unmatched_count"] == 1, s["unmatched_count"])
check("its total is reported", abs(s["unmatched_total"] + 1935.00) < 0.005, s["unmatched_total"])
check("and it is listed so it can be fixed",
      s["unmatched"] and s["unmatched"][0]["description"].startswith("1800ACCT"))
check("no category was invented for it",
      all(c["category"] != "Other spending" for c in s["by_category"]), s["by_category"])

# The list is largest first: the next rule worth writing is the biggest thing
# the rules do not yet understand.
s = budget.summary(budget.classify(conn, [
    t("2025-02-01", -10.00, "SMALL MYSTERY"), t("2025-02-02", -900.00, "BIG MYSTERY"),
    t("2025-02-03", -70.00, "MID MYSTERY")]))
check("unmatched is ranked by size",
      [u["description"] for u in s["unmatched"]] == ["BIG MYSTERY", "MID MYSTERY", "SMALL MYSTERY"],
      [u["description"] for u in s["unmatched"]])

# ----------------------------------------------------- grouping the tail ----
# 264 uncategorised transactions is 264 decisions listed one by one and about 30
# grouped, because most of the tail is the same few shops seen again and again.
# Grouping is what makes finishing the job plausible.
check("a card number is not part of the merchant name",
      budget.suggest_pattern("SPOTIFY USA 877-7781161 CARD: 6503 — Debit Card Purchase")
      == "SPOTIFY USA",
      budget.suggest_pattern("SPOTIFY USA 877-7781161 CARD: 6503 — Debit Card Purchase"))
check("the importer's own suffix is dropped",
      "Debit" not in budget.suggest_pattern("ATT*BILL PAYMENT — Electronic Debit"))
# The bug this had: "1800ACCT" contains "ACCT", and stripping account markers
# without requiring a space before them turned the merchant into "1800" — both
# a wrong name and a rule that would match a thousand unrelated amounts.
check("a marker inside a merchant name is not stripped",
      budget.suggest_pattern("1800ACCT 646-8299082 CARD: 9603 — Debit Card Purchase")
      == "1800ACCT",
      budget.suggest_pattern("1800ACCT 646-8299082 CARD: 9603 — Debit Card Purchase"))

# THE invariant, and the bug that made the categoriser feel broken: the pattern
# offered for a transaction has to be findable in that transaction. It was not,
# in two separate ways, and both failed silently — the rule was written, stored,
# and simply never matched anything, so picking a category appeared to do
# nothing at all. 101 of 383 merchant groups were unusable this way.
SAMPLES = [
    # Fixed-width padding: the suggestion collapsed the run of spaces, the
    # matcher compared literally, and the two could never meet.
    "UBER   *TRIP",
    "WM SUPERCENTER #3225   ROWLETT       TX",
    # An interior store number was spliced OUT, leaving a string that is not a
    # contiguous substring of the description under any comparison.
    "Crash Champions 0169 - ROWLETT       TX",
    "DILLARDS 744 MALL OF A ABILENE       TX",
    "ZOOM.COM 888-799-9666  ZOOM.US       CA",
    "GLACIARIUM SAN ISIDRO AR - 80000.0000 ARGENTINE PESO",
    "BC *UBER CASH 800-592-8996 CARD: — Debit Card Purchase",
    "SPOTIFY USA 877-7781161 CARD: 6503 — Debit Card Purchase",
    "1800ACCT 646-8299082 CARD: 9603 — Debit Card Purchase",
]
unfindable = [s for s in SAMPLES
              if budget.norm(budget.suggest_pattern(s)) not in budget.norm(s)]
check("a suggested pattern is always findable in its own description",
      not unfindable, unfindable)
# And the same invariant measured end to end: the rule a description produces
# must actually classify that description.
def _rule_for(description):
    return [{"pattern": budget.norm(budget.suggest_pattern(description)),
             "category": "Shopping", "kind": "expense", "priority": 150, "id": 1}]

unclassified = [s for s in SAMPLES if budget.match(s, _rule_for(s)) is None]
check("the rule written from a description classifies that description",
      not unclassified, unclassified)
check("matching ignores how many spaces the exporter used",
      budget.match("COSTCO   WHSE  #1234", [{"pattern": "COSTCO WHSE", "category": "Groceries",
                                             "kind": "expense", "priority": 150, "id": 1}])
      is not None)

many = [t("2026-01-05", -12.50, "IC* INSTACART SAN FRANCISCO CA"),
        t("2026-02-05", -30.00, "IC* INSTACART SAN FRANCISCO CA"),
        t("2026-03-05", -20.00, "IC* INSTACART SAN FRANCISCO CA"),
        t("2026-01-09", -900.00, "ONE OFF SHOP 12345")]
groups = budget.group_unmatched(many)
check("charges from one merchant collapse to one row", len(groups) == 2, len(groups))
biggest = groups[0]
check("the largest total comes first", biggest["count"] == 1 and biggest["total"] == -900.00,
      biggest)
instacart = [g for g in groups if "INSTACART" in g["pattern"]][0]
check("the group counts every charge", instacart["count"] == 3, instacart["count"])
check("and sums them", abs(instacart["total"] + 62.50) < 0.005, instacart["total"])
check("and reports the span they cover",
      instacart["first"] == "2026-01-05" and instacart["last"] == "2026-03-05", instacart)

# The suggested pattern has to actually match what it was derived from, or the
# rule it writes silently covers nothing.
rules = [{"pattern": instacart["pattern"].upper(), "category": "Groceries",
          "kind": "expense", "priority": 100, "id": 1}]
check("the suggested pattern matches every charge it was built from",
      all(budget.match(x["description"], rules) for x in many[:3]),
      instacart["pattern"])

# ------------------------------------------------------------ monthly ----
# Averaged over months that HAVE spending. Dividing by the calendar understates
# it whenever the export starts or ends mid-month.
s = budget.summary(budget.classify(conn, [
    t("2025-01-10", -100.00, "Spotify USA"), t("2025-02-10", -300.00, "Spotify USA")]))
check("monthly spend averages over months with spending in them",
      s["monthly_spend"] == 200.00, s["monthly_spend"])
check("and is reported as a positive number", s["monthly_spend"] > 0, s["monthly_spend"])

# Both months above have spending in them, so that fixture cannot tell "months
# with spending" from "every month in the range". The case the rule exists for
# is a month the export touches without any spending in it — the payday at the
# end of a half-imported January, or a month that is nothing but a transfer.
# Dividing by the calendar there reports $150 a month for someone spending $300.
s = budget.summary(budget.classify(conn, [
    t("2025-01-10", -300.00, "Spotify USA"),
    t("2025-02-10", 5000.00, "L3HARRIS TECH IN PAYROLL xxxxx92 — Electronic Deposit")]))
check("a month with income but no spending does not dilute the average",
      s["monthly_spend"] == 300.00, s["monthly_spend"])
check("that month is still present in the monthly series",
      [m["month"] for m in s["by_month"]] == ["2025-01", "2025-02"],
      [m["month"] for m in s["by_month"]])
check("with no spending at all there is no average rather than a zero",
      budget.summary(budget.classify(conn, [
          t("2025-01-10", 5000.00, "L3HARRIS TECH IN PAYROLL xxxxx92 — Electronic Deposit")
      ]))["monthly_spend"] is None)
check("the monthly series covers each month once",
      [m["month"] for m in s["by_month"]] == ["2025-01", "2025-02"],
      [m["month"] for m in s["by_month"]])

# ---------------------------------------------------------- overrides ----
# A single row can be corrected without inventing a pattern for it.
conn.execute("INSERT INTO institutions (id, name) VALUES (1, 'Test Bank')")
conn.execute("INSERT INTO accounts (id, institution_id, external_id, name, kind) "
             "VALUES (1, 1, 'TESTACCT', 'Test Checking', 'checking')")
conn.execute("INSERT INTO transactions (id, account_id, txn_date, kind, amount, description, source, source_id) "
             "VALUES (900, 1, '2025-03-01', 'debit', -50.0, 'Spotify USA', 'test', 'x900')")
cid = conn.execute("SELECT id FROM categories WHERE name = 'Health'").fetchone()["id"]
conn.execute("UPDATE transactions SET category_id = ? WHERE id = 900", (cid,))
conn.commit()
got = budget.classify(conn, [t("2025-03-01", -50.0, "Spotify USA", tid=900)])[0]
check("a manual override beats the rule that would otherwise match",
      got["category"] == "Health", got["category"])
check("and says it was manual", got["category_source"] == "manual", got["category_source"])

# ----------------------------------------------------------- add rule ----
made = budget.add_rule(conn, "1800ACCT", "Health", 150)
check("a new rule can be added", made.get("id"), made)
s = budget.summary(budget.classify(conn, [t("2025-02-01", -1935.00, "1800ACCT 646-8299082")]))
check("and it takes effect on existing history immediately",
      s["unmatched_count"] == 0 and abs(s["by_kind"]["expense"] + 1935.00) < 0.005, s["by_kind"])
check("adding it twice does not duplicate it",
      budget.add_rule(conn, "1800ACCT", "Health", 150).get("already") is True)

for bad, why in [(("ab", "Health"), "a pattern too short to be a rule"),
                 (("SOMETHING", "No Such Category"), "an unknown category")]:
    try:
        budget.add_rule(conn, *bad)
        check(f"refuses {why}", False, "it was accepted")
    except ValueError:
        check(f"refuses {why}", True)

check("a rule can be removed", budget.remove_rule(conn, made["id"])["removed"] == 1)
s = budget.summary(budget.classify(conn, [t("2025-02-01", -1935.00, "1800ACCT 646-8299082")]))
check("removing it puts the transaction back in unmatched", s["unmatched_count"] == 1)

conn.close()

# ------------------------------------------------------------- goals -------
# Plan-vs-actual compared an imported spreadsheet whose category names are its
# own, matched almost none of them, and reported 62,587 against 8,242. Targets
# from your own trailing average cannot fail to match.
_bm = [
    {"month": "2026-01", "income": 10_000.0, "expense": -6_000.0, "investment": -1_000.0},
    {"month": "2026-02", "income": 10_000.0, "expense": -8_000.0},
    {"month": "2026-03", "income": 10_000.0, "expense": -4_000.0},
]
_g = budget.goals(_bm, None, savings_goal=3_500.0, asof="2026-04-10")
check("saving is income minus spending", _g["months"][0]["saved"] == 4_000.0,
      str(_g["months"][0]))
check("a month that cleared the goal is marked met", _g["months"][0]["met"] is True)
check("a month that missed it is not", _g["months"][1]["met"] is False,
      "2,000 saved against a 3,500 goal")
check("money moved to investments is not counted as spending",
      _g["months"][0]["saved"] == 4_000.0,
      "it left the current account but it was kept, which is the point")
check("the goal is the one figure NOT taken from history",
      _g["goal"] == 3_500.0 and _g["average_saved"] != _g["goal"],
      "a goal set to what you already do is not a goal")

# The current month is always partial. Comparing eight days against a full
# month's average shows every category comfortably under target, every month,
# until the last day of it.
_bm2 = _bm + [{"month": "2026-04", "income": 2_000.0, "expense": -1_000.0}]
_part = budget.goals(_bm2, None, savings_goal=3_000.0, asof="2026-04-10")
check("the current month is pro-rated, not compared against a full month",
      0.3 < _part["current"]["elapsed"] < 0.35, str(_part["current"]["elapsed"]))
check("...and on-track is judged against the pro-rated goal",
      _part["current"]["on_track"] is True,
      "1,000 saved by the 10th beats 3,000 x 33%")
check("a partial month is excluded from the trailing average",
      all(m["month"] != "2026-04" for m in _part["months"]),
      "averaging in a part-month drags every target down")

# Category targets come from the trailing average, in the parallel-array shape
# the payload actually uses. Reading it as one row per category-month produced
# zero categories in silence.
_cm = ["2026-01", "2026-02", "2026-03", "2026-04"]
_bcm = [{"category": "Groceries", "values": [500.0, 600.0, 700.0, 900.0]}]
_gc = budget.goals(_bm2, _bcm, savings_goal=3_000.0, asof="2026-04-10",
                   category_months=_cm)
check("a category target is its own trailing average",
      _gc["categories"][0]["target"] == 600.0, str(_gc["categories"][0]))
check("this month's spending is measured against the pro-rated target",
      _gc["categories"][0]["spent"] == 900.0
      and _gc["categories"][0]["over"] is True,
      "900 by the 10th against a 600 month is over")
check("no categories are claimed without the month labels to align them",
      budget.goals(_bm2, _bcm, asof="2026-04-10")["categories"] == [],
      "the values are a parallel array; without the labels they mean nothing")
check("an empty ledger reports unavailable rather than dividing by zero",
      budget.goals([], None)["available"] is False)

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
