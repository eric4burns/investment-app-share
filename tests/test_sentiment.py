"""Market fear and greed, and the restraint built into how it is used.

A market-wide number is the easiest kind to misuse: it says the same thing
about every holding, so wiring it in naively shifts the whole book at once and
makes itself unmeasurable at the same time. Most of these tests are about the
limits rather than the arithmetic.

Nothing here touches the network. The fetch is stubbed, because a test that
depends on CNN being up is a test that fails for reasons that have nothing to
do with this code.
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import sentiment as S

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    S.ensure_schema(conn)
    return conn


TODAY = date.today().isoformat()


def ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


# ----------------------------------------------------------- thresholds ----
# CNN's own bands. The labels matter less than the fact that `stance` is None
# across the whole middle, which is what keeps this out of most verdicts.
for score, want in ((0, "extreme fear"), (25, "extreme fear"), (26, "fear"),
                    (50, "neutral"), (60, "greed"), (75, "extreme greed"),
                    (100, "extreme greed")):
    check(f"{score} reads as {want}", S.label(score) == want, S.label(score))

check("extreme fear argues for buying", S.stance(20) == "bull")
check("extreme greed argues for taking something off", S.stance(80) == "extended")
for mid in (26, 40, 50, 60, 74):
    check(f"{mid} argues nothing either way", S.stance(mid) is None, S.stance(mid))

# The whole design rests on this: a condition present on EVERY call has no
# "without" bucket, so calibration.by_condition can never measure it. Firing
# only at the extremes is what keeps it attributable.
check("a mid-range reading carries no weight in any verdict",
      S.evidence({"score": 50, "rating": "neutral", "stance": None,
                  "previous": 48})["weight"] == 0.0)
check("an extreme reading carries weight, but less than a structural condition",
      S.evidence({"score": 10, "rating": "extreme fear", "stance": "bull",
                  "previous": 12})["weight"] == 1.0,
      "1.0 against 1.5 for pivots, the cloud and a level price is standing on")
check("the evidence names the number that produced it",
      "10" in S.evidence({"score": 10, "rating": "extreme fear",
                          "stance": "bull", "previous": 12})["detail"])
check("...and says it is market-wide rather than about this holding",
      "market-wide" in S.evidence({"score": 10, "rating": "extreme fear",
                                   "stance": "bull", "previous": 12})["detail"])
check("no reading at all produces no evidence", S.evidence(None) is None)

# ---------------------------------------------------------------- cache ----
_stub = {"ok": True, "score": 31.26, "rating": "fear", "as_of": TODAY,
         "previous_close": 44.57,
         "history": [{"date": ago(3), "score": 55.4},
                     {"date": ago(2), "score": 52.31},
                     {"date": ago(1), "score": 47.51},
                     # CNN timestamps the LIVE point in UTC, which lands on the
                     # previous calendar day often enough that it was
                     # overwriting yesterday's close with today's score — so
                     # "previous" came back equal to "now" and the day-over-day
                     # move read as zero every time.
                     {"date": TODAY, "score": 31.26}]}

conn = db()
_real, S.fetch = S.fetch, lambda timeout=20: dict(_stub)
try:
    res = S.sync(conn)
    check("a sync caches the history as well as today", res["ok"] and res["cached"] >= 4,
          str(res))
    _y = conn.execute("SELECT score FROM sentiment WHERE as_of=?", (ago(1),)).fetchone()
    check("the live reading does not overwrite yesterday's close",
          _y and abs(_y["score"] - 47.51) < 0.01,
          f"yesterday is {_y['score'] if _y else None}, not today's 31.26")

    now = S.latest(conn)
    check("the latest reading is today's", now["as_of"] == TODAY and now["score"] == 31.26)
    check("previous comes from CNN's own figure, not the cached series",
          now["previous"] == 44.57,
          "the two disagree, and CNN quotes the score against its own")
    check("a mid-range reading is not flagged extreme", now["extreme"] is False)

    # Sentiment from a fortnight ago describes a market that has since moved,
    # and shown beside today's price it would be read as today's.
    stale = S.latest(conn, asof=(date.today() + timedelta(days=30)).isoformat())
    check("a stale reading is refused rather than shown as current",
          stale and stale.get("stale") is True and "score" not in stale, stale)
    check("...but says when it was last fetched and how old that is",
          stale and stale.get("as_of") == TODAY and stale.get("age_days") == 30, stale)
    check("a stale reading carries no weight in any verdict", S.evidence(stale) is None)
    check("a current reading still does", S.evidence(S.latest(conn)) is not None)
    check("...and the age is reported while it is still usable",
          S.latest(conn)["age_days"] == 0)
    check("an empty cache returns nothing rather than a zero", S.latest(db()) is None)

    # Re-running the nightly job must not double anything.
    before = conn.execute("SELECT COUNT(*) n FROM sentiment").fetchone()["n"]
    S.sync(conn)
    after = conn.execute("SELECT COUNT(*) n FROM sentiment").fetchone()["n"]
    check("re-running the sync does not duplicate rows", before == after,
          f"{before} then {after}")

    # A failed fetch must not leave a half-written or a fabricated reading.
    S.fetch = lambda timeout=20: (_ for _ in ()).throw(OSError("network down"))
    bad = S.sync(db())
    check("a failed fetch is reported, not swallowed",
          bad["ok"] is False and "network" in bad["error"].lower(), str(bad))
finally:
    S.fetch = _real

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
