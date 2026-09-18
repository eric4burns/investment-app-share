#!/bin/sh
# Does the app work for somebody who has just cloned it?
#
# Starts a server on port 8739 against an EMPTY ledger — schema only, not one
# transaction — and opens it in a browser.
#
# This exists because every other test here runs against a database with data
# in it, and the first screen a new user sees is the one case none of them
# covered. A fresh clone used to throw RangeError inside init() (bounds.first is
# null with no transactions, and new Date("nullT00:00:00").toISOString() raises),
# which aborted startup and left the page on "Loading your portfolio" forever.
# Green suites, and the app was unusable for anybody who was not already using it.
set -e
cd "$(dirname "$0")"
[ -d node_modules/playwright ] || {
  echo "  playwright is not installed. Run: npm install -D playwright && npx playwright install chromium" >&2
  exit 1; }

DB=$(mktemp -t empty-ledger).db
rm -f "$DB"
trap 'rm -f "$DB" "$DB"-wal "$DB"-shm' EXIT
# connect() applies schema.sql, so this is a real ledger with nothing in it.
INVESTMENT_APP_DB="$DB" python3 -c "
import sys; sys.path.insert(0, '.')
from app.ledger import connect
connect().close()
"

INVESTMENT_APP_PORT=8739 INVESTMENT_APP_DB="$DB" python3 -c "
import sys; sys.path.insert(0, '.')
from app import web
from http.server import ThreadingHTTPServer
ThreadingHTTPServer(('127.0.0.1', 8739), web.Handler).serve_forever()
" &
SERVER=$!
trap '[ -n "$SERVER" ] && kill $SERVER 2>/dev/null; rm -f "$DB" "$DB"-wal "$DB"-shm' EXIT

for i in $(seq 1 40); do
  curl -s -o /dev/null "http://127.0.0.1:8739/" && break
  sleep 0.25
done

set +e
SMOKE_URL=http://127.0.0.1:8739 node tests/empty.mjs
rc=$?
kill $SERVER 2>/dev/null
wait $SERVER 2>/dev/null
SERVER=
exit $rc
