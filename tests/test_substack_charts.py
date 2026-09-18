"""The Substack charts, split from the saved posts.

The reader and the nightly writer (subpull.py) have to agree on the file: the
title on line one, the URL on line three, `TICKER (1D)` headers, images as
`[image: url]` lines. A block with no image is not a chart; a block whose
image is not an http(s) URL is dropped before it can reach an <img src>; and
the newest post comes first. Written against a temp folder in the receiver's
format, and against subpull.to_text's output, so a drift between the two
fails here rather than as an empty tab.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import subpull, substack_charts as SC  # noqa: E402

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


tmp = Path(tempfile.mkdtemp())
SC.ROOT = tmp
d = tmp / "StonkChris"
d.mkdir()
(d / "2026-09-09-aerospace.txt").write_text(
    "# Aerospace chart review\nsubtitle\n2026-09-09T23:58:39.976Z  https://stonkchris.substack.com/p/aerospace\n\n"
    "ASTS (1D)\n[image: https://substackcdn.com/a.png]\nStill looks bottomed around $52.\n\n"
    "KTOS (1W)\nNo chart here, just words.\n\n"
    "RKLB (1D)\n[image: javascript:alert(1)]\nbad image\n\n"
    "$SATL (4H)\n[image: https://substackcdn.com/s.png]\n[image: https://substackcdn.com/s2.png]\nTwo charts.\n")
(d / "2026-09-13-weekend.txt").write_text(
    "# Weekend review\n\n2026-09-13T10:00:00Z  https://stonkchris.substack.com/p/weekend\n\n"
    "AMD (1D)\n[image: https://substackcdn.com/amd.png]\nConstructive.\n")

rows = SC.charts()
check("only blocks with an http(s) image are charts", [r["symbol"] for r in rows] == ["AMD", "ASTS", "SATL"], [r["symbol"] for r in rows])
check("newest post first", rows[0]["date"] == "2026-09-13", rows[0]["date"])
check("the post's URL is read off line three", rows[1]["post_url"] == "https://stonkchris.substack.com/p/aerospace", rows[1]["post_url"])
check("the title is line one without the hash", rows[1]["post"] == "Aerospace chart review", rows[1]["post"])
check("a $-prefixed header and a 4H timeframe are read", rows[2]["symbol"] == "SATL" and rows[2]["timeframe"] == "4H", rows[2])
check("every image of a block is kept, in order", rows[2]["images"] == ["https://substackcdn.com/s.png", "https://substackcdn.com/s2.png"], rows[2]["images"])
check("the words stay with the chart, without the image lines", rows[1]["text"] == "Still looks bottomed around $52.", rows[1]["text"])
check("by_symbol keys the same rows", set(SC.by_symbol()) == {"AMD", "ASTS", "SATL"})

# What the nightly pull writes is what this reads: to_text renders an <img>
# as an [image: url] line, and the post header goes on the same three lines.
html = "<h3>NVDA (1D)</h3><p>Holding the 50-day.</p><img src=\"https://substackcdn.com/n.png\"><p>Target $200.</p>"
(d / "2026-09-14-nightly.txt").write_text(
    f"# Nightly\n\n2026-09-14T01:00:00Z  https://stonkchris.substack.com/p/nightly\n\n{subpull.to_text(html)}")
rows = SC.charts()
check("a post written by subpull.to_text splits into the same chart rows",
      rows[0]["symbol"] == "NVDA" and rows[0]["images"] == ["https://substackcdn.com/n.png"] and "Target $200." in rows[0]["text"], rows[0])
check("a missing author folder is an empty list, not an error", SC.charts("Nobody") == [])

# Every post is read by default. Twelve was the old window, and a name charted
# thirteen posts ago vanished from the tab (FPS, 2026-09-17).
for i in range(26):
    (d / f"2026-06-{i + 1:02d}-old.txt").write_text(
        f"# Old {i}\n\n2026-06-{i + 1:02d}T00:00:00Z  https://stonkchris.substack.com/p/old{i}\n\n"
        f"OLD{chr(65 + i)} (1D)\n[image: https://substackcdn.com/old{i}.png]\nWords.\n")
rows = SC.charts()
check("every post is read, not the newest dozen", any(r["symbol"] == "OLDA" for r in rows) and len(rows) == 30, len(rows))
check("a caller may still ask for the newest few posts", len(SC.charts(limit_posts=2)) == 2, len(SC.charts(limit_posts=2)))

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
