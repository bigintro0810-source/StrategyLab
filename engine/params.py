"""Single source of truth for reconstructing a params dict from a CSV row.

Previously duplicated: main.py::build_best_params() and
walk_forward.py::build_params_from_row() were separate copies of the same
whitelist, and had already drifted (walk_forward.py's copy was missing
pip_size). Both now call this instead.
"""

import ast
from typing import Any

DEFAULT_PIP_SIZE = 0.01


def _reconstruct_tree(row: dict[str, Any], key: str) -> dict | None:
    """condition_tree (and long_condition_tree/short_condition_tree) survive a
    CSV round-trip as a Python-repr string (pandas str()-ifies dict cells),
    not JSON - e.g. "{'op': 'AND', ...}" with single quotes, so it needs
    ast.literal_eval rather than json.loads."""
    raw = row.get(key)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return ast.literal_eval(raw)
    return None


def reconstruct_params_from_row(row: dict[str, Any]) -> dict:
    return {
        "condition_tree": _reconstruct_tree(row, "condition_tree"),
        "long_condition_tree": _reconstruct_tree(row, "long_condition_tree"),
        "short_condition_tree": _reconstruct_tree(row, "short_condition_tree"),
        "ema_length": int(row["ema_length"]),
        "min_body_pips": float(row["min_body_pips"]),
        "max_body_pips": float(row["max_body_pips"]),
        "max_wick_pips": float(row["max_wick_pips"]),
        "lookahead_bars": int(row["lookahead_bars"]),
        "breakout_bars": int(row["breakout_bars"]),
        "ema_distance_pips": float(row["ema_distance_pips"]),
        "rsi_min": float(row["rsi_min"]),
        "rr": float(row["rr"]),
        "spread_pips": float(row.get("spread_pips", 0.0)),
        "slippage_pips": float(row.get("slippage_pips", 0.0)),
        "commission_per_trade": float(row.get("commission_per_trade", 0.0)),
        "session_start": int(row["session_start"]),
        "session_end": int(row["session_end"]),
        "use_weekend_exit": bool(row["use_weekend_exit"]),
        "weekend_exit_hour": int(row["weekend_exit_hour"]),
        "use_daily_exit": bool(row["use_daily_exit"]),
        "daily_exit_hour": int(row["daily_exit_hour"]),
        "pip_size": float(row.get("pip_size", DEFAULT_PIP_SIZE)),
        "direction": str(row.get("direction", "short")),
        # V3.0 trigger/filter schema - .get() with defaults so rows from
        # before this schema existed (older saved runs/ranking CSVs) still
        # reconstruct cleanly, reproducing the pre-V3.0 breakout strategy.
        "entry_trigger": str(row.get("entry_trigger", "breakout")),
        "use_session_filter": bool(row.get("use_session_filter", True)),
        "use_min_body_filter": bool(row.get("use_min_body_filter", True)),
        "use_max_body_filter": bool(row.get("use_max_body_filter", True)),
        "use_max_wick_filter": bool(row.get("use_max_wick_filter", True)),
        "use_ema_distance_filter": bool(row.get("use_ema_distance_filter", True)),
        "use_rsi_filter": bool(row.get("use_rsi_filter", True)),
        "use_donchian_filter": bool(row.get("use_donchian_filter", False)),
        "donchian_period": int(row.get("donchian_period", 20)),
        "use_bollinger_filter": bool(row.get("use_bollinger_filter", False)),
        "bollinger_period": int(row.get("bollinger_period", 20)),
        "bollinger_std": float(row.get("bollinger_std", 2.0)),
        "use_macd_filter": bool(row.get("use_macd_filter", False)),
        "macd_fast": int(row.get("macd_fast", 12)),
        "macd_slow": int(row.get("macd_slow", 26)),
        "macd_signal": int(row.get("macd_signal", 9)),
        "use_ichimoku_filter": bool(row.get("use_ichimoku_filter", False)),
        "ichimoku_tenkan": int(row.get("ichimoku_tenkan", 9)),
        "ichimoku_kijun": int(row.get("ichimoku_kijun", 26)),
        "ichimoku_senkou_b": int(row.get("ichimoku_senkou_b", 52)),
        "use_stochastic_filter": bool(row.get("use_stochastic_filter", False)),
        "stochastic_k_period": int(row.get("stochastic_k_period", 14)),
        "stochastic_d_period": int(row.get("stochastic_d_period", 3)),
        "stochastic_smooth": int(row.get("stochastic_smooth", 3)),
        "stochastic_level": float(row.get("stochastic_level", 80.0)),
        "use_pivot_filter": bool(row.get("use_pivot_filter", False)),
        "use_prev_high_filter": bool(row.get("use_prev_high_filter", False)),
        "use_prev_low_filter": bool(row.get("use_prev_low_filter", False)),
        "use_round_number_filter": bool(row.get("use_round_number_filter", False)),
        "round_number_pips": float(row.get("round_number_pips", 10.0)),
        "use_weekday_filter": bool(row.get("use_weekday_filter", False)),
        "weekday_monday": bool(row.get("weekday_monday", True)),
        "weekday_tuesday": bool(row.get("weekday_tuesday", True)),
        "weekday_wednesday": bool(row.get("weekday_wednesday", True)),
        "weekday_thursday": bool(row.get("weekday_thursday", True)),
        "weekday_friday": bool(row.get("weekday_friday", True)),
        "adr_period": int(row.get("adr_period", 14)),
        "use_fvg_filter": bool(row.get("use_fvg_filter", False)),
        "use_order_block_filter": bool(row.get("use_order_block_filter", False)),
        "use_bos_filter": bool(row.get("use_bos_filter", False)),
        "use_choch_filter": bool(row.get("use_choch_filter", False)),
        "use_liquidity_sweep_filter": bool(row.get("use_liquidity_sweep_filter", False)),
        "smc_swing_lookback": int(row.get("smc_swing_lookback", 5)),
        "use_supertrend_filter": bool(row.get("use_supertrend_filter", False)),
        "supertrend_period": int(row.get("supertrend_period", 10)),
        "supertrend_multiplier": float(row.get("supertrend_multiplier", 3.0)),
        "use_adx_filter": bool(row.get("use_adx_filter", False)),
        "adx_period": int(row.get("adx_period", 14)),
        "adx_threshold": float(row.get("adx_threshold", 25.0)),
    }
