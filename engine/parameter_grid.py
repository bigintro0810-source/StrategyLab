from itertools import product

from config.strategy_config import StrategyConfig


class ParameterGrid:
    def __init__(self):
        self.ema_periods = [20, 50, 100, 200]
        self.rsi_periods = [14]
        self.rsi_thresholds = [40, 50, 60]
        self.directions = ["long", "short"]
        self.stop_loss_pips_list = [10, 15, 20]
        self.take_profit_pips_list = [10, 20, 30]

    def generate(self):
        for (
            ema_period,
            rsi_period,
            rsi_threshold,
            direction,
            stop_loss_pips,
            take_profit_pips,
        ) in product(
            self.ema_periods,
            self.rsi_periods,
            self.rsi_thresholds,
            self.directions,
            self.stop_loss_pips_list,
            self.take_profit_pips_list,
        ):
            yield StrategyConfig(
                timeframe="1m",
                ema_period=ema_period,
                rsi_period=rsi_period,
                rsi_threshold=rsi_threshold,
                direction=direction,
                size=1.0,
                stop_loss_pips=stop_loss_pips,
                take_profit_pips=take_profit_pips,
            )

    def count(self):
        return (
            len(self.ema_periods)
            * len(self.rsi_periods)
            * len(self.rsi_thresholds)
            * len(self.directions)
            * len(self.stop_loss_pips_list)
            * len(self.take_profit_pips_list)
        )