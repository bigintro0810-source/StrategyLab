"""Locks in known-good results for the new direction="long" + condition_tree path
(engine/conditions.py + engine/backtest_engine.py's direction-aware entry/exit
mechanics), added 2026-07-05 per the Strategy Lab project charter (long/short must be
freely switchable, no hardcoded short-only design).

Not pytest-based (matches this project's other tests/test_*.py convention) - run
directly: `python tests/test_regression_long.py`.

The example strategy is a breakdown-and-fade mirror of the existing default short
breakout strategy: bearish candle, close breaks below the recent 30-bar low, RSI(14)
< 30 (oversold), close below EMA(200) - direction="long" (buy the oversold bounce).
Baseline captured 2026-07-05 by actually running this against real USDJPY 15m data
(data/raw/USDJPY_Data/USDJPY_2003_2026_15m.csv) - not hand-derived.

tests/test_regression.py and tests/test_regression_indicators.py are NOT modified by
this change and must keep passing byte-for-byte unchanged - that's the acceptance gate
proving the new condition_tree/direction path is additive, not a rewrite of the
existing short-only trigger/filter path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import find_data_file, load_price_data
from engine.backtest_engine import run_backtest, compute_is_intraday
from engine.conditions import Condition, ConditionGroup

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

LONG_BREAKDOWN_TREE = ConditionGroup(
    op="AND",
    children=[
        Condition(indicator="candle_body", operator="<", value=0.0),
        Condition(indicator="close", operator="<", value="lowest_low", value_params={"length": 30}),
        Condition(indicator="rsi", operator="<", value=30.0, params={"length": 14}),
        Condition(indicator="close", operator="<", value="ema", value_params={"length": 200}),
    ],
).to_dict()

EXPECTED_LONG_BREAKDOWN = {
    "trades": 2022,
    "net_profit": -10.0464,
    "profit_factor": 0.957,
    "max_dd": 27.0114,
    "win_rate": 44.36,
    "recovery_factor": -0.372,
}


def _check(label: str, result: dict, expected: dict) -> list[str]:
    failures = []
    for key, expected_value in expected.items():
        actual_value = result[key]
        if abs(actual_value - expected_value) > TOLERANCE:
            failures.append(f"[{label}] {key}: expected {expected_value}, got {actual_value}")
    return failures


def test_long_breakdown_strategy(df, is_intraday) -> list[str]:
    params = dict(BASE_PARAMS, direction="long", condition_tree=LONG_BREAKDOWN_TREE)
    result = run_backtest(df, params, is_intraday=is_intraday)
    failures = _check("long breakdown-fade", result, EXPECTED_LONG_BREAKDOWN)
    if not failures:
        print("PASS: long breakdown-fade condition_tree strategy matches baseline")
    return failures


def test_invalid_direction_rejected(df, is_intraday) -> list[str]:
    params = dict(BASE_PARAMS, direction="sideways")
    try:
        run_backtest(df, params, is_intraday=is_intraday)
        return ["FAIL: invalid direction 'sideways' did not raise ValueError"]
    except ValueError:
        print("PASS: invalid direction raises ValueError")
        return []


def test_explicit_short_matches_default(df, is_intraday) -> list[str]:
    """direction="short" passed explicitly must produce byte-identical output to
    omitting it entirely - proves the .get("direction", "short") default and an
    explicit "short" are the same code path, not two things that could drift apart."""
    from main import build_parameter_grid

    default_params = build_parameter_grid("dev")[0]
    explicit_params = dict(default_params, direction="short")

    result_default = run_backtest(df, default_params, is_intraday=is_intraday)
    result_explicit = run_backtest(df, explicit_params, is_intraday=is_intraday)

    failures = []
    for key in ["trades", "net_profit", "profit_factor", "max_dd", "win_rate", "recovery_factor"]:
        if result_default[key] != result_explicit[key]:
            failures.append(
                f"[explicit-short-vs-default] {key}: default={result_default[key]}, "
                f"explicit={result_explicit[key]}"
            )

    if not failures:
        print("PASS: direction='short' explicit matches default (no direction key) exactly")

    return failures


def main() -> None:
    df = load_price_data(find_data_file("15m", "USDJPY"))
    is_intraday = compute_is_intraday(df["datetime"])

    all_failures = []
    all_failures += test_long_breakdown_strategy(df, is_intraday)
    all_failures += test_invalid_direction_rejected(df, is_intraday)
    all_failures += test_explicit_short_matches_default(df, is_intraday)

    if all_failures:
        print("FAIL")
        for failure in all_failures:
            print(f"  {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
