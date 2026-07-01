# Strategy Lab

## 目的

過去の為替データから期待値の高いストラテジーを自動で発見するソフトを作る。

最終的にはTradingViewコードを自動生成し、
ボタン一つで検証できるWindowsアプリを目指す。

---

# Version 1.0

## データ管理

・USDJPY
・EURUSD
・GBPUSD
・XAUUSD
・BTC
など追加可能

---

## 戦略検索

・ブレイクアウト
・EMA
・RSI
・ATR
・FVG
・Liquidity Sweep
・Order Block
・ICT

---

## ランキング

・PF順
・勝率順
・利益順
・期待値順
・最大DD順
・年別安定度順

※項目は今後追加可能

---

## フィルター

・期間指定
・PF以上
・最大DD以下
・勝率以上
・利益以上
・トレード回数以上

※項目は今後追加可能

---

## 詳細画面

・資産曲線
・年別利益
・月別利益
・PF推移
・DD推移
・勝率推移

---

## TradingView

ランキングからワンクリックで
Pine Scriptを生成する。

---

## 将来追加

・AIによる自動探索
・ウォークフォワードテスト
・モンテカルロ分析
・お気に入り
・研究ノート
・戦略比較

## Current Features

- Numba高速バックテスト
- Indicator Cache
- Signal Cache
- ATR Filter
- Session Filter
- Configurable Scoring
- CSV Reranking
- Yearly Stability
- Monthly Stability
- Max Win/Loss Streak