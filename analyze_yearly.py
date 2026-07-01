from pathlib import Path

import pandas as pd


INPUT_CSV = Path("output/trade_log.csv")
OUTPUT_CSV = Path("output/yearly_analysis.csv")


def calc_profit_factor(profits: pd.Series) -> float:
    gross_profit = profits[profits > 0].sum()
    gross_loss = profits[profits < 0].sum()

    if gross_loss < 0:
        return gross_profit / abs(gross_loss)

    if gross_profit > 0:
        return 999.0

    return 0.0


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError("output/trade_log.csv が見つかりません。先に main.py を実行してください。")

    df = pd.read_csv(INPUT_CSV)

    if df.empty:
        print("取引履歴が空です。")
        return

    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["year"] = df["entry_time"].dt.year

    rows = []

    for year, group in df.groupby("year"):
        profits = group["profit"]

        trades = len(group)
        wins = int((profits > 0).sum())
        losses = int((profits < 0).sum())
        win_rate = wins / trades * 100 if trades else 0.0

        net_profit = profits.sum()
        gross_profit = profits[profits > 0].sum()
        gross_loss = profits[profits < 0].sum()
        profit_factor = calc_profit_factor(profits)

        rows.append(
            {
                "year": int(year),
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "net_profit": round(net_profit, 5),
                "gross_profit": round(gross_profit, 5),
                "gross_loss": round(gross_loss, 5),
                "profit_factor": round(profit_factor, 3),
            }
        )

    result_df = pd.DataFrame(rows).sort_values("year")
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print()
    print("========== Yearly Analysis ==========")
    print()
    print(result_df.to_string(index=False))
    print()
    print(f"CSV保存完了: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()