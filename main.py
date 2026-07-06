from pathlib import Path
import argparse
import itertools
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

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
from engine.params import reconstruct_params_from_row


AVAILABLE_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

SUPPORTED_SYMBOLS = [
    "USDJPY",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
    "AUDUSD",
    "EURUSD",
    "GBPUSD",
]

OUTPUT_DIR = Path("output")

MAX_WORKERS = 8

_WORKER_DF = None
_WORKER_IS_INTRADAY = True


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
        choices=["grid", "random", "genetic", "bayesian"],
        default="grid",
        help="grid=全探索 / random=ランダムサンプリング / genetic=遺伝的アルゴリズム / bayesian=ベイズ最適化(optuna) (デフォルト: grid)",
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
        "--generations",
        type=int,
        default=10,
        help="--optimizer genetic の世代数 (デフォルト: 10)",
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


def pip_size_for_symbol(symbol: str) -> float:
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


def run_one_backtest(task: tuple[int, dict]) -> dict:
    global _WORKER_DF, _WORKER_IS_INTRADAY

    if _WORKER_DF is None:
        raise RuntimeError("Worker data is not initialized.")

    param_id, params = task

    result, trade_log = run_backtest(
        df=_WORKER_DF,
        params=params,
        return_trades=True,
        is_intraday=_WORKER_IS_INTRADAY,
    )

    stability = calculate_stability_metrics(trade_log)
    advanced = calculate_advanced_metrics(trade_log)

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


def build_yearly_analysis(trade_log: pd.DataFrame) -> pd.DataFrame:
    if trade_log.empty:
        return pd.DataFrame()

    df = trade_log.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["year"] = df["entry_time"].dt.year

    rows = []

    for year, group in df.groupby("year"):
        profits = group["profit"]

        trades = len(group)
        wins = int((profits > 0).sum())
        losses = int((profits < 0).sum())
        win_rate = wins / trades * 100 if trades else 0.0

        net_profit = profits.sum()
        gross_profit = profits[profits > 0].sum()
        gross_loss = profits[profits < 0].sum()
        profit_factor = calc_profit_factor(profits)

        rows.append(
            {
                "year": int(year),
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "net_profit": round(net_profit, 5),
                "gross_profit": round(gross_profit, 5),
                "gross_loss": round(gross_loss, 5),
                "profit_factor": round(profit_factor, 3),
            }
        )

    return pd.DataFrame(rows).sort_values("year")


def build_monthly_analysis(trade_log: pd.DataFrame) -> pd.DataFrame:
    if trade_log.empty:
        return pd.DataFrame()

    df = trade_log.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["year_month"] = df["entry_time"].dt.to_period("M").astype(str)

    rows = []

    for year_month, group in df.groupby("year_month"):
        profits = group["profit"]

        trades = len(group)
        wins = int((profits > 0).sum())
        losses = int((profits < 0).sum())
        win_rate = wins / trades * 100 if trades else 0.0

        net_profit = profits.sum()
        gross_profit = profits[profits > 0].sum()
        gross_loss = profits[profits < 0].sum()
        profit_factor = calc_profit_factor(profits)

        rows.append(
            {
                "year_month": year_month,
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "net_profit": round(net_profit, 5),
                "gross_profit": round(gross_profit, 5),
                "gross_loss": round(gross_loss, 5),
                "profit_factor": round(profit_factor, 3),
            }
        )

    return pd.DataFrame(rows).sort_values("year_month")


def calculate_stability_metrics(trade_log: pd.DataFrame) -> dict:
    yearly_df = build_yearly_analysis(trade_log)
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


def calculate_advanced_metrics(trade_log: pd.DataFrame) -> dict:
    if trade_log.empty:
        return {
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "cagr": 0.0,
            "calmar_ratio": 0.0,
        }

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

    if args.strategy_config:
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
        if args.optimizer == "grid":
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
        if args.optimizer == "genetic":
            print(f"検証パターン数: {total_tasks} x {args.generations}世代")
        else:
            print(f"検証パターン数: {total_tasks}")
        print(f"並列数: {workers}")

        def run_batch(executor: ProcessPoolExecutor, param_dicts: list[dict], id_offset: int) -> list[dict]:
            tasks = list(enumerate(param_dicts, start=id_offset))
            futures = [executor.submit(run_one_backtest, task) for task in tasks]

            batch_results = []
            for completed, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                batch_results.append(result)

                if completed % 10 == 0 or completed == len(tasks):
                    elapsed = time.time() - start_time
                    print(f"{completed}/{len(tasks)} 完了 経過 {format_seconds(elapsed)}")

            return batch_results

        results = []

        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=init_worker,
            initargs=(df,),
        ) as executor:
            if args.optimizer in ("grid", "random"):
                results = run_batch(executor, parameter_list, id_offset=1)
            else:
                search = GeneticSearch(param_space, population_size=args.population)
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

    ranking_paths = export_rankings(result_df)

    ranking_total = pd.read_csv(ranking_paths["total"])

    best_row = ranking_total.iloc[0].to_dict()
    best_params = reconstruct_params_from_row(best_row)

    _, best_trade_log = run_backtest(
        df=df,
        params=best_params,
        return_trades=True,
    )

    trade_log_path = OUTPUT_DIR / "trade_log.csv"
    best_trade_log.to_csv(trade_log_path, index=False, encoding="utf-8-sig")

    yearly_df = export_yearly_analysis(best_trade_log)
    monthly_df = export_monthly_analysis(best_trade_log)
    stability_df = export_stability_analysis(yearly_df, monthly_df)

    equity_df = export_equity_curve(
        trade_log=best_trade_log,
        output_dir=OUTPUT_DIR,
    )

    monte_carlo_results, monte_carlo_summary = export_monte_carlo(
        trade_log=best_trade_log,
        output_dir=OUTPUT_DIR,
    )

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