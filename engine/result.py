from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    param_id: str

    net_profit: float
    gross_profit: float
    gross_loss: float
    profit_factor: float

    trades: int
    wins: int
    losses: int
    win_rate: float

    avg_profit: float
    expected_value: float

    max_dd: float
    max_win_streak: int
    max_loss_streak: int

    year_stability: float
    month_stability: float

    params: dict[str, Any]


def create_empty_result(
    param_id: str = "",
    params: dict[str, Any] | None = None,
) -> BacktestResult:
    return BacktestResult(
        param_id=param_id,
        net_profit=0.0,
        gross_profit=0.0,
        gross_loss=0.0,
        profit_factor=0.0,
        trades=0,
        wins=0,
        losses=0,
        win_rate=0.0,
        avg_profit=0.0,
        expected_value=0.0,
        max_dd=0.0,
        max_win_streak=0,
        max_loss_streak=0,
        year_stability=0.0,
        month_stability=0.0,
        params=params or {},
    )


def build_result_from_trades(
    trades_df: pd.DataFrame,
    param_id: str = "",
    params: dict[str, Any] | None = None,
    datetime_col: str = "exit_time",
    profit_col: str = "profit",
) -> BacktestResult:
    if trades_df is None or trades_df.empty:
        return create_empty_result(param_id=param_id, params=params)

    if profit_col not in trades_df.columns:
        raise ValueError(f"profit column not found: {profit_col}")

    work = trades_df.copy()
    profits = pd.to_numeric(work[profit_col], errors="coerce").fillna(0.0)

    net_profit = float(profits.sum())

    win_profits = profits[profits > 0]
    loss_profits = profits[profits < 0]

    gross_profit = float(win_profits.sum())
    gross_loss = float(loss_profits.sum())

    trades = int(len(profits))
    wins = int((profits > 0).sum())
    losses = int((profits < 0).sum())

    win_rate = calc_win_rate(wins=wins, trades=trades)
    profit_factor = calc_profit_factor(gross_profit=gross_profit, gross_loss=gross_loss)

    avg_profit = float(profits.mean()) if trades > 0 else 0.0
    expected_value = avg_profit

    equity = profits.cumsum()
    max_dd = calc_max_drawdown(equity)

    max_win_streak, max_loss_streak = calc_streaks(profits)

    year_stability = calc_period_stability(
        work=work,
        profits=profits,
        datetime_col=datetime_col,
        freq="Y",
    )

    month_stability = calc_period_stability(
        work=work,
        profits=profits,
        datetime_col=datetime_col,
        freq="M",
    )

    return BacktestResult(
        param_id=param_id,
        net_profit=round(net_profit, 10),
        gross_profit=round(gross_profit, 10),
        gross_loss=round(gross_loss, 10),
        profit_factor=round(profit_factor, 10),
        trades=trades,
        wins=wins,
        losses=losses,
        win_rate=round(win_rate, 10),
        avg_profit=round(avg_profit, 10),
        expected_value=round(expected_value, 10),
        max_dd=round(max_dd, 10),
        max_win_streak=max_win_streak,
        max_loss_streak=max_loss_streak,
        year_stability=round(year_stability, 10),
        month_stability=round(month_stability, 10),
        params=params or {},
    )


def build_result_from_profit_array(
    profits: np.ndarray | list[float],
    param_id: str = "",
    params: dict[str, Any] | None = None,
) -> BacktestResult:
    arr = np.asarray(profits, dtype=np.float64)

    if arr.size == 0:
        return create_empty_result(param_id=param_id, params=params)

    net_profit = float(arr.sum())

    win_arr = arr[arr > 0]
    loss_arr = arr[arr < 0]

    gross_profit = float(win_arr.sum())
    gross_loss = float(loss_arr.sum())

    trades = int(arr.size)
    wins = int((arr > 0).sum())
    losses = int((arr < 0).sum())

    win_rate = calc_win_rate(wins=wins, trades=trades)
    profit_factor = calc_profit_factor(gross_profit=gross_profit, gross_loss=gross_loss)

    avg_profit = float(arr.mean()) if trades > 0 else 0.0
    expected_value = avg_profit

    equity = np.cumsum(arr)
    max_dd = calc_max_drawdown(equity)

    max_win_streak, max_loss_streak = calc_streaks(arr)

    return BacktestResult(
        param_id=param_id,
        net_profit=round(net_profit, 10),
        gross_profit=round(gross_profit, 10),
        gross_loss=round(gross_loss, 10),
        profit_factor=round(profit_factor, 10),
        trades=trades,
        wins=wins,
        losses=losses,
        win_rate=round(win_rate, 10),
        avg_profit=round(avg_profit, 10),
        expected_value=round(expected_value, 10),
        max_dd=round(max_dd, 10),
        max_win_streak=max_win_streak,
        max_loss_streak=max_loss_streak,
        year_stability=0.0,
        month_stability=0.0,
        params=params or {},
    )


def result_to_dict(result: BacktestResult) -> dict[str, Any]:
    base = asdict(result)
    params = base.pop("params", {}) or {}

    for key, value in params.items():
        base[str(key)] = value

    return base


def results_to_dataframe(results: list[BacktestResult]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    return pd.DataFrame([result_to_dict(r) for r in results])


def calc_profit_factor(gross_profit: float, gross_loss: float) -> float:
    if gross_loss == 0:
        if gross_profit > 0:
            return float("inf")
        return 0.0

    return float(gross_profit / abs(gross_loss))


def calc_win_rate(wins: int, trades: int) -> float:
    if trades <= 0:
        return 0.0

    return float(wins / trades * 100.0)


def calc_max_drawdown(equity: np.ndarray | pd.Series) -> float:
    if len(equity) == 0:
        return 0.0

    arr = np.asarray(equity, dtype=np.float64)

    running_max = np.maximum.accumulate(arr)
    drawdown = running_max - arr

    return float(np.max(drawdown)) if drawdown.size > 0 else 0.0


def calc_streaks(profits: np.ndarray | pd.Series | list[float]) -> tuple[int, int]:
    arr = np.asarray(profits, dtype=np.float64)

    max_win_streak = 0
    max_loss_streak = 0

    current_win = 0
    current_loss = 0

    for value in arr:
        if value > 0:
            current_win += 1
            current_loss = 0
        elif value < 0:
            current_loss += 1
            current_win = 0
        else:
            current_win = 0
            current_loss = 0

        if current_win > max_win_streak:
            max_win_streak = current_win

        if current_loss > max_loss_streak:
            max_loss_streak = current_loss

    return int(max_win_streak), int(max_loss_streak)


def calc_period_stability(
    work: pd.DataFrame,
    profits: pd.Series,
    datetime_col: str,
    freq: str,
) -> float:
    if datetime_col not in work.columns:
        return 0.0

    if len(work) == 0:
        return 0.0

    temp = work.copy()
    temp[datetime_col] = pd.to_datetime(temp[datetime_col], errors="coerce")
    temp["_profit"] = profits.values

    temp = temp.dropna(subset=[datetime_col])

    if temp.empty:
        return 0.0

    period_profit = temp.groupby(pd.Grouper(key=datetime_col, freq=freq))["_profit"].sum()
    period_profit = period_profit[period_profit != 0]

    if len(period_profit) == 0:
        return 0.0

    positive_rate = float((period_profit > 0).sum() / len(period_profit))

    avg_profit = float(period_profit.mean())
    std_profit = float(period_profit.std(ddof=0))

    if std_profit == 0:
        consistency = 1.0 if avg_profit > 0 else 0.0
    else:
        consistency = max(0.0, min((avg_profit / std_profit + 1.0) / 2.0, 1.0))

    stability = positive_rate * 70.0 + consistency * 30.0

    return float(stability)


def normalize_result_dict(result: dict[str, Any]) -> dict[str, Any]:
    """
    Walk Forwardやランキングで使うため、キー名の揺れを吸収する。
    """

    normalized = dict(result)

    key_map = {
        "profit": "net_profit",
        "total_profit": "net_profit",
        "pf": "profit_factor",
        "winrate": "win_rate",
        "total_trades": "trades",
        "trade_count": "trades",
        "max_drawdown": "max_dd",
        "ev": "expected_value",
    }

    for old_key, new_key in key_map.items():
        if old_key in normalized and new_key not in normalized:
            normalized[new_key] = normalized[old_key]

    defaults = {
        "param_id": "",
        "net_profit": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "profit_factor": 0.0,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "avg_profit": 0.0,
        "expected_value": 0.0,
        "max_dd": 0.0,
        "max_win_streak": 0,
        "max_loss_streak": 0,
        "year_stability": 0.0,
        "month_stability": 0.0,
        "walk_forward_score": 0.0,
        "wf_score": 0.0,
    }

    for key, value in defaults.items():
        normalized.setdefault(key, value)

    return normalized


def normalize_results_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    records = [normalize_result_dict(row.to_dict()) for _, row in df.iterrows()]
    return pd.DataFrame(records)