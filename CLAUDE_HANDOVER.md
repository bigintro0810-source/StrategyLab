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

**Version 1.0 完成**

Git Tag

v1.0.0

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

優先順位

① 複数通貨対応

② グラフ表示

③ HTMLレポート

④ GUI

⑤ AI評価

⑥ 複数ストラテジー比較

---

# Version3.0予定

Pine Script自動生成

TradingView連携

インジケータ生成

最適化AI

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