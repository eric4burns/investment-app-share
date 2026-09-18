"""Checks that a file imported completely, and that the ledger has no holes.

Every importer here is idempotent and forgiving, which is what makes re-running
them safe — and also what makes a truncated export dangerous. A file with half
its rows missing imports without complaint, reports a plausible number, and
leaves a hole that looks exactly like a quiet month. That is not hypothetical:
this project spent a long session tracking down $45,204 of card spending that
was invisible because a card had never been exported at all, and the only
symptom was totals that felt low.

The providers make it likely rather than merely possible:

  * **Chase** caps a single downloaded report at **1,000 transactions** and
    says so in small print on the download dialog. Ask for more and you get
    exactly 1,000, with no error.
  * **Elan** (the Fidelity Rewards Visa) serves at most **18 months** of
    history online, silently clamping any wider range.
  * **Fidelity** caps an activity export at 90 days per file.

So there are two questions worth asking after every import, and neither was
being asked:

  1. **Did this FILE import completely?** Rows the parser could not understand
     are dropped on the floor. Each importer already knows how many it dropped;
     nothing was printing it.
  2. **Does the LEDGER have holes?** A month with no transactions at all in a
     checking or credit account is nearly impossible in real life, and is the
     signature of a missing or truncated export.

Both report; neither fails the run. A shortfall is a prompt to go and look, not
proof of a problem — a Fidelity export legitimately carries a legal footer, and
a card genuinely can sit unused for a month.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

# Rows a provider will hand over in one file. Hitting one of these EXACTLY is
# the tell: real activity does not land on a round number by chance, so a file
# with precisely this many rows is almost certainly the top slice of a longer
# list.
PROVIDER_CAPS = {
    1000: "Chase caps a downloaded report at 1,000 transactions",
}

STMTTRN_RE = re.compile(r"<STMTTRN>", re.I)


def count_records(path: Path) -> int | None:
    """Candidate records in the file, before any parsing.

    Deliberately crude and format-shaped: the point is to have a second opinion
    that does NOT share the importer's own parsing logic, because a count
    derived from the parser can never disagree with it.

    Returns None for formats where a record count is not meaningful.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    if suffix == ".ofx":
        return len(STMTTRN_RE.findall(text))
    if suffix == ".csv":
        # Parsed as CSV RECORDS, not counted as lines. Amex writes the extended
        # merchant detail as a quoted field containing newlines, so one
        # transaction can span five physical lines — counting lines reported
        # 1,114 records in a 229-row file and accused a perfectly good import of
        # losing 885 of them. A check that cries wolf is worse than no check,
        # because it teaches you to skim past the line that finally matters.
        # A record has at least two populated fields. Every Fidelity export ends
        # with nine lines of legal boilerplate, each a single quoted sentence;
        # counting those as records accused all ten Fidelity files of losing
        # exactly nine rows, every run, forever.
        try:
            rows = [r for r in csv.reader(io.StringIO(text))
                    if sum(1 for f in r if f.strip()) > 1]
        except csv.Error:
            return None
        return max(0, len(rows) - 1)          # less the header
    return None


def file_warnings(result: dict, path: Path | None = None,
                  rows_are_transactions: bool = True) -> list[str]:
    """What looks wrong about one importer result. Empty means nothing does.

    `rows_are_transactions` says whether the result's "seen" count is one per
    record in the file. For the reference importers it is not — a budget grid
    reports CELLS and a pay stub reports FIELDS, so comparing either against a
    record count is meaningless and produced a confident, wrong warning on both.
    """
    out = []
    seen = int(result.get("seen") or 0)

    unparsed = int(result.get("unparsed") or 0)
    if unparsed:
        out.append(f"{unparsed} row{'s' if unparsed != 1 else ''} in the file "
                   f"could not be read and were skipped")

    if seen and seen in PROVIDER_CAPS:
        out.append(f"exactly {seen} rows — {PROVIDER_CAPS[seen]}, "
                   f"so this file is probably truncated; export a narrower "
                   f"date range and import both halves")

    if path is not None and rows_are_transactions:
        records = count_records(path)
        # Only a shortfall is interesting. A count HIGHER than seen is the
        # normal case for a CSV with a preamble or footer, and warning about it
        # every run would train the reader to ignore the whole section.
        if records is not None and seen and records > seen:
            missing = records - seen
            # A couple of lines is the legal footer every Fidelity export
            # carries. A tenth of the file is a different thing entirely.
            if missing > max(3, seen * 0.05):
                out.append(f"{records} record-like lines in the file but only "
                           f"{seen} understood — {missing} unaccounted for")
    return out


def coverage_gaps(conn, kinds=("checking", "credit")) -> list[dict]:
    """Months with no transactions at all, inside an account's active range.

    Scoped to spending accounts on purpose. A brokerage or retirement account
    with a quiet month is ordinary; a checking account with one has almost
    certainly lost an export. Only months strictly between the account's first
    and last transaction count — the silence before you opened it and after the
    last import is not a gap.
    """
    placeholders = ",".join("?" for _ in kinds)
    accounts = conn.execute(
        f"""SELECT a.id, a.name, a.kind,
                   MIN(t.txn_date) AS first, MAX(t.txn_date) AS last,
                   COUNT(*) AS n
              FROM accounts a JOIN transactions t ON t.account_id = a.id
             WHERE a.kind IN ({placeholders})
          GROUP BY a.id""", tuple(kinds)).fetchall()

    out = []
    for acct in accounts:
        present = {r[0] for r in conn.execute(
            "SELECT DISTINCT substr(txn_date,1,7) FROM transactions WHERE account_id = ?",
            (acct["id"],))}
        missing = [m for m in _months(acct["first"][:7], acct["last"][:7])
                   if m not in present]
        if missing:
            out.append({"account": acct["name"], "kind": acct["kind"],
                        "first": acct["first"], "last": acct["last"],
                        "missing": missing})
    return out


def _months(start: str, end: str) -> list[str]:
    """Every yyyy-mm from start to end inclusive."""
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out
