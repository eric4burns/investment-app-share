"""Portfolio construction frameworks.

A third kind of artifact, distinct from the other two. A SETUP says how to read
a chart. A METHOD says what constitutes a tradeable condition. A FRAMEWORK says
how the whole portfolio should be shaped — how many positions, how large, which
buckets, and what causes a sale.

This one exists because the most useful thing found while gathering material was
not a chart technique at all. It was a portfolio philosophy, and it happens to
address exactly the finding the diagnosis engine keeps returning: a book that is
67% one theme across three names.

Frameworks are checkable. Each principle carries a test against the actual
ledger, so following one is a measurable state rather than an intention.
"""
from __future__ import annotations

FRAMEWORKS: dict[str, dict] = {
    "jrould-three-buckets": {
        "name": "Dr J Rould — three buckets",
        "attribution": "Dr J Rould (@jrouldz)",
        "confidence": "stated",
        "source": "Posted in full on X, 29 Aug 2026, as 'My basic portfolio construction'.",
        "summary":
            "Three separate books with different rules, not one book with mixed intentions. "
            "A long-term basket holding the majority of net worth, a smaller and more "
            "experimental swing book, and dividends as ballast. The point of separating them "
            "is that each has its own sell rule — the failure mode he is designing against is "
            "a swing trade quietly becoming a long-term hold because it went down.",
        "buckets": [
            {"name": "Long term", "share": "the lion's share of net worth",
             "rules": [
                 "Buy with intent to forever-hold",
                 "Sell only when the thesis is failing, or valuation becomes too extreme to justify",
                 "A concentrated core, plus numerous SMALL speculative bets",
                 "Speculative bets become large positions only if they deliver; sold off if they fail",
             ]},
            {"name": "Swing trades", "share": "smaller, experimental",
             "rules": [
                 "Profit and loss targets set on the chart in advance — 'guidelines, not rules'",
                 "For short-to-medium opportunities he is not convinced by fundamentally",
                 "Sometimes riding trends based on investor sentiment",
                 "Smaller sizing, shorter timeframes",
                 "If one proves itself fundamentally, take partial profits and move the rest to long term",
             ]},
            {"name": "Dividends", "share": "counterbalance",
             "rules": [
                 "Counterbalance against all the speculation",
                 "Underperforms in bull markets, outperforms in bear or flat markets",
                 "Stable income generation",
             ]},
        ],
        "quotes": [
            "\"Buy with intent to forever-hold. Only sell when either the thesis is failing or "
            "the valuation has become too extreme to justify\"",
            "\"concentrated core with numerous small speculative bets (that become large "
            "positions if they deliver - or sold off if they fail)\"",
            "\"If one truly proves themselves fundamentally and I have an opening in long term, "
            "I can take partial profits and transfer remainder into long term hold\"",
            "\"Note: if I didn't do this full time, I would have a much simpler portfolio "
            "construction. This takes constant management.\"",
        ],
        "caveats": [
            "He says plainly this is a full-time person's construction and that he would "
            "simplify it otherwise — worth weighing before copying the structure wholesale",
            "No position-count or percentage targets are given; 'concentrated' and 'small' "
            "are his words and are not quantified",
        ],
    },
    "ronniev-dca-optimizer": {
        "name": "RonnieV — DCA optimiser",
        "attribution": "RonnieV (@TheRonnieVShow)",
        "confidence": "stated",
        "source":
            "From his video 'How I Dollar Cost Average Without Guessing'. The multiplier "
            "ladder and the dollar figures are his. What COLOURS a candle is his proprietary "
            "tool and he does not disclose it, so the mapping used to compute a multiplier "
            "here is this app's, built from his stated favourite indicator — see the caveats.",
        "summary":
            "Dollar-cost averaging with a variable amount instead of a fixed one. The "
            "contribution stays on a schedule; only its SIZE changes, scaling up as conditions "
            "get more extreme. His argument is that a flat DCA buys the same dollar amount into "
            "fear and euphoria alike, when fear is precisely when the same dollars buy more.",
        "buckets": [
            {"name": "The ladder", "share": "applied to a regular contribution",
             "rules": [
                 "White candle: 1x — the normal contribution ($250 in his example)",
                 "2x: double down ($500)",
                 "Lime green candle: 3x ($750), and held for as many months as the candle stays green",
                 "Purple candle: 4x — 'very very rare'",
             ]},
            {"name": "Why it is meant to work", "share": "",
             "rules": [
                 "The schedule is unchanged; only the size varies, so it stays a rule rather than a forecast",
                 "Extremes are rare by construction, so the largest buys are few and concentrated",
                 "'That way there's minimal downside, minimal red, but also massive upside'",
             ]},
        ],
        "quotes": [
            "\"You're just simply doing 1x one times your normal DCA.\"",
            "\"2x means now you're going to double down on your DCA and now you're going to do $500.\"",
            "\"if we get to these lime green candles ... that is going to be a 3x DCA, meaning we "
            "are now going to do $750 for that month and however many months it stays that green candle\"",
            "\"lastly, we have the purple candles, which are very very rare ... instead of your 1x, "
            "you're now doing four times that\"",
            "\"instead of 752% gain on Palantir, you would have doubled it and made 1,315% ... "
            "Instead of a seven bagger, you made a 13 bagger.\"",
        ],
        "caveats": [
            "The ladder is his; the trigger is not. His candle colouring comes from a "
            "proprietary tool he does not disclose, so any computed multiplier here is this "
            "app's approximation using his stated favourite indicator (Williams %R, length 12, "
            "bands 0/-100), not his signal.",
            "The Palantir figure is a single retrospective example on a name that worked, "
            "chosen after the fact. It is an illustration of the mechanism, not evidence.",
            "Scaling into weakness increases exposure exactly when a thesis may be breaking; "
            "the ladder assumes the underlying eventually recovers.",
        ],
    },
    "stonkchris-harvest-and-size": {
        "name": "StonkChris — earn the size, harvest into strength",
        "attribution": "Chris (@StonkChris)",
        "confidence": "stated",
        "source":
            "His Substack guides, read in full on 2026-09-04: 'Position Sizing' (26 Jan "
            "2026), 'The Professional Trader's Guide to Stop Loss Placement' (15 Feb 2026), "
            "'My In-Depth Guide on Profit-Taking' (7 Nov 2025) and its remastered edition "
            "(31 May 2026). The numbers below are his; the tiers are named but not sized.",
        "summary":
            "Three sizes of position, none of them started at full size; a stop that sits "
            "where the reason for the trade stops being true; and a fixed order of sales on "
            "the way up — cost basis out first, then quarters at the Fibonacci extensions, "
            "then whatever is left rides until the daily cloud or the trendline goes. The "
            "failure he is designing against is the round trip: a winner held past its "
            "extension targets and given back on the next pullback.",
        "buckets": [
            {"name": "Sizing", "share": "three tiers, earned not granted",
             "rules": [
                 "Starter: early breakout attempts, bottoming structures, new themes, deep "
                 "oversold mean reversion, VIX spikes — exposure without size, then add at "
                 "better levels or into strength as the trade proves itself",
                 "Core: clean weekly structure, established trend, price above or holding HTF "
                 "levels, risk defined, lower volatility — still not started at full size",
                 "Full size, rare: an exceptional HTF setup, clear asymmetry, or deep "
                 "conviction with confirmation",
                 "'If your position is all you can think about ... you need to cut your size "
                 "in half at a minimum'",
             ]},
            {"name": "Stops", "share": "structure first, then the arithmetic",
             "rules": [
                 "The stop sits where the trade's reason is no longer true: under HTF "
                 "horizontal support, range lows, the HTF higher low, the breakout base, the "
                 "trendline, or the daily/weekly cloud",
                 "Percentage stops as a second layer: about 3% for a new swing, 5% for an "
                 "established trend trade, 8–10% for a low-volatility core holding",
                 "Dollar risk sets size: max loss per trade divided by the stop distance",
                 "Time stop: a breakout with no follow-through in 3–5 daily candles, or no "
                 "expansion in about a week, is exited",
                 "Place the stop slightly beyond the crowded level (equal lows, round numbers) "
                 "and reduce size rather than tighten it",
             ]},
            {"name": "Harvest", "share": "sell into strength, in a fixed order",
             "rules": [
                 "First sale: take the whole cost basis out, typically near the 1.0 extension "
                 "or prior all-time high — 'get my cost basis out of a profitable trade before "
                 "doing anything else'",
                 "Then trim about 25% of what remains near 1.618, and another 25% near 2.618 "
                 "(2.0 is the target for extreme momentum); 1.618 is 'always my primary "
                 "profit-taking target'",
                 "Do not sell on RSI above 70 alone; sell on bearish divergence into a Fib "
                 "extension, ideally with price stretched to the upper weekly Bollinger band",
                 "The forgiving exit for the remainder: hold until a close below the daily "
                 "cloud, or the loss of the uptrend line — both together is the strongest signal",
                 "Percentage ladder as an alternative: +30% sell 10%, +50% sell 15%, +100% sell 20%",
                 "Every trim names a rebuy zone: the middle or lower Bollinger band, the "
                 "retest of the breakout level, or the top of the weekly cloud",
             ]},
        ],
        "quotes": [
            "\"One of the most important rules I follow now — at all costs — is to get my "
            "cost basis out of a profitable trade before doing anything else.\" (7 Nov 2025)",
            "\"Trim 25% near 1.618 ... Trim another 25% near 2.618\" (7 Nov 2025)",
            "\"High conviction does not mean 'go all in.'\" (26 Jan 2026)",
            "\"But even here, I don't start full size. I earn my size\" (26 Jan 2026)",
            "\"Your stop should sit at the level where that reason is no longer true.\" "
            "(15 Feb 2026)",
            "\"3% swing stop ... 5% trend stop ... 8–10% position stop\" (15 Feb 2026)",
            "\"Missing a trade is fine. Chasing a trade is not. Oversizing a trade is "
            "unforgivable.\" (26 Jan 2026)",
        ],
        "caveats": [
            "The tiers are named, not sized: he gives no percentage of the book for a "
            "starter, a core or a full position, so nothing here can grade the ledger "
            "against them without inventing the numbers.",
            "The trim ladder is described on winners chosen after the fact (IREN, UBER, CIFR, "
            "NBIS); the fraction of his positions that ever reach 1.618 is not stated.",
            "The 2.618 in the first guide becomes 2.0 as the stretch target in the later ones; "
            "the app treats 1.618 as primary and 2.0 as the extension, following the later "
            "statement.",
            "His own study of the priced levels in the Substack posts is in "
            "research/audits/substack-stonkchris-levels-2026-09-04.md — the targets are "
            "reached no more often than a level the same distance away on a random day.",
        ],
    },
}


# The multiplier ladder is his. The trigger below is NOT — it is this app's
# attempt to reproduce the behaviour from his stated favourite indicator, since
# the tool that colours his candles is proprietary. Labelled everywhere it is
# surfaced so it is never mistaken for his signal.
DCA_LADDER = [
    (-95.0, 4, "purple",     "Williams %R at the very bottom of its range — his rarest tier"),
    (-85.0, 3, "lime green", "deeply oversold on his settings"),
    (-70.0, 2, "amber",      "oversold but not extreme"),
    (None,  1, "white",      "normal conditions — the base contribution"),
]


def dca_multiplier(conn, symbol: str, end: str, timeframe: str = "W") -> dict:
    """Approximate the DCA tier for one symbol. See DCA_LADDER on attribution."""
    from . import indicators as I, prices

    bars = I.resample(prices.load_bars(conn, symbol, "2015-01-01", end), timeframe)
    if len(bars) < 20:
        return {"symbol": symbol, "insufficient": True}
    series = I.williams_r(bars, 12, 0.0, -100.0)
    if not series:
        return {"symbol": symbol, "insufficient": True}
    value = series[-1]["value"]
    for threshold, mult, colour, why in DCA_LADDER:
        if threshold is None or value <= threshold:
            return {"symbol": symbol, "williams_r": value, "multiplier": mult,
                    "tier": colour, "why": why, "as_of": bars[-1]["time"],
                    "approximation": True}
    return {"symbol": symbol, "insufficient": True}


def catalogue() -> list[dict]:
    return [{"key": k, **v} for k, v in FRAMEWORKS.items()]


def check(conn, positions: list[dict], framework_key: str) -> dict:
    """Compare the actual book against a framework's shape.

    Deliberately reports observations rather than a score. The framework does not
    quantify 'concentrated' or 'small', so inventing thresholds and grading
    against them would be putting numbers in his mouth. What can be said without
    inventing anything is what the book actually looks like beside what he
    describes.
    """
    spec = FRAMEWORKS.get(framework_key)
    if not spec:
        return {"error": f"unknown framework {framework_key}"}

    held = [p for p in positions if p.get("value")]
    total = sum(p["value"] for p in held) or 1.0
    ranked = sorted(held, key=lambda p: -p["value"])

    # The observations below test Dr J Rould's principles. They used to be
    # returned for every framework, so RonnieV's ladder was shown "checked"
    # against buckets he never described. Anything else gets the one honest
    # observation: what the ledger can and cannot say about it.
    if framework_key != "jrould-three-buckets":
        return {"framework": framework_key, "name": spec["name"],
                "attribution": spec["attribution"], "summary": spec["summary"],
                "buckets": spec["buckets"], "quotes": spec["quotes"],
                "caveats": spec["caveats"],
                "observations": [{
                    "principle": "How the book measures against this framework",
                    "state": "Not graded. Its rules are about sizing, stops and the order of "
                             "sales, and the ledger records what was bought and sold, not "
                             "the plan behind it.",
                    "matches": None,
                    "note": "Tagging positions by intent (starter / core / full) would make "
                            "the sizing tiers checkable.",
                }],
                "positions": len(held),
                "largest": ranked[0]["value"] / total if ranked else None}

    # "Small speculative bets" cannot be defined by him, so it is defined here
    # explicitly and labelled as this app's definition, not his.
    small = [p for p in ranked if p["value"] / total < 0.02]
    core = [p for p in ranked if p["value"] / total >= 0.10]

    observations = []
    if core:
        observations.append({
            "principle": "A concentrated core",
            "state": f"{len(core)} position(s) at 10% or more: "
                     + ", ".join(f"{p['symbol']} {p['value']/total*100:.0f}%" for p in core),
            "matches": True,
            # This observation asserted a match against a 10% line with nothing
            # saying whose line it was, in a module whose docstring refuses to
            # invent thresholds because that is "putting numbers in his mouth".
            # The 2% used for small bets was disclosed; this one was not.
            "note": "'Concentrated' is this app's threshold at 10%, not his — he "
                    "does not quantify it.",
        })
    observations.append({
        "principle": "Numerous small speculative bets alongside the core",
        "state": f"{len(small)} position(s) below 2% of the book"
                 + (f", totalling {sum(p['value'] for p in small)/total*100:.1f}%"
                    if small else ""),
        "matches": len(small) >= 5,
        "note": "'Small' is this app's threshold at 2%, not his — he does not quantify it.",
    })
    # This principle used to be a hardcoded False with a note claiming it had
    # been "checked" — in a module whose docstring promises every principle is
    # tested against the actual ledger. It now reads the positions.
    INCOME_FUNDS = {"SCHD", "VYM", "DVY", "HDV", "NOBL", "SPHD", "VIG", "DGRO",
                    "JEPI", "JEPQ", "SDIV", "PFF", "VNQ", "SPYD", "DIVO"}
    income = [p for p in positions
              if (p.get("symbol") or "").upper() in INCOME_FUNDS]
    income_weight = sum(p.get("weight") or 0 for p in income)
    observations.append({
        "principle": "Dividends as a counterbalance to the speculation",
        "state": (f"{', '.join(p['symbol'] for p in income)} — "
                  f"{income_weight*100:.1f}% of the book"
                  if income else "No dividend-oriented holding is identifiable in the book"),
        "matches": bool(income),
        "note": "Recognised by a list of income-oriented funds, so a dividend-paying "
                "individual stock held for its yield would not be counted. He gives no "
                "target weight, so any presence counts as a match.",
    })
    observations.append({
        "principle": "Swing trades sized smaller than long-term holds",
        "state": "The ledger does not record intent, so a swing trade and a long-term hold "
                 "are indistinguishable to the app",
        "matches": None,
        "note": "Tagging positions by intent would make this checkable.",
    })

    return {"framework": framework_key, "name": spec["name"],
            "attribution": spec["attribution"], "summary": spec["summary"],
            "buckets": spec["buckets"], "quotes": spec["quotes"],
            "caveats": spec["caveats"], "observations": observations,
            "positions": len(held), "largest": ranked[0]["value"] / total if ranked else None}
