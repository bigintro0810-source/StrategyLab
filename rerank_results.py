import pandas as pd

from config.scoring_config import ScoringConfig


INPUT_CSV = "output/optimizer_results_session.csv"
OUTPUT_CSV = "output/reranked_results.csv"


config = ScoringConfig()


def calculate_score(row):

    if row["total_trades"] < config.minimum_trades:
        return -999999999

    if row["total_profit"] < config.minimum_profit:
        return -999999999

    if row["profit_factor"] < config.minimum_pf:
        return -999999999

    expectancy = row["average_profit"]

    score = (
        row["profit_factor"] * config.pf_weight
        + row["total_profit"] * config.profit_weight
        + expectancy * config.expectancy_weight
        + row["win_rate"] * config.win_rate_weight
        - row["max_drawdown"] * config.drawdown_weight
        + row["total_trades"] * config.trades_weight
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

        print(
            f"{i:2d}. "
            f"Score={row.new_score:.2f} | "
            f"PF={row.profit_factor:.2f} | "
            f"利益={row.total_profit:.2f} | "
            f"DD={row.max_drawdown:.2f} | "
            f"勝率={row.win_rate:.2f}% | "
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