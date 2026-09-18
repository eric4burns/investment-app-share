"""Receive Substack posts from the logged-in browser tab and save them locally.

Substack's paid posts render only to a logged-in session, and the browser tool
can carry a few kilobytes per call. So the page fetches each post itself and
POSTs it here; this writes research/substack/<author>/<date>-<slug>.json (the
full API record) and .txt (the article as plain text). Everything under
research/substack/ is gitignored: paid content, kept locally only.

    python3 research/substack_receiver.py 8799
"""
import json
import re
import sys
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "substack"


def to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<img[^>]+src=\"([^\"]+)\"[^>]*>", r"\n[image: \1]\n", html)
    html = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|blockquote|figure|figcaption)>", "\n", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    text = unescape(html)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class H(BaseHTTPRequestHandler):
    timeout = 30
    protocol_version = "HTTP/1.1"
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        author = re.sub(r"[^A-Za-z0-9_-]", "", body.get("author", "unknown")) or "unknown"
        post = body["post"]
        date = (post.get("post_date") or "")[:10]
        slug = re.sub(r"[^A-Za-z0-9_-]", "", post.get("slug", str(post.get("id"))))
        d = ROOT / author
        d.mkdir(parents=True, exist_ok=True)
        base = d / f"{date}-{slug}"
        base.with_suffix(".json").write_text(json.dumps(post, indent=1))
        txt = f"# {post.get('title','')}\n{post.get('subtitle','')}\n{post.get('post_date','')}  {post.get('canonical_url','')}\n\n"
        txt += to_text(post.get("body_html") or "")
        base.with_suffix(".txt").write_text(txt)
        out = json.dumps({"saved": base.name, "chars": len(txt)}).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.command, fmt % a)); sys.stderr.flush()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"receiving on http://localhost:{port} -> {ROOT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
