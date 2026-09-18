"""Which book each holding is in, and what that changes about its verdict.

    python3 -m app.books                     # list
    python3 -m app.books set IREN conviction --trade-around --note "..."

## The three books

Decided 2026-09-02: the portfolio is three books with different rules, not
one book with mixed intentions.

  * **swing** — read off the chart, held for days to weeks. The verdict
    engine's calls apply as written: buy, add, hold, trim, sell.
  * **conviction** — bought on a thesis, accumulated on a schedule, scaled
    up into weakness. A broken trend on this book is an accumulation zone,
    not an exit, so the engine never says *sell* here: the same evidence
    reads as *hold* with the DCA tier beside it, and the level that would
    have been the sell call's flip is shown as the level under which the
    thesis itself is in question. *Trim* still fires, because trimming into
    strength is how a conviction position is kept from becoming the whole
    book.
  * **trade-around** is not a third book but a flag on a conviction name:
    the core is never sold, and a slice is traded against it — sold into
    strength, bought back lower — to grow the share count. Phase B builds
    the tools; the flag is recorded now so nothing has to be re-entered.

Assigned 2026-09-03: IREN and DGXX conviction (IREN traded around),
everything else swing. SIVEF is a swing with a note: conviction until it
runs, and sold into a run like June's.

A name not in the table is treated as **swing**, because that is the book
whose calls need no special handling and the one a new position most
likely belongs to until said otherwise.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .ledger import connect

BOOKS = ("swing", "conviction")

# How long a position in each book is meant to be held, in the words the
# reading uses as its heading.
#
# This replaces the daily/weekly/monthly grid as the thing shown to the reader.
# The user on 2026-09-09: "The day week month thing doesn't really click. The
# values depend on the length of the trade." A grid of three verdicts asks the
# reader to blend three timeframes into one decision, which is the work the app
# was supposed to do; the holding period is the frame they actually think in,
# and the book already records it. The engine still weighs the longer timeframe
# more heavily — that rule is about how evidence is combined, not about how the
# answer is presented.
HORIZON = {"swing": "days to weeks", "conviction": "months"}


def horizon(book: str | None) -> str:
    return HORIZON.get(book or "swing", HORIZON["swing"])
DEFAULT_BOOK = "swing"

SCHEMA = """
CREATE TABLE IF NOT EXISTS position_books (
    symbol       TEXT PRIMARY KEY,
    book         TEXT NOT NULL,
    trade_around INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    set_at       TEXT NOT NULL
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(position_books)")}
    if "core_shares" not in cols:
        # The share count that is never sold on a traded-around name.
        conn.execute("ALTER TABLE position_books ADD COLUMN core_shares REAL")


def set_core(conn, symbol: str, core_shares: float | None) -> dict:
    ensure_schema(conn)
    symbol = (symbol or "").strip().upper()
    if not conn.execute("SELECT 1 FROM position_books WHERE symbol=?", (symbol,)).fetchone():
        return {"error": f"{symbol} has no book yet; set the book first"}
    if core_shares is not None and core_shares < 0:
        return {"error": "a core cannot be negative"}
    conn.execute("UPDATE position_books SET core_shares=?, set_at=? WHERE symbol=?",
                 (core_shares, datetime.now().isoformat(timespec="seconds"), symbol))
    return {"ok": True, "symbol": symbol, "core_shares": core_shares}


def set_book(conn, symbol: str, book: str, trade_around: bool | None = None,
             note: str | None = None) -> dict:
    ensure_schema(conn)
    symbol = (symbol or "").strip().upper()
    if book not in BOOKS:
        return {"error": f"unknown book {book!r}", "allowed": list(BOOKS)}
    if not symbol:
        return {"error": "a symbol is needed"}
    existing = conn.execute("SELECT * FROM position_books WHERE symbol=?", (symbol,)).fetchone()
    ta = (int(bool(trade_around)) if trade_around is not None
          else (existing["trade_around"] if existing else 0))
    if book != "conviction":
        ta = 0                            # trading around needs a core to trade around
    nt = note if note is not None else (existing["note"] if existing else None)
    conn.execute("""INSERT INTO position_books (symbol, book, trade_around, note, set_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET book=excluded.book,
                      trade_around=excluded.trade_around, note=excluded.note, set_at=excluded.set_at""",
                 (symbol, book, ta, nt, datetime.now().isoformat(timespec="seconds")))
    return {"ok": True, "symbol": symbol, "book": book, "trade_around": bool(ta), "note": nt}


def lookup(conn) -> dict[str, dict]:
    ensure_schema(conn)
    return {r["symbol"]: {"book": r["book"], "trade_around": bool(r["trade_around"]),
                          "note": r["note"], "set_at": r["set_at"],
                          "core_shares": r["core_shares"]}
            for r in conn.execute("SELECT * FROM position_books")}


def attach(conn, positions: list[dict]) -> list[dict]:
    """Put the book on each position dict, defaulting to swing."""
    by = lookup(conn)
    for p in positions:
        b = by.get((p.get("symbol") or "").upper())
        p["book"] = b["book"] if b else DEFAULT_BOOK
        p["trade_around"] = bool(b["trade_around"]) if b else False
        p["book_note"] = b["note"] if b else None
        p["book_default"] = b is None
    return positions


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.books")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("set")
    s.add_argument("symbol"); s.add_argument("book", choices=BOOKS)
    s.add_argument("--trade-around", action="store_true")
    s.add_argument("--no-trade-around", action="store_true")
    s.add_argument("--note", default=None)
    args = p.parse_args(argv)
    conn = connect()
    if args.cmd == "set":
        ta = True if args.trade_around else (False if args.no_trade_around else None)
        r = set_book(conn, args.symbol, args.book, ta, args.note)
        conn.commit()
        print(r)
        return 0 if r.get("ok") else 1
    for sym, b in sorted(lookup(conn).items()):
        print(f"  {sym:<7} {b['book']:<11}{' + trade-around' if b['trade_around'] else '':<16} {b['note'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
