from pathlib import Path

import pandas as pd


YEARLY_CSV = Path("output/yearly_analysis.csv")
MONTHLY_CSV = Path("output/monthly_analysis.csv")
OUTPUT_CSV = Path("output/stability_analysis.csv")


def safe_mean(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.mean())


def calc_positive_rate(profits: pd.Series) -> float:
    if len(profits) == 0:
        return 0.0
    return float((profits > 0).sum() / len(profits) * 100)


def calc_stability_score(profits: pd.Series) -> float:
    if len(profits) == 0:
        return 0.0

    positive_rate = calc_positive_rate(profits)
    avg_profit = safe_mean(profits)

    if avg_profit <= 0:
        return round(positive_rate * 0.5, 2)

    volatility = float(profits.std()) if len(profits) >= 2 else 0.0

    if volatility <= 0:
        return 100.0 if avg_profit > 0 else 0.0

    stability = avg_profit / volatility
    score = positive_rate * 0.7 + min(stability * 30, 30)

    return round(max(0.0, min(score, 100.0)), 2)


def main() -> None:
    if not YEARLY_CSV.exists():
        raise FileNotFoundError("output/yearly_analysis.csv が見つかりません。先に python analyze_yearly.py を実行してください。")

    if not MONTHLY_CSV.exists():
        raise FileNotFoundError("output/monthly_analysis.csv が見つかりません。先に python analyze_monthly.py を実行してください。")

    yearly_df = pd.read_csv(YEARLY_CSV)
    monthly_df = pd.read_csv(MONTHLY_CSV)

    yearly_profits = yearly_df["net_profit"]
    monthly_profits = monthly_df["net_profit"]

    yearly_positive_rate = calc_positive_rate(yearly_profits)
    monthly_positive_rate = calc_positive_rate(monthly_profits)

    yearly_stability = calc_stability_score(yearly_profits)
    monthly_stability = calc_stability_score(monthly_profits)

    total_profit = float(yearly_profits.sum())
    profitable_years = int((yearly_profits > 0).sum())
    losing_years = int((yearly_profits < 0).sum())
    flat_years = int((yearly_profits == 0).sum())

    profitable_months = int((monthly_profits > 0).sum())
    losing_months = int((monthly_profits < 0).sum())
    flat_months = int((monthly_profits == 0).sum())

    avg_yearly_profit = safe_mean(yearly_profits)
    avg_monthly_profit = safe_mean(monthly_profits)

    worst_year_profit = float(yearly_profits.min()) if len(yearly_profits) else 0.0
    best_year_profit = float(yearly_profits.max()) if len(yearly_profits) else 0.0

    worst_month_profit = float(monthly_profits.min()) if len(monthly_profits) else 0.0
    best_month_profit = float(monthly_profits.max()) if len(monthly_profits) else 0.0

    overall_stability = round(
        yearly_stability * 0.6 + monthly_stability * 0.4,
        2,
    )

    if overall_stability >= 80:
        rating = "A"
    elif overall_stability >= 65:
        rating = "B"
    elif overall_stability >= 50:
        rating = "C"
    else:
        rating = "D"

    result = {
        "total_profit": round(total_profit, 5),
        "profitable_years": profitable_years,
        "losing_years": losing_years,
        "flat_years": flat_years,
        "yearly_positive_rate": round(yearly_positive_rate, 2),
        "avg_yearly_profit": round(avg_yearly_profit, 5),
        "best_year_profit": round(best_year_profit, 5),
        "worst_year_profit": round(worst_year_profit, 5),
        "yearly_stability_score": yearly_stability,
        "profitable_months": profitable_months,
        "losing_months": losing_months,
        "flat_months": flat_months,
        "monthly_positive_rate": round(monthly_positive_rate, 2),
        "avg_monthly_profit": round(avg_monthly_profit, 5),
        "best_month_profit": round(best_month_profit, 5),
        "worst_month_profit": round(worst_month_profit, 5),
        "monthly_stability_score": monthly_stability,
        "overall_stability_score": overall_stability,
        "rating": rating,
    }

    result_df = pd.DataFrame([result])
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print()
    print("========== Stability Analysis ==========")
    print()
    print(f"総利益: {result['total_profit']}")
    print()
    print("----- 年別 -----")
    print(f"プラス年: {profitable_years}")
    print(f"マイナス年: {losing_years}")
    print(f"プラス年率: {yearly_positive_rate:.2f}%")
    print(f"平均年利益: {avg_yearly_profit:.5f}")
    print(f"最高年利益: {best_year_profit:.5f}")
    print(f"最低年利益: {worst_year_profit:.5f}")
    print(f"年別安定度: {yearly_stability}")
    print()
    print("----- 月別 -----")
    print(f"プラス月: {profitable_months}")
    print(f"マイナス月: {losing_months}")
    print(f"プラス月率: {monthly_positive_rate:.2f}%")
    print(f"平均月利益: {avg_monthly_profit:.5f}")
    print(f"最高月利益: {best_month_profit:.5f}")
    print(f"最低月利益: {worst_month_profit:.5f}")
    print(f"月別安定度: {monthly_stability}")
    print()
    print(f"総合安定度: {overall_stability}")
    print(f"評価: {rating}")
    print()
    print(f"CSV保存完了: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()