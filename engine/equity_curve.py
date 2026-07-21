from pathlib import Path

import pandas as pd


def build_equity_curve(trade_log: pd.DataFrame) -> pd.DataFrame:
    if trade_log.empty:
        return pd.DataFrame()

    df = trade_log.copy()

    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.sort_values("exit_time").reset_index(drop=True)

    df["trade_number"] = range(1, len(df) + 1)
    df["equity"] = df["profit"].cumsum()
    df["equity_high"] = df["equity"].cummax()
    df["drawdown"] = df["equity_high"] - df["equity"]

    return df[
        [
            "trade_number",
            "entry_time",
            "exit_time",
            "entry_price",
            "exit_price",
            "profit",
            "equity",
            "equity_high",
            "drawdown",
            "exit_reason",
            "mae",
            "mfe",
        ]
    ]


def export_equity_curve(
    trade_log: pd.DataFrame,
    output_dir: Path,
) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)

    result_df = build_equity_curve(trade_log)

    output_path = output_dir / "equity_curve.csv"
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    return result_df


def print_equity_curve_summary(equity_df: pd.DataFrame) -> None:
    print()
    print("========== Equity Curve ==========")
    print()

    if equity_df.empty:
        print("Equity Curveが空です。")
        return

    total_profit = float(equity_df["equity"].iloc[-1])
    max_dd = float(equity_df["drawdown"].max())
    max_equity = float(equity_df["equity"].max())
    min_equity = float(equity_df["equity"].min())

    print(f"取引数: {len(equity_df)}")
    print(f"最終利益: {total_profit:.5f}")
    print(f"最大利益地点: {max_equity:.5f}")
    print(f"最低利益地点: {min_equity:.5f}")
    print(f"最大DD: {max_dd:.5f}")
    print()
    print("最後の20取引")
    print(equity_df.tail(20).to_string(index=False))