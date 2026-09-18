#!/bin/bash
# Store the Substack session the nightly pull needs, without the cookie ever
# appearing on a command line.
#
#   ./substack-setup.sh          store the session, then test it
#   ./substack-setup.sh --check  test the session already stored
#
# One value, read with `read -rs`: nothing is echoed and nothing enters shell
# history. The file is recreated under umask 077, private from the start.
set -u
cd "$(dirname "$0")"
ROOT=$(pwd)
SESSION=${SUBSTACK_SESSION_FILE:-$ROOT/data/.substack}

if [ "${1:-}" != "--check" ]; then
  echo "One value from Chrome: DevTools > Application > Cookies > https://<publication>.substack.com"
  echo "Click the row named substack.sid and copy its Cookie Value."
  echo "Nothing appears as you paste. That is deliberate, not a hang."
  echo
  printf 'substack.sid, then Return: '
  IFS= read -rs SID; echo
  SID=${SID#substack.sid=}
  SID=$(printf '%s' "$SID" | tr -d '[:space:]')
  if [ ${#SID} -lt 40 ]; then
    echo "  that is ${#SID} characters; the cookie is a long token (usually 200+). Not saved." >&2
    exit 1
  fi
  mkdir -p "$ROOT/data"
  rm -f "$SESSION"
  ( umask 077; printf '# substack.sid — the logged-in Substack session. Private; never committed.\n%s\n' "$SID" > "$SESSION" )
  echo "  saved to ${SESSION#$ROOT/}"
fi

echo "Testing the session against the newest paid post…"
python3 -m app.subpull --dry-run --limit 3 || exit $?
python3 - <<'PY'
import json, sys
from app import subpull
sid = subpull.session()
for author, host in subpull.publications():
    for p in subpull.archive(host, sid, 6):
        if p.get("audience") in ("only_paid", "founding"):
            body = subpull.post(host, p["slug"], sid).get("body_html") or ""
            ok = len(body) >= subpull.TEASER
            print(f"  {author}: {p['slug']} came back {'whole' if ok else 'as the teaser'} ({len(body):,} chars)")
            sys.exit(0 if ok else 2)
print("  no paid post in the archive to test against")
PY
