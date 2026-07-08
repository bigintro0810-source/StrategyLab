"""Heikin-Ashi synthetic candles - a smoothed OHLC transform popular for
filtering out noise-driven trend-direction flips.

ha_close is a simple average of the bar's own OHLC (fully vectorized, no
recursion). ha_open is recursive by definition (each bar's ha_open depends
on the PREVIOUS bar's ha_open and ha_close):

    ha_open[0] = (open[0] + close[0]) / 2
    ha_open[i] = (ha_open[i-1] + ha_close[i-1]) / 2   for i > 0

This is mathematically identical to an EWM (exponentially weighted mean,
alpha=0.5, adjust=False) applied to a series whose first element is the
seed ha_open[0] and whose remaining elements are ha_close shifted by one -
verified by direct comparison against a naive per-bar Python loop (exact
match to floating-point precision) rather than assumed. Using pandas' EWM
here avoids an O(n) Python loop for something that otherwise looks
recursive, at zero cost to correctness.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import engine.candlestick_patterns as _cdl


def heikin_ashi_ohlc(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4

    seed = pd.Series(ha_close.shift(1))
    seed.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
    ha_open = seed.ewm(alpha=0.5, adjust=False).mean()

    ha_high = pd.concat([df["high"], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df["low"], ha_open, ha_close], axis=1).min(axis=1)

    return ha_open, ha_high, ha_low, ha_close


def ha_bullish(df: pd.DataFrame, **p) -> np.ndarray:
    ha_open, _high, _low, ha_close = heikin_ashi_ohlc(df)
    return _cdl.bullish_candle(ha_open, ha_close).to_numpy(dtype=float)


def ha_bearish(df: pd.DataFrame, **p) -> np.ndarray:
    ha_open, _high, _low, ha_close = heikin_ashi_ohlc(df)
    return _cdl.bearish_candle(ha_open, ha_close).to_numpy(dtype=float)


def ha_strong_bullish(df: pd.DataFrame, threshold: float = 0.05, **p) -> np.ndarray:
    """Bullish HA candle with (near-)zero lower wick - the classic "strong,
    uninterrupted uptrend" Heikin-Ashi reading, distinct from a plain
    ha_bullish (which fires on any green HA candle, wick or no wick)."""
    ha_open, ha_high, ha_low, ha_close = heikin_ashi_ohlc(df)
    bullish = _cdl.bullish_candle(ha_open, ha_close)
    no_lower_wick = _cdl.no_lower_wick(ha_open, ha_high, ha_low, ha_close, threshold)
    return (bullish & no_lower_wick).to_numpy(dtype=float)


def ha_strong_bearish(df: pd.DataFrame, threshold: float = 0.05, **p) -> np.ndarray:
    """Mirror image of ha_strong_bullish: bearish HA candle with
    (near-)zero upper wick."""
    ha_open, ha_high, ha_low, ha_close = heikin_ashi_ohlc(df)
    bearish = _cdl.bearish_candle(ha_open, ha_close)
    no_upper_wick = _cdl.no_upper_wick(ha_open, ha_high, ha_low, ha_close, threshold)
    return (bearish & no_upper_wick).to_numpy(dtype=float)
