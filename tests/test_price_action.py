"""Regression tests for the 2026-07-08 price-action round: trendline
break/parallel channel/false breakout (engine/chart_patterns.py), NR4/NR7
and volume climax (engine/derived_indicators.py), and AB=CD/Three Drives
(engine/harmonic_patterns.py). Plain-script style, matching this project's
convention - run directly with `python tests/test_price_action.py`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import engine.chart_patterns as cp
import engine.derived_indicators as di
import engine.harmonic_patterns as hp

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


def _seg(a: float, b: float, n: int = 15) -> np.ndarray:
    return np.linspace(a, b, n)


def _hlc(closes: np.ndarray, wick: float = 0.3) -> tuple[pd.Series, pd.Series, pd.Series]:
    return pd.Series(closes + wick), pd.Series(closes - wick), pd.Series(closes)


def _make_df(rows: list[dict], freq_minutes: int = 15) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["datetime"] = pd.date_range("2024-01-01", periods=len(rows), freq=f"{freq_minutes}min")
    return df


def test_uptrend_line_break():
    closes = np.concatenate([
        _seg(110, 100, 12), _seg(100, 120, 12), _seg(120, 105, 12),
        _seg(105, 125, 12), _seg(125, 90, 20),
    ])
    high, low, close = _hlc(closes)
    result = cp.uptrend_line_break(high, low, close, swing_lookback=5)
    check("uptrend_line_break fires on a clean support-line breakdown", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_downtrend_line_break():
    closes = np.concatenate([
        _seg(90, 100, 12), _seg(100, 80, 12), _seg(80, 95, 12),
        _seg(95, 75, 12), _seg(75, 110, 20),
    ])
    high, low, close = _hlc(closes)
    result = cp.downtrend_line_break(high, low, close, swing_lookback=5)
    check("downtrend_line_break fires on a clean resistance-line breakout", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_false_breakout_bullish_reversal():
    rng = np.random.RandomState(2)
    boxed = 100 + rng.normal(0, 0.05, 60)
    fake_break = [99.0, 98.7, 99.3]
    after = 100 + rng.normal(0, 0.05, 30)
    closes = np.concatenate([boxed, fake_break, after])
    high, low, close = _hlc(closes, wick=0.1)
    result = cp.false_breakout_bullish_reversal(high, low, close, window=20, box_atr_mult=2.0, max_bars_outside=3)
    check("false_breakout_bullish_reversal fires right after price returns inside the box", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_false_breakout_does_not_fire_on_a_real_breakout():
    rng = np.random.RandomState(3)
    boxed = 100 + rng.normal(0, 0.05, 60)
    real_breakout = 100 + np.cumsum(np.abs(rng.normal(0.3, 0.05, 30)))  # sustained move away, never returns
    closes = np.concatenate([boxed, real_breakout])
    high, low, close = _hlc(closes, wick=0.1)
    result = cp.false_breakout_bullish_reversal(high, low, close, window=20, box_atr_mult=2.0, max_bars_outside=3)
    # A sustained breakout with no prompt return should not read as a fakey reversal.
    check("false_breakout_bullish_reversal does not fire on a genuine sustained breakout", result.sum() == 0, detail=str(result.sum()))


def test_nr4_nr7():
    rng = np.random.RandomState(4)
    # 10 bars of normal range, then one deliberately narrow bar.
    ranges = np.abs(rng.normal(1.0, 0.2, 10))
    closes = 100 + np.cumsum(rng.normal(0, 0.1, 10))
    rows = []
    for c, r in zip(closes, ranges):
        rows.append({"open": c, "high": c + r / 2, "low": c - r / 2, "close": c})
    # Narrowest-of-4 and narrowest-of-7 bar.
    rows.append({"open": 100.0, "high": 100.05, "low": 99.98, "close": 100.02})
    df = _make_df(rows)
    nr4 = di.nr4(df)
    nr7 = di.nr7(df)
    check("nr4 fires on the deliberately narrow final bar", nr4[-1] == 1.0)
    check("nr7 fires on the deliberately narrow final bar", nr7[-1] == 1.0)


def test_volume_climax_bullish():
    rng = np.random.RandomState(5)
    n = 25
    closes = 100 + rng.normal(0, 0.05, n)
    rows = [{"open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 1000 + rng.normal(0, 50)} for c in closes]
    # A climax bar: huge bullish body + huge volume.
    rows.append({"open": 100.0, "high": 105.5, "low": 99.9, "close": 105.0, "volume": 10000})
    df = _make_df(rows)
    result = di.volume_climax_bullish(df, lookback=20, body_mult=2.0, volume_mult=2.0)
    check("volume_climax_bullish fires on the exaggerated final bar", result[-1] == 1.0)
    check("volume_climax_bullish does not fire on the quiet baseline bars", result[:n].sum() == 0, detail=str(result[:n].sum()))


def test_ab_cd_bullish():
    a, b = 200.0, 100.0
    c = b + 0.618 * (a - b)
    d = c - 1.0 * (a - b)
    closes = np.concatenate([_seg(a - 50, a, 15), _seg(a, b, 15), _seg(b, c, 15), _seg(c, d, 15), _seg(d, d + 10, 15)])
    high, low, _close = _hlc(closes)
    result = hp.ab_cd_bullish(high, low, lookback=5, tolerance=0.1)
    check("ab_cd_bullish fires on an exact-ratio AB=CD", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_three_drives_bearish():
    p0 = 100.0
    p1 = p0 + 100
    p2 = p1 - 0.7 * (p1 - p0)
    drive1 = p1 - p0
    correction1 = p1 - p2
    drive2 = 1.4 * correction1
    p3 = p2 + drive2
    correction2 = 0.7 * drive2
    p4 = p3 - correction2
    drive3 = 1.4 * correction2
    p5 = p4 + drive3
    closes = np.concatenate([
        _seg(p0 + 40, p0, 12), _seg(p0, p1, 15), _seg(p1, p2, 15),
        _seg(p2, p3, 15), _seg(p3, p4, 15), _seg(p4, p5, 15), _seg(p5, p5 - 10, 15),
    ])
    high, low, _close = _hlc(closes)
    result = hp.three_drives_bearish(high, low, lookback=5, tolerance=0.15)
    check("three_drives_bearish fires on an exact-ratio three-drives-up structure", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_ascending_channel_break():
    # Parallel rising support/resistance, then a breakdown below support.
    rng = np.random.RandomState(6)
    segments = []
    base = 100.0
    for i in range(4):
        up = np.linspace(base, base + 20 - rng.uniform(0, 0.3), 10)
        down = np.linspace(base + 20 - rng.uniform(0, 0.3), base + 5, 10)
        segments.append(up)
        segments.append(down)
        base += 5
    breakdown = np.linspace(base, base - 30, 15)
    closes = np.concatenate(segments + [breakdown])
    high, low, close = _hlc(closes)
    result = cp.ascending_channel_break(high, low, close, swing_lookback=4, slope_tolerance_atr_mult=0.5)
    check("ascending_channel_break fires at least once", result.sum() >= 1, detail=str(result.sum()))


if __name__ == "__main__":
    test_uptrend_line_break()
    test_downtrend_line_break()
    test_false_breakout_bullish_reversal()
    test_false_breakout_does_not_fire_on_a_real_breakout()
    test_nr4_nr7()
    test_volume_climax_bullish()
    test_ab_cd_bullish()
    test_three_drives_bearish()
    test_ascending_channel_break()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll price_action tests passed.")
