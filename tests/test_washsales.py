"""Wash sales from the ledger's own transactions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import washsales

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def tx(day, sym, qty, price, kind=None):
    return {"txn_date": day, "symbol": sym, "quantity": qty, "price": price,
            "kind": kind or ("buy" if qty > 0 else "sell"), "account": "Brokerage"}


# Sold at a loss, bought back nine days later: the classic wash.
T = [tx("2026-01-05", "IREN", 100, 40.0), tx("2026-02-10", "IREN", -100, 30.0), tx("2026-02-19", "IREN", 100, 31.0)]
r = washsales.past(T)
check("a loss sale with a repurchase inside 30 days is flagged", len(r) == 1 and r[0]["symbol"] == "IREN", r)
check("the whole loss is disallowed when every share is replaced", r and r[0]["disallowed"] == -1000.0, r and r[0]["disallowed"])
check("the replacement date is named", r and r[0]["replacement_dates"] == ["2026-02-19"], r)

# The same trade with the repurchase 31 days later is clean.
T2 = [tx("2026-01-05", "IREN", 100, 40.0), tx("2026-02-10", "IREN", -100, 30.0), tx("2026-03-13", "IREN", 100, 31.0)]
check("a repurchase after the window is not a wash", washsales.past(T2) == [], washsales.past(T2))

# A purchase BEFORE the sale inside 30 days counts too.
T3 = [tx("2026-01-05", "IREN", 100, 40.0), tx("2026-02-01", "IREN", 50, 35.0), tx("2026-02-10", "IREN", -100, 30.0)]
r3 = washsales.past(T3)
check("a purchase in the 30 days before the sale counts", len(r3) == 1, r3)
check("only the replaced share of the loss is disallowed", r3 and r3[0]["partial"] and abs(r3[0]["disallowed"] - (-1000.0 * 0.5)) < 0.01, r3 and r3[0]["disallowed"])

# A gain is never a wash.
T4 = [tx("2026-01-05", "IREN", 100, 20.0), tx("2026-02-10", "IREN", -100, 30.0), tx("2026-02-12", "IREN", 100, 31.0)]
check("a sale at a gain is never flagged", washsales.past(T4) == [], washsales.past(T4))

# Live windows.
w = washsales.windows([tx("2026-08-01", "IREN", 100, 40.0), tx("2026-08-20", "IREN", -100, 30.0),
                       tx("2026-08-25", "ASST", 10, 30.0)], {"IREN": 31.0, "ASST": 27.0}, "2026-09-04")
check("a loss sale 15 days ago is a do-not-rebuy window", len(w["do_not_rebuy"]) == 1 and w["do_not_rebuy"][0]["days_left"] == 15, w["do_not_rebuy"])
check("the window's closing date is 31 days after the sale", w["do_not_rebuy"][0]["window_closes"] == "2026-09-20", w["do_not_rebuy"])
check("a recent buy now underwater is listed", len(w["underwater_recent_buys"]) == 1 and w["underwater_recent_buys"][0]["symbol"] == "ASST", w["underwater_recent_buys"])
check("the note says the count is a floor", "floor" in w["note"])

# A lot bought and sold whole inside a month, nothing rebought, is not a wash:
# the shares sold cannot be their own replacement.
lone = [tx("2026-07-20", "AMPG", 93.376, 6.0), tx("2026-08-17", "AMPG", -93.376, 3.78)]
check("a lot sold whole with no rebuy is not a wash", washsales.past(lone) == [], washsales.past(lone))
# ...but a buy inside the window whose shares stayed held is.
kept = [tx("2026-07-20", "AMPG", 100, 6.0), tx("2026-08-10", "AMPG", 50, 4.0), tx("2026-08-17", "AMPG", -100, 3.78)]
w = washsales.past(kept)
check("a buy inside the window whose shares stayed held replaces that many shares", len(w) == 1 and abs(w[0]["replacement_shares"] - 50) < 1e-6 and w[0]["partial"], w)

# The rebuy warning: the latest loss sale inside the window, per symbol.
import sqlite3
mem = sqlite3.connect(":memory:"); mem.row_factory = sqlite3.Row
mem.execute("CREATE TABLE email_trades (id INTEGER PRIMARY KEY, message_ref TEXT, email_date TEXT, trade_date TEXT, account TEXT, action TEXT, security_name TEXT, symbol TEXT, price REAL, recorded_at TEXT)")
mem.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY, txn_date TEXT, kind TEXT, quantity REAL, security_id INTEGER)")
mem.execute("CREATE TABLE securities (id INTEGER PRIMARY KEY, symbol TEXT, name TEXT, kind TEXT)")
mem.execute("INSERT INTO email_trades (message_ref, email_date, trade_date, account, action, security_name, symbol, price, recorded_at) VALUES ('m1','2026-09-05','2026-09-04','5205','sell','STRIVE INC CL A COM','ASST',26.48,'x')")
warn = washsales.rebuy_warnings(mem, [tx("2026-08-01", "IREN", 100, 40.0), tx("2026-08-20", "IREN", -100, 30.0)], "2026-09-04")
check("a loss sale inside the window warns on that symbol", "IREN" in warn and not warn["IREN"]["possible"] and warn["IREN"]["days_left"] == 15, warn.get("IREN"))
check("a sale seen only in an email warns as possible", "ASST" in warn and warn["ASST"]["possible"], warn.get("ASST"))
check("the ledger's certain warning outranks an email's possible one", not warn["IREN"]["possible"])
check("a name with no recent loss sale has no warning", "TSLA" not in warn)

rep = washsales.report(T, {}, "2026-09-04")
check("the report totals the disallowed losses", rep["disallowed_total"] == -1000.0, rep["disallowed_total"])

failed = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -> {detail}"))
print(f"\n  {len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
sys.exit(1 if failed else 0)
