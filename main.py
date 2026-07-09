from pathlib import Path
import argparse
import itertools
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

from engine.backtest_engine import run_backtest, compute_is_intraday, calc_max_dd
from engine.data_loader import DATA_DIRS, build_data_candidates, find_data_file, load_price_data
from engine.advanced_metrics import sharpe_ratio, sortino_ratio, cagr, calmar_ratio
from engine.equity_curve import export_equity_curve
from engine.monte_carlo import export_monte_carlo, print_monte_carlo_summary
from engine.html_report import export_html_report
from engine.pdf_report import export_pdf_report
from engine.strategy_registry import save_strategy
from engine.optimizer_search import GeneticSearch, run_bayesian_search, sample_random_combos
from engine.strategy_config_loader import load_strategy_config
from engine.structure_generator import StructureGeneticSearch, coarser_timeframes, generate_candidate_trees
from engine.params import reconstruct_params_from_row


AVAILABLE_TIMEFRAMES = ["1m", "5m", "10m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"]

SUPPORTED_SYMBOLS = [
    "USDJPY",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
    "AUDUSD",
    "EURUSD",
    "GBPUSD",
    "XAUUSD",
    "XAGUSD",
]

OUTPUT_DIR = Path("output")

# os.cpu_count() reports LOGICAL processors (16 here), not physical cores
# (10 on this machine - 2-way hyperthreading/SMT). Measured directly rather
# than assumed: for this numba-jitted, CPU-bound per-bar loop, matching
# os.cpu_count() exactly (16 workers) measured SLOWER than the original
# hardcoded 8 (174s vs 161s on the same 500-candidate benchmark), and even
# matching the true physical core count (10) was still slower than 8
# (172s) - two hyperthreads sharing one physical core's execution units
# don't give a real 2x for tight compute-bound work, so oversubscribing
# past the physical core count adds scheduling/cache overhead without a
# matching throughput gain. `os.cpu_count() // 2` approximates the physical
# core count under the common 2-way SMT assumption (portable across
# machines, unlike hardcoding 8) without needing a new dependency (psutil)
# just to read the true physical count.
MAX_WORKERS = max((os.cpu_count() or 16) // 2, 1)

_WORKER_DF = None
_WORKER_IS_INTRADAY = True
# One cache dict per worker process, alive for that worker's whole
# lifetime (every task it ever runs shares the same _WORKER_DF - see
# engine/conditions.py::evaluate_condition_tree's docstring for why this is
# safe here specifically) - lets indicator arrays (ema, rsi, ...) be reused
# across different generated condition_trees that happen to reference the
# same (indicator, params) pair, instead of recomputing from scratch every
# single task.
_WORKER_INDICATOR_CACHE: dict = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy Lab optimizer")

    parser.add_argument(
        "--mode",
        choices=["dev", "full"],
        default="dev",
        help="dev=軽量テスト / full=全パラメータ検証",
    )

    parser.add_argument(
        "--timeframe",
        choices=AVAILABLE_TIMEFRAMES,
        default="15m",
        help="使用する時間足 (デフォルト: 15m)",
    )

    parser.add_argument(
        "--symbol",
        choices=SUPPORTED_SYMBOLS,
        default="USDJPY",
        help="通貨ペア (デフォルト: USDJPY)",
    )

    parser.add_argument(
        "--save-as",
        default=None,
        help="指定した名前でこの実行のベスト戦略をsaved_strategies/に保存する",
    )

    parser.add_argument(
        "--optimizer",
        choices=["grid", "random", "genetic", "bayesian", "structure", "structure_genetic"],
        default="grid",
        help="grid=全探索 / random=ランダムサンプリング / genetic=遺伝的アルゴリズム / bayesian=ベイズ最適化(optuna) / "
        "structure=条件ツリーの自動構造生成(ランダムスクリーニング) / "
        "structure_genetic=条件ツリー構造自体を交叉・突然変異で進化させる (デフォルト: grid)",
    )

    parser.add_argument(
        "--n-candidates",
        type=int,
        default=500,
        help="--optimizer structure で生成する候補ストラテジー数 (デフォルト: 500)",
    )

    parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="--optimizer structure で生成する条件ツリーのAND/OR/NOTネスト最大深さ (デフォルト: 2)",
    )

    parser.add_argument(
        "--max-leaves",
        type=int,
        default=4,
        help="--optimizer structure で生成する条件ツリー1本あたりの条件数の目安上限 (デフォルト: 4)",
    )

    parser.add_argument(
        "--min-trades",
        type=int,
        default=30,
        help="--optimizer structure でランキング対象に残す最低トレード数。少なすぎるトレード数の候補は"
        "勝率100%/PF999のような統計的に無意味な値でランキング上位を占めてしまうため除外する (デフォルト: 30)",
    )

    parser.add_argument(
        "--mtf-probability",
        type=float,
        default=0.0,
        help="--optimizer structure/structure_genetic で、生成する条件の指標(または比較先)が"
        "バックテスト自身より粗い時間足を参照する確率 (デフォルト: 0.0=マルチタイムフレーム条件を生成しない)",
    )

    parser.add_argument(
        "--mtf-timeframes",
        default=None,
        help="--mtf-probability > 0 のときに参照する時間足をカンマ区切りで指定 "
        "(例: 1h,4h,1d)。未指定なら--timeframeより粗い時間足すべてを自動で対象にする",
    )

    parser.add_argument(
        "--n-samples",
        type=int,
        default=50,
        help="--optimizer random/bayesian で試すパラメータ組み合わせ数 (デフォルト: 50)",
    )

    parser.add_argument(
        "--population",
        type=int,
        default=20,
        help="--optimizer genetic の世代あたり個体数 (デフォルト: 20)",
    )

    parser.add_argument(
        "--mutation-rate",
        type=float,
        default=0.2,
        help="--optimizer genetic/structure_genetic の突然変異率 (デフォルト: 0.2)。"
        "structure_geneticでは葉の再生成/AND⇔OR反転が各ノードごとにこの確率で発生し、"
        "方向(Long/Short)反転はこの1/4の確率",
    )

    parser.add_argument(
        "--generations",
        type=int,
        default=30,
        help="--optimizer genetic/structure_genetic の世代数 (デフォルト: 30)。"
        "同じ総評価数(個体数×世代数)なら個体数を増やすより世代数を増やす方が"
        "良い結果に繋がりやすいという実験結果に基づく既定値(project_auto_exploration_core_goal.md参照)",
    )

    parser.add_argument(
        "--strategy-config",
        default=None,
        help="strategy_configs/*.json のパスを指定すると、--mode のグリッドの代わりにこの設定を使う",
    )

    return parser.parse_args()


def resolve_output_dir(symbol: str, timeframe: str) -> Path:
    parts = []

    if symbol != "USDJPY":
        parts.append(symbol)

    if timeframe != "15m":
        parts.append(timeframe)

    return Path("output").joinpath(*parts) if parts else Path("output")


JPY_PIP_SIZE = 0.01
NON_JPY_PIP_SIZE = 0.0001
# Metals quote to a different number of decimals than FX pairs (XAUUSD ~2000.00,
# XAGUSD ~25.000), so neither the JPY nor the non-JPY FX convention applies -
# each gets its own conventional pip size instead of falling through to
# NON_JPY_PIP_SIZE (which would be 100x too fine for both).
METAL_PIP_SIZE = {
    "XAUUSD": 0.01,
    "XAGUSD": 0.001,
}


def pip_size_for_symbol(symbol: str) -> float:
    if symbol in METAL_PIP_SIZE:
        return METAL_PIP_SIZE[symbol]
    return JPY_PIP_SIZE if symbol.endswith("JPY") else NON_JPY_PIP_SIZE


def build_trigger_filter_defaults() -> dict[str, list]:
    """Single-value defaults for the V3.0 trigger/filter param schema.

    Identical in both dev and full grids (kept as a single-element list so
    default behavior is exactly the pre-V3.0 breakout strategy in both
    modes). --optimizer random/genetic or a custom --strategy-config JSON
    is the intended way to explore wider values for these - deliberately
    NOT widened here, so `--mode full`'s existing grid size/runtime doesn't
    change.
    """
    return {
        "direction": ["short"],
        "entry_trigger": ["breakout"],
        "use_session_filter": [True],
        "use_min_body_filter": [True],
        "use_max_body_filter": [True],
        "use_max_wick_filter": [True],
        "use_ema_distance_filter": [True],
        "use_rsi_filter": [True],
        "use_donchian_filter": [False],
        "donchian_period": [20],
        "use_bollinger_filter": [False],
        "bollinger_period": [20],
        "bollinger_std": [2.0],
        "use_macd_filter": [False],
        "macd_fast": [12],
        "macd_slow": [26],
        "macd_signal": [9],
        "use_ichimoku_filter": [False],
        "ichimoku_tenkan": [9],
        "ichimoku_kijun": [26],
        "ichimoku_senkou_b": [52],
        "use_stochastic_filter": [False],
        "stochastic_k_period": [14],
        "stochastic_d_period": [3],
        "stochastic_smooth": [3],
        "stochastic_level": [80.0],
        "use_pivot_filter": [False],
        "use_prev_high_filter": [False],
        "use_prev_low_filter": [False],
        "use_round_number_filter": [False],
        "round_number_pips": [10.0],
        "use_weekday_filter": [False],
        "weekday_monday": [True],
        "weekday_tuesday": [True],
        "weekday_wednesday": [True],
        "weekday_thursday": [True],
        "weekday_friday": [True],
        "adr_period": [14],
        # Tier 3 (SMC) - unverified against TradingView, see engine/smc_indicators.py.
        "use_fvg_filter": [False],
        "use_order_block_filter": [False],
        "use_bos_filter": [False],
        "use_choch_filter": [False],
        "use_liquidity_sweep_filter": [False],
        "smc_swing_lookback": [5],
        # Tier 2 - Wilder ATR-based, unblocked 2026-07-03.
        "use_supertrend_filter": [False],
        "supertrend_period": [10],
        "supertrend_multiplier": [3.0],
        "use_adx_filter": [False],
        "adx_period": [14],
        "adx_threshold": [25.0],
    }


def build_parameter_space(mode: str, symbol: str = "USDJPY") -> dict[str, list]:
    pip_size = pip_size_for_symbol(symbol)

    if mode == "dev":
        return {
            "ema_length": [200],
            "min_body_pips": [20.0],
            "max_body_pips": [0.0],
            "max_wick_pips": [0.0],
            "lookahead_bars": [15],
            "breakout_bars": [30],
            "ema_distance_pips": [50.0],
            "rsi_min": [70.0],
            "rr": [1.2],
            "session_start": [8],
            "session_end": [3],
            "use_weekend_exit": [True],
            "weekend_exit_hour": [4],
            "use_daily_exit": [False],
            "daily_exit_hour": [4],
            "pip_size": [pip_size],
            "symbol": [symbol],
            **build_trigger_filter_defaults(),
        }

    return {
        "ema_length": [150, 200, 250],
        "min_body_pips": [15.0, 20.0, 25.0],
        "max_body_pips": [0.0],
        "max_wick_pips": [0.0],
        "lookahead_bars": [15],
        "breakout_bars": [30],
        "ema_distance_pips": [40.0, 50.0, 60.0],
        "rsi_min": [65.0, 70.0, 75.0],
        "rr": [1.0, 1.2, 1.5],
        "session_start": [8],
        "session_end": [3],
        "use_weekend_exit": [True],
        "weekend_exit_hour": [4],
        "use_daily_exit": [False],
        "daily_exit_hour": [4],
        "pip_size": [pip_size],
        "symbol": [symbol],
        **build_trigger_filter_defaults(),
    }


def build_grid_from_space(param_space: dict[str, list]) -> list[dict]:
    keys = list(param_space.keys())
    combos = itertools.product(*[param_space[key] for key in keys])

    return [dict(zip(keys, combo)) for combo in combos]


def build_parameter_grid(mode: str, symbol: str = "USDJPY") -> list[dict]:
    return build_grid_from_space(build_parameter_space(mode, symbol))


def init_worker(df: pd.DataFrame) -> None:
    global _WORKER_DF, _WORKER_IS_INTRADAY
    _WORKER_DF = df
    _WORKER_IS_INTRADAY = compute_is_intraday(df["datetime"])
    # In real ProcessPoolExecutor usage this only ever runs once per worker
    # process (the initializer, called at worker startup) so this reset is
    # a no-op there - but init_worker can legitimately be called more than
    # once with a DIFFERENT df in the same process outside that context
    # (e.g. tests/test_regression.py calls it directly, once per timeframe
    # case, in a single process) - without clearing here, a stale cached
    # series computed against the OLD df could get silently reused against
    # the new one if both dataframes happened to produce the same
    # (indicator, params) cache key, exactly the danger
    # evaluate_condition_tree's docstring warns callers about.
    _WORKER_INDICATOR_CACHE.clear()


def run_one_backtest(task: tuple[int, dict]) -> dict:
    global _WORKER_DF, _WORKER_IS_INTRADAY

    if _WORKER_DF is None:
        raise RuntimeError("Worker data is not initialized.")

    param_id, params = task

    result, trade_log = run_backtest(
        df=_WORKER_DF,
        params=params,
        indicator_cache=_WORKER_INDICATOR_CACHE,
        return_trades=True,
        is_intraday=_WORKER_IS_INTRADAY,
    )

    yearly_df = build_yearly_analysis(trade_log)
    monthly_df = build_monthly_analysis(trade_log)
    stability = calculate_stability_metrics(trade_log, yearly_df, monthly_df)
    advanced = calculate_advanced_metrics(trade_log, monthly_df)

    result["param_id"] = param_id
    result["yearly_stability_score"] = stability["yearly_stability_score"]
    result["monthly_stability_score"] = stability["monthly_stability_score"]
    result["overall_stability_score"] = stability["overall_stability_score"]
    result["stability_rating"] = stability["rating"]
    result["sharpe_ratio"] = advanced["sharpe_ratio"]
    result["sortino_ratio"] = advanced["sortino_ratio"]
    result["cagr"] = advanced["cagr"]
    result["calmar_ratio"] = advanced["calmar_ratio"]

    return result


def export_single_strategy_analysis(df: pd.DataFrame, params: dict, output_dir: Path) -> dict:
    """Runs one backtest for `params` and writes every per-strategy analysis
    artifact (trade_log/equity_curve/yearly/monthly/stability/monte_carlo)
    to output_dir - exactly what main()'s own end-of-run "best row" export
    already did inline. Factored out so rerun_ranking_row.py (re-running an
    arbitrary OTHER ranking row the user picked in the dashboard, not just
    the top-ranked one) shares this instead of risking a second copy drifting
    from main()'s own version.

    export_yearly_analysis/export_monthly_analysis/export_stability_analysis
    (unlike export_equity_curve/export_monte_carlo) write to the module-level
    OUTPUT_DIR global rather than taking an output_dir parameter - a
    pre-existing inconsistency in this file, not introduced here. Setting the
    global explicitly makes this function actually honor its own output_dir
    argument regardless of what the caller left OUTPUT_DIR set to, rather
    than silently depending on main() having already set it correctly."""
    global OUTPUT_DIR
    OUTPUT_DIR = output_dir

    _, trade_log = run_backtest(df=df, params=params, return_trades=True)

    trade_log_path = output_dir / "trade_log.csv"
    trade_log.to_csv(trade_log_path, index=False, encoding="utf-8-sig")

    yearly_df = export_yearly_analysis(trade_log)
    monthly_df = export_monthly_analysis(trade_log)
    stability_df = export_stability_analysis(yearly_df, monthly_df)

    equity_df = export_equity_curve(trade_log=trade_log, output_dir=output_dir)

    monte_carlo_results, monte_carlo_summary = export_monte_carlo(
        trade_log=trade_log, output_dir=output_dir
    )

    return {
        "trade_log": trade_log,
        "yearly_df": yearly_df,
        "monthly_df": monthly_df,
        "stability_df": stability_df,
        "equity_df": equity_df,
        "monte_carlo_results": monte_carlo_results,
        "monte_carlo_summary": monte_carlo_summary,
    }


def add_rank_column(df: pd.DataFrame) -> pd.DataFrame:
    ranked = df.reset_index(drop=True).copy()
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ranked


def export_rankings(result_df: pd.DataFrame) -> dict[str, Path]:
    rankings = {
        "total": result_df.sort_values(
            by=[
                "profit_factor",
                "overall_stability_score",
                "net_profit",
                "max_dd",
                "trades",
            ],
            ascending=[False, False, False, True, False],
        ),
        "pf": result_df.sort_values(
            by=["profit_factor", "overall_stability_score", "net_profit", "max_dd"],
            ascending=[False, False, False, True],
        ),
        "dd": result_df.sort_values(
            by=["max_dd", "profit_factor", "overall_stability_score", "net_profit"],
            ascending=[True, False, False, False],
        ),
        "win_rate": result_df.sort_values(
            by=["win_rate", "profit_factor", "overall_stability_score", "net_profit"],
            ascending=[False, False, False, False],
        ),
        "profit": result_df.sort_values(
            by=["net_profit", "profit_factor", "overall_stability_score", "max_dd"],
            ascending=[False, False, False, True],
        ),
        "expected_value": result_df.sort_values(
            by=[
                "expected_value",
                "profit_factor",
                "overall_stability_score",
                "net_profit",
            ],
            ascending=[False, False, False, False],
        ),
        "yearly_stability": result_df.sort_values(
            by=["yearly_stability_score", "profit_factor", "net_profit", "max_dd"],
            ascending=[False, False, False, True],
        ),
        "monthly_stability": result_df.sort_values(
            by=["monthly_stability_score", "profit_factor", "net_profit", "max_dd"],
            ascending=[False, False, False, True],
        ),
        "overall_stability": result_df.sort_values(
            by=["overall_stability_score", "profit_factor", "net_profit", "max_dd"],
            ascending=[False, False, False, True],
        ),
        "recovery_factor": result_df.sort_values(
            by=["recovery_factor", "profit_factor", "overall_stability_score", "net_profit"],
            ascending=[False, False, False, False],
        ),
    }

    paths: dict[str, Path] = {}

    for name, ranking_df in rankings.items():
        output_path = OUTPUT_DIR / f"ranking_{name}.csv"
        add_rank_column(ranking_df).to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig",
        )
        paths[name] = output_path

    return paths


def format_seconds(seconds: float) -> str:
    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def write_progress_file(
    completed: int,
    total: int,
    elapsed: float,
    generation: int | None = None,
    generations_total: int | None = None,
) -> None:
    """Lets api_server.py's job-status polling show live progress for a
    structure/structure_genetic run - this is the only channel available for
    that, since main.py runs as a fire-and-forget subprocess (api_server.py
    only reads its stdout/stderr once the whole process exits, not as it
    runs) and stdout's own progress prints are Japanese prose, not meant to
    be machine-parsed. Overwritten on every progress tick (same cadence as
    the existing print statements) rather than appended, so a crashed run
    just leaves the last-known state instead of a growing log."""
    payload = {
        "completed": completed,
        "total": total,
        "elapsed_seconds": round(elapsed, 1),
        "generation": generation,
        "generations_total": generations_total,
    }
    (OUTPUT_DIR / "progress.json").write_text(json.dumps(payload), encoding="utf-8")


def calc_profit_factor(profits: pd.Series) -> float:
    gross_profit = profits[profits > 0].sum()
    gross_loss = profits[profits < 0].sum()

    if gross_loss < 0:
        return float(gross_profit / abs(gross_loss))

    if gross_profit > 0:
        return 999.0

    return 0.0


def safe_mean(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.mean())


def calc_positive_rate(profits: pd.Series) -> float:
    if len(profits) == 0:
        return 0.0
    return float((profits > 0).sum() / len(profits) * 100)


def calc_stability_score(profits: pd.Series) -> float:
    if len(profits) == 0:
        return 0.0

    positive_rate = calc_positive_rate(profits)
    avg_profit = safe_mean(profits)

    if avg_profit <= 0:
        return round(positive_rate * 0.5, 2)

    volatility = float(profits.std()) if len(profits) >= 2 else 0.0

    if volatility <= 0:
        return 100.0 if avg_profit > 0 else 0.0

    stability = avg_profit / volatility
    score = positive_rate * 0.7 + min(stability * 30, 30)

    return round(max(0.0, min(score, 100.0)), 2)


def _build_period_analysis(trade_log: pd.DataFrame, period_column: str, period_key: pd.Series) -> pd.DataFrame:
    """Shared vectorized implementation for build_yearly_analysis/
    build_monthly_analysis - groups by period_key and aggregates via
    groupby().agg() (compiled/vectorized pandas internals) instead of a
    Python for-loop over the groupby object. Iterating a groupby object
    materializes a new sub-DataFrame slice per group, which profiled at
    ~0.6s for a ~14,000-trade/~290-group backtest despite each group's own
    computation being trivial - purely per-iteration Python/pandas
    overhead, and this function is called on every single mass-search task
    (via calculate_stability_metrics/calculate_advanced_metrics), so it was
    the single largest remaining cost after the market-order loop itself
    was moved to numba (engine/numba_fast_backtest.py)."""
    if trade_log.empty:
        return pd.DataFrame()

    df = trade_log.copy()
    df[period_column] = period_key
    df["_is_win"] = df["profit"] > 0
    df["_is_loss"] = df["profit"] < 0
    df["_gross_profit_part"] = df["profit"].where(df["_is_win"], 0.0)
    df["_gross_loss_part"] = df["profit"].where(df["_is_loss"], 0.0)

    grouped = df.groupby(period_column).agg(
        trades=("profit", "size"),
        wins=("_is_win", "sum"),
        losses=("_is_loss", "sum"),
        net_profit=("profit", "sum"),
        gross_profit=("_gross_profit_part", "sum"),
        gross_loss=("_gross_loss_part", "sum"),
    ).reset_index()

    grouped["wins"] = grouped["wins"].astype(int)
    grouped["losses"] = grouped["losses"].astype(int)
    grouped["win_rate"] = np.where(
        grouped["trades"] > 0, grouped["wins"] / grouped["trades"] * 100, 0.0
    )
    grouped["profit_factor"] = np.where(
        grouped["gross_loss"] < 0,
        grouped["gross_profit"] / grouped["gross_loss"].abs(),
        np.where(grouped["gross_profit"] > 0, 999.0, 0.0),
    )

    grouped["win_rate"] = grouped["win_rate"].round(2)
    grouped["net_profit"] = grouped["net_profit"].round(5)
    grouped["gross_profit"] = grouped["gross_profit"].round(5)
    grouped["gross_loss"] = grouped["gross_loss"].round(5)
    grouped["profit_factor"] = grouped["profit_factor"].round(3)

    return grouped[
        [period_column, "trades", "wins", "losses", "win_rate", "net_profit", "gross_profit", "gross_loss", "profit_factor"]
    ].sort_values(period_column).reset_index(drop=True)


def build_yearly_analysis(trade_log: pd.DataFrame) -> pd.DataFrame:
    if trade_log.empty:
        return pd.DataFrame()

    entry_time = pd.to_datetime(trade_log["entry_time"], errors="coerce")
    result = _build_period_analysis(trade_log, "year", entry_time.dt.year)
    result["year"] = result["year"].astype(int)
    return result


def build_monthly_analysis(trade_log: pd.DataFrame) -> pd.DataFrame:
    if trade_log.empty:
        return pd.DataFrame()

    entry_time = pd.to_datetime(trade_log["entry_time"], errors="coerce")
    return _build_period_analysis(trade_log, "year_month", entry_time.dt.to_period("M").astype(str))


def calculate_stability_metrics(
    trade_log: pd.DataFrame,
    yearly_df: pd.DataFrame | None = None,
    monthly_df: pd.DataFrame | None = None,
) -> dict:
    # yearly_df/monthly_df accepted pre-computed (falling back to computing
    # them here if not given, so existing callers passing just trade_log
    # keep working unchanged) - run_one_backtest computes both once and
    # shares them with calculate_advanced_metrics below, since this
    # function and that one previously each computed build_monthly_analysis
    # independently for every single mass-search task (profiled: ~0.6s per
    # call before build_yearly_analysis/build_monthly_analysis were
    # vectorized, doubled by being computed twice).
    if yearly_df is None:
        yearly_df = build_yearly_analysis(trade_log)
    if monthly_df is None:
        monthly_df = build_monthly_analysis(trade_log)

    if yearly_df.empty or monthly_df.empty:
        return {
            "yearly_stability_score": 0.0,
            "monthly_stability_score": 0.0,
            "overall_stability_score": 0.0,
            "rating": "D",
        }

    yearly_profits = yearly_df["net_profit"]
    monthly_profits = monthly_df["net_profit"]

    yearly_stability = calc_stability_score(yearly_profits)
    monthly_stability = calc_stability_score(monthly_profits)

    overall_stability = round(
        yearly_stability * 0.6 + monthly_stability * 0.4,
        2,
    )

    if overall_stability >= 80:
        rating = "A"
    elif overall_stability >= 65:
        rating = "B"
    elif overall_stability >= 50:
        rating = "C"
    else:
        rating = "D"

    return {
        "yearly_stability_score": yearly_stability,
        "monthly_stability_score": monthly_stability,
        "overall_stability_score": overall_stability,
        "rating": rating,
    }


def calculate_advanced_metrics(trade_log: pd.DataFrame, monthly_df: pd.DataFrame | None = None) -> dict:
    if trade_log.empty:
        return {
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "cagr": 0.0,
            "calmar_ratio": 0.0,
        }

    if monthly_df is None:
        monthly_df = build_monthly_analysis(trade_log)
    monthly_returns = monthly_df["net_profit"] if not monthly_df.empty else pd.Series(dtype=float)

    entry_times = pd.to_datetime(trade_log["entry_time"], errors="coerce")
    exit_times = pd.to_datetime(trade_log["exit_time"], errors="coerce")
    span_days = (exit_times.max() - entry_times.min()).days
    years = span_days / 365.25 if span_days > 0 else 0.0

    net_profit = float(trade_log["profit"].sum())
    max_dd = calc_max_dd(trade_log["profit"].to_numpy())

    cagr_value = cagr(net_profit, years)

    return {
        "sharpe_ratio": round(sharpe_ratio(monthly_returns), 3),
        "sortino_ratio": round(sortino_ratio(monthly_returns), 3),
        "cagr": round(cagr_value, 5),
        "calmar_ratio": round(calmar_ratio(cagr_value, max_dd), 3),
    }


def export_yearly_analysis(trade_log: pd.DataFrame) -> pd.DataFrame:
    output_path = OUTPUT_DIR / "yearly_analysis.csv"
    result_df = build_yearly_analysis(trade_log)
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return result_df


def export_monthly_analysis(trade_log: pd.DataFrame) -> pd.DataFrame:
    output_path = OUTPUT_DIR / "monthly_analysis.csv"
    result_df = build_monthly_analysis(trade_log)
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return result_df


def export_stability_analysis(
    yearly_df: pd.DataFrame,
    monthly_df: pd.DataFrame,
) -> pd.DataFrame:
    output_path = OUTPUT_DIR / "stability_analysis.csv"

    if yearly_df.empty or monthly_df.empty:
        result_df = pd.DataFrame()
        result_df.to_csv(output_path, index=False, encoding="utf-8-sig")
        return result_df

    yearly_profits = yearly_df["net_profit"]
    monthly_profits = monthly_df["net_profit"]

    yearly_positive_rate = calc_positive_rate(yearly_profits)
    monthly_positive_rate = calc_positive_rate(monthly_profits)

    yearly_stability = calc_stability_score(yearly_profits)
    monthly_stability = calc_stability_score(monthly_profits)

    total_profit = float(yearly_profits.sum())

    profitable_years = int((yearly_profits > 0).sum())
    losing_years = int((yearly_profits < 0).sum())
    flat_years = int((yearly_profits == 0).sum())

    profitable_months = int((monthly_profits > 0).sum())
    losing_months = int((monthly_profits < 0).sum())
    flat_months = int((monthly_profits == 0).sum())

    avg_yearly_profit = safe_mean(yearly_profits)
    avg_monthly_profit = safe_mean(monthly_profits)

    worst_year_profit = float(yearly_profits.min()) if len(yearly_profits) else 0.0
    best_year_profit = float(yearly_profits.max()) if len(yearly_profits) else 0.0

    worst_month_profit = float(monthly_profits.min()) if len(monthly_profits) else 0.0
    best_month_profit = float(monthly_profits.max()) if len(monthly_profits) else 0.0

    overall_stability = round(
        yearly_stability * 0.6 + monthly_stability * 0.4,
        2,
    )

    if overall_stability >= 80:
        rating = "A"
    elif overall_stability >= 65:
        rating = "B"
    elif overall_stability >= 50:
        rating = "C"
    else:
        rating = "D"

    result = {
        "total_profit": round(total_profit, 5),
        "profitable_years": profitable_years,
        "losing_years": losing_years,
        "flat_years": flat_years,
        "yearly_positive_rate": round(yearly_positive_rate, 2),
        "avg_yearly_profit": round(avg_yearly_profit, 5),
        "best_year_profit": round(best_year_profit, 5),
        "worst_year_profit": round(worst_year_profit, 5),
        "yearly_stability_score": yearly_stability,
        "profitable_months": profitable_months,
        "losing_months": losing_months,
        "flat_months": flat_months,
        "monthly_positive_rate": round(monthly_positive_rate, 2),
        "avg_monthly_profit": round(avg_monthly_profit, 5),
        "best_month_profit": round(best_month_profit, 5),
        "worst_month_profit": round(worst_month_profit, 5),
        "monthly_stability_score": monthly_stability,
        "overall_stability_score": overall_stability,
        "rating": rating,
    }

    result_df = pd.DataFrame([result])
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    return result_df


def print_analysis_summary(
    yearly_df: pd.DataFrame,
    monthly_df: pd.DataFrame,
    stability_df: pd.DataFrame,
) -> None:
    print("")
    print("========== Period Analysis ==========")
    print("")

    if not yearly_df.empty:
        print("年別分析")
        print(yearly_df.to_string(index=False))
        print("")

    if not stability_df.empty:
        row = stability_df.iloc[0]
        print("安定度")
        print(f"  年別安定度: {row['yearly_stability_score']}")
        print(f"  月別安定度: {row['monthly_stability_score']}")
        print(f"  総合安定度: {row['overall_stability_score']}")
        print(f"  評価: {row['rating']}")
        print("")


def main() -> None:
    global OUTPUT_DIR

    args = parse_args()

    OUTPUT_DIR = resolve_output_dir(args.symbol, args.timeframe)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data_path = find_data_file(args.timeframe, args.symbol)
    print(f"モード: {args.mode}")
    print(f"通貨ペア: {args.symbol}")
    print(f"時間足: {args.timeframe}")
    print(f"読み込み: {data_path}")

    df = load_price_data(data_path)

    print(f"データ数: {len(df):,}")
    print(f"期間: {df['datetime'].min()} ～ {df['datetime'].max()}")

    # Shared by both structure/structure_genetic modes: resolve which
    # timeframes MTF-generated conditions may reference. Explicit
    # --mtf-timeframes wins; otherwise, if MTF generation is enabled at all
    # (--mtf-probability > 0), default to every timeframe coarser than this
    # run's own --timeframe (the only sane MTF direction - see
    # coarser_timeframes()'s docstring).
    if args.mtf_timeframes:
        mtf_timeframes = [tf.strip() for tf in args.mtf_timeframes.split(",") if tf.strip()]
    elif args.mtf_probability > 0:
        mtf_timeframes = coarser_timeframes(args.timeframe)
    else:
        mtf_timeframes = None

    if args.optimizer == "structure":
        # Phase 1 of the auto-exploration engine (see
        # project_auto_exploration_core_goal.md): base_space supplies every
        # non-tree field (rr/session/exit rules/etc, all single-value in
        # dev mode) exactly as build_parameter_space() already does for any
        # other run; condition_tree and direction are then overridden with
        # the generated candidates, and build_grid_from_space's existing
        # itertools.product cross-multiplies each generated structure
        # against both directions - no change needed to the grid/backtest/
        # ranking machinery below.
        param_space = build_parameter_space(args.mode, args.symbol)
        param_space["condition_tree"] = generate_candidate_trees(
            n=args.n_candidates,
            max_depth=args.max_depth,
            max_leaves=args.max_leaves,
            mtf_timeframes=mtf_timeframes,
            mtf_probability=args.mtf_probability,
        )
        param_space["direction"] = ["long", "short"]
        print(f"構造生成candidate数: {len(param_space['condition_tree'])} (要求: {args.n_candidates})")
    elif args.optimizer == "structure_genetic":
        # base_space's non-tree fields (rr/session/exit rules/etc) stay
        # fixed defaults exactly like --optimizer structure - only
        # condition_tree/direction evolve here, driven per-generation below
        # (StructureGeneticSearch), not by build_grid_from_space.
        param_space = build_parameter_space(args.mode, args.symbol)
    elif args.strategy_config:
        param_space = load_strategy_config(Path(args.strategy_config))
        print(f"ストラテジー設定ファイル: {args.strategy_config}")
    else:
        param_space = build_parameter_space(args.mode, args.symbol)

    start_time = time.time()

    if args.optimizer == "bayesian":
        print(f"最適化方式: {args.optimizer} (optuna TPE)")
        print(f"試行回数: {args.n_samples}")

        def bayesian_progress(completed: int, total: int) -> None:
            if completed % 10 == 0 or completed == total:
                elapsed = time.time() - start_time
                print(f"{completed}/{total} 完了 経過 {format_seconds(elapsed)}")

        is_intraday_flag = compute_is_intraday(df["datetime"])
        results = run_bayesian_search(
            df=df,
            is_intraday=is_intraday_flag,
            param_space=param_space,
            n_trials=args.n_samples,
            stability_fn=calculate_stability_metrics,
            advanced_metrics_fn=calculate_advanced_metrics,
            progress_callback=bayesian_progress,
        )
    else:
        if args.optimizer in ("grid", "structure"):
            parameter_list = build_grid_from_space(param_space)
            total_tasks = len(parameter_list)
        elif args.optimizer == "random":
            parameter_list = sample_random_combos(param_space, args.n_samples)
            total_tasks = len(parameter_list)
        else:
            parameter_list = None
            total_tasks = args.population

        workers = min(MAX_WORKERS, os.cpu_count() or 1, total_tasks)

        print(f"最適化方式: {args.optimizer}")
        if args.optimizer in ("genetic", "structure_genetic"):
            print(f"検証パターン数: {total_tasks} x {args.generations}世代")
        else:
            print(f"検証パターン数: {total_tasks}")
        print(f"並列数: {workers}")

        def run_batch(
            executor: ProcessPoolExecutor,
            param_dicts: list[dict],
            id_offset: int,
            progress_base: int = 0,
            progress_total: int | None = None,
            generation: int | None = None,
            generations_total: int | None = None,
        ) -> list[dict]:
            tasks = list(enumerate(param_dicts, start=id_offset))
            futures = [executor.submit(run_one_backtest, task) for task in tasks]

            batch_results = []
            for completed, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                batch_results.append(result)

                if completed % 10 == 0 or completed == len(tasks):
                    elapsed = time.time() - start_time
                    print(f"{completed}/{len(tasks)} 完了 経過 {format_seconds(elapsed)}")
                    # Only structure/structure_genetic runs actually have a UI
                    # polling for this (see api_server.py's job-status
                    # endpoint) - written unconditionally anyway since it's
                    # cheap and harmless for grid/random/genetic too.
                    write_progress_file(
                        completed=progress_base + completed,
                        total=progress_total if progress_total is not None else len(tasks),
                        elapsed=elapsed,
                        generation=generation,
                        generations_total=generations_total,
                    )

            return batch_results

        results = []

        if args.optimizer in ("structure", "structure_genetic"):
            # Written once up front so a job-status poll landing before the
            # first in-loop checkpoint (run_batch only writes every 10
            # completions) sees this run's own 0/total, not a stale
            # progress.json left over from a previous run that used the same
            # --symbol/--timeframe output directory.
            write_progress_file(
                completed=0,
                total=total_tasks if args.optimizer == "structure" else args.population * args.generations,
                elapsed=0.0,
                generation=1 if args.optimizer == "structure_genetic" else None,
                generations_total=args.generations if args.optimizer == "structure_genetic" else None,
            )

        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=init_worker,
            initargs=(df,),
        ) as executor:
            if args.optimizer in ("grid", "random", "structure"):
                results = run_batch(executor, parameter_list, id_offset=1, progress_total=total_tasks)
            elif args.optimizer == "structure_genetic":
                # base_defaults supplies every non-tree field (rr/session/
                # exit rules/etc) as plain scalars, extracted once from the
                # dev/full-mode single-value lists - each generation's
                # individuals ({"condition_tree","direction"} only) get
                # merged with this into a full run_one_backtest()-ready
                # params dict.
                base_defaults = {key: values[0] for key, values in param_space.items()}
                search = StructureGeneticSearch(
                    population_size=args.population,
                    mutation_rate=args.mutation_rate,
                    max_depth=args.max_depth,
                    max_leaves=args.max_leaves,
                    mtf_timeframes=mtf_timeframes,
                    mtf_probability=args.mtf_probability,
                )
                population = search.initial_population()
                next_id = 1

                for generation in range(1, args.generations + 1):
                    print(f"[構造遺伝的アルゴリズム] 世代 {generation}/{args.generations}")
                    task_params = [
                        {**base_defaults, "condition_tree": ind["condition_tree"], "direction": ind["direction"]}
                        for ind in population
                    ]
                    generation_results = run_batch(
                        executor,
                        task_params,
                        id_offset=next_id,
                        progress_base=(generation - 1) * args.population,
                        progress_total=args.population * args.generations,
                        generation=generation,
                        generations_total=args.generations,
                    )
                    next_id += len(population)
                    results.extend(generation_results)

                    # Fitness must penalize low trade counts BEFORE selection,
                    # not just at the final ranking step (see
                    # StructureGeneticSearch's docstring) - otherwise the GA's
                    # selection pressure converges the whole population onto
                    # the same 1-3-trade profit_factor=999 exploit that MVP1's
                    # ranking-only --min-trades filter had to clean up after
                    # the fact.
                    #
                    # Rebuilt from each result's OWN echoed-back params
                    # (result = {**p, ...} in backtest_engine.py) rather than
                    # zip(generation_results, population) - run_batch collects
                    # futures via as_completed(), which yields results in
                    # COMPLETION order, not submission order, so pairing by
                    # position silently mismatched each fitness score with the
                    # wrong individual (confirmed: this broke elitism in a
                    # real run - best fitness was NOT monotonic across
                    # generations despite next_population()'s elite carryover
                    # being correct in isolation, see
                    # project_auto_exploration_core_goal.md). This mirrors the
                    # scalar `genetic` branch below, which was never affected
                    # since it already rebuilds each individual from `result`
                    # itself instead of a separately-tracked population list.
                    scored_population = [
                        (
                            result["profit_factor"] if result["trades"] >= args.min_trades else 0.0,
                            {"condition_tree": result["condition_tree"], "direction": result["direction"]},
                        )
                        for result in generation_results
                    ]
                    fitness_values = [fitness for fitness, _ in scored_population]
                    print(
                        f"  世代{generation} 適応度: best={max(fitness_values):.3f} "
                        f"avg={sum(fitness_values) / len(fitness_values):.3f} "
                        f"(0.0={sum(1 for f in fitness_values if f == 0.0)}件/{len(fitness_values)}件)"
                    )
                    population = search.next_population(scored_population)
            else:
                search = GeneticSearch(
                    param_space, population_size=args.population, mutation_rate=args.mutation_rate
                )
                population = search.initial_population()
                next_id = 1

                for generation in range(1, args.generations + 1):
                    print(f"[遺伝的アルゴリズム] 世代 {generation}/{args.generations}")
                    generation_results = run_batch(executor, population, id_offset=next_id)
                    next_id += len(population)
                    results.extend(generation_results)

                    scored_population = [
                        (result["profit_factor"], {key: result[key] for key in param_space})
                        for result in generation_results
                    ]
                    population = search.next_population(scored_population)

    result_df = pd.DataFrame(results)

    if args.optimizer in ("structure", "structure_genetic"):
        # Auto-generated candidates commonly include near-degenerate
        # low-signal structures (rare AND chains, boolean-only conditions
        # that rarely align) that trade only a handful of times - a 1-3
        # trade all-winners candidate hits profit_factor's zero-loss cap
        # (999) and overall_stability_score's cap (100), so it dominates
        # export_rankings()'s sort ahead of genuinely tested candidates
        # with hundreds/thousands of trades. This never surfaced before
        # structure search existed: a human-built or hand-optimized
        # strategy is never submitted for ranking with only 1-3 trades.
        before_count = len(result_df)
        result_df = result_df[result_df["trades"] >= args.min_trades].reset_index(drop=True)
        print(
            f"最低トレード数フィルター({args.min_trades}件以上): "
            f"{len(result_df)}/{before_count} 件が対象"
        )
        if result_df.empty:
            raise ValueError(
                f"--min-trades {args.min_trades} 件以上のトレードがある候補がありませんでした。"
                "--n-candidatesを増やすか--min-tradesを下げて再実行してください。"
            )

    ranking_paths = export_rankings(result_df)

    ranking_total = pd.read_csv(ranking_paths["total"])

    best_row = ranking_total.iloc[0].to_dict()
    best_params = reconstruct_params_from_row(best_row)

    analysis = export_single_strategy_analysis(df, best_params, OUTPUT_DIR)
    best_trade_log = analysis["trade_log"]
    yearly_df = analysis["yearly_df"]
    monthly_df = analysis["monthly_df"]
    stability_df = analysis["stability_df"]
    equity_df = analysis["equity_df"]
    monte_carlo_results = analysis["monte_carlo_results"]
    monte_carlo_summary = analysis["monte_carlo_summary"]

    trade_log_path = OUTPUT_DIR / "trade_log.csv"

    report_path = export_html_report(
        output_dir=OUTPUT_DIR,
        mode=args.mode,
        timeframe=args.timeframe,
        ranking_total=ranking_total,
        yearly_df=yearly_df,
        monthly_df=monthly_df,
        stability_df=stability_df,
        equity_df=equity_df,
        monte_carlo_summary=monte_carlo_summary,
    )

    pdf_report_path = export_pdf_report(
        output_dir=OUTPUT_DIR,
        mode=args.mode,
        timeframe=args.timeframe,
        symbol=args.symbol,
        ranking_total=ranking_total,
        equity_df=equity_df,
        stability_df=stability_df,
        monte_carlo_summary=monte_carlo_summary,
    )

    if args.save_as:
        saved_entry = save_strategy(
            output_dir=OUTPUT_DIR,
            mode=args.mode,
            timeframe=args.timeframe,
            best_row=best_row,
            params=best_params,
            name=args.save_as,
            strategy_config=args.strategy_config,
            symbol=args.symbol,
        )
        print(f"戦略を保存しました: {saved_entry['id']} ({saved_entry['name']})")

    elapsed_total = time.time() - start_time

    print("完了")
    print(f"総実行時間: {format_seconds(elapsed_total)}")
    print("ランキング出力:")
    for name, path in ranking_paths.items():
        print(f"  {name}: {path}")

    print(f"取引履歴出力: {trade_log_path}")
    print(f"年別分析出力: {OUTPUT_DIR / 'yearly_analysis.csv'}")
    print(f"月別分析出力: {OUTPUT_DIR / 'monthly_analysis.csv'}")
    print(f"安定度分析出力: {OUTPUT_DIR / 'stability_analysis.csv'}")
    print(f"Equity Curve出力: {OUTPUT_DIR / 'equity_curve.csv'}")
    print(f"Monte Carlo出力: {OUTPUT_DIR / 'monte_carlo_results.csv'}")
    print(f"Monte Carloサマリー出力: {OUTPUT_DIR / 'monte_carlo_summary.csv'}")
    print(f"HTMLレポート出力: {report_path}")
    print(f"PDFレポート出力: {pdf_report_path}")
    print("")
    print("総合ランキング 上位20件")
    print(ranking_total.head(20).to_string(index=False))

    print_analysis_summary(yearly_df, monthly_df, stability_df)
    print_monte_carlo_summary(monte_carlo_results, monte_carlo_summary)


if __name__ == "__main__":
    main()