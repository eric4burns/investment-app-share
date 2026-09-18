"""Fidelity confirmation emails -> the morning-after trade record. Fixtures only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import mailtrades

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


# The shape of a real confirmation with every personal detail replaced: the
# name, the account tail and the reference are invented.
BODY = ("Fidelity Investments, Inc.\n\nYour trade confirmation is available.\n\n JANE EXAMPLE\n\n"
        "Your trade confirmation is available online\n\nAccount: XXXXX1234\n"
        "ActionSecurityPriceSOLDSTRIVE INC CL A COM26.4800SOLDSTRIVE INC CL A COM26.4800\n\n"
        "Full details of all transactions are ready for your review.\n\nEMAIL REF# 00000000-0000.0000000\n")


def mail(body, subject="Your trade confirmation is available", sender="Fidelity.Investments@mail.fidelity.com",
         when="Sat, 05 Sep 2026 10:26:28 +0000"):
    return (f"From: {sender}\r\nTo: me@example.com\r\nSubject: {subject}\r\nDate: {when}\r\n"
            f"Message-ID: <abc123@mail.fidelity.com>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n").encode()


r = mailtrades.parse_message(mail(BODY))
check("one fill is read from the duplicated row", len(r) == 1, r)
check("the action is a sell", r and r[0]["action"] == "sell", r)
check("the security name is captured", r and r[0]["security_name"] == "STRIVE INC CL A COM", r)
check("the price is captured to four decimals", r and r[0]["price"] == 26.48, r)
check("the account tail is captured", r and r[0]["account"] == "1234", r)
check("a Saturday email means a Friday trade", r and r[0]["trade_date"] == "2026-09-04", r)

two = BODY.replace("SOLDSTRIVE INC CL A COM26.4800SOLDSTRIVE INC CL A COM26.4800",
                   "BOUGHTIREN LIMITED COM NPV44.6800BOUGHTIREN LIMITED COM NPV44.6800SOLDTEMPUS AI INC CL A64.6200SOLDTEMPUS AI INC CL A64.6200")
r2 = mailtrades.parse_message(mail(two))
check("two fills in one email are two records", len(r2) == 2 and r2[0]["action"] == "buy" and r2[1]["action"] == "sell", r2)
check("each record has its own message reference", r2 and r2[0]["message_ref"] != r2[1]["message_ref"], r2)

check("a Fidelity email that is not a confirmation is ignored",
      mailtrades.parse_message(mail("Deposit received", subject="Fidelity Alerts: Deposit Received")) == [])
check("a confirmation-looking email from elsewhere is ignored",
      mailtrades.parse_message(mail(BODY, sender="phish@example.com")) == [])
# The old check was `"fidelity" in sender`, which a display name satisfies.
check("a spoofed sender with Fidelity in the display name only is ignored",
      mailtrades.parse_message(mail(BODY, sender="Fidelity Investments <alerts@fidelity-secure.example>")) == [])
check("a lookalike domain that merely ends in fidelity.com is ignored",
      mailtrades.parse_message(mail(BODY, sender="alerts@notfidelity.com")) == [])
check("a Fidelity subdomain is accepted",
      len(mailtrades.parse_message(mail(BODY, sender="Fidelity <Fidelity.Investments@mail.fidelity.com>"))) == 1)

check("a Monday email means a Friday trade", mailtrades.previous_trading_day(__import__("datetime").date(2026, 9, 7)).isoformat() == "2026-09-04")

# Symbol mapping against a small securities table.
import sqlite3
conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
conn.execute("CREATE TABLE securities (id INTEGER PRIMARY KEY, symbol TEXT, name TEXT, kind TEXT)")
conn.executemany("INSERT INTO securities (symbol, name, kind) VALUES (?,?,?)", [
    ("ASST", "STRIVE INC CL A COM", "equity"), ("CUSIP:862945102", "STRIVE INC CL A COM 1 FOR 20 R/S", "equity"),
    ("IREN", "IREN LIMITED COM NPV", "equity"), ("CRDO", "CREDO TECHNOLOGY GROUP HOLDING LTD COM USD0.00005", "equity")])
check("an exact statement name maps to its ticker", mailtrades.symbol_for(conn, "STRIVE INC CL A COM") == "ASST")
check("a CUSIP placeholder never wins", mailtrades.symbol_for(conn, "STRIVE INC CL A COM 1 FOR 20 R/S") != "CUSIP:862945102")
check("a shorter email name maps by prefix", mailtrades.symbol_for(conn, "CREDO TECHNOLOGY GROUP HOLDING LTD") == "CRDO")
check("an unknown name maps to nothing", mailtrades.symbol_for(conn, "ACME WIDGETS") is None)

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -> {detail}"))
print(f"\n  {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
