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
# 非対称ピボット(左右の本数を別々に指定できるスイング高値/安値検出) -
# engine/smc_indicators.py::_detect_swing_highs/_detect_swing_lowsは
# center=Trueの対称窓(左右が必ず同じ本数)しか使えないため、ダブルトップ/
# ボトムの厳密な仕様(ユーザー提供仕様書の「Pivot Left Bars」「Pivot Right
# Bars」)向けにこちらを新設した。BOS/CHoCH等、既存の全指標が使っている
# 対称版(_swing_high_levels等)には一切手を加えていない。
#
# ベクトル化の考え方: 窓[i-left, i+right]内の最大値は、
# 「[i-left, i]の最大値」と「[i, i+right]の最大値」の大きい方に等しい
# (どちらもiを含むので、2つの合成が元の窓全体と一致する) - rolling().max()
# を2回(片方は系列を逆順にしてから)呼ぶだけでよく、バー数ぶんのPythonループ
# が不要。500k本規模のバックテストでも高速。
# ---------------------------------------------------------------------------

def _detect_pivot_highs(high: pd.Series, left: int, right: int) -> pd.Series:
    left_max = high.rolling(window=left + 1).max()
    right_max = high[::-1].rolling(window=right + 1).max()[::-1]
    # skipna=False(デフォルトのskipna=Trueを明示的に無効化) - 配列の末尾
    # right本未満の区間はright_maxがNaN(右側の確認本数が足りず判定不能)に
    # なるが、デフォルトのskipna=Trueだとmax(axis=1)がそのNaNを無視して
    # left_maxだけで判定してしまい、右側が全く確認されていないバーまで
    # 「ピボット高値」と誤判定してしまう(実際に発生: 配列末尾付近の
    # バーがピボットと誤判定され、そのバーの位置+right本を配列の範囲外
    # まで使おうとしてIndexErrorになるまで気づかれなかった)。片方でも
    # NaN(=左右どちらかの確認本数が足りない)ならこのバー自体を判定不能
    # としてNaNのまま伝播させ、is_pivotのfillna(False)で正しく除外する。
    overall_max = pd.concat([left_max, right_max], axis=1).max(axis=1, skipna=False)
    is_pivot = (high == overall_max).fillna(False)
    return _collapse_consecutive_runs(is_pivot)


def _detect_pivot_lows(low: pd.Series, left: int, right: int) -> pd.Series:
    left_min = low.rolling(window=left + 1).min()
    right_min = low[::-1].rolling(window=right + 1).min()[::-1]
    # _detect_pivot_highsと同じ理由でskipna=False。
    overall_min = pd.concat([left_min, right_min], axis=1).min(axis=1, skipna=False)
    is_pivot = (low == overall_min).fillna(False)
    return _collapse_consecutive_runs(is_pivot)


def _collapse_consecutive_runs(flags: pd.Series) -> pd.Series:
    """engine/smc_indicators.py::_collapse_consecutive_runsと同じ(平坦な
    天井/底が窓の等号判定に複数バーで一致してしまうのを、最初の1本だけに
    絞る) - こちらは非対称ピボット専用に複製(smc_indicators.py側は
    プライベート関数でimportして再利用する契約になっていないため)。"""
    return flags & ~flags.shift(1, fill_value=False)


# ---------------------------------------------------------------------------
# Double / Triple Top & Bottom
# ---------------------------------------------------------------------------

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
# 高値(安値)がほぼ同じ水準に並んでいる状態(ネックライン突破の確認は不要、
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


# ---------------------------------------------------------------------------
# Double Top/Bottom (形状判定版・2026-07-25) - "本物のW字/M字か"をより厳密に
# 判定する設計。ユーザーとの設計レビューで固まった仕様をそのまま実装して
# いる:
#
#   ①山1(bullish=Falseなら谷1、以下山1で統一)の検出: 左右pivot_left_bars/
#     pivot_right_bars本より高い(安い)、かつ左右の境界の安値(高値)より
#     ATR×prominence_atr_mult以上高い(低い) - 単なる順位だけでなく、値幅
#     そのものを問う「本物の反発」基準(ユーザー指摘:「0.1Pipsとかでも安け
#     ればそれがピボット安値になっちゃう、それは反発とは言えない」)。
#   ②ネックライン: 山1より後、山2が確定するまでの間に出た、①と同じ基準
#     (逆方向)を満たす本物のピボットのうち一番低い(高い)もの - 新しい
#     ピボットが出るたびに更新されるが、既に選んだネックの探索窓を過ぎて
#     からの後出しピボットは採用しない(そのネックではもう山2を探せない
#     ため無意味)。
#   ③山1→ネックの間隔(interval1)がmin_bars_between_tops〜
#     max_bars_between_topsの範囲内。
#   ④山2の探索窓 = ネックからinterval1×symmetry_ratio_min〜
#     symmetry_ratio_max本の範囲。
#   ⑤⑥山2候補: 窓の中で①と同じ基準(値幅込みの本物のピボット)を満たし、
#     かつ山1との価格差がATR×top_tolerance_atr_mult以内のバーのうち、
#     時系列で最後に見つかったもの(「条件を満たす最新の候補で更新」 -
#     複雑な極値追跡はせず、単純に上書きしていく)。窓の中で山1の水準を
#     許容誤差を超えて突き抜ける値が一度でも出たら、その時点でこの山1
#     候補ごと不成立にする(ユーザー判断:「許容範囲外の安値が出たらそれは
#     もうダブルボトムじゃない」)。
#   ⑦谷(山)の深さ: ネックライン−(山1・山2の平均、絶対値)がATR×
#     min_valley_depth_atr_mult以上・ATR×max_valley_depth_atr_mult以下。
#   ⑧山1前点: ネックが確定した時点で山1より過去に遡り、安値≦
#     (ネック∓余白)≦高値を満たす、山1に一番近い(直近の)バーを探す。
#     この点の価格はそのバー自身のOHLCではなく水準(ネック∓余白)そのもの。
#     この水準は⑪のブレイク判定水準と同じ側にする(ユーザー判断
#     2026-07-27: 以前は符号が逆で、ブレイク水準とは反対側の水準を使って
#     しまっていた)。見つからなければ候補ごと不成立(ユーザー判断)。
#     山1前点→ネックの本数を時間0(interval0)とする(以前は山1前点→山1
#     だったが、⑪の対称性チェックの比較対象を時間1に変更したのに合わせて
#     変更、ユーザー判断2026-07-27)。
#   ⑨値動きのなめらかさ(効率比・終値ベース): 各区間(山1前→山1・山1→ネッ
#     ク・ネック→山2・山2→ブレイク[Confirmed評価時のみ])について、正味の
#     値動き÷総移動距離がefficiency_ratio_min以上(常に判定 - ユーザー判断:
#     「滑らかさも切り離して」)。
#   ⑩直線からの乖離(高値/安値ベース): ⑨と同じ各区間で、区間の両端を結ぶ
#     直線からの最大乖離が、trendline_dev_basis(「atr」または
#     「price_pct」)で選んだ基準以内。
#   ①〜⑧、および⑨⑩のうち山1前→山1・山1→ネック・ネック→山2の3区間が
#     揃った瞬間(confirm_floor、先読み防止のため各ピボットの右側確認が
#     終わるまで遅延させる)が"Detected"。
#   ⑪決着判定(6状態): Rejected(早すぎるブレイク - formed_barからbreakout_
#     deadline_min_bars本未満での突破は無効。以前はinterval1基準の比率
#     だったが、比率だと判定を開始できる時点(pivot_right_bars分の遅延後)
#     で既に猶予を使い切ってしまうケースがあったため、固定本数(デフォルト
#     4本)に変更した/Confirmed(ネックライン突破、かつ時間0(山1前点→ネックの
#     本数)が時間1(ネック→ブレイクの本数、判定バーごとに変わる)×
#     interval_symmetry_ratio_min〜maxの範囲内、かつ山2→ブレイク区間も
#     なめらかさ・直線乖離を満たす - 満たさなければRejected)/
#     Failed After Retest/Failed Before Retest/Expired(山1→山2の本数×
#     breakout_deadline_ratio_max本経過しても決着しなければ期限切れ - 以前は
#     interval1(山1→ネック)基準だったが、山1→山2の本数基準に変更、ユーザー
#     判断2026-07-27)。
#     同一バーでConfirmed・Failed両方の条件が成立した場合はFailedを優先
#     する(ユーザー判断: バックテストエンジン本体のSL/TP同時ヒット時と
#     同じ「悪い方を優先」という既存の全体方針に合わせた)。
#
# 2026-08-02: 山1前のトレンド確認(pre_trend_lookback_bars/pre_trend_atr_mult)
# はユーザー判断で機能ごと削除した(デフォルトが既に無効=0で実質使われて
# いなかったため)。山1・山2の水準許容誤差(旧top_tolerance_pct)とブレイク
# 判定の余白(旧breakout_buffer_pct)は「値幅に対する%」から「値幅に対する
# 倍率」表記に変更(15%→0.15のように、他の*_atr_mult系パラメータと表記を
# 揃えるため)、それぞれtop_tolerance_mult/breakout_buffer_multに改名した。
#
# 上記どの判定にも、実際にそのピボットが「本物」だと確定するpivot_right_bars
# 本の確認遅延を先読み防止として組み込んでいる(_double_top_bottom_stateの
# confirm_floorと同じ考え方)。
# ---------------------------------------------------------------------------

# 2026-07-29: _double_top_bottom_shape_state本体の外側ループ(山1候補×ネック
# 候補の二重ループ)がPythonループのオーバーヘッドで5分足フル期間で2〜3分/
# 銘柄かかっていたため(プロファイリングで残り時間の9割がこの二重ループ自体、
# 中の numpy 呼び出しは1割程度と判明)、Numba(nopython, cache=True)でJIT
# コンパイルされる _shape_state_core に丸ごと移植した。ロジックは全く同じだが、
# Numbaはstr型の分岐やdictの戻り値、None/Optionalを苦手とするため:
#   - "atr"/"price_pct"等の文字列パラメータは呼び出し側でbool(*_is_pct等)に
#     変換してから渡す
#   - None穴埋めのbar変数は-1を「見つからなかった」の番兵にする
#   - 元は「窓内をnumpyでベクトル化して破綻/一致を判定→最後に採用」という
#     書き方だった(それ自体が以前Pythonループを高速化するために導入した
#     ベクトル化 - 2026-07-28)が、Numba化するとバーごとの素直なループの方が
#     速く、かつスカラー/配列どちらの型にもなり得るtol変数(Numbaのnopython
#     モードは1変数1型しか許さない)を避けられるため、バーごとに閾値を都度
#     計算する素直なループに戻した。「窓内に破綻が1つでもあれば候補全体を
#     無効にする」「最初に成立したバーで確定させ、それ以前の近接判定も含めて
#     retestedとする」という意味は全く変えていない(コメントで都度対応関係を
#     示す)。
# 検証: engine/chart_patterns.pyのgit履歴のこの変更のコミット時点で、変更前
# の実装(numpy/純Pythonループ版)の出力と、XAUUSD 5分足(20万本)・USDJPY
# 15分足(全期間58万本)×7種類のパラメータ組み合わせ×bullish/bearishの
# 全パターンで、14個の出力配列すべてがビット単位で完全一致することを確認済み
# (再度大きく手を入れる場合は同じ手順で再検証すること)。
# ---------------------------------------------------------------------------

from numba import njit


@njit(cache=True)
def _shape_spike_ok(price_a, atr_a, n, bar, window_size, is_right, is_high_type, excess_atr_max):
    if excess_atr_max <= 0.0 or window_size <= 0:
        return True
    if is_right:
        lo = bar + 1
        hi = bar + window_size
        if hi > n - 1:
            hi = n - 1
    else:
        lo = bar - window_size
        if lo < 0:
            lo = 0
        hi = bar - 1
    if lo > hi:
        return True
    if is_high_type:
        seg_max = price_a[lo]
        for k in range(lo + 1, hi + 1):
            if price_a[k] > seg_max:
                seg_max = price_a[k]
        excess = price_a[bar] - seg_max
    else:
        seg_min = price_a[lo]
        for k in range(lo + 1, hi + 1):
            if price_a[k] < seg_min:
                seg_min = price_a[k]
        excess = seg_min - price_a[bar]
    return excess <= atr_a[bar] * excess_atr_max


@njit(cache=True)
def _shape_eff_ratio(close_a, start_bar, end_bar):
    if end_bar <= start_bar:
        return 1.0
    net_move = abs(close_a[end_bar] - close_a[start_bar])
    path = 0.0
    for j in range(start_bar, end_bar):
        path += abs(close_a[j + 1] - close_a[j])
    if path <= 0.0:
        return 1.0
    return net_move / path


@njit(cache=True)
def _shape_dev_ok(high_a, low_a, atr_a, start_bar, start_price, end_bar, end_price,
                   dev_is_atr, dev_atr_mult, dev_pct):
    span = end_bar - start_bar
    if span <= 0:
        return True
    if dev_is_atr:
        tol = atr_a[end_bar] * dev_atr_mult
    else:
        tol = abs(end_price - start_price) * dev_pct
    for j in range(start_bar, end_bar + 1):
        line_v = start_price + (end_price - start_price) * (j - start_bar) / span
        d1 = abs(high_a[j] - line_v)
        d2 = abs(low_a[j] - line_v)
        m = d1 if d1 > d2 else d2
        if m > tol:
            return False
    return True


@njit(cache=True)
def _shape_state_core(
    high_a, low_a, close_a, atr_a,
    ext_price_a, neck_price_a,
    ext_flags, neck_flags,
    bullish,
    pivot_confirm_lag,
    pivot_spike_excess_atr_max, pivot_spike_window_ratio,
    min_bars_between_tops, max_bars_between_tops,
    symmetry_ratio_min, symmetry_ratio_max,
    top_tolerance_is_pct, top_tolerance_atr_mult, top_tolerance_mult,
    min_valley_depth_atr_mult, max_valley_depth_atr_mult,
    breakout_buffer_is_pct, breakout_buffer_atr_mult, breakout_buffer_mult,
    efficiency_ratio_min, efficiency_ratio_floor,
    trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct,
    breakout_deadline_is_top1top2, breakout_deadline_min_bars,
    breakout_deadline_ratio_min, breakout_deadline_ratio_max,
    interval_symmetry_ratio_min, interval_symmetry_ratio_max,
    retest_buffer_mult,
    breakout_type_is_close,
):
    n = high_a.shape[0]
    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)
    rejected_a = np.zeros(n, dtype=np.bool_)
    resolve_a = np.zeros(n, dtype=np.bool_)
    failed_after_retest_a = np.zeros(n, dtype=np.bool_)
    failed_before_retest_a = np.zeros(n, dtype=np.bool_)
    expired_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    top1_bar_a = np.full(n, np.nan)
    top2_bar_a = np.full(n, np.nan)
    top1_price_a = np.full(n, np.nan)
    top2_price_a = np.full(n, np.nan)
    neckline_bar_a = np.full(n, np.nan)
    neckline_price_a = np.full(n, np.nan)

    ext_events = np.flatnonzero(ext_flags)
    neck_events = np.flatnonzero(neck_flags)
    n_neck = neck_events.shape[0]

    for ei in range(ext_events.shape[0]):
        top1_true_bar = ext_events[ei]
        top1_price = ext_price_a[top1_true_bar]
        top1_confirm_bar = top1_true_bar + pivot_confirm_lag

        neck_true_bar = -1
        neck_price = 0.0
        neck_confirm_bar = -1

        start_idx = np.searchsorted(neck_events, top1_true_bar + 1, side="left")

        for ki in range(start_idx, n_neck):
            k = neck_events[ki]
            interval1_candidate = k - top1_true_bar
            if max_bars_between_tops > 0 and interval1_candidate > max_bars_between_tops:
                break
            if interval1_candidate < min_bars_between_tops:
                continue
            if neck_true_bar != -1:
                interval1_prev = neck_true_bar - top1_true_bar
                prev_win_end = neck_true_bar + int(np.floor(interval1_prev * symmetry_ratio_max))
                if k > prev_win_end:
                    break
            if bullish:
                is_better = (neck_true_bar == -1) or (neck_price_a[k] > neck_price)
            else:
                is_better = (neck_true_bar == -1) or (neck_price_a[k] < neck_price)
            if not is_better:
                continue
            neck_price = neck_price_a[k]
            neck_true_bar = k
            neck_confirm_bar = neck_true_bar + pivot_confirm_lag

            interval1 = neck_true_bar - top1_true_bar

            top1_right_window = int(round(interval1 * pivot_spike_window_ratio))
            top1_right_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_right_window,
                                             True, not bullish, pivot_spike_excess_atr_max)
            neck_left_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck_true_bar, top1_right_window,
                                            False, bullish, pivot_spike_excess_atr_max)

            win_start = neck_true_bar + int(np.ceil(interval1 * symmetry_ratio_min))
            win_end = neck_true_bar + int(np.floor(interval1 * symmetry_ratio_max))
            if win_end > n - 1:
                win_end = n - 1
            if win_start > win_end:
                continue

            top_tolerance_value = abs(top1_price - neck_price) * top_tolerance_mult

            window_invalidated = False
            top2_true_bar = -1
            top2_price = 0.0
            for j in range(win_start, win_end + 1):
                if top_tolerance_is_pct:
                    tol_j = top_tolerance_value
                else:
                    tol_j = atr_a[j] * top_tolerance_atr_mult
                if bullish:
                    breach = low_a[j] < (top1_price - tol_j)
                else:
                    breach = high_a[j] > (top1_price + tol_j)
                if breach:
                    window_invalidated = True
                    break
                if ext_flags[j] and abs(ext_price_a[j] - top1_price) <= tol_j:
                    top2_true_bar = j
                    top2_price = ext_price_a[j]

            if window_invalidated or top2_true_bar == -1:
                continue
            top2_confirm_bar = top2_true_bar + pivot_confirm_lag

            interval2 = top2_true_bar - neck_true_bar
            top2_left_window = int(round(interval2 * pivot_spike_window_ratio))
            top2_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top2_true_bar, top2_left_window,
                                            False, not bullish, pivot_spike_excess_atr_max)
            neck_right_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck_true_bar, top2_left_window,
                                             True, bullish, pivot_spike_excess_atr_max)
            if not (neck_left_ok or neck_right_ok):
                continue

            avg_extreme = (top1_price + top2_price) / 2.0
            if bullish:
                depth = neck_price - avg_extreme
            else:
                depth = avg_extreme - neck_price
            depth_min = atr_a[top2_true_bar] * min_valley_depth_atr_mult
            if max_valley_depth_atr_mult <= 0.0:
                depth_max = np.inf
            else:
                depth_max = atr_a[top2_true_bar] * max_valley_depth_atr_mult
            if not (depth_min <= depth <= depth_max):
                continue

            breakout_buffer_value = depth * breakout_buffer_mult

            if breakout_buffer_is_pct:
                pre_buf = breakout_buffer_value
            else:
                pre_buf = atr_a[top1_true_bar] * breakout_buffer_atr_mult
            if bullish:
                pre_level = neck_price + pre_buf
            else:
                pre_level = neck_price - pre_buf

            pre_bar = -1
            for j in range(top1_true_bar - 1, -1, -1):
                if low_a[j] <= pre_level <= high_a[j]:
                    pre_bar = j
                    break
            if pre_bar == -1:
                continue

            top1_left_window = int(round((top1_true_bar - pre_bar) * pivot_spike_window_ratio))
            top1_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_left_window,
                                            False, not bullish, pivot_spike_excess_atr_max)
            if not (top1_left_ok or top1_right_ok):
                continue

            interval0 = neck_true_bar - pre_bar

            if bullish:
                seg_min = low_a[pre_bar]
                for j in range(pre_bar + 1, neck_true_bar + 1):
                    if low_a[j] < seg_min:
                        seg_min = low_a[j]
                if top1_price > seg_min:
                    continue
            else:
                seg_max = high_a[pre_bar]
                for j in range(pre_bar + 1, neck_true_bar + 1):
                    if high_a[j] > seg_max:
                        seg_max = high_a[j]
                if top1_price < seg_max:
                    continue

            confirm_floor = top1_confirm_bar
            if neck_confirm_bar > confirm_floor:
                confirm_floor = neck_confirm_bar
            if top2_confirm_bar > confirm_floor:
                confirm_floor = top2_confirm_bar
            if confirm_floor >= n:
                continue

            eff1 = _shape_eff_ratio(close_a, pre_bar, top1_true_bar)
            eff2 = _shape_eff_ratio(close_a, top1_true_bar, neck_true_bar)
            eff3 = _shape_eff_ratio(close_a, neck_true_bar, top2_true_bar)
            legs_ok = (
                eff1 >= efficiency_ratio_floor
                and eff2 >= efficiency_ratio_floor
                and eff3 >= efficiency_ratio_floor
                and (eff1 + eff2 + eff3) / 3.0 >= efficiency_ratio_min
                and _shape_dev_ok(high_a, low_a, atr_a, pre_bar, pre_level, top1_true_bar, top1_price,
                                  trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                and _shape_dev_ok(high_a, low_a, atr_a, top1_true_bar, top1_price, neck_true_bar, neck_price,
                                  trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                and _shape_dev_ok(high_a, low_a, atr_a, neck_true_bar, neck_price, top2_true_bar, top2_price,
                                  trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
            )
            if not legs_ok:
                continue

            formed_bar = confirm_floor
            detected_a[formed_bar] = True

            expire_bars = interval1 * breakout_deadline_ratio_max
            scan_start = top2_true_bar + 1
            if formed_bar > scan_start:
                scan_start = formed_bar
            scan_end = top2_true_bar + int(np.ceil(expire_bars))
            if scan_end > n - 1:
                scan_end = n - 1

            retested = False
            outcome = 4  # expired
            outcome_bar = scan_end

            if scan_start <= scan_end:
                worse_extreme = min(top1_price, top2_price) if bullish else max(top1_price, top2_price)
                seen_near = False
                found = False
                for j in range(scan_start, scan_end + 1):
                    if breakout_buffer_is_pct:
                        buf_j = breakout_buffer_value
                    else:
                        buf_j = atr_a[j] * breakout_buffer_atr_mult

                    if breakout_type_is_close:
                        if bullish:
                            confirm_j = close_a[j] > (neck_price + buf_j)
                            fail_j = close_a[j] < (worse_extreme - buf_j)
                        else:
                            confirm_j = close_a[j] < (neck_price - buf_j)
                            fail_j = close_a[j] > (worse_extreme + buf_j)
                    else:
                        if bullish:
                            confirm_j = high_a[j] > (neck_price + buf_j)
                            fail_j = low_a[j] < (worse_extreme - buf_j)
                        else:
                            confirm_j = low_a[j] < (neck_price - buf_j)
                            fail_j = high_a[j] > (worse_extreme + buf_j)

                    retest_lo = neck_price - buf_j * retest_buffer_mult
                    retest_hi = neck_price + buf_j * retest_buffer_mult
                    near_j = (
                        (retest_lo <= high_a[j] <= retest_hi)
                        or (retest_lo <= low_a[j] <= retest_hi)
                        or (low_a[j] <= retest_lo and high_a[j] >= retest_hi)
                    )
                    seen_near = seen_near or near_j

                    if confirm_j or fail_j:
                        found = True
                        retested = seen_near
                        if fail_j:
                            outcome = 3  # failed
                            outcome_bar = j
                        else:
                            bars_since_formed = j - formed_bar
                            if breakout_deadline_is_top1top2:
                                reject_bars = float(breakout_deadline_min_bars)
                            else:
                                reject_bars = interval1 * breakout_deadline_ratio_min
                            if bars_since_formed < reject_bars:
                                outcome = 1  # rejected
                                outcome_bar = j
                            else:
                                time1 = j - neck_true_bar
                                symmetric_ok = (
                                    time1 * interval_symmetry_ratio_min <= interval0 <= time1 * interval_symmetry_ratio_max
                                )
                                eff4 = _shape_eff_ratio(close_a, top2_true_bar, j)
                                if bullish:
                                    seg_min2 = low_a[neck_true_bar]
                                    for jj in range(neck_true_bar + 1, j + 1):
                                        if low_a[jj] < seg_min2:
                                            seg_min2 = low_a[jj]
                                    no_undercut = top2_price <= seg_min2
                                else:
                                    seg_max2 = high_a[neck_true_bar]
                                    for jj in range(neck_true_bar + 1, j + 1):
                                        if high_a[jj] > seg_max2:
                                            seg_max2 = high_a[jj]
                                    no_undercut = top2_price >= seg_max2

                                top2_right_window = int(round((j - top2_true_bar) * pivot_spike_window_ratio))
                                max_window = j - top2_true_bar
                                if top2_right_window > max_window:
                                    top2_right_window = max_window
                                top2_right_ok = _shape_spike_ok(
                                    ext_price_a, atr_a, n, top2_true_bar, top2_right_window,
                                    True, not bullish, pivot_spike_excess_atr_max,
                                )
                                top2_isolation_ok = top2_left_ok or top2_right_ok

                                if breakout_type_is_close:
                                    end_price_for_dev = close_a[j]
                                else:
                                    end_price_for_dev = high_a[j] if bullish else low_a[j]

                                breakout_leg_ok = (
                                    symmetric_ok
                                    and eff4 >= efficiency_ratio_floor
                                    and eff4 >= efficiency_ratio_min
                                    and no_undercut
                                    and top2_isolation_ok
                                    and _shape_dev_ok(high_a, low_a, atr_a, top2_true_bar, top2_price, j, end_price_for_dev,
                                                       trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                                )
                                if not breakout_leg_ok:
                                    outcome = 1  # rejected
                                    outcome_bar = j
                                else:
                                    outcome = 2  # confirmed
                                    outcome_bar = j
                        break
                if not found:
                    retested = seen_near

            exists_end = outcome_bar
            exists_a[formed_bar: exists_end + 1] = True
            formed_bar_a[formed_bar: exists_end + 1] = formed_bar
            top1_bar_a[formed_bar] = top1_true_bar
            top2_bar_a[formed_bar] = top2_true_bar
            top1_price_a[formed_bar] = top1_price
            top2_price_a[formed_bar] = top2_price
            neckline_bar_a[formed_bar] = neck_true_bar
            neckline_price_a[formed_bar] = neck_price

            if outcome == 1:
                rejected_a[outcome_bar] = True
            elif outcome == 2:
                resolve_a[outcome_bar] = True
            elif outcome == 3:
                if retested:
                    failed_after_retest_a[outcome_bar] = True
                else:
                    failed_before_retest_a[outcome_bar] = True
            else:
                expired_a[outcome_bar] = True

    return (
        exists_a, detected_a, rejected_a, resolve_a, failed_after_retest_a,
        failed_before_retest_a, expired_a, formed_bar_a, top1_bar_a, top2_bar_a,
        top1_price_a, top2_price_a, neckline_bar_a, neckline_price_a,
    )

def _double_top_bottom_shape_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.15,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.075,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_basis: str = "top1_top2",
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_min: float = 0.3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
) -> dict[str, pd.Series]:
    """モジュール冒頭のコメント参照。bullish=Trueでダブルボトム、Falseで
    ダブルトップ(高値/安値・上下を反転させた鏡像)。

    top_tolerance_basis: 山1・山2の水準許容誤差の基準。"atr"は固定ATR倍率
    (パターンの規模に関わらず一定なので、期間が短い/値動きが小さいパターン
    では相対的に緩すぎ、期間が長い/値動きが大きいパターンでは相対的に厳し
    すぎる傾向がある)。"price_pct"は山1→ネックの値幅(山2探索時点で既知の
    量)に対する倍率で、trendline_dev_basisと同じ考え方でパターンの規模に
    応じて許容誤差がスケールする。

    breakout_buffer_basis: ネックライン付近での「本物のブレイク/失敗」判定
    に使う余白の基準。top_tolerance_basisと同じ理由で"atr"は固定ATR倍率、
    "price_pct"は谷の深さ(⑧で計算済み、山1前点探索・ブレイク確定・失敗
    判定・リテスト判定の全てで谷の深さは既知)に対する倍率。谷の深さ自体は
    (min/max_valley_depth_atr_multで判定する)パターンの規模の主指標なので
    ATR倍率のままにしてある(top_toleranceやbreakout_bufferのような「別の
    値幅と比較する許容誤差」ではないため)。

    breakout_deadline_basis: ブレイク猶予(早すぎる/遅すぎるの判定)の方式。
    "top1_top2"(既定、double_top_shape/double_bottom_shapeが使う唯一の方式)
    は、早すぎる判定をbreakout_deadline_min_bars(formed_barからの固定
    本数)、遅すぎる判定を山1→山2の本数×breakout_deadline_ratio_maxで行う。
    "interval1"は2026-07-27に前者へ変更する前の旧方式(早すぎる判定も
    breakout_deadline_ratio_min×山1→ネックの本数(比率)で行う)で、比較用に
    別indicatorとして提供していたdouble_top_shape_v1/double_bottom_shape_v1
    が使っていたが、2026-07-29にそれらのindicator自体を削除したため現在は
    呼び出し元が存在しない(関数自体はまだこの基準を受け付ける)。"""
    n = len(high)
    idx_index = high.index
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_a = _atr_series(df, 14).to_numpy()

    if breakout_type not in ("close", "wick"):
        raise ValueError(f"未対応のbreakout_typeです(close/wickのみ対応): {breakout_type}")
    if trendline_dev_basis not in ("atr", "price_pct"):
        raise ValueError(f"未対応のtrendline_dev_basisです(atr/price_pctのみ対応): {trendline_dev_basis}")

    # 「山」= 高値側の反転点、「谷」= 安値側の反転点。bullish(ダブルボトム)
    # は谷1→ネック(高値側)→谷2、ダブルトップはその鏡像。
    ext_price_a = low_a if bullish else high_a  # 山1/山2側(反転点そのもの)
    neck_price_a = high_a if bullish else low_a  # ネック側

    # ① 値幅込みのピボット判定 - 通常のピボット判定(_detect_pivot_highs/
    # _detect_pivot_lows)に、「左右の境界からATR×prominence_atr_mult以上
    # 離れているか」という値幅の下限を追加でANDする。
    plain_pivot_ext = (
        _detect_pivot_lows(low, pivot_left_bars, pivot_right_bars)
        if bullish
        else _detect_pivot_highs(high, pivot_left_bars, pivot_right_bars)
    ).to_numpy()
    plain_pivot_neck = (
        _detect_pivot_highs(high, pivot_left_bars, pivot_right_bars)
        if bullish
        else _detect_pivot_lows(low, pivot_left_bars, pivot_right_bars)
    ).to_numpy()

    boundary_other_a = high_a if bullish else low_a  # 反転点側の判定に使う「境界」の反対サイド
    left_boundary = pd.Series(boundary_other_a).shift(pivot_left_bars).to_numpy()
    right_boundary = pd.Series(boundary_other_a).shift(-pivot_right_bars).to_numpy()
    prom_thresh = atr_a * prominence_atr_mult
    with np.errstate(invalid="ignore"):
        if bullish:
            prominence_ok_ext = (left_boundary - ext_price_a >= prom_thresh) & (right_boundary - ext_price_a >= prom_thresh)
        else:
            prominence_ok_ext = (ext_price_a - left_boundary >= prom_thresh) & (ext_price_a - right_boundary >= prom_thresh)
    prominence_ok_ext = np.nan_to_num(prominence_ok_ext, nan=0.0).astype(bool)

    neck_boundary_other_a = low_a if bullish else high_a
    left_boundary_neck = pd.Series(neck_boundary_other_a).shift(pivot_left_bars).to_numpy()
    right_boundary_neck = pd.Series(neck_boundary_other_a).shift(-pivot_right_bars).to_numpy()
    with np.errstate(invalid="ignore"):
        if bullish:
            prominence_ok_neck = (neck_price_a - left_boundary_neck >= prom_thresh) & (neck_price_a - right_boundary_neck >= prom_thresh)
        else:
            prominence_ok_neck = (left_boundary_neck - neck_price_a >= prom_thresh) & (right_boundary_neck - neck_price_a >= prom_thresh)
    prominence_ok_neck = np.nan_to_num(prominence_ok_neck, nan=0.0).astype(bool)

    ext_flags = plain_pivot_ext & prominence_ok_ext
    neck_flags = plain_pivot_neck & prominence_ok_neck

    pivot_confirm_lag = pivot_right_bars

    # 二重ループの本体はNumba(nopython, cache=True)でJITコンパイルされる
    # _shape_state_coreに丸ごと移植済み(モジュール冒頭のこの関数の直前を
    # 参照)。文字列パラメータ(*_basis/breakout_type)はbool/int codeに変換
    # してから渡す。
    (
        exists_a, detected_a, rejected_a, resolve_a, failed_after_retest_a,
        failed_before_retest_a, expired_a, formed_bar_a, top1_bar_a, top2_bar_a,
        top1_price_a, top2_price_a, neckline_bar_a, neckline_price_a,
    ) = _shape_state_core(
        high_a, low_a, close_a, atr_a,
        ext_price_a, neck_price_a,
        ext_flags, neck_flags,
        bool(bullish),
        int(pivot_confirm_lag),
        float(pivot_spike_excess_atr_max), float(pivot_spike_window_ratio),
        int(min_bars_between_tops), int(max_bars_between_tops),
        float(symmetry_ratio_min), float(symmetry_ratio_max),
        top_tolerance_basis == "price_pct", float(top_tolerance_atr_mult), float(top_tolerance_mult),
        float(min_valley_depth_atr_mult), float(max_valley_depth_atr_mult),
        breakout_buffer_basis == "price_pct", float(breakout_buffer_atr_mult), float(breakout_buffer_mult),
        float(efficiency_ratio_min), float(efficiency_ratio_floor),
        trendline_dev_basis == "atr", float(trendline_dev_atr_mult), float(trendline_dev_pct),
        breakout_deadline_basis == "top1_top2", int(breakout_deadline_min_bars),
        float(breakout_deadline_ratio_min), float(breakout_deadline_ratio_max),
        float(interval_symmetry_ratio_min), float(interval_symmetry_ratio_max),
        float(retest_buffer_mult),
        breakout_type == "close",
    )

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "detected": pd.Series(detected_a, index=idx_index),
        "rejected": pd.Series(rejected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "failed_after_retest": pd.Series(failed_after_retest_a, index=idx_index),
        "failed_before_retest": pd.Series(failed_before_retest_a, index=idx_index),
        "expired": pd.Series(expired_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "top1_bar": pd.Series(top1_bar_a, index=idx_index),
        "top2_bar": pd.Series(top2_bar_a, index=idx_index),
        "top1_price": pd.Series(top1_price_a, index=idx_index),
        "top2_price": pd.Series(top2_price_a, index=idx_index),
        "neckline_bar": pd.Series(neckline_bar_a, index=idx_index),
        "neckline_price": pd.Series(neckline_price_a, index=idx_index),
    }


_SHAPE_STATE_KEYS = {
    "detected": "detected",
    "rejected": "rejected",
    "confirmed": "confirmed",
    "failed_after_retest": "failed_after_retest",
    "failed_before_retest": "failed_before_retest",
    "expired": "expired",
}


def double_bottom_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.15,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.075,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """ダブルボトム(形状判定版) - モジュール冒頭のコメント参照。
    Detected/Rejected/Confirmed/Failed After Retest/Failed Before Retest/
    Expiredの6状態をstateパラメータで選べる(既存のdouble_bottom/
    double_bottom_pivotとは完全に独立した実装、そちらは一切変更していない)。"""
    result = _double_top_bottom_shape_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        min_bars_between_tops, max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_mult,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_mult,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        retest_buffer_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Triple Top & Bottom (形状判定版) - _shape_state_core(ダブルトップ/ボトム)を
# そのまま踏襲し、「谷2→ネック2→谷3」をもう一段追加しただけの拡張版。
# ユーザーとの設計レビューで決めた分岐点(2026-08-01):
#   - 谷1・谷2・谷3が「並んでいるか」は3点全体(最大値-最小値)で判定する
#     (谷1だけを基準にすると、緩やかな下降/上昇トレンドが混ざった形も
#     通ってしまうため)。谷3探索窓の破綻判定(window invalidated)も同様に
#     「谷1・谷2のうち悪い方」を基準にする。
#   - ブレイク判定に使うネックラインはネック1・ネック2の高い方(ダブルボトム
#     側)/低い方(ダブルトップ側)。既存の double_bottom_shape 内部でも
#     「その時点までで一番良い(高い/低い)ネック候補」を採用するロジック
#     なので一貫性がある。
#   - ネック1とネック2自体の水準が近いか(水平に近いネックラインか)は
#     任意パラメータ neckline_tolerance_pct で追加(0=無効、既定値は緩め)。
#   - 谷3の探索窓・ブレイク猶予・ブレイクバッファは「谷1→ネック1」ではなく
#     直近の間隔・深さ(谷2→ネック2)を基準にする - パターンが進むにつれて
#     スケールが変わっても自然に追従できるため。
# 品質チェック(孤立度・効率比・直線乖離)は5区間(pre→谷1・谷1→ネック1・
# ネック1→谷2・谷2→ネック2・ネック2→谷3)全てに拡張。6状態モデル
# (Detected/Rejected/Confirmed/Failed After Retest/Failed Before Retest/
# Expired)はダブルトップ/ボトムと共通。
# ---------------------------------------------------------------------------

@njit(cache=True)
def _shape_state_core3(
    high_a, low_a, close_a, atr_a,
    ext_price_a, neck_price_a,
    ext_flags, neck_flags,
    bullish,
    pivot_confirm_lag,
    pivot_spike_excess_atr_max, pivot_spike_window_ratio,
    pre_trend_lookback_bars, pre_trend_atr_mult,
    min_bars_between_tops, max_bars_between_tops,
    symmetry_ratio_min, symmetry_ratio_max,
    top_tolerance_is_pct, top_tolerance_atr_mult, top_tolerance_pct,
    neckline_tolerance_pct,
    min_valley_depth_atr_mult, max_valley_depth_atr_mult,
    breakout_buffer_is_pct, breakout_buffer_atr_mult, breakout_buffer_pct,
    efficiency_ratio_min, efficiency_ratio_floor,
    trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct,
    breakout_deadline_min_bars, breakout_deadline_ratio_max,
    interval_symmetry_ratio_min, interval_symmetry_ratio_max,
    retest_buffer_mult,
    breakout_type_is_close,
):
    n = high_a.shape[0]
    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)
    rejected_a = np.zeros(n, dtype=np.bool_)
    resolve_a = np.zeros(n, dtype=np.bool_)
    failed_after_retest_a = np.zeros(n, dtype=np.bool_)
    failed_before_retest_a = np.zeros(n, dtype=np.bool_)
    expired_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    top1_bar_a = np.full(n, np.nan)
    top2_bar_a = np.full(n, np.nan)
    top3_bar_a = np.full(n, np.nan)
    top1_price_a = np.full(n, np.nan)
    top2_price_a = np.full(n, np.nan)
    top3_price_a = np.full(n, np.nan)
    neck1_bar_a = np.full(n, np.nan)
    neck1_price_a = np.full(n, np.nan)
    neck2_bar_a = np.full(n, np.nan)
    neck2_price_a = np.full(n, np.nan)

    ext_events = np.flatnonzero(ext_flags)
    neck_events = np.flatnonzero(neck_flags)
    n_neck = neck_events.shape[0]

    for ei in range(ext_events.shape[0]):
        top1_true_bar = ext_events[ei]
        top1_price = ext_price_a[top1_true_bar]
        top1_confirm_bar = top1_true_bar + pivot_confirm_lag

        if pre_trend_lookback_bars > 0 and pre_trend_atr_mult > 0.0:
            ref_bar = top1_true_bar - pre_trend_lookback_bars
            if ref_bar < 0:
                continue
            trend_thresh = atr_a[top1_true_bar] * pre_trend_atr_mult
            ref_price = ext_price_a[ref_bar]
            if bullish:
                if not (ref_price - top1_price >= trend_thresh):
                    continue
            else:
                if not (top1_price - ref_price >= trend_thresh):
                    continue

        neck1_true_bar = -1
        neck1_price = 0.0
        neck1_confirm_bar = -1

        start_idx = np.searchsorted(neck_events, top1_true_bar + 1, side="left")

        for ki in range(start_idx, n_neck):
            k = neck_events[ki]
            interval1_candidate = k - top1_true_bar
            if max_bars_between_tops > 0 and interval1_candidate > max_bars_between_tops:
                break
            if interval1_candidate < min_bars_between_tops:
                continue
            if neck1_true_bar != -1:
                interval1_prev = neck1_true_bar - top1_true_bar
                prev_win_end = neck1_true_bar + int(np.floor(interval1_prev * symmetry_ratio_max))
                if k > prev_win_end:
                    break
            if bullish:
                is_better = (neck1_true_bar == -1) or (neck_price_a[k] > neck1_price)
            else:
                is_better = (neck1_true_bar == -1) or (neck_price_a[k] < neck1_price)
            if not is_better:
                continue
            neck1_price = neck_price_a[k]
            neck1_true_bar = k
            neck1_confirm_bar = neck1_true_bar + pivot_confirm_lag

            interval1 = neck1_true_bar - top1_true_bar

            top1_right_window = int(round(interval1 * pivot_spike_window_ratio))
            top1_right_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_right_window,
                                             True, not bullish, pivot_spike_excess_atr_max)
            neck1_left_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck1_true_bar, top1_right_window,
                                             False, bullish, pivot_spike_excess_atr_max)

            win_start = neck1_true_bar + int(np.ceil(interval1 * symmetry_ratio_min))
            win_end = neck1_true_bar + int(np.floor(interval1 * symmetry_ratio_max))
            if win_end > n - 1:
                win_end = n - 1
            if win_start > win_end:
                continue

            top_tolerance_pct_value = abs(top1_price - neck1_price) * (top_tolerance_pct / 100.0)

            window_invalidated = False
            top2_true_bar = -1
            top2_price = 0.0
            for j in range(win_start, win_end + 1):
                if top_tolerance_is_pct:
                    tol_j = top_tolerance_pct_value
                else:
                    tol_j = atr_a[j] * top_tolerance_atr_mult
                if bullish:
                    breach = low_a[j] < (top1_price - tol_j)
                else:
                    breach = high_a[j] > (top1_price + tol_j)
                if breach:
                    window_invalidated = True
                    break
                # トリプル版は谷2を「窓内で最初に水準一致した安値」に固定する
                # (ダブル版の_shape_state_coreは最後に一致した安値まで更新
                # し続けるが、それだと窓が谷3にまで届いた時に谷2を素通り
                # して谷3を「谷2」として誤検出してしまう - 谷1・谷2・谷3が
                # 均等に近い間隔で並ぶ本物のトリプルボトムほど起こりやすい)。
                # 窓の残り(谷2発見後)は引き続き破綻(breach)判定のみ続行する。
                if top2_true_bar == -1 and ext_flags[j] and abs(ext_price_a[j] - top1_price) <= tol_j:
                    top2_true_bar = j
                    top2_price = ext_price_a[j]

            if window_invalidated or top2_true_bar == -1:
                continue
            top2_confirm_bar = top2_true_bar + pivot_confirm_lag

            interval2 = top2_true_bar - neck1_true_bar
            top2_left_window = int(round(interval2 * pivot_spike_window_ratio))
            top2_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top2_true_bar, top2_left_window,
                                            False, not bullish, pivot_spike_excess_atr_max)
            neck1_right_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck1_true_bar, top2_left_window,
                                              True, bullish, pivot_spike_excess_atr_max)
            if not (neck1_left_ok or neck1_right_ok):
                continue

            avg_extreme12 = (top1_price + top2_price) / 2.0
            if bullish:
                depth1 = neck1_price - avg_extreme12
            else:
                depth1 = avg_extreme12 - neck1_price
            depth_min1 = atr_a[top2_true_bar] * min_valley_depth_atr_mult
            if max_valley_depth_atr_mult <= 0.0:
                depth_max1 = np.inf
            else:
                depth_max1 = atr_a[top2_true_bar] * max_valley_depth_atr_mult
            if not (depth_min1 <= depth1 <= depth_max1):
                continue

            breakout_buffer_pct_value1 = depth1 * (breakout_buffer_pct / 100.0)
            if breakout_buffer_is_pct:
                pre_buf = breakout_buffer_pct_value1
            else:
                pre_buf = atr_a[top1_true_bar] * breakout_buffer_atr_mult
            if bullish:
                pre_level = neck1_price + pre_buf
            else:
                pre_level = neck1_price - pre_buf

            pre_bar = -1
            for j in range(top1_true_bar - 1, -1, -1):
                if low_a[j] <= pre_level <= high_a[j]:
                    pre_bar = j
                    break
            if pre_bar == -1:
                continue

            top1_left_window = int(round((top1_true_bar - pre_bar) * pivot_spike_window_ratio))
            top1_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_left_window,
                                            False, not bullish, pivot_spike_excess_atr_max)
            if not (top1_left_ok or top1_right_ok):
                continue

            interval0 = neck1_true_bar - pre_bar

            if bullish:
                seg_min = low_a[pre_bar]
                for j in range(pre_bar + 1, neck1_true_bar + 1):
                    if low_a[j] < seg_min:
                        seg_min = low_a[j]
                if top1_price > seg_min:
                    continue
            else:
                seg_max = high_a[pre_bar]
                for j in range(pre_bar + 1, neck1_true_bar + 1):
                    if high_a[j] > seg_max:
                        seg_max = high_a[j]
                if top1_price < seg_max:
                    continue

            # ===== ここから谷2→ネック2→谷3(ダブルトップ/ボトムには無い拡張) =====
            neck2_true_bar = -1
            neck2_price = 0.0
            neck2_confirm_bar = -1

            start_idx2 = np.searchsorted(neck_events, top2_true_bar + 1, side="left")

            for ki2 in range(start_idx2, n_neck):
                k2 = neck_events[ki2]
                interval2n_candidate = k2 - top2_true_bar
                if max_bars_between_tops > 0 and interval2n_candidate > max_bars_between_tops:
                    break
                if interval2n_candidate < min_bars_between_tops:
                    continue
                if neck2_true_bar != -1:
                    interval2n_prev = neck2_true_bar - top2_true_bar
                    prev_win_end2 = neck2_true_bar + int(np.floor(interval2n_prev * symmetry_ratio_max))
                    if k2 > prev_win_end2:
                        break
                if bullish:
                    is_better2 = (neck2_true_bar == -1) or (neck_price_a[k2] > neck2_price)
                else:
                    is_better2 = (neck2_true_bar == -1) or (neck_price_a[k2] < neck2_price)
                if not is_better2:
                    continue
                neck2_price = neck_price_a[k2]
                neck2_true_bar = k2
                neck2_confirm_bar = neck2_true_bar + pivot_confirm_lag

                # ネック1・ネック2自体の水準が近いか(水平に近いネックライン
                # か) - 0以下で無効。
                if neckline_tolerance_pct > 0.0:
                    neck_tol = abs(top1_price - neck1_price) * (neckline_tolerance_pct / 100.0)
                    if abs(neck2_price - neck1_price) > neck_tol:
                        continue

                interval2n = neck2_true_bar - top2_true_bar

                top2_right_window = int(round(interval2n * pivot_spike_window_ratio))
                top2_right_ok = _shape_spike_ok(ext_price_a, atr_a, n, top2_true_bar, top2_right_window,
                                                 True, not bullish, pivot_spike_excess_atr_max)
                neck2_left_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck2_true_bar, top2_right_window,
                                                 False, bullish, pivot_spike_excess_atr_max)
                if not (top2_left_ok or top2_right_ok):
                    continue

                win_start2 = neck2_true_bar + int(np.ceil(interval2n * symmetry_ratio_min))
                win_end2 = neck2_true_bar + int(np.floor(interval2n * symmetry_ratio_max))
                if win_end2 > n - 1:
                    win_end2 = n - 1
                if win_start2 > win_end2:
                    continue

                lo12 = top1_price if top1_price < top2_price else top2_price
                hi12 = top1_price if top1_price > top2_price else top2_price
                worst12 = lo12 if bullish else hi12

                window_invalidated2 = False
                top3_true_bar = -1
                top3_price = 0.0
                for j in range(win_start2, win_end2 + 1):
                    if top_tolerance_is_pct:
                        tol_j = top_tolerance_pct_value
                    else:
                        tol_j = atr_a[j] * top_tolerance_atr_mult
                    if bullish:
                        breach = low_a[j] < (worst12 - tol_j)
                    else:
                        breach = high_a[j] > (worst12 + tol_j)
                    if breach:
                        window_invalidated2 = True
                        break
                    # 谷2側と同じ理由(素通り防止)で谷3も窓内で最初に一致した
                    # 安値に固定する。
                    if top3_true_bar == -1 and ext_flags[j]:
                        cand = ext_price_a[j]
                        lo_all = cand if cand < lo12 else lo12
                        hi_all = cand if cand > hi12 else hi12
                        if (hi_all - lo_all) <= tol_j:
                            top3_true_bar = j
                            top3_price = cand

                if window_invalidated2 or top3_true_bar == -1:
                    continue
                top3_confirm_bar = top3_true_bar + pivot_confirm_lag

                interval3 = top3_true_bar - neck2_true_bar
                top3_left_window = int(round(interval3 * pivot_spike_window_ratio))
                top3_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top3_true_bar, top3_left_window,
                                                False, not bullish, pivot_spike_excess_atr_max)
                neck2_right_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck2_true_bar, top3_left_window,
                                                  True, bullish, pivot_spike_excess_atr_max)
                if not (neck2_left_ok or neck2_right_ok):
                    continue

                avg_extreme23 = (top2_price + top3_price) / 2.0
                if bullish:
                    depth2 = neck2_price - avg_extreme23
                else:
                    depth2 = avg_extreme23 - neck2_price
                depth_min2 = atr_a[top3_true_bar] * min_valley_depth_atr_mult
                if max_valley_depth_atr_mult <= 0.0:
                    depth_max2 = np.inf
                else:
                    depth_max2 = atr_a[top3_true_bar] * max_valley_depth_atr_mult
                if not (depth_min2 <= depth2 <= depth_max2):
                    continue

                confirm_floor = top1_confirm_bar
                if neck1_confirm_bar > confirm_floor:
                    confirm_floor = neck1_confirm_bar
                if top2_confirm_bar > confirm_floor:
                    confirm_floor = top2_confirm_bar
                if neck2_confirm_bar > confirm_floor:
                    confirm_floor = neck2_confirm_bar
                if top3_confirm_bar > confirm_floor:
                    confirm_floor = top3_confirm_bar
                if confirm_floor >= n:
                    continue

                eff1 = _shape_eff_ratio(close_a, pre_bar, top1_true_bar)
                eff2 = _shape_eff_ratio(close_a, top1_true_bar, neck1_true_bar)
                eff3 = _shape_eff_ratio(close_a, neck1_true_bar, top2_true_bar)
                eff4 = _shape_eff_ratio(close_a, top2_true_bar, neck2_true_bar)
                eff5 = _shape_eff_ratio(close_a, neck2_true_bar, top3_true_bar)
                legs_ok = (
                    eff1 >= efficiency_ratio_floor
                    and eff2 >= efficiency_ratio_floor
                    and eff3 >= efficiency_ratio_floor
                    and eff4 >= efficiency_ratio_floor
                    and eff5 >= efficiency_ratio_floor
                    and (eff1 + eff2 + eff3 + eff4 + eff5) / 5.0 >= efficiency_ratio_min
                    and _shape_dev_ok(high_a, low_a, atr_a, pre_bar, pre_level, top1_true_bar, top1_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, top1_true_bar, top1_price, neck1_true_bar, neck1_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, neck1_true_bar, neck1_price, top2_true_bar, top2_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, top2_true_bar, top2_price, neck2_true_bar, neck2_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, neck2_true_bar, neck2_price, top3_true_bar, top3_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                )
                if not legs_ok:
                    continue

                formed_bar = confirm_floor
                detected_a[formed_bar] = True

                # ネックライン=ネック1・ネック2の高い方(bullish)/低い方(not
                # bullish) - 両方の山を上抜けて初めてブレイク成立とみなす
                # 保守的な判定(高い方を超えれば自動的に低い方も超えている)。
                if bullish:
                    neckline_price = neck1_price if neck1_price > neck2_price else neck2_price
                else:
                    neckline_price = neck1_price if neck1_price < neck2_price else neck2_price

                # 猶予・バッファは直近の間隔/深さ(谷2→ネック2)基準 - パターン
                # が進むにつれてスケールが変わっても自然に追従できるため。
                expire_bars = interval2n * breakout_deadline_ratio_max
                scan_start = top3_true_bar + 1
                if formed_bar > scan_start:
                    scan_start = formed_bar
                scan_end = top3_true_bar + int(np.ceil(expire_bars))
                if scan_end > n - 1:
                    scan_end = n - 1

                breakout_buffer_pct_value2 = depth2 * (breakout_buffer_pct / 100.0)

                retested = False
                outcome = 4  # expired
                outcome_bar = scan_end

                if scan_start <= scan_end:
                    worst_extreme = top1_price
                    if bullish:
                        if top2_price < worst_extreme:
                            worst_extreme = top2_price
                        if top3_price < worst_extreme:
                            worst_extreme = top3_price
                    else:
                        if top2_price > worst_extreme:
                            worst_extreme = top2_price
                        if top3_price > worst_extreme:
                            worst_extreme = top3_price

                    seen_near = False
                    found = False
                    for j in range(scan_start, scan_end + 1):
                        if breakout_buffer_is_pct:
                            buf_j = breakout_buffer_pct_value2
                        else:
                            buf_j = atr_a[j] * breakout_buffer_atr_mult

                        if breakout_type_is_close:
                            if bullish:
                                confirm_j = close_a[j] > (neckline_price + buf_j)
                                fail_j = close_a[j] < (worst_extreme - buf_j)
                            else:
                                confirm_j = close_a[j] < (neckline_price - buf_j)
                                fail_j = close_a[j] > (worst_extreme + buf_j)
                        else:
                            if bullish:
                                confirm_j = high_a[j] > (neckline_price + buf_j)
                                fail_j = low_a[j] < (worst_extreme - buf_j)
                            else:
                                confirm_j = low_a[j] < (neckline_price - buf_j)
                                fail_j = high_a[j] > (worst_extreme + buf_j)

                        retest_lo = neckline_price - buf_j * retest_buffer_mult
                        retest_hi = neckline_price + buf_j * retest_buffer_mult
                        near_j = (
                            (retest_lo <= high_a[j] <= retest_hi)
                            or (retest_lo <= low_a[j] <= retest_hi)
                            or (low_a[j] <= retest_lo and high_a[j] >= retest_hi)
                        )
                        seen_near = seen_near or near_j

                        if confirm_j or fail_j:
                            found = True
                            retested = seen_near
                            if fail_j:
                                outcome = 3  # failed
                                outcome_bar = j
                            else:
                                bars_since_formed = j - formed_bar
                                if bars_since_formed < breakout_deadline_min_bars:
                                    outcome = 1  # rejected
                                    outcome_bar = j
                                else:
                                    time1 = j - neck2_true_bar
                                    symmetric_ok = (
                                        time1 * interval_symmetry_ratio_min <= interval0 <= time1 * interval_symmetry_ratio_max
                                    )
                                    eff_breakout = _shape_eff_ratio(close_a, top3_true_bar, j)

                                    if bullish:
                                        seg_min2 = low_a[neck2_true_bar]
                                        for jj in range(neck2_true_bar + 1, j + 1):
                                            if low_a[jj] < seg_min2:
                                                seg_min2 = low_a[jj]
                                        no_undercut = top3_price <= seg_min2
                                    else:
                                        seg_max2 = high_a[neck2_true_bar]
                                        for jj in range(neck2_true_bar + 1, j + 1):
                                            if high_a[jj] > seg_max2:
                                                seg_max2 = high_a[jj]
                                        no_undercut = top3_price >= seg_max2

                                    top3_right_window = int(round((j - top3_true_bar) * pivot_spike_window_ratio))
                                    max_window3 = j - top3_true_bar
                                    if top3_right_window > max_window3:
                                        top3_right_window = max_window3
                                    top3_right_ok = _shape_spike_ok(
                                        ext_price_a, atr_a, n, top3_true_bar, top3_right_window,
                                        True, not bullish, pivot_spike_excess_atr_max,
                                    )
                                    top3_isolation_ok = top3_left_ok or top3_right_ok

                                    if breakout_type_is_close:
                                        end_price_for_dev = close_a[j]
                                    else:
                                        end_price_for_dev = high_a[j] if bullish else low_a[j]

                                    breakout_leg_ok = (
                                        symmetric_ok
                                        and eff_breakout >= efficiency_ratio_floor
                                        and eff_breakout >= efficiency_ratio_min
                                        and no_undercut
                                        and top3_isolation_ok
                                        and _shape_dev_ok(high_a, low_a, atr_a, top3_true_bar, top3_price, j, end_price_for_dev,
                                                           trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                                    )
                                    if not breakout_leg_ok:
                                        outcome = 1  # rejected
                                        outcome_bar = j
                                    else:
                                        outcome = 2  # confirmed
                                        outcome_bar = j
                            break
                    if not found:
                        retested = seen_near

                exists_end = outcome_bar
                exists_a[formed_bar: exists_end + 1] = True
                formed_bar_a[formed_bar: exists_end + 1] = formed_bar
                top1_bar_a[formed_bar] = top1_true_bar
                top2_bar_a[formed_bar] = top2_true_bar
                top3_bar_a[formed_bar] = top3_true_bar
                top1_price_a[formed_bar] = top1_price
                top2_price_a[formed_bar] = top2_price
                top3_price_a[formed_bar] = top3_price
                neck1_bar_a[formed_bar] = neck1_true_bar
                neck1_price_a[formed_bar] = neck1_price
                neck2_bar_a[formed_bar] = neck2_true_bar
                neck2_price_a[formed_bar] = neck2_price

                if outcome == 1:
                    rejected_a[outcome_bar] = True
                elif outcome == 2:
                    resolve_a[outcome_bar] = True
                elif outcome == 3:
                    if retested:
                        failed_after_retest_a[outcome_bar] = True
                    else:
                        failed_before_retest_a[outcome_bar] = True
                else:
                    expired_a[outcome_bar] = True

    return (
        exists_a, detected_a, rejected_a, resolve_a, failed_after_retest_a,
        failed_before_retest_a, expired_a, formed_bar_a,
        top1_bar_a, top2_bar_a, top3_bar_a,
        top1_price_a, top2_price_a, top3_price_a,
        neck1_bar_a, neck1_price_a, neck2_bar_a, neck2_price_a,
    )


def _triple_top_bottom_shape_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    pre_trend_lookback_bars: int = 0,
    pre_trend_atr_mult: float = 0.0,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_pct: float = 15.0,
    neckline_tolerance_pct: float = 30.0,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_pct: float = 7.5,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
) -> dict[str, pd.Series]:
    """モジュール冒頭のコメント参照。bullish=Trueでトリプルボトム、Falseで
    トリプルトップ(高値/安値・上下を反転させた鏡像)。_double_top_bottom_
    shape_stateの「谷1→ネック→谷2」をそのまま使い、「谷2→ネック2→谷3」を
    もう一段追加した拡張版。"""
    n = len(high)
    idx_index = high.index
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_a = _atr_series(df, 14).to_numpy()

    if breakout_type not in ("close", "wick"):
        raise ValueError(f"未対応のbreakout_typeです(close/wickのみ対応): {breakout_type}")
    if trendline_dev_basis not in ("atr", "price_pct"):
        raise ValueError(f"未対応のtrendline_dev_basisです(atr/price_pctのみ対応): {trendline_dev_basis}")

    ext_price_a = low_a if bullish else high_a
    neck_price_a = high_a if bullish else low_a

    plain_pivot_ext = (
        _detect_pivot_lows(low, pivot_left_bars, pivot_right_bars)
        if bullish
        else _detect_pivot_highs(high, pivot_left_bars, pivot_right_bars)
    ).to_numpy()
    plain_pivot_neck = (
        _detect_pivot_highs(high, pivot_left_bars, pivot_right_bars)
        if bullish
        else _detect_pivot_lows(low, pivot_left_bars, pivot_right_bars)
    ).to_numpy()

    boundary_other_a = high_a if bullish else low_a
    left_boundary = pd.Series(boundary_other_a).shift(pivot_left_bars).to_numpy()
    right_boundary = pd.Series(boundary_other_a).shift(-pivot_right_bars).to_numpy()
    prom_thresh = atr_a * prominence_atr_mult
    with np.errstate(invalid="ignore"):
        if bullish:
            prominence_ok_ext = (left_boundary - ext_price_a >= prom_thresh) & (right_boundary - ext_price_a >= prom_thresh)
        else:
            prominence_ok_ext = (ext_price_a - left_boundary >= prom_thresh) & (ext_price_a - right_boundary >= prom_thresh)
    prominence_ok_ext = np.nan_to_num(prominence_ok_ext, nan=0.0).astype(bool)

    neck_boundary_other_a = low_a if bullish else high_a
    left_boundary_neck = pd.Series(neck_boundary_other_a).shift(pivot_left_bars).to_numpy()
    right_boundary_neck = pd.Series(neck_boundary_other_a).shift(-pivot_right_bars).to_numpy()
    with np.errstate(invalid="ignore"):
        if bullish:
            prominence_ok_neck = (neck_price_a - left_boundary_neck >= prom_thresh) & (neck_price_a - right_boundary_neck >= prom_thresh)
        else:
            prominence_ok_neck = (left_boundary_neck - neck_price_a >= prom_thresh) & (right_boundary_neck - neck_price_a >= prom_thresh)
    prominence_ok_neck = np.nan_to_num(prominence_ok_neck, nan=0.0).astype(bool)

    ext_flags = plain_pivot_ext & prominence_ok_ext
    neck_flags = plain_pivot_neck & prominence_ok_neck

    pivot_confirm_lag = pivot_right_bars

    (
        exists_a, detected_a, rejected_a, resolve_a, failed_after_retest_a,
        failed_before_retest_a, expired_a, formed_bar_a,
        top1_bar_a, top2_bar_a, top3_bar_a,
        top1_price_a, top2_price_a, top3_price_a,
        neck1_bar_a, neck1_price_a, neck2_bar_a, neck2_price_a,
    ) = _shape_state_core3(
        high_a, low_a, close_a, atr_a,
        ext_price_a, neck_price_a,
        ext_flags, neck_flags,
        bool(bullish),
        int(pivot_confirm_lag),
        float(pivot_spike_excess_atr_max), float(pivot_spike_window_ratio),
        int(pre_trend_lookback_bars), float(pre_trend_atr_mult),
        int(min_bars_between_tops), int(max_bars_between_tops),
        float(symmetry_ratio_min), float(symmetry_ratio_max),
        top_tolerance_basis == "price_pct", float(top_tolerance_atr_mult), float(top_tolerance_pct),
        float(neckline_tolerance_pct),
        float(min_valley_depth_atr_mult), float(max_valley_depth_atr_mult),
        breakout_buffer_basis == "price_pct", float(breakout_buffer_atr_mult), float(breakout_buffer_pct),
        float(efficiency_ratio_min), float(efficiency_ratio_floor),
        trendline_dev_basis == "atr", float(trendline_dev_atr_mult), float(trendline_dev_pct),
        int(breakout_deadline_min_bars), float(breakout_deadline_ratio_max),
        float(interval_symmetry_ratio_min), float(interval_symmetry_ratio_max),
        float(retest_buffer_mult),
        breakout_type == "close",
    )

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "detected": pd.Series(detected_a, index=idx_index),
        "rejected": pd.Series(rejected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "failed_after_retest": pd.Series(failed_after_retest_a, index=idx_index),
        "failed_before_retest": pd.Series(failed_before_retest_a, index=idx_index),
        "expired": pd.Series(expired_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "top1_bar": pd.Series(top1_bar_a, index=idx_index),
        "top2_bar": pd.Series(top2_bar_a, index=idx_index),
        "top3_bar": pd.Series(top3_bar_a, index=idx_index),
        "top1_price": pd.Series(top1_price_a, index=idx_index),
        "top2_price": pd.Series(top2_price_a, index=idx_index),
        "top3_price": pd.Series(top3_price_a, index=idx_index),
        "neck1_bar": pd.Series(neck1_bar_a, index=idx_index),
        "neck1_price": pd.Series(neck1_price_a, index=idx_index),
        "neck2_bar": pd.Series(neck2_bar_a, index=idx_index),
        "neck2_price": pd.Series(neck2_price_a, index=idx_index),
    }


def triple_bottom_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    pre_trend_lookback_bars: int = 0,
    pre_trend_atr_mult: float = 0.0,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_pct: float = 15.0,
    neckline_tolerance_pct: float = 30.0,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_pct: float = 7.5,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """トリプルボトム(形状判定版) - モジュール冒頭のコメント参照。
    double_bottom_shapeの「谷1→ネック→谷2」に「谷2→ネック2→谷3」を追加した
    拡張版(既存のdouble_bottom_shape/triple_bottom_breakoutとは完全に
    独立した実装、そちらは一切変更していない)。"""
    result = _triple_top_bottom_shape_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        pre_trend_lookback_bars, pre_trend_atr_mult,
        min_bars_between_tops, max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_pct,
        neckline_tolerance_pct,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_pct,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        breakout_deadline_min_bars, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        retest_buffer_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def triple_top_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    pre_trend_lookback_bars: int = 0,
    pre_trend_atr_mult: float = 0.0,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_pct: float = 15.0,
    neckline_tolerance_pct: float = 30.0,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_pct: float = 7.5,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """Mirror image of triple_bottom_shape - トリプルトップ(形状判定版)。"""
    result = _triple_top_bottom_shape_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        pre_trend_lookback_bars, pre_trend_atr_mult,
        min_bars_between_tops, max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_pct,
        neckline_tolerance_pct,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_pct,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        breakout_deadline_min_bars, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        retest_buffer_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def double_top_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.15,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.075,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """Mirror image of double_bottom_shape - ダブルトップ(形状判定版)。"""
    result = _double_top_bottom_shape_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        min_bars_between_tops, max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_mult,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_mult,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        retest_buffer_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


