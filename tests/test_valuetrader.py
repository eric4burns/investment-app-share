"""The Value Trader emails: the subject's ticker and call, the teaser, the chart."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import valuetrader as vt

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

check("a BUY LEVEL subject is a buy on the ticker", vt.classify("$ONDS - BUY LEVEL") == (["ONDS"], "buy"), vt.classify("$ONDS - BUY LEVEL"))
check("a question subject names the ticker and makes no call", vt.classify("$IREN - IS IT CHEAP?") == (["IREN"], None))
check("TOP PICK is a buy", vt.classify("$ETH 2026 TOP PICK") == (["ETH"], "buy"))
check("an earnings calendar is noise", vt.classify("EARNINGS CALENDAR - WEEK 13") == ([], None))
check("a video note with a ticker keeps the ticker, no call", vt.classify("$AMD - SHORT VIDEO")[0] == ["AMD"])

HTML = """<html><body><style>x{}</style><table><tr><td>$ONDS - BUY LEVEL</td></tr><tr><td>96</td></tr>
<tr><td>This is just a short update ... &#847; &#847;</td></tr>
<tr><td><img src="https://c10.patreonusercontent.com/4/patreon-media/p/post/168589398/90c0/eyJ3IjoxMDgwfQ%3D%3D/1.png?token-hash=abc&amp;token-time=1"></td></tr>
<tr><td>$ONDS - BUY LEVEL</td></tr><tr><td>The Value Trader</td></tr><tr><td>Sep 4, 2026</td></tr>
<tr><td><a href="https://www.patreon.com/TheValueTrader/posts/onds-buy-level-168589398?utm=1">View in app</a></td></tr>
<tr><td>This is just a short update to share the buy levels for $ONDS tonight.</td></tr>
<tr><td>These are the buy levels, but if we were to get weakness, my concerns would be how $ONDS performs.</td></tr>
<tr><td>Did you like this post?</td></tr><tr><td>Share</td></tr><tr><td>&copy; 2026 The Value Trader</td></tr>
</table></body></html>"""
b = vt.parse_html(HTML)
check("the post's chart image is found with its token intact", b["image_url"] and "token-hash=abc&token-time=1" in b["image_url"], b["image_url"])
check("the post id comes from the image path", b["post_id"] == "168589398", b["post_id"])
check("the post link is kept without its tracking query", b["post_url"] == "https://www.patreon.com/TheValueTrader/posts/onds-buy-level-168589398", b["post_url"])
check("the teaser is the body text, not the header or footer",
      b["teaser"].startswith("This is just a short update to share") and "Did you like" not in b["teaser"] and "96" not in b["teaser"], b["teaser"])

EMPTY = HTML.replace("<tr><td>This is just a short update to share the buy levels for $ONDS tonight.</td></tr>\n<tr><td>These are the buy levels, but if we were to get weakness, my concerns would be how $ONDS performs.</td></tr>\n", "").replace("<tr><td>Share</td></tr>", "<tr><td>Share</td></tr><tr><td>600 Townsend Street</td></tr><tr><td>San Francisco, CA 94103</td></tr>")
check("an email with no body text has an empty teaser, not the footer address", vt.parse_html(EMPTY)["teaser"] == "", vt.parse_html(EMPTY)["teaser"])

raw = ("From: The Value Trader <thevaluetrader@creator.patreon.com>\r\nSubject: $ONDS - BUY LEVEL\r\nDate: Fri, 04 Sep 2026 12:04:08 +0000\r\n"
       "Message-ID: <abc@creator.patreon.com>\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + HTML).encode()
rec = vt.parse_message(raw)
check("a message parses to a dated record", rec and rec["email_date"] == "2026-09-04" and rec["symbols"] == ["ONDS"] and rec["action"] == "buy", rec)
check("mail from anyone else is ignored", vt.parse_message(raw.replace(b"patreon.com>", b"example.com>", 1)) is None)

# store into a memory ledger without downloading
import sqlite3
mem = sqlite3.connect(":memory:"); mem.row_factory = sqlite3.Row
from app import journal
journal.ensure_schema(mem)
mem.execute("CREATE TABLE IF NOT EXISTS prices (symbol TEXT, bar_date TEXT, close REAL)")
r = vt.store(mem, [rec], download=False)
check("a new post is stored once and journaled as the author's call", len(r["new"]) == 1 and r["journaled"] == 1, r)
r2 = vt.store(mem, [rec], download=False)
check("storing it again adds nothing", not r2["new"] and r2["journaled"] == 0, r2)
rows = vt.recent(mem, 400)
check("recent lists it with its symbols and no image", rows and rows[0]["symbols"] == ["ONDS"] and rows[0]["has_image"] is False, rows)
check("by_symbol indexes it under the ticker", "ONDS" in vt.by_symbol(mem, 400))

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  -> {detail}"))
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
