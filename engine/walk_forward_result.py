from dataclasses import dataclass


@dataclass
class WalkForwardResult:
    train_start: int
    train_end: int

    test_start: int
    test_end: int

    score: float

    profit_factor: float
    total_profit: float
    max_drawdown: float
    win_rate: float

    yearly_stability: float
    monthly_stability: float

    max_consecutive_wins: int
    max_consecutive_losses: int

    passed: bool

    def to_dict(self):
        return {
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "score": self.score,
            "profit_factor": self.profit_factor,
            "total_profit": self.total_profit,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "yearly_stability": self.yearly_stability,
            "monthly_stability": self.monthly_stability,
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "passed": self.passed,
        }