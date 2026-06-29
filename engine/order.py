from dataclasses import dataclass
from datetime import datetime


@dataclass
class Order:
    direction: str          # "long" または "short"
    order_type: str         # "market", "limit", "stop"
    price: float
    size: float
    time: datetime

    stop_loss: float | None = None
    take_profit: float | None = None
    comment: str = ""

    def is_market(self) -> bool:
        return self.order_type == "market"

    def is_limit(self) -> bool:
        return self.order_type == "limit"

    def is_stop(self) -> bool:
        return self.order_type == "stop"