"""Unit tests for engine/conditions.py's generic AND/OR/NOT condition engine.

Not pytest-based (matches this project's other tests/test_*.py convention) - run
directly: `python tests/test_conditions.py`. Uses a small synthetic DataFrame (fast,
deterministic), not data/raw, since this tests the engine's own logic in isolation
from any real price data.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.conditions import Condition, ConditionGroup, node_from_dict


def _make_df(n: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="15min")
    close = pd.Series(np.linspace(100.0, 110.0, n))
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
        }
    )


def _check(label: str, condition: bool, detail: str = "") -> str | None:
    if condition:
        print(f"PASS: {label}")
        return None
    return f"FAIL: {label} {detail}"


def test_operators() -> list[str]:
    df = _make_df()
    close = df["close"].to_numpy()
    failures = []

    for op, expected in [
        (">", close > 105.0),
        ("<", close < 105.0),
        (">=", close >= close[10]),
        ("<=", close <= close[10]),
        ("==", close == close[10]),
    ]:
        result = Condition(indicator="close", operator=op, value=float(close[10]) if op in (">=", "<=", "==") else 105.0).evaluate(df, {})
        failure = _check(f"operator {op}", (result == expected).all())
        if failure:
            failures.append(failure)

    return failures


def test_crosses_above_below() -> list[str]:
    df = _make_df()
    cache: dict = {}

    above = Condition(indicator="close", operator="crosses_above", value=105.0).evaluate(df, cache)
    below = Condition(indicator="close", operator="crosses_below", value=105.0).evaluate(df, cache)

    # Bar 0 has no true "previous bar", so - matching engine/triggers.py's existing
    # _crossed_above convention that this mirrors - a condition already true at bar 0
    # always counts as a "cross" there (there's nothing to compare against). For this
    # monotonically increasing series: crosses_above(105) fires once mid-series;
    # crosses_below(105) fires once, at bar 0 only (close starts below 105, then only
    # ever increases, so it's never "below" again after leaving that zone).
    failures = []
    failures += [f for f in [_check("crosses_above fires exactly once (monotonic series)", above.sum() == 1)] if f]
    failures += [
        f
        for f in [
            _check(
                "crosses_below fires exactly once, at bar 0, then never again (monotonic increasing series)",
                below.sum() == 1 and bool(below[0]),
            )
        ]
        if f
    ]
    return failures


def test_indicator_vs_indicator() -> list[str]:
    df = _make_df()
    cond = Condition(
        indicator="close",
        operator="crosses_above",
        value="ema",
        value_params={"length": 5},
    )
    result = cond.evaluate(df, {})
    return [f for f in [_check("close crosses_above ema(5) fires at least once", result.sum() >= 1)] if f]


def test_and_or_not() -> list[str]:
    df = _make_df()
    close = df["close"].to_numpy()

    c_high = Condition(indicator="close", operator=">", value=105.0)
    c_low = Condition(indicator="close", operator="<", value=103.0)
    c_mid = Condition(indicator="close", operator=">=", value=104.0)

    and_group = ConditionGroup(op="AND", children=[c_high, c_mid])
    or_group = ConditionGroup(op="OR", children=[and_group, c_low])
    not_group = ConditionGroup(op="NOT", children=[c_high])

    failures = []
    failures += [
        f
        for f in [
            _check(
                "AND matches both conditions simultaneously",
                (and_group.evaluate(df, {}) == ((close > 105.0) & (close >= 104.0))).all(),
            )
        ]
        if f
    ]
    failures += [
        f
        for f in [
            _check(
                "nested (A AND B) OR C matches charter's own example shape",
                (or_group.evaluate(df, {}) == (((close > 105.0) & (close >= 104.0)) | (close < 103.0))).all(),
            )
        ]
        if f
    ]
    failures += [
        f for f in [_check("NOT inverts its single child", (not_group.evaluate(df, {}) == ~(close > 105.0)).all())] if f
    ]

    return failures


def test_serialization_roundtrip() -> list[str]:
    df = _make_df()

    tree = ConditionGroup(
        op="OR",
        children=[
            ConditionGroup(
                op="AND",
                children=[
                    Condition(indicator="close", operator=">", value=105.0),
                    Condition(indicator="rsi", operator=">", value=50.0, params={"length": 14}),
                ],
            ),
            Condition(indicator="close", operator="<", value=103.0),
        ],
    )

    original = tree.evaluate(df, {})
    restored = node_from_dict(tree.to_dict())
    roundtripped = restored.evaluate(df, {})

    return [f for f in [_check("to_dict/from_dict roundtrip matches original evaluation", (original == roundtripped).all())] if f]


def test_invalid_inputs_rejected() -> list[str]:
    failures = []

    try:
        Condition(indicator="close", operator="not_a_real_operator", value=1.0)
        failures.append("FAIL: bad operator did not raise")
    except ValueError:
        print("PASS: bad operator raises ValueError")

    try:
        ConditionGroup(op="XOR", children=[Condition(indicator="close", operator=">", value=1.0)])
        failures.append("FAIL: bad group op did not raise")
    except ValueError:
        print("PASS: bad group op raises ValueError")

    try:
        ConditionGroup(
            op="NOT",
            children=[
                Condition(indicator="close", operator=">", value=1.0),
                Condition(indicator="close", operator="<", value=1.0),
            ],
        )
        failures.append("FAIL: NOT with 2 children did not raise")
    except ValueError:
        print("PASS: NOT with more than 1 child raises ValueError")

    return failures


def main() -> None:
    all_failures: list[str] = []
    for test_fn in [
        test_operators,
        test_crosses_above_below,
        test_indicator_vs_indicator,
        test_and_or_not,
        test_serialization_roundtrip,
        test_invalid_inputs_rejected,
    ]:
        all_failures.extend(test_fn())

    if all_failures:
        print("FAIL")
        for failure in all_failures:
            print(f"  {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
