import pandas as pd

from engine.trade import Trade


class FastBacktest:
    def __init__(self, data: pd.DataFrame, strategy):
        self.data = data
        self.strategy = strategy

        self.datetime_array = data["datetime"].to_numpy(copy=False)
        self.high_array = data["high"].to_numpy(copy=False)
        self.low_array = data["low"].to_numpy(copy=False)

        if hasattr(self.strategy, "prepare"):
            self.strategy.prepare(data)

    def run(self):
        trades = []

        has_position = False
        direction = None
        entry_time = None
        entry_price = 0.0
        size = 0.0
        stop_loss = None
        take_profit = None

        datetime_array = self.datetime_array
        high_array = self.high_array
        low_array = self.low_array

        strategy = self.strategy
        data = self.data
        data_length = len(data)

        for i in range(data_length):
            current_time = datetime_array[i]
            high = high_array[i]
            low = low_array[i]

            if has_position:
                exit_price = None
                reason = ""

                if direction == "long":
                    if stop_loss is not None and low <= stop_loss:
                        exit_price = stop_loss
                        reason = "stop_loss"
                    elif take_profit is not None and high >= take_profit:
                        exit_price = take_profit
                        reason = "take_profit"

                    if exit_price is not None:
                        profit = (exit_price - entry_price) * size

                        trades.append(
                            Trade(
                                entry_time=entry_time,
                                exit_time=current_time,
                                direction=direction,
                                entry_price=entry_price,
                                exit_price=exit_price,
                                size=size,
                                profit=profit,
                                reason=reason,
                            )
                        )

                        has_position = False
                        direction = None
                        entry_time = None
                        entry_price = 0.0
                        size = 0.0
                        stop_loss = None
                        take_profit = None

                elif direction == "short":
                    if stop_loss is not None and high >= stop_loss:
                        exit_price = stop_loss
                        reason = "stop_loss"
                    elif take_profit is not None and low <= take_profit:
                        exit_price = take_profit
                        reason = "take_profit"

                    if exit_price is not None:
                        profit = (entry_price - exit_price) * size

                        trades.append(
                            Trade(
                                entry_time=entry_time,
                                exit_time=current_time,
                                direction=direction,
                                entry_price=entry_price,
                                exit_price=exit_price,
                                size=size,
                                profit=profit,
                                reason=reason,
                            )
                        )

                        has_position = False
                        direction = None
                        entry_time = None
                        entry_price = 0.0
                        size = 0.0
                        stop_loss = None
                        take_profit = None

            if not has_position:
                order = strategy.next(i, data)

                if order is not None:
                    has_position = True
                    direction = order.direction
                    entry_time = order.time
                    entry_price = order.price
                    size = order.size
                    stop_loss = order.stop_loss
                    take_profit = order.take_profit

        return trades