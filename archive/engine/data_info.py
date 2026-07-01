def show_data_info(df, symbol="USDJPY", timeframe="15m"):
    print()
    print("=" * 50)
    print("Data Info")
    print("=" * 50)

    print(f"Symbol    : {symbol}")
    print(f"Timeframe : {timeframe}")
    print(f"Rows      : {len(df):,}")
    print(f"Columns   : {len(df.columns)}")

    print()
    print("Column Names:")
    print(list(df.columns))

    print()
    print("First Row:")
    print(df.head(1))

    print()
    print("Last Row:")
    print(df.tail(1))

    print("=" * 50)