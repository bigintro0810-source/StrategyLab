# ABCDパターン(投影型)検出仕様書 v1.0

| 項目 | 内容 |
|---|---|
| 文書ID | SL-PAT-ABCD-001 |
| 版 | v1.0(2026-08-12) |
| 対象 | ABCD Bullish / ABCD Bearish |
| 方式 | B方式(参考元コードを移植せず、検出仕様を抽出して独自実装) |
| 参考元 | "ABCD Projection [Trendoscope®]" (Pine v6) |
| 参考元ライセンス | CC BY-NC-SA 4.0 |
| 参考元著作権表記 | © Trendoscope Pty Ltd, Trendoscope® |
| 実装先 | `engine/chart_patterns.py::_abcd_state` |

---

## 0. 依存追跡の記録

```
ABCD Projection [Trendoscope®]     ← 検出条件は wrapper 内に全部ある
├── Trendoscope/ZigzagLite/3       ★ZigZag本体
└── Trendoscope/arrays/2            配列ユーティリティのみ。検出に無関係(確認済み)
```

`findABCD` / `getD` / `evaluate` はいずれも wrapper 内で定義されており、
ライブラリ側に検出条件は無い。ZigZag部分だけが `ZigzagLite` にある。

**ZigzagLite について**: 取得できたのは v4。`Zigzag/11`(トリプル等で使用)から
指標対応を取り除いただけで、ピボット検出・`ratio` 計算・多段化は**完全に同一**
であることを行単位で照合済み。したがってZigZagの仕様は
`docs/pattern_spec_reversal_chart_patterns_recursive.md` の3章をそのまま参照する。

**確認できていない事項**(推測で実装しない):

| 項目 | 状態 |
|---|---|
| `ZigzagLite/3` の中身 | **不明**。TradingViewは最新版(v4)しか表示しない。v3→v4の差分は未確認 |
| `chart.point.now(close)` の `index` | Pine組み込み。現在バーの `bar_index` と解釈 |
| `ta.highestbars` の同値時の返り値 | **不明**。「最も新しい位置」と解釈(他パターンと同じ) |

---

## 1. パラメータ

| 内部名 | UI表示 | 型 | 初期値 | 最小 | 最大 | step | 意味 |
|---|---|---|---|---|---|---|---|
| `zigzag_length` | ZigZag期間 | int | 13 | 3 | 制限なし | 5 | Pivot候補のlookback長 |
| `min_abc_ratio` | ABC比率(下限) | float | 0.5 | 0.382 | 1.0 | 0.1 | C点のratioの下限 |
| `max_abc_ratio` | ABC比率(上限) | float | 1.0 | 0.382 | 1.0 | 0.1 | C点のratioの上限 |
| `avoid_overlap` | 重なりを避ける | bool | true | - | - | - | 直前パターンと重なる場合は検出しない |

**固定値(参考元でも定数)**:

| 項目 | 値 | 意味 |
|---|---|---|
| `depth` | 20 | 保持するPivot数 |
| `offset` | 1 | **確定足のみ使う**。ZigZagは1本前までのHigh/Lowで計算する |
| 投影の上限 | 500本 | D点が現在バー+500本より先なら不成立 |

**採用しなかったパラメータ**: `numberOfPatterns`(表示件数)、`showFibLevels`、
各種色 — いずれも描画専用で検出結果に影響しない。

**有効範囲の保証**: 上表の最小・最大は**検出器の内部でも保証する**(UI側の指定だけに
頼らない)。範囲外は境界値へ丸め、`min_abc_ratio > max_abc_ratio` なら入れ替える。
`step` はUI入力欄の増減単位としてのみ扱う。

---

## 2. 使用データ

| データ | 使用 | 用途 |
|---|---|---|
| High / Low | 必須 | Pivot候補、target/stop到達判定 |
| Close | 必須 | S点(エントリー価格)と成立条件の判定 |
| Volume / ATR | 不使用 | |

---

## 3. ZigZag

`docs/pattern_spec_reversal_chart_patterns_recursive.md` の3章と**完全に同じ**。
ただし本パターンでは:

- `offset = 1`。バー `i` の時点で、ZigZagは **バー `i-1` までのHigh/Low** を使い、
  Pivotのバー位置も `i-1` を基準に記録する
- **多段ZigZag(`nextlevel`)は使わない**。レベル0のみ

---

## 4. 構成点

Pivot配列は先頭(index 0)が最新。

| 記号 | 位置 | 意味 |
|---|---|---|
| C | index 1 | パターンの3点目 |
| B | index 2 | 2点目 |
| A | index 3 | 1点目(最も古い) |
| — | index 0 | 直近Pivot。成立条件の判定に使うが構成点ではない |
| S | 現在バー | `(index = 現在バー, price = 現在バーの終値)` |
| D | 投影点 | 下式で算出。Pivotではない |

---

## 5. D点の投影

```
bcdRatio = 1 / (index1のPivotのratio)

D価格 = C価格 + bcdRatio × (B価格 - C価格)

currentRatio = |C価格 - S価格| / |D価格 - C価格|
Dバー位置    = C.index + int((S.index - C.index) / currentRatio)
```

`int()` は**ゼロ方向への切り捨て**(Pineの `int()`)。

---

## 6. 成立条件

Pivot配列が **4件以上**、かつ **そのバーで新しいPivotが出た**ことが前提。

```
currentPriceRatio = (C価格 - S価格) / (C価格 - D価格)
lastPivotRatio    = (C価格 - index0のPivot価格) / (C価格 - D価格)

① 0.0 < currentPriceRatio < 0.382          ← 厳密不等号。0.382は含まない
② 0.0 < lastPivotRatio    < 0.382          ← 同上
③ Dバー位置 < 現在バー + 500
④ min_abc_ratio <= index1のPivotのratio <= max_abc_ratio    ← 両端を含む
⑤ 直前に登録したパターンと A/B/C のバー位置が全て一致しない
⑥ avoid_overlap が true のとき: 直前に登録したパターンの Dバー位置 < Aのバー位置
```

**注意**: ①②は分子・分母とも符号付きの引き算。絶対値ではない。

---

## 7. 方向とトレード水準(参考元に明示あり)

```
エントリー価格 = S価格 (= 検出バーの終値)
損切り価格     = A価格
利確価格       = D価格
方向           = sign(D価格 - A価格)      +1 = 強気 / -1 = 弱気
```

---

## 8. Confirmed / Invalidated

> 参考元は `evaluate` でこの追跡を**自前で行っている**。したがって他のパターンの
> ような独自拡張ではなく、参考元由来の仕様である。判定はヒゲ(High/Low)ベースで、
> 全チャートパターン共通の状態モデル(2026-08-12ユーザー決定)とも一致する。

Candidate成立の**次のバーから**毎バー評価する。期限は無い。

```
targetRef = 方向 > 0 ? High : Low
stopRef   = 方向 > 0 ? Low  : High

Confirmed   : targetRef × 方向 >= 利確価格 × 方向        ← 到達(タッチ)判定
Invalidated : stopRef   × 方向 <= 損切り価格 × 方向
```

同一バーで両方成立した場合、参考元の評価順に従い **Confirmed を優先**する。

1パターンにつき決着は1回だけ。決着後は監視を終了する。

---

## 9. StrategyX共通管理仕様の適用

### 9.1 pattern_id

```
pattern_id = パターン種類 + "_" + Cバー + "_" + Bバー + "_" + Aバー
例: abcd_bullish_140_120_100
```

D点は投影値でPivotではないため、構成点はA/B/Cの3点とする。これは参考元の
重複判定(A/B/Cのバー位置の一致を見る)と同じ粒度。

### 9.2 その他

- Candidate成立時点でA/B/C/D/エントリー/損切り/利確の全てを固定する
- 1パターン1決着(8章)
- 未決着のパターンを複数同時に監視する
- 状態は `CANDIDATE → CONFIRMED / INVALIDATED`。参考元に期限が無いので EXPIRED は使わない
- 先読みなし。`offset=1` によりZigZagは確定足のみを使う。ただし**S点は現在バーの
  終値**なので、Candidateはそのバーの終値が確定した時点で認識できる

---

## 10. 出力

### 10.1 イベント一覧(欠落のない出力)

| フィールド | 意味 |
|---|---|
| `pattern_id` | 9.1の一意ID |
| `pattern_type` | `abcd_bullish` / `abcd_bearish` |
| `status` | `candidate` / `confirmed` / `invalidated` |
| `event_bar` | イベントが発生したバー位置 |
| `a_bar` / `a_price` 〜 `c_bar` / `c_price` | 構成点 |
| `d_bar` / `d_price` | 投影したD点 |
| `entry_price` / `stop_price` / `target_price` | 7章の3水準 |
| `abc_ratio` | 判定に使ったC点のratio |

### 10.2 Boolean系列(互換用)

`candidate` / `confirmed` / `invalidated` の3系列。同一バーの複数イベントは1つに
潰れるため、件数や構成点が要る用途では10.1を読む。

---

## 11. 実装前チェックリスト

- [ ] `zigzag_length` 初期値13・min3・step5 を保持したか
- [ ] `min/max_abc_ratio` 初期値0.5/1.0・範囲0.382〜1.0・step0.1 を保持したか
- [ ] `depth = 20`、`offset = 1` を固定にしたか
- [ ] ZigZagが**1本前まで**のHigh/Lowを使う(offset=1)ようになっているか
- [ ] 多段ZigZagを**使っていない**か(このパターンは単一レベル)
- [ ] `bcdRatio = 1 / ratio` の逆数を忘れていないか
- [ ] Dバー位置の `int()` をゼロ方向切り捨てにしたか
- [ ] ①②の比率を**絶対値ではなく符号付き**で計算したか
- [ ] ①②を `<` `>` の**厳密不等号**で実装したか(0.382を含めない)
- [ ] ④のABC比率を**両端を含む** `<=` で実装したか
- [ ] ③の投影上限500本を入れたか
- [ ] ⑤⑥の判定対象を「**直前に登録した1件**」に限定したか(全件ではない)
- [ ] 新しいPivotが出たバーでのみ判定しているか
- [ ] 方向を `sign(D価格 - A価格)` で決めているか
- [ ] Confirmed/Invalidatedをヒゲ(High/Low)の**到達(タッチ)**で判定したか(クロスではない)
- [ ] 同一バー競合で Confirmed を優先したか
- [ ] 評価を Candidate成立の**次のバーから**始めているか
- [ ] pattern_id で重複登録を防ぎ、外部出力にも含めたか
- [ ] 1パターン1決着になっているか
- [ ] 複数パターンを同時に監視しているか
- [ ] 参考元に無いフィルター(ATR・期限・リテスト等)を追加していないか
