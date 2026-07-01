from pathlib import Path

import pandas as pd

from engine.monte_carlo import (
    export_monte_carlo,
    print_monte_carlo_summary,
)


INPUT_CSV = Path("output/trade_log.csv")
OUTPUT_DIR = Path("output")


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            "output/trade_log.csv が見つかりません。先に python main.py --mode full を実行してください。"
        )

    trade_log = pd.read_csv(INPUT_CSV)

    result_df, summary_df = export_monte_carlo(
        trade_log=trade_log,
        output_dir=OUTPUT_DIR,
    )

    print_monte_carlo_summary(
        result_df=result_df,
        summary_df=summary_df,
    )

    print()
    print(f"CSV保存完了: {OUTPUT_DIR / 'monte_carlo_results.csv'}")
    print(f"サマリー保存完了: {OUTPUT_DIR / 'monte_carlo_summary.csv'}")


if __name__ == "__main__":
    main()