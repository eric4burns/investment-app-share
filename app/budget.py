"""Where the money goes.

The investing half of this app reads a brokerage export. This half reads a bank
export, and the difference that matters is that a bank account is mostly NOT
spending. Of the 1,302 rows in this ledger's checking account, the four largest
flows are money moving to Fidelity, money moving to a savings account, payroll
arriving and credit-card bills being paid. Add those up as expenses and the
"spending" for two years reads $388,943 against an income of $377,981, which
describes nobody's life and is entirely an artefact of counting transfers.

So the first job of a category is not to name a merchant, it is to say whether
the money LEFT. Four kinds:

    income      money arriving from outside
    expense     money leaving and not coming back
    transfer    money moving between accounts you own, in either direction
    investment  money moving into a brokerage — a transfer, but worth its own
                line, because "how much did I invest this year" is a question
                this app should answer

Only `expense` is spending. Everything else nets out.

## Rules are evaluated on read

A transaction's category is not written into it. The rules are the source of
truth and are applied every time, so correcting a rule reclassifies two years of
history at once instead of only what arrives next. That matters because the
rules WILL be wrong at first, and a categoriser you cannot correct in bulk is
one you abandon.

The exception is a manual override on a single transaction, which is written and
always wins — some rows are genuinely one-offs and no pattern should be invented
for them.

## What this cannot see

Card spending. The checking account records a payment to Chase or Amex, not what
was bought with it. Any budget built from this data alone shows a large
"credit card payment" line and no breakdown beneath it, and reporting that as
though it were a complete picture of spending would be a lie by omission. It is
labelled as a blind spot everywhere it appears, and closing it means importing
the card statements too.
"""
from __future__ import annotations

import re
from collections import defaultdict

KINDS = ("income", "expense", "transfer", "investment")

# Categories are (name, kind). Kept flat: a two-level tree looks tidier and
# immediately raises the question of whether a total includes children, which is
# a bug generator for no gain at this size.
DEFAULT_CATEGORIES = [
    ("Salary",              "income"),
    ("Business income",     "income"),
    ("Interest",            "income"),
    ("Other income",        "income"),

    ("To brokerage",        "investment"),
    ("Crypto",              "investment"),
    ("Credit card payment", "transfer"),
    ("Savings transfer",    "transfer"),
    ("Internal transfer",   "transfer"),

    ("Rent",                "expense"),
    ("Utilities",           "expense"),
    ("Groceries",           "expense"),
    ("Dining",              "expense"),
    ("Transport",           "expense"),
    ("Subscriptions",       "expense"),
    ("Shopping",            "expense"),
    # Split out of Shopping, which was 303 transactions and $22,020 of "things"
    # — a category that large answers no question. Amazon alone was $8,736 of it.
    ("Amazon",              "expense"),
    ("Clothing",            "expense"),
    ("Personal care",       "expense"),
    ("Home",                "expense"),
    ("Health",              "expense"),
    ("Travel",              "expense"),
    ("Pets",                "expense"),
    ("Insurance",           "expense"),
    ("Taxes",               "expense"),
    ("Fees",                "expense"),
    ("Cash and P2P",        "expense"),
    ("Other spending",      "expense"),
]

# (pattern, category, priority). Higher priority wins; ties go to the longer,
# more specific pattern. Patterns are matched case-insensitively anywhere in the
# description.
#
# These are seeds, not truth. They were written by reading this ledger's own
# descriptions, and the honest measure of them is how much they leave unmatched
# — which the report shows, largest first, so the next rule to write is always
# the one at the top.
DEFAULT_RULES = [
    # --- money in ---
    ("PAYROLL",                 "Salary", 200),
    ("DIRECT DEP",              "Salary", 190),
    # Employer names are person-specific; add your own under "employers" in
    # config.json rather than editing this list. PAYROLL and DIRECT DEP above
    # catch most deposits without knowing any employer's name at all.
    ("L3HARRIS",                "Salary", 180),
    ("CELESTICA",               "Salary", 180),
    ("Interest Payment",        "Interest", 200),
    ("Zelle Receive",           "Business income", 150),
    ("Mobile Deposit",          "Other income", 120),
    ("CASH REWARD",             "Other income", 200),
    ("CASH BACK REWARD",        "Other income", 200),
    ("REDEMPTION CREDIT",       "Other income", 200),

    # --- moving your own money: never spending ---
    ("FID BKG SVC",             "To brokerage", 300),
    ("FIDELITY",                "To brokerage", 290),
    ("ROBINHOOD",               "To brokerage", 300),
    # Two spellings of the same Amex savings account, in both directions.
    ("AMERICANEXPRESS TRANSFER", "Savings transfer", 300),
    ("AMERICAN EXPRESS TRANSFER", "Savings transfer", 300),
    ("CARDMEMBER SERV",         "Credit card payment", 300),
    ("CHASE CREDIT CRD",        "Credit card payment", 300),
    ("ELAN WEB PYMT",           "Credit card payment", 300),
    ("CAPITAL ONE",             "Credit card payment", 300),
    ("DISCOVER",                "Credit card payment", 280),
    # As the CARD itself records them. A payment shows up twice — leaving
    # checking and arriving at the card — and both legs have to be transfers, or
    # the pair reads as spending on one side and income on the other.
    ("PAYMENT THANK YOU",       "Credit card payment", 320),
    ("PAYMENT - THANK YOU",     "Credit card payment", 320),
    ("ONLINE PAYMENT",          "Credit card payment", 320),
    ("MOBILE PYMT",             "Credit card payment", 320),
    ("AUTOPAY",                 "Credit card payment", 320),
    ("DIRECTPAY",               "Credit card payment", 320),
    ("PAYMENT RECEIVED",        "Credit card payment", 320),
    ("PAYMENT FROM",            "Credit card payment", 320),
    ("AMEX EPAYMENT",           "Credit card payment", 300),
    # Foris DAX is the legal entity behind Crypto.com, in both directions:
    # money out is a purchase, money in is a sale or card rebate. Neither is
    # spending, which is why it is not left in "other".
    ("FORIS",                   "Crypto", 300),

    # --- money out ---
    ("BILTRENT",                "Rent", 250),
    ("BILT PAYMENT",            "Rent", 240),
    ("BILT-RENT",               "Rent", 240),
    ("USATAXPYMT",              "Taxes", 250),
    ("IRS ",                    "Taxes", 240),
    ("FRANCHISE TAX",           "Taxes", 240),

    ("ATT*BILL",                "Utilities", 200),
    ("AT&T",                    "Utilities", 190),
    ("SPECTRUM",                "Utilities", 200),
    ("CITY OF",                 "Utilities", 180),
    ("ATT PAYMENT",             "Utilities", 210),
    ("MYENERGYINVOICE",         "Utilities", 200),
    ("RELIANT",                 "Utilities", 190),
    ("TXU ",                    "Utilities", 190),
    ("ATMOS",                   "Utilities", 190),
    ("ELECTRIC",                "Utilities", 180),

    ("UBER* TRIP",              "Transport", 210),
    ("UBER *TRIP",              "Transport", 210),
    ("UBER * PENDING",          "Transport", 210),
    ("LYFT",                    "Transport", 200),
    ("SHELL ",                  "Transport", 190),
    ("EXXON",                   "Transport", 190),
    ("CHEVRON",                 "Transport", 190),
    ("PARKING",                 "Transport", 180),
    # Fuel and tolls. Buc-ee's and QuikTrip are filling stations that read as
    # nothing in particular unless you know them.
    ("MURPHY USA",              "Transport", 200),
    ("BUC-EE",                  "Transport", 200),
    ("QT ",                     "Transport", 185),
    ("QUIKTRIP",                "Transport", 200),
    ("RACETRAC",                "Transport", 200),
    ("NTTA",                    "Transport", 200),
    ("TOLL",                    "Transport", 180),
    ("VALVOLINE",               "Transport", 190),
    ("DISCOUNT TIRE",           "Transport", 190),

    ("UBER* EATS",              "Dining", 220),
    ("UBER *EATS",              "Dining", 220),
    ("DOORDASH",                "Dining", 200),
    ("GRUBHUB",                 "Dining", 200),
    ("STARBUCKS",               "Dining", 200),
    ("CHIPOTLE",                "Dining", 200),
    # Toast and Square are point-of-sale systems, so the prefix is the reliable
    # signal even though the restaurant name that follows never repeats.
    ("TST*",                    "Dining", 200),
    ("SQ *",                    "Dining", 190),
    ("WHATABURGER",             "Dining", 200),
    ("MCDONALD",                "Dining", 200),
    ("TACO ",                   "Dining", 180),
    ("PIZZA",                   "Dining", 180),
    ("RESTAURANT",              "Dining", 180),
    ("CHICK-FIL-A",             "Dining", 200),
    ("PANERA",                  "Dining", 200),
    ("SONIC DRIVE",             "Dining", 200),
    ("BUFFALO WILD WINGS",      "Dining", 200),
    ("WINGSTOP",                "Dining", 200),
    ("CHILI'S",                 "Dining", 200),
    ("OLIVE GARDEN",            "Dining", 200),
    ("CRACKER BARREL",          "Dining", 200),
    ("DAIRY QUEEN",             "Dining", 200),
    ("SUBWAY",                  "Dining", 190),

    ("H-E-B",                   "Groceries", 200),
    ("HEB ",                    "Groceries", 200),
    ("KROGER",                  "Groceries", 200),
    ("WHOLEFDS",                "Groceries", 200),
    ("TRADER JOE",              "Groceries", 200),
    # "WALMART" does not match "WAL-MART SUPERCENTER", which is how the receipts
    # actually read — $3,334 of groceries sat uncategorised behind a hyphen.
    ("WAL-MART",                "Groceries", 175),
    ("WALMART",                 "Groceries", 170),
    ("SPROUTS FARMERS",         "Groceries", 200),
    ("ALDI",                    "Groceries", 190),
    ("SAM'S CLUB",              "Groceries", 175),
    ("SAMS CLUB",               "Groceries", 175),
    ("CENTRAL MARKET",          "Groceries", 190),
    ("COSTCO",                  "Groceries", 170),

    ("SPOTIFY",                 "Subscriptions", 200),
    ("GOOGLE *Google One",      "Subscriptions", 210),
    ("FIREFLIES",               "Subscriptions", 200),
    ("IPSY",                    "Subscriptions", 200),
    ("NETFLIX",                 "Subscriptions", 200),
    ("AUDIBLE",                 "Subscriptions", 200),
    ("OPENAI",                  "Subscriptions", 200),
    ("ANTHROPIC",               "Subscriptions", 200),
    ("APPLE.COM/BILL",          "Subscriptions", 200),
    ("PRIME VIDEO",             "Subscriptions", 200),
    ("CANVA",                   "Subscriptions", 200),
    ("HULU",                    "Subscriptions", 200),
    ("DISNEY PLUS",             "Subscriptions", 200),
    ("YOUTUBEPREMIUM",          "Subscriptions", 200),
    ("PATREON",                 "Subscriptions", 200),
    ("ADOBE",                   "Subscriptions", 200),
    ("MICROSOFT",               "Subscriptions", 180),

    # Travel and pets, which the first pass had no categories for at all and
    # which the card data turned out to be full of.
    ("UNITED AIRLINES",         "Travel", 200),
    ("AMERICAN AIR",            "Travel", 200),
    ("DELTA AIR",               "Travel", 200),
    ("SOUTHWEST AIR",           "Travel", 200),
    ("AIRBNB",                  "Travel", 200),
    ("BOOKING.COM",             "Travel", 200),
    ("EXPEDIA",                 "Travel", 200),
    ("HOTEL",                   "Travel", 170),
    ("MARRIOTT",                "Travel", 200),
    ("HILTON",                  "Travel", 200),

    ("GOODDOG",                 "Pets", 200),
    ("PETCARERX",               "Pets", 200),
    ("PETCO",                   "Pets", 200),
    ("PETSMART",                "Pets", 200),
    ("CHEWY",                   "Pets", 200),
    ("VETERINAR",               "Pets", 200),
    ("VETCARE",                 "Pets", 200),
    ("ANIMAL HOSP",             "Pets", 200),

    ("BESTBUY",                 "Shopping", 190),
    ("BEST BUY",                "Shopping", 190),
    ("OLD NAVY",                "Shopping", 190),
    ("NEIMANMARCUS",            "Shopping", 190),
    ("SHEIN",                   "Shopping", 190),
    ("HM.COM",                  "Shopping", 190),
    ("ETSY",                    "Shopping", 190),
    ("EBAY",                    "Shopping", 190),

    ("KWIK KAR",                "Transport", 190),
    ("AMZN",                    "Shopping", 160),
    ("AMAZON",                  "Shopping", 160),
    ("TARGET",                  "Shopping", 160),
    ("PATAGONIA",               "Shopping", 190),
    ("MENS WEARHOUSE",          "Shopping", 190),
    ("TOMMY.COM",               "Shopping", 190),
    ("ZARA",                    "Shopping", 190),
    ("UNCOMMONGOODS",           "Shopping", 190),
    ("CANAKIT",                 "Shopping", 190),
    ("MACYS",                   "Shopping", 190),
    ("NIKE",                    "Shopping", 190),
    ("BR FACTORY",              "Shopping", 190),
    ("LULULEMON",               "Shopping", 190),
    ("NORDSTROM",               "Shopping", 190),
    ("HOME DEPOT",              "Shopping", 180),
    ("LOWES",                   "Shopping", 180),
    ("GORILLA MIND",            "Health", 190),

    ("CVS",                     "Health", 190),
    ("WALGREENS",               "Health", 190),
    ("PHARMACY",                "Health", 190),
    ("DENTAL",                  "Health", 190),

    ("GEICO",                   "Insurance", 200),
    ("PROGRESSIVE",             "Insurance", 200),
    ("PROG COUNTY MUT",         "Insurance", 210),
    ("STATE FARM",              "Insurance", 200),

    ("VENMO",                   "Cash and P2P", 180),
    ("Zelle Send",              "Cash and P2P", 180),
    ("CASH APP",                "Cash and P2P", 180),
    ("WUVISAAFT",               "Cash and P2P", 180),
    ("WESTERN UNION",           "Cash and P2P", 190),
    ("WU DIGITAL",              "Cash and P2P", 190),
    ("REMITLY",                 "Cash and P2P", 190),
    ("ZELLE",                   "Cash and P2P", 150),
    ("ATM ",                    "Cash and P2P", 180),

    ("OVERDRAFT",               "Fees", 220),
    ("SERVICE CHARGE",          "Fees", 220),
    ("ANNUAL FEE",              "Fees", 220),
]


SPENDING_ACCOUNT_KINDS = ("checking", "savings", "credit")


def load_spending(conn, start: str | None = None, end: str | None = None,
                  account: str | None = None) -> list[dict]:
    """Every transaction from the accounts a budget is built from."""
    kinds = ",".join("?" * len(SPENDING_ACCOUNT_KINDS))
    sql = [f"""SELECT t.id, t.txn_date, t.amount, t.description, t.kind,
                      a.name AS account, a.kind AS account_kind
                 FROM transactions t JOIN accounts a ON a.id = t.account_id
                WHERE a.kind IN ({kinds})"""]
    args = list(SPENDING_ACCOUNT_KINDS)
    if start:
        sql.append("AND t.txn_date >= ?"); args.append(start)
    if end:
        sql.append("AND t.txn_date <= ?"); args.append(end)
    if account:
        sql.append("AND a.name = ?"); args.append(account)
    sql.append("ORDER BY t.txn_date, t.id")
    return [dict(r) for r in conn.execute(" ".join(sql), args)]


def accounts(conn) -> list[dict]:
    kinds = ",".join("?" * len(SPENDING_ACCOUNT_KINDS))
    return [dict(r) for r in conn.execute(
        f"""SELECT a.name, a.kind, COUNT(*) n, MIN(t.txn_date) first, MAX(t.txn_date) last
              FROM accounts a JOIN transactions t ON t.account_id = a.id
             WHERE a.kind IN ({kinds}) GROUP BY a.id ORDER BY n DESC""",
        SPENDING_ACCOUNT_KINDS)]


def ensure_seed(conn) -> dict:
    """Create the default categories and rules if they are not there.

    Idempotent by name and by (pattern, category), so running it again after
    hand-editing adds only what is genuinely missing and never resurrects a rule
    that was deliberately deleted... which is why deletion is not offered: a
    disabled rule would come back. Change a rule instead of removing it.
    """
    added_c = added_r = 0
    have = {r["name"] for r in conn.execute("SELECT name FROM categories")}
    for name, kind in DEFAULT_CATEGORIES:
        if name not in have:
            conn.execute("INSERT INTO categories (name, kind) VALUES (?,?)", (name, kind))
            added_c += 1
    ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}
    seen = {(r["pattern"].upper(), r["category_id"])
            for r in conn.execute("SELECT pattern, category_id FROM category_rules")}
    for pattern, category, priority in DEFAULT_RULES:
        cid = ids.get(category)
        if cid is None or (pattern.upper(), cid) in seen:
            continue
        conn.execute(
            "INSERT INTO category_rules (pattern, category_id, priority, origin) "
            "VALUES (?,?,?,'seed')", (pattern, cid, priority))
        added_r += 1
    conn.commit()
    return {"categories_added": added_c, "rules_added": added_r}


def add_rule(conn, pattern: str, category: str, priority: int = 150) -> dict:
    """Teach it one more pattern.

    Written from the unmatched list, which is deliberately sorted by size: the
    next rule worth adding is always the one at the top, and a categoriser is
    only ever finished in the sense that what is left does not matter.
    """
    pattern = (pattern or "").strip()
    if len(pattern) < 3:
        raise ValueError("a pattern needs at least three characters — "
                         "shorter ones match half the ledger")
    row = conn.execute("SELECT id FROM categories WHERE name = ?",
                       ((category or "").strip(),)).fetchone()
    if not row:
        raise ValueError(f"no category named {category!r}")
    existing = conn.execute(
        "SELECT id FROM category_rules WHERE UPPER(pattern) = ? AND category_id = ?",
        (pattern.upper(), row["id"])).fetchone()
    if existing:
        return {"id": existing["id"], "pattern": pattern, "category": category,
                "already": True}
    cur = conn.execute(
        "INSERT INTO category_rules (pattern, category_id, priority, origin) "
        "VALUES (?,?,?,'manual')", (pattern, row["id"], int(priority)))
    conn.commit()
    return {"id": cur.lastrowid, "pattern": pattern, "category": category}


def remove_rule(conn, rule_id: int) -> dict:
    cur = conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    conn.commit()
    return {"removed": cur.rowcount}


def load_rules(conn) -> list[dict]:
    """Rules in the order they should be tried: strongest first.

    Priority first, then pattern length. Without the length tiebreak two rules of
    equal priority are applied in whatever order the database returns them, so
    "UBER* EATS" and "UBER* TRIP" would classify the same row differently
    depending on the query plan — a category that changes for no visible reason
    is worse than one that is simply wrong.
    """
    # Patterns are normalised once here rather than on every comparison: this
    # list is walked for each of several thousand transactions.
    return [{"pattern": norm(r["pattern"]), "category": r["name"],
             "kind": r["kind"], "priority": r["priority"], "id": r["id"]}
            for r in conn.execute(
                """SELECT cr.id, cr.pattern, cr.priority, c.name, c.kind
                     FROM category_rules cr JOIN categories c ON c.id = cr.category_id
                 ORDER BY cr.priority DESC, LENGTH(cr.pattern) DESC, cr.id""")]


def norm(text: str) -> str:
    """Upper-cased, with every run of whitespace squeezed to one space.

    Matching has to be whitespace-insensitive because the descriptions are
    fixed-width card exports: "UBER   *TRIP" pads the merchant out to a column,
    and the next row from the same merchant may pad it differently. Comparing
    those literally makes a rule that matches one charge and misses its twin.

    It also has to be insensitive because of where the patterns come from.
    suggest_pattern() collapses whitespace to produce a readable merchant name,
    and that name was then stored and compared literally — so for any merchant
    whose description contained a double space, the rule the UI offered could
    never match the transaction it was offered for. Accepting the suggestion
    appeared to do nothing, which is exactly what it did: 101 of 383 merchant
    groups were unfixable this way, 172 transactions and about $10,700 of them.

    Normalising here rather than in suggest_pattern() is deliberate: it repairs
    rules that were already written and stored broken, and it forgives a pattern
    typed by hand, which will never reproduce a run of seven spaces either.
    """
    return re.sub(r"\s+", " ", (text or "").upper()).strip()


def match(description: str, rules: list[dict]) -> dict | None:
    d = norm(description)
    for rule in rules:
        if rule["pattern"] in d:
            return rule
    return None


def classify(conn, txns: list[dict]) -> list[dict]:
    """Attach a category to each transaction. Does not write to the database."""
    rules = load_rules(conn)
    overrides = {r["id"]: (r["name"], r["kind"]) for r in conn.execute(
        """SELECT t.id, c.name, c.kind FROM transactions t
             JOIN categories c ON c.id = t.category_id
            WHERE t.category_id IS NOT NULL""")}
    out = []
    for t in txns:
        row = dict(t)
        manual = overrides.get(t.get("id"))
        if manual:
            row["category"], row["category_kind"], row["category_source"] = (
                manual[0], manual[1], "manual")
        else:
            hit = match(t.get("description"), rules)
            row["category"] = hit["category"] if hit else None
            row["category_kind"] = hit["kind"] if hit else None
            row["category_source"] = "rule" if hit else "unmatched"
        out.append(row)
    return out


def suggest_pattern(description: str) -> str:
    """The part of a description that will match this merchant's other charges.

    Every card row carries something unique — a store number, a city, a
    reference — so the raw description matches exactly one transaction and makes
    a useless rule. What is wanted is the merchant-looking head of the string,
    which is what the next charge from them will also start with.
    """
    text = norm(re.split(r"\s+—\s+", str(description or ""))[0])

    # TRUNCATE at the first per-charge unique, never splice it out of the
    # middle. Cutting "0169" from "Crash Champions 0169 - ROWLETT" leaves
    # "Crash Champions - ROWLETT", which is not a contiguous substring of the
    # description and so cannot match it under any amount of whitespace
    # forgiveness — the rule is unusable the moment it is written. Truncating
    # instead yields "CRASH CHAMPIONS", which is a prefix, matches every charge
    # from them, and is the merchant head this function set out to find.
    #
    # Whitespace is REQUIRED before the marker. Without it "1800ACCT" matched
    # its own "ACCT" and the merchant became "1800", which is both a wrong name
    # and a rule that would match a thousand unrelated dollar amounts.
    cut = re.search(r"\s(?:\d{3,}[\d\-.]*|[X*#]{3,}\S*|(?:CARD|ACCT|REF)[:# ])", text)
    # A cut inside the first three characters would leave nothing to match on,
    # so the whole string is kept and the caller's own length guard applies.
    if cut and cut.start() >= 3:
        text = text[:cut.start()]

    # A trailing state code is noise on every card row, and dropping it from the
    # END keeps the result a prefix.
    text = re.sub(r"\s+[A-Z]{2}$", "", text)
    text = text.rstrip(" -*#/,.")
    # Truncation is also safe for the same reason: a prefix of a substring is
    # still a substring.
    return text[:32].strip()


def group_unmatched(rows: list[dict], limit: int = 60) -> list[dict]:
    """Unmatched transactions collapsed to one row per merchant.

    264 uncategorised transactions is 264 decisions if they are listed one by
    one, and about 30 if they are grouped — most of the tail is the same handful
    of shops seen again and again. Grouping is what makes finishing the job
    plausible rather than a chore nobody does.
    """
    groups: dict[str, dict] = {}
    for t in rows:
        pattern = suggest_pattern(t.get("description"))
        if len(pattern) < 3:
            pattern = str(t.get("description") or "")[:32]
        row = groups.setdefault(pattern, {
            "pattern": pattern, "count": 0, "total": 0.0,
            "example": t.get("description"), "first": t.get("txn_date"),
            "last": t.get("txn_date"),
        })
        row["count"] += 1
        row["total"] += float(t.get("amount") or 0.0)
        day = t.get("txn_date") or ""
        if day and day < (row["first"] or "9999"):
            row["first"] = day
        if day and day > (row["last"] or ""):
            row["last"] = day
    out = sorted(groups.values(), key=lambda r: -abs(r["total"]))
    for row in out:
        row["total"] = round(row["total"], 2)
    return out[:limit]


def summary(classified: list[dict]) -> dict:
    """Totals by kind and by category, plus the monthly series for each."""
    by_kind: dict[str, float] = defaultdict(float)
    by_category: dict[str, dict] = {}
    by_month: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    unmatched_rows = []

    for t in classified:
        amount = float(t.get("amount") or 0.0)
        month = (t.get("txn_date") or "")[:7]
        cat, kind = t.get("category"), t.get("category_kind")
        if cat is None:
            # Unmatched is its own bucket, never folded into "other spending".
            # A budget that quietly absorbs what it does not understand looks
            # complete and is not.
            unmatched_rows.append(t)
            by_kind["unmatched"] += amount
            by_month[month]["unmatched"] += amount
            continue
        by_kind[kind] += amount
        by_month[month][kind] += amount
        row = by_category.setdefault(cat, {"category": cat, "kind": kind,
                                           "total": 0.0, "n": 0})
        row["total"] += amount
        row["n"] += 1

    for row in by_category.values():
        row["total"] = round(row["total"], 2)

    # Category BY MONTH. The totals above say where the money went; they cannot
    # say whether groceries are creeping up or last month's travel was a one-off.
    # Twelve numbers per category answer that and a single total never can.
    per_cat_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in classified:
        if t.get("category_kind") != "expense":
            continue
        month = (t.get("txn_date") or "")[:7]
        if month:
            per_cat_month[t["category"]][month] += -float(t.get("amount") or 0.0)

    # The blind spot is what was paid to cards MINUS what those cards can now
    # account for. Both halves have to be measured on one side only: a payment
    # appears twice, leaving the bank and arriving at the card, and the category
    # total holds both legs. So the money out is counted from the bank accounts
    # alone, and the spending it stands for from the card accounts alone.
    card_paid = abs(sum(float(t.get("amount") or 0) for t in classified
                        if t.get("category") == "Credit card payment"
                        and t.get("account_kind") != "credit"
                        and float(t.get("amount") or 0) < 0))
    card_seen = abs(sum(float(t.get("amount") or 0) for t in classified
                        if t.get("account_kind") == "credit"
                        and float(t.get("amount") or 0) < 0
                        and t.get("category_kind") != "transfer"))

    unmatched_rows.sort(key=lambda t: -abs(float(t.get("amount") or 0)))
    months = sorted(by_month)
    spend_months = [m for m in months if by_month[m].get("expense")]
    return {
        "by_kind": {k: round(v, 2) for k, v in by_kind.items()},
        "by_category": sorted(by_category.values(),
                              key=lambda r: (r["kind"], -abs(r["total"]))),
        "by_month": [{"month": m, **{k: round(v, 2) for k, v in by_month[m].items()}}
                     for m in months],
        "unmatched": [{"date": t.get("txn_date"), "amount": t.get("amount"),
                       "description": t.get("description")}
                      for t in unmatched_rows[:50]],
        # One row per merchant, largest first. Categorising the top ten of these
        # is worth more than categorising the top fifty individual transactions.
        "unmatched_groups": group_unmatched(unmatched_rows),
        "unmatched_count": len(unmatched_rows),
        "unmatched_total": round(sum(float(t.get("amount") or 0)
                                     for t in unmatched_rows), 2),
        # The signed total is nearly useless once card data is in: unmatched
        # purchases and unmatched payments sit in the same bucket and cancel, so
        # 854 rows reported as $1,000. What matters is how much money left and
        # has not been classified.
        "unmatched_out": round(abs(sum(float(t.get("amount") or 0)
                                       for t in unmatched_rows
                                       if float(t.get("amount") or 0) < 0)), 2),
        "unmatched_in": round(sum(float(t.get("amount") or 0)
                                  for t in unmatched_rows
                                  if float(t.get("amount") or 0) > 0), 2),
        # Spending per month, over months that actually have spending in them —
        # dividing by the calendar would understate it whenever the export
        # starts or ends mid-month.
        "monthly_spend": (round(abs(sum(by_month[m].get("expense", 0.0)
                                        for m in spend_months)) / len(spend_months), 2)
                          if spend_months else None),
        # What is still unseen, not what was ever paid to a card. Once a card's
        # own transactions are imported its purchases ARE visible, so counting
        # its payments as a blind spot would keep reporting the spending that is
        # now on screen as missing.
        "card_payments": round(card_paid, 2),
        "card_spend_seen": round(card_seen, 2),
        "card_blind_spot": round(max(0.0, card_paid - card_seen), 2),
        # One row per expense category, aligned to the same month list, so the
        # front end can draw them as small multiples without re-deriving the
        # grid and risking a different one.
        "category_months": months,
        "by_category_month": [
            {"category": cat,
             "values": [round(vals.get(m, 0.0), 2) for m in months],
             "total": round(sum(vals.values()), 2)}
            for cat, vals in sorted(per_cat_month.items(),
                                    key=lambda kv: -sum(kv[1].values()))
        ],
    }


# --- goals ----------------------------------------------------------------

DEFAULT_SAVINGS_GOAL = 3_500.0
TRAILING_MONTHS = 6


def goals(by_month: list[dict], by_category_month: list[dict] | None = None,
          savings_goal: float = DEFAULT_SAVINGS_GOAL,
          asof: str | None = None,
          category_months: list[str] | None = None) -> dict:
    """Targets built from your own history, plus one number you chose.

    The Plan-vs-actual tab compared an imported spreadsheet against the ledger
    and effectively compared nothing: the sheet's categories are its own
    ("Everyday", "Debt", "Transportation") and almost none of them matched, so
    it reported 62,587 against 8,242 and a difference that was really just the
    unmatched remainder. Category names in somebody's spreadsheet are the wrong
    thing to hang a comparison on.

    So a category's target is its own trailing average instead — what you
    actually spend on it, over the last `TRAILING_MONTHS` complete months. That
    cannot fail to match, and "more than usual" is the comparison worth making
    anyway.

    The savings goal is the one number that is NOT derived from history, because
    a goal set to what you already do is not a goal. It defaults to 3,500 a
    month and money moved into investments counts toward it: it left the
    spending accounts either way, and the point is what was kept rather than
    where it was kept.

    The current month is always partial and is pro-rated by the share of it that
    has elapsed. Comparing eight days against a full month's average shows every
    category comfortably under target, every month, until the last day.
    """
    from datetime import date

    asof = asof or date.today().isoformat()
    cur_month = asof[:7]
    rows = sorted(by_month or [], key=lambda m: m["month"])
    if not rows:
        return {"available": False,
                "why": "no months in the ledger yet"}

    def saved(m: dict) -> float:
        # expense is stored negative; transfers and investment contributions are
        # not spending, so neither is subtracted here.
        return round((m.get("income") or 0.0) + (m.get("expense") or 0.0), 2)

    complete = [m for m in rows if m["month"] < cur_month]
    current = next((m for m in rows if m["month"] == cur_month), None)

    hist = complete[-TRAILING_MONTHS:]
    avg_saved = round(sum(saved(m) for m in hist) / len(hist), 2) if hist else None
    avg_spend = (round(sum(abs(m.get("expense") or 0.0) for m in hist) / len(hist), 2)
                 if hist else None)
    avg_income = (round(sum(m.get("income") or 0.0 for m in hist) / len(hist), 2)
                  if hist else None)

    months = [{"month": m["month"], "saved": saved(m),
               "income": round(m.get("income") or 0.0, 2),
               "spent": round(abs(m.get("expense") or 0.0), 2),
               "invested": round(abs(m.get("investment") or 0.0), 2),
               "met": saved(m) >= savings_goal}
              for m in complete[-24:]]
    hit = sum(1 for m in months if m["met"])

    # ---- where the current month stands ----------------------------------
    elapsed = None
    if current:
        y, mo = (int(x) for x in cur_month.split("-"))
        nxt = date(y + (mo == 12), (mo % 12) + 1, 1)
        days_in = (nxt - date(y, mo, 1)).days
        elapsed = round(min(1.0, (date.fromisoformat(asof).day) / days_in), 4)

    now = None
    if current and elapsed:
        s = saved(current)
        income_now = round(current.get("income") or 0.0, 2)
        now = {
            "month": cur_month, "elapsed": elapsed,
            "saved": s, "spent": round(abs(current.get("expense") or 0.0), 2),
            "income": income_now,
            "goal_so_far": round(savings_goal * elapsed, 2),
            "pace": round(s / elapsed, 2) if elapsed else None,
            # Before the month's first pay lands, "behind pace" is only the
            # calendar: nothing has been earned yet to save from.
            "no_pay_yet": income_now <= 0 and elapsed < 0.6,
            "on_track": (s >= savings_goal * elapsed) if income_now > 0 else None,
        }

    # ---- per-category targets from the trailing average -------------------
    # by_category_month is parallel arrays — one `values` list per category,
    # aligned to `category_months` — not one row per category-month. Reading it
    # as rows produced zero categories silently, because .get("month") was None
    # on every entry and every one was skipped.
    cats = []
    if by_category_month and category_months:
        per: dict[str, list[float]] = {}
        cur: dict[str, float] = {}
        for r in by_category_month:
            name, vals = r.get("category"), r.get("values") or []
            if not name:
                continue
            past = [abs(v or 0.0) for m, v in zip(category_months, vals)
                    if m < cur_month]
            if past:
                per[name] = past
            cur[name] = sum(abs(v or 0.0) for m, v in zip(category_months, vals)
                            if m == cur_month)
        for name, vals in per.items():
            recent = vals[-TRAILING_MONTHS:]
            target = round(sum(recent) / len(recent), 2)
            spent = round(cur.get(name, 0.0), 2)
            pro = round(target * (elapsed or 1.0), 2)
            # "Over" means over the whole month's target. Rent is paid on the
            # 2nd, so measured against a pro-rated target it read "+$1,920
            # over" every month on the 6th; ahead of the pro-rated pace but
            # under the month's target is reported as ahead, not over.
            cats.append({"category": name, "target": target, "spent": spent,
                         "target_so_far": pro, "months": len(recent),
                         "over": spent > target * 1.02,
                         "ahead": spent > pro and spent <= target * 1.02,
                         "over_by": round(spent - target, 2) if spent > target * 1.02 else round(spent - pro, 2)})
        # Overspends first, then the biggest categories. Sorting on over_by
        # alone put the whole list in "least under target" order early in a
        # month, which leads with whatever you happen to spend least on.
        cats.sort(key=lambda c: (not c["over"], -c["over_by"] if c["over"]
                                 else -c["target"]))

    return {
        "available": True, "goal": savings_goal, "asof": asof,
        "trailing_months": len(hist),
        "average_saved": avg_saved, "average_spent": avg_spend,
        "average_income": avg_income,
        "months": months, "months_met": hit, "months_counted": len(months),
        "current": now, "categories": cats[:20],
        "note": (
            f"The savings goal is {savings_goal:,.0f} a month and is yours, not "
            f"derived from history — a goal set to what you already do is not a "
            f"goal. Money moved into investments counts toward it. Category "
            f"targets ARE the trailing {TRAILING_MONTHS}-month average, so "
            f"\"over target\" means more than you usually spend, not more than "
            f"somebody's spreadsheet said."),
    }
