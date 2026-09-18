"""Finding what charges you again and again.

The first version of this called a weekly grocery run a subscription. It was not
wrong about the cadence — 26 H-E-B trips really were about seven days apart —
but "$8,126 a year, weekly" is not something anyone can cancel, and burying
three real subscriptions under a list of shopping habits makes the whole feature
useless. It also reported a fortnightly Robinhood deposit as a recurring charge
that had gone up in price.

So these tests are mostly about the two distinctions that make the output worth
reading: fixed charges versus variable ones, and spending versus moving your own
money.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import recurring

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def series(description, start, every, times, amount, kind="expense", jitter=0):
    """A merchant charging on a cadence."""
    day = date.fromisoformat(start)
    out = []
    for i in range(times):
        a = amount(i) if callable(amount) else amount
        out.append({"txn_date": (day + timedelta(days=every * i + (jitter if i % 2 else 0))).isoformat(),
                    "amount": -abs(a), "description": description,
                    "category_kind": kind, "account": "Card"})
    return out


def find(rows, merchant, asof="2026-08-30"):
    hits = [r for r in recurring.detect(rows, asof=asof) if merchant in r["merchant"]]
    return hits[0] if hits else None


# ------------------------------------------------------ subscriptions ----
netflix = series("NETFLIX.COM 866-579-7172", "2026-01-05", 30, 8, 9.99)
r = find(netflix, "NETFLIX")
check("a fixed monthly charge is found", r is not None)
check("its cadence is monthly", r and r["cadence"] == "monthly", r and r["cadence"])
check("it is called a subscription", r and r["kind"] == "subscription", r and r["kind"])
check("the typical amount is right", r and r["typical"] == 9.99, r and r["typical"])
check("the annual cost is the monthly one times twelve",
      r and abs(r["annual"] - 119.88) < 0.01, r and r["annual"])
check("the next charge is projected", r and r["next_expected"] > r["last"])

# Two charges is one interval, and one interval is not a pattern.
check("two charges are not a subscription",
      find(series("TWICE ONLY LLC", "2026-01-05", 30, 2, 9.99), "TWICE") is None)
check("three are", find(series("THRICE LLC", "2026-01-05", 30, 3, 9.99), "THRICE") is not None)

# A few days of slippage is normal — weekends move payment dates.
r = find(series("SPOTIFY USA", "2026-01-05", 30, 8, 18.39, jitter=3), "SPOTIFY")
check("a charge that slips a few days is still monthly",
      r and r["cadence"] == "monthly", r and r["cadence"])

# Irregular gaps are not a cadence at all.
lumpy = [{"txn_date": d, "amount": -20.0, "description": "RANDOM SHOP",
          "category_kind": "expense"} for d in
         ("2026-01-02", "2026-01-09", "2026-04-20", "2026-04-22", "2026-08-01")]
check("irregular gaps are not reported as recurring", find(lumpy, "RANDOM") is None)

# ------------------------------------------------ subscription vs habit ----
# The distinction the first version got wrong. Both are weekly; only one is
# something you can cancel.
groceries = series("H-E-B #123 ROCKWALL TX", "2026-01-03", 7, 26,
                   lambda i: 40 + (i * 37) % 220)
r = find(groceries, "H E B")
check("a weekly grocery run is found as recurring", r is not None)
check("but it is a habit, not a subscription",
      r and r["kind"] == "habit", r and r["kind"])
check("and it gets no annual projection, which would be fiction",
      r and r["annual"] is None, r and r["annual"])

s = recurring.summary(recurring.detect(netflix + groceries, asof="2026-08-30"))
check("the summary keeps them apart",
      len(s["subscriptions"]) == 1 and len(s["habits"]) == 1,
      (len(s["subscriptions"]), len(s["habits"])))
check("only subscriptions are totalled",
      abs(s["annual_total"] - 119.88) < 0.01, s["annual_total"])

# ------------------------------------------------------------ transfers ----
# A card payment is as regular as any subscription and is not spending.
payments = series("CHASE CREDIT CRD EPAY", "2026-01-10", 30, 8, 500.0, kind="transfer")
deposits = series("ROBINHOOD DEBITS", "2026-01-10", 14, 9, 500.0, kind="investment")
check("a regular card payment is not a subscription", find(payments, "CHASE") is None)
check("nor is a regular brokerage deposit", find(deposits, "ROBINHOOD") is None)
check("and they do not crowd out the real ones",
      len(recurring.detect(netflix + payments + deposits, asof="2026-08-30")) == 1)

# Money coming in is not a charge however regular it is.
income = [{"txn_date": f"2026-0{m}-15", "amount": 5000.0, "description": "PAYROLL",
           "category_kind": "income"} for m in (1, 2, 3, 4, 5)]
check("income is not a subscription", find(income, "PAYROLL") is None)

# ---------------------------------------------------------- price rises ----
# A rise arrives as one slightly larger number among hundreds.
rising = series("HULUPLUS", "2026-01-05", 30, 8,
                lambda i: 9.99 if i < 4 else 12.99)
r = find(rising, "HULU")
check("a price rise is detected", r and r["price_change"] > 0, r and r["price_change"])
check("and measured correctly", r and abs(r["price_change"] - 3.00) < 0.01,
      r and r["price_change"])
check("HULUPLUS is filed under the brand, HULU", r and r["merchant"] == "HULU", r and r["merchant"])
check("the price steps are the two prices with the day each started",
      r and [(h["amount"], h["charges"]) for h in r["history"]] == [(9.99, 4), (12.99, 4)], r and r["history"])

# ------------------------------------------------- bills that reprice ----
# Car insurance: four half-years, 993 -> 960 -> 1,110 -> 1,380. Its spread
# is past the drift line, and it was filed as a habit beside the groceries.
premiums = [993.5, 960.5, 1109.5, 1379.5]
ins = [{"txn_date": d, "amount": -a, "description": "PROG COUNTY MUT INS PREM xxxxx35 — Electronic Debit",
        "category": "Insurance", "category_kind": "expense"}
       for d, a in zip(["2025-01-14", "2025-07-15", "2026-01-14", "2026-07-14"], premiums)]
r = find(ins, "PROGRESSIVE")
check("a repricing insurance premium is a bill, not a habit", r and r["kind"] == "subscription" and r["cadence"] == "semiannual", r and (r["kind"], r["cadence"]))
check("and every step of its price is kept", r and [h["amount"] for h in r["history"]] == premiums, r and r["history"])
uncat = [dict(t, category=None) for t in ins]
r = find(uncat, "PROGRESSIVE")
check("even uncategorised, a semiannual charge with bounded steps is a bill", r and r["kind"] == "subscription", r and r["kind"])
# Two charges a year apart, in a bill category, is an annual bill — one
# interval used to fail a "two must fit" rule and read as irregular.
norton = [{"txn_date": d, "amount": -281.44, "description": "NORTON *AP1628041763 NORTON.COM/CC AZ",
           "category": "Subscriptions", "category_kind": "expense"} for d in ("2025-08-05", "2026-08-05")]
r = find(norton, "NORTON", asof="2026-09-13")
check("two charges a year apart read as annual", r and r["cadence"] == "annual", r and r["cadence"])
# Three spellings of one product are one row.
gone = (series("NETFLIX COM", "2026-01-05", 30, 3, 8.65) + series("NETFLIX INC", "2026-04-05", 30, 3, 8.65))
rows = [x for x in recurring.detect(gone, asof="2026-07-10") if "NETFLIX" in x["merchant"]]
check("NETFLIX COM and NETFLIX INC are one merchant with six charges", len(rows) == 1 and rows[0]["charges"] == 6, [(x["merchant"], x["charges"]) for x in rows])
s = recurring.summary(recurring.detect(rising, asof="2026-08-30"))
check("the annual cost of the rise is what gets reported",
      s["risen"] and abs(s["risen"][0]["annual_increase"] - 36.00) < 0.01,
      s["risen"][0]["annual_increase"] if s["risen"] else None)
check("a steady price is not reported as a rise",
      not recurring.summary(recurring.detect(netflix, asof="2026-08-30"))["risen"])
# One odd charge is not a rise: comparing halves rather than first-to-last is
# what keeps a single unusual month from reading as a permanent increase.
blip = series("STEADY CO", "2026-01-05", 30, 9, lambda i: 50.0 if i != 4 else 200.0)
r = find(blip, "STEADY")
check("one unusual charge is not a price rise",
      r is None or r["price_change"] == 0, r and r["price_change"])

# -------------------------------------------------------------- lapsed ----
# Charges that stopped. The most expensive kind of forgotten.
stopped = series("FIREFLIES.AI", "2025-01-05", 30, 12, 29.00)
r = find(stopped, "FIREFLIES", asof="2026-08-30")
check("a subscription that stopped is flagged", r and r["lapsed"], r and r["lapsed"])
check("and how overdue it is, is reported", r and r["days_overdue"] > 200,
      r and r["days_overdue"])
r = find(series("ACTIVE CO", "2026-01-05", 30, 8, 12.0), "ACTIVE", asof="2026-08-30")
check("one still billing is not flagged", r and not r["lapsed"])

# -------------------------------------------------------- merchant keys ----
# Card numbers and reference ids change on every charge; over-normalising the
# other way merges merchants that are not the same, which invents subscriptions.
check("a card number does not split one merchant into many",
      recurring.merchant_key("SPOTIFY USA 877-7781161 CARD: 6503")
      == recurring.merchant_key("SPOTIFY USA 877-7781161 CARD: 9912"),
      recurring.merchant_key("SPOTIFY USA 877-7781161 CARD: 6503"))
check("the importer's own suffix is stripped",
      "ELECTRONIC" not in recurring.merchant_key("ATT*BILL PAYMENT — Electronic Debit"))
check("two different merchants stay different",
      recurring.merchant_key("NETFLIX.COM") != recurring.merchant_key("SPOTIFY USA"))

# Two charges on one day are two purchases, not a zero-day interval.
same_day = ([{"txn_date": "2026-01-05", "amount": -9.99, "description": "DOUBLE CO",
              "category_kind": "expense"}] * 2
            + series("DOUBLE CO", "2026-02-05", 30, 4, 9.99))
r = find(same_day, "DOUBLE")
check("two charges on the same day do not break the cadence",
      r is not None and r["cadence"] == "monthly", r and r["cadence"])

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
