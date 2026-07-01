from dataclasses import dataclass


@dataclass
class YearStat:
    year: int

    trades: int = 0

    wins: int = 0

    losses: int = 0

    gross_profit: float = 0.0

    gross_loss: float = 0.0

    net_profit: float = 0.0

    @property
    def win_rate(self):

        if self.trades == 0:
            return 0.0

        return self.wins / self.trades * 100

    @property
    def profit_factor(self):

        if self.gross_loss == 0:

            if self.gross_profit > 0:
                return float("inf")

            return 0.0

        return self.gross_profit / abs(self.gross_loss)