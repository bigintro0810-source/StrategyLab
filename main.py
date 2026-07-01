from pathlib import Path
import itertools
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from engine.backtest_engine import prepare_indicator_columns, run_backtest


DATA_CANDIDATES = [
    "data/raw/USDJPY_2003_2026_15m.csv",
    "data/USDJPY_2003_2026_15m.csv",
    "input/USDJPY_2003_2026_15m.csv",
    "USDJPY_2003_2026_15m.csv",
]

OUTPUT_DIR = Path("output")

# 16GBメモリなので、まずは8並列が安全
MAX_WORKERS = 8

_WORKER_DF = None


def find_data_file() -> Path:
    for file_path in DATA_CANDIDATES:
        path = Path(file_path)
        if path.exists():
            return path

    raise FileNotFoundError(
        "USDJPY_2003_2026_15m.csv が見つかりません。data/raw に置いてください。"
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


def build_parameter_grid() -> list[dict]:
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


def get_required_ema_lengths(parameter_list: list[dict]) -> list[int]:
    return sorted({int(params["ema_length"]) for params in parameter_list})


def init_worker(df: pd.DataFrame) -> None:
    global _WORKER_DF
    _WORKER_DF = df


def run_one_backtest(task: tuple[int, dict]) -> dict:
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


def add_rank_column(df: pd.DataFrame) -> pd.DataFrame:
    ranked = df.reset_index(drop=True).copy()
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ranked


def export_rankings(result_df: pd.DataFrame) -> dict[str, Path]:
    rankings = {
        "total": result_df.sort_values(
            by=["profit_factor", "net_profit", "max_dd", "trades"],
            ascending=[False, False, True, False],
        ),
        "pf": result_df.sort_values(
            by=["profit_factor", "net_profit", "max_dd"],
            ascending=[False, False, True],
        ),
        "dd": result_df.sort_values(
            by=["max_dd", "profit_factor", "net_profit"],
            ascending=[True, False, False],
        ),
        "win_rate": result_df.sort_values(
            by=["win_rate", "profit_factor", "net_profit"],
            ascending=[False, False, False],
        ),
        "profit": result_df.sort_values(
            by=["net_profit", "profit_factor", "max_dd"],
            ascending=[False, False, True],
        ),
        "expected_value": result_df.sort_values(
            by=["expected_value", "profit_factor", "net_profit"],
            ascending=[False, False, False],
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


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data_path = find_data_file()
    print(f"読み込み: {data_path}")

    df = load_price_data(data_path)

    print(f"データ数: {len(df):,}")
    print(f"期間: {df['datetime'].min()} ～ {df['datetime'].max()}")

    parameter_list = build_parameter_grid()
    tasks = list(enumerate(parameter_list, start=1))

    total_tasks = len(tasks)
    workers = min(MAX_WORKERS, os.cpu_count() or 1)

    ema_lengths = get_required_ema_lengths(parameter_list)

    print("インジケーター事前計算中...")
    print(f"EMAキャッシュ対象: {ema_lengths}")
    df = prepare_indicator_columns(
        df=df,
        ema_lengths=ema_lengths,
        rsi_length=14,
    )
    print("インジケーター事前計算完了")

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

    elapsed_total = time.time() - start_time

    print("完了")
    print(f"総実行時間: {format_seconds(elapsed_total)}")
    print("ランキング出力:")
    for name, path in ranking_paths.items():
        print(f"  {name}: {path}")

    print(f"取引履歴出力: {trade_log_path}")
    print("")
    print("総合ランキング 上位20件")
    print(ranking_total.head(20).to_string(index=False))


if __name__ == "__main__":
    main()