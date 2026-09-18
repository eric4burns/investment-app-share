# Investment App — Feasibility & Competitive Research (reference)

> **Superseded for planning purposes by `02_free_build_plan.md`.**
> This file remains the reference research on the paid/commercial landscape — vendor
> pricing, licensing rules, and the competitive analysis. Use it when evaluating an
> upgrade. The operative build plan is the free one in `02`.

_Research date: 2026-08-28. All prices/limits verified this date; re-verify before committing._

---

## 0. Verdict at a glance

| # | Item from your notes | Feasible? | The real constraint |
|---|---|---|---|
| 1 | Pull Fidelity account values + positions | **Yes, read-only** | Fidelity has no retail API. Must go through SnapTrade (OAuth, read-only, no trading). ~$0–2/mo at your scale. |
| 2 | Returns charts over time periods | **Yes** | Not a data problem, a *methodology* problem. Needs TWR + cash-flow handling to be honest. |
| 3 | Compare vs S&P on same plot | **Yes, easy** | Must normalize (indexed to 100) and use TWR, or the comparison lies. |
| 4 | TradingView-style custom charting | **Yes** | Lightweight Charts is free/Apache-2.0 but ships **zero indicators** — you build the indicator layer. |
| 5 | Pull X posts from specific follows | **Yes, cheap now** | X killed the free tier; pay-per-use is $0.005/read. A personal follow-list is a few dollars a month. |
| 6 | Watchlists + organization | **Yes, trivial** | This is where you can beat everyone with taste, not tech. |
| 7 | Theoretical/paper account | **Yes** | Alpaca paper trading API is free and real. Best-solved item on the list. |
| 8 | Automated trading (algo / Claude-driven) | **Yes technically, on a non-Fidelity broker** | Legal for your own account. Alpaca or Schwab, not Fidelity. |
| 9 | Copy Pelosi / a trader on X | **Buildable as a feed, weak as a strategy** | 45-day disclosure lag. The two ETFs that do exactly this don't meaningfully beat the market. |

**One structural conclusion that shapes everything else:** Fidelity can be *read* but not *traded* programmatically. So the app is naturally two-sided — **Fidelity is your source of truth for real money, a second broker (Alpaca) is your execution + experimentation sandbox.** Design for that split from day one rather than discovering it in month three.

---

## 1. Live market data — "how do we do it, what do the others do?"

### What Yahoo and TradingView actually do
Neither one produces data. They license it and resell access to it.

Yahoo Finance's own disclosure page lists a stack of vendors: **Commodity Systems Inc.** for US equity and index history, **Morningstar** for financial statements and valuation ratios, **LSEG (Refinitiv)** for economic events and insider transactions, **S&P Global Market Intelligence** for estimates and analyst data, plus ICE for quotes. Consumer-facing quotes are **delayed 15–20 minutes** for most exchanges unless you're on a real-time entitlement.

TradingView is the same model at larger scale — direct exchange feeds plus vendor feeds, with real-time entitlements sold per-exchange as add-ons on top of the subscription.

The lesson: **the hard part of market data is licensing, not engineering.**

### The licensing rule that will govern your architecture
Exchanges charge on *who sees the data*:
- **Display use** — billed per entitled user.
- **Non-display use** — billed per device/application (this is what an algo consuming quotes is).
- **Redistribution** — a separate, much more expensive license triggered the moment you show exchange data to *anyone other than the licensee*.

Self-service API plans (Polygon, Alpaca, Finnhub, etc.) grant you *internal use*. They do **not** grant redistribution. So:

> **A single-user app for you personally is cheap and clean. The moment one other person logs in, your data cost structure changes category.** Budget for that fork now, even if you never take it.

### Vendor options, priced (Aug 2026)

| Provider | Cost | Real-time? | Good for |
|---|---|---|---|
| **Alpaca Basic** | **Free** | IEX only (~2% of consolidated volume) real-time via websocket; SIP delayed 15 min | Paper trading, research, bars. **Not** trustworthy for a live quote display. |
| **Alpaca Algo Trader Plus** | **$99/mo** | Full SIP (CTA + UTP) + OPRA options | The natural upgrade if you're already executing on Alpaca |
| **Tiingo** | **~$10/mo** | EOD + fundamentals | Long-horizon research, cheapest honest historical |
| **Financial Modeling Prep** | **~$19/mo** | Real-time REST + websocket | Best value if it holds up under load |
| **Polygon.io** | $29 / $79 delayed; **$199/mo** for real-time | Full real-time equities | The default "serious retail" flat-rate choice |
| **Finnhub** | Free tier: 60 calls/min, 50 websocket symbols | US real-time via IEX | Good free supplement; paid tier jumps to enterprise pricing |
| **Databento** | ~$100–500/mo metered | Tick + L2 | Overkill unless you go microstructure |

### On `yfinance` — read this before you build on it
It is the obvious first move and it is a trap for anything you intend to keep:
- It scrapes **unofficial, undocumented endpoints**. Yahoo changes URLs, adds auth, and alters response shapes without notice.
- It gets **rate-limited and blacklisted** aggressively; this is the single most common failure mode in the wild.
- Yahoo's ToS **explicitly prohibits automated access** without written permission. (Enforcement risk for a private personal tool is low — *hiQ v. LinkedIn* established that scraping public data isn't automatically a CFAA violation — but it rises sharply for anything customer-facing.)

**Recommendation:** use `yfinance` for throwaway prototyping only, behind an interface you can swap. Ship on a paid provider.

### Recommended data architecture
Don't pick one vendor. Build a thin `MarketDataProvider` interface with three concrete backends and route by need:
1. **Bars/history** → Tiingo or FMP (cheap, reliable, cacheable forever).
2. **Live quotes** → Alpaca (free IEX while you're prototyping, $99 SIP when it matters).
3. **Fundamentals/corporate actions** → FMP or Alpaca corporate actions.

Cache aggressively in local Postgres/TimescaleDB or DuckDB. Historical bars are immutable — you should pay for each bar exactly once, ever. This alone is the difference between a $20/mo app and a $200/mo app.

---

## 2. Pulling Fidelity account values and positions

### The hard fact
**Fidelity does not offer a public API to retail developers.** Its official API program (WorkplaceXchange) is for 401(k)/benefits plan administration, not individual brokerage accounts.

### The three real paths

**A. SnapTrade — recommended.**
- Purpose-built for brokerage aggregation. **OAuth** connection (your Fidelity credentials never touch your app or SnapTrade).
- Fidelity integration is **read-only: positions and balances. It explicitly does not support placing trades.**
- Near-real-time refresh (vs. Plaid's once-daily).
- Also covers Schwab, Robinhood, Vanguard, Webull, IBKR — so the same integration scales if you add accounts.
- Pricing: free production tier including 1 connected user, then roughly **$1–2/user/month**. For a personal app that's effectively free. Confirm your actual number with their team.

**B. Plaid Investments.**
- Read-only, **updates once daily**, broader banking coverage.
- Right choice only if you also want bank/cash accounts in the same net-worth picture.

**C. Unofficial browser automation (`fidelity-api` on PyPI/GitHub).**
- Playwright-driven headless browser. Can read positions *and place orders*.
- **Do not build on this.** It breaks on every Fidelity UI change, requires storing your actual credentials, and is squarely against Fidelity's terms. The failure mode is "your automated trader silently stops working, or worse, misclicks."

### Consequence for the design
Since Fidelity is read-only, the app should have a clean split:

```
Fidelity  ──SnapTrade (read)──►  "Real Portfolio"    (observe, analyze, benchmark)
Alpaca    ──REST (read+write)─►  "Live Sandbox"      (algo execution, real or paper)
Internal  ──your own ledger───►  "Paper Portfolio"   (strategy testing, backtests)
```

Three portfolio types, **one shared position/performance engine**. Build the engine once against an abstract `Portfolio` and all three light up together. This is the single most important architectural decision in the whole project.

---

## 3. Returns over time + benchmark comparison (the item everyone gets wrong)

This looks like a charting task. It isn't — it's an accounting task, and it's where Fidelity's and Yahoo's own tools are genuinely weak.

### Use time-weighted return (TWR), not simple % change
- **TWR** breaks the period at every cash flow and geometrically links the sub-period returns, so deposits and withdrawals don't distort the number. It measures *how the strategy performed*.
- **MWR/IRR** answers "how did my money do," which is a different and also useful question, but it is **not comparable to an index**.
- GIPS — the professional performance standard — **requires TWR** precisely because it's what makes comparison to a benchmark valid.
- **Modified Dietz** is the practical middle ground: it approximates TWR without needing a valuation at every single cash flow. Start here; it's what most trackers actually run.

> If you deposit $10k in March and the app reports raw account growth as "return," your S&P overlay is meaningless. Getting this right is a real differentiator — most consumer tools quietly get it wrong.

### Making the S&P overlay honest
- Index both series to 100 at the period start; plot the growth of $1.
- Compare **total return** to **total return** — use SPY/VOO or the S&P 500 Total Return index, not the price index, or you silently lose ~1.3%/yr of dividends and flatter yourself.
- Offer a **"same-cash-flows" benchmark**: replay your exact deposits and withdrawals into SPY. This answers the question you actually care about — *would I have done better indexing?* — and almost no consumer tool offers it. **This is a headline feature.**
- Standard metric row: CAGR, max drawdown, volatility, Sharpe, Sortino, beta vs. benchmark, alpha, up/down capture, correlation.

---

## 4. Custom charting like TradingView

### The licensing fork
| | **Lightweight Charts** | **Advanced Charts (Charting Library)** |
|---|---|---|
| License | **Apache 2.0, free, open source** | Free license for *approved public projects* with mandatory TradingView branding |
| Personal/hobby use | Allowed | **Explicitly not permitted** |
| Commercial | Allowed | Separate agreement, reportedly **$1,500–3,000+/mo** |
| Built-in indicators | **None** | Full TA suite, drawing tools, studies |
| Size | ~45 KB | Heavy |
| Data model | You push data in | Library requests data from your datafeed adapter |

**The catch that matters to you:** Advanced Charts' free tier is for *public* projects — a personal tool doesn't qualify. So the realistic choice is:

**Recommended: Lightweight Charts v5 + your own indicator layer.** Compute indicators server-side in Python (`pandas-ta` / `TA-Lib`) and push the resulting series to the chart as additional line/histogram series. This is more work than TradingView's built-ins, but it has a decisive advantage: **the same indicator code that draws your chart is the code your backtester and your live algo run.** With TradingView you'd have Pine Script on the chart and Python in the algo, and they'd drift out of agreement — which is exactly how people ship strategies that don't behave like their charts.

Alternatives worth a look if you want more out of the box: **Highcharts Stock** (commercial, excellent stock UX), **Apache ECharts** (free, more general-purpose), **KLineCharts** (free, TradingView-like, includes indicators).

### Where TradingView's *free* plan is beatable
As of 2026 the free Basic plan gives: **2 indicators per chart, 1 chart per tab, 1 saved layout, 3 active price alerts, no technical/indicator alerts, no webhooks, alerts expire after a month, and ads.** For a self-hosted personal app, all of those limits are simply *zero* — unlimited indicators, unlimited layouts, unlimited alerts, webhooks to anything. **You beat TradingView free on day one just by not having a paywall**, and TradingView's paid tiers are where their real product lives.

---

## 5. X (Twitter) posts from specific follows

### Current state of the API (this changed recently — don't trust older guides)
- **February 2026: X replaced tiered pricing with pay-per-use as the default.** New developers get **no free tier** and cannot sign up for Basic or Pro.
- Legacy **Basic ($200/mo)** and **Pro ($5,000/mo)** exist only for existing subscribers, and **as of June 1, 2026 X began auto-migrating remaining Basic subscribers to pay-per-use.**
- Pay-per-use rates: **$0.005 per post read** (capped at 2M reads/month), $0.015 per post created, $0.20 if the post contains a link.

**This is good news for you.** A personal app polling ~40 accounts and reading, say, 20k posts/month costs **~$100/mo**; polling 20 accounts at ~5k posts/month is **~$25/mo**; a tight, filtered follow-list can land under $10. It scales with what you actually read, which suits a single-user tool far better than the old $200 floor.

### Design notes
- Don't poll timelines broadly and filter after — you pay per read. Use **filtered stream rules** scoped to your author list, and let X do the filtering server-side.
- Store every post you pay for. Never pay for the same post twice.
- **Cashtag extraction** (`$NVDA`) and mapping to your watchlist is the whole value. Join posts to tickers, then surface them *on the chart* as timeline markers and *in the watchlist row* as a recent-chatter indicator. That contextual join — post pinned to the moment on the price chart — is something none of Fidelity, Yahoo, or TradingView free does well.
- Sentiment scoring via an LLM pass is cheap and adds a sortable column. Treat it as color, not signal.
- **Realistic expectation:** this is a *context and awareness* feature, not an edge. Financial X is overwhelmingly noise, and the accounts worth reading are worth reading slowly.

---

## 6. Watchlists and organization

The least technically interesting item and possibly the highest-leverage one, because the incumbents are all mediocre here.

What to build that they don't have:
- **Tags, not folders.** A ticker belongs in "semis," "AI capex," and "owned" simultaneously. Fidelity and Yahoo both force a single-list mental model.
- **Computed/smart lists** — "everything I hold," "everything mentioned on X this week," "everything within 5% of a 52-week high," "everything in a sector I'm underweight vs. SPY." These come free once the data layer exists.
- **Custom columns** — let any indicator, any metric, any X-sentiment score become a sortable column. TradingView paid does this; free doesn't.
- **Position awareness everywhere** — every watchlist row should know whether you own it, at what basis, and your unrealized P/L, because you already have the Fidelity feed. This is the fusion the incumbents structurally can't do: Fidelity knows your positions but charts badly; TradingView charts brilliantly but doesn't know your positions.

---

## 7. Theoretical/paper trading account

The best-supported item in your list.

**Use Alpaca's paper trading API.** It's free, mirrors the live API exactly (same endpoints, same order types, same responses), and gives you real fills against real market data. Building on it means your paper strategy and your live strategy are *literally the same code with a different base URL* — no re-implementation gap.

Also run an **internal paper ledger** for strategies you want to test against your own assumptions or over history Alpaca won't simulate. Same `Portfolio` abstraction as §2.

### Backtesting engine, if you want to test strategies over history
| Framework | Type | Verdict |
|---|---|---|
| **VectorBT** | Vectorized | Fastest for parameter sweeps and signal research. Lies about microstructure. Open-source tier is good; PRO ~$25/mo. |
| **backtesting.py** | Event-driven | Simplest, cleanest docs. Good starting point. |
| **NautilusTrader** | Event-driven | **Strongest open-source foundation if you want backtest→live to survive the transition.** Where to land if this gets serious. |
| **Backtrader** | Event-driven | In long-term maintenance since ~2023, no significant releases. Expect friction on modern Python. Avoid for new work. |
| **QuantConnect** | Hosted | Most complete end-to-end, at the cost of ecosystem lock-in. |

**Suggested path:** vectorbt for research iteration → NautilusTrader if/when you go live. The known trap is the **backtest-to-live gap**: a strategy showing 50% annualized in backtest commonly delivers 10–15% live once spreads, slippage, and commissions are real. Model costs pessimistically from the start.

---

## 8. Automated trading

### Legality (US, personal account)
- **Automated trading on your own account is legal.** Retail traders using automated software through a regulated broker aren't subject to registration. You're still bound by the conduct rules everyone is — no manipulation, no spoofing, no wash trading.
- **The line you must not cross casually:** the moment you provide trading signals *to other people as a regular business*, you're potentially in **investment adviser** or even **broker-dealer** territory. Regulators focus on systems that "automatically generate orders and order-related messages" and effectuate them. Idea-generation alone is treated more leniently, but "I'll let a friend use it" is where hobby projects acquire real legal exposure.
- **Pattern Day Trader rule:** under $25,000 equity, you're capped at 3 day trades per rolling 5 business days in a margin account. An intraday algo will hit this immediately. Cash account or ≥$25k, or design for swing timeframes.
- **Wash sales** apply to your real account and an algo that re-enters positions will generate them constantly. Track them or your tax reporting will be wrong.

### Which broker
Fidelity is out (no retail API). Ranked for your case:
1. **Alpaca** — fastest to a working prototype, clean REST docs, commission-free equities/ETFs, free paper API that mirrors live, 200 calls/min free (1,000 funded), unlimited websockets. **Start here.**
2. **Schwab Trader API** — free at developer.schwab.com; register as *Individual Developer*, app sits "Approved — Pending" for a few days before "Ready for use." Individual access lets you trade **your own** accounts only; letting anyone else connect requires a separate **commercial approval** review. Good if you'd rather consolidate at a full-service broker.
3. **Interactive Brokers** — best execution (SmartRouting), widest market access, 50 order msgs/sec. Heavier: gateway software, clunkier API. The endgame, not the start.
4. **Tradier** — low fees, solid order-lifecycle endpoints, 120 req/min standard / 600 premium.

### "Claude trading its own stocks"
Honest read of the 2026 research:
- Benchmarks like **StockBench** find LLM agents *can* trade profitably and that **most tested models beat buy-and-hold** in their windows, with notably **better drawdown control** (best agents held max drawdown to ~-11% to -14%).
- But: **sample sizes are small (often <50 stocks), evaluation windows are short, and out-of-sample statistical rigor is well below what financial economics demands.** These are promising demos, not evidence of durable alpha.
- **Reasoning-tuned models do not reliably beat instruction-tuned ones** at trading tasks — so "use the biggest reasoner" isn't the answer.

**How to actually build this responsibly:**
- Use the LLM as a **research and structuring layer**, not an order generator: summarize filings and earnings calls, extract catalysts, score X sentiment, flag when a thesis you wrote is contradicted by new information, propose *candidate* trades with written reasoning.
- Keep **deterministic code** in the execution path: position sizing, risk limits, stop losses, max daily loss, per-name concentration caps. An LLM should never be the last thing between an idea and a filled order.
- Log every decision with its full reasoning and its inputs. In six months the log is the most valuable artifact in the project — it's the only way to know whether the thing works.
- Run it in the paper account for **at least two quarters** before a dollar is real.

### Copying Pelosi or a trader on X
**Build the feed. Be skeptical of the strategy.**

*Data is easy:* the STOCK Act requires members of Congress to disclose transactions over $1,000 within **45 days**. **Quiver Quantitative** (~1,800 equities, back to Jan 2016, daily delivery, and available as a QuantConnect dataset), **Capitol Trades** (back to 2012, ingested within hours of publication), and **Disclosed Capitol** (queryable JSON by member/ticker/committee/date) all serve this. The raw filings are free from House/Senate disclosure portals if you want to parse them yourself.

*The strategy is the problem:*
- **45-day lag** is fatal to anything resembling a fast signal. You're copying a trade a month and a half after the fact.
- The two ETFs doing exactly this — **NANC** (Democratic members) and **KRUZ** (Republican) — provide a clean natural experiment. NANC returned ~35% in 2024 and KRUZ ~18%, but academic analysis concludes **neither significantly outperforms market returns**, and the gap between them is explained by **sector exposure (NANC's tech concentration), not informational advantage.** In the 2026 drawdown NANC was down ~4% against SPY's ~2%.
- **Regulatory risk:** if Congress bans member stock trading, the entire thesis evaporates overnight.
- Copying an X trader is strictly worse — no disclosure requirement, no verification, survivorship bias in who you've heard of, and no way to know their position size, basis, or whether they exited.

**Recommendation:** build congressional and X-follow trades as a **watchlist-population and context feed** — "this name was bought by N members in the last 90 days," rendered as markers on the chart. Then **let the paper account settle the question empirically** rather than arguing about it. That's exactly what the sandbox is for, and it turns a debatable feature into a testable one.

---

## 9. Where the incumbents are actually weak — your wedge

| Competitor | Strong at | Structurally weak at |
|---|---|---|
| **Fidelity** | Custody, execution, real cost basis, tax lots | Charting is basic; no cross-broker view; no custom indicators; no strategy testing; no benchmark math worth the name |
| **Yahoo Finance** | Breadth, news, free | Ad-heavy; portfolios are shallow; return math doesn't handle cash flows properly; no execution; no algo layer |
| **TradingView free** | Best-in-class charting UX, huge indicator community | 2 indicators/chart, 1 layout, 3 price alerts, no technical alerts, no webhooks, ads — and **it has no idea what you own** |

**The gap none of them fills:** *your actual positions*, joined to *serious charting*, joined to *honest benchmark-relative performance*, joined to *a sandbox where a strategy can be tested before it touches real money* — in one place, with no paywall on your own data.

Concretely, the five things to build that no one else offers you:
1. **Same-cash-flows benchmark** — replay your real deposits/withdrawals into SPY and show both curves.
2. **Every chart knows your position** — entry markers, cost basis line, unrealized P/L in the header.
3. **One indicator implementation** shared by chart, backtest, and live algo — so what you see is what you trade.
4. **X and congressional activity as timeline markers on the price chart**, not a separate feed you never open.
5. **Paper → live promotion path** — the same strategy object runs in backtest, paper, and live with a flag.

---

## 10. Recommended stack and build order

### Stack
- **Backend:** Python (FastAPI). Non-negotiable — the entire quant ecosystem (pandas, vectorbt, NautilusTrader, TA-Lib, Alpaca SDK) lives there.
- **Storage:** Postgres + TimescaleDB for time series, or DuckDB + Parquet if you'd rather stay file-based. Cache every bar you ever pay for.
- **Frontend:** React + TypeScript, **TradingView Lightweight Charts v5** for price, your dataviz library of choice for performance/analytics charts.
- **Scheduling:** a simple job runner for market-hours polling, EOD snapshots, and X stream ingestion.
- **Deployment:** local-first (a Mac mini or your laptop) is genuinely correct here — single user, no redistribution licensing, no hosting cost, no data leaving your machine.

### Phases

**Phase 1 — Read-only truth (2–4 weeks).**
SnapTrade → Fidelity positions and balances. Daily snapshot into Postgres. Correct TWR/Modified Dietz engine. Performance chart with S&P total-return overlay and same-cash-flows benchmark. *This alone already beats what Fidelity shows you.*

**Phase 2 — Charting and watchlists (3–5 weeks).**
Lightweight Charts, server-computed indicators, tag-based watchlists with custom columns, position awareness on every row and chart.

**Phase 3 — Sandbox (3–4 weeks).**
Alpaca paper account + internal paper ledger against the same `Portfolio` abstraction. Strategy interface. vectorbt backtests over cached history.

**Phase 4 — Signals (2–3 weeks).**
X pay-per-use ingestion on a filtered author list, cashtag extraction, congressional disclosure feed, all rendered as chart markers and watchlist columns.

**Phase 5 — Automation (open-ended).**
Deterministic strategies first, on paper. LLM as research/structuring layer with hard-coded risk limits. Two quarters of paper before real money.

### Cost model

| Item | Prototype | Serious |
|---|---|---|
| Brokerage aggregation (SnapTrade) | $0 (free tier, 1 user) | ~$2/mo |
| Market data | $0 (Alpaca IEX + cached EOD) | $10–19/mo (Tiingo/FMP), $99–199/mo if you need real-time SIP |
| X API | $0 (skip initially) | ~$10–100/mo depending on read volume |
| Charting | $0 (Lightweight Charts) | $0 |
| Backtesting | $0 (vectorbt OSS) | $0–25/mo |
| Broker (Alpaca) | $0 | $0 commissions |
| Hosting | $0 (local) | $0–20/mo |
| **Total** | **≈ $0/mo** | **≈ $25–150/mo** |

The entire Phase 1–3 product is buildable for roughly nothing. That's the real headline.

---

## 11. Open questions for you

1. **Are you the only user, ever?** This is the highest-stakes question in the document. Single-user keeps market data licensing trivial and hosting free. Multi-user changes data licensing category, triggers Schwab/SnapTrade commercial review, and puts signal-sharing near investment-adviser territory.
2. **Would you open an Alpaca account?** Fidelity read-only is a hard wall. Without a second broker, "automated trading" reduces to "automated suggestions you enter by hand" — which is a legitimate product, just a different one.
3. **What timeframe do you actually trade?** Intraday means real-time SIP data ($99–199/mo) and PDT constraints. Swing/position means free delayed data and near-zero cost. This single answer swings the budget by 10x.
4. **Desktop app, local web app, or hosted?** Local-first is my recommendation and it's meaningfully cheaper and simpler, but it means no phone access unless you add a tunnel or a small hosted mirror.
5. **How much history do you want at import?** Fidelity's aggregated feed gives current positions; reconstructing multi-year performance may need a manual CSV import of historical transactions to seed the ledger.

---

## Sources
- SnapTrade Fidelity integration — https://snaptrade.com/brokerage-integrations/fidelity-api
- SnapTrade vs Plaid Investments — https://dev.to/pickuma/snaptrade-vs-plaid-investments-brokerage-aggregation-apis-for-fintech-builders-27mh
- Does Fidelity Have an API? (TradersPost) — https://blog.traderspost.io/article/does-fidelity-have-an-api
- fidelity-api (unofficial) — https://github.com/kennyboy106/fidelity-api
- Yahoo Finance exchanges and data providers — https://help.yahoo.com/kb/SLN2310.html
- Alpaca market data plans — https://alpaca.markets/data
- Alpaca market data docs — https://docs.alpaca.markets/us/docs/about-market-data-api
- Best real-time stock data APIs 2026 — https://medium.com/coinmonks/the-7-best-real-time-stock-data-apis-for-investors-and-developers-in-2026-in-depth-analysis-61614dc9bf6c
- Databento vs Polygon 2026 — https://aifinhub.io/articles/market-data-apis-compared-2026/
- NYSE proprietary market data pricing — https://www.nyse.com/publicdocs/nyse/data/NYSE_Market_Data_Pricing.pdf
- CME data licensing / non-display FAQ — https://www.cmegroup.com/market-data/distributor/files/cme-group-data-licensing-policy-guidelines-and-non-display-licensing-faq.pdf
- OPRA fees & licensing explained — https://www.marketdata.app/education/options/opra-fees/
- Why yfinance keeps getting blocked — https://medium.com/@trading.dude/why-yfinance-keeps-getting-blocked-and-what-to-use-instead-92d84bb2cc01
- TradingView free charting libraries — https://www.tradingview.com/free-charting-libraries/
- TradingView Advanced Charts product comparison — https://www.tradingview.com/charting-library-docs/latest/getting_started/product-comparison/
- TradingView free vs paid plans 2026 — https://quantroutine.com/tools/tradingview-free-vs-pro/
- X (Twitter) API pricing 2026 — https://postproxy.dev/blog/x-api-pricing-2026/
- X API cost breakdown 2026 — https://twitterapi.io/blog/x-api-cost-breakdown-2026
- Quiver Quantitative US Congress Trading dataset — https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/quiver-quantitative/us-congress-trading
- Capitol Trades APIs for congressional stock data — https://www.lambdafin.com/articles/capitol-trades-api
- Disclosed Capitol developer API — https://www.disclosedcapitol.com/developers
- NANC vs KRUZ (ETF.com) — https://www.etf.com/sections/etf-basics/nanc-vs-kruz-battle-congress-stock-trackers
- US Congress members' trading activities: NANC and KRUZ (ScienceDirect) — https://www.sciencedirect.com/science/article/abs/pii/S0165176525001004
- StockBench: Can LLM Agents Trade Stocks Profitably? — https://arxiv.org/html/2510.02209v2
- TradingAgents multi-agent LLM framework — https://github.com/tauricresearch/tradingagents
- Best brokers for algo trading US 2026 — https://brokerchooser.com/best-brokers/best-brokers-for-algo-trading-in-the-united-states
- Schwab Trader API commercial approval — https://mylinedchart.com/resources/articles/schwab-trader-api-commercial-approval-what-the-review-evaluates
- FINRA algorithmic trading — https://www.finra.org/rules-guidance/key-topics/algorithmic-trading
- Python backtesting landscape 2026 — https://quanttradingtools.com/python-backtesting-frameworks/
- Best Python backtest engines 2026 — https://bullalert.ai/blog/best-python-backtest-engines-2026/
- GIPS guidance on calculation methodology — https://www.gipsstandards.org/wp-content/uploads/2021/03/calculation_methodology_gs_2011.pdf
- Calculating and understanding portfolio returns (PWL) — https://pwlcapital.com/calculating-understanding-portfolio-returns/
- Best investment tracking apps 2026 — https://robberger.com/investment-tracking-apps/
