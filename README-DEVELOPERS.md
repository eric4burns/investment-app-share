# Investment App

A personal, single-user investing application: combines and improves on Fidelity,
Yahoo Finance and TradingView, plus a general personal-finance and budgeting
section. Runs entirely locally at zero recurring cost.

## Files

Two of these are live and the rest are reference. **`SETUP.md`** if it is not
running yet, **`HOW_TO_RUN.md`** once it is; `03_decisions.md`,
`06_feature_roadmap.md` and `07_improvement_plan.md` are the ones kept current as the app changes.

| File | What it is |
|---|---|
| `00_original_notes.md` | The original idea, transcribed from `~/Desktop/Stock App.pages`. |
| `01_feasibility_research.md` | Reference research on the paid/commercial landscape — vendor pricing, market-data licensing, competitive analysis. Consult when evaluating an upgrade. |
| [the shared plan](https://claude.ai/code/artifact/dba861e5-2eca-44f2-b393-26f585810d8c) | **Historical.** A shareable page of the original build plan, published 2026-08. It predates the whole verdict layer and is not kept current. |
| `02_free_build_plan.md` | The reasoning behind the $0 approach — what free actually costs, blockers sorted by kind, phased build order. Its original stack table named FastAPI, Postgres and React; none of that was built, and the rows now describe what was. |
| `03_decisions.md` | Decision log — fixed constraints, settled decisions, corrections, known hard limits, open questions. Append-only; when it reaches its 80 KB budget the oldest block moves unchanged to `research/audits/` (D14–D59 are there). |
| `04_getting_started.md` | **Historical.** The first push, from before any of it existed. Every task in it is done; kept because the reasoning explains why the ledger is shaped as it is. |
| `05_method_sources.md` | The analysts whose techniques are encoded, what was captured from each, and the confidence attached to it. |
| `06_feature_roadmap.md` | What is built and what is not. The honest list of what remains. |
| `07_improvement_plan.md` | The 2026-09-02 review: three root causes, and the phased plan to fix them. Working list while it is being worked through. |
| `CLAUDE.md` | What a Claude Code session reads first: the order to read the docs in, the facts that bite (the server does not reload Python; writes need the page's token; never write to the ledger from a test), and the conventions. `HOW_TO_RUN.md` has the five steps to start a session from iTerm2. |
| `SETUP.md` | **Start here if it is not yet running on your machine.** Prerequisites, price access, where each export goes, and phone access. |
| `HOW_TO_RUN.md` | Day-to-day operation of a copy that already works: start the server, import statements, run the tests, take a backup. |

## Code

| Path | What it is |
|---|---|
| `app/` | The application. `web.py` serves it; the front end is `dashboard.html` (the stylesheet and the markup — seven sections with sub-tabs since D117) plus its script in `static/` — `core.js` (helpers, the token wrapper, the router) and one file per section (`today`, `money`, `stocks`, `follow`, `bot`, `symbol`, `chart`, `budget`), plain scripts sharing one page scope with no build step; the rest is the analysis layer. |
| `tests/` | 63 Python suites, about 2,550 checks (one suite a size budget for every file kind, the database and the backups), plus a browser smoke test (184) and an empty-ledger test (14), run with `./run_tests.sh`. The runner fails on an incomplete tally, a suite that ran nothing, a missing suite file, and drops compiled bytecode first so a stale `.pyc` can never be what gets tested. |
| `research/` | Research-time tools, not part of the app: `x-nightly.py`, `substack-nightly.py` and `yt-nightly.py` are the three overnight pulls launchd runs (their clients are `app/xpull.py`, `app/subpull.py` and `app/ytpull.py`; the X one also runs `app/xcalls.py` and `app/xcharts.py` so the night's calls are journaled and its charts saved); `video/` reads a chart-flipping video end to end — `collect.sh` samples frames with a Swift/Vision OCR tool, resolves the instrument names to tickers, transcribes the audio with a vendored whisper.cpp, proves each chart really is that ticker against real price bars, and stores the Fibonacci levels drawn on it as author levels; `fetch_transcripts.py` pulls YouTube transcripts, falling back to local transcription when a video has no captions; `substack_receiver.py` + `substack_extract.py` + `substack_levels.py` pull a subscribed Substack through the logged-in browser, split it into per-ticker blocks and grade its priced levels; the `seed-*.py` scripts put followed accounts' calls in the journal (`seed-stonkchris-calls.py` re-reads the Substack for new priced calls; the dated ones are one-off seeds kept as the record of what went in); `retry_one.py` re-tries a single transcript slowly once YouTube has rate-limited `fetch_transcripts.py`; `confirm-compare.py` sets the one-close and two-close replays side by side; `sweep.py` scores every reading the app computes against a name's real turns; `ladder-study.py` tests the sell ladder and four rebuy rules on names they were not read from; `own-trades-exits.py` replays the ladder over every closed trade in the ledger since 2022 against the exit actually taken; `tests/phone_shots.mjs` renders six tabs at iPhone width to the scratch folder (the layout check that found the sideways page); `x_pull.js` + `seed-x-calls.py` are the MANUAL fallback for the X pull and the seeding of the reviewed calls (D75), kept for when the stored session has expired; `anatomy.py` prints what a name's real tops and washed-out lows looked like and counts, on that name's own history, how often each candidate signal fired and what followed; `swing-study.py` trades half a position by written sell-slice and rebuy rules over the conviction names and counts shares at the end; `pattern-study.py` walks every week-end for confirmed cup-and-handle and head-and-shoulders breakouts and grades what followed. `research/audits/` holds the measurement reports and the archived decisions; `research/transcripts/`, `research/substack/` and `research/x/` are third-party content and the user's own notes, kept locally only and refused by `share.sh`. |
| `run_tests.sh` | Every suite, one command — including the browser test, because every Python suite here can pass while the page is blank. |
| `smoke.sh` | Opens the app in a real browser and asserts on what renders. Runs against a throwaway copy of the ledger. |
| `empty.sh` | The same, against an EMPTY ledger — what a fresh clone has, and the one case every other test misses. |
| `update.sh` | Re-import statements, refresh prices, and record the day's verdicts. |
| `backup.sh` | Nightly at 19:30: a full snapshot with sqlite3 `.backup` (gzip -1, seven kept plus six monthlies) and a curated few-megabyte copy of only what cannot be rebuilt, to `~/Backups/investment-app/`. The database holds curated data that exists in no file under `data/`. |
| `install-agents.sh` | Optional: seven launchd agents — keep the server up, refresh at 18:30, back up at 19:30, poll levels every 15 minutes in market hours, pull X at 02:10, the Substack at 03:30 and YouTube at 04:00. |
| `x-setup.sh` | Stores the x.com session the nightly pull needs, reading both cookies without echoing them or putting them in shell history. |
| `substack-setup.sh` | The same for the Substack: stores the `substack.sid` cookie in `data/.substack` and tests it against the newest paid post. |
| `check-key.sh`, `edit-key.sh` | Verify and edit the Alpaca credentials without remembering where the file lives. |
| `Investment App.command`, `Investment App.bat`, `GETTING-STARTED.md` | What a recipient double-clicks and reads: the launchers find Python 3.11+ or fetch a private copy with `uv` (nothing to install, D128), clear the Mac's quarantine flag once running, and open the browser; the guide is their whole setup, including the three ways past Gatekeeper. |
| `share.sh` | Cut an archive to give somebody: one clean commit, no history, and it refuses to hand over a zip containing the ledger or a key. |
| `phone.sh` | Prints the address to open on your phone, and checks the server is listening on it. |

### The analysis layer

Two halves that meet at net worth.

| Module | What it answers |
|---|---|
| `performance.py`, `holdings.py`, `risk.py` | What the portfolio is worth, what it returned, and how concentrated it is. |
| `networth.py` | Everything owned minus everything owed, over time. |
| `prices.py` | Price bars, cached. Alpaca's consolidated (SIP) feed first — free for anything older than fifteen minutes, and the only feed that sees the whole tape on a thin name; Yahoo only where Alpaca returns nothing, which is how the OTC holdings get priced at all. A finished bar is never rewritten; the newest one is, because a bar fetched mid-session is not a close. |
| `analysis.py`, `structure.py`, `indicators.py` | What a chart says — pivots, trendlines, channels, Fibonacci, horizontal support/resistance zones, indicators. |
| `setups.py`, `methods.py`, `frameworks.py`, `theses.py` | The encoded research: what is tradeable, how to shape the book, why a group might re-rate. |
| `backtest.py`, `exits.py` | Walk-forward replay of a method against a survivorship-free control, and whether any mechanical exit would have gotten out sooner. |
| `watchlist.py`, `sectors.py`, `themes.py`, `intermarket.py` | What is being watched, what sector it is in, what theme it belongs to, and what the rest of the market is doing. |
| **the verdict layer** | |
| `sentiment.py` | CNN's fear and greed index, cached daily. Market-wide, so it only carries weight in a verdict at the extremes. |
| `verdicts.py` | The one module that reaches a conclusion — buy, add, hold, trim or sell — on daily, weekly and monthly, with the evidence, the case against it and a reward-against-risk score that ranks calls saying the same word. Since 2026-09-03 the weekly call comes from the measured record rather than the trend items (top fifth with a level below is a buy, bottom fifth a sell), a weekly sell at high confidence takes the headline, and a buy is marked down one notch while the S&P is breaking. A hold no longer reports the share of evidence it fell short of; it says there is nothing to do at this price and hands over to the levels. |
| `levels.py` | The prices a reading tells you to act at: **buy at**, **sell into**, **wrong below**, each with the move it starts. A level is only offered if the market has turned there three times or from both sides, so most support and resistance never becomes a call; where a side has nothing that qualifies the reading says so rather than leaving a blank. Targets are measured from the level, not from today's price. Split out of `verdicts.py` in D95. |
| `discover.py` | Two ways to find names off the watchlist. The **method scan** runs the encoded methods across every liquid listed name. The **accumulation scan** flags dollar volume expanding 4–20x against its own six-month base while the price has *not* yet run. It surfaces names early — it found IREN at 3.75 and DGXX at 1.38 — but it is **not a tradeable edge**: bought mechanically and held a year these names compound at 1.01x and over a quarter at 0.94x, and a portfolio of them returned 0.655x against SPY's 1.950x from mid-2021. The widely-quoted "11.5% reach 4x" describes the PEAK they touch, not what a holder realises. About four names a week, to research; the deciding is still the user's. |
| `regime.py` | The exposure dial (growth against the market, small caps against large, the index against its average, the dollar) and the indices' own read — SPY, QQQ and IWM against their 50- and 200-day averages, which sets whether the market is with or against a setup. Both recorded on every call for the replay to measure. |
| `books.py`, `trade_around.py` | Which book each position is in (swing, conviction, or a core traded around) and, for a traded-around name, the slice to sell into strength, where to buy it back, the odds, and which lots keep it tax-free. |
| `outlook.py` | The nightly pass: score every holding, record the call, and print what CHANGED. |
| `journal.py` | Calls made, by the app and by you, graded against SPY once the horizon has elapsed. |
| `calibration.py` | Whether the engine is working, sliced by action, timeframe, confidence and individual condition — the tool that says what to change. |
| `replay.py` | The engine run at every week-end since 2022 on the bars it would have had then, graded the same way and kept under its own source — so calibration has tens of thousands of calls instead of twenty. Its rows live in `ledger-replay.db` once `split_replay.py` has moved them out of the ledger. |
| `split_replay.py`, `retention.py` | Data lifecycle: the one-time move of the replayed calls into their own file (and a safe `VACUUM INTO` afterwards), and the nightly prune of what nothing reads — two-year-old bars for names only the discovery screen knows, old hits, alerts and intraday bars. Both dry-run by default. |
| **the money half** | |
| `budget.py` | Where the money goes. Rules are evaluated on read, so correcting one reclassifies all history. |
| `cash.py` | What is actually in cash. The core money-market funds are derived from flows, because the sweep is never exported. |
| `recurring.py` | What charges you again and again — by brand, with the distinction between a subscription you can cancel and a habit you cannot, bills (insurance, utilities, rent) kept as bills whatever the amount does, and every price each charge has billed at with the day it started (D126). |
| `trends.py` | What changed this month, against the median of the months before it. |
| `taxes.py` | Bracket and contribution-limit arithmetic, and the taxable account's year — FIFO realised gains split at a year held, wash losses added back, dividends and interest, a long-term gain at its own rate stacked on ordinary income (D121). Every figure is a floor, and says so. |
| `substack_charts.py` | The charts from a subscribed Substack, per symbol, on the New Stocks tab. The Value Trader's charts were shown from D74 because his levels are ONLY on the image; StonkChris writes his out, so the parser was built and the charts never were — each post carries ten and the URLs were already on disk. Split on the same `TICKER (1D)` header the level parser uses, so a chart and its parsed levels can never disagree about which block they came from. Every post on disk is read (D131: a twelve-post window had hidden FPS and every other name older than two weeks). |
| `broker_basis.py` | The broker's own cost basis, imported, because FIFO is a guess about which lots were sold and the statement is a fact. Fidelity reported IREN at $19.63 a share against the app's FIFO $25.69 — $25,633 of basis and ~$18,000 of unrealised gain on the largest position — because lots are selected per sale and no rule reproduces that. Applied only where the broker's share count matches the ledger's; where it does not, the position stays on FIFO and says why, and every position carries `basis_source`. |
| `ladder.py` | The sell ladder — **switched off 2026-09-10 (D97)**. Measured against buy-and-hold over 3,613 momentum entries it cost 2.4% of the book, and rung 1 alone cost 8% of the mean by cutting winners early: it sold IREN at 14.00 seven days into a move to 76.87. D71's finding that it beat the user's own exits still stands — it had been validated against the wrong baseline. `ENABLED = False` makes `state()` return None, which silences the rung alerts, the Outlook card, the trade-around sell level and the buy-back ladder stage together; `rungs()` still computes for the research scripts, and turning it back on is one constant. |
| `rebuy.py` | The buy-back screen (D73): on every name sold out of or trimmed in the last year and the watchlist, the weekly Williams floor and its confirmation, drawdown from the 52-week high, the followed authors' zones, the last sale and the wash window, with the state in words. A screen, not a rule — none beat holding (D69). |
| `xcalls.py` | The followed accounts' calls, read out of the nightly X pull the night they are posted (D122): one or two cashtags and a claim in words near them become an `outside` call priced at that day's close, marked `auto`, the tweet id remembered in `x_calls` so nothing is recorded twice and a deleted post changes nothing. A post that says both things is skipped; a hand-recorded call for the same author, name and day wins. |
| `xcharts.py` | The charts the followed accounts post on X, saved by account the night they appear (D127): the photo URLs the pull keeps become files under `research/x/images/<handle>/`, recorded in `x_charts` with the post's cashtags as the chart's names. Serves the Their charts grid and the `/chart-x` image route, which only ever serves a stored path under that folder. `charts(conn, symbol=)` narrows to one name for the symbol page (D133). |
| `subpull.py` | The nightly Substack pull (D123): the publication's archive JSON, then each new post's body with the stored `substack.sid` cookie, written as the same `.json` and `.txt` the browser receiver wrote. Refuses to write a paywall teaser, so a lapsed cookie is a STOPPED line in the log. Publications are listed in `research/substack-publications.txt`. |
| `xpull.py` | The nightly X pull. Makes the same GraphQL calls the browser makes, using a session stored in `data/.x`, because X's own API starts at $100 a month. Paced at 150s an account to stay under the rate limit, so a full pass over 32 accounts is about eighty minutes; it writes after every account and resumes an interrupted run, and a partial pull is never used as the next run's starting point. |
| `ytpull.py` | Which names a YouTube video is about. Spoken transcripts contain no cashtags, so this matches company names — the first word of the name, four letters or more, absent from the system dictionary, not a corporate word, unambiguous across the tracked set, plus a two-word phrase where the first word alone is too common ("advanced micro"). About 140 of 206 tracked names are reachable that way and the rest, like Apple and Block, are not; the coverage figure is printed every run, because a name that cannot be matched looks exactly like a name nobody mentioned. It confirms interest in names already tracked rather than discovering new ones. |
| `plans.py` | Buy plans for the next session (D90): a name, the price to pay at most, and a gap rule — over N% above the prior close at the open means wait for a pullback under the open. Judged by the 15-minute poll against the day's first bar and the last price; alerts once per condition per day; nothing is ordered. Set from the name's page (Plan & levels), listed on Today → What to do. |
| `authors.py` | The levels followed authors have named on a symbol — buy zones and targets — shown beside the app's own level and used by the buy-back screen and the trade-around plan. Also holds **mentions**: `crowd()` says whether a name is early, warming or crowded by how many followed accounts have posted it in 30 days, counting distinct accounts rather than posts. Two nightly jobs feed it — `xpull.py` for X and `ytpull.py` for YouTube — under the same handle per person, so somebody posting on both platforms counts once. Those cut-offs are a judgement, not a measurement, and every verdict says so; coverage is reported beside them so "nobody is discussing this" is not confused with "the pull never covered that week". |
| `valuetrader.py` | The Value Trader's Patreon posts from the notification emails (D74): subject, teaser, the chart saved once and served back, a call journaled when the subject makes one. |
| `sample.py` | A made-up year for one household, written in the real export formats and imported through the real importers, so a fresh copy shows the whole app before any export exists (D129). Into an empty ledger only; out again with one click; every account named Sample. |
| `setup_flow.py` | The first-run screen's back end: what a fresh install still needs, a file dropped in the browser saved under data/ and imported, the price key and tax profile written locally (D89). |
| `washsales.py` | Loss sales with a same-symbol purchase inside the 61-day window, the loss disallowed, and the live windows not to trade into. From the ledger only, so a floor. |
| `amazon.py` | Amazon refund emails, read over IMAP with an app password, matched to card credits; what was promised and never arrived. |
| `mailtrades.py` | Fidelity's trade-confirmation emails, the morning after a fill: action, price and security into the journal as a trade made, shares pending the statement. |
| `drawings.py`, `static/drawings.js` | Hand-drawn chart annotations, stored as (time, price) and rendered on a canvas above the chart. `static/` also holds the vendored chart library and, since 2026-09-13, the dashboard's own script split by section (see the `app/` row). |
| **tools and plumbing** | |
| `alerts.py` | What changed, what is at a level, what reports soon, and which export is overdue (a card, the bank, Fidelity or a pay stub five weeks old, asked for weekly until the file lands — D125) — nightly and every 15 minutes during the session — sent to the phone by ntfy and to this Mac, and listed on the Overview whether sent or not. Your own horizontal levels on the Chart tab get alerts too, and every level alert carries what it means: which way the level now faces, the app's call with its reason, and the next levels either side. |
| `earnings.py` | The next report date for every name, from Nasdaq's calendar (undocumented, like the Yahoo fallback), shown beside every call. |
| `insiders.py` | Open-market insider buying and selling from the SEC's own Form 4 filings, two years deep, on the watchlist rows. |
| `discover.py` | Nightly, across every liquid NASDAQ and NYSE name, so the scanner can find something rather than confirm the watchlist: the encoded methods, and the **accumulation** pass that flags dollar volume expanding against its own base before the price has run. The accumulation pass reads only bars the scan has just refreshed, so it costs nothing extra. |
| `paper.py` | The weekly engine's calls traded on the Alpaca paper account from 2026-09-03: day market orders placed after the close and filled at the next open, equal weight across ten names, exits on a sell call or a closed stop. No price floor, but at most two names under $2 at half a slot unless their relative strength is in the top fifth. A forward record nobody can backfill, shown on the Backtest tab against SPY. |
| `measure.py` | Every evidence item measured against the universe's own drift, with an out-of-sample test of whether measured weights order the calls — on the watchlist replay and on a 500-name sample of the liquidity screen that nobody chose for performance. Its stored weights are the "Measured" column on the Holdings calls table, and the findings are in `research/audits/`. |
| `report.py`, `diagnose.py` | The same figures at the command line, and a ranked read of what is wrong with the book. |
| `refeed.py` | Rebuild the daily cache from the consolidated feed, with a before-and-after audit of every reading that depends on it. Run once on 2026-09-02; the report is `research/audits/refeed-2026-09-02.md`. |
| `anchor.py`, `reconcile.py`, `integrity.py` | Telling the app a balance it cannot derive, checking it against the broker, and reporting the holes rather than importing over them. |
| `config.py`, `ledger.py`, `import_all.py` | Settings, the database, and the one command that reads everything in `data/`. |

### Where data goes

| Directory | What belongs there | How |
|---|---|---|
| `data/fidelity/` | Fidelity activity exports (`.csv`) | 93 days per export; overlapping ranges are fine |
| `data/bank/` | Bank exports (`.ofx`) | Frost does 2 years in one file |
| `data/cards/` | Any card issuer's export (`.csv`) | Filename becomes the account name |
| `data/budget/` | Your own budget spreadsheet (`.csv`) | Categories down, months across; put the year in the filename |
| `data/robinhood/` | Robinhood activity report (`.csv`) | Excludes crypto and Spending, which its own footer says |
| `data/payroll/` | Pay stubs (`.pdf`) | Gross wages, withholding and the 401(k) deferral, none of which a deposit reveals |

Everything under `data/` is gitignored. The card importer reads the header to
find the columns and works out the sign convention from the payment rows, since
issuers disagree about whether a purchase is positive or negative and guessing
wrong imports a year of spending as a year of income.

## How it is tested

Three layers, because each catches what the one below cannot.

**Python suites** cover the analysis. They are written against specific past
failures rather than for coverage, which is why so many of them assert what the
code must REFUSE: a trendline through prices that already broke it, a card CSV
whose sign cannot be established, a budget that counts a transfer as spending, a
Roth allowance treated as a cliff.

**The browser smoke test** exists because every Python suite here can pass while
the page is blank — and has. It opens the app in Chromium, walks all thirteen
tabs, draws on the chart, and asserts on what actually rendered.

**Mutation checks** are how the tests themselves are trusted. Three tests in
this project once could not fail at all. Any assertion worth keeping should
break when the code beneath it is deliberately broken, and the important ones
here have been checked that way: inverting a card sign convention, counting
transfers as spending, comparing a half-finished month, calling every habit a
subscription.

## What it cannot do

Stated plainly, because each is a real limit rather than a missing feature.

- **It cannot download your statements by itself.** Fidelity has no API and
  card exports need a browser session. Claude can drive most of the exports
  through the Chrome extension once you have signed in (SETUP.md, "Monthly
  statement pull"); the Fidelity Rewards Visa is the one that stays by hand.
  Everything after the file lands is automatic. Cards, the bank and Fidelity
  have no API and no cookie a nightly job could carry, so unlike X and the
  Substack they cannot be pulled overnight (D124).
- **The research pulls depend on things outside the app.** The X pull needs a
  logged-in session that expires when you log out, and automated collection is
  outside X's terms of service — a terms question, not a technical one, and the
  user's call. The YouTube pull needs nothing, but it can only match names with
  a distinctive word in them, so a quiet name and an unmatchable name look the
  same; the coverage figure is printed so the difference is visible.
- **Card spending it has no export for is invisible.** The bank records a payment
  to the card, never what was bought. The Budget tab reports how much is still
  unaccounted for rather than pretending the total is complete.
- **A bank account whose history predates the import derives a balance that is
  too low** — negative, in one case here — and every net worth figure is short
  by that much until a statement balance is entered.
- **Tax figures are floors.** A payroll deposit is net of tax and pre-tax
  deferrals, business receipts are revenue rather than profit, and neither is
  MAGI. Useful for noticing a limit is close; not a filing figure.
- **OTC prices come from an undocumented endpoint.** Alpaca's free tier refuses
  OTC outright, so those holdings are priced from Yahoo, whose terms do not
  permit automated collection and which can change without notice. CNN's fear
  and greed index is on the same footing: it works, it is not a supported API,
  and it answers 418 to anything that does not look like a browser.
- **A verdict is a reading, not a recommendation.** It is a mechanical scoring
  of price structure with the evidence attached, and it says nothing about the
  company, the sector, an earnings date or anything else that is not on the
  chart. Whether it is any good is the question `calibration.py`, `replay.py` and
  `measure.py` answer. The replay has graded the engine at every week-end since
  2022 — 78,000 calls on the watchlist and 150,000 on a random slice of the
  market — and the honest summary is: the daily chart carries no measurable
  information at a one-month horizon; the weekly, read from the measured record
  since 2026-09-03, orders outcomes the right way; and the standard trend
  readings on a weekly chart were followed by the opposite of what they claim
  in 2022–2026, on both universes, which is why they are switched off.
- **The tax projection is a floor projected forward.** Income already received
  is counted from deposits, which are net of tax and deferrals, while the rest
  of the year is priced at gross. So a projection that CROSSES a threshold is
  reliable and one that does not is worth nothing — the real figure is higher by
  an unknown amount. Every message about it is phrased that way on purpose.

## The one-line summary

Fidelity is read-only truth, imported from CSV; one SQLite ledger serves both
the portfolio and the budget; and the analysis layer encodes named traders'
techniques with the confidence level of each attached to it.

On top of that sits one verdict per name — held or watched — on daily, weekly
and monthly, recorded nightly with the price that would flip it. That is what
lets the app say what CHANGED since yesterday rather than only what is true
today, and it is what makes every call it has ever made gradeable against what
the market went on to do. Your own trades are read out of the ledger and scored
by the same code, so "does this add anything to what I would have done anyway"
is a query rather than a project.

Both halves meet at net worth: investments, bank cash and card debt in one
figure, over time. Neither half alone answers the question, and the third piece
only became knowable once the card exports were imported — a brokerage balance
rising while a card balance rises faster is a portfolio going up and a net worth
going down.

Robinhood automation was planned and is not built. Alpaca is the free price
feed and, since 2026-09-03, the paper account on which the weekly engine's calls
are traded so the record cannot be backfilled.

## Running it

    cd ~/Desktop/Projects/investment-app
    python3 -m app.web        # then open http://localhost:8737

Or double-click **Investment App.command** (Mac) / **Investment App.bat**
(Windows), which is what a copy given to somebody else starts with; it also
prints the address to open on a phone when Tailscale is signed in. On this
Mac the launchd service from `install-agents.sh` keeps it running; the phone
reaches it by the address `./phone.sh` prints, and a work computer by name over
Tailscale Serve (SETUP.md, "Reaching it from a work computer").

See `HOW_TO_RUN.md`. The server binds to loopback only unless
`INVESTMENT_APP_HOST` says otherwise, and has no password.

It watches its own source and restarts when a file changes, so a feature added
while it is running does not need a restart to appear. Set
`INVESTMENT_APP_RELOAD=0` to turn that off — `install-agents.sh` does, since a
supervised service should not re-exec under its supervisor.

Responses are cached against the database's own state, so two browser tabs no
longer queue behind each other for the GIL. Any write moves the file and drops
exactly the answers that could have changed.

## Licence

MIT — see `LICENSE`. Use it, change it, redistribute it; it comes with no
warranty.

It is worth saying plainly what the no-warranty clause means for software of
this particular kind. This app computes returns, tax estimates and exit signals
from your own imported data, and it can be wrong: an export can be incomplete,
an importer can misread a row, a price can be stale, and a cash balance derived
from transactions alone is wrong by the opening balance until you anchor it.
Check anything you intend to act on against your broker's own figures. Nothing
here is financial advice.
