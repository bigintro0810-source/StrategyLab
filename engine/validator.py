def validate_ohlc_data(df):
    print()
    print("=" * 50)
    print("Data Validation")
    print("=" * 50)

    required_columns = ["Date", "Open", "High", "Low", "Close"]

    # 必須列チェック
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        print("❌ 必須列が足りません")
        print("足りない列:", missing_columns)
        return False

    print("✅ 必須列チェック OK")

    # データ件数チェック
    if len(df) == 0:
        print("❌ データが空です")
        return False

    print(f"✅ データ件数 OK: {len(df):,} 行")

    # 欠損値チェック
    missing_values = df[required_columns].isna().sum()
    total_missing = missing_values.sum()

    if total_missing > 0:
        print("⚠ 欠損値があります")
        print(missing_values)
    else:
        print("✅ 欠損値チェック OK")

    # 時系列チェック
    try:
        dates = df["Date"]
        if dates.is_monotonic_increasing:
            print("✅ 時系列チェック OK")
        else:
            print("⚠ Date が時系列順ではありません")
    except Exception as e:
        print("⚠ 時系列チェックでエラー:", e)

    print("=" * 50)

    return True