"""Import every data file in data/ into the ledger.

Safe to re-run at any time: every importer is idempotent, so dropping new
exports into data/ and running this again only ever adds what's new.

    python3 -m app.import_all
"""
from __future__ import annotations

import sys
from pathlib import Path

from .ledger import DB_PATH, ROOT, connect
from .importers import (budget_grid, card_csv, fidelity_csv, frost_ofx,
                        payroll_pdf, robinhood_csv)
from . import integrity, reconcile


def main() -> int:
    conn = connect()
    results = []

    for path in sorted((ROOT / "data" / "fidelity").glob("*.csv")):
        results.append(("Fidelity", fidelity_csv.import_file(conn, path), path))
    for path in sorted((ROOT / "data" / "bank").glob("*.ofx")):
        results.append(("Frost", frost_ofx.import_file(conn, path), path))
    # Robinhood: no API and no OFX, so an on-demand activity report is the only
    # export there is. Crypto and equities arrive in the same file.
    for path in sorted((ROOT / "data" / "robinhood").glob("*.csv")):
        results.append(("Robinhood", robinhood_csv.import_file(conn, path), path))
    # One importer for every card issuer, since no two agree on a format and
    # writing a new one per card does not scale past the second card.
    for path in sorted((ROOT / "data" / "cards").glob("*.csv")):
        results.append(("Card", card_csv.import_file(conn, path), path))
    # A hand-kept budget sheet is a reference series, not transactions. It is
    # stored apart from the ledger and never added to computed totals.
    for path in sorted((ROOT / "data" / "budget").glob("*.csv")):
        results.append(("Budget sheet", budget_grid.import_file(conn, path), path))
    # Pay stubs are a reference series too. They carry the three figures a bank
    # deposit cannot: gross wages, tax actually withheld, and how much of the
    # 401(k) was the employee's own deferral rather than the employer's match.
    for path in sorted((ROOT / "data" / "payroll").glob("*.pdf")):
        results.append(("Pay stub", payroll_pdf.import_file(conn, path), path))

    # A plan investment option has no ticker and no feed, but every one of its
    # transactions states units and dollars, so its NAV history is already in
    # the ledger and only needs reading out. Without this the L3Harris balance
    # sits at contributions-at-cost forever and never moves with the market.
    navs = fidelity_csv.store_plan_navs(conn)

    paired = reconcile.pair_internal_transfers(conn)
    conn.commit()

    if not results:
        print("No data files found under data/.")
        return 1

    print(f"{'file':<44} {'seen':>6} {'new':>6} {'dup':>6}")
    print("-" * 66)
    for label, r, path in results:
        print(f"{r['file']:<44} {r['seen']:>6} {r['inserted']:>6} {r['skipped']:>6}")
        if r.get("error"):
            print(f"  !! {r['file']}: {r['error']}")
        # How the sign convention was decided is printed for every card file.
        # Getting it backwards imports a year of spending as a year of income,
        # and the file looks entirely valid either way — so the basis is stated
        # rather than left to be discovered in a wrong total.
        elif r.get("sign"):
            weak = "assumed" in r["sign"]
            print(f"  {'!!' if weak else '  '} {r.get('account', '')}: sign from {r['sign']}")
        # A file that imported fewer rows than it appears to contain, or that
        # landed exactly on a provider's export cap. Neither is proof of a
        # problem, and neither was visible at all before: a truncated export
        # used to import quietly and leave a hole shaped exactly like a quiet
        # month.
        # The reference importers count cells and fields rather than rows, so
        # they get the cap and unparsed checks but not the record comparison.
        for warning in integrity.file_warnings(
                r, path, rows_are_transactions=label in ("Fidelity", "Frost", "Card", "Robinhood")):
            print(f"  !! {r['file']}: {warning}")

    if navs:
        print()
        for symbol, d in sorted(navs.items()):
            print(f"  {symbol:<30} {d['bars']:>3} NAVs  {d['first']} .. {d['last']}"
                  f"  latest {d['latest_nav']:,.4f}")

    if paired["created"]:
        print(f"\n  Paired {paired['created']} one-sided internal transfers "
              f"({paired['net_amount']:+,.2f} debited to the source plan).")
    if paired["unmapped_accounts"]:
        print(f"  !! Internal transfers with no known source plan: {paired['unmapped_accounts']}")
    for u in reconcile.audit_unpaired(conn):
        print(f"  !! Internal transfer still unbalanced: {u['net']:+,.2f} over "
              f"{u['rows']} rows — {u['description'][:50]}")

    unknown = set().union(*[r.get("unknown_accounts", set()) for _, r, _p in results])
    if unknown:
        print(f"\n!! Unmapped accounts (defaulted to brokerage/na): {sorted(unknown)}")

    # A whole month with no activity in a checking or credit account. Real life
    # does not do that, so it is the signature of an export that was never taken
    # or was silently clamped — which is exactly how $45,204 of card spending
    # stayed invisible until it was hunted down by hand.
    gaps = integrity.coverage_gaps(conn)
    if gaps:
        print("\n!! Months with no transactions at all, inside an account's own range:")
        for g in gaps:
            shown = ", ".join(g["missing"][:8])
            more = f" (+{len(g['missing']) - 8} more)" if len(g["missing"]) > 8 else ""
            print(f"   {g['account']} ({g['kind']}): {shown}{more}")
        print("   Each is either a genuinely unused month or a missing export.")

    print(f"\nLedger: {DB_PATH}")
    for row in conn.execute("""
        SELECT i.name AS institution, a.name AS account, a.tax_status,
               COUNT(*) AS txns, MIN(t.txn_date) AS first, MAX(t.txn_date) AS last
          FROM transactions t
          JOIN accounts a ON a.id = t.account_id
          JOIN institutions i ON i.id = a.institution_id
      GROUP BY a.id ORDER BY i.name, txns DESC"""):
        print(f"  {row['institution']:<12} {row['account']:<34} {row['tax_status']:<13} "
              f"{row['txns']:>5}  {row['first']} .. {row['last']}")

    total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    secs = conn.execute("SELECT COUNT(*) FROM securities").fetchone()[0]
    print(f"\n  {total} transactions, {secs} securities")
    return 0


if __name__ == "__main__":
    sys.exit(main())
