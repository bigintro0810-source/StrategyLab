import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

REGISTRY_DIR = Path("saved_strategies")
REGISTRY_FILE = REGISTRY_DIR / "registry.json"

METRIC_COLUMNS = [
    "net_profit",
    "profit_factor",
    "max_dd",
    "win_rate",
    "trades",
    "recovery_factor",
]

SNAPSHOT_FILES = [
    "report.html",
    "trade_log.csv",
    "equity_curve.csv",
    "ranking_total.csv",
]


def _new_id(mode: str, timeframe: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{timestamp}_{mode}_{timeframe}_{suffix}"


def load_registry() -> list[dict]:
    if not REGISTRY_FILE.exists():
        return []

    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def _write_registry(entries: list[dict]) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_strategy(
    output_dir: Path,
    mode: str,
    timeframe: str,
    best_row: dict,
    params: dict,
    name: str | None = None,
    tags: list[str] | None = None,
    memo: str = "",
    favorite: bool = False,
    strategy_config: str | None = None,
) -> dict:
    strategy_id = _new_id(mode, timeframe)
    snapshot_dir = REGISTRY_DIR / strategy_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for filename in SNAPSHOT_FILES:
        source = output_dir / filename
        if source.exists():
            shutil.copy2(source, snapshot_dir / filename)

    metrics = {
        column: best_row[column]
        for column in METRIC_COLUMNS
        if column in best_row
    }

    entry = {
        "id": strategy_id,
        "name": name or strategy_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "timeframe": timeframe,
        "strategy_config": strategy_config,
        "tags": tags or [],
        "memo": memo,
        "favorite": favorite,
        "params": params,
        "metrics": metrics,
        "snapshot_dir": str(snapshot_dir),
    }

    entries = load_registry()
    entries.append(entry)
    _write_registry(entries)

    return entry


def get_strategy(strategy_id: str) -> dict:
    for entry in load_registry():
        if entry["id"] == strategy_id:
            return entry

    raise KeyError(f"保存された戦略が見つかりません: {strategy_id}")


def list_strategies(tag: str | None = None, favorite_only: bool = False) -> list[dict]:
    entries = load_registry()

    if tag is not None:
        entries = [entry for entry in entries if tag in entry["tags"]]

    if favorite_only:
        entries = [entry for entry in entries if entry["favorite"]]

    return entries


def update_strategy(strategy_id: str, **changes) -> dict:
    entries = load_registry()

    for entry in entries:
        if entry["id"] == strategy_id:
            entry.update(changes)
            _write_registry(entries)
            return entry

    raise KeyError(f"保存された戦略が見つかりません: {strategy_id}")


def add_tags(strategy_id: str, tags: list[str]) -> dict:
    entry = get_strategy(strategy_id)
    merged = sorted(set(entry["tags"]) | set(tags))
    return update_strategy(strategy_id, tags=merged)


def remove_tag(strategy_id: str, tag: str) -> dict:
    entry = get_strategy(strategy_id)
    remaining = [t for t in entry["tags"] if t != tag]
    return update_strategy(strategy_id, tags=remaining)


def set_memo(strategy_id: str, memo: str) -> dict:
    return update_strategy(strategy_id, memo=memo)


def toggle_favorite(strategy_id: str) -> dict:
    entry = get_strategy(strategy_id)
    return update_strategy(strategy_id, favorite=not entry["favorite"])


def rename_strategy(strategy_id: str, name: str) -> dict:
    return update_strategy(strategy_id, name=name)
