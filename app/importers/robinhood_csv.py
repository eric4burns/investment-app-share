"""Import a Robinhood account activity report (CSV).

Robinhood gives no API and no OFX. What it does give is an "account activity
report" generated on demand from Reports and statements, covering a date range
you choose, as a CSV with these columns:

    Activity Date, Process Date, Settle Date, Instrument, Description,
    Trans Code, Quantity, Price, Amount

## Three things this format does that the other importers never had to handle

**No transaction id.** Like the Fidelity export, identity has to be synthesised
from the row's own contents. The natural key here is the activity date, the
instrument, the transaction code, the quantity and the amount, plus an ordinal
that counts genuine repeats within a file — two identical fills of the same
order on the same day are two rows, and must stay two rows, while re-importing
an overlapping report must not duplicate either of them.

**Crypto quantities are not share counts.** A holding can be 20.177226134 SOL
or 0.4343964459 ETH, so quantity is parsed as a full float and never rounded on
the way in. Rounding to the four decimals a share count needs would silently
lose most of a small ETH position.

**Amounts are parenthesised for money going out**, in the accounting
convention: "($1,234.56)" is negative. Stripping the parentheses and calling
float() yields a POSITIVE number, which turns every purchase into a deposit —
the same trap the Fidelity importer documents, and the reason `_money` here is
deliberate rather than a one-liner.

## Codes

Trans Code is Robinhood's own vocabulary and is not fully documented anywhere
public. The ones seen in real files are mapped below; anything unrecognised is
imported as "other" AND reported by name, rather than being quietly folded into
a bucket that makes the totals look complete. An unknown code that moves money
is exactly the kind of thing that should be noticed rather than absorbed.
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..ledger import (get_or_create_account, get_or_create_institution,
                      get_or_create_security, insert_transaction, record_import)

SOURCE = "robinhood_csv"
INSTITUTION = "Robinhood"

# Robinhood's transaction codes -> ledger kinds.
TRANS_CODES = {
    "Buy": "buy", "BTO": "buy", "BTC": "buy",
    "Sell": "sell", "STC": "sell", "STO": "sell",
    "ACH": "deposit",              # sign decides deposit vs withdrawal
    "RTP": "deposit",
    "CDIV": "dividend", "DIV": "dividend",
    "INT": "interest", "MINT": "interest",
    "GOLD": "fee", "DFEE": "fee", "AFEE": "fee", "FEE": "fee",
    "DTAX": "tax",
    "REC": "corporate_action", "SPL": "corporate_action", "SPR": "corporate_action",
    "MRGC": "corporate_action", "NC": "corporate_action",
    "SLIP": "exchange_in", "SXCH": "exchange_in",
    "XFER": "transfer_in",
}

MONEY_RE = re.compile(r"[^\d.\-()]")


def _money(value: str | None) -> float | None:
    """Parse an amount, honouring the accounting convention for negatives.

    "($1,234.56)" is money LEAVING. Removing the punctuation and calling
    float() returns +1234.56, which files every purchase as an inflow and
    inverts the entire account.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = MONEY_RE.sub("", s).replace("(", "").replace(")", "")
    if not s or s in {"-", "."}:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negative else n


def _qty(value: str | None) -> float | None:
    """Quantity at full precision — crypto runs to nine decimal places."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    # Robinhood suffixes a crypto quantity with its symbol on some rows.
    s = re.sub(r"[A-Za-z\s]+$", "", s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(value: str | None) -> str | None:
    v = (value or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _header_row(lines: list[str]) -> int:
    """Robinhood sometimes puts a title above the header."""
    for i, line in enumerate(lines[:10]):
        if "Trans Code" in line or ("Activity Date" in line and "Amount" in line):
            return i
    return 0


def parse(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    if not lines:
        return {"error": "empty file"}
    start = _header_row(lines)
    reader = csv.DictReader(lines[start:])
    if not reader.fieldnames or "Trans Code" not in ",".join(reader.fieldnames):
        return {"error": f"no 'Trans Code' column — columns were {reader.fieldnames}"}

    rows, unparsed, codes, unknown = [], 0, Counter(), Counter()
    for raw in reader:
        day = _date(raw.get("Activity Date"))
        code = (raw.get("Trans Code") or "").strip()
        if not day:
            # The report ends with blank lines and a legal disclaimer; a row
            # with content but no date is a genuine problem and is counted.
            #
            # The disclaimer is ONE unquoted sentence containing commas, so csv
            # reads it as extra fields and DictReader files them under the
            # restkey as a LIST, not a string. Calling .strip() on that raised
            # AttributeError and took the whole import down on the last line of
            # the file — every real row already parsed and then discarded. So
            # flatten values before testing them, and treat the trailing notice
            # as the boilerplate it is rather than as unparsed data.
            flat = []
            for v in raw.values():
                flat.extend(v if isinstance(v, list) else [v])
            text = " ".join((v or "").strip() for v in flat).strip()
            if text and not text.startswith("The data provided is for informational"):
                unparsed += 1
            continue
        amount = _money(raw.get("Amount")) or 0.0
        kind = TRANS_CODES.get(code, "other")
        if code not in TRANS_CODES:
            unknown[code] += 1
        # Direction lives in the sign, not the code: one ACH covers both a
        # deposit and a withdrawal.
        if kind == "deposit" and amount < 0:
            kind = "withdrawal"
        codes[code] += 1
        rows.append({
            "txn_date": day,
            "settle_date": _date(raw.get("Settle Date")),
            "kind": kind,
            "symbol": (raw.get("Instrument") or "").strip().upper(),
            "quantity": _qty(raw.get("Quantity")),
            "price": _money(raw.get("Price")),
            "amount": amount,
            "description": re.sub(r"\s+", " ", (raw.get("Description") or "").strip()),
            "code": code,
        })
    return {"rows": rows, "unparsed": unparsed, "codes": codes, "unknown_codes": unknown}


def _source_id(r: dict, ordinal: int) -> str:
    """Stable synthetic id: the row's natural key plus a repeat counter."""
    return "|".join([r["txn_date"], r["symbol"], r["code"],
                     f"{r['quantity']!r}", f"{r['amount']:.4f}", str(ordinal)])


def import_file(conn, path: Path,
                account_name: str = "Robinhood Individual") -> dict:
    path = Path(path)
    parsed = parse(path)
    if parsed.get("error"):
        return {"file": path.name, "seen": 0, "inserted": 0, "skipped": 0,
                "error": parsed["error"], "account": account_name}

    inst = get_or_create_institution(conn, INSTITUTION)
    account_id = get_or_create_account(conn, inst, account_name, account_name,
                                       "brokerage", "taxable")

    ordinals: Counter = Counter()
    inserted = skipped = 0
    for r in parsed["rows"]:
        natural = (r["txn_date"], r["symbol"], r["code"], r["quantity"], r["amount"])
        ordinal = ordinals[natural]
        ordinals[natural] += 1
        security_id = (get_or_create_security(conn, r["symbol"], r["description"])
                       if r["symbol"] else None)
        ok = insert_transaction(conn, {
            "account_id": account_id, "txn_date": r["txn_date"],
            "settle_date": r["settle_date"], "kind": r["kind"],
            # A DISPOSAL CARRIES A NEGATIVE QUANTITY. Every other importer in
            # this app writes sells that way and the lot builder relies on it,
            # so storing Robinhood's positive figure left sold-out positions
            # still showing as held: SLNH read 20.96 shares and FRMI 2.0 after
            # both had been closed out entirely, because the sell added to the
            # position instead of reducing it. Robinhood's own CSV states the
            # quantity unsigned and puts the direction in Trans Code alone.
            "security_id": security_id,
            "quantity": (-r["quantity"] if r["quantity"] is not None
                         and r["kind"] == "sell" else r["quantity"]),
            "price": r["price"], "amount": r["amount"],
            "fees": 0.0, "commission": 0.0,
            "description": r["description"] or r["code"],
            "source": SOURCE, "source_id": _source_id(r, ordinal), "raw": None,
        })
        inserted += 1 if ok else 0
        skipped += 0 if ok else 1

    conn.commit()
    record_import(conn, SOURCE, path.name, len(parsed["rows"]), inserted, skipped)
    return {"file": path.name, "account": account_name,
            "seen": len(parsed["rows"]), "inserted": inserted, "skipped": skipped,
            "unparsed": parsed["unparsed"],
            "codes": dict(parsed["codes"]),
            # Named rather than absorbed: an unrecognised code that moves money
            # is exactly what should be noticed.
            "unknown_codes": dict(parsed["unknown_codes"])}
