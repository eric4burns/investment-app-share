"""Import Frost Bank OFX exports (Web Connect).

Frost has no Direct Connect, but its Download Transactions page exports a full
two-year window in one file — no 93-day chunking — and the OFX carries a real
FITID per transaction. That FITID is a genuine unique id, so this importer is
idempotent for free: no synthetic key, no fuzzy matching.

OFX from banks is often SGML rather than XML (unclosed tags), so this parses
with regular expressions rather than an XML parser, which is the usual and
correct approach for the format.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..ledger import (get_or_create_account, get_or_create_institution,
                      insert_transaction, record_import)
from .. import cash

SOURCE = "frost_ofx"
INSTITUTION = "Frost Bank"

STMTTRN_RE = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.S | re.I)
ACCTID_RE = re.compile(r"<ACCTID>([^<\r\n]*)", re.I)
# The statement's own closing balance, and the moment it was true. This is the
# one number an OFX gives that the transaction list cannot: a bank export starts
# wherever you asked it to, so summing its rows assumes the account was empty
# the day before — and it was not. Frost read -$8,618.13 by that arithmetic
# against a real $9,358.35, an opening balance of nearly $18,000 that no
# transaction in the file could ever account for.
LEDGERBAL_RE = re.compile(r"<LEDGERBAL>(.*?)(?:</LEDGERBAL>|<AVAILBAL>)", re.S | re.I)
BALAMT_RE = re.compile(r"<BALAMT>\s*(-?[\d.,]+)", re.I)
DTASOF_RE = re.compile(r"<DTASOF>\s*(\d{8})", re.I)


def statement_balance(text: str) -> tuple[str, float] | None:
    """(as_of, balance) from the statement's LEDGERBAL block, if it has one."""
    block = LEDGERBAL_RE.search(text)
    if not block:
        return None
    amt = BALAMT_RE.search(block.group(1))
    when = DTASOF_RE.search(block.group(1))
    if not amt or not when:
        return None
    try:
        value = float(amt.group(1).replace(",", ""))
    except ValueError:
        return None
    d = when.group(1)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}", value

# OFX transaction types -> ledger kinds. Everything that moves cash in a
# checking account is a debit or a credit; the budget categoriser is what
# gives those meaning later.
TRNTYPE_KINDS = {
    "CREDIT": "credit", "DEP": "deposit", "DIRECTDEP": "deposit",
    "DEBIT": "debit", "CHECK": "debit", "POS": "debit", "ATM": "debit",
    "PAYMENT": "debit", "DIRECTDEBIT": "debit", "REPEATPMT": "debit",
    "XFER": "transfer_out", "FEE": "fee", "SRVCHG": "fee", "INT": "interest",
}


def _tag(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}>([^<\r\n]*)", block, re.I)
    return m.group(1).strip() if m else ""


def _date(value: str) -> str | None:
    v = (value or "").strip()[:8]
    if len(v) != 8 or not v.isdigit():
        return None
    return datetime.strptime(v, "%Y%m%d").strftime("%Y-%m-%d")


def import_file(conn, path: Path, account_name: str = "Frost Personal Account") -> dict:
    text = path.read_text(errors="replace")
    inst = get_or_create_institution(conn, INSTITUTION)

    # An export covering several accounts carries several ACCTIDs. Taking the
    # first and filing everything under it would silently merge two accounts
    # into one, so refuse rather than guess.
    account_ids = {m.strip() for m in ACCTID_RE.findall(text) if m.strip()}
    if len(account_ids) > 1:
        raise ValueError(
            f"{path.name} contains {len(account_ids)} accounts "
            f"({', '.join(sorted(account_ids))}). Export one account per file — "
            f"importing them together would merge them under whichever appeared "
            f"first.")
    external_id = next(iter(account_ids), path.stem)
    account_id = get_or_create_account(conn, inst, external_id, account_name, "checking", "na")

    seen = inserted = skipped = 0
    kinds = Counter()

    malformed = []
    for block in STMTTRN_RE.findall(text):
        seen += 1
        trntype = _tag(block, "TRNTYPE").upper()
        raw_amount = _tag(block, "TRNAMT")
        try:
            # `float(raw_amount or 0)` short-circuited an EMPTY tag to zero
            # before float() could raise, so the guard below could not fire on
            # the likeliest malformation of all: a bank that drops the amount
            # imported the row as a real $0.00 debit, with a genuine date and
            # description, and the cash balance came out short by the missing
            # figure with nothing anywhere saying so. A statement transaction
            # always carries an amount; a missing one is a gap, not a zero.
            if not raw_amount:
                raise ValueError("empty TRNAMT")
            amount = float(raw_amount)
        except ValueError:
            # float() used to raise here and abort the import midway, with rows
            # already inserted and no rollback. Collect and report instead.
            malformed.append(f"{_tag(block, 'FITID') or '?'}: TRNAMT={raw_amount!r}")
            skipped += 1
            continue
        # A transfer's DIRECTION is in the sign, not the type. Mapping XFER to
        # transfer_out regardless made every incoming transfer an outflow.
        kind = TRNTYPE_KINDS.get(trntype, "debit" if amount < 0 else "credit")
        if trntype == "XFER":
            kind = "transfer_out" if amount < 0 else "transfer_in"
        kinds[kind] += 1

        name, memo = _tag(block, "NAME"), _tag(block, "MEMO")
        # NAME carries the merchant ("CHASE CREDIT CRD EPAY"); MEMO is usually a
        # generic type ("Electronic Debit"). An earlier version filtered on
        # `p != name`, which is always false for p == name, so the merchant was
        # dropped from every row and all 1,302 descriptions collapsed to 13
        # generic strings — leaving the budget rules engine nothing to match on.
        parts = [p for p in (name, memo) if p]
        description = " — ".join(dict.fromkeys(parts))

        txn = {
            "account_id": account_id,
            "txn_date": _date(_tag(block, "DTPOSTED")),
            "settle_date": None,
            "kind": kind,
            "security_id": None,
            "quantity": None,
            "price": None,
            "amount": amount,
            "fees": 0.0,
            "commission": 0.0,
            "description": re.sub(r"\s+", " ", description).strip(),
            "source": SOURCE,
            "source_id": _tag(block, "FITID") or f"{path.stem}:{seen}",
            "raw": None,
        }
        try:
            if insert_transaction(conn, txn):
                inserted += 1
            else:
                skipped += 1                     # genuinely already imported
        except ValueError as exc:
            # A row the ledger will not accept — an unparseable DTPOSTED, most
            # likely. Named, not counted as a duplicate.
            malformed.append(str(exc))
            skipped += 1

    # Anchor the account to the statement's own closing balance. Without this
    # the running total is only as old as the export, which is a different
    # number from the balance and always wrong by whatever was in the account
    # when the window opened. The anchor is keyed by account and replaced each
    # import, so it always reflects the newest statement rather than accreting
    # a history of superseded readings.
    anchored = None
    bal = statement_balance(text)
    if bal:
        as_of, amount = bal
        cash.set_anchor(conn, account_name, as_of, amount,
                        note=f"LEDGERBAL from {path.name}")
        anchored = {"as_of": as_of, "balance": amount}

    record_import(conn, SOURCE, path.name, seen, inserted, skipped)
    return {"file": path.name, "seen": seen, "inserted": inserted,
            "anchor": anchored,
            "skipped": skipped, "kinds": kinds,
            # Named, not swallowed: a row dropped for an unreadable amount is a
            # gap in the ledger and must be visible as one.
            "malformed": malformed,
            # Same thing as a count, under the name every importer reports it
            # by, so the integrity check does not need to know which importer
            # produced the result.
            "unparsed": len(malformed)}
