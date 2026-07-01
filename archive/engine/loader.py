import pandas as pd


def load_csv(file_path):
    """
    CSVを読み込んでDataFrameを返す
    """

    df = pd.read_csv(file_path)

    print("=" * 50)
    print("CSV 読み込み完了")
    print("=" * 50)
    print(f"行数 : {len(df):,}")
    print(f"列数 : {len(df.columns)}")
    print()
    print(df.head())

    return df