import pandas as pd

from config.scoring_config import load_scoring_config


INPUT_CSV = "output/optimizer_results_session.csv"
OUTPUT_CSV = "output/reranked_results.csv"


config = load_scoring_config()


def get_value(row, column_name, default=0.0):
    if column_name in row.index:
        return row[column_name]

    return default


def is_excluded(row):
    total_trades = get_value(row, "total_trades")
    total_profit = get_value(row, "total_profit")
    profit_factor = get_value(row, "profit_factor")
    yearly_stability = get_value(row, "yearly_stability")
    monthly_stability = get_value(row, "monthly_stability")
    max_drawdown = get_value(row, "max_drawdown")
    win_rate = get_value(row, "win_rate")
    average_profit = get_value(row, "average_profit")
    max_consecutive_losses = get_value(row, "max_consecutive_losses")
    direction = get_value(row, "direction", "")
    session_name = get_value(row, "session_name", "")

    if total_trades < config.minimum_trades:
        return True

    if total_profit < config.minimum_profit:
        return True

    if profit_factor < config.minimum_pf:
        return True

    if yearly_stability < config.minimum_yearly_stability:
        return True

    if monthly_stability < config.minimum_monthly_stability:
        return True

    if max_drawdown > config.maximum_drawdown:
        return True

    if win_rate < config.minimum_win_rate:
        return True

    if average_profit < config.minimum_average_profit:
        return True

    if max_consecutive_losses > config.maximum_consecutive_losses:
        return True

    if config.exclude_long == 1 and direction == "long":
        return True

    if config.exclude_short == 1 and direction == "short":
        return True

    if config.only_session != "" and session_name != config.only_session:
        return True

    return False


def calculate_score(row):
    if is_excluded(row):
        return -999999999

    total_trades = get_value(row, "total_trades")
    total_profit = get_value(row, "total_profit")
    profit_factor = get_value(row, "profit_factor")
    average_profit = get_value(row, "average_profit")
    win_rate = get_value(row, "win_rate")
    max_drawdown = get_value(row, "max_drawdown")

    yearly_stability = get_value(row, "yearly_stability")
    winning_years = get_value(row, "winning_years")
    losing_years = get_value(row, "losing_years")
    avg_yearly_profit = get_value(row, "avg_yearly_profit")
    min_yearly_profit = get_value(row, "min_yearly_profit")

    monthly_stability = get_value(row, "monthly_stability")
    winning_months = get_value(row, "winning_months")
    losing_months = get_value(row, "losing_months")
    avg_monthly_profit = get_value(row, "avg_monthly_profit")
    min_monthly_profit = get_value(row, "min_monthly_profit")

    max_consecutive_wins = get_value(row, "max_consecutive_wins")
    max_consecutive_losses = get_value(row, "max_consecutive_losses")

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
        + monthly_stability * config.monthly_stability_weight
        + winning_months * config.winning_months_weight
        - losing_months * config.losing_months_weight
        + avg_monthly_profit * config.avg_monthly_profit_weight
        + min_monthly_profit * config.min_monthly_profit_weight
        + max_consecutive_wins * config.max_consecutive_wins_weight
        - max_consecutive_losses * config.max_consecutive_losses_weight
    )

    return score


def main():
    df = pd.read_csv(INPUT_CSV)

    df["new_score"] = df.apply(calculate_score, axis=1)

    df = df[df["new_score"] > -999999999]

    df = df.sort_values("new_score", ascending=False)

    df.to_csv(OUTPUT_CSV, index=False)

    print()
    print("========== 新ランキング TOP10 ==========")
    print()

    if len(df) == 0:
        print("条件を満たすストラテジーはありません。")
        print()
        print("CSV保存完了")
        print(OUTPUT_CSV)
        return

    for i, row in enumerate(df.head(10).itertuples(index=False), start=1):
        yearly_stability = getattr(row, "yearly_stability", 0.0)
        winning_years = getattr(row, "winning_years", 0)
        losing_years = getattr(row, "losing_years", 0)

        monthly_stability = getattr(row, "monthly_stability", 0.0)
        winning_months = getattr(row, "winning_months", 0)
        losing_months = getattr(row, "losing_months", 0)

        max_consecutive_wins = getattr(row, "max_consecutive_wins", 0)
        max_consecutive_losses = getattr(row, "max_consecutive_losses", 0)

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
            f"月安定={monthly_stability:.2f}% | "
            f"勝月={winning_months} | "
            f"負月={losing_months} | "
            f"最大連勝={max_consecutive_wins} | "
            f"最大連敗={max_consecutive_losses} | "
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