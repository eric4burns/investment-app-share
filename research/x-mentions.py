"""Turn the raw X pulls into mention counts, so the app can say "are we early?".

    python3 research/x-mentions.py                       # every pull on disk
    python3 research/x-mentions.py research/x/pulls/2026-09-05.json

The pulls are what `research/x_pull.js` leaves behind: {tweets: {handle: [{id,
date, text}]}}. `seed-x-calls.py` reads the HAND-REVIEWED calls beside them —
a judgement about what somebody claimed. This reads the raw posts instead and
only counts cashtags, which needs no judgement and answers a different
question: how many of the followed accounts have started talking about a name.

Idempotent on the tweet id, so re-running over the same pulls adds nothing.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import authors, ledger  # noqa: E402


def iso_date(raw: str) -> str:
    """X writes 'Fri Sep 04 20:27:53 +0000 2026'; the ledger wants 2026-09-04.

    Both forms are accepted because a pull edited by hand, or a future pull that
    normalises its own dates, would otherwise be silently dropped. Silently is
    the operative word: the first run of this stored 251 mentions whose date
    read 'Fri Sep 04' after a naive [:10] slice, so every comparison against an
    ISO window matched nothing and every name looked untouched — including IREN,
    which five accounts had posted about that day.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    try:
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").date().isoformat()
    except ValueError:
        return ""


def rows_from(path: Path) -> list[dict]:
    d = json.loads(path.read_text())
    out = []
    for handle, tweets in (d.get("tweets") or {}).items():
        for t in tweets or []:
            # A pull that lost the per-tweet date falls back to the pull's own
            # `since`: better a date that is at worst a week early than to drop
            # the post, because the count is what matters and the window is
            # thirty days.
            when = iso_date(t.get("date")) or iso_date(d.get("since") or "")
            if not when:
                continue
            for sym in authors.mentions_in(t.get("text") or ""):
                out.append({"handle": handle, "symbol": sym, "date": when,
                            "tweet_id": t.get("id") or f"{handle}:{when}:{sym}"})
    return out


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    paths = ([Path(a) for a in argv] if argv
             else sorted(Path("research/x/pulls").glob("*.json")))
    if not paths:
        print("no pulls found under research/x/pulls/")
        return 1
    conn = ledger.connect()
    total = 0
    for p in paths:
        rows = rows_from(p)
        n = authors.store_mentions(conn, rows)
        total += n
        syms = len({r["symbol"] for r in rows})
        print(f"  {p.name}: {len(rows)} mentions of {syms} symbols, {n} new")
    print(f"{total} new mentions stored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
