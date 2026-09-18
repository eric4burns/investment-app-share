"""What is actually sitting in cash, per account.

The money-market funds are the core position at Fidelity: uninvested money is
swept into SPAXX or FDRXX automatically and that fund IS the account's cash
balance. But the activity export never records the sweep. The only SPAXX rows in
this ledger are monthly dividends and their reinvestments, so summing the share
quantities counted the interest and none of the principal — $842 of core against
roughly $11,700 actually there, with the difference simply missing from the
portfolio total.

The balance is therefore derived from the cash flows, which the export does
record in full: every transaction's `amount` is its effect on cash, so the sum
of them is what is left over.

One subtraction matters. A sweep INTO the core fund is not money leaving the
account, it is money moving between two names for the same pool, so those
purchases are excluded from the sum. The dividend that funded a reinvestment is
kept, because that is real income arriving. Get this wrong and every account
that has ever earned interest reads slightly negative — which is how the
arithmetic announces the mistake, since a cash balance below zero is not a thing
a brokerage account can have.

Where the imported history does not reach back to when an account was funded,
no amount of arithmetic can recover the opening balance, and the total will be
too low by exactly that. An anchor fixes it: a balance the user read off a
statement, on a date, after which the flows take over.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .prices import is_money_market

# A purchase of the core fund is a sweep, not a spend.
SWEEP_KINDS = {"buy", "reinvest", "exchange_in", "transfer_in"}

# Rows that carry an amount but move no money. Fidelity books "Change in Market
# Value" against a retirement plan to restate a holding's worth; it is a
# valuation, not a transfer, and summing it into a cash balance is simply
# wrong. performance.values_at has always excluded these, cash.balances did
# not, and the two disagreed by exactly their total -- $35.08 here -- which is
# small enough to look like rounding and is nothing of the sort.
NON_CASH_KINDS = {"market_value_adj"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS cash_anchors (
    account   TEXT PRIMARY KEY,
    as_of     TEXT NOT NULL,
    balance   REAL NOT NULL,
    note      TEXT,
    set_at    TEXT NOT NULL
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def anchors(conn) -> dict[str, dict]:
    ensure_schema(conn)
    return {r["account"]: {"as_of": r["as_of"], "balance": r["balance"],
                           "note": r["note"]}
            for r in conn.execute(
                "SELECT account, as_of, balance, note FROM cash_anchors")}


def set_anchor(conn, account: str, as_of: str, balance: float,
               note: str | None = None) -> dict:
    """Record a statement balance for an account, on a date.

    Deliberately keyed by account with one row each: an anchor is the last
    reading known to be true, and keeping a history of superseded ones only
    creates the question of which to believe.
    """
    account = (account or "").strip()
    if not account:
        raise ValueError("an anchor needs an account")
    try:
        datetime.strptime(as_of[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"as_of must be a date, got {as_of!r}") from None
    balance = float(balance)
    if balance != balance or balance in (float("inf"), float("-inf")):
        raise ValueError("balance must be finite")
    ensure_schema(conn)
    conn.execute(
        """INSERT INTO cash_anchors (account, as_of, balance, note, set_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(account) DO UPDATE SET as_of = excluded.as_of,
                balance = excluded.balance, note = excluded.note,
                set_at = excluded.set_at""",
        (account, as_of[:10], balance, note,
         datetime.now(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()
    return {"account": account, "as_of": as_of[:10], "balance": balance}


def clear_anchor(conn, account: str) -> dict:
    ensure_schema(conn)
    cur = conn.execute("DELETE FROM cash_anchors WHERE account = ?",
                       ((account or "").strip(),))
    conn.commit()
    return {"removed": cur.rowcount}


def _is_sweep(txn) -> bool:
    return bool(is_money_market(txn.get("symbol")) and txn.get("kind") in SWEEP_KINDS)


def balances(txns, asof: str | None = None, anchor_map: dict | None = None) -> dict[str, dict]:
    """Cash per account, keyed by account name."""
    anchor_map = anchor_map or {}
    out: dict[str, dict] = {}
    for t in txns:
        acct = t.get("account") or "(unassigned)"
        day = (t.get("txn_date") or "")[:10]
        anchor = anchor_map.get(acct)
        amount = float(t.get("amount") or 0.0)
        # An anchor is a reading on a date, so a date BEFORE it has to be
        # reached by undoing what happened in between. Rolling only forwards
        # meant every historical point reported the anchor unchanged: two years
        # of net worth showed the same $9,358.35 of cash on every date, because
        # each transaction was either filtered out as being after `asof` or
        # skipped as already contained in the anchor, leaving flows at zero.
        rolling_back = bool(anchor and asof and asof < anchor["as_of"])
        if not rolling_back and asof and day > asof:
            continue

        row = out.setdefault(acct, {
            "account": acct, "flows": 0.0, "first_txn": day, "last_txn": day,
            "sweeps": 0.0,
        })
        if day and day < row["first_txn"]:
            row["first_txn"] = day
        if day and (not asof or day <= asof) and day > row["last_txn"]:
            row["last_txn"] = day

        if t.get("kind") in NON_CASH_KINDS:
            continue

        if _is_sweep(t):
            if not asof or day <= asof:
                row["sweeps"] += amount
            continue

        if rolling_back:
            # Undo everything that happened between the date being asked about
            # and the anchor. Anything on or before `asof` is already inside the
            # anchor's figure; anything after the anchor is in its future.
            if asof < day <= anchor["as_of"]:
                row["flows"] -= amount
            continue

        # Only flows AFTER the anchor date count; the anchor already contains
        # everything before it, and adding both would double the history.
        if anchor and day <= anchor["as_of"]:
            continue
        row["flows"] += amount

    for acct, row in out.items():
        anchor = anchor_map.get(acct)
        row["anchored"] = bool(anchor)
        row["anchor"] = anchor
        row["balance"] = round((anchor["balance"] if anchor else 0.0) + row["flows"], 2)
        row["flows"] = round(row["flows"], 2)
        row["sweeps"] = round(row["sweeps"], 2)
        # A brokerage account cannot hold less than nothing. When it reads that
        # way, the history does not go back far enough and the figure is a floor
        # rather than a balance — worth saying out loud rather than showing a
        # negative number as though it were real.
        row["impossible"] = row["balance"] < -0.005
    return out


def by_fund(txns, asof: str | None = None, anchor_map: dict | None = None) -> dict[str, float]:
    """Cash grouped by the core fund each account sweeps into.

    An account's core fund is whichever money-market symbol it has traded most
    recently — Fidelity gives a brokerage account SPAXX and an HSA FDRXX, and an
    account that has changed core funds should report under the current one.
    """
    per_account = balances(txns, asof, anchor_map)
    fund_of: dict[str, tuple[str, str]] = {}
    for t in txns:
        if not is_money_market(t.get("symbol")):
            continue
        acct, day = t.get("account") or "(unassigned)", (t.get("txn_date") or "")[:10]
        if asof and day > asof:
            continue
        seen = fund_of.get(acct)
        if not seen or day >= seen[1]:
            fund_of[acct] = (t["symbol"].strip().upper(), day)

    out: dict[str, float] = {}
    for acct, (fund, _day) in fund_of.items():
        row = per_account.get(acct)
        if not row:
            continue
        out[fund] = round(out.get(fund, 0.0) + row["balance"], 2)
    return out
