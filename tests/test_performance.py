"""Known-answer tests for the return math.

The whole value of this engine is that its return figure is comparable to an
index. That claim is only worth anything if the deposit-stripping is provably
correct, so it is tested against a scenario whose answer can be worked out by
hand rather than against real data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ledger import connect, get_or_create_account, get_or_create_institution, get_or_create_security
from app import performance


def build(tmp):
    conn = connect(tmp)
    inst = get_or_create_institution(conn, "Test")
    acct = get_or_create_account(conn, inst, "T1", "Test Brokerage", "brokerage", "taxable")
    sec = get_or_create_security(conn, "TEST")
    for d, close in [("2026-01-01", 100.0), ("2026-06-01", 110.0), ("2026-12-01", 121.0)]:
        conn.execute("INSERT INTO prices (security_id, bar_date, close, source) VALUES (?,?,?,?)",
                     (sec, d, close, "test"))

    def txn(d, kind, amount, qty=None, price=None, sid=None, key=""):
        conn.execute(
            """INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity,
                                         price, amount, source, source_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (acct, d, kind, sid, qty, price, amount, "test", key))

    # $10k in, fully invested at $100.
    txn("2026-01-01", "deposit", 10_000, key="d1")
    txn("2026-01-01", "buy", -10_000, qty=100, price=100.0, sid=sec, key="b1")
    # Price rises 10% to $110. Another $10k in, fully invested.
    txn("2026-06-01", "deposit", 10_000, key="d2")
    txn("2026-06-01", "buy", -10_000, qty=10_000 / 110, price=110.0, sid=sec, key="b2")
    # Price rises another 10% to $121.
    conn.commit()
    return conn


def build_coverage(tmp=":memory:"):
    """Two holdings of equal value; only one of them has a price feed."""
    conn = connect(tmp)
    inst = get_or_create_institution(conn, "Cov")
    acct = get_or_create_account(conn, inst, "C1", "Cov Brokerage", "brokerage", "taxable")
    live = get_or_create_security(conn, "LIVE")
    dark = get_or_create_security(conn, "DARK")
    for d, close in [("2026-01-05", 10.0), ("2026-06-30", 10.0)]:
        conn.execute("INSERT INTO prices (security_id, bar_date, close, source)"
                     " VALUES (?,?,?,?)", (live, d, close, "test"))
    conn.execute("INSERT INTO transactions (account_id, txn_date, kind, security_id,"
                 " quantity, price, amount, source, source_id)"
                 " VALUES (?,?,?,?,?,?,?,?,?)",
                 (acct, "2026-01-05", "deposit", None, None, None, 2000.0, "t", "d1"))
    for sid, key in ((live, "b1"), (dark, "b2")):
        conn.execute("INSERT INTO transactions (account_id, txn_date, kind, security_id,"
                     " quantity, price, amount, source, source_id)"
                     " VALUES (?,?,?,?,?,?,?,?,?)",
                     (acct, "2026-01-05", "buy", sid, 100.0, 10.0, -1000.0, "t", key))
    conn.commit()
    return conn


def approx(a, b, tol=1e-6):
    return a is not None and abs(a - b) < tol


def main():
    conn = build(":memory:")
    txns = performance.load_transactions(conn, "2026-01-01", "2026-12-01", "taxable")
    failures = []

    begin, _ = performance.portfolio_value(conn, txns, "2026-01-01")
    mid, _ = performance.portfolio_value(conn, txns, "2026-06-01")
    end, _ = performance.portfolio_value(conn, txns, "2026-12-01")

    checks = [
        ("beginning value is 10,000", approx(begin, 10_000, 0.01), begin),
        ("value after 2nd deposit is 21,000", approx(mid, 21_000, 0.01), mid),
        ("ending value is 23,100", approx(end, 23_100, 0.01), end),
    ]

    twr, missing, _merged = performance.time_weighted_return(conn, txns, "2026-01-01", "2026-12-01")
    # Two sub-periods of +10% each chain to +21%, regardless of the deposit.
    checks.append(("time-weighted return is +21%", approx(twr, 0.21, 1e-6), twr))
    checks.append(("no missing prices", missing == [], missing))

    # The naive number a lesser tracker would show, for contrast: total growth
    # over total money in = 15.5%. If TWR ever equals this, deposit-stripping broke.
    naive = (end - 20_000) / 20_000
    checks.append(("naive return differs from TWR (deposits stripped)",
                   not approx(twr, naive, 1e-6), f"naive={naive:.4f} twr={twr:.4f}"))

    flows = performance.external_flows(txns, "2026-01-01", "2026-12-01")
    checks.append(("only the mid-period deposit counts as an external flow",
                   flows == [("2026-06-01", 10_000.0)], flows))

    # --- cash yield: a money-market core position must be valued at $1.00,
    # and the yield that produced it must be counted exactly once.
    conn2 = connect(":memory:")
    inst = get_or_create_institution(conn2, "Test")
    acct = get_or_create_account(conn2, inst, "T2", "Cash Test", "brokerage", "taxable")
    mm = get_or_create_security(conn2, "SPAXX")
    conn2.execute("""INSERT INTO transactions (account_id, txn_date, kind, amount, source, source_id)
                     VALUES (?,?,?,?,?,?)""", (acct, "2026-01-01", "deposit", 1000.0, "test", "c1"))
    # $10 of yield paid, then swept back into the fund at $1.00/share.
    conn2.execute("""INSERT INTO transactions (account_id, txn_date, kind, security_id, amount, source, source_id)
                     VALUES (?,?,?,?,?,?,?)""", (acct, "2026-02-01", "dividend", mm, 10.0, "test", "c2"))
    conn2.execute("""INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity, amount, source, source_id)
                     VALUES (?,?,?,?,?,?,?,?)""", (acct, "2026-02-01", "reinvest", mm, 10.0, -10.0, "test", "c3"))
    conn2.commit()
    ct = performance.load_transactions(conn2, "2026-01-01", "2026-03-01", "taxable")
    cash_value, cash_missing = performance.portfolio_value(conn2, ct, "2026-03-01")
    checks.append(("money-market position is valued (no price feed needed)",
                   cash_missing == [], cash_missing))
    checks.append(("cash yield counted exactly once: 1000 + 10 = 1010",
                   approx(cash_value, 1010.0, 0.01), cash_value))

    for label, ok, value in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<52} {value}")
        if not ok:
            failures.append(label)

    # --- price coverage must be able to FAIL --------------------------------
    # It previously could not. `missing` filled only when NO number could be
    # found, and every holding was bought at some price, so a fallback always
    # existed — a $13,200 position with zero price bars, marked to a five-month
    # old fill, reported 100% coverage and "complete".
    cconn = build_coverage()
    r = performance.analyse(cconn, "2026-01-05", "2026-06-30", scope="investment")
    cov_checks = [
        ("coverage falls below 1.0 when half the book has no feed",
         r["price_coverage"] < 1.0, round(r["price_coverage"], 4)),
        ("coverage is value-weighted, not a count of symbols",
         approx(r["price_coverage"], 0.5, 0.02), round(r["price_coverage"], 4)),
        ("a materially stale book is not reported complete",
         r["complete"] is False, r["complete"]),
        ("the unpriced holding is named",
         "DARK" in r["stale_valued"], sorted(r["stale_valued"])),
        ("a same-day price is not counted stale",
         "LIVE" not in r["stale_valued"], sorted(r["stale_valued"])),
    ]
    # A feed that simply stopped is stale too — the final bar used to carry
    # forward for ever, so a delisted name was valued as confidently as one
    # trading today.
    late = performance.load_transactions(cconn, "1900-01-01", "2026-12-31", "investment")
    stopped = performance.market_value(cconn, late, "2026-12-31")[2]
    cov_checks.append(("a feed that stopped months ago is stale, not a live mark",
                       "LIVE" in stopped, sorted(stopped)))
    for label, ok, detail in cov_checks:
        checks.append((label, ok, detail))
        if not ok:
            failures.append(label)
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")

    # --- Modified Dietz, which had NO behavioural coverage at all ----------
    # Mutation testing removed both the flow time-weighting and the deposit
    # subtraction with the whole suite still green. The second is the exact
    # class that produced the +2211% figure, on a card the dashboard prints.
    md = performance.modified_dietz
    # $100k start, $110k end, no flows -> exactly 10%.
    dietz_checks = [
        ("no flows: dietz is the plain return",
         approx(md(100_000, 110_000, [], "2026-01-01", "2026-12-31"), 0.10, 1e-9), None),
    ]
    # A deposit is NOT return. $100k in, $50k deposited mid-year, ends $160k:
    # the gain is $10k on a weighted base, never 60%.
    mid = md(100_000, 160_000, [("2026-07-02", 50_000)], "2026-01-01", "2026-12-31")
    dietz_checks += [
        ("a deposit is not counted as gain",
         mid is not None and mid < 0.15, mid),
        ("the gain is measured on the weighted base, not the start",
         approx(mid, 10_000 / (100_000 + 50_000 * 0.5), 0.02), mid),
    ]
    # Flow TIMING must matter: the same money in on day 2 vs day 364 weights
    # the denominator differently, so the returns must differ.
    early = md(100_000, 160_000, [("2026-01-02", 50_000)], "2026-01-01", "2026-12-31")
    late = md(100_000, 160_000, [("2026-12-30", 50_000)], "2026-01-01", "2026-12-31")
    dietz_checks += [
        ("flow timing changes the answer", early is not None and late is not None
         and abs(early - late) > 0.02, (early, late)),
        ("money in early dilutes the return more than money in late",
         early is not None and late is not None and early < late, (early, late)),
        ("a withdrawal raises the measured return, not lowers it",
         md(100_000, 60_000, [("2026-07-02", -50_000)], "2026-01-01", "2026-12-31")
         > md(100_000, 60_000, [], "2026-01-01", "2026-12-31"), None),
    ]

    # --- the risk-free rate is a DECIMAL, not a percent --------------------
    # A missing /100 makes it 100x and turns every Sharpe negative; the comment
    # in risk.py claims this is handled and nothing checked it.
    import app.risk as _risk
    # Seeded here rather than read from the real ledger, so the test constrains
    # the arithmetic instead of whatever happens to be cached.
    _rfsec = get_or_create_security(conn, "DGS3MO")
    for _d, _pct in (("2026-01-05", 4.0), ("2026-06-05", 5.0)):
        conn.execute("INSERT OR REPLACE INTO prices (security_id, bar_date, close,"
                     " source) VALUES (?,?,?,?)", (_rfsec, _d, _pct, "test"))
    conn.commit()
    _rf = _risk.risk_free_rate(conn, "2026-01-01", "2026-12-01")
    dietz_checks += [
        ("FRED publishes a percent; the rate is returned as a DECIMAL",
         _rf is not None and abs(_rf - 0.045) < 1e-9, _rf),
        ("an uncached series returns None, not a silent zero",
         _risk.risk_free_rate(connect(":memory:"), "2026-01-01", "2026-12-01") is None,
         None),
    ]

    for label, ok, detail in dietz_checks:
        checks.append((label, ok, detail))
        if not ok:
            failures.append(label)
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")

    print(f"\n  {len(checks) - len(failures)}/{len(checks)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
