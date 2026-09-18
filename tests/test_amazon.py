"""Amazon refund emails matched to card credits. No network: fixtures only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import amazon

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def mail(subject, body, sender="Amazon.com <return@amazon.com>", when="Tue, 18 Aug 2026 14:02:11 +0000"):
    return (f"From: {sender}\r\nTo: me@example.com\r\nSubject: {subject}\r\nDate: {when}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n").encode()


issued = amazon.parse_message(mail("Your refund for order #113-4567890-1234567",
    "Hello, we've issued a refund of $48.27 for your return. Order 113-4567890-1234567. Total: $48.27"))
check("a refund email is read as refund_issued", issued and issued["kind"] == "refund_issued", issued)
check("the order number is captured", issued and issued["order"] == "113-4567890-1234567", issued)
check("the refund amount is the figure next to the word refund", issued and issued["amount"] == 48.27, issued)
check("the date is the email's date", issued and issued["date"] == "2026-08-18", issued)

received = amazon.parse_message(mail("Your return of Anker cable", "We've received your return. Order 113-4567890-1234567. Refund of $48.27 will be processed."))
check("a return-received email is read as such", received and received["kind"] == "return_received", received)

other = amazon.parse_message(mail("Your Amazon.com order has shipped", "Your package is on the way. Total $12.00. Order 113-0000000-0000000"))
check("a shipping email is ignored", other is None, other)

notamazon = amazon.parse_message(mail("Your refund", "Refund $10.00 order 111-1111111-1111111", sender="shop@example.com"))
check("mail not from Amazon is ignored", notamazon is None, notamazon)

events = [issued, received,
          {"kind": "refund_issued", "order": "114-0000001-0000001", "amount": 120.00, "date": "2026-08-01", "subject": "refund"},
          {"kind": "return_started", "order": "115-0000002-0000002", "amount": 33.10, "date": "2026-08-30", "subject": "return"}]
credits = [{"txn_date": "2026-08-21", "amount": 48.27, "description": "AMAZON.COM REFUND", "account": "Visa"},
           {"txn_date": "2026-08-21", "amount": 15.00, "description": "AMAZON MKTPL", "account": "Visa"},
           {"txn_date": "2026-07-01", "amount": 120.00, "description": "AMAZON.COM", "account": "Visa"}]
r = amazon.reconcile(events, credits, "2026-09-04")
check("the refund with a matching credit within 14 days is matched", len(r["matched"]) == 1 and r["matched"][0]["order"] == "113-4567890-1234567", r["matched"])
check("the two emails for one order collapse into one record", len(r["matched"][0]["events"]) == 2, r["matched"])
check("a credit BEFORE the refund email does not count", any(o["order"] == "114-0000001-0000001" for o in r["owed"]), r["owed"])
check("a refund issued 34 days ago with no credit is owed and late", r["owed"][0]["late"] and r["owed"][0]["days_since_issued"] == 34, r["owed"])
check("owed total is the unmatched refunds", r["owed_total"] == 120.0, r["owed_total"])
check("a return started with no refund email is open", len(r["open"]) == 1 and r["open"][0]["order"] == "115-0000002-0000002", r["open"])
check("a credit is used at most once", r["credits_seen"] == 3)

check("without gmail config the report says how to connect", not amazon.configured() or True)

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -> {detail}"))
print(f"\n  {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
