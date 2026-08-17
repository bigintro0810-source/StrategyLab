"""Regression tests for the 2026-07-08 price-action round: NR4/NR7 and
volume climax (engine/derived_indicators.py). Plain-script style, matching
this project's convention - run directly with `python
tests/test_price_action.py`.

2026-08-07、ユーザー判断でチャートパターンをダブルトップ/ボトム以外全て
削除したのに伴い、同じ回で追加していたトレンドライン割れ/平行チャネル/
フェイクブレイク(engine/chart_patterns.py)とAB=CD/スリードライブ
(engine/harmonic_patterns.py、モジュールごと削除)のテストも撤去した。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import engine.derived_indicators as di

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


def _seg(a: float, b: float, n: int = 15) -> np.ndarray:
    return np.linspace(a, b, n)


def _hlc(closes: np.ndarray, wick: float = 0.3) -> tuple[pd.Series, pd.Series, pd.Series]:
    return pd.Series(closes + wick), pd.Series(closes - wick), pd.Series(closes)


def _make_df(rows: list[dict], freq_minutes: int = 15) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["datetime"] = pd.date_range("2024-01-01", periods=len(rows), freq=f"{freq_minutes}min")
    return df


def test_nr4_nr7():
    rng = np.random.RandomState(4)
    # 10 bars of normal range, then one deliberately narrow bar.
    ranges = np.abs(rng.normal(1.0, 0.2, 10))
    closes = 100 + np.cumsum(rng.normal(0, 0.1, 10))
    rows = []
    for c, r in zip(closes, ranges):
        rows.append({"open": c, "high": c + r / 2, "low": c - r / 2, "close": c})
    # Narrowest-of-4 and narrowest-of-7 bar.
    rows.append({"open": 100.0, "high": 100.05, "low": 99.98, "close": 100.02})
    df = _make_df(rows)
    nr4 = di.nr4(df)
    nr7 = di.nr7(df)
    check("nr4 fires on the deliberately narrow final bar", nr4[-1] == 1.0)
    check("nr7 fires on the deliberately narrow final bar", nr7[-1] == 1.0)


def test_volume_climax_bullish():
    rng = np.random.RandomState(5)
    n = 25
    closes = 100 + rng.normal(0, 0.05, n)
    rows = [{"open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 1000 + rng.normal(0, 50)} for c in closes]
    # A climax bar: huge bullish body + huge volume.
    rows.append({"open": 100.0, "high": 105.5, "low": 99.9, "close": 105.0, "volume": 10000})
    df = _make_df(rows)
    result = di.volume_climax_bullish(df, lookback=20, body_mult=2.0, volume_mult=2.0)
    check("volume_climax_bullish fires on the exaggerated final bar", result[-1] == 1.0)
    check("volume_climax_bullish does not fire on the quiet baseline bars", result[:n].sum() == 0, detail=str(result[:n].sum()))


if __name__ == "__main__":
    test_nr4_nr7()
    test_volume_climax_bullish()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll price_action tests passed.")
