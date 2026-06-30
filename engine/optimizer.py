from engine.fast_backtest import FastBacktest
from engine.metrics import Metrics
from engine.parameter_grid import ParameterGrid
from engine.result import Result


class Optimizer:
    def __init__(self, data, strategy_class):
        self.data = data
        self.strategy_class = strategy_class
        self.grid = ParameterGrid()

    def run(self):
        results = []

        total = self.grid.count()

        for index, config in enumerate(self.grid.generate(), start=1):
            strategy = self.strategy_class(config)
            backtest = FastBacktest(self.data, strategy)
            trades = backtest.run()

            metrics = Metrics(trades)
            summary = metrics.summary()

            result = Result(
                timeframe=config.timeframe,
                ema_period=config.ema_period,
                rsi_period=config.rsi_period,
                rsi_threshold=config.rsi_threshold,
                direction=config.direction,
                stop_loss_pips=config.stop_loss_pips,
                take_profit_pips=config.take_profit_pips,
                total_trades=summary["total_trades"],
                win_rate=summary["win_rate"],
                total_profit=summary["total_profit"],
                profit_factor=summary["profit_factor"],
                average_profit=summary["average_profit"],
                max_drawdown=summary["max_drawdown"],
                sharpe_ratio=summary["sharpe_ratio"],
                score=summary["score"],
            )

            results.append(result)

            print(f"{index}/{total} 完了")

        return results