"""Classic multi-swing chart patterns (double top/bottom, head & shoulders,
triangles, wedges, flags/pennants, range boxes) - built on top of
engine/smc_indicators.py's swing-high/swing-low detection (the same
machinery BOS/CHoCH already use), rather than a new fractal detector.

UNLIKE engine/technical_indicators.py's classic indicators, chart patterns
have no single agreed mechanical definition - real traders judge "is this a
head and shoulders" partly by eye. Everything here is a deliberately
simplified, vectorizable approximation (flat necklines instead of the
textbook's slanted ones, relative-tolerance level-matching instead of
subjective symmetry) - same "exploratory, not verified against any
reference charting tool" caveat engine/smc_indicators.py's own module
docstring already states, extended to a harder category of pattern.

Every function returns a plain np.ndarray[float] (boolean fired 1.0/0.0)
directly, same convention as engine/derived_indicators.py, for the same
reason (a pd.Series slipping into the numba fast backtest path crashed it
once - see engine/candlestick_patterns.py's history).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.indicators import atr as _atr_series
from engine.smc_indicators import _confirmed_swing_level_series, _detect_swing_highs, _detect_swing_lows


# ---------------------------------------------------------------------------
# Swing-level tracking: for each bar, the level and bar-index of the most
# recently confirmed swing high/low (n=0), the one before that (n=1), and
# the one before THAT (n=2) - generalizes smc_indicators.py's
# _last_confirmed_level/_previous_confirmed_level (which only ever look 1
# swing back) to however many a given pattern needs.
# ---------------------------------------------------------------------------

def _swing_high_levels(high: pd.Series, lookback: int) -> pd.Series:
    flags = _detect_swing_highs(high, lookback)
    return _confirmed_swing_level_series(flags, high, lookback)


def _swing_low_levels(low: pd.Series, lookback: int) -> pd.Series:
    flags = _detect_swing_lows(low, lookback)
    return _confirmed_swing_level_series(flags, low, lookback)


def _nth_back_level(level_series: pd.Series, n: int) -> pd.Series:
    sparse = level_series.dropna()
    shifted = sparse.shift(n)
    return shifted.reindex(level_series.index).ffill()


def _nth_back_bar_index(level_series: pd.Series, n: int = 0) -> pd.Series:
    """Integer position of the bar the n-th-back confirmed swing point (0 =
    most recent) was ORIGINALLY confirmed at, forward-filled onto the full
    timeline - `level_series` must be the RAW (unshifted) swing series
    (e.g. `swing_low`, not `_nth_back_level(swing_low, 1)`), same
    convention as _nth_back_level's own `n`."""
    sparse = level_series.dropna()
    bar_positions = pd.Series(sparse.index, index=sparse.index)
    shifted = bar_positions.shift(n)
    return shifted.reindex(level_series.index).ffill()


def _similar(a: pd.Series, b: pd.Series, atr: pd.Series, tolerance_atr_mult: float) -> pd.Series:
    """Whether two price levels are "the same level" for pattern-matching
    purposes, expressed as a multiple of ATR rather than a % of the raw
    price - a % of price scales wildly differently for a ~150-unit JPY
    pair vs a ~1-unit USD pair AND, separately, is the wrong order of
    magnitude entirely (a swing-to-swing gap is naturally comparable to a
    handful of bars' typical range, not a % of the symbol's absolute price
    level) - same ATR-normalization already used for dist_to_ema_atr_ratio
    and the flag/pennant impulse thresholds, for the same reason."""
    return (a - b).abs() <= atr * tolerance_atr_mult


def _falling_edge(state: pd.Series) -> pd.Series:
    """True only on the bar `state` transitions True->False (mirror image
    of _rising_edge, same dtype-upcast fix applied)."""
    filled = state.fillna(False).astype(bool)
    previous = filled.shift(1).fillna(False).astype(bool)
    return previous & ~filled


def _rising_edge(state: pd.Series) -> pd.Series:
    """True only on the bar `state` transitions False->True.

    `.shift(1)` on a bool Series introduces NaN at the first row, which
    silently upcasts the whole Series to object dtype - `.fillna(False)`
    alone does NOT undo that upcast, so a later `~` (bitwise NOT) applies
    Python's integer bitwise-complement to leftover Python bool objects
    (`~False == -1`, `~True == -2`, both truthy) instead of logical
    negation. The explicit `.astype(bool)` after fillna is required to get
    a real boolean dtype back before inverting."""
    filled = state.fillna(False).astype(bool)
    previous = filled.shift(1).fillna(False).astype(bool)
    return filled & ~previous


def _first_occurrence_after(pattern_formed: pd.Series, trigger: pd.Series) -> np.ndarray:
    """Fires only on the FIRST bar `trigger` is true after `pattern_formed`
    becomes true - a fresh pattern-formed bar starts a new "epoch"; a
    trigger before any pattern has formed, or a repeat trigger within the
    same still-active epoch, never (re-)fires. Same vectorized cumsum-
    within-epoch trick engine/derived_indicators.py's _first_retest and
    _first_pullback_after_breakout already use."""
    formed = pattern_formed.fillna(False)
    epoch = formed.cumsum()
    triggered = trigger.fillna(False) & (epoch > 0) & ~formed
    triggered_count_in_epoch = triggered.groupby(epoch).cumsum()
    return (triggered & (triggered_count_in_epoch == 1)).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Double / Triple Top & Bottom
# ---------------------------------------------------------------------------

def double_top_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Two swing highs at a similar level (within `tolerance_atr_mult`
    ATRs of each other), confirmed on the bar the second one completes,
    followed by a break below the most recently confirmed swing low (the
    "neckline") - the classic bearish reversal pattern."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0 = _nth_back_bar_index(swing_high)
    bar_index = pd.Series(np.arange(len(high)), index=high.index)

    formed = (bar_index == bh0) & _similar(lh0, lh1, atr_values, tolerance_atr_mult)
    neckline = _nth_back_level(swing_low, 0)
    breakdown = close < neckline
    return _first_occurrence_after(formed, breakdown)


def double_bottom_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Mirror image of double_top_breakdown."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0 = _nth_back_bar_index(swing_low)
    bar_index = pd.Series(np.arange(len(low)), index=low.index)

    formed = (bar_index == bl0) & _similar(ll0, ll1, atr_values, tolerance_atr_mult)
    neckline = _nth_back_level(swing_high, 0)
    breakout = close > neckline
    return _first_occurrence_after(formed, breakout)


def triple_top_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Three swing highs all at a similar level."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1, lh2 = (_nth_back_level(swing_high, n) for n in (0, 1, 2))
    bh0 = _nth_back_bar_index(swing_high)
    bar_index = pd.Series(np.arange(len(high)), index=high.index)

    formed = (
        (bar_index == bh0)
        & _similar(lh0, lh1, atr_values, tolerance_atr_mult)
        & _similar(lh1, lh2, atr_values, tolerance_atr_mult)
    )
    neckline = _nth_back_level(swing_low, 0)
    breakdown = close < neckline
    return _first_occurrence_after(formed, breakdown)


def triple_bottom_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Mirror image of triple_top_breakdown."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    ll0, ll1, ll2 = (_nth_back_level(swing_low, n) for n in (0, 1, 2))
    bl0 = _nth_back_bar_index(swing_low)
    bar_index = pd.Series(np.arange(len(low)), index=low.index)

    formed = (
        (bar_index == bl0)
        & _similar(ll0, ll1, atr_values, tolerance_atr_mult)
        & _similar(ll1, ll2, atr_values, tolerance_atr_mult)
    )
    neckline = _nth_back_level(swing_high, 0)
    breakout = close > neckline
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Head & Shoulders
# ---------------------------------------------------------------------------

def head_and_shoulders_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, shoulder_tolerance_atr_mult: float = 0.75, head_margin_atr_mult: float = 0.5,
) -> np.ndarray:
    """Three swing highs: a middle "head" clearly above two similar-level
    "shoulders", confirmed as the right shoulder completes. Neckline
    approximated as the most recently confirmed swing low (a flat line,
    unlike the textbook's slanted neckline connecting the two troughs)."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    right_shoulder, head, left_shoulder = (_nth_back_level(swing_high, n) for n in (0, 1, 2))
    bh0 = _nth_back_bar_index(swing_high)
    bar_index = pd.Series(np.arange(len(high)), index=high.index)

    head_margin = atr_values * head_margin_atr_mult
    head_is_highest = (head > right_shoulder + head_margin) & (head > left_shoulder + head_margin)
    shoulders_similar = _similar(right_shoulder, left_shoulder, atr_values, shoulder_tolerance_atr_mult)
    formed = (bar_index == bh0) & head_is_highest & shoulders_similar
    neckline = _nth_back_level(swing_low, 0)
    breakdown = close < neckline
    return _first_occurrence_after(formed, breakdown)


def inverse_head_and_shoulders_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, shoulder_tolerance_atr_mult: float = 0.75, head_margin_atr_mult: float = 0.5,
) -> np.ndarray:
    """Mirror image of head_and_shoulders_breakdown."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    right_shoulder, head, left_shoulder = (_nth_back_level(swing_low, n) for n in (0, 1, 2))
    bl0 = _nth_back_bar_index(swing_low)
    bar_index = pd.Series(np.arange(len(low)), index=low.index)

    head_margin = atr_values * head_margin_atr_mult
    head_is_lowest = (head < right_shoulder - head_margin) & (head < left_shoulder - head_margin)
    shoulders_similar = _similar(right_shoulder, left_shoulder, atr_values, shoulder_tolerance_atr_mult)
    formed = (bar_index == bl0) & head_is_lowest & shoulders_similar
    neckline = _nth_back_level(swing_high, 0)
    breakout = close > neckline
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Triangles & Wedges
# ---------------------------------------------------------------------------

def ascending_triangle_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, flat_tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Flat resistance (last two swing highs similar) + rising support
    (swing lows climbing) - a bullish continuation setup. Fires on the
    breakout above resistance."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)

    state = _similar(lh0, lh1, atr_values, flat_tolerance_atr_mult) & (ll0 > ll1)
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


def descending_triangle_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, flat_tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Mirror image of ascending_triangle_breakout: flat support + falling
    resistance, fires on the breakdown below support."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)

    state = _similar(ll0, ll1, atr_values, flat_tolerance_atr_mult) & (lh0 < lh1)
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


def _symmetrical_triangle_state(high: pd.Series, low: pd.Series, swing_lookback: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    state = (lh0 < lh1) & (ll0 > ll1)
    return state, lh0, ll0


def symmetrical_triangle_breakout_bullish(high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5) -> np.ndarray:
    """Converging swing highs (falling) and swing lows (rising) - fires on
    an upside break out of the apex."""
    state, lh0, _ll0 = _symmetrical_triangle_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


def symmetrical_triangle_breakout_bearish(high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5) -> np.ndarray:
    """Same converging shape as symmetrical_triangle_breakout_bullish, but
    fires on a downside break instead - a symmetrical triangle is
    direction-agnostic until it actually breaks."""
    state, _lh0, ll0 = _symmetrical_triangle_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


def rising_wedge_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5,
) -> np.ndarray:
    """Both swing highs AND swing lows rising, but the channel is
    narrowing (a shrinking high-low spread despite the overall upward
    drift) - a bearish reversal setup, fires on the breakdown below
    support."""
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)

    both_rising = (lh0 > lh1) & (ll0 > ll1)
    narrowing = (lh0 - ll0).abs() < (lh1 - ll1).abs()
    state = both_rising & narrowing
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


def falling_wedge_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5,
) -> np.ndarray:
    """Mirror image of rising_wedge_breakdown: both swing highs and lows
    falling, but narrowing - bullish reversal, fires on breakout above
    resistance."""
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)

    both_falling = (lh0 < lh1) & (ll0 < ll1)
    narrowing = (lh0 - ll0).abs() < (lh1 - ll1).abs()
    state = both_falling & narrowing
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Flags & Pennants: a sharp impulse move, then a brief consolidation, then
# a breakout continuing the impulse's direction. ATR-normalized so the
# impulse/consolidation thresholds are comparable across symbols/timeframes.
# ---------------------------------------------------------------------------

def _flag_or_pennant(
    high: pd.Series, low: pd.Series, close: pd.Series,
    is_bullish: bool, require_narrowing: bool,
    impulse_lookback: int, impulse_atr_mult: float,
    consolidation_window: int, consolidation_atr_mult: float,
) -> np.ndarray:
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)

    if is_bullish:
        impulse = (close - close.shift(impulse_lookback)) / atr_values >= impulse_atr_mult
    else:
        impulse = (close - close.shift(impulse_lookback)) / atr_values <= -impulse_atr_mult
    impulse_recently = impulse.fillna(False).rolling(consolidation_window).max().shift(1).fillna(0) > 0

    consolidation_high = high.rolling(consolidation_window).max()
    consolidation_low = low.rolling(consolidation_window).min()
    consolidation_range = consolidation_high - consolidation_low
    is_narrow = consolidation_range <= atr_values * consolidation_atr_mult

    if require_narrowing:
        half = max(consolidation_window // 2, 1)
        first_half_range = high.rolling(half).max().shift(half) - low.rolling(half).min().shift(half)
        second_half_range = high.rolling(half).max() - low.rolling(half).min()
        is_narrow = is_narrow & (second_half_range < first_half_range)

    state = impulse_recently & is_narrow
    formed = _rising_edge(state)

    # Breakout level must exclude the current bar (shift(1)) - otherwise
    # "close > consolidation_high" can never be true, since the rolling
    # max already includes this same bar's own high (close <= high always).
    # Same no-lookahead convention as derived_indicators.py's
    # _highest_high_level.
    if is_bullish:
        trigger = close > consolidation_high.shift(1)
    else:
        trigger = close < consolidation_low.shift(1)
    return _first_occurrence_after(formed, trigger)


def bull_flag_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    impulse_lookback: int = 10, impulse_atr_mult: float = 3.0,
    consolidation_window: int = 10, consolidation_atr_mult: float = 2.0,
) -> np.ndarray:
    return _flag_or_pennant(
        high, low, close, is_bullish=True, require_narrowing=False,
        impulse_lookback=impulse_lookback, impulse_atr_mult=impulse_atr_mult,
        consolidation_window=consolidation_window, consolidation_atr_mult=consolidation_atr_mult,
    )


def bear_flag_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    impulse_lookback: int = 10, impulse_atr_mult: float = 3.0,
    consolidation_window: int = 10, consolidation_atr_mult: float = 2.0,
) -> np.ndarray:
    return _flag_or_pennant(
        high, low, close, is_bullish=False, require_narrowing=False,
        impulse_lookback=impulse_lookback, impulse_atr_mult=impulse_atr_mult,
        consolidation_window=consolidation_window, consolidation_atr_mult=consolidation_atr_mult,
    )


def bullish_pennant_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    impulse_lookback: int = 10, impulse_atr_mult: float = 3.0,
    consolidation_window: int = 12, consolidation_atr_mult: float = 2.5,
) -> np.ndarray:
    """Same idea as bull_flag_breakout, but additionally requires the
    consolidation's range to be actively NARROWING (triangle-shaped)
    rather than merely staying inside a flat band."""
    return _flag_or_pennant(
        high, low, close, is_bullish=True, require_narrowing=True,
        impulse_lookback=impulse_lookback, impulse_atr_mult=impulse_atr_mult,
        consolidation_window=consolidation_window, consolidation_atr_mult=consolidation_atr_mult,
    )


def bearish_pennant_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    impulse_lookback: int = 10, impulse_atr_mult: float = 3.0,
    consolidation_window: int = 12, consolidation_atr_mult: float = 2.5,
) -> np.ndarray:
    return _flag_or_pennant(
        high, low, close, is_bullish=False, require_narrowing=True,
        impulse_lookback=impulse_lookback, impulse_atr_mult=impulse_atr_mult,
        consolidation_window=consolidation_window, consolidation_atr_mult=consolidation_atr_mult,
    )


# ---------------------------------------------------------------------------
# Range box (consolidation)
# ---------------------------------------------------------------------------

def in_range_box(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, box_atr_mult: float = 2.0) -> np.ndarray:
    """Currently consolidating: the trailing `window`-bar high-low range is
    within `box_atr_mult` ATRs - a state indicator (like bb_squeeze), not a
    one-shot event."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    box_range = high.rolling(window).max() - low.rolling(window).min()
    return (box_range <= atr_values * box_atr_mult).fillna(False).to_numpy(dtype=float)


def range_box_breakout_bullish(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, box_atr_mult: float = 2.0) -> np.ndarray:
    """Fires the FIRST bar close breaks above the box's high after the box
    ends - not necessarily the very next bar (a real breakout can take a
    few bars to actually clear the level), so this uses the same
    fire-once-per-epoch machinery as the other patterns rather than only
    checking a single bar right after the box."""
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    # The box's high must be FROZEN at the level it held while still
    # boxed, not a live rolling max - a plain `high.rolling(window).max()`
    # keeps climbing right along with an ongoing breakout (it re-includes
    # the breakout's own recent highs), so `close > box_high` would rarely
    # or never fire for a gradual breakout. `.where(boxed).ffill()` holds
    # the box's own last-known high steady once boxed turns False.
    box_high = high.rolling(window).max().where(boxed).ffill()
    box_ended = _falling_edge(boxed)
    breakout = close > box_high
    return _first_occurrence_after(box_ended, breakout)


def range_box_breakdown_bearish(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, box_atr_mult: float = 2.0) -> np.ndarray:
    """Mirror image of range_box_breakout_bullish."""
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    box_low = low.rolling(window).min().where(boxed).ffill()
    box_ended = _falling_edge(boxed)
    breakdown = close < box_low
    return _first_occurrence_after(box_ended, breakdown)


# ---------------------------------------------------------------------------
# Trendline break: a single sloped line through the last TWO swing points
# (unlike triangles/wedges, which need two CONVERGING lines) - the most
# basic price-action concept in this module. Support drawn through the
# last two swing lows, resistance through the last two swing highs.
# ---------------------------------------------------------------------------

def uptrend_line_break(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    """Support trendline through the last two swing lows (rising: the more
    recent low is higher than the one before it) - fires the first time
    close breaks below that line's extrapolated current value."""
    swing_low = _swing_low_levels(low, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0, bl1 = _nth_back_bar_index(swing_low, 0), _nth_back_bar_index(swing_low, 1)
    bar_position = pd.Series(np.arange(len(close)), index=close.index)

    valid_uptrend = (ll0 > ll1) & (bl0 > bl1)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (ll0 - ll1) / (bl0 - bl1)
    trendline_value = ll0 + slope * (bar_position - bl0)

    formed = _rising_edge(valid_uptrend)
    breakdown = close < trendline_value
    return _first_occurrence_after(formed, breakdown)


def downtrend_line_break(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    """Mirror image of uptrend_line_break: resistance trendline through the
    last two swing highs (falling), fires when close breaks above it."""
    swing_high = _swing_high_levels(high, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0, bh1 = _nth_back_bar_index(swing_high, 0), _nth_back_bar_index(swing_high, 1)
    bar_position = pd.Series(np.arange(len(close)), index=close.index)

    valid_downtrend = (lh0 < lh1) & (bh0 > bh1)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (lh0 - lh1) / (bh0 - bh1)
    trendline_value = lh0 + slope * (bar_position - bh0)

    formed = _rising_edge(valid_downtrend)
    breakout = close > trendline_value
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Parallel channel: same idea as uptrend/downtrend_line_break, but ALSO
# requires the opposite side (the last two swing highs for an ascending
# channel, swing lows for a descending one) to be roughly the same slope -
# distinguishing a genuine parallel channel from a wedge/triangle, which
# converge instead.
# ---------------------------------------------------------------------------

def ascending_channel_break(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, slope_tolerance_atr_mult: float = 0.02, **p,
) -> np.ndarray:
    """Support (swing lows) and resistance (swing highs) both rising at
    roughly the SAME slope (parallel, not converging) - fires when close
    breaks below the support line (the classic "channel breakdown")."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0, bl1 = _nth_back_bar_index(swing_low, 0), _nth_back_bar_index(swing_low, 1)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0, bh1 = _nth_back_bar_index(swing_high, 0), _nth_back_bar_index(swing_high, 1)
    bar_position = pd.Series(np.arange(len(close)), index=close.index)

    with np.errstate(divide="ignore", invalid="ignore"):
        support_slope = (ll0 - ll1) / (bl0 - bl1)
        resistance_slope = (lh0 - lh1) / (bh0 - bh1)
    both_rising = (ll0 > ll1) & (lh0 > lh1)
    parallel = (support_slope - resistance_slope).abs() <= atr_values * slope_tolerance_atr_mult
    state = both_rising & parallel

    support_value = ll0 + support_slope * (bar_position - bl0)
    formed = _rising_edge(state)
    breakdown = close < support_value
    return _first_occurrence_after(formed, breakdown)


def descending_channel_break(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, slope_tolerance_atr_mult: float = 0.02, **p,
) -> np.ndarray:
    """Mirror image of ascending_channel_break: fires when close breaks
    above the (falling, parallel) resistance line."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0, bl1 = _nth_back_bar_index(swing_low, 0), _nth_back_bar_index(swing_low, 1)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0, bh1 = _nth_back_bar_index(swing_high, 0), _nth_back_bar_index(swing_high, 1)
    bar_position = pd.Series(np.arange(len(close)), index=close.index)

    with np.errstate(divide="ignore", invalid="ignore"):
        support_slope = (ll0 - ll1) / (bl0 - bl1)
        resistance_slope = (lh0 - lh1) / (bh0 - bh1)
    both_falling = (ll0 < ll1) & (lh0 < lh1)
    parallel = (support_slope - resistance_slope).abs() <= atr_values * slope_tolerance_atr_mult
    state = both_falling & parallel

    resistance_value = lh0 + resistance_slope * (bar_position - bh0)
    formed = _rising_edge(state)
    breakout = close > resistance_value
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# False breakout ("fakey"): price breaks outside a consolidation box, then
# closes back inside it within a few bars - the failed-breakout reversal
# setup. Built on in_range_box's existing box-tracking rather than a new
# level detector.
# ---------------------------------------------------------------------------

def _false_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series, is_bullish_reversal: bool,
    window: int, box_atr_mult: float, max_bars_outside: int,
) -> np.ndarray:
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    box_high = high.rolling(window).max().where(boxed).ffill()
    box_low = low.rolling(window).min().where(boxed).ffill()
    box_ended = _falling_edge(boxed)

    if is_bullish_reversal:
        # Broke DOWN out of the box, then closed back inside it -> a
        # bullish reversal (the breakdown was a fake).
        broke_out = close < box_low
    else:
        broke_out = close > box_high

    epoch = box_ended.cumsum()
    broke_out_in_epoch = broke_out.fillna(False) & (epoch > 0) & ~box_ended
    back_inside = (close >= box_low) & (close <= box_high)

    # First bar back inside the box after having broken out, within
    # `max_bars_outside` bars of the break - a return that took longer
    # than that doesn't read as a prompt "fakey" reversal anymore.
    was_outside_recently = broke_out_in_epoch.rolling(max_bars_outside, min_periods=1).max().shift(1).fillna(0) > 0
    reversal_bar = back_inside & was_outside_recently & (epoch > 0)

    reversal_count_in_epoch = reversal_bar.groupby(epoch).cumsum()
    fired = reversal_bar & (reversal_count_in_epoch == 1)
    return fired.fillna(False).to_numpy(dtype=float)


def false_breakout_bullish_reversal(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, box_atr_mult: float = 2.0, max_bars_outside: int = 3, **p,
) -> np.ndarray:
    return _false_breakout(high, low, close, True, window, box_atr_mult, max_bars_outside)


def false_breakout_bearish_reversal(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, box_atr_mult: float = 2.0, max_bars_outside: int = 3, **p,
) -> np.ndarray:
    return _false_breakout(high, low, close, False, window, box_atr_mult, max_bars_outside)


# ---------------------------------------------------------------------------
# Saucer top/bottom (rounding reversal) - a smooth curved extreme rather
# than a sharp spike, detected via a rolling quadratic fit (np.polyfit
# degree 2 per window - O(n*window), same cost class already accepted for
# CCI's rolling mean-absolute-deviation). Concavity alone isn't enough (a
# plain V-shaped reversal also fits a downward/upward parabola loosely) -
# also require the fitted extremum to land roughly in the MIDDLE of the
# window, confirming a genuinely rounded arc rather than a sharp corner
# near one edge.
# ---------------------------------------------------------------------------

def _quadratic_concavity(y: pd.Series, window: int) -> np.ndarray:
    def fit(arr: np.ndarray) -> float:
        x = np.arange(len(arr), dtype=float)
        a, _b, _c = np.polyfit(x, arr, 2)
        return a
    return y.rolling(window).apply(fit, raw=True).to_numpy(dtype=float)


def _extremum_position_fraction(y: pd.Series, window: int, is_max: bool) -> np.ndarray:
    fn = (lambda arr: np.argmax(arr)) if is_max else (lambda arr: np.argmin(arr))
    position = y.rolling(window).apply(fn, raw=True)
    return (position / (window - 1)).to_numpy(dtype=float)


def _rounding_state(close: pd.Series, window: int, is_top: bool) -> np.ndarray:
    concavity = _quadratic_concavity(close, window)
    position_fraction = _extremum_position_fraction(close, window, is_max=is_top)
    concave = concavity < 0 if is_top else concavity > 0
    centered = (position_fraction >= 0.3) & (position_fraction <= 0.7)
    return concave & centered


def saucer_top(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 30, **p) -> np.ndarray:
    """Currently forming a smooth, rounded top - a state indicator (like
    in_range_box), not a one-shot breakout event."""
    return np.nan_to_num(_rounding_state(close, int(window), True), nan=0.0).astype(float)


def saucer_bottom(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 30, **p) -> np.ndarray:
    """Mirror image of saucer_top: a smooth, rounded bottom."""
    return np.nan_to_num(_rounding_state(close, int(window), False), nan=0.0).astype(float)


# ---------------------------------------------------------------------------
# Ascending/Descending Rectangle - same flat-box shape as in_range_box, but
# specifically requires a prior TREND leading into the box (a continuation
# setup) and fires only on the breakout that continues that trend
# direction - distinguishing it from a plain range_box, which is
# direction-agnostic about what came before it.
# ---------------------------------------------------------------------------

def ascending_rectangle_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, box_atr_mult: float = 2.0, trend_lookback: int = 30, **p,
) -> np.ndarray:
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    box_high = high.rolling(window).max().where(boxed).ffill()
    box_ended = _falling_edge(boxed)

    prior_uptrend = close.shift(window) > close.shift(window + trend_lookback)
    formed = box_ended & prior_uptrend.fillna(False)
    breakout = close > box_high
    return _first_occurrence_after(formed, breakout)


def descending_rectangle_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, box_atr_mult: float = 2.0, trend_lookback: int = 30, **p,
) -> np.ndarray:
    """Mirror image of ascending_rectangle_breakout: a box preceded by a
    downtrend, fires on the breakdown continuing it."""
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    box_low = low.rolling(window).min().where(boxed).ffill()
    box_ended = _falling_edge(boxed)

    prior_downtrend = close.shift(window) < close.shift(window + trend_lookback)
    formed = box_ended & prior_downtrend.fillna(False)
    breakdown = close < box_low
    return _first_occurrence_after(formed, breakdown)


# ---------------------------------------------------------------------------
# Broadening Formation (Megaphone) - the mirror image of a symmetrical
# triangle: swing highs rising AND swing lows falling (diverging instead of
# converging). Direction-agnostic until it actually breaks, same as the
# symmetrical triangle above.
# ---------------------------------------------------------------------------

def _broadening_state(high: pd.Series, low: pd.Series, swing_lookback: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    state = (lh0 > lh1) & (ll0 < ll1)
    return state, lh0, ll0


def broadening_formation_breakout_bullish(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    state, lh0, _ll0 = _broadening_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


def broadening_formation_breakout_bearish(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    state, _lh0, ll0 = _broadening_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


# ---------------------------------------------------------------------------
# Diamond Formation - broadening (diverging swing highs/lows) followed by
# narrowing (converging) - the two-phase combination of the broadening
# formation above and a symmetrical triangle, checked via 3 trailing swing
# highs/lows (the earlier pair diverging, the later pair converging).
# ---------------------------------------------------------------------------

def _diamond_state(high: pd.Series, low: pd.Series, swing_lookback: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1, lh2 = (_nth_back_level(swing_high, n) for n in (0, 1, 2))
    ll0, ll1, ll2 = (_nth_back_level(swing_low, n) for n in (0, 1, 2))

    earlier_broadening = (lh1 > lh2) & (ll1 < ll2)
    later_narrowing = (lh0 < lh1) & (ll0 > ll1)
    state = earlier_broadening & later_narrowing
    return state, lh0, ll0


def diamond_formation_breakout_bullish(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    state, lh0, _ll0 = _diamond_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


def diamond_formation_breakout_bearish(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    state, _lh0, ll0 = _diamond_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


# ---------------------------------------------------------------------------
# Cup with Handle - a rounding bottom (the "cup", reusing saucer_bottom's
# quadratic-fit detector) followed by a brief, narrow consolidation near
# the cup's rim (the "handle", reusing in_range_box's ATR-scaled
# narrowness check over a shorter window) - fires on the breakout above
# the handle.
# ---------------------------------------------------------------------------

def cup_with_handle_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    cup_window: int = 40, handle_window: int = 10, handle_atr_mult: float = 1.5, **p,
) -> np.ndarray:
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)

    cup_state = pd.Series(_rounding_state(close, cup_window, is_top=False), index=close.index) > 0
    # Same "did X happen within the trailing window" trick as
    # _flag_or_pennant's `impulse_recently` - the cup must have completed
    # BEFORE the handle (shift(handle_window)), not overlap with it.
    cup_happened_recently = cup_state.shift(handle_window).rolling(cup_window).max().fillna(0) > 0

    handle_range = high.rolling(handle_window).max() - low.rolling(handle_window).min()
    is_handle = handle_range <= atr_values * handle_atr_mult

    state = cup_happened_recently & is_handle
    formed = _rising_edge(state)
    handle_high = high.rolling(handle_window).max().where(is_handle).ffill()
    breakout = close > handle_high
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Equal High / Equal Low (ICT用語の「流動性プール」) - 直近2つの確定スイング
# 高値(安値)がほぼ同じ水準に並んでいる状態。double_top_breakdown等と同じ
# ATR許容誤差の仕組みをそのまま再利用(ネックライン突破の確認は不要、
# 2点が並んだ時点で成立)。
# ---------------------------------------------------------------------------

def equal_high(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.3, **p,
) -> np.ndarray:
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0 = _nth_back_bar_index(swing_high)
    bar_index = pd.Series(np.arange(len(high)), index=high.index)
    formed = (bar_index == bh0) & _similar(lh0, lh1, atr_values, tolerance_atr_mult)
    return formed.fillna(False).to_numpy(dtype=float)


def equal_low(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.3, **p,
) -> np.ndarray:
    """Mirror image of equal_high, for swing lows."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0 = _nth_back_bar_index(swing_low)
    bar_index = pd.Series(np.arange(len(low)), index=low.index)
    formed = (bar_index == bl0) & _similar(ll0, ll1, atr_values, tolerance_atr_mult)
    return formed.fillna(False).to_numpy(dtype=float)
