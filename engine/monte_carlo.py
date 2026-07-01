from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_SIMULATIONS = 1000
DEFAULT_RANDOM_SEED = 42


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


def run_monte_carlo(
    trade_log: pd.DataFrame,
    simulations: int = DEFAULT_SIMULATIONS,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trade_log.empty:
        empty_results = pd.DataFrame()
        empty_summary = pd.DataFrame(
            [
                {
                    "simulations": simulations,
                    "trades": 0,
                    "original_total_profit": 0.0,
                    "avg_max_dd": 0.0,
                    "median_max_dd": 0.0,
                    "dd_90": 0.0,
                    "dd_95": 0.0,
                    "dd_99": 0.0,
                    "worst_max_dd": 0.0,
                    "best_max_dd": 0.0,
                    "rating": "D",
                    "comment": "取引履歴が空です。",
                }
            ]
        )
        return empty_results, empty_summary

    profits = trade_log["profit"].to_numpy(dtype=float)
    rng = np.random.default_rng(random_seed)

    rows = []

    for i in range(1, simulations + 1):
        shuffled = rng.permutation(profits)

        rows.append(
            {
                "simulation": i,
                "final_profit": round(float(shuffled.sum()), 5),
                "max_dd": round(calc_max_dd(shuffled), 5),
            }
        )

    result_df = pd.DataFrame(rows)
    dd_values = result_df["max_dd"]

    dd_95 = round(float(dd_values.quantile(0.95)), 5)
    rating, comment = judge_monte_carlo(dd_95)

    summary = {
        "simulations": simulations,
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

    return result_df, summary_df


def export_monte_carlo(
    trade_log: pd.DataFrame,
    output_dir: Path,
    simulations: int = DEFAULT_SIMULATIONS,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    result_df, summary_df = run_monte_carlo(
        trade_log=trade_log,
        simulations=simulations,
        random_seed=random_seed,
    )

    result_path = output_dir / "monte_carlo_results.csv"
    summary_path = output_dir / "monte_carlo_summary.csv"

    result_df.to_csv(result_path, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    return result_df, summary_df


def print_monte_carlo_summary(
    result_df: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> None:
    print()
    print("========== Monte Carlo ==========")
    print()

    if summary_df.empty:
        print("Monte Carlo結果が空です。")
        return

    summary = summary_df.iloc[0]

    print(f"シミュレーション回数: {int(summary['simulations'])}")
    print(f"元の取引数: {int(summary['trades'])}")
    print(f"元の合計利益: {summary['original_total_profit']:.5f}")
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

    if not result_df.empty:
        worst_5 = result_df.sort_values("max_dd", ascending=False).head(5)
        best_5 = result_df.sort_values("max_dd", ascending=True).head(5)

        print()
        print("----- ワースト5 -----")
        print(worst_5.to_string(index=False))
        print()
        print("----- ベスト5 -----")
        print(best_5.to_string(index=False))