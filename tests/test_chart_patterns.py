"""Regression tests for engine/chart_patterns.py (classic multi-swing chart
patterns, added 2026-07-08). Plain-script style (not pytest-based) matching
this project's convention - run directly with `python
tests/test_chart_patterns.py`.

Hand-built synthetic OHLC sequences with a known answer by construction -
there's no external reference to check chart-pattern definitions against
(same situation as engine/smc_indicators.py and engine/candlestick_patterns.py).
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


def _hlc(closes: np.ndarray, wick: float = 0.3) -> tuple[pd.Series, pd.Series, pd.Series]:
    high = pd.Series(closes + wick)
    low = pd.Series(closes - wick)
    close = pd.Series(closes)
    return high, low, close


def test_double_top_breakdown():
    leg1_up = np.linspace(100, 130, 15)
    leg1_down = np.linspace(130, 110, 15)
    leg2_up = np.linspace(110, 130.2, 15)   # second top close to the first
    leg2_down = np.linspace(130.2, 105, 20)  # breaks below the trough (~110)
    closes = np.concatenate([leg1_up, leg1_down, leg2_up, leg2_down])
    high, low, close = _hlc(closes)
    result = cp.double_top_breakdown(high, low, close, swing_lookback=5, tolerance_atr_mult=1.0)
    check("double_top_breakdown fires exactly once on a clean double top", result.sum() == 1, detail=str(np.where(result)[0]))


def test_double_top_breakdown_rejects_dissimilar_tops():
    # Second peak is FAR higher than the first - not a double top, so this
    # must never fire even though price does eventually dip and recover.
    leg1_up = np.linspace(100, 130, 15)
    leg1_down = np.linspace(130, 110, 15)
    leg2_up = np.linspace(110, 160, 15)  # much taller second peak
    leg2_down = np.linspace(160, 140, 20)
    closes = np.concatenate([leg1_up, leg1_down, leg2_up, leg2_down])
    high, low, close = _hlc(closes)
    result = cp.double_top_breakdown(high, low, close, swing_lookback=5, tolerance_atr_mult=0.5)
    check("double_top_breakdown does not fire when the two peaks are clearly different levels", result.sum() == 0, detail=str(result.sum()))


def test_double_bottom_breakout():
    leg1_down = np.linspace(130, 100, 15)
    leg1_up = np.linspace(100, 120, 15)
    leg2_down = np.linspace(120, 99.8, 15)  # second bottom close to the first
    leg2_up = np.linspace(99.8, 135, 20)     # breaks above the peak (~120)
    closes = np.concatenate([leg1_down, leg1_up, leg2_down, leg2_up])
    high, low, close = _hlc(closes)
    result = cp.double_bottom_breakout(high, low, close, swing_lookback=5, tolerance_atr_mult=1.0)
    check("double_bottom_breakout fires exactly once on a clean double bottom", result.sum() == 1, detail=str(np.where(result)[0]))


def test_head_and_shoulders_breakdown():
    left_shoulder_up = np.linspace(100, 120, 12)
    left_shoulder_down = np.linspace(120, 108, 12)
    head_up = np.linspace(108, 140, 12)      # head clearly higher
    head_down = np.linspace(140, 108, 12)    # trough back to a similar level
    right_shoulder_up = np.linspace(108, 120.5, 12)  # shoulder similar to the left one
    right_shoulder_down = np.linspace(120.5, 95, 20)  # breaks the neckline (~108)
    closes = np.concatenate([
        left_shoulder_up, left_shoulder_down, head_up, head_down,
        right_shoulder_up, right_shoulder_down,
    ])
    high, low, close = _hlc(closes)
    result = cp.head_and_shoulders_breakdown(high, low, close, swing_lookback=5, shoulder_tolerance_atr_mult=1.0, head_margin_atr_mult=0.5)
    check("head_and_shoulders_breakdown fires at least once on a clean H&S", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_ascending_triangle_breakout():
    # Flat resistance around 130, rising support (each trough higher than
    # the last), then a clean break above resistance.
    rng = np.random.RandomState(0)
    segments = []
    base = 100.0
    for i in range(4):
        up = np.linspace(base, 130 - rng.uniform(0, 0.3), 10)
        down = np.linspace(130 - rng.uniform(0, 0.3), base + 5, 10)
        segments.append(up)
        segments.append(down)
        base += 5
    breakout = np.linspace(base, 145, 15)
    closes = np.concatenate(segments + [breakout])
    high, low, close = _hlc(closes)
    result = cp.ascending_triangle_breakout(high, low, close, swing_lookback=4, flat_tolerance_atr_mult=1.0)
    check("ascending_triangle_breakout fires at least once", result.sum() >= 1, detail=str(result.sum()))


def test_in_range_box_and_breakout():
    rng = np.random.RandomState(1)
    boxed = 100 + rng.normal(0, 0.1, 100)
    breakout = 100 + np.cumsum(np.abs(rng.normal(0.3, 0.1, 20)))  # sustained push upward
    closes = np.concatenate([boxed, breakout])
    high, low, close = _hlc(closes, wick=0.15)
    boxed_state = cp.in_range_box(high, low, close, window=20, box_atr_mult=2.0)
    breakout_signal = cp.range_box_breakout_bullish(high, low, close, window=20, box_atr_mult=2.0)
    check("in_range_box reads True during the boxed phase", boxed_state[30:95].sum() > 0)
    check("range_box_breakout_bullish fires after the box, during the breakout run", breakout_signal[100:120].sum() > 0, detail=str(breakout_signal[95:120]))


def test_first_occurrence_after_fires_once_per_epoch():
    # Two independent double-top formations back-to-back should each fire
    # once - the epoch/cumsum machinery must not get stuck after the first.
    def make_double_top(base):
        leg1_up = np.linspace(base, base + 30, 15)
        leg1_down = np.linspace(base + 30, base + 10, 15)
        leg2_up = np.linspace(base + 10, base + 30.1, 15)
        leg2_down = np.linspace(base + 30.1, base - 5, 20)
        return np.concatenate([leg1_up, leg1_down, leg2_up, leg2_down])

    closes = np.concatenate([make_double_top(100), make_double_top(150)])
    high, low, close = _hlc(closes)
    result = cp.double_top_breakdown(high, low, close, swing_lookback=5, tolerance_atr_mult=1.0)
    check("double_top_breakdown fires exactly twice across two independent formations", result.sum() == 2, detail=str(np.where(result)[0]))


if __name__ == "__main__":
    test_double_top_breakdown()
    test_double_top_breakdown_rejects_dissimilar_tops()
    test_double_bottom_breakout()
    test_head_and_shoulders_breakdown()
    test_ascending_triangle_breakout()
    test_in_range_box_and_breakout()
    test_first_occurrence_after_fires_once_per_epoch()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll chart_patterns tests passed.")
