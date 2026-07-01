def normalize_ohlc_columns(df):
    """
    CSVの列名をStrategy Lab標準に変換する
    標準列名: Date, Open, High, Low, Close, Volume
    """

    rename_map = {
        "datetime": "Date",
        "date": "Date",
        "time": "Date",

        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",

        "volume": "Volume",
        "vol": "Volume",
        "tick_volume": "Volume",
    }

    df = df.rename(columns=rename_map)

    return df