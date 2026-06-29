import pandas as pd

from engine.broker import Broker


class Backtest:
    def __init__(self, data: pd.DataFrame, strategy):
        self.data = data
        self.strategy = strategy
        self.broker = Broker()

    def run(self):
        for i in range(len(self.data)):
            row = self.data.iloc[i]

            self.broker.check_exit(
                time=row["datetime"],
                high=row["high"],
                low=row["low"],
            )

            if not self.broker.has_position():
                order = self.strategy.next(i, self.data)

                if order is not None:
                    self.broker.open_position(order)

        return self.broker.trades