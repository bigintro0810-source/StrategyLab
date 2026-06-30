from engine.cache import IndicatorCache
from engine.csv_export import CsvExporter
from engine.data_loader import DataLoader
from engine.optimizer import Optimizer
from engine.ranking import Ranking
from strategies.test_strategy import TestStrategy


def print_results(title, results):
    print(f"\n=== {title} ===")

    if len(results) == 0:
        print("条件を満たすストラテジーはありません。")
        return

    for i, r in enumerate(results, start=1):

        pf = "∞" if r.profit_factor == float("inf") else f"{r.profit_factor:.2f}"

        print(
            f"{i:2d}. "
            f"Score={r.score:.2f} | "
            f"PF={pf} | "
            f"利益={r.total_profit:.2f} | "
            f"DD={r.max_drawdown:.2f} | "
            f"勝率={r.win_rate:.2f}% | "
            f"回数={r.total_trades} | "
            f"{r.direction} | "
            f"EMA{r.ema_period} | "
            f"RSI>{r.rsi_threshold} | "
            f"SL={r.stop_loss_pips} | "
            f"TP={r.take_profit_pips}"
        )


def main():

    print("=" * 60)
    print("Strategy Lab Optimizer v2.0 Full Data Numba")
    print("=" * 60)

    loader = DataLoader()
    df = loader.load("1m")

    print(f"読み込み件数: {len(df):,}")
    print(f"検証件数: {len(df):,}")

    cache = IndicatorCache(df)
    df = cache.preload()

    print("インジケーター計算完了")

    optimizer = Optimizer(
        df,
        strategy_class=TestStrategy
    )

    results = optimizer.run()

    print(f"\nバックテスト完了 : {len(results)} パターン")

    ranking = Ranking(results)

    print_results("総合ランキング TOP10", ranking.by_score(10))
    print_results("PFランキング TOP10", ranking.by_profit_factor(10))
    print_results("利益ランキング TOP10", ranking.by_total_profit(10))
    print_results("勝率ランキング TOP10", ranking.by_win_rate(10))
    print_results("期待値ランキング TOP10", ranking.by_average_profit(10))
    print_results("DDランキング TOP10", ranking.by_drawdown(10))

    exporter = CsvExporter()

    path = exporter.export(
        results,
        "optimizer_results_full_numba.csv"
    )

    print("\nCSV保存完了")
    print(path)


if __name__ == "__main__":
    main()