from pathlib import Path
import itertools
import numpy as np
import pandas as pd


DATA_CANDIDATES = [
    "data/raw/USDJPY_2003_2026_15m.csv",
    "data/USDJPY_2003_2026_15m.csv",
    "input/USDJPY_2003_2026_15m.csv",
    "USDJPY_2003_2026_15m.csv",
]

OUTPUT_DIR = Path("output")


def find_data_file() -> Path:
    for p in DATA_CANDIDATES:
        path = Path(p)
        if path.exists():
            return path
    raise FileNotFoundError("15分足CSVが見つかりません。")


def load_price_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    rename = {}
    for c in df.columns:
        lc = c.lower().strip()
        if lc in ["time", "datetime", "date", "timestamp", "gmt time"]:
            rename[c] = "datetime"
        elif lc in ["open", "o"]:
            rename[c] = "open"
        elif lc in ["high", "h"]:
            rename[c] = "high"
        elif lc in ["low", "l"]:
            rename[c] = "low"
        elif lc in ["close", "c"]:
            rename[c] = "close"

    df = df.rename(columns=rename)

    required = ["datetime", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"必要な列がありません: {missing}")

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=required)
    df = df.sort_values("datetime").reset_index(drop=True)

    return df


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    diff = series.diff()
    gain = diff.clip(lower=0).rolling(length).mean()
    loss = (-diff.clip(upper=0)).rolling(length).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def is_in_session(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def calc_max_dd(profits: np.ndarray) -> float:
    if len(profits) == 0:
        return 0.0

    equity = profits.cumsum()
    running_max = np.maximum.accumulate(equity)
    dd = running_max - equity
    return float(dd.max()) if len(dd) else 0.0


def run_backtest(df: pd.DataFrame, params: dict) -> dict:
    pip = 0.01

    df = df.copy()
    df["ema"] = ema(df["close"], params["ema_length"])
    df["rsi"] = rsi(df["close"], 14)

    profits = []
    entry_times = []
    exit_times = []

    in_position = False
    entry = 0.0
    sl = 0.0
    tp = 0.0
    entry_time = None

    pending_signal = False
    signal_low = 0.0
    signal_high = 0.0
    signal_expire_i = -1

    start_hour = params["session_start"]
    end_hour = params["session_end"]

    for i in range(250, len(df) - 1):
        row = df.iloc[i]
        nxt = df.iloc[i + 1]
        dt = row["datetime"]

        hour = dt.hour
        weekday = dt.weekday()

        # ===== 保有中の決済 =====
        if in_position:
            # 週末決済：金曜4時以降で強制クローズ
            if params["use_weekend_exit"] and weekday == 4 and hour >= params["weekend_exit_hour"]:
                exit_price = row["close"]
                profits.append(entry - exit_price)
                entry_times.append(entry_time)
                exit_times.append(dt)
                in_position = False
                continue

            # 日跨ぎ回避：毎日4時で強制クローズ
            if params["use_daily_exit"] and hour == params["daily_exit_hour"]:
                exit_price = row["close"]
                profits.append(entry - exit_price)
                entry_times.append(entry_time)
                exit_times.append(dt)
                in_position = False
                continue

            hit_sl = row["high"] >= sl
            hit_tp = row["low"] <= tp

            if hit_sl and hit_tp:
                # 保守的にSL優先
                profits.append(entry - sl)
                entry_times.append(entry_time)
                exit_times.append(dt)
                in_position = False
                continue

            if hit_sl:
                profits.append(entry - sl)
                entry_times.append(entry_time)
                exit_times.append(dt)
                in_position = False
                continue

            if hit_tp:
                profits.append(entry - tp)
                entry_times.append(entry_time)
                exit_times.append(dt)
                in_position = False
                continue

            continue

        # ===== 監視中シグナルの処理 =====
        if pending_signal:
            if i > signal_expire_i:
                pending_signal = False
            else:
                # 基準足後に高値更新したらSL候補を更新
                if row["high"] > signal_high:
                    signal_high = row["high"]

                # 安値割れでショート
                if row["low"] < signal_low:
                    entry = row["close"]
                    sl = signal_high
                    risk = sl - entry

                    if risk > 0:
                        tp = entry - risk * params["rr"]
                        in_position = True
                        entry_time = dt

                    pending_signal = False
                    continue

        # ===== 新規シグナル判定 =====
        if not is_in_session(hour, start_hour, end_hour):
            continue

        body_pips = abs(row["close"] - row["open"]) / pip
        wick_pips = (row["high"] - row["low"]) / pip

        if body_pips < params["min_body_pips"]:
            continue

        if params["max_body_pips"] > 0 and body_pips > params["max_body_pips"]:
            continue

        if params["max_wick_pips"] > 0 and wick_pips > params["max_wick_pips"]:
            continue

        if row["close"] <= row["ema"]:
            continue

        ema_distance = (row["close"] - row["ema"]) / pip
        if ema_distance < params["ema_distance_pips"]:
            continue

        if row["rsi"] < params["rsi_min"]:
            continue

        lookback = params["breakout_bars"]
        if i - lookback < 0:
            continue

        recent_high = df["high"].iloc[i - lookback:i].max()

        # 終値が直近高値更新
        if row["close"] <= recent_high:
            continue

        pending_signal = True
        signal_low = row["low"]
        signal_high = row["high"]
        signal_expire_i = i + params["lookahead_bars"]

    profits = np.array(profits, dtype=float)

    trades = len(profits)
    wins = int((profits > 0).sum())
    losses = int((profits < 0).sum())

    gross_profit = float(profits[profits > 0].sum()) if trades else 0.0
    gross_loss = float(profits[profits < 0].sum()) if trades else 0.0
    net_profit = float(profits.sum()) if trades else 0.0

    if gross_loss < 0:
        pf = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        pf = 999.0
    else:
        pf = 0.0

    win_rate = wins / trades * 100 if trades else 0.0
    max_dd = calc_max_dd(profits)
    expected_value = net_profit / trades if trades else 0.0

    return {
        **params,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "net_profit": round(net_profit, 5),
        "gross_profit": round(gross_profit, 5),
        "gross_loss": round(gross_loss, 5),
        "profit_factor": round(pf, 3),
        "max_dd": round(max_dd, 5),
        "expected_value": round(expected_value, 5),
    }


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    data_path = find_data_file()
    print(f"読み込み: {data_path}")

    df = load_price_data(data_path)

    print(f"データ数: {len(df):,}")
    print(f"期間: {df['datetime'].min()} ～ {df['datetime'].max()}")

    grid = {
        "ema_length": [200],

        # 前に良かった周辺
        "min_body_pips": [20],
        "max_body_pips": [0],
        "max_wick_pips": [0],

        "lookahead_bars": [15],
        "breakout_bars": [30],

        "ema_distance_pips": [50],
        "rsi_min": [70],

        "rr": [1.2],

        # 日本時間想定
        "session_start": [8],
        "session_end": [3],

        # 前の良好版に近い設定
        "use_weekend_exit": [True],
        "weekend_exit_hour": [4],

        # これは前に悪化したのでまずFalse
        "use_daily_exit": [False],
        "daily_exit_hour": [4],
    }

    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))

    print(f"検証パターン数: {len(combos)}")

    results = []

    for idx, combo in enumerate(combos, start=1):
        params = dict(zip(keys, combo))
        result = run_backtest(df, params)
        result["param_id"] = idx
        results.append(result)

        if idx % 25 == 0 or idx == len(combos):
            print(f"{idx}/{len(combos)} 完了")

    result_df = pd.DataFrame(results)

    result_df = result_df.sort_values(
        by=["profit_factor", "net_profit", "max_dd", "trades"],
        ascending=[False, False, True, False],
    ).reset_index(drop=True)

    result_df.insert(0, "rank", range(1, len(result_df) + 1))

    output_path = OUTPUT_DIR / "ranking_total.csv"
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print("完了")
    print(f"出力: {output_path}")
    print(result_df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()