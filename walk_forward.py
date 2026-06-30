import pandas as pd

from config.walk_forward_config import WalkForwardConfig


INPUT_CSV = "output/reranked_results.csv"
OUTPUT_CSV = "output/walk_forward_plan.csv"


config = WalkForwardConfig()


def build_windows():
    windows = []

    train_start = config.start_year

    while True:
        train_end = train_start + config.train_years - 1
        test_start = train_end + 1
        test_end = test_start + config.test_years - 1

        if test_end > config.end_year:
            break

        windows.append({
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        })

        train_start += config.test_years

    return windows


def main():
    df = pd.read_csv(INPUT_CSV)
    windows = build_windows()

    rows = []

    top_df = df.head(config.top_n)

    for window in windows:
        for rank, row in enumerate(top_df.itertuples(index=False), start=1):
            rows.append({
                "rank": rank,
                "train_start": window["train_start"],
                "train_end": window["train_end"],
                "test_start": window["test_start"],
                "test_end": window["test_end"],
                "timeframe": row.timeframe,
                "ema_period": row.ema_period,
                "rsi_period": row.rsi_period,
                "rsi_threshold": row.rsi_threshold,
                "atr_period": row.atr_period,
                "atr_threshold": row.atr_threshold,
                "session_name": row.session_name,
                "session_start": row.session_start,
                "session_end": row.session_end,
                "direction": row.direction,
                "stop_loss_pips": row.stop_loss_pips,
                "take_profit_pips": row.take_profit_pips,
                "score": row.new_score,
                "pf": row.profit_factor,
                "profit": row.total_profit,
                "drawdown": row.max_drawdown,
                "win_rate": row.win_rate,
                "yearly_stability": getattr(row, "yearly_stability", 0.0),
                "monthly_stability": getattr(row, "monthly_stability", 0.0),
                "max_consecutive_losses": getattr(row, "max_consecutive_losses", 0),
            })

    output_df = pd.DataFrame(rows)
    output_df.to_csv(OUTPUT_CSV, index=False)

    print()
    print("========== Walk Forward Plan ==========")
    print()

    for i, w in enumerate(windows, start=1):
        print(
            f"{i}. "
            f"Train {w['train_start']}-{w['train_end']} "
            f"-> Test {w['test_start']}-{w['test_end']}"
        )

    print()
    print(f"対象ストラテジー数: {config.top_n}")
    print(f"ウィンドウ数: {len(windows)}")
    print(f"出力行数: {len(output_df)}")
    print()
    print("CSV保存完了")
    print(OUTPUT_CSV)


if __name__ == "__main__":
    main()