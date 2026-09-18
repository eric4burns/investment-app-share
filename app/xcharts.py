"""The charts the followed accounts post on X, saved by account the night they appear.

    python3 -m app.xcharts                          # every pull on disk
    python3 -m app.xcharts research/x/pulls/2026-09-14.json

The X pull keeps each post's photo URLs (xpull.posts_for). This downloads
them to research/x/images/<handle>/<tweet_id>-<n>.jpg and records each one
in `x_charts` with the day, the account, the cashtags in the post and its
words, so Who I Follow → Their charts can show them beside the Substack and
Patreon charts, filter by account, and put two people's charts of the same
name side by side. The file is ours from that night: a post deleted later
changes nothing here, the same rule as the calls (xcalls.py).

Nothing is read off the image. The chart's name comes from the cashtags in
the post; a chart posted with no cashtag is kept under the account with no
name, and shows only when that account is chosen.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from . import authors, netsafe, xcalls
from .ledger import connect

ROOT = Path(__file__).resolve().parent.parent
PULL_DIR = ROOT / "research" / "x" / "pulls"
IMAGE_DIR = ROOT / "research" / "x" / "images"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
GAP = 1.0                      # seconds between downloads; a reader's pace
MAX_BYTES = 6_000_000          # a chart is a few hundred KB; past this it is a photo, not a chart


def ensure_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS x_charts (
        tweet_id TEXT NOT NULL, n INTEGER NOT NULL, handle TEXT NOT NULL,
        date TEXT NOT NULL, symbols TEXT NOT NULL DEFAULT '', text TEXT,
        url TEXT NOT NULL, path TEXT NOT NULL,
        saved_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (tweet_id, n))""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_x_charts_date ON x_charts (date)")


def _download(url: str) -> bytes | None:
    # Ask for the large rendition; the URL in the post is the medium one.
    full = url + ("&" if "?" in url else "?") + "name=large"
    req = urllib.request.Request(full, headers={"user-agent": UA})
    resp = netsafe.urlopen(req, timeout=45)
    body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES or not body:
        return None
    return body


def fetch(conn, pull: dict, dry_run: bool = False, log=None) -> dict:
    """Save every photo in one pull file that is not yet on disk."""
    ensure_schema(conn)
    say = log or (lambda *_: None)
    have = {(r["tweet_id"], r["n"]) for r in conn.execute("SELECT tweet_id, n FROM x_charts")}
    n_seen = n_saved = n_failed = 0
    for handle, posts in (pull.get("tweets") or {}).items():
        for p in posts or []:
            images = p.get("images") or []
            if not images:
                continue
            tid = str(p.get("id") or "")
            day = xcalls.iso_date(p.get("date") or "")
            if not tid or not day:
                continue
            syms = ",".join(sorted(authors.mentions_in(p.get("text") or "")))
            for n, url in enumerate(images):
                if (tid, n) in have:
                    continue
                n_seen += 1
                rel = f"{re.sub(r'[^A-Za-z0-9_]', '', handle)}/{tid}-{n}.jpg"
                say(f"  {day} @{handle:<18} {syms or '—':<12} {rel}")
                if dry_run:
                    continue
                try:
                    body = _download(url)
                except Exception as exc:                       # noqa: BLE001
                    n_failed += 1
                    say(f"    ! {type(exc).__name__}: {exc}")
                    continue
                if not body:
                    n_failed += 1
                    continue
                dest = IMAGE_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                conn.execute("""INSERT OR IGNORE INTO x_charts (tweet_id, n, handle, date, symbols, text, url, path)
                                VALUES (?,?,?,?,?,?,?,?)""",
                             (tid, n, handle, day, syms, (p.get("text") or "")[:600], url, rel))
                have.add((tid, n))
                n_saved += 1
                time.sleep(GAP)
    if not dry_run:
        conn.commit()
    return {"seen": n_seen, "saved": n_saved, "failed": n_failed}


def charts(conn, limit: int = 600, symbol: str | None = None) -> list[dict]:
    """Newest first, in the shape the Their charts grid reads. With `symbol`,
    only the charts whose post named it — matched in SQL on the comma list,
    so a name's whole history comes back and not the newest `limit` of
    everyone's. The symbol page asks this way (D133)."""
    ensure_schema(conn)
    out = []
    if symbol:
        rows = conn.execute("SELECT * FROM x_charts WHERE ',' || symbols || ',' LIKE ? "
                            "ORDER BY date DESC, tweet_id DESC, n LIMIT ?", (f"%,{symbol},%", limit))
    else:
        rows = conn.execute("SELECT * FROM x_charts ORDER BY date DESC, tweet_id DESC, n LIMIT ?", (limit,))
    for r in rows:
        syms = [s for s in (r["symbols"] or "").split(",") if s]
        out.append({"source": "x", "author": xcalls.author_for(conn, r["handle"]), "handle": r["handle"],
                    "date": r["date"], "symbols": syms, "symbol": syms[0] if syms else None,
                    "timeframe": "", "text": r["text"] or "",
                    "images": [f"/chart-x?id={r['tweet_id']}&n={r['n']}"],
                    "post_url": f"https://x.com/{r['handle']}/status/{r['tweet_id']}"})
    return out


def image_path(conn, tweet_id: str, n: int) -> Path | None:
    """The saved file for one chart, or None. The path is the stored one,
    checked to stay under the images folder."""
    if not re.fullmatch(r"\d{1,25}", tweet_id or ""):
        return None
    row = conn.execute("SELECT path FROM x_charts WHERE tweet_id=? AND n=?", (tweet_id, n)).fetchone()
    if not row:
        return None
    p = (IMAGE_DIR / row["path"]).resolve()
    if IMAGE_DIR.resolve() not in p.parents or not p.is_file():
        return None
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pulls", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    files = [Path(p) for p in args.pulls] or sorted(PULL_DIR.glob("*.json"))
    conn = connect()
    total = {"seen": 0, "saved": 0, "failed": 0}
    for f in files:
        try:
            pull = json.loads(f.read_text())
        except (ValueError, OSError) as exc:
            print(f"{f}: {exc}")
            continue
        r = fetch(conn, pull, dry_run=args.dry_run, log=print)
        for k in total:
            total[k] += r[k]
    print(f"{total['seen']} chart(s) new, {total['saved']} saved, {total['failed']} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
