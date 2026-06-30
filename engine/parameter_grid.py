from itertools import product

from config.strategy_config import StrategyConfig


class ParameterGrid:
    def __init__(self):
        self.timeframes = ["1m"]

        self.ema_periods = [20, 50, 100, 200]

        self.rsi_periods = [14]
        self.rsi_thresholds = [40, 50, 60]

        self.atr_periods = [14]

        # 0.0 はATRフィルターOFF
        # 0.03 = 3pips, 0.05 = 5pips, 0.07 = 7pips, 0.10 = 10pips
        self.atr_thresholds = [0.0, 0.03, 0.05, 0.07, 0.10]

        self.directions = ["long", "short"]

        self.stop_loss_pips_list = [10, 15, 20]
        self.take_profit_pips_list = [10, 20, 30]

    def generate(self):
        for (
            timeframe,
            ema_period,
            rsi_period,
            rsi_threshold,
            atr_period,
            atr_threshold,
            direction,
            stop_loss_pips,
            take_profit_pips,
        ) in product(
            self.timeframes,
            self.ema_periods,
            self.rsi_periods,
            self.rsi_thresholds,
            self.atr_periods,
            self.atr_thresholds,
            self.directions,
            self.stop_loss_pips_list,
            self.take_profit_pips_list,
        ):
            yield StrategyConfig(
                timeframe=timeframe,
                ema_period=ema_period,
                rsi_period=rsi_period,
                rsi_threshold=rsi_threshold,
                atr_period=atr_period,
                atr_threshold=atr_threshold,
                direction=direction,
                size=1.0,
                stop_loss_pips=stop_loss_pips,
                take_profit_pips=take_profit_pips,
            )

    def count(self):
        return (
            len(self.timeframes)
            * len(self.ema_periods)
            * len(self.rsi_periods)
            * len(self.rsi_thresholds)
            * len(self.atr_periods)
            * len(self.atr_thresholds)
            * len(self.directions)
            * len(self.stop_loss_pips_list)
            * len(self.take_profit_pips_list)
        )