"""The Value Trader's Patreon posts, read from the notification emails.

Each post arrives as an email from creator.patreon.com: a subject that names
the ticker and the topic ("$ONDS - BUY LEVEL", "$IREN - IS IT CHEAP?"), a
one-line teaser, and the post's chart as an image hosted on Patreon's CDN
with a long-lived token in the URL. The levels are drawn on the chart, not
written in the text, so this module cannot read them; what it can do is put
the chart, dated, beside the app's levels on the name — the same place the
other followed authors' zones sit (D68) — and grade the subject's call in
the journal when the subject makes one (BUY LEVEL, TOP PICK, SHORT, SELL).

Read-only IMAP, same mailbox settings as the Fidelity confirmations. Images
are saved once under data/valuetrader/ (never versioned) and served back by
the app; nothing here is ever posted anywhere.

    python3 -m app.valuetrader          # read, store, journal, print
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import re
import ssl
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from . import config
from .amazon import _subject

AUTHOR = "The Value Trader (Patreon)"
SENDER = "patreon.com"
FROM_QUERY = '(FROM "value trader")'
IMAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "valuetrader"
TICKER = re.compile(r"\$([A-Z]{1,6})\b")
BUY_WORDS = re.compile(r"\bBUY\b|\bTOP PICK\b|\bLONG\b|\bACCUMULAT", re.I)
SELL_WORDS = re.compile(r"\bSELL\b|\bSHORT\b|\bTRIM\b|\bTAKE PROFIT|\bTOP\b(?! PICK)", re.I)
NOISE = re.compile(r"earnings calendar|free trial|portfolio|sizing|cash position|basic ewt|support - video", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS valuetrader_posts (
    id INTEGER PRIMARY KEY,
    message_ref TEXT NOT NULL UNIQUE,
    post_id TEXT,
    email_date TEXT NOT NULL,
    subject TEXT NOT NULL,
    symbols TEXT,                 -- comma separated
    action TEXT,                  -- buy | sell | NULL
    teaser TEXT,
    post_url TEXT,
    image_url TEXT,
    image_path TEXT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _html(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
            except Exception:                                  # noqa: BLE001
                return ""
    return ""


def parse_html(h: str) -> dict:
    """The teaser, the post link and the post's own image out of the email body."""
    body = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    text = re.sub(r"(?s)<br\s*/?>|</p>|</div>|</tr>", "\n", body)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    import html as _h
    text = _h.unescape(text)
    text = text.replace("͏", " ").replace("­", " ")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    # the teaser is the first sentence-like line after the header block, before the footer
    skip = re.compile(r"^(view in app|share|©|privacy|\d+$|the value trader$|email was sent|unsubscribe|download the app|\w{3} \d{1,2}, \d{4}$)", re.I)
    end = re.compile(r"^(did you like this post|© \d{4}|\d+ townsend street|san francisco, ca)", re.I)
    teaser = []
    started = False
    for ln in lines:
        if re.match(r"^View in app$", ln, re.I):
            started = True; continue
        if not started:
            continue
        if end.match(ln):
            break                # the footer: nothing after it is the post
        if skip.match(ln):
            continue
        teaser.append(ln)
    post = re.search(r'href="(https://www\.patreon\.com/TheValueTrader/posts/[^"?]+)', h)
    img = re.search(r'src="(https://c\d+\.patreonusercontent\.com/[^"]*?/p/post/(\d+)/[^"]+)"', h)
    return {"teaser": " ".join(teaser)[:600], "post_url": post.group(1) if post else None,
            "image_url": img.group(1).replace("&amp;", "&") if img else None, "post_id": img.group(2) if img else None}


def classify(subject: str) -> tuple[list[str], str | None]:
    syms = [s for s in TICKER.findall(subject) if s not in ("BTC", "ETH")] + [s for s in TICKER.findall(subject) if s in ("BTC", "ETH")]
    if NOISE.search(subject) and not syms:
        return [], None
    action = None
    if BUY_WORDS.search(subject):
        action = "buy"
    elif SELL_WORDS.search(subject):
        action = "sell"
    return syms, action


def parse_message(raw: bytes) -> dict | None:
    msg = email.message_from_bytes(raw)
    if SENDER not in (msg.get("From") or "").lower():
        return None
    subject = _subject(msg).strip()
    when = email.utils.parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    day = (when.date() if when else date.today()).isoformat()
    syms, action = classify(subject)
    body = parse_html(_html(msg))
    ref = (msg.get("Message-ID") or "").strip() or f"{day}|{subject}"
    return {"message_ref": ref, "post_id": body["post_id"], "email_date": day, "subject": subject,
            "symbols": syms, "action": action, "teaser": body["teaser"], "post_url": body["post_url"],
            "image_url": body["image_url"]}


def fetch(user: str, app_password: str, since_days: int = 365, host: str = "imap.gmail.com") -> list[dict]:
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    pw = re.sub(r"\s+", "", app_password or "")
    out = []
    with imaplib.IMAP4_SSL(host, ssl_context=ssl.create_default_context()) as m:
        m.login(user, pw)
        m.select("INBOX", readonly=True)
        typ, data = m.search(None, f'{FROM_QUERY[:-1]} SINCE {since})')
        for num in (data[0].split() if typ == "OK" and data and data[0] else []):
            typ, d = m.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not d or not d[0]:
                continue
            rec = parse_message(d[0][1])
            if rec:
                out.append(rec)
    return out


def save_image(url: str, post_id: str) -> str | None:
    """Download the chart once. Returns the local path, or None."""
    if not url or not post_id:
        return None
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_DIR / f"{post_id}.png"
    if path.exists():
        return str(path)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        if len(data) < 1000:
            return None
        path.write_bytes(data)
        return str(path)
    except Exception:                                          # noqa: BLE001
        return None


def store(conn, records: list[dict], download: bool = True) -> dict:
    """Insert new posts, fetch their charts, and journal the subject's call."""
    from . import journal, prices
    ensure_schema(conn)
    new, journaled = [], 0
    for r in records:
        exists = conn.execute("SELECT id, image_path FROM valuetrader_posts WHERE message_ref=?", (r["message_ref"],)).fetchone()
        img = exists["image_path"] if exists else None
        if download and not img:
            img = save_image(r["image_url"], r["post_id"])
        if exists:
            if img and not exists["image_path"]:
                conn.execute("UPDATE valuetrader_posts SET image_path=? WHERE id=?", (img, exists["id"]))
            continue
        conn.execute("""INSERT INTO valuetrader_posts (message_ref, post_id, email_date, subject, symbols, action, teaser, post_url, image_url, image_path)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (r["message_ref"], r["post_id"], r["email_date"], r["subject"], ",".join(r["symbols"]), r["action"],
                      r["teaser"], r["post_url"], r["image_url"], img))
        new.append(r)
        if r["action"] and r["symbols"]:
            sym = r["symbols"][0]
            px = None
            try:
                series = prices.load_series(conn, sym)
                dates = [d for d in sorted(series) if d <= r["email_date"]]
                px = series[dates[-1]] if dates else None
            except Exception:                                  # noqa: BLE001
                px = None
            journal.record(conn, r["email_date"], sym, "outside", r["action"], price=px,
                           rationale=f"{r['subject']} — {r['teaser'][:140]}" if r["teaser"] else r["subject"], author=AUTHOR)
            journaled += 1
    conn.commit()
    return {"new": new, "journaled": journaled}


def recent(conn, days: int = 120) -> list[dict]:
    ensure_schema(conn)
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = [dict(r) for r in conn.execute("SELECT * FROM valuetrader_posts WHERE email_date >= ? ORDER BY email_date DESC, id DESC", (since,))]
    for r in rows:
        r["symbols"] = [s for s in (r["symbols"] or "").split(",") if s]
        r["has_image"] = bool(r["image_path"] and Path(r["image_path"]).exists())
    return rows


def by_symbol(conn, days: int = 120) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in recent(conn, days):
        for s in r["symbols"]:
            out.setdefault(s, []).append(r)
    return out


def image_bytes(conn, post_id: str) -> bytes | None:
    ensure_schema(conn)
    row = conn.execute("SELECT image_path FROM valuetrader_posts WHERE post_id=?", (post_id,)).fetchone()
    if not row or not row["image_path"]:
        return None
    p = Path(row["image_path"])
    if not p.exists() or p.parent != IMAGE_DIR:
        return None
    return p.read_bytes()


def sync(conn) -> dict:
    g = (config.load().get("gmail") or {})
    if not (g.get("user") and g.get("app_password")):
        return {"configured": False, "note": "Gmail is not connected (config.json, gmail) — SETUP.md."}
    try:
        recs = fetch(g["user"], g["app_password"], int(g.get("valuetrader_days") or 365))
    except (imaplib.IMAP4.error, OSError) as exc:
        return {"configured": True, "error": f"Could not read the mailbox: {str(exc)[:120]}"}
    r = store(conn, recs)
    return {"configured": True, "emails": len(recs), "new": len(r["new"]), "journaled": r["journaled"]}


def main(argv=None) -> int:
    from . import ledger
    conn = ledger.connect()
    r = sync(conn)
    if not r.get("configured"):
        print(r["note"]); return 1
    if r.get("error"):
        print(r["error"]); return 1
    print(f"{r['emails']} Value Trader emails; {r['new']} new, {r['journaled']} journaled")
    for p in recent(conn, 400)[:40]:
        print(f"  {p['email_date']}  {p['subject'][:40]:40s} {','.join(p['symbols']) or '-':8s} {p['action'] or '-':4s} {'chart' if p['has_image'] else 'no image'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
