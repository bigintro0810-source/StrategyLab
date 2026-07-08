"""Metadata for automatic condition-tree generation (engine/structure_generator.py).

engine/conditions.py's INDICATOR_REGISTRY only knows how to *evaluate* an
indicator - it has no notion of which comparisons are semantically sane
(e.g. RSI vs a raw price level is meaningless; a boolean SMC signal only
ever means anything compared against 1). That information belongs here,
not in conditions.py, since it's only needed by the generator - hand-built
trees from the dashboard's manual builder don't need this and shouldn't be
constrained by it.

Each indicator is tagged with a "kind" that determines: which operators
make sense, whether it can be compared against another indicator of the
same kind (e.g. ema(20) vs ema(50) - a moving-average cross), and/or what
range a literal comparison value should be sampled from.

Full pool: covers all 40 indicators in engine/conditions.py's
INDICATOR_REGISTRY (as of 2026-07-07) across 6 kinds. Two kinds added
beyond the original MVP1 pool to handle indicators that don't fit
price_level/oscillator_0_100/boolean_signal cleanly:
    - "volatility" (ATR): always positive, no natural upper bound, so
      "atr > <literal>" has no symbol-independent meaning (a JPY pair's ATR
      in raw price units is ~100x a non-JPY pair's) - like price_level,
      restricted to indicator-vs-indicator only (e.g. atr(14) vs atr(50),
      a volatility expansion/contraction signal), never a literal.
    - "signed_price_diff" (MACD line/signal, candle_body): a signed
      difference in the symbol's native price units, so an arbitrary
      nonzero literal has the same cross-symbol-scale problem as
      price_level/volatility - but unlike those, zero itself IS a
      universally meaningful boundary (MACD's zero-line cross, a
      bearish/bullish candle body) regardless of symbol, so literal_choices
      is restricted to exactly 0.0 rather than being disabled outright.
See project memory project_auto_exploration_core_goal.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IndicatorSpec:
    name: str
    kind: str
    param_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Discrete float choices for a param, sampled via rng.choice() instead of
    # rng.randint() - for knobs like Fibonacci's ratio where only specific
    # conventional values (0.236/0.382/0.618/...) are meaningful, unlike a
    # continuous "length"-style range.
    param_choices: dict[str, list[float]] = field(default_factory=dict)
    allow_indicator_pair: bool = False
    literal_range: tuple[float, float] | None = None
    literal_choices: list[float] | None = None
    literal_is_int: bool = False


# Which operators make sense for each kind. Condition.evaluate() itself
# doesn't care about kind - this is purely about generating sane candidates.
OPERATORS_BY_KIND: dict[str, list[str]] = {
    "price_level": [">", "<", "crosses_above", "crosses_below"],
    "oscillator_0_100": [">", "<", "crosses_above", "crosses_below"],
    "boolean_signal": ["=="],
    "trend_binary": ["=="],
    "volatility": [">", "<", "crosses_above", "crosses_below"],
    "signed_price_diff": [">", "<", "crosses_above", "crosses_below"],
    "time_hour": [">", "<", "=="],
    "time_weekday": [">", "<", "=="],
    "time_month": [">", "<", "=="],
    # Dimensionless ratios/percentiles/z-scores/angles/rate-of-change - unlike
    # price_level/volatility, a literal comparison IS symbol-independent
    # (a %B of 0.8 or a z-score of 2.0 means the same thing on any pair), so
    # unlike those two, per-spec literal_range below is the normal case, not
    # the exception.
    "unitless_ratio": [">", "<", "crosses_above", "crosses_below"],
}

# price_level has no literal_range on purpose: a raw price number ("close >
# 150.5") doesn't generalize across symbols with very different price
# scales, so every price_level indicator must be compared against another
# price_level indicator instead. Bollinger/VWAP/Donchian-mid/SuperTrend-line
# are all price-level lines too (same units as close), so they join this
# same group rather than getting their own kind.
INDICATOR_POOL: list[IndicatorSpec] = [
    IndicatorSpec("close", "price_level", allow_indicator_pair=True),
    IndicatorSpec("open", "price_level", allow_indicator_pair=True),
    IndicatorSpec("high", "price_level", allow_indicator_pair=True),
    IndicatorSpec("low", "price_level", allow_indicator_pair=True),
    IndicatorSpec("ema", "price_level", param_ranges={"length": (10, 300)}, allow_indicator_pair=True),
    IndicatorSpec("sma", "price_level", param_ranges={"length": (10, 300)}, allow_indicator_pair=True),
    IndicatorSpec("highest_high", "price_level", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec("lowest_low", "price_level", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec("donchian_mid", "price_level", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec(
        "bollinger_upper", "price_level", param_ranges={"period": (10, 50)}, allow_indicator_pair=True
    ),
    IndicatorSpec(
        "bollinger_middle", "price_level", param_ranges={"period": (10, 50)}, allow_indicator_pair=True
    ),
    IndicatorSpec(
        "bollinger_lower", "price_level", param_ranges={"period": (10, 50)}, allow_indicator_pair=True
    ),
    # No volume column check happens here - all 7 currently-supported
    # symbols have one (see engine/technical_indicators.py::daily_vwap's
    # docstring); a future symbol without volume would raise a clear
    # ValueError from _vwap() at backtest time, same as the manual builder.
    IndicatorSpec("vwap", "price_level", allow_indicator_pair=True),
    IndicatorSpec(
        "supertrend_line", "price_level", param_ranges={"length": (5, 30)}, allow_indicator_pair=True
    ),
    # prev_day_high/low + pivot/R1/S1 have no adjustable params - they're
    # always derived from the single immediately-preceding calendar day
    # (no lookback length concept), unlike adr below which shares the same
    # underlying daily_reference_levels() call but IS period-sensitive.
    IndicatorSpec("prev_day_high", "price_level", allow_indicator_pair=True),
    IndicatorSpec("prev_day_low", "price_level", allow_indicator_pair=True),
    IndicatorSpec("pivot", "price_level", allow_indicator_pair=True),
    IndicatorSpec("pivot_r1", "price_level", allow_indicator_pair=True),
    IndicatorSpec("pivot_s1", "price_level", allow_indicator_pair=True),
    IndicatorSpec(
        "ichimoku_tenkan", "price_level",
        param_ranges={"tenkan_period": (5, 15), "kijun_period": (20, 35), "senkou_b_period": (40, 65)},
        allow_indicator_pair=True,
    ),
    IndicatorSpec(
        "ichimoku_kijun", "price_level",
        param_ranges={"tenkan_period": (5, 15), "kijun_period": (20, 35), "senkou_b_period": (40, 65)},
        allow_indicator_pair=True,
    ),
    IndicatorSpec(
        "ichimoku_senkou_a", "price_level",
        param_ranges={"tenkan_period": (5, 15), "kijun_period": (20, 35), "senkou_b_period": (40, 65)},
        allow_indicator_pair=True,
    ),
    IndicatorSpec(
        "ichimoku_senkou_b", "price_level",
        param_ranges={"tenkan_period": (5, 15), "kijun_period": (20, 35), "senkou_b_period": (40, 65)},
        allow_indicator_pair=True,
    ),
    # Fibonacci retracement/extension: `ratio` sampled from the conventional
    # discrete levels (not a continuous range - intermediate values like
    # 0.44 aren't a recognized Fibonacci level) via param_choices.
    IndicatorSpec(
        "fib_level", "price_level",
        param_ranges={"length": (10, 50)},
        param_choices={"ratio": [0.236, 0.382, 0.5, 0.618, 0.786, 1.272, 1.618]},
        allow_indicator_pair=True,
    ),
    IndicatorSpec(
        "rsi", "oscillator_0_100", param_ranges={"length": (7, 30)},
        allow_indicator_pair=True, literal_range=(20.0, 80.0),
    ),
    IndicatorSpec(
        "adx", "oscillator_0_100", param_ranges={"length": (7, 30)},
        allow_indicator_pair=True, literal_range=(15.0, 40.0),
    ),
    IndicatorSpec(
        "plus_di", "oscillator_0_100", param_ranges={"length": (7, 30)},
        allow_indicator_pair=True, literal_range=(15.0, 40.0),
    ),
    IndicatorSpec(
        "minus_di", "oscillator_0_100", param_ranges={"length": (7, 30)},
        allow_indicator_pair=True, literal_range=(15.0, 40.0),
    ),
    IndicatorSpec(
        "stochastic_k",
        "oscillator_0_100",
        param_ranges={"k_period": (5, 21), "d_period": (3, 5), "smooth": (3, 5)},
        allow_indicator_pair=True, literal_range=(20.0, 80.0),
    ),
    IndicatorSpec(
        "stochastic_d",
        "oscillator_0_100",
        param_ranges={"k_period": (5, 21), "d_period": (3, 5), "smooth": (3, 5)},
        allow_indicator_pair=True, literal_range=(20.0, 80.0),
    ),
    IndicatorSpec("atr", "volatility", param_ranges={"length": (7, 30)}, allow_indicator_pair=True),
    IndicatorSpec("adr", "volatility", param_ranges={"adr_period": (7, 30)}, allow_indicator_pair=True),
    IndicatorSpec(
        "macd_line",
        "signed_price_diff",
        param_ranges={"fast": (8, 16), "slow": (20, 30), "signal": (7, 11)},
        allow_indicator_pair=True, literal_choices=[0.0],
    ),
    IndicatorSpec(
        "macd_signal",
        "signed_price_diff",
        param_ranges={"fast": (8, 16), "slow": (20, 30), "signal": (7, 11)},
        allow_indicator_pair=True, literal_choices=[0.0],
    ),
    IndicatorSpec("candle_body", "signed_price_diff", allow_indicator_pair=True, literal_choices=[0.0]),
    IndicatorSpec("fvg_bullish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("fvg_bearish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("order_block_bullish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("order_block_bearish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("breaker_block_bullish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("breaker_block_bearish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec(
        "bos_bullish", "boolean_signal", param_ranges={"length": (3, 10)}, literal_choices=[1.0]
    ),
    IndicatorSpec(
        "bos_bearish", "boolean_signal", param_ranges={"length": (3, 10)}, literal_choices=[1.0]
    ),
    IndicatorSpec(
        "choch_bullish", "boolean_signal", param_ranges={"length": (3, 10)}, literal_choices=[1.0]
    ),
    IndicatorSpec(
        "choch_bearish", "boolean_signal", param_ranges={"length": (3, 10)}, literal_choices=[1.0]
    ),
    IndicatorSpec(
        "liquidity_sweep_bullish", "boolean_signal", param_ranges={"length": (3, 10)}, literal_choices=[1.0]
    ),
    IndicatorSpec(
        "liquidity_sweep_bearish", "boolean_signal", param_ranges={"length": (3, 10)}, literal_choices=[1.0]
    ),
    IndicatorSpec("killzone_asian", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("killzone_london", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("killzone_newyork", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("killzone_london_close", "boolean_signal", literal_choices=[1.0]),
    # Candlestick patterns (engine/candlestick_patterns.py) - all
    # boolean_signal, same as the SMC/Kill Zone entries above.
    IndicatorSpec("bullish_candle", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("bearish_candle", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec(
        "large_bullish_candle", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (10, 50)}, param_choices={"multiplier": [1.2, 1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "large_bearish_candle", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (10, 50)}, param_choices={"multiplier": [1.2, 1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "small_bullish_candle", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (10, 50)}, param_choices={"multiplier": [0.3, 0.4, 0.5, 0.6, 0.7]},
    ),
    IndicatorSpec(
        "small_bearish_candle", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (10, 50)}, param_choices={"multiplier": [0.3, 0.4, 0.5, 0.6, 0.7]},
    ),
    IndicatorSpec(
        "doji", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_threshold": [0.05, 0.1, 0.15, 0.2]},
    ),
    IndicatorSpec(
        "long_upper_wick", "boolean_signal", literal_choices=[1.0],
        param_choices={"wick_ratio_threshold": [0.5, 0.6, 0.7, 0.8]},
    ),
    IndicatorSpec(
        "long_lower_wick", "boolean_signal", literal_choices=[1.0],
        param_choices={"wick_ratio_threshold": [0.5, 0.6, 0.7, 0.8]},
    ),
    IndicatorSpec(
        "no_upper_wick", "boolean_signal", literal_choices=[1.0],
        param_choices={"threshold": [0.02, 0.05, 0.1]},
    ),
    IndicatorSpec(
        "no_lower_wick", "boolean_signal", literal_choices=[1.0],
        param_choices={"threshold": [0.02, 0.05, 0.1]},
    ),
    IndicatorSpec(
        "marubozu_bullish", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_threshold": [0.9, 0.95, 0.98]},
    ),
    IndicatorSpec(
        "marubozu_bearish", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_threshold": [0.9, 0.95, 0.98]},
    ),
    IndicatorSpec(
        "pin_bar_bullish", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_max": [0.2, 0.3, 0.4], "wick_ratio_min": [0.5, 0.6, 0.7]},
    ),
    IndicatorSpec(
        "pin_bar_bearish", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_max": [0.2, 0.3, 0.4], "wick_ratio_min": [0.5, 0.6, 0.7]},
    ),
    IndicatorSpec(
        "hammer", "boolean_signal", literal_choices=[1.0],
        param_choices={
            "body_ratio_max": [0.2, 0.3, 0.4],
            "lower_wick_ratio_min": [0.5, 0.6, 0.7],
            "upper_wick_ratio_max": [0.05, 0.1, 0.15],
        },
    ),
    IndicatorSpec(
        "hanging_man", "boolean_signal", literal_choices=[1.0],
        param_choices={
            "body_ratio_max": [0.2, 0.3, 0.4],
            "lower_wick_ratio_min": [0.5, 0.6, 0.7],
            "upper_wick_ratio_max": [0.05, 0.1, 0.15],
        },
    ),
    IndicatorSpec(
        "inverted_hammer", "boolean_signal", literal_choices=[1.0],
        param_choices={
            "body_ratio_max": [0.2, 0.3, 0.4],
            "upper_wick_ratio_min": [0.5, 0.6, 0.7],
            "lower_wick_ratio_max": [0.05, 0.1, 0.15],
        },
    ),
    IndicatorSpec(
        "shooting_star", "boolean_signal", literal_choices=[1.0],
        param_choices={
            "body_ratio_max": [0.2, 0.3, 0.4],
            "upper_wick_ratio_min": [0.5, 0.6, 0.7],
            "lower_wick_ratio_max": [0.05, 0.1, 0.15],
        },
    ),
    IndicatorSpec("engulfing_bullish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("engulfing_bearish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("inside_bar", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("outside_bar", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec(
        "tweezer_top", "boolean_signal", literal_choices=[1.0],
        param_choices={"tolerance_pct": [0.05, 0.1, 0.15, 0.2]},
    ),
    IndicatorSpec(
        "tweezer_bottom", "boolean_signal", literal_choices=[1.0],
        param_choices={"tolerance_pct": [0.05, 0.1, 0.15, 0.2]},
    ),
    IndicatorSpec("harami_bullish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("harami_bearish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("gap_up", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("gap_down", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec(
        "morning_star", "boolean_signal", literal_choices=[1.0],
        param_choices={"small_body_ratio": [0.2, 0.3, 0.4]},
    ),
    IndicatorSpec(
        "evening_star", "boolean_signal", literal_choices=[1.0],
        param_choices={"small_body_ratio": [0.2, 0.3, 0.4]},
    ),
    IndicatorSpec("three_white_soldiers", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("three_black_crows", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("rising_three_methods", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("falling_three_methods", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec(
        "consecutive_bullish_candles", "boolean_signal", literal_choices=[1.0],
        param_ranges={"n": (2, 10)},
    ),
    IndicatorSpec(
        "consecutive_bearish_candles", "boolean_signal", literal_choices=[1.0],
        param_ranges={"n": (2, 10)},
    ),
    IndicatorSpec(
        "consecutive_higher_highs", "boolean_signal", literal_choices=[1.0],
        param_ranges={"n": (2, 10)},
    ),
    IndicatorSpec(
        "consecutive_lower_lows", "boolean_signal", literal_choices=[1.0],
        param_ranges={"n": (2, 10)},
    ),
    IndicatorSpec(
        "body_larger_than_average", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (10, 50)}, param_choices={"multiplier": [1.2, 1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "wick_ratio_at_least", "boolean_signal", literal_choices=[1.0],
        param_choices={"threshold_pct": [30.0, 40.0, 50.0, 60.0, 70.0]},
    ),
    IndicatorSpec(
        "body_ratio_at_least", "boolean_signal", literal_choices=[1.0],
        param_choices={"threshold_pct": [30.0, 40.0, 50.0, 60.0, 70.0]},
    ),
    IndicatorSpec(
        "supertrend_direction", "trend_binary", param_ranges={"length": (5, 30)},
        literal_choices=[-1.0, 1.0],
    ),
    IndicatorSpec("hour", "time_hour", literal_range=(0, 23), literal_is_int=True),
    IndicatorSpec("weekday", "time_weekday", literal_range=(0, 6), literal_is_int=True),
    IndicatorSpec("month", "time_month", literal_range=(1, 12), literal_is_int=True),
]

# ---------------------------------------------------------------------------
# 2026-07-08追加: 距離系/傾き系/価格位置/統計系/イベント系 (engine/derived_indicators.py)
# 114 new indicators. dist_{close,high,low}_{11 targets} (33) and the 7
# rising/falling series pairs (14) are generated via a loop rather than
# hand-duplicated, same DRY approach derived_indicators.py itself used.
# ---------------------------------------------------------------------------

# name -> (param_ranges, param_choices) for each of the 11 distance targets -
# shared between all three close/high/low variants of that target.
_DISTANCE_TARGET_PARAMS: dict[str, tuple[dict, dict]] = {
    "ema": ({"length": (10, 300)}, {}),
    "sma": ({"length": (10, 300)}, {}),
    "vwap": ({}, {}),
    "supertrend": ({"length": (5, 30)}, {"multiplier": [2.0, 2.5, 3.0, 3.5, 4.0]}),
    "pivot": ({}, {}),
    "prev_day_high": ({}, {}),
    "prev_day_low": ({}, {}),
    "donchian_upper": ({"length": (10, 50)}, {}),
    "donchian_lower": ({"length": (10, 50)}, {}),
    "bb_upper": ({"period": (10, 50)}, {"num_std": [1.5, 2.0, 2.5]}),
    "bb_lower": ({"period": (10, 50)}, {"num_std": [1.5, 2.0, 2.5]}),
}

# "volatility": always positive, symbol-scale-dependent (a distance in raw
# JPY-pair price units is ~100x a non-JPY pair's) - same restriction as ATR,
# indicator-vs-indicator comparison only (e.g. dist_close_ema vs atr, which
# is literally "EMAからATR◯倍以上離れている" from an indicator pair rather
# than the dedicated dist_to_ema_atr_ratio below).
for _target_name, (_ranges, _choices) in _DISTANCE_TARGET_PARAMS.items():
    for _price_source in ("close", "high", "low"):
        INDICATOR_POOL.append(
            IndicatorSpec(
                f"dist_{_price_source}_{_target_name}", "volatility",
                param_ranges=dict(_ranges), param_choices=dict(_choices), allow_indicator_pair=True,
            )
        )

INDICATOR_POOL.extend([
    IndicatorSpec("dist_order_block_bullish", "volatility", allow_indicator_pair=True),
    IndicatorSpec("dist_order_block_bearish", "volatility", allow_indicator_pair=True),
    IndicatorSpec("dist_fvg_bullish", "volatility", allow_indicator_pair=True),
    IndicatorSpec("dist_fvg_bearish", "volatility", allow_indicator_pair=True),
    IndicatorSpec("dist_bos_bullish", "volatility", param_ranges={"length": (3, 10)}, allow_indicator_pair=True),
    IndicatorSpec("dist_bos_bearish", "volatility", param_ranges={"length": (3, 10)}, allow_indicator_pair=True),
    IndicatorSpec(
        "minutes_since_london_open", "unitless_ratio",
        literal_range=(0, 480), literal_is_int=True,
    ),
    IndicatorSpec(
        "minutes_since_ny_open", "unitless_ratio",
        literal_range=(0, 480), literal_is_int=True,
    ),
])

# 傾き系: rising/falling generated for all 7 base series (engine/
# derived_indicators.py::SLOPE_INDICATORS), boolean ("==1.0"), each with the
# base series' own param_ranges plus a shared `lookback` (how many bars back
# to compare against).
_SLOPE_SERIES_PARAMS: dict[str, dict] = {
    "ema": {"length": (10, 300)},
    "vwap": {},
    "supertrend": {"length": (5, 30)},
    "rsi": {"length": (7, 30)},
    "adx": {"length": (7, 30)},
    "macd": {"fast": (8, 16), "slow": (20, 30), "signal": (7, 11)},
    "atr": {"length": (7, 30)},
}
for _series_name, _series_ranges in _SLOPE_SERIES_PARAMS.items():
    for _direction in ("rising", "falling"):
        INDICATOR_POOL.append(
            IndicatorSpec(
                f"{_series_name}_{_direction}", "boolean_signal", literal_choices=[1.0],
                param_ranges={**_series_ranges, "lookback": (1, 10)},
            )
        )

INDICATOR_POOL.extend([
    IndicatorSpec(
        "ema_slope_degrees", "unitless_ratio", literal_range=(-30.0, 30.0),
        param_ranges={"length": (10, 300), "lookback": (2, 20)},
    ),
    IndicatorSpec(
        "ema_roc", "unitless_ratio", literal_range=(-10.0, 10.0),
        param_ranges={"length": (10, 300), "lookback": (2, 20)},
    ),
    IndicatorSpec(
        "atr_roc", "unitless_ratio", literal_range=(-30.0, 100.0),
        param_ranges={"length": (7, 30), "lookback": (1, 10)},
    ),
    IndicatorSpec("higher_high", "boolean_signal", literal_choices=[1.0], param_ranges={"lookback": (3, 15)}),
    IndicatorSpec("higher_low", "boolean_signal", literal_choices=[1.0], param_ranges={"lookback": (3, 15)}),
    IndicatorSpec("lower_high", "boolean_signal", literal_choices=[1.0], param_ranges={"lookback": (3, 15)}),
    IndicatorSpec("lower_low", "boolean_signal", literal_choices=[1.0], param_ranges={"lookback": (3, 15)}),
    # 価格位置
    IndicatorSpec(
        "bb_percent_b", "unitless_ratio", literal_range=(-0.2, 1.2),
        param_ranges={"period": (10, 50)}, param_choices={"num_std": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec(
        "donchian_percent_position", "unitless_ratio", literal_range=(-0.2, 1.2),
        param_ranges={"length": (10, 50)},
    ),
    IndicatorSpec(
        "dist_to_ema_atr_ratio", "unitless_ratio", literal_range=(0.2, 3.0),
        param_ranges={"ema_length": (10, 300), "atr_length": (7, 30)},
    ),
    IndicatorSpec(
        "today_range_pct_of_adr", "unitless_ratio", literal_range=(50.0, 150.0),
        param_ranges={"adr_period": (7, 30)},
    ),
    IndicatorSpec("prev_day_mid", "price_level", allow_indicator_pair=True),
    IndicatorSpec("today_range_position", "unitless_ratio", literal_range=(0.0, 1.0)),
    IndicatorSpec(
        "dist_to_fib", "volatility",
        param_ranges={"length": (10, 50)},
        param_choices={"ratio": [0.236, 0.382, 0.5, 0.618, 0.786, 1.272, 1.618]},
        allow_indicator_pair=True,
    ),
    # 統計系
    IndicatorSpec("rolling_mean_high", "price_level", param_ranges={"length": (10, 300)}, allow_indicator_pair=True),
    IndicatorSpec("rolling_mean_low", "price_level", param_ranges={"length": (10, 300)}, allow_indicator_pair=True),
    IndicatorSpec("avg_body_size", "volatility", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec("max_body_size", "volatility", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec("min_body_size", "volatility", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec("body_size_std", "volatility", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec("avg_upper_wick", "volatility", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec("avg_lower_wick", "volatility", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec(
        "atr_rolling_mean", "volatility",
        param_ranges={"atr_length": (7, 30), "window": (10, 50)}, allow_indicator_pair=True,
    ),
    IndicatorSpec(
        "atr_deviation", "signed_price_diff",
        param_ranges={"atr_length": (7, 30), "window": (10, 50)}, literal_choices=[0.0],
        allow_indicator_pair=True,
    ),
    IndicatorSpec("close_rolling_std", "volatility", param_ranges={"length": (10, 50)}, allow_indicator_pair=True),
    IndicatorSpec(
        "rsi_rolling_mean", "oscillator_0_100",
        param_ranges={"rsi_length": (7, 30), "window": (10, 50)},
        allow_indicator_pair=True, literal_range=(20.0, 80.0),
    ),
    IndicatorSpec(
        "rsi_deviation", "unitless_ratio", literal_range=(-15.0, 15.0),
        param_ranges={"rsi_length": (7, 30), "window": (10, 50)}, allow_indicator_pair=True,
    ),
    IndicatorSpec(
        "adx_rolling_mean", "oscillator_0_100",
        param_ranges={"adx_length": (7, 30), "window": (10, 50)},
        allow_indicator_pair=True, literal_range=(15.0, 40.0),
    ),
    IndicatorSpec(
        "macd_rolling_mean", "signed_price_diff",
        param_ranges={"window": (10, 50)}, literal_choices=[0.0], allow_indicator_pair=True,
    ),
    IndicatorSpec(
        "percentile_rank_rsi", "unitless_ratio", literal_range=(0.0, 100.0),
        param_ranges={"rsi_length": (7, 30), "window": (50, 200)},
    ),
    IndicatorSpec(
        "percentile_rank_atr", "unitless_ratio", literal_range=(0.0, 100.0),
        param_ranges={"atr_length": (7, 30), "window": (100, 300)},
    ),
    IndicatorSpec(
        "percentile_rank_body", "unitless_ratio", literal_range=(0.0, 100.0),
        param_ranges={"window": (20, 100)},
    ),
    IndicatorSpec(
        "zscore_close", "unitless_ratio", literal_range=(-3.0, 3.0), param_ranges={"window": (10, 50)},
    ),
    IndicatorSpec(
        "zscore_rsi", "unitless_ratio", literal_range=(-3.0, 3.0),
        param_ranges={"rsi_length": (7, 30), "window": (10, 50)},
    ),
    IndicatorSpec(
        "zscore_atr", "unitless_ratio", literal_range=(-3.0, 3.0),
        param_ranges={"atr_length": (7, 30), "window": (10, 50)},
    ),
    IndicatorSpec(
        "is_max_body_of_n", "boolean_signal", literal_choices=[1.0], param_ranges={"window": (50, 200)},
    ),
    IndicatorSpec(
        "is_min_atr_of_n", "boolean_signal", literal_choices=[1.0],
        param_ranges={"atr_length": (7, 30), "window": (20, 100)},
    ),
    IndicatorSpec(
        "is_max_rsi_of_n", "boolean_signal", literal_choices=[1.0],
        param_ranges={"rsi_length": (7, 30), "window": (50, 300)},
    ),
    # エントリー専用イベント
    IndicatorSpec(
        "bb_width", "volatility",
        param_ranges={"period": (10, 50)}, param_choices={"num_std": [1.5, 2.0, 2.5]},
        allow_indicator_pair=True,
    ),
    IndicatorSpec(
        "bb_squeeze", "boolean_signal", literal_choices=[1.0],
        param_ranges={"period": (10, 50), "window": (50, 200)},
        param_choices={"num_std": [1.5, 2.0, 2.5], "percentile": [5.0, 10.0, 15.0, 20.0]},
    ),
    IndicatorSpec(
        "bb_expansion", "boolean_signal", literal_choices=[1.0],
        param_ranges={"period": (10, 50), "window": (50, 200)},
        param_choices={"num_std": [1.5, 2.0, 2.5], "percentile": [5.0, 10.0, 15.0, 20.0]},
    ),
    IndicatorSpec(
        "supertrend_flip_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length": (5, 30)}, param_choices={"multiplier": [2.0, 2.5, 3.0, 3.5, 4.0]},
    ),
    IndicatorSpec(
        "supertrend_flip_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length": (5, 30)}, param_choices={"multiplier": [2.0, 2.5, 3.0, 3.5, 4.0]},
    ),
    IndicatorSpec("today_new_high", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("today_new_low", "boolean_signal", literal_choices=[1.0]),
    # 一瞬だけ起きる変化
    IndicatorSpec(
        "rsi_divergence_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length": (10, 50), "rsi_length": (7, 30)},
    ),
    IndicatorSpec(
        "rsi_divergence_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length": (10, 50), "rsi_length": (7, 30)},
    ),
    IndicatorSpec(
        "macd_divergence_bearish", "boolean_signal", literal_choices=[1.0], param_ranges={"length": (10, 50)},
    ),
    IndicatorSpec(
        "macd_divergence_bullish", "boolean_signal", literal_choices=[1.0], param_ranges={"length": (10, 50)},
    ),
    IndicatorSpec(
        "ema_perfect_order_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length_1": (10, 30), "length_2": (40, 70), "length_3": (80, 130), "length_4": (150, 250)},
    ),
    IndicatorSpec(
        "ema_perfect_order_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length_1": (10, 30), "length_2": (40, 70), "length_3": (80, 130), "length_4": (150, 250)},
    ),
    IndicatorSpec(
        "ema_perfect_order_broken_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length_1": (10, 30), "length_2": (40, 70), "length_3": (80, 130), "length_4": (150, 250)},
    ),
    IndicatorSpec(
        "ema_perfect_order_broken_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length_1": (10, 30), "length_2": (40, 70), "length_3": (80, 130), "length_4": (150, 250)},
    ),
    IndicatorSpec(
        "first_pullback_after_breakout_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length": (10, 50)},
    ),
    IndicatorSpec(
        "first_pullback_after_breakout_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"length": (10, 50)},
    ),
    IndicatorSpec("fvg_first_retest_bullish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("fvg_first_retest_bearish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("order_block_first_retest_bullish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("order_block_first_retest_bearish", "boolean_signal", literal_choices=[1.0]),
])

# ---------------------------------------------------------------------------
# 2026-07-08追加(2巡目): ローソク足パターン14種 + ラウンドナンバー距離 +
# チャートパターン19種 (engine/chart_patterns.py) - 34 new indicators.
# ---------------------------------------------------------------------------
INDICATOR_POOL.extend([
    # 追加ローソク足パターン
    IndicatorSpec(
        "long_legged_doji", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_threshold": [0.05, 0.1, 0.15, 0.2], "wick_ratio_min": [0.25, 0.35, 0.45]},
    ),
    IndicatorSpec(
        "dragonfly_doji", "boolean_signal", literal_choices=[1.0],
        param_choices={
            "body_ratio_threshold": [0.05, 0.1, 0.15],
            "lower_wick_ratio_min": [0.5, 0.6, 0.7],
            "upper_wick_ratio_max": [0.05, 0.1, 0.15],
        },
    ),
    IndicatorSpec(
        "gravestone_doji", "boolean_signal", literal_choices=[1.0],
        param_choices={
            "body_ratio_threshold": [0.05, 0.1, 0.15],
            "upper_wick_ratio_min": [0.5, 0.6, 0.7],
            "lower_wick_ratio_max": [0.05, 0.1, 0.15],
        },
    ),
    IndicatorSpec(
        "spinning_top", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_max": [0.2, 0.3, 0.4], "wick_ratio_min": [0.2, 0.3, 0.4]},
    ),
    IndicatorSpec(
        "kicker_bullish", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_threshold": [0.5, 0.6, 0.7, 0.8]},
    ),
    IndicatorSpec(
        "kicker_bearish", "boolean_signal", literal_choices=[1.0],
        param_choices={"body_ratio_threshold": [0.5, 0.6, 0.7, 0.8]},
    ),
    IndicatorSpec(
        "belt_hold_bullish", "boolean_signal", literal_choices=[1.0],
        param_choices={"lower_wick_ratio_max": [0.02, 0.05, 0.1], "body_ratio_min": [0.6, 0.7, 0.8]},
    ),
    IndicatorSpec(
        "belt_hold_bearish", "boolean_signal", literal_choices=[1.0],
        param_choices={"upper_wick_ratio_max": [0.02, 0.05, 0.1], "body_ratio_min": [0.6, 0.7, 0.8]},
    ),
    IndicatorSpec(
        "abandoned_baby_bullish", "boolean_signal", literal_choices=[1.0],
        param_choices={"small_body_ratio": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec(
        "abandoned_baby_bearish", "boolean_signal", literal_choices=[1.0],
        param_choices={"small_body_ratio": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec("three_inside_up", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("three_inside_down", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("three_outside_up", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("three_outside_down", "boolean_signal", literal_choices=[1.0]),
    # ラウンドナンバー距離 - 常にvolatility kind(価格単位・symbol依存)。
    # pip_sizeは通貨ペア/銘柄によって異なるべきだが(main.py::pip_size_for_symbol
    # 参照 - JPYペア=0.01、非JPYペア=0.0001、XAUUSD=0.01、XAGUSD=0.001)、この
    # プールは通貨ペアを知らないので候補をまとめて選択肢として渡すのみ - 実行
    # 対象と噛み合わないpip_sizeを選ぶ可能性はある既知の限界(このプロジェクトの
    # fib比率選択などと同じ、symbol非依存な汎用選択肢という扱い)。
    IndicatorSpec(
        "dist_to_round_number", "volatility",
        param_choices={"pip_size": [0.01, 0.001, 0.0001]}, allow_indicator_pair=True,
    ),
    # チャートパターン(engine/chart_patterns.py) - 全てboolean_signal。
    # tolerance/margin類はATR倍率で正規化済み(symbol/timeframe非依存)。
    IndicatorSpec(
        "double_top_breakdown", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)}, param_choices={"tolerance_atr_mult": [0.3, 0.5, 0.75, 1.0]},
    ),
    IndicatorSpec(
        "double_bottom_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)}, param_choices={"tolerance_atr_mult": [0.3, 0.5, 0.75, 1.0]},
    ),
    IndicatorSpec(
        "triple_top_breakdown", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)}, param_choices={"tolerance_atr_mult": [0.3, 0.5, 0.75, 1.0]},
    ),
    IndicatorSpec(
        "triple_bottom_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)}, param_choices={"tolerance_atr_mult": [0.3, 0.5, 0.75, 1.0]},
    ),
    IndicatorSpec(
        "head_and_shoulders_breakdown", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
        param_choices={"shoulder_tolerance_atr_mult": [0.5, 0.75, 1.0], "head_margin_atr_mult": [0.25, 0.5, 0.75]},
    ),
    IndicatorSpec(
        "inverse_head_and_shoulders_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
        param_choices={"shoulder_tolerance_atr_mult": [0.5, 0.75, 1.0], "head_margin_atr_mult": [0.25, 0.5, 0.75]},
    ),
    IndicatorSpec(
        "ascending_triangle_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)}, param_choices={"flat_tolerance_atr_mult": [0.3, 0.5, 0.75]},
    ),
    IndicatorSpec(
        "descending_triangle_breakdown", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)}, param_choices={"flat_tolerance_atr_mult": [0.3, 0.5, 0.75]},
    ),
    IndicatorSpec(
        "symmetrical_triangle_breakout_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "symmetrical_triangle_breakout_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "rising_wedge_breakdown", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "falling_wedge_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "bull_flag_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"impulse_lookback": (5, 20), "consolidation_window": (5, 20)},
        param_choices={"impulse_atr_mult": [2.0, 2.5, 3.0, 3.5], "consolidation_atr_mult": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec(
        "bear_flag_breakdown", "boolean_signal", literal_choices=[1.0],
        param_ranges={"impulse_lookback": (5, 20), "consolidation_window": (5, 20)},
        param_choices={"impulse_atr_mult": [2.0, 2.5, 3.0, 3.5], "consolidation_atr_mult": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec(
        "bullish_pennant_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"impulse_lookback": (5, 20), "consolidation_window": (5, 20)},
        param_choices={"impulse_atr_mult": [2.0, 2.5, 3.0, 3.5], "consolidation_atr_mult": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec(
        "bearish_pennant_breakdown", "boolean_signal", literal_choices=[1.0],
        param_ranges={"impulse_lookback": (5, 20), "consolidation_window": (5, 20)},
        param_choices={"impulse_atr_mult": [2.0, 2.5, 3.0, 3.5], "consolidation_atr_mult": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec(
        "in_range_box", "boolean_signal", literal_choices=[1.0],
        param_ranges={"window": (10, 40)}, param_choices={"box_atr_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "range_box_breakout_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"window": (10, 40)}, param_choices={"box_atr_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "range_box_breakdown_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"window": (10, 40)}, param_choices={"box_atr_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
])


# ---------------------------------------------------------------------------
# 2026-07-08追加(3巡目): 定番オシレーター/トレンド系 + ボリューム系 + 一目補完 +
# TTMスクイーズ + ピボットバリエーション + 線形回帰 + 平均足 +
# ハーモニックパターン - 58 new indicators.
# ---------------------------------------------------------------------------
INDICATOR_POOL.extend([
    IndicatorSpec(
        "cci", "unitless_ratio", literal_range=(-200.0, 200.0), param_ranges={"period": (10, 30)},
    ),
    IndicatorSpec(
        "williams_r", "unitless_ratio", literal_range=(-90.0, -10.0), param_ranges={"period": (7, 30)},
    ),
    IndicatorSpec(
        "parabolic_sar_line", "price_level", allow_indicator_pair=True,
        param_choices={"af_start": [0.01, 0.02, 0.03], "af_max": [0.1, 0.2, 0.3]},
    ),
    IndicatorSpec(
        "parabolic_sar_direction", "trend_binary",
        param_choices={"af_start": [0.01, 0.02, 0.03], "af_max": [0.1, 0.2, 0.3]},
        literal_choices=[-1.0, 1.0],
    ),
    IndicatorSpec("aroon_up", "oscillator_0_100", param_ranges={"period": (10, 30)}, literal_range=(20.0, 80.0)),
    IndicatorSpec("aroon_down", "oscillator_0_100", param_ranges={"period": (10, 30)}, literal_range=(20.0, 80.0)),
    IndicatorSpec(
        "aroon_oscillator", "unitless_ratio", literal_range=(-100.0, 100.0), param_ranges={"period": (10, 30)},
    ),
    IndicatorSpec(
        "choppiness_index", "oscillator_0_100", param_ranges={"period": (10, 30)}, literal_range=(38.2, 61.8),
    ),
    IndicatorSpec(
        "keltner_upper", "price_level", allow_indicator_pair=True,
        param_ranges={"period": (10, 50), "atr_period": (7, 20)}, param_choices={"multiplier": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec(
        "keltner_middle", "price_level", allow_indicator_pair=True,
        param_ranges={"period": (10, 50), "atr_period": (7, 20)}, param_choices={"multiplier": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec(
        "keltner_lower", "price_level", allow_indicator_pair=True,
        param_ranges={"period": (10, 50), "atr_period": (7, 20)}, param_choices={"multiplier": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec("obv", "volatility", allow_indicator_pair=True),
    IndicatorSpec("ad_line", "volatility", allow_indicator_pair=True),
    IndicatorSpec("mfi", "oscillator_0_100", param_ranges={"period": (7, 30)}, literal_range=(20.0, 80.0)),
    IndicatorSpec("cmf", "unitless_ratio", literal_range=(-0.3, 0.3), param_ranges={"period": (10, 30)}),
    IndicatorSpec("woodie_pivot", "price_level", allow_indicator_pair=True),
    IndicatorSpec("woodie_r1", "price_level", allow_indicator_pair=True),
    IndicatorSpec("woodie_s1", "price_level", allow_indicator_pair=True),
    IndicatorSpec("woodie_r2", "price_level", allow_indicator_pair=True),
    IndicatorSpec("woodie_s2", "price_level", allow_indicator_pair=True),
    IndicatorSpec("camarilla_r1", "price_level", allow_indicator_pair=True),
    IndicatorSpec("camarilla_r2", "price_level", allow_indicator_pair=True),
    IndicatorSpec("camarilla_r3", "price_level", allow_indicator_pair=True),
    IndicatorSpec("camarilla_r4", "price_level", allow_indicator_pair=True),
    IndicatorSpec("camarilla_s1", "price_level", allow_indicator_pair=True),
    IndicatorSpec("camarilla_s2", "price_level", allow_indicator_pair=True),
    IndicatorSpec("camarilla_s3", "price_level", allow_indicator_pair=True),
    IndicatorSpec("camarilla_s4", "price_level", allow_indicator_pair=True),
    IndicatorSpec("fib_pivot", "price_level", allow_indicator_pair=True),
    IndicatorSpec("fib_pivot_r1", "price_level", allow_indicator_pair=True),
    IndicatorSpec("fib_pivot_r2", "price_level", allow_indicator_pair=True),
    IndicatorSpec("fib_pivot_r3", "price_level", allow_indicator_pair=True),
    IndicatorSpec("fib_pivot_s1", "price_level", allow_indicator_pair=True),
    IndicatorSpec("fib_pivot_s2", "price_level", allow_indicator_pair=True),
    IndicatorSpec("fib_pivot_s3", "price_level", allow_indicator_pair=True),
    IndicatorSpec(
        "ttm_squeeze", "boolean_signal", literal_choices=[1.0],
        param_ranges={"bb_period": (10, 30), "kc_period": (10, 30), "kc_atr_period": (7, 20)},
        param_choices={"bb_num_std": [1.5, 2.0, 2.5], "kc_multiplier": [1.0, 1.5, 2.0]},
    ),
    IndicatorSpec(
        "ttm_squeeze_release", "boolean_signal", literal_choices=[1.0],
        param_ranges={"bb_period": (10, 30), "kc_period": (10, 30), "kc_atr_period": (7, 20)},
        param_choices={"bb_num_std": [1.5, 2.0, 2.5], "kc_multiplier": [1.0, 1.5, 2.0]},
    ),
    IndicatorSpec(
        "ichimoku_price_vs_cloud", "trend_binary",
        param_ranges={"tenkan_period": (5, 15), "kijun_period": (20, 35), "senkou_b_period": (40, 65)},
        literal_choices=[-1.0, 0.0, 1.0],
    ),
    IndicatorSpec(
        "ichimoku_kumo_twist_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"tenkan_period": (5, 15), "kijun_period": (20, 35), "senkou_b_period": (40, 65)},
    ),
    IndicatorSpec(
        "ichimoku_kumo_twist_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"tenkan_period": (5, 15), "kijun_period": (20, 35), "senkou_b_period": (40, 65)},
    ),
    IndicatorSpec(
        "ichimoku_chikou_signal", "trend_binary",
        param_ranges={"kijun_period": (20, 35)}, literal_choices=[-1.0, 0.0, 1.0],
    ),
    IndicatorSpec(
        "linreg_slope_atr_ratio", "unitless_ratio", literal_range=(-2.0, 2.0),
        param_ranges={"length": (10, 50), "atr_length": (7, 20)},
    ),
    IndicatorSpec(
        "linreg_angle_degrees", "unitless_ratio", literal_range=(-45.0, 45.0),
        param_ranges={"length": (10, 50), "atr_length": (7, 20)},
    ),
    IndicatorSpec("linreg_value", "price_level", allow_indicator_pair=True, param_ranges={"length": (10, 50)}),
    IndicatorSpec(
        "linreg_upper", "price_level", allow_indicator_pair=True,
        param_ranges={"length": (10, 50)}, param_choices={"num_std": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec(
        "linreg_lower", "price_level", allow_indicator_pair=True,
        param_ranges={"length": (10, 50)}, param_choices={"num_std": [1.5, 2.0, 2.5]},
    ),
    IndicatorSpec("ha_bullish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("ha_bearish", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec(
        "ha_strong_bullish", "boolean_signal", literal_choices=[1.0],
        param_choices={"threshold": [0.02, 0.05, 0.1]},
    ),
    IndicatorSpec(
        "ha_strong_bearish", "boolean_signal", literal_choices=[1.0],
        param_choices={"threshold": [0.02, 0.05, 0.1]},
    ),
    IndicatorSpec(
        "gartley_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec(
        "gartley_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec(
        "bat_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec(
        "bat_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec(
        "butterfly_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec(
        "butterfly_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec(
        "crab_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.05, 0.1, 0.15]},
    ),
    IndicatorSpec(
        "crab_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.05, 0.1, 0.15]},
    ),
])

# ---------------------------------------------------------------------------
# 2026-07-08追加(4巡目): プライスアクション系 - トレンドラインブレイク/
# 平行チャネル/フェイクブレイク/NR4-NR7/出来高クライマックス/AB=CD/
# スリードライブ - 14 new indicators.
# ---------------------------------------------------------------------------
INDICATOR_POOL.extend([
    IndicatorSpec(
        "uptrend_line_break", "boolean_signal", literal_choices=[1.0], param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "downtrend_line_break", "boolean_signal", literal_choices=[1.0], param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "ascending_channel_break", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)}, param_choices={"slope_tolerance_atr_mult": [0.01, 0.02, 0.05]},
    ),
    IndicatorSpec(
        "descending_channel_break", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)}, param_choices={"slope_tolerance_atr_mult": [0.01, 0.02, 0.05]},
    ),
    IndicatorSpec(
        "false_breakout_bullish_reversal", "boolean_signal", literal_choices=[1.0],
        param_ranges={"window": (10, 40), "max_bars_outside": (1, 5)},
        param_choices={"box_atr_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "false_breakout_bearish_reversal", "boolean_signal", literal_choices=[1.0],
        param_ranges={"window": (10, 40), "max_bars_outside": (1, 5)},
        param_choices={"box_atr_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec("nr4", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec("nr7", "boolean_signal", literal_choices=[1.0]),
    IndicatorSpec(
        "volume_climax_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (10, 40)}, param_choices={"body_mult": [1.5, 2.0, 2.5, 3.0], "volume_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "volume_climax_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (10, 40)}, param_choices={"body_mult": [1.5, 2.0, 2.5, 3.0], "volume_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "ab_cd_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.1, 0.15, 0.2]},
    ),
    IndicatorSpec(
        "ab_cd_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.1, 0.15, 0.2]},
    ),
    IndicatorSpec(
        "three_drives_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.1, 0.15, 0.2]},
    ),
    IndicatorSpec(
        "three_drives_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"lookback": (3, 10)}, param_choices={"tolerance": [0.1, 0.15, 0.2]},
    ),
])


# ---------------------------------------------------------------------------
# 2026-07-08追加(5巡目、HFM記事の未実装分): ソーサートップ/ボトム、上昇/下降
# レクタングル、ブロードニングフォーメーション、ダイヤモンドフォーメーション、
# カップウィズハンドル - 9 new indicators.
# ---------------------------------------------------------------------------
INDICATOR_POOL.extend([
    IndicatorSpec("saucer_top", "boolean_signal", literal_choices=[1.0], param_ranges={"window": (20, 50)}),
    IndicatorSpec("saucer_bottom", "boolean_signal", literal_choices=[1.0], param_ranges={"window": (20, 50)}),
    IndicatorSpec(
        "ascending_rectangle_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"window": (10, 40), "trend_lookback": (15, 50)},
        param_choices={"box_atr_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "descending_rectangle_breakdown", "boolean_signal", literal_choices=[1.0],
        param_ranges={"window": (10, 40), "trend_lookback": (15, 50)},
        param_choices={"box_atr_mult": [1.5, 2.0, 2.5, 3.0]},
    ),
    IndicatorSpec(
        "broadening_formation_breakout_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "broadening_formation_breakout_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "diamond_formation_breakout_bullish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "diamond_formation_breakout_bearish", "boolean_signal", literal_choices=[1.0],
        param_ranges={"swing_lookback": (3, 10)},
    ),
    IndicatorSpec(
        "cup_with_handle_breakout", "boolean_signal", literal_choices=[1.0],
        param_ranges={"cup_window": (25, 60), "handle_window": (5, 20)},
        param_choices={"handle_atr_mult": [1.0, 1.5, 2.0]},
    ),
])


def pool_by_kind(pool: list[IndicatorSpec] = INDICATOR_POOL) -> dict[str, list[IndicatorSpec]]:
    grouped: dict[str, list[IndicatorSpec]] = {}
    for spec in pool:
        grouped.setdefault(spec.kind, []).append(spec)
    return grouped
