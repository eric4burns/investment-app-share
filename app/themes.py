"""Themes — the granular layer sectors cannot express.

GICS sectors put a satellite operator, a bank and a payments processor in the
same bucket, and split a nuclear SMR developer from the utility that will buy
its output. Nobody trades "Financials"; people trade space, critical minerals,
neoclouds, quantum, nuclear. Themes are how the portfolio is actually
constructed, so they are how it should be measured.

A symbol can carry several themes at once — IREN is both a neocloud and a
bitcoin miner, and both are true — so this is many-to-many rather than a second
single-valued classification.

The seed map below is curated, not derived. There is no free feed for "which
companies are neoclouds", and a wrong automatic answer would be worse than an
explicit hand-made one that can be corrected. Everything is editable and the
UI treats these as ordinary watchlist tags.
"""
from __future__ import annotations

THEMES: dict[str, dict] = {
    "space": {
        "label": "Space & satellites",
        "symbols": ["RKLB", "ASTS", "LUNR", "RDW", "SATL", "SIDU", "PL", "SPCX", "VSAT", "OPTT", "KTOS", "LHX", "BKSY", "MNTS"],
    },
    "critical-minerals": {
        "label": "Critical minerals & rare earths",
        "symbols": ["MP", "USAR", "TMC", "ABAT", "SBSW", "COPX", "LAC", "ALB", "UEC", "LEU", "NB", "IPX", "TRLV"],
    },
    "neocloud": {
        "label": "Neoclouds & AI datacentres",
        "symbols": ["CRWV", "NBIS", "APLD", "IREN", "WULF", "GPUS", "CIFR", "DGXX", "HUT", "CORZ", "GLXY", "SLNH", "BTBT"],
    },
    "ai-semis": {
        "label": "AI semiconductors",
        "symbols": ["NVDA", "AMD", "AVGO", "MRVL", "SMCI", "CRDO", "ASML", "QRVO", "AEHR", "GSIT", "INTC", "SNDK",
                    "ALAB", "ANET"],
    },
    "photonics": {
        "label": "Photonics & optical",
        "symbols": ["LASR", "AAOI", "LITE", "POET", "IQE.L", "AXTI", "LWLG", "INFN", "KOPN", "VUZI",
                    "COHR", "FN", "CIEN", "SIVEF"],
    },
    "memory": {
        "label": "Memory & storage",
        "symbols": ["MU", "SNDK", "WDC", "STX", "SIMO", "PSTG"],
    },
    "defense-drones": {
        "label": "Defence & drones",
        "symbols": ["KTOS", "AVAV", "RCAT", "ONDS", "LHX", "DPRO"],
    },
    "quantum": {
        "label": "Quantum computing",
        "symbols": ["IONQ", "RGTI", "QBTS", "QUBT", "NUAI"],
    },
    "nuclear-power": {
        "label": "Nuclear & power",
        "symbols": ["OKLO", "SMR", "LEU", "VST", "PCG", "FLNC", "EOSE", "TE",
                    "CEG", "TLN", "GEV", "NRG", "BWXT", "CCJ", "NNE"],
    },
    "autonomy": {
        "label": "Autonomy, lidar & robotics",
        "symbols": ["AEVA", "OUST", "MBLY", "SERV", "TSLA", "JOBY", "KITT", "DPRO", "ONDS", "SYM", "RR", "STRL"],
    },
    "digital-assets": {
        "label": "Digital assets & treasuries",
        "symbols": ["MSTR", "BMNR", "HOOD", "GLXY", "BITW", "FBTC", "FETH", "ETHU", "BKKT", "ASST", "DJT"],
    },
    "biotech": {
        "label": "Biotech & medtech",
        "symbols": ["TEM", "ABCL", "IBRX", "TMDX", "CCXI", "SLS", "KLRA", "ADUR", "OSCR", "UNH", "VIVO"],
    },
    "fintech": {
        "label": "Fintech & consumer finance",
        "symbols": ["SOFI", "PGY", "NU", "PYPL", "ROOT", "LMND", "REAX", "OPEN"],
    },
    "software-ai": {
        "label": "Software & AI platforms",
        "symbols": ["PLTR", "MSFT", "GOOG", "META", "AMZN", "ORCL", "NFLX", "ESTC", "RBRK", "PATH", "DUOL", "ZETA", "SOUN", "FICO", "EFX", "BKNG", "GRAB", "UBER", "RXT", "HPE", "VRT"],
    },
    "index": {
        "label": "Index & broad ETFs",
        "symbols": ["SPY", "QQQ", "IWM", "QLD", "TQQQ", "SCHD", "EUSA", "MSOS"],
    },
    "metals": {
        "label": "Precious metals",
        "symbols": ["GLD", "SLV", "SBSW"],
    },
    "energy": {
        "label": "Energy",
        "symbols": ["PBR", "UCO", "TOP", "SOI.PA"],
    },
}

# symbol -> [theme keys]
_INDEX: dict[str, list[str]] | None = None


def index() -> dict[str, list[str]]:
    global _INDEX
    if _INDEX is None:
        idx: dict[str, list[str]] = {}
        for key, spec in THEMES.items():
            for sym in spec["symbols"]:
                idx.setdefault(sym.upper(), []).append(key)
        _INDEX = idx
    return _INDEX


def for_symbol(symbol: str) -> list[str]:
    return index().get((symbol or "").upper(), [])


# One liquid fund per theme, so "is space leading" is answerable the same way
# "is energy leading" is. Chosen by hand, and the fit is a judgement in a way
# the eleven sector funds are not: WGMI holds the bitcoin miners that the
# neocloud names mostly are, BITQ holds the crypto-industry equities rather
# than the coins. A theme with no reasonable fund (photonics) has none rather
# than a poor one. A wrong pick is one line to change.
THEME_ETFS: dict[str, str] = {
    "space": "UFO",               # Procure Space
    "critical-minerals": "REMX",  # VanEck Rare Earth and Strategic Metals
    "neocloud": "WGMI",           # CoinShares Bitcoin Mining
    "ai-semis": "SMH",            # VanEck Semiconductor
    "quantum": "QTUM",            # Defiance Quantum
    "defense-drones": "ITA",      # iShares U.S. Aerospace & Defense
    # "memory" has no fund of its own; the names are tracked directly.
    "nuclear-power": "NLR",       # VanEck Uranium and Nuclear
    "autonomy": "DRIV",           # Global X Autonomous and Electric Vehicles
    "digital-assets": "BITQ",     # Bitwise Crypto Industry Innovators
    "biotech": "XBI",             # SPDR S&P Biotech
    "fintech": "ARKF",            # ARK Fintech Innovation
    "software-ai": "IGV",         # iShares Expanded Tech-Software
    "metals": "GLD",              # SPDR Gold
    "energy": "XLE",              # SPDR Energy
}


def label(key: str) -> str:
    return THEMES.get(key, {}).get("label", key)


def rotation(conn, windows=(21, 63, 126, 252)) -> dict:
    """Relative strength of each theme's fund against the market."""
    from . import sectors
    funds = {sym: label(k) for k, sym in THEME_ETFS.items()}
    out = sectors.relative_strength(conn, funds, windows, key="theme")
    by_label = {label(k): k for k in THEME_ETFS}
    for row in out.get("sectors", []):
        row["key"] = by_label.get(row["theme"])
    out["themes"] = out.pop("sectors", [])
    return out


def exposure(conn, positions: list[dict]) -> list[dict]:
    """Portfolio weight by theme.

    Weights deliberately sum to MORE than 100% where a holding carries several
    themes — IREN counts in both neoclouds and digital assets, because that is
    genuinely how much of the book each theme touches. Forcing them to sum to
    100 would require splitting a position arbitrarily and would understate
    every overlapping exposure.
    """
    total = sum(p["value"] or 0 for p in positions) or 1.0
    buckets: dict[str, dict] = {}
    untagged = []
    for p in positions:
        if not p.get("value"):
            continue
        keys = for_symbol(p["symbol"])
        if not keys:
            untagged.append(p["symbol"])
            continue
        for k in keys:
            b = buckets.setdefault(k, {"theme": k, "label": label(k),
                                       "value": 0.0, "symbols": []})
            b["value"] += p["value"]
            b["symbols"].append(p["symbol"])
    rows = [{**b, "weight": b["value"] / total, "value": round(b["value"], 2)}
            for b in buckets.values()]
    rows.sort(key=lambda r: -r["value"])
    return rows, untagged


def tags_for_import(symbol: str) -> list[str]:
    """Themes as watchlist tags, so imported names arrive already organised."""
    return for_symbol(symbol)
