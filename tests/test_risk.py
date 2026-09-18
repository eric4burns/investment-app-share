"""Known-answer tests for drawdown and risk metrics.

The flow-adjustment is the part most worth guarding: without it a payday looks
like a 30% gain and a withdrawal looks like a crash, which would make every
volatility, Sharpe and drawdown figure fiction.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ledger import (connect, get_or_create_account, get_or_create_institution,
                        get_or_create_security)
from app import performance, risk

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def build(price_by_date, flows=()):
    """One security, prices you specify, optional deposits."""
    conn = connect(":memory:")
    inst = get_or_create_institution(conn, "T")
    acct = get_or_create_account(conn, inst, "A", "Test", "brokerage", "taxable")
    sec = get_or_create_security(conn, "X")
    for d, p in price_by_date.items():
        conn.execute("INSERT INTO prices (security_id, bar_date, close, source) VALUES (?,?,?,?)",
                     (sec, d, p, "test"))
    first = min(price_by_date)
    conn.execute("""INSERT INTO transactions (account_id, txn_date, kind, amount, source, source_id)
                    VALUES (?,?,?,?,?,?)""", (acct, first, "deposit", 1000.0, "t", "d0"))
    conn.execute("""INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity,
                                              price, amount, source, source_id)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                 (acct, first, "buy", sec, 1000.0 / price_by_date[first],
                  price_by_date[first], -1000.0, "t", "b0"))
    for i, (d, amt) in enumerate(flows):
        conn.execute("""INSERT INTO transactions (account_id, txn_date, kind, amount, source, source_id)
                        VALUES (?,?,?,?,?,?)""", (acct, d, "deposit", amt, "t", f"f{i}"))
        conn.execute("""INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity,
                                                  price, amount, source, source_id)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                     (acct, d, "buy", sec, amt / price_by_date[d], price_by_date[d], -amt, "t", f"fb{i}"))
    conn.commit()
    return conn


DATES = [f"2026-0{m}-01" for m in range(1, 7)]

# A price path that halves then recovers: max drawdown must be exactly -50%.
px = dict(zip(DATES, [100.0, 120.0, 60.0, 80.0, 120.0, 150.0]))
conn = build(px)
t = performance.load_transactions(conn, DATES[0], DATES[-1], "taxable")
curve, worst = risk.drawdown_curve(conn, t, DATES)
check("max drawdown is exactly -50% for a 120 -> 60 fall",
      abs(min(p["drawdown"] for p in curve) + 0.5) < 1e-6,
      min(p["drawdown"] for p in curve))
check("drawdown episode dates the peak and the trough correctly",
      worst["peak_date"] == "2026-02-01" and worst["trough_date"] == "2026-03-01",
      (worst["peak_date"], worst["trough_date"]))
check("recovery is dated when a new high is made, not when the fall stops",
      worst["recovered_date"] == "2026-05-01", worst["recovered_date"])
check("drawdown ends at 0 when the series finishes at a new high",
      abs(curve[-1]["drawdown"]) < 1e-9, curve[-1]["drawdown"])

# A deposit must NOT register as a gain, nor a drawdown recovery.
flat = dict(zip(DATES, [100.0] * 6))
conn = build(flat, flows=[("2026-04-01", 10_000.0)])
t = performance.load_transactions(conn, DATES[0], DATES[-1], "taxable")
rets = risk.period_returns(conn, t, DATES)
check("a deposit into a flat portfolio produces zero return, not a spike",
      all(abs(r) < 1e-9 for _, r in rets), [round(r, 6) for _, r in rets])
m = risk.metrics(conn, t, DATES)
check("volatility of a flat portfolio with a deposit is zero",
      abs(m["volatility"]) < 1e-9, m["volatility"])
check("max drawdown of a flat portfolio with a deposit is zero",
      abs(m["max_drawdown"]) < 1e-9, m["max_drawdown"])

# Monotonic rise: no drawdown, positive CAGR, every period positive.
rise = dict(zip(DATES, [100.0, 110.0, 121.0, 133.1, 146.41, 161.05]))
conn = build(rise)
t = performance.load_transactions(conn, DATES[0], DATES[-1], "taxable")
m = risk.metrics(conn, t, DATES)
check("a monotonic rise has no drawdown", abs(m["max_drawdown"]) < 1e-9, m["max_drawdown"])
check("all periods positive on a monotonic rise", m["positive_periods"] == 1.0)
check("CAGR is positive on a monotonic rise", m["cagr"] > 0, m["cagr"])
check("Sortino is undefined with no losing periods", m["sortino"] is None, m["sortino"])

# Sanity on the metric relationships.
conn = build(px)
t = performance.load_transactions(conn, DATES[0], DATES[-1], "taxable")
m = risk.metrics(conn, t, DATES)
check("Sortino >= Sharpe when downside is smaller than total deviation",
      m["sortino"] is None or m["sharpe"] is None or m["sortino"] >= m["sharpe"],
      (m["sharpe"], m["sortino"]))
check("current drawdown is never worse than max drawdown",
      m["current_drawdown"] >= m["max_drawdown"] - 1e-9,
      (m["current_drawdown"], m["max_drawdown"]))
check("best period is not worse than worst period",
      m["best_period"][1] >= m["worst_period"][1])
check("too few data points reports insufficient rather than a number",
      risk.metrics(conn, t, DATES[:2]).get("insufficient_data") is True)

# A transfer between two of your own accounts is internal to the PORTFOLIO but
# external to either account on its own. Suppressing it regardless made every
# dollar moved out of the 401(k) look like a loss — a -100.2% drawdown, which
# is not a possible number.
conn = build(dict(zip(DATES, [100.0] * 6)))
inst = get_or_create_institution(conn, "T")
acct = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()["id"]
conn.execute("""INSERT INTO transactions (account_id, txn_date, kind, amount, description,
                                          source, source_id)
                VALUES (?,?,?,?,?,?,?)""",
             (acct, "2026-03-01", "transfer_out", -500.0,
              "TRANSFERRED FROM TO BROKERAGE OPTION (Cash)", "t", "tx1"))
conn.commit()
t = performance.load_transactions(conn, DATES[0], DATES[-1], "taxable")

single = risk.metrics(conn, t, DATES, multi_account=False)
multi = risk.metrics(conn, t, DATES, multi_account=True)
check("single-account scope treats an inter-account transfer as external",
      abs(single["max_drawdown"]) < 1e-9, single["max_drawdown"])
check("multi-account scope still nets it out (so it shows as a loss there)",
      multi["max_drawdown"] < -0.01, multi["max_drawdown"])
check("drawdown can never be worse than -100%",
      single["max_drawdown"] >= -1.0 and multi["max_drawdown"] >= -1.0,
      (single["max_drawdown"], multi["max_drawdown"]))

# --- unpriced holdings must not be handed a risk figure ---------------------
# Substituting 0.00% returns for a missing feed says "this did not move", which
# is a claim about the market rather than about the data: the name keeps its
# full weight while reporting zero volatility and zero risk contribution, so it
# ranks as the safest thing in the book.
_rk_conn = connect(":memory:")
_ri = get_or_create_institution(_rk_conn, "R")
_ra = get_or_create_account(_rk_conn, _ri, "R1", "R", "brokerage", "taxable")
_priced = get_or_create_security(_rk_conn, "PRICED")
_dates = [f"2026-01-{d:02d}" for d in range(1, 21)]
for _i, _d in enumerate(_dates):
    _rk_conn.execute("INSERT INTO prices (security_id, bar_date, close, source)"
                     " VALUES (?,?,?,?)",
                     (_priced, _d, 100.0 + (_i % 5) * 3.0, "test"))
_rk_conn.commit()
_pos = [{"symbol": "PRICED", "value": 600.0, "weight": 0.6},
        {"symbol": "NOFEED", "value": 400.0, "weight": 0.4}]
_c = risk.concentration(_rk_conn, _pos, _dates)
check("a holding with no price history is reported, not scored",
      [u["symbol"] for u in _c["unmeasured"]] == ["NOFEED"],
      [u["symbol"] for u in _c["unmeasured"]])
check("its weight is stated so the reader knows what the shares cover",
      abs(_c["unmeasured_weight"] - 0.4) < 1e-6, _c["unmeasured_weight"])
check("the unpriced name gets no risk row at all",
      "NOFEED" not in [r["symbol"] for r in _c["rows"]],
      [r["symbol"] for r in _c["rows"]])
check("risk shares sum to one over the MEASURED book",
      abs(sum(r["risk_share"] for r in _c["rows"]) - 1.0) < 1e-6,
      sum(r["risk_share"] for r in _c["rows"]))

# Two holdings, neither with a series: min() over an empty sequence used to
# raise ValueError and take the whole request down with it.
_none = risk.correlation(_rk_conn, [{"symbol": "A", "value": 1.0},
                                    {"symbol": "B", "value": 1.0}], _dates)
check("correlation reports a shortage rather than raising",
      isinstance(_none, dict) and _none.get("symbols") == [], _none.get("note"))

check("_returns_from_series can report a gap instead of inventing a flat period",
      risk._returns_from_series({}, _dates[:3], [], unknown=None) == [None, None])

# --- formulas with hand-computed answers ------------------------------------
# Mutation testing deleted the Bessel correction and the risk-free term from
# Sharpe with the whole suite green. Both are asserted against numbers worked
# out by hand rather than against the implementation.
import math as _math

_xs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
# mean 5; squared deviations sum to 32. Population sd = sqrt(32/8) = 2.
# SAMPLE sd = sqrt(32/7) = 2.13809... — a sample of returns is what this is.
check("stdev uses the sample denominator (n-1), not the population one",
      abs(risk._stdev(_xs) - _math.sqrt(32.0 / 7.0)) < 1e-12, risk._stdev(_xs))
check("and is therefore strictly larger than the population figure",
      risk._stdev(_xs) > _math.sqrt(32.0 / 8.0), risk._stdev(_xs))
check("a single observation has no dispersion", risk._stdev([5.0]) == 0.0)

# Sharpe must subtract the risk-free rate. Deleting `- rf` leaves a ratio with
# the same name and a different meaning, and risk.py's own comment claims the
# subtraction is there.
_conn = connect(":memory:")
_inst = get_or_create_institution(_conn, "S")
_acct = get_or_create_account(_conn, _inst, "S1", "S", "brokerage", "taxable")
_sec = get_or_create_security(_conn, "SS")
_dates = [f"2026-{m:02d}-01" for m in range(1, 13)]
for _i, _d in enumerate(_dates):
    _conn.execute("INSERT INTO prices (security_id, bar_date, close, source)"
                  " VALUES (?,?,?,?)", (_sec, _d, 100.0 * (1.02 ** _i), "test"))
_rf = get_or_create_security(_conn, "DGS3MO")
for _d in _dates:
    _conn.execute("INSERT INTO prices (security_id, bar_date, close, source)"
                  " VALUES (?,?,?,?)", (_rf, _d, 4.0, "test"))     # 4% as a percent
_conn.execute("INSERT INTO transactions (account_id, txn_date, kind, security_id,"
              " quantity, price, amount, fees, commission, source, source_id)"
              " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (_acct, _dates[0], "buy", _sec, 100.0, 100.0, -10000.0, 0.0, 0.0,
               "t", "s1"))
_conn.commit()
_txns = performance.load_transactions(_conn, _dates[0], _dates[-1], "investment")
_m = risk.metrics(_conn, _txns, _dates, multi_account=False)
check("the risk-free rate reaches the metrics payload",
      abs((_m.get("risk_free") or 0) - 0.04) < 1e-9, _m.get("risk_free"))
check("it is not silently assumed to be zero",
      _m.get("risk_free_assumed_zero") is False, _m.get("risk_free_assumed_zero"))
# The two checks below used to sit inside `if sharpe is not None and volatility`,
# which means the assertion this whole fixture exists for would have been SKIPPED
# — silently, and reported as a pass — by any change that stopped Sharpe being
# computed at all. A precondition worth guarding is worth asserting.
check("this fixture actually produces a Sharpe to check",
      _m.get("sharpe") is not None and _m.get("volatility"),
      (_m.get("sharpe"), _m.get("volatility")))
# Sharpe is excess/vol, so it must equal (cagr - rf)/vol exactly.
check("Sharpe is EXCESS over cash divided by volatility",
      _m.get("sharpe") is not None and _m.get("volatility")
      and abs(_m["sharpe"] - (_m["cagr"] - _m["risk_free"]) / _m["volatility"]) < 1e-9,
      _m.get("sharpe"))
check("dropping the risk-free term would change the number",
      _m.get("sharpe") is not None and _m.get("volatility")
      and abs(_m["sharpe"] - _m["cagr"] / _m["volatility"]) > 1e-6,
      (_m.get("sharpe"), _m.get("cagr")))


# ------------------------------------------------- give-back while held ----
# The peak is measured from the first open lot, never from history the holder
# was not exposed to. AEVA's 2021 high and ASST's 2023 print were both being
# reported as give-backs on positions opened in 2026.
from datetime import date as _date, timedelta as _td

_gconn = connect(":memory:")
_gsec = get_or_create_security(_gconn, "GB")
for _i in range(180):
    _d = (_date(2025, 1, 1) + _td(days=_i)).isoformat()
    _px = (200.0 if _d == "2025-01-15" else      # the all-history high, before entry
           150.0 if _d == "2025-04-01" else      # the high while held
           100.0 if _d >= "2025-06-01" else      # where it sits now, back at cost
           100.0)
    # The held high carries an intraday high above its close: the peak is
    # that high (155), the way the broker's gain read at the time.
    _hi = 155.0 if _d == "2025-04-01" else _px
    _gconn.execute("INSERT INTO prices (security_id, bar_date, high, close, source) VALUES (?,?,?,?,?)",
                   (_gsec, _d, _hi, _px, "test"))
_pos = [{"symbol": "GB", "price": 100.0, "unrealised_pct": 0.0, "quantity": 10.0,
         "oldest_lot": "2025-03-01", "value": 1000.0, "weight": 1.0}]
_rows = risk.position_moves(_gconn, _pos, "2025-06-29")
_r = _rows[0] if _rows else {}
check("the peak is the intraday high while held, not the all-history high",
      _r.get("peak") == 155.0, _r.get("peak"))
check("the all-history high is still reported, apart",
      _r.get("all_time_high") == 200.0 and _r.get("all_time_high_date") == "2025-01-15",
      (_r.get("all_time_high"), _r.get("all_time_high_date")))
check("from peak is measured from the held intraday peak",
      abs((_r.get("from_peak") or 0) - (100/155 - 1)) < 1e-4, _r.get("from_peak"))
check("gain on cost at the peak is in the bars' own terms (cost 100, peak 155)",
      abs((_r.get("gain_at_peak_pct") or 0) - 0.55) < 1e-6, _r.get("gain_at_peak_pct"))
check("given back in points of cost is the gap between the two gains",
      abs((_r.get("given_back_pct") or 0) - 0.55) < 1e-6, _r.get("given_back_pct"))
check("given back in dollars is the price fall on the shares held",
      abs((_r.get("given_back_usd") or 0) - 550.0) < 1e-6, _r.get("given_back_usd"))
check("the note states gain at peak against gain now",
      any("+55% on cost there" in n and "+0% now" in n for n in _r.get("notes", [])), _r.get("notes"))
_rows2 = risk.position_moves(_gconn, [{"symbol": "GB", "price": 100.0, "unrealised_pct": 0.0,
                                       "quantity": 10.0, "value": 1000.0}], "2025-06-29")
check("without a lot date the peak is the history's high",
      bool(_rows2) and _rows2[0]["peak"] == 200.0, _rows2[0]["peak"] if _rows2 else None)
_gconn.close()


# ------------------------------------------------------------- dust ----
# A fraction of a share left behind by a rounding difference is not a holding.
from app import holdings as _h
_dc = connect(":memory:")
_inst = get_or_create_institution(_dc, "T2")
_acct = get_or_create_account(_dc, _inst, "B", "Test2", "brokerage", "taxable")
_sec = get_or_create_security(_dc, "DUST")
_dc.execute("""INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity, price, amount, source, source_id)
               VALUES (?,?,?,?,?,?,?,?,?)""", (_acct, "2025-09-22", "buy", _sec, 0.0147, 300.0, -4.41, "t", "d1"))
_dc.execute("""INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity, price, amount, source, source_id)
               VALUES (?,?,?,?,?,?,?,?,?)""", (_acct, "2025-11-14", "sell", _sec, -0.014679, 325.72, 4.78, "t", "d2"))
_dtx = performance.load_transactions(_dc, "1900-01-01", "2026-09-03", "investment")
check("a residual of a few hundred-thousandths of a share is not a position",
      not [p for p in _h.positions(_dc, _dtx, "2026-09-03") if p["symbol"] == "DUST"])
_dc.close()

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
