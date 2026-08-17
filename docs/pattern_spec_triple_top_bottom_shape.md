# 形状判定版トリプルトップ/ボトム 仕様書

対象関数(想定): `triple_top_shape` / `triple_bottom_shape`
→ ラッパー `_triple_top_bottom_shape_state`
→ njitコア `_shape_state_core3`

土台: 形状判定版ダブルトップ/ボトムST(`engine/chart_patterns.py::_shape_state_core` L471–940、ヘルパー L338–446、ラッパー L942–1143、共通ID L1311–1337)。

本文は `bullish=False`(トリプルトップ=山を探す)で記述する。`bullish=True`(トリプルボトム=谷を探す)は上下・大小をすべて反転した鏡像であり、以降「山」「高い」「割る(下抜け)」は反転読み替えとする。

> **重要**: 本仕様は「設計書」と「査読」を突き合わせた確定版である。設計と査読が対立した箇所は**すべて査読を採用**した。どちらを採ったかは各節で明記する(§1.3 に一覧)。

---

## 0. この文書について

### 0.1 位置づけ
- 本パターンは**形状判定版ダブルトップST(`_shape_state_core`)を土台に、2山→3山・1ネック→2ネックへ拡張した「形状判定版」トリプル**である。
- 既存の `triple_top` / `triple_bottom`(**多段ZigZag=RRCP方式**)とは**別物**。RRCP版はZigZagの折れ点列からトリプルを抽出する方式で、内部ロジックも状態管理も本仕様とは無関係。名前が似ているだけの独立実装として扱う。
- 状態は StrategyX 標準の**3種**: Candidate → Confirmed → Invalidated。1パターン1決着、複数パターン同時保持、pattern_id、先読み禁止、リペイント管理をすべて土台STから踏襲する。

### 0.2 なぜ「山3=ダブルの山2」なのか(設計の根幹)
構成点は **山1 → ネック1(谷1) → 山2 → ネック2(谷2) → 山3 の5点**。この5点をどう確定するかで、ピボット判定方式が決まる。

| ダブル | トリプル | ピボット判定 | 確定遅延 |
|---|---|---|---|
| 山1 | 山1 | 両側確認 `ext_flags` | +lag |
| ネック | ネック1 | 両側確認 `neck_flags` | +lag |
| (なし) | **山2(中間の山)** | **両側確認 `ext_flags`** | +lag |
| (なし) | ネック2 | 両側確認 `neck_flags` | +lag |
| **山2(終端)** | **山3(終端)** | **左側のみ `ext_flags_top3`** | +0 |

- ダブルの山2は「ブレイクへ直結する**終端点**」なので左側のみ確定(遅延ゼロ、本当に頂点だったかは決着走査の `fail_j` が担保)。トリプルでその役を演じるのは**山3**。
- 山2は前後に完全な区間(ネック1→山2→ネック2)を持つ**中間点**。中間点を左側のみで確定すると「上がり続けている間ずっとTrue」になり頂点位置がズレる(`_detect_pivot_highs_left_only` のdocstring L93–102 の警告)。よって**山2は両側確認 `ext_flags`** を使う。
- この対応により、トリプルは「ダブルの (山1→ネック→終端) の途中に (→中間の山2→ネック2→) を1段挿し込んだもの」に構造分解でき、土台ロジックをほぼ丸ごと再利用できる。

---

## 1. 構成点と全体像

### 1.1 構成点(5点)
```
      山1        山2        山3
      /\        /\        /\
     /  \      /  \      /  \
    /    \    /    \    /    \
   /      \__/      \__/      \____ ← ブレイク
          ネック1    ネック2
```
- **山1 / 山2 / 山3**: 3山**全体の最高値-最安値が許容誤差tol以内**に収まる(§2.2 の設計判断2、2026-08-14訂正 — 特定の1点を基準にすると、基準にしなかった2点同士が最大2×tolまでズレて良いことになる抜け道があったため、3点まとめての値幅判定に変更)。
- **ネック1 / ネック2**: 2つの谷。互いに近接していることを要求(新パラメータ `neck_tolerance_mult`、§2.2 設計判断3a)。
- 4間隔 i1(山1→ネック1)・i2(ネック1→山2)・i3(山2→ネック2)・i4(ネック2→山3)がジオメトリを決める。

### 1.2 確定に使うネックライン水準(最重要の設計判断)
**確定・失敗判定に使うネックライン水準 = `min(ネック1_price, ネック2_price)`(bullishは `max`)。その水準を持つ谷のバーを `neck_ref_bar` とする。**

3案を検討し `min/max` を採用:
1. ~~ネック2のみ~~ → ネック1を無視。ネック2が浅いと早すぎ確定。**却下**。
2. ~~2谷を結ぶ直線~~ → 水準がバーごと可変になり、余白・interval0・時間対称・既存ブレイク走査(スカラー水準前提)をすべて作り直しになる。**却下**。
3. **min/max(採用)**。

採用の根拠3点:
- **早すぎ確定の排除**: 浅い方の谷だけ割っても構造は生きている。深い方(悲観側)を割って初めて多谷サポートが決定的に崩れる。
- **既存走査を丸ごと再利用**: 単一スカラー水準+余白なので `confirm_j/fail_j`(土台 L822–835)を1文字も変えず流用できる。
- **house rule「悲観側優先」と整合**(SL/TP同時ヒットや Confirmed/Failed 同着で悪い方を採る既存方針)。

> **【査読採用・重大】左側ジオメトリには min/max を持ち込まない。**
> `neck_ref = min(ネック1,ネック2)` が **ネック2** になった場合、事前undercut窓 `pre_bar→neck_ref` が**山2を内包**する。3山はほぼ同高なので山2 > 山1 が普通に起き、走行max が山1を超えて**まともなトリプルがほぼ全部落ちる**。
> → **左側ジオメトリ(pre_bar探索・interval0・事前undercut)は常に `neck1` を軸に固定**する。`min(neck1,neck2)` は**ブレイク判定(confirm_j/fail_j)専用**に隔離する。設計書の「事前undercutを neck_ref へ一般化」は**破棄**(査読 §1 を採用)。

### 1.3 設計 vs 査読 — 採否一覧(A〜Fは査読採用、G以降はユーザー訂正)
| # | 論点 | 設計書 | 確定 |
|---|---|---|---|
| A | 左側ジオメトリの軸 | neck_ref(min)へ一般化 | **neck1固定**。minはブレイク判定専用 |
| B | 中間の山2の選び方 | ループで総当り(完全性優先) | **単一正準点に確定**(dedup濫立・perf・一貫性) |
| C | `symmetry_ratio_max`/`max_bars_between_tops` 初期値 | 0=無制限を維持 | **symmetry_ratio_maxのみ有限化**(perf論拠)。`max_bars_between_tops`は査読Bの単一正準点化で計算量の主因が既に解消済みと実測確認できたため、**0=無制限に差し戻し**(2026-08-14、ユーザー指摘・実測: USDJPY/XAUUSD全期間とも1500上限と無制限で所要時間・検出数とも差なし) |
| D | `neck_tolerance_mult` 初期値 | 0=無制限から開始 | **有限の緩め値0.5**、0=無制限禁止 |
| E | 中央山(山2)の孤立度チェック | 5点すべてに適用 | **v1では山2の孤立度を外す**(稀少化対策) |
| F | 昇降型(傾いたネック) | 言及なし | **非対応と明記**(0件の誤読防止) |
| G | 単一正準点(B)の**選び方**そのもの | 「山1に最も近い」(`\|price−山1\|` 最小) | **「tol以内で最高値」に訂正**(2026-08-13、ユーザー指摘: 「山の周囲に山よりも高値が来ないように」— 最も近い基準だと、選ばれなかった側により高い山が取り残される) |
| H | 時間0/時間1対称性の基準点 | neck_ref基準(§4) | **山2(パターンの中心)基準**に確定(2026-08-14。実装時に一度「山3(終端点)基準」にしたが、これはダブル側の変更をトリプルへ機械的に当てはめた誤解によるもので撤回。ダブルはネックが中心なので変更なし、トリプルは山2が中心という指示が正しい理解だった) |
| I | 山1・山2・山3の水準許容誤差の判定方式 | 「全山を山1アンカー」(設計判断2、§2.2) | **「3点全体の最高値-最安値がtol以内」に訂正**(2026-08-14、ユーザー指摘: 「1点基準だと基準にしなかった2点同士は最大2倍までズレて良いことになる」— 数値検証で確認、旧版(削除済み)・一般的なトリプルトップの定義とも一致するためこちらを採用) |

---

## 2. パラメータ一覧

### 2.1 方針
- **新設は `neck_tolerance_mult` の1個のみ。** 既存37個のうち36個を値・意味とも不変で流用し、`min_bars_between_tops` は既存同様 `pivot_right_bars` に内部固定する。
- ただし査読の perf・稀少化の指摘により、**トリプル専用の推奨初期値**を一部変更する(パラメータ自体は増やさない)。

### 2.2 意味を各区間へ複製適用するもの(パラメータは増えない)

**設計判断2 — 3山の水準許容は3点全体の値幅で判定(2026-08-14訂正)**
```
tol = ∞ (top_tolerance_mult ≤ 0)
    | |山1 − ネック1| × top_tolerance_mult      (top_tolerance_basis == "price_pct")
    | ATR[bar] × top_tolerance_atr_mult          (== "atr")
require: max(山1, 山2, 山3) − min(山1, 山2, 山3) ≤ tol
```
当初は「全山を山1にアンカー(`|山2−山1|≤tol AND |山3−山1|≤tol`)」だったが、これだと基準にしなかった2点(山2と山3)同士は最大2×tolまでズレて良いことになる抜け道があった(ユーザー指摘、数値検証で確認)。3点まとめての値幅判定ならこの抜け道が無く、隣接ペアだけで見た場合の「山1>山2>山3と少しずつ下がる下降階段」(ドリフト)も引き続き封じられる。旧版(削除済み、コミット`1cc1e54`)・一般的なトリプルトップの定義とも一致する方式。

実装上は、山2の時点では2点しかないので「範囲≤tol」と「`\|山2−山1\|≤tol`」は等価(変更不要)。山3を探す段階で初めて3点になるため、`lo12=min(山1,山2)`・`hi12=max(山1,山2)`(山2確定時点で1回計算)と候補ごとの範囲拡張だけで済む。窓の破綻判定(breach)は方向性のある片側境界`worst12`(bullishならlo12、そうでなければhi12)を使う。price_pctの基準幅は最初に確定する脚 `|山1−ネック1|`(山2・山3探索時に既知)を全山共有。

**設計判断3a — 2ネック近接(新パラメータ `neck_tolerance_mult`)**
```
neck_tol = |山1 − ネック1| × neck_tolerance_mult   (top_tolerance_basis=="price_pct")
         | ATR[ネック2_bar] × top_tolerance_atr_mult (=="atr")
require: |ネック1_price − ネック2_price| ≤ neck_tol
```
古典的トリプルは2谷を通るほぼ水平なネックラインが定義そのもの。谷水準が大きくズレる形は階段でありトリプルではない。basis/ATR companion は `top_tolerance_*` を流用し、新規は倍率1個に抑える。

2026-08-15訂正: 当初`neck_tolerance_mult ≤ 0`を「無制限(∞)」として扱う特別処理があり、UI上は0の入力自体を禁止することでこれを回避していたが、コード自体は0を渡せば無制限になってしまう(ドキュメントの「0=無制限は禁止」という記述と実装が矛盾していた)不具合だった。H&S側の同じ処理を訂正した際(2026-08-15、ユーザー判断)にこちらも合わせて訂正し、`neck_tolerance_mult`は他の`*_mult`パラメータが持つ「0以下=np.inf(無制限)」という共通規約を適用しない専用扱いとした - **0はリテラルに「完全な同水準」を意味する許容誤差そのものであり、無制限にする手段自体を提供しない。**

**設計判断4 — 谷深さは2谷を独立判定(平均でない)**
```
depth1 = |mean(山1,山2) − ネック1_price|     # 谷1
depth2 = |mean(山2,山3) − ネック2_price|     # 谷2
depth_min = ATR[neck_bar] × min_valley_depth_atr_mult
depth_max = ∞ (max_valley_depth_atr_mult ≤ 0) else ATR[neck_bar] × max_valley_depth_atr_mult
require: depth_min ≤ depth1 ≤ depth_max  AND  depth_min ≤ depth2 ≤ depth_max
```
平均にすると「深い谷1+極浅の谷2」=「ダブル+こぶ」が通る。両谷独立に要求。ATRは各谷の `neck_bar` 局所値。ブレイク余白計算に使う `depth` は **neck_ref側(min側)の谷深さ** を使う。

**その他の複製適用**:
- `top_tolerance_*` … 山2・山3を**山1基準**で共有。
- `symmetry_ratio_min/max` … 山2窓・山3窓の各終端窓に適用(§3④)。
- eff・dev 無印 … 核心4脚に適用(§3⑨⑩)。
- `_shape_spike_ok`(孤立度) … v1では**山1・ネック1・ネック2・山3の4点に適用、山2は外す**(査読E)。

### 2.3 パラメータ表(最終初期値、2026-08-14確定)

初稿(査読反映直後)の推奨値からユーザーがUI上で実データを見ながら調整し、その結果を最終デフォルトとして採用した。実装当初の中間値(査読直後の推奨値)は取り消し線で残す。

| 分類 | パラメータ | 既定(ダブル) | **トリプル最終初期値** | 備考 |
|---|---|---|---|---|
| そのまま | state | confirmed | confirmed | |
| **調整** | pivot_left_bars / pivot_right_bars | 5 / 5 | **3 / 3** | ユーザー調整(2026-08-14)。`min_bars_between_tops` は内部で `pivot_right_bars` に固定 |
| そのまま | prominence_atr_mult | 0.0 | 0.0 | |
| そのまま | pivot_spike_excess_atr_max | 1.3 | 1.3 | 山2には適用しない(査読E) |
| そのまま | pivot_spike_window_ratio | 0.5 | 0.5 | 同上 |
| そのまま | max_bars_between_tops | 0(無制限) | **0(無制限)** | ~~査読C時点で1500(有限)に変更~~ → 山2単一正準点化で計算量は既に解消済みと実測確認できたため0(無制限)へ差し戻し(2026-08-14) |
| そのまま | symmetry_ratio_min | 0.0 | 0.0 | |
| そのまま | symmetry_ratio_max | 3.33 | **3.33** | ~~査読C時点で2.5(有限)に変更~~ → ユーザー調整により3.33(ダブルと同じ既定)へ差し戻し(2026-08-14) |
| そのまま | top_tolerance_basis | price_pct | price_pct | |
| そのまま | top_tolerance_atr_mult | 2.0 | 2.0 | atr時の3山共有 |
| **調整** | top_tolerance_mult | 0.2 | **0.25** | ~~査読4直後は0.3~~ → ユーザー調整で0.25(2026-08-14)。3点まとめての値幅判定(設計判断2、2026-08-14訂正)に対する倍率 |
| そのまま | min_valley_depth_atr_mult | 1.0 | 1.0 | 2谷とも |
| そのまま | max_valley_depth_atr_mult | 0.0(無制限) | **0.0(維持)** | 査読は「大きめ有限も可」だが2谷独立で既に厳しく維持 |
| そのまま | breakout_buffer_basis | price_pct | price_pct | |
| そのまま | breakout_buffer_atr_mult | 0.5 | 0.5 | |
| **調整** | breakout_buffer_mult | 0.075 | **0.05** | ユーザー調整(2026-08-14) |
| **調整** | efficiency_ratio_min | 0.25 | **0.1** | ~~査読4直後は0.15~~ → ユーザー調整で0.1(2026-08-14)。4脚平均に効くため |
| **調整** | efficiency_ratio_floor | 0.07 | **0.05** | ユーザー調整(2026-08-14)。核心4脚それぞれ |
| そのまま | trendline_dev_basis | price_pct | price_pct | |
| そのまま | trendline_dev_atr_mult | 0.9 | 0.9 | |
| **調整** | trendline_dev_pct | 0.8 | **0.9** | ユーザー調整(2026-08-14) |
| そのまま | efficiency_ratio_min_context | 0.1 | 0.1 | 山1前→山1 |
| そのまま | trendline_dev_*_context | 0.9 | 0.9 | |
| **調整** | efficiency_ratio_min_breakout | 0.25 | **0.15** | ~~査読4直後は0.25(そのまま)~~ → ユーザー調整で0.15(2026-08-14)。山3→ブレイク |
| **調整** | trendline_dev_*_breakout | 0.9 / 0.8 | **0.9 / 0.9** | ユーザー調整(2026-08-14) |
| そのまま | breakout_deadline_min_bars | 3 | 3 | 山3からの固定本数 |
| そのまま | breakout_deadline_ratio_max | 3.33 | 3.33 | 基準脚=i1 |
| **調整** | interval_symmetry_ratio_min | 0.67 | **0.5** | ~~実装当初は0.67(ダブルと同じ)~~ → ユーザー調整で0.5(2026-08-14)。**山2(パターンの中心)基準**(2026-08-14確定、§4参照) |
| **調整** | interval_symmetry_ratio_max | 1.5 | **2.0** | 同上、ユーザー調整で2.0 |
| そのまま | terminal_bounce_close_mult | 0.7 | 0.7 | 山3探索窓のみ |
| そのまま | breakout_type | close | close | |
| **新設・調整** | **neck_tolerance_mult** | — | **0.25(0=無制限は禁止)** | 査読D。~~初期値0.5~~ → ユーザー調整で0.25(2026-08-14)。2ネック水準近接 |

**検証済みの実測結果(2026-08-14、USDJPY 15分足全期間・約58万本)**: 上記最終初期値でConfirmed 22件(トップ)・21件(ボトム)、実行時間は1銘柄1方向あたり1秒未満(XAUUSD全期間でも同様)。

---

## 3. 検出アルゴリズム ①〜⑫

土台STの①〜⑫を、5点・2ネック・4間隔へ拡張する。逐条で示す。

| # | ダブル | トリプル拡張 | 根拠 |
|---|---|---|---|
| ① 山1 | 両側確認+値幅 | 変更なし(`ext_flags`) | 流用 |
| ② ネック | 山1後の最安ピボット・窓更新 | **ネック1** + 山2後に**ネック2**を同ロジックで探索 | best選択を2回 |
| ③ 間隔 | i1∈[min,max_bars] | **i1,i2,i3,i4 全て**が[min_bars,max_bars] | 各脚独立拘束 |
| ④ 山2窓 | ネック+i1×[sym] | **山2窓**=ネック1+i1×[sym]、**山3窓**=ネック2+i3×[sym] | 各終端窓に適用 |
| ⑤⑥ 終端 | 山2=左側のみ・最後一致 | **山3**=左側のみ・最後一致。**山2=単一正準点**(査読B) | 下記詳細 |
| ⑥.5 | ネック→山2でネック割れ禁止 | ネック1→山2、ネック2→山3 の両区間で `_shape_neckline_intact` | 複製 |
| ⑦ 深さ | ネック−平均(山1,山2) | **谷1・谷2を独立判定**(§2.2 設計判断4) | 各々[min,max] |
| ⑧ 山1前点 | ネック±余白へ後方探索 | **neck1基準**(査読A)。interval0 = neck1_bar − pre_bar | 左側=neck1固定 |
| ⑨⑩ | 3核心+文脈+ブレイク | **4核心**+文脈+ブレイク。孤立度は山2を除く4点 | 4脚へ拡張 |
| ⑪ 決着 | Confirmed/Invalidated | ネック=min/max単一水準。fail=max(山1,山2,山3)+余白。時間対称=neck_ref基準 | §4 |
| ⑫ 走査開始 | 山2+1 | **山3+1**から。報告は formed_bar 未満へクランプ | §5 |

### 3.1 探索の入れ子構造(擬似コード)
```
for 山1 in ext_events:                                   # ① 両側確認・値幅込み
  neck1 = -1
  for ネック1 in neck_events (> 山1):                     # ② best(最安)選択・窓打ち切り(規則A)
    if not is_better(neck1): continue
    if not _shape_extreme_intact(山1, ネック1): continue   # 山1が区間の極値のまま
    commit neck1;  i1 = ネック1 - 山1                       # ③ i1 ∈ [min_bars, max_bars]
    W2 = window(ネック1, i1, sym, min/max_bars)            # ④ 山2窓
    breach2 = first_breach(W2, 山1+tol)                    # 山1+tol超え → 窓を手前で打ち切り

    # ── 山2 = 単一正準点(査読B: 総当りしない) ──
    山2 = pick_highest(W2 ∩ [.., breach2-1], ext_flags,
                        anchor=山1, tol)                   # ⑤ W2内でtol範囲内の両側確認ピボットのうち最高値の1本
    if 山2 == -1: continue
    if not _shape_neckline_intact(ネック1, 山2): continue   # ⑥.5
    i2 = 山2 - ネック1

    neck2 = -1
    for ネック2 in neck_events (> 山2):                     # ネック2: best選択・窓打ち切り(規則A複製)
      if not is_better(neck2): continue
      if not _shape_extreme_intact(山2, ネック2): continue
      commit neck2;  i3 = ネック2 - 山2                      # i3 ∈ [min_bars, max_bars]
      if not neck_close(neck1_price, neck2_price): continue  # ★設計判断3a
      W3 = window(ネック2, i3, sym, min/max_bars)           # 山3窓
      山3, invalid = scan_terminal(W3, ext_flags_top3,
                       anchor=山1, tol, terminal_bounce)     # ⑤⑥ 終端:左側のみ・最後一致
      if 山3 == -1 or invalid: continue
      if not _shape_neckline_intact(ネック2, 山3): continue   # ⑥.5
      i4 = 山3 - ネック2

      # ⑦ 深さ×2 / ⑧ pre_bar(neck1軸) / ⑨⑩ eff×4核心+文脈+孤立度×4点
      if not all_geometry_ok(): continue
      formed_bar = confirm_floor(山1,ネック1,山2,ネック2,山3)  # ⑪ Candidate
      # ⑫ ブレイク走査(scan_start=山3+1, neck_ref=min): Confirmed / Invalidated
```

### 3.2 窓打ち切り規則A(ネック1・ネック2 共通)
土台の 2026-08-06 / 2026-08-13 修正(L552–606)を**両ネック探索へ複製**する:
- **08-06**: まだネック候補が1つも決まっていない間は、次の谷が出ても窓を閉じない。
- **08-13**: 窓を閉じてよいのは「次の山になり得る」谷、すなわち直後の反対型ピボットが山1(ネック2側なら山1)から `close_tol` 以内に収まるものだけ。ノイズ級の出っ張り1本では打ち切らない。
- トリプルは間隔が2倍で中間にトレンド区間を挟むため、ノイズ谷での早期打ち切りはダブル以上に致命的。**両方へ適用は必須**(適用しない選択は取らない)。

### 3.3 山2の単一正準点化(査読B・E を採用)
設計書は「山2をループで総当り(rareゆえ完全性優先)」としたが、**採用しない**。理由:
- 山2/ネック2は dedup キーに含まれる(除外は末尾の山3のみ)。総当りだと中央山の選び方違いで近接コピーが格子状に量産され、**dedupが一切効かない**(査読§5)。
- ネスト1段増でperf破綻(査読§3)。
- 土台STは各役割で単一ベスト点を選ぶ思想。総当りはそこからの逸脱(査読§6)。

**確定**(2026-08-13、ユーザー指摘で選択基準を再修正): 山2は W2 内の両側確認ピボットのうち「**山1との差がtol以内で、かつ価格が最も高い**(`price` 最大)」1本に正準化する(タイは時系列で早い方)。

> **経緯**: 当初「山1に最も近い(`|price−山1|` 最小)」を基準としていたが、これだとtol範囲内に複数の山型ピボットが立った場合、選ばれなかった側にもっと高い山が無視されたまま残ってしまう(例: 山1=100、候補がA=98/B=105/C=96なら「最も近い」はAを選び、Aより高いBが取り残される)。トリプルトップは**山を探すパターン**なので、tol範囲内の候補があるなら**その中で最も高いもの**を選ぶのが自然。これにより「選んだ山2の周囲(tol範囲内)に山2より高い山が来ない」ことが選択の時点で保証される。tolによる山1超過側の足切り(breach2)は従来どおり不変 — 変わるのは、足切り後に残った候補群からの**選び方**のみ。

これでネスト1段除去・dedup健全化・perfは変わらず一括解決する。

### 3.4 山3の終端走査(`scan_terminal`)
ダブルの山2走査(L644–678)を関数化して流用:
- W3内で `ext_flags_top3`(左側のみ)を満たし、かつ「山1・山2・候補3点の値幅(`max−min`)が tol 以内」の「**窓内で最後に一致したバー**」を山3とする(2026-08-14訂正、設計判断2参照)。
- `terminal_bounce_close_mult`: 山3出現後、山3→ネック2の価格差×この倍率だけ反発したら山3探索窓を閉じる(山3探索窓のみ、L667–674)。中間の山2にはこの概念は不要(両側確認ピボットのため)。
- W3内で `worst12`(bullishなら`min(山1,山2)`、そうでなければ`max(山1,山2)`)±tol を超えたら `window_invalidated`(候補ごと不成立方向)。

### 3.5 なめらかさ⑨/直線乖離⑩/孤立度
区間は文脈1+核心4+ブレイク1の計6。

| 区間 | 種別 | eff基準 | dev基準 | 孤立度 |
|---|---|---|---|---|
| 山1前 → 山1 | 文脈 | `_min_context` | `*_context` | 山1: 左=文脈窓, 右=山1→ネック1 → `L or R` |
| 山1 → ネック1 | 核心 | floor + 4脚平均 | 無印 | ネック1: 左=山1→ネック1, 右=ネック1→山2 → `L or R` |
| ネック1 → 山2 | 核心 | floor + 4脚平均 | 無印 | **山2: v1では孤立度なし(査読E)** |
| 山2 → ネック2 | 核心 | floor + 4脚平均 | 無印 | ネック2: 左=山2→ネック2, 右=ネック2→山3 → `L or R` |
| ネック2 → 山3 | 核心 | floor + 4脚平均 | 無印 | 山3: 左=ネック2→山3, 右=山3→ブレイク → `L or R`(右窓はブレイク確定時) |
| 山3 → ブレイク | ブレイク(Confirmed時のみ) | `_min_breakout` | `*_breakout` | |

**eff核心の一般化**: ダブルの `eff2≥floor and eff3≥floor and (eff2+eff3)/2≥min` を
```
eff_k ≥ efficiency_ratio_floor  (k=2..5)  かつ  (eff2+eff3+eff4+eff5)/4 ≥ efficiency_ratio_min
```
**dev核心**: 4核心区間それぞれで `_shape_dev_ok`(無印パラメータ)。
**文脈/ブレイク**: ダブルと同一。

---

## 4. 確定 / 無効 / (期限)の判定 — 3状態・1決着

走査は**山3+1**(`true_bar+1`)から。報告バーは `formed_bar` 未満にクランプ(ダブル L793–906 と完全同型)。

```
neck_price     = min(ネック1_price, ネック2_price)  (bullishは max)   # = 確定ネックライン(ブレイク判定専用)
worse_extreme  = max(山1, 山2, 山3)                (bullishは min)   # fail基準
depth          = neck_ref側(min側)の谷深さ
buf_j          = depth × breakout_buffer_mult          (price_pct)
               | ATR[j] × breakout_buffer_atr_mult      (atr)

confirm_j : 終値/ヒゲ が neck_price − buf_j を下抜け   (bullishは上抜け)          → Confirmed候補
fail_j    : 終値/ヒゲ が worse_extreme + buf_j を上抜け (bullishは下抜け)          → Invalidated
early     : (break_bar − 山3) < breakout_deadline_min_bars                       → Invalidated(早すぎ)
expire    : 走査窓 = i1 × breakout_deadline_ratio_max 経過で未決着                 → Invalidated(期限切れ)
同着(confirm_j & fail_j)は fail(=Invalidated)優先
```

**Confirmed の追加条件**(ダブルと同型):
- 時間0/時間1 対称(§6c): `time1 × interval_symmetry_ratio_min ≤ interval0 ≤ time1 × interval_symmetry_ratio_max`。
  - `interval0 = 山2_bar − pre_bar`
  - `time1 = break_bar − 山2_bar`
  - **実装確定(2026-08-13、再訂正)**: 本節の初稿は当時のダブル側の定義
    (ネック基準)に合わせて `neck_ref_bar` 基準で書いていた。実装着手時に
    一度「山3(終端の山)基準」に変更したが(ダブル側で基準点をネック→
    山2=終端点へ変更したという誤解に基づく変更)、これは誤りだった。
    実際の指示は「トリプルの山2(中間の山)を基準にしてほしい。トリプル
    は5点構成なので山2が前後2点ずつを従えるパターンの中心に来る。ダブル
    はネックが中心だから変更しない」というものだった。ダブル側は
    ネック基準のまま変更せず、トリプル側だけ**山2(中間の山)**を基準に
    する。山3基準にしていた際は実データで検出数が数十分の1まで激減する
    (山1前→山2〜山3〜ネック2と2区間分も余分に距離が伸びるため)実害が
    確認された。査読A(§1.2)の「左側ジオメトリはネック1固定・neck_refを
    持ち込まない」という原則とは別軸の変更(こちらは基準点を「ネックか
    山か」で選ぶ話、査読Aは「ネック1かネック2(neck_ref)か」を選ぶ話)。
- 山3→ブレイク区間の eff/dev(`_breakout`)を満たす。
- 満たさなければ Invalidated。

**実装時に発見した追加の論点(査読A関連、2026-08-13)**: ⑧山1前点の余白
(`pre_buf`)のサイズは、ブレイク判定の余白(`buf_j`、neck_ref側の深さを
使う)とは別に、**常にdepth1(ネック1自身の深さ)を使う**よう実装した。
当初はbreakout_buffer_valueをそのまま使い回していたが、これだと
neck_refがネック2になったケース(ネック2の方が高い/低い)で、
pre_level(ネック1基準の水準)にネック2側の深さから来た余白を足す
ことになり、基準点と余白サイズがねじれて`pre_bar`が見つからず候補
ごと不成立になる実バグがあった(合成テストで検出)。査読Aの「左側
ジオメトリは常にネック1軸」という原則を、余白の大きさにも一貫して
適用した形。

**各基準の一般化根拠**:
- **fail基準 = max(山1,山2,山3)+余白**: 3山の最高値ゾーンを上抜けて初めて不成立。ダブルの `max(top1,top2)` を3点へ一般化。
- **expire基準 = i1 × ratio_max**: ダブルと同じ基準脚。山どうしはsym比率でほぼ等間隔で i1 ≈ 各脚。総スパン基準にすると既定倍率が合わなくなるため**採用しない**。
- **早すぎ = breakout_deadline_min_bars(山3からの固定本数)**: ダブルと同一。
- **undercut/孤立(ブレイク区間)**:
  - 走行undercut `no_undercut`(L856–868): `neck_ref_bar → j` の走行極値と**山3**を比較。
  - **事前undercut(L738–751): `pre_bar → neck1_bar` の走行極値と山1**を比較。**neck_ref ではなく neck1 固定**(査読A、§1.2)。

---

## 5. 先読み防止とリペイント管理

### 5.1 confirm_floor(先読み防止)
```
confirm_floor = max(
    山1_bar    + pivot_confirm_lag,
    ネック1_bar + pivot_confirm_lag,
    山2_bar    + pivot_confirm_lag,
    ネック2_bar + pivot_confirm_lag,
    山3_bar                          # 左側のみ=遅延0
)
formed_bar = confirm_floor
```
山3 ≥ ネック2 + min_bars(= pivot_right = lag) ≥ ネック2確定 なので実質 `formed_bar ≈ 山3`。走査は山3+1開始・報告は山3以降にクランプされ、報告バーの先読みは無い(査読§1「合格」)。

### 5.2 ブレイク走査開始と書き込みクランプ
- 走査開始 = `山3 + 1`(価格自体はそのバーが閉じた時点で既知=未来不使用)。
- 結果を書き込むバー `outcome_bar` は `formed_bar` 未満にならないようクランプ(L905–934と同型)。

### 5.3 既知のリペイント性質(明記)
- **窓無効化リペイント(継承・トリプルで2倍化)**: 山2窓・山3窓の前方走査で、点確定より**後**のバーが `山1±tol` を突き抜けると `window_invalidated` で候補ごと `continue`(L650–655)。報告予定 formed_bar より未来のバーで候補を握り潰すため、ライブなら Candidate→Invalidated 遷移すべきものが、バッチでは「最初から無かった」ことになる。**ダブル由来の既知性質で、無効化窓が2つになり発生頻度が上がる。v1では許容**(査読§1・中)。
- **昇降型トリプル(傾いたネック)は非対応**(査読F): 谷が階段状に切り上がる/切り下がる形は本来傾いたネックが定義。水平 min/max 線は割れが遅い/来ないため、これらは**丸ごと取りこぼす**。v1は水平型のみ対応と割り切る。将来は「2谷を結ぶ直線」バリアントで別途対応。**黙って落ちると0件の原因が読めなくなるため明記必須**。

---

## 6. 計算量と枝刈り

### 6.1 素朴実装の危険性(査読§3)
土台の内側走査はバー単位ループ(L644 `for j in range(win_start, win_end+1)`)。`sym_max=3.33`・`max_bars=0(CAP3000)`だとW2が数千バー。トリプルを素朴に4段ネスト+山2総当りにすると `ext_events(10万) × [W2走査(数千) × 山2ピボット(数十) × (neck2走査 + W3走査(数千))]` ≈ **10¹¹ バー訪問**で、ゴールド等トレンド銘柄では1銘柄1方向あたり分〜十数分。auto-exploration(数千パラメータ組)では**実質使用不能**。

### 6.2 枝刈り(必須・全採用)
1. **山2を単一正準点に確定**(§3.3、査読B): ネスト1段除去。最大の効き。
2. **`symmetry_ratio_max` の初期値を有限化**(§2.3、査読C): 0=無制限を初期値にしない(推奨2.5)。窓終端は必ず `_MAX_BARS_BETWEEN_TOPS_UNLIMITED_CAP=3000` でクランプし、`i1×sym_max`・`i3×sym_max` もCAPクランプ。`max_bars_between_tops`自体は0(無制限)のままで実用速度が出ることを実測確認済み(2026-08-14) - 山2単一正準点化(枝刈り1)だけで計算量の主因は解消されており、`_MAX_BARS_BETWEEN_TOPS_UNLIMITED_CAP`の内部クランプが暴走時の安全弁として機能する。
3. **neck1/neck2 の best-谷を事前配列で前計算**し、各終端窓でO(1)参照。ループ内で毎回 `neck_events` を舐めない。
4. **cheap precheck**: ネック1改善時、W2に `山1±tol` の山型ピボットが1本も無ければ neck2/山3 の重い走査へ降りない。

これらにより、有界窓×正準点1本で per-top1 のコストがダブル並に落ち、58万本(5m全期間相当)でも実用速度で回る見込み。

---

## 7. 共通管理仕様

- **pattern_id**: `_make_pattern_id("triple_top_shape", (山1, ネック1, 山2, ネック2, 山3))`。
- **重複判定キー**: `_make_dedup_key("triple_top_shape", (…5点…), newest_first=False)` → **末尾=最新(山3)を除外**した4点で同一性を見る。山3は左側のみ確定で右側の値動き次第で後からズレ得るため(ダブル/フラッグと同じ末尾除外規則、L1311–1333)。山2を正準点化(§3.3)したことで、この4点キーが視覚的トリプル1つに正しく1対1対応する(総当りだと格子状濫立して破綻していた)。
- **1パターン1決着 / 複数同時保持**: `formed_bar` アンカー方式(L908–934)を踏襲。同一 formed_bar の上書き回避(L917–921)もそのまま。
- **3状態**: Candidate / Confirmed / Invalidated。`_SHAPE_STATE_KEYS`(旧6状態互換マップ L1146–1158)を流用。

---

## 8. 再利用する既存ヘルパーと新規njit関数の骨格

### 8.1 既存ヘルパー使用箇所(すべて `engine/chart_patterns.py`)
| ヘルパー | 用途 |
|---|---|
| `_detect_pivot_highs/lows`(両側) | `ext_flags`(山1・山2)、`neck_flags`(ネック1・ネック2)。`_pivot_flags` 経由で left/right=0 の片側判定も自動対応 |
| `_detect_pivot_highs/lows_left_only` | `ext_flags_top3`(**山3のみ**) |
| `_prominence_flags` | 山1・山2・ネック1・ネック2・山3 の値幅チェック(山3は `pivot_right_bars=0` 渡し) |
| `_shape_spike_ok` | 孤立度(**v1は 山1・ネック1・ネック2・山3 の4点。山2は外す**) |
| `_shape_eff_ratio` | 6区間の効率比 |
| `_shape_dev_ok` | 6区間の直線乖離 |
| `_shape_neckline_intact` | ネック1→山2、ネック2→山3 |
| `_shape_extreme_intact` | 山1→ネック1、山2→ネック2 |
| `_make_pattern_id` / `_make_dedup_key` | §7 |
| `_rrcp_resolve_core` | **使わない**(STは独自ブレイク走査) |

### 8.2 新規njit `_shape_state_core3` 骨格
```python
@njit(cache=True)
def _shape_state_core3(
    high_a, low_a, close_a, atr_a,
    ext_price_a, neck_price_a,
    ext_flags, neck_flags, ext_flags_top3,        # 山1/山2=ext_flags, 山3=ext_flags_top3
    bullish, pivot_confirm_lag,
    …(ダブルと同じ33個)…,
    neck_tolerance_mult,                          # ★新規1個
):
    n = high_a.shape[0]
    # effective_* クランプ(_MAX_BARS.../ _UNLIMITED_RATIO)はダブルと同じ
    # 出力: exists/candidate/confirmed/invalidated + formed_bar
    #       + top1/neck1/top2/neck2/top3 の bar と price
    ext_events  = np.flatnonzero(ext_flags)
    neck_events = np.flatnonzero(neck_flags)

    for ei in range(ext_events.shape[0]):                 # 山1
        top1 = ext_events[ei]; top1_price = ext_price_a[top1]
        neck1 = -1
        s1 = np.searchsorted(neck_events, top1+1, "left")
        for ki1 in range(s1, neck_events.shape[0]):       # ネック1(規則A: L552-606 複製)
            k1 = neck_events[ki1]
            # 窓打ち切り(08-06/08-13)/ i1拘束 / is_better / _shape_extreme_intact(top1,k1)
            # commit neck1; i1 = k1 - top1
            # W2 = window(neck1, i1, sym, min/max_bars); breach2 = first_breach(W2, top1+tol)
            # top2 = pick_highest(W2∩[..breach2-1], ext_flags, top1, tol)   # 査読B: 単一化(2026-08-13、tol内最高値へ訂正)
            # if top2==-1 or not _shape_neckline_intact(neck1,top2): continue
            # i2 = top2 - neck1
            s2 = np.searchsorted(neck_events, top2+1, "left")
            for ki2 in range(s2, neck_events.shape[0]):   # ネック2(規則A 複製)
                k2 = neck_events[ki2]
                # 窓打ち切り / i3拘束 / is_better / _shape_extreme_intact(top2,k2)
                # commit neck2; i3 = k2 - top2
                # if not neck_close(neck1_price, neck2_price, neck_tolerance_mult): continue  # ★3a
                # W3 = window(neck2, i3, sym, min/max_bars)
                # top3, invalid = scan_terminal(W3, ext_flags_top3, top1, tol, terminal_bounce)  # L644-678型
                # if top3==-1 or invalid: continue
                # if not _shape_neckline_intact(neck2, top3): continue
                # ⑦ depth1/depth2 独立 / neck_ref = argmin(neck1,neck2) / depth = neck_ref谷
                # ⑧ pre_bar は neck1 軸で後方探索(査読A)、余白サイズもdepth1固定
                #    (breakout_buffer_valueのneck_ref依存を流用しない、実装で発見)
                #    interval0 = 山2_bar - pre_bar(§4、2026-08-13に山2(中間の
                #    山=パターンの中心)基準へ確定。一度山3基準にしたが誤りで撤回)
                # ⑨⑩ eff×4核心 + 文脈 + 孤立度×4点(山2除外)
                # formed_bar = confirm_floor(top1,neck1,top2,neck2,top3)
                # candidate_a[formed_bar] = True
                # ⑪⑫ ブレイク走査(scan_start=top3+1, neck_price=min, 事前undercutはneck1軸)
                #     confirm/fail/early/expire → resolve/invalidated, outcome_bar クランプ(L905-934型)
    return (exists, candidate, invalidated, resolve, formed_bar,
            top1_bar, neck1_bar, top2_bar, neck2_bar, top3_bar,
            top1_price, neck1_price, top2_price, neck2_price, top3_price)
```
`scan_terminal`・早すぎ/失敗/期限判定は、ダブルの該当ブロック(L644–678、L814–899)を**関数化して式変更なしで移す**のが安全。

### 8.3 ラッパー `_triple_top_bottom_shape_state`
ダブルの L1024–1143 をコピーし、`ext_flags_top2`→`ext_flags_top3`(山3用に名称のみ)、`neck_tolerance_mult` を渡し、戻り値dictに `neck1_bar/neck2_bar/top3_bar` 系を追加するだけ。

---

## 9. 表現力の限界・稀少性の注意

### 9.1 効きすぎる条件(強い順)
1. **山2が両側確認ピボット** + `ネック1→山2`・`ネック2→山3` の両 `_shape_neckline_intact` + **核心4脚それぞれ eff≥floor**(失敗機会が2→4に倍増)。掛け算で最も効く。
2. **3山すべて山1±tol**(mult=0.2は「最初の脚の20%以内に3ピークが収まる」できつすぎ)+ **2ネック近接**。
3. **2谷独立の深さ判定**(実質2乗)。
4. **対称窓×2 + 4脚すべて min_bars_between_tops 拘束**でジオメトリ硬直。

### 9.2 v1で削った/緩めた条件(査読採用)
- **中央山(山2)の孤立度チェックを外す**(検出寄与が薄く稀少化に効きすぎる、査読E)。
- `efficiency_ratio_min` を 0.25 → **0.15**(4脚平均に効く)。
- `top_tolerance_mult` を 0.2 → **0.3**(トリプルだけ広げ中央山の変動を許容)。
- `symmetry_ratio_max` 3.33 → **2.5**(perf論拠)。`max_bars_between_tops`は一度0→1500に変更したが、山2単一正準点化で計算量は既に解消済みと実測確認できたため**0(無制限)へ差し戻し**(2026-08-14)。
- `neck_tolerance_mult` = **0.5**(0=無制限は禁止。理由は下記)。
- **昇降型トリプルは非対応と明記**(0件の誤読防止、査読F)。

### 9.3 「min ネックと neck_tolerance の自己矛盾」を解消(査読§2)
設計書は「2谷は近接強制済みだから min≒both」としつつ「neck_tolerance_mult を一旦0=無制限から開始」を推奨し、**矛盾**していた。neck_tol=0 だと2谷が任意にズレ、min() がネック1から大きく下方へ外れ、ブレイク水準が視覚的ネックラインと乖離して**系統的に Confirmed=0**(緩めるほど減る逆説)。
→ **v1は `neck_tolerance_mult` を有限の緩め値0.5で開始し、0=無制限は封じる**。min ネックの論拠と初期値を一致させる。

---

## 10. 実装時の検証手順

土台STの「丸ごと移植」と同じ流儀:

1. **段階的に条件を足す**(退化ケースでダブルに一致させることは構造上できないので不可)。まず**最小構成**(5点ジオメトリ + tol + 深さ)だけで検出し、件数がゼロでないことを確認 → eff/dev/孤立度/対称/neck近接 を1つずつ足して各段の件数減を観測。
2. **件数計測ベースライン**: bearish/bullish 各1銘柄フル期間で件数を出す。**RRCP版 `triple_top` と同一銘柄で桁を突き合わせ**て妥当性を判断。0件なら §9.2 の緩和を1つずつさらに緩める。
3. **目視ギャラリー比較**: RRCP版と同一銘柄で検出区間をチャート重畳し、形が「3山・2谷・水平ネック」に見えるか目視。昇降型が落ちているのは仕様(§5.3)。
4. **決定性の回帰テスト**: 同一入力で全出力配列がビット一致(先読み無し・非乱択)を回帰テスト化。
5. **先読みの明示検証**: 山3以降のバーを人為的に改変しても formed_bar 以前の出力が変わらないことを確認(§5)。
6. **perf計測**: ゴールド等トレンド銘柄・5m全期間で1銘柄1方向の実行時間を計測し、§6.2 の枝刈りが効いているか(ダブル並のオーダーか)を確認。

---

参照実装: `C:\Users\bigin\保存用ファルダ\StrategyX\engine\chart_patterns.py`
(`_shape_state_core` L471–940、pre-undercut L738–751、top2バー走査 L644–678、ブレイク走査 L814–899、ヘルパー L338–446、ラッパー L942–1143、dedup L1311–1333)
