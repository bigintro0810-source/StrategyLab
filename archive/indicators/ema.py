def ema(series, length):
    """
    EMAを計算する
    series: Closeなどの価格データ
    length: EMA期間
    """
    return series.ewm(span=length, adjust=False).mean()