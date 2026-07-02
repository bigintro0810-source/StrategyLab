# CLAUDE_HANDOVER.md

# Strategy Lab 引き継ぎ資料

## プロジェクト概要

Strategy Lab は Python 製のFXストラテジー研究・開発ツールです。

目的は

「長期間のヒストリカルデータから、本当に将来でも機能するストラテジーを見つけること」

です。

裁量補助ではなく、

**ストラテジー発見ツール**

として設計されています。

---

# Version

現在

**Version 2.0 / 3.0 とも進行中（未タグ付け）**

V2.0-1（複数時間足対応）/ V2.0-3（Equity・Drawdownグラフ入りHTMLレポート）/ V2.0-4（保存済みストラテジーのタグ・メモ・お気に入り・横断比較。`strategy_manager.py`）は完了。

V2.0-2（評価指標拡充）はRecovery Factorのみ実装済みで、Sharpe Ratio / Sortino Ratio / Calmar Ratio / CAGR / Profit-DDの5指標は未実装のまま保留（2026-07-02、ユーザー判断によりV3.0を優先）。

V3.0のうち、指標ライブラリ拡充を除く3項目が完了（2026-07-02）：
- 最適化強化：`--optimizer {grid,random,genetic}`（`engine/optimizer_search.py`）。Bayesian最適化は依存ライブラリ導入判断待ちで未着手。
- 信頼性評価拡充：パラメータ感度分析（`analyze_sensitivity.py`）、既存のstability/Monte Carlo/walk-forwardレーティングを束ねたConfidence Score（`engine/robustness.py` / `analyze_confidence.py`）。
- 条件ベースのストラテジー定義：JSON設定ファイルでパラメータグリッドを外出し（`--strategy-config`, `strategy_configs/*.json`）。戦略ロジック自体のDSL化ではなく、値の選択を設定ファイル化するスコープに限定。

指標ライブラリ拡充（FVG/OrderBlock/BOS/CHoCH/LiquiditySweep/Bollinger/Donchian/SuperTrend）は保留。理由：リポジトリ内で既にRSI/ATRの計算式が2系統あり数値が食い違っており（`indicators/`のWilder平滑 vs `engine/indicators.py`の単純移動平均）、「正」を決めないまま指標を追加すると同じ問題を再生産するため。着手前にユーザーが計算式の基準を決める必要がある。

Git Tag

v1.0.0（V2.0系はまだタグ未作成。v2.0.0タグを打つかはユーザー判断待ち）

---

# 開発環境

OS

Windows 11

Python

VS Code

Git + GitHub

---

# PCスペック

CPU

Intel Core i7-12650H

10コア16スレッド

RAM

16GB

GPU

GeForce MX550

SSD

約500GB

---

# 対象データ

現在

USDJPY

15分足

約23年分

2003〜2026

CSV形式

将来的には

EURUSD

GBPJPY

EURJPY

AUDJPY

Gold

日経225

へ拡張予定。

---

# 現在実装済み

## バックテスト

高速バックテスト

パラメータ最適化

ランキング

取引履歴

---

## ランキング

総合

PF

DD

利益

勝率

期待値

年別安定度

月別安定度

総合安定度

---

## 分析

年別分析

月別分析

安定度分析

Monte Carlo

Equity Curve

Walk Forward

Walk Forward Analyzer

---

# 実行方法

軽量確認

python main.py --mode dev

本番

python main.py --mode full

Walk Forward

python walk_forward.py

Walk Forward解析

python analyze_walk_forward.py

Monte Carlo

python monte_carlo.py

Equity Curve

python equity_curve.py

---

# Git運用

GitHubで管理。

mainは常に動作する状態を維持。

大きな変更はブランチを切る。

Version完成時はタグ付け。

---

# コーディングルール

非常に重要。

変更するファイルは

**毎回全文で出力してください。**

部分的な

「ここを書き換えて」

は禁止。

ユーザーは全文コピペ方式で開発しています。

---

# 設計思想

最優先

正確性

↓

速度

↓

拡張性

コードは読みやすさより

高速実行

を重視。

---

# 優先事項

・高速

・大量データ対応

・CPU並列化

・不要な再計算禁止

・メモリ効率

---

# Version2.0予定

複数通貨対応は後回し（V4.0）。

時間足・評価・可視化・戦略管理を先に固める。

## V2.0-1 複数時間足対応

15分足決め打ちを可変化。

1分〜月足のCSV読み込み・リサンプリング対応。

## V2.0-2 評価指標拡充

Sharpe Ratio

Sortino Ratio

Calmar Ratio

CAGR

Recovery Factor

Profit/DD

既存ランキングへ組み込み。

## V2.0-3 可視化・レポート

Equity Curveグラフ化

Drawdown Curveグラフ化

Monthly Heatmap

Yearly Heatmap

HTMLレポート出力

## V2.0-4 複数ストラテジー管理・比較

戦略の保存

タグ管理

メモ機能

お気に入り

横断比較

---

# Version3.0予定

指標ライブラリ拡充（FVG / Order Block / BOS / CHoCH / Liquidity Sweep / Bollinger / Donchian / SuperTrend等）

条件ベースのストラテジー定義（コード直書き依存を減らす）

最適化強化（ランダムサーチ / 遺伝的アルゴリズム / ベイズ最適化）

信頼性評価拡充（Robustness Score / 過剰最適化判定 / パラメータ感度分析 / Confidence Score）

---

# Version4.0予定

複数通貨対応

・pip値/小数桁/データパスをconfig化 → pip値のハードコード解消は完了（2026-07-02）。EURUSD等の追加は`data/raw/`に該当通貨のヒストリカルデータが無いため未着手（データ入手待ち）。

・EURUSD等を追加 → 未着手（上記と同じ理由）

複数時間足と合わせてデータ軸の拡張として実施。

GUI化（Streamlit等） → 完了（2026-07-02）。`gui_app.py`（`streamlit run gui_app.py`）。バックテスト実行タブ・保存済み戦略管理タブ（一覧/タグ/メモ/お気に入り/横断比較）。本リポジトリ初のサードパーティ依存として`requirements.txt`を新規作成。

・GUIからのストラテジー条件設定 → 完了（mode/timeframe/optimizer/strategy-configの指定、実行、レポート閲覧）

・PDF/Excel出力 → 未着手。ランキングCSVダウンロードのみ実装（ExcelはCSVで開けるため最低限は満たすが、xlsx/PDF専用出力ではない）。追加ライブラリ（openpyxl/reportlab等）の導入判断が必要。

---

# Version5.0予定

Pine Script自動生成

Strategy自動生成

Indicator自動生成

アラートコード生成

TradingView一致検証の自動化

---

# Version6.0予定

自然言語からのストラテジー作成

改善提案

過剰最適化検出

フィルター提案

自動レポート生成

---

# Version7.0以降予定

GPU最適化・並列化強化

通貨相性分析・共通パターン発見

夜間自動バックテスト・定期レポート

MT5 / cTrader / API連携

Discord / LINE通知

Web版・クラウド実行

---

# 最終目標（完成形）

「世界最高レベルの個人向けストラテジー研究プラットフォーム」を作ること。

理想のワークフロー：

アイデアを自然言語やGUIで入力

数十年・複数通貨・複数時間足で高速検証

Walk Forward・Monte Carlo・安定度などで信頼性を自動評価

AIが改善案を提案

採用した戦略をTradingView用のPine Scriptとして自動生成

必要に応じて実運用や監視へつなげる

---

# Claudeへの依頼

いきなり全面リファクタリングしないこと。

まず既存設計を理解してください。

後方互換性を維持してください。

既存機能を壊さないでください。

速度低下は極力避けてください。

変更後は

main.py

walk_forward.py

analyze_walk_forward.py

の動作を考慮してください。

---

# ユーザーの希望

コードは全文で送る。

説明は簡潔。

1ステップずつ進める。

Git管理を継続する。

Version管理を重視。

---

# 最終目標

Strategy Labを

個人レベルではなく

プロ品質の

ストラテジー研究プラットフォーム

へ成長させること。

Version1.0はその土台です。