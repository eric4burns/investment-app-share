"""The server's request guards, against a live server on a random port.

Every check here is a request a browser somewhere else on the internet could
make once the app is open on the phone at http://100.x.x.x:8737 — where no
Sec-Fetch-Site header arrives and the token is the only thing between an
<img src="/api/watchlist?action=remove&symbol=IREN"> and the watchlist.
"""
import http.client
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# An empty ledger of our own, chosen BEFORE app.web is imported: ledger.DB_PATH
# is resolved at import, and a test must never write to the real database.
_TMP = tempfile.mkdtemp(prefix="webguard-")
os.environ["INVESTMENT_APP_DB"] = str(Path(_TMP) / "ledger.db")
os.environ.setdefault("INVESTMENT_APP_CONFIG", "/nonexistent/no-config.json")

from app import web                                     # noqa: E402
from app.ledger import connect                          # noqa: E402

connect().close()                                       # schema only

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()


def req(method, path, headers=None, body=None, host=None, raw_length=None):
    """One request, one fresh connection. Returns (status, headers, body)."""
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"Host": host if host is not None else f"127.0.0.1:{PORT}"}
    h.update(headers or {})
    if raw_length is not None:
        # http.client computes Content-Length itself; send the bad one by hand.
        c.putrequest(method, path, skip_host=True)
        for k, v in h.items():
            c.putheader(k, v)
        c.putheader("Content-Length", raw_length)
        c.endheaders()
    else:
        c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


TOKEN = {"X-App-Token": web.TOKEN}

# ---- the page hands out the token and the policy -------------------------
st, hd, body = req("GET", "/")
check("the dashboard is served", st == 200, st)
check("the page carries the token in a meta tag",
      f'<meta name="app-token" content="{web.TOKEN}">' in body.decode(), body[:200])
check("a Content-Security-Policy header is on the page",
      "default-src 'self'" in hd.get("Content-Security-Policy", ""), hd.get("Content-Security-Policy"))
check("the page names the server without a Python version",
      hd.get("Server") == "investment-app", hd.get("Server"))
check("every response carries a Content-Length (HTTP/1.1 needs it)",
      hd.get("Content-Length") == str(len(body)), hd.get("Content-Length"))

# ---- writes need the token ------------------------------------------------
st, _, body = req("GET", "/api/watchlist?action=remove&symbol=IREN")
check("a GET write without the token is refused", st == 403, (st, body))
st, _, body = req("GET", "/api/watchlist?action=remov%65&symbol=IREN")
check("percent-encoding the action does not slip past the guard", st == 403, (st, body))
st, _, body = req("GET", "/api/watchlist?action=remove&symbol=IREN", headers=TOKEN)
check("the same write with the token passes the guard", st == 200, (st, body))
st, _, body = req("GET", "/api/watchlist?action=remove&symbol=IREN",
                  headers={**TOKEN, "Sec-Fetch-Site": "cross-site"})
check("a browser that says cross-site is refused even with the token", st == 403, (st, body))
for path in ("/api/backtest?method=x", "/api/replay", "/api/rotation", "/api/valuetrader",
             "/api/amazon", "/api/research?kind=macro&detail=x", "/api/outlook?action=refresh"):
    st, _, body = req("GET", path)
    check(f"{path} is guarded without an action word", st == 403, (st, body))
for path in ("/api/backtest?last=1", "/api/backtest?catalogue=1", "/api/research"):
    st, _, body = req("GET", path)
    check(f"{path} is a read and needs no token", st == 200, (st, body[:120]))

st, _, body = req("GET", "/api/watchlist")
check("a plain read needs no token", st == 200, (st, body[:120]))
st, _, body = req("GET", "/api/watchlist", host="")
check("no Host header at all (curl) is allowed", st == 200, (st, body[:120]))

# ---- POST ----------------------------------------------------------------
st, _, body = req("POST", "/api/setup", body=b'{"action":"profile","filing_status":"single"}',
                  headers={"Content-Type": "application/json"})
check("a POST without the token is refused", st == 403, (st, body))
st, _, body = req("POST", "/api/setup", body=b'{"action":"nonsense"}',
                  headers={"Content-Type": "application/json", **TOKEN})
check("a POST with the token passes the guard (and reaches the action check)",
      st == 400 and b"unknown action" in body, (st, body))
st, _, body = req("POST", "/api/setup", body=b'{}',
                  headers={"Content-Type": "application/json", **TOKEN,
                           "Origin": "http://evil.example"})
check("a POST whose Origin is another site is refused", st == 403, (st, body))
st, _, body = req("POST", "/api/setup", body=b'{"action":"nonsense"}',
                  headers={"Content-Type": "application/json", **TOKEN,
                           "Origin": f"http://127.0.0.1:{PORT}"})
check("a POST whose Origin is this server passes", st == 400, (st, body))
st, _, body = req("POST", "/api/setup", headers={**TOKEN}, raw_length="abc")
check("a non-numeric Content-Length is a 400, not a crash", st == 400, (st, body))

# ---- Host -----------------------------------------------------------------
st, _, body = req("GET", "/api/watchlist", host="evil.example")
check("a Host this server does not answer to is refused", st == 403, (st, body))
st, _, body = req("GET", "/api/watchlist", host=f"[::1]:{PORT}")
check("IPv6 loopback with a port is allowed", st == 200, (st, body[:120]))
check("host_name strips the bracketed port form", web.host_name("[::1]:8737") == "::1")
check("host_name leaves a bare IPv6 address alone", web.host_name("::1") == "::1")
check("host_name drops a port from a name", web.host_name("Localhost:8737") == "localhost")

# ---- symbols --------------------------------------------------------------
st, _, body = req("GET", "/api/chart?symbol=X/../../v2/account")
check("a symbol that rewrites a feed URL path is refused", st == 400, (st, body))
for ok in ("SIVEF", "BRK.B", "LINK-USD", "HYPE32196-USD", "sivef"):
    check(f"{ok!r} is a symbol", web.bad_symbol_params({"symbol": [ok]}) is None)
check("a benchmark off the page's list is refused",
      web.bad_symbol_params({"benchmarks": ["SPY,EVIL"]}) is not None)
check("the page's own benchmarks pass",
      web.bad_symbol_params({"benchmarks": ["SPY,QQQ,DJIA"]}) is None)

# ---- static ---------------------------------------------------------------
st, hd, body = req("GET", "/static/../web.py")
check("path traversal under /static is a 404", st == 404, st)
check("the 404 carries a Content-Length too", hd.get("Content-Length") == "0", hd)
st, _, _ = req("GET", "/static/lightweight-charts.js")
check("the vendored chart library is served", st == 200, st)
st, hd, _ = req("GET", "/nowhere")
check("an unknown path is a 404 with Content-Length", st == 404 and hd.get("Content-Length") == "0", (st, hd))

# ---- the token file ---------------------------------------------------------
check("the token is kept beside the ledger, owner-only",
      web.TOKEN_FILE.exists() and (web.TOKEN_FILE.stat().st_mode & 0o777) == 0o600,
      oct(web.TOKEN_FILE.stat().st_mode & 0o777) if web.TOKEN_FILE.exists() else "missing")
check("the file holds the token the server is using",
      web.TOKEN_FILE.read_text().strip() == web.TOKEN)

# ---- credentials stop at a redirect off the host ---------------------------
# urllib follows a 302 anywhere and re-sends the request headers with it, so
# an Alpaca key or the X cookie would go to whatever host a redirect named.
from app import netsafe                                 # noqa: E402
from http.server import BaseHTTPRequestHandler          # noqa: E402
import urllib.error                                     # noqa: E402
import urllib.request                                   # noqa: E402


class _Redirector(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/away":
            self.send_response(302); self.send_header("Location", "http://example.invalid/steal")
        elif self.path == "/home":
            self.send_response(302); self.send_header("Location", f"http://127.0.0.1:{RPORT}/landed")
        else:
            self.send_response(200)
        self.send_header("Content-Length", "0"); self.end_headers()


rsrv = ThreadingHTTPServer(("127.0.0.1", 0), _Redirector)
RPORT = rsrv.server_address[1]
threading.Thread(target=rsrv.serve_forever, daemon=True).start()
try:
    netsafe.urlopen(urllib.request.Request(f"http://127.0.0.1:{RPORT}/away", headers={"X-Key": "k"}), timeout=5)
    check("a redirect to another host is refused", False, "followed")
except urllib.error.HTTPError as exc:
    check("a redirect to another host is refused", exc.code == 302 and "refused" in str(exc.reason), exc)
except Exception as exc:                                     # noqa: BLE001
    check("a redirect to another host is refused", False, repr(exc))
try:
    with netsafe.urlopen(urllib.request.Request(f"http://127.0.0.1:{RPORT}/home"), timeout=5) as r:
        check("a redirect on the same host is followed", r.status == 200 and r.url.endswith("/landed"), r.url)
except Exception as exc:                                     # noqa: BLE001
    check("a redirect on the same host is followed", False, repr(exc))
rsrv.shutdown()

server.shutdown()
failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -> {detail}"))
print(f"\n  {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
