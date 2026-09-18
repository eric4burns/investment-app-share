#!/bin/sh
# Keep the dashboard running, and refresh the data once a day.
#
#   ./install-agents.sh          install and start them all
#   ./install-agents.sh remove   stop and remove them all
#
# Six launchd agents:
#   serve   starts the dashboard at login and restarts it if it dies
#   update  runs ./update.sh at 18:30, after the US close
#   backup  runs ./backup.sh at 19:30, once update.sh is done: a full
#           snapshot and a small curated one into ~/Backups/investment-app
#   poll    every 15 minutes, checks live prices against each call's levels
#           during market hours and sends alerts (see app/alerts.py)
#   xpull   at 02:10, pulls the followed X accounts' new posts and counts the
#           cashtags, so the "is the crowd here yet" reading has history
#           (see app/xpull.py; needs the session in data/.x)
#   subpull at 03:30, fetches new posts from the subscribed Substacks and seeds
#           the priced calls and levels they name (see app/subpull.py; needs
#           the session in data/.substack — ./substack-setup.sh)
#   ytpull  at 04:00, fetches new videos from the followed YouTube channels,
#           transcribes any without captions, and counts the names spoken
#           (see app/ytpull.py; no credentials needed)
#
# What this CANNOT do is download your statements. Fidelity has no API, and the
# card exports need a browser session, so new files still have to be dropped
# into data/ by hand. What it automates is everything after that: importing
# whatever is new, refreshing prices, and keeping the server up.
set -e
cd "$(dirname "$0")"
ROOT=$(pwd -P)   # physical path: ~/Desktop/Projects is a symlink, and launchd cannot read through ~/Desktop
AGENTS="$HOME/Library/LaunchAgents"
# Logs live under ~/Library/Logs, not in the repo: launchd opens the
# StandardOutPath itself, and it cannot open a file inside ~/Desktop,
# ~/Documents or ~/Downloads (the job never starts, "last exit code = 78:
# EX_CONFIG", nothing in any log). Found 2026-09-13 when the repo moved to
# ~/Desktop/Projects. A symlink logs/ -> that folder keeps `tail logs/x.log`
# working. The python process itself reads the repo fine; only the log path
# has to be outside.
LOGS="$HOME/Library/Logs/investment-app"
# Label prefix from config.json when present, so two people on one machine do
# not collide, and so a fork does not install agents named after someone else.
PREFIX=$(python3 -c "import json,pathlib;p=pathlib.Path('config.json');print((json.loads(p.read_text()).get('label_prefix') if p.exists() else None) or 'investment-app')" 2>/dev/null || echo investment-app)
LABELS="com.$USER.$PREFIX.serve com.$USER.$PREFIX.update com.$USER.$PREFIX.backup com.$USER.$PREFIX.poll com.$USER.$PREFIX.xpull com.$USER.$PREFIX.subpull com.$USER.$PREFIX.ytpull"
# The template files are named by ROLE, not by label: the label contains the
# username, so naming the files after it would mean a fork could not find its
# own templates.
ROLES="serve update backup poll xpull subpull ytpull"

if [ "$1" = "remove" ]; then
  for label in $LABELS; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    rm -f "$AGENTS/$label.plist"
    echo "  removed $label"
  done
  exit 0
fi

PYTHON=$(command -v python3)
[ -n "$PYTHON" ] || { echo "  python3 not found" >&2; exit 1; }

# This machine's Tailscale address, so the dashboard is reachable from a phone
# without listening on every network the laptop joins. Resolved at install time
# because it is stable per device. If Tailscale is not installed or not logged
# in, fall back to loopback rather than baking in a placeholder: an unbindable
# address would send the server into a retry loop for something the user never
# asked for.
# Tailscale is looked for in four places because it installs to a different one
# depending on how it was obtained, and only the first of these is on PATH:
# the /usr/local/bin shim exists ONLY if the user ran "Install CLI" from the
# Tailscale menu bar, which most people never do. Checking that path alone —
# which this did — meant a Mac App Store install reported "no Tailscale address
# found", bound loopback, and the phone silently never worked.
TS=""
for cand in \
  "$(command -v tailscale 2>/dev/null)" \
  /usr/local/bin/tailscale \
  /opt/homebrew/bin/tailscale \
  /Applications/Tailscale.app/Contents/MacOS/Tailscale
do
  [ -n "$cand" ] && [ -x "$cand" ] && { TS="$cand"; break; }
done

TSIP=""
[ -n "$TS" ] && TSIP=$("$TS" ip -4 2>/dev/null | head -1)
if [ -n "$TSIP" ]; then
  HOSTS="127.0.0.1,$TSIP"
  echo "  Tailscale address: $TSIP"
elif [ -n "$TS" ]; then
  HOSTS="127.0.0.1"
  echo "  Tailscale is installed but not logged in — binding loopback only."
  echo "  Sign in, then re-run ./install-agents.sh to reach this from your phone."
else
  HOSTS="127.0.0.1"
  echo "  Tailscale not found — binding loopback only."
  echo "  The dashboard will work on this Mac but NOT on your phone."
  echo "  To fix: install Tailscale, sign in, then re-run ./install-agents.sh"
fi
mkdir -p "$AGENTS" "$LOGS"
if [ -d logs ] && [ ! -L logs ]; then mv logs/* "$LOGS"/ 2>/dev/null || true; rmdir logs; fi
[ -e logs ] || ln -s "$LOGS" logs

for role in $ROLES; do
  label="com.$USER.$PREFIX.$role"
  src="launchd/$role.plist"
  dst="$AGENTS/$label.plist"
  # Absolute paths, resolved now: launchd has no shell, no cwd of its own and
  # almost no PATH, so anything relative simply fails to start with a message
  # that says nothing about why.
  sed -e "s|__ROOT__|$ROOT|g" -e "s|__LOGS__|$LOGS|g" -e "s|__PYTHON__|$PYTHON|g" \
      -e "s|__LABEL__|$label|g" \
      -e "s|127.0.0.1,__TAILSCALE_IP__|$HOSTS|g" \
      -e "s|__PYTHONDIR__|$(dirname "$PYTHON")|g" "$src" > "$dst"
  plutil -lint "$dst" >/dev/null
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  # bootout returns before the job has finished going away, and bootstrapping
  # a label that is still unloading fails with "Bootstrap failed: 5: Input/
  # output error". With set -e that aborted the whole loop -- on the FIRST
  # role, serve, which had just been booted out. The dashboard was left down
  # and the remaining agents never installed. Wait for the label to clear, and
  # do not let one failure take the others with it.
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1 || break
    sleep 1
  done
  if launchctl bootstrap "gui/$(id -u)" "$dst"; then
    echo "  installed $label"
  else
    echo "  FAILED to install $label — re-run ./install-agents.sh" >&2
    FAILED="${FAILED:-} $label"
  fi
done

if [ -n "${FAILED:-}" ]; then
  echo
  echo "  NOT installed:${FAILED}" >&2
fi

echo
echo "  dashboard: http://localhost:8737"
echo "  logs:      $LOGS/  (logs/ in the repo points there)"
echo "  remove:    ./install-agents.sh remove"
