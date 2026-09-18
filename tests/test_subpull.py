"""The nightly Substack pull, without the network.

What must hold: the publication list is read from the tracked file beside
the gitignored folder; the text rendering keeps the receiver's header so the
chart splitter still finds the post's URL on line three; a paid post that
comes back as the paywall teaser is never written and is reported as the
session's fault; and a post already on disk is not fetched again.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import subpull  # noqa: E402

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


tmp = Path(tempfile.mkdtemp())
subpull.SUB_DIR = tmp / "substack"
subpull.PUBLICATIONS = tmp / "publications.txt"
subpull.COOKIE_FILE = tmp / ".substack"
subpull.GAP = 0

check("no list means no publications", subpull.publications() == [])
subpull.PUBLICATIONS.write_text("# comment\nStonkChris stonkchris.substack.com\n\nbad\n")
check("the list is (folder, host) pairs, comments and short lines skipped",
      subpull.publications() == [("StonkChris", "stonkchris.substack.com")], subpull.publications())
check("no cookie file means no session", subpull.session() is None)
subpull.COOKIE_FILE.write_text("# private\nsubstack.sid=abc123\n")
check("the cookie may be pasted with its name", subpull.session() == "abc123", subpull.session())

txt = subpull.to_text('<p>Hello <b>there</b></p><img src="https://x/y.png"><p>&amp; more</p>')
check("images become [image: url] lines", "[image: https://x/y.png]" in txt, txt)
check("entities are unescaped and tags dropped", "Hello there" in txt and "& more" in txt, txt)

# The network, replaced.
ARCHIVE = [{"slug": "old-post", "post_date": "2026-09-01T10:00:00Z", "audience": "only_paid", "type": "newsletter"},
           {"slug": "new-post", "post_date": "2026-09-13T10:00:00Z", "audience": "only_paid", "type": "newsletter"},
           {"slug": "a-podcast", "post_date": "2026-09-12T10:00:00Z", "audience": "everyone", "type": "podcast"}]
BODIES = {"new-post": "<p>" + "chart " * 600 + "</p>", "old-post": "<p>old</p>"}
subpull.archive = lambda host, sid, limit=20: ARCHIVE
subpull.post = lambda host, slug, sid: {"slug": slug, "title": "T", "subtitle": "S", "post_date": "2026-09-13T10:00:00Z",
                                        "canonical_url": f"https://stonkchris.substack.com/p/{slug}",
                                        "body_html": BODIES[slug]}
(subpull.SUB_DIR / "StonkChris").mkdir(parents=True)
(subpull.SUB_DIR / "StonkChris" / "2026-09-01-old-post.json").write_text("{}")

r = subpull.pull(log=lambda *_: None)
check("only the post not on disk is written, and not the podcast", r["written"] == ["StonkChris/2026-09-13-new-post"], r)
head = (subpull.SUB_DIR / "StonkChris" / "2026-09-13-new-post.txt").read_text().splitlines()[:3]
check("the text file carries the receiver's header: title, subtitle, date and URL",
      head[0] == "# T" and head[1] == "S" and head[2].endswith("https://stonkchris.substack.com/p/new-post"), head)

# A teaser is the session's fault and is never written.
BODIES["new-post"] = "<p>Subscribe to read</p>"
(subpull.SUB_DIR / "StonkChris" / "2026-09-13-new-post.json").unlink()
try:
    subpull.pull(log=lambda *_: None)
    check("a teaser stops the pull with a message about the session", False)
except subpull.SubPullError as exc:
    check("a teaser stops the pull with a message about the session", "expired" in str(exc), str(exc))
check("and nothing was written for it", not (subpull.SUB_DIR / "StonkChris" / "2026-09-13-new-post.json").exists())

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
