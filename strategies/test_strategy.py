from engine.order import Order
from config.strategy_config import StrategyConfig


class TestStrategy:
    def __init__(self, config: StrategyConfig):
        self.config = config

        self.datetime_array = None
        self.close_array = None
        self.ema_array = None
        self.rsi_array = None

        self.start_index = max(
            self.config.ema_period,
            self.config.rsi_period
        )

        self.pip = 0.01

    def prepare(self, data):
        ema_column = f"ema_{self.config.ema_period}"
        rsi_column = f"rsi_{self.config.rsi_period}"

        self.datetime_array = data["datetime"].to_numpy(copy=False)
        self.close_array = data["close"].to_numpy(copy=False)
        self.ema_array = data[ema_column].to_numpy(copy=False)
        self.rsi_array = data[rsi_column].to_numpy(copy=False)

    def next(self, i, data):
        if i < self.start_index:
            return None

        close_price = self.close_array[i]
        ema_value = self.ema_array[i]
        rsi_value = self.rsi_array[i]

        if close_price <= ema_value:
            return None

        if rsi_value <= self.config.rsi_threshold:
            return None

        entry_price = close_price

        if self.config.direction == "long":
            stop_loss = entry_price - self.config.stop_loss_pips * self.pip
            take_profit = entry_price + self.config.take_profit_pips * self.pip
        else:
            stop_loss = entry_price + self.config.stop_loss_pips * self.pip
            take_profit = entry_price - self.config.take_profit_pips * self.pip

        return Order(
            direction=self.config.direction,
            order_type="market",
            price=entry_price,
            size=self.config.size,
            time=self.datetime_array[i],
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment="Config Test Strategy",
        )