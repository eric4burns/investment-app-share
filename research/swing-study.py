"""The swing study: sell a slice near the top, buy it back lower, end with
more shares than holding.

The user's objective in one sentence: "sell IREN near 80 and buy back in the
upper 20s to low 30s." Nobody picks the top. What can be tested is a written
rule that sells a SLICE when momentum changes and buys it back at a level named
at the sale, run over the actual history of the conviction names since 2022,
scored on the one number that matters for a name you intend to keep: how many
shares you end with against simply holding.

Book: a core of half the shares that is never sold, and a slice of half that
each rule trades. Every rule starts with 1,000 shares on the first bar. Cash
from a sale waits for the rule's rebuy; if the rebuy never comes the cash is
held to the end and counted (a rule that sells the winner and never gets back
in is the failure the user named). Trades are at the close, no costs, no tax —
both would make every rule look worse than holding, and the study says so.

Rules, each from a person on the user's list, made mechanical:

  leader     LEADER_TRADING. After a run (close at least 15% above the 20-day
             average), a day that fails to exceed the prior day's high and
             closes below the prior close sells the slice. Rebuy at the lower
             of 5% below the sale or the 20-day average, within 30 sessions;
             else rebuy at the close on session 30 (a chase, counted).
  extension  StonkChris. Anchor the prior cycle high (highest close in the year
             before the trailing 250-day low) and that low; sell half the slice
             at the 1.618 extension and half at 2.0; rebuy at the 1.0 (the
             prior high) if price comes back to it.
  rsi_break  StonkChris's sell: the weekly RSI, having been 70 or more in the
             last eight weeks, closes below its 10-week average — sell the
             slice. Rebuy when the weekly RSI closes at or under 35, or price
             closes back above the 10-week average after at least four weeks.
  cloud      The forgiving exit: after 40 sessions above the daily cloud, the
             first close below it sells the slice; rebuy on the first close
             back above the cloud.
  parabolic  A week that gains 25% or more, then a week that closes below the
             prior week's open, sells the slice; rebuy at a touch of the
             10-week average within 26 weeks, else at week 26.

    python3 research/swing-study.py [--md out.md] [--symbols IREN,SIVEF,CIFR,ASST]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import indicators as I, ledger, prices  # noqa: E402

START = "2022-01-01"
SLICE = 0.5


def load(conn, sym):
    bars = [b for b in prices.load_bars(conn, sym, "2021-01-01", "2030-01-01")]
    return bars


def sim(bars, decide):
    """decide(state, i) -> ('sell', fraction) | ('buy', None) | None, on daily closes."""
    n = len(bars)
    shares_core = 500.0
    slice_shares, cash = 500.0, 0.0
    trades, chases, log = 0, 0, []
    sold_at = None
    state = {"bars": bars, "sold_at": None, "sell_i": None, "slice_out": False}
    for i in range(30, n):
        act = decide(state, i)
        px = bars[i]["close"]
        if act and act[0] == "sell" and slice_shares > 0:
            frac = act[1] or 1.0
            qty = slice_shares * frac
            cash += qty * px; slice_shares -= qty; trades += 1
            state.update(sold_at=px, sell_i=i, slice_out=slice_shares <= 1e-9)
            log.append((bars[i]["time"], "sell", round(qty, 1), px))
        elif act and act[0] == "buy" and cash > 0:
            qty = cash / px
            slice_shares += qty; cash = 0.0; trades += 1
            if act[1] == "chase":
                chases += 1
            state.update(sold_at=None, sell_i=None, slice_out=False)
            log.append((bars[i]["time"], "buy", round(qty, 1), px))
    end_px = bars[-1]["close"]
    shares = shares_core + slice_shares
    return {"shares": round(shares, 1), "cash": round(cash, 2), "value": round(shares * end_px + cash, 2),
            "trades": trades, "chases": chases, "log": log}


# ---- rules -------------------------------------------------------------------
def rule_leader(bars):
    sma20 = {x["time"]: x["value"] for x in I.sma(bars, 20)}
    def decide(st, i):
        b, p = bars[i], bars[i - 1]
        m = sma20.get(b["time"])
        if st["sold_at"] is None:
            if m and b["close"] >= 1.15 * m and b["high"] <= p["high"] and b["close"] < p["close"]:
                return ("sell", 1.0)
        else:
            target = min(st["sold_at"] * 0.95, m or 1e9)
            if b["low"] <= target:
                return ("buy", None)
            if i - st["sell_i"] >= 30:
                return ("buy", "chase")
        return None
    return decide


def rule_extension(bars):
    closes = [b["close"] for b in bars]
    def decide(st, i):
        b = bars[i]
        lo_i = min(range(max(0, i - 250), i + 1), key=lambda k: closes[k])
        low = closes[lo_i]
        prior = closes[max(0, lo_i - 250):lo_i] or [low]
        high = max(prior)
        if high <= low * 1.2:
            return None                       # no cycle to measure
        leg = high - low
        e1618, e20, one = low + 1.618 * leg, low + 2.0 * leg, high
        if not st.get("sold_half") and st["sold_at"] is None and b["close"] >= e1618:
            st["sold_half"] = True; st["anchor"] = (low, high)
            return ("sell", 0.5)
        if st.get("sold_half") and not st.get("sold_all") and b["close"] >= e20:
            st["sold_all"] = True
            return ("sell", 1.0)
        if (st.get("sold_half") or st.get("sold_all")) and st.get("anchor"):
            lo0, hi0 = st["anchor"]
            if b["close"] <= hi0:
                st["sold_half"] = st["sold_all"] = False; st["anchor"] = None
                return ("buy", None)
        return None
    return decide


def rule_rsi_break(bars):
    weekly = I.resample(bars, "W")
    rsi = {x["time"]: x["value"] for x in I.rsi(weekly, 14)}
    sma10 = {x["time"]: x["value"] for x in I.sma(weekly, 10)}
    wk_by_time = {w["time"]: k for k, w in enumerate(weekly)}
    rsi_series = [(w["time"], rsi.get(w["time"])) for w in weekly]
    week_of_day = {}
    j = 0
    for b in bars:
        while j + 1 < len(weekly) and weekly[j]["time"] < b["time"]:
            j += 1
        week_of_day[b["time"]] = j
    def decide(st, i):
        b = bars[i]
        k = week_of_day.get(b["time"])
        if k is None or k < 12 or weekly[k]["time"] != b["time"]:
            return None                        # act on the weekly close only
        r = rsi.get(weekly[k]["time"]); m = sma10.get(weekly[k]["time"])
        recent = [rsi_series[q][1] for q in range(max(0, k - 8), k) if rsi_series[q][1] is not None]
        rsi_ma = sum(x for _, x in rsi_series[max(0, k - 10):k] if x is not None) / max(1, len([x for _, x in rsi_series[max(0, k - 10):k] if x is not None]))
        if st["sold_at"] is None:
            if r is not None and recent and max(recent) >= 70 and r < rsi_ma:
                return ("sell", 1.0)
        else:
            weeks_out = k - week_of_day.get(bars[st["sell_i"]]["time"], k)
            if r is not None and r <= 35:
                return ("buy", None)
            if m and weekly[k]["close"] > m and weeks_out >= 4:
                return ("buy", None)
        return None
    return decide


def rule_cloud(bars):
    ich = I.ichimoku(bars)
    top = {}
    bot = {}
    for a, bb in zip(ich["span_a"], ich["span_b"]):
        if a["value"] is not None and bb["value"] is not None:
            top[a["time"]] = max(a["value"], bb["value"]); bot[a["time"]] = min(a["value"], bb["value"])
    above_run = {"n": 0}
    def decide(st, i):
        b = bars[i]; t, lo = top.get(b["time"]), bot.get(b["time"])
        if t is None:
            return None
        if b["close"] > t:
            above_run["n"] += 1
        elif b["close"] < lo:
            was = above_run["n"]; above_run["n"] = 0
            if st["sold_at"] is None and was >= 40:
                return ("sell", 1.0)
        if st["sold_at"] is not None and b["close"] > t:
            return ("buy", None)
        return None
    return decide


def rule_parabolic(bars):
    weekly = I.resample(bars, "W")
    sma10 = {x["time"]: x["value"] for x in I.sma(weekly, 10)}
    idx = {w["time"]: k for k, w in enumerate(weekly)}
    def decide(st, i):
        b = bars[i]; k = idx.get(b["time"])
        if k is None or k < 2:
            return None                        # weekly closes only
        w, pw = weekly[k], weekly[k - 1]
        if st["sold_at"] is None:
            if pw["close"] / pw["open"] - 1 >= 0.25 and w["close"] < pw["open"]:
                return ("sell", 1.0)
        else:
            m = sma10.get(w["time"]); k0 = idx.get(bars[st["sell_i"]]["time"], k)
            if m and w["low"] <= m:
                return ("buy", None)
            if k - k0 >= 26:
                return ("buy", "chase")
        return None
    return decide


def rule_extension_swing(bars, lookback=120):
    """The extension re-anchored on the current leg: the low of the last
    `lookback` sessions and the highest close before that low within the same
    window. Sell half the slice at 1.618 of that leg, all at 2.0, and rebuy at
    the leg's 1.0 (the prior swing high) — or, if a new low forms 20% under the
    anchor low, treat the leg as over and rebuy there."""
    closes = [b["close"] for b in bars]
    def decide(st, i):
        b = bars[i]
        w0 = max(0, i - lookback)
        lo_i = min(range(w0, i + 1), key=lambda k: closes[k])
        low = closes[lo_i]
        prior = closes[w0:lo_i] or [low]
        high = max(prior)
        if st["sold_at"] is None and not st.get("half"):
            if high > low * 1.15 and b["close"] >= low + 1.618 * (high - low):
                st["half"] = True; st["anchor"] = (low, high)
                return ("sell", 0.5)
            return None
        if st.get("half") and not st.get("all") and st.get("anchor"):
            lo0, hi0 = st["anchor"]
            if b["close"] >= lo0 + 2.0 * (hi0 - lo0):
                st["all"] = True
                return ("sell", 1.0)
        if st.get("anchor"):
            lo0, hi0 = st["anchor"]
            if b["close"] <= hi0 or b["close"] <= lo0 * 0.8:
                st["half"] = st["all"] = False; st["anchor"] = None
                return ("buy", None)
        return None
    return decide


# ---- rules from the anatomy of the names themselves (research/anatomy.py) ----
def rule_anatomy_a(bars):
    """Sell the slice when price is 150% or more above the 200-day (on IREN this
    fired three times, two followed by 50%+ falls); buy it back when price is
    60% or more under its 52-week high (fired five times, four followed by
    50%+ rises, within 9% of the low in median)."""
    sma200 = {x["time"]: x["value"] for x in I.sma(bars, 200)}
    closes = [b["close"] for b in bars]
    def decide(st, i):
        b = bars[i]; m = sma200.get(b["time"]); c = closes[i]
        hi52 = max(closes[max(0, i - 250):i + 1])
        if st["sold_at"] is None:
            if m and c / m - 1 >= 1.5:
                return ("sell", 1.0)
        else:
            if c / hi52 - 1 <= -0.60:
                return ("buy", None)
        return None
    return decide


def rule_anatomy_b(bars):
    """Sell when the weekly RSI, having been 80 or more in the last eight
    weeks, closes back under 70 (fired once on each name, right after the
    blow-off top), or when price is 60% above the 50-day with the weekly RSI
    at 80 or more; buy back on the first weekly close over the prior week's
    high once price is 40% or more under its 52-week high (IREN: 11 of 14)."""
    weekly = I.resample(bars, "W")
    w_rsi = {x["time"]: x["value"] for x in I.rsi(weekly, 14)}
    sma50 = {x["time"]: x["value"] for x in I.sma(bars, 50)}
    idx = {w["time"]: k for k, w in enumerate(weekly)}
    closes = [b["close"] for b in bars]
    def decide(st, i):
        b = bars[i]; k = idx.get(b["time"])
        if k is None or k < 10:
            return None                          # weekly closes only
        r = w_rsi.get(weekly[k]["time"])
        recent = [w_rsi.get(weekly[q]["time"]) for q in range(k - 8, k)]
        recent = [x for x in recent if x is not None]
        m50 = sma50.get(b["time"])
        hi52 = max(closes[max(0, i - 250):i + 1])
        if st["sold_at"] is None:
            if r is not None and recent and max(recent) >= 80 and r < 70:
                return ("sell", 1.0)
            if r is not None and r >= 80 and m50 and closes[i] / m50 - 1 >= 0.60:
                return ("sell", 1.0)
        else:
            w, pw = weekly[k], weekly[k - 1]
            if closes[i] / hi52 - 1 <= -0.40 and w["close"] > pw["high"] and w["low"] >= pw["low"]:
                return ("buy", None)
        return None
    return decide


RULES = {"leader": rule_leader, "extension": rule_extension, "extension_swing": rule_extension_swing,
         "rsi_break": rule_rsi_break, "cloud": rule_cloud, "parabolic": rule_parabolic,
         "anatomy_a": rule_anatomy_a, "anatomy_b": rule_anatomy_b}
STARTS = {"ASST": "2025-06-01"}   # before the Strive merger the history is a different company


def main():
    conn = ledger.connect()
    syms = (sys.argv[sys.argv.index("--symbols") + 1].split(",") if "--symbols" in sys.argv
            else ["IREN", "SIVE.ST", "CIFR", "ASST"])
    L = ["# The swing study — 2026-09-05", "",
         "Half the shares are a core that is never sold; each rule trades the other half. 1,000 shares at the start, "
         "closes only, no costs or tax. **Shares** is the number that matters for a name you mean to keep; hold is 1,000.", ""]
    for sym in syms:
        bars = [b for b in load(conn, sym) if b["time"] >= STARTS.get(sym, START)]
        if len(bars) < 300:
            L.append(f"## {sym}: only {len(bars)} bars since {START}, skipped"); continue
        hold_val = 1000 * bars[-1]["close"]
        L += [f"## {sym} — {bars[0]['time']} to {bars[-1]['time']}, {bars[0]['close']:.2f} → {bars[-1]['close']:.2f}; "
              f"hold: 1,000 shares, ${hold_val:,.0f}", "",
              "| Rule | Shares at end | Cash idle | Value | Trades | Chased rebuys | vs hold |", "|---|---|---|---|---|---|---|"]
        details = []
        for name, make in RULES.items():
            r = sim(bars, make(bars))
            L.append(f"| {name} | {r['shares']:,.0f} | ${r['cash']:,.0f} | ${r['value']:,.0f} | {r['trades']} | {r['chases']} | "
                     f"{(r['value'] / hold_val - 1) * 100:+.1f}% |")
            details.append((name, r["log"]))
        L.append("")
        if sym == "IREN":
            for title, a, z in (("Around the November 2025 top (76.41 on 2025-11-05) — September 2025 to February 2026", "2025-09-01", "2026-02-28"),
                                ("Around the May 2026 top (67.84 on 2026-05-27) and the July low (29.31) — April to August 2026", "2026-04-01", "2026-08-31")):
                L.append(f"### {title}")
                L.append("")
                for name, log in details:
                    win = [x for x in log if a <= x[0] <= z]
                    L.append(f"- **{name}**: " + ("; ".join(f"{side} {q:,.0f} @ {px:.2f} on {d}" for d, side, q, px in win) if win else "no trade in the window"))
                L.append("")
        for name, log in details:
            if log:
                L.append(f"<details><summary>{name}: {len(log)} trades</summary>\n")
                L.append("| Date | Side | Slice shares | Price |"); L.append("|---|---|---|---|")
                for d, side, q, px in log[-24:]:
                    L.append(f"| {d} | {side} | {q:,.0f} | {px:.2f} |")
                L.append("\n</details>\n")
    text = "\n".join(L)
    print(text)
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(text + "\n")


if __name__ == "__main__":
    main()
