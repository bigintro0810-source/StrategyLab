# ABCパターン(多段ZigZag)検出仕様書 v1.0

| 項目 | 内容 |
|---|---|
| 文書ID | SL-PAT-ABC-001 |
| 版 | v1.0(2026-08-12) |
| 対象 | ABC Bullish / ABC Bearish |
| 方式 | B方式(参考元コードを移植せず、検出仕様を抽出して独自実装) |
| 参考元 | "ABC on Recursive Zigzag [Trendoscope]" (Pine v6) |
| 参考元ライセンス | CC BY-NC-SA 4.0 |
| 参考元著作権表記 | © Trendoscope Pty Ltd |
| 実装先 | `engine/chart_patterns.py::_abc_state` |

---

## 0. 依存追跡の記録

```
ABC on Recursive Zigzag [Trendoscope]   ← 検出条件は wrapper 内にある
├── Trendoscope/ZigzagLite/3   ★ZigZag本体(v4を取得。v3との差分は不明)
├── Trendoscope/FibRatios/1    ★水準計算(全文取得済み)
├── Trendoscope/Drawing/2       描画のみ。検出に無関係
└── Trendoscope/utils/1         色のみ。検出に無関係
```

### FibRatios/1 の全式(取得済み)

```
round(value, precision) = precision < 0 ? 最小刻みへ丸め : 小数precision桁へ丸め

retracement(a, b, ratio, logScale=false)  = logScale ? b × (a/b)^ratio : b - (b-a)×ratio
extension  (a, b, c, ratio, logScale=false) = logScale ? c × (b/a)^ratio : c + (b-a)×ratio
retracementRatio(a, b, c, logScale=false) = logScale ? log(c/b)/log(a/b) : (b-c)/(b-a)
extensionRatio (a,b,c,d, logScale=false)  = logScale ? log(d/c)/log(b/a) : (d-c)/(b-a)
```

**確認できていない事項**(推測で実装しない):

| 項目 | 状態 |
|---|---|
| `ZigzagLite/3` の中身 | **不明**。TradingViewは最新版(v4)しか表示しない |
| `round_to_mintick` の丸め | 銘柄の最小刻みに依存。検出器は刻みを知らないため**丸めを行わない**。水準の表示値がわずかに違いうるが、条件判定には影響しない |
| `ta.highestbars` の同値時の返り値 | **不明**。「最も新しい位置」と解釈 |

---

## 1. パラメータ

| 内部名 | UI表示 | 型 | 初期値 | 最小 | 最大 | step |
|---|---|---|---|---|---|---|
| `zigzag_length` | ZigZag期間 | int | 13 | 3 | 制限なし | 5 |
| `depth` | ZigZag保持数 | int | 200 | 制限なし | 500 | 25 |
| `min_zigzag_level` | 最小ZigZagレベル | int | 0 | 0 | 制限なし | 1 |
| `base` | 水準の基準 | str | `abc_extension` | — | — | — |
| `entry_ratio` | エントリー比率 | float | 0.3 | 0.1 | 制限なし | 0.1 |
| `target_ratio` | 利確比率 | float | 1.0 | 制限なし | 制限なし | — |
| `stop_ratio` | 損切り比率 | float | 0.0 | 制限なし | **0.0** | 0.1 |
| `log_scale` | 対数スケール | bool | false | — | — | — |
| `trade_condition` | 方向フィルター | str | `any` | — | — | — |
| `use_close_for_entry` | エントリー判定に終値を使う | bool | true | — | — | — |
| `use_close_for_target` | 利確判定に終値を使う | bool | true | — | — | — |
| `use_close_for_stop` | 損切り判定に終値を使う | bool | true | — | — | — |

`base`: `abc_extension`(=1) / `bc_retracement`(=2)
`trade_condition`: `any`(0) / `trend`(1) / `reverse`(2) / `contracting`(3) / `expanding`(4)

**採用しなかったパラメータ**: `useClosePricesForRetest` — 参考元では `retested` を
計算しているが**どこからも参照されない死んだコード**なので採用しない。表示専用の
色・テーマも同様。

**有効範囲の保証**: 上表の最小・最大は検出器の内部でも保証する。特に
`stop_ratio` は**0以下**(参考元が `maxval = 0.0`)。

---

## 2. ZigZag

`docs/pattern_spec_reversal_chart_patterns_recursive.md` の3章・4章と**完全に同じ**
(ZigzagLite は Zigzag/11 から指標対応を除いただけで同一。行単位で照合済み)。

- `offset = 0`(リアルタイム足を使う)
- **多段ZigZag(`nextlevel`)を使う**

---

## 3. 走査

**レベル0で新しいPivotが出たバー**でのみ走査する。レベル0から始め、そのレベルの
Pivot数が **3以上** の間、`min_zigzag_level` 以上のレベルについて判定し、
`nextlevel()` で上位へ進む。

判定自体は Pivot が **4件以上** ある場合のみ行う。

---

## 4. 構成点

Pivot配列は先頭(index 0)が最新。

| 記号 | 位置 |
|---|---|
| C | index 0(最新) |
| B | index 1 |
| A | index 2 |

> **注意**: ABCDパターン(別仕様書)とは添字の割り当てが**1つずれている**。
> あちらは C=index1 だが、こちらは C=index0。混同しないこと。

---

## 5. 成立条件

```
① 0.618 <= C.ratio <= 0.786                      ← 両端を含む

② 方向フィルター(|A.dir| と |B.dir| は 1 か 2)
   any        : 条件なし
   trend      : |A.dir| == 1 かつ |B.dir| == 2
   reverse    : |A.dir| == 2 かつ |B.dir| == 1
   contracting: |A.dir| == 1 かつ |B.dir| == 1
   expanding  : |A.dir| == 2 かつ |B.dir| == 2

③ エントリー未達(withinEntry)
   方向 = B価格 > C価格 ? +1 : -1
   終値 × 方向 < エントリー価格 × 方向

④ 既に登録済みのパターンと重複しない(9.1参照)
```

**方向**: `B価格 > C価格` なら **+1(強気)**、そうでなければ **-1(弱気)**。

---

## 6. トレード水準(参考元に明示あり)

`base` の値で計算式が変わる。`X` は `entry_ratio` / `target_ratio` / `stop_ratio`。

```
base = abc_extension のとき:
    水準 = extension(A価格, B価格, C価格, X, log_scale)
         = 非対数: C価格 + (B価格 - A価格) × X
         = 対数  : C価格 × (B価格 / A価格)^X

base = bc_retracement のとき:
    水準 = retracement(B価格, C価格, X, log_scale)
         = 非対数: C価格 - (C価格 - B価格) × X
         = 対数  : C価格 × (B価格 / C価格)^X
```

初期値(`abc_extension`、entry 0.3 / target 1.0 / stop 0.0)なら:

```
エントリー = C + (B - A) × 0.3
利確       = C + (B - A) × 1.0
損切り     = C + (B - A) × 0.0 = C価格
```

---

## 7. Confirmed / Invalidated

> 参考元は `traverse` でこの追跡を**自前で行っている**。独自拡張ではない。
> 終値で判定するかヒゲで判定するかは参考元のパラメータで切り替えられ、
> **初期値は終値**である。

内部状態は3段階(参考元の `status`)。

```
0 = エントリー未到達
1 = エントリー到達
2 = 利確到達
```

Candidate成立の**次のバーから**毎バー評価する。期限は無い。

```
基準値(方向 dir、初期値はいずれも終値):
    利確基準     = use_close_for_target ? 終値 : (dir>0 ? 高値 : 安値)
    エントリー基準 = use_close_for_entry  ? 終値 : (dir>0 ? 高値 : 安値)
    損切り基準   = use_close_for_stop   ? 終値 : (dir>0 ? 安値 : 高値)

新状態 = 利確基準×dir >= 利確×dir       ? 2
       : エントリー基準×dir >= エントリー×dir ? 1
       : 現状態
新状態 = max(現状態, 新状態)             ← 後戻りしない

決着 = (新状態 > 0 かつ 損切り基準×dir <= 損切り×dir)
    または (新状態 == 0 かつ 終値×dir <= 損切り×dir)
```

**StrategyXの状態への対応**:

| 参考元の終了状態 | StrategyX |
|---|---|
| 状態2に到達(利確) | **Confirmed** |
| 状態0のまま損切り(Invalid) | **Invalidated** |
| 状態1から損切り(Stopped) | **Invalidated** |

1パターンにつき決着は1回だけ。決着後は監視を終了する。

> **参考元との差異(報告タイミング)**: 参考元は利確到達の**次のバー**でパターンを
> 配列から取り除いて集計する(`closed` の判定に古い状態を使うため1本遅れる)。
> StrategyXでは**利確に到達したそのバー**でConfirmedを出す。状態遷移そのものは
> 同一で、遅れは参考元の後片付け処理の副作用にすぎないため。

---

## 8. StrategyX共通管理仕様の適用

### 8.1 pattern_id と重複判定

```
pattern_id = パターン種類 + "_" + Cバー + "_" + Bバー + "_" + Aバー
例: abc_bullish_140_120_100
```

> **参考元との差異(意図的)**: 参考元は「監視中のパターンと **A価格・B価格が
> 一致するか**」で重複を判定し、さらに一致した場合に条件次第で**既存パターンの
> C点を新しいものへ書き換える**(`p.update(c)`)。StrategyXでは共通管理仕様に
> 従い、① 重複判定はバー位置ベースの `pattern_id` で行い、② **Candidate成立後の
> 構成点は固定して書き換えない**。価格の一致は偶然起こりうるうえ、構成点の
> 書き換えはリペイントにあたるため。

### 8.2 その他

- 1パターン1決着(7章)
- 未決着のパターンを複数同時に監視する(レベル違いを含む)
- 状態は `CANDIDATE → CONFIRMED / INVALIDATED`。期限が無いので EXPIRED は使わない
- 先読みなし。ただしZigZagの最新Pivotは後から動きうる(RRCPと同じ性質)

---

## 9. 出力

### 9.1 イベント一覧

| フィールド | 意味 |
|---|---|
| `pattern_id` / `pattern_type` / `status` / `event_bar` | 共通 |
| `level` | 検出されたZigZagレベル |
| `a_bar` / `a_price` 〜 `c_bar` / `c_price` | 構成点 |
| `entry_price` / `stop_price` / `target_price` | 6章の3水準 |
| `bc_ratio` | 判定に使ったC点のratio |

### 9.2 Boolean系列(互換用)

同一バーの複数イベントは1つに潰れる。件数や構成点が要る用途では9.1を読む。

---

## 10. 実装前チェックリスト

- [ ] `zigzag_length` 13/min3/step5、`depth` 200/max500/step25 を保持したか
- [ ] `entry_ratio` 0.3/min0.1、`target_ratio` 1.0、`stop_ratio` 0.0/**max0.0** を保持したか
- [ ] 有効範囲を検出器内部でも保証したか(特に `stop_ratio <= 0`)
- [ ] 多段ZigZagを使い、走査条件を「Pivot数 >= 3」、判定条件を「Pivot数 >= 4」にしたか
- [ ] **C=index0 / B=index1 / A=index2** にしたか(ABCDとは添字が違う)
- [ ] ①のratio範囲 0.618〜0.786 を**両端を含む**で実装したか
- [ ] ②の方向フィルター4種を `|dir|` の 1/2 で判定したか
- [ ] ③の `withinEntry`(終値がエントリーに未到達)を成立条件に入れたか
- [ ] 方向を `B価格 > C価格` で決めたか
- [ ] `extension` / `retracement` の式を対数版も含めて正しく実装したか
- [ ] `extension` の引数順が (A, B, C, ratio)、`retracement` が (B, C, ratio) になっているか
- [ ] 状態0/1/2の遷移と `max(現状態, 新状態)` を再現したか
- [ ] 決着条件の2つの分岐(状態>0なら損切り基準、状態0なら終値)を再現したか
- [ ] 終値/ヒゲの切り替えを参考元の初期値(**すべて終値**)で実装したか
- [ ] 死んだコード(`retested` / `increment`)を実装に持ち込んでいないか
- [ ] pattern_id で重複登録を防ぎ、構成点を書き換えていないか
- [ ] 1パターン1決着になっているか
- [ ] 複数パターンを同時に監視しているか
- [ ] 参考元に無いフィルターを追加していないか
