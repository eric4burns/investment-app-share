"""Chart setups — how somebody configures a chart, separated from what they trade.

A full trading method needs entry rules, invalidation and sizing, and encoding
one badly is worse than not encoding it. A chart SETUP needs none of that: it is
just the timeframe and the indicators at the settings a particular analyst uses,
which is both easier to source accurately and, in practice, the more useful half.
Being able to open any ticker "the way he looks at it" is most of the value of
following someone.

Setups are therefore first-class and separate from methods. A setup can exist on
a single sourced quote about which indicator someone uses; a method cannot.

Every setup records where its settings came from, and `confidence` says plainly
how well sourced it is:

    stated    — the analyst names the indicator and its settings, quoted here
    reported  — settings relayed by someone who watched their material, but not
                quoted directly. Almost certainly right, and still second-hand:
                the distinction matters because a misremembered period would be
                indistinguishable from a sourced one without it.
    inferred  — repeatedly visible in their material, settings deduced
    proposed  — a sensible default awaiting confirmation, attributed to nobody
"""
from __future__ import annotations

SETUPS: dict[str, dict] = {
    "cantonese-cat-monthly": {
        "name": "Cantonese Cat — monthly structure",
        "attribution": "Cantonese Cat (@cantonmeow)",
        "confidence": "inferred",
        "source": "8 videos, Jun–Aug 2026. 'monthly' appears 49 times against 3 for 'daily'.",
        "timeframe": "M",
        "scan": "cantonese-cat-monthly-reversion",
        "indicators": ["sma:20", "bollinger:20:2", "ichimoku:9:26:52", "rsi:14", "volume"],
        "reading": [
            "Start on the monthly. The 20-month moving average is the reference level — "
            "price backtesting it is the event worth waiting for, quoted as ~12 times in 16 years.",
            "A rising 20-month MA supports price. A negatively sloping one rejects it; that "
            "distinction does more work than any oscillator here.",
            "The lower monthly Bollinger Band often coincides with those backtests. Touching "
            "both at once is the strongest version of the setup.",
            "Ichimoku supplies structure: stretched far from the tenkan implies consolidation "
            "before continuation, and holding the kijun means the monthly picture is intact.",
            "RSI is used for divergence rather than level — a bullish divergence is what marks "
            "stabilisation.",
        ],
        "quotes": [
            "\"over the last 16 years, there have been 12 times where it back tested the "
            "20-month moving average and sometimes go beyond and touch the lower Bollinger Band\"",
            "\"the 20-month moving average here is negatively sloping ... to the point that it "
            "is rejecting price\"",
            "\"when things get a little bit too far from the Ichimoku, it just consolidate sideways\"",
        ],
    },
    "ronniev-williams": {
        "name": "RonnieV — Williams %R",
        "attribution": "RonnieV (@TheRonnieVShow)",
        # REPORTED, not stated. The taxonomy above draws the line at whether the
        # SETTINGS are quoted, and these are not: they were relayed by someone
        # who watched the video. The approach around them is quoted from his
        # posts, which is why this read as "stated" — but the quotes are about
        # how he uses %R, not about the length or the band levels, and it is the
        # settings this setup exists to record. Almost certainly right, and
        # still second-hand; `needs` already listed what remains unconfirmed.
        "confidence": "reported",
        "source":
            "Settings relayed by the user from one of his videos (length 12, bands 0 and "
            "-100, read on weekly candles); the approach below is quoted from his own posts "
            "on X, August 2026. His broader Matrix system is a proprietary indicator whose "
            "internals are not public, so the Bull Trigger and Matrix Trend references are "
            "recorded as vocabulary rather than reproduced.",
        "timeframe": "W",
        "indicators": ["willr:12:0:-100", "sma:20", "sma:50", "volume"],
        "reading": [
            "Williams %R at length 12 on weekly candles, and he calls it his favourite "
            "indicator outright.",
            "The bands at 0 and -100 are the key choice, and his posts explain why: he draws "
            "STRUCTURE ON THE OSCILLATOR ITSELF — a 'green barrier' at the oversold extreme, "
            "and 'boxes' that consolidate and then break out. Removing the -20/-80 guides "
            "gives the full range to draw in. He is reading %R as a chart in its own right, "
            "not checking it against two threshold lines.",
            "A 'W%R green barrier' hit is his signal that a bottom is in range. He then waits "
            "at a predetermined price rather than buying the signal: 'This is why I don't "
            "chase. I wait for MY price.' On $ZETA he asked $18.79, was filled at $19.07, and "
            "the low held.",
            "A 'W%R bearish box breaking out' is the bullish version on the way up — the "
            "oscillator escaping a consolidation range it had been trapped in.",
            "%R is one input among several. He describes using 'a lot of different indicators "
            "and moving averages' alongside it, with his Matrix trend flip and Bull Trigger as "
            "confirmation after the %R sets up the level.",
            "He runs the same idea as a DCA optimiser — using the extremes to decide when to "
            "add rather than adding on a calendar.",
            "His SMH chart of 2026-07-19 (saved by the user from X) shows the argument he makes "
            "for the signal: every earlier touch of the floor is circled and the rally that "
            "followed is written beside it — 15.68%, 24.25%, 6.53%, 76.30% — with a volume "
            "spike and the 200-day average under the current one. The record of what the "
            "floor did last time is the case, not the reading itself; the engine now carries "
            "that record on its Williams %R item.",
        ],
        "quotes": [
            "\"A lot of different indicators and moving averages to include my favorite "
            "indicator the W%R.\" (X, 27 Aug 2026)",
            "\"W%R Green Barrier nailed it AGAIN and the Bull Trigger followed shortly after. "
            "This is why I don't chase. I wait for MY price.\" (X, 27 Aug 2026, on $ZETA)",
            "\"$APP may have just bottomed... +Daily Matrix is flipping bullish. +W%R bearish "
            "box is breaking out. +False breakdown of consolidation.\" (X, 27 Aug 2026)",
            "\"Williams % range. Free on Tradingview.\" (X, 13 Aug 2026)",
        ],
        "needs": [
            "The exact level he treats as the green barrier — the settings imply -100, but "
            "whether he uses a zone above it is unconfirmed",
            "How he picks the limit price once %R signals; 'MY price' is not defined publicly",
            "Whether length 12 changes on daily or monthly, since he trades all three",
        ],
    },
    "ronniev-matrix": {
        "name": "RonnieV — Matrix system (reading order)",
        "attribution": "RonnieV (@TheRonnieVShow)",
        "confidence": "stated",
        "source":
            "His video 'Most Traders See This Signal Too Late', which is the source of the "
            "Bull Trigger vocabulary he posts on X. The indicator that PRINTS a trigger is "
            "proprietary and he does not disclose it, so nothing here reproduces it. What is "
            "recorded is the order he reads things in and the filter he applies, both of "
            "which he states plainly and neither of which needs his indicator.",
        "timeframe": "W",
        "indicators": ["willr:12:0:-100", "ema:9", "ema:21", "sma:50", "volume"],
        "reading": [
            "Top-down, and in that order: which sectors and themes are already in a bull run, "
            "then the individual names inside them. The market call comes before the ticker.",
            "Weekly is the working timeframe, chosen for what it feeds rather than for its own "
            "sake — 'it gets you monthly signals, so I love the weekly time frame'.",
            "Three things must line up, not one: a bull trigger prints, the leading trend "
            "flips red to green, and the trend itself flips bear to bull. A trigger on its own "
            "is not the trade.",
            "THE FILTER THAT MATTERS: a trigger late in a move that has already run is not the "
            "same trade as a trigger off a flip, even though the signal looks identical. He "
            "names the case — a name that already went 13.37 to 30 and then prints another "
            "trigger — and declines it. Where you are in the run is part of the setup.",
            "Enter as close as possible to the trend line, which is the same patience as his "
            "%R work: the signal identifies the name, a predetermined price gets the fill.",
            "The exit is deliberately not symmetric with the entry. He cuts losers quickly but "
            "will not take a fixed 10-30% win — the whole point is to hold the trend while it "
            "lasts.",
            "Charts stay clean. The only additions he allows are a volume shelf or anchored "
            "volume profile, Williams %R, and Fibonacci retracements and extensions.",
        ],
        "quotes": [
            "\"a bull trigger is bullish, and a bear trigger is bearish ... It is that simple "
            "with this strategy\"",
            "\"Bull trigger, out of the sweet spot, flip from red to green, and you can enter, "
            "and you can ride it\"",
            "\"I do not want to take a bull trigger that's up here ... we already had a bull "
            "trigger ... and we ran from 13.37 up to $30, almost 3Xing our trade, yeah, you're "
            "taking a big risk\"",
            "\"It gets you monthly signals, so I love the weekly time frame\"",
            "\"It's getting rid of losers quickly ... but then after that, it's not about "
            "making 10, 20, 30% and then exiting\"",
        ],
        "caveats": [
            "The trigger itself is a proprietary indicator behind his paid community. Nothing "
            "in this app reproduces or approximates it, and no signal here should be read as "
            "a Bull Trigger.",
        ],
    },
    "ronniev-ma-stack": {
        "name": "RonnieV — moving average stack",
        "attribution": "RonnieV (@TheRonnieVShow)",
        "confidence": "stated",
        "source": "His video 'The LAST moving averages tutorial you'll EVER need...'",
        "timeframe": "D",
        "scan": "ronniev-ma-stack-trend",
        "indicators": ["ema:9", "ema:21", "sma:50", "sma:200", "volume"],
        "reading": [
            "Four lines, each answering a different question: the 9 EMA for the last two "
            "weeks of momentum, the 21 EMA for the short trend, the 50 for the intermediate "
            "trend, the 200 for the long one.",
            "EMA below 50 periods, SMA at and above it. His reasoning is about what the "
            "average is FOR: a short average should weight recent sessions because it is "
            "measuring momentum, and a long one should weight them equally because it is "
            "measuring trend.",
            "Two readings come before any cross — is price above or below the average, and is "
            "the average rising or falling. Above and rising is the bullish case; the crosses "
            "only confirm it.",
            "9 crossing 21 upward is short-term bullish, downward short-term bearish. 50 "
            "through 200 is the same statement about the long trend.",
            "The longer averages hold better than the short ones. He expects decent bounces "
            "off the 50 and 200 and much less from the 9, 13 and 21.",
            "REPEATED TESTS WEAKEN SUPPORT RATHER THAN CONFIRMING IT. This is the "
            "counter-intuitive one: a moving average tested over and over inside a month is "
            "getting weaker each time, not proving itself, and when it finally breaks 'things "
            "got very bad very quickly'.",
            "A downtrend is recognised by price consistently rejecting off the nearest average "
            "rather than by any single break. The turn shows up first as the 20 and 50 going "
            "flat, then consolidation, then price reclaiming them as support.",
        ],
        "quotes": [
            "\"when you get a 9 EMA crossing through a 21 EMA to the upside, that's going to "
            "be bullish\"",
            "\"what can happen when you start testing the EMA in quick succession over a "
            "shorter period of time, say like a month or so, this starts weakening your "
            "support ... And once it breaks below the EMA, things got very bad very quickly\"",
            "\"it's consistently rejecting off the 21 EMA telling you that nope we are still "
            "bearish ... but you will get these flips eventually where it starts leveling out\"",
        ],
    },
    "stonkchris-cloud-fib": {
        "name": "StonkChris — cloud, Fibonacci and structure",
        "attribution": "Chris (@StonkChris)",
        "confidence": "stated",
        "source":
            "His Substack, read in full on 2026-09-04: the twelve 'Trading Guides & "
            "Strategies' posts (Oct 2025 – Jun 2026) state the rules in his own words, and "
            "243 dated chart reviews apply them. The X posts of August 2026 that this entry "
            "was first inferred from say the same things more briefly. Indicator settings are "
            "not stated anywhere; TradingView defaults are assumed and listed under needs.",
        "timeframe": "D",
        "indicators": ["ichimoku:9:26:52", "rsi:14", "volume"],
        "reading": [
            "The 10/10 buy: price at the BOTTOM of the daily Ichimoku cloud, a downtrend line "
            "that has flipped to support at the same place, and a deeply oversold daily RSI — "
            "where he starts layering DCA bids. Confluence is the whole point; any one alone "
            "is 'above average', not a 10/10.",
            "Weekly and monthly RSI are read as a chart: a long-standing RSI uptrend line, a "
            "higher low against the prior cycle, divergence against price. The core buy is "
            "an HTF RSI reset into that support while price sits at an HTF horizontal flip "
            "or the cloud; the core sell is the RSI trend line breaking, which he says price "
            "lags by weeks.",
            "Fibonacci is anchored on the CYCLE, not the last swing: prior cycle high down to "
            "the bear-market low, on a log scale, so 1.0 is the prior high. 1.618 is the "
            "primary profit-taking target, 2.0 the extension for extreme momentum. On the "
            "daily the 0.5 is his trigger — 'reclaim the 0.5 Fib and the daily cloud'.",
            "Horizontal flip zones must have acted as support or resistance 2–3 times, on the "
            "weekly or daily, with clear wicks; the three buys are the retest after a "
            "breakout, the panic flush into HTF support, and the reclaim from below. Stops go "
            "just under the zone. 'If you have to squint to see it, it's probably not real.'",
            "Top-down: weekly for the trend and HTF support, daily for entries, 4H for timing; "
            "when the weekly, daily and 4H clouds agree the move is high-conviction. Above the "
            "cloud bullish, below bearish, inside trendless. Cloud loss with a trendline break "
            "is the confirmation-based exit.",
            "Everything is conditioned on the index: 'A+ setups routinely failed throughout "
            "2022 because the macro environment was hostile.'",
        ],
        "quotes": [
            "\"I look for moments when price finds support at the lower boundary of the daily "
            "Ichimoku Cloud while the daily RSI is deeply oversold ... When price tags the "
            "bottom of the cloud, aligns with a downtrend line that has flipped into support, "
            "and prints that deeply oversold daily RSI, that's where I start layering DCA "
            "bids.\" (Substack, 29 Oct 2025)",
            "\"The 1.618 Fibonacci level is always my primary profit-taking target in a bull "
            "trend, while the 2.0 Fibonacci level serves as an extension target for names "
            "showing extreme bullish momentum.\" (Substack, 20 Dec 2025)",
            "\"If you anchor the Fib retracement from the 2021 highs ($61.30) down to the 2022 "
            "bear market lows ($20.08), the roadmap becomes very clear\" (Substack, on UBER, "
            "20 Dec 2025)",
            "\"Weekly or monthly RSI pulls back to a long-standing support trendline; RSI prints "
            "a higher low vs prior cycle; price taps into a high-timeframe horizontal S/R flip "
            "or bottom of the cloud\" (Substack, 20 Nov 2025)",
            "\"Once the RSI uptrend breaks, the party is usually over ... Price often lags the "
            "RSI break by weeks\" (Substack, 20 Nov 2025)",
            "\"The level has acted as support/resistance at least 2–3 times ... If you have to "
            "squint to see it, it's probably not real.\" (Substack, 15 Nov 2025)",
            "\"If the weekly cloud, daily cloud, and 4H cloud all agree, the move becomes "
            "high-conviction.\" (Substack, 30 Nov 2025)",
            "\"$GRAB is setting up nicely here if it can break above the 0.5 Fib level and "
            "reclaim the daily cloud.\" (X, 27 Aug 2026)",
        ],
        "needs": [
            "Ichimoku and RSI periods — never stated; his charts are TradingView so the "
            "defaults (9/26/52 and 14) are assumed",
            "How 'deeply oversold' is drawn on the daily RSI — no number is given",
            "The '10/10 Buy Signal' is a name for the confluence above, not a separate "
            "indicator; nothing proprietary is reproduced here",
        ],
    },

    # ------------------------------------------------------------------
    # The accounts in the charts the user saved from X on 2026-09-03.
    # research/charts-2026-09-03-x-accounts.md reads each chart in full; what
    # follows is the setup each one implies. Every one is INFERRED from a
    # posted chart, with the words on the chart or in the post as the quote.
    "wave-count-fib-zones": {
        "name": "Wave count into a Fibonacci zone — The Analyst, Freedom By 40, Mind Investor",
        "attribution": "The Analyst (@MMatters22596), Freedom By 40 (@Freedom_By_40), Mind Investor (@mind1nvestor)",
        "confidence": "inferred",
        "source":
            "Four charts saved from X on 2026-09-03: The Analyst on ASTS and RKLB (daily), "
            "Freedom By 40 on IREN (weekly), Mind Investor on SMR (weekly), plus an "
            "unattributed SIVE daily wave count. Three people, one method: an Elliott wave "
            "count that says where in the cycle price is, and Fibonacci ratios that say "
            "where the correction ends and where the next impulse goes. Settings are read "
            "off the charts; none of them has published a rules list.",
        "timeframe": "W",
        "indicators": ["rsi:14", "sma:200", "volume"],
        "reading": [
            "The count is the frame: a five-wave impulse up, then an A-B-C correction. What "
            "matters for a buy is the C leg — the correction is not over until C has run, "
            "and the B bounce in the middle is not the bottom.",
            "The correction's end is a Fibonacci ZONE, not a level. Mind Investor labels "
            "0.786–0.887 of the prior impulse 'Reversal Zone' on SMR; Freedom By 40 boxes "
            "0.618–0.786 on IREN's weekly with 1.236–1.38 below it as the failure case; the "
            "SIVE count marks 0.786 (24.86) and 0.887 (13.87). A pullback that deep and "
            "holding is the entry.",
            "The B bounce is projected to 0.5–0.786 of the A leg first — The Analyst draws "
            "92.53 / 102.29 / 116.19 on ASTS and 104.60 / 115.55 / 131.14 on RKLB, then the C "
            "leg down to 1.382–1.618 extensions of A (52.80 on ASTS, 58.20 on RKLB). Rallies "
            "into that band are sells to them, not confirmation.",
            "Targets for the next impulse are extensions of the whole structure: 1.382 / 1.618 "
            "/ 1.886 on ASTS (213.70 / 245.30 / 281.19), 1.618 on SMR (~50, 'Wave 3'), "
            "0.618 / 0.786 of a larger degree on IREN (130 / 226). The prior all-time high is "
            "the level that has to be reclaimed on the way (133.90 on ASTS, 150.99 on RKLB).",
            "Freedom By 40 draws trendlines on the RSI pane as well as on price and marks each "
            "break — the same structure-on-the-oscillator habit as RonnieV, StonkChris and "
            "Cantonese Cat.",
            "A rising trendline from the wave (2) low is the invalidation for the whole "
            "count (Mind Investor's SMR line); a close under it says the count is wrong, "
            "not that the zone is a better price.",
        ],
        "quotes": [
            "\"Reversal Zone\" / \"Wave 3\" (Mind Investor, chart labels on SMR weekly, X, Sep 2026)",
            "\"$OKLO & $SMR...\" (Mind Investor, X, Sep 2026)",
            "\"$ASTS & $RKLB:...\" (The Analyst, X, Sep 2026)",
            "\"$IREN isn't a bad company. ...\" (Freedom By 40, X, Sep 2026)",
        ],
        "needs": [
            "Which leg each of them anchors the retracement on — the last impulse, or the "
            "whole advance; the charts differ",
            "Whether the zone is a limit order or a signal to wait for a reversal candle",
            "What invalidates the count for The Analyst — no line is drawn on his charts",
        ],
    },
    "con-wyckoff-phases": {
        "name": "Con — accumulation, distribution, reaccumulation",
        "attribution": "Con (@__Con_)",
        "confidence": "inferred",
        "source":
            "Two charts from one post saved from X on 2026-09-03, 'I'm buying AI stocks "
            "here....': SIVE (4-hour, Stockholm listing) and AAOI (daily). The labels are "
            "his — Accumulation, Distribution, Reaccumulation, HH/HL/LH/LL, and 'Previous "
            "support is now resistance' — and they are the whole method.",
        "timeframe": "D",
        "indicators": ["volume", "sma:50", "sma:200"],
        "reading": [
            "The chart is read as a cycle: accumulation (a base with higher lows), markup "
            "(HH and HL), distribution (a HH followed by LH and LL), markdown, then "
            "reaccumulation — a new range under the old one, where the first higher low "
            "after the lower lows is what he buys.",
            "Every swing is labelled HH, HL, LH or LL. The label sequence IS the phase: "
            "the first HL after a run of LLs is the tell that markdown has ended.",
            "A shelf that held price on the way up and is now above price is resistance, and "
            "he writes it out: 'Previous support is now resistance'. The mirror — a shelf "
            "broken and retested from above — is support. Levels change sides; the line "
            "does not move.",
            "On AAOI the same cycle is drawn as a distribution top under a descending "
            "triangle, a break, and then accumulation above the 105–115 shelf with the "
            "80–90 shelf as the floor beneath it. The buy is in the accumulation range at "
            "the shelf, not on a breakout.",
            "Both charts are on names that had fallen 60–70% from the top. He is buying "
            "washed-out names that have stopped making lower lows, not strong ones.",
        ],
        "quotes": [
            "\"I'm buying AI stocks here....\" (X, 25 Aug 2026)",
            "\"Previous support is now resistance\" (chart label, SIVE 4h, 25 Aug 2026)",
            "\"Accumulation\" / \"Distribution\" / \"Reaccumulation\" (chart labels, SIVE and AAOI)",
        ],
        "needs": [
            "Whether a close below the reaccumulation range is his stop, or he adds",
            "Whether he uses volume to confirm the phase (Wyckoff does; his charts show none)",
            "Position sizing between the first HL and a later confirmation",
        ],
    },
    "x-chart-conventions": {
        "name": "Shelf, trendline break, channel touch and extension targets — three saved charts",
        "attribution": "Nobody; three charts the user saved from X on 2026-09-03 (SteveUrkeldude on IREN, AsafNaaman15 on ASST, an unattributed AEVA chart)",
        "confidence": "proposed",
        "source":
            "Read off three posted charts with no words on them beyond the labels, so nothing "
            "here is sourced from anything anybody said, and none of the three is quoted or "
            "given a setup of their own. What they draw is recorded as a set of conventions "
            "the user already shares (see the note on their own charts of 2026-09-03).",
        "timeframe": "D",
        "indicators": ["ichimoku:9:26:52", "rsi:14", "volume", "sma:50", "sma:200"],
        "reading": [
            "SteveUrkeldude, IREN daily: one descending trendline from the last swing high, an "
            "arrow through it, and a volume-by-price histogram down the right edge. The heavy "
            "node is 40–44; above 47 is thin. The break is drawn into the thin part, which is "
            "the point: a breakout above a heavy node has little in its way.",
            "AsafNaaman15, ASST 4-hour: one horizontal shelf at 23.80 (the prior consolidation "
            "high, now retested from above), a box around the retest, and 1.272 / 1.414 / "
            "1.618 extensions above it (27.03 / 28.84 / 31.44) as targets. Two converging "
            "trendlines from the February low frame the wedge price broke out of.",
            "AEVA daily: a rising channel from the November low with Ichimoku, and beside each "
            "touch of the channel floor the rally that followed — +95.20%, +158.56%, +109.88%. "
            "A line under RSI's rising lows at the current touch marks the divergence. The "
            "case for buying the floor is the record of the earlier touches, not the line.",
            "Common to all three, and to the user's own charts: buy the retest of a level that "
            "held before, trim into extensions above, and treat a trendline break as the "
            "event that turns a range into a trend.",
        ],
        "quotes": [],
        "needs": [
            "Confirmation from any of the three that these are their rules rather than one "
            "chart's annotations",
            "The volume-profile window SteveUrkeldude uses (the histogram spans the visible chart)",
        ],
    },
    "momentum-standard": {
        "name": "Momentum — standard configuration",
        "attribution": "Nobody; public momentum literature",
        "confidence": "proposed",
        "source": "Conventional trend-following configuration, attributed to no individual.",
        "timeframe": "W",
        "indicators": ["sma:20", "sma:50", "sma:200", "rsi:14", "volume"],
        "reading": [
            "Stacked 20 > 50 > 200 is the definition of an established uptrend.",
            "Price near its running high is where momentum lives; a name well off its high "
            "is a different trade with different odds.",
            "RSI strong but capped — momentum and exhaustion look identical until afterwards.",
        ],
        "quotes": [],
    },
    "mean-reversion-standard": {
        "name": "Mean reversion — standard configuration",
        "attribution": "Nobody; public literature",
        "confidence": "proposed",
        "source": "Conventional band-and-average configuration, attributed to no individual.",
        "timeframe": "D",
        "indicators": ["bollinger:20:2", "rsi:14", "sma:200", "volume"],
        "reading": [
            "Price at the lower band with RSI oversold, inside an uptrend defined by the 200.",
            "The 200 is the filter: the same signal below it is a falling knife.",
        ],
        "quotes": [],
    },
}


def catalogue() -> list[dict]:
    return [{"key": k, **v} for k, v in SETUPS.items()]


def get(key: str) -> dict | None:
    s = SETUPS.get(key)
    return {"key": key, **s} if s else None
