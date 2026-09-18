# Running the app

> Setting this up for the first time, on your own machine and your own data?
> Read **[SETUP.md](SETUP.md)** instead. This file is day-to-day operating
> notes for a copy that is already working.

## Reaching it from another device

    ./phone.sh

It prints the address to open on your phone and checks that the server is
actually listening on it. Every device is different, so the address is looked up
rather than written down here.

`INVESTMENT_APP_HOST` is a comma-separated list of addresses to listen on and
defaults to `127.0.0.1` alone; `./install-agents.sh` adds this machine's
Tailscale address, so the installed service listens on loopback and the tailnet
and nothing else.

That is deliberately not `0.0.0.0`. There is no password on this server and it
reads the whole ledger, so listening on every interface would put it on whatever
coffee-shop or airport Wi-Fi the laptop joins. Naming the two addresses keeps
`localhost` working here and the phone working over Tailscale, while an
untrusted network has no socket to reach at all.

If Tailscale is not up when the service starts at login, it binds loopback
immediately and retries the other address every 15 seconds, so nothing waits on
the tunnel.

**A work computer** usually blocks port 8737 even with Tailscale connected, so
the Mac also serves the app on port 80 by name over Tailscale Serve: open
`http://erics-macbook-pro/` there. Set up once and kept across restarts; the
command and the checks are in SETUP.md, "Reaching it from a work computer".

## What to open

Seven sections, each named for the question it answers, with sub-tabs
underneath (since 2026-09-13, D117). It opens on **My Money → Overview**.

**Today → What to do** is one ranked list, biggest dollars first: alerts,
tomorrow's buy plans, the "worth a look" items and the Diagnose findings,
each saying what it is and what to do, with a box to tick it off. **Today →
Market** is the fear-and-greed reading, the regime and the indices.

**My Money** — Overview, Holdings, Trades, Risk, Sectors — is everything the
ledger says; the Period / Scope / Vs bar lives here. **Stocks** is the app's
read on names: Holdings calls (one verdict per held name on monthly, weekly
and daily, led by the longest timeframe with enough history), Watchlist,
Setups (each row leads with buy at / sell into / wrong below), Buy back, and
New Stocks (the nightly scan). **Who I Follow** holds everything from X,
YouTube, Substack and Patreon — their calls graded, their charts, their
methods, and the form to record a call. **AI Trade Bot** is the paper
account, the engine's record and the backtest.

**Click any name anywhere** and it opens that name's page under **Chart**:
the chart, The read (the verdict and why), Plan & levels (every level with a
reason, yours in amber), Who I follow on it, and My trades.

**Budget → Plan vs actual** compares each category against its own trailing
average and the month against your savings goal. **Budget → Taxes** projects
whether the year crosses the Roth phase-out or the next bracket.

The Stocks calls state which day's prices they were scored from and offer a
refresh when that is behind — during the session they work from the previous
close, because the nightly job runs at 18:30. The theme toggle (System /
Light / Dark) is top right.

## Every day / whenever you want to look

```
cd ~/Desktop/Projects/investment-app
python3 -m app.web
```

Then open **http://localhost:8737**. Leave it running; it uses no resources idle.
Double-clicking **Investment App.command** does the same from the Finder, and
is what a friend's copy starts with (GETTING-STARTED.md).

- **Anywhere** (phone, work PC, cellular): install Tailscale on the other
  device, sign in to the same account, then open the address `./phone.sh`
  prints. Free, no port forwarding, nothing exposed publicly, and it works on
  cellular exactly as it does at home.
- **Same Wi-Fi by LAN address no longer works**, on purpose — go through
  Tailscale, which works everywhere including at home.
- On iPhone, Share → **Add to Home Screen**. It opens as a real app.

Your period, scope, benchmarks, chart indicators and last-viewed symbol are remembered in the browser, per device — so the phone and the desktop each keep their own view.

## Working on it with Claude Code, from iTerm2

The project carries its own `CLAUDE.md`, so a fresh session reads the
decision log, the roadmap and the layout spec before touching anything.

1. Open iTerm2.
2. `invest` (a shell function: it does `cd ~/Projects/investment-app && claude`)
3. (nothing — Claude is already starting)
4. Type what you want changed, in your own words.
5. When it says a change is live, open http://localhost:8737 and look.

To pick up a previous session where it left off, type `invest --continue`
instead.

## Checking everything still works

The size suite is part of the run: it fails when a source file, a document,
the database, the logs, the audits folder or the backup folder passes a
budget written in `tests/test_size.py`, and when two files in the project
have the same contents. Raise a budget on purpose, with the reason beside it,
rather than working around it.


```
./run_tests.sh
```

52 Python suites (2,009 checks), a browser test (97) that opens the app in
Chromium and walks every tab, and the same browser test against an empty
ledger (8). It takes about ten minutes, most of it the browser. Run it after
any change — a green Python run says nothing about whether the page renders,
which is the failure this project keeps having.

```
./smoke.sh
```

Just the browser half, against a throwaway copy of the ledger.

## Updating prices — ~15 seconds

```
./update.sh
```

Refreshes benchmarks and every held security, re-imports anything new sitting in `data/`, then prints the performance summary. Safe to run as often as you like: importers are idempotent and a cached bar is never re-fetched.

**Run this before you look at anything, if it's been more than a day.** Prices are cached, so without it the dashboard shows the last close it knows about.

## Adding new transactions — the only manual part

Fidelity caps each export at **93 days**, so this is periodic rather than automatic.

1. Fidelity → **Activity & Orders**, set the date range to cover since your last import.
2. Make sure all five filter chips are on (Orders, History, Transfers, Deposits, Dividends/Interest).
3. Download icon → **Download as CSV**.
4. Drop the file in `data/fidelity/`.
5. `./update.sh`

Or skip the folder: **Import files / setup** at the top of the Overview takes
the same file from a picker and imports it on the spot, saying how many rows it
read. Same importer, same duplicate check.

Overlapping ranges are fine — duplicates are detected and skipped, so when in doubt grab a wider window.

**Your bank** is usually easier: Download transactions → **OFX** → often up to
2 years in one file → `data/bank/`.

**Credit cards** — any issuer, into `data/cards/`. Name the file for the card
(`chase_sapphire.csv` becomes the account "Chase Sapphire") and the importer
handles the rest: it reads the header to find the columns and works out the sign
convention from the payment rows. Issuers disagree about this — Chase writes
purchases negative, Amex and Discover write them positive, Capital One uses
separate Debit and Credit columns — and getting it backwards would import a year
of spending as a year of income, so the import prints which evidence it used for
every file.

Capital One caps a download at one year and 25 months of history, so two exports
cover the usual window. Amex offers whole years directly.

**Your own budget spreadsheet** — export as CSV into `data/budget/`. Put the
year in the filename (`budget_2025.csv`) unless the column headings already
carry it, because a column headed just "Jan" is ambiguous in a file and a
two-year sheet has two of them. It is never added to the app's totals; it is a
reference series, used to measure what the exports cannot see.

Ask me and I can drive those downloads through your browser rather than you
clicking through them. The route that works for each site, and which ones need
you to sign in first, is in SETUP.md under "Monthly statement pull". Today
tells you when one is due: an account whose newest transaction is five weeks
old shows as **export due**, weekly, until the file lands.

## Keeping it running by itself — optional

```
./install-agents.sh          # install and start
./install-agents.sh remove   # undo
```

Seven launchd agents. Logs land in `logs/`, one file each; `update.sh` trims
any log past 1 MB back to its last 200 KB.

| agent | when | what it does |
|---|---|---|
| `serve` | at login | keeps the dashboard running, restarts it if it dies |
| `update` | 18:30 | `./update.sh` — re-import, refresh prices, record verdicts, prune (`app/retention.py`) |
| `backup` | 19:30 | `./backup.sh` — a full snapshot and a small curated one, see below |
| `poll` | every 15 min | checks live prices against each call's levels in market hours |
| `xpull` | 02:10 | the followed X accounts' new posts, the cashtags in them, the calls in words (`app/xcalls.py`) into the journal, and their charts saved by account (`app/xcharts.py`) |
| `subpull` | 03:30 | new posts from the subscribed Substacks, then their priced calls and levels |
| `ytpull` | 04:00 | new videos from the followed YouTube channels, and the names spoken in them |

Re-running `./install-agents.sh` briefly restarts the dashboard, so it is not a
no-op to run casually.

### The three overnight pulls

X and YouTube feed one table, `x_mentions`, which is what the "is the crowd
already here?" reading on a name is built from. They use the same handle for a
person who posts on both platforms, so somebody like `cantonmeow` counts as
one account rather than two. Since 2026-09-13 the X pull also reads each new
post for a call in words and records it in the journal the same night, marked
"auto" on Who I Follow → Their calls, graded (D122); a wrong reading is
removed with the × on its row.

**`xpull`** needs your logged-in x.com session in `data/.x` — see
`research/x/SETUP.md`, or just run `./x-setup.sh`. It paces itself at 150
seconds an account to stay under X's rate limit, so a full pass over 32
accounts takes about eighty minutes. It writes its result after every account
and resumes an interrupted run, so a sleep or a restart costs one account
rather than the night.

When the session expires the log says `STOPPED: X refused the session` and
nothing else happens. Re-run `./x-setup.sh` to fix it.

**`subpull`** needs your Substack session in `data/.substack`: run
`./substack-setup.sh`, paste the `substack.sid` cookie value from DevTools →
Application → Cookies on the publication's site, and it tests the session
against the newest paid post. The publications are listed in
`research/substack-publications.txt`, one per line. When the cookie lapses the
log says `STOPPED: … the session … has expired` and nothing is written — it
never saves a paywall teaser as a post. Cards, the bank and Fidelity have no
equivalent and stay the monthly routine in `SETUP.md`.

**`ytpull`** needs no credentials. A video with no caption track is transcribed
locally with whisper.cpp — at most two a night, nothing over 90 minutes.

It matches company names, because spoken transcripts contain no cashtags. About
140 of the 206 names you hold or watch have a word distinctive enough to match;
the rest — Apple, Target, Block — do not, and the job prints that coverage
figure every run. A name that cannot be matched looks exactly like a name
nobody mentioned, which is why the number is said out loud rather than assumed.

### What is fresh, and what is not

Two clocks run at different speeds, and it is worth knowing which you are
looking at.

**Prices update themselves.** The nightly job refreshes the benchmarks and every
security you hold, and opening a chart fetches anything not already cached.
Intraday charts re-fetch on every open, because the newest bar is still forming.

**Transactions do not.** Nothing can log into your broker or bank, so the ledger
only learns about a trade or a purchase when you download an export and drop it
in `data/`. The nightly job re-reads the same files and reports every row as a
duplicate until a new one appears.

So the portfolio VALUE tracks the market daily even when no export has arrived:
holdings are carried forward and priced at the last close, which is exact rather
than approximate, because a position's quantity cannot change without a
transaction. What goes stale is the holdings themselves — a trade made today is
invisible until its export is imported.

What this cannot automate is the download — Fidelity has no API and the card
exports need a browser session. What it automates is everything after a file
lands in `data/`.

**Research does update itself now.** The two overnight pulls above run without
you, so the mention history grows nightly rather than whenever somebody
remembers to paste a script into a browser console.

## Where things live

```
app/            code
data/fidelity/  Fidelity activity exports (.csv)
data/bank/      bank exports (.ofx)
data/cards/     any card issuer's export (.csv)
data/budget/    your own budget spreadsheet (.csv)
data/payroll/   pay stubs (.pdf) — gross wages, withholding, 401(k) deferral
data/robinhood/ Robinhood activity report (.csv) — excludes crypto, its footer says so
research/       research-time tools and audits; x/, substack/ and transcripts/ are local only
ledger.db       the database, rebuilt from data/ any time
ledger-replay.db  the replayed calls, once split out (python3 -m app.split_replay); rebuilt by app.replay
~/Backups/investment-app/   where ./backup.sh writes — outside the tree, outside iCloud
logs/           only if the launchd agents are installed
06_feature_roadmap.md   what's next
```

Everything under `data/` is gitignored and never committed.

**`ledger.db` is NOT disposable.** Rebuilding it from `data/` recovers the
imported transactions and nothing else — hand-curated watchlist rows, their
tags, and the sector classifications exist only inside the database — this ledger holds 164 of them. Run `./backup.sh` before anything
destructive; it uses sqlite3's
`.backup`, which is safe on a live WAL-mode database in a way that `cp` is not.

`./backup.sh` writes two files to `~/Backups/investment-app/` (not under
iCloud, unlike the Desktop and Documents folders): `ledger-<stamp>.db.gz`,
the whole ledger, and `curated-<stamp>.db.gz`, a few megabytes holding only
what cannot be rebuilt — watchlist, tags, sectors, the live journal,
drawings, plans, books, basis, categories, rules, transactions. It keeps the
newest seven full snapshots plus the first of each month for six months, and
ninety days of curated ones. The `backup` agent runs it nightly at 19:30.
`ledger-replay.db` is not backed up: `python3 -m app.replay run` rebuilds it.

**Two databases.** The replayed calls (`source` starting `replay`, ~330,000
decisions and 6.6 million evidence rows) live in `ledger-replay.db` beside
the ledger once `python3 -m app.split_replay --apply` has moved them there
(a dry run without `--apply` prints the plan; `--vacuum` gives the space
back afterwards). `replay.py`, `measure.py` and `calibration.py` attach it
when it exists and read the ledger's own table when it does not, so a fresh
clone needs nothing. `python3 -m app.retention` prints what the nightly
prune would delete — old bars for names only the discovery screen knows,
old hits, alerts and intraday bars — and `--apply` deletes it.
