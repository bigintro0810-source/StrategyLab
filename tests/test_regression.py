"""Locks in known-good dev-mode backtest results against silent regressions.

Not pytest-based (pytest isn't a project dependency and there's no
requirements.txt) - run directly: `python tests/test_regression.py`.
Exits non-zero on mismatch so it can still be wired into CI later.

Baselines were regenerated 2026-07-04 after replacing data/raw's USDJPY
source with the broker EET-timestamped export (converted to JST + OHLC-
consistency-fixed via import_broker_csv.py). The 15m data itself shifted
slightly (~2.3% of bars differ from the old source - mostly sub-pip
noise between feeds, see project memory for the investigation), and the
1d data switched from a self-built 1m->1d resample (which turned out to
have ~1094 unexplained extra daily bars) to the broker's native daily
candles. Both changes genuinely shift every backtest result, so the old
baseline values were deliberately replaced rather than treated as a
regression - same precedent as the 2026-07-03 RSI Wilder-smoothing change.
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
            "net_profit": 16.2862,
            "profit_factor": 1.506,
            "max_dd": 4.5562,
            "win_rate": 48.04,
            "trades": 179,
            "recovery_factor": 3.575,
        },
    },
    {
        "timeframe": "1d",
        "expected": {
            "net_profit": 8.622,
            "profit_factor": 1.405,
            "max_dd": 7.4756,
            "win_rate": 51.61,
            "trades": 31,
            "recovery_factor": 1.153,
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
