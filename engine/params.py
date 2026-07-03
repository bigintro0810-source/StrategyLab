"""Single source of truth for reconstructing a params dict from a CSV row.

Previously duplicated: main.py::build_best_params() and
walk_forward.py::build_params_from_row() were separate copies of the same
whitelist, and had already drifted (walk_forward.py's copy was missing
pip_size). Both now call this instead.
"""

from typing import Any

DEFAULT_PIP_SIZE = 0.01


def reconstruct_params_from_row(row: dict[str, Any]) -> dict:
    return {
        "ema_length": int(row["ema_length"]),
        "min_body_pips": float(row["min_body_pips"]),
        "max_body_pips": float(row["max_body_pips"]),
        "max_wick_pips": float(row["max_wick_pips"]),
        "lookahead_bars": int(row["lookahead_bars"]),
        "breakout_bars": int(row["breakout_bars"]),
        "ema_distance_pips": float(row["ema_distance_pips"]),
        "rsi_min": float(row["rsi_min"]),
        "rr": float(row["rr"]),
        "session_start": int(row["session_start"]),
        "session_end": int(row["session_end"]),
        "use_weekend_exit": bool(row["use_weekend_exit"]),
        "weekend_exit_hour": int(row["weekend_exit_hour"]),
        "use_daily_exit": bool(row["use_daily_exit"]),
        "daily_exit_hour": int(row["daily_exit_hour"]),
        "pip_size": float(row.get("pip_size", DEFAULT_PIP_SIZE)),
    }
