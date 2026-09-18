#!/bin/sh
# Every suite, one command. Exits non-zero if any fail.
fail=0
# Drop compiled bytecode before running. Python validates its cache on the
# source's (mtime, size), which is almost always enough and silently is not when
# a file is rewritten within the same second at the same length — an edit of
# "in" to "==" is both. That happened here during mutation testing: the source
# read correct, git reported the tree clean, and the tests kept exercising the
# mutant. Recompiling costs a fraction of a second and removes the whole class.
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
# Every suite runs against the DEFAULT configuration, never the one on this
# machine. All three test audits hit the same failure: a result that depended on
# the developer's home directory — Alpaca credentials present or absent, and a
# synthetic tax fixture that broke the moment a real stub_employer was set. A
# test that passes or fails on config.json is not testing the code.
INVESTMENT_APP_CONFIG=/nonexistent/no-config.json
export INVESTMENT_APP_CONFIG
# Deleting a suite used to leave the runner reporting success over whatever
# remained. The count is asserted so a disappearing file is loud.
EXPECTED_SUITES=63
FOUND=$(ls -1 tests/test_*.py 2>/dev/null | wc -l | tr -d " ")
if [ "$FOUND" != "$EXPECTED_SUITES" ]; then
  echo "  expected $EXPECTED_SUITES suites, found $FOUND — update EXPECTED_SUITES if this is deliberate"
  fail=1
fi

for t in tests/test_*.py; do
  printf "%-34s " "$t"
  if out=$(python3 "$t" 2>&1); then rc=0; else rc=1; fail=1; fi
  line=$(echo "$out" | tail -1 | sed 's/^ *//')
  # A suite that prints no tally ran nothing. Silence is not a pass.
  # A count of zero is not a pass. The previous guard matched the word
  # "passed", so a suite reporting "0/0 passed" — which is what an empty or
  # crashed-out-early file prints — sailed through as green.
  # The tally must be complete, not merely present. Checking only the numerator
  # rendered "3/9 passed" green — a suite reporting six failures was shown as a
  # pass, which is the gate guarding every other check in this project.
  count=$(echo "$line" | sed -n 's|^\([0-9][0-9]*\)/[0-9][0-9]* passed$|\1|p')
  total=$(echo "$line" | sed -n 's|^[0-9][0-9]*/\([0-9][0-9]*\) passed$|\1|p')
  if [ -z "$count" ] || [ "$count" -eq 0 ]; then
    line="${line:-(no output)} -- NO TESTS RAN"; rc=1; fail=1
  elif [ "$count" != "$total" ]; then
    line="$line -- $((total - count)) FAILED"; rc=1; fail=1
  fi
  # A non-zero exit is a failure even when the tally looks complete.
  if [ "$rc" = 1 ] && [ "${line#*--}" = "$line" ]; then
    line="$line -- EXITED NON-ZERO"; fail=1
  fi
  echo "$line"
  [ "$rc" = 1 ] && echo "$out" | grep FAIL
done
# The Python suites can all pass while the page is blank — that has happened
# repeatedly here. The browser check is part of the run, not an optional extra.
printf "%-34s " "browser smoke"
if [ ! -d node_modules/playwright ]; then
  echo "SKIPPED -- playwright not installed (npm install -D playwright && npx playwright install chromium)"
  echo "  a green run above does NOT mean the page renders"
elif out=$(./smoke.sh 2>&1); then
  echo "$(echo "$out" | grep -E '^ *[0-9]+/[0-9]+ passed$' | tail -1 | sed 's/^ *//')"
else
  echo "$(echo "$out" | grep -E '^ *[0-9]+/[0-9]+ passed$' | tail -1 | sed 's/^ *//') -- FAILED"
  echo "$out" | grep FAIL
  fail=1
fi

# And once against an EMPTY ledger, which is what a fresh clone has. Every
# other test here runs against a database with transactions in it, so the first
# screen a new user sees was the one case nothing covered — and it was broken.
printf "%-34s " "empty ledger"
if [ ! -d node_modules/playwright ]; then
  echo "SKIPPED -- playwright not installed"
elif out=$(./empty.sh 2>&1); then
  echo "$(echo "$out" | grep -E '^ *[0-9]+/[0-9]+ passed$' | tail -1 | sed 's/^ *//')"
else
  echo "$(echo "$out" | grep -E '^ *[0-9]+/[0-9]+ passed$' | tail -1 | sed 's/^ *//') -- FAILED"
  echo "$out" | grep FAIL
  fail=1
fi

# A green run says nothing about the process on port 8737, which serves the
# code it started with. If one is listening, ask it whether the disk is newer.
if h=$(curl -s --max-time 2 http://127.0.0.1:8737/api/health 2>/dev/null) && [ -n "$h" ]; then
  case "$h" in *'"stale": true'*) printf "\n  ******** SERVER STALE: the process on :8737 is older than the source on disk — restart it ********\n";; esac
fi
if [ "$fail" = 0 ]; then printf "\nall suites passed\n"; else printf "\nFAILURES\n"; fi
exit $fail
