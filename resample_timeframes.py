"""30分足・週足データを、すでに取り込み済みのより細かい足からリサンプルして生成する。

ブローカー側に30分足・週足の個別エクスポートがないため(1分/5分/15分/1時間/4時間/
日足のみ)、import_broker_csv.pyのように生データを変換するのではなく、既に検証済みの
`data/raw/{symbol}_Data/{symbol}_2003_2026_15m.csv`(30分足の元データ)と
`..._1d.csv`(週足の元データ)からpandas.resampleで再構成する。これはどのチャート
ツールでも標準的な手法(30分足は15分足2本分、週足は日足の暦週分をOHLC集約するだけ)。

集約ルール: open=区間内先頭の始値、high=区間内高値の最大、low=区間内安値の最小、
close=区間内末尾の終値、volume=区間内合計。

週足の週区切りはW-SUN(日曜終わり=月曜〜日曜のバケツ)という一般的なデフォルトを採用。

使い方:
    python resample_timeframes.py --symbols USDJPY,EURJPY,GBPJPY,AUDJPY,AUDUSD,EURUSD,GBPUSD
    (--symbolsを省略するとdata/raw配下の{symbol}_Dataフォルダを自動検出)
"""

import sys
from pathlib import Path

import pandas as pd

DATA_ROOT = Path("data/raw")

AGG_RULES = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.set_index("datetime")


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    resampled = df.resample(rule).agg(AGG_RULES)
    # Bars with no source data in that bucket (weekends, holidays) produce
    # all-NaN rows - drop them rather than forward-filling a fake candle.
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])
    return resampled.reset_index()


def generate_30m(symbol_dir: Path, symbol: str) -> None:
    src = symbol_dir / f"{symbol}_2003_2026_15m.csv"
    dst = symbol_dir / f"{symbol}_2003_2026_30m.csv"

    if not src.exists():
        print(f"  [skip] {src.name} が見つかりません")
        return

    df = _load(src)
    out = resample_ohlc(df, "30min")
    out.to_csv(dst, index=False)
    print(f"  30m: {len(df)}行(15m) -> {len(out)}行 -> {dst}")


def generate_1w(symbol_dir: Path, symbol: str) -> None:
    src = symbol_dir / f"{symbol}_2003_2026_1d.csv"
    dst = symbol_dir / f"{symbol}_2003_2026_1w.csv"

    if not src.exists():
        print(f"  [skip] {src.name} が見つかりません")
        return

    df = _load(src)
    out = resample_ohlc(df, "W-SUN")
    out.to_csv(dst, index=False)
    print(f"  1w: {len(df)}行(1d) -> {len(out)}行 -> {dst}")


def main(symbols: list[str] | None) -> None:
    if symbols is None:
        symbols = sorted(
            p.name.removesuffix("_Data") for p in DATA_ROOT.glob("*_Data") if p.is_dir()
        )

    for symbol in symbols:
        symbol_dir = DATA_ROOT / f"{symbol}_Data"
        if not symbol_dir.is_dir():
            print(f"[skip] {symbol_dir} が見つかりません")
            continue

        print(f"=== {symbol} ===")
        generate_30m(symbol_dir, symbol)
        generate_1w(symbol_dir, symbol)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="カンマ区切りの通貨ペア(省略時はdata/raw配下を自動検出)")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    main(symbols)
