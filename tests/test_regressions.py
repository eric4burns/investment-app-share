"""Regression tests for defects found by review on 2026-08-29.

Every case here corresponds to a bug that shipped, produced a confident and
wrong number, and was not caught by the existing suite. Each test states the
wrong answer it guards against.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ledger import (connect, get_or_create_account, get_or_create_institution,
                        get_or_create_security)
from app.importers.fidelity_csv import classify
from app import holdings, performance, reconcile

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def fixture(prices_by_date=None):
    conn = connect(":memory:")
    inst = get_or_create_institution(conn, "T")
    acct = get_or_create_account(conn, inst, "A1", "Test Brokerage", "brokerage", "taxable")
    sec = get_or_create_security(conn, "FLAT")
    for d, p in (prices_by_date or {}).items():
        conn.execute("INSERT INTO prices (security_id, bar_date, close, source) VALUES (?,?,?,?)",
                     (sec, d, p, "test"))
    return conn, acct, sec


def add(conn, acct, d, kind, amount, qty=None, price=None, sid=None, desc="", key=None):
    conn.execute(
        """INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity,
                                     price, amount, description, source, source_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (acct, d, kind, sid, qty, price, amount, desc, "test",
         key or f"{d}{kind}{amount}{qty}{desc}"))


# 1 — a real purchase of a stock with a pending reorg must stay a purchase.
#     Was: classified corporate_action, price refused, position valued at $0.
action = "YOU BOUGHT STRIVE INC CL A COM 1 FOR 20 R/S INT... (862945102) (Cash)"
check("reorg-suffixed BUY classifies as buy", classify(action, -249.08) == "buy",
      classify(action, -249.08))
check("actual reverse-split leg classifies as corporate_action",
      classify("REVERSE SPLIT R/S TO 862945300#REOR M005 STRIVE INC", -5498.55) == "corporate_action")
check("cash-in-lieu stays a corporate action",
      classify("IN LIEU OF FRX SHARE LEU PAYOUT 862945102#REOR", 14.80) == "corporate_action")

# 2 — TWR must return None, never 0.0, when no sub-period could be chained.
#     Was: printed +0.00% for an account that had lost 15%.
#     The portfolio is EMPTY at the start and is funded later by a movement
#     that is internal (so it creates no break date). There is therefore one
#     sub-period whose opening value is zero — nothing can be chained, and the
#     honest answer is "unknown", not a number.
conn, acct, sec = fixture({"2026-01-01": 1.0, "2026-06-01": 1.0, "2026-12-01": 0.5})
add(conn, acct, "2026-06-01", "transfer_in", 10_000,
    desc="TRANSFERRED FROM TO BROKERAGE OPTION (Cash)", key="tin")
add(conn, acct, "2026-06-01", "buy", -10_000, qty=10_000, price=1.0, sid=sec, key="bin")
conn.commit()
t = performance.load_transactions(conn, "2026-01-01", "2026-12-01", "taxable")
twr, _m, skipped = performance.time_weighted_return(conn, t, "2026-01-01", "2026-12-01")
check("TWR is None (not 0.0) when nothing could be chained", twr is None, f"twr={twr}")

# 3 — the merge/skip branch must not fabricate a loss on a flat portfolio.
#     Was: -42.86% for a portfolio whose price never moved.
px = {f"2026-{m:02d}-01": 1.0 for m in range(1, 13)}
conn, acct, sec = fixture(px)
for m in range(1, 13):
    d = f"2026-{m:02d}-01"
    amt = 490_000 if m == 5 else 1_000
    add(conn, acct, d, "deposit", amt, key=f"dep{m}")
    add(conn, acct, d, "buy", -amt, qty=amt, price=1.0, sid=sec, key=f"buy{m}")
conn.commit()
t = performance.load_transactions(conn, "2026-01-01", "2026-12-01", "taxable")
twr, _m, skipped = performance.time_weighted_return(conn, t, "2026-01-01", "2026-12-01")
check("flat portfolio returns ~0%, not a fabricated loss",
      twr is not None and abs(twr) < 0.02, f"twr={twr}, skipped={skipped}")

# 4 — a position held only mid-period must count toward price coverage.
#     Was: netted to zero at both endpoints, so coverage read 100% while the
#     holding was 7.7% of the book and valued at $0.
conn, acct, sec = fixture({"2026-01-01": 1.0, "2026-12-01": 1.0})
unpriced = get_or_create_security(conn, "NOFEED")
add(conn, acct, "2026-01-01", "deposit", 10_000, key="d0")
add(conn, acct, "2026-01-01", "buy", -10_000, qty=10_000, price=1.0, sid=sec, key="b0")
add(conn, acct, "2026-05-01", "deposit", 100, key="d1")          # forces a break date
add(conn, acct, "2026-04-01", "buy", -5_000, qty=500, price=10.0, sid=unpriced, key="b1")
add(conn, acct, "2026-06-01", "sell", 5_000, qty=-500, price=10.0, sid=unpriced, key="s1")
conn.commit()
res = performance.analyse(conn, "2026-01-01", "2026-12-01", "taxable", [])
check("mid-period holding is counted in price coverage",
      res["held_securities"] >= 2, f"held={res['held_securities']}")

# 5 — market-value adjustments are not cash.
conn, acct, sec = fixture({"2026-01-01": 1.0})
add(conn, acct, "2026-01-01", "deposit", 1_000, key="d")
add(conn, acct, "2026-02-01", "market_value_adj", 5_000, desc="Change in Market Value", key="mv")
conn.commit()
t = performance.load_transactions(conn, "2026-01-01", "2026-03-01", "taxable")
check("market_value_adj does not become cash",
      abs(performance.cash_asof(t, "2026-03-01") - 1_000) < 0.01,
      performance.cash_asof(t, "2026-03-01"))

# 6 — anchoring: known opening allowed, unknown opening refused.
conn, acct, sec = fixture({"2026-01-01": 1.0, "2026-12-01": 2.0})
add(conn, acct, "2026-01-01", "deposit", 1_000, key="d")
add(conn, acct, "2026-01-01", "buy", -1_000, qty=1_000, price=1.0, sid=sec, key="b")
conn.commit()
after = performance.analyse(conn, "2026-06-01", "2026-12-01", "taxable", [])
before = performance.analyse(conn, "2020-01-01", "2026-12-01", "taxable", [])
check("sub-period report (opening known) is anchored", after["anchored"] is True)
# A start before any data is CLAMPED forward to the first transaction rather
# than refused: asking for "all time" on an account opened partway through is a
# request for that account's whole life, not for a period it did not exist in.
# Refusing it meant selecting a single account produced no return at all.
check("range starting before any data is clamped, not refused",
      before["start_clamped"] is True and before["start"] == "2026-01-01"
      and before["anchored"] is True,
      f"start={before['start']} clamped={before['start_clamped']}")
check("clamped range still computes a return", before["twr"] is not None, before["twr"])

# 7 — one-sided internal transfers get a synthetic counter-leg.
#     Was: $39,919.50 appeared from nowhere and was attributed to performance.
conn = connect(":memory:")
inst = get_or_create_institution(conn, "Fidelity")
plan = get_or_create_account(conn, inst, "P1", "L3HARRIS RETIREMENT SAVINGS PLAN", "retirement", "tax_deferred")
sleeve = get_or_create_account(conn, inst, "S1", "BROKERAGELINK", "retirement", "tax_deferred")
add(conn, sleeve, "2026-03-01", "transfer_in", 1_210.16,
    desc="TRANSFERRED FROM TO BROKERAGE OPTION (Cash)", key="x1")
conn.commit()
r1 = reconcile.pair_internal_transfers(conn); conn.commit()
r2 = reconcile.pair_internal_transfers(conn); conn.commit()   # idempotence
net = conn.execute("SELECT ROUND(SUM(amount),2) FROM transactions").fetchone()[0]
check("internal transfer is paired and nets to zero", abs(net) < 0.01, net)
check("pairing is idempotent", r1["created"] == 1 and r2["created"] == 0,
      f"{r1['created']}/{r2['created']}")
check("unpaired audit is clean after pairing", reconcile.audit_unpaired(conn) == [])

# 8 — an account with value but no tickers is flagged, not passed off as market value.
conn = connect(":memory:")
inst = get_or_create_institution(conn, "F")
plan = get_or_create_account(conn, inst, "P", "PLAN", "retirement", "tax_deferred")
add(conn, plan, "2026-01-01", "contribution", 42_800, desc="Contributions", key="c")
conn.commit()
res = performance.analyse(conn, "2026-01-01", "2026-06-01", "investment", [])
check("account with no tickers is reported as valued at cost",
      res["at_cost_total"] > 42_000, res["at_cost_total"])


# 9 — FIFO cost basis, and a reverse split must carry basis rather than
#     resetting it to zero (which reported +653% on a renamed position).
from app import holdings

conn, acct, sec = fixture({"2026-06-01": 20.0})
add(conn, acct, "2026-01-01", "buy", -1_000, qty=100, price=10.0, sid=sec, key="b1")
add(conn, acct, "2026-02-01", "buy", -1_500, qty=100, price=15.0, sid=sec, key="b2")
add(conn, acct, "2026-03-01", "sell", 1_800, qty=-100, price=18.0, sid=sec, key="s1")
conn.commit()
t = performance.load_transactions(conn, "2026-01-01", "2026-06-01", "taxable")
pos = {p["symbol"]: p for p in holdings.positions(conn, t, "2026-06-01")}
check("FIFO consumes the oldest lot first (avg cost of remainder is 15.00)",
      abs(pos["FLAT"]["avg_cost"] - 15.0) < 0.01, pos["FLAT"]["avg_cost"])
r = {x["symbol"]: x for x in holdings.realised(conn, t, "2026-01-01", "2026-06-01")}
check("realised gain uses the FIFO lot cost (1800 - 1000 = 800)",
      abs(r["FLAT"]["gain"] - 800.0) < 0.01, r["FLAT"]["gain"])

conn, acct, sec = fixture({"2026-06-01": 25.0})
newsec = get_or_create_security(conn, "NEWCO")
add(conn, acct, "2026-01-01", "buy", -2_000, qty=1_000, price=2.0, sid=sec, key="rb")
# 1-for-20 reverse split: old shares out, new shares in, basis travels with them.
add(conn, acct, "2026-03-01", "corporate_action", 0.0, qty=-1_000, price=2.0, sid=sec, key="ro")
add(conn, acct, "2026-03-01", "corporate_action", 0.0, qty=50, price=40.0, sid=newsec, key="rn")
conn.commit()
t = performance.load_transactions(conn, "2026-01-01", "2026-06-01", "taxable")
pos = {p["symbol"]: p for p in holdings.positions(conn, t, "2026-06-01")}
check("reverse split carries cost basis (avg 40.00, not 0.00)",
      "NEWCO" in pos and abs(pos["NEWCO"]["avg_cost"] - 40.0) < 0.01,
      pos.get("NEWCO", {}).get("avg_cost"))
check("reverse split does not leave a phantom old position", "FLAT" not in pos)

# --- share-for-share reorganisations ----------------------------------------
# A reverse split is not a sale. Fidelity reports it as two corporate actions
# with independently stated per-share prices that do NOT reconcile, so taking
# them at face value conjured basis and booked a large realised loss on a
# non-taxable event.
def _split_ledger():
    rows = [
        {"txn_date": "2025-01-10", "symbol": "OLD", "kind": "buy",
         "quantity": 2000.0, "price": 1.00, "amount": -2000.0, "description": ""},
        {"txn_date": "2025-06-10", "symbol": "OLD", "kind": "buy",
         "quantity": 2000.0, "price": 2.00, "amount": -4000.0, "description": ""},
        # 1-for-20: 4,000 out, 200 in, priced inconsistently on purpose.
        {"txn_date": "2026-02-06", "symbol": "OLD", "kind": "corporate_action",
         "quantity": -4000.0, "price": 0.50, "amount": 0.0,
         "description": "REVERSE SPLIT R/S TO 999999999#REOR M001"},
        {"txn_date": "2026-02-06", "symbol": "NEW", "kind": "corporate_action",
         "quantity": 200.0, "price": 40.00, "amount": 0.0,
         "description": "REVERSE SPLIT R/S FROM OLD#REOR M001"},
    ]
    return rows


_rows = _split_ledger()
_lots, _real = holdings.build_lots(_rows, "2026-12-31")
check("the reorganisation is detected and paired",
      holdings.reorganisations(_rows) == {("2026-02-06", "NEW"): "OLD"},
      holdings.reorganisations(_rows))
check("basis is conserved across the split, not re-derived from the statement",
      abs(sum(l.qty * l.price for l in _lots.get("NEW", [])) - 6000.0) < 1e-6,
      sum(l.qty * l.price for l in _lots.get("NEW", [])))
check("share count comes from the incoming leg",
      abs(sum(l.qty for l in _lots.get("NEW", [])) - 200.0) < 1e-6)
check("the old identifier is emptied", not _lots.get("OLD"))
check("no gain or loss is realised on a share-for-share exchange",
      "OLD" not in _real and "NEW" not in _real, sorted(_real))
check("the holding period is NOT reset by the split",
      min(l.date for l in _lots["NEW"]) == "2025-01-10",
      min(l.date for l in _lots["NEW"]))

# The position-level view must see ONE continuous trade, not a sale and a
# repurchase — this is the path that reported a $22,523 phantom loss.
_trips = holdings.position_trades(_rows, "2026-12-31")
check("the split does not close a position-level round trip",
      len(_trips) == 1 and _trips[0]["open"] is True, [t["symbol"] for t in _trips])
check("the surviving trade is dated from the ORIGINAL entry",
      _trips and _trips[0]["entry_date"] == "2025-01-10",
      _trips[0]["entry_date"] if _trips else None)
check("cash actually spent is unchanged by the restatement",
      _trips and abs(_trips[0]["bought"] - 6000.0) < 1e-6,
      _trips[0]["bought"] if _trips else None)

# A corporate action with no counterpart must keep its existing treatment.
_solo = [{"txn_date": "2025-01-10", "symbol": "AAA", "kind": "buy",
          "quantity": 100.0, "price": 5.0, "amount": -500.0, "description": ""},
         {"txn_date": "2025-03-01", "symbol": "AAA", "kind": "corporate_action",
          "quantity": -100.0, "price": 5.0, "amount": 0.0, "description": "DELISTED"}]
check("an unpaired corporate action is left alone",
      not holdings.reorganisations(_solo), holdings.reorganisations(_solo))

# --- money parsing: silently wrong beats loudly wrong, so neither ------------
from app.importers.fidelity_csv import _num as _parse_money

for _raw, _want in [
    ("1234.56", 1234.56),
    ("$1,234.56", 1234.56),
    # Accounting parentheses mean NEGATIVE. This used to fail float() and return
    # None, and the caller's `or 0.0` turned an outflow into zero.
    ("(1,234.56)", -1234.56),
    ("(500.00)", -500.0),
    ("-1,234.56", -1234.56),
    # Deleting commas blindly made this 1.23456 — a thousandfold understatement
    # that still reads as a plausible price.
    ("1.234,56", 1234.56),
    ("1,234", 1234.0),
    ("1,23", 1.23),
    ("12,345,678.90", 12345678.90),
    ("", None), ("   ", None), ("-", None), ("n/a", None), (None, None),
]:
    _got = _parse_money(_raw)
    _ok = (_got is None and _want is None) or (
        _got is not None and _want is not None and abs(_got - _want) < 1e-9)
    check(f"money parse {_raw!r} -> {_want!r}", _ok, _got)

# --- scope-sensitivity is a CLASS, not a list of sites ----------------------
# Whether a transfer counts as external money depends on the scope being
# measured. That flag was fixed three times at three call sites while a fourth
# kept printing a single account's deposits as gains — CAGR 305.80% and Sharpe
# 4.10 against a true 23.86% and 0.42. Enumerating the callers in a test is the
# only thing that makes the class visible rather than the instance.
import re as _re

_APP = Path(__file__).resolve().parent.parent / "app"
_SCOPE_SENSITIVE = ("external_flows", "time_weighted_return", "same_cashflow_benchmark")
_offenders = []
for _f in sorted(_APP.glob("*.py")):
    _src = _f.read_text()
    for _fn in _SCOPE_SENSITIVE:
        for _m in _re.finditer(rf"(?<!def ){_fn}\(", _src):
            # The definition and the docstring references are not call sites.
            _line = _src[_src.rfind("\n", 0, _m.start()) + 1:
                         _src.find("\n", _m.start())]
            if _line.lstrip().startswith(("def ", "#", '"')):
                continue
            _call = _src[_m.start():_src.find("\n\n", _m.start())]
            _args = _call[:_call.find(")") + 1] if ")" in _call else _call
            if _args.count(",") < 3:
                _offenders.append(f"{_f.name}: {_line.strip()[:70]}")

check("every scope-sensitive call passes the multi_account flag",
      not _offenders, _offenders[:4])

# risk.metrics takes the same flag and has the same failure mode.
_metric_calls = []
for _f in sorted(_APP.glob("*.py")):
    _src = _f.read_text()
    for _m in _re.finditer(r"risk\.metrics\(", _src):
        _chunk = _src[_m.start():_m.start() + 260]
        if "multi_account" not in _chunk:
            _line = _src[_src.rfind("\n", 0, _m.start()) + 1:_src.find("\n", _m.start())]
            _metric_calls.append(f"{_f.name}: {_line.strip()[:70]}")
check("every risk.metrics call states its scope", not _metric_calls, _metric_calls)

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<56} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
