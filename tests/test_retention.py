"""Retention deletes only what nothing reads, and never a name the app relies on.

The dangerous failure here is not deleting too little. It is a rule that
quietly takes two years off a benchmark, a holding, or a name the replay
grades — so most of these checks are about what is LEFT ALONE.
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import alerts, discover, journal, ledger, prices, retention, watchlist  # noqa: E402

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


TODAY = date(2026, 9, 12)
CUTOFF = "2024-09-12"
OLD = "2023-06-01"          # a bar date well inside the pruned range
RECENT = "2025-06-01"       # inside the kept two years


def db():
    conn = ledger.connect(":memory:")
    journal.ensure_schema(conn)
    discover.ensure_schema(conn)
    alerts.ensure_schema(conn)
    watchlist.ensure_schema(conn)
    prices.ensure_intraday_schema(conn)
    prices._ensure_fetch_log(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS drawings (id INTEGER PRIMARY KEY, symbol TEXT);
        CREATE TABLE IF NOT EXISTS buy_plans (id INTEGER PRIMARY KEY, symbol TEXT);
    """)
    return conn


def security(conn, sym, kind="equity"):
    return conn.execute("INSERT INTO securities (symbol, kind) VALUES (?, ?)", (sym, kind)).lastrowid


def bars(conn, sid, days, source="alpaca-sip"):
    for d in days:
        conn.execute("INSERT INTO prices (security_id, bar_date, close, source) VALUES (?,?,1,?)",
                     (sid, d, source))


def count(conn, sid, before=None):
    if before:
        return conn.execute("SELECT COUNT(*) FROM prices WHERE security_id=? AND bar_date<?",
                            (sid, before)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM prices WHERE security_id=?", (sid,)).fetchone()[0]


# ---- the window is the scan's own ------------------------------------------------
check("the price cutoff is discover.history_from, so pruning and fetching agree",
      retention.price_cutoff(TODAY) == discover.history_from(TODAY) == CUTOFF)
check("a leap day slides to the 28th rather than raising",
      discover.history_from(date(2028, 2, 29)) == "2026-02-28")

# ---- what the code protects -------------------------------------------------------
code = retention.code_symbols()
for s in ("SPY", "QQQ", "IWM", "DIA", "XLK", "XLE", "CPER", "GLD", "DTWEXBGS", "BITQ", "ARKF", "SCHD"):
    check(f"{s} is protected because the code names it", s in code)

# ---- the fixture: one of everything ---------------------------------------------
conn = db()
ids = {}
for sym, kind in (("SPY", "etf"), ("HELD", "equity"), ("WATCHED", "equity"), ("GRADED", "equity"),
                  ("SCREENED", "equity"), ("DRAWN", "equity"), ("BYHAND", "equity"), ("FREDX", "equity"),
                  ("NOBARS", "equity")):
    ids[sym] = security(conn, sym, kind)
    if sym != "NOBARS":
        bars(conn, ids[sym], [OLD, "2023-07-01", RECENT], source="fred" if sym == "FREDX" else "alpaca-sip")
# HELD: a transaction. WATCHED: on the watchlist. GRADED: a replayed call.
# SCREENED, DRAWN, BYHAND, FREDX: the discovery screen brought them in...
inst = conn.execute("INSERT INTO institutions (name) VALUES ('t')").lastrowid
acct = conn.execute("INSERT INTO accounts (institution_id, external_id, name, kind) VALUES (?, 'x', 'x', 'brokerage')",
                    (inst,)).lastrowid
conn.execute("""INSERT INTO transactions (account_id, txn_date, kind, security_id, quantity, amount, source, source_id)
                VALUES (?, '2024-01-01', 'buy', ?, 1, -10, 't', '1')""", (acct, ids["HELD"]))
conn.execute("INSERT INTO watchlist (symbol) VALUES ('WATCHED')")
journal.record(conn, "2025-01-03", "GRADED", "replay-screen", "buy", price=1.0, timeframe="D")
for sym in ("SCREENED", "DRAWN", "FREDX", "GRADED", "NOBARS"):
    conn.execute("INSERT INTO discover_universe (symbol, kept, screened_at) VALUES (?, 1, '2026-09-01')", (sym,))
# ...but DRAWN has a drawing on it, FREDX has a FRED series, and BYHAND was
# never on the screen at all: somebody charted it.
conn.execute("INSERT INTO drawings (symbol) VALUES ('DRAWN')")
conn.commit()

keep = retention.protected_symbols(conn)
for sym, why in (("SPY", "the code names it"), ("HELD", "it was traded"), ("WATCHED", "it is watched"),
                 ("GRADED", "a replayed call is graded from its bars"), ("DRAWN", "it has a drawing"),
                 ("FREDX", "its bars are not from a feed")):
    check(f"{sym} is protected: {why}", sym in keep)
check("SCREENED is not protected: only the screen knows it", "SCREENED" not in keep)
prunable = {s for _, s, _ in retention.prunable_price_symbols(conn, TODAY)}
check("only the screened-only name is prunable", prunable == {"SCREENED"}, prunable)
check("a name charted by hand is not the screen's to age out, even unprotected",
      "BYHAND" not in prunable and "BYHAND" not in keep)

# ---- the other tables -------------------------------------------------------------
old_day = (TODAY - timedelta(days=100)).isoformat()
new_day = (TODAY - timedelta(days=10)).isoformat()
conn.execute("INSERT INTO discover_hits (day, method, symbol) VALUES (?, 'm', 'A')", (old_day,))
conn.execute("INSERT INTO discover_hits (day, method, symbol) VALUES (?, 'm', 'A')", (new_day,))
old_log = (TODAY - timedelta(days=40)).isoformat()
conn.execute("INSERT INTO discover_universe_log (day, symbol, kept) VALUES (?, 'DROPPED', 0)", (old_log,))
conn.execute("INSERT INTO discover_universe_log (day, symbol, kept) VALUES (?, 'KEPT', 1)", (old_log,))
conn.execute("INSERT INTO discover_universe_log (day, symbol, kept) VALUES (?, 'DROPPEDNEW', 0)", (new_day,))
old_alert = (TODAY - timedelta(days=200)).isoformat()
conn.execute("INSERT INTO alerts (created_at, day, kind, level, message, key) VALUES (?, ?, 'k', 'info', 'm', 'old')",
             (old_alert, old_alert))
conn.execute("INSERT INTO alerts (created_at, day, kind, level, message, key) VALUES (?, ?, 'k', 'info', 'm', 'new')",
             (new_day, new_day))
conn.execute("INSERT INTO intraday_bars (security_id, timeframe, ts, source) VALUES (?, '5Min', ?, 't')",
             (ids["HELD"], (TODAY - timedelta(days=45)).isoformat() + "T14:00:00Z"))
conn.execute("INSERT INTO intraday_bars (security_id, timeframe, ts, source) VALUES (?, '5Min', ?, 't')",
             (ids["HELD"], (TODAY - timedelta(days=5)).isoformat() + "T14:00:00Z"))
stale = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
fresh = datetime.now(timezone.utc).isoformat(timespec="seconds")
conn.execute("INSERT INTO price_fetches (symbol, attempted_at, outcome) VALUES ('NOBARS', ?, 'empty')", (stale,))
conn.execute("INSERT INTO price_fetches (symbol, attempted_at, outcome) VALUES ('NOBARSNEW', ?, 'empty')", (fresh,))
conn.execute("INSERT INTO price_fetches (symbol, attempted_at, outcome) VALUES ('HELD', ?, 'ok')", (stale,))
conn.commit()

plan = retention.rules(conn, TODAY)
by = {r["table"]: r for r in plan}
check("every table has a rule", set(by) == {"prices", "discover_hits", "discover_universe_log", "alerts",
                                            "intraday_bars", "price_fetches"}, set(by))
check("prices: two stale bars of the one prunable name", by["prices"]["rows"] == 2, by["prices"]["rows"])
check("discover_hits: the 100-day-old hit, not the 10-day-old one", by["discover_hits"]["rows"] == 1)
check("universe log: the dropped name from 40 days ago, never a kept one",
      by["discover_universe_log"]["rows"] == 1)
check("alerts: the 200-day-old one", by["alerts"]["rows"] == 1)
check("intraday: the 45-day-old bar", by["intraday_bars"]["rows"] == 1)
check("fetch log: the stale no-bars symbol only", by["price_fetches"]["rows"] == 1)
check("an estimate is a number of megabytes, never a crash",
      all(isinstance(retention.estimate_mb(conn, r), float) for r in plan))
check("a dry run deletes nothing",
      count(conn, ids["SCREENED"]) == 3 and conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 2)

# ---- apply ------------------------------------------------------------------------
done = retention.apply(conn, plan, say=lambda *a: None)
check("apply reports what it deleted", done == {"prices": 2, "discover_hits": 1, "discover_universe_log": 1,
                                                "alerts": 1, "intraday_bars": 1, "price_fetches": 1}, done)
check("the screened name keeps its recent bar and loses the old ones",
      count(conn, ids["SCREENED"]) == 1 and count(conn, ids["SCREENED"], CUTOFF) == 0)
for sym in ("SPY", "HELD", "WATCHED", "GRADED", "DRAWN", "BYHAND", "FREDX"):
    check(f"{sym} keeps every bar", count(conn, ids[sym]) == 3)
check("the kept universe rows survive",
      {r[0] for r in conn.execute("SELECT symbol FROM discover_universe_log")} == {"KEPT", "DROPPEDNEW"})
check("the fresh no-bars fetch and the real one survive",
      {r[0] for r in conn.execute("SELECT symbol FROM price_fetches")} == {"NOBARSNEW", "HELD"})
check("a second pass finds nothing", sum(r["rows"] for r in retention.rules(conn, TODAY)) == 0)

# A ledger with none of the optional tables (a fresh clone before anything
# ran) must plan nothing rather than fail.
bare = ledger.connect(":memory:")
check("a bare ledger plans only the tables it has",
      {r["table"] for r in retention.rules(bare, TODAY)} == {"prices"}
      and retention.rules(bare, TODAY)[0]["rows"] == 0)

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
