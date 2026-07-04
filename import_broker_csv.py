"""ブローカー提供のEET(東欧時間)タイムスタンプ付きCSVを、
Strategy Labのエンジンが前提とするJST・列名形式に変換する。

想定入力形式:
    Time (EET),Open,High,Low,Close,Volume
    2003.05.05 00:00:00,118.94,119.016,118.926,118.951,3468.2

出力形式:
    datetime,open,high,low,close,volume
    2003-05-05 09:00:00,118.94,119.016,118.926,118.951,3468.2

EETはEU方式のサマータイム(3月最終日曜〜10月最終日曜)を採用するブローカー
サーバー時間を想定(Europe/Helsinki)。FX市場は切り替え時刻(週末未明)は
休場のため通常はDSTの重複/欠落時刻と衝突しないが、念のため検出して
エラーにする。

タイムゾーン変換と同時に、OHLC整合性エラー(high<open/close や
low>open/close など、四本値としてあり得ない行)も
high=max(O,H,L,C)・low=min(O,H,L,C)に補正する。

使い方:
    単一ファイル変換:
        python import_broker_csv.py <入力CSV> <出力CSV>

    一括変換(FX_Data配下の{symbol}_Data/{symbol}_<足>_Bid_*.csvを
    data/raw配下の{symbol}_Data/{symbol}_2003_2026_<足>.csvへ変換):
        python import_broker_csv.py --batch-source <ソースルート> --batch-dest <出力ルート> \\
            --symbols USDJPY,EURJPY,GBPJPY --timeframes 1m,5m,15m,1h
"""

import sys
from pathlib import Path

import pandas as pd

SOURCE_TZ = "Europe/Helsinki"
TARGET_TZ = "Asia/Tokyo"

TIMEFRAME_LABELS = {
    "1m": "1 Min",
    "5m": "5 Mins",
    "15m": "15 Mins",
    "1h": "Hourly",
    "4h": "4 Hours",
    "1d": "Daily",
}


def convert(input_path: Path, output_path: Path) -> pd.DataFrame:
    df = pd.read_csv(input_path)
    df.columns = [c.strip() for c in df.columns]

    time_col = next(c for c in df.columns if c.lower().startswith("time"))
    df = df.rename(
        columns={
            time_col: "datetime",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )

    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y.%m.%d %H:%M:%S")
    df["datetime"] = df["datetime"].dt.tz_localize(
        SOURCE_TZ, ambiguous="NaT", nonexistent="NaT"
    )

    unresolved = int(df["datetime"].isna().sum())
    if unresolved:
        raise ValueError(
            f"{unresolved}件のタイムスタンプがDST切り替えの曖昧/欠落時刻に該当し変換できません。"
            "該当行を確認してください。"
        )

    df["datetime"] = df["datetime"].dt.tz_convert(TARGET_TZ).dt.tz_localize(None)
    df = df[["datetime", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("datetime").reset_index(drop=True)

    orig_high = df["high"].copy()
    orig_low = df["low"].copy()
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    n_fixed = int(((df["high"] != orig_high) | (df["low"] != orig_low)).sum())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    print(f"変換完了: {len(df)}行 -> {output_path}")
    print(f"期間: {df['datetime'].min()} 〜 {df['datetime'].max()}")
    print(f"OHLC整合性エラー修正: {n_fixed}件")

    return df


def find_source_file(source_dir: Path, symbol: str, timeframe: str) -> Path:
    label = TIMEFRAME_LABELS[timeframe]
    matches = sorted(source_dir.glob(f"{symbol}_{label}_Bid_*.csv"))

    if not matches:
        raise FileNotFoundError(
            f"{source_dir} に {symbol}_{label}_Bid_*.csv が見つかりません"
        )

    return matches[0]


def convert_symbol(
    source_root: Path, dest_root: Path, symbol: str, timeframes: list[str]
) -> None:
    source_dir = source_root / f"{symbol}_Data"
    dest_dir = dest_root / f"{symbol}_Data"

    for timeframe in timeframes:
        src = find_source_file(source_dir, symbol, timeframe)
        dst = dest_dir / f"{symbol}_2003_2026_{timeframe}.csv"

        print(f"=== {symbol} {timeframe}: {src.name} -> {dst} ===")
        convert(src, dst)


def _parse_args(argv: list[str]):
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("input", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--batch-source", type=Path)
    parser.add_argument("--batch-dest", type=Path)
    parser.add_argument("--symbols")
    parser.add_argument("--timeframes", default="1m,5m,15m,1h")

    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])

    if args.batch_source and args.batch_dest and args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

        for symbol in symbols:
            convert_symbol(args.batch_source, args.batch_dest, symbol, timeframes)
    elif args.input and args.output:
        convert(Path(args.input), Path(args.output))
    else:
        print(
            "使い方:\n"
            "  単一ファイル: python import_broker_csv.py <入力CSV> <出力CSV>\n"
            "  一括変換:     python import_broker_csv.py --batch-source <ソースルート> "
            "--batch-dest <出力ルート> --symbols USDJPY,EURJPY,GBPJPY "
            "--timeframes 1m,5m,15m,1h"
        )
        sys.exit(1)
