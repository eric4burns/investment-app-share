"""Split the pulled Substack posts into per-ticker blocks and pull out the
dated, priced claims each one makes.

Input is research/substack/<author>/*.txt (local only, never committed). Output
is a list of dicts — one per ticker block — with the date, symbol, timeframe,
the block text, every dollar figure or range in it, and a coarse reading of
what the block is claiming, taken from the author's own recurring phrases:

    buy    "Smart Money buy zone", "accumulate", "I'd be a buyer", "DCA"
    sell   "take profits", "trim", "sell", "profit-taking"
    bear   "breakdown", "measured downside target", "bearish", "below the cloud"
    bull   "bull trigger", "reclaim", "measured upside target", "breakout"
    -      nothing recognisable

The reading is a starting point for a person, not a verdict; the journal
seeding downstream only uses the unambiguous ones.

    python3 research/substack_extract.py            # summary
    python3 research/substack_extract.py --csv out.csv
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "substack" / "StonkChris"

# The timeframe list is what SPLITS one name's block from the next, so a
# timeframe missing from it silently merges two names. "SPCX (2H)" was not
# recognised, so SpaceX's text — and its $164-$173 levels — were attributed to
# SATL, a $5 stock. Any number-plus-letter in brackets counts now; the
# alternation was a whitelist doing a job a shape check does better.
HDR = re.compile(r'^\$?([A-Z]{1,6})(?:\.[A-Z])?\s*\((\d{1,2}[A-Za-z]{1,3})\)\s*(?:\*+)?\s*$', re.M)
# The K/M suffix must not be the first letter of the NEXT WORD. Without the
# lookahead this read "~$390 marked as my ideal pullback target" as $390
# MILLION — it took the m from "marked" — and stored a GLD target of
# 390,000,000 against a $400 share price. "$135 minimum", "$52 more" and
# "$46 max" all fail the same way; "$3K+" and "$1.5M float" must still work.
PRICE = re.compile(r'\$\s?(\d[\d,]*(?:\.\d+)?)(?:\s?([KkMm])(?![A-Za-z]))?'
                   r'(?:\s?[–-]\s?\$?\s?(\d[\d,]*(?:\.\d+)?)(?:\s?([KkMm])(?![A-Za-z]))?)?')
CUES = [
    ("buy",  re.compile(r"smart money buy|buy zone|accumulat|i'?d be a buyer|be a buyer|dca|optimal entry|entry zone|re-?buy|added|adding|i bought|started a position|nibbl", re.I)),
    ("sell", re.compile(r"take profit|taking profit|profit[- ]taking|trim|sell it all|sold|selling into|lock in|harvest", re.I)),
    ("bear", re.compile(r"breakdown|measured downside|downside target|bearish|below the (daily|weekly) cloud|looks like death|lower low|rejected|rejection|fail(s|ed)? to (hold|reclaim)|lose[s]? the", re.I)),
    ("bull", re.compile(r"bull trigger|reclaim|measured upside|upside target|breakout|break above|higher low|above the (daily|weekly) cloud|bullish|new highs|ath", re.I)),
]


def _num(s: str, suffix: str | None) -> float:
    v = float(s.replace(",", ""))
    if suffix and suffix.lower() == "k":
        v *= 1000
    if suffix and suffix.lower() == "m":
        v *= 1_000_000
    return v


def blocks(author_dir: Path = ROOT) -> list[dict]:
    out = []
    for f in sorted(author_dir.glob("*.txt")):
        text = f.read_text()
        date = f.name[:10]
        title = text.splitlines()[0].lstrip("# ").strip()
        heads = list(HDR.finditer(text))
        for i, h in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            body = text[h.end():end]
            body = re.sub(r"\[image: [^\]]*\]", "", body).strip()
            prices = []
            for m in PRICE.finditer(body):
                lo = _num(m.group(1), m.group(2))
                hi = _num(m.group(3), m.group(4)) if m.group(3) else None
                prices.append((lo, hi))
            cues = [name for name, rx in CUES if rx.search(body)]
            out.append({"date": date, "post": f.stem, "title": title, "symbol": h.group(1),
                        "tf": h.group(2), "text": body, "prices": prices, "cues": cues})
    return out


def main() -> int:
    bs = blocks()
    print(f"{len(bs)} ticker blocks")
    print("cues:", Counter(tuple(b["cues"]) for b in bs).most_common(12))
    print("with a price:", sum(1 for b in bs if b["prices"]))
    print("with a range:", sum(1 for b in bs if any(hi for _lo, hi in b["prices"])))
    print("symbols:", len({b["symbol"] for b in bs}))
    if "--csv" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--csv") + 1])
        with out.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "symbol", "tf", "cues", "prices", "post", "text"])
            for b in bs:
                w.writerow([b["date"], b["symbol"], b["tf"], "+".join(b["cues"]),
                            ";".join(f"{lo:g}" + (f"-{hi:g}" if hi else "") for lo, hi in b["prices"]),
                            b["post"], b["text"].replace("\n", " ")])
        print("wrote", out)
    return 0



# ---- priced levels ----------------------------------------------------------
# Nearly every block names a level with a role: somewhere he would buy, or
# somewhere he expects price to go. Those are checkable without deciding what
# the block "means" as a whole, so they are pulled out sentence by sentence.
SENT = re.compile(r"(?<=[.!?])\s+|\n+")
BUY_ZONE = re.compile(r"buy zone|buy-zone|dip[- ]buy|accumulat|entry zone|entry area|entry point|optimal entry|be a buyer|buying opportunit|rebuy|re-buy|reload|must hold|attractive (buying|entry|area|zone)|support zone|find support|support (?:around|near|at)", re.I)
TARGET = re.compile(r"\bpt\b|price target|upside target|target zone|targeting|\btarget\b|next leg|measured (upside|move)|back toward|move toward|headed toward|room to|extension", re.I)
DOWNSIDE = re.compile(r"downside target|breakdown target|measured downside|lower toward|one final (leg|unravel)|washout|retest of the (range |local )?lows", re.I)


def levels(bs: list[dict] | None = None) -> list[dict]:
    """(date, symbol, tf, kind, lo, hi, sentence) for every priced sentence.

    kind is 'buy' for a zone he says he would buy, 'target' for an upside
    objective, 'downside' for a measured downside zone (which is a buy zone
    he has not committed to yet, and a claim price is going lower first)."""
    bs = bs if bs is not None else blocks()
    out = []
    for b in bs:
        prev_kind = None
        for s in SENT.split(b["text"]):
            s = s.strip()
            ms = list(PRICE.finditer(s))
            down, buy, tgt = DOWNSIDE.search(s), BUY_ZONE.search(s), TARGET.search(s)
            if not ms:
                # A sentence that names the zone without a price ("...the next
                # Smart Money buy zone") is followed by one that gives the price
                # ("I have that area around $44–$47"). Carry the cue forward.
                prev_kind = "downside" if down else "buy" if buy and not tgt else "target" if tgt and not buy else None
                continue
            if not (down or buy or tgt) and prev_kind and re.search(r"\b(that|this|the) (area|zone|level|range)\b", s, re.I):
                if prev_kind == "downside":
                    down = True
                elif prev_kind == "buy":
                    buy = True
                else:
                    tgt = True
            prev_kind = None
            if down:
                kind = "downside"            # "measured downside target zone" is a downside zone, not a target
            elif buy and not tgt:
                kind = "buy"
            elif tgt and not buy:
                kind = "target"
            elif buy and tgt:
                kind = "mixed"
            else:
                kind = "level"
            for m in ms:
                lo = _num(m.group(1), m.group(2))
                hi = _num(m.group(3), m.group(4)) if m.group(3) else None
                out.append({"date": b["date"], "symbol": b["symbol"], "tf": b["tf"], "kind": kind,
                            "lo": lo, "hi": hi, "sentence": s, "post": b["post"]})
    return out


def main_levels() -> int:
    ls = levels()
    print(len(ls), "priced sentences;", Counter(l["kind"] for l in ls))
    import random
    random.seed(7)
    for kind in ("buy", "target", "downside", "mixed", "level"):
        print(f"\n### {kind}")
        for l in random.sample([x for x in ls if x["kind"] == kind], 5):
            print(f"{l['date']} {l['symbol']} {l['tf']} {l['lo']:g}{'-'+format(l['hi'],'g') if l['hi'] else ''} :: {l['sentence'][:220]}")
    return 0


if __name__ == "__main__":
    sys.exit(main_levels() if "--levels" in sys.argv else main())
