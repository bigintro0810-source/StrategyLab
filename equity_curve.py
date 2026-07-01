from pathlib import Path

import pandas as pd

from engine.equity_curve import (
    export_equity_curve,
    print_equity_curve_summary,
)


INPUT_CSV = Path("output/trade_log.csv")
OUTPUT_DIR = Path("output")


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            "output/trade_log.csv が見つかりません。先に python main.py --mode full を実行してください。"
        )

    trade_log = pd.read_csv(INPUT_CSV)

    equity_df = export_equity_curve(
        trade_log=trade_log,
        output_dir=OUTPUT_DIR,
    )

    print_equity_curve_summary(equity_df)

    print()
    print(f"CSV保存完了: {OUTPUT_DIR / 'equity_curve.csv'}")


if __name__ == "__main__":
    main()