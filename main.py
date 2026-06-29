from config.strategy_config import StrategyConfig
from engine.backtest import Backtest
from engine.data_loader import DataLoader
from engine.indicator_manager import IndicatorManager
from engine.metrics import Metrics
from strategies.test_strategy import TestStrategy


def main():
    print("=== Strategy Lab ===")

    # 設定
    config = StrategyConfig()

    # データ読み込み
    loader = DataLoader()
    df = loader.load(config.timeframe)

    # 動作確認用
    df = df.head(1000)

    # インジケーター追加
    manager = IndicatorManager(df)
    manager.add_ema(config.ema_period)
    manager.add_rsi(config.rsi_period)
    df = manager.data

    # ストラテジー
    strategy = TestStrategy(config)

    # バックテスト
    backtest = Backtest(df, strategy)
    trades = backtest.run()

    # 成績
    metrics = Metrics(trades)
    summary = metrics.summary()

    print("\n=== 検証結果 ===")
    print(f"時間足: {config.timeframe}")
    print(f"EMA期間: {config.ema_period}")
    print(f"RSI期間: {config.rsi_period}")
    print(f"RSI閾値: {config.rsi_threshold}")

    print(f"\nトレード数: {summary['total_trades']}")
    print(f"勝率: {summary['win_rate']:.2f}%")
    print(f"総利益: {summary['total_profit']:.3f}")
    print(f"PF: {summary['profit_factor']:.3f}")
    print(f"期待値: {summary['average_profit']:.3f}")


if __name__ == "__main__":
    main()