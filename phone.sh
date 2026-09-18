#!/bin/sh
# What to open on your phone.
#
#   ./phone.sh
#
# This exists because "reach it from your phone" was a paragraph of prose that
# named somebody else's machine, and there was no way to find out your own
# address without knowing where Tailscale had installed itself. It prints the
# URL and checks the three things that have to be true for it to work.
set -e
cd "$(dirname "$0")"
PORT=$(python3 -c "import json,pathlib;p=pathlib.Path('config.json');print((json.loads(p.read_text()).get('port') if p.exists() else None) or 8737)" 2>/dev/null || echo 8737)

TS=""
for cand in \
  "$(command -v tailscale 2>/dev/null)" \
  /usr/local/bin/tailscale \
  /opt/homebrew/bin/tailscale \
  /Applications/Tailscale.app/Contents/MacOS/Tailscale
do
  [ -n "$cand" ] && [ -x "$cand" ] && { TS="$cand"; break; }
done

if [ -z "$TS" ]; then
  echo "Tailscale is not installed on this Mac."
  echo
  echo "  1. Install it from https://tailscale.com/download"
  echo "  2. Sign in"
  echo "  3. Install Tailscale on your phone and sign in to the SAME account"
  echo "  4. Run ./install-agents.sh"
  echo "  5. Run ./phone.sh again"
  exit 1
fi

IP=$("$TS" ip -4 2>/dev/null | head -1 || true)
if [ -z "$IP" ]; then
  echo "Tailscale is installed but not signed in."
  echo
  echo "  1. Open Tailscale and sign in"
  echo "  2. Run ./install-agents.sh"
  echo "  3. Run ./phone.sh again"
  exit 1
fi

NAME=$("$TS" status --json 2>/dev/null \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" 2>/dev/null || true)

echo "Open this on your phone:"
echo
[ -n "$NAME" ] && echo "    http://$NAME:$PORT" || true
echo "    http://$IP:$PORT"
echo
# Being reachable needs the server bound to the tailnet address, not just to
# loopback. Checking is the difference between "here is a URL" and "here is a
# URL that works", and binding is exactly what people get wrong.
if nc -z "$IP" "$PORT" 2>/dev/null; then
  echo "  The server is listening on that address."
else
  echo "  WARNING: nothing is listening on $IP:$PORT."
  echo "  The server is probably bound to this Mac only. Run:"
  echo
  echo "      ./install-agents.sh"
  echo
  echo "  and then run ./phone.sh again."
fi
echo
echo "  Your phone must have Tailscale installed and signed in to the SAME"
echo "  account as this Mac, and the toggle switched on."
