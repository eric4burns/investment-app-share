"""A budget spreadsheet: categories down the side, months across the top.

This is the shape almost every hand-kept budget ends up in, and it is not
transactions — there is no date, no merchant, no individual purchase to import.
Loading it as if it were would invent data.

What it IS good for is the thing the bank export cannot do. A hand-kept budget
records what was actually spent, including everything bought on a card, while
this app sees only the payment to the card and nothing beneath it. So the gap
between the two, per category and per month, is a direct measurement of the
blind spot — available before a single card statement is imported, and useful
afterwards as a check that the imports are complete.

It is stored as a reference series, deliberately kept apart from the ledger.
These numbers were typed by a person, they are not double-entry, and they must
never be added to computed totals or they would count the same spending twice.

## Working out which month a column is

The hard part is the year. A column headed "Jan" is unambiguous inside a
spreadsheet a person is looking at and completely ambiguous in a file, and a
sheet covering two years usually has two blocks of the same twelve names. So a
year has to come from somewhere — the header itself, the filename, or the
caller — and when it cannot be established the import refuses rather than
picking one. Silently filing last January's grocery bill under this January
would corrupt exactly the comparison this exists to make.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

SOURCE = "budget_grid"

SCHEMA = """
CREATE TABLE IF NOT EXISTS budget_reference (
    category  TEXT NOT NULL,
    month     TEXT NOT NULL,          -- yyyy-mm
    amount    REAL NOT NULL,
    source    TEXT NOT NULL,
    PRIMARY KEY (category, month, source)
);
"""

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Rows that are arithmetic on the other rows, not categories of their own.
# Importing them would double every total.
TOTAL_ROWS = re.compile(r"^\s*(total|totals|sum|subtotal|net|balance|difference|"
                        r"remaining|left\s*over|grand\s*total)\b", re.I)


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def parse_month(header: str, default_year: int | None = None) -> str | None:
    """A column heading into yyyy-mm, or None if it is not a month at all."""
    text = (header or "").strip()
    if not text:
        return None
    # 2026-01, 2026/01
    m = re.fullmatch(r"(20\d\d)[-/](\d{1,2})", text)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    # 01/2026, 1-2026
    m = re.fullmatch(r"(\d{1,2})[-/](20\d\d)", text)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    # Jan 2026, January-2026, Jan '26
    m = re.fullmatch(r"([A-Za-z]+)\.?[\s\-']*(20\d\d|\d\d)?", text)
    if m:
        name = m.group(1).lower()
        if name in MONTHS:
            year_text = m.group(2)
            if year_text:
                year = int(year_text) if len(year_text) == 4 else 2000 + int(year_text)
            elif default_year:
                year = default_year
            else:
                return None                 # a month with no year is not a date
            return f"{year}-{MONTHS[name]:02d}"
    return None


def year_from_name(path: Path) -> int | None:
    years = re.findall(r"20\d\d", path.stem)
    # Exactly one year in the filename is a usable default. Two means the sheet
    # spans them and the filename cannot say which column is which.
    return int(years[0]) if len(set(years)) == 1 else None


def _number(value) -> float | None:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text or text in {"-", "—", "–"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        n = float(text)
    except ValueError:
        return None
    return -n if negative else n


def parse(path: Path, default_year: int | None = None) -> dict:
    default_year = default_year or year_from_name(path)
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig",
                                          errors="replace").splitlines()))
    if not rows:
        return {"error": "the file is empty", "cells": []}

    # The header is whichever of the first few rows has the MOST month-like
    # columns — a sheet often has a title, a blank line, or a note above the real
    # grid. Taking the first row with two or more of them looked equivalent and
    # was not: a sheet covering a single month has exactly one, and found no
    # header at all.
    header_at, columns = None, {}
    for i, row in enumerate(rows[:12]):
        found = {j: parse_month(c, default_year) for j, c in enumerate(row)}
        found = {j: m for j, m in found.items() if m}
        if len(found) > len(columns):
            header_at, columns = i, found
    if header_at is None:
        bare = any(parse_month(c, 2000) for row in rows[:12] for c in row)
        return {"error": ("the month columns have no year in them and the filename "
                          "does not supply one — rename it like budget_2025.csv, "
                          "or say which year it covers")
                if bare else "could not find a row of month columns",
                "cells": []}

    cells, skipped = [], []
    for row in rows[header_at + 1:]:
        if not row or not any((c or "").strip() for c in row):
            continue
        category = (row[0] or "").strip()
        if not category:
            continue
        if TOTAL_ROWS.match(category):
            skipped.append(category)
            continue
        for j, month in columns.items():
            if j >= len(row):
                continue
            amount = _number(row[j])
            if amount is None or amount == 0:
                continue
            cells.append({"category": category, "month": month,
                          "amount": round(abs(amount), 2)})
    return {"cells": cells, "months": sorted(set(columns.values())),
            "categories": sorted({c["category"] for c in cells}),
            "skipped_rows": skipped, "default_year": default_year}


def import_file(conn, path: Path, default_year: int | None = None) -> dict:
    ensure_schema(conn)
    parsed = parse(path, default_year)
    if parsed.get("error"):
        return {"file": path.name, "seen": 0, "inserted": 0, "skipped": 0,
                "error": parsed["error"]}
    source = path.stem
    n = 0
    for cell in parsed["cells"]:
        conn.execute(
            """INSERT INTO budget_reference (category, month, amount, source)
               VALUES (?,?,?,?)
               ON CONFLICT(category, month, source) DO UPDATE SET
                   amount = excluded.amount""",
            (cell["category"], cell["month"], cell["amount"], source))
        n += 1
    conn.commit()
    return {"file": path.name, "seen": len(parsed["cells"]), "inserted": n,
            "skipped": 0, "months": parsed["months"],
            "categories": len(parsed["categories"]),
            "ignored_total_rows": parsed["skipped_rows"]}


def _norm(name: str) -> str:
    """Loose match for category names typed by a person against ours."""
    text = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    # A handful of names for the same thing. Deliberately short: a big synonym
    # table would silently map things the user did not mean, and an unmapped
    # row is visible while a wrongly mapped one is not.
    aliases = {
        "rent mortgage": "rent", "housing": "rent", "mortgage": "rent",
        "food": "groceries", "grocery": "groceries", "eating out": "dining",
        "restaurants": "dining", "gas": "transport", "fuel": "transport",
        "car": "transport", "auto": "transport", "utility": "utilities",
        "phone": "utilities", "internet": "utilities", "subscription": "subscriptions",
        "streaming": "subscriptions", "medical": "health", "pet": "pets",
        "clothing": "shopping", "clothes": "shopping", "tax": "taxes",
        "vacation": "travel", "trips": "travel",
    }
    return aliases.get(text, text)


def compare(conn, classified, source: str | None = None) -> dict:
    """Your spreadsheet against what the ledger computes, month by month.

    The differences are the POINT, not errors to be reconciled away. Each side
    knows things the other does not: a hand-kept budget records cash spending and
    anything bought on a card whose export has not been imported, while the
    ledger records everything that moved through an account whether or not it was
    ever written down. So a category where the sheet is higher is usually
    spending the app cannot see; one where the ledger is higher is usually
    spending that never made it into the sheet.
    """
    rows = reference(conn, source)
    if not rows:
        return {"available": False, "rows": [], "months": [], "sources": []}

    ours: dict[tuple[str, str], float] = {}
    our_categories = set()
    for t in classified:
        if t.get("category_kind") != "expense" or not t.get("category"):
            continue
        month = (t.get("txn_date") or "")[:7]
        if not month:
            continue
        key = (_norm(t["category"]), month)
        ours[key] = ours.get(key, 0.0) + abs(float(t.get("amount") or 0.0))
        our_categories.add(_norm(t["category"]))

    theirs: dict[tuple[str, str], float] = {}
    their_names: dict[str, str] = {}
    for r in rows:
        key = (_norm(r["category"]), r["month"])
        theirs[key] = theirs.get(key, 0.0) + float(r["amount"])
        their_names.setdefault(_norm(r["category"]), r["category"])

    months = sorted({m for _c, m in theirs})
    # Only months the sheet actually covers, and only ones the ledger also has
    # data for — comparing against a month the app has no transactions in
    # reports the entire sheet as a discrepancy.
    our_months = {m for _c, m in ours}
    months = [m for m in months if m in our_months]

    by_category = []
    for category in sorted({c for c, _m in theirs}):
        sheet = round(sum(theirs.get((category, m), 0.0) for m in months), 2)
        app = round(sum(ours.get((category, m), 0.0) for m in months), 2)
        if not sheet and not app:
            continue
        by_category.append({
            "category": their_names.get(category, category),
            "matched": category in our_categories,
            "sheet": sheet, "app": app,
            "difference": round(app - sheet, 2),
            "months": [{"month": m,
                        "sheet": round(theirs.get((category, m), 0.0), 2),
                        "app": round(ours.get((category, m), 0.0), 2)}
                       for m in months],
        })
    by_category.sort(key=lambda r: -abs(r["difference"]))

    # Categories the ledger has that the sheet never mentions, which is the other
    # direction of the same question.
    missing = sorted(c for c in our_categories if c not in {r for r, _m in theirs})

    sheet_total = round(sum(r["sheet"] for r in by_category), 2)
    app_total = round(sum(r["app"] for r in by_category), 2)
    return {
        "available": True,
        "rows": by_category,
        "months": months,
        "sources": sorted({r["source"] for r in rows}),
        "sheet_total": sheet_total,
        "app_total": app_total,
        "difference": round(app_total - sheet_total, 2),
        "unmatched_categories": [r["category"] for r in by_category if not r["matched"]],
        "not_in_sheet": missing,
    }


def reference(conn, source: str | None = None) -> list[dict]:
    ensure_schema(conn)
    sql = "SELECT category, month, amount, source FROM budget_reference"
    args: list = []
    if source:
        sql += " WHERE source = ?"
        args.append(source)
    return [dict(r) for r in conn.execute(sql + " ORDER BY month, category", args)]
