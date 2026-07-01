from pathlib import Path
import pandas as pd

from engine.backtest_engine import run_backtest


TV_CSV = Path("data/raw/TV_USDJPY_15m.csv")
OUTPUT_DIR = Path("output")


def load_tv_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"TradingView CSVが見つかりません: {path}")

    df = pd.read_csv(path)

    rename = {
        "time": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
    }

    df = df.rename(columns=rename)

    required = ["datetime", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(f"必要な列がありません: {missing}")

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    # TradingViewの +09:00 を外して、Python側と同じ扱いにする
    if getattr(df["datetime"].dt, "tz", None) is not None:
        df["datetime"] = df["datetime"].dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)

    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=required)
    df = df.sort_values("datetime").reset_index(drop=True)

    return df


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_tv_csv(TV_CSV)

    print(f"読み込み: {TV_CSV}")
    print(f"データ数: {len(df):,}")
    print(f"期間: {df['datetime'].min()} ～ {df['datetime'].max()}")

    params = {
        "ema_length": 200,
        "min_body_pips": 20.0,
        "max_body_pips": 0.0,
        "max_wick_pips": 0.0,
        "lookahead_bars": 15,
        "breakout_bars": 30,
        "ema_distance_pips": 50.0,
        "rsi_min": 70.0,
        "rr": 1.2,
        "session_start": 8,
        "session_end": 3,
        "use_weekend_exit": True,
        "weekend_exit_hour": 4,
        "use_daily_exit": False,
        "daily_exit_hour": 4,
    }

    result, trade_log = run_backtest(
        df=df,
        params=params,
        return_trades=True,
    )

    result_df = pd.DataFrame([result])

    result_path = OUTPUT_DIR / "tv_compare_result.csv"
    trade_path = OUTPUT_DIR / "tv_compare_trade_log.csv"

    result_df.to_csv(result_path, index=False, encoding="utf-8-sig")
    trade_log.to_csv(trade_path, index=False, encoding="utf-8-sig")

    print("完了")
    print(f"結果: {result_path}")
    print(f"取引ログ: {trade_path}")
    print(result_df.to_string(index=False))
    print("")
    print("最初の10件")
    print(trade_log.head(10).to_string(index=False))


if __name__ == "__main__":
    main()