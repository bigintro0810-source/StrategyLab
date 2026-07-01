# -*- coding: utf-8 -*-
"""
Strategy Lab V1
初心者向け・本格版の土台

やること:
- 15分足をメインにブレイクアウト戦略を大量検証
- 4時間足・日足EMAフィルター対応
- 結果を途中保存
- 途中で止めても output/strategy_lab_results.csv に結果が残る

実行:
python strategy_lab_v1.py
"""

from pathlib import Path
import pandas as pd
import numpy as np
from itertools import product
import time

# =========================
# 設定
# =========================

DATA_DIR = Path("data")
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)

SYMBOL = "USDJPY"

FILE_15M = DATA_DIR / "USDJPY_2003_2026_15m.csv"
FILE_4H = DATA_DIR / "USDJPY_2003_2026_4h_TV_NY.csv"
FILE_1D = DATA_DIR / "USDJPY_2003_2026_1d_TV_NY.csv"

PIP_SIZE = 0.01

OUT_FILE = OUT_DIR / "strategy_lab_results.csv"


# =========================
# CSV読み込み
# =========================

def load_ohlc(path):
    if not path.exists():
        raise FileNotFoundError(f"ファイルがありません: {path}")

    df = pd.read_csv(path)
    df.columns = [c.lower().strip() for c in df.columns]

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

    required = ["open", "high", "low", "close"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"{path} に {col} 列がありません")

    if "volume" not in df.columns:
        df["volume"] = 0

    df = df[["datetime", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("datetime").drop_duplicates("datetime")
    df = df.reset_index(drop=True)

    return df


# =========================
# データ準備
# =========================

def prepare_data():
    print("CSV読み込み中...")

    m15 = load_ohlc(FILE_15M)
    h4 = load_ohlc(FILE_4H)
    d1 = load_ohlc(FILE_1D)

    print("インジケーター作成中...")

    h4["h4_ema50"] = h4["close"].ewm(span=50, adjust=False).mean()
    h4["h4_ema200"] = h4["close"].ewm(span=200, adjust=False).mean()
    h4 = h4[["datetime", "close", "h4_ema50", "h4_ema200"]]
    h4 = h4.rename(columns={"close": "h4_close"})

    d1["d1_ema50"] = d1["close"].ewm(span=50, adjust=False).mean()
    d1["d1_ema200"] = d1["close"].ewm(span=200, adjust=False).mean()
    d1 = d1[["datetime", "close", "d1_ema50", "d1_ema200"]]
    d1 = d1.rename(columns={"close": "d1_close"})

    m15 = pd.merge_asof(m15, h4, on="datetime", direction="backward")
    m15 = pd.merge_asof(m15, d1, on="datetime", direction="backward")

    m15["hour"] = m15["datetime"].dt.hour
    m15["weekday"] = m15["datetime"].dt.weekday
    m15["year"] = m15["datetime"].dt.year

    m15 = m15.dropna().reset_index(drop=True)

    print(f"データ期間: {m15['datetime'].min()} ～ {m15['datetime'].max()}")
    print(f"15分足本数: {len(m15):,}")

    return m15


# =========================
# 条件
# =========================

def session_ok(hour, session):
    if session == "tokyo":
        return 8 <= hour <= 14
    if session == "london":
        return 15 <= hour <= 21
    if session == "ny":
        return hour >= 21 or hour <= 2
    if session == "london_ny":
        return hour >= 15 or hour <= 2
    return True


def trend_ok(row, direction, h4_filter, d1_filter):
    if h4_filter == "bull" and not (row["h4_close"] > row["h4_ema50"]):
        return False
    if h4_filter == "bear" and not (row["h4_close"] < row["h4_ema50"]):
        return False

    if d1_filter == "bull" and not (row["d1_close"] > row["d1_ema50"]):
        return False
    if d1_filter == "bear" and not (row["d1_close"] < row["d1_ema50"]):
        return False

    return True


# =========================
# バックテスト
# =========================

def backtest(df, direction, breakout_bars, session, h4_filter, d1_filter, sl_pips, tp_pips, max_hold_bars):
    trades = []

    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    closes = df["close"].values

    rolling_high = df["high"].shift(1).rolling(breakout_bars).max().values
    rolling_low = df["low"].shift(1).rolling(breakout_bars).min().values

    in_position = False
    entry_price = 0
    entry_i = 0

    start_i = max(250, breakout_bars + 1)

    for i in range(start_i, len(df) - 1):
        row = df.iloc[i]

        if in_position:
            if direction == "long":
                sl = entry_price - sl_pips * PIP_SIZE
                tp = entry_price + tp_pips * PIP_SIZE

                hit_sl = lows[i] <= sl
                hit_tp = highs[i] >= tp

                if hit_sl and hit_tp:
                    pnl = -sl_pips
                elif hit_sl:
                    pnl = -sl_pips
                elif hit_tp:
                    pnl = tp_pips
                elif i - entry_i >= max_hold_bars:
                    pnl = (closes[i] - entry_price) / PIP_SIZE
                else:
                    continue

            else:
                sl = entry_price + sl_pips * PIP_SIZE
                tp = entry_price - tp_pips * PIP_SIZE

                hit_sl = highs[i] >= sl
                hit_tp = lows[i] <= tp

                if hit_sl and hit_tp:
                    pnl = -sl_pips
                elif hit_sl:
                    pnl = -sl_pips
                elif hit_tp:
                    pnl = tp_pips
                elif i - entry_i >= max_hold_bars:
                    pnl = (entry_price - closes[i]) / PIP_SIZE
                else:
                    continue

            trades.append({
                "entry_time": df.iloc[entry_i]["datetime"],
                "exit_time": df.iloc[i]["datetime"],
                "direction": direction,
                "pnl": pnl,
                "year": df.iloc[i]["year"],
            })

            in_position = False
            continue

        if not session_ok(row["hour"], session):
            continue

        if not trend_ok(row, direction, h4_filter, d1_filter):
            continue

        if direction == "long":
            signal = closes[i] > rolling_high[i]
        else:
            signal = closes[i] < rolling_low[i]

        if signal:
            entry_price = opens[i + 1]
            entry_i = i + 1
            in_position = True

    return trades


# =========================
# 成績計算
# =========================

def calc_stats(trades):
    if len(trades) == 0:
        return None

    pnls = np.array([t["pnl"] for t in trades], dtype=float)

    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    pf = gross_profit / gross_loss if gross_loss > 0 else 999

    equity = pnls.cumsum()
    peak = np.maximum.accumulate(equity)
    dd = equity - peak
    max_dd = abs(dd.min()) if len(dd) else 0

    return {
        "trades": len(pnls),
        "net_pips": round(pnls.sum(), 1),
        "pf": round(pf, 3),
        "winrate": round(len(wins) / len(pnls) * 100, 2),
        "max_dd_pips": round(max_dd, 1),
        "avg_pips": round(pnls.mean(), 2),
    }


def period_pf(trades, start_year, end_year):
    sub = [t for t in trades if start_year <= t["year"] <= end_year]
    s = calc_stats(sub)
    if s is None:
        return np.nan
    return s["pf"]


# =========================
# メイン処理
# =========================

def main():
    start_time = time.time()

    df = prepare_data()

    directions = ["long", "short"]
    breakout_bars_list = [24, 48, 72, 96]
    sessions = ["tokyo", "london", "ny", "london_ny"]
    h4_filters = ["none", "bull", "bear"]
    d1_filters = ["none", "bull", "bear"]
    sl_list = [30, 40, 50, 60]
    tp_list = [45, 60, 80, 100, 120]
    max_hold_list = [24, 48]

    combos = list(product(
        directions,
        breakout_bars_list,
        sessions,
        h4_filters,
        d1_filters,
        sl_list,
        tp_list,
        max_hold_list,
    ))

    print(f"検証パターン数: {len(combos):,}")
    print("検証開始...")

    results = []

    for idx, combo in enumerate(combos, start=1):
        direction, breakout_bars, session, h4_filter, d1_filter, sl_pips, tp_pips, max_hold_bars = combo

        if direction == "long" and (h4_filter == "bear" or d1_filter == "bear"):
            continue
        if direction == "short" and (h4_filter == "bull" or d1_filter == "bull"):
            continue

        trades = backtest(
            df,
            direction,
            breakout_bars,
            session,
            h4_filter,
            d1_filter,
            sl_pips,
            tp_pips,
            max_hold_bars,
        )

        stats = calc_stats(trades)

        if stats is None:
            continue

        if stats["trades"] < 100:
            continue

        pf1 = period_pf(trades, 2003, 2010)
        pf2 = period_pf(trades, 2011, 2018)
        pf3 = period_pf(trades, 2019, 2026)

        min_pf = np.nanmin([pf1, pf2, pf3])

        result = {
            "symbol": SYMBOL,
            "strategy": "breakout",
            "direction": direction,
            "breakout_bars": breakout_bars,
            "session": session,
            "h4_filter": h4_filter,
            "d1_filter": d1_filter,
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
            "max_hold_bars": max_hold_bars,
            "trades": stats["trades"],
            "net_pips": stats["net_pips"],
            "pf": stats["pf"],
            "winrate": stats["winrate"],
            "max_dd_pips": stats["max_dd_pips"],
            "avg_pips": stats["avg_pips"],
            "pf_2003_2010": round(pf1, 3),
            "pf_2011_2018": round(pf2, 3),
            "pf_2019_2026": round(pf3, 3),
            "min_period_pf": round(min_pf, 3),
            "score": round(stats["pf"] + min_pf * 0.7, 4),
        }

        results.append(result)

        if idx % 100 == 0:
            pd.DataFrame(results).sort_values(
                ["score", "pf", "net_pips"],
                ascending=False
            ).to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

            elapsed = time.time() - start_time
            print(f"{idx}/{len(combos)} 完了  経過: {elapsed/60:.1f}分  結果数: {len(results)}")

    if len(results) == 0:
        print("有効な結果がありませんでした。")
        return

    res = pd.DataFrame(results)
    res = res.sort_values(["score", "pf", "net_pips"], ascending=False)
    res.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print("\n完了")
    print(f"結果保存: {OUT_FILE}")
    print("\n上位20件")
    print(res.head(20).to_string(index=False))


if __name__ == "__main__":
    main()