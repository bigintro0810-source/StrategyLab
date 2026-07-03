"""Independently toggleable filter functions (V3.0 条件ベースのストラテジー定義).

Each filter takes the same `(df, p, precomputed)` shape as engine/triggers.py
and returns np.ndarray[bool] - True where the filter's condition holds.
engine/signal_builder.py ANDs together whichever filters are enabled via
their `use_X` flag in `p`.

The first six filters below are extracted verbatim from the original inline
condition chain in engine/backtest_engine.py (each one previously an
unconditional `continue` guard, now individually toggleable but defaulting
to True/on so default behavior is unchanged). The remaining filters are new
(V3.0 Tier 1), default off (additive only).
"""

from typing import Any

import numpy as np


def filter_session(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]

    if not precomputed["is_intraday"]:
        return np.ones(len(close_arr), dtype=bool)

    hour_arr = precomputed["hour"]
    start = int(p["session_start"])
    end = int(p["session_end"])

    if start < end:
        return (hour_arr >= start) & (hour_arr < end)

    return (hour_arr >= start) | (hour_arr < end)


def filter_min_body(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]
    open_arr = precomputed["open"]
    min_body_price = float(p["min_body_pips"]) * precomputed["pip"]

    return (close_arr - open_arr) >= min_body_price


def filter_max_body(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]
    max_body_pips = float(p["max_body_pips"])

    if max_body_pips <= 0:
        return np.ones(len(close_arr), dtype=bool)

    open_arr = precomputed["open"]
    body_pips = np.abs(close_arr - open_arr) / precomputed["pip"]

    return body_pips <= max_body_pips


def filter_max_wick(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]
    max_wick_pips = float(p["max_wick_pips"])

    if max_wick_pips <= 0:
        return np.ones(len(close_arr), dtype=bool)

    high_arr = precomputed["high"]
    low_arr = precomputed["low"]
    wick_pips = (high_arr - low_arr) / precomputed["pip"]

    return wick_pips <= max_wick_pips


def filter_ema_distance(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]
    ema_arr = precomputed["ema"]
    ema_distance_price = float(p["ema_distance_pips"]) * precomputed["pip"]
    ema_distance = close_arr - ema_arr

    return (close_arr > ema_arr) & (ema_distance >= ema_distance_price)


def filter_rsi(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    rsi_arr = precomputed["rsi"]
    rsi_min = float(p["rsi_min"])

    return rsi_arr > rsi_min


def filter_donchian(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]
    midpoint = (precomputed["donchian_upper"] + precomputed["donchian_lower"]) / 2

    return close_arr > midpoint


def filter_bollinger(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    return precomputed["close"] > precomputed["bollinger_middle"]


def filter_macd(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    return precomputed["macd_line"] > precomputed["macd_signal"]


def filter_ichimoku(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]
    cloud_top = np.maximum(precomputed["ichimoku_senkou_a"], precomputed["ichimoku_senkou_b"])

    return close_arr > cloud_top


def filter_stochastic(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    return precomputed["stochastic_k"] > precomputed["stochastic_d"]


def filter_pivot(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    return precomputed["close"] > precomputed["pivot_r1"]


def filter_prev_high(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    return precomputed["close"] > precomputed["prev_day_high"]


def filter_prev_low(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    return precomputed["close"] > precomputed["prev_day_low"]


def filter_round_number(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    threshold = float(p.get("round_number_pips", 10.0))

    return precomputed["round_number_distance"] <= threshold


def filter_weekday(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    weekday_arr = precomputed["weekday"]
    signal = np.zeros(len(weekday_arr), dtype=bool)

    if p.get("weekday_monday", True):
        signal |= weekday_arr == 0
    if p.get("weekday_tuesday", True):
        signal |= weekday_arr == 1
    if p.get("weekday_wednesday", True):
        signal |= weekday_arr == 2
    if p.get("weekday_thursday", True):
        signal |= weekday_arr == 3
    if p.get("weekday_friday", True):
        signal |= weekday_arr == 4

    return signal


def filter_fvg(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """SMC Tier 3 - unverified against TradingView, see engine/smc_indicators.py."""
    return precomputed["smc_fvg_bearish"]


def filter_order_block(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """SMC Tier 3 - unverified against TradingView, see engine/smc_indicators.py."""
    return precomputed["smc_order_block_bearish"]


def filter_bos(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """SMC Tier 3 - unverified against TradingView, see engine/smc_indicators.py."""
    return precomputed["smc_bos_bearish"]


def filter_choch(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """SMC Tier 3 - unverified against TradingView, see engine/smc_indicators.py."""
    return precomputed["smc_choch_bearish"]


def filter_liquidity_sweep(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """SMC Tier 3 - unverified against TradingView, see engine/smc_indicators.py."""
    return precomputed["smc_liquidity_sweep_bearish"]


def filter_supertrend(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """SuperTrend is currently in a downtrend (bearish context)."""
    return precomputed["supertrend_direction"] == -1


def filter_adx(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """ADX above threshold - a strong trend is present (non-directional)."""
    adx_threshold = float(p.get("adx_threshold", 25.0))
    return precomputed["adx_line"] > adx_threshold


# (use_flag key, default enabled, filter function) - order matches the
# original inline condition chain for the first six (auditability against
# the pre-refactor code), then new Tier-1 filters, then Tier-3 SMC filters,
# then Tier-2 filters.
FILTER_REGISTRY: list[tuple[str, bool, Any]] = [
    ("use_session_filter", True, filter_session),
    ("use_min_body_filter", True, filter_min_body),
    ("use_max_body_filter", True, filter_max_body),
    ("use_max_wick_filter", True, filter_max_wick),
    ("use_ema_distance_filter", True, filter_ema_distance),
    ("use_rsi_filter", True, filter_rsi),
    ("use_donchian_filter", False, filter_donchian),
    ("use_bollinger_filter", False, filter_bollinger),
    ("use_macd_filter", False, filter_macd),
    ("use_ichimoku_filter", False, filter_ichimoku),
    ("use_stochastic_filter", False, filter_stochastic),
    ("use_pivot_filter", False, filter_pivot),
    ("use_prev_high_filter", False, filter_prev_high),
    ("use_prev_low_filter", False, filter_prev_low),
    ("use_round_number_filter", False, filter_round_number),
    ("use_weekday_filter", False, filter_weekday),
    ("use_fvg_filter", False, filter_fvg),
    ("use_order_block_filter", False, filter_order_block),
    ("use_bos_filter", False, filter_bos),
    ("use_choch_filter", False, filter_choch),
    ("use_liquidity_sweep_filter", False, filter_liquidity_sweep),
    ("use_supertrend_filter", False, filter_supertrend),
    ("use_adx_filter", False, filter_adx),
]
