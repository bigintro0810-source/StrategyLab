# -*- coding: utf-8 -*-
from pathlib import Path
import pandas as pd

OUT_DIR = Path("output")
RESULT_FILE = OUT_DIR / "strategy_lab_fast_results.csv"

def main():
    if not RESULT_FILE.exists():
        print("結果ファイルが見つかりません。")
        print("先に strategy_lab_fast_v1.py を実行してください。")
        return

    df = pd.read_csv(RESULT_FILE)

    print("=== Strategy Lab Detail V1 ===")
    print(f"読み込み件数: {len(df)}")
    print()

    # 上位20件を表示
    cols = [
        "direction", "breakout_bars", "session",
        "h4_filter", "d1_filter",
        "sl_pips", "tp_pips", "max_hold_bars",
        "trades", "pf", "winrate", "max_dd_pips",
        "net_pips", "min_period_pf", "score"
    ]

    print("=== ランキング上位20件 ===")
    print(df[cols].head(20).to_string(index=True))
    print()

    # 1位戦略を表示
    best = df.iloc[0]

    print("=== 1位戦略 ===")
    for c in cols:
        print(f"{c}: {best[c]}")

    print()
    print("次のVersionで、この1位戦略の年別成績とグラフを出します。")

if __name__ == "__main__":
    main()