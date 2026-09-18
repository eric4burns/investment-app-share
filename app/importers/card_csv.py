"""Credit-card CSV exports, from whichever issuer produced them.

Every card issuer exports a CSV and no two agree on the format. Rather than one
importer per issuer — which needs a new one written every time a card is opened
— this reads the header and works out which column is which.

The part that actually matters is the SIGN, because issuers disagree about it in
a way that silently inverts the whole file:

    Chase        purchases negative, payments positive
    Amex         purchases POSITIVE, payments negative
    Discover     purchases POSITIVE, payments negative
    Capital One  no signs at all — separate Debit and Credit columns
    Citi         separate Debit and Credit columns

Guess wrong and a year of spending is imported as a year of income. Nothing else
in the file gives it away: the amounts, dates and descriptions are all perfectly
valid either way, and the total just comes out backwards.

So the sign is proved rather than assumed. Every card statement contains at
least one payment — that is what a card is for — and a payment moves money INTO
the card account, so whichever sign the payment rows carry is the sign that
means "money in". That single observation fixes the convention for the file. If
there is no payment row, the fallback is that purchases outnumber payments by
count, which is true of any real statement but is a weaker claim, so the import
reports which of the two it used rather than leaving it to be discovered later.

In this ledger's convention, as everywhere else: amount is the cash impact, so a
purchase is negative and a payment is positive.
"""
from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter
from pathlib import Path

from ..ledger import insert_transaction

SOURCE = "card_csv"

# Header names seen across the major issuers, lowercased. Order matters: the
# first match wins, so the transaction date beats the posting date — the day you
# spent it is the day it belongs to.
DATE_COLUMNS = ("transaction date", "trans. date", "trans date", "date",
                "posted date", "post date", "posting date")
DESC_COLUMNS = ("description", "payee", "merchant", "name", "transaction",
                "details", "extended details")
AMOUNT_COLUMNS = ("amount", "transaction amount", "amount (usd)")
DEBIT_COLUMNS = ("debit", "withdrawal", "charges", "charge")
CREDIT_COLUMNS = ("credit", "deposit", "payments", "payment")

# A payment lands on every statement and is the one row whose direction is not
# in doubt, which is what makes it usable as the reference for the whole file.
PAYMENT_PATTERNS = re.compile(
    r"(payment\s*(-\s*)?thank\s*you|thank\s*you|autopay|auto\s*pay|"
    r"online\s*payment|mobile\s*payment|electronic\s*payment|payment\s*received|"
    r"pymt|direct\s*debit|directpay|internet\s*payment|bank\s*payment|"
    r"payment\s*-\s*|epay|ach\s*pmt|^payment\b|\bpayment\b)", re.I)

# A refund is money in too, but it is NOT a payment, and treating it as the
# reference would work only by accident — it happens to have the same sign.
REFUND_PATTERNS = re.compile(r"(refund|return|credit\s*adjustment|reversal)", re.I)


def _pick(header: list[str], wanted: tuple[str, ...]) -> str | None:
    lower = {h.strip().lower(): h for h in header if h}
    for want in wanted:
        if want in lower:
            return lower[want]
    return None


def sniff(header: list[str]) -> dict:
    """Which column is the date, the description, and the money."""
    date = _pick(header, DATE_COLUMNS)
    desc = _pick(header, DESC_COLUMNS)
    amount = _pick(header, AMOUNT_COLUMNS)
    debit = _pick(header, DEBIT_COLUMNS)
    credit = _pick(header, CREDIT_COLUMNS)
    return {"date": date, "description": desc, "amount": amount,
            "debit": debit, "credit": credit,
            "split": bool(debit or credit) and not amount}


def _number(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    # Accounting negatives: (12.34) means -12.34.
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        n = float(text)
    except ValueError:
        return None
    return -n if negative else n


def _date(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d",
                "%b %d, %Y", "%d %b %Y", "%m-%d-%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def detect_sign(rows: list[dict], cols: dict) -> dict:
    """Work out whether a positive number in this file means money in or out.

    Returns the multiplier to apply so that a purchase ends up negative, plus
    what that conclusion rests on — so a weak basis is visible in the import
    output rather than discovered months later in a wrong total.
    """
    if cols["split"]:
        return {"multiplier": 1, "basis": "separate debit and credit columns"}

    payments = []
    for row in rows:
        desc = str(row.get(cols["description"]) or "")
        if PAYMENT_PATTERNS.search(desc) and not REFUND_PATTERNS.search(desc):
            n = _number(row.get(cols["amount"]))
            if n:
                payments.append(n)
    if payments:
        # A payment is money INTO the card, so it must end up positive.
        positive = sum(1 for p in payments if p > 0)
        negative = len(payments) - positive
        if positive and not negative:
            return {"multiplier": 1, "basis": f"{len(payments)} payment rows, positive"}
        if negative and not positive:
            return {"multiplier": -1, "basis": f"{len(payments)} payment rows, negative"}
        # Mixed signs on rows that should all point the same way means the
        # description match caught something that is not a payment.
        return {"multiplier": None,
                "basis": f"payment rows disagree ({positive} positive, {negative} negative)"}

    # No payment on the statement. Purchases outnumber payments on any real one,
    # so the majority sign is the purchase sign — weaker, and labelled as such.
    signs = Counter()
    for row in rows:
        n = _number(row.get(cols["amount"]))
        if n:
            signs[n > 0] += 1
    if not signs:
        return {"multiplier": None, "basis": "no amounts found"}
    purchases_positive = signs[True] >= signs[False]
    return {"multiplier": -1 if purchases_positive else 1,
            "basis": f"no payment row; assumed from the majority of "
                     f"{signs[True] + signs[False]} rows"}


def account_name_from(path: Path) -> str:
    """A readable account name from the filename.

    The file is the only thing that says which card this is — the CSV itself
    usually does not — so `chase_sapphire_2026.csv` becomes "Chase Sapphire".
    """
    # Dates go first, while their separators are still intact — once hyphens
    # have become spaces, "2026-08-14" is three bare numbers and only the year
    # still looks like part of a date.
    stem = re.sub(r"\d{4}[-_/]\d{2}[-_/]\d{2}", " ", path.stem)
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\b(20\d\d|\d{1,2}|transactions?|export|activity|statement|"
                  r"history|download)\b", "", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem.title() if stem else path.stem


def _source_id(account: str, day: str, amount: float, description: str, ordinal: int) -> str:
    # Card exports carry no stable identifier, so one is synthesised. The
    # ordinal is what makes two identical purchases on the same day at the same
    # place import as two transactions rather than one — which is a real
    # pattern, not an edge case.
    key = f"{account}|{day}|{amount:.2f}|{description}|{ordinal}"
    return hashlib.sha1(key.encode()).hexdigest()


def parse(path: Path) -> dict:
    """Read a card CSV into ledger-shaped rows without touching the database."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    # Some issuers put a title line or a blank line above the real header.
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines[:8]):
        if line.count(",") >= 2:
            start = i
            break
    reader = csv.DictReader(lines[start:])
    header = reader.fieldnames or []
    cols = sniff(header)
    if not cols["date"] or not cols["description"]:
        return {"error": f"could not find a date and description column in {header}",
                "rows": [], "columns": cols}
    if not cols["amount"] and not (cols["debit"] or cols["credit"]):
        return {"error": f"could not find an amount column in {header}",
                "rows": [], "columns": cols}

    raw = [r for r in reader if any((v or "").strip() for v in r.values())]
    sign = detect_sign(raw, cols)
    if sign["multiplier"] is None:
        return {"error": f"could not determine the sign convention: {sign['basis']}",
                "rows": [], "columns": cols, "sign": sign}

    rows, skipped = [], 0
    for r in raw:
        day = _date(r.get(cols["date"]))
        if not day:
            skipped += 1
            continue
        if cols["split"]:
            debit = _number(r.get(cols["debit"])) or 0.0
            credit = _number(r.get(cols["credit"])) or 0.0
            amount = abs(credit) - abs(debit)
        else:
            n = _number(r.get(cols["amount"]))
            if n is None:
                skipped += 1
                continue
            amount = n * sign["multiplier"]
        description = str(r.get(cols["description"]) or "").strip()
        rows.append({"txn_date": day, "amount": round(amount, 2),
                     "description": description,
                     "kind": "credit" if amount > 0 else "debit"})
    return {"rows": rows, "columns": cols, "sign": sign, "unparsed": skipped}


def import_file(conn, path: Path, account_name: str | None = None) -> dict:
    account = account_name or account_name_from(path)
    parsed = parse(path)
    if parsed.get("error"):
        return {"file": path.name, "seen": 0, "inserted": 0, "skipped": 0,
                "error": parsed["error"], "account": account}

    inst = conn.execute("SELECT id FROM institutions WHERE name = ?", ("Cards",)).fetchone()
    if not inst:
        cur = conn.execute("INSERT INTO institutions (name) VALUES ('Cards')")
        inst_id = cur.lastrowid
    else:
        inst_id = inst["id"]
    row = conn.execute("SELECT id FROM accounts WHERE institution_id = ? AND external_id = ?",
                       (inst_id, account)).fetchone()
    if row:
        account_id = row["id"]
    else:
        account_id = conn.execute(
            "INSERT INTO accounts (institution_id, external_id, name, kind, tax_status) "
            "VALUES (?,?,?,'credit','taxable')", (inst_id, account, account)).lastrowid

    ordinals = Counter()
    inserted = skipped = 0
    for r in parsed["rows"]:
        natural = (r["txn_date"], r["amount"], r["description"])
        ordinal = ordinals[natural]
        ordinals[natural] += 1
        ok = insert_transaction(conn, {
            "account_id": account_id, "txn_date": r["txn_date"], "kind": r["kind"],
            "security_id": None, "quantity": None, "price": None,
            "amount": r["amount"], "description": r["description"],
            "source": SOURCE,
            "source_id": _source_id(account, r["txn_date"], r["amount"],
                                    r["description"], ordinal),
        })
        inserted += 1 if ok else 0
        skipped += 0 if ok else 1
    conn.commit()
    return {"file": path.name, "account": account, "seen": len(parsed["rows"]),
            "inserted": inserted, "skipped": skipped,
            "sign": parsed["sign"]["basis"], "unparsed": parsed.get("unparsed", 0)}
