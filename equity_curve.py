from pathlib import Path

import pandas as pd


INPUT_CSV = Path("output/trade_log.csv")
OUTPUT_CSV = Path("output/equity_curve.csv")


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            "output/trade_log.csv が見つかりません。先に python main.py --mode full を実行してください。"
        )

    df = pd.read_csv(INPUT_CSV)

    if df.empty:
        print("取引履歴が空です。")
        return

    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.sort_values("exit_time").reset_index(drop=True)

    df["trade_number"] = range(1, len(df) + 1)
    df["equity"] = df["profit"].cumsum()
    df["equity_high"] = df["equity"].cummax()
    df["drawdown"] = df["equity_high"] - df["equity"]

    output_df = df[
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
        ]
    ]

    output_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    total_profit = float(df["equity"].iloc[-1])
    max_dd = float(df["drawdown"].max())
    max_equity = float(df["equity"].max())
    min_equity = float(df["equity"].min())

    print()
    print("========== Equity Curve ==========")
    print()
    print(f"取引数: {len(df)}")
    print(f"最終利益: {total_profit:.5f}")
    print(f"最大利益地点: {max_equity:.5f}")
    print(f"最低利益地点: {min_equity:.5f}")
    print(f"最大DD: {max_dd:.5f}")
    print()
    print("最後の20取引")
    print(output_df.tail(20).to_string(index=False))
    print()
    print(f"CSV保存完了: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()