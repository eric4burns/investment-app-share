"""Nothing here may grow without being noticed.

The database reached 1.2 GB on 2026-09-04 with a seven-thousand-row ledger in
it, because every replayed call stored a sentence of evidence text nobody
read; the dashboard was one 6,000-line file; the improvement plan is a log
that only grows. None of that is wrong by itself, and all of it is the kind
of thing that is only ever noticed too late. So every budget below is a
number somebody has to raise on purpose, with the reason next to it.

Budgets are generous against today's sizes (the current figure is printed
beside each) so the suite stays green through ordinary work and goes red
when something has actually changed shape.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def lines(p: Path) -> int:
    try:
        return sum(1 for _ in p.open("rb"))
    except OSError:
        return 0


def kb(p: Path) -> float:
    return p.stat().st_size / 1024 if p.exists() else 0.0


def dir_mb(p: Path, skip=()) -> float:
    total = 0
    if not p.exists():
        return 0.0
    for dp, dn, fn in os.walk(p):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            try:
                total += (Path(dp) / f).stat().st_size
            except OSError:
                pass
    return total / 1e6


# ---- source files: lines -------------------------------------------------
# A module past this is two modules wearing one name. verdicts.py is the
# largest at ~1,950 and web.py ~1,800; the budget leaves room for a feature,
# not for a year. Raised 2400 -> 2700 on 2026-09-12: the request guards
# (write token, Origin, symbol validation, HTTP/1.1 send path) put web.py at
# ~2,450 — the Handler is the next thing to split out of it. Raised 2700 ->
# 2800 on 2026-09-13 for the X charts endpoint and image route (D127);
# web.py is at ~2,720 and the Handler split is still the next job.
PY_LINE_BUDGET = 2800
for p in sorted((ROOT / "app").glob("*.py")):
    n = lines(p)
    check(f"{p.name} stays under {PY_LINE_BUDGET} lines ({n})", n <= PY_LINE_BUDGET, n)

# The front end is dashboard.html (the stylesheet and the markup, ~1,440
# lines) plus nine script files under app/static, one per section and core,
# since 2026-09-13. Until then it was one 9,000-line file: the budget on it
# was raised five times in two days (7500 -> 7800 -> 8100 -> 8300 -> 8700 ->
# 9000) as the Phase 2 shell, the design system, the symbol page and the
# chart went in, and splitting the script out was "the next job" on each.
# Each file gets its own line, with a little headroom over today's size, so
# a section that doubles is noticed as that section; and the SUM keeps the
# old budget, so the whole cannot grow quietly across nine files where it
# used to be stopped in one.
FRONT_END = {
    "dashboard.html": 1600,   # 1,439: the stylesheet and the markup, no script but the init() call
    "static/core.js":  850,   # 703: helpers, the token wrapper, theme, settings, the router
    "static/money.js": 1650,  # 1,450: init/load, overview, holdings, trades, risk, sectors, net worth
    "static/today.js": 750,   # 594: the ranked list, alerts, attention, diagnose, mood, plans
    "static/stocks.js": 1150, # 1,000: calls, watchlist, setups, rebuy, discover, method scanner
    "static/follow.js": 400,  # 262: research artifacts, graded accounts, record, charts
    "static/bot.js":   650,   # 491: paper, scorecard, calibration, journal, replay, backtest
    "static/symbol.js": 850,  # 701: the symbol page
    "static/chart.js": 1800,  # 1,606: loadChart and everything chart
    "static/budget.js": 1050, # 917: budget, amazon, get started, category trends
}
front_total = 0
for rel, budget in FRONT_END.items():
    n = lines(ROOT / "app" / rel)
    front_total += n
    check(f"{rel} stays under {budget} lines ({n})", n <= budget, n)
# 9,000 was the one-file budget; the split added the script tags, a three-line
# header per file and nothing else. The room left is for a feature. Raised
# 9200 -> 9400 on 2026-09-13: the first-review items (D120–D124 — the New
# Stocks description rows, the who/when chart filters, the tax panel's
# investment rows, labelled fib levels) added ~105 lines of features.
check(f"the front end as a whole stays under 9400 lines ({front_total})", front_total <= 9400, front_total)
n = lines(ROOT / "app" / "static" / "drawings.js")
check(f"drawings.js stays under 1200 lines ({n})", n <= 1200, n)

# A test file past this is unreadable as a document of what the module must do.
for p in sorted((ROOT / "tests").glob("test_*.py")):
    n = lines(p)
    check(f"{p.name} stays under 1500 lines ({n})", n <= 1500, n)

# ---- documents: kilobytes --------------------------------------------------
# The numbered docs are read by people. 07_improvement_plan.md is a running
# log at ~45 KB; past 80 KB the older entries belong in research/audits.
for p in sorted(ROOT.glob("*.md")):
    k = kb(p)
    check(f"{p.name} stays under 80 KB ({k:.0f} KB)", k <= 80, f"{k:.0f} KB")
for p in sorted((ROOT / "research").glob("*.md")):
    k = kb(p)
    check(f"research/{p.name} stays under 120 KB ({k:.0f} KB)", k <= 120, f"{k:.0f} KB")

# ---- what git carries -------------------------------------------------------
# Nothing binary or bulky belongs in history: one 5 MB file committed by
# accident is there forever. 560 KB covered dashboard.html with room (it
# crossed 400 with the Get started screen, 2026-09-07, 450 with the Phase 2
# shell, 475 with its design system and 515 with the symbol page, all
# 2026-09-13); since the script split the same day the largest tracked file
# is the vendored chart library at ~350 KB, and the line stays where it was.
try:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True).stdout.decode().split("\0")
    big = [(t, kb(ROOT / t)) for t in tracked if t and kb(ROOT / t) > 560]
    check("no tracked file is over 560 KB", not big, big)
    # Replay and smoke logs under research/audits are audit records and are
    # tracked on purpose; anything else with these suffixes is a leak.
    leaks = [t for t in tracked if t.endswith((".db", ".log", ".csv", ".ofx", ".gz"))
             and not t.startswith(("app/", "research/audits/"))]
    check("no database, log or export is tracked outside research/audits", not leaks, leaks)
    # Third-party content pulled for research — video transcripts and the
    # Substack posts — is kept locally and must never enter history.
    content = [t for t in tracked if t.startswith(("research/transcripts/", "research/substack/"))]
    check("no transcript or Substack post is tracked", not content, content)
    check("the git objects stay under 200 MB",
          dir_mb(ROOT / ".git") <= 200, f"{dir_mb(ROOT / '.git'):.0f} MB")
except (subprocess.CalledProcessError, FileNotFoundError):
    check("git is available to inspect the tracked files", False)

# ---- the database ------------------------------------------------------------
# The ledger is a few megabytes of transactions and a couple of hundred of
# cached prices; the replayed calls and their millions of evidence rows live
# beside it in ledger-replay.db since the 2026-09-12 split (split_replay.py),
# and the discovery universe's bars are pruned to two years nightly
# (retention.py). 400 MB is the line past which something is being stored in
# the ledger that should not be — replay rows, or bars for names nobody
# holds or watches. The replay file is reproducible and capped separately.
# Skipped when there is no real ledger here — a fresh clone or the test
# runner's own config.
db = ROOT / "ledger.db"
replay_db = ROOT / "ledger-replay.db"
if db.exists() and db.stat().st_size > 100_000:
    mb = db.stat().st_size / 1e6
    # Until the split has been run the replay rows are still inside, and the
    # old 800 MB line is the honest one.
    cap = 400 if replay_db.exists() else 800
    check(f"ledger.db stays under {cap} MB ({mb:.0f} MB)", mb <= cap, f"{mb:.0f} MB")
    wal = ROOT / "ledger.db-wal"
    if wal.exists():
        wmb = wal.stat().st_size / 1e6
        check(f"the write-ahead log is checkpointed, under 200 MB ({wmb:.0f} MB)", wmb <= 200, f"{wmb:.0f} MB")
if replay_db.exists():
    rmb = replay_db.stat().st_size / 1e6
    check(f"ledger-replay.db stays under 600 MB ({rmb:.0f} MB)", rmb <= 600, f"{rmb:.0f} MB")

# ---- what accumulates on disk ---------------------------------------------------
check(f"logs/ stays under 50 MB ({dir_mb(ROOT / 'logs'):.1f} MB)", dir_mb(ROOT / "logs") <= 50)
check(f"research/audits stays under 10 MB ({dir_mb(ROOT / 'research' / 'audits'):.1f} MB)",
      dir_mb(ROOT / "research" / "audits") <= 10)
backups = Path.home() / "Backups" / "investment-app"
if backups.exists():
    check(f"backups stay under 2 GB ({dir_mb(backups):.0f} MB)", dir_mb(backups) <= 2000)
    stray = [p.name for p in backups.iterdir() if p.suffix in (".db-wal", ".db-shm", ".db")]
    check("the backup folder holds only compressed snapshots", not stray, stray)

# ---- duplicates ------------------------------------------------------------------
# Same bytes under two names, outside node_modules and git. Transcripts are
# excluded: a video that belongs to two channels is fetched under both, and
# that is the fetcher's business, not the repository's. So is vendor/, which
# holds third-party source built from scratch by research/video/setup.sh --
# its duplicates are upstream's and are not ours to clean up.
import hashlib
seen: dict[str, str] = {}
dups = []
for dp, dn, fn in os.walk(ROOT):
    dn[:] = [d for d in dn if d not in (".git", "node_modules", "__pycache__", "transcripts",
                                        ".claude", "vendor")]
    for f in fn:
        p = Path(dp) / f
        if p.suffix in (".pyc",) or p.name == ".DS_Store" or p.stat().st_size < 200:
            continue
        h = hashlib.md5(p.read_bytes()).hexdigest()
        if h in seen:
            dups.append((str(p.relative_to(ROOT)), seen[h]))
        else:
            seen[h] = str(p.relative_to(ROOT))
check("no two files in the project have the same contents", not dups, dups)
_ds = [str(p.relative_to(ROOT)) for p in ROOT.rglob(".DS_Store")
       if not str(p.relative_to(ROOT)).startswith(("node_modules/", ".git/"))]
check("no .DS_Store is left in the project", not _ds, _ds)

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
