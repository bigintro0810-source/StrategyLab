from engine.data_loader import DataLoader
from engine.indicators import ema, sma, rsi, atr


def main():
    print("=== Strategy Lab ===")

    loader = DataLoader()
    df = loader.load("1m")

    df = df.head(1000).copy()

    df["sma_20"] = sma(df["close"], 20)
    df["ema_20"] = ema(df["close"], 20)
    df["rsi_14"] = rsi(df["close"], 14)
    df["atr_14"] = atr(df, 14)

    print(df[[
        "datetime",
        "close",
        "sma_20",
        "ema_20",
        "rsi_14",
        "atr_14",
    ]].tail(20))


if __name__ == "__main__":
    main()