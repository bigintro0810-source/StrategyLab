from config import *

from engine.loader import load_csv
from engine.normalizer import normalize_ohlc_columns
from engine.data_info import show_data_info
from engine.validator import validate_ohlc_data
from engine.backtest import run_backtest

from strategies.ema_sample import ema_sample_strategy

from indicators import ta


def main():

    print("=" * 50)
    print("Strategy Lab")
    print("=" * 50)

    file = RAW_DATA_DIR / "USDJPY_2003_2026_15m.csv"

    df = load_csv(file)
    df = normalize_ohlc_columns(df)

    show_data_info(
        df,
        symbol="USDJPY",
        timeframe="15m"
    )

    if not validate_ohlc_data(df):
        print("CSVに問題があるため終了します。")
        return

    df["EMA200"] = ta.ema(df["Close"], 200)
    df["SMA200"] = ta.sma(df["Close"], 200)
    df["RSI14"] = ta.rsi(df["Close"], 14)
    df["ATR14"] = ta.atr(df, 14)

    print()
    print("=" * 50)
    print("Indicator Test")
    print("=" * 50)

    print(
        df[
            [
                "Close",
                "EMA200",
                "SMA200",
                "RSI14",
                "ATR14"
            ]
        ].tail(10)
    )

    result = run_backtest(
        df,
        ema_sample_strategy
    )

    print()
    print("=" * 50)
    print("Backtest Result")
    print("=" * 50)

    print(result)


if __name__ == "__main__":
    main()