# Strategy Lab フェーズ0：棚卸し結果と安全な整理手順

全68 .pyファイルのimport文を機械的に検証し、main.py起動時に実際に読み込まれるかどうかを追跡した結果です。削除・リファクタリングは一切行っていません。

---

## 1. 現在実際に使われているファイル一覧

### 1-A. main.py実行時に自動的に通る本番経路

| ファイル | 役割 |
|---|---|
| `main.py` | エントリーポイント |
| `engine/backtest_engine.py` | 本番バックテスト実行（`run_backtest`） |
| `engine/monte_carlo.py` | モンテカルロ分析（main.py末尾で自動実行） |

### 1-B. ユーザーが個別にコマンド実行する運用ツール（正常動作）

これらはmain.pyからは呼ばれませんが、単体で実行すれば正しく動作する現役ツールです。

| ファイル | 役割 | 依存関係 |
|---|---|---|
| `walk_forward.py`（root） | ウォークフォワード検証 | `main.py`の関数と`engine/backtest_engine.py`を再利用 |
| `analyze_walk_forward.py` | walk_forward.pyの出力を判定（PASS/CAUTION/FAIL） | 内部import無し、CSV読込のみ |
| `equity_curve.py`（root） | Equity Curve出力 | `engine/equity_curve.py` |
| `monte_carlo.py`（root） | モンテカルロ分析の単体実行 | `engine/monte_carlo.py` |
| `compare_tradingview.py` | TradingViewとの一致検証 | `engine/backtest_engine.py` |
| `analyze_monthly.py` / `analyze_yearly.py` / `analyze_stability.py` | 月別/年別/安定度の単体集計 | 内部import無し（※main.py内蔵ロジックと重複、後述） |
| `compare_signals.py` | シグナル一致率の手動検証 | 内部import無し |

**この12ファイルが「現在使われているもの」の全てです。**

---

## 2. 未接続・古い可能性があるファイル一覧

import文を全数確認した結果、**どこからも参照されていない、または参照元自体が孤立している**ファイル群です。性質の異なる3グループに分けました。

### 2-A. 設計は良いが未接続の「将来資産」候補（削除でなく活用を検討したいもの）

| ファイル/クラスタ | 内容 | 備考 |
|---|---|---|
| `engine/numba_backtest.py` | JIT高速バックテスト | `engine/optimizer.py`からのみ参照。本番エンジンより速い可能性あり |
| `engine/condition_engine.py` / `condition_config.py` | numpyベクトル化シグナル生成 | 同上のクラスタ内 |
| `engine/ranking.py` | 重み付きスコア方式ランキング | main.py内の独自ランキングと別方式 |
| `engine/walk_forward.py`（`WalkForwardTester`） | 汎用ウォークフォワード基盤 | root walk_forward.pyとは別物、未使用 |
| `engine/walk_forward_engine/_runner/_manager/_summary/_exporter/_result.py`（6ファイル） | 3層構成のウォークフォワード専用フレームワーク | クラスタ内でのみ結線、外部からの入口なし |
| `config/`（`strategy_config.py`, `scoring_config.py`, `walk_forward_config.py`, `scoring_weights.csv`） | dataclassベースの設定 | 一部はrerank_results.py等から参照されるが本流未使用 |
| `engine/data_loader.py`（`DataLoader`） | 時間足別データ管理 | main.pyは独自実装を使用中で未接続 |

### 2-B. 壊れている・実行時エラーになるファイル（優先度高、実害あり）

| ファイル | 問題 |
|---|---|
| `engine/csv_export.py` | `from engine.result import Result`としているが、`engine/result.py`には`Result`クラスが存在せず（実際は`BacktestResult`）。**importした瞬間にImportError**になる |
| `engine/fast_optimizer.py` | 同様に存在しない`Result`クラスをimport。ImportErrorになる |
| `engine/optimizer.py` | 同様に存在しない`Result`クラスをimport。ImportErrorになる |
| `rerank_results.py` | importは通るが、必要な入力`output/optimizer_results_session.csv`を生成するスクリプトがリポジトリ内に存在しない。**単独実行するとFileNotFoundErrorで即終了する** |
| `engine/tv_engine.py` / `engine/tv_state.py` | 0バイトの空ファイル |

### 2-C. 重複・矛盾があり価値が低いもの（archive候補、詳細は3節）

- `indicators/`パッケージ一式（`ema.py`/`sma.py`/`rsi.py`/`atr.py`/`ta.py`/`__init__.py`）：`engine/indicators.py`と同名関数だが計算式が異なり数値が一致しない。どこからも使われていない。
- `engine/cache.py`・`engine/indicator_manager.py`：上記`engine/indicators.py`版を使うが、両方とも呼び出し元がない。
- `engine/backtest.py`・`broker.py`・`order.py`・`position.py`・`trade.py`・`metrics.py`・`parameter_grid.py`：OOP版バックテストエンジンのクラスタ。`strategies/test_strategy.py`・`strategies/ema_sample.py`（どちらも孤立）からのみ部分的に参照。
- `engine/fast_backtest.py`・`engine/conditions.py`・`engine/loader.py`・`engine/data_info.py`・`engine/normalizer.py`・`engine/validator.py`・`engine/yearly_stats.py`・`engine/tv_types.py`：いずれも参照元ゼロ。
- `strategies/ema_sample.py`（空リストを返すだけのダミー実装）・`strategies/test_strategy.py`：孤立。
- `old_config.py`：完全にデッド。`config/`に代替あり。

---

## 3. archive候補の一覧（確信度つき）

archive＝削除ではなく、`archive/`のようなフォルダへ**移動して隔離するだけ**の候補です。

### 確信度：高（実害あり、または完全に重複・矛盾しており活用の見込みが薄い）

- `old_config.py`
- `engine/tv_engine.py` / `engine/tv_state.py`（空ファイル）
- `engine/csv_export.py`（壊れたimport）
- `indicators/`パッケージ一式（`engine/indicators.py`と数値不一致の重複）
- `engine/cache.py` / `engine/indicator_manager.py`（上記に依存し孤立）
- `engine/loader.py` / `engine/data_info.py` / `engine/normalizer.py` / `engine/validator.py` / `engine/yearly_stats.py`
- `engine/conditions.py`
- `strategies/ema_sample.py`（ダミー実装）

### 確信度：中（重複・孤立だが、将来使う可能性を一度検討してから決めたいもの）

- `engine/optimizer.py` / `engine/fast_optimizer.py` / `engine/fast_backtest.py`（壊れたimportの修正で活きる可能性あり。今のバックテストエンジンより速い可能性）
- `engine/numba_backtest.py`（同上、JIT高速化の資産）
- `engine/ranking.py`（別方式のランキング。V2.0で活かせないか検討の価値あり）
- `engine/walk_forward.py` + `walk_forward_engine/_runner/_manager/_summary/_exporter/_result.py`の7ファイル（設計は整っている。root版walk_forward.pyと統合するかどうかの判断が必要）
- `engine/backtest.py` / `broker.py` / `order.py` / `position.py` / `trade.py` / `metrics.py` / `parameter_grid.py`
- `strategies/test_strategy.py`
- `config/walk_forward_config.py`（値がroot walk_forward.pyと矛盾しているため要整理）
- `engine/tv_types.py`（TradingView連携の型定義。V3.0で使う予定なら残す価値あり）

### 要ユーザー確認（判断材料が不足しているもの）

- `strategy_lab_v1.py` / `strategy_lab_fast_v1.py` / `strategy_search.py`：engine非依存の旧世代プロトタイプ。まだ参照・比較用に使っていますか？ `reports/strategy_detail_v1.py`は`strategy_lab_fast_v1.py`の出力CSVと連動する専用スクリプトです。
- `rerank_results.py`：入力CSVが存在せず現状動きませんが、`config/scoring_config.py`・`scoring_weights.csv`という重み付けスコアリングの仕組み自体は今後使いたいですか？
- `docs/README_StrategyLab.md`：ルート`README.md`と内容が食い違う古いビジョン文書です。参照用に残しますか、archiveしますか？

---

## 4. 重要：これは提案のみです

上記はすべて分類・提案であり、**このドキュメント作成の時点で一切のファイル移動・削除・コード変更は行っていません。** 次のステップに進むかどうかはご判断ください。

---

## 5. 安全な整理の作業手順（次にやるとしたら）

大規模リファクタリングではなく、**1クラスタ＝1コミット**で進める前提の手順案です。

1. **`archive/`フォルダを新規作成**（`archive/engine/`, `archive/indicators/`, `archive/strategies/`のようにディレクトリ構造を保ったまま）。ファイルは削除せず`git mv`で移動するだけ＝Git履歴は保持され、いつでも元に戻せます。
2. **確信度「高」グループから着手**（上記3節）。壊れているファイル・空ファイル・完全に参照ゼロのものなので、動作に影響しないことがほぼ確実です。1ファイルまたは1クラスタ移動するごとに`python main.py --mode dev`を実行し、正常終了することを確認してからコミットします。
3. **確認できたら`--mode full`・`walk_forward.py`・`analyze_walk_forward.py`も一通り実行**し、既存の3つの運用フロー（本番/ウォークフォワード/検証ツール群）が壊れていないことを確認します（CLAUDE_HANDOVER.mdにある「main.py, walk_forward.py, analyze_walk_forward.pyの動作を考慮」という要望に対応）。
4. **確信度「中」グループは、archiveする前に一度用途を相談**します。特にnumba版バックテストエンジンやwalk_forward専用フレームワークは、壊れたimportを直せばV2.0でそのまま活用できる可能性があるため、archiveするかリペアして本流に組み込むかを個別に決めたいです。
5. **「要ユーザー確認」グループは、ご回答をいただいてから対応**します。
6. **全ての移動が終わった後**、`CLAUDE_HANDOVER.md`・`README.md`・`docs/CHANGELOG.md`をリポジトリの実態に合わせて更新します（ここで初めてドキュメントの内容にも手を入れます）。

各ステップでコミットとタグ（例：`v1.0.1-cleanup-step1`）を分けておけば、万一動作がおかしくなった場合もどのステップで問題が起きたか特定しやすくなります。

---

まず「確信度：高」グループのarchive移動から始めてよいか、あるいは「要ユーザー確認」の3項目（旧プロトタイプ3本、rerank_results.py関連、docs/README_StrategyLab.md）についてお考えを聞かせていただけますか。
