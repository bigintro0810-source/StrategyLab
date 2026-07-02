"""Locks in known-good dev-mode backtest results against silent regressions.

Not pytest-based (pytest isn't a project dependency and there's no
requirements.txt) - run directly: `python tests/test_regression.py`.
Exits non-zero on mismatch so it can still be wired into CI later.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import build_parameter_grid, find_data_file, init_worker, load_price_data, run_one_backtest

TOLERANCE = 1e-3

CASES = [
    {
        "timeframe": "15m",
        "expected": {
            "net_profit": 15.9758,
            "profit_factor": 1.563,
            "max_dd": 4.3244,
            "win_rate": 49.69,
            "trades": 159,
            "recovery_factor": 3.694,
        },
    },
    {
        "timeframe": "1d",
        "expected": {
            "net_profit": -10.4594,
            "profit_factor": 0.762,
            "max_dd": 23.1792,
            "win_rate": 40.0,
            "trades": 50,
            "recovery_factor": -0.451,
        },
    },
]


def run_case(timeframe: str, expected: dict) -> list[str]:
    data_path = find_data_file(timeframe)
    df = load_price_data(data_path)
    params = build_parameter_grid("dev")[0]

    init_worker(df)
    result = run_one_backtest((1, params))

    failures = []
    for key, expected_value in expected.items():
        actual_value = result[key]
        if abs(actual_value - expected_value) > TOLERANCE:
            failures.append(
                f"[{timeframe}] {key}: expected {expected_value}, got {actual_value}"
            )

    return failures


def main() -> None:
    all_failures = []

    for case in CASES:
        failures = run_case(case["timeframe"], case["expected"])
        if failures:
            all_failures.extend(failures)
        else:
            print(f"PASS: {case['timeframe']} dev-mode baseline matches expected metrics")

    if all_failures:
        print("FAIL")
        for failure in all_failures:
            print(f"  {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
