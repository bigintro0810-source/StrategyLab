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

from engine.indicators import ema as _ema
from engine.indicators import rsi as _rsi
from engine.technical_indicators import bollinger_bands, macd, stochastic_oscillator


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


# Indicator name -> function(df, **params) -> np.ndarray[float]. Add new indicators
# here only - never touch Condition/ConditionGroup's evaluation logic to support one.
INDICATOR_REGISTRY: dict[str, Any] = {
    "close": lambda df, **p: df["close"].to_numpy(dtype=float),
    "open": lambda df, **p: df["open"].to_numpy(dtype=float),
    "high": lambda df, **p: df["high"].to_numpy(dtype=float),
    "low": lambda df, **p: df["low"].to_numpy(dtype=float),
    "hour": lambda df, **p: pd.to_datetime(df["datetime"]).dt.hour.to_numpy(dtype=float),
    "weekday": lambda df, **p: pd.to_datetime(df["datetime"]).dt.weekday.to_numpy(dtype=float),
    "candle_body": lambda df, **p: (df["close"] - df["open"]).to_numpy(dtype=float),
    "ema": lambda df, length=200, **p: _ema(df["close"], int(length)).to_numpy(dtype=float),
    "rsi": lambda df, length=14, **p: _rsi(df["close"], int(length)).to_numpy(dtype=float),
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
}

_OPERATORS = {">", "<", ">=", "<=", "==", "crosses_above", "crosses_below"}


def _cache_key(indicator: str, params: dict[str, Any]) -> tuple:
    return (indicator, tuple(sorted(params.items())))


def _resolve_series(df: pd.DataFrame, cache: dict, indicator: str, params: dict[str, Any]) -> np.ndarray:
    if indicator not in INDICATOR_REGISTRY:
        raise ValueError(f"未知のindicatorです: {indicator}")

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
    """One indicator compared against a literal value or another indicator."""

    indicator: str
    operator: str
    value: Union[float, "Condition"]
    params: dict[str, Any] = field(default_factory=dict)
    value_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.operator not in _OPERATORS:
            raise ValueError(f"未知のoperatorです: {self.operator}")

    def evaluate(self, df: pd.DataFrame, cache: dict) -> np.ndarray:
        left = _resolve_series(df, cache, self.indicator, self.params)

        if isinstance(self.value, str):
            right = _resolve_series(df, cache, self.value, self.value_params)
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


def evaluate_condition_tree(tree: dict, df: pd.DataFrame) -> np.ndarray:
    """Entry point used by engine/backtest_engine.py: JSON dict in, boolean array out."""
    node = node_from_dict(tree)
    cache: dict = {}
    return node.evaluate(df, cache)
