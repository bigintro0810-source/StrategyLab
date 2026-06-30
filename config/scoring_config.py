from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringConfig:
    pf_weight: float = 1000.0
    profit_weight: float = 2.0
    expectancy_weight: float = 10000.0
    win_rate_weight: float = 10.0
    drawdown_weight: float = 50.0
    trades_weight: float = 0.0

    minimum_trades: int = 1000
    minimum_profit: float = 0.0
    minimum_pf: float = 1.05