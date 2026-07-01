# Strategy Lab Version 1.0

Strategy Labは、FXストラテジーを高速に検証・比較・評価するためのバックテスト研究ツールです。

## 主な機能

- USDJPY 15分足データの読み込み
- 高速バックテスト
- パラメータ最適化
- ランキング出力
  - 総合順
  - PF順
  - DD順
  - 勝率順
  - 利益順
  - 期待値順
  - 年別安定度順
  - 月別安定度順
  - 総合安定度順
- 取引履歴出力
- 年別分析
- 月別分析
- 安定度分析
- Monte Carlo分析
- Equity Curve分析
- Walk Forward分析
- Walk Forward評価

## 基本の使い方

### 開発モード

軽く動作確認する場合。

```powershell
python main.py --mode dev