"""ユーザーが作ったチャートパターン(カスタムパターン)の読み込み。

このモジュールが解く問題
------------------------
バックテストは api_server とは**別プロセス**で走る(api_server.py が
`sys.executable main.py` などを subprocess 起動し、main.py はさらに
ProcessPoolExecutor で分岐する)。したがって「APIサーバーのメモリ上に指標を
登録する」だけでは、条件ビルダーには出るのにバックテストが
`未知のindicatorです` で落ちる、という最悪の壊れ方をする。

そのため、カスタムパターンは**必ずファイルに保存し、全プロセスの import 時に
ここから読み込む**。engine/conditions.py と engine/indicator_pool.py の末尾から
呼ばれるのがその入口。

循環importを避けるため、このモジュールは conditions / indicator_pool を
import しない。純粋なデータ(名前・関数・メタ情報)を返すだけにして、
レジストリへの実際の登録は呼び出し側で行う。

保存形式
--------
    custom_patterns/<pattern_id>/
        detector.py            検出コード本体
        meta.json              指標名・日本語ラベル・パラメータ定義など
        spec.md                日本語仕様書(B方式と同じ位置づけ)
        validation_report.json 検証ハーネスの結果

指標名は必ず ``custom_`` で始まる。既存364指標や
engine/indicator_pool.py の _CHART_PATTERN_PREFIXES との衝突を構造的に
起こらなくするため(_normalize_name で強制する)。
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# custom_patterns/ はリポジトリ直下。engine/ の1つ上。
CUSTOM_PATTERN_DIR = Path(__file__).resolve().parent.parent / "custom_patterns"

# 指標名の必須プレフィックス。既存指標と絶対に衝突させないための約束。
NAME_PREFIX = "custom_"

# 検出関数がモジュール内で持つべき名前。
ENTRY_POINT = "detect"

META_FILENAME = "meta.json"
DETECTOR_FILENAME = "detector.py"
SPEC_FILENAME = "spec.md"
REPORT_FILENAME = "validation_report.json"

SCHEMA_VERSION = 1


class CustomPatternUnavailableError(RuntimeError):
    """読み込みに失敗したカスタムパターンが実際に使われたときに投げる。

    読み込み時点では例外にせず、使われた瞬間にこれを投げる - こうしないと
    壊れたパターンが1つあるだけでアプリ全体(engine.conditions の import)が
    起動しなくなる。"""


@dataclass
class LoadedPattern:
    """読み込んだカスタムパターン1件。broken=True なら fn は
    CustomPatternUnavailableError を投げるスタブ。"""

    name: str
    label: str
    fn: Callable[..., Any]
    params: list[dict] = field(default_factory=list)
    kind: str = "boolean_signal"
    category: str = "chart_pattern"
    literal_choices: list[float] = field(default_factory=lambda: [1.0])
    param_choices: dict[str, list] = field(default_factory=dict)
    include_in_exploration: bool = False
    meta: dict = field(default_factory=dict)
    broken: bool = False
    reason: str = ""


def normalize_name(raw: str) -> str:
    """指標名を custom_ 始まりの安全な識別子へ正規化する。"""
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(raw).strip().lower())
    cleaned = cleaned.strip("_") or "pattern"
    if not cleaned.startswith(NAME_PREFIX):
        cleaned = NAME_PREFIX + cleaned
    return cleaned


def code_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _broken_stub(name: str, reason: str) -> Callable[..., Any]:
    """読み込めなかったパターンの代わりに登録する関数。

    使われた瞬間に日本語で理由を出して止める。従来の
    「未知のindicatorです」(engine/conditions.py)より原因が分かる。"""

    def _fn(df, **params):
        raise CustomPatternUnavailableError(
            f"カスタムパターン「{name}」が読み込めませんでした: {reason}\n"
            f"パターン作成画面で作り直すか、この条件を外してください。"
        )

    _fn.__name__ = name
    return _fn


def _load_one(directory: Path) -> LoadedPattern | None:
    """1ディレクトリを読む。meta.json が無ければカスタムパターンではないと
    みなして None(静かに無視)。それ以外の失敗は broken として返す
    - 握りつぶすと「保存したのに出てこない」原因が分からなくなるため。"""
    meta_path = directory / META_FILENAME
    if not meta_path.is_file():
        return None

    name = normalize_name(directory.name)
    label = name
    meta: dict = {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        name = normalize_name(meta.get("name") or directory.name)
        label = str(meta.get("label_ja") or meta.get("label") or name)
    except Exception as exc:
        return LoadedPattern(
            name=name, label=label, fn=_broken_stub(name, f"meta.jsonを読めません({exc})"),
            broken=True, reason=f"meta.jsonを読めません: {exc}",
        )

    if not meta.get("enabled", True):
        return None

    detector_path = directory / DETECTOR_FILENAME
    if not detector_path.is_file():
        reason = f"{DETECTOR_FILENAME} がありません"
        return LoadedPattern(name=name, label=label, fn=_broken_stub(name, reason),
                             meta=meta, broken=True, reason=reason)

    try:
        source = detector_path.read_text(encoding="utf-8")
    except Exception as exc:
        reason = f"{DETECTOR_FILENAME} を読めません: {exc}"
        return LoadedPattern(name=name, label=label, fn=_broken_stub(name, reason),
                             meta=meta, broken=True, reason=reason)

    # 保存時のコードと中身が変わっていないか。手で書き換えられた場合に
    # 検証済みでないコードが黙って走るのを防ぐ。
    expected = meta.get("code_sha256")
    if expected and expected != code_sha256(source):
        reason = "保存時から detector.py が書き換えられています(再検証が必要)"
        return LoadedPattern(name=name, label=label, fn=_broken_stub(name, reason),
                             meta=meta, broken=True, reason=reason)

    try:
        fn = compile_detector(source, name)
    except Exception as exc:
        reason = f"コードの読み込みに失敗: {exc}"
        return LoadedPattern(name=name, label=label, fn=_broken_stub(name, reason),
                             meta=meta, broken=True, reason=reason)

    params = meta.get("params") or []
    return LoadedPattern(
        name=name,
        label=label,
        fn=fn,
        params=list(params),
        kind=str(meta.get("kind") or "boolean_signal"),
        category=str(meta.get("category") or "chart_pattern"),
        literal_choices=list(meta.get("literal_choices") or [1.0]),
        param_choices=dict(meta.get("param_choices") or {}),
        include_in_exploration=bool(meta.get("include_in_exploration", False)),
        meta=meta,
    )


def compile_detector(source: str, name: str) -> Callable[..., Any]:
    """detector.py のソースを実行して検出関数を取り出す。

    ここでは AST ホワイトリスト検査は行わない - それは保存前に
    engine/custom_pattern_validate.py が別プロセスで済ませている。
    ここまで来たコードは「検証を通って保存されたもの」という前提。"""
    namespace: dict[str, Any] = {"__name__": f"custom_pattern_{name}"}
    exec(compile(source, f"<custom_pattern:{name}>", "exec"), namespace)
    fn = namespace.get(ENTRY_POINT)
    if not callable(fn):
        raise ValueError(f"{DETECTOR_FILENAME} に {ENTRY_POINT}() が見つかりません")
    return fn


def load_all(directory: Path | None = None) -> list[LoadedPattern]:
    """custom_patterns/ 配下を全て読む。名前順に固定して、プロセスごとに
    登録順がぶれないようにする。"""
    root = Path(directory) if directory is not None else CUSTOM_PATTERN_DIR
    if not root.is_dir():
        return []

    loaded: list[LoadedPattern] = []
    seen: set[str] = set()
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        try:
            item = _load_one(child)
        except Exception:
            # ここに来るのは _load_one 自体のバグ。1件のせいで
            # アプリが起動しなくなるのは避けたいので握るが、必ず出力する。
            print(
                f"[custom_patterns] {child.name} の読み込みで想定外の例外:\n"
                f"{traceback.format_exc()}",
                file=sys.stderr,
            )
            continue
        if item is None or item.name in seen:
            continue
        seen.add(item.name)
        loaded.append(item)
    return loaded


def registry_entries(patterns: list[LoadedPattern] | None = None) -> dict[str, Callable]:
    """engine/conditions.py の INDICATOR_REGISTRY へ入れる形にする。

    レジストリの契約は (df, **params) -> np.ndarray[float]。カスタムパターンの
    detect() も同じ契約にしてあるので、そのまま渡せる。"""
    items = load_all() if patterns is None else patterns
    return {p.name: p.fn for p in items}
