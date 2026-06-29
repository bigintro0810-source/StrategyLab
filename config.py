from pathlib import Path

# プロジェクトルート
BASE_DIR = Path(__file__).resolve().parent

# フォルダ
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

OUTPUT_DIR = BASE_DIR / "output"
REPORT_DIR = BASE_DIR / "reports"
EXPORT_DIR = BASE_DIR / "exports"
LOG_DIR = BASE_DIR / "logs"

# バージョン
VERSION = "1.0.0"

# デフォルト設定
DEFAULT_SYMBOL = "USDJPY"
DEFAULT_TIMEFRAME = "15m"