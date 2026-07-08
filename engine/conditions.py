"""Generic, composable condition engine (AND/OR/NOT trees over indicator comparisons).

Per the project charter (Strategy Lab プロジェクト仕様, 2026-07-05): entry conditions
must compose via AND/OR/NOT with no limit on how many, and must not hardcode any
particular indicator's "direction" (e.g. RSI>70 does NOT inherently mean "short bias" -
that's a choice the condition's operator/value make explicit, independent of which
way the resulting trade is taken). This module is additive - it does not replace
engine/triggers.py + engine/filters.py + engine/signal_builder.py, which remain
exactly as they are for backward compatibility. A strategy built with this engine is
selected by run_backtest() when a params dict contains a "condition_tree" key; when
absent, run_backtest() uses the existing trigger/filter registry path unchanged.

Two composable node types:
    Condition       - one indicator compared against a literal value or another
                       indicator, e.g. {"indicator": "rsi", "params": {"length": 14},
                       "operator": "<", "value": 30.0}
    ConditionGroup   - AND/OR/NOT of child Condition/ConditionGroup nodes, e.g.
                       {"op": "AND", "children": [cond1, cond2]}

Both evaluate to a boolean numpy array over the whole price series (vectorized, not
per-bar - matches this project's existing performance approach of computing indicator
arrays once and comparing them elementwise, rather than looping per bar).

Indicators are looked up by name in INDICATOR_REGISTRY, wrapping the existing,
already-correct indicator math in engine/indicators.py and engine/technical_indicators.py
rather than reimplementing it. Adding a new indicator later is a 2-3 line registry
addition, not a new trigger/filter function pair and not a new if-branch anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

import numpy as np
import pandas as pd

from engine.indicators import atr as _atr
from engine.indicators import ema as _ema
from engine.indicators import rsi as _rsi
from engine.indicators import sma as _sma
from engine.technical_indicators import adx as _adx
from engine.technical_indicators import bollinger_bands, macd, stochastic_oscillator
from engine.technical_indicators import daily_reference_levels
from engine.technical_indicators import round_number_distance_pips as _round_number_distance_pips
from engine.technical_indicators import daily_vwap as _daily_vwap
from engine.technical_indicators import ichimoku
from engine.technical_indicators import supertrend as _supertrend
from engine.technical_indicators import (
    accumulation_distribution,
    aroon,
    camarilla_levels,
    chaikin_money_flow,
    cci as _cci,
    choppiness_index as _choppiness_index,
    fibonacci_pivot_levels,
    keltner_channels,
    money_flow_index,
    on_balance_volume,
    parabolic_sar,
    williams_r as _williams_r,
    woodie_pivot_levels,
)
from engine.smc_indicators import (
    bearish_fvg,
    bearish_order_block,
    bos_choch_bearish,
    bos_choch_bullish,
    breaker_block_bearish,
    breaker_block_bullish,
    bullish_fvg,
    bullish_order_block,
    liquidity_sweep_bearish,
    liquidity_sweep_bullish,
)
import engine.candlestick_patterns as _cdl
import engine.chart_patterns as _chart
import engine.derived_indicators as _derived
import engine.harmonic_patterns as _harmonic
import engine.heikin_ashi as _ha
from engine.data_loader import find_data_file, load_price_data

_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
    # Approximate (30 days) - months have variable length, but this dict is
    # only ever used for "which known label is closest" inference (see
    # _infer_timeframe_label), not exact duration math, so an average is fine.
    "1mo": 2592000,
}


def _infer_timeframe_label(datetime_series: pd.Series) -> str | None:
    """Guesses which of this project's known timeframe labels a price
    series' bars match, from the median gap between bars - used only to
    detect when a condition's requested `timeframe` happens to equal the
    backtest's own base timeframe, so that case can skip the multi-
    timeframe alignment path entirely (which would otherwise introduce a
    spurious 1-bar lag not present in a normal same-timeframe condition)."""
    median_seconds = pd.to_datetime(datetime_series).diff().dt.total_seconds().median()
    if pd.isna(median_seconds):
        return None
    label, _ = min(_TIMEFRAME_SECONDS.items(), key=lambda kv: abs(kv[1] - median_seconds))
    return label


def _align_mtf_series(base_datetime: pd.Series, tf_datetime: pd.Series, tf_values: np.ndarray) -> np.ndarray:
    """Aligns another timeframe's indicator array down to base_datetime's bar
    index, using only the most recently CLOSED bar of that other timeframe as
    of each base bar. Shifting tf_values by 1 before an as-of backward merge
    is the standard no-lookahead MTF alignment technique: row i of the
    shifted series holds the value of the bar that just closed as of
    tf_datetime[i], so backward-matching against it can never return a
    still-forming bar's value."""
    shifted = pd.Series(tf_values).shift(1)
    tf_lookup = pd.DataFrame({"datetime": pd.to_datetime(tf_datetime), "value": shifted}).sort_values("datetime")
    base_lookup = pd.DataFrame({"datetime": pd.to_datetime(base_datetime)})
    merged = pd.merge_asof(base_lookup, tf_lookup, on="datetime", direction="backward")
    return merged["value"].to_numpy(dtype=float)


def _highest_high(df: pd.DataFrame, length: int = 20) -> np.ndarray:
    """Highest high of the PREVIOUS `length` bars (shifted 1, excludes current bar)."""
    return df["high"].rolling(window=length).max().shift(1).to_numpy(dtype=float)


def _lowest_low(df: pd.DataFrame, length: int = 20) -> np.ndarray:
    """Lowest low of the PREVIOUS `length` bars (shifted 1, excludes current bar)."""
    return df["low"].rolling(window=length).min().shift(1).to_numpy(dtype=float)


def _donchian_mid(df: pd.DataFrame, length: int = 20) -> np.ndarray:
    return (_highest_high(df, length) + _lowest_low(df, length)) / 2


def _bollinger_upper(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> np.ndarray:
    upper, _middle, _lower = bollinger_bands(df["close"], period, num_std)
    return upper.to_numpy(dtype=float)


def _bollinger_middle(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> np.ndarray:
    _upper, middle, _lower = bollinger_bands(df["close"], period, num_std)
    return middle.to_numpy(dtype=float)


def _bollinger_lower(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> np.ndarray:
    _upper, _middle, lower = bollinger_bands(df["close"], period, num_std)
    return lower.to_numpy(dtype=float)


def _macd_line(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> np.ndarray:
    line, _signal, _hist = macd(df["close"], fast, slow, signal)
    return line.to_numpy(dtype=float)


def _macd_signal(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> np.ndarray:
    _line, signal_line, _hist = macd(df["close"], fast, slow, signal)
    return signal_line.to_numpy(dtype=float)


def _stochastic_k(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3, smooth: int = 3
) -> np.ndarray:
    k, _d = stochastic_oscillator(df["high"], df["low"], df["close"], k_period, d_period, smooth)
    return k.to_numpy(dtype=float)


def _stochastic_d(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3, smooth: int = 3
) -> np.ndarray:
    _k, d = stochastic_oscillator(df["high"], df["low"], df["close"], k_period, d_period, smooth)
    return d.to_numpy(dtype=float)


def _adx_line(df: pd.DataFrame, length: int = 14) -> np.ndarray:
    line, _plus_di, _minus_di = _adx(df["high"], df["low"], df["close"], length)
    return line.to_numpy(dtype=float)


def _plus_di(df: pd.DataFrame, length: int = 14) -> np.ndarray:
    _line, plus_di, _minus_di = _adx(df["high"], df["low"], df["close"], length)
    return plus_di.to_numpy(dtype=float)


def _minus_di(df: pd.DataFrame, length: int = 14) -> np.ndarray:
    _line, _plus_di, minus_di = _adx(df["high"], df["low"], df["close"], length)
    return minus_di.to_numpy(dtype=float)


def _supertrend_line(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> np.ndarray:
    # multiplier isn't adjustable from the condition-builder UI yet (which
    # only exposes one "length"-named field per indicator) - same tradeoff
    # already made for bollinger_upper/lower's num_std above.
    line, _direction = _supertrend(df["high"], df["low"], df["close"], length, multiplier)
    return np.asarray(line, dtype=float)


def _supertrend_direction(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> np.ndarray:
    _line, direction = _supertrend(df["high"], df["low"], df["close"], length, multiplier)
    return np.asarray(direction, dtype=float)


def _local_hour(datetime_series: pd.Series, tz: str) -> np.ndarray:
    """Converts this project's datetime column (tz-naive, but always true
    JST wall-clock - see import_broker_csv.py's SOURCE_TZ/TARGET_TZ
    conversion) to another IANA timezone's local hour-of-day, via a real
    tz-aware conversion rather than a hardcoded UTC-offset guess. Tokyo has
    no DST so localizing to it is always unambiguous; converting onward to
    a DST-observing zone (Europe/London, America/New_York) then correctly
    picks up that zone's actual historical DST transition dates (the US
    rule changed in 2007 - a fixed calendar rule would be wrong for this
    project's pre-2007 data)."""
    localized = pd.to_datetime(datetime_series).dt.tz_localize("Asia/Tokyo")
    return localized.dt.tz_convert(tz).dt.hour.to_numpy(dtype=float)


def _in_hour_range(hour_arr: np.ndarray, start: int, end: int) -> np.ndarray:
    return (hour_arr >= start) & (hour_arr < end)


# ICT/SMC "Kill Zone" time windows - fixed in each city's OWN local time
# (confirmed by reverse-deriving from a JST DST/winter-time table: 3 of the
# 4 zones show a 1-hour JST shift between DST/winter because JST itself has
# no DST, while the underlying city-local window is identical in both rows).
def _killzone_asian(df: pd.DataFrame) -> np.ndarray:
    hour = pd.to_datetime(df["datetime"]).dt.hour.to_numpy(dtype=float)  # already Asia/Tokyo (=JST)
    return _in_hour_range(hour, 8, 10)


def _killzone_london(df: pd.DataFrame) -> np.ndarray:
    return _in_hour_range(_local_hour(df["datetime"], "Europe/London"), 7, 10)


def _killzone_newyork(df: pd.DataFrame) -> np.ndarray:
    return _in_hour_range(_local_hour(df["datetime"], "America/New_York"), 7, 10)


def _killzone_london_close(df: pd.DataFrame) -> np.ndarray:
    return _in_hour_range(_local_hour(df["datetime"], "Europe/London"), 15, 17)


def _daily_ref_column(df: pd.DataFrame, column: str, adr_period: int = 14) -> np.ndarray:
    """Wraps daily_reference_levels() (previous-day high/low, classic daily
    pivot/R1/S1, and ADR - all causally safe, shift(1) before broadcasting
    onto every intraday bar of the following day). Called once per distinct
    (column) request rather than shared across pivot/r1/s1/prev_day_high/
    prev_day_low/adr - same "recompute per indicator name, cache misses
    across siblings" tradeoff already accepted by adx/plus_di/minus_di
    below (extensibility/correctness over speed, per this project's stated
    priority order)."""
    return daily_reference_levels(df, adr_period)[column].to_numpy(dtype=float)


def _ichimoku_component(
    df: pd.DataFrame,
    component: str,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
) -> np.ndarray:
    tenkan, kijun, senkou_a, senkou_b = ichimoku(
        df["high"], df["low"], tenkan_period, kijun_period, senkou_b_period
    )
    lines = {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b}
    return lines[component].to_numpy(dtype=float)


def _fib_level(df: pd.DataFrame, length: int = 20, ratio: float = 0.618) -> np.ndarray:
    """Fibonacci retracement/extension level: a linear interpolation
    (ratio<1) or extrapolation (ratio>1) between the rolling N-bar high and
    low - direction-agnostic by construction (ratio=0 sits at the high,
    ratio=1 at the low; which end represents "the swing being retraced"
    is left to how the resulting condition is used, same as how a manually
    drawn Fibonacci tool doesn't know which of its two anchor points came
    first chronologically either)."""
    high = _highest_high(df, length)
    low = _lowest_low(df, length)
    return high - ratio * (high - low)


def _vwap(df: pd.DataFrame) -> np.ndarray:
    if "volume" not in df.columns:
        raise ValueError(
            "VWAPにはvolume列が必要ですが、この価格データにはありません"
            "(volume列を含むデータソースを使用してください)"
        )
    return _daily_vwap(df["high"], df["low"], df["close"], df["volume"], df["datetime"]).to_numpy(dtype=float)


def _require_volume(df: pd.DataFrame) -> pd.Series:
    if "volume" not in df.columns:
        raise ValueError(
            "この指標にはvolume列が必要ですが、この価格データにはありません"
            "(volume列を含むデータソースを使用してください)"
        )
    return df["volume"]


def _parabolic_sar_line(df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2) -> np.ndarray:
    sar, _direction = parabolic_sar(df["high"], df["low"], df["close"], af_start, af_step, af_max)
    return np.asarray(sar, dtype=float)


def _parabolic_sar_direction(df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2) -> np.ndarray:
    _sar, direction = parabolic_sar(df["high"], df["low"], df["close"], af_start, af_step, af_max)
    return np.asarray(direction, dtype=float)


def _aroon_up(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    up, _down = aroon(df["high"], df["low"], int(period))
    return up.to_numpy(dtype=float)


def _aroon_down(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    _up, down = aroon(df["high"], df["low"], int(period))
    return down.to_numpy(dtype=float)


def _aroon_oscillator(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    up, down = aroon(df["high"], df["low"], int(period))
    return (up - down).to_numpy(dtype=float)


def _keltner_band(df: pd.DataFrame, band: str, period: int = 20, atr_period: int = 10, multiplier: float = 2.0) -> np.ndarray:
    upper, middle, lower = keltner_channels(df["high"], df["low"], df["close"], int(period), int(atr_period), float(multiplier))
    return {"upper": upper, "middle": middle, "lower": lower}[band].to_numpy(dtype=float)


def _woodie_column(df: pd.DataFrame, column: str) -> np.ndarray:
    return woodie_pivot_levels(df)[column].to_numpy(dtype=float)


def _camarilla_column(df: pd.DataFrame, column: str) -> np.ndarray:
    return camarilla_levels(df)[column].to_numpy(dtype=float)


def _fib_pivot_column(df: pd.DataFrame, column: str) -> np.ndarray:
    return fibonacci_pivot_levels(df)[column].to_numpy(dtype=float)


# Indicator name -> function(df, **params) -> np.ndarray[float]. Add new indicators
# here only - never touch Condition/ConditionGroup's evaluation logic to support one.
INDICATOR_REGISTRY: dict[str, Any] = {
    "close": lambda df, **p: df["close"].to_numpy(dtype=float),
    "open": lambda df, **p: df["open"].to_numpy(dtype=float),
    "high": lambda df, **p: df["high"].to_numpy(dtype=float),
    "low": lambda df, **p: df["low"].to_numpy(dtype=float),
    "hour": lambda df, **p: pd.to_datetime(df["datetime"]).dt.hour.to_numpy(dtype=float),
    "weekday": lambda df, **p: pd.to_datetime(df["datetime"]).dt.weekday.to_numpy(dtype=float),
    "month": lambda df, **p: pd.to_datetime(df["datetime"]).dt.month.to_numpy(dtype=float),
    "candle_body": lambda df, **p: (df["close"] - df["open"]).to_numpy(dtype=float),
    "ema": lambda df, length=200, **p: _ema(df["close"], int(length)).to_numpy(dtype=float),
    "sma": lambda df, length=200, **p: _sma(df["close"], int(length)).to_numpy(dtype=float),
    "rsi": lambda df, length=14, **p: _rsi(df["close"], int(length)).to_numpy(dtype=float),
    "atr": lambda df, length=14, **p: _atr(df, int(length)).to_numpy(dtype=float),
    "highest_high": lambda df, length=20, **p: _highest_high(df, int(length)),
    "lowest_low": lambda df, length=20, **p: _lowest_low(df, int(length)),
    "donchian_mid": lambda df, length=20, **p: _donchian_mid(df, int(length)),
    "bollinger_upper": lambda df, period=20, num_std=2.0, **p: _bollinger_upper(
        df, int(period), float(num_std)
    ),
    "bollinger_middle": lambda df, period=20, num_std=2.0, **p: _bollinger_middle(
        df, int(period), float(num_std)
    ),
    "bollinger_lower": lambda df, period=20, num_std=2.0, **p: _bollinger_lower(
        df, int(period), float(num_std)
    ),
    "macd_line": lambda df, fast=12, slow=26, signal=9, **p: _macd_line(
        df, int(fast), int(slow), int(signal)
    ),
    "macd_signal": lambda df, fast=12, slow=26, signal=9, **p: _macd_signal(
        df, int(fast), int(slow), int(signal)
    ),
    "stochastic_k": lambda df, k_period=14, d_period=3, smooth=3, **p: _stochastic_k(
        df, int(k_period), int(d_period), int(smooth)
    ),
    "stochastic_d": lambda df, k_period=14, d_period=3, smooth=3, **p: _stochastic_d(
        df, int(k_period), int(d_period), int(smooth)
    ),
    "adx": lambda df, length=14, **p: _adx_line(df, int(length)),
    "plus_di": lambda df, length=14, **p: _plus_di(df, int(length)),
    "minus_di": lambda df, length=14, **p: _minus_di(df, int(length)),
    "supertrend_line": lambda df, length=10, multiplier=3.0, **p: _supertrend_line(
        df, int(length), float(multiplier)
    ),
    "supertrend_direction": lambda df, length=10, multiplier=3.0, **p: _supertrend_direction(
        df, int(length), float(multiplier)
    ),
    # SMC (Smart Money Concepts) - boolean per-bar signals represented as
    # 1.0/0.0, meant to be compared with =="1" ("did this fire on this
    # bar"). Unverified against TradingView/any reference indicator -
    # see engine/smc_indicators.py's module docstring.
    "fvg_bullish": lambda df, **p: bullish_fvg(df["high"], df["low"]).astype(float),
    "fvg_bearish": lambda df, **p: bearish_fvg(df["high"], df["low"]).astype(float),
    "order_block_bullish": lambda df, **p: bullish_order_block(df["open"], df["close"]).astype(float),
    "order_block_bearish": lambda df, **p: bearish_order_block(df["open"], df["close"]).astype(float),
    "liquidity_sweep_bullish": lambda df, length=5, **p: liquidity_sweep_bullish(
        df["high"], df["low"], df["close"], int(length)
    ).astype(float),
    "liquidity_sweep_bearish": lambda df, length=5, **p: liquidity_sweep_bearish(
        df["high"], df["low"], df["close"], int(length)
    ).astype(float),
    "bos_bullish": lambda df, length=5, **p: bos_choch_bullish(
        df["high"], df["low"], df["close"], int(length)
    )[0].astype(float),
    "choch_bullish": lambda df, length=5, **p: bos_choch_bullish(
        df["high"], df["low"], df["close"], int(length)
    )[1].astype(float),
    "bos_bearish": lambda df, length=5, **p: bos_choch_bearish(
        df["high"], df["low"], df["close"], int(length)
    )[0].astype(float),
    "choch_bearish": lambda df, length=5, **p: bos_choch_bearish(
        df["high"], df["low"], df["close"], int(length)
    )[1].astype(float),
    "breaker_block_bullish": lambda df, **p: breaker_block_bullish(
        df["open"], df["high"], df["low"], df["close"]
    ).astype(float),
    "breaker_block_bearish": lambda df, **p: breaker_block_bearish(
        df["open"], df["high"], df["low"], df["close"]
    ).astype(float),
    # Forex "volume" is broker tick/proxy volume (no central exchange), not
    # true traded volume - see engine/technical_indicators.py::daily_vwap's
    # docstring. Raises a clear error if the loaded price data has no
    # volume column rather than silently returning NaN/garbage.
    "vwap": lambda df, **p: _vwap(df),
    # ICT/SMC "Kill Zone" sessions - boolean per-bar signals (1.0/0.0),
    # meant to be compared with =="1" like the SMC signals above.
    "killzone_asian": lambda df, **p: _killzone_asian(df).astype(float),
    "killzone_london": lambda df, **p: _killzone_london(df).astype(float),
    "killzone_newyork": lambda df, **p: _killzone_newyork(df).astype(float),
    "killzone_london_close": lambda df, **p: _killzone_london_close(df).astype(float),
    # Previous-day high/low + classic daily pivot/R1/S1 (all shift(1),
    # no lookahead) and ADR - see _daily_ref_column's docstring.
    "prev_day_high": lambda df, **p: _daily_ref_column(df, "prev_day_high"),
    "prev_day_low": lambda df, **p: _daily_ref_column(df, "prev_day_low"),
    "pivot": lambda df, **p: _daily_ref_column(df, "pivot"),
    "pivot_r1": lambda df, **p: _daily_ref_column(df, "r1"),
    "pivot_s1": lambda df, **p: _daily_ref_column(df, "s1"),
    "adr": lambda df, adr_period=14, **p: _daily_ref_column(df, "adr", int(adr_period)),
    "ichimoku_tenkan": lambda df, tenkan_period=9, kijun_period=26, senkou_b_period=52, **p: _ichimoku_component(
        df, "tenkan", int(tenkan_period), int(kijun_period), int(senkou_b_period)
    ),
    "ichimoku_kijun": lambda df, tenkan_period=9, kijun_period=26, senkou_b_period=52, **p: _ichimoku_component(
        df, "kijun", int(tenkan_period), int(kijun_period), int(senkou_b_period)
    ),
    "ichimoku_senkou_a": lambda df, tenkan_period=9, kijun_period=26, senkou_b_period=52, **p: _ichimoku_component(
        df, "senkou_a", int(tenkan_period), int(kijun_period), int(senkou_b_period)
    ),
    "ichimoku_senkou_b": lambda df, tenkan_period=9, kijun_period=26, senkou_b_period=52, **p: _ichimoku_component(
        df, "senkou_b", int(tenkan_period), int(kijun_period), int(senkou_b_period)
    ),
    "fib_level": lambda df, length=20, ratio=0.618, **p: _fib_level(df, int(length), float(ratio)),
    # Candlestick patterns (engine/candlestick_patterns.py) - boolean per-bar
    # signals (1.0/0.0), meant to be compared with =="1" like the SMC
    # signals above. Not verified against any reference charting platform -
    # see that module's own docstring for why, and for why hammer/
    # hanging_man and inverted_hammer/shooting_star are registered twice
    # under the same underlying shape function.
    "bullish_candle": lambda df, **p: _cdl.bullish_candle(df["open"], df["close"]).to_numpy(dtype=float),
    "bearish_candle": lambda df, **p: _cdl.bearish_candle(df["open"], df["close"]).to_numpy(dtype=float),
    "large_bullish_candle": lambda df, lookback=20, multiplier=1.5, **p: _cdl.large_bullish_candle(
        df["open"], df["high"], df["low"], df["close"], int(lookback), float(multiplier)
    ).to_numpy(dtype=float),
    "large_bearish_candle": lambda df, lookback=20, multiplier=1.5, **p: _cdl.large_bearish_candle(
        df["open"], df["high"], df["low"], df["close"], int(lookback), float(multiplier)
    ).to_numpy(dtype=float),
    "small_bullish_candle": lambda df, lookback=20, multiplier=0.5, **p: _cdl.small_bullish_candle(
        df["open"], df["high"], df["low"], df["close"], int(lookback), float(multiplier)
    ).to_numpy(dtype=float),
    "small_bearish_candle": lambda df, lookback=20, multiplier=0.5, **p: _cdl.small_bearish_candle(
        df["open"], df["high"], df["low"], df["close"], int(lookback), float(multiplier)
    ).to_numpy(dtype=float),
    "doji": lambda df, body_ratio_threshold=0.1, **p: _cdl.doji(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_threshold)
    ).to_numpy(dtype=float),
    "long_upper_wick": lambda df, wick_ratio_threshold=0.6, **p: _cdl.long_upper_wick(
        df["open"], df["high"], df["low"], df["close"], float(wick_ratio_threshold)
    ).to_numpy(dtype=float),
    "long_lower_wick": lambda df, wick_ratio_threshold=0.6, **p: _cdl.long_lower_wick(
        df["open"], df["high"], df["low"], df["close"], float(wick_ratio_threshold)
    ).to_numpy(dtype=float),
    "no_upper_wick": lambda df, threshold=0.05, **p: _cdl.no_upper_wick(
        df["open"], df["high"], df["low"], df["close"], float(threshold)
    ).to_numpy(dtype=float),
    "no_lower_wick": lambda df, threshold=0.05, **p: _cdl.no_lower_wick(
        df["open"], df["high"], df["low"], df["close"], float(threshold)
    ).to_numpy(dtype=float),
    "marubozu_bullish": lambda df, body_ratio_threshold=0.95, **p: _cdl.marubozu_bullish(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_threshold)
    ).to_numpy(dtype=float),
    "marubozu_bearish": lambda df, body_ratio_threshold=0.95, **p: _cdl.marubozu_bearish(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_threshold)
    ).to_numpy(dtype=float),
    "pin_bar_bullish": lambda df, body_ratio_max=0.3, wick_ratio_min=0.6, **p: _cdl.pin_bar_bullish(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_max), float(wick_ratio_min)
    ).to_numpy(dtype=float),
    "pin_bar_bearish": lambda df, body_ratio_max=0.3, wick_ratio_min=0.6, **p: _cdl.pin_bar_bearish(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_max), float(wick_ratio_min)
    ).to_numpy(dtype=float),
    "hammer": lambda df, body_ratio_max=0.3, lower_wick_ratio_min=0.6, upper_wick_ratio_max=0.1, **p: _cdl.hammer_shape(
        df["open"], df["high"], df["low"], df["close"],
        float(body_ratio_max), float(lower_wick_ratio_min), float(upper_wick_ratio_max),
    ).to_numpy(dtype=float),
    "hanging_man": lambda df, body_ratio_max=0.3, lower_wick_ratio_min=0.6, upper_wick_ratio_max=0.1, **p: _cdl.hammer_shape(
        df["open"], df["high"], df["low"], df["close"],
        float(body_ratio_max), float(lower_wick_ratio_min), float(upper_wick_ratio_max),
    ).to_numpy(dtype=float),
    "inverted_hammer": lambda df, body_ratio_max=0.3, upper_wick_ratio_min=0.6, lower_wick_ratio_max=0.1, **p: _cdl.inverted_hammer_shape(
        df["open"], df["high"], df["low"], df["close"],
        float(body_ratio_max), float(upper_wick_ratio_min), float(lower_wick_ratio_max),
    ).to_numpy(dtype=float),
    "shooting_star": lambda df, body_ratio_max=0.3, upper_wick_ratio_min=0.6, lower_wick_ratio_max=0.1, **p: _cdl.inverted_hammer_shape(
        df["open"], df["high"], df["low"], df["close"],
        float(body_ratio_max), float(upper_wick_ratio_min), float(lower_wick_ratio_max),
    ).to_numpy(dtype=float),
    "engulfing_bullish": lambda df, **p: _cdl.engulfing_bullish(df["open"], df["close"]).to_numpy(dtype=float),
    "engulfing_bearish": lambda df, **p: _cdl.engulfing_bearish(df["open"], df["close"]).to_numpy(dtype=float),
    "inside_bar": lambda df, **p: _cdl.inside_bar(df["high"], df["low"]).to_numpy(dtype=float),
    "outside_bar": lambda df, **p: _cdl.outside_bar(df["high"], df["low"]).to_numpy(dtype=float),
    "tweezer_top": lambda df, tolerance_pct=0.1, **p: _cdl.tweezer_top(
        df["open"], df["high"], df["low"], df["close"], float(tolerance_pct)
    ).to_numpy(dtype=float),
    "tweezer_bottom": lambda df, tolerance_pct=0.1, **p: _cdl.tweezer_bottom(
        df["open"], df["high"], df["low"], df["close"], float(tolerance_pct)
    ).to_numpy(dtype=float),
    "harami_bullish": lambda df, **p: _cdl.harami_bullish(df["open"], df["close"]).to_numpy(dtype=float),
    "harami_bearish": lambda df, **p: _cdl.harami_bearish(df["open"], df["close"]).to_numpy(dtype=float),
    "gap_up": lambda df, **p: _cdl.gap_up(df["open"], df["high"]).to_numpy(dtype=float),
    "gap_down": lambda df, **p: _cdl.gap_down(df["open"], df["low"]).to_numpy(dtype=float),
    "morning_star": lambda df, small_body_ratio=0.3, **p: _cdl.morning_star(
        df["open"], df["high"], df["low"], df["close"], float(small_body_ratio)
    ).to_numpy(dtype=float),
    "evening_star": lambda df, small_body_ratio=0.3, **p: _cdl.evening_star(
        df["open"], df["high"], df["low"], df["close"], float(small_body_ratio)
    ).to_numpy(dtype=float),
    "three_white_soldiers": lambda df, **p: _cdl.three_white_soldiers(df["open"], df["close"]).to_numpy(dtype=float),
    "three_black_crows": lambda df, **p: _cdl.three_black_crows(df["open"], df["close"]).to_numpy(dtype=float),
    "rising_three_methods": lambda df, **p: _cdl.rising_three_methods(
        df["open"], df["high"], df["low"], df["close"]
    ).to_numpy(dtype=float),
    "falling_three_methods": lambda df, **p: _cdl.falling_three_methods(
        df["open"], df["high"], df["low"], df["close"]
    ).to_numpy(dtype=float),
    "consecutive_bullish_candles": lambda df, n=3, **p: _cdl.consecutive_bullish_candles(
        df["open"], df["close"], int(n)
    ).to_numpy(dtype=float),
    "consecutive_bearish_candles": lambda df, n=3, **p: _cdl.consecutive_bearish_candles(
        df["open"], df["close"], int(n)
    ).to_numpy(dtype=float),
    "consecutive_higher_highs": lambda df, n=3, **p: _cdl.consecutive_higher_highs(df["high"], int(n)).to_numpy(dtype=float),
    "consecutive_lower_lows": lambda df, n=3, **p: _cdl.consecutive_lower_lows(df["low"], int(n)).to_numpy(dtype=float),
    "body_larger_than_average": lambda df, lookback=20, multiplier=1.5, **p: _cdl.body_larger_than_average(
        df["open"], df["high"], df["low"], df["close"], int(lookback), float(multiplier)
    ).to_numpy(dtype=float),
    "wick_ratio_at_least": lambda df, threshold_pct=50.0, **p: _cdl.wick_ratio_at_least(
        df["open"], df["high"], df["low"], df["close"], float(threshold_pct)
    ).to_numpy(dtype=float),
    "body_ratio_at_least": lambda df, threshold_pct=50.0, **p: _cdl.body_ratio_at_least(
        df["open"], df["high"], df["low"], df["close"], float(threshold_pct)
    ).to_numpy(dtype=float),
    # 2026-07-08追加分 (candlestick_patterns.py拡張)
    "long_legged_doji": lambda df, body_ratio_threshold=0.1, wick_ratio_min=0.35, **p: _cdl.long_legged_doji(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_threshold), float(wick_ratio_min)
    ).to_numpy(dtype=float),
    "dragonfly_doji": lambda df, body_ratio_threshold=0.1, lower_wick_ratio_min=0.6, upper_wick_ratio_max=0.1, **p: _cdl.dragonfly_doji(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_threshold), float(lower_wick_ratio_min), float(upper_wick_ratio_max)
    ).to_numpy(dtype=float),
    "gravestone_doji": lambda df, body_ratio_threshold=0.1, upper_wick_ratio_min=0.6, lower_wick_ratio_max=0.1, **p: _cdl.gravestone_doji(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_threshold), float(upper_wick_ratio_min), float(lower_wick_ratio_max)
    ).to_numpy(dtype=float),
    "spinning_top": lambda df, body_ratio_max=0.3, wick_ratio_min=0.3, **p: _cdl.spinning_top(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_max), float(wick_ratio_min)
    ).to_numpy(dtype=float),
    "kicker_bullish": lambda df, body_ratio_threshold=0.7, **p: _cdl.kicker_bullish(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_threshold)
    ).to_numpy(dtype=float),
    "kicker_bearish": lambda df, body_ratio_threshold=0.7, **p: _cdl.kicker_bearish(
        df["open"], df["high"], df["low"], df["close"], float(body_ratio_threshold)
    ).to_numpy(dtype=float),
    "belt_hold_bullish": lambda df, lower_wick_ratio_max=0.05, body_ratio_min=0.7, **p: _cdl.belt_hold_bullish(
        df["open"], df["high"], df["low"], df["close"], float(lower_wick_ratio_max), float(body_ratio_min)
    ).to_numpy(dtype=float),
    "belt_hold_bearish": lambda df, upper_wick_ratio_max=0.05, body_ratio_min=0.7, **p: _cdl.belt_hold_bearish(
        df["open"], df["high"], df["low"], df["close"], float(upper_wick_ratio_max), float(body_ratio_min)
    ).to_numpy(dtype=float),
    "abandoned_baby_bullish": lambda df, small_body_ratio=0.1, **p: _cdl.abandoned_baby_bullish(
        df["open"], df["high"], df["low"], df["close"], float(small_body_ratio)
    ).to_numpy(dtype=float),
    "abandoned_baby_bearish": lambda df, small_body_ratio=0.1, **p: _cdl.abandoned_baby_bearish(
        df["open"], df["high"], df["low"], df["close"], float(small_body_ratio)
    ).to_numpy(dtype=float),
    "three_inside_up": lambda df, **p: _cdl.three_inside_up(
        df["open"], df["high"], df["low"], df["close"]
    ).to_numpy(dtype=float),
    "three_inside_down": lambda df, **p: _cdl.three_inside_down(
        df["open"], df["high"], df["low"], df["close"]
    ).to_numpy(dtype=float),
    "three_outside_up": lambda df, **p: _cdl.three_outside_up(
        df["open"], df["high"], df["low"], df["close"]
    ).to_numpy(dtype=float),
    "three_outside_down": lambda df, **p: _cdl.three_outside_down(
        df["open"], df["high"], df["low"], df["close"]
    ).to_numpy(dtype=float),
    # ラウンドナンバー(キリ番)までの距離 - engine/technical_indicators.pyの
    # round_number_distance_pipsは旧filters.pyでは使われていたが、条件ツリー
    # エンジンにはまだ繋がれていなかった。pip_sizeは通貨ペアごとに違うため
    # (JPYペアは0.01、それ以外は0.0001)、条件側のparamsで明示指定する。
    "dist_to_round_number": lambda df, pip_size=0.01, **p: _round_number_distance_pips(
        df["close"], float(pip_size)
    ).to_numpy(dtype=float),
}

# engine/derived_indicators.py's functions already match the registry's
# (df, **params) -> np.ndarray calling convention exactly, so they're
# registered directly (no wrapping lambda needed) - see that module's
# docstring for why it's a separate file.
INDICATOR_REGISTRY.update(_derived.DISTANCE_INDICATORS)
INDICATOR_REGISTRY.update(_derived.SLOPE_INDICATORS)
INDICATOR_REGISTRY.update({
    # SMC zone distance
    "dist_order_block_bullish": _derived.dist_to_order_block_bullish,
    "dist_order_block_bearish": _derived.dist_to_order_block_bearish,
    "dist_fvg_bullish": _derived.dist_to_fvg_bullish,
    "dist_fvg_bearish": _derived.dist_to_fvg_bearish,
    "dist_bos_bullish": _derived.dist_to_bos_bullish,
    "dist_bos_bearish": _derived.dist_to_bos_bearish,
    # Time since session open
    "minutes_since_london_open": _derived.minutes_since_london_open,
    "minutes_since_ny_open": _derived.minutes_since_ny_open,
    # 傾き系 extras (rising/falling for 7 series already merged in via
    # SLOPE_INDICATORS above)
    "ema_slope_degrees": _derived.ema_slope_degrees,
    "ema_roc": _derived.ema_roc,
    "atr_roc": _derived.atr_roc,
    "higher_high": _derived.higher_high,
    "higher_low": _derived.higher_low,
    "lower_high": _derived.lower_high,
    "lower_low": _derived.lower_low,
    # 価格位置
    "bb_percent_b": _derived.bb_percent_b,
    "donchian_percent_position": _derived.donchian_percent_position,
    "dist_to_ema_atr_ratio": _derived.dist_to_ema_atr_ratio,
    "today_range_pct_of_adr": _derived.today_range_pct_of_adr,
    "prev_day_mid": _derived.prev_day_mid,
    "today_range_position": _derived.today_range_position,
    "dist_to_fib": _derived.dist_to_fib,
    # 統計系
    "rolling_mean_high": _derived.rolling_mean_high,
    "rolling_mean_low": _derived.rolling_mean_low,
    "avg_body_size": _derived.avg_body_size,
    "max_body_size": _derived.max_body_size,
    "min_body_size": _derived.min_body_size,
    "body_size_std": _derived.body_size_std,
    "avg_upper_wick": _derived.avg_upper_wick,
    "avg_lower_wick": _derived.avg_lower_wick,
    "atr_rolling_mean": _derived.atr_rolling_mean,
    "atr_deviation": _derived.atr_deviation,
    "close_rolling_std": _derived.close_rolling_std,
    "rsi_rolling_mean": _derived.rsi_rolling_mean,
    "rsi_deviation": _derived.rsi_deviation,
    "adx_rolling_mean": _derived.adx_rolling_mean,
    "macd_rolling_mean": _derived.macd_rolling_mean,
    "percentile_rank_rsi": _derived.percentile_rank_rsi,
    "percentile_rank_atr": _derived.percentile_rank_atr,
    "percentile_rank_body": _derived.percentile_rank_body,
    "zscore_close": _derived.zscore_close,
    "zscore_rsi": _derived.zscore_rsi,
    "zscore_atr": _derived.zscore_atr,
    "is_max_body_of_n": _derived.is_max_body_of_n,
    "is_min_atr_of_n": _derived.is_min_atr_of_n,
    "is_max_rsi_of_n": _derived.is_max_rsi_of_n,
    # エントリー専用イベント
    "bb_width": _derived.bb_width,
    "bb_squeeze": _derived.bb_squeeze,
    "bb_expansion": _derived.bb_expansion,
    "supertrend_flip_bullish": _derived.supertrend_flip_bullish,
    "supertrend_flip_bearish": _derived.supertrend_flip_bearish,
    "today_new_high": _derived.today_new_high,
    "today_new_low": _derived.today_new_low,
    # 一瞬だけ起きる変化
    "rsi_divergence_bearish": _derived.rsi_divergence_bearish,
    "rsi_divergence_bullish": _derived.rsi_divergence_bullish,
    "macd_divergence_bearish": _derived.macd_divergence_bearish,
    "macd_divergence_bullish": _derived.macd_divergence_bullish,
    "ema_perfect_order_bullish": _derived.ema_perfect_order_bullish,
    "ema_perfect_order_bearish": _derived.ema_perfect_order_bearish,
    "ema_perfect_order_broken_bullish": _derived.ema_perfect_order_broken_bullish,
    "ema_perfect_order_broken_bearish": _derived.ema_perfect_order_broken_bearish,
    "first_pullback_after_breakout_bullish": _derived.first_pullback_after_breakout_bullish,
    "first_pullback_after_breakout_bearish": _derived.first_pullback_after_breakout_bearish,
    "fvg_first_retest_bullish": _derived.fvg_first_retest_bullish,
    "fvg_first_retest_bearish": _derived.fvg_first_retest_bearish,
    "order_block_first_retest_bullish": _derived.order_block_first_retest_bullish,
    "order_block_first_retest_bearish": _derived.order_block_first_retest_bearish,
})

# Classic multi-swing chart patterns (engine/chart_patterns.py) - unlike
# every other function in this registry, these take (high, low, close, ...)
# directly rather than the whole df, so each needs a thin unpacking lambda.
INDICATOR_REGISTRY.update({
    "double_top_breakdown": lambda df, **p: _chart.double_top_breakdown(df["high"], df["low"], df["close"], **p),
    "double_bottom_breakout": lambda df, **p: _chart.double_bottom_breakout(df["high"], df["low"], df["close"], **p),
    "triple_top_breakdown": lambda df, **p: _chart.triple_top_breakdown(df["high"], df["low"], df["close"], **p),
    "triple_bottom_breakout": lambda df, **p: _chart.triple_bottom_breakout(df["high"], df["low"], df["close"], **p),
    "head_and_shoulders_breakdown": lambda df, **p: _chart.head_and_shoulders_breakdown(df["high"], df["low"], df["close"], **p),
    "inverse_head_and_shoulders_breakout": lambda df, **p: _chart.inverse_head_and_shoulders_breakout(df["high"], df["low"], df["close"], **p),
    "ascending_triangle_breakout": lambda df, **p: _chart.ascending_triangle_breakout(df["high"], df["low"], df["close"], **p),
    "descending_triangle_breakdown": lambda df, **p: _chart.descending_triangle_breakdown(df["high"], df["low"], df["close"], **p),
    "symmetrical_triangle_breakout_bullish": lambda df, **p: _chart.symmetrical_triangle_breakout_bullish(df["high"], df["low"], df["close"], **p),
    "symmetrical_triangle_breakout_bearish": lambda df, **p: _chart.symmetrical_triangle_breakout_bearish(df["high"], df["low"], df["close"], **p),
    "rising_wedge_breakdown": lambda df, **p: _chart.rising_wedge_breakdown(df["high"], df["low"], df["close"], **p),
    "falling_wedge_breakout": lambda df, **p: _chart.falling_wedge_breakout(df["high"], df["low"], df["close"], **p),
    "bull_flag_breakout": lambda df, **p: _chart.bull_flag_breakout(df["high"], df["low"], df["close"], **p),
    "bear_flag_breakdown": lambda df, **p: _chart.bear_flag_breakdown(df["high"], df["low"], df["close"], **p),
    "bullish_pennant_breakout": lambda df, **p: _chart.bullish_pennant_breakout(df["high"], df["low"], df["close"], **p),
    "bearish_pennant_breakdown": lambda df, **p: _chart.bearish_pennant_breakdown(df["high"], df["low"], df["close"], **p),
    "in_range_box": lambda df, **p: _chart.in_range_box(df["high"], df["low"], df["close"], **p),
    "range_box_breakout_bullish": lambda df, **p: _chart.range_box_breakout_bullish(df["high"], df["low"], df["close"], **p),
    "range_box_breakdown_bearish": lambda df, **p: _chart.range_box_breakdown_bearish(df["high"], df["low"], df["close"], **p),
})

# 2026-07-08追加(3巡目): 定番オシレーター/トレンド系 + ボリューム系 +
# ピボットバリエーション
INDICATOR_REGISTRY.update({
    "cci": lambda df, period=20, **p: _cci(df["high"], df["low"], df["close"], int(period)).to_numpy(dtype=float),
    "williams_r": lambda df, period=14, **p: _williams_r(df["high"], df["low"], df["close"], int(period)).to_numpy(dtype=float),
    "parabolic_sar_line": lambda df, af_start=0.02, af_step=0.02, af_max=0.2, **p: _parabolic_sar_line(
        df, float(af_start), float(af_step), float(af_max)
    ),
    "parabolic_sar_direction": lambda df, af_start=0.02, af_step=0.02, af_max=0.2, **p: _parabolic_sar_direction(
        df, float(af_start), float(af_step), float(af_max)
    ),
    "aroon_up": lambda df, period=14, **p: _aroon_up(df, int(period)),
    "aroon_down": lambda df, period=14, **p: _aroon_down(df, int(period)),
    "aroon_oscillator": lambda df, period=14, **p: _aroon_oscillator(df, int(period)),
    "choppiness_index": lambda df, period=14, **p: _choppiness_index(
        df["high"], df["low"], df["close"], int(period)
    ).to_numpy(dtype=float),
    "keltner_upper": lambda df, period=20, atr_period=10, multiplier=2.0, **p: _keltner_band(
        df, "upper", int(period), int(atr_period), float(multiplier)
    ),
    "keltner_middle": lambda df, period=20, atr_period=10, multiplier=2.0, **p: _keltner_band(
        df, "middle", int(period), int(atr_period), float(multiplier)
    ),
    "keltner_lower": lambda df, period=20, atr_period=10, multiplier=2.0, **p: _keltner_band(
        df, "lower", int(period), int(atr_period), float(multiplier)
    ),
    "obv": lambda df, **p: on_balance_volume(df["close"], _require_volume(df)).to_numpy(dtype=float),
    "mfi": lambda df, period=14, **p: money_flow_index(
        df["high"], df["low"], df["close"], _require_volume(df), int(period)
    ).to_numpy(dtype=float),
    "cmf": lambda df, period=20, **p: chaikin_money_flow(
        df["high"], df["low"], df["close"], _require_volume(df), int(period)
    ).to_numpy(dtype=float),
    "ad_line": lambda df, **p: accumulation_distribution(
        df["high"], df["low"], df["close"], _require_volume(df)
    ).to_numpy(dtype=float),
    "woodie_pivot": lambda df, **p: _woodie_column(df, "pivot"),
    "woodie_r1": lambda df, **p: _woodie_column(df, "r1"),
    "woodie_s1": lambda df, **p: _woodie_column(df, "s1"),
    "woodie_r2": lambda df, **p: _woodie_column(df, "r2"),
    "woodie_s2": lambda df, **p: _woodie_column(df, "s2"),
    "camarilla_r1": lambda df, **p: _camarilla_column(df, "r1"),
    "camarilla_r2": lambda df, **p: _camarilla_column(df, "r2"),
    "camarilla_r3": lambda df, **p: _camarilla_column(df, "r3"),
    "camarilla_r4": lambda df, **p: _camarilla_column(df, "r4"),
    "camarilla_s1": lambda df, **p: _camarilla_column(df, "s1"),
    "camarilla_s2": lambda df, **p: _camarilla_column(df, "s2"),
    "camarilla_s3": lambda df, **p: _camarilla_column(df, "s3"),
    "camarilla_s4": lambda df, **p: _camarilla_column(df, "s4"),
    "fib_pivot": lambda df, **p: _fib_pivot_column(df, "pivot"),
    "fib_pivot_r1": lambda df, **p: _fib_pivot_column(df, "r1"),
    "fib_pivot_r2": lambda df, **p: _fib_pivot_column(df, "r2"),
    "fib_pivot_r3": lambda df, **p: _fib_pivot_column(df, "r3"),
    "fib_pivot_s1": lambda df, **p: _fib_pivot_column(df, "s1"),
    "fib_pivot_s2": lambda df, **p: _fib_pivot_column(df, "s2"),
    "fib_pivot_s3": lambda df, **p: _fib_pivot_column(df, "s3"),
    # TTM Squeeze + Ichimoku completion (engine/derived_indicators.py)
    "ttm_squeeze": _derived.ttm_squeeze,
    "ttm_squeeze_release": _derived.ttm_squeeze_release,
    "ichimoku_price_vs_cloud": _derived.ichimoku_price_vs_cloud,
    "ichimoku_kumo_twist_bullish": _derived.ichimoku_kumo_twist_bullish,
    "ichimoku_kumo_twist_bearish": _derived.ichimoku_kumo_twist_bearish,
    "ichimoku_chikou_signal": _derived.ichimoku_chikou_signal,
    "linreg_slope_atr_ratio": _derived.linreg_slope_atr_ratio,
    "linreg_angle_degrees": _derived.linreg_angle_degrees,
    "linreg_value": _derived.linreg_value,
    "linreg_upper": _derived.linreg_upper,
    "linreg_lower": _derived.linreg_lower,
    # Heikin-Ashi (engine/heikin_ashi.py)
    "ha_bullish": _ha.ha_bullish,
    "ha_bearish": _ha.ha_bearish,
    "ha_strong_bullish": _ha.ha_strong_bullish,
    "ha_strong_bearish": _ha.ha_strong_bearish,
    # Harmonic patterns (engine/harmonic_patterns.py) - take (high, low)
    # directly rather than the whole df, like engine/chart_patterns.py's
    # functions do, so each needs a thin unpacking lambda.
    "gartley_bullish": lambda df, **p: _harmonic.gartley_bullish(df["high"], df["low"], **p),
    "gartley_bearish": lambda df, **p: _harmonic.gartley_bearish(df["high"], df["low"], **p),
    "bat_bullish": lambda df, **p: _harmonic.bat_bullish(df["high"], df["low"], **p),
    "bat_bearish": lambda df, **p: _harmonic.bat_bearish(df["high"], df["low"], **p),
    "butterfly_bullish": lambda df, **p: _harmonic.butterfly_bullish(df["high"], df["low"], **p),
    "butterfly_bearish": lambda df, **p: _harmonic.butterfly_bearish(df["high"], df["low"], **p),
    "crab_bullish": lambda df, **p: _harmonic.crab_bullish(df["high"], df["low"], **p),
    "crab_bearish": lambda df, **p: _harmonic.crab_bearish(df["high"], df["low"], **p),
    "ab_cd_bullish": lambda df, **p: _harmonic.ab_cd_bullish(df["high"], df["low"], **p),
    "ab_cd_bearish": lambda df, **p: _harmonic.ab_cd_bearish(df["high"], df["low"], **p),
    "three_drives_bullish": lambda df, **p: _harmonic.three_drives_bullish(df["high"], df["low"], **p),
    "three_drives_bearish": lambda df, **p: _harmonic.three_drives_bearish(df["high"], df["low"], **p),
})

# 2026-07-08追加(4巡目): トレンドライン/平行チャネル/フェイクブレイク
# (engine/chart_patterns.py) + NR4/NR7/出来高クライマックス
# (engine/derived_indicators.py)
INDICATOR_REGISTRY.update({
    "uptrend_line_break": lambda df, **p: _chart.uptrend_line_break(df["high"], df["low"], df["close"], **p),
    "downtrend_line_break": lambda df, **p: _chart.downtrend_line_break(df["high"], df["low"], df["close"], **p),
    "ascending_channel_break": lambda df, **p: _chart.ascending_channel_break(df["high"], df["low"], df["close"], **p),
    "descending_channel_break": lambda df, **p: _chart.descending_channel_break(df["high"], df["low"], df["close"], **p),
    "false_breakout_bullish_reversal": lambda df, **p: _chart.false_breakout_bullish_reversal(df["high"], df["low"], df["close"], **p),
    "false_breakout_bearish_reversal": lambda df, **p: _chart.false_breakout_bearish_reversal(df["high"], df["low"], df["close"], **p),
    "nr4": _derived.nr4,
    "nr7": _derived.nr7,
    "volume_climax_bullish": _derived.volume_climax_bullish,
    "volume_climax_bearish": _derived.volume_climax_bearish,
})

# 2026-07-08追加(5巡目、HFM記事の未実装分): ソーサートップ/ボトム、上昇/下降
# レクタングル、ブロードニングフォーメーション、ダイヤモンドフォーメーション、
# カップウィズハンドル (engine/chart_patterns.py)
INDICATOR_REGISTRY.update({
    "saucer_top": lambda df, **p: _chart.saucer_top(df["high"], df["low"], df["close"], **p),
    "saucer_bottom": lambda df, **p: _chart.saucer_bottom(df["high"], df["low"], df["close"], **p),
    "ascending_rectangle_breakout": lambda df, **p: _chart.ascending_rectangle_breakout(df["high"], df["low"], df["close"], **p),
    "descending_rectangle_breakdown": lambda df, **p: _chart.descending_rectangle_breakdown(df["high"], df["low"], df["close"], **p),
    "broadening_formation_breakout_bullish": lambda df, **p: _chart.broadening_formation_breakout_bullish(df["high"], df["low"], df["close"], **p),
    "broadening_formation_breakout_bearish": lambda df, **p: _chart.broadening_formation_breakout_bearish(df["high"], df["low"], df["close"], **p),
    "diamond_formation_breakout_bullish": lambda df, **p: _chart.diamond_formation_breakout_bullish(df["high"], df["low"], df["close"], **p),
    "diamond_formation_breakout_bearish": lambda df, **p: _chart.diamond_formation_breakout_bearish(df["high"], df["low"], df["close"], **p),
    "cup_with_handle_breakout": lambda df, **p: _chart.cup_with_handle_breakout(df["high"], df["low"], df["close"], **p),
})

_OPERATORS = {">", "<", ">=", "<=", "==", "crosses_above", "crosses_below"}


def _cache_key(indicator: str, params: dict[str, Any], timeframe: str | None = None) -> tuple:
    return (indicator, tuple(sorted(params.items())), timeframe)


# Caps how many distinct (indicator, params[, timeframe]) series arrays a
# single cache dict holds before evicting the oldest - relevant now that
# main.py's workers keep ONE cache dict alive across many/all tasks (see
# evaluate_condition_tree's docstring), so without a cap it would grow for
# the whole lifetime of a large batch. Simple FIFO (dict insertion order),
# not true LRU - good enough since a long-running worker's distinct
# (indicator, params) combinations cluster early rather than being
# revisited in a hot-and-cold pattern that would make FIFO much worse than
# LRU. 500 entries * ~4.6MB/array (a 578k-bar 15m dataset's float64 series)
# is a generous ~2.3GB worst case per worker, rarely approached in practice
# since auto-generated candidates reuse far fewer distinct combinations
# than that.
_MAX_CACHED_SERIES = 500


def _is_protected_cache_key(key: Any) -> bool:
    """Context keys (__symbol__/__base_timeframe__) and loaded MTF
    dataframes (__mtf_df__ tuples - few in number, expensive to reload,
    always worth keeping) are never eviction candidates - only the
    per-series numpy arrays _resolve_series/_resolve_mtf_series add are."""
    if isinstance(key, str) and key.startswith("__"):
        return True
    if isinstance(key, tuple) and key and isinstance(key[0], str) and key[0].startswith("__"):
        return True
    return False


def _evict_oldest_series_if_full(cache: dict) -> None:
    if len(cache) <= _MAX_CACHED_SERIES:
        return
    for key in cache:
        if not _is_protected_cache_key(key):
            del cache[key]
            return


def _resolve_mtf_series(
    df: pd.DataFrame, cache: dict, indicator: str, params: dict[str, Any], timeframe: str
) -> np.ndarray:
    # Callers that pass cache=None to evaluate_condition_tree() (the
    # default - walk_forward.py, the manual builder's api_server.py path,
    # etc) get a fresh cache per call as before, so nothing here is ever
    # reused beyond one evaluate_condition_tree() call for them. Callers
    # that deliberately keep ONE cache dict alive across many calls sharing
    # the exact same df (main.py's ProcessPoolExecutor workers - see
    # evaluate_condition_tree's docstring) DO get MTF series reused across
    # calls now - safe there specifically because that df (and therefore
    # its date range) never changes for that cache's whole lifetime, unlike
    # walk_forward.py's per-window date-sliced dataframes, which is exactly
    # why walk_forward.py must never opt into a shared cache.
    symbol = cache.get("__symbol__")
    if symbol is None:
        raise ValueError(
            "マルチタイムフレーム条件(timeframe指定)を使うにはsymbolが必要です"
            "(evaluate_condition_treeにsymbol引数を渡してください)"
        )

    mtf_df_key = ("__mtf_df__", symbol, timeframe)
    if mtf_df_key not in cache:
        cache[mtf_df_key] = load_price_data(find_data_file(timeframe, symbol))
    tf_df = cache[mtf_df_key]

    series_key = _cache_key(indicator, params, timeframe)
    if series_key not in cache:
        _evict_oldest_series_if_full(cache)
        raw = INDICATOR_REGISTRY[indicator](tf_df, **params)
        cache[series_key] = _align_mtf_series(df["datetime"], tf_df["datetime"], raw)

    return cache[series_key]


def _resolve_series(
    df: pd.DataFrame, cache: dict, indicator: str, params: dict[str, Any], timeframe: str | None = None
) -> np.ndarray:
    if indicator not in INDICATOR_REGISTRY:
        raise ValueError(f"未知のindicatorです: {indicator}")

    # A timeframe matching the backtest's own base timeframe is treated
    # exactly like no timeframe at all (see _infer_timeframe_label's
    # docstring) - only a genuinely different timeframe goes through the
    # multi-timeframe alignment path.
    if timeframe is not None and timeframe != cache.get("__base_timeframe__"):
        return _resolve_mtf_series(df, cache, indicator, params, timeframe)

    key = _cache_key(indicator, params)
    if key not in cache:
        _evict_oldest_series_if_full(cache)
        cache[key] = INDICATOR_REGISTRY[indicator](df, **params)

    return cache[key]


def _shift_forward_false(arr: np.ndarray) -> np.ndarray:
    """arr shifted by 1 bar (previous bar's value), with index 0 forced False."""
    shifted = np.roll(arr, 1)
    shifted[0] = False
    return shifted


@dataclass
class Condition:
    """One indicator compared against a literal value or another indicator.

    timeframe/value_timeframe (both optional, default None = the backtest's
    own base timeframe, today's existing behavior unchanged) let either side
    reference a DIFFERENT timeframe's data for the same symbol - e.g. a 15m
    backtest filtering entries by a 1h or daily EMA. Causally safe: only the
    most recently CLOSED bar of that other timeframe is ever visible to a
    given base bar (see _align_mtf_series)."""

    indicator: str
    operator: str
    value: Union[float, "Condition"]
    params: dict[str, Any] = field(default_factory=dict)
    value_params: dict[str, Any] = field(default_factory=dict)
    timeframe: str | None = None
    value_timeframe: str | None = None

    def __post_init__(self) -> None:
        if self.operator not in _OPERATORS:
            raise ValueError(f"未知のoperatorです: {self.operator}")

    def evaluate(self, df: pd.DataFrame, cache: dict) -> np.ndarray:
        left = _resolve_series(df, cache, self.indicator, self.params, self.timeframe)

        if isinstance(self.value, str):
            right = _resolve_series(df, cache, self.value, self.value_params, self.value_timeframe)
        else:
            right = float(self.value)

        if self.operator == ">":
            return left > right
        if self.operator == "<":
            return left < right
        if self.operator == ">=":
            return left >= right
        if self.operator == "<=":
            return left <= right
        if self.operator == "==":
            return left == right
        if self.operator == "crosses_above":
            above = left > right
            return above & ~_shift_forward_false(above)
        if self.operator == "crosses_below":
            below = left < right
            return below & ~_shift_forward_false(below)

        raise ValueError(f"未知のoperatorです: {self.operator}")

    def to_dict(self) -> dict:
        value = self.value.to_dict() if isinstance(self.value, Condition) else self.value
        return {
            "indicator": self.indicator,
            "operator": self.operator,
            "value": value,
            "params": self.params,
            "value_params": self.value_params,
            "timeframe": self.timeframe,
            "value_timeframe": self.value_timeframe,
        }

    @staticmethod
    def from_dict(data: dict) -> "Condition":
        value = data["value"]
        if isinstance(value, str):
            pass  # indicator name reference, kept as-is
        return Condition(
            indicator=data["indicator"],
            operator=data["operator"],
            value=value,
            params=dict(data.get("params", {})),
            value_params=dict(data.get("value_params", {})),
            timeframe=data.get("timeframe"),
            value_timeframe=data.get("value_timeframe"),
        )


@dataclass
class ConditionGroup:
    """AND/OR/NOT of child Condition/ConditionGroup nodes. NOT takes exactly one child."""

    op: str
    children: list[Union[Condition, "ConditionGroup"]]

    def __post_init__(self) -> None:
        if self.op not in {"AND", "OR", "NOT"}:
            raise ValueError(f"未知のopです(AND/OR/NOTのみ対応): {self.op}")
        if self.op == "NOT" and len(self.children) != 1:
            raise ValueError("NOTはchildrenを1つだけ指定してください")
        if not self.children:
            raise ValueError("childrenが空です")

    def evaluate(self, df: pd.DataFrame, cache: dict) -> np.ndarray:
        results = [child.evaluate(df, cache) for child in self.children]

        if self.op == "AND":
            return np.logical_and.reduce(results)
        if self.op == "OR":
            return np.logical_or.reduce(results)
        return ~results[0]

    def to_dict(self) -> dict:
        return {"op": self.op, "children": [child.to_dict() for child in self.children]}

    @staticmethod
    def from_dict(data: dict) -> "ConditionGroup":
        children = [node_from_dict(child) for child in data["children"]]
        return ConditionGroup(op=data["op"], children=children)


def node_from_dict(data: dict) -> Union[Condition, ConditionGroup]:
    if "op" in data:
        return ConditionGroup.from_dict(data)
    return Condition.from_dict(data)


def evaluate_condition_tree(
    tree: dict, df: pd.DataFrame, symbol: str | None = None, cache: dict | None = None
) -> np.ndarray:
    """Entry point used by engine/backtest_engine.py: JSON dict in, boolean array out.

    `symbol` is only required if the tree contains a node with a `timeframe`
    different from the backtest's own base timeframe (multi-timeframe
    conditions) - otherwise unused, so every pre-existing caller that never
    passes it keeps working unchanged.

    `cache` is optional and defaults to a fresh dict per call (existing
    behavior, unchanged for every caller that doesn't pass one - walk_forward.py,
    the manual builder's api_server.py path, etc). Passing in a dict the
    caller keeps ALIVE ACROSS MULTIPLE CALLS lets indicator arrays (ema,
    rsi, ...) be reused instead of recomputed whenever different generated
    trees happen to reference the same (indicator, params) pair - safe ONLY
    when every one of those calls shares the exact same `df` (same symbol/
    timeframe/date-range) for the cache's whole lifetime, which is exactly
    main.py's ProcessPoolExecutor worker model (one fixed `_WORKER_DF` per
    worker process, reused across every task that worker ever runs) but is
    NOT true of e.g. walk_forward.py's direct run_backtest() calls across
    different year-sliced windows in the same process - callers there must
    keep passing cache=None (the default) rather than opting into this."""
    node = node_from_dict(tree)
    if cache is None:
        cache = {}
    cache["__symbol__"] = symbol
    cache["__base_timeframe__"] = _infer_timeframe_label(df["datetime"])
    return node.evaluate(df, cache)
