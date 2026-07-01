from pathlib import Path

import numpy as np
import pandas as pd


INPUT_CSV = Path("output/trade_log.csv")
OUTPUT_CSV = Path("output/monte_carlo_results.csv")

SIMULATIONS = 1000
RANDOM_SEED = 42


def calc_max_dd(profits: np.ndarray) -> float:
    if len(profits) == 0:
        return 0.0

    equity = profits.cumsum()
    running_max = np.maximum.accumulate(equity)
    drawdown = running_max - equity

    return float(drawdown.max())


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            "output/trade_log.csv が見つかりません。先に python main.py --mode full を実行してください。"
        )

    trade_df = pd.read_csv(INPUT_CSV)

    if trade_df.empty:
        print("取引履歴が空です。")
        return

    profits = trade_df["profit"].to_numpy(dtype=float)

    rng = np.random.default_rng(RANDOM_SEED)

    rows = []

    for i in range(1, SIMULATIONS + 1):
        shuffled = rng.permutation(profits)

        final_profit = float(shuffled.sum())
        max_dd = calc_max_dd(shuffled)

        rows.append(
            {
                "simulation": i,
                "final_profit": round(final_profit, 5),
                "max_dd": round(max_dd, 5),
            }
        )

    result_df = pd.DataFrame(rows)
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print()
    print("========== Monte Carlo ==========")
    print()
    print(f"シミュレーション回数: {SIMULATIONS}")
    print(f"元の取引数: {len(profits)}")
    print(f"元の合計利益: {profits.sum():.5f}")
    print()
    print(f"平均最終利益: {result_df['final_profit'].mean():.5f}")
    print(f"最低最終利益: {result_df['final_profit'].min():.5f}")
    print(f"最高最終利益: {result_df['final_profit'].max():.5f}")
    print()
    print(f"平均最大DD: {result_df['max_dd'].mean():.5f}")
    print(f"最悪最大DD: {result_df['max_dd'].max():.5f}")
    print(f"最良最大DD: {result_df['max_dd'].min():.5f}")
    print()
    print(f"CSV保存完了: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()