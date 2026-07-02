"""Parameter sensitivity analysis for the current best strategy (V3.0).

For each tuned parameter, holds every other parameter at the best-known
value and re-runs the backtest across that one parameter's other grid
values. A flat profit_factor across those variants means the strategy
isn't relying on a lucky, narrow parameter choice; a cliff means it might
be overfit to that exact value.

Reads output/ranking_total.csv (produced by main.py), so run main.py
first. --mode controls which parameter grid to vary across - dev mode
has only one value per parameter, so there's nothing to test; use
--mode full (matching whatever mode actually produced ranking_total.csv).
"""

import argparse
from pathlib import Path

import pandas as pd

from engine.backtest_engine import compute_is_intraday, run_backtest
from main import build_best_params, build_parameter_space, find_data_file, load_price_data

OUTPUT_DIR = Path("output")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="パラメータ感度分析")

    parser.add_argument(
        "--mode",
        choices=["dev", "full"],
        default="full",
        help="ranking_total.csvを作った際に使ったモード (デフォルト: full)",
    )

    parser.add_argument(
        "--timeframe",
        default="15m",
        help="使用する時間足 (main.pyの--timeframeと合わせる)",
    )

    return parser.parse_args()


def load_best_row(output_dir: Path) -> dict:
    ranking_path = output_dir / "ranking_total.csv"

    if not ranking_path.exists():
        raise FileNotFoundError(
            f"{ranking_path} が見つかりません。先に main.py を実行してください。"
        )

    return pd.read_csv(ranking_path).iloc[0].to_dict()


def analyze_param_sensitivity(
    df: pd.DataFrame,
    base_params: dict,
    param_space: dict[str, list],
    is_intraday: bool,
) -> pd.DataFrame:
    rows = []

    for key, values in param_space.items():
        if len(values) <= 1:
            continue

        for value in values:
            variant_params = dict(base_params)
            variant_params[key] = value

            result = run_backtest(
                df=df,
                params=variant_params,
                return_trades=False,
                is_intraday=is_intraday,
            )

            rows.append(
                {
                    "param": key,
                    "value": value,
                    "is_baseline": value == base_params[key],
                    "profit_factor": result["profit_factor"],
                    "net_profit": result["net_profit"],
                    "max_dd": result["max_dd"],
                    "trades": result["trades"],
                }
            )

    return pd.DataFrame(rows)


def summarize_sensitivity(detail_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for param, group in detail_df.groupby("param"):
        pf_values = group["profit_factor"]
        pf_max = float(pf_values.max())
        pf_min = float(pf_values.min())

        flatness_ratio = (pf_min / pf_max) if pf_max > 0 else 0.0

        rows.append(
            {
                "param": param,
                "variants_tested": len(group),
                "pf_min": pf_min,
                "pf_max": pf_max,
                "pf_range": round(pf_max - pf_min, 3),
                "flatness_ratio": round(flatness_ratio, 3),
            }
        )

    summary_df = pd.DataFrame(rows).sort_values("flatness_ratio")

    return summary_df


def rate_sensitivity(summary_df: pd.DataFrame) -> tuple[float, str]:
    if summary_df.empty:
        return 0.0, "D"

    score = round(float(summary_df["flatness_ratio"].mean()) * 100, 2)

    if score >= 80:
        rating = "A"
    elif score >= 65:
        rating = "B"
    elif score >= 50:
        rating = "C"
    else:
        rating = "D"

    return score, rating


def main() -> None:
    args = parse_args()

    output_dir = OUTPUT_DIR if args.timeframe == "15m" else OUTPUT_DIR / args.timeframe

    best_row = load_best_row(output_dir)
    base_params = build_best_params(best_row)
    param_space = build_parameter_space(args.mode)

    data_path = find_data_file(args.timeframe)
    df = load_price_data(data_path)
    is_intraday = compute_is_intraday(df["datetime"])

    print(f"時間足: {args.timeframe}")
    print(f"モード: {args.mode}")
    print(f"ベースラインPF: {best_row.get('profit_factor')}")
    print()

    detail_df = analyze_param_sensitivity(df, base_params, param_space, is_intraday)

    if detail_df.empty:
        print("感度分析の対象となるパラメータがありません(全パラメータが単一値)。")
        return

    summary_df = summarize_sensitivity(detail_df)
    score, rating = rate_sensitivity(summary_df)

    detail_path = output_dir / "sensitivity_detail.csv"
    summary_path = output_dir / "sensitivity_summary.csv"

    detail_df.to_csv(detail_path, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print("========== パラメータ感度分析 ==========")
    print()
    print(summary_df.to_string(index=False))
    print()
    print(f"パラメータ感度スコア: {score} ({rating})")
    print("(スコアが低い/Dに近いほど、特定パラメータの微妙な選択に依存している=過剰最適化の疑いあり)")
    print()
    print(f"詳細出力: {detail_path}")
    print(f"サマリー出力: {summary_path}")


if __name__ == "__main__":
    main()
