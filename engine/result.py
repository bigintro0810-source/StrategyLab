from dataclasses import dataclass


@dataclass
class Result:
    timeframe: str

    ema_period: int
    rsi_period: int
    rsi_threshold: float

    atr_period: int
    atr_threshold: float

    session_name: str
    session_start: int
    session_end: int

    direction: str

    stop_loss_pips: float
    take_profit_pips: float

    total_trades: int
    win_rate: float
    total_profit: float
    profit_factor: float
    average_profit: float
    max_drawdown: float
    sharpe_ratio: float
    score: float

    def to_dict(self):
        return {
            "timeframe": self.timeframe,
            "ema_period": self.ema_period,
            "rsi_period": self.rsi_period,
            "rsi_threshold": self.rsi_threshold,
            "atr_period": self.atr_period,
            "atr_threshold": self.atr_threshold,
            "session_name": self.session_name,
            "session_start": self.session_start,
            "session_end": self.session_end,
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