from config.scoring_config import ScoringConfig


class Ranking:
    def __init__(self, results):
        self.results = results
        self.config = ScoringConfig()

    def _score(self, r):

        if r.total_trades < self.config.minimum_trades:
            return -999999999

        expectancy = r.average_profit

        return (
            r.profit_factor * self.config.pf_weight
            + r.total_profit * self.config.profit_weight
            + expectancy * self.config.expectancy_weight
            + r.win_rate * self.config.win_rate_weight
            - r.max_drawdown * self.config.drawdown_weight
            + r.total_trades * self.config.trades_weight
        )

    def by_score(self, top=10):
        return sorted(
            self.results,
            key=self._score,
            reverse=True
        )[:top]

    def by_profit_factor(self, top=10):
        return sorted(
            self.results,
            key=lambda x: x.profit_factor,
            reverse=True
        )[:top]

    def by_total_profit(self, top=10):
        return sorted(
            self.results,
            key=lambda x: x.total_profit,
            reverse=True
        )[:top]

    def by_win_rate(self, top=10):
        return sorted(
            self.results,
            key=lambda x: x.win_rate,
            reverse=True
        )[:top]

    def by_average_profit(self, top=10):
        return sorted(
            self.results,
            key=lambda x: x.average_profit,
            reverse=True
        )[:top]

    def by_drawdown(self, top=10):
        return sorted(
            self.results,
            key=lambda x: x.max_drawdown
        )[:top]