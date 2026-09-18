"""Backtest tests, centred on the one failure that invalidates everything.

A backtest that peeks at the future does not produce a slightly optimistic
number, it produces a fictional one, and it looks its best exactly when it is
most wrong. So the first tests here construct series where lookahead would be
unmistakable, and check it does not happen.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ledger import connect
from app import backtest, methods

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def bars(closes):
    out = []
    for i, c in enumerate(closes):
        y, m = 2020 + i // 12, i % 12 + 1
        out.append({"time": f"{y}-{m:02d}-01", "open": c, "close": c,
                    "high": c, "low": c, "volume": 1000})
    return out


# --- truncation: the method must never see a bar after the decision date ---
b = bars(list(range(1, 61)))
vis = backtest._bars_before(b, "2022-01-01")
check("truncation excludes every bar after the decision date",
      all(x["time"] <= "2022-01-01" for x in vis), len(vis))
check("truncation includes the decision date itself",
      vis[-1]["time"] == "2022-01-01", vis[-1]["time"])
check("truncation is not the whole series", len(vis) < len(b), (len(vis), len(b)))

# --- fills happen strictly after the signal --------------------------------
nxt = backtest._next_open(b, "2022-01-01")
check("the fill bar is strictly after the decision bar", nxt and nxt[0] > "2022-01-01", nxt)
check("no fill exists after the final bar",
      backtest._next_open(b, b[-1]["time"]) is None)

# --- a method scored on truncated data cannot see the future ---------------
# Two series identical up to the cut, wildly different after. If evaluation
# leaked future data, the scores at the cut would differ.
early = list(range(1, 31))
a1 = bars(early + [100] * 30)
a2 = bars(early + [1] * 30)
cut = a1[29]["time"]
s1 = methods.evaluate(backtest._bars_before(a1, cut), "momentum-relative-strength")
s2 = methods.evaluate(backtest._bars_before(a2, cut), "momentum-relative-strength")
check("identical history scores identically regardless of what follows",
      s1.get("pct") == s2.get("pct"), (s1.get("pct"), s2.get("pct")))

# --- rebalance calendar ----------------------------------------------------
by_sym = {"X": bars(list(range(1, 49)))}
monthly = backtest.rebalance_dates(by_sym, "2020-01-01", "2023-12-01", "M")
check("monthly rebalancing yields one date per month",
      len(monthly) == len({d[:7] for d in monthly}), len(monthly))
check("rebalance dates stay inside the requested range",
      all("2020-01-01" <= d <= "2023-12-01" for d in monthly))

# --- the real thing --------------------------------------------------------
conn = connect()
syms = [r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist LIMIT 40")]
r = backtest.run(conn, "momentum-relative-strength", syms, "2023-01-01", "2026-08-28")
check("a real backtest runs", "error" not in r, r.get("error"))
if "error" not in r:
    check("equity curve has one point per rebalance",
          len(r["equity"]) == r["rebalances"], (len(r["equity"]), r["rebalances"]))
    check("equity never goes negative", all(e["value"] >= 0 for e in r["equity"]))
    check("max drawdown is between -100% and 0",
          -1 <= r["max_drawdown"] <= 0, r["max_drawdown"])
    check("never holds more than the position limit",
          all(e["positions"] <= r["max_positions"] for e in r["equity"]),
          max(e["positions"] for e in r["equity"]))
    # Asserting r["cost_bps"] > 0 only restated the argument we passed in, so
    # deleting the cost logic entirely left this green. The effect is below.
    check("it states its own caveats", len(r["caveats"]) >= 4)
    check("survivorship is named first among the caveats",
          "urvivorship" in r["caveats"][0], r["caveats"][0][:40])

    # Costs must reduce returns; if they do not, they are not being applied.
    free = backtest.run(conn, "momentum-relative-strength", syms,
                        "2023-01-01", "2026-08-28", cost_bps=0)
    # STRICTLY lower. `>=` was satisfied by equality, which is exactly the state
    # you are in when costs are not being applied at all.
    check("costs actually reduce the return, not merely fail to raise it",
          free["total_return"] > r["total_return"],
          (free["total_return"], r["total_return"]))
    check("the cost difference is proportional to the rate charged",
          abs(free["total_return"] - r["total_return"]) > 1e-6,
          (free["total_return"], r["total_return"]))

check("an unknown method errors rather than backtesting nothing",
      "error" in backtest.run(conn, "nope", syms, "2023-01-01", "2026-08-28"))
check("a control universe is defined and survivorship-free",
      len(backtest.NEUTRAL_UNIVERSE) >= 10)

# ===========================================================================
# A SYNTHETIC PRICE DATABASE
#
# Everything above tests _bars_before and _next_open in isolation. That proves
# the two helpers work; it proves nothing about whether run() uses them. Both
# of these one-line edits inside run() passed every assertion in this file:
#
#     visible = _bars_before(bars, dt)     ->  visible = bars
#     bench_visible = _bars_before(...)    ->  bench_visible = bench_tf
#
# which is the exact look-ahead the module exists to prevent, and the second is
# a leak of future INDEX levels into a past decision — the thing the comment in
# run() warns about. A test that cannot fail when the promise is broken is not
# testing the promise, so the rest of this file drives the whole loop against a
# database built for the purpose. In-memory, so the real ledger is never
# touched and no test can be poisoned by whatever happens to be cached in it.
# ===========================================================================
import math
from datetime import date as _date, timedelta as _td
from app import indicators as I, prices
from app.ledger import connect as _connect

_N_BARS = 780                       # about three years of sessions
_CUT_I = 600                        # where the two halves of a paired fixture split


def _sessions(n=_N_BARS):
    out, d = [], _date(2021, 1, 4)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += _td(days=1)
    return out


DATES = _sessions()
CUT, LAST = DATES[_CUT_I], DATES[-1]


def path(pre_rate, post_rate=None, wobble=0.03, base=100.0):
    """A compounding series that changes trend at the cut, with a sawtooth on top.

    The wobble is not decoration: a series that only ever rises pins RSI at 100
    and fails the momentum method's exhaustion ceiling, so nothing would ever
    qualify and every run would sit in cash — a test that passes for the wrong
    reason.
    """
    out, v = [], base
    for i in range(_N_BARS):
        v *= (1 + (pre_rate if (post_rate is None or i <= _CUT_I) else post_rate))
        out.append(round(v * (1 + wobble * math.sin(i / 3.0)), 4))
    return out


def fixture(series: dict, dates=None):
    """symbol -> closes, or symbol -> (closes, volumes) where volume matters."""
    dates = dates or DATES
    conn = _connect(":memory:")
    for sym, spec in series.items():
        closes, vols = spec if isinstance(spec, tuple) else (spec, None)
        prices.store(conn, sym, [
            (t, round(c, 4), round(c, 4), round(c * 1.01, 4), round(c * 0.99, 4),
             100_000 if vols is None else vols[i])
            for i, (t, c) in enumerate(zip(dates, closes))], "test")
    conn.commit()
    return conn


MOM = "momentum-relative-strength"
FROM = DATES[300]                   # leaves ~60 weekly rebalances before the cut

# --- LOOK-AHEAD, end to end: what happens later cannot change what happened --
# Two databases with byte-identical history up to the cut and violently
# different histories after it. Every equity point dated on or before the cut
# must match exactly. If any decision at those dates could see past them, the
# curves separate — and they do, immediately, under either truncation mutation.
_lead = path(0.0016)                                    # strong all the way
_lag = path(0.0002)                                     # dull all the way
_bench = path(0.0003, wobble=0.004)
_before = fixture({"SPY": _bench, "SP500": _bench, "LEAD": _lead, "LAG": _lag})
_after = fixture({"SPY": _bench, "SP500": _bench,
                  "LEAD": path(0.0016, -0.006),         # the leader collapses
                  "LAG": path(0.0002, 0.006)})          # the laggard takes off
_ra = backtest.run(_before, MOM, ["LEAD", "LAG"], FROM, LAST, max_positions=1)
_rb = backtest.run(_after, MOM, ["LEAD", "LAG"], FROM, LAST, max_positions=1)
_pre_a = [e for e in _ra["equity"] if e["date"] <= CUT]
_pre_b = [e for e in _rb["equity"] if e["date"] <= CUT]
check("the fixture actually diverges after the cut, or this proves nothing",
      len(_pre_a) > 20 and _ra["equity"][-1]["value"] != _rb["equity"][-1]["value"],
      (len(_pre_a), _ra["equity"][-1]["value"], _rb["equity"][-1]["value"]))
check("rewriting a name's FUTURE changes nothing about its past equity",
      _pre_a == _pre_b,
      next((i for i, (x, y) in enumerate(zip(_pre_a, _pre_b)) if x != y), None))

# The benchmark is the leak that is easy to miss, because it is loaded once
# outside the loop: the same series is reused at every rebalance, so handing
# evaluate() the whole thing dates every relative-strength reading to the end of
# the backtest. Here the two databases hold IDENTICAL symbols and differ only in
# what the index does after the cut.
_boom = fixture({"SPY": path(0.0003, 0.010, 0.004), "SP500": path(0.0003, 0.010, 0.004),
                 "LEAD": _lead, "LAG": _lag})
_bust = fixture({"SPY": path(0.0003, -0.008, 0.004), "SP500": path(0.0003, -0.008, 0.004),
                 "LEAD": _lead, "LAG": _lag})
_rc = backtest.run(_boom, MOM, ["LEAD", "LAG"], FROM, LAST, max_positions=1)
_rd = backtest.run(_bust, MOM, ["LEAD", "LAG"], FROM, LAST, max_positions=1)
_pre_c = [e for e in _rc["equity"] if e["date"] <= CUT]
_pre_d = [e for e in _rd["equity"] if e["date"] <= CUT]
check("the benchmark fixture diverges after the cut too",
      _rc["equity"][-1]["value"] != _rd["equity"][-1]["value"],
      (_rc["equity"][-1]["value"], _rd["equity"][-1]["value"]))
check("rewriting the BENCHMARK's future changes nothing about past decisions",
      _pre_c == _pre_d,
      next((i for i, (x, y) in enumerate(zip(_pre_c, _pre_d)) if x != y), None))

# --- the fill is the next bar's OPEN, not the close that produced the signal --
# Asserting this on _next_open alone leaves run() free to price a fill anywhere.
# The method decides on a bar's close and the fill belongs to the following
# bar's open, so for every recorded trade: the price is that bar's open, it is
# NOT that bar's close, and — the sentence in the module docstring — it is not
# the close of the previous bar either, which is the bar that produced the
# signal and the price a look-ahead backtest would quietly use.
_ohlc = {}
for _sym in ("LEAD", "LAG"):
    _wk = I.resample(prices.load_bars(_before, _sym, DATES[0], LAST), "W")
    for _j, _b in enumerate(_wk):
        _ohlc[(_sym, _b["time"])] = (round(_b["open"], 4), round(_b["close"], 4),
                                     round(_wk[_j - 1]["close"], 4) if _j else None)
_tl = _ra["trade_log"]
check("every fill is priced at the open of the bar it is dated on",
      _tl and all(t["price"] == _ohlc[(t["symbol"], t["date"])][0] for t in _tl),
      [(t["symbol"], t["date"], t["price"], _ohlc[(t["symbol"], t["date"])][0])
       for t in _tl if t["price"] != _ohlc[(t["symbol"], t["date"])][0]][:2])
check("no fill is priced at the close of the bar that produced the signal",
      all(t["price"] != _ohlc[(t["symbol"], t["date"])][2] for t in _tl),
      [(t["symbol"], t["date"]) for t in _tl
       if t["price"] == _ohlc[(t["symbol"], t["date"])][2]][:3])

# --- the cost model applies to BOTH sides of every trade ---------------------
# "Costs reduce the return" only proves SOME cost is charged: dropping the sell
# side alone left it green. With one position at a time every fill converts the
# whole book, so the drag is exactly (1-c) per fill — buys and sells alike, and
# the exponent is the fill count, not the buy count.
_c = 0.004                                        # 40 bps, big enough to see
_costly = backtest.run(_before, MOM, ["LEAD", "LAG"], FROM, LAST,
                       max_positions=1, cost_bps=int(_c * 10_000))
_freely = backtest.run(_before, MOM, ["LEAD", "LAG"], FROM, LAST,
                       max_positions=1, cost_bps=0)
_fills = _costly["trades"]          # trade_log is only the last 40
check("the fixture round-trips, so both sides of the cost model are exercised",
      _fills >= 2 and any(t["side"] == "sell" for t in _costly["trade_log"])
      and any(t["side"] == "buy" for t in _costly["trade_log"]),
      (_fills, {t["side"] for t in _costly["trade_log"]}))
check("charging costs never changes which names get bought, only what is left",
      _costly["trades"] == _freely["trades"], (_costly["trades"], _freely["trades"]))
check("every fill costs exactly the modelled spread, buys and sells alike",
      abs((1 + _costly["total_return"]) / (1 + _freely["total_return"])
          - (1 - _c) ** _fills) < 1e-5,
      ((1 + _costly["total_return"]) / (1 + _freely["total_return"]),
       (1 - _c) ** _fills, _fills))

# --- the threshold is a filter, not a label ---------------------------------
_unreachable = backtest.run(_before, MOM, ["LEAD", "LAG"], FROM, LAST,
                            max_positions=1, threshold=1.01)
check("a threshold nothing can clear buys nothing and stays in cash",
      _unreachable["trades"] == 0
      and _unreachable["equity"][-1]["value"] == _unreachable["starting_cash"],
      (_unreachable["trades"], _unreachable["equity"][-1]["value"]))

# --- allocation must not depend on hash order -------------------------------
# `wanted` was a set, which discarded the ranking, and a starved entry takes
# whatever cash is left — so WHICH names got funded varied between runs under
# different PYTHONHASHSEED values. Same inputs, different backtest. This used to
# be four greps for the current source text, which restate the implementation
# and would pass on any rewrite that reintroduced the bug differently.
_tied = fixture({"SPY": _bench, "SP500": _bench, "AAAA": _lead, "ZZZZ": list(_lead)})
_rt = backtest.run(_tied, MOM, ["ZZZZ", "AAAA"], FROM, LAST, max_positions=1)
check("two names with identical histories score identically",
      _rt["equity"][-1]["candidates"] == 2, _rt["equity"][-1])
check("a tie is broken on the symbol, so the same run funds the same name",
      _rt["trade_log"] and {t["symbol"] for t in _rt["trade_log"]} == {"AAAA"},
      {t["symbol"] for t in _rt["trade_log"]})

# Rank order, behaviourally: two candidates that both clear the threshold but do
# NOT score the same, and whose alphabetical order is the reverse of their
# strength — otherwise the tie-break alone would pick the right name and a sort
# running the wrong way round would go unnoticed. Both are identical series;
# AWEAK's volume dries up at the end, so it fails one condition and only one.
_fading = [100_000 if i < _N_BARS - 120 else 100 for i in range(_N_BARS)]
_two = fixture({"SPY": _bench, "SP500": _bench,
                "ZBEST": _lead, "AWEAK": (list(_lead), _fading)})
_r2 = backtest.run(_two, MOM, ["AWEAK", "ZBEST"], DATES[700], LAST,
                   max_positions=1, threshold=0.5)
check("both names are candidates, so the ranking is what decides between them",
      set(e["candidates"] for e in _r2["equity"]) == {2},
      sorted({e["candidates"] for e in _r2["equity"]}))
check("when only one slot is funded it goes to the highest-scoring name",
      _r2["trade_log"] and {t["symbol"] for t in _r2["trade_log"]} == {"ZBEST"},
      {t["symbol"] for t in _r2["trade_log"]})

# --- the coverage floor the live scanner also applies ------------------------
# A name can clear the threshold on a THIRD of the method's weight: 275 sessions
# is not enough history for a 200-period weekly average, a 50-bar volume
# comparison, or (with no index cached) relative strength, which between them
# are 5 of the method's 9 points. What is left it passes perfectly, so its score
# is 1.0 and its trend filter was never evaluated at all. Without the floor the
# backtest buys it.
_short_dates = _sessions(275)
_thin = fixture({"THIN": path(0.0016)[:275]}, _short_dates)
_ev = methods.evaluate(prices.load_bars(_thin, "THIN", _short_dates[0], _short_dates[-1]),
                       MOM)
check("the thin fixture is exactly the trap: a perfect score on a third of the weight",
      _ev["pct"] >= 0.75 and _ev["coverage"] < 0.6,
      (_ev["pct"], round(_ev["coverage"], 3), _ev["unavailable"]))
_rthin = backtest.run(_thin, MOM, ["THIN"], _short_dates[-40], _short_dates[-1],
                      max_positions=1)
check("a name scoring 1.0 on a third of the method is not bought",
      _rthin["trades"] == 0
      and _rthin["equity"][-1]["value"] == _rthin["starting_cash"],
      (_rthin["trades"], _rthin["equity"][-1]["value"]))

# --- the Sharpe caveat must match what was actually subtracted ---------------
# A Sharpe computed against an assumed zero risk-free rate is a different number
# with the same name, and over a period when cash paid 4-5% it is not a rounding
# difference. The fixture has no Treasury series cached, so the caveat has to
# say the ratio is flattered rather than claim excess over cash.
check("with no Treasury series cached the risk-free rate is reported as zero",
      _ra["risk_free_rate"] == 0, _ra["risk_free_rate"])
check("and the caveats admit the Sharpe is flattered rather than claiming excess "
      "over cash",
      any("ZERO risk-free rate" in c for c in _ra["caveats"])
      and not any("excess over the 3-month Treasury, not raw" in c
                  for c in _ra["caveats"]),
      _ra["caveats"][-1][:60])
if "error" not in r:
    # The real ledger does cache it, so the same run must make the opposite
    # claim. Both branches have to be exercised or the wording is decoration.
    _has_rf = r["risk_free_rate"] > 0
    check("a run with a real Treasury rate subtracts it and says so",
          _has_rf and any("excess over the 3-month Treasury" in c for c in r["caveats"])
          and not any("ZERO risk-free rate" in c for c in r["caveats"]),
          (r["risk_free_rate"], r["caveats"][-1][:50]))

# ===========================================================================
# THE SURVIVORSHIP CONTROL
#
# with_control exists because the momentum method returned +398% on the user's
# own watchlist and -4.0% on sector ETFs over the identical period. Nothing
# tested it beyond `len(NEUTRAL_UNIVERSE) >= 10`, so the verdict could be
# rewired to read the flattered number, or the control could be run on the very
# universe it is meant to control for, and the suite stayed green.
#
# The fixture reproduces the shape of that finding: three hand-picked winners,
# a neutral universe that goes nowhere, and an index that drifts up.
# ===========================================================================
_flat = path(0.0)
_ctl_series = {"SPY": _bench, "SP500": _bench}
for _s in ("WINA", "WINB", "WINC"):
    _ctl_series[_s] = path(0.0016)
for _s in backtest.NEUTRAL_UNIVERSE:
    if _s != "SPY":
        _ctl_series[_s] = list(_flat)
_ctl_conn = fixture(_ctl_series)
wc = backtest.with_control(_ctl_conn, MOM, ["WINA", "WINB", "WINC"], FROM, LAST,
                           max_positions=3)

check("with_control reports both runs, not just the flattering one",
      "error" not in wc["live"] and "error" not in wc["control"],
      (wc["live"].get("error"), wc["control"].get("error")))
check("the control ignores the caller's universe and uses the neutral one",
      wc["control"]["universe"] == len(backtest.NEUTRAL_UNIVERSE)
      and wc["live"]["universe"] == 3,
      (wc["live"]["universe"], wc["control"]["universe"]))
check("the universe gap is the difference between the two excess returns",
      abs(wc["universe_gap"] - (wc["live"]["excess"] - wc["control"]["excess"])) < 1e-9,
      (wc["universe_gap"], wc["live"]["excess"], wc["control"]["excess"]))
check("the fixture reproduces the finding: great on the picks, not on the control",
      wc["live"]["excess"] > 0.05 and wc["control"]["excess"] <= 0.05,
      (round(wc["live"]["excess"], 3), round(wc["control"]["excess"], 3)))
# THE POINT OF THE WHOLE FUNCTION. A method that only works on names chosen with
# hindsight must be described that way, and the sentence has to be driven by the
# CONTROL number. Keying it off the live number instead produces a verdict that
# endorses the very result the control just refuted.
check("a method that wins only on the hand-picked universe is said to",
      "only beats the benchmark on the hand-picked universe" in wc["verdict"],
      wc["verdict"][:70])
check("and the verdict says what the first number actually measured",
      "watchlist" in wc["verdict"], wc["verdict"][-60:])

# The other branch has to be reachable, or the sentence above is the only one
# the function can ever say. Here the neutral universe is the one that runs.
_flip = dict(_ctl_series)
for _s in backtest.NEUTRAL_UNIVERSE:
    if _s != "SPY":
        _flip[_s] = path(0.0016)
wc2 = backtest.with_control(fixture(_flip), MOM, ["WINA", "WINB", "WINC"], FROM, LAST,
                            max_positions=3)
check("a method that also wins on the survivorship-free universe is said to",
      wc2["control"]["excess"] > 0.05
      and "survivorship-free universe too" in wc2["verdict"],
      (round(wc2["control"]["excess"], 3), wc2["verdict"][:60]))

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
