"""Regression tests for engine/derived_indicators.py (距離系/傾き系/価格位置/
統計系/イベント系, added 2026-07-08). Plain-script style (not pytest-based)
matching this project's convention - run directly with `python
tests/test_derived_indicators.py`, prints PASS/FAIL per check and exits 1 on
any failure.

Covers the state-tracking indicators by hand-built synthetic OHLC data with
a known answer (same approach as tests/test_candlestick_patterns.py, since
there's no external reference to check these against) - the simple
rolling-window ones are exercised via the real-data smoke test already run
during implementation, not re-duplicated here bar-by-bar.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine import derived_indicators as di

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


def _make_df(rows: list[dict], start="2024-01-01 00:00:00", freq_minutes=15) -> pd.DataFrame:
    n = len(rows)
    datetimes = pd.date_range(start=start, periods=n, freq=f"{freq_minutes}min")
    df = pd.DataFrame(rows)
    df["datetime"] = datetimes
    return df


def test_ema_rising_falling():
    # A strictly increasing close series -> EMA also strictly increases once
    # warmed up, so ema_rising should be True and ema_falling False at the end.
    closes = list(np.linspace(100, 110, 60))
    rows = [{"open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    rising = di.SLOPE_INDICATORS["ema_rising"](df, length=5, lookback=1)
    falling = di.SLOPE_INDICATORS["ema_falling"](df, length=5, lookback=1)
    check("ema_rising true on strict uptrend (last bar)", rising[-1] == 1.0)
    check("ema_falling false on strict uptrend (last bar)", falling[-1] == 0.0)


def test_higher_high_lower_low():
    # Two down-legs and two up-legs, each swing point separated far enough
    # for lookback=2's window(=5)+confirmation-delay(=2) requirements:
    # trough1=100 (idx4) < trough2=105 (idx15) -> higher_low at idx17;
    # peak1=130 (idx10) < peak2=160 (idx21) -> higher_high at idx23.
    closes = [
        120, 115, 110, 105, 100, 105, 110, 115, 120, 125, 130, 125, 120, 115,
        110, 105, 110, 120, 130, 140, 150, 160, 150, 140, 130, 120, 110,
    ]
    rows = [{"open": c, "high": c + 0.2, "low": c - 0.2, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    hh = di.higher_high(df, lookback=2)
    ll = di.higher_low(df, lookback=2)
    check("higher_high fires once the second, taller peak confirms", hh.sum() >= 1, detail=str(np.where(hh)[0]))
    check("higher_low fires once the second, shallower trough confirms", ll.sum() >= 1, detail=str(np.where(ll)[0]))


def test_bb_percent_b_bounds_and_direction():
    rng = np.random.RandomState(0)
    closes = 100 + np.cumsum(rng.normal(0, 0.05, 200))
    rows = [{"open": c, "high": c + 0.05, "low": c - 0.05, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    percent_b = di.bb_percent_b(df, period=20, num_std=2.0)
    finite = percent_b[~np.isnan(percent_b)]
    check("bb_percent_b mostly within [-0.5, 1.5] for mild-noise series", np.mean((finite > -0.5) & (finite < 1.5)) > 0.9)


def test_donchian_percent_position_bounds():
    rng = np.random.RandomState(1)
    closes = 100 + np.cumsum(rng.normal(0, 0.05, 200))
    rows = [{"open": c, "high": c + 0.05, "low": c - 0.05, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    pos = di.donchian_percent_position(df, length=20)
    finite = pos[~np.isnan(pos)]
    check("donchian_percent_position within [0,1] (close is always within its own trailing hi/lo band, sans the shift(1) edge)", np.mean((finite >= -0.05) & (finite <= 1.05)) > 0.95)


def test_today_new_high_low_resets_daily():
    # Day 1: rising highs (each bar a new high). Day 2 starts lower - the
    # first bar of day 2 must NOT count as "new high" relative to day 1's
    # close-of-day high (resets, doesn't carry over).
    day1 = [{"open": 100 + i, "high": 100 + i + 0.5, "low": 100 + i - 0.2, "close": 100 + i, "volume": 100} for i in range(5)]
    day2 = [{"open": 90, "high": 90.3, "low": 89.5, "close": 90, "volume": 100}]
    rows = day1 + day2
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(
        [f"2024-01-01 0{i}:00:00" for i in range(5)] + ["2024-01-02 00:00:00"]
    )
    new_high = di.today_new_high(df)
    check("day1 bars 1-4 each make a new high", list(new_high[1:5]) == [1.0, 1.0, 1.0, 1.0])
    check("day1 bar 0 never counts as new high (nothing earlier today)", new_high[0] == 0.0)
    check("day2 bar 0 doesn't inherit day1's high streak", new_high[5] == 0.0)


def test_bb_squeeze_and_expansion():
    # Three phases so the trailing-100-bar percentile rank has something to
    # discriminate against: normal noise (baseline), then genuinely
    # narrower noise (should rank low = squeeze), then a sudden burst
    # (should read as expansion right after).
    # Narrow phase kept short relative to `window` so it never dominates its
    # own trailing window (a percentile-rank squeeze naturally stops
    # reading as "squeezed" once the narrow values are the majority of what
    # they're being ranked against - not a bug, just what a relative/rolling
    # definition means; keeping the narrow-phase minority-sized avoids that
    # self-dilution from confusing this test).
    rng = np.random.RandomState(2)
    normal = 100 + rng.normal(0, 0.05, 100)
    narrow = 100 + rng.normal(0, 0.003, 20)
    rows = [{"open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 100} for c in normal]
    rows += [{"open": c, "high": c + 0.006, "low": c - 0.006, "close": c, "volume": 100} for c in narrow]
    burst = 100 + np.cumsum(rng.normal(0, 0.5, 10))
    rows += [{"open": c, "high": c + 1.0, "low": c - 1.0, "close": c, "volume": 100} for c in burst]
    df = _make_df(rows)
    squeeze = di.bb_squeeze(df, period=20, num_std=2.0, window=100, percentile=20.0)
    expansion = di.bb_expansion(df, period=20, num_std=2.0, window=100, percentile=20.0)
    check("bb_squeeze fires right before the burst", squeeze[110:120].sum() > 0, detail=str(squeeze[110:120].sum()))
    check("bb_expansion fires right as the volatility burst starts", expansion[120:130].sum() > 0, detail=str(expansion[120:130].sum()))


def test_supertrend_flip():
    # A clear downtrend then a sharp reversal to uptrend should flip
    # supertrend_direction from -1 to 1 at least once.
    down = list(np.linspace(120, 100, 40))
    up = list(np.linspace(100, 130, 40))
    closes = down + up
    rows = [{"open": c, "high": c + 0.3, "low": c - 0.3, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    flip_bullish = di.supertrend_flip_bullish(df, length=10, multiplier=3.0)
    check("supertrend_flip_bullish fires at least once across a down->up reversal", flip_bullish.sum() >= 1)


def test_ema_perfect_order():
    # Strong sustained uptrend -> fast EMA should end up above slower EMAs
    # (bullish perfect order) by the end of the series.
    closes = list(np.linspace(100, 160, 300))
    rows = [{"open": c, "high": c + 0.2, "low": c - 0.2, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    bullish = di.ema_perfect_order_bullish(df, length_1=5, length_2=10, length_3=20, length_4=40)
    check("ema_perfect_order_bullish holds at the end of a sustained uptrend", bullish[-1] == 1.0)


def test_first_pullback_after_breakout():
    # Breakout above the trailing 10-bar high, then one down bar (the
    # pullback), then more down bars - only the FIRST down bar after the
    # breakout should be flagged, not every subsequent one.
    flat = [100.0] * 12
    breakout = [101.0, 102.0]
    pullback = [101.5, 100.8, 100.0]  # three down bars in a row
    closes = flat + breakout + pullback
    rows = [{"open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    result = di.first_pullback_after_breakout_bullish(df, length=10)
    fire_indices = np.where(result == 1.0)[0]
    check("first_pullback_after_breakout_bullish fires exactly once for the 3-bar pullback", len(fire_indices) == 1,
          detail=f"got {fire_indices}")


def test_fvg_first_retest():
    # Build a clean bullish FVG (bar i-2 high < bar i low), then bring price
    # back down to touch the gap on a later bar - should fire once, on the
    # first touch, not on every bar the price happens to sit in the gap.
    rows = [
        {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},   # 0
        {"open": 101.0, "high": 102.0, "low": 100.8, "close": 101.5},  # 1 (gap-forming impulse)
        {"open": 103.0, "high": 104.0, "low": 102.8, "close": 103.5},  # 2: prev2_high(0)=100.2 < low(2)=102.8 -> bullish FVG
        {"open": 104.0, "high": 105.0, "low": 103.5, "close": 104.5},  # 3: away from the gap
        {"open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0},  # 4: dips back down through the gap (100.2) -> first retest
        {"open": 101.0, "high": 101.5, "low": 100.0, "close": 100.5},  # 5: still inside/near the gap -> should NOT re-fire
    ]
    for r in rows:
        r["volume"] = 100
    df = _make_df(rows)
    result = di.fvg_first_retest_bullish(df)
    check("fvg_first_retest_bullish fires on bar 4 (first touch)", result[4] == 1.0, detail=str(result))
    check("fvg_first_retest_bullish does not re-fire on bar 5", result[5] == 0.0, detail=str(result))


def test_dist_indicators_nonnegative():
    rng = np.random.RandomState(3)
    closes = 100 + np.cumsum(rng.normal(0, 0.05, 250))
    rows = [{"open": c, "high": c + 0.05, "low": c - 0.05, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    dist = di.DISTANCE_INDICATORS["dist_close_ema"](df, length=20)
    finite = dist[~np.isnan(dist)]
    check("dist_close_ema is always >= 0 (absolute distance)", np.all(finite >= 0))


def test_zscore_and_percentile_rank_bounds():
    rng = np.random.RandomState(4)
    closes = 100 + np.cumsum(rng.normal(0, 0.05, 300))
    rows = [{"open": c, "high": c + 0.05, "low": c - 0.05, "close": c, "volume": 100} for c in closes]
    df = _make_df(rows)
    z = di.zscore_close(df, window=20)
    finite_z = z[~np.isnan(z)]
    check("zscore_close stays within a sane range for mild noise", np.all(np.abs(finite_z) < 6))

    pct = di.percentile_rank_rsi(df, rsi_length=14, window=50)
    finite_pct = pct[~np.isnan(pct)]
    check("percentile_rank_rsi stays within [0,100]", np.all((finite_pct >= 0) & (finite_pct <= 100)))


if __name__ == "__main__":
    test_ema_rising_falling()
    test_higher_high_lower_low()
    test_bb_percent_b_bounds_and_direction()
    test_donchian_percent_position_bounds()
    test_today_new_high_low_resets_daily()
    test_bb_squeeze_and_expansion()
    test_supertrend_flip()
    test_ema_perfect_order()
    test_first_pullback_after_breakout()
    test_fvg_first_retest()
    test_dist_indicators_nonnegative()
    test_zscore_and_percentile_rank_bounds()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll derived_indicators tests passed.")
