"""The decision journal: calls made, and whether they were right.

The whole value of this record is that it was written before the outcome was
known, so these tests are mostly about the ways a journal quietly stops being
that: grading on raw return instead of against the index, skipping the holds,
letting the nightly job write the same call twice, or scoring a horizon that has
not elapsed yet.
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import journal as J

CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


def db(series: dict | None = None):
    """An in-memory ledger with just the price rows these tests need."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # The REAL schema, not a hand-rolled stand-in. A local mock of the prices
    # table is how this suite first passed against a column name (`price_date`)
    # that does not exist in the app — the tests were green and nothing they
    # covered could have run against the actual database.
    conn.executescript((Path(__file__).resolve().parent.parent
                        / "app" / "schema.sql").read_text())
    J.ensure_schema(conn)
    for sym, rows in (series or {}).items():
        sid = conn.execute("INSERT INTO securities (symbol, kind) VALUES (?, 'equity')",
                           (sym,)).lastrowid
        for d, c in rows.items():
            conn.execute("""INSERT INTO prices (security_id, bar_date, close,
                                                open, high, low, volume, source)
                            VALUES (?,?,?,?,?,?,0,'test')""", (sid, d, c, c, c, c))
    conn.commit()
    return conn




def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False




def days(start: str, n: int, first: float, step: float) -> dict:
    d0 = date.fromisoformat(start)
    return {(d0 + timedelta(days=i)).isoformat(): first + step * i for i in range(n)}


# A past date so every horizon has elapsed, whenever this suite is run.
PAST = (date.today() - timedelta(days=200)).isoformat()

# ACME doubles; SPY doubles harder. Raw return says the buy was good; measured
# against the index it plainly was not, and that difference is the entire
# reason the benchmark is subtracted.
conn = db({"ACME": days(PAST, 220, 100.0, 0.5),
           "SPY":  days(PAST, 220, 100.0, 1.0)})
J.record(conn, PAST, "ACME", "me", "buy")
g = J.history(conn, symbol="ACME")[0]
h = g["horizons"][21]
check("a call is graded against the index over the same dates",
      h["benchmark"] is not None and h["excess"] < h["return"],
      f"return {h['return']:+.3f} bench {h['benchmark']:+.3f} excess {h['excess']:+.3f}")
check("a buy that rose but lagged the index is scored as wrong",
      h["return"] > 0 and h["right"] is False,
      f"made {h['return']:+.2%} while SPY made {h['benchmark']:+.2%}")

# The same tape, called the other way.
conn2 = db({"DOWN": days(PAST, 220, 100.0, -0.2),
            "SPY":  days(PAST, 220, 100.0, 0.3)})
J.record(conn2, PAST, "DOWN", "me", "sell")
J.record(conn2, PAST, "DOWN", "me", "hold")
sell = [x for x in J.history(conn2, symbol="DOWN") if x["action"] == "sell"][0]
hold = [x for x in J.history(conn2, symbol="DOWN") if x["action"] == "hold"][0]
check("a sell on a name that then underperformed is scored right",
      sell["horizons"][21]["right"] is True)
check("holding that same name is scored WRONG, not skipped",
      hold["horizons"][21]["right"] is False,
      "holding is a decision; a journal that only graded trades would hide it")
check("a sell and a hold on identical facts score opposite",
      sell["horizons"][21]["score"] == -hold["horizons"][21]["score"])
# Reading the constant back out of the module proves only that the module has a
# constant. What matters is that a trim is scored as HALF a sell on the same
# tape, because a trim removes half the exposure and claims half as much.
J.record(conn2, PAST, "DOWN", "me", "trim")
trim = [x for x in J.history(conn2, symbol="DOWN") if x["action"] == "trim"][0]
check("a trim scores as a half-sized sell",
      abs(trim["horizons"][21]["score"] - sell["horizons"][21]["score"] / 2) < 1e-9,
      f"trim {trim['horizons'][21]['score']} vs sell {sell['horizons'][21]['score']}")
check("a trim on a name that fell is still scored right, just less so",
      trim["horizons"][21]["right"] is True
      and abs(trim["horizons"][21]["score"]) < abs(sell["horizons"][21]["score"]))

# --------------------------------------------------------------- horizons ---
recent = (date.today() - timedelta(days=2)).isoformat()
conn3 = db({"NEW": days((date.today() - timedelta(days=10)).isoformat(), 12, 10.0, 0.1),
            "SPY": days((date.today() - timedelta(days=10)).isoformat(), 12, 10.0, 0.1)})
J.record(conn3, recent, "NEW", "me", "buy")
gh = J.history(conn3, symbol="NEW")[0]["horizons"]
check("a horizon that has not elapsed is reported open, never scored",
      gh[63]["status"] == "open", str(gh[63]))
check("an open horizon carries no score at all",
      "score" not in gh[63] and "right" not in gh[63])

# A horizon is measured in TRADING days, so 21 of them is about 29 on the
# calendar. Counting them as calendar days would score every call a week and a
# half early — a real difference on a swing-trading book.
h21 = J.history(conn, symbol="ACME")[0]["horizons"][21]
check("21 trading days is scored roughly 29 calendar days out",
      h21["asof"] == J._plus(PAST, 29), f"{h21['asof']} vs {J._plus(PAST, 29)}")

# ...and the horizon must not land on a day the market was shut and quietly
# report "no price". This fixture trades weekdays only, which is the real shape
# of a price table and the one the every-calendar-day fixtures above never test.
def weekdays(start: str, n: int, first: float, step: float) -> dict:
    out, d, i = {}, date.fromisoformat(start), 0
    while len(out) < n:
        if d.isoweekday() <= 5:
            out[d.isoformat()] = first + step * i
            i += 1
        d += timedelta(days=1)
    return out


# Snapped to a weekday. `today - 200 days` lands on a Saturday two days in
# seven, and on those days the fixture had no bar on the very date the call was
# recorded — so `entry` was None, every horizon reported "no price", and the
# test failed for a reason that had nothing to do with the code. A test whose
# result depends on which day of the week it is run is not testing anything.
_wk_d = date.today() - timedelta(days=200)
while _wk_d.isoweekday() > 5:
    _wk_d += timedelta(days=1)
_wk = _wk_d.isoformat()
conn_wk = db({"WK": weekdays(_wk, 160, 100.0, 0.4),
              "SPY": weekdays(_wk, 160, 100.0, 0.1)})
J.record(conn_wk, _wk, "WK", "me", "buy")
_wh = J.history(conn_wk, symbol="WK")[0]["horizons"]
check("a horizon landing on a closed market still scores, off the last bar",
      all(_wh[h]["status"] == "scored" for h in J.HORIZONS),
      str({h: _wh[h]["status"] for h in J.HORIZONS}))

# A call is graded from the price it was made at, not from whatever that day
# closed at. Overwriting the recorded entry would silently re-grade every call
# whose fill differed from the close, which is most of them.
conn_px = db({"PX": days(PAST, 220, 100.0, 0.5), "SPY": days(PAST, 220, 100.0, 0.5)})
J.record(conn_px, PAST, "PX", "me", "buy", price=50.0)
_pg = J.history(conn_px, symbol="PX")[0]
check("a call is graded from the price it was recorded at",
      _pg["entry"] == 50.0, f"entry {_pg['entry']}, that day's close was 100.0")
check("...and the return is measured from that price, not the day's close",
      _pg["horizons"][21]["return"] > 1.0,
      "a fill at half the close doubled before the index moved at all")

# -------------------------------------------------------------- idempotent --
# The nightly job must be safe to re-run; running it twice used to be the
# easiest way to double-count a day.
conn4 = db({"IDEM": days(PAST, 220, 10.0, 0.1), "SPY": days(PAST, 220, 10.0, 0.1)})
J.record(conn4, PAST, "IDEM", "app", "hold", timeframe="D")
J.record(conn4, PAST, "IDEM", "app", "buy", timeframe="D")
rows = conn4.execute("SELECT action FROM decisions WHERE source='app'").fetchall()
check("re-running the nightly job replaces the day's verdict rather than adding one",
      len(rows) == 1 and rows[0]["action"] == "buy", f"{len(rows)} rows")

# ...but a person really can trade the same name twice in one day.
J.record(conn4, PAST, "IDEM", "me", "buy")
J.record(conn4, PAST, "IDEM", "me", "trim")
mine = conn4.execute("SELECT id FROM decisions WHERE source='me'").fetchall()
check("two decisions of your own on one day are both kept", len(mine) == 2)

# Daily and weekly are separate calls and must not overwrite each other.
J.record(conn4, PAST, "IDEM", "app", "sell", timeframe="W")
app_rows = conn4.execute(
    "SELECT timeframe FROM decisions WHERE source='app' ORDER BY timeframe").fetchall()
check("a weekly verdict does not overwrite the day's daily verdict",
      [r["timeframe"] for r in app_rows] == ["D", "W"])

try:
    J.record(conn4, PAST, "X", "me", "yolo")
    _ok = False
except ValueError:
    _ok = True
check("an action outside buy/add/hold/trim/sell is rejected", _ok)

# -------------------------------------------------------------- scorecard ---
sc = J.scorecard(conn, "me", 21)
check("a scorecard reports its sample size", sc["n"] == 1)
check("a tiny sample is refused a characterisation",
      "far too few" in sc["verdict"], sc["verdict"][:60])
check("the sample floor is stated in the payload", sc["min_sample"] == J.MIN_SAMPLE)
check("the scorecard says it is measured against SPY",
      any("SPY" in c for c in sc["caveats"]))
check("the scorecard says holds are graded too",
      any("Hold is graded" in c for c in sc["caveats"]))

# "0 graded calls" beside a list of recorded ones reads as broken. It is not
# broken, it is early, and the difference is a date the payload has to name.
_open = J.scorecard(conn3, "me", 63)
check("a call too young to grade is counted as recorded, not as scored",
      _open["n"] == 0 and _open["recorded"] == 1 and _open["open"] == 1,
      f"n={_open['n']} recorded={_open['recorded']} open={_open['open']}")
check("...and the scorecard names the date it first becomes gradeable",
      _open["first_grade_on"] == J._plus(recent, int(63 * 7 / 5)),
      str(_open["first_grade_on"]))
check("...rather than characterising a record it has not measured",
      "none old enough to grade" in _open["verdict"], _open["verdict"][:60])

cmp_ = J.compare(conn, 21)
check("comparing you against the app refuses on too little data",
      "Not enough" in cmp_["note"], cmp_["note"][:60])
# "You" is the TRADE record, not calls typed in by hand: there are hundreds of
# the former in the ledger and almost none of the latter, and what you did is
# the honest comparison anyway. This asserted source='me' and kept passing on a
# side that compare() no longer reads.
check("both sides are still reported while the comparison abstains",
      cmp_["app"]["n"] == 0 and cmp_["me"]["n"] == 0,
      "'you' is source='trade'")

# ------------------------------------------------- decisions from trades ----
tconn = db({"TR": days(PAST, 220, 10.0, 0.1), "SPY": days(PAST, 220, 10.0, 0.05)})
sid = tconn.execute("SELECT id FROM securities WHERE symbol='TR'").fetchone()["id"]
aid = tconn.execute("""INSERT INTO institutions (name) VALUES ('X')""").lastrowid
acc = tconn.execute("""INSERT INTO accounts (institution_id, external_id, name, kind)
                       VALUES (?, 'a', 'A', 'brokerage')""", (aid,)).lastrowid
def txn(day, kind, qty, price, sid_=None, n=[0]):
    n[0] += 1
    tconn.execute("""INSERT INTO transactions (account_id, txn_date, kind, security_id,
                                               quantity, price, amount, source, source_id)
                     VALUES (?,?,?,?,?,?,0,'t',?)""",
                  (acc, day, kind, sid_ or sid, qty, price, str(n[0])))

d0 = PAST
d1 = J._plus(PAST, 3)
d2 = J._plus(PAST, 6)
d3 = J._plus(PAST, 9)
# The reinvestment and the flat day each get a day to themselves. Hanging them
# off a day that already has a real trade hides them: the netting collapses both
# into that day's decision, so the assertions below pass whether or not the
# module filters them at all.
d_ri = J._plus(PAST, 1)
d_flat = J._plus(PAST, 4)
txn(d0, "buy", 100, 10.0)          # opens -> buy
txn(d_ri, "reinvest", 5, 10.0)     # never a decision, and alone on its day
txn(d1, "buy", 50, 11.0)           # adds  -> add
txn(d1, "buy", 50, 11.0)           # same day, same order -> still ONE decision
txn(d_flat, "buy", 30, 11.5)       # bought and sold the same size in one day:
txn(d_flat, "sell", -30, 11.5)     # nothing about the position changed
txn(d2, "sell", -20, 12.0)         # 20 of 200 -> trim
txn(d3, "sell", -180, 13.0)        # the rest -> sell
tconn.commit()

res = J.derive_from_trades(tconn)
got = {r["date"]: r["action"] for r in
       tconn.execute("SELECT date, action FROM decisions WHERE source='trade'")}
check("opening a position is a buy", got.get(d0) == "buy", str(got))
check("adding to one is an add, not a second buy", got.get(d1) == "add", str(got))
check("two fills of one order on one day are ONE decision",
      len([d for d in got if d == d1]) == 1 and res["decisions"] == 4,
      f"{res['decisions']} decisions from 8 trade rows")
check("selling a slice is a trim", got.get(d2) == "trim", str(got))
check("selling the rest is a sell", got.get(d3) == "sell", str(got))
check("a reinvested dividend is not a decision anybody made",
      d_ri not in got and res["decisions"] == 4,
      "the broker following a standing instruction is not a view")
check("a day that bought and sold the same size is not a decision either way",
      d_flat not in got and res["skipped_flat_days"] == 1,
      f"{res['skipped_flat_days']} flat days skipped, decisions on {sorted(got)}")

before = res["decisions"]
again = J.derive_from_trades(tconn)
total = tconn.execute("SELECT COUNT(*) n FROM decisions WHERE source='trade'").fetchone()["n"]
check("re-importing does not duplicate the decisions",
      total == before, f"{total} rows after deriving twice")

# ------------------------------------------------------------ cross-check ---
# The comparison the journal was built for: not "does the app score well" but
# "when we disagreed, who was right". None of it was exercised, so the matching
# rules below could all have been inverted without a test noticing.
xc = db({"XX": days(PAST, 220, 10.0, 0.1), "SPY": days(PAST, 220, 10.0, 0.05)})
_t0 = J._plus(PAST, 30)
J.record(xc, _t0, "XX", "trade", "buy", price=10.0)
J.record(xc, _t0, "XX", "app", "add", timeframe="D", price=10.0)
r = J.cross_check(xc, 21)
check("a verdict from the same day is matched to the trade",
      r["matched"] == 1, f"{r['matched']} of {r['trades']} trades matched")
check("buy and add are the same direction, not a disagreement",
      r["agreed"] == 1 and r["disagreed"] == 0,
      "grading 'add' against 'buy' as a conflict would manufacture one")

xc2 = db({"XX": days(PAST, 220, 10.0, 0.1), "SPY": days(PAST, 220, 10.0, 0.05)})
J.record(xc2, _t0, "XX", "trade", "buy", price=10.0)
J.record(xc2, _t0, "XX", "app", "sell", timeframe="D", price=10.0)
r2 = J.cross_check(xc2, 21)
check("buying what the app said to sell is recorded as a disagreement",
      r2["disagreed"] == 1 and r2["agreed"] == 0, str(r2["agreement_rate"]))

# A verdict from a month ago is not what the app was saying at the time. It is
# left unmatched rather than stretched to fit, because a stale verdict scored as
# agreement is exactly how this report would flatter itself.
xc3 = db({"XX": days(PAST, 220, 10.0, 0.1), "SPY": days(PAST, 220, 10.0, 0.05)})
J.record(xc3, _t0, "XX", "trade", "buy", price=10.0)
J.record(xc3, J._plus(PAST, 5), "XX", "app", "buy", timeframe="D", price=10.0)
r3 = J.cross_check(xc3, 21, window_days=5)
check("a verdict older than the window is left unmatched, not stretched to fit",
      r3["matched"] == 0 and r3["rows"][0]["app"] is None,
      f"matched {r3['matched']} against a verdict 25 days stale")
check("...and an unmatched trade is still reported rather than dropped",
      r3["trades"] == 1 and len(r3["rows"]) == 1)
check("with nothing matched the note says so instead of quoting a rate",
      r3["agreement_rate"] is None and "No trade yet falls within" in r3["note"],
      r3["note"][:60])

# --------------------------------------------------------------- evidence ---
# One decision's evidence is keyed by condition and stance. The same condition
# arriving twice in one verdict is one condition, or every attribution query
# counts it double.
ev_conn = db({"EV": days(PAST, 220, 10.0, 0.1), "SPY": days(PAST, 220, 10.0, 0.1)})
J.record(ev_conn, PAST, "EV", "app", "buy", timeframe="D", evidence=[
    {"name": "level", "stance": "bull", "weight": 1.5},
    {"name": "level", "stance": "bull", "weight": 1.0},   # the same thing again
    {"name": "level", "stance": "bear", "weight": 1.0},   # a different stance
    {"name": None, "stance": "bull", "weight": 1.0},      # nameless, unusable
])
_evr = [(r["name"], r["stance"], r["weight"]) for r in
        ev_conn.execute("SELECT name, stance, weight FROM decision_evidence "
                        "ORDER BY stance")]
check("one condition at one stance is stored once per decision",
      _evr == [("level", "bear", 1.0), ("level", "bull", 1.5)], str(_evr))
check("the first weight wins rather than the last",
      ("level", "bull", 1.5) in _evr, "a later duplicate must not overwrite it")

# Recording without evidence must leave what is already stored alone: the CLI
# records verdicts with evidence and other callers record without, and wiping
# on the second would make the evidence table depend on call order.
J.record(ev_conn, PAST, "EV", "app", "sell", timeframe="D")
check("re-recording with no evidence leaves the stored evidence intact",
      ev_conn.execute("SELECT COUNT(*) n FROM decision_evidence").fetchone()["n"] == 2)

# ...but re-recording WITH evidence replaces it. The nightly job re-runs the
# same day, and appending would let one call accumulate conditions until it
# counted several times over in every attribution query.
J.record(ev_conn, PAST, "EV", "app", "hold", timeframe="D",
         evidence=[{"name": "ichimoku", "stance": "bear", "weight": 1.5}])
_after = sorted(r["name"] for r in
                ev_conn.execute("SELECT name FROM decision_evidence"))
check("re-recording a day's verdict replaces its evidence rather than adding to it",
      _after == ["ichimoku"], str(_after))

# Every branch of record() hands back the row it wrote. Callers attach evidence
# and cross-reference with it, so a branch that silently returns None is a
# feature that fails only in the caller.
_ids = db({"RID": days(PAST, 220, 10.0, 0.1), "SPY": days(PAST, 220, 10.0, 0.1)})
_written = {src: J.record(_ids, PAST, "RID", src, "buy",
                          timeframe="D" if src == "app" else None)
            for src in ("app", "me", "trade")}
check("every source returns the id of the row it wrote",
      all(isinstance(i, int) for i in _written.values()), str(_written))
check("...and those ids are the rows actually in the table",
      sorted(_written.values())
      == sorted(r["id"] for r in _ids.execute("SELECT id FROM decisions")),
      str(_written))


# ---- the human half: which book, and what happened ----
from app.ledger import connect as _connect
_jc = _connect(":memory:")
J.ensure_schema(_jc)
_id = J.record(_jc, "2026-09-01", "IREN", "me", "trim", price=40.0,
                     rationale="into the 1.618 extension", bucket="trade-around")
_row = dict(_jc.execute("SELECT * FROM decisions WHERE id=?", (_id,)).fetchone())
check("a hand-logged decision stores the book it was made in",
      _row["bucket"] == "trade-around" and _row["rationale"] == "into the 1.618 extension", _row)
try:
    J.record(_jc, "2026-09-01", "IREN", "me", "buy", bucket="yolo")
    check("an unknown book is refused at record time", False)
except ValueError:
    check("an unknown book is refused at record time", True)
_r = J.set_tag(_jc, _id, "sold too early")
check("an outcome tag is stored on the decision",
      _r.get("ok") and _jc.execute("SELECT tag FROM decisions WHERE id=?", (_id,)).fetchone()[0] == "sold too early", _r)
check("an unknown tag is refused", J.set_tag(_jc, _id, "meh").get("error"))
check("clearing the tag works", J.set_tag(_jc, _id, None).get("ok")
      and _jc.execute("SELECT tag FROM decisions WHERE id=?", (_id,)).fetchone()[0] is None)
_app = J.record(_jc, "2026-09-01", "IREN", "app", "hold", timeframe="D")
J.set_tag(_jc, _app, "chased")
check("the app's own calls cannot be tagged — tags are about your decisions",
      _jc.execute("SELECT tag FROM decisions WHERE id=?", (_app,)).fetchone()[0] is None)
check("graded history carries bucket and tag",
      all("bucket" in g and "tag" in g for g in J.history(_jc, source="me")))
_jc.close()


# ------------------------------------------------- outside calls ----------
# Calls made by the accounts the user follows, graded on the same yardstick.
conn_o = db({"ACME": days(PAST, 220, 100.0, 0.5),
             "SPY":  days(PAST, 220, 100.0, 0.2)})
check("an outside call without an author is refused",
      _raises(lambda: J.record(conn_o, PAST, "ACME", "outside", "buy")))
did1 = J.record(conn_o, PAST, "ACME", "outside", "buy", price=100.0, flip=90.0,
                rationale="buying the shelf", author="Con (@__Con_)")
did2 = J.record(conn_o, PAST, "ACME", "outside", "buy", price=100.0, flip=92.0,
                rationale="buying the shelf, revised", author="Con (@__Con_)")
check("re-recording the same author, symbol and day replaces the row rather than doubling it",
      did1 == did2 and len(J.history(conn_o, source="outside")) == 1,
      (did1, did2, len(J.history(conn_o, source="outside"))))
row = J.history(conn_o, source="outside")[0]
check("the replaced row carries the newer level and note",
      row["flip"] == 92.0 and "revised" in row["rationale"] and row["author"] == "Con (@__Con_)", row)
J.record(conn_o, PAST, "ACME", "outside", "sell", price=100.0, author="The Analyst")
check("a different author on the same symbol and day is a separate call",
      len(J.history(conn_o, source="outside")) == 2)
check("history can be cut by author",
      [g["author"] for g in J.history(conn_o, source="outside", author="The Analyst")] == ["The Analyst"])
rec = J.outside_record(conn_o)
by = {a["author"]: a for a in rec["authors"]}
check("the outside record lists every author with their calls",
      set(by) == {"Con (@__Con_)", "The Analyst"} and by["Con (@__Con_)"]["recorded"] == 1, list(by))
c_buy = by["Con (@__Con_)"]["calls"][0]["horizons"][21]
a_sell = by["The Analyst"]["calls"][0]["horizons"][21]
check("a buy on a name that beat SPY grades right, and the sell on the same tape grades wrong",
      c_buy["right"] is True and a_sell["right"] is False, (c_buy, a_sell))
check("the per-author scorecard refuses to characterise one call",
      "too few" in by["Con (@__Con_)"]["verdict"], by["Con (@__Con_)"]["verdict"])
check("the app's own scorecard does not count outside calls",
      J.scorecard(conn_o, "app")["recorded"] == 0)
r = J.remove_outside(conn_o, did1)
check("an outside call can be removed", r["ok"] and len(J.history(conn_o, source="outside")) == 1)
J.record(conn_o, PAST, "ACME", "me", "buy", price=100.0)
mine = J.history(conn_o, source="me")[0]["id"]
check("the removal path never touches the user's own record",
      not J.remove_outside(conn_o, mine)["ok"] and len(J.history(conn_o, source="me")) == 1)

# ---- windowed price loads grade exactly like the full series ---------------
# history() loads each symbol's prices from the first date the batch needs
# rather than all of them. A shared cache (outside_record reuses one across
# fifty history() calls) can then meet an EARLIER call on a symbol it already
# holds — that must widen the window, not read as "no price".
w_conn = db({"WIN": days(PAST, 220, 10.0, 0.1), "SPY": days(PAST, 220, 10.0, 0.05)})
late = (date.fromisoformat(PAST) + timedelta(days=100)).isoformat()
early = (date.fromisoformat(PAST) + timedelta(days=3)).isoformat()
J.record(w_conn, late, "WIN", "outside", "buy", author="A")
J.record(w_conn, early, "WIN", "outside", "buy", author="B")
shared: dict = {}
J.history(w_conn, source="outside", author="A", cache=shared)       # loads WIN from `late`
b_rows = J.history(w_conn, source="outside", author="B", cache=shared)
full = J.grade(w_conn, dict(w_conn.execute("SELECT * FROM decisions WHERE author='B'").fetchone()), {})
check("an earlier call on an already-cached symbol widens the window and grades",
      b_rows and b_rows[0]["horizons"][21]["status"] == "scored", b_rows and b_rows[0]["horizons"])
check("and the windowed grade equals the full-series grade exactly", b_rows and b_rows[0] == full)
rec = J.outside_record(w_conn)
check("outside_record grades every author's calls from one shared load",
      all(c["horizons"][21]["status"] == "scored" for a in rec["authors"] for c in a["calls"]),
      [(a["author"], [c["horizons"][21]["status"] for c in a["calls"]]) for a in rec["authors"]])

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
