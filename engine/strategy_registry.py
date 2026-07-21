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
    "sharpe_ratio",
    "sortino_ratio",
    "cagr",
    "calmar_ratio",
]

SNAPSHOT_FILES = [
    "report.html",
    "trade_log.csv",
    "equity_curve.csv",
    "ranking_total.csv",
    # 年別成績/月別成績/安定度タブ(api_server.pyの
    # GET /api/strategies/{id}/resultsが読む)用 - 以前はここに無く、
    # 保存済みストラテジーのそれらのタブが常に空になっていた。
    "yearly_analysis.csv",
    "monthly_analysis.csv",
    "stability_analysis.csv",
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
    """Writes via a temp file + atomic rename rather than REGISTRY_FILE.
    write_text() directly - a plain write_text() truncates-then-writes in
    place, so two concurrent saves (e.g. the same row's 🔖 clicked twice in
    quick succession, or a save racing a rename/delete) can interleave
    mid-write and leave registry.json as a corrupted hybrid of both writes
    (invalid JSON, breaking every /api/strategies read - actually hit this:
    a rapid double-save left the file with an extra stray ']' followed by
    a truncated second document, losing several entries until manually
    recovered from each entry's own saved_strategies/{id}/ranking_total.csv
    snapshot). Path.replace() is an atomic rename on both POSIX and Windows,
    so any concurrent writer's version fully wins rather than interleaving -
    a "last write wins" race can still drop one writer's update, but the
    file itself can never end up corrupted/unparseable."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = REGISTRY_FILE.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(REGISTRY_FILE)


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
    symbol: str = "USDJPY",
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
        "symbol": symbol,
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


def delete_strategy(strategy_id: str) -> None:
    entries = load_registry()
    entry = next((e for e in entries if e["id"] == strategy_id), None)
    if entry is None:
        raise KeyError(f"保存された戦略が見つかりません: {strategy_id}")

    remaining = [e for e in entries if e["id"] != strategy_id]
    _write_registry(remaining)

    snapshot_dir = Path(entry["snapshot_dir"])
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
