"""Which names a YouTube video talks about, and getting that into the ledger.

The X pull counts cashtags, because that is how people write on X. Video does
not work that way: across 26 transcripts already on disk there was not one
cashtag in spoken text, because nobody says "dollar sign P-L-T-R" out loud.
They say "Palantir".

So this matches company NAMES, and the whole difficulty is doing that without
filling the crowd reading with nonsense. Two failed attempts, kept here because
the failures are the reason for the rules:

* Matching the first word of every tradable company name against the
  transcript produced "where" -> WFCF, "three" -> TLACU and "hello" -> MOMO.
  The tradable universe is 13,000 names deep and its long tail is made of
  ordinary English words.
* Restricting that to the user's own 206 tracked symbols was nearly right, but
  skipping short leading words turned "Nu Holdings" into the alias "holdings",
  so every video that said the word matched NU.

What works is narrow and worth being honest about: the literal first word of
the name, at least four letters, not in the system dictionary, not a generic
corporate word, and unambiguous across the tracked set. That yields about a
hundred usable aliases from two hundred symbols — names like Apple, Target and
Block have no distinctive word at all and simply cannot be matched this way.

The consequence is that this confirms interest in names already tracked. It
does NOT discover new ones; cashtags in a title or description are the only
reliable channel for that, and they are read too.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DICT = Path("/usr/share/dict/words")

# handle -> the label used for mentions. The handle is deliberately the same
# string the X pull uses, so somebody posting on both platforms counts as ONE
# account in the crowd reading rather than two.
CHANNELS = {
    "cantonmeow": "https://www.youtube.com/@cantonmeow/videos",
    "TheRonnieVShow": "https://www.youtube.com/@TheRonnieVShow/videos",
    "RonnieVTrades": "https://www.youtube.com/@RonnieVTrades/videos",
    "thetechnicaltraders": "https://www.youtube.com/@thetechnicaltraders/videos",
    "nanalyze": "https://www.youtube.com/@nanalyze/videos",
    "VerifiedInvesting": "https://www.youtube.com/@VerifiedInvesting/videos",
    "JosephCarlsonShow": "https://www.youtube.com/@JosephCarlsonShow/videos",
}

# Words that name a corporate form rather than a company. None of these are in
# the system dictionary in plural form, so they have to be listed.
GENERIC = set("""holdings holding technologies technology group corporation incorporated
industries enterprises international global systems solutions services resources partners
capital financial energy mining digital networks pharmaceuticals therapeutics biosciences
sciences laboratories motors media entertainment communications semiconductor
semiconductors software hardware materials products brands companies acquisition
ventures securities investments management associates
inc corp co ltd plc sa nv ag llc lp class common stock shares ordinary etf trust
fund index the and for new""".split())

MIN_ALIAS = 4
# Where the tradable-asset list is cached. It is the same list research/video
# resolves tickers against; one copy, so the two cannot disagree.
ASSET_CACHE = ROOT / "data" / "alpaca-assets.json"
CASHTAG = re.compile(r"\$([A-Z][A-Z.\-]{0,5})\b")


def english_words() -> set[str]:
    if not DICT.exists():
        return set()
    return {w.strip().lower() for w in DICT.read_text(errors="ignore").splitlines()}


def asset_names(refresh: bool = False) -> dict[str, str]:
    """symbol -> company name for everything tradable, cached on disk.

    The ledger only knows the names of things the user has actually traded, so
    on its own it covers about a fifth of the watchlist. Alpaca's asset list is
    the same free endpoint app/discover.py already uses.
    """
    if ASSET_CACHE.exists() and not refresh:
        return json.loads(ASSET_CACHE.read_text())
    from . import discover
    names = {a["symbol"]: a.get("name") or "" for a in discover.assets() if a.get("name")}
    ASSET_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ASSET_CACHE.write_text(json.dumps(names))
    return names


def tracked_symbols(conn: sqlite3.Connection) -> set[str]:
    """What the user holds or watches — the set worth matching names against."""
    held = {r[0] for r in conn.execute(
        """SELECT s.symbol FROM transactions t JOIN securities s ON s.id = t.security_id
           GROUP BY s.symbol HAVING ABS(SUM(t.quantity)) > 0.001""")}
    return held | {r[0] for r in conn.execute("SELECT symbol FROM watchlist")}


def aliases(conn: sqlite3.Connection, extra_names: dict[str, str] | None = None) -> dict[str, str]:
    """word -> symbol, for words distinctive enough to be worth matching."""
    words = english_words()
    names = {s: n for s, n in conn.execute(
        "SELECT symbol, name FROM securities WHERE name IS NOT NULL AND name != ''")}
    for sym, name in (extra_names or {}).items():
        names.setdefault(sym, name)
    def usable(word: str) -> bool:
        return len(word) >= MIN_ALIAS and word not in words and word not in GENERIC

    candidates: dict[str, set[str]] = {}
    for sym in tracked_symbols(conn):
        toks = [t.lower() for t in re.sub(r"[^A-Za-z ]", " ", names.get(sym) or "").split()]
        if not toks:
            continue
        if usable(toks[0]):
            candidates.setdefault(toks[0], set()).add(sym)
        elif (len(toks) > 1 and toks[1] not in GENERIC and toks[0] not in GENERIC
              and len(toks[0]) + len(toks[1]) >= 8):
            # "Advanced Micro Devices" and "Rocket Lab" start with a dictionary
            # word and would otherwise be unmatchable. Two words together are
            # specific even when neither is on its own, and a phrase is far
            # less likely to appear by accident than a single word.
            candidates.setdefault(f"{toks[0]} {toks[1]}", set()).add(sym)
    # An alias that could mean two of the user's own names means neither.
    return {w: next(iter(s)) for w, s in candidates.items() if len(s) == 1}


def symbols_in(text: str, alias: dict[str, str], known: set[str] | None = None) -> set[str]:
    """Symbols this text is about: cashtags, plus distinctive company names."""
    out = {s for s in CASHTAG.findall(text or "") if known is None or s in known}
    blob = (text or "").lower()
    for word, sym in alias.items():
        if re.search(r"\b" + re.escape(word) + r"\b", blob):
            out.add(sym)
    return out


def rows_for(video: dict, symbols: set[str], handle: str) -> list[dict]:
    """Mention rows for one video, shaped for authors.store_mentions."""
    when = (video.get("upload_date") or "")
    if len(when) == 8 and when.isdigit():
        when = f"{when[:4]}-{when[4:6]}-{when[6:]}"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when or ""):
        return []
    return [{"handle": handle, "symbol": s, "date": when,
             "tweet_id": f"yt:{video['id']}"} for s in sorted(symbols)]


def alias_report(conn: sqlite3.Connection) -> dict:
    """How much of the tracked book can actually be matched by name.

    Reported rather than assumed: about half of the symbols have no
    distinctive first word, so a name never appearing in this count does not
    mean nobody talked about it.
    """
    # Must use the same name source the real run uses, or it reports a
    # coverage figure nothing actually achieves.
    alias = aliases(conn, asset_names())
    tracked = tracked_symbols(conn)
    covered = set(alias.values())
    return {"tracked": len(tracked), "aliases": len(alias),
            "covered": len(covered), "unmatchable": sorted(tracked - covered)}
