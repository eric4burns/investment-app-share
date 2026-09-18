"""Supply-chain theses: why a group of names might re-rate, and what would kill it.

The other artifact types all start from a chart. A thesis starts from a physical
constraint — a factory that can only make one thing at a time, a material with
one supplier — and argues that the constraint has to show up in somebody's
margins eventually. It says nothing about when, which is exactly why it is kept
separate from setups and methods rather than folded into them: a thesis tells
you what to watch, a setup tells you when.

Every thesis here carries a falsifier. A supply-chain argument that cannot be
wrong is a story, and the failure mode is holding one long after the constraint
it depended on has quietly gone away.
"""

THESES = {
    "legacy-memory-squeeze": {
        "name": "Legacy memory squeeze",
        "attribution": "Serenity (@aleabitoreddit)",
        "confidence": "stated",
        "as_of": "2026-08",
        "claim":
            "High-bandwidth memory demand pulled the large memory makers' capacity "
            "away from older DRAM and NAND, and the customers who still need the "
            "old parts have almost nowhere else to buy them. The squeeze shows up "
            "not at the leaders but at whoever still runs the legacy lines.",
        "mechanism": [
            "NVIDIA buys HBM in quantity and pays for it, so HBM is the most "
            "profitable thing a memory fab can produce.",
            "Micron, SK Hynix and Samsung converted capacity toward it. That "
            "conversion is the whole event — supply left the legacy segments "
            "because it was worth more elsewhere, not because demand fell.",
            "Demand for legacy parts did not go anywhere. Industrial, automotive "
            "and embedded designs are qualified around specific old parts and "
            "cannot re-spec quickly.",
            "So the remaining legacy suppliers price into a shortage, and the "
            "constraint pushes one step upstream to the foundries that make the "
            "wafers for them.",
            "The upstream supplier can raise prices too, but by less than the "
            "finished part rises — which is why the margin lands in the middle of "
            "the chain rather than at either end.",
        ],
        "chain": [
            {"role": "demand sink", "names": ["NVDA"],
             "note": "buys HBM, sets the opportunity cost for every fab"},
            {"role": "converted capacity", "names": ["MU"],
             "note": "plus SK Hynix and Samsung, neither US-listed"},
            {"role": "legacy supplier", "names": ["ESMT"],
             "note": "Taiwan 3006 — SLC/SPI NAND, NOR flash, DDR2/DDR3, MCP/eMCP. "
                     "Not reachable from a US brokerage account and no free daily "
                     "history here, so it can be read about but not held or charted."},
            {"role": "upstream foundry", "names": ["PSMC"],
             "note": "Taiwan 6770 — same access problem"},
            {"role": "US-listed proxy", "names": ["SNDK", "WDC", "STX"],
             "note": "NAND and storage exposure that IS reachable, but none is a "
                     "clean read on the legacy squeeze — they carry leading-edge "
                     "and drive businesses alongside it"},
        ],
        "quotes": [
            "\"A potato farmer $MU, that was selling carrots... now shifted farmland "
            "to potatos.\" (her analogy: potatoes are HBM, carrots are legacy memory)",
            "\"now there's no more carrots aside from a player like 'ESMT', the "
            "legacy carrot farmer. So now, because everyone buys carrots off ESMT, "
            "there's a shortage and the price goes up.\"",
            "\"the price ESMT sells the carrots at are much higher than what PSMC "
            "hikes the carrot seed price\"",
            "\"ESMT is making enough from selling carrots that it traded 1.9x P/E "
            "off July's earnings\"",
            "\"All the other farmers thinks so since it's both hard + low incentive "
            "to migrate their valuable potato farms back to carrot farms\" (on "
            "whether it holds through 2027)",
        ],
        "falsifiers": [
            "Capacity migrating back to legacy nodes. She names this as the load-"
            "bearing assumption herself — the thesis lasts exactly as long as "
            "converting back stays unattractive.",
            "HBM demand cooling, which frees the converted capacity and removes the "
            "opportunity cost holding legacy supply off the market.",
            "Legacy customers re-qualifying around newer parts. Slow, but it is the "
            "structural end of the squeeze rather than a pause in it.",
            "The price hikes appearing in headlines but not in the suppliers' "
            "realised margins, which would mean the increases are being absorbed "
            "rather than passed on.",
        ],
        "caveats": [
            "A 1.9x P/E is a claim about trailing earnings at a cycle peak, not a "
            "valuation argument. Peak-cycle semiconductor earnings routinely support "
            "very low multiples precisely because the market expects them to fall.",
            "The two names at the centre of the thesis are Taiwan-listed and out of "
            "reach here, so acting on it means holding a proxy that is only partly "
            "exposed to it.",
            "Second-hand price-hike figures (SLC NAND up 120-170%) come from another "
            "account she cites, not from her own work.",
        ],
    },
}


def exposure(conn, key: str, end: str) -> dict:
    """Where a thesis touches the actual book and watchlist.

    A thesis with no reachable exposure is still worth recording — it explains
    moves in names that ARE held — so this reports the gap rather than hiding it.
    """
    from . import holdings, performance, watchlist

    spec = THESES.get(key)
    if not spec:
        return {"error": f"unknown thesis {key!r}"}

    txns = performance.load_transactions(conn, "1900-01-01", end, "investment")
    held = {p["symbol"]: p for p in holdings.positions(conn, txns, end)}
    try:
        listed = {r["symbol"] for r in watchlist.rows(conn, end)}
    except Exception:                                           # noqa: BLE001
        listed = set()

    # holdings.positions() emits "value"; reading "market_value" made total 0 and
    # every weight None, silently, on every row.
    rows, total = [], sum(p.get("value") or 0 for p in held.values())
    for link in spec["chain"]:
        for sym in link["names"]:
            pos = held.get(sym)
            rows.append({
                "symbol": sym, "role": link["role"], "note": link["note"],
                "held": bool(pos),
                "weight": (round((pos["value"] or 0) / total * 100, 2)
                           if pos and total else None),
                "watchlist": sym in listed,
            })
    return {"key": key, "name": spec["name"], "attribution": spec["attribution"],
            "claim": spec["claim"], "mechanism": spec["mechanism"],
            "quotes": spec["quotes"], "falsifiers": spec["falsifiers"],
            "caveats": spec["caveats"], "as_of": spec["as_of"], "links": rows,
            "held_count": sum(1 for r in rows if r["held"]),
            "watchlist_count": sum(1 for r in rows if r["watchlist"] and not r["held"])}


def catalogue() -> list[dict]:
    return [{"key": k, "name": v["name"], "attribution": v["attribution"],
             "confidence": v["confidence"], "as_of": v["as_of"], "claim": v["claim"]}
            for k, v in THESES.items()]
