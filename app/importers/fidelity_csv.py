"""Import Fidelity 'Accounts_History' CSV exports.

Format notes learned from the real files (2026-08-29):
  * UTF-8 BOM, then two blank lines, then the header row.
  * A multi-line legal footer follows the data; rows there have no date in col 1.
  * Fidelity caps each export at 93 days, so history arrives as several
    overlapping-capable files. There is no transaction id in the export, so
    one is synthesized — see `_source_id`.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .. import config
from ..ledger import (get_or_create_account, get_or_create_institution,
                      get_or_create_security, insert_transaction, record_import)

SOURCE = "fidelity_csv"
INSTITUTION = "Fidelity"
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

# Account kind and tax status are INFERRED from the account's name rather than
# listed here. tax_status drives the taxable-only toggle and every after-tax
# figure, so getting it wrong matters — but brokerages name accounts after what
# they are, so "ROTH IRA" and "HEALTH SAVINGS ACCOUNT" are readable. The six
# accounts this importer was written against all classify identically to the
# table that used to sit here.
#
# config.json overrides the guess for anything a name cannot reveal. See
# app/config.py.

# Ordered: first matching prefix wins.
ACTION_KINDS = [
    ("YOU BOUGHT",         "buy"),
    ("YOU SOLD",           "sell"),
    ("DIVIDEND",           "dividend"),
    ("REINVESTMENT",       "reinvest"),
    ("INTEREST",           "interest"),
    ("CONTRIBUTIONS",      "contribution"),
    # Money arriving from OUTSIDE these accounts. Missing any of these is not a
    # cosmetic mislabel: unclassified inflows are indistinguishable from
    # investment gains, and $68,614 of them turned a real return into +1519%.
    ("CASH CONTRIBUTION",  "contribution"),
    ("ROLLOVER",           "transfer_in"),      # rollover check from another custodian
    ("ROTH CONVERSION",    "transfer_in"),      # conversion from an IRA outside this ledger
    ("TRANSFER OF ASSETS", "transfer_in"),      # e.g. HSA transferred in from Optum
    ("EXCHANGED TO",       "exchange_in"),
    ("PARTIC CONTR",       "contribution"),
    ("PART CONTRIB",       "contribution"),
    ("CO CONTR",           "contribution"),
    ("DIRECT DEPOSIT",     "deposit"),
    ("ELECTRONIC FUNDS",   "deposit"),      # sign-corrected below
    ("TRANSFERRED FROM",   "transfer_in"),
    ("TRANSFERRED TO",     "transfer_out"),
    ("EXCHANGE IN",        "exchange_in"),
    ("EXCHANGE OUT",       "exchange_out"),
    ("RECORDKEEPING FEE",  "fee"),
    ("FEE CHARGED",        "fee"),
    ("FOREIGN TAX",        "tax"),
    ("REVERSE SPLIT",      "corporate_action"),
    ("CHANGE IN MARKET",   "market_value_adj"),
    ("IN LIEU",            "corporate_action"),
]

# Corporate-action markers that must be tested BEFORE the verb prefixes above.
# Fidelity books share allocations from a reverse split as "YOU BOUGHT ... R/S INT",
# which would otherwise be counted as a real purchase and quietly corrupt both
# cost basis and any buy/sell statistics.
CORPORATE_ACTION_RE = re.compile(r"\bR/S\b|REVERSE SPLIT|\bIN LIEU\b|#REOR", re.I)
REVERSE_SPLIT_RE = re.compile(r"^REVERSE SPLIT\b", re.I)

# A 9-character CUSIP in parentheses, used on corporate-action lines that carry
# no ticker. Tracking these under a CUSIP: pseudo-symbol keeps them distinct
# instead of collapsing every symbol-less row into one anonymous bucket.
CUSIP_RE = re.compile(r"\((\d{8}[0-9A-Z])\)")


def _num(value: str | None) -> float | None:
    """Parse a money field, without silently losing or rescaling it.

    Two traps, both of which produced a plausible wrong number rather than a
    failure. Accounting parentheses mean NEGATIVE — "(1,234.56)" was stripped to
    "(1234.56)", failed float(), returned None, and the caller's `or 0.0` turned
    a $1,234.56 outflow into zero. And blindly deleting commas turns the
    European "1.234,56" into 1.23456, a thousandfold understatement that still
    looks like a price.

    Which character is the decimal separator is decided by whichever appears
    LAST, which is correct for both conventions.
    """
    if value is None:
        return None
    s = str(value).strip().replace("$", "").replace('"', "").replace("\u00a0", " ")
    s = s.replace(" ", "")
    if not s or s in {"-", "--"}:
        return None

    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]

    if "," in s and "." in s:
        decimal = "," if s.rindex(",") > s.rindex(".") else "."
        s = s.replace("," if decimal == "." else ".", "")
        s = s.replace(decimal, ".")
    elif "," in s:
        # A lone comma is a decimal point only when it is followed by one or two
        # digits and nothing else; otherwise it groups thousands.
        tail = s.rsplit(",", 1)[1]
        s = s.replace(",", "." if (len(tail) in (1, 2) and tail.isdigit()) else "")

    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negative else n


def _date(value: str | None) -> str | None:
    v = (value or "").strip()
    if not DATE_RE.match(v):
        return None
    return datetime.strptime(v, "%m/%d/%Y").strftime("%Y-%m-%d")


def classify(action: str, amount: float | None) -> str:
    """Map a Fidelity Action string to a ledger kind.

    Trade verbs are tested FIRST and win outright. Fidelity appends the reorg
    marker to the *security name* of a stock with a pending corporate action,
    so "YOU BOUGHT STRIVE INC CL A COM 1 FOR 20 R/S INT..." is an ordinary
    purchase with a real price and settlement date — not an event. An earlier
    version tested the reorg regex first and swallowed 65 real buys worth
    $42,772, which then had no usable price and were valued at zero.
    """
    a = re.sub(r"\s+", " ", (action or "").strip()).upper()
    for prefix, kind in ACTION_KINDS:
        if a.startswith(prefix):
            # Cash movements are only distinguishable by sign.
            if kind == "deposit" and amount is not None and amount < 0:
                return "withdrawal"
            return kind
    # Only rows that match no known verb fall through to the reorg test.
    if CORPORATE_ACTION_RE.search(a):
        return "corporate_action"
    return "other"


# A 401(k) plan holds investment OPTIONS, not listed securities: a collective
# trust or separate account with a daily NAV that is published to the plan and
# nowhere else. Fidelity's export leaves the Symbol column empty for these and
# puts the option's name in Description, so every such row arrived with no
# security at all and the balance sat at CONTRIBUTIONS AT COST forever, never
# moving with the market. The L3Harris plan reads $2,916.10 that way against
# $3,279.81 at its own NAV.
#
# BROKERAGELINK is excluded deliberately. Its "units" are dollars moving to the
# self-directed sleeve, which is a SEPARATE ACCOUNT in this ledger, so treating
# it as a holding here would count the same money twice.
#
# "Change in Market Value" is excluded too: it carries a quantity, but its
# amount over its quantity implies a NAV of -$2,246, which is a restatement of
# value rather than a purchase of units.
PLAN_FUND_SKIP = {"", "NO DESCRIPTION", "BROKERAGELINK"}
PLAN_FUND_PREFIX = "PLAN:"


def plan_fund(row: dict) -> str | None:
    """The plan investment option a row belongs to, if it is one."""
    if (row.get("Symbol") or "").strip():
        return None                      # a real ticker; not a plan option
    name = re.sub(r"\s+", " ", (row.get("Description") or "").strip()).upper()
    if name in PLAN_FUND_SKIP:
        return None
    if REVERSE_SPLIT_RE.match((row.get("Action") or "").strip()):
        return None
    if "CHANGE IN MARKET" in (row.get("Action") or "").upper():
        return None
    # A corporate action also arrives with an empty Symbol, but its reorg marker
    # is on the SECURITY NAME rather than the action — so checking the Action
    # alone let "STRIVE INC CL A COM 1 FOR 20 R/S INTO ... CUSIP #862945300"
    # through as a plan option, and it became a 26,149-unit holding worth
    # $13,859 that does not exist.
    if CORPORATE_ACTION_RE.search(name) or CUSIP_RE.search(name):
        return None
    # A plan option is a short name off a menu — "INDEX EQUITY FUND", "STABLE
    # VALUE FUND". A security description is long and carries share classes and
    # identifiers. The cut is generous enough for any real option name.
    if len(name) > 40:
        return None
    return PLAN_FUND_PREFIX + name


def _symbol(row: dict) -> str:
    sym = (row.get("Symbol") or "").strip().upper()
    if sym not in {"", "--", "N/A"}:
        return sym
    # Corporate-action lines often carry a CUSIP instead of a ticker.
    m = CUSIP_RE.search((row.get("Action") or ""))
    return f"CUSIP:{m.group(1)}" if m else ""


def _source_id(row: dict, ordinal: int) -> str:
    """Stable synthetic id for a Fidelity row.

    Fidelity gives us no transaction id, so the identity of a row is its
    natural key. `ordinal` disambiguates genuinely identical rows on the same
    day (two identical fills of the same order); because Fidelity's export
    ordering is stable, the same row gets the same ordinal in any export that
    covers it, which is what keeps overlapping files idempotent.
    """
    key = "|".join([
        (row.get("Account Number") or "").strip(),
        (row.get("Run Date") or "").strip(),
        re.sub(r"\s+", " ", (row.get("Action") or "").strip()),
        _symbol(row),
        (row.get("Quantity") or "").strip(),
        (row.get("Amount") or "").strip(),
        (row.get("Settlement Date") or "").strip(),
        str(ordinal),
    ])
    return hashlib.sha1(key.encode()).hexdigest()


def read_rows(path: Path, dropped: list | None = None):
    """Yield data rows, skipping the BOM/blank preamble and the legal footer.

    Rows without a parseable Run Date are dropped. That is usually the legal
    footer and is meant to be silent, but it is also where a malformed or
    truncated row would disappear without trace — so when `dropped` is given,
    each one is appended to it and the caller can report the count.
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    try:
        header = next(i for i, line in enumerate(lines) if line.startswith("Run Date,"))
    except StopIteration:
        raise ValueError(f"{path.name}: no 'Run Date' header found")
    body = "\n".join(lines[header:])
    for row in csv.DictReader(io.StringIO(body)):
        if DATE_RE.match((row.get("Run Date") or "").strip()):
            yield row
        elif dropped is not None and sum(1 for v in row.values() if (v or "").strip()) > 1:
            # Only rows shaped like DATA. The nine-line legal footer every
            # export carries is one quoted sentence per line, so it populates a
            # single field; reporting those made all ten files claim to have
            # lost nine rows on every run. A row with several populated fields
            # and no readable date is a different animal, and is worth saying.
            dropped.append(row)


def import_file(conn, path: Path) -> dict:
    inst = get_or_create_institution(conn, INSTITUTION)
    seen = inserted = skipped = 0
    cfg_accounts = config.load().get("accounts") or {}
    guessed_accounts: dict[str, str] = {}
    unknown_accounts: set[str] = set()
    kinds = Counter()
    seen_keys = Counter()
    dropped: list = []

    for row in read_rows(path, dropped):
        seen += 1
        name = (row.get("Account") or "").strip()
        number = (row.get("Account Number") or "").strip()
        kind, tax_status, guessed = config.classify_account(name, cfg_accounts)
        if guessed:
            # Reported, never silent: a misclassified account decides whether a
            # contribution counts against the Roth limit or the 401(k) deferral
            # limit, and whether a gain is taxable at all.
            guessed_accounts[name] = f"{kind}/{tax_status}"
        account_id = get_or_create_account(conn, inst, number, name, kind, tax_status)

        amount = _num(row.get("Amount")) or 0.0
        kind = classify(row.get("Action", ""), amount)

        # A REVERSE SPLIT leg's Amount column holds the dollar value of the
        # shares being transferred, not a cash movement. The two legs are
        # struck on different prices so they do not net, and summing them
        # fabricated $2,666.74 of cash that never existed. Shares still move;
        # cash does not.
        split_price = None
        if REVERSE_SPLIT_RE.match(re.sub(r"\s+", " ", (row.get("Action") or "").strip()).upper()):
            # The Amount column on a reorg leg is the dollar value of the shares
            # being moved. It is not cash — but it IS the cost basis travelling
            # with them, so convert it to a per-share price before discarding it.
            # Dropping it outright left the post-split lots at zero basis, which
            # reported a 653% gain on a position that had merely been renamed.
            qty_val = _num(row.get("Quantity"))
            if qty_val:
                split_price = abs(amount) / abs(qty_val)
            amount = 0.0
        kinds[kind] += 1

        symbol = _symbol(row)
        # A plan investment option becomes a security under a PLAN: pseudo-symbol
        # so the rest of the app can hold and price it like anything else. The
        # kind is rewritten to buy/sell by the SIGN of the quantity, because a
        # payroll contribution that buys fund units is a purchase — and without
        # that the units never accumulate, since "contribution" is not a
        # position kind.
        #
        # _source_id deliberately still reads the RAW Symbol column, which stays
        # empty, so a row's identity is unchanged by any of this and re-importing
        # an overlapping export remains idempotent.
        # NOTE: the plan-fund purchase is emitted as a SECOND row below rather
        # than by rewriting this one. See the comment there.
        security_id = get_or_create_security(conn, symbol, (row.get("Description") or "").strip()) if symbol else None

        # ordinal counts repeats of an otherwise-identical row within this file
        natural = (number, row.get("Run Date"), row.get("Action"), symbol, row.get("Amount"))
        ordinal = seen_keys[natural]
        seen_keys[natural] += 1

        txn = {
            "account_id": account_id,
            "txn_date": _date(row.get("Run Date")),
            "settle_date": _date(row.get("Settlement Date")),
            "kind": kind,
            "security_id": security_id,
            "quantity": _num(row.get("Quantity")),
            "price": split_price if split_price is not None else _num(row.get("Price")),
            "amount": amount,
            "fees": _num(row.get("Fees")) or 0.0,
            "commission": _num(row.get("Commission")) or 0.0,
            "description": re.sub(r"\s+", " ", (row.get("Action") or "").strip()),
            "source": SOURCE,
            "source_id": _source_id(row, ordinal),
            "raw": None,
        }
        if insert_transaction(conn, txn):
            inserted += 1
        else:
            skipped += 1

        # A 401(k) row is a single line doing two things: money arrives from
        # payroll AND it is immediately invested in a plan option. One row
        # cannot express that, and neither shortcut works alone --
        #
        #   rewriting it as a buy credits the cash AND adds the units, which
        #   counted the L3Harris plan twice and turned $2,916 into $6,283;
        #
        #   zeroing its amount loses the contribution as an EXTERNAL FLOW, and
        #   an unrecognised inflow is indistinguishable from investment gain,
        #   which is precisely how $68,614 once turned a real return into
        #   +1519% elsewhere in this importer.
        #
        # So the original row stands unchanged -- cash in, flow recorded -- and
        # a paired purchase is emitted beside it: cash back out, units in. Net
        # cash zero, units held, flow intact.
        fund = plan_fund(row)
        fund_qty = _num(row.get("Quantity")) if fund else None
        if fund and fund_qty:
            fund_sec = get_or_create_security(conn, fund, fund[len(PLAN_FUND_PREFIX):])
            if insert_transaction(conn, {
                **txn,
                "kind": "buy" if fund_qty > 0 else "sell",
                "security_id": fund_sec,
                "quantity": fund_qty,
                "price": (abs(amount) / abs(fund_qty)) if fund_qty else None,
                "amount": -amount,
                "description": f"[plan option] {fund[len(PLAN_FUND_PREFIX):]}",
                "source_id": txn["source_id"] + ":fund",
            }):
                inserted += 1
            else:
                skipped += 1

    record_import(conn, SOURCE, path.name, seen, inserted, skipped)
    return {"file": path.name, "seen": seen, "inserted": inserted,
            "skipped": skipped, "kinds": kinds, "unknown_accounts": unknown_accounts,
            "guessed_accounts": guessed_accounts,
            # Rows with content that carried no readable date. Normally the
            # legal footer; occasionally the edge of a truncated file.
            "unparsed": len(dropped)}


def store_plan_navs(conn) -> dict:
    """Derive a price series for each plan investment option, from its own rows.

    A plan option has no ticker and no public feed, so nothing can be fetched
    for it — but every transaction states units AND dollars, and the ratio of
    those is the NAV the plan struck that day. The fund's whole price history is
    therefore already sitting in the ledger; it just was never read as one.

    Only rows whose implied NAV is positive and plausible are used. A
    "Change in Market Value" row carries a quantity but implies -$2,246 a unit,
    which is a restatement rather than a trade, and one such row admitted into
    the series would drag every valuation through it.
    """
    from .. import prices

    rows = conn.execute(
        """SELECT s.symbol, t.txn_date, t.quantity, t.amount
             FROM transactions t JOIN securities s ON s.id = t.security_id
            WHERE s.symbol LIKE ? AND t.quantity IS NOT NULL
              AND t.quantity != 0 AND t.amount IS NOT NULL""",
        (PLAN_FUND_PREFIX + "%",)).fetchall()

    by_symbol: dict[str, dict[str, float]] = {}
    for r in rows:
        # Magnitudes, because the paired purchase row carries a NEGATED amount
        # against a positive quantity — a buy costs money. What is wanted is the
        # price per unit, which has no sign.
        nav = abs(r["amount"] or 0.0) / abs(r["quantity"])
        if nav <= 0 or nav > 1_000_000:
            continue
        by_symbol.setdefault(r["symbol"], {})[r["txn_date"][:10]] = round(nav, 6)

    out = {}
    for symbol, navs in by_symbol.items():
        stored = prices.store(conn, symbol,
                              [(d, v) for d, v in sorted(navs.items())],
                              source="plan_nav")
        out[symbol] = {"bars": len(navs), "new": stored,
                       "first": min(navs), "last": max(navs),
                       "latest_nav": navs[max(navs)]}
    return out
