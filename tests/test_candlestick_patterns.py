"""Unit tests for engine/candlestick_patterns.py - hand-built synthetic OHLC
sequences where the expected answer is known by construction (there's no
external reference like TradingView to check pattern definitions against,
same situation as engine/smc_indicators.py).

Not pytest-based (matches this project's tests/test_conditions.py
convention) - run directly: `python tests/test_candlestick_patterns.py`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import engine.candlestick_patterns as cdl


def _make_df(bars: list[dict]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(bars), freq="15min")
    df = pd.DataFrame(bars)
    df.insert(0, "datetime", dates)
    return df


def _check(label: str, condition: bool) -> str | None:
    if condition:
        return None
    return f"FAIL: {label}"


def test_single_candle_basics() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0},  # bullish
            {"open": 105.0, "high": 106.0, "low": 99.0, "close": 100.0},  # bearish
        ]
    )
    bullish = cdl.bullish_candle(df["open"], df["close"])
    bearish = cdl.bearish_candle(df["open"], df["close"])
    failures.append(_check("bullish_candle true on bar 0", bool(bullish.iloc[0])))
    failures.append(_check("bullish_candle false on bar 1", not bullish.iloc[1]))
    failures.append(_check("bearish_candle true on bar 1", bool(bearish.iloc[1])))
    failures.append(_check("bearish_candle false on bar 0", not bearish.iloc[0]))
    return [f for f in failures if f]


def test_doji_and_marubozu() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 100.0, "high": 110.0, "low": 90.0, "close": 100.5},  # doji: tiny body, big range
            {"open": 100.0, "high": 110.0, "low": 100.0, "close": 110.0},  # bullish marubozu: full body, no wicks
            {"open": 100.0, "high": 100.0, "low": 90.0, "close": 90.0},  # bearish marubozu
        ]
    )
    is_doji = cdl.doji(df["open"], df["high"], df["low"], df["close"])
    marubozu_bull = cdl.marubozu_bullish(df["open"], df["high"], df["low"], df["close"])
    marubozu_bear = cdl.marubozu_bearish(df["open"], df["high"], df["low"], df["close"])

    failures.append(_check("doji fires on tiny-body bar", bool(is_doji.iloc[0])))
    failures.append(_check("doji does not fire on marubozu bar", not is_doji.iloc[1]))
    failures.append(_check("marubozu_bullish fires on bar 1", bool(marubozu_bull.iloc[1])))
    failures.append(_check("marubozu_bearish fires on bar 2", bool(marubozu_bear.iloc[2])))
    failures.append(_check("marubozu_bullish false on bearish bar", not marubozu_bull.iloc[2]))
    return [f for f in failures if f]


def test_wick_conditions() -> list[str]:
    failures = []
    df = _make_df(
        [
            # long upper wick: small body near the bottom, big upper wick
            {"open": 100.0, "high": 110.0, "low": 99.0, "close": 101.0},
            # long lower wick: small body near the top, big lower wick
            {"open": 109.0, "high": 110.0, "low": 99.0, "close": 110.0},
            # marubozu-like: no wicks at all
            {"open": 100.0, "high": 110.0, "low": 100.0, "close": 110.0},
        ]
    )
    long_upper = cdl.long_upper_wick(df["open"], df["high"], df["low"], df["close"], wick_ratio_threshold=0.5)
    long_lower = cdl.long_lower_wick(df["open"], df["high"], df["low"], df["close"], wick_ratio_threshold=0.5)
    no_upper = cdl.no_upper_wick(df["open"], df["high"], df["low"], df["close"], threshold=0.05)
    no_lower = cdl.no_lower_wick(df["open"], df["high"], df["low"], df["close"], threshold=0.05)

    failures.append(_check("long_upper_wick fires on bar 0", bool(long_upper.iloc[0])))
    failures.append(_check("long_upper_wick false on bar 1", not long_upper.iloc[1]))
    failures.append(_check("long_lower_wick fires on bar 1", bool(long_lower.iloc[1])))
    failures.append(_check("no_upper_wick fires on marubozu bar 2", bool(no_upper.iloc[2])))
    failures.append(_check("no_lower_wick fires on marubozu bar 2", bool(no_lower.iloc[2])))
    return [f for f in failures if f]


def test_hammer_family() -> list[str]:
    failures = []
    df = _make_df(
        [
            # hammer/hanging_man shape: small body near top, long lower wick, tiny upper wick
            {"open": 108.0, "high": 109.0, "low": 100.0, "close": 109.0},
            # inverted_hammer/shooting_star shape: small body near bottom, long upper wick, tiny lower wick
            {"open": 100.0, "high": 109.0, "low": 100.0, "close": 101.0},
            # neither: a plain large-range marubozu (body fills the whole range)
            {"open": 100.0, "high": 109.0, "low": 100.0, "close": 109.0},
        ]
    )
    hammer = cdl.hammer_shape(df["open"], df["high"], df["low"], df["close"])
    inv_hammer = cdl.inverted_hammer_shape(df["open"], df["high"], df["low"], df["close"])

    failures.append(_check("hammer_shape fires on bar 0", bool(hammer.iloc[0])))
    failures.append(_check("hammer_shape false on bar 1 (wrong wick side)", not hammer.iloc[1]))
    failures.append(_check("inverted_hammer_shape fires on bar 1", bool(inv_hammer.iloc[1])))
    failures.append(_check("inverted_hammer_shape false on bar 0", not inv_hammer.iloc[0]))
    failures.append(_check("hammer_shape false on marubozu bar 2 (body too big)", not hammer.iloc[2]))
    return [f for f in failures if f]


def test_pin_bars() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 108.0, "high": 109.0, "low": 100.0, "close": 108.5},  # long lower wick -> bullish pin bar
            {"open": 101.0, "high": 109.0, "low": 100.0, "close": 100.5},  # long upper wick -> bearish pin bar
        ]
    )
    pin_bull = cdl.pin_bar_bullish(df["open"], df["high"], df["low"], df["close"])
    pin_bear = cdl.pin_bar_bearish(df["open"], df["high"], df["low"], df["close"])

    failures.append(_check("pin_bar_bullish fires on long-lower-wick bar", bool(pin_bull.iloc[0])))
    failures.append(_check("pin_bar_bullish false on long-upper-wick bar", not pin_bull.iloc[1]))
    failures.append(_check("pin_bar_bearish fires on long-upper-wick bar", bool(pin_bear.iloc[1])))
    failures.append(_check("pin_bar_bearish false on long-lower-wick bar", not pin_bear.iloc[0]))
    return [f for f in failures if f]


def test_engulfing() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 105.0, "high": 106.0, "low": 99.0, "close": 100.0},  # bearish
            {"open": 99.0, "high": 107.0, "low": 98.0, "close": 106.0},  # bullish, engulfs bar 0's body
            {"open": 107.0, "high": 108.0, "low": 97.0, "close": 98.0},  # bearish, engulfs bar 1's body
        ]
    )
    engulf_bull = cdl.engulfing_bullish(df["open"], df["close"])
    engulf_bear = cdl.engulfing_bearish(df["open"], df["close"])

    failures.append(_check("engulfing_bullish fires on bar 1", bool(engulf_bull.iloc[1])))
    failures.append(_check("engulfing_bearish fires on bar 2", bool(engulf_bear.iloc[2])))
    failures.append(_check("engulfing_bullish false on bar 0 (no prior bar)", not engulf_bull.iloc[0]))
    return [f for f in failures if f]


def test_inside_outside_bar() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0},
            {"open": 102.0, "high": 106.0, "low": 95.0, "close": 103.0},  # fully inside bar 0's range
            {"open": 96.0, "high": 112.0, "low": 88.0, "close": 100.0},  # fully engulfs bar 1's range
        ]
    )
    inside = cdl.inside_bar(df["high"], df["low"])
    outside = cdl.outside_bar(df["high"], df["low"])

    failures.append(_check("inside_bar fires on bar 1", bool(inside.iloc[1])))
    failures.append(_check("outside_bar fires on bar 2", bool(outside.iloc[2])))
    failures.append(_check("inside_bar false on bar 2", not inside.iloc[2]))
    failures.append(_check("outside_bar false on bar 1", not outside.iloc[1]))
    return [f for f in failures if f]


def test_tweezers() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 100.0, "high": 110.0, "low": 99.0, "close": 109.0},  # bullish, sets the high
            {"open": 109.0, "high": 110.1, "low": 100.0, "close": 101.0},  # bearish, matching high -> tweezer top
            {"open": 100.0, "high": 101.0, "low": 90.0, "close": 91.0},  # bearish, sets the low
            {"open": 91.0, "high": 100.0, "low": 89.9, "close": 99.0},  # bullish, matching low -> tweezer bottom
        ]
    )
    top = cdl.tweezer_top(df["open"], df["high"], df["low"], df["close"])
    bottom = cdl.tweezer_bottom(df["open"], df["high"], df["low"], df["close"])

    failures.append(_check("tweezer_top fires on bar 1", bool(top.iloc[1])))
    failures.append(_check("tweezer_bottom fires on bar 3", bool(bottom.iloc[3])))
    return [f for f in failures if f]


def test_harami() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 110.0, "high": 111.0, "low": 99.0, "close": 100.0},  # large bearish
            {"open": 103.0, "high": 104.0, "low": 102.0, "close": 104.0},  # small bullish, inside bar 0's body
            {"open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0},  # large bullish
            {"open": 107.0, "high": 108.0, "low": 106.0, "close": 106.0},  # small bearish, inside bar 2's body
        ]
    )
    harami_bull = cdl.harami_bullish(df["open"], df["close"])
    harami_bear = cdl.harami_bearish(df["open"], df["close"])

    failures.append(_check("harami_bullish fires on bar 1", bool(harami_bull.iloc[1])))
    failures.append(_check("harami_bearish fires on bar 3", bool(harami_bear.iloc[3])))
    return [f for f in failures if f]


def test_gaps() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0},
            {"open": 108.0, "high": 112.0, "low": 107.0, "close": 110.0},  # gaps up above bar 0's high
            {"open": 100.0, "high": 105.0, "low": 90.0, "close": 95.0},  # gaps down below bar 1's low
        ]
    )
    up = cdl.gap_up(df["open"], df["high"])
    down = cdl.gap_down(df["open"], df["low"])

    failures.append(_check("gap_up fires on bar 1", bool(up.iloc[1])))
    failures.append(_check("gap_down fires on bar 2", bool(down.iloc[2])))
    failures.append(_check("gap_up false on bar 0", not up.iloc[0]))
    return [f for f in failures if f]


def test_three_candle_patterns() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 110.0, "high": 111.0, "low": 99.0, "close": 100.0},  # large bearish (c1 for morning star)
            {"open": 99.0, "high": 100.0, "low": 97.0, "close": 99.5},  # small body, gaps down (c2)
            {"open": 100.0, "high": 108.0, "low": 99.0, "close": 107.0},  # large bullish closing above c1 mid (c3)
        ]
    )
    morning = cdl.morning_star(df["open"], df["high"], df["low"], df["close"])
    failures.append(_check("morning_star fires on bar 2", bool(morning.iloc[2])))

    df2 = _make_df(
        [
            {"open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0},  # large bullish (c1 for evening star)
            {"open": 111.0, "high": 113.0, "low": 110.5, "close": 111.5},  # small body, gaps up (c2)
            {"open": 110.0, "high": 111.0, "low": 102.0, "close": 103.0},  # large bearish closing below c1 mid (c3)
        ]
    )
    evening = cdl.evening_star(df2["open"], df2["high"], df2["low"], df2["close"])
    failures.append(_check("evening_star fires on bar 2", bool(evening.iloc[2])))

    df3 = _make_df(
        [
            {"open": 100.0, "high": 103.0, "low": 99.5, "close": 102.5},
            {"open": 101.5, "high": 105.5, "low": 101.0, "close": 105.0},
            {"open": 103.0, "high": 108.0, "low": 102.5, "close": 107.5},
        ]
    )
    soldiers = cdl.three_white_soldiers(df3["open"], df3["high"], df3["low"], df3["close"])
    failures.append(_check("three_white_soldiers fires on bar 2", bool(soldiers.iloc[2])))

    df4 = _make_df(
        [
            {"open": 108.5, "high": 109.0, "low": 105.0, "close": 105.5},
            {"open": 107.0, "high": 107.5, "low": 102.0, "close": 102.5},
            {"open": 104.5, "high": 105.0, "low": 98.5, "close": 99.0},
        ]
    )
    crows = cdl.three_black_crows(df4["open"], df4["high"], df4["low"], df4["close"])
    failures.append(_check("three_black_crows fires on bar 2", bool(crows.iloc[2])))

    return [f for f in failures if f]


def test_three_methods() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 100.0, "high": 110.0, "low": 99.0, "close": 109.0},  # c1: large bullish
            {"open": 108.0, "high": 108.5, "low": 105.0, "close": 106.0},  # c2..c4: small, inside c1's range
            {"open": 106.0, "high": 107.0, "low": 104.0, "close": 105.0},
            {"open": 105.0, "high": 106.5, "low": 103.5, "close": 104.5},
            {"open": 104.5, "high": 115.0, "low": 104.0, "close": 114.0},  # c5: large bullish, new high
        ]
    )
    rising = cdl.rising_three_methods(df["open"], df["high"], df["low"], df["close"])
    failures.append(_check("rising_three_methods fires on bar 4", bool(rising.iloc[4])))

    df2 = _make_df(
        [
            {"open": 110.0, "high": 111.0, "low": 100.0, "close": 101.0},  # c1: large bearish
            {"open": 102.0, "high": 105.0, "low": 101.5, "close": 104.0},  # c2..c4: small, inside c1's range
            {"open": 104.0, "high": 106.0, "low": 103.0, "close": 105.0},
            {"open": 105.0, "high": 106.5, "low": 103.5, "close": 104.5},
            {"open": 104.5, "high": 105.0, "low": 94.0, "close": 95.0},  # c5: large bearish, new low
        ]
    )
    falling = cdl.falling_three_methods(df2["open"], df2["high"], df2["low"], df2["close"])
    failures.append(_check("falling_three_methods fires on bar 4", bool(falling.iloc[4])))

    return [f for f in failures if f]


def test_consecutive_and_ratio_conditions() -> list[str]:
    failures = []
    df = _make_df(
        [
            {"open": 99.0, "high": 100.0, "low": 98.5, "close": 99.5},  # baseline (only used for the shift(1) compare)
            {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.8},
            {"open": 100.8, "high": 102.0, "low": 100.5, "close": 101.8},
            {"open": 101.8, "high": 103.0, "low": 101.5, "close": 102.8},
            {"open": 102.8, "high": 102.9, "low": 100.0, "close": 101.0},  # breaks the streak
        ]
    )
    bull_streak = cdl.consecutive_bullish_candles(df["open"], df["close"], n=3)
    higher_highs = cdl.consecutive_higher_highs(df["high"], n=3)

    failures.append(_check("consecutive_bullish_candles fires on bar 3 (3rd bullish bar in a row)", bool(bull_streak.iloc[3])))
    failures.append(_check("consecutive_bullish_candles false on bar 4 (streak broken)", not bull_streak.iloc[4]))
    failures.append(_check("consecutive_higher_highs fires on bar 3", bool(higher_highs.iloc[3])))

    ratio_df = _make_df(
        [
            {"open": 100.0, "high": 110.0, "low": 99.0, "close": 109.0},  # body 9/10 = 90%
        ]
    )
    body_ratio = cdl.body_ratio_at_least(
        ratio_df["open"], ratio_df["high"], ratio_df["low"], ratio_df["close"], threshold_pct=80.0
    )
    wick_ratio = cdl.wick_ratio_at_least(
        ratio_df["open"], ratio_df["high"], ratio_df["low"], ratio_df["close"], threshold_pct=80.0
    )
    failures.append(_check("body_ratio_at_least(80%) fires on a 90%-body bar", bool(body_ratio.iloc[0])))
    failures.append(_check("wick_ratio_at_least(80%) false on a 90%-body bar", not wick_ratio.iloc[0]))

    return [f for f in failures if f]


def main() -> None:
    test_fns = [
        test_single_candle_basics,
        test_doji_and_marubozu,
        test_wick_conditions,
        test_hammer_family,
        test_pin_bars,
        test_engulfing,
        test_inside_outside_bar,
        test_tweezers,
        test_harami,
        test_gaps,
        test_three_candle_patterns,
        test_three_methods,
        test_consecutive_and_ratio_conditions,
    ]

    all_failures: list[str] = []
    for fn in test_fns:
        failures = fn()
        if failures:
            all_failures.extend(failures)
        else:
            print(f"PASS: {fn.__name__}")

    if all_failures:
        print("FAIL")
        for f in all_failures:
            print(f"  {f}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
