from pathlib import Path

import numpy as np
import pandas as pd


INPUT_CSV = Path("output/trade_log.csv")
OUTPUT_CSV = Path("output/monte_carlo_results.csv")
SUMMARY_CSV = Path("output/monte_carlo_summary.csv")

SIMULATIONS = 1000
RANDOM_SEED = 42


def calc_max_dd(profits: np.ndarray) -> float:
    if len(profits) == 0:
        return 0.0

    equity = profits.cumsum()
    running_max = np.maximum.accumulate(equity)
    drawdown = running_max - equity

    return float(drawdown.max())


def judge_monte_carlo(dd95: float) -> tuple[str, str]:
    if dd95 <= 2.0:
        return "A", "非常に安定しています。"
    if dd95 <= 3.0:
        return "B", "安定しています。"
    if dd95 <= 4.0:
        return "C", "実運用可能ですがDDに注意してください。"
    return "D", "DDが大きく、改善を推奨します。"


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

    dd_values = result_df["max_dd"]

    dd_95 = round(float(dd_values.quantile(0.95)), 5)
    rating, comment = judge_monte_carlo(dd_95)

    summary = {
        "simulations": SIMULATIONS,
        "trades": len(profits),
        "original_total_profit": round(float(profits.sum()), 5),
        "avg_max_dd": round(float(dd_values.mean()), 5),
        "median_max_dd": round(float(dd_values.median()), 5),
        "dd_90": round(float(dd_values.quantile(0.90)), 5),
        "dd_95": dd_95,
        "dd_99": round(float(dd_values.quantile(0.99)), 5),
        "worst_max_dd": round(float(dd_values.max()), 5),
        "best_max_dd": round(float(dd_values.min()), 5),
        "rating": rating,
        "comment": comment,
    }

    summary_df = pd.DataFrame([summary])
    summary_df.to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")

    worst_5 = result_df.sort_values("max_dd", ascending=False).head(5)
    best_5 = result_df.sort_values("max_dd", ascending=True).head(5)

    print()
    print("========== Monte Carlo ==========")
    print()
    print(f"シミュレーション回数: {SIMULATIONS}")
    print(f"元の取引数: {len(profits)}")
    print(f"元の合計利益: {profits.sum():.5f}")
    print()
    print("----- DD統計 -----")
    print(f"平均最大DD: {summary['avg_max_dd']}")
    print(f"中央値DD: {summary['median_max_dd']}")
    print(f"DD90%: {summary['dd_90']}")
    print(f"DD95%: {summary['dd_95']}")
    print(f"DD99%: {summary['dd_99']}")
    print(f"最悪最大DD: {summary['worst_max_dd']}")
    print(f"最良最大DD: {summary['best_max_dd']}")
    print()
    print("----- 評価 -----")
    print(f"Monte Carlo評価: {summary['rating']}")
    print(summary["comment"])
    print()
    print("----- ワースト5 -----")
    print(worst_5.to_string(index=False))
    print()
    print("----- ベスト5 -----")
    print(best_5.to_string(index=False))
    print()
    print(f"CSV保存完了: {OUTPUT_CSV}")
    print(f"サマリー保存完了: {SUMMARY_CSV}")


if __name__ == "__main__":
    main()