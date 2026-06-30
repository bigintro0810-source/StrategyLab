from engine.condition_config import ConditionConfig
from engine.condition_engine import ConditionEngine
from engine.numba_backtest import NumbaBacktest
from engine.parameter_grid import ParameterGrid
from engine.result import Result


class Optimizer:
    def __init__(self, data, strategy_class):
        self.data = data
        self.strategy_class = strategy_class
        self.grid = ParameterGrid()
        self.backtest = NumbaBacktest(data)

        self.condition_config = ConditionConfig()
        self.condition_engine = ConditionEngine(
            data,
            self.condition_config
        )

    def run(self):
        results = []

        total = self.grid.count()

        for index, config in enumerate(self.grid.generate(), start=1):

            ema_column = f"ema_{config.ema_period}"
            rsi_column = f"rsi_{config.rsi_period}"

            ema_array = self.data[ema_column].to_numpy(copy=False)
            rsi_array = self.data[rsi_column].to_numpy(copy=False)

            signal_array = self.condition_engine.build_signal(
                ema_array=ema_array,
                rsi_array=rsi_array,
                rsi_threshold=config.rsi_threshold,
            )

            (
                total_trades,
                win_rate,
                total_profit,
                profit_factor,
                average_profit,
                max_drawdown,
                score,
            ) = self.backtest.run(config, signal_array)

            if profit_factor >= 999999.0:
                profit_factor = float("inf")

            result = Result(
                timeframe=config.timeframe,
                ema_period=config.ema_period,
                rsi_period=config.rsi_period,
                rsi_threshold=config.rsi_threshold,
                direction=config.direction,
                stop_loss_pips=config.stop_loss_pips,
                take_profit_pips=config.take_profit_pips,
                total_trades=total_trades,
                win_rate=win_rate,
                total_profit=total_profit,
                profit_factor=profit_factor,
                average_profit=average_profit,
                max_drawdown=max_drawdown,
                sharpe_ratio=0.0,
                score=score,
            )

            results.append(result)

            print(f"{index}/{total} 完了")

        return results