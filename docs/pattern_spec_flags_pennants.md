# チャートパターン仕様書 — フラッグ / ペナント(4種)

バージョン: v1.0
作成日: 2026-08-12
作成方式: **B方式**(元コード → 言語化された仕様書 → StrategyX独自実装)

対象パターン: 強気フラッグ / 弱気フラッグ / 強気ペナント / 弱気ペナント

---

## 0. 参考元と依存追跡

### 0.1 参考元

| 項目 | 内容 |
|---|---|
| スクリプト名 | Flags and Pennants [Trendoscope®] |
| URL | https://www.tradingview.com/script/25YrlXsf-Flags-and-Pennants-Trendoscope/ |
| Pineバージョン | v6 |
| ライセンス | CC BY-NC-SA 4.0 / © Trendoscope Pty Ltd |
| 行数 | 149行(wrapperのみ。検出本体はライブラリ側) |

### 0.2 import追跡(ユーザー指示の手順1〜5)

wrapperのimport文:

```
import Trendoscope/utils/1        as ut     // 配色のみ・検出に無関係
import Trendoscope/ohlc/3         as o
import Trendoscope/LineWrapper/2  as wr
import Trendoscope/ZigzagLite/3   as zg
import Trendoscope/chartpatterns/10 as p    // ★検出本体
```

`chartpatterns/10` のimport文:

```
import Trendoscope/ZigzagLite/3  as zg
import Trendoscope/LineWrapper/2 as wr
import Trendoscope/ohlc/3        as o
```

追跡結果:

| ライブラリ | 役割 | 取得 |
|---|---|---|
| `chartpatterns` | **検出本体**(`findPatternPlain` / `findFNP` / `resolvePatternName` / `inspect` / `isSame`) | ✅ 全文(614行) |
| `LineWrapper` | `get_price`(直線の内挿) | ✅ 該当部分 |
| `ohlc` | `OHLC` 型(`o` `h` `l` `c` の4フィールド) | ✅ 該当部分 |
| `ZigzagLite` | ピボット生成 | ⚠️ **不明**(後述) |
| `utils` | 配色のみ | 不要 |

### 0.3 【不明】指定バージョンとの差分

TradingViewは公開ライブラリの**最新版のソースしか表示しない**ため、
参考元が指定している `ZigzagLite/3` と `LineWrapper/2` そのものは取得できなかった。

- ZigZag部分(3章・4章)は `ZigzagLite/4` を書き起こしたもの。
  `ZigzagLite/4` は公開版 `Zigzag` から指標対応を取り除いただけで、
  ピボット検出・ratio計算・多段化ロジックは**行単位で完全に同一**であることを
  照合済み(`docs/pattern_spec_reversal_chart_patterns_recursive.md`)。
  `/3` との差分は **不明**。
- `LineWrapper` の `get_price` は最新版を書き起こしたもの。
  内容は2点を通る直線の内挿という自明な式で、`/2` との差分は **不明**だが
  変わりようがない。

なお `chartpatterns` は**指定どおり `/10` が最新版として公開されていた**ので、
検出本体については差分の問題は無い。

---

## 1. パラメータ

| 表示名 | 内部名 | 型 | 初期値 | 最小 | 最大 | step |
|---|---|---|---|---|---|---|
| Zigzag1 有効 | `useZigzag1` | bool | true | — | — | — |
| Zigzag1 期間 | `zigzagLength1` | int | **3** | 1 | — | 5 |
| Zigzag1 保持数 | `depth1` | int | **144** | — | 500 | 25 |
| Zigzag2 有効 | `useZigzag2` | bool | true | — | — | — |
| Zigzag2 期間 | `zigzagLength2` | int | **5** | 1 | — | 5 |
| Zigzag2 保持数 | `depth2` | int | **89** | — | 500 | 25 |
| Zigzag3 有効 | `useZigzag3` | bool | true | — | — | — |
| Zigzag3 期間 | `zigzagLength3` | int | **8** | 1 | — | 5 |
| Zigzag3 保持数 | `depth3` | int | **55** | — | 500 | 25 |
| Zigzag4 有効 | `useZigzag4` | bool | true | — | — | — |
| Zigzag4 期間 | `zigzagLength4` | int | **13** | 1 | — | 5 |
| Zigzag4 保持数 | `depth4` | int | **34** | — | 500 | 25 |
| Error Threshold | `errorThresold` | float | **20.0** | 0 | 100 | 5 |
| Flat Threshold | `flatThreshold` | float | **20.0** | 0 | 30 | 5 |
| Max Retracement | `flagRatio` | float | **0.618** | 0.1 | 1.0 | 0.05 |
| Verify Bar Ratio | `checkBarRatio` | bool | **false** | — | — | — |
| (同上) | `barRatioLimit` | float | 0.382 | — | — | — |
| Avoid Overlap | `avoidOverlap` | bool | **true** | — | — | — |
| Max Patterns | `maxPatterns` | int | **20** | 1 | — | 5 |

派生値:

```
errorRatio = errorThresold / 100      → 初期値 0.2
flatRatio  = flatThreshold / 100      → 初期値 0.2
```

参考元でコード内固定になっている値:

| 名前 | 値 |
|---|---|
| `offset` | 0 |
| `numberOfPivots` | **5**(6点版は使わない) |
| `allowedPatterns` | 後述(6.5) |
| `allowedLastPivotDirections` | 後述(6.5) |

### 1.1 検出に影響しないパラメータ

- `theme` / `patternLineWidth` / `showPatternLabel` / `showPivotLabels` /
  `showZigzag` / `deleteOldPatterns` … 描画のみ。
- `limitBars`(初期値5000)… 参考元が「直近N本だけ計算する」ための重さ対策。
  StrategyXでは全期間を計算するので採用しない(8.2)。
- **`repaint`(初期値 false)… 参考元では `ScanProperties` に渡されているが、
  実際に使われる `findPatternPlain` の中では一度も参照されていない。
  つまりこのスクリプトでは何の効果も無い。** よって StrategyX でも
  パラメータとして出さない。

### 1.2 検出に影響するが「表示用」に見えるパラメータ

`maxPatterns` は「チャートに残す本数」の設定に見えるが、実際には

- 土台パターンの保持数 = `maxPatterns * 2`(重複・重なり判定に使う)
- 成立したフラッグの保持数 = `maxPatterns`(重なり判定に使う)

として**検出結果そのものを変える**。よってパラメータとして残す。

---

## 2. パターンの構成点

```
強気フラッグ                            弱気フラッグ
        p2                                        p6
        /\    p4                          p1  /\  /
       /  \  /\    p6                      \  /\/
      /    \/  \  /                         \/  \  ...
     /     p3   \/                          p2   \
    /           p5                                p5
   /
  p1(旗竿の起点)                       p1(旗竿の起点)
```

- **p1** … 旗竿(flagpole)の起点。土台パターンより**古い**ZigZagピボット。
- **p2〜p6** … 土台パターンの5点。ZigZagの「新しい方から5点」。

出力の `point_bars` / `point_prices` は **`[p1, p2, p3, p4, p5, p6]` の古い順**。

土台パターンでは

- **トレンドライン1** = p2・p4・p6 を結ぶ線(最後のピボットと同じ側)
- **トレンドライン2** = p3・p5 を結ぶ線(反対側)

---

## 3. ZigZagピボットの生成方法(レベル0)

> **注**: 3章・4章は 0.3 のとおり `ZigzagLite/3` そのものではなく
> `ZigzagLite/4` の書き起こしである。差分は不明。

`docs/pattern_spec_motive_wave.md` の3章と**完全に同じ**なので要点のみ記す。

### 3.1 ピボット候補(lookback型・右側の確定を待たない)

```
pHigh / pHighBar = 直近 length 本の高値の最大とその位置(同値なら新しい方)
pLow  / pLowBar  = 直近 length 本の安値の最小とその位置(同値なら新しい方)
isHighPivot = (pHighBar == 現在バー)
isLowPivot  = (pLowBar  == 現在バー)
```

### 3.2 3つの分岐

① 同方向でより極端(`>=`)なら直近ピボットを置き換え。
② 反対方向のピボットなら新規追加。
  Pineの演算子優先順位により `pDir==1` 側にはガードが掛からず、
  ①と②が同じバーで両方走ることがある(= 1本のローソクに2つのピボット)。
③ 直近ピボットから `length` 本以上離れていて①②とも走らなければ強制追加。

### 3.3 ピボットに付く値

```
dir      = (符号 * 値 > 符号 * llastの値) ? 符号*2 : 符号
ratio    = round(|last価格 - 値| / |llast価格 - last価格|, 3)
barRatio = round(|lastバー - 値のバー| / |llastバー - lastバー|, 3)
```

`barRatio` は `checkBarRatio` が true のときだけ使う。
配列は `depth` 件を超えたら古い方から捨てる。

---

## 4. 多段(recursive)ZigZag

`docs/pattern_spec_reversal_chart_patterns_recursive.md` の4章と**完全に同じ**。

要点: レベル n の配列から古い順に見て、`|dir|==2` のピボットだけを昇格させ、
`|dir|==1` は保留に貯める。上位の件数が下位の件数以上になったら打ち切る。
上位のZigZagは長さも保持数も下位と同じ。

---

## 5. 判定タイミングと走査手順

### 5.1 直線の価格(LineWrapper の `get_price`)

```
get_price(line, bar) = y1 + (bar - x1) * (y2 - y1) / (x2 - x1)
```

### 5.2 走査ループ

4本のZigZagはそれぞれ独立に持つ。**どれか1本に新しいピボットが出たら**、
そのZigZagについてだけ以下を回す。

```
if zigzag.flags.newPivot:
    mlzigzag = zigzag                        # レベル0
    while mlzigzag.zigzagPivots.size() >= 6:
        lastBar = mlzigzag.zigzagPivots.first().point.index
        if lastDBar[このZigZag][level] < lastBar:   # まだ見ていない先頭バー
            lastDBar[このZigZag][level] = lastBar
            [valid, pattern] = findPatternPlain(...)      # 6章
            if valid:
                patterns へ追加(上限 maxPatterns*2、古い方から捨てる)
                [validFlag, fnp] = findFNP(pattern, ...)  # 7章
                overlap = avoidOverlap and validFlag ? 既存フラッグと重なるか : false
                if validFlag and not overlap:
                    fngPatterns へ追加(上限 maxPatterns)
                    → **検出**
        else:
            break                            # このレベルで進んでいないなら以降も見ない
        mlzigzag = mlzigzag.nextlevel()
```

- **6点以上**必要(5点使うが `>= 6` が条件)。
- `patterns` と `fngPatterns` は**4本のZigZag・全レベルで共有**する1つの配列。
- 既存フラッグとの重なり判定:

```
for fng in fngPatterns:
    start = fng の p2 のバー,  end = fng の p6 のバー
    if (現p2 >= start and 現p2 <= end) or (現p6 >= start and 現p6 <= end):
        重なりあり
```

---

## 6. 土台パターンの判定(`findPatternPlain`)

新しい順に `p6 = pivots[0]`, `p5 = pivots[1]`, `p4 = pivots[2]`,
`p3 = pivots[3]`, `p2 = pivots[4]`。並べ替えて `[p2, p3, p4, p5, p6]`。

### 6.0 既存パターンとの照合

```
for pattern in patterns:                       # 古い順、最大 maxPatterns*2
    startBar = pattern の p2 バー
    endBar   = pattern の p6 バー
    if 現p2バー > startBar and 現p2バー < endBar and avoidOverlap:
        無視して終了(break)
    先頭4点(p2,p3,p4,p5)のバーが全部一致するなら「既出」
既出 or 無視 なら不成立
```

### 6.1 3点の並びチェック(`isSame`)

`isSame(p2, p4, p6)` を要求する(5点版なのでこの1回だけ)。

```
r1 = (p4価格 - p2価格) / (p4バー - p2バー)      # 傾き
r2 = (p6価格 - p4価格) / (p6バー - p4バー)
rMax = max(r1, r2),  rMin = min(r1, r2)

ratioMax = max(p6.ratio, p4.ratio)
ratioMin = min(p6.ratio, p4.ratio)

条件A = rMin >= (1 - errorRatio) * rMax          # 傾きが揃っている
     or ratioMin >= (1 - errorRatio) * ratioMax  # または値幅比が揃っている

条件B = checkBarRatio ?
          (barRatioLimit <= p6.barRatio <= 1/barRatioLimit) and
          (barRatioLimit <= p4.barRatio <= 1/barRatioLimit)
        : true

isSame = 条件A かつ 条件B
```

**注意**: 条件Aの比較は傾きの符号込みで行う(負の傾きでもそのまま比較する)。
参考元がそうであるためそのまま踏襲する。

### 6.2 トレンドラインの検証(`inspect`)

区間は `firstIndex = p2バー` 〜 `lastIndex = p6バー`。

**1本の直線に対する検証**

```
valid = true, score = 0
for bar = firstIndex to lastIndex:
    barPrice    = direction > 0 ? 高値 : 安値
    barOutPrice = direction > 0 ? 安値 : 高値
    linePrice   = get_price(line, bar)

    if linePrice * direction < min(始値 * direction, 終値 * direction):
        valid = false; break                      # 実体を突き抜けた
    if barOutPrice*direction <= linePrice*direction <= barPrice*direction:
        score += 1                                # そのバーの値幅を通った
    else if bar == otherBar:
        valid = false; break                      # 使わなかった構成点に当たらない
```

**トレンドライン1(3点)** … p2・p4・p6 から3通りの引き方を試す。

| 候補 | 結ぶ2点 | otherBar |
|---|---|---|
| 1 | p2 — p6 | p4のバー |
| 2 | p2 — p4 | p6のバー |
| 3 | p4 — p6 | p2のバー |

```
採用 = valid1 and score1 > max(score2, score3) ? 候補1
     : valid2 and score2 > max(score1, score3) ? 候補2
     : 候補3
```

`direction` は `sign(p6.dir)`。

**トレンドライン2(2点)** … p3 — p5 を結ぶ1本のみ。`otherBar` は p3 のバー
(自分自身なので実質「p3のバーでラインが値幅を通ること」を要求する)。
`direction` は `sign(p5.dir)`。

両方 valid でなければ不成立。

### 6.3 端点の引き直しと構成点の載せ直し(`resolve`)

2本の線を、区間の両端 `firstIndex` / `lastIndex` まで延長・切り詰めて
端点を取り直す。

```
t1p1 = トレンドライン1 の firstIndex での価格
t1p2 = トレンドライン1 の lastIndex  での価格
t2p1 = トレンドライン2 の firstIndex での価格
t2p2 = トレンドライン2 の lastIndex  での価格
```

さらに構成点5つの価格を、対応する線の上の値に**置き換える**。

```
[p2, p3, p4, p5, p6] の i 番目 →  i が偶数ならトレンドライン1、奇数ならトレンドライン2
```

以降(7章の旗竿探索を含む)はこの**載せ直した価格**を使う。

### 6.4 13種類への分類(`resolvePatternName`)

```
if t1p1 > t2p1:
    upperAngle = (t1p2 - min(t2p1,t2p2)) / (t1p1 - min(t2p1,t2p2))
    lowerAngle = (t2p2 - max(t1p1,t1p2)) / (t2p1 - max(t1p1,t1p2))
else:
    upperAngle = (t2p2 - min(t1p1,t1p2)) / (t2p1 - min(t1p1,t1p2))
    lowerAngle = (t1p2 - max(t2p1,t2p2)) / (t1p1 - max(t2p1,t2p2))

upperLineDir = upperAngle > 1+flatRatio ?  1 : upperAngle < 1-flatRatio ? -1 : 0
lowerLineDir = lowerAngle > 1+flatRatio ? -1 : lowerAngle < 1-flatRatio ?  1 : 0

startDiff = |t1p1 - t2p1|,  endDiff = |t1p2 - t2p2|
barDiff   = lastIndex - firstIndex
priceDiff = |startDiff - endDiff| / barDiff
probableConvergingBars = min(startDiff, endDiff) / priceDiff

isExpanding   = endDiff > startDiff
isContracting = endDiff < startDiff
isChannel = probableConvergingBars > 2*barDiff
         or (not isExpanding and not isContracting)
         or (upperLineDir == 0 and lowerLineDir == 0)
invalid = sign(t1p1 - t2p1) != sign(t1p2 - t2p2)     # 2本が交差している
```

| 条件 | upper | lower | 種類 |
|---|---|---|---|
| invalid | — | — | **0**(該当なし) |
| isChannel | +1 | +1 | 1 上昇チャネル |
| isChannel | -1 | -1 | 2 下降チャネル |
| isChannel | それ以外 | | 3 レンジチャネル |
| isExpanding | +1 | +1 | 4 上昇ウェッジ(拡大) |
| isExpanding | -1 | -1 | 5 下降ウェッジ(拡大) |
| isExpanding | +1 | -1 | 6 拡大トライアングル |
| isExpanding | +1 | 0 | 7 上昇トライアングル(拡大) |
| isExpanding | 0 | -1 | 8 下降トライアングル(拡大) |
| isContracting | +1 | +1 | 9 上昇ウェッジ(収束) |
| isContracting | -1 | -1 | 10 下降ウェッジ(収束) |
| isContracting | -1 | +1 | 11 収束トライアングル |
| isContracting | 任意 | 0 | upper<0 なら 12 下降トライアングル(収束)、そうでなければ 1 |
| isContracting | 0 | 任意 | lower>0 なら 13 上昇トライアングル(収束)、そうでなければ 2 |
| どれにも当たらない | | | **0** |

### 6.5 許可フィルター

参考元は13種類のうち**7種類だけ**をフラッグ/ペナントの土台として許可する。
さらに種類ごとに「最後のピボットの向き」も指定する。

| 種類 | 許可 | 最後のピボットの向き |
|---|---|---|
| 1 上昇チャネル | ✅ | **-1**(安値で終わる) |
| 2 下降チャネル | ✅ | **+1**(高値で終わる) |
| 9 上昇ウェッジ(収束) | ✅ | **-1** |
| 10 下降ウェッジ(収束) | ✅ | **+1** |
| 11 収束トライアングル | ✅ | 0(どちらでも) |
| 12 下降トライアングル(収束) | ✅ | **+1** |
| 13 上昇トライアングル(収束) | ✅ | **-1** |
| 上記以外(0,3,4,5,6,7,8) | ❌ | — |

「最後のピボットの向き」= `sign(p6.dir)`。

---

## 7. 旗竿の判定(`findFNP`)

`dir` = **p6 の生の `dir`**(±1 だけでなく ±2 もあり得る)。

```
invalidationPrice = max(t1p1 * dir, t1p2 * dir)      # トレンドライン1の「進行方向側」の端
validationPrice   = min(t2p1 * dir, t2p2 * dir)      # トレンドライン2の「逆側」の端

prices = 土台5点の(載せ直した)価格を dir>0 なら降順、dir<0 なら昇順に並べたもの
priceIndex = 0
iinval = invalidationPrice
confirmed = false, valid = true, lastPoint = na
```

ZigZagの `index 5` 以降(= 土台より**古い**ピボット)を順に遡る。

```
for i = 5 to zigzagPivots.size()-1:
    pivot = zigzagPivots[i]

    if confirmed:
        if pivot価格*dir < lastPoint価格*dir:  lastPoint = pivot     # より深い方へ更新
        if pivot価格*dir >= iinval:            break                 # 竿の外に出た
        if pivot価格*dir <  iinval:            iinval = pivot価格*dir
    else:
        # 土台の価格帯を、pivotの位置まで1段ずつ降ろす
        for j = priceIndex to 4:
            if pivot価格*dir < prices[j]*dir:  priceIndex = j; iinval = prices[j]*dir
            else: break

        invalidationRatio = |abs(iinval) - pivot価格| / |invalidationPrice - iinval|
        if pivot価格*dir > iinval and invalidationRatio > 0.5:
            valid = false; break              # 竿の途中で半分以上戻している

        if pivot価格*dir < validationPrice:
            confirmed = true                  # 竿の起点を発見
            lastPoint = pivot
            continue
```

**参考元の癖(そのまま踏襲する)**

- `iinval` / `invalidationPrice` は `dir` を掛けた値なのに、
  `invalidationRatio` の分子では `abs(iinval)` としか戻していない。
  `|dir| == 2` のとき2倍のままになる。意図かどうかは**不明**。
- `invalidationRatio` の分母が0のとき参考元では `na` になり、
  比較が偽になる(= 無効化しない)。

### 7.1 旗竿の傾きチェック

```
midbar            = lastPoint.index + int((firstIndex - lastPoint.index) * flagRatio)
priceAtMidBar     = トレンドライン2 の midbar での価格(区間外への外挿)
flagPriceAtMidBar = (lastPoint価格 + p6の生の価格) / 2

flagConfirmed = (priceAtMidBar * dir >= flagPriceAtMidBar * dir)
```

`int()` は0方向への切り捨て。

### 7.2 成立条件

```
成立 = valid かつ confirmed かつ flagConfirmed
```

### 7.3 フラッグ/ペナントの種類

| 土台の種類 | フラッグ/ペナント |
|---|---|
| 2 下降チャネル / 10 下降ウェッジ(収束) | **強気フラッグ** |
| 1 上昇チャネル / 9 上昇ウェッジ(収束) | **弱気フラッグ** |
| 11 / 12 / 13 トライアングル系 | p6.dir > 0 なら **強気ペナント**、そうでなければ **弱気ペナント** |
| それ以外 | (発生しない) |

6.5 の許可フィルターにより、フラッグ側は土台の種類だけで向きが決まる。

---

## 8. 共通管理仕様とStrategyX独自拡張

### 8.1 Confirmed / Invalidated の水準【独自拡張の範囲を明記】

参考元はパターンを描画するだけで、成立後の追跡をしない。
一方 StrategyX では全チャートパターンに共通の状態モデルを適用するため、
**参考元が旗竿探索に使っている水準をそのまま流用する**(新しい価格を発明しない)。

```
シグナルの向き = sign(p6.dir)          # 強気フラッグ/ペナント = +1

ネックライン = invalidationPrice / dir  # トレンドライン1 の「進行方向側」の端
極値        = validationPrice   / dir  # トレンドライン2 の「逆側」の端

強気(+1): Confirmed   … 高値がネックラインを下から上へクロス
          Invalidated … 安値が極値を上から下へクロス
弱気(-1): Confirmed   … 安値がネックラインを上から下へクロス
          Invalidated … 高値が極値を下から上へクロス
```

- クロス判定は**ヒゲ**(High / Low)。終値は使わない。
- 同一バーで両方成立したら **Confirmed 優先**。
- 他のチャートパターン(トリプルトップ等)と完全に同じ扱い。

### 8.2 その他の独自拡張

| 項目 | 参考元 | StrategyX |
|---|---|---|
| 計算範囲 | 直近 `limitBars`(初期5000)本のみ | **全期間**(`limitBars` は採用しない) |
| `repaint` | `ScanProperties` にあるが未使用 | **パラメータとして出さない**(1.1) |
| 有効範囲の保証 | UIのmin/maxのみ | detector内部でもクリップする |

### 8.3 共通管理仕様(全detector共通)

**① pattern_id**

```
pattern_id = パターン種類 + "_" + p1のバー + "_" + p2 + ... + "_" + p6
例: bullish_flag_569_581_588_591_598_599
```

同じパターンが再び現れても**再登録しない**。

**重複判定は最新の構成点を除いて行う。** ZigZagの最新ピボットは右側の確定を待たずに
置き換えられる(=後から動く)ため、全構成点で同一性を見ると「同じ形なのに最新点の
位置だけ違う別パターン」が何度も登録されてしまう。
`pattern_id` として出力する値は全構成点を含んだままで、判定にだけこの規則を使う。
これは参考元の照合規則(6.0 の「先頭4点のバーが全部一致するなら既出」)と同じ考え方。

**② 1パターン1決着** … Candidate / Confirmed / Invalidated はそれぞれ1回だけ。

**③ 複数パターンの同時存在** … 未決着のものは何件でも保持し、同一バーで複数が
決着した場合もすべて個別に出力する。

**④ 状態管理** … CANDIDATE / CONFIRMED / INVALIDATED。
**EXPIRED は設けない**(参考元に期限条件が無いため)。

**⑤ 先読み・リペイント**

- `offset = 0`。当バーのOHLCまでしか見ない。**先読みは無い。**
- 3.1のとおりピボットは右側の確定を待たないため**リペイントし得る**。
  これは参考元の設計。
- `inspect` は区間 `firstIndex 〜 lastIndex` のローソクを読むが、
  `lastIndex` は p6 のバーであり現在バー以前。先読みではない。
- Candidate成立バーは走査が走ったバー(現在バー)。

### 8.4 容量上限

| 定数 | 値 | 内容 |
|---|---|---|
| `_FNP_MAX_LEVELS` | 32 | 走査する最大レベル数 |
| `_FNP_SLOT_CAPACITY` | 4096 | 同時監視する未決着パターンの上限 |

土台パターン配列(`maxPatterns*2`)とフラッグ配列(`maxPatterns`)は
参考元どおりの上限を使う(これらは検出結果を変えるため)。

### 8.5 計算量の目安

USDJPY 15分足 全期間(579,552本)・初期値で **約4.1秒**、検出 8,270 イベント。
参考元が `limitBars = 5000` で自衛しているのに対し、
StrategyX は全期間を一括で回せる。

---

## 9. 出力

### 9.1 イベント列(`events`)

| キー | 内容 |
|---|---|
| `pattern_id` | 8.3① |
| `pattern_type` | `bullish_flag` / `bearish_flag` / `bullish_pennant` / `bearish_pennant` |
| `base_pattern` | 土台の13種類の名前(6.4) |
| `zigzag_index` | どのZigZag(1〜4)で見つかったか |
| `level` | 多段ZigZagのレベル |
| `status` | `candidate` / `confirmed` / `invalidated` |
| `event_bar` | そのイベントが起きたバー位置 |
| `point_bars` | `[p1, p2, p3, p4, p5, p6]` のバー位置(古い順) |
| `point_prices` | 同じ順の価格(p2〜p6は6.3で載せ直した後の値) |
| `neckline_price` | 8.1 |
| `extreme_price` | 8.1 |

### 9.2 Boolean系列

パターン名 × 状態ごとの Boolean系列も返す。
同一バーに複数イベントが乗ると1つに潰れるため、
件数や構成点が要る用途では 9.1 を読むこと。
