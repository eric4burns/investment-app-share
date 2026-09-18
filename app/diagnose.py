"""Portfolio diagnosis.

Answers the question a dashboard cannot: not "what is my return" but "why is it
that, and what in the portfolio is actually causing it". Every other module
here produces one measurement; this one joins them and says what they mean
together.

The output is findings, each carrying the numbers it rests on. It is
deliberately not advice and does not size, rank or recommend a trade: it says
what is true of the portfolio right now — this position is 45% of the book and
below its own method's invalidation level; this theme is two-thirds of your
money; the sector leading over every window is one you have no exposure to —
and leaves the decision where it belongs.

The distinction that does most of the work is MARKET versus IDIOSYNCRATIC. A
portfolio down 20% while its sectors are down 20% has a market problem and
usually nothing to do; the same portfolio down 20% while its sectors are flat
has a selection problem, which is a different conversation entirely.
"""
from __future__ import annotations

from . import (analysis, frameworks, holdings, indicators, intermarket, methods,
               performance, prices, risk,
               sectors, themes)

SEVERITY = {"critical": 3, "warning": 2, "note": 1}


def _finding(kind, severity, headline, detail, numbers=None, symbols=None,
             why=None, action=None):
    """One finding. `why` says what it means in plain words and `action` what
    could be done about it — the two things the first review said every
    finding lacked. Neither is advice; both are the sentence a reader would
    otherwise have to work out from the numbers."""
    return {"kind": kind, "severity": severity, "headline": headline,
            "detail": detail, "numbers": numbers or {}, "symbols": symbols or [],
            "why": why, "action": action}


def _grid(start: str, end: str) -> list[str]:
    """Every weekday from start to end — the same grid the report's value curve
    and its Risk panel use (see web.value_series).

    This stepped seven days at a time, and the Diagnose tab's "Drawdown now"
    disagreed with the Risk tab's "Current drawdown" for the same period and
    scope: a weekly grid samples two days either side of the peak and never
    the peak itself, so the drawdown it measures is from a lower high. The
    report had already found and fixed the same defect on its own curve; this
    was the copy of it that survived. Weekends are skipped for the reason
    given there — a Saturday at Friday's price is a zero return by
    construction, and the volatility annualisation reads the grid."""
    from datetime import date, timedelta
    out, cur = [], date.fromisoformat(start)
    last = date.fromisoformat(end)
    while cur <= last:
        if cur.isoweekday() <= 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    if out and out[-1] != end:
        out.append(end)
    return out


def diagnose(conn, start: str, end: str, scope: str = "investment",
             benchmark: str = "SPY") -> dict:
    txns = performance.load_transactions(conn, start, end, scope)
    if not txns:
        return {"error": "no transactions in scope"}

    summary = performance.analyse(conn, start, end, scope, [benchmark])
    start = summary["start"]
    dates = _grid(start, end)
    pos = holdings.positions(conn, txns, end)
    rk = risk.metrics(conn, txns, dates, benchmark=benchmark,
                      multi_account=scope in performance.MULTI_ACCOUNT_SCOPES)
    conc = risk.concentration(conn, pos, dates)
    attribution = holdings.attribution(conn, txns, start, end)
    theme_rows, theme_untagged = themes.exposure(conn, pos)
    sector_rows = sectors.exposure(conn, pos)
    rot = sectors.rotation(conn)

    findings: list[dict] = []

    # ---- 1. is the drawdown the market's or yours? --------------------------
    dd = rk.get("current_drawdown")
    if dd is not None and dd < -0.05:
        bm = rk.get("benchmark") or {}
        beta = bm.get("beta")
        # The benchmark's own drawdown over the same window, from its series.
        # The metrics dict never carried one, so the "expected" figure below
        # had been beta times zero for as long as it existed.
        mkt_dd = None
        resolved = prices.resolve_benchmark(benchmark)
        if resolved:
            ser = prices.load_series(conn, resolved[0])
            vals = [v for d, v in sorted(ser.items()) if start <= d <= end and v]
            if vals:
                mkt_dd = vals[-1] / max(vals) - 1.0
        bm["market_drawdown"] = mkt_dd
        expected = (beta * mkt_dd) if (beta is not None and mkt_dd is not None) else None
        leaders = [r for r in rot.get("sectors", []) if r["score"] and r["score"] > 0]
        yours = {s["sector"] for s in sector_rows}
        overlap = [r["sector"] for r in leaders if r["sector"] in yours]
    # ---- is the ledger even current? -------------------------------------
    # Everything below is computed from imported transactions, so a stale
    # import makes every figure confidently wrong rather than obviously
    # missing. On 2026-09-10 the ledger was a week behind and the app said
    # nothing: DGXX was short 2,101 shares, TEM 53, and a whole FPS position
    # worth $23,229 of basis did not exist here at all.
    #
    # The test is not "how many days since the last import" — a quiet week
    # looks identical to a broken one. It is the broker's own share count
    # disagreeing with the ledger's, which only happens when transactions are
    # missing.
    try:
        from . import broker_basis
        book = broker_basis.lookup(conn)
        held = {p["symbol"]: (p.get("quantity") or 0) for p in pos}
        off = []
        for sym, b in book.items():
            q = held.get(sym, 0.0)
            if abs(q - b["quantity"]) > max(0.01 * max(q, b["quantity"]), 0.001):
                off.append((sym, q, b["quantity"]))
        if off:
            worst = sorted(off, key=lambda r: -abs(r[1] - r[2]))
            findings.append(_finding(
                "stale", "critical",
                f"{len(off)} position(s) disagree with the broker — transactions are missing",
                "; ".join(f"{s}: ledger {q:,.2f} shares against the broker's {b:,.2f}"
                          for s, q, b in worst[:4]),
                symbols=[s for s, _q, _b in worst],
                why="Every figure on this page is built from imported transactions. "
                    "When the share counts disagree the ledger is behind, and the "
                    "returns, drawdowns and tax numbers are all being computed on a "
                    "book you no longer hold.",
                action="Export the transactions since the last import from the broker "
                       "and drop the CSV in data/fidelity/, then re-run the import."))
    except Exception:                                          # noqa: BLE001
        pass

        findings.append(_finding(
            "drawdown", "critical" if dd < -0.25 else "warning",
            f"{dd*100:.1f}% below the previous peak",
            f"Volatility is {rk['volatility']*100:.0f}% annualised against the benchmark's "
            f"{bm.get('volatility', 0)*100:.0f}%"
            + (f", and beta is {beta:.2f} — so a market fall of X should produce "
               f"roughly {beta:.1f}X here. " if beta is not None
               # Beta is None whenever the benchmark series is missing or has no
               # variance. The neighbouring volatility lookup was already
               # guarded; this one was not, so the ENTIRE diagnosis raised
               # TypeError — and only once drawdown passed -5%, meaning the page
               # blanked precisely on the days it was most wanted.
               else ". Beta is unavailable for this range, so how much of this is "
                    "the market cannot be separated out here. ")
            + (f"Your sectors that are currently leading: {', '.join(overlap)}. "
               if overlap else "None of the sectors you hold are currently leading the market. ")
            + "Whether this is the market or your selection is the first thing to settle, "
              "and beta is what settles it.",
            {"current_drawdown": dd, "max_drawdown": rk.get("max_drawdown"),
             "beta": beta, "volatility": rk.get("volatility")},
            why=("A fall the market caused recovers when the market does; a fall your "
                 "selection caused does not have to. The two call for different "
                 "responses, so which one this is comes before anything else."),
            action=((f"With beta {beta:.2f} and the market {abs(bm.get('market_drawdown') or 0)*100:.0f}% "
                     f"off its high, the market explains roughly {abs(expected or 0)*100:.0f} points of "
                     f"this {abs(dd)*100:.0f}%. The rest is the names.")
                    if beta is not None and bm.get("market_drawdown") is not None else
                    "Beta could not be measured for this range, so split the fall by hand: "
                    "compare each large position against its own sector fund over the same dates.")))

    # ---- 2. what actually caused the period's P&L --------------------------
    if False and attribution:   # Holdings' "What moved the needle" is this table; the finding repeated it in prose
        top = attribution[:3]
        bottom = [a for a in attribution if a["contribution"] < 0][-3:]
        total_gain = sum(a["contribution"] for a in attribution)
        if bottom:
            worst_sum = sum(a["contribution"] for a in bottom)
            findings.append(_finding(
                "attribution", "note",
                f"{', '.join(a['symbol'] for a in bottom)} account for "
                f"${abs(worst_sum):,.0f} of losses",
                "Attribution is in dollars rather than percent, because a 300% move on a "
                "small position did not drive the portfolio and a percentage table would "
                "claim it did. "
                + (f"Against that, {', '.join(a['symbol'] for a in top)} contributed "
                   f"${sum(a['contribution'] for a in top):,.0f}."),
                {"period_total": total_gain},
                [a["symbol"] for a in bottom + top],
                why=("Where the money was actually made and lost over the range, in dollars, "
                     "so a big percentage move on a small position cannot claim the credit."),
                action=("The names on the loss side are the ones whose thesis needs re-reading; "
                        "the names on the gain side are where the return came from, and the "
                        "question there is whether they are now too large.")))

    # ---- 3. concentration, in risk terms not weight ------------------------
    for row in (conc.get("rows") or [])[:5]:
        if row["risk_share"] > 0.25 and row["risk_vs_weight"] and row["risk_vs_weight"] > 1.5:
            rw = row["risk_vs_weight"]
            vol_full = row["volatility"]
            vol_held = row.get("volatility_held")
            # Say which window the number came from. Risk share is measured over
            # the whole range so that every position is compared on the same
            # dates — which for a name bought late in the range means it is
            # judged on history the holder never sat through. ASST reads as a
            # third of the book's risk on a 13x week in May 2025, five months
            # before its first lot; over the period held it is a different name.
            window = (f"Measured over the whole range from {start}, on the same dates as every "
                      f"other position. ")
            if row.get("history_predates_holding") and vol_held is not None:
                window += (f"That includes history from before you owned it: volatility over the "
                           f"range is {vol_full*100:.0f}%, but over the time you have actually held "
                           f"it (since {row.get('held_since')}) it is {vol_held*100:.0f}%, so the "
                           f"share of risk overstates what you have lived through.")
            else:
                window += (f"Volatility over the time you have held it is "
                           f"{(vol_held or vol_full)*100:.0f}%.")
            findings.append(_finding(
                "concentration", "warning",
                f"{row['symbol']} is {row['weight']*100:.1f}% of the money but "
                f"{row['risk_share']*100:.0f}% of the risk",
                f"That is {rw:.1f}x its weight. " + window,
                {"weight": row["weight"], "risk_share": row["risk_share"],
                 "volatility": vol_full, "volatility_held": vol_held},
                [row["symbol"]],
                why=(f"For its size, this position moves about {rw:.0f} times as much as the rest "
                     f"of the book. A 10% move in it costs or makes about as much as a "
                     f"{10 / rw:.1f}% move in everything else put together."),
                action=(f"Sized for its risk rather than its dollars, it would be about "
                        f"{row['weight'] / rw * 100:.0f}% of the book instead of "
                        f"{row['weight']*100:.0f}%. Keeping it larger is a choice to own that "
                        f"volatility on purpose; the finding is here so it is a choice.")))

    if conc.get("effective_holdings") and conc["effective_holdings"] < 5:
        findings.append(_finding(
            "concentration", "warning",
            f"The book behaves like {conc['effective_holdings']} equal positions, "
            f"not {conc['positions']}",
            f"Largest position {conc['top1']*100:.1f}%, top three {conc['top3']*100:.1f}%.",
            {"effective_holdings": conc["effective_holdings"], "top1": conc["top1"]},
            why=("Positions that move together are one bet with several tickers on it. "
                 "The count that matters is how many independent bets the book holds, "
                 "and this is that number."),
            action=("Adding a name that moves with the top three does not diversify anything. "
                    "Only something that moves on different news raises this figure.")))

    # ---- 4. theme concentration -------------------------------------------
    if theme_rows and theme_rows[0]["weight"] > 0.4:
        t = theme_rows[0]
        findings.append(_finding(
            "theme", "warning",
            f"{t['weight']*100:.0f}% of the portfolio is {t['label'].lower()}",
            f"Held through {', '.join(t['symbols'])}. Sector classification reports this as "
            "ordinary technology exposure, which is true and tells you nothing — the names "
            "rise and fall on the same thesis.",
            {"weight": t["weight"]}, t["symbols"],
            why="These names rise and fall on the same news, so they are one position in all but name.",
            action=("Decide on the thesis once and size the whole group as a single position — "
                    "then the question of which names inside it is a separate, smaller one.")))

    # ---- 5. rotation: what leads that you do not own -----------------------
    held_sectors = {s["sector"] for s in sector_rows if s["weight"] > 0.02}
    persistent = [r for r in rot.get("sectors", []) if r.get("persistent")]
    for r in persistent:
        if r["sector"] not in held_sectors:
            findings.append(_finding(
                "rotation", "note",
                f"{r['sector']} leads over every window and you hold none of it",
                f"{r['symbol']} against {rot['market']}: "
                + ", ".join(f"{w//21}M {r['relative'][w]*100:+.1f}%" for w in rot["windows"]
                            if r['relative'].get(w) is not None)
                + ". Leading over both the short and the long window is what separates rotation "
                  "from a bounce.",
                {"score": r["score"]}, [r["symbol"]],
                why=("Money moving into a sector you do not hold is money moving out of the "
                     "ones you do, whatever the companies are doing."),
                action=("Not a reason to buy it on its own. It is a reason to know the book is "
                        "positioned against the current flow, and to hold its names on their "
                        "own merits rather than the sector's.")))

    laggards = [r for r in rot.get("sectors", []) if r["score"] is not None and r["score"] < -0.05]
    exposed_laggards = [r for r in laggards if r["sector"] in held_sectors]
    if exposed_laggards:
        findings.append(_finding(
            "rotation", "note",
            f"You hold {', '.join(r['sector'] for r in exposed_laggards)}, "
            "which lag the market on average",
            "Lagging is not a reason to sell on its own — it is a reason to know that the "
            "position needs its own thesis rather than the sector's.",
            {}, [r["symbol"] for r in exposed_laggards],
            why="A position in a lagging sector gets no help from the tide; it has to earn its place alone.",
            action="Each of these positions needs a reason of its own to be held. If there is none, that is the finding."))

    # ---- 6. technical state of what you hold, and method levels ------------
    levels, broken = [], []
    for p in pos[:12]:
        if not p.get("value") or p["value"] < 1000:
            continue
        bars = prices.load_bars(conn, p["symbol"], "2010-01-01", end)
        if len(bars) < 260:
            continue
        ta = analysis.analyse(bars, p["symbol"])
        monthly = next((f for f in ta["frames"]
                        if f["timeframe"] == "Monthly" and not f.get("insufficient")), None)
        weekly = next((f for f in ta["frames"]
                       if f["timeframe"] == "Weekly" and not f.get("insufficient")), None)
        if monthly and "bear" in monthly["bias"]:
            broken.append({"symbol": p["symbol"], "bias": monthly["bias"],
                           "trend": monthly["trend"], "weight": p["weight"]})

        # Levels the encoded methods actually care about — the places a position
        # would be added to, not a target invented for the purpose.
        m = methods.evaluate(bars, "cantonese-cat-monthly-reversion")
        if not m.get("insufficient"):
            ctx = methods.build_context(
                indicators.resample(bars, "M"),
                methods.METHODS["cantonese-cat-monthly-reversion"])
            ma = methods._last(ctx["sma20"])
            lo = ctx["bollinger"]["lower"][-1]["value"] if ctx["bollinger"]["lower"] else None
            kij = methods._last(ctx["ichimoku"]["base"])
            close = p["price"]
            # A level is only useful if a price could plausibly reach it.
            #  * A lower Bollinger Band goes NEGATIVE when monthly volatility
            #    exceeds the mean — arithmetically correct, meaningless as a
            #    level, and printing "-113% away" destroys trust in the rest.
            #  * A level more than 80% away is not a level you are waiting at;
            #    on this book those come from Ichimoku spans crossing a reverse
            #    split, where the series is comparing two different share counts.
            def usable(level):
                if not level or level <= 0 or not close:
                    return None
                return level if abs(level / close - 1) <= 0.8 else None

            ma_u, lo_u, kij_u = usable(ma), usable(lo), usable(kij)
            if close and ma_u:
                levels.append({
                    "symbol": p["symbol"], "close": close, "weight": p["weight"],
                    "ma20": ma_u, "to_ma20": (ma_u / close - 1),
                    "lower_band": lo_u, "to_lower_band": (lo_u / close - 1) if lo_u else None,
                    "kijun": kij_u, "to_kijun": (kij_u / close - 1) if kij_u else None,
                    "method_score": m["pct"],
                    "note": None if lo_u else
                            "lower band is below zero on this timeframe — too volatile for the band to be a level",
                })

    if broken:
        findings.append(_finding(
            "technical", "warning",
            f"{len(broken)} holding(s) are bearish on the monthly chart",
            ", ".join(f"{b['symbol']} ({b['weight']*100:.0f}% of the book, {b['trend']})"
                      for b in broken)
            + ". The monthly chart is the one that separates a dip from a decline.",
            {}, [b["symbol"] for b in broken],
            why=("A daily or weekly dip can sit inside a monthly uptrend; a monthly downtrend "
                 "is the one timeframe a decline cannot hide in."),
            action=("These are the names to re-read the thesis on before adding, not the ones to "
                    "average into on the daily chart.")))

    # Support being worn out, per RonnieV. This belongs among findings rather
    # than in a table because his claim is specifically that the break, when it
    # comes, is fast — so it is a thing to notice now, not a column to browse.
    worn = []
    for p in pos:
        bars = prices.load_bars(conn, p["symbol"], "2023-01-01", end)
        if len(bars) < 60:
            continue
        met, touches, _ = methods.CONDITIONS["ma_support_exhausted"](bars, {})
        if met:
            worn.append((p["symbol"], touches, p.get("weight") or 0))
    if worn:
        worn.sort(key=lambda w: -w[1])
        findings.append(_finding(
            "technical", "warning",
            f"{len(worn)} holding(s) are wearing out their 21-day support",
            ", ".join(f"{sym} ({n} touches from above in the last month, "
                      f"{w*100:.0f}% of the book)" for sym, n, w in worn)
            + ". RonnieV's reading is that repeated tests WEAKEN a moving average "
              "rather than confirming it, and that once it goes, it goes quickly. "
              "This is the opposite of how repeated bounces are usually read.",
            {}, [w[0] for w in worn],
            why="Each test uses up buyers at that level; when it breaks there are few left to catch it.",
            action="Know where the exit is before the average goes, not after."))

    findings.sort(key=lambda f: -SEVERITY.get(f["severity"], 0))

    return {
        "start": start, "end": end, "scope": scope,
        "value": summary["end_value"],
        "twr": summary["twr"], "benchmark": summary.get("benchmarks", [{}])[0],
        "risk": {k: rk.get(k) for k in
                 ("current_drawdown", "max_drawdown", "volatility", "sharpe", "sortino")},
        "findings": findings,
        "concentration": conc,
        "levels": sorted(levels, key=lambda x: -x["weight"]),
        "themes": theme_rows, "sectors": sector_rows,
        "rotation": rot.get("sectors", [])[:5],
        "attribution": attribution[:5] + attribution[-5:],
        # regime and construction used to be computed here and never rendered
        # (0.87 s a call); they live on the Backtest tab's methods.
    }
