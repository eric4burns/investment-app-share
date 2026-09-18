#!/bin/sh
# Snapshot the ledger somewhere the app is not writing to.
#
#   ./backup.sh                 # into ~/Backups/investment-app
#   ./backup.sh /some/where     # elsewhere
#
# Runs nightly at 19:30 from launchd (launchd/backup.plist), after update.sh
# has finished at 18:30. Two files each night:
#
#   ledger-<stamp>.db.gz    the whole ledger, gzip -1 (fast; a database of
#                           price bars compresses about 3:1 whatever level)
#   curated-<stamp>.db.gz   only what cannot be rebuilt — the watchlist and
#                           its tags, the sector classifications, the live
#                           journal (never the replay), the drawings, plans,
#                           books, basis, categories, rules and the imported
#                           transactions. A few megabytes. If the full
#                           snapshots are ever too big to keep, these are the
#                           ones that matter; everything else is a fetch.
#
# Kept: the newest 7 full snapshots plus the first of each month for six
# months; curated snapshots for 90 days. ~/Backups is not under iCloud (the
# Desktop and Documents folders are), so a snapshot here is not also being
# uploaded and is not what gets pruned when iCloud runs short.
#
# `cp ledger.db` is NOT a backup: the schema runs in WAL mode, so a naive copy
# taken while the server is running can catch the database mid-transaction.
# sqlite3's .backup takes a consistent snapshot of a live database.
#
# ledger-replay.db is NOT backed up. It holds the replayed calls, which
# `python3 -m app.replay run` rebuilds from the price cache in under an hour.
set -e

# Resolve to the script's own directory FIRST. The previous version used the
# relative path "ledger.db" and never cd'd, so run from anywhere else sqlite3
# created an empty database in the current directory, backed THAT up, printed
# the success line, exited 0, and applied retention — fourteen such runs would
# have deleted every real backup. A backup script that destroys backups is
# worse than no backup script.
cd "$(dirname "$0")"

# INVESTMENT_APP_DB is the same override app/ledger.py honours, so a test can
# point this at a copy; unset, it is the real ledger beside this script.
SRC="${INVESTMENT_APP_DB:-$PWD/ledger.db}"
DEST="${1:-$HOME/Backups/investment-app}"
KEEP_NIGHTLY=7
KEEP_MONTHS=6
KEEP_CURATED_DAYS=90

# Refuse rather than invent. An absent or implausibly small source means
# something is wrong with the invocation, not that the ledger is empty.
[ -f "$SRC" ] || { echo "  no ledger at $SRC — refusing to back up nothing" >&2; exit 1; }
SRC_BYTES=$(wc -c < "$SRC" | tr -d ' ')
[ "$SRC_BYTES" -gt 100000 ] || {
  echo "  $SRC is only $SRC_BYTES bytes — refusing, this is not the real ledger" >&2
  exit 1; }

mkdir -p "$DEST"
chmod 700 "$DEST"
STAMP=$(date +%Y-%m-%d-%H%M)
SNAP="$DEST/ledger-$STAMP.db"
CUR="$DEST/curated-$STAMP.db"

sqlite3 "$SRC" ".backup '$SNAP'"

# Verify BEFORE rotating anything away. A snapshot is only a backup once it has
# been shown to open, pass an integrity check, and contain the tables whose loss
# would be unrecoverable.
sqlite3 "$SNAP" "PRAGMA integrity_check;" | grep -qx ok || {
  echo "  integrity check FAILED — keeping older backups, removing this one" >&2
  rm -f "$SNAP" "$SNAP-wal" "$SNAP-shm"; exit 1; }
ROWS=$(sqlite3 "$SNAP" "SELECT (SELECT count(*) FROM watchlist) + (SELECT count(*) FROM transactions);")
[ "$ROWS" -gt 0 ] || {
  echo "  snapshot has no watchlist or transaction rows — refusing to rotate" >&2
  rm -f "$SNAP" "$SNAP-wal" "$SNAP-shm"; exit 1; }

# The curated copy is built from the snapshot just taken, not from the live
# file: same consistent view, and no lock on the database the server is
# using. Tables are copied whole except the two the replay shares, which
# keep only the hand-made and live rows; the tables listed as EXCLUDE are
# caches of a feed and come back with ./update.sh.
CUR_ROWS=$(python3 - "$SNAP" "$CUR" <<'PY'
import re, sqlite3, sys
snap, cur = sys.argv[1], sys.argv[2]
EXCLUDE = {"prices", "intraday_bars", "price_fetches", "insider_trades", "insider_fetches",
           "earnings_dates", "earnings_fetches", "discover_universe", "discover_universe_log",
           "discover_hits", "accumulation_hits", "backtest_runs", "replay_reports"}
KEEP_WHERE = {"decisions": "WHERE source NOT LIKE 'replay%'",
              "decision_evidence": "WHERE decision_id IN (SELECT id FROM main.decisions "
                                   "WHERE source NOT LIKE 'replay%')"}
tmp = cur + ".tmp"
src = sqlite3.connect(snap)
src.execute("ATTACH DATABASE ? AS cur", (tmp,))
tables = [(n, s) for n, s in src.execute(
    "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")
    if n not in EXCLUDE]
for name, sql in tables:
    src.execute(re.sub(r"^\s*CREATE TABLE\s+", "CREATE TABLE cur.", sql, count=1))
    src.execute(f'INSERT INTO cur."{name}" SELECT * FROM main."{name}" {KEEP_WHERE.get(name, "")}')
for sql, tbl in src.execute("SELECT sql, tbl_name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
    if tbl not in EXCLUDE:
        src.execute(re.sub(r"^\s*CREATE (UNIQUE )?INDEX\s+", lambda m: f"CREATE {m.group(1) or ''}INDEX cur.", sql, count=1))
src.commit()
src.execute("DETACH DATABASE cur")
src.close()
# VACUUM INTO writes the compact single-file form and leaves the build file
# untouched, so a failure here leaves nothing half-written under the final name.
c = sqlite3.connect(tmp)
c.execute("VACUUM INTO ?", (cur,))
c.close()
import os; os.unlink(tmp)
c = sqlite3.connect(cur)
ok = c.execute("PRAGMA integrity_check").fetchone()[0]
n = c.execute("SELECT (SELECT count(*) FROM watchlist) + (SELECT count(*) FROM transactions)").fetchone()[0]
d = c.execute("SELECT count(*) FROM decisions WHERE source LIKE 'replay%'").fetchone()[0]
c.close()
if ok != "ok" or d:
    sys.exit(f"curated copy failed: integrity {ok}, {d} replay rows")
print(f"{n} {len(tables)}")
PY
) || { echo "  curated copy FAILED — removing it, keeping the full snapshot" >&2
       rm -f "$CUR" "$CUR.tmp"; CUR=""; }

# `.backup` of a WAL-mode source leaves an empty -wal and a -shm beside the
# snapshot, and thirty of them had piled up unnoticed. They are not part of
# the backup; the gzipped file is.
rm -f "$SNAP-wal" "$SNAP-shm" "$CUR-wal" "$CUR-shm"
# -1: the file is mostly price bars and evidence rows that gzip finds no
# harder at -6; the default took four times as long for a few percent.
gzip -1 -f "$SNAP"
chmod 600 "$SNAP.gz"
if [ -n "$CUR" ]; then
  gzip -f "$CUR"
  chmod 600 "$CUR.gz"
fi

# Only now, with a verified snapshot on disk, retire the old ones.
#
# Full snapshots: the newest KEEP_NIGHTLY, plus the FIRST one taken in each
# of the last KEEP_MONTHS months — "first taken", not "taken on the 1st", so
# a laptop asleep on the 1st still leaves a monthly. The stamp in the name
# sorts as a date, so `sort -r` is newest first.
CUTOFF_MONTH=$(date -v-${KEEP_MONTHS}m +%Y-%m 2>/dev/null || date -d "$KEEP_MONTHS months ago" +%Y-%m)
i=0
ls -1 "$DEST"/ledger-*.db.gz 2>/dev/null | sort -r | while read -r old; do
  i=$((i + 1))
  if [ "$i" -le "$KEEP_NIGHTLY" ]; then continue; fi
  base=$(basename "$old")
  month=$(echo "$base" | sed 's/^ledger-\([0-9]\{4\}-[0-9]\{2\}\)-.*/\1/')
  first=$(ls -1 "$DEST"/ledger-"$month"-*.db.gz | sort | head -1)
  if [ "$old" = "$first" ] && [ "$month" \> "$CUTOFF_MONTH" -o "$month" = "$CUTOFF_MONTH" ]; then
    continue
  fi
  rm -f "$old"
done
# Curated: everything older than KEEP_CURATED_DAYS, by the stamp in the name.
CUTOFF_DAY=$(date -v-${KEEP_CURATED_DAYS}d +%Y-%m-%d 2>/dev/null || date -d "$KEEP_CURATED_DAYS days ago" +%Y-%m-%d)
ls -1 "$DEST"/curated-*.db.gz 2>/dev/null | while read -r old; do
  day=$(basename "$old" | sed 's/^curated-\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}\)-.*/\1/')
  # if/then, not `test && rm`: under set -e a false test as the loop's last
  # command is a non-zero pipeline, and the script died here before its
  # summary line.
  if [ "$day" \< "$CUTOFF_DAY" ]; then rm -f "$old"; fi
done

echo "  backed up $ROWS rows to $SNAP.gz ($(du -h "$SNAP.gz" | cut -f1))"
if [ -n "$CUR" ]; then
  echo "  curated: ${CUR_ROWS% *} watchlist+transaction rows, ${CUR_ROWS#* } tables, $(du -h "$CUR.gz" | cut -f1) -> $CUR.gz"
fi
ls -1t "$DEST"/ledger-*.db.gz | head -3 | sed 's/^/    /'
