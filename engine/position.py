from dataclasses import dataclass
from datetime import datetime


@dataclass
class Position:
    direction: str
    entry_time: datetime
    entry_price: float
    size: float
    stop_loss: float | None = None
    take_profit: float | None = None

    def is_long(self) -> bool:
        return self.direction == "long"

    def is_short(self) -> bool:
        return self.direction == "short"

    def unrealized_profit(self, current_price: float) -> float:
        if self.is_long():
            return (current_price - self.entry_price) * self.size

        if self.is_short():
            return (self.entry_price - current_price) * self.size

        return 0.0