"""Verifies engine/conditions.py's opt-in persistent indicator cache
(evaluate_condition_tree's `cache` param) - the feature added so main.py's
ProcessPoolExecutor workers can reuse indicator arrays across different
generated condition_trees that happen to share an (indicator, params) pair,
instead of recomputing every task from scratch.

Three properties checked, none of which the existing regression suite
happens to exercise (it never calls evaluate_condition_tree with a shared
cache across DIFFERENT trees):
1. Reusing one cache dict across several different trees produces results
   identical to giving each tree a fresh cache (cache=None).
2. Forcing eviction (a tiny cap) still produces correct results - an
   evicted-then-recomputed series must equal what a fresh computation gives.
3. main.py's init_worker() correctly clears the persistent cache when
   called again with a different df, so no stale series from one
   dataframe can leak into a backtest against a different one.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.conditions as conditions
from engine.conditions import evaluate_condition_tree
from engine.data_loader import find_data_file, load_price_data

DF = load_price_data(find_data_file("15m", "USDJPY"))

TREES = [
    {"indicator": "ema", "operator": ">", "value": "ema", "params": {"length": 50}, "value_params": {"length": 200}},
    {"indicator": "rsi", "operator": "<", "value": 70.0, "params": {"length": 14}, "value_params": {}},
    {"indicator": "ema", "operator": ">", "value": "sma", "params": {"length": 50}, "value_params": {"length": 100}},
    {
        "op": "AND",
        "children": [
            {"indicator": "ema", "operator": ">", "value": "close", "params": {"length": 200}, "value_params": {}},
            {"indicator": "rsi", "operator": "<", "value": 60.0, "params": {"length": 14}, "value_params": {}},
        ],
    },
    {"indicator": "atr", "operator": ">", "value": "atr", "params": {"length": 14}, "value_params": {"length": 50}},
]


def check_shared_cache_matches_fresh() -> list[str]:
    failures = []
    shared_cache: dict = {}

    for i, tree in enumerate(TREES):
        fresh_result = evaluate_condition_tree(tree, DF, symbol="USDJPY")
        cached_result = evaluate_condition_tree(tree, DF, symbol="USDJPY", cache=shared_cache)

        if not np.array_equal(fresh_result, cached_result, equal_nan=True):
            failures.append(f"tree[{i}]: shared-cache result differs from fresh-cache result")

    # Re-run all trees again through the SAME shared cache (now warm) -
    # must still match a brand-new fresh evaluation for every tree.
    for i, tree in enumerate(TREES):
        fresh_result = evaluate_condition_tree(tree, DF, symbol="USDJPY")
        cached_result = evaluate_condition_tree(tree, DF, symbol="USDJPY", cache=shared_cache)
        if not np.array_equal(fresh_result, cached_result, equal_nan=True):
            failures.append(f"tree[{i}] (second pass, warm cache): shared-cache result differs from fresh")

    return failures


def check_eviction_still_correct() -> list[str]:
    failures = []
    original_cap = conditions._MAX_CACHED_SERIES
    conditions._MAX_CACHED_SERIES = 2  # force eviction almost immediately
    try:
        shared_cache: dict = {}
        for i, tree in enumerate(TREES):
            fresh_result = evaluate_condition_tree(tree, DF, symbol="USDJPY")
            cached_result = evaluate_condition_tree(tree, DF, symbol="USDJPY", cache=shared_cache)
            if not np.array_equal(fresh_result, cached_result, equal_nan=True):
                failures.append(f"tree[{i}] (eviction cap=2): result differs from fresh")
        if len(shared_cache) > 10:
            failures.append(f"eviction cap did not bound cache size (grew to {len(shared_cache)} entries)")
    finally:
        conditions._MAX_CACHED_SERIES = original_cap

    return failures


def check_init_worker_clears_cache_on_new_df() -> list[str]:
    failures = []
    import main as m

    tree = TREES[0]

    m.init_worker(DF)
    m.run_one_backtest(
        (
            1,
            {
                **{k: v[0] for k, v in m.build_parameter_space("dev", "USDJPY").items()},
                "condition_tree": tree,
            },
        )
    )
    if len(m._WORKER_INDICATOR_CACHE) == 0:
        failures.append("expected the worker cache to be populated after a real backtest run")

    # Build a differently-SHAPED dataframe (truncated) - if init_worker
    # failed to clear the cache, a stale array sized for the ORIGINAL df
    # would still be sitting under the same (indicator, params) key here,
    # and using it against this shorter df would be silently wrong (or
    # crash on a length mismatch further down the pipeline).
    truncated_df = DF.iloc[:2000].reset_index(drop=True)
    m.init_worker(truncated_df)

    if len(m._WORKER_INDICATOR_CACHE) != 0:
        failures.append("init_worker() did not clear the indicator cache for the new df")

    m.run_one_backtest(
        (
            2,
            {
                **{k: v[0] for k, v in m.build_parameter_space("dev", "USDJPY").items()},
                "condition_tree": tree,
            },
        )
    )
    for key, value in m._WORKER_INDICATOR_CACHE.items():
        if isinstance(value, np.ndarray) and value.ndim == 1 and len(value) not in (len(truncated_df),):
            if key not in ("__symbol__", "__base_timeframe__"):
                failures.append(f"cache entry {key} has length {len(value)}, expected {len(truncated_df)}")

    return failures


def main() -> None:
    all_failures: list[str] = []
    all_failures += check_shared_cache_matches_fresh()
    all_failures += check_eviction_still_correct()
    all_failures += check_init_worker_clears_cache_on_new_df()

    if all_failures:
        print("FAIL")
        for f in all_failures:
            print(f"  {f}")
        raise SystemExit(1)

    print("PASS: persistent indicator cache matches fresh-cache results, survives eviction, "
          "and init_worker() correctly clears it for a new dataframe")


if __name__ == "__main__":
    main()
