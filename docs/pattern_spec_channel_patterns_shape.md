# 形状判定版 チャネル系パターン(共通仕様) - レクタングル/トライアングル/ウェッジ/ペナント/フラッグ

対象関数: `ascending_box_shape` / `descending_box_shape`(上昇/下降ボックス=レクタングル)、
`ascending_triangle_shape` / `descending_triangle_shape`(上昇/下降三角保ち合い)、
`rising_wedge_shape` / `falling_wedge_shape`(上昇/下降ウェッジ型)、
`bullish_pennant_shape` / `bearish_pennant_shape`(上昇/下降ペナント型)、
`bullish_flag_shape` / `bearish_flag_shape`(上昇/下降フラッグ型)

共通コア: `_shape_state_core_channel`(njit) → ラッパー `_channel_shape_state`

前提: `docs/pattern_spec_triple_top_bottom_shape.md`(既存のST方式の管理仕様・
用語)。ダブル/トリプル/H&Sは「M/W字の反転パターン」(山と谷が交互に、かつ
同じ側の点同士は水準が近いことを要求する)だったが、この6家系は構造が違う
- **2本の境界線(トレンドライン)の傾きの組み合わせ**で分類される「継続/
保ち合い」型パターン。そのため管理仕様(3状態モデル・先読み防止)は完全に
共有しつつ、探索コアは新設する。

---

## 0. なぜ6家系をひとつの共通コアにまとめるか

ヘッド&ショルダーズはトリプルからの差分2点だけで済んだが、この6家系は
そもそも「山と谷が交互に4点、上側2点を結ぶ線と下側2点を結ぶ線の傾きの
組み合わせで模様が決まる」という**同一の骨格**を持つ:

| パターン | 下側の線(点1・点3) | 上側の線(点2・点4) | ブレイク方向 |
|---|---|---|---|
| 上昇ボックス | 水平 | 水平 | 上 |
| 下降ボックス | 水平 | 水平 | 下 |
| 上昇三角保ち合い | 上昇 | 水平 | 上 |
| 下降三角保ち合い | 水平 | 下降 | 下 |
| 上昇ウェッジ(弱気) | 上昇 | 上昇(収束) | 下 |
| 下降ウェッジ(強気) | 下降 | 下降(収束) | 上 |
| 上昇ペナント | 収束(小型) + 上向き旗竿 | 上 |
| 下降ペナント | 収束(小型) + 下向き旗竿 | 下 |
| 上昇フラッグ | 平行・下向き傾斜 + 上向き旗竿 | 上 |
| 下降フラッグ | 平行・上向き傾斜 + 下向き旗竿 | 下 |

つまり「4点を探して2本の線を引く」ところまでは完全に共通で、違うのは
**探索後に計算される2本の傾きをどう判定するか**という、探索が終わった後の
分類ロジックだけ。共通コアを1つ書き、分類だけをPython側の軽い後処理
(ベクトル演算)にすることで、6家系×2方向=12関数を、バグの温床になり
やすいnjitコードの重複なしに実装する。ロジック自体は
[[project_v3_indicator_plan]]や既存のB方式(トリプル/H&S)と同じ考え方の
延長。

---

## 1. 構成点と全体像(下側始点の例、点1が谷)

```
                          点4(高値2)
                点2(高値1)  /
                    \      /
                     \    /
   ──┘\              /   点3(谷2)
        \            /
         点1(谷1)
```

- **点1・点3**: 片方の境界線(以下「下側の線」と呼ぶが、`start_is_low=False`
  で呼べば実体は上側になる)。両側確認ピボット(ダブル/トリプルの「山」と
  同じ`ext_flags`方式)。
- **点2・点4**: もう片方の境界線(「上側の線」)。同じく両側確認ピボット
  (`neck_flags`方式)。
- **点4だけ左側のみ確認**(トリプルの山3・H&Sの肩3と同じ理由 - 先読み
  防止。両側確認だと右側が確定するまで山4/点4が動かず、確定が
  `pivot_right_bars`本遅れてしまう)。

`start_is_low`(新設の探索方向フラグ)で「点1・点3が安値」か「点1・点3が
高値」かを選べる。フラグ/ペナントは旗竿(点1に入る直前の急な値動き)の
向きに応じてこれを選び分ける(§3.3)。それ以外(ボックス/トライアングル/
ウェッジ)はv1では常に`start_is_low=True`固定(§6.1で限界として明記)。

---

## 2. トリプルSTからの意図的な簡略化(3点)

6家系ぶんを堅牢に実装しきる時間を優先するため、探索コアはトリプル/H&Sの
以下3つの仕組みを**持たない**。理由とともに明記する。

1. **窓内の破綻(breach)判定なし**: トリプルは「窓内で山1の水準を大きく
   割ったら候補ごと無効」という仕組みを持つが、これは「M/W字は基準の山の
   水準に留まり続けるべき」という反転パターン特有の前提に基づく。チャネル
   系パターンは点1と点3の水準が異なってよい(それこそが傾き)ため、この
   前提が成立しない。単純化して「窓内の両側確認ピボットのうち最も極端な
   ものを採用(採用基準は§2.2のみ)」とする。
2. **ネックの「より深い候補優先+窓打ち切り規則A」なし**: 同じ理由(点2・
   点4は「浅い方が良い」という優先順位を持たない - 単に境界線上の点として
   後から採否を判定するだけ)。
3. **山1・山2・山3の水準許容誤差チェックなし(トリプルの設計判断2)**:
   チャネル系は水準が近いことを要求するとは限らない(傾きがあってよい)
   ため、代わりに§4の分類ロジックが「近いかどうか」を事後的に判定する。

一方、以下はトリプル/H&Sと**完全に同じ**ものを流用する: 両側/片側確認
ピボット検出(`_pivot_flags`+`_prominence_flags`)、値幅下限
(prominence_atr_mult)、孤立度チェック(`_shape_spike_ok`)、カウフマン
効率比(`_shape_eff_ratio`)、トレンドラインからの乖離(`_shape_dev_ok`)、
ブレイク判定余白・期限、confirm_floorによる先読み防止、Candidate→
Confirmed→Invalidatedの3状態モデル。

4. **時間対称性(interval_symmetry)チェックなし**: トリプル/H&Sは「山2
   (パターン中心)」という明確な基準点を軸に前半/後半の本数比を判定できた
   が、4点構成のチャネル系には同じ意味を持つ中心点がない。無理に代用の
   基準点を作ると、トリプルの時に実際に起きた「基準点の取り違えで検出数が
   大きく崩れる」不具合(docs/pattern_spec_triple_top_bottom_shape.md
   参照)を再発させかねないため、v1では見送る。

### 2.2 点の採用基準(統一)

全4点とも「窓内で条件を満たす両側確認(点4のみ左側のみ確認)ピボットの
うち、**より極端な値のときだけ更新**」(2026-08-14に確定した全構成点共通の
規則、ダブルの山2・トリプルの山3・H&Sの肩3と同じ)。窓の大きさは
`symmetry_ratio_min`/`symmetry_ratio_max`(直前の区間の本数に対する倍率、
トリプルと同じ変数名・同じ意味)。

---

## 3. ブレイク判定と旗竿(pole)

### 3.1 2本の線の値(判定バーごとに変化)

```
lower_line_at(j) = 点1_price + lower_slope × (j − 点1_bar)
upper_line_at(j) = 点2_price + upper_slope × (j − 点2_bar)
lower_slope = (点3_price − 点1_price) / (点3_bar − 点1_bar)
upper_slope = (点4_price − 点2_price) / (点4_bar − 点2_bar)
```

H&Sの斜めネックライン(§3.2)と同じ「2点を結んだ直線の延長」方式。

### 3.2 ブレイク判定

点4確定後、`breakout_deadline_min_bars`/`breakout_deadline_ratio_max`
(トリプルと同じ意味・基準脚は点1→点2の本数)以内に、終値/ヒゲが
`upper_line_at(j) + buf_j`を上抜け(上ブレイク)、または
`lower_line_at(j) − buf_j`を下抜け(下ブレイク)したら判定成立。
どちらが先に成立したかで方向が決まる。`want_upper_break`(コア引数)と
一致する方向なら**Confirmed**、逆方向に抜けたら**Invalidated**
(トリプルの`fail`と同じ扱い)。期限内にどちらも起きなければ
**Invalidated**(`expired`)。

余白(buf_j)の深さ計算は`|点2_price − 点1_price|`(最初の区間の値幅、
トリプルのbase_legに相当)を使う。

### 3.3 旗竿(ペナント/フラッグ専用)

トリプルの「山1前点→山1」の事前コンテキスト脚(`efficiency_ratio_min_
context`/`trendline_dev_pct_context`)を**そのまま旗竿として流用**する。
`start_is_low=False`(点1=高値)で呼べば、点1は「旗竿の先端(高値)」を
表すことになり、`pre_bar→点1`の脚が旗竿そのものになる。

新設パラメータ`pole_height_min_mult`(既定0=無効、ペナント/フラッグでは
既定3.0)で「旗竿の値幅がATRの何倍以上必要か」を追加要求する
(効率比・乖離チェックだけでは「まっすぐだが小さい動き」を弾けないため)。

- **上昇(強気)旗竿**: `start_is_low=False`(点1=高値=旗竿の先端)、
  `want_upper_break=True`(保ち合い後は上に継続ブレイク)。
- **下降(弱気)旗竿**: `start_is_low=True`(点1=安値=旗竿の先端)、
  `want_upper_break=False`。

ボックス/トライアングル/ウェッジは`pole_height_min_mult=0`(無効)の
まま、`efficiency_ratio_min_context`等は緩い既定値(トリプルと同じ0.1等)
にしておき、事前の脚に対する最低限の質チェックとしてのみ機能させる
(旗竿の強制ではない)。

---

## 4. 分類ロジック(コアの外、Python側の後処理)

コアは分類をせず、点1〜4の bar/price と、どちらに抜けたか
(`broke_upper`)だけを返す。家系ごとの判定はベクトル演算で以下を計算し、
AND条件でマスクする。

```
base_leg  = |点2_price − 点1_price|
tol       = base_leg × top_tolerance_mult   (0以下なら無制限)

flat(a, b)    = |b − a| <= tol
rising(a, b)  = (b − a) > tol
falling(a, b) = (a − b) > tol

lower_flat/rising/falling  … 点1→点3 に上式を適用
upper_flat/rising/falling  … 点2→点4 に上式を適用

entry_width = upper_line_at(点1_bar) − lower_line_at(点1_bar)
exit_width  = upper_line_at(点4_bar) − lower_line_at(点4_bar)
converging  = exit_width < entry_width × (1 − converge_margin)
parallel    = |exit_width − entry_width| <= entry_width × width_tol
```

| 関数 | start_is_low | want_upper | 分類条件 |
|---|---|---|---|
| `ascending_box_shape` | False | True | lower_flat & upper_flat |
| `descending_box_shape` | True | False | lower_flat & upper_flat |
| `ascending_triangle_shape` | False | True | lower_rising & upper_flat |
| `descending_triangle_shape` | True | False | lower_flat & upper_falling |
| `rising_wedge_shape` | False | False | lower_rising & upper_rising & converging |
| `falling_wedge_shape` | True | True | lower_falling & upper_falling & converging |
| `bullish_pennant_shape` | False | True | converging & pole_ok |
| `bearish_pennant_shape` | True | False | converging & pole_ok |
| `bullish_flag_shape` | False | True | lower_falling & upper_falling & parallel & pole_ok |
| `bearish_flag_shape` | True | False | lower_rising & upper_rising & parallel & pole_ok |

### 4.1 start_is_lowの選び方(2026-08-14、実データ検証で確定)

理論上はstart_is_lowがTrueでもFalseでも同じ4点が見つかるはずだが、実際は
「点1(探索の起点)を安値にすると、その後の値動きは下方向に確定しやすい」
「点1を高値にすると、上方向に確定しやすい」という非対称性が実データ
(USDJPY 15分足)で確認された(安値起点: 上方向ブレイク22件 vs 下方向
606件、高値起点: 上方向754件 vs 下方向51件 - 完全な鏡像)。点1(ピボット
安値/高値)自体が「その時点までの下降/上昇トレンドの終端」として検出される
ことが多く、値動きがそのまま継続しやすいという市場の一般的な性質と整合的
であるため、バグではなく実際の傾向と判断した。この傾向に合わせて、ボックス/トライアングルは
`want_upper=True`の家系を高値起点(start_is_low=False)、`want_upper=False`
の家系を安値起点(start_is_low=True)に統一した - 検出数を稼ぐための恣意的
な調整ではなく、点1の物理的な意味(トレンドの終端)により整合する選び方
になっている。

ウェッジだけは例外: 「両方の線が同じ方向(上昇/下降)」という**形そのもの**
の出現頻度にも同じ非対称性が現れ(上昇/上昇の形は高値起点でしか十分に
出現せず、下降/下降の形は安値起点でしか十分に出現しない)、これがブレイク
方向の非対称性より支配的だった。そのため上昇ウェッジ(弱気、下抜けで確定)
は高値起点、下降ウェッジ(強気、上抜けで確定)は安値起点という、ブレイク
方向だけで見ると逆に見える組み合わせを採用している - 教科書通りの意味
(上昇ウェッジ=弱気、下降ウェッジ=強気)を優先し、検出件数はその次に
最適化した結果。

`pole_ok = context_legs_ok (efficiency+deviation, コアが既に判定済み)
           & |点1_price − pre_level| >= atr_a[点1_bar] × pole_height_min_mult`

分類条件を満たさない候補は、この関数の出力(exists/candidate/confirmed/
invalidated 全て)から**丸ごと除外**する(トリプルの「窓内で条件を満たさず
continueする」候補と同じ扱い - 「そもそもこの家系の形ではなかった」もの
であり、Invalidatedとして表示すべき「この家系の形だったが失敗した」もの
とは区別する)。分類条件を満たし、かつ逆方向にブレイクした候補だけを
Invalidatedとして表示する。

---

## 5. 共通管理仕様

トリプル/H&Sと同じ(Candidate/Confirmed/Invalidated の3状態、
formed_barアンカー方式)。ダブル/トリプル/H&Sと異なりpattern_id/dedup key
は使わない(既存の`*_shape`系はそもそもこの仕組みを使っていない -
frontend側は`point1_time..point4_time`+`point_count=4`の汎用形式
(RRCP/推進波と同じ、`frontend/src/patternMarkers.ts::hasVariablePoints`)
で描画するため、専用のマーカー分岐追加も不要)。

---

## 6. 既知の限界(v1、時間制約下の意図的な判断)

1. **`start_is_low`は家系ごとに固定1方向のみ探索**(§1)。理論上は点1が
   反対側の型で始まる同じ形も存在しうるが検出されない。旗竿を伴わない
   4家系(ボックス/トライアングル/ウェッジ)で、双方向探索(2回呼んで
   マージ)にする拡張は今後の課題。
2. **点1〜点4は厳密に2点+2点(合計4点)のみ**。3回以上同じ境界に
   タッチする「教科書的に美しい」パターンは点3・点4以外のタッチを
   無視して判定する(トリプルが3点固定なのと同じ考え方)。
3. §2の3つの簡略化(破綻判定なし・優先順位なし・水準許容誤差なし)。

---

## 6.1 フラッグ2種の検出件数が少ないことについて(実データ検証、2026-08-14)

`bullish_flag_shape`(高値起点、falling/falling必須)・`bearish_flag_shape`
(安値起点、rising/rising必須)は、実データ(USDJPY 15分足)で検出件数が
非常に少ない(それぞれ0件・2件)。原因を調査した結果、ウィンドウの広さ
(symmetry_ratio_max)を狭めても変化がなく、**「高値起点の探索では
falling/fallingの形自体がほぼ出現しない(1386件中1件)」「安値起点では
rising/risingの形自体がほぼ出現しない(1149件中2件)」**という、§4.1と
同根のより強い非対称性が原因と判明した(確定済みピボット高値は、その後
「一旦下げてから再度下げる」形より「さらに高値を更新し続ける」形の方が
圧倒的に多い、という実データの性質)。

フラッグは定義上「旗竿と逆行する小さな保ち合い」であり、この非対称性の
影響を最も強く受ける家系(ペナントはlower_kind/upper_kind=anyのため影響
を受けない - 実際325件/208件と健全)。ウィンドウ調整では解決しないため、
v1では実データ上の希少なパターンとしてそのまま許容する - 教科書通りの
意味(上昇フラッグ=旗竿と逆行する下向き保ち合い)を優先し、無理に緩和
しない。

---

## 7. 検証手順

1. 合成データで各家系につき最低1パターン(上側/下側の線の傾きを明示的に
   作る)がCandidate/Confirmedで検出されることを確認。
2. 実データ(USDJPY 15分足)で検出件数・実行速度を確認。
3. `pole_height_min_mult`を上げるとペナント/フラッグの検出数が減ることを
   確認(旗竿が弱い候補が弾かれる)。
