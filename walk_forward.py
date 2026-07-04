from pathlib import Path
import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from engine.backtest_engine import run_backtest, compute_is_intraday
from engine.params import reconstruct_params_from_row
from main import (
    AVAILABLE_TIMEFRAMES,
    SUPPORTED_SYMBOLS,
    find_data_file,
    load_price_data,
    build_parameter_grid,
    format_seconds,
    resolve_output_dir,
)


TRAIN_YEARS = 5
TEST_YEARS = 1
START_YEAR = 2004
END_YEAR = 2026
TOP_N = 3
MAX_WORKERS = 8

_WORKER_DF = None
_WORKER_IS_INTRADAY = True


def build_windows() -> list[dict]:
    windows = []
    train_start = START_YEAR

    while True:
        train_end = train_start + TRAIN_YEARS - 1
        test_start = train_end + 1
        test_end = test_start + TEST_YEARS - 1

        if test_end > END_YEAR:
            break

        windows.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )

        train_start += TEST_YEARS

    return windows


def filter_by_year(df: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    years = df["datetime"].dt.year
    return df[(years >= start_year) & (years <= end_year)].reset_index(drop=True)


def init_worker(df: pd.DataFrame) -> None:
    global _WORKER_DF, _WORKER_IS_INTRADAY
    _WORKER_DF = df
    _WORKER_IS_INTRADAY = compute_is_intraday(df["datetime"])


def run_one(task: tuple[int, dict]) -> dict:
    global _WORKER_DF, _WORKER_IS_INTRADAY

    if _WORKER_DF is None:
        raise RuntimeError("Worker data is not initialized.")

    param_id, params = task

    result = run_backtest(
        df=_WORKER_DF,
        params=params,
        return_trades=False,
        is_intraday=_WORKER_IS_INTRADAY,
    )

    result["param_id"] = param_id
    return result


def rank_results(result_df: pd.DataFrame) -> pd.DataFrame:
    return result_df.sort_values(
        by=["profit_factor", "net_profit", "max_dd", "trades"],
        ascending=[False, False, True, False],
    ).reset_index(drop=True)


def run_optimization(df: pd.DataFrame, params_list: list[dict]) -> pd.DataFrame:
    tasks = list(enumerate(params_list, start=1))
    workers = min(MAX_WORKERS, os.cpu_count() or 1, len(tasks))

    results = []

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=init_worker,
        initargs=(df,),
    ) as executor:
        futures = [executor.submit(run_one, task) for task in tasks]

        for future in as_completed(futures):
            results.append(future.result())

    return pd.DataFrame(results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy Lab walk forward")

    parser.add_argument(
        "--symbol",
        choices=SUPPORTED_SYMBOLS,
        default="USDJPY",
        help="通貨ペア (デフォルト: USDJPY)",
    )

    parser.add_argument(
        "--timeframe",
        choices=AVAILABLE_TIMEFRAMES,
        default="15m",
        help="使用する時間足 (デフォルト: 15m)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_dir = resolve_output_dir(args.symbol, args.timeframe)
    output_csv = output_dir / "walk_forward_results.csv"

    output_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    data_path = find_data_file(args.timeframe, args.symbol)
    print(f"通貨ペア: {args.symbol}")
    print(f"時間足: {args.timeframe}")
    print(f"読み込み: {data_path}")

    df = load_price_data(data_path)
    params_list = build_parameter_grid("full", args.symbol)
    windows = build_windows()

    print(f"データ数: {len(df):,}")
    print(f"期間: {df['datetime'].min()} ～ {df['datetime'].max()}")
    print(f"パラメータ数: {len(params_list)}")
    print(f"Walk Forward ウィンドウ数: {len(windows)}")
    print("")

    output_rows = []

    for window_index, window in enumerate(windows, start=1):
        print(
            f"[{window_index}/{len(windows)}] "
            f"Train {window['train_start']}-{window['train_end']} "
            f"-> Test {window['test_start']}-{window['test_end']}"
        )

        train_df = filter_by_year(
            df,
            window["train_start"],
            window["train_end"],
        )

        test_df = filter_by_year(
            df,
            window["test_start"],
            window["test_end"],
        )

        train_results = run_optimization(train_df, params_list)
        train_ranked = rank_results(train_results).head(TOP_N)

        for rank, (_, train_row) in enumerate(train_ranked.iterrows(), start=1):
            params = reconstruct_params_from_row(train_row)

            test_result = run_backtest(
                df=test_df,
                params=params,
                return_trades=False,
            )

            output_rows.append(
                {
                    "window": window_index,
                    "rank": rank,
                    "train_start": window["train_start"],
                    "train_end": window["train_end"],
                    "test_start": window["test_start"],
                    "test_end": window["test_end"],
                    "param_id": int(train_row["param_id"]),
                    "ema_length": params["ema_length"],
                    "min_body_pips": params["min_body_pips"],
                    "ema_distance_pips": params["ema_distance_pips"],
                    "rsi_min": params["rsi_min"],
                    "rr": params["rr"],
                    "train_trades": int(train_row["trades"]),
                    "train_win_rate": float(train_row["win_rate"]),
                    "train_net_profit": float(train_row["net_profit"]),
                    "train_profit_factor": float(train_row["profit_factor"]),
                    "train_max_dd": float(train_row["max_dd"]),
                    "test_trades": int(test_result["trades"]),
                    "test_win_rate": float(test_result["win_rate"]),
                    "test_net_profit": float(test_result["net_profit"]),
                    "test_profit_factor": float(test_result["profit_factor"]),
                    "test_max_dd": float(test_result["max_dd"]),
                    "test_expected_value": float(test_result["expected_value"]),
                }
            )

        elapsed = time.time() - start_time
        print(f"  完了 経過 {format_seconds(elapsed)}")
        print("")

    result_df = pd.DataFrame(output_rows)
    result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    elapsed_total = time.time() - start_time

    print("========== Walk Forward 完了 ==========")
    print(f"総実行時間: {format_seconds(elapsed_total)}")
    print(f"出力: {output_csv}")
    print("")
    print(result_df.to_string(index=False))


if __name__ == "__main__":
    main()