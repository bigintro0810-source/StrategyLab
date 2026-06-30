import numpy as np
from numba import njit


@njit(cache=True)
def run_numba_backtest(
    close_array,
    high_array,
    low_array,
    year_array,
    signal_array,
    direction_code,
    stop_loss_pips,
    take_profit_pips,
    start_index,
    size,
):
    pip = 0.01

    has_position = False
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0

    total_trades = 0
    win_trades = 0

    gross_profit = 0.0
    gross_loss = 0.0
    total_profit = 0.0

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0

    base_year = 1970
    max_years = 100

    yearly_profit = np.zeros(max_years)
    yearly_trades = np.zeros(max_years)

    n = len(close_array)

    for i in range(n):

        if has_position:
            exit_price = 0.0
            should_exit = False

            if direction_code == 1:
                if low_array[i] <= stop_loss:
                    exit_price = stop_loss
                    should_exit = True
                elif high_array[i] >= take_profit:
                    exit_price = take_profit
                    should_exit = True

                if should_exit:
                    profit = (exit_price - entry_price) * size

                    total_trades += 1
                    total_profit += profit
                    equity += profit

                    if profit > 0:
                        win_trades += 1
                        gross_profit += profit
                    elif profit < 0:
                        gross_loss += -profit

                    year_index = year_array[i] - base_year
                    if 0 <= year_index < max_years:
                        yearly_profit[year_index] += profit
                        yearly_trades[year_index] += 1

                    if equity > peak:
                        peak = equity

                    drawdown = peak - equity
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown

                    has_position = False

            elif direction_code == -1:
                if high_array[i] >= stop_loss:
                    exit_price = stop_loss
                    should_exit = True
                elif low_array[i] <= take_profit:
                    exit_price = take_profit
                    should_exit = True

                if should_exit:
                    profit = (entry_price - exit_price) * size

                    total_trades += 1
                    total_profit += profit
                    equity += profit

                    if profit > 0:
                        win_trades += 1
                        gross_profit += profit
                    elif profit < 0:
                        gross_loss += -profit

                    year_index = year_array[i] - base_year
                    if 0 <= year_index < max_years:
                        yearly_profit[year_index] += profit
                        yearly_trades[year_index] += 1

                    if equity > peak:
                        peak = equity

                    drawdown = peak - equity
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown

                    has_position = False

        if not has_position and i >= start_index:
            if signal_array[i]:
                entry_price = close_array[i]

                if direction_code == 1:
                    stop_loss = entry_price - stop_loss_pips * pip
                    take_profit = entry_price + take_profit_pips * pip
                else:
                    stop_loss = entry_price + stop_loss_pips * pip
                    take_profit = entry_price - take_profit_pips * pip

                has_position = True

    if total_trades == 0:
        return (
            0, 0.0, 0.0, 0.0, 0.0, 0.0, -999999.0,
            0, 0, 0, 0, 0.0, 0.0, 0.0
        )

    win_rate = win_trades / total_trades * 100.0
    average_profit = total_profit / total_trades

    if gross_loss == 0.0:
        profit_factor = 999999.0 if gross_profit > 0.0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    active_years = 0
    winning_years = 0
    losing_years = 0
    flat_years = 0
    yearly_profit_sum = 0.0
    min_yearly_profit = 0.0

    for j in range(max_years):
        if yearly_trades[j] > 0:
            active_years += 1
            yp = yearly_profit[j]
            yearly_profit_sum += yp

            if active_years == 1:
                min_yearly_profit = yp
            elif yp < min_yearly_profit:
                min_yearly_profit = yp

            if yp > 0:
                winning_years += 1
            elif yp < 0:
                losing_years += 1
            else:
                flat_years += 1

    if active_years > 0:
        avg_yearly_profit = yearly_profit_sum / active_years
        yearly_stability = winning_years / active_years * 100.0
    else:
        avg_yearly_profit = 0.0
        yearly_stability = 0.0

    score_pf = profit_factor
    if score_pf > 10.0:
        score_pf = 10.0

    score = (
        score_pf * 100.0
        + average_profit * 1000.0
        + win_rate
        - max_drawdown * 50.0
        + total_trades * 0.1
    )

    return (
        total_trades,
        win_rate,
        total_profit,
        profit_factor,
        average_profit,
        max_drawdown,
        score,
        active_years,
        winning_years,
        losing_years,
        flat_years,
        avg_yearly_profit,
        min_yearly_profit,
        yearly_stability,
    )


class NumbaBacktest:
    def __init__(self, data):
        self.close_array = data["close"].to_numpy(copy=False)
        self.high_array = data["high"].to_numpy(copy=False)
        self.low_array = data["low"].to_numpy(copy=False)
        self.year_array = data["datetime"].dt.year.to_numpy(copy=False)

    def run(self, config, signal_array):
        direction_code = 1 if config.direction == "long" else -1
        start_index = max(config.ema_period, config.rsi_period)

        return run_numba_backtest(
            self.close_array,
            self.high_array,
            self.low_array,
            self.year_array,
            signal_array,
            direction_code,
            config.stop_loss_pips,
            config.take_profit_pips,
            start_index,
            config.size,
        )