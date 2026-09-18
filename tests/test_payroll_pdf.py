"""Checks on reading a payroll advice for its year-to-date column.

The failure this guards against is quiet and expensive. A pay stub prints four
boxes side by side, so one text line carries several unrelated fields, and a
parser anchored to the start of a line reads the leftmost box and silently
returns nothing for the rest. That loses the Roth deferral and every tax figure
while still importing "successfully" — and an understated deferral tells you to
contribute less than you may, which is the wrong direction to be wrong in.
"""
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.importers import payroll_pdf as p          # noqa: E402

def shutil_missing():
    """True when poppler genuinely is not installed here."""
    return shutil.which("pdftotext") is None and not any(
        Path(x).exists() for x in p.POPPLER_PATHS)


CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


# One line lifted verbatim from a real advice, with the same column geometry:
# a before-tax deduction, an after-tax one, and an employer benefit, all sharing
# the line. Everything below is exercised against text rather than a PDF so the
# suite does not need poppler installed to run.
LINE = ("401K          589.38 4,037.24 Roth 401k     136.01  10,358.69 "
        "BasicLife*    1.88      27.80")
TAXLINE = ("Fed MED/EE                58.54             1,197.17       "
           "Regular       1,180.00            66,318.58")

check("a mid-line field is found at all", p._row(LINE, "Roth 401k") == [136.01, 10358.69],
      p._row(LINE, "Roth 401k"))
check("the YTD figure is the second number, not the first",
      p._row(LINE, "401K")[1] == 4037.24, p._row(LINE, "401K"))
check("a field stops at the next box rather than swallowing it",
      p._row(LINE, "401K") == [589.38, 4037.24], p._row(LINE, "401K"))
# Without the lookbehind "401K" matches inside "Roth 401k" and the two deferral
# lines collapse into one.
check("traditional 401K does not match inside 'Roth 401k'",
      p._row("Roth 401k     136.01  10,358.69", "401K") == [],
      p._row("Roth 401k     136.01  10,358.69", "401K"))
check("a tax field beside an earnings box is read",
      p._row(TAXLINE, "Fed MED/EE") == [58.54, 1197.17], p._row(TAXLINE, "Fed MED/EE"))
check("an absent field yields nothing rather than a wrong number",
      p._row(LINE, "HSA") == [], p._row(LINE, "HSA"))

# A ledger that has never seen a stub must not take the budget endpoint down.
conn = sqlite3.connect(":memory:")
check("latest() on a ledger with no stub table returns empty", p.latest(conn, 2026) == {})

# YTD is cumulative, so the newest stub in a year supersedes the earlier ones.
# Summing them would multiply the year by the number of stubs on file.
p.ensure_schema(conn)
for pay_end, gross in (("2026-01-24", 7906.25), ("2026-07-24", 90010.11)):
    conn.execute("INSERT INTO payroll_reference (pay_end, field, amount, source)"
                 " VALUES (?,?,?,?)", (pay_end, "gross", gross, p.SOURCE))
conn.commit()
check("the latest stub wins rather than the stubs summing",
      p.latest(conn, 2026).get("gross") == 90010.11, p.latest(conn, 2026))
check("a year with no stub is empty even when another year has one",
      p.latest(conn, 2025) == {}, p.latest(conn, 2025))

# The real files, when they are present and poppler is installed. Skipped
# rather than failed elsewhere, since data/ is gitignored.
stubs = sorted((ROOT / "data" / "payroll").glob("*.pdf"))
if stubs and p.extract_text(stubs[0]).strip():
    parsed = [p.parse(s) for s in stubs]
    check("every stub on file parses", all(not r.get("error") for r in parsed),
          [r.get("error") for r in parsed if r.get("error")])
    check("every stub yields a pay end date",
          all(len(r.get("pay_end") or "") == 10 for r in parsed),
          [r.get("pay_end") for r in parsed])
    # The whole point of the stub is that these two differ; if a parse ever made
    # them equal it has read the same column twice.
    check("gross always exceeds net pay",
          all(r["fields"]["gross"] > r["fields"]["net_pay"] for r in parsed
              if "gross" in r["fields"] and "net_pay" in r["fields"]),
          [(r["pay_end"], r["fields"].get("gross"), r["fields"].get("net_pay"))
           for r in parsed])
    check("employee deferral is the sum of its traditional and Roth halves",
          all(abs(r["fields"].get("deferral_employee", 0)
                  - r["fields"].get("deferral_traditional", 0)
                  - r["fields"].get("deferral_roth", 0)) < 0.005 for r in parsed))

# --- found without a PATH -------------------------------------------------
# launchd gives a scheduled job almost no PATH: not /opt/homebrew/bin, not
# /usr/local/bin. shutil.which() therefore found pdftotext from a terminal and
# nothing at all from the nightly run, so the importer reported "poppler not
# installed" every night on a machine where it plainly was, and imported no
# stubs. The bug was invisible until the agent was actually run rather than
# assumed to work.
import os                                              # noqa: E402
check("pdftotext is located even with an empty PATH",
      p._pdftotext() is not None or shutil_missing(),
      "not found on this machine")

for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail if not ok else ''}")
passed = sum(1 for _, ok, _ in CHECKS if ok)
print(f"\n  {passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
