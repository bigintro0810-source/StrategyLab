from engine.metrics import calculate_metrics


def run_backtest(df, strategy):

    print()

    print("=" * 50)
    print("Backtest Start")
    print("=" * 50)

    trades = strategy(df)

    result = calculate_metrics(trades)

    return result