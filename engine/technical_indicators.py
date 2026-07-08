"""Pure technical-indicator math (V3.0 指標ライブラリ拡充, Tier 1 + Tier 2).

No knowledge of "signal"/"filter"/"trigger" semantics here - just formulas,
vectorized over pandas Series. engine/triggers.py and engine/filters.py
build on top of these.

Tier 1 indicators (Donchian/Bollinger/MACD/Ichimoku/Stochastic/pivot+ADR)
have a single, unambiguous industry-standard formula. Tier 2 (SuperTrend,
ADX) both depend on Wilder-smoothed ATR - this was blocked until 2026-07-
03, when engine/backtest_engine.py::rsi() was verified against real
TradingView data and switched to Wilder smoothing (100% match vs. TV's
RSI export). engine/indicators.py::atr() was updated to the same Wilder
convention at the same time, though that specific inference (vs. RSI)
wasn't independently checked against a TradingView ATR export - see
CLAUDE_HANDOVER.md for the full history.

Default periods (Bollinger 20/2, MACD 12/26/9, Ichimoku 9/26/52,
Stochastic 14/3/3, SuperTrend 10/3, ADX 14) are the common industry
defaults, not settled facts - every one of them is also an adjustable/
searchable parameter.
"""

import numpy as np
import pandas as pd

from engine.indicators import atr as wilder_atr
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


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int,
    multiplier: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Standard SuperTrend: a Wilder-ATR-based trailing band that flips
    side when price closes through it. Returns (line, direction) where
    direction is +1 (uptrend, line acts as support below price) or -1
    (downtrend, line acts as resistance above price).

    The band construction is inherently recursive (each bar's band value
    depends on the previous bar's band AND trend state, not just a fixed
    lookback window), so unlike the other Tier 1/2 indicators this can't
    be expressed as a single vectorized pandas operation - it's computed
    with an explicit O(n) pass, the same complexity class as the
    line-continuation logic already used elsewhere in this codebase (e.g.
    run_backtest's own bar-by-bar loop).
    """
    atr_series = wilder_atr(pd.DataFrame({"high": high, "low": low, "close": close}), period)

    high_arr = high.to_numpy(dtype=float)
    low_arr = low.to_numpy(dtype=float)
    close_arr = close.to_numpy(dtype=float)
    atr_arr = atr_series.to_numpy(dtype=float)

    hl2 = (high_arr + low_arr) / 2
    basic_upper = hl2 + multiplier * atr_arr
    basic_lower = hl2 - multiplier * atr_arr

    n = len(close_arr)
    final_upper = np.zeros(n)
    final_lower = np.zeros(n)
    line = np.zeros(n)
    direction = np.ones(n, dtype=int)

    for i in range(n):
        if i == 0 or np.isnan(atr_arr[i]):
            final_upper[i] = basic_upper[i]
            final_lower[i] = basic_lower[i]
            line[i] = final_upper[i]
            direction[i] = -1
            continue

        if basic_upper[i] < final_upper[i - 1] or close_arr[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        if basic_lower[i] > final_lower[i - 1] or close_arr[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        if direction[i - 1] == -1 and close_arr[i] > final_upper[i - 1]:
            direction[i] = 1
        elif direction[i - 1] == 1 and close_arr[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

        line[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    return line, direction


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Wilder's ADX (Average Directional Index) plus its two directional
    components (+DI, -DI). All three legs (true range, +DM, -DM) use the
    same Wilder smoothing as RSI/ATR elsewhere in this codebase."""
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    smoothed_tr = true_range.ewm(alpha=1 / period, adjust=False).mean()
    smoothed_plus_dm = plus_dm.ewm(alpha=1 / period, adjust=False).mean()
    smoothed_minus_dm = minus_dm.ewm(alpha=1 / period, adjust=False).mean()

    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_line = dx.ewm(alpha=1 / period, adjust=False).mean()

    return plus_di, minus_di, adx_line


def daily_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    datetime: pd.Series,
) -> pd.Series:
    """Volume Weighted Average Price, anchored to (reset at) each calendar
    day - the standard default anchor most charting platforms use when no
    custom session/anchor is configured. cumsum-based, so still fully
    vectorized/causal (each bar only uses that day's bars up to itself).

    Forex has no single central exchange, so `volume` here is whatever
    tick/proxy volume the broker's feed reports (this project's data
    pipeline - see data/raw/{SYMBOL}_Data/*.csv - already carries a
    `volume` column for all 7 supported pairs), not true traded volume.
    Treat VWAP distance/crosses as a rough participation-weighted average,
    not a precise institutional benchmark, the same caveat that applies to
    any forex VWAP."""
    typical_price = (high + low + close) / 3.0
    day = pd.to_datetime(datetime).dt.date

    cum_pv = (typical_price * volume).groupby(day).cumsum()
    cum_volume = volume.groupby(day).cumsum()

    return cum_pv / cum_volume


# ---------------------------------------------------------------------------
# 2026-07-08追加: 定番オシレーター/トレンド系 (V3.0 Tier 1/2 と同じ位置づけ、
# 単一の業界標準式を持つもの)
# ---------------------------------------------------------------------------

def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """Commodity Channel Index - typical price's deviation from its own
    rolling mean, scaled by mean absolute deviation (the constant 0.015
    is Lambert's original scaling so +-100 roughly bounds normal
    fluctuation, though CCI itself is unbounded)."""
    typical_price = (high + low + close) / 3.0
    rolling_mean = typical_price.rolling(window=period).mean()
    mean_abs_dev = typical_price.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (typical_price - rolling_mean) / (0.015 * mean_abs_dev)


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Williams %R - same inputs as stochastic %K, inverted/rescaled to
    [-100, 0] (0 = at the period high, -100 = at the period low)."""
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    return -100 * (highest_high - close) / (highest_high - lowest_low)


def parabolic_sar(
    high: pd.Series, low: pd.Series, close: pd.Series,
    af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    """Parabolic Stop-And-Reverse. Returns (sar, direction) where direction
    is +1 (uptrend, SAR trails below price) or -1 (downtrend, SAR trails
    above price) - same output shape as supertrend() above.

    Inherently recursive (each bar's SAR/acceleration-factor depends on the
    previous bar's state and whether a new extreme was made), so - like
    supertrend() - this is an explicit O(n) pass rather than a single
    vectorized pandas expression."""
    high_arr = high.to_numpy(dtype=float)
    low_arr = low.to_numpy(dtype=float)
    n = len(high_arr)

    sar = np.zeros(n)
    direction = np.ones(n, dtype=int)
    af = np.full(n, af_start)
    ep = np.zeros(n)  # extreme point of the current trend

    direction[0] = 1
    sar[0] = low_arr[0]
    ep[0] = high_arr[0]

    for i in range(1, n):
        prev_sar = sar[i - 1]
        prev_ep = ep[i - 1]
        prev_af = af[i - 1]

        candidate_sar = prev_sar + prev_af * (prev_ep - prev_sar)

        if direction[i - 1] == 1:
            candidate_sar = min(candidate_sar, low_arr[i - 1], low_arr[i - 2] if i >= 2 else low_arr[i - 1])
            if low_arr[i] < candidate_sar:
                direction[i] = -1
                sar[i] = prev_ep
                ep[i] = low_arr[i]
                af[i] = af_start
            else:
                direction[i] = 1
                sar[i] = candidate_sar
                if high_arr[i] > prev_ep:
                    ep[i] = high_arr[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af
        else:
            candidate_sar = max(candidate_sar, high_arr[i - 1], high_arr[i - 2] if i >= 2 else high_arr[i - 1])
            if high_arr[i] > candidate_sar:
                direction[i] = 1
                sar[i] = prev_ep
                ep[i] = high_arr[i]
                af[i] = af_start
            else:
                direction[i] = -1
                sar[i] = candidate_sar
                if low_arr[i] < prev_ep:
                    ep[i] = low_arr[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af

    return sar, direction


def aroon(high: pd.Series, low: pd.Series, period: int = 14) -> tuple[pd.Series, pd.Series]:
    """Aroon Up/Down: 100 * (period - bars since the period's high/low) /
    period - measures how RECENTLY a new extreme was made, not just
    whether one exists (100 = the extreme is the current bar, 0 = it was
    `period` bars ago)."""
    bars_since_high = high.rolling(window=period + 1).apply(lambda x: period - np.argmax(x), raw=True)
    bars_since_low = low.rolling(window=period + 1).apply(lambda x: period - np.argmin(x), raw=True)
    aroon_up = 100 * (period - bars_since_high) / period
    aroon_down = 100 * (period - bars_since_low) / period
    return aroon_up, aroon_down


def choppiness_index(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """0-100: high values (>61.8 conventionally) mean the market is
    choppy/ranging, low values (<38.2) mean it's trending - built from the
    ratio of summed true-range "wiggle" to the period's net high-low
    range (a straight-line move has a small ratio; a back-and-forth chop
    covers much more total distance than its net range)."""
    prev_close = close.shift(1)
    true_range = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    sum_tr = true_range.rolling(window=period).sum()
    period_range = high.rolling(window=period).max() - low.rolling(window=period).min()
    return 100 * np.log10(sum_tr / period_range) / np.log10(period)


def keltner_channels(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20, atr_period: int = 10, multiplier: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ATR-based channel (EMA midline +- a multiple of ATR) - unlike
    Bollinger's std-based width, Keltner's width only reflects true-range
    volatility, which is exactly why "Bollinger inside Keltner" (see
    ttm_squeeze in engine/derived_indicators.py) is a meaningful squeeze
    signal and a plain single-band width percentile isn't."""
    middle = ema(close, period)
    atr_series = wilder_atr(pd.DataFrame({"high": high, "low": low, "close": close}), atr_period)
    upper = middle + multiplier * atr_series
    lower = middle - multiplier * atr_series
    return upper, middle, lower


# ---------------------------------------------------------------------------
# ボリューム系 - engine/technical_indicators.py::daily_vwap の注記と同じ制約:
# FXの出来高はブローカーのティック疑似出来高であり、真の取引高ではない。
# ---------------------------------------------------------------------------

def on_balance_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def money_flow_index(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 14) -> pd.Series:
    typical_price = (high + low + close) / 3.0
    raw_money_flow = typical_price * volume
    price_up = typical_price > typical_price.shift(1)

    positive_flow = raw_money_flow.where(price_up, 0.0).rolling(window=period).sum()
    negative_flow = raw_money_flow.where(~price_up, 0.0).rolling(window=period).sum()

    money_ratio = positive_flow / negative_flow
    return 100 - (100 / (1 + money_ratio))


def chaikin_money_flow(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
    money_flow_multiplier = ((close - low) - (high - close)) / (high - low)
    money_flow_volume = money_flow_multiplier * volume
    return money_flow_volume.rolling(window=period).sum() / volume.rolling(window=period).sum()


def accumulation_distribution(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    money_flow_multiplier = ((close - low) - (high - close)) / (high - low)
    return (money_flow_multiplier * volume).cumsum()


# ---------------------------------------------------------------------------
# ピボットポイントのバリエーション - すべて daily_reference_levels() と同じ
# 「前日の確定した高値/安値/終値のみを使い、翌日の全バーに配布する」規約
# (先読みなし)。
# ---------------------------------------------------------------------------

def _prev_day_hlc(df: pd.DataFrame) -> pd.DataFrame:
    daily = (
        df.set_index("datetime")[["high", "low", "close"]]
        .resample("1D")
        .agg({"high": "max", "low": "min", "close": "last"})
        .dropna()
    )
    daily_shifted = daily.shift(1).reset_index().rename(columns={"datetime": "date"})

    work = df[["datetime"]].copy()
    work["date"] = work["datetime"].dt.floor("D")
    merged = work.merge(daily_shifted, on="date", how="left")
    return merged[["high", "low", "close"]]


def woodie_pivot_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Woodie's pivot weights the previous close twice as heavily as
    high/low - meant to react a bit faster to the latest close than the
    classic floor-trader pivot."""
    prev = _prev_day_hlc(df)
    pivot = (prev["high"] + prev["low"] + 2 * prev["close"]) / 4
    r1 = 2 * pivot - prev["low"]
    s1 = 2 * pivot - prev["high"]
    r2 = pivot + (prev["high"] - prev["low"])
    s2 = pivot - (prev["high"] - prev["low"])
    return pd.DataFrame({"pivot": pivot, "r1": r1, "s1": s1, "r2": r2, "s2": s2})


def camarilla_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Camarilla levels cluster tightly around the previous close (R1-R2/
    S1-S2 are meant as intraday mean-reversion targets; R3/R4 and S3/S4
    are the breakout levels beyond that range)."""
    prev = _prev_day_hlc(df)
    day_range = prev["high"] - prev["low"]
    close = prev["close"]
    r1 = close + day_range * 1.1 / 12
    r2 = close + day_range * 1.1 / 6
    r3 = close + day_range * 1.1 / 4
    r4 = close + day_range * 1.1 / 2
    s1 = close - day_range * 1.1 / 12
    s2 = close - day_range * 1.1 / 6
    s3 = close - day_range * 1.1 / 4
    s4 = close - day_range * 1.1 / 2
    return pd.DataFrame({"r1": r1, "r2": r2, "r3": r3, "r4": r4, "s1": s1, "s2": s2, "s3": s3, "s4": s4})


def fibonacci_pivot_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Classic floor-trader pivot as the base, with R1-R3/S1-S3 spaced by
    Fibonacci ratios (0.382/0.618/1.0) of the previous day's range instead
    of the classic pivot formula's fixed 1x/2x spacing."""
    prev = _prev_day_hlc(df)
    pivot = (prev["high"] + prev["low"] + prev["close"]) / 3
    day_range = prev["high"] - prev["low"]
    r1 = pivot + 0.382 * day_range
    r2 = pivot + 0.618 * day_range
    r3 = pivot + 1.0 * day_range
    s1 = pivot - 0.382 * day_range
    s2 = pivot - 0.618 * day_range
    s3 = pivot - 1.0 * day_range
    return pd.DataFrame({"pivot": pivot, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3})
