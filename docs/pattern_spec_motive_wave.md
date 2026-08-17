# チャートパターン仕様書 — 推進波 / 収束ダイアゴナル / 拡大ダイアゴナル

バージョン: v1.0
作成日: 2026-08-12
作成方式: **B方式**(元コード → 言語化された仕様書 → StrategyX独自実装)

---

## 0. 参考元と依存追跡

### 0.1 参考元

| 項目 | 内容 |
|---|---|
| スクリプト名 | Motive Wave Scanner [Trendoscope®] |
| URL | https://www.tradingview.com/script/66eIIUfi-Motive-Wave-Scanner-Trendoscope/ |
| Pineバージョン | v6 |
| ライセンス | CC BY-NC-SA 4.0 / © Trendoscope Pty Ltd |
| 行数 | 55行(wrapperのみ。検出本体はライブラリ側) |

### 0.2 import追跡(ユーザー指示の手順1〜5)

wrapperのimport文:

```
import Trendoscope/Drawing/2  as dr
import Trendoscope/Zigzag/10  as zg
import Trendoscope/utils/2    as ut
import Trendoscope/Waves/3    as w
```

`Waves/3` のimport文:

```
import Trendoscope/Drawing/2   as dr
import Trendoscope/Zigzag/10   as zg
import Trendoscope/FibRatios/1 as fibs
import Trendoscope/utils/1     as ut
```

追跡結果:

| ライブラリ | 役割 | 取得 | 備考 |
|---|---|---|---|
| `Waves/3` | **検出本体**(`checkMotiveWave` / `scanMotiveWave`) | ✅ 全文 | 257行 |
| `utils/1` | **検出に使う**(`get_trend_series`) | ✅ 全文 | |
| `FibRatios/1` | **検出に使う**(`retracementRatio`) | ✅ 全文 | ABC仕様書で取得済み |
| `Zigzag/10` | ピボット生成 | ⚠️ **不明**(後述) | |
| `Drawing/2` | 線・ラベルの描画のみ | 不要 | 検出条件に無関係 |
| `utils/2` | 配色(`getColors`)のみ | 不要 | 検出条件に無関係 |

### 0.3 【不明】Zigzag/10 と公開版の差分

TradingViewは公開ライブラリの**最新版のソースしか表示しない**。
現在公開されているのは `Trendoscope/Zigzag`(Pine v6)であり、
参考元が指定している **`Zigzag/10` そのもののソースは取得できなかった**。

したがって本仕様書のZigZag部分(3章・4章)は
**「現在公開されている Zigzag の最新版」を書き起こしたもの**であり、
`Zigzag/10` との差分は **不明** である。

差分が無いと断定はできないが、以下の事実を記録しておく:

- 既に取得済みの `ZigzagLite/4` は、公開版 `Zigzag` から指標(indicator)対応を
  取り除いただけで、ピボット検出・ratio計算・多段化ロジックは**行単位で完全に同一**
  であることを照合済み(`docs/pattern_spec_reversal_chart_patterns_recursive.md` 参照)。
- よってこの系統のZigZagの中核は複数バージョンにまたがって安定していると
  推測されるが、**推測であり確認ではない**。

---

## 1. パラメータ

参考元 wrapper の `input` をそのまま踏襲する。

| 表示名 | 内部名 | 型 | 初期値 | 最小 | 最大 | step | 意味 |
|---|---|---|---|---|---|---|---|
| Length | `zigzagLength` | int | **5** | 3 | — | 5 | レベル0 ZigZagの長さ |
| Depth | `depth` | int | **200** | — | 500 | 25 | 保持するZigZagピボット数 |
| Level | `levelType` | string | **'Minimum'** | — | — | — | `'Minimum'` / `'Absolute'` |
| (同上) | `level` | int | **1** | 1 | — | 1 | 走査するZigZagレベル |
| Draw only first subwave | `limitSubwaves` | bool | true | — | — | — | **描画のみ。検出に無関係** |
| Repaint | `repaint` | bool | **true** | — | — | — | 5.1参照 |

参考元でコード内固定になっている値:

| 名前 | 値 | 意味 |
|---|---|---|
| `useRealTimeBars` | `true`(固定) | |
| `offset` | `useRealTimeBars ? 0 : 1` → **0** | ZigZagは当バーのHigh/Lowを使う |
| `allowedTypes` | `[ContractingDiagonal, ExpandingDiagonal, ImpulseWave]` | 3種すべて許可 |
| `limit`(`createWave`の引数) | 10 | 既存パターン照合に使う保持件数 |

`theme` は配色のみで検出に無関係。

### 1.1 パラメータ同士の依存関係

- `levelType == 'Minimum'` のとき、`level` **以上**の全レベルを走査する。
  `'Absolute'` のときは `level` に**一致するレベルだけ**を走査する。
- `level` の最小値が1なので、**レベル0(素のZigZag)は決して走査されない**。
  実際レベル0のピボットは `micropivots` が空なので走査しても何も出ない。
- `repaint` は走査タイミングと参照するピボットの位置の両方を変える(5.1)。

---

## 2. パターンの構成点

いずれのパターンも **6点 P0〜P5**(= 5つの波 W1〜W5)からなる。

```
上昇推進波(direction = +1)                下降推進波(direction = -1)
                       P5                  P0
                       /                    \
                 P4   /                      \   P1
                  \  /                        \  /\
             P3    \/                          \/  \    P3
              \    /                            \  /\   /\
          P2   \  /                              \/  \ /  \
           \   /\/                               P2   \/   \
            \ /                                       P4    \
            P1                                               P5
            /
          P0
```

- P0 → P1 → P2 → P3 → P4 → P5 の順に**時系列で新しくなる**。
- ピボットは**必ず高値・安値が交互**になる。
- 上昇推進波では P0,P2,P4 が安値、P1,P3,P5 が高値(下降では逆)。
- W1 = P0→P1、W2 = P1→P2、W3 = P2→P3、W4 = P3→P4、W5 = P4→P5。

パターン種類は3つ:

| コード | 名前 | 意味 |
|---|---|---|
| ImpulseWave | 推進波 | 標準的なエリオット5波 |
| ContractingDiagonal | 収束ダイアゴナル | 波幅が単調減少するウェッジ |
| ExpandingDiagonal | 拡大ダイアゴナル | 波幅が単調増加するウェッジ |

---

## 3. ZigZagピボットの生成方法(レベル0)

> **注**: 3章・4章は 0.3 のとおり `Zigzag/10` そのものではなく
> 公開版 Zigzag の書き起こしである。差分は不明。

### 3.1 ピボット候補の判定(lookback型)

各バー `i` で、**直近 `zigzagLength` 本**(自分を含む)の高値の最大・安値の最小を取る。

```
pHigh    = max(high[i-length+1 .. i])
pHighBar = その位置(同値なら最も新しい位置)
pLow     = min(low[i-length+1 .. i])
pLowBar  = その位置(同値なら最も新しい位置)

isHighPivot = (pHighBar == i)
isLowPivot  = (pLowBar  == i)
```

**右側の確定を待たない**。つまり「直近length本で最高値なら、その場で高値ピボット候補」。
このため後から取り消される(リペイントする)。

### 3.2 3つの分岐

配列 `zigzagPivots` は **index 0 が最新**。
`pDir` = 直近ピボットの方向の符号(まだ無ければ +1)。
`distance` = 現在バー − 直近ピボットのバー。`overflow = distance >= length`。

```
forceDoublePivot =
    pDir== 1 and isLowPivot  ? pLow  < zigzagPivots[1].price :
    pDir==-1 and isHighPivot ? pHigh > zigzagPivots[1].price : false
```

**① 置き換え(removeOld)**

```
if (pDir==1 and isHighPivot or pDir==-1 and isLowPivot) and size >= 1:
    value = (pDir==1 ? pHigh : pLow)
    if value * lastPivot.dir >= lastPivot.price * lastPivot.dir:
        直近ピボットを取り除き、(value, i, pDir) を積む
        newPivot = true
```

比較演算子は **`>=`**(同値でも置き換える)。

**② 新規追加**

```
if pDir==1 and isLowPivot  or  pDir==-1 and isHighPivot and (not newPivot or forceDoublePivot):
    value = (pDir==1 ? pLow : pHigh)
    (value, i, -pDir) を積む
    newPivot = true
```

Pineの演算子優先順位により `and` が `or` より強く結合するため、
**`pDir==1` 側には `(not newPivot or forceDoublePivot)` のガードが掛からない**。
意図か不具合かは**不明**だが、そのまま踏襲する。

この結果 ①と② が同じバーで両方走ることがあり、**1本のローソクの高値と安値に
2つのピボットが同時に立つ**(参考元の `flags.doublePivot`)。
よってパターンの構成点のバー位置は**同じ値が並ぶことがある**(厳密増加ではない)。

**③ 強制追加(overflow)**

```
if overflow and not newPivot:
    value    = (pDir==1 ? pLow    : pHigh)
    valueBar = (pDir==1 ? pLowBar : pHighBar)
    (value, valueBar, -pDir) を積む
    newPivot = true
```

### 3.3 ピボットに付く値

積むときに以下を計算する(`last` = 直前、`llast` = その1つ前)。

```
dir   = (dir_sign * value > dir_sign * llast.price) ? dir_sign * 2 : dir_sign
ratio = round(|last.price - value| / |llast.price - last.price|, 3)
```

- `|dir| == 2` … 前の同方向ピボットを更新した(HH または LL)
- `|dir| == 1` … 更新していない(LH または HL)
- 分母が0のとき参考元は `na` になる → NaN として扱う。
- 丸めは**0から遠い側**へ(`math.round`)。

配列は `depth` 件を超えたら古い方から捨てる。

---

## 4. 多段(recursive)ZigZagと micropivots

### 4.1 上位レベルの作り方(`nextlevel`)

レベル n の配列から**古い順**に見て、レベル n+1 を新規に組み立てる。
毎回ゼロから作り直すため、後述の `componentIndex` は常に最新である。

保留変数 `tempBullish` / `tempBearish` を持ちながら:

```
for i = size-1 downto 0:                # 古い順
    lPivot = copy(level_n[i])
    lPivot.level         = lPivot.level + 1
    lPivot.componentIndex = i           # ← レベルnの配列内位置を記録
    lPivot.micropivots   = 空配列
    nd  = sign(lPivot.dir)

    if 上位配列が空:
        |dir|==2 のときだけ積む
        continue

    if |dir| == 2:
        if 上位の直近と同方向:
            if より極端 (dir*lastValue < dir*value):
                上位の直近を取り除く
            else:
                反対側の保留があれば先に積む。無ければ**このピボットを捨てる**
        else:
            同方向の保留と反対方向の保留が**両方**あり、かつ
            同方向の保留の方がこのピボットより極端なら、2つまとめて先に積む
        lPivot を積む
        保留を両方クリア
    else:                               # |dir| == 1
        同方向の保留が無ければ lPivot を保留にする
        あれば、より極端な方を残す
```

最後に:

```
if 上位の件数 >= 下位の件数:
    上位を空にする        # これ以上細かくならない → 打ち切り
```

### 4.2 micropivots(`addnewpivot` 内)

上位レベルにピボットを積むとき、下位配列 `components` を使って
そのピボットが束ねている下位ピボット列を記録する。

```
pivot.subComponents = lastPivot.componentIndex - pivot.componentIndex
if components.size() > lastPivot.componentIndex:
    subPivots = components[pivot.componentIndex .. lastPivot.componentIndex]   # 両端含む
    for (index, subPivot) in subPivots:
        if index != subPivots.size()-1:                       # 最後の1つ以外
            if subPivot.micropivots が空:
                micropivots に subPivot を1つ追加
            else:
                micropivots に subPivot.micropivots を連結
        else if pivot.level == 1:                             # 最後の1つ
            micropivots に subPivot を追加
```

ここから読み取れること:

- `lastPivot` は**そのピボットを積む直前に上位配列の先頭にいたピボット**、
  つまり**1つ古い同レベルのピボット**である。
- **レベル1**の micropivots
  = レベル0の `[自分のcomponentIndex .. 1つ古い同レベルピボットのcomponentIndex]`(**両端含む**)。
  すなわち「上位の1波を構成するレベル0ピボット列」。**index 0 が最新**。
- **レベル2以上**の micropivots
  = 下位ピボット列のうち**最後の1つを除いた各要素の micropivots を順に連結**したもの。
  この連結では**隣り合う下位波の境界のピボットが重複する**
  (参考元のコメントアウトされたログがこの重複を検査している)。
  StrategyXでも**この重複をそのまま再現する**。
- レベル0のピボットの micropivots は常に空。

### 4.3 走査対象になるピボットの条件

`scanMotiveWave` の冒頭:

```
if pivot.dir % 2 == 0 and not na(pivot.micropivots)
   and not na(lastPivot.micropivots) and pivot.micropivots.size() >= 5:
```

- `dir % 2 == 0` … **|dir| == 2**(そのレベルで新高値/新安値を作ったピボット)のみ。
- micropivots が **5個以上**。

`lastPivot`(第2引数)は **`na` チェックにしか使われていない**
(価格を使う行はコメントアウトされている)。

---

## 5. 判定タイミングと走査手順

### 5.1 走査のトリガ

```
if zigzag.flags.newPivot and (repaint or not zigzag.flags.updateLastPivot):
```

- `newPivot` … そのバーでレベル0に新しいピボットが生まれた(3.2の①②③いずれか)。
- `updateLastPivot` … ①の置き換えが起きた。
- `repaint = true`(初期値)なら置き換えでも走査する。
  `false` なら**置き換えでない**新規ピボットのときだけ走査する。

### 5.2 レベルを登りながら走査

```
mlzigzag = zigzag                       # レベル0
while mlzigzag.size() >= (repaint ? 3 : 4):
    if (levelType=='Minimum' ? mlzigzag.level >= level : mlzigzag.level == level):
        lastPivot  = repaint ? mlzigzag[1] : mlzigzag[2]
        llastPivot = repaint ? mlzigzag[2] : mlzigzag[3]
        結果 = lastPivot.scanMotiveWave(llastPivot, 既存パターン, allowedTypes)
    mlzigzag = mlzigzag.nextlevel()
```

- 走査対象は **index 0(最新)ではなく index 1**(`repaint=false` なら index 2)。
  最新ピボットは形が確定していないため1つ前を見る、という設計。
- `mlzigzag[0]` は wrapper で変数に取られているが**使われていない**。
- `nextlevel()` が空を返したらループは終わる(4.1の打ち切り条件)。

### 5.3 既存パターンとの重複排除(参考元)

```
for existingWave in existingWaves:          # 最大10件
    if existingWave.pivot.point.index == pivot.point.index:
        existingPattern = true; break
if existingPattern: 何も返さない
```

さらに `createWave` 側で、線の終点(= micropivots の最後 = 波の起点)が
同じ既存パターンがあれば削除して差し替える。保持は**最大10件**。

→ StrategyXでは共通管理仕様①②(pattern_id + 1パターン1決着)に置き換える(7章)。

---

## 6. 6点の組み合わせ探索(`scanMotiveWave`)

対象ピボットの micropivots(**index 0 が最新**)の価格配列を `prices` とする。

```
direction = sign(pivot.dir)             # +1 = 上昇波, -1 = 下降波
trendSeries    = get_trend_series(prices, prices.size(), direction, direction)
pullbackSeries = get_trend_series(prices, prices.size(), -direction, direction)
p0 = pullbackSeries[0]
```

### 6.1 `get_trend_series`(utils/1)

```
startLength = 1
endLength   = min(size(pivots), length)
result      = []

if startLength < endLength:
    dir = (pivots[0] > pivots[1]) ? 1 : -1

    while startLength + (dir == highLow ? 1 : 0) < endLength:
        oTrend    = trend * highLow
        window    = pivots[startLength .. endLength-1]
        peak      = (highLow == 1) ? max(window) : min(window)
        peakIndex = (oTrend == 1) ? window内の最初の位置 : window内の最後の位置

        if oTrend == 1: result の**先頭**に (startLength + peakIndex) を挿入
        else:           result の**末尾**に (startLength + peakIndex) を追加

        if (oTrend == 1 ? startLength + peakIndex == endLength : peakIndex == 0):
            break

        if oTrend == 1: startLength = startLength + peakIndex + 1 + (dir > 0 ? 1 : 0)
        else:           endLength   = peakIndex
return result
```

**注意点(参考元のまま踏襲する)**

- `oTrend == 1` の枝では `result` の**先頭に挿入**するため、
  返る配列は「絶対indexの降順」= **古い順**になる。
- `oTrend != 1` の枝の `endLength = peakIndex` は、
  **window内の相対index**を**絶対的な上限**に代入している。
  window の起点 `startLength` を足していないため、実際には1つ余分に縮む。
  これが意図かどうかは**不明**だが、そのまま再現する。
- 本パターンでの呼び出しでは `direction = ±1` なので
  `oTrend = direction * direction = 1`(trendSeries)、
  `oTrend = direction * (-direction) = -1`(pullbackSeries)に固定される。

### 6.2 4重ループ

```
for p1Index = 0 .. (trendSeries.size() >= 2 ? trendSeries.size()-2 : ループしない):
    p1 = trendSeries[p1Index]
    if p0 > p1:
        for p2Index = 1 .. (pullbackSeries.size() >= 3 ? pullbackSeries.size()-2 : ループしない):
            p2 = pullbackSeries[p2Index]
            if p1 > p2:
                for p3Index = p1Index+1 .. trendSeries.size()-1:
                    p3 = trendSeries[p3Index]
                    if p2 > p3:
                        for p4Index = p2Index+1 .. pullbackSeries.size()-1:
                            p4 = pullbackSeries[p4Index]
                            p5 = 0
                            if p3 > p4 and p4 > p5:
                                → 6.3 の検査へ
```

`p0 > p1 > p2 > p3 > p4 > p5 = 0` はすべて **micropivots の配列index**の比較であり、
index が大きいほど古い。つまり **P0 が最も古く、P5 が最新**という並び順の要求。

### 6.3 各波の単調性チェック

各波の区間に、その両端を超える中間ピボットが**存在しないこと**を要求する。

```
w1Sub = prices[p1 .. p0]        # 両端含む
w2Sub = prices[p2 .. p1]
w3Sub = prices[p3 .. p2]
w4Sub = prices[p4 .. p3]
w5Sub = prices[p5 .. p4]

条件 = すべての k について
    max(wkSub) == max(端点2つ)  かつ  min(wkSub) == min(端点2つ)
```

比較は **`==`**(浮動小数の完全一致)。参考元がそうであるため踏襲する。

### 6.4 パターン分類(`checkMotiveWave`)

```
w1 = P1-P0,  w2 = P2-P1,  w3 = P3-P2,  w4 = P4-P3,  w5 = P5-P4
w1L..w5L = |w1|..|w5|

retracementRatio(a, b, c) = (b - c) / (b - a)          # FibRatios/1

w2Ratio = retracementRatio(P0, P1, P2) = (P1-P2)/(P1-P0)
w3Ratio = retracementRatio(P1, P2, P3) = (P2-P3)/(P2-P1)
w4Ratio = retracementRatio(P2, P3, P4) = (P3-P4)/(P3-P2)
w5Ratio = retracementRatio(P3, P4, P5) = (P4-P5)/(P4-P3)
mRatio  = retracementRatio(P0, P3, P4) = (P3-P4)/(P3-P0)

w3isNotShortest    = (w3L > w1L) or (w3L > w5L)
motiveRatiosIntact = (w2Ratio < 1) and (w3Ratio > 1) and (w4Ratio < 1)
                     and (w5Ratio > 0.9) and (mRatio < 1)
isMotiveWave       = w3isNotShortest and motiveRatiosIntact

direction = sign(P5 - P0)
w4NotBeyondEndofW1 = direction * P1 <  direction * P4
wave1OverlapsWave4 = direction * P1 >  direction * P4

numberofExtendedWaves = (1/w2Ratio > 2 ? 1:0) + (w3Ratio > 2 ? 1:0) + (w5Ratio > 2 ? 1:0)
notAllExtended        = numberofExtendedWaves < 3

wave4NotBeyondWave3 = (w4Ratio < 1)
isExpandingWaves    = w1L < w2L < w3L < w4L < w5L
isContractingWaves  = w1L > w2L > w3L > w4L > w5L

isImpulse            = w4NotBeyondEndofW1 and isMotiveWave and notAllExtended
isExpandingDiagonal  = isMotiveWave and wave1OverlapsWave4 and isExpandingWaves and wave4NotBeyondWave3
isContractingDiagonal= isMotiveWave and wave1OverlapsWave4 and isContractingWaves and wave4NotBeyondWave3

結果 = isImpulse             ? ImpulseWave
     : isContractingDiagonal ? ContractingDiagonal
     : isExpandingDiagonal   ? ExpandingDiagonal
     : なし
```

**優先順位は 推進波 → 収束ダイアゴナル → 拡大ダイアゴナル。**
`w4NotBeyondEndofW1` と `wave1OverlapsWave4` は排他(`<` と `>`)なので、
推進波とダイアゴナルが同時に成立することはない。等号のときはどちらでもない。

比較演算子はすべて**厳密不等号**(`<` `>`)。`w5Ratio > 0.9` の 0.9 は含まない。

### 6.4.1 比率は小数第3位に丸めてから比較する

`FibRatios/1` の `retracementRatio` は引数 `precision` の既定値が **3** で、
戻り値は `math.round(value, 3)` を通る。丸めは**0から遠い側**へ。
よって `w5Ratio > 0.9` 等の閾値比較は**丸めた後の値**で行われる。

例: 生の値が 0.9004 なら 0.900 に丸まって `> 0.9` を**満たさない**。
0.9006 なら 0.901 に丸まって満たす。

### 6.5 許可タイプでの絞り込み

```
if na(allowedTypes) or allowedTypes.includes(waveType):
    候補として採用
```

参考元は3種すべてを許可している。

### 6.6 【重要】ダイアゴナル2種は参考元では決して成立しない

6.4 を読み解くと、**収束ダイアゴナルも拡大ダイアゴナルも成立し得ない**ことが分かる。
理由は独立に2つある。

**理由① 比率の矛盾**

```
w2Ratio = (P1-P2)/(P1-P0) = w2の長さ / w1の長さ
w3Ratio = (P2-P3)/(P2-P1) = w3の長さ / w2の長さ
```
(上昇波でも下降波でも符号が打ち消し合うので、常に正の「長さの比」になる)

`isMotiveWave` は `w2Ratio < 1` かつ `w3Ratio > 1`、つまり
**「w2 < w1 かつ w3 > w2」**を要求する。一方

- 収束(`isContractingWaves`)は `w1 > w2 > w3 > w4 > w5` → `w3 < w2` が必要
- 拡大(`isExpandingWaves`)は `w1 < w2 < w3 < w4 < w5` → `w2 > w1` が必要

どちらも `isMotiveWave` と直接矛盾する。
ダイアゴナルは `isMotiveWave` を必須にしているので、両方とも常に偽。

**理由② 形の矛盾**

仮に理由①の2条件を外しても成立しない。

- `P0 = pullbackSeries[0]` は 6.1 より **micropivots 内の最安値(上昇波の場合)**。
  拡大が要求する `P2 < P0` は起こり得ない。
- `P5 = prices[0]` は走査対象のピボット自身で、そのレベルで新高値を作った点
  (4.3 の `|dir|==2`)なので **micropivots 内の最高値**。
  収束が要求する `P5 < P3` は起こり得ない。

**検証**

USDJPY 15分足 全期間(579,552本)で、ダイアゴナル側の比率条件を**すべて外した**
状態でも検出は**0件**だった(理由②の裏付け)。推進波は同条件で 44,327 件検出。

**StrategyXでの扱い**

- 分類ロジックは参考元どおり3種すべて実装してある(条件を緩める独自拡張はしない)。
- ただし**常に0件になる指標をUIや自動探索のプールに並べても害しか無い**ので、
  公開する指標は `impulse_wave_bullish` / `impulse_wave_bearish` の**2本だけ**とする。

---

## 7. 共通管理仕様(全detector共通)

### 7.1 ① pattern_id

```
pattern_id = パターン種類 + "_" + P0のバー + "_" + P1 + ... + "_" + P5
例: impulse_wave_bearish_120340_120388_120401_120455_120470_120512
```

同じパターンが再び現れても**再登録しない**。最初に現れたバーを Candidate 成立バーとする。

**重複判定は最新の構成点を除いて行う。** ZigZagの最新ピボットは右側の確定を待たずに
置き換えられる(=後から動く)ため、全構成点で同一性を見ると「同じ形なのに最新点の
位置だけ違う別パターン」が何度も登録されてしまう。実測ではUSDJPY15分足の
トリプルトップで検出された形の48%がこの重複だった。
`pattern_id` として出力する値は全構成点を含んだままで、判定にだけこの規則を使う。

参考元は「終点ピボットのバーが既存パターンと一致したら検出しない」という別の形の
規則を持つ(最大10件との照合)。StrategyXでは他のパターンと揃えて上の規則を使う
(**独自拡張**)。

### 7.2 ② 1パターン1決着

Candidate / Confirmed / Invalidated はそれぞれ**1回だけ**発生する。
確定または無効になった時点でそのパターンの監視を終了する。

### 7.3 ③ 複数パターンの同時存在

未決着のパターンは同時に何件でも保持する。
同一バーで複数が決着した場合も、すべて個別に保持・出力する。

### 7.4 ④ 状態管理

| 状態 | 意味 |
|---|---|
| CANDIDATE | 6.4 の分類が成立し、pattern_id が新規 |
| CONFIRMED | 8.1 のネックラインをヒゲでクロス |
| INVALIDATED | 8.1 のパターン極値をヒゲでクロス |

**EXPIRED(期限切れ)は設けない。**
参考元に期限条件が存在しないため、StrategyX側で勝手に追加しない。
未決着のパターンはデータ終端まで監視し続ける。

### 7.5 ⑤ 先読み・リペイント

- レベル0 ZigZagは `offset = 0`(**当バーのHigh/Lowを使う**)。
  未来のバーは一切参照しない。**先読みは無い。**
- ただし3.1のとおりピボットは右側の確定を待たないため、
  **確定後に取り消される(リペイントする)ことがある**。これは参考元の設計。
- `repaint = false` にすると、置き換え(`updateLastPivot`)が起きたバーでは走査せず、
  参照するピボットも1つ古い側にずらすため、リペイントの影響が小さくなる代わりに
  検出が遅れる。参考元の初期値は `true`。
- ③(overflow)で追加されるピボットのバー位置は
  **過去のバー(`pLowBar` / `pHighBar`)**になり得るが、価格はその時点で既知の値であり
  先読みではない。
- Candidate成立バーは**走査が走ったバー**(現在バー)であり、
  構成点のバー位置より新しい。Confirmed/Invalidatedの判定はそれ以降のバーのみを見る。

---

## 8. StrategyX独自拡張

以下は**参考元に無い**。参考元由来の仕様と明確に区別する。

### 8.1 Confirmed / Invalidated の水準

参考元はパターンを描画するだけで、エントリー・利確・損切りの水準を**一切定義していない**。
一方 StrategyX では全チャートパターンに共通の状態モデル
(Candidate → Confirmed / Invalidated)を適用する方針であるため、
**パターン自身の構成点だけを使って**以下のように定める(新しい価格を発明しない)。

```
waveDirection = sign(P5 - P0)           # +1 = 上昇推進波, -1 = 下降推進波
signalDirection = -waveDirection        # 推進波の完成は反転を示唆する

necklinePrice = P4 の価格                # 第5波の起点。ここを割ると波が終わったとみなす
extremePrice  = P5 の価格                # パターン極値。ここを超えると波が伸びている

上昇推進波(signalDirection = -1):
    Confirmed   … low  が necklinePrice を上から下へクロス
    Invalidated … high が extremePrice  を下から上へクロス

下降推進波(signalDirection = +1):
    Confirmed   … high が necklinePrice を下から上へクロス
    Invalidated … low  が extremePrice  を上から下へクロス
```

- クロス判定は**ヒゲ**(High / Low)で行う。終値は使わない。
- 同一バーで両方成立したら **Confirmed 優先**。
- これは他のチャートパターン(トリプルトップ等)と完全に同じ扱いである。

### 8.2 指標名と向き

指標名は**シグナルの向き**で付ける(他パターンと統一)。

| 指標名 | 波の向き | 意味 |
|---|---|---|
| `impulse_wave_bearish` | 上昇推進波 | 完成後の下落を示唆 |
| `impulse_wave_bullish` | 下降推進波 | 完成後の上昇を示唆 |

収束/拡大ダイアゴナルは 6.6 のとおり参考元では決して成立しないため、
指標としては公開しない。

### 8.3 有効範囲のエンジン側での保証

保存済みJSON経由などUIを介さない呼び出しがあり得るため、
1章の有効範囲(`zigzagLength >= 3`、`depth <= 500`、`level >= 1` 等)を
detector内部でクリップする。step(5 / 25)は**UI表示上の刻みであり、
エンジン側では強制しない**。

### 8.4 容量上限

参考元に上限が無い箇所で、実装上の固定長バッファを使う。
溢れたら**黙って取りこぼさず**、バッファを広げて計算し直すか例外にする。

| 定数 | 値 | 内容 |
|---|---|---|
| `_MW_MAX_LEVELS` | 32 | 走査する最大レベル数 |
| `_MW_MICRO_CAPACITY` | 1024 | 1つのピボットが束ねる micropivots の上限 |
| `_MW_SERIES_CAPACITY` | 256 | trendSeries / pullbackSeries の上限 |
| `_MW_SLOT_CAPACITY` | 4096 | 同時監視する未決着パターンの上限 |

### 8.5 計算量の目安

USDJPY 15分足 全期間(579,552本)での実測(初期値 `zigzagLength=5`, `level=1`,
`levelType='Minimum'`, `repaint=true`):

| `depth` | 所要時間 | イベント数 |
|---|---|---|
| 50 | 0.9秒 | 21,506 |
| 100 | 1.4秒 | 32,920 |
| **200(初期値)** | **4.2秒** | **44,327** |
| 500(上限) | 40秒 | 54,873 |

`depth` を上げると多段ZigZagの再構築と micropivots の展開が急に重くなる。
自動探索のプールでは 50 / 100 / 200 を候補にしてある。

---

## 9. 出力

### 9.1 イベント列(`events`)

検出した全イベントを1件1レコードで時系列順に並べる。

| キー | 内容 |
|---|---|
| `pattern_id` | 7.1 |
| `pattern_type` | 8.2 の指標名 |
| `status` | `candidate` / `confirmed` / `invalidated` |
| `event_bar` | そのイベントが起きたバー位置 |
| `level` | 検出したZigZagレベル |
| `point_bars` | `[P0, P1, P2, P3, P4, P5]` のバー位置(古い順) |
| `point_prices` | 同じ順の価格 |
| `neckline_price` | 8.1 |
| `extreme_price` | 8.1 |
| `ratios` | `[w2Ratio, w3Ratio, w4Ratio, w5Ratio, mRatio]` |

### 9.2 Boolean系列

StrategyXの条件式インターフェース用に、
パターン名 × 状態ごとの Boolean系列も返す。
**同一バーに複数イベントが乗ると1つに潰れる**ため、
件数や構成点が要る用途では 9.1 を読むこと。
