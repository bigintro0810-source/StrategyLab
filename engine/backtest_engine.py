from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class BacktestConfig:
    ema_length: int = 200
    min_body_pips: float = 20.0
    max_body_pips: float = 0.0
    max_wick_pips: float = 0.0
    lookahead_bars: int = 15
    breakout_bars: int = 30
    ema_distance_pips: float = 50.0
    rsi_min: float = 70.0
    rr: float = 1.2
    session_start: int = 8
    session_end: int = 3
    use_weekend_exit: bool = True
    weekend_exit_hour: int = 4
    use_daily_exit: bool = False
    daily_exit_hour: int = 4


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    diff = series.diff()
    gain = diff.clip(lower=0).rolling(length).mean()
    loss = (-diff.clip(upper=0)).rolling(length).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def is_in_session(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def calc_max_dd(profits: np.ndarray) -> float:
    if len(profits) == 0:
        return 0.0

    equity = profits.cumsum()
    running_max = np.maximum.accumulate(equity)
    drawdown = running_max - equity

    return float(drawdown.max())


def prepare_indicator_columns(
    df: pd.DataFrame,
    ema_lengths: list[int] | tuple[int, ...],
    rsi_length: int = 14,
) -> pd.DataFrame:
    """
    Optimizer高速化用。

    main.py側で最初に一度だけ呼び出し、
    ema_150 / ema_200 / ema_250 / rsi_14 のような列を作っておく。

    run_backtest側は、これらの列があれば再計算せずに使う。
    """
    work = df.copy()

    for length in sorted(set(int(x) for x in ema_lengths)):
        col = f"ema_{length}"
        if col not in work.columns:
            work[col] = ema(work["close"], length)

    rsi_col = f"rsi_{rsi_length}"
    if rsi_col not in work.columns:
        work[rsi_col] = rsi(work["close"], rsi_length)

    return work


def resolve_ema_series(work: pd.DataFrame, ema_length: int) -> pd.Series:
    """
    優先順位:
    1. ema_XXX 列
    2. TradingView CSVの EMA200 列
    3. その場で計算
    """
    cached_col = f"ema_{int(ema_length)}"

    if cached_col in work.columns:
        return pd.to_numeric(work[cached_col], errors="coerce")

    if int(ema_length) == 200 and "EMA200" in work.columns:
        return pd.to_numeric(work["EMA200"], errors="coerce")

    return ema(work["close"], int(ema_length))


def resolve_rsi_series(work: pd.DataFrame, rsi_length: int = 14) -> pd.Series:
    """
    優先順位:
    1. rsi_14 列
    2. TradingView CSVの RSI 列
    3. その場で計算
    """
    cached_col = f"rsi_{int(rsi_length)}"

    if cached_col in work.columns:
        return pd.to_numeric(work[cached_col], errors="coerce")

    if int(rsi_length) == 14 and "RSI" in work.columns:
        return pd.to_numeric(work["RSI"], errors="coerce")

    return rsi(work["close"], int(rsi_length))


def run_backtest(
    df: pd.DataFrame,
    params: dict[str, Any] | BacktestConfig,
    return_trades: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], pd.DataFrame]:
    if isinstance(params, BacktestConfig):
        p = asdict(params)
    else:
        p = dict(params)

    pip = 0.01

    work = df.copy()

    ema_length = int(p["ema_length"])
    work["ema"] = resolve_ema_series(work, ema_length)
    work["rsi"] = resolve_rsi_series(work, 14)

    profits: list[float] = []
    trade_logs: list[dict[str, Any]] = []

    in_position = False

    entry_price = 0.0
    entry_time = None
    entry_bar_index = None

    sl = 0.0
    tp = 0.0

    signal_low = np.nan
    signal_high = np.nan
    signal_bar = None
    signal_time = None

    pending_entry = False
    pending_signal_low = np.nan
    pending_signal_high = np.nan
    pending_signal_bar = None
    pending_signal_time = None

    position_signal_low = np.nan
    position_signal_high = np.nan
    position_signal_bar = None
    position_signal_time = None

    for i in range(250, len(work)):
        row = work.iloc[i]
        dt = row["datetime"]
        hour = int(dt.hour)
        weekday = int(dt.weekday())

        if pending_entry and not in_position:
            entry_price = float(row["open"])
            entry_time = dt
            entry_bar_index = i

            position_signal_low = pending_signal_low
            position_signal_high = pending_signal_high
            position_signal_bar = pending_signal_bar
            position_signal_time = pending_signal_time

            stop_reference_high = float(position_signal_high)
            stop_price = entry_price + ((stop_reference_high - entry_price) * 1.0)
            risk_distance = stop_price - entry_price

            if risk_distance > 0:
                sl = stop_price
                tp = entry_price - risk_distance * float(p["rr"])
                in_position = True

            pending_entry = False
            pending_signal_low = np.nan
            pending_signal_high = np.nan
            pending_signal_bar = None
            pending_signal_time = None

        if in_position:
            exit_reason = None
            exit_price = None

            if (
                bool(p["use_weekend_exit"])
                and weekday == 5
                and hour >= int(p["weekend_exit_hour"])
            ):
                exit_reason = "Weekend"
                exit_price = float(row["close"])

            elif bool(p["use_daily_exit"]) and hour == int(p["daily_exit_hour"]):
                exit_reason = "DailyExit"
                exit_price = float(row["close"])

            else:
                hit_sl = float(row["high"]) >= sl
                hit_tp = float(row["low"]) <= tp

                if hit_sl and hit_tp:
                    exit_reason = "SL_and_TP_SL_first"
                    exit_price = sl
                elif hit_sl:
                    exit_reason = "SL"
                    exit_price = sl
                elif hit_tp:
                    exit_reason = "TP"
                    exit_price = tp

            if exit_reason is not None:
                profit = entry_price - float(exit_price)
                profits.append(profit)

                trade_logs.append(
                    {
                        "entry_time": entry_time,
                        "entry_bar_index": entry_bar_index,
                        "entry_price": round(entry_price, 5),
                        "exit_time": dt,
                        "exit_bar_index": i,
                        "exit_price": round(float(exit_price), 5),
                        "sl": round(sl, 5),
                        "tp": round(tp, 5),
                        "profit": round(profit, 5),
                        "exit_reason": exit_reason,
                        "signal_time": position_signal_time,
                        "signal_bar_index": position_signal_bar,
                        "signal_low": round(float(position_signal_low), 5),
                        "signal_high": round(float(position_signal_high), 5),
                    }
                )

                in_position = False

                entry_price = 0.0
                entry_time = None
                entry_bar_index = None

                sl = 0.0
                tp = 0.0

                position_signal_low = np.nan
                position_signal_high = np.nan
                position_signal_bar = None
                position_signal_time = None

            continue

        if signal_bar is not None:
            bars_from_signal = i - signal_bar
            within_bars = (
                bars_from_signal > 0
                and bars_from_signal <= int(p["lookahead_bars"])
            )

            if within_bars and float(row["close"]) < float(signal_low):
                pending_entry = True

                pending_signal_low = signal_low
                pending_signal_high = signal_high
                pending_signal_bar = signal_bar
                pending_signal_time = signal_time

                signal_low = np.nan
                signal_high = np.nan
                signal_bar = None
                signal_time = None

                continue

            expired = bars_from_signal > int(p["lookahead_bars"])
            if expired:
                signal_low = np.nan
                signal_high = np.nan
                signal_bar = None
                signal_time = None

        if signal_bar is not None:
            continue

        if not is_in_session(
            hour=hour,
            start_hour=int(p["session_start"]),
            end_hour=int(p["session_end"]),
        ):
            continue

        if float(row["close"]) <= float(row["open"]):
            continue

        body_size = float(row["close"]) - float(row["open"])
        if body_size < float(p["min_body_pips"]) * pip:
            continue

        body_pips = abs(float(row["close"]) - float(row["open"])) / pip
        wick_pips = (float(row["high"]) - float(row["low"])) / pip

        if float(p["max_body_pips"]) > 0 and body_pips > float(p["max_body_pips"]):
            continue

        if float(p["max_wick_pips"]) > 0 and wick_pips > float(p["max_wick_pips"]):
            continue

        if float(row["close"]) <= float(row["ema"]):
            continue

        ema_distance = float(row["close"]) - float(row["ema"])
        if ema_distance < float(p["ema_distance_pips"]) * pip:
            continue

        if float(row["rsi"]) <= float(p["rsi_min"]):
            continue

        lookback = int(p["breakout_bars"])
        if i - lookback < 0:
            continue

        recent_high = float(work["high"].iloc[i - lookback:i].max())
        if float(row["close"]) <= recent_high:
            continue

        signal_low = float(row["low"])
        signal_high = float(row["high"])
        signal_bar = i
        signal_time = dt

    profits_arr = np.array(profits, dtype=float)

    trades = int(len(profits_arr))
    wins = int((profits_arr > 0).sum())
    losses = int((profits_arr < 0).sum())

    gross_profit = float(profits_arr[profits_arr > 0].sum()) if trades else 0.0
    gross_loss = float(profits_arr[profits_arr < 0].sum()) if trades else 0.0
    net_profit = float(profits_arr.sum()) if trades else 0.0

    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    win_rate = wins / trades * 100.0 if trades else 0.0
    max_dd = calc_max_dd(profits_arr)
    expected_value = net_profit / trades if trades else 0.0

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
    }

    trades_df = pd.DataFrame(trade_logs)

    if return_trades:
        return result, trades_df

    return result