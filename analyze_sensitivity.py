"""Parameter sensitivity analysis for a given strategy (V3.0).

For each tuned parameter, holds every other parameter at the best-known
value and re-runs the backtest across that one parameter's other grid
values. A flat profit_factor across those variants means the strategy
isn't relying on a lucky, narrow parameter choice; a cliff means it might
be overfit to that exact value.

Reads ranking_total.csv from resolve_output_dir(symbol, timeframe) - the
same per-symbol output directory every other script in this project uses
(main.py/walk_forward.py/rerun_ranking_row.py) - so run main.py for that
symbol/timeframe first. --mode controls which parameter grid to vary
across - dev mode has only one value per parameter, so there's nothing to
test; use --mode full (matching whatever mode actually produced
ranking_total.csv).
"""

import argparse
from pathlib import Path

import pandas as pd

from engine.backtest_engine import compute_is_intraday, run_backtest
from engine.params import reconstruct_params_from_row
from engine.strategy_config_loader import load_strategy_config
from main import (
    build_grid_from_space,
    build_parameter_space,
    find_data_file,
    load_price_data,
    resolve_output_dir,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="パラメータ感度分析")

    parser.add_argument(
        "--symbol",
        default="USDJPY",
        help="通貨ペア (main.pyの--symbolと合わせる。デフォルト: USDJPY。data/rawに取り込み済みならどの名前でも可)",
    )

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

    parser.add_argument(
        "--rank",
        type=int,
        default=1,
        help="ranking_total.csv内のどの行(rank)を分析対象にするか (デフォルト: 1=全体ベスト)",
    )
    parser.add_argument(
        "--strategy-config",
        default=None,
        help="strategy_configs/*.json のパスを指定すると、--rankの代わりにこの設定(ライブラリの"
        "保存済みストラテジー等)を分析対象にする(walk_forward.pyの--strategy-configと同じ仕組み)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="結果の出力先を指定すると、通常のresolve_output_dir()の代わりにこちらへ書き出す"
        "(ライブラリのストラテジーごとに結果を分けて永続化するため)",
    )

    return parser.parse_args()


def load_ranking_row(output_dir, rank: int) -> dict:
    ranking_path = output_dir / "ranking_total.csv"

    if not ranking_path.exists():
        raise FileNotFoundError(
            f"{ranking_path} が見つかりません。先に main.py を実行してください。"
        )

    ranking_total = pd.read_csv(ranking_path)
    matches = ranking_total[ranking_total["rank"] == rank]
    if matches.empty:
        raise ValueError(f"rank={rank} がranking_total.csvに見つかりません。")

    return matches.iloc[0].to_dict()


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

    output_dir = Path(args.output_dir) if args.output_dir else resolve_output_dir(args.symbol, args.timeframe)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.strategy_config:
        base_params = build_grid_from_space(load_strategy_config(Path(args.strategy_config)))[0]
        baseline_label = args.strategy_config
    else:
        best_row = load_ranking_row(resolve_output_dir(args.symbol, args.timeframe), args.rank)
        base_params = reconstruct_params_from_row(best_row)
        baseline_label = f"rank={args.rank} (PF={best_row.get('profit_factor')})"
    param_space = build_parameter_space(args.mode, args.symbol)

    data_path = find_data_file(args.timeframe, args.symbol)
    df = load_price_data(data_path)
    is_intraday = compute_is_intraday(df["datetime"])

    print(f"通貨ペア: {args.symbol}")
    print(f"時間足: {args.timeframe}")
    print(f"モード: {args.mode}")
    print(f"対象: {baseline_label}")
    print()

    detail_df = analyze_param_sensitivity(df, base_params, param_space, is_intraday)

    if detail_df.empty:
        print("感度分析の対象となるパラメータがありません(全パラメータが単一値)。")
        return

    summary_df = summarize_sensitivity(detail_df)
    score, rating = rate_sensitivity(summary_df)

    summary_df["sensitivity_score"] = score
    summary_df["sensitivity_rating"] = rating

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
