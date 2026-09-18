"""What is different about this month.

"Where does the money go" is answered by the category table. The question after
it is "and is that normal", which needs each category compared against its own
history rather than against a budget nobody set.

## The partial-month trap

The single easiest way to make this feature lie is to compare a month that is
half over against months that are complete. On the 10th, every category is
"down 65%" and none of it means anything. So the current month is never compared
— the newest COMPLETE month is — and if the caller asks about a month that has
not finished, it says so and compares the one before it instead.

The same trap in reverse catches the baseline: comparing one month against the
single month before it makes every ordinary fluctuation look like a trend. The
baseline here is the MEDIAN of the preceding months, which absorbs one unusual
month without being dragged by it.

## What counts as notable

Both a proportion and an absolute floor. A 90% rise on a category that went from
$2 to $4 is arithmetically dramatic and worth nothing, while $400 more on
groceries matters at any percentage. Requiring both keeps the list short enough
to read, which is the only thing that makes it useful.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date

# A change has to clear both bars to be worth showing.
MIN_DELTA = 75.0
MIN_SHARE = 0.35
MIN_HISTORY = 3          # months of baseline before any comparison is honest


def month_of(txn) -> str:
    return (txn.get("txn_date") or "")[:7]


def complete_months(classified, asof: str | None = None) -> list[str]:
    """Every month with data, excluding one that has not finished yet."""
    today = date.fromisoformat(asof[:10]) if asof else date.today()
    current = f"{today.year:04d}-{today.month:02d}"
    months = sorted({month_of(t) for t in classified if month_of(t)})
    return [m for m in months if m < current]


def by_category(classified, kind: str = "expense") -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in classified:
        if t.get("category_kind") != kind or not t.get("category"):
            continue
        month = month_of(t)
        if not month:
            continue
        # A charge is negative and a refund positive, so the signed sum is
        # what was actually spent. abs() counted a refund as more spending,
        # which put August 2026 "over typical" when it was under.
        out[t["category"]][month] += -float(t.get("amount") or 0.0)
    return {c: dict(m) for c, m in out.items()}


def changes(classified, asof: str | None = None, lookback: int = 6) -> dict:
    """How the newest complete month compares with the months before it."""
    months = complete_months(classified, asof)
    if len(months) < MIN_HISTORY + 1:
        return {"month": months[-1] if months else None, "baseline_months": 0,
                "rows": [], "notable": [],
                "note": "not enough finished months to compare against yet"}

    latest = months[-1]
    baseline = months[-(lookback + 1):-1]
    spend = by_category(classified)

    rows = []
    for category, per_month in spend.items():
        now = round(per_month.get(latest, 0.0), 2)
        history = [per_month.get(m, 0.0) for m in baseline]
        if len([h for h in history if h > 0]) < 2 and now == 0:
            continue
        typical = round(statistics.median(history), 2) if history else 0.0
        delta = round(now - typical, 2)
        share = (delta / typical) if typical else (1.0 if now else 0.0)
        rows.append({
            "category": category, "now": now, "typical": typical,
            "delta": delta, "share": round(share, 3),
            # Both bars, deliberately. A 90% rise from $2 to $4 is dramatic and
            # worth nothing; $400 more on groceries matters at any percentage.
            "notable": abs(delta) >= MIN_DELTA and abs(share) >= MIN_SHARE,
            "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
        })
    rows.sort(key=lambda r: -abs(r["delta"]))
    return {
        "month": latest,
        "baseline_months": len(baseline),
        "baseline_from": baseline[0] if baseline else None,
        "rows": rows,
        "notable": [r for r in rows if r["notable"]],
        "total_now": round(sum(r["now"] for r in rows), 2),
        # The typical MONTH, not the sum of typical categories: a sum of
        # per-category medians is lower than any real month, because no month
        # is median in every category at once, and read as "over typical".
        "total_typical": round(statistics.median([sum(per.get(m, 0.0) for per in spend.values()) for m in baseline]), 2) if baseline else 0.0,
    }


def drivers(classified, month: str, category: str, limit: int = 5) -> list[dict]:
    """The individual charges behind a category's month.

    A category that moved is not actionable on its own — "shopping is up $600"
    is only useful once you can see it was one purchase rather than sixty.
    """
    rows = [t for t in classified
            if month_of(t) == month and t.get("category") == category
            and float(t.get("amount") or 0.0) < 0]
    rows.sort(key=lambda t: float(t.get("amount") or 0.0))
    return [{"date": t.get("txn_date"), "amount": round(float(t["amount"]), 2),
             "description": t.get("description"), "account": t.get("account")}
            for t in rows[:limit]]


def unusual_charges(classified, month: str, multiple: float = 4.0,
                    floor: float = 150.0) -> list[dict]:
    """Single charges far larger than that category's usual one.

    Compared against the typical CHARGE rather than the typical month, because a
    category's monthly total moving is a different fact from one purchase in it
    being enormous, and the second is the one you can do something about.
    """
    per_category: dict[str, list[float]] = defaultdict(list)
    for t in classified:
        amount = float(t.get("amount") or 0.0)
        if amount < 0 and t.get("category_kind") == "expense" and t.get("category"):
            per_category[t["category"]].append(abs(amount))

    out = []
    for t in classified:
        amount = float(t.get("amount") or 0.0)
        if month_of(t) != month or amount >= 0 or t.get("category_kind") != "expense":
            continue
        history = per_category.get(t.get("category") or "", [])
        if len(history) < 5:
            continue
        typical = statistics.median(history)
        if abs(amount) >= max(floor, typical * multiple):
            out.append({"date": t.get("txn_date"), "amount": round(amount, 2),
                        "description": t.get("description"),
                        "category": t.get("category"),
                        "typical_for_category": round(typical, 2)})
    out.sort(key=lambda r: r["amount"])
    return out
