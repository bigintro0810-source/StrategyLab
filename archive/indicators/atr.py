import pandas as pd


def atr(df, length=14):
    """
    ATR(Average True Range)
    dfには High, Low, Close が必要
    """

    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_value = true_range.ewm(alpha=1 / length, adjust=False).mean()

    return atr_value