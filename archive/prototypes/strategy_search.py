# -*- coding: utf-8 -*-
"""
USDJPY Strategy Search Engine
15分足をメインに、4時間足・日足フィルターを使って大量検証する版

フォルダ構成:
USDJPY_Strategy_Search
├── strategy_search.py
├── data
│   ├── USDJPY_2003_2026_15m.csv
│   ├── USDJPY_2003_2026_4h_TV_NY.csv
│   └── USDJPY_2003_2026_1d_TV_NY.csv
└── output

実行:
python strategy_search.py
"""

from pathlib import Path
import pandas as pd
import numpy as np
from itertools import product

DATA_DIR = Path("data")
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)

FILE_15M = DATA_DIR / "USDJPY_2003_2026_15m.csv"
FILE_4H = DATA_DIR / "USDJPY_2003_2026_4h_TV_NY.csv"
FILE_1D = DATA_DIR / "USDJPY_2003_2026_1d_TV_NY.csv"

PIP = 0.01
START_YEAR = 2003
END_YEAR = 2026


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"ファイルがありません: {path}")

    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    if "datetime" in df.columns:
        time_col = "datetime"
    elif "timestamp" in df.columns:
        time_col = "timestamp"
    elif "time" in df.columns:
        time_col = "time"
    else:
        raise ValueError(f"日時列が見つかりません: {path}")

    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=[time_col])
    df = df.rename(columns={time_col: "datetime"})

    need = ["open", "high", "low", "close"]
    for c in need:
        if c not in df.columns:
            raise ValueError(f"{path} に {c} 列がありません")

    if "volume" not in df.columns:
        df["volume"] = 0.0

    df = df[["datetime", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("datetime").drop_duplicates("datetime")
    df = df.reset_index(drop=True)
    return df


def add_indicators(df15, df4h, df1d):
    df15 = df15.copy()
    df4h = df4h.copy()
    df1d = df1d.copy()

    df15["ema20"] = df15["close"].ewm(span=20, adjust=False).mean()
    df15["ema50"] = df15["close"].ewm(span=50, adjust=False).mean()
    df15["ema200"] = df15["close"].ewm(span=200, adjust=False).mean()

    tr1 = df15["high"] - df15["low"]
    tr2 = (df15["high"] - df15["close"].shift()).abs()
    tr3 = (df15["low"] - df15["close"].shift()).abs()
    df15["atr14"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

    df4h["h4_ema50"] = df4h["close"].ewm(span=50, adjust=False).mean()
    df4h["h4_ema200"] = df4h["close"].ewm(span=200, adjust=False).mean()
    df4h = df4h[["datetime", "close", "h4_ema50", "h4_ema200"]].rename(columns={"close": "h4_close"})

    df1d["d_ema50"] = df1d["close"].ewm(span=50, adjust=False).mean()
    df1d["d_ema200"] = df1d["close"].ewm(span=200, adjust=False).mean()
    df1d["prev_high"] = df1d["high"].shift(1)
    df1d["prev_low"] = df1d["low"].shift(1)
    df1d = df1d[["datetime", "close", "d_ema50", "d_ema200", "prev_high", "prev_low"]].rename(columns={"close": "d_close"})

    df15 = pd.merge_asof(df15, df4h, on="datetime", direction="backward")
    df15 = pd.merge_asof(df15, df1d, on="datetime", direction="backward")

    df15["hour_jst"] = df15["datetime"].dt.tz_localize(None).dt.hour
    df15["weekday"] = df15["datetime"].dt.weekday
    df15["year"] = df15["datetime"].dt.year

    return df15.dropna().reset_index(drop=True)


def in_session(hour, session_name):
    if session_name == "tokyo":
        return 8 <= hour <= 14
    if session_name == "london":
        return 15 <= hour <= 21
    if session_name == "ny":
        return hour >= 21 or hour <= 2
    if session_name == "london_ny":
        return hour >= 15 or hour <= 2
    return True


def calc_stats(trades):
    if len(trades) == 0:
        return None

    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else np.inf
    winrate = len(wins) / len(pnls) * 100

    equity = pnls.cumsum()
    peak = np.maximum.accumulate(equity)
    dd = equity - peak
    max_dd = abs(dd.min()) if len(dd) else 0

    return {
        "trades": len(pnls),
        "net_pips": pnls.sum(),
        "pf": pf,
        "winrate": winrate,
        "max_dd_pips": max_dd,
        "avg_pips": pnls.mean(),
    }


def backtest_breakout(df, direction, breakout_bars, session, h4_filter, d_filter, sl_pips, tp_pips, max_hold_bars):
    trades = []
    in_pos = False
    entry_price = 0
    entry_i = 0

    high_roll = df["high"].shift(1).rolling(breakout_bars).max()
    low_roll = df["low"].shift(1).rolling(breakout_bars).min()

    for i in range(max(250, breakout_bars + 1), len(df) - 1):
        row = df.iloc[i]

        if in_pos:
            for j in range(i, min(i + 1, len(df))):
                r = df.iloc[j]

                if pos_dir == "long":
                    sl = entry_price - sl_pips * PIP
                    tp = entry_price + tp_pips * PIP

                    hit_sl = r["low"] <= sl
                    hit_tp = r["high"] >= tp

                    if hit_sl and hit_tp:
                        pnl = -sl_pips
                    elif hit_tp:
                        pnl = tp_pips
                    elif hit_sl:
                        pnl = -sl_pips
                    elif i - entry_i >= max_hold_bars:
                        pnl = (r["close"] - entry_price) / PIP
                    else:
                        continue

                else:
                    sl = entry_price + sl_pips * PIP
                    tp = entry_price - tp_pips * PIP

                    hit_sl = r["high"] >= sl
                    hit_tp = r["low"] <= tp

                    if hit_sl and hit_tp:
                        pnl = -sl_pips
                    elif hit_tp:
                        pnl = tp_pips
                    elif hit_sl:
                        pnl = -sl_pips
                    elif i - entry_i >= max_hold_bars:
                        pnl = (entry_price - r["close"]) / PIP
                    else:
                        continue

                trades.append({
                    "entry_time": df.iloc[entry_i]["datetime"],
                    "exit_time": r["datetime"],
                    "direction": pos_dir,
                    "pnl": pnl,
                    "year": r["year"],
                })
                in_pos = False
                break

            if in_pos:
                continue

        if not in_session(row["hour_jst"], session):
            continue

        if h4_filter == "bull" and not (row["h4_close"] > row["h4_ema50"]):
            continue
        if h4_filter == "bear" and not (row["h4_close"] < row["h4_ema50"]):
            continue

        if d_filter == "bull" and not (row["d_close"] > row["d_ema50"]):
            continue
        if d_filter == "bear" and not (row["d_close"] < row["d_ema50"]):
            continue

        if direction == "long":
            signal = row["close"] > high_roll.iloc[i]
        else:
            signal = row["close"] < low_roll.iloc[i]

        if signal:
            entry_price = df.iloc[i + 1]["open"]
            entry_i = i + 1
            pos_dir = direction
            in_pos = True

    return trades


def period_pf(trades, y1, y2):
    sub = [t for t in trades if y1 <= t["year"] <= y2]
    s = calc_stats(sub)
    return s["pf"] if s else np.nan


def main():
    print("CSV読み込み中...")
    df15 = load_csv(FILE_15M)
    df4h = load_csv(FILE_4H)
    df1d = load_csv(FILE_1D)

    print("インジケーター作成中...")
    df = add_indicators(df15, df4h, df1d)

    print(f"検証データ: {df['datetime'].min()} ～ {df['datetime'].max()}")
    print(f"15分足本数: {len(df):,}")

    directions = ["long", "short"]
    breakout_bars_list = [24, 48, 72, 96]
    sessions = ["tokyo", "london", "ny", "london_ny"]
    h4_filters = ["none", "bull", "bear"]
    d_filters = ["none", "bull", "bear"]
    sl_list = [30, 40, 50, 60]
    tp_list = [45, 60, 80, 100, 120]
    max_hold_list = [24, 48]  # 15分足24本=6時間, 48本=12時間

    results = []
    total = (
        len(directions)
        * len(breakout_bars_list)
        * len(sessions)
        * len(h4_filters)
        * len(d_filters)
        * len(sl_list)
        * len(tp_list)
        * len(max_hold_list)
    )

    n = 0
    print(f"検証パターン数: {total}")

    for direction, bb, session, h4f, dfilt, sl, tp, mh in product(
        directions,
        breakout_bars_list,
        sessions,
        h4_filters,
        d_filters,
        sl_list,
        tp_list,
        max_hold_list,
    ):
        n += 1

        # ロングにbearフィルター、ショートにbullフィルターは一応除外
        if direction == "long" and (h4f == "bear" or dfilt == "bear"):
            continue
        if direction == "short" and (h4f == "bull" or dfilt == "bull"):
            continue

        trades = backtest_breakout(df, direction, bb, session, h4f, dfilt, sl, tp, mh)
        stats = calc_stats(trades)

        if not stats:
            continue
        if stats["trades"] < 100:
            continue

        pf_03_10 = period_pf(trades, 2003, 2010)
        pf_11_18 = period_pf(trades, 2011, 2018)
        pf_19_26 = period_pf(trades, 2019, 2026)

        results.append({
            "strategy": "breakout",
            "direction": direction,
            "breakout_bars": bb,
            "session": session,
            "h4_filter": h4f,
            "d_filter": dfilt,
            "sl_pips": sl,
            "tp_pips": tp,
            "max_hold_bars": mh,
            "trades": stats["trades"],
            "net_pips": round(stats["net_pips"], 1),
            "pf": round(stats["pf"], 3),
            "winrate": round(stats["winrate"], 2),
            "max_dd_pips": round(stats["max_dd_pips"], 1),
            "avg_pips": round(stats["avg_pips"], 2),
            "pf_2003_2010": round(pf_03_10, 3),
            "pf_2011_2018": round(pf_11_18, 3),
            "pf_2019_2026": round(pf_19_26, 3),
            "score": round(
                stats["pf"]
                + min(pf_03_10, pf_11_18, pf_19_26) * 0.7
                + min(stats["trades"], 1500) / 1500 * 0.2,
                4
            )
        })

        if n % 200 == 0:
            print(f"{n}/{total} 完了")

    res = pd.DataFrame(results)

    if res.empty:
        print("有効な結果がありませんでした。")
        return

    res = res.sort_values(["score", "pf", "net_pips"], ascending=False)
    out_path = OUT_DIR / "strategy_results.csv"
    res.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n完了")
    print(f"結果保存: {out_path}")
    print("\n上位20件:")
    print(res.head(20).to_string(index=False))


if __name__ == "__main__":
    main()