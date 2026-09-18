"""Alerts: what fires, what does not fire twice, and what gets sent."""
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import alerts
from app.ledger import connect

CHECKS = []
def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))

NY = ZoneInfo("America/New_York")
check("a weekday at 10:00 New York is open", alerts.market_open(datetime(2026, 9, 2, 10, 0, tzinfo=NY)))
check("the same day at 17:00 is closed", not alerts.market_open(datetime(2026, 9, 2, 17, 0, tzinfo=NY)))
check("a Saturday is closed", not alerts.market_open(datetime(2026, 9, 5, 11, 0, tzinfo=NY)))
check("07:00 Pacific on a weekday is 10:00 New York, open",
      alerts.market_open(datetime(2026, 9, 2, 7, 0, tzinfo=ZoneInfo("America/Los_Angeles"))))

run = {
    "changed": [
        {"symbol": "IREN", "timeframe": "D", "verdict": "hold", "from": "sell", "kind": "changed",
         "price": 39.6, "because": ["the evidence is 45% bullish"]},
        {"symbol": "TEM", "timeframe": "W", "verdict": "add", "kind": "new", "price": 66.0, "because": []},
    ],
    "results": {
        "IREN": {"daily": {"verdict": "hold", "price": 39.6,
                           "watch": {"price": 39.6, "buy_at": 39.2, "trim_at": 48.0, "stop_at": 35.0}}},
        "DGXX": {"daily": {"verdict": "hold", "price": 3.20,
                           "watch": {"price": 3.20, "buy_at": None, "trim_at": None, "stop_at": 3.29}}},
        "ASST": {"daily": {"verdict": "trim", "price": 30.0,
                           "watch": {"price": 30.0, "buy_at": None, "trim_at": 24.68, "stop_at": 20.0}}},
        "SOFI": {"daily": {"verdict": "hold", "price": 16.0, "watch": {"price": 16.0}}},
    },
}
ups = {"SOFI": {"date": "2026-09-05", "days": 3, "timing": "after-hours"},
       "IREN": {"date": "2026-11-12", "days": 71, "timing": "unknown"}}
got = alerts.from_outlook(run, ups, "2026-09-02")
keys = {a["key"] for a in got}
msgs = {a["key"]: a["message"] for a in got}
check("a changed verdict is an act-level alert naming from and to",
      "verdict:IREN:D:2026-09-02" in keys and "SELL → HOLD" in msgs["verdict:IREN:D:2026-09-02"], msgs)
check("a first reading is info, not act",
      any(a["key"].startswith("first:TEM") and a["level"] == "info" for a in got))
check("price merely near the buy-at level does NOT fire",
      "level:IREN:buy_at:2026-09-02" not in keys, sorted(keys))
check("a close below the stop fires as through, not near",
      "level:DGXX:stop-through:2026-09-02" in keys and "BELOW its stop" in msgs["level:DGXX:stop-through:2026-09-02"])
check("a close through the trim level fires",
      "level:ASST:trim-through:2026-09-02" in keys)
check("earnings inside five days fires once per report, keyed by the date",
      "earnings:SOFI:2026-09-05" in keys and "in 3 days" in msgs["earnings:SOFI:2026-09-05"])
check("earnings ten weeks out does not fire", not any(k.startswith("earnings:IREN") for k in keys))
run2 = {"changed": [], "results": {"IREN": {"daily": {"verdict": "hold", "price": 39.6,
        "watch": {"price": 39.6, "buy_at": 39.48, "trim_at": 48.0, "stop_at": 39.48}}}}}
got2 = alerts.from_outlook(run2, {}, "2026-09-02")
check("with the near-level alerts gone, a name sitting on its levels is silent",
      [a["key"] for a in got2] == [], [a["key"] for a in got2])
check("a name with no levels and nothing coming produces nothing",
      not any(a["symbol"] == "SOFI" and a["kind"] != "earnings" for a in got))

# ---- delivery: stored once, sent once, by level ----
conn = connect(":memory:")
alerts.ensure_schema(conn)
sent = []
senders = {"fake": lambda title, body: (sent.append((title, body)) or True)}
cfg = {"ntfy_topic": None, "macos": False, "min_level": "warn"}
r1 = alerts.deliver(conn, got, cfg, senders)
check("every alert is stored", r1["stored"] == len(got), r1)
check("only alerts at or above the configured level are sent",
      r1["sent"] == sum(1 for a in got if a["level"] != "info") and len(sent) == r1["sent"], (r1, len(sent)))
r2 = alerts.deliver(conn, got, cfg, senders)
check("the same run delivered again stores and sends nothing", r2["stored"] == 0 and r2["sent"] == 0, r2)
check("what was sent is marked with its channel",
      conn.execute("SELECT COUNT(*) FROM alerts WHERE sent_at IS NOT NULL AND channel='fake'").fetchone()[0] == r1["sent"])
# `recent()` counts back from TODAY, so this row's day has to as well. It was
# hard-coded to 2026-09-02 and passed until the date rolled to 2026-09-10, when
# the seven-day window started at 09-03 and the row fell out of it — a test that
# depended on the day it was run, which is the thing the suite exists to catch.
_today = date.today().isoformat()
check("a failing channel is reported, not raised",
      alerts.deliver(conn, [alerts._alert("x", "Q", "act", "m", "k1", _today)], cfg,
                     {"bad": lambda t, b: (_ for _ in ()).throw(RuntimeError("down"))})["failed"] == [("bad", "RuntimeError")])
check("the last week is readable back, newest first",
      [a["key"] for a in alerts.recent(conn, 7)][:1] == ["k1"],
      [a["key"] for a in alerts.recent(conn, 7)][:3])

# ---- levels kept for the poll ----
alerts.store_levels(conn, "2026-09-01", "IREN", "hold", {"price": 40.0, "buy_at": 39.0, "trim_at": 48.0, "stop_at": 35.0, "flip": 36.0})
alerts.store_levels(conn, "2026-09-02", "IREN", "hold", {"price": 39.6, "buy_at": 39.2, "trim_at": 48.0, "stop_at": 35.5, "flip": 36.5})
lv = alerts.latest_levels(conn, "IREN", "2026-09-02")
check("the poll reads the most recent call's levels", lv and lv["stop_at"] == 35.5 and lv["flip"] == 36.5, lv)
check("and as of an earlier day, that day's", alerts.latest_levels(conn, "IREN", "2026-09-01")["stop_at"] == 35.0)
conn.close()


# ---- the user's own levels ----
lv = alerts.from_levels({"ASST": [26.57], "TEM": [62.0, 58.0], "SOFI": [19.2]},
                        {"ASST": (26.82, 24.32), "TEM": (64.66, 61.94), "SOFI": (18.51, 17.84)}, "2026-09-03")
lk = {a["key"]: a for a in lv}
check("closing through a hand-drawn level is an alert saying which side price is now on",
      any("ASST" in k for k in lk) and "ABOVE your 26.57" in lk["mylevel:ASST:26.5700:2026-09-03"]["message"], lk)
check("a level crossed today alerts, one not reached does not",
      "mylevel:TEM:62.0000:2026-09-03" in lk and "mylevel:TEM:58.0000:2026-09-03" not in lk, sorted(lk))
# Being NEAR a level no longer alerts, on the app's levels or the user's own.
# It was 103 of the last 138 alerts and it is an event, not a reason to act.
check("a close merely NEAR a level does not alert at all",
      alerts.from_levels({"SOFI": [18.6]}, {"SOFI": (18.51, 17.84)}, "2026-09-03") == [],
      "18.51 against an 18.60 level is 0.5% away and used to fire")
check("...but actually crossing it still does",
      len(alerts.from_levels({"SOFI": [18.6]}, {"SOFI": (18.90, 17.84)}, "2026-09-03")) == 1)
check("intraday level alerts carry their own key and wording",
      alerts.from_levels({"ASST": [26.57]}, {"ASST": (26.82, 24.32)}, "2026-09-03", intraday=True)[0]["key"]
      == "intraday:mylevel:ASST:26.5700:2026-09-03")
check("no price, no alert", alerts.from_levels({"X": [1.0]}, {}, "2026-09-03") == [])
# what the alert means: the app's call and the next levels ride along as detail
_calls = {"ASST": {"daily": "trim", "daily_confidence": "medium", "weekly": "hold", "weekly_confidence": "medium",
                   "headline": "hold", "headline_tf": "monthly", "because": "at the 1.000 extension",
                   "book": "swing", "horizon": "days to weeks",
                   "buy_at": 24.68, "buy_now": False, "sell_into": 28.59,
                   "next_up": 28.59, "next_down": 24.68, "stop_at": 18.69}}
_la = alerts.from_levels({"ASST": [26.57]}, {"ASST": (26.82, 24.32)}, "2026-09-03", calls=_calls)[0]
check("a level alert says which way the level now faces",
      "now acts as support" in _la["detail"], _la["detail"])
# The alert used to open "daily TRIM (medium), weekly HOLD, headline HOLD on
# the monthly" — three verdicts and no plan. "The day week month thing doesn't
# really click. The values depend on the length of the trade."
check("the alert leads with the holding period, not a grid of timeframes",
      "swing (days to weeks)" in _la["detail"]
      and "headline HOLD on the monthly" not in _la["detail"], _la["detail"])
check("and gives the three levels named for what you would DO at each",
      "BUY AT 24.68" in _la["detail"] and "SELL INTO 28.59" in _la["detail"]
      and "WRONG BELOW 18.69" in _la["detail"], _la["detail"])
check("and says outright when there is nothing to do between them",
      "Nothing to do between 18.69 and 28.59." in _la["detail"], _la["detail"])
check("and still carries the reason",
      "Why: at the 1.000 extension" in _la["detail"], _la["detail"])
# "If it gives me a buy level or sell level it should also tell me the upside
# or downside target of the move."
_tg = alerts.from_levels({"ASST": [26.57]}, {"ASST": (26.82, 24.32)}, "2026-09-03",
                         calls={"ASST": {**_calls["ASST"], "buy_target": 31.0,
                                         "buy_target_pct": 25.6, "buy_risk_pct": -24.3,
                                         "buy_rr": 1.1, "sell_target": 22.5,
                                         "sell_target_pct": -21.3}})[0]
check("a buy level says what the move is worth, measured from the entry",
      "Buying 24.68 targets 31.00 (+26%) against 18.69 (-24%) — 1.1 to 1."
      in _tg["detail"], _tg["detail"])
check("a sell level says where the pullback is expected to go",
      "Selling into 28.59 targets a pullback to 22.50 (-21%)." in _tg["detail"],
      _tg["detail"])
check("a level with no target stays a bare level rather than inventing one",
      "targets" not in _la["detail"], _la["detail"])
# A blank side reads as an oversight. It is a finding, so it is said.
_bare = alerts.from_levels({"ASST": [26.57]}, {"ASST": (26.82, 24.32)}, "2026-09-03",
                           calls={"ASST": {"book": "swing", "horizon": "days to weeks",
                                           "stop_at": 18.69}})[0]
check("a side with no level worth trading says so rather than going blank",
      "No buy level, no sell level — nothing tested enough on that side to trade."
      in _bare["detail"], _bare["detail"])
check("a buy level price is already standing on says so in the alert",
      "price is at it now" in alerts.from_levels(
          {"ASST": [26.57]}, {"ASST": (26.82, 24.32)}, "2026-09-03",
          calls={"ASST": {"buy_at": 26.40, "buy_now": True}})[0]["detail"])
check("without a call the detail still explains the level",
      "resistance" in alerts.from_levels({"X": [10.0]}, {"X": (9.0, 11.0)}, "2026-09-03")[0]["detail"])
_sent = []
_c = connect(":memory:")
alerts.deliver(_c, [_la], {"min_level": "act"}, senders={"t": lambda title, body: (_sent.append(body), True)[1]})
check("the delivered body carries the detail after the message and the row stores it",
      _sent and _la["detail"] in _sent[0] and _c.execute("select detail from alerts").fetchone()[0] == _la["detail"], _sent[:1])

# ---- how few get pushed --------------------------------------------------
# "When market opens i get smacked with like 20 notifications and i dont have
# time to read them all." 17-26 fired daily and every one was sent, because
# nothing capped it. Twenty well-worded alerts are functionally zero.
_c2 = connect(":memory:")
alerts.ensure_schema(_c2)
_many = [alerts._alert("level", f"S{i}", "act", f"m{i}", f"kk{i}", _today) for i in range(20)]
_got2 = []
_r = alerts.deliver(_c2, _many, {"min_level": "act", "max_push": 4},
                    {"t": lambda ti, b: (_got2.append((ti, b)), True)[1]})
check("twenty alerts do not become twenty notifications",
      _r["pushed"] == 4 and _r["digested"] == 16, _r)
check("...they become five: the four that matter and one digest",
      len(_got2) == 5, len(_got2))
check("all twenty are still STORED, so the Overview shows everything",
      _r["stored"] == 20 and _c2.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 20)
check("the digest names the symbols rather than just counting them",
      "16 more alerts" in _got2[-1][1] and "S12" in _got2[-1][1], _got2[-1][1])
check("the digested ones are marked sent, or they fire again next run — which "
      "is the flood this exists to stop",
      _c2.execute("SELECT COUNT(*) FROM alerts WHERE sent_at IS NULL").fetchone()[0] == 0)

# Ranked by consequence: severity first, then how much money the position is.
_vals = {"BIG": 190000.0, "MID": 20000.0, "SMALL": 900.0}
_ranked = alerts.rank(_c2, [alerts._alert("level", "SMALL", "act", "m", "r1", _today),
                            alerts._alert("level", "BIG", "act", "m", "r2", _today),
                            alerts._alert("regime", None, "warn", "m", "r3", _today),
                            alerts._alert("level", "MID", "act", "m", "r4", _today)])
check("an 'act' outranks a 'warn' however big the position",
      _ranked[-1]["kind"] == "regime", [a["symbol"] for a in _ranked])
_c2.close()

# a stale series gives no "price now": the nightly must not alert on it
from app import prices as _prices
_orig_load = _prices.load_bars
def _fake_load(conn, sym, start, end):
    return {"STALE": [{"time": "2026-08-27", "close": 2.9}, {"time": "2026-08-28", "close": 3.0}],
            "FRESH": [{"time": "2026-09-02", "close": 3.0}, {"time": "2026-09-03", "close": 3.5}]}.get(sym, [])
_prices.load_bars = _fake_load
try:
    _cl = alerts._closes(None, ["STALE", "FRESH"], "2026-09-03")
finally:
    _prices.load_bars = _orig_load
check("a symbol whose newest bar is days old is left out of the level check, a fresh one is in",
      "STALE" not in _cl and _cl.get("FRESH") == (3.5, 3.0), _cl)

# ------------------------------------------------ statement reminders ----
# Cards, the bank, Fidelity and the pay stubs cannot pull themselves; once an
# export is five weeks old the nightly says so, once a week, until it lands.
_s = connect(":memory:")
_s.execute("INSERT INTO institutions (id, name) VALUES (1, 'T')")
for i, (name, kind) in enumerate([("Frost", "checking"), ("Amex", "credit"), ("Individual", "brokerage"), ("ROTH IRA", "retirement")], 1):
    _s.execute("INSERT INTO accounts (id, institution_id, external_id, name, kind) VALUES (?,1,?,?,?)", (i, str(i), name, kind))
for acct, day in [(1, "2026-08-01"), (2, "2026-09-10"), (3, "2026-07-01"), (4, "2026-09-09")]:
    _s.execute("INSERT INTO transactions (account_id, txn_date, kind, amount, source, source_id) VALUES (?,?,'debit',-1,'t',?)", (acct, day, f"{acct}-{day}"))
_rem = alerts.statement_reminders(_s, "2026-09-13")
_names = [a["message"].split(":")[0] for a in _rem]
check("a bank export five weeks old is due", "Frost" in _names, _names)
check("a card exported this week is not", "Amex" not in _names, _names)
check("Fidelity's accounts are one reminder, dated by the newest of them",
      "Fidelity (all accounts)" not in _names, _names)
check("the message says where the file goes", any("data/bank/" in a["message"] for a in _rem), _rem)
check("it is keyed to the week, so it returns until the export lands",
      all("2026w37" in a["key"] for a in _rem), [a["key"] for a in _rem])
check("nothing is due while every export is under five weeks old", alerts.statement_reminders(_s, "2026-08-20") == [], alerts.statement_reminders(_s, "2026-08-20"))
_s.close()

passed = sum(1 for _, ok, _ in CHECKS if ok)
for label, ok, detail in CHECKS:
    if not ok:
        print(f"  FAIL  {label}  {detail}")
print(f"{passed}/{len(CHECKS)} passed")
sys.exit(0 if passed == len(CHECKS) else 1)
