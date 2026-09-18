# Substack notes — StonkChris, 2026-09-04

Rules mined from the 255 posts on `stonkchris.substack.com` (12 Sep 2025 – 2 Sep 2026), pulled in full through the logged-in session and kept locally under `research/substack/StonkChris/` (gitignored; paid content). Twelve posts sit in his "Trading Guides & Strategies" section and state the method in his own words; the other 243 are dated chart reviews that apply it. This file is the rules; the outcome study of his priced levels is `research/audits/substack-stonkchris-levels-2026-09-04.md`.

As with the transcript notes: each rule carries his words, a confidence label (stated / inferred), and whether the app already encodes it. Nothing here is a finding about whether the rule works.

## Entry — "10/10 Buy Signal" (29 Oct 2025), RSI guide (20 Nov 2025), Ichimoku guide (30 Nov 2025)

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| The 10/10 entry is a confluence: price at the bottom of the daily cloud, a downtrend line flipped to support at the same place, daily RSI deeply oversold; then DCA bids | "When price tags the bottom of the cloud, aligns with a downtrend line that has flipped into support, and prints that deeply oversold daily RSI, that's where I start layering DCA bids." | stated | Partly. The cloud, RSI and trendlines exist as separate evidence items; nothing scores the three landing on the same bar. `stonkchris-cloud-fib` now states it. |
| The whole thing is conditioned on the index | "A+ setups routinely failed throughout 2022 because the macro environment was hostile." | stated | Yes — the index read marks a buy down while the S&P is breaking (2026-09-03). |
| HTF RSI is read as a chart: a long-standing RSI uptrend line, higher lows against the prior cycle, divergence | "Weekly or monthly RSI pulls back to a long-standing support trendline; RSI prints a higher low vs prior cycle" | stated | Partly. Weekly RSI divergence is measured (and reads the right way both ways); no RSI trendline exists. |
| The core sell: the HTF RSI trend line breaks, price lags by weeks | "Once the RSI uptrend breaks, the party is usually over ... Price often lags the RSI break by weeks" | stated | **No.** Nothing draws a line on the RSI pane. This is the same "structure on the oscillator" habit RonnieV and Cantonese Cat share (05_method_sources.md). |
| "RSI cooling off": weekly RSI back from 70–90 to 50–60 with the trend intact is the first buyable reset | "Weekly RSI cools from 70–90 down to 50–60 ... You're buying the first reset in a strong bullish cycle" | stated | **No** as a level; the engine reads RSI 50–60 as neutral. |
| Monthly RSI trend breaks mark multi-year turns | "Monthly RSI downtrends breaking → start of new multi-year bull markets" | stated | No — the monthly is scored, but no trend line on it. |
| Buy checklist, needs 3–4 of 5: weekly RSI reset into support; price at an HTF flip or the cloud bottom; RSI divergence or higher low; a Fib retracement lining up; HTF trend still bullish | "When at least 3–4 of these align, the probabilities skew massively in your favor." | stated | Partly — each item exists, the count does not. |
| Cloud: above bullish, below bearish, inside trendless; the bottom of the cloud is the buy in an uptrend, the underside the short | "Good things tend to happen above the cloud. Bad things tend to happen below it." | stated | Yes for the position; the bottom-of-cloud buy-at level is not offered. |
| Weekly, daily and 4H clouds agreeing is high conviction | "If the weekly cloud, daily cloud, and 4H cloud all agree, the move becomes high-conviction." | stated | Weekly and daily are scored; there is no 4H. |
| T/K crosses are secondary | "I don't use the Tenkan or Kijun all that often" | stated | Consistent — `exits.py` replays a Kijun rule, the live call does not lean on it. |
| Edge-to-edge cloud moves as an LTF trade | "Price enters the cloud on one side, clears the first 'edge' with strength, then travels through the entire cloud" | stated | No. |
| Reversal: price through the cloud on volume, a T/K cross, and the cloud ahead thinning and flipping | "The three (3) simple things I focus on" | stated | No. |

## Levels — horizontal flip zones (15 Nov 2025), Fibonacci (5 Nov, 20 Dec 2025, 31 May 2026)

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| A real flip zone has acted 2–3 times, with clear wicks, on the weekly or daily | "The level has acted as support/resistance at least 2–3 times ... If you have to squint to see it, it's probably not real." | stated | Partly — horizontal zones are scored by touches; the "clean, not sloppy" test is not encoded. |
| Three buys off a zone: the retest after a breakout, the panic flush into HTF support, the reclaim from below | "Price loses support → falls lower → reclaims that support level from below → uses it as a launchpad." | stated | The retest exists as the "retest of a shelf" reading; the reclaim does not. |
| Stops go just under the zone; sell into the opposing flip zone | "Buy at support → stop just below" | stated | The levels-to-act-at exist; no stop is proposed. |
| Confirm with RSI basing and volume contracting into the level, expanding on the bounce | "Volume should contract into the level and expand on the bounce." | stated | No volume-shape item. |
| Fibonacci is anchored on the cycle: prior cycle high to bear-market low, log scale; 1.0 = the prior high | "If you anchor the Fib retracement from the 2021 highs ($61.30) down to the 2022 bear market lows ($20.08), the roadmap becomes very clear" | stated | **Different.** `structure.fib` anchors on the last 120-bar swing, linear. His 1.0 is a prior ATH; the app's is the last swing high. Candidate item, measurable on the replay. |
| 1.618 is the primary target, 2.0 the extension for extreme momentum; 0.5 is the daily trigger | "The 1.618 Fibonacci level is always my primary profit-taking target in a bull trend, while the 2.0 Fibonacci level serves as an extension target" | stated | Yes for the ratios (0.5 / 1 / 1.618 / 2 are in `structure.py`); the anchoring differs. |
| Fib levels flip roles: after the 1.618 rejection, price bases at the 1.0 | "Break above 1.0 Fib → target 1.618. Hit 1.618 → take profits. Pull back → attempt to base at 1.0" | stated | No. |
| After a retrace, re-draw from the new swing for 2.618 / 3.618 | "traders can draw a new Fibonacci extension from the most recent swing low to swing high" | stated | The app re-draws every bar by construction. |

## Exits — profit-taking guides (7 Nov 2025, 31 May 2026), stops (15 Feb 2026)

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| First sale takes the whole cost basis out, near the 1.0 extension / prior ATH | "get my cost basis out of a profitable trade before doing anything else" | stated | **No.** `trade_around.py` sells a slice into strength; nothing frames the first sale as cost-basis recovery. Encoded in `stonkchris-harvest-and-size`. |
| Then 25% near 1.618, 25% near 2.618 | "Trim 25% near 1.618 ... Trim another 25% near 2.618" | stated | No ladder. |
| Not on RSI > 70 alone; on bearish divergence into an extension, ideally at the upper weekly Bollinger band | "I don't sell just because RSI hits 70+. Instead, I watch for divergence" | stated | Divergence exists; Bollinger bands do not. Consistent with the trim-into-strength rule. |
| The forgiving exit: a close below the daily cloud, or the uptrend line lost; both at once is the strongest | "Hold the position until price loses the uptrend line or closes below the daily Ichimoku cloud with confirmation" | stated | `exits.py` replays "below the cloud"; the live verdict does not use it as a stop. |
| Percentage ladder: +30% sell 10%, +50% sell 15%, +100% sell 20% | as written | stated (attributed to "many other professional traders") | No. |
| Every trim names a rebuy zone: mid/lower Bollinger band, the breakout retest, or the top of the weekly cloud | "you simultaneously identify a 're-entry zone'" | stated | `trade_around.py` names a buy-back level; not these three. |
| Stops sit where the thesis stops being true — HTF support, range lows, the HTF higher low, the breakout base, the trendline, the cloud | "Your stop should sit at the level where that reason is no longer true." | stated | The verdict shows the level that flips the call; it is not framed as a stop. |
| Percentage stops as a second layer: 3% swing, 5% trend, 8–10% core | as written | stated | `exits.py` replays trailing stops; not these tiers. |
| Dollar risk sets size | "Max risk per trade = $1,500 / Entry = $60 / Stop = $54 / Risk per share = $6 / Position size = 250 shares" | stated | No. |
| Time stop: no follow-through in 3–5 daily candles, or about a week | "Breakout shows no follow-through within 3–5 daily candles → exit" | stated | No. |
| Stops sit slightly beyond crowded levels; reduce size instead of tightening | "don't park your stop exactly where everyone else does" | stated | No. |

## Sizing (26 Jan 2026) and market fear (4 Mar, 11 Jun 2026)

| Rule | His words | Confidence | In the app? |
|---|---|---|---|
| Three tiers — starter, core, full — none started at full size | "I earn my size" | stated | Encoded as a framework; the ledger does not record intent, so it is not graded. |
| Oversized is the usual fault | "If a position is making you uncomfortable ... ~90% of the time, it's #2 [sized too big]" | stated | `risk.py` reports concentration; no sizing rule. |
| VIX above 30 is where he gets aggressive; above 40 is exceptional; the entry is when the VIX stops making new highs | "If the VIX pushes above 30, that's typically when I start looking to get more aggressive with buying quality names." | stated | **No.** Sentiment uses CNN fear and greed; the VIX is not a series. The 12-month forward returns he quotes (~23% above 30, ~28% above 35, ~30%+ above 40) are "multiple studies", unsourced. |
| Scale in over days or weeks after the VIX rolls over | "Scaling into high-conviction positions over several days or weeks reduces timing risk." | stated | No. |

## The daily reviews — how the rules are applied (243 posts)

Vocabulary that recurs in nearly every ticker block, useful because it is what the extraction keys on:

- **"bull trigger"** — a break above the 0.5 Fib and/or a reclaim of the daily cloud; the target that follows is the local high, then the 1.0, then the "measured upside target zone" (1.618–2.0).
- **"Smart Money buy zone"** — a zone below price, usually the bottom of the daily cloud, an HTF horizontal, a Fib (1.0, 1.618 or 2.0 measured DOWN from a breakdown) and an uptrend line landing together. Stated as where he would buy, not as a forecast that price gets there.
- **"measured downside target zone"** — the same Fib drawn down from a failed level; when he names one, the buy zone is at it.
- **"price and RSI put in a higher low"** — his most common bullish tell on the daily.
- Posts follow a weekly rhythm: Monday cross-asset review (SPY, QQQ, IWM, BTC, ETH, GLD, SLV), daily sector reviews mid-week, a weekend theme piece and a weekend subscriber review.

1,737 ticker blocks across 396 symbols; 2,501 priced sentences. The outcome study is in the audit file; the journal carries his "buy here" calls and his measured-downside calls under the `outside` source.
