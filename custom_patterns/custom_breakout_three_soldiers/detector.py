"""3連続陽線 + 直近高値ブレイク(サンプル)。

直近 lookback 本の高値を終値で上抜け、かつ直前3本が連続陽線のバーで1を返す。
現在バーまでの情報しか使わない(先読みなし)。
"""

import numpy as np


def detect(df, lookback=20, **params):
    lookback = max(2, int(lookback))
    open_a = df["open"].to_numpy(dtype=float)
    high_a = df["high"].to_numpy(dtype=float)
    close_a = df["close"].to_numpy(dtype=float)
    n = len(close_a)
    out = np.zeros(n)
    if n < lookback + 3:
        return out

    bullish = close_a > open_a
    for i in range(lookback + 2, n):
        if not (bullish[i] and bullish[i - 1] and bullish[i - 2]):
            continue
        prior_high = high_a[i - lookback:i].max()
        if close_a[i] > prior_high:
            out[i] = 1.0
    return out
