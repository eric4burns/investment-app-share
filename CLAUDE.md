# Working on the Investment App

Read these before changing anything, in this order:

- `INBOX.md`, if it exists — answers and notes Eric sent from his phone
  through the Project Board (`~/Projects/board`). Act on each entry, update
  STATE.md, then delete the entry; delete the file when it is empty.
0. `STATE.md` — one page: what is true now, next up, waiting on Eric.
   Keep it under 8 KB; it summarises 06/07, it does not replace them.
1. `README.md` — what every file and module is for.
2. `HOW_TO_RUN.md` — how the app runs day to day, and the section
   "Working on it with Claude Code" below it.
3. `03_decisions.md` — the decision log. Append-only, numbered (D1…);
   the latest entries are the current state of every argument. When it
   passes its 80 KB budget, move the oldest block unchanged to
   `research/audits/decisions-Dxx-Dyy.md` and leave a pointer, in the same
   commit.
4. `07_improvement_plan.md` and `06_feature_roadmap.md` — what is built,
   what is open. Keep both current when something changes.
5. `research/audits/app-review-2026-09-12.md` and
   `phase2-spec-2026-09-13.md` — the last full review and the layout and
   design system that came out of it. The seven sections and their
   sub-tabs are fixed; a new feature goes in an existing sub-tab unless the
   user asks for a new one.

## Facts that bite

- **Statement exports can be fetched with Claude in Chrome.** Fidelity and the
  card sites have no API, so new statements are dropped into `data/` by hand.
  With the user present at the browser, the `claude-in-chrome` tools can log
  in (the user types the password), download the export and move it into
  `data/`; then `./update.sh` imports it. Never store or type a credential.

- **The server on :8737 is a launchd agent with reload OFF.** It serves
  `app/dashboard.html` and `app/static/*.js` fresh from disk (front-end
  edits are live at once) but runs the Python it loaded at start. After
  any `.py` change: `launchctl kickstart -k gui/$(id -u)/com.ericburns.investment-app.serve`,
  then `curl -s localhost:8737/api/health` and confirm `"stale": false`.
  `./run_tests.sh` prints SERVER STALE at the end when this was forgotten.
- **Verify in the running instance, not just the tests.** The smoke test
  starts its own server on 8738 against a copy of the ledger. Before saying
  a feature is done, open http://localhost:8737 and look — at 1440 and at
  390 px (Playwright is in `node_modules`; `tests/phone_shots.mjs` shows
  how). A blank panel is indistinguishable from a feature that was never
  built.
- **Writes need the page's token.** Any request that changes state
  (`action=`, POST, backtest/replay/valuetrader/amazon) is refused without
  `X-App-Token`; the page adds it itself. From a shell:
  `-H "X-App-Token: $(cat data/.token)"`. Plain reads need nothing.
- **Never write to `ledger.db` from a test.** Tests use `:memory:` or a
  temp copy; four suites read the real ledger read-only. Bulk deletes,
  VACUUM and migrations run only with the server stopped and after
  `./backup.sh`.
- **`data/`, `config.json`, `ledger*.db`, `logs/` are private and
  gitignored.** `share.sh` builds a friend's copy without
  `research/audits/`, the seed scripts, the video notes and the PDF.
- **Zero recurring cost, single user, no new brokerage accounts,
  iPhone access required.** Every recommendation leads with the free
  option.
- **The user judges the UI against TradingView** and the numbers against
  Fidelity. Their own data — fills, cost, drawn levels, plans — is
  visually louder than anything the app computes. Alerts and to-do rows
  say in words what the thing is and what to do.
- **File budgets** live in `tests/test_size.py`. When one trips, raise it
  with a dated one-line reason in the same commit — never by deleting
  the check.
- `sqlite3 -readonly ledger.db` for any ad-hoc query.

## Conventions

- Stdlib Python only; vanilla JS/CSS, no build step; template-string
  `innerHTML` with `esc()` on every data-derived string; `safeUrl()` on
  every data-derived `href`/`src`.
- Comments explain why, in full sentences; docstrings carry the reasoning
  and the number that motivated the code.
- One commit per change, message in the repo's voice (`git log -10`): a
  one-line title in plain words, then what and why, ending with the
  attribution lines the session provides.
- `./run_tests.sh` before every commit (about 100 s); it fails on an
  incomplete tally, a suite that ran nothing, or a missing suite.
- Docs move with the code: a bench-tested fact or a corrected number is
  propagated through `03_decisions.md`, `06_feature_roadmap.md`,
  `07_improvement_plan.md`, `README.md` and `HOW_TO_RUN.md` in the same
  commit, not appended as a dated note somewhere else.
