from pathlib import Path
import itertools

import pandas as pd

from engine.backtest_engine import BacktestConfig, run_backtest


DATA_CANDIDATES = [
    "data/raw/USDJPY_2003_2026_15m.csv",
    "data/USDJPY_2003_2026_15m.csv",
    "input/USDJPY_2003_2026_15m.csv",
    "USDJPY_2003_2026_15m.csv",
]

OUTPUT_DIR = Path("output")


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

    keys = list(grid.keys())
    combos = itertools.product(*[grid[key] for key in keys])

    return [dict(zip(keys, combo)) for combo in combos]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data_path = find_data_file()
    print(f"読み込み: {data_path}")

    df = load_price_data(data_path)

    print(f"データ数: {len(df):,}")
    print(f"期間: {df['datetime'].min()} ～ {df['datetime'].max()}")

    parameter_list = build_parameter_grid()

    print(f"検証パターン数: {len(parameter_list)}")

    results = []
    best_trade_log = pd.DataFrame()

    for index, params in enumerate(parameter_list, start=1):
        result, trade_log = run_backtest(
            df=df,
            params=params,
            return_trades=True,
        )

        result["param_id"] = index
        results.append(result)

        if index == 1:
            best_trade_log = trade_log.copy()

        print(f"{index}/{len(parameter_list)} 完了")

    result_df = pd.DataFrame(results)

    result_df = result_df.sort_values(
        by=["profit_factor", "net_profit", "max_dd", "trades"],
        ascending=[False, False, True, False],
    ).reset_index(drop=True)

    result_df.insert(0, "rank", range(1, len(result_df) + 1))

    ranking_path = OUTPUT_DIR / "ranking_total.csv"
    trade_log_path = OUTPUT_DIR / "trade_log.csv"

    result_df.to_csv(ranking_path, index=False, encoding="utf-8-sig")
    best_trade_log.to_csv(trade_log_path, index=False, encoding="utf-8-sig")

    print("完了")
    print(f"ランキング出力: {ranking_path}")
    print(f"取引履歴出力: {trade_log_path}")
    print(result_df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()