def sma(series, length):
    """
    単純移動平均(SMA)
    """

    return series.rolling(window=length).mean()