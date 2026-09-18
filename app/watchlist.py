"""Watchlist — tags, not folders.

A ticker belongs to "semis", "AI capex" and "owned" at the same time. Fidelity
and Yahoo both force a single-list mental model, which means the same name gets
duplicated across lists and the lists drift apart. Tags are many-to-many, so a
name is entered once and appears wherever it belongs.

Every row is position-aware by construction: the ledger already knows whether
something is owned, at what basis and at what unrealised P/L, and a watchlist
that cannot see that is the gap between Fidelity (knows the position, charts
badly) and TradingView (charts well, knows nothing about the position).
"""
from __future__ import annotations

import bisect
import re

from . import holdings, indicators, performance, prices, sectors

# How many bars the per-row readings are computed from; see rows().
RECENT_BARS = 520

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol     TEXT PRIMARY KEY,
    note       TEXT,
    added_at   TEXT NOT NULL DEFAULT (datetime('now')),
    target     REAL,          -- a price you would act at
    stop       REAL           -- a level that would invalidate the idea
);
CREATE TABLE IF NOT EXISTS watchlist_tags (
    symbol TEXT NOT NULL REFERENCES watchlist(symbol) ON DELETE CASCADE,
    tag    TEXT NOT NULL,
    PRIMARY KEY (symbol, tag)
);
CREATE INDEX IF NOT EXISTS ix_wl_tag ON watchlist_tags (tag);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def add(conn, symbol: str, tags: list[str] | None = None, note: str | None = None,
        target: float | None = None, stop: float | None = None) -> dict:
    ensure_schema(conn)
    sym = clean_symbol(symbol)
    if not sym:
        return {"error": "no symbol"}
    conn.execute("""INSERT INTO watchlist (symbol, note, target, stop) VALUES (?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      note   = COALESCE(excluded.note, watchlist.note),
                      target = COALESCE(excluded.target, watchlist.target),
                      stop   = COALESCE(excluded.stop, watchlist.stop)""",
                 (sym, note, target, stop))
    for t in (tags or []):
        t = clean_tag(t)
        if t:
            conn.execute("INSERT OR IGNORE INTO watchlist_tags (symbol, tag) VALUES (?,?)", (sym, t))
    return {"symbol": sym}


def clean_tag(raw: str) -> str:
    """Restrict a tag to characters that cannot be markup.

    Lowercasing does not defang <img src=x onerror=...>. These strings are
    rendered into the page, so the write path — not only the render — has to
    make script impossible: escaping is a second line of defence, and the first
    should be that the data never contains the characters in the first place.
    """
    return re.sub(r"[^a-z0-9 _\-]", "", (raw or "").strip().lower())[:40]


def clean_symbol(raw: str) -> str:
    """A ticker is letters, digits, dot, dash. Nothing else has a meaning here."""
    return re.sub(r"[^A-Z0-9.\-]", "", (raw or "").strip().upper())[:24]


def remove(conn, symbol: str) -> dict:
    ensure_schema(conn)
    sym = clean_symbol(symbol)
    conn.execute("DELETE FROM watchlist_tags WHERE symbol = ?", (sym,))
    conn.execute("DELETE FROM watchlist WHERE symbol = ?", (sym,))
    return {"removed": sym}


def sync_theme_tags(conn) -> int:
    """Tag every watchlist row with the theme it belongs to.

    Themes are defined in themes.py as membership lists, but the watchlist
    groups by TAG — so a theme nothing was tagged with grouped nothing, and all
    164 rows fell into "untagged" no matter which theme they belonged to. The
    two were never connected.

    Only theme keys are touched. A tag the user added by hand is left alone, and
    a symbol that has moved between themes loses the stale one so it does not
    end up in two groups at once.
    """
    from . import themes

    keys = set(themes.THEMES)
    owner = {sym: key for key, spec in themes.THEMES.items()
             for sym in spec["symbols"]}
    changed = 0
    for (sym,) in conn.execute("SELECT symbol FROM watchlist").fetchall():
        want = owner.get(sym)
        have = {t for (t,) in conn.execute(
            "SELECT tag FROM watchlist_tags WHERE symbol = ?", (sym,))} & keys
        if want and have == {want}:
            continue
        for stale in have - ({want} if want else set()):
            conn.execute("DELETE FROM watchlist_tags WHERE symbol = ? AND tag = ?",
                         (sym, stale))
            changed += 1
        if want and want not in have:
            conn.execute("INSERT OR IGNORE INTO watchlist_tags (symbol, tag)"
                         " VALUES (?,?)", (sym, want))
            changed += 1
    conn.commit()
    return changed


def set_tags(conn, symbol: str, tags: list[str]) -> dict:
    ensure_schema(conn)
    sym = clean_symbol(symbol)
    conn.execute("DELETE FROM watchlist_tags WHERE symbol = ?", (sym,))
    for t in tags:
        t = clean_tag(t)
        if t:
            conn.execute("INSERT OR IGNORE INTO watchlist_tags (symbol, tag) VALUES (?,?)", (sym, t))
    return {"symbol": sym, "tags": tags}


def set_note(conn, symbol: str, note: str | None, target: float | None, stop: float | None) -> None:
    """The user's own note, target and stop on a watched name — the three
    fields the payload always carried and the page never showed or let
    anyone set (app review 2026-09-06)."""
    ensure_schema(conn)
    conn.execute("UPDATE watchlist SET note=?, target=?, stop=? WHERE symbol=?",
                 ((note or "").strip() or None, target, stop, clean_symbol(symbol)))


def tags(conn) -> list[dict]:
    ensure_schema(conn)
    return [{"tag": r["tag"], "count": r["n"]} for r in conn.execute(
        "SELECT tag, COUNT(*) n FROM watchlist_tags GROUP BY tag ORDER BY n DESC, tag")]


def _pct_from(series: dict, dates: list[str], days: int) -> float | None:
    if not dates:
        return None
    end = dates[-1]
    idx = max(0, len(dates) - 1 - days)
    p0, p1 = series.get(dates[idx]), series.get(end)
    return (p1 / p0 - 1.0) if p0 and p1 else None


def rows(conn, end: str, scope: str = "investment") -> list[dict]:
    """The watchlist, enriched with price action, sector and your own position."""
    ensure_schema(conn)
    sectors.ensure_schema(conn)

    symbols = [r["symbol"] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]
    tag_map: dict[str, list[str]] = {}
    for r in conn.execute("SELECT symbol, tag FROM watchlist_tags ORDER BY tag"):
        tag_map.setdefault(r["symbol"], []).append(r["tag"])

    meta = sectors.lookup(conn, symbols) if symbols else {}
    txns = performance.load_transactions(conn, "1900-01-01", end, scope)
    pos = {p["symbol"]: p for p in holdings.positions(conn, txns, end)}

    out = []
    for r in conn.execute("SELECT * FROM watchlist ORDER BY symbol"):
        sym = r["symbol"]
        series = prices.load_series(conn, sym)
        dates = prices.sorted_dates(conn, sym)
        last = series.get(dates[-1]) if dates else None

        # Only the tail. Every reading below is taken at the LAST bar, and
        # loading eight years to compute a 14-day RSI at the end of them was
        # two seconds of the request. The 200-day average and the 52-week
        # range are exact on any tail longer than themselves; Wilder's RSI
        # carries its seed forward with weight (13/14)^n, which at n=500 is
        # below double precision, so its last value is the same number too.
        # `bars` in the row stays the count over the full range.
        bars = prices.load_bars(conn, sym, "2018-01-01", end, last=RECENT_BARS)
        n_bars = (bisect.bisect_right(dates, end) - bisect.bisect_left(dates, "2018-01-01")
                  if dates else 0)
        rsi = indicators.rsi(bars, 14) if n_bars > 20 else []
        sma50 = indicators.sma(bars, 50) if n_bars > 60 else []
        sma200 = indicators.sma(bars, 200) if n_bars > 220 else []
        hi52 = max((b["high"] for b in bars[-252:]), default=None)
        lo52 = min((b["low"] for b in bars[-252:]), default=None)

        p = pos.get(sym)
        out.append({
            "symbol": sym,
            "tags": tag_map.get(sym, []),
            "note": r["note"], "target": r["target"], "stop": r["stop"],
            "added_at": r["added_at"],
            "sector": (meta.get(sym) or {}).get("sector") or "Unknown",
            "price": last,
            "chg_1w": _pct_from(series, dates, 5),
            "chg_1m": _pct_from(series, dates, 21),
            "chg_3m": _pct_from(series, dates, 63),
            "chg_6m": _pct_from(series, dates, 126),
            "chg_12m": _pct_from(series, dates, 252),
            "rsi": rsi[-1]["value"] if rsi else None,
            "above_50": (last > sma50[-1]["value"]) if (last and sma50) else None,
            "above_200": (last > sma200[-1]["value"]) if (last and sma200) else None,
            "from_52w_high": ((last / hi52 - 1.0) if last and hi52 else None),
            "from_52w_low": ((last / lo52 - 1.0) if last and lo52 else None),
            "to_target": ((r["target"] / last - 1.0) if last and r["target"] else None),
            # Position awareness is the whole point — a watchlist that cannot
            # see what you own makes you check two screens to answer one question.
            "owned": bool(p),
            "quantity": p["quantity"] if p else None,
            "avg_cost": p["avg_cost"] if p else None,
            "unrealised_pct": p["unrealised_pct"] if p else None,
            "weight": p["weight"] if p else None,
            "bars": n_bars,
        })
    rank_relative_strength(out)
    # Insider open-market activity over the last quarter, as context on the
    # row. Nothing here is scored by it; the replay decides whether it should be.
    try:
        from . import insiders
        ins = insiders.summary(conn, [r["symbol"] for r in out])
        for r in out:
            r["insiders"] = ins.get(r["symbol"])
    except Exception:                                          # noqa: BLE001
        for r in out:
            r["insiders"] = None
    out.sort(key=lambda x: (not x["owned"], x["symbol"]))
    return out


# The weights are IBD's published shape for its RS rating — the most recent
# quarter counts double — applied to the windows this app already computes.
# The rank is against the names on THIS list, not the market, which is the
# honest version of the question a watchlist can answer: of the things I am
# looking at, which are strongest.
RS_WEIGHTS = (("chg_3m", 0.4), ("chg_6m", 0.2), ("chg_12m", 0.2), ("chg_1m", 0.2))


def momentum_at(series: dict, dates: list[str], asof: str) -> dict:
    """The four momentum windows as of a date, from a price series."""
    import bisect
    i = bisect.bisect_right(dates, asof)
    if i < 22:
        return {}
    end = dates[i - 1]
    p1 = series.get(end)
    out = {}
    for key, days in (("chg_1m", 21), ("chg_3m", 63), ("chg_6m", 126), ("chg_12m", 252)):
        j = i - 1 - days
        if j >= 0 and p1 and series.get(dates[j]):
            out[key] = p1 / series[dates[j]] - 1.0
    return out


def rs_ranks(conn, symbols: list[str], asof: str) -> dict[str, int]:
    """Relative-strength rank across `symbols` as of `asof`, 1 to 99."""
    rows = []
    for s in symbols:
        m = momentum_at(prices.load_series(conn, s), prices.sorted_dates(conn, s), asof)
        rows.append({"symbol": s, **m})
    rank_relative_strength(rows)
    return {r["symbol"]: r["rs_rank"] for r in rows if r.get("rs_rank") is not None}


def rank_relative_strength(rows: list[dict]) -> None:
    """Percentile rank of composite return among the rows, 1 (weakest) to 99."""
    scored = []
    for r in rows:
        parts = [(r.get(k), w) for k, w in RS_WEIGHTS if r.get(k) is not None]
        if len(parts) < 2:
            r["rs_score"] = None
            r["rs_rank"] = None
            continue
        wsum = sum(w for _, w in parts)
        r["rs_score"] = round(sum(v * w for v, w in parts) / wsum, 6)
        scored.append(r)
    n = len(scored)
    if n < 2:
        for r in scored:
            r["rs_rank"] = None
        return
    scored.sort(key=lambda r: r["rs_score"])
    for i, r in enumerate(scored):
        r["rs_rank"] = max(1, min(99, round(100 * (i + 0.5) / n)))


def sync_prices(conn, end: str) -> dict:
    """Make sure every watched name has price history, fetching what is missing."""
    ensure_schema(conn)
    got, failed = 0, []
    for r in conn.execute("SELECT symbol FROM watchlist"):
        res = prices.ensure_symbol(conn, r["symbol"], "2018-01-01", end, as_equity=True)
        if res.get("ok"):
            got += 1
        else:
            failed.append({"symbol": r["symbol"], "error": res.get("error")})
    return {"priced": got, "failed": failed}
