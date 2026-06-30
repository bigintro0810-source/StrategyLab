from numba import njit


@njit(cache=True)
def run_numba_backtest(
    close_array,
    high_array,
    low_array,
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
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            -999999.0,
        )

    win_rate = win_trades / total_trades * 100.0
    average_profit = total_profit / total_trades

    if gross_loss == 0.0:
        profit_factor = 999999.0 if gross_profit > 0.0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

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
    )


class NumbaBacktest:
    def __init__(self, data):
        self.close_array = data["close"].to_numpy(copy=False)
        self.high_array = data["high"].to_numpy(copy=False)
        self.low_array = data["low"].to_numpy(copy=False)

    def run(self, config, signal_array):
        direction_code = 1 if config.direction == "long" else -1
        start_index = max(config.ema_period, config.rsi_period)

        return run_numba_backtest(
            self.close_array,
            self.high_array,
            self.low_array,
            signal_array,
            direction_code,
            config.stop_loss_pips,
            config.take_profit_pips,
            start_index,
            config.size,
        )