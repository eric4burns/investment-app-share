# Improvement Plan
_Created 2026-09-02 from the notes in `~/Desktop/investment app.pages`, a read of every module those notes touch, and the live figures the running app was showing that evening. This is the working list; `06_feature_roadmap.md` stays the record of what is built._

The notes were short. The problems underneath them are not, and most of them share three root causes. Fixing those three is most of this plan; the rest is the screen-by-screen list.

---

## The three root causes

### 1. The app argues with itself about what a falling stock is

The verdict engine (`verdicts.py`) is a **trend-following** reader: below the cloud, below the moving averages, lower highs and lower lows — that is a sell. The DCA ladder on the Holdings tab (`frameworks.py`, from RonnieV) is a **buy-into-weakness** reader: Williams %R at the floor is a 4x buy. Both are shown for the same name on the same day with nothing reconciling them.

That is the "3 or 4x DCC zone but listed as a sell" note, and on 2026-09-02 it was literal:

| Name | DCA tier | Daily verdict | Weekly | Monthly |
|---|---|---|---|---|
| DGXX | 4x purple | sell on Sep 1, hold on Sep 2 | add | add |
| SIVEF | 4x purple | sell on Sep 1, hold on Sep 2 | hold | — |
| IREN | 2x amber | sell | sell | add |

The user's own reading in the notes is the right one: *"just because a stock is down a good amount doesn't mean it can't be a good trade — below the moving averages and cloud but could be close to a bottom."* The engine has no concept of a base or a washout. Every bearish structural fact scores as "sell", and nothing in it can say "trend broken, but this is where accumulation happens".

### 2. The price history came from one exchange, not the tape

*Corrected 2026-09-02.* The first draft of this said the bars were not split-adjusted. That was wrong — Alpaca is fetched with adjustment on, and the app already reconciles fills against adjusted bars. The real defect was the **feed**: every daily bar came from IEX, which is one exchange. On thin names it saw a few shares a day, and on days it saw none Alpaca emitted a placeholder bar — zero volume, one flat price. ASST in April 2023 flickered between real prints near 94 and placeholders at exactly 170.50 for a month, while the consolidated tape traded 85 to 122 on hundreds of shares.

The free plan serves the consolidated (SIP) feed for anything older than fifteen minutes. The cache was rebuilt from it the same day: 191 symbols, 5,334 placeholder bars removed, and 71 of 483 verdict readings changed. The before-and-after record is `research/audits/refeed-2026-09-02.md`.

What did **not** change is the ASST risk finding. It reads "36% of the risk on 6% of the money" on both feeds, because the risk window runs from June 2024 and ASST went from 12 to 154 in one week of May 2025 — a real move, five months before the position was opened. Over the period actually held its volatility is 114%, not 800%. That is root cause 3 wearing different clothes, and Phase 1's Diagnose wording has to say which window a risk figure was measured over.

### 3. "Given back" is measured from a peak you never owned

`risk.position_moves` takes the highest close in the whole cached history. AEVA's peak is 99.40 on **2021-02-10**; it was bought 2026-06-16. ASST's is 2023; bought 2026. The number the notes actually want is the one the SIVE example spells out: at the 2026-06-17 high of 10.49 the position was up **+656% on cost** on the app's own basis (an earlier draft said 797%, from a cost figure that was not the ledger's); today it is +104%, and the difference on the shares held is $84,260. That is the give-back — in percent on cost and in dollars — measured only from the day the first lot was bought.

---

## Phase 0 — Fix the data (first, one session) — **done 2026-09-02**

Nothing built on top is worth reading until this is done. What was actually done, against the list as first written:

- Item 1 became the feed switch above rather than split adjustment. The newest bar in a fetch is now replaced instead of frozen, which had been silently keeping a mid-session print as the close.
- Item 2: the audit ran and is in `logs/`. The fifteen daily verdicts recorded on 2026-09-01 were re-scored on the new bars (same date, same information set, only the data corrected) rather than flagged.
- Item 3: placeholder bars are refused at the source; a test proves it.
- Item 4: give-back is measured from the first open lot, three ways, with the all-history high kept apart. The Overview attention list ranks by dollars actually handed back.

The original list, kept for the record:

1. **Split-adjusted bars.** Request adjusted bars from Alpaca, refetch every held and watched name, keep the raw series for reconciling against Fidelity share counts. Regression test: a synthetic series with a 1:10 reverse split must produce one continuous curve.
2. **Backward audit.** Re-run diagnose, risk and the verdict engine on the adjusted bars and print every finding and recorded verdict that changed. Those rows in `decisions` get flagged so calibration never grades them.
3. **Bad-print filter.** A close that jumps more than N× and returns the next bar, with no volume behind it, is a bad print. Report it rather than use it.
4. **Give-back since entry.** Peak measured from `oldest_lot`, reported three ways: price from peak, gain on cost at peak versus now, and dollars handed back. Keep the all-history 52-week high as a separate column, labelled.

## Phase 1 — Make every screen say what it means (two sessions) — **done 2026-09-02**

Every item below shipped the same evening as Phase 0, each verified in the running app and by the browser test. Three things came out differently from the list:

- The Risk tab was not renamed; that waits for Phase 5, where its per-position half moves to Positions.
- Theme rotation needed funds, so thirteen were picked by hand (`themes.THEME_ETFS`) and each was confirmed served by Alpaca. The fit of a fund to a theme is a judgement and is labelled as one on the page.
- Two defects found on the way were fixed in passing: the Diagnose drawdown finding's market-versus-selection split had been beta times zero for as long as it existed, because the metrics never carried a market drawdown; and the Overview's day change first read a day stale because it took its calendar from the FRED index, which publishes a day late.

The list as first written:

The quick fixes from the notes, screen by screen. Each is a small change; together they are most of what makes the app feel finished.

**Overview**
- "Prices to 2026-09-02, last nightly run 18:30" at the top, and a warning when the nightly run has not happened.
- Next to Value: the change over the last trading day, in dollars and percent.
- Time-weighted return also stated in dollars: end value minus start value minus net deposits. Say plainly that TWR is the return your picks made regardless of when money went in, and that the dollar figure is what that return was worth.

**Outlook**
- A flip level always reads with the current price and the direction: *HOLD at 23.31 → becomes SELL on a close below 20.97 (−10%)*. Never a bare "flips at".
- "Caps rallies at 4.56" becomes a checked claim: how many times in this name's own history did price reach the cloud from below and fail, and how many times did it go straight through. DGXX's chart says it went through, so the sentence should say that.
- Broken trendlines are currently discarded (`structure.trendlines`). A resistance line that price closed above becomes a support line; keep it, flip its role, and show it as *prior breakout line, now support at X*. This is the missing line on the DGXX chart.

**Diagnose**
- Every finding gets a one-line "why this matters" and a "what you could do about it" — the ASST risk finding should say "this position moves about 5× as much as the rest of the book, so a 10% move in it costs you as much as a 2% move in everything else".
- Concentration appears here **only**; it leaves the Risk tab.
- The tab's real job is the portfolio-level page. Once Risk gives up its portfolio panels (Phase 5), this is where they live.

**Risk**
- Rename to what it is about: what each **position** is doing.
- Exit-rule table: plain column names with one sentence under each — *Helped: how often the rule got out above where the position sits today. Median: by how much. Fires immediately: greyed because the rule triggered at its first legal bar, so it is measuring the market, not the rule.*
- Correlation heat map: a proper diverging palette with distinct steps (deep red, red, pale, pale blue, blue) and the number always printed, rather than one red at varying transparency.

**Sectors**
- Themes become the primary table; the eleven SIC sectors become the secondary one. The themes already exist (`themes.py` has space, quantum, nuclear, fintech, autonomy, digital assets…) but the page leads with SIC, which is why AEVA shows as "Consumer Discretionary" (SIC 3714, motor vehicle parts). Override AEVA to Technology and tag it autonomy.
- Rotation by theme, not only by SPDR sector: a research pass to pick one liquid ETF per theme (space, quantum, nuclear, semis, crypto, fintech…) so "is space leading" is answerable the same way "is energy leading" is now. Zero cost; the ETFs are just more price series.
- Condense: one table with theme, weight, held names, and 1M/3M/6M relative strength on the same row. Two panels instead of three.

**Backtest**
- Rewrite the top of the page as a worked example in plain words: *"Pretend it is 2021-01-01. Score every name on what was known that day. Buy the ones that pass. Next month, do it again. This is what that would have earned, against just buying SPY, and against running the same rule on sector ETFs that could not have been cherry-picked."*
- Show a default result on load (the last run, cached) so the tab is never blank.
- The Phase 3 replay makes this tab about the app's own calls, which is the version that will actually be understood.

## Phase 2 — Teach the engine what a bottom looks like (three to four sessions)

This is the answer to root cause 1 and to the last paragraph of the notes.

**Measured first (overnight 2026-09-02 → 03, `research/audits/measure-2026-09-02-summary.md`).** With the universe's drift removed and errors clustered by date: on daily calls no evidence item carries information. On weekly calls, weights *measured* from the record order the calls out of sample under three different split dates (top fifth +1.2 to +2.4 points, bottom fifth negative) while the engine's hand-assigned confidence orders them backwards. The weekly Fibonacci retracement reading is inverted with t −4.3 — the strongest number found. Consequences, in order: turn off or invert the weekly Fibonacci item and re-run the replay (one line, one decision for you); build weekly confidence from measured weights, which `python3 -m app.measure --save` now stores and the Outlook table shows as a "Measured" column beside each call; add new evidence types on the weekly first, where there is a signal to measure them against. Nothing in the engine was changed overnight. A second pass with RonnieV's moving-average rules carried at zero weight (`research/audits/measure-2026-09-03-update.md`) found the same inversion on every weekly trend item — a weekly death cross is followed by outperformance at t 4.4, a golden cross by underperformance — which is either genuine mean reversion at the weekly scale or the shape of a list assembled from names that went up. The discovery screen now stores a point-in-time universe nobody chose with hindsight; replaying the engine on it, once a few weeks of screens exist, is the test that settles which.

**Decided and done 2026-09-03:** the weekly Fibonacci retracement reading is off (option A). The replay re-run confirms it removed the inverted calls and nothing more: weekly buy and add no longer fire at all, because they were anchored to that level; weekly sells and confidence still carry nothing; the measured ordering still holds (`research/audits/measure-2026-09-03-after-fib-off.md`). Position books are in: IREN and DGXX conviction, IREN traded around, the rest swing, and the conviction book never gets a sell call. **Measured 2026-09-03, six candidates** (`research/audits/measure-2026-09-03-candidates.md`): absorption, volume commitment, on-balance volume, candlesticks at a level, Gann fractions, double bottoms and tops. None earns a weight; the volume readings carry nothing, and the level-based ones repeat the weekly inversion. All stay at zero weight as context. The measurement loop is the way every future item goes in.

**Measured 2026-09-03, relative strength** (`research/audits/measure-2026-09-03-relative-strength.md`): the top fifth of the list outperforms in the direction claimed (t 2.5) but the bottom fifth outperforms by more — both ends beat the middle, the survivorship signature again. No weight; stays as context. The exposure dial (`app/regime.py`) was measured by the day's mean excess, the only test a date-level item can pass (`research/audits/measure-2026-09-03-regime.md`): clear-skies weeks were followed by the smallest excess and windy weeks by the largest, so no weight; context only. Every candidate the transcripts and the plan named has now been through the loop, and the record's verdict is that nothing in the standard toolkit measures on this universe beyond the measured-weight ordering.

**The decisive test, 2026-09-03 (`research/audits/measure-2026-09-03-screen-universe.md`):** the engine replayed on 500 names drawn at random from the liquidity screen — chosen for trading enough, not for having gone up — since 2023, 150,072 calls. The weekly inversion is there too, at the same strength: Fibonacci bull −2.27 (t −3.6), moving averages bull −1.21 (t −3.0), death cross +6.49 (t 4.3). It is the market's behaviour at a one-month horizon, not the watchlist's survivorship. The measured-weight ordering does not travel to the broad universe out of sample (top fifth fails), so the live measured confidence is calibrated to the watchlist and is a thin edge. One item measures the right way at t 3.6: daily relative strength, top fifth of the universe. Decisions pending: the remaining weekly trend items (off, or inverted), and a weight for daily relative strength once the point-in-time universe confirms it.

**Decision A, 2026-09-03.** The weekly trend items — the pivot sequence, the cloud, tenkan/kijun and the moving averages — are switched off, as the Fibonacci retracement was. They are still recorded at zero weight so the measurement continues, and on the weekly the call itself now comes from the measured score: top fifth of the replayed record with a level below price is a buy (add if held), bottom fifth is a sell (a hold on the conviction book), everything between is a hold. Levels the market has turned at keep their weight and supply the stop. The watchlist replay was re-run under the new rule (`research/audits/replay-2026-09-03-trend-off.log`) so the calibration and the measured cuts reflect the engine as it now runs. The paper book's first two orders (PATH, DJT, market-on-open) expired unfilled at the 2026-09-03 open — Alpaca's paper venue does not reliably fill on-open orders — so the paper book now places plain day market orders after the close, which queue for the next open. Re-measured under the new rule (`research/audits/measure-2026-09-03-trend-off.md`): out of sample the weekly buy now reads +4.61 points against the same-day average and the weekly sell −2.11 — the right way round, where the trend-item weekly had read the wrong way — with the caveat that the live cuts were fitted on the whole record. The measured staircase itself is unchanged (bottom fifth −1.58, top +1.82).

**From the user's own charts, 2026-09-03.** Eleven TradingView charts reviewed together. Their horizontal shelves are the evidence-backed part of their method, so sixteen of them (ASST, IREN, DGXX, SIVEF, CRDO, SMR, TEM, SOFI) are loaded as level drawings and the nightly and 15-minute alerts now fire when price reaches or closes through one (`alerts.user_levels`, `alerts.from_levels`). Three engine changes came out of the discussion: a weekly sell at high confidence now takes the headline from a monthly add or hold (CRDO); a `gap` item — a gap on twice average volume held into the close — is recorded at zero weight for the replay to measure (the user sold CRDO on exactly that); and a failed or empty price fetch now holds off the retry for twenty minutes instead of six hours, after SIVEF's OTC series sat four sessions behind. What looked like an unflipped shelf on TEM was the previous day's close sitting under the zone, not a flip bug.

**Same evening, three more from the user.** (1) Engine shelves for the holdings without hand-drawn levels — the three strongest zones each on AEVA, BMNR, CRWV, KRKNF, LASR, MP and MSTR, drawn in blue to tell them from the user's own — so every holding now has level alerts. (2) Coverage: `memory` and `defense-drones` themes added (ITA is the defence fund; memory has no fund of its own), nuclear-power and photonics widened, and 27 names and theme funds added to the watchlist for tracking exposure the book does not have — MU, WDC, STX; CEG, TLN, GEV, NRG, BWXT, CCJ, NNE; COHR, FN, CIEN, POET; ALAB, ANET; AVAV, RCAT; HUT; BKSY; GRID, DTCR, ARKX, URA, ITA, SOXX, XLU. (3) The indices: `regime.index_read` reads SPY, QQQ and IWM against their 50- and 200-day averages and the S&P sets a state — *against* below its 200-day or a falling 50-day, *with* above a rising stack, *neutral* between. Recorded on every call at zero weight as the `index` item, shown on the Outlook tab beside the exposure dial, and while *against* every buy and add is marked down one notch of confidence (`INDEX_GATE`) — a mark-down, not a veto, until the replay measures it. The state deliberately does not use the engine's measured fifth on the index: that profile was fitted on stocks and reads an index at its highs as a sell, which is the inversion, not a warning. Level alerts now carry a detail — which way the level faces, the app's daily and weekly call with its reason, the next levels either side and the stop — sent in the phone notification's body and expandable by clicking the row on the Alerts tab. Measured the same night (`research/audits/measure-2026-09-03-index.md`): when the S&P was breaking, the watchlist names still rose over the next month and quarter on average, but by less (+3.5% against +3.9% at 21 days; +8.9% against +11.7% at 63) and fell in 45% of those weeks against 34% — the shape of a mark-down, not a veto, so the one-notch rule stays. The weekly gap-down-on-volume item read −14 points at 63 days (t −5.0, small sample), the user's CRDO rule measuring the right way.

**From the charts the user saved from X, 2026-09-04** (`research/charts-2026-09-03-x-accounts.md`). Thirteen screenshots of charts by accounts they follow — The Analyst, Freedom By 40, Mind Investor, Con, SteveUrkeldude, AsafNaaman15, RonnieV — read for what is drawn and why. Seven items went into the engine at zero weight so the replay measures them before any can move a call: `reversal zone` (a pullback holding at 0.786–0.887 of its own leg, the band three of these accounts buy), `target` (the next 1.272 / 1.414 / 1.618 extension above price, capped at double the price), `role flip` (a level whose latest touch came from the other side — Con's "previous support is now resistance," and the breakout-and-retest the user's TEM shelf showed), `phase` (accumulation or distribution forming, from the pivot labels, only while price is still inside the range), `channel floor` / `channel ceiling` (price at an edge, with the rally or fade after each earlier touch — the AEVA chart's "+95%, +158%, +110%"), `rsi divergence` (structure on the oscillator, the fourth source in this project to draw it), and `volume profile` (volume by price; thin air above a heavy node, or below one). The Williams %R item now carries the best gain after each earlier floor hit, which is RonnieV's SMH argument made per name. This covers items 1 (the basing lens: phase, reversal zone, divergence), 5 (volume profile) and part of 4 of the list below. Not done: Elliott counts (a judgement, not a computation) and pattern weights from a reported table. **Second pass the same day:** the volume profile is drawn on the chart; the reversal zone and targets are on the Fibonacci overlay and feed the trim level; head and shoulders, triple tops and bottoms, triangles and wedges are detected from the existing pivots and trendlines at zero weight (item 4 of the list below, flags excepted); the followed accounts' calls are journaled under an `outside` source and graded like the app's own; and the mortgage-rate chart is a macro series on the Research tab. **Measured the same day** on the watchlist replay (`research/audits/measure-2026-09-04-x-charts-*.md`): weekly RSI divergence reads the right way in both directions (bull +4.29 at 63 days, t 3.5; bear −2.38, t −3.1), distribution forming is followed by underperformance (−8.38, t −5.9), and the two level readings — the reversal zone and the role flip — invert on the weekly like every level item before them (role flip bull −5.95, t −6.1). Nothing on the daily reaches t 2. No weights changed; the screen-universe replay decides. The pattern items were measured on a second replay the same morning (`research/audits/measure-2026-09-04-patterns-*.md`): head and shoulders in both directions, both wedges and the confirmed triple top read the right way on the weekly (triple top −11.87 at 63 days, t −4.9; falling wedge +8.22, t 2.4; inverted head and shoulders +2.55 at 21 days, t 2.4), the triangles read weakly the wrong way, and the triple bottom inverts. The falling wedge is the first daily item to reach t 2 the right way (+2.80, t 2.6). Still no weights: the screen universe decides. **Later the same morning:** `measure.pairs` — for every pair of items that fire together on enough calls and dates, the residual of calls carrying both against the sum of what each measures alone, with both "alone" baselines held to the same date-count bar as any item (`research/audits/measure-2026-09-04-pairs-*.md`). This is the first answer to "how do the variables work together": on the weekly at a quarter, bearish trend readings that agree with each other (the cloud below with lower highs and lows; a death cross with a Fibonacci ceiling) are followed by MORE outperformance than either alone — the washed-out lens of Phase 2 item 1, measured — while a confirmed bearish double top with anything else is followed by underperformance beyond the sum. The screen-universe replay for the new items ran the same morning (`research/audits/measure-screen-2026-09-04-*.md`, 153,183 calls): what survives away from the watchlist is the completed bearish structures — rising wedge (−5.39 at 63 days, t −3.3), distribution forming (−5.28, t −3.3), confirmed triple top (−3.81, t −2.8), confirmed head and shoulders and bearish RSI divergence at a month (t −2.7 each). Bullish RSI divergence, the watchlist's strongest item, does not travel; the reversal zone inverts in both directions; the triple bottom and ascending triangle invert. The pattern matches the relative-strength finding from the other side: in a broad universe, weakness continues at a month and a quarter. Still no weights — the point-in-time universe is the fourth gate (the four gates are decision D48). **Storage, the same day (D49):** the database was 1.2 GB because replayed evidence rows carried prose; replays now store name, stance and weight only, the existing rows were cleared and the file vacuumed, and `tests/test_size.py` budgets every file kind, the database, the logs, the audits and the backups, and fails on duplicate files. The repository was tidied: a stray debug script removed, the March research PDF moved under `research/`, stale fetch logs and a duplicated refeed note deleted, thirty empty WAL sidecars left by `backup.sh` beside its snapshots removed and the script fixed to not leave them. The browser smoke suite's seven standing failures were the test's own assumptions: it expected the chart symbol to start with nothing drawn (the copied ledger has the user's shelf levels since 2026-09-03), and it waited for figures in the backtest cards, which a stored run already shows, so it read the Run button mid-run. The test now clears its symbol's drawings on the throwaway copy and waits for the button itself; 96 of 96. Two unrelated fixes from the user's morning notes: the Diagnose tab's "Drawdown now" sampled every seventh day and disagreed with the Risk tab's daily figure for the same period (a copy of the defect `web.value_series` had already fixed), now the same weekday grid and the same number; and a Panes control on the chart (Small / Normal / Large) so oscillator panes stop taking half the screen, small by default on a phone.

**Done 2026-09-03:** weekly confidence is now the fifth of the record a call's measured score falls in (top fifth for a buy, add or hold; bottom for a sell or trim), and a weekly buy or add fires only from the top fifth. The engine's own label is kept beside it. Position books are applied. Daily and monthly unchanged; the next measurement pass tells whether the weekly now orders outcomes live.


1. **Two lenses, stated.** Every verdict names the regime it read the chart under: *trending* (cloud, moving averages, pivot sequence decide) or *basing / washed out* (distance from the 200-day, Williams %R and RSI at the floor, volume climax, a higher low on the daily inside a weekly downtrend, a base forming under a broken trendline). A name in a washout cannot read "sell"; it reads *"trend broken; accumulation zone — DCA on schedule, wrong below X"*. The DCA tier and the verdict then agree by construction.
2. **Risk against reward as a first-class input**, not a tiebreak. Distance to the next real level above against distance to the stop below decides whether a *buy* is worth taking at all, and is shown on every call.
3. **Candlestick evidence.** Engulfing, hammer, doji and shooting star, but only **at a level** — a hammer in the middle of nowhere is noise. Weighted like the other evidence, with attribution (Nison).
4. **Chart patterns.** Double bottom, cup and handle, bull flag, falling wedge, head and shoulders, detected from the pivots `structure.py` already finds. Bulkowski's pattern statistics give a measured success rate per pattern, which is what the weight should be — not a guess.
5. **Volume evidence.** OBV trend agreeing or disagreeing with price, breakout volume against the 50-day average, climax volume at a low. OBV is already computed and thrown away.
6. **Timeframe fit per method.** The note that "an SMA is good for swing trading but doesn't apply to one of my positions" is right: each encoded method already declares a timeframe; the verdict should say which of your positions are swing trades and which are holds, and apply the swing rules only to the swing book. That is Dr J Rould's three-buckets framework, already encoded and not yet wired to anything.

Each addition goes through the same test discipline the engine has now: a mutation check that the new evidence can actually change a verdict, and a lookahead test.

## Phase 3 — Prove it before trusting it (two to three sessions)

1. **Verdict replay** — *built and running 2026-09-02 (`app/replay.py`; the report is on the Outlook tab).* Run the verdict engine at every week-end from 2022 to today on every held and watched name, grade each call against SPY at 21 and 63 trading days, exactly as `journal.py` grades live calls. Calibration then has thousands of graded calls **today** instead of twenty in mid-October, and it can say which evidence items help and which hurt — before Phase 2 tunes any of them. This is also the version of "backtest" the notes will understand: *did the app's own calls work?*
   **What the replay found (2026-09-02, 78,616 calls, `research/audits/replay-2026-09-02.md`).** Stated with the replay's caveats in force — no position, no sentiment, today's watchlist as the universe — and across both the 21-day and 63-day horizons, which agree:

   | 21 trading days | Calls | Hit rate | Against SPY |
   |---|---|---|---|
   | buy | 13,947 | 44.5% | +1.56 pts |
   | hold | 46,610 | 46.8% | +2.52 pts |
   | sell | 16,374 | 54.0% | −2.78 pts |

   - **The engine has no measurable edge beyond the drift of its own universe.** "Hold" is the baseline: it is what every name did on average, +2.5 points over SPY per month, because the watchlist is a list of names that went up. A *buy* did worse than that baseline. The names it said *sell* went on to do about the baseline too, so a sell carried no information either. At 63 days the shape is identical (buy +7.2, hold +8.2, sell −10.6).
   - **Confidence is not ordered.** High-confidence calls scored +0.9 points, low-confidence +2.0. The evidence weights, all assigned by hand, are measuring something other than reliability. The calibration tool flags this as the first thing to fix, and it is right.
   - **On this universe, momentum beat mean reversion.** RSI overbought was the single most helpful condition (+3.0 points; names that were extended kept outperforming) and RSI oversold was among the least helpful (−1.7; washed-out names kept underperforming). Every trend-following bullish item helped and every bearish item hurt, which is what a rising universe of high-beta names produces whether or not the items mean anything.
   - **Calls with a flip level scored worse than calls without one** — which is buys and sells scoring worse than holds, restated.

   Confidence in this: moderate. The direction is consistent across horizons and tens of thousands of calls, but the universe's own survivorship inflates every long reading and penalises every sell, and the replay cannot say how much. What it can say is that Phase 2 should not start by adding more evidence types to a weighting scheme that does not discriminate. It should start by measuring each candidate item against the hold baseline on this record and keeping only what beats it, then rebuilding confidence from measured hit rates. The replay is the instrument for that, and it re-runs in half an hour.

2. **Alpaca paper trading** — *built and started 2026-09-03 (`app/paper.py`; the Backtest tab shows the book against SPY).* The first two orders, PATH and DJT, went in as market-on-open for that day's session; the nightly job places the rest. **Original description:** `SETUP.md` has the credentials coming from a free paper account, and that key pair is what `paper-api.alpaca.markets` accepts. A `paper.py` module submits the nightly verdicts as orders to the paper account after the close, and reads positions and P/L back. A Paper tab shows the paper book against SPY and against the real book. Alpaca's own documentation says several paper accounts can be created and deleted from the dashboard, each with its own keys, so each strategy worth forward-testing can have its own paper book. What runs there is the app's **own blended engine** — not any single analyst's method (decided 2026-09-02, see below). Each strategy gets a forward record nobody can backfill.
3. **Your trades against the app's.** `journal.py` already has 958 of your trades graded. Put the comparison on the Outlook tab: over the same names and dates, did the app's call or your decision do better. Blunt, and the single most useful number the app can produce.

## Phase 4 — Research programme (in parallel, ongoing)

The notes are right that this has been thin. Zero-cost first, in this order:

1. **YouTube transcripts** of Cantonese Cat and both RonnieV channels, using `research/fetch_transcripts.py` which already exists. Every stated rule becomes an encoded condition with a quote and a confidence level, as the Method Library does now.
2. **Books.** Drop PDFs or EPUBs into `research/books/` (gitignored) and they get read and mined for rules the same way. Suggested list, cheapest and most encodable first:
   - Weinstein, *Secrets for Profiting in Bull and Bear Markets* — stage analysis; directly answers "is this a dip or a decline", which is the Phase 2 question.
   - Bulkowski, *Encyclopedia of Chart Patterns* — measured success rates per pattern; the only pattern book with numbers.
   - Nison, *Japanese Candlestick Charting Techniques* — the candlestick reference.
   - Elder, *Trading for a Living* — the triple-screen method, which is the daily/weekly/monthly design this app already has.
   - Murphy, *Technical Analysis of the Financial Markets* — the general reference.
   - Minervini, *Trade Like a Stock Market Wizard* and O'Neil, *How to Make Money in Stocks* — bases, VCP, and the swing-trade rules.
   - Van Tharp, *Trade Your Way to Financial Freedom* — position sizing and R-multiples, which is what "weigh risk vs reward" turns into in code.
3. **Newsletters.** StonkChris's Substack, done 2026-09-04: pulled in full through the logged-in tab, kept local (D50), mined into `research/substack-notes-2026-09-04.md`, his levels graded against controls (D51). The same receiver works for any other Substack the user subscribes to.
4. **The Cantonese Cat course.** `05_method_sources.md` already set the rule: encode the free material, run it through the Phase 3 replay, and let that result decide whether the course is worth buying. Nothing in this plan changes that.

## Phase 5 — Fewer tabs (one session, after Phases 1 and 2)

*Superseded 2026-09-12 by the review in `research/audits/app-review-2026-09-12.md`.*
The first shape below was seven tabs named for modules (Positions, Book…).
The review's inventory found that the daily questions cut across those, and
that the same levels and verdicts were being drawn on six surfaces. The
shape that came out of it is named for the question and puts every
per-name thing on one symbol page:

| Section | Sub-tabs |
|---|---|
| Today | What to do (one ranked list: alerts, tomorrow's buys, worth a look, the diagnose findings) · Market · All alerts |
| My Money | Overview · Holdings · Trades · Risk · Sectors — the Period/Scope bar lives here only |
| Stocks | Holdings calls · Watchlist · Setups · Buy back · New Stocks |
| Who I Follow | Their calls, graded · Their charts · Their methods · Record a call |
| AI Trade Bot | Paper account · Its record · Backtest |
| Chart | the symbol page — Chart · The read · Plan & levels · Who I follow on it · My trades — opened from any name anywhere |
| Budget | unchanged |

Phone: a bottom bar of Today · Money · Stocks · Budget · More. It shipped
with the design system in the same review (TradingView register; the
user's own marks privileged over the app's). **Done 2026-09-13 (D117)** in
four commits; the old→new mapping of every section is in
`research/audits/phase2-spec-2026-09-13.md`.

The first proposal, kept for the record:

| Tab | Holds |
|---|---|
| Overview | value, day change, TWR in $ and %, net worth, "worth a look" |
| Positions | today's Holdings plus the per-position half of Risk (give-back, exit rules, DCA tier) |
| Outlook | as now, with the replay scorecard and your-trades-versus-the-app |
| Book | Diagnose plus the portfolio half of Risk (drawdown, ratios, concentration, correlation) plus Sectors |
| Chart | as now, with controls collapsed by default |
| Research | Methods, Research, Backtest and Paper as sub-tabs |
| Budget | as now |

---

## Decisions taken 2026-09-02

1. **The book is three books.** Swing trades read off the chart; DCA into names with conviction; and *trading around a core* in volatile names — IREN was the example — selling a slice when a fall is likely and buying it back lower so the share count grows. Every position carries a bucket tag, and the verdict applies that bucket's rules. This adds a bucket to Dr J Rould's three, and it is the user's own.
2. **No single analyst's method is traded.** The encoded methods are incomplete — several rest on proprietary indicators — and none is personal. What gets paper-traded and eventually trusted is the app's own blend, tuned on the user's names. Individual methods stay as sources of evidence and as comparisons.
3. **Books.** Question 3 was only asking whether any of the listed books are already on the shelf, because a PDF or EPUB dropped into `research/books/` can be read and mined for rules. None are assumed owned; the free sources below come first.

## How the information actually gets gathered

The honest state on 2026-09-02: the app encodes about twenty indicators and the structure engine, and the analyst material on disk is eight Cantonese Cat transcripts, three from The RonnieV Show and none from Ronnie V Trades. Nothing has been checked against a reference, and no weight in the verdict engine was measured — every weight is a judgement. So "have you researched all the indicators and patterns" has a plain answer: no. The standard canon is known; it has not been applied systematically here.

The method, cheapest first, is definitions from references and weights from measurement — never weights from anyone's opinion, including this app's.

1. **Definitions from two free references.** StockCharts ChartSchool for every indicator and overlay (settings, what it measures, standard readings), and Bulkowski's ThePatternSite for chart and candlestick patterns, which carries his measured failure rates and average moves after breakout for free. Each item gets a one-page entry in a new `08_indicator_catalogue.md`: what it measures, the timeframe it suits, the standard reading, the source, and — once Phase 3 runs — what it measured on this book.
2. **Transcripts, finished.** Pull the remaining Cantonese Cat and both RonnieV channels, and mine every stated rule into a condition with a quote and a confidence level, as now.
3. **Measure, then weight.** The Phase 3 replay grades every evidence item on the user's own names over four years. An item that does not predict anything on this universe gets weight zero regardless of who recommends it; one that does gets a weight from its measured hit rate. This is the step that turns "what others do" into "what works here".
4. **Books last, if at all.** Only where the free references and the replay leave a gap that a book plainly fills.

## What other apps have that this one does not

Checked 2026-09-02 against current reviews of TrendSpider, TradingView, the portfolio trackers (Delta, Empower, Stock Events) and the trade journals (Edgewonk, TraderSync, Tradervue). The pattern is consistent: the commercial tools win on **acting for you while you are away**, on **event awareness**, and on **discovery beyond your own list**. Everything below is zero-cost to add.

| Everyone has it | This app | Add as |
|---|---|---|
| **Alerts to the phone** — TrendSpider's move with the trendline; TradingView's fire on any condition | none; the nightly run prints to a log | A1 |
| **Earnings dates** on the chart and in every call | none; a verdict two days before earnings says nothing about it | A2 |
| **Pattern recognition** — TradingView 48 candlesticks free; TrendSpider patterns and up to 2,000 trendlines | pivots, trendlines, zones, Fibonacci; no patterns | Phase 2 |
| **Screener / discovery** across the whole market | scanner runs only on the 145-name watchlist | A3 |
| **Relative-strength rank** of one name against all others | sector rotation only | A4 |
| **Bar replay** — step through history to train the eye | none | A5 |
| **Journal with the why** — Edgewonk's edge finder, mistake tags, session report cards | calls are recorded; no reason, no tag, no mistake field | A6 |
| **Insider and congressional buying**, short interest | none (congressional was on the old roadmap) | A7 |
| **Backtest to bot** — TrendSpider converts a tested strategy into automation | backtest only | Phase 3 paper |
| **AI chart read** — TradingView Chart Copilot, TrendSpider Sidekick | this session, by hand | out of scope; the engine is the point |

### Phase A — Act while you are away, know what is coming (two sessions, slots after Phase 1)

*Progress, overnight 2026-09-02 → 03:* A1 alerts (nightly and a 15-minute intraday poll, ntfy and macOS channels, Overview log) — **done**; A2 earnings dates (Nasdaq's undocumented calendar, ~8 weeks ahead, refreshed nightly) — **done**; A4 relative-strength rank — **done**; A6 journal bucket, reason and outcome tags with calibration slices — **done**; A7 insider buying from EDGAR Form 4 — **done**, two years synced. A3 discovery (a weekly liquidity screen of every plain NASDAQ and NYSE name, a nightly scan of the methods across what survives, a panel on the Watchlist tab) — **done**; A5 bar replay on the Chart tab — **done**. Phase A is complete. The phone channel needs one step from you: install ntfy, subscribe to a topic, put it in `config.json` (SETUP.md has the five steps).


- **A1 Alerts.** A free push channel (ntfy or similar — to be verified before use) from the Mac to the phone. Fired by: a verdict change, price crossing a flip level, a buy-at or stop level reached, the DCA tier changing, and earnings inside five days. An intraday poll during market hours against Alpaca, which the free plan allows.
- **A2 Earnings calendar.** A free source to be verified (Finnhub's free tier or the SEC's own filings index); date on every chart, every verdict, and every alert.
- **A3 Discovery.** Run the scanner across every US name above a dollar-volume floor, from Alpaca's free assets list, and surface what qualifies that is not on the watchlist.
- **A4 Relative-strength rank.** Each name's return against every other watched name over 3, 6 and 12 months, percentile-ranked. Cheap, and the single input the momentum literature agrees on.
- **A5 Bar replay.** The chart at any past date, with the verdict the engine would have given that day. Doubles as the way to audit the Phase 3 replay by eye.
- **A6 Journal, the human half.** On every decision: the bucket, the reason in one line, and a tag on close (followed the plan, chased, held through the stop, sized wrong). Calibration then slices by tag — the edge finder, on your own record.
- **A7 Insider buying** from EDGAR Form 4 (free, keyless, already the sector source), short interest from FINRA, congressional trades. All as chart markers and evidence items, weighted by measurement like everything else.
- **A8 Statements without the download ritual.** Asked 2026-09-02: can the Fidelity, Frost and card imports be automated? Three routes, none free of a trade-off:
  1. **SimpleFIN Bridge** — an aggregator built for personal-finance apps, read-only, $1.50 a month or $15 a year, up to 25 institutions. Its institution list includes Fidelity, and the app would poll it nightly for new transactions. The one thing to confirm before paying: whether a brokerage connection returns transactions or only balances.
  2. **Plaid's trial plan** — free for accounts created after 2026-04-15, up to ten live connections, which covers Fidelity, Frost and four cards with room to spare. More code than SimpleFIN (a developer account, a Link flow, token handling) for the same result, but $0.
  3. **A browser script per institution** — Playwright is already installed for the smoke test; a script that logs in and downloads the same CSV you download by hand costs nothing and breaks whenever a site changes or asks for a code. Fidelity's two-factor prompt is the reason this is the fallback, not the plan.
  Recommendation: try SimpleFIN first, because it is the only one that was designed for exactly this and the cost is a coffee a year. Keep the hand-import path working regardless; every importer stays idempotent so the two can overlap.

### Phase B — Trading around a core (one to two sessions, slots after Phase 2) — **done 2026-09-03**

Built on the IREN case: a core share count (default three quarters until set), the slice above it, the level to sell the slice into and a buy-back level at least 3% below that price has turned at before, the odds from IREN's own two years of reaching the lower level first, the shares gained if the trip completes, every account's lots with tax status — the whole slice fits in the Roth and HSA, so no tax and no wash-sale rule apply — and the record of past sales bought back within sixty days, in shares (November 2025: four round trips, +20 shares). All on IREN's verdict card. Today's read: sell into 42.21, buy back at 32.22, +328 shares if it completes, but from a spot like this price has reached the lower level first only 25% of the time.

The list as first written:

For the IREN case, the tools the bucket needs:

- A **core share count** per name that the engine never proposes selling, and a tradeable slice above it.
- The trim rule on the **daily** timeframe, into resistance, extension or an overbought oscillator — the existing into-strength logic — paired with a **buy-back level** below and a stated probability from the replay of price getting there before it gets to the next level up.
- **Shares gained** as the reported result of every round trip, beside the dollar figure.
- **Specific-lot selection and wash-sale detection**, because a slice sold at a gain in a taxable account realises tax and a slice sold at a loss and re-bought inside thirty days is disallowed. The ledger already builds lots; this uses them.

## Grade

Against the question the notes asked — much better and more useful — scored 1 to 10, where 10 is an app that reads the chart the way the best of these people do, tells you on your phone when it matters, and can prove it works on your own names.

| Area | Today | Plan as first written | Plan with Phases A and B |
|---|---|---|---|
| Data it stands on | 3 | 8 | 8 |
| Reads the chart | 5 | 8 | 8 |
| Knows what the book is (buckets, core, tax lots) | 3 | 5 | 8 |
| Acts while you are away | 1 | 1 | 8 |
| Knows what is coming (earnings, events) | 1 | 1 | 7 |
| Finds new names | 2 | 2 | 7 |
| Proves itself | 3 | 8 | 9 |
| Explains itself on screen | 4 | 8 | 8 |
| **Overall** | **3** | **6** | **8** |

What keeps it under 10, and is left out on purpose: options and crypto are not modelled; prices are Alpaca's free feed, not consolidated real-time; and statements still arrive by hand. Each is a known limit with a cost, not a missing idea.

## Order of work, revised

**Where it stands, 2026-09-04.** Phases 0, 1, A and B are done. Phase 2 has been through the measurement loop end to end: every candidate the plan and the transcripts named was recorded at zero weight, replayed, and measured, and the engine changed only where the record said so — the weekly trend items off and the weekly call read from the measured score (decision A), the weekly sell allowed to take the headline, the index mark-down, and three items still at zero weight that measured the right way and wait for confirmation (daily relative strength, the weekly gap-down on volume, the index state). Phase 3's replay runs on the watchlist and on the screen universe, and the paper account has been trading the weekly calls since 2026-09-03. Statements are pulled monthly through the browser (SETUP.md).

Seven readings from the user's saved X charts were added at zero weight on 2026-09-04 and have not been through the replay yet; the next `--redo` measures them.

**Where it stands, 2026-09-10.** The exit side has been re-measured and
**retired**. D69 and D71 tested the sell ladder against names it was not read
from and against the user's own exits, and it passed both; nobody had tested it
against simply holding. Against buy-and-hold over 3,613 momentum entries it
loses — 2.4% of the book, with rung 1 alone costing 8% of the mean — and so
does every other exit rule tried (trailing stops, moving-average breaks, RSI
extremes). The rungs are right about half the time and still destroy the mean,
because the half they get wrong contains every large winner. The ladder is off
(D97). What replaced the effort is discovery: the accumulation scan (D96),
which is the first thing in this app with a measured edge on the outcome that
matters — 11.5% of its names reach 4x within a year against a 1.5% base rate.
The full working is in `research/audits/edge-log.md`.

**Where it stood, 2026-09-08.** The exit side, which the notes' last paragraph was really about, is built and measured: the sell ladder (D69, D72) and the buy-back readings (D73) came out of IREN's anatomy, held up on 36 names they were not read from, and on the user's own closed trades every rung fired after the sale (D71) — the winners were sold early. Both are live on the Outlook rows with alerts. The five-evaluator review (D77–D81) and the phone pass (D85–D86) are done; the app is shareable as an app (D89, D92); buy plans with a gap rule cover the next session (D90). Phase 5 (fewer tabs) is still not done: thirteen tabs, though the Overview, Budget and Outlook consolidation took most of the sting out.

Next: let the paper book and the point-in-time universe accumulate; re-measure daily relative strength and the gap item on the point-in-time universe before giving either a weight; Phase 5 (fewer tabs) when the layout is decided; Phase 4 alongside throughout.


---

## 2026-09-12 — where this stands

The three root causes this file opened with were about the app telling the user
things it had not earned. That work is done and measured; the record is in
`research/audits/edge-log.md` and the short version is that **no mechanical rule
beat doing nothing**, the sell ladder is off, and the edge is selection in the
tail.

So the effort moved to the input side: finding names and reasoning earlier,
rather than scoring the names already in hand better. What is now automatic:

| | before | now |
|---|---|---|
| X posts | a browser console paste, weekly, when remembered | 02:10 nightly, 32 accounts, resumable |
| YouTube | a manual script run, captions only | 04:00 nightly, 7 channels, local transcription when there are no captions |
| Chart videos | unreadable | `research/video/collect.sh`, names + commentary + drawn levels |
| An author's levels | typed in by hand from a screenshot | read off the chart into `author_levels` |

**The honest limits**, because they decide what is worth doing next:

1. **YouTube confirms, it does not discover.** 140 of 206 tracked names can be
   matched by a spoken name; a name nobody has heard of has no alias at all, so
   this cannot surface something new. Cashtags in a title are the only
   discovery channel, and most channels do not use them.
2. **The crowd reading is still thin.** A handful of days of history, and the
   thresholds for early/warming/crowded are a judgement rather than a
   measurement. They cannot be tested until there are months of nightly pulls
   behind them — which is now accumulating, and was not before.
3. **Nothing reads the transcripts for meaning.** They are searched for names.
   What a person actually said about a name is in the file and in the video
   report, and nowhere in the app.

**The next thing worth doing is organisation, not more data.** The app is 15
tabs and the spread is lopsided — Budget carries 12 sections, Holdings 1, and
Chart, Watchlist and Backtest none at all. The user has twice said things are
hard to find, and the last two features both had to be given a tab of their own
to be findable. That is the symptom of a layout that has grown by appending.

**2026-09-12, later.** The review ran — six audits, in
`research/audits/app-review-2026-09-12.md` — and its Phase 1 landed the same
day (D111–D115): the Holdings percentage now agrees with the broker's
dollars, a tab that fails says so, the watchlist Outlook is served from a
nightly verdict cache instead of 48–100 s of scoring per open, the cache no
longer empties on every intraday write, writes need the page's token off
localhost, the Gmail session verifies its certificate, the replay set is in
its own file, the ledger is pruned nightly and backed up nightly. Phase 2 —
the seven sections above and the new look — is specified and waits on the go.

**2026-09-13.** Phase 2 shipped: the seven sections, the design system with
both themes and a toggle, Today as one ranked list, the symbol page behind
every name, and the chart opening on the last year with the user's marks
loudest (D117). The user's own review of the give-back column found the peak
was the highest close where the broker showed the intraday high; fixed the
same morning (D116).

**2026-09-13, evening — the first pass of living with it.** Ten items from
one read-through, all shipped the same session (D120–D124):

| what Eric said | what changed |
|---|---|
| DCA and the call disagree (DGXX 3x but hold) | Holdings showed the DAILY read; now the headline with its timeframe, like everywhere else. The DCA cell says it sizes a scheduled buy and is not a call. |
| the watchlist's sector % — at what interval? | the group header's figure is the average 1-month move of the names in it; it now says "avg 1m" and its tooltip says so |
| buy back: was my sell good? | the sale column reads "sold 06-09 at $16.41 · now 25% lower — good sell" in green, or "higher — sold early" in red |
| New Stocks has nothing useful | every row: the company, its sector and the SEC's business line, 1w/1m/3m, from the 52-week high, RS, and who among the followed accounts posted it |
| charts: filter by trader and by dates | Who I Follow → Their charts has who / symbol / from / to, over both grids |
| keep a record of their calls, going forward | the nightly X pull records calls the night they are posted (`app/xcalls.py`); a deleted post changes nothing |
| fib levels not labelled | every level is labelled ratio · price at its start |
| automate the Substack, cards, bank, Fidelity | Substack nightly at 03:30 with a stored session (`./substack-setup.sh`); the other three cannot be — no API, no cookie — and stay the monthly browser routine (D124) |
| taxes: no tax from trades, dividends, interest | the taxable account's realised gains (short/long), dividends and interest are in the floor, with the tax they add or save shown |
| "short of the floor by"? | reworded: "paid in less than the floor owes — expect to owe at least this much" |

The remaining limits: the X reading is of words, not charts, so an account
that posts images without text is invisible to it; and the Substack pull
needs the `substack.sid` cookie stored once before its first night.

**Later the same evening** (D125–D126): the exports that cannot pull
themselves — cards, bank, Fidelity, pay stubs — are asked for on Today once
they are five weeks old, weekly until the file lands; and the Recurring tab
now lists car insurance, Norton and the renters policy (it had filed the
premium as a grocery-like habit for rising, and split one product across
three descriptors), with every price each charge has billed at on the row.
Then the charts: the X pull saves every chart the followed accounts post,
by account, and Their charts puts two people's charts of the same name side
by side (D127). Reading the images stays open; the user chose pulling them
in over reading them.
