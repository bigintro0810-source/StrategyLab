"""Selectable entry-trigger functions (V3.0 条件ベースのストラテジー定義).

Each trigger takes the same shape of inputs and returns a single
np.ndarray[bool] marking "a candidate signal fires at this bar" - the same
role the inline condition chain at the end of engine/backtest_engine.py's
loop used to play before this refactor. engine/signal_builder.py combines
whichever trigger is selected with the independently toggleable filters in
engine/filters.py.

`precomputed` is a dict of arrays built once by signal_builder.py before
dispatch (mirrors the precompute-once-outside-the-loop pattern already
used for ema_arr/rsi_arr/previous_high_arr in backtest_engine.py) - each
trigger below documents exactly which keys it reads.

A one-bar "cross" event (X was below Y last bar, is above Y this bar) is
computed the same way in every trigger that needs one: `above & ~prev_above`
where `prev_above` is `above` shifted forward by one bar via np.roll, with
index 0 forced False (np.roll would otherwise wrap the last bar's value
into index 0). NaN comparisons are always False in numpy, so warmup-period
bars (where a rolling indicator hasn't filled yet) naturally never trigger
without any extra isnan() handling - this matches how the original engine's
`previous_high_arr` NaN bars silently failed to trigger.
"""

from typing import Any

import numpy as np


def _crossed_above(above: np.ndarray) -> np.ndarray:
    prev_above = np.roll(above, 1)
    prev_above[0] = False
    return above & ~prev_above


def trigger_breakout(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """Current default trigger: bullish candle + close breaks above the
    previous N-bar high (N = breakout_bars). Extracted verbatim from the
    original inline condition chain, vectorized."""
    open_arr = precomputed["open"]
    close_arr = precomputed["close"]
    previous_high_arr = precomputed["previous_high"]

    bullish = close_arr > open_arr
    breakout = close_arr > previous_high_arr

    return bullish & breakout


def trigger_donchian_breakout(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """Same idea as trigger_breakout but WITHOUT the bullish-candle
    requirement - a plain Donchian-upper-band breakout."""
    close_arr = precomputed["close"]
    donchian_upper = precomputed["donchian_upper"]

    return close_arr > donchian_upper


def trigger_ema_cross(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]
    ema_arr = precomputed["ema"]

    return _crossed_above(close_arr > ema_arr)


def trigger_macd_cross(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    macd_line = precomputed["macd_line"]
    macd_signal = precomputed["macd_signal"]

    return _crossed_above(macd_line > macd_signal)


def trigger_bollinger_touch(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    """Close touches/exceeds the upper Bollinger band - consistent with
    this strategy's short-only, fade-the-extreme character."""
    close_arr = precomputed["close"]
    bollinger_upper = precomputed["bollinger_upper"]

    return close_arr >= bollinger_upper


def trigger_ichimoku_cloud_breakout(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    close_arr = precomputed["close"]
    senkou_a = precomputed["ichimoku_senkou_a"]
    senkou_b = precomputed["ichimoku_senkou_b"]

    cloud_top = np.maximum(senkou_a, senkou_b)

    return _crossed_above(close_arr > cloud_top)


def trigger_ichimoku_tk_cross(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    tenkan = precomputed["ichimoku_tenkan"]
    kijun = precomputed["ichimoku_kijun"]

    return _crossed_above(tenkan > kijun)


def trigger_stochastic_kd_cross(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    k = precomputed["stochastic_k"]
    d = precomputed["stochastic_d"]

    return _crossed_above(k > d)


def trigger_stochastic_level_cross(df, p: dict[str, Any], precomputed: dict[str, np.ndarray]) -> np.ndarray:
    k = precomputed["stochastic_k"]
    level = float(p.get("stochastic_level", 80.0))

    return _crossed_above(k > level)


TRIGGER_REGISTRY = {
    "breakout": trigger_breakout,
    "donchian_breakout": trigger_donchian_breakout,
    "ema_cross": trigger_ema_cross,
    "macd_cross": trigger_macd_cross,
    "bollinger_touch": trigger_bollinger_touch,
    "ichimoku_cloud_breakout": trigger_ichimoku_cloud_breakout,
    "ichimoku_tk_cross": trigger_ichimoku_tk_cross,
    "stochastic_kd_cross": trigger_stochastic_kd_cross,
    "stochastic_level_cross": trigger_stochastic_level_cross,
}
