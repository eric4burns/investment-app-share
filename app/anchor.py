"""Record a real statement balance for an account, and see the ones on file.

    python3 -m app.anchor list
    python3 -m app.anchor set "ROTH IRA" 2026-08-28 1234.56 --note "Aug statement"
    python3 -m app.anchor clear "ROTH IRA"

## Why this exists

Cash in an account is derived by summing the transactions that have been
imported, which silently assumes the account held nothing the day before the
export window opened. That assumption is wrong for every account funded before
its first imported row, and it is wrong by exactly the opening balance.

Frost proved how badly: it read **-$8,618.13**, which is not a balance a
checking account can hold, against a real $9,358.35 — understating net worth by
nearly $18,000. That one fixed itself once the importer learned to read the
LEDGERBAL block an OFX file carries.

Fidelity's CSV exports carry no balance at all, so those accounts cannot
self-correct. Their derived cash may be right; there is no way to know from the
data, because an account that is short by its opening balance looks exactly
like an account that is simply low. An anchor is how you tell the app something
it cannot work out for itself.

An anchor is a reading on a DATE, and cash.balances rolls both directions from
it: later dates add the flows since, earlier dates undo the flows between.
"""
from __future__ import annotations

import argparse
import sys

from . import cash
from .ledger import connect


def _accounts(conn) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM accounts ORDER BY name")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m app.anchor", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the anchors on file")
    s = sub.add_parser("set", help="record a statement balance")
    s.add_argument("account")
    s.add_argument("as_of", help="the date the balance was true, YYYY-MM-DD")
    s.add_argument("balance", type=float)
    s.add_argument("--note", default=None)
    c = sub.add_parser("clear", help="remove an account's anchor")
    c.add_argument("account")
    args = ap.parse_args(argv)

    conn = connect()
    existing = cash.anchors(conn)

    if args.cmd == "list":
        names = _accounts(conn)
        if not existing:
            print("  No anchors set. Cash for every account is derived from imported")
            print("  transactions alone, which assumes each was empty before its first row.")
        for name in names:
            a = existing.get(name)
            if a:
                print(f"  {name:<34} {a['balance']:>12,.2f}  as of {a['as_of']}"
                      f"{'  · ' + a['note'] if a.get('note') else ''}")
            else:
                print(f"  {name:<34} {'—':>12}  derived from transactions only")
        return 0

    # Refuse an account that does not exist rather than creating an anchor that
    # can never apply to anything — a typo would otherwise fail silently.
    names = _accounts(conn)
    if args.account not in names:
        print(f"  No account named {args.account!r}. Known accounts:", file=sys.stderr)
        for n in names:
            print(f"    {n}", file=sys.stderr)
        return 1

    if args.cmd == "clear":
        conn.execute("DELETE FROM cash_anchors WHERE account = ?", (args.account,))
        conn.commit()
        print(f"  cleared the anchor on {args.account}")
        return 0

    try:
        cash.set_anchor(conn, args.account, args.as_of, args.balance, note=args.note)
    except ValueError as exc:
        print(f"  {exc}", file=sys.stderr)
        return 1
    conn.commit()
    was = existing.get(args.account)
    print(f"  {args.account}: {args.balance:,.2f} as of {args.as_of}"
          + (f"  (replaced {was['balance']:,.2f} as of {was['as_of']})" if was else ""))
    print("  Run ./update.sh or reload the dashboard to see it applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
