from engine.data_loader import DataLoader
from engine.backtest import Backtest
from engine.metrics import Metrics
from strategies.test_strategy import TestStrategy


def main():
    print("=== Strategy Lab ===")

    loader = DataLoader()
    df = loader.load("1m")

    df = df.head(1000)

    strategy = TestStrategy()
    backtest = Backtest(df, strategy)

    trades = backtest.run()

    metrics = Metrics(trades)
    summary = metrics.summary()

    print("\n=== 検証結果 ===")
    print(f"トレード数: {summary['total_trades']}")
    print(f"勝率: {summary['win_rate']:.2f}%")
    print(f"総利益: {summary['total_profit']:.3f}")
    print(f"総利益額: {summary['gross_profit']:.3f}")
    print(f"総損失額: {summary['gross_loss']:.3f}")
    print(f"PF: {summary['profit_factor']:.3f}")
    print(f"期待値: {summary['average_profit']:.3f}")


if __name__ == "__main__":
    main()