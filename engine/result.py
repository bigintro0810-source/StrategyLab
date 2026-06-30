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

    active_years: int = 0
    winning_years: int = 0
    losing_years: int = 0
    flat_years: int = 0
    avg_yearly_profit: float = 0.0
    min_yearly_profit: float = 0.0
    yearly_stability: float = 0.0

    active_months: int = 0
    winning_months: int = 0
    losing_months: int = 0
    flat_months: int = 0
    avg_monthly_profit: float = 0.0
    min_monthly_profit: float = 0.0
    monthly_stability: float = 0.0

    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

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
            "active_years": self.active_years,
            "winning_years": self.winning_years,
            "losing_years": self.losing_years,
            "flat_years": self.flat_years,
            "avg_yearly_profit": self.avg_yearly_profit,
            "min_yearly_profit": self.min_yearly_profit,
            "yearly_stability": self.yearly_stability,
            "active_months": self.active_months,
            "winning_months": self.winning_months,
            "losing_months": self.losing_months,
            "flat_months": self.flat_months,
            "avg_monthly_profit": self.avg_monthly_profit,
            "min_monthly_profit": self.min_monthly_profit,
            "monthly_stability": self.monthly_stability,
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
        }