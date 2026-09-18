"""Bracket and contribution-limit arithmetic, from what the ledger can see.

This is arithmetic, not tax advice, and the distinction is not a disclaimer —
it changes what the numbers mean. A ledger sees deposits. It does not see
taxable income, and the gap between the two is large and specific:

  * Payroll deposits are NET of tax and pre-tax deferrals, so gross wages are
    higher than what lands in the bank. Wages are read from the 401(k) plan's
    own contribution records where they exist, and otherwise flagged as a floor.
  * Business receipts are revenue, not profit. Deductible expenses come off
    before any of it is taxable, and this app cannot know which expenses those
    were.
  * MAGI is not gross income, and it is MAGI that the Roth phase-out is measured
    against.

So every figure here is a floor or an estimate, is labelled as which, and says
what it excluded. A number that looks authoritative and is quietly wrong about
someone's tax bracket is worse than no number.

Figures are for tax year 2026, from the IRS's own announcement — Rev. Proc.
2025-32 and Notice 2025-67. They are inflation-adjusted every year, so the year
is part of the data rather than assumed, and an unknown year refuses rather than
silently applying the wrong table.
"""
from __future__ import annotations

FILING_STATUSES = ("single", "married_jointly", "head_of_household")

# (rate, upper bound of the band). The last band has no upper bound.
BRACKETS = {
    2026: {
        "single": [(0.10, 12_400), (0.12, 50_400), (0.22, 105_700),
                   (0.24, 201_775), (0.32, 256_225), (0.35, 640_600),
                   (0.37, None)],
        "married_jointly": [(0.10, 24_800), (0.12, 100_800), (0.22, 211_400),
                            (0.24, 403_550), (0.32, 512_450), (0.35, 768_700),
                            (0.37, None)],
        # Head of household shares the top two thresholds with single filers.
        "head_of_household": [(0.10, 17_700), (0.12, 67_450), (0.22, 105_700),
                              (0.24, 201_775), (0.32, 256_225), (0.35, 640_600),
                              (0.37, None)],
    },
}

STANDARD_DEDUCTION = {
    2026: {"single": 16_100, "married_jointly": 32_200, "head_of_household": 24_150},
}

# Notice 2025-67.
# HSA contribution limits, employer and employee together (Rev. Proc. 2025-19).
HSA = {2026: {"self": 4_400, "family": 8_750}}

RETIREMENT = {
    2026: {
        "ira_limit": 7_500,
        "ira_catch_up": 1_100,          # age 50+
        "deferral_401k": 24_500,
        "roth_phase_out": {
            "single": (153_000, 168_000),
            "head_of_household": (153_000, 168_000),
            "married_jointly": (242_000, 252_000),
        },
    },
}

# Long-term capital gains: (rate, upper bound of TAXABLE income for that rate),
# Rev. Proc. 2025-32. The gain stacks on top of ordinary income, so the rate
# it pays depends on where the wages already put you — which is why it is a
# function of both figures below and not a flat percentage.
LTCG = {
    2026: {
        "single": [(0.0, 49_450), (0.15, 545_500), (0.20, None)],
        "married_jointly": [(0.0, 98_900), (0.15, 613_700), (0.20, None)],
        "head_of_household": [(0.0, 66_200), (0.15, 579_600), (0.20, None)],
    },
}

# A net capital loss offsets at most this much ordinary income in a year; the
# rest carries forward. §1211(b).
CAPITAL_LOSS_LIMIT = 3_000

SUPPORTED_YEARS = sorted(BRACKETS)


def _table(year: int, status: str):
    if year not in BRACKETS:
        raise ValueError(f"no bracket table for {year}; have {SUPPORTED_YEARS}")
    if status not in FILING_STATUSES:
        raise ValueError(f"unknown filing status {status!r}")
    return BRACKETS[year][status]


def bracket(taxable: float, year: int, status: str) -> dict:
    """Which band this lands in, and how much room is left in it."""
    bands = _table(year, status)
    floor = 0.0
    for rate, ceiling in bands:
        if ceiling is None or taxable <= ceiling:
            return {"rate": rate, "floor": floor, "ceiling": ceiling,
                    "room": None if ceiling is None else round(ceiling - taxable, 2),
                    "next_rate": _next_rate(bands, rate)}
        floor = ceiling
    return {"rate": bands[-1][0], "floor": floor, "ceiling": None, "room": None,
            "next_rate": None}


def _next_rate(bands, rate):
    for i, (r, _c) in enumerate(bands):
        if r == rate and i + 1 < len(bands):
            return bands[i + 1][0]
    return None


def tax_owed(taxable: float, year: int, status: str) -> float:
    """Total federal income tax at these brackets.

    Included because "what bracket am I in" is much less useful than people
    expect: only the dollars above the threshold are taxed at the higher rate,
    so crossing a bracket never costs more than it earns. Showing the actual
    total alongside the marginal rate is what keeps that from being confusing.
    """
    bands = _table(year, status)
    owed, floor = 0.0, 0.0
    for rate, ceiling in bands:
        if taxable <= floor:
            break
        top = taxable if ceiling is None else min(taxable, ceiling)
        owed += (top - floor) * rate
        floor = ceiling if ceiling is not None else top
        if ceiling is None:
            break
    return round(owed, 2)


def ltcg_tax(ordinary_taxable: float, gain: float, year: int, status: str) -> float:
    """Tax on a long-term gain stacked on top of ordinary taxable income.

    The 0% band is filled by wages first: a $10,000 gain on $45,000 of wages
    pays nothing in 2026 as a single filer, and the same gain on $120,000 pays
    15% on all of it. Ordinary income never pays the LTCG rate and the gain
    never pays the ordinary one, so the two are computed apart and added.
    """
    if gain <= 0:
        return 0.0
    owed, floor = 0.0, max(0.0, ordinary_taxable)
    top_of_gain = floor + gain
    for rate, ceiling in LTCG[year][status]:
        if ceiling is not None and ceiling <= floor:
            continue
        top = top_of_gain if ceiling is None else min(top_of_gain, ceiling)
        if top > floor:
            owed += (top - floor) * rate
            floor = top
        if floor >= top_of_gain:
            break
    return round(owed, 2)


def investment_income(txns: list[dict], year: int) -> dict:
    """What the TAXABLE brokerage account did this year, as the return sees it.

    Only accounts whose tax_status is 'taxable' count: a sale inside a Roth or
    the 401(k) is not a taxable event, and the HSA's are not either. Realised
    gains are FIFO-matched lots (`holdings.closed_trades`), split at a year
    held — the broker chooses lots per sale, so this is an estimate of what
    the 1099-B will say, not the figure itself. Dividends and interest are the
    cash the account was paid, money-market dividends included, all treated
    as ordinary (the ledger does not know which dividends were qualified, and
    calling them all ordinary errs on the side of the higher figure).

    The netting follows the return: short against long, and a net loss offsets
    at most CAPITAL_LOSS_LIMIT of ordinary income.
    """
    from . import holdings, washsales
    # Reverse-split legs restated first, or a 1-for-20 reads as a $10k loss.
    taxable = holdings.apply_reorganisations([t for t in txns if (t.get("tax_status") or "") == "taxable"])
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    trades = holdings.closed_trades(taxable, y0, y1)
    short = round(sum(t["pnl"] for t in trades if t["held_days"] <= 365), 2)
    long_ = round(sum(t["pnl"] for t in trades if t["held_days"] > 365), 2)
    # A loss the wash-sale rule disallows does not reduce this year's gain; it
    # moves into the replacement shares' basis, which the FIFO here cannot see.
    # Added back to the short-term figure (the ledger's wash sales are all
    # inside a year), so the floor does not count a loss the return refuses.
    disallowed = round(sum(w["disallowed"] for w in washsales.past(taxable)
                           if y0 <= (w.get("date") or "") <= y1), 2)
    short = round(short + abs(disallowed), 2)
    dividends = round(sum(float(t.get("amount") or 0.0) for t in taxable
                          if t.get("kind") == "dividend" and str(t.get("txn_date") or "").startswith(str(year))), 2)
    interest = round(sum(float(t.get("amount") or 0.0) for t in taxable
                         if t.get("kind") == "interest" and str(t.get("txn_date") or "").startswith(str(year))), 2)
    net = round(short + long_, 2)
    if net < 0:
        ordinary_gain, long_gain = max(net, -float(CAPITAL_LOSS_LIMIT)), 0.0
        carry = round(min(0.0, net + CAPITAL_LOSS_LIMIT), 2)
    elif short < 0:
        ordinary_gain, long_gain, carry = 0.0, net, 0.0       # the long gain absorbs the short loss
    elif long_ < 0:
        ordinary_gain, long_gain, carry = net, 0.0, 0.0       # the short gain absorbs the long loss
    else:
        ordinary_gain, long_gain, carry = short, long_, 0.0
    by_symbol: dict[str, float] = {}
    for t in trades:
        by_symbol[t["symbol"]] = round(by_symbol.get(t["symbol"], 0.0) + t["pnl"], 2)
    biggest = sorted(by_symbol.items(), key=lambda kv: -abs(kv[1]))[:5]
    return {"short_term": short, "long_term": long_, "net_gain": net,
            "dividends": dividends, "interest": interest,
            "ordinary_addition": round(ordinary_gain + dividends + interest, 2),
            "long_term_taxed": round(long_gain, 2), "loss_carried": carry,
            "wash_disallowed": abs(disallowed),
            "trades": len(trades), "last_sale": max((t["exit_date"] for t in trades), default=None),
            "biggest": [{"symbol": k, "pnl": v} for k, v in biggest]}


def roth_allowance(magi: float, year: int, status: str, age: int | None = None) -> dict:
    """How much can still go into a Roth IRA at this income.

    The phase-out is a range, not a cliff: the allowance shrinks linearly across
    it and reaches zero at the top. Treating it as a cliff is the common mistake
    and it is wrong in the direction that costs you a contribution.
    """
    plan = RETIREMENT[year]
    limit = plan["ira_limit"] + (plan["ira_catch_up"] if (age or 0) >= 50 else 0)
    low, high = plan["roth_phase_out"][status]
    if magi <= low:
        allowed, state = limit, "full"
    elif magi >= high:
        allowed, state = 0.0, "ineligible"
    else:
        # Reduced proportionally across the range, then rounded to the nearest
        # $10 and floored at $200, which is how the IRS states the rounding.
        share = (high - magi) / (high - low)
        allowed = max(200.0, round(limit * share / 10) * 10)
        state = "partial"
    return {"limit": limit, "allowed": round(allowed, 2), "state": state,
            "phase_out": [low, high], "magi": round(magi, 2),
            "headroom_to_phase_out": round(low - magi, 2)}


def contributions(txns, year: int) -> dict:
    """Retirement contributions the ledger has actually recorded, by account."""
    out: dict[str, float] = {}
    for t in txns:
        if t.get("kind") != "contribution":
            continue
        if not str(t.get("txn_date") or "").startswith(str(year)):
            continue
        out[t.get("account") or "(unknown)"] = round(
            out.get(t.get("account") or "(unknown)", 0.0) + float(t.get("amount") or 0.0), 2)
    return out


# --- projecting the year, and what it runs into ---------------------------

def project_year(ytd: float, asof: str, year: int) -> dict:
    """Annualise income earned so far.

    Straight-line: what has been received divided by the share of the year that
    has passed. That is the right shape for salary and the wrong shape for a
    bonus, a commission year or a business with a season, so the projection
    names its own method rather than presenting a number as a forecast.
    """
    from datetime import date
    a = date.fromisoformat(asof)
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    if a <= start:
        return {"projected": None, "elapsed": 0.0, "method": "not started"}
    a = min(a, end)
    elapsed = (a - start).days / (end - start).days
    return {
        "projected": round(ytd / elapsed, 2) if elapsed > 0 else None,
        "ytd": round(ytd, 2), "elapsed": round(elapsed, 4),
        "asof": asof,
        "method": (f"{ytd:,.0f} received in the first {elapsed * 100:.0f}% of "
                   f"{year}, extended straight-line to the full year"),
    }


def project_forward(ytd: float, asof: str, year: int,
                    base_annual: float | None = None,
                    other_annual: float = 0.0) -> dict:
    """What has actually been received, plus base pay for the rest of the year.

    This replaces straight-line extrapolation for anyone whose income is lumpy,
    which is most people. Annualising the year so far multiplies overtime, a
    bonus or a one-off contract month across every month still to come — income
    that has already happened and will not happen again.

    So the year is two halves that are computed differently: what has been
    received is a FACT and is used as-is, and what is still to come is a RATE.
    Overtime belongs only in the first half.

    `base_annual` is base salary before overtime — the pay stub's own annual
    rate, not a figure inferred from deposits. `other_annual` is anything else
    expected at a steady rate for the remainder, such as a second W2 income.
    Passing neither falls back to straight-line, which is stated in `method` so
    a weaker projection never passes for a stronger one.
    """
    from datetime import date
    a = date.fromisoformat(asof)
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    if a <= start:
        return {"projected": None, "method": "not started", "basis": "none"}
    a = min(a, end)
    total_days = (end - start).days
    elapsed = (a - start).days / total_days
    remaining = 1.0 - elapsed

    rate = (base_annual or 0.0) + (other_annual or 0.0)
    if rate <= 0:
        out = project_year(ytd, asof, year)
        out["basis"] = "extrapolated"
        return out

    to_come = rate * remaining
    return {
        "projected": round(ytd + to_come, 2),
        "ytd": round(ytd, 2), "to_come": round(to_come, 2),
        "elapsed": round(elapsed, 4), "asof": asof,
        "basis": "run_rate", "rate": round(rate, 2),
        "method": (f"{ytd:,.0f} actually received through {asof}, plus "
                   f"{to_come:,.0f} at a {rate:,.0f}/yr rate for the remaining "
                   f"{remaining * 100:.0f}% of {year}. Overtime already worked "
                   f"is in the first figure and is NOT projected forward."),
    }


def crossings(ytd: float, asof: str, year: int, status: str,
              age: int | None = None, base_annual: float | None = None,
              other_annual: float = 0.0) -> dict:
    """Will this year's income cross the Roth phase-out or the next bracket?

    ## The asymmetry that governs every sentence here

    The income figure this is built on is a FLOOR — a payroll deposit is net of
    tax and of deferrals, business receipts are revenue rather than profit, and
    none of it is MAGI. So the projection is a floor too, and that makes the two
    possible answers unequal:

        a floor that already crosses  ->  you WILL cross. Real income is at
                                          least this, so the crossing is certain.
        a floor that does not cross   ->  says NOTHING. The true figure is
                                          higher by an unknown amount and may
                                          cross anyway.

    Reporting "you are clear of the phase-out" from a floor would be the single
    most damaging thing this module could say, because it is the answer somebody
    would act on by contributing to a Roth they turn out to be ineligible for.
    So the clear case is phrased as "not on this figure, and this figure is a
    floor" rather than as reassurance.
    """
    proj = project_forward(ytd, asof, year, base_annual, other_annual)
    projected = proj["projected"]
    plan = RETIREMENT.get(year) or RETIREMENT[max(RETIREMENT)]
    lo, hi = plan["roth_phase_out"][status]
    out = {"projection": proj, "year": year, "status": status}

    if projected is None:
        out["roth"] = {"state": "unknown"}
        out["bracket"] = {"state": "unknown"}
        return out

    # ---- Roth ------------------------------------------------------------
    if projected >= hi:
        roth = {"state": "will_exceed", "over_by": round(projected - hi, 2),
                "message": (f"Projected income for the year is "
                            f"{projected:,.0f}, past the {hi:,.0f} where the Roth "
                            f"allowance ends. A direct Roth contribution this "
                            f"year is very likely to be disallowed, and this "
                            f"figure is a floor, so the real number is higher.")}
    elif projected >= lo:
        roth = {"state": "will_partial", "into_band": round(projected - lo, 2),
                "message": (f"Projected income for the year is "
                            f"{projected:,.0f}, inside the {lo:,.0f}–{hi:,.0f} "
                            f"phase-out band, so only part of a Roth "
                            f"contribution would be allowed. The figure is a "
                            f"floor, so it may land higher in the band or past "
                            f"it entirely.")}
    else:
        roth = {"state": "not_on_this_figure", "under_by": round(lo - projected, 2),
                "message": (f"Projected income for the year is "
                            f"{projected:,.0f}, {lo - projected:,.0f} short of "
                            f"the {lo:,.0f} phase-out. That is not a clearance: "
                            f"the figure is a FLOOR built from deposits, so the "
                            f"real total is higher by an unknown amount and may "
                            f"cross anyway.")}
    roth["phase_out"] = [lo, hi]
    roth["projected"] = projected
    out["roth"] = roth

    # ---- the next bracket -------------------------------------------------
    # Brackets apply to TAXABLE income, the Roth phase-out to MAGI. Comparing
    # the bracket against gross overstates it by the whole standard deduction —
    # 32,300 for a joint filer — which is enough to report a crossing that will
    # not happen. The two thresholds genuinely measure different figures, and
    # the app's own year-to-date bracket already subtracts the deduction.
    deduction = STANDARD_DEDUCTION.get(year, {}).get(status, 0)
    now = bracket(max(0.0, ytd - deduction), year, status)
    later = bracket(max(0.0, projected - deduction), year, status)
    crossed = later["rate"] > now["rate"]
    out["bracket"] = {
        "state": "will_cross" if crossed else "not_on_this_figure",
        "now_rate": now["rate"], "projected_rate": later["rate"],
        "ceiling": now["ceiling"], "projected": projected,
        "deduction": deduction,
        "projected_taxable": round(max(0.0, projected - deduction), 2),
        "room": (round(now["ceiling"] - (projected - deduction), 2)
                 if now["ceiling"] else None),
        "message": (
            f"Projected taxable income is "
            f"{projected - deduction:,.0f} (after the {deduction:,.0f} standard "
            f"deduction), past the {now['ceiling']:,.0f} top of the "
            f"{now['rate'] * 100:.0f}% bracket — "
            f"income above that is taxed at {later['rate'] * 100:.0f}%. Only the "
            f"amount above the threshold is, not the whole income."
            if crossed else
            f"Projected taxable income is "
            f"{projected - deduction:,.0f} (after the {deduction:,.0f} standard "
            f"deduction), still inside the {now['rate'] * 100:.0f}% bracket, "
            f"which runs to {now['ceiling']:,.0f}. The figure is a floor, so "
            f"treat the {now['ceiling'] - (projected - deduction):,.0f} of room "
            f"as an upper bound."
            if now["ceiling"] else
            f"Projected income for the year is {projected:,.0f}, in the "
            f"top bracket."),
    }
    return out
