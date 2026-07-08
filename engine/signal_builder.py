"""Composition layer: pick an entry trigger, AND in every enabled filter.

Mirrors engine/condition_engine.py's `signal &= condition` composition
style (that module itself is not imported here - it models a different,
simpler strategy shape; only its composition style is mirrored).

Each indicator array is computed only when the currently selected
entry_trigger needs it or its corresponding use_X_filter flag is on (see
_build_indicator_arrays' own docstring) - previously computed
unconditionally regardless of whether anything in the current params dict
actually read it. Profiling found this mattering concretely: SuperTrend
alone cost ~3s/call for a strategy that doesn't even use it (this file's
own prior docstring called the always-compute approach "worth revisiting
only if profiling ever shows this mattering" - it now does).
"""

from typing import Any

import numpy as np
import pandas as pd

from engine.filters import FILTER_REGISTRY
from engine.smc_indicators import (
    bearish_fvg,
    bearish_order_block,
    bos_choch_bearish,
    liquidity_sweep_bearish,
)
from engine.technical_indicators import (
    adx,
    bollinger_bands,
    daily_reference_levels,
    donchian_channel,
    ichimoku,
    macd,
    round_number_distance_pips,
    stochastic_oscillator,
    supertrend,
)
from engine.triggers import TRIGGER_REGISTRY


def _build_indicator_arrays(
    df: pd.DataFrame,
    p: dict[str, Any],
    precomputed: dict[str, Any],
) -> dict[str, Any]:
    """Each block below is gated behind "is the currently selected
    entry_trigger this one, OR is the matching use_X_filter flag on" -
    matches engine/triggers.py::TRIGGER_REGISTRY / engine/filters.py::
    FILTER_REGISTRY exactly, so skipping a block is safe by construction:
    nothing downstream ever reads that precomputed key unless the trigger/
    filter that reads it is the one active."""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    entry_trigger = p.get("entry_trigger", "breakout")

    def _enabled(flag_name: str) -> bool:
        return bool(p.get(flag_name, False))

    if entry_trigger == "donchian_breakout" or _enabled("use_donchian_filter"):
        donchian_period = int(p.get("donchian_period", 20))
        donchian_upper, donchian_lower = donchian_channel(high, low, donchian_period)
        # Shift so the current bar isn't part of its own channel, matching
        # the "previous N bars" semantics of breakout_bars/previous_high_arr.
        precomputed["donchian_upper"] = donchian_upper.shift(1).to_numpy(dtype=float)
        precomputed["donchian_lower"] = donchian_lower.shift(1).to_numpy(dtype=float)

    if entry_trigger == "bollinger_touch" or _enabled("use_bollinger_filter"):
        bollinger_period = int(p.get("bollinger_period", 20))
        bollinger_std = float(p.get("bollinger_std", 2.0))
        b_upper, b_middle, _b_lower = bollinger_bands(close, bollinger_period, bollinger_std)
        precomputed["bollinger_upper"] = b_upper.to_numpy(dtype=float)
        precomputed["bollinger_middle"] = b_middle.to_numpy(dtype=float)

    if entry_trigger == "macd_cross" or _enabled("use_macd_filter"):
        macd_fast = int(p.get("macd_fast", 12))
        macd_slow = int(p.get("macd_slow", 26))
        macd_signal_period = int(p.get("macd_signal", 9))
        macd_line, macd_signal, _macd_hist = macd(close, macd_fast, macd_slow, macd_signal_period)
        precomputed["macd_line"] = macd_line.to_numpy(dtype=float)
        precomputed["macd_signal"] = macd_signal.to_numpy(dtype=float)

    if entry_trigger in ("ichimoku_cloud_breakout", "ichimoku_tk_cross") or _enabled("use_ichimoku_filter"):
        tenkan_period = int(p.get("ichimoku_tenkan", 9))
        kijun_period = int(p.get("ichimoku_kijun", 26))
        senkou_b_period = int(p.get("ichimoku_senkou_b", 52))
        tenkan, kijun, senkou_a, senkou_b = ichimoku(
            high, low, tenkan_period, kijun_period, senkou_b_period
        )
        precomputed["ichimoku_tenkan"] = tenkan.to_numpy(dtype=float)
        precomputed["ichimoku_kijun"] = kijun.to_numpy(dtype=float)
        precomputed["ichimoku_senkou_a"] = senkou_a.to_numpy(dtype=float)
        precomputed["ichimoku_senkou_b"] = senkou_b.to_numpy(dtype=float)

    if entry_trigger in ("stochastic_kd_cross", "stochastic_level_cross") or _enabled("use_stochastic_filter"):
        stochastic_k_period = int(p.get("stochastic_k_period", 14))
        stochastic_d_period = int(p.get("stochastic_d_period", 3))
        stochastic_smooth = int(p.get("stochastic_smooth", 3))
        stoch_k, stoch_d = stochastic_oscillator(
            high, low, close, stochastic_k_period, stochastic_d_period, stochastic_smooth
        )
        precomputed["stochastic_k"] = stoch_k.to_numpy(dtype=float)
        precomputed["stochastic_d"] = stoch_d.to_numpy(dtype=float)

    if _enabled("use_pivot_filter") or _enabled("use_prev_high_filter") or _enabled("use_prev_low_filter"):
        adr_period = int(p.get("adr_period", 14))
        daily_ref = daily_reference_levels(df, adr_period)
        precomputed["prev_day_high"] = daily_ref["prev_day_high"].to_numpy(dtype=float)
        precomputed["prev_day_low"] = daily_ref["prev_day_low"].to_numpy(dtype=float)
        precomputed["pivot_r1"] = daily_ref["r1"].to_numpy(dtype=float)
        precomputed["pivot_s1"] = daily_ref["s1"].to_numpy(dtype=float)

    if _enabled("use_round_number_filter"):
        precomputed["round_number_distance"] = round_number_distance_pips(
            close, precomputed["pip"]
        ).to_numpy(dtype=float)

    # Tier 3 (SMC) - unverified against TradingView, see engine/smc_indicators.py.
    smc_triggers = (
        "fvg_bearish", "order_block_bearish", "bos_bearish",
        "choch_bearish", "liquidity_sweep_bearish",
    )
    smc_filter_flags = (
        "use_fvg_filter", "use_order_block_filter", "use_bos_filter",
        "use_choch_filter", "use_liquidity_sweep_filter",
    )
    if entry_trigger in smc_triggers or any(_enabled(flag) for flag in smc_filter_flags):
        smc_swing_lookback = int(p.get("smc_swing_lookback", 5))
        precomputed["smc_fvg_bearish"] = bearish_fvg(high, low)
        precomputed["smc_order_block_bearish"] = bearish_order_block(df["open"], close)
        precomputed["smc_liquidity_sweep_bearish"] = liquidity_sweep_bearish(
            high, low, close, smc_swing_lookback
        )
        bos_arr, choch_arr = bos_choch_bearish(high, low, close, smc_swing_lookback)
        precomputed["smc_bos_bearish"] = bos_arr
        precomputed["smc_choch_bearish"] = choch_arr

    # Tier 2 - depends on Wilder ATR, unblocked 2026-07-03 (see
    # engine/technical_indicators.py's module docstring). By far the most
    # expensive single indicator here (profiled ~3s/call) - the main reason
    # this whole function is no longer unconditional.
    if entry_trigger == "supertrend_flip_bearish" or _enabled("use_supertrend_filter"):
        supertrend_period = int(p.get("supertrend_period", 10))
        supertrend_multiplier = float(p.get("supertrend_multiplier", 3.0))
        _supertrend_line, supertrend_direction = supertrend(
            high, low, close, supertrend_period, supertrend_multiplier
        )
        precomputed["supertrend_direction"] = supertrend_direction

    if entry_trigger == "adx_di_cross_bearish" or _enabled("use_adx_filter"):
        adx_period = int(p.get("adx_period", 14))
        plus_di, minus_di, adx_line = adx(high, low, close, adx_period)
        precomputed["adx_plus_di"] = plus_di.to_numpy(dtype=float)
        precomputed["adx_minus_di"] = minus_di.to_numpy(dtype=float)
        precomputed["adx_line"] = adx_line.to_numpy(dtype=float)

    return precomputed


def build_candidate_signal(
    df: pd.DataFrame,
    p: dict[str, Any],
    precomputed: dict[str, Any],
) -> np.ndarray:
    precomputed = _build_indicator_arrays(df, p, precomputed)

    entry_trigger = p.get("entry_trigger", "breakout")
    trigger_fn = TRIGGER_REGISTRY.get(entry_trigger)

    if trigger_fn is None:
        raise ValueError(f"未知のentry_triggerです: {entry_trigger}")

    signal = trigger_fn(df, p, precomputed)

    for flag_name, default_enabled, filter_fn in FILTER_REGISTRY:
        if p.get(flag_name, default_enabled):
            signal = signal & filter_fn(df, p, precomputed)

    return signal
