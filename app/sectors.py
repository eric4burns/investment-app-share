"""Sector classification and rotation.

Sector data comes from SEC EDGAR — the ticker-to-CIK map and each filer's SIC
code — because it is official, free, keyless and not going to quietly start
charging. SIC codes are coarse and occasionally eccentric (a bitcoin miner
files as a services company), so they are folded into the eleven GICS-style
sectors people actually talk about, and anything unmapped is reported as
unknown rather than guessed into a bucket.

Rotation is measured against the SPDR sector ETFs, which is what "rotate into
energy" concretely means: relative strength of XLE against the market over
several windows at once, because a sector leading over one month and lagging
over six is a different thing from one leading over both.
"""
from __future__ import annotations

import json
import urllib.request

from . import config, prices

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def user_agent() -> dict:
    """The header SEC EDGAR requires, naming whoever is actually running this.

    EDGAR's fair-access policy asks every caller to identify itself with a
    contact address and throttles requests that do not. Set `sec_contact` in
    config.json. Without it the request still goes out — the sector lookup is
    optional and failing it silently would be worse — but it identifies nobody,
    which the SEC may rate-limit.
    """
    contact = (config.load().get("sec_contact") or "").strip()
    return {"User-Agent": f"investment-app {contact}".strip()
            if contact else "investment-app (no contact configured)"}


# Kept as a module attribute for anything importing it by name; the request
# path calls user_agent() directly so a config written after import is seen.
UA = user_agent()

# The eleven SPDR sector funds, plus the benchmark they are measured against.
SECTOR_ETFS = {
    "XLK": "Technology", "XLF": "Financials", "XLV": "Health Care",
    "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
    "XLE": "Energy", "XLI": "Industrials", "XLB": "Materials",
    "XLU": "Utilities", "XLRE": "Real Estate", "XLC": "Communication Services",
}
MARKET = "SPY"

# SIC ranges -> sector. Deliberately a small, readable table rather than a
# thousand-line lookup: the point is a usable grouping, not a taxonomy.
SIC_RANGES = [
    ((100, 999), "Consumer Staples"), ((1000, 1119), "Materials"),
    ((1200, 1399), "Energy"), ((1400, 1499), "Materials"),
    ((1500, 1799), "Industrials"), ((2000, 2199), "Consumer Staples"),
    ((2200, 2399), "Consumer Discretionary"), ((2400, 2599), "Industrials"),
    ((2600, 2699), "Materials"), ((2700, 2799), "Communication Services"),
    # Narrow ranges MUST precede the band that contains them — sector_for_sic
    # returns the first match, so listing chemicals (2800-2899) first classified
    # SIC 2834 "Pharmaceutical Preparations", the single most common biotech
    # filing code, as Materials.
    ((2830, 2836), "Health Care"),
    # Aerospace and defence. These sit inside broader bands — 3812 inside a
    # Health Care one, 3721 and 3760 inside the automotive one — so without
    # explicit narrow ranges L3Harris and Kratos classified as Health Care and
    # guided missiles as Consumer Discretionary. GICS puts all of it in
    # Industrials.
    ((3480, 3489), "Industrials"),      # ordnance and accessories
    ((3721, 3728), "Industrials"),      # aircraft and parts
    ((3760, 3769), "Industrials"),      # guided missiles, space vehicles
    ((3812, 3812), "Industrials"),      # search, detection, navigation, guidance
    ((2800, 2899), "Materials"), ((2830, 2836), "Health Care"),
    ((2900, 2999), "Energy"), ((3000, 3299), "Materials"),
    ((3300, 3499), "Materials"), ((3500, 3599), "Technology"),
    ((3600, 3699), "Technology"), ((3700, 3799), "Consumer Discretionary"),
    ((3800, 3851), "Health Care"), ((3852, 3899), "Technology"),
    ((3900, 3999), "Consumer Discretionary"), ((4000, 4499), "Industrials"),
    ((4500, 4599), "Industrials"), ((4600, 4699), "Energy"),
    ((4700, 4799), "Industrials"), ((4800, 4899), "Communication Services"),
    ((4900, 4999), "Utilities"), ((5000, 5199), "Industrials"),
    ((5200, 5999), "Consumer Discretionary"), ((6000, 6299), "Financials"),
    ((6300, 6499), "Financials"), ((6500, 6599), "Real Estate"),
    ((6798, 6798), "Real Estate"), ((6600, 6999), "Financials"),
    ((7000, 7299), "Consumer Discretionary"), ((7300, 7379), "Technology"),
    ((7380, 7399), "Industrials"), ((7400, 7999), "Consumer Discretionary"),
    ((8000, 8099), "Health Care"), ((8100, 8999), "Industrials"),
]

# SIC is a filing category, not a business description, and for a few names it
# is actively misleading: a bitcoin miner that files as "Finance Services"
# lands in Financials and drags a whole portfolio's sector picture with it.
# These are corrections, not guesses — each one names why.
SIC_OVERRIDES = {
    "IREN":  ("Technology", "Bitcoin mining and AI data centres; files SIC 6199 Finance Services"),
    "DGXX":  ("Technology", "Digital infrastructure and power; files under finance"),
    "MSTR":  ("Technology", "Software company operating as a bitcoin treasury; files under finance"),
    "CIFR":  ("Technology", "Bitcoin mining infrastructure"),
    "BMNR":  ("Technology", "Digital asset treasury"),
    "SMR":   ("Utilities",  "Small modular nuclear reactors"),
    "OKLO":  ("Utilities",  "Advanced nuclear power"),
    "ASTS":  ("Communication Services", "Satellite direct-to-cell network"),
    "SATL":  ("Communication Services", "Satellite communications"),
    "RKLB":  ("Industrials", "Launch vehicles and space systems"),
    "AEVA":  ("Technology", "Lidar and perception sensors; files SIC 3714 Motor Vehicle Parts"),
}

# ETFs and funds do not file SIC codes, so EDGAR cannot classify them. They are
# named here rather than left Unknown, since a watchlist full of "Unknown" is
# worse than a short hand-maintained list.
FUND_SECTORS = {
    "SPY": "Index", "QQQ": "Index", "IWM": "Index", "QLD": "Index",
    "TQQQ": "Index", "SCHD": "Index", "EUSA": "Index", "DIA": "Index",
    "COPX": "Materials", "GLD": "Materials", "SLV": "Materials",
    "MSOS": "Health Care", "UCO": "Energy",
    "ETHU": "Digital Assets", "FBTC": "Digital Assets", "FETH": "Digital Assets",
    "BITW": "Digital Assets",
    "FDCPX": "Technology", "FMKT": "Index",
    "SPAXX": "Cash", "FDRXX": "Cash",
    "SOXX": "Technology", "SMH": "Technology", "BOT": "Technology", "ARKX": "Industrials",
    "ITA": "Industrials", "GRID": "Industrials", "PAVE": "Industrials",
    "URA": "Energy", "XLE": "Energy", "XLU": "Utilities", "DTCR": "Real Estate",
    "XLK": "Technology", "XLF": "Financials", "XLV": "Health Care", "XLI": "Industrials",
}

# Broad funds are spread across sectors rather than dropped whole into one
# "Index" bucket, because the question the Sectors tab answers is how much of
# the BOOK is in technology, and a third of it held through QQQ is still in
# technology. The weights are static approximations from the funds' own
# published breakdowns as of mid-2026, rounded to whole percents, and are
# labelled as such wherever they are used; there is no free daily source for
# them. Leveraged funds follow their index. Anything not listed here keeps the
# whole-fund sector from FUND_SECTORS.
FUND_LOOKTHROUGH_ASOF = "2026-06"
FUND_LOOKTHROUGH: dict[str, dict[str, float]] = {
    "SPY": {"Technology": 0.33, "Financials": 0.13, "Consumer Discretionary": 0.10,
            "Communication Services": 0.10, "Health Care": 0.09, "Industrials": 0.08,
            "Consumer Staples": 0.05, "Energy": 0.03, "Utilities": 0.03,
            "Real Estate": 0.02, "Materials": 0.02, "Cash": 0.02},
    "QQQ": {"Technology": 0.52, "Communication Services": 0.16, "Consumer Discretionary": 0.13,
            "Health Care": 0.05, "Consumer Staples": 0.04, "Industrials": 0.04,
            "Utilities": 0.01, "Financials": 0.01, "Materials": 0.01, "Energy": 0.01,
            "Real Estate": 0.01, "Cash": 0.01},
    "IWM": {"Financials": 0.18, "Industrials": 0.17, "Health Care": 0.16, "Technology": 0.14,
            "Consumer Discretionary": 0.10, "Real Estate": 0.06, "Energy": 0.05,
            "Materials": 0.04, "Utilities": 0.03, "Communication Services": 0.03,
            "Consumer Staples": 0.03, "Cash": 0.01},
    "DIA": {"Financials": 0.24, "Technology": 0.20, "Health Care": 0.15, "Consumer Discretionary": 0.14,
            "Industrials": 0.13, "Consumer Staples": 0.06, "Communication Services": 0.03,
            "Materials": 0.02, "Energy": 0.02, "Cash": 0.01},
    "SCHD": {"Energy": 0.20, "Consumer Staples": 0.19, "Health Care": 0.15, "Industrials": 0.13,
             "Technology": 0.09, "Financials": 0.09, "Consumer Discretionary": 0.08,
             "Communication Services": 0.04, "Materials": 0.02, "Cash": 0.01},
}
for _lev, _base in (("QLD", "QQQ"), ("TQQQ", "QQQ"), ("FMKT", "SPY"), ("EUSA", "SPY")):
    FUND_LOOKTHROUGH[_lev] = FUND_LOOKTHROUGH[_base]

_TICKER_INDEX: dict[str, int] | None = None


def _get(url: str) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=user_agent()), timeout=30).read()


def _narrowest_first(table):
    """Sort ranges so a narrow band always beats the broad one containing it.

    sector_for_sic returns the FIRST match, so ordering is the whole
    classification. Prepending one range fixed pharma and left the identical bug
    everywhere else: SIC 3812, Search/Detection/Navigation — L3Harris, Kratos and
    most defence electronics — fell inside a broad 3800-3851 Health Care band,
    and 3760, guided missiles and space vehicles, inside the automotive one.
    Sorting by width means adding a range can no longer be shadowed by an older,
    wider one.
    """
    return sorted(table, key=lambda r: (r[0][1] - r[0][0], r[0][0]))


# Ordered once at import: narrow ranges before the broad ones containing them.
_SIC_BY_WIDTH = None


def sector_for_sic(sic: int | None) -> str:
    global _SIC_BY_WIDTH
    if _SIC_BY_WIDTH is None:
        _SIC_BY_WIDTH = _narrowest_first(SIC_RANGES)
    if not sic:
        return "Unknown"
    for (lo, hi), name in _SIC_BY_WIDTH:
        if lo <= sic <= hi:
            return name
    return "Unknown"


def ticker_index(force: bool = False) -> dict[str, int]:
    global _TICKER_INDEX
    if _TICKER_INDEX is None or force:
        data = json.loads(_get(SEC_TICKERS))
        _TICKER_INDEX = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
    return _TICKER_INDEX


def ensure_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS security_meta (
        symbol TEXT PRIMARY KEY, cik INTEGER, name TEXT, sic INTEGER,
        sic_description TEXT, sector TEXT, source TEXT, note TEXT,
        fetched_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(security_meta)")}
    if "note" not in cols:
        conn.execute("ALTER TABLE security_meta ADD COLUMN note TEXT")


def classify(conn, symbols: list[str], refresh: bool = False) -> dict:
    """Look up and cache the sector for each symbol. One SEC call per new name."""
    ensure_schema(conn)
    have = {r["symbol"] for r in conn.execute("SELECT symbol FROM security_meta")}
    todo = [s for s in symbols if refresh or s.upper() not in have]
    index, done, failed = None, 0, []

    for sym in todo:
        s = sym.upper()
        if s in FUND_SECTORS:
            conn.execute("""INSERT OR REPLACE INTO security_meta
                (symbol, sector, source, note) VALUES (?,?,?,?)""",
                (s, FUND_SECTORS[s], "fund", "ETF or fund; does not file a SIC code"))
            done += 1
            continue
        if s in SECTOR_ETFS:
            conn.execute("""INSERT OR REPLACE INTO security_meta
                (symbol, name, sector, source) VALUES (?,?,?,?)""",
                (s, f"SPDR {SECTOR_ETFS[s]}", SECTOR_ETFS[s], "etf"))
            done += 1
            continue
        if s in SIC_OVERRIDES and s not in {x["symbol"] for x in
                conn.execute("SELECT symbol FROM security_meta WHERE source='sec'")}:
            sector, note = SIC_OVERRIDES[s]
            conn.execute("""INSERT OR REPLACE INTO security_meta
                (symbol, sector, source, note) VALUES (?,?,?,?)""",
                (s, sector, "override", note))
            done += 1
            continue
        if index is None:
            try:
                index = ticker_index()
            except Exception as exc:                       # noqa: BLE001
                return {"error": f"SEC ticker map unavailable: {type(exc).__name__}", "done": done}
        cik = index.get(s)
        if not cik:
            conn.execute("""INSERT OR REPLACE INTO security_meta (symbol, sector, source)
                            VALUES (?,?,?)""", (s, "Unknown", "not-in-edgar"))
            failed.append(s)
            continue
        try:
            sub = json.loads(_get(SEC_SUBMISSIONS.format(cik=cik)))
        except Exception:                                  # noqa: BLE001
            failed.append(s)
            continue
        sic = int(sub.get("sic") or 0) or None
        sector, source = sector_for_sic(sic), "sec"
        note = None
        if s in SIC_OVERRIDES:
            sector, note = SIC_OVERRIDES[s]
            source = "override"
        conn.execute("""INSERT OR REPLACE INTO security_meta
            (symbol, cik, name, sic, sic_description, sector, source, note)
            VALUES (?,?,?,?,?,?,?,?)""",
            (s, cik, sub.get("name"), sic,
             (sub.get("sicDescription") or "") + (f" — reclassified: {note}" if note else ""),
             sector, source, note))
        done += 1
    return {"classified": done, "unmapped": failed, "requested": len(symbols)}


def lookup(conn, symbols: list[str]) -> dict[str, dict]:
    ensure_schema(conn)
    out = {}
    for r in conn.execute("SELECT * FROM security_meta"):
        if r["symbol"] in {s.upper() for s in symbols}:
            out[r["symbol"]] = dict(r)
    return out


def exposure(conn, positions: list[dict]) -> list[dict]:
    """Portfolio weight by sector — the concentration view that matters most."""
    meta = lookup(conn, [p["symbol"] for p in positions])
    total = sum(p["value"] or 0 for p in positions) or 1.0
    buckets: dict[str, dict] = {}

    def add(sec, value, symbol, via=None):
        b = buckets.setdefault(sec, {"sector": sec, "value": 0.0, "symbols": [], "via_funds": []})
        b["value"] += value
        if via:
            if via not in b["via_funds"]:
                b["via_funds"].append(via)
        elif symbol not in b["symbols"]:
            b["symbols"].append(symbol)

    spread = []
    for p in positions:
        if not p.get("value"):
            continue
        sym = p["symbol"]
        look = FUND_LOOKTHROUGH.get(sym)
        if look:
            spread.append(sym)
            for sec, share in look.items():
                add(sec, p["value"] * share, sym, via=sym)
            continue
        sec = (meta.get(sym) or {}).get("sector") or "Unknown"
        add(sec, p["value"], sym)
    rows = [{**b, "weight": b["value"] / total, "value": round(b["value"], 2)}
            for b in buckets.values()]
    rows.sort(key=lambda r: -r["value"])
    if spread:
        for r in rows:
            r["lookthrough_note"] = (f"{', '.join(sorted(spread))} spread across sectors by static "
                                     f"weights as of {FUND_LOOKTHROUGH_ASOF}")
    return rows


def _ret(series: dict[str, float], dates: list[str], days: int) -> float | None:
    if not dates:
        return None
    end = dates[-1]
    idx = max(0, len(dates) - 1 - days)
    p0, p1 = series.get(dates[idx]), series.get(end)
    return (p1 / p0 - 1.0) if p0 and p1 else None


def rotation(conn, windows=(21, 63, 126, 252)) -> dict:
    """Relative strength of each sector ETF against the market, over several windows.

    Several windows because leadership that is one month old and leadership that
    is six months old mean different things — the first is a trade, the second
    is a trend, and a sector showing both is the only one worth calling rotation.
    """
    return relative_strength(conn, SECTOR_ETFS, windows, key="sector")


def relative_strength(conn, funds: dict[str, str], windows=(21, 63, 126, 252),
                      key: str = "sector") -> dict:
    """The rotation table for any {symbol: label} map of funds.

    Written once so the theme funds — space, quantum, nuclear — are measured
    the same way as the eleven sectors, rather than with a second copy of the
    arithmetic that could drift.
    """
    for sym in [MARKET, *funds]:
        prices.ensure_symbol(conn, sym, "2018-01-01", "2030-01-01", as_equity=True)
    conn.commit()

    mkt = prices.load_series(conn, MARKET)
    mkt_dates = prices.sorted_dates(conn, MARKET)
    if not mkt_dates:
        return {"error": "no market data"}

    rows = []
    for sym, name in funds.items():
        series = prices.load_series(conn, sym)
        dates = prices.sorted_dates(conn, sym)
        if not dates:
            continue
        rel, abs_ = {}, {}
        for w in windows:
            r_sec = _ret(series, dates, w)
            r_mkt = _ret(mkt, mkt_dates, w)
            abs_[w] = r_sec
            rel[w] = (r_sec - r_mkt) if (r_sec is not None and r_mkt is not None) else None
        vals = [v for v in rel.values() if v is not None]
        rows.append({"symbol": sym, key: name,
                     "absolute": abs_, "relative": rel,
                     "score": sum(vals) / len(vals) if vals else None,
                     # Leading on both the short and the long window is the
                     # configuration that actually reads as rotation.
                     "persistent": all((rel.get(w) or 0) > 0 for w in windows)})
    rows.sort(key=lambda r: -(r["score"] if r["score"] is not None else -9))
    return {"windows": list(windows), "market": MARKET, "sectors": rows,
            "as_of": mkt_dates[-1] if mkt_dates else None}


def set_sector(conn, symbol: str, sector: str, note: str = "manual") -> dict:
    """Let the user correct a classification. Their knowledge beats a filing code."""
    ensure_schema(conn)
    conn.execute("""INSERT INTO security_meta (symbol, sector, source, note)
                    VALUES (?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      sector=excluded.sector, source='manual', note=excluded.note""",
                 (symbol.upper(), sector, "manual", note))
    return {"symbol": symbol.upper(), "sector": sector}
