from dataclasses import dataclass


@dataclass
class Trade:
    entry_time: str
    exit_time: str

    direction: str

    entry_price: float
    exit_price: float

    stop_loss: float
    take_profit: float

    profit: float