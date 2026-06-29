from dataclasses import dataclass


@dataclass
class Result:
    # -----------------------
    # Strategy
    # -----------------------

    timeframe: str

    ema_period: int
    rsi_period: int
    rsi_threshold: float

    direction: str

    stop_loss_pips: float
    take_profit_pips: float

    # -----------------------
    # Performance
    # -----------------------

    total_trades: int
    win_rate: float

    total_profit: float

    profit_factor: float

    average_profit: float

    max_drawdown: float

    sharpe_ratio: float

    score: float

    # -----------------------

    def to_dict(self):
        return {
            "timeframe": self.timeframe,
            "ema_period": self.ema_period,
            "rsi_period": self.rsi_period,
            "rsi_threshold": self.rsi_threshold,
            "direction": self.direction,
            "stop_loss_pips": self.stop_loss_pips,
            "take_profit_pips": self.take_profit_pips,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "total_profit": self.total_profit,
            "profit_factor": self.profit_factor,
            "average_profit": self.average_profit,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "score": self.score,
        }