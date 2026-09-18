"""Sample data, so a fresh copy shows the whole app before a single export exists.

    python3 -m app.sample load       # into an EMPTY ledger only
    python3 -m app.sample clear      # remove it again, nothing else touched
    python3 -m app.sample write DIR  # just write the three files

A friend who opens the archive sees an empty ledger and a Get started screen
asking for broker exports they have not gathered yet — and at that moment
the app is a form, not an app. "Load sample data" fills it in ten seconds
with a made-up year of one household: a brokerage account with a handful of
listed names and their dividends, a checking account with pay, rent, bills
and card payments, and a credit card with the spending. Every tab then has
something on it, and "Remove sample data" takes it all out again.

The files are written in the SAME formats the real exports arrive in and go
through the same importers, so what a friend sees is what their own exports
will produce — not a demo database with its own shape. The names are real
tickers (prices come from the same feed), the people, accounts and numbers
are invented, and every account is named "Sample …" so nothing here can be
mistaken for a real statement.

Loading refuses unless the ledger has no transactions at all; clearing
refuses unless the ledger was marked as holding the sample. Both rules exist
so sample rows can never sit beside real ones.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from .ledger import connect

MARK = "sample_data"

# One household's year. Dates step from the first Monday of last year's
# September so the ledger always ends near today and the charts are full.
START = date.today().replace(day=1) - timedelta(days=365)

BUYS = [  # (month offset, symbol, name, quantity, price)
    (0, "VTI", "VANGUARD TOTAL STOCK MARKET ETF", 20, 268.40),
    (0, "AAPL", "APPLE INC", 15, 226.80),
    (1, "MSFT", "MICROSOFT CORP", 8, 412.15),
    (2, "NVDA", "NVIDIA CORP", 30, 118.60),
    (3, "AMD", "ADVANCED MICRO DEVICES INC", 25, 140.20),
    (4, "VTI", "VANGUARD TOTAL STOCK MARKET ETF", 10, 281.05),
    (5, "SOFI", "SOFI TECHNOLOGIES INC", 200, 14.85),
    (7, "NVDA", "NVIDIA CORP", 10, 132.40),
    (9, "AAPL", "APPLE INC", 5, 236.10),
]
SELLS = [(6, "AMD", "ADVANCED MICRO DEVICES INC", 10, 158.70), (10, "SOFI", "SOFI TECHNOLOGIES INC", 100, 18.30)]
DIVIDENDS = [("VTI", 0.92, (2, 5, 8, 11)), ("AAPL", 0.25, (1, 4, 7, 10)), ("MSFT", 0.83, (2, 5, 8, 11))]

MERCHANTS = [  # (description, amount, days of the month it lands on)
    ("NETFLIX.COM", 15.49, (3,)), ("SPOTIFY USA", 11.99, (7,)), ("ROCKWALL POWER & LIGHT", None, (12,)),
    ("H-E-B #482 ROCKWALL TX", None, (2, 9, 16, 23)), ("SHELL OIL 57430118", None, (5, 19)),
    ("CHIPOTLE 1834", None, (4, 11, 18, 25)), ("AMAZON.COM*2K7QW", None, (8, 21)),
    ("CVS/PHARMACY #0421", None, (14,)), ("PROGRESSIVE INS PREM", 118.00, (20,)),
]
VARIABLE = {"ROCKWALL POWER & LIGHT": (95, 180), "H-E-B #482 ROCKWALL TX": (48, 165), "SHELL OIL 57430118": (38, 62),
            "CHIPOTLE 1834": (12, 31), "AMAZON.COM*2K7QW": (18, 140), "CVS/PHARMACY #0421": (9, 44)}


def _rand(seed: int, lo: float, hi: float) -> float:
    """Deterministic 'randomness': the same files every time, so a re-load is
    a re-import and nothing doubles."""
    x = (seed * 9301 + 49297) % 233280 / 233280.0
    return round(lo + (hi - lo) * x, 2)


def _month(n: int, day: int = 1) -> date:
    y, m = START.year, START.month + n
    while m > 12:
        y, m = y + 1, m - 12
    return date(y, m, min(day, 28))     # may lie after today; every writer skips those


def fidelity_rows() -> list[list]:
    rows: list[list] = []
    acct, num = "Sample Individual - TOD", "S00000001"

    def row(d: date, action: str, sym: str, desc: str, price, qty, amount) -> list | None:
        if d > date.today():
            return None
        return [d.strftime("%m/%d/%Y"), acct, num, action, sym, desc, "Cash", 0, "", "USD",
                price if price is not None else "", qty if qty is not None else "", 0, 0, "", "", round(amount, 2), d.strftime("%m/%d/%Y")]
    rows.append(row(_month(0, 2), "ELECTRONIC FUNDS TRANSFER RECEIVED (Cash)", "", "No Description", None, None, 20000.0))
    for n in (3, 6, 9):
        rows.append(row(_month(n, 2), "ELECTRONIC FUNDS TRANSFER RECEIVED (Cash)", "", "No Description", None, None, 3000.0))
    for n, sym, name, qty, px in BUYS:
        rows.append(row(_month(n, 6), f"YOU BOUGHT {name} ({sym}) (Cash)", sym, name, px, qty, -qty * px))
    for n, sym, name, qty, px in SELLS:
        rows.append(row(_month(n, 15), f"YOU SOLD {name} ({sym}) (Cash)", sym, name, px, -qty, qty * px))
    events = sorted([(n, s, q) for n, s, _, q, _ in BUYS] + [(n, s, -q) for n, s, _, q, _ in SELLS])
    for sym, per_share, months in DIVIDENDS:
        for n in months:
            qty = sum(q for (m, s, q) in events if s == sym and m <= n)
            if qty > 0:
                name = next(nm for _, s, nm, _, _ in BUYS if s == sym)
                rows.append(row(_month(n, 20), f"DIVIDEND RECEIVED {name} ({sym}) (Cash)", sym, name, None, 0, round(qty * per_share, 2)))
    for n in range(0, 13):
        rows.append(row(_month(n, 28), "DIVIDEND RECEIVED FIDELITY GOVERNMENT MONEY MARKET (SPAXX) (Cash)", "SPAXX",
                        "FIDELITY GOVERNMENT MONEY MARKET", None, 0, _rand(n + 7, 4.0, 19.0)))
    rows = [r for r in rows if r]
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def fidelity_csv() -> str:
    head = ("Run Date,Account,Account Number,Action,Symbol,Description,Type,Exchange Quantity,Exchange Currency,"
            "Currency,Price,Quantity,Exchange Rate,Commission,Fees,Accrued Interest,Amount,Settlement Date")
    lines = [head] + [",".join(f'"{v}"' if isinstance(v, str) and "," in v else str(v) for v in r) for r in fidelity_rows()]
    lines += ["", '"Sample data written by the Investment App. Not a statement from any broker."']
    return "\n".join(lines) + "\n"


def bank_ofx() -> str:
    blocks = []
    n = 0

    def trn(d: date, kind: str, amount: float, name: str, memo: str):
        nonlocal n
        if d > date.today():
            return
        n += 1
        blocks.append(f"<STMTTRN><TRNTYPE>{kind}<DTPOSTED>{d:%Y%m%d}120000<TRNAMT>{amount:.2f}"
                      f"<FITID>SAMPLE{n:05d}<NAME>{name}<MEMO>{memo}</STMTTRN>")
    for m in range(0, 13):
        for day in (1, 15):
            trn(_month(m, day), "CREDIT", 3120.00, "ACME ROBOTICS PAYROLL", "Direct Deposit")
        trn(_month(m, 2), "DEBIT", -1650.00, "OAKRIDGE APARTMENTS RENT", "Electronic Debit")
        trn(_month(m, 10), "DEBIT", -_rand(m + 31, 55, 85), "AT&T BILL PAYMENT", "Electronic Debit")
        trn(_month(m, 24), "DEBIT", -_rand(m + 53, 900, 1600), "SAMPLE CARD PAYMENT", "Electronic Debit")
        if m in (0, 3, 6, 9):
            trn(_month(m, 5), "DEBIT", -1000.00, "FID BKG SVC LLC MONEYLINE", "Electronic Debit")
        if m == 0:
            trn(_month(0, 3), "DEBIT", -20000.00, "FID BKG SVC LLC MONEYLINE", "Electronic Debit")
        if m % 2 == 1:
            trn(_month(m, 17), "DEBIT", -_rand(m + 71, 40, 120), "VENMO PAYMENT", "Debit")
    body = "".join(blocks)
    return ("OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n\n<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD"
            "<BANKACCTFROM><BANKID>000000000<ACCTID>SAMPLE-CHK-1<ACCTTYPE>CHECKING</BANKACCTFROM>"
            f"<BANKTRANLIST>{body}</BANKTRANLIST><LEDGERBAL><BALAMT>8412.77</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>\n")


def card_csv() -> str:
    lines = ["Transaction Date,Post Date,Description,Category,Type,Amount"]
    for m in range(0, 13):
        for desc, fixed, days in MERCHANTS:
            for i, day in enumerate(days):
                d = _month(m, day)
                if d > date.today():
                    continue
                amt = fixed if fixed is not None else _rand(m * 31 + day + i * 7 + len(desc), *VARIABLE[desc])
                if desc == "NETFLIX.COM" and m >= 8:
                    amt = 17.99            # a price rise, so the Recurring tab has one to show
                lines.append(f"{d:%m/%d/%Y},{d:%m/%d/%Y},{desc},Shopping,Sale,-{amt:.2f}")
        pay = _month(m, 24)
        if pay <= date.today():
            lines.append(f"{pay:%m/%d/%Y},{pay:%m/%d/%Y},Payment Thank You-Mobile,,Payment,{_rand(m + 53, 900, 1600):.2f}")
    return "\n".join(lines) + "\n"


def write(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    files = {"fidelity": folder / "sample_fidelity.csv", "bank": folder / "sample_checking.ofx",
             "cards": folder / "sample_visa.csv"}
    files["fidelity"].write_text(fidelity_csv())
    files["bank"].write_text(bank_ofx())
    files["cards"].write_text(card_csv())
    return files


def loaded(conn) -> bool:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (MARK,)).fetchone()
    return bool(row and row["value"] == "1")


def load(conn, log=None) -> dict:
    """Write the three files to a temp folder and import them, on an empty ledger only."""
    from . import reconcile
    from .importers import card_csv as cards, fidelity_csv as fid, frost_ofx as ofx
    say = log or (lambda *_: None)
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    if n:
        return {"error": f"the ledger already holds {n:,} transactions; sample data only goes into an empty one"}
    with tempfile.TemporaryDirectory() as tmp:
        files = write(Path(tmp))
        out = {}
        out["fidelity"] = fid.import_file(conn, files["fidelity"])
        out["bank"] = ofx.import_file(conn, files["bank"], account_name="Sample Checking")
        out["cards"] = cards.import_file(conn, files["cards"], account_name="Sample Visa")
    try:
        reconcile.pair_internal_transfers(conn)
    except Exception:                                          # noqa: BLE001
        pass
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, '1')", (MARK,))
    conn.commit()
    for k, r in out.items():
        say(f"  {k}: {r.get('inserted')} rows")
    return {"loaded": {k: r.get("inserted") for k, r in out.items()},
            "transactions": conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]}


# Everything the importers and the import-time derivations write, and nothing
# else: prices, the watchlist, categories and rules, drawings all stay.
CLEAR_TABLES = ["transactions", "import_runs", "broker_basis", "cash_anchors", "payroll_reference", "accounts", "institutions"]


def clear(conn, log=None) -> dict:
    """Remove the sample rows. Refuses unless the ledger is marked as sample."""
    say = log or (lambda *_: None)
    if not loaded(conn):
        return {"error": "this ledger is not marked as holding sample data; nothing removed"}
    removed = {}
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in CLEAR_TABLES:
        if t in have:
            removed[t] = conn.execute(f"DELETE FROM {t}").rowcount
    # Calls the journal derived from the sample trades (source 'trade').
    if "decisions" in have:
        removed["decisions"] = conn.execute("DELETE FROM decisions WHERE source='trade'").rowcount
    conn.execute("DELETE FROM meta WHERE key=?", (MARK,))
    conn.commit()
    say(f"  removed {removed}")
    return {"removed": removed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["load", "clear", "write"])
    ap.add_argument("dir", nargs="?")
    args = ap.parse_args(argv)
    if args.cmd == "write":
        files = write(Path(args.dir or "sample-out"))
        print("\n".join(str(p) for p in files.values()))
        return 0
    conn = connect()
    r = load(conn, log=print) if args.cmd == "load" else clear(conn, log=print)
    print(r.get("error") or r)
    return 1 if r.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
