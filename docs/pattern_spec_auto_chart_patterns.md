# チャートパターン仕様書 — チャネル / ウェッジ / トライアングル(13種)

バージョン: v1.0
作成日: 2026-08-12
作成方式: **B方式**(元コード → 言語化された仕様書 → StrategyX独自実装)

---

## 0. 参考元と依存追跡

### 0.1 参考元

| 項目 | 内容 |
|---|---|
| スクリプト名 | Auto Chart Patterns [Trendoscope®] |
| URL | https://www.tradingview.com/script/WZ8B1FIW-Auto-Chart-Patterns-Trendoscope/ |
| Pineバージョン | v6 |
| ライセンス | CC BY-NC-SA 4.0 / © Trendoscope Pty Ltd |
| 行数 | 272行(wrapperのみ。大半がinput定義。検出本体はライブラリ側) |

### 0.2 import追跡(ユーザー指示の手順1〜5)

```
wrapper
 ├─ Trendoscope/utils/6                  … 配色のみ・検出に無関係
 ├─ Trendoscope/ohlc/3                   … OHLC型
 ├─ Trendoscope/LineWrapper/2            … 直線の内挿
 ├─ Trendoscope/ZigzagLite/4             … ピボット生成
 ├─ Trendoscope/abstractchartpatterns/10 … ★型定義 + checkBarRatio + inspect
 └─ Trendoscope/basechartpatterns/9      … ★find(検出の入口) + 分類

basechartpatterns/9
 ├─ Trendoscope/ZigzagLite/4
 ├─ Trendoscope/LineWrapper/2
 ├─ Trendoscope/ohlc/3
 └─ Trendoscope/abstractchartpatterns/10
```

| ライブラリ | 役割 | 取得 |
|---|---|---|
| `basechartpatterns/9` | **検出の入口**(`find`)と分類(`resolvePatternName` / `resolve`) | ✅ 全文183行 |
| `abstractchartpatterns/10` | **判定部品**(`checkBarRatio` / `inspect` / `getRatioDiff` / 型) | ✅ 全文273行 |
| `LineWrapper` | `get_price` | ⚠️ **不明**(最新版のみ。式は自明) |
| `ohlc/3` | `OHLC` 型 | ✅ 該当部分 |
| `ZigzagLite/4` | ピボット生成 | ✅ **指定どおりの版が公開されていた** |

### 0.3 【不明】

`LineWrapper/2` そのものは取得できなかった(公開は最新版のみ)。
`get_price` は2点を通る直線の内挿という自明な式で、差分は不明だが変わりようがない。

`abstractchartpatterns/10` と `basechartpatterns/9` と `ZigzagLite/4` は
**指定どおりの版がそのまま公開されていた**ので、検出条件については差分の問題は無い。

### 0.4 【重要】フラッグ/ペナント(`chartpatterns/10`)との違い

`docs/pattern_spec_flags_pennants.md` と土台の考え方は同じだが、
**検出条件が違う**ので流用できない。

| 項目 | `chartpatterns/10`(F&P) | `basechartpatterns/9`(本仕様) |
|---|---|---|
| 前提チェック | `isSame`(傾き or 値幅比 + barRatio) | **`checkBarRatio`(バー間隔の比だけ)** |
| トレンドライン妥当性 | `[valid, score]` | **`[valid かつ score/総バー数 < 0.2, score]`** |
| ライン選択の追加規則 | 無し | `TrendLineMandatoryTouchPoints`(本スクリプトでは未指定=既定枝) |
| サイズフィルター | 無し | `SizeFilters` はあるが**本スクリプトからは呼ばれない** |
| 構成点の数 | 5点固定 | **5点 または 6点** |
| 出力 | 13種類のうち7種類を旗竿判定の土台に使う | **13種類すべてを出力** |
| パターン保持数 | `maxPatterns * 2` | **`maxPatterns`** |

**分類そのもの(`resolvePatternName`)は両ライブラリで完全に同一**なので、
実装では共用している。

---

## 1. パラメータ

| 表示名 | 内部名 | 型 | 初期値 | 最小 | 最大 | step |
|---|---|---|---|---|---|---|
| Zigzag1 有効 | `useZigzag1` | bool | **true** | — | — | — |
| Zigzag1 期間 | `zigzagLength1` | int | **8** | 1 | — | 5 |
| Zigzag1 保持数 | `depth1` | int | **55** | — | 500 | 25 |
| Zigzag2 有効 | `useZigzag2` | bool | **false** | — | — | — |
| Zigzag2 期間 | `zigzagLength2` | int | 13 | 1 | — | 5 |
| Zigzag2 保持数 | `depth2` | int | 34 | — | 500 | 25 |
| Zigzag3 有効 | `useZigzag3` | bool | **false** | — | — | — |
| Zigzag3 期間 | `zigzagLength3` | int | 21 | 1 | — | 5 |
| Zigzag3 保持数 | `depth3` | int | 21 | — | 500 | 25 |
| Zigzag4 有効 | `useZigzag4` | bool | **false** | — | — | — |
| Zigzag4 期間 | `zigzagLength4` | int | 34 | 1 | — | 5 |
| Zigzag4 保持数 | `depth4` | int | 13 | — | 500 | 25 |
| Number of Pivots | `numberOfPivots` | int | **5** | 5 or 6 | | |
| Error Threshold | `errorThresold` | float | **20.0** | 0 | 100 | 5 |
| Flat Threshold | `flatThreshold` | float | **20.0** | 0 | 30 | 5 |
| Last Pivot Direction | `lastPivotDirection` | string | **'both'** | up/down/both/custom | | |
| Verify Bar Ratio | `checkBarRatio` | bool | **true** | — | — | — |
| (同上) | `barRatioLimit` | float | 0.382 | — | — | — |
| Avoid Overlap | `avoidOverlap` | bool | **true** | — | — | — |
| Max Patterns | `maxPatterns` | int | **20** | 1 | — | 5 |

派生値: `errorRatio = errorThresold/100`(初期0.2)、`flatRatio = flatThreshold/100`(初期0.2)。
固定値: `offset = 0`。

**F&Pとの初期値の違い**: ZigZagは1本だけ有効(8/55)、`checkBarRatio` は **true**。

### 1.1 パターンごとの許可設定

参考元は3階層のグループトグルと13個の個別トグルを掛け合わせる。

```
allowedPatterns[種類] = 個別トグル
                    and 方向グループ(Rising / Falling / Flat・Bi-Directional)
                    and 形状動態グループ(Expanding / Contracting / Parallel)
                    and 形状グループ(Channels / Wedges / Triangles)
```

**すべて初期値 true** なので、初期状態では13種類すべてが許可される。

StrategyX では**1パターン=1指標**にするため、これらのトグルは持たない
(指標を選ぶこと自体が個別トグルに相当する)。

### 1.2 最後の構成点の向きフィルター

```
lastPivotDirection == 'up'   → +1
                   == 'down' → -1
                   == 'both' → 0(フィルターしない)
                   == 'custom' → パターンごとの個別設定を使う
```

初期値は `'both'` なので、**初期状態では方向フィルターは掛からない**。
`'custom'` のときだけ使われるパターン別の初期値は以下(参考記録):

| 種類 | 個別設定 |
|---|---|
| 1 上昇チャネル / 2 下降チャネル / 3 レンジチャネル | both |
| 4 上昇ウェッジ(拡大) | down |
| 5 下降ウェッジ(拡大) | up |
| 6 拡大トライアングル | both |
| 7 上昇トライアングル(拡大) | up |
| 8 下降トライアングル(拡大) | down |
| 9 上昇ウェッジ(収束) | down |
| 10 下降ウェッジ(収束) | up |
| 11 収束トライアングル | both |
| 12 下降トライアングル(収束) | down |
| 13 上昇トライアングル(収束) | up |

StrategyX では `last_pivot_direction`(both/up/down)の1つにまとめている。
`custom` は「1パターン=1指標」の構成では意味が無くなる(その指標の個別設定
そのものが `up`/`down` の指定になる)ため持たない。

### 1.3 検出に影響しないパラメータ

- `theme` / 各種 `show*` / `patternLineWidth` / `useCustomColors` … 描画のみ。
- `calc_bars_count = 5000` … 参考元の重さ対策。StrategyXでは全期間を計算する。
- **`repaint`(初期値 false)** … 参考元は `if barstate.isconfirmed or repaint` で
  走査するかを決める。**確定済みのバーでは `barstate.isconfirmed` が常に真**なので、
  バックテスト(全バーが確定済み)では `repaint` の値は結果を変えない。
  よって StrategyX ではパラメータとして出さない。

### 1.4 検出に影響するが「表示用」に見えるパラメータ

`maxPatterns` は重複・重なり判定に使う保持数を兼ねるので**検出結果を変える**。

---

## 2. パターンの構成点

`numberOfPivots` が 5 なら5点、6 なら6点。ZigZagの「新しい方から N 点」を
古い順に並べたものを `points[0] … points[N-1]` とする。

- **トレンドライン1** = `points[0]`, `points[2]`, `points[4]`(3点)
- **トレンドライン2** = 5点なら `points[1]`, `points[3]`(2点)
                        6点なら `points[1]`, `points[3]`, `points[5]`(3点)

```
上側が下がり下側が上がる例(収束トライアングル、5点)

  p0 ●
      \
       \    p2 ●
        \      / \
         \    /   \  p4 ●
          \  /     \  /
       p1  ●        ●  p3
```

---

## 3. ZigZagピボットの生成方法(レベル0)

`docs/pattern_spec_flags_pennants.md` の3章と**完全に同じ**(`ZigzagLite`)。
右側の確定を待たない lookback 型ピボットで、①置き換え ②新規追加
(Pineの演算子優先順位により1本のローソクに2つ立つことがある) ③強制追加の3分岐。

本仕様では `ratio` / `barRatio` フィールドは使わない
(0.4 のとおり前提チェックが `checkBarRatio` に変わり、
そちらは**ピボットのフィールドではなく構成点のバー位置から直接計算する**)。

---

## 4. 多段(recursive)ZigZag

`docs/pattern_spec_reversal_chart_patterns_recursive.md` の4章と**完全に同じ**。

---

## 5. 判定タイミングと走査手順

### 5.1 直線の価格

```
get_price(line, bar) = y1 + (bar - x1) * (y2 - y1) / (x2 - x1)
```

### 5.2 走査ループ

有効な各ZigZagについて、新しいピボットが出たバーだけ以下を回す。

```
if zigzag.flags.newPivot:
    mlzigzag = zigzag                          # レベル0
    while mlzigzag.zigzagPivots.size() >= 6:    # numberOfPivotsに関わらず6
        lastBar = mlzigzag.zigzagPivots.first().point.index
        if lastDBar[このZigZag][level] < lastBar:
            lastDBar[このZigZag][level] = lastBar
            [valid, pattern] = find(...)        # 6章
            if valid:
                patterns へ追加(上限 maxPatterns、古い方から捨てる)
                → **検出**
        else:
            break
        mlzigzag = mlzigzag.nextlevel()
```

`patterns` は**全ZigZag・全レベルで共有**する1つの配列。

---

## 6. パターンの判定(`find`)

### 6.0 既存パターンとの照合

```
for pattern in patterns:                        # 古い順、最大 maxPatterns
    startBar = pattern の先頭点のバー
    endBar   = pattern の末尾点のバー
    if 現先頭バー > startBar and 現先頭バー < endBar and avoidOverlap:
        無視して終了(break)
    先頭 N-1 点のバーが全部一致するなら「既出」
既出 or 無視 なら不成立
```

### 6.1 バー間隔の比(`checkBarRatio`)

```
checkBarRatio(p1, p2, p3) =
    checkBarRatio が false なら true
    そうでなければ  barRatioLimit <= |p3.index - p2.index| / |p2.index - p1.index| <= 1/barRatioLimit
```

- 5点: `checkBarRatio(points[0], points[2], points[4])`
- 6点: 上に加えて `checkBarRatio(points[1], points[3], points[5])` も要求

初期値 `barRatioLimit = 0.382` なので、比が **0.382〜2.618** に収まること。

### 6.2 トレンドラインの検証(`inspect`)

区間は `firstIndex = points[0].index` 〜 `lastIndex = points[N-1].index`。

**1本の直線に対する検証**

```
valid = true, score = 0, total = 0
for bar = firstIndex to lastIndex:
    total += 1
    barPrice    = direction > 0 ? 高値 : 安値
    barOutPrice = direction > 0 ? 安値 : 高値
    linePrice   = get_price(line, bar)

    if linePrice * direction < min(始値 * direction, 終値 * direction):
        valid = false; break                     # 実体を突き抜けた
    if barOutPrice*direction <= linePrice*direction <= barPrice*direction:
        score += 1                               # そのバーの値幅を通った
    else if bar == otherBar:
        valid = false; break                     # 使わなかった構成点に当たらない

戻り値 = [ valid かつ (score / total < 0.2), score ]
```

**最後の `score / total < 0.2` が F&P 側には無い追加条件**(0.4)。
ローソクに触れすぎている線 —— つまり価格帯の中をなぞっているだけで
境界線になっていない線 —— を弾く。

**3点から引く場合** … 3通りを試し、既定では

```
採用 = valid1 and score1 > max(score2, score3) ? 候補1(先頭—末尾)
     : valid2 and score2 > max(score1, score3) ? 候補2(先頭—中間)
     : 候補3(中間—末尾)
```

`otherBar` はそれぞれ使わなかった点のバー。

参考元には「必須接触点」(`TrendLineMandatoryTouchPoints`: NONE/START/END/BOTH)
による別の選び方もあるが、**Auto Chart Patterns からは渡されない(= `na`)**ため
常に上の既定枝になる。

**2点から引く場合**(5点構成のトレンドライン2)… 1本のみ。`otherBar` は先頭点。

**方向**

```
firstDirection = points[0].price > points[1].price ? 1 : -1
トレンドライン1 の direction =  firstDirection
トレンドライン2 の direction = -firstDirection
```

両方 valid でなければ不成立。

### 6.3 端点の引き直しと構成点の載せ直し(`resolve`)

2本の線を区間の両端まで延長・切り詰めて端点を取り直す。

```
t1p1 = トレンドライン1 の firstIndex での価格
t1p2 = トレンドライン1 の lastIndex  での価格
t2p1 = トレンドライン2 の firstIndex での価格
t2p2 = トレンドライン2 の lastIndex  での価格
```

構成点の価格を、対応する線の上の値に**置き換える**。

```
points[i] → i が偶数ならトレンドライン1、奇数ならトレンドライン2
```

### 6.4 13種類への分類(`resolvePatternName`)

`docs/pattern_spec_flags_pennants.md` の6.4と**完全に同一**の式・分岐。
結果は次の13種類(および該当なしの0)。

| コード | 名前 |
|---|---|
| 1 | 上昇チャネル |
| 2 | 下降チャネル |
| 3 | レンジチャネル |
| 4 | 上昇ウェッジ(拡大) |
| 5 | 下降ウェッジ(拡大) |
| 6 | 拡大トライアングル |
| 7 | 上昇トライアングル(拡大) |
| 8 | 下降トライアングル(拡大) |
| 9 | 上昇ウェッジ(収束) |
| 10 | 下降ウェッジ(収束) |
| 11 | 収束トライアングル |
| 12 | 下降トライアングル(収束) |
| 13 | 上昇トライアングル(収束) |

### 6.5 許可フィルター

```
lastDir = sign(points[N-1].price - points[N-2].price)     # 載せ直した後の価格で判定

allowedPattern = allowedPatterns[種類]
             and (allowedLastPivotDirections[種類] == 0
                  or allowedLastPivotDirections[種類] == lastDir)
```

種類が 0(該当なし)や範囲外なら不許可。

---

## 7. 共通管理仕様(全detector共通)

### 7.1 ① pattern_id

```
pattern_id = パターン種類 + "_" + 各構成点のバー位置(古い順)
例: converging_triangle_512_534_549_567_588
```

**重複判定は最新の構成点を除いて行う。** ZigZagの最新ピボットは右側の確定を待たずに
置き換えられる(=後から動く)ため、全構成点で同一性を見ると「同じ形なのに最新点の
位置だけ違う別パターン」が何度も登録されてしまう。実測ではUSDJPY15分足の
トリプルトップで検出された形の48%がこの重複だった。
`pattern_id` として出力する値は全構成点を含んだままで、判定にだけこの規則を使う。

これは参考元の照合規則(6.0 の「先頭 N-1 点のバーが全部一致するなら既出」)と
同じ考え方である。

### 7.2 ② 1パターン1決着

Candidate / Confirmed / Invalidated はそれぞれ1回だけ。

### 7.3 ③ 複数パターンの同時存在

未決着のものは何件でも保持し、同一バーで複数決着してもすべて個別に出力する。

### 7.4 ④ 状態管理

CANDIDATE / CONFIRMED / INVALIDATED。
**EXPIRED は設けない**(参考元に期限条件が無いため)。

### 7.5 ⑤ 先読み・リペイント

- `offset = 0`。当バーのOHLCまでしか見ない。**先読みは無い。**
- ピボットは右側の確定を待たないため**リペイントし得る**(参考元の設計)。
- `inspect` が読む区間の終端は最後の構成点のバーであり、現在バー以前。
- Candidate成立バーは走査が走ったバー(現在バー)。

---

## 8. StrategyX独自拡張

### 8.1 Confirmed / Invalidated の水準

参考元は形を描画するだけで、成立後の追跡をしない。
共通の状態モデルに載せるため、**パターン自身の2本のトレンドラインだけ**を使って
以下のように定める(新しい価格を発明しない)。

```
lastDir = 最後の構成点の向き(6.5と同じ)

ネックライン側の線 = 最後の構成点が乗っている線
                   (5点構成ならトレンドライン1、6点構成ならトレンドライン2)
極値側の線        = もう一方の線

lastDir > 0 の場合:
    ネックライン = ネックライン側の線の高い方の端
    極値        = 極値側の線の低い方の端
    Confirmed   … 高値がネックラインを下から上へクロス
    Invalidated … 安値が極値を上から下へクロス

lastDir < 0 の場合:
    ネックライン = ネックライン側の線の低い方の端
    極値        = 極値側の線の高い方の端
    Confirmed   … 安値がネックラインを上から下へクロス
    Invalidated … 高値が極値を下から上へクロス
```

- クロス判定は**ヒゲ**(High / Low)。終値は使わない。
- 同一バーで両方成立したら **Confirmed 優先**。
- この決め方はフラッグ/ペナント側(参考元自身が同じ2本の線から
  `invalidationPrice` / `validationPrice` を作っている)と揃えてある。

**注意**: シグナルの向きは `lastDir` で決まるため、
`last_pivot_direction = 'both'`(初期値)のままだと**同じ指標に上向きと下向きの
両方が混ざる**。方向を固定したい場合は `'up'` / `'down'` を指定すること。

### 8.2 その他の独自拡張

| 項目 | 参考元 | StrategyX |
|---|---|---|
| 計算範囲 | 直近 `calc_bars_count`(5000)本のみ | **全期間** |
| `repaint` | 実質バックテストでは無効果(1.3) | パラメータとして出さない |
| パターン別トグル | 13個のON/OFF + グループ3階層 | **1パターン=1指標**に置き換え |
| `lastPivotDirection = 'custom'` | パターン別に個別指定 | 指標ごとの `last_pivot_direction` に集約 |
| `SizeFilters` | 型はあるが本スクリプトからは未使用 | 実装しない |
| 有効範囲の保証 | UIのmin/maxのみ | detector内部でもクリップする |

### 8.3 容量上限

| 定数 | 値 | 内容 |
|---|---|---|
| `_ACP_MAX_LEVELS` | 32 | 走査する最大レベル数 |
| `_ACP_SLOT_CAPACITY` | 4096 | 同時監視する未決着パターンの上限 |

パターン配列(`maxPatterns`)は参考元どおりの上限を使う(検出結果を変えるため)。

### 8.4 計算量の目安

USDJPY 15分足 全期間(579,552本)・初期値(ZigZag1本のみ)で **約0.9秒**、
検出 22,315 イベント。4本すべて有効でも約0.8秒、6点構成で約0.4秒。

---

## 9. 出力

### 9.1 イベント列(`events`)

| キー | 内容 |
|---|---|
| `pattern_id` | 7.1 |
| `pattern_type` | 13種類の名前(6.4) |
| `zigzag_index` | どのZigZag(1〜4)で見つかったか |
| `level` | 多段ZigZagのレベル |
| `last_pivot_direction` | +1(高値終わり)/ -1(安値終わり) |
| `status` | `candidate` / `confirmed` / `invalidated` |
| `event_bar` | そのイベントが起きたバー位置 |
| `point_bars` | 構成点のバー位置(古い順、5点または6点) |
| `point_prices` | 同じ順の価格(6.3で載せ直した後の値) |
| `neckline_price` | 8.1 |
| `extreme_price` | 8.1 |

### 9.2 Boolean系列

パターン名 × 状態ごとの Boolean系列も返す。
同一バーに複数イベントが乗ると1つに潰れるため、
件数や構成点が要る用途では 9.1 を読むこと。
