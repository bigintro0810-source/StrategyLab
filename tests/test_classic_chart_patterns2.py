"""Regression tests for the second HFM-list follow-up round (2026-07-08):
saucer top/bottom, ascending/descending rectangle, broadening formation,
diamond formation, cup with handle - all in engine/chart_patterns.py.
Plain-script style, matching this project's convention.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import engine.chart_patterns as cp

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


def _seg(a: float, b: float, n: int) -> np.ndarray:
    return np.linspace(a, b, n)


def _hlc(closes: np.ndarray, wick: float = 0.3) -> tuple[pd.Series, pd.Series, pd.Series]:
    return pd.Series(closes + wick), pd.Series(closes - wick), pd.Series(closes)


def test_saucer_bottom_fires_on_smooth_u_shape():
    x = np.linspace(-1, 1, 40)
    closes = 100 + 20 * x ** 2
    high, low, close = _hlc(closes)
    result = cp.saucer_bottom(high, low, close, window=30)
    check("saucer_bottom fires on a smooth U-shape", result[-10:].sum() > 0)


def test_saucer_top_does_not_fire_on_a_u_shape():
    x = np.linspace(-1, 1, 40)
    closes = 100 + 20 * x ** 2
    high, low, close = _hlc(closes)
    result = cp.saucer_top(high, low, close, window=30)
    check("saucer_top does not fire on a U-shape (wrong concavity)", result[-10:].sum() == 0)


def test_ascending_rectangle_breakout():
    trend = _seg(80, 120, 40)
    box = np.full(25, 120.0) + np.random.RandomState(0).normal(0, 0.15, 25)
    breakout = _seg(120, 140, 15)
    closes = np.concatenate([trend, box, breakout])
    high, low, close = _hlc(closes)
    result = cp.ascending_rectangle_breakout(high, low, close, window=20, box_atr_mult=2.0, trend_lookback=30)
    check("ascending_rectangle_breakout fires after a prior uptrend + box breakout", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_ascending_rectangle_rejects_without_prior_trend():
    # Same box+breakout shape, but with a DECLINING (not flat) run-up to
    # the box - unambiguously not an uptrend by a wide margin, so the
    # box's own small internal noise can't flip the comparison by chance
    # (a merely-flat baseline sits right at the decision boundary and is
    # too fragile a test fixture). Must not fire.
    declining_before = _seg(130, 100, 40)
    box = np.full(25, 100.0) + np.random.RandomState(2).normal(0, 0.15, 25)
    breakout = _seg(100, 120, 15)
    closes = np.concatenate([declining_before, box, breakout])
    high, low, close = _hlc(closes)
    result = cp.ascending_rectangle_breakout(high, low, close, window=20, box_atr_mult=2.0, trend_lookback=30)
    check("ascending_rectangle_breakout does not fire without a genuine prior uptrend", result.sum() == 0, detail=str(result.sum()))


def test_broadening_formation_breakout_bullish():
    rng = np.random.RandomState(1)
    segments = []
    hi, lo = 110.0, 90.0
    for _ in range(4):
        segments.append(_seg(lo, hi, 10))
        segments.append(_seg(hi, lo - 3, 10))
        hi += 8
        lo -= 3
    breakout = _seg(lo + 3, lo + 40, 15)
    closes = np.concatenate(segments + [breakout])
    high, low, close = _hlc(closes)
    result = cp.broadening_formation_breakout_bullish(high, low, close, swing_lookback=4)
    check("broadening_formation_breakout_bullish fires on a diverging structure", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_diamond_formation_breakout_bullish():
    segs = [
        _seg(100, 90, 12), _seg(90, 110, 12), _seg(110, 85, 12), _seg(85, 120, 12),
        _seg(120, 95, 12), _seg(95, 115, 12), _seg(115, 105, 12), _seg(105, 140, 15),
    ]
    closes = np.concatenate(segs)
    high, low, close = _hlc(closes)
    result = cp.diamond_formation_breakout_bullish(high, low, close, swing_lookback=4)
    check("diamond_formation_breakout_bullish fires on broadening-then-narrowing", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_cup_with_handle_breakout():
    x = np.linspace(-1, 1, 40)
    cup = 120 - 20 * (1 - x ** 2)
    handle = 118 + np.random.RandomState(0).normal(0, 0.15, 10)
    breakout = _seg(118, 140, 15)
    closes = np.concatenate([cup, handle, breakout])
    high, low, close = _hlc(closes, wick=0.2)
    result = cp.cup_with_handle_breakout(high, low, close, cup_window=30, handle_window=10, handle_atr_mult=1.5)
    check("cup_with_handle_breakout fires after the handle breaks out", result.sum() >= 1, detail=str(np.where(result)[0]))


if __name__ == "__main__":
    test_saucer_bottom_fires_on_smooth_u_shape()
    test_saucer_top_does_not_fire_on_a_u_shape()
    test_ascending_rectangle_breakout()
    test_ascending_rectangle_rejects_without_prior_trend()
    test_broadening_formation_breakout_bullish()
    test_diamond_formation_breakout_bullish()
    test_cup_with_handle_breakout()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll classic_chart_patterns2 tests passed.")
