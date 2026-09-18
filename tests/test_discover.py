"""Discovery: which listings count as companies, the liquidity floor, and the hits."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import discover
from app.ledger import connect

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

raw = [
    {"symbol": "IREN", "name": "IREN Limited", "exchange": "NASDAQ", "tradable": True},
    {"symbol": "WTGUU", "name": "Wintergreen Acquisition Corp. Units", "exchange": "NASDAQ", "tradable": True},
    {"symbol": "BBBYW", "name": "Neighborhood Intelligence Warrant", "exchange": "NASDAQ", "tradable": True},
    {"symbol": "NBIG", "name": "Themes ETF Trust Leverage Shares", "exchange": "NASDAQ", "tradable": True},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "ARCA", "tradable": True},
    {"symbol": "BRK.B", "name": "Berkshire Hathaway Class B", "exchange": "NYSE", "tradable": True},
    {"symbol": "HALT", "name": "Halted Co", "exchange": "NYSE", "tradable": False},
    {"symbol": "SIVEF", "name": "Sivers Semiconductors", "exchange": "OTC", "tradable": True},
    {"symbol": "NTRS", "name": "Northern Trust Corporation", "exchange": "NASDAQ", "tradable": True},
]
c = {a["symbol"] for a in discover.candidates(raw)}
check("an operating company on NASDAQ or NYSE is a candidate", "IREN" in c, c)
check("blank-cheque shells, warrants and ETF trusts are dropped by their own names",
      not ({"WTGUU", "BBBYW", "NBIG"} & c), c)
check("ARCA and OTC listings are not candidates", not ({"SPY", "SIVEF"} & c), c)
check("a dotted share class and an untradable name are dropped", not ({"BRK.B", "HALT"} & c), c)
check("the word Trust costs a real bank its place, and that is accepted", "NTRS" not in c)

bars = [("2026-08-01", 10.0, 9.9, 10.2, 9.8, 1_000_000.0), ("2026-08-02", 12.0, 10.0, 12.1, 9.9, 500_000.0)]
dv, px = discover._dollar_volume(bars)
check("dollar volume is the average of close times volume", abs(dv - 8_000_000.0) < 1e-6 and px == 12.0, (dv, px))
check("no bars means no figures", discover._dollar_volume([]) == (None, None))

conn = connect(":memory:")
discover.ensure_schema(conn)
from app import watchlist as _wl
_wl.ensure_schema(conn)
conn.execute("INSERT INTO watchlist (symbol) VALUES ('IREN')")
conn.executemany("INSERT INTO discover_universe (symbol, name, exchange, price, dollar_volume, kept, screened_at) VALUES (?,?,?,?,?,1,'2026-09-01')",
                 [("IREN", "IREN Limited", "NASDAQ", 40.0, 9e8), ("NEWCO", "New Co", "NYSE", 12.0, 2e7)])
conn.executemany("INSERT INTO discover_hits (day, method, symbol, pct, coverage, rs_rank, price) VALUES (?,?,?,?,?,?,?)",
                 [("2026-09-01", "momentum-relative-strength", "NEWCO", 0.8, 1.0, 91, 12.0),
                  ("2026-09-02", "momentum-relative-strength", "NEWCO", 0.85, 1.0, 93, 12.4),
                  ("2026-09-02", "momentum-relative-strength", "IREN", 0.9, 1.0, 88, 40.0)])
h = discover.hits(conn)
m = h["methods"].get("momentum-relative-strength") or {}
check("the latest scan is reported", h["day"] == "2026-09-02", h.get("day"))
check("a name already on the watchlist is left out", [x["symbol"] for x in m.get("hits", [])] == ["NEWCO"], m)
check("a name flagged on consecutive nights carries the count", m["hits"][0]["days_flagged"] == 2, m["hits"][0])
check("the listing's name and liquidity travel with the hit",
      m["hits"][0]["name"] == "New Co" and m["hits"][0]["dollar_volume"] == 2e7, m["hits"][0])
# What a row says about the company and its moves, from cached data only.
from app import sectors as _sec  # noqa: E402
_sec.ensure_schema(conn)
conn.execute("INSERT INTO security_meta (symbol, sector, sic_description, source) VALUES ('NEWCO', 'Technology', 'SERVICES-PREPACKAGED SOFTWARE', 'sec')")
_sid = conn.execute("INSERT INTO securities (symbol, kind) VALUES ('NEWCO', 'equity')").lastrowid
from datetime import date as _date, timedelta as _td  # noqa: E402
for i in range(80):
    d = (_date(2026, 5, 1) + _td(days=i)).isoformat()
    px = 10.0 + i * 0.05
    conn.execute("INSERT INTO prices (security_id, bar_date, close, open, high, low, volume, source) VALUES (?,?,?,?,?,?,0,'test')",
                 (_sid, d, px, px, px + 1 if i == 40 else px, px))
rows = discover.describe(conn, m["hits"])
r0 = rows[0]
check("describe adds the sector and the business line, in words",
      r0["sector"] == "Technology" and r0["business"] == "Services-Prepackaged Software", r0)
check("the month move comes from the cached bars", r0["chg_1m"] is not None and abs(r0["chg_1m"] - (13.95 / 12.9 - 1)) < 1e-6, r0.get("chg_1m"))
check("from the 52-week high is negative or zero", r0["from_52w_high"] is not None and r0["from_52w_high"] <= 0, r0.get("from_52w_high"))
check("the method scan's RS rank rides along", r0["rs_rank"] == 93, r0.get("rs_rank"))
check("a name with no bars keeps its row and says so",
      discover.describe(conn, [{"symbol": "NOBARS"}])[0]["chg_1m"] is None)
check("describe on nothing is nothing", discover.describe(conn, []) == [])
n = discover.log_universe(conn, "2026-09-03")
check("a screen is logged by the day it was taken", n == 2 and discover.universe_on(conn, "2026-09-03") == ["IREN", "NEWCO"])
check("logging the same day twice adds nothing", discover.log_universe(conn, "2026-09-03") == 0)
check("a date before any screen has no universe", discover.universe_on(conn, "2026-01-01") == [])
check("a later date reads the latest screen on or before it", discover.universe_on(conn, "2026-12-31") == ["IREN", "NEWCO"])

# ---- accumulation: volume expanding before the price has run --------------
# Measured 2026-09-09: names in the band quadrupled within a year 11.5% of the
# time against a 1.5% base rate. Every bound below exists because leaving it
# off broke that measurement, so each is pinned by a test.
def _bars(n=200, price=10.0, vol=1_000_000, hot=0, hot_mult=1.0, drift=1.0):
    """n sessions; the last `hot` of them carry `hot_mult` times the volume."""
    out = []
    for i in range(n):
        p = price * (drift ** i)
        v = vol * (hot_mult if i >= n - hot else 1)
        out.append({"time": f"2026-01-{i + 1:02d}" if i < 31 else f"2026-{2 + i // 31:02d}-{i % 31 + 1:02d}",
                    "open": p, "high": p, "low": p, "close": p, "volume": v})
    return out

quiet = _bars()
check("a name whose volume has not expanded is not accumulating",
      discover.accumulation_at(quiet) is None)

hot = _bars(hot=discover.ACC_WIN, hot_mult=8)
got = discover.accumulation_at(hot)
check("volume 8x its own base, price flat, is accumulating",
      got is not None and 7.0 < got["surge"] < 9.0, got)
check("...and it reports the numbers the display needs",
      got and {"price", "surge", "runup", "dollar_volume"} <= set(got), got)

check("an absurd volume ratio is a corporate action, not accumulation",
      discover.accumulation_at(_bars(hot=discover.ACC_WIN, hot_mult=500)) is None,
      "CLRO printed 1,900x its base on a reverse split and inflated the headline")

# A name that has already run is an ordinary momentum screen, which the same
# study found is worth much less. 1.006**126 is about 2.1x over the window.
check("a name that has already run is not accumulating",
      discover.accumulation_at(_bars(hot=discover.ACC_WIN, hot_mult=8, drift=1.006)) is None,
      "the whole point is to be early")
check("a collapsed or unadjusted-split name is not accumulating",
      discover.accumulation_at(_bars(hot=discover.ACC_WIN, hot_mult=8, drift=0.99)) is None)

check("too little history is None rather than a guess",
      discover.accumulation_at(_bars(n=discover.ACC_WIN + discover.ACC_BASE - 5)) is None)
check("an illiquid name is skipped however much its volume expanded",
      discover.accumulation_at(_bars(hot=discover.ACC_WIN, hot_mult=8, vol=100)) is None)
check("a sub-dollar name is skipped",
      discover.accumulation_at(_bars(price=0.5, hot=discover.ACC_WIN, hot_mult=8, vol=90_000_000)) is None)

check("the bounds are the measured ones",
      (discover.ACC_MIN, discover.ACC_MAX, discover.ACC_RUNUP_MAX) == (4.0, 20.0, 1.25),
      "changing these changes what was measured; re-measure before moving them")


# ---- crowd arrival: has anybody the user follows noticed yet? -------------
from app import authors  # noqa: E402
_c = connect(":memory:")
authors.ensure_schema(_c)
check("cashtags are read, bare words that look like tickers are not",
      authors.mentions_in("$IREN is up, but IT and ALL are just words") == {"IREN"},
      authors.mentions_in("$IREN is up, but IT and ALL are just words"))
check("several cashtags in one post all count",
      authors.mentions_in("$MU and $SNDK") == {"MU", "SNDK"})

authors.store_mentions(_c, [
    {"handle": "@a", "symbol": "HOT", "date": "2026-09-01", "tweet_id": "1"},
    {"handle": "b", "symbol": "HOT", "date": "2026-09-02", "tweet_id": "2"},
    {"handle": "c", "symbol": "HOT", "date": "2026-09-02", "tweet_id": "3"},
    {"handle": "d", "symbol": "HOT", "date": "2026-09-03", "tweet_id": "4"},
    {"handle": "a", "symbol": "HOT", "date": "2026-09-03", "tweet_id": "5"},
    {"handle": "a", "symbol": "WARM", "date": "2026-09-01", "tweet_id": "6"},
    {"handle": "b", "symbol": "WARM", "date": "2026-09-02", "tweet_id": "7"},
])
check("storing the same tweet twice adds nothing",
      authors.store_mentions(_c, [{"handle": "a", "symbol": "HOT", "date": "2026-09-01", "tweet_id": "1"}]) == 0)

_cr = authors.crowd(_c, ["HOT", "WARM", "QUIET"], "2026-09-09")
check("four distinct accounts is crowded", _cr["HOT"]["state"] == "crowded", _cr["HOT"])
check("two is warming", _cr["WARM"]["state"] == "warming", _cr["WARM"])
check("nobody talking is early", _cr["QUIET"]["state"] == "early" and _cr["QUIET"]["accounts"] == 0)
check("it counts ACCOUNTS, not posts — one person posting twice is one person",
      _cr["HOT"]["accounts"] == 4, "five posts from four handles")
check("the crowd verdict says it is not measured, because the cut-offs are a judgement",
      _cr["HOT"]["measured"] is False)
# The bug that made every name look untouched: X writes its own date format and
# a naive [:10] slice produced "Fri Sep 04", which matched no ISO window.
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("xm", Path(__file__).resolve().parent.parent / "research" / "x-mentions.py")
_xm = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_xm)
check("X's own date format is parsed, not sliced",
      _xm.iso_date("Fri Sep 04 20:27:53 +0000 2026") == "2026-09-04",
      _xm.iso_date("Fri Sep 04 20:27:53 +0000 2026"))
check("an already-ISO date is left alone", _xm.iso_date("2026-09-04T12:00:00Z") == "2026-09-04")
check("an unparseable date is dropped rather than stored wrong", _xm.iso_date("last tuesday") == "")

check("coverage reports how thin the record is, so 'early' and 'no data' can be told apart",
      authors.mention_coverage(_c)["thin"] is True and authors.mention_coverage(_c)["days"] == 3,
      authors.mention_coverage(_c))
_c.close()

conn.close()

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
