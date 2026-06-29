from engine.order import Order
from engine.conditions import close_above, rsi_above
from config.strategy_config import StrategyConfig


class TestStrategy:
    def __init__(self, config: StrategyConfig):
        self.config = config

    def next(self, i, data):
        if i < max(self.config.ema_period, self.config.rsi_period):
            return None

        ema_column = f"ema_{self.config.ema_period}"
        rsi_column = f"rsi_{self.config.rsi_period}"

        conditions = [
            close_above(data, i, ema_column),
            rsi_above(data, i, rsi_column, self.config.rsi_threshold),
        ]

        if not all(conditions):
            return None

        row = data.iloc[i]
        entry_price = row["close"]

        pip = 0.01

        if self.config.direction == "long":
            stop_loss = entry_price - self.config.stop_loss_pips * pip
            take_profit = entry_price + self.config.take_profit_pips * pip
        else:
            stop_loss = entry_price + self.config.stop_loss_pips * pip
            take_profit = entry_price - self.config.take_profit_pips * pip

        return Order(
            direction=self.config.direction,
            order_type="market",
            price=entry_price,
            size=self.config.size,
            time=row["datetime"],
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment="Config Test Strategy",
        )