from concurrent.futures import ProcessPoolExecutor, as_completed
from engine.backtest import Backtest
from engine.metrics import Metrics
from engine.parameter_grid import ParameterGrid
from engine.result import Result


_GLOBAL_DATA = None
_GLOBAL_STRATEGY_CLASS = None


def _init_worker(data, strategy_class):
    global _GLOBAL_DATA
    global _GLOBAL_STRATEGY_CLASS

    _GLOBAL_DATA = data
    _GLOBAL_STRATEGY_CLASS = strategy_class


def _run_chunk(configs):
    results = []

    for config in configs:
        strategy = _GLOBAL_STRATEGY_CLASS(config)
        backtest = Backtest(_GLOBAL_DATA, strategy)
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

    return results


class FastOptimizer:
    def __init__(
        self,
        data,
        strategy_class,
        max_workers=6,
        chunk_size=4
    ):
        self.data = data
        self.strategy_class = strategy_class
        self.grid = ParameterGrid()
        self.max_workers = max_workers
        self.chunk_size = chunk_size

    def _make_chunks(self, configs):
        chunks = []

        for i in range(0, len(configs), self.chunk_size):
            chunks.append(configs[i:i + self.chunk_size])

        return chunks

    def run(self):
        configs = list(self.grid.generate())
        total = len(configs)

        if total == 0:
            return []

        chunks = self._make_chunks(configs)
        total_chunks = len(chunks)

        print(f"高速最適化開始: {total} パターン")
        print(f"worker数: {self.max_workers}")
        print(f"chunk数: {total_chunks}")
        print(f"chunk_size: {self.chunk_size}")

        results = []
        completed = 0

        with ProcessPoolExecutor(
            max_workers=self.max_workers,
            initializer=_init_worker,
            initargs=(self.data, self.strategy_class)
        ) as executor:

            futures = [
                executor.submit(_run_chunk, chunk)
                for chunk in chunks
            ]

            for future in as_completed(futures):
                chunk_results = future.result()
                results.extend(chunk_results)

                completed += len(chunk_results)

                print(f"{completed}/{total} 完了")

        return results