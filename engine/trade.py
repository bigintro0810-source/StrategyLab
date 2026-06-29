from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    entry_time: datetime
    exit_time: datetime
    direction: str
    entry_price: float
    exit_price: float
    size: float
    profit: float
    reason: str = ""

    def is_win(self) -> bool:
        return self.profit > 0

    def is_loss(self) -> bool:
        return self.profit < 0