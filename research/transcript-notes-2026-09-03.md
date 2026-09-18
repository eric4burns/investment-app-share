# Transcript notes — 2026-09-03

Rules mined overnight from the transcripts fetched on 2026-09-02 (27 on disk now, up from 11). Each rule carries the speaker's own words, a confidence label in the Method Library's vocabulary (stated / reported / inferred), and whether the app already encodes it. The point is encoding material; nothing here is a finding about whether the rule works — that is what the replay is for.

## RonnieV — "The LAST moving averages tutorial you'll EVER need" (Ronnie V Trades, 2026-08-09)

The clearest statement of his moving-average practice on record. Three lines only, daily chart.

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| Three lines: 20 EMA (short-term momentum), 50 SMA (intermediate), 200 SMA (long-term) | "We're going to focus on just three simple lines… the 20 EMA… the 50 SMA… the 200 SMA. These are going to be your short-term, medium-term, and then long-term actual trends." | stated | Partly. The engine uses 20/50/200 **SMA**; his short line is an **EMA**. `ronniev-ma-stack-trend` has a four-deep stack. |
| Above the line is bullish, below bearish; rising or falling matters as much | "If the price is above the trend… that is bullish… if the price is below the trend then that is bearish. Is it rising or falling?" | stated | Yes (moving averages evidence, stacked bonus). |
| The best entries are pullbacks INTO the average in an uptrend | "The best time to be buying into your trades should be around these EMAs because more than likely, if you're in an uptrend, these are going to hold." | stated | **No.** The engine reads "above the 20-day" as bullish wherever price is; it does not distinguish a pullback *to* the line from an extension *away* from it. |
| Investors buy around the 200-day, if the business is sound | "As an investor… just buying close around the 200 day moving average… if you pick a good stock and the fundamentals are getting better and you buy around the 200 day moving average, then you should do very very well." | stated | **No** as a level to act at. The 200-day is scored as trend, not offered as a buy-at. |
| Repeated tests of the 20 EMA in quick succession weaken it | "When you start testing the EMA in quick succession over a shorter period of time, say like a month or so, this starts weakening your support." | stated | Yes — `ma_support_exhausted`, on the 21-day. |
| Exit a trade on a close below the 20 or the 50 that had been holding | "That's where you just kind of know, hey, this is where I'm going to just exit my trade if we go below the 20 or the 50 EMA." | stated | Partly — `exits.py` replays "below 20-day" and "below 50-day" rules but the live verdict does not use it as a stop. |
| Crossovers: 20 through 50 up is bullish, 50 through 200 up is bullish; the reverse bearish | "When you get a 9 EMA crossing through a 21 EMA to the upside, that's going to be bullish… 50 smooth moving average crossing through a 200… bullish." | stated | **No** crossover evidence item exists. |
| The lines are lagging; price leads, the averages confirm | "Moving averages are lagging indicators… Price has to do it itself and then the moving averages follow." | stated | Caveat only. |
| Do not buy every touch or trade every crossover; structure comes first | "You cannot buy every touch. You cannot trade every crossover. You cannot ignore the price structure." | stated | Consistent with the engine's design. |

**Worth encoding first:** the pullback-to-average entry (a *buy-at* level at the rising 20 EMA / 50 SMA in an uptrend, and the 200-day for the conviction book), and the crossover items. Both are cheap and both are measurable by the replay before any weight is trusted.

## RonnieV — "Most Traders See This Signal Too Late" (The RonnieV Show, 2026-07-03)

His Matrix system. The trigger itself is proprietary and is **not** reproduced (see `05_method_sources.md`); what is stated is the process around it.

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| Weekly timeframe for swing trades, read once a week | "This is why I love looking at these weekly time frames because it's cutting out the daily noise… you really only have to look at this once a week." | stated | Yes — weekly is a first-class timeframe and, per the replay, the only one with a measurable signal. |
| Enter early in a new trend, never after it has run | "If you miss the beginning of the trend, and you are getting in mid inning or late inning… you are risking way way more… This strategy is all about catching momentum, catching a new trend." | stated | **Partly.** `leg_pos` (where price sits in its swing) exists; nothing uses "how long since the trend flipped" as a gate. |
| The sweet spot for a trigger is Williams %R between −60 and −100 | "We came down here into the sweet spot between -60 and -100, that is the sweet spot. I do not want to take a bull trigger… up here." | stated | Partly — W%R ≤ −80 is bullish evidence; the −60 floor is not used. |
| Top-down: index first, then sector/theme, then the stock | "I look at the overall markets… then we go into sectors and themes… then we go into the individual stocks." | stated | The pieces exist (regime, rotation, theme rotation); nothing sequences them into a gate. |
| Scale in thirds when price is far from the trend line | "You would nibble like 1/3 position, and then as it comes back another 1/3, and then as it comes back into the trend another 1/3." | stated | No. |
| Never chase a 20% week | "I wouldn't be chasing a 20% week." | stated | No explicit rule; the swing-location gate approximates it. |
| Take profits at targets and psychological levels; always leave a quarter as a runner | "Once you take your profits on the way up… you always leave 1/4 for runners." | stated | No. Relevant to the trade-around-core bucket. |
| After the first target, the stop moves to the entry | "Once you get to your first target, you're saying, 'Okay, my stop loss now becomes my entry price.'" | stated | No. |
| Cut losers at 10–20%, hold winners for 30–80%; 3:1 is the target | "Cut a loss very quickly, say no more than 10, 15, 20%, and you can hold a winner for 30, 60, 81%… 3:1 risk-reward ratio is where we live." | stated | The reward/risk score exists; no sizing or stop rule uses these numbers. |
| His own record: 54% win rate, average win 37%, average loss 14% | "54.4% win rate, 68 wins, 57 losses… average loss is 14%, average win is 37%." | stated, self-reported | Context for what a working swing method's numbers look like. |

## RonnieV — "Markets Just Flashed A Warning" (Ronnie V Trades, 2026-07-08)

Index-level reading, on the QQQ weekly. Several proprietary indicators appear; only the Williams %R method is stated in enough detail to encode.

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| Williams %R "consolidation boxes" near the top of its range mean the index keeps rising; breaking DOWN out of the box is the warning | "These tight consolidations of the Williams percentage indicator… as long as you're in these boxes up here towards the red barrier, the market is going higher. But whenever you break out of these boxes, the market typically falls lower." | stated | **No.** Structure on the oscillator pane is the cross-cutting idea in `05_method_sources.md`, still unbuilt. |
| The green barrier (W%R near −100) on the index is where to buy as an investor; raise cash beforehand | "Buying at the green barrier when the overall indexes are down low and beaten up is the best time to be buying." / "Raising some cash… 10, 15, 20% to be a big buyer if we do fall down to the green barrier." | stated | Partly — W%R floor is bullish evidence per name; there is no index-level cash rule. |
| His weather scale: clear skies (max exposure), windy (pull back, raise cash) | "Move us from clear skies… into windy where we're going to be a little bit more cautious." | stated | No. A regime label is what `intermarket.py` produces for one pair; this is a portfolio-exposure dial. |
| RSI divergence while price chops sideways is a crack | "Now you have divergence on the RSI… we're starting to see signs and cracks." | stated | No divergence detection. |

## Cantonese Cat — "AI Data Center Stocks: What's Next?" (2026-08-26)

A walk through the neocloud names (WGMI, HUT, CIFR, IREN, KULR, CLSK, MARA, RIOT, HIVE, CORZ). What is stated is how he reads, which is what the schema wants.

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| Absorption: high-volume selling that fails to break support is shares moving from weak to strong hands | "When you have high volume but you're not able to break down underneath support… that to me is absorption." | stated | **No.** The single most repeated idea in his material; needs volume-at-a-level. |
| Committed vs non-committal moves: up on rising volume, down on declining volume is progression | "The up move is committed. Then the move down is non-committal… there is progression here on the way up." | stated | No volume evidence in the engine at all. |
| Cup, handle, breakout, backtest as the bullish sequence | "I see a big cup… a handle. I see a breakout. I see a back test." | stated | No pattern detection. (Phase 2.) |
| A resistance flipped to support, then respected, is the bullish tell | "You have a resistance level flipped into support here, which is not a bearish thing." | stated | Yes — zones carry `flipped`, and broken trendlines now flip role. |
| The monthly Ichimoku Kijun as the line a bull trend must hold | "It is still holding the monthly Ichimoku kijun… so it is still at an important support level." | stated | Yes on the monthly timeframe. |
| Confluence of support (anchored VWAP from the high and the low, Supertrend, 20-month MA, Keltner 20 EMA) marks the bottom | "There is so much confluence of support right here that tells me… a very important bottom." | stated | Partly — no anchored VWAP, Supertrend or Keltner as evidence; confluence is not counted. |
| Rising three methods (five-candle continuation) on the monthly | "This is usually a continuation pattern." | stated | No candlestick patterns. |
| Gann fractions (1/4, 1/3, 1/2, 2/3, 3/4 of a range) over Fibonacci | "I don't want to look at the Fibonacci. I want to look at what I call GAN levels… it basically is respecting the GAN levels extremely well." | stated | **No — and worth noting beside the replay's finding that the weekly Fibonacci reading is inverted.** |
| Institutional ownership rising through a correction supports the absorption read | "There's actually a huge spike in terms of institutional ownership… across the entire sector." | stated (fintel.io) | No; 13F data from EDGAR is free and could follow the Form 4 work. |

## Cantonese Cat — "The Cat 30: Sector Rotation, Gold, Silver" (2026-08-23)

Macro process; the encodable part is how he judges regime.

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| Corrections getting shallower in an uptrend is rising risk appetite | "The corrections have gotten lamer and lamer… we are becoming more risk on here over time." | stated | No. Measurable: successive drawdown depths on the index. |
| Judge relative strength on 18–24 months, not the last quarter | "You cannot just look at the market by just looking at the last two or three months… look at it from around 18 to 24 months." | stated | Rotation uses 1/3/6/12-month windows; the 12-month is the longest. |
| QQQ/SPY ratio and IWM/SPY ratio as risk-on gauges, read with the 20-month MA and monthly Ichimoku | "If this chart looks really strong… the Nasdaq is outperforming SPY. Usually that happens in a more risk on environment." | stated | Ratio charts exist on the Chart tab; not read as a regime input. |
| ARKK breaking out while indices only backtest their 20-day is a risk-on tell | "It certainly doesn't seem like a risk-off environment if the ARK fund is able to outperform the rest." | stated | No. |
| Bollinger squeeze after years of nothing resolves impulsively | "This huge Bollinger Band squeeze… is telling you… volatility is to come." | stated | Bollinger exists as an indicator, not as a squeeze condition. |
| Dollar index at resistance with a negatively sloping 20-month MA: not bullish, and a falling dollar helps risk assets | "If the US dollar index is finding resistance and it's going down… that's going to be more bullish for assets in general that you own that are more risk on." | stated | `intermarket.py` has one pair (copper/gold); the dollar is not read. |

## What to encode next, in order

1. **Pullback-to-average entry** (RonnieV): a buy-at level at a rising 20 EMA or 50 SMA in an uptrend, the 200-day for the conviction book. Cheap; the replay can measure it in half an hour.
2. **Moving-average crossovers** as evidence items (RonnieV). Cheap.
3. **Absorption** (Cantonese Cat): high-volume down bars that close above a level. Needs the volume-at-level machinery that the Phase 2 volume items need anyway.
4. **Gann fractions** as an alternative to Fibonacci levels (Cantonese Cat) — and test both against the replay, given the weekly Fibonacci result.
5. **An exposure dial** (RonnieV's weather, Cantonese Cat's risk-on gauges): one regime reading from the QQQ/SPY and IWM/SPY ratios, the dollar, and the index's W%R box, feeding position size rather than any single verdict.

Not encoded, on purpose: the Matrix trigger and Ronnie's temperature indicator (proprietary, undisclosed), and the options-market "volt" levels (a paid third-party feed).
