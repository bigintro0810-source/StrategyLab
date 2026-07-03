import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's smoothed RSI - matches TradingView's built-in RSI.

    Verified 2026-07-03 against data/raw/TV_USDJPY_15m.csv's exported RSI
    column (100% agreement at the RSI>70 threshold, mean abs diff 0.006);
    see engine/backtest_engine.py::rsi() for the same formula, the one
    actually used by the live pipeline.
    """
    delta = series.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's smoothed ATR - matches TradingView's default ATR (RMA
    smoothing). NOT empirically verified against a TradingView export
    the way rsi() above was (no ATR column in data/raw/TV_USDJPY_15m.csv)
    - this follows the same Wilder convention on the reasonable inference
    that TradingView's ATR uses the same smoothing as its RSI does, but
    that inference hasn't been directly checked against real data yet.
    """
    high = data["high"]
    low = data["low"]
    close = data["close"]

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return true_range.ewm(alpha=1 / period, adjust=False).mean()