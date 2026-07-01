from pathlib import Path

import pandas as pd


INPUT_CSV = Path("output/walk_forward_results.csv")
OUTPUT_CSV = Path("output/walk_forward_summary.csv")


def judge_row(row: pd.Series) -> str:
    if row["test_trades"] <= 0:
        return "NO_TRADE"

    if (
        row["test_net_profit"] > 0
        and row["test_profit_factor"] >= 1.2
        and row["test_max_dd"] <= 5.0
    ):
        return "PASS"

    if row["test_net_profit"] > 0:
        return "CAUTION"

    return "FAIL"


def overall_rating(pass_rate: float, avg_pf: float, total_profit: float, negative_tests: int) -> str:
    if pass_rate >= 70 and avg_pf >= 1.5 and total_profit > 0 and negative_tests <= 4:
        return "A"

    if pass_rate >= 55 and avg_pf >= 1.2 and total_profit > 0:
        return "B"

    if pass_rate >= 40 and total_profit > 0:
        return "C"

    return "D"


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            "output/walk_forward_results.csv が見つかりません。先に python walk_forward.py を実行してください。"
        )

    df = pd.read_csv(INPUT_CSV)

    df["judge"] = df.apply(judge_row, axis=1)

    valid_df = df[df["test_trades"] > 0].copy()

    total_rows = len(df)
    valid_rows = len(valid_df)

    pass_count = int((df["judge"] == "PASS").sum())
    caution_count = int((df["judge"] == "CAUTION").sum())
    fail_count = int((df["judge"] == "FAIL").sum())
    no_trade_count = int((df["judge"] == "NO_TRADE").sum())

    pass_rate = pass_count / total_rows * 100 if total_rows else 0.0

    avg_test_pf = float(valid_df["test_profit_factor"].replace(999.0, pd.NA).dropna().mean()) if valid_rows else 0.0
    avg_test_win_rate = float(valid_df["test_win_rate"].mean()) if valid_rows else 0.0
    total_test_profit = float(df["test_net_profit"].sum())
    avg_test_profit = float(df["test_net_profit"].mean()) if total_rows else 0.0
    max_test_dd = float(df["test_max_dd"].max()) if total_rows else 0.0

    negative_tests = int((df["test_net_profit"] < 0).sum())
    positive_tests = int((df["test_net_profit"] > 0).sum())

    rating = overall_rating(
        pass_rate=pass_rate,
        avg_pf=avg_test_pf,
        total_profit=total_test_profit,
        negative_tests=negative_tests,
    )

    summary = {
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "pass_count": pass_count,
        "caution_count": caution_count,
        "fail_count": fail_count,
        "no_trade_count": no_trade_count,
        "pass_rate": round(pass_rate, 2),
        "avg_test_pf": round(avg_test_pf, 3),
        "avg_test_win_rate": round(avg_test_win_rate, 2),
        "total_test_profit": round(total_test_profit, 5),
        "avg_test_profit": round(avg_test_profit, 5),
        "max_test_dd": round(max_test_dd, 5),
        "positive_tests": positive_tests,
        "negative_tests": negative_tests,
        "overall_rating": rating,
    }

    summary_df = pd.DataFrame([summary])
    summary_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    detail_output = Path("output/walk_forward_results_judged.csv")
    df.to_csv(detail_output, index=False, encoding="utf-8-sig")

    print()
    print("========== Walk Forward Analyzer ==========")
    print()
    print(f"総件数: {total_rows}")
    print(f"取引あり: {valid_rows}")
    print(f"PASS: {pass_count}")
    print(f"CAUTION: {caution_count}")
    print(f"FAIL: {fail_count}")
    print(f"NO_TRADE: {no_trade_count}")
    print()
    print(f"合格率: {pass_rate:.2f}%")
    print(f"平均テストPF: {avg_test_pf:.3f}")
    print(f"平均テスト勝率: {avg_test_win_rate:.2f}%")
    print(f"テスト合計利益: {total_test_profit:.5f}")
    print(f"テスト平均利益: {avg_test_profit:.5f}")
    print(f"最大DD: {max_test_dd:.5f}")
    print(f"プラス件数: {positive_tests}")
    print(f"マイナス件数: {negative_tests}")
    print()
    print(f"総合評価: {rating}")
    print()
    print(f"保存: {OUTPUT_CSV}")
    print(f"詳細保存: {detail_output}")


if __name__ == "__main__":
    main()