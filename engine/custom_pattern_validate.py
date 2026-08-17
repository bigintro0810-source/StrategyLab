"""カスタムパターンの検証ハーネス。

LLMが生成した検出コードを保存・登録する前に、必ずここを通す。
**1つでも不合格があれば保存させない。**

何を見て、何を見ていないか
--------------------------
見るのは「コードとして壊れていないか」であって「日本語で書いた意図どおりか」
ではない。既存の33パターンには参考元のPine Scriptという答え合わせの対象が
あったが、生成パターンには無い。意図との一致は、最後に人がチャートと
検出件数を見て判断するしかない - そのための材料(件数・割合・最初と最後の
検出日時・間隔の中央値)をレポートとして返す。

検査項目
--------
1. 構文ガード   AST検査。許可した以外のimportや危険な呼び出しを拒否
2. 形式         1次元・長さ一致・float化可能・infなし・boolean型なら0/1のみ
3. 先読み       f(df[:n]) と f(df[:n+k])[:n] が完全一致するか  ← ハウスルール⑤
4. 再現性       2回実行してビット一致
5. 例外耐性     実データ + 異常データ(短い・値動きゼロ・NaN)で落ちない
6. 速度         ウォームアップ後に計測。遅い検出器は自動探索を壊すので落とす
7. 検出件数     0件は不合格。全バーの5%超も不合格

engine/custom_patterns.py と同じく、conditions / indicator_pool を import
しない(循環import回避 + 検証を軽くするため)。
"""

from __future__ import annotations

import ast
import json
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

# --- 構文ガードの許可リスト -------------------------------------------------
ALLOWED_IMPORTS = {"numpy", "numba", "pandas", "math"}
# 名前で呼ばれたら拒否する関数。うっかりファイルを触る/任意コードを走らせる系。
FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "open", "__import__", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "breakpoint", "exit", "quit",
}
# 属性アクセスで拒否するもの。__class__ 等からの回り込みを防ぐ。
FORBIDDEN_ATTR_PREFIX = "__"

# --- 速度のしきい値(10万本あたり) -----------------------------------------
SPEED_FAIL_MS_PER_100K = 2000.0
SPEED_WARN_MS_PER_100K = 500.0

# --- 検出件数のしきい値 -----------------------------------------------------
MAX_DETECTION_RATIO = 0.05   # 全バーの5%を超えたら「ほぼ常時ON」で無意味

# --- 先読みテストの設定 -----------------------------------------------------
LOOKAHEAD_TAIL_SIZES = (1, 5, 50, 200)
LOOKAHEAD_SAMPLES = 3


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationResult:
    ok: bool = False
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, passed, detail))
        return passed

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks],
            "warnings": list(self.warnings),
            "report": self.report,
        }


# ---------------------------------------------------------------------------
# 1. 構文ガード
# ---------------------------------------------------------------------------
def check_source_ast(source: str) -> tuple[bool, str]:
    """危険な構文が無いかをASTで見る。

    これは「うっかり」を止めるためのもので、本気の攻撃は防げない
    (numpy/pandasだけでもファイルシステムには到達できる)。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"Pythonの文法エラー: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    return False, f"許可されていないimport: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                return False, f"許可されていないimport: {node.module}"
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CALLS:
                return False, f"使用できない関数: {fn.id}()"
            if isinstance(fn, ast.Attribute) and fn.attr in FORBIDDEN_CALLS:
                return False, f"使用できない関数: .{fn.attr}()"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith(FORBIDDEN_ATTR_PREFIX):
                return False, f"使用できない属性アクセス: .{node.attr}"

    return True, ""


# ---------------------------------------------------------------------------
# 2. 検証用データ
# ---------------------------------------------------------------------------
def _synthetic_frames() -> list[tuple[str, pd.DataFrame]]:
    """異常系のデータ。実データでは通っても、こういうもので落ちる実装は多い。"""
    rng = np.random.default_rng(0)

    def frame(name: str, close: np.ndarray) -> tuple[str, pd.DataFrame]:
        n = len(close)
        high = close + np.abs(rng.normal(0, 0.05, n))
        low = close - np.abs(rng.normal(0, 0.05, n))
        return name, pd.DataFrame({
            "datetime": pd.date_range("2024-01-01", periods=n, freq="15min"),
            "open": close, "high": high, "low": low, "close": close,
            "volume": np.zeros(n),
        })

    frames = [
        frame("短いデータ(50本)", 100 + np.cumsum(rng.normal(0, 0.1, 50))),
        frame("値動きゼロ", np.full(300, 100.0)),
    ]
    # NaN欠損あり
    name, df = frame("NaN欠損あり", 100 + np.cumsum(rng.normal(0, 0.1, 300)))
    for col in ("open", "high", "low", "close"):
        df.loc[100:104, col] = np.nan
    frames.append((name, df))
    return frames


def _real_frames(max_sets: int = 3, bars: int = 40000) -> list[tuple[str, pd.DataFrame]]:
    """実データ。無ければ空リストを返す(合成データだけで検証を続ける)。"""
    try:
        from engine.data_loader import find_data_file, load_price_data
    except Exception:
        return []

    out: list[tuple[str, pd.DataFrame]] = []
    for symbol in ("USDJPY", "EURUSD", "GBPJPY"):
        if len(out) >= max_sets:
            break
        try:
            df = load_price_data(find_data_file("15m", symbol))
            df = df.reset_index(drop=True).tail(bars).reset_index(drop=True)
            out.append((f"{symbol} 15分足", df))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# 3. 各検査
# ---------------------------------------------------------------------------
def _coerce_output(raw: Any, n: int) -> np.ndarray:
    arr = np.asarray(raw)
    if arr.ndim != 1:
        raise ValueError(f"戻り値が1次元ではありません(shape={arr.shape})")
    if len(arr) != n:
        raise ValueError(f"戻り値の長さが入力と違います({len(arr)} != {n})")
    return arr.astype(float)


def _check_shape(fn: Callable, df: pd.DataFrame, params: dict, res: ValidationResult) -> np.ndarray | None:
    try:
        arr = _coerce_output(fn(df, **params), len(df))
    except Exception as exc:
        res.add("戻り値の形式", False, f"{type(exc).__name__}: {exc}")
        return None
    if np.isinf(arr).any():
        res.add("戻り値の形式", False, "infが含まれています")
        return None
    uniq = set(np.unique(arr[~np.isnan(arr)]).tolist())
    if not uniq <= {0.0, 1.0}:
        res.add("戻り値の形式", False,
                f"0.0/1.0以外の値が含まれています(例: {sorted(uniq)[:5]})")
        return None
    res.add("戻り値の形式", True, "1次元・長さ一致・0.0/1.0のみ")
    return arr


def _check_lookahead(fn: Callable, df: pd.DataFrame, params: dict, res: ValidationResult) -> bool:
    """先読みしていないか。

    未来のバーを見ている実装は、データを後ろに継ぎ足すと過去の出力が
    変わってしまう。それを直接突く。ハウスルール⑤の自動チェック。"""
    n_total = len(df)
    if n_total < 600:
        res.add("先読みしていないか", True, "データが短いため省略")
        return True

    rng = random.Random(12345)
    for _ in range(LOOKAHEAD_SAMPLES):
        n = rng.randint(int(n_total * 0.4), n_total - max(LOOKAHEAD_TAIL_SIZES) - 1)
        try:
            base = _coerce_output(fn(df.iloc[:n].reset_index(drop=True), **params), n)
        except Exception as exc:
            res.add("先読みしていないか", False, f"途中までのデータで例外: {exc}")
            return False
        for k in LOOKAHEAD_TAIL_SIZES:
            try:
                longer = _coerce_output(
                    fn(df.iloc[:n + k].reset_index(drop=True), **params), n + k)
            except Exception as exc:
                res.add("先読みしていないか", False, f"データを{k}本足したら例外: {exc}")
                return False
            if not np.array_equal(base, longer[:n], equal_nan=True):
                diff = int(np.sum(~(base == longer[:n]) & ~(np.isnan(base) & np.isnan(longer[:n]))))
                res.add(
                    "先読みしていないか", False,
                    f"未来のバーを見ています。{n}本目までの結果が、{k}本足すと"
                    f"{diff}箇所変わりました(先読み・リペイントは禁止)",
                )
                return False
    res.add("先読みしていないか", True,
            f"末尾{LOOKAHEAD_TAIL_SIZES}本を足しても過去の出力は不変")
    return True


def _check_determinism(fn: Callable, df: pd.DataFrame, params: dict, res: ValidationResult) -> bool:
    try:
        a = _coerce_output(fn(df, **params), len(df))
        b = _coerce_output(fn(df, **params), len(df))
    except Exception as exc:
        res.add("再現性", False, f"{type(exc).__name__}: {exc}")
        return False
    ok = np.array_equal(a, b, equal_nan=True)
    res.add("再現性", ok, "2回実行してビット一致" if ok else "実行のたびに結果が変わります")
    return ok


def _check_robustness(fn: Callable, params: dict, res: ValidationResult) -> bool:
    ok = True
    details: list[str] = []
    for name, df in _synthetic_frames():
        try:
            _coerce_output(fn(df, **params), len(df))
            details.append(f"{name}:OK")
        except Exception as exc:
            ok = False
            details.append(f"{name}:{type(exc).__name__} {exc}")
    res.add("異常データ耐性", ok, " / ".join(details))
    return ok


def _measure_speed(fn: Callable, df: pd.DataFrame, params: dict) -> float:
    """ミリ秒/10万本。Numbaの初回JITを除くためウォームアップしてから測る。"""
    fn(df.iloc[:min(len(df), 2000)].reset_index(drop=True), **params)
    start = time.perf_counter()
    fn(df, **params)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return elapsed_ms / max(len(df), 1) * 100000.0


# ---------------------------------------------------------------------------
# 4. 入口
# ---------------------------------------------------------------------------
def validate(source: str, params: dict | None = None, name: str = "custom_pattern") -> ValidationResult:
    """検出コードを検証する。戻り値の ok が True のときだけ保存してよい。"""
    from engine.custom_patterns import compile_detector

    res = ValidationResult()
    params = dict(params or {})

    ok, detail = check_source_ast(source)
    if not res.add("構文ガード", ok, detail or "許可された範囲のコードです"):
        return res

    try:
        fn = compile_detector(source, name)
    except Exception as exc:
        res.add("読み込み", False, f"{type(exc).__name__}: {exc}")
        return res
    res.add("読み込み", True, "detect() が見つかりました")

    datasets = _real_frames() + _synthetic_frames()[:0]
    if not datasets:
        # 実データが無い環境でも検証できるよう、合成データで代替する。
        datasets = [("合成データ", _synthetic_frames()[0][1])]
        res.warnings.append(
            "実データが見つからないため合成データで検証しました。"
            "検出件数は参考値として扱ってください。"
        )

    primary_name, primary = datasets[0]

    arr = _check_shape(fn, primary, params, res)
    if arr is None:
        return res
    if not _check_determinism(fn, primary, params, res):
        return res
    if not _check_lookahead(fn, primary, params, res):
        return res
    if not _check_robustness(fn, params, res):
        return res

    # --- 速度と検出件数 ---
    per_dataset: list[dict] = []
    speed_ms = 0.0
    total_hits = 0
    for label, df in datasets:
        try:
            values = _coerce_output(fn(df, **params), len(df))
        except Exception as exc:
            res.add("実データでの実行", False, f"{label}: {type(exc).__name__} {exc}")
            return res
        hits = int(np.nansum(values == 1.0))
        total_hits += hits
        ratio = hits / max(len(df), 1)
        idx = np.flatnonzero(values == 1.0)
        times = df["datetime"] if "datetime" in df.columns else None
        gaps = np.diff(idx)
        per_dataset.append({
            "dataset": label,
            "bars": int(len(df)),
            "detections": hits,
            "ratio_pct": round(ratio * 100.0, 4),
            "first": str(times.iloc[idx[0]]) if times is not None and len(idx) else None,
            "last": str(times.iloc[idx[-1]]) if times is not None and len(idx) else None,
            "median_gap_bars": int(np.median(gaps)) if len(gaps) else None,
        })
        speed_ms = max(speed_ms, _measure_speed(fn, df, params))
        if ratio > MAX_DETECTION_RATIO:
            res.add("検出件数", False,
                    f"{label} で全バーの{ratio * 100:.1f}%が検出されました"
                    f"(上限{MAX_DETECTION_RATIO * 100:.0f}%)。"
                    f"ほぼ常時ONの条件は指標として意味を持ちません")
            res.report["per_dataset"] = per_dataset
            return res

    if total_hits == 0:
        res.add("検出件数", False,
                "どのデータでも1件も検出されませんでした。条件が厳しすぎるか、"
                "ロジックが意図どおり動いていません")
        res.report["per_dataset"] = per_dataset
        return res
    res.add("検出件数", True, f"合計{total_hits}件")

    speed_ok = speed_ms <= SPEED_FAIL_MS_PER_100K
    res.add("速度", speed_ok,
            f"10万本あたり {speed_ms:.0f}ms"
            + ("" if speed_ok else f"(上限{SPEED_FAIL_MS_PER_100K:.0f}ms)。"
                                   "遅い検出器は自動探索を実用不能にします"))
    if speed_ok and speed_ms > SPEED_WARN_MS_PER_100K:
        res.warnings.append(
            f"やや遅めです(10万本あたり{speed_ms:.0f}ms)。"
            f"自動探索に含めると全体が遅くなる可能性があります。"
        )

    res.report["per_dataset"] = per_dataset
    res.report["speed_ms_per_100k"] = round(speed_ms, 1)
    res.ok = not res.failures()
    return res


def _main() -> int:
    """subprocess から使う入口。stdin に {"source":..., "params":...} を渡すと
    stdout に検証結果のJSONを返す。

    別プロセスにするのは、生成コードの無限ループやメモリ爆発から
    APIサーバー本体を守るため(呼び出し側で timeout を掛ける)。"""
    payload = json.loads(sys.stdin.read())
    result = validate(
        payload["source"], payload.get("params") or {}, payload.get("name") or "custom_pattern"
    )
    sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
