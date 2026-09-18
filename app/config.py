"""Everything that is specific to one person, in one place.

The app was written for one ledger and grew a handful of hardcoded facts about
it: six Fidelity account names, a 401(k) whose BrokerageLink sleeves belong to
one plan, an employer's name to recognise on a payslip, a filing status. None of
that is true for anyone else, and all of it was scattered across five modules.

## The rule this file follows

**A new user should get a working app with no configuration at all.** Anything
that can be inferred is inferred, and `config.json` exists only for what cannot
be — or to correct a guess that came out wrong. An app that demands a filled-in
config before it will run is one most people never get running.

So account kinds are guessed from their names, which works because brokerages
name accounts after what they are: something called "ROTH IRA" is tax-free and
something called "HEALTH SAVINGS ACCOUNT" is an HSA. The guess is always
REPORTED rather than applied silently, because a wrong tax status quietly
distorts every after-tax figure in the app and looks like nothing at all.

`config.json` is gitignored. `config.example.json` is committed and documents
every key.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Overridable for the same reason INVESTMENT_APP_DB is. Every one of the three
# test audits ran into a suite whose result depended on the developer's own
# machine — Alpaca credentials present or absent, and a synthetic tax fixture
# that started failing the moment a real `stub_employer` was configured. A test
# that passes or fails on the contents of a home directory is not testing the
# code. run_tests.sh points this at a path that does not exist, so every suite
# sees the defaults and nothing else.
CONFIG_PATH = (Path(os.environ["INVESTMENT_APP_CONFIG"])
               if os.environ.get("INVESTMENT_APP_CONFIG")
               else ROOT / "config.json")

# Account NAME patterns -> (kind, tax_status). Ordered: the first match wins, so
# the more specific patterns come first. "ROTH 401" has to be tested before
# "ROTH", or a Roth 401(k) sleeve is filed as an IRA and measured against the
# wrong contribution limit entirely.
ACCOUNT_PATTERNS = [
    (r"HEALTH\s*SAVINGS|\bHSA\b",                 ("hsa",        "hsa")),
    (r"ROTH\s*401|BROKERAGELINK\s*ROTH",          ("retirement", "tax_free")),
    (r"\bROTH\b",                                 ("retirement", "tax_free")),
    (r"401\s*\(?K\)?|RETIREMENT\s*SAVINGS|\bTSP\b|BROKERAGELINK",
                                                  ("retirement", "tax_deferred")),
    (r"\bSEP\b|\bSIMPLE\b|TRADITIONAL\s*IRA|\bIRA\b",
                                                  ("retirement", "tax_deferred")),
    (r"\b529\b|COVERDELL",                        ("education",  "tax_free")),
    (r"CHECKING|SAVINGS|\bBANK\b",                ("checking",   "na")),
    (r"CREDIT|\bCARD\b|VISA|AMEX|MASTERCARD",     ("credit",     "taxable")),
    (r"INDIVIDUAL|BROKERAGE|\bTOD\b|JOINT|TAXABLE",
                                                  ("brokerage",  "taxable")),
]

DEFAULTS = {
    # Tax profile. Wrong values here silently distort the standard deduction,
    # every bracket threshold, the Roth phase-out band and the catch-up rules at
    # once, and none of it looks like an error on screen.
    "filing_status": "single",
    "age": None,

    # Accounts whose kind or tax status the name cannot reveal. Only needed to
    # correct a guess: {"MY PLAN": {"kind": "retirement", "tax_status": "tax_deferred"}}
    "accounts": {},

    # Self-directed brokerage sleeves inside an employer plan, mapped to the
    # plan that funds them. Money moving from the plan into a sleeve is an
    # INTERNAL transfer; without this pairing it reads as an external deposit,
    # and an unrecognised inflow is indistinguishable from investment gain.
    "plan_sleeves": {},

    # Employer names to recognise as salary on a bank statement.
    "employers": [],

    "port": 8737,
    # Which addresses the server listens on. Loopback plus a Tailscale address
    # is the intended shape; 0.0.0.0 puts an unauthenticated server holding your
    # whole financial history on whatever network the machine joins.
    "host": "127.0.0.1",
    # launchd label prefix, so two people on one machine do not collide.
    "label_prefix": "investment-app",

    # SEC EDGAR's fair-access policy requires a real contact address in the
    # User-Agent of every request, and throttles or blocks requests without
    # one. This was hard-coded to the author's own email, which meant anybody
    # running a copy identified to the SEC as him — wrong for them and wrong
    # for the SEC, whose whole reason for asking is to know who is calling.
    "sec_contact": None,

    # Read a holding's chart from a different listing. A foreign company's US
    # OTC line and its home listing are the same business and a different
    # chart — SIVEF prints about a million shares a day against 8.5 million on
    # Stockholm and can be days stale. {"SIVEF": "SIVE.ST"}. The proxy's prices
    # are rescaled into the held symbol's currency before anything reads them.
    "chart_proxy": {},

    # What you intend to keep each month, in dollars. Deliberately NOT derived
    # from history: a goal set to what you already do is not a goal. Money moved
    # into investments counts toward it.
    "savings_goal": 3500,

    # A second W2 income the pay stubs cannot see, as an annual GROSS figure —
    # the salary, not what lands in the bank. The Roth phase-out is measured on
    # MAGI, which is a gross figure, so using take-home here understates it by
    # the whole tax and deferral load: about a quarter of the salary.
    #
    # Cross-check it against the deposits before trusting it. Take-home landing
    # at roughly three quarters of the number is what a gross salary looks like;
    # take-home equal to it means the number is net and is too low.
    #
    # Note the asymmetry this leaves. Income ALREADY received is counted from
    # deposits, which are net, while the remainder of the year is priced at
    # gross — so the projection stays a floor, which is what every threshold
    # message here already says it is.
    "spouse_annual": None,

    # The payer name on the stub-holder's own payroll deposits, e.g. "L3HARRIS".
    # A pay stub replaces payroll DEPOSITS with gross wages, and in a two-income
    # household "Salary" holds both people's — so without this the other
    # earner's wages are subtracted and never added back.
    "stub_employer": None,
}


def load() -> dict:
    """The merged configuration. Missing file is normal, not an error."""
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()) or {})
        except (OSError, ValueError) as exc:
            # A malformed config must say so. Falling back to defaults in
            # silence would apply the wrong filing status to a real tax figure.
            raise ValueError(f"{CONFIG_PATH.name} is not valid JSON: {exc}") from None
    return cfg


def classify_account(name: str, configured: dict | None = None) -> tuple[str, str, bool]:
    """(kind, tax_status, guessed) for an account name.

    `guessed` is returned rather than hidden so the caller can report it. A
    misclassified account is not a cosmetic problem: tax status decides whether
    a contribution counts against the Roth limit or the 401(k) deferral limit,
    and whether a gain is taxable at all.
    """
    configured = configured or {}
    hit = configured.get(name) or configured.get(name.upper())
    if hit and hit.get("kind"):
        return hit["kind"], hit.get("tax_status", "na"), False
    upper = (name or "").upper()
    for pattern, (kind, status) in ACCOUNT_PATTERNS:
        if re.search(pattern, upper):
            return kind, status, True
    return "brokerage", "na", True
