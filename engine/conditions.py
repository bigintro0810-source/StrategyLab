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
from engine.technical_indicators import daily_vwap as _daily_vwap
from engine.technical_indicators import supertrend as _supertrend
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
from engine.data_loader import find_data_file, load_price_data

_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
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


def _vwap(df: pd.DataFrame) -> np.ndarray:
    if "volume" not in df.columns:
        raise ValueError(
            "VWAPにはvolume列が必要ですが、この価格データにはありません"
            "(volume列を含むデータソースを使用してください)"
        )
    return _daily_vwap(df["high"], df["low"], df["close"], df["volume"], df["datetime"]).to_numpy(dtype=float)


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
}

_OPERATORS = {">", "<", ">=", "<=", "==", "crosses_above", "crosses_below"}


def _cache_key(indicator: str, params: dict[str, Any], timeframe: str | None = None) -> tuple:
    return (indicator, tuple(sorted(params.items())), timeframe)


def _resolve_mtf_series(
    df: pd.DataFrame, cache: dict, indicator: str, params: dict[str, Any], timeframe: str
) -> np.ndarray:
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


def evaluate_condition_tree(tree: dict, df: pd.DataFrame, symbol: str | None = None) -> np.ndarray:
    """Entry point used by engine/backtest_engine.py: JSON dict in, boolean array out.

    `symbol` is only required if the tree contains a node with a `timeframe`
    different from the backtest's own base timeframe (multi-timeframe
    conditions) - otherwise unused, so every pre-existing caller that never
    passes it keeps working unchanged."""
    node = node_from_dict(tree)
    cache: dict = {
        "__symbol__": symbol,
        "__base_timeframe__": _infer_timeframe_label(df["datetime"]),
    }
    return node.evaluate(df, cache)
