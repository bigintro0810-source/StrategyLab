"""Byte-for-byte parity check: engine/numba_fast_backtest.py's numba loop
vs. engine/backtest_engine.py::run_backtest()'s existing Python loop, on
real price data, across many condition trees/directions/rr/exit-flag
combinations. Run BEFORE wiring the fast path into run_backtest() as an
automatic dispatch (see project memory project_auto_exploration_core_goal.md)
- a numba reimplementation of the core simulation loop is exactly the kind
of change where a subtle bug would silently corrupt every future backtest
that hits it, so this is deliberately exhaustive rather than a couple of
spot checks.

Each case runs the OLD Python path (run_backtest with return_trades=True)
and the NEW numba path (run_market_backtest_fast, fed the exact same
precomputed arrays run_backtest() itself would have built) and asserts:
trade count matches, and every trade's entry/exit time/price/profit/reason
matches exactly (not just aggregate metrics - the full trade log).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest_engine import compute_is_intraday, run_backtest
from engine.conditions import evaluate_condition_tree
from engine.data_loader import find_data_file, load_price_data
from engine.numba_fast_backtest import run_market_backtest_fast

DF = load_price_data(find_data_file("15m", "USDJPY"))
IS_INTRADAY = compute_is_intraday(DF["datetime"])


def _run_fast_path(params: dict) -> tuple[dict, pd.DataFrame]:
    p = dict(params)
    pip = float(p.get("pip_size", 0.01))
    cost_per_trade = (
        float(p.get("spread_pips", 0.0)) * pip
        + float(p.get("slippage_pips", 0.0)) * pip
        + float(p.get("commission_per_trade", 0.0))
    )
    direction = str(p.get("direction", "short")).lower()

    datetime_arr = DF["datetime"].to_numpy()
    datetime_series = pd.to_datetime(DF["datetime"])
    hour_arr = datetime_series.dt.hour.to_numpy(dtype=np.int16)
    weekday_arr = datetime_series.dt.weekday.to_numpy(dtype=np.int16)

    open_arr = DF["open"].to_numpy(dtype=float)
    high_arr = DF["high"].to_numpy(dtype=float)
    low_arr = DF["low"].to_numpy(dtype=float)
    close_arr = DF["close"].to_numpy(dtype=float)

    condition_tree = p.get("condition_tree")
    if condition_tree is not None:
        candidate_signal = evaluate_condition_tree(condition_tree, DF, symbol=p.get("symbol"))
    else:
        raise ValueError("test harness only supports condition_tree-based params")

    return run_market_backtest_fast(
        p=p,
        datetime_arr=datetime_arr,
        open_arr=open_arr,
        high_arr=high_arr,
        low_arr=low_arr,
        close_arr=close_arr,
        hour_arr=hour_arr,
        weekday_arr=weekday_arr,
        candidate_signal=candidate_signal,
        direction=direction,
        lookahead_bars=int(p["lookahead_bars"]),
        rr=float(p["rr"]),
        cost_per_trade=cost_per_trade,
        is_intraday=IS_INTRADAY,
        use_weekend_exit=bool(p["use_weekend_exit"]),
        weekend_exit_hour=int(p["weekend_exit_hour"]),
        use_daily_exit=bool(p["use_daily_exit"]),
        daily_exit_hour=int(p["daily_exit_hour"]),
        use_confirmation=condition_tree is None,
        return_trades=True,
    )


BASE_PARAMS = {
    "ema_length": 200,
    "min_body_pips": 20.0,
    "max_body_pips": 0.0,
    "max_wick_pips": 0.0,
    "lookahead_bars": 15,
    "breakout_bars": 30,
    "rr": 1.2,
    "session_start": 8,
    "session_end": 3,
    "use_weekend_exit": True,
    "weekend_exit_hour": 4,
    "use_daily_exit": False,
    "daily_exit_hour": 4,
    "pip_size": 0.01,
    "symbol": "USDJPY",
}

TREES = {
    "ema_cross": {
        "indicator": "ema", "operator": ">", "value": "ema",
        "params": {"length": 50}, "value_params": {"length": 200},
    },
    "rsi_threshold": {
        "indicator": "rsi", "operator": "<", "value": 70.0,
        "params": {"length": 14}, "value_params": {},
    },
    "and_group": {
        "op": "AND",
        "children": [
            {"indicator": "close", "operator": ">", "value": "ema",
             "params": {}, "value_params": {"length": 100}},
            {"indicator": "rsi", "operator": "<", "value": 60.0,
             "params": {"length": 14}, "value_params": {}},
        ],
    },
    "crosses_above": {
        "indicator": "close", "operator": "crosses_above", "value": "highest_high",
        "params": {}, "value_params": {"length": 20},
    },
}


def _run_case(**overrides) -> list[str]:
    failures = []
    for tree_name, tree in TREES.items():
        for direction in ("long", "short"):
            params = {**BASE_PARAMS, "condition_tree": tree, "direction": direction, **overrides}
            label = f"{tree_name}/{direction}/{overrides}"

            slow_result, slow_trades = run_backtest(df=DF, params=params, return_trades=True, is_intraday=IS_INTRADAY)
            fast_result, fast_trades = _run_fast_path(params)

            if slow_result["trades"] != fast_result["trades"]:
                failures.append(f"{label}: trade count mismatch slow={slow_result['trades']} fast={fast_result['trades']}")
                continue

            for key in ("trades", "wins", "losses", "win_rate", "net_profit", "gross_profit",
                        "gross_loss", "profit_factor", "max_dd", "expected_value", "recovery_factor"):
                if slow_result[key] != fast_result[key]:
                    failures.append(f"{label}: result['{key}'] mismatch slow={slow_result[key]} fast={fast_result[key]}")

            cols = ["entry_time", "exit_time", "entry_price", "exit_price", "profit", "exit_reason", "mae", "mfe"]
            slow_cols = slow_trades[cols].reset_index(drop=True)
            fast_cols = fast_trades[cols].reset_index(drop=True)
            if not slow_cols.equals(fast_cols):
                mismatch_rows = (slow_cols != fast_cols).any(axis=1).sum()
                failures.append(f"{label}: trade_log mismatch in {mismatch_rows} row(s)")

    return failures


def main() -> None:
    all_failures: list[str] = []

    all_failures += _run_case()
    all_failures += _run_case(use_weekend_exit=False)
    all_failures += _run_case(use_daily_exit=True, daily_exit_hour=10)
    all_failures += _run_case(rr=2.0)
    all_failures += _run_case(lookahead_bars=5)
    all_failures += _run_case(spread_pips=1.0, slippage_pips=0.5, commission_per_trade=0.001)

    if all_failures:
        print("FAIL")
        for f in all_failures:
            print(f"  {f}")
        raise SystemExit(1)

    print("PASS: numba fast path is byte-for-byte identical to the slow Python path "
          f"across {len(TREES) * 2 * 6} scenarios")


if __name__ == "__main__":
    main()
