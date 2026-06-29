import pandas as pd

from engine.indicators import ema, sma, rsi, atr


class IndicatorManager:
    def __init__(self, data: pd.DataFrame):
        self.data = data.copy()

    def add_sma(self, period: int):
        self.data[f"sma_{period}"] = sma(self.data["close"], period)

    def add_ema(self, period: int):
        self.data[f"ema_{period}"] = ema(self.data["close"], period)

    def add_rsi(self, period: int):
        self.data[f"rsi_{period}"] = rsi(self.data["close"], period)

    def add_atr(self, period: int):
        self.data[f"atr_{period}"] = atr(self.data, period)

    def add_basic_indicators(self):
        self.add_sma(20)
        self.add_ema(20)
        self.add_ema(50)
        self.add_ema(200)
        self.add_rsi(14)
        self.add_atr(14)

        return self.data