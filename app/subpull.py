"""The nightly Substack pull: new posts from the subscribed publications, to disk.

    python3 -m app.subpull                 # every publication in research/substack-publications.txt
    python3 -m app.subpull --dry-run       # list what would be fetched

## Why

The posts were fetched by hand: a receiver on a local port, the logged-in
browser tab told to POST each post to it (D50). That worked once for the
back catalogue and then nobody did it again, so the charts, the priced
levels and the graded calls from the Substack stopped at whatever day the
last session happened to be. The user asked for it automated on 2026-09-13.

## How

Substack's own JSON is what the site's pages read. The archive list is
public; a paid post's body comes back whole only with the reader's session
cookie (`substack.sid`), and as the paywall teaser without it. The cookie
goes on the first line of data/.substack — the same arrangement as the X
session in data/.x — and the pull refuses to write a truncated post so a
lapsed cookie shows up as "nothing new" in the log rather than as a folder of
teasers.

Each post is written as research/substack/<author>/<date>-<slug>.json (the
record as Substack returned it) and .txt (the article as plain text), which
is exactly what the receiver wrote, so everything downstream — the chart
splitter, the level parser, the call seeder — reads the new posts unchanged.
Everything under research/substack/ is gitignored: paid content, local only.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path

from . import netsafe

ROOT = Path(__file__).resolve().parent.parent
SUB_DIR = ROOT / "research" / "substack"
# Beside the folder, not in it: research/substack/ is gitignored whole and
# tests/test_size.py fails if any of it is ever tracked. The list is not paid
# content and belongs in the repository.
PUBLICATIONS = ROOT / "research" / "substack-publications.txt"
COOKIE_FILE = ROOT / "data" / ".substack"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
# Seconds between posts. A subscriber reading the site makes the same calls
# at about this pace; there is no reason to go faster.
GAP = 3
# Below this many characters of body a "paid" post is the teaser, not the post.
TEASER = 1500


class SubPullError(RuntimeError):
    """Something the user has to fix — a missing or expired session."""


def publications() -> list[tuple[str, str]]:
    """(folder name, host) pairs: `StonkChris stonkchris.substack.com`."""
    if not PUBLICATIONS.exists():
        return []
    out = []
    for line in PUBLICATIONS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


def session() -> str | None:
    if not COOKIE_FILE.exists():
        return None
    for line in COOKIE_FILE.read_text().splitlines():
        v = line.strip()
        if v and not v.startswith("#"):
            return v.split("=", 1)[1] if v.lower().startswith("substack.sid=") else v
    return None


def _get(url: str, sid: str | None, timeout: int = 45) -> str:
    headers = {"user-agent": UA, "accept": "application/json", "accept-encoding": "gzip"}
    if sid:
        headers["cookie"] = f"substack.sid={sid}"
    resp = netsafe.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def to_text(html: str) -> str:
    """The article as plain text, one image per line as [image: url] — the
    same rendering the receiver used, so the chart splitter's headers match."""
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<img[^>]+src=\"([^\"]+)\"[^>]*>", r"\n[image: \1]\n", html)
    html = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|blockquote|figure|figcaption)>", "\n", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    text = unescape(html)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def archive(host: str, sid: str | None, limit: int = 20) -> list[dict]:
    return json.loads(_get(f"https://{host}/api/v1/archive?sort=new&offset=0&limit={limit}", sid))


def post(host: str, slug: str, sid: str | None) -> dict:
    return json.loads(_get(f"https://{host}/api/v1/posts/{slug}", sid))


def on_disk(author: str) -> set[str]:
    d = SUB_DIR / author
    return {p.stem.split("-", 3)[-1] for p in d.glob("*.json")} if d.exists() else set()


def pull(dry_run: bool = False, log=print, limit: int = 20) -> dict:
    sid = session()
    pubs = publications()
    if not pubs:
        raise SubPullError(f"no publications listed in {PUBLICATIONS.name} "
                           f"(one per line: `StonkChris stonkchris.substack.com`)")
    written, teasers, errors = [], [], []
    for author, host in pubs:
        try:
            posts = archive(host, sid, limit)
        except Exception as exc:                               # noqa: BLE001
            errors.append(f"{host}: archive: {type(exc).__name__}: {exc}")
            continue
        have = on_disk(author)
        new = [p for p in posts if p.get("slug") and p["slug"] not in have and p.get("type") != "podcast"]
        log(f"{author}: {len(posts)} in the archive, {len(new)} not on disk")
        for p in new:
            slug, day = p["slug"], (p.get("post_date") or "")[:10]
            if dry_run:
                log(f"  would fetch {day} {slug} ({p.get('audience')})")
                continue
            try:
                full = post(host, slug, sid)
            except Exception as exc:                           # noqa: BLE001
                errors.append(f"{host}/{slug}: {type(exc).__name__}: {exc}")
                continue
            body = full.get("body_html") or ""
            if p.get("audience") in ("only_paid", "founding") and len(body) < TEASER:
                # The teaser, not the post: the session is missing or expired.
                teasers.append(slug)
                log(f"  {day} {slug}: paywall teaser only ({len(body)} chars) — not written")
                time.sleep(GAP)
                continue
            d = SUB_DIR / author
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{day}-{slug}.json").write_text(json.dumps(full, indent=1))
            # The receiver's exact header — title, subtitle, date and URL —
            # because substack_charts.py reads the post's URL off line three.
            (d / f"{day}-{slug}.txt").write_text(
                f"# {full.get('title', '')}\n{full.get('subtitle', '')}\n"
                f"{full.get('post_date', '')}  {full.get('canonical_url', '')}\n\n{to_text(body)}")
            written.append(f"{author}/{day}-{slug}")
            log(f"  wrote {day} {slug} ({len(body):,} chars)")
            time.sleep(GAP)
    if teasers and not sid:
        raise SubPullError(f"{len(teasers)} paid post(s) came back as the teaser and there is no session: "
                           f"run ./substack-setup.sh to store the substack.sid cookie in {COOKIE_FILE.name}")
    if teasers:
        raise SubPullError(f"{len(teasers)} paid post(s) came back as the teaser: the session in "
                           f"{COOKIE_FILE.name} has expired — log in to Substack in the browser and run "
                           f"./substack-setup.sh again")
    return {"written": written, "errors": errors}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=20, help="archive entries to look at per publication")
    args = ap.parse_args(argv)
    try:
        r = pull(dry_run=args.dry_run, limit=args.limit)
    except SubPullError as exc:
        print(f"STOPPED: {exc}")
        return 2
    for e in r["errors"]:
        print(f"  ! {e}")
    print(f"{len(r['written'])} post(s) written" + (f", {len(r['errors'])} errors" if r["errors"] else ""))
    return 0 if not r["errors"] else 3


if __name__ == "__main__":
    sys.exit(main())
