"""Price-data file lookup and CSV loading - moved out of main.py (2026-07-06)
so engine/conditions.py's multi-timeframe condition support can load a
different timeframe's data for the same symbol without main.py importing
engine/*.py and engine/*.py importing back from main.py (a circular import).

main.py still exposes find_data_file/load_price_data/DATA_DIRS by importing
them from here, so every existing caller (analyze_sensitivity.py,
api_server.py, walk_forward.py, tests/*.py - all of which do
`from main import find_data_file, load_price_data`) is unaffected.

(This file previously held an unused, unreferenced `DataLoader` prototype
class hardcoded to USDJPY-only - confirmed via a full-repo grep to have no
importers anywhere - replaced outright rather than kept alongside.)
"""

from pathlib import Path

import pandas as pd

DATA_DIRS = ["data/raw", "data", "input", "."]


def build_data_candidates(timeframe: str, symbol: str = "USDJPY") -> list[str]:
    filenames = [
        f"{symbol}_2003_2026_{timeframe}.csv",
        f"{symbol}_2003_2026_{timeframe}_TV_NY.csv",
    ]

    if timeframe == "1m":
        filenames.append(f"{symbol}_2003_2026_1min_filled.csv")

    candidates = [
        str(Path(d) / f"{symbol}_Data" / name) for d in DATA_DIRS for name in filenames
    ]
    candidates += [str(Path(d) / name) for d in DATA_DIRS for name in filenames]

    return candidates


def find_data_file(timeframe: str = "15m", symbol: str = "USDJPY") -> Path:
    for file_path in build_data_candidates(timeframe, symbol):
        path = Path(file_path)
        if path.exists():
            return path

    raise FileNotFoundError(
        f"{symbol}_2003_2026_{timeframe}.csv が見つかりません。data/raw に置いてください。"
    )


def load_price_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    rename_map = {}

    for col in df.columns:
        name = col.lower().strip()

        if name in ["datetime", "time", "date", "timestamp", "gmt time"]:
            rename_map[col] = "datetime"
        elif name in ["open", "o"]:
            rename_map[col] = "open"
        elif name in ["high", "h"]:
            rename_map[col] = "high"
        elif name in ["low", "l"]:
            rename_map[col] = "low"
        elif name in ["close", "c"]:
            rename_map[col] = "close"

    df = df.rename(columns=rename_map)

    required_cols = ["datetime", "open", "high", "low", "close"]
    missing = [col for col in required_cols if col not in df.columns]

    if missing:
        raise ValueError(f"必要な列がありません: {missing}")

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required_cols)
    df = df.sort_values("datetime").reset_index(drop=True)

    return df
