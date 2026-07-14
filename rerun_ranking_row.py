"""Re-runs ONE specific row of an already-computed ranking_total.csv,
producing the same per-strategy analysis artifacts (trade_log/equity_curve/
yearly/monthly/stability/monte_carlo) that main.py's own end-of-run "best
row" export already produces for rank #1 - lets the dashboard's ranking
table show any row's own results, not just the top-ranked one.

Invoked by api_server.py's POST /api/backtests/{job_id}/rows/{rank}, via
the same subprocess pattern every other backtest already uses (see
api_server.py's module docstring for why main.py's own optimizer loop can't
run in-process on Windows - this script doesn't use ProcessPoolExecutor
itself, but stays on the same subprocess pattern rather than introducing a
second, different code path).

Overwrites the SAME output_dir the original run used (trade_log.csv,
equity_curve.csv, etc) rather than a separate per-request directory - this
is a single-user local app (see api_server.py's JOBS in-memory store), so
there is no concurrent-multi-user scenario to isolate against, and reusing
the existing dir means the frontend's already-built /results endpoint needs
no changes to serve a re-run row's data.
"""

import argparse
import json

import pandas as pd

from engine.data_loader import find_data_file, load_price_data
from engine.params import reconstruct_params_from_row
from engine.strategy_registry import save_strategy
from main import (
    AVAILABLE_TIMEFRAMES,
    SUPPORTED_SYMBOLS,
    export_single_strategy_analysis,
    resolve_output_dir,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ranking_total.csvの特定行を再実行する")

    parser.add_argument("--symbol", choices=SUPPORTED_SYMBOLS, default="USDJPY")
    parser.add_argument("--timeframe", choices=AVAILABLE_TIMEFRAMES, default="15m")
    parser.add_argument("--rank", type=int, required=True, help="ranking_total.csv内のrank列の値")
    parser.add_argument(
        "--simulations",
        type=int,
        default=None,
        help="モンテカルロのシミュレーション回数を上書き(未指定ならengine/monte_carlo.pyの既定値)",
    )
    parser.add_argument("--mode", default="dev", help="保存エントリに記録するmode(--save-asと併用)")
    parser.add_argument("--save-as", default=None, help="指定するとこの行をライブラリ(saved_strategies)に保存する")
    parser.add_argument("--favorite", action="store_true", help="保存時にお気に入りとして登録する")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_dir = resolve_output_dir(args.symbol, args.timeframe)
    ranking_path = output_dir / "ranking_total.csv"
    if not ranking_path.exists():
        raise FileNotFoundError(
            f"{ranking_path} が見つかりません。先に通常のバックテストを実行してください。"
        )

    ranking_total = pd.read_csv(ranking_path)
    matches = ranking_total[ranking_total["rank"] == args.rank]
    if matches.empty:
        raise ValueError(f"rank={args.rank} がranking_total.csvに見つかりません。")

    row = matches.iloc[0].to_dict()
    params = reconstruct_params_from_row(row)

    data_path = find_data_file(args.timeframe, args.symbol)
    df = load_price_data(data_path)

    export_single_strategy_analysis(df, params, output_dir, mc_simulations=args.simulations)

    print(f"rank={args.rank} の再実行が完了しました。")

    if args.save_as:
        saved_entry = save_strategy(
            output_dir=output_dir,
            mode=args.mode,
            timeframe=args.timeframe,
            best_row=row,
            params=params,
            name=args.save_as,
            favorite=args.favorite,
            symbol=args.symbol,
        )
        print(f"戦略を保存しました: {saved_entry['id']} ({saved_entry['name']})")
        print(f"SAVE_RESULT_JSON:{json.dumps(saved_entry, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
