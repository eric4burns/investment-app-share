"""Tests for portfolio frameworks.

Same honesty contract as setups, plus one more: a framework that does not
quantify a principle must not be graded as though it did. Inventing a threshold
and scoring someone against it is putting numbers in their mouth, so any
observation using a threshold this app chose has to say so.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ledger import connect
from app import frameworks, holdings, performance

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

for key, f in frameworks.FRAMEWORKS.items():
    check(f"{key} names a source", bool(f.get("source")))
    check(f"{key} names an attribution", bool(f.get("attribution")))
    check(f"{key} declares confidence",
          f.get("confidence") in {"stated", "reported", "inferred", "proposed"})
    check(f"{key} quotes the person it is attributed to", len(f.get("quotes", [])) >= 2)
    check(f"{key} records its own caveats", len(f.get("caveats", [])) >= 1)
    check(f"{key} describes at least two buckets", len(f.get("buckets", [])) >= 2)
    check(f"{key} gives every bucket rules",
          all(len(b.get("rules", [])) >= 2 for b in f["buckets"]))

conn = connect()
txns = performance.load_transactions(conn, "1900-01-01", "2026-08-28", "investment")
pos = holdings.positions(conn, txns, "2026-08-28")
r = frameworks.check(conn, pos, "jrould-three-buckets")

check("check runs against the real book", "error" not in r, r.get("error"))
check("it produces observations", len(r.get("observations", [])) >= 3)
check("every observation states what the book actually looks like",
      all(o.get("state") for o in r["observations"]))
check("matches is true, false, or explicitly unknown",
      all(o.get("matches") in (True, False, None) for o in r["observations"]))

# THE HONESTY RULE THAT MATTERS HERE.
#
# He quantifies neither "concentrated" nor "small", so any percentage line this
# app grades against is the app's own and must say so — the module docstring
# calls doing otherwise "putting numbers in his mouth". The old version of this
# check accepted `"10%" in o["state"]` as disclosure, which is the literal text
# of the invented threshold itself rather than an admission of whose it is. That
# escape hatch was the only reason it passed: the concentrated-core observation
# asserted `matches: True` against a 10% line and carried no note at all.
def undisclosed_threshold(o: dict) -> bool:
    """A graded observation that uses a percentage without owning the number."""
    if o.get("matches") is None or "%" not in (o.get("state") or ""):
        return False
    note = (o.get("note") or "").lower()
    return not any(w in note for w in ("this app", "not his", "he gives no",
                                       "he does not quantif"))


_graded_pct = [o for o in r["observations"]
               if o["matches"] is not None and "%" in o["state"]]
check("the real book grades at least two principles on a percentage, so this "
      "rule is not vacuous",
      len(_graded_pct) >= 2, [o["principle"] for o in _graded_pct])
check("every threshold the app invented is disclosed as the app's",
      not [o for o in r["observations"] if undisclosed_threshold(o)],
      [(o["principle"], o.get("note")) for o in r["observations"]
       if undisclosed_threshold(o)])
check("and the rule itself rejects a graded percentage with no note",
      undisclosed_threshold({"principle": "x", "state": "3 at 10% or more",
                             "matches": True, "note": None}))
check("while an ungraded observation is exempt, since it grades nothing",
      not undisclosed_threshold({"principle": "x", "state": "3 at 10% or more",
                                 "matches": None}))

check("an unknowable principle is reported as unknown, not guessed",
      any(o["matches"] is None for o in r["observations"]))
check("an unknown framework errors",
      "error" in frameworks.check(conn, pos, "nope"))
check("catalogue exposes every framework",
      len(frameworks.catalogue()) == len(frameworks.FRAMEWORKS))

# --- check() against books built on purpose ----------------------------------
# Everything above runs against the real ledger, whose shape changes as the user
# trades — so which branches execute is not under the test's control, and a
# branch can quietly stop being exercised without anything failing. These books
# force each one.
# Sized so the two thresholds are load-bearing: four positions sit at 5% of the
# book, well below "concentrated" and well above "small". A book of only huge
# and tiny positions would score the same however wide either line was drawn.
_INCOME = "SCHD"
_core_book = ([{"symbol": "BIG", "value": 4000.0, "weight": 0.408},
               {"symbol": "MID", "value": 2000.0, "weight": 0.204},
               {"symbol": _INCOME, "value": 1200.0, "weight": 0.122}]
              + [{"symbol": f"MED{i}", "value": 500.0, "weight": 0.051}
                 for i in range(4)]
              + [{"symbol": f"SPEC{i}", "value": 100.0, "weight": 0.0102}
                 for i in range(6)])
_r_core = {o["principle"]: o for o in
           frameworks.check(conn, _core_book, "jrould-three-buckets")["observations"]}
check("a book with double-digit positions is described as having a core",
      _r_core["A concentrated core"]["matches"] is True
      and "BIG" in _r_core["A concentrated core"]["state"],
      _r_core["A concentrated core"]["state"])
# Exactly six, not eleven: the four 5% positions are neither the core nor
# speculative change, and widening "small" to swallow them would report a
# concentrated book as a diversified one.
check("exactly the six positions under 2% count as the small speculative bets",
      _r_core["Numerous small speculative bets alongside the core"]["matches"] is True
      and _r_core["Numerous small speculative bets alongside the core"]["state"]
      .startswith("6 position(s) below 2%"),
      _r_core["Numerous small speculative bets alongside the core"]["state"])
check("and the three positions at or above 10% are the core, not the mid-sized ones",
      _r_core["A concentrated core"]["state"].startswith("3 position(s) at 10% or more")
      and "MED0" not in _r_core["A concentrated core"]["state"],
      _r_core["A concentrated core"]["state"])
check("a recognised income fund satisfies the dividend counterbalance",
      _r_core["Dividends as a counterbalance to the speculation"]["matches"] is True
      and _INCOME in _r_core["Dividends as a counterbalance to the speculation"]["state"],
      _r_core["Dividends as a counterbalance to the speculation"]["state"])

# The same book with the income fund swapped for an ordinary stock. The note
# already admits this: a dividend-paying individual name held for its yield is
# not recognised, and the observation must say "none identifiable" rather than
# guessing.
_no_income = [dict(p, symbol="ZZZ") if p["symbol"] == _INCOME else p
              for p in _core_book]
_r_none = {o["principle"]: o for o in
           frameworks.check(conn, _no_income, "jrould-three-buckets")["observations"]}
check("with no recognised income fund the dividend principle reports a miss",
      _r_none["Dividends as a counterbalance to the speculation"]["matches"] is False,
      _r_none["Dividends as a counterbalance to the speculation"]["state"])
check("a principle the ledger cannot answer stays unknown on every book",
      _r_core["Swing trades sized smaller than long-term holds"]["matches"] is None
      and _r_none["Swing trades sized smaller than long-term holds"]["matches"] is None)
check("largest is the biggest position's share of the book, not its dollar value",
      abs(frameworks.check(conn, _core_book, "jrould-three-buckets")["largest"]
          - 4000.0 / sum(p["value"] for p in _core_book)) < 1e-9,
      frameworks.check(conn, _core_book, "jrould-three-buckets")["largest"])
check("positions with no value are left out of the book entirely",
      frameworks.check(conn, _core_book + [{"symbol": "GHOST", "value": 0.0}],
                       "jrould-three-buckets")["positions"] == len(_core_book),
      frameworks.check(conn, _core_book + [{"symbol": "GHOST", "value": 0.0}],
                       "jrould-three-buckets")["positions"])

# --- the DCA ladder ----------------------------------------------------------
# This is the module's only computation and it had no test. It also matters more
# than most: the LADDER is his, the TRIGGER is not — what colours his candles is
# a proprietary tool he does not disclose — so this is the app approximating
# somebody's signal under their name. Every tier boundary, and the flag that
# stops the result being read as his, are pinned here.
from datetime import date as _date, timedelta as _td               # noqa: E402
from app import prices as _prices                                  # noqa: E402
from app.ledger import connect as _connect                         # noqa: E402

check("the ladder is ordered from the rarest tier down to the base contribution",
      [m for _t, m, _c, _w in frameworks.DCA_LADDER] == [4, 3, 2, 1],
      [m for _t, m, _c, _w in frameworks.DCA_LADDER])
check("its thresholds rise toward zero and the last one catches everything else",
      frameworks.DCA_LADDER[-1][0] is None
      and all(a[0] < b[0] for a, b in zip(frameworks.DCA_LADDER,
                                          frameworks.DCA_LADDER[1:-1])),
      [t for t, _m, _c, _w in frameworks.DCA_LADDER])
check("every tier explains what it is reading",
      all(w and c for _t, _m, c, w in frameworks.DCA_LADDER))


def _dca_conn(last_close):
    """Thirty sessions whose 12-bar range is a flat 100-110, ending where told.

    Williams %R is then exactly -100 * (110 - close) / 10, so each tier
    boundary can be hit on purpose rather than hoped for.
    """
    conn = _connect(":memory:")
    closes = [105.0] * 29 + [last_close]
    _prices.store(conn, "TIER", [(f"2026-{i//28+1:02d}-{i%28+1:02d}", c, c, 110.0,
                                  100.0, 100) for i, c in enumerate(closes)], "test")
    conn.commit()
    return conn


_tiers = {}
for _close, _want_mult, _want_tier in ((100.0, 4, "purple"), (101.0, 3, "lime green"),
                                       (102.5, 2, "amber"), (105.0, 1, "white")):
    _c = _dca_conn(_close)
    _tiers[_close] = frameworks.dca_multiplier(_c, "TIER", "2026-02-02", "D")
    check(f"a close at {_close} reads %R {-100*(110-_close)/10:.0f} and buys "
          f"{_want_mult}x ({_want_tier})",
          _tiers[_close]["multiplier"] == _want_mult
          and _tiers[_close]["tier"] == _want_tier,
          (_tiers[_close].get("williams_r"), _tiers[_close].get("multiplier"),
           _tiers[_close].get("tier")))
check("the ladder is monotone: the more oversold it reads, the more it buys",
      [_tiers[c]["multiplier"] for c in (100.0, 101.0, 102.5, 105.0)] == [4, 3, 2, 1],
      [_tiers[c]["multiplier"] for c in sorted(_tiers)])
# The one thing that must never be dropped. His candle colouring is proprietary
# and not reproduced here, so a tier this app computed has to arrive labelled as
# an approximation or the UI has no way to avoid presenting it as his signal.
check("every computed tier is flagged as this app's approximation, not his signal",
      all(t.get("approximation") is True and t.get("why") for t in _tiers.values()),
      [(c, t.get("approximation")) for c, t in _tiers.items()
       if not t.get("approximation")])
check("and the framework's caveats say the trigger is not his",
      any("proprietary" in c.lower() and "approximation" in c.lower()
          for c in frameworks.FRAMEWORKS["ronniev-dca-optimizer"]["caveats"]),
      frameworks.FRAMEWORKS["ronniev-dca-optimizer"]["caveats"][0][:60])

# Too little history must say so rather than defaulting to the 1x tier, which
# would be indistinguishable from a real "normal conditions" reading.
# Fifteen sessions: enough for a 12-period %R to produce a number, so the
# length guard is the only thing standing between a three-week-old listing and
# a confident "4x, buy quadruple this month".
_short = _connect(":memory:")
_prices.store(_short, "TINY", [(f"2026-01-{i+1:02d}", 100.0 + i, 100.0 + i, 101.0 + i,
                                99.0 + i, 10) for i in range(15)], "test")
_short.commit()
check("a name with too little history reports insufficient, not a 1x reading",
      frameworks.dca_multiplier(_short, "TINY", "2026-01-15", "D").get("insufficient")
      is True and "multiplier" not in frameworks.dca_multiplier(
          _short, "TINY", "2026-01-05", "D"),
      frameworks.dca_multiplier(_short, "TINY", "2026-01-15", "D"))
check("and so does a name with no history at all",
      frameworks.dca_multiplier(_short, "NOSUCH", "2026-01-15", "D").get("insufficient")
      is True)

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
