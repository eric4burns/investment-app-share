#!/bin/sh
# Refresh everything the app can refresh on its own.
#
#   ./update.sh
#
# Safe to run any time and as often as you like: every importer is idempotent,
# and a cached price bar is never re-fetched. Re-running only ever adds what
# is new — except the retention step after the discovery scan, which prunes
# what nothing reads any more (app/retention.py says exactly what, and a dry
# run prints it: python3 -m app.retention).
set -e
cd "$(dirname "$0")"

echo "== importing anything new in data/ =="
python3 -m app.import_all

echo
echo "== refreshing prices (benchmarks + every held security) =="
python3 - <<'PY'
import sys; sys.path.insert(0, ".")
from app.ledger import connect
from app import prices
from datetime import date
conn = connect()
for b in ("SPY", "QQQ", "DJIA", "NASDAQ"):
    r = prices.sync_benchmark(conn, b)
    print(f"  {b:<8} {'ok' if r['ok'] else r.get('error')}")
# The trade-weighted dollar, for the exposure dial (app/regime.py). FRED,
# keyless, like the index levels above.
try:
    n = prices.store(conn, "DTWEXBGS", prices.fetch_fred("DTWEXBGS"), "fred")
    print(f"  DTWEXBGS dollar index: {n} new")
except Exception as exc:
    print(f"  DTWEXBGS dollar index: {type(exc).__name__}")
if prices.alpaca_credentials():
    r = prices.sync_holdings(conn, "2024-01-01", date.today().isoformat())
    print(f"  holdings:  priced {len(r['priced'])}, no feed {len(r['failed'])}")
    for s in r["failed"]:
        print(f"    no feed: {s}")
    # The watchlist too. It was never refreshed by anything, so the Outlook
    # tab's watchlist was scoring names on bars up to five days old.
    w = prices.sync_watchlist(conn, "2024-01-01", date.today().isoformat())
    print(f"  watchlist: priced {len(w['priced'])}, no feed {len(w['failed'])}"
          f" of {w['symbols']}")
else:
    print("  holdings: skipped (no data/.alpaca)")
conn.commit()
PY

echo
echo "== earnings calendar (next 100 days) =="
python3 -m app.earnings sync 2>&1 | tail -1

echo
echo "== insider filings (SEC Form 4) =="
python3 -m app.insiders sync 2>&1 | tail -1

echo
echo "== market fear and greed =="
python3 -c "
import sys; sys.path.insert(0, '.')
from app.ledger import connect
from app import sentiment
r = sentiment.sync(connect())
print(f\"  {r['score']} ({r['rating']}) on {r['as_of']}\" if r.get('ok') else f\"  unavailable: {r.get('error')}\")
"

echo
echo "== recording the trades in the ledger as decisions =="
# Every buy and sell is a decision made before the outcome was known, which is
# the same standard the app's own verdicts are held to. Idempotent.
python3 -c "
import sys; sys.path.insert(0, '.')
from app.ledger import connect
from app import journal
r = journal.derive_from_trades(connect())
print(f\"  {r['decisions']} decisions across {r['symbols']} symbols\")
"

echo
echo "== trades from Fidelity's confirmation emails (the morning after a fill) =="
# The email carries action and price, not shares; the trade goes in the journal
# today and the statement fills in the rest when it lands. Needs gmail in
# config.json; says so and moves on when it is not there.
python3 -m app.mailtrades 2>&1 | tail -4
python3 -m app.valuetrader 2>&1 | tail -3
# sectors for names the watchlist gained without one
python3 -c "
import sys; sys.path.insert(0, '.')
from app import ledger, sectors, watchlist
c = ledger.connect(); u = [r['symbol'] for r in watchlist.rows(c, __import__('datetime').date.today().isoformat()) if (r.get('sector') or 'Unknown') == 'Unknown']
r = sectors.classify(c, u) if u else {}; c.commit(); print('sectors:', len(u), 'unknown,', (r or {}).get('classified', 0), 'classified')
" 2>&1 | tail -1

echo
echo "== outlook: score every holding and record what changed =="
# After the price refresh, because a verdict computed on yesterday's bars would
# be recorded under today's date and then graded from the wrong entry price.
python3 -m app.outlook --warm-watchlist

echo
echo "== paper trading: the weekly engine's calls, on the Alpaca paper account =="
python3 -m app.paper run 2>&1 | tail -6

echo
echo "== discovery: the methods across the whole liquid market =="
python3 -m app.discover scan 2>&1 | tail -4

echo
echo "== retention: pruning what nothing reads any more =="
# After the scan, because the scan is what adds two thousand names' bars.
# Bars older than two years for names only the screen knows, old hits and
# alerts, stale intraday bars. Never held, watched, graded or coded names.
# A failure here must not cost the alerts that follow.
python3 -m app.retention --apply || echo "  retention failed; see above"

echo
echo "== alerts: what changed, what is at a level, what reports soon =="
python3 -m app.alerts nightly

echo
echo "== current performance =="
python3 -m app.report

# Compact the database when it has room to give back — but only when the
# dashboard is NOT up. VACUUM rewrites the whole file under an exclusive
# lock, and on a 759 MB ledger that was well past the server's 30-second
# busy timeout: every request errored for the duration, every night the
# replay had been redone. With the replay in its own file (app/split_replay.py)
# and retention pruning nightly there is much less to give back anyway, so
# skipping is the normal case. The freed pages are reused by tomorrow's
# writes; the file simply does not shrink until a night the server is down,
# or until `python3 -m app.split_replay --vacuum` rebuilds it beside itself.
PREFIX=$(python3 -c "import json,pathlib;p=pathlib.Path('config.json');print((json.loads(p.read_text()).get('label_prefix') if p.exists() else None) or 'investment-app')" 2>/dev/null || echo investment-app)
if launchctl list "com.$USER.$PREFIX.serve" >/dev/null 2>&1; then
  echo "  compaction skipped: the dashboard agent com.$USER.$PREFIX.serve is loaded" \
       "(VACUUM would lock it out; python3 -m app.split_replay --vacuum does it safely)"
elif pgrep -f "app\.web" >/dev/null 2>&1; then
  echo "  compaction skipped: a dashboard process (app.web) is running"
else
python3 - <<'PY'
import sqlite3, os
c = sqlite3.connect("ledger.db", timeout=120)
c.execute("PRAGMA busy_timeout=120000")
c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
free = c.execute("PRAGMA freelist_count").fetchone()[0] * c.execute("PRAGMA page_size").fetchone()[0]
if free > 100_000_000:
    before = os.path.getsize("ledger.db")
    c.execute("VACUUM")
    print(f"  compacted: {before/1e6:,.0f} MB -> {os.path.getsize('ledger.db')/1e6:,.0f} MB")
else:
    print(f"  database {os.path.getsize('ledger.db')/1e6:,.0f} MB, {free/1e6:,.0f} MB free — no compaction needed")
c.close()
PY
fi

# Keep the logs from growing without bound: serve.log gains a traceback per
# broken pipe and poll.log a line every fifteen minutes. Anything over 1 MB
# is cut back to its last 200 KB, in place — launchd holds these files open
# in append mode, so truncating through the same path is what keeps the
# writer's next line landing at the new end rather than in a fresh file it
# is not looking at.
for f in logs/*.log; do
  [ -f "$f" ] || continue
  if [ "$(wc -c < "$f" | tr -d ' ')" -gt 1048576 ]; then
    tail -c 204800 "$f" > "$f.rotating" && cat "$f.rotating" > "$f" && rm -f "$f.rotating"
    echo "  rotated $f"
  fi
done

echo
echo "Done. Dashboard: python3 -m app.web  ->  http://localhost:8737"
