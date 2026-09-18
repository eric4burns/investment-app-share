"""The nightly X pull: new posts from the followed accounts, into the ledger.

Run by launchd (see launchd/xpull.plist). Safe to run by hand at any time:
it continues from where the last pull stopped, and storing is idempotent on
the tweet id, so nothing is double-counted.

    python3 research/x-nightly.py              # continue from the last pull
    python3 research/x-nightly.py --days 14    # override the window
    python3 research/x-nightly.py --dry-run    # pull, show, write nothing

Why this exists: the mention history was three days long, because the pull was
a manual paste into a browser console once a week. A crowd reading needs
months of history before "early" means anything other than "no data", and the
only way to get months is to stop asking a person to remember.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import xpull  # noqa: E402

ACCOUNTS = ROOT / "research" / "x" / "accounts.txt"


def accounts() -> list[str]:
    if not ACCOUNTS.exists():
        return []
    return [l.strip().lstrip("@") for l in ACCOUNTS.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, help="look back this many days instead of "
                                             "continuing from the last pull")
    ap.add_argument("--gap", type=int, default=xpull.GAP,
                    help="seconds between accounts (default %(default)s)")
    ap.add_argument("--only", help="comma-separated handles, for testing")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    handles = [h.strip() for h in args.only.split(",")] if args.only else accounts()
    if not handles:
        print(f"no accounts listed in {ACCOUNTS.relative_to(ROOT)}")
        return 1

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)) if args.days else None
    started = datetime.now(timezone.utc)
    xpull.PULL_DIR.mkdir(parents=True, exist_ok=True)
    out = xpull.PULL_DIR / f"{started:%Y-%m-%d}.json"

    # Pick up a run that was interrupted earlier today rather than paying for
    # those accounts twice. An hour of requests is not cheap against a limit
    # that allows about twenty an hour.
    done = None
    if out.exists() and not args.dry_run:
        try:
            prev = json.loads(out.read_text())
            if prev.get("partial"):
                done = prev.get("tweets") or {}
                since = since or datetime.fromisoformat(prev["since"])
        except (ValueError, KeyError):
            done = None

    def save(partial):
        out.write_text(json.dumps(partial, indent=1))

    print(f"{started:%Y-%m-%d %H:%M} — pulling {len(handles)} accounts", flush=True)
    try:
        data = xpull.pull(handles, since=since, gap=args.gap,
                          log=lambda m: print(m, flush=True),
                          checkpoint=None if args.dry_run else save, done=done)
    except xpull.XPullError as e:
        # A dead session is the one failure the user has to act on, so it is
        # said plainly rather than left as a traceback in a log nobody reads.
        print(f"STOPPED: {e}")
        return 2

    posts = sum(len(v) for v in data["tweets"].values())
    print(f"{posts} posts from {len(data['tweets'])} accounts since {data['since'][:10]}"
          + (f", {len(data['errors'])} errors" if data["errors"] else ""))
    for e in data["errors"]:
        print(f"  ! {e}")
    if args.dry_run:
        return 0

    save(data)
    print(f"wrote {out.relative_to(ROOT)}")

    # The mention counting already exists and is tested; run it rather than
    # reimplement it here.
    r = subprocess.run([sys.executable, str(ROOT / "research" / "x-mentions.py"), str(out)],
                       cwd=ROOT, capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    # The calls in tonight's posts go into the journal tonight, so the record
    # of what each account said is the app's from then on, whatever happens
    # to the post (app/xcalls.py).
    for mod in ("app.xcalls", "app.xcharts"):
        c = subprocess.run([sys.executable, "-m", mod, str(out)],
                           cwd=ROOT, capture_output=True, text=True)
        print((c.stdout.strip() or c.stderr.strip()).splitlines()[-1] if (c.stdout or c.stderr) else "")
    return 0 if r.returncode == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
