# Turning on the nightly X pull

The pull needs the two cookies from your logged-in x.com session. There is no
free X API — theirs starts at $100 a month — and the logged-out web bundle does
not contain the endpoints the pull uses, so the session is the only way in.

## Steps

`setup-session.sh` reads both values with `read -rs`, so nothing is echoed to
the screen and nothing enters shell history. Never type a token as part of a
command — it lands in `~/.zsh_history` in plain text and stays there.

1. Open `https://x.com` in Chrome, signed in.
2. Press **⌥⌘I**, click **Application**, expand **Cookies**, click **https://x.com**.
3. In Terminal, run `cd ~/Desktop/Projects/investment-app && ./research/x/setup-session.sh`
4. In DevTools, click the row named **auth_token** and copy its **Cookie Value**.
5. Paste at the first prompt and press Return. Nothing appears — that is deliberate.
6. In DevTools, click the row named **ct0** and copy its **Cookie Value**.
7. Paste at the second prompt and press Return.

The script writes `data/.x`, private to you, and immediately tests the session
against one account so you know straight away whether it worked.

To re-test later without re-entering anything:
`./research/x/setup-session.sh --check`

## What that token is

It is the thing that keeps you logged in to X. Anyone who has it is signed in
as you, without needing your password and without triggering two-factor. It is
stored in `data/`, which is never committed, it is sent only to x.com, and the
code never prints or logs it. If you ever want to cut it off, log out of x.com
in that browser — that invalidates the token everywhere, including here.

## When it stops working

The session lasts months, but it dies if you log out. The nightly job then
prints `STOPPED: X refused the session` into `logs/xpull.log` and does nothing
else. Redo the steps above to fix it.

`research/x_pull.js` is still there as the manual fallback: paste it into a
logged-in x.com tab and it does the same pull by hand.

## What it does once it is on

At 02:10 each night it reads the accounts in `accounts.txt`, keeps their own
posts since the last pull, writes them to `pulls/<date>.json`, and counts the
cashtags into the `x_mentions` table. That table is what the "is the crowd here
yet?" reading on a name is built from.

It spaces the accounts about two and a half minutes apart. X answers with HTTP
429 after roughly twenty accounts in an hour, and a nightly job has all night,
so it is deliberately slow rather than fast and blocked.

## A note on X's terms

Automated collection is outside X's terms of service. It is the same requests
your browser makes, at a slower rate, against your own account and your own
follows — but it is a terms question rather than a technical one, and it is
your call. The codebase takes the same position on the Yahoo price fallback in
`app/prices.py`. To turn it off: `./install-agents.sh remove`, then re-run
`./install-agents.sh` after deleting the `xpull` role from `ROLES`.
