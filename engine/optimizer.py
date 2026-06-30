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
        self.signal_cache = {}

    def _build_signal_cache_key(self, config):
        return (
            config.ema_period,
            config.rsi_period,
            config.rsi_threshold,
            config.atr_period,
            config.atr_threshold,
            config.session_name,
            config.session_start,
            config.session_end,
        )

    def _get_signal_array(self, config):
        cache_key = self._build_signal_cache_key(config)

        if cache_key in self.signal_cache:
            return self.signal_cache[cache_key]

        use_atr = config.atr_threshold > 0.0
        use_session = config.session_name != "all"

        condition_config = ConditionConfig(
            use_ema=True,
            ema_above=True,
            ema_below=False,
            use_rsi=True,
            rsi_above=True,
            rsi_below=False,
            use_atr=use_atr,
            atr_above=use_atr,
            atr_below=False,
            use_session=use_session,
            session_start=config.session_start,
            session_end=config.session_end,
        )

        condition_engine = ConditionEngine(
            self.data,
            condition_config
        )

        ema_column = f"ema_{config.ema_period}"
        rsi_column = f"rsi_{config.rsi_period}"
        atr_column = f"atr_{config.atr_period}"

        ema_array = self.data[ema_column].to_numpy(copy=False)
        rsi_array = self.data[rsi_column].to_numpy(copy=False)

        atr_array = None
        if use_atr:
            atr_array = self.data[atr_column].to_numpy(copy=False)

        signal_array = condition_engine.build_signal(
            ema_array=ema_array,
            rsi_array=rsi_array,
            atr_array=atr_array,
            rsi_threshold=config.rsi_threshold,
            atr_threshold=config.atr_threshold,
        )

        self.signal_cache[cache_key] = signal_array

        return signal_array

    def run(self):
        results = []

        total = self.grid.count()

        for index, config in enumerate(self.grid.generate(), start=1):
            signal_array = self._get_signal_array(config)

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
                atr_period=config.atr_period,
                atr_threshold=config.atr_threshold,
                session_name=config.session_name,
                session_start=config.session_start,
                session_end=config.session_end,
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