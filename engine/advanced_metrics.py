"""Sharpe/Sortino/CAGR/Calmar - completes V2.0-2 評価指標拡充.

Recovery Factor (net_profit / max_dd) was already implemented and shipped
earlier; the roadmap's separately-listed "Profit/DD" is the exact same
formula, so no new code for that one.

Sharpe/Sortino are computed from monthly pip returns (the same monthly
net_profit series main.py already builds for the monthly heatmap), risk-
free rate defaulted to 0 - the engine tracks profit in raw pips, not
percentage returns on capital, so these compare a strategy's own return
distribution to itself rather than to an external benchmark.

CAGR/Calmar need an actual percentage, which requires an assumed starting
capital this engine has no other concept of anywhere (no lot sizing/
account balance model exists). Uses a configurable virtual_capital,
default 100 (pips) - confirmed with the user 2026-07-03 rather than
guessed, since the choice materially changes what the resulting numbers
mean.
"""

import numpy as np
import pandas as pd

MONTHS_PER_YEAR = 12
DEFAULT_VIRTUAL_CAPITAL = 100.0


def sharpe_ratio(monthly_returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    if monthly_returns.empty or monthly_returns.std() == 0:
        return 0.0

    excess = monthly_returns - risk_free_rate
    return float(excess.mean() / monthly_returns.std() * np.sqrt(MONTHS_PER_YEAR))


def sortino_ratio(monthly_returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    if monthly_returns.empty:
        return 0.0

    excess = monthly_returns - risk_free_rate
    downside = monthly_returns[monthly_returns < 0]
    downside_std = downside.std() if len(downside) > 1 else 0.0

    if not downside_std:
        return 0.0

    return float(excess.mean() / downside_std * np.sqrt(MONTHS_PER_YEAR))


def cagr(net_profit: float, years: float, virtual_capital: float = DEFAULT_VIRTUAL_CAPITAL) -> float:
    if years <= 0 or virtual_capital <= 0:
        return 0.0

    ending_value = virtual_capital + net_profit

    if ending_value <= 0:
        return -1.0

    return float((ending_value / virtual_capital) ** (1 / years) - 1)


def calmar_ratio(
    cagr_value: float,
    max_dd: float,
    virtual_capital: float = DEFAULT_VIRTUAL_CAPITAL,
) -> float:
    if max_dd <= 0 or virtual_capital <= 0:
        return 0.0

    max_dd_pct = max_dd / virtual_capital
    return float(cagr_value / max_dd_pct)
