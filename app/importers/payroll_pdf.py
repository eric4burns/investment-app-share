"""A payroll advice (pay stub) PDF, read for its year-to-date column.

The bank ledger sees a payroll deposit, which is NET — net of tax, net of every
pre-tax deferral, net of the after-tax ones too. That single number is all the
rest of this app has ever had to reason about wages with, and it is the wrong
number for three separate questions:

  * **Income.** Gross wages, not the deposit, are what a bracket is measured
    against. In 2026 the gap between the two is over thirty thousand dollars.
  * **Deferral limits.** The 401(k) employee limit counts what the EMPLOYEE
    defers. The brokerage side of the ledger sees money arriving in the plan,
    which is employee deferral PLUS the employer match — so counting plan
    inflow against the limit overstates it and reports far less room than
    really remains. Only the stub separates the two.
  * **Withholding.** What was actually withheld is the only thing that makes a
    computed tax figure meaningful; without it the app can say what is owed but
    never whether it has already been paid.

Like the budget sheet, this is stored as a **reference series** and is never
added to the ledger's own totals. These are figures reported by an employer,
not double-entry transactions, and adding a YTD column to a running total would
count the whole year again on every stub.

Year-to-date is cumulative, so the latest stub in a year supersedes the earlier
ones rather than adding to them. Storing each stub separately and reading the
newest is deliberate: it keeps a stub that turns up out of order from clobbering
a later one, and it makes the progression through the year visible.

Text is extracted with `pdftotext -layout` (poppler). The layout flag matters:
the stub is a grid of side-by-side boxes, and without it the columns interleave
into unparseable soup. If poppler is missing the importer says so plainly rather
than silently importing nothing.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

SOURCE = "payroll_pdf"

SCHEMA = """
CREATE TABLE IF NOT EXISTS payroll_reference (
    pay_end     TEXT NOT NULL,          -- ISO yyyy-mm-dd, the stub's period end
    field       TEXT NOT NULL,
    amount      REAL NOT NULL,
    source      TEXT NOT NULL,
    file        TEXT,
    PRIMARY KEY (pay_end, field, source)
);
"""

# Every figure below is read from the YTD column, never the current-period one.
# A single pay period says nothing about a limit.
#
# Employee 401(k) deferral is the sum of the traditional "401K" before-tax line
# and the "Roth 401k" after-tax line: both are employee deferrals and both count
# against the same annual limit, which is exactly the distinction the brokerage
# side of the ledger cannot make.
BEFORE_TAX = {"401K": "deferral_traditional", "HSA": "hsa_employee",
              "Medical": "medical", "Dental": "dental", "Vision": "vision"}
AFTER_TAX = {"Roth 401k": "deferral_roth"}
TAXES = {"Fed MED/EE": "medicare", "Fed OASDI/EE": "social_security",
         "Fed Withholdng": "federal_withheld", "Fed Withholding": "federal_withheld"}


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _money(text: str) -> float | None:
    try:
        return float(text.replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


# launchd hands a job almost no PATH — not /opt/homebrew/bin, not /usr/local/bin
# — so shutil.which() finds pdftotext from a terminal and finds nothing from the
# scheduled run. The importer then reported "poppler not installed" every night
# on a machine where it plainly was, and imported no stubs at all. Looking in
# the usual places is what makes the scheduled run behave like the manual one.
POPPLER_PATHS = (
    "/opt/homebrew/bin/pdftotext",      # Homebrew on Apple silicon
    "/usr/local/bin/pdftotext",         # Homebrew on Intel
    "/opt/local/bin/pdftotext",         # MacPorts
    "/usr/bin/pdftotext",               # Linux
)


def _pdftotext() -> str | None:
    """Where pdftotext actually is, PATH or no PATH."""
    found = shutil.which("pdftotext")
    if found:
        return found
    return next((p for p in POPPLER_PATHS if Path(p).exists()), None)


def extract_text(path: Path) -> str:
    """The stub as laid-out text, or "" when poppler is not installed."""
    exe = _pdftotext()
    if not exe:
        return ""
    out = subprocess.run([exe, "-layout", str(path), "-"],
                         capture_output=True, text=True, timeout=30)
    return out.stdout or ""


_NUMBER = re.compile(r"^-?[\d,]+\.\d{2}$")


def _row(text: str, label: str) -> list[float]:
    """The run of numbers printed immediately after `label`.

    The stub is four boxes side by side, so a single text line holds several
    unrelated fields: "401K 589.38 4,037.24 Roth 401k 136.01 10,358.69" is one
    line carrying two different deductions. Anchoring to the start of a line
    therefore finds only the leftmost box and silently loses the deferral, the
    withholding and every tax figure.

    So the label is matched anywhere, and the numbers after it are taken only
    until the next non-numeric token — which is the next box's field name. That
    boundary is what stops "401K" from swallowing the Roth column beside it.

    The lookbehind keeps the traditional "401K" from matching inside "Roth
    401k"; without it the two deferral lines collapse into one and the employee
    total comes out wrong in the direction that matters.
    """
    guard = r"(?<!Roth )" if label.upper() == "401K" else ""
    pattern = re.compile(guard + re.escape(label) + r"\b(.*)$", re.M | re.I)
    for m in pattern.finditer(text):
        nums = []
        for token in m.group(1).split():
            if not _NUMBER.match(token):
                break
            value = _money(token)
            if value is not None:
                nums.append(value)
        if nums:
            return nums
    return []


def parse(path: Path) -> dict:
    text = extract_text(path)
    if not text.strip():
        return {"error": "pdftotext (poppler) not installed, or the PDF has no text layer"}

    m = re.search(r"Pay End Date:\s*(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return {"error": "no 'Pay End Date' found — is this a payroll advice?"}
    pay_end = f"{m.group(3)}-{m.group(1)}-{m.group(2)}"

    fields: dict[str, float] = {}

    # The summary strip at the foot carries the five figures that matter most,
    # on one line beginning "YTD:" — gross, federal taxable gross, total taxes,
    # total deductions, net pay, in that fixed order.
    for line in text.splitlines():
        if re.match(r"\s*YTD:\s", line):
            nums = [_money(n) for n in re.findall(r"-?[\d,]+\.\d{2}", line)]
            nums = [n for n in nums if n is not None]
            if len(nums) >= 5:
                for key, value in zip(("gross", "federal_taxable_gross", "taxes_total",
                                       "deductions_total", "net_pay"), nums):
                    fields[key] = value
                break

    # Deduction and tax lines print "Current YTD" side by side, so the YTD figure
    # is the SECOND number on the row. Taking the first would report a fortnight
    # as a year.
    for label, key in {**BEFORE_TAX, **AFTER_TAX, **TAXES}.items():
        nums = _row(text, label)
        if len(nums) >= 2:
            fields[key] = nums[1]

    if "deferral_traditional" in fields or "deferral_roth" in fields:
        fields["deferral_employee"] = round(
            fields.get("deferral_traditional", 0.0) + fields.get("deferral_roth", 0.0), 2)

    rate = re.search(r"Pay Rate:\s*\$?([\d,]+\.\d{2})\s*Annual", text)
    if rate:
        value = _money(rate.group(1))
        if value is not None:
            fields["annual_rate"] = value

    status = re.search(r"Tax Status:\s*(\w+)", text)
    return {"pay_end": pay_end, "fields": fields,
            "filing_status": (status.group(1).lower() if status else None)}


def import_file(conn, path: Path) -> dict:
    ensure_schema(conn)
    path = Path(path)
    parsed = parse(path)
    if parsed.get("error"):
        return {"file": path.name, "seen": 0, "inserted": 0, "skipped": 0,
                "error": parsed["error"]}

    seen = inserted = skipped = 0
    for field, amount in sorted(parsed["fields"].items()):
        seen += 1
        cur = conn.execute(
            "INSERT OR IGNORE INTO payroll_reference (pay_end, field, amount, source, file)"
            " VALUES (?,?,?,?,?)",
            (parsed["pay_end"], field, amount, SOURCE, path.name))
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    return {"file": path.name, "seen": seen, "inserted": inserted, "skipped": skipped,
            "pay_end": parsed["pay_end"], "filing_status": parsed["filing_status"]}


def latest(conn, year: int) -> dict:
    """The most recent stub's YTD figures for `year`, or {} if there are none.

    YTD is cumulative, so this is a lookup of one stub rather than a sum across
    them — summing would multiply the year by the number of stubs on file.
    """
    # On a ledger where no stub has ever been imported the table does not exist
    # yet, and an unguarded query here takes the whole budget endpoint down with
    # it. Creating it is cheaper than a try/except around every caller.
    ensure_schema(conn)
    row = conn.execute(
        "SELECT MAX(pay_end) FROM payroll_reference WHERE pay_end LIKE ?",
        (f"{year}-%",)).fetchone()
    if not row or not row[0]:
        return {}
    pay_end = row[0]
    fields = {r[0]: r[1] for r in conn.execute(
        "SELECT field, amount FROM payroll_reference WHERE pay_end = ?", (pay_end,))}
    fields["pay_end"] = pay_end
    return fields
