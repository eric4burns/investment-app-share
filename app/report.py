"""Performance report.

    python3 -m app.report --from 2025-09-01 --to 2026-08-28 --benchmarks SPY,QQQ
    python3 -m app.report --scope taxable --benchmarks SPY
    python3 -m app.report --scope "Individual - TOD" --from 2026-01-01

--scope takes 'investment' (default, all investment accounts), 'taxable',
'all', or an exact account name.
"""
from __future__ import annotations

import argparse
import sys

from .ledger import connect
from . import performance, prices


def pct(x: float | None) -> str:
    return "     n/a" if x is None else f"{x * 100:+7.2f}%"


def money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.2f}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.report")
    p.add_argument("--from", dest="start", default=None, help="YYYY-MM-DD (default: earliest txn)")
    p.add_argument("--to", dest="end", default=None, help="YYYY-MM-DD (default: latest txn)")
    p.add_argument("--scope", default="investment")
    p.add_argument("--benchmarks", default="SPY,QQQ")
    p.add_argument("--sync", action="store_true", help="refresh benchmark data first")
    args = p.parse_args(argv)

    conn = connect()
    names = [b.strip() for b in args.benchmarks.split(",") if b.strip()]

    if args.sync:
        for n in names:
            r = prices.sync_benchmark(conn, n)
            print(f"  benchmark {n}: {'ok' if r['ok'] else r.get('error')}")
        if prices.alpaca_credentials():
            h = prices.sync_holdings(conn, "2024-01-01", args.end or "2030-01-01")
            print(f"  holdings: priced {len(h['priced'])}, "
                  f"skipped {len(h['skipped'])}, no feed {len(h['failed'])}")
            for sym in h["failed"]:
                print(f"    no feed: {sym}")
        else:
            print("  holdings: skipped (no Alpaca credentials in data/.alpaca)")
        conn.commit()

    bounds = conn.execute("SELECT MIN(txn_date) a, MAX(txn_date) b FROM transactions").fetchone()
    start = args.start or bounds["a"]
    end = args.end or bounds["b"]

    r = performance.analyse(conn, start, end, args.scope, names)

    if r.get("start_clamped"):
        print(f"\n  (range adjusted: {r['scope']} has no activity before {r['start']})")
    print(f"\n  {r['start']}  ->  {end}      scope: {r['scope']}      {r['transactions']} transactions")
    print("  " + "-" * 66)
    print(f"  {'Beginning value':<26} {money(r['begin_value']):>18}")
    print(f"  {'Ending value':<26} {money(r['end_value']):>18}")
    print(f"  {'Net deposits/withdrawals':<26} {money(r['net_external_flow']):>18}"
          f"   ({r['flow_events']} events)")
    print()
    if r["complete"]:
        print(f"  {'Time-weighted return':<26} {pct(r['twr']):>18}   <- comparable to an index")
        print(f"  {'Modified Dietz':<26} {pct(r['modified_dietz']):>18}")
        if r.get("skipped_subperiods"):
            print(f"\n  ({r['skipped_subperiods']} early sub-periods DROPPED — the account's value")
            print( "   was too small to divide by. Those periods are not in the figure above.)")
    else:
        print(f"  {'Time-weighted return':<26} {'WITHHELD':>18}")
        print(f"  {'Modified Dietz':<26} {'WITHHELD':>18}")
        if not r.get("anchored", True):
            print("\n  Returns are withheld because the OPENING PORTFOLIO IS UNKNOWN.")
            print(f"  Beginning value reads as {money(r['begin_value'])} against "
                  f"{money(r['net_external_flow'])} of net deposits, which means")
            print( "  positions opened before the ledger's first transaction are invisible.")
            print( "  Any return computed from this would be meaningless, not merely rough.")
            print(f"  The requested start ({r['start']}) is before the first transaction on")
            print(f"  record for this scope ({r.get('first_transaction')}), so any holding")
            print( "  opened earlier would be invisible and the opening value would read as")
            print( "  zero. Start the report at or after that date, or backfill more history.")
        else:
            print(f"\n  Returns are withheld because price coverage is "
                  f"{r['priced_securities']}/{r['held_securities']} holdings "
                  f"({r['price_coverage']*100:.0f}%).")
            print( "  An unpriced holding counts as zero, which would not make these numbers")
            print( "  imprecise — it would make them wrong while still looking like plausible")
            print( "  percentages. Better to show nothing than something misreadable.")

    if r["benchmarks"] and r["complete"]:
        print("\n  Benchmarks")
        print("  " + "-" * 66)
        for b in r["benchmarks"]:
            if b.get("error"):
                print(f"  {b['symbol']:<26} {b['error']}")
                continue
            print(f"  {b['label']}")
            print( "    time-weighted  (ignores when you added money)")
            print(f"      {'index':<22} {pct(b['return']):>18}")
            print(f"      {'you':<22} {pct(r['twr']):>18}")
            if b.get("tw_delta") is not None:
                print(f"      {'-> difference':<22} {pct(b['tw_delta']):>18}   "
                      f"{'ahead' if b['tw_delta'] > 0 else 'behind'}  (selection)")
            print( "    money-weighted (accounts for when you added money)")
            print(f"      {'same deposits ->':<22} {pct(b.get('mw_benchmark')):>18}   "
                  f"{money(b['same_cashflow']['final_value']) if b.get('same_cashflow') else ''}")
            print(f"      {'you':<22} {pct(b.get('mw_you')):>18}   {money(r['end_value'])}")
            if b.get("mw_delta") is not None:
                print(f"      {'-> difference':<22} {pct(b['mw_delta']):>18}   "
                      f"{'ahead' if b['mw_delta'] > 0 else 'behind'}  "
                      f"({money(abs(b['dollar_delta']))})")
            if b.get("timing_disagrees"):
                print( "      NOTE: the two disagree. Your picks beat the index over the same")
                print( "      days, but more of your money was invested during the weaker")
                print( "      stretch, so the index ends with more dollars.")
            print(f"  {'':26} {b['caveat']}")

    elif r["benchmarks"]:
        print("\n  Benchmark comparison also withheld until holdings can be priced.")

    if r.get("at_cost_accounts"):
        print(f"\n  !! {money(r['at_cost_total'])} is held in account(s) that report no ticker,")
        print( "     so it is valued at CONTRIBUTIONS AT COST and never moves with the market:")
        for a in r["at_cost_accounts"]:
            print(f"       {a['account']:<36} {money(a['value']):>14}")

    if r.get("stale_valued"):
        share = r["stale_share_of_value"] * 100
        print(f"\n  Note: {len(r['stale_valued'])} holding(s) have no market feed (OTC) and are")
        print(f"  valued at the price you last traded them — {money(r['stale_value_total'])}, "
              f"{share:.1f}% of the portfolio.")
        for sym, val in sorted(r["stale_valued"].items(), key=lambda kv: -kv[1]):
            print(f"    {sym:<10} {money(val):>14}")

    if r["missing_prices"]:
        n = len(r["missing_prices"])
        print(f"\n  Missing prices for {n} holdings:")
        print(f"    {', '.join(r['missing_prices'][:14])}{' ...' if n > 14 else ''}")
        print( "    Fix: free Alpaca paper account (email only, no SSN, no funding),")
        print( "    then put the key id and secret on two lines in data/.alpaca")
    conn.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
