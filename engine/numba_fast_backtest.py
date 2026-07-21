"""Numba-accelerated fast path for the market-order backtest loop.

engine/backtest_engine.py::run_backtest() was profiled (cProfile, 5 repeated
calls) and found to spend ~70% of its own time in the per-bar Python for
loop itself - condition-tree evaluation (engine/conditions.py) is only ~7%.
This is exactly the kind of tight, branchy, sequential per-bar state
machine numba's JIT compiler is built for - this module replicates that
loop's logic in a @njit function, verified byte-for-byte equivalent to the
Python original (see tests/test_fast_backtest_parity.py) before being wired
into run_backtest() as an automatic dispatch.

A prior prototype (engine/numba_backtest.py, dated 2026-06-30) already
proved a numba backtest loop is achievable, but modeled a much simpler
backtest (fixed pip SL/TP, no signal/confirmation/pending state machine, no
weekend/daily exit) that doesn't match this project's actual current
market-order semantics - not reused here, rebuilt from scratch to mirror
run_backtest()'s REAL state machine exactly.

Scope (deliberate v1 cut, not an oversight): replicates ONLY the
market-order path's core mechanism - signal -> close-confirmation ->
pending -> next-bar-open entry -> RR-based SL/TP (from the ORIGINAL signal
bar's high/low, not the entry bar's) -> weekend/daily exit or SL/TP hit.
This is exactly what engine/structure_generator.py's auto-generation engine
generates by default, since every advanced feature (ATR trailing,
breakeven, partial TP, circuit breakers, position sizing) defaults off in
main.py::build_parameter_space(). run_backtest() only dispatches here when
ALL of those are off (see its dispatch guard) - falls back to the slow,
fully-featured Python loop otherwise, so this is a pure speed opt-in with
zero behavior change for any strategy actually using those features.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from numba import njit

from engine.backtest_engine import calc_max_dd

_EXIT_REASON_LABELS = {
    0: "SL",
    1: "TP",
    2: "SL_and_TP_SL_first",
    3: "Weekend",
    4: "DailyExit",
}


@njit(cache=True)
def _run_market_backtest_core(
    open_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    hour_arr: np.ndarray,
    weekday_arr: np.ndarray,
    candidate_signal: np.ndarray,
    direction_code: int,
    lookahead_bars: int,
    rr: float,
    cost_per_trade: float,
    is_intraday: bool,
    use_weekend_exit: bool,
    weekend_exit_hour: int,
    use_daily_exit: bool,
    daily_exit_hour: int,
    use_confirmation: bool,
):
    n = len(open_arr)

    entry_bar = np.empty(n, dtype=np.int64)
    exit_bar = np.empty(n, dtype=np.int64)
    entry_price_out = np.empty(n, dtype=np.float64)
    exit_price_out = np.empty(n, dtype=np.float64)
    sl_out = np.empty(n, dtype=np.float64)
    tp_out = np.empty(n, dtype=np.float64)
    profit_out = np.empty(n, dtype=np.float64)
    reason_out = np.empty(n, dtype=np.int64)
    mae_out = np.empty(n, dtype=np.float64)
    mfe_out = np.empty(n, dtype=np.float64)
    trade_count = 0

    in_position = False
    entry_price = 0.0
    entry_bar_index = -1
    sl = 0.0
    tp = 0.0
    # MAE/MFEの追跡用: ポジション保有中に見た最悪値/最良値の価格そのもの
    # (entry_priceとの差はexit時にdirection別に計算する)。
    mae_extreme_price = 0.0
    mfe_extreme_price = 0.0

    signal_low = np.nan
    signal_high = np.nan
    signal_bar = -1

    pending_entry = False
    pending_signal_low = np.nan
    pending_signal_high = np.nan

    position_signal_low = np.nan
    position_signal_high = np.nan

    start = 250
    for i in range(start, n):
        hour = hour_arr[i]
        weekday = weekday_arr[i]

        open_price = open_arr[i]
        high_price = high_arr[i]
        low_price = low_arr[i]
        close_price = close_arr[i]

        if pending_entry and not in_position:
            entry_price = open_price
            entry_bar_index = i

            position_signal_low = pending_signal_low
            position_signal_high = pending_signal_high

            if direction_code == -1:
                stop_price = position_signal_high
                risk_distance = stop_price - entry_price
            else:
                stop_price = position_signal_low
                risk_distance = entry_price - stop_price

            if risk_distance > 0:
                sl = stop_price
                if direction_code == -1:
                    tp = entry_price - risk_distance * rr
                else:
                    tp = entry_price + risk_distance * rr
                in_position = True
                mae_extreme_price = entry_price
                mfe_extreme_price = entry_price

            pending_entry = False
            pending_signal_low = np.nan
            pending_signal_high = np.nan

        if in_position:
            # このバーのhigh/lowを使って保有中の最悪値/最良値を更新する
            # (エントリーしたバー自身も含む - 同じバーでエントリーと決済が
            # 両方起きるケースがあるため)。short/longで不利な方向/有利な
            # 方向が逆になる。
            if direction_code == -1:
                if high_price > mae_extreme_price:
                    mae_extreme_price = high_price
                if low_price < mfe_extreme_price:
                    mfe_extreme_price = low_price
            else:
                if low_price < mae_extreme_price:
                    mae_extreme_price = low_price
                if high_price > mfe_extreme_price:
                    mfe_extreme_price = high_price

            exit_reason = -1
            exit_price = 0.0

            if is_intraday and use_weekend_exit and weekday == 5 and hour >= weekend_exit_hour:
                exit_reason = 3
                exit_price = close_price
            elif is_intraday and use_daily_exit and hour == daily_exit_hour:
                exit_reason = 4
                exit_price = close_price
            else:
                if direction_code == -1:
                    hit_sl = high_price >= sl
                    hit_tp = low_price <= tp
                else:
                    hit_sl = low_price <= sl
                    hit_tp = high_price >= tp

                if hit_sl and hit_tp:
                    exit_reason = 2
                    exit_price = sl
                elif hit_sl:
                    exit_reason = 0
                    exit_price = sl
                elif hit_tp:
                    exit_reason = 1
                    exit_price = tp

            if exit_reason != -1:
                if direction_code == -1:
                    profit = entry_price - exit_price
                    mae = mae_extreme_price - entry_price
                    mfe = entry_price - mfe_extreme_price
                else:
                    profit = exit_price - entry_price
                    mae = entry_price - mae_extreme_price
                    mfe = mfe_extreme_price - entry_price
                profit -= cost_per_trade

                entry_bar[trade_count] = entry_bar_index
                exit_bar[trade_count] = i
                entry_price_out[trade_count] = entry_price
                exit_price_out[trade_count] = exit_price
                sl_out[trade_count] = sl
                tp_out[trade_count] = tp
                profit_out[trade_count] = profit
                reason_out[trade_count] = exit_reason
                mae_out[trade_count] = mae
                mfe_out[trade_count] = mfe
                trade_count += 1

                in_position = False
                entry_price = 0.0
                entry_bar_index = -1
                sl = 0.0
                tp = 0.0
                position_signal_low = np.nan
                position_signal_high = np.nan

            continue

        if use_confirmation:
            # 旧来のブレイクアウト確認方式(自動探索のstructure系向け) -
            # 条件成立(signal_bar)後、後続バーの終値がそのバーの高値/安値を
            # 上抜け/下抜けするのを確認してからエントリー(lookahead_bars以内)。
            if signal_bar != -1:
                bars_from_signal = i - signal_bar
                within_bars = bars_from_signal > 0 and bars_from_signal <= lookahead_bars

                if direction_code == -1:
                    confirmation = close_price < signal_low
                else:
                    confirmation = close_price > signal_high

                if within_bars and confirmation:
                    pending_entry = True
                    pending_signal_low = signal_low
                    pending_signal_high = signal_high
                    signal_low = np.nan
                    signal_high = np.nan
                    signal_bar = -1
                    continue

                expired = bars_from_signal > lookahead_bars
                if expired:
                    signal_low = np.nan
                    signal_high = np.nan
                    signal_bar = -1

            if signal_bar != -1:
                continue

            if not candidate_signal[i]:
                continue

            signal_low = low_price
            signal_high = high_price
            signal_bar = i
        else:
            # 条件ツリー(手動条件ビルダー/自動探索の全モード)向けの即時
            # エントリー - 確認待ちなし。「条件が成立したバーの次のバーの
            # 始値でそのままエントリー」で、画面に見えている条件だけが
            # 動作を決める(ユーザー要望:「画面上に見えていることが全て。
            # EMA200＞終値と設定したらこの条件が満たされたら次の足の始値で
            # 即エントリー」)。既存のpending_entryの仕組み(このバーで武装
            # →次のバーの始値で消費)をそのまま再利用しているだけなので、
            # confirmation方式と全く同じ1バー分のラグで実行される。
            if candidate_signal[i]:
                pending_entry = True
                pending_signal_low = low_price
                pending_signal_high = high_price

    return (
        entry_bar[:trade_count],
        exit_bar[:trade_count],
        entry_price_out[:trade_count],
        exit_price_out[:trade_count],
        sl_out[:trade_count],
        tp_out[:trade_count],
        profit_out[:trade_count],
        reason_out[:trade_count],
        mae_out[:trade_count],
        mfe_out[:trade_count],
    )


def run_market_backtest_fast(
    p: dict[str, Any],
    datetime_arr: np.ndarray,
    open_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    hour_arr: np.ndarray,
    weekday_arr: np.ndarray,
    candidate_signal: np.ndarray,
    direction: str,
    lookahead_bars: int,
    rr: float,
    cost_per_trade: float,
    is_intraday: bool,
    use_weekend_exit: bool,
    weekend_exit_hour: int,
    use_daily_exit: bool,
    daily_exit_hour: int,
    return_trades: bool,
    use_confirmation: bool = True,
):
    """Drop-in replacement for run_backtest()'s market-order result/trade_log
    shape - same result dict keys (plus **p spread), same trade_log columns
    (entry_time/entry_bar_index/entry_price/exit_time/exit_bar_index/
    exit_price/sl/tp/profit/exit_reason/mae/mfe) as the slow path's own
    trade_logs, restricted to the subset needed downstream (see the confirmed
    column audit in project memory) - signal_time/signal_bar_index/signal_low/
    signal_high are omitted (debug-only fields, not read by any downstream
    consumer)."""
    direction_code = -1 if direction == "short" else 1

    (
        entry_bar,
        exit_bar,
        entry_price_arr,
        exit_price_arr,
        sl_arr,
        tp_arr,
        profit_arr,
        reason_arr,
        mae_arr,
        mfe_arr,
    ) = _run_market_backtest_core(
        open_arr.astype(np.float64),
        high_arr.astype(np.float64),
        low_arr.astype(np.float64),
        close_arr.astype(np.float64),
        hour_arr.astype(np.int64),
        weekday_arr.astype(np.int64),
        candidate_signal.astype(np.bool_),
        direction_code,
        int(lookahead_bars),
        float(rr),
        float(cost_per_trade),
        bool(is_intraday),
        bool(use_weekend_exit),
        int(weekend_exit_hour),
        bool(use_daily_exit),
        int(daily_exit_hour),
        bool(use_confirmation),
    )

    trades = int(len(profit_arr))
    wins = int((profit_arr > 0).sum())
    losses = int((profit_arr < 0).sum())

    gross_profit = float(profit_arr[profit_arr > 0].sum()) if trades else 0.0
    gross_loss = float(profit_arr[profit_arr < 0].sum()) if trades else 0.0
    net_profit = float(profit_arr.sum()) if trades else 0.0

    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    win_rate = wins / trades * 100.0 if trades else 0.0
    max_dd = calc_max_dd(profit_arr)
    expected_value = net_profit / trades if trades else 0.0

    if max_dd > 0:
        recovery_factor = net_profit / max_dd
    elif net_profit > 0:
        recovery_factor = 999.0
    else:
        recovery_factor = 0.0

    result = {
        **p,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "net_profit": round(net_profit, 5),
        "gross_profit": round(gross_profit, 5),
        "gross_loss": round(gross_loss, 5),
        "profit_factor": round(profit_factor, 3),
        "max_dd": round(max_dd, 5),
        "expected_value": round(expected_value, 5),
        "recovery_factor": round(recovery_factor, 3),
    }

    if not return_trades:
        return result

    if trades == 0:
        trades_df = pd.DataFrame(
            columns=[
                "entry_time", "entry_bar_index", "entry_price",
                "exit_time", "exit_bar_index", "exit_price",
                "sl", "tp", "profit", "exit_reason", "mae", "mfe",
            ]
        )
        return result, trades_df

    trades_df = pd.DataFrame(
        {
            "entry_time": datetime_arr[entry_bar],
            "entry_bar_index": entry_bar,
            "entry_price": np.round(entry_price_arr, 5),
            "exit_time": datetime_arr[exit_bar],
            "exit_bar_index": exit_bar,
            "exit_price": np.round(exit_price_arr, 5),
            "sl": np.round(sl_arr, 5),
            "tp": np.round(tp_arr, 5),
            "profit": np.round(profit_arr, 5),
            "exit_reason": [_EXIT_REASON_LABELS[r] for r in reason_arr],
            "mae": np.round(mae_arr, 5),
            "mfe": np.round(mfe_arr, 5),
        }
    )

    return result, trades_df
