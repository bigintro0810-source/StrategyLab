"""Smart Money Concepts (SMC) indicators - V3.0 指標ライブラリ拡充 Tier 3.

UNLIKE engine/technical_indicators.py, these do NOT have a single agreed
industry-standard definition - FVG/Order Block/BOS/CHoCH/Liquidity Sweep
are defined differently across different traders and tools. Per an
explicit 2026-07-03 decision, these are implemented with common/ICT-style
approximations and are NOT verified against TradingView or any specific
reference indicator. Treat results from these as exploratory, not
validated ground truth, until someone checks them against a real chart.

All five originally shipped as BEARISH-only variants, matching the old
trigger/filter system's short-only direction. Bullish mirror-image
variants (bullish_fvg, bullish_order_block, liquidity_sweep_bullish,
bos_choch_bullish) were added 2026-07-06 so these are usable from the
generic AND/OR/NOT condition-tree engine (engine/conditions.py), which
supports long, short, and simultaneous long+short strategies - the
project's charter explicitly forbids short-only design. The original
bearish functions are unchanged, still consumed by the legacy
trigger/filter system exactly as before.

breaker_block_bullish/breaker_block_bearish (added 2026-07-06) build on
top of bearish_order_block/bullish_order_block: a "breaker" is what an
order block becomes once price breaks clean through it and later comes
back to retest it from the other side, flipping its role (old resistance
becomes support, or vice versa). Like the rest of this module, this is a
simplified/exploratory approximation, not a verified reference definition.

Swing-point detection (used by BOS/CHoCH/Liquidity Sweep) is causally
careful: a swing point at bar k is only "confirmed" (usable without
lookahead bias) `lookback` bars later, once we've seen enough future bars
to know it really was a local extreme. Functions here account for that
confirmation delay internally - callers get back arrays safe to index at
bar i using only information available by bar i.
"""

import numpy as np
import pandas as pd


def _collapse_consecutive_runs(flags: pd.Series) -> pd.Series:
    """Keep only the first bar of each contiguous run of True values.

    A rounded/flat local extreme can satisfy the rolling-window equality
    check on several adjacent bars in a row (a plateau bottom, or two
    bars tied to the pip). Without this, each such run would be treated
    as several distinct swing events instead of one, corrupting
    "the swing level before this one" comparisons downstream.
    """
    is_first_of_run = flags & ~flags.shift(1, fill_value=False)
    return is_first_of_run


def _detect_swing_highs(high: pd.Series, lookback: int) -> pd.Series:
    window = 2 * lookback + 1
    is_max = high == high.rolling(window=window, center=True).max()
    return _collapse_consecutive_runs(is_max.fillna(False))


def _detect_swing_lows(low: pd.Series, lookback: int) -> pd.Series:
    window = 2 * lookback + 1
    is_min = low == low.rolling(window=window, center=True).min()
    return _collapse_consecutive_runs(is_min.fillna(False))


def _confirmed_swing_level_series(is_swing: pd.Series, level: pd.Series, lookback: int) -> pd.Series:
    """NaN everywhere except at the bar where a swing point becomes
    confirmable (lookback bars after it formed), where it holds that
    swing point's price level."""
    confirmed_at = is_swing.shift(lookback).fillna(False)
    level_at_confirmation = level.shift(lookback)
    return level_at_confirmation.where(confirmed_at)


def _last_confirmed_level(swing_level_series: pd.Series) -> pd.Series:
    """The most recently confirmed swing level as of each bar (forward-filled)."""
    return swing_level_series.ffill()


def _previous_confirmed_level(swing_level_series: pd.Series) -> pd.Series:
    """The confirmed swing level BEFORE the current one, as of each bar -
    used to tell whether swing points have been rising or falling."""
    sparse = swing_level_series.dropna()
    prev_sparse = sparse.shift(1)
    return prev_sparse.reindex(swing_level_series.index).ffill()


def bearish_fvg(high: pd.Series, low: pd.Series) -> np.ndarray:
    """Fair Value Gap: a 3-candle imbalance where candle i-2's low sits
    above candle i's high, leaving a gap the market skipped over.
    Simplified definition - only flags the bar the gap completes on, does
    not track whether the gap later gets "filled"."""
    prev2_low = low.shift(2)
    return (prev2_low > high).fillna(False).to_numpy()


def bullish_fvg(high: pd.Series, low: pd.Series) -> np.ndarray:
    """Mirror image of bearish_fvg: candle i-2's high sits below candle
    i's low, leaving an upward gap the market skipped over."""
    prev2_high = high.shift(2)
    return (prev2_high < low).fillna(False).to_numpy()


def bearish_order_block(open_: pd.Series, close: pd.Series) -> np.ndarray:
    """Simplified 2-candle order block: a bullish candle immediately
    followed by a bearish candle with a larger body (an "engulfing"-style
    reversal), flagged on the bullish candle's bar. Simpler than the
    multi-candle "impulse move" definitions some traders use - a
    deliberate simplification for a first pass."""
    is_bullish = close > open_
    this_body = close - open_

    next_open = open_.shift(-1)
    next_close = close.shift(-1)
    next_is_bearish = next_close < next_open
    next_body = next_open - next_close

    return (is_bullish & next_is_bearish & (next_body > this_body)).fillna(False).to_numpy()


def bullish_order_block(open_: pd.Series, close: pd.Series) -> np.ndarray:
    """Mirror image of bearish_order_block: a bearish candle immediately
    followed by a bullish candle with a larger body, flagged on the
    bearish candle's bar."""
    is_bearish = close < open_
    this_body = open_ - close

    next_open = open_.shift(-1)
    next_close = close.shift(-1)
    next_is_bullish = next_close > next_open
    next_body = next_close - next_open

    return (is_bearish & next_is_bullish & (next_body > this_body)).fillna(False).to_numpy()


def liquidity_sweep_bearish(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int) -> np.ndarray:
    """A bar's high wicks above the most recently confirmed swing high but
    closes back below it - a "stop hunt" above resistance followed by
    rejection."""
    swing_high_flags = _detect_swing_highs(high, lookback)
    swing_high_series = _confirmed_swing_level_series(swing_high_flags, high, lookback)
    recent_swing_high = _last_confirmed_level(swing_high_series)

    return ((high > recent_swing_high) & (close < recent_swing_high)).fillna(False).to_numpy()


def liquidity_sweep_bullish(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int) -> np.ndarray:
    """Mirror image of liquidity_sweep_bearish: a bar's low wicks below
    the most recently confirmed swing low but closes back above it - a
    "stop hunt" below support followed by rejection."""
    swing_low_flags = _detect_swing_lows(low, lookback)
    swing_low_series = _confirmed_swing_level_series(swing_low_flags, low, lookback)
    recent_swing_low = _last_confirmed_level(swing_low_series)

    return ((low < recent_swing_low) & (close > recent_swing_low)).fillna(False).to_numpy()


def bos_choch_bearish(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int) -> tuple[np.ndarray, np.ndarray]:
    """Distinguishes a downside break of structure into two flavors:

    - BOS (continuation): close breaks below the most recent confirmed
      swing low, and that swing low was already LOWER than the swing low
      before it (structure was already trending down).
    - CHoCH (reversal): close breaks below the most recent confirmed swing
      low, but that swing low was HIGHER than the one before it
      (structure had been making higher lows / trending up) - the first
      break signaling a possible trend change.

    Returns (bos_bearish, choch_bearish) as two boolean arrays.
    """
    swing_low_flags = _detect_swing_lows(low, lookback)
    swing_low_series = _confirmed_swing_level_series(swing_low_flags, low, lookback)

    recent_swing_low = _last_confirmed_level(swing_low_series)
    previous_swing_low = _previous_confirmed_level(swing_low_series)

    close_arr = close.to_numpy(dtype=float)
    recent_arr = recent_swing_low.to_numpy(dtype=float)
    prev_arr = previous_swing_low.to_numpy(dtype=float)

    broke_below = close_arr < recent_arr
    prev_above = np.roll(broke_below, 1)
    prev_above[0] = False
    fresh_break = broke_below & ~prev_above

    was_downtrend = recent_arr <= prev_arr
    was_uptrend = recent_arr > prev_arr

    bos_bearish = fresh_break & was_downtrend & ~np.isnan(prev_arr)
    choch_bearish = fresh_break & was_uptrend & ~np.isnan(prev_arr)

    return bos_bearish, choch_bearish


def bos_choch_bullish(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int) -> tuple[np.ndarray, np.ndarray]:
    """Mirror image of bos_choch_bearish, for upside breaks of structure:

    - BOS (continuation): close breaks above the most recent confirmed
      swing high, and that swing high was already HIGHER than the swing
      high before it (structure was already trending up).
    - CHoCH (reversal): close breaks above the most recent confirmed swing
      high, but that swing high was LOWER than the one before it
      (structure had been making lower highs / trending down) - the first
      break signaling a possible trend change.

    Returns (bos_bullish, choch_bullish) as two boolean arrays.
    """
    swing_high_flags = _detect_swing_highs(high, lookback)
    swing_high_series = _confirmed_swing_level_series(swing_high_flags, high, lookback)

    recent_swing_high = _last_confirmed_level(swing_high_series)
    previous_swing_high = _previous_confirmed_level(swing_high_series)

    close_arr = close.to_numpy(dtype=float)
    recent_arr = recent_swing_high.to_numpy(dtype=float)
    prev_arr = previous_swing_high.to_numpy(dtype=float)

    broke_above = close_arr > recent_arr
    prev_below = np.roll(broke_above, 1)
    prev_below[0] = False
    fresh_break = broke_above & ~prev_below

    was_uptrend = recent_arr >= prev_arr
    was_downtrend = recent_arr < prev_arr

    bos_bullish = fresh_break & was_uptrend & ~np.isnan(prev_arr)
    choch_bullish = fresh_break & was_downtrend & ~np.isnan(prev_arr)

    return bos_bullish, choch_bullish


def _tracked_zone_level(ob_flags: pd.Series, zone_level: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Forward-fills `zone_level` starting from each bar where ob_flags is
    True, so every bar carries the most recently formed order block's zone
    price (NaN before the first one ever forms). Also returns an "epoch id"
    (incrementing once per new order block) callers use to reset their own
    "has this specific zone broken yet" tracking each time a newer order
    block supersedes an older, still-untested one."""
    epoch_id = ob_flags.cumsum()
    level = zone_level.where(ob_flags).groupby(epoch_id).transform("first")
    return level, epoch_id


def breaker_block_bullish(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> np.ndarray:
    """A bearish order block (a bullish candle overwhelmed by a larger
    bearish one - see bearish_order_block) that price later closes clean
    above (breaking the resistance it was expected to hold), then pulls
    back down and touches that same zone again - flipping it from
    resistance to support. Fires on every bar the retest condition holds
    (not just the first), matching liquidity_sweep/BOS-CHoCH's style."""
    ob_flags = pd.Series(bearish_order_block(open_, close), index=close.index)
    zone_high = np.maximum(open_, close)

    tracked_high, epoch_id = _tracked_zone_level(ob_flags, zone_high)
    broke_above = close > tracked_high
    broken_so_far = broke_above.groupby(epoch_id).cummax().fillna(False)

    return (broken_so_far & (low <= tracked_high)).fillna(False).to_numpy()


def breaker_block_bearish(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> np.ndarray:
    """Mirror image of breaker_block_bullish: a bullish order block (a
    bearish candle overwhelmed by a larger bullish one - see
    bullish_order_block) that price later closes clean below (breaking the
    support it was expected to hold), then pulls back up and touches that
    same zone again - flipping it from support to resistance."""
    ob_flags = pd.Series(bullish_order_block(open_, close), index=close.index)
    zone_low = np.minimum(open_, close)

    tracked_low, epoch_id = _tracked_zone_level(ob_flags, zone_low)
    broke_below = close < tracked_low
    broken_so_far = broke_below.groupby(epoch_id).cummax().fillna(False)

    return (broken_so_far & (high >= tracked_low)).fillna(False).to_numpy()
