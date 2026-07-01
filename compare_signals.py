from pathlib import Path
import pandas as pd


TV_CSV = Path("data/raw/TV_USDJPY_15m.csv")
OUTPUT = Path("output/tv_signal_conditions.csv")


def main():
    df = pd.read_csv(TV_CSV)

    df["datetime"] = pd.to_datetime(df["time"])
    df["datetime"] = df["datetime"].dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)

    for c in ["open", "high", "low", "close", "EMA200", "RSI", "基準足安値"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    pip = 0.01

    hours = df["datetime"].dt.hour

    df["session_ok"] = (hours >= 8) | (hours < 3)
    df["bullish_ok"] = df["close"] > df["open"]
    df["body_ok"] = (df["close"] - df["open"]) >= 20 * pip
    df["ema_ok"] = (df["close"] > df["EMA200"]) & ((df["close"] - df["EMA200"]) >= 50 * pip)
    df["rsi_ok"] = df["RSI"] > 70

    df["recent_high"] = df["high"].rolling(30).max().shift(1)
    df["breakout_ok"] = df["close"] > df["recent_high"]

    df["python_signal"] = (
        df["session_ok"]
        & df["bullish_ok"]
        & df["body_ok"]
        & df["ema_ok"]
        & df["rsi_ok"]
        & df["breakout_ok"]
    )

    df["tv_signal_active"] = df["基準足安値"].notna()

    cols = [
        "datetime", "open", "high", "low", "close",
        "EMA200", "RSI", "基準足安値",
        "session_ok", "bullish_ok", "body_ok",
        "ema_ok", "rsi_ok", "recent_high", "breakout_ok",
        "python_signal", "tv_signal_active",
    ]

    out = df[cols].copy()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

    print("完了")
    print(f"出力: {OUTPUT}")
    print("")
    print("条件別件数")
    for c in ["session_ok", "bullish_ok", "body_ok", "ema_ok", "rsi_ok", "breakout_ok", "python_signal", "tv_signal_active"]:
        print(f"{c}: {int(df[c].sum())}")

    print("")
    print("python_signal 上位20件")
    print(df[df["python_signal"]][cols].head(20).to_string(index=False))

    print("")
    print("TV signal active だが python_signal ではない上位20件")
    mismatch = df[df["tv_signal_active"] & ~df["python_signal"]]
    print(mismatch[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()