"""Intermarket signals, the Keltner/quarterly additions, and support exhaustion.

The point of most of these is not that the arithmetic works — it is that a
signal built on six years of proxy ETF data does not quietly present itself as
evidence for a claim about multiple market cycles.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import indicators as I, intermarket, methods, setups


def _bars(n=400, start=100.0, step=0.5):
    out, price = [], start
    for i in range(n):
        y, doy = 2020 + i // 250, i % 250
        m, d = doy // 21 + 1, doy % 21 + 1
        price += step
        out.append({"time": f"{y}-{min(m,12):02d}-{d:02d}", "open": price - 0.2,
                    "high": price + 1, "low": price - 1, "close": price, "volume": 1000})
    return out


def test_quarterly_resample_buckets_by_three_months():
    bars = [{"time": f"2026-{m:02d}-{d:02d}", "open": 1.0, "high": 2.0,
             "low": 0.5, "close": 1.5, "volume": 10}
            for m in range(1, 13) for d in (1, 15)]
    out = I.resample(bars, "Q")
    assert len(out) == 4, "a full year is four quarters"
    # Each quarter is dated by its last session, matching the weekly/monthly rule.
    assert [b["time"] for b in out] == ["2026-03-15", "2026-06-15",
                                        "2026-09-15", "2026-12-15"]


def test_keltner_bands_straddle_the_ema():
    bars = _bars()
    k = I.keltner(bars, 20, 2.0, 10)
    assert k["upper"] and k["lower"] and k["middle"]
    for up, mid, lo in zip(k["upper"], k["middle"], k["lower"]):
        assert lo["value"] < mid["value"] < up["value"]
        assert up["time"] == mid["time"] == lo["time"]


def test_keltner_differs_from_bollinger():
    # They look alike and are routinely confused; one measures true range and the
    # other the dispersion of closes, so on gappy data they must not coincide.
    bars = _bars()
    for i in range(50, 60):
        bars[i]["high"] += 15          # a gap widens true range, not close dispersion
        bars[i]["low"] -= 15
    k = I.keltner(bars, 20, 2.0, 10)
    b = I.bollinger(bars, 20, 2.0)
    kw = k["upper"][-1]["value"] - k["lower"][-1]["value"]
    bw = b["upper"][-1]["value"] - b["lower"][-1]["value"]
    assert abs(kw - bw) > 1e-6


def test_keltner_is_registered_with_adjustable_params():
    assert "keltner" in I.REGISTRY
    names = [p[0] for p in I.REGISTRY["keltner"]["params"]]
    assert names == ["period", "mult", "atr_period"]
    assert I.parse("keltner:20:2.5:10") == ("keltner", [20.0, 2.5, 10.0])


def test_ratio_bars_only_use_common_sessions():
    class FakeConn:
        pass

    calls = {}

    def fake_load(conn, sym, start, end):
        calls[sym] = True
        if sym == "AAA":
            return [{"time": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10},
                    {"time": "2026-01-02", "open": 12, "high": 13, "low": 11, "close": 12}]
        return [{"time": "2026-01-02", "open": 2, "high": 2, "low": 2, "close": 2},
                {"time": "2026-01-03", "open": 4, "high": 4, "low": 4, "close": 4}]

    original = intermarket.prices.load_bars
    intermarket.prices.load_bars = fake_load
    try:
        out = intermarket.ratio_bars(FakeConn(), "AAA", "BBB", "2026-01-01", "2026-01-03")
    finally:
        intermarket.prices.load_bars = original
    assert len(out) == 1 and out[0]["time"] == "2026-01-02"
    assert out[0]["close"] == 6.0


def test_signal_reports_too_few_crosses_rather_than_a_hit_rate():
    spec = intermarket.SIGNALS["copper-gold-macd"]
    text = " ".join(spec["caveats"]).lower()
    assert "does not" in text or "too few" in text
    # His own public doubt has to travel with the claim, not be filtered out.
    assert any("stops working" in q for q in spec["quotes"])


def test_window_arithmetic_rolls_the_year():
    assert intermarket._add_months("2026-05-29", 6) == "2026-11"
    assert intermarket._add_months("2026-05-29", 12) == "2027-05"
    assert intermarket._add_months("2026-12-31", 1) == "2027-01"


def _trend_bars(dip_every):
    """A rising series whose low sits clear of its own average between tests.

    This shape matters: a bar closing ON its moving average necessarily has its
    low below it, so a flat series makes every bar look like a touch and nothing
    can be distinguished. Only when price trades clear of the average is a
    genuine test of it identifiable.
    """
    out = []
    for i in range(80):
        close = 100 + 2 * i
        low = close - 24 if (dip_every and i % dip_every == 0) else close - 3
        out.append({"time": f"2026-{i//21+1:02d}-{i%21+1:02d}", "open": close,
                    "high": close + 1, "low": low, "close": close, "volume": 100})
    return out


def test_support_exhaustion_counts_distinct_tests():
    fn = methods.CONDITIONS["ma_support_exhausted"]
    ok, touches, why = fn(_trend_bars(5), {})
    assert ok is True and touches == 4, (ok, touches)
    assert "weakening" in why


def test_support_exhaustion_is_false_when_the_average_is_never_tested():
    fn = methods.CONDITIONS["ma_support_exhausted"]
    ok, touches, _ = fn(_trend_bars(0), {})
    assert ok is False and touches == 0, (ok, touches)


def test_one_long_lean_is_one_touch_not_one_per_bar():
    """The regression this exists for.

    A run of consecutive bars inside the band is ONE test of the level. Counting
    per bar reported 22 touches for a name that never pulled back once, and
    diagnose then warned that its support was about to give way.
    """
    fn = methods.CONDITIONS["ma_support_exhausted"]
    bars = []
    for i in range(80):
        close = 100 + 2 * i
        low = close - 24 if i >= 58 else close - 3
        bars.append({"time": f"2026-{i//21+1:02d}-{i%21+1:02d}", "open": close,
                     "high": close + 1, "low": low, "close": close, "volume": 100})
    ok, touches, _ = fn(bars, {})
    assert touches == 1, f"a single unbroken lean counted as {touches} tests"
    assert ok is False


def test_support_tolerance_scales_with_volatility_not_price():
    """Two percent of a hundred-dollar stock is wider than a week of trading.

    A fixed percentage made every bar of a quiet name count as a touch, which is
    the same defect already corrected in structure.py.
    """
    fn = methods.CONDITIONS["ma_support_exhausted"]
    quiet = [{"time": f"2026-{i//21+1:02d}-{i%21+1:02d}", "open": 100 + i * 0.1,
              "high": 100.5 + i * 0.1, "low": 99.9 + i * 0.1,
              "close": 100 + i * 0.1, "volume": 1} for i in range(60)]
    ok, touches, _ = fn(quiet, {})
    assert touches == 0, f"a quiet drift that never pulled back scored {touches}"


def test_new_setups_are_attributed_and_quoted():
    cat = {s["key"]: s for s in setups.catalogue()}
    for key in ("ronniev-matrix", "ronniev-ma-stack"):
        assert key in cat
        spec = setups.SETUPS[key]
        assert spec["confidence"] == "stated"
        assert spec["quotes"], f"{key} claims 'stated' so it must carry quotes"


def test_matrix_setup_does_not_pretend_to_reproduce_the_trigger():
    spec = setups.SETUPS["ronniev-matrix"]
    text = " ".join(spec.get("caveats", []) + [spec["source"]]).lower()
    assert "proprietary" in text
    assert "reproduce" in text or "reproduces" in text


def test_ma_stack_keeps_the_counter_intuitive_rule():
    # The whole value of this setup is that repeated tests WEAKEN support; if that
    # sentence is ever lost the setup degrades into generic moving-average advice.
    reading = " ".join(setups.SETUPS["ronniev-ma-stack"]["reading"]).lower()
    assert "weaken" in reading
    assert any("quick succession" in q for q in setups.SETUPS["ronniev-ma-stack"]["quotes"])


CHECKS = []


def check(label, ok, detail=""):
    CHECKS.append((label, bool(ok), detail))


for _name, _fn in sorted(globals().items()):
    if not _name.startswith("test_") or not callable(_fn):
        continue
    try:
        _fn()
        check(_name.replace("test_", "").replace("_", " "), True)
    except AssertionError as exc:
        check(_name.replace("test_", "").replace("_", " "), False, str(exc)[:70])
    except Exception as exc:                                    # noqa: BLE001
        check(_name.replace("test_", "").replace("_", " "), False,
              f"{type(exc).__name__}: {str(exc)[:60]}")


# ------------------------------------------------------- macro series -----
# One series read for its structure, offline: nothing here may touch the
# network, so `fetch=False` and an empty cache must report "insufficient"
# rather than raise or invent a reading.
import sqlite3 as _sqlite3
IM = intermarket


def _db(series=None):
    conn = _sqlite3.connect(":memory:")
    conn.row_factory = _sqlite3.Row
    conn.executescript((Path(__file__).resolve().parent.parent / "app" / "schema.sql").read_text())
    for sym, rows in (series or {}).items():
        sid = conn.execute("INSERT INTO securities (symbol, kind) VALUES (?, 'equity')", (sym,)).lastrowid
        for d, c in rows.items():
            conn.execute("""INSERT INTO prices (security_id, bar_date, close, open, high, low, volume, source)
                            VALUES (?,?,?,?,?,?,0,'test')""", (sid, d, c, c, c, c))
    conn.commit()
    return conn


_conn_empty = _db()
_mc = IM.macro_catalogue()
check("the macro catalogue lists the mortgage-rate series with its FRED id",
      any(m["key"] == "mortgage-30y" and m["pair"] == "MORTGAGE30US" for m in _mc), _mc)
check("a macro entry attributed to nobody says so in its attribution",
      all(m["attribution"].lower().startswith("nobody") for m in _mc if m["confidence"] == "proposed"))
_r = IM.evaluate_macro(_conn_empty, "mortgage-30y", "2026-09-04", fetch=False)
check("with no cached history the macro read is insufficient, not a guess",
      _r.get("insufficient") and "state" in _r and not _r.get("line"), _r)
check("an unknown macro key is an error", "error" in IM.evaluate_macro(_conn_empty, "nope", "2026-09-04", fetch=False))
# A synthetic falling series: a resistance line from the high should be found
# and the latest value reported as under it.
import math as _math
_rows = {}
from datetime import date as _dd, timedelta as _tdd
_d0 = _dd(2022, 1, 6)
for i in range(240):
    _rows[(_d0 + _tdd(days=7 * i)).isoformat()] = 8.0 - i * 0.01 + 0.3 * _math.sin(i / 5)
_conn_m = _db({"MORTGAGE30US": _rows})
_rm = IM.evaluate_macro(_conn_m, "mortgage-30y", "2026-12-31", fetch=False)
check("with cached weekly history the macro read reports a value and a state",
      not _rm.get("insufficient") and _rm.get("value") and "%" in _rm["state"], _rm.get("state"))

failures = [c for c in CHECKS if not c[1]]
for label, ok, detail in CHECKS:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {detail}")
print(f"\n  {len(CHECKS)-len(failures)}/{len(CHECKS)} passed")
sys.exit(1 if failures else 0)
