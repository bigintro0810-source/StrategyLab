from dataclasses import dataclass


@dataclass
class StrategyConfig:
    timeframe: str = "1m"

    ema_period: int = 20
    rsi_period: int = 14
    rsi_threshold: float = 50.0

    direction: str = "long"
    size: float = 1.0

    stop_loss_pips: float = 10.0
    take_profit_pips: float = 20.0