"""Derived indicators: distance/slope/statistical/event conditions built on
top of the base indicators in engine/indicators.py, engine/technical_indicators.py
and engine/smc_indicators.py.

Every function here takes the full OHLCV `df` plus **params (matching
engine/conditions.py's INDICATOR_REGISTRY calling convention) and returns a
plain np.ndarray[float] - never a pd.Series (a pandas Series slipping into
the numba fast backtest path crashed it once already, see
engine/candlestick_patterns.py's history for why every new indicator module
now converts at its own boundary rather than relying on the registry to
catch it).

Split out from engine/conditions.py (which already wraps the ~100
pre-existing indicators) purely to keep that file's size manageable - same
INDICATOR_REGISTRY still owns the name -> function mapping, this module
just supplies the functions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.indicators import atr as _atr_series
from engine.indicators import ema as _ema_series
from engine.indicators import rsi as _rsi_series
from engine.indicators import sma as _sma_series
from engine.technical_indicators import adx as _adx_raw
from engine.technical_indicators import bollinger_bands as _bollinger_bands
from engine.technical_indicators import daily_reference_levels
from engine.technical_indicators import daily_vwap as _daily_vwap_raw
from engine.technical_indicators import ichimoku as _ichimoku_raw
from engine.technical_indicators import keltner_channels as _keltner_channels_raw
from engine.technical_indicators import macd as _macd_raw
from engine.technical_indicators import supertrend as _supertrend_raw
from engine.smc_indicators import (
    _confirmed_swing_level_series,
    _detect_swing_highs,
    _detect_swing_lows,
    _last_confirmed_level,
    _tracked_zone_level,
    bearish_fvg,
    bearish_order_block,
    bullish_fvg,
    bullish_order_block,
)


# ---------------------------------------------------------------------------
# Shared low-level helpers (level series any category below can build on)
# ---------------------------------------------------------------------------

def _price_series(df: pd.DataFrame, source: str) -> pd.Series:
    return df[source]


def _ema_level(df: pd.DataFrame, length: int) -> pd.Series:
    return _ema_series(df["close"], int(length))


def _sma_level(df: pd.DataFrame, length: int) -> pd.Series:
    return _sma_series(df["close"], int(length))


def _vwap_level(df: pd.DataFrame) -> pd.Series:
    if "volume" not in df.columns:
        raise ValueError(
            "VWAPにはvolume列が必要ですが、この価格データにはありません"
            "(volume列を含むデータソースを使用してください)"
        )
    return _daily_vwap_raw(df["high"], df["low"], df["close"], df["volume"], df["datetime"])


def _supertrend_level(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> pd.Series:
    line, _direction = _supertrend_raw(df["high"], df["low"], df["close"], int(length), float(multiplier))
    return pd.Series(np.asarray(line, dtype=float), index=df.index)


def _rsi_level(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return _rsi_series(df["close"], int(length))


def _atr_level(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return _atr_series(df, int(length))


def _adx_level(df: pd.DataFrame, length: int = 14) -> pd.Series:
    line, _plus_di, _minus_di = _adx_raw(df["high"], df["low"], df["close"], int(length))
    return line


def _macd_line_level(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    line, _signal, _hist = _macd_raw(df["close"], int(fast), int(slow), int(signal))
    return line


def _bollinger_level(df: pd.DataFrame, band: str, period: int = 20, num_std: float = 2.0) -> pd.Series:
    upper, middle, lower = _bollinger_bands(df["close"], int(period), float(num_std))
    return {"upper": upper, "middle": middle, "lower": lower}[band]


def _highest_high_level(df: pd.DataFrame, length: int = 20) -> pd.Series:
    return df["high"].rolling(window=int(length)).max().shift(1)


def _lowest_low_level(df: pd.DataFrame, length: int = 20) -> pd.Series:
    return df["low"].rolling(window=int(length)).min().shift(1)


def _pivot_level(df: pd.DataFrame) -> pd.Series:
    return daily_reference_levels(df, 14)["pivot"]


def _prev_day_high_level(df: pd.DataFrame) -> pd.Series:
    return daily_reference_levels(df, 14)["prev_day_high"]


def _prev_day_low_level(df: pd.DataFrame) -> pd.Series:
    return daily_reference_levels(df, 14)["prev_day_low"]


def _fib_level_series(df: pd.DataFrame, length: int = 20, ratio: float = 0.618) -> pd.Series:
    high = _highest_high_level(df, length)
    low = _lowest_low_level(df, length)
    return high - ratio * (high - low)


def _today_group(df: pd.DataFrame):
    return pd.to_datetime(df["datetime"]).dt.date


def _today_running_high(df: pd.DataFrame) -> pd.Series:
    return df["high"].groupby(_today_group(df)).cummax()


def _today_running_low(df: pd.DataFrame) -> pd.Series:
    return df["low"].groupby(_today_group(df)).cummin()


def _minutes_since_session_open(df: pd.DataFrame, tz: str, open_hour: int) -> np.ndarray:
    """Minutes elapsed since `open_hour`:00 in `tz`'s own local time, reset
    to 0 at each day's session open and held at the elapsed count for the
    rest of that local day (negative before the session has opened yet
    today, matching a plain "hours since midnight minus open_hour" - callers
    filtering with e.g. `>= 0` naturally exclude the pre-open period)."""
    localized = pd.to_datetime(df["datetime"]).dt.tz_localize("Asia/Tokyo").dt.tz_convert(tz)
    minutes_of_day = localized.dt.hour * 60 + localized.dt.minute
    return (minutes_of_day - open_hour * 60).to_numpy(dtype=float)


_DISTANCE_TARGETS = {
    "ema": lambda df, **p: _ema_level(df, p.get("length", 200)),
    "sma": lambda df, **p: _sma_level(df, p.get("length", 200)),
    "vwap": lambda df, **p: _vwap_level(df),
    "supertrend": lambda df, **p: _supertrend_level(df, p.get("length", 10), p.get("multiplier", 3.0)),
    "pivot": lambda df, **p: _pivot_level(df),
    "prev_day_high": lambda df, **p: _prev_day_high_level(df),
    "prev_day_low": lambda df, **p: _prev_day_low_level(df),
    "donchian_upper": lambda df, **p: _highest_high_level(df, p.get("length", 20)),
    "donchian_lower": lambda df, **p: _lowest_low_level(df, p.get("length", 20)),
    "bb_upper": lambda df, **p: _bollinger_level(df, "upper", p.get("period", 20), p.get("num_std", 2.0)),
    "bb_lower": lambda df, **p: _bollinger_level(df, "lower", p.get("period", 20), p.get("num_std", 2.0)),
}


def _make_distance_fn(price_source: str, target_name: str):
    target_fn = _DISTANCE_TARGETS[target_name]

    def _dist(df: pd.DataFrame, **params) -> np.ndarray:
        price = _price_series(df, price_source).to_numpy(dtype=float)
        target = target_fn(df, **params).to_numpy(dtype=float)
        return np.abs(price - target)

    return _dist


# dist_{close,high,low}_{ema,sma,vwap,supertrend,pivot,prev_day_high,
# prev_day_low,donchian_upper,donchian_lower,bb_upper,bb_lower} - 33
# indicators total, generated rather than hand-duplicated 33 times over.
DISTANCE_INDICATORS: dict[str, "callable"] = {}
for _price_source in ("close", "high", "low"):
    for _target_name in _DISTANCE_TARGETS:
        DISTANCE_INDICATORS[f"dist_{_price_source}_{_target_name}"] = _make_distance_fn(_price_source, _target_name)


# ---------------------------------------------------------------------------
# SMC zone distance (Order Block / FVG / BOS) - reuses smc_indicators.py's
# _tracked_zone_level forward-fill pattern (already built for
# breaker_block_bullish/bearish) rather than re-deriving zone tracking.
# ---------------------------------------------------------------------------

def dist_to_order_block_bullish(df: pd.DataFrame, **p) -> np.ndarray:
    """Distance from close to the most recently formed bullish order
    block's zone level (the low of that zone - support side)."""
    ob_flags = pd.Series(bullish_order_block(df["open"], df["close"]), index=df.index)
    zone_low = np.minimum(df["open"], df["close"])
    tracked_low, _epoch = _tracked_zone_level(ob_flags, zone_low)
    return np.abs(df["close"].to_numpy(dtype=float) - tracked_low.to_numpy(dtype=float))


def dist_to_order_block_bearish(df: pd.DataFrame, **p) -> np.ndarray:
    """Distance from close to the most recently formed bearish order
    block's zone level (the high of that zone - resistance side)."""
    ob_flags = pd.Series(bearish_order_block(df["open"], df["close"]), index=df.index)
    zone_high = np.maximum(df["open"], df["close"])
    tracked_high, _epoch = _tracked_zone_level(ob_flags, zone_high)
    return np.abs(df["close"].to_numpy(dtype=float) - tracked_high.to_numpy(dtype=float))


def dist_to_fvg_bullish(df: pd.DataFrame, **p) -> np.ndarray:
    """Distance from close to the nearest edge of the most recent bullish
    FVG gap (the gap between bar i-2's high and bar i's low)."""
    fvg_flags = pd.Series(bullish_fvg(df["high"], df["low"]), index=df.index)
    gap_bottom = df["high"].shift(2)
    tracked_level, _epoch = _tracked_zone_level(fvg_flags, gap_bottom)
    return np.abs(df["close"].to_numpy(dtype=float) - tracked_level.to_numpy(dtype=float))


def dist_to_fvg_bearish(df: pd.DataFrame, **p) -> np.ndarray:
    """Distance from close to the nearest edge of the most recent bearish
    FVG gap (the gap between bar i-2's low and bar i's high)."""
    fvg_flags = pd.Series(bearish_fvg(df["high"], df["low"]), index=df.index)
    gap_top = df["low"].shift(2)
    tracked_level, _epoch = _tracked_zone_level(fvg_flags, gap_top)
    return np.abs(df["close"].to_numpy(dtype=float) - tracked_level.to_numpy(dtype=float))


def dist_to_bos_bullish(df: pd.DataFrame, length: int = 5, **p) -> np.ndarray:
    """Distance from close to the swing high that a fresh upside BOS/CHoCH
    would need to break (the most recently confirmed swing high)."""
    swing_flags = _detect_swing_highs(df["high"], int(length))
    swing_level_series = _confirmed_swing_level_series(swing_flags, df["high"], int(length))
    recent_level = _last_confirmed_level(swing_level_series)
    return np.abs(df["close"].to_numpy(dtype=float) - recent_level.to_numpy(dtype=float))


def dist_to_bos_bearish(df: pd.DataFrame, length: int = 5, **p) -> np.ndarray:
    """Distance from close to the swing low that a fresh downside BOS/CHoCH
    would need to break (the most recently confirmed swing low)."""
    swing_flags = _detect_swing_lows(df["low"], int(length))
    swing_level_series = _confirmed_swing_level_series(swing_flags, df["low"], int(length))
    recent_level = _last_confirmed_level(swing_level_series)
    return np.abs(df["close"].to_numpy(dtype=float) - recent_level.to_numpy(dtype=float))


# ---------------------------------------------------------------------------
# Time-since-session-open (distance in minutes rather than price)
# ---------------------------------------------------------------------------

def minutes_since_london_open(df: pd.DataFrame, **p) -> np.ndarray:
    return _minutes_since_session_open(df, "Europe/London", 7)


def minutes_since_ny_open(df: pd.DataFrame, **p) -> np.ndarray:
    return _minutes_since_session_open(df, "America/New_York", 7)


# ---------------------------------------------------------------------------
# 傾き系: rising/falling/slope/rate-of-change, generic over 7 base series
# ---------------------------------------------------------------------------

_SLOPE_SERIES = {
    "ema": lambda df, **p: _ema_level(df, p.get("length", 200)),
    "vwap": lambda df, **p: _vwap_level(df),
    "supertrend": lambda df, **p: _supertrend_level(df, p.get("length", 10), p.get("multiplier", 3.0)),
    "rsi": lambda df, **p: _rsi_level(df, p.get("length", 14)),
    "adx": lambda df, **p: _adx_level(df, p.get("length", 14)),
    "macd": lambda df, **p: _macd_line_level(df, p.get("fast", 12), p.get("slow", 26), p.get("signal", 9)),
    "atr": lambda df, **p: _atr_level(df, p.get("length", 14)),
}


def _make_rising_fn(series_name: str):
    series_fn = _SLOPE_SERIES[series_name]

    def _rising(df: pd.DataFrame, lookback: int = 1, **params) -> np.ndarray:
        values = series_fn(df, **params).to_numpy(dtype=float)
        prior = np.roll(values, int(lookback))
        prior[: int(lookback)] = np.nan
        return (values > prior).astype(float)

    return _rising


def _make_falling_fn(series_name: str):
    series_fn = _SLOPE_SERIES[series_name]

    def _falling(df: pd.DataFrame, lookback: int = 1, **params) -> np.ndarray:
        values = series_fn(df, **params).to_numpy(dtype=float)
        prior = np.roll(values, int(lookback))
        prior[: int(lookback)] = np.nan
        return (values < prior).astype(float)

    return _falling


SLOPE_INDICATORS: dict[str, "callable"] = {}
for _series_name in _SLOPE_SERIES:
    SLOPE_INDICATORS[f"{_series_name}_rising"] = _make_rising_fn(_series_name)
    SLOPE_INDICATORS[f"{_series_name}_falling"] = _make_falling_fn(_series_name)


def ema_slope_degrees(df: pd.DataFrame, length: int = 200, lookback: int = 5, **p) -> np.ndarray:
    """EMA slope expressed as an angle (degrees), via arctan of the price
    change per bar normalized by ATR(14) - dividing by ATR rather than raw
    price keeps the angle comparable across symbols/timeframes with very
    different pip scales (a raw-price slope would call USDJPY "steeper"
    than EURUSD purely from JPY's larger unit price, not real trend
    strength)."""
    ema_values = _ema_level(df, length).to_numpy(dtype=float)
    prior = np.roll(ema_values, int(lookback))
    prior[: int(lookback)] = np.nan
    atr_values = _atr_level(df, 14).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        normalized_change = (ema_values - prior) / (atr_values * lookback)
    return np.degrees(np.arctan(normalized_change))


def ema_roc(df: pd.DataFrame, length: int = 200, lookback: int = 5, **p) -> np.ndarray:
    """EMA rate of change over `lookback` bars, as a percentage."""
    return _roc(_ema_level(df, length).to_numpy(dtype=float), int(lookback))


def _roc(values: np.ndarray, lookback: int) -> np.ndarray:
    prior = np.roll(values, lookback)
    prior[:lookback] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        return (values - prior) / np.abs(prior) * 100.0


def atr_roc(df: pd.DataFrame, length: int = 14, lookback: int = 1, **p) -> np.ndarray:
    """ATR rate of change over `lookback` bars (default 1 = vs previous
    bar), as a percentage - a sudden spike here is the classic
    "volatility just expanded" signal."""
    return _roc(_atr_level(df, length).to_numpy(dtype=float), int(lookback))


def higher_high(df: pd.DataFrame, lookback: int = 5, **p) -> np.ndarray:
    """A confirmed swing high strictly above the swing high before it
    (classic Dow-theory market structure), fired on the bar the newer
    swing point becomes confirmable."""
    flags = _detect_swing_highs(df["high"], int(lookback))
    level_series = _confirmed_swing_level_series(flags, df["high"], int(lookback))
    sparse = level_series.dropna()
    is_higher = sparse > sparse.shift(1)
    return is_higher.reindex(level_series.index).fillna(False).to_numpy(dtype=float)


def lower_high(df: pd.DataFrame, lookback: int = 5, **p) -> np.ndarray:
    """A confirmed swing high strictly below the swing high before it."""
    flags = _detect_swing_highs(df["high"], int(lookback))
    level_series = _confirmed_swing_level_series(flags, df["high"], int(lookback))
    sparse = level_series.dropna()
    is_lower = sparse < sparse.shift(1)
    return is_lower.reindex(level_series.index).fillna(False).to_numpy(dtype=float)


def higher_low(df: pd.DataFrame, lookback: int = 5, **p) -> np.ndarray:
    """A confirmed swing low strictly above the swing low before it."""
    flags = _detect_swing_lows(df["low"], int(lookback))
    level_series = _confirmed_swing_level_series(flags, df["low"], int(lookback))
    sparse = level_series.dropna()
    is_higher = sparse > sparse.shift(1)
    return is_higher.reindex(level_series.index).fillna(False).to_numpy(dtype=float)


def lower_low(df: pd.DataFrame, lookback: int = 5, **p) -> np.ndarray:
    """A confirmed swing low strictly below the swing low before it."""
    flags = _detect_swing_lows(df["low"], int(lookback))
    level_series = _confirmed_swing_level_series(flags, df["low"], int(lookback))
    sparse = level_series.dropna()
    is_lower = sparse < sparse.shift(1)
    return is_lower.reindex(level_series.index).fillna(False).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# 価格位置: position within a channel/range (0-1 style ratios, or ATR/ADR
# multiples) - one numeric indicator per channel, compared with plain
# operators/thresholds rather than one boolean per named zone.
# ---------------------------------------------------------------------------

def bb_percent_b(df: pd.DataFrame, period: int = 20, num_std: float = 2.0, **p) -> np.ndarray:
    """%B: 0 = at the lower band, 0.5 = at the middle, 1 = at the upper
    band (can exceed [0,1] when price is outside the bands entirely).
    ">= 0.8" is "upper 20% of the band", "<= 0.5" is "below the middle",
    etc - one indicator covers every Bollinger-position condition asked
    for rather than three separately-named booleans."""
    upper = _bollinger_level(df, "upper", period, num_std).to_numpy(dtype=float)
    lower = _bollinger_level(df, "lower", period, num_std).to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (close - lower) / (upper - lower)


def donchian_percent_position(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    """Same 0-1 style position, but within the Donchian channel
    (highest_high/lowest_low over `length` bars)."""
    upper = _highest_high_level(df, length).to_numpy(dtype=float)
    lower = _lowest_low_level(df, length).to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (close - lower) / (upper - lower)


def dist_to_ema_atr_ratio(df: pd.DataFrame, ema_length: int = 200, atr_length: int = 14, **p) -> np.ndarray:
    """|close - EMA| expressed as a multiple of ATR - "EMAからATR1倍以上
    離れている" is this indicator `>= 1.0`, "ATR0.5以内" is `<= 0.5`."""
    dist = np.abs(df["close"].to_numpy(dtype=float) - _ema_level(df, ema_length).to_numpy(dtype=float))
    atr_values = _atr_level(df, atr_length).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return dist / atr_values


def today_range_pct_of_adr(df: pd.DataFrame, adr_period: int = 14, **p) -> np.ndarray:
    """Today's (so far) high-low range as a percentage of ADR - "80%"/
    "100%"/"120%" from the wishlist are just this indicator compared with
    >= 80 / >= 100 / >= 120."""
    today_high = _today_running_high(df).to_numpy(dtype=float)
    today_low = _today_running_low(df).to_numpy(dtype=float)
    adr_values = daily_reference_levels(df, adr_period)["adr"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (today_high - today_low) / adr_values * 100.0


def prev_day_mid(df: pd.DataFrame, **p) -> np.ndarray:
    high = _prev_day_high_level(df).to_numpy(dtype=float)
    low = _prev_day_low_level(df).to_numpy(dtype=float)
    return (high + low) / 2.0


def today_range_position(df: pd.DataFrame, **p) -> np.ndarray:
    """Same 0-1 style position, but within TODAY's own running high/low so
    far (resets every day) - "今日レンジ上位20%" is `>= 0.8`, "下位20%"
    is `<= 0.2`, "中央" is close to `0.5`."""
    today_high = _today_running_high(df).to_numpy(dtype=float)
    today_low = _today_running_low(df).to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (close - today_low) / (today_high - today_low)


def dist_to_fib(df: pd.DataFrame, length: int = 20, ratio: float = 0.618, **p) -> np.ndarray:
    """Distance from close to a Fibonacci retracement level - "38.2/61.8/
    78.6付近" is `ratio=0.382/0.618/0.786` with this indicator `<=` some
    small tolerance."""
    level = _fib_level_series(df, length, ratio).to_numpy(dtype=float)
    return np.abs(df["close"].to_numpy(dtype=float) - level)


# ---------------------------------------------------------------------------
# 統計系: rolling means/std/percentile-rank/z-score/extremes
# ---------------------------------------------------------------------------

def rolling_mean_high(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return df["high"].rolling(window=int(length)).mean().to_numpy(dtype=float)


def rolling_mean_low(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return df["low"].rolling(window=int(length)).mean().to_numpy(dtype=float)


def _body_size(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _upper_wick_size(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df[["close", "open"]].max(axis=1)


def _lower_wick_size(df: pd.DataFrame) -> pd.Series:
    return df[["close", "open"]].min(axis=1) - df["low"]


def avg_body_size(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return _body_size(df).rolling(window=int(length)).mean().to_numpy(dtype=float)


def max_body_size(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return _body_size(df).rolling(window=int(length)).max().to_numpy(dtype=float)


def min_body_size(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return _body_size(df).rolling(window=int(length)).min().to_numpy(dtype=float)


def body_size_std(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return _body_size(df).rolling(window=int(length)).std().to_numpy(dtype=float)


def avg_upper_wick(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return _upper_wick_size(df).rolling(window=int(length)).mean().to_numpy(dtype=float)


def avg_lower_wick(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return _lower_wick_size(df).rolling(window=int(length)).mean().to_numpy(dtype=float)


def atr_rolling_mean(df: pd.DataFrame, atr_length: int = 14, window: int = 20, **p) -> np.ndarray:
    return _atr_level(df, atr_length).rolling(window=int(window)).mean().to_numpy(dtype=float)


def atr_deviation(df: pd.DataFrame, atr_length: int = 14, window: int = 20, **p) -> np.ndarray:
    atr_series = _atr_level(df, atr_length)
    return (atr_series - atr_series.rolling(window=int(window)).mean()).to_numpy(dtype=float)


def close_rolling_std(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return df["close"].rolling(window=int(length)).std().to_numpy(dtype=float)


def rsi_rolling_mean(df: pd.DataFrame, rsi_length: int = 14, window: int = 20, **p) -> np.ndarray:
    return _rsi_level(df, rsi_length).rolling(window=int(window)).mean().to_numpy(dtype=float)


def rsi_deviation(df: pd.DataFrame, rsi_length: int = 14, window: int = 20, **p) -> np.ndarray:
    rsi_series = _rsi_level(df, rsi_length)
    return (rsi_series - rsi_series.rolling(window=int(window)).mean()).to_numpy(dtype=float)


def adx_rolling_mean(df: pd.DataFrame, adx_length: int = 14, window: int = 20, **p) -> np.ndarray:
    return _adx_level(df, adx_length).rolling(window=int(window)).mean().to_numpy(dtype=float)


def macd_rolling_mean(df: pd.DataFrame, window: int = 20, **p) -> np.ndarray:
    return _macd_line_level(df).rolling(window=int(window)).mean().to_numpy(dtype=float)


def _rolling_percentile_rank(series: pd.Series, window: int) -> np.ndarray:
    """What fraction (0-100) of the trailing `window` bars (including the
    current one) the current value is greater than or equal to. Uses
    pandas' rolling().rank(pct=True) (vectorized C implementation, not a
    per-row Python callback) - important at this project's row counts
    (500k+ bars) per the performance priorities already established this
    session for the backtest hot path."""
    ranks = series.rolling(window=window).rank(pct=True)
    return (ranks * 100.0).to_numpy(dtype=float)


def percentile_rank_rsi(df: pd.DataFrame, rsi_length: int = 14, window: int = 100, **p) -> np.ndarray:
    return _rolling_percentile_rank(_rsi_level(df, rsi_length), int(window))


def percentile_rank_atr(df: pd.DataFrame, atr_length: int = 14, window: int = 200, **p) -> np.ndarray:
    return _rolling_percentile_rank(_atr_level(df, atr_length), int(window))


def percentile_rank_body(df: pd.DataFrame, window: int = 50, **p) -> np.ndarray:
    return _rolling_percentile_rank(_body_size(df), int(window))


def _zscore(series: pd.Series, window: int) -> np.ndarray:
    mean = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    with np.errstate(divide="ignore", invalid="ignore"):
        return ((series - mean) / std).to_numpy(dtype=float)


def zscore_close(df: pd.DataFrame, window: int = 20, **p) -> np.ndarray:
    return _zscore(df["close"], int(window))


def zscore_rsi(df: pd.DataFrame, rsi_length: int = 14, window: int = 20, **p) -> np.ndarray:
    return _zscore(_rsi_level(df, rsi_length), int(window))


def zscore_atr(df: pd.DataFrame, atr_length: int = 14, window: int = 20, **p) -> np.ndarray:
    return _zscore(_atr_level(df, atr_length), int(window))


def is_max_body_of_n(df: pd.DataFrame, window: int = 100, **p) -> np.ndarray:
    body = _body_size(df)
    return (body == body.rolling(window=int(window)).max()).to_numpy(dtype=float)


def is_min_atr_of_n(df: pd.DataFrame, atr_length: int = 14, window: int = 50, **p) -> np.ndarray:
    atr_series = _atr_level(df, atr_length)
    return (atr_series == atr_series.rolling(window=int(window)).min()).to_numpy(dtype=float)


def is_max_rsi_of_n(df: pd.DataFrame, rsi_length: int = 14, window: int = 200, **p) -> np.ndarray:
    rsi_series = _rsi_level(df, rsi_length)
    return (rsi_series == rsi_series.rolling(window=int(window)).max()).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# エントリー専用イベント: Bollinger squeeze/expansion, SuperTrend flips,
# today's new high/low. (Everything else on the wishlist - golden/dead
# cross, Donchian/BB breaks, prev-day/pivot/fib breaks, SMC occurrences,
# session open/close - is already expressible with existing indicators
# via crosses_above/crosses_below, so isn't duplicated here.)
# ---------------------------------------------------------------------------

def bb_width(df: pd.DataFrame, period: int = 20, num_std: float = 2.0, **p) -> np.ndarray:
    upper = _bollinger_level(df, "upper", period, num_std).to_numpy(dtype=float)
    lower = _bollinger_level(df, "lower", period, num_std).to_numpy(dtype=float)
    return upper - lower


def bb_squeeze(df: pd.DataFrame, period: int = 20, num_std: float = 2.0, window: int = 100, percentile: float = 10.0, **p) -> np.ndarray:
    """True when the current Bollinger width sits at/below its own
    trailing `percentile`-th percentile (default: bottom 10% of the last
    100 bars' widths) - "band squeeze" relative to its own recent history,
    since an absolute width threshold wouldn't be comparable across
    symbols/timeframes."""
    width = pd.Series(bb_width(df, period, num_std), index=df.index)
    rank = width.rolling(window=int(window)).rank(pct=True) * 100.0
    return (rank <= percentile).to_numpy(dtype=float)


def bb_expansion(df: pd.DataFrame, period: int = 20, num_std: float = 2.0, window: int = 100, percentile: float = 10.0, **p) -> np.ndarray:
    """The bar after a squeeze where width has just started widening again
    - squeeze was true on the PREVIOUS bar (avoids requiring the squeeze
    condition and the rising condition on the very same bar, which would
    exclude the actual breakout bar since width typically stops shrinking
    a bar before it visibly expands)."""
    width = pd.Series(bb_width(df, period, num_std), index=df.index)
    rank = width.rolling(window=int(window)).rank(pct=True) * 100.0
    was_squeezed = (rank <= percentile).shift(1).fillna(False)
    now_rising = width > width.shift(1)
    return (was_squeezed & now_rising).to_numpy(dtype=float)


def supertrend_flip_bullish(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0, **p) -> np.ndarray:
    _line, direction = _supertrend_raw(df["high"], df["low"], df["close"], int(length), float(multiplier))
    direction = np.asarray(direction, dtype=float)
    prev = np.roll(direction, 1)
    prev[0] = np.nan
    return ((direction == 1) & (prev == -1)).astype(float)


def supertrend_flip_bearish(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0, **p) -> np.ndarray:
    _line, direction = _supertrend_raw(df["high"], df["low"], df["close"], int(length), float(multiplier))
    direction = np.asarray(direction, dtype=float)
    prev = np.roll(direction, 1)
    prev[0] = np.nan
    return ((direction == -1) & (prev == 1)).astype(float)


def today_new_high(df: pd.DataFrame, **p) -> np.ndarray:
    """This bar's high exceeds every prior bar's high SO FAR TODAY (the
    running high as of the previous bar, reset at each day's first bar -
    a day's very first bar never counts as "new" since there's nothing
    earlier that day to exceed)."""
    prev_running_high = df.groupby(_today_group(df))["high"].transform(lambda s: s.cummax().shift(1))
    return (df["high"] > prev_running_high).fillna(False).to_numpy(dtype=float)


def today_new_low(df: pd.DataFrame, **p) -> np.ndarray:
    prev_running_low = df.groupby(_today_group(df))["low"].transform(lambda s: s.cummin().shift(1))
    return (df["low"] < prev_running_low).fillna(False).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# 一瞬だけ起きる変化
# ---------------------------------------------------------------------------

def rsi_divergence_bearish(df: pd.DataFrame, length: int = 20, rsi_length: int = 14, **p) -> np.ndarray:
    """Simplified proxy, NOT true swing-based divergence: fires when price
    makes a fresh `length`-bar high (close crosses above its own trailing
    highest_high) while RSI, at that same moment, is LOWER than RSI was
    the last time that trailing-high was set - i.e. price pushed higher
    but momentum didn't confirm it. A textbook divergence detector would
    compare confirmed swing highs directly (like smc_indicators.py's BOS/
    CHoCH does for price structure); this rolling-window proxy is far
    simpler to compute correctly and vectorize, at the cost of being
    fuzzier about exactly which two peaks are being compared."""
    high = df["high"]
    close = df["close"]
    rsi_series = _rsi_level(df, rsi_length)
    rolling_high = high.rolling(window=int(length)).max()
    made_new_high = close > rolling_high.shift(1)
    rsi_at_prior_high_window = rsi_series.rolling(window=int(length)).max().shift(1)
    return (made_new_high & (rsi_series < rsi_at_prior_high_window)).fillna(False).to_numpy(dtype=float)


def rsi_divergence_bullish(df: pd.DataFrame, length: int = 20, rsi_length: int = 14, **p) -> np.ndarray:
    """Mirror image of rsi_divergence_bearish: price makes a fresh
    `length`-bar low while RSI is HIGHER than it was the last time that
    trailing low was set."""
    low = df["low"]
    close = df["close"]
    rsi_series = _rsi_level(df, rsi_length)
    rolling_low = low.rolling(window=int(length)).min()
    made_new_low = close < rolling_low.shift(1)
    rsi_at_prior_low_window = rsi_series.rolling(window=int(length)).min().shift(1)
    return (made_new_low & (rsi_series > rsi_at_prior_low_window)).fillna(False).to_numpy(dtype=float)


def macd_divergence_bearish(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    """Same simplified rolling-window proxy as rsi_divergence_bearish,
    using the MACD line instead of RSI."""
    high = df["high"]
    close = df["close"]
    macd_line = _macd_line_level(df)
    rolling_high = high.rolling(window=int(length)).max()
    made_new_high = close > rolling_high.shift(1)
    macd_at_prior_high_window = macd_line.rolling(window=int(length)).max().shift(1)
    return (made_new_high & (macd_line < macd_at_prior_high_window)).fillna(False).to_numpy(dtype=float)


def macd_divergence_bullish(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    low = df["low"]
    close = df["close"]
    macd_line = _macd_line_level(df)
    rolling_low = low.rolling(window=int(length)).min()
    made_new_low = close < rolling_low.shift(1)
    macd_at_prior_low_window = macd_line.rolling(window=int(length)).min().shift(1)
    return (made_new_low & (macd_line > macd_at_prior_low_window)).fillna(False).to_numpy(dtype=float)


def _ema_perfect_order_state(
    df: pd.DataFrame, length_1: int, length_2: int, length_3: int, length_4: int
) -> tuple[pd.Series, pd.Series]:
    e1 = _ema_level(df, length_1)
    e2 = _ema_level(df, length_2)
    e3 = _ema_level(df, length_3)
    e4 = _ema_level(df, length_4)
    bullish = (e1 > e2) & (e2 > e3) & (e3 > e4)
    bearish = (e1 < e2) & (e2 < e3) & (e3 < e4)
    return bullish, bearish


def ema_perfect_order_bullish(
    df: pd.DataFrame, length_1: int = 20, length_2: int = 50, length_3: int = 100, length_4: int = 200, **p
) -> np.ndarray:
    """4 EMAs (fastest to slowest) stacked in descending order
    (length_1 > length_2 > length_3 > length_4) - the classic "perfect
    order" trend-strength filter."""
    bullish, _bearish = _ema_perfect_order_state(df, length_1, length_2, length_3, length_4)
    return bullish.to_numpy(dtype=float)


def ema_perfect_order_bearish(
    df: pd.DataFrame, length_1: int = 20, length_2: int = 50, length_3: int = 100, length_4: int = 200, **p
) -> np.ndarray:
    _bullish, bearish = _ema_perfect_order_state(df, length_1, length_2, length_3, length_4)
    return bearish.to_numpy(dtype=float)


def ema_perfect_order_broken_bullish(
    df: pd.DataFrame, length_1: int = 20, length_2: int = 50, length_3: int = 100, length_4: int = 200, **p
) -> np.ndarray:
    """The bullish perfect order held on the PREVIOUS bar but no longer
    holds now - the moment the stack breaks, not merely "not currently
    stacked" (which would also be true e.g. before it was ever established)."""
    bullish, _bearish = _ema_perfect_order_state(df, length_1, length_2, length_3, length_4)
    was_bullish = bullish.shift(1).fillna(False)
    return (was_bullish & ~bullish).to_numpy(dtype=float)


def ema_perfect_order_broken_bearish(
    df: pd.DataFrame, length_1: int = 20, length_2: int = 50, length_3: int = 100, length_4: int = 200, **p
) -> np.ndarray:
    _bullish, bearish = _ema_perfect_order_state(df, length_1, length_2, length_3, length_4)
    was_bearish = bearish.shift(1).fillna(False)
    return (was_bearish & ~bearish).to_numpy(dtype=float)


def _first_pullback_after_breakout(df: pd.DataFrame, length: int, is_bullish: bool) -> np.ndarray:
    """After an N-bar breakout (close breaks the trailing N-bar high/low),
    the first subsequent bar that closes back against the breakout
    direction (the first "give-back" bar) - a common "wait for the first
    pullback before entering" filter. Vectorized via a cumulative-group
    trick: each breakout starts a new "epoch"; within an epoch, flag only
    the first bar where a pullback bar has occurred (cumsum of pullback
    flags == 1 at, and only at, that first occurrence)."""
    close = df["close"]
    if is_bullish:
        breakout = close > _highest_high_level(df, length)
        pullback_bar = close < close.shift(1)
    else:
        breakout = close < _lowest_low_level(df, length)
        pullback_bar = close > close.shift(1)

    breakout = breakout.fillna(False)
    epoch = breakout.cumsum()
    pullback_bar = pullback_bar.fillna(False) & (epoch > 0) & ~breakout
    pullback_count_in_epoch = pullback_bar.groupby(epoch).cumsum()
    is_first_pullback = pullback_bar & (pullback_count_in_epoch == 1)
    return is_first_pullback.to_numpy(dtype=float)


def first_pullback_after_breakout_bullish(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return _first_pullback_after_breakout(df, int(length), is_bullish=True)


def first_pullback_after_breakout_bearish(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    return _first_pullback_after_breakout(df, int(length), is_bullish=False)


def _first_retest(zone_flags: pd.Series, touched: pd.Series) -> np.ndarray:
    """Given a boolean "zone just formed" series and a boolean "price is
    touching the most recently formed zone right now" series (already
    computed against the tracked zone level), flags only the FIRST bar
    after formation where the touch happens - same cumsum-within-epoch
    trick as _first_pullback_after_breakout."""
    epoch = zone_flags.cumsum()
    touched = touched.fillna(False) & (epoch > 0) & ~zone_flags
    touch_count_in_epoch = touched.groupby(epoch).cumsum()
    return (touched & (touch_count_in_epoch == 1)).to_numpy(dtype=float)


def fvg_first_retest_bullish(df: pd.DataFrame, **p) -> np.ndarray:
    fvg_flags = pd.Series(bullish_fvg(df["high"], df["low"]), index=df.index)
    gap_bottom = df["high"].shift(2)
    tracked_level, _epoch = _tracked_zone_level(fvg_flags, gap_bottom)
    touched = df["low"] <= tracked_level
    return _first_retest(fvg_flags, touched)


def fvg_first_retest_bearish(df: pd.DataFrame, **p) -> np.ndarray:
    fvg_flags = pd.Series(bearish_fvg(df["high"], df["low"]), index=df.index)
    gap_top = df["low"].shift(2)
    tracked_level, _epoch = _tracked_zone_level(fvg_flags, gap_top)
    touched = df["high"] >= tracked_level
    return _first_retest(fvg_flags, touched)


def order_block_first_retest_bullish(df: pd.DataFrame, **p) -> np.ndarray:
    ob_flags = pd.Series(bullish_order_block(df["open"], df["close"]), index=df.index)
    zone_low = np.minimum(df["open"], df["close"])
    tracked_low, _epoch = _tracked_zone_level(ob_flags, zone_low)
    touched = df["low"] <= tracked_low
    return _first_retest(ob_flags, touched)


def order_block_first_retest_bearish(df: pd.DataFrame, **p) -> np.ndarray:
    ob_flags = pd.Series(bearish_order_block(df["open"], df["close"]), index=df.index)
    zone_high = np.maximum(df["open"], df["close"])
    tracked_high, _epoch = _tracked_zone_level(ob_flags, zone_high)
    touched = df["high"] >= tracked_high
    return _first_retest(ob_flags, touched)


# ---------------------------------------------------------------------------
# TTM Squeeze: Bollinger Bands nested INSIDE Keltner Channels - a real
# volatility-comparison squeeze (John Carter's original definition), unlike
# bb_squeeze/bb_expansion above (which only compare BB width against its
# OWN trailing percentile). Kept as separate indicators rather than
# replacing bb_squeeze - the percentile version is still useful on its own
# and existing generated strategies/tests already reference it by name.
# ---------------------------------------------------------------------------

def ttm_squeeze(
    df: pd.DataFrame, bb_period: int = 20, bb_num_std: float = 2.0,
    kc_period: int = 20, kc_atr_period: int = 10, kc_multiplier: float = 1.5, **p,
) -> np.ndarray:
    bb_upper = _bollinger_level(df, "upper", bb_period, bb_num_std)
    bb_lower = _bollinger_level(df, "lower", bb_period, bb_num_std)
    kc_upper, _kc_middle, kc_lower = _keltner_channels_raw(
        df["high"], df["low"], df["close"], kc_period, kc_atr_period, kc_multiplier
    )
    return ((bb_upper < kc_upper) & (bb_lower > kc_lower)).to_numpy(dtype=float)


def ttm_squeeze_release(
    df: pd.DataFrame, bb_period: int = 20, bb_num_std: float = 2.0,
    kc_period: int = 20, kc_atr_period: int = 10, kc_multiplier: float = 1.5, **p,
) -> np.ndarray:
    """The bar the squeeze just ended (was squeezed on the previous bar,
    isn't now) - the classic "squeeze fired" entry trigger. Uses
    `shift(1, fill_value=False)` rather than `.shift(1).fillna(False)` -
    the latter silently upcasts a bool Series to object dtype, which broke
    `~` (bitwise NOT) in engine/chart_patterns.py's first version of this
    exact pattern (see that module's _rising_edge/_falling_edge for the
    full story) - `~squeeze` here is safe regardless, since it inverts the
    UNSHIFTED, still-genuinely-bool `squeeze` series, not the shifted one."""
    squeeze = pd.Series(
        ttm_squeeze(df, bb_period, bb_num_std, kc_period, kc_atr_period, kc_multiplier) > 0, index=df.index
    )
    was_squeezed = squeeze.shift(1, fill_value=False)
    return (was_squeezed & ~squeeze).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Ichimoku completion: engine/conditions.py already registers the 4 raw
# lines (tenkan/kijun/senkou_a/senkou_b - senkou_a/b already shifted
# forward by kijun_period at the source, see technical_indicators.py::
# ichimoku's docstring, so they're causally safe to compare against price
# as-is). These add the derived signals that raw line values alone don't
# give you.
# ---------------------------------------------------------------------------

def ichimoku_price_vs_cloud(
    df: pd.DataFrame, tenkan_period: int = 9, kijun_period: int = 26, senkou_b_period: int = 52, **p,
) -> np.ndarray:
    """1.0 = price above the cloud, -1.0 = below, 0.0 = inside it."""
    _tenkan, _kijun, senkou_a, senkou_b = _ichimoku_raw(
        df["high"], df["low"], int(tenkan_period), int(kijun_period), int(senkou_b_period)
    )
    cloud_top = np.maximum(senkou_a, senkou_b)
    cloud_bottom = np.minimum(senkou_a, senkou_b)
    close = df["close"]
    result = pd.Series(0.0, index=df.index)
    result[close > cloud_top] = 1.0
    result[close < cloud_bottom] = -1.0
    return result.to_numpy(dtype=float)


def ichimoku_kumo_twist_bullish(
    df: pd.DataFrame, tenkan_period: int = 9, kijun_period: int = 26, senkou_b_period: int = 52, **p,
) -> np.ndarray:
    """Senkou Span A crosses above Senkou Span B - the cloud ahead just
    turned from red to green. A thin convenience wrapper (this is already
    buildable manually as senkou_a crosses_above senkou_b with matching
    params) so it shows up as one discoverable named condition."""
    _tenkan, _kijun, senkou_a, senkou_b = _ichimoku_raw(
        df["high"], df["low"], int(tenkan_period), int(kijun_period), int(senkou_b_period)
    )
    above = senkou_a > senkou_b
    prev_above = above.shift(1, fill_value=False)
    return (above & ~prev_above).to_numpy(dtype=float)


def ichimoku_kumo_twist_bearish(
    df: pd.DataFrame, tenkan_period: int = 9, kijun_period: int = 26, senkou_b_period: int = 52, **p,
) -> np.ndarray:
    """Mirror image of ichimoku_kumo_twist_bullish."""
    _tenkan, _kijun, senkou_a, senkou_b = _ichimoku_raw(
        df["high"], df["low"], int(tenkan_period), int(kijun_period), int(senkou_b_period)
    )
    below = senkou_a < senkou_b
    prev_below = below.shift(1, fill_value=False)
    return (below & ~prev_below).to_numpy(dtype=float)


def ichimoku_chikou_signal(df: pd.DataFrame, kijun_period: int = 26, **p) -> np.ndarray:
    """Practical, causally-safe stand-in for reading the Chikou (lagging)
    Span: traditionally it's the CURRENT close plotted `kijun_period` bars
    into the past, so a trader visually compares it against the price
    action already drawn there - a genuinely retrospective/visual
    comparison, not a real-time signal (checking it "as of" a past bar
    would require knowing that past bar's future, i.e. today's close,
    which is only just now available - not a lookahead violation for a
    human glancing at a finished chart, but not expressible as a
    real-time, no-lookahead condition either). The actionable real-time
    equivalent traders actually act on is simpler: is the CURRENT close
    above/below the close from `kijun_period` bars ago - this is exactly
    that, returned as +1/-1/0 (0 on an exact tie)."""
    close = df["close"]
    past_close = close.shift(kijun_period)
    result = pd.Series(0.0, index=df.index)
    result[close > past_close] = 1.0
    result[close < past_close] = -1.0
    return result.to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Linear regression slope/channel - a statistically grounded alternative to
# ema_slope_degrees' simple two-point comparison.
# ---------------------------------------------------------------------------

def _rolling_linreg_stats(y: pd.Series, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Rolling OLS slope and fitted-value-at-the-window's-last-point, via
    an O(n) closed-form trick rather than an O(n*window) per-window Python
    callback (important at this project's 500k+ row scale, per the
    performance priorities already established this session).

    Treats x as the LOCAL position 0..window-1 within each window. The
    tricky term, sum(i*y_i) for local i, is recovered from a plain rolling
    sum of (global_index * y) via sum(i*y_i) = sum(k*y_k) -
    window_start*sum(y_k) (k = global index, window_start = k of the
    window's first row) - both sum(k*y_k) and sum(y_k) ARE expressible as
    plain `.rolling(window).sum()` calls since they don't depend on the
    window's own local offset."""
    n = window
    y_arr = y.to_numpy(dtype=float)
    idx = np.arange(len(y_arr), dtype=float)

    sum_y = y.rolling(window).sum().to_numpy(dtype=float)
    iy_global = pd.Series(idx * y_arr, index=y.index)
    sum_iy_global = iy_global.rolling(window).sum().to_numpy(dtype=float)

    window_start = idx - n + 1
    sum_iy_local = sum_iy_global - window_start * sum_y

    sum_i = n * (n - 1) / 2
    sum_i2 = (n - 1) * n * (2 * n - 1) / 6

    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (n * sum_iy_local - sum_i * sum_y) / (n * sum_i2 - sum_i ** 2)

    mean_y = sum_y / n
    mean_i = sum_i / n
    intercept = mean_y - slope * mean_i
    fitted_at_last = intercept + slope * (n - 1)

    return slope, fitted_at_last


def linreg_slope_atr_ratio(df: pd.DataFrame, length: int = 20, atr_length: int = 14, **p) -> np.ndarray:
    """Rolling regression slope (price units/bar), expressed as a multiple
    of ATR so it's comparable across symbols/timeframes."""
    slope, _fitted = _rolling_linreg_stats(df["close"], int(length))
    atr_values = _atr_level(df, atr_length).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return slope / atr_values


def linreg_angle_degrees(df: pd.DataFrame, length: int = 20, atr_length: int = 14, **p) -> np.ndarray:
    slope, _fitted = _rolling_linreg_stats(df["close"], int(length))
    atr_values = _atr_level(df, atr_length).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        normalized = slope / atr_values
    return np.degrees(np.arctan(normalized))


def linreg_value(df: pd.DataFrame, length: int = 20, **p) -> np.ndarray:
    """The regression line's fitted value at the most recent bar in the
    window - a smoothed trend-line level, comparable to price like an
    EMA/SMA."""
    _slope, fitted = _rolling_linreg_stats(df["close"], int(length))
    return fitted


def _linreg_band(df: pd.DataFrame, length: int, num_std: float, sign: float) -> np.ndarray:
    _slope, fitted = _rolling_linreg_stats(df["close"], int(length))
    # Approximation: uses plain rolling std of close as the channel's half-
    # width rather than the true regression residual std (which would need
    # per-window residuals, defeating the O(n) closed form above) - same
    # "simplified but honestly documented" tradeoff as this session's other
    # approximated indicators (e.g. bb_squeeze's percentile-based
    # definition vs a textbook TTM squeeze).
    residual_std = df["close"].rolling(int(length)).std().to_numpy(dtype=float)
    return fitted + sign * num_std * residual_std


def linreg_upper(df: pd.DataFrame, length: int = 20, num_std: float = 2.0, **p) -> np.ndarray:
    return _linreg_band(df, length, num_std, 1.0)


def linreg_lower(df: pd.DataFrame, length: int = 20, num_std: float = 2.0, **p) -> np.ndarray:
    return _linreg_band(df, length, num_std, -1.0)


# ---------------------------------------------------------------------------
# NR4/NR7 (Narrow Range) - classic price-action volatility-compression
# read, using the RAW high-low range directly rather than an indicator
# (Bollinger/Keltner width) - distinct from bb_squeeze/ttm_squeeze, which
# are both indicator-derived.
# ---------------------------------------------------------------------------

def _narrow_range(df: pd.DataFrame, n: int) -> np.ndarray:
    bar_range = df["high"] - df["low"]
    return (bar_range == bar_range.rolling(n).min()).fillna(False).to_numpy(dtype=float)


def nr4(df: pd.DataFrame, **p) -> np.ndarray:
    return _narrow_range(df, 4)


def nr7(df: pd.DataFrame, **p) -> np.ndarray:
    return _narrow_range(df, 7)


# ---------------------------------------------------------------------------
# Volume/range climax (exhaustion) bar - an unusually large body on
# unusually high volume, the classic "blow-off"/exhaustion read at a trend
# extreme. Same "FX volume is broker tick/proxy volume" caveat as every
# other volume-based indicator in this project.
# ---------------------------------------------------------------------------

def _require_volume_column(df: pd.DataFrame) -> pd.Series:
    if "volume" not in df.columns:
        raise ValueError(
            "この指標にはvolume列が必要ですが、この価格データにはありません"
            "(volume列を含むデータソースを使用してください)"
        )
    return df["volume"]


def _volume_climax(df: pd.DataFrame, is_bullish: bool, lookback: int, body_mult: float, volume_mult: float) -> np.ndarray:
    volume = _require_volume_column(df)
    body = (df["close"] - df["open"]).abs()
    avg_body = body.rolling(lookback).mean().shift(1)
    avg_volume = volume.rolling(lookback).mean().shift(1)

    direction = df["close"] > df["open"] if is_bullish else df["close"] < df["open"]
    large_body = body > avg_body * body_mult
    high_volume = volume > avg_volume * volume_mult
    return (direction & large_body & high_volume).fillna(False).to_numpy(dtype=float)


def volume_climax_bullish(df: pd.DataFrame, lookback: int = 20, body_mult: float = 2.0, volume_mult: float = 2.0, **p) -> np.ndarray:
    return _volume_climax(df, True, int(lookback), float(body_mult), float(volume_mult))


def volume_climax_bearish(df: pd.DataFrame, lookback: int = 20, body_mult: float = 2.0, volume_mult: float = 2.0, **p) -> np.ndarray:
    return _volume_climax(df, False, int(lookback), float(body_mult), float(volume_mult))
