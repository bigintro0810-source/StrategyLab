from pathlib import Path

import pandas as pd


class DataLoader:
    def __init__(self, data_dir: str = "data/raw"):
        self.data_dir = Path(data_dir)

        self.files = {
            "1m": "USDJPY_2003_2026_1m.csv",
            "5m": "USDJPY_2003_2026_5m.csv",
            "15m": "USDJPY_2003_2026_15m.csv",
            "1h": "USDJPY_2003_2026_1h.csv",
            "4h": "USDJPY_2003_2026_4h.csv",
            "1d": "USDJPY_2003_2026_1d.csv",
        }

    def load(self, timeframe: str) -> pd.DataFrame:
        if timeframe not in self.files:
            raise ValueError(f"未対応の時間足です: {timeframe}")

        file_path = self.data_dir / self.files[timeframe]

        if not file_path.exists():
            raise FileNotFoundError(f"データファイルが見つかりません: {file_path}")

        df = pd.read_csv(file_path)

        required_columns = ["datetime", "open", "high", "low", "close", "volume"]
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            raise ValueError(f"必要な列がありません: {missing_columns}")

        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)

        return df

    def available_timeframes(self) -> list[str]:
        return list(self.files.keys())