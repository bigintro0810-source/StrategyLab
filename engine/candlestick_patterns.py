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

from engine.indicators import atr as _atr_series


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


def kicker_bullish(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    body_ratio_threshold: float = 0.7, require_gap: bool = True,
) -> pd.Series:
    """Previous candle bearish, current candle opens past the PREVIOUS
    OPEN (not just the previous close - a stronger move than gap_up alone)
    and closes as a strong bullish candle with no overlap at all between
    the two bodies - the sharpest, least-ambiguous single-bar reversal
    signal in this module. require_gap=True(既定)は現在の始値が前の始値を
    超えていることを要求する(株式・指数向け、FXではGapがほぼ発生しないため
    ほぼ常に不成立)。require_gap=Falseにすると始値の位置は問わず、色反転+
    実体無重複のみで判定する(FX等Gapが起きない市場向け)。"""
    prev_bearish = bearish_candle(open_, close).shift(1).fillna(False)
    cur_bullish = bullish_candle(open_, close)
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    no_overlap = open_ >= open_.shift(1)
    result = prev_bearish & cur_bullish & no_overlap & (body_pct >= body_ratio_threshold)
    if require_gap:
        result = result & (open_ > open_.shift(1))
    return result


def kicker_bearish(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    body_ratio_threshold: float = 0.7, require_gap: bool = True,
) -> pd.Series:
    """Mirror image of kicker_bullish - see its docstring for require_gap."""
    prev_bullish = bullish_candle(open_, close).shift(1).fillna(False)
    cur_bearish = bearish_candle(open_, close)
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng
    no_overlap = open_ <= open_.shift(1)
    result = prev_bullish & cur_bearish & no_overlap & (body_pct >= body_ratio_threshold)
    if require_gap:
        result = result & (open_ < open_.shift(1))
    return result


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


def three_inside_up(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, containment_tolerance: float = 0.0) -> pd.Series:
    """harami_bullish (a large bearish candle then a smaller bullish candle
    contained within it) completed on the PREVIOUS bar, confirmed by the
    current bar closing higher still - the confirmation candle that
    upgrades a harami from "maybe a pause" to "a real reversal".
    containment_tolerance: harami_bullishのパラメータをそのまま引き継ぐ。"""
    prior_harami = harami_bullish(open_, close, containment_tolerance).shift(1).fillna(False)
    confirmation = close > close.shift(1)
    return prior_harami & confirmation


def three_inside_down(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, containment_tolerance: float = 0.0) -> pd.Series:
    """Mirror image of three_inside_up, confirming a harami_bearish."""
    prior_harami = harami_bearish(open_, close, containment_tolerance).shift(1).fillna(False)
    confirmation = close < close.shift(1)
    return prior_harami & confirmation


def three_outside_up(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, tolerance_pct: float = 0.0) -> pd.Series:
    """engulfing_bullish completed on the PREVIOUS bar, confirmed by the
    current bar closing higher still. tolerance_pct: engulfing_bullishの
    パラメータをそのまま引き継ぐ。"""
    prior_engulfing = engulfing_bullish(open_, close, tolerance_pct).shift(1).fillna(False)
    confirmation = close > close.shift(1)
    return prior_engulfing & confirmation


def three_outside_down(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, tolerance_pct: float = 0.0) -> pd.Series:
    """Mirror image of three_outside_up, confirming an engulfing_bearish."""
    prior_engulfing = engulfing_bearish(open_, close, tolerance_pct).shift(1).fillna(False)
    confirmation = close < close.shift(1)
    return prior_engulfing & confirmation


# ---------------------------------------------------------------------------
# Two-candle patterns
# ---------------------------------------------------------------------------


def engulfing_bullish(open_: pd.Series, close: pd.Series, tolerance_pct: float = 0.0) -> pd.Series:
    """tolerance_pct: 0(既定)は前の実体を完全に包んだ場合のみ成立する厳格
    判定。0より大きくすると、前の実体サイズに対する割合分だけ包み不足を
    許容する(実務でよく使われる「ほぼ包んでいればOK」判定)。"""
    prev_bearish = bearish_candle(open_, close).shift(1).fillna(False)
    cur_bullish = bullish_candle(open_, close)
    prev_body = (close.shift(1) - open_.shift(1)).abs()
    slack = prev_body * tolerance_pct
    return prev_bearish & cur_bullish & (open_ <= close.shift(1) + slack) & (close >= open_.shift(1) - slack)


def engulfing_bearish(open_: pd.Series, close: pd.Series, tolerance_pct: float = 0.0) -> pd.Series:
    """Mirror image of engulfing_bullish - see its docstring for tolerance_pct."""
    prev_bullish = bullish_candle(open_, close).shift(1).fillna(False)
    cur_bearish = bearish_candle(open_, close)
    prev_body = (close.shift(1) - open_.shift(1)).abs()
    slack = prev_body * tolerance_pct
    return prev_bullish & cur_bearish & (open_ >= close.shift(1) - slack) & (close <= open_.shift(1) + slack)


def inside_bar(high: pd.Series, low: pd.Series, close: pd.Series | None = None, min_mother_range_atr_mult: float = 0.0) -> pd.Series:
    """min_mother_range_atr_mult=0(既定)は母足(前バー)のレンジの大きさを
    問わない(従来の挙動)。0より大きくすると、母足のレンジがATRの何倍以上
    かも要求する(小さすぎる母足によるノイズを除外したい場合向け。closeは
    ATR算出用でmin_mother_range_atr_mult=0のままなら省略可)。"""
    contained = (high < high.shift(1)) & (low > low.shift(1))
    if min_mother_range_atr_mult <= 0 or close is None:
        return contained
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    mother_range = (high - low).shift(1)
    return contained & (mother_range >= atr_values * min_mother_range_atr_mult)


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


def harami_bullish(open_: pd.Series, close: pd.Series, containment_tolerance: float = 0.0) -> pd.Series:
    """Previous bar a large bearish candle; current bar a smaller bullish
    candle whose body is (by default) fully contained within the previous
    body. containment_tolerance: 0(既定)は厳密な内包判定。0より大きくすると
    前の実体サイズに対する割合分だけ、現在の実体がはみ出すことを許容する。"""
    prev_bearish = bearish_candle(open_, close).shift(1).fillna(False)
    cur_bullish = bullish_candle(open_, close)
    prev_top = np.maximum(open_.shift(1), close.shift(1))
    prev_bottom = np.minimum(open_.shift(1), close.shift(1))
    slack = (prev_top - prev_bottom) * containment_tolerance
    cur_top = np.maximum(open_, close)
    cur_bottom = np.minimum(open_, close)
    contained = (cur_top <= prev_top + slack) & (cur_bottom >= prev_bottom - slack)
    return prev_bearish & cur_bullish & contained


def harami_bearish(open_: pd.Series, close: pd.Series, containment_tolerance: float = 0.0) -> pd.Series:
    """Mirror image of harami_bullish - see its docstring for containment_tolerance."""
    prev_bullish = bullish_candle(open_, close).shift(1).fillna(False)
    cur_bearish = bearish_candle(open_, close)
    prev_top = np.maximum(open_.shift(1), close.shift(1))
    prev_bottom = np.minimum(open_.shift(1), close.shift(1))
    slack = (prev_top - prev_bottom) * containment_tolerance
    cur_top = np.maximum(open_, close)
    cur_bottom = np.minimum(open_, close)
    contained = (cur_top <= prev_top + slack) & (cur_bottom >= prev_bottom - slack)
    return prev_bullish & cur_bearish & contained


def gap_up(open_: pd.Series, high: pd.Series, low: pd.Series | None = None, close: pd.Series | None = None, min_gap_atr_mult: float = 0.0) -> pd.Series:
    """min_gap_atr_mult=0(既定)は始値が前の高値を超えていれば成立(従来の
    挙動)。0より大きくすると、その超過分がATRの何倍以上かも要求する
    (ノイズレベルの小さなGapを除外したい場合向け。low/closeはATR算出用で、
    min_gap_atr_mult=0のままなら省略可)。"""
    gapped = open_ > high.shift(1)
    if min_gap_atr_mult <= 0 or low is None or close is None:
        return gapped
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    return gapped & ((open_ - high.shift(1)) >= atr_values * min_gap_atr_mult)


def gap_down(open_: pd.Series, low: pd.Series, high: pd.Series | None = None, close: pd.Series | None = None, min_gap_atr_mult: float = 0.0) -> pd.Series:
    """Mirror image of gap_up - see its docstring for min_gap_atr_mult."""
    gapped = open_ < low.shift(1)
    if min_gap_atr_mult <= 0 or high is None or close is None:
        return gapped
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    return gapped & ((low.shift(1) - open_) >= atr_values * min_gap_atr_mult)


# ---------------------------------------------------------------------------
# Three-candle (and Three Methods' traditional 5-candle) patterns
# ---------------------------------------------------------------------------


def morning_star(
    open_, high, low, close, small_body_ratio: float = 0.3,
    close_position_ratio: float = 0.5, require_gap: bool = False,
) -> pd.Series:
    """close_position_ratio: 3本目の終値が1本目の実体のどこまで押し戻せば
    成立とするか(0.5=中間点、既定。1.0にすると1本目の始値まで完全に押し
    戻す必要がある、より厳格な判定)。require_gap=True(既定False)にすると
    1本目→2本目、2本目→3本目それぞれに真のGapがあることも要求する
    (伝統的な定義。FXではGapがほぼ発生しないため既定はFalse)。"""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng

    c1_bearish = bearish_candle(open_, close).shift(2).fillna(False)
    c1_open = open_.shift(2)
    c1_close = close.shift(2)
    c1_body = _abs_body(open_, close).shift(2)
    c1_target = c1_close + (c1_open - c1_close) * close_position_ratio
    c2_small = body_pct.shift(1) < small_body_ratio
    c3_bullish = bullish_candle(open_, close)
    c3_large = _abs_body(open_, close) > c1_body * 0.5
    c3_closes_past_target = close > c1_target

    result = c1_bearish & c2_small & c3_bullish & c3_large & c3_closes_past_target
    if require_gap:
        gap_into_c2 = high.shift(1) < low.shift(2)
        gap_into_c3 = low < high.shift(1)
        result = result & gap_into_c2 & gap_into_c3
    return result


def evening_star(
    open_, high, low, close, small_body_ratio: float = 0.3,
    close_position_ratio: float = 0.5, require_gap: bool = False,
) -> pd.Series:
    """Mirror image of morning_star - see its docstring for
    close_position_ratio/require_gap."""
    rng = _safe_range(high, low)
    body_pct = _abs_body(open_, close) / rng

    c1_bullish = bullish_candle(open_, close).shift(2).fillna(False)
    c1_open = open_.shift(2)
    c1_close = close.shift(2)
    c1_body = _abs_body(open_, close).shift(2)
    c1_target = c1_close - (c1_close - c1_open) * close_position_ratio
    c2_small = body_pct.shift(1) < small_body_ratio
    c3_bearish = bearish_candle(open_, close)
    c3_large = _abs_body(open_, close) > c1_body * 0.5
    c3_closes_past_target = close < c1_target

    result = c1_bullish & c2_small & c3_bearish & c3_large & c3_closes_past_target
    if require_gap:
        gap_into_c2 = low.shift(1) > high.shift(2)
        gap_into_c3 = high < low.shift(1)
        result = result & gap_into_c2 & gap_into_c3
    return result


def three_white_soldiers(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, min_body_ratio: float = 0.0) -> pd.Series:
    """min_body_ratio=0(既定)は3本それぞれの実体の大きさを問わない(従来の
    挙動)。0より大きくすると、3本とも値幅に対する実体比率がこの値以上
    であることも要求する(弱い陽線3本による誤検出を除外したい場合向け)。"""
    bullish = bullish_candle(open_, close)
    all_bullish = bullish & bullish.shift(1).fillna(False) & bullish.shift(2).fillna(False)
    rising_closes = (close > close.shift(1)) & (close.shift(1) > close.shift(2))
    opens_within_prior_body = (
        (open_ > open_.shift(1)) & (open_ < close.shift(1))
        & (open_.shift(1) > open_.shift(2)) & (open_.shift(1) < close.shift(2))
    )
    result = all_bullish & rising_closes & opens_within_prior_body
    if min_body_ratio > 0:
        body_pct = _abs_body(open_, close) / _safe_range(high, low)
        strong_bodies = (body_pct >= min_body_ratio) & (body_pct.shift(1) >= min_body_ratio) & (body_pct.shift(2) >= min_body_ratio)
        result = result & strong_bodies
    return result


def three_black_crows(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, min_body_ratio: float = 0.0) -> pd.Series:
    """Mirror image of three_white_soldiers - see its docstring for min_body_ratio."""
    bearish = bearish_candle(open_, close)
    all_bearish = bearish & bearish.shift(1).fillna(False) & bearish.shift(2).fillna(False)
    falling_closes = (close < close.shift(1)) & (close.shift(1) < close.shift(2))
    opens_within_prior_body = (
        (open_ < open_.shift(1)) & (open_ > close.shift(1))
        & (open_.shift(1) < open_.shift(2)) & (open_.shift(1) > close.shift(2))
    )
    result = all_bearish & falling_closes & opens_within_prior_body
    if min_body_ratio > 0:
        body_pct = _abs_body(open_, close) / _safe_range(high, low)
        strong_bodies = (body_pct >= min_body_ratio) & (body_pct.shift(1) >= min_body_ratio) & (body_pct.shift(2) >= min_body_ratio)
        result = result & strong_bodies
    return result


def rising_three_methods(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, max_middle_body_ratio: float = 1.0) -> pd.Series:
    """Traditional 5-candle continuation: one large bullish candle, three
    small consolidating candles staying within its range, then a final
    large bullish candle breaking to a new high. max_middle_body_ratio=1.0
    (既定)は中間3本の実体の大きさを問わない(従来の挙動、レンジ内に収まる
    ことのみ要求)。1.0未満にすると、中間3本の実体が値幅に対してこの比率
    以下(=小さい、伝統的な定義によりよく合う)であることも要求する。"""
    c1_bullish = bullish_candle(open_, close).shift(4).fillna(False)
    c1_high = high.shift(4)
    c1_low = low.shift(4)

    middle_within_range = pd.Series(True, index=open_.index)
    for k in (1, 2, 3):
        middle_within_range &= (high.shift(k) <= c1_high) & (low.shift(k) >= c1_low)
    if max_middle_body_ratio < 1.0:
        body_pct = _abs_body(open_, close) / _safe_range(high, low)
        for k in (1, 2, 3):
            middle_within_range &= body_pct.shift(k) <= max_middle_body_ratio

    c5_bullish = bullish_candle(open_, close)
    c5_breaks_high = close > c1_high

    return c1_bullish & middle_within_range & c5_bullish & c5_breaks_high


def falling_three_methods(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, max_middle_body_ratio: float = 1.0) -> pd.Series:
    """Mirror image of rising_three_methods - see its docstring for max_middle_body_ratio."""
    c1_bearish = bearish_candle(open_, close).shift(4).fillna(False)
    c1_high = high.shift(4)
    c1_low = low.shift(4)

    middle_within_range = pd.Series(True, index=open_.index)
    for k in (1, 2, 3):
        middle_within_range &= (high.shift(k) <= c1_high) & (low.shift(k) >= c1_low)
    if max_middle_body_ratio < 1.0:
        body_pct = _abs_body(open_, close) / _safe_range(high, low)
        for k in (1, 2, 3):
            middle_within_range &= body_pct.shift(k) <= max_middle_body_ratio

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


def three_line_strike_bullish(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """TA-LibのCDL3LINESTRIKEと同じ定義: 3本連続の陰線(終値が切り下がり
    続ける)の直後、4本目が3本分の実体を丸ごと飲み込む大陽線で終わる形
    (前3本の陰線側から見た終値[-1]より下で始まり、1本目の陰線の始値
    より上で終わる)。"""
    bearish = bearish_candle(open_, close)
    three_bearish = bearish.shift(1).fillna(False) & bearish.shift(2).fillna(False) & bearish.shift(3).fillna(False)
    falling = (close.shift(1) < close.shift(2)) & (close.shift(2) < close.shift(3))
    cur_bullish = bullish_candle(open_, close)
    engulfs = (open_ < close.shift(1)) & (close > open_.shift(3))
    return (three_bearish & falling & cur_bullish & engulfs).fillna(False)


def three_line_strike_bearish(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Mirror image of three_line_strike_bullish."""
    bullish = bullish_candle(open_, close)
    three_bullish = bullish.shift(1).fillna(False) & bullish.shift(2).fillna(False) & bullish.shift(3).fillna(False)
    rising = (close.shift(1) > close.shift(2)) & (close.shift(2) > close.shift(3))
    cur_bearish = bearish_candle(open_, close)
    engulfs = (open_ > close.shift(1)) & (close < open_.shift(3))
    return (three_bullish & rising & cur_bearish & engulfs).fillna(False)


def tasuki_gap_upside(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """上昇継続のGapパターン: 陽線→(高値をGapで飛び越える)陽線→3本目が
    陰線で2本目の実体内から始まりGapへ戻すが、1本目の高値までは埋め
    きらない(Gapの一部が残る)。Gap前提のパターンのためFXではほぼ発生
    しない(TradingView等との照合は未検証)。"""
    bar1_bullish = bullish_candle(open_, close).shift(2).fillna(False)
    bar2_bullish = bullish_candle(open_, close).shift(1).fillna(False)
    gap_up = open_.shift(1) > high.shift(2)
    bar3_bearish = bearish_candle(open_, close)
    bar2_top = np.maximum(open_.shift(1), close.shift(1))
    bar2_bottom = np.minimum(open_.shift(1), close.shift(1))
    opens_within_bar2_body = (open_ < bar2_top) & (open_ > bar2_bottom)
    gap_not_fully_closed = close > high.shift(2)
    return (bar1_bullish & bar2_bullish & gap_up & bar3_bearish & opens_within_bar2_body & gap_not_fully_closed).fillna(False)


def tasuki_gap_downside(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Mirror image of tasuki_gap_upside."""
    bar1_bearish = bearish_candle(open_, close).shift(2).fillna(False)
    bar2_bearish = bearish_candle(open_, close).shift(1).fillna(False)
    gap_down = open_.shift(1) < low.shift(2)
    bar3_bullish = bullish_candle(open_, close)
    bar2_top = np.maximum(open_.shift(1), close.shift(1))
    bar2_bottom = np.minimum(open_.shift(1), close.shift(1))
    opens_within_bar2_body = (open_ < bar2_top) & (open_ > bar2_bottom)
    gap_not_fully_closed = close < low.shift(2)
    return (bar1_bearish & bar2_bearish & gap_down & bar3_bullish & opens_within_bar2_body & gap_not_fully_closed).fillna(False)
