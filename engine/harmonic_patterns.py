"""Harmonic patterns (Gartley, Bat, Butterfly, Crab) - 5-point X-A-B-C-D
structures defined by specific Fibonacci retracement/extension ratios
between consecutive legs, popular specifically among FX traders.

Built on top of engine/smc_indicators.py's swing-high/low detection (same
foundation as engine/chart_patterns.py), extended to track the last FIVE
confirmed swing points in chronological order REGARDLESS of whether each
one is a high or a low (a double top only ever needed "the last two swing
highs"; a harmonic pattern needs the whole alternating high-low-high-low-
high sequence). Swing highs and swing lows are detected independently by
smc_indicators.py's existing machinery, then merged and sorted by
confirmation bar to reconstruct that combined sequence.

Like engine/chart_patterns.py, this is a deliberately simplified/
approximate implementation - real harmonic-pattern scanners also check the
overall symmetry/time-relationship between legs, which this does not; only
the price ratios are checked here. Not verified against any reference
charting platform - same "exploratory" caveat as every other pattern-
recognition module in this project.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.smc_indicators import _confirmed_swing_level_series, _detect_swing_highs, _detect_swing_lows


def _merged_swing_events(high: pd.Series, low: pd.Series, lookback: int) -> pd.DataFrame:
    """One row per confirmed swing point (high OR low), sorted
    chronologically by confirmation bar (kept as a plain "bar" column,
    NOT the row index - a swing high and a swing low can occasionally be
    confirmed on the exact same bar, which would make that bar a
    duplicate/ambiguous index label) - the "X/A/B/C/D candidate" sequence
    every harmonic pattern check reads its last 5 entries from."""
    high_flags = _detect_swing_highs(high, lookback)
    high_levels = _confirmed_swing_level_series(high_flags, high, lookback).dropna()
    low_flags = _detect_swing_lows(low, lookback)
    low_levels = _confirmed_swing_level_series(low_flags, low, lookback).dropna()

    events = pd.concat([
        pd.DataFrame({"bar": high_levels.index, "level": high_levels.to_numpy(), "is_high": True}),
        pd.DataFrame({"bar": low_levels.index, "level": low_levels.to_numpy(), "is_high": False}),
    ]).sort_values("bar").reset_index(drop=True)
    return events


def _nth_back(events: pd.DataFrame, n: int, column: str, full_length: int) -> pd.Series:
    shifted = events[column].shift(n)
    result = np.full(full_length, np.nan)
    bars = events["bar"].to_numpy()
    values = shifted.to_numpy()
    valid = ~pd.isna(values)
    # Fancy-indexing assignment tolerates duplicate `bars` values (a high
    # and low confirmed on the same bar) - last write wins, which is fine
    # since which of the two "wins" for a same-bar tie doesn't materially
    # change the pattern check.
    result[bars[valid].astype(int)] = values[valid]
    return pd.Series(result).ffill()


def _harmonic_points(high: pd.Series, low: pd.Series, lookback: int) -> dict[str, pd.Series]:
    events = _merged_swing_events(high, low, lookback)
    full_length = len(high)
    bar_position = pd.Series(np.arange(full_length))

    points = {}
    for label, n in zip(("d", "c", "b", "a", "x"), (0, 1, 2, 3, 4)):
        points[f"{label}_level"] = _nth_back(events, n, "level", full_length)
        points[f"{label}_is_high"] = _nth_back(events, n, "is_high", full_length) > 0

    d_bar_series = _nth_back(events, 0, "bar", full_length)
    points["d_just_confirmed"] = bar_position == d_bar_series
    return points


def _within(ratio: pd.Series, low: float, high: float, tolerance: float) -> pd.Series:
    return (ratio >= low - tolerance) & (ratio <= high + tolerance)


def _harmonic_pattern(
    high: pd.Series, low: pd.Series, is_bullish: bool,
    ab_xa_range: tuple[float, float], d_xa_range: tuple[float, float],
    lookback: int, tolerance: float,
    bc_ab_range: tuple[float, float] = (0.30, 0.95),
    # Wide on purpose: cd_bc isn't actually an independent parameter once
    # ab_xa/bc_ab/d_xa are all fixed (given real, non-idealized swing
    # points, whatever CD needs to be to land D at its target retracement
    # of XA is whatever it is) - a tight range here rejects genuine
    # patterns whose BC leg happened to be short relative to a deep D
    # extension (this is exactly how the Crab pattern's synthetic test
    # case, a legitimate exact-1.618 Crab, first failed: its arithmetic
    # required a ~5.5x CD/BC extension, comfortably outside a naively
    # "reasonable-looking" (1.0, 4.0) range). This stays as a loose sanity
    # check (CD must at least be an extension, not a contraction) rather
    # than a real per-pattern discriminator.
    cd_bc_range: tuple[float, float] = (1.00, 8.00),
) -> np.ndarray:
    pts = _harmonic_points(high, low, lookback)
    x, a, b, c, d = pts["x_level"], pts["a_level"], pts["b_level"], pts["c_level"], pts["d_level"]

    if is_bullish:
        # X low -> A high -> B low -> C high -> D low.
        alternating = (
            ~pts["x_is_high"] & pts["a_is_high"] & ~pts["b_is_high"] & pts["c_is_high"] & ~pts["d_is_high"]
        )
        xa = a - x
        ab = a - b
        bc = c - b
        cd = c - d
        d_retrace = (a - d) / xa
    else:
        # X high -> A low -> B high -> C low -> D high (mirror image).
        alternating = (
            pts["x_is_high"] & ~pts["a_is_high"] & pts["b_is_high"] & ~pts["c_is_high"] & pts["d_is_high"]
        )
        xa = x - a
        ab = b - a
        bc = b - c
        cd = d - c
        d_retrace = (d - a) / xa

    with np.errstate(divide="ignore", invalid="ignore"):
        ab_xa = ab / xa
        bc_ab = bc / ab
        cd_bc = cd / bc

    valid_legs = (xa > 0) & (ab > 0) & (bc > 0) & (cd > 0)
    ratios_match = (
        _within(ab_xa, *ab_xa_range, tolerance)
        & _within(bc_ab, *bc_ab_range, tolerance)
        & _within(cd_bc, *cd_bc_range, tolerance)
        & _within(d_retrace, *d_xa_range, tolerance)
    )

    fired = pts["d_just_confirmed"] & alternating & valid_legs & ratios_match
    return fired.fillna(False).to_numpy(dtype=float)


def gartley_bullish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.1, **p) -> np.ndarray:
    return _harmonic_pattern(high, low, True, (0.55, 0.68), (0.70, 0.85), lookback, tolerance)


def gartley_bearish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.1, **p) -> np.ndarray:
    return _harmonic_pattern(high, low, False, (0.55, 0.68), (0.70, 0.85), lookback, tolerance)


def bat_bullish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.1, **p) -> np.ndarray:
    return _harmonic_pattern(high, low, True, (0.35, 0.55), (0.82, 0.93), lookback, tolerance)


def bat_bearish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.1, **p) -> np.ndarray:
    return _harmonic_pattern(high, low, False, (0.35, 0.55), (0.82, 0.93), lookback, tolerance)


def butterfly_bullish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.1, **p) -> np.ndarray:
    return _harmonic_pattern(high, low, True, (0.72, 0.85), (1.13, 1.71), lookback, tolerance)


def butterfly_bearish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.1, **p) -> np.ndarray:
    return _harmonic_pattern(high, low, False, (0.72, 0.85), (1.13, 1.71), lookback, tolerance)


def crab_bullish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.1, **p) -> np.ndarray:
    return _harmonic_pattern(high, low, True, (0.35, 0.68), (1.50, 1.75), lookback, tolerance)


def crab_bearish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.1, **p) -> np.ndarray:
    return _harmonic_pattern(high, low, False, (0.35, 0.68), (1.50, 1.75), lookback, tolerance)


# ---------------------------------------------------------------------------
# AB=CD: the simplest harmonic shape - just 4 points (no X), where the
# defining feature is that the CD leg's length roughly equals the AB leg's
# (not a retracement-of-XA ratio like Gartley/Bat/Butterfly/Crab).
# ---------------------------------------------------------------------------

def _generic_points(high: pd.Series, low: pd.Series, lookback: int, count: int) -> dict[str, pd.Series]:
    """Same idea as _harmonic_points, generalized to however many trailing
    swing points (`count`) a pattern needs (5 for the X-A-B-C-D harmonics
    above, 4 for AB=CD, 6 for Three Drives)."""
    events = _merged_swing_events(high, low, lookback)
    full_length = len(high)
    bar_position = pd.Series(np.arange(full_length))

    points: dict[str, pd.Series] = {}
    labels = [chr(ord("a") + count - 1 - i) for i in range(count)]  # count=4 -> d,c,b,a
    for label, n in zip(labels, range(count)):
        points[f"{label}_level"] = _nth_back(events, n, "level", full_length)
        points[f"{label}_is_high"] = _nth_back(events, n, "is_high", full_length) > 0

    last_bar_series = _nth_back(events, 0, "bar", full_length)
    points["last_just_confirmed"] = bar_position == last_bar_series
    return points


def ab_cd_bullish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.15, **p) -> np.ndarray:
    """A(high) -> B(low) -> C(high, retraces AB) -> D(low, CD leg roughly
    equals AB in length) - fires once, when D confirms."""
    pts = _generic_points(high, low, lookback, 4)
    a, b, c, d = pts["a_level"], pts["b_level"], pts["c_level"], pts["d_level"]

    alternating = pts["a_is_high"] & ~pts["b_is_high"] & pts["c_is_high"] & ~pts["d_is_high"]
    ab = a - b
    bc = c - b
    cd = c - d
    valid = (ab > 0) & (bc > 0) & (cd > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        bc_ab = bc / ab
        cd_ab = cd / ab
    ratios_match = _within(bc_ab, 0.382, 0.886, tolerance) & _within(cd_ab, 0.85, 1.15, tolerance)

    fired = pts["last_just_confirmed"] & alternating & valid & ratios_match
    return fired.fillna(False).to_numpy(dtype=float)


def ab_cd_bearish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.15, **p) -> np.ndarray:
    """Mirror image of ab_cd_bullish: A(low) -> B(high) -> C(low) ->
    D(high). Every leg here is a plain magnitude (higher point minus
    lower point), so - unlike the X-A-B-C-D harmonics' signed D-
    retracement-of-XA ratio - this mirrors safely without needing the
    negation-based re-derivation that caught the sign bug in
    _harmonic_pattern's bearish branch."""
    pts = _generic_points(high, low, lookback, 4)
    a, b, c, d = pts["a_level"], pts["b_level"], pts["c_level"], pts["d_level"]

    alternating = ~pts["a_is_high"] & pts["b_is_high"] & ~pts["c_is_high"] & pts["d_is_high"]
    ab = b - a
    bc = b - c
    cd = d - c
    valid = (ab > 0) & (bc > 0) & (cd > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        bc_ab = bc / ab
        cd_ab = cd / ab
    ratios_match = _within(bc_ab, 0.382, 0.886, tolerance) & _within(cd_ab, 0.85, 1.15, tolerance)

    fired = pts["last_just_confirmed"] & alternating & valid & ratios_match
    return fired.fillna(False).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Three Drives: three consecutive pushes to a new extreme, each drive
# extending the prior correction by a Fibonacci ratio, each correction
# retracing the prior drive by a Fibonacci ratio - 6 points total (one more
# than the X-A-B-C-D harmonics above).
# ---------------------------------------------------------------------------

def _three_drives(high: pd.Series, low: pd.Series, is_bearish: bool, lookback: int, tolerance: float) -> np.ndarray:
    pts = _generic_points(high, low, lookback, 6)
    # Labelled p0 (oldest) .. p5 (most recent/newest = the 3rd drive's peak/trough).
    p0, p1, p2, p3, p4, p5 = (pts[f"{l}_level"] for l in "abcdef")
    p0h, p1h, p2h, p3h, p4h, p5h = (pts[f"{l}_is_high"] for l in "abcdef")

    if is_bearish:
        # p0 low -> p1 high(drive1) -> p2 low(correction1) -> p3 high(drive2)
        # -> p4 low(correction2) -> p5 high(drive3).
        alternating = ~p0h & p1h & ~p2h & p3h & ~p4h & p5h
        drive1 = p1 - p0
        correction1 = p1 - p2
        drive2 = p3 - p2
        correction2 = p3 - p4
        drive3 = p5 - p4
        ascending = (p2 > p0) & (p3 > p1) & (p4 > p2) & (p5 > p3)
    else:
        alternating = p0h & ~p1h & p2h & ~p3h & p4h & ~p5h
        drive1 = p0 - p1
        correction1 = p2 - p1
        drive2 = p2 - p3
        correction2 = p4 - p3
        drive3 = p4 - p5
        ascending = (p2 < p0) & (p3 < p1) & (p4 < p2) & (p5 < p3)

    valid = (drive1 > 0) & (correction1 > 0) & (drive2 > 0) & (correction2 > 0) & (drive3 > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        correction1_ratio = correction1 / drive1
        drive2_ratio = drive2 / correction1
        correction2_ratio = correction2 / drive2
        drive3_ratio = drive3 / correction2

    ratios_match = (
        _within(correction1_ratio, 0.618, 0.786, tolerance)
        & _within(drive2_ratio, 1.13, 1.618, tolerance)
        & _within(correction2_ratio, 0.618, 0.786, tolerance)
        & _within(drive3_ratio, 1.13, 1.618, tolerance)
    )

    fired = pts["last_just_confirmed"] & alternating & ascending & valid & ratios_match
    return fired.fillna(False).to_numpy(dtype=float)


def three_drives_bullish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.15, **p) -> np.ndarray:
    """Three descending drives (lower lows) each retraced by a
    Fibonacci-ratio correction - exhaustion signal, bullish reversal
    expected after the 3rd drive."""
    return _three_drives(high, low, False, lookback, tolerance)


def three_drives_bearish(high: pd.Series, low: pd.Series, lookback: int = 5, tolerance: float = 0.15, **p) -> np.ndarray:
    """Mirror image of three_drives_bullish: three ascending drives (higher
    highs), bearish reversal expected after the 3rd drive."""
    return _three_drives(high, low, True, lookback, tolerance)
