# -*- coding: utf-8 -*-
from pathlib import Path
import pandas as pd
import numpy as np
from itertools import product
import time

DATA_DIR = Path("data")
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)

FILE_15M = DATA_DIR / "USDJPY_2003_2026_15m.csv"
FILE_4H  = DATA_DIR / "USDJPY_2003_2026_4h_TV_NY.csv"
FILE_1D  = DATA_DIR / "USDJPY_2003_2026_1d_TV_NY.csv"

OUT_FILE = OUT_DIR / "strategy_lab_fast_results.csv"
PIP = 0.01


def load_csv(path):
    df = pd.read_csv(path)
    df.columns = [c.lower().strip() for c in df.columns]
    time_col = "datetime" if "datetime" in df.columns else "timestamp"
    df[time_col] = pd.to_datetime(df[time_col])
    df = df.rename(columns={time_col: "datetime"})
    df = df[["datetime", "open", "high", "low", "close", "volume"]]
    return df.sort_values("datetime").drop_duplicates("datetime").reset_index(drop=True)


def prepare():
    print("CSV読み込み中...")
    m15 = load_csv(FILE_15M)
    h4 = load_csv(FILE_4H)
    d1 = load_csv(FILE_1D)

    print("インジケーター作成中...")
    h4["h4_ema50"] = h4["close"].ewm(span=50, adjust=False).mean()
    d1["d1_ema50"] = d1["close"].ewm(span=50, adjust=False).mean()

    h4 = h4[["datetime", "close", "h4_ema50"]].rename(columns={"close": "h4_close"})
    d1 = d1[["datetime", "close", "d1_ema50"]].rename(columns={"close": "d1_close"})

    df = pd.merge_asof(m15, h4, on="datetime", direction="backward")
    df = pd.merge_asof(df, d1, on="datetime", direction="backward")

    df["hour"] = df["datetime"].dt.hour
    df["year"] = df["datetime"].dt.year
    df = df.dropna().reset_index(drop=True)

    print(f"データ期間: {df['datetime'].min()} ～ {df['datetime'].max()}")
    print(f"15分足本数: {len(df):,}")
    return df


def session_mask(hours, name):
    if name == "tokyo":
        return (hours >= 8) & (hours <= 14)
    if name == "london":
        return (hours >= 15) & (hours <= 21)
    if name == "ny":
        return (hours >= 21) | (hours <= 2)
    if name == "london_ny":
        return (hours >= 15) | (hours <= 2)
    return np.ones(len(hours), dtype=bool)


def calc_stats(pnls, years):
    if len(pnls) < 50:
        return None

    pnls = np.array(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    if len(losses) == 0:
        pf = 999
    else:
        pf = wins.sum() / abs(losses.sum())

    equity = pnls.cumsum()
    peak = np.maximum.accumulate(equity)
    dd = equity - peak

    def pf_period(y1, y2):
        mask = (years >= y1) & (years <= y2)
        p = pnls[mask]
        if len(p) < 10:
            return np.nan
        w = p[p > 0].sum()
        l = abs(p[p < 0].sum())
        return 999 if l == 0 else w / l

    return {
        "trades": len(pnls),
        "net_pips": round(pnls.sum(), 1),
        "pf": round(pf, 3),
        "winrate": round(len(wins) / len(pnls) * 100, 2),
        "max_dd_pips": round(abs(dd.min()), 1),
        "pf_2003_2010": round(pf_period(2003, 2010), 3),
        "pf_2011_2018": round(pf_period(2011, 2018), 3),
        "pf_2019_2026": round(pf_period(2019, 2026), 3),
    }


def run_backtest(df, direction, breakout_bars, session, h4_filter, d1_filter, sl_pips, tp_pips, max_hold):
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    open_ = df["open"].to_numpy()
    close = df["close"].to_numpy()
    hours = df["hour"].to_numpy()
    years_all = df["year"].to_numpy()

    roll_high = pd.Series(high).shift(1).rolling(breakout_bars).max().to_numpy()
    roll_low = pd.Series(low).shift(1).rolling(breakout_bars).min().to_numpy()

    mask = session_mask(hours, session)

    if h4_filter == "bull":
        mask &= df["h4_close"].to_numpy() > df["h4_ema50"].to_numpy()
    elif h4_filter == "bear":
        mask &= df["h4_close"].to_numpy() < df["h4_ema50"].to_numpy()

    if d1_filter == "bull":
        mask &= df["d1_close"].to_numpy() > df["d1_ema50"].to_numpy()
    elif d1_filter == "bear":
        mask &= df["d1_close"].to_numpy() < df["d1_ema50"].to_numpy()

    if direction == "long":
        signal = close > roll_high
    else:
        signal = close < roll_low

    entries = np.where(mask & signal)[0]
    entries = entries[entries < len(df) - max_hold - 2]

    pnls = []
    trade_years = []
    next_allowed = 0

    for i in entries:
        if i < next_allowed:
            continue

        entry_i = i + 1
        entry = open_[entry_i]

        if direction == "long":
            sl = entry - sl_pips * PIP
            tp = entry + tp_pips * PIP

            exit_pnl = None
            for j in range(entry_i, entry_i + max_hold):
                hit_sl = low[j] <= sl
                hit_tp = high[j] >= tp

                if hit_sl:
                    exit_pnl = -sl_pips
                    next_allowed = j + 1
                    break
                if hit_tp:
                    exit_pnl = tp_pips
                    next_allowed = j + 1
                    break

            if exit_pnl is None:
                j = entry_i + max_hold
                exit_pnl = (close[j] - entry) / PIP
                next_allowed = j + 1

        else:
            sl = entry + sl_pips * PIP
            tp = entry - tp_pips * PIP

            exit_pnl = None
            for j in range(entry_i, entry_i + max_hold):
                hit_sl = high[j] >= sl
                hit_tp = low[j] <= tp

                if hit_sl:
                    exit_pnl = -sl_pips
                    next_allowed = j + 1
                    break
                if hit_tp:
                    exit_pnl = tp_pips
                    next_allowed = j + 1
                    break

            if exit_pnl is None:
                j = entry_i + max_hold
                exit_pnl = (entry - close[j]) / PIP
                next_allowed = j + 1

        pnls.append(exit_pnl)
        trade_years.append(years_all[i])

    return np.array(pnls), np.array(trade_years)


def main():
    start = time.time()
    df = prepare()

    directions = ["long", "short"]
    breakout_bars_list = [24, 48, 72, 96]
    sessions = ["tokyo", "london", "ny", "london_ny"]
    h4_filters = ["none", "bull", "bear"]
    d1_filters = ["none", "bull", "bear"]
    sl_list = [30, 40, 50, 60]
    tp_list = [60, 80, 100, 120]
    max_hold_list = [24, 48]

    combos = list(product(
        directions, breakout_bars_list, sessions,
        h4_filters, d1_filters, sl_list, tp_list, max_hold_list
    ))

    print(f"検証パターン数: {len(combos):,}")
    print("検証開始...")

    results = []

    for idx, c in enumerate(combos, start=1):
        direction, bb, session, h4f, d1f, sl, tp, mh = c

        if direction == "long" and (h4f == "bear" or d1f == "bear"):
            continue
        if direction == "short" and (h4f == "bull" or d1f == "bull"):
            continue

        pnls, years = run_backtest(df, direction, bb, session, h4f, d1f, sl, tp, mh)
        stats = calc_stats(pnls, years)

        if stats is None:
            continue

        min_pf = np.nanmin([stats["pf_2003_2010"], stats["pf_2011_2018"], stats["pf_2019_2026"]])
        score = stats["pf"] + min_pf * 0.7

        results.append({
            "direction": direction,
            "breakout_bars": bb,
            "session": session,
            "h4_filter": h4f,
            "d1_filter": d1f,
            "sl_pips": sl,
            "tp_pips": tp,
            "max_hold_bars": mh,
            **stats,
            "min_period_pf": round(min_pf, 3),
            "score": round(score, 4),
        })

        if idx % 10 == 0:
            res = pd.DataFrame(results).sort_values(["score", "pf", "net_pips"], ascending=False)
            res.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
            print(f"{idx}/{len(combos)} 完了  経過 {((time.time()-start)/60):.1f}分  結果数 {len(results)}")

    res = pd.DataFrame(results).sort_values(["score", "pf", "net_pips"], ascending=False)
    res.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print("\n完了")
    print(f"結果保存: {OUT_FILE}")
    print(res.head(20).to_string(index=False))


if __name__ == "__main__":
    main()