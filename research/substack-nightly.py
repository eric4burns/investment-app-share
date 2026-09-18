"""The nightly Substack pull: new posts to disk, then the readers that feed the app.

Run by launchd (see launchd/subpull.plist) at 03:30, between the X pull and
the YouTube one. Safe to run by hand any time; a post already on disk is not
fetched again, and every step after the fetch is idempotent.

    python3 research/substack-nightly.py
    python3 research/substack-nightly.py --dry-run

After the fetch, in order: the priced calls into the journal
(seed-stonkchris-calls.py), and the zones and targets into author_levels
(seed-author-levels.py). The charts need no step — substack_charts.py reads
the .txt files as they are.
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import subpull  # noqa: E402

AFTER = ["research/seed-stonkchris-calls.py", "research/seed-author-levels.py"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    print(f"{datetime.now():%Y-%m-%d %H:%M} — Substack pull", flush=True)
    try:
        r = subpull.pull(dry_run=args.dry_run, log=lambda m: print(m, flush=True))
    except subpull.SubPullError as e:
        # A dead session is the one failure the user has to act on: said
        # plainly, so the log reads as an instruction rather than a traceback.
        print(f"STOPPED: {e}")
        return 2
    for e in r["errors"]:
        print(f"  ! {e}")
    if args.dry_run or not r["written"]:
        print("nothing new" if not r["written"] else "dry run")
        return 0
    print(f"{len(r['written'])} new post(s)")
    for script in AFTER:
        c = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, capture_output=True, text=True)
        tail = (c.stdout.strip() or c.stderr.strip()).splitlines()[-1:] or [""]
        print(f"  {Path(script).name}: {tail[0]}" + ("" if c.returncode == 0 else f" (exit {c.returncode})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
