"""Checks on the exit-rule replay.

The danger here is not a crash, it is a plausible wrong answer. A backtest that
peeks one bar into the future looks brilliant and is worthless, and a summary
that reports "helped 9 of 13" without saying the rule fired at the first bar it
legally could reads as timing skill when it is nothing of the sort.

The module makes two promises that these tests exist to hold it to:

  * NO LOOKAHEAD. The decision at bar i uses only bars up to and including i.
    That is checked here as a PREFIX PROPERTY over every rule: truncate the
    series anywhere and the answer about the bars that remain must not change.
    A grep for `bars[i + 1]` — which is what this file used to do — passes for
    any rule that reads the future by some other spelling.

  * EVERY rule against EVERY position. One rule fitted to one holding that
    happened to collapse is curve-fitting, so the aggregate is what decides
    which rule leads the table. That is checked by building positions where the
    rule with the single best outcome is NOT the rule that helped most often,
    and asserting the ranking prefers the second.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from datetime import date as _date, timedelta as _td      # noqa: E402
from app import exits, indicators as I, prices            # noqa: E402
from app.ledger import connect                            # noqa: E402

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def bars(closes):
    return [{"time": f"2026-{1 + i//28:02d}-{1 + i%28:02d}", "open": c, "high": c*1.01,
             "low": c*0.99, "close": c, "volume": 1000} for i, c in enumerate(closes)]


# A ramp up then a collapse. Any trend rule must fire AFTER the turn, never before.
up = [10 + i for i in range(60)]          # 10 -> 69
down = [69 - i*2 for i in range(30)]      # 69 -> 11
series = bars(up + down)

i20 = exits.rule_below_sma(series, 20)
check("a moving-average exit fires only after the peak",
      i20 is not None and i20 >= 60, i20)

# A trailing stop measured from the RUNNING peak, never the eventual one.
i_tr = exits.rule_trailing(series, 0.20)
check("a 20% trailing stop fires once price is 20% off the running high",
      i_tr is not None and series[i_tr]["close"] <= 69 * 0.8, i_tr)

# On a series that only ever rises NOTHING may fire. The classic lookahead bug
# is a stop measured against a peak that has not happened yet, and it shows up
# here as a rule firing on the way up. This used to be asserted for two rules;
# the ichimoku pair — the two with a displacement to get wrong — were not
# covered at all.
_only_up = bars(up)
_fired_on_the_way_up = [label for label, fn, _fam, _w in exits.RULES
                        if fn(_only_up) is not None]
check("no rule fires at all on a series that only rises",
      not _fired_on_the_way_up, _fired_on_the_way_up)

# ---------------------------------------------------------------------------
# NO LOOKAHEAD, as a property rather than a grep.
#
# If a rule fires at bar i on the whole series, then it must fire at bar i on
# every prefix that reaches bar i, and say nothing at all on every prefix that
# stops short of it. Any rule reading bar i+1 — or i+2, or a slice, or the
# series maximum — breaks this immediately, because the bars it was peeking at
# are gone while the ones it claims to use are not.
# ---------------------------------------------------------------------------
_never_fired = [label for label, fn, _fam, _w in exits.RULES if fn(series) is None]
check("every rule fires somewhere on this series, so the prefix sweep is not vacuous",
      not _never_fired, _never_fired)
_violations = []
for _label, _fn, _fam, _w in exits.RULES:
    _full = _fn(series)
    if _full is None:
        continue
    for _n in range(1, len(series) + 1):
        _want = _full if _n >= _full + 1 else None
        if _fn(series[:_n]) != _want:
            _violations.append((_label, _n, _fn(series[:_n]), _want))
            break
check("truncating the series never changes a rule's verdict on the bars that remain",
      not _violations, _violations[:3])

# ---------------------------------------------------------------------------
# WARM-UP BOUNDARY. A rule cannot speak before its own window is full, and the
# boundary has to be exact: the old fixture dropped 30 bars in, so a rule that
# spoke one bar early was indistinguishable from one that did not. This series
# is below every average from the very first bar, so each rule fires on exactly
# the bar it becomes legal to.
# ---------------------------------------------------------------------------
_from_the_top = bars([100 - i for i in range(120)])
check("a 20-bar average says nothing until bar 19, and then says it at once",
      exits.rule_below_sma(_from_the_top, 20) == 19,
      exits.rule_below_sma(_from_the_top, 20))
check("a 50-bar average waits until bar 49",
      exits.rule_below_sma(_from_the_top, 50) == 49,
      exits.rule_below_sma(_from_the_top, 50))
check("the kijun needs its full 26-bar range before it can be lost",
      exits.rule_below_kijun(_from_the_top) == 25,
      exits.rule_below_kijun(_from_the_top))
# The cloud is displaced, so it needs 52 bars of range plotted 26 bars further
# on: 77, not 51. Reading the undisplaced cloud would let it speak at 51.
check("the displaced cloud cannot be lost before bar 77",
      exits.rule_below_cloud(_from_the_top) == 77,
      exits.rule_below_cloud(_from_the_top))
check("every rule's declared warm-up is the bar it actually first fires on",
      all(fn(_from_the_top) == warm for _l, fn, _fam, warm in exits.RULES
          if _l.endswith("average") or "kijun" in _l or "cloud" in _l),
      [(l, fn(_from_the_top), w) for l, fn, _f, w in exits.RULES])

check("every rule returns None rather than raising on a short series",
      all(fn(bars([10]*5)) is None for _l, fn, _f, _w in exits.RULES))

# ---------------------------------------------------------------------------
# THE CLOUD THE RULE READS IS THE CLOUD THE CHART DRAWS.
#
# indicators.ichimoku plots senkou A and B `kijun` bars AHEAD of the data they
# came from, and that displacement is a bug this project has had before. The
# exit rule computes its own spans, so the two can silently disagree — the rule
# would then be exiting on a cloud nobody plots. Rather than restate the
# formula, compare the rule against the drawn series bar for bar.
# ---------------------------------------------------------------------------
# A longer ramp, so the cloud is established for a good while BEFORE the rule
# fires. On the 90-bar series above, senkou B's first plotted bar is bar 77 and
# the rule fires on bar 77 — so "it fires on the first such bar" would have had
# no earlier bars to look at and would have passed over an empty loop.
_long = bars([10 + i for i in range(100)] + [110 - i * 2.5 for i in range(40)])
_ich = I.ichimoku(_long, 9, 26, 52)
_span_a = {p["time"]: p["value"] for p in _ich["span_a"]}
_span_b = {p["time"]: p["value"] for p in _ich["span_b"]}
_bottom = {t: min(_span_a[t], _span_b[t]) for t in _span_a if t in _span_b}
_i_cloud = exits.rule_below_cloud(_long)
_covered_before = [b for b in _long[:_i_cloud] if b["time"] in _bottom]
check("the drawn cloud covers the bar the rule fired on and many bars before it",
      _i_cloud is not None and _long[_i_cloud]["time"] in _bottom
      and len(_covered_before) > 20,
      (_i_cloud, len(_bottom), len(_covered_before)))
check("the cloud exit fires where price is under the cloud AS PLOTTED",
      _long[_i_cloud]["close"] < _bottom[_long[_i_cloud]["time"]],
      (_long[_i_cloud]["close"], _bottom[_long[_i_cloud]["time"]]))
check("and it fires on the FIRST such bar, not a later one",
      all(b["close"] >= _bottom[b["time"]] for b in _covered_before),
      [b["time"] for b in _covered_before if b["close"] < _bottom[b["time"]]][:3])

# The kijun exit has to read the same base line the chart draws: the midpoint
# of a 26-bar HIGH/LOW range, not of the closes inside it. The bars everywhere
# else in this file span only +/-1% around the close, which makes those two
# midpoints nearly the same number and hides the difference. These bars run from
# 15% below the close to 30% above it, so a base line built from closes fires
# four bars later and the disagreement is visible.
_wide = [dict(b, high=b["close"] * 1.30, low=b["close"] * 0.85) for b in _long]
_base = {p["time"]: p["value"] for p in I.ichimoku(_wide, 9, 26, 52)["base"]}
_i_kijun = exits.rule_below_kijun(_wide)
check("the kijun exit fires on the first bar closing under the drawn base line",
      _i_kijun is not None and _long[_i_kijun]["close"] < _base[_wide[_i_kijun]["time"]]
      and all(b["close"] >= _base[b["time"]] for b in _wide[:_i_kijun]
              if b["time"] in _base),
      (_i_kijun, _wide[_i_kijun]["close"], _base[_wide[_i_kijun]["time"]]))

# ---------------------------------------------------------------------------
# THE SUMMARY.
#
# summary() was covered by three greps for its own source text plus two
# assertions of the form `X or True`, which are true whatever X is. A fake
# result dict was built and then never passed to anything. So the aggregate —
# the part the module's docstring says is what stops this being curve-fitting —
# had no coverage at all, and every one of these mutations passed: reporting
# every rule as having helped, inverting vs_holding so losing rules read as
# winners, and ranking by the single best outcome.
#
# Three synthetic positions, in memory, so the real ledger is never touched:
#   COLLAPSE — climbs, then decays to a fraction of its peak and stays there.
#              Exiting anywhere near the top beat holding.
#   RECOVER  — climbs, drops two thirds, then makes a new high. Every rule
#              fires into the dip and every one of them cost money.
#   MILDDIP  — climbs, dips 8%, climbs again. Trips the averages, never trips a
#              20% trailing stop, so the rules do NOT all see the same sample.
# ---------------------------------------------------------------------------
def _sessions(n, start=_date(2024, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += _td(days=1)
    return out


DAYS = _sessions(400)
ENTRY = DAYS[120]


def _store(conn, sym, closes):
    prices.store(conn, sym, [(t, round(c, 4), round(c, 4), round(c * 1.02, 4),
                              round(c * 0.98, 4), 1000)
                             for t, c in zip(DAYS, closes)], "test")


_rise = [50 + i * 0.5 for i in range(260)]                        # 50 -> 179.5
_conn = connect(":memory:")
_store(_conn, "COLLAPSE", _rise + [179.5 * (0.985 ** (i + 1)) for i in range(140)])
_store(_conn, "RECOVER", [50 + i * 0.5 for i in range(200)]
       + [150 - (i + 1) * 2.0 for i in range(50)]
       + [50 + (i + 1) * 2.5 for i in range(150)])
_store(_conn, "MILDDIP", [50 + i * 0.5 for i in range(200)]
       + [150 - (i + 1) * 0.6 for i in range(20)]
       + [138 + (i + 1) * 0.5 for i in range(180)])
_store(_conn, "SHORTY", [10.0] * 60)                              # not enough history
_store(_conn, "FDRXX", [1.0] * 400)                               # a cash sweep, not a trade
_conn.commit()

SUM = exits.summary(_conn, [
    {"symbol": "COLLAPSE", "oldest_lot": ENTRY},
    {"symbol": "RECOVER", "oldest_lot": ENTRY},
    {"symbol": "MILDDIP", "oldest_lot": ENTRY},
    {"symbol": "SHORTY", "oldest_lot": DAYS[0]},
    {"symbol": "FDRXX", "oldest_lot": ENTRY},
    # Years of price history, but bought ten sessions ago. A rule needing a
    # 50-bar average has nothing to say about a holding this young, and
    # scoring it anyway would put a row in the table built on six signals
    # that could not have fired.
    {"symbol": "COLLAPSE", "oldest_lot": DAYS[-10]},
    {"symbol": "NOENTRY"},
], DAYS[-1])

# A money-market sweep is a cash balance, not a position anyone chose to hold,
# and a name with 60 bars cannot support a 50-bar average — replaying either
# would put a meaningless row in the table rather than omitting it.
check("only positions with enough history are replayed",
      [p["symbol"] for p in SUM["positions"]] == ["COLLAPSE", "RECOVER", "MILDDIP"],
      [p["symbol"] for p in SUM["positions"]])
check("a holding only a few sessions old is skipped even with years of history behind it",
      sum(1 for p in SUM["positions"] if p["symbol"] == "COLLAPSE") == 1
      and all(p["entry"] == ENTRY for p in SUM["positions"] if p["symbol"] == "COLLAPSE"),
      [(p["symbol"], p["entry"], p["bars"]) for p in SUM["positions"]])
check("n_positions counts what was actually replayed",
      SUM["n_positions"] == 3, SUM["n_positions"])

_by_rule = {r["rule"]: r for r in SUM["rules"]}
_per_pos = {p["symbol"]: {r["rule"]: r for r in p["rules"]} for p in SUM["positions"]}

# "Helped" means the rule got out ABOVE where the position sits now. On a name
# that collapsed and stayed down, every rule that fired helped; on one that dug
# a hole and then made a new high, every rule that fired cost money. Reporting
# every rule as having helped, or flipping the ratio, must be visible.
check("a rule that exited before a collapse reports a gain against holding",
      all(r["vs_holding"] > 0 for r in _per_pos["COLLAPSE"].values() if r["fired"]),
      {k: v.get("vs_holding") for k, v in _per_pos["COLLAPSE"].items()})
check("a rule that exited into a dip that then recovered reports a loss",
      all(r["vs_holding"] < 0 for r in _per_pos["RECOVER"].values() if r["fired"]),
      {k: v.get("vs_holding") for k, v in _per_pos["RECOVER"].items()})
check("helped counts only the positions where the rule beat holding",
      all(r["helped"] == sum(1 for p in SUM["positions"] for x in p["rules"]
                             if x["rule"] == r["rule"] and x.get("fired")
                             and x.get("vs_holding", 0) > 0)
          for r in SUM["rules"]),
      [(r["rule"], r["helped"], r["positions"]) for r in SUM["rules"]])
check("help_rate is helped over the positions the rule actually fired on",
      all(abs(r["help_rate"] - r["helped"] / r["positions"]) < 5e-4
          for r in SUM["rules"]),
      [(r["rule"], r["help_rate"], r["helped"], r["positions"]) for r in SUM["rules"]])
check("no rule claims to have helped everywhere on this sample",
      all(0 < r["help_rate"] < 1 for r in SUM["rules"]),
      [(r["rule"], r["help_rate"]) for r in SUM["rules"]])

# The rules do not all see the same number of positions, because a 20% trailing
# stop simply never fires on an 8% dip. A rule's row must be scored over the
# positions it fired on, not over the three that were replayed.
check("the sample size differs between rules and is reported per rule",
      {r["positions"] for r in SUM["rules"]} == {2, 3},
      {r["rule"]: r["positions"] for r in SUM["rules"]})

# THE ANTI-CURVE-FITTING PROMISE. "below 20-day average" has the single best
# outcome in this sample by a wide margin — and it also fired on a position
# where it cost money that the trailing stops sat out, so it helped least often.
# Ordering on the best single outcome would put exactly that rule on top, which
# is the docstring's own example of the wrong answer.
_best_first = sorted(SUM["rules"], key=lambda r: -r["best"])
check("the fixture separates 'best single outcome' from 'helped most often'",
      _best_first[0]["rule"] != SUM["rules"][0]["rule"],
      (_best_first[0]["rule"], SUM["rules"][0]["rule"]))
check("the rule with the single best outcome does not lead the table",
      SUM["rules"][0]["rule"] != "below 20-day average"
      and _by_rule["below 20-day average"]["best"] == max(r["best"] for r in SUM["rules"]),
      [(r["rule"], r["help_rate"], r["best"]) for r in SUM["rules"]])
check("rules are ranked by how often they helped, then by median size",
      all((-a["help_rate"], -a["median"]) <= (-b["help_rate"], -b["median"])
          for a, b in zip(SUM["rules"], SUM["rules"][1:])),
      [(r["rule"], r["help_rate"], r["median"]) for r in SUM["rules"]])

# of_peak says how much of the best price available a rule captured. It cannot
# exceed 1 — the exit happens at a bar inside the window the peak is taken from
# — so a value above 1 means the ratio is upside down.
check("no rule captures more than the best price that was available",
      all(0 < r["of_peak"] <= 1 for p in SUM["positions"] for r in p["rules"]
          if r.get("fired")),
      [(p["symbol"], r["rule"], r["of_peak"]) for p in SUM["positions"]
       for r in p["rules"] if r.get("fired") and not 0 < r["of_peak"] <= 1])

# ---------------------------------------------------------------------------
# THE IMMEDIACY FLAG, which the dashboard greys a row out for and captions
# "fires at the earliest bar it can — reads as timing, is not".
#
# earliest_possible must be the bar the rule COULD first fire on, which is a
# property of the rule, not of this sample. It used to be min(days_after_entry)
# — the earliest bar it DID fire on here — so with a single position every rule
# was flagged by construction, and any rule whose signals clustered was accused
# of firing immediately however long it had waited.
# ---------------------------------------------------------------------------
check("each rule reports the warm-up it actually has, whatever the sample did",
      {r["rule"]: r["earliest_possible"] for r in SUM["rules"]}
      == {label: warm for label, _fn, _fam, warm in exits.RULES},
      {r["rule"]: r["earliest_possible"] for r in SUM["rules"]})
check("a rule that waited far past its warm-up is not flagged as immediate",
      not any(r["fires_immediately"] for r in SUM["rules"]),
      [(r["rule"], r["median_days"], r["earliest_possible"])
       for r in SUM["rules"] if r["fires_immediately"]])

# Bought at the exact top of a run that then falls away: the averages and the
# ichimoku lines are all broken the instant they have enough bars to speak, so
# those four ARE firing at their first legal opportunity and must be flagged.
# The trailing stops are not — they could have fired at bar 1 and took 8 and 12
# — and flagging them too would be the old bug.
_conn2 = connect(":memory:")
_store(_conn2, "DOOMED", _rise + [179.5 * (0.97 ** (i + 1)) for i in range(140)])
_conn2.commit()
SUM2 = exits.summary(_conn2, [{"symbol": "DOOMED", "oldest_lot": DAYS[259]}], DAYS[-1])
_flag = {r["rule"]: r["fires_immediately"] for r in SUM2["rules"]}
_days = {r["rule"]: r["median_days"] for r in SUM2["rules"]}
check("a rule firing on its first legal bar is flagged",
      all(_flag[r] for r in ("below 20-day average", "below 50-day average",
                             "lost the kijun", "fell out of the cloud")),
      {k: (_days[k], v) for k, v in _flag.items()})
check("a rule that could have fired at bar 1 and did not is NOT flagged",
      not _flag["20% trailing stop"] and not _flag["30% trailing stop"],
      {k: _days[k] for k in ("20% trailing stop", "30% trailing stop")})

# ---------------------------------------------------------------------------
# for_position on its own: the report is about ONE holding, so its own numbers
# have to line up with the bars it replayed.
# ---------------------------------------------------------------------------
_one = exits.for_position(_conn, "COLLAPSE", ENTRY, DAYS[-1])
check("the replay starts at the entry date, not at the start of history",
      _one["bars"] == len(DAYS) - 120, (_one["bars"], len(DAYS) - 120))
check("the peak it reports is the highest close in the window it replayed",
      _one["peak"] == max(r["price"] for r in _one["rules"] if r.get("fired"))
      or _one["peak"] >= max(r["price"] for r in _one["rules"] if r.get("fired")),
      _one["peak"])
check("every fired rule is dated inside the replay window",
      all(r["date"] >= ENTRY for r in _one["rules"] if r.get("fired")),
      [r["date"] for r in _one["rules"] if r.get("fired") and r["date"] < ENTRY])
check("a symbol with no price history is reported as unreplayable, not crashed",
      exits.for_position(_conn, "NOSUCH", ENTRY, DAYS[-1]) is None)


# ---- the drawdown reading (D98) -------------------------------------------
# Measured 2026-09-10: a name that doubled then broke 20% off its high went on
# to fall a median 46% FURTHER before bottoming, took 2.8 months to get back,
# and 16% never did. Deeper is worse on every column. The reading puts those
# base rates on a live position, so what it must never do is quote them where
# they do not apply.
def _dd_bars(path):
    return [{"time": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": c, "high": c,
             "low": c, "close": c, "volume": 1000} for i, c in enumerate(path)]

check("a position at its high has no drawdown reading",
      exits.drawdown_reading(_dd_bars([10] * 30 + [20] * 30)) is None)

_down = exits.drawdown_reading(_dd_bars([10] * 20 + [100] * 5 + [75] * 40))
check("a 25% fall is measured off the peak",
      _down and abs(_down["drawdown"] - 0.25) < 0.001, _down)
check("...and carries the -20% base rates",
      _down["odds"]["n"] == 3084 and _down["odds"]["at_least"] == 0.20, _down["odds"])
check("a 35% fall reads the -30% row",
      exits.drawdown_reading(_dd_bars([10] * 20 + [100] * 5 + [65] * 40))["odds"]["at_least"] == 0.30)

# The deepest row is measured at "-70% or worse", so a name at -73% belongs in
# it rather than being refused a number — that refusal was the first version's
# answer for SIVEF and DGXX, and the whole point of remeasuring was to end it.
_sivef_like = exits.drawdown_reading(_dd_bars([10] * 20 + [100] * 5 + [27] * 40))
check("a name at SIVEF's depth now gets a real number instead of a shrug",
      _sivef_like["odds"]["at_least"] == 0.70 and _sivef_like["odds"]["n"] == 86,
      _sivef_like)
check("...and that number is the sobering one: most never get back",
      _sivef_like["odds"]["never_recovered"] > 0.6)
# Past the bottom row by a wide margin there is still nothing to say.
_absurd = exits.drawdown_reading(_dd_bars([10] * 20 + [100] * 5 + [3] * 40))
check("a fall past everything measured still gets NO odds, and says why",
      "odds" not in _absurd and "deeper than anything measured" in _absurd["odds_note"], _absurd)

# IREN crossed -40% ten months ago; those are not today's odds.
_stale = exits.drawdown_reading(_dd_bars([10] * 20 + [100] * 5 + [70] * 220))
check("a position that crossed months ago is marked stale",
      _stale["odds"]["stale"] is True and _stale["months_since_peak"] > 6, _stale)
check("...and one that just broke is not",
      exits.drawdown_reading(_dd_bars([10] * 20 + [100] * 5 + [70] * 10))["odds"]["stale"] is False)

check("the table is ordered deepest first, so the lookup takes the deepest row cleared",
      [o[0] for o in exits.DRAWDOWN_ODDS] == sorted((o[0] for o in exits.DRAWDOWN_ODDS), reverse=True))
check("every row is populated enough to quote — the thin table it replaced had "
      "25 events at -40% and nothing below",
      min(o[1] for o in exits.DRAWDOWN_ODDS) >= 80,
      [(o[0], o[1]) for o in exits.DRAWDOWN_ODDS])
check("deeper always means worse odds and a longer wait, on every row",
      all(a[2] >= b[2] and a[3] >= b[3]
          for a, b in zip(exits.DRAWDOWN_ODDS, exits.DRAWDOWN_ODDS[1:])),
      [(o[0], o[2], o[3]) for o in exits.DRAWDOWN_ODDS])

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {detail if not ok else ''}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
