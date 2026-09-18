"""Which prices a reading tells you to act at, and what each one is worth.

Split out of `verdicts.py` on 2026-09-09. That module answers "what is this
name doing"; this one answers "so what price do I do something at", and the
two questions had grown into one 2,450-line file. The engine reaches a call;
everything here turns the call into a plan.

## The one rule the whole module is built on

A level is only offered as somewhere to ACT if the market has actually turned
there — three touches, or from both sides. That gate lived on the sell side
alone for a long time, and the buy side took whatever line sat nearest below
price, which put the "buy level" within 1.3% of the last trade on six of
thirteen holdings. The user's reading of that output: "I'm not looking to sell
at every point of resistance and buy at every point of support."

Everything else follows from it. A level that clears the gate is a plan; one
that does not is still drawn on the chart and listed in the levels table, and
is never quoted as a price to act at. Where no level on a side qualifies, the
answer is none, said out loud — "no sell level, nothing tested enough on that
side to trade" — because a blank reads as an oversight and this is a finding.

## Each level carries the move it starts

"If it gives me a buy level or sell level it should also tell me the upside or
downside target of the move." A buy level is quoted with the upside it is being
taken for and the reward against the risk; a sell level with the pullback
expected after it. Both are measured FROM THE LEVEL, not from today's price:
the reader is being told to wait, so a number computed from the current price
describes a different trade from the one on offer.
"""
from __future__ import annotations

# How far a level may be from price and still be offered as somewhere to ACT.
#
# A judgement, and named as one. SIVEF was offering "worth adding nearer 0.58"
# against a price of 2.55 — a 77% fall away, from a zone last touched when the
# Stockholm listing traded at a quarter of today's price — and a trim target
# 347% above. Both are real levels and neither is a plan.
#
# It is a percentage rather than a multiple of ATR because ATR fails exactly
# where this is needed: SIVEF's weekly ATR is 1.52 on a 2.55 stock, so an
# ATR-based gate waves the 77% level straight through. The trendline evidence
# has had a distance gate since CRWV; the watch levels never did.
ACTIONABLE_PCT = 0.35
# The furthest an extension target may sit above price and still be reported
# as a target: a level 600% up is not one.
MAX_TARGET_GAIN = 1.0
MIN_TARGET_GAIN = 0.05    # a level under 5% away is where price is, not a target

# How many times price must have turned at a zone before that zone may be
# offered as somewhere to ACT — on either side.
#
# The sell side has required this since the "how much resistance is there?"
# correction. The buy side never got it and took whatever line sat nearest
# below price, which on 2026-09-09 put the "buy level" within 1.3% of the last
# trade on six of thirteen holdings — a restatement of the price, not a level.
# The user, reading that output: "I'm not looking to sell at every point of
# resistance and buy at every point of support."
#
# One bar for both sides now: price turned there at least three times, or from
# BOTH sides (`flipped`), which structure.zones already calls the strongest
# kind of level. A zone clearing neither is still drawn and still listed; it is
# just not offered as a price to act at.
MIN_LEVEL_TOUCHES = 3

# A buy level nearer than this is not a level to wait for. Price is already
# there, and the honest output is "this is the level, you are at it" rather
# than a number a hair under the last trade.
MIN_ENTRY_DROP = 0.03

# How far below price, in the name's own typical bars, a "you are wrong below"
# level has to sit before it is a stop rather than noise. See where it is used.
MIN_STOP_ATR = 1.0

def watch_levels(g: dict, d: dict, position: dict | None = None) -> dict:
    """The prices to actually watch — where to buy, where to trim, where to bail.

    Separate from `flip`, which is only the price that would INVALIDATE the
    current call. That is the right thing for judging a verdict and the wrong
    thing for acting on one: a hold whose reason is "trend intact, but price is
    not at a level worth adding at" has no flip level and is exactly the case
    where somebody wants a number — the level to wait for.

    Every level here is a price something has already happened at: a zone price
    has turned before, a Fibonacci level is measured off the actual swing, the
    cloud is where it is. None of them is a forecast, and none is a promise that
    price will get there.
    """
    price = g.get("price")
    if not price:
        return {}
    near = g.get("near") or {}
    fib = g.get("fib") or {}
    cloud = g.get("cloud") or {}
    held = bool(position and (position.get("quantity") or 0) > 0)

    # Nearest on the correct side AND close enough to be a plan rather than a
    # historical fact. A level outside the band is still reported in the levels
    # table and on the chart; it just stops being offered as somewhere to act.
    # The cap applies to the ENTRY, which is where you act now. A stop or a
    # target legitimately sits further out — that is what makes a wide setup —
    # and capping those too nulled the reward-to-risk on nearly every holding.
    lo_cap, hi_cap = price * (1 - ACTIONABLE_PCT), price * (1 + ACTIONABLE_PCT)

    def below(*cands, capped=False):
        lo = lo_cap if capped else 0.0
        vals = [c for c in cands if c and lo <= c < price]
        return max(vals) if vals else None

    def above(*cands, capped=False):
        hi = hi_cap if capped else float("inf")
        vals = [c for c in cands if c and price < c <= hi]
        return min(vals) if vals else None

    sup = (near.get("support") or {}).get("high")
    res_zone = near.get("resistance") or {}
    res = res_zone.get("low")
    rets = [l["price"] for l in fib.get("levels", []) if l["kind"] == "retracement"]
    exts = [l for l in fib.get("levels", []) if l["kind"] == "extension"]

    # ---- the buy level: a level, not whatever line sits nearest -----------
    # Candidates are tested zones below price that clear MIN_LEVEL_TOUCHES,
    # the 0.5 and 0.618 retracements — StonkChris triggers off those two and
    # off nothing shallower — and the top of the cloud. The 0.236 and 0.382
    # are deliberately excluded: on most names they sit close enough to price
    # that "buy the 0.236" means "buy here".
    #
    # Nearest among the QUALIFYING candidates, not nearest overall. That is
    # the difference between waiting for a level and buying the last tick.
    deep_rets = [l["price"] for l in fib.get("levels", [])
                 if l["kind"] == "retracement" and l.get("ratio", 0) >= 0.5]
    buy_cands = []
    for z in (g.get("zones") or []):
        if z["high"] >= price or z["high"] < lo_cap:
            continue
        if z["touches"] < MIN_LEVEL_TOUCHES and not z["flipped"]:
            continue
        buy_cands.append((
            z["high"],
            f"tested {z['touches']} time{'s' if z['touches'] != 1 else ''} since "
            f"{z.get('first', '?')}, last {z.get('last', '?')}"
            + (", from both sides" if z["flipped"] else "")))
    for r in deep_rets:
        if lo_cap <= r < price:
            ratio = next((l["ratio"] for l in fib.get("levels", [])
                          if l["kind"] == "retracement" and l["price"] == r), None)
            buy_cands.append((r, f"the {ratio:.3f} retracement of the swing"
                                 if ratio else "a deep retracement of the swing"))
    ct = cloud.get("top")
    if ct and lo_cap <= ct < price:
        buy_cands.append((ct, "the top of the cloud — the edge price has to hold to stay above it"))

    buy_at, buy_why = (max(buy_cands, key=lambda c: c[0]) if buy_cands else (None, None))
    # Price already at the level. Printing 44.89 against a 45.37 last trade
    # reads as a different number and is not one; say it is here instead.
    buy_now = bool(buy_at and buy_at >= price * (1 - MIN_ENTRY_DROP))

    # A resistance is not a trim level because it exists. "Just because there
    # is resistance doesn't mean it's a trim level — how much resistance is
    # there?" A horizontal zone qualifies when price has turned there at least
    # three times, or from both sides; a Fibonacci extension qualifies because
    # it is where the followed charts take the first trim; and nothing more
    # than MAX_TARGET_GAIN above price qualifies at all — ASST's monthly
    # offered a level 828% away. Whatever is chosen carries its strength so the
    # display can say how much resistance is there.
    # ...and it has to be far enough away to be a target. A "target" 1.2%
    # above price (SOFI, 18.43 on 18.22) is where price already is, not
    # somewhere to sell into; anything under MIN_TARGET_GAIN away is skipped
    # for the next level up.
    trim_at, trim_why, trim_strength = None, None, None
    cands = []
    # EVERY zone above price, not just the nearest. `near.resistance` is the
    # nearest by definition, and on IREN that was a 2-touch shelf 1.2% up —
    # under MIN_TARGET_GAIN, so it dropped out and took the whole zone branch
    # with it, leaving the cycle high (76.41, +68%) as the only candidate. The
    # 4-touch flipped zone at 49.19-52.36, the strongest level on that chart,
    # was never considered because something weaker sat in front of it.
    for z in (g.get("zones") or []):
        if not (price * (1 + MIN_TARGET_GAIN) <= z["low"] <= price * (1 + MAX_TARGET_GAIN)):
            continue
        touches = z.get("touches") or 0
        strong = touches >= MIN_LEVEL_TOUCHES or z.get("flipped")
        cands.append((z["low"], strong, touches,
                      f"tested {touches} time{'s' if touches != 1 else ''} since {z.get('first', '?')}, last {z.get('last', '?')}"
                      + (", from both sides" if z.get("flipped") else "")))
    for e in exts:
        if price * (1 + MIN_TARGET_GAIN) <= e["price"] <= price * (1 + MAX_TARGET_GAIN):
            cands.append((e["price"], True, 0,
                          f"the {e['ratio']:.3f} Fibonacci extension of the swing — a measured target, not a tested level"))
    # The cycle leg's extensions first: on a name that has run, "next
    # resistance" is a pivot a few percent up, while the 1.618 of the whole
    # cycle is where the followed traders actually trim. If price is already
    # past the 1.618, the 2.0; past that, the 2.618.
    cyc = g.get("cycle")
    if cyc:
        # Below the prior high, the prior high is the first target (the 1.0),
        # with the 1.618 named as what comes after it; above it, the next
        # extension out.
        ladder = ((1.0, "one"), (1.618, "e1618"), (2.0, "e20"), (2.618, "e2618"))
        for n, (ratio, key) in enumerate(ladder):
            lvl = cyc[key]
            # One MAX_TARGET_GAIN, not three. The 3x allowance let the cycle
            # anchor reach 300% above price — how MSTR's pre-decline high of
            # 455.90 became the sell level against a 132.70 last trade. That
            # level is where the stock came FROM; "sell into it" is a forecast
            # of full recovery dressed as a plan. Still context, not a number.
            if price * (1 + MIN_TARGET_GAIN) <= lvl <= price * (1 + MAX_TARGET_GAIN):
                nxt = cyc[ladder[n + 1][1]] if n + 1 < len(ladder) else None
                what = ("the prior high" if ratio == 1.0 else f"the {ratio} extension") + \
                       f" of the cycle leg {cyc['low_time'][:7]} low {cyc['low']:,.2f} → {cyc['high_time'][:7]} high {cyc['one']:,.2f}"
                cands.append((lvl, True, 0,
                              what + " (StonkChris's anchoring: 1.0 is the prior high, 1.618 the primary trim, 2.0 the stretch)"
                              + (f"; after it, {ladder[n + 1][0]} at {nxt:,.2f}" if nxt else "")))
                break
    strong_cands = [c for c in cands if c[1]]
    if strong_cands:
        ext = [c for c in strong_cands if "extension" in c[3] or "prior high" in c[3]]
        zones = [c for c in strong_cands if c not in ext]
        # A TESTED level wins over a projected one. It was the other way round,
        # and the result was a sell level nobody could use: MSTR was told to
        # sell into 455.90 against a 132.70 price (+244%) because that is the
        # pre-decline high the cycle anchor projects to, while the level that
        # had actually capped it three times since 2026-08 sat at 134.50 and
        # was demoted to a footnote. A price the market has turned at is a
        # place to sell into; a price derived from a ratio is a direction of
        # travel, and belongs after it.
        if zones:
            trim_at, _s, trim_strength, trim_why = min(zones, key=lambda c: c[0])
            beyond = [c for c in ext if c[0] > trim_at]
            if beyond:
                b = min(beyond, key=lambda c: c[0])
                trim_why = trim_why + f"; beyond it, {b[0]:,.2f} ({b[3]})"
        else:
            trim_at, _s, trim_strength, trim_why = min(ext, key=lambda c: c[0])
    weak = [c for c in cands if not c[1]]
    weak_level = min(weak, key=lambda c: c[0]) if weak else None

    # ---- where the idea is wrong ------------------------------------------
    # Measured down from PRICE, not down from the buy level. Anchoring under
    # the entry meant a name whose nearest tested support is far away (IREN,
    # first strong zone 29% below) searched below THAT and came back empty, so
    # a position actually owned had no invalidation number at all. What breaks
    # the position is a level under today's price; whether you would also have
    # bought there is a separate question. Every candidate is a price the
    # market actually made — never a percentage off the last trade.
    unit = g.get("atr") or price * 0.02
    cyc_low = (g.get("cycle") or {}).get("low")
    stop_cands = sorted(
        {round(x, 4) for x in
         [sup, cloud.get("bottom"), d.get("flip"), cyc_low]
         + [r for r in rets]
         + [z["low"] for z in (g.get("zones") or [])]
         if x and x < price},
        reverse=True)
    # The nearest one under price, subject to three rules. It is never the same
    # number as the buy level — one price as both the place to add and the
    # place to leave (ASST once showed 23.02 as both) is not a plan. It must
    # sit at least MIN_STOP_ATR of the name's OWN typical bar below price,
    # because a stop inside one session's range is not a stop: IREN's was 44.89
    # against a 45.37 last trade, on a name that moves ten times that in a day.
    # And it is capped like the entry — SIVEF offered 0.31 against 3.24, which
    # is a historical fact, not a price you would still be holding at.
    stop_at = next((c for c in stop_cands
                    if not (buy_at and abs(c - buy_at) < unit)
                    and c <= price - MIN_STOP_ATR * unit
                    and c >= lo_cap), None)

    def pct(x):
        return None if not x else round((x / price - 1) * 100, 1)

    # ---- what each level is being taken FOR -------------------------------
    # "If it gives me a buy level or sell level it should also tell me the
    # upside or downside target of the move." A level says WHEN and nothing
    # about what the trade is worth, so on its own it cannot be compared with
    # any other trade or with doing nothing.
    #
    # Both targets are measured FROM THE LEVEL, never from today's price. The
    # reader is being told to wait, so a ratio computed from the current price
    # answers a question about buying today — a different trade from the one
    # being offered. `quality()` still measures from price, deliberately: it
    # ranks a screen of calls rather than describing one plan.
    targets = _targets(g, price, buy_at, trim_at, stop_at)

    return {
        "price": price,
        "buy_at": buy_at, "buy_pct": pct(buy_at),
        "buy_why": buy_why, "buy_now": buy_now,
        "trim_at": trim_at, "trim_pct": pct(trim_at),
        "trim_why": trim_why, "trim_strength": trim_strength,
        **targets,
        "weak_resistance": (weak_level[0] if weak_level else None),
        "weak_resistance_why": (weak_level[3] if weak_level else None),
        "stop_at": stop_at, "stop_pct": pct(stop_at),
        "levels": _watch_levels_for(d.get("verdict"), held, price,
                                    buy_at, trim_at, stop_at,
                                    d.get("flip"), d.get("flip_note"),
                                    trim_why=trim_why,
                                    weak=(weak_level[0], weak_level[3]) if weak_level else None),
    }


def _targets(g: dict, price: float, buy_at, trim_at, stop_at) -> dict:
    """Where the move from each level is expected to go, and what it is worth.

    The upside target of a buy is the next tested level above the ENTRY, which
    is normally the sell level itself. The downside target of a sell is the
    next tested level below it — on a trade-around name that is the buy-back.
    Both are levels the market has already turned at, so neither is a forecast
    of a price that has never traded; what is being claimed is only that the
    place a move stalls is usually a place it has stalled before.

    `buy_rr` is the reward against the risk of the trade being offered:
    entry to target over entry to invalidation. It is None where the
    invalidation sits ABOVE the entry, because there is no trade there to size
    — the reading says so in words instead.
    """
    strong = [z for z in (g.get("zones") or [])
              if z["touches"] >= MIN_LEVEL_TOUCHES or z.get("flipped")]

    def above(x):
        c = [z["low"] for z in strong if z["low"] >= x * (1 + MIN_TARGET_GAIN)]
        return min(c) if c else None

    def below(x):
        c = [z["high"] for z in strong if z["high"] <= x * (1 - MIN_TARGET_GAIN)]
        return max(c) if c else None

    buy_target = None
    if buy_at:
        # The sell level is the target when it is genuinely above the entry;
        # otherwise the next tested level up from the entry.
        buy_target = trim_at if (trim_at and trim_at > buy_at) else above(buy_at)
    sell_target = below(trim_at) if trim_at else None

    buy_rr = None
    if buy_at and buy_target and stop_at and stop_at < buy_at:
        buy_rr = round((buy_target - buy_at) / (buy_at - stop_at), 1)

    move = lambda frm, to: (None if not (frm and to)
                            else round((to / frm - 1) * 100, 1))
    return {
        "buy_target": buy_target, "buy_target_pct": move(buy_at, buy_target),
        "buy_risk_pct": move(buy_at, stop_at), "buy_rr": buy_rr,
        "sell_target": sell_target, "sell_target_pct": move(trim_at, sell_target),
    }


def _watch_levels_for(verdict: str, held: bool, price: float,
                      buy_at, trim_at, stop_at, flip, flip_note,
                      trim_why: str | None = None, weak=None) -> list[dict]:
    """The levels this particular call is about, each labelled with what it means.

    The three fields were shown under fixed headings — "Buy / add at", "Trim
    into", "Wrong below" — regardless of the verdict, which produced nonsense on
    anything but a hold. IREN read SELL and displayed "Buy / add at 32.24" above
    "Wrong below 32.24": the same number under two contradictory labels, on a
    name the app was saying to get out of. A sell is also proved wrong ABOVE,
    not below, so the heading was backwards as well as duplicated.

    `tone` is up / down / flag, and `why` is a sentence rather than a heading,
    because "wrong below" is only obvious to whoever wrote it.
    """
    pct = lambda x: None if not x or not price else round((x / price - 1) * 100, 1)

    def lvl(label, value, tone, why):
        return None if not value else {"label": label, "price": value,
                                       "pct": pct(value), "tone": tone, "why": why}

    out = []
    if verdict == "sell":
        # A sell is invalidated by strength, so the flip is the level that
        # matters and it sits ABOVE price. Buy and trim levels are not part of
        # this call at all and showing them contradicts it.
        # The clarification is APPENDED rather than used as a fallback. With a
        # real flip_note present it was replaced, which is exactly the case that
        # prompted the question — IREN read "sell" beside "flips at 42.40" and
        # the obvious reading of a level under a sell is "buy back there".
        out.append(lvl("Sell case ends above", flip, "flag",
                       ((flip_note + ". ") if flip_note else "")
                       + "It is not a target to buy at — price back above here "
                         "undoes the reason for selling, nothing more"))
        out.append(lvl("Next support below", buy_at, "muted",
                       "where a decline would meet a level price has turned at "
                       "before. Not a buy — the call here is to be out"))
    elif verdict == "trim":
        out.append(lvl("Taking some off here", price, "flag",
                       "price is at an upside level it has reached"))
        out.append(lvl("Next level up", trim_at, "up",
                       "what trimming here gives up if it keeps going"
                       + (f" — {trim_why}" if trim_why else "")))
        out.append(lvl("Position is in trouble below", stop_at, "down",
                       "the structure the rest of the position rests on"))
    elif verdict in ("buy", "add"):
        # An add whose level is well below price is not "acting here": MSTR
        # read ADD on the monthly at 142.80 with the level to act at 123.18,
        # three sessions after the user trimmed it at 124.77, and the card
        # said "Acting here at $142.80".
        if buy_at and price and buy_at < price * 0.97:
            out.append(lvl("Worth adding nearer", buy_at, "up",
                           "the call is add, but the level to act at is below today's price — "
                           "nothing to do up here; this is the level to wait for"))
        else:
            out.append(lvl("Acting here at", price, "up",
                           "price is at a level worth acting on now"))
        out.append(lvl("This is wrong below", stop_at, "down",
                       "a close under here breaks what the idea rests on — the "
                       "price to leave, not a place to buy more"))
        out.append(lvl("Next resistance above", trim_at, "flag",
                       trim_why or "where the move would meet a level it has turned at before"))
    else:                                     # hold, and the downgrades
        out.append(lvl("Worth buying nearer" if not held else "Worth adding nearer",
                       buy_at, "up",
                       "nothing to do at today's price; this is the level to wait for"))
        out.append(lvl("Resistance above", trim_at, "flag",
                       trim_why or "where a rally would meet a level price has turned at before"))
        out.append(lvl("Trend breaks below", stop_at, "down",
                       "under here the reason for holding stops applying"))
    if weak and verdict != "sell":
        out.append(lvl("A level, not a trim", weak[0], "muted",
                       f"{weak[1]} — too little resistance to act on"))
    return [x for x in out if x]


