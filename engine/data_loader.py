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


# symbol×timeframeの組み合わせ(数十種)ぶんをまるごとメモリに載せても
# 現実的なサイズに収まる(1m/8.6M行でも数百MB)一方、無制限に増やし続ける
# 必要はないので緩めの上限だけ設ける。キーにファイルの mtime/size を含める
# ことで、セッション中にユーザーがデータを再インポートしても古いキャッシュ
# を掴み続けない(2026-08-01、ダッシュボードの各画面操作のたびに同じ
# symbol/timeframeを何度もCSVから読み直していたのを解消)。
_PRICE_DATA_CACHE: dict[tuple[str, float, int], pd.DataFrame] = {}
_PRICE_DATA_CACHE_MAX_ENTRIES = 16


def load_price_data(path: Path) -> pd.DataFrame:
    stat = Path(path).stat()
    cache_key = (str(path), stat.st_mtime, stat.st_size)
    cached = _PRICE_DATA_CACHE.get(cache_key)
    if cached is not None:
        # 呼び出し元がフィルタ/tail等で新しいdfに束ね直すのは安全だが、
        # 万一列を直接書き換える呼び出し元が将来現れてもキャッシュ本体を
        # 汚さないよう、防御的にコピーを返す(1m/8.6M行でも約0.35秒、
        # 再パースの数秒に比べれば十分軽い)。
        return cached.copy()

    df = _load_price_data_uncached(path)

    if len(_PRICE_DATA_CACHE) >= _PRICE_DATA_CACHE_MAX_ENTRIES:
        _PRICE_DATA_CACHE.pop(next(iter(_PRICE_DATA_CACHE)))
    _PRICE_DATA_CACHE[cache_key] = df
    return df.copy()


def _load_price_data_uncached(path: Path) -> pd.DataFrame:
    # pyarrowエンジンはCエンジンよりCSV読み込みが大幅に速い(5m/USDJPY全期間
    # で実測1.5s→0.15s程度)。未インストール/読み込み失敗時は黙って従来の
    # デフォルトエンジンにフォールバックする(2026-08-01、V4.0のembeddable
    # Python配布で万一pyarrowが欠けていてもアプリが起動しなくなる事態を
    # 避けるため)。
    try:
        df = pd.read_csv(path, engine="pyarrow")
    except Exception:
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

    # このプロジェクトのデータファイルは全て"YYYY-MM-DD HH:MM:SS"形式
    # (2026-08-01時点、data/raw配下106ファイル全件で確認済み)なので、まず
    # 明示フォーマットで高速パースを試みる(汎用パーサーの75倍近く速い)。
    # 1件でもこの形式に合わない行があれば(NaTが出る、あるいはタイムゾーン
    # 付き等で例外が飛ぶ)、従来どおりの汎用パーサーに自動フォールバック
    # する - 出力は形式が揃ったファイルではビット単位で従来と同一、揃って
    # いないファイルでは従来の挙動をそのまま踏襲する。
    try:
        parsed = pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M:%S", errors="coerce").astype("datetime64[us]")
        if parsed.isna().any():
            raise ValueError("datetime format mismatch - falling back to generic parser")
    except Exception:
        parsed = pd.to_datetime(df["datetime"], errors="coerce")
    df["datetime"] = parsed

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required_cols)
    df = df.sort_values("datetime").reset_index(drop=True)

    return df
