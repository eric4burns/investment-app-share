"""Trades from Fidelity's confirmation emails, the morning after.

Fidelity emails "Your trade confirmation is available" the day after a fill.
The message names the account, the action, the security and the price — not
the number of shares. The statement that carries the shares arrives weeks
later. So the email is the earliest record the app can have that a trade
happened, and it is enough to put the decision in the journal on the day it
was made, price and all, with the shares marked pending until the statement
confirms them.

Read over IMAP with the same app password as the Amazon check (`gmail` in
config.json). Only Fidelity confirmation messages are read; only the date,
account tail, action, security name and price are kept.

    python3 -m app.mailtrades            # read, store, journal, print
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import re
import ssl
import sys
from datetime import date, datetime, timedelta

from . import config, journal
from .amazon import _text, _subject, sender_is

SUBJECT = re.compile(r"trade confirmation", re.I)
ACCOUNT = re.compile(r"Account:\s*X*(\d{4,5})")
# The table is flattened by the plain-text rendering: "ActionSecurityPrice"
# then one run per fill, "SOLDSTRIVE INC CL A COM26.4800", each fill twice
# (the email renders the row for two layouts). Price is 2–4 decimals.
FILL = re.compile(r"(BOUGHT|SOLD)\s*([A-Z][A-Z0-9 .&'/#-]+?)\s*(\d+\.\d{2,4})(?=BOUGHT|SOLD|\s|$)")

SCHEMA = """
CREATE TABLE IF NOT EXISTS email_trades (
    id INTEGER PRIMARY KEY,
    message_ref TEXT NOT NULL UNIQUE,
    email_date TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    account TEXT,
    action TEXT NOT NULL,
    security_name TEXT NOT NULL,
    symbol TEXT,
    price REAL,
    recorded_at TEXT NOT NULL
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def previous_trading_day(d: date) -> date:
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def parse_message(raw: bytes) -> list[dict]:
    """One confirmation email -> one record per distinct fill."""
    msg = email.message_from_bytes(raw)
    subject = _subject(msg)
    if not sender_is(msg, "fidelity.com") or not SUBJECT.search(subject):
        return []
    text = _text(msg)
    when = email.utils.parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    email_day = when.date() if when else date.today()
    acct = ACCOUNT.search(text)
    ref = (msg.get("Message-ID") or "").strip() or (re.search(r"EMAIL REF#\s*([\w.-]+)", text) or [None, f"{email_day}|{subject}"])[1]
    seen, out = set(), []
    for m in FILL.finditer(text):
        action, name, price = m.group(1), m.group(2).strip(), float(m.group(3))
        key = (action, name, price)
        if key in seen:
            continue
        seen.add(key)
        out.append({"message_ref": f"{ref}#{len(out)}", "email_date": email_day.isoformat(),
                    "trade_date": previous_trading_day(email_day).isoformat(),
                    "account": acct.group(1) if acct else None,
                    "action": "sell" if action == "SOLD" else "buy",
                    "security_name": name, "price": price})
    return out


def fetch(user: str, app_password: str, since_days: int = 45, host: str = "imap.gmail.com") -> list[dict]:
    app_password = re.sub(r"\s", "", app_password.replace("\xa0", ""))
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    out = []
    with imaplib.IMAP4_SSL(host, ssl_context=ssl.create_default_context()) as m:
        m.login(user.strip(), app_password)
        m.select("INBOX", readonly=True)
        typ, data = m.search(None, f'(FROM "fidelity" SUBJECT "trade confirmation" SINCE {since})')
        if typ != "OK":
            return out
        for i in data[0].split()[-200:]:
            typ, parts = m.fetch(i, "(RFC822)")
            if typ != "OK":
                continue
            for part in parts:
                if isinstance(part, tuple):
                    out.extend(parse_message(part[1]))
    return out


def symbol_for(conn, name: str) -> str | None:
    """The ticker whose statement name matches the email's security name.

    The statements name securities the same way the emails do ("STRIVE INC CL
    A COM"), so an exact match on the securities table is the first try; then
    the longest securities name the email name starts with; then the reverse."""
    name = re.sub(r"\s+", " ", name.upper()).strip()
    rows = [(r["symbol"], re.sub(r"\s+", " ", (r["name"] or "").upper()).strip())
            for r in conn.execute("SELECT symbol, name FROM securities WHERE name IS NOT NULL AND symbol NOT LIKE 'CUSIP:%'")]
    for sym, n in rows:
        if n == name:
            return sym
    best = None
    for sym, n in rows:
        if n and (name.startswith(n) or n.startswith(name)) and (best is None or len(n) > len(best[1])):
            best = (sym, n)
    return best[0] if best else None


def store(conn, records: list[dict]) -> dict:
    """Keep the fills, and put each new one in the journal as a trade made."""
    ensure_schema(conn)
    journal.ensure_schema(conn)
    new, unmapped = [], []
    now = datetime.now().isoformat(timespec="seconds")
    for r in records:
        sym = symbol_for(conn, r["security_name"])
        cur = conn.execute("""INSERT OR IGNORE INTO email_trades
                              (message_ref, email_date, trade_date, account, action, security_name, symbol, price, recorded_at)
                              VALUES (?,?,?,?,?,?,?,?,?)""",
                           (r["message_ref"], r["email_date"], r["trade_date"], r.get("account"), r["action"],
                            r["security_name"], sym, r["price"], now))
        if cur.rowcount:
            new.append({**r, "symbol": sym})
            if sym:
                # The statement, when it lands, re-derives this row with the
                # shares and, for a sale, whether it was a trim; until then
                # the email's action and price stand.
                journal.record(conn, r["trade_date"], sym, "trade", r["action"], price=r["price"],
                               rationale=f"from Fidelity's confirmation email of {r['email_date']}; "
                                         f"shares pending the statement")
            else:
                unmapped.append(r["security_name"])
    conn.commit()
    return {"new": new, "unmapped": unmapped}


def confirmed(conn, rows: list[dict]) -> list[dict]:
    """Mark each email trade with whether the ledger now holds the statement's transaction."""
    out = []
    for r in rows:
        hit = None
        if r.get("symbol"):
            hit = conn.execute("""SELECT t.quantity FROM transactions t JOIN securities s ON s.id = t.security_id
                                  WHERE s.symbol = ? AND t.txn_date = ? AND t.kind = ?""",
                               (r["symbol"], r["trade_date"], r["action"])).fetchone()
        out.append({**r, "confirmed": bool(hit), "quantity": (hit["quantity"] if hit else None)})
    return out


def recent(conn, days: int = 60) -> list[dict]:
    ensure_schema(conn)
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = [dict(r) for r in conn.execute("SELECT * FROM email_trades WHERE trade_date >= ? ORDER BY trade_date DESC, id DESC", (since,))]
    return confirmed(conn, rows)


def sync(conn) -> dict:
    g = (config.load().get("gmail") or {})
    if not (g.get("user") and g.get("app_password")):
        return {"configured": False, "note": "Gmail is not connected (config.json, gmail) — SETUP.md, Amazon returns."}
    try:
        recs = fetch(g["user"], g["app_password"], int(g.get("since_days") or 45))
    except (imaplib.IMAP4.error, OSError) as exc:
        return {"configured": True, "error": f"Could not read the mailbox: {str(exc)[:120]}"}
    r = store(conn, recs)
    return {"configured": True, "emails_fills": len(recs), **r}


def main(argv=None) -> int:
    from . import ledger
    conn = ledger.connect()
    r = sync(conn)
    if not r.get("configured"):
        print(r["note"]); return 1
    if r.get("error"):
        print(r["error"]); return 1
    print(f"{r['emails_fills']} fills in confirmation emails; {len(r['new'])} new")
    for t in r["new"]:
        print(f"  {t['trade_date']}  {t['action']:4s} {t['symbol'] or '?':6s} @ {t['price']:.4f}  ({t['security_name']})")
    for u in r["unmapped"]:
        print(f"  could not map to a ticker: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
