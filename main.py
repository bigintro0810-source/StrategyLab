from pathlib import Path
import argparse
import itertools
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from engine.backtest_engine import run_backtest, compute_is_intraday
from engine.equity_curve import export_equity_curve
from engine.monte_carlo import export_monte_carlo, print_monte_carlo_summary
from engine.html_report import export_html_report
from engine.strategy_registry import save_strategy


AVAILABLE_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

DATA_DIRS = ["data/raw", "data", "input", "."]

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
        "--save-as",
        default=None,
        help="指定した名前でこの実行のベスト戦略をsaved_strategies/に保存する",
    )

    return parser.parse_args()


def build_data_candidates(timeframe: str) -> list[str]:
    filenames = [
        f"USDJPY_2003_2026_{timeframe}.csv",
        f"USDJPY_2003_2026_{timeframe}_TV_NY.csv",
    ]

    return [str(Path(d) / name) for d in DATA_DIRS for name in filenames]


def find_data_file(timeframe: str = "15m") -> Path:
    for file_path in build_data_candidates(timeframe):
        path = Path(file_path)
        if path.exists():
            return path

    raise FileNotFoundError(
        f"USDJPY_2003_2026_{timeframe}.csv が見つかりません。data/raw に置いてください。"
    )


def load_price_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    rename_map = {}

    for col in df.columns:
        name = col.lower().strip()

        if name in ["datetime", "time", "date", "timestamp", "gmt time"]:
            rename_map[col] = "datetime"
        elif name in ["open", "o"]:
            rename_map[col] = "open"
        elif name in ["high", "h"]:
            rename_map[col] = "high"
        elif name in ["low", "l"]:
            rename_map[col] = "low"
        elif name in ["close", "c"]:
            rename_map[col] = "close"

    df = df.rename(columns=rename_map)

    required_cols = ["datetime", "open", "high", "low", "close"]
    missing = [col for col in required_cols if col not in df.columns]

    if missing:
        raise ValueError(f"必要な列がありません: {missing}")

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required_cols)
    df = df.sort_values("datetime").reset_index(drop=True)

    return df


def build_parameter_grid(mode: str) -> list[dict]:
    if mode == "dev":
        grid = {
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
        }
    else:
        grid = {
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
        }

    keys = list(grid.keys())
    combos = itertools.product(*[grid[key] for key in keys])

    return [dict(zip(keys, combo)) for combo in combos]


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

    result["param_id"] = param_id
    result["yearly_stability_score"] = stability["yearly_stability_score"]
    result["monthly_stability_score"] = stability["monthly_stability_score"]
    result["overall_stability_score"] = stability["overall_stability_score"]
    result["stability_rating"] = stability["rating"]

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


def build_best_params(best_row: dict) -> dict:
    return {
        "ema_length": int(best_row["ema_length"]),
        "min_body_pips": float(best_row["min_body_pips"]),
        "max_body_pips": float(best_row["max_body_pips"]),
        "max_wick_pips": float(best_row["max_wick_pips"]),
        "lookahead_bars": int(best_row["lookahead_bars"]),
        "breakout_bars": int(best_row["breakout_bars"]),
        "ema_distance_pips": float(best_row["ema_distance_pips"]),
        "rsi_min": float(best_row["rsi_min"]),
        "rr": float(best_row["rr"]),
        "session_start": int(best_row["session_start"]),
        "session_end": int(best_row["session_end"]),
        "use_weekend_exit": bool(best_row["use_weekend_exit"]),
        "weekend_exit_hour": int(best_row["weekend_exit_hour"]),
        "use_daily_exit": bool(best_row["use_daily_exit"]),
        "daily_exit_hour": int(best_row["daily_exit_hour"]),
    }


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

    if args.timeframe != "15m":
        OUTPUT_DIR = Path("output") / args.timeframe

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data_path = find_data_file(args.timeframe)
    print(f"モード: {args.mode}")
    print(f"時間足: {args.timeframe}")
    print(f"読み込み: {data_path}")

    df = load_price_data(data_path)

    print(f"データ数: {len(df):,}")
    print(f"期間: {df['datetime'].min()} ～ {df['datetime'].max()}")

    parameter_list = build_parameter_grid(args.mode)
    tasks = list(enumerate(parameter_list, start=1))

    total_tasks = len(tasks)

    workers = min(MAX_WORKERS, os.cpu_count() or 1, total_tasks)

    print(f"検証パターン数: {total_tasks}")
    print(f"並列数: {workers}")

    start_time = time.time()
    results = []

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=init_worker,
        initargs=(df,),
    ) as executor:
        futures = [executor.submit(run_one_backtest, task) for task in tasks]

        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)

            if completed % 10 == 0 or completed == total_tasks:
                elapsed = time.time() - start_time
                avg_per_task = elapsed / completed
                remaining = avg_per_task * (total_tasks - completed)

                print(
                    f"{completed}/{total_tasks} 完了 "
                    f"経過 {format_seconds(elapsed)} "
                    f"残り予想 {format_seconds(remaining)}"
                )

    result_df = pd.DataFrame(results)

    ranking_paths = export_rankings(result_df)

    ranking_total = pd.read_csv(ranking_paths["total"])

    best_row = ranking_total.iloc[0].to_dict()
    best_params = build_best_params(best_row)

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

    if args.save_as:
        saved_entry = save_strategy(
            output_dir=OUTPUT_DIR,
            mode=args.mode,
            timeframe=args.timeframe,
            best_row=best_row,
            params=best_params,
            name=args.save_as,
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
    print("")
    print("総合ランキング 上位20件")
    print(ranking_total.head(20).to_string(index=False))

    print_analysis_summary(yearly_df, monthly_df, stability_df)
    print_monte_carlo_summary(monte_carlo_results, monte_carlo_summary)


if __name__ == "__main__":
    main()