"""The charts the followed accounts post on X, saved by account.

What must hold: a photo is saved once per tweet and index, under the
account's folder, with the cashtags of the post as its names; a download
that fails or is too large leaves no row; the grid rows carry the author the
journal uses, a link to the post and the app's own image route; and the
image route serves only a stored path under the images folder.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import journal as J, xcharts  # noqa: E402

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())
J.ensure_schema(conn)

tmp = Path(tempfile.mkdtemp())
xcharts.IMAGE_DIR = tmp / "images"
xcharts.GAP = 0
BODIES = {"https://pbs.twimg.com/media/a.jpg": b"\xff\xd8chart-a", "https://pbs.twimg.com/media/b.jpg": b"\xff\xd8chart-b",
          "https://pbs.twimg.com/media/big.jpg": None}
xcharts._download = lambda url: BODIES[url] if url in BODIES else (_ for _ in ()).throw(OSError("no such image"))

pull = {"tweets": {"StonkChris": [
    {"id": "100", "date": "2026-09-13T10:00:00+00:00", "text": "$IREN and $DGXX weekly charts",
     "images": ["https://pbs.twimg.com/media/a.jpg", "https://pbs.twimg.com/media/b.jpg"]},
    {"id": "101", "date": "Sat Sep 13 11:00:00 +0000 2026", "text": "a photo of lunch", "images": ["https://pbs.twimg.com/media/big.jpg"]},
    {"id": "102", "date": "2026-09-13T12:00:00+00:00", "text": "$AMD", "images": ["https://pbs.twimg.com/media/gone.jpg"]},
    {"id": "103", "date": "2026-09-13T12:00:00+00:00", "text": "no picture", "images": []},
]}}
r = xcharts.fetch(conn, pull)
check("two photos saved, one too large and one failed download left out", (r["seen"], r["saved"], r["failed"]) == (4, 2, 2), r)
rows = conn.execute("SELECT * FROM x_charts ORDER BY n").fetchall()
check("one row per photo, under the account's folder", [x["path"] for x in rows] == ["StonkChris/100-0.jpg", "StonkChris/100-1.jpg"], [x["path"] for x in rows])
check("the files are on disk", all((xcharts.IMAGE_DIR / x["path"]).read_bytes().startswith(b"\xff\xd8") for x in rows))
check("the post's cashtags are the chart's names", rows[0]["symbols"] == "DGXX,IREN", rows[0]["symbols"])
r = xcharts.fetch(conn, pull)
check("running again saves nothing new", r["saved"] == 0 and conn.execute("SELECT COUNT(*) FROM x_charts").fetchone()[0] == 2, r)

grid = xcharts.charts(conn)
check("grid rows carry the journal's author name", grid[0]["author"] == "StonkChris (@StonkChris)", grid[0]["author"])
check("the names, the post link and the app's image route",
      grid[0]["symbols"] == ["DGXX", "IREN"] and grid[0]["post_url"] == "https://x.com/StonkChris/status/100"
      and grid[0]["images"] == ["/chart-x?id=100&n=0"], grid[0])
one = xcharts.charts(conn, symbol="IREN")
check("asking for one name returns only the charts whose post named it", len(one) == 2 and all("IREN" in r["symbols"] for r in one), one)
check("a name matched on the comma list, not as a substring (IRE is nobody)", xcharts.charts(conn, symbol="IRE") == [])

p = xcharts.image_path(conn, "100", 1)
check("the image route resolves a stored chart", p is not None and p.name == "100-1.jpg", p)
check("an unknown chart is None", xcharts.image_path(conn, "100", 5) is None)
check("a non-numeric id is refused", xcharts.image_path(conn, "../etc/passwd", 0) is None)
conn.execute("UPDATE x_charts SET path='../../escape.jpg' WHERE tweet_id='100' AND n=0")
check("a path outside the images folder is refused even if stored", xcharts.image_path(conn, "100", 0) is None)

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
