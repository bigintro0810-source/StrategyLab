from engine.order import Order
from engine.position import Position
from engine.trade import Trade


class Broker:
    def __init__(self):
        self.position: Position | None = None
        self.trades: list[Trade] = []

    def has_position(self) -> bool:
        return self.position is not None

    def open_position(self, order: Order) -> None:
        if self.has_position():
            return

        self.position = Position(
            direction=order.direction,
            entry_time=order.time,
            entry_price=order.price,
            size=order.size,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
        )

    def close_position(self, time, price: float, reason: str = "") -> None:
        if not self.has_position():
            return

        position = self.position

        if position.is_long():
            profit = (price - position.entry_price) * position.size
        elif position.is_short():
            profit = (position.entry_price - price) * position.size
        else:
            profit = 0.0

        trade = Trade(
            entry_time=position.entry_time,
            exit_time=time,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=price,
            size=position.size,
            profit=profit,
            reason=reason,
        )

        self.trades.append(trade)
        self.position = None

    def check_exit(self, time, high: float, low: float) -> None:
        if not self.has_position():
            return

        position = self.position

        if position.is_long():
            if position.stop_loss is not None and low <= position.stop_loss:
                self.close_position(time, position.stop_loss, "stop_loss")
                return

            if position.take_profit is not None and high >= position.take_profit:
                self.close_position(time, position.take_profit, "take_profit")
                return

        if position.is_short():
            if position.stop_loss is not None and high >= position.stop_loss:
                self.close_position(time, position.stop_loss, "stop_loss")
                return

            if position.take_profit is not None and low <= position.take_profit:
                self.close_position(time, position.take_profit, "take_profit")
                return