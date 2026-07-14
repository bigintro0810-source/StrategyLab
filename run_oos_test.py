"""Out-of-Sample test for one already-computed ranking row: splits the full
price history at a single cutoff point (by row count, so both halves get a
predictable share of the data regardless of gaps/holidays) into an
in-sample and an out-of-sample period, then runs the SAME already-selected
strategy (no re-optimization) on each half separately.

Unlike walk_forward.py (many rolling train/test windows, re-optimizing on
each train window), this is a single split of an already-picked strategy -
the simplest possible "does this still work on data it wasn't picked
using" check. A strategy whose out-of-sample metrics collapse relative to
its in-sample ones is a red flag for overfitting to the specific period it
was found on.

Invoked by api_server.py's POST /api/tools/oos, via the same subprocess
pattern every other tool script uses (see api_server.py's module docstring
for why main.py's own optimizer can't run in-process on Windows - this
script doesn't use ProcessPoolExecutor itself, but stays on the same
subprocess pattern rather than introducing a second, different code path).
"""

import argparse

import pandas as pd

from engine.backtest_engine import compute_is_intraday, run_backtest
from engine.params import reconstruct_params_from_row
from main import SUPPORTED_SYMBOLS, find_data_file, load_price_data, resolve_output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Out-of-Sampleテスト(単純な学習/検証1回分割)")

    parser.add_argument("--symbol", choices=SUPPORTED_SYMBOLS, default="USDJPY")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--rank", type=int, default=1, help="ranking_total.csv内のrank列の値 (デフォルト: 1)")
    parser.add_argument(
        "--split-ratio",
        type=float,
        default=0.7,
        help="全期間のうち学習期間(In-Sample)に充てる割合 (デフォルト: 0.7=先頭70%%)",
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


def main() -> None:
    args = parse_args()

    if not 0.1 <= args.split_ratio <= 0.9:
        raise ValueError("--split-ratioは0.1〜0.9の範囲で指定してください。")

    output_dir = resolve_output_dir(args.symbol, args.timeframe)
    row = load_ranking_row(output_dir, args.rank)
    params = reconstruct_params_from_row(row)

    data_path = find_data_file(args.timeframe, args.symbol)
    df = load_price_data(data_path)
    is_intraday = compute_is_intraday(df["datetime"])

    split_index = int(len(df) * args.split_ratio)
    in_sample = df.iloc[:split_index].reset_index(drop=True)
    out_of_sample = df.iloc[split_index:].reset_index(drop=True)

    print(f"通貨ペア: {args.symbol}")
    print(f"時間足: {args.timeframe}")
    print(f"対象rank: {args.rank}")
    print(f"分割比率: {args.split_ratio}")
    print(f"In-Sample:     {in_sample['datetime'].min()} 〜 {in_sample['datetime'].max()} ({len(in_sample):,}本)")
    print(f"Out-of-Sample: {out_of_sample['datetime'].min()} 〜 {out_of_sample['datetime'].max()} ({len(out_of_sample):,}本)")
    print()

    in_sample_result = run_backtest(df=in_sample, params=params, return_trades=False, is_intraday=is_intraday)
    oos_result = run_backtest(df=out_of_sample, params=params, return_trades=False, is_intraday=is_intraday)

    metric_keys = ["trades", "win_rate", "net_profit", "profit_factor", "max_dd", "expected_value", "recovery_factor"]

    rows = [
        {
            "period": "in_sample",
            "start": str(in_sample["datetime"].min()),
            "end": str(in_sample["datetime"].max()),
            **{key: in_sample_result[key] for key in metric_keys},
        },
        {
            "period": "out_of_sample",
            "start": str(out_of_sample["datetime"].min()),
            "end": str(out_of_sample["datetime"].max()),
            **{key: oos_result[key] for key in metric_keys},
        },
    ]

    result_df = pd.DataFrame(rows)
    output_path = output_dir / "oos_results.csv"
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print("========== Out-of-Sample テスト結果 ==========")
    print()
    print(result_df.to_string(index=False))
    print()
    print(f"出力: {output_path}")


if __name__ == "__main__":
    main()
