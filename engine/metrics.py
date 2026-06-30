from typing import List

from engine.trade import Trade


class Metrics:
    def __init__(self, trades: List[Trade]):
        self.trades = trades

    # -----------------------
    # 基本
    # -----------------------

    def total_trades(self):
        return len(self.trades)

    def wins(self):
        return [t for t in self.trades if t.profit > 0]

    def losses(self):
        return [t for t in self.trades if t.profit < 0]

    def breakeven(self):
        return [t for t in self.trades if t.profit == 0]

    # -----------------------
    # 勝率
    # -----------------------

    def win_rate(self):
        if self.total_trades() == 0:
            return 0.0

        return len(self.wins()) / self.total_trades() * 100

    # -----------------------
    # 利益
    # -----------------------

    def total_profit(self):
        return sum(t.profit for t in self.trades)

    def gross_profit(self):
        return sum(t.profit for t in self.wins())

    def gross_loss(self):
        return abs(sum(t.profit for t in self.losses()))

    # -----------------------
    # Profit Factor
    # -----------------------

    def profit_factor(self):
        gp = self.gross_profit()
        gl = self.gross_loss()

        if gl == 0:
            if gp > 0:
                return float("inf")
            return 0.0

        return gp / gl

    # -----------------------
    # Expectancy
    # -----------------------

    def average_profit(self):
        if self.total_trades() == 0:
            return 0.0

        return self.total_profit() / self.total_trades()

    # -----------------------
    # 最大DD
    # -----------------------

    def max_drawdown(self):
        equity = 0.0
        peak = 0.0
        max_dd = 0.0

        for trade in self.trades:
            equity += trade.profit

            if equity > peak:
                peak = equity

            dd = peak - equity

            if dd > max_dd:
                max_dd = dd

        return max_dd

    # -----------------------
    # Sharpe（仮）
    # -----------------------

    def sharpe_ratio(self):
        return 0.0

    # -----------------------
    # スコア
    # -----------------------

    def score(self):
        if self.total_trades() == 0:
            return -999999

        pf = self.profit_factor()

        if pf == float("inf"):
            pf = 10.0

        score = (
            pf * 100
            + self.average_profit() * 1000
            + self.win_rate()
            - self.max_drawdown() * 50
            + self.total_trades() * 0.1
        )

        return score

    # -----------------------
    # Summary
    # -----------------------

    def summary(self):
        return {
            "total_trades": self.total_trades(),
            "win_rate": self.win_rate(),
            "total_profit": self.total_profit(),
            "gross_profit": self.gross_profit(),
            "gross_loss": self.gross_loss(),
            "profit_factor": self.profit_factor(),
            "average_profit": self.average_profit(),
            "max_drawdown": self.max_drawdown(),
            "sharpe_ratio": self.sharpe_ratio(),
            "score": self.score(),
        }