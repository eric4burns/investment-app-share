"""A verdict on a holding: buy, trim, hold or sell — and what would change it.

Every other module here reports a measurement. This one reaches a conclusion,
which is a different and more dangerous kind of output, so the rules it follows
are written down rather than tuned until the current book looks good.

## Why this exists at all

`methods.py` deliberately scores and never signals: "five of seven conditions,
here are the two that are missing". That is the right output when the question
is whether somebody else's process likes a name. It is the wrong output when
the question is "do I buy more of this on Monday", because it hands the whole
judgement back to the reader, which is the part they wanted help with.

So this module states a call. What keeps that honest is not hedging the call —
it is that every verdict ships with three things:

  * the evidence, each item naming the number that produced it,
  * the **flip level**: a price that would change the verdict, and
  * the timeframe it was reached on, because a daily buy inside a weekly
    downtrend is a different animal from one inside a weekly uptrend.

A verdict with no flip level is a horoscope. If a rule here cannot name the
price that would invalidate it, it does not get to be a verdict and degrades to
`hold` with the reason attached.

## Trim fires into strength, never into weakness

Trim is deliberately NOT a drawdown rule. A position down 20% from its own high
is ambiguous evidence — the same figure describes a broken thesis and a routine
pullback inside an intact uptrend, and nothing in the drawdown itself separates
them. Selling on it therefore cuts good positions on ordinary red days about as
often as it saves anything.

An advance into a level identified in advance is far less ambiguous, so trim
requires price to be in the UPPER part of its own swing leg and to have reached
a Fibonacci extension, an overbought oscillator, or an outsized portfolio
weight. Falling into a level is still shown as evidence, but it belongs to the
sell/hold judgement about whether the trend is intact, not to trim.

## What it will not tell you

It does not say a name is "topping" or "bottoming". Those are only identifiable
afterwards, and a rule claiming to name one in advance would be the part that
lies. What it states instead is where price sits inside its own swing, which
way the pivots are sequencing, and which side of the cloud it is on — all
checkable today, and all the parts of the question that can actually be
answered.
"""
from __future__ import annotations

from . import indicators as I, structure
# The level machinery moved to levels.py (it was half this module). Re-exported
# here because `verdicts` is the name every caller already holds, and a plan is
# what a verdict is FOR — splitting the file should not split the interface.
from .levels import (  # noqa: F401
    ACTIONABLE_PCT, MAX_TARGET_GAIN, MIN_TARGET_GAIN, MIN_LEVEL_TOUCHES,
    MIN_ENTRY_DROP, MIN_STOP_ATR, watch_levels, _targets, _watch_levels_for)

# Where in its own swing leg price has to be before an upside rule may fire.
# 0.60 rather than 0.5 so a name that has merely recovered half its decline is
# not treated as extended.
UPPER_LEG = 0.60
LOWER_LEG = 0.35

# Distance, in units of the instrument's own typical bar, within which price
# counts as AT a level rather than merely near one. Measured in ATR for the
# same reason structure.py measures in typical_range: a fixed percentage is
# several sessions of movement on SPY and far too tight on a $3 name.
AT_LEVEL_ATR = 0.75

# A position bigger than this is a trim candidate on size alone.
HEAVY_WEIGHT = 0.15

# How near price must be to a line before that line is evidence about NOW.
#
# A support line 94% below price is held trivially, and counting it as bullish
# is how CRWV scored 4.5 bullish against 4.0 bearish with 3.0 of that coming
# from two support lines at 43.87 and 44.98 while the stock traded at 85. The
# line is still worth REPORTING — it is where a decline would find support — but
# it is context, not evidence about today. A level becomes evidence when price
# is interacting with it, which is the same rule the horizontal zones already
# follow.
RELEVANT_ATR = 3.0

# Williams %R runs 0 (top of the range) to -100 (bottom). RonnieV uses length
# 12 with the bands at 0 and -100, calls it his favourite indicator, and reads a
# hit near the floor as "a bottom is in range" — then waits at a predetermined
# price rather than buying the signal. That is the only reading it is given
# weight for here.
#
# Deliberately one-sided. A stretched oscillator near the TOP is already covered
# by RSI and by the Fibonacci extensions, and adding a second overbought voice
# would double-count the same observation; near the bottom nothing else in this
# engine is looking. Between the two it says nothing worth a number.

WILLR_PERIOD = 12
WILLR_BOTTOM = -80.0
WILLR_FLOOR = -97.0      # the weekly floor, from the sweep of 2026-09-05

# A swing leg narrower than this many typical bars is not a swing.
#
# structure.py already makes the point that a drawn line looks authoritative
# whether or not it means anything, and it is worse here, because this module
# turns those lines into the word "sell". A near-flat series still produces
# pivots, still labels them LH and LL, and still puts price on one side of a
# cloud that is nearly as wide as the noise — which was enough to produce a
# confident sell on a series moving two cents. The whole swing has to be worth
# more than a few sessions of ordinary movement before any of it is read as
# direction.
MIN_LEG_ATR = 4.0

VERDICTS = ("buy", "add", "hold", "trim", "sell")


# Timeframes on which the Fibonacci RETRACEMENT reading is switched off.
#
# The replay of 2022-2026 (research/audits/measure-2026-09-03-update.md)
# found the weekly reading inverted: a name sitting on a retracement support
# went on to lag the day's average by 1.24 points over the next month
# (t -4.3 on 239 week-ends), and one at a retracement resistance went on to
# beat it by 1.59 (t 3.3). The strongest numbers in the whole measurement,
# and the opposite of what the item claims. Decided 2026-09-03: off on the
# weekly. It stays recorded at zero weight so the measurement continues, and
# it is no longer the level a weekly buy or add is taken at. The daily
# reading was noise either way and is unchanged; the extension reading
# (the take-profit target) agreed with its claim and is unchanged.
FIB_RETRACEMENT_OFF = {"W"}

# Timeframes on which the TREND items are switched off: the pivot sequence,
# the cloud, tenkan/kijun and the moving averages. Decided 2026-09-03 after
# the engine was replayed on 500 names drawn from the liquidity screen —
# a universe chosen for trading enough, not for having gone up — and every
# one of these read the opposite of its claim at a one-month horizon, at
# the same strength as on the watchlist (research/audits/
# measure-2026-09-03-screen-universe.md). They stay recorded at zero weight
# so the measurement continues, and on these timeframes the call itself
# comes from the measured score: top fifth of the record is a buy or add,
# bottom fifth a sell, the rest a hold. Levels the market has turned at
# (zones, trendlines, the extension targets) are not trend items and keep
# their weight, which is also where the stop under a measured call comes from.
TREND_OFF = {"W"}

# While the S&P is breaking — below its 200-day, or below a falling 50-day
# (regime.index_read) — a buy or add on any name is marked down one notch of
# confidence. The user's rule: the indices can override a setup. Off switches
# it to record-only.
INDEX_GATE = True
TREND_ITEMS = ("pivot sequence", "ichimoku", "tenkan/kijun", "moving averages")


def _last(series: list[dict]):
    return series[-1]["value"] if series else None


def _at_time(series: list[dict], when: str):
    """A displaced series' value at a given bar time.

    The Ichimoku cloud is plotted `kijun` bars ahead of the data it is computed
    from, so its entries are keyed by a FUTURE timestamp. Taking `series[-1]`
    would read the furthest projected value rather than the cloud standing over
    price today, which is the one a "reclaim the cloud" reading is about.
    """
    for row in reversed(series):
        if row["time"] <= when:
            return row["value"]
    return None


def _evidence(name: str, stance: str | None, detail: str, level=None, weight: float = 1.0):
    """One observation. `stance` is bull, bear, extended, or None for context."""
    return {"name": name, "stance": stance, "detail": detail,
            "level": (round(level, 4) if level is not None else None),
            "weight": weight}


# How many bars each timeframe needs before it is read at all.
#
# 60 was applied to every timeframe, which is five years of monthly candles and
# excluded almost every holding — so there was no monthly reading at all. The
# floor is really "enough bars for the indicators to mean something", and that
# is a different number per timeframe: at 36 months there is no Ichimoku cloud
# (senkou needs 52) but structure, Fibonacci and the averages all work, and the
# tally simply carries fewer items. Refusing the whole timeframe instead was
# strictly worse.
# Two years of monthly bars is enough to read; three is the full read. Names
# with 24–35 months are scored on the monthly with confidence capped at low and
# flagged `thin`, rather than shown as "too new" beside names the user knows
# have traded for years (GEV, TEM, ALAB, FBTC were all between two and three).
MIN_BARS = {"D": 60, "W": 60, "M": 24}
FULL_BARS = {"D": 60, "W": 60, "M": 36}

# The proximity unit is the ATR, capped as a share of price. A monthly ATR on a
# name whose split-adjusted history sits far above today's price (ASST after
# its reverse split and long decline: 37.57 on a 27 stock) made every
# level "at" price and a resistance 828% away "close enough to matter". A
# level is near when it is within a bar's move OR within these caps, whichever
# is smaller.
# Loose enough that an ordinary volatile name (IREN moves 8% in a day, 17% in
# a week) keeps its own bar as the unit; only a history whose adjusted prices
# dwarf today's is bounded.
UNIT_CAP = {"D": 0.08, "W": 0.15, "M": 0.20}


def proximity_unit(price: float, atr: float, timeframe: str) -> float:
    return min(atr or price * 0.02, price * UNIT_CAP.get(timeframe, 0.05))


# How far ahead to look after price reaches the cloud before calling the
# episode decided, and the fewest episodes before the record is quoted at all.
CLOUD_LOOKAHEAD = 10
CLOUD_MIN_EPISODES = 2


def cloud_record(bars: list[dict], ich: dict) -> dict:
    """What THIS name's cloud has actually done when price reached it.

    "Below the cloud; it caps rallies" is the textbook reading and it was being
    stated for every name regardless of that name's own history — DGXX had
    gone straight up through its cloud on the previous leg and the sentence
    said it capped rallies anyway. So the claim is checked: every time price
    was under the cloud and reached its floor, did it get turned back or did
    it close above the top within a couple of weeks? The same from above. The
    counts are reported alongside the reading, and when the record says the
    opposite of the textbook, the reading carries less weight.
    """
    a = {r["time"]: r["value"] for r in ich.get("span_a", [])}
    b = {r["time"]: r["value"] for r in ich.get("span_b", [])}
    from_below = {"turned": 0, "through": 0}
    from_above = {"held": 0, "through": 0}
    i, n = 1, len(bars)
    while i < n:
        t, pt = bars[i]["time"], bars[i - 1]["time"]
        if any(k not in a or k not in b for k in (t, pt)):
            i += 1
            continue
        top, bot = max(a[t], b[t]), min(a[t], b[t])
        ptop, pbot = max(a[pt], b[pt]), min(a[pt], b[pt])
        prev = bars[i - 1]["close"]
        outcome = None
        if prev < pbot and bars[i]["high"] >= bot:
            # Reached from below. Through if a close clears the top; turned
            # back if it closes under the floor again first (or never clears).
            outcome = "turned"
            for j in range(i, min(n, i + CLOUD_LOOKAHEAD)):
                tj = bars[j]["time"]
                if tj not in a:
                    break
                tj_top, tj_bot = max(a[tj], b[tj]), min(a[tj], b[tj])
                if bars[j]["close"] > tj_top:
                    outcome = "through"
                    break
                if j > i and bars[j]["close"] < tj_bot:
                    break
            from_below[outcome] += 1
        elif prev > ptop and bars[i]["low"] <= top:
            outcome = "held"
            for j in range(i, min(n, i + CLOUD_LOOKAHEAD)):
                tj = bars[j]["time"]
                if tj not in a:
                    break
                tj_top, tj_bot = max(a[tj], b[tj]), min(a[tj], b[tj])
                if bars[j]["close"] < tj_bot:
                    outcome = "through"
                    break
                if j > i and bars[j]["close"] > tj_top:
                    break
            from_above[outcome] += 1
        if outcome:
            i += CLOUD_LOOKAHEAD          # one episode, not one per bar inside it
        else:
            i += 1
    return {"from_below": from_below, "from_above": from_above}


def _cloud_claim(record: dict, side: str) -> tuple[str, float]:
    """The sentence and the weight the cloud reading has earned on this name."""
    if side == "below":
        r = record["from_below"]
        total = r["turned"] + r["through"]
        if total < CLOUD_MIN_EPISODES:
            return " — too few approaches in this history to say how it has behaved", 1.5
        if r["through"] > r["turned"]:
            return (f" — but on this name it has NOT held: price went straight through "
                    f"{r['through']} of the {total} times it reached the cloud from below, "
                    f"so this is read at half weight"), 0.75
        return f" — it has turned price back {r['turned']} of the {total} times it was reached from below", 1.5
    r = record["from_above"]
    total = r["held"] + r["through"]
    if total < CLOUD_MIN_EPISODES:
        return " — too few tests in this history to say how it has behaved", 1.5
    if r["through"] > r["held"]:
        return (f" — but on this name it has NOT held: price fell through "
                f"{r['through']} of the {total} times it came down to the cloud, "
                f"so this is read at half weight"), 0.75
    return f" — it has held {r['held']} of the {total} times price came down to it", 1.5


def gather(bars: list[dict], position: dict | None = None,
           market: dict | None = None, timeframe: str = "D",
           context: dict | None = None) -> dict:
    """Every piece of evidence, on bars already resampled to one timeframe.

    `context` carries what one name's bars cannot know: today its relative-
    strength rank across the list, computed by the caller for the same date.
    """
    ev: list[dict] = []
    if len(bars) < MIN_BARS.get(timeframe, 60):
        return {"insufficient": True, "bars": len(bars), "evidence": ev,
                "needed": MIN_BARS.get(timeframe, 60), "first": bars[0]["time"] if bars else None}
    thin = len(bars) < FULL_BARS.get(timeframe, 60)

    price = bars[-1]["close"]
    atr_series = I.atr(bars, 14)
    true_atr = _last(atr_series) or (price * 0.02)
    # Everything below that asks "is price near this" uses the capped unit.
    atr = proximity_unit(price, true_atr, timeframe)
    st = structure.detect(bars, unit_cap=UNIT_CAP.get(timeframe))
    fib = st.get("fib")
    # The CYCLE leg, the way StonkChris anchors his targets: the low of the
    # last 250 bars and the highest close in the 250 bars before that low.
    # 1.0 is the prior high, 1.618 the primary target, 2.0 the stretch. The
    # swing fib above is the last 120-bar move; this is the whole cycle, and
    # it is what a trim target on a name that has run should be measured on.
    cycle = None
    year = {"D": 250, "W": 52, "M": 12}.get(timeframe, 250)     # one year of this timeframe's bars
    if len(bars) >= max(20, year // 4):
        cl = [b["close"] for b in bars]
        w0 = max(0, len(cl) - year)
        lo_i = min(range(w0, len(cl)), key=lambda k: cl[k])
        prior = cl[max(0, lo_i - year):lo_i]
        if prior:
            hi_i = max(range(max(0, lo_i - year), lo_i), key=lambda k: cl[k])
            low, high = cl[lo_i], cl[hi_i]
            if high > low * 1.15:
                leg = high - low
                cycle = {"low": round(low, 4), "high": round(high, 4), "low_time": bars[lo_i]["time"],
                         "high_time": bars[hi_i]["time"], "one": round(high, 4),
                         "e1618": round(low + 1.618 * leg, 4), "e20": round(low + 2.0 * leg, 4),
                         "e2618": round(low + 2.618 * leg, 4)}
    # Named for what it asks, and NOT reused. This was `near`, which the
    # trendline loop below then rebound to a bool — leaving the function one
    # reordering away from calling a boolean and raising TypeError on every
    # symbol. It is a latent bug rather than a live one only because every use
    # of the lambda happens to precede the loop.
    at_same_price = lambda a, b: abs(a - b) <= AT_LEVEL_ATR * atr

    # ---- where price sits inside its own swing leg ------------------------
    # This is the answer to "is it topping or bottoming" that can actually be
    # stated: not a prediction, a location.
    leg_pos, leg_atr = None, None
    if fib:
        lo = min(fib["from"]["price"], fib["to"]["price"])
        hi = max(fib["from"]["price"], fib["to"]["price"])
        leg_atr = (hi - lo) / atr if atr else None
        if hi > lo:
            leg_pos = (price - lo) / (hi - lo)
            where = ("upper third" if leg_pos >= 0.67 else
                     "lower third" if leg_pos <= 0.33 else "middle")
            ev.append(_evidence(
                "swing location", None,
                f"{where} of a {fib['direction']} leg from {lo:,.2f} to {hi:,.2f} "
                f"({leg_pos * 100:.0f}% of the range)"))

    # ---- pivot sequence: the trend, as structure rather than as an average --
    highs = [p for p in st.get("pivots", []) if p["kind"] == "high"]
    lows = [p for p in st.get("pivots", []) if p["kind"] == "low"]
    seq = None
    if highs and lows:
        lh, ll = highs[-1]["label"], lows[-1]["label"]
        if lh == "HH" and ll == "HL":
            seq, stance = "higher highs and higher lows", "bull"
        elif lh == "LH" and ll == "LL":
            seq, stance = "lower highs and lower lows", "bear"
        else:
            seq, stance = f"{lh} then {ll}", None
        ev.append(_evidence("pivot sequence", stance, seq,
                            level=lows[-1]["price"], weight=1.5))

    # ---- Ichimoku cloud ---------------------------------------------------
    ich = I.ichimoku(bars)
    now = bars[-1]["time"]
    a, b = _at_time(ich["span_a"], now), _at_time(ich["span_b"], now)
    cloud_top = cloud_bot = None
    record = cloud_record(bars, ich) if (a is not None and b is not None) else None
    if a is not None and b is not None:
        cloud_top, cloud_bot = max(a, b), min(a, b)
        if price > cloud_top:
            tail, w = _cloud_claim(record, "above")
            ev.append(_evidence("ichimoku", "bull",
                                f"above the cloud; it holds support at {cloud_top:,.2f}{tail}",
                                level=cloud_top, weight=w))
        elif price < cloud_bot:
            tail, w = _cloud_claim(record, "below")
            ev.append(_evidence("ichimoku", "bear",
                                f"below the cloud; it caps rallies at {cloud_bot:,.2f}{tail}",
                                level=cloud_bot, weight=w))
        else:
            ev.append(_evidence("ichimoku", None,
                                f"inside the cloud ({cloud_bot:,.2f}–{cloud_top:,.2f}), "
                                f"which is the definition of no trend",
                                level=cloud_bot))

    conv, base = _last(ich["conversion"]), _last(ich["base"])
    if conv is not None and base is not None:
        ev.append(_evidence("tenkan/kijun", "bull" if conv > base else "bear",
                            f"conversion {conv:,.2f} {'above' if conv > base else 'below'} "
                            f"base {base:,.2f}", level=base, weight=0.5))

    # ---- Fibonacci: which level price is actually standing on -------------
    at_level = None
    if fib:
        rising = fib["direction"] == "up"
        fib_off = timeframe in FIB_RETRACEMENT_OFF
        for lv in fib["levels"]:
            if not at_same_price(price, lv["price"]):
                continue
            if lv["kind"] == "retracement":
                # In a rising leg a retracement is support underneath; in a
                # falling one the same construction is resistance overhead.
                # On a timeframe where the reading is switched off it is still
                # recorded — at zero weight, and not as a level to act at — so
                # the replay keeps measuring it.
                if not fib_off:
                    at_level = lv
                ev.append(_evidence(
                    "fibonacci", "bull" if rising else "bear",
                    f"at the {lv['ratio']:.3f} retracement "
                    f"({'support' if rising else 'resistance'}) at {lv['price']:,.2f}"
                    + (" — switched off on this timeframe: the replay found the "
                       "opposite of what it claims" if fib_off else ""),
                    level=lv["price"], weight=0.0 if fib_off else 1.5))
            else:
                at_level = lv
                ev.append(_evidence(
                    "fibonacci", "extended" if rising else "bear",
                    f"at the {lv['ratio']:.3f} extension at {lv['price']:,.2f}"
                    f"{' — an upside target, reached' if rising else ''}",
                    level=lv["price"], weight=1.5))
            break

        # Reached an extension without necessarily sitting on one.
        if rising:
            hit = [lv for lv in fib["levels"]
                   if lv["kind"] == "extension" and price >= lv["price"]]
            if hit and at_level is None:
                top = max(hit, key=lambda l: l["ratio"])
                ev.append(_evidence("fibonacci", "extended",
                                    f"trading above the {top['ratio']:.3f} extension "
                                    f"({top['price']:,.2f})",
                                    level=top["price"], weight=1.0))

    # ---- the deep-pullback band and the trim targets, at ZERO weight -------
    # Read off the charts the user saved from X on 2026-09-03: Mind Investor's
    # "Reversal Zone" on SMR, Freedom By 40's boxed 0.618-0.786 on IREN, the
    # SIVE wave count ending at 0.786/0.887; and the 1.272/1.414/1.618
    # extension targets AsafNaaman15 draws above ASST's shelf. Separate from
    # the weighted Fibonacci item above so nothing already measured moves.
    if fib and fib.get("reversal_zone"):
        rz = fib["reversal_zone"]
        rising = fib["direction"] == "up"
        # Inside the band, with tolerance only on the side the leg came from:
        # under the band in a rising leg the pullback has given back MORE
        # than 0.887 and is not holding anything.
        inside = ((rz["low"] <= price <= rz["high"] + AT_LEVEL_ATR * atr) if rising
                  else (rz["low"] - AT_LEVEL_ATR * atr <= price <= rz["high"]))
        if inside:
            ev.append(_evidence(
                "reversal zone", "bull" if rising else "bear",
                f"in the {rz['ratios'][0]:.3f}–{rz['ratios'][1]:.3f} band of the "
                f"{'rising' if rising else 'falling'} leg ({rz['low']:,.2f}–{rz['high']:,.2f}) — "
                + ("a pullback that has given back nearly the whole move and is holding; "
                   "the 'reversal zone' the wave-count charts buy"
                   if rising else
                   "a rally that has recovered nearly the whole decline; where the "
                   "wave-count charts expect it to fail"),
                level=rz["low"] if rising else rz["high"], weight=0.0))
    if fib and fib.get("targets") and fib["direction"] == "up":
        # A target more than double the price is arithmetic on a weekly leg,
        # not a level anyone trims into; the charts' targets sit 10-40% up.
        above = [t for t in fib["targets"]
                 if price + AT_LEVEL_ATR * atr < t["price"] <= price * (1 + MAX_TARGET_GAIN)]
        if above:
            nxt = min(above, key=lambda t: t["price"])
            ev.append(_evidence(
                "target", None,
                f"next extension target the {nxt['ratio']:.3f} at {nxt['price']:,.2f} "
                f"({(nxt['price'] / price - 1) * 100:+.1f}%) — where the charts saved from X "
                f"take the first trim", level=nxt["price"], weight=0.0))

    # ---- horizontal levels: what price has actually turned at before ------
    # The most commonly asked question about a chart, and the one this engine
    # could not answer at all until zones existed: trendlines and Fibonacci
    # both describe moving boundaries, and neither is what somebody means by
    # "where is support".
    zs = st.get("zones") or []
    near_z = structure.nearest_zones(zs, price)
    if near_z["at"]:
        z = near_z["at"]
        ev.append(_evidence(
            "level", "bull" if z["flipped"] else None,
            f"sitting on a level tested {z['touches']} times "
            f"({z['low']:,.2f}–{z['high']:,.2f}, last {z['last']})"
            + (" — it has acted as both support and resistance" if z["flipped"] else ""),
            level=z["price"], weight=1.5 if z["flipped"] else 1.0))
    if near_z["support"]:
        z = near_z["support"]
        ev.append(_evidence(
            "support", None,
            f"nearest support {((price / z['high']) - 1) * 100:.1f}% below at "
            f"{z['low']:,.2f}–{z['high']:,.2f}, {z['touches']} touches"
            + (" (flipped)" if z["flipped"] else ""), level=z["high"]))
    if near_z["resistance"]:
        z = near_z["resistance"]
        gap = (z["low"] / price) - 1
        ev.append(_evidence(
            "resistance", "bear" if gap < 0.03 else None,
            f"resistance {gap * 100:.1f}% above at {z['low']:,.2f}–{z['high']:,.2f}, "
            f"{z['touches']} touches" + (" (flipped)" if z["flipped"] else "")
            + (" — close enough to cap a move from here" if gap < 0.03 else ""),
            level=z["low"], weight=1.0))

    # A level whose most recent touch came from the OTHER side than its
    # earlier ones — Con's "Previous support is now resistance", and the
    # mirror, a broken shelf retested from above that is now support (TEM's
    # 62, which this engine kept calling resistance). Zero weight.
    rf = role_flip_item(near_z, price, atr)
    if rf:
        ev.append(_evidence("role flip", rf["stance"], rf["detail"],
                            level=rf["level"], weight=0.0))

    # ---- trendlines, already fitted and previously discarded --------------
    live = [l for l in st.get("trendlines", [])
            if l.get("reaches_present") and l.get("confirmations", 0) >= 1]
    # Two lines a few cents apart are one piece of structure counted twice, and
    # CRWV carried exactly that: 43.87 and 44.98, both weighted 1.5.
    unique, seen_at = [], []
    for line in sorted(live, key=lambda l: -l["touches"]):
        at_now = line["to"]["price"]
        if any(abs(at_now - s) <= AT_LEVEL_ATR * atr for s in seen_at):
            continue
        seen_at.append(at_now)
        unique.append(line)

    for line in unique[:3]:
        at_now = line["to"]["price"]
        # A line projected to zero or below is arithmetic, not a level: it
        # happens on a monthly resample of a name that has fallen 95%, where
        # a steep line through two old highs reaches the floor before the
        # present. The replay found it by dividing by it.
        if not at_now or at_now <= 0:
            continue
        rising = line["to"]["price"] > line["from"]["price"]
        held = price > at_now
        gap_atr = abs(price - at_now) / atr if atr else 99.0
        close_enough = gap_atr <= RELEVANT_ATR
        side = "support" if line["side"] == "support" else "resistance"
        where = (f"{(price / at_now - 1) * 100:+.1f}% "
                 f"{'above' if held else 'below'} it")
        if line.get("flipped_from"):
            n = line.get("retests", 0)
            side = (f"line, {line['flipped_from']} until price broke "
                    f"{'above' if line['flipped_from'] == 'resistance' else 'below'} it on "
                    f"{line['broke_on']} and now {side}, retested {n} time{'' if n == 1 else 's'} since,")
        if close_enough:
            stance = "bull" if held else "bear"
            tail = f" — price is {where}, close enough to matter"
        else:
            # Reported, not scored. Distance is the whole reason.
            stance = None
            tail = (f" — price is {where}, too far away to be evidence about "
                    f"today; this is where a move would meet it")
        ev.append(_evidence(
            "trendline", stance,
            f"{'rising' if rising else 'falling'} {side}{'' if line.get('flipped_from') else ' line'} from "
            f"{line['from']['time']}, {line['touches']} touches, now at "
            f"{at_now:,.2f}{tail}",
            level=at_now,
            weight=(1.5 if line["touches"] >= 4 else 1.0) if close_enough else 0.0))

    # ---- channel ----------------------------------------------------------
    channel_rec = None
    for ch in (st.get("channels") or [])[:1]:
        top = ch.get("upper", {}).get("to", {}).get("price")
        bot = ch.get("lower", {}).get("to", {}).get("price")
        if top and bot and top > bot:
            pos = (price - bot) / (top - bot)
            ev.append(_evidence(
                "channel", None,
                f"in a channel {bot:,.2f}–{top:,.2f}, {pos * 100:.0f}% of the way up it",
                level=bot))
        # What each earlier touch of the edges produced — the AEVA chart's
        # "+95%, +158%, +110%" written beside each floor touch. Zero weight.
        base = next((l for l in st.get("trendlines", [])
                     if l["from"]["time"] == ch["from"]["time"]
                     and l["to"]["time"] == ch["to"]["time"]
                     and not l.get("flipped_from")), None)
        unit = st.get("unit") or atr
        # The same window detect() fitted the line on, so the anchors resolve.
        window = bars[-(st.get("bars") or len(bars)):]
        channel_rec = structure.channel_touches(window, base, ch, unit) if base else None
        if channel_rec:
            item = channel_record_item(channel_rec, price, atr)
            if item:
                ev.append(_evidence(item["name"], item["stance"], item["detail"],
                                    level=item["level"], weight=0.0))

    # ---- moving averages --------------------------------------------------
    mas = {}
    for n in (20, 50, 200):
        series = I.sma(bars, n)
        val = _last(series)
        if val is None:
            continue
        prev = series[-min(len(series), 6)]["value"] if len(series) > 5 else None
        mas[n] = {"value": val, "rising": (prev is not None and val > prev)}
    if mas:
        above = [n for n, m in mas.items() if price > m["value"]]
        stacked = (len(mas) == 3 and mas[20]["value"] > mas[50]["value"] > mas[200]["value"])
        ev.append(_evidence(
            "moving averages",
            "bull" if len(above) == len(mas) else "bear" if not above else None,
            "above the " + ", ".join(str(n) for n in above) + "-day"
            if above else "below every moving average",
            level=(min(mas[n]["value"] for n in above) if above else None),
            weight=1.5 if stacked and len(above) == 3 else 1.0))

    # ---- moving-average items from the transcripts, recorded at ZERO weight -
    # RonnieV's moving-average rules (research/transcript-notes-2026-09-03.md):
    # the 20 crossing the 50, the 50 crossing the 200, a pullback INTO a rising
    # average in an uptrend as the entry, and price stretched far above its
    # average as the reason to wait. They are carried with a stance so the
    # replay records and measures them, and with weight zero so they change no
    # verdict until the measurement says they should. That is the order the
    # September measurement set: measure first, weight second.
    def _series_by_time(n):
        return {r["time"]: r["value"] for r in I.sma(bars, n)}
    s20, s50, s200 = _series_by_time(20), _series_by_time(50), _series_by_time(200)
    times = [b["time"] for b in bars]

    def _cross(fast, slow, label):
        rel = [(fast[t] > slow[t]) for t in times if t in fast and t in slow]
        if len(rel) < 2:
            return
        above = rel[-1]
        ago = next((i for i in range(1, len(rel)) if rel[-1 - i] != above), None)
        recent = ago is not None and ago <= 10
        ev.append(_evidence(
            label, "bull" if above else "bear",
            f"{label}: the faster average is {'above' if above else 'below'} the slower"
            + (f", crossed {ago} bars ago" if recent else
               (f", for {ago} bars" if ago is not None else " for the whole window")),
            weight=0.0))
    _cross(s20, s50, "ma cross 20/50")
    _cross(s50, s200, "ma cross 50/200")

    if mas and 20 in mas and 200 in mas:
        m20 = mas[20]["value"]
        gap_atr = (price - m20) / atr if atr else 0.0
        uptrend = price > mas[200]["value"] and mas[20]["rising"]
        downtrend = price < mas[200]["value"] and not mas[20]["rising"]
        if uptrend and -1.0 <= gap_atr <= 1.0:
            ev.append(_evidence("pullback to average", "bull",
                                f"within one typical bar of a rising 20-day average "
                                f"({m20:,.2f}) with price above the 200-day — the entry "
                                f"RonnieV describes", level=m20, weight=0.0))
        elif downtrend and -1.0 <= gap_atr <= 1.0:
            ev.append(_evidence("pullback to average", "bear",
                                f"within one typical bar of a falling 20-day average "
                                f"({m20:,.2f}) with price below the 200-day — a rally into "
                                f"the average in a downtrend", level=m20, weight=0.0))
        elif gap_atr >= 3.0:
            ev.append(_evidence("stretched from average", "extended",
                                f"{gap_atr:.1f} typical bars above the 20-day average "
                                f"({m20:,.2f}) — far from the trend line, where he nibbles "
                                f"rather than buys", level=m20, weight=0.0))

    # ---- Williams %R, but only when it is near the floor ------------------
    wr_series = I.williams_r(bars, WILLR_PERIOD, 0.0, -100.0)
    wr = _last(wr_series)
    if wr is not None and wr <= WILLR_BOTTOM:
        # The record of earlier floor hits on this name — RonnieV's SMH chart
        # writes the rally after each one beside it (15.68%, 24.25%, 6.53%,
        # 76.30%), which is the argument, not the reading itself.
        rec = floor_record(bars, wr_series, WILLR_BOTTOM)
        tail = ""
        if rec["episodes"]:
            shown = ", ".join(f"{e['gain_pct']:+.1f}%" for e in rec["episodes"][-4:])
            tail = (f". The last {len(rec['episodes'][-4:])} times it was here, the "
                    f"best gain within {rec['horizon']} bars was {shown}"
                    f" (median {rec['median_pct']:+.1f}%)")
        ev.append(_evidence(
            "williams %r", "bull",
            # %R of -80 puts price 80% of the way DOWN from the period high,
            # which is the bottom 20% of the range — not the bottom 80%.
            f"Williams %R at {wr:.0f} on a {WILLR_PERIOD}-period setting — the "
            f"bottom {100 + WILLR_BOTTOM:.0f}% of its range, which is RonnieV's "
            f"reading that a bottom is in range. Not a trigger: he waits at a "
            f"price rather than buying the signal" + tail))

    # ---- the weekly floor: Williams %R 14 at -97 or under -----------------
    # The strongest single reading the sweep of every indicator found on the
    # user's names (research/audits/sweep-IREN-2026-09-05.md): on IREN since
    # 2023, every weekly reading at or under -97 was within 8% of a low that
    # then rallied 81% to 590%; in the 2022 collapse it fired three times and
    # kept falling. Weekly bars only; zero weight until the replay has it.
    if timeframe == "W":
        wr14 = _last(I.williams_r(bars, 14, 0.0, -100.0))
        if wr14 is not None and wr14 <= WILLR_FLOOR:
            ev.append(_evidence(
                "williams floor", "bull",
                f"weekly Williams %R (14) at {wr14:.0f} — the floor. On IREN since 2023 every such "
                f"reading was within 8% of a low that rallied 81–590%; in the 2022 collapse it "
                f"fired three times and kept falling, so it needs the business intact",
                weight=0.0))

    # ---- oscillator -------------------------------------------------------
    rsi_series = I.rsi(bars, 14)
    rsi = _last(rsi_series)
    if rsi is not None:
        if rsi >= 70:
            ev.append(_evidence("rsi", "extended", f"RSI {rsi:.0f} — overbought")
                      )
        elif rsi <= 30:
            ev.append(_evidence("rsi", "bull", f"RSI {rsi:.0f} — washed out"))
        else:
            ev.append(_evidence("rsi", None, f"RSI {rsi:.0f}"))
        # Structure on the oscillator: price at a lower low while RSI holds a
        # higher low (or the mirror at highs). The AEVA chart draws the line
        # under RSI's rising lows at the channel floor; Cantonese Cat and
        # StonkChris read divergence the same way. Zero weight.
        dv = rsi_divergence(bars, rsi_series)
        if dv:
            ev.append(_evidence("rsi divergence", dv["stance"], dv["detail"], weight=0.0))

    # ---- what the market as a whole is feeling ----------------------------
    # Passed in rather than fetched, so scoring stays offline and every symbol
    # on one evening is scored against the SAME reading. It carries weight only
    # at the extremes; see sentiment.py for why a market-wide number that fires
    # every day is one that can never be measured.
    if market:
        ev.append(_evidence(market["name"], market["stance"], market["detail"],
                            weight=market["weight"]))

    # ---- Phase 2 candidates, recorded at zero weight ---------------------
    near_support = (near_z.get("support") and abs(price - near_z["support"]["high"]) <= AT_LEVEL_ATR * atr)
    near_resistance = (near_z.get("resistance") and abs(near_z["resistance"]["low"] - price) <= AT_LEVEL_ATR * atr)
    at_a_level = bool(near_z.get("at")) or at_level is not None or bool(near_support) or bool(near_resistance)

    vi = volume_items(bars)
    if vi["heavy"] and vi["down_bar"] and (near_z.get("at") or near_support):
        ev.append(_evidence("absorption", "bull",
                            f"heavy selling ({vi['ratio']:.1f}x average volume) that closed on a level "
                            f"rather than through it — Cantonese Cat's absorption", weight=0.0))
    elif vi["heavy"] and vi["down_bar"] is False and (near_z.get("at") or near_resistance):
        ev.append(_evidence("absorption", "bear",
                            f"heavy buying ({vi['ratio']:.1f}x average volume) that stalled at a level "
                            f"rather than clearing it", weight=0.0))
    if vi["up_share"] is not None:
        if vi["up_share"] >= 0.65:
            ev.append(_evidence("volume commitment", "bull",
                                f"up bars carried {vi['up_share'] * 100:.0f}% of the last ten sessions' "
                                f"volume — the move up is the committed one", weight=0.0))
        elif vi["up_share"] <= 0.35:
            ev.append(_evidence("volume commitment", "bear",
                                f"down bars carried {(1 - vi['up_share']) * 100:.0f}% of the last ten "
                                f"sessions' volume — the move down is the committed one", weight=0.0))
    gp = gap_item(bars)
    if gp:
        ev.append(_evidence("gap", gp["stance"], gp["detail"], weight=0.0))
    if vi["obv_above"] is not None:
        ev.append(_evidence("obv", "bull" if vi["obv_above"] else "bear",
                            f"on-balance volume {'above' if vi['obv_above'] else 'below'} its 20-bar average",
                            weight=0.0))

    if at_a_level and len(bars) >= 2:
        cp = candle_pattern(bars[-2], bars[-1])
        if cp and cp[1] in ("bull", "bear"):
            ev.append(_evidence("candlestick", cp[1],
                                f"{cp[0]} at a level, closing at {price:,.2f}", weight=0.0))
        elif cp:
            ev.append(_evidence("candlestick", None,
                                f"doji at a level, closing at {price:,.2f} — indecision, not direction"))

    gl = gann_level(fib, price, atr)
    if gl:
        label, level, rising = gl
        ev.append(_evidence("gann", "bull" if rising else "bear",
                            f"at the {label} fraction of the leg ({level:,.2f}) — "
                            f"{'support' if rising else 'resistance'} by Cantonese Cat's reading",
                            level=level, weight=0.0))

    dp = double_pattern(st.get("pivots", []), price)
    if dp:
        stance = ("bull" if dp["kind"] == "double bottom" else "bear") if dp["confirmed"] else None
        ev.append(_evidence("pattern", stance,
                            f"{dp['kind']} {'confirmed' if dp['confirmed'] else 'forming'}, neckline "
                            f"{dp['neck']:,.2f}", level=dp["neck"], weight=0.0))

    # The other shapes on the RonnieV graphic, at zero weight. Names are
    # distinct so the replay measures each shape on its own.
    hs = head_shoulders(st.get("pivots", []), price, atr)
    if hs:
        ev.append(_evidence("head and shoulders", hs["stance"],
                            f"{hs['kind']} {'confirmed' if hs['confirmed'] else 'forming'}: head "
                            f"{hs['head']:,.2f}, shoulders {hs['shoulders'][0]:,.2f} / "
                            f"{hs['shoulders'][1]:,.2f}, neckline {hs['neck']:,.2f}",
                            level=hs["neck"], weight=0.0))
    tp = triple_pattern(st.get("pivots", []), price, atr)
    if tp:
        ev.append(_evidence("triple", tp["stance"],
                            f"{tp['kind']} {'confirmed' if tp['confirmed'] else 'forming'} at "
                            f"{tp['levels'][0]:,.2f} / {tp['levels'][1]:,.2f} / {tp['levels'][2]:,.2f}, "
                            f"neckline {tp['neck']:,.2f}", level=tp["neck"], weight=0.0))
    # Cup and handle needs more history than the 120-bar structure window (a
    # cup can run fifteen months), so its pivots are found on the last 400
    # bars and the indices are relative to that slice. Zero weight until the
    # study and the replay have measured it.
    cup_window = bars[-400:]
    ch = cup_handle(cup_window, structure.pivots(cup_window, 3, 3), price, atr)
    if ch:
        ev.append(_evidence("cup and handle", ch["stance"],
                            f"cup and handle {'confirmed' if ch['confirmed'] else 'forming'}: cup "
                            f"{ch['depth'] * 100:.0f}% deep over {ch['cup_bars']} bars from "
                            f"{ch['left_rim']:,.2f}, handle {ch['handle_depth'] * 100:.0f}% deep over "
                            f"{ch['handle_bars']} bars, pivot {ch['pivot']:,.2f}"
                            + (f", breakout volume {ch['volume_ratio']:.1f}x the 50-day average"
                               if ch["confirmed"] and ch.get("volume_ratio") else ""),
                            level=ch["pivot"], weight=0.0))
    idx_by_time = {b["time"]: i for i, b in enumerate(bars)}
    cl = converging_lines(st.get("trendlines", []), price, atr, idx_by_time)
    if cl:
        ev.append(_evidence("triangle" if "triangle" in cl["kind"] else "wedge", cl["stance"],
                            f"{cl['kind']} forming between {cl['lower']:,.2f} and {cl['upper']:,.2f} "
                            f"({cl['width_atr']:.1f} typical bars wide) — "
                            + ("resolves upward more often than not" if cl["stance"] == "bull"
                               else "resolves downward more often than not" if cl["stance"] == "bear"
                               else "breaks either way; the direction is the signal"),
                            level=cl["lower"], weight=0.0))

    # The phase, by Con's reading: a higher low after a lower low under a
    # lower high is accumulation forming; a lower high after a higher high
    # over a higher low is distribution forming. The pivot sequence above
    # already scores the trending cases; this names the turn. Zero weight.
    ph = phase_item(st.get("pivots", []), price, atr)
    if ph:
        ev.append(_evidence("phase", ph["stance"], ph["detail"], level=ph["level"], weight=0.0))

    # Volume by price: is there a heavy node under price and thin air above
    # it, or the reverse? SteveUrkeldude's IREN chart. Zero weight.
    vp = I.volume_profile(bars)
    tv = thin_volume(vp, price) if vp else None
    if tv:
        ev.append(_evidence("volume profile", tv["stance"], tv["detail"],
                            level=tv["level"], weight=0.0))

    # Relative strength across the list, at zero weight. The one direction
    # the measurement has agreed on so far is momentum — overbought kept
    # outperforming — and this is the standard form of it: the name's
    # composite return ranked against every other name watched, the most
    # recent quarter counted double. Top fifth is bullish, bottom fifth
    # bearish, the middle is context.
    rs = (context or {}).get("rs_rank")
    if rs is not None:
        stance = "bull" if rs >= 80 else "bear" if rs <= 20 else None
        ev.append(_evidence("relative strength", stance,
                            f"relative strength rank {rs} of 99 across the list"
                            + (" — top fifth" if rs >= 80 else " — bottom fifth" if rs <= 20 else ""),
                            weight=0.0))

    # The exposure dial (regime.py), at zero weight: clear skies is bullish
    # context, risk-off bearish, windy neither. Computed by the caller for
    # the same date, so the replay can measure whether it predicts anything.
    rg = (context or {}).get("regime")
    if rg:
        ev.append(_evidence("regime", "bull" if rg["state"] == "on" else "bear" if rg["state"] == "off" else None,
                            f"exposure dial reads {rg['label']} ({rg['score']:+d} of 4)", weight=0.0))

    # The indices' own read (regime.index_read), at zero weight: the S&P's
    # weekly call sets it. Recorded so the replay can measure whether the
    # market overriding a setup is a real effect at this horizon.
    ix = (context or {}).get("index")
    if ix and ix.get("indices"):
        ev.append(_evidence("index", "bull" if ix.get("state") == "with" else "bear" if ix.get("state") == "against" else None,
                            f"the market: {ix.get('summary', '')}", weight=0.0))

    # ---- size: a reason to trim that has nothing to do with the chart -----
    if position and (position.get("weight") or 0) >= HEAVY_WEIGHT:
        ev.append(_evidence("weight", "extended",
                            f"{position['weight'] * 100:.0f}% of the portfolio, "
                            f"above the {HEAVY_WEIGHT * 100:.0f}% line", weight=1.5))

    if timeframe in TREND_OFF:
        for e in ev:
            if e["name"] in TREND_ITEMS and e["weight"] > 0:
                e["weight"] = 0.0
                e["detail"] += " — trend reading switched off on this timeframe; the call comes from the measured score"

    noise = leg_atr is not None and leg_atr < MIN_LEG_ATR
    if noise:
        ev.append(_evidence(
            "significance", None,
            f"the whole swing spans {leg_atr:.1f} typical bars — less than the "
            f"{MIN_LEG_ATR:.0f} it takes to be a swing rather than noise"))

    prev_close = bars[-2]["close"] if len(bars) > 1 else None
    return {"price": round(price, 4), "atr": round(atr, 4), "true_atr": round(true_atr, 4),
            "thin": thin, "bars": len(bars), "asof": bars[-1]["time"],
            "prev_close": (round(prev_close, 4) if prev_close else None),
            "change": (round(price / prev_close - 1, 4)
                       if prev_close else None),
            "zones": zs, "near": near_z,
            "trendlines": [l for l in live],
            "moving_averages": {str(n): round(m["value"], 4) for n, m in mas.items()},
            "noise": noise, "leg_atr": (round(leg_atr, 2) if leg_atr else None),
            "leg_pos": (round(leg_pos, 3) if leg_pos is not None else None),
            "fib": fib, "cycle": cycle, "cloud": ({"top": cloud_top, "bottom": cloud_bot, "record": record}
                                  if cloud_top is not None else None),
            "sequence": seq, "at_level": at_level, "rsi": rsi,
            "volume_profile": ({"poc": vp["poc"], "value_area": vp["value_area"]} if vp else None),
            "channel_record": channel_rec,
            "evidence": ev, "bars": len(bars)}


# Timeframes whose confidence comes from the MEASURED score rather than from
# the hand-assigned evidence weights, and whose entries require the measured
# score to sit in the top fifth of the record.
#
# The weekly is the only timeframe on which anything orders outcomes, and the
# thing that does is the sum of each evidence item's measured residual —
# fitted on the replay, tested out of sample under three split dates
# (research/audits). The engine's own weekly confidence ordered outcomes
# backwards, and once the inverted Fibonacci entry was switched off the weekly
# had no entry rule at all. So on the weekly: confidence is which fifth of the
# record the measured score falls in, and a buy or add fires only from the
# top fifth, with the same support level under it as before. Decided
# 2026-09-03. The daily and monthly are unchanged.
MEASURED_CONFIDENCE = {"W"}
MEASURED_ENTRY_FIFTH = 5

# 2026-09-04: the confidence WORD is read off the past record on every
# timeframe. The user's rule — "if they work in the present then they should've
# worked in the past" — means a label is only high if calls in this fifth, on
# this timeframe, actually beat SPY more often than not in the replay. The
# fifth alone is not enough: out of sample the fifths were flat on the screen
# universe, so "top fifth" would have said high about a 45% hit rate. The
# record per fifth is stored by measure.save_record and carried on the call so
# the page can show the number the word came from.
# What the record showed on 2026-09-04 (measure.save_record, 21 days, whole
# record, in-sample): on every timeframe the share of calls that beat SPY is
# 44–51% in EVERY fifth, while the mean excess climbs with the fifth (daily
# +1.2% → +4.0%, weekly +1.2% → +5.0%, monthly +0.3% → +7.2%). The measured
# score does not pick more winners; it picks bigger ones. So the word is read
# off the mean, with a floor on the share so a fifth carried by a handful of
# outliers cannot read high.
RECORD_HIGH_MEAN = 0.03
RECORD_HIGH_SHARE = 0.45
RECORD_MEDIUM_MEAN = 0.015
RECORD_MIN_CALLS = 200
RECORD_MIN_DATES = 30


def measured_confidence(fifth: int | None, verdict: str | None = None,
                        record: dict | None = None) -> str | None:
    """A measured score is what calls with this evidence did NEXT. For a buy,
    add or hold the top fifth is the confident end; for a sell or a trim it is
    the bottom fifth — a name whose evidence was followed by underperformance
    is the one worth selling.

    With a `record` (measure.load_record for the timeframe) the word comes
    from what that fifth's calls actually did, in the call's own direction:
    high needs at least RECORD_HIGH of them to have beaten SPY (or lagged it,
    for a sell or trim) across enough calls and dates; medium needs a coin
    flip or better; anything else is low. Without a record, the fifth's rank
    is all there is, and a top fifth reads high as before."""
    if fifth is None:
        return None
    if record and record.get(fifth):
        r = record[fifth]
        p, m = r.get("up_share"), r.get("mean_excess")
        if p is None or m is None:
            return None
        if verdict in ("sell", "trim"):
            p, m = 1.0 - p, -m
        enough = (r.get("calls") or 0) >= RECORD_MIN_CALLS and (r.get("dates") or 0) >= RECORD_MIN_DATES
        if enough and m >= RECORD_HIGH_MEAN and p >= RECORD_HIGH_SHARE:
            return "high"
        if enough and m >= RECORD_MEDIUM_MEAN:
            return "medium"
        return "low"
    if verdict in ("sell", "trim"):
        fifth = 6 - fifth
    return "high" if fifth >= 5 else "medium" if fifth == 4 else "low"


def record_note(fifth: int | None, verdict: str | None, record: dict | None) -> dict | None:
    """The numbers behind the word, for the page."""
    if fifth is None or not record or not record.get(fifth):
        return None
    r = record[fifth]
    p, m = r.get("up_share"), r.get("mean_excess")
    if p is None or m is None:
        return None
    if verdict in ("sell", "trim"):
        p, m = 1.0 - p, -m
    side = "lagged" if verdict in ("sell", "trim") else "beat"
    return {"fifth": fifth, "share": round(p, 3), "calls": r.get("calls"), "dates": r.get("dates"),
            "mean_excess": round(m, 4),
            "text": (f"On the past record, calls with this evidence on this timeframe {side} SPY by "
                     f"{m*100:+.1f}% on average over 21 days and {side} it {p*100:.0f}% of the time — "
                     f"{r.get('calls'):,} replayed calls on {r.get('dates')} dates, fifth {fifth} of 5. "
                     f"In-sample: the weights were fitted on the same record.")}


# ---------------------------------------------------- Phase 2 candidates ----
# Evidence the engine did not have, each recorded at ZERO weight so the replay
# measures it on this book before it can move a call. Pure helpers, so each
# rule can be tested on a handful of bars.

def candle_pattern(prev: dict, last: dict) -> tuple[str, str] | None:
    """The single-bar and two-bar candlesticks worth naming AT a level: a
    hammer or a bullish engulfing bar (bull), a shooting star or a bearish
    engulfing bar (bear). A doji is noted as context. Nison's definitions,
    in their plainest form."""
    o, h, l, c = last["open"], last["high"], last["low"], last["close"]
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    upper, lower = h - max(o, c), min(o, c) - l
    po, pc = prev["open"], prev["close"]
    # A doji is a tiny body with wicks on BOTH sides; a tiny body with one long
    # wick is a hammer or a shooting star, and has to be tested first.
    if body <= 0.1 * rng and min(upper, lower) >= 0.25 * rng:
        return ("doji", "none")
    if lower >= 2 * body and upper <= max(body, 0.1 * rng):
        return ("hammer", "bull")
    if upper >= 2 * body and lower <= max(body, 0.1 * rng):
        return ("shooting star", "bear")
    if c > o and pc < po and c >= po and o <= pc and body > abs(pc - po):
        return ("bullish engulfing", "bull")
    if c < o and pc > po and c <= po and o >= pc and body > abs(pc - po):
        return ("bearish engulfing", "bear")
    return None


def volume_items(bars: list[dict], lookback: int = 10, heavy: float = 2.5) -> dict:
    """Three readings of volume. `heavy` is how many times the 20-bar average
    the last bar's volume has to be to count as a climax."""
    vols = [b.get("volume") or 0 for b in bars]
    out = {"heavy": False, "down_bar": None, "up_share": None, "obv_above": None, "ratio": None}
    if len(bars) < 25 or not any(vols[-20:]):
        return out
    avg20 = sum(vols[-21:-1]) / 20
    out["ratio"] = (vols[-1] / avg20) if avg20 else None
    out["heavy"] = bool(avg20 and vols[-1] >= heavy * avg20)
    out["down_bar"] = bars[-1]["close"] < bars[-1]["open"]
    ups = sum(v for b, v in zip(bars[-lookback:], vols[-lookback:]) if b["close"] >= b["open"])
    downs = sum(v for b, v in zip(bars[-lookback:], vols[-lookback:]) if b["close"] < b["open"])
    out["up_share"] = ups / (ups + downs) if (ups + downs) else None
    ob = I.obv(bars)
    if len(ob) > 20:
        avg = sum(r["value"] for r in ob[-20:]) / 20
        out["obv_above"] = ob[-1]["value"] > avg
    return out


def gap_item(bars: list[dict], lookback: int = 3, heavy: float = 2.0) -> dict | None:
    """A gap on volume within the last `lookback` bars, held into the close.

    The user's rule, stated 2026-09-03 after selling CRDO on its post-earnings
    gap: a gap down through the prior bar on heavy volume that closes below
    the gap is a change of character, not a dip; a gap up that holds is the
    same in the other direction. Recorded at zero weight until measured."""
    if len(bars) < 25:
        return None
    vols = [b.get("volume") or 0 for b in bars]
    for i in range(len(bars) - 1, max(len(bars) - 1 - lookback, 0), -1):
        avg20 = sum(vols[i - 20:i]) / 20 if i >= 20 else 0
        if not avg20 or vols[i] < heavy * avg20:
            continue
        b, prev = bars[i], bars[i - 1]
        ratio = vols[i] / avg20
        ago = len(bars) - 1 - i
        when = "today" if ago == 0 else f"{ago} bar{'s' if ago > 1 else ''} ago"
        if b["open"] < prev["low"] and b["close"] < prev["low"]:
            return {"stance": "bear",
                    "detail": f"gapped down {when} on {ratio:.1f}x average volume and closed below "
                              f"the gap — a change of character, not a dip"}
        if b["open"] > prev["high"] and b["close"] > prev["high"]:
            return {"stance": "bull",
                    "detail": f"gapped up {when} on {ratio:.1f}x average volume and held the gap"}
    return None


GANN_FRACTIONS = ((0.25, "1/4"), (1 / 3, "1/3"), (0.5, "1/2"), (2 / 3, "2/3"), (0.75, "3/4"))


def gann_level(fib: dict | None, price: float, atr: float):
    """Cantonese Cat's Gann fractions of the same swing leg the Fibonacci
    levels are drawn on: is price standing on a quarter, third or half of
    the leg? Returns (label, level, rising) or None."""
    if not fib or not atr:
        return None
    lo = min(fib["from"]["price"], fib["to"]["price"])
    hi = max(fib["from"]["price"], fib["to"]["price"])
    if hi <= lo:
        return None
    rising = fib["direction"] == "up"
    for frac, label in GANN_FRACTIONS:
        level = hi - frac * (hi - lo) if rising else lo + frac * (hi - lo)
        if abs(price - level) <= AT_LEVEL_ATR * atr:
            return (label, level, rising)
    return None


def double_pattern(pivots: list[dict], price: float, tolerance: float = 0.03,
                   min_gap: int = 8) -> dict | None:
    """A double bottom or top from the last two pivots of a kind: two lows
    within `tolerance` of each other, at least `min_gap` bars apart, with a
    high between them — confirmed when price is above that high. Mirrored
    for a top. Bulkowski's shapes, without his statistics yet."""
    lows = [p for p in pivots if p["kind"] == "low"]
    highs = [p for p in pivots if p["kind"] == "high"]
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        between = [h for h in highs if a["index"] < h["index"] < b["index"]]
        if (b["index"] - a["index"] >= min_gap and between
                and abs(a["price"] - b["price"]) <= tolerance * max(a["price"], b["price"])):
            neck = max(h["price"] for h in between)
            return {"kind": "double bottom", "neck": neck, "confirmed": price > neck,
                    "lows": (a["price"], b["price"])}
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        between = [l for l in lows if a["index"] < l["index"] < b["index"]]
        if (b["index"] - a["index"] >= min_gap and between
                and abs(a["price"] - b["price"]) <= tolerance * max(a["price"], b["price"])):
            neck = min(l["price"] for l in between)
            return {"kind": "double top", "neck": neck, "confirmed": price < neck,
                    "highs": (a["price"], b["price"])}
    return None


def role_flip_item(near_z: dict, price: float, atr: float) -> dict | None:
    """A level whose latest touch came from the other side than its earlier
    ones. Support that has become resistance is bearish while price is under
    it; resistance that has become support is bullish while price is over it.
    Only the level price is actually near counts."""
    for key in ("at", "support", "resistance"):
        z = near_z.get(key)
        if not z or not z.get("role_flipped"):
            continue
        edge = z["high"] if key == "support" else z["low"]
        if key != "at" and abs(price - edge) > AT_LEVEL_ATR * atr:
            continue
        if z["role"] == "resistance" and price <= z["high"]:
            return {"stance": "bear", "level": z["high"],
                    "detail": f"previous support is now resistance: {z['low']:,.2f}–{z['high']:,.2f} "
                              f"held price up {len(z['sequence']) - 1} time"
                              f"{'' if len(z['sequence']) == 2 else 's'} and has since turned "
                              f"it back from below (last {z['last']})"}
        if z["role"] == "support" and price >= z["low"]:
            return {"stance": "bull", "level": z["low"],
                    "detail": f"previous resistance is now support: {z['low']:,.2f}–{z['high']:,.2f} "
                              f"capped price {len(z['sequence']) - 1} time"
                              f"{'' if len(z['sequence']) == 2 else 's'} and has since held "
                              f"it from above (last {z['last']}) — the breakout-and-retest"}
    return None


def phase_item(pivots: list[dict], price: float, atr: float) -> dict | None:
    """Con's phase labels from the last few labelled pivots.

    Accumulation forming: the latest low is a higher low, the one before it a
    lower low, and the latest high is still a lower high — the first higher
    low inside a decline. Distribution forming is the mirror: a lower high
    after a higher high, with the latest low still a higher low. Markup and
    markdown are the pivot-sequence item's job and are not repeated here.

    Price has to still be INSIDE the range those two pivots bound. The pivots
    are the last ones found, and a straight run leaves none behind: ASST read
    "accumulation forming" between 10.96 and 12.97 with price at 26.82, and
    CRDO the same with price under the higher low. Out of the range the phase
    has resolved — up into markup, or down into a failed base."""
    lows = [p for p in pivots if p["kind"] == "low"]
    highs = [p for p in pivots if p["kind"] == "high"]
    if len(lows) < 2 or len(highs) < 2:
        return None
    tol = AT_LEVEL_ATR * (atr or 0.0)
    in_range = (lows[-1]["price"] - tol) <= price <= (highs[-1]["price"] + tol)
    if not in_range:
        return None
    if lows[-1]["label"] == "HL" and lows[-2]["label"] == "LL" and highs[-1]["label"] == "LH":
        return {"stance": "bull", "level": lows[-1]["price"],
                "detail": f"accumulation forming: a higher low ({lows[-1]['price']:,.2f}) after a "
                          f"lower low ({lows[-2]['price']:,.2f}), still under a lower high "
                          f"({highs[-1]['price']:,.2f}) — the range Con buys in"}
    if highs[-1]["label"] == "LH" and highs[-2]["label"] == "HH" and lows[-1]["label"] == "HL":
        return {"stance": "bear", "level": highs[-1]["price"],
                "detail": f"distribution forming: a lower high ({highs[-1]['price']:,.2f}) after a "
                          f"higher high ({highs[-2]['price']:,.2f}), still over a higher low "
                          f"({lows[-1]['price']:,.2f}) — the top of Con's cycle"}
    return None


def rsi_divergence(bars: list[dict], rsi_series: list[dict], lookback: int = 40,
                   min_gap: int = 3) -> dict | None:
    """Price and RSI disagreeing at the last two swing points of a kind.

    Bullish: the latest swing low in price is LOWER than the one before while
    RSI at those bars is HIGHER. Bearish is the mirror at swing highs. The two
    swings must be separate events (`min_gap` bars apart) — the methods
    module's version of this once compared adjacent bars of one descent."""
    if len(bars) < lookback + 2 or len(rsi_series) < lookback + 2:
        return None
    window = bars[-lookback:]
    rwin = {r["time"]: r["value"] for r in rsi_series[-lookback:]}
    pv = structure.pivots(window, 2, 2)
    lows = [p for p in pv if p["kind"] == "low"]
    highs = [p for p in pv if p["kind"] == "high"]
    if len(lows) >= 2 and lows[-1]["index"] - lows[-2]["index"] >= min_gap:
        a, b = lows[-2], lows[-1]
        ra, rb = rwin.get(a["time"]), rwin.get(b["time"])
        if ra is not None and rb is not None and b["price"] < a["price"] and rb > ra:
            return {"stance": "bull",
                    "detail": f"bullish divergence: price made a lower low ({a['price']:,.2f} → "
                              f"{b['price']:,.2f}) while RSI made a higher low ({ra:.0f} → {rb:.0f})"}
    if len(highs) >= 2 and highs[-1]["index"] - highs[-2]["index"] >= min_gap:
        a, b = highs[-2], highs[-1]
        ra, rb = rwin.get(a["time"]), rwin.get(b["time"])
        if ra is not None and rb is not None and b["price"] > a["price"] and rb < ra:
            return {"stance": "bear",
                    "detail": f"bearish divergence: price made a higher high ({a['price']:,.2f} → "
                              f"{b['price']:,.2f}) while RSI made a lower high ({ra:.0f} → {rb:.0f})"}
    return None


def floor_record(bars: list[dict], series: list[dict], floor: float,
                 horizon: int = 20) -> dict:
    """Each earlier time the oscillator crossed down to `floor`, and the best
    gain price then made within `horizon` bars. The current episode — the one
    still open — is not counted. RonnieV's SMH chart, made general."""
    by_time = {r["time"]: r["value"] for r in series}
    episodes, i, n = [], 0, len(bars)
    while i < n:
        v = by_time.get(bars[i]["time"])
        if v is None or v > floor:
            i += 1
            continue
        start = i
        while i < n and (by_time.get(bars[i]["time"]) is not None
                         and by_time[bars[i]["time"]] <= floor):
            i += 1
        end = i  # first bar back above the floor, or n
        if end >= n:
            break  # the open episode
        entry = bars[start]["close"]
        after = bars[start + 1:min(start + 1 + horizon, n)]
        if not after or entry <= 0:
            continue
        best = max(b["high"] for b in after)
        episodes.append({"time": bars[start]["time"], "price": round(entry, 4),
                         "gain_pct": round((best / entry - 1) * 100, 1)})
    gains = sorted(e["gain_pct"] for e in episodes)
    median = (gains[len(gains) // 2] if gains else None)
    return {"episodes": episodes, "horizon": horizon,
            "median_pct": median}


def thin_volume(profile: dict, price: float, band: float = 0.10,
                thin: float = 0.35) -> dict | None:
    """Where price sits against the volume-by-price profile.

    Above the point of control with the bins in the next `band` (10%) above
    price together holding less than `thin` of the point-of-control bin's
    volume: thin air overhead, a breakout has little in its way. Below the
    point of control with thin volume beneath: the same the other way."""
    if not profile:
        return None
    poc = profile["poc"]
    poc_vol = poc["share"]
    if poc_vol <= 0:
        return None
    above = [b for b in profile["bins"] if b["low"] >= price and b["low"] <= price * (1 + band)]
    below = [b for b in profile["bins"] if b["high"] <= price and b["high"] >= price * (1 - band)]
    if price > poc["high"] and above:
        share = sum(b["share"] for b in above) / poc_vol
        if share <= thin:
            return {"stance": "bull", "level": poc["price"],
                    "detail": f"above the heaviest volume node ({poc['low']:,.2f}–{poc['high']:,.2f}) "
                              f"with thin volume overhead — the next {band * 100:.0f}% up holds "
                              f"{share * 100:.0f}% of what traded at the node, so little stands in "
                              f"the way of a move"}
    if price < poc["low"] and below:
        share = sum(b["share"] for b in below) / poc_vol
        if share <= thin:
            return {"stance": "bear", "level": poc["price"],
                    "detail": f"below the heaviest volume node ({poc['low']:,.2f}–{poc['high']:,.2f}) "
                              f"with thin volume beneath — the next {band * 100:.0f}% down holds "
                              f"{share * 100:.0f}% of what traded at the node, so little would "
                              f"catch a fall"}
    if poc["low"] <= price <= poc["high"]:
        return {"stance": None, "level": poc["price"],
                "detail": f"inside the heaviest volume node ({poc['low']:,.2f}–{poc['high']:,.2f}), "
                          f"where most of the window's volume changed hands — a range, not a level"}
    return None


def channel_record_item(rec: dict, price: float, atr: float) -> dict | None:
    """Price at a channel edge, with what earlier touches of that edge did."""
    if not rec:
        return None
    near_floor = abs(price - rec["lower_now"]) <= AT_LEVEL_ATR * atr
    near_ceiling = abs(price - rec["upper_now"]) <= AT_LEVEL_ATR * atr
    if near_floor:
        done = [f for f in rec["floor"] if f["rally_pct"] is not None and not f["open"]]
        if not done:
            return {"name": "channel floor", "stance": "bull", "level": rec["lower_now"],
                    "detail": f"at the channel floor ({rec['lower_now']:,.2f}) with no completed "
                              f"earlier touch to compare against"}
        shown = ", ".join(f"{f['rally_pct']:+.0f}%" for f in done[-3:])
        return {"name": "channel floor", "stance": "bull", "level": rec["lower_now"],
                "detail": f"at the channel floor ({rec['lower_now']:,.2f}); the last {len(done[-3:])} "
                          f"touch{'es' if len(done[-3:]) > 1 else ''} rallied {shown} before the "
                          f"next touch — the measured-move case for buying the floor"}
    if near_ceiling:
        done = [c for c in rec["ceiling"] if c["fade_pct"] is not None and not c["open"]]
        if not done:
            return {"name": "channel ceiling", "stance": "extended", "level": rec["upper_now"],
                    "detail": f"at the channel ceiling ({rec['upper_now']:,.2f}) with no completed "
                              f"earlier touch to compare against"}
        shown = ", ".join(f"{c['fade_pct']:+.0f}%" for c in done[-3:])
        return {"name": "channel ceiling", "stance": "extended", "level": rec["upper_now"],
                "detail": f"at the channel ceiling ({rec['upper_now']:,.2f}); the last {len(done[-3:])} "
                          f"touch{'es' if len(done[-3:]) > 1 else ''} faded {shown} before the next "
                          f"touch — the place these charts trim, not chase"}
    return None


# ---------------------------------------------------- chart patterns ----
# The shapes on the "Top 8 Chart Patterns" graphic the user saved from X
# (research/charts-2026-09-03-x-accounts.md), detected from the pivots and
# trendlines structure.py already finds. The graphic's success rates are
# reported there and NOT used: every item below is at zero weight until the
# replay has measured it on this book, and the reference for a weight, when
# one is earned, is Bulkowski's measured statistics, not a hand-written
# percentage of unstated origin. Flags are not detected — a flag needs the
# pole measured as a separate impulse, and the pivot finder does not see one.

PATTERN_TOLERANCE = 0.05     # two shoulders, or three tops, within 5% of each other
PATTERN_STALE_ATR = 3.0      # a confirmed break more than this far gone is history


def head_shoulders(pivots: list[dict], price: float, atr: float,
                   tolerance: float = PATTERN_TOLERANCE) -> dict | None:
    """Head and shoulders from the last three highs (bear), or the inverted
    form from the last three lows (bull). The head is the middle extreme,
    the shoulders match within `tolerance`, and the neckline is the further
    of the two lows (or highs) between them. Confirmed on a close through the
    neckline; forming while price is still on the pattern's side of it."""
    highs = [p for p in pivots if p["kind"] == "high"]
    lows = [p for p in pivots if p["kind"] == "low"]

    def _build(three, between_kind, kind, bear):
        a, h, b = three
        if not (h["price"] > max(a["price"], b["price"]) if bear
                else h["price"] < min(a["price"], b["price"])):
            return None
        if abs(a["price"] - b["price"]) > tolerance * max(a["price"], b["price"]):
            return None
        between = [p for p in pivots if p["kind"] == between_kind
                   and a["index"] < p["index"] < b["index"]]
        if len(between) < 2:
            return None
        neck = (min(p["price"] for p in between) if bear
                else max(p["price"] for p in between))
        confirmed = price < neck if bear else price > neck
        gone = abs(price - neck) / atr if atr else 0.0
        if confirmed and gone > PATTERN_STALE_ATR:
            return None
        return {"kind": kind, "neck": round(neck, 4), "confirmed": confirmed,
                "head": h["price"], "shoulders": (a["price"], b["price"]),
                "stance": ("bear" if bear else "bull") if confirmed else None}

    if len(highs) >= 3:
        r = _build(highs[-3:], "low", "head and shoulders", True)
        if r:
            return r
    if len(lows) >= 3:
        r = _build(lows[-3:], "high", "inverted head and shoulders", False)
        if r:
            return r
    return None


# ---- cup and handle --------------------------------------------------------
# The base the user has had the most success with, and the one the engine did
# not detect. The rules are O'Neil's and Minervini's as commonly stated, made
# explicit so the study can vary them: a left rim at a swing high; a cup
# 12–50% deep over at least seven weeks and at most about fifteen months, with
# a rounded bottom rather than a spike; a right rim back within 5% of the left;
# then a handle — a pullback of 3–15% lasting one to five weeks whose low stays
# in the upper half of the cup — and a breakout: a close above the handle's
# high. Forming while price is inside the handle; confirmed on the close
# through; stale once price has run more than PATTERN_STALE_ATR past the pivot.
CUP_MIN_BARS, CUP_MAX_BARS = 30, 330
CUP_MIN_DEPTH, CUP_MAX_DEPTH = 0.12, 0.50
RIM_TOLERANCE = 0.05
HANDLE_MIN_BARS, HANDLE_MAX_BARS = 5, 25
HANDLE_MIN_DEPTH, HANDLE_MAX_DEPTH = 0.03, 0.15


def cup_handle(bars: list[dict], pivots: list[dict], price: float, atr: float) -> dict | None:
    """The most recent cup-and-handle base, forming or confirmed, or None."""
    n = len(bars)
    if n < CUP_MIN_BARS + HANDLE_MIN_BARS + 5:
        return None
    highs = [p for p in pivots if p["kind"] == "high"]
    if len(highs) < 2:
        return None
    closes = [b["close"] for b in bars]
    his = [b.get("high", b["close"]) for b in bars]
    los = [b.get("low", b["close"]) for b in bars]
    vols = [b.get("volume") or 0 for b in bars]
    best = None
    # Right rim candidates from the most recent pivot highs; the left rim is an
    # earlier pivot high within the allowed span that the right rim comes back to.
    for right in reversed(highs[-6:]):
        b_i = right["index"]
        if n - b_i > HANDLE_MAX_BARS + 60:
            break                               # too old to still be a live base
        lefts = [p for p in highs if CUP_MIN_BARS <= b_i - p["index"] <= CUP_MAX_BARS]
        for left in reversed(lefts):
            a_i = left["index"]
            rim = max(left["price"], right["price"])
            if abs(left["price"] - right["price"]) > RIM_TOLERANCE * rim:
                continue
            cup_lows = los[a_i:b_i + 1]
            low = min(cup_lows)
            depth = 1 - low / rim
            if not (CUP_MIN_DEPTH <= depth <= CUP_MAX_DEPTH):
                continue
            m_i = a_i + cup_lows.index(low)
            span = b_i - a_i
            # Rounded, not a V: the low sits in the middle 60% of the cup and the
            # bottom fifth of the depth holds at least a tenth of the bars.
            if not (a_i + 0.2 * span <= m_i <= a_i + 0.8 * span):
                continue
            # A rounded bowl spends about 30% of its bars in the bottom fifth
            # of its depth; a V spends 20%. The line is drawn between them.
            floor_band = low + 0.2 * (rim - low)
            if sum(1 for x in cup_lows if x <= floor_band) < max(3, int(0.25 * span)):
                continue
            # The handle: from the right rim onward, the pullback low and the
            # handle high (the pivot).
            handle = list(range(b_i + 1, n))
            if len(handle) < HANDLE_MIN_BARS:
                continue
            h_lows = los[b_i + 1:n]
            h_low = min(h_lows[:HANDLE_MAX_BARS]) if h_lows else None
            if h_low is None:
                continue
            h_low_i = b_i + 1 + h_lows[:HANDLE_MAX_BARS].index(h_low)
            h_depth = 1 - h_low / right["price"]
            if not (HANDLE_MIN_DEPTH <= h_depth <= HANDLE_MAX_DEPTH):
                continue
            if h_low < low + 0.5 * (rim - low):
                continue                        # handle fell into the lower half of the cup
            pivot = max(his[b_i:h_low_i + 1])   # the handle's high, from the right rim to its low
            # Where is price now relative to the pivot?
            after = closes[h_low_i + 1:]
            confirmed = bool(after) and price > pivot and max(after) > pivot
            if confirmed:
                first = next((i for i, c in enumerate(closes[h_low_i + 1:], h_low_i + 1) if c > pivot), None)
                if first is not None and n - 1 - first > 60:
                    continue                    # broke out long ago; history now
                if atr and (price - pivot) / atr > PATTERN_STALE_ATR:
                    continue
            elif n - 1 - h_low_i > HANDLE_MAX_BARS:
                continue                        # the handle has dragged on too long to be one
            v50 = sum(vols[max(0, n - 51):n - 1]) / max(1, min(50, n - 1))
            cand = {"kind": "cup and handle", "pivot": round(pivot, 4), "left_rim": round(left["price"], 4),
                    "right_rim": round(right["price"], 4), "low": round(low, 4), "depth": round(depth, 3),
                    "cup_bars": span, "handle_low": round(h_low, 4), "handle_depth": round(h_depth, 3),
                    "handle_bars": h_low_i - b_i, "confirmed": confirmed,
                    "volume_ratio": round(vols[-1] / v50, 2) if v50 else None,
                    "stance": "bull" if confirmed else None,
                    "left_time": left.get("time"), "right_time": right.get("time")}
            if best is None or b_i > best["_b"]:
                best = {**cand, "_b": b_i}
        if best:
            break
    if best:
        best.pop("_b", None)
    return best


def triple_pattern(pivots: list[dict], price: float, atr: float,
                   tolerance: float = PATTERN_TOLERANCE) -> dict | None:
    """Triple top (bear) or triple bottom (bull): the last three highs (lows)
    within `tolerance` of one another with two pullbacks between. The
    neckline is the lower of the two pullback lows (higher of the highs)."""
    for kind, want, between_kind, bear in (("triple top", "high", "low", True),
                                           ("triple bottom", "low", "high", False)):
        pts = [p for p in pivots if p["kind"] == want]
        if len(pts) < 3:
            continue
        a, b, c = pts[-3:]
        top = max(a["price"], b["price"], c["price"])
        if (top - min(a["price"], b["price"], c["price"])) > tolerance * top:
            continue
        between = [p for p in pivots if p["kind"] == between_kind
                   and a["index"] < p["index"] < c["index"]]
        if len(between) < 2:
            continue
        neck = (min(p["price"] for p in between) if bear
                else max(p["price"] for p in between))
        confirmed = price < neck if bear else price > neck
        if confirmed and atr and abs(price - neck) / atr > PATTERN_STALE_ATR:
            continue
        return {"kind": kind, "neck": round(neck, 4), "confirmed": confirmed,
                "levels": (a["price"], b["price"], c["price"]),
                "stance": ("bear" if bear else "bull") if confirmed else None}
    return None


def converging_lines(trendlines: list[dict], price: float, atr: float,
                     bars_index: dict | None = None, flat: float = 0.05) -> dict | None:
    """Triangles and wedges from one live support line and one live
    resistance line. Slopes are in typical bars per bar, so `flat` means the
    same thing on every name.

        rising support + flat resistance      ascending triangle   (bull)
        flat support + falling resistance     descending triangle  (bear)
        rising support + falling resistance   symmetrical triangle (none)
        both rising, support steeper          rising wedge         (bear)
        both falling, resistance steeper      falling wedge        (bull)

    Only while price is still between the lines: a pattern price has left is
    a breakout, and the trendline items already describe that."""
    if not atr:
        return None
    live = [l for l in trendlines if l.get("reaches_present") and not l.get("flipped_from")]
    sup = [l for l in live if l["side"] == "support"]
    res = [l for l in live if l["side"] == "resistance"]
    if not sup or not res:
        return None

    def _slope(l):
        a, b = l["from"], l["to"]
        span = (bars_index or {}).get(b["time"], 0) - (bars_index or {}).get(a["time"], 0)
        if span <= 0:
            return None
        return (b["price"] - a["price"]) / span / atr

    best = None
    for s_ in sup:
        for r_ in res:
            lo, hi = s_["to"]["price"], r_["to"]["price"]
            if not (lo < price < hi) or hi - lo <= 0:
                continue
            ms, mr = _slope(s_), _slope(r_)
            if ms is None or mr is None:
                continue
            s_flat, r_flat = abs(ms) <= flat, abs(mr) <= flat
            if ms > flat and r_flat:
                kind, stance = "ascending triangle", "bull"
            elif s_flat and mr < -flat:
                kind, stance = "descending triangle", "bear"
            elif ms > flat and mr < -flat:
                kind, stance = "symmetrical triangle", None
            elif ms > flat and mr > flat and ms > mr:
                kind, stance = "rising wedge", "bear"
            elif ms < -flat and mr < -flat and mr < ms:
                kind, stance = "falling wedge", "bull"
            else:
                continue
            width = (hi - lo) / atr
            if best is None or width < best["width_atr"]:
                best = {"kind": kind, "stance": stance, "lower": round(lo, 4),
                        "upper": round(hi, 4), "width_atr": round(width, 2),
                        "support_slope": round(ms, 3), "resistance_slope": round(mr, 3)}
    return best


def decide(g: dict, position: dict | None = None) -> dict:
    """Turn gathered evidence into one call, with the level that would flip it."""
    if g.get("insufficient"):
        return {"verdict": "hold", "confidence": "none",
                "because": [f"only {g.get('bars', 0)} bars of history — "
                            f"not enough to read structure from"],
                "against": [], "flip": None, "flip_note": None}

    # Structure that is indistinguishable from noise does not get to become a
    # directional call. It degrades to hold WITH the reason, rather than being
    # dropped silently, so the screen says why it is quiet on that name.
    if g.get("noise"):
        return {"verdict": "hold", "confidence": "none",
                "because": [e["detail"] for e in g["evidence"]
                            if e["name"] == "significance"]
                + ["no directional call is made on a series this quiet"],
                "against": [], "flip": None, "flip_note": None}

    ev = g["evidence"]
    price, atr = g["price"], g["atr"]
    bull = sum(e["weight"] for e in ev if e["stance"] == "bull")
    bear = sum(e["weight"] for e in ev if e["stance"] == "bear")
    extended = sum(e["weight"] for e in ev if e["stance"] == "extended")
    leg = g.get("leg_pos")
    held = bool(position and (position.get("quantity") or 0) > 0)

    say = lambda e: e["detail"]
    # Only evidence that was actually SCORED becomes a reason. Items carried at
    # zero weight for the replay to measure are context in the tally, and
    # listing them as reasons would explain a call by things that did not
    # contribute to it.
    reasons = lambda stances: [say(e) for e in ev if e["stance"] in stances and e["weight"] > 0]
    # What argues the OTHER way. A verdict that lists only its confirming
    # evidence is advocacy, not analysis — DGXX read "add" while sitting below
    # all three moving averages and the reason list never mentioned it. The
    # dissent is carried on the verdict itself so it cannot be dropped by a
    # caller that only renders `because`.
    against = lambda stances: [say(e) for e in ev if e["stance"] in stances and e["weight"] > 0]

    # ---- trim: upside only, and only on something already owned -----------
    # Gated on leg position so this can never fire on a position that has come
    # down. See the module docstring for why that gate is the whole point.
    # Rules are proportional, not absolute. They were first written as fixed
    # sums (bear >= 3.0 and bull < 1.5) against about five pieces of evidence.
    # Adding levels, trendlines, channels and moving averages roughly doubled
    # that, so incidental weight on the losing side crossed the fixed ceiling
    # and every strong reading collapsed to hold — IREN went from SELL on 2.0
    # against 6.5. A share of the total says the same thing at any evidence
    # count, and does not need retuning the next time something is added.
    total = bull + bear
    bull_share = bull / total if total else 0.0
    bear_share = bear / total if total else 0.0

    # The arithmetic, itemised. "4.5 bullish against 4.0 bearish" is a number
    # with no way to check it — asked what it meant, there was nowhere to look.
    # Every scoring item is listed with what it contributed, and the items
    # carrying zero are named as counted-but-not-scored rather than hidden, so
    # the totals visibly add up.
    tally = {
        "bull": round(bull, 2), "bear": round(bear, 2),
        "extended": round(extended, 2),
        "bull_share": round(bull_share, 3),
        "items": [{"name": e["name"], "stance": e["stance"],
                   "weight": e["weight"], "detail": e["detail"]}
                  for e in ev if e["weight"] > 0 and e["stance"]],
        "context": [{"name": e["name"], "detail": e["detail"]}
                    for e in ev if not e["stance"] or e["weight"] == 0],
        "explain": (
            f"Each piece of evidence carries a weight — 1.5 for the structural "
            f"ones (pivots, the cloud, a level price is standing on), 1.0 for "
            f"ordinary ones, 0.5 for weak ones. Bullish weights sum to "
            f"{bull:.1f} and bearish to {bear:.1f}, so the evidence is "
            f"{bull_share * 100:.0f}% bullish. A call needs 65% of the weight on "
            f"one side and at least 3.0 of it; anything less is a hold."),
    }

    if held and extended >= 1.5 and (leg is None or leg >= UPPER_LEG) and bear_share < 0.5:
        flip, note = _next_upside(g)
        # `because` is the extension evidence alone. The bullish evidence is
        # the case AGAINST trimming — it is why the position is worth holding —
        # and listing it on both sides read as the engine arguing with itself.
        return {"verdict": "trim", "tally": tally,
                "confidence": _confidence(extended, bear),
                "because": reasons({"extended"}),
                "against": against({"bull"})[:3],
                "flip": flip, "flip_note": note}

    # ---- a measured timeframe with its trend items off: the record decides ---
    if g.get("timeframe") in TREND_OFF and g.get("measured_fifth") is not None:
        fifth = g["measured_fifth"]
        support = _support(g)
        conf = measured_confidence(fifth, "buy" if fifth >= 4 else "sell" if fifth <= 2 else "hold")
        why_m = [f"measured: calls carrying this evidence sit in fifth {fifth} of 5 of the replayed "
                 f"record ({g.get('measured_score', 0) or 0:+.2f} points against the same-day average)"]
        if fifth >= MEASURED_ENTRY_FIFTH and support is not None:
            call = "add" if held else "buy"
            return {"verdict": call, "tally": tally, "confidence": conf,
                    "because": why_m + reasons({"bull"}),
                    "against": against({"bear"}),
                    "flip": round(support, 4),
                    "flip_note": f"a close below {support:,.2f} breaks the structure this rests on"}
        if fifth <= 1:
            if position and position.get("book") == "conviction":
                return {"verdict": "hold", "tally": tally, "confidence": conf,
                        "because": ["conviction book: the record reads against this name, which on this "
                                    "book is an accumulation zone rather than an exit"] + why_m,
                        "against": against({"bull"}), "flip": None, "flip_note": None,
                        "book": "conviction"}
            cloud = (g.get("cloud") or {}).get("bottom")
            flip = cloud if cloud and cloud > price else None
            return {"verdict": "sell", "tally": tally, "confidence": conf,
                    "because": why_m + reasons({"bear"}),
                    "against": against({"bull"}),
                    "flip": round(flip, 4) if flip else None,
                    "flip_note": (f"a close back above {flip:,.2f} puts price into the cloud and ends "
                                  f"the case for selling" if flip else None)}
        return {"verdict": "hold", "tally": tally, "confidence": conf,
                "because": why_m + (["no level below price is close enough to be a stop, so no entry"]
                                    if fifth >= MEASURED_ENTRY_FIFTH else []),
                "against": [], "flip": None, "flip_note": None}

    # ---- sell: trend broken, and a reclaim level to name ------------------
    if bear >= 3.0 and bear_share >= 0.65:
        cloud = (g.get("cloud") or {}).get("bottom")
        flip = cloud if cloud and cloud > price else None
        note = (f"a close back above {flip:,.2f} puts price into the cloud and "
                f"ends the case for selling" if flip else None)
        # The conviction book never gets a sell. The same evidence is real and
        # is listed, but on a name held on a thesis a broken trend is where
        # the schedule buys more, not where the position ends. See books.py.
        if position and position.get("book") == "conviction":
            return {"verdict": "hold", "tally": tally,
                    "confidence": _confidence(bear, bull),
                    "because": ["conviction book: the trend is broken, which on this "
                                "book is an accumulation zone rather than an exit — "
                                "no sell call is made on a name held on a thesis"]
                    + reasons({"bear"}),
                    "against": against({"bull"}),
                    "flip": round(flip, 4) if flip else None,
                    "flip_note": (f"a close back above {flip:,.2f} puts price into the "
                                  f"cloud and the trend is no longer broken" if flip else None),
                    "book": "conviction"}
        if flip is None:
            return {"verdict": "hold", "confidence": "low",
                    "because": reasons({"bear"}) +
                    ["downgraded from sell: no level above price would flip the "
                     "call, and a verdict that cannot be invalidated is not one"],
                    "against": against({"bull"}), "tally": tally,
                    "flip": None, "flip_note": None}
        return {"verdict": "sell", "tally": tally,
                "confidence": _confidence(bear, bull),
                "because": reasons({"bear"}), "against": against({"bull"}),
                "flip": round(flip, 4), "flip_note": note}

    measured_tf = g.get("measured_fifth") is not None and g.get("timeframe") in MEASURED_CONFIDENCE

    # ---- buy / add: trend intact and price at a level worth acting on -----
    if bull >= 3.0 and bull_share >= 0.65:
        at = g.get("at_level")
        support = _support(g)
        strong = at and at["kind"] == "retracement" and (leg is None or leg <= 0.8)
        if measured_tf:
            # On a measured timeframe the entry is earned by the record, not
            # by standing on a textbook level.
            strong = g["measured_fifth"] >= MEASURED_ENTRY_FIFTH
        if support is None:
            return {"verdict": "hold", "confidence": "low",
                    "because": reasons({"bull"}) +
                    ["downgraded from buy: nothing below price is close enough to "
                     "act as a stop, so the idea has no invalidation"],
                    "against": against({"bear"}), "tally": tally,
                    "flip": None, "flip_note": None}
        call = "buy" if (strong and not held) else "add" if strong else "hold"
        why = reasons({"bull"})
        if call == "hold":
            # First, not appended. The CLI and the change log both truncate the
            # reason list, and "why is a strongly trending name only a hold" is
            # the one line that has to survive that cut — without it a high
            # confidence hold reads as the engine hedging.
            why.insert(0, "trend is intact, but price is not at a level worth "
                          "adding at — a hold rather than a chase")
        return {"verdict": call, "tally": tally,
                "confidence": _confidence(bull, bear),
                "because": why,
                "against": against({"bear"}),
                "flip": round(support, 4),
                "flip_note": f"a close below {support:,.2f} breaks the structure this "
                             f"rests on"}

    # ---- hold: say there is nothing to do, not how close it came ----------
    # This led with "the evidence is 53% bullish (4.0 against 3.5), short of
    # the 65% a call needs" on eleven of thirteen holdings. The user: "seems
    # like all readings are wishy washy and say like 51% bullish. That doesn't
    # give me anything useful." A share near the middle is the engine reporting
    # it has nothing, formatted as a finding. So the hold says the one true
    # thing and hands over to the levels. The arithmetic stays on `tally` for
    # anyone who opens it; it no longer masquerades as the headline.
    return {"verdict": "hold", "confidence": "low", "tally": tally,
            "because": ["nothing to do at this price — the evidence is split "
                        "and no side carries it. The levels below are the plan: "
                        "wait for one of them."]
            + reasons({"bull", "bear", "extended"})[:2],
            "against": [], "flip": None, "flip_note": None}


def _confidence(for_: float, against: float) -> str:
    """How lopsided the evidence is, as a share rather than a difference.

    A raw difference rewards volume: ten agreeing items on a quiet name would
    outrank a clean six-to-one, which is backwards.
    """
    total = for_ + against
    if total <= 0:
        return "low"
    share = for_ / total
    return "high" if share >= 0.85 else "medium" if share >= 0.7 else "low"


def _support(g: dict):
    """The nearest level BELOW price that something is actually anchored to."""
    price = g["price"]
    cands = []
    cloud = (g.get("cloud") or {}).get("top")
    if cloud and cloud < price:
        cands.append(cloud)
    for e in g["evidence"]:
        if e["name"] == "pivot sequence" and e["level"] and e["level"] < price:
            cands.append(e["level"])
    fib = g.get("fib")
    if fib:
        below = [l["price"] for l in fib["levels"] if l["price"] < price]
        if below:
            cands.append(max(below))
    return max(cands) if cands else None


def _next_upside(g: dict):
    """The level a trim is being taken into, or the one above it."""
    price, fib, atr = g["price"], g.get("fib"), g["atr"]
    if fib:
        # Strictly above, and far enough above to be a different level. The
        # level a trim is being taken AT is not also the thing being given up
        # by trimming, and reporting it as both read as a contradiction.
        # The 1.272 and 1.414 extension targets are candidates too: they are
        # where the charts the user follows take the first trim, and a trim
        # gives up the NEAREST level above, not the nearest of the old list.
        # Only in a rising leg — in a falling one the "targets" are below.
        cands = list(fib["levels"])
        if fib.get("direction") == "up":
            cands += [{"ratio": t["ratio"], "price": t["price"], "kind": "target"}
                      for t in fib.get("targets", [])
                      if t["ratio"] not in {l["ratio"] for l in fib["levels"]}]
        above = [l for l in cands
                 if l["price"] > price + AT_LEVEL_ATR * atr]
        if above:
            nxt = min(above, key=lambda l: l["price"])
            return round(nxt["price"], 4), (
                f"still {(nxt['price'] / price - 1) * 100:.1f}% to the "
                f"{nxt['ratio']:.3f} {nxt['kind']} at {nxt['price']:,.2f} — "
                f"trimming here gives that up")
    return None, ("no further level above price is defined, which is itself a "
                  "reason not to trim the whole position here")


def for_symbol(bars_daily: list[dict], timeframe: str = "D",
               position: dict | None = None, market: dict | None = None,
               measured: dict | None = None, context: dict | None = None,
               confirm: int = 1) -> dict:
    """The whole answer for one symbol on one timeframe.

    `measured` is the profile from measure.load_profile for this timeframe —
    the measured weight of every evidence item and where the fifths of the
    record fall. With it, the call carries a measured score and fifth, and on
    a measured timeframe its confidence and entry come from them.
    """
    bars = I.resample(bars_daily, timeframe) if timeframe != "D" else bars_daily
    g = gather(bars, position, market, timeframe, context)
    g["timeframe"] = timeframe
    # Confirmation. The user asked whether a level counts on one close through
    # it or two. With confirm=2 an evidence item votes only if it read the same
    # way on the previous bar as well — a break that has held for two closes,
    # a cloud position that has held for two closes. Items that read
    # differently a bar ago stay on the list at weight zero, marked, so the
    # replay can measure the gate against the one-close engine.
    if confirm and confirm >= 2 and not g.get("insufficient") and len(bars) > MIN_BARS.get(timeframe, 60):
        prev = gather(bars[:-1], position, market, timeframe, context)
        seen = {(e["name"], e.get("stance")) for e in prev.get("evidence", []) if e.get("stance")}
        for e in g.get("evidence", []):
            if e.get("stance") and (e["name"], e["stance"]) not in seen and (e.get("weight") or 0) > 0:
                e["weight"] = 0.0
                e["unconfirmed"] = True
                e["detail"] = (e.get("detail") or "") + " — unconfirmed: read differently one bar ago"
        g["confirm"] = confirm
    g["measured_score"] = g["measured_fifth"] = None
    if measured and measured.get("weights") and not g.get("insufficient"):
        from . import measure
        g["measured_score"] = measure.measured_score(g.get("evidence"), measured["weights"])
        g["measured_fifth"] = measure.fifth_of(g["measured_score"], measured.get("cuts"))
    d = decide(g, position)
    record = (measured or {}).get("record") or None
    # The word is read off the record on EVERY timeframe that has one; the
    # weekly's entry rule (top fifth only) is unchanged.
    if (timeframe in MEASURED_CONFIDENCE or record) and g.get("measured_fifth") is not None \
            and d.get("verdict") not in (None,) and d.get("confidence") != "none":
        mc = measured_confidence(g["measured_fifth"], d.get("verdict"), record)
        d["confidence_engine"] = d.get("confidence")
        d["confidence"] = mc
        d["record"] = record_note(g["measured_fifth"], d.get("verdict"), record)
        d["confidence_note"] = (d["record"]["text"] if d.get("record") else
                                f"measured: calls with this evidence sit in fifth "
                                f"{g['measured_fifth']} of 5 of the record "
                                f"({g['measured_score']:+.2f} points against the same-day average)")
    # A thin monthly — two years of bars but not three — is read, and it leads
    # the headline as any monthly does, but its confidence is capped at low:
    # a 20-month average and a 26-month Kijun on 28 bars are mostly warm-up.
    if g.get("thin") and d.get("confidence") in ("high", "medium"):
        d["confidence_before_thin"] = d["confidence"]
        d["confidence"] = "low"
        d["thin_note"] = (f"{g.get('bars')} {timeframe}-bars of history; the full read "
                          f"needs {FULL_BARS.get(timeframe, 60)}, so confidence is capped at low")
    # The market against the setup: a buy or add loses one notch of
    # confidence while the S&P's weekly reads sell. A mark-down, not a veto.
    ix = (context or {}).get("index")
    if INDEX_GATE and ix and ix.get("state") == "against" and d.get("verdict") in ("buy", "add") \
            and d.get("confidence") in ("high", "medium"):
        d["confidence_before_market"] = d["confidence"]
        d["confidence"] = {"high": "medium", "medium": "low"}[d["confidence"]]
        d["against"] = list(d.get("against") or []) + [
            f"the market is against it — {ix.get('summary', '')}; confidence marked down one notch"]
        d["market_against"] = True
    return {**d, "timeframe": timeframe, "price": g.get("price"),
            "measured_score": g.get("measured_score"), "measured_fifth": g.get("measured_fifth"),
            "watch": watch_levels(g, d, position),
            "tally": d.get("tally"),
            "change": g.get("change"), "near": g.get("near"),
            "zones": g.get("zones"), "trendlines": g.get("trendlines"),
            "moving_averages": g.get("moving_averages"),
            "asof": g.get("asof"), "leg_pos": g.get("leg_pos"),
            "cloud": g.get("cloud"),
            "sequence": g.get("sequence"), "rsi": g.get("rsi"),
            "evidence": g.get("evidence", []),
            "thin": bool(g.get("thin")), "bars": g.get("bars"),
            "first": (bars[0]["time"] if bars else None),
            "needed": MIN_BARS.get(timeframe, 60),
            "insufficient": bool(g.get("insufficient"))}


def quality(both: dict) -> dict:
    """What separates two calls that say the same word.

    A screen full of "add" ranks by nothing on its own, and the honest
    discriminator is not conviction — it is the shape of the trade. Three
    things, each reported rather than folded into an opaque number:

    `reward_risk` — how far it is to the next level above against how far to the
    price that would prove the idea wrong. Both come from levels price has
    already turned at, so neither is a forecast. Two adds at 2.5:1 and 0.6:1 are
    not the same trade, and this is the difference nothing else here was showing.

    `distance` — how far price is from the level worth acting at, as a percent.
    An add sitting ON its level is a different proposition from one eight
    percent above it, and paying up is how a good level becomes a bad entry.

    `agreement` — how many of the three timeframes say the same thing. One
    timeframe agreeing with itself is not evidence.

    The composite exists to sort a list and is deliberately crude: reward/risk
    dominates, agreement and closeness adjust it. Anything that would need
    tuning to look right is left out, because a ranking nobody can check is
    worse than an unranked list.
    """
    head = both.get("headline")
    tf = both.get("headline_timeframe", "D")
    r = both.get({"D": "daily", "W": "weekly", "M": "monthly"}[tf], {})
    w = r.get("watch") or {}
    price = w.get("price")
    read = [both[k] for k in ("daily", "weekly", "monthly")
            if both.get(k) and not both[k].get("insufficient")]
    same = sum(1 for x in read if x.get("verdict") == head)

    # Measured between the nearest ZONES either side, not between a Fibonacci
    # extension and a stop. A zone is a price the market has actually turned at
    # more than once and is recent by construction; an extension is arithmetic
    # off a swing and can sit three times the share price away, which made the
    # ratio look magnificent and mean nothing.
    near = r.get("near") or {}
    res = (near.get("resistance") or {}).get("low")
    sup = (near.get("support") or {}).get("high")
    basis = "resistance the market has turned at before"
    if not res:
        # Nothing overhead is not missing data — it is a name trading above
        # every level it has, which is usually WHY it reads as an add. The
        # projected target is the honest fallback, and the basis is reported
        # because a ratio measured to a projection deserves less trust than one
        # measured to a price the market has already refused.
        res = w.get("trim_at")
        basis = "a projected target, since price is above every level it has"
    reward = (res - price) if (res and price and res > price) else None
    risk = (price - sup) if (sup and price and price > sup) else None
    rr = round(reward / risk, 2) if (reward and risk and risk > 0) else None

    entry = w.get("buy_at") if head in ("buy", "add") else None
    dist = (round(abs(price / entry - 1) * 100, 1)
            if (entry and price) else None)

    tally = r.get("tally") or {}
    share = tally.get("bull_share")

    score = None
    if rr is not None:
        score = rr
        score *= 1 + 0.15 * (same - 1)          # agreement nudges, never decides
        if dist is not None:
            score *= max(0.5, 1 - dist / 40.0)  # paying up is a real cost
        score = round(score, 2)

    return {
        "score": score, "reward_risk": rr, "reward_basis": basis if rr else None,
        "agreement": same,
        "timeframes_read": len(read), "distance_pct": dist,
        "bull_share": share,
        "reward": round(reward, 2) if reward else None,
        "risk": round(risk, 2) if risk else None,
        "why": (
            f"{rr:.1f} to 1 reward against risk, measured to {basis}"
            + (f", price {dist:.1f}% from the level worth acting at" if dist is not None else "")
            + f", {same} of {len(read)} timeframes agreeing"
            if rr is not None else
            "no ranking: this call has no level above and below price to measure "
            "a reward against a risk, which is itself a reason to prefer one that has"),
    }


def both_timeframes(bars_daily: list[dict], position: dict | None = None,
                    market: dict | None = None, measured: dict | None = None,
                    context: dict | None = None, confirm: int = 1) -> dict:
    """Daily, weekly and monthly, kept separate and ordered longest first.

    They are reported side by side rather than blended, because the
    disagreement between them is information: a daily buy inside a weekly
    downtrend is a bounce to trade, and inside a weekly uptrend it is an entry.
    Averaging them would erase exactly that.

    The HEADLINE is the longest timeframe that could be read, not the daily one.
    Daily led for no better reason than being computed first, which is the wrong
    emphasis for anyone holding for weeks or months — and it is why a name could
    show a stale daily "sell" beside a weekly "add" and read as a contradiction.
    """
    measured = measured or {}
    # The gate is passed only when it is on, so callers and test doubles that
    # know the six-argument signature keep working.
    extra = {"confirm": confirm} if confirm and confirm > 1 else {}
    d = for_symbol(bars_daily, "D", position, market, measured.get("D"), context, **extra)
    w = for_symbol(bars_daily, "W", position, market, measured.get("W"), context, **extra)
    m = for_symbol(bars_daily, "M", position, market, measured.get("M"), context, **extra)

    read = [(tf, r) for tf, r in (("M", m), ("W", w), ("D", d))
            if not r.get("insufficient")]
    headline_tf, headline = (read[0] if read else ("D", d))
    # A weekly SELL at high confidence is not hidden behind a monthly add or
    # hold: the monthly has too few replayed calls to be measured, the weekly
    # sell is the measured bottom fifth, and the user's own charts sided with
    # the weekly the day this came up (CRDO, 2026-09-03).
    if (headline_tf == "M" and not w.get("insufficient") and w.get("verdict") == "sell"
            and w.get("confidence") == "high" and headline.get("verdict") != "sell"):
        headline_tf, headline = "W", w

    # Only compare timeframes that were actually read. A "conflict" against a
    # timeframe with too little history is not a conflict.
    calls = {tf: r["verdict"] for tf, r in read}
    agree = len(set(calls.values())) <= 1
    names = {"D": "daily", "W": "weekly", "M": "monthly"}
    conflict = None
    if not agree:
        parts = ", ".join(f"{names[tf]} says {c}" for tf, c in calls.items())
        conflict = (f"{parts} — the longer timeframe is the one that decides "
                    f"whether this is a position or a trade")
    out = {"daily": d, "weekly": w, "monthly": m,
           "agree": agree, "headline": headline["verdict"],
           "headline_timeframe": headline_tf,
           "headline_confidence": headline["confidence"],
           "conflict": conflict}
    out["quality"] = quality(out)
    return out
