-- Investment App — unified ledger
-- One ledger serves both the portfolio and the budget (decision D7).
-- SQLite: zero install, zero server, portable. Migrate later if it ever outgrows this.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS institutions (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE
);

-- kind:       brokerage | retirement | hsa | checking | savings | credit | crypto
-- tax_status: taxable | tax_deferred | tax_free | hsa | na
--   tax_status is what powers the "taxable only" toggle on the performance chart (D12):
--   accounts with payroll contributions flowing in distort a combined return number.
CREATE TABLE IF NOT EXISTS accounts (
    id             INTEGER PRIMARY KEY,
    institution_id INTEGER NOT NULL REFERENCES institutions(id),
    external_id    TEXT NOT NULL,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL,
    tax_status     TEXT NOT NULL DEFAULT 'na',
    currency       TEXT NOT NULL DEFAULT 'USD',
    is_active      INTEGER NOT NULL DEFAULT 1,
    UNIQUE (institution_id, external_id)
);

CREATE TABLE IF NOT EXISTS securities (
    id      INTEGER PRIMARY KEY,
    symbol  TEXT NOT NULL UNIQUE,
    name    TEXT,
    kind    TEXT NOT NULL DEFAULT 'equity'   -- equity | etf | mutual_fund | money_market | crypto | other
);

CREATE TABLE IF NOT EXISTS categories (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES categories(id),
    kind      TEXT NOT NULL DEFAULT 'expense' -- expense | income | transfer | investment
);

-- Merchant-pattern rules for budget categorization (D9).
-- The LLM only ever sees what these fail to match, and each LLM decision
-- is written back here as a new rule, so model usage trends toward zero.
CREATE TABLE IF NOT EXISTS category_rules (
    id          INTEGER PRIMARY KEY,
    pattern     TEXT NOT NULL,            -- matched case-insensitively against description
    category_id INTEGER NOT NULL REFERENCES categories(id),
    priority    INTEGER NOT NULL DEFAULT 100,
    origin      TEXT NOT NULL DEFAULT 'manual',  -- manual | llm
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- kind vocabulary:
--   buy sell dividend interest reinvest contribution deposit withdrawal
--   transfer_in transfer_out fee tax split exchange_in exchange_out
--   debit credit other
-- amount is ALWAYS the signed cash impact on the account.
-- (source, source_id) is the idempotency key: re-importing an overlapping
-- export is a no-op. Frost supplies a real FITID; Fidelity CSV has no such
-- key, so one is synthesized — see importers/fidelity_csv.py.
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    txn_date    TEXT NOT NULL,            -- ISO yyyy-mm-dd
    settle_date TEXT,
    kind        TEXT NOT NULL,
    security_id INTEGER REFERENCES securities(id),
    quantity    REAL,
    price       REAL,
    amount      REAL NOT NULL,
    fees        REAL NOT NULL DEFAULT 0,
    commission  REAL NOT NULL DEFAULT 0,
    description TEXT,
    category_id INTEGER REFERENCES categories(id),
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    raw         TEXT,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS ix_txn_account_date ON transactions (account_id, txn_date);
CREATE INDEX IF NOT EXISTS ix_txn_date         ON transactions (txn_date);
CREATE INDEX IF NOT EXISTS ix_txn_security     ON transactions (security_id, txn_date);

-- Daily price bars, cached forever. A bar is immutable: pay for it once.
CREATE TABLE IF NOT EXISTS prices (
    security_id INTEGER NOT NULL REFERENCES securities(id),
    bar_date    TEXT NOT NULL,
    open        REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
    source      TEXT NOT NULL,
    PRIMARY KEY (security_id, bar_date)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    path          TEXT NOT NULL,
    rows_seen     INTEGER NOT NULL DEFAULT 0,
    rows_inserted INTEGER NOT NULL DEFAULT 0,
    rows_skipped  INTEGER NOT NULL DEFAULT 0,
    ran_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per key. `cache_epoch` counts meaningful writes (see ledger.py):
-- the dashboard's response cache is keyed on it instead of the file's mtime,
-- so an intraday candle refresh no longer drops every cached answer.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
