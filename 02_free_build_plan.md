> **Stack section superseded.** This document's original stack table named
> FastAPI, Postgres and a React PWA. None of that was built. The app is
> Python 3.13 standard library only, SQLite, and one hand-written
> `app/dashboard.html` served by `http.server`. The reasoning about what to
> build and why still stands; the technology choices in it do not.

# Investment App — The $0 Build Plan
_Revision 3 — 2026-08-28. Constraints: free, single user, no new brokerage account, swing-trading timeframe (months–year), iPhone access required, always-on host = an old MacBook Pro._

> **Revision 3 corrects two things from revision 2.** I filed automated bank sync as blocked when a free path exists (OFX Direct Connect, §6), and I under-read your Robinhood account — because it's crypto, it's the one account you own that has a real, official, supported trading API (§4).

---

## The short version

**Free is not a compromise here — it's close to the right answer anyway.** Almost everything I priced in the first pass was priced for *real-time data* and *the X API*. You swing trade, so you don't need real-time data. And the X problem has a free workaround you basically already guessed. What's left costs nothing.

Three things genuinely change under the free constraint, and only one of them hurts:

| | Verdict |
|---|---|
| **Chart analysis better than TradingView** | **Unaffected.** Free was always the answer here — Lightweight Charts is Apache-2.0 and TradingView's *free* tier is the weak one. |
| **Account charts better than Fidelity** | **Unaffected.** This is math on data you already own. Costs nothing, ever. |
| **Real-time quotes** | **Gone, and you don't need them.** Free tiers give end-of-day plus 15-min-delayed. For month-to-year holds that's irrelevant. For your occasional day trade, glance at Robinhood for the live price and use this app for the analysis. |
| **Automated trading with real money** | **Available on your Robinhood crypto account** — official supported API. Equities stay human-in-the-loop. See §4. |
| **X posts** | **Free-ish, via a side door.** See §3 — your notification instinct was right, just on the wrong device. |
| **Budgeting** | **Free, and likely fully automatic** — OFX Direct Connect pulls transactions with no aggregator. I got this wrong last time. See §6. |

---

## 1. The complete free stack

| Layer | Choice | Cost | Why |
|---|---|---|---|
| Position/balance sync | **CSV / OFX export, imported locally** | **$0** | SnapTrade was planned and never built. Fidelity CSVs and a Frost OFX file are imported by `app/importers/`. |
| History seed | **Fidelity + Robinhood CSV export** | **$0** | One-time import to reconstruct 2–3 years. See §7. |
| Price history + bars | **Alpaca paper account** | **$0** | 7+ years of history, real-time IEX websocket, clean terms of service. Email signup only. |
| Backup price source | **Stooq** (no key) / **Tiingo free** | **$0** | Redundancy for when one source has a bad day. |
| Fundamentals | **SEC EDGAR** (`data.sec.gov`) | **$0** | Official, free, no key, no registration. 10 req/sec. Every XBRL fact for any CIK. |
| Macro data | **FRED** | **$0** | Free API key, rates/CPI/unemployment for context overlays. |
| Charting | **Lightweight Charts v5** | **$0** | Apache 2.0. |
| Indicators | **pandas-ta** (Python) | **$0** | Your own layer — shared by chart, scanner and backtest. |
| Backtesting | **`app/backtest.py`**, hand-rolled | **$0** | Walk-forward with a survivorship control universe. |
| Paper trading | **Alpaca paper API** | **$0** | Mirrors live API exactly. |
| Social/sentiment | **macOS notification harvest + StockTwits + Bluesky** | **$0** | See §3. |
| Congressional trades | **House/Senate disclosure portals** (parse directly) | **$0** | Quiver/Capitol Trades charge; the raw filings don't. |
| Bank/card transactions | **OFX Direct Connect** via `ofxtools`, else statement drop | **$0** | See §6. Not blocked after all. |
| Database | **SQLite** | **$0** | Standard library. One file, `ledger.db`. |
| Backend | **Python 3.13 standard library** (`http.server`) | **$0** | No dependencies at all. |
| Frontend | **One hand-written `app/dashboard.html`** | **$0** | Vanilla JS. TradingView Lightweight Charts vendored locally. |
| Hosting | **Your Mac** | **$0** | |
| iPhone access | **Tailscale** free Personal | **$0** | 6 users, unlimited user devices, free forever. |

**Total recurring cost: $0.** No trial expiries, no card on file, no service in the chain that can start charging you.

---

## 2. What "free" actually costs you (honest list)

Not nothing. Here's the real bill, paid in constraints rather than dollars:

- **No real-time consolidated quotes.** Free real-time is IEX-only, ~2% of consolidated volume — fine for a sanity check, wrong for a live quote display. Label delayed data as delayed *in the UI* so you never misread it.
- **A machine has to stay on** for scheduled jobs, notification harvesting and iPhone access. Your old MacBook Pro on a charger solves this — see §5b, including one hardware caution worth reading before you commit it to 24/7 duty.
- **No native iOS app.** A real App Store app requires the $99/yr Apple Developer Program. Free sideloading re-signs every 7 days, which is unusable. PWA it is (§5).
- **Budget imports stay manual.** Free bank-sync is effectively dead (§6).
- **You maintain it.** Free tiers change terms, scrapers break, endpoints move. Build every external dependency behind an interface so a swap is an afternoon, not a rewrite.

---

## 2b. What's actually blocked — by kind, not by verdict

You asked whether some of these could be built from scratch. Fair challenge: "blocked" was doing too much work in the last revision. Here's the same list sorted by *what kind* of obstacle it is, because only one category is genuinely immovable.

| Thing | Kind of blocker | Can it be built from scratch? |
|---|---|---|
| Reading other apps' notifications on **iPhone** | **Hard — OS level** | **No.** The iOS sandbox has no API for it and never has. Not a money or effort problem; the capability does not exist outside a jailbreak. This is the only true impossibility on the list. |
| **Real-time consolidated (SIP) quotes** | **Licensing** | **No, not by coding.** You'd have to become a licensed data recipient. But free IEX *is* a real exchange feed, and delayed SIP is free — so you can get 95% of the way for a swing trader. |
| **Fidelity programmatic orders** | **Terms-of-service risk** | **Yes — and working implementations already exist.** `fidelity-api` drives a headless browser and genuinely places orders. It is buildable, and we could build a better one. |
| **Robinhood equity orders** | **Terms-of-service risk** | **Yes** — same story, via `robin_stocks`. |
| **Robinhood crypto orders** | **Not blocked at all** | **Official, documented, supported API.** See §4. |
| **Automated bank/card transaction import** | **Was wrong — not blocked** | **Yes, free.** OFX Direct Connect. See §6. |
| **Native iOS app** | **Cost — $99/yr** | Buildable any time you decide to pay. The free 7-day re-signing path is unusable. |
| Charting, indicators, scanners, backtesting, performance math, method library | **Effort only** | All of it. None of this was ever gated by anything but time. |

### On the two terms-of-service items — your call, not mine

I want to be straight rather than protective here. Browser-automating Fidelity is **not technically infeasible**. It works. What you'd be accepting:

- Your real Fidelity credentials stored on the always-on Mac, and a session that can place orders.
- Silent breakage on any Fidelity UI change — the dangerous failure isn't "it stops," it's "it misclicks."
- A terms violation that, if noticed, is grounds for Fidelity restricting the account holding most of your money.

**My recommendation, which is a risk judgment and not a feasibility one:** don't put it in the live order path. If you want it, the good use is **order staging** — the app pre-fills a Fidelity order ticket and you press the last button. You get most of the convenience and none of the "my bot sold something at 3am" scenario. And with Robinhood crypto now in play (§4), you already have a legitimate venue for the real-money automation experiment.

---

## 3. The X problem, and your notification idea

**Your instinct was right. It just doesn't work on iPhone — it works on your Mac.**

### Why not on iPhone
iOS has no API, and no Shortcuts hook, that lets an app read *other apps'* notifications. The UserNotifications framework only manages an app's own notifications. This is a deliberate, longstanding platform restriction and there's no supported workaround. Dead end.

### Why it works on macOS
macOS writes **every delivered notification** to a SQLite database. Since Sequoia it lives at:

```
~/Library/Group Containers/group.com.apple.usernoted/db2/db
```

The `record` table holds the delivering app's bundle ID, title, subtitle, body text, delivery timestamp, and whether you interacted with it. So:

1. Follow the accounts you care about on X and turn on the **bell** for each one.
2. Let X's web app (Safari or Chrome) send desktop notifications on your Mac.
3. Poll that SQLite database on a schedule, filter to X's bundle ID, extract cashtags, store.

Verify it works on your machine in one command — you'll likely need to grant **Full Disk Access** to Terminal first (System Settings → Privacy & Security → Full Disk Access):

```bash
sqlite3 ~/Library/Group\ Containers/group.com.apple.usernoted/db2/db \
  "SELECT DISTINCT app_id FROM record;"
```

**Caveats, so this doesn't surprise you later:**
- You only capture what X actually *pushes*. Bell notifications per-account, not full timelines.
- Notification bodies are stored as binary plist blobs — decode with `plutil -p`, not a plain text read.
- Text is truncated to notification length. You get the hook, not the thread.
- Requires the Mac awake and logged in.
- Apple moved this DB in Sequoia specifically to harden privacy around it. **Treat it as a path that may close.** Keep it behind an interface.

### The other free sources, ranked
1. **StockTwits** — purpose-built for exactly this, cashtag-native, free tier. Should be your *primary* social feed, not X. Better signal-to-noise for tickers than X by a wide margin.
2. **Bluesky** — genuinely free API, no paid tier games. A meaningful slice of finance commentary has migrated there. Worth checking whether the specific people you follow are on it.
3. **RSS + newsletters** — many of the analysts worth reading publish Substack/blogs with RSS. Free, structured, full text, no rate limits, and *higher quality than their tweets*. For a swing trader on a months-to-year horizon this is strictly better input than X.
4. **X email digests** — X can email you notification digests. Worth a 10-minute test to see whether per-account bell notifications appear in them; if they do, that's a clean free parse path. Uncertain, cheap to check.
5. **Paid X API** — $0.005/read, ~$25/mo for a modest follow list. Not free, but the smallest paid upgrade on the whole board if the free routes disappoint.

**Blunt take:** for months-to-year holds, X is the *least* valuable input on this list. Build StockTwits + RSS first, add the macOS notification harvest as a bonus, and let X be the thing you add only if you miss it.

---

## 4. Automated trading — you already own the account that allows it

I under-read your Robinhood account last revision. Because it's **crypto**, it's the one account you hold that has a **real, official, documented, supported trading API**.

| Account | Programmatic orders? |
|---|---|
| **Fidelity** | **No** — no retail API; SnapTrade's integration is read-only. |
| **Robinhood equities** | **No** — undocumented, unsupported endpoints. |
| **Robinhood crypto** | **Yes.** Official Robinhood Crypto Trading API. View market data, manage positions, place orders. |

### How to turn it on
Sign in to Robinhood **web classic** → crypto account settings → **Add key** → select which API actions to enable (you can grant read-only first, and add trading later). You get credentials you authenticate with directly. Docs live at `docs.robinhood.com/crypto/trading/`. No cost, no application, no new account.

**One documented weakness:** Robinhood does not publish its rate limits. Build in conservative throttling and retry-with-backoff from the start, and never assume an order request will land during a volatile moment.

### Why this materially improves the plan
The algorithm experiment no longer has to be purely hypothetical. You get a three-rung ladder, each rung free and each one earned:

```
1.  Backtest        app/backtest.py over cached history  no risk, fastest iteration
2.  Paper           Alpaca paper account              real fills, real data, no money
3.  Live, small     Robinhood crypto API              real money, real slippage,
                                                      real emotions — at a stake
                                                      you've already sized as small
```

That third rung is the one that actually teaches you something. Paper trading famously flatters strategies because nothing is at stake; a small live account with real fills and real slippage is where a strategy's actual behavior shows up. And you already have exactly that account, sized exactly right for it.

**Keep the scope honest:** crypto is a different animal from your swing-traded equities — 24/7 markets, different volatility regime, no earnings, no fundamentals. A strategy that works there tells you the *plumbing* works and that you can execute a rules-based system without overriding it. It does not validate an equity strategy. Treat it as the proving ground for the machinery, not for the edge.

### For equities, the design stays human-in-the-loop
```
Strategy ──► Alpaca paper ──► scored vs. SPY (did it work?)
         └─► "Trade ticket" card ──► you enter it in Fidelity by hand
```
An Alpaca paper-only account is **not a brokerage account** — email signup, no SSN, no ID, no funding, no minimum. It's a simulator with an API, so it doesn't violate your no-new-accounts constraint, and it also supplies 7+ years of historical bars for the app's charting.

Legally: trading your own accounts algorithmically is fine. The line you don't cross is giving signals to other people as a regular business, which is where adviser and broker-dealer registration questions start. Staying single-user keeps you well clear of it.

## 5. iPhone access — most reliable free option

**Recommendation: a PWA served from your Mac, reachable over Tailscale.**

- **Tailscale free Personal** — 6 users, *unlimited user devices*, free forever. Your iPhone and your Mac join one private network. No port forwarding, no dynamic DNS, no exposing anything to the public internet, no VPS. Works on cellular.
- **PWA on iOS 26** — every site added to the Home Screen now opens as a web app by default. Full-screen, own icon, own app switcher card. Indistinguishable from native for a data app like this.
- **Push notifications work** (iOS 16.4+, Home Screen web apps only). Good enough for price alerts; delivery is less reliable than native, and there's no Time-Sensitive or Live Activity support.

**Known limits, stated plainly:** no Background Sync or Background Fetch on iOS, so the PWA can't refresh in the background — it fetches when you open it. For a swing trader that's fine. Push delivery is best-effort, so don't build a strategy that depends on an alert arriving within seconds.

**Why not native:** $99/yr Developer Program, which breaks the free constraint. If you ever pay for one thing in this project, that's a reasonable candidate — but build the PWA first, because the PWA is also the desktop UI and you'd need it either way.

---

## 5b. Turning the old MacBook Pro into the server

Good answer to the always-on question — this workload (SQLite, one stdlib http.server process) is trivial for any Mac of the last decade. A few things worth setting up deliberately.

### Keep it awake and self-healing
```bash
sudo pmset -a sleep 0            # never system-sleep
sudo pmset -a disablesleep 1     # stay awake with the lid closed
sudo pmset -a displaysleep 10    # screen off is fine and saves wear
sudo pmset -a autorestart 1      # come back automatically after a power cut
sudo pmset -a womp 1             # wake on network access
```
Also enable **automatic login** (System Settings → Users & Groups) so an unattended reboot comes all the way back up without you, and turn **off** automatic macOS updates that reboot on their own schedule — you want to choose when this thing restarts.

### One hardware caution before you commit it
An older laptop held at 100% charge continuously is the classic recipe for a **swollen battery**, which is a genuine physical hazard, not just a degradation issue. Before you leave it plugged in permanently:

```bash
system_profiler SPPowerDataType | grep -A3 -E "Cycle Count|Condition|Maximum Capacity"
```

If cycle count is high or condition is anything other than Normal, either replace the battery or plan to run it lid-open somewhere ventilated where you'd notice a bulge. Enable **Optimized Battery Charging** so macOS doesn't hold it at full indefinitely. This is a five-minute check that's worth doing before the machine spends a year unattended on a shelf.

### Practical server hygiene
- **Tailscale** installs as a system service and survives reboots — that's what gives your iPhone access from anywhere with no port forwarding.
- **No database server and no Docker.** SQLite is a file; the app is one Python process with no dependencies. Docker's overhead on an older Intel machine buys nothing here.
- Exclude the data directories from **Spotlight indexing** so it isn't re-indexing Parquet files forever.
- Put the whole app under **launchd** rather than a terminal you left open, so it restarts itself.

### One thing I need from you
**Which model year, and which macOS version?** Two decisions depend on it: whether Docker is worth using at all, and — more importantly — the path to the notification database from §3, which Apple moved in Sequoia. On Sequoia and later it's `~/Library/Group Containers/group.com.apple.usernoted/db2/db`; before that it lived under the Darwin user directory instead. `sw_vers` will tell us.

---

## 6. The budgeting page — you were right, this isn't blocked

What I called blocked last revision was *third-party aggregator* sync (Plaid, GoCardless, SimpleFIN). What you actually described — hand over statements, have them categorized and automated — works fine and costs nothing. There are three tiers, and you should try them in this order.

### Your institutions, checked (2026-08-28)

Frost Bank, Chase, Fidelity, Amex, Capital One. Verdict: **OFX Direct Connect is mostly dead for this set.** Only Fidelity is a solid candidate.

| Institution | OFX Direct Connect | Notes |
|---|---|---|
| **Fidelity** | **Likely yes** | Server `https://ofx.fidelity.com/ftgw/OFX/clients/download`, FID `7776`, ORG `fidelity.com`. Documented and in active use. Known to break periodically (see `ofxtools` issue #140), so treat as best-effort, not load-bearing. |
| **Chase** | **No — discontinued** | Chase dropped Direct Connect/OFX on **6 October 2022**, including third-party bill pay. Web Connect (manual QFX download) only. |
| **Amex** | **Probably not** | Settings exist historically (server `online.americanexpress.com/myca/ofxdl/...`, FID `3101`, ORG `AMEX` case-sensitive) but users report ongoing breakage as Amex moved to a Quicken-only OAuth path. Worth one test; expect failure. |
| **Capital One** | **No** | Does not support Direct Connect for credit card accounts. Manual OFX/QFX download from their site only. |
| **Frost Bank** | **Unknown** | Not in the GnuCash settings list, and reports conflict. **Worth one phone call** — ask whether they support *Quicken Direct Connect* specifically (not Web Connect, not Express Web Connect). |

**So the realistic plan is tier 2 as the primary path, not tier 1.** Test Fidelity's OFX endpoint and call Frost; everything else gets downloaded. That's a revision downward from the last version of this document, and worth being straight about.

The upside: it makes the download step the thing worth automating, and there's a good way to do that — see "Automating the download" below.

### Tier 1 — OFX Direct Connect, where it works
`ofxtools` is a free Python library that speaks the protocol. Credentials live in the **macOS keychain on your own machine** — never in a chat, never in a config file, never with a third party. Configure the institution's endpoint, org and FID, and pull on a schedule. This is exactly what Quicken does; nothing exotic.

Use it for Fidelity, and for Frost if the call comes back positive.

### Tier 2 — statement drop (what you described)
A watched folder. You export CSV/OFX/QFX (or even PDF) from each account once a month and drop it in; the pipeline parses, deduplicates against what's already in the ledger, categorizes, and files it. **The only manual step is the download — about two minutes per account per month.** PDF statements parse fine too, so this works even for issuers with poor export.

### Tier 3 — transaction alert emails (near-real-time supplement)
Most cards will email you on every transaction if you enable alerts. Those emails are highly structured and trivially parseable, and your Gmail is already connected here. This won't replace tier 1 or 2 as the system of record — alerts lack final posted amounts and merchant cleanup — but it gives you a same-day view between imports.

### Automating the download itself

Since most of your institutions require a manual export, the download is the chore worth removing — and it can be, without anyone holding your credentials.

**Claude in Chrome** drives *your* Chrome, in *your* already-logged-in session. You sign in and clear 2FA yourself; the automation then walks the date ranges and clicks the export buttons. Credentials never leave your machine and never enter a transcript. For Fidelity's 90-day-capped exports in particular — twelve separate downloads to cover three years — this turns a genuinely tedious job into a supervised one.

**What does not work, and why:** handing over account credentials directly. Beyond the obvious, there are three concrete reasons it wouldn't even function — every institution here enforces 2FA, so a password alone stalls at the second factor; authenticated pages can't be fetched server-side; and the credentials would then live in conversation history. The browser-driving approach gets the same result with none of that.

### The categorization, which is the part you actually asked about
Fully automatic, and it should get *more* automatic over time rather than depending on me:

1. **Rules engine first.** Merchant-string patterns to categories. After a few weeks of training this handles the large majority of transactions at zero cost and zero latency.
2. **LLM pass on the leftovers only** — the genuinely ambiguous ones. Each decision it makes is written back as a **new rule**, so the LLM's share of the work shrinks every month toward near-zero.
3. **Everything stays local.** The ledger lives on your Mac. Only merchant strings and amounts need to reach a model, with account numbers stripped first — and once the rules mature, most months won't need a model call at all.

### Build it on the same ledger as the portfolio
One double-entry ledger, two views. That's what unlocks the thing no single app gives you: **net worth, cash flow and investment performance in one picture** — savings rate feeding contributions, contributions feeding positions, positions feeding returns. Empower does a shallow version; Fidelity, Yahoo and TradingView don't attempt it.

Worth studying, both free and open source: **Actual Budget** for the UX model, **Firefly III** for the double-entry data model and rules engine. Both have importers whose patterns are worth borrowing rather than reinventing.

## 7. Seeding your history — the one manual chore

SnapTrade gives you *current* positions. To chart 2–3 years of returns you need the transactions behind them.

- **Fidelity:** exports transaction history as CSV, but **capped at 90 days per download**, with about 5 trading years available. So covering 3 years is roughly **12 downloads**. Tedious once, then never again — write the importer to be idempotent so you can drop files in any order and re-run safely.
- **Robinhood:** account statements and CSV export, under a year of history to cover.
- After the seed, SnapTrade keeps it current automatically.

Budget a weekend for this. It's the single least fun part of the project and it's also what makes every performance chart afterward actually true.

---

## 8. The Method Library — your best idea, and it's free

You mentioned wanting to feed me the work of chartists and technical analysts you rate, and have the app absorb their style. **This is the most differentiated feature in the whole project, and it costs nothing but effort.** Nothing on the market does it.

The design: each analyst becomes a **structured method definition** — not a blog post, a machine-readable profile:

```yaml
method: "<analyst name>"
timeframes: [daily, weekly]
indicators:
  - {type: ema, period: 21}
  - {type: rsi, period: 14}
  - {type: volume_profile}
setups:
  - name: "pullback to rising 21 EMA"
    conditions: [...]
    invalidation: "close below 50 EMA"
    typical_hold: "6-14 weeks"
risk:
  stop: "below setup low"
  sizing: "1% account risk"
ignores: ["intraday noise", "earnings gaps"]
```

Once a method is structured, it compiles into four things at once:

1. **A chart template** — open any ticker "in their style," with exactly their indicators, their timeframes, their layout.
2. **A scanner** — run their setup conditions across your whole watchlist nightly, surface what qualifies.
3. **A trade checklist** — score a candidate against their criteria before you commit, so you can see *which* conditions you're overriding.
4. **A backtest** — because the conditions are already formal, the same definition runs through `app/backtest.py` over your cached history. **You get to find out whether their method actually works, on the names you actually trade.**

That last one is the payoff. Right now these people's track records are unfalsifiable — you can read them but you can't test them. This makes them testable, and lets you **stack methods** ("show me names where three of my five methods agree"), which is not something any of them can do for you either.

**How we'd work on it:** you send me an analyst's material — videos, posts, threads, book chapters — and I turn it into a method definition, flagging what's mechanical enough to encode versus what's genuinely discretionary. The discretionary parts become checklist prompts rather than automated conditions, which is the honest way to handle them.

---

## 9. Revised build order

| Phase | What | Time | Why here |
|---|---|---|---|
| **1** | **Ledger + history import.** SQLite schema, Fidelity CSV importer, correct time-weighted return, S&P total-return overlay, same-cash-flows benchmark. Robinhood tracked as a **separate crypto account**, not folded into equity performance. | 2–4 wks | Everything downstream needs the ledger. And this alone already beats Fidelity's own reporting. |
| **2** | **Charting + watchlists.** Lightweight Charts, server-computed indicators, tag-based watchlists, custom columns, position awareness on every chart and row. | 3–5 wks | The TradingView-beating half. |
| **3** | **PWA + Tailscale.** Make it good on the phone. | 1 wk | Do this *early*, not last — it changes how you build every screen after it. |
| **4** | **Method Library.** Method schema, chart templates, scanner, checklist. Encode your first two analysts. | 3–4 wks | The differentiator. Needs 1 and 2 in place. |
| **5** | **Paper engine + backtests.** Alpaca paper account, strategy interface, walk-forward backtest over cached history. Backtest the encoded methods. | 3–4 wks | Now the methods become falsifiable. |
| **6** | **Budgeting page.** CSV import, rules engine, LLM categorization fallback, unified net-worth view. | 2–3 wks | Independent of the rest — can slot anywhere you feel like a change of pace. |
| **7** | **Signals.** StockTwits, RSS, macOS notification harvest, congressional filings — all as chart markers and watchlist columns. | 2 wks | Lowest value per hour. Deliberately last. |
| **8** | **The algo experiment.** Backtest → Alpaca paper → **live small on Robinhood crypto**. Deterministic strategies first; LLM as research layer with hard-coded risk limits. Equity signals stay as trade tickets you approve by hand. | ongoing | Built on proven infrastructure rather than being the thing that shapes it. |

---

## 10. Still open

1. **Which analysts do you want encoded first?** Send whatever you've got — sites, channels, threads. Two well-encoded methods beat ten shallow ones, and the first one will teach us what the method schema actually needs to hold. This is the biggest open item and the one that most shapes the build.
2. **The old MacBook Pro: model year and macOS version?** Determines the notification-database path (§3) and whether Docker is worth bothering with. Run `sw_vers` on it. And run the battery check in §5b before committing it to always-on duty.
3. **Which bank and card issuer?** So I can check them against the OFX Direct Connect lists before we build anything. If they support it, budgeting becomes fully automatic; if not, we go with the statement-drop pipeline. Thirty minutes of checking decides a whole subsystem.
4. **Do you want the Robinhood crypto algo experiment in scope early, or later?** It's now genuinely available, but it's a different market from your equity swing trading. Early gets the machinery proven; later keeps focus on the part you actually trade.
5. **How much Fidelity history at import?** Three years is about 12 CSV downloads (90-day cap each). If one year is enough to start, that's 4 and you can backfill later.
6. **Anything you already like in Fidelity's or TradingView's interface** that I should preserve rather than redesign?

## Sources (new in this revision)
- iOS notification access limits — https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide
- macOS Notification Center database location — https://9to5mac.com/2024/09/01/security-bite-apple-addresses-privacy-concerns-around-notification-center-database-in-macos-sequoia/
- macOS notification DB schema — https://github.com/75033us/blog/blob/main/2022-02-02-macos-monterey-notification-database-schema.md
- SnapTrade Robinhood integration (read-only) — https://snaptrade.com/brokerage-integrations/robinhood-api
- Robinhood Crypto Trading API (crypto only) — https://robinhood.com/us/en/newsroom/robinhood-crypto-trading-api/
- Alpaca paper-only account signup — https://alpaca.markets/learn/register-on-alpaca
- Alpaca paper trading docs — https://docs.alpaca.markets/us/docs/paper-trading
- Free equity price APIs data card — https://edwardlg.github.io/assip-2026-empirical-finance/textbook/data-cards/free-equity-apis.html
- SEC EDGAR APIs — https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- Tailscale free plans — https://tailscale.com/docs/account/manage-plans/free-plans-discounts
- PWAs on iOS 2026 — https://www.mobiloud.com/blog/progressive-web-apps-ios
- Firefly III vs Actual Budget, self-hosted — https://selfhostable.dev/blog/firefly-iii-vs-actual-budget-self-hosted-finance/
- Fidelity 90-day CSV export limit — https://capyparse.com/blog/fidelity-brokerage-cma-statement-to-csv
- Twitter/X API alternatives 2026 — https://www.xpoz.ai/blog/comparisons/best-twitter-api-alternatives-2026/
- Robinhood Crypto Trading API — support article — https://robinhood.com/us/en/support/articles/crypto-api
- Robinhood Crypto trading API docs — https://docs.robinhood.com/crypto/trading/
- ofxtools (Python OFX client) — https://ofxtools.readthedocs.io/en/latest/
- OFX Direct Connect bank settings list (GnuCash) — https://wiki.gnucash.org/wiki/OFX_Direct_Connect_Bank_Settings
- Supported OFX Direct Connect banks — https://www.inzolo.com/direct-connect-supported-banks/
- Intuit OFX connectivity types — https://www.intuit.com/partners/fdp/implementation-support/ofx/why-connect/connectivity-types/
