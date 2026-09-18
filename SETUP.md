# Setting this up with your own data

A personal portfolio and budget dashboard. It reads exports from your broker,
bank and credit cards, and answers questions those exports cannot on their own:
what you actually own, what it is worth, whether you beat the index, where the
money goes, and what you owe in tax.

It runs entirely on your own machine. Nothing is uploaded, there is no account
to create, and the only network calls are to fetch share prices.

---

## What you need

- **Python 3.11+**. No build step, no framework, no package install for the app
  itself — it is standard library only.
- **macOS**, or **Linux with one caveat** (below).
- **A free Alpaca account** for share prices. Email only; no SSN, no funding.
- Optional: `poppler` for reading pay stubs (`brew install poppler`), and
  `npm install -D playwright && npx playwright install chromium` if you want to
  run the browser test.

---

### Which platforms this actually runs on

Stated plainly, because "should work anywhere" is how people lose an evening.

| | The app | `./update.sh`, tests, backups | `./install-agents.sh` |
|---|---|---|---|
| **macOS** | yes | yes | yes |
| **Linux** | yes | yes | **no — macOS only** |
| **Windows** | should — `Investment App.bat` starts it; not yet verified on a Windows machine | no | no |

`install-agents.sh` uses launchd (`launchctl`, `plutil`, `~/Library/LaunchAgents`),
which exists only on macOS. On Linux everything else works; you start the server
yourself, or write a systemd unit, and set the listen address by hand:

```
INVESTMENT_APP_HOST=127.0.0.1,$(tailscale ip -4) python3 -m app.web
```

On Windows the shell scripts do not run at all. The app is stdlib Python and
`Investment App.bat` starts it (and adds the Tailscale address when signed in),
but no Windows machine has run it yet, so treat it as unverified rather than as
probably fine.

The **phone** is a different question and the answer is simpler: your phone only
opens a web page, so any phone with a browser works — iPhone or Android. It is
the machine *running* the app that has to be macOS or Linux.

---

## 1. Get it running — about five minutes

```
cd investment-app
python3 -m app.web
```

Open **http://localhost:8737**. It will be empty. That is expected: there is no
data yet.

## 2. Add price access

Create a free paper account at alpaca.markets, then put the key id and secret on
two lines:

```
mkdir -p data
printf 'YOUR_KEY_ID\nYOUR_SECRET\n' > data/.alpaca
```

Without this the app still works, but no share prices are fetched and every
position is valued at what you paid.

## 3. Export your data

Each folder under `data/` takes one kind of file. Create the ones you need;
missing folders are skipped, not errors.

| Folder | What goes in it | Where to get it |
|---|---|---|
| `data/fidelity/` | Fidelity activity exports (`.csv`) | Accounts & Trade → Activity → Download. Capped at 90 days, so take several. |
| `data/bank/` | Bank export (`.ofx`) | Most banks: Download transactions → OFX/Quicken. Up to 2 years in one file. |
| `data/cards/` | Any card issuer's export (`.csv`) | Name the file for the card: `chase_sapphire.csv` becomes the account "Chase Sapphire". |
| `data/robinhood/` | Account activity report (`.csv`) | Reports and statements → generate a report over the full date range. **Excludes crypto and Spending** — the report says so in its own footer, so any crypto you hold will be missing while the deposits that bought it are present, leaving the balance looking like idle cash. |
| `data/budget/` | Your own budget spreadsheet (`.csv`) | Optional. Categories down the side, months across the top. |
| `data/payroll/` | Pay stubs (`.pdf`) | Optional, and worth it — see below. |

Then:

```
./update.sh
```

This imports everything, fetches prices, and prints a summary. **Re-run it as
often as you like**: every importer is idempotent, overlapping exports are
deduplicated, and a cached price is never fetched twice.

## 4. Check what it guessed

The import prints the account kind and tax status it inferred from each account.
Read that list once, then correct anything wrong: copy `config.example.json` to
`config.json` and add

```json
{ "accounts": { "Account 4471": { "kind": "retirement", "tax_status": "tax_free" } } }
```

Every key in that file is optional; the app runs with no config at all.

Worth doing because a name like `ROTH IRA` classifies itself correctly and one
like `Account 4471` does not — and a wrong tax status quietly distorts every
after-tax figure without ever looking like an error.

## 5. Tell it your tax profile

```json
{ "filing_status": "married_jointly", "age": 34 }
```

Filing status changes the standard deduction, every bracket threshold and the
Roth phase-out band at once — for a joint filer the Roth band starts ninety
thousand dollars higher than for a single one, so the default being wrong is not
a rounding difference. The default is `single`.

## 6. The rest of `config.json`, and when each matters

Every key is optional and the app runs with none of them. These are the ones
worth knowing about, and `config.example.json` documents all of them.

| Key | Set it when |
|---|---|
| `stub_employer` | **Two incomes.** A pay stub replaces payroll DEPOSITS with gross wages, and `Salary` holds both people's — so without the payer name on your own deposits, the other earner's wages are subtracted and never added back. |
| `spouse_annual` | A second income your stubs cannot see. **A GROSS figure**, because the Roth phase-out is measured on MAGI. Cross-check it: deposits landing at roughly three quarters of the number means it is gross; equal to it means it is net and too low. |
| `savings_goal` | You want Budget → Plan vs actual to compare against something. Defaults to 3,500 a month; money moved into investments counts toward it. |
| `sec_contact` | You use the Research tab. SEC EDGAR asks every caller to identify itself and throttles those that do not. |
| `chart_proxy` | You hold a foreign company through a thin US OTC line. `{"SIVEF": "SIVE.ST"}` reads the chart from the home listing and rescales it into your currency. |
| `label_prefix` | Two people run this on one machine, so the launchd agents must not collide. |

---

## Two things that are worth the effort

**Import your credit cards.** A bank export records the *payment* to a card, not
what was bought with it. Without the card statements the app can see that money
left, and nothing about where it went — it reports this as an explicit blind
spot rather than showing a total that looks complete.

**Import your pay stubs.** A payroll deposit is net of tax and of every
deferral, so a ledger built from deposits alone understates gross income
badly, cannot tell your 401(k) deferral from your employer's match, and has no
idea what has been withheld.

---

## Running it all the time — optional

```
./install-agents.sh          # install and start
./install-agents.sh remove   # undo
```

Two launchd agents: one keeps the dashboard running and starts it at login, one
refreshes prices at 18:30 after the US close. Logs land in `logs/`.

### What updates by itself, and what does not

**Prices do.** The nightly job refreshes benchmarks and everything you hold.

**Transactions do not.** Nothing can log into your broker, so a trade is
invisible until you download a new export into `data/` and re-run `./update.sh`.

## Giving a copy to somebody else — optional

`./share.sh` cuts `~/Desktop/investment-app.zip`: one clean commit, no history, and it refuses to hand over an archive containing the ledger, a data file, `config.json` or a key. **Do not email it** — Gmail blocks any zip holding a `.js` or `.bat`, and this one has thirteen. The public repo `eric4burns/investment-app-share` is the `share` remote, so every `./share.sh` also pushes there and the link to send is always **https://github.com/eric4burns/investment-app-share/archive/refs/heads/main.zip** (D130). The zip on the Desktop is for AirDrop. What the other person gets is an app, not a folder of code:

- **Investment App.command** (Mac) and **Investment App.bat** (Windows) — double-click to start; they find Python 3.11+, or open its download page, and open the browser. If Tailscale is installed and signed in on their machine, the launcher also listens on its Tailscale address and prints the address to open on their phone — the same private-link route as below, never the whole Wi-Fi network.
- **GETTING-STARTED.md** — the whole of their setup in one page.
- The **Get started** screen in the app itself: the export clicks for Fidelity, Robinhood, a bank's Web Connect file, credit cards and pay stubs; a file picker that imports on the spot; the free Alpaca price key; filing status and age. Nothing for them to run or edit by hand. The same screen is behind **Import files / setup** at the top of the Overview for adding later exports.

There is no way to "connect" a brokerage by login: Fidelity and Robinhood have no free personal API, and aggregators cost money and need a hosted service. Exports are the honest route, and everything stays on their machine.

## Reaching it from your phone — optional

1. Install [Tailscale](https://tailscale.com/download) on this computer.
2. Open Tailscale and sign in.
3. Install Tailscale on your phone from the App Store or Play Store.
4. Sign in on the phone **to the same account**.
5. Turn the Tailscale toggle on, on the phone.
6. Run `./install-agents.sh` on this computer. *(macOS only — on Linux, start
   the server with `INVESTMENT_APP_HOST=127.0.0.1,$(tailscale ip -4) python3 -m app.web`
   instead.)*
7. Run `./phone.sh` — it prints the address to open.
8. Open that address in your phone's browser.
9. On iPhone: Share → **Add to Home Screen**.

`./phone.sh` also checks whether the server is actually listening on that
address, and tells you what to do if it is not. Run it whenever the phone
cannot connect — it is faster than guessing.

### Why Tailscale rather than just typing the laptop's IP

The server has no password and reads your whole ledger. Tailscale gives it an
address only your own devices can reach, so it works on cellular, at home and at
work without ever being exposed to the network you happen to be joined to.

**Never set `INVESTMENT_APP_HOST` to `0.0.0.0`.** That puts your entire
financial history on whatever café Wi-Fi the laptop joins.

---

## Reaching it from a work computer

A work machine usually allows only the normal web ports, so the `:8737` address the phone uses is blocked there even though Tailscale connects. The fix, done once on this Mac and kept across restarts, is Tailscale Serve carrying the app on port 80 inside the tailnet:

```
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg --yes --http=80 8737
```

Then on the work computer:

1. Install Tailscale and sign in with the same account.
2. Open `http://erics-macbook-pro/` (or `http://erics-macbook-pro.tail9d4790.ts.net/`). The bare `100.x` number does not work on port 80 — Serve answers only to the machine's name.

This is tailnet-only; nothing is exposed to the internet. `tailscale serve status` shows it; `tailscale serve --http=80 off` removes it. The Mac has to be awake: System Settings → Battery → Options → "Prevent automatic sleeping on power adapter when the display is off".

## Alerts on your phone — optional

The app can tell you when a verdict changes, when a price reaches a level a
call named, when a DCA tier moves, and when a report is days away. Nightly
after the close, and every 15 minutes during the session for a price through
a stop or a trim level. On this Mac it uses the normal notification centre
with nothing to set up. For the phone:

1. Install the free **ntfy** app from the App Store.
2. In ntfy, tap **+** and subscribe to a topic. Make the name long and random, like `eb-invest-7f3a9c2d41`. The name is the only secret: anyone who knows it can read the alerts.
3. Put it in `config.json`:

       "alerts": {"ntfy_topic": "eb-invest-7f3a9c2d41", "macos": true, "min_level": "warn"}

4. Send yourself a test:

       python3 -m app.alerts test

5. If the launchd agents are installed, re-run `./install-agents.sh` once so the 15-minute poll is installed too.

Everything that fires is also listed on the Overview under **Alerts**, sent or
not, so a quiet phone is never a mystery.

## Amazon returns — optional

Budget → Loose ends can check that every Amazon refund actually reached a card.
It reads the refund emails from the mailbox on your Amazon account over IMAP,
read-only, and keeps only the order number, date and amount.

1. Make sure your Amazon account's email is the Gmail address.
2. Open https://myaccount.google.com/apppasswords (2-step verification has to be on).
3. Type a name such as `investment-app` and click **Create**.
4. Copy the sixteen-character password Google shows.
5. In `config.json`, add:

       "gmail": {"user": "you@gmail.com", "app_password": "xxxx xxxx xxxx xxxx", "since_days": 120}

6. Restart the server and open Budget → Loose ends.

The app never sees your Google password; the app password can be revoked on
the same page at any time.

The same connection reads Fidelity's "Your trade confirmation is available"
emails, which arrive the morning after a fill. The nightly update puts each one
in the journal as a trade made — action and price, shares pending — so the app
knows what you did weeks before the statement says so. Trades → "From your
Fidelity emails".

## Checking it works

```
./run_tests.sh
```

52 Python suites (2,009 checks), a browser test (97) that opens every tab in
Chromium, and the same against an empty ledger (8). Run it after any change — a green Python run says nothing about
whether the page renders, which is the failure this project keeps having.

---

## Where your data lives, and what is private

Everything under `data/`, the `ledger.db` database, `config.json` and `logs/`
are gitignored and never leave the machine.

**`ledger.db` is not disposable.** Rebuilding it from `data/` recovers the
imported transactions and nothing else — your watchlist, its tags, your
categorisation rules and any chart drawings exist only inside the database. Run
`./backup.sh` before anything destructive.

If you keep this in a synced folder, note that iCloud's "Desktop & Documents"
option syncs `~/Desktop` and `~/Documents`. Financial exports in either of those
are being copied to every device on the account.

## Monthly statement pull (what worked on 2026-09-04)

Claude drives the exports through the Chrome extension; you sign in, it
downloads and imports. Sessions do not carry into Claude's tab group, so
each site needs a sign-in in the tab Claude opens.

| Source | Route that works | Notes |
|---|---|---|
| Fidelity (all accounts) | Activity & Orders → download icon → "Download as CSV", Past 30 days | file to `data/fidelity/fidelity_<from>_<to>.csv` |
| Robinhood | Reports and statements → Reports → Download CSV of the existing report | generate a new report first if the range is stale |
| Chase | open the card, then `#/dashboard/accountDetails/downloadAccountTransactions/index;params=accountId,<id>` — the account comes preselected; the picker on the plain page ignores automation | file to `data/cards/chase_sapphire_preferred_<yyyy>_<mm>.csv` |
| Amex | Activity → Download → CSV | needs the site allowed in the extension |
| Capital One | View Account → Download Transactions → CSV, Custom Date Range | file to `data/cards/capital_one_quicksilver_<yyyy>_<mm>.csv` |
| Frost | Download transactions → tick the account, From date, Format OFX | the From field is masked: set it with form_input, not typing |
| Fidelity Rewards Visa | export is by statement only; the link opens a separate window Claude cannot reach | pull once a month after the ~27th close, from your own window |

Then `python3 -m app.import_all`. Every importer is idempotent, so overlapping
ranges are fine.

You do not have to remember the month: once an account's newest transaction
is five weeks old (a pay stub, six), Today lists it as **export due** with
the folder the file goes in, and again each week until it lands (D125).


## The overnight research pulls

Both run themselves once set up, and both feed `x_mentions` — the table behind
the "is the crowd already here?" reading on a name.

### X — one-time setup

The pull needs your logged-in x.com session, because X's own API starts at $100
a month. Run:

```
./x-setup.sh
```

It asks for two cookie values from Chrome (DevTools → Application → Cookies →
`https://x.com`): **auth_token**, then **ct0**. Both are read without echoing
and never touch your shell history. It writes `data/.x`, private to you, and
tests the session immediately.

Copy each value from the **Cookie Value** panel *below* the table — the Value
column in the table itself is truncated. For `ct0`, the reliable way is the
DevTools Console: `copy(document.cookie.match(/ct0=([^;]+)/)[1])`.

Two things to know. **That token is your account** — anyone holding it is
signed in as you, with no password and no two-factor. Logging out of x.com in
that browser invalidates it everywhere, including here. And **automated
collection is outside X's terms of service**: it is the same requests your
browser makes, at a slower rate, against your own follows, but it is a terms
question rather than a technical one and the choice is yours. The same position
applies to the Yahoo price fallback in `app/prices.py`.

To edit which accounts are read: `research/x/accounts.txt`, one handle a line.
To turn the pull off, delete `xpull` from `ROLES` in `install-agents.sh` and
re-run it.

`research/x_pull.js` remains as the manual fallback — paste it into a logged-in
x.com tab and it does the same pull by hand.

### YouTube — no setup

Nothing to configure. Channels live in `app/ytpull.py`; add one by adding its
handle and `/videos` URL. Videos without captions are transcribed locally, for
which `research/video/setup.sh` must have been run once (it builds whisper.cpp
and downloads a model — free, about 470 MB).

### Reading a chart video

For a video that is someone flipping through charts rather than talking over
one, `research/video/collect.sh` reads the whole thing: which names were shown,
in what order, what was said about each, and the price levels drawn on them.
`research/video/README.md` has the detail.

## Your own buy-back level for a name

The trade-around card and the Chart aim the buy-back at half the sale price. To name your own level for a symbol, add it to `config.json`:

```json
"buy_back_targets": {"IREN": 32.0}
```

The card picks the level price has turned at nearest your number, or your number itself if none is within 10% of it.
