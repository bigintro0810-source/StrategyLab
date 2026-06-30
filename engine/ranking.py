from engine.result import Result


class Ranking:
    def __init__(self, results: list[Result]):
        self.results = results

    def valid_results(self, min_trades: int = 1):
        return [
            r for r in self.results
            if r.total_trades >= min_trades and r.score > -999999
        ]

    def by_score(self, top: int = 20, min_trades: int = 1):
        return sorted(
            self.valid_results(min_trades),
            key=lambda r: r.score,
            reverse=True
        )[:top]

    def by_profit_factor(self, top: int = 20, min_trades: int = 1):
        return sorted(
            self.valid_results(min_trades),
            key=lambda r: r.profit_factor,
            reverse=True
        )[:top]

    def by_total_profit(self, top: int = 20, min_trades: int = 1):
        return sorted(
            self.valid_results(min_trades),
            key=lambda r: r.total_profit,
            reverse=True
        )[:top]

    def by_win_rate(self, top: int = 20, min_trades: int = 1):
        return sorted(
            self.valid_results(min_trades),
            key=lambda r: r.win_rate,
            reverse=True
        )[:top]

    def by_average_profit(self, top: int = 20, min_trades: int = 1):
        return sorted(
            self.valid_results(min_trades),
            key=lambda r: r.average_profit,
            reverse=True
        )[:top]

    def by_drawdown(self, top: int = 20, min_trades: int = 1):
        return sorted(
            self.valid_results(min_trades),
            key=lambda r: r.max_drawdown
        )[:top]