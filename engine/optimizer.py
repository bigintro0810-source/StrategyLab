from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import pandas as pd

from engine.backtest_engine import run_backtest
from engine.condition_config import ConditionConfig
from engine.condition_engine import ConditionEngine
from engine.numba_backtest import NumbaBacktest
from engine.parameter_grid import ParameterGrid
from engine.result import Result


_WORKER_DF: pd.DataFrame | None = None


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

        condition_engine = ConditionEngine(self.data, condition_config)

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
                active_years,
                winning_years,
                losing_years,
                flat_years,
                avg_yearly_profit,
                min_yearly_profit,
                yearly_stability,
                active_months,
                winning_months,
                losing_months,
                flat_months,
                avg_monthly_profit,
                min_monthly_profit,
                monthly_stability,
                max_consecutive_wins,
                max_consecutive_losses,
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
                active_years=active_years,
                winning_years=winning_years,
                losing_years=losing_years,
                flat_years=flat_years,
                avg_yearly_profit=avg_yearly_profit,
                min_yearly_profit=min_yearly_profit,
                yearly_stability=yearly_stability,
                active_months=active_months,
                winning_months=winning_months,
                losing_months=losing_months,
                flat_months=flat_months,
                avg_monthly_profit=avg_monthly_profit,
                min_monthly_profit=min_monthly_profit,
                monthly_stability=monthly_stability,
                max_consecutive_wins=max_consecutive_wins,
                max_consecutive_losses=max_consecutive_losses,
            )

            results.append(result)

            print(f"{index}/{total} 完了")

        return results


def format_seconds(seconds: float) -> str:
    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def init_parallel_worker(df: pd.DataFrame) -> None:
    global _WORKER_DF
    _WORKER_DF = df


def run_parallel_task(task: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    global _WORKER_DF

    if _WORKER_DF is None:
        raise RuntimeError("Worker data is not initialized.")

    param_id, params = task

    result = run_backtest(
        df=_WORKER_DF,
        params=params,
        return_trades=False,
    )

    result["param_id"] = param_id

    return result


def run_parallel_optimizer(
    df: pd.DataFrame,
    parameter_list: list[dict[str, Any]],
    max_workers: int = 8,
    progress_interval: int = 10,
) -> pd.DataFrame:
    total_tasks = len(parameter_list)

    if total_tasks == 0:
        return pd.DataFrame()

    tasks = list(enumerate(parameter_list, start=1))
    workers = min(max_workers, os.cpu_count() or 1)

    print(f"検証パターン数: {total_tasks}")
    print(f"並列数: {workers}")

    start_time = time.time()
    results: list[dict[str, Any]] = []

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=init_parallel_worker,
        initargs=(df,),
    ) as executor:
        futures = [executor.submit(run_parallel_task, task) for task in tasks]

        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)

            if completed % progress_interval == 0 or completed == total_tasks:
                elapsed = time.time() - start_time
                avg_per_task = elapsed / completed
                remaining = avg_per_task * (total_tasks - completed)

                print(
                    f"{completed}/{total_tasks} 完了 "
                    f"経過 {format_seconds(elapsed)} "
                    f"残り予想 {format_seconds(remaining)}"
                )

    return pd.DataFrame(results)