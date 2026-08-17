# トリプルトップ/ボトム・カップ&ハンドル・ヘッド&ショルダーズ 検出仕様書 v1.0

| 項目 | 内容 |
|---|---|
| 文書ID | SL-PAT-RRCP-001 |
| 版 | v1.0(2026-08-12) |
| 対象 | Triple Top / Triple Bottom / Cup and Handle / Inverted Cup and Handle / Head and Shoulders / Inverse Head and Shoulders |
| 方式 | B方式(参考元コードを移植せず、検出仕様を抽出して独自実装) |
| 参考元 | "Recursive Reversal Chart Patterns [Trendoscope®]" (Pine v6) |
| 参考元ライセンス | CC BY-NC-SA 4.0 |
| 参考元著作権表記 | © Trendoscope Pty Ltd, Trendoscope® |
| 実装先 | `engine/chart_patterns.py::_rrcp_state` |

本書は「元のPineコードを見なくても、仕様だけで独自実装できる」ことを目標とする。

**ダブルトップ/ボトムは対象外**。あちらは別系統(MPL-2.0の "Double Top/Bottom -
Ultimate (OS)")を出典とする独立実装で、`docs/pattern_spec_double_top_bottom_zigzag.md`
が仕様書。本書のパターンとはZigZagの作り方から違うので混同しないこと。

---

## 0. 依存追跡の記録

参考元のスクリプト単体には検出条件が含まれておらず、importしているライブラリ側に
本体があった。以下まで辿って仕様化した。

```
Recursive Reversal Chart Patterns [Trendoscope®]   ← 呼び出し側のみ
├── Trendoscope/reversalchartpatterns/2   ★判定条件の本体(全349行を確認)
│   ├── Trendoscope/Drawing/2             描画のみ。検出に無関係
│   ├── Trendoscope/Zigzag/11             ★ratio計算・ピボット検出・多段化(全759行を確認)
│   │   └── Trendoscope/arrays/2          配列ユーティリティのみ。検出に無関係(確認済み)
│   └── Trendoscope/TradeTracker/1        エントリー/損切り/利確の保持。検出に無関係
├── Trendoscope/utils/6                   テーマ色のみ。検出に無関係
└── Trendoscope/iLogger/1                 ログのみ。検出に無関係
```

**確認できていない事項**(推測で実装しない、7章に扱いを明記):

| 項目 | 状態 |
|---|---|
| `ta.highestbars` の同値時の返り値 | **不明**。「最も新しい位置を返す」と解釈した |
| `Pivot.copy()` が浅いコピーか深いコピーか | **不明**。値のコピーとして扱う |
| `Drawing/2`・`TradeTracker/1`・`utils/6`・`iLogger/1` の中身 | 未取得。用途から検出に無関係と判断 |

---

## 1. パラメータ

参考元の呼び出し側で公開されているもののうち、検出結果に影響するものだけを採る。

| 内部名 | UI表示 | 型 | 初期値 | 最小 | 最大 | step | 意味 |
|---|---|---|---|---|---|---|---|
| `zigzag_length` | ZigZag期間 | int | 8 | 3 | 制限なし | 5 | 本。Pivot候補のlookback長 |
| `depth` | ZigZag保持数 | int | 50 | 制限なし | 500 | 25 | 各レベルで保持するPivot数 |
| `min_zigzag_level` | 最小ZigZagレベル | int | 0 | 0 | 制限なし | 1 | このレベル未満は走査しない |
| `error_percent` | 許容誤差(%) | float | 13 | 0 | 50 | 5 | Tap判定の許容幅 |
| `shoulder_start` | 肩の比率(下限) | float | 0.1 | 0.1 | 1.0 | 0.05 | 肩・ハンドル・ネックの下限 |
| `shoulder_end` | 肩の比率(上限) | float | 0.5 | 0.5 | 1.0 | 0.05 | 肩・ハンドル・ネックの上限 |

**有効範囲の保証**: 上表の最小・最大は**検出器の内部でも保証する**(UI側の指定だけに
頼らない。保存済みJSON経由などUIを介さない経路があるため)。範囲外は境界値へ丸める。
`step` はUI入力欄の増減単位としてのみ扱い、検出器は範囲内の任意の値を受け付ける。

`shoulder_start <= shoulder_end` も保証する(逆転して渡された場合は入れ替える)。

**採用しなかった参考元パラメータ**:

| 項目 | 理由 |
|---|---|
| `riskAdjustment` (13) | 損切り価格の余白。検出条件に影響しない(6章参照) |
| RSI/MFI/OBV/カスタム指標 | 既定OFF。ONにするとTap判定に追加条件が付く(3.3参照)が、StrategyXでは採用しない |
| `useRealTimeBars` / `offset` | 参考元は `true` 固定なので `offset = 0` 相当。可変にしない |
| 各種表示設定(色・線幅・テーマ等) | 描画専用 |

---

## 2. 使用データ

| データ | 使用 | 用途 |
|---|---|---|
| High | 必須 | Pivot候補、Confirmed/Invalidated判定 |
| Low | 必須 | Pivot候補、Confirmed/Invalidated判定 |
| Open / Close / Volume / ATR | **不使用** | |

---

## 3. ZigZag(レベル0)

### 3.1 Pivot候補(lookback型、右側確認なし)

各バー `i` で、直近 `zigzag_length` 本(自分を含む)の最高値/最安値を求める。

```
pHigh(i) = max(high[i-L+1 .. i]),  pHighBar(i) = 0 なら high[i] がその最高値
pLow(i)  = min(low[i-L+1 .. i]),   pLowBar(i)  = 0 なら low[i] がその最安値
```

`pHighBar`/`pLowBar` は「最高値/最安値のバーまでのオフセット(0以下)」。
**同値のとき最も新しい位置を返す**と解釈する(**不明**、0章参照)。

### 3.2 Pivotの追加・置換

`dir` は直近Pivotの方向。`+1`系=高値Pivot、`-1`系=安値Pivot。Pivotは必ず交互になる
(同方向が連続したら参考元は実行時エラーを出す)。

処理は毎バー、次の順に評価する。

```
newBar   = 現在のバー位置
distance = newBar - 直近Pivotのバー位置
overflow = distance >= zigzag_length

① 同方向でより極端 → 直近Pivotを置き換え
   条件: (dir==+1 かつ pHighBar==0) または (dir==-1 かつ pLowBar==0)  かつ Pivotが1つ以上ある
   value = dir==+1 ? pHigh : pLow
   さらに value * dir >= 直近Pivot価格 * dir  のときのみ実行
   → 直近Pivotを取り除いてから、(newBar, value, dir) を追加

② 反対方向のPivot → 新規追加
   条件(原文どおり、Pineの演算子優先順位を保つ):
     (dir==+1 かつ pLowBar==0)
     または (dir==-1 かつ pHighBar==0 かつ (①で追加していない または forceDoublePivot))
   value = dir==+1 ? pLow : pHigh
   → (newBar, value, -dir) を追加

③ length本Pivotが出ていなければ強制追加
   条件: overflow かつ ①②のどちらでも追加していない
   value    = dir==+1 ? pLow : pHigh
   valueBar = dir==+1 ? newBar + pLowBar : newBar + pHighBar
   → (valueBar, value, -dir) を追加
```

`forceDoublePivot` は、Pivotが2つ以上あるとき次で決まる。

```
dir==+1 かつ pLowBar==0  → pLow  < 2つ前のPivot価格
dir==-1 かつ pHighBar==0 → pHigh > 2つ前のPivot価格
それ以外 → false
```

> **原文の非対称性について**: ②の条件は Pine の `and` が `or` より強いため、
> `dir==+1` 側には「①で追加していない」というガードが**掛からない**。意図か
> 不具合かは**不明**だが、参考元の挙動を再現するためそのまま実装する。

Pivot配列は先頭(index 0)が最新。`depth` を超えたら末尾(最古)を捨てる。

### 3.3 Pivotに付随する値

Pivotを追加するたび、直前2つのPivotと比べて次を計算する(Pivotが3つ以上ある場合)。

```
value      = 追加するPivotの価格
lastValue  = 1つ前のPivotの価格
llastValue = 2つ前のPivotの価格
dir        = 追加するPivotの方向の符号(+1/-1)

ratio = round( |lastValue - value| / |llastValue - lastValue| , 小数第3位 )     ★判定に使う

dir(分類) = (dir * value > dir * llastValue) ? dir * 2 : dir
```

**`ratio` の意味**: 「直前の1本の波の値幅」に対する「今の1本の波の値幅」の比。

**`dir` の分類**: 絶対値2 = 2つ前の同方向Pivotを更新した(新記録)、絶対値1 = 更新して
いない。ダブルトップ側のHH/LH/HL/LLと同じ考え方。

参考元は `barRatio`(本数の比)・`sizeRatio`・`indicatorRatios` も計算するが、
`barRatio` と `sizeRatio` は**判定に使われていない**。`indicatorRatios` は
RSI等を有効にしたときだけTap判定に条件が加わるが、既定OFFかつStrategyXでは
採用しないため常に空として扱う(=Tap判定の指標条件は常に真)。

---

## 4. 多段ZigZag(レベル1以上)

レベル `n` のPivot列から、レベル `n+1` のPivot列を作る。**古い順**に1つずつ処理する。

保留用に `tempBullishPivot`(高値側)と `tempBearishPivot`(安値側)を持つ(初期はなし)。

```
各Pivot P について(古い順):
    dir     = P.dir          (±1 または ±2)
    newDir  = sign(dir)
    P.level = P.level + 1

    上位配列がまだ空のとき:
        |dir| == 2 なら P を追加。|dir| == 1 なら何もしない

    上位配列に既に何かあるとき:
        lastPivot = 上位配列の先頭(最新)

        |dir| == 2 の場合:
            lastPivot と同方向なら:
                dir * lastPivot価格 < dir * P価格  → 先頭を取り除く(より極端なので置換)
                そうでなければ:
                    反対側の保留Pivot(newDir>0なら tempBearish、else tempBullish)があれば
                    それを先に追加する。無ければ この P は捨てて次へ進む
            lastPivot と逆方向なら:
                同方向の保留(tempFirst)と反対方向の保留(tempSecond)が両方あり、かつ
                newDir * tempFirst価格 > newDir * P価格 のときだけ、
                tempFirst → tempSecond の順に追加する
            そのうえで P を追加し、保留を両方クリアする

        |dir| == 1 の場合(上位には昇格させず保留に貯める):
            同方向の保留があれば、P の方がより極端(P価格*dir > 保留価格*dir)なら差し替え
            保留が無ければ P を保留にする

最後に: 上位のPivot数 >= 元のPivot数 なら、上位配列を空にする(それ以上細かくならない
ので打ち切り)
```

追加時は3.3の `ratio` / `dir` 再計算が同じ規則で行われる(上位レベルのPivot列の中で、
その1つ前・2つ前と比べ直す)。

---

## 5. パターン判定

### 5.1 走査のタイミングと範囲

- **レベル0で新しいPivotが出たバー**でのみ走査する
- レベル0から始め、そのレベルのPivot数が **4より多い間**、`min_zigzag_level` 以上の
  レベルについて判定する。判定後 `nextlevel()` で上位へ進む
- 各レベルで見るのは**先頭4つのPivotだけ**(index 0〜3)

### 5.2 判定に使う値

先頭から `c(0) → b(1) → a(2) → x(3)`(新しい順)とし、各Pivotの `ratio` を取る。

```
r1 = c.ratio      r2 = b.ratio      r3 = a.ratio      r4 = x.ratio

min = 1 - error_percent / 100          (13なら 0.87)
max = 1 + error_percent / 100          (13なら 1.13)

rN が Tap      : min <= rN <= max
rN が Shoulder : shoulder_start <= rN <= shoulder_end       (0.1〜0.5)
r3 が Head     : 1/shoulder_end <= r3 <= 1/shoulder_start   (2〜10)
```

比較はすべて**両端を含む**(`>=` と `<=`)。

### 5.3 各パターンの成立条件

| パターン | 条件 |
|---|---|
| Triple Tap(3) | `r1:Tap かつ r2:Tap かつ r3:Tap かつ r4:Shoulder` |
| Head and Shoulders(4) | `r1:Shoulder かつ r2:Tap かつ r3:Head かつ r4:Shoulder` |
| Cup and Handle(3点) | `Head and Shouldersでない かつ r1:Shoulder かつ r2:Tap` |

参考元の Double Tap(`r1:Tap かつ r2:Shoulder かつ Triple Tapでない`)は、本書の
対象外(別系統の実装が既にあるため)。

**優先順位**: 参考元は `doubleTap → tripleTap → cupAndHandle → headAndShoulders` の順に
判定し、最初に当たったものを採用する。Double Tapを除外すると
**Triple Tap → Cup and Handle → Head and Shoulders** の順になる。

> Cup and Handle の条件は Head and Shoulders の条件の一部(r1:Shoulder と r2:Tap)を
> 含むため、`not headAndShoulders` という除外が入っている。Triple Tap と
> Cup and Handle は `r1` が Tap か Shoulder かで排他になる(範囲が重ならない限り)。

### 5.4 上下(トップ/ボトム)の決定

**一番古いPivot `x` の `dir` の符号**で決まる。

| x.dir の符号 | Triple Tap | Cup and Handle | Head and Shoulders |
|---|---|---|---|
| 負(x が安値) | Triple Top | Inverted Cup and Handle | Head and Shoulders |
| 正(x が高値) | Triple Bottom | Cup and Handle | Inverse Head and Shoulders |

### 5.5 重複判定

参考元は、既に検出済みのパターン(直近10件を保持)と比べ、**index 1 以降の全Pivotの
バー位置が一致**したら重複とみなして検出しない(index 0 は比較から除外される)。

StrategyXでは共通管理仕様の `pattern_id` で置き換える(7.1)。

### 5.6 パターンを構成するPivot数

| パターン | 構成点 |
|---|---|
| Triple Tap | 6点(index 0〜5) |
| Cup and Handle | 4点(index 0〜3) |
| Head and Shoulders | 6点(index 0〜5) |

**判定自体は常に先頭4点の `ratio` だけで行う**。6点使うのは構成点の記録・描画のみ。

---

## 6. Confirmed / Invalidated(StrategyX独自の拡張)

> **ここは参考元に存在しない**。参考元の `scan()` は形が揃った時点でパターン種類を
> 返すだけで、その後の追跡処理がライブラリにもwrapper側にも無い。
> 2026-08-12のユーザー決定により、全チャートパターンで状態モデルを揃えるため、
> ダブルトップ/ボトムと同じ形の判定を被せる。
> **判定に使う水準は参考元自身が計算しているものを使い、独自に発明しない。**

### 6.1 水準の定義

参考元の `init()` は次を計算している(検出には使っていない)。

```
エントリー価格 = pivots[1].price          … 新しい方から2番目のPivot
損切り価格     = pivots[0].price ± riskAdjustment(13%)分の余白
方向           = sign(pivots.last().dir)  … 一番古いPivotの方向
```

このうち**エントリー価格をネックラインとして採用する**。損切り側は余白パラメータが
入るため採用せず、代わりにパターンの極値を使う。

| 名称 | 定義 |
|---|---|
| ネックライン | `pivots[1].price`(新しい方から2番目のPivot、参考元のエントリー価格) |
| パターン極値 | トップ系: 構成点の中で最も高い価格 / ボトム系: 最も安い価格 |

### 6.2 判定

Candidate成立後、**毎バー**評価する。期限・バッファ・リテストは設けない。

| 方向 | 状態 | 条件 |
|---|---|---|
| トップ系 | Confirmed | Low がネックラインを**下方向へクロス** |
| トップ系 | Invalidated | High がパターン極値を**上方向へクロス** |
| ボトム系 | Confirmed | High がネックラインを**上方向へクロス** |
| ボトム系 | Invalidated | Low がパターン極値を**下方向へクロス** |

```
crossunder(x, level): x[i] <  level  かつ  x[i-1] >= level
crossover (x, level): x[i] >  level  かつ  x[i-1] <= level
```

終値ではなく**High / Low(ヒゲを含む)**で判定する。

同一バーで両方成立した場合は **Confirmed を優先**する。

判定はCandidateが成立した**そのバーから**始める。Candidate成立前のバーへ遡らない。

---

## 7. StrategyX共通管理仕様の適用

### 7.1 パターンごとの一意ID

```
pattern_id = パターン種類 + "_" + 全構成点のバー位置を "_" でつないだもの
例: triple_top_100_120_140_160_180_200
```

構成点が1つでも異なれば別パターン…**ではなく、参考元の重複判定(5.5)と同じく
最新の構成点(index 0)を比較から除く**。
**重複判定は最新の構成点を除いて行う。** ZigZagの最新ピボットは右側の確定を待たずに
置き換えられる(=後から動く)ため、全構成点で同一性を見ると「同じ形なのに最新点の
位置だけ違う別パターン」が何度も登録されてしまう。実測ではUSDJPY15分足の
トリプルトップで検出された形の48%がこの重複だった。
`pattern_id` として出力する値は全構成点を含んだままで、判定にだけこの規則を使う。


**レベル違いは別パターンとして扱う**。多段ZigZagでは同じバー位置のPivotが複数レベルに
現れうるが、構成点の組み合わせが違えばIDも異なるため自然に区別される。構成点が完全に
一致する場合は同じパターンとみなす(レベルが違っても実体は同じ形のため)。

### 7.2 Candidate成立後の構成点固定

Candidate成立時点で全構成点のバー位置・価格・判定水準を固定する。以降、新しいPivotや
ZigZag更新が起きても書き換えない。

### 7.3 1パターン1決着

同じ `pattern_id` から Confirmed / Invalidated を複数回発生させない。決着したら監視を
終了する。

### 7.4 複数パターンの同時保持

未決着のパターンを複数同時に監視する。Pivotを共有していても、レベルが違っても、
形成期間が重複していても自動削除しない。

> 参考元は直近10件を重複判定用に保持するだけで、決着の追跡自体をしていない。

### 7.5 状態遷移

```
CANDIDATE → CONFIRMED
CANDIDATE → INVALIDATED
```

参考元に期限切れ条件が無いため **EXPIRED は使わない**。

### 7.6 先読み・リペイント

| 項目 | 内容 |
|---|---|
| Pivotの確定 | 右側確認なし。ただし①の置換規則により、**最新Pivotは後から動きうる** |
| Candidateを最初に認識可能なバー | そのレベルのPivotが4つ以上たまり、条件を満たしたバー |
| Confirmed/Invalidatedを最初に認識可能なバー | Candidate成立バー以降 |
| リペイント | **あり**。index 0 のPivotは置換されうる。ただし判定に使う `ratio` は index 0〜3 の全てに関わるため、**index 0 が動くと判定結果も変わりうる** |

> **ダブルトップ/ボトム(別仕様書)との重要な違い**: あちらは index 1〜3 だけで判定する
> ためCandidate成立時点で3点が確定していた。本書のパターンは **index 0 を含めて判定
> する**ため、Candidateが成立したバーの後で index 0 のPivotが置換されると、同じ形が
> 別の構成点として再度Candidateになりうる。参考元もこの挙動のままなので変更しないが、
> バックテストでは「そのバー時点で利用可能な情報のみ」を使う点は守る(未来のバーを
> 見て遡って判定しない)。

---

## 8. 出力

### 8.1 イベント一覧(欠落のない出力)

1イベント1レコードで時系列順に並べる。同一バーに何件でも並べられる。

| フィールド | 意味 |
|---|---|
| `pattern_id` | 7.1の一意ID |
| `pattern_type` | `triple_top` / `triple_bottom` / `cup_and_handle` / `inverted_cup_and_handle` / `head_and_shoulders` / `inverse_head_and_shoulders` |
| `status` | `candidate` / `confirmed` / `invalidated` |
| `event_bar` | イベントが発生したバー位置 |
| `level` | 検出されたZigZagレベル |
| `point_bars` / `point_prices` | 構成点(4点または6点、新しい順) |
| `neckline_price` | 6.1のネックライン |
| `extreme_price` | 6.1のパターン極値 |
| `ratios` | 判定に使った r1〜r4 |

### 8.2 Boolean系列(互換用)

StrategyXの条件式が要求するため、パターン種類ごとに
`candidate` / `confirmed` / `invalidated` のBoolean系列も返す。
**同一バーの複数イベントは1つに潰れる**ので、件数や構成点が要る用途では8.1を読む。

---

## 9. 実装前チェックリスト

- [ ] `zigzag_length` 初期値8・min3・step5、`depth` 初期値50・max500・step25 を保持したか
- [ ] `error_percent` 初期値13・0〜50・step5 を保持したか
- [ ] `shoulder_start` 初期値0.1・0.1〜1.0、`shoulder_end` 初期値0.5・0.5〜1.0 を保持したか
- [ ] 上記の範囲を検出器内部でも保証したか(UI任せにしていないか)
- [ ] Pivot候補を左右対称ではなく lookback型 として実装したか
- [ ] 置換①・新規追加②・強制追加③ の3分岐と、②の演算子優先順位による非対称性を再現したか
- [ ] `forceDoublePivot` を再現したか
- [ ] `ratio` を**小数第3位で丸めて**いるか(丸め忘れは境界判定に影響する)
- [ ] `dir` の ±2 / ±1 分類を「2つ前の同方向Pivotとの比較」で行っているか
- [ ] 多段ZigZagの保留Pivot(tempBullish/tempBearish)の扱いを再現したか
- [ ] 「上位のPivot数 >= 元のPivot数 なら空にする」打ち切りを入れたか
- [ ] 走査を「レベル0で新Pivotが出たバー」に限定したか
- [ ] 各レベルで先頭4つのPivotだけを見ているか
- [ ] Tap/Shoulder/Head の比較を**両端含む**で実装したか
- [ ] Head の範囲を `1/shoulder_end 〜 1/shoulder_start` にしたか(逆数を忘れていないか)
- [ ] 優先順位を Triple → Cup and Handle → Head and Shoulders にしたか
- [ ] Cup and Handle に `not headAndShoulders` の除外を入れたか
- [ ] 上下の判定を**一番古いPivotの dir の符号**で行っているか
- [ ] 構成点数を Triple/H&S = 6点、Cup and Handle = 4点 にしたか
- [ ] Confirmed/Invalidated が独自拡張であることを明示したか(6章)
- [ ] ネックラインを `pivots[1].price` にしたか(参考元のエントリー価格)
- [ ] Confirmed/Invalidated をヒゲ(High/Low)で判定したか
- [ ] 同一バー競合で Confirmed を優先したか
- [ ] pattern_id で重複登録を防ぎ、外部出力にも含めたか
- [ ] 1パターン1決着になっているか
- [ ] 複数パターン(レベル違いを含む)を同時に監視しているか
- [ ] 同一バーで複数決着した場合に全件をイベントとして保持しているか
- [ ] 参考元に無い品質フィルター(ATR・期限・リテスト・効率比・出来高)を追加していないか
