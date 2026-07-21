"""ブローカー提供のEET(東欧時間)タイムスタンプ付きCSVを、
Strategy Labのエンジンが前提とするJST・列名形式に変換する。

想定入力形式:
    Time (EET),Open,High,Low,Close,Volume
    2003.05.05 00:00:00,118.94,119.016,118.926,118.951,3468.2

Volume列は無くてもよい(FXは中央取引所が無く「出来高」自体が業者ごとの
参考値でしかないため、無い提供元も多い) - 無ければ0で埋める。OBV/MFI/CMF/
出来高クライマックス等、出来高そのものを条件に使うインジケーターを使わない
限り、この値はバックテスト結果に一切影響しない。

日時列は上記の「年.月.日 時:分:秒」形式に加えて、TradingViewのCSV
エクスポート等が使うISO8601形式(例: 2025-09-01T06:30:00+09:00、
タイムゾーンオフセット付き)にも対応する。オフセット付きの場合はその
オフセットをそのまま採用するため、下記「取り込み元のタイムゾーン」指定は
無視される(文字列自体に既にタイムゾーンが明記されているため)。

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

TARGET_TZ = "Asia/Tokyo"
# 取り込み元CSVのタイムスタンプが実際にどのタイムゾーンかは、ブローカー/
# データ提供元によって違う(必ずEETとは限らない) - CSVインポート画面の
# 「取り込み元のタイムゾーン」欄で選べるようにする(ユーザー要望:
# 「もしもとからJSTのデータでも勝手にEETって認識して変換しちゃうの?」
# への対応)。EETはEU方式のサマータイム(3月最終日曜〜10月最終日曜)を
# 採用するブローカーサーバー時間を想定(Europe/Helsinki)。JSTを選んだ
# 場合は変換元=変換先が同じなので実質そのまま(オフセット0)、UTCは
# サマータイム無しで常に+9時間。
SOURCE_TZ_OPTIONS = {
    "EET": "Europe/Helsinki",
    "JST": "Asia/Tokyo",
    "UTC": "UTC",
}
DEFAULT_SOURCE_TZ_LABEL = "EET"

TIMEFRAME_LABELS = {
    "1m": "1 Min",
    "5m": "5 Mins",
    "10m": "10 Mins",
    "15m": "15 Mins",
    "30m": "30 Mins",
    "1h": "Hourly",
    "4h": "4 Hours",
    "1d": "Daily",
    "1w": "Weekly",
    "1mo": "Monthly",
}


def merge_into_existing(new_df: pd.DataFrame, existing_path: Path) -> tuple[pd.DataFrame, int]:
    """出力先に既存のデータファイルがある場合、それを丸ごと置き換えるのでは
    なく、既存の行はそのまま残し、既存に無い日時の行だけをnew_dfから追加する
    (ユーザー要望:「23年分は残したい」)。重複する日時は既存側の値を優先し、
    new_df側の値では上書きしない - 過去に保存済みのバックテスト結果が、
    後から取り込んだ別データ提供元の値でこっそり変わってしまわないようにする
    ため。出力先が無ければnew_dfをそのまま返す(=従来通りの新規作成)。"""
    if not existing_path.exists():
        return new_df, len(new_df)

    existing_df = pd.read_csv(existing_path)
    existing_df["datetime"] = pd.to_datetime(existing_df["datetime"])

    existing_times = set(existing_df["datetime"])
    added_rows = new_df[~new_df["datetime"].isin(existing_times)]

    merged = pd.concat([existing_df, added_rows], ignore_index=True)
    merged = merged.sort_values("datetime").reset_index(drop=True)
    return merged, len(added_rows)


def _read_and_normalize(input_path: Path, source_tz: str) -> tuple[pd.DataFrame, bool]:
    """1ファイル分を読み込み、datetime/open/high/low/close/volume列に正規化
    する。戻り値の2つ目はVolume列が元々無く0で補ったかどうか。"""
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

    try:
        df["datetime"] = pd.to_datetime(df["datetime"], format="%Y.%m.%d %H:%M:%S")
    except ValueError:
        # ブローカー形式("2003.05.05 00:00:00")に一致しない場合、TradingView
        # エクスポート等のISO8601形式("2025-09-01T06:30:00+09:00")として
        # 再トライする。
        df["datetime"] = pd.to_datetime(df["datetime"])

    if df["datetime"].dt.tz is None:
        # タイムゾーンオフセットを含まない(=ブローカー形式)場合のみ、
        # 「取り込み元のタイムゾーン」指定で解釈する。ISO8601でオフセットが
        # 既に付いている場合はここをスキップする(tz-awareな値に
        # tz_localizeを呼ぶとpandasがエラーになるため、かつ文字列自体に
        # 既にタイムゾーンが明記されているのでsource_tzを適用する必要が無い)。
        df["datetime"] = df["datetime"].dt.tz_localize(
            source_tz, ambiguous="NaT", nonexistent="NaT"
        )

        unresolved = int(df["datetime"].isna().sum())
        if unresolved:
            raise ValueError(
                f"{unresolved}件のタイムスタンプがDST切り替えの曖昧/欠落時刻に該当し変換できません。"
                f"該当行を確認してください。({input_path.name})"
            )

    df["datetime"] = df["datetime"].dt.tz_convert(TARGET_TZ).dt.tz_localize(None)

    volume_defaulted = "volume" not in df.columns
    if volume_defaulted:
        df["volume"] = 0.0

    return df[["datetime", "open", "high", "low", "close", "volume"]], volume_defaulted


def convert(
    input_path: Path | list[Path],
    output_path: Path,
    source_tz: str = SOURCE_TZ_OPTIONS[DEFAULT_SOURCE_TZ_LABEL],
    merge: bool = False,
) -> pd.DataFrame:
    # 同じ通貨ペア/時間足のCSVが期間ごとに複数ファイルへ分かれて提供される
    # こともある(ユーザー要望:「15分足のデータが2つある場合はどうなる?」
    # への対応、例: "USDJPY_15 Mins_Bid_2003.05.05_2026.07.02.csv"+
    # "USDJPY_15 Mins_Bid_2026.07.01_2026.07.18.csv") - 1つに結合してから
    # 処理する(以前はfind_source_fileが最初の1件しか返さず、他のファイルが
    # 無言で無視されていた不具合があった)。
    input_paths = [input_path] if isinstance(input_path, Path) else list(input_path)

    results = [_read_and_normalize(p, source_tz) for p in input_paths]
    parts = [r[0] for r in results]
    volume_defaulted = any(r[1] for r in results)

    df = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]

    dup_count = 0
    if len(input_paths) > 1:
        before = len(df)
        # 複数ファイルの境界で同じ日時が重複することがある(上の例だと
        # 2026.07.01〜07.02が両方に含まれる) - 同じ提供元からの再エクスポート
        # 前提で、先に読んだファイル側の値を採用して1行にまとめる。
        df = df.drop_duplicates(subset="datetime", keep="first")
        dup_count = before - len(df)

    df = df.sort_values("datetime").reset_index(drop=True)

    orig_high = df["high"].copy()
    orig_low = df["low"].copy()
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    n_fixed = int(((df["high"] != orig_high) | (df["low"] != orig_low)).sum())

    added_count: int | None = None
    if merge:
        df, added_count = merge_into_existing(df, output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    print(f"変換完了: {len(df)}行 -> {output_path}")
    print(f"期間: {df['datetime'].min()} 〜 {df['datetime'].max()}")
    print(f"OHLC整合性エラー修正: {n_fixed}件")
    if len(input_paths) > 1:
        print(f"入力ファイル{len(input_paths)}件を結合しました(重複日時{dup_count}件は1つにまとめました)。")
    if volume_defaulted:
        print("Volume列が入力CSVに無かったため、0で補いました(出来高系インジケーターを使わない限り結果に影響しません)。")
    if merge and added_count is not None:
        print(f"マージモード: 既存データは保持したまま、新規に{added_count}件追加しました(重複日時は既存側の値を維持)。")

    return df


def find_source_files(source_dir: Path, symbol: str, timeframe: str) -> list[Path]:
    label = TIMEFRAME_LABELS[timeframe]
    matches = sorted(source_dir.glob(f"{symbol}_{label}_Bid_*.csv"))

    if not matches:
        raise FileNotFoundError(
            f"{source_dir} に {symbol}_{label}_Bid_*.csv が見つかりません"
        )

    return matches


def convert_symbol(
    source_root: Path,
    dest_root: Path,
    symbol: str,
    timeframes: list[str],
    completed: list[str],
    skipped: list[str],
    skip_existing: bool = False,
    source_tz: str = SOURCE_TZ_OPTIONS[DEFAULT_SOURCE_TZ_LABEL],
    merge: bool = False,
) -> None:
    """指定した時間足のうち、対応するCSVファイルが見つからなかったものは
    スキップして残りを続行する(ユーザー要望:「見つからなかったものは
    飛ばしてほかのやつは成功にできる?」) - ファイルが単にまだ無いだけで、
    他の時間足の変換を諦める理由にはならないため。

    completed/skippedは呼び出し元が持つ一覧に直接追記する(戻り値で返す
    のではなく) - convert()の途中で本当のエラー(DST境界の曖昧な時刻など)
    が起きて例外がそのまま外へ伝播した場合でも、そこまでに完了/スキップ
    済みの分の記録が失われないようにするため(ユーザー要望:「どこまで
    上書きしたかはわかる?」への対応)。

    skip_existingがTrueの時は、出力先ファイルが既に存在する時間足は
    再変換せずスキップする - エラー後に同じ内容で再実行した時、既に
    成功している分をやり直さず続きから進められるようにするため
    (ユーザー要望:「エラー出たとき途中から再開できるようにしてほしい」)。"""
    source_dir = source_root / f"{symbol}_Data"
    dest_dir = dest_root / f"{symbol}_Data"

    for timeframe in timeframes:
        dst = dest_dir / f"{symbol}_2003_2026_{timeframe}.csv"

        if skip_existing and dst.exists():
            print(f"既存のためスキップ: {symbol} {timeframe}")
            completed.append(f"{symbol} {timeframe}")
            continue

        try:
            srcs = find_source_files(source_dir, symbol, timeframe)
        except FileNotFoundError:
            print(f"スキップ: {symbol} {timeframe} - ファイルが見つかりません")
            skipped.append(f"{symbol} {timeframe}")
            continue

        src_desc = srcs[0].name if len(srcs) == 1 else f"{len(srcs)}件のファイル({', '.join(s.name for s in srcs)})"
        print(f"=== {symbol} {timeframe}: {src_desc} -> {dst} ===")
        convert(srcs, dst, source_tz, merge=merge)
        print(f"完了: {symbol} {timeframe}")
        completed.append(f"{symbol} {timeframe}")


def _parse_args(argv: list[str]):
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("input", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--batch-source", type=Path)
    parser.add_argument("--batch-dest", type=Path)
    parser.add_argument("--symbols")
    parser.add_argument("--timeframes", default="1m,5m,15m,1h")
    # エラー後の「続きから再開」用(ユーザー要望) - api_server.pyのCsvImport
    # Request.skip_existing/CsvImportScreen.tsxの「続きから再開」ボタン参照。
    parser.add_argument("--skip-existing", action="store_true")
    # 取り込み元CSVのタイムゾーン(ユーザー要望:「もしもとからJSTのデータ
    # でも勝手にEETって認識して変換しちゃうの?」への対応) - SOURCE_TZ_
    # OPTIONSのキー(EET/JST/UTC)のいずれか。
    parser.add_argument("--source-tz", default=DEFAULT_SOURCE_TZ_LABEL, choices=list(SOURCE_TZ_OPTIONS))
    # ユーザー要望:「23年分は残したい」への対応 - 指定時は出力先を丸ごと
    # 置き換えず、既存に無い日時の行だけを追加する(merge_into_existing参照)。
    parser.add_argument("--merge", action="store_true")

    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])

    if args.batch_source and args.batch_dest and args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

        source_tz = SOURCE_TZ_OPTIONS[args.source_tz]
        all_completed: list[str] = []
        all_skipped: list[str] = []
        try:
            for symbol in symbols:
                convert_symbol(
                    args.batch_source, args.batch_dest, symbol, timeframes,
                    all_completed, all_skipped, args.skip_existing, source_tz,
                    merge=args.merge,
                )
        finally:
            # convert()の途中で例外が飛んで打ち切られた場合でも、finallyで
            # 必ずここまでの進捗を表示する(ユーザー要望:「どこまで上書き
            # したかはわかる?」)。
            # 標準出力はWindowsのデフォルト文字コード(cp932)でエンコード
            # されることが多く、✓のような記号はcp932の文字集合に無いため
            # UnicodeEncodeErrorでジョブ自体が落ちてしまう(実際に踏んだ
            # 不具合) - 日本語(Shift-JISの範囲内)とASCII記号だけを使う。
            print(f"\n変換完了: {len(all_completed)}件")
            for item in all_completed:
                print(f"  * {item}")
            if all_skipped:
                print(f"\n見つからずスキップ: {len(all_skipped)}件")
                for item in all_skipped:
                    print(f"  - {item}")

        total_requested = len(symbols) * len(timeframes)
        # 1件も変換できていない(全部スキップ)場合は「成功」扱いにすると
        # 何も起きていないのに完了と表示されて紛らわしいため、その時だけ
        # エラーにする。
        if all_skipped and len(all_skipped) == total_requested:
            print("\nエラー: 指定した組み合わせが1件も見つかりませんでした。")
            sys.exit(1)
    elif args.input and args.output:
        convert(Path(args.input), Path(args.output), merge=args.merge)
    else:
        print(
            "使い方:\n"
            "  単一ファイル: python import_broker_csv.py <入力CSV> <出力CSV>\n"
            "  一括変換:     python import_broker_csv.py --batch-source <ソースルート> "
            "--batch-dest <出力ルート> --symbols USDJPY,EURJPY,GBPJPY "
            "--timeframes 1m,5m,15m,1h"
        )
        sys.exit(1)
