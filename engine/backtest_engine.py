from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from engine.conditions import evaluate_condition_tree
from engine.signal_builder import build_candidate_signal


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
    direction: str = "short"
    # Execution cost simulation - all default to 0.0 (frictionless fills,
    # exactly today's behavior) so existing callers/tests are unaffected
    # unless they opt in.
    spread_pips: float = 0.0
    slippage_pips: float = 0.0
    commission_per_trade: float = 0.0


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's smoothed RSI - matches TradingView's built-in RSI.

    Verified 2026-07-03 against data/raw/TV_USDJPY_15m.csv's exported RSI
    column: this formula agrees with TradingView at 100% of RSI>70 bars
    (mean abs diff 0.006), vs. a simple-rolling-mean version which only
    agreed 90.48% of the time (mean abs diff 6.6) - that version was live
    in this engine until this change and never actually matched
    TradingView despite the project's TradingView-validation goal.
    """
    diff = series.diff()
    gain = diff.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def is_in_session(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def compute_is_intraday(datetime_series: pd.Series) -> bool:
    bar_seconds = pd.to_datetime(datetime_series).diff().dt.total_seconds().median()

    if pd.isna(bar_seconds):
        return True

    return bool(bar_seconds < 86400)


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
    work = df.copy()

    for length in sorted(set(int(x) for x in ema_lengths)):
        col = f"ema_{length}"
        if col not in work.columns:
            work[col] = ema(work["close"], length)

    rsi_col = f"rsi_{rsi_length}"
    if rsi_col not in work.columns:
        work[rsi_col] = rsi(work["close"], rsi_length)

    return work


def resolve_ema_series(df: pd.DataFrame, ema_length: int) -> pd.Series:
    cached_col = f"ema_{int(ema_length)}"

    if cached_col in df.columns:
        return pd.to_numeric(df[cached_col], errors="coerce")

    if int(ema_length) == 200 and "EMA200" in df.columns:
        return pd.to_numeric(df["EMA200"], errors="coerce")

    return ema(df["close"], int(ema_length))


def resolve_rsi_series(df: pd.DataFrame, rsi_length: int = 14) -> pd.Series:
    cached_col = f"rsi_{int(rsi_length)}"

    if cached_col in df.columns:
        return pd.to_numeric(df[cached_col], errors="coerce")

    if int(rsi_length) == 14 and "RSI" in df.columns:
        return pd.to_numeric(df["RSI"], errors="coerce")

    return rsi(df["close"], int(rsi_length))


def build_previous_high_array(high_arr: np.ndarray, lookback: int) -> np.ndarray:
    high_series = pd.Series(high_arr)
    return high_series.rolling(window=lookback).max().shift(1).to_numpy(dtype=float)


def build_previous_low_array(low_arr: np.ndarray, lookback: int) -> np.ndarray:
    low_series = pd.Series(low_arr)
    return low_series.rolling(window=lookback).min().shift(1).to_numpy(dtype=float)


def run_backtest(
    df: pd.DataFrame,
    params: dict[str, Any] | BacktestConfig,
    return_trades: bool = False,
    is_intraday: bool | None = None,
) -> dict[str, Any] | tuple[dict[str, Any], pd.DataFrame]:
    if isinstance(params, BacktestConfig):
        p = asdict(params)
    else:
        p = dict(params)

    pip = float(p.get("pip_size", 0.01))

    # Round-trip execution cost, expressed in the same price-difference units
    # as "profit" below (this codebase already calls that unit "pips" without
    # actually dividing by pip_size - matching that existing convention here
    # rather than introducing a second, inconsistent one).
    cost_per_trade = (
        float(p.get("spread_pips", 0.0)) * pip
        + float(p.get("slippage_pips", 0.0)) * pip
        + float(p.get("commission_per_trade", 0.0))
    )

    direction = str(p.get("direction", "short")).lower()
    if direction not in ("short", "long"):
        raise ValueError(f"未対応のdirectionです(short/longのみ対応): {direction}")

    ema_length = int(p["ema_length"])
    lookahead_bars = int(p["lookahead_bars"])
    breakout_bars = int(p["breakout_bars"])
    rr = float(p["rr"])

    use_weekend_exit = bool(p["use_weekend_exit"])
    weekend_exit_hour = int(p["weekend_exit_hour"])

    use_daily_exit = bool(p["use_daily_exit"])
    daily_exit_hour = int(p["daily_exit_hour"])

    datetime_arr = df["datetime"].to_numpy()

    datetime_series = pd.to_datetime(df["datetime"])
    hour_arr = datetime_series.dt.hour.to_numpy(dtype=np.int16)
    weekday_arr = datetime_series.dt.weekday.to_numpy(dtype=np.int16)

    if is_intraday is None:
        is_intraday = compute_is_intraday(datetime_series)

    open_arr = df["open"].to_numpy(dtype=float)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)

    ema_arr = resolve_ema_series(df, ema_length).to_numpy(dtype=float)
    rsi_arr = resolve_rsi_series(df, 14).to_numpy(dtype=float)

    previous_high_arr = build_previous_high_array(high_arr, breakout_bars)

    condition_tree = p.get("condition_tree")
    if condition_tree is not None:
        # V-next generic condition engine (engine/conditions.py) - additive path,
        # selected only when a strategy explicitly supplies a condition_tree. The
        # existing entry_trigger/use_X_filter path below is untouched otherwise.
        candidate_signal = evaluate_condition_tree(condition_tree, df)
    else:
        candidate_signal = build_candidate_signal(
            df,
            p,
            {
                "open": open_arr,
                "high": high_arr,
                "low": low_arr,
                "close": close_arr,
                "ema": ema_arr,
                "rsi": rsi_arr,
                "previous_high": previous_high_arr,
                "hour": hour_arr,
                "weekday": weekday_arr,
                "is_intraday": is_intraday,
                "pip": pip,
            },
        )

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

    for i in range(250, len(df)):
        dt = datetime_arr[i]
        hour = int(hour_arr[i])
        weekday = int(weekday_arr[i])

        open_price = float(open_arr[i])
        high_price = float(high_arr[i])
        low_price = float(low_arr[i])
        close_price = float(close_arr[i])

        if pending_entry and not in_position:
            entry_price = open_price
            entry_time = dt
            entry_bar_index = i

            position_signal_low = pending_signal_low
            position_signal_high = pending_signal_high
            position_signal_bar = pending_signal_bar
            position_signal_time = pending_signal_time

            if direction == "short":
                stop_price = float(position_signal_high)
                risk_distance = stop_price - entry_price
            else:
                stop_price = float(position_signal_low)
                risk_distance = entry_price - stop_price

            if risk_distance > 0:
                sl = stop_price
                tp = (
                    entry_price - risk_distance * rr
                    if direction == "short"
                    else entry_price + risk_distance * rr
                )
                in_position = True

            pending_entry = False
            pending_signal_low = np.nan
            pending_signal_high = np.nan
            pending_signal_bar = None
            pending_signal_time = None

        if in_position:
            exit_reason = None
            exit_price = None

            if is_intraday and use_weekend_exit and weekday == 5 and hour >= weekend_exit_hour:
                exit_reason = "Weekend"
                exit_price = close_price

            elif is_intraday and use_daily_exit and hour == daily_exit_hour:
                exit_reason = "DailyExit"
                exit_price = close_price

            else:
                if direction == "short":
                    hit_sl = high_price >= sl
                    hit_tp = low_price <= tp
                else:
                    hit_sl = low_price <= sl
                    hit_tp = high_price >= tp

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
                profit = (
                    entry_price - float(exit_price)
                    if direction == "short"
                    else float(exit_price) - entry_price
                )
                profit -= cost_per_trade
                profits.append(profit)

                if return_trades:
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
            within_bars = bars_from_signal > 0 and bars_from_signal <= lookahead_bars

            confirmation = (
                close_price < float(signal_low)
                if direction == "short"
                else close_price > float(signal_high)
            )
            if within_bars and confirmation:
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

            expired = bars_from_signal > lookahead_bars
            if expired:
                signal_low = np.nan
                signal_high = np.nan
                signal_bar = None
                signal_time = None

        if signal_bar is not None:
            continue

        if not candidate_signal[i]:
            continue

        signal_low = low_price
        signal_high = high_price
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

    trades_df = pd.DataFrame(trade_logs)

    if return_trades:
        return result, trades_df

    return result