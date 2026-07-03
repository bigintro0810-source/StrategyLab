"""Locks in known-good results for every V3.0 entry_trigger and filter.

tests/test_regression.py only ever exercises the default "breakout"
trigger with the six original (always-on) filters - none of the Tier 1/2/3
work landing 2026-07-03 (engine/triggers.py, engine/filters.py,
engine/smc_indicators.py, engine/technical_indicators.py's SuperTrend/ADX)
had any regression coverage at all before this file. That's a real blind
spot: a refactor could silently break any of these 16 triggers or 17 new
filters and nothing would notice.

Not pytest-based (matches tests/test_regression.py's convention - no
pytest dependency, no requirements.txt entry for it) - run directly:
`python tests/test_regression_indicators.py`.

Baselines generated 2026-07-03 against real USDJPY 15m data, current at
that commit. A 0-trades baseline (several filters, e.g. use_fvg_filter,
use_bos_filter) is a legitimate, deterministic result given how
restrictive ANDing a rare SMC condition onto the already-selective
default breakout trigger is - not a placeholder to "fix" later.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import find_data_file, load_price_data
from engine.backtest_engine import run_backtest, compute_is_intraday

TOLERANCE = 1e-3

BASE_PARAMS = {
    "ema_length": 200,
    "min_body_pips": 20.0,
    "max_body_pips": 0.0,
    "max_wick_pips": 0.0,
    "lookahead_bars": 15,
    "breakout_bars": 30,
    "ema_distance_pips": 50.0,
    "rsi_min": 70.0,
    "rr": 1.2,
    "session_start": 8,
    "session_end": 3,
    "use_weekend_exit": True,
    "weekend_exit_hour": 4,
    "use_daily_exit": False,
    "daily_exit_hour": 4,
    "pip_size": 0.01,
}

# Non-default triggers, tested with the three usually-on filters relaxed
# so each trigger's own behavior (not the unrelated default filters)
# drives the result. "breakout" itself is already covered by
# tests/test_regression.py.
TRIGGER_CASES = {
    "donchian_breakout": {"trades": 5135, "net_profit": 11.0348, "profit_factor": 1.024},
    "ema_cross": {"trades": 2773, "net_profit": -33.6124, "profit_factor": 0.865},
    "macd_cross": {"trades": 8439, "net_profit": 24.8058, "profit_factor": 1.041},
    "bollinger_touch": {"trades": 4885, "net_profit": 16.7122, "profit_factor": 1.038},
    "ichimoku_cloud_breakout": {"trades": 4223, "net_profit": 3.2212, "profit_factor": 1.01},
    "ichimoku_tk_cross": {"trades": 6796, "net_profit": 8.828, "profit_factor": 1.018},
    "stochastic_kd_cross": {"trades": 15376, "net_profit": -0.2412, "profit_factor": 1.0},
    "stochastic_level_cross": {"trades": 8238, "net_profit": 6.4016, "profit_factor": 1.011},
    "fvg_bearish": {"trades": 12883, "net_profit": -22.7446, "profit_factor": 0.978},
    "order_block_bearish": {"trades": 24335, "net_profit": -8.1518, "profit_factor": 0.995},
    "bos_bearish": {"trades": 2991, "net_profit": -23.2212, "profit_factor": 0.933},
    "choch_bearish": {"trades": 4477, "net_profit": -7.0788, "profit_factor": 0.985},
    "liquidity_sweep_bearish": {"trades": 7261, "net_profit": 42.5722, "profit_factor": 1.073},
    "supertrend_flip_bearish": {"trades": 4231, "net_profit": -3.4812, "profit_factor": 0.992},
    "adx_di_cross_bearish": {"trades": 8453, "net_profit": 10.4376, "profit_factor": 1.014},
}

TRIGGER_TEST_OVERRIDES = {
    "use_ema_distance_filter": False,
    "use_rsi_filter": False,
    "use_min_body_filter": False,
}

# New (Tier 1/2/3) filters, each tested ANDed onto the default breakout
# trigger with everything else at its default. The six original filters
# (session/min_body/max_body/max_wick/ema_distance/rsi) are already
# covered by tests/test_regression.py's default-path baseline.
FILTER_CASES = {
    "use_donchian_filter": {"trades": 169, "net_profit": 13.0438, "profit_factor": 1.412},
    "use_bollinger_filter": {"trades": 169, "net_profit": 13.0438, "profit_factor": 1.412},
    "use_macd_filter": {"trades": 163, "net_profit": 12.3242, "profit_factor": 1.398},
    "use_ichimoku_filter": {"trades": 169, "net_profit": 13.0438, "profit_factor": 1.412},
    "use_stochastic_filter": {"trades": 146, "net_profit": 8.4584, "profit_factor": 1.301},
    "use_pivot_filter": {"trades": 132, "net_profit": 16.0074, "profit_factor": 1.717},
    "use_prev_high_filter": {"trades": 151, "net_profit": 15.9572, "profit_factor": 1.601},
    "use_prev_low_filter": {"trades": 169, "net_profit": 13.0438, "profit_factor": 1.412},
    "use_round_number_filter": {"trades": 27, "net_profit": -1.8644, "profit_factor": 0.715},
    "use_weekday_filter": {"trades": 166, "net_profit": 13.5518, "profit_factor": 1.435},
    "use_fvg_filter": {"trades": 0, "net_profit": 0.0, "profit_factor": 0.0},
    "use_order_block_filter": {"trades": 10, "net_profit": 1.7218, "profit_factor": 1.82},
    "use_bos_filter": {"trades": 0, "net_profit": 0.0, "profit_factor": 0.0},
    "use_choch_filter": {"trades": 0, "net_profit": 0.0, "profit_factor": 0.0},
    "use_liquidity_sweep_filter": {"trades": 0, "net_profit": 0.0, "profit_factor": 0.0},
    "use_supertrend_filter": {"trades": 0, "net_profit": 0.0, "profit_factor": 0.0},
    "use_adx_filter": {"trades": 131, "net_profit": 10.4108, "profit_factor": 1.441},
}


def _check(label: str, result: dict, expected: dict) -> list[str]:
    failures = []
    for key, expected_value in expected.items():
        actual_value = result[key]
        if abs(actual_value - expected_value) > TOLERANCE:
            failures.append(f"[{label}] {key}: expected {expected_value}, got {actual_value}")
    return failures


def main() -> None:
    df = load_price_data(find_data_file("15m", "USDJPY"))
    is_intraday = compute_is_intraday(df["datetime"])

    all_failures = []

    for trigger_name, expected in TRIGGER_CASES.items():
        params = dict(BASE_PARAMS, entry_trigger=trigger_name, **TRIGGER_TEST_OVERRIDES)
        result = run_backtest(df, params, is_intraday=is_intraday)
        failures = _check(f"trigger:{trigger_name}", result, expected)
        if failures:
            all_failures.extend(failures)
        else:
            print(f"PASS: trigger {trigger_name}")

    for flag_name, expected in FILTER_CASES.items():
        params = dict(BASE_PARAMS, **{flag_name: True})
        result = run_backtest(df, params, is_intraday=is_intraday)
        failures = _check(f"filter:{flag_name}", result, expected)
        if failures:
            all_failures.extend(failures)
        else:
            print(f"PASS: filter {flag_name}")

    if all_failures:
        print("FAIL")
        for failure in all_failures:
            print(f"  {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
