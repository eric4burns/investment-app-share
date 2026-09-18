"""Tests for chart setups.

The risk with setups is attribution: a configuration labelled with someone's
name that they never described is misinformation wearing a citation. So the
tests are mostly about honesty — every setup must say how well sourced it is,
anything attributed to a person must either quote them or be flagged as
unconfirmed, and every indicator must actually exist.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import indicators as I, setups

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

VALID_CONFIDENCE = {"stated", "reported", "inferred", "proposed"}

check("there is at least one setup", len(setups.SETUPS) > 0)


# The honesty rule, as a function rather than four `if` branches inside the loop
# over real setups.
#
# It was written inline, and two of its four branches had never executed: no
# setup is `reported`, and both `proposed` ones are attributed to nobody, so
# `named and confidence == "proposed"` was unreachable. Three assertions about
# second-hand settings and unconfirmed periods sat in the file testing nothing,
# and a bug in any of them was invisible. Pulling the rule out means the real
# catalogue is still checked against it AND the rule itself is checked against
# constructed cases that hit every branch.
def honesty_faults(s: dict) -> list[str]:
    """What is missing before this setup may claim the confidence it claims."""
    out = []
    named = bool(s.get("attribution")) and not s["attribution"].lower().startswith("nobody")
    conf, source = s.get("confidence"), (s.get("source") or "").lower()
    if not named:
        return out
    # Anything claiming to be their own words must actually contain their words.
    if conf in {"stated", "inferred"} and len(s.get("quotes", [])) < 1:
        out.append("attributed to a person with no quote from them")
    # Settings that say plainly they were relayed cannot also claim to be the
    # person's own stated words. This is the distinction the whole field exists
    # to draw, and the difference between the two levels is only ever visible in
    # the source text.
    if conf == "stated" and any(w in source for w in ("relayed", "second-hand",
                                                      "not quoted")):
        out.append("source says the settings were relayed, which is 'reported'")
    # Second-hand settings must say they are second-hand and what is still open.
    if conf == "reported":
        if not any(w in source for w in ("relayed", "second-hand", "not quoted")):
            out.append("claims to be second-hand without saying so in its source")
        if len(s.get("needs", [])) < 1:
            out.append("second-hand with nothing listed as unconfirmed")
    # A default nobody has confirmed, but hung on a person's name, has to say in
    # its own source that it did not come from their material.
    if conf == "proposed":
        if len(s.get("needs", [])) < 1:
            out.append("proposed with nothing listed as unconfirmed")
        if not ("not" in source and "sourced" in source):
            out.append("proposed under a person's name without disowning the source")
    return out


# Every branch above, exercised on cases built for the purpose. Without these
# the rule is only as good as whatever happens to be in SETUPS today.
_ok_stated = {"attribution": "Someone (@someone)", "confidence": "stated",
              "source": "His video, quoted below.", "quotes": ["\"a quote\""]}
_ok_reported = {"attribution": "Someone (@someone)", "confidence": "reported",
                "source": "Settings relayed by a viewer of his video.",
                "needs": ["whether the period changes on a daily chart"]}
_ok_proposed = {"attribution": "Someone (@someone)", "confidence": "proposed",
                "source": "A sensible default, not sourced from his material.",
                "needs": ["confirmation that he uses anything like this"]}
check("a stated setup that quotes its source passes",
      honesty_faults(_ok_stated) == [], honesty_faults(_ok_stated))
check("a stated setup with no quote from the person is rejected",
      honesty_faults(dict(_ok_stated, quotes=[])), "attributed with no quote")
check("a setup whose source says the settings were relayed may not claim 'stated'",
      any("relayed" in f for f in honesty_faults(
          dict(_ok_stated, source="Settings relayed by the user from his video."))),
      honesty_faults(dict(_ok_stated, source="Settings relayed by the user.")))
check("a reported setup that says it is second-hand and lists gaps passes",
      honesty_faults(_ok_reported) == [], honesty_faults(_ok_reported))
check("a reported setup that never says it is second-hand is rejected",
      honesty_faults(dict(_ok_reported, source="From his video.")),
      honesty_faults(dict(_ok_reported, source="From his video.")))
check("a reported setup with nothing listed as unconfirmed is rejected",
      honesty_faults(dict(_ok_reported, needs=[])), "second-hand with no open questions")
check("a proposed setup under a person's name must disown their material",
      honesty_faults(dict(_ok_proposed, source="From his video.")),
      honesty_faults(dict(_ok_proposed, source="From his video.")))
check("a proposed setup attributed to nobody is exempt, since nobody is misquoted",
      honesty_faults({"attribution": "Nobody; public literature",
                      "confidence": "proposed", "source": "Conventional."}) == [])

# And the levels the real catalogue actually uses, so a level quietly falling out
# of use does not leave its rule untested here forever.
_levels_in_use = {s["confidence"] for s in setups.SETUPS.values()}
check("every confidence level in the catalogue is one the rule knows about",
      _levels_in_use <= VALID_CONFIDENCE, _levels_in_use)
check("the catalogue exercises more than one level, so the rule is not vacuous",
      len(_levels_in_use) >= 3, sorted(_levels_in_use))

for key, s in setups.SETUPS.items():
    check(f"{key} declares a confidence level",
          s.get("confidence") in VALID_CONFIDENCE, s.get("confidence"))
    check(f"{key} names a source", bool(s.get("source")))
    check(f"{key} names an attribution", bool(s.get("attribution")))
    check(f"{key} has a timeframe the app understands",
          s.get("timeframe") in {"D", "W", "M"}, s.get("timeframe"))
    check(f"{key} explains how to read it", len(s.get("reading", [])) >= 2)

    # Every indicator spec must parse and resolve to a real indicator.
    for spec in s["indicators"]:
        name, args = I.parse(spec)
        if name not in I.REGISTRY:
            check(f"{key} uses only registered indicators", False, spec)
            break
        entry = I.REGISTRY[name]
        if len(args) > len(entry["params"]):
            check(f"{key}: {spec} passes no more args than the indicator takes", False,
                  (len(args), len(entry["params"])))
            break
    else:
        check(f"{key} uses only registered indicators with valid arguments", True)

    # The honesty rule, applied to every setup. See `honesty_faults` below for
    # what it actually requires and why it lives in a function.
    faults = honesty_faults(s)
    check(f"{key} carries the evidence its confidence level claims",
          not faults, faults)

# The catalogue is what the UI renders from.
cat = setups.catalogue()
check("catalogue exposes every setup", len(cat) == len(setups.SETUPS))
check("catalogue entries carry their key", all("key" in c for c in cat))
check("lookup returns a known setup", setups.get("cantonese-cat-monthly") is not None)
check("lookup returns nothing for an unknown key", setups.get("nope") is None)

# A setup that offers to scan the watchlist has to point at a method that
# exists, and at one on its OWN timeframe. A monthly setup wired to a weekly
# scan would draw one chart and compute a different one, and the disagreement
# would look like a bug in the scanner rather than a broken link.
from app import methods as _methods                                # noqa: E402
_with_scan = {k: v for k, v in setups.SETUPS.items() if v.get("scan")}
check("at least one setup offers a scan, so these two checks are not vacuous",
      len(_with_scan) >= 1, list(_with_scan))
check("every setup's scan names a method that exists",
      all(v["scan"] in _methods.METHODS for v in _with_scan.values()),
      [(k, v["scan"]) for k, v in _with_scan.items()
       if v["scan"] not in _methods.METHODS])
check("a setup and the method it scans read the same timeframe",
      all(_methods.METHODS[v["scan"]]["timeframe"] == v["timeframe"]
          for v in _with_scan.values() if v["scan"] in _methods.METHODS),
      [(k, v["timeframe"], _methods.METHODS[v["scan"]]["timeframe"])
       for k, v in _with_scan.items() if v["scan"] in _methods.METHODS
       and _methods.METHODS[v["scan"]]["timeframe"] != v["timeframe"]])

# Applying a setup must produce a chart the indicator layer can actually
# compute. The old fixture repeated the same twelve timestamps twenty-five
# times, which is not a price series — and it only asserted that nothing
# errored, so a spec returning an EMPTY series (a 200-period average on too
# little history, say) drew nothing and still passed. 300 distinct sessions,
# and every line has to actually have points on it.
import math as _math                                               # noqa: E402
from datetime import date as _date, timedelta as _td               # noqa: E402
bars, _d = [], _date(2024, 1, 1)
while len(bars) < 300:
    if _d.weekday() < 5:
        _c = 100 + len(bars) * 0.2 + 5 * _math.sin(len(bars) / 7)
        bars.append({"time": _d.isoformat(), "open": round(_c, 4),
                     "high": round(_c * 1.02, 4), "low": round(_c * 0.98, 4),
                     "close": round(_c, 4), "volume": 1000 + len(bars)})
    _d += _td(days=1)


def _empty_parts(data):
    """Which lines of an indicator came back with nothing on them.

    Summing across a multi-line indicator hides the case that matters: an
    ichimoku whose senkou period is longer than the history draws its
    conversion and base lines perfectly and no cloud at all, and "reclaim the
    daily cloud" is the whole reason two of these setups load it.
    """
    if isinstance(data, dict):
        return [k for k, v in data.items() if not v]
    return [] if data else ["(series)"]


for key, s in setups.SETUPS.items():
    out = I.compute(bars, s["indicators"])
    check(f"{key} computes without error on real-shaped bars",
          all("error" not in v for v in out.values()),
          [k for k, v in out.items() if "error" in v])
    check(f"{key} draws an actual line for every indicator it asks for",
          set(out) == set(s["indicators"])
          and not any(_empty_parts(v["data"]) for v in out.values()),
          [(k, _empty_parts(v["data"])) for k, v in out.items()
           if _empty_parts(v["data"])] or sorted(set(s["indicators"]) - set(out)))

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
