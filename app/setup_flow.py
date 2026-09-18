"""The first-run screen's back end: what a fresh install still needs, a file
dropped in the browser saved into the right folder and imported, and the
price key and tax profile written locally.

This is what turns the archive a friend downloads from a folder of code into
an app: they never see data/, never run an importer by hand, never edit
config.json. Nothing here leaves the machine — the exports are saved under
data/ beside the ledger, the Alpaca key goes to data/.alpaca, and the only
network call the app ever makes is to fetch share prices.
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
from datetime import date
from pathlib import Path

from . import config, prices, reconcile
from .importers import budget_grid, card_csv, fidelity_csv, frost_ofx, payroll_pdf, robinhood_csv
from .ledger import ROOT

# What kinds of file the screen accepts, where each goes, and the importer.
KINDS = {
    "fidelity": {"folder": "fidelity", "ext": {".csv"}, "label": "Fidelity activity CSV",
                 "importer": lambda conn, p: fidelity_csv.import_file(conn, p)},
    "robinhood": {"folder": "robinhood", "ext": {".csv"}, "label": "Robinhood activity CSV",
                  "importer": lambda conn, p: robinhood_csv.import_file(conn, p)},
    "bank": {"folder": "bank", "ext": {".ofx", ".qfx"}, "label": "Bank OFX / QFX (Web Connect)",
             "importer": lambda conn, p: frost_ofx.import_file(conn, p)},
    "cards": {"folder": "cards", "ext": {".csv"}, "label": "Credit card CSV (Chase, Amex, Capital One…)",
              "importer": lambda conn, p: card_csv.import_file(conn, p)},
    "payroll": {"folder": "payroll", "ext": {".pdf"}, "label": "Pay stub PDF",
                "importer": lambda conn, p: payroll_pdf.import_file(conn, p)},
    "budget": {"folder": "budget", "ext": {".csv"}, "label": "Budget spreadsheet CSV",
               "importer": lambda conn, p: budget_grid.import_file(conn, p)},
}

# Where to find the export in each place, written for somebody who has never
# done it. Kept here, not in the page, so the same words reach the CLI.
HOW_TO_EXPORT = {
    "fidelity": ["Log in at fidelity.com and open Accounts & Trade → Portfolio.",
                 "Click Activity & Orders.",
                 "Set the date range to as far back as it allows (a year at a time is fine; add each year as its own file).",
                 "Click Download (the arrow icon) and choose CSV.",
                 "Drop that file here as Fidelity."],
    "robinhood": ["Open Robinhood on the web and go to Account → Reports and statements (or History).",
                  "Choose Reports, Generate a new report, Account activity, for all time.",
                  "When it is ready, download the CSV.",
                  "Drop it here as Robinhood."],
    "bank": ["In your bank's online banking find Download or Export on the checking account.",
             "Choose the Quicken / QuickBooks / Web Connect format — the file ends in .ofx or .qfx.",
             "Take the longest range offered.",
             "Drop it here as Bank."],
    "cards": ["On the card issuer's site open the card's activity or statements.",
              "Choose Download activity, CSV, for the longest range offered.",
              "Drop each card's file here as Card."],
    "payroll": ["Download a recent pay stub as a PDF from your payroll site.",
                "Drop it here as Pay stub (it needs poppler installed to read PDFs; without it, skip this)."],
}


def status(conn) -> dict:
    """What the install has and what it still needs."""
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    files = {k: len([p for p in (ROOT / "data" / v["folder"]).glob("*") if p.suffix.lower() in v["ext"]])
             for k, v in KINDS.items()}
    cfg = config.load()
    from . import sample
    return {"transactions": n, "files": files, "alpaca": prices.alpaca_credentials() is not None,
            "sample": sample.loaded(conn),
            "filing_status": cfg.get("filing_status"), "age": cfg.get("age"),
            "python": sys.version.split()[0], "platform": platform.system(),
            "kinds": {k: {"label": v["label"], "ext": sorted(v["ext"]), "steps": HOW_TO_EXPORT.get(k, [])} for k, v in KINDS.items()}}


def safe_name(filename: str) -> str:
    base = Path(filename or "upload").name
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" .") or "upload"
    return base[:120]


def save_upload(kind: str, filename: str, data: bytes) -> Path:
    """Write a dropped file into its data/ folder; a same-named file gets a suffix."""
    spec = KINDS.get(kind)
    if not spec:
        raise ValueError(f"unknown file kind {kind!r}")
    name = safe_name(filename)
    if Path(name).suffix.lower() not in spec["ext"]:
        raise ValueError(f"a {spec['label']} should end in {' or '.join(sorted(spec['ext']))}, not {Path(name).suffix or 'nothing'}")
    if not data or len(data) < 20:
        raise ValueError("the file is empty")
    folder = ROOT / "data" / spec["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    i = 1
    while target.exists() and target.read_bytes() != data:
        target = folder / f"{Path(name).stem}-{i}{Path(name).suffix}"
        i += 1
    target.write_bytes(data)
    return target


def import_upload(conn, kind: str, filename: str, data: bytes) -> dict:
    """Save and import one dropped file, then pair internal transfers."""
    path = save_upload(kind, filename, data)
    r = KINDS[kind]["importer"](conn, path)
    try:
        reconcile.pair_internal_transfers(conn)
    except Exception:                                          # noqa: BLE001
        pass
    conn.commit()
    return {"kind": kind, "file": path.name, "seen": r.get("seen"), "inserted": r.get("inserted"),
            "skipped": r.get("skipped"), "error": r.get("error"), "account": r.get("account"), "sign": r.get("sign")}


def write_alpaca(key: str, secret: str) -> bool:
    key, secret = (key or "").strip(), (secret or "").strip()
    if not key or not secret:
        raise ValueError("both the key id and the secret are needed")
    prices.ALPACA_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _write_private(prices.ALPACA_KEY_FILE, f"{key}\n{secret}\n")
    return True


def _write_private(path: Path, text: str) -> None:
    """Owner-only from the first byte. write_text takes the umask, which is
    0644 on a Mac, so the Alpaca secret and the Gmail app password sat
    world-readable; a chmod after the fact leaves the same window open."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)                      # an existing file keeps its old mode otherwise


def write_profile(filing_status: str | None, age: int | None) -> dict:
    """Filing status and age into config.json; everything else stays."""
    path = config.CONFIG_PATH
    cfg = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text()) or {}
        except ValueError:
            cfg = {}
    if filing_status in ("single", "married_jointly", "head_of_household"):
        cfg["filing_status"] = filing_status
    if age:
        cfg["age"] = int(age)
    _write_private(path, json.dumps(cfg, indent=2) + "\n")
    return {"filing_status": cfg.get("filing_status"), "age": cfg.get("age")}


def refresh_prices(conn) -> dict:
    """Benchmarks and every held name, so the first screen after import is not blank."""
    out = {"benchmarks": {}, "holdings": None}
    for b in ("SPY", "QQQ"):
        try:
            r = prices.sync_benchmark(conn, b)
            out["benchmarks"][b] = "ok" if r.get("ok") else r.get("error")
        except Exception as exc:                               # noqa: BLE001
            out["benchmarks"][b] = f"{type(exc).__name__}: {exc}"
    # With no Alpaca key the fetch falls through to Yahoo (prices.OTC_FALLBACK),
    # so a friend sees priced holdings without signing up for anything; the
    # key is the better feed, not the price of admission.
    try:
        r = prices.sync_holdings(conn, "2018-01-01", date.today().isoformat())
        out["holdings"] = {"priced": len(r.get("priced", [])), "failed": r.get("failed", [])}
    except Exception as exc:                                   # noqa: BLE001
        out["holdings"] = {"error": f"{type(exc).__name__}: {exc}"}
    conn.commit()
    return out


def parse_multipart(content_type: str, body: bytes) -> tuple[dict, list[tuple[str, str, bytes]]]:
    """Fields and files out of a multipart/form-data body, standard library only
    (the cgi module is gone in 3.13)."""
    from email import policy
    from email.parser import BytesParser
    msg = BytesParser(policy=policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    fields, files = {}, []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.append((name or "file", filename, payload))
        else:
            fields[name or ""] = payload.decode("utf-8", "replace").strip()
    return fields, files
