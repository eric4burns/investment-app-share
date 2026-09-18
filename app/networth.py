"""Everything you own, minus everything you owe, over time.

This is the number the whole app exists to produce and the one it could not
compute until now. Each half was there separately — a portfolio worth $365,072
on one tab, spending of $5,125 a month on another — and neither is net worth. It
needed three things at once, and the third only arrived with the card imports:

    investments   positions valued at market, plus uninvested cash in them
    bank cash     what is left in checking and savings after every flow
    card debt     what has been charged and not yet paid

A brokerage balance rising while a card balance rises faster is a portfolio
going up and a net worth going down, and until both sides were in one ledger
there was no way to see that.

## Card debt is a running balance, not a total

A credit card has no "balance" column in an export — it has charges and
payments, and the balance is what they add up to. So it is carried forward:
every purchase increases what is owed, every payment reduces it, and the balance
on any date is the running sum to that point. That also means the number is only
as good as the history behind it. A card whose export starts in the middle of
its life begins from an assumed zero, which UNDERSTATES the debt, so the first
date of each card's data is reported and the series is marked as partial before
it.

## Savings rate

Income minus spending, over income. Transfers are excluded from both — money
moved to a brokerage is saved, not spent, and counting it as spending is what
made the first cut of the budget tab report a negative savings rate for someone
who saves half their income.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import budget, cash, performance


def month_ends(start: str, end: str) -> list[str]:
    """The last day of each month in the range, plus the end date itself."""
    out = []
    day = date.fromisoformat(start[:10])
    last = date.fromisoformat(end[:10])
    cursor = date(day.year, day.month, 1)
    while cursor <= last:
        nxt = date(cursor.year + (cursor.month == 12),
                   1 if cursor.month == 12 else cursor.month + 1, 1)
        eom = nxt - timedelta(days=1)
        if day <= eom <= last:
            out.append(eom.isoformat())
        cursor = nxt
    if not out or out[-1] != last.isoformat():
        out.append(last.isoformat())
    return out


def card_balances(spending_txns, dates: list[str]) -> dict[str, float]:
    """What is owed on cards at each date, carried forward.

    Positive means money owed. A purchase adds to it, a payment reduces it —
    which is the sign of the stored amount reversed, since from the account's
    point of view a purchase is money out.
    """
    rows = sorted((t for t in spending_txns if t.get("account_kind") == "credit"),
                  key=lambda t: (t.get("txn_date") or ""))
    out, owed, i = {}, 0.0, 0
    for when in dates:
        while i < len(rows) and (rows[i].get("txn_date") or "")[:10] <= when:
            owed -= float(rows[i].get("amount") or 0.0)
            i += 1
        out[when] = round(owed, 2)
    return out


def bank_balances(spending_txns, dates: list[str], anchors: dict | None = None) -> dict[str, float]:
    """Cash in the bank accounts at each date, from ONE forward pass.

    This used to call cash.balances once per date, and each of those calls
    rebuilt a filtered copy of the whole transaction list and walked it from the
    beginning: O(dates x transactions). At month ends that was twenty-seven
    calls and nobody noticed. On a daily grid it is eight hundred, which took
    the whole /api/performance response past its three-second budget.

    The anchor makes this look harder than it is. An anchor says the balance was
    B on date A, and cash.balances rolls forward from it or backwards to it. Both
    directions are the same statement:

        balance(d) = B + (F(d) - F(A))

    where F is the cumulative flow up to a date. So one forward pass gives F at
    every requested date, and the anchor is a constant offset applied after --
    which is also why this cannot drift from cash.balances as long as both agree
    on what counts as a flow. Sweeps and non-cash valuation rows are excluded
    here for exactly that reason.
    """
    anchors = anchors or {}
    rows = sorted((t for t in spending_txns if t.get("account_kind") != "credit"),
                  key=lambda t: (t.get("txn_date") or ""))

    # F per account at each requested date, and F at each anchor date.
    running: dict[str, float] = {}
    at_date: dict[str, dict[str, float]] = {}
    anchor_days = {a["as_of"] for a in anchors.values()}
    f_at_anchor: dict[str, float] = {}
    marks = sorted(set(dates) | anchor_days)

    i = 0
    for when in marks:
        while i < len(rows) and (rows[i].get("txn_date") or "")[:10] <= when:
            t = rows[i]
            i += 1
            if t.get("kind") in cash.NON_CASH_KINDS or cash._is_sweep(t):
                continue
            acct = t.get("account") or "(unassigned)"
            running[acct] = running.get(acct, 0.0) + float(t.get("amount") or 0.0)
        snapshot = dict(running)
        if when in anchor_days:
            for acct, a in anchors.items():
                if a["as_of"] == when:
                    f_at_anchor[acct] = snapshot.get(acct, 0.0)
        at_date[when] = snapshot

    out = {}
    for when in dates:
        snap = at_date.get(when, {})
        accounts = set(snap) | set(anchors)
        total = 0.0
        for acct in accounts:
            f = snap.get(acct, 0.0)
            a = anchors.get(acct)
            total += (a["balance"] + f - f_at_anchor.get(acct, 0.0)) if a else f
        out[when] = round(total, 2)
    return out


def sample_dates(start: str, end: str, step_days: int = 1) -> list[str]:
    """The grid the net-worth curve is drawn on.

    Month ends are the natural reconciliation points and were the original
    grid, but they make a poor CHART: two years is twenty-six points, so the
    line is a coarse zigzag and any peak between two month ends is invisible.
    Every balance here is derived from transactions, so any date is as valid as
    any other. Daily costs about a second, which is worth paying: at month ends
    the curve peaked at $598,946, at weekly $598,946 again, and daily $636,634 —
    the last of which is the figure that agrees with the broker's own screen.
    A chart that disagrees with the account it describes is worse than a slow
    one. Weekends are kept here, unlike the portfolio curve, because bank and
    card balances do change over a weekend and nothing downstream annualises
    this grid.

    The end date is always included, so the last point is today rather than
    whenever the last whole week happened to fall.
    """
    out, cursor, last = [], date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    while cursor <= last:
        out.append(cursor.isoformat())
        cursor += timedelta(days=step_days)
    if not out or out[-1] != last.isoformat():
        out.append(last.isoformat())
    return out


def series(conn, start: str, end: str, anchors: dict | None = None) -> dict:
    """Net worth across the range, sampled daily."""
    dates = sample_dates(start, end)
    inv_txns = performance.load_transactions(conn, "1900-01-01", end, "all")
    valued = performance.values_at(conn, inv_txns, dates)

    spending = budget.load_spending(conn, None, end)
    spending = budget.classify(conn, spending)
    cards = card_balances(spending, dates)
    bank = bank_balances(spending, dates, anchors)

    # Before a card's first transaction its balance is assumed to be zero, which
    # understates what was owed. Saying where that assumption stops mattering is
    # more useful than quietly drawing a line through it.
    card_rows = [t for t in spending if t.get("account_kind") == "credit"]
    card_from = min((t["txn_date"][:10] for t in card_rows), default=None)

    # A bank account whose imported history does not reach back to when it was
    # funded derives a NEGATIVE balance, which is not a thing an account can
    # hold. It means the opening balance is missing, and every net worth figure
    # here is short by at least that much. Saying so is the difference between a
    # number that is low and a number that is wrong.
    latest_balances = cash.balances(
        [t for t in spending if t.get("account_kind") != "credit"],
        asof=end, anchor_map=anchors or {})
    understated = sorted(
        [{"account": name, "short_by": round(-row["balance"], 2)}
         for name, row in latest_balances.items() if row["impossible"]],
        key=lambda r: -r["short_by"])

    points = []
    for when in dates:
        investments = round(valued.get(when, (0.0, []))[0], 2)
        points.append({
            "date": when,
            "investments": investments,
            "cash": bank.get(when, 0.0),
            "debt": cards.get(when, 0.0),
            "net": round(investments + bank.get(when, 0.0) - cards.get(when, 0.0), 2),
            "partial": bool(card_from and when < card_from),
        })

    first, last = (points[0] if points else None), (points[-1] if points else None)
    return {
        "points": points,
        "latest": last,
        "change": (round(last["net"] - first["net"], 2)
                   if first and last and len(points) > 1 else None),
        "card_history_from": card_from,
        # Not a warning about precision — a statement that the true figure is
        # higher than the one shown, by at least this much.
        "understated_by": round(sum(r["short_by"] for r in understated), 2),
        "understated_accounts": understated,
        "start": start, "end": end,
    }


def savings_rate(classified, start: str | None = None, end: str | None = None) -> dict:
    """What share of what came in did not go back out.

    Transfers and investment moves are excluded from BOTH sides. Money sent to a
    brokerage is saved, not spent — counting it as spending is what makes an app
    tell someone who saves half their income that they are living beyond their
    means.
    """
    income = spend = 0.0
    for t in classified:
        day = (t.get("txn_date") or "")[:10]
        if start and day < start:
            continue
        if end and day > end:
            continue
        amount = float(t.get("amount") or 0.0)
        kind = t.get("category_kind")
        if kind == "income":
            income += amount
        elif kind == "expense":
            spend += abs(amount)
    saved = income - spend
    return {
        "income": round(income, 2),
        "spending": round(spend, 2),
        "saved": round(saved, 2),
        "rate": round(saved / income, 4) if income > 0 else None,
    }
