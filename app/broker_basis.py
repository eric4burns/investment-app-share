"""The broker's own cost basis, when the app's FIFO figure disagrees with it.

`holdings.build_lots` matches lots FIFO, which is a reasonable default and is
not what this user's broker does. On 2026-09-10 Fidelity reported IREN at
$19.63 a share against the app's $25.69 — a $25,633 difference in basis and
about $18,000 in unrealised gain on the largest position in the book. Neither
figure is a bug: the broker allows a lot to be chosen per sale, and picking
high-cost lots to sell is the tax-sensible thing to do, so the remaining basis
is far below FIFO's. No lot rule reproduces it, because there is no rule — the
choice was made sale by sale.

So the basis is imported rather than derived. The broker's number is the
authoritative one: it is what the statement says, what the 1099 will say, and
what the tax figures have to be built on.

    python3 -m app.broker_basis show
    python3 -m app.broker_basis set IREN 4227.912 82987.98 --as-of 2026-09-10

Only the SYMBOLS present are overridden. Anything not imported keeps the FIFO
figure, and every consumer can tell which it is looking at, because a position
carries `basis_source` of "broker" or "fifo". A number that silently changes
meaning depending on whether somebody remembered to import a file is worse than
a number that is merely wrong.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from .ledger import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_basis (
    symbol   TEXT PRIMARY KEY,
    quantity REAL NOT NULL,
    basis    REAL NOT NULL,
    as_of    TEXT NOT NULL,
    source   TEXT NOT NULL DEFAULT 'fidelity'
);
"""

# How far the broker's share count may drift from the ledger's before the
# imported basis is refused. Beyond this the two are describing different
# positions — usually because transactions since the import are missing — and
# applying a basis for 20,226 shares to a ledger holding 18,125 would quietly
# overstate the cost of every share.
QTY_TOLERANCE = 0.01


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def store(conn, rows: list[dict]) -> int:
    ensure_schema(conn)
    n = 0
    for r in rows:
        if r.get("basis") is None or r.get("quantity") is None:
            continue
        conn.execute(
            """INSERT INTO broker_basis (symbol, quantity, basis, as_of, source)
               VALUES (?,?,?,?,?)
               ON CONFLICT(symbol) DO UPDATE SET
                 quantity=excluded.quantity, basis=excluded.basis,
                 as_of=excluded.as_of, source=excluded.source""",
            (r["symbol"].upper(), float(r["quantity"]), float(r["basis"]),
             r.get("as_of") or date.today().isoformat(), r.get("source") or "fidelity"))
        n += 1
    conn.commit()
    return n


def lookup(conn) -> dict[str, dict]:
    ensure_schema(conn)
    return {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM broker_basis")}


def apply_to(positions: list[dict], book: dict[str, dict]) -> list[dict]:
    """Replace the FIFO basis with the broker's where the share counts agree.

    The share count is the check that the two are talking about the same
    position. When they disagree the ledger is usually behind — a week of
    transactions not yet exported — and the position is left on FIFO with
    `basis_stale` set, so the interface can say why rather than showing a
    confident wrong number.
    """
    for p in positions:
        b = book.get(p.get("symbol"))
        p["basis_source"] = "fifo"
        if not b:
            continue
        qty = p.get("quantity") or 0
        if qty and abs(qty - b["quantity"]) / max(qty, 1e-9) <= QTY_TOLERANCE:
            p["cost_basis"] = round(b["basis"], 2)
            p["avg_cost"] = round(b["basis"] / qty, 4) if qty else None
            p["basis_source"] = "broker"
            p["basis_as_of"] = b["as_of"]
            # Every figure derived from the basis moves with it. The percent
            # was once left on FIFO: IREN showed +$102,321 beside +70.6%, and
            # risk.py back-derives cost from the percent, so it was wrong twice.
            if p.get("value") is not None:
                p["unrealised"] = round(p["value"] - p["cost_basis"], 2)
                p["unrealised_pct"] = ((p["value"] - p["cost_basis"]) / p["cost_basis"]
                                       if abs(p["cost_basis"]) > 1e-9 else None)
            else:
                p["unrealised"] = None
                p["unrealised_pct"] = None
        else:
            p["basis_stale"] = {"broker_qty": b["quantity"], "ledger_qty": round(qty, 4),
                                "as_of": b["as_of"]}
    return positions


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.broker_basis")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    s = sub.add_parser("set")
    s.add_argument("symbol"); s.add_argument("quantity", type=float)
    s.add_argument("basis", type=float)
    s.add_argument("--as-of", default=date.today().isoformat())
    args = p.parse_args(argv)
    conn = connect()
    if args.cmd == "set":
        store(conn, [{"symbol": args.symbol, "quantity": args.quantity,
                      "basis": args.basis, "as_of": args.as_of}])
        print(f"{args.symbol.upper()}: {args.quantity:,.4f} shares, basis {args.basis:,.2f}")
        return 0
    book = lookup(conn)
    if not book:
        print("no broker basis imported")
        return 0
    print(f"{'symbol':<8}{'quantity':>14}{'basis':>14}{'per share':>12}  as of")
    for sym, b in sorted(book.items()):
        print(f"{sym:<8}{b['quantity']:>14,.4f}{b['basis']:>14,.2f}"
              f"{b['basis'] / b['quantity']:>12,.2f}  {b['as_of']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
