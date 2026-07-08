"""Candlestick pattern recognition - single/two/three-candle shapes plus a
few statistical "N consecutive bars" conditions, all as boolean per-bar
signals (1.0/0.0) matching engine/smc_indicators.py's existing convention.

Every function is a pure vectorized computation over the whole price
series (no per-bar Python loop) and is causally safe: any reference to a
"previous" bar uses .shift(), and any rolling average used as a comparison
baseline is itself .shift(1)'d so it never includes the current bar being
measured against it (same convention as engine/conditions.py's
_highest_high/_lowest_low).

Like engine/smc_indicators.py, these are geometric pattern definitions, not
verified against any reference charting platform - candlestick pattern
definitions vary somewhat between sources (exact wick/body ratio
thresholds differ by author), so the specific default thresholds below are
reasonable conventional choices, not a single universally-agreed standard.

Traditional pattern pairs that are geometrically IDENTICAL and only differ
by the surrounding trend context (hammer vs hanging man; inverted hammer vs
shooting star) are implemented once and registered under both names in
engine/conditions.py - this project's charter treats trend context as an
independent, separately composable condition (e.g. AND'd with an EMA slope
or SuperTrend direction) rather than baking it into the candle shape
itself, matching the same "conditions and direction are independent axes"
principle used throughout this engine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_range(high: pd.Series, low: pd.Series) -> pd.Series:
    return (high - low).replace(0, np.nan)


def _abs_body(open_: pd.Series, close: pd.Series) -> pd.Series:
    return (close - open_).abs()


def _upper_wick(open_: pd.Series, high: pd.Series, close: pd.Series) -> pd.Series:
    return high - np.maximum(open_, close)


def _lower_wick(open_: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    return np.minimum(open_, close) - low


def bullish_candle(open_: pd.Series, close: pd.Series) -> pd.Series:
    return close > open_


def bearish_candle(open_: pd.Series, close: pd.Series) -> pd.Series:
    return close < open_


def _large_candle(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool, lookback: int, multiplier: float,
) -> pd.Series:
    abs_body = _abs_body(open_, close)
    avg_body = abs_body.rolling(lookback).mean().shift(1)
    direction = bullish_candle(open_, close) if bullish else bearish_candle(open_, close)
    return direction & (abs_body > avg_body * multiplier)


def large_bullish_candle(open_, high, low, close, lookback: int = 20, multiplier: float = 1.5) -> pd.Series:
    return _large_candle(open_, high, low, close, True, lookback, multiplier)


def large_bearish_candle(open_, high, low, close, lookback: int = 20, multiplier: float = 1.5) -> pd.Series:
    return _large_candle(open_, high, low, close, False, lookback, multiplier)


def _small_candle(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool, lookback: int, multiplier: float,
) -> pd.Series:
    abs_body = _abs_body(open_, close)
    avg_body = abs_body.rolling(lookback).mean().shift(1)
    direction = bullish_candle(open_, close) if bullish else bearish_candle(open_, close)
    return direction & (abs_body < avg_body * multiplier) & (avg_body > 0)


def small_bullish_candle(open_, high, low, close, lookback: int = 20, multiplier: float = 0.5) -> pd.Series:
    return _small_candle(open_, high, low, close, True, lookback, multiplier)


def small_bearish_candle(open_, high, low, close, lookback: int = 20, multiplier: float = 0.5) -> pd.Series:
    return _small_candle(open_, high, low, close, False, lookback, multiplier)


def doji(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, body_ratio_threshold: float = 0.1) -> pd.Series:
    body_pct = _abs_body(open_, close) / _safe_range(high, low)
    return body_pct < body_ratio_threshold


def long_upper_wick(open_, high, low, close, wick_ratio_threshold: float = 0.6) -> pd.Series:
    rng = _safe_range(high, low)
    return (_upper_wick(open_, high, close) / rng) >= wick_ratio_threshold


def long_lower_wick(open_, high, low, close, wick_ratio_threshold: float = 0.6) -> pd.Series:
    rng = _safe_range(high, low)
    return (_lower_wick(open_, low, close) / rng) >= wick_ratio_threshold


def no_upper_wick(open_, high, low, close, threshold: float = 0.05) -> pd.Series:
    rng = _safe_range(high, low)
    return (_upper_wick(open_, high, close) / rng) <= threshold


def no_lower_wick(open_, high, low, close, threshold: float = 0.05) -> pd.Series:
    rng = _safe_range(high, low)
    return (_lower_wick(open_, low, close) / rng) <= threshold


def marubozu_bullish(open_, high, low, close, body_ratio_threshold: float = 0.95) -> pd.Series:
    body_pct = _abs_body(open_, close) / _safe_range(high, low)
    return bullish_candle(open_, close) & (body_pct >= body_ratio_threshold)


def marubozu_bearish(open_, high, low, close, body_ratio_threshold: float = 0.95) -> pd.Series:
    body_pct = _abs_body(open_, close) / _safe_range(high, low)
    return bearish_candle(open_, close) & (body_pct >= body_ratio_threshold)


def pin_bar_bullish(open_, high, low, close, body_ratio_max: float = 0.3, wick_ratio_min: float = 0.6) -> pd.Series:
    """Small body + a dominant LOWER wick (rejection of lower prices)."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    lower_pct = _lower_wick(open_, low, close) / rng
    return (body_pct <= body_ratio_max) & (lower_pct >= wick_ratio_min)


def pin_bar_bearish(open_, high, low, close, body_ratio_max: float = 0.3, wick_ratio_min: float = 0.6) -> pd.Series:
    """Small body + a dominant UPPER wick (rejection of higher prices)."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    upper_pct = _upper_wick(open_, high, close) / rng
    return (body_pct <= body_ratio_max) & (upper_pct >= wick_ratio_min)


def hammer_shape(
    open_, high, low, close,
    body_ratio_max: float = 0.3, lower_wick_ratio_min: float = 0.6, upper_wick_ratio_max: float = 0.1,
) -> pd.Series:
    """Small body near the TOP of the range, long lower wick, minimal upper
    wick - geometrically identical whether the trader calls this a Hammer
    (bullish reversal, seen after a downtrend) or a Hanging Man (bearish
    reversal, seen after an uptrend); see this module's own docstring for
    why trend context isn't baked in here."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    lower_pct = _lower_wick(open_, low, close) / rng
    upper_pct = _upper_wick(open_, high, close) / rng
    return (body_pct <= body_ratio_max) & (lower_pct >= lower_wick_ratio_min) & (upper_pct <= upper_wick_ratio_max)


def inverted_hammer_shape(
    open_, high, low, close,
    body_ratio_max: float = 0.3, upper_wick_ratio_min: float = 0.6, lower_wick_ratio_max: float = 0.1,
) -> pd.Series:
    """Small body near the BOTTOM of the range, long upper wick, minimal
    lower wick - Inverted Hammer (bullish reversal after a downtrend) and
    Shooting Star (bearish reversal after an uptrend) share this exact
    shape; see this module's docstring."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    upper_pct = _upper_wick(open_, high, close) / rng
    lower_pct = _lower_wick(open_, low, close) / rng
    return (body_pct <= body_ratio_max) & (upper_pct >= upper_wick_ratio_min) & (lower_pct <= lower_wick_ratio_max)


def long_legged_doji(open_, high, low, close, body_ratio_threshold: float = 0.1, wick_ratio_min: float = 0.35) -> pd.Series:
    """Doji (near-zero body) with BOTH wicks substantial - unlike a plain
    doji, which says nothing about wick length, this specifically requires
    the indecision to have played out with real range on both sides."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    upper_pct = _upper_wick(open_, high, close) / rng
    lower_pct = _lower_wick(open_, low, close) / rng
    return (body_pct < body_ratio_threshold) & (upper_pct >= wick_ratio_min) & (lower_pct >= wick_ratio_min)


def dragonfly_doji(
    open_, high, low, close, body_ratio_threshold: float = 0.1,
    lower_wick_ratio_min: float = 0.6, upper_wick_ratio_max: float = 0.1,
) -> pd.Series:
    """Doji sitting at the TOP of its range - a long lower wick and almost
    no upper wick, the same rejection-of-lower-prices shape as a hammer but
    with a true near-zero body rather than merely a small one."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    lower_pct = _lower_wick(open_, low, close) / rng
    upper_pct = _upper_wick(open_, high, close) / rng
    return (body_pct < body_ratio_threshold) & (lower_pct >= lower_wick_ratio_min) & (upper_pct <= upper_wick_ratio_max)


def gravestone_doji(
    open_, high, low, close, body_ratio_threshold: float = 0.1,
    upper_wick_ratio_min: float = 0.6, lower_wick_ratio_max: float = 0.1,
) -> pd.Series:
    """Mirror image of dragonfly_doji: doji sitting at the BOTTOM of its
    range, long upper wick, almost no lower wick."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    upper_pct = _upper_wick(open_, high, close) / rng
    lower_pct = _lower_wick(open_, low, close) / rng
    return (body_pct < body_ratio_threshold) & (upper_pct >= upper_wick_ratio_min) & (lower_pct <= lower_wick_ratio_max)


def spinning_top(open_, high, low, close, body_ratio_max: float = 0.3, wick_ratio_min: float = 0.3) -> pd.Series:
    """Small (but not doji-tiny) body with substantial wicks on BOTH sides,
    roughly balanced - net indecision after a move, distinct from a doji
    (near-zero body) and from a pin bar (one dominant wick, not two)."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    upper_pct = _upper_wick(open_, high, close) / rng
    lower_pct = _lower_wick(open_, low, close) / rng
    return (body_pct <= body_ratio_max) & (upper_pct >= wick_ratio_min) & (lower_pct >= wick_ratio_min)


def kicker_bullish(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, body_ratio_threshold: float = 0.7) -> pd.Series:
    """Previous candle bearish, current candle gaps up past the PREVIOUS
    OPEN (not just the previous close - a stronger gap than gap_up alone)
    and closes as a strong bullish candle with no overlap at all between
    the two bodies - the sharpest, least-ambiguous single-bar reversal
    signal in this module."""
    prev_bearish = bearish_candle(open_, close).shift(1).fillna(False)
    gapped_past_prev_open = open_ > open_.shift(1)
    cur_bullish = bullish_candle(open_, close)
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    return prev_bearish & gapped_past_prev_open & cur_bullish & (body_pct >= body_ratio_threshold)


def kicker_bearish(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, body_ratio_threshold: float = 0.7) -> pd.Series:
    """Mirror image of kicker_bullish: previous candle bullish, current
    candle gaps down past the previous open and closes as a strong bearish
    candle with no body overlap."""
    prev_bullish = bullish_candle(open_, close).shift(1).fillna(False)
    gapped_past_prev_open = open_ < open_.shift(1)
    cur_bearish = bearish_candle(open_, close)
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    return prev_bullish & gapped_past_prev_open & cur_bearish & (body_pct >= body_ratio_threshold)


def belt_hold_bullish(open_, high, low, close, lower_wick_ratio_max: float = 0.05, body_ratio_min: float = 0.7) -> pd.Series:
    """Opens at (or almost at) the bar's low and closes strongly higher -
    no time for a lower wick to form, all conviction from the open."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    lower_pct = _lower_wick(open_, low, close) / rng
    return bullish_candle(open_, close) & (lower_pct <= lower_wick_ratio_max) & (body_pct >= body_ratio_min)


def belt_hold_bearish(open_, high, low, close, upper_wick_ratio_max: float = 0.05, body_ratio_min: float = 0.7) -> pd.Series:
    """Mirror image of belt_hold_bullish: opens at (or almost at) the bar's
    high and closes strongly lower."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    upper_pct = _upper_wick(open_, high, close) / rng
    return bearish_candle(open_, close) & (upper_pct <= upper_wick_ratio_max) & (body_pct >= body_ratio_min)


def abandoned_baby_bullish(open_, high, low, close, small_body_ratio: float = 0.1) -> pd.Series:
    """Stricter version of morning_star: the middle candle isn't just
    small, it must have a TRUE price gap on both sides (its high sits
    below the first candle's low, and the third candle's low sits above
    its high) - an isolated island of indecision, not merely a small-
    bodied candle within overlapping ranges."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng

    c1_bearish = bearish_candle(open_, close).shift(2).fillna(False)
    c1_low = low.shift(2)
    c2_small = body_pct.shift(1) < small_body_ratio
    c2_high = high.shift(1)
    gapped_down_into_c2 = c2_high < c1_low
    c3_bullish = bullish_candle(open_, close)
    gapped_up_out_of_c2 = low > c2_high

    return c1_bearish & c2_small & gapped_down_into_c2 & c3_bullish & gapped_up_out_of_c2


def abandoned_baby_bearish(open_, high, low, close, small_body_ratio: float = 0.1) -> pd.Series:
    """Mirror image of abandoned_baby_bullish: an isolated small-bodied
    candle gapped ABOVE the first candle's high, then a third bearish
    candle gaps back down below it."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng

    c1_bullish = bullish_candle(open_, close).shift(2).fillna(False)
    c1_high = high.shift(2)
    c2_small = body_pct.shift(1) < small_body_ratio
    c2_low = low.shift(1)
    gapped_up_into_c2 = c2_low > c1_high
    c3_bearish = bearish_candle(open_, close)
    gapped_down_out_of_c2 = high < c2_low

    return c1_bullish & c2_small & gapped_up_into_c2 & c3_bearish & gapped_down_out_of_c2


def three_inside_up(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """harami_bullish (a large bearish candle then a smaller bullish candle
    contained within it) completed on the PREVIOUS bar, confirmed by the
    current bar closing higher still - the confirmation candle that
    upgrades a harami from "maybe a pause" to "a real reversal"."""
    prior_harami = harami_bullish(open_, close).shift(1).fillna(False)
    confirmation = close > close.shift(1)
    return prior_harami & confirmation


def three_inside_down(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Mirror image of three_inside_up, confirming a harami_bearish."""
    prior_harami = harami_bearish(open_, close).shift(1).fillna(False)
    confirmation = close < close.shift(1)
    return prior_harami & confirmation


def three_outside_up(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """engulfing_bullish completed on the PREVIOUS bar, confirmed by the
    current bar closing higher still."""
    prior_engulfing = engulfing_bullish(open_, close).shift(1).fillna(False)
    confirmation = close > close.shift(1)
    return prior_engulfing & confirmation


def three_outside_down(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Mirror image of three_outside_up, confirming an engulfing_bearish."""
    prior_engulfing = engulfing_bearish(open_, close).shift(1).fillna(False)
    confirmation = close < close.shift(1)
    return prior_engulfing & confirmation


# ---------------------------------------------------------------------------
# Two-candle patterns
# ---------------------------------------------------------------------------


def engulfing_bullish(open_: pd.Series, close: pd.Series) -> pd.Series:
    prev_bearish = bearish_candle(open_, close).shift(1).fillna(False)
    cur_bullish = bullish_candle(open_, close)
    return prev_bearish & cur_bullish & (open_ <= close.shift(1)) & (close >= open_.shift(1))


def engulfing_bearish(open_: pd.Series, close: pd.Series) -> pd.Series:
    prev_bullish = bullish_candle(open_, close).shift(1).fillna(False)
    cur_bearish = bearish_candle(open_, close)
    return prev_bullish & cur_bearish & (open_ >= close.shift(1)) & (close <= open_.shift(1))


def inside_bar(high: pd.Series, low: pd.Series) -> pd.Series:
    return (high < high.shift(1)) & (low > low.shift(1))


def outside_bar(high: pd.Series, low: pd.Series) -> pd.Series:
    return (high > high.shift(1)) & (low < low.shift(1))


def tweezer_top(open_, high, low, close, tolerance_pct: float = 0.1) -> pd.Series:
    rng = _safe_range(high, low)
    avg_rng = (rng + rng.shift(1)) / 2
    matching_highs = (high - high.shift(1)).abs() <= avg_rng * tolerance_pct
    prev_bullish = bullish_candle(open_, close).shift(1).fillna(False)
    cur_bearish = bearish_candle(open_, close)
    return matching_highs & prev_bullish & cur_bearish


def tweezer_bottom(open_, high, low, close, tolerance_pct: float = 0.1) -> pd.Series:
    rng = _safe_range(high, low)
    avg_rng = (rng + rng.shift(1)) / 2
    matching_lows = (low - low.shift(1)).abs() <= avg_rng * tolerance_pct
    prev_bearish = bearish_candle(open_, close).shift(1).fillna(False)
    cur_bullish = bullish_candle(open_, close)
    return matching_lows & prev_bearish & cur_bullish


def harami_bullish(open_: pd.Series, close: pd.Series) -> pd.Series:
    """Previous bar a large bearish candle; current bar a smaller bullish
    candle whose body is fully contained within the previous body."""
    prev_bearish = bearish_candle(open_, close).shift(1).fillna(False)
    cur_bullish = bullish_candle(open_, close)
    prev_top = np.maximum(open_.shift(1), close.shift(1))
    prev_bottom = np.minimum(open_.shift(1), close.shift(1))
    cur_top = np.maximum(open_, close)
    cur_bottom = np.minimum(open_, close)
    contained = (cur_top <= prev_top) & (cur_bottom >= prev_bottom)
    return prev_bearish & cur_bullish & contained


def harami_bearish(open_: pd.Series, close: pd.Series) -> pd.Series:
    """Previous bar a large bullish candle; current bar a smaller bearish
    candle whose body is fully contained within the previous body."""
    prev_bullish = bullish_candle(open_, close).shift(1).fillna(False)
    cur_bearish = bearish_candle(open_, close)
    prev_top = np.maximum(open_.shift(1), close.shift(1))
    prev_bottom = np.minimum(open_.shift(1), close.shift(1))
    cur_top = np.maximum(open_, close)
    cur_bottom = np.minimum(open_, close)
    contained = (cur_top <= prev_top) & (cur_bottom >= prev_bottom)
    return prev_bullish & cur_bearish & contained


def gap_up(open_: pd.Series, high: pd.Series) -> pd.Series:
    return open_ > high.shift(1)


def gap_down(open_: pd.Series, low: pd.Series) -> pd.Series:
    return open_ < low.shift(1)


# ---------------------------------------------------------------------------
# Three-candle (and Three Methods' traditional 5-candle) patterns
# ---------------------------------------------------------------------------


def morning_star(open_, high, low, close, small_body_ratio: float = 0.3) -> pd.Series:
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng

    c1_bearish = bearish_candle(open_, close).shift(2).fillna(False)
    c1_body = _abs_body(open_, close).shift(2)
    c1_mid = ((open_.shift(2) + close.shift(2)) / 2)
    c2_small = body_pct.shift(1) < small_body_ratio
    c3_bullish = bullish_candle(open_, close)
    c3_large = _abs_body(open_, close) > c1_body * 0.5
    c3_closes_above_mid = close > c1_mid

    return c1_bearish & c2_small & c3_bullish & c3_large & c3_closes_above_mid


def evening_star(open_, high, low, close, small_body_ratio: float = 0.3) -> pd.Series:
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng

    c1_bullish = bullish_candle(open_, close).shift(2).fillna(False)
    c1_body = _abs_body(open_, close).shift(2)
    c1_mid = ((open_.shift(2) + close.shift(2)) / 2)
    c2_small = body_pct.shift(1) < small_body_ratio
    c3_bearish = bearish_candle(open_, close)
    c3_large = _abs_body(open_, close) > c1_body * 0.5
    c3_closes_below_mid = close < c1_mid

    return c1_bullish & c2_small & c3_bearish & c3_large & c3_closes_below_mid


def three_white_soldiers(open_: pd.Series, close: pd.Series) -> pd.Series:
    bullish = bullish_candle(open_, close)
    all_bullish = bullish & bullish.shift(1).fillna(False) & bullish.shift(2).fillna(False)
    rising_closes = (close > close.shift(1)) & (close.shift(1) > close.shift(2))
    opens_within_prior_body = (
        (open_ > open_.shift(1)) & (open_ < close.shift(1))
        & (open_.shift(1) > open_.shift(2)) & (open_.shift(1) < close.shift(2))
    )
    return all_bullish & rising_closes & opens_within_prior_body


def three_black_crows(open_: pd.Series, close: pd.Series) -> pd.Series:
    bearish = bearish_candle(open_, close)
    all_bearish = bearish & bearish.shift(1).fillna(False) & bearish.shift(2).fillna(False)
    falling_closes = (close < close.shift(1)) & (close.shift(1) < close.shift(2))
    opens_within_prior_body = (
        (open_ < open_.shift(1)) & (open_ > close.shift(1))
        & (open_.shift(1) < open_.shift(2)) & (open_.shift(1) > close.shift(2))
    )
    return all_bearish & falling_closes & opens_within_prior_body


def rising_three_methods(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Traditional 5-candle continuation: one large bullish candle, three
    small consolidating candles staying within its range, then a final
    large bullish candle breaking to a new high."""
    c1_bullish = bullish_candle(open_, close).shift(4).fillna(False)
    c1_high = high.shift(4)
    c1_low = low.shift(4)

    middle_within_range = pd.Series(True, index=open_.index)
    for k in (1, 2, 3):
        middle_within_range &= (high.shift(k) <= c1_high) & (low.shift(k) >= c1_low)

    c5_bullish = bullish_candle(open_, close)
    c5_breaks_high = close > c1_high

    return c1_bullish & middle_within_range & c5_bullish & c5_breaks_high


def falling_three_methods(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    c1_bearish = bearish_candle(open_, close).shift(4).fillna(False)
    c1_high = high.shift(4)
    c1_low = low.shift(4)

    middle_within_range = pd.Series(True, index=open_.index)
    for k in (1, 2, 3):
        middle_within_range &= (high.shift(k) <= c1_high) & (low.shift(k) >= c1_low)

    c5_bearish = bearish_candle(open_, close)
    c5_breaks_low = close < c1_low

    return c1_bearish & middle_within_range & c5_bearish & c5_breaks_low


# ---------------------------------------------------------------------------
# Statistical / "N consecutive bars" conditions
# ---------------------------------------------------------------------------


def consecutive_bullish_candles(open_: pd.Series, close: pd.Series, n: int = 3) -> pd.Series:
    bullish_int = bullish_candle(open_, close).astype(int)
    return bullish_int.rolling(n).sum() == n


def consecutive_bearish_candles(open_: pd.Series, close: pd.Series, n: int = 3) -> pd.Series:
    bearish_int = bearish_candle(open_, close).astype(int)
    return bearish_int.rolling(n).sum() == n


def consecutive_higher_highs(high: pd.Series, n: int = 3) -> pd.Series:
    higher_int = (high > high.shift(1)).astype(int)
    return higher_int.rolling(n).sum() == n


def consecutive_lower_lows(low: pd.Series, n: int = 3) -> pd.Series:
    lower_int = (low < low.shift(1)).astype(int)
    return lower_int.rolling(n).sum() == n


def body_larger_than_average(open_, high, low, close, lookback: int = 20, multiplier: float = 1.5) -> pd.Series:
    abs_body = _abs_body(open_, close)
    avg_body = abs_body.rolling(lookback).mean().shift(1)
    return abs_body > avg_body * multiplier


def wick_ratio_at_least(open_, high, low, close, threshold_pct: float = 50.0) -> pd.Series:
    rng = _safe_range(high, low)
    total_wick_pct = (_upper_wick(open_, high, close) + _lower_wick(open_, low, close)) / rng * 100.0
    return total_wick_pct >= threshold_pct


def body_ratio_at_least(open_, high, low, close, threshold_pct: float = 50.0) -> pd.Series:
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng * 100.0
    return body_pct >= threshold_pct
