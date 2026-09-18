"""Supply-chain theses, and the research endpoint that serves the whole library.

The tests that matter here are about honesty rather than arithmetic: a thesis
must carry a falsifier, an artifact must not claim a confidence its evidence
does not support, and the four artifact kinds must stay separable so a
supply-chain argument is never presented as a chart signal.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import frameworks, intermarket, setups, theses, web

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


for key, spec in theses.THESES.items():
    check(f"{key} names what would make it wrong",
          spec.get("falsifiers"), "a thesis with no falsifier is a story")
    check(f"{key} records when it was captured", spec.get("as_of"))
    check(f"{key} carries caveats", spec.get("caveats"))
    if spec["confidence"] == "stated":
        check(f"{key} claims 'stated' so it quotes the source", spec.get("quotes"))
    # Every link in the chain has to say what the name is doing there, otherwise
    # the table reads as a list of tickers to buy.
    for link in spec["chain"]:
        check(f"{key}: role {link['role']} explains itself",
              link.get("note") and link.get("names"))

# Access limits belong in the artifact, not in the reader's head: two of the
# names at the centre of this thesis cannot be bought from a US brokerage.
_mem = theses.THESES["legacy-memory-squeeze"]
_text = " ".join(l["note"] for l in _mem["chain"]) + " ".join(_mem["caveats"])
check("legacy-memory-squeeze flags the unreachable names",
      "not reachable" in _text or "out of reach" in _text)
check("legacy-memory-squeeze does not treat 1.9x P/E as a valuation argument",
      any("peak" in c.lower() for c in _mem["caveats"]))

# The four kinds must not collide, or the UI's kind selector would silently
# shadow one artifact with another.
_keys = ([s["key"] for s in setups.catalogue()] + [f["key"] for f in frameworks.catalogue()]
         + [i["key"] for i in intermarket.catalogue()] + [t["key"] for t in theses.catalogue()])
check("artifact keys are unique across all four kinds",
      len(_keys) == len(set(_keys)),
      [k for k in _keys if _keys.count(k) > 1])

VALID = {"stated", "reported", "inferred", "proposed"}
for group, cat in (("setup", setups.catalogue()), ("framework", frameworks.catalogue()),
                   ("intermarket", intermarket.catalogue()), ("thesis", theses.catalogue())):
    for art in cat:
        check(f"{group} {art['key']} declares a known confidence level",
              art.get("confidence") in VALID, art.get("confidence"))
        check(f"{group} {art['key']} names who it came from", art.get("attribution"))

payload = web.research_payload({})
for kind in ("setups", "frameworks", "intermarket", "theses"):
    check(f"research payload serves {kind}", payload.get(kind))

for kind, key in (("thesis", "legacy-memory-squeeze"),
                  ("intermarket", "copper-gold-macd"),
                  ("framework", "jrould-three-buckets"),
                  ("setup", "ronniev-matrix")):
    detail = web.research_payload({"key": [key], "kind": [kind]}).get("detail")
    check(f"research detail resolves {kind}/{key}", detail and not detail.get("error"))

_bad = theses.exposure(None, "no-such-thesis", "2026-08-28")
check("unknown thesis key returns an error dict", "error" in _bad)

# A falsifier or a caveat that is merely truthy is not a falsifier. `spec.get(
# "falsifiers")` above passes on `[""]`, and the whole point of the field is
# that somebody can read it and go and check.
for key, spec in theses.THESES.items():
    check(f"{key}'s falsifiers are sentences, not placeholders",
          all(isinstance(f, str) and len(f) > 30 for f in spec["falsifiers"])
          and len(spec["falsifiers"]) >= 2, spec["falsifiers"][:1])
    check(f"{key} records WHEN it was captured, in a form that sorts",
          len(spec["as_of"]) >= 7 and spec["as_of"][:4].isdigit()
          and spec["as_of"][4] == "-", spec["as_of"])

# The catalogue is the list view. It must NOT carry the chain: a table of
# tickers without the note saying what each name is doing there is exactly the
# "list of tickers to buy" the module says it is not.
check("the catalogue summarises without shipping the chain of names",
      all("chain" not in c and "mechanism" not in c for c in theses.catalogue()),
      [k for c in theses.catalogue() for k in c if k in ("chain", "mechanism")])
check("but it does carry the claim, so the list is readable on its own",
      all(c.get("claim") and c.get("as_of") for c in theses.catalogue()))

# ---------------------------------------------------------------------------
# EXPOSURE against a book that actually holds some of the chain.
#
# The only exposure test was the unknown-key error path. Running it against the
# real ledger does not help: none of these names is held there, so every row
# comes back `held: False, weight: None` — which is precisely the state the
# module's own recorded bug produced ("reading market_value made total 0 and
# every weight None, silently, on every row"). A test that cannot tell the bug
# from the correct answer is not testing anything, so the book is built here.
# ---------------------------------------------------------------------------
from app import holdings as _holdings, ledger as _ledger            # noqa: E402
from app import performance as _performance, prices as _prices      # noqa: E402
from app import watchlist as _watchlist                             # noqa: E402

_conn = _ledger.connect(":memory:")
_inst = _ledger.get_or_create_institution(_conn, "Test")
_acct = _ledger.get_or_create_account(_conn, _inst, "X1", "Brokerage", "brokerage",
                                      "taxable")
_conn.execute("""INSERT INTO transactions (account_id, txn_date, kind, amount,
                                           description, source, source_id)
                 VALUES (?, '2026-01-02', 'deposit', 10000.0, 'seed', 'test', 'd1')""",
              (_acct,))
# NVDA and WDC are on the chain; AAPL is not, and is here so the book has weight
# the thesis does not touch — otherwise every weight would be a share of a book
# made only of thesis names and could not be wrong.
for _sym, _qty, _px in (("NVDA", 10, 100.0), ("WDC", 5, 40.0), ("AAPL", 20, 50.0)):
    _sec = _ledger.get_or_create_security(_conn, _sym)
    _conn.execute(
        """INSERT INTO transactions (account_id, security_id, txn_date, kind, amount,
                                     quantity, price, description, source, source_id)
           VALUES (?, ?, '2026-01-05', 'buy', ?, ?, ?, 'test buy', 'test', ?)""",
        (_acct, _sec, -_qty * _px, _qty, _px, f"t-{_sym}"))
    _prices.store(_conn, _sym, [("2026-08-28", _px * 2, _px * 2, _px * 2, _px * 2, 100)],
                  "test")
_watchlist.ensure_schema(_conn)
# NVDA is BOTH held and on the watchlist; STX is only on the watchlist.
for _w in ("NVDA", "STX"):
    _conn.execute("INSERT OR IGNORE INTO watchlist (symbol) VALUES (?)", (_w,))
_conn.commit()

EXP = theses.exposure(_conn, "legacy-memory-squeeze", "2026-08-28")
_rows = {r["symbol"]: r for r in EXP["links"]}
_chain_names = [n for l in theses.THESES["legacy-memory-squeeze"]["chain"]
                for n in l["names"]]
check("the fixture actually holds part of the chain, or this proves nothing",
      _rows["NVDA"]["held"] and _rows["WDC"]["held"], EXP["held_count"])
check("every name in the chain gets a row, in chain order, once each",
      [r["symbol"] for r in EXP["links"]] == _chain_names,
      [r["symbol"] for r in EXP["links"]])
check("every row carries the role and the note that put the name there",
      all(r["role"] and r["note"] for r in EXP["links"]),
      [r["symbol"] for r in EXP["links"] if not (r["role"] and r["note"])])

# The recorded bug. A held name has to come back with a real weight; None on
# every row is what reading the wrong key looked like, and it failed silently.
_book = sum(p["value"] or 0 for p in _holdings.positions(
    _conn, _performance.load_transactions(_conn, "1900-01-01", "2026-08-28",
                                          "investment"), "2026-08-28"))
check("a held name reports its actual share of the book, not None",
      _rows["NVDA"]["weight"] is not None
      and abs(_rows["NVDA"]["weight"] - 2000.0 / _book * 100) < 0.01,
      (_rows["NVDA"]["weight"], round(2000.0 / _book * 100, 2)))
check("two held names of different size get different weights",
      _rows["WDC"]["weight"] is not None
      and _rows["NVDA"]["weight"] > _rows["WDC"]["weight"] > 0,
      (_rows["NVDA"]["weight"], _rows["WDC"]["weight"]))
check("a name that is not held reports no weight rather than a zero",
      all(r["weight"] is None for r in EXP["links"] if not r["held"]),
      [(r["symbol"], r["weight"]) for r in EXP["links"]
       if not r["held"] and r["weight"] is not None])
check("held_count counts the rows actually in the book",
      EXP["held_count"] == sum(1 for r in EXP["links"] if r["held"]) == 2,
      EXP["held_count"])
# The watchlist number answers "what could you still act on", so a name already
# held must not be counted twice. NVDA is on both lists and belongs only to the
# held one.
check("watchlist_count is what is watched but NOT already held",
      EXP["watchlist_count"] == 1 and _rows["STX"]["watchlist"]
      and _rows["NVDA"]["watchlist"] and _rows["NVDA"]["held"],
      (EXP["watchlist_count"], [r["symbol"] for r in EXP["links"] if r["watchlist"]]))
check("exposure carries the falsifiers with it, so the table is never read alone",
      EXP["falsifiers"] == theses.THESES["legacy-memory-squeeze"]["falsifiers"]
      and EXP["caveats"], list(EXP))

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
