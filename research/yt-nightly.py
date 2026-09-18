"""The nightly YouTube pull: new videos from the followed channels, into the ledger.

Run by launchd (see launchd/ytpull.plist). Safe to run by hand at any time —
a video already on disk is skipped, and storing mentions is idempotent on the
video id.

    python3 research/yt-nightly.py               # the usual nightly sweep
    python3 research/yt-nightly.py --limit 20    # look further back per channel
    python3 research/yt-nightly.py --dry-run     # fetch nothing, count what is stored

Video says what a post cannot: which levels, on what timeframe, what would
invalidate the idea. The X pull answers "who is talking about this name"; this
answers the same question for long-form, and the two share the `x_mentions`
table and the same handles, so a person on both platforms counts once.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from app import authors, ledger, ytpull  # noqa: E402

TRANSCRIPTS = ROOT / "research" / "transcripts"


def store_mentions(conn: sqlite3.Connection, verbose: bool = True) -> int:
    """Read every transcript on disk and count the names in it."""
    alias = ytpull.aliases(conn, ytpull.asset_names())
    rows, seen = [], 0
    for meta_path in sorted(TRANSCRIPTS.rglob("*.json")):
        text_path = meta_path.with_suffix(".txt")
        if not text_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except ValueError:
            continue
        handle = meta_path.parent.name
        blob = (meta.get("title") or "") + " " + text_path.read_text()
        syms = ytpull.symbols_in(blob, alias)
        seen += 1
        rows += ytpull.rows_for(meta, syms, handle)
    n = authors.store_mentions(conn, rows)
    if verbose:
        print(f"  {seen} transcripts, {len(rows)} mentions of "
              f"{len({r['symbol'] for r in rows})} symbols, {n} new")
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=6,
                    help="videos to check per channel (default %(default)s)")
    ap.add_argument("--only", help="one channel handle")
    ap.add_argument("--dry-run", action="store_true",
                    help="skip fetching; just re-count what is already on disk")
    args = ap.parse_args(argv)

    conn = ledger.connect()
    if not args.dry_run:
        import fetch_transcripts
        targets = ({args.only: ytpull.CHANNELS[args.only]} if args.only in ytpull.CHANNELS
                   else ytpull.CHANNELS)
        for name, url in targets.items():
            try:
                fetch_transcripts.fetch(name, url, args.limit)
            except Exception as exc:                          # noqa: BLE001
                # One channel going wrong must not cost the others their night.
                print(f"  {name}: FAILED — {type(exc).__name__}: {str(exc)[:80]}")

    store_mentions(conn)
    report = ytpull.alias_report(conn)
    # Said every run, because a name that cannot be matched looks exactly like
    # a name nobody mentioned, and the two are not the same thing.
    print(f"  {report['covered']} of {report['tracked']} tracked symbols can be "
          f"matched by name at all; the rest only via a cashtag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
