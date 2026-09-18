"""CNN's Fear and Greed index: what the market as a whole is feeling.

## What it is

Seven indicators of market breadth, volatility, demand for safety and demand
for junk bonds, combined into one 0-100 score. Low is fear, high is greed, and
the contrarian reading — buy fear, trim greed — is the whole reason anybody
watches it.

## Why it is used sparingly here

It is a MARKET-WIDE number. It says the same thing about every holding on the
same day, which has two consequences that shape how this module is wired in.

The first is that it cannot discriminate. Adding it to every name's evidence
would shift the whole book in one direction at once and tell you nothing about
which of your holdings to act on — and `calibration.by_condition` would be
unable to measure it, because a condition present on every call has no
"without" bucket to compare against. That is not a hypothetical: the
calibration suite asserts exactly that property.

So it scores only at the EXTREMES. Between `FEAR` and `GREED` it is reported as
context and weighted zero, which keeps it absent from most calls and therefore
measurable when it does appear.

The second is that it is sentiment, not a forecast. Its record is genuinely
mixed — extreme fear has marked bottoms and has also marked the middle of
declines that kept going — so it is never allowed to produce a verdict on its
own. At best it adds weight to a case the chart is already making.

## The data

CNN publishes it at an undocumented endpoint, which is the same footing as the
OTC price data here: it works, it is not a supported API, and it can change
without notice. It returns 418 to a request that does not look like a browser.
Cached per day, because the index updates once a day.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# CNN answers 418 without these. Not evasion of a rate limit — the endpoint is
# meant for their own front end and refuses anything that does not look like it.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cnn.com/",
    "Origin": "https://www.cnn.com",
    "Accept-Language": "en-US,en;q=0.9",
}

# The thresholds at which this is allowed to carry weight. CNN's own labels put
# "extreme fear" under 25 and "extreme greed" over 75, and those are the only
# readings with a case worth acting on; the middle is noise dressed as a number.
FEAR, GREED = 25.0, 75.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentiment (
    as_of   TEXT NOT NULL,
    source  TEXT NOT NULL,
    score   REAL NOT NULL,
    rating  TEXT,
    previous REAL,
    fetched TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (as_of, source)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def fetch(timeout: int = 20) -> dict:
    req = urllib.request.Request(CNN_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read())
    now = raw.get("fear_and_greed") or {}
    if now.get("score") is None:
        return {"ok": False, "error": "no score in the response"}
    hist = [{"date": datetime.utcfromtimestamp(p["x"] / 1000).date().isoformat(),
             "score": round(float(p["y"]), 2)}
            for p in (raw.get("fear_and_greed_historical") or {}).get("data", [])
            if p.get("x") and p.get("y") is not None]
    return {
        "ok": True,
        "score": round(float(now["score"]), 2),
        "rating": now.get("rating"),
        "as_of": str(now.get("timestamp") or "")[:10] or date.today().isoformat(),
        "previous_close": now.get("previous_close"),
        "previous_1_week": now.get("previous_1_week"),
        "previous_1_month": now.get("previous_1_month"),
        "previous_1_year": now.get("previous_1_year"),
        "history": hist[-260:],
    }


def sync(conn) -> dict:
    """Fetch today's reading and cache it. Safe to call repeatedly."""
    ensure_schema(conn)
    try:
        got = fetch()
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not got.get("ok"):
        return got
    # History points dated on or after the live reading are the live value
    # again: CNN timestamps the current point in UTC, which lands on the
    # previous calendar day often enough that it was overwriting yesterday's
    # close with today's score — so "previous" came back equal to "now" and the
    # day-over-day move read as zero every time.
    rows = [(h["date"], "cnn", h["score"], None, None)
            for h in got["history"] if h["date"] < got["as_of"]]
    rows.append((got["as_of"], "cnn", got["score"], got["rating"],
                 got.get("previous_close")))
    conn.executemany("""INSERT INTO sentiment (as_of, source, score, rating, previous)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT (as_of, source) DO UPDATE SET
                          score=excluded.score,
                          rating=COALESCE(excluded.rating, sentiment.rating),
                          previous=COALESCE(excluded.previous, sentiment.previous)""", rows)
    conn.commit()
    return {"ok": True, "as_of": got["as_of"], "score": got["score"],
            "rating": got["rating"], "cached": len(rows)}


def latest(conn, asof: str | None = None, max_age_days: int = 5) -> dict | None:
    """The most recent cached reading; None if there is nothing at all.

    A stale reading is worse than none: sentiment from a fortnight ago describes
    a market that has since moved, and presenting it beside today's price would
    be read as today's. Anything older than `max_age_days` carries no score —
    but it is not returned as None either, because None also meant "never
    fetched", and the page said "unavailable" for a week while the nightly
    fetch was failing with nothing to say when it last worked. The stale
    marker names the date and the age; evidence() weighs it at nothing.
    """
    ensure_schema(conn)
    asof = asof or date.today().isoformat()
    row = conn.execute(
        """SELECT as_of, score, rating, previous FROM sentiment
            WHERE source='cnn' AND as_of <= ? ORDER BY as_of DESC LIMIT 1""",
        (asof,)).fetchone()
    if not row:
        return None
    age = (date.fromisoformat(asof) - date.fromisoformat(row["as_of"])).days
    if age > max_age_days:
        return {"stale": True, "as_of": row["as_of"], "age_days": age,
                "max_age_days": max_age_days}
    # CNN's own previous_close where we have it. Deriving it from the cached
    # series is a fallback, not the first choice — the two disagree, and the
    # figure CNN publishes beside the score is the one it is quoting against.
    prior = conn.execute(
        """SELECT score FROM sentiment WHERE source='cnn' AND as_of < ?
            ORDER BY as_of DESC LIMIT 1""", (row["as_of"],)).fetchone()
    previous = (round(float(row["previous"]), 2) if row["previous"] is not None
                else (prior["score"] if prior else None))
    month = conn.execute(
        """SELECT score FROM sentiment WHERE source='cnn' AND as_of <= ?
            ORDER BY as_of DESC LIMIT 1""",
        ((date.fromisoformat(row["as_of"]) - timedelta(days=30)).isoformat(),)).fetchone()
    return {"as_of": row["as_of"], "score": row["score"],
            "rating": row["rating"] or label(row["score"]),
            "age_days": age,
            "previous": previous,
            "month_ago": month["score"] if month else None,
            "stance": stance(row["score"]),
            "extreme": row["score"] <= FEAR or row["score"] >= GREED}


def label(score: float) -> str:
    if score <= FEAR:
        return "extreme fear"
    if score < 45:
        return "fear"
    if score <= 55:
        return "neutral"
    if score < GREED:
        return "greed"
    return "extreme greed"


def stance(score: float) -> str | None:
    """What this reading argues, and only at the extremes.

    Contrarian by construction: fear argues for buying, greed for taking
    something off. `None` in the middle, which is most of the time, and that is
    deliberate — see the module docstring on why a market-wide number that fires
    every day is one that can never be measured.
    """
    if score <= FEAR:
        return "bull"
    if score >= GREED:
        return "extended"
    return None


def evidence(reading: dict | None) -> dict | None:
    """The reading as one piece of verdict evidence, or nothing.

    A stale marker is nothing: a fortnight-old score must not weigh on
    today's call, and every caller (the nightly run, the page, the alerts)
    comes through here or checks for a score first.
    """
    if not reading or reading.get("stale") or reading.get("score") is None:
        return None
    s = reading["score"]
    st = reading["stance"]
    detail = (f"market fear and greed at {s:.0f} ({reading['rating']})"
              + (f", from {reading['previous']:.0f} yesterday"
                 if reading.get("previous") is not None else ""))
    if st == "bull":
        detail += " — a contrarian argument for buying, and a market-wide one"
    elif st == "extended":
        detail += " — a contrarian argument for taking something off"
    else:
        detail += " — mid-range, so it argues nothing either way"
    return {"name": "fear and greed", "stance": st,
            # One, against 1.5 for the structural conditions. It is market
            # sentiment, it says the same thing about every holding, and its
            # record at calling turns is genuinely mixed — so it may add to a
            # case the chart is making and must never make one by itself.
            "weight": 1.0 if st else 0.0,
            "detail": detail, "level": None}
