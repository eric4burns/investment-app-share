"""Rebuild the daily price cache from the consolidated feed, and audit what changed.

    python3 -m app.refeed snapshot before.json      # what the app says NOW
    python3 -m app.refeed run                        # replace IEX bars with SIP bars
    python3 -m app.refeed snapshot after.json
    python3 -m app.refeed compare before.json after.json > logs/refeed-2026-09-02.md

## Why this exists

Every daily bar in the cache came from Alpaca's IEX feed, which is one
exchange. On thinly traded names it saw a handful of shares a day and, on the
days it saw none, emitted a placeholder bar — zero volume, one flat price —
that flickered against the real prints. See `prices.ALPACA_FEED` for the case
that exposed it. The consolidated feed is available on the same free plan for
anything older than fifteen minutes, so the cache is rebuilt from it.

## Why the audit is not optional

A price series is the input to every finding on the Diagnose tab, every
figure on the Risk tab and every verdict the app has recorded. Changing it
silently would leave no way to tell which of yesterday's conclusions were
about the market and which were about the feed. So the same readings are taken
before and after, and the differences are written down — what the position
risk shares were, what each name's give-back was, what every verdict said —
so that anyone reading a call recorded before the switch knows it was made on
the old data, and by how much the new data disagrees.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import diagnose, holdings, outlook, performance, prices, risk
from .ledger import connect


def snapshot(conn, asof: str | None = None) -> dict:
    """The readings most exposed to the feed, in one document."""
    asof = asof or date.today().isoformat()
    txns = performance.load_transactions(conn, "1900-01-01", asof, "investment")
    pos = holdings.positions(conn, txns, asof)
    summary = performance.analyse(conn, "2024-06-07", asof, "investment", ["SPY"])
    start = summary["start"]
    dates = diagnose._grid(start, asof)
    conc = risk.concentration(conn, pos, dates)
    moves = risk.position_moves(conn, pos, asof)
    dx = diagnose.diagnose(conn, start, asof, "investment")
    ol = outlook.run(conn, asof, dry_run=True, scope="all")

    return {
        "asof": asof,
        "bars": {r["source"]: r["n"] for r in conn.execute(
            "SELECT source, COUNT(*) n FROM prices GROUP BY source")},
        "placeholders": conn.execute(
            """SELECT COUNT(*) FROM prices WHERE (volume IS NULL OR volume = 0)
                  AND open = close AND high = low AND source LIKE 'alpaca%'""").fetchone()[0],
        "concentration": {r["symbol"]: {"risk_share": r["risk_share"], "volatility": r["volatility"],
                                        "volatility_held": r["volatility_held"]}
                          for r in conc.get("rows", [])},
        "effective_holdings": conc.get("effective_holdings"),
        "moves": {m["symbol"]: {"peak": m["peak"], "peak_date": m["peak_date"],
                                "from_peak": m["from_peak"], "given_back_usd": m["given_back_usd"],
                                "all_time_high": m["all_time_high"]}
                  for m in moves},
        "findings": [f["headline"] for f in dx.get("findings", [])],
        "verdicts": {sym: {tf: (r.get(tf) or {}).get("verdict") for tf in ("daily", "weekly", "monthly")}
                     for sym, r in (ol.get("results") or {}).items()},
    }


def compare(before: dict, after: dict) -> str:
    """A markdown record of what the switch changed."""
    out = [f"# Price feed switch — {after['asof']}", "",
           "Daily bars rebuilt from Alpaca's consolidated (SIP) feed in place of IEX. "
           "Readings below were taken on the same day, before and after.", "",
           "## Cache", "",
           f"- Before: {before['bars']}, {before['placeholders']} placeholder bars",
           f"- After: {after['bars']}, {after['placeholders']} placeholder bars", ""]

    out += ["## Risk share by position", "",
            "| Symbol | Risk share before | after | Volatility before | after |", "|---|---|---|---|---|"]
    for sym in sorted(set(before["concentration"]) | set(after["concentration"]),
                      key=lambda s: -(after["concentration"].get(s, {}).get("risk_share") or 0)):
        b, a = before["concentration"].get(sym, {}), after["concentration"].get(sym, {})
        pct = lambda v: "—" if v is None else f"{v*100:.0f}%"
        out.append(f"| {sym} | {pct(b.get('risk_share'))} | {pct(a.get('risk_share'))} "
                   f"| {pct(b.get('volatility'))} | {pct(a.get('volatility'))} |")
    out += ["", f"Effective holdings: {before.get('effective_holdings')} → {after.get('effective_holdings')}", ""]

    out += ["## Give-back by position (peak while held)", "",
            "| Symbol | Peak before | after | From peak before | after | Given back $ after |",
            "|---|---|---|---|---|---|"]
    for sym in sorted(set(before["moves"]) | set(after["moves"])):
        b, a = before["moves"].get(sym, {}), after["moves"].get(sym, {})
        if b == a:
            continue
        pct = lambda v: "—" if v is None else f"{v*100:.0f}%"
        out.append(f"| {sym} | {b.get('peak')} ({b.get('peak_date')}) | {a.get('peak')} ({a.get('peak_date')}) "
                   f"| {pct(b.get('from_peak'))} | {pct(a.get('from_peak'))} | {a.get('given_back_usd')} |")

    out += ["", "## Diagnose findings", "", "Before:"] + [f"- {h}" for h in before["findings"]] \
        + ["", "After:"] + [f"- {h}" for h in after["findings"]] + [""]

    out += ["## Verdicts that changed", "", "| Symbol | Timeframe | Before | After |", "|---|---|---|---|"]
    changed = 0
    for sym in sorted(set(before["verdicts"]) | set(after["verdicts"])):
        for tf in ("daily", "weekly", "monthly"):
            b = before["verdicts"].get(sym, {}).get(tf)
            a = after["verdicts"].get(sym, {}).get(tf)
            if b != a:
                changed += 1
                out.append(f"| {sym} | {tf} | {b} | {a} |")
    total = sum(1 for s in after["verdicts"].values() for v in s.values() if v)
    out += ["", f"{changed} of {total} readings changed.", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.refeed")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("path"); s.add_argument("--asof")
    r = sub.add_parser("run"); r.add_argument("--symbol", action="append", dest="symbols")
    c = sub.add_parser("compare"); c.add_argument("before"); c.add_argument("after")
    args = p.parse_args(argv)

    if args.cmd == "snapshot":
        conn = connect()
        doc = snapshot(conn, args.asof)
        with open(args.path, "w") as fh:
            json.dump(doc, fh, indent=1)
        print(f"snapshot of {doc['asof']}: {len(doc['verdicts'])} names, "
              f"{len(doc['findings'])} findings, {doc['placeholders']} placeholder bars -> {args.path}")
        return 0
    if args.cmd == "run":
        conn = connect()
        res = prices.refeed(conn, args.symbols, log=print)
        print(f"\nrefed {len(res['refed'])}, untouched {len(res['untouched'])}, failed {len(res['failed'])}")
        for sym, why in res["failed"].items():
            print(f"  failed {sym}: {why}")
        return 1 if res["failed"] else 0
    if args.cmd == "compare":
        print(compare(json.load(open(args.before)), json.load(open(args.after))))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
