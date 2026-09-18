"""Insider transactions, from the SEC's own Form 4 filings.

    python3 -m app.insiders sync            # every held and watched name
    python3 -m app.insiders sync --symbol IREN
    python3 -m app.insiders show IREN

Free, keyless and official: EDGAR is the source every paid "insider activity"
screen is reading from, one filing behind. Each Form 4 is an XML document
listing the reporting person, their role, and every transaction — with a
one-letter code that is the whole point:

    P  open-market purchase        the only unambiguous vote of confidence
    S  open-market sale            ambiguous: tax, diversification, a house
    A  grant or award              compensation, not a decision
    M  option exercise             usually paired with an S
    F  shares withheld for tax     mechanical
    G  gift                        estate planning

Only P and S are open-market decisions, so only they are summed into the
"bought" and "sold" figures. Awards and exercises are stored, because they
explain a sale that follows, but they carry no weight.

This is CONTEXT until the replay has measured it. Whether insider buying
predicts anything on this book is a question the Phase 3 machinery can
answer once the history is stored — which is why two years are pulled rather
than the ninety days the screen shows.

EDGAR asks for ten requests a second at most and a User-Agent that names the
caller; both are respected here, and the one-off sync of the whole list is
the only time it comes close to mattering.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta

from . import sectors
from .ledger import connect, retry_locked

SCHEMA = """
CREATE TABLE IF NOT EXISTS insider_trades (
    symbol     TEXT NOT NULL,
    accession  TEXT NOT NULL,          -- the filing
    seq        INTEGER NOT NULL,       -- transaction number within it
    filed      TEXT NOT NULL,
    txn_date   TEXT,
    owner      TEXT,
    title      TEXT,
    code       TEXT,                   -- P S A M F G ...
    acquired   TEXT,                   -- A or D
    shares     REAL,
    price      REAL,
    post       REAL,                   -- shares owned after
    PRIMARY KEY (accession, seq)
);
CREATE INDEX IF NOT EXISTS ix_insider_symbol ON insider_trades (symbol, txn_date);
CREATE TABLE IF NOT EXISTS insider_fetches (
    symbol TEXT PRIMARY KEY, checked_at TEXT NOT NULL, outcome TEXT
);
"""

OPEN_MARKET = {"P": "bought", "S": "sold"}
CODE_LABEL = {"P": "open-market purchase", "S": "open-market sale", "A": "award",
              "M": "option exercise", "F": "tax withholding", "G": "gift",
              "C": "conversion", "D": "disposition to issuer", "X": "option exercise"}
FRESH_HOURS = 20
SEC_PAUSE = 0.12                      # under the ten-per-second limit


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _fresh(conn, symbol: str) -> bool:
    row = conn.execute("SELECT checked_at FROM insider_fetches WHERE symbol=?", (symbol,)).fetchone()
    if not row:
        return False
    try:
        when = datetime.fromisoformat(row["checked_at"])
    except ValueError:
        return False
    return (datetime.now() - when) < timedelta(hours=FRESH_HOURS)


def _mark(conn, symbol: str, outcome: str) -> None:
    conn.execute("""INSERT INTO insider_fetches (symbol, checked_at, outcome) VALUES (?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET checked_at=excluded.checked_at,
                    outcome=excluded.outcome""",
                 (symbol, datetime.now().isoformat(timespec="seconds"), outcome))


def _text(pattern: str, blob: str):
    m = re.search(pattern, blob, re.S)
    return m.group(1).strip() if m else None


def _num(pattern: str, blob: str):
    v = _text(pattern, blob)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def parse_form4(xml: str) -> dict:
    """The reporting person and every non-derivative transaction in one filing."""
    owner = _text(r"<rptOwnerName>(.*?)</rptOwnerName>", xml)
    title = _text(r"<officerTitle>(.*?)</officerTitle>", xml)
    if not title:
        if (_text(r"<isDirector>(\w)</isDirector>", xml) or "0") in ("1", "true"):
            title = "Director"
        elif (_text(r"<isTenPercentOwner>(\w)</isTenPercentOwner>", xml) or "0") in ("1", "true"):
            title = "10% owner"
    out = []
    for i, block in enumerate(re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>",
                                         xml, re.S)):
        out.append({
            "seq": i,
            "txn_date": _text(r"<transactionDate>\s*<value>([\d-]+)</value>", block),
            "code": _text(r"<transactionCode>(\w)</transactionCode>", block),
            "acquired": _text(r"<transactionAcquiredDisposedCode>\s*<value>(\w)</value>", block),
            "shares": _num(r"<transactionShares>\s*<value>([\d.]+)</value>", block),
            "price": _num(r"<transactionPricePerShare>\s*<value>([\d.]+)</value>", block),
            "post": _num(r"<sharesOwnedFollowingTransaction>\s*<value>([\d.]+)</value>", block),
        })
    return {"owner": owner, "title": title, "transactions": out}


def _raw_doc(primary: str) -> str:
    """The XML behind the rendered path EDGAR lists ("xslF345X05/ownership.xml")."""
    return primary.split("/")[-1]


def sync(conn, symbols: list[str], months: int = 24, log=None, force: bool = False) -> dict:
    say = log or (lambda *a: None)
    ensure_schema(conn)
    since = (date.today() - timedelta(days=30 * months)).isoformat()
    try:
        index = sectors.ticker_index()
    except Exception as exc:                                   # noqa: BLE001
        return {"error": f"SEC ticker map unavailable: {type(exc).__name__}"}
    done, missing, failed, new_rows = [], [], {}, 0
    for sym in symbols:
        sym = sym.upper()
        if not force and _fresh(conn, sym):
            continue
        cik = index.get(sym)
        if not cik:
            missing.append(sym)
            _mark(conn, sym, "not in EDGAR")
            continue
        try:
            sub = json.loads(sectors._get(sectors.SEC_SUBMISSIONS.format(cik=cik)))
            time.sleep(SEC_PAUSE)
        except Exception as exc:                               # noqa: BLE001
            failed[sym] = f"{type(exc).__name__}"
            continue
        rec = sub.get("filings", {}).get("recent", {})
        have = {r[0] for r in conn.execute(
            "SELECT DISTINCT accession FROM insider_trades WHERE symbol=?", (sym,))}
        # Every network request happens BEFORE the write, and the write is one
        # short transaction. The first version inserted as it fetched, which
        # held the ledger's write lock across minutes of EDGAR round-trips and
        # locked out the earnings sync and the dashboard alike.
        pending = []
        for form, filed, acc, primary in zip(rec.get("form", []), rec.get("filingDate", []),
                                             rec.get("accessionNumber", []),
                                             rec.get("primaryDocument", [])):
            if form not in ("4", "4/A") or filed < since or acc in have:
                continue
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                   f"{acc.replace('-', '')}/{_raw_doc(primary)}")
            try:
                xml = sectors._get(url).decode("utf-8", "replace")
                time.sleep(SEC_PAUSE)
            except Exception:                                  # noqa: BLE001
                continue
            pending.append((acc, filed, parse_form4(xml)))
        wrote = 0

        def _write():
            nonlocal wrote
            wrote = 0
            conn.rollback()
            for acc, filed, parsed in pending:
                _write_one(acc, filed, parsed)
            _mark(conn, sym, "ok")
            conn.commit()

        def _write_one(acc, filed, parsed):
            nonlocal wrote
            if not parsed["transactions"]:
                # A filing with only derivative lines still marks the accession
                # as seen, so it is not fetched again tomorrow.
                conn.execute("""INSERT OR IGNORE INTO insider_trades
                                (symbol, accession, seq, filed, owner, title, code)
                                VALUES (?,?,?,?,?,?,?)""",
                             (sym, acc, -1, filed, parsed["owner"], parsed["title"], None))
                return
            for t in parsed["transactions"]:
                conn.execute("""INSERT OR IGNORE INTO insider_trades
                    (symbol, accession, seq, filed, txn_date, owner, title, code, acquired,
                     shares, price, post) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (sym, acc, t["seq"], filed, t["txn_date"], parsed["owner"],
                              parsed["title"], t["code"], t["acquired"], t["shares"],
                              t["price"], t["post"]))
                wrote += 1
        retry_locked(_write)
        new_rows += wrote
        done.append(sym)
        say(f"  {sym:<8} {wrote:>3} new transactions")
    return {"synced": done, "not_in_edgar": missing, "failed": failed, "new": new_rows}


def summary(conn, symbols: list[str], days: int = 90) -> dict[str, dict]:
    """Open-market buying and selling per symbol over the window, in dollars."""
    ensure_schema(conn)
    since = (date.today() - timedelta(days=days)).isoformat()
    out: dict[str, dict] = {}
    for r in conn.execute(
        """SELECT symbol, code, owner, title, txn_date, shares, price
             FROM insider_trades
            WHERE txn_date >= ? AND code IN ('P', 'S') AND shares IS NOT NULL
            ORDER BY txn_date DESC""", (since,)):
        s = out.setdefault(r["symbol"], {"bought_usd": 0.0, "sold_usd": 0.0, "buys": 0,
                                         "sells": 0, "buyers": [], "sellers": [], "last": None})
        usd = (r["shares"] or 0) * (r["price"] or 0)
        who = f"{r['owner']}{' (' + r['title'] + ')' if r['title'] else ''}"
        if r["code"] == "P":
            s["bought_usd"] += usd
            s["buys"] += 1
            if who not in s["buyers"]:
                s["buyers"].append(who)
        else:
            s["sold_usd"] += usd
            s["sells"] += 1
            if who not in s["sellers"]:
                s["sellers"].append(who)
        s["last"] = max(s["last"] or "", r["txn_date"] or "")
    want = {s.upper() for s in symbols}
    for sym, s in out.items():
        s["net_usd"] = round(s["bought_usd"] - s["sold_usd"], 2)
        s["bought_usd"] = round(s["bought_usd"], 2)
        s["sold_usd"] = round(s["sold_usd"], 2)
        s["days"] = days
    return {k: v for k, v in out.items() if k in want}


def recent(conn, symbol: str, limit: int = 40) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute(
        """SELECT * FROM insider_trades WHERE symbol=? AND seq >= 0
            ORDER BY txn_date DESC, filed DESC LIMIT ?""", (symbol.upper(), limit)).fetchall()
    return [{**dict(r), "label": CODE_LABEL.get(r["code"] or "", r["code"])} for r in rows]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.insiders")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--symbol", action="append", dest="symbols")
    s.add_argument("--force", action="store_true")
    sh = sub.add_parser("show")
    sh.add_argument("symbol")
    args = p.parse_args(argv)
    conn = connect()
    if args.cmd == "sync":
        if args.symbols:
            syms = args.symbols
        else:
            from . import replay
            syms = replay.universe(conn)
        r = sync(conn, syms, log=print, force=args.force)
        if r.get("error"):
            print(r["error"])
            return 1
        print(f"\n{len(r['synced'])} names checked, {r['new']} new transactions, "
              f"{len(r['not_in_edgar'])} not in EDGAR, {len(r['failed'])} failed")
        return 0
    if args.cmd == "show":
        for t in recent(conn, args.symbol):
            usd = (t["shares"] or 0) * (t["price"] or 0)
            print(f"  {t['txn_date'] or t['filed']}  {t['code'] or '-'}  {t['label']:<22} "
                  f"{(t['shares'] or 0):>12,.0f} @ {(t['price'] or 0):>8.2f}  ${usd:>12,.0f}  "
                  f"{t['owner']} {('(' + t['title'] + ')') if t['title'] else ''}")
        s = summary(conn, [args.symbol]).get(args.symbol.upper())
        if s:
            print(f"\n  last {s['days']} days: bought ${s['bought_usd']:,.0f} in {s['buys']} "
                  f"purchase(s), sold ${s['sold_usd']:,.0f} in {s['sells']} sale(s)")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
