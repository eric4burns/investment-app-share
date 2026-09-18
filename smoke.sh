#!/bin/sh
# Browser smoke test: does the app work when a real browser opens it?
#
# Starts its own server on port 8738 so a dashboard you have open on 8737 is
# untouched, against a THROWAWAY COPY of the database. The copy is not caution
# for its own sake: the test places and deletes drawings, and the real ledger is
# thousands of imported brokerage transactions with no other source.
set -e
cd "$(dirname "$0")"
[ -d node_modules/playwright ] || {
  echo "  playwright is not installed. Run: npm install -D playwright && npx playwright install chromium" >&2
  exit 1; }

DB=$(mktemp -t smoke-ledger).db
trap 'rm -f "$DB" "$DB"-wal "$DB"-shm' EXIT
# sqlite's own backup, not cp: the database runs in WAL mode, so a plain copy of
# the .db file alone can miss everything still sitting in the write-ahead log.
python3 -c "
import sqlite3, sys
src = sqlite3.connect('ledger.db'); dst = sqlite3.connect(sys.argv[1])
src.backup(dst); dst.close(); src.close()
" "$DB"

INVESTMENT_APP_PORT=8738 INVESTMENT_APP_DB="$DB" python3 -c "
import sys; sys.path.insert(0, '.')
from app import web
from http.server import ThreadingHTTPServer
ThreadingHTTPServer(('127.0.0.1', 8738), web.Handler).serve_forever()
" &
SERVER=$!
trap '[ -n "$SERVER" ] && kill $SERVER 2>/dev/null; rm -f "$DB" "$DB"-wal "$DB"-shm' EXIT

for i in $(seq 1 40); do
  curl -s -o /dev/null "http://127.0.0.1:8738/" && break
  sleep 0.25
done

set +e
# Warm the two outlook payloads first. The server is one Python process, so a
# cold watchlist-scope outlook started by an early tab check queues every
# later request behind it — the backtest run then never finishes inside its
# wait, and the failure reads as a broken button. This used to be the bulk
# of the run (176 names computed from scratch, ~170 s of a 180 s test); the
# copy carries the ledger's verdict_cache now, so both answer in about a
# second, and the warm is kept as cheap insurance. Its time is printed so a
# cache that has gone cold shows up here rather than as a slow, flaky tour.
t0=$(date +%s)
curl -s -m 900 -o /dev/null "http://127.0.0.1:8738/api/outlook"
curl -s -m 900 -o /dev/null "http://127.0.0.1:8738/api/outlook?scope=watchlist"
echo "  warmed the outlook payloads in $(( $(date +%s) - t0 )) s"
SMOKE_URL=http://127.0.0.1:8738 node tests/smoke.mjs
rc=$?
# Reap the server quietly. Left to the EXIT trap, the shell prints its own
# "Terminated" notice AFTER the tally, and anything reading the last line of
# this script for a result reads that instead.
kill $SERVER 2>/dev/null
wait $SERVER 2>/dev/null
SERVER=
exit $rc
