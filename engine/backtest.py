import pandas as pd

from engine.broker import Broker


class Backtest:
    def __init__(self, data: pd.DataFrame, strategy):
        self.data = data
        self.strategy = strategy
        self.broker = Broker()

        self.datetime_array = data["datetime"].to_numpy(copy=False)
        self.high_array = data["high"].to_numpy(copy=False)
        self.low_array = data["low"].to_numpy(copy=False)

        if hasattr(self.strategy, "prepare"):
            self.strategy.prepare(data)

    def run(self):
        data_length = len(self.data)

        datetime_array = self.datetime_array
        high_array = self.high_array
        low_array = self.low_array

        broker = self.broker
        strategy = self.strategy

        for i in range(data_length):
            broker.check_exit(
                time=datetime_array[i],
                high=high_array[i],
                low=low_array[i],
            )

            if not broker.has_position():
                order = strategy.next(i, self.data)

                if order is not None:
                    broker.open_position(order)

        return broker.trades