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

**Version 2.0 / 3.0 / 4.0 とも進行中（未タグ付け）**

V2.0-1（複数時間足対応）/ V2.0-3（Equity・Drawdownグラフ入りHTMLレポート）/ V2.0-4（保存済みストラテジーのタグ・メモ・お気に入り・横断比較。`strategy_manager.py`）は完了。

**V2.0-2（評価指標拡充）は完了（2026-07-03）**。Profit-DDは既存のRecovery Factor(net_profit/max_dd)と同一計算式のため追加実装なし。Sharpe/Sortino Ratioは月次損益(pips)を既存のリターン系列としてそのまま使用(無リスク金利=0、月次で年率化)。CAGR/Calmar Ratioはこのプロジェクトが口座残高/ロットサイズの概念を持たない(pipsベースで動作する)ため、%換算に仮想初期資金100(pips基準)を導入(ユーザー確認済み)。`engine/advanced_metrics.py`。`main.py::run_one_backtest`と`engine/optimizer_search.py::run_bayesian_search`の両方に実装(前回のstability_fnと同じ理由でコールバック注入、両経路の食い違いを防ぐため)。

**V3.0（2026-07-02〜03）:**
- **最適化強化：完了（2026-07-03）**。`--optimizer {grid,random,genetic,bayesian}`（`engine/optimizer_search.py`）。Bayesian最適化は`optuna`(TPEサンプラー)を採用(混合探索空間=カテゴリカル+bool+int+floatに強いため)。ProcessPoolExecutorは使わず、1試行ずつ`run_backtest`を直接呼ぶ逐次実行(Bayesianは前の結果を見て次を決めるため、そもそもバッチ並列化と相性が悪い)。`main.py::calculate_stability_metrics`はコールバック注入で受け渡し(循環import回避)。
- 信頼性評価拡充：パラメータ感度分析（`analyze_sensitivity.py`）、既存のstability/Monte Carlo/walk-forwardレーティングを束ねたConfidence Score（`engine/robustness.py` / `analyze_confidence.py`）。
- **条件ベースのストラテジー定義：完了。当初はJSON設定ファイルでの値の外出しのみだったが、ユーザーとの追加すり合わせで最終的にエンジン自体をプラガブル化した。**
  - `engine/backtest_engine.py::run_backtest()`は、ループ前に1回だけ`candidate_signal`配列を計算する方式に変更（ステートフルなポジション管理ループ自体は無変更）。
  - `engine/triggers.py`: エントリートリガーを`entry_trigger`パラメータで選択式に（`breakout`(旧来のデフォルト) / `donchian_breakout` / `ema_cross` / `macd_cross` / `bollinger_touch` / `ichimoku_cloud_breakout` / `ichimoku_tk_cross` / `stochastic_kd_cross` / `stochastic_level_cross`）。定義が割れているもの(Ichimoku・Stochastic)は片方に決め打ちせず両方を別トリガーとして用意。
  - `engine/filters.py`: 既存6条件(セッション・実体/ヒゲpips・EMA距離・RSI)を含む全16フィルターが`use_X`フラグでON/OFF可能に(既存分はデフォルトTrue=現状維持、新規10種はデフォルトFalse)。
  - `engine/technical_indicators.py`: Donchian/Bollinger/MACD/Ichimoku/Stochastic/日次ピボット+ADR/ラウンドナンバーの計算式(V3.0指標ライブラリ拡充のTier1完了)。
  - `engine/signal_builder.py`: トリガー+フィルター合成の司令塔。`engine/params.py::reconstruct_params_from_row()`: `main.py`/`walk_forward.py`にあった重複ホワイトリスト関数を統合。
  - 新パラメータは`main.py --mode full`の既存243通りグリッドには追加していない(組み合わせ爆発を避けるため、`--optimizer random/genetic`または`--strategy-config`で探索する設計)。

**指標ライブラリ拡充、残りの状況:**
- Tier 1(Donchian/Bollinger/MACD/Ichimoku/Stochastic/Pivot+ADR/prev_high/prev_low/round_number/weekday): 完了(上記)。
- **RSI計算式の問題は解決済み（2026-07-03）**。`data/raw/TV_USDJPY_15m.csv`のTradingView公式RSI列と直接数値比較した結果、従来の単純移動平均版はTV不一致(平均絶対誤差6.6、RSI>70判定の一致率90.48%)、Wilder平滑化版はTVとほぼ完全一致(平均絶対誤差0.006、一致率100%)。`engine/backtest_engine.py::rsi()`と`engine/indicators.py::rsi()`をWilder平滑化に変更。**この変更で全バックテスト結果が変わる**ため`tests/test_regression.py`の基準値も再計算済み。ATRも同じ理由でWilder化したが、TVエクスポートにATR列が無いため直接検証はできていない(標準的な慣習からの推測)。
- **Tier 2(SuperTrend/ADX): 完了（2026-07-03）**。`engine/technical_indicators.py`に追加。SuperTrendは前バーの状態に依存する再帰的な構造のため(トレンド方向とバンド値が1本前の値に依存)、他の指標と違いO(n)のPythonループで実装(既存のバックテストループと同じ計算量クラス)。1分足87万行規模でも約37秒で許容範囲。既知パターンの合成データ(強い上昇→下降トレンド、トレンド相場 vs レンジ相場)で事前検証してから本番データに適用。トリガー`supertrend_flip_bearish`/`adx_di_cross_bearish`、フィルター`use_supertrend_filter`/`use_adx_filter`として追加。
- **Tier 3(FVG/OrderBlock/BOS/CHoCH/LiquiditySweep): 完了(2026-07-03)。`engine/smc_indicators.py`。ユーザーの指示通り「一般的な(ICT系)定義で実装、TradingView未検証」の位置づけ。ショート専用戦略に合わせ全てbearish版のみ実装。エントリートリガー5種+フィルター5種として追加。BOS/CHoCHはswing point検出のルックアヘッド回避・隣接バー重複統合という2つの実装上の落とし穴を、既知パターンの合成データで検証して回避済み。**

**V4.0（2026-07-02〜04）:**
- 複数通貨対応：`--symbol`が全7通貨(USDJPY/EURJPY/GBPJPY/AUDJPY/AUDUSD/EURUSD/GBPUSD)対応完了(2026-07-04)。`main.py::pip_size_for_symbol()`が通貨名の末尾"JPY"判定でpip_sizeを自動選択(JPYクロス=0.01、それ以外=0.0001)。`walk_forward.py`/`analyze_walk_forward.py`/`gui_app.py`の`--symbol`/`SYMBOLS`も同時に拡張。
- **データ取り込みパイプライン刷新（2026-07-04）:** ブローカー提供のEET(東欧時間、EU方式サマータイム)タイムスタンプ付きCSVを`C:\Users\bigin\保存用ファルダ\FX_Data\{通貨}_Data\`に置く運用に変更。`import_broker_csv.py`でJST変換(`Europe/Helsinki`→`Asia/Tokyo`、DST切替の瞬間はFX市場休場のため衝突なしを確認済み)とOHLC整合性エラー自動補正(`high=max(O,H,L,C)`/`low=min(O,H,L,C)`)を同時実施。`data/raw/{通貨}_Data/{通貨}_2003_2026_<足>.csv`という通貨別サブフォルダ構成に統一(`main.py::build_data_candidates()`が新構成を優先、旧フラット配置にもフォールバック)。**日足データの重要な決定:** 旧`_TV_NY.csv`(ユーザーが1分足から自作リサンプルしたもの)は日足本数が想定営業日数より1,094本も多いという原因不明の不整合があったため、ブローカー由来の日足(想定営業日数とほぼ一致)に置き換えて`_TV_NY.csv`/`_1min_filled.csv`は削除。**この変更で全バックテスト結果が変わるため`tests/test_regression.py`・`tests/test_regression_indicators.py`の基準値も実データで再計算して置き換え済み(両方PASS確認済み)。**
- GUI化：完了。`gui_app.py`（`streamlit run gui_app.py`）。
- PDF出力：完了（2026-07-03）。`engine/pdf_report.py`（`fpdf2`使用、`output/report.pdf`自動出力、GUIにもダウンロードボタン追加）。HTMLをそのまま変換する方式(weasyprint等)はWindowsでシステム依存関係のインストールが不安定になるリスクがあるため避け、サマリー・Equity/Drawdownチャート・ランキング表を独自に再構成する方式。日本語は游ゴシック(Windows同梱フォント)を埋め込み。Excel出力は未着手（CSVダウンロードで代替可能なため優先度低）。

**個人/小規模販売向けパッケージ化：完了（2026-07-03）**。`build_package.ps1`実行で`dist/StrategyLab/`にダブルクリック起動可能な配布物を生成(Python embeddable package同梱、`run.bat`起動)。PyInstallerではなくPython同梱方式を採用した理由: `gui_app.py`は`sys.executable`経由でmain.pyをサブプロセス起動する設計(Streamlit+ProcessPoolExecutorのWindows spawn方式対策、V4.0 GUI化時に導入)。PyInstallerで凍結するとsys.executableが凍結exe自身を指してこの呼び出しが壊れるため、埋め込み型Pythonでコード変更を回避。同梱Python環境での動作を実際に検証済み(main.py単体実行、Streamlit GUI起動、`subprocess.run([sys.executable, "main.py", ...])`パターン全て確認)。埋め込みPythonの`._pth`ファイルはデフォルトでスクリプト自身のディレクトリをsys.pathに含めない(サイト制限モード)ため、ビルドスクリプトで`..\app`を明示的に追加する対応が必要だった。ライセンス/課金の仕組みは未着手（後日検討、ユーザー確認済み）。免責事項は`gui_app.py`サイドバーと`packaging/README_usage.txt`に記載。`data/raw/`のヒストリカルデータはリポジトリに一度もコミットされておらず(`.gitignore`)、配布物にも同梱しない(ユーザー自身のデータを使う設計)。

Git Tag

v1.0.0, v3.0.0（現時点の最新タグはv3.0.0。V4.0のGUI/PDF/パッケージ化分はまだタグ未作成）

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

USDJPY / EURJPY / GBPJPY / AUDJPY / AUDUSD / EURUSD / GBPUSD の7通貨

1分〜日足(1m/5m/15m/1h/4h/1d)

約23年分

2003〜2026

CSV形式（ブローカーEET提供データをJST変換・OHLC補正して`data/raw/{通貨}_Data/`に格納。詳細はV4.0の項を参照）

将来的には

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

・PDF/Excel出力 → PDF完了（`engine/pdf_report.py`、`fpdf2`使用）。Excelは未着手（CSVダウンロードで代替）。

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