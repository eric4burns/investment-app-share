#!/bin/sh
# Cut a fresh archive to give somebody, from a single clean commit.
#
#   ./share.sh                 -> ~/Desktop/investment-app.zip
#   ./share.sh /some/where.zip
#
# Two things this exists to get right, both of which were got wrong by hand.
#
# HISTORY. `master` carries the real development history, and dozens of those
# commit messages quote real account balances inside explanatory prose. The
# shared branch is therefore a SINGLE orphan commit holding the current tree and
# no history at all — recreated from scratch each time rather than added to.
#
# SECRETS. Everything private is gitignored (data/, ledger.db, config.json,
# logs/), so archiving from git rather than zipping the folder is what keeps
# them out. Zipping the working directory would have swept up the ledger, the
# statements and the Alpaca key. The check below is belt and braces.
set -e
cd "$(dirname "$0")"
OUT=${1:-$HOME/Desktop/investment-app.zip}

# --dry-run: build the archive to a temp file, run the private-file check, and
# delete it — a way to know the refusal list is right without cutting a real
# archive or needing a clean tree.
DRY=
if [ "$1" = "--dry-run" ]; then
  DRY=1; OUT=$(mktemp -t investment-app-dry).zip; rm -f "$OUT"
fi

if [ -z "$DRY" ] && { ! git diff --quiet || ! git diff --cached --quiet; }; then
  echo "  uncommitted changes — commit them first, or they will not be in the archive" >&2
  exit 1
fi

# A fresh orphan commit holding master's tree, minus the private paths. Those
# stay tracked on master — research/audits/ is the working record the docs
# cite — but a friend's copy has no use for this ledger's round trips, so they
# are dropped from a temporary index before the tree is written. No checkout,
# no parent, so the development history cannot travel with it.
PRIVATE="research/audits research/video research/x/notes"
PRIVATE="$PRIVATE $(git ls-files 'research/seed-*' 'research/*.pdf' 'research/**/*.pdf' | tr '\n' ' ')"
export GIT_INDEX_FILE=$(mktemp)
git read-tree master
git rm -r -q --cached --ignore-unmatch $PRIVATE >/dev/null
# The page a friend lands on is the getting-started guide, not the file map
# the developer reads: on GitHub the root README.md is the landing page, so
# in the shared tree the guide IS README.md and the developer's README moves
# to README-DEVELOPERS.md. GETTING-STARTED.md stays too, under its own name.
git update-index --add --cacheinfo "100644,$(git rev-parse master:README.md),README-DEVELOPERS.md"
git update-index --add --cacheinfo "100644,$(git rev-parse master:GETTING-STARTED.md),README.md"
TREE=$(git write-tree)
rm -f "$GIT_INDEX_FILE"; unset GIT_INDEX_FILE
COMMIT=$(git commit-tree "$TREE" -m "Investment App — a local, single-user portfolio and budget dashboard")
# The dry run archives the loose commit and leaves the share branch alone.
[ -n "$DRY" ] || git branch -f share "$COMMIT"

git archive --format=zip --prefix=investment-app/ "$COMMIT" -o "$OUT"

# Refuse to hand over an archive containing anything private, whatever the
# .gitignore happens to say today. research/audits/ is the working record of
# this ledger (real round trips, net worth, income); the seed-* scripts, the
# video notes and the PDF carry the owner's own calls and holdings. Two files
# under research/x/ are configuration, tracked on purpose, and are let through
# — the old bare "/x/" matched them and this script could never succeed.
BAD=$(unzip -l "$OUT" | grep -iE "ledger\.db|/data/|config\.json|\.alpaca|/logs/|\.pages|/substack/|/transcripts/|/x/|research/audits/|research/seed-|research/video/|research/[^ ]*\.pdf" \
      | grep -vE "research/x/(SETUP\.md|accounts\.txt)?$" || true)
if [ -n "$BAD" ]; then
  rm -f "$OUT"
  echo "  ARCHIVE CONTAINED PRIVATE FILES — deleted. Check .gitignore:" >&2
  echo "$BAD" >&2
  exit 1
fi

# A link beats a file: Gmail refuses any zip that contains a .js or a .bat,
# and this one holds thirteen, so an emailed archive may never arrive. When
# a remote named `share` exists (a PUBLIC repo holding nothing but this
# branch), the same clean commit is pushed there and the download URL is
# printed — the friend gets a link, and the zip on the Desktop is for
# AirDrop.
if [ -z "$DRY" ] && git remote get-url share >/dev/null 2>&1; then
  if git push -q -f share share:main 2>/dev/null; then
    URL=$(git remote get-url share | sed -E 's#(\.git)?$##; s#^git@github\.com:#https://github.com/#')
    echo "  pushed to $URL — send: $URL/archive/refs/heads/main.zip"
  else
    echo "  (the push to the share remote failed; the zip below is still good)" >&2
  fi
fi

if [ -n "$DRY" ]; then
  rm -f "$OUT"
  echo "  dry run: the archive would contain no private files"
  exit 0
fi
echo "  wrote $OUT"
echo "  $(unzip -l "$OUT" | tail -1 | awk '{print $2}') files, from a single commit with no history"
echo "  contains no ledger, no statements, no config, no keys"
