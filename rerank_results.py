import pandas as pd

from config.scoring_config import ScoringConfig


INPUT_CSV = "output/optimizer_results_session.csv"
OUTPUT_CSV = "output/reranked_results.csv"


config = ScoringConfig()


def get_value(row, column_name, default=0.0):
    if column_name in row.index:
        return row[column_name]

    return default


def calculate_score(row):

    total_trades = get_value(row, "total_trades")
    total_profit = get_value(row, "total_profit")
    profit_factor = get_value(row, "profit_factor")
    yearly_stability = get_value(row, "yearly_stability")

    if total_trades < config.minimum_trades:
        return -999999999

    if total_profit < config.minimum_profit:
        return -999999999

    if profit_factor < config.minimum_pf:
        return -999999999

    if yearly_stability < config.minimum_yearly_stability:
        return -999999999

    average_profit = get_value(row, "average_profit")
    win_rate = get_value(row, "win_rate")
    max_drawdown = get_value(row, "max_drawdown")

    winning_years = get_value(row, "winning_years")
    losing_years = get_value(row, "losing_years")
    avg_yearly_profit = get_value(row, "avg_yearly_profit")
    min_yearly_profit = get_value(row, "min_yearly_profit")

    score = (
        profit_factor * config.pf_weight
        + total_profit * config.profit_weight
        + average_profit * config.expectancy_weight
        + win_rate * config.win_rate_weight
        - max_drawdown * config.drawdown_weight
        + total_trades * config.trades_weight
        + yearly_stability * config.yearly_stability_weight
        + winning_years * config.winning_years_weight
        - losing_years * config.losing_years_weight
        + avg_yearly_profit * config.avg_yearly_profit_weight
        + min_yearly_profit * config.min_yearly_profit_weight
    )

    return score


def main():

    df = pd.read_csv(INPUT_CSV)

    df["new_score"] = df.apply(calculate_score, axis=1)

    df = df.sort_values("new_score", ascending=False)

    df.to_csv(OUTPUT_CSV, index=False)

    print()
    print("========== 新ランキング TOP10 ==========")
    print()

    for i, row in enumerate(df.head(10).itertuples(index=False), start=1):

        yearly_stability = getattr(row, "yearly_stability", 0.0)
        winning_years = getattr(row, "winning_years", 0)
        losing_years = getattr(row, "losing_years", 0)

        print(
            f"{i:2d}. "
            f"Score={row.new_score:.2f} | "
            f"PF={row.profit_factor:.2f} | "
            f"利益={row.total_profit:.2f} | "
            f"DD={row.max_drawdown:.2f} | "
            f"勝率={row.win_rate:.2f}% | "
            f"年安定={yearly_stability:.2f}% | "
            f"勝年={winning_years} | "
            f"負年={losing_years} | "
            f"回数={row.total_trades} | "
            f"{row.direction} | "
            f"EMA{row.ema_period} | "
            f"RSI>{row.rsi_threshold} | "
            f"ATR>{row.atr_threshold} | "
            f"Session={row.session_name} | "
            f"SL={row.stop_loss_pips} | "
            f"TP={row.take_profit_pips}"
        )

    print()
    print("CSV保存完了")
    print(OUTPUT_CSV)


if __name__ == "__main__":
    main()