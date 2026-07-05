# Strategy Lab Version 2.0 設計レビュー

対象: bigintro0810-source/StrategyLab（main, v1.0.0）。全ファイル実読の上での分析。

---

## 1. 現在の設計レビュー

**実際に動いている経路は1本だけ**です。

`main.py --mode dev/full` → `engine/backtest_engine.run_backtest()`（本番バックテスト）→ main.py内蔵の年別/月別/安定度分析・ランキング出力（`export_rankings`ほか）→ `engine/monte_carlo.py` / `engine/equity_curve.py`。

これに加えて `walk_forward.py`（root）が main.py の関数を再利用しつつ独自にウォークフォワード検証を行い、`analyze_walk_forward.py` がその判定（PASS/CAUTION/FAIL/A〜D評価）を行う、という2本目の経路があります。

問題は、**それ以外にも「設計だけは整っているが、この実行経路からは呼ばれていないコード」が大量に存在する**ことです。具体的には以下が並存し、統合されていません。

| 機能領域 | 並存数 | 実際に使われているもの |
|---|---|---|
| バックテストエンジン本体 | 5系統 | `engine/backtest_engine.py` のみ |
| パラメータ最適化 | 3系統 | main.py内の`ProcessPoolExecutor`独自実装のみ |
| ウォークフォワード | 3系統 | root `walk_forward.py` のみ |
| ランキング | 2系統 | main.py内`export_rankings`のみ |
| インジケータ計算式 | 3種類（数値が不一致） | `engine/backtest_engine.py`内のローカル定義のみ |
| データ読み込み | 4系統 | main.py内`load_price_data`のみ |
| 列名規約 | 2系統（大文字/小文字） | 小文字系のみ実質稼働 |

`config/`（dataclassベースの設定）、`engine/optimizer.py`・`engine/numba_backtest.py`（JIT高速版）、`engine/ranking.py`（重み付きスコア方式）、`engine/walk_forward.py`系（3層フレームワーク）はいずれも作りは悪くないものの、main.pyの本流からは到達不能です。`old_config.py`は完全にデッドコード、`engine/tv_engine.py`・`engine/tv_state.py`は0バイトの空ファイルでした。

ドキュメントも実態とズレています。`docs/CHANGELOG.md`は「v2.0予定」としてウォークフォワード・モンテカルロを挙げていますが、これらは既にv1.0時点で実装済みです。`docs/README_StrategyLab.md`はルート`README.md`と内容が食い違う古いビジョン文書です。

要するに現状のStrategy Labは、**「本番として動く細い一本道」と「将来を見据えて先に作られたが未接続の設計群」が同じリポジトリに混在している**状態です。これはChatGPTとの反復開発で機能ごとに新しい実装を積み重ねた結果と見られ、V1.0としては動くものが完成している一方、V2.0で機能拡張する前に、この「二重構造」をどう扱うかの意思決定が必要です。

---

## 2. 良い点

**本番エンジンの設計品質は高い。** `engine/backtest_engine.py`は次バーOpen約定・SL優先・週末決済など、`docs/TV_Backtest_Engine_Spec.md`と`docs/TradingView_Order_Execution.md`という実務的な仕様書の内容をほぼ忠実に実装しています。TradingViewとの一致率を検証する仕組み（`compare_signals.py`, `compare_tradingview.py`）もあり、「正確性最優先」という設計思想が実際のコードに反映されています。

**個々のパーツの完成度は高い。** numba JIT実装（`numba_backtest.py`）、numpyベクトル化されたシグナル生成（`ConditionEngine`）、`ParameterGrid`、`IndicatorCache`など、高速化を意識した質の良いコンポーネントが揃っています。今は未接続ですが、資産としては十分使えるものです。

**設定管理の土台は良い。** `config/`配下がdataclassで型安全に設計されており（`StrategyConfig`, `ScoringConfig`, `WalkForwardConfig`）、一元化する下地は既にあります。

**開発プロセスへの意識が高い。** Git運用・バージョンタグ・引き継ぎ資料（CLAUDE_HANDOVER.md）を用意し、23年分のヒストリカルデータでの検証、ウォークフォワード、モンテカルロまでV1.0の時点で揃えているのは、個人開発のバックテストツールとしてはかなり踏み込んだ内容です。

**並列化でのスケール確保。** `ProcessPoolExecutor`による複数パラメータの並列評価で、実行時間を現実的な範囲に抑える工夫ができています。

---

## 3. 改善点

**最大の課題は「未接続の設計」の扱いです。** `engine/optimizer.py`・`numba_backtest.py`・`ranking.py`・`walk_forward_*`系・`config/`・`indicators/`パッケージは、削除して良い死んだコードなのか、将来本番に昇格させたい資産なのかが曖昧なまま残っています。V2.0で複数通貨対応や複数戦略比較を進めるほど、この二重構造がバグの温床になります。まず「main.pyから到達可能かどうか」で仕分けし、使わないものは`archive/`のような場所に退避する（消すのではなく隔離する）ところから始めるのが安全です。

**複数通貨対応（V2.0優先度①）の直接的な障害があります。** `pip = 0.01`というUSDJPY固定値が`backtest_engine.py`・`compare_signals.py`・`strategy_lab_v1.py`など複数箇所にハードコードされています。通貨ペアごとのpipサイズ・小数桁を一元化しないと、EURUSD等への拡張時に個別修正が漏れるリスクがあります。

**インジケータの計算式が3種類あり、数値が一致しません。** `indicators/`パッケージ（Wilder平滑）と`engine/indicators.py`（単純移動平均）でRSI/ATRの計算結果が異なります。将来どちらかに統一する際、既存のバックテスト結果と数値がズレる可能性があるため、早めに「正」を決めておくべきです。

**設定・パスがコードに散在しています。** `OUTPUT_DIR = Path("output")`が main.py・walk_forward.py・monte_carlo.py・equity_curve.pyでそれぞれ再定義されており、`config/walk_forward_config.py`のtrain_years=10と実際に動くroot walk_forward.pyのTRAIN_YEARS=5も食い違っています。

**自動テストが一切ありません。** `strategies/test_strategy.py`は名前に反してpytestのテストではなく、戦略クラスのサンプル実装です。TradingViewとの一致率検証（compare_signals.py等）が唯一の検証手段で、手動でのCSV比較に留まっています。エンジンを触る変更が増えるV2.0では、最低限の回帰テスト（既知パラメータでの期待値チェック程度）があると事故を防げます。

**ドキュメントとコードの進捗が乖離しています。** CHANGELOGやdocs/README_StrategyLab.mdの内容を、実際のコード状態に合わせて更新する必要があります。

---

## 4. Version 2.0 ロードマップ（提案）

CLAUDE_HANDOVER.mdに記載の優先順位（①複数通貨 ②グラフ ③HTMLレポート ④GUI ⑤AI評価 ⑥複数戦略比較）を尊重しつつ、上記の技術的負債を無視すると①の実装自体が積み上がった不整合の上に乗ってしまうため、**フェーズ0として最小限の土台整理を先頭に置くことを提案します**。一気にリファクタリングはせず、1機能＝1ステップで進める前提です。

**フェーズ0: 土台整理（複数通貨対応の前提づくり）**
未接続コードの棚卸しと仕分け（使う/退避するの判断のみ、大規模書き換えはしない）。pip値・OUTPUT_DIRなど、通貨拡張時に確実に触る箇所の洗い出しリスト作成。ここは「設計判断」が中心で、コード変更は最小限に留めます。

**フェーズ1: 複数通貨対応（①）**
通貨ペアごとのpipサイズ・データファイルパスをconfigに集約し、main.pyのハードコードを段階的に置き換え。まずEURUSD 1通貨を追加できる状態を目標にします。

**フェーズ2: グラフ表示・HTMLレポート（②③）**
既存のequity_curve出力を土台に、matplotlib/plotly等でのグラフ生成とHTMLレポート化。`reports/`ディレクトリを本格活用します。

**フェーズ3: 複数ストラテジー比較（⑥）**
現行のランキング基盤を拡張し、複数戦略・複数通貨の横断比較を可能にします。

**フェーズ4: GUI（④）**
フェーズ1〜3が固まった後、Streamlit等での操作画面化を検討します。

**フェーズ5: AI評価（⑤）**
スコアリング・パターン発見へのAI活用は、データと評価基盤が安定してから着手するのが安全です。

V3.0で予定されているTradingView連携（Pine Script生成）は、`tv_types.py`と2本の仕様書という形で既に土台があるため、V2.0の合間や後続で`tv_engine.py`/`tv_state.py`の実装として自然に継続できます。

---

以上がレビューです。次にどこから着手するか、フェーズ0の棚卸しから始めるか、あるいはフェーズ1（複数通貨対応）を優先するか、ご相談させてください。
