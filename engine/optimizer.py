from itertools import product

from config.strategy_config import StrategyConfig
from engine.backtest import Backtest
from engine.indicator_manager import IndicatorManager
from engine.metrics import Metrics
from strategies.test_strategy import TestStrategy


class Optimizer:
    def __init__(self, data):
        self.data = data

    def generate_configs(self):
        ema_periods = [20, 50, 100, 200]
        rsi_thresholds = [40, 50, 60]
        stop_loss_pips_list = [10, 15, 20]
        take_profit_pips_list = [10, 20, 30]

        for ema_period, rsi_threshold, stop_loss_pips, take_profit_pips in product(
            ema_periods,
            rsi_thresholds,
            stop_loss_pips_list,
            take_profit_pips_list,
        ):
            yield StrategyConfig(
                timeframe="1m",
                ema_period=ema_period,
                rsi_period=14,
                rsi_threshold=rsi_threshold,
                direction="long",
                size=1.0,
                stop_loss_pips=stop_loss_pips,
                take_profit_pips=take_profit_pips,
            )

    def run(self):
        results = []

        for config in self.generate_configs():
            manager = IndicatorManager(self.data)
            manager.add_ema(config.ema_period)
            manager.add_rsi(config.rsi_period)
            df = manager.data

            strategy = TestStrategy(config)
            backtest = Backtest(df, strategy)
            trades = backtest.run()

            metrics = Metrics(trades)
            summary = metrics.summary()

            results.append({
                "timeframe": config.timeframe,
                "ema_period": config.ema_period,
                "rsi_period": config.rsi_period,
                "rsi_threshold": config.rsi_threshold,
                "direction": config.direction,
                "stop_loss_pips": config.stop_loss_pips,
                "take_profit_pips": config.take_profit_pips,
                "total_trades": summary["total_trades"],
                "win_rate": summary["win_rate"],
                "total_profit": summary["total_profit"],
                "profit_factor": summary["profit_factor"],
                "average_profit": summary["average_profit"],
            })

        return results