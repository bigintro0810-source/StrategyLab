import json
import uuid
from pathlib import Path

# strategy_registry.pyと同じ「JSON1ファイルに全件」方式 - 件数がユーザーの
# 手作業ペースでしか増えない設定データなので、これで十分(DBは要らない)。
# saved_strategies/配下に置くのは、保存済みストラテジー(strategy_registry.py)
# と論理的に対になるデータだから。
REGISTRY_DIR = Path("saved_strategies")
REGISTRY_FILE = REGISTRY_DIR / "collections.json"


def load_collections() -> list[dict]:
    if not REGISTRY_FILE.exists():
        return []

    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def _write_collections(collections: list[dict]) -> None:
    # 一時ファイル+アトミックrename方式 - strategy_registry.py::_write_
    # registryと同じ理由(直接write_text()すると、同時書き込みが競合した
    # 時にファイルが壊れたJSONになり得るため、実際にregistry.json側で
    # 踏んだ不具合と同じクラスのバグをここでも予防する)。
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = REGISTRY_FILE.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(collections, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(REGISTRY_FILE)


def get_collection(collection_id: str) -> dict:
    for entry in load_collections():
        if entry["id"] == collection_id:
            return entry

    raise KeyError(f"タブが見つかりません: {collection_id}")


def create_collection(name: str) -> dict:
    entry = {"id": uuid.uuid4().hex, "name": name, "strategy_ids": []}
    collections = load_collections()
    collections.append(entry)
    _write_collections(collections)
    return entry


def rename_collection(collection_id: str, name: str) -> dict:
    collections = load_collections()

    for entry in collections:
        if entry["id"] == collection_id:
            entry["name"] = name
            _write_collections(collections)
            return entry

    raise KeyError(f"タブが見つかりません: {collection_id}")


def delete_collection(collection_id: str) -> None:
    collections = load_collections()
    remaining = [c for c in collections if c["id"] != collection_id]

    if len(remaining) == len(collections):
        raise KeyError(f"タブが見つかりません: {collection_id}")

    _write_collections(remaining)


def add_strategy(collection_id: str, strategy_id: str) -> dict:
    collections = load_collections()

    for entry in collections:
        if entry["id"] == collection_id:
            if strategy_id not in entry["strategy_ids"]:
                entry["strategy_ids"].append(strategy_id)
            _write_collections(collections)
            return entry

    raise KeyError(f"タブが見つかりません: {collection_id}")


def remove_strategy(collection_id: str, strategy_id: str) -> dict:
    collections = load_collections()

    for entry in collections:
        if entry["id"] == collection_id:
            entry["strategy_ids"] = [s for s in entry["strategy_ids"] if s != strategy_id]
            _write_collections(collections)
            return entry

    raise KeyError(f"タブが見つかりません: {collection_id}")
