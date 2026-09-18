"""Amazon returns: did the refund actually arrive?

Amazon writes to the mailbox on the account when a return is started, when
the item is received, and when the refund is issued. The card statement shows
the refund as a credit days later — or does not. Checking that by hand means
remembering every return and reading two places, which is exactly the kind of
thing that gets forgotten. So: read the refund emails, read the card credits,
match them, and list what is still owed.

Mail is read over IMAP with an app password the user creates in their Google
account and puts in config.json themselves (`gmail.user`, `gmail.app_password`).
The app never asks for the account password, and nothing here sends mail.
Only messages from amazon.com senders are fetched, and only the fields below
are kept — order number, date, amount, subject — never the message text.

    python3 -m app.amazon            # print the report
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import re
import ssl
import sys
from datetime import date, datetime, timedelta
from email.header import decode_header
from html import unescape

from . import config

REFUND_SUBJECT = re.compile(r"refund|return", re.I)
ORDER = re.compile(r"\b(\d{3}-\d{7}-\d{7})\b")
MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2})")
ISSUED = re.compile(r"refund (?:has been )?(?:issued|processed|initiated|is on its way)|we've issued|we have issued|your refund", re.I)
RECEIVED = re.compile(r"return (?:has been )?received|we(?:'ve| have) received your return|received your return", re.I)
STARTED = re.compile(r"return (?:request|started|authorized|label)|start(?:ed)? your return|drop.?off", re.I)
MATCH_DAYS = 14
LATE_DAYS = 10

AMAZON_CREDIT = re.compile(r"AMAZON|AMZN", re.I)


def _text(msg) -> str:
    parts = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/plain", "text/html"):
            continue
        try:
            body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
        except Exception:                                      # noqa: BLE001
            continue
        if ct == "text/html":
            body = re.sub(r"(?is)<(script|style).*?</\1>", " ", body)
            body = re.sub(r"<[^>]+>", " ", body)
        parts.append(unescape(body))
    return re.sub(r"\s+", " ", " ".join(parts))


def _subject(msg) -> str:
    out = []
    for frag, enc in decode_header(msg.get("Subject") or ""):
        out.append(frag.decode(enc or "utf-8", "ignore") if isinstance(frag, bytes) else frag)
    return "".join(out)


def sender_is(msg, domain: str) -> bool:
    """Whether the From address is at `domain` or a subdomain of it.

    A substring test on the whole header ("amazon" in sender) was satisfied by
    a display name — `From: Amazon Refunds <anyone@example.com>` — so the
    sender check was a formality. The address part is what a mail server
    authenticates, and only its domain is compared, so `return@amazon.com` and
    `no-reply@mail.fidelity.com` pass while `amazon@phish.example` does not.
    """
    addr = email.utils.parseaddr(msg.get("From") or "")[1].lower()
    host = addr.rpartition("@")[2]
    return bool(host) and (host == domain or host.endswith("." + domain))


def parse_message(raw: bytes) -> dict | None:
    """One Amazon email -> {kind, order, amount, date, subject}, or None."""
    msg = email.message_from_bytes(raw)
    subject = _subject(msg)
    if not sender_is(msg, "amazon.com"):
        return None
    text = _text(msg)
    blob = subject + " " + text
    if ISSUED.search(subject) or (ISSUED.search(text) and REFUND_SUBJECT.search(subject)):
        kind = "refund_issued"
    elif RECEIVED.search(blob):
        kind = "return_received"
    elif STARTED.search(blob) and REFUND_SUBJECT.search(subject):
        kind = "return_started"
    else:
        return None
    order = ORDER.search(blob)
    amounts = [float(m.replace(",", "")) for m in MONEY.findall(blob)]
    # The refund amount is the figure nearest the word "refund"; failing that
    # the largest figure in the message (the total, not a line item).
    amount = None
    near = re.search(r"refund[^$]{0,80}\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2})", blob, re.I)
    if near:
        amount = float(near.group(1).replace(",", ""))
    elif amounts:
        amount = max(amounts)
    when = email.utils.parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    return {"kind": kind, "order": order.group(1) if order else None, "amount": amount,
            "date": (when.date().isoformat() if when else None), "subject": subject[:120]}


def fetch(user: str, app_password: str, since_days: int = 120, host: str = "imap.gmail.com") -> list[dict]:
    """Amazon return and refund emails from the last `since_days`."""
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    out = []
    # Google shows the app password in four groups separated by spaces, and an
    # editor turns those into non-breaking spaces; IMAP wants the sixteen
    # characters alone.
    app_password = re.sub(r"\s", "", app_password.replace("\xa0", ""))
    # An explicit default context: the class's own default verified nothing
    # before Python 3.13, and the login below is the Gmail app password.
    with imaplib.IMAP4_SSL(host, ssl_context=ssl.create_default_context()) as m:
        m.login(user.strip(), app_password)
        m.select("INBOX", readonly=True)
        typ, data = m.search(None, f'(FROM "amazon" SINCE {since})')
        if typ != "OK":
            return out
        ids = data[0].split()
        for i in ids[-400:]:
            typ, parts = m.fetch(i, "(RFC822)")
            if typ != "OK":
                continue
            for part in parts:
                if isinstance(part, tuple):
                    rec = parse_message(part[1])
                    if rec:
                        out.append(rec)
    return out


def reconcile(events: list[dict], credits: list[dict], asof: str) -> dict:
    """Match refund emails to card credits.

    `credits` are ledger rows with txn_date, amount (positive), description.
    A refund matches a credit of the same amount within MATCH_DAYS after the
    email; each credit is used once. A refund with no credit after LATE_DAYS
    is what the user needs to chase; a return received or started with no
    refund email is listed as still open."""
    today = date.fromisoformat(asof)
    pool = [c for c in credits if float(c.get("amount") or 0) > 0 and AMAZON_CREDIT.search(c.get("description") or "")]
    used = set()
    by_order: dict[str, dict] = {}
    for e in sorted(events, key=lambda e: e.get("date") or ""):
        key = e.get("order") or f"{e.get('date')}|{e.get('amount')}"
        rec = by_order.setdefault(key, {"order": e.get("order"), "events": [], "amount": None, "issued": None})
        rec["events"].append(e)
        if e.get("amount") and (rec["amount"] is None or e["kind"] == "refund_issued"):
            rec["amount"] = e["amount"]
        if e["kind"] == "refund_issued":
            rec["issued"] = e.get("date")
    matched, owed, open_ = [], [], []
    for key, rec in by_order.items():
        if rec["issued"] and rec["amount"]:
            d0 = date.fromisoformat(rec["issued"])
            hit = None
            for i, c in enumerate(pool):
                if i in used:
                    continue
                cd = date.fromisoformat(c["txn_date"][:10])
                if abs(float(c["amount"]) - rec["amount"]) <= 0.01 and 0 <= (cd - d0).days <= MATCH_DAYS:
                    hit = (i, c)
                    break
            if hit:
                used.add(hit[0])
                matched.append({**rec, "credit_date": hit[1]["txn_date"][:10], "account": hit[1].get("account")})
            else:
                days = (today - d0).days
                owed.append({**rec, "days_since_issued": days, "late": days > LATE_DAYS})
        else:
            open_.append(rec)
    owed.sort(key=lambda r: -r["days_since_issued"])
    return {"matched": matched, "owed": owed, "open": open_,
            "owed_total": round(sum(r["amount"] or 0 for r in owed), 2),
            "credits_seen": len(pool), "asof": asof}


def configured() -> dict | None:
    g = (config.load().get("gmail") or {})
    if g.get("user") and g.get("app_password"):
        return g
    return None


def report(conn, asof: str | None = None) -> dict:
    from . import budget
    asof = asof or date.today().isoformat()
    g = configured()
    if not g:
        return {"configured": False,
                "note": "Not connected. Put the Gmail address and an app password under \"gmail\" in config.json — SETUP.md, Amazon returns."}
    try:
        events = fetch(g["user"], g["app_password"], int(g.get("since_days") or 120))
    except (imaplib.IMAP4.error, OSError) as exc:
        return {"configured": True, "error": f"Could not read the mailbox: {str(exc)[:120]}"}
    since = (date.fromisoformat(asof) - timedelta(days=int(g.get("since_days") or 120) + MATCH_DAYS)).isoformat()
    txns = budget.load_spending(conn, since, asof)
    out = reconcile(events, txns, asof)
    out.update({"configured": True, "emails": len(events)})
    return out


def main(argv=None) -> int:
    from . import ledger
    conn = ledger.connect()
    r = report(conn)
    if not r.get("configured"):
        print(r["note"]); return 1
    if r.get("error"):
        print(r["error"]); return 1
    print(f"{r['emails']} Amazon return/refund emails; {len(r['matched'])} refunds matched to card credits; "
          f"{len(r['owed'])} owed (${r['owed_total']:.2f}); {len(r['open'])} returns without a refund yet")
    for o in r["owed"]:
        print(f"  OWED  {o['order'] or '?'}  ${o['amount']:.2f}  issued {o['issued']}  {o['days_since_issued']} days ago{'  LATE' if o['late'] else ''}")
    for o in r["open"]:
        print(f"  open  {o['order'] or '?'}  ${o['amount'] or 0:.2f}  {o['events'][-1]['kind']} {o['events'][-1]['date']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
