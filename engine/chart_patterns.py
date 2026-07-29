"""Classic multi-swing chart patterns (double top/bottom, head & shoulders,
triangles, wedges, flags/pennants, range boxes) - built on top of
engine/smc_indicators.py's swing-high/swing-low detection (the same
machinery BOS/CHoCH already use), rather than a new fractal detector.

UNLIKE engine/technical_indicators.py's classic indicators, chart patterns
have no single agreed mechanical definition - real traders judge "is this a
head and shoulders" partly by eye. Everything here is a deliberately
simplified, vectorizable approximation (flat necklines instead of the
textbook's slanted ones, relative-tolerance level-matching instead of
subjective symmetry) - same "exploratory, not verified against any
reference charting tool" caveat engine/smc_indicators.py's own module
docstring already states, extended to a harder category of pattern.

Every function returns a plain np.ndarray[float] (boolean fired 1.0/0.0)
directly, same convention as engine/derived_indicators.py, for the same
reason (a pd.Series slipping into the numba fast backtest path crashed it
once - see engine/candlestick_patterns.py's history).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.indicators import atr as _atr_series
from engine.smc_indicators import _confirmed_swing_level_series, _detect_swing_highs, _detect_swing_lows


# ---------------------------------------------------------------------------
# Swing-level tracking: for each bar, the level and bar-index of the most
# recently confirmed swing high/low (n=0), the one before that (n=1), and
# the one before THAT (n=2) - generalizes smc_indicators.py's
# _last_confirmed_level/_previous_confirmed_level (which only ever look 1
# swing back) to however many a given pattern needs.
# ---------------------------------------------------------------------------

def _swing_high_levels(high: pd.Series, lookback: int) -> pd.Series:
    flags = _detect_swing_highs(high, lookback)
    return _confirmed_swing_level_series(flags, high, lookback)


def _swing_low_levels(low: pd.Series, lookback: int) -> pd.Series:
    flags = _detect_swing_lows(low, lookback)
    return _confirmed_swing_level_series(flags, low, lookback)


def _nth_back_level(level_series: pd.Series, n: int) -> pd.Series:
    sparse = level_series.dropna()
    shifted = sparse.shift(n)
    return shifted.reindex(level_series.index).ffill()


def _nth_back_bar_index(level_series: pd.Series, n: int = 0) -> pd.Series:
    """Integer position of the bar the n-th-back confirmed swing point (0 =
    most recent) was ORIGINALLY confirmed at, forward-filled onto the full
    timeline - `level_series` must be the RAW (unshifted) swing series
    (e.g. `swing_low`, not `_nth_back_level(swing_low, 1)`), same
    convention as _nth_back_level's own `n`."""
    sparse = level_series.dropna()
    bar_positions = pd.Series(sparse.index, index=sparse.index)
    shifted = bar_positions.shift(n)
    return shifted.reindex(level_series.index).ffill()


def _similar(a: pd.Series, b: pd.Series, atr: pd.Series, tolerance_atr_mult: float) -> pd.Series:
    """Whether two price levels are "the same level" for pattern-matching
    purposes, expressed as a multiple of ATR rather than a % of the raw
    price - a % of price scales wildly differently for a ~150-unit JPY
    pair vs a ~1-unit USD pair AND, separately, is the wrong order of
    magnitude entirely (a swing-to-swing gap is naturally comparable to a
    handful of bars' typical range, not a % of the symbol's absolute price
    level) - same ATR-normalization already used for dist_to_ema_atr_ratio
    and the flag/pennant impulse thresholds, for the same reason."""
    return (a - b).abs() <= atr * tolerance_atr_mult


def _falling_edge(state: pd.Series) -> pd.Series:
    """True only on the bar `state` transitions True->False (mirror image
    of _rising_edge, same dtype-upcast fix applied)."""
    filled = state.fillna(False).astype(bool)
    previous = filled.shift(1).fillna(False).astype(bool)
    return previous & ~filled


def _rising_edge(state: pd.Series) -> pd.Series:
    """True only on the bar `state` transitions False->True.

    `.shift(1)` on a bool Series introduces NaN at the first row, which
    silently upcasts the whole Series to object dtype - `.fillna(False)`
    alone does NOT undo that upcast, so a later `~` (bitwise NOT) applies
    Python's integer bitwise-complement to leftover Python bool objects
    (`~False == -1`, `~True == -2`, both truthy) instead of logical
    negation. The explicit `.astype(bool)` after fillna is required to get
    a real boolean dtype back before inverting."""
    filled = state.fillna(False).astype(bool)
    previous = filled.shift(1).fillna(False).astype(bool)
    return filled & ~previous


def _first_occurrence_after(pattern_formed: pd.Series, trigger: pd.Series) -> np.ndarray:
    """Fires only on the FIRST bar `trigger` is true after `pattern_formed`
    becomes true - a fresh pattern-formed bar starts a new "epoch"; a
    trigger before any pattern has formed, or a repeat trigger within the
    same still-active epoch, never (re-)fires. Same vectorized cumsum-
    within-epoch trick engine/derived_indicators.py's _first_retest and
    _first_pullback_after_breakout already use."""
    formed = pattern_formed.fillna(False)
    epoch = formed.cumsum()
    triggered = trigger.fillna(False) & (epoch > 0) & ~formed
    triggered_count_in_epoch = triggered.groupby(epoch).cumsum()
    return (triggered & (triggered_count_in_epoch == 1)).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# 非対称ピボット(左右の本数を別々に指定できるスイング高値/安値検出) -
# engine/smc_indicators.py::_detect_swing_highs/_detect_swing_lowsは
# center=Trueの対称窓(左右が必ず同じ本数)しか使えないため、ダブルトップ/
# ボトムの厳密な仕様(ユーザー提供仕様書の「Pivot Left Bars」「Pivot Right
# Bars」)向けにこちらを新設した。BOS/CHoCH等、既存の全指標が使っている
# 対称版(_swing_high_levels等)には一切手を加えていない。
#
# ベクトル化の考え方: 窓[i-left, i+right]内の最大値は、
# 「[i-left, i]の最大値」と「[i, i+right]の最大値」の大きい方に等しい
# (どちらもiを含むので、2つの合成が元の窓全体と一致する) - rolling().max()
# を2回(片方は系列を逆順にしてから)呼ぶだけでよく、バー数ぶんのPythonループ
# が不要。500k本規模のバックテストでも高速。
# ---------------------------------------------------------------------------

def _detect_pivot_highs(high: pd.Series, left: int, right: int) -> pd.Series:
    left_max = high.rolling(window=left + 1).max()
    right_max = high[::-1].rolling(window=right + 1).max()[::-1]
    # skipna=False(デフォルトのskipna=Trueを明示的に無効化) - 配列の末尾
    # right本未満の区間はright_maxがNaN(右側の確認本数が足りず判定不能)に
    # なるが、デフォルトのskipna=Trueだとmax(axis=1)がそのNaNを無視して
    # left_maxだけで判定してしまい、右側が全く確認されていないバーまで
    # 「ピボット高値」と誤判定してしまう(実際に発生: 配列末尾付近の
    # バーがピボットと誤判定され、そのバーの位置+right本を配列の範囲外
    # まで使おうとしてIndexErrorになるまで気づかれなかった)。片方でも
    # NaN(=左右どちらかの確認本数が足りない)ならこのバー自体を判定不能
    # としてNaNのまま伝播させ、is_pivotのfillna(False)で正しく除外する。
    overall_max = pd.concat([left_max, right_max], axis=1).max(axis=1, skipna=False)
    is_pivot = (high == overall_max).fillna(False)
    return _collapse_consecutive_runs(is_pivot)


def _detect_pivot_lows(low: pd.Series, left: int, right: int) -> pd.Series:
    left_min = low.rolling(window=left + 1).min()
    right_min = low[::-1].rolling(window=right + 1).min()[::-1]
    # _detect_pivot_highsと同じ理由でskipna=False。
    overall_min = pd.concat([left_min, right_min], axis=1).min(axis=1, skipna=False)
    is_pivot = (low == overall_min).fillna(False)
    return _collapse_consecutive_runs(is_pivot)


def _collapse_consecutive_runs(flags: pd.Series) -> pd.Series:
    """engine/smc_indicators.py::_collapse_consecutive_runsと同じ(平坦な
    天井/底が窓の等号判定に複数バーで一致してしまうのを、最初の1本だけに
    絞る) - こちらは非対称ピボット専用に複製(smc_indicators.py側は
    プライベート関数でimportして再利用する契約になっていないため)。"""
    return flags & ~flags.shift(1, fill_value=False)


# ---------------------------------------------------------------------------
# Double / Triple Top & Bottom
# ---------------------------------------------------------------------------

def _double_top_bottom_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int, pivot_right_bars: int,
    min_bars_between_tops: int, max_bars_between_tops: int,
    top_tolerance_type: str, top_tolerance: float,
    min_valley_depth_type: str, min_valley_depth: float,
    symmetry_ratio_min: float, symmetry_ratio_max: float,
    trendline_tolerance_pct: float,
    breakout_type: str, breakout_buffer: float,
    breakout_deadline_ratio_min: float, breakout_deadline_ratio_max: float,
    pip_size: float,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    top2_pivot_based: bool = False,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
) -> dict[str, pd.Series]:
    """ダブルトップ/ボトムの共通判定ロジック - 「パターンの検出(市場構造)」
    と「売買方向を持つシグナル」を分離する設計(ユーザー要望:「ダブルトップ
    は本来ショートエントリー用の反転パターンであるが...チャートパターンの
    検出とエントリーシグナルを分離して設計したい」)。

    2026-07-23大幅改訂: 「第2トップ = 独立にピボット検出された次の高値」
    ではなく、「山1→谷の本数を基準に、谷から一定範囲内で最も山1に近い
    価格を山2として探す」という、山1と谷が決まった時点で山2の"探索窓"
    自体を計算する方式に変更(ユーザー要望をそのまま反映)。

    top2_pivot_based: 上記の変更を一部差し戻す形のオプション(デフォルト
    False=現状維持)。Trueにすると、山2候補として採用できるのは窓の中の
    「本物のピボット高値/安値」(ext_flags、山1・仮点と同じ判定基準)に
    限定される(ユーザー要望:「谷2の探索方法をピボット安値バージョンで
    別に実装して。今の構造はそのまま別に残して」- 一般的なチャート
    パターン認識ツールは山1・山2の両方を対称にピボットで検出するため)。
    それ以外の判定(許容誤差ゲート・窓の範囲・直線乖離・5状態モデル等)は
    Falseの時と完全に共通。ピボット確定にはpivot_right_bars本の確認が
    必要なため、これもtop1・ネックと同じ先読み防止(confirm_floor)の
    対象に含める。

    ダブルトップ(bullish=False)を主語に書くと:
      ① 第1トップ = Pivot High(左pivot_left_bars本・右pivot_right_bars本
         より高い高値、right本後に確定)
      ② 谷(ネックライン) = 第1トップより後に確定した最初のPivot Low
      ③ 山1→谷の本数(interval1)がmin_bars_between_tops〜
         max_bars_between_tops
      ④ 第2トップ探索窓 = 谷からinterval1×symmetry_ratio_min本〜
         interval1×symmetry_ratio_max本の範囲。この窓の中で最高値を山2と
         する(窓の終わりに達するまで、より高い値が出るたびに山2を更新
         し続ける - ユーザー要望「この間に上値を更新したときは山2を
         更新する」)。ただし窓が開くより前(山1→谷の下落〜窓開始直前の
         上昇)に山1の価格を上回ったら、この山1はダブルトップの起点として
         無効(ユーザー要望「山1を上回ったときはダブルトップとみなさない」)
      ④' 窓の途中で(その時点までの暫定山2を基準に)ネックラインを割り、
         かつその時点の形(⑤⑥⑦)が妥当なら、窓の終わりを待たずにその場で
         山2を確定させて即エントリーにする(ユーザー要望:「その期間中に
         ネックラインをブレイクしたときはその時点で山2決定でエントリー
         にして」)。この経路では⑧⑨のブレイク猶予は評価しない(山2から
         の経過が定義上0本になるため) - 窓が閉じるまで割れなかった場合に
         限り、⑤〜⑨の通常経路(窓の最後の最高値を山2として確定)に進む。
      ⑤ 窓が終わった時点で確定した山2の価格が、山1に対して
         top_tolerance_type/top_toleranceの範囲外なら、このダブルトップは
         不成立(ユーザー要望「山2の価格が許容範囲外を超えたときは
         ダブルトップとみなさない」)
      ⑥ 谷の深さ((山1+山2)/2 - 谷)がmin_valley_depth_type/
         min_valley_depth以上、かつmax_valley_depth_type/
         max_valley_depth以下(デフォルト999=実質無制限 - ユーザー報告:
         「山1・山2の水準はほぼ同じでも、間のネックラインが極端に高い
         (大きな一方向の値動きを挟んだだけの)崩れた形をいまだ拾って
         しまう」に対応。下限のみだったmin_valley_depthに上限を追加)
      ⑦ 山1→谷、谷→山2それぞれを直線で結んだ時、その間の高値/安値が
         直線からtrendline_tolerance_pct%(2点間の値幅に対する割合)以上
         乖離しない
         → ③〜⑦がすべて揃った瞬間(=山2探索窓の終わり)が"formed"
      ⑧ 山2確定後、谷→山2の本数(interval2)×breakout_deadline_ratio_min
         本未満でネックラインを下抜けたら、このダブルトップ自体を無効と
         する(早すぎるブレイクは「本物のダブルトップではなかった」と
         みなす - ユーザー要望「（ネックから山2までの本数）×0.5以内に
         ネックラインを下抜けたときはダブルトップとみなさない」)
      ⑨ interval2×breakout_deadline_ratio_min本以上・
         breakout_deadline_ratio_max本以内にbreakout_type(Close/Low)が
         ネックライン-breakout_bufferを下回れば"breakdown"(ショート方向の
         シグナル)
      ⑩ ブレイクダウンより先に、終値が両トップの高い方+breakout_bufferを
         上抜けたら"failed"(ネックラインを割らずに反転 - ロング方向の
         シグナル)。⑧と同じ早すぎ無効ルールをfailedにも適用する
      ⑪ formed〜(breakdown/failedのどちらかが起きる、または猶予本数超過)
         までの間、"exists"(パターン形成中の状態フィルター)がTrueで
         あり続ける
    bullish=Trueならダブルボトムとして高値/安値・上下を反転させた鏡像
    (谷1→山→谷2)。

    山1→谷→山2という一連の関係が本質的に逐次的(谷が決まらないと山2の
    探索窓が決まらず、山2が決まらないとブレイク猶予も決まらない)なため、
    確定したピボットの列を時系列に1件ずつ辿るPythonループで実装している
    (このモジュールの他のロジックのようなpandas全体のベクトル化はできない
    - ただし辿る対象は「確定ピボットの一覧」のみで全バー数ではないため、
    実用上十分高速)。"""
    n = len(high)
    idx_index = high.index
    high_a = high.to_numpy()
    low_a = low.to_numpy()
    close_a = close.to_numpy()
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_a = _atr_series(df, 14).to_numpy()

    # 「山」= 高値側のピボット、「谷」= 安値側のピボット。ダブルトップは
    # 山1→谷→山2(山側の2点を比べる)、ダブルボトムはその鏡像(谷1→山→谷2、
    # 谷側の2点を比べる) - extreme側/neck側どちらの生値を見るかを
    # bullishで切り替える。
    is_pivot_ext = (
        _detect_pivot_lows(low, pivot_left_bars, pivot_right_bars)
        if bullish
        else _detect_pivot_highs(high, pivot_left_bars, pivot_right_bars)
    )
    is_pivot_neck = (
        _detect_pivot_highs(high, pivot_left_bars, pivot_right_bars)
        if bullish
        else _detect_pivot_lows(low, pivot_left_bars, pivot_right_bars)
    )
    ext_price_a = low_a if bullish else high_a
    neck_price_a = high_a if bullish else low_a

    ext_flags = is_pivot_ext.fillna(False).to_numpy()
    neck_flags = is_pivot_neck.fillna(False).to_numpy()
    # _detect_pivot_highs/_detect_pivot_lowsは山/谷の「実際のバー」自体に
    # Trueが立つ(前後pivot_left_bars/pivot_right_bars本を見て初めて判定
    # できるが、フラグの位置そのものは確定遅延ぶんシフトされていない) -
    # ここでi自体をそのまま実際のバー位置として使う(以前i-pivot_right_bars
    # としていたのは、独立した_confirmed_level_asymヘルパーがshift(right)
    # で確定バーへずらした"後"の系列に対する変換だったため - このヘルパーは
    # もう使っていないので、この引き算はもう不要かつ誤り)。
    ext_events = [i for i in range(n) if ext_flags[i]]
    neck_events = [i for i in range(n) if neck_flags[i]]

    def _threshold(reference: float, atr: float, kind: str, amount: float) -> float:
        if kind == "pips":
            return amount * pip_size
        if kind == "percent":
            return abs(reference) * (amount / 100.0)
        return atr * amount

    def _line_deviation_ok(bar_a: int, price_a: float, bar_b: int, price_b: float) -> bool:
        # 山1→ネック・ネック→山2・山2→エントリー(Confirmedのみ)の3区間とも
        # 共通のこのヘルパーを使う(ユーザー仕様「それぞれの区間の両端を
        # 結んだ直線からの乖離(すべて同じ仕組み)」)。許容幅は
        # 「2点間の値幅×trendline_tolerance_pct%」(ユーザー仕様
        # 「許容幅=|区間両端の価格差|×直線からの乖離許容(%)」- 0.5倍は
        # 撤廃、デフォルト80%)。
        span = bar_b - bar_a
        if span <= 0:
            return True
        tol = abs(price_b - price_a) * (trendline_tolerance_pct / 100.0)
        for j in range(bar_a, bar_b + 1):
            line_v = price_a + (price_b - price_a) * (j - bar_a) / span
            if max(abs(high_a[j] - line_v), abs(low_a[j] - line_v)) > tol:
                return False
        return True

    exists_a = np.zeros(n, dtype=bool)
    resolve_a = np.zeros(n, dtype=bool)
    failed_a = np.zeros(n, dtype=bool)
    # EA Studio的な5状態モデル(Detected/Confirmed/Failed After Retest/
    # Failed Before Retest/Expired)向けの追加出力(ユーザー要望:「チャート
    # パターンは基本的にはすべてこの運用にする」)。confirmedはresolveと
    # 同じなので専用配列は持たない。detectedは「谷2候補が最初に見つかった
    # バー」(existsの立ち上がりより前になり得る)なので専用配列を持つ。
    # failed_after_retest/failed_before_retest/expiredも、ここでの判定に
    # 専用の状態(リテスト有無、猶予切れ)が要るため配列を持つ。
    detected_a = np.zeros(n, dtype=bool)
    failed_after_retest_a = np.zeros(n, dtype=bool)
    failed_before_retest_a = np.zeros(n, dtype=bool)
    expired_a = np.zeros(n, dtype=bool)
    top1_bar_a = np.full(n, np.nan)
    top2_bar_a = np.full(n, np.nan)
    top1_price_a = np.full(n, np.nan)
    top2_price_a = np.full(n, np.nan)
    neckline_bar_a = np.full(n, np.nan)
    neckline_price_a = np.full(n, np.nan)
    formed_bar_a = np.full(n, np.nan)

    last_consumed_bar = -1
    neck_search_from = 0

    for top1_true_bar in ext_events:
        if top1_true_bar <= last_consumed_bar:
            continue
        top1_price = float(ext_price_a[top1_true_bar])
        # top1_true_barはピボット判定(左pivot_left_bars本・右pivot_right_bars
        # 本より高い/安い)の「実際のバー」だが、そのバーが本物のピボットだと
        # 分かるのは右側pivot_right_bars本ぶん先(top1_true_bar+
        # pivot_right_bars)になってから - それより前にこの山1を根拠にした
        # 判定(Detected/Confirmed/Failed等)を確定させると、リアルタイムでは
        # まだ持ち得ない情報を使ったことになる(先読みバイアス・リペイント)。
        # confirm_floor(下記)の一部として、実際の判定確定を遅らせる。
        top1_confirm_bar = top1_true_bar + pivot_right_bars

        # neck_search_fromは「top1_true_bar以下の谷候補」だけを恒久的に
        # 読み飛ばすポインタ(top1_true_barは毎回のイテレーションで単調
        # 増加するため、あるバー以下の谷はそれ以降のどのtop1候補にとっても
        # 使えないので安全に捨てられる)。以前は直前に成立した候補の
        # インデックス(k)まで丸ごと読み飛ばしていたが、それだと「不成立に
        # 終わった候補が使った谷」を後続の別の(正当な)候補が再利用できず
        # ネックの取り違えが起きる恐れがあった(山1候補どうしの時間範囲の
        # 消費をやめたことで、複数の候補が同じ谷を共有し得るようになった
        # ため)。
        while neck_search_from < len(neck_events) and neck_events[neck_search_from] <= top1_true_bar:
            neck_search_from += 1
        if neck_search_from >= len(neck_events):
            break  # これ以降、谷候補が確定することはない
        neck_true_bar = neck_events[neck_search_from]
        neck_price = float(neck_price_a[neck_true_bar])
        # top1と同じ理由でネックもpivot_right_bars本ぶんの確定遅延を持つ -
        # ただし後で(窓が開くまでの監視・窓の中の再判定で)生の高値/安値に
        # 基づいて更新された場合は、その値は更新された瞬間から既知(生の
        # 価格そのものなので確定待ちは不要)になる。neck_confirm_barはこの
        # 「いつからこのネック価格を根拠に判定を確定してよいか」を表す。
        neck_confirm_bar = neck_true_bar + pivot_right_bars

        interval1 = neck_true_bar - top1_true_bar
        if interval1 <= 0 or not (min_bars_between_tops <= interval1 <= max_bars_between_tops):
            continue

        # ネックは、山1から見て「山1→ネックの本数×neck_prior_lookback_ratio」
        # だけ遡った期間の最高値(ダブルトップなら最安値)より、さらに低い
        # (ダブルトップなら高い)位置になければならない(ユーザー要望:「ネック
        # は谷1よりも(谷1〜ネックまでの期間分)前の期間の最高値よりも低い
        # 位置でなければならない」→その後「期間長を(谷1→ネック)×3.0倍に、
        # このチェック自体もオン/オフを選べるパラメーターに」)。これを満たさ
        # ないネックは、山1の手前からすでに続いていた大きな流れの一部でしか
        # なく、そこだけを切り取って反転パターンとみなすのは不適切と
        # みなして不成立にする。山1より前のデータが足りない場合は判定
        # できないのでスキップ(不成立にはしない)。参照期間の長さはここで
        # 確定したinterval1×neck_prior_lookback_ratioで固定し、この後ネック
        # が再判定されても変えない - prior_extremeは形の判定時に再判定後の
        # ネック価格と突き合わせるため、ここでは変数として残しておく。
        prior_extreme = None
        if neck_prior_check_enabled:
            lookback_len = int(round(interval1 * neck_prior_lookback_ratio))
            lookback_start = top1_true_bar - lookback_len
            if lookback_start >= 0:
                prior_extreme = float(
                    neck_price_a[lookback_start:top1_true_bar].max()
                    if bullish
                    else neck_price_a[lookback_start:top1_true_bar].min()
                )
                neck_prior_ok = (neck_price < prior_extreme) if bullish else (neck_price > prior_extreme)
                if not neck_prior_ok:
                    continue

                # 谷1の前に「仮点」を設ける(ユーザー要望) - 上のネック事前
                # 妥当性チェックで見ている同じ遡り期間
                # [lookback_start, top1_true_bar)の中で、終値がネックより
                # 高い(ダブルトップなら低い)ローソク足のうち、谷1に一番
                # 近い(バーindexが一番大きい)ものの終値を仮点とする。
                # 「谷1の直前まで、ネックを上回る水準にいた」ことを表す
                # 具体的な1点を作り、そこから谷1までが妥当な下落経路(直線
                # 乖離が許容範囲内)であることを、他の3区間(山1→ネック・
                # ネック→山2・山2→エントリー)と同じ仕組みで検証する。
                # 該当するローソク足が1本も無ければ、この山1候補自体を
                # 不成立にする(=5状態のいずれも成立し得ない、ユーザー
                # 要望「上記を満たしたときのみ、下記5点の判定が有効」)。
                # 仮点も他の3点と同じくヒゲ(生の高値/安値)ベース(ユーザー
                # 要望:「ネックより高値が高いローソク足のうち一番新しい
                # ローソク足の高値」- neck_price_aが元々high_a(ダブルトップ
                # なら安値との比較用にlow_a)なので、そのまま流用できる)。
                provisional_bar = None
                for k in range(top1_true_bar - 1, lookback_start - 1, -1):
                    if (neck_price_a[k] > neck_price) if bullish else (neck_price_a[k] < neck_price):
                        provisional_bar = k
                        break
                if provisional_bar is None:
                    continue
                provisional_price = float(neck_price_a[provisional_bar])
                if not _line_deviation_ok(provisional_bar, provisional_price, top1_true_bar, top1_price):
                    continue

        win_start = neck_true_bar + max(1, round(interval1 * symmetry_ratio_min))
        win_end = min(neck_true_bar + round(interval1 * symmetry_ratio_max), n - 1)
        if win_start > win_end:
            continue

        # 山2探索窓が開くまで(谷への下落〜窓が開く直前の上昇)の間に山1の
        # 価格を上回ったら、この山1はダブルトップの起点として無効とする
        # (ユーザー要望「山1を上回ったときはダブルトップとみなさない」)。
        # 窓の中で山1と同水準/やや上の値が出ること自体は正常(許容誤差判定
        # で別途扱う)なので、窓が開く直前までだけを見る。
        # あわせて、谷が確定してから山2ができるまでの間にさらに安値(ダブル
        # ボトムなら高値)を更新したら、谷を再判定する(ユーザー要望:
        # 「ネックが確定してから山2ができるまでにネックラインを割った場合
        # はネックを再判定して。山1〜山2の最安値がネックラインと一致する
        # ように」) - 窓が開く前の区間(このループ)と窓の中(次のループ)の
        # 両方で継続して見る。win_start/win_endは元の(再判定前の)谷を基準
        # に既に計算済みなので、ここでの再判定はそちらに影響しない。
        pre_window_exceeded = False
        exceed_bar = win_start
        running_neck_bar = neck_true_bar
        running_neck_price = neck_price
        running_neck_confirm_bar = neck_confirm_bar
        for j in range(top1_true_bar + 1, win_start):
            if (low_a[j] < top1_price) if bullish else (high_a[j] > top1_price):
                pre_window_exceeded = True
                exceed_bar = j
                break
            if j > neck_true_bar:
                cur_neck_price = float(neck_price_a[j])
                if (cur_neck_price > running_neck_price) if bullish else (cur_neck_price < running_neck_price):
                    running_neck_price = cur_neck_price
                    running_neck_bar = j
                    # 生の高値/安値による再判定 - このバーjの時点で既に
                    # 観測済みの実際の価格なので、pivot_right_barsぶんの
                    # 確定待ちは不要(このバー自体が確定バー)。
                    running_neck_confirm_bar = j
        if pre_window_exceeded:
            continue
        neck_true_bar = running_neck_bar
        neck_price = running_neck_price
        neck_confirm_bar = running_neck_confirm_bar

        # 山2探索窓([win_start, win_end])を1本ずつ進めながら、その最中に
        # ネックラインを割ったら、その時点の暫定山2(それまでの最高値)を
        # そのまま確定させて即エントリーにする(ユーザー要望:「山2＝(山1
        # から谷の間隔)×0.5〜1.5だが、その期間中にネックラインをブレイク
        # したときはその時点で山2決定でエントリーにして」) - 窓が閉じる
        # まで待たされてエントリーが遅れる問題(実際にユーザー報告)への
        # 対応。ブレイクの瞬間に形(許容誤差・谷の深さ・トレンドライン)が
        # 妥当でなければ即決着にはせず、山2の更新を続けて窓の終わりまで
        # 進む(=下の「窓が閉じるまで割れなかった場合」の通常経路にそのまま
        # つながる)。
        # 窓に入る時点の谷(窓が開くまでの再判定を反映済み)を控えておく。
        neck_true_bar_pre = neck_true_bar
        neck_price_pre = neck_price

        # 山2候補は、山1の水準許容誤差(top_tolerance_type/top_tolerance)の
        # 範囲内に収まっている値しか採用しない(ユーザー要望:「谷の水準
        # 許容誤差内に入ってないと谷2だと見なさないでほしい」)。候補が
        # 「新しい安値(高値)を付けたかどうか」自体はraw安値/高値(ext_price_a)
        # で判定するが、実際に山2候補として採用する価格は終値(ユーザー要望:
        # 「終値が安値を更新するたびに許容誤差内なら候補として更新する」) -
        # running_raw_extremeが「新しい安値/高値が出たか」の判定専用、
        # running_top2_bar/priceが実際の候補(終値ベース)。どちらもまだ
        # 候補が一つも見つかっていない間はNoneのまま。
        running_raw_extreme = None
        running_top2_bar = None
        running_top2_price = None
        # top2_pivot_based=Trueの時だけ使う、山2候補(ピボット)が実際に
        # 確定するバー(pivot_right_bars本の確認終了後、top1_confirm_bar/
        # neck_confirm_barと同じ考え方) - Falseの時は一度も更新されず、
        # confirm_floorのmax()に混ぜても他の2つより必ず小さいままなので
        # 挙動に影響しない。
        running_top2_confirm_bar = -1
        # 谷の再判定は「その時点までに確定している山2候補(running_top2_bar)
        # のバーまで」に限定する - neck_scanned_up_toが、谷の再判定を
        # 反映し終えた最後のバーを表す。山2候補が更新されるたびに、
        # そこまで谷スキャンを追いつかせる。山2候補がまだ更新されていない
        # (=まだ本当の山2ではなく、単なる下落の途中の)バーの安値/高値は
        # ここに含めない - 含めてしまうと、山2確定後の下落までネックの
        # 再判定に吸収されてしまい、本来起きるはずのブレイクが消える
        # (実際に発生: 2026-04-13のダブルトップで山2確定(21:00)後の下落が
        # すべて谷の再判定に吸収され、ブレイクが起きなくなっていた)。
        neck_scanned_up_to = neck_true_bar_pre
        early_exit_bar = None
        early_exit_kind = None
        # Detected(検出)= 山1/ネック/山2候補が出揃い、かつ形(谷の深さ・
        # 2区間の直線乖離・ネックの事前妥当性)も既に妥当と判定された最初の
        # バー(ユーザー要望:「最初に谷2候補が見つかったタイミングで
        # 「Detected」とする」- 正確には「候補が見つかり、かつ形も妥当な
        # 最初のタイミング」。窓が閉じるまで待たずに済むよう、候補が更新
        # されるたびに毎回チェックする)。
        detected_bar = None
        window_invalidated = False
        for j in range(win_start, win_end + 1):
            cur_raw = float(ext_price_a[j])
            cur_close = float(close_a[j])
            tol_j = _threshold(top1_price, atr_a[j], top_tolerance_type, top_tolerance)

            # 窓の中で一度でも、終値が山1の水準許容誤差を(悪い方向に)外れ
            # たら、この山1自体を不成立にする(ユーザー要望:「窓の中で
            # 一度でも許容誤差より低い終値が出現すると、この谷1自体を
            # 不成立にする」- ダブルトップならその鏡像で「許容誤差より
            # 高い終値」)。
            out_of_range_bad_side = (
                (cur_close < top1_price - tol_j) if bullish else (cur_close > top1_price + tol_j)
            )
            if out_of_range_bad_side:
                window_invalidated = True
                break

            # top2_pivot_based=Trueの時は、山1・仮点と同じ基準(ext_flags=
            # 本物のピボット高値/安値)を満たすバーだけを候補更新の対象に
            # する - それ以外のバーは単なる通過点として無視する(ユーザー
            # 要望:「谷2の探索方法をピボット安値バージョンで別に実装して」)。
            if (not top2_pivot_based) or ext_flags[j]:
                is_new_extreme = running_raw_extreme is None or (
                    (cur_raw < running_raw_extreme) if bullish else (cur_raw > running_raw_extreme)
                )
                if is_new_extreme:
                    running_raw_extreme = cur_raw
                    # 谷2の値も谷1・ネックと同じくヒゲ(生の安値/高値)ベースに
                    # 統一する(ユーザー要望:「3点すべて髭にする」- 谷1/ネックは
                    # 元々ヒゲ、谷2だけ終値だったのは以前の要望「終値が安値を
                    # 更新するたびに」によるものだったが、一般的なチャート
                    # パターンの定義(実際に到達した価格水準=ヒゲ)に合わせて
                    # 統一した)。
                    if abs(cur_raw - top1_price) <= tol_j:
                        running_top2_price = cur_raw
                        running_top2_bar = j
                        if top2_pivot_based:
                            # ピボット確定にはtop1・ネックと同じくpivot_
                            # right_bars本の確認が要る(先読み防止)。
                            running_top2_confirm_bar = j + pivot_right_bars

            if running_top2_bar is None:
                # まだ許容誤差内に収まる山2候補が一つも見つかっていない -
                # ネックの再判定もブレイク判定もまだ評価できない。
                continue

            # 山2候補が(このバーまでに)進んだぶんだけ、谷の再判定スキャンを
            # 追いつかせる。
            if running_top2_bar > neck_scanned_up_to:
                for k2 in range(neck_scanned_up_to + 1, running_top2_bar + 1):
                    cur_neck_price = float(neck_price_a[k2])
                    if (cur_neck_price > neck_price) if bullish else (cur_neck_price < neck_price):
                        neck_price = cur_neck_price
                        neck_true_bar = k2
                        # 生の高値/安値による再判定なので確定待ち不要(前述と
                        # 同じ理由)。
                        neck_confirm_bar = k2
                neck_scanned_up_to = running_top2_bar

            # 山1・ネックそれぞれが「実際にピボットだと確定する(pivot_
            # right_bars本の確認が終わる)バー」の遅い方 - これより前の
            # バーでDetected/Confirmed/Failedを確定させると、リアルタイムでは
            # まだ持ち得ない情報(未確定のピボット)を使ったことになる
            # (ユーザー報告により発覚: 実データでConfirmed対象の38%が、
            # Detected発火時点でネック未確定だった)。top2_pivot_based=True
            # の時は山2もピボットなので同じ扱いに含める(Falseの時は
            # running_top2_confirm_barが-1のままなので影響しない)。
            confirm_floor = max(top1_confirm_bar, neck_confirm_bar, running_top2_confirm_bar)

            # 形(山1との近さ・谷の深さ・2区間の直線乖離・ネックの事前妥当性)
            # の判定に使うATRは、判定している今のバー(j)ではなく、山2その
            # ものが確定した時点(running_top2_bar、最後に山2が更新された
            # 瞬間)のもので固定する(ユーザー要望:「形の判定に使うATRは...
            # 山2確定時点の値で固定する」)。そうしないと、山2確定後にATR
            # (ボラティリティ)が変動するだけで「同じ山2が急に形として成立
            # したりしなかったりする」という直感に反する挙動になっていた
            # (実際に発生: ネックラインは早期に割れていたのに、ATRが追い
            # つくまで数時間エントリーが遅れた)。
            tol_now = _threshold(top1_price, atr_a[running_top2_bar], top_tolerance_type, top_tolerance)
            extremes_similar_now = abs(running_top2_price - top1_price) <= tol_now
            avg_now = (top1_price + running_top2_price) / 2
            depth_tol_now = _threshold(avg_now, atr_a[running_top2_bar], min_valley_depth_type, min_valley_depth)
            max_depth_tol_now = _threshold(avg_now, atr_a[running_top2_bar], max_valley_depth_type, max_valley_depth)
            gap_now = (neck_price - avg_now) if bullish else (avg_now - neck_price)
            depth_ok_now = depth_tol_now <= gap_now <= max_depth_tol_now
            trend_ok_now = _line_deviation_ok(top1_true_bar, top1_price, neck_true_bar, neck_price) and _line_deviation_ok(
                neck_true_bar, neck_price, running_top2_bar, running_top2_price
            )
            # ネックが窓の中で再判定されている場合があるので、山1より前の
            # 期間との比較も再判定後の価格で確認し直す(前述のprior_extreme
            # チェックと同じ理由)。
            neck_prior_ok_now = prior_extreme is None or (
                (neck_price < prior_extreme) if bullish else (neck_price > prior_extreme)
            )
            shape_ok_now = depth_ok_now and trend_ok_now and neck_prior_ok_now

            if detected_bar is None and shape_ok_now and j >= confirm_floor:
                detected_bar = j

            if j < confirm_floor:
                # 山1・ネックのどちらかがまだ未確定 - この後のブレイク判定
                # (resolve_now/failed_now)はここでは評価しない(先読み防止)。
                # running_top2/ネックの追跡自体はループの次の周回でも続ける。
                continue

            buf = atr_a[j] * breakout_buffer
            if bullish:
                breakdown_price = high_a[j] if breakout_type == "high" else close_a[j]
                resolve_now = breakdown_price > (neck_price + buf)
                worse_extreme = max(top1_price, running_top2_price)
                failed_now = close_a[j] < (worse_extreme - buf)
            else:
                breakdown_price = low_a[j] if breakout_type == "low" else close_a[j]
                resolve_now = breakdown_price < (neck_price - buf)
                worse_extreme = min(top1_price, running_top2_price)
                failed_now = close_a[j] > (worse_extreme + buf)
            # ヒゲだけがネックを越えて終値がまだ戻っている間は無効にしない -
            # そのまま形成中(existsの範囲)として継続し、resolve_now/
            # failed_now(判定基準breakout_typeで選んだ価格)が実際に成立する
            # まで待つ(ユーザー要望「髭がネックを超えてもダブルボトム継続に
            # して」- 以前はヒゲの時点で形が妥当なら即無効にしていたが、
            # それをやめる)。
            if not (resolve_now or failed_now):
                continue

            if extremes_similar_now and shape_ok_now:
                early_exit_bar = j
                early_exit_kind = "resolve" if resolve_now else "failed"
                break

        if window_invalidated:
            # 不成立(終値が山1の水準許容誤差を悪い方向に外れた=無効)。
            # 前述と同じ理由で時間範囲を消費しない。
            continue

        if early_exit_bar is not None:
            # 山2確定とエントリーが同じ瞬間 - formed_bar=山2確定バー=
            # 発火バー。この経路では「山2からのブレイク猶予」の下限/上限
            # (次のブロックの reject_bars/expire_bars)は評価しない(定義上
            # 山2からの経過0本になってしまうため) - ユーザーとの合意通り、
            # このブレイク猶予ルールは「窓の中で割れなかった場合」の通常
            # 経路にのみ適用する。detected_barはearly_exit_barと同じか
            # それより前(形が妥当になった時点)のはず。
            top2_true_bar = running_top2_bar
            top2_price = running_top2_price
            formed_bar = early_exit_bar
            if detected_bar is None:
                detected_bar = formed_bar
            exists_a[detected_bar : formed_bar + 1] = True
            formed_bar_a[detected_bar : formed_bar + 1] = formed_bar
            detected_a[detected_bar] = True
            if early_exit_kind == "resolve":
                resolve_a[formed_bar] = True
            else:
                failed_a[formed_bar] = True
                # 即成立(early exit)は形成とほぼ同時に決着するため、リテスト
                # (ネック付近への再到達)が起きる時間的余地が無い - 常に
                # 「リテスト前の失敗」として扱う。
                failed_before_retest_a[formed_bar] = True
            top1_bar_a[formed_bar] = top1_true_bar
            top2_bar_a[formed_bar] = top2_true_bar
            top1_price_a[formed_bar] = top1_price
            top2_price_a[formed_bar] = top2_price
            neckline_bar_a[formed_bar] = neck_true_bar
            neckline_price_a[formed_bar] = neck_price
            last_consumed_bar = formed_bar
            continue

        if running_top2_bar is None:
            # 窓の中で一度も、山1の水準許容誤差内に収まる山2候補が
            # 見つからなかった - この山1は不成立(時間範囲は消費しない)。
            continue

        # 窓の中でネックライン割れが起きなかった(または割れても形が妥当
        # でなかった) - 従来通り、窓の最後の時点での最高値を山2として確定
        # し、その後のブレイク猶予(reject_bars/expire_bars)で判定する。
        top2_true_bar = running_top2_bar
        top2_price = running_top2_price
        formed_bar = win_end
        if detected_bar is None:
            # 理論上、通常経路が成立する(下のextremes_similar等が全て
            # 満たされる)なら、窓の最後のイテレーションでdetected_barも
            # 必ずセットされているはずだが、念のためのフォールバック。
            # confirm_floor未満にはできない(先読み防止、上のループ内と
            # 同じ理由)。
            detected_bar = max(formed_bar, confirm_floor)

        # この時点でneck_true_bar/neck_priceは、ループ内の「山2候補が
        # 進んだぶんだけ谷スキャンを追いつかせる」処理により、既に
        # top2_true_bar(山2の値が最後に更新されたバー)まで正しく限定
        # された値になっている(早期成立しなかった場合、山2候補の更新は
        # ここが最後のため)。

        # 形の許容誤差に使うATRは、早期成立の経路と同じく山2確定時点
        # (top2_true_bar、山2が最後に更新されたバー)のもので固定する -
        # 窓の終わり(formed_bar/win_end)まで待って評価すると、山2自体は
        # とっくに確定しているのにその後のボラティリティ変化で判定が
        # 揺れてしまう(早期成立の経路で見つかったのと同じ問題)。
        tol = _threshold(top1_price, atr_a[top2_true_bar], top_tolerance_type, top_tolerance)
        extremes_similar = abs(top2_price - top1_price) <= tol

        avg_extreme = (top1_price + top2_price) / 2
        depth_tol = _threshold(avg_extreme, atr_a[top2_true_bar], min_valley_depth_type, min_valley_depth)
        max_depth_tol = _threshold(avg_extreme, atr_a[top2_true_bar], max_valley_depth_type, max_valley_depth)
        gap = (neck_price - avg_extreme) if bullish else (avg_extreme - neck_price)
        depth_ok = depth_tol <= gap <= max_depth_tol

        trend_ok = _line_deviation_ok(top1_true_bar, top1_price, neck_true_bar, neck_price) and _line_deviation_ok(
            neck_true_bar, neck_price, top2_true_bar, top2_price
        )

        # ネックが窓の中で再判定されている場合があるので、山1より前の期間
        # との比較も再判定後の価格で確認し直す(早期成立の経路と同じ理由)。
        neck_prior_ok = prior_extreme is None or (
            (neck_price < prior_extreme) if bullish else (neck_price > prior_extreme)
        )

        if not (extremes_similar and depth_ok and trend_ok and neck_prior_ok):
            # 不成立の候補は時間範囲を「消費」しない(ユーザー報告: すぐ近くに
            # 別の正当なダブルボトムがあるのに検出されないケースを調査した
            # ところ、直前の全く無関係な候補が不成立に終わったにも関わらず、
            # その探索窓の終わり(win_end)まで次の山1候補を一切試さなく
            # なっていたことが原因だった - 不成立の候補が結果的に後続の
            # 正当な候補まで巻き込んでブロックしてしまう)。continueするだけ
            # にして、次のext_events(確定ピボット)をすぐに新しい山1候補として
            # 試す。
            continue

        interval2 = top2_true_bar - neck_true_bar
        reject_bars = interval2 * breakout_deadline_ratio_min
        expire_bars = interval2 * breakout_deadline_ratio_max
        scan_end = min(top2_true_bar + int(np.ceil(expire_bars)), n - 1)

        # 「山1or山2の高い方を超えたら無効」というヒゲ基準の事前チェックは
        # 撤去した - failed_now(終値+余白ベース、下記)と同じ境界(worse_
        # extreme)を見ているのに、ヒゲはほぼ必ず終値より先に境界を超える
        # ため、このチェックが常にfailed_nowより先に発火してしまい、通常
        # 経路のfailedが実質的に一度も成立できなくなっていた(リテスト有無
        # の判定を追加した際に発覚 - ヒゲでの無効化をやめた「髭がネックを
        # 超えてもダブルボトム継続にして」の要望と同じ理由で、山1/山2側も
        # 終値ベースのfailed_nowだけで判定する)。

        first_trigger_bar = None
        first_trigger_kind = None
        # 山2確定後、一度でもネック付近(ブレイク判定の余白と同じ基準)まで
        # 価格が戻ってきたら「リテスト」成立とみなす(ユーザー要望:「Failed
        # After Retest」と「Failed Before Retest」を分ける基準として、
        # ブレイク余白[ATR倍率]と同じ基準を流用)。最終的にfailedで決着した
        # 時、この時点までにリテストが起きていたかどうかで2状態に分ける。
        retested = False
        for j in range(top2_true_bar + 1, scan_end + 1):
            buf = atr_a[j] * breakout_buffer
            if bullish:
                breakdown_price = high_a[j] if breakout_type == "high" else close_a[j]
                resolve_now = breakdown_price > (neck_price + buf)
                worse_extreme = max(top1_price, top2_price)
                failed_now = close_a[j] < (worse_extreme - buf)
                # 「ネック付近」＝ネック±ブレイク余白(ユーザー要望「ブレイク
                # 余白と同じ基準ならネック＋αになるよね？ネック±αにしたい」
                # - 以前はneck-buf以上を無条件でリテスト扱いにしており、
                # ネックを遥かに超えて突き抜けた場合もリテスト成立に
                # なってしまっていた)。
                near_neck_now = (neck_price - buf) <= high_a[j] <= (neck_price + buf)
            else:
                breakdown_price = low_a[j] if breakout_type == "low" else close_a[j]
                resolve_now = breakdown_price < (neck_price - buf)
                worse_extreme = min(top1_price, top2_price)
                failed_now = close_a[j] > (worse_extreme + buf)
                near_neck_now = (neck_price - buf) <= low_a[j] <= (neck_price + buf)
            if j < confirm_floor:
                # 山1・ネックのどちらかがまだ未確定 - リテスト判定・ブレイク
                # 判定とも、ここではまだ評価しない(先読み防止、上のループと
                # 同じ理由)。
                continue
            if near_neck_now:
                retested = True
            # ヒゲだけがネックを越えて終値がまだ戻っている間は無効にしない
            # (ユーザー要望「髭がネックを超えてもダブルボトム継続にして」) -
            # resolve_now/failed_now(判定基準breakout_typeで選んだ価格)が
            # 実際に成立するまで、形成中(exists)のまま待つ。
            if resolve_now or failed_now:
                first_trigger_bar = j
                first_trigger_kind = "resolve" if resolve_now else "failed"
                break

        if (
            first_trigger_bar is not None
            and first_trigger_kind == "resolve"
            and (first_trigger_bar - top2_true_bar) >= reject_bars
        ):
            # 山2とエントリーポイント(実際に発火するバー)を直線で結んだ時、
            # その間の高値/安値が直線からtrendline_tolerance_pct%(2点間の
            # 値幅に対する割合)以上乖離したら無効(ユーザー要望「山2と
            # エントリーポイントを直線で結んだとき...乖離すると許容範囲
            # 外」) - 早すぎ判定を通過したものだけ対象にする(早すぎ無効は
            # このあとの分岐でも判定されるため、ここでは形の良し悪しだけ
            # 見る)。この区間はConfirmed(resolve)の時だけ判定する(ユーザー
            # 要望:「山2→エントリー(Confirmedのみ)」- Failedにはエントリー
            # 価格という概念自体が無いため)。
            fire_bar_candidate = max(first_trigger_bar, formed_bar)
            if bullish:
                entry_price = high_a[fire_bar_candidate] if breakout_type == "high" else close_a[fire_bar_candidate]
            else:
                entry_price = low_a[fire_bar_candidate] if breakout_type == "low" else close_a[fire_bar_candidate]
            if not _line_deviation_ok(top2_true_bar, top2_price, fire_bar_candidate, float(entry_price)):
                # 山1→ネック→山2(①②)は妥当でもこの区間(③)の形が悪い場合、
                # Confirmedにはしない。ただしDetectedは既に②の時点で成立
                # しているため、候補ごと握りつぶさず「有効な決着が一度も
                # 起きなかった」= Expiredとして扱う(ユーザー選択:
                # 「Expiredとして扱う(推奨)」)。first_trigger自体を無かった
                # ことにすれば、この下のif/elif/else分岐がそのままExpired
                # ルートに落ちる。
                first_trigger_bar = None
                first_trigger_kind = None

        # 山1/山2/ネックラインのスナップショットはformed_bar(=このパターンが
        # 出揃ったバー)1点にだけ書く - api_server.py::_compute_pattern_
        # markersは「事象が起きたバー→formed_barを引く→formed_barの位置で
        # top1_bar等を読む」という2段引きをする作りなので、formed_barと
        # 同じ場所に置かないと(以前fire_barに置いていた時のように)読めない
        # バグになる(実際に発生: resolve自体は成立してもマーカーが1件も
        # 出ない不具合)。formed_bar自体は、パターンが「生きている」全バー
        # (exists区間・fire_bar含む)に同じ値を書き込み、どのバーからでも
        # このformed_barを引けるようにする。
        if first_trigger_bar is None:
            # 猶予本数以内にブレイクが一度も起きなかった - 形成中(exists)
            # のまま猶予切れで終わる。exists自体は本物の出力なのでそのまま
            # 書き込むが、次の山1候補を試せるようになるのは山1/谷/山2の
            # 3点が出揃った時点(formed_bar)まででよい - 猶予切れ(exists_end)
            # まで待たせると、判定不能なまま終わった候補が、近くにある
            # 別の正当な候補まで巻き込んでブロックしてしまう(前述と同じ
            # 理由)。
            exists_end = min(top2_true_bar + int(expire_bars), n - 1)
            exists_a[detected_bar : exists_end + 1] = True
            formed_bar_a[detected_bar : exists_end + 1] = formed_bar
            detected_a[detected_bar] = True
            expired_a[exists_end] = True
            top1_bar_a[formed_bar] = top1_true_bar
            top2_bar_a[formed_bar] = top2_true_bar
            top1_price_a[formed_bar] = top1_price
            top2_price_a[formed_bar] = top2_price
            neckline_bar_a[formed_bar] = neck_true_bar
            neckline_price_a[formed_bar] = neck_price
            last_consumed_bar = formed_bar
        elif (first_trigger_bar - top2_true_bar) < reject_bars:
            # 早すぎるブレイク - このダブルトップ自体を無効とする(ユーザー
            # 要望「(ネックから山2までの本数)×0.5以内にネックラインを
            # 下抜けたときはダブルトップとみなさない」)。exists/resolve/
            # failedのいずれも立てない。不成立なので時間範囲を消費しない
            # (前述と同じ理由)。
            pass
        else:
            fire_bar = max(first_trigger_bar, formed_bar)
            exists_a[detected_bar : fire_bar + 1] = True
            formed_bar_a[detected_bar : fire_bar + 1] = formed_bar
            detected_a[detected_bar] = True
            if first_trigger_kind == "resolve":
                resolve_a[fire_bar] = True
            else:
                failed_a[fire_bar] = True
                if retested:
                    failed_after_retest_a[fire_bar] = True
                else:
                    failed_before_retest_a[fire_bar] = True
            top1_bar_a[formed_bar] = top1_true_bar
            top2_bar_a[formed_bar] = top2_true_bar
            top1_price_a[formed_bar] = top1_price
            top2_price_a[formed_bar] = top2_price
            neckline_bar_a[formed_bar] = neck_true_bar
            neckline_price_a[formed_bar] = neck_price
            last_consumed_bar = fire_bar

    exists_series = pd.Series(exists_a, index=idx_index)
    resolve_series = pd.Series(resolve_a, index=idx_index)
    return {
        "exists": exists_series,
        "resolve": resolve_series,
        "failed": pd.Series(failed_a, index=idx_index),
        # EA Studio的な5状態モデル(ユーザー要望:「チャートパターンは基本的
        # にはすべてこの運用にする」)。
        # - detected: 谷2候補が最初に見つかった瞬間(窓の途中でも良い)。
        #   ユーザー仕様⑤「最初に谷2候補が見つかったタイミングで、
        #   『Detected』とする」- existsの立ち上がりより前に来ることがある。
        # - confirmed: ネックラインを実際に突破した瞬間(=resolveと同じ)。
        # - failed_after_retest/failed_before_retest: 山2確定後、決着(失敗)
        #   までの間に一度でもネック付近(ブレイク余白と同じ基準)まで価格が
        #   戻ってきていればafter、一度も戻らないまま失敗すればbefore。
        #   即成立(early exit)経路はリテストする時間的余地が無いため常に
        #   before扱い。
        # - expired: 猶予切れで決着がつかないまま終わった瞬間。
        "detected": pd.Series(detected_a, index=idx_index),
        "confirmed": resolve_series,
        "failed_after_retest": pd.Series(failed_after_retest_a, index=idx_index),
        "failed_before_retest": pd.Series(failed_before_retest_a, index=idx_index),
        "expired": pd.Series(expired_a, index=idx_index),
        # 「このバーで確定した2つの山/谷はどのバーだったか」- チャート上に
        # 実際にエントリーへ使われた山/谷だけを印付けたい(汎用のピボット
        # 全表示だと多すぎて分かりにくいというユーザー要望)ためのもので、
        # resolve/failed/existsの判定自体には使わない副産物の情報。
        "top1_bar": pd.Series(top1_bar_a, index=idx_index),
        "top2_bar": pd.Series(top2_bar_a, index=idx_index),
        "top1_price": pd.Series(top1_price_a, index=idx_index),
        # ネックライン(2つの山/谷の間の谷/山)- 山/谷どうしの近さだけでなく
        # 「その間がどれだけ深く/高く離れているか」の判定にも、ブレイクの
        # 基準ラインにも使われる、パターン成立に不可欠な第3の点。
        "neckline_bar": pd.Series(neckline_bar_a, index=idx_index),
        "neckline_price": pd.Series(neckline_price_a, index=idx_index),
        "top2_price": pd.Series(top2_price_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
    }


def double_top_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """ダブルトップのネックライン割れ(ショート方向のシグナル) - 厳密仕様版
    (ユーザー提供の仕様書通りに実装)。以前の簡易版(2つのスイング高値の水準
    が近ければ即成立、山の間隔にもブレイクまでの期間にも制限なし)は
    ユーザー報告:「ダブルトップのエントリーが全然ダブルトップに見えない」
    の原因だった。判定フローは_double_top_bottom_stateのdocstring参照。"""
    state = _double_top_bottom_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, False,
        max_valley_depth_type, max_valley_depth,
    )
    return state["resolve"].to_numpy(dtype=float)


def double_top_failed(
    high: pd.Series, low: pd.Series, close: pd.Series,
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """ダブルトップ不成立(ロング方向のシグナル) - ネックライン割れが起きる
    前に、終値が両トップの高い方+breakout_bufferを上抜けた瞬間に成立する
    (ユーザー要望の「Double Top Failed」と「Double Top Top Break Up」を
    1つに統合したもの - 「ネックラインを割らず、終値が高値レベルを上抜け」
    という同一の価格イベントを指すとユーザーに確認済み)。弱気の反転シナリオ
    が否定された、という意味でロングエントリー候補になる。"""
    state = _double_top_bottom_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, False,
        max_valley_depth_type, max_valley_depth,
    )
    return state["failed"].to_numpy(dtype=float)


def double_top_exists(
    high: pd.Series, low: pd.Series, close: pd.Series,
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """ダブルトップ形成中(方向を持たない状態フィルター) - 2つのトップが
    確定してから、ネックライン割れ/Failed成立/猶予本数超過のいずれかで
    決着するまでの間、常にTrueであり続ける(ユーザー要望:「パターン自体は
    方向を持たない検出結果として扱い、その後のシグナルで売買方向を決定
    できるようにしたい」- 例: 「ロング禁止フィルター」としての利用)。"""
    state = _double_top_bottom_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, False,
        max_valley_depth_type, max_valley_depth,
    )
    return state["exists"].to_numpy(dtype=float)


# EA Studio的な5状態モデル(Detected/Confirmed/Failed After Retest/Failed
# Before Retest/Expired)を1つの指標のパラメータ選択でまとめて選べるように
# したもの(ユーザー要望:「チャートパターンは基本的にはすべてこの運用に
# する...エントリー条件を選ぶ際は「チャートパターン」→「ダブルボトム」を
# 選択。「ダブルボトム」内のパラメーター選択で状態を選べるように」)。
# double_top_breakdown/failed/existsは既存の保存済みストラテジーとの互換性
# のためそのまま残し、こちらは新しい選び方として追加する(置き換えでは
# ない)。ダブルボトムは他のチャートパターンへ展開する前段の実装として、
# まずこの2つ(ダブルトップ/ダブルボトム)だけに適用する。
_PATTERN_STATE_KEYS = {
    "detected": "detected",
    "confirmed": "confirmed",
    "failed_after_retest": "failed_after_retest",
    "failed_before_retest": "failed_before_retest",
    "expired": "expired",
}


def double_top(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """ダブルトップ - Detected/Confirmed/Failed After Retest/Failed Before
    Retest/Expiredの5状態をstateパラメータで選べる統合版(EA Studio的な
    パターンのライフサイクル管理)。判定フローは_double_top_bottom_stateの
    docstring参照。"""
    result = _double_top_bottom_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, False,
        max_valley_depth_type, max_valley_depth,
    )
    key = _PATTERN_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def double_top_pivot(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """ダブルトップ(谷2ピボット版) - double_topと全く同じ5状態モデルだが、
    山2の探索方法だけが違う(ユーザー要望:「谷2の探索方法をピボット安値
    バージョンで別に実装して。今の構造はそのまま別に残して」)。double_top
    は「窓の中で山1に近い最高値」を山2として採用するのに対し、こちらは
    「窓の中の本物のピボット高値(山1・仮点と同じ判定基準)」だけを山2候補
    にする、一般的なチャートパターン認識ツールにより近い方式。既存の
    double_topはこの関数と無関係に一切変更していない。"""
    result = _double_top_bottom_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, True,
        max_valley_depth_type, max_valley_depth,
    )
    key = _PATTERN_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def double_bottom_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """Mirror image of double_top_breakdown - ネックライン(直近の確定
    スイング高値)を上抜けた瞬間(ロング方向のシグナル)。"""
    state = _double_top_bottom_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, False,
        max_valley_depth_type, max_valley_depth,
    )
    return state["resolve"].to_numpy(dtype=float)


def double_bottom_failed(
    high: pd.Series, low: pd.Series, close: pd.Series,
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """Mirror image of double_top_failed - ネックライン上抜けが起きる前に、
    終値が両ボトムの低い方-breakout_bufferを下抜けた瞬間(ショート方向の
    シグナル、強気の反転シナリオが否定された)。"""
    state = _double_top_bottom_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, False,
        max_valley_depth_type, max_valley_depth,
    )
    return state["failed"].to_numpy(dtype=float)


def double_bottom_exists(
    high: pd.Series, low: pd.Series, close: pd.Series,
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """Mirror image of double_top_exists - ダブルボトム形成中(方向を持たない
    状態フィルター)。"""
    state = _double_top_bottom_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, False,
        max_valley_depth_type, max_valley_depth,
    )
    return state["exists"].to_numpy(dtype=float)


def double_bottom(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """Mirror image of double_top - ダブルボトムの5状態統合版(Detected/
    Confirmed/Failed After Retest/Failed Before Retest/Expired)。"""
    result = _double_top_bottom_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, False,
        max_valley_depth_type, max_valley_depth,
    )
    key = _PATTERN_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def double_bottom_pivot(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 15,
    pivot_right_bars: int = 15,
    min_bars_between_tops: int = 10,
    max_bars_between_tops: int = 80,
    top_tolerance_type: str = "atr",
    top_tolerance: float = 0.5,
    min_valley_depth_type: str = "atr",
    min_valley_depth: float = 1.0,
    symmetry_ratio_min: float = 0.5,
    symmetry_ratio_max: float = 1.67,
    trendline_tolerance_pct: float = 80.0,
    breakout_type: str = "close",
    breakout_buffer: float = 0.1,
    breakout_deadline_ratio_min: float = 0.5,
    breakout_deadline_ratio_max: float = 1.67,
    pip_size: float = 0.0001,
    neck_prior_check_enabled: bool = True,
    neck_prior_lookback_ratio: float = 3.0,
    max_valley_depth_type: str = "atr",
    max_valley_depth: float = 999.0,
    **p,
) -> np.ndarray:
    """Mirror image of double_top_pivot - ダブルボトム(谷2ピボット版)。
    既存のdouble_bottomはこの関数と無関係に一切変更していない。"""
    result = _double_top_bottom_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, min_bars_between_tops, max_bars_between_tops,
        top_tolerance_type, top_tolerance, min_valley_depth_type, min_valley_depth,
        symmetry_ratio_min, symmetry_ratio_max, trendline_tolerance_pct,
        breakout_type, breakout_buffer, breakout_deadline_ratio_min, breakout_deadline_ratio_max, pip_size,
        neck_prior_check_enabled, neck_prior_lookback_ratio, True,
        max_valley_depth_type, max_valley_depth,
    )
    key = _PATTERN_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def triple_top_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Three swing highs all at a similar level."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1, lh2 = (_nth_back_level(swing_high, n) for n in (0, 1, 2))
    bh0 = _nth_back_bar_index(swing_high)
    bar_index = pd.Series(np.arange(len(high)), index=high.index)

    formed = (
        (bar_index == bh0)
        & _similar(lh0, lh1, atr_values, tolerance_atr_mult)
        & _similar(lh1, lh2, atr_values, tolerance_atr_mult)
    )
    neckline = _nth_back_level(swing_low, 0)
    breakdown = close < neckline
    return _first_occurrence_after(formed, breakdown)


def triple_bottom_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Mirror image of triple_top_breakdown."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    ll0, ll1, ll2 = (_nth_back_level(swing_low, n) for n in (0, 1, 2))
    bl0 = _nth_back_bar_index(swing_low)
    bar_index = pd.Series(np.arange(len(low)), index=low.index)

    formed = (
        (bar_index == bl0)
        & _similar(ll0, ll1, atr_values, tolerance_atr_mult)
        & _similar(ll1, ll2, atr_values, tolerance_atr_mult)
    )
    neckline = _nth_back_level(swing_high, 0)
    breakout = close > neckline
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Head & Shoulders
# ---------------------------------------------------------------------------

def head_and_shoulders_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, shoulder_tolerance_atr_mult: float = 0.75, head_margin_atr_mult: float = 0.5,
) -> np.ndarray:
    """Three swing highs: a middle "head" clearly above two similar-level
    "shoulders", confirmed as the right shoulder completes. Neckline
    approximated as the most recently confirmed swing low (a flat line,
    unlike the textbook's slanted neckline connecting the two troughs)."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    right_shoulder, head, left_shoulder = (_nth_back_level(swing_high, n) for n in (0, 1, 2))
    bh0 = _nth_back_bar_index(swing_high)
    bar_index = pd.Series(np.arange(len(high)), index=high.index)

    head_margin = atr_values * head_margin_atr_mult
    head_is_highest = (head > right_shoulder + head_margin) & (head > left_shoulder + head_margin)
    shoulders_similar = _similar(right_shoulder, left_shoulder, atr_values, shoulder_tolerance_atr_mult)
    formed = (bar_index == bh0) & head_is_highest & shoulders_similar
    neckline = _nth_back_level(swing_low, 0)
    breakdown = close < neckline
    return _first_occurrence_after(formed, breakdown)


def inverse_head_and_shoulders_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, shoulder_tolerance_atr_mult: float = 0.75, head_margin_atr_mult: float = 0.5,
) -> np.ndarray:
    """Mirror image of head_and_shoulders_breakdown."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    right_shoulder, head, left_shoulder = (_nth_back_level(swing_low, n) for n in (0, 1, 2))
    bl0 = _nth_back_bar_index(swing_low)
    bar_index = pd.Series(np.arange(len(low)), index=low.index)

    head_margin = atr_values * head_margin_atr_mult
    head_is_lowest = (head < right_shoulder - head_margin) & (head < left_shoulder - head_margin)
    shoulders_similar = _similar(right_shoulder, left_shoulder, atr_values, shoulder_tolerance_atr_mult)
    formed = (bar_index == bl0) & head_is_lowest & shoulders_similar
    neckline = _nth_back_level(swing_high, 0)
    breakout = close > neckline
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Triangles & Wedges
# ---------------------------------------------------------------------------

def ascending_triangle_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, flat_tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Flat resistance (last two swing highs similar) + rising support
    (swing lows climbing) - a bullish continuation setup. Fires on the
    breakout above resistance."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)

    state = _similar(lh0, lh1, atr_values, flat_tolerance_atr_mult) & (ll0 > ll1)
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


def descending_triangle_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, flat_tolerance_atr_mult: float = 0.5,
) -> np.ndarray:
    """Mirror image of ascending_triangle_breakout: flat support + falling
    resistance, fires on the breakdown below support."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)

    state = _similar(ll0, ll1, atr_values, flat_tolerance_atr_mult) & (lh0 < lh1)
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


def _symmetrical_triangle_state(high: pd.Series, low: pd.Series, swing_lookback: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    state = (lh0 < lh1) & (ll0 > ll1)
    return state, lh0, ll0


def symmetrical_triangle_breakout_bullish(high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5) -> np.ndarray:
    """Converging swing highs (falling) and swing lows (rising) - fires on
    an upside break out of the apex."""
    state, lh0, _ll0 = _symmetrical_triangle_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


def symmetrical_triangle_breakout_bearish(high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5) -> np.ndarray:
    """Same converging shape as symmetrical_triangle_breakout_bullish, but
    fires on a downside break instead - a symmetrical triangle is
    direction-agnostic until it actually breaks."""
    state, _lh0, ll0 = _symmetrical_triangle_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


def rising_wedge_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5,
) -> np.ndarray:
    """Both swing highs AND swing lows rising, but the channel is
    narrowing (a shrinking high-low spread despite the overall upward
    drift) - a bearish reversal setup, fires on the breakdown below
    support."""
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)

    both_rising = (lh0 > lh1) & (ll0 > ll1)
    narrowing = (lh0 - ll0).abs() < (lh1 - ll1).abs()
    state = both_rising & narrowing
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


def falling_wedge_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5,
) -> np.ndarray:
    """Mirror image of rising_wedge_breakdown: both swing highs and lows
    falling, but narrowing - bullish reversal, fires on breakout above
    resistance."""
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)

    both_falling = (lh0 < lh1) & (ll0 < ll1)
    narrowing = (lh0 - ll0).abs() < (lh1 - ll1).abs()
    state = both_falling & narrowing
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Flags & Pennants: a sharp impulse move, then a brief consolidation, then
# a breakout continuing the impulse's direction. ATR-normalized so the
# impulse/consolidation thresholds are comparable across symbols/timeframes.
# ---------------------------------------------------------------------------

def _flag_or_pennant(
    high: pd.Series, low: pd.Series, close: pd.Series,
    is_bullish: bool, require_narrowing: bool,
    impulse_lookback: int, impulse_atr_mult: float,
    consolidation_window: int, consolidation_atr_mult: float,
) -> np.ndarray:
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)

    if is_bullish:
        impulse = (close - close.shift(impulse_lookback)) / atr_values >= impulse_atr_mult
    else:
        impulse = (close - close.shift(impulse_lookback)) / atr_values <= -impulse_atr_mult
    impulse_recently = impulse.fillna(False).rolling(consolidation_window).max().shift(1).fillna(0) > 0

    consolidation_high = high.rolling(consolidation_window).max()
    consolidation_low = low.rolling(consolidation_window).min()
    consolidation_range = consolidation_high - consolidation_low
    is_narrow = consolidation_range <= atr_values * consolidation_atr_mult

    if require_narrowing:
        half = max(consolidation_window // 2, 1)
        first_half_range = high.rolling(half).max().shift(half) - low.rolling(half).min().shift(half)
        second_half_range = high.rolling(half).max() - low.rolling(half).min()
        is_narrow = is_narrow & (second_half_range < first_half_range)

    state = impulse_recently & is_narrow
    formed = _rising_edge(state)

    # Breakout level must exclude the current bar (shift(1)) - otherwise
    # "close > consolidation_high" can never be true, since the rolling
    # max already includes this same bar's own high (close <= high always).
    # Same no-lookahead convention as derived_indicators.py's
    # _highest_high_level.
    if is_bullish:
        trigger = close > consolidation_high.shift(1)
    else:
        trigger = close < consolidation_low.shift(1)
    return _first_occurrence_after(formed, trigger)


def bull_flag_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    impulse_lookback: int = 10, impulse_atr_mult: float = 3.0,
    consolidation_window: int = 10, consolidation_atr_mult: float = 2.0,
) -> np.ndarray:
    return _flag_or_pennant(
        high, low, close, is_bullish=True, require_narrowing=False,
        impulse_lookback=impulse_lookback, impulse_atr_mult=impulse_atr_mult,
        consolidation_window=consolidation_window, consolidation_atr_mult=consolidation_atr_mult,
    )


def bear_flag_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    impulse_lookback: int = 10, impulse_atr_mult: float = 3.0,
    consolidation_window: int = 10, consolidation_atr_mult: float = 2.0,
) -> np.ndarray:
    return _flag_or_pennant(
        high, low, close, is_bullish=False, require_narrowing=False,
        impulse_lookback=impulse_lookback, impulse_atr_mult=impulse_atr_mult,
        consolidation_window=consolidation_window, consolidation_atr_mult=consolidation_atr_mult,
    )


def bullish_pennant_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    impulse_lookback: int = 10, impulse_atr_mult: float = 3.0,
    consolidation_window: int = 12, consolidation_atr_mult: float = 2.5,
) -> np.ndarray:
    """Same idea as bull_flag_breakout, but additionally requires the
    consolidation's range to be actively NARROWING (triangle-shaped)
    rather than merely staying inside a flat band."""
    return _flag_or_pennant(
        high, low, close, is_bullish=True, require_narrowing=True,
        impulse_lookback=impulse_lookback, impulse_atr_mult=impulse_atr_mult,
        consolidation_window=consolidation_window, consolidation_atr_mult=consolidation_atr_mult,
    )


def bearish_pennant_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    impulse_lookback: int = 10, impulse_atr_mult: float = 3.0,
    consolidation_window: int = 12, consolidation_atr_mult: float = 2.5,
) -> np.ndarray:
    return _flag_or_pennant(
        high, low, close, is_bullish=False, require_narrowing=True,
        impulse_lookback=impulse_lookback, impulse_atr_mult=impulse_atr_mult,
        consolidation_window=consolidation_window, consolidation_atr_mult=consolidation_atr_mult,
    )


# ---------------------------------------------------------------------------
# Range box (consolidation)
# ---------------------------------------------------------------------------

def in_range_box(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, box_atr_mult: float = 2.0) -> np.ndarray:
    """Currently consolidating: the trailing `window`-bar high-low range is
    within `box_atr_mult` ATRs - a state indicator (like bb_squeeze), not a
    one-shot event."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    box_range = high.rolling(window).max() - low.rolling(window).min()
    return (box_range <= atr_values * box_atr_mult).fillna(False).to_numpy(dtype=float)


def range_box_breakout_bullish(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, box_atr_mult: float = 2.0) -> np.ndarray:
    """Fires the FIRST bar close breaks above the box's high after the box
    ends - not necessarily the very next bar (a real breakout can take a
    few bars to actually clear the level), so this uses the same
    fire-once-per-epoch machinery as the other patterns rather than only
    checking a single bar right after the box."""
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    # The box's high must be FROZEN at the level it held while still
    # boxed, not a live rolling max - a plain `high.rolling(window).max()`
    # keeps climbing right along with an ongoing breakout (it re-includes
    # the breakout's own recent highs), so `close > box_high` would rarely
    # or never fire for a gradual breakout. `.where(boxed).ffill()` holds
    # the box's own last-known high steady once boxed turns False.
    box_high = high.rolling(window).max().where(boxed).ffill()
    box_ended = _falling_edge(boxed)
    breakout = close > box_high
    return _first_occurrence_after(box_ended, breakout)


def range_box_breakdown_bearish(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, box_atr_mult: float = 2.0) -> np.ndarray:
    """Mirror image of range_box_breakout_bullish."""
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    box_low = low.rolling(window).min().where(boxed).ffill()
    box_ended = _falling_edge(boxed)
    breakdown = close < box_low
    return _first_occurrence_after(box_ended, breakdown)


# ---------------------------------------------------------------------------
# Trendline break: a single sloped line through the last TWO swing points
# (unlike triangles/wedges, which need two CONVERGING lines) - the most
# basic price-action concept in this module. Support drawn through the
# last two swing lows, resistance through the last two swing highs.
# ---------------------------------------------------------------------------

def uptrend_line_break(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    """Support trendline through the last two swing lows (rising: the more
    recent low is higher than the one before it) - fires the first time
    close breaks below that line's extrapolated current value."""
    swing_low = _swing_low_levels(low, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0, bl1 = _nth_back_bar_index(swing_low, 0), _nth_back_bar_index(swing_low, 1)
    bar_position = pd.Series(np.arange(len(close)), index=close.index)

    valid_uptrend = (ll0 > ll1) & (bl0 > bl1)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (ll0 - ll1) / (bl0 - bl1)
    trendline_value = ll0 + slope * (bar_position - bl0)

    formed = _rising_edge(valid_uptrend)
    breakdown = close < trendline_value
    return _first_occurrence_after(formed, breakdown)


def downtrend_line_break(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    """Mirror image of uptrend_line_break: resistance trendline through the
    last two swing highs (falling), fires when close breaks above it."""
    swing_high = _swing_high_levels(high, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0, bh1 = _nth_back_bar_index(swing_high, 0), _nth_back_bar_index(swing_high, 1)
    bar_position = pd.Series(np.arange(len(close)), index=close.index)

    valid_downtrend = (lh0 < lh1) & (bh0 > bh1)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (lh0 - lh1) / (bh0 - bh1)
    trendline_value = lh0 + slope * (bar_position - bh0)

    formed = _rising_edge(valid_downtrend)
    breakout = close > trendline_value
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Parallel channel: same idea as uptrend/downtrend_line_break, but ALSO
# requires the opposite side (the last two swing highs for an ascending
# channel, swing lows for a descending one) to be roughly the same slope -
# distinguishing a genuine parallel channel from a wedge/triangle, which
# converge instead.
# ---------------------------------------------------------------------------

def ascending_channel_break(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, slope_tolerance_atr_mult: float = 0.02, **p,
) -> np.ndarray:
    """Support (swing lows) and resistance (swing highs) both rising at
    roughly the SAME slope (parallel, not converging) - fires when close
    breaks below the support line (the classic "channel breakdown")."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0, bl1 = _nth_back_bar_index(swing_low, 0), _nth_back_bar_index(swing_low, 1)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0, bh1 = _nth_back_bar_index(swing_high, 0), _nth_back_bar_index(swing_high, 1)
    bar_position = pd.Series(np.arange(len(close)), index=close.index)

    with np.errstate(divide="ignore", invalid="ignore"):
        support_slope = (ll0 - ll1) / (bl0 - bl1)
        resistance_slope = (lh0 - lh1) / (bh0 - bh1)
    both_rising = (ll0 > ll1) & (lh0 > lh1)
    parallel = (support_slope - resistance_slope).abs() <= atr_values * slope_tolerance_atr_mult
    state = both_rising & parallel

    support_value = ll0 + support_slope * (bar_position - bl0)
    formed = _rising_edge(state)
    breakdown = close < support_value
    return _first_occurrence_after(formed, breakdown)


def descending_channel_break(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, slope_tolerance_atr_mult: float = 0.02, **p,
) -> np.ndarray:
    """Mirror image of ascending_channel_break: fires when close breaks
    above the (falling, parallel) resistance line."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    swing_high = _swing_high_levels(high, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0, bl1 = _nth_back_bar_index(swing_low, 0), _nth_back_bar_index(swing_low, 1)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0, bh1 = _nth_back_bar_index(swing_high, 0), _nth_back_bar_index(swing_high, 1)
    bar_position = pd.Series(np.arange(len(close)), index=close.index)

    with np.errstate(divide="ignore", invalid="ignore"):
        support_slope = (ll0 - ll1) / (bl0 - bl1)
        resistance_slope = (lh0 - lh1) / (bh0 - bh1)
    both_falling = (ll0 < ll1) & (lh0 < lh1)
    parallel = (support_slope - resistance_slope).abs() <= atr_values * slope_tolerance_atr_mult
    state = both_falling & parallel

    resistance_value = lh0 + resistance_slope * (bar_position - bh0)
    formed = _rising_edge(state)
    breakout = close > resistance_value
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# False breakout ("fakey"): price breaks outside a consolidation box, then
# closes back inside it within a few bars - the failed-breakout reversal
# setup. Built on in_range_box's existing box-tracking rather than a new
# level detector.
# ---------------------------------------------------------------------------

def _false_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series, is_bullish_reversal: bool,
    window: int, box_atr_mult: float, max_bars_outside: int,
) -> np.ndarray:
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    box_high = high.rolling(window).max().where(boxed).ffill()
    box_low = low.rolling(window).min().where(boxed).ffill()
    box_ended = _falling_edge(boxed)

    if is_bullish_reversal:
        # Broke DOWN out of the box, then closed back inside it -> a
        # bullish reversal (the breakdown was a fake).
        broke_out = close < box_low
    else:
        broke_out = close > box_high

    epoch = box_ended.cumsum()
    broke_out_in_epoch = broke_out.fillna(False) & (epoch > 0) & ~box_ended
    back_inside = (close >= box_low) & (close <= box_high)

    # First bar back inside the box after having broken out, within
    # `max_bars_outside` bars of the break - a return that took longer
    # than that doesn't read as a prompt "fakey" reversal anymore.
    was_outside_recently = broke_out_in_epoch.rolling(max_bars_outside, min_periods=1).max().shift(1).fillna(0) > 0
    reversal_bar = back_inside & was_outside_recently & (epoch > 0)

    reversal_count_in_epoch = reversal_bar.groupby(epoch).cumsum()
    fired = reversal_bar & (reversal_count_in_epoch == 1)
    return fired.fillna(False).to_numpy(dtype=float)


def false_breakout_bullish_reversal(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, box_atr_mult: float = 2.0, max_bars_outside: int = 3, **p,
) -> np.ndarray:
    return _false_breakout(high, low, close, True, window, box_atr_mult, max_bars_outside)


def false_breakout_bearish_reversal(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, box_atr_mult: float = 2.0, max_bars_outside: int = 3, **p,
) -> np.ndarray:
    return _false_breakout(high, low, close, False, window, box_atr_mult, max_bars_outside)


# ---------------------------------------------------------------------------
# Saucer top/bottom (rounding reversal) - a smooth curved extreme rather
# than a sharp spike, detected via a rolling quadratic fit (np.polyfit
# degree 2 per window - O(n*window), same cost class already accepted for
# CCI's rolling mean-absolute-deviation). Concavity alone isn't enough (a
# plain V-shaped reversal also fits a downward/upward parabola loosely) -
# also require the fitted extremum to land roughly in the MIDDLE of the
# window, confirming a genuinely rounded arc rather than a sharp corner
# near one edge.
# ---------------------------------------------------------------------------

def _quadratic_concavity(y: pd.Series, window: int) -> np.ndarray:
    def fit(arr: np.ndarray) -> float:
        x = np.arange(len(arr), dtype=float)
        a, _b, _c = np.polyfit(x, arr, 2)
        return a
    return y.rolling(window).apply(fit, raw=True).to_numpy(dtype=float)


def _extremum_position_fraction(y: pd.Series, window: int, is_max: bool) -> np.ndarray:
    fn = (lambda arr: np.argmax(arr)) if is_max else (lambda arr: np.argmin(arr))
    position = y.rolling(window).apply(fn, raw=True)
    return (position / (window - 1)).to_numpy(dtype=float)


def _rounding_state(close: pd.Series, window: int, is_top: bool) -> np.ndarray:
    concavity = _quadratic_concavity(close, window)
    position_fraction = _extremum_position_fraction(close, window, is_max=is_top)
    concave = concavity < 0 if is_top else concavity > 0
    centered = (position_fraction >= 0.3) & (position_fraction <= 0.7)
    return concave & centered


def saucer_top(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 30, **p) -> np.ndarray:
    """Currently forming a smooth, rounded top - a state indicator (like
    in_range_box), not a one-shot breakout event."""
    return np.nan_to_num(_rounding_state(close, int(window), True), nan=0.0).astype(float)


def saucer_bottom(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 30, **p) -> np.ndarray:
    """Mirror image of saucer_top: a smooth, rounded bottom."""
    return np.nan_to_num(_rounding_state(close, int(window), False), nan=0.0).astype(float)


# ---------------------------------------------------------------------------
# Ascending/Descending Rectangle - same flat-box shape as in_range_box, but
# specifically requires a prior TREND leading into the box (a continuation
# setup) and fires only on the breakout that continues that trend
# direction - distinguishing it from a plain range_box, which is
# direction-agnostic about what came before it.
# ---------------------------------------------------------------------------

def ascending_rectangle_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, box_atr_mult: float = 2.0, trend_lookback: int = 30, **p,
) -> np.ndarray:
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    box_high = high.rolling(window).max().where(boxed).ffill()
    box_ended = _falling_edge(boxed)

    prior_uptrend = close.shift(window) > close.shift(window + trend_lookback)
    formed = box_ended & prior_uptrend.fillna(False)
    breakout = close > box_high
    return _first_occurrence_after(formed, breakout)


def descending_rectangle_breakdown(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, box_atr_mult: float = 2.0, trend_lookback: int = 30, **p,
) -> np.ndarray:
    """Mirror image of ascending_rectangle_breakout: a box preceded by a
    downtrend, fires on the breakdown continuing it."""
    boxed = pd.Series(in_range_box(high, low, close, window, box_atr_mult), index=high.index) > 0
    box_low = low.rolling(window).min().where(boxed).ffill()
    box_ended = _falling_edge(boxed)

    prior_downtrend = close.shift(window) < close.shift(window + trend_lookback)
    formed = box_ended & prior_downtrend.fillna(False)
    breakdown = close < box_low
    return _first_occurrence_after(formed, breakdown)


# ---------------------------------------------------------------------------
# Broadening Formation (Megaphone) - the mirror image of a symmetrical
# triangle: swing highs rising AND swing lows falling (diverging instead of
# converging). Direction-agnostic until it actually breaks, same as the
# symmetrical triangle above.
# ---------------------------------------------------------------------------

def _broadening_state(high: pd.Series, low: pd.Series, swing_lookback: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    state = (lh0 > lh1) & (ll0 < ll1)
    return state, lh0, ll0


def broadening_formation_breakout_bullish(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    state, lh0, _ll0 = _broadening_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


def broadening_formation_breakout_bearish(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    state, _lh0, ll0 = _broadening_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


# ---------------------------------------------------------------------------
# Diamond Formation - broadening (diverging swing highs/lows) followed by
# narrowing (converging) - the two-phase combination of the broadening
# formation above and a symmetrical triangle, checked via 3 trailing swing
# highs/lows (the earlier pair diverging, the later pair converging).
# ---------------------------------------------------------------------------

def _diamond_state(high: pd.Series, low: pd.Series, swing_lookback: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    swing_high = _swing_high_levels(high, swing_lookback)
    swing_low = _swing_low_levels(low, swing_lookback)
    lh0, lh1, lh2 = (_nth_back_level(swing_high, n) for n in (0, 1, 2))
    ll0, ll1, ll2 = (_nth_back_level(swing_low, n) for n in (0, 1, 2))

    earlier_broadening = (lh1 > lh2) & (ll1 < ll2)
    later_narrowing = (lh0 < lh1) & (ll0 > ll1)
    state = earlier_broadening & later_narrowing
    return state, lh0, ll0


def diamond_formation_breakout_bullish(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    state, lh0, _ll0 = _diamond_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakout = close > lh0
    return _first_occurrence_after(formed, breakout)


def diamond_formation_breakout_bearish(
    high: pd.Series, low: pd.Series, close: pd.Series, swing_lookback: int = 5, **p,
) -> np.ndarray:
    state, _lh0, ll0 = _diamond_state(high, low, swing_lookback)
    formed = _rising_edge(state)
    breakdown = close < ll0
    return _first_occurrence_after(formed, breakdown)


# ---------------------------------------------------------------------------
# Cup with Handle - a rounding bottom (the "cup", reusing saucer_bottom's
# quadratic-fit detector) followed by a brief, narrow consolidation near
# the cup's rim (the "handle", reusing in_range_box's ATR-scaled
# narrowness check over a shorter window) - fires on the breakout above
# the handle.
# ---------------------------------------------------------------------------

def cup_with_handle_breakout(
    high: pd.Series, low: pd.Series, close: pd.Series,
    cup_window: int = 40, handle_window: int = 10, handle_atr_mult: float = 1.5, **p,
) -> np.ndarray:
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)

    cup_state = pd.Series(_rounding_state(close, cup_window, is_top=False), index=close.index) > 0
    # Same "did X happen within the trailing window" trick as
    # _flag_or_pennant's `impulse_recently` - the cup must have completed
    # BEFORE the handle (shift(handle_window)), not overlap with it.
    cup_happened_recently = cup_state.shift(handle_window).rolling(cup_window).max().fillna(0) > 0

    handle_range = high.rolling(handle_window).max() - low.rolling(handle_window).min()
    is_handle = handle_range <= atr_values * handle_atr_mult

    state = cup_happened_recently & is_handle
    formed = _rising_edge(state)
    handle_high = high.rolling(handle_window).max().where(is_handle).ffill()
    breakout = close > handle_high
    return _first_occurrence_after(formed, breakout)


# ---------------------------------------------------------------------------
# Equal High / Equal Low (ICT用語の「流動性プール」) - 直近2つの確定スイング
# 高値(安値)がほぼ同じ水準に並んでいる状態。double_top_breakdown等と同じ
# ATR許容誤差の仕組みをそのまま再利用(ネックライン突破の確認は不要、
# 2点が並んだ時点で成立)。
# ---------------------------------------------------------------------------

def equal_high(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.3, **p,
) -> np.ndarray:
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_high = _swing_high_levels(high, swing_lookback)
    lh0, lh1 = _nth_back_level(swing_high, 0), _nth_back_level(swing_high, 1)
    bh0 = _nth_back_bar_index(swing_high)
    bar_index = pd.Series(np.arange(len(high)), index=high.index)
    formed = (bar_index == bh0) & _similar(lh0, lh1, atr_values, tolerance_atr_mult)
    return formed.fillna(False).to_numpy(dtype=float)


def equal_low(
    high: pd.Series, low: pd.Series, close: pd.Series,
    swing_lookback: int = 5, tolerance_atr_mult: float = 0.3, **p,
) -> np.ndarray:
    """Mirror image of equal_high, for swing lows."""
    atr_values = _atr_series(pd.DataFrame({"high": high, "low": low, "close": close}), 14)
    swing_low = _swing_low_levels(low, swing_lookback)
    ll0, ll1 = _nth_back_level(swing_low, 0), _nth_back_level(swing_low, 1)
    bl0 = _nth_back_bar_index(swing_low)
    bar_index = pd.Series(np.arange(len(low)), index=low.index)
    formed = (bar_index == bl0) & _similar(ll0, ll1, atr_values, tolerance_atr_mult)
    return formed.fillna(False).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Double Top/Bottom (形状判定版・2026-07-25) - "本物のW字/M字か"をより厳密に
# 判定する再設計版。既存のdouble_top/double_bottom/double_top_pivot/
# double_bottom_pivotとは完全に独立した、別のロジック・別の指標として追加
# (既存のものには一切手を加えていない)。ユーザーとの設計レビューで固まった
# 仕様をそのまま実装している:
#
#   ①山1(bullish=Falseなら谷1、以下山1で統一)の検出: 左右pivot_left_bars/
#     pivot_right_bars本より高い(安い)、かつ左右の境界の安値(高値)より
#     ATR×prominence_atr_mult以上高い(低い) - 単なる順位だけでなく、値幅
#     そのものを問う「本物の反発」基準(ユーザー指摘:「0.1Pipsとかでも安け
#     ればそれがピボット安値になっちゃう、それは反発とは言えない」)。
#   ②山1前のトレンド確認(pre_trend_lookback_barsまたはpre_trend_atr_multが
#     0なら無効、両方とも0より大きければ有効): 山1の価格が、その手前
#     pre_trend_lookback_bars本の価格よりATR×pre_trend_atr_mult以上高い
#     (低い)こと。100件サンプルチェックで見つかった「谷1がゆるい上昇トレ
#     ンドの起点に過ぎない」崩れ方への対策。
#   ③ネックライン: 山1より後、山2が確定するまでの間に出た、①と同じ基準
#     (逆方向)を満たす本物のピボットのうち一番低い(高い)もの - 新しい
#     ピボットが出るたびに更新されるが、既に選んだネックの探索窓を過ぎて
#     からの後出しピボットは採用しない(そのネックではもう山2を探せない
#     ため無意味)。
#   ④山1→ネックの間隔(interval1)がmin_bars_between_tops〜
#     max_bars_between_topsの範囲内。
#   ⑤山2の探索窓 = ネックからinterval1×symmetry_ratio_min〜
#     symmetry_ratio_max本の範囲。
#   ⑥⑦山2候補: 窓の中で①と同じ基準(値幅込みの本物のピボット)を満たし、
#     かつ山1との価格差がATR×top_tolerance_atr_mult以内のバーのうち、
#     時系列で最後に見つかったもの(「条件を満たす最新の候補で更新」 -
#     複雑な極値追跡はせず、単純に上書きしていく)。窓の中で山1の水準を
#     許容誤差を超えて突き抜ける値が一度でも出たら、その時点でこの山1
#     候補ごと不成立にする(ユーザー判断:「許容範囲外の安値が出たらそれは
#     もうダブルボトムじゃない」)。
#   ⑧谷(山)の深さ: ネックライン−(山1・山2の平均、絶対値)がATR×
#     min_valley_depth_atr_mult以上・ATR×max_valley_depth_atr_mult以下。
#   ⑨山1前点: ネックが確定した時点で山1より過去に遡り、安値≦
#     (ネック∓余白)≦高値を満たす、山1に一番近い(直近の)バーを探す。
#     この点の価格はそのバー自身のOHLCではなく水準(ネック∓余白)そのもの。
#     この水準は⑫のブレイク判定水準と同じ側にする(ユーザー判断
#     2026-07-27: 以前は符号が逆で、ブレイク水準とは反対側の水準を使って
#     しまっていた)。見つからなければ候補ごと不成立(ユーザー判断)。
#     山1前点→ネックの本数を時間0(interval0)とする(以前は山1前点→山1
#     だったが、⑫の対称性チェックの比較対象を時間1に変更したのに合わせて
#     変更、ユーザー判断2026-07-27)。
#   ⑩値動きのなめらかさ(効率比・終値ベース): 各区間(山1前→山1・山1→ネッ
#     ク・ネック→山2・山2→ブレイク[Confirmed評価時のみ])について、正味の
#     値動き÷総移動距離がefficiency_ratio_min以上(②のON/OFFとは無関係に
#     常に判定 - ユーザー判断:「滑らかさも切り離して」)。
#   ⑪直線からの乖離(高値/安値ベース): ⑩と同じ各区間で、区間の両端を結ぶ
#     直線からの最大乖離が、trendline_dev_basis(「atr」または
#     「price_pct」)で選んだ基準以内。
#   ①〜⑨、および⑩⑪のうち山1前→山1・山1→ネック・ネック→山2の3区間が
#     揃った瞬間(confirm_floor、先読み防止のため各ピボットの右側確認が
#     終わるまで遅延させる)が"Detected"。
#   ⑫決着判定(6状態): Rejected(早すぎるブレイク - formed_barからbreakout_
#     deadline_min_bars本未満での突破は無効。以前はinterval1基準の比率
#     だったが、比率だと判定を開始できる時点(pivot_right_bars分の遅延後)
#     で既に猶予を使い切ってしまうケースがあったため、固定本数(デフォルト
#     4本)に変更した/Confirmed(ネックライン突破、かつ時間0(山1前点→ネックの
#     本数)が時間1(ネック→ブレイクの本数、判定バーごとに変わる)×
#     interval_symmetry_ratio_min〜maxの範囲内、かつ山2→ブレイク区間も
#     なめらかさ・直線乖離を満たす - 満たさなければRejected)/
#     Failed After Retest/Failed Before Retest/Expired(山1→山2の本数×
#     breakout_deadline_ratio_max本経過しても決着しなければ期限切れ - 以前は
#     interval1(山1→ネック)基準だったが、山1→山2の本数基準に変更、ユーザー
#     判断2026-07-27)。
#     同一バーでConfirmed・Failed両方の条件が成立した場合はFailedを優先
#     する(ユーザー判断: バックテストエンジン本体のSL/TP同時ヒット時と
#     同じ「悪い方を優先」という既存の全体方針に合わせた)。
#
# 上記どの判定にも、実際にそのピボットが「本物」だと確定するpivot_right_bars
# 本の確認遅延を先読み防止として組み込んでいる(_double_top_bottom_stateの
# confirm_floorと同じ考え方)。
# ---------------------------------------------------------------------------

def _double_top_bottom_shape_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    pre_trend_lookback_bars: int = 0,
    pre_trend_atr_mult: float = 0.0,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_pct: float = 15.0,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_pct: float = 7.5,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_basis: str = "top1_top2",
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_min: float = 0.3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
) -> dict[str, pd.Series]:
    """モジュール冒頭のコメント参照。bullish=Trueでダブルボトム、Falseで
    ダブルトップ(高値/安値・上下を反転させた鏡像)。

    top_tolerance_basis: 山1・山2の水準許容誤差の基準。"atr"は固定ATR倍率
    (パターンの規模に関わらず一定なので、期間が短い/値動きが小さいパターン
    では相対的に緩すぎ、期間が長い/値動きが大きいパターンでは相対的に厳し
    すぎる傾向がある)。"price_pct"は山1→ネックの値幅(山2探索時点で既知の
    量)に対する%で、trendline_dev_basisと同じ考え方でパターンの規模に応じ
    て許容誤差がスケールする。

    breakout_buffer_basis: ネックライン付近での「本物のブレイク/失敗」判定
    に使う余白の基準。top_tolerance_basisと同じ理由で"atr"は固定ATR倍率、
    "price_pct"は谷の深さ(⑧で計算済み、山1前点探索・ブレイク確定・失敗
    判定・リテスト判定の全てで谷の深さは既知)に対する%。谷の深さ自体は
    (min/max_valley_depth_atr_multで判定する)パターンの規模の主指標なので
    ATR倍率のままにしてある(top_toleranceやbreakout_bufferのような「別の
    値幅と比較する許容誤差」ではないため)。

    breakout_deadline_basis: ブレイク猶予(早すぎる/遅すぎるの判定)の方式。
    "top1_top2"(既定、double_top_shape/double_bottom_shapeが使う最新方式)
    は、早すぎる判定をbreakout_deadline_min_bars(formed_barからの固定
    本数)、遅すぎる判定を山1→山2の本数×breakout_deadline_ratio_maxで行う。
    "interval1"(旧方式、double_top_shape_v1/double_bottom_shape_v1が使う)
    は、早すぎる判定もbreakout_deadline_ratio_min×山1→ネックの本数(比率)
    で行い、遅すぎる判定も山1→ネックの本数×breakout_deadline_ratio_maxで
    行う(2026-07-27に前者へ変更する前の方式。ユーザー要望により、比較用に
    別indicatorとして両方残している)。"""
    n = len(high)
    idx_index = high.index
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_a = _atr_series(df, 14).to_numpy()

    if breakout_type not in ("close", "wick"):
        raise ValueError(f"未対応のbreakout_typeです(close/wickのみ対応): {breakout_type}")
    if trendline_dev_basis not in ("atr", "price_pct"):
        raise ValueError(f"未対応のtrendline_dev_basisです(atr/price_pctのみ対応): {trendline_dev_basis}")

    # 「山」= 高値側の反転点、「谷」= 安値側の反転点。bullish(ダブルボトム)
    # は谷1→ネック(高値側)→谷2、ダブルトップはその鏡像。
    ext_price_a = low_a if bullish else high_a  # 山1/山2側(反転点そのもの)
    neck_price_a = high_a if bullish else low_a  # ネック側

    # ① 値幅込みのピボット判定 - 通常のピボット判定(_detect_pivot_highs/
    # _detect_pivot_lows)に、「左右の境界からATR×prominence_atr_mult以上
    # 離れているか」という値幅の下限を追加でANDする。
    plain_pivot_ext = (
        _detect_pivot_lows(low, pivot_left_bars, pivot_right_bars)
        if bullish
        else _detect_pivot_highs(high, pivot_left_bars, pivot_right_bars)
    ).to_numpy()
    plain_pivot_neck = (
        _detect_pivot_highs(high, pivot_left_bars, pivot_right_bars)
        if bullish
        else _detect_pivot_lows(low, pivot_left_bars, pivot_right_bars)
    ).to_numpy()

    boundary_other_a = high_a if bullish else low_a  # 反転点側の判定に使う「境界」の反対サイド
    left_boundary = pd.Series(boundary_other_a).shift(pivot_left_bars).to_numpy()
    right_boundary = pd.Series(boundary_other_a).shift(-pivot_right_bars).to_numpy()
    prom_thresh = atr_a * prominence_atr_mult
    with np.errstate(invalid="ignore"):
        if bullish:
            prominence_ok_ext = (left_boundary - ext_price_a >= prom_thresh) & (right_boundary - ext_price_a >= prom_thresh)
        else:
            prominence_ok_ext = (ext_price_a - left_boundary >= prom_thresh) & (ext_price_a - right_boundary >= prom_thresh)
    prominence_ok_ext = np.nan_to_num(prominence_ok_ext, nan=0.0).astype(bool)

    neck_boundary_other_a = low_a if bullish else high_a
    left_boundary_neck = pd.Series(neck_boundary_other_a).shift(pivot_left_bars).to_numpy()
    right_boundary_neck = pd.Series(neck_boundary_other_a).shift(-pivot_right_bars).to_numpy()
    with np.errstate(invalid="ignore"):
        if bullish:
            prominence_ok_neck = (neck_price_a - left_boundary_neck >= prom_thresh) & (neck_price_a - right_boundary_neck >= prom_thresh)
        else:
            prominence_ok_neck = (left_boundary_neck - neck_price_a >= prom_thresh) & (right_boundary_neck - neck_price_a >= prom_thresh)
    prominence_ok_neck = np.nan_to_num(prominence_ok_neck, nan=0.0).astype(bool)

    ext_flags = plain_pivot_ext & prominence_ok_ext
    neck_flags = plain_pivot_neck & prominence_ok_neck

    ext_events = [i for i in range(n) if ext_flags[i]]
    neck_events_all = [i for i in range(n) if neck_flags[i]]

    pivot_confirm_lag = pivot_right_bars

    def _threshold_atr(bar: int, mult: float) -> float:
        return atr_a[bar] * mult

    # ⑥' 山1・山2・ネックの孤立度チェック(区間比例窓) - 固定本数ではなく、
    # 隣接する区間の長さ×pivot_spike_window_ratio(既定1.0)本を「片側だけ」
    # 見る。実体が小さくヒゲ1本だけが周囲から突出している「一瞬のスパイク」
    # を、値幅基準(prominence、境界バーとの比較のみ)では弾けないケースが
    # あったため追加(ユーザー判断2026-07-29)。山1左は(山1前→山1)、山1右は
    # (山1→ネック)、山2左は(ネック→山2)、山2右は(山2→ブレイク、⑫の決着
    # 判定ループ内でその時点のバーjまでを使って都度判定)、ネック左は
    # (山1→ネック、山1右と同じ区間)、ネック右は(ネック→山2、山2左と同じ
    # 区間)を基準にする。それぞれ左右どちらか一方が合格すればOK(OR、
    # ユーザー判断2026-07-29: 両方AND必須だと厳しすぎたため)。
    # pivot_spike_excess_atr_max<=0で無効(他の0=無効の慣習と統一、別の
    # ON/OFFフラグは作らない)。window_sizeの右端/左端は反転点自身の直前/
    # 直後から、区間長×比率ぶんだけ。
    def _directional_spike_ok(price_a: np.ndarray, bar: int, window_size: int, direction: str, is_high_type: bool) -> bool:
        if pivot_spike_excess_atr_max <= 0 or window_size <= 0:
            return True
        if direction == "left":
            lo, hi = max(0, bar - window_size), bar - 1
        else:
            lo, hi = bar + 1, min(n - 1, bar + window_size)
        if lo > hi:
            return True
        segment = price_a[lo : hi + 1]
        if is_high_type:
            excess = price_a[bar] - segment.max()
        else:
            excess = segment.min() - price_a[bar]
        return excess <= atr_a[bar] * pivot_spike_excess_atr_max

    def _efficiency_ratio(start_bar: int, end_bar: int) -> float:
        """正味の値動き(終値ベース)÷実際に動いた総距離。区間が1本以下なら
        判定不能として満点(1.0)扱い(短すぎる区間をなめらかさの理由で
        落とさないため)。"""
        if end_bar <= start_bar:
            return 1.0
        segment = close_a[start_bar : end_bar + 1]
        net_move = abs(segment[-1] - segment[0])
        path = np.abs(np.diff(segment)).sum()
        if path <= 0:
            return 1.0
        return net_move / path

    def _max_deviation_ok(start_bar: int, start_price: float, end_bar: int, end_price: float) -> bool:
        """区間の両端を結んだ直線から、高値/安値のヒゲが最大でどれだけ
        乖離しているかを判定する(_line_deviation_okと同じ考え方だが、
        許容幅をATR基準/価格差基準のどちらで取るか選べる)。"""
        span = end_bar - start_bar
        if span <= 0:
            return True
        if trendline_dev_basis == "atr":
            tol = _threshold_atr(end_bar, trendline_dev_atr_mult)
        else:
            tol = abs(end_price - start_price) * trendline_dev_pct
        for j in range(start_bar, end_bar + 1):
            line_v = start_price + (end_price - start_price) * (j - start_bar) / span
            if max(abs(high_a[j] - line_v), abs(low_a[j] - line_v)) > tol:
                return False
        return True

    exists_a = np.zeros(n, dtype=bool)
    detected_a = np.zeros(n, dtype=bool)
    rejected_a = np.zeros(n, dtype=bool)
    resolve_a = np.zeros(n, dtype=bool)  # confirmed
    failed_after_retest_a = np.zeros(n, dtype=bool)
    failed_before_retest_a = np.zeros(n, dtype=bool)
    expired_a = np.zeros(n, dtype=bool)
    formed_bar_a = np.full(n, np.nan)
    top1_bar_a = np.full(n, np.nan)
    top2_bar_a = np.full(n, np.nan)
    top1_price_a = np.full(n, np.nan)
    top2_price_a = np.full(n, np.nan)
    neckline_bar_a = np.full(n, np.nan)
    neckline_price_a = np.full(n, np.nan)

    # 以前はlast_consumed_barで「既に決着した候補の区間より前の山1候補」を
    # スキップしていたが、これだと大きいダブルトップの中に小さいダブル
    # トップがネストしている場合、大きい方が先に決着すると小さい方が丸ごと
    # スキップされてしまっていた。両方を独立に検出できるようにするため、
    # 消費済み区間によるスキップを廃止し、全ての山1候補を独立に評価する
    # (ユーザー判断2026-07-27)。
    for top1_true_bar in ext_events:
        top1_price = float(ext_price_a[top1_true_bar])
        top1_confirm_bar = top1_true_bar + pivot_confirm_lag

        # ② 山1前のトレンド確認 - 別のON/OFFフラグ(旧pre_trend_check_enabled)
        # を廃止し、pre_trend_lookback_bars・pre_trend_atr_multのどちらかが
        # 0なら無効、両方とも0より大きければ有効(ユーザー判断2026-07-28、
        # 他の0=無制限/無効の慣習と統一)。
        if pre_trend_lookback_bars > 0 and pre_trend_atr_mult > 0:
            ref_bar = top1_true_bar - pre_trend_lookback_bars
            if ref_bar < 0:
                continue
            trend_thresh = _threshold_atr(top1_true_bar, pre_trend_atr_mult)
            ref_price = float(ext_price_a[ref_bar])
            if bullish:
                if not (ref_price - top1_price >= trend_thresh):
                    continue
            else:
                if not (top1_price - ref_price >= trend_thresh):
                    continue

        # ③⑤⑥⑦⑧⑨⑩⑪⑫ ネックライン探索 - 有効なネック候補(min/max_bars_
        # between_topsを満たす)のうち、「一番良い(高い/安い)ものだが、それ
        # より後に出た候補は、既に選んだネックの探索窓を過ぎていたら採用
        # しない」というルールで次々更新する。以前はネックを確定させ切って
        # から山2を1回だけ探していたが、それだと本来近くにあるはずの山2が
        # ネックの更新に押し流されて探索窓の外に出てしまうケースがあった
        # (ユーザー報告2026-07-28)。そのため、ネックが更新されるたびに
        # その時点のネックで山2以降(⑤〜⑫)を毎回試す形に変更 - 同じ山1から
        # 複数の(ネック・山2)の組み合わせが独立した候補として成立し、それ
        # ぞれ別々にDetected〜決着まで進みうる(ユーザー判断2026-07-28)。
        # 後から出てきたより良いネックが、既に決着した候補を上書きすること
        # はない(判定はその都度その場で完結させるため)。
        neck_true_bar = None
        neck_price = None
        for k in neck_events_all:
            if k <= top1_true_bar:
                continue
            interval1_candidate = k - top1_true_bar
            # max_bars_between_tops=0は無制限(ユーザー判断2026-07-28)。
            # neck_events_allは昇順なので、超えたらこれ以降はもっと遠い。
            if max_bars_between_tops > 0 and interval1_candidate > max_bars_between_tops:
                break
            if interval1_candidate < min_bars_between_tops:
                continue
            if neck_true_bar is not None:
                interval1_prev = neck_true_bar - top1_true_bar
                prev_win_end = neck_true_bar + int(np.floor(interval1_prev * symmetry_ratio_max))
                if k > prev_win_end:
                    break  # 今のネックの探索窓を過ぎてから出た候補はもう無意味
            is_better = (
                neck_price is None
                or (neck_price_a[k] > neck_price if bullish else neck_price_a[k] < neck_price)
            )
            if not is_better:
                continue
            neck_price = float(neck_price_a[k])
            neck_true_bar = k
            neck_confirm_bar = neck_true_bar + pivot_confirm_lag

            interval1 = neck_true_bar - top1_true_bar

            # ⑥' 山1右側・ネック左側の孤立度チェック - どちらも(山1→ネック)
            # ×pivot_spike_window_ratio本を使う(山1右はneck_true_barより
            # 手前、ネック左はtop1_true_barより奥、同じ区間の反対向き)。
            # neck_true_barは既に確定済みの過去データなので先読みにはなら
            # ない。左右どちらか一方が合格すればOK(OR)とするため、ここでは
            # 即continueせず結果だけ保持し、山1側は⑨'、ネック側は⑦'で
            # それぞれの反対側の結果と合わせて判定する(ユーザー判断
            # 2026-07-29: 左右ともAND必須だと厳しすぎたため)。
            top1_right_ok = _directional_spike_ok(
                ext_price_a,
                top1_true_bar,
                int(round(interval1 * pivot_spike_window_ratio)),
                "right",
                is_high_type=not bullish,
            )
            neck_left_ok = _directional_spike_ok(
                neck_price_a,
                neck_true_bar,
                int(round(interval1 * pivot_spike_window_ratio)),
                "left",
                is_high_type=bullish,
            )

            win_start = neck_true_bar + int(np.ceil(interval1 * symmetry_ratio_min))
            win_end = min(neck_true_bar + int(np.floor(interval1 * symmetry_ratio_max)), n - 1)
            if win_start > win_end:
                continue

            # ⑥⑦ 山2候補 - 窓の中で値幅込みピボット・水準許容誤差を両方満たす
            # バーを見つけるたびに上書き(「最新の候補で更新」)。許容誤差を
            # 超えて悪化する値が一度でも出たら候補ごと不成立。
            # top_tolerance_basisが"price_pct"の場合、山1→ネックの値幅(この
            # 時点で既知)に対する%を許容誤差とする(パターン規模でスケール)。
            # "atr"の場合は従来通りバーごとのATR倍率(バーによって変動)。
            top_tolerance_pct_value = abs(top1_price - neck_price) * (top_tolerance_pct / 100.0)
            # numpyの一括計算で判定(元はバーごとのPythonループだったが、
            # ネック更新のたびに呼ばれるようになった影響で遅くなったため
            # 高速化、判定結果は元のロジックと同一 - ユーザー報告2026-07-28)。
            # 「破綻(breached)より後の候補は使わない」「破綻より前の範囲内
            # では一番遅い(最新の)一致を採用」という元の意味を維持したまま、
            # 配列演算に置き換えている。
            # price_pct(既定)の場合は窓内で許容誤差が一定値になるため、
            # 配列を作らずスカラーのままnumpyのブロードキャストに任せる
            # (np.fullで定数配列を作ると無駄にコストがかかると判明したため
            # 修正 - ユーザー報告2026-07-28、バックテスト速度確認時)。
            if top_tolerance_basis == "price_pct":
                tol = top_tolerance_pct_value
            else:
                tol = atr_a[win_start : win_end + 1] * top_tolerance_atr_mult
            if bullish:
                breach_mask = low_a[win_start : win_end + 1] < (top1_price - tol)
            else:
                breach_mask = high_a[win_start : win_end + 1] > (top1_price + tol)
            breach_idx = np.flatnonzero(breach_mask)
            window_invalidated = breach_idx.size > 0
            scan_hi_local = (int(breach_idx[0]) - 1) if window_invalidated else (win_end - win_start)

            top2_true_bar = None
            top2_price = None
            if scan_hi_local >= 0:
                tol_sub = tol[: scan_hi_local + 1] if isinstance(tol, np.ndarray) else tol
                match_mask = ext_flags[win_start : win_start + scan_hi_local + 1] & (
                    np.abs(ext_price_a[win_start : win_start + scan_hi_local + 1] - top1_price) <= tol_sub
                )
                match_idx = np.flatnonzero(match_mask)
                if match_idx.size > 0:
                    top2_true_bar = win_start + int(match_idx[-1])
                    top2_price = float(ext_price_a[top2_true_bar])

            if window_invalidated or top2_true_bar is None:
                continue
            top2_confirm_bar = top2_true_bar + pivot_confirm_lag

            # ⑦' 山2左側・ネック右側の孤立度チェック - どちらも(ネック→山2)
            # ×pivot_spike_window_ratio本を使う。neck_true_bar・top2_true_
            # barは既に確定済みの過去データなので先読みにはならない。山2側
            # は⑫'の右側の結果とOR、ネック側はここで⑥'の左側の結果と合わせ
            # てORで判定する(ユーザー判断2026-07-29)。山2側は⑫'まで即
            # continueせず結果だけ保持する。
            interval2 = top2_true_bar - neck_true_bar
            top2_left_ok = _directional_spike_ok(
                ext_price_a,
                top2_true_bar,
                int(round(interval2 * pivot_spike_window_ratio)),
                "left",
                is_high_type=not bullish,
            )
            neck_right_ok = _directional_spike_ok(
                neck_price_a,
                neck_true_bar,
                int(round(interval2 * pivot_spike_window_ratio)),
                "right",
                is_high_type=bullish,
            )
            if not (neck_left_ok or neck_right_ok):
                continue

            # ⑧ 谷(山)の深さ。max_valley_depth_atr_mult=0は無制限(ユーザー
            # 判断2026-07-28)。
            avg_extreme = (top1_price + top2_price) / 2
            depth = (neck_price - avg_extreme) if bullish else (avg_extreme - neck_price)
            depth_min = _threshold_atr(top2_true_bar, min_valley_depth_atr_mult)
            depth_max = np.inf if max_valley_depth_atr_mult <= 0 else _threshold_atr(top2_true_bar, max_valley_depth_atr_mult)
            if not (depth_min <= depth <= depth_max):
                continue

            # breakout_buffer_basisが"price_pct"の場合、谷の深さ(直前の⑧で
            # 計算済み)に対する%を余白とする。山1前点探索・ブレイク確定・
            # 失敗判定・リテスト判定の全てで共通のこの値を使う("atr"の場合
            # は決着判定のループ内でバーごとのATRを都度使うので、そちらは
            # 従来通りバーごとに計算する)。
            breakout_buffer_pct_value = depth * (breakout_buffer_pct / 100.0)

            # ⑨ 山1前点 - 山1より過去に遡り、安値≦(ネック∓余白)≦高値を満た
            # す直近のバーを探す。見つからなければ候補ごと不成立。この水準
            # は⑫のブレイク判定水準と揃える(ユーザー判断2026-07-27: 以前は
            # 符号が逆で、ブレイク水準とは反対側の水準を使ってしまっていた)。
            pre_buf = breakout_buffer_pct_value if breakout_buffer_basis == "price_pct" \
                else _threshold_atr(top1_true_bar, breakout_buffer_atr_mult)
            pre_level = neck_price + pre_buf if bullish else neck_price - pre_buf
            # numpyの一括計算で判定(元は山1から遡るPythonループで、範囲の
            # 上限が無いため特に遅かった。ネック更新のたびに呼ばれるように
            # なった影響を最も受けていた箇所 - ユーザー報告2026-07-28)。
            # 「一番山1に近い(=一番後ろの)一致」を採る元の意味は維持。
            pre_bar = None
            if top1_true_bar > 0:
                pre_mask = (low_a[:top1_true_bar] <= pre_level) & (pre_level <= high_a[:top1_true_bar])
                pre_matches = np.flatnonzero(pre_mask)
                if pre_matches.size > 0:
                    pre_bar = int(pre_matches[-1])
            if pre_bar is None:
                continue

            # ⑨' 山1左側の孤立度チェック - (山1前→山1)×pivot_spike_window_
            # ratio本だけ山1の左側を見る。pre_barは既に確定済みの過去
            # データなので先読みにはならない。⑥'の右側の結果とOR(どちらか
            # 一方が合格すればOK)で山1の孤立度を判定する(ユーザー判断
            # 2026-07-29)。
            top1_left_ok = _directional_spike_ok(
                ext_price_a,
                top1_true_bar,
                int(round((top1_true_bar - pre_bar) * pivot_spike_window_ratio)),
                "left",
                is_high_type=not bullish,
            )
            if not (top1_left_ok or top1_right_ok):
                continue

            # 時間0(山1前点→ネック)。以前は山1前点→山1だったが、対称性
            # チェックの比較対象を時間1(ネック→ブレイク)に変更したのに
            # 合わせて、時間0も同じくネックまでの本数にする(ユーザー判断
            # 2026-07-27)。
            interval0 = neck_true_bar - pre_bar

            # 谷1(山1)が山1前点→ネックの区間で絶対最安値(山1前点→ネックの
            # 区間内で高値・安値のヒゲも含めた真の最安値/最高値)であること
            # を必須条件にする(ユーザー判断2026-07-29: ピボット判定は値幅
            # 基準を満たす反転点かどうかしか見ないため、区間内に値幅基準を
            # 満たさない「一瞬だけのダマシ安値/高値」が紛れていても弾かれ
            # ず、谷1が区間の真の最安値でないまま候補として進んでしまう
            # ケースがあったため)。この区間は既に確定済み(pre_bar・
            # neck_true_barとも先読みなしに既知)なので先読みにはならない。
            if bullish:
                if top1_price > low_a[pre_bar : neck_true_bar + 1].min():
                    continue
            else:
                if top1_price < high_a[pre_bar : neck_true_bar + 1].max():
                    continue

            # ①〜⑨、および⑩⑪のうち山1前→山1・山1→ネック・ネック→山2の3
            # 区間が先読みなしに揃う最初のバー(confirm_floor)
            confirm_floor = max(top1_confirm_bar, neck_confirm_bar, top2_confirm_bar)
            if confirm_floor >= n:
                continue  # データの末尾で確定しきれない

            # ⑩⑪ 山1前→山1・山1→ネック・ネック→山2のなめらかさ - ②(トレン
            # ド確認)のON/OFFとは無関係に常に判定する(ユーザー判断:「滑ら
            # かさも切り離して」- ⑨の谷1前点探索・間隔0自体も元々②とは無関
            # 係に常に動くようになっているので、それと揃える形)。②でON/OFF
            # が効くのは山1の値幅(下げ幅/上げ幅)基準のみ。
            # なめらかさ(効率比)は「各区間が個別にefficiency_ratio_min以上」
            # (=min(区間群)≥閾値と同義)から、「各区間はefficiency_ratio_
            # floor以上(1区間だけ壊滅的に崩れているのは防ぐ)、かつ平均が
            # efficiency_ratio_min以上」に変更(ユーザー判断2026-07-28: 1
            # 区間だけ崩れていても他が良ければ薄めて隠せてしまう懸念には
            # efficiency_ratio_floorで対応)。直線乖離(_max_deviation_ok)
            # は従来通り各区間個別にAND判定のまま。
            eff1 = _efficiency_ratio(pre_bar, top1_true_bar)
            eff2 = _efficiency_ratio(top1_true_bar, neck_true_bar)
            eff3 = _efficiency_ratio(neck_true_bar, top2_true_bar)
            legs_ok = (
                eff1 >= efficiency_ratio_floor
                and eff2 >= efficiency_ratio_floor
                and eff3 >= efficiency_ratio_floor
                and (eff1 + eff2 + eff3) / 3 >= efficiency_ratio_min
                and _max_deviation_ok(pre_bar, pre_level, top1_true_bar, top1_price)
                and _max_deviation_ok(top1_true_bar, top1_price, neck_true_bar, neck_price)
                and _max_deviation_ok(neck_true_bar, neck_price, top2_true_bar, top2_price)
            )
            if not legs_ok:
                continue

            formed_bar = confirm_floor
            detected_a[formed_bar] = True

            # ⑫ 決着判定
            # 猶予上限(expire_bars)の基準は山1→ネックの本数(interval1)。
            # 以前は"top1_top2"方式のみ山1→山2の本数(=山1→ネック→山2の
            # 2区間分)を使っていたが、これだと同じ倍率でも実質2区間分の
            # 長さになってしまい猶予が想定より長くなる(ユーザー指摘
            # 2026-07-29)。対称性チェック(山1前→ネック vs ネック→ブレイク)
            # も1区間(interval1)基準なので、それと揃える形でbreakout_
            # deadline_basisの値によらずinterval1に統一(旧方式"interval1"
            # は元々interval1だったので実質変化なし)。breakout_deadline_
            # basisは早すぎる判定(reject_bars)の計算方法の違いとしては
            # 引き続き使う。
            expire_ref_bars = interval1
            expire_bars = expire_ref_bars * breakout_deadline_ratio_max
            scan_start = max(top2_true_bar + 1, formed_bar)
            scan_end = min(top2_true_bar + int(np.ceil(expire_bars)), n - 1)

            retested = False
            outcome = None  # "rejected" | "confirmed" | "failed" | "expired"
            outcome_bar = None

            # numpyの一括計算で判定(元はバーごとのPythonループだったが、
            # ネック更新のたびに呼ばれるようになった影響で遅くなったため
            # 高速化 - ユーザー報告2026-07-28)。confirm_hit/fail_hitはどちら
            # かが最初に成立したバーで必ずループを抜ける(rejected/failed/
            # confirmedいずれの分岐でもbreakする)ため、「最初に成立する
            # バー」を配列演算で一括に求め、そのバー1本分だけ元と同じ分岐
            # ロジックを実行すれば結果は完全に同一になる。
            if scan_start <= scan_end:
                seg = slice(scan_start, scan_end + 1)
                # price_pct(既定)の場合は区間内で余白が一定値になるため、
                # 配列を作らずスカラーのままブロードキャストに任せる(⑥⑦と
                # 同じ理由 - np.fullでの定数配列生成が無駄だったため修正)。
                if breakout_buffer_basis == "price_pct":
                    buf_arr = breakout_buffer_pct_value
                else:
                    buf_arr = atr_a[seg] * breakout_buffer_atr_mult
                worse_extreme = min(top1_price, top2_price) if bullish else max(top1_price, top2_price)

                if breakout_type == "close":
                    if bullish:
                        confirm_arr = close_a[seg] > (neck_price + buf_arr)
                        fail_arr = close_a[seg] < (worse_extreme - buf_arr)
                    else:
                        confirm_arr = close_a[seg] < (neck_price - buf_arr)
                        fail_arr = close_a[seg] > (worse_extreme + buf_arr)
                else:  # "wick"
                    if bullish:
                        confirm_arr = high_a[seg] > (neck_price + buf_arr)
                        fail_arr = low_a[seg] < (worse_extreme - buf_arr)
                    else:
                        confirm_arr = low_a[seg] < (neck_price - buf_arr)
                        fail_arr = high_a[seg] > (worse_extreme + buf_arr)

                retest_zone_lo_arr = neck_price - buf_arr * retest_buffer_mult
                retest_zone_hi_arr = neck_price + buf_arr * retest_buffer_mult
                near_arr = (
                    ((retest_zone_lo_arr <= high_a[seg]) & (high_a[seg] <= retest_zone_hi_arr))
                    | ((retest_zone_lo_arr <= low_a[seg]) & (low_a[seg] <= retest_zone_hi_arr))
                    | ((low_a[seg] <= retest_zone_lo_arr) & (high_a[seg] >= retest_zone_hi_arr))
                )

                hit_idx = np.flatnonzero(confirm_arr | fail_arr)

                if hit_idx.size > 0:
                    first_local = int(hit_idx[0])
                    j = scan_start + first_local
                    retested = bool(near_arr[: first_local + 1].any())

                    # 同一バーでConfirmed/Failed両方成立した場合はFailedを
                    # 優先(ユーザー判断: バックテストエンジン本体のSL/TP
                    # 同時ヒット時と同じ「悪い方を優先」という既存の全体
                    # 方針に合わせる)。
                    if fail_arr[first_local]:
                        outcome = "failed"
                        outcome_bar = j
                    else:
                        # ここに来るのはconfirm_hitのみ成立した場合。「早
                        # すぎる」の起点は山2のバー(top2_true_bar)ではなく
                        # formed_bar(先読み回避のため判定を開始できる最初
                        # のバー)にする。山2からformed_barまでは既にピボ
                        # ット右本数ぶん経過しているので、起点を山2のまま
                        # にすると、猶予がピボット右本数より小さい設定の
                        # 場合、判定を開始できる時点で既に猶予を使い切っ
                        # てしまい、このガードが実質機能しなくなる(ユーザ
                        # ー報告2026-07-27: formed_barの1本後に即Confirmed
                        # になった実例)。
                        bars_since_formed = j - formed_bar
                        reject_bars = breakout_deadline_min_bars if breakout_deadline_basis == "top1_top2" \
                            else interval1 * breakout_deadline_ratio_min
                        if bars_since_formed < reject_bars:
                            outcome = "rejected"
                            outcome_bar = j
                        else:
                            # 時間0(山1前点→ネック)と時間1(ネック→ブレイ
                            # ク)の対称性(基準を山1→ネックの本数からネッ
                            # ク→ブレイクの本数に変更、時間0も山1前点→山1
                            # からネックまでの本数に変更、ユーザー判断
                            # 2026-07-27)、および山2→ブレイク区間のなめら
                            # かさ。山2→ブレイク区間は①〜③の3区間の平均に
                            # は混ぜず、独立してfloor以上・min以上を満たす
                            # かで判定する(ユーザー判断2026-07-28: 4区間ま
                            # とめた平均だと、この区間だけの良し悪しが薄ま
                            # ってしまうため)。
                            time1 = j - neck_true_bar
                            symmetric_ok = (
                                time1 * interval_symmetry_ratio_min <= interval0 <= time1 * interval_symmetry_ratio_max
                            )
                            eff4 = _efficiency_ratio(top2_true_bar, j)
                            # 谷2(山2)がネック→(このバーjで確定させようと
                            # している)ブレイクの区間で絶対最安値(最高値)
                            # であることも必須条件にする(ユーザー判断
                            # 2026-07-29: 谷1と同じ理由。この時点でのjは
                            # 「今まさに確定させようとしているブレイクの
                            # バー」であり、ネックからjまでは全て既知の過去
                            # データなので、先読みにはならない - eff4や
                            # symmetric_okと同じ扱い)。
                            if bullish:
                                no_undercut = top2_price <= low_a[neck_true_bar : j + 1].min()
                            else:
                                no_undercut = top2_price >= high_a[neck_true_bar : j + 1].max()
                            # ⑫' 山2右側の孤立度チェック - (山2→ブレイク)×
                            # pivot_spike_window_ratio本だけ山2の右側を見る。
                            # jは「今まさに確定させようとしているブレイクの
                            # バー」なので、top2_true_barからjまでは全て既知
                            # の過去データであり、先読みにはならない
                            # (no_undercutと同じ扱い、ユーザー判断2026-07-29)。
                            # window_sizeはjを超えないようclampする(比率が
                            # 1.0を超える設定でも先読みにならないようにする
                            # ための安全策)。
                            top2_right_window = min(
                                int(round((j - top2_true_bar) * pivot_spike_window_ratio)),
                                j - top2_true_bar,
                            )
                            top2_right_ok = _directional_spike_ok(
                                ext_price_a,
                                top2_true_bar,
                                top2_right_window,
                                "right",
                                is_high_type=not bullish,
                            )
                            # 山2左側(⑦'で計算済み)とOR(どちらか一方が合格
                            # すればOK、ユーザー判断2026-07-29)。
                            top2_isolation_ok = top2_left_ok or top2_right_ok
                            breakout_leg_ok = (
                                symmetric_ok
                                and eff4 >= efficiency_ratio_floor
                                and eff4 >= efficiency_ratio_min
                                and no_undercut
                                and top2_isolation_ok
                                and _max_deviation_ok(top2_true_bar, top2_price, j, float(close_a[j] if breakout_type == "close" else (high_a[j] if bullish else low_a[j])))
                            )
                            if not breakout_leg_ok:
                                outcome = "rejected"
                                outcome_bar = j
                            else:
                                outcome = "confirmed"
                                outcome_bar = j
                else:
                    retested = bool(near_arr.any())

            if outcome is None:
                outcome = "expired"
                outcome_bar = scan_end

            exists_end = outcome_bar if outcome_bar is not None else scan_end
            exists_a[formed_bar : exists_end + 1] = True
            formed_bar_a[formed_bar : exists_end + 1] = formed_bar
            top1_bar_a[formed_bar] = top1_true_bar
            top2_bar_a[formed_bar] = top2_true_bar
            top1_price_a[formed_bar] = top1_price
            top2_price_a[formed_bar] = top2_price
            neckline_bar_a[formed_bar] = neck_true_bar
            neckline_price_a[formed_bar] = neck_price

            if outcome == "rejected":
                rejected_a[outcome_bar] = True
            elif outcome == "confirmed":
                resolve_a[outcome_bar] = True
            elif outcome == "failed":
                if retested:
                    failed_after_retest_a[outcome_bar] = True
                else:
                    failed_before_retest_a[outcome_bar] = True
            else:
                expired_a[outcome_bar] = True

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "detected": pd.Series(detected_a, index=idx_index),
        "rejected": pd.Series(rejected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "failed_after_retest": pd.Series(failed_after_retest_a, index=idx_index),
        "failed_before_retest": pd.Series(failed_before_retest_a, index=idx_index),
        "expired": pd.Series(expired_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "top1_bar": pd.Series(top1_bar_a, index=idx_index),
        "top2_bar": pd.Series(top2_bar_a, index=idx_index),
        "top1_price": pd.Series(top1_price_a, index=idx_index),
        "top2_price": pd.Series(top2_price_a, index=idx_index),
        "neckline_bar": pd.Series(neckline_bar_a, index=idx_index),
        "neckline_price": pd.Series(neckline_price_a, index=idx_index),
    }


_SHAPE_STATE_KEYS = {
    "detected": "detected",
    "rejected": "rejected",
    "confirmed": "confirmed",
    "failed_after_retest": "failed_after_retest",
    "failed_before_retest": "failed_before_retest",
    "expired": "expired",
}


def double_bottom_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    pre_trend_lookback_bars: int = 0,
    pre_trend_atr_mult: float = 0.0,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_pct: float = 15.0,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_pct: float = 7.5,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """ダブルボトム(形状判定版) - モジュール冒頭のコメント参照。
    Detected/Rejected/Confirmed/Failed After Retest/Failed Before Retest/
    Expiredの6状態をstateパラメータで選べる(既存のdouble_bottom/
    double_bottom_pivotとは完全に独立した実装、そちらは一切変更していない)。"""
    result = _double_top_bottom_shape_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        pre_trend_lookback_bars, pre_trend_atr_mult,
        min_bars_between_tops, max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_pct,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_pct,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        retest_buffer_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def double_bottom_shape_v1(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    pre_trend_lookback_bars: int = 0,
    pre_trend_atr_mult: float = 0.0,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_pct: float = 15.0,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_pct: float = 7.5,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_ratio_min: float = 0.3,
    breakout_deadline_ratio_max: float = 3.0,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """ダブルボトム(形状判定版・旧ブレイク猶予方式) - double_bottom_shapeと
    完全に同じロジックだが、⑫のブレイク猶予(早すぎる/遅すぎるの判定)だけ
    2026-07-27にbreakout_deadline_basis="top1_top2"へ変更する前の方式
    (どちらも山1→ネックの本数×比率、早すぎる判定もbreakout_deadline_
    ratio_min倍率)を使う。比較用にユーザー要望で別indicatorとして残して
    いる。"""
    result = _double_top_bottom_shape_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        pre_trend_lookback_bars, pre_trend_atr_mult,
        min_bars_between_tops, max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_pct,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_pct,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        "interval1", 0, breakout_deadline_ratio_min, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        retest_buffer_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def double_top_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    pre_trend_lookback_bars: int = 0,
    pre_trend_atr_mult: float = 0.0,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_pct: float = 15.0,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_pct: float = 7.5,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """Mirror image of double_bottom_shape - ダブルトップ(形状判定版)。"""
    result = _double_top_bottom_shape_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        pre_trend_lookback_bars, pre_trend_atr_mult,
        min_bars_between_tops, max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_pct,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_pct,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        retest_buffer_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def double_top_shape_v1(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    pre_trend_lookback_bars: int = 0,
    pre_trend_atr_mult: float = 0.0,
    min_bars_between_tops: int = 5,
    max_bars_between_tops: int = 500,
    symmetry_ratio_min: float = 0.3,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_pct: float = 15.0,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_pct: float = 7.5,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    breakout_deadline_ratio_min: float = 0.3,
    breakout_deadline_ratio_max: float = 3.0,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    retest_buffer_mult: float = 1.5,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """ダブルトップ(形状判定版・旧ブレイク猶予方式) - double_bottom_shape_v1
    のミラー。double_top_shapeと完全に同じロジックだが、⑫のブレイク猶予
    だけ旧方式(山1→ネックの本数×比率、早すぎる判定もbreakout_deadline_
    ratio_min倍率)を使う。"""
    result = _double_top_bottom_shape_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        pre_trend_lookback_bars, pre_trend_atr_mult,
        min_bars_between_tops, max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_pct,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_pct,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        "interval1", 0, breakout_deadline_ratio_min, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        retest_buffer_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)
