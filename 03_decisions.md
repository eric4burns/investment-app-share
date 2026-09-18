# Investment App — Decision Log
_Started 2026-08-28. Append-only. Each entry records what was decided and why, so we never re-litigate it._

---

## Fixed constraints (from you, not assumptions)

| # | Constraint | Consequence |
|---|---|---|
| C1 | **Must be free.** Zero recurring cost. | Every choice leads with the $0 option. Paid items are labeled as optional future upgrades only. |
| C2 | **Single user — me only**, now and probably ever. | Keeps market-data licensing, exchange redistribution fees, and investment-adviser registration entirely out of scope. Adding a second user changes the project's legal and cost category. |
| C3 | **No new brokerage accounts.** Fidelity (2–3 yrs) and Robinhood (<1 yr, crypto, small) only. | Alpaca *paper-only* is permitted because it is not a brokerage account — email signup, no SSN, no funding, no application. |
| C4 | **Swing trading**, months to a year. Occasional week or day trade. | Delayed / end-of-day data is fine. Real-time SIP is not worth paying for. |
| C5 | **iPhone access required**, most reliable/professional option. | PWA over Tailscale. Native is $99/yr and violates C1. |
| C6 | **Always-on host = the old MacBook Pro.** The current M1 MBP (macOS 26.6.1, 16 GB) is not available for this. | Everything runs local. No VPS, no cloud, no hosting cost. |

---

## Decisions made

**D1 — Two-sided account architecture.**
Fidelity is read-only truth for real money. Robinhood crypto is the live automation venue. Alpaca paper is the sandbox. One shared `Portfolio` abstraction serves all three, so the position and performance engine is written once.

**D2 — Robinhood is tracked separately from Fidelity.**
It's crypto and a small amount. Folding it into equity performance-vs-SPY would be meaningless. Separate account view, benchmarked against a crypto reference if at all.

**D3 — Performance math uses time-weighted return (Modified Dietz to start).**
Simple percent change is wrong the moment there's a deposit. This is the thing Fidelity and Yahoo get wrong and is our first real differentiator. Benchmark comparisons use *total* return (SPY/VOO), indexed to 100.

**D4 — Charting is Lightweight Charts v5 + our own indicator layer.**
TradingView's Advanced Charts free license excludes personal projects. Server-computing indicators in Python means the same code draws the chart, runs the scanner, and runs the backtest — no Pine-vs-Python drift.

**D5 — Equity automation stays human-in-the-loop.**
Neither Fidelity nor Robinhood permits programmatic equity orders. Browser automation is technically possible but risks the account holding most of the money. Strategies emit a **trade ticket** the user enters by hand. Order staging is an acceptable future convenience; automated live equity execution is not.

**D6 — Real-money automation happens on Robinhood crypto.**
Official, documented, supported API. Free. Small stakes already. It proves the machinery, not an equity edge.

**D7 — Budgeting shares the portfolio's double-entry ledger.**
One ledger, two views. This is what produces net worth + cash flow + investment performance in a single picture, which no competitor offers.

**D8 — Bank transactions: statement-drop, and it turns out to be fine.**
**Frost resolved 2026-08-29 (in-product, no phone call needed):** Frost offers **Web Connect only** — a Download Transactions page exporting Quicken / QuickBooks / **OFX** / Excel / CSV. No Direct Connect. But the export window is **a full 2 years in a single download**, with no 90-day chunking, and the OFX carries a unique `FITID` per transaction. That makes Direct Connect largely unnecessary for Frost: one download per period, perfectly deduplicable.

**D8b — Prefer OFX over CSV wherever an institution offers it.** OFX gives `TRNTYPE`, `DTPOSTED`, `TRNAMT`, `NAME`, `MEMO` and — critically — `FITID`, a stable unique id. That makes the importer trivially idempotent: dedup on `FITID` and re-importing overlapping exports is a no-op. CSV has no such key and needs fuzzy matching.

_(original note retained below)_
Third-party aggregators (Plaid, GoCardless, SimpleFIN) are ruled out by C1. Institutions checked 2026-08-28: **Fidelity** likely supports OFX (FID 7776, `ofx.fidelity.com`); **Chase discontinued it 6 Oct 2022**; **Capital One** never supported it for cards; **Amex** historically did but has moved to Quicken-only OAuth and reports breakage; **Frost Bank** unknown, needs a phone call. So the download step is manual for most accounts — which makes *automating the download* the thing worth building.

**D8a — The download is automated via Claude in Chrome, never via shared credentials.**
It drives the user's own logged-in Chrome session; the user handles login and 2FA. Credentials never enter a transcript, a config file, or a third party. This also covers the Fidelity 90-day-capped history export, which is ~12 separate downloads for three years.

**D9 — Categorization is rules-first, LLM-on-leftovers, with write-back.**
Every LLM categorization becomes a new rule, so model usage trends toward zero and the system doesn't depend on an assistant being in the loop.

**D10 — The Method Library is the project's differentiator.**
Analysts the user rates get encoded as structured method definitions that compile into a chart template, a scanner, a pre-trade checklist, and a backtest. Nothing on the market does this.

**D11 — Social/sentiment is deliberately last and deliberately cheap.**
StockTwits and RSS first (free, better signal than X for months-to-year holds). macOS notification harvest as a bonus. Paid X API only if the free routes disappoint.

---

## Corrections made during research

- **Rev 2 → Rev 3:** Automated bank sync was reported as blocked. Wrong — OFX Direct Connect is free and works with most major institutions.
- **Rev 2 → Rev 3:** Robinhood was written off for automation. Wrong — the *crypto* API is official and supported, and that's what the user's Robinhood account holds.

---

## Known hard limits (verified, not worth revisiting)

- iOS cannot read other apps' notifications. No API, no Shortcuts hook, no workaround short of jailbreak. **Only true impossibility in the project.**
- Fidelity has no retail API. SnapTrade's Fidelity and Robinhood integrations are both read-only.
- Real-time consolidated (SIP) quotes require an exchange data license. Free IEX real-time covers ~2% of volume.
- Fidelity CSV export is capped at **93 days** per download, ~5 years available. Confirmed in-product 2026-08-29.
- A native iOS app requires the $99/yr Apple Developer Program.

---

**D12 — Performance charts: one combined total, plus per-account separation.**
User's call. Headline is a single combined performance curve; below it, account filters and a per-account breakdown. Add a **taxable-only toggle** — the 401(k) and HSA carry payroll contributions that make a combined "return" noisier than it looks, and isolating the accounts where the user's own decisions drive the result is what makes the number informative.

**D13 — Cash yield is part of the return, and is valued without a price feed.**
Fidelity's core position pays a monthly yield, booked as a `dividend` (cash in) followed by a `reinvest` into SPAXX/FDRXX (cash out, shares in). Money-market funds hold a stable $1.00 NAV by design, so they are valued at $1.00 rather than being sent to a price provider — otherwise the core position silently reads as zero. Audited against the real ledger: dividends received split into fund shares held plus residual cash — the three sum exactly, so the yield is counted once and not twice.

**D14 — Daily bars come from the consolidated feed, and the newest bar is replaceable.** *(2026-09-02)*
The cache had been built from Alpaca's IEX feed, which is one exchange. On thin names it saw a few shares a day and, on days it saw none, emitted a zero-volume placeholder bar at a stale price — ASST in April 2023 flickered between 94 and 170.50 for a month while the consolidated tape traded 85 to 122. The free plan serves the SIP feed for anything older than fifteen minutes, so daily bars now come from it with the end clamped, placeholder bars are dropped at the source, and the cache was rebuilt (191 symbols, 5,334 placeholders removed, 71 of 483 verdict readings changed — `research/audits/refeed-2026-09-02.md`). Intraday bars stay on IEX because the chart wants the current bar. Separately, `store()` now replaces the newest bar of a batch instead of ignoring it, because a daily bar fetched during the session had been frozen as "the close". The give-back on the Risk tab is measured from the first open lot rather than the whole history, since a peak from before the position existed is not something the holder gave back.

## First validated result (2026-08-29)

History backfilled to account opening: 12 windows, 5,023 transactions, 2024-06-07 to 2026-08-28. Three of the twelve windows returned zero rows, which proves the accounts did not exist before mid-2024 — so the opening value is genuinely near zero rather than an artefact of where the export began, and the return is exactly anchored.

| | |
|---|---|
| Beginning value | near zero — see above |
| Net deposits | *(withheld)* |
| Ending value | *(withheld)* |
| Time-weighted return | **+122.11%** |
| Modified Dietz | +86.39% |
| S&P 500 (index, price only) | +44.23% |
| Same deposits into SPY | **13.0% behind the real portfolio** |
| Same deposits into QQQ | **7.8% behind** |

**Cross-check:** Fidelity's own summary and our computed total came out **0.8% apart**, with the ledger built from raw transactions and no balance ever imported. Residual difference is explained by two OTC holdings valued at stale last-traded prices, and by our prices being prior close against Fidelity's live quotes.

**Caveat worth remembering:** TWR (+122%) and Modified Dietz (+86%) differ substantially. That is expected with high volatility and frequent flows, but it means neither should be quoted alone. The dollar comparison against the same-deposit benchmark is the most robust of the three figures and the one to lead with.

## Data on hand

- **Fidelity transactions, 12 months (2025-08-29 → 2026-08-28): imported 2026-08-29.** 1,908 rows across 4 CSVs in `data/fidelity/`, pulled via Claude in Chrome. Fidelity's custom-range cap is **93 days** (not 90), going back 5 years.
- **Frost personal checking, 2 years (2024-08-29 → 2026-08-28): imported 2026-08-29.** 1,302 transactions in `data/bank/frost_personal_2024-08-29_2026-08-29.ofx`. All 1,302 FITIDs unique. Mix: 1,060 DEBIT, 239 CREDIT, 3 DEP.
- Six Fidelity accounts in scope, including a Health Savings Account and an employer 401(k) via BrokerageLink — worth deciding whether all six belong in the same performance view or whether retirement/HSA get separated.

- **D14 – D59 (2026-08-29 → 2026-09-05)** are in `research/audits/decisions-D14-D59.md`, moved there unchanged on 2026-09-08 when this file reached its size budget. Still in force; this file keeps the constraints, D1–D13, and everything from D86 on.

- **D60 – D85 (2026-09-05 → 2026-09-08)** are in `research/audits/decisions-D60-D85.md`, moved there unchanged on 2026-09-12 for the same reason. Still in force; this file continues from D86.

- **D86 — The phone, second pass: every tab rendered and measured.**
  `tests/phone_shots.mjs` now renders all thirteen tabs, the Outlook card
  and the Budget sub-tabs at iPhone width and reports every element wider
  than the screen and any script error. Findings and fixes: the period and
  scope bar took 560px of every tab and is now one line ("Period, scope ·
  All time · ▾") that opens on a tap; nine tables were wider than the screen
  and scrolled sideways inside their panel (the Outlook holdings table was
  1,464px on a 390px screen), so each wide table keeps a named set of
  columns on a phone — Outlook: symbol and the three calls; Holdings: symbol,
  verdict, from peak, next rung; Watchlist: symbol, price, 1m, RS, call,
  note; Setups: symbol, call, why — applied whenever rows are added so a
  column painted later is handled; in a table the call pill drops its
  confidence word (it is on the card); the Setups reason wraps. No page
  overflows on any tab, no script errors, Holdings fits the screen exactly.
  Desktop is untouched: every rule sits under a 640px media query. Second
  sweep the same evening: the remaining wide tables (Trades, Risk's positions
  and accounts, Sectors, Research's method detail, Backtest, the account and
  alerts tables on Overview, Loose ends) got their column sets too; no table
  on any tab is wider than the screen.
- **D87 — SIVEF is read on Sivers' own years, everywhere.** The verdict
  already read SIVEF off SIVE.ST, the Stockholm listing, rescaled into
  dollars (`chart_proxy`, 2,178 bars against 115 on the OTC line), so the
  weekly and monthly calls were never thin — but the Chart tab, the Outlook
  mini chart, the sell ladder, the buy-back readings and the rung alerts all
  still read the 115 OTC bars, which is why the chart looked like it had no
  history and the ladder started in June. All of them now take the same bars
  the verdict does. On the full history the ladder ran a whole cycle on the
  spring run — a third at 1.55 on the entry day, a third at 1.44 on the
  weekly RSI 85, the rest at 6.79 when the weekly RSI rolled under 70 after
  the 10.49 peak — and re-armed on 30 June; today it is at stage 0 with
  rung 1 at 6.50, and the buy-back readings say "at the floor": weekly
  Williams %R at −94 on 28 August, 73% off the high. Not a trim. The Chart
  tab says under the chart what it is drawn from and offers the OTC line
  with one link (`?own=1`).
- **D88 — The work computer reaches the app through Tailscale Serve on
  port 80.** The PC joined the tailnet and could ping the Mac, but a TCP
  connection to :8737 failed: the work machine's security allows only the
  standard web ports. `tailscale serve --bg --yes --http=80 8737` carries the
  app on port 80 inside the tailnet (HTTPS on 443 would need certificates
  enabled in the Tailscale admin console, which they are not), answering to
  the machine's name only — `http://erics-macbook-pro/` — never the bare
  address, which Serve meets with its own "404 page not found". Written up
  in SETUP.md; the phone's `:8737` route is unchanged.
- **D89 — The archive is an app, not a folder of code.** Friends given
  `share.sh`'s zip saw source and a README and called it "a shell". Now the
  zip carries `Investment App.command` (Mac) and `Investment App.bat`
  (Windows), which find Python 3.11+ or open its download page, start the
  server and open the browser; `GETTING-STARTED.md`; and a **Get started**
  screen in the app (`app/setup_flow.py`, `POST /api/upload`, `POST /api/setup`)
  that shows the export clicks for Fidelity, Robinhood, bank Web Connect,
  cards and pay stubs, imports a dropped file on the spot into `data/` with
  the row counts shown, takes the free Alpaca price key into `data/.alpaca`
  and the filing status and age into `config.json`, and fetches prices —
  none of it by hand. Multipart parsing is standard library (`cgi` is gone in
  3.13); writes are same-origin only and go through the host guard. The
  same screen is behind "Import files / setup" on the Overview for later
  exports. What it does not and cannot do: connect a brokerage by login —
  there is no free personal API and aggregators cost money and need a
  hosted service — so "put in your brokerage" means dropping its export
  file, and the guide says so. Windows is now reachable through the .bat
  but still untested by hand.
- **D90 — Buy plans for the next session; ideas-only authors; an add is
  not "acting here" when its level is below.** The user named TEM and DGXX
  as buys "as long as they don't gap up at open — then I'd wait to see if
  they sell off a bit", and asked the app to help with daily buys. A plan
  (`app/plans.py`, set from the Outlook card, listed under "Tomorrow's buys"
  on the Overview) holds that rule as numbers: buy at or below a price, and
  a gap over N% of the prior close means wait for a pullback under the open.
  The 15-minute poll judges each plan against the day's first bar and the
  last price and alerts once per condition per day — at level, gapped,
  pulled back. Nothing is ordered. Tonight: TEM at or below 63.61, DGXX at
  or below 3.71, 2% gap rule on both. Serenity (@aleabitoreddit) is
  "great for fundamentals and finding stocks but should not be taken into
  account for buys, sells, and trims": `journal.IDEAS_ONLY_AUTHORS` — record()
  refuses their calls, the seeder skips them, the cards do not list them, and
  the three rows seeded from their posts were removed. And on MSTR: the user
  trimmed on 2026-09-01 at 124.77 while the app read HOLD at low confidence
  (the cross-check shows it as a disagreement, not an app call); three
  sessions and +14% later the monthly turned ADD with the level to act at
  123.18, and the card said "Acting here at 142.80". An add whose level is
  more than 3% below price now reads "Worth adding nearer 123.18" — the
  level to wait for, not a buy up here — and Setups already excludes it.

- **D91 — The smoke judges the backtest by its response, not by a timer.**
  The check "the Run button comes back when the run finishes" failed on the
  smoke server and passed everywhere else. The run itself was not slow — the
  monthly method is 12 seconds on a copy of the ledger — but the smoke's
  earlier tab visits leave a watchlist-scope outlook and a research scan
  running in the same Python process, and beside them the same run took 68
  seconds, while the check also pressed Run before the method's stored-run
  fetch had filled the form (the run went out with the previous method's
  parameters). The smoke now lets the stored-run response land, then waits on
  the run's own HTTP response and only afterwards asks whether the button is
  back, reporting the status and elapsed seconds on failure. A second failure
  in the same run — the empty-ledger suite reporting data on a "fresh" ledger
  — was a probe server left listening on the port that suite uses; killed.

- **D92 — The friends' launchers print a phone address.** A copy of the app
  had no way onto a phone: `phone.sh` and `install-agents.sh` are this Mac's
  tooling and are not what a friend double-clicks. Both launchers now look
  for Tailscale (the CLI on a Mac, `C:\Program Files\Tailscale` or PATH on
  Windows); when it is installed and signed in they start the server on
  `127.0.0.1` and the machine's Tailscale address and print
  `http://100.x.y.z:8737/` with the same-account instruction, and when it is
  not they print the three things to do to get one. Never `0.0.0.0` — the
  app has no password — and the test now refuses a launcher that says it.
  GETTING-STARTED.md has the five phone steps. Verified on this Mac: the
  detection finds the address and a server started with that host list
  answers on both.

- **D93 — Documentation brought current; the log archives by block.**
  A pass over every top-level document after D82–D92: test counts (52
  suites, 2,009 checks, smoke 97, empty ledger 8), the launchers and the
  Get started import route in HOW_TO_RUN.md and README.md, `plans.py` and
  `authors.py` in the module table, Windows as "starts, unverified" rather
  than "untested", Serenity's ideas-only status in the roadmap and the
  sources doc, and a 2026-09-08 "where it stands" in the improvement plan.
  This file was at its 80 KB budget, so D14–D59 moved unchanged to
  `research/audits/decisions-D14-D59.md` with a pointer here; later blocks
  go the same way. Nothing was deleted from the repository: every script
  and document is referenced from somewhere or is the record of a run, and
  the only unreferenced files are the user's own source documents.

- **D94 — The reading resolves to three prices; the percentage is gone.**
  The user: "the overall stock readings and especially notifications are
  still not helpful... what is the clear get out level. What is the clear
  buy level. I'm not looking to sell at every point of resistance and buy
  at every point of support. seems like all readings are wishy washy and
  say like 51% bullish." Four changes, all in the levels and the wording;
  no verdict on any of the thirteen holdings moved, so the replay and the
  measured record stand.
  (1) `MIN_LEVEL_TOUCHES` now gates the BUY side as well as the sell side.
  The buy level had been the nearest support below price with no strength
  test at all, which on 2026-09-09 put it within 1.3% of the last trade on
  six of thirteen holdings (SOFI 0.1%, SMR 0.5%, TEM 1.0%, IREN 1.1%, MP
  1.3%). Where price is already standing on a qualifying level, `buy_now`
  says so instead of printing a number a hair below.
  (2) The sell level reads EVERY zone above price, not `near.resistance`
  alone, and a tested level now outranks a projected one. IREN's 4-touch
  flipped zone at 49.19–52.36 had been invisible behind a 2-touch shelf,
  leaving the cycle high at 76.41 (+68%) as the call; MSTR was told to sell
  into 455.90 against a 132.70 price (+244%) because the cycle branch was
  allowed three times `MAX_TARGET_GAIN`. That allowance is now one.
  (3) Every name gets an invalidation level. It is measured down from
  price rather than from the entry, and must sit at least `MIN_STOP_ATR`
  of the name's own typical bar below price — IREN's had been 44.89
  against a 45.37 last trade, inside a single session's range.
  (4) The hold no longer reports the share it fell short of. Eleven of
  thirteen names read "the evidence is 53% bullish, short of the 65% a
  call needs"; it now says there is nothing to do at this price and hands
  over to the levels. The arithmetic stays on `tally`, behind the
  "Why this call" disclosure.
  Presentation follows the HOLDING PERIOD from `position_books`, not the
  daily/weekly/monthly grid — "the day week month thing doesn't really
  click. The values depend on the length of the trade." A trade-around
  name says SELL THE SLICE INTO, because its core is never sold. The
  longer-timeframe-outranks-shorter rule is unchanged: it governs how
  evidence is weighed, not how the answer is shown.

- **D95 — Every level carries the move it starts; the level machinery
  becomes its own module.**
  The user, on the D94 output: "If it gives me a buy level or sell level it
  should also tell me the upside or downside target of the move." A level
  says WHEN and nothing about what the trade is worth, so it cannot be
  weighed against another name or against doing nothing.
  A buy level now quotes the upside it is taken for, the invalidation as
  risk, and the ratio; a sell level quotes the pullback expected after it.
  Both targets are the next TESTED level past the one being acted at — the
  same `MIN_LEVEL_TOUCHES` gate as the levels themselves, so a target is
  never a shelf the market has touched twice. Critically both are measured
  FROM THE LEVEL, not from today's price: the reader is being told to wait,
  and a ratio off the current price describes a different trade from the one
  on offer. `quality()` still measures from price and is unchanged — it
  ranks a screen of calls rather than describing one plan.
  Reading today: CRWV 4.3 to 1 (85.37 → 122.00 against 76.77), IREN 3.1,
  TEM 2.2, SOFI 1.1, MP 1.0, MSTR 0.7. That spread is the thing a list of
  eleven holds could not show.
  This pushed `verdicts.py` to 2,453 lines against a 2,400 budget, and the
  budget's own note — "a module past this is two modules wearing one name" —
  described exactly what had happened: one file answering both "what is this
  name doing" and "so what price do I act at". `watch_levels`, `_targets`
  and `_watch_levels_for` and their six constants moved to `app/levels.py`
  (424 lines), re-exported from `verdicts` so every caller and test reaches
  them by the name it already holds. `verdicts.py` is 2,069.

- **D96 — Discovery replaces the conditions bar; the app gets a measured
  edge for the first time.**
  Twelve iterations of measurement against the user's note of 2026-09-09
  (`research/audits/edge-log.md` has the full working). Two of the three
  items in that note did not survive contact with the data, and the third
  changed shape.
  **Item 1, a market-conditions bar, is recommended AGAINST.** Bucketing
  3,613 momentum entries by the regime dial's own gauges runs backwards and
  monotonically: 0 of 3 gauges returned a 1.554 mean and 66% up, 3 of 3
  returned 1.264 and 49%. Breadth agrees. The extreme buckets are only two
  market episodes, so the defensible claim is the weaker one — there is no
  evidence a conditions gate helps and some that it hurts. **Item 2 is done
  and is what retired item 1.**
  **Exits were tested and abandoned.** Every rule loses to buy-and-hold over
  the same sample: weekly RSI 85 −3.9%, rung 1 −8.0%, trailing 30% −18.3%,
  weekly-under-10-week −22.2%, daily-under-50-day −22.8%. They are right on
  ~47% of entries and still destroy the mean, because the half they get
  wrong contains every large winner. Robust to injecting 20%
  delisted-to-zero. **The shipped sell ladder measures −2.4% against holding
  on this book and has not been changed, because it is a live trading rule
  and the user has not been asked.**
  **The edge is selection and it is in the tail.** The user's ten holdings
  average 2.95x peak against a universe mean of 2.214x, but the whole
  advantage is SIVEF (98.4th percentile) and IREN (98.3rd); the other eight
  average 1.82x, below the universe mean. So the goal is more shots at the
  tail, not a better average pick — which is what the user said in the first
  place.
  **What shipped: `discover.accumulation*`.** Dollar volume expanding 4–20x
  against its own 126-session base while the price has not yet run (run-up
  0.5–1.25). 11.5% of these reach 4x within a year against a 1.5% base rate,
  present separately in 2020–22, 2023–24 and 2025–26, and surviving a 50%
  injected total-loss rate. Verified again through the shipped thresholds
  over the kept universe: 261 episodes since 2024, 10.7% reaching 4x. It
  found IREN at 3.75 (bought at 10.47) and DGXX at 1.38 (bought at 4.42),
  and missed six of twelve holdings — a candidate generator at ~4 names a
  week, not an oracle. The 20x ceiling and the run-up floor exist because
  without them the list filled with reverse splits (CLRO at 1,900x its base)
  and the headline inflated to 15.1%.
  **And `authors.crowd`.** `research/x-mentions.py` turns the raw X pulls
  into per-account cashtag mentions; the crowd reading counts distinct
  accounts over 30 days and labels a name early / warming / crowded. Those
  cut-offs are a judgement, carry `measured: False`, and are shown as such:
  validating them needs post history from before each name ran, which is not
  on disk and which the user chose not to backfill. Coverage is reported
  beside every verdict, because "nobody is discussing this" and "the pull
  never covered that week" are the same zero — with two days on disk the
  column reads "no data", not "early". On the one pull available IREN comes
  back crowded (4 accounts) while all 23 accumulation candidates have none,
  which is the intended contrast.

- **D97 — The sell ladder is switched off.**
  Turned off by the user on 2026-09-10 after the measurement in D96
  (`research/audits/edge-log.md`, iterations 2–6). Against **buy-and-hold**
  over 3,613 momentum entries in 2,643 symbols the full ladder costs 2.4% of
  the book, and rung 1 alone costs 8% of the mean. No variant beat holding:
  rung 3 alone +0.3%, rung 1 alone −1.3%, ladder without rung 1 −1.0%. Robust
  to injecting 20% delisted-to-zero names.
  The mechanism is the mean/median split. The rungs are right about half the
  time and still destroy the average, because the half they get wrong contains
  every large winner: holding's distribution runs p90 2.35x, p95 3.13x, p99
  6.23x, and a rung truncates that tail while keeping the losses. On this book
  rung 1 fired on IREN on 2025-06-27 at 14.00 — seven days after the entry at
  10.47, into a move that reached 76.87.
  **D69 and D71 are not overturned and are not in conflict.** D71 measured the
  ladder against the user's OWN exits and it beat them on 35 of 51 fires,
  median +6%. That is still true. It was validated against the wrong baseline:
  "better than what you did" is a different claim from "better than doing
  nothing", and nobody had made the second comparison.
  **Off, not deleted.** `ladder.ENABLED = False` and `state()` returns None,
  which is the shape every caller already handled for "too little history", so
  four things go quiet together: the nightly rung alerts, the Outlook's ladder
  card, the trade-around sell level (which falls back to the strength-gated
  SELL INTO level from D94), and the buy-back screen's ladder stage. `rungs()`
  still computes, so the research scripts and the audits keep working, and
  turning it back on is one constant. `ladder.DISABLED_NOTE` carries the reason
  and is shown on the page where the card used to be — a card that simply
  vanished would read as a bug, or worse as "no rung is near".
  `tests/test_ladder.py` forces it on for the mechanics and pins the shipped
  default at off, because an implementation rotting behind a switch is worse
  than no implementation.

- **D98 — The drawdown reading: what usually happened to names that got
  this deep.**
  The user, after a week of measurement concluded that no exit rule beats
  holding: *"i want to be more effiecent and not hold through 50% downdraws
  even if it going to recover down the road."* That is a different objective
  from the one every earlier test scored. Those compared holding a name
  against holding CASH, which cash always loses; the user's capital is finite
  and a position sitting through a round trip cannot take the next setup.
  Measured three ways (`research/audits/edge-log.md`). **Rotating** out of a
  drawdown into that week's accumulation candidates: no reliable threshold —
  neutral at -20%, holding better at -30%, rotating better at -40%, on n=72
  and n=25, which is noise. A **swing slot** beside the core: clearly negative,
  monotone, and pure swing-rolling loses 37% of capital over three years.
  **Time in the drawdown**, which is the measure that matches what was asked:
  this is where the evidence backs the user. Over 6,376 events, a name down 40%
  from its own high never got back to that high 46% of the time, took 13.2
  months in the median case that did, and fell a further 52% first. At -70% it
  is 63%, 22.1 months and -66%.
  Holding still wins on the MEAN — its advantage is a minority of enormous
  recoveries — and loses on the median, the wait and the further fall. Which
  side to take is a preference, and the user has stated theirs.
  Shipped as `exits.drawdown_reading`, on every held position: depth, the peak
  it fell from, months since, and the base rates for that depth. The peak is
  measured over the CURRENT position's life, not a rolling window — three
  holdings round-tripped, and CRWV reads -22% from the position actually held
  rather than -49% from a stake that was sold. Two guards, both because the
  first version quoted rates where they do not apply: a fall past everything
  measured gets no odds and says so, and a position that crossed months ago is
  marked stale because the rates describe the day a name FIRST broke.
  **Known limitation, stated in the code**: these names doubled before they
  fell, and that subset does worse (a one-year median of 0.712 against 1.069 at
  -30%) but has only 29 events. The published table may flatter this book.

- **D99 — Following the app would not have beaten the user. Standing answer.**
  Measured after the user said *"i cant trust the app because if i did i would
  not have the performance i have today"* (`research/audits/edge-log.md`).
  Buying every name the app called buy, equal weight, ten slots, selling on a
  sell call: **12.889x** on the `replay` universe, **2.906x** on
  `replay-screen`. The gap is hindsight — 187 of `replay`'s 204 symbols are on
  the user's watchlist, against 21 of `replay-screen`'s 492. Only the
  point-in-time screen is honest, which is what `discover_universe_log` exists
  for.
  The honest 2.906x does not survive either. **Five names of 492 are 121% of
  the profit** (ALMS 42%, AAOI 33%, ACRS 26%, ALM 12%, TQQQ 8%) — everything
  else lost money together — and 0.5% round-trip costs, optimistic for
  microcaps like ALMS, take it to **1.850x against SPY's 1.763x**. It is at
  least stable across 8–30 slots at 2.8–3.3x; the 5-slot 8.467x is
  concentration luck.
  Annualised: the user ~41%/yr since June 2024, the app ~26%/yr before costs and
  ~14%/yr after, SPY ~13%/yr. **The user is right.**
  So the app's defensible role is support, not substitution: surface names not
  yet seen, show the cost of waiting in a drawdown, keep the books right, and do
  not tell them to sell winners. Anything that overrides a decision must clear
  ~41% a year.
  Logged as the standing answer because every brilliant backtest in this project
  has dissolved on inspection — 12.889x was survivorship, the accumulation
  scan's "11.5% reach 4x" was a peak statistic that compounds to 1.011, and the
  sell ladder passed two validations against the wrong baseline before D97 took
  it out.

- **D100 — Alerts: four at most, and only when something was actually
  given up.**
  The user: *"When market opens i get smacked with like 20 notifications and i
  dont have time to read them all."* The record agreed — 17 to 26 a day through
  early September and **every one sent**, because nothing capped it. Twenty
  individually well-worded alerts are functionally zero, so the wording work
  of D76 never reached them.
  **Fewer fire.** Price being NEAR a level is no longer an alert, in any of the
  three places it was: the engine's buy-at / trim / stop at 1.5%, the user's own
  drawn levels, and the buy-at intraday. That was **103 of the last 138
  alerts**. Approaching a number is an event, not a reason to act — the level
  has not been reached and no action attaches to it, and the levels are on the
  Outlook and drawn on the chart for when they look. The intraday buy-at went
  for a second reason: the buy level sits near price by construction, so it
  fired on most names on most days, and buying is decided at the desk.
  What still fires: a verdict that CHANGED, price THROUGH the stop or the trim,
  price below the level that flips the call, earnings inside five days, and the
  tier / wash / regime / sentiment alerts unchanged.
  **Fewer are pushed.** At most `max_push` (default 4) notifications leave the
  machine per run, ranked by severity and then by the dollar value of the
  position — a level given up on a $191,820 holding outranks the same event on
  an $86 one, which is the ordering the Overview already uses. Everything above
  the cap arrives as ONE digest naming the symbols. The digested ones are marked
  sent, because they did reach the user inside the digest and leaving them
  unsent would fire them again on the next 15-minute poll — the flood this
  exists to stop.
  Checked both ways: against today's real data it produces **0 alerts**; against
  a synthetic day where a verdict flips and two levels are given up it produces
  4, while a name sitting 0.4% above its buy-at stays silent.
  **Known risk**: about 75% of alert volume was cut on a judgement about what is
  useful. If the near-stop warning turns out to have been wanted as a heads-up,
  a narrower version — within 1.5% of the stop only, on positions above a size —
  is the thing to add back.

- **D101 — Five endpoints were reporting the last day you traded as though
  it were today.**
  Found while verifying a CRITICAL finding rather than trusting it. Diagnose
  reported a portfolio drawdown of **-41.2%** when the real figure that morning
  was **-38.8%**, because `diagnose_payload` defaulted its window to
  `MAX(txn_date)` — the last day a transaction was imported, 2026-09-03 — and
  not to the last day there is data for. The arithmetic was correct throughout:
  the max drawdown of -55.7% matched an independent calculation exactly. It was
  purely the window.
  `_build` had already hit this exact bug and been fixed, with a comment
  explaining why: prices arrive nightly over the network, transactions only
  when an export is downloaded by hand, so pinning a window to the last
  transaction freezes the view on the last import. **That fix had never reached
  the other five** — Diagnose, Watchlist, Backtest, Methods and Theses. Stop
  trading for a month and every one of them would have been a month stale while
  prices moved. A stale number wearing a CRITICAL label is worse than no number.
  All five now go through one `web.data_end(conn)`: the later of the newest
  price and the newest transaction, falling back to today on an empty ledger.
  `tests/test_integrity.py` asserts the behaviour and also asserts that the
  string `MAX(txn_date) d FROM transactions` no longer appears in `web.py` at
  all, so it cannot come back one endpoint at a time.

- **D102 — The performance budget tests time twice before failing.**
  `test_performance_budget.py` failed at 5.11s against a 3.0s budget and 25.05s
  against 15.0s on 2026-09-10, then passed 37/37 alone on unchanged code minutes
  later. The budgets have four to five times headroom, so this was contention —
  the full suite runs a server and a headless browser alongside it — not drift.
  It now times once and re-times only if something missed, keeping the better
  result. A genuine regression misses on both runs and still fails, verified by
  squeezing a budget to 0.0001s and confirming the failure with "missed on BOTH
  runs". This matters for the same reason the alert cap does: an alarm that
  fires when nothing is wrong teaches people to ignore it, and these tests guard
  a regression that once put the dashboard at thirty seconds to first paint
  while 415 other tests stayed green.

- **D103 — The broker's cost basis is imported; the ledger says when it is
  behind.**
  The user checked the app against Fidelity on their largest position:
  *"iren according to yahoo says 4227.912 shares averqge cost of 19.63 and
  market values of 184,506.08 with 101,518.07 in gains as of today"*. The app
  said $25.69 a share. The share count matched to four decimals, so the
  disagreement was entirely about **which lots count as sold**: FIFO $25.69,
  LOFO $26.13, the broker $19.63, LIFO $18.82, HIFO $18.79. Sitting just above
  LIFO is the signature of specific-lot selection — picking high-cost lots to
  sell — so no rule reproduces it and `app/broker_basis.py` imports the figure
  instead of deriving it. Total contribution per name is unaffected, since
  profit does not depend on lot method (IREN's $109,803 matched an independent
  $109,792); what was wrong is the basis and the realised/unrealised split.
  Applied only where the broker's share count agrees with the ledger's. Six
  positions took it; four refused — DGXX, TEM, MSTR, ASST — and stay on FIFO
  with the reason attached, because applying a basis for 20,226 shares to a
  ledger holding 18,125 would overstate the cost of every one and look
  authoritative doing it. Every position carries `basis_source`.
  **And the bigger finding underneath it.** Reading the broker's positions
  showed the ledger a week behind: DGXX short 2,101 shares, TEM 53, MSTR 8,
  ASST 47 too many, and an entire FPS position — 721 shares, $23,229 of basis
  — absent. The last Fidelity export ends 2026-09-03. Every figure the app
  produced that day was computed on a book the user no longer held, and nothing
  said so. Diagnose now opens with a **critical** finding when the broker's
  share counts disagree with the ledger's, naming the positions and the action.
  Deliberately not "days since the last import": a quiet week looks identical
  to a broken one, while a share count only disagrees when transactions are
  actually missing.

- **D104 — Two tabs for two things that already existed and could not be
  found, and the charts nobody had shown.**
  The user, on an app they use daily: *"I feel like acouple of things are hard
  to find. Tab wise something like having a tab for AI Trade Bot, New Stocks.
  … Why are there charts for the value trader but not anyone else?"* Both of
  the tabs they asked for were features that had shipped — the accumulation
  scan at the bottom of **Setups**, and the paper account at the bottom of
  **Backtest**, which is where somebody looks for a historical simulation and
  not for a live bot. A feature nobody can find has not shipped.
  **New Stocks** now holds everything about names not in the book: the nightly
  scan, and the followed accounts' charts, filterable by symbol with a "hide
  names I already hold" toggle. **AI Trade Bot** holds the paper account, which
  reads −10.42% since 2026-09-03 against SPY's −1.98% — the app trading without
  the user, on its own tab, saying plainly that its calls are not worth
  following.
  **The charts.** There was no reason StonkChris's were not shown. The Value
  Trader's are displayed because his levels exist ONLY on the image; StonkChris
  writes his out, so `substack_levels.py` was built and the images were never
  used. `app/substack_charts.py` splits on the same `TICKER (1D)` header the
  level parser uses — deliberately, because when those two disagreed about
  where a block started, SPCX's prices ended up on SATL (D103's sibling bug).
  120 charts across 84 names.
  Names left alone at the user's request: Setups and Trades keep their names.
  **And a gap the suite had.** Both harnesses carry HARDCODED tab lists, so the
  two new tabs passed by never being tested — the suite was green on fifteen
  tabs while looking at thirteen. The list is hardcoded on purpose, because it
  catches a tab disappearing, but it cuts both ways. Both lists updated with a
  comment saying so; browser smoke went from 97 checks to 99.

- **D105 — A video with no transcript is readable, and the pipeline is the
  deliverable.**
  Cantonese Cat posts his work as a screen recording with no description, no
  chapters, no tags and no caption track. The list of names existed only as
  pixels. `research/video/` reads one end to end in about fifteen minutes:
  `yt-dlp` for the streams, a Swift tool using AVFoundation and Vision to OCR a
  frame every five seconds, a parser that collapses those into one segment per
  chart, symbol resolution against the ledger and Alpaca's asset list, and
  whisper.cpp for the commentary. Everything is free and most of it ships with
  macOS. The user's steer — *"I would like to automate this task in the
  future"* — is why this is a script and a README rather than a list of names.

- **D106 — Prove each chart is the ticker claimed, from a second part of the
  frame.**
  A ticker came from OCR of a company name and a fuzzy catalogue match — two
  guesses stacked, with nothing to check them against. TradingView also prints
  the OHLC of the bar under the cursor, and four prices together identify one
  stock in one month, so every quad read while a chart was up is matched
  against real daily, monthly and quarterly bars of the resolved ticker. All 34
  equities and Ethereum verified, against bars from 2017 to 2026; gold, silver,
  copper and the two indices have no free source and are reported UNCHECKED
  rather than counted as passing. It also reports stretches of video where no
  chart header was read at all — a chart whose header never OCRs leaves no
  trace, and the list would simply be one name short.

- **D107 — The levels an author draws, on the user's own names.**
  The user: *"i want to look at a holding or potential trade and see what they
  say the upside/downside is (buy levels, drawdown levels, targets)."* The
  commentary says "this wants to go to 1.618"; the chart draws that as a real
  price in the right-hand axis. A second OCR pass reads the Fibonacci ladders
  into `author_levels`, the same table the Substack and X extractions feed, so
  they appear per name in the Outlook card with no UI work — 163 levels across
  33 names from one video. Five per name: the next two up, the next two down,
  one beyond. Three guards: each ratio's price is the most common reading
  across the segment; a ladder must rise with the ratio; a ladder must BRACKET
  the current price. Width proves nothing — PLTR's runs 5.92 to 593.88 on a
  twenty-year log chart, and a width-based guard rejected exactly the charts
  worth keeping.

  **A UI bug this surfaced:** the per-name list of followed-author levels was
  filled in strict recency order and capped, so IREN showed two targets and not
  one level below price — half the question. It interleaves target, buy zone
  and downside now, so a name always says where it goes and where it goes if
  the call is wrong.

- **D108 — The research pulls run themselves.**
  The mention history was three days long, because the X pull was a paste into
  a browser console once a week. A manual step that has to be remembered is a
  manual step that does not happen, and "early" means nothing until months sit
  behind it. `app/xpull.py` makes the same GraphQL calls from Python against a
  session in `data/.x`, at 02:10; `app/ytpull.py` reads seven YouTube channels
  at 04:00. Both feed `x_mentions` under the same handle per person, so
  somebody on both platforms counts once.

  Four things worth keeping:

  * **The session is the only way in.** X's API starts at $100 a month. Query
    ids turned out to be readable WITHOUT a valid session, but only from
    `x.com/home` — `x.com/` serves a logged-out bundle whose 117 chunks contain
    none of the authenticated operations.
  * **Deliberately slow.** 150s an account; the browser script used 3.5s and hit
    HTTP 429 at about twenty. A nightly job has all night.
  * **Checkpointing is not optional.** The first full run was killed by memory
    pressure at fifty minutes and lost everything, because it only wrote at the
    end. It now writes after every account and resumes; a partial pull is never
    used as the next run's starting point, since its timestamp covers only the
    accounts it reached.
  * **Terms.** Automated collection is outside X's terms of service. Same
    position as the Yahoo price fallback: written down, the user's call.

- **D109 — What a video is about, when nobody says "dollar sign".**
  Across 26 transcripts there was not one cashtag in spoken text. Two attempts
  at name matching produced confident nonsense and are recorded in
  `app/ytpull.py` because they are the reason for the rules: matching the first
  word of every tradable company name gave `where` → WFCF, `three` → TLACU and
  `hello` → MOMO, the tradable universe being 13,000 deep with a tail of
  ordinary English; restricting that to the 206 tracked symbols was close, but
  skipping short leading words turned "Nu Holdings" into the alias `holdings`.
  What survives: the literal first word, four letters or more, not in
  `/usr/share/dict/words`, not a corporate word, unambiguous across the tracked
  set, plus a two-word phrase where the first word alone is too common — the
  only way "Advanced Micro" and "Rocket Lab" are reachable. 140 aliases from
  206 symbols; Apple, Target and Block cannot be matched at any threshold. So
  it confirms interest in tracked names and does NOT discover new ones, and the
  coverage figure is printed every run because a name that cannot be matched
  looks exactly like a name nobody mentioned.

- **D110 — Never put a secret on a command line.**
  A setup step read `printf ... 'PASTE_AUTH_TOKEN_HERE' > data/.x`, which is two
  actions wearing one number. Taken as written it wrote the placeholder to the
  file, and the real token went in on its own line where the shell tried to
  execute it — leaving it in shell history. `x-setup.sh` reads both values with
  `read -rs`, removes and recreates the file under `umask 077`, tells the two
  cookies apart by shape so the order does not matter, and names which value is
  wrong when one is. Three separate paste failures were survived this way; each
  produced a specific message instead of a misleading 401.

- **D111 — The 2026-09-12 review: six audits, two phases.**
  Six read-only audits (navigation, appearance, front-end performance,
  back-end and database, security, code health with a full test run) were
  run in parallel and consolidated in `research/audits/app-review-2026-09-12.md`.
  The findings fell into two kinds, and they are handled in two phases so
  that nothing the user relies on daily moves without their say-so. Phase 1,
  done the same day, changes no screen: wrong numbers, silent failures,
  speed, security and data lifecycle. Phase 2 — the reorganisation into seven
  question-named sections with one symbol page, and the TradingView-register
  design system — is specified there and waits on the user's go.
- **D112 — Where the broker's basis is used, every derived figure is the
  broker's.** `broker_basis.apply_to` rewrote cost, average cost and the
  unrealised dollars but not `unrealised_pct`, so IREN showed +$102,321
  beside +70.6% (the FIFO figure; the broker's is +123.3%). The test suite
  was green because nothing asserted on the column. Now the percentage is
  recomputed from the same cost the dollars use, the test checks that the
  two agree, and the Holdings row says which basis it is on — `broker · as
  of <date>`, or `FIFO — broker count ≠ ledger` where the two disagree and
  the position stays on FIFO (MSTR, today).
- **D113 — A write needs a token the page was given; a read does not.** The
  cross-site guard checked `Sec-Fetch-Site` only when a browser sent it, and
  browsers do not send it to a plain-HTTP address that is not localhost — the
  phone and Tailscale paths, exactly where the app is opened up. The server
  now mints a token into `data/.token`, injects it into the page, and refuses
  any state-changing request (`action=`, POST, and the endpoints that write
  or reach out: backtest, replay, rotation, valuetrader, amazon, macro
  research) without it. Plain reads stay open so `curl` and the smoke test
  keep working; outside callers pass `X-App-Token: $(cat data/.token)`.
  With it: an unverified IMAP context replaced by a verified one, symbols
  validated at the boundary, a CSP on the page, and `share.sh` builds its
  tree without `research/audits/`, the seed scripts, the video notes and the
  PDF rather than refusing.
- **D114 — The response cache is invalidated by an epoch, not by the file.**
  Keying the cache on the ledger's mtime meant every write anywhere — the
  15-minute poll, a 5-minute chart open storing intraday bars, a price-cache
  refresh — dropped every cached answer, and the next Outlook open paid the
  full 48–100 s of watchlist scoring again. Now a connection marks itself
  dirty on any write outside the quiet tables (`intraday_bars`,
  `price_fetches`, `meta`, `verdict_cache`) and bumps a stored epoch on
  commit, so a writer cannot forget to invalidate and a quiet write cannot
  invalidate. Beside it: single-flight so two identical misses compute once;
  rolling-window indicators that return the same values in a third of the
  time (a test asserts equality against the rescan on random series); a
  `verdict_cache` warmed nightly for the watchlist; `last_bar_date` and
  `last_sessions` through the primary key instead of a table scan; gzip,
  HTTP/1.1 and ETags; `/api/health` that says whether the running process
  is behind the code on disk, checked at the end of `run_tests.sh`.
- **D115 — The replayed calls live in their own file, and the ledger is
  pruned nightly.** 55% of the 759 MB ledger was the replay set of
  2026-09-04/05 (331,764 decisions, 6.6 M evidence rows), reproducible by
  `app.replay run` and read only by the measure and calibration tools; 32%
  was price history for 2,709 discovery-universe names never held or
  watched. `split_replay.py` moves the replay rows to `ledger-replay.db`
  (attached by the modules that read them; a fresh clone works without it),
  `retention.py` prunes discovery bars past a sliding two years plus old
  hits, alerts, intraday bars and orphan fetch rows, and `update.sh` only
  VACUUMs when the server is not loaded. `backup.sh` now runs from launchd
  at 19:30 — it had never been scheduled and the newest snapshot was ten
  days old — keeping seven nightly full snapshots plus one a month, and a
  curated few-megabyte copy of every hand-entered table for ninety days.
  Everything the app shows is unchanged; the measure and calibration
  fingerprints were identical before and after on a copy.

- **D116 — The held peak is the intraday high, not the highest close.** The
  user remembered SIVEF "close to 700 or 800%" on Fidelity; the app said
  +648%. Cost was identical both ways ($1.4023, the ledger's four buys with
  fees and the broker's $15,425 on 11,000 shares). The gap was the bar:
  the app took the highest close (10.49 on 2026-06-17) where the position
  had actually traded at 11.25 on 2026-06-02 — +702% on cost, the figure
  the broker's screen showed at the time. `risk.position_moves` now takes
  the day's high (falling back to the close where a bar has none), so the
  give-back is measured from the most the position was ever worth; IREN's
  peak becomes 76.87, DGXX's 9.20. The column and the Risk tab say so.

- **D117 — Seven sections named for the question, one page per name.** The
  2026-09-12 review's reorganisation, agreed with the user on 2026-09-13 —
  names as proposed, Overview as the landing screen on both desktop and
  phone, every name click opening the full symbol page, nothing dropped —
  shipped in four verified commits so any one could be stopped at: the
  shell (every old tab folded in unchanged, old hashes redirecting), the
  look (the TradingView-register token set in light and dark with a toggle,
  one card, one table, one badge and one button system), Today as one
  ranked list with the symbol page behind every name (Chart · The read ·
  Plan & levels · Who I follow on it · My trades) and Setups rows leading
  with the three prices, and the chart — last year of bars by default, the
  user's cost, fills, drawn levels and plan prices the only 2 px solids, the
  app's S/R and trendlines 1 px dashed, the verdict's three prices drawn on
  the axis. The Chart's second "Technical read" engine was kept as a labelled
  second reading rather than removed. Each commit ran every suite and was
  screenshotted at 390 and 1440 in both themes before the next began.
- **D118 — A bar's low below a fifth of its open and close is a bad print.**
  SPY's consolidated bar for 2026-02-02 came from Alpaca with low 68.64
  against 685.90 / 691.70 (Yahoo: 685.78) and squashed a year of SPY into the
  top tenth of the chart. The feed itself carries it, so the nightly refresh
  could never have fixed it. `prices.store` now clips such a low to the
  lower of open and close — a real crash moves the close too, so the rule
  cannot fire on one — and the stored bar was corrected by hand. No other
  bar in the ledger met the rule.
- **D119 — The page's script is nine files, one per section, sharing one
  scope.** dashboard.html reached 9,000 lines with its budget raised five
  times in two days, every raise noting the split as the next job. The
  inline script is now `app/static/core.js` (helpers, the token fetch
  wrapper first, theme, settings, the router) and `money`, `today`,
  `stocks`, `follow`, `bot`, `symbol`, `chart`, `budget`, loaded by plain
  `<script src>` tags in that order; the page keeps the stylesheet, the
  markup, the four-line theme script in `<head>` and a one-line `init()`
  call. Classic scripts, no modules and no bundler: top-level functions,
  `let` and `const` are visible across all of them exactly as they were in
  one file, so every function moved whole and nothing was renamed. The
  server already served `static/*.js` with an ETag and `no-cache`, so an
  edit is live on the next load with no restart. `test_dashboard.py` reads
  the files concatenated in tag order and checks the tags, each file's
  parse and the whole for a duplicate top-level declaration;
  `test_size.py` budgets each file and the sum. The same commit made the
  smoke test wait on conditions instead of the clock (68 s → 45 s with the
  same 169 checks); its outlook warm-up, once ~170 s, is a second from the
  verdict cache and now prints its time.
- **D120 — Holdings shows the headline call, and the DCA tier is labelled
  as sizing, not a call.** The user's first question after living with
  Phase 2: "why do DCA and Add not agree? DGXX is 3x DCA but a hold." The
  Holdings "Verdict" column was the DAILY read — the one timeframe the
  replay found carries no information — while Today, the watchlist and the
  name's page showed the headline (monthly add, low). One name, two words,
  same night. The column is now the headline with its timeframe, the same
  everywhere. The DCA tier answers a different question: RonnieV's ladder
  sizes a contribution you were already making by how oversold the weekly
  Williams %R is (DGXX at −88 is his 3x), and a weak short-term chart is
  exactly when that ladder scales up. Its cell and the note under the table
  now say so.
- **D121 — The tax floor counts the taxable account's year.** It stopped at
  deposits and the pay stub, so $80k of sales in the taxable account showed
  the same tax as none. `taxes.investment_income` reads the FIFO-closed
  lots of the taxable account only (reverse splits restated, wash-sale
  losses added back, netted as the return nets them, a net loss capped at
  $3,000 with the rest carried), dividends and interest as ordinary income,
  and a long-term gain at its own rate stacked on ordinary income
  (`ltcg_tax`, Rev. Proc. 2025-32). The panel shows the trades row, the
  dividends row, the tax the account added to or took off the bill, and
  the withholding gap is now worded as "paid in less than the floor owes:
  expect to owe at least this much". Still a floor: the broker chooses
  lots per sale, and the ledger cannot tell a qualified dividend from an
  ordinary one, so it errs high on that and low on everything else.
- **D122 — The followed accounts' calls are recorded the night they are
  posted, from the pull the app keeps.** The user: "we should be keeping a
  record of calls made by who I follow and how they are doing. It has to be
  going forward, so if they delete old posts the numbers aren't skewed."
  Until now a person read the pull file and wrote `research/x/calls/<date>.json`
  by hand — twice, ever. `app/xcalls.py` reads each new post for one or two
  cashtags and a claim in words near them (bought, adding, breakout, higher
  low; sold, trimming, lower first, wait for a pullback…), records it as an
  `outside` call priced at that day's close with the matched words in the
  rationale and `confidence='auto'`, and remembers the tweet id in
  `x_calls` so nothing is recorded twice and nothing is ever re-read from a
  feed a poster can edit. A post that says both things is skipped rather
  than guessed; a chart posted without words is not read; a hand-recorded
  call for the same author, name and day wins. The graded table marks the
  automatic rows "auto" with the × to remove a wrong reading. The first pass
  over the two pulls on disk found 17 calls in 131 posts, 9 new.
- **D123 — The Substack is pulled nightly too, with a stored session.**
  The posts were fetched once by a receiver fed from the logged-in browser
  tab (D50) and never again, so the charts, levels and graded calls from it
  stopped at that day. `app/subpull.py` reads the publication's own archive
  JSON (public) and each new post's body (whole only with the reader's
  `substack.sid` cookie, the teaser without it), writes the same .json and
  .txt the receiver wrote so nothing downstream changes, and refuses to
  write a teaser — a lapsed cookie is a STOPPED line in `logs/subpull.log`,
  not a folder of paywalls. `research/substack-nightly.py` at 03:30 then
  runs the call seeder and the level seeder. `./substack-setup.sh` stores
  the cookie the way `x-setup.sh` does. The publication list lives beside
  the gitignored folder, in `research/substack-publications.txt`.
- **D124 — What the app cannot pull, said plainly.** Cards, the bank and
  Fidelity have no API and no cookie that a nightly job could carry; their
  exports need a signed-in browser (SETUP.md, "Monthly statement pull",
  which Claude can drive through the Chrome extension). That stays the
  monthly routine. The user asked for all three automated on 2026-09-13;
  this is the answer, recorded so it is not re-investigated.
- **D125 — What cannot pull itself is asked for, weekly, once it is
  overdue.** `alerts.statement_reminders`: an account whose newest
  transaction is 35 days old raises a warn alert naming the account, the
  date the export ends and the folder the file goes in; the pay stub at 45
  days. Keyed to the ISO week, so it comes back every night's run until the
  file lands and never twice in a week. Fidelity's brokerage, retirement and
  HSA accounts are one reminder, dated by the newest, because they are one
  export. Today shows it as "export due" with the route in words.
- **D126 — The recurring list is by brand, a bill that reprices is still a
  bill, and every price it billed at is on the row.** The user could not
  find car insurance, Norton or the renters policy. Car insurance was there
  as a "habit" beside the groceries: 993 → 960 → 1,110 → 1,380 across four
  half-years put its spread over the drift line, and the one recurring
  charge most worth watching for a rise was demoted for rising. Norton
  billed on the same day two years running and read "irregular" because one
  interval could never satisfy a "two must fit" rule. The renters policy
  was two charges, uncategorised, and dropped. And the same product reached
  the list under three descriptors (NETFLIX COM / NETFLIX INC, three
  spellings of Google One), each with too few charges to be "sure". Now:
  `BRANDS` maps descriptors to one name (a list, not a rule); the bill
  categories — Subscriptions, Insurance, Utilities, Rent — and any
  long-cadence charge whose steps are under 40% stay subscriptions whatever
  the amount does; one interval within tolerance is a cadence; and each row
  carries `history`, every distinct price with the day it started, shown as
  "$993.50 → $960.50 → $1,109.50 → $1,379.50 +39% since Jan 25". The rises
  table reads from those steps rather than the two medians, which had put
  Claude's "was" at −$74 once a $213 charge landed among the $21 ones; a
  price that billed once is in the chain but is not a rise until it repeats,
  except on a cadence longer than quarterly where every term bills once.
  Two Insurance rules were added for the Progressive descriptors.
- **D127 — The charts the followed accounts post are saved by account, and
  shown beside everyone else's chart of the same name.** The user's answer
  to the image-reading trade-offs: do not read them, pull them in by
  account, and let two people's charts of one ticker be compared. The X
  pull now keeps each post's photo URLs (`xpull.posts_for`), and
  `app/xcharts.py` saves the files the same night to
  `research/x/images/<handle>/<tweet_id>-<n>.jpg` with the day, the
  account, the post's cashtags and its words in `x_charts` — the file is
  the app's from that night, like the calls (D122). Nothing is read off
  the image; a chart's name is the cashtag in its post, and one posted
  without a cashtag is kept under the account with no name. Who I Follow →
  Their charts is one grid over X, the Substack and the Patreon, filtered
  by who, name and dates, and "side by side, by name" groups the charts by
  ticker with the newest from each person first, names charted by the most
  people at the top. Served by `/api/x-charts` and `/chart-x?id=&n=`; the
  image route serves only a stored path under the images folder. A
  seven-day re-pull was run the same evening so the grid did not start
  empty; the nightly carries it from there. Reading the images (OCR first,
  free; a vision model if that leaves too much) stays open.
- **D128 — A friend installs nothing.** Friends were still failing to get
  the archive running (2026-09-14). The two walls were the ones D89 left
  standing: Python — the Mac's own `python3` is a stub that wants the 1 GB
  Xcode tools, and python.org is an installer and a lost evening — and
  Gatekeeper, whose "cannot be opened" dialog on macOS 15+ no longer offers
  the right-click Open the guide described. Now both launchers use a real
  Python 3.11+ when one is there and otherwise fetch a private copy with
  `uv` (astral.sh's free single binary, into the user's home, no admin, no
  PATH, ~30 MB once) and run `uv run --no-project --python 3.12 python -m
  app.web`; python.org opens only when that fails. The Mac launcher clears
  the quarantine flag from the folder once it is running, so whichever way
  it was first opened, the next double-click just works; the guide gives
  the three ways past the block (Settings → Open Anyway on 15+, right-click
  Open on older, and `bash` + drag in Terminal, which always works) and the
  Windows SmartScreen click. The Windows batch was restructured without
  `( )` blocks around a runtime `set`, which cmd expands before the block
  runs. Verified here: `uv run --no-project --python 3.12` imports the app
  in 4 s with the interpreter cached; the smoke's launcher checks cover the
  rest. Still not a signed app: that costs $99 a year and the rule is zero.
- **D129 — A fresh copy shows the whole app before a single export exists,
  and prices need no key.** After the launcher, a friend met an empty ledger
  and a form asking for exports they had not gathered — at that moment the
  app is a form. `app/sample.py` writes a made-up year for one household
  (a taxable brokerage with six real tickers and their dividends, a checking
  account with pay, rent, bills and card payments, a credit card with the
  spending, a Netflix price rise) in the SAME formats the real exports
  arrive in and imports it through the same importers, so what a friend
  sees is what their own files will produce. Every account is named
  "Sample"; the files are deterministic; loading refuses a ledger with any
  transaction in it and clearing refuses one not marked as sample, so
  sample rows can never sit beside real ones; clearing deletes only what
  the importers write. Get started offers **Load sample data** on an empty
  ledger and **Remove sample data** on a sample one, both reloading the
  page. And the Alpaca key was presented as a required step with the price
  button disabled until it was saved, when the fetch already falls through
  to Yahoo without one (`prices.OTC_FALLBACK`): `refresh_prices` now prices
  the holdings key or no key, the button is live from the start, and the
  key is a folded "optional — the better feed". Both launchers open the
  browser when the app is already running instead of failing on the port.
  The empty-ledger test round-trips the sample year (14 checks; a friend
  with no key sees six holdings priced from Yahoo in about 12 s). Found on
  the way: the automatic outside calls (D122) had filled the newest sixty
  journal rows and pushed every one of the user's own out of Money → Trades;
  the payload now carries the user's own calls as their own list.
- **D130 — The archive has to travel as a link.** Gmail refuses any zip
  that contains a `.js` or a `.bat` — this one holds thirteen — so an
  emailed archive may never have arrived intact, which fits two rounds of
  "no luck" better than any launcher fault. `share.sh` now pushes the same
  clean commit to a remote named `share` when one exists (a PUBLIC repo
  holding nothing but that branch) and prints the direct download URL
  (`…/archive/refs/heads/main.zip`); the Desktop zip stays for AirDrop.
  The user said "yes, make it public" the same day: the repo is
  `eric4burns/investment-app-share`, the `share` remote, one commit, and
  the download link is `…/archive/refs/heads/main.zip`; in the shared tree
  the getting-started guide is `README.md` (GitHub's landing page) and the
  developer's README is `README-DEVELOPERS.md`. The same
  pass: both launchers refuse to run outside the unzipped folder and say
  so (Windows opens a zip as a folder without extracting it, and a .bat
  run from there dies in a temp folder before anyone can read why); the
  guide gives Extract All; "reload the page" is a **Show it in the app**
  button after an import rather than a numbered step; and the guide says
  plainly that it cannot run ON a phone, only be opened from one.
- **D131 — Every Substack chart is read, not the newest dozen.** The user
  asked on 2026-09-17 why Their charts had no StonkChris chart of FPS. He
  has charted it four times; the last was 2026-08-04, and seventeen posts
  came after it. `substack_charts.charts()` opened only the newest twelve
  posts (about two weeks of him) and the payload then cut the result to
  120 rows, so the tab never held more than the most recent fortnight and
  its "every name" list was a fraction of what is on disk. Both limits are
  gone: all 261 posts parse in under a second into ~1,800 charts of 413
  names, the answer is cached and gzipped (340 KB over the wire), and the
  tab already narrows by name and date and shows at most eighty cards. A
  caller may still pass `limit_posts`; nothing does.
- **D132 — The URL guard let only http(s) through, so every X and Patreon
  chart was a blank card.** Same day, same question: "there is an FPS chart
  from September". There is — his X post of 2026-09-15, two images, saved
  by the nightly pull and served by `/chart-x`. `safeUrl()` passed only
  `http(s)://`, so the app's own `/chart-x?…` and `/chart-image?…` came out
  as `#` and every chart from X (since D127) and from the Value Trader's
  Patreon rendered as a card with text and no picture, which is exactly
  what a chart that was never saved looks like. The Substack ones showed
  because they are CDN URLs. The guard now also passes a path with a single
  leading slash (`//host` stays refused); the smoke test checks the guard's
  five cases and that no card on Their charts has lost its image. What is
  and is not read, since the user asked: the Substack pull takes each post's
  body only — not its comments (all eight September posts have none) and
  not Substack Notes or Chat, where "shared in my group" would live; the X
  pull covers his X posts and their images. Nothing else of his is fetched.
- **D133 — The symbol page shows the charts posted on X about the name.**
  Third time, same day: "there is no Sept 2026 FPS chart in the app". The
  user looks a name up on its own page (Chart → Follow), and that page asked
  only for the Substack's charts of it, so his X post of 2026-09-15 — FPS's
  only September chart, and the one the user meant all along — was on the
  Their charts grid (after D132) and nowhere on FPS's page. The X charts
  endpoint takes `symbol=` (matched in SQL on the comma list, so a name's
  whole history comes back), the page asks for it beside the Substack's and
  renders both newest first with where and when on every card, and the
  smoke test checks that a name charted on X shows that chart on its page.
  The lesson for the next "why isn't X in the app": look everywhere the app
  shows that name, on the page the user actually opens, before answering.
- **D134 — One person is one entry in the Who filter.** Fourth round, and
  this time reproduced in the user's own browser rather than a headless
  one: "I am looking under Who I Follow and filtering. It is still not
  there." The X rows named their author "StonkChris (@StonkChris)" and the
  Substack rows "StonkChris", so the Who list had two of him; picking the
  natural one showed his Substack charts only, and with FPS chosen the grid
  ended on 2026-08-04 whatever the date filter said. The X rows now carry
  the bare name (the handle kept on the row), so one person is one entry
  and the side-by-side view no longer counts him as two people. The smoke
  test checks that no Who entry carries an "@handle" and none repeats.
  Verified with Claude in Chrome on the user's tab, filters as he sets
  them: 6 charts of FPS, May 25 to Sep 15, the X card first. The other
  thing that hides FPS by design: "hide names I already hold" — FPS is
  held.


## Open questions

1. Which analysts to encode first — biggest open item, most shapes the build.
2. Old MacBook Pro: model year and macOS version (`sw_vers`), plus battery health. **Deferred — machine not accessible right now.** Does not block anything else.
3. ~~Which bank and card issuer~~ — **answered.** Frost resolved in-product (Web Connect, 2-year OFX export — good enough). Chase, Amex, Capital One still need their export paths mapped. See D8.
4. Robinhood crypto algo experiment: early or later? **Partly answered** — the
   equity side is now imported (see `06_feature_roadmap.md` §3). Crypto is still
   outside the ledger entirely because the activity report excludes it, so the
   experiment cannot be measured against real positions until that is fixed.
5. How much Fidelity history to import at seed (1 year = 4 CSVs, 3 years = ~12).
6. Anything in Fidelity's or TradingView's UI worth preserving rather than redesigning.
