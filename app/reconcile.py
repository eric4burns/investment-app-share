"""Post-import reconciliation of one-sided internal transfers.

A 401(k) plan and its BrokerageLink sleeve are separate accounts in Fidelity's
export, but the plan's own export contains **no transfer rows at all** — only
contributions, exchanges, fees and market-value adjustments. So money moving
from the plan into the sleeve appears exactly once, as a credit in the sleeve,
with nothing debited anywhere.

That single missing leg is the most expensive defect the project has had. The
credit is correctly recognised as an *internal* movement and therefore excluded
from external cash flows — but because the sending side is never debited, the
money materialises from nowhere and every dollar of it is attributed to
investment performance. On this ledger it inflated the time-weighted return by
roughly 31 percentage points and flipped the Nasdaq comparison from "ahead" to
"behind".

The fix is to synthesise the missing debit, not to reclassify the credit as
external money. Reclassifying would double-count in the other direction, since
the plan account still holds the full contribution history that funded it.
"""
from __future__ import annotations

import hashlib
import re

# Sleeve account -> the plan account that funds it. A self-directed brokerage
# window inside an employer plan is fed BY that plan, so money moving between
# them is internal; unpaired, it reads as an external deposit, and an
# unrecognised inflow is indistinguishable from investment gain.
#
# Read from config.json rather than hardcoded, because whose plan it is differs
# per person. The default covers Fidelity's BrokerageLink, which is the common
# case and is named the same for everyone who has one — the PLAN it belongs to
# is discovered as the only tax_deferred retirement account, rather than named.
DEFAULT_SLEEVE_NAMES = ("BROKERAGELINK", "BrokerageLink Roth")


def plan_sleeves(conn=None) -> dict:
    """Sleeve -> plan. Configured if stated, discovered otherwise."""
    from . import config
    configured = config.load().get("plan_sleeves") or {}
    if configured:
        return configured
    if conn is None:
        return {}
    names = [r["name"] for r in conn.execute("SELECT name FROM accounts")]
    sleeves = [n for n in names if n in DEFAULT_SLEEVE_NAMES]
    if not sleeves:
        return {}
    plans = [r["name"] for r in conn.execute(
        "SELECT name FROM accounts WHERE kind='retirement' AND tax_status='tax_deferred'")
        if r["name"] not in DEFAULT_SLEEVE_NAMES]
    # Only when there is exactly one candidate. Guessing between two plans would
    # attribute a transfer to the wrong one, which is worse than not pairing it.
    return {s: plans[0] for s in sleeves} if len(plans) == 1 else {}




INTERNAL_MARKERS = ("TO BROKERAGE OPTION", "OTHER PLAN OPTION")
SOURCE = "synthetic_transfer_leg"


def _is_internal(description: str) -> bool:
    d = (description or "").upper()
    return any(m in d for m in INTERNAL_MARKERS)


def pair_internal_transfers(conn) -> dict:
    """Create the missing counter-leg for every one-sided internal transfer.

    Idempotent: the synthetic row's source_id is derived from the row it
    mirrors, so re-running inserts nothing.
    """
    created, skipped_no_plan, total = 0, set(), 0.0
    sleeves = plan_sleeves(conn)

    accounts = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM accounts")}

    rows = conn.execute("""
        SELECT t.id, t.txn_date, t.amount, t.description, a.name AS account
          FROM transactions t JOIN accounts a ON a.id = t.account_id
         WHERE t.kind IN ('transfer_in', 'transfer_out')""").fetchall()

    for row in rows:
        if not _is_internal(row["description"]):
            continue
        plan_name = sleeves.get(row["account"])
        if plan_name is None:
            skipped_no_plan.add(row["account"])
            continue
        plan_id = accounts.get(plan_name)
        if plan_id is None:
            skipped_no_plan.add(plan_name)
            continue

        amount = -(row["amount"] or 0.0)
        source_id = hashlib.sha1(f"pair:{row['id']}".encode()).hexdigest()
        cur = conn.execute(
            """INSERT OR IGNORE INTO transactions
                 (account_id, txn_date, kind, amount, description, source, source_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (plan_id, row["txn_date"],
             "transfer_out" if amount < 0 else "transfer_in",
             amount,
             f"[paired leg] {row['description']}",
             SOURCE, source_id))
        if cur.rowcount:
            created += 1
            total += amount

    return {"created": created, "net_amount": round(total, 2),
            "unmapped_accounts": sorted(skipped_no_plan)}


def audit_unpaired(conn) -> list[dict]:
    """Any internal transfer that still doesn't net to zero across the ledger.

    A non-empty result means money is still appearing or vanishing, which will
    be read as performance. Surfaced rather than silently tolerated.
    """
    # Group the synthetic leg together with the row it mirrors, otherwise each
    # side of a correctly balanced pair looks unbalanced on its own.
    totals: dict[str, list] = {}
    for r in conn.execute("""
        SELECT t.description, t.amount FROM transactions t
         WHERE t.kind IN ('transfer_in','transfer_out')"""):
        desc = (r["description"] or "").replace("[paired leg] ", "")
        if not _is_internal(desc):
            continue
        entry = totals.setdefault(desc, [0.0, 0])
        entry[0] += r["amount"] or 0.0
        entry[1] += 1
    return [{"description": d, "net": round(v[0], 2), "rows": v[1]}
            for d, v in sorted(totals.items()) if abs(v[0]) > 0.01]
