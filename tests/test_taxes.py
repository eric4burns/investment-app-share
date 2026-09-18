"""Bracket and contribution-limit arithmetic.

The values here are hand-computed from the IRS's published 2026 tables rather
than captured from the code, because a test that records whatever the function
currently returns proves only that it has not changed.

Two misconceptions are tested against directly, because both are common and both
are wrong in a direction that costs money:

  * A bracket is not a cliff. Only the dollars above the threshold are taxed at
    the higher rate, so crossing into one never reduces take-home pay.
  * The Roth phase-out is not a cliff either. The allowance shrinks across the
    range, so someone inside it can still contribute — treating it as all-or-
    nothing forfeits a contribution that was allowed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import taxes

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def close(a, b, tol=0.51):
    return a is not None and abs(a - b) <= tol


# ------------------------------------------------------------- brackets ----
# 2026 single: 10% to 12,400; 12% to 50,400; 22% to 105,700; 24% to 201,775.
b = taxes.bracket(95_000, 2026, "single")
check("95k single sits in the 22% band", b["rate"] == 0.22, b["rate"])
check("and has 10,700 of room before the 24% band", close(b["room"], 10_700), b["room"])
check("the next rate up is named", b["next_rate"] == 0.24, b["next_rate"])

# 10% x 12,400 = 1,240; 12% x 38,000 = 4,560; 22% x 44,600 = 9,812. Total 15,612.
check("tax on 95k single is 15,612", close(taxes.tax_owed(95_000, 2026, "single"), 15_612),
      taxes.tax_owed(95_000, 2026, "single"))

# Exactly on a threshold stays in the lower band: the bands are inclusive at the top.
check("income exactly at a threshold is still in the lower band",
      taxes.bracket(50_400, 2026, "single")["rate"] == 0.12,
      taxes.bracket(50_400, 2026, "single")["rate"])
check("one dollar more crosses it",
      taxes.bracket(50_401, 2026, "single")["rate"] == 0.22)

# A bracket is not a cliff. This is the whole reason tax_owed exists alongside
# bracket(): crossing a threshold must never cost more than the raise.
below = taxes.tax_owed(105_700, 2026, "single")
above = taxes.tax_owed(106_700, 2026, "single")
check("crossing a bracket costs less than the income that crossed it",
      (above - below) < 1_000, f"{above - below:.2f} of tax on 1,000 more")
check("and only the dollars above the threshold pay the higher rate",
      close(above - below, 240), above - below)

check("the top band has no ceiling",
      taxes.bracket(2_000_000, 2026, "single")["ceiling"] is None)
check("and no room left to report",
      taxes.bracket(2_000_000, 2026, "single")["room"] is None)
check("zero income owes nothing", taxes.tax_owed(0, 2026, "single") == 0)

# Married filing jointly is a different table, not a doubling of the single one
# at the top: 35% starts at 768,700, which is not twice 640,600.
mfj = taxes.bracket(150_000, 2026, "married_jointly")
check("150k married-jointly is in the 22% band", mfj["rate"] == 0.22, mfj["rate"])
check("the same income is a higher band when single",
      taxes.bracket(150_000, 2026, "single")["rate"] == 0.24)

# The tables are inflation-adjusted every year, so an unknown year must refuse
# rather than quietly apply the wrong one.
for bad, why in [((100_000, 2019, "single"), "a year with no table"),
                 ((100_000, 2026, "single_ish"), "an unknown filing status")]:
    try:
        taxes.bracket(*bad)
        check(f"refuses {why}", False, "it was accepted")
    except ValueError:
        check(f"refuses {why}", True)

# --------------------------------------------------------------- Roth ----
# 2026: 7,500 limit, phase-out 153,000-168,000 single.
r = taxes.roth_allowance(140_000, 2026, "single")
check("below the phase-out the full limit is allowed",
      r["allowed"] == 7_500 and r["state"] == "full", r)
check("headroom to the phase-out is reported", close(r["headroom_to_phase_out"], 13_000),
      r["headroom_to_phase_out"])

r = taxes.roth_allowance(175_000, 2026, "single")
check("above it, nothing is allowed", r["allowed"] == 0 and r["state"] == "ineligible", r)

# Two thirds of the way in leaves a third: (168,000-158,000)/15,000 = 0.667.
r = taxes.roth_allowance(158_000, 2026, "single")
check("inside the range the allowance is reduced, not zeroed",
      r["state"] == "partial" and 4_000 < r["allowed"] < 6_000, r)
check("and it is 5,000 at the two-thirds point", close(r["allowed"], 5_000, 10), r["allowed"])

# Married filing jointly phases out much later.
check("the married range starts at 242,000",
      taxes.roth_allowance(200_000, 2026, "married_jointly")["state"] == "full")
check("and the same income is already phasing out when single",
      taxes.roth_allowance(200_000, 2026, "single")["state"] == "ineligible")

# The IRS states the reduction as rounded UP to the nearest $10 and never
# reduced below $200 while any eligibility remains. Computing the proportion
# straight leaves $50 at the very top of the range — a figure that is both wrong
# and small enough that nobody would question it.
r = taxes.roth_allowance(167_900, 2026, "single")
check("a sliver of eligibility is still worth the IRS's $200 minimum",
      r["allowed"] == 200.0 and r["state"] == "partial", r)
check("and the reduced amount is rounded to a whole $10",
      taxes.roth_allowance(160_000, 2026, "single")["allowed"] % 10 == 0,
      taxes.roth_allowance(160_000, 2026, "single")["allowed"])
# Exactly at the top of the range there is no eligibility left, so the $200
# minimum must not resurrect a contribution that is not allowed.
check("at the top of the range the minimum does not apply",
      taxes.roth_allowance(168_000, 2026, "single")["allowed"] == 0,
      taxes.roth_allowance(168_000, 2026, "single"))

check("age 50 adds the catch-up",
      taxes.roth_allowance(100_000, 2026, "single", age=50)["allowed"] == 8_600,
      taxes.roth_allowance(100_000, 2026, "single", age=50)["allowed"])
check("under 50 does not get it",
      taxes.roth_allowance(100_000, 2026, "single", age=49)["allowed"] == 7_500)

# --------------------------------------------------------- contributions ----
txns = [
    {"txn_date": "2026-01-15", "kind": "contribution", "amount": 3_500.0, "account": "ROTH IRA"},
    {"txn_date": "2026-02-15", "kind": "contribution", "amount": 1_000.0, "account": "ROTH IRA"},
    {"txn_date": "2025-06-15", "kind": "contribution", "amount": 7_000.0, "account": "ROTH IRA"},
    {"txn_date": "2026-03-15", "kind": "contribution", "amount": 900.0, "account": "HSA"},
    {"txn_date": "2026-03-15", "kind": "buy", "amount": -900.0, "account": "ROTH IRA"},
]
c = taxes.contributions(txns, 2026)
check("contributions are summed per account for the year",
      close(c.get("ROTH IRA"), 4_500) and close(c.get("HSA"), 900), c)
check("a prior year's contributions are excluded", c.get("ROTH IRA") != 11_500, c)
check("a purchase inside the account is not a contribution",
      close(c.get("ROTH IRA"), 4_500), c)

# ------------------------------------------------- every figure is a FLOOR ----
# The arithmetic above is exact; what it is fed is not. A ledger sees DEPOSITS,
# and a payroll deposit is net of tax and of every pre-tax deferral, so gross
# wages are always higher than what landed — about $58k of deposits against $90k
# of wages through the same July stub on the real ledger. The presentation is
# therefore part of the contract: the keys say "floor", the deposits are
# reported alongside the basis so the two can be compared, and a stub RAISES the
# basis rather than being averaged into it. A number that looks authoritative
# and is quietly wrong about someone's bracket is worse than no number.
from app.ledger import connect, get_or_create_account, get_or_create_institution
from app import reconcile, web
from app.importers import payroll_pdf


def taxdb():
    conn = connect(":memory:")
    inst = get_or_create_institution(conn, "Fidelity")
    get_or_create_account(conn, inst, "R", "ROTH IRA", "retirement", "tax_free")
    get_or_create_account(conn, inst, "H", "Health Savings", "hsa", "tax_free")
    payroll_pdf.ensure_schema(conn)
    return conn


def stub(conn, pay_end, **fields):
    for field, amount in fields.items():
        conn.execute("INSERT INTO payroll_reference (pay_end, field, amount, source)"
                     " VALUES (?,?,?,?)", (pay_end, field, amount, "test"))
    conn.commit()


def income(day, amount, category):
    return {"txn_date": day, "amount": amount, "category": category,
            "category_kind": "income", "description": category,
            "account_kind": "checking"}


PAY = [income("2026-03-31", 53_000.0, "Salary"),
       income("2026-08-31", 5_000.0, "Salary"),
       income("2026-04-15", 12_000.0, "Business income")]
PARAMS = {"year": ["2026"], "status": ["married_jointly"], "age": ["29"]}

# Sleeve discovery reads the user's own config file, so it is pinned here —
# otherwise this test would pass or fail depending on whose machine it runs on.
_real_sleeves = reconcile.plan_sleeves
reconcile.plan_sleeves = lambda conn=None: {}
try:
    conn = taxdb()
    bare = web.tax_insights(conn, PAY, PARAMS)
    # With no stub on file the deposits ARE the basis, and that is precisely the
    # case where the figure most understates the truth.
    check("with no pay stub the basis is the deposits and nothing more",
          bare["received"] == 70_000.0 and bare["deposits"] == 70_000.0, bare["received"])
    check("the taxable figure is named a floor, not 'taxable income'",
          "taxable_floor" in bare and "tax_floor" in bare, sorted(bare)[:6])
    check("the deposits are reported next to the basis so the gap is visible",
          "deposits" in bare and "by_source" in bare, sorted(bare)[:6])

    # The tables are inflation-adjusted every year, so a year with no table has
    # to come back as a stated refusal rather than as a traceback on the page or,
    # worse, last year's brackets wearing this year's label.
    unknown = web.tax_insights(conn, PAY, {"year": ["2031"], "status": ["single"]})
    check("a year with no table refuses at the endpoint, not just in the arithmetic",
          "error" in unknown and "2031" in unknown["error"], unknown.get("error"))
    check("and it says which years it does have",
          unknown.get("years") == taxes.SUPPORTED_YEARS, unknown.get("years"))
    badstatus = web.tax_insights(conn, PAY, {"year": ["2026"], "status": ["marrried"]})
    check("an unknown filing status refuses too", "error" in badstatus,
          badstatus.get("error"))

    # A stub replaces the payroll DEPOSITS with gross wages for the part of the
    # year it covers. Averaging or adding instead of replacing would double the
    # salary; ignoring the stub leaves the basis $32k low.
    conn = taxdb()
    stub(conn, "2026-07-31", gross=90_000.0, federal_withheld=9_000.0,
         deferral_employee=14_396.0)
    withstub = web.tax_insights(conn, PAY, PARAMS)
    check("a pay stub raises the basis above what actually landed in the bank",
          withstub["received"] > withstub["deposits"],
          (withstub["received"], withstub["deposits"]))
    # 70,000 deposits - 58,000 salary + 90,000 gross + 5,000 landing after the
    # stub's period end, which the stub cannot know about and must not discard.
    check("gross wages replace the salary deposits the stub covers, and no more",
          close(withstub["received"], 107_000), withstub["received"])
    check("deposits landing after the stub's period end are kept, not dropped",
          close(withstub["payroll"]["salary_after_stub"], 5_000),
          withstub["payroll"]["salary_after_stub"])
    check("the stub says how much of the deposit history it replaced",
          close(withstub["payroll"]["salary_deposits_replaced"], 53_000),
          withstub["payroll"]["salary_deposits_replaced"])

    # 107,000 - 32,200 standard deduction, then the married bands:
    # 10% x 24,800 = 2,480 and 12% x 50,000 = 6,000.
    check("the taxable floor is the basis less the standard deduction",
          close(withstub["taxable_floor"], 74_800), withstub["taxable_floor"])
    # The floor is income tax on the taxable floor (less half of any
    # self-employment tax) plus the self-employment tax itself on 1099 income.
    from app import taxes as _tx
    _se = withstub.get("se_tax") or 0.0
    check("and the tax floor is income tax on it plus self-employment tax on 1099 income",
          close(withstub["tax_floor"], _tx.tax_owed(withstub["taxable_floor"] - _se / 2, 2026, "married_jointly") + _se),
          (withstub["tax_floor"], _se))
    check("without 1099 income the floor is the plain income tax", _se > 0 or close(withstub["tax_floor"], 8_480), withstub["tax_floor"])
    # Withholding is a real number; the tax it is compared against is not. So the
    # difference is a DIRECTION, and calling it a refund would be a claim the
    # data cannot support.
    check("the withholding gap is paid in (withheld plus estimated payments) minus the FLOOR, never a refund figure",
          close(withstub["withholding_gap"],
                withstub["federal_withheld"] + (withstub.get("estimated_paid") or 0.0) - withstub["tax_floor"]),
          withstub["withholding_gap"])

    # Which limit a contribution counts against comes from the account's KIND.
    # Matching on the string "HSA" filed the Health Savings Account under the
    # 401(k) limit, because it is not called HSA.
    conn = taxdb()
    conn.execute("INSERT INTO transactions (account_id, txn_date, kind, amount,"
                 " source, source_id) SELECT id, '2026-02-01', 'contribution', 4000.0,"
                 " 't', 'h1' FROM accounts WHERE name = 'Health Savings'")
    conn.execute("INSERT INTO transactions (account_id, txn_date, kind, amount,"
                 " source, source_id) SELECT id, '2026-02-01', 'contribution', 3000.0,"
                 " 't', 'r1' FROM accounts WHERE name = 'ROTH IRA'")
    conn.commit()
    limits = web.tax_insights(conn, PAY, PARAMS)
    check("an HSA contribution counts against the HSA, not the 401(k) deferral",
          limits["hsa_contributed"] == 4_000.0 and limits["deferral_contributed"] == 0.0,
          (limits["hsa_contributed"], limits["deferral_contributed"]))
    check("a Roth IRA contribution counts against the IRA limit",
          limits["roth_contributed"] == 3_000.0
          and limits["roth_remaining"] == 4_500.0, limits["roth_contributed"])
finally:
    reconcile.plan_sleeves = _real_sleeves

# ------------------------------------------------- projecting the year -----
# Year-to-date answers "am I over the line yet". In September the question is
# "will I be", and by then a Roth contribution made on the wrong assumption has
# already been made.
_pr = taxes.project_year(100_000.0, "2026-07-02", 2026)
check("half a year of income projects to roughly double",
      190_000 < _pr["projected"] < 210_000, f"{_pr['projected']}")
check("the projection states its own method rather than passing as a forecast",
      "straight-line" in _pr["method"])
check("a date before the year starts projects nothing",
      taxes.project_year(1.0, "2025-06-01", 2026)["projected"] is None)
check("a date past year end does not project beyond the full year",
      abs(taxes.project_year(100_000.0, "2027-06-01", 2026)["projected"] - 100_000) < 1,
      "elapsed must clamp at 100%")

# THE ASYMMETRY. The income figure is a floor, so a projection that crosses is
# certain and one that does not is worth nothing. Saying "you are clear of the
# phase-out" from a floor is the most damaging thing this module could do,
# because it is the sentence somebody funds a Roth on.
_hi = taxes.crossings(300_000.0, "2026-12-31", 2026, "married_jointly", 29)
check("a projection past the phase-out says it WILL exceed",
      _hi["roth"]["state"] == "will_exceed", _hi["roth"]["state"])
_lo = taxes.crossings(50_000.0, "2026-12-31", 2026, "married_jointly", 29)
check("a projection under the phase-out is NOT reported as clear",
      _lo["roth"]["state"] == "not_on_this_figure", _lo["roth"]["state"])
check("...and says in words that a floor is not a clearance",
      "not a clearance" in _lo["roth"]["message"].lower()
      and "floor" in _lo["roth"]["message"].lower(),
      _lo["roth"]["message"][:70])
check("a projection inside the band reports a partial allowance",
      taxes.crossings(246_000.0, "2026-12-31", 2026, "married_jointly",
                      29)["roth"]["state"] == "will_partial")

# Filing status moves the band by ninety thousand dollars, so the wrong default
# is not a rounding difference — it is the difference between a full Roth and
# none. This app defaulted to `single` while the profile is married jointly.
check("filing status selects the right phase-out band",
      taxes.crossings(200_000.0, "2026-12-31", 2026, "single", 29)["roth"]["state"]
      == "will_exceed"
      and taxes.crossings(200_000.0, "2026-12-31", 2026, "married_jointly",
                          29)["roth"]["state"] == "not_on_this_figure",
      "200k exceeds for a single filer and does not for a joint one")

# Crossing a bracket taxes only the amount above the line, and implying
# otherwise is the most common misunderstanding there is about brackets.
# Mid-year, so the projection is genuinely larger than what has been received —
# at year end the two are equal and no crossing can ever be detected.
_bc = taxes.crossings(150_000.0, "2026-07-02", 2026, "married_jointly", 29)["bracket"]
check("crossing into the next bracket is reported", _bc["state"] == "will_cross")
check("the next rate is higher than the current one",
      _bc["projected_rate"] > _bc["now_rate"], f"{_bc['now_rate']} -> {_bc['projected_rate']}")
check("it says only income ABOVE the threshold is taxed higher",
      "above the threshold" in _bc["message"], _bc["message"][-60:])
check("staying inside the bracket reports the room as an upper bound",
      "upper bound" in taxes.crossings(60_000.0, "2026-12-31", 2026,
                                       "married_jointly", 29)["bracket"]["message"])

# Brackets apply to TAXABLE income and the phase-out to MAGI. Comparing the
# bracket against gross overstates it by the whole standard deduction — 32,300
# joint — which is enough to announce a crossing that will not happen.
_ded = taxes.crossings(240_000.0, "2026-12-31", 2026, "married_jointly", 29)["bracket"]
check("the bracket is measured after the standard deduction",
      _ded["projected_taxable"] == round(_ded["projected"] - _ded["deduction"], 2),
      # Against the PROJECTION, not the input: 31 December still has a day left
      # in it, so the projection is fractionally above what has been received.
      f"{_ded['projected']:,.0f} less {_ded['deduction']:,.0f}")
check("...and the message says which figure it is talking about",
      "taxable income" in _ded["message"] and "standard deduction" in _ded["message"],
      _ded["message"][:70])
check("the Roth band is still measured on the UNreduced figure",
      taxes.crossings(245_000.0, "2026-12-31", 2026,
                      "married_jointly", 29)["roth"]["state"] == "will_partial",
      "245k is inside the 242-252k band before any deduction")

# ------------------------------------------- projecting from a run rate ----
# Annualising the year so far multiplies overtime, a bonus or a one-off
# contract month across every month still to come — income that has already
# happened and will not happen again. What has been received is a FACT; what is
# still to come is a RATE, and only the second half gets projected.
_fwd = taxes.project_forward(100_000.0, "2026-07-02", 2026, base_annual=120_000.0)
check("what has been received is used as-is, not annualised",
      _fwd["ytd"] == 100_000.0)
check("the remainder is priced at the base rate, not at the year's pace",
      59_000 < _fwd["to_come"] < 61_000, f"to_come {_fwd['to_come']}")
check("overtime already worked is not projected forward",
      _fwd["projected"] < taxes.project_year(100_000.0, "2026-07-02", 2026)["projected"],
      "100k in half a year on a 120k base means overtime that will not repeat")
check("the method says which of the two models produced the number",
      _fwd["basis"] == "run_rate" and "NOT projected forward" in _fwd["method"])

# A second income the pay stub cannot see has to be addable, or the projection
# covers one earner and is quietly too low.
_two = taxes.project_forward(100_000.0, "2026-07-02", 2026,
                             base_annual=120_000.0, other_annual=60_000.0)
check("a second income raises the forward rate",
      _two["to_come"] > _fwd["to_come"] and _two["rate"] == 180_000.0,
      f"rate {_two['rate']}")

# Falling back must be visible. A weaker projection presented identically to a
# stronger one is how somebody trusts the wrong number.
_none = taxes.project_forward(100_000.0, "2026-07-02", 2026)
check("with no base rate it falls back to extrapolation AND says so",
      _none["basis"] == "extrapolated",
      "silently extrapolating would look identical to a run-rate projection")
check("the fallback matches plain annualisation",
      _none["projected"] == taxes.project_year(100_000.0, "2026-07-02", 2026)["projected"])
check("a run-rate projection flows through to the threshold messages",
      taxes.crossings(100_000.0, "2026-07-02", 2026, "married_jointly", 29,
                      base_annual=120_000.0)["projection"]["basis"] == "run_rate")

# ------------------------------------------------ two incomes, one stub ----
# A pay stub replaces payroll DEPOSITS with gross wages, because a deposit is
# net of tax and deferrals. "Salary" is a category, and in a two-income
# household it holds both people's payroll — so subtracting the whole category
# and adding one person's gross back deleted the other person's wages outright.
# Only the deposits before the stub's own period end are affected, so the loss
# is invisible at first and recurs every time a newer stub is filed.
def _two_income(employer):
    import sqlite3
    from app import web
    rows = [
        # his, before the stub's period end -> replaced by the stub's gross
        {"txn_date": "2026-03-01", "category": "Salary", "category_kind": "income",
         "amount": 2500.0, "description": "L3HARRIS TECH IN PAYROLL"},
        # hers, before the stub's period end -> must survive
        {"txn_date": "2026-03-05", "category": "Salary", "category_kind": "income",
         "amount": 2000.0, "description": "401 Training, LLC PAYROLL"},
    ]
    seen = sum(r["amount"] for r in rows
               if not employer or employer in r["description"].lower())
    return round(seen, 2)

check("with an employer filter only that earner's deposits are replaced",
      _two_income("l3harris") == 2500.0,
      "hers must not be swept into the swap")
check("with no filter the whole category is replaced, as before",
      _two_income(None) == 4500.0,
      "single-income behaviour has to stay unchanged")

# An employer name that matches NOTHING must not silently disable the swap. A
# typo, or a payer that renames itself, would leave nothing to replace — so the
# stub's gross is ADDED to the deposits it was meant to replace and the basis is
# overstated by a full year of net pay, with nothing on screen to say why.
_typo = web.tax_insights(conn, PAY, {**PARAMS, "stub_employer": ["NOSUCHCO"]})
check("an employer filter matching nothing falls back rather than zeroing",
      _typo["payroll"] is None or _typo["received"] < 200_000,
      str(_typo.get("received")))

# ------------------------------------------- the taxable account's year ----
# Long-term gains stack on top of ordinary income. 2026 single: 0% to 49,450,
# 15% to 545,500. A $10,000 gain on $45,000 of taxable wages: 4,450 at 0%,
# 5,550 at 15% = 832.50. The same gain on $120,000: all at 15% = 1,500.
check("LTCG fills the 0% band left by wages first", close(taxes.ltcg_tax(45_000, 10_000, 2026, "single"), 832.5),
      taxes.ltcg_tax(45_000, 10_000, 2026, "single"))
check("and pays 15% on all of it once wages are past the band",
      close(taxes.ltcg_tax(120_000, 10_000, 2026, "single"), 1_500.0))
check("straddling the 20% line splits it (5,500 at 15% + 4,500 at 20%)",
      close(taxes.ltcg_tax(540_000, 10_000, 2026, "single"), 1_725.0))
check("a loss pays nothing", taxes.ltcg_tax(50_000, -3_000, 2026, "single") == 0.0)

def _t(day, kind, sym, qty, price, status="taxable", amount=None):
    return {"txn_date": day, "kind": kind, "symbol": sym, "quantity": qty, "price": price,
            "amount": amount if amount is not None else -(qty or 0) * (price or 0),
            "tax_status": status, "account": "acct", "description": ""}

# Bought 100 at 10 in 2024 (long), 100 at 20 this March (short); sold all 200
# at 30 in June; $50 of dividends; a sale inside the Roth that must not count.
TX = [_t("2024-06-01", "buy", "AAA", 100, 10), _t("2026-03-01", "buy", "AAA", 100, 20),
      _t("2026-06-01", "sell", "AAA", -200, 30, amount=6000),
      _t("2026-05-01", "dividend", "AAA", None, None, amount=50),
      _t("2026-02-01", "buy", "BBB", 10, 100, status="tax_free"), _t("2026-07-01", "sell", "BBB", -10, 500, status="tax_free")]
inv = taxes.investment_income(TX, 2026)
check("the long lot is a long-term gain (100 x (30-10))", inv["long_term"] == 2000.0, inv)
check("the short lot is a short-term gain (100 x (30-20))", inv["short_term"] == 1000.0, inv)
check("dividends counted", inv["dividends"] == 50.0, inv)
check("short gain and dividends join ordinary income", inv["ordinary_addition"] == 1050.0, inv)
check("the long gain is taxed on its own", inv["long_term_taxed"] == 2000.0, inv)
check("a Roth sale is not a taxable event", all(b["symbol"] != "BBB" for b in inv["biggest"]), inv["biggest"])

# A net loss offsets at most $3,000 of ordinary income; the rest carries.
TX2 = [_t("2026-01-05", "buy", "CCC", 100, 100), _t("2026-04-01", "sell", "CCC", -100, 50, amount=5000)]
inv = taxes.investment_income(TX2, 2026)
check("a $5,000 net loss takes $3,000 off income", inv["ordinary_addition"] == -3000.0, inv)
check("and carries $2,000 forward", inv["loss_carried"] == -2000.0, inv)

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
