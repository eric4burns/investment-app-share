# Investment app — state

**As of 2026-09-17.** Runs as a launchd agent on :8737 from this folder
(`CLAUDE.md`, "Facts that bite"). Phase 2 shipped today: seven sections, the
design system with both themes, Today as one ranked list, a symbol page behind
every name, chart opening on the last year with the user's marks loudest
(D117). The give-back peak bug was fixed the same morning (D116). Eric's
first read-through of Phase 2 gave ten items; all shipped the same evening
(D120–D124: Holdings shows the headline call, the tax floor counts the
taxable account, followed accounts' calls are journaled the night they are
posted, the Substack is pulled nightly, New Stocks says what each name is,
fib levels are labelled, charts filter by who and when). Later the same
evening: export reminders on Today, the Recurring tab finds the bills that
reprice with every price on the row (D125–D126), and the charts the followed
accounts post on X are saved by account and shown side by side by name
(D127). 2026-09-17: Their charts reads every Substack post, not the newest
dozen — FPS and every name older than two weeks had been missing (D131) —
and the X and Patreon charts on it show their pictures; the URL guard had
blanked every one since D127 (D132) — and a name's own page (Chart → Follow)
shows the X charts of it, which it never asked for (D133) — and the Who filter
names each person once, not once per place they post (D134).
Nightly: X pull 02:10 (32 accounts; calls journaled, charts saved),
Substack 03:30 (session stored 2026-09-13), YouTube 04:00 (7 channels),
verdict cache, ledger prune and backup.

The measured conclusion that steers everything (`research/audits/edge-log.md`):
no mechanical rule beat doing nothing; the sell ladder is off; the edge is
selection in the tail. So the work is on finding names earlier, not scoring
the ones in hand better.

## Next up

1. Live with Phase 2 for a few sessions — fix what Eric cannot find, not
   what is missing. Every alert says what it is and what to do.
2. The crowd reading (early / warming / crowded) cannot be tested until
   months of nightly pulls exist — let it accumulate; do not tune it yet.
3. Reading the transcripts for meaning (what was said about a name) —
   currently only searched for names. Open, not scheduled.

Full detail: `07_improvement_plan.md` ("where this stands") and
`06_feature_roadmap.md`.

## Waiting on Eric

- A friend has it running on Windows (reported 2026-09-18, the first
  Windows report; he set up an older copy and the guide now has an
  "Updating to a newer copy" section). Did the update over the old folder
  work for him, and did he get stuck on any step of the first setup?

- His read of the automatic "auto" calls on Who I Follow after a few nights:
  are the words-only readings worth grading. Reading the chart images is
  open; he chose pulling them in by account first (D127).
