"""The charts from a subscribed Substack, per symbol, beside the app's own read.

The Value Trader's charts have been on the Research tab since D74 for a reason
that does not apply to anyone else: his levels are drawn ON the chart and never
written in the text, so the image is the only way to use him. StonkChris writes
his levels out, `substack_levels.py` parses them, and nobody ever showed his
charts — the user asked why, on 2026-09-10, and the honest answer is that it
never came up. His posts carry ten charts each and the URLs were already on
disk.

The blocks come from the same `[TICKER] (1D)` headers `substack_extract` splits
on, so a symbol's chart and its parsed levels can never disagree about which
block they came from. Images are read from the `.txt` the receiver writes, where
the extractor drops them.

Nothing is downloaded: the URLs point at Substack's own CDN and the page loads
them the way the post does. The posts themselves stay local and gitignored.

Every post is read, not the newest dozen. The first version stopped at twelve
posts, which on 2026-09-17 was about two weeks of him: FPS, last charted on
2026-08-04 with seventeen posts since, was simply absent from the tab and the
user asked why. All 261 posts parse in under a second and the answer is cached
and gzipped like every other payload, and the tab already narrows by name and
date, so there is nothing to gain from a window and a name to lose.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "research" / "substack"

# Same shape as substack_extract.HDR — a ticker and a timeframe on their own
# line. Kept in step deliberately: if one recognises a header and the other does
# not, a chart ends up under the wrong name, which is exactly how SPCX's levels
# were once attributed to SATL.
HDR = re.compile(r"^\$?([A-Z]{1,6})(?:\.[A-Z])?\s*\((\d{1,2}[A-Za-z]{1,3})\)\s*(?:\*+)?\s*$", re.M)
# Only http(s) URLs are kept, here and for the post link below: what these
# match is served straight into <img src> and <a href>, and the receiver
# stores whatever the email said. A `javascript:` URL in a post is dropped
# before it is ever stored or sent.
IMG = re.compile(r"^\[image:\s*(https?://\S+?)\]\s*$", re.M)
LINK = re.compile(r"^https?://\S+$")


def charts(author: str = "StonkChris", limit_posts: int | None = None) -> list[dict]:
    """Every per-symbol block that has a chart, newest post first. `limit_posts`
    exists for a caller that wants only the newest few; the tab wants all."""
    d = ROOT / author
    if not d.is_dir():
        return []
    out = []
    files = sorted(d.glob("*.txt"), reverse=True)
    if limit_posts is not None:
        files = files[:limit_posts]
    for f in files:
        body = f.read_text(errors="ignore")
        head, _, rest = body.partition("\n\n")
        title = head.splitlines()[0].lstrip("# ").strip() if head else f.stem
        url = next((w for w in head.split() if LINK.match(w)), None)
        date = f.name[:10]
        marks = list(HDR.finditer(rest))
        for i, m in enumerate(marks):
            chunk = rest[m.end():(marks[i + 1].start() if i + 1 < len(marks) else len(rest))]
            imgs = IMG.findall(chunk)
            if not imgs:
                continue
            text = IMG.sub("", chunk).strip()
            out.append({"author": author, "date": date, "post": title, "post_url": url,
                        "symbol": m.group(1), "timeframe": m.group(2),
                        "images": imgs, "text": text[:600]})
    return out


def by_symbol(author: str = "StonkChris", limit_posts: int | None = None) -> dict[str, list[dict]]:
    """Newest chart first for each symbol."""
    out: dict[str, list[dict]] = {}
    for c in charts(author, limit_posts):
        out.setdefault(c["symbol"], []).append(c)
    return out
