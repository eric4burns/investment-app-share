# Method Sources — people to encode
_From `investment account follows.pages`, 2026-08-29. First batch; more to come, especially for research._

## X / Twitter

| Handle | Name | What they're good at | Tier |
|---|---|---|---|
| `@Nanakyzetweets` | Nanalyze | Good bear cases | first batch |
| `@kevinxu` | Kevin Xu | Good swing trades | first batch |
| `@zastocks` | za | Charts | first batch |
| `@aleabitoreddit` | serenity | Supply chains | **top 5** |
| `@cantonmeow` | cantonese cat | Great technical analyst | **top 5** |
| `@jrouldz` | Dr J Rould | "Very good" | **top 5** |
| `@TheRonnieVShow` | RonnieV | — | **top 5** |
| `@StonkChris` | Chris | "One of the best" | **top 5** |

User's note: *"I think the last 5 are the best by far"* — so **serenity, cantonese cat, Dr J Rould, RonnieV and StonkChris are the priority set.**

## YouTube

Pulled nightly at 04:00 by `research/yt-nightly.py`. The handle in brackets is
what `app/ytpull.py` keys on, and is deliberately the same string the X pull
uses so one person is one account in the crowd reading.

- **Cantonese Cat** (`@cantonmeow` — *not* `@CantoneseCat`, which is dead)
- **TheRonnieVShow** (`@TheRonnieVShow`)
- **Ronnie V Trades** (`@RonnieVTrades`)
- **TheTechnicalTraders** (`@thetechnicaltraders`)
- **Nanalyze** (`@nanalyze`)
- **Verified Investing** (`@VerifiedInvesting`) — Gareth Soloway, also followed on X
- **Joseph Carlson** (`@JosephCarlsonShow`)

Added 2026-09-13 at the user's request. Every handle was resolved against
YouTube before being wired in, after `@CantoneseCat` turned out to 404.

## Why YouTube matters more than X here

Long-form video is *far* better raw material for method extraction than tweets. A tweet shows a conclusion; a video shows the reasoning — which indicators are on the chart, what timeframe, what invalidates the setup, how position size is chosen. Those are exactly the fields the method schema needs and exactly what tweets omit.

**Practical consequence:** transcripts are free (YouTube auto-captions), unlimited, and searchable — no API cost, no rate limits, no scraping fragility. So the Method Library should be built **YouTube-transcript-first**, with X as a supplementary signal feed rather than the primary source. This also further weakens the case for paying for the X API.

**Two things learned since, which qualify that.** Auto-captions are not always
there — Cantonese Cat's chart videos carry no caption track at all, so a local
whisper.cpp transcription now runs for those. And a transcript is searchable for
*names* only with difficulty: nobody says "dollar sign P-L-T-R" out loud, so
company names have to be matched instead, which works for about 140 of the 206
names on the book and not at all for Apple, Target or Block. Detail in D109.

**A chart-flipping video is a different problem again.** Where somebody shows
forty charts and talks over them, the names are on screen rather than in the
words. `research/video/` reads those off the frames with OCR, resolves them to
tickers, proves each chart is the ticker claimed against real price bars, and
stores the Fibonacci levels drawn on it. See D105–D107.

## Overlap worth noting

**Cantonese Cat** and **RonnieV** appear on *both* lists — they're in the priority five on X and they publish long-form on YouTube. That makes them the obvious first two to encode: the most material, in the most extractable form, from people already rated highly.

## Proposed first encoding order

1. **Cantonese Cat** — described as a technical analyst, and has YouTube. Technical methods are the most mechanically encodable, so this is the best test of the schema.
2. **RonnieV / Ronnie V Trades** — two channels of long-form, priority tier.
3. **StonkChris** — "one of the best," X-only for now.
4. **Dr J Rould**, **serenity** — serenity's supply-chain angle is fundamental rather than technical, which will usefully stress-test whether the schema can hold non-chart methods.

## What has actually been encoded (as of 2026-08-29)

All of it lives in the app's **Research** tab, split into four kinds because
they answer different questions and mixing them is dangerous:

| Kind | Answers | Encoded |
|---|---|---|
| **Setup** | how to read a chart | 7 |
| **Framework** | how the whole book should be shaped | 3 |
| **Intermarket** | what regime we are probably in | 1 |
| **Thesis** | why a group of names might re-rate | 1 |

Confidence is recorded on every artifact and shown in the UI, because it changes
how much weight the rest deserves:

- **stated** — quoted directly from the source
- **reported** — relayed second-hand, no direct quote
- **inferred** — deduced from their material, not something they said
- **proposed** — belongs to nobody; this app's own baseline

### The cross-cutting finding

Three of these people, working independently and in different markets, do the
same unusual thing: **they draw structure on the indicator, not just on price.**

- RonnieV sets Williams %R bands to 0 and −100 — removing the usual −20/−80
  guides — specifically so he has the full pane to draw in, and then talks about
  a "W%R Green Barrier" and a "W%R bearish box breaking out".
- StonkChris draws trendlines on the oscillator and reads divergence as broken
  structure rather than as a numeric threshold. His Substack states it outright:
  "Once the RSI uptrend breaks, the party is usually over ... Price often lags
  the RSI break by weeks."
- Cantonese Cat posts "a weekly RSI trendline breakout that nobody is paying
  attention to."

The conventional use of an oscillator is a threshold check — is RSI above 70.
All three instead treat the oscillator pane as a chart in its own right, with
support, resistance and breakouts of its own. That is the single most
transferable idea gathered so far, and it is an argument for the charting side
of this app supporting drawing tools **on the lower panes**, not only on price.

### What is deliberately NOT encoded

Two of these people rely on proprietary indicators they sell access to and do
not disclose:

- RonnieV's **Matrix** system prints the "Bull Trigger" he posts about. What is
  recorded is his reading ORDER and his filters, both stated plainly and neither
  requiring the indicator. Nothing here reproduces or approximates the trigger,
  and a test enforces that.
- His **DCA Optimizer** colours candles white / 2x / lime green / purple. The
  multiplier ladder is his and is quoted. The trigger is not, so the computed
  tier in this app is an approximation built from his stated favourite indicator
  and is labelled as such everywhere it appears.

## Accounts seen in the user's saved charts (2026-09-03)

Not on the original follows list, but the user saved their charts and said "some of these are the other accounts I like on twitter." Read in full in `research/charts-2026-09-03-x-accounts.md`.

| Handle | Name | What they draw | Encoded as |
|---|---|---|---|
| `@MMatters22596` | The Analyst | Elliott counts with A-B-C corrective targets in Fibonacci zones (ASTS, RKLB) | `wave-count-fib-zones` |
| `@Freedom_By_40` | Freedom By 40 | Weekly wave count, 0.618–0.786 buy box, trendlines on the RSI pane (IREN) | `wave-count-fib-zones` |
| `@mind1nvestor` | Mind Investor | "Reversal Zone" at 0.786–0.887, wave-3 target at 1.618 (SMR, OKLO) | `wave-count-fib-zones` |
| `@__Con_` | Con | Wyckoff phases: accumulation / distribution / reaccumulation, "previous support is now resistance" (SIVE, AAOI) | `con-wyckoff-phases` |
| SteveUrkeldude | — | One descending trendline and a volume-by-price histogram (IREN) | `x-chart-conventions` (unquoted) |
| AsafNaaman15 | — | A shelf retest with 1.272 / 1.414 / 1.618 extension targets (ASST) | `x-chart-conventions` (unquoted) |

RonnieV's SMH chart from the same batch is folded into `ronniev-williams`. The calls on every one of these charts are in the decision journal under the `outside` source and are graded on the Research tab ("Followed accounts, graded"); on 2026-09-04 Con's two shelf calls had failed within days, RonnieV's SMH floor was right on direction and wrong on entry, and the rest were too new to score. The charts are conclusions, so everything here is **inferred** from what was drawn, or **proposed** where nothing was said at all; the same YouTube-first rule applies if any of them is to be encoded as a full method.

## StonkChris on Substack (pulled in full 2026-09-04)

`stonkchris.substack.com`, 255 posts from 12 Sep 2025 to 2 Sep 2026, about 216,000 words and 2,071 chart images. The user is a paid subscriber, so the logged-in session sees every post. They were pulled through the browser tab into a local receiver (`research/substack_receiver.py`) and live under `research/substack/StonkChris/` — gitignored, excluded by `share.sh`, and guarded by a test, because every post ends with a redistribution notice. The app stores rules and short quotes, never the posts.

**What was in it.** Twelve posts in his "Trading Guides & Strategies" section state the method in his own words: the "10/10 Buy Signal" (bottom of the daily cloud + a flipped trendline + deeply oversold daily RSI), the higher-timeframe RSI guide (RSI read as a chart with its own trend lines; the RSI trend line breaking is the sell), the Ichimoku guide, horizontal flip zones, two profit-taking guides (cost basis out first, then quarters at the 1.618 and 2.618, or the daily cloud as the forgiving exit), position sizing (starter / core / full, none started at full size), stop placement (structure first, 3 / 5 / 8–10% as the second layer, dollar risk sets size) and two VIX pieces (above 30 get aggressive, above 40 exceptional). The other 243 posts are dated chart reviews on a weekly rhythm — Monday cross-asset, daily sector reviews, weekend theme — 1,737 ticker blocks across 396 symbols, almost every one naming a priced buy zone or target.

**What changed in the app.** `stonkchris-cloud-fib` is now **stated** rather than inferred, with eight quotes and its three open questions answered (settings are never given, so TradingView defaults are assumed and listed as such). A new framework, `stonkchris-harvest-and-size`, holds the sizing tiers, the stop methods and the order of sales. The rules table is `research/substack-notes-2026-09-04.md`. Two places where he differs from the app's own construction are recorded there as candidates, not changes: he anchors Fibonacci on the prior **cycle** high and the bear-market low on a log scale (the app uses the last 120-bar swing, linear), and he draws trend lines on the RSI pane (the app has no such line).

**What his priced levels did** (`research/audits/substack-stonkchris-levels-2026-09-04.md`, cached bars, same-era controls):

- His **upside targets** (887 graded at 63 days) were reached exactly as often as a level the same distance above price on a random day for the same name in the same era — 77% vs 77% within 10%, 56% vs 57% at 10–25%, 35% vs 33% at 25–50%, 12% vs 12% beyond. The targets carry no information beyond how far away they are.
- His **buy zones below price** (192) were reached within 63 trading days 57% of the time. The 90 that were reached and are old enough to grade were up a median 10.6% 63 days after the touch, 64% of them positive, against a fall-matched control (same names, same era, random days after a fall as deep as the zone) of −2.1% median and 45% positive. That is a real difference on a small sample in one year, and it is the one thing in the material that measured better than chance. The zone's floor was undercut by more than 5% in two-thirds of cases, so the entry is the zone, not a stop under it.
- His **"buy here" calls** — a zone named while price was already in it — did no better than the same names on random days: 20 graded, median −9.7% at 63 days, 40% positive, against −8.4% and 39%.
- In the journal, 50 of his calls (28 buys where price was in the zone, 22 measured-downside targets recorded as sells) are graded under the `outside` source as `StonkChris (@StonkChris, Substack)`; at 21 days, 44 graded, 41% hit, averaging 7.8 points behind SPY. The Research tab shows it beside the other followed accounts.

The extraction keys on his own vocabulary and is not perfect — about 2% of priced sentences were dropped as mis-parsed, and a ticker written inline (`$U - ...`) inside another name's block is misattributed — so the numbers above are the shape of the record, not its last decimal. To re-pull after new posts: start `python3 research/substack_receiver.py 8799`, open the archive logged in, and run the fetch loop from the browser tab; `research/seed-stonkchris-calls.py` re-seeds the journal safely.

Cantonese Cat's course is $550; the user has ruled it out, which is consistent with the plan above — encode from the free videos, let the backtest decide.

## The X follow list, read (2026-09-05)

All 507 follows were read through the logged-in browser (X's own Following
query, paged), about 200 of them finance. The user cut the list to 428 and
approved six more unfollows; the sorting and the notes on what each account
contributes are in `research/x/` (local only, like the transcripts). Recent
posts of the finance shortlist were pulled the same way and every dated,
priced call went into the journal under the author's name
(`research/seed-x-calls-2026-09-05.py`, 72 calls across 20 authors), so the
Research tab now grades the people the user actually reads.

Two lessons for how this list is judged, both from the user: a bio that sells
signals says nothing about the account (LEADER_TRADING sells nothing and is
the one account that does what the user wants to do — trade around an IREN
core and end with more shares); and bears on held names are kept on purpose
(Lazarus_Capital on IREN's financing). What LEADER_TRADING actually does, in
his own words, is written up in `research/x/notes-2026-09-05.md`: the core
never moves, a small slice is sold on an intraday failure to make a new high
after a run and bought back at a level named at the sale, and his own
confirmation rule is two consecutive closes over a level. That is the first
thing to encode for the swing study.

The eleven accounts X rate-limited on the day were pulled once the limit
cleared (78 calls across 24 authors in the journal now); _Sgr_A_Star is the
best IREN business coverage on the list, penny_ether the sharpest on the
miners, Tom Lambos the most disciplined swing entries with stops posted.

The pull is now a weekly procedure (D75, SETUP.md): `research/x_pull.js` in
the logged-in tab, the posts read by hand, the priced calls written to
`research/x/calls/<date>.json` and seeded with `research/seed-x-calls.py`.
Two pulls so far, 2026-09-05 and 2026-09-07. **Serenity (@aleabitoreddit)
is ideas-only (D90):** the user rates them for fundamentals and for finding
names, not for timing, so their calls are refused by the journal and never
count toward a buy, sell or trim; their names still surface as ideas.

## Paid courses

Cantonese Cat sells courses the user is considering buying, with the intent of encoding them into the app.

**Worth knowing before spending:** paid course material is usually *better* encoding input than free content — explicit named setups, stated rules, defined invalidation — which is exactly what the method schema wants, and exactly what tweets lack. So the purchase is not wasted on this project if made.

**But the cheaper sequence is better.** Encode the method from the free YouTube material first, backtest it over the user's own cached history, and let *that result* decide whether the course is worth buying. This inverts the usual order — instead of buying the course and hoping, the app tells you whether this person's approach works on the names you actually trade, before you pay. That's a concrete use for the tool before it's even finished.

**Scope note:** what gets encoded is the *method* — indicator settings, entry conditions, invalidation, sizing rules. Methods and factual settings aren't the protected part of a course; the expression is. So the app should hold structured rule definitions, never bulk copies of course text or video. Single-user and private keeps this uncomplicated, but the schema should be built to store rules, not transcripts, regardless.

## Open

- ~~Confirm the exact handles before ingesting~~ — done; the handle is `@nanalyzetweets`, in the second batch of `research/x_pull.js`.
- Which of these do you actually act on versus just read? The ones you *trade* should be encoded first.
