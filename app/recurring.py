"""What charges you again and again.

This is the one question a bank statement is uniquely bad at answering and that
a combined ledger is uniquely good at. A subscription is invisible in a list of
transactions — it looks exactly like any other $12.99 — and it only becomes
visible when you line up every charge from the same merchant and notice the gap
between them is always the same.

Three things worth money come out of that:

  * What you are actually subscribed to, and what it costs a YEAR rather than a
    month, which is the number people are wrong about.
  * What has gone UP. A price rise on a recurring charge is designed not to be
    noticed; it arrives as one slightly larger number among hundreds.
  * What is still billing you. A charge that has kept its cadence for a year and
    belongs to something you stopped using is the most expensive kind of
    forgotten, and nothing else in this app would surface it.

## Two different things, and only one of them is cancellable

The first attempt at this called a weekly grocery run a subscription. It was not
wrong about the cadence — 26 H-E-B trips really were about seven days apart —
but "$8,126 a year, weekly" is not a thing anyone can cancel, and burying three
real subscriptions under a list of shopping habits makes the feature useless.

So the amounts decide which is which:

  * A SUBSCRIPTION bills the same amount on a schedule. Netflix is $9.99 every
    month. The variation between charges is nearly nothing, and that is what
    makes it cancellable — you are paying for access, not for goods.
  * A HABIT is regular in time and irregular in amount. Groceries every Saturday,
    petrol every ten days. Worth seeing, because it is where the money goes,
    but there is no button to press.

Both are reported, separately and with different language. Only subscriptions
get an annual projection, because projecting a year of groceries from four
trips produces a number ($81,536, in one real case here) that is worse than
useless.

Transfers never count. A credit-card payment is as regular as any subscription
and is not spending at all — it was the single largest source of nonsense in the
first version, which confidently reported a monthly Robinhood deposit as a
recurring charge that had gone up in price.

Cadence is still measured on gaps rather than amounts, which is what lets a
subscription survive the month its price changes — a fixed-amount rule would
drop it exactly when you most want to know.

Three charges minimum. Two of anything have exactly one interval between them,
and one interval is not a pattern — with a two-charge rule every pair of
purchases at the same shop becomes a subscription.

The interval is taken as the MEDIAN, not the mean. A single skipped month, or
one charge landing a few days late, drags a mean far enough to break the match
while leaving the median untouched.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import date, timedelta

# (label, days, tolerance). Tolerance widens with the period: a monthly bill
# lands anywhere in a five-day window because months are unequal and weekends
# push payments around, while a weekly one is far tighter.
CADENCES = [
    ("weekly",    7,   2),
    ("biweekly",  14,  3),
    ("monthly",   30,  5),
    ("bimonthly", 61,  8),
    ("quarterly", 91,  12),
    ("semiannual", 182, 20),
    ("annual",    365, 30),
]

PER_YEAR = {"weekly": 52.0, "biweekly": 26.0, "monthly": 12.0, "bimonthly": 6.0,
            "quarterly": 4.0, "semiannual": 2.0, "annual": 1.0}

MIN_CHARGES = 3

# How much the amount is allowed to wander before it stops being a subscription
# and becomes a habit, as a fraction of the typical charge. Netflix at $9.99
# every month sits near zero; a grocery run swinging between $40 and $260 is far
# above it. Set from this ledger: real subscriptions here land under 0.08 and
# real shopping over 0.30, so the boundary is not delicate.
AMOUNT_DRIFT = 0.15

# Categories whose charges are bills whatever the amount does. Car insurance
# went 993 → 960 → 1,110 → 1,380 across four half-years and was filed as a
# "habit" beside the groceries because its spread was over the drift line —
# which is the one recurring charge the user most wanted to see rise.
BILL_CATEGORIES = {"Subscriptions", "Insurance", "Utilities", "Rent"}
# A charge on a long cadence whose amount moves by less than this between one
# bill and the next is a bill repricing, not shopping: nobody buys groceries
# twice a year at a stable merchant.
BILL_STEP = 0.40

# Trailing noise that makes every charge from one merchant look like a different
# merchant: card numbers, reference ids, store numbers, city and state.
_NOISE = [
    re.compile(r"\s+—\s+.*$"),                       # the importer's own suffix
    re.compile(r"\b(CARD|ACCT|REF|ID)[:# ]\s*\S+", re.I),
    re.compile(r"[*#]\s*\d[\dA-Z]*", re.I),
    re.compile(r"\b[X*x]{3,}\d*\b"),
    re.compile(r"\b\d{4,}\b"),
    # an invoice or order token: four or more letters-and-digits with at least
    # one digit (CANVA I04288, NORTON 8N2K7Q) — it split one merchant into
    # twenty-two "subscriptions"
    re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{4,}\b", re.I),
    re.compile(r"\s+[A-Z]{2}$"),                     # trailing state code
]


# One name per brand. The same subscription reaches the ledger under several
# descriptors — NETFLIX COM and NETFLIX INC, HULU and HLU HULUPLUS, three
# spellings of Google One, three of Fireflies — and each spelling came out as
# its own "subscription" with too few charges to measure, so the list the user
# opened to see what bills them was twice as long as the truth and said
# "likely" about things that had billed twenty times. Only names that are one
# product are merged; PROG COUNTY MUT INS (the car) and ASI / PROGRESSIVE (the
# home policy) are the same company and two bills, so they stay apart.
BRANDS = [
    (r"\bNETFLIX\b", "NETFLIX"), (r"\bHULU|HLU HULUPLUS", "HULU"), (r"\bDISNEY", "DISNEY PLUS"),
    (r"\bSPOTIFY", "SPOTIFY"), (r"\bFIREFLIES", "FIREFLIES AI"), (r"\bGOOGLE ONE|GOOGLE GOOGLE ONE", "GOOGLE ONE"),
    (r"\bAPPLE COM BILL", "APPLE"), (r"\bIPSY", "IPSY"), (r"\bANTHROPIC|CLAUDE AI|CLAUDE SUB", "CLAUDE (ANTHROPIC)"),
    (r"\bOPENAI|CHATGPT", "CHATGPT (OPENAI)"), (r"\bZOOM\b", "ZOOM"), (r"\bCANVA\b", "CANVA"),
    (r"\bADOBE\b", "ADOBE"), (r"\bNORTON\b", "NORTON"), (r"\bATT\b|AT&T", "AT&T"),
    (r"PROG COUNTY MUT INS", "PROGRESSIVE (AUTO INSURANCE)"), (r"\bASI\b.*PROGRESSIVE", "ASI / PROGRESSIVE (PROPERTY INSURANCE)"),
    (r"\bNTTA\b", "NTTA TOLLS"), (r"\bPRIME VIDEO", "PRIME VIDEO"), (r"\bATHLEAN", "ATHLEAN-X"),
]
_BRANDS = [(re.compile(rx), name) for rx, name in BRANDS]


def merchant_key(description: str) -> str:
    """A stable name for a merchant across its charges.

    Deliberately conservative. Over-normalising merges merchants that are not
    the same and invents subscriptions that do not exist, which is a worse
    failure than missing one: a missed subscription costs nothing, a fabricated
    one sends you cancelling something you need. BRANDS is the one exception,
    and it is a list of names, not a rule.
    """
    text = (description or "").upper()
    for pattern in _NOISE:
        text = pattern.sub(" ", text)
    text = re.sub(r"[^A-Z0-9&' ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for rx, name in _BRANDS:
        if rx.search(text):
            return name
    return text[:24].strip()


def _classify(intervals: list[float]) -> tuple[str, float] | None:
    median = statistics.median(intervals)
    for label, days, tolerance in CADENCES:
        if abs(median - days) <= tolerance:
            # The median matching is not enough on its own — a merchant charged
            # at 5 and 55 days has a median near 30 and no cadence at all. Most
            # of the individual gaps have to fit too.
            close = sum(1 for i in intervals if abs(i - days) <= tolerance * 2.5)
            # One interval is one interval: Norton billed on the same day two
            # years running could never pass a "two of them must fit" rule
            # and read as irregular.
            if close >= max(min(2, len(intervals)), int(len(intervals) * 0.6)):
                return label, median
    return None


def detect(txns, asof: str | None = None, min_charges: int = MIN_CHARGES) -> list[dict]:
    """Every merchant that charges on a regular cadence."""
    asof_date = date.fromisoformat(asof) if asof else date.today()
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        amount = float(t.get("amount") or 0.0)
        if amount >= 0:
            continue                       # money coming in is not a subscription
        # Moving your own money is regular by nature and is not a charge. Card
        # payments, brokerage deposits and transfers to savings all keep perfect
        # cadence and all of them are noise here.
        if t.get("category_kind") in ("transfer", "investment"):
            continue
        key = merchant_key(t.get("description"))
        if len(key) < 4:
            continue
        groups[key].append(t)

    out = []
    for key, rows in groups.items():
        rows.sort(key=lambda r: r.get("txn_date") or "")
        # One charge per day at most: a merchant billed twice in a day is two
        # purchases, and counting both makes the gap zero and breaks the cadence.
        seen_days, unique = set(), []
        for r in rows:
            day = (r.get("txn_date") or "")[:10]
            if day and day not in seen_days:
                seen_days.add(day)
                unique.append(r)
        if len(unique) < min_charges:
            # A subscription billed once a year cannot show a cadence inside a
            # year of statements, and a new one has been billed once. The
            # budget rules already say what these merchants are — Norton and
            # the Claude plan land in the Subscriptions category on one charge
            # — so a charge in that category is reported as a subscription
            # with the cadence marked as assumed, rather than left out of the
            # list the user opens to find exactly this.
            if unique and all((r.get("category") or "") in BILL_CATEGORIES for r in unique):
                out.append(_assumed_subscription(key, unique, asof_date))
            continue

        days = [date.fromisoformat((r["txn_date"])[:10]) for r in unique]
        intervals = [(b - a).days for a, b in zip(days, days[1:])]
        if not intervals or min(intervals) <= 0:
            continue
        hit = _classify([float(i) for i in intervals])
        if not hit:
            continue
        cadence, median = hit

        amounts = [abs(float(r.get("amount") or 0.0)) for r in unique]
        typical = round(statistics.median(amounts), 2)
        drift = (statistics.pstdev(amounts) / typical) if typical else 1.0
        kind = "subscription" if drift <= AMOUNT_DRIFT else "habit"
        # A merchant the budget rules file under a bill category is one,
        # whatever its amount did: Google One went from $3.19 to $10.65 and was
        # being reported as a shopping habit because the price rose. So is a
        # long-cadence charge whose steps are bounded (the insurance premium).
        steps = [abs(b - a) / a for a, b in zip(amounts, amounts[1:]) if a]
        if kind == "habit" and (all((r.get("category") or "") in BILL_CATEGORIES for r in unique)
                                or (PER_YEAR[cadence] <= 6 and steps and max(steps) <= BILL_STEP)):
            kind = "subscription"
        last_day = days[-1]
        # Overdue by more than half a period: either it was cancelled, or it is
        # about to arrive. Said as "not seen since" rather than "cancelled",
        # because the ledger cannot tell those apart.
        overdue = (asof_date - last_day).days - median
        lapsed = overdue > median * 0.5

        # A price rise hides as one slightly larger number among hundreds. The
        # comparison is first-half against last-half rather than first against
        # last, so a single odd charge does not read as a rise.
        half = max(1, len(amounts) // 2)
        early = statistics.median(amounts[:half])
        late = statistics.median(amounts[-half:])
        changed = round(late - early, 2) if abs(late - early) >= 0.01 else 0.0

        out.append({
            "merchant": key,
            "description": unique[-1].get("description"),
            "account": unique[-1].get("account"),
            "category": unique[-1].get("category"),
            "cadence": cadence,
            "interval_days": round(median, 1),
            "charges": len(unique),
            "typical": typical,
            "first": days[0].isoformat(),
            "last": last_day.isoformat(),
            "next_expected": (last_day + timedelta(days=round(median))).isoformat(),
            "kind": kind,
            "drift": round(drift, 3),
            # Only a fixed charge gets projected forward. Multiplying four
            # grocery trips into a year is how the first version produced
            # $81,536 of "annual subscription" from a handful of transfers.
            "annual": (round(typical * PER_YEAR[cadence], 2)
                       if kind == "subscription" else None),
            "total_paid": round(sum(amounts), 2),
            "price_change": changed,
            "price_change_pct": (round(changed / early * 100, 1)
                                 if early and changed else 0.0),
            "lapsed": lapsed,
            "days_overdue": max(0, round(overdue)),
            # The price over time, as the steps it took: each distinct amount
            # with the day it started, so "$993.50 → $960.50 → $1,109.50 →
            # $1,379.50" is read off the row rather than hunted for.
            "history": price_steps(unique) if kind == "subscription" else [],
        })

    out.sort(key=lambda r: -(r["annual"] or r["total_paid"]))
    return out


def price_steps(unique: list[dict], tolerance: float = 0.01) -> list[dict]:
    """Each distinct price and the day it first billed, in order.

    A one-cent wobble (tax rounding) is not a step; a change of more than a
    per cent is. Returns [{"from": day, "amount": x, "charges": n}].
    """
    steps: list[dict] = []
    for r in unique:
        amt = round(abs(float(r.get("amount") or 0.0)), 2)
        if steps and abs(amt - steps[-1]["amount"]) <= max(0.05, steps[-1]["amount"] * tolerance):
            steps[-1]["charges"] += 1
            continue
        steps.append({"from": (r.get("txn_date") or "")[:10], "amount": amt, "charges": 1})
    return steps


def _assumed_subscription(key: str, unique: list[dict], asof_date: date) -> dict:
    """A Subscriptions-category merchant with too few charges to measure a cadence.

    One charge is reported as annual (assumed); two about a year apart as
    annual; anything else as unknown. `assumed` is set so the display can say
    the cadence is inferred from the category, not observed."""
    days = [date.fromisoformat((r["txn_date"])[:10]) for r in unique]
    amounts = [abs(float(r.get("amount") or 0.0)) for r in unique]
    typical = round(statistics.median(amounts), 2)
    cadence, median = "annual", 365.0
    if len(days) >= 2:
        gap = (days[-1] - days[0]).days / (len(days) - 1)
        hit = _classify([float(gap)])
        # A renewal that moved a month — the home policy billed in July one
        # year and August the next — is still an annual bill.
        if not hit and 300 <= gap <= 430:
            hit = ("annual", 365.0)
        cadence, median = hit if hit else ("irregular", gap)
    per_year = PER_YEAR.get(cadence)
    last_day = days[-1]
    overdue = (asof_date - last_day).days - median
    return {
        "merchant": key,
        "description": unique[-1].get("description"),
        "account": unique[-1].get("account"),
        "category": unique[-1].get("category"),
        "cadence": cadence,
        "interval_days": round(median, 1),
        "charges": len(unique),
        "typical": typical,
        "first": days[0].isoformat(),
        "last": last_day.isoformat(),
        "next_expected": (last_day + timedelta(days=round(median))).isoformat(),
        "kind": "subscription",
        "drift": 0.0,
        "annual": round(typical * per_year, 2) if per_year else None,
        "total_paid": round(sum(amounts), 2),
        "price_change": 0.0,
        "price_change_pct": 0.0,
        "lapsed": overdue > median * 0.5,
        "days_overdue": max(0, round(overdue)),
        "assumed": True,
        "history": price_steps(unique),
    }


def confidence(r: dict) -> str:
    """How sure the detection is. "sure" has billed three or more times on a
    measured cadence and is current; "likely" is current but on one or two
    charges (cadence assumed); "quiet" has stopped billing."""
    if r.get("lapsed"):
        return "quiet"
    if r.get("assumed") or (r.get("charges") or 0) < 3:
        return "likely"
    return "sure"


def _risen(r: dict) -> bool:
    """Billing more now than at first, by the price steps rather than the two
    medians — the medians put Claude's "was" at −$74 once a $213 charge landed
    among the $21 ones, and insurance at a "was" nobody ever paid. A rise is
    the latest price above the first, on a current charge, by more than a
    per cent."""
    h = settled_steps(r)
    if len(h) < 2 or r.get("lapsed") or r.get("cadence") not in PER_YEAR:
        return False
    return h[-1]["amount"] > h[0]["amount"] * 1.01


def settled_steps(r: dict) -> list[dict]:
    """The price steps that billed at least twice. A half-month of rent, a
    doubled payment, one $213 charge among the $21 ones: each is a real
    charge and belongs in the row's history, but none is a PRICE until it
    repeats, so the rise table waits for the second one."""
    # A bill on a long cadence prices each term once by nature — the
    # insurance premium is four steps of one charge each, and all four are
    # real prices.
    if PER_YEAR.get(r.get("cadence"), 12) <= 4:
        return list(r.get("history") or [])
    h = [x for x in (r.get("history") or []) if x["charges"] >= 2]
    return h if h else (r.get("history") or [])[:1]


def summary(found: list[dict], hidden: set | None = None) -> dict:
    hidden = hidden or set()
    subs_all = [dict(r, confidence=confidence(r)) for r in found if r["kind"] == "subscription"]
    # A hidden merchant leaves the list (the user has said it does not
    # belong) and sits under a fold with an undo, rather than staying in the
    # table it was hidden from.
    subs = [r for r in subs_all if r["merchant"] not in hidden]
    hidden_rows = [r for r in subs_all if r["merchant"] in hidden]
    order = {"sure": 0, "likely": 1, "quiet": 2}
    subs.sort(key=lambda r: (order[r["confidence"]], -(r.get("annual") or 0), r["merchant"]))
    habits = [r for r in found if r["kind"] == "habit"]
    live = [r for r in subs if not r["lapsed"]]
    return {
        "subscriptions": subs,
        "hidden": hidden_rows,
        "habits": habits,
        "count": len(subs),
        "live_count": len(live),
        "annual_total": round(sum(r["annual"] or 0 for r in live), 2),
        "monthly_total": round(sum(r["annual"] or 0 for r in live) / 12, 2),
        # A rise on something you pay every month compounds quietly; the annual
        # cost of the increase alone is the number worth seeing.
        "risen": sorted(
            [dict(r, was=settled_steps(r)[0]["amount"], now=settled_steps(r)[-1]["amount"],
                  was_from=settled_steps(r)[0]["from"], now_from=settled_steps(r)[-1]["from"],
                  annual_increase=round((settled_steps(r)[-1]["amount"] - settled_steps(r)[0]["amount"]) * PER_YEAR.get(r["cadence"], 0), 2))
             for r in subs if _risen(r)],
            key=lambda r: -r["annual_increase"]),
        # Dismissed merchants stay out of "gone quiet" but remain in the
        # subscription list itself — the point is to stop re-reporting a
        # question already answered, not to forget the charge existed.
        "lapsed": [r for r in subs if r["lapsed"]],
        "dismissed": sorted(hidden),
    }


# --------------------------------------------------------- dismissing ----
# "Gone quiet" is a list of things that billed on a cadence and then stopped:
# a cancelled subscription, a card that was replaced, a free trial that ended.
# Each one is worth checking once and then never seeing again. Without a way to
# dismiss them the panel only grows, and a list that only grows stops being read
# — which defeats the point of noticing a $29/month charge that quietly resumed.
DISMISS_SCHEMA = """
CREATE TABLE IF NOT EXISTS recurring_dismissed (
    merchant    TEXT PRIMARY KEY,
    dismissed_at TEXT NOT NULL DEFAULT (datetime('now')),
    note        TEXT
);
"""


def ensure_dismiss_schema(conn) -> None:
    conn.executescript(DISMISS_SCHEMA)


def dismissed(conn) -> set:
    ensure_dismiss_schema(conn)
    return {r[0] for r in conn.execute("SELECT merchant FROM recurring_dismissed")}


def dismiss(conn, merchant: str, note: str | None = None) -> dict:
    """Stop reporting one merchant as gone quiet."""
    merchant = (merchant or "").strip()
    if not merchant:
        raise ValueError("a merchant is required")
    ensure_dismiss_schema(conn)
    conn.execute("INSERT OR REPLACE INTO recurring_dismissed (merchant, note) VALUES (?,?)",
                 (merchant, note))
    conn.commit()
    return {"merchant": merchant, "dismissed": True}


def undismiss(conn, merchant: str) -> dict:
    ensure_dismiss_schema(conn)
    cur = conn.execute("DELETE FROM recurring_dismissed WHERE merchant = ?",
                       ((merchant or "").strip(),))
    conn.commit()
    return {"merchant": merchant, "restored": bool(cur.rowcount)}
