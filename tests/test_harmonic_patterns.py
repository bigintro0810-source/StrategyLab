"""Regression tests for engine/harmonic_patterns.py (Gartley/Bat/Butterfly/
Crab, added 2026-07-08). Plain-script style, matching this project's
convention - run directly with `python tests/test_harmonic_patterns.py`.

Hand-built synthetic X-A-B-C-D sequences using the EXACT textbook ratios
for each pattern - if the geometry/ratio math has a sign or scaling bug,
these are the checks that catch it (this is exactly how a real sign bug in
the bearish D-retracement formula was caught during implementation: the
bearish patterns fired ZERO times on real data while bullish fired
hundreds, which a symmetric-rate market has no reason to produce).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import engine.harmonic_patterns as hp

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


def _seg(a: float, b: float, n: int = 15) -> np.ndarray:
    return np.linspace(a, b, n)


def _build_bullish_xabcd(x: float, a: float, b: float, c: float, d: float) -> tuple[pd.Series, pd.Series]:
    closes = np.concatenate([
        _seg(x + 5, x, 12),
        _seg(x, a, 15),
        _seg(a, b, 15),
        _seg(b, c, 15),
        _seg(c, d, 15),
        _seg(d, d + 10, 15),
    ])
    return pd.Series(closes + 0.3), pd.Series(closes - 0.3)


def _build_bearish_xabcd(x: float, a: float, b: float, c: float, d: float) -> tuple[pd.Series, pd.Series]:
    closes = np.concatenate([
        _seg(x - 5, x, 12),
        _seg(x, a, 15),
        _seg(a, b, 15),
        _seg(b, c, 15),
        _seg(c, d, 15),
        _seg(d, d - 10, 15),
    ])
    return pd.Series(closes + 0.3), pd.Series(closes - 0.3)


def test_gartley_bullish_exact_ratios():
    x, a = 100.0, 200.0
    xa = a - x
    b = a - 0.618 * xa
    c = b + 0.5 * (a - b)
    d = a - 0.786 * xa
    high, low = _build_bullish_xabcd(x, a, b, c, d)
    result = hp.gartley_bullish(high, low, lookback=5, tolerance=0.1)
    check("gartley_bullish fires on an exact-ratio Gartley", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_gartley_bearish_exact_ratios():
    x, a = 200.0, 100.0
    xa = x - a
    b = a + 0.618 * xa
    c = b - 0.5 * (b - a)
    d = a + 0.786 * xa
    high, low = _build_bearish_xabcd(x, a, b, c, d)
    result = hp.gartley_bearish(high, low, lookback=5, tolerance=0.1)
    check("gartley_bearish fires on an exact-ratio Gartley (mirror image)", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_bat_bullish_exact_ratios():
    x, a = 100.0, 200.0
    xa = a - x
    b = a - 0.45 * xa
    c = b + 0.5 * (a - b)
    d = a - 0.886 * xa
    high, low = _build_bullish_xabcd(x, a, b, c, d)
    result = hp.bat_bullish(high, low, lookback=5, tolerance=0.1)
    check("bat_bullish fires on an exact-ratio Bat", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_butterfly_bullish_exact_ratios():
    x, a = 100.0, 200.0
    xa = a - x
    b = a - 0.786 * xa
    c = b + 0.5 * (a - b)
    d = a - 1.4 * xa  # extension beyond X, as butterfly requires
    high, low = _build_bullish_xabcd(x, a, b, c, d)
    result = hp.butterfly_bullish(high, low, lookback=5, tolerance=0.1)
    check("butterfly_bullish fires on an exact-ratio Butterfly", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_crab_bullish_exact_ratios():
    x, a = 100.0, 200.0
    xa = a - x
    b = a - 0.5 * xa
    c = b + 0.5 * (a - b)
    d = a - 1.618 * xa
    high, low = _build_bullish_xabcd(x, a, b, c, d)
    result = hp.crab_bullish(high, low, lookback=5, tolerance=0.1)
    check("crab_bullish fires on an exact-ratio Crab", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_gartley_bullish_rejects_wrong_ratios():
    # AB retraces only 0.2 of XA - nowhere near Gartley's 0.618 - must not fire.
    x, a = 100.0, 200.0
    xa = a - x
    b = a - 0.2 * xa
    c = b + 0.5 * (a - b)
    d = a - 0.786 * xa
    high, low = _build_bullish_xabcd(x, a, b, c, d)
    result = hp.gartley_bullish(high, low, lookback=5, tolerance=0.05)
    check("gartley_bullish does not fire when AB/XA is nowhere near 0.618", result.sum() == 0, detail=str(result.sum()))


def test_bullish_and_bearish_rates_are_roughly_symmetric_on_real_data():
    # Real regression-catcher: a sign bug in one direction's retracement
    # formula made bearish patterns fire ~0 times against bullish's
    # hundreds on the same real data, which a roughly-symmetric market has
    # no structural reason to produce.
    from engine.data_loader import find_data_file, load_price_data
    df = load_price_data(find_data_file("15m", "USDJPY"))
    high, low = df["high"], df["low"]

    for bullish_fn, bearish_fn, label in [
        (hp.gartley_bullish, hp.gartley_bearish, "gartley"),
        (hp.bat_bullish, hp.bat_bearish, "bat"),
        (hp.butterfly_bullish, hp.butterfly_bearish, "butterfly"),
        (hp.crab_bullish, hp.crab_bearish, "crab"),
    ]:
        bull_count = bullish_fn(high, low).sum()
        bear_count = bearish_fn(high, low).sum()
        check(
            f"{label}: bullish ({bull_count:.0f}) and bearish ({bear_count:.0f}) counts are both nonzero on real data",
            bull_count > 0 and bear_count > 0,
            detail=f"bull={bull_count} bear={bear_count}",
        )


if __name__ == "__main__":
    test_gartley_bullish_exact_ratios()
    test_gartley_bearish_exact_ratios()
    test_bat_bullish_exact_ratios()
    test_butterfly_bullish_exact_ratios()
    test_crab_bullish_exact_ratios()
    test_gartley_bullish_rejects_wrong_ratios()
    test_bullish_and_bearish_rates_are_roughly_symmetric_on_real_data()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll harmonic_patterns tests passed.")
