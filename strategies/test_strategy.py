from engine.order import Order


class TestStrategy:
    def next(self, i, data):
        if i != 10:
            return None

        row = data.iloc[i]

        entry_price = row["close"]
        stop_loss = entry_price - 0.10
        take_profit = entry_price + 0.20

        return Order(
            direction="long",
            order_type="market",
            price=entry_price,
            size=1,
            time=row["datetime"],
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment="test long",
        )