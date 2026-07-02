"""Print/save the combined Confidence Score for the current best strategy (V3.0).

Run this AFTER main.py, and ideally after walk_forward.py +
analyze_walk_forward.py + analyze_sensitivity.py have also been run
against the same best result - otherwise this will silently combine
fresh stability/Monte Carlo numbers with stale walk-forward/sensitivity
numbers from a previous run. There's no run identifier linking these
files together, so this script can't detect staleness itself; it just
tells you which components it found and used.
"""

import argparse
from pathlib import Path

import pandas as pd

from engine.robustness import compute_confidence_score

OUTPUT_DIR = Path("output")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="総合信頼性(Confidence Score)の集計")

    parser.add_argument(
        "--timeframe",
        default="15m",
        help="main.pyで使った時間足に合わせる (デフォルト: 15m)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = OUTPUT_DIR if args.timeframe == "15m" else OUTPUT_DIR / args.timeframe

    result = compute_confidence_score(output_dir)

    print("========== Confidence Score ==========")
    print()

    if not result["components_used"]:
        print("集計対象のデータがありません。main.pyを先に実行してください。")
        return

    for component in result["components_used"]:
        print(f"  {component['name']}: {component['rating']}")

    if result["components_missing"]:
        print()
        print(f"未取得(未実行のため対象外): {', '.join(result['components_missing'])}")

    print()
    print(f"総合Confidence Score: {result['confidence_score']} ({result['confidence_rating']})")
    print()
    print(
        "注意: walk_forward/sensitivityの数値は main.py とは別に手動実行した結果です。"
        "直近のベスト戦略に対して再実行していないと古い数値のまま混ざります。"
    )

    summary_path = output_dir / "confidence_summary.csv"

    pd.DataFrame(
        [
            {
                "confidence_score": result["confidence_score"],
                "confidence_rating": result["confidence_rating"],
                "components_used": ",".join(c["name"] for c in result["components_used"]),
                "components_missing": ",".join(result["components_missing"]),
            }
        ]
    ).to_csv(summary_path, index=False, encoding="utf-8-sig")

    print(f"出力: {summary_path}")


if __name__ == "__main__":
    main()
