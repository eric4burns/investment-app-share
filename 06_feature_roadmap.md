# Feature Roadmap
_Created 2026-08-29. Rewritten 2026-08-31, when items 1-8 and 10 turned out to be built and the file still described them as upcoming. Brought current 2026-09-02._

Ordered so each step is usable on its own and unblocks the next. Every item is $0.

---

## Done

**Ledger + importers** — Fidelity (6 accounts), Frost, four credit cards, pay stubs, a budget sheet. 7,024 transactions, idempotent, reconciled. Import warns on a row-count shortfall, a provider export cap, and any month with no activity in a spending account.
**Performance engine** — time-weighted return, Modified Dietz, same-deposits benchmark replay. Values agree with Fidelity account by account, the totals landing **0.014% apart** — a gap fully explained by three days of price drift.
**Dashboard** — seven sections named for the question (Today · My Money · Stocks · Who I Follow · AI Trade Bot · Chart · Budget) with sub-tabs, a phone bottom bar, one symbol page opened from any name, and a TradingView-register design system in light and dark (2026-09-13, D117). Today → What to do is one ranked list; value and net-worth curves are sampled daily with a crosshair readout showing dollars, time-weighted return, and the gap against each benchmark in percentage points.
**Holdings** — positions, cost basis, unrealised P/L, per-position contribution, DCA tier coloured by RonnieV's ladder.
**Charts** — candles, 20+ indicators, structure (trendlines, channels, HH/HL, Fibonacci), hand drawings, trades marked on the chart. Daily through quarterly, plus 5-minute, 15-minute and hourly intraday with a refresh on open during market hours.
**Watchlists** — tags, computed columns, position awareness.
**Research** — SEC EDGAR and FRED, encoded setups per analyst.
**Method Library** — Cantonese Cat, RonnieV (3 setups), StonkChris (stated, from his Substack since 2026-09-04, plus a sizing-and-harvest framework). Two of the priority five are still unencoded; see below.
**Scanner and backtest** — method conditions across the watchlist, plus an exit-rule replay measuring what would have gotten out sooner. The backtest tab lists every method with its thesis, what invalidates it and what a run costs, and computes nothing until Run is pressed.
**Budgeting** — six sub-tabs, 551 categorisation rules leaving 27 of 3,247 spending rows uncategorised, card spending fully reconciled so every dollar paid to a card is itemised. The Spending sub-tab charts each category month by month over up to 25 months, per-tile scaled with a monthly average on each; a savings panel gives income minus spending per month against a real zero line, two months of this ledger being negative. Lapsed subscriptions are listed individually and can be dismissed once investigated. Since 2026-09-13 (D126) the recurring list is by brand, keeps insurance, utilities and rent as bills whatever the amount does, and shows every price each charge has billed at with the change since the first.
**Taxes** — married filing jointly, gross wages and withholding read from pay stubs rather than inferred from deposits; since 2026-09-13 the taxable account's realised gains (short and long, FIFO, wash losses added back), dividends and interest are in the floor, with the tax they add or save shown (D121).
**Stocks → Holdings calls** (the Outlook, until D117) — one verdict per name on **daily, weekly and monthly**, led by the longest timeframe that could be read; three named levels to act at; the levels drawn on the name's own page beside the reasoning. Trim fires only into strength. Where several names give the same call, a reward-against-risk score ranks them.
**Decision journal** — `journal.py` records the app's calls and your own trades, derived from the ledger, and grades both against SPY at 5, 21 and 63 trading days. `calibration.py` slices the result by action, timeframe, confidence and individual condition to say what to change, and refuses to characterise a sample under 20 calls across 10 separate days.
**Market sentiment** — CNN's fear and greed index, cached nightly. Reported every day, weighted in a verdict only below 25 or above 75.
**Goals and tax projection** — a savings goal with per-category targets from your own trailing average, and a projection of whether the year's income will cross the Roth phase-out or the next bracket. Both halves of the projection are stated as floors, because the income figure is one.
**Phone access** — Tailscale. The server listens on loopback and the tailnet only, never 0.0.0.0.

**The verdict engine, measured (2026-09-02 → 04)** — daily bars from Alpaca's consolidated feed; the engine replayed at every week-end since 2022 on the watchlist and on a 500-name random slice of the liquidity screen, and every evidence item measured against the universe's drift. The weekly call now comes from the measured record; the weekly trend readings are recorded but carry no weight. Position books (swing, conviction, trade-around) with a trade-around plan for IREN. The Alpaca paper account trades the weekly calls. Alerts to the phone: verdict changes, the app's levels and your own drawn levels with what they mean, earnings dates, the exposure dial and the indices. Insider filings from EDGAR, a nightly discovery scan of every liquid name, bar replay on the chart, and sixteen themes with a fund each where one exists.

**The saved charts from X (2026-09-04)** — thirteen screenshots of charts by accounts the user follows, read one by one in `research/charts-2026-09-03-x-accounts.md`. Seven readings the engine did not have went in at zero weight for the replay to measure: the 0.786–0.887 reversal zone, the next 1.272/1.414/1.618 target, a level's role flip (previous support now resistance, and the mirror), accumulation/distribution forming from the pivot labels, the record of earlier channel-edge touches, RSI divergence, and a volume-by-price profile. Williams %R now quotes what the last four floor hits did. Three setups added to the Research tab. **Second pass the same day:** the journal grades the followed accounts' calls under an `outside` source with the author on the row, with a Research-tab panel to record and read them (eleven seeded from the charts); volume by price drawn on the chart; the reversal zone and 1.272 / 1.414 targets on the Fibonacci overlay and in the trim level; head and shoulders, triple tops and bottoms, triangles and wedges at zero weight; the 30-year mortgage rate as a macro series. Then: a Panes size control on the chart; the Diagnose drawdown brought onto the report's daily grid; `measure.pairs`, the combinations report.

**2026-09-09 → 10 (D94–D97).** The reading on a held name became three prices
with what each move is worth — buy at, sell into, wrong below — with a strength
gate on both sides so most support and resistance never becomes a call, and the
holding period from the position's book replacing the daily/weekly/monthly grid
(D94, D95). Then a day of measurement against the user's note (D96): a
market-conditions bar is **not** supported and the sign points the other way; no
exit rule beats holding on 3,613 momentum entries; the edge is selection and it
sits in the tail. What shipped from it is the **accumulation scan** — dollar
volume expanding 4–20x against its own six-month base before the price has run,
11.5% of which reach 4x within a year against a 1.5% base rate — plus a crowd
filter that says whether anybody the user follows has noticed yet. **The sell
ladder is off (D97)**: it beat the user's own exits but loses to doing nothing.
Full working in `research/audits/edge-log.md`.

**2026-09-05 → 08 (D63–D92).** The sell ladder and the buy-back screen, studied on names they were not read from and on the user's own closed trades, then live: rungs on every held row, act alerts when one fires, one sell level and one buy-back per name, the trade-around plan drawn on the chart. A five-evaluator review worked through in five passes (D77–D81). The weekly X pull as a scripted procedure with the reading step kept, two pulls in; the Value Trader's charts from the emails; StonkChris's newer charts. Setups kept strict — a name at its level with a confirmation, sector strength as support only (D83, D84). The phone layout rendered and measured on every tab (D85, D86). SIVEF read on Sivers' Stockholm history everywhere (D87). The work computer by name over Tailscale Serve (D88). A copy for friends that is an app: launchers, a Get started screen that imports from a file picker, the price key and tax profile written locally, and a phone address printed when Tailscale is signed in (D89, D92). Buy plans for the next session with the gap rule, Serenity as ideas-only, an add whose level is below reads "worth adding nearer" (D90).

**2026-09-11 → 13 (D98–D110).** The broker's own cost basis imported rather
than derived, because no lot rule reproduces it (the app's FIFO had IREN
$25,633 high on basis and $18,000 low on unrealised gain). Alerts capped and
ranked by consequence after *"When market opens i get smacked with like 20
notifications"*. Two tabs for things that existed and could not be found — **AI
Trade Bot** and **New Stocks** — plus the followed accounts' charts beside the
Value Trader's.

Then the research pipeline, which is the substantial part:

* **Reading a chart video** (`research/video/`, D105–D107). A screen recording
  with no transcript, description or captions becomes a ticker list with the
  commentary attached to each name and the Fibonacci levels drawn on it — 41
  charts, 34 equities, 163 levels across 33 names from one video. Every chart is
  proved to BE that ticker by matching the OHLC printed in its header against
  real price bars. Free end to end: AVFoundation and Vision ship with macOS,
  whisper.cpp builds from source.
* **The overnight pulls** (D108, D109). X at 02:10 and seven YouTube channels at
  04:00, both feeding `x_mentions` under one handle per person. The mention
  history was three days long because the pull was a manual paste; it now grows
  nightly. The X pull checkpoints after every account and resumes, after the
  first full run was killed at fifty minutes and lost everything.
* **What a video is about** (D109). Spoken transcripts contain no cashtags, so
  names are matched instead — 140 aliases from 206 tracked symbols, with the
  coverage figure printed every run because an unmatchable name looks exactly
  like an unmentioned one.
* **Their calls, recorded the night they are posted** (D122). The X pull
  reads each new post for a cashtag and a claim in words near it and records
  it as a graded outside call, marked "auto", the tweet id remembered so a
  deleted post changes nothing. Words only: a chart posted without text is
  not read.
* **A friend installs nothing and sees it working first** (D128–D129). The
  launchers fetch Python themselves and clear the Gatekeeper block; Get
  started loads a made-up year on an empty ledger and takes it out again;
  prices need no key.
* **Their charts, by account** (D127). Every chart the followed accounts
  post on X is saved the night it appears, named by the post's cashtags, and
  shown with the Substack and Patreon charts in one grid — filtered by who,
  name and dates, or side by side by name so two people's charts of one
  ticker sit together. Every Substack post on disk is read, a year of
  him, not the newest dozen (D131), and the X and Patreon images render —
  the URL guard had blanked them since D127 (D132), and a name's own page
  shows its X charts beside its Substack and Patreon ones (D133); the Who
  filter names a person once across X and the Substack (D134). The images are not
  read for meaning; that stays open.
* **The Substack, nightly** (D123). 03:30, with the reader's session cookie
  stored by `./substack-setup.sh`; a lapsed cookie is a STOPPED line, never a
  folder of teasers. Cards, the bank and Fidelity stay a monthly browser
  routine — no API, no cookie (D124).

---

## What is actually left

## 1. Signals · *2 days*

The last unbuilt item from the original list. StockTwits and RSS first, macOS notification harvest, congressional disclosures. All as chart markers and watchlist columns, not a separate feed.

## 3. Encoding the rest of the priority five

**StonkChris's Substack (2026-09-04)** — all 255 posts pulled and kept locally (D50); the setup is now stated and a framework holds his sizing, stops and order of sales. Three candidates came out of it for the replay to measure before anything is weighted: a trend line on the weekly RSI pane (his sell signal, and the habit all three of the priority technicians share), Fibonacci anchored on the prior cycle high and bear-market low on a log scale rather than the last swing, and the VIX as a series with his 30 / 40 thresholds. His priced levels were graded (`research/audits/substack-stonkchris-levels-2026-09-04.md`): targets no better than chance, buy zones that were reached better than a matched fall on a small sample.

**Review of 2026-09-04 (the user's notes)** — fixed the same evening: the response cache now stamps the WAL file so a fresh fear-and-greed reading is not served stale; an alert fires on extreme fear (under 25), extreme greed (over 75) or a ten-point move in a day; trim levels need shown strength (D52); the proximity unit is bounded on collapsed histories (D53); thin monthlies read at low confidence (D54); annual subscriptions appear on their first bill (D55); the Outlook chart draws weekly bars over the whole history when the headline is weekly or monthly; excess returns are shown as percent over SPY, not points. The weekly Williams %R floor is an alert and an item (D65); Setups is one ranked list with reasons (D66). Cup and handle detected and measured 2026-09-05 (D62): a small edge on the neutral universe, strongest with volume; head and shoulders none. Done the night before (D56–D59): confidence read off the past record on every timeframe with the numbers shown; "what changed" on the Outlook rows; regime and construction off Diagnose; a Setups tab with the discover scan; Methods under Backtest; sector look-through for index funds; wash sales on Trades; Amazon refunds against card credits on Loose ends. Confirmation rules were measured overnight (D60): two closes instead of one changes nothing, so the engine keeps one close. Still open: a way to find names early that is actually early — the user's point stands that public feeds (StockTwits, Reddit) are known to everyone and carry no edge, so the candidate is the user's own X following read through the logged-in browser and graded per author in the journal, which is the source that found IREN and SAVE. **Wash-sale warning (D70)** on Outlook, Setups and alerts. **Sell ladder live (D72):** rungs on every held name's row and detail, act alerts when one fires. **Fifth pass (D81):** the plan's levels on the Chart, from-peak and next-rung columns on Holdings, bills before payday on the Budget summary. **Fourth pass (D80):** consolidation — one record panel, one-line market strip, alerts grouped with a dealt-with box, Diagnose and Risk reprints removed, held names in one list. **Third pass (D79):** the remaining bugs — split-adjusted and intraday marks, paper cash cap and base, estimated taxes and SE tax in the floor, the budget filter, pacing wording, scan prices, sectors, account risk. **Second pass (D78):** one sell level (the ladder's rung) and one buy-back (30% under the sale) per name, the watch block on the headline timeframe, verdict and note/target/stop on the Watchlist. **Five-evaluator review (D77), first pass:** the number bugs fixed — refunds, recurring keys, wash sales, the cash row, author spellings, weekend alerts; 27 more items in research/audits/app-review-2026-09-06.md. **Overview and Diagnose review (D76):** both returns named, growth-of-$100 toggle, looked-into boxes, alerts named by kind, SIVEF in concentration, chart view slides to today, weekend bars dropped. **Value Trader charts (D74)** on Outlook and Research, from the emails. **Weekly X pull (D75)** as a scripted procedure with the reading step kept. **Buy-back screen (D73)** on Setups: the floor, the drawdown, the followed zones and the last sale on every name sold in the last year, with the state in words. **Own exits (D71):** on 19 of the user's closed trades every ladder rung fired only after the sale, at far higher prices — the winners were sold early; where a rung fired while held the ladder was no better. **Ladder study (D69):** the sell ladder read off IREN's anatomy put 78% of its sells within 25% of a real top on 36 names it was not read from; no rebuy rule beat holding on more than 19 of 36. **Swing study, first pass 2026-09-05 (D63):** no written rule caught IREN's 76 → 29; the momentum exits fired at 46, the rebuys came too early. Next iteration is the rebuy side. **Started 2026-09-05:** the whole follow list read and sorted, 72 dated calls from 20 authors in the journal, notes on what each contributes in `research/x/`; the sell-slice-and-rebuy rule from LEADER_TRADING is still to be studied; the weekly pull of the shortlist's calls is D75.

**serenity (@aleabitoreddit)** is decided (D90): good for fundamentals and finding names, not for buys, sells or trims, so the journal refuses their calls and the cards do not list them — nothing of theirs is encoded. **Dr J Rould (@jrouldz)** is still unencoded and X-only; `05_method_sources.md` concluded the library should be YouTube-transcript-first. Either that rule gives way for this one, or he stays out. Worth deciding deliberately rather than leaving it.

## 2. Robinhood crypto

The equity side is imported and reconciled; what follows is the crypto gap only.
The import itself is **done.** The activity report arrived and imported: 25 rows, 2025-09-19 to 2026-04-29, into a taxable "Robinhood Individual" account. Cash derives to $4,011.40 and hand-checks against the rows exactly.

The real file exposed two bugs in an importer that had been written against the format rather than against an export, which is the case for not treating an unrun importer as finished:

- **Sells were stored with a positive quantity.** Robinhood states quantity unsigned and puts direction in `Trans Code` alone. Every other importer here writes a disposal negative and the lot builder depends on it, so a sell *added* to the position — SLNH read 20.96 shares and FRMI 2.0 after both were closed out entirely.
- **The trailing legal disclaimer aborted the import.** It is one unquoted sentence containing commas, so `csv` files the overflow under the restkey as a list; `.strip()` on it raised `AttributeError` at the final row and discarded all 25 rows already parsed.

Both are covered by regression tests.

**Still open: crypto.** The report states in its own footer that it excludes Robinhood Crypto and Robinhood Spending. The deposits that bought the crypto ARE present, so roughly $4,000 currently reads as idle cash in Robinhood when it is really SOL and ETH. Two routes: a cash anchor corrects the cash side immediately but leaves the holdings missing, or the positions get entered and priced (Alpaca covers both). The second is the real fix.

## 4. Options and crypto modelling

Neither is modelled. Robinhood holds SOL and ETH — see §2 for why they are not in the ledger yet.

---

## Cross-cutting

- **Tab organisation — done 2026-09-13 (D117).** The 2026-09-12 review's reorganisation shipped in four commits: the seven-section shell, the design system, the Today list with the symbol page, and the chart (opens on the last year; the user's marks are the only bold lines). Spec in `research/audits/phase2-spec-2026-09-13.md`.
- **The calibration tool has nothing to measure yet.** It needs 20 graded calls across 10 separate days; the app began recording verdicts on 2026-09-01, so the first real reading is mid-October. Your own trades already clear the floor — 958 of them across 275 days.
- **Reading posts for meaning is words, not charts.** `xcalls.py` catches "adding $X on the higher low" and misses a chart image with an arrow on it. The images are now saved (D127); reading them is open — macOS Vision OCR first (free, already built for video, reads the printed levels and text), a local vision model if that leaves too much, Claude with vision only if the user accepts a per-image cost. Any image-derived call should sit in a review state before it counts toward an author's grade.
- **The second earner has no pay stub on file**, so their income is counted from net deposits while the rest of the year is projected at gross. That keeps the tax projection a floor, which every message about it says.
- **Security.** Project is outside iCloud; pay stubs moved out of the synced Desktop; FileVault on. Since 2026-09-12 (D113): state-changing requests need the token the page is given, so a web page open on the phone cannot write to the ledger over Tailscale; IMAP verifies Gmail's certificate; symbols are validated at the boundary; the page carries a CSP; `share.sh` drops the private research paths from the tree. `tailscale set --accept-routes=false` is still worth doing.
- **Scale.** Not a problem at 7,000 transactions. The daily value curve costs ~40ms and the whole payload about a second cold. The watchlist Outlook was the exception — 48–100 s of scoring per cache miss, and every intraday write emptied the cache — until D114: nightly verdict cache, an epoch the quiet tables do not bump, single-flight, rolling indicators, gzip. The ledger went 760 MB → 318 MB on 2026-09-13 (D115: replay set in its own 446 MB file, 785,000 discovery-only bars pruned; 72 MB of that 318 is free space SQLite reuses, so the file will not grow for years), backed up nightly at 19:30.

---

## Superseded

The original list's items 1-8 and 10 are built. What follows is kept only because the reasoning still explains why things are shaped as they are.

## 1. Holdings — what you actually own · *2–3 days*

The obvious hole: the app knows every transaction but has no screen showing current positions.

- Position table: symbol, shares, average cost, market value, unrealised P/L ($ and %), weight of portfolio, day change.
- Realised P/L for closed positions, and a per-position contribution to the period return — *which holdings actually produced the +90.96%*.
- Cost basis by tax lot (FIFO), which also lays the groundwork for wash-sale detection later.
- Drill-through: click a position, see every transaction in it.

**Why first:** it needs no new data source, it's the screen you'll open most, and per-position return attribution is the first genuinely new insight the app produces.

## 2. Price charts — candlesticks and indicators · *3–4 days*

- TradingView Lightweight Charts, candlestick + volume, any ticker you hold or watch.
- Indicators computed server-side in Python so the same code later drives the scanner and the backtester — no Pine-vs-Python drift.
- **Your trades drawn on the chart**: entry and exit markers, cost-basis line, position size. This is the join Fidelity and TradingView structurally cannot do.
- Daily bars from Alpaca, already cached.

**Depends on:** nothing. **Unblocks:** the Method Library, scanner, backtests.

## 3. Watchlists — tags, not folders · *2 days*

- A ticker can be in "semis", "AI capex" and "owned" at once.
- Custom sortable columns: any indicator, any metric.
- Computed lists: everything held, everything within 5% of a 52-week high, everything you sold in the last 90 days.
- Position awareness on every row.

## 4. Research panel · *3–4 days*

- **SEC EDGAR** (free, no key): filings, and every XBRL fact — revenue, margins, share count, debt — as a time series next to the price chart.
- **FRED** (already wired): rates, CPI, unemployment as context overlays.
- Earnings dates and history.
- A per-ticker notes field: your own thesis, timestamped, so the app can later tell you when new information contradicts something you wrote.

## 5. The Method Library · *4–5 days*

The differentiator. Each analyst becomes a structured definition — timeframes, indicators, named setups with entry conditions and invalidation, risk rules, and what they ignore. One definition compiles into four things: a chart template, a nightly scanner, a pre-trade checklist, and a backtest.

Start with **Cantonese Cat** and **RonnieV** — both in your priority five and both publishing long-form video, which is far better encoding material than tweets.

**Depends on:** charts (2) and indicators.

## 6. Scanner · *2–3 days*

Run any method's conditions across your watchlist nightly; surface what qualifies; stack methods ("show me names three of my five agree on").

## 7. Backtesting + paper trading · *4–5 days*

app/backtest.py over cached history; Alpaca paper account for forward testing. Makes the encoded methods falsifiable on the names you actually trade.

## 8. Budgeting · *3–4 days*

Now unblocked — the Frost importer retains merchant names again (625 distinct, was 13). Rules engine first, LLM only on the leftovers, each decision written back as a new rule. Shares the ledger with the portfolio, which is what produces net worth + cash flow + investment performance in one picture.

## 9. Signals · *2 days*

StockTwits and RSS first (better signal than X for month-to-year holds), macOS notification harvest, congressional disclosures. All as chart markers and watchlist columns, not a separate feed.

## 10. Phone access — PWA + Tailscale · *1 day*

The dashboard is already responsive and installs to the home screen. Tailscale makes it reachable from the work PC and from cellular.

---

## Cross-cutting, to slot in as they start to hurt

- **Security:** move the project out of iCloud-synced Desktop. Still outstanding.
- **Robustness:** importers should report a row-count shortfall — a truncated file currently imports silently.
- **Scale:** cache the value curve per scope. Not needed at 5k transactions; needed by ~50k.
- **Options and crypto:** neither is modelled yet. Robinhood crypto is a separate account with a real API.
