#!/bin/bash
# Double-click to start the Investment App on a Mac. It runs on this computer
# and opens in your browser. Close this window to stop it.
#
# Phone: if Tailscale is installed and signed in on this Mac, the app also
# listens on the Mac's Tailscale address — a private link between your own
# devices — and the address to open on the phone is printed below. It never
# listens on the Wi-Fi network as a whole: the app has no password.
cd "$(dirname "$0")"
# Opened from inside the zip, or dragged out on its own: the app is not here.
if [ ! -f app/web.py ]; then
  echo "This file has to stay inside the investment-app folder from the zip."
  echo "Unzip the archive first (double-click it), then double-click this file inside the folder it makes."
  read -r -p "Press Return to close." _
  exit 1
fi
# A zip that came by AirDrop, mail or a download carries macOS's quarantine
# flag on every file, and that is what makes the double-click say "cannot be
# opened". Once this script IS running (right-click > Open, or Terminal) the
# flag is cleared from the folder so the next double-click just works.
xattr -dr com.apple.quarantine . 2>/dev/null
# Python, without asking anybody to install Python. The Mac's own python3 is
# a stub that wants the 1 GB Xcode tools; python.org is a download, an
# installer and a reboot of the conversation. So: use a real Python 3.11+ if
# one is here, and otherwise fetch a private copy with uv (astral.sh's
# free, single-binary tool) into this user's home — no admin, no PATH, no
# system change, about a minute the first time and nothing after.
PY=""
for c in python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then PY="$c"; break; fi
done
run_py() { "$PY" "$@"; }
if [ -z "$PY" ]; then
  UV=""
  for c in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv "$(command -v uv 2>/dev/null)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then UV="$c"; break; fi
  done
  if [ -z "$UV" ]; then
    echo "Python is not installed. Fetching a private copy for this app (one time, about a minute)…"
    if curl -LsSf https://astral.sh/uv/install.sh | sh -s -- --quiet 2>/dev/null && [ -x "$HOME/.local/bin/uv" ]; then
      UV="$HOME/.local/bin/uv"
    else
      echo "That did not work (no internet?). Install Python 3.12 from the page that opens, then double-click this file again."
      open "https://www.python.org/downloads/macos/"
      read -r -p "Press Return to close." _
      exit 1
    fi
  fi
  PY="uv"
  run_py() { "$UV" run --no-project --python 3.12 python "$@"; }
fi
export INVESTMENT_APP_RELOAD=0
TS=""
for c in "$(command -v tailscale 2>/dev/null)" /usr/local/bin/tailscale /opt/homebrew/bin/tailscale /Applications/Tailscale.app/Contents/MacOS/Tailscale; do
  if [ -n "$c" ] && [ -x "$c" ]; then TS="$c"; break; fi
done
TSIP=""
if [ -n "$TS" ]; then TSIP=$("$TS" ip -4 2>/dev/null | head -1); fi
if [ -n "$TSIP" ]; then export INVESTMENT_APP_HOST="127.0.0.1,$TSIP"; fi
mkdir -p data/fidelity data/robinhood data/bank data/cards data/payroll data/budget
# Double-clicked twice: the app is already up, so open the browser on it
# rather than failing on the port with a message nobody can act on.
if curl -s -o /dev/null http://127.0.0.1:8737/ 2>/dev/null; then
  echo "The Investment App is already running — opening it in your browser."
  open "http://127.0.0.1:8737/"
  read -r -p "Press Return to close this window (the app keeps running in the other one)." _
  exit 0
fi
echo "Starting the Investment App with $PY …"
run_py -m app.web &
SERVER=$!
for i in $(seq 1 40); do
  if curl -s -o /dev/null http://127.0.0.1:8737/ 2>/dev/null; then break; fi
  sleep 0.5
done
open "http://127.0.0.1:8737/"
echo
echo "The app is open in your browser at http://127.0.0.1:8737/"
echo "Leave this window open while you use it. Close it to stop the app."
echo
if [ -n "$TSIP" ]; then
  echo "On your phone: install Tailscale, sign in to the SAME account as this Mac,"
  echo "switch it on, and open"
  echo
  echo "    http://$TSIP:8737/"
else
  echo "To use it on your phone as well: install Tailscale (https://tailscale.com/download)"
  echo "on this Mac and on the phone, sign in to the same account on both, then"
  echo "double-click this file again — it will print the address to open."
fi
wait $SERVER
