"""カスタムパターン(ユーザーが作るチャートパターン)の基盤テスト。

このプロジェクトの慣習に合わせたプレーンスクリプト形式(pytest非依存)。
    python tests/test_custom_patterns.py

ここで守りたいのは主に2つ:

1. **検証ハーネスが本当に不正なコードを落とすか。**
   落とせないハーネスは有害でしかない(「検証済み」という嘘の安心を与える)。
   特に先読みテストは、既存33パターンで守ってきたハウスルール⑤を
   自動化したものなので、意図的に未来を見るコードで必ず突く。

2. **登録が別プロセスから見えるか。**
   バックテストは api_server とは別プロセスで走るため、メモリ上だけの登録は
   「条件ビルダーには出るのにバックテストが落ちる」という壊れ方をする。
"""

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import engine.custom_patterns as cp
from engine.custom_pattern_validate import check_source_ast, validate

FAILURES: list[str] = []
ROOT = Path(__file__).resolve().parent.parent


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


# --- 検証にかけるサンプルコード ---------------------------------------------

GOOD = '''
import numpy as np


def detect(df, lookback=20, **params):
    lookback = max(2, int(lookback))
    open_a = df["open"].to_numpy(dtype=float)
    high_a = df["high"].to_numpy(dtype=float)
    close_a = df["close"].to_numpy(dtype=float)
    n = len(close_a)
    out = np.zeros(n)
    if n < lookback + 3:
        return out
    bullish = close_a > open_a
    for i in range(lookback + 2, n):
        if not (bullish[i] and bullish[i - 1] and bullish[i - 2]):
            continue
        if close_a[i] > high_a[i - lookback:i].max():
            out[i] = 1.0
    return out
'''

# 未来のバーを見ている。先読みテストが落とせなければハーネスが無意味。
LOOKAHEAD = '''
import numpy as np


def detect(df, **params):
    close = df["close"].to_numpy(dtype=float)
    out = np.zeros(len(close))
    future = np.roll(close, -1)
    out[:-1] = (future[:-1] > close[:-1]).astype(float)
    return out
'''

# 全バーで1を返す。指標として意味を持たない。
ALWAYS_ON = '''
import numpy as np


def detect(df, **params):
    return np.ones(len(df))
'''

# 1件も出ない。
NEVER = '''
import numpy as np


def detect(df, **params):
    return np.zeros(len(df))
'''


def test_ast_gate_blocks_dangerous_code():
    """構文ガード。許可外のimportと危険な呼び出しを拒否する。"""
    ok, _ = check_source_ast(GOOD)
    check("構文ガード 正常なコードは通る", ok)

    for label, src in (
        ("os のimport", "import os\ndef detect(df, **p):\n    return None\n"),
        ("from os import", "from os import path\ndef detect(df, **p):\n    return None\n"),
        ("subprocess", "import subprocess\ndef detect(df, **p):\n    return None\n"),
        ("eval", "def detect(df, **p):\n    return eval('1')\n"),
        ("exec", "def detect(df, **p):\n    exec('x=1')\n"),
        ("open", "def detect(df, **p):\n    open('x','w')\n"),
        ("__import__", "def detect(df, **p):\n    __import__('os')\n"),
        ("__class__経由の回り込み", "def detect(df, **p):\n    return (1).__class__\n"),
    ):
        ok, detail = check_source_ast(src)
        check(f"構文ガード {label} を拒否", not ok, detail)


def test_harness_rejects_lookahead():
    """**最重要**: 未来を見るコードを確実に落とす。

    これが通ってしまうと、検証ハーネス全体が「検証したふり」になる。"""
    res = validate(LOOKAHEAD, {}, "custom_lookahead_test")
    check("先読みするコードは不合格になる", not res.ok)
    names = [c.name for c in res.checks if not c.passed]
    check("落ちた理由が先読みである", "先読みしていないか" in names, f"got {names}")


def test_harness_rejects_useless_detectors():
    """常時ON / 検出ゼロ のように指標として成立しないものを落とす。"""
    res_on = validate(ALWAYS_ON, {}, "custom_always_on")
    check("全バー検出は不合格になる", not res_on.ok)

    res_never = validate(NEVER, {}, "custom_never")
    check("検出ゼロは不合格になる", not res_never.ok)
    names = [c.name for c in res_never.checks if not c.passed]
    check("検出ゼロの理由が件数である", "検出件数" in names, f"got {names}")


def test_harness_accepts_a_sound_detector():
    """まっとうなコードは通り、レポートに判断材料が入る。"""
    res = validate(GOOD, {}, "custom_good")
    check("正常なコードは合格する", res.ok,
          "; ".join(f"{c.name}:{c.detail}" for c in res.checks if not c.passed))
    per = res.report.get("per_dataset") or []
    check("データセット別のレポートが出る", len(per) > 0)
    if per:
        first = per[0]
        check("レポートに検出件数と割合が入る",
              "detections" in first and "ratio_pct" in first, str(first))
        check("レポートに最初と最後の検出時刻が入る",
              "first" in first and "last" in first, str(first))
    check("速度が計測されている", "speed_ms_per_100k" in res.report, str(res.report.keys()))


def test_name_normalization_prevents_collisions():
    """指標名は必ず custom_ 始まりへ正規化される。

    既存364指標や _CHART_PATTERN_PREFIXES との衝突を構造的に起こさないため。"""
    check("プレフィックスが付く", cp.normalize_name("my pattern") == "custom_my_pattern")
    check("既に付いていれば二重に付かない",
          cp.normalize_name("custom_foo") == "custom_foo")
    check("記号は落とされる", cp.normalize_name("a/b*c") == "custom_a_b_c")
    check("空文字でも壊れない", cp.normalize_name("") == "custom_pattern")
    # 既存指標名を横取りできないこと
    from engine.conditions import INDICATOR_REGISTRY
    for builtin in ("rsi", "ema", "triple_top", "head_and_shoulders"):
        check(f"既存指標 {builtin} を横取りできない",
              cp.normalize_name(builtin) not in INDICATOR_REGISTRY
              or cp.normalize_name(builtin).startswith("custom_"))


def test_broken_pattern_degrades_gracefully(tmp_root: Path | None = None):
    """壊れたパターンはアプリを落とさず、使った時に日本語で理由を出す。

    従来の「未知のindicatorです」より原因が分かるようにするのが狙い。"""
    root = ROOT / "custom_patterns"
    workdir = root / "custom_zz_broken_selftest"
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        # code_sha256 をわざと合わない値にする(=保存後に書き換えられた状態)
        io.open(workdir / "meta.json", "w", encoding="utf-8").write(json.dumps({
            "schema_version": 1, "name": "custom_zz_broken_selftest",
            "label_ja": "自己テスト用", "code_sha256": "0" * 64,
        }, ensure_ascii=False))
        io.open(workdir / "detector.py", "w", encoding="utf-8").write(
            "import numpy as np\ndef detect(df, **p):\n    return np.zeros(len(df))\n"
        )

        loaded = {p.name: p for p in cp.load_all()}
        item = loaded.get("custom_zz_broken_selftest")
        check("壊れたパターンも読み込み自体は成功する(例外で落ちない)", item is not None)
        if item is None:
            return
        check("brokenとして印が付く", item.broken, item.reason)

        df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]})
        try:
            item.fn(df)
            check("使うと専用の例外が出る", False, "例外が出なかった")
        except cp.CustomPatternUnavailableError as exc:
            msg = str(exc)
            check("使うと専用の例外が出る", True)
            check("エラーに日本語で理由が入る", "読み込めませんでした" in msg, msg[:120])
            check("エラーにパターン名が入る", "custom_zz_broken_selftest" in msg, msg[:120])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_registration_is_visible_from_a_separate_process():
    """**最重要**: 別プロセスから登録が見えるか。

    バックテストは api_server とは別プロセス(sys.executable main.py)で走る。
    ここが通らないと「条件ビルダーには出るのにバックテストが落ちる」ことになる。
    このテスト自身も subprocess を起こして確かめる。"""
    sample = ROOT / "custom_patterns" / "custom_breakout_three_soldiers"
    if not sample.is_dir():
        check("サンプルカスタムパターンが存在する", False, str(sample))
        return
    check("サンプルカスタムパターンが存在する", True)

    code = (
        "from engine.conditions import INDICATOR_REGISTRY;"
        "import engine.indicator_pool as ip;"
        "n='custom_breakout_three_soldiers';"
        "print(int(n in INDICATOR_REGISTRY),"
        "int(n in [s.name for s in ip.INDICATOR_POOL]),"
        "int(n in ip.LEVEL_PRESETS['advanced']),"
        "int(n in [s.name for s in ip.build_filtered_pool(categories=['chart_pattern'])]))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(ROOT),
        capture_output=True, text=True, timeout=300,
    )
    check("別プロセスがエラーなく起動する", proc.returncode == 0, proc.stderr[-300:])
    if proc.returncode != 0:
        return
    flags = proc.stdout.strip().split()
    check("別プロセスの INDICATOR_REGISTRY に載る", flags[0] == "1")
    check("別プロセスの INDICATOR_POOL に載る", flags[1] == "1")
    check("自動探索の advanced プリセットに載る", flags[2] == "1")
    check("チャートパターンのカテゴリに分類される", flags[3] == "1")


def test_custom_pattern_works_as_a_condition():
    """条件式エンジンから実際に評価できるか(バックテストと同じ経路)。"""
    from engine.conditions import evaluate_condition_tree

    try:
        from engine.data_loader import find_data_file, load_price_data
        df = load_price_data(find_data_file("15m", "USDJPY"))
        df = df.reset_index(drop=True).tail(20000).reset_index(drop=True)
    except Exception as exc:
        check("実データで条件式として評価できる", False, f"データ読み込み失敗: {exc}")
        return

    tree = {
        "indicator": "custom_breakout_three_soldiers",
        "params": {"lookback": 20},
        "operator": "==",
        "value": 1.0,
    }
    signal = evaluate_condition_tree(tree, df, "USDJPY", {}, 0.01)
    check("条件式としてBoolean系列が返る",
          isinstance(signal, np.ndarray) and len(signal) == len(df),
          f"{type(signal)} len={len(signal) if hasattr(signal, '__len__') else '?'}")
    check("実データで1件以上成立する", int(np.sum(signal)) > 0)


if __name__ == "__main__":
    test_ast_gate_blocks_dangerous_code()
    test_name_normalization_prevents_collisions()
    test_broken_pattern_degrades_gracefully()
    test_harness_rejects_lookahead()
    test_harness_rejects_useless_detectors()
    test_harness_accepts_a_sound_detector()
    test_registration_is_visible_from_a_separate_process()
    test_custom_pattern_works_as_a_condition()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll custom_patterns tests passed.")
