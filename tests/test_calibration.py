"""Does the calibration tool find what is actually in the data?

Nothing real is gradeable for weeks after the first verdict is recorded, so the
only way to know this tool works is to feed it outcomes that were constructed
with a known answer and check it reports that answer.

Most of these are about restraint. A tool whose job is to say "change this rule"
does damage when it says so on four days of correlated data, and the failure
mode is not a crash — it is a confident, wrong recommendation.
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import calibration as C, journal as J

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).resolve().parent.parent
                        / "app" / "schema.sql").read_text())
    J.ensure_schema(conn)
    return conn


def prices_for(conn, sym, start, days, first, step):
    sid = conn.execute("INSERT INTO securities (symbol, kind) VALUES (?, 'equity')",
                       (sym,)).lastrowid
    d0 = date.fromisoformat(start)
    for i in range(days):
        c = first + step * i
        conn.execute("""INSERT INTO prices (security_id, bar_date, close, open,
                                            high, low, volume, source)
                        VALUES (?,?,?,?,?,?,0,'test')""",
                     ((sid), (d0 + timedelta(days=i)).isoformat(), c, c, c, c))


START = (date.today() - timedelta(days=260)).isoformat()


def seeded(n_days=30, per_day=4):
    """Calls where WINNER always precedes outperformance and LOSER never does.

    SPY is flat; half the symbols rise and half fall, so the sign of every score
    is known before the tool is asked for it.

    Each call of a day gets its OWN symbol. An earlier version reused two
    symbols and lost most of the rows without saying so: app verdicts are unique
    per (date, symbol, timeframe) by design, so writing four calls a day across
    two symbols silently stores two. The fixture has to respect the schema it is
    testing against.
    """
    conn = db()
    prices_for(conn, "SPY", START, 260, 100.0, 0.0)
    for k in range(per_day):
        prices_for(conn, f"S{k}", START, 260, 100.0, 0.5 if k % 2 == 0 else -0.2)
    d0 = date.fromisoformat(START)
    for i in range(n_days):
        when = (d0 + timedelta(days=i)).isoformat()
        for k in range(per_day):
            sym = f"S{k}"
            good = k % 2 == 0
            J.record(conn, when, sym, "app", "buy", timeframe="D",
                     confidence="high" if good else "low",
                     flip=1.0 if good else None,
                     evidence=[{"name": "WINNER" if good else "LOSER",
                                "stance": "bull", "weight": 1.0},
                               # Fires on everything, so it can have no edge.
                               {"name": "NOISE", "stance": None, "weight": 1.0}])
    conn.commit()
    return conn


conn = seeded()
rep = C.report(conn, 21)

check("the tool grades the seeded calls at all", rep["overall"]["n"] > 0,
      f"{rep['overall']['n']} calls")
check("it counts distinct days, not just calls",
      rep["overall"]["days"] == 30 and rep["overall"]["n"] == 120,
      f"{rep['overall']['n']} calls over {rep['overall']['days']} days")

conds = {(c["condition"], c["stance"]): c for c in rep["by_condition"]["conditions"]}
check("a condition that precedes outperformance shows a positive edge",
      conds[("WINNER", "bull")]["edge"] > 0, str(conds[("WINNER", "bull")]["edge"]))
check("a condition that precedes underperformance shows a negative edge",
      conds[("LOSER", "bull")]["edge"] < 0, str(conds[("LOSER", "bull")]["edge"]))
check("a condition present on every call has no edge to report",
      conds[("NOISE", None)]["edge"] in (None, 0.0)
      or abs(conds[("NOISE", None)]["edge"]) < 1e-9,
      f"edge {conds[('NOISE', None)]['edge']} — it never distinguishes anything")
check("the best condition is ranked first",
      rep["by_condition"]["conditions"][0]["condition"] == "WINNER")

# The edge is a difference between two buckets, so the comparison bucket has to
# be the calls that did NOT carry the condition. Comparing against every call
# including its own leaves an edge that is merely diluted, never wrong-signed,
# and the seeded answer would still come out with the right sign.
_w = conds[("WINNER", "bull")]
check("a condition is compared against the calls that did not carry it",
      _w["with"]["n"] + _w["without"]["n"] == rep["overall"]["n"]
      and _w["without"]["n"] == 60,
      f"{_w['with']['n']} with, {_w['without']['n']} without, "
      f"{rep['overall']['n']} in total")

# The hit rate is reported beside the mean score and is a different measurement:
# a bucket can be right most of the time and still lose money on average. The
# seed makes both knowable exactly.
check("the hit rate counts the calls that were right, not all of them",
      rep["overall"]["hit_rate"] == 0.5,
      f"{rep['overall']['hit_rate']} — half the seeded symbols rise, half fall")
check("a condition that never fails reports a perfect hit rate",
      _w["with"]["hit_rate"] == 1.0 and _w["without"]["hit_rate"] == 0.0,
      f"{_w['with']['hit_rate']} with, {_w['without']['hit_rate']} without")

# Stance is part of a condition's identity. "Ichimoku bull" and "ichimoku bear"
# are opposite readings of the same indicator, and averaging them together
# would report the indicator as having no edge whichever way it fired.
mix = db()
prices_for(mix, "SPY", START, 260, 100.0, 0.0)
prices_for(mix, "MUP", START, 260, 100.0, 0.5)
prices_for(mix, "MDN", START, 260, 100.0, -0.2)
_m0 = date.fromisoformat(START)
for i in range(30):
    when = (_m0 + timedelta(days=i)).isoformat()
    for sym in ("MUP", "MDN"):
        J.record(mix, when, sym, "app", "buy", timeframe="D",
                 evidence=[{"name": "ich", "stance":
                            "bull" if sym == "MUP" else "bear", "weight": 1.0}])
mix.commit()
_mc = {(c["condition"], c["stance"]): c
       for c in C.by_condition(mix, 21)["conditions"]}
check("one condition read two ways is two rows, not one",
      {("ich", "bull"), ("ich", "bear")} <= set(_mc), str(sorted(_mc)))
check("...and the two stances carry opposite edges",
      _mc[("ich", "bull")]["edge"] > 0 > _mc[("ich", "bear")]["edge"],
      f"bull {_mc[('ich', 'bull')]['edge']}, bear {_mc[('ich', 'bear')]['edge']}")
check("a row counts only the calls that carried that STANCE of the condition",
      all(_mc[(n, s)]["with"]["n"] == 30 and _mc[(n, s)]["without"]["n"] == 30
          for n, s in (("ich", "bull"), ("ich", "bear"))),
      str({k: (v["with"]["n"], v["without"]["n"]) for k, v in _mc.items()}))

# Confidence: the seed makes 'high' genuinely better, so it must say so.
check("correctly-ordered confidence is reported as ordered",
      rep["by_confidence"]["ordered"] is True, rep["by_confidence"]["finding"][:70])

# ...and the inverse must be caught, which is the whole point of the slice.
inv = db()
prices_for(inv, "SPY", START, 260, 100.0, 0.0)
prices_for(inv, "UP", START, 260, 100.0, 0.5)
prices_for(inv, "DOWN", START, 260, 100.0, -0.2)
_d0 = date.fromisoformat(START)
for i in range(30):
    when = (_d0 + timedelta(days=i)).isoformat()
    for k in range(3):
        sym = "UP" if k % 2 == 0 else "DOWN"
        # Labels deliberately backwards: the winners are called low confidence.
        J.record(inv, when, sym, "app", "buy", timeframe="D",
                 confidence="low" if sym == "UP" else "high",
                 evidence=[{"name": "X", "stance": "bull", "weight": 1.0}])
inv.commit()
check("mislabelled confidence is caught and named as the thing to fix",
      C.by_confidence(inv, 21)["ordered"] is False
      and "first thing to fix" in C.by_confidence(inv, 21)["finding"],
      C.by_confidence(inv, 21)["finding"][:70])

# One bucket cannot be out of order with itself. Ranking a single level and
# calling it "ordered correctly" would announce that the label is carrying
# information on the strength of never having compared it to anything.
one_level = db()
prices_for(one_level, "SPY", START, 260, 100.0, 0.0)
prices_for(one_level, "OL", START, 260, 100.0, 0.4)
_o0 = date.fromisoformat(START)
for i in range(30):
    J.record(one_level, (_o0 + timedelta(days=i)).isoformat(), "OL", "app", "buy",
             timeframe="D", confidence="high",
             evidence=[{"name": "x", "stance": "bull", "weight": 1.0}])
one_level.commit()
_ol = C.by_confidence(one_level, 21)
check("a single confidence level is not declared correctly ordered",
      _ol["ordered"] is None and "at least two confidence levels" in _ol["finding"],
      f"{_ol['ordered']} — {_ol['finding'][:60]}")

# A bucket below the floors is shown but must not be RANKED. Three calls
# labelled medium are not evidence that medium sits where it should, and letting
# them into the ordering is how a thin bucket flips the whole finding.
thin_mid = db()
prices_for(thin_mid, "SPY", START, 260, 100.0, 0.0)
prices_for(thin_mid, "TH", START, 260, 100.0, 0.4)
prices_for(thin_mid, "TL", START, 260, 100.0, -0.3)
_h0 = date.fromisoformat(START)
for i in range(30):
    when = (_h0 + timedelta(days=i)).isoformat()
    J.record(thin_mid, when, "TH", "app", "buy", timeframe="D", confidence="high",
             evidence=[{"name": "x", "stance": "bull", "weight": 1.0}])
    J.record(thin_mid, when, "TL", "app", "buy", timeframe="D", confidence="low",
             evidence=[{"name": "x", "stance": "bull", "weight": 1.0}])
# ...and a handful of "medium" calls that would, if ranked, sit above "high".
prices_for(thin_mid, "TM", START, 260, 100.0, 2.0)
for i in range(3):
    J.record(thin_mid, (_h0 + timedelta(days=i)).isoformat(), "TM", "app", "buy",
             timeframe="D", confidence="medium",
             evidence=[{"name": "x", "stance": "bull", "weight": 1.0}])
thin_mid.commit()
_tm = C.by_confidence(thin_mid, 21)
check("the thin bucket is under the floors and outscores the ones that are not",
      _tm["buckets"]["medium"]["enough"] is False
      and _tm["buckets"]["medium"]["mean_score"] > _tm["buckets"]["high"]["mean_score"],
      str({k: (b["n"], b["days"], b["mean_score"]) for k, b in _tm["buckets"].items()}))
check("a bucket below the floors is reported but never ranked",
      _tm["ordered"] is True and "medium" not in _tm["finding"],
      _tm["finding"][:80])

# --------------------------------------------------------------- flip -------
# A verdict that names an invalidation price is making a sharper claim than one
# that does not, so the calls carrying a level should do better. The seed makes
# that true by construction — every winner names one and no loser does.
fl = rep["flip_levels"]
check("naming a flip level is measured against not naming one",
      fl["with_flip"]["n"] == 60 and fl["without_flip"]["n"] == 60,
      f"{fl['with_flip']['n']} with, {fl['without_flip']['n']} without")
check("the sharper claim is measured as the better one here",
      fl["edge"] > 0, str(fl["edge"]))
check("the number reported is the GAP between the two, not one side's score",
      fl["edge"] > fl["with_flip"]["mean_score"] > 0
      and fl["without_flip"]["mean_score"] < 0,
      f"edge {fl['edge']} against {fl['with_flip']['mean_score']} / "
      f"{fl['without_flip']['mean_score']}")
check("...and the finding says by how much rather than just that it did",
      "points better" in fl["finding"], fl["finding"][:70])

# With every call naming a level there is nothing to compare against, and the
# report must abstain rather than quote an edge against an empty bucket.
check("with nothing on one side the flip comparison abstains",
      C.flip_levels(one_level, 21)["finding"] == "Not enough graded calls on both sides yet.",
      C.flip_levels(one_level, 21)["finding"][:60])

# ------------------------------------------------------------- restraint ----
# Many calls on few days is the shape this tool must refuse to speak about:
# sixteen holdings scored one evening is one observation, not sixteen.
few = seeded(n_days=3, per_day=12)
r2 = C.report(few, 21)
check("many calls over few days is refused",
      r2["overall"]["n"] >= C.MIN_CALLS and r2["overall"]["days"] < C.MIN_DAYS
      and r2["overall"]["enough"] is False,
      f"{r2['overall']['n']} calls but only {r2['overall']['days']} days")
check("...and the headline says so rather than quoting a hit rate",
      "Nothing is measurable yet" in r2["headline"], r2["headline"][:60])
check("no condition is called actionable on too few days",
      r2["best"] == [] and r2["worst"] == [])

# The mirror case: plenty of separate days, but barely any calls on them.
thin = seeded(n_days=12, per_day=1)
_rt = C.report(thin, 21)
check("few calls over many days is also refused",
      _rt["overall"]["days"] >= C.MIN_DAYS and _rt["overall"]["n"] < C.MIN_CALLS
      and _rt["overall"]["enough"] is False,
      f"{_rt['overall']['n']} calls over {_rt['overall']['days']} days")

check("an empty ledger reports nothing rather than dividing by zero",
      C.report(db(), 21)["overall"]["n"] == 0)

# --------------------------------------------------------------- source -----
# The CLI takes --source and the whole point of it is asking the same questions
# of your own trades. It was parsed and then never passed to report(), so
# `--source trade` silently produced the app's calibration — a flag that lies is
# worse than no flag, because the answer looks like the one that was asked for.
mine = seeded()
_m0 = date.fromisoformat(START)
for i in range(12):
    J.record(mine, (_m0 + timedelta(days=i)).isoformat(), "S0", "trade", "sell",
             evidence=[{"name": "MINE", "stance": "bear", "weight": 1.0}])
mine.commit()
_app, _trade = C.report(mine, 21), C.report(mine, 21, "trade")
check("a calibration on your own trades reads your rows, not the app's",
      _trade["overall"]["n"] == 12 and _app["overall"]["n"] == 120,
      f"trade {_trade['overall']['n']}, app {_app['overall']['n']}")
check("...and every slice of it follows the same source",
      list(_trade["by_action"]) == ["sell"] and list(_app["by_action"]) == ["buy"],
      f"{list(_trade['by_action'])} vs {list(_app['by_action'])}")
check("...including the condition attribution",
      {c["condition"] for c in _trade["by_condition"]["conditions"]} == {"MINE"},
      str([c["condition"] for c in _trade["by_condition"]["conditions"]]))
check("the multiple-comparisons problem is stated in the payload, not just in code",
      "by chance" in rep["by_condition"]["caveat"]
      and "one thing at a time" in rep["by_condition"]["caveat"],
      rep["by_condition"]["caveat"][:60])
check("the caveat counts the comparisons that were actually made",
      rep["by_condition"]["comparisons"] == len(rep["by_condition"]["conditions"])
      and str(rep["by_condition"]["comparisons"]) in rep["by_condition"]["caveat"],
      f"{rep['by_condition']['comparisons']} conditions")

# A call whose horizon has not elapsed has no outcome, and averaging it in as a
# zero would drag every bucket toward nothing while inflating the sample the
# floors are checked against. It must not appear at all.
young = seeded()
_ungraded = (date.today() - timedelta(days=2)).isoformat()
prices_for(young, "NEW", _ungraded, 3, 100.0, 0.0)
for k in range(4):
    J.record(young, _ungraded, "NEW", "app", "buy", timeframe=f"T{k}",
             evidence=[{"name": "WINNER", "stance": "bull", "weight": 1.0}])
young.commit()
check("a call whose horizon has not elapsed is not counted as graded",
      C.report(young, 21)["overall"]["n"] == rep["overall"]["n"],
      f"{C.report(young, 21)['overall']['n']} against {rep['overall']['n']}")

# --------------------------------------------------------------- storage ----
# The nightly job re-records the same day. Evidence must be replaced, or one
# call's conditions accumulate and count twice in every attribution.
one = db()
prices_for(one, "SPY", START, 260, 100.0, 0.0)
prices_for(one, "AAA", START, 260, 100.0, 0.3)
for _ in range(3):
    J.record(one, START, "AAA", "app", "buy", timeframe="D",
             evidence=[{"name": "ich", "stance": "bull", "weight": 1.0}])
one.commit()
rows = one.execute("SELECT COUNT(*) n FROM decision_evidence").fetchone()["n"]
check("re-running the nightly job does not duplicate a call's evidence",
      rows == 1, f"{rows} evidence rows after three identical records")

J.record(one, START, "AAA", "app", "sell", timeframe="D",
         evidence=[{"name": "cloud", "stance": "bear", "weight": 1.0}])
one.commit()
names = [r["name"] for r in one.execute("SELECT name FROM decision_evidence")]
check("a changed verdict replaces its evidence rather than adding to it",
      names == ["cloud"], str(names))


# ---- slices your own record has: by book and by what happened ----
_r = C.report(conn, 21, source="app")
check("the report carries by-book and by-tag slices, empty for the app's own calls",
      isinstance(_r.get("by_bucket"), dict) and isinstance(_r.get("by_tag"), dict), list(_r))

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
