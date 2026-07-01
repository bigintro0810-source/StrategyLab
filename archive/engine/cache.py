import pandas as pd

from engine.indicators import ema, sma, rsi, atr


class IndicatorCache:
    def __init__(self, data: pd.DataFrame):
        self.data = data.copy()
        self.cache = {}

    def get_ema(self, period: int):
        key = f"ema_{period}"

        if key not in self.cache:
            self.cache[key] = ema(self.data["close"], period)

        return self.cache[key]

    def get_sma(self, period: int):
        key = f"sma_{period}"

        if key not in self.cache:
            self.cache[key] = sma(self.data["close"], period)

        return self.cache[key]

    def get_rsi(self, period: int):
        key = f"rsi_{period}"

        if key not in self.cache:
            self.cache[key] = rsi(self.data["close"], period)

        return self.cache[key]

    def get_atr(self, period: int):
        key = f"atr_{period}"

        if key not in self.cache:
            self.cache[key] = atr(self.data, period)

        return self.cache[key]

    def preload(self):
        # よく使うインジケーターを最初に計算
        for period in [20, 50, 100, 200]:
            self.get_ema(period)

        self.get_sma(20)
        self.get_rsi(14)
        self.get_atr(14)

        # DataFrameへ追加
        for name, values in self.cache.items():
            self.data[name] = values

        return self.data