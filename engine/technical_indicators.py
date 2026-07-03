"""Pure technical-indicator math (V3.0 指標ライブラリ拡充, Tier 1).

No knowledge of "signal"/"filter"/"trigger" semantics here - just formulas,
vectorized over pandas Series. engine/triggers.py and engine/filters.py
build on top of these.

Deliberately limited to indicators with a single, unambiguous industry-
standard formula (no Wilder-vs-SMA-style dispute the way RSI/ATR have one
elsewhere in this codebase - see CLAUDE_HANDOVER.md for that unresolved
question, which this module does not touch).

Default periods (Bollinger 20/2, MACD 12/26/9, Ichimoku 9/26/52,
Stochastic 14/3/3) are the common industry defaults, not settled facts -
every one of them is also an adjustable/searchable parameter.
"""

import pandas as pd

from engine.indicators import ema


def donchian_channel(
    high: pd.Series,
    low: pd.Series,
    period: int,
) -> tuple[pd.Series, pd.Series]:
    upper = high.rolling(window=period).max()
    lower = low.rolling(window=period).min()

    return upper, lower


def bollinger_bands(
    close: pd.Series,
    period: int,
    num_std: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()

    upper = middle + num_std * std
    lower = middle - num_std * std

    return upper, middle, lower


def macd(
    close: pd.Series,
    fast: int,
    slow: int,
    signal: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)

    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    tenkan_period: int,
    kijun_period: int,
    senkou_b_period: int,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    tenkan = (
        high.rolling(window=tenkan_period).max() + low.rolling(window=tenkan_period).min()
    ) / 2

    kijun = (
        high.rolling(window=kijun_period).max() + low.rolling(window=kijun_period).min()
    ) / 2

    # Senkou spans are plotted `kijun_period` bars ahead of the data that
    # produced them, so the cloud visible AT bar i was computed using data
    # as of bar i - kijun_period. Shifting forward here reproduces that:
    # senkou_a[i] holds the (tenkan+kijun)/2 value from kijun_period bars ago.
    senkou_a = ((tenkan + kijun) / 2).shift(kijun_period)

    senkou_b_raw = (
        high.rolling(window=senkou_b_period).max() + low.rolling(window=senkou_b_period).min()
    ) / 2
    senkou_b = senkou_b_raw.shift(kijun_period)

    return tenkan, kijun, senkou_a, senkou_b


def stochastic_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int,
    d_period: int,
    smooth: int,
) -> tuple[pd.Series, pd.Series]:
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    raw_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    k = raw_k.rolling(window=smooth).mean()
    d = k.rolling(window=d_period).mean()

    return k, d


def daily_reference_levels(df: pd.DataFrame, adr_period: int) -> pd.DataFrame:
    """Previous-day high/low, classic pivot/R1/S1, and ADR - broadcast onto
    every intraday bar of the following day.

    Uses the PREVIOUS completed day's data only (shift(1) before broadcast),
    so nothing here looks ahead into the current day.
    """
    daily = (
        df.set_index("datetime")[["high", "low", "close"]]
        .resample("1D")
        .agg({"high": "max", "low": "min", "close": "last"})
        .dropna()
    )

    daily["pivot"] = (daily["high"] + daily["low"] + daily["close"]) / 3
    daily["r1"] = 2 * daily["pivot"] - daily["low"]
    daily["s1"] = 2 * daily["pivot"] - daily["high"]
    daily["daily_range"] = daily["high"] - daily["low"]
    daily["adr"] = daily["daily_range"].rolling(window=adr_period).mean()

    daily_shifted = daily.shift(1).rename(
        columns={"high": "prev_day_high", "low": "prev_day_low"}
    )
    daily_shifted = daily_shifted.reset_index().rename(columns={"datetime": "date"})

    work = df[["datetime"]].copy()
    work["date"] = work["datetime"].dt.floor("D")

    merged = work.merge(
        daily_shifted[["date", "prev_day_high", "prev_day_low", "pivot", "r1", "s1", "adr"]],
        on="date",
        how="left",
    )

    return merged[["prev_day_high", "prev_day_low", "pivot", "r1", "s1", "adr"]]


def round_number_distance_pips(close: pd.Series, pip: float) -> pd.Series:
    """Distance in pips from the nearest whole-unit price level (e.g. the
    nearest whole yen for a JPY pair)."""
    nearest_round = close.round(0)
    return (close - nearest_round).abs() / pip
