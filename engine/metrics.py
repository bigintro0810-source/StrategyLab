class Metrics:
    def __init__(self, trades):
        self.trades = trades

    def total_trades(self):
        return len(self.trades)

    def wins(self):
        return [trade for trade in self.trades if trade.profit > 0]

    def losses(self):
        return [trade for trade in self.trades if trade.profit < 0]

    def win_rate(self):
        if self.total_trades() == 0:
            return 0.0

        return len(self.wins()) / self.total_trades() * 100

    def total_profit(self):
        return sum(trade.profit for trade in self.trades)

    def gross_profit(self):
        return sum(trade.profit for trade in self.wins())

    def gross_loss(self):
        return abs(sum(trade.profit for trade in self.losses()))

    def profit_factor(self):
        loss = self.gross_loss()

        if loss == 0:
            return 0.0

        return self.gross_profit() / loss

    def average_profit(self):
        if self.total_trades() == 0:
            return 0.0

        return self.total_profit() / self.total_trades()

    def summary(self):
        return {
            "total_trades": self.total_trades(),
            "win_rate": self.win_rate(),
            "total_profit": self.total_profit(),
            "gross_profit": self.gross_profit(),
            "gross_loss": self.gross_loss(),
            "profit_factor": self.profit_factor(),
            "average_profit": self.average_profit(),
        }