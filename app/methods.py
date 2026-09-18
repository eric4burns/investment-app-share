"""The Method Library.

A method is a trader's approach expressed as data rather than prose: which
timeframe, which indicators at which settings, what constitutes a setup, what
invalidates it, and what the method deliberately ignores. Once it is data, one
definition drives four things — a chart template, a scanner over the watchlist,
a pre-trade checklist, and a backtest — and they cannot drift apart, because
they are the same object.

Methods are scored, never signalled. Each condition reports whether it is met
and with what number, so a name is presented as "five of seven conditions, here
is which two are missing" rather than as a buy. The point is to make somebody
else's process legible and testable on your own holdings, not to outsource the
decision to it.

The first method is derived from eight Cantonese Cat videos (research/transcripts).
It is a reading of his public content, not his own words, and any of it can be
wrong — every condition names the evidence it came from so it can be checked.
"""
from __future__ import annotations

from . import indicators as I

# --- condition primitives -------------------------------------------------
# Each returns (met, actual_value, description). They take resampled bars for
# the method's timeframe plus a dict of precomputed indicator series.


def _last(series):
    return series[-1]["value"] if series else None


def _slope(series, lookback=3):
    if not series or len(series) <= lookback:
        return None
    a, b = series[-lookback - 1]["value"], series[-1]["value"]
    return (b - a) / abs(a) if abs(a) > 1e-12 else None


CONDITIONS = {}


def condition(key):
    def wrap(fn):
        CONDITIONS[key] = fn
        return fn
    return wrap


@condition("near_20ma")
def _near_20ma(bars, ctx, tolerance=0.08):
    """Price within `tolerance` of the 20-period moving average."""
    ma = _last(ctx["sma20"])
    if not ma:
        return None, None, "20-period MA unavailable"
    close = bars[-1]["close"]
    dist = (close - ma) / ma
    return abs(dist) <= tolerance, dist, f"{dist*100:+.1f}% from the 20-month MA ({ma:,.2f})"


@condition("ma_support_exhausted")
def _ma_support_exhausted(bars, ctx, period=21, lookback=22, tolerance=None,
                          threshold=3):
    """Count recent touches of a moving average from above.

    RonnieV's point is that these accumulate the wrong way: an average tested
    over and over inside a month is a support that is being worn down, not one
    being proven. So a HIGH count is the bearish reading, which inverts how a
    bounce count is usually read, and the condition is true when the count
    reaches the threshold.

    Only touches from above count. Price crossing up through the average from
    below is a different event entirely and would otherwise inflate the count
    exactly when the setup is turning bullish.
    """
    from . import indicators as I, structure as S

    # Measured in typical bar ranges, not percent — the same correction made in
    # structure.py. Two percent of a hundred-dollar stock is two dollars, which
    # on a quiet name is wider than a week of trading, so every bar counted as
    # touching and the whole window collapsed into one undifferentiated band.
    line = {p["time"]: p["value"] for p in I.ema(bars, period)}
    window = [b for b in bars[-lookback:] if b["time"] in line]
    if len(window) < 4:
        return None, None, f"not enough history for a {period}-period EMA"

    # A run of consecutive bars sitting near the average is ONE test of it, not
    # one per bar. Without this a quiet name drifting upward inside the tolerance
    # band scored 22 touches in 22 bars having never pulled back once, and
    # diagnose then warned that its support was about to fail.
    band = (tolerance * abs(line[window[-1]["time"]]) if tolerance is not None
            else S.typical_range(window) * 0.5)
    if not band:
        return None, None, "no measurable range in this window"
    touches, prev_above, in_band = 0, None, False
    for b in window:
        ma = line[b["time"]]
        above = b["close"] >= ma
        touched = (b["low"] <= ma + band and b["close"] >= ma - band
                   and prev_above is not False)
        if touched and not in_band:
            touches += 1
        in_band = touched
        prev_above = above

    close, ma = bars[-1]["close"], line[window[-1]["time"]]
    if close < ma:
        return None, touches, (
            f"already below the {period} EMA — this condition measures support "
            f"being worn down, not support that has already gone")
    return touches >= threshold, touches, (
        f"{touches} touch(es) of the {period} EMA from above in {len(window)} bars"
        + (" — support weakening" if touches >= threshold else ""))


@condition("ma_support_intact")
def _ma_support_intact(bars, ctx, period=21, lookback=22, tolerance=None,
                       threshold=3):
    """The inverse of ma_support_exhausted, for use as a SCORED condition.

    `tolerance` defaults to None so the volatility-scaled band in the primitive
    is what actually runs. It used to default to 0.02, which meant the percent
    band the primitive had deliberately moved away from was reinstated by its
    own wrapper — and this wrapper is the ONLY path the scanner scores, so the
    original "every bar is a touch" bug was alive there while diagnose, which
    calls the primitive directly, disagreed with it on the same holdings.

    The scoring engine adds weight when a condition is met, so wiring the
    exhaustion check in directly rewards exactly the names it is meant to warn
    about — a name wearing out its support ranks top. Stating the desirable
    direction as its own condition keeps that from being a comment in a `why`
    string that the engine cannot read.
    """
    worn, touches, detail = _ma_support_exhausted(
        bars, ctx, period=period, lookback=lookback, tolerance=tolerance,
        threshold=threshold)
    if worn is None:
        return None, touches, detail
    return not worn, touches, detail


@condition("below_20ma")
def _below_20ma(bars, ctx):
    ma = _last(ctx["sma20"])
    if not ma:
        return None, None, "20-period MA unavailable"
    close = bars[-1]["close"]
    return close < ma, (close - ma) / ma, f"close {close:,.2f} vs 20-month MA {ma:,.2f}"


@condition("ma20_rising")
def _ma20_rising(bars, ctx):
    """A rising 20-month MA supports price; a falling one rejects it."""
    sl = _slope(ctx["sma20"], 3)
    if sl is None:
        return None, None, "not enough history for MA slope"
    return sl > 0, sl, f"20-month MA slope {sl*100:+.1f}% over 3 bars"


@condition("at_lower_band")
def _at_lower_band(bars, ctx, tolerance=0.03):
    bb = ctx["bollinger"]
    if not bb["lower"]:
        return None, None, "bands unavailable"
    lo, close = bb["lower"][-1]["value"], bars[-1]["close"]
    dist = (close - lo) / lo
    return dist <= tolerance, dist, f"{dist*100:+.1f}% from the lower band ({lo:,.2f})"


@condition("percent_b")
def _percent_b(bars, ctx, below=0.5):
    bb = ctx["bollinger"]
    if not bb["upper"] or not bb["lower"]:
        return None, None, "bands unavailable"
    up, lo = bb["upper"][-1]["value"], bb["lower"][-1]["value"]
    close = bars[-1]["close"]
    pb = (close - lo) / (up - lo) if up > lo else 0.5
    return pb <= below, pb, f"%B {pb:.2f} (0 = lower band, 1 = upper)"


@condition("above_cloud")
def _above_cloud(bars, ctx):
    ich = ctx["ichimoku"]
    if not ich["span_a"] or not ich["span_b"]:
        return None, None, "cloud unavailable"
    a, b = ich["span_a"][-1]["value"], ich["span_b"][-1]["value"]
    top, close = max(a, b), bars[-1]["close"]
    return close > top, (close - top) / top, f"close {close:,.2f} vs cloud top {top:,.2f}"


@condition("above_kijun")
def _above_kijun(bars, ctx):
    k = _last(ctx["ichimoku"]["base"])
    if not k:
        return None, None, "kijun unavailable"
    close = bars[-1]["close"]
    return close > k, (close - k) / k, f"close {close:,.2f} vs kijun {k:,.2f}"


@condition("tenkan_above_kijun")
def _tk_cross(bars, ctx):
    t, k = _last(ctx["ichimoku"]["conversion"]), _last(ctx["ichimoku"]["base"])
    if not t or not k:
        return None, None, "tenkan/kijun unavailable"
    return t > k, (t - k) / k, f"tenkan {t:,.2f} vs kijun {k:,.2f}"


@condition("near_ichimoku")
def _near_ichimoku(bars, ctx, tolerance=0.25):
    """Stretched far from the Ichimoku lines means consolidation is due."""
    t = _last(ctx["ichimoku"]["conversion"])
    if not t:
        return None, None, "tenkan unavailable"
    close = bars[-1]["close"]
    dist = (close - t) / t
    return abs(dist) <= tolerance, dist, f"{dist*100:+.1f}% from the tenkan"


@condition("rsi_below")
def _rsi_below(bars, ctx, level=50.0):
    r = _last(ctx["rsi"])
    if r is None:
        return None, None, "RSI unavailable"
    return r < level, r, f"RSI {r:.0f}"


@condition("rsi_bullish_divergence")
def _rsi_div(bars, ctx, lookback=20):
    """Price makes a lower low while RSI makes a higher low.

    The two lows must be actual SWING lows — each the lowest of its own
    neighbourhood, and separated from one another. The docstring used to promise
    that while the code took the two lowest BARS in the window, which are
    routinely adjacent: on real data it returned indices 9 and 11 of a 12-bar
    window and called two points on the same descent a divergence.
    """
    from . import structure as S

    r = ctx["rsi"]
    if len(r) < lookback + 2 or len(bars) < lookback + 2:
        return None, None, "not enough history for divergence"
    window = bars[-lookback:]
    rwin = r[-lookback:]
    pv = [p for p in S.pivots(window, 2, 2) if p["kind"] == "low"]
    if len(pv) < 2:
        return None, None, "no two swing lows in the window"
    # The most recent pair, and they have to be far enough apart to be separate
    # events rather than two bars of one move.
    i, j = pv[-2]["index"], pv[-1]["index"]
    if j - i < 3:
        return None, None, "the two swing lows are too close to be distinct"
    price_lower = window[j]["low"] < window[i]["low"]
    rsi_higher = rwin[j]["value"] > rwin[i]["value"]
    met = price_lower and rsi_higher
    return met, rwin[j]["value"] - rwin[i]["value"], (
        f"price low {'lower' if price_lower else 'higher'}, "
        f"RSI {rwin[i]['value']:.0f} -> {rwin[j]['value']:.0f}")


@condition("above_ma")
def _above_ma(bars, ctx, key="sma50"):
    ma = _last(ctx.get(key))
    if not ma:
        return None, None, f"{key} unavailable"
    close = bars[-1]["close"]
    return close > ma, (close - ma) / ma, f"{(close/ma-1)*100:+.1f}% vs {key} ({ma:,.2f})"


@condition("ma_stack")
def _ma_stack(bars, ctx):
    """Fast average above slow average above slowest — the classic trend stack."""
    f, m, sl = _last(ctx.get("sma20")), _last(ctx.get("sma50")), _last(ctx.get("sma200"))
    if not (f and m and sl):
        return None, None, "not enough history for all three averages"
    return f > m > sl, (f - sl) / sl, f"20 {f:,.2f} / 50 {m:,.2f} / 200 {sl:,.2f}"


@condition("ma_stack_keys")
def _ma_stack_keys(bars, ctx, keys=None):
    """A stack of any depth, named by context key, fastest first.

    The classic `ma_stack` hard-codes 20/50/200. RonnieV's is four deep and
    mixes types on purpose — 9 and 21 EMA, then 50 and 200 SMA — because his
    argument is about what each average is FOR: a short one should weight recent
    sessions since it is measuring momentum, a long one should weight them
    equally since it is measuring trend.
    """
    keys = keys or []
    values = [(k, _last(ctx.get(k))) for k in keys]
    missing = [k for k, v in values if not v]
    if missing:
        return None, None, f"not enough history for {', '.join(missing)}"
    seq = [v for _, v in values]
    ordered = all(a > b for a, b in zip(seq, seq[1:]))
    spread = (seq[0] - seq[-1]) / seq[-1] if seq[-1] else None
    return ordered, spread, " > ".join(
        f"{k.replace('sma','SMA ').replace('ema','EMA ')} {v:,.2f}" for k, v in values)


@condition("above_all")
def _above_all(bars, ctx, keys=None):
    """Price above every average in the stack.

    Separate from the ordering check because they answer different questions and
    can disagree: a name can have a perfectly stacked set of averages while
    price has already dropped through the fastest of them, which is the moment
    the trend starts failing rather than a confirmation that it is intact.
    """
    keys = keys or []
    values = [(k, _last(ctx.get(k))) for k in keys]
    missing = [k for k, v in values if not v]
    if missing:
        return None, None, f"not enough history for {', '.join(missing)}"
    close = bars[-1]["close"]
    below = [k for k, v in values if close < v]
    return not below, len(below), (
        f"close {close:,.2f} is above all {len(values)}" if not below
        else f"close {close:,.2f} is below {', '.join(below)}")


@condition("near_high")
def _near_high(bars, ctx, within=0.15, lookback=252):
    """Close to the running high — momentum lives near highs, not near lows."""
    window = bars[-lookback:] if len(bars) > lookback else bars
    hi = max(b["high"] for b in window)
    close = bars[-1]["close"]
    dist = close / hi - 1
    return dist >= -within, dist, f"{dist*100:+.1f}% from the {len(window)}-bar high ({hi:,.2f})"


@condition("outperforming")
def _outperforming(bars, ctx, lookback=126):
    """Relative strength: the position's own return over the window.

    Compared against the benchmark by the caller when one is supplied; on its
    own it still separates names that are going up from names that are not.
    """
    if len(bars) <= lookback:
        return None, None, "not enough history"
    a, b = bars[-lookback - 1]["close"], bars[-1]["close"]
    r = (b / a - 1) if a else None
    if r is None:
        return None, None, "no price"
    # ctx never carried "benchmark_return" — nothing anywhere set that key — so
    # this silently degraded to "did it go up at all", which in a rising market
    # is met by everything and is the opposite of RELATIVE strength. The
    # benchmark series is now passed in explicitly by scan().
    bars_b = ctx.get("benchmark_bars")
    bench = None
    if bars_b and len(bars_b) > lookback:
        a2, b2 = bars_b[-lookback - 1]["close"], bars_b[-1]["close"]
        bench = (b2 / a2 - 1) if a2 else None
    if bench is None:
        # Say so rather than quietly scoring "did it go up at all" — that is met
        # by everything in a rising market and is the opposite of RELATIVE
        # strength, which is the whole point of the condition.
        return None, r, (f"{r*100:+.1f}% over {lookback} bars, but no benchmark "
                         f"was available to compare it against")
    return r > bench, r - bench, (f"{r*100:+.1f}% vs benchmark {bench*100:+.1f}% "
                                  f"({(r-bench)*100:+.1f} pts)")


@condition("rsi_between")
def _rsi_between(bars, ctx, low=45.0, high=75.0):
    """Momentum wants RSI strong but not exhausted."""
    r = _last(ctx["rsi"])
    if r is None:
        return None, None, "RSI unavailable"
    return low <= r <= high, r, f"RSI {r:.0f} (want {low:.0f}-{high:.0f})"


@condition("volume_expanding")
def _volume_expanding(bars, ctx, lookback=50, ratio=1.0):
    """Recent volume against its own longer average — participation, not price."""
    if len(bars) < lookback + 10:
        return None, None, "not enough history"
    recent = [b.get("volume") or 0 for b in bars[-10:]]
    base = [b.get("volume") or 0 for b in bars[-lookback:]]
    if not sum(base):
        return None, None, "no volume data"
    r = (sum(recent) / len(recent)) / (sum(base) / len(base))
    return r >= ratio, r, f"recent volume {r:.2f}x its {lookback}-bar average"


# --- method definitions ---------------------------------------------------

METHODS = {
    "ronniev-ma-stack-trend": {
        "name": "RonnieV — moving average stack",
        "source":
            "His video 'The LAST moving averages tutorial you'll EVER need...'. The "
            "averages, the EMA-below-50 / SMA-above-50 split and the support-exhaustion "
            "rule are all his and quoted in setups.py; the weights are this app's.",
        "timeframe": "D",
        "thesis":
            "Four averages answering four different questions — the 9 EMA for the last "
            "two weeks of momentum, the 21 for the short trend, the 50 for the "
            "intermediate, the 200 for the long. Two readings come before any crossover: "
            "whether price is above or below each average, and whether the average is "
            "rising or falling. The distinctive part is the last condition, which runs "
            "the opposite way to intuition — a moving average tested over and over inside "
            "a month is being WORN DOWN, not proven, and when it finally gives way it "
            "tends to go quickly.",
        "evidence": [
            "\"when you get a 9 EMA crossing through a 21 EMA to the upside, that's going "
            "to be bullish\"",
            "\"what can happen when you start testing the EMA in quick succession over a "
            "shorter period of time, say like a month or so, this starts weakening your "
            "support ... And once it breaks below the EMA, things got very bad very quickly\"",
            "\"Typically, especially for the larger ones like 50 SMA or 200 SMA, typically "
            "you're going to get decent bounces off of these moving averages\"",
        ],
        "indicators": {
            "ema9": ("ema", [9]), "ema21": ("ema", [21]),
            "sma50": ("sma", [50]), "sma200": ("sma", [200]),
        },
        "setup": [
            {"condition": "ma_stack_keys",
             "args": {"keys": ["ema9", "ema21", "sma50", "sma200"]}, "weight": 3,
             "why": "His full stack in order is the trend being intact on every horizon at once"},
            {"condition": "above_all",
             "args": {"keys": ["ema9", "ema21", "sma50", "sma200"]}, "weight": 2,
             "why": "Above or below the average is the reading he takes before any crossover"},
            {"condition": "ma_support_intact",
             "args": {"period": 21, "lookback": 22, "threshold": 3}, "weight": 2,
             "why": "Support not being worn out. Repeated tests weaken a moving average "
                    "rather than confirming it, so few touches is the healthy reading"},
        ],
        "invalidation":
            "Price closing below the 21 EMA after a run of tests against it. That is the "
            "exact sequence he describes going bad quickly.",
        "ignores": [
            "Everything not on the chart — earnings, valuation, why the name moved",
            "Whether the averages are rising or falling, which he reads by eye and this "
            "does not yet compute",
        ],
        "caveats": [
            "A high score means the trend is intact and its support is not being worn "
            "out. It is not a buy signal, and he pairs all of this with a trigger that "
            "is proprietary and not reproduced here.",
            "He gives no weights, thresholds or position sizing. The 3/2/2 split and the "
            "3-touch threshold are this app's and are not his.",
        ],
    },
    "cantonese-cat-monthly-reversion": {
        "name": "Cantonese Cat — monthly mean reversion",
        "source": "Derived from 8 public videos, Jun–Aug 2026 (research/transcripts/CantoneseCat)",
        "timeframe": "M",
        "thesis":
            "Works primarily on the monthly chart. The 20-month moving average is the "
            "central level: over roughly 16 years it has been backtested about 12 times, "
            "an event every ~1.33 years, often coinciding with a touch of the lower "
            "monthly Bollinger Band. A rising 20-month MA supports price; a negatively "
            "sloping one rejects it. Ichimoku provides structure — price stretched far "
            "from the tenkan tends to consolidate back toward it — and a bullish RSI "
            "divergence is what marks stabilisation.",
        "evidence": [
            "\"over the last 16 years, there have been 12 times where it back tested the "
            "20-month moving average and sometimes go beyond and touch the lower Bollinger Band\"",
            "\"Every 1.33 years, you have one of these events where it touches or pushes "
            "through the 20-month moving average or and/or touch the lower Bollinger Band\"",
            "\"the 20-month moving average here is negatively sloping ... to the point that "
            "it is rejecting price\"",
            "\"when things get a little bit too far from the Ichimoku, it just consolidate sideways\"",
            "\"When you have a weekly bullish divergence, that's usually when things start to stabilize\"",
        ],
        "indicators": {
            "sma20": ("sma", [20]),
            "bollinger": ("bollinger", [20, 2.0]),
            "ichimoku": ("ichimoku", [9, 26, 52]),
            "rsi": ("rsi", [14]),
        },
        "setup": [
            {"condition": "near_20ma", "args": {"tolerance": 0.10}, "weight": 2,
             "why": "The 20-month MA backtest is the event the whole method waits for"},
            {"condition": "ma20_rising", "args": {}, "weight": 2,
             "why": "A falling 20-month MA rejects price rather than supporting it"},
            {"condition": "percent_b", "args": {"below": 0.4}, "weight": 1,
             "why": "Lower half of the monthly bands is where these tests happen"},
            {"condition": "above_kijun", "args": {}, "weight": 1,
             "why": "Holding the kijun means the monthly structure is intact"},
            {"condition": "near_ichimoku", "args": {"tolerance": 0.30}, "weight": 1,
             "why": "Stretched far from the tenkan implies consolidation first"},
            {"condition": "rsi_bullish_divergence", "args": {}, "weight": 1,
             "why": "Divergence is what marks stabilisation rather than continuation"},
        ],
        "invalidation":
            "A 20-month MA that turns down while price is below it. That is the "
            "configuration described as rejecting price rather than supporting it.",
        "ignores": [
            "Daily noise — the daily chart is barely mentioned across eight videos",
            "Earnings and fundamentals; this is a price-structure method",
            "News catalysts, except as an explanation after the fact",
        ],
        "caveats": [
            "Derived from public videos, not stated by the author as a system",
            "The ~1.33-year cadence is his observation on an index, not a tested edge",
            "Divergence detection here is cruder than reading it by eye",
        ],
    },
    "momentum-relative-strength": {
        "name": "Momentum & relative strength (weekly)",
        "source":
            "Public momentum literature, not attributed to any individual. Written as a "
            "deliberate counterweight to the monthly mean-reversion method: one buys "
            "weakness near a long average, the other buys strength near highs, and where "
            "they disagree is more informative than where either agrees with itself.",
        "timeframe": "W",
        "thesis":
            "Momentum is the best-documented anomaly in public equity research: what has "
            "outperformed over three to twelve months tends to keep outperforming over the "
            "next few months. The setup wants price above a stacked set of rising averages, "
            "near its own running high, outperforming the benchmark, with RSI strong but not "
            "exhausted, and participation confirming rather than fading.",
        "evidence": [
            "Cross-sectional momentum (12-1 month relative strength) is among the most "
            "replicated effects in the asset-pricing literature.",
            "Trend-following rules based on price versus a long moving average are the "
            "standard published implementation.",
            "The RSI ceiling exists because momentum and exhaustion look identical until "
            "afterwards; capping it is what separates 'strong' from 'parabolic'.",
        ],
        "indicators": {
            "sma20": ("sma", [20]),
            "sma50": ("sma", [50]),
            "sma200": ("sma", [200]),
            "rsi": ("rsi", [14]),
        },
        "setup": [
            {"condition": "ma_stack", "args": {}, "weight": 2,
             "why": "A stacked 20 > 50 > 200 is the definition of an established uptrend"},
            {"condition": "near_high", "args": {"within": 0.15}, "weight": 2,
             "why": "Momentum lives near highs; a name 40% off its high is a different trade"},
            {"condition": "outperforming", "args": {"lookback": 26}, "weight": 2,
             "why": "Relative strength over six months is the effect the method rests on"},
            {"condition": "rsi_between", "args": {"low": 45, "high": 78}, "weight": 1,
             "why": "Strong but not exhausted — the ceiling is the part people skip"},
            {"condition": "above_ma", "args": {"key": "sma50"}, "weight": 1,
             "why": "Holding the 50 is the usual line between a pullback and a break"},
            {"condition": "volume_expanding", "args": {"ratio": 0.9}, "weight": 1,
             "why": "Participation should confirm the move rather than fade it"},
        ],
        "invalidation":
            "A weekly close below the 50-period average, or the 50 crossing below the 200. "
            "Momentum methods are defined as much by where they exit as where they enter.",
        "ignores": [
            "Valuation entirely — this method will buy something expensive that is going up",
            "Mean reversion; a name at its lows will never qualify no matter how cheap",
            "Fundamentals and catalysts",
        ],
        "caveats": [
            "Momentum's documented edge is a cross-sectional average, not a per-name promise",
            "It suffers sharp reversals at market turns, which is precisely when it looks best",
            "Written from public literature, so it is nobody's personal system",
        ],
    },
}


def build_context(bars: list[dict], spec: dict,
                  benchmark_bars: list[dict] | None = None) -> dict:
    ctx = {}
    if benchmark_bars:
        # Resampled to the method's own timeframe by the caller, so the two
        # returns cover the same window measured the same way.
        ctx["benchmark_bars"] = benchmark_bars
    for key, (name, args) in spec["indicators"].items():
        entry = I.REGISTRY.get(name)
        ctx[key] = entry["fn"](bars, *args) if entry else None
    return ctx


def evaluate(bars_daily: list[dict], method_key: str,
             benchmark_daily: list[dict] | None = None,
             benchmark_resampled: list[dict] | None = None) -> dict:
    """Score one symbol against one method on that method's own timeframe."""
    spec = METHODS.get(method_key)
    if not spec:
        return {"error": f"unknown method {method_key}"}
    bars = I.resample(bars_daily, spec["timeframe"])
    if len(bars) < 24:
        return {"method": method_key, "insufficient": True, "bars": len(bars)}

    # Callers that evaluate many symbols against ONE benchmark should resample
    # it once and pass it here. Resampling inside made the backtest redo the
    # whole benchmark series for every symbol at every rebalance date, which
    # tripled its runtime.
    bench = benchmark_resampled or (
        I.resample(benchmark_daily, spec["timeframe"]) if benchmark_daily else None)
    ctx = build_context(bars, spec, bench)
    results, score, possible, unavailable = [], 0, 0, 0
    for rule in spec["setup"]:
        fn = CONDITIONS.get(rule["condition"])
        if not fn:
            continue
        met, value, detail = fn(bars, ctx, **rule.get("args", {}))
        # A condition that COULD NOT BE COMPUTED is not a condition that failed.
        # Counting it in the denominator penalised a name for its listing date —
        # a 52-period monthly Ichimoku needs four years of history, so anything
        # younger scored down for existing recently rather than for anything
        # about its chart.
        if met is None:
            unavailable += rule["weight"]
        else:
            possible += rule["weight"]
            if met:
                score += rule["weight"]
        results.append({"condition": rule["condition"], "met": met, "value": value,
                        "detail": detail, "weight": rule["weight"], "why": rule["why"]})

    pct = score / possible if possible else 0.0
    total_weight = possible + unavailable
    return {
        "method": method_key, "name": spec["name"], "timeframe": spec["timeframe"],
        "score": score, "possible": possible, "pct": pct,
        # What share of the method's weight could actually be evaluated. A 100%
        # earned on a third of the conditions is not the same claim as a 100%
        # earned on all of them, and the two used to be indistinguishable.
        "coverage": (possible / total_weight) if total_weight else 0.0,
        "unavailable_weight": unavailable,
        "unavailable": [r["condition"] for r in results if r["met"] is None],
        "met": sum(1 for r in results if r["met"]),
        "total": len(results),
        "missing": [r["condition"] for r in results if r["met"] is False],
        "conditions": results,
        "close": bars[-1]["close"], "as_of": bars[-1]["time"],
    }


def catalogue() -> list[dict]:
    return [{"key": k, **{f: v[f] for f in
                          ("name", "source", "timeframe", "thesis", "evidence",
                           "invalidation", "ignores", "caveats")}}
            for k, v in METHODS.items()]


def scan(conn, symbols: list[str], method_key: str, end: str) -> dict:
    """Score every symbol against one method and rank them.

    Ranking is by proportion of the method's weighted conditions met, not by an
    absolute score, so methods with different numbers of conditions stay
    comparable. Names without enough history are reported separately rather
    than scored as zero, which would rank a new listing alongside a genuine
    failure.
    """
    from . import prices

    spec = METHODS.get(method_key)
    if not spec:
        return {"error": f"unknown method {method_key}"}

    # One benchmark load for the whole scan. Without it `outperforming` was
    # comparing each name against nothing at all.
    bench_daily = []
    resolved = prices.resolve_benchmark("SPY")
    if resolved:
        bench_daily = prices.load_bars(conn, resolved[0], "2010-01-01", end)
    if not bench_daily:
        bench_daily = prices.load_bars(conn, "SPY", "2010-01-01", end)

    bench_tf = I.resample(bench_daily, spec["timeframe"]) if bench_daily else None

    rows, skipped = [], []
    for sym in symbols:
        bars = prices.load_bars(conn, sym, "2010-01-01", end)
        r = evaluate(bars, method_key, benchmark_resampled=bench_tf)
        if r.get("insufficient") or r.get("error"):
            skipped.append({"symbol": sym, "bars": r.get("bars", 0)})
            continue
        rows.append({
            "symbol": sym, "pct": r["pct"], "score": r["score"], "possible": r["possible"],
            "coverage": r["coverage"], "unavailable": r["unavailable"],
            "met": r["met"], "total": r["total"], "missing": r["missing"],
            "close": r["close"], "as_of": r["as_of"],
            "conditions": r["conditions"],
        })
    # A name evaluated on a third of the method's weight must not head the table
    # the dashboard renders. qualifying was guarded; the ranked list was not.
    rows.sort(key=lambda x: (x["coverage"] < 0.6, -x["pct"], -x["coverage"],
                             x["symbol"]))
    return {"method": method_key, "name": spec["name"], "timeframe": spec["timeframe"],
            "rows": rows, "skipped": skipped,
            # Qualifying now also requires that most of the method was actually
            # computable. Without the coverage floor a name could clear 0.75 on
            # a third of the weight — its highest-weighted trend filter never
            # having been evaluated — and rank beside one that cleared it on
            # every condition.
            "qualifying": [r for r in rows
                           if r["pct"] >= 0.75 and r.get("coverage", 1.0) >= 0.6]}


def stack(conn, symbols: list[str], end: str, minimum: int = 2) -> list[dict]:
    """Names that several methods agree on.

    Agreement between independent methods is the whole reason to hold more than
    one. With a single method this returns nothing useful, which is honest —
    it becomes meaningful as the library grows.

    A hit needs the SAME coverage floor scan() applies to `qualifying`, and did
    not have it. This is the strongest thing the app says about a name, so it
    was also the worst place to drop the floor: a 150-session listing cleared
    0.75 on both methods while RonnieV's entire moving-average stack and the
    price-above-stack check went unevaluated for want of a 200-day average — 29%
    of that method's weight actually measured — and came back as "two methods
    agree, 0.90". scan() would not have put it in either method's shortlist.
    """
    per_method = {k: {r["symbol"]: r for r in scan(conn, symbols, k, end)["rows"]}
                  for k in METHODS}
    out = []
    for sym in symbols:
        hits = [{"method": k, "pct": v[sym]["pct"], "coverage": v[sym]["coverage"]}
                for k, v in per_method.items()
                if sym in v and v[sym]["pct"] >= 0.75
                and v[sym].get("coverage", 1.0) >= 0.6]
        if len(hits) >= minimum:
            out.append({"symbol": sym, "methods": hits,
                        "average": sum(h["pct"] for h in hits) / len(hits)})
    out.sort(key=lambda x: -x["average"])
    return out
