"""Which names a video is about — and, more important, which it is not.

Everything here is about precision. Two earlier versions of this matching
produced confident nonsense, and a crowd reading built on nonsense is worse
than no crowd reading, so the cases that must NOT match are tested as heavily
as the ones that must.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ytpull

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


conn = sqlite3.connect(":memory:")
conn.executescript("""
CREATE TABLE securities (id INTEGER PRIMARY KEY, symbol TEXT, name TEXT, kind TEXT);
CREATE TABLE transactions (id INTEGER PRIMARY KEY, security_id INTEGER, quantity REAL);
CREATE TABLE watchlist (symbol TEXT PRIMARY KEY, note TEXT, added_at TEXT,
                        target REAL, stop REAL);
""")
NAMES = {
    "PLTR": "Palantir Technologies Inc",
    "AMD": "Advanced Micro Devices Inc",     # first word is a dictionary word
    "RKLB": "Rocket Lab Corporation",        # ditto
    "AAPL": "Apple Inc",                     # nothing distinctive at all
    "NU": "Nu Holdings Ltd",                 # "holdings" must not become an alias
    "WFCF": "Where Food Comes From Inc",     # "where" must not become an alias
    "MOMO": "Hello Group Inc",               # "hello" must not become an alias
    "SOFI": "SoFi Technologies, Inc",
}
for i, (sym, name) in enumerate(NAMES.items(), 1):
    conn.execute("INSERT INTO securities (id, symbol, name) VALUES (?,?,?)", (i, sym, name))
    conn.execute("INSERT INTO watchlist (symbol) VALUES (?)", (sym,))
alias = ytpull.aliases(conn)
rev = {s: w for w, s in alias.items()}

check("a distinctive company name becomes an alias", rev.get("PLTR") == "palantir", rev.get("PLTR"))
# The long tail of the tradable universe is made of ordinary English words. An
# earlier version matched "where" to WFCF and "hello" to MOMO on real data.
check("an ordinary English word never becomes an alias",
      "where" not in alias and "hello" not in alias,
      {k: v for k, v in alias.items() if k in ("where", "hello")})
# "Nu Holdings" once produced the alias "holdings", so every video that said
# the word matched NU.
check("a generic corporate word never becomes an alias", "holdings" not in alias)
check("a name with no distinctive word is simply unmatchable",
      "AAPL" not in alias.values(), rev.get("AAPL"))
# Two words are specific even when neither is on its own, which is the only
# way AMD and RKLB are reachable at all.
check("a two-word phrase rescues a name starting with a common word",
      rev.get("AMD") == "advanced micro", rev.get("AMD"))
check("...and the same for Rocket Lab", rev.get("RKLB") == "rocket lab", rev.get("RKLB"))

check("a spoken company name is found", ytpull.symbols_in("If you missed Palantir", alias) == {"PLTR"})
check("matching is case-insensitive", ytpull.symbols_in("PALANTIR is extended", alias) == {"PLTR"})
check("a phrase alias matches in running speech",
      ytpull.symbols_in("advanced micro devices reported", alias) == {"AMD"})
check("the word 'where' does not summon a ticker",
      ytpull.symbols_in("where do we go from here", alias) == set())
check("the word 'holdings' does not summon a ticker",
      ytpull.symbols_in("my holdings are up", alias) == set())
# A substring must not count: "sofia" is not SOFI.
check("an alias inside a longer word does not match",
      ytpull.symbols_in("Sofia went to Palantirland", alias) == set(),
      ytpull.symbols_in("Sofia went to Palantirland", alias))
check("cashtags are read even with no name present",
      ytpull.symbols_in("$SPY and $QQQ look heavy", alias) == {"SPY", "QQQ"})
check("a cashtag and a name in one title both count",
      ytpull.symbols_in("$SPY vs Palantir", alias) == {"SPY", "PLTR"})

# ---- mention rows --------------------------------------------------------
vid = {"id": "abc123", "upload_date": "20260912", "title": "x"}
rows = ytpull.rows_for(vid, {"PLTR", "SOFI"}, "cantonmeow")
check("a video becomes one mention row per symbol", len(rows) == 2, rows)
check("YouTube's compact date becomes ISO", rows[0]["date"] == "2026-09-12", rows[0]["date"])
check("the id is namespaced so it cannot collide with a tweet",
      all(r["tweet_id"] == "yt:abc123" for r in rows))
check("the handle is carried through, so one person on two platforms is one account",
      all(r["handle"] == "cantonmeow" for r in rows))
check("a video with no usable date is dropped rather than dated wrongly",
      ytpull.rows_for({"id": "x", "upload_date": None}, {"PLTR"}, "h") == [])

# ---- coverage is reported, not assumed -----------------------------------
report = ytpull.alias_report(conn)
check("coverage says how many symbols are matchable at all",
      report["covered"] < report["tracked"], report)
check("...and names the ones that are not", "AAPL" in report["unmatchable"])

# ---- the channel list ----------------------------------------------------
check("every channel has a videos URL",
      all(u.endswith("/videos") for u in ytpull.CHANNELS.values()))
check("channel handles are unique", len(ytpull.CHANNELS) == len(set(ytpull.CHANNELS)))

conn.close()
failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<72} {detail if not ok else ''}")
print(f"\n  {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
