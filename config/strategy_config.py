from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyConfig:
    timeframe: str = "1m"

    ema_period: int = 20
    rsi_period: int = 14
    rsi_threshold: float = 50.0

    atr_period: int = 14
    atr_threshold: float = 0.0

    session_name: str = "all"
    session_start: int = 0
    session_end: int = 24

    direction: str = "long"
    size: float = 1.0

    stop_loss_pips: float = 10.0
    take_profit_pips: float = 20.0