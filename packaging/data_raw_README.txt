価格データの配置について

このフォルダに、ご自身でご用意いただいたヒストリカル価格データ(CSV)を
配置してください。

■ 推奨する配置場所(通貨ペアごとのサブフォルダ)
data\raw\{通貨ペア}_Data\{通貨ペア}_2003_2026_{時間足}.csv

例:
  data\raw\USDJPY_Data\USDJPY_2003_2026_15m.csv
  data\raw\EURJPY_Data\EURJPY_2003_2026_1h.csv
  data\raw\AUDUSD_Data\AUDUSD_2003_2026_1d.csv

(このフォルダ直下に {通貨ペア}_2003_2026_{時間足}.csv を直接置く
 従来の形式でも認識されますが、通貨が増えると混在しやすいため
 サブフォルダ形式を推奨します)

対応する時間足: 1m, 5m, 15m, 1h, 4h, 1d
対応する通貨ペア: USDJPY, EURJPY, GBPJPY, AUDJPY, AUDUSD, EURUSD, GBPUSD
  (1分足のみ、ファイル名が {通貨ペア}_2003_2026_1min_filled.csv でも
   認識されます)

■ 必要な列(1行目をヘッダーとしてください)
datetime (または time / date / timestamp), open, high, low, close

列名の大文字・小文字は区別されません。
volume列があっても構いませんが、使用されません。

■ データの入手方法
ご利用のFX会社の取引ツール、またはTradingView等のチャートサービスから
CSV形式でエクスポートしてください。エクスポート方法は各サービスの
ヘルプをご参照ください。

■ ブローカーのタイムスタンプがJSTでない場合(EET/東欧時間など)
このソフトはJST(日本時間)のタイムスタンプを前提としています。
EET形式のCSV(列名が "Time (EET),Open,High,Low,Close,Volume" など)を
お使いの場合は、同梱の import_broker_csv.py で変換できます。

  例(1ファイルだけ変換):
    python import_broker_csv.py 入力.csv 出力.csv

  例(通貨・時間足をまとめて変換):
    python import_broker_csv.py --batch-source ソースフォルダ --batch-dest data\raw ^
      --symbols USDJPY,EURJPY,GBPJPY --timeframes 1m,5m,15m,1h,4h,1d

タイムゾーン変換とあわせて、OHLC(始値・高値・安値・終値)の
整合性エラー(高値が実は最高値でない等)も自動で補正します。
