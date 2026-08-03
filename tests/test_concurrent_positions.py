"""Regression tests for allow_concurrent_positions (engine/backtest_engine.py).

Plain-script style (not pytest-based) matching this project's convention -
run directly with `python tests/test_concurrent_positions.py`.

Hand-built synthetic OHLC series with two candidate signals 5 bars apart,
both of which stay open (no SL/TP hit) until a later bar spikes high enough
to stop out whichever position(s) are open at that point. This isolates
exactly the behavior allow_concurrent_positions controls: whether the
second signal is silently dropped (default, position already open) or
opens a second, independently-tracked position (opt-in).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.backtest_engine import BacktestConfig, run_backtest
from engine.conditions import Condition, ConditionGroup
from dataclasses import asdict

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


N = 300
SIGNAL1_BAR = 260
SIGNAL2_BAR = 265
SL_TRIGGER_BAR = 280
BASE = 99.0
WICK = 0.2
# Two distinct signal highs (both > the 100.5 threshold) so position1's SL
# (set from signal1's high) and signal2's own candle high never collide at
# the same price - otherwise signal2's candle would itself immediately
# stop position1 out via the >= boundary, muddying what's being tested.
SIGNAL1_CLOSE = 100.6
SIGNAL2_CLOSE = 100.55


def _build_df() -> pd.DataFrame:
    open_ = np.full(N, BASE)
    close = np.full(N, BASE)
    high = np.full(N, BASE + WICK)
    low = np.full(N, BASE - WICK)

    close[SIGNAL1_BAR] = SIGNAL1_CLOSE
    high[SIGNAL1_BAR] = SIGNAL1_CLOSE + WICK
    close[SIGNAL2_BAR] = SIGNAL2_CLOSE
    high[SIGNAL2_BAR] = SIGNAL2_CLOSE + WICK

    # Intrabar-only spike (close stays at baseline, so it never itself
    # trips the close>100.5 candidate_signal condition) that stops out
    # whichever position(s) are open at this point.
    high[SL_TRIGGER_BAR] = 105.2

    datetime = pd.date_range("2024-01-01", periods=N, freq="15min")
    return pd.DataFrame({"datetime": datetime, "open": open_, "high": high, "low": low, "close": close})


def _run(allow_concurrent: bool):
    df = _build_df()
    tree = ConditionGroup(
        op="AND",
        children=[Condition(indicator="close", operator=">", value=100.5)],
    ).to_dict()

    params = asdict(BacktestConfig())
    params["condition_tree"] = tree
    params["direction"] = "short"
    params["pip_size"] = 0.01
    params["use_weekend_exit"] = False
    params["allow_concurrent_positions"] = allow_concurrent
    return run_backtest(df, params, return_trades=True, is_intraday=True)


def test_default_drops_signal_while_position_open():
    result, trades = _run(allow_concurrent=False)
    check("default (off): exactly 1 trade", len(trades) == 1, detail=str(len(trades)))
    if len(trades) == 1:
        row = trades.iloc[0]
        check("default: entry at bar 261 (signal1's next bar)", int(row["entry_bar_index"]) == SIGNAL1_BAR + 1)
        check("default: entry price is baseline open", abs(row["entry_price"] - BASE) < 1e-9)
        check("default: SL at signal1's high", abs(row["sl"] - (SIGNAL1_CLOSE + WICK)) < 1e-9)
        check("default: exit at the SL-trigger bar", int(row["exit_bar_index"]) == SL_TRIGGER_BAR)
        check("default: exit reason is SL", row["exit_reason"] == "SL")
        expected_profit = round(BASE - (SIGNAL1_CLOSE + WICK), 5)
        check("default: profit matches short SL formula", abs(row["profit"] - expected_profit) < 1e-9, detail=str(row["profit"]))
    check("default (off) result['trades'] matches trade_log length", result["trades"] == len(trades))


def test_concurrent_on_stacks_second_signal():
    result, trades = _run(allow_concurrent=True)
    check("concurrent (on): exactly 2 trades", len(trades) == 2, detail=str(len(trades)))
    if len(trades) == 2:
        trades_sorted = trades.sort_values("entry_bar_index").reset_index(drop=True)
        row1, row2 = trades_sorted.iloc[0], trades_sorted.iloc[1]

        check("concurrent: position1 entry at bar 261", int(row1["entry_bar_index"]) == SIGNAL1_BAR + 1)
        check("concurrent: position2 entry at bar 266", int(row2["entry_bar_index"]) == SIGNAL2_BAR + 1)
        check(
            "concurrent: positions overlap in time (pos2 opens before pos1 closes)",
            int(row2["entry_bar_index"]) < int(row1["exit_bar_index"]),
        )
        for label, row, signal_close in (
            ("position1", row1, SIGNAL1_CLOSE),
            ("position2", row2, SIGNAL2_CLOSE),
        ):
            check(f"concurrent {label}: entry price is baseline open", abs(row["entry_price"] - BASE) < 1e-9)
            check(f"concurrent {label}: SL at its own signal's high", abs(row["sl"] - (signal_close + WICK)) < 1e-9)
            check(f"concurrent {label}: exit at the SL-trigger bar", int(row["exit_bar_index"]) == SL_TRIGGER_BAR)
            check(f"concurrent {label}: exit reason is SL", row["exit_reason"] == "SL")
            expected_profit = round(BASE - (signal_close + WICK), 5)
            check(f"concurrent {label}: profit matches short SL formula", abs(row["profit"] - expected_profit) < 1e-9)
    check("concurrent (on) result['trades'] matches trade_log length", result["trades"] == len(trades))


def test_concurrent_off_matches_fast_path_default_trade_count():
    # The fast numba path is only eligible when allow_concurrent_positions
    # is False - confirm the two dispatch routes agree on this scenario
    # (fast_path_eligible's own gate is exercised implicitly here since
    # run_backtest picks the path internally).
    result_off, trades_off = _run(allow_concurrent=False)
    result_on, trades_on = _run(allow_concurrent=True)
    check(
        "concurrent=True never produces fewer trades than the default",
        len(trades_on) >= len(trades_off),
        detail=f"off={len(trades_off)} on={len(trades_on)}",
    )


if __name__ == "__main__":
    test_default_drops_signal_while_position_open()
    test_concurrent_on_stacks_second_signal()
    test_concurrent_off_matches_fast_path_default_trade_count()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll concurrent_positions tests passed.")
