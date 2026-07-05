"""V5.0 Pine Script自動生成 - CLI entry point.

Converts one already-backtested strategy (a row from ranking_total.csv, or
a saved strategy from saved_strategies/registry.json) into a TradingView
Pine Script v5 file. See engine/pine_generator.py's module docstring for
exactly what is and isn't an exact translation of the Python backtest.

使い方:
    保存済み戦略から:
        python generate_pinescript.py --strategy-id <id>

    ranking_total.csvの行から(mainで--mode fullなどを実行した後):
        python generate_pinescript.py --ranking-csv output/ranking_total.csv --rank 1 --symbol USDJPY --timeframe 15m
"""

import argparse
from pathlib import Path

import pandas as pd

from engine.params import reconstruct_params_from_row
from engine.pine_generator import generate_pine_script
from engine.strategy_registry import get_strategy
from main import resolve_output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pine Script自動生成")

    parser.add_argument(
        "--strategy-id",
        default=None,
        help="saved_strategies/registry.json に保存済みの戦略ID",
    )

    parser.add_argument(
        "--ranking-csv",
        default=None,
        help="ranking_total.csv等のパス(--strategy-id未指定時に使用)",
    )

    parser.add_argument(
        "--rank",
        type=int,
        default=1,
        help="--ranking-csv使用時、何位の行を使うか(1始まり、デフォルト1位)",
    )

    parser.add_argument(
        "--symbol",
        default="USDJPY",
        help="--ranking-csv使用時の通貨ペア表記(スクリプトのコメントに使うのみ、デフォルト: USDJPY)",
    )

    parser.add_argument(
        "--timeframe",
        default="15m",
        help="--ranking-csv使用時の時間足表記(スクリプトのコメントに使うのみ、デフォルト: 15m)",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="出力する.pineファイルのパス(未指定時は output/<symbol>/<timeframe>/strategy.pine)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.strategy_id:
        entry = get_strategy(args.strategy_id)
        params = entry["params"]
        symbol = entry.get("symbol", "USDJPY")
        timeframe = entry.get("timeframe", "15m")
        title = f"StrategyLab {entry['name']}"
    elif args.ranking_csv:
        df = pd.read_csv(args.ranking_csv)

        if args.rank < 1 or args.rank > len(df):
            raise SystemExit(f"--rank は1から{len(df)}の範囲で指定してください")

        row = df.iloc[args.rank - 1].to_dict()
        params = reconstruct_params_from_row(row)
        symbol = args.symbol
        timeframe = args.timeframe
        title = None
    else:
        raise SystemExit("--strategy-id か --ranking-csv のどちらかを指定してください")

    script = generate_pine_script(
        params,
        symbol=symbol,
        timeframe=timeframe,
        strategy_title=title,
    )

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = resolve_output_dir(symbol, timeframe) / "strategy.pine"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(script, encoding="utf-8")

    print(f"Pine Script出力: {output_path}")
    print(f"通貨ペア: {symbol} / 時間足: {timeframe} / entry_trigger: {params.get('entry_trigger', 'breakout')}")
    print("TradingViewのPineエディタに貼り付けて使用してください。")
    print("既知の非互換点はengine/pine_generator.pyのモジュールdocstringを参照。")


if __name__ == "__main__":
    main()
