# Strategy Lab フェーズ0：整理方針 最終版

コード変更なし。ファイル移動もまだ行っていません。方針の確定のみです。

ユーザー確認結果を反映：
1. 旧プロトタイプ3本（strategy_lab_v1.py / strategy_lab_fast_v1.py / strategy_search.py）→ archive確定
2. rerank_results.py / config/scoring_config.py / scoring_weights.csv → archiveせず「将来資産」として保持
3. docs/README_StrategyLab.md → archive確定（README.mdを正とする）

---

## 1. 残すファイルリスト最終版（現行稼働中・フェーズ0で一切触らない）

### 本番自動フロー
- `main.py`
- `engine/backtest_engine.py`
- `engine/monte_carlo.py`

### 手動運用ツール
- `walk_forward.py`（root）
- `analyze_walk_forward.py`
- `equity_curve.py`（root）
- `monte_carlo.py`（root）
- `compare_tradingview.py`
- `analyze_monthly.py`
- `analyze_yearly.py`
- `analyze_stability.py`
- `compare_signals.py`

### ドキュメント類
- `README.md`
- `CLAUDE_HANDOVER.md`
- `docs/CHANGELOG.md`
- `docs/TV_Backtest_Engine_Spec.md`
- `docs/TradingView_Order_Execution.md`
- `.gitignore`

**計18ファイル。これらは今後も現状の場所・中身のまま維持します。**

---

## 2. archive候補リスト最終版

### クラスタA：完全に孤立・空・壊れている（リスク最小）
- `old_config.py`
- `engine/tv_engine.py`（空ファイル）
- `engine/tv_state.py`（空ファイル）
- `engine/csv_export.py`（存在しないクラスをimportしており実行時エラーになる）

### クラスタB：indicators重複クラスタ（相互依存なので一括移動）
- `indicators/__init__.py`
- `indicators/ta.py`
- `indicators/ema.py`
- `indicators/sma.py`
- `indicators/rsi.py`
- `indicators/atr.py`
- `engine/cache.py`
- `engine/indicator_manager.py`

### クラスタC：孤立ユーティリティ（個別に孤立、依存なし）
- `engine/loader.py`
- `engine/data_info.py`
- `engine/normalizer.py`
- `engine/validator.py`
- `engine/yearly_stats.py`
- `engine/conditions.py`

### クラスタD：ダミー戦略
- `strategies/ema_sample.py`

### クラスタE：旧世代プロトタイプ（ユーザー確定済み）
- `strategy_lab_v1.py`
- `strategy_lab_fast_v1.py`
- `strategy_search.py`
- `reports/strategy_detail_v1.py`（strategy_lab_fast_v1.pyの出力専用スクリプトのため同時移動）

### クラスタF：古いドキュメント（ユーザー確定済み）
- `docs/README_StrategyLab.md`

**計21ファイル（indicators/を6ファイルとしてカウント）。**

---

## 3. 将来資産として残すファイルリスト（archiveせず、元の場所に残す）

V2.0以降で「直して活かす」か判断したいもの。フェーズ0では移動も編集もしません。

### スコアリング関連（ユーザー指定）
- `rerank_results.py`
- `config/scoring_config.py`
- `config/scoring_weights.csv`

### 高速化・最適化エンジン（numba/Optimizer系、壊れたimportの修理が前提）
- `engine/optimizer.py`
- `engine/fast_optimizer.py`
- `engine/fast_backtest.py`
- `engine/numba_backtest.py`
- `engine/result.py`（上記3ファイルが本来参照すべき対象。クラス名の不一致が原因でImportErrorになっている）
- `engine/condition_engine.py`
- `engine/condition_config.py`
- `engine/parameter_grid.py`
- `engine/metrics.py`

### 別方式のランキング
- `engine/ranking.py`

### ウォークフォワード専用フレームワーク（root版とは別系統、統合要検討）
- `engine/walk_forward.py`（`WalkForwardTester`）
- `engine/walk_forward_engine.py`
- `engine/walk_forward_runner.py`
- `engine/walk_forward_manager.py`
- `engine/walk_forward_summary.py`
- `engine/walk_forward_exporter.py`
- `engine/walk_forward_result.py`
- `config/walk_forward_config.py`（値の食い違い要整理）

### OOP版バックテストエンジン一式
- `engine/backtest.py`
- `engine/broker.py`
- `engine/order.py`
- `engine/position.py`
- `engine/trade.py`
- `strategies/test_strategy.py`

### データ管理
- `engine/data_loader.py`
- `config/strategy_config.py`

### TradingView連携（V3.0向け）
- `engine/tv_types.py`

**計26ファイル。これらはリポジトリ内に残しつつ、「本流とは別の資産」として扱います。**

---

## 4. V2.0開始前に触らない方がいいファイル

フェーズ0の作業中（archive移動〜完了まで）、**中身を一切編集しないファイル**です。

- **第1節の「残すファイル」18ファイル全て**：現行稼働中のため、フェーズ0中の変更はリスクでしかありません。動作確認のためのコマンド実行はしますが、コード自体は変更しません。
- **第3節の「将来資産」26ファイル全て**：archiveはしませんが、壊れたimportの修理やロジックの統合は行いません。それはV2.0の各フェーズで個別に判断してから着手すべき作業です。フェーズ0では「移動するかどうか」の判断のみに留めます。

つまりフェーズ0で実際に手を動かすのは、**第2節のarchive候補21ファイルの移動のみ**になります。

---

## 5. 安全な作業順

`archive/`フォルダ構成案（ディレクトリ構造を保ったまま移動）：
```
archive/
  engine/       ← クラスタA・B・Cのengine配下ファイル
  indicators/   ← クラスタB
  strategies/   ← クラスタD
  prototypes/   ← クラスタE（strategy_lab_v1.py等）
  reports/      ← クラスタE（strategy_detail_v1.py）
docs/archive/   ← クラスタF（docs/README_StrategyLab.md）
```

移動は以下の順（リスクが低い順）で、**1クラスタ＝1コミット**とします。各ステップ後に `python main.py --mode dev` を実行し、正常終了を確認してからコミットします。

| ステップ | 対象クラスタ | 内容 | 動作確認 |
|---|---|---|---|
| 1 | クラスタA | old_config.py, tv_engine.py, tv_state.py, csv_export.py | `main.py --mode dev` |
| 2 | クラスタB | indicators/一式 + cache.py + indicator_manager.py | `main.py --mode dev` |
| 3 | クラスタC | loader.py, data_info.py, normalizer.py, validator.py, yearly_stats.py, conditions.py | `main.py --mode dev` |
| 4 | クラスタD | strategies/ema_sample.py | `main.py --mode dev` |
| 5 | クラスタE | strategy_lab_v1.py, strategy_lab_fast_v1.py, strategy_search.py, reports/strategy_detail_v1.py | `main.py --mode dev` |
| 6 | クラスタF | docs/README_StrategyLab.md | （コード無関係のため動作確認不要） |
| 7 | 総仕上げ | 全ステップ完了後、`main.py --mode full`・`walk_forward.py`・`analyze_walk_forward.py`・`equity_curve.py`・`monte_carlo.py`・`compare_tradingview.py`・`analyze_monthly.py`・`analyze_yearly.py`・`analyze_stability.py`・`compare_signals.py`を一通り実行し、全ての現役ツールが壊れていないことを最終確認 | 上記9ツール全て |

各ステップは独立しているため、途中で止めても問題ありません。全ステップ完了後、`v1.0.1-cleanup`のようなタグを打つことを推奨します。

---

この方針でよろしければ、ステップ1（クラスタA：old_config.py, tv_engine.py, tv_state.py, csv_export.py）から着手します。
