import numpy as np

from engine.condition_config import ConditionConfig


class ConditionEngine:
    def __init__(self, data, config: ConditionConfig):
        self.data = data
        self.config = config

        self.close = data["close"].to_numpy(copy=False)

        self.datetime = data["datetime"].to_numpy(copy=False)

        self.hour = None
        self.weekday = None

    def prepare_time_arrays(self):
        if self.hour is None:
            datetime_series = self.data["datetime"]

            self.hour = datetime_series.dt.hour.to_numpy(copy=False)
            self.weekday = datetime_series.dt.weekday.to_numpy(copy=False)

    def build_signal(
        self,
        ema_array=None,
        rsi_array=None,
        atr_array=None,
        adx_array=None,
        rsi_threshold=None,
        atr_threshold=None,
        adx_threshold=None,
    ):
        signal = np.ones(len(self.close), dtype=np.bool_)

        # -----------------------
        # EMA
        # -----------------------

        if self.config.use_ema:
            if ema_array is None:
                raise ValueError("EMA条件がONですが、ema_arrayがありません。")

            if self.config.ema_above:
                signal &= self.close > ema_array

            if self.config.ema_below:
                signal &= self.close < ema_array

        # -----------------------
        # RSI
        # -----------------------

        if self.config.use_rsi:
            if rsi_array is None:
                raise ValueError("RSI条件がONですが、rsi_arrayがありません。")

            if rsi_threshold is None:
                raise ValueError("RSI条件がONですが、rsi_thresholdがありません。")

            if self.config.rsi_above:
                signal &= rsi_array > rsi_threshold

            if self.config.rsi_below:
                signal &= rsi_array < rsi_threshold

        # -----------------------
        # ATR
        # -----------------------

        if self.config.use_atr:
            if atr_array is None:
                raise ValueError("ATR条件がONですが、atr_arrayがありません。")

            if atr_threshold is None:
                raise ValueError("ATR条件がONですが、atr_thresholdがありません。")

            if self.config.atr_above:
                signal &= atr_array > atr_threshold

            if self.config.atr_below:
                signal &= atr_array < atr_threshold

        # -----------------------
        # ADX
        # -----------------------

        if self.config.use_adx:
            if adx_array is None:
                raise ValueError("ADX条件がONですが、adx_arrayがありません。")

            if adx_threshold is None:
                raise ValueError("ADX条件がONですが、adx_thresholdがありません。")

            if self.config.adx_above:
                signal &= adx_array > adx_threshold

        # -----------------------
        # 時間帯
        # -----------------------

        if self.config.use_session:
            self.prepare_time_arrays()

            start = self.config.session_start
            end = self.config.session_end

            if start < end:
                signal &= (self.hour >= start) & (self.hour < end)
            else:
                signal &= (self.hour >= start) | (self.hour < end)

        # -----------------------
        # 曜日
        # -----------------------

        if self.config.use_weekday:
            self.prepare_time_arrays()

            weekday_signal = np.zeros(len(self.close), dtype=np.bool_)

            if self.config.monday:
                weekday_signal |= self.weekday == 0

            if self.config.tuesday:
                weekday_signal |= self.weekday == 1

            if self.config.wednesday:
                weekday_signal |= self.weekday == 2

            if self.config.thursday:
                weekday_signal |= self.weekday == 3

            if self.config.friday:
                weekday_signal |= self.weekday == 4

            signal &= weekday_signal

        return signal