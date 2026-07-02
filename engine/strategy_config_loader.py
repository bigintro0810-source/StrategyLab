"""Loads a named parameter grid from a JSON file (V3.0 条件ベースのストラテジー定義).

Scoped-down version of "condition-based strategy definition": the
existing dormant engine/condition_engine.py + engine/condition_config.py
model a different, simpler strategy shape (EMA/RSI/ATR/ADX threshold
crossovers) than the live breakout strategy in engine/backtest_engine.py
(candle body/wick filters, breakout lookback, EMA distance, RR exits), and
have several condition flags (FVG/BOS/CHoCH/order block/liquidity) that
are declared but never implemented. Reusing it directly isn't possible
without redesigning the live strategy's condition vocabulary, which is a
much larger, riskier change to a bar-by-bar loop that's been validated
against TradingView.

This instead attacks the concrete pain point directly: trying a new
parameter combination currently requires editing build_parameter_space()
in main.py. Named JSON config files let you do that without touching
Python. It does NOT make the strategy's *logic* (which conditions exist,
how they combine) configurable - only which values get tried for the
already-existing parameters.
"""

import json
from pathlib import Path


def load_strategy_config(path: Path) -> dict[str, list]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    if "params" not in data:
        raise ValueError(f"{path} に 'params' キーがありません。")

    return data["params"]
