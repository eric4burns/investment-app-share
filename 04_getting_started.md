# Getting the Ball Rolling

> **This file is history, kept deliberately.** It was written on 2026-08-29,
> before any of the app existed, and every task in it is done: the Fidelity
> exports are imported, the bank and card paths are mapped, the performance
> engine agrees with the broker to 0.014%. Nothing here is a to-do list any
> more.
>
> It is kept because it explains WHY the ledger is shaped the way it is —
> which exports were available, which were capped, and what had to be worked
> around. For what is actually outstanding see **`06_feature_roadmap.md`**;
> for how to run it see **`SETUP.md`** and **`HOW_TO_RUN.md`**.


The goal of the first push is one concrete, motivating thing:

> **See your real Fidelity return, correctly calculated, plotted against the S&P — something Fidelity itself won't show you.**

Everything below is either work you do or work I do, and the two run in parallel.

---

## Your side — five short tasks, none longer than 30 minutes

### 1. Check the old MacBook Pro (10 min) — deferred, machine not accessible
Not blocking anything. When you can get to it:

```bash
sw_vers                                    # macOS version -> notification DB path
system_profiler SPHardwareDataType | grep -E "Model Name|Model Identifier|Chip|Memory"
system_profiler SPPowerDataType | grep -A3 -E "Cycle Count|Condition|Maximum Capacity"
```

Send me all three outputs. **If battery condition is anything other than Normal, or cycle count is high, don't leave it plugged in 24/7 yet** — an old battery held at full charge is the classic swelling scenario. We'll work out a plan before it goes on a shelf.

### 2. ~~Name your bank and card issuer~~ — done
Frost, Chase, Fidelity, Amex, Capital One. Checked: only **Fidelity** is a likely OFX Direct Connect candidate; Chase discontinued it in 2022, Capital One never supported it for cards, Amex has moved on. **One thing left: call Frost Bank** and ask whether they support *Quicken Direct Connect* specifically. Five-minute call, and it's the only remaining unknown.

### 3. ~~Start the Fidelity CSV downloads~~ — DONE 2026-08-29
Pulled via Claude in Chrome on the user's own logged-in session. Fidelity's custom range is capped at **93 days, going back 5 years**, so 12 months took four passes:

| File | Transactions | Range |
|---|---|---|
| `fidelity_2025-08-29_2025-11-29.csv` | 628 | 08/29/2025 – 11/28/2025 |
| `fidelity_2025-11-30_2026-03-02.csv` | 551 | 12/01/2025 – 03/02/2026 |
| `fidelity_2026-03-03_2026-06-03.csv` | 473 | 03/03/2026 – 06/03/2026 |
| `fidelity_2026-06-04_2026-08-29.csv` | 256 | 06/04/2026 – 08/28/2026 |

**1,908 transactions, contiguous, no gaps.** Six accounts present: Individual-TOD, ROTH IRA, BROKERAGELINK, BrokerageLink Roth, L3HARRIS Retirement Savings Plan, Health Savings Account.

CSV columns: `Run Date, Account, Account Number, Action, Symbol, Description, Type, Exchange Quantity, Exchange Currency, Currency, Price, Quantity, Exchange Rate, Commission, Fees, Accrued Interest, Amount, Settlement Date`. Each file carries a multi-line legal footer after the data that the importer must strip.

**Remaining:** backfill to 3 years = 8 more windows, same procedure. Not blocking.

### 4. Create two free accounts (10 min)
Neither is a brokerage account, neither takes money or an SSN.

- **Alpaca paper-only** — email signup. Gives us 7+ years of price history and the paper trading sandbox.
- **SnapTrade developer** — free tier includes one connected user; this is what syncs Fidelity and Robinhood positions going forward.

### 5. Send me your first analyst (whenever)
The Method Library is the part nothing else on the market does, and the first encoded method will teach us what the schema actually needs to hold. **Two well-encoded methods beat ten shallow ones**, so start with whoever you trust most — links, channels, threads, whatever you have.

---

## My side — starts now, needs nothing from you

1. **Repo scaffold** — Python standard-library backend, SQLite schema, project structure.
2. **The ledger** — double-entry schema that serves portfolio *and* budgeting from day one (decision D7), with accounts, transactions, positions, and tax lots.
3. **Fidelity CSV importer** — idempotent, deduplicating, tolerant of the format quirks. Ready before your downloads land.
4. **Performance engine** — Modified Dietz / time-weighted return, benchmark alignment, and the same-cash-flows SPY replay.
5. **Price ingestion** — cached bars from Alpaca with Stooq as fallback, stored once and never re-fetched.

---

## What "done" looks like for round one

A local page showing your Fidelity portfolio value over the last 12 months, with a correctly-computed time-weighted return line, an S&P total-return overlay indexed to the same start, and the same-cash-flows benchmark that answers *"would I have done better just buying SPY?"*

No charting library, no watchlists, no signals, no phone access yet. Just the number, correct, for the first time.

---

## Priority order if you only do one thing

**Task 3** — start the Fidelity CSV downloads, or let me drive them via Claude in Chrome. It's the long pole and everything in round one waits on real data.
