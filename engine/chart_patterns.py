"""Double top / double bottom (形状判定版) - 非対称ピボット(左右の本数を
別々に指定できるスイング検出)の上に、事前トレンド確認・値動きのなめらかさ
(カウフマン効率比・トレンドラインからの乖離)・ブレイク余白/期限・リテスト
判定まで乗せた、厳密な形状判定ロジック。

UNLIKE engine/technical_indicators.py's classic indicators, chart patterns
have no single agreed mechanical definition - real traders judge "is this a
double top" partly by eye. Everything here is a deliberately simplified,
vectorizable approximation (flat necklines instead of the textbook's slanted
ones, relative-tolerance level-matching instead of subjective symmetry) -
same "exploratory, not verified against any reference charting tool" caveat
engine/smc_indicators.py's own module docstring already states, extended to a
harder category of pattern.

2026-08-07、ユーザー判断: このモジュールには以前トリプルトップ/ボトム、
ヘッド&ショルダーズ、三角形、ウェッジ、フラッグ/ペナント、レンジボックス等
36種のパターンが同居していたが、それらは全て削除した(ハーモニックパターン
12種を収めていたengine/harmonic_patterns.pyも同時に削除)。今後のチャート
パターンは、参考元コードを一度仕様書として言語化してから独自実装する
「B方式」と、全検出器共通の管理仕様(パターンごとの一意ID・1パターン1決着・
複数パターンの同時保持・共通の状態遷移・先読み/リペイント管理)に沿って
改めて追加していく方針のため、旧実装は残さず整理した。

Every function returns a plain np.ndarray[float] (boolean fired 1.0/0.0)
directly, same convention as engine/derived_indicators.py, for the same
reason (a pd.Series slipping into the numba fast backtest path crashed it
once - see engine/candlestick_patterns.py's history).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from engine.indicators import atr as _atr_series


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


def _detect_pivot_highs_left_only(high: pd.Series, left: int) -> pd.Series:
    """_detect_pivot_highsの右側確認を外した版 - 直近left本より高ければ
    その場で(未来のバーを一切使わず)確定する。ダブル/トリプルトップ・
    ボトム(形状判定版)の「最後の山/谷(山2、トリプルなら山3)」専用
    (2026-08-04追加、ユーザー判断: 「山2はピボット左右判定じゃなく左だけで
    右は無でもよくないか」)。右側確認による遅延が無いぶん先読みバイアスが
    ないのは自明(過去のバーしか見ていない)だが、代わりに「本当にそこが
    頂点だったか(その後さらに上がらなかったか)」の保証が弱くなる - これは
    ブレイク判定側のfail_j(山1・この点の高い方+余白を超えたらFailed)が
    実質的に代わりを果たす設計(そちらで拾えなければ、そもそも右側確認を
    待っても同じ結論になる)。

    _detect_pivot_highs/lowsと違って_collapse_consecutive_runsは使わない -
    あちらは「値が完全に同じ(横ばいの天井/底)」バーの連続を先頭1本に絞る
    ためのものだが、左側のみの判定は上昇/下降が続く区間全体で連続してTrue
    になる(値は毎回更新される、単なる横ばいではない)。ここで先頭1本に
    潰すと「上昇/下降し始めて左本数だけ経過した最初のバー」を拾ってしまい、
    実際の頂点/底とはズレる。呼び出し側([_shape_state_core]の山2探索/
    [_shape_state_core3]の谷3探索)は「窓内でより極端な値が出るたびに
    更新する」方式(2026-08-14、全構成点で統一)なので、素の(潰さない)
    フラグのまま渡せば、価格が動き続けている間は追従し、それを超える
    値が出ない限り最も極端だった値が残る。"""
    left_max = high.rolling(window=left + 1).max()
    return (high == left_max).fillna(False)


def _detect_pivot_lows_left_only(low: pd.Series, left: int) -> pd.Series:
    """_detect_pivot_highs_left_onlyの安値版。"""
    left_min = low.rolling(window=left + 1).min()
    return (low == left_min).fillna(False)


def _detect_pivot_highs_right_only(high: pd.Series, right: int) -> pd.Series:
    """_detect_pivot_highsの左側確認を外した版 - pivot_left_bars=0の時、
    山1・ネック側の判定に使う(2026-08-05、ユーザー判断: 「ピボット左本数
    だけ0にしたらピボット右本数だけで判断ということにできない?」)。
    _detect_pivot_highs_left_onlyと違って未来方向(right本先)を見て確定する
    ため、既存のpivot_confirm_lag(=pivot_right_bars)による遅延の仕組みは
    そのまま機能する。横ばいの天井が複数バーにまたがるケースは
    _detect_pivot_highsと同じ性質(「連続で真」になるのはタイの時だけ、
    _left_onlyのような「動き続けている間ずっと真」にはならない)なので、
    _collapse_consecutive_runsで先頭1本に絞る。"""
    right_max = high[::-1].rolling(window=right + 1).max()[::-1]
    is_pivot = (high == right_max).fillna(False)
    return _collapse_consecutive_runs(is_pivot)


def _detect_pivot_lows_right_only(low: pd.Series, right: int) -> pd.Series:
    """_detect_pivot_highs_right_onlyの安値版。"""
    right_min = low[::-1].rolling(window=right + 1).min()[::-1]
    is_pivot = (low == right_min).fillna(False)
    return _collapse_consecutive_runs(is_pivot)


def _pivot_flags(extreme: pd.Series, pivot_left_bars: int, pivot_right_bars: int, is_high_type: bool) -> pd.Series:
    """pivot_left_bars/pivot_right_barsの0/非0に応じて、両側確認・右側のみ・
    左側のみのいずれかのピボット判定を選ぶ(2026-08-05、ユーザー判断:
    「ピボット左本数だけ0にしたらピボット右本数だけで判断」の一般化 - 山1・
    ネック側の判定全般に適用する。呼び出し側でpivot_left_bars/
    pivot_right_barsが両方0にならないことを保証している前提)。"""
    if pivot_left_bars > 0 and pivot_right_bars > 0:
        return _detect_pivot_highs(extreme, pivot_left_bars, pivot_right_bars) if is_high_type else _detect_pivot_lows(
            extreme, pivot_left_bars, pivot_right_bars
        )
    if pivot_right_bars > 0:
        return (
            _detect_pivot_highs_right_only(extreme, pivot_right_bars)
            if is_high_type
            else _detect_pivot_lows_right_only(extreme, pivot_right_bars)
        )
    return (
        _detect_pivot_highs_left_only(extreme, pivot_left_bars)
        if is_high_type
        else _detect_pivot_lows_left_only(extreme, pivot_left_bars)
    )


def _prominence_flags(
    extreme_a: np.ndarray,
    boundary_other_a: np.ndarray,
    pivot_left_bars: int,
    pivot_right_bars: int,
    prom_thresh: np.ndarray,
    is_high_type: bool,
) -> np.ndarray:
    """値幅(prominence)チェック。pivot_left_bars/pivot_right_barsが0の側は
    比較対象がバー自身になり(shift(0))常に差0に退化してしまうため、0の側は
    そもそも計算しない(2026-08-05、ユーザー判断による一般化)。両方0で
    呼ばれた場合(top2/谷2側の右本数は元から常に0扱い、かつpivot_left_bars
    自体も0の時)はチェック自体を無効化する。"""
    checks = []
    if pivot_left_bars > 0:
        left_boundary = pd.Series(boundary_other_a).shift(pivot_left_bars).to_numpy()
        with np.errstate(invalid="ignore"):
            checks.append((extreme_a - left_boundary >= prom_thresh) if is_high_type else (left_boundary - extreme_a >= prom_thresh))
    if pivot_right_bars > 0:
        right_boundary = pd.Series(boundary_other_a).shift(-pivot_right_bars).to_numpy()
        with np.errstate(invalid="ignore"):
            checks.append((extreme_a - right_boundary >= prom_thresh) if is_high_type else (right_boundary - extreme_a >= prom_thresh))
    if not checks:
        return np.ones(len(extreme_a), dtype=bool)
    combined = checks[0]
    for c in checks[1:]:
        combined = combined & c
    return np.nan_to_num(combined, nan=0.0).astype(bool)


def _collapse_consecutive_runs(flags: pd.Series) -> pd.Series:
    """engine/smc_indicators.py::_collapse_consecutive_runsと同じ(平坦な
    天井/底が窓の等号判定に複数バーで一致してしまうのを、最初の1本だけに
    絞る) - こちらは非対称ピボット専用に複製(smc_indicators.py側は
    プライベート関数でimportして再利用する契約になっていないため)。"""
    return flags & ~flags.shift(1, fill_value=False)


# ---------------------------------------------------------------------------
# Double Top/Bottom (形状判定版・2026-07-25) - "本物のW字/M字か"をより厳密に
# 判定する設計。ユーザーとの設計レビューで固まった仕様をそのまま実装して
# いる:
#
#   ①山1(bullish=Falseなら谷1、以下山1で統一)の検出: 左右pivot_left_bars/
#     pivot_right_bars本より高い(安い)、かつ左右の境界の安値(高値)より
#     ATR×prominence_atr_mult以上高い(低い) - 単なる順位だけでなく、値幅
#     そのものを問う「本物の反発」基準(ユーザー指摘:「0.1Pipsとかでも安け
#     ればそれがピボット安値になっちゃう、それは反発とは言えない」)。
#   ②ネックライン: 山1より後、山2が確定するまでの間に出た、①と同じ基準
#     (逆方向)を満たす本物のピボットのうち一番低い(高い)もの - 新しい
#     ピボットが出るたびに更新されるが、既に選んだネックの探索窓を過ぎて
#     からの後出しピボットは採用しない(そのネックではもう山2を探せない
#     ため無意味)。
#   ③山1→ネックの間隔(interval1)がmin_bars_between_tops〜
#     max_bars_between_topsの範囲内。
#   ④山2の探索窓 = ネックからinterval1×symmetry_ratio_min〜
#     symmetry_ratio_max本の範囲、かつ③と同じmin_bars_between_tops〜
#     max_bars_between_tops本の範囲(両方を満たす区間まで絞り込む -
#     2026-08-04追加、ユーザー判断: 「山1→ネックと同じところでネック→山2の
#     本数の範囲も決めたい」)。
#   ⑤⑥山2候補: 窓の中で①とは別の、右側確認を外した左側のみのピボット判定
#     (2026-08-04、ユーザー判断: 「山2はピボット左右判定じゃなく左だけで
#     右は無でもよくないか」)を満たし、かつ山1との価格差がATR×
#     top_tolerance_atr_mult以内のバーのうち、**それまでの候補より高い
#     (bullishなら低い)、より極端な値のときだけ更新する**(2026-08-14、
#     ユーザー判断: 「より深い谷、より高い山が出現したときだけ更新して
#     ほしい」- 山1/谷1・ネックの更新規則(既に「より極端な値のときだけ
#     更新」)と統一。以前は「時系列で最後に見つかったもので単純に上書き」
#     方式だったが、これだと後から出た浅い山でも上書きされてしまい、
#     全ての構成点の更新基準が揃っていなかった)。左側のみの判定は値が
#     更新され続ける間ずっとTrueになるので、価格が動き続けている間は
#     自然に追従し、それより高い(低い)値が出ない限り最も極端だった値が
#     残る(_detect_pivot_highs_left_only/lowsのdocstring参照)。
#     右側確認が無いぶん、山2の確定にformed_bar上の遅延が生じない
#     (pivot_right_bars分の待ちが不要) - 「本当にそこが頂点だったか」の
#     保証は、後段⑪のブレイク判定のfail_j(山1・山2の高い方+余白を超えたら
#     Failed)が代わりに担保する。窓の中で山1の水準を
#     許容誤差を超えて突き抜ける値が一度でも出たら、その時点でこの山1
#     候補ごと不成立にする(ユーザー判断:「許容範囲外の安値が出たらそれは
#     もうダブルボトムじゃない」)。
#   ⑥.5 ネック→山2の間はネックラインを割らない(2026-08-03追加): ⑤⑥は山1
#     との近さ(上側)しか見ていないため、ネックが確定した後に一度ネック
#     ラインを下抜け(bullishなら上抜け)してから山2を付けるような、見た目
#     ダブルトップ/ボトムとして不自然な形も、区間が小さければ⑨⑩(効率比・
#     直線乖離)を通り抜けてしまっていた(ユーザー指摘: 実データの1件で
#     ネック→山2の間にネック割れが発生していたのに確定していた)。
#   ⑦谷(山)の深さ: ネックライン−(山1・山2の平均、絶対値)がATR×
#     min_valley_depth_atr_mult以上・ATR×max_valley_depth_atr_mult以下。
#   ⑧山1前点: ネックが確定した時点で山1より過去に遡り、安値≦
#     (ネック∓余白)≦高値を満たす、山1に一番近い(直近の)バーを探す。
#     この点の価格はそのバー自身のOHLCではなく水準(ネック∓余白)そのもの。
#     この水準は⑪のブレイク判定水準と同じ側にする(ユーザー判断
#     2026-07-27: 以前は符号が逆で、ブレイク水準とは反対側の水準を使って
#     しまっていた)。見つからなければ候補ごと不成立(ユーザー判断)。
#     山1前点→ネックの本数を時間0(interval0)とする(以前は山1前点→山1
#     だったが、⑪の対称性チェックの比較対象を時間1に変更したのに合わせて
#     変更、ユーザー判断2026-07-27)。
#   ⑨値動きのなめらかさ(効率比・終値ベース): 各区間(山1前→山1・山1→ネッ
#     ク・ネック→山2・山2→ブレイク[Confirmed評価時のみ])について、正味の
#     値動き÷総移動距離がefficiency_ratio_min以上(常に判定 - ユーザー判断:
#     「滑らかさも切り離して」)。
#   ⑩直線からの乖離(高値/安値ベース): ⑨と同じ各区間で、区間の両端を結ぶ
#     直線からの最大乖離が、trendline_dev_basis(「atr」または
#     「price_pct」)で選んだ基準以内。
#   ①〜⑧、および⑨⑩のうち山1前→山1・山1→ネック・ネック→山2の3区間が
#     揃った瞬間(confirm_floor、先読み防止のため各ピボットの右側確認が
#     終わるまで遅延させる)が"Detected"。
#   ⑪決着判定(6状態): Rejected(早すぎるブレイク - 山2/谷2からbreakout_
#     deadline_min_bars本未満での突破は無効(2026-08-03、以前はformed_bar
#     基準だったが、ピボット右本数を大きくするとformed_bar自体が山2/谷2
#     から遠ざかり、この判定が意味を失う不具合があったため山2/谷2基準に
#     変更。あわせてbreakout_deadline_min_barsがピボット右本数を下回る値は
#     ピボット右本数+3まで自動的に繰り上げる)。以前はinterval1基準の比率
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
#   ⑫早すぎるブレイクの判定は山2/谷2の直後から(2026-08-04、⑤⑥の変更に
#     合わせて再設計): ⑪のスキャンはformed_barではなく山2/谷2の次のバー
#     (true_bar+1)から始める - 山2/谷2・ネックの価格自体はそのバーが
#     閉じた時点で既知なので、confirm_j/fail_j/bars_since_top2/breakout_leg_
#     okの計算はそこから行っても未来のバーを一切使わない。ただし「パターン
#     全体(山1・ネックの右側確認含む)が存在すると確定できる」のは
#     formed_bar以降なので、結果の報告(Rejected/Confirmed/Failedをどのバー
#     に書き込むか)だけはformed_bar未満にならないようクランプする -
#     判定の計算と結果の報告バーを分離することで、breakout_deadline_
#     min_barsがどんな値でも(ピボット右本数を下回っても)「早すぎ」判定が
#     正しく機能する(以前はformed_barより前を専用の別スキャンで事前に
#     チェックしていたが、通常のスキャンをそのまま前倒しするだけで同じ
#     ことができると気づき、そちらに一本化した)。あわせて
#     breakout_deadline_min_barsをピボット右本数未満にできない繰り上げ
#     クランプ(2026-08-03に追加)も撤去した(そのクランプの根拠自体が
#     「スキャンがformed_barより前を見られない」ことだったため - ユーザー
#     判断2026-08-04)。
#
# 2026-08-02: 山1前のトレンド確認(pre_trend_lookback_bars/pre_trend_atr_mult)
# はユーザー判断で機能ごと削除した(デフォルトが既に無効=0で実質使われて
# いなかったため)。山1・山2の水準許容誤差(旧top_tolerance_pct)とブレイク
# 判定の余白(旧breakout_buffer_pct)は「値幅に対する%」から「値幅に対する
# 倍率」表記に変更(15%→0.15のように、他の*_atr_mult系パラメータと表記を
# 揃えるため)、それぞれtop_tolerance_mult/breakout_buffer_multに改名した。
#
# 上記どの判定にも、実際にそのピボットが「本物」だと確定するpivot_right_bars
# 本の確認遅延を先読み防止として組み込んでいる(_double_top_bottom_stateの
# confirm_floorと同じ考え方)。
# ---------------------------------------------------------------------------

# 2026-07-29: _double_top_bottom_shape_state本体の外側ループ(山1候補×ネック
# 候補の二重ループ)がPythonループのオーバーヘッドで5分足フル期間で2〜3分/
# 銘柄かかっていたため(プロファイリングで残り時間の9割がこの二重ループ自体、
# 中の numpy 呼び出しは1割程度と判明)、Numba(nopython, cache=True)でJIT
# コンパイルされる _shape_state_core に丸ごと移植した。ロジックは全く同じだが、
# Numbaはstr型の分岐やdictの戻り値、None/Optionalを苦手とするため:
#   - "atr"/"price_pct"等の文字列パラメータは呼び出し側でbool(*_is_pct等)に
#     変換してから渡す
#   - None穴埋めのbar変数は-1を「見つからなかった」の番兵にする
#   - 元は「窓内をnumpyでベクトル化して破綻/一致を判定→最後に採用」という
#     書き方だった(それ自体が以前Pythonループを高速化するために導入した
#     ベクトル化 - 2026-07-28)が、Numba化するとバーごとの素直なループの方が
#     速く、かつスカラー/配列どちらの型にもなり得るtol変数(Numbaのnopython
#     モードは1変数1型しか許さない)を避けられるため、バーごとに閾値を都度
#     計算する素直なループに戻した。「窓内に破綻が1つでもあれば候補全体を
#     無効にする」「最初に成立したバーで確定させ、それ以前の近接判定も含めて
#     retestedとする」という意味は全く変えていない(コメントで都度対応関係を
#     示す)。
# 検証: engine/chart_patterns.pyのgit履歴のこの変更のコミット時点で、変更前
# の実装(numpy/純Pythonループ版)の出力と、XAUUSD 5分足(20万本)・USDJPY
# 15分足(全期間58万本)×7種類のパラメータ組み合わせ×bullish/bearishの
# 全パターンで、14個の出力配列すべてがビット単位で完全一致することを確認済み
# (再度大きく手を入れる場合は同じ手順で再検証すること)。
# ---------------------------------------------------------------------------

from numba import njit


@njit(cache=True)
def _shape_spike_ok(price_a, atr_a, n, bar, window_size, is_right, is_high_type, excess_atr_max):
    if excess_atr_max <= 0.0 or window_size <= 0:
        return True
    if is_right:
        lo = bar + 1
        hi = bar + window_size
        if hi > n - 1:
            hi = n - 1
    else:
        lo = bar - window_size
        if lo < 0:
            lo = 0
        hi = bar - 1
    if lo > hi:
        return True
    if is_high_type:
        seg_max = price_a[lo]
        for k in range(lo + 1, hi + 1):
            if price_a[k] > seg_max:
                seg_max = price_a[k]
        excess = price_a[bar] - seg_max
    else:
        seg_min = price_a[lo]
        for k in range(lo + 1, hi + 1):
            if price_a[k] < seg_min:
                seg_min = price_a[k]
        excess = seg_min - price_a[bar]
    return excess <= atr_a[bar] * excess_atr_max


@njit(cache=True)
def _shape_eff_ratio(close_a, start_bar, end_bar):
    if end_bar <= start_bar:
        return 1.0
    net_move = abs(close_a[end_bar] - close_a[start_bar])
    path = 0.0
    for j in range(start_bar, end_bar):
        path += abs(close_a[j + 1] - close_a[j])
    if path <= 0.0:
        return 1.0
    return net_move / path


@njit(cache=True)
def _shape_dev_ok(high_a, low_a, atr_a, start_bar, start_price, end_bar, end_price,
                   dev_is_atr, dev_atr_mult, dev_pct):
    span = end_bar - start_bar
    if span <= 0:
        return True
    if dev_is_atr:
        tol = atr_a[end_bar] * dev_atr_mult
    else:
        # dev_pct<=0(無制限)は乖離チェック自体を無効化する(2026-08-04、
        # ユーザー判断: 「ブレイク判定余白以外すべて0=無制限にして」)。
        if dev_pct <= 0.0:
            return True
        tol = abs(end_price - start_price) * dev_pct
    for j in range(start_bar, end_bar + 1):
        line_v = start_price + (end_price - start_price) * (j - start_bar) / span
        d1 = abs(high_a[j] - line_v)
        d2 = abs(low_a[j] - line_v)
        m = d1 if d1 > d2 else d2
        if m > tol:
            return False
    return True


@njit(cache=True)
def _shape_neckline_intact(high_a, low_a, neck_bar, next_top_bar, neckline_price, bullish):
    """True if price never crosses the neckline strictly between neck_bar
    and next_top_bar - guards against a right shoulder that already breaks
    the neckline before the next extreme even forms, which none of the
    other checks catch on their own (the top1-proximity breach check only
    looks at closeness to the FIRST extreme, and the deviation/efficiency
    checks use a tolerance proportional to that leg's own price range, so a
    small-range leg can dip below/above the neckline and still pass both).
    Found 2026-08-03 via a real occurrence (a diagnostic gallery's card
    #176) whose neck->top2 leg dipped below the neckline before recovering
    to form top2 - visually a clean double top shouldn't do that."""
    for j in range(neck_bar + 1, next_top_bar):
        if bullish:
            if high_a[j] > neckline_price:
                return False
        else:
            if low_a[j] < neckline_price:
                return False
    return True


@njit(cache=True)
def _shape_extreme_intact(high_a, low_a, ext_bar, next_neck_bar, ext_price, bullish):
    """_shape_neckline_intactの逆方向版 - 山/谷(ext_bar)自体が、次のネック
    (next_neck_bar)が確定するまでの間、本当にその区間の極値のままかを確認
    する。2026-08-05、ユーザー報告(トリプルボトムの診断ギャラリー#34)で
    発覚: 谷2確定後、ネック2が確定するまでの間に谷2よりずっと深い安値が
    出ていたのに、その谷2がそのまま採用されていた(=谷2は実はその区間の
    本当の底ではなかった)。_shape_neckline_intactは「ネック→次の山」方向
    (山がネックラインを再び割らないか)しか見ておらず、逆の「山/谷→次の
    ネック」方向(山/谷がそれ自身の水準を保っているか)を見る仕組みが
    無かった。"""
    for j in range(ext_bar + 1, next_neck_bar):
        if bullish:
            if low_a[j] < ext_price:
                return False
        else:
            if high_a[j] > ext_price:
                return False
    return True


# max_bars_between_tops<=0(ユーザー入力上は「無制限」)を文字通り無制限
# スキャンにすると、強いトレンドが続く銘柄(例: ゴールド)でネックの「より
# 良い方」更新が延々と連鎖し、山1ごとにネックイベント全件近くを走査する
# O(ピボット数の2乗)的な劣化が起きる(2026-08-04、ユーザー報告: 「無制限
# にしたらゴールドとかのバックテストで異常に時間かかった」→デフォルトを
# 500にして回避していたが、「500は実質無制限のつもりで設定してるから、
# 本当は0にしたい」との要望)。3000本(15分足で約1か月)を超えて離れた
# 山1→山2はどのみちダブル/トリプルトップとして意味を持たないため、
# 「無制限」指定時もこの上限だけは内部的にかけてスキャンを打ち切る -
# ユーザーが指定できる実用的な範囲では気づかれない上限でありながら、
# 病的に長いトレンド区間での暴走を防ぐ。
_MAX_BARS_BETWEEN_TOPS_UNLIMITED_CAP = 3000

# symmetry_ratio_max/interval_symmetry_ratio_max/breakout_deadline_ratio_max
# <=0(無制限)を表す代わりの倍率(2026-08-04、ユーザー判断: 「ブレイク判定
# 余白以外すべて0=無制限にして」)。本数(interval1等)に掛けて窓の終端を
# 求めるのに使うだけなので、掛けた結果がどのみち_MAX_BARS_BETWEEN_TOPS_
# UNLIMITED_CAPやn-1で後からクランプされる - どんな現実的なデータ量でも
# 絶対に効かないくらい大きければ十分。
_UNLIMITED_RATIO = 1.0e9


@njit(cache=True)
def _shape_state_core(
    high_a, low_a, close_a, atr_a,
    ext_price_a, neck_price_a,
    ext_flags, neck_flags, ext_flags_top2,
    bullish,
    pivot_confirm_lag,
    pivot_spike_excess_atr_max, pivot_spike_window_ratio,
    min_bars_between_tops, max_bars_between_tops,
    symmetry_ratio_min, symmetry_ratio_max,
    top_tolerance_is_pct, top_tolerance_atr_mult, top_tolerance_mult,
    min_valley_depth_atr_mult, max_valley_depth_atr_mult,
    breakout_buffer_is_pct, breakout_buffer_atr_mult, breakout_buffer_mult,
    efficiency_ratio_min, efficiency_ratio_floor,
    trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct,
    efficiency_ratio_min_context,
    trendline_dev_is_atr_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
    efficiency_ratio_min_breakout,
    trendline_dev_is_atr_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
    breakout_deadline_is_top1top2, breakout_deadline_min_bars,
    breakout_deadline_ratio_min, breakout_deadline_ratio_max,
    interval_symmetry_ratio_min, interval_symmetry_ratio_max,
    terminal_bounce_close_mult,
    breakout_type_is_close,
):
    n = high_a.shape[0]
    # 2026-08-03に導入したbreakout_deadline_min_bars<pivot_confirm_lagの
    # 自動繰り上げクランプは2026-08-04に撤去した - 当時はスキャンが
    # formed_bar(=山2/谷2+pivot_confirm_lag本後)より前を絶対に見られな
    # かったため、規定本数がpivot_confirm_lagを下回ると「早すぎ判定」が
    # 構造的に発動できなくなる問題があった。今はスキャン自体を山2/谷2の
    # 直後(true_bar+1)から開始できる(下のscan_start参照 - 結果の報告
    # だけformed_bar以降まで遅らせ、判定の計算自体はそこより前のバーの
    # 既知の価格を使って行う、先読みにならない設計)ので、規定本数がどんな
    # 値でも「早すぎ判定」がそのまま機能する。よってクランプ自体が不要に
    # なった(ユーザー判断2026-08-04)。
    effective_breakout_deadline_min_bars = float(breakout_deadline_min_bars)
    # max_bars_between_tops<=0(無制限)でも、_MAX_BARS_BETWEEN_TOPS_
    # UNLIMITED_CAP(モジュール冒頭のコメント参照)だけは内部的にかける。
    effective_max_bars_between_tops = (
        max_bars_between_tops if max_bars_between_tops > 0 else _MAX_BARS_BETWEEN_TOPS_UNLIMITED_CAP
    )
    # symmetry_ratio_max/interval_symmetry_ratio_max/breakout_deadline_ratio_max
    # <=0(無制限)は_UNLIMITED_RATIO(モジュール冒頭のコメント参照)に
    # 差し替える。
    effective_symmetry_ratio_max = symmetry_ratio_max if symmetry_ratio_max > 0.0 else _UNLIMITED_RATIO
    effective_interval_symmetry_ratio_max = (
        interval_symmetry_ratio_max if interval_symmetry_ratio_max > 0.0 else _UNLIMITED_RATIO
    )
    effective_breakout_deadline_ratio_max = (
        breakout_deadline_ratio_max if breakout_deadline_ratio_max > 0.0 else _UNLIMITED_RATIO
    )
    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)      # Candidate(候補成立)
    resolve_a = np.zeros(n, dtype=np.bool_)       # Confirmed
    # 2026-08-13、ユーザー指示で6状態→3状態へ統合。Rejected(早すぎるブレイク)/
    # Failed(反対側へ抜けた)/Expired(期限切れ)を1本の Invalidated にまとめる。
    invalidated_a = np.zeros(n, dtype=np.bool_)   # Invalidated(無効)
    formed_bar_a = np.full(n, np.nan)
    top1_bar_a = np.full(n, np.nan)
    top2_bar_a = np.full(n, np.nan)
    top1_price_a = np.full(n, np.nan)
    top2_price_a = np.full(n, np.nan)
    neckline_bar_a = np.full(n, np.nan)
    neckline_price_a = np.full(n, np.nan)

    ext_events = np.flatnonzero(ext_flags)
    neck_events = np.flatnonzero(neck_flags)
    n_neck = neck_events.shape[0]

    for ei in range(ext_events.shape[0]):
        top1_true_bar = ext_events[ei]
        top1_price = ext_price_a[top1_true_bar]
        top1_confirm_bar = top1_true_bar + pivot_confirm_lag

        neck_true_bar = -1
        neck_price = 0.0
        neck_confirm_bar = -1

        start_idx = np.searchsorted(neck_events, top1_true_bar + 1, side="left")

        for ki in range(start_idx, n_neck):
            k = neck_events[ki]
            # ネック候補がまだ1つも見つかっていない間は、次の谷が現れても
            # 窓を閉じない(2026-08-06、ユーザー判断修正: 山1直後のノイズ
            # レベルの小さな谷1本で即座に窓が閉じてしまい、本物のネックに
            # 到達できなくなる不具合があったため)。ネック候補を一度採用した
            # 後、その候補より後で次に本物の谷型ピボット(ext_flags)が
            # 現れたら、そこで窓を閉じる。
            if neck_true_bar != -1:
                valley_idx = np.searchsorted(ext_events, neck_true_bar + 1, side="left")
                next_valley_bar = ext_events[valley_idx] if valley_idx < ext_events.shape[0] else n
                if k >= next_valley_bar:
                    # 窓を閉じられるのは「山2/谷2になり得る」ピボットだけ
                    # (2026-08-13、ユーザー指摘)。ここは元々「次の山型/谷型
                    # ピボットが出たら打ち切る」だけで、そのピボットが山2として
                    # 採用され得るか(下の探索と同じ許容誤差に収まるか)を見て
                    # いなかった。そのため、許容誤差の何倍も離れた=山2には
                    # 絶対に採用されないノイズ級の小さな出っ張り1本で打ち切られ、
                    # その先にある本物のネックへ到達できなくなっていた。
                    # 2026-08-06に「最初の候補が決まる前」については同じ趣旨の
                    # 修正を入れてあり、これはその取りこぼし(候補が決まった後)。
                    if top_tolerance_mult <= 0.0:
                        close_tol = np.inf
                    elif top_tolerance_is_pct:
                        close_tol = abs(top1_price - neck_price) * top_tolerance_mult
                    else:
                        close_tol = atr_a[next_valley_bar] * top_tolerance_atr_mult
                    if abs(ext_price_a[next_valley_bar] - top1_price) <= close_tol:
                        break
            interval1_candidate = k - top1_true_bar
            if interval1_candidate > effective_max_bars_between_tops:
                break
            if interval1_candidate < min_bars_between_tops:
                continue
            if neck_true_bar != -1:
                interval1_prev = neck_true_bar - top1_true_bar
                prev_win_end = neck_true_bar + int(np.floor(interval1_prev * effective_symmetry_ratio_max))
                if k > prev_win_end:
                    break
            if bullish:
                is_better = (neck_true_bar == -1) or (neck_price_a[k] > neck_price)
            else:
                is_better = (neck_true_bar == -1) or (neck_price_a[k] < neck_price)
            if not is_better:
                continue
            # 山1がネックが確定するまでの間、本当にその区間の極値のままか
            # (_shape_extreme_intactのdocstring参照)。確定変数(neck_true_bar/
            # neck_price)へ代入するのは検証を通ってから - 先に代入してから
            # 検証で弾くと、弾かれた候補がneck_true_barに残ったまま次の
            # 候補との比較(is_better)や窓を閉じる判定を汚染してしまう
            # (2026-08-06、ユーザー指摘で発覚した実際の不具合)。
            if not _shape_extreme_intact(high_a, low_a, top1_true_bar, k, top1_price, bullish):
                continue
            neck_price = neck_price_a[k]
            neck_true_bar = k
            neck_confirm_bar = neck_true_bar + pivot_confirm_lag

            interval1 = neck_true_bar - top1_true_bar

            top1_right_window = int(round(interval1 * pivot_spike_window_ratio))
            top1_right_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_right_window,
                                             True, not bullish, pivot_spike_excess_atr_max)
            neck_left_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck_true_bar, top1_right_window,
                                            False, bullish, pivot_spike_excess_atr_max)

            win_start = neck_true_bar + int(np.ceil(interval1 * symmetry_ratio_min))
            win_end = neck_true_bar + int(np.floor(interval1 * effective_symmetry_ratio_max))
            # ネック→山2の本数も、山1→ネックと同じmin/max_bars_between_tops
            # で追加拘束する(2026-08-04、ユーザー判断: 「山1→ネックと同じ
            # ところでパラメーターを変更できるように」) - 比率ベースの窓と
            # 絶対本数ベースの窓、両方を満たす範囲まで絞り込む。
            abs_win_start = neck_true_bar + min_bars_between_tops
            if abs_win_start > win_start:
                win_start = abs_win_start
            abs_win_end = neck_true_bar + effective_max_bars_between_tops
            if abs_win_end < win_end:
                win_end = abs_win_end
            if win_end > n - 1:
                win_end = n - 1
            if win_start > win_end:
                continue

            # top_tolerance_mult<=0(無制限)は乖離許容を無限大にする
            # (2026-08-04、ユーザー判断: 「ブレイク判定余白以外すべて0=無制限に
            # して」)。
            top_tolerance_value = (
                np.inf if top_tolerance_mult <= 0.0 else abs(top1_price - neck_price) * top_tolerance_mult
            )

            window_invalidated = False
            top2_true_bar = -1
            top2_price = 0.0
            for j in range(win_start, win_end + 1):
                if top_tolerance_is_pct:
                    tol_j = top_tolerance_value
                else:
                    tol_j = atr_a[j] * top_tolerance_atr_mult
                if bullish:
                    breach = low_a[j] < (top1_price - tol_j)
                else:
                    breach = high_a[j] > (top1_price + tol_j)
                if breach:
                    window_invalidated = True
                    break
                # 谷2(ダブルの最後の点)が出現してから、(谷2→ネックの価格差×
                # terminal_bounce_close_mult)分だけ反発したら、そこで窓を
                # 閉じる(2026-08-06、ユーザー設計: 谷2の窓が閉じた後の
                # 安値割れはパターン継続、閉じる前の安値割れは無効、という
                # 区別を成立させるための専用ルール)。無効化(window_invalidated)
                # とは違い、ここまでに見つけた谷2はそのまま確定として使う。
                # 判定は必ずこのバーで谷2を更新する"前"の値で行う - 更新後の
                # 値で同じバーの反対側(高値側)をチェックすると、1本のバーの
                # ヒゲの広さだけで即座に窓が閉じてしまい、実質「最初に一致
                # した安値で固定」に逆戻りしてしまう(2026-08-06、ユーザー
                # 報告で発覚した実際の不具合 - 想定と逆に確定件数が減った)。
                if top2_true_bar != -1 and terminal_bounce_close_mult > 0.0:
                    bounce_threshold = abs(neck_price - top2_price) * terminal_bounce_close_mult
                    if bullish:
                        if high_a[j] > top2_price + bounce_threshold:
                            break
                    else:
                        if low_a[j] < top2_price - bounce_threshold:
                            break
                if ext_flags_top2[j] and abs(ext_price_a[j] - top1_price) <= tol_j:
                    if bullish:
                        is_more_extreme = (top2_true_bar == -1) or (ext_price_a[j] < top2_price)
                    else:
                        is_more_extreme = (top2_true_bar == -1) or (ext_price_a[j] > top2_price)
                    if is_more_extreme:
                        top2_true_bar = j
                        top2_price = ext_price_a[j]

            if window_invalidated or top2_true_bar == -1:
                continue
            if not _shape_neckline_intact(high_a, low_a, neck_true_bar, top2_true_bar, neck_price, bullish):
                continue
            # 山2/谷2は右側確認不要(2026-08-04、モジュール冒頭コメント参照) -
            # 確定は自分自身のバーで完結する。それでも本当に頂点だったかは
            # ブレイク判定側のfail_j(山1・山2の高い方+余白を超えたら
            # Failed)が代わりに担保する。
            top2_confirm_bar = top2_true_bar

            interval2 = top2_true_bar - neck_true_bar
            top2_left_window = int(round(interval2 * pivot_spike_window_ratio))
            top2_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top2_true_bar, top2_left_window,
                                            False, not bullish, pivot_spike_excess_atr_max)
            neck_right_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck_true_bar, top2_left_window,
                                             True, bullish, pivot_spike_excess_atr_max)
            if not (neck_left_ok or neck_right_ok):
                continue

            avg_extreme = (top1_price + top2_price) / 2.0
            if bullish:
                depth = neck_price - avg_extreme
            else:
                depth = avg_extreme - neck_price
            depth_min = atr_a[top2_true_bar] * min_valley_depth_atr_mult
            if max_valley_depth_atr_mult <= 0.0:
                depth_max = np.inf
            else:
                depth_max = atr_a[top2_true_bar] * max_valley_depth_atr_mult
            if not (depth_min <= depth <= depth_max):
                continue

            breakout_buffer_value = depth * breakout_buffer_mult

            if breakout_buffer_is_pct:
                pre_buf = breakout_buffer_value
            else:
                pre_buf = atr_a[top1_true_bar] * breakout_buffer_atr_mult
            if bullish:
                pre_level = neck_price + pre_buf
            else:
                pre_level = neck_price - pre_buf

            pre_bar = -1
            for j in range(top1_true_bar - 1, -1, -1):
                if low_a[j] <= pre_level <= high_a[j]:
                    pre_bar = j
                    break
            if pre_bar == -1:
                continue

            top1_left_window = int(round((top1_true_bar - pre_bar) * pivot_spike_window_ratio))
            top1_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_left_window,
                                            False, not bullish, pivot_spike_excess_atr_max)
            if not (top1_left_ok or top1_right_ok):
                continue

            interval0 = neck_true_bar - pre_bar

            if bullish:
                seg_min = low_a[pre_bar]
                for j in range(pre_bar + 1, neck_true_bar + 1):
                    if low_a[j] < seg_min:
                        seg_min = low_a[j]
                if top1_price > seg_min:
                    continue
            else:
                seg_max = high_a[pre_bar]
                for j in range(pre_bar + 1, neck_true_bar + 1):
                    if high_a[j] > seg_max:
                        seg_max = high_a[j]
                if top1_price < seg_max:
                    continue

            confirm_floor = top1_confirm_bar
            if neck_confirm_bar > confirm_floor:
                confirm_floor = neck_confirm_bar
            if top2_confirm_bar > confirm_floor:
                confirm_floor = top2_confirm_bar
            if confirm_floor >= n:
                continue

            # 2026-08-04(ユーザー判断)、3グループに分離: eff1(山1前→山1)は
            # 形そのものではなく前後関係でしかないので緩めた基準(_context)。
            # eff2/eff3(山1→ネック・ネック→山2)は形を定義する核心区間なので
            # 厳しい基準(無印)。eff4(山2→ブレイク、下のbreakout_leg_ok側)は
            # 実際にエントリーの引き金になる瞬間で重要度が高いが、性質が異なる
            # (短い・方向性が出やすい)区間なので独立した基準(_breakout)。
            eff1 = _shape_eff_ratio(close_a, pre_bar, top1_true_bar)
            eff2 = _shape_eff_ratio(close_a, top1_true_bar, neck_true_bar)
            eff3 = _shape_eff_ratio(close_a, neck_true_bar, top2_true_bar)
            core_legs_ok = (
                eff2 >= efficiency_ratio_floor
                and eff3 >= efficiency_ratio_floor
                and (eff2 + eff3) / 2.0 >= efficiency_ratio_min
                and _shape_dev_ok(high_a, low_a, atr_a, top1_true_bar, top1_price, neck_true_bar, neck_price,
                                  trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                and _shape_dev_ok(high_a, low_a, atr_a, neck_true_bar, neck_price, top2_true_bar, top2_price,
                                  trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
            )
            context_legs_ok = (
                eff1 >= efficiency_ratio_min_context
                and _shape_dev_ok(high_a, low_a, atr_a, pre_bar, pre_level, top1_true_bar, top1_price,
                                  trendline_dev_is_atr_context, trendline_dev_atr_mult_context, trendline_dev_pct_context)
            )
            legs_ok = core_legs_ok and context_legs_ok
            if not legs_ok:
                continue

            formed_bar = confirm_floor
            detected_a[formed_bar] = True

            worse_extreme = min(top1_price, top2_price) if bullish else max(top1_price, top2_price)

            # スキャンは山2/谷2の直後(true_bar+1)から始める - formed_barより
            # 前でも、山2/谷2・ネックの価格自体はそのバーが閉じた時点で既知
            # なので、判定の計算(confirm_j/fail_j/bars_since_top2/breakout_leg_
            # ok)はここから行って問題ない(未来のバーは一切使わない)。ただし
            # 「パターン全体(山1・ネックの右側確認含む)が存在すると確定
            # できる」のはformed_bar以降なので、結果の報告(outcome_bar)だけ
            # はformed_bar未満にならないよう後段でクランプする - 2026-08-04、
            # 「山2は左側のみで確定」への変更に合わせてこの一本化した設計に
            # した(以前はformed_barより前を別関数で事前スキャンしていたが、
            # 通常のスキャンをそのまま前倒しするだけで同じことができ、
            # breakout_deadline_min_barsがどんな値でも「早すぎ判定」が正しく
            # 機能するようになった)。
            expire_bars = interval1 * effective_breakout_deadline_ratio_max
            scan_start = top2_true_bar + 1
            scan_end = top2_true_bar + int(np.ceil(expire_bars))
            if scan_end > n - 1:
                scan_end = n - 1

            outcome = 4  # expired
            outcome_bar = scan_end

            if scan_start <= scan_end:
                found = False
                for j in range(scan_start, scan_end + 1):
                    if breakout_buffer_is_pct:
                        buf_j = breakout_buffer_value
                    else:
                        buf_j = atr_a[j] * breakout_buffer_atr_mult

                    if breakout_type_is_close:
                        if bullish:
                            confirm_j = close_a[j] > (neck_price + buf_j)
                            fail_j = close_a[j] < (worse_extreme - buf_j)
                        else:
                            confirm_j = close_a[j] < (neck_price - buf_j)
                            fail_j = close_a[j] > (worse_extreme + buf_j)
                    else:
                        if bullish:
                            confirm_j = high_a[j] > (neck_price + buf_j)
                            fail_j = low_a[j] < (worse_extreme - buf_j)
                        else:
                            confirm_j = low_a[j] < (neck_price - buf_j)
                            fail_j = high_a[j] > (worse_extreme + buf_j)

                    if confirm_j or fail_j:
                        found = True
                        if fail_j:
                            outcome = 3  # failed
                            outcome_bar = j
                        else:
                            bars_since_top2 = j - top2_true_bar
                            if breakout_deadline_is_top1top2:
                                reject_bars = effective_breakout_deadline_min_bars
                            else:
                                reject_bars = interval1 * breakout_deadline_ratio_min
                            if bars_since_top2 < reject_bars:
                                outcome = 1  # rejected
                                outcome_bar = j
                            else:
                                time1 = j - neck_true_bar
                                symmetric_ok = (
                                    time1 * interval_symmetry_ratio_min <= interval0 <= time1 * effective_interval_symmetry_ratio_max
                                )
                                eff4 = _shape_eff_ratio(close_a, top2_true_bar, j)
                                if bullish:
                                    seg_min2 = low_a[neck_true_bar]
                                    for jj in range(neck_true_bar + 1, j + 1):
                                        if low_a[jj] < seg_min2:
                                            seg_min2 = low_a[jj]
                                    no_undercut = top2_price <= seg_min2
                                else:
                                    seg_max2 = high_a[neck_true_bar]
                                    for jj in range(neck_true_bar + 1, j + 1):
                                        if high_a[jj] > seg_max2:
                                            seg_max2 = high_a[jj]
                                    no_undercut = top2_price >= seg_max2

                                top2_right_window = int(round((j - top2_true_bar) * pivot_spike_window_ratio))
                                max_window = j - top2_true_bar
                                if top2_right_window > max_window:
                                    top2_right_window = max_window
                                top2_right_ok = _shape_spike_ok(
                                    ext_price_a, atr_a, n, top2_true_bar, top2_right_window,
                                    True, not bullish, pivot_spike_excess_atr_max,
                                )
                                top2_isolation_ok = top2_left_ok or top2_right_ok

                                if breakout_type_is_close:
                                    end_price_for_dev = close_a[j]
                                else:
                                    end_price_for_dev = high_a[j] if bullish else low_a[j]

                                breakout_leg_ok = (
                                    symmetric_ok
                                    and eff4 >= efficiency_ratio_min_breakout
                                    and no_undercut
                                    and top2_isolation_ok
                                    and _shape_dev_ok(high_a, low_a, atr_a, top2_true_bar, top2_price, j, end_price_for_dev,
                                                       trendline_dev_is_atr_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout)
                                )
                                if not breakout_leg_ok:
                                    outcome = 1  # rejected
                                    outcome_bar = j
                                else:
                                    outcome = 2  # confirmed
                                    outcome_bar = j
                        break

            # 判定自体はformed_barより前のバーで完結していることがある
            # (山2/谷2の直後から見ているため) - その場合でも報告はパターン
            # 全体の存在が確定するformed_bar以降にする(先読み防止、
            # モジュール冒頭のコメント参照)。
            if outcome_bar < formed_bar:
                outcome_bar = formed_bar

            # exists_a/formed_bar_aへの範囲書き込みは、別候補(別のei/ki)自身の
            # formed_barバー(detected_a[idx]==True)を上書きしない - 上書き
            # すると、その候補自身のdetected_a==Trueは残ったまま
            # formed_bar_a[そのバー]だけ別候補の値に化けてしまい、そこから
            # top1_bar_a等を逆引きすると全く別の候補の中身を拾ってしまう
            # (2026-08-04発見、既存の仕様上の特性 - 複数候補の存在区間が
            # 重なった際、後から処理された広い範囲の書き込みが先に処理された
            # 候補自身のアンカーバーを踏みつけていた)。自分自身のformed_bar
            # バーは常に書き込む。
            exists_end = outcome_bar
            for _idx in range(formed_bar, exists_end + 1):
                if _idx == formed_bar or not detected_a[_idx]:
                    exists_a[_idx] = True
                    formed_bar_a[_idx] = formed_bar
            top1_bar_a[formed_bar] = top1_true_bar
            top2_bar_a[formed_bar] = top2_true_bar
            top1_price_a[formed_bar] = top1_price
            top2_price_a[formed_bar] = top2_price
            neckline_bar_a[formed_bar] = neck_true_bar
            neckline_price_a[formed_bar] = neck_price

            # outcome==2 のみ Confirmed。それ以外(1=早すぎるブレイク /
            # 3=反対側へ抜けた / 4=期限切れ)は全て Invalidated へ(3状態統合)。
            if outcome == 2:
                resolve_a[outcome_bar] = True
            else:
                invalidated_a[outcome_bar] = True

    return (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a, top1_bar_a, top2_bar_a,
        top1_price_a, top2_price_a, neckline_bar_a, neckline_price_a,
    )

def _double_top_bottom_shape_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.2,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.075,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.25,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.8,
    breakout_deadline_basis: str = "top1_top2",
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_min: float = 0.3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
) -> dict[str, pd.Series]:
    """モジュール冒頭のコメント参照。bullish=Trueでダブルボトム、Falseで
    ダブルトップ(高値/安値・上下を反転させた鏡像)。

    top_tolerance_basis: 山1・山2の水準許容誤差の基準。"atr"は固定ATR倍率
    (パターンの規模に関わらず一定なので、期間が短い/値動きが小さいパターン
    では相対的に緩すぎ、期間が長い/値動きが大きいパターンでは相対的に厳し
    すぎる傾向がある)。"price_pct"は山1→ネックの値幅(山2探索時点で既知の
    量)に対する倍率で、trendline_dev_basisと同じ考え方でパターンの規模に
    応じて許容誤差がスケールする。

    breakout_buffer_basis: ネックライン付近での「本物のブレイク/失敗」判定
    に使う余白の基準。top_tolerance_basisと同じ理由で"atr"は固定ATR倍率、
    "price_pct"は谷の深さ(⑧で計算済み、山1前点探索・ブレイク確定・失敗
    判定・リテスト判定の全てで谷の深さは既知)に対する倍率。谷の深さ自体は
    (min/max_valley_depth_atr_multで判定する)パターンの規模の主指標なので
    ATR倍率のままにしてある(top_toleranceやbreakout_bufferのような「別の
    値幅と比較する許容誤差」ではないため)。

    breakout_deadline_basis: ブレイク猶予(早すぎる/遅すぎるの判定)の方式。
    "top1_top2"(既定、double_top_shape/double_bottom_shapeが使う唯一の方式)
    は、早すぎる判定をbreakout_deadline_min_bars(山2/谷2からの固定本数)、
    遅すぎる判定を山1→山2の本数×breakout_deadline_ratio_maxで行う。
    breakout_deadline_min_barsはピボット右本数(pivot_right_bars)を下回る
    設定にはできない(パターンの確定自体が山2/谷2+ピボット右本数本かかる
    ため、下回ると確定した瞬間に早すぎ判定が意味を失ってしまう) -
    下回る値を指定した場合はピボット右本数+3まで自動的に繰り上げる
    (2026-08-03、ユーザー判断)。
    "interval1"は2026-07-27に前者へ変更する前の旧方式(早すぎる判定も
    breakout_deadline_ratio_min×山1→ネックの本数(比率)で行う)で、比較用に
    別indicatorとして提供していたdouble_top_shape_v1/double_bottom_shape_v1
    が使っていたが、2026-07-29にそれらのindicator自体を削除したため現在は
    呼び出し元が存在しない(関数自体はまだこの基準を受け付ける)。

    terminal_bounce_close_mult: 谷2(最後の点)の探索窓を、期間・本数だけで
    なく価格の反発でも閉じるための倍率(2026-08-06、ユーザー設計)。谷2候補
    が一度見つかった後、そこから(谷2→ネックの価格差×この倍率)分だけ
    反発(bullishなら高値側へ上昇)したら、それ以上安い谷2を探すのをやめて
    確定させる。0以下で無効(従来通り期間・本数の窓だけで閉じる)。この
    ルールで窓が閉じた"後"に安値割れが起きてもパターンは継続扱いのまま-
    無効になるのは、この窓が閉じる"前"に許容誤差を超える安値が出た場合だけ
    (window_invalidated、別の既存チェック)。"""
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

    # pivot_left_bars/pivot_right_barsはマイナスを許さない(2026-08-05、
    # ユーザー判断: 「全て0以上にできない?」) - UI側のmin=0ガードと同じ
    # 制約をエンジン側でも保証する(保存済みJSON経由でUIを介さず渡された
    # 場合の保険)。両方0は「確認材料が左右ゼロ」で意味を持たない状態
    # (2026-08-05、ユーザー判断: 「左右どちらも0にはできないようにする」)
    # なので、片方だけ最低1に引き上げる。
    pivot_left_bars = max(0, pivot_left_bars)
    pivot_right_bars = max(0, pivot_right_bars)
    if pivot_left_bars == 0 and pivot_right_bars == 0:
        pivot_left_bars = 1

    # 山1→ネック・ネック→山2、各区間の最短本数(旧min_bars_between_tops、
    # ユーザー入力の独立パラメータだった)は常にピボット右本数(pivot_
    # right_bars)を使う(2026-08-05、トリプル版と同じ理由・ユーザー判断
    # - そちらのコメント参照。区間がピボット右本数より短いと、片方のピボットが
    # まだ確認しきれていないうちにもう片方が始まってしまい、実質1〜2本しか
    # ない不自然な区間が通ってしまう)。
    min_bars_between_tops = pivot_right_bars

    # 「山」= 高値側の反転点、「谷」= 安値側の反転点。bullish(ダブルボトム)
    # は谷1→ネック(高値側)→谷2、ダブルトップはその鏡像。
    ext_price_a = low_a if bullish else high_a  # 山1/山2側(反転点そのもの)
    neck_price_a = high_a if bullish else low_a  # ネック側

    # ① 値幅込みのピボット判定 - 通常のピボット判定(_detect_pivot_highs/
    # _detect_pivot_lows)に、「左右の境界からATR×prominence_atr_mult以上
    # 離れているか」という値幅の下限を追加でANDする。pivot_left_bars/
    # pivot_right_barsの片方が0の時は、その側の確認を丸ごと省略して
    # 反対側だけで判定する(2026-08-05、ユーザー判断: 「ピボット左本数だけ
    # 0にしたらピボット右本数だけで判断ということにできない?」) -
    # _pivot_flags/_prominence_flags(モジュール冒頭)が0/非0を見て自動で
    # 両側確認・右側のみ・左側のみを切り替える。両方0にはできない前提
    # (呼び出し元で保証、フロントエンドのUI側でも防止)。
    boundary_other_a = high_a if bullish else low_a  # 反転点側の判定に使う「境界」の反対サイド
    prom_thresh = atr_a * prominence_atr_mult
    ext_flags = (
        _pivot_flags(low if bullish else high, pivot_left_bars, pivot_right_bars, not bullish).to_numpy()
        & _prominence_flags(ext_price_a, boundary_other_a, pivot_left_bars, pivot_right_bars, prom_thresh, not bullish)
    )

    neck_boundary_other_a = low_a if bullish else high_a
    neck_flags = (
        _pivot_flags(high if bullish else low, pivot_left_bars, pivot_right_bars, bullish).to_numpy()
        & _prominence_flags(neck_price_a, neck_boundary_other_a, pivot_left_bars, pivot_right_bars, prom_thresh, bullish)
    )

    # 山2/谷2(ブレイクへ直接つながる最後の反転点)専用: 右側確認を外した
    # ピボット判定(2026-08-04、ユーザー判断: 「山2は左だけで右は無でも
    # よくないか」)。山1・ネックはext_flags/neck_flags(上の一般化済みの
    # 判定)のまま。値幅チェックはpivot_right_bars=0として渡し、右側を
    # 見ない(_prominence_flags参照)。
    plain_pivot_ext_left_only = (
        _detect_pivot_lows_left_only(low, pivot_left_bars)
        if bullish
        else _detect_pivot_highs_left_only(high, pivot_left_bars)
    ).to_numpy()
    prominence_ok_ext_left_only = _prominence_flags(ext_price_a, boundary_other_a, pivot_left_bars, 0, prom_thresh, not bullish)
    ext_flags_top2 = plain_pivot_ext_left_only & prominence_ok_ext_left_only

    pivot_confirm_lag = pivot_right_bars

    # 二重ループの本体はNumba(nopython, cache=True)でJITコンパイルされる
    # _shape_state_coreに丸ごと移植済み(モジュール冒頭のこの関数の直前を
    # 参照)。文字列パラメータ(*_basis/breakout_type)はbool/int codeに変換
    # してから渡す。
    (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a, top1_bar_a, top2_bar_a,
        top1_price_a, top2_price_a, neckline_bar_a, neckline_price_a,
    ) = _shape_state_core(
        high_a, low_a, close_a, atr_a,
        ext_price_a, neck_price_a,
        ext_flags, neck_flags, ext_flags_top2,
        bool(bullish),
        int(pivot_confirm_lag),
        float(pivot_spike_excess_atr_max), float(pivot_spike_window_ratio),
        int(min_bars_between_tops), int(max_bars_between_tops),
        float(symmetry_ratio_min), float(symmetry_ratio_max),
        top_tolerance_basis == "price_pct", float(top_tolerance_atr_mult), float(top_tolerance_mult),
        float(min_valley_depth_atr_mult), float(max_valley_depth_atr_mult),
        breakout_buffer_basis == "price_pct", float(breakout_buffer_atr_mult), float(breakout_buffer_mult),
        float(efficiency_ratio_min), float(efficiency_ratio_floor),
        trendline_dev_basis == "atr", float(trendline_dev_atr_mult), float(trendline_dev_pct),
        float(efficiency_ratio_min_context),
        trendline_dev_basis_context == "atr", float(trendline_dev_atr_mult_context), float(trendline_dev_pct_context),
        float(efficiency_ratio_min_breakout),
        trendline_dev_basis_breakout == "atr", float(trendline_dev_atr_mult_breakout), float(trendline_dev_pct_breakout),
        breakout_deadline_basis == "top1_top2", int(breakout_deadline_min_bars),
        float(breakout_deadline_ratio_min), float(breakout_deadline_ratio_max),
        float(interval_symmetry_ratio_min), float(interval_symmetry_ratio_max),
        float(terminal_bounce_close_mult),
        breakout_type == "close",
    )

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "candidate": pd.Series(detected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "invalidated": pd.Series(invalidated_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "top1_bar": pd.Series(top1_bar_a, index=idx_index),
        "top2_bar": pd.Series(top2_bar_a, index=idx_index),
        "top1_price": pd.Series(top1_price_a, index=idx_index),
        "top2_price": pd.Series(top2_price_a, index=idx_index),
        "neckline_bar": pd.Series(neckline_bar_a, index=idx_index),
        "neckline_price": pd.Series(neckline_price_a, index=idx_index),
    }


_SHAPE_STATE_KEYS = {
    "candidate": "candidate",
    "confirmed": "confirmed",
    "invalidated": "invalidated",
    "exists": "exists",
    # 後方互換 - 旧6状態名で保存された戦略のため。2026-08-13に
    # Candidate/Confirmed/Invalidated の3状態へ統合した。
    "detected": "candidate",
    "rejected": "invalidated",
    "failed_after_retest": "invalidated",
    "failed_before_retest": "invalidated",
    "expired": "invalidated",
}


def double_bottom_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 5,
    pivot_right_bars: int = 5,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.2,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.075,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.25,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """ダブルボトム(形状判定版) - モジュール冒頭のコメント参照。
    Candidate(候補成立)/Confirmed(ネックライン突破)/Invalidated(無効)の
    3状態をstateパラメータで選べる(2026-08-13に旧6状態から統合。
    Rejected/Failed/Expired は全て Invalidated にまとめた。リテスト判定余白は
    廃止)。既存のdouble_bottom/double_bottom_pivotとは完全に独立した実装で、
    そちらは一切変更していない。"""
    result = _double_top_bottom_shape_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_mult,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_mult,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        efficiency_ratio_min_context,
        trendline_dev_basis_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
        efficiency_ratio_min_breakout,
        trendline_dev_basis_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        terminal_bounce_close_mult,
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
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.2,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.075,
    efficiency_ratio_min: float = 0.25,
    efficiency_ratio_floor: float = 0.07,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.8,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.25,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.8,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.67,
    interval_symmetry_ratio_max: float = 1.5,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
    **p,
) -> np.ndarray:
    """Mirror image of double_bottom_shape - ダブルトップ(形状判定版)。"""
    result = _double_top_bottom_shape_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_mult,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_mult,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        efficiency_ratio_min_context,
        trendline_dev_basis_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
        efficiency_ratio_min_breakout,
        trendline_dev_basis_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        terminal_bounce_close_mult,
        breakout_type,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Triple Top/Bottom(形状判定版・2026-08-13) - ダブルトップ/ボトムST
# (_shape_state_core、直前の一連の関数)を土台に、2山→3山・1ネック→2ネック
# へ拡張したもの。詳細な設計根拠・査読での採否は
# docs/pattern_spec_triple_top_bottom_shape.md を参照(本コードはその確定版
# を実装したもの)。ここでは実装上の要点だけ簡潔に記す:
#   - 構成点は5点: 山1→ネック1→山2→ネック2→山3。山1・ネック1・山2・ネック2は
#     両側確認(ext_flags/neck_flags)、山3のみダブルの山2と同じ左側のみ
#     確認(ext_flags_top3、右側待ちゼロ)。
#   - 山2(中間点)は「窓内で総当り」ではなく単一の正準点に確定する(査読B):
#     窓W2内の両側確認ピボットのうち、山1との差が許容誤差tol以内で、かつ
#     価格が最も高い(bullishなら最も低い)1本を採用する(2026-08-13、
#     ユーザー指摘で「山1に最も近い」から訂正 - 選ばれなかった側により
#     高い/低い山が取り残されるのを防ぐため)。tolによる足切り(breach)自体は
#     不変。
#   - 山1・山2・山3の水準許容誤差は「山1個別基準」ではなく「3点全体の
#     最高値-最安値がtol以内」で判定する(2026-08-14、ユーザー判断で再修正
#     - 特定の1点を基準にすると、基準にしなかった2点同士は最大2×tolまで
#     ズレて良いことになってしまう抜け道があり、緩すぎた。3点まとめての
#     値幅判定ならその抜け道が無く、旧版(削除済み)・一般的なトリプル
#     トップの定義とも一致する)。山2はこの時点で山1との差が既にtol以内と
#     保証されているため、山3を探す段階でのみ「山1・山2・候補3点の値幅」
#     を計算すれば足りる(lo12/hi12/worst12、窓の破綻判定・ネック2側の
#     窓打ち切り判定・採用可否のすべてで共有)。
#   - 山1前点(pre_bar)・時間0(interval0)の左側ジオメトリは常にネック1を
#     軸に固定する(査読の重大な指摘: min/maxネック水準を左側にも使うと
#     山2を窓に巻き込み、ほぼ全件が不成立になる)。
#   - ブレイク判定(confirm_j/fail_j)にだけ、2ネックの低い方/高い方
#     (bullishはmax、v1では新パラメータneck_tolerance_multで2ネックの
#     近接を要求)を使う。
#   - 時間0/時間1の対称性チェックの基準点は「山2」にする(ユーザー判断
#     2026-08-13: 「ダブルはネックがパターンの中心(前後1点ずつ)だから
#     そのまま。トリプルは山1→ネック1→山2→ネック2→山3の5点構成で、山2が
#     前後2点ずつを従えるパターンの中心に来るから山2を基準にしてほしい」)。
#     ダブル側(_shape_state_core)は基準点をネックのまま変更していない
#     (一度山2基準へ変更したが、指示の対象がトリプルだったと判明したため
#     撤回した)。interval0 = 山2_bar - pre_bar、time1 = 判定バー - 山2_bar。
#     設計書(pattern_spec_triple_top_bottom_shape.md)執筆時点ではネック
#     (当時のneck_ref)基準と書かれていたが、この決定でその後さらに変更した。
#   - 中央の山2は孤立度チェック(_shape_spike_ok)の対象外(査読E、稀少化
#     対策)。山1・ネック1・ネック2・山3の4点にのみ適用。
# ---------------------------------------------------------------------------


@njit(cache=True)
def _shape_state_core3(
    high_a, low_a, close_a, atr_a,
    ext_price_a, neck_price_a,
    ext_flags, neck_flags, ext_flags_top3,
    bullish,
    pivot_confirm_lag,
    pivot_spike_excess_atr_max, pivot_spike_window_ratio,
    min_bars_between_tops, max_bars_between_tops,
    symmetry_ratio_min, symmetry_ratio_max,
    top_tolerance_is_pct, top_tolerance_atr_mult, top_tolerance_mult,
    min_valley_depth_atr_mult, max_valley_depth_atr_mult,
    breakout_buffer_is_pct, breakout_buffer_atr_mult, breakout_buffer_mult,
    efficiency_ratio_min, efficiency_ratio_floor,
    trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct,
    efficiency_ratio_min_context,
    trendline_dev_is_atr_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
    efficiency_ratio_min_breakout,
    trendline_dev_is_atr_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
    breakout_deadline_is_top1top2, breakout_deadline_min_bars,
    breakout_deadline_ratio_min, breakout_deadline_ratio_max,
    interval_symmetry_ratio_min, interval_symmetry_ratio_max,
    terminal_bounce_close_mult,
    breakout_type_is_close,
    neck_tolerance_mult,
):
    n = high_a.shape[0]
    effective_breakout_deadline_min_bars = float(breakout_deadline_min_bars)
    effective_max_bars_between_tops = (
        max_bars_between_tops if max_bars_between_tops > 0 else _MAX_BARS_BETWEEN_TOPS_UNLIMITED_CAP
    )
    effective_symmetry_ratio_max = symmetry_ratio_max if symmetry_ratio_max > 0.0 else _UNLIMITED_RATIO
    effective_interval_symmetry_ratio_max = (
        interval_symmetry_ratio_max if interval_symmetry_ratio_max > 0.0 else _UNLIMITED_RATIO
    )
    effective_breakout_deadline_ratio_max = (
        breakout_deadline_ratio_max if breakout_deadline_ratio_max > 0.0 else _UNLIMITED_RATIO
    )

    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)
    resolve_a = np.zeros(n, dtype=np.bool_)
    invalidated_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    top1_bar_a = np.full(n, np.nan)
    neck1_bar_a = np.full(n, np.nan)
    top2_bar_a = np.full(n, np.nan)
    neck2_bar_a = np.full(n, np.nan)
    top3_bar_a = np.full(n, np.nan)
    top1_price_a = np.full(n, np.nan)
    neck1_price_a = np.full(n, np.nan)
    top2_price_a = np.full(n, np.nan)
    neck2_price_a = np.full(n, np.nan)
    top3_price_a = np.full(n, np.nan)

    ext_events = np.flatnonzero(ext_flags)
    neck_events = np.flatnonzero(neck_flags)
    n_neck = neck_events.shape[0]

    for ei in range(ext_events.shape[0]):
        top1_true_bar = ext_events[ei]
        top1_price = ext_price_a[top1_true_bar]
        top1_confirm_bar = top1_true_bar + pivot_confirm_lag

        neck1_true_bar = -1
        neck1_price = 0.0
        neck1_confirm_bar = -1

        start_idx1 = np.searchsorted(neck_events, top1_true_bar + 1, side="left")

        for ki1 in range(start_idx1, n_neck):
            k1 = neck_events[ki1]

            # 窓打ち切り規則A(モジュール冒頭②参照)をネック1探索へ複製。
            if neck1_true_bar != -1:
                valley_idx = np.searchsorted(ext_events, neck1_true_bar + 1, side="left")
                next_valley_bar = ext_events[valley_idx] if valley_idx < ext_events.shape[0] else n
                if k1 >= next_valley_bar:
                    if top_tolerance_mult <= 0.0:
                        close_tol = np.inf
                    elif top_tolerance_is_pct:
                        close_tol = abs(top1_price - neck1_price) * top_tolerance_mult
                    else:
                        close_tol = atr_a[next_valley_bar] * top_tolerance_atr_mult
                    if abs(ext_price_a[next_valley_bar] - top1_price) <= close_tol:
                        break

            i1_candidate = k1 - top1_true_bar
            if i1_candidate > effective_max_bars_between_tops:
                break
            if i1_candidate < min_bars_between_tops:
                continue
            if neck1_true_bar != -1:
                i1_prev = neck1_true_bar - top1_true_bar
                prev_win_end = neck1_true_bar + int(np.floor(i1_prev * effective_symmetry_ratio_max))
                if k1 > prev_win_end:
                    break
            if bullish:
                is_better1 = (neck1_true_bar == -1) or (neck_price_a[k1] > neck1_price)
            else:
                is_better1 = (neck1_true_bar == -1) or (neck_price_a[k1] < neck1_price)
            if not is_better1:
                continue
            if not _shape_extreme_intact(high_a, low_a, top1_true_bar, k1, top1_price, bullish):
                continue
            neck1_price = neck_price_a[k1]
            neck1_true_bar = k1
            neck1_confirm_bar = neck1_true_bar + pivot_confirm_lag

            i1 = neck1_true_bar - top1_true_bar

            top1_right_window = int(round(i1 * pivot_spike_window_ratio))
            top1_right_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_right_window,
                                             True, not bullish, pivot_spike_excess_atr_max)
            neck1_left_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck1_true_bar, top1_right_window,
                                             False, bullish, pivot_spike_excess_atr_max)

            # 全山共有の許容誤差基準幅(山1→ネック1の値幅、設計判断2)。以降の
            # 山2窓・ネック2窓打ち切り・山3窓すべてこの1回計算した値を使う。
            base_leg = abs(top1_price - neck1_price)
            top_tolerance_value = np.inf if top_tolerance_mult <= 0.0 else base_leg * top_tolerance_mult

            win_start2 = neck1_true_bar + int(np.ceil(i1 * symmetry_ratio_min))
            win_end2 = neck1_true_bar + int(np.floor(i1 * effective_symmetry_ratio_max))
            abs_win_start2 = neck1_true_bar + min_bars_between_tops
            if abs_win_start2 > win_start2:
                win_start2 = abs_win_start2
            abs_win_end2 = neck1_true_bar + effective_max_bars_between_tops
            if abs_win_end2 < win_end2:
                win_end2 = abs_win_end2
            if win_end2 > n - 1:
                win_end2 = n - 1
            if win_start2 > win_end2:
                continue

            # ⑤⑥ 山2 = 単一正準点(査読B・2026-08-13訂正: tol以内で最高値)。
            window2_invalidated = False
            top2_true_bar = -1
            top2_price = 0.0
            for j in range(win_start2, win_end2 + 1):
                tol_j = top_tolerance_value if top_tolerance_is_pct else atr_a[j] * top_tolerance_atr_mult
                if bullish:
                    breach2 = low_a[j] < (top1_price - tol_j)
                else:
                    breach2 = high_a[j] > (top1_price + tol_j)
                if breach2:
                    window2_invalidated = True
                    break
                if ext_flags[j] and abs(ext_price_a[j] - top1_price) <= tol_j:
                    if bullish:
                        is_more_extreme2 = (top2_true_bar == -1) or (ext_price_a[j] < top2_price)
                    else:
                        is_more_extreme2 = (top2_true_bar == -1) or (ext_price_a[j] > top2_price)
                    if is_more_extreme2:
                        top2_true_bar = j
                        top2_price = ext_price_a[j]

            if window2_invalidated or top2_true_bar == -1:
                continue
            if not _shape_neckline_intact(high_a, low_a, neck1_true_bar, top2_true_bar, neck1_price, bullish):
                continue

            top2_confirm_bar = top2_true_bar + pivot_confirm_lag  # 山2は両側確認+lag(中間点のため)

            i2 = top2_true_bar - neck1_true_bar
            neck1_right_window = int(round(i2 * pivot_spike_window_ratio))
            # 山2自身の孤立度チェックはv1では対象外(査読E)。ネック1の右側
            # だけここで見る。
            neck1_right_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck1_true_bar, neck1_right_window,
                                              True, bullish, pivot_spike_excess_atr_max)
            if not (neck1_left_ok or neck1_right_ok):
                continue

            # ⑦ 谷1の深さ(独立判定、設計判断4)。
            avg1 = (top1_price + top2_price) / 2.0
            depth1 = (neck1_price - avg1) if bullish else (avg1 - neck1_price)
            depth1_min = atr_a[top2_true_bar] * min_valley_depth_atr_mult
            depth1_max = np.inf if max_valley_depth_atr_mult <= 0.0 else atr_a[top2_true_bar] * max_valley_depth_atr_mult
            if not (depth1_min <= depth1 <= depth1_max):
                continue

            # 設計判断2(2026-08-14訂正): 山1・山2・山3の水準許容誤差は、特定の
            # 1点(山1)を基準にするのではなく、3点全体の最高値-最安値がtol以内
            # かで判定する(旧版・一般的なトリプルトップの定義と同じ方式へ
            # 変更 - ユーザー判断: 「1点基準だと、基準にしなかった2点同士は
            # 最大2倍までズレて良いことになってしまう」)。lo12/hi12は山1・
            # 山2の範囲(山2はこの時点で確定済み、山1との差は山2探索時点で
            # 既にtol以内と保証されている)。worst12は山3候補の破綻判定用の
            # 片側境界(bullishなら安値側の下限、そうでなければ高値側の上限)。
            lo12 = top1_price if top1_price < top2_price else top2_price
            hi12 = top1_price if top1_price > top2_price else top2_price
            worst12 = lo12 if bullish else hi12

            # --- ネック2探索(規則Aをネック1と同じ形で複製、close_tolの基準
            # 幅はbase_leg=|山1-ネック1|を共有) ---
            neck2_true_bar = -1
            neck2_price = 0.0
            neck2_confirm_bar = -1
            start_idx2 = np.searchsorted(neck_events, top2_true_bar + 1, side="left")

            for ki2 in range(start_idx2, n_neck):
                k2 = neck_events[ki2]

                if neck2_true_bar != -1:
                    valley_idx2 = np.searchsorted(ext_events, neck2_true_bar + 1, side="left")
                    next_valley_bar2 = ext_events[valley_idx2] if valley_idx2 < ext_events.shape[0] else n
                    if k2 >= next_valley_bar2:
                        close_tol2 = top_tolerance_value if top_tolerance_is_pct else atr_a[next_valley_bar2] * top_tolerance_atr_mult
                        cand_v = ext_price_a[next_valley_bar2]
                        lo_v = cand_v if cand_v < lo12 else lo12
                        hi_v = cand_v if cand_v > hi12 else hi12
                        if (hi_v - lo_v) <= close_tol2:
                            break

                i3_candidate = k2 - top2_true_bar
                if i3_candidate > effective_max_bars_between_tops:
                    break
                if i3_candidate < min_bars_between_tops:
                    continue
                if neck2_true_bar != -1:
                    i3_prev = neck2_true_bar - top2_true_bar
                    prev_win_end2 = neck2_true_bar + int(np.floor(i3_prev * effective_symmetry_ratio_max))
                    if k2 > prev_win_end2:
                        break
                if bullish:
                    is_better2 = (neck2_true_bar == -1) or (neck_price_a[k2] > neck2_price)
                else:
                    is_better2 = (neck2_true_bar == -1) or (neck_price_a[k2] < neck2_price)
                if not is_better2:
                    continue
                if not _shape_extreme_intact(high_a, low_a, top2_true_bar, k2, top2_price, bullish):
                    continue
                neck2_price = neck_price_a[k2]
                neck2_true_bar = k2
                neck2_confirm_bar = neck2_true_bar + pivot_confirm_lag

                # ★設計判断3a: 2ネック近接(新パラメータneck_tolerance_mult)。
                # 2026-08-15訂正: 0は完全な同水準を意味するリテラルな
                # 許容誤差(無制限にする手段は無し) - 他の*_multパラメータ
                # の「0以下=np.inf(無制限)」という共通規約はここでは
                # 適用しない(ドキュメント上は元々「0以下=無制限は禁止」と
                # 書いていたが、コードがその通りになっていなかった不具合)。
                if top_tolerance_is_pct:
                    neck_tol = base_leg * neck_tolerance_mult
                else:
                    neck_tol = atr_a[neck2_true_bar] * top_tolerance_atr_mult
                if abs(neck1_price - neck2_price) > neck_tol:
                    continue

                i3 = neck2_true_bar - top2_true_bar
                neck2_left_window = int(round(i3 * pivot_spike_window_ratio))
                neck2_left_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck2_true_bar, neck2_left_window,
                                                 False, bullish, pivot_spike_excess_atr_max)

                win_start3 = neck2_true_bar + int(np.ceil(i3 * symmetry_ratio_min))
                win_end3 = neck2_true_bar + int(np.floor(i3 * effective_symmetry_ratio_max))
                abs_win_start3 = neck2_true_bar + min_bars_between_tops
                if abs_win_start3 > win_start3:
                    win_start3 = abs_win_start3
                abs_win_end3 = neck2_true_bar + effective_max_bars_between_tops
                if abs_win_end3 < win_end3:
                    win_end3 = abs_win_end3
                if win_end3 > n - 1:
                    win_end3 = n - 1
                if win_start3 > win_end3:
                    continue

                # ⑤⑥ 山3 = 終端(ダブルの山2走査と同型: 左側のみ・窓内最後一致)。
                # 破綻(breach3)・採用可否とも3点(山1・山2・候補)まとめての
                # 値幅判定(設計判断2、2026-08-14訂正)。
                window3_invalidated = False
                top3_true_bar = -1
                top3_price = 0.0
                for j in range(win_start3, win_end3 + 1):
                    tol_j3 = top_tolerance_value if top_tolerance_is_pct else atr_a[j] * top_tolerance_atr_mult
                    if bullish:
                        breach3 = low_a[j] < (worst12 - tol_j3)
                    else:
                        breach3 = high_a[j] > (worst12 + tol_j3)
                    if breach3:
                        window3_invalidated = True
                        break
                    if top3_true_bar != -1 and terminal_bounce_close_mult > 0.0:
                        bounce_threshold3 = abs(neck2_price - top3_price) * terminal_bounce_close_mult
                        if bullish:
                            if high_a[j] > top3_price + bounce_threshold3:
                                break
                        else:
                            if low_a[j] < top3_price - bounce_threshold3:
                                break
                    if ext_flags_top3[j]:
                        cand3 = ext_price_a[j]
                        lo_all = cand3 if cand3 < lo12 else lo12
                        hi_all = cand3 if cand3 > hi12 else hi12
                        if (hi_all - lo_all) <= tol_j3:
                            # より極端な値のときだけ更新(2026-08-14、
                            # ユーザー判断で全構成点の更新基準を統一 -
                            # ダブルの山2と同じ変更、そちらのコメント参照)。
                            if bullish:
                                is_more_extreme3 = (top3_true_bar == -1) or (cand3 < top3_price)
                            else:
                                is_more_extreme3 = (top3_true_bar == -1) or (cand3 > top3_price)
                            if is_more_extreme3:
                                top3_true_bar = j
                                top3_price = cand3

                if window3_invalidated or top3_true_bar == -1:
                    continue
                if not _shape_neckline_intact(high_a, low_a, neck2_true_bar, top3_true_bar, neck2_price, bullish):
                    continue

                i4 = top3_true_bar - neck2_true_bar
                top3_left_window = int(round(i4 * pivot_spike_window_ratio))
                top3_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top3_true_bar, top3_left_window,
                                                False, not bullish, pivot_spike_excess_atr_max)
                neck2_right_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck2_true_bar, top3_left_window,
                                                  True, bullish, pivot_spike_excess_atr_max)
                if not (neck2_left_ok or neck2_right_ok):
                    continue

                # ⑦ 谷2の深さ(独立判定)。
                avg2 = (top2_price + top3_price) / 2.0
                depth2 = (neck2_price - avg2) if bullish else (avg2 - neck2_price)
                depth2_min = atr_a[top3_true_bar] * min_valley_depth_atr_mult
                depth2_max = np.inf if max_valley_depth_atr_mult <= 0.0 else atr_a[top3_true_bar] * max_valley_depth_atr_mult
                if not (depth2_min <= depth2 <= depth2_max):
                    continue

                # neck_ref = 2ネックの低い方(bullishは高い方) - ブレイク判定
                # 専用(査読A、§1.2)。左側ジオメトリ(pre_bar/interval0)には
                # 使わない。
                if bullish:
                    neck_ref_is_neck1 = neck1_price >= neck2_price
                else:
                    neck_ref_is_neck1 = neck1_price <= neck2_price
                if neck_ref_is_neck1:
                    neck_ref_price = neck1_price
                    neck_ref_bar = neck1_true_bar
                else:
                    neck_ref_price = neck2_price
                    neck_ref_bar = neck2_true_bar
                depth_for_buffer = depth1 if neck_ref_is_neck1 else depth2

                # ブレイク判定(buf_j)用の余白はneck_ref側の深さを使う(§4)。
                breakout_buffer_value = depth_for_buffer * breakout_buffer_mult

                # ⑧ 山1前点の余白は常にdepth1(ネック1自身の深さ)を使う -
                # 査読A「左側ジオメトリは常にネック1軸」の原則を余白サイズにも
                # 徹底する。neck_ref(ネック2側になり得る)由来のbreakout_
                # buffer_valueをここに流用すると、pre_levelの基準点(ネック1)と
                # 余白の大きさ(ネック2の深さ)がねじれ、ネック2側が高い/低い
                # 場合にpre_barが見つからず候補ごと不成立になる不具合が
                # あった(2026-08-13、テストで発覚)。
                pre_buffer_value = depth1 * breakout_buffer_mult
                if breakout_buffer_is_pct:
                    pre_buf = pre_buffer_value
                else:
                    pre_buf = atr_a[top1_true_bar] * breakout_buffer_atr_mult
                # ⑧ 山1前点: ネック1固定(査読A) - min/maxのネック水準は使わない。
                pre_level = (neck1_price + pre_buf) if bullish else (neck1_price - pre_buf)

                pre_bar = -1
                for j in range(top1_true_bar - 1, -1, -1):
                    if low_a[j] <= pre_level <= high_a[j]:
                        pre_bar = j
                        break
                if pre_bar == -1:
                    continue

                top1_left_window = int(round((top1_true_bar - pre_bar) * pivot_spike_window_ratio))
                top1_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_left_window,
                                                False, not bullish, pivot_spike_excess_atr_max)
                if not (top1_left_ok or top1_right_ok):
                    continue

                # 事前undercut(ネック1軸、査読A) - pre_bar→ネック1の走行極値と山1。
                if bullish:
                    seg_min_pre = low_a[pre_bar]
                    for j in range(pre_bar + 1, neck1_true_bar + 1):
                        if low_a[j] < seg_min_pre:
                            seg_min_pre = low_a[j]
                    if top1_price > seg_min_pre:
                        continue
                else:
                    seg_max_pre = high_a[pre_bar]
                    for j in range(pre_bar + 1, neck1_true_bar + 1):
                        if high_a[j] > seg_max_pre:
                            seg_max_pre = high_a[j]
                    if top1_price < seg_max_pre:
                        continue

                # 時間0(interval0) = 山1前点→山2。ダブルは「ネック」がパター
                # ンの中心(前後1点ずつ)だから基準点はネックのまま(2026-08-13
                # に一度山2基準へ変更したが誤りだったため撤回、ユーザー判断)。
                # トリプルは5点構成(山1→ネック1→山2→ネック2→山3)のうち
                # 「山2」こそが前後2点ずつを従えるパターンの中心なので、
                # ダブルのネックに相当する基準点として山2を使う(ユーザー
                # 判断2026-08-13: 「トリプルの時はダブルと違って山2がパター
                # ンの中心に来る。だから山2を基準にしてほしい」)。
                interval0 = top2_true_bar - pre_bar

                confirm_floor = top1_confirm_bar
                if neck1_confirm_bar > confirm_floor:
                    confirm_floor = neck1_confirm_bar
                if top2_confirm_bar > confirm_floor:
                    confirm_floor = top2_confirm_bar
                if neck2_confirm_bar > confirm_floor:
                    confirm_floor = neck2_confirm_bar
                if top3_true_bar > confirm_floor:  # 山3は左側のみ確定、+lag無し
                    confirm_floor = top3_true_bar
                if confirm_floor >= n:
                    continue

                eff_ctx = _shape_eff_ratio(close_a, pre_bar, top1_true_bar)
                eff_a = _shape_eff_ratio(close_a, top1_true_bar, neck1_true_bar)
                eff_b = _shape_eff_ratio(close_a, neck1_true_bar, top2_true_bar)
                eff_c = _shape_eff_ratio(close_a, top2_true_bar, neck2_true_bar)
                eff_d = _shape_eff_ratio(close_a, neck2_true_bar, top3_true_bar)

                core_legs_ok = (
                    eff_a >= efficiency_ratio_floor
                    and eff_b >= efficiency_ratio_floor
                    and eff_c >= efficiency_ratio_floor
                    and eff_d >= efficiency_ratio_floor
                    and (eff_a + eff_b + eff_c + eff_d) / 4.0 >= efficiency_ratio_min
                    and _shape_dev_ok(high_a, low_a, atr_a, top1_true_bar, top1_price, neck1_true_bar, neck1_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, neck1_true_bar, neck1_price, top2_true_bar, top2_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, top2_true_bar, top2_price, neck2_true_bar, neck2_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, neck2_true_bar, neck2_price, top3_true_bar, top3_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                )
                context_legs_ok = (
                    eff_ctx >= efficiency_ratio_min_context
                    and _shape_dev_ok(high_a, low_a, atr_a, pre_bar, pre_level, top1_true_bar, top1_price,
                                      trendline_dev_is_atr_context, trendline_dev_atr_mult_context, trendline_dev_pct_context)
                )
                if not (core_legs_ok and context_legs_ok):
                    continue

                formed_bar = confirm_floor
                detected_a[formed_bar] = True

                if bullish:
                    worse_extreme = top1_price
                    if top2_price < worse_extreme:
                        worse_extreme = top2_price
                    if top3_price < worse_extreme:
                        worse_extreme = top3_price
                else:
                    worse_extreme = top1_price
                    if top2_price > worse_extreme:
                        worse_extreme = top2_price
                    if top3_price > worse_extreme:
                        worse_extreme = top3_price

                # expire基準の基準脚はi1(ダブルのinterval1に相当、§4)。
                expire_bars = i1 * effective_breakout_deadline_ratio_max
                scan_start = top3_true_bar + 1
                scan_end = top3_true_bar + int(np.ceil(expire_bars))
                if scan_end > n - 1:
                    scan_end = n - 1

                outcome = 4  # expired
                outcome_bar = scan_end

                if scan_start <= scan_end:
                    for j in range(scan_start, scan_end + 1):
                        buf_j = breakout_buffer_value if breakout_buffer_is_pct else atr_a[j] * breakout_buffer_atr_mult

                        if breakout_type_is_close:
                            if bullish:
                                confirm_j = close_a[j] > (neck_ref_price + buf_j)
                                fail_j = close_a[j] < (worse_extreme - buf_j)
                            else:
                                confirm_j = close_a[j] < (neck_ref_price - buf_j)
                                fail_j = close_a[j] > (worse_extreme + buf_j)
                        else:
                            if bullish:
                                confirm_j = high_a[j] > (neck_ref_price + buf_j)
                                fail_j = low_a[j] < (worse_extreme - buf_j)
                            else:
                                confirm_j = low_a[j] < (neck_ref_price - buf_j)
                                fail_j = high_a[j] > (worse_extreme + buf_j)

                        if not (confirm_j or fail_j):
                            continue

                        if fail_j:
                            outcome = 3  # failed
                            outcome_bar = j
                        else:
                            bars_since_top3 = j - top3_true_bar
                            if breakout_deadline_is_top1top2:
                                reject_bars = effective_breakout_deadline_min_bars
                            else:
                                reject_bars = i1 * breakout_deadline_ratio_min
                            if bars_since_top3 < reject_bars:
                                outcome = 1  # rejected
                                outcome_bar = j
                            else:
                                # 時間1 = 山2→判定バー(interval0と対になる
                                # 基準点、山2がパターンの中心)。
                                time1 = j - top2_true_bar
                                symmetric_ok = (
                                    time1 * interval_symmetry_ratio_min <= interval0 <= time1 * effective_interval_symmetry_ratio_max
                                )
                                eff_brk = _shape_eff_ratio(close_a, top3_true_bar, j)

                                if bullish:
                                    seg_min2 = low_a[neck_ref_bar]
                                    for jj in range(neck_ref_bar + 1, j + 1):
                                        if low_a[jj] < seg_min2:
                                            seg_min2 = low_a[jj]
                                    no_undercut = top3_price <= seg_min2
                                else:
                                    seg_max2 = high_a[neck_ref_bar]
                                    for jj in range(neck_ref_bar + 1, j + 1):
                                        if high_a[jj] > seg_max2:
                                            seg_max2 = high_a[jj]
                                    no_undercut = top3_price >= seg_max2

                                top3_right_window = int(round((j - top3_true_bar) * pivot_spike_window_ratio))
                                max_window3 = j - top3_true_bar
                                if top3_right_window > max_window3:
                                    top3_right_window = max_window3
                                top3_right_ok = _shape_spike_ok(
                                    ext_price_a, atr_a, n, top3_true_bar, top3_right_window,
                                    True, not bullish, pivot_spike_excess_atr_max,
                                )
                                top3_isolation_ok = top3_left_ok or top3_right_ok

                                end_price_for_dev = close_a[j] if breakout_type_is_close else (high_a[j] if bullish else low_a[j])

                                breakout_leg_ok = (
                                    symmetric_ok
                                    and eff_brk >= efficiency_ratio_min_breakout
                                    and no_undercut
                                    and top3_isolation_ok
                                    and _shape_dev_ok(high_a, low_a, atr_a, top3_true_bar, top3_price, j, end_price_for_dev,
                                                       trendline_dev_is_atr_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout)
                                )
                                outcome = 2 if breakout_leg_ok else 1
                                outcome_bar = j
                        break

                if outcome_bar < formed_bar:
                    outcome_bar = formed_bar

                exists_end = outcome_bar
                for _idx in range(formed_bar, exists_end + 1):
                    if _idx == formed_bar or not detected_a[_idx]:
                        exists_a[_idx] = True
                        formed_bar_a[_idx] = formed_bar
                top1_bar_a[formed_bar] = top1_true_bar
                neck1_bar_a[formed_bar] = neck1_true_bar
                top2_bar_a[formed_bar] = top2_true_bar
                neck2_bar_a[formed_bar] = neck2_true_bar
                top3_bar_a[formed_bar] = top3_true_bar
                top1_price_a[formed_bar] = top1_price
                neck1_price_a[formed_bar] = neck1_price
                top2_price_a[formed_bar] = top2_price
                neck2_price_a[formed_bar] = neck2_price
                top3_price_a[formed_bar] = top3_price

                if outcome == 2:
                    resolve_a[outcome_bar] = True
                else:
                    invalidated_a[outcome_bar] = True

    return (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a,
        top1_bar_a, neck1_bar_a, top2_bar_a, neck2_bar_a, top3_bar_a,
        top1_price_a, neck1_price_a, top2_price_a, neck2_price_a, top3_price_a,
    )


def _triple_top_bottom_shape_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.25,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.05,
    efficiency_ratio_min: float = 0.1,
    efficiency_ratio_floor: float = 0.05,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.9,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.15,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.9,
    breakout_deadline_basis: str = "top1_top2",
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_min: float = 0.3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.5,
    interval_symmetry_ratio_max: float = 2.0,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
    neck_tolerance_mult: float = 0.25,
) -> dict[str, pd.Series]:
    """docs/pattern_spec_triple_top_bottom_shape.md 参照。bullish=Trueで
    トリプルボトム、Falseでトリプルトップ(高値/安値・上下を反転させた鏡像)。
    ダブルトップ/ボトムST(_double_top_bottom_shape_state)を土台に、
    山1→ネック1→山2→ネック2→山3の5点構成へ拡張したもの。各パラメータの
    意味はダブル版と同じ(top_tolerance_mult等は3点(山1・山2・山3)全体の
    値幅で判定)。neck_tolerance_multのみ新規 - 2ネック(ネック1・ネック2)の
    水準近接を要求する倍率(0以下=無制限は禁止、v1既定0.25)。"""
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

    pivot_left_bars = max(0, pivot_left_bars)
    pivot_right_bars = max(0, pivot_right_bars)
    if pivot_left_bars == 0 and pivot_right_bars == 0:
        pivot_left_bars = 1

    # 山1→ネック1・ネック1→山2・山2→ネック2・ネック2→山3、各区間の最短本数は
    # ダブルと同じくピボット右本数(pivot_right_bars)に内部固定する。
    min_bars_between_tops = pivot_right_bars

    ext_price_a = low_a if bullish else high_a
    neck_price_a = high_a if bullish else low_a

    boundary_other_a = high_a if bullish else low_a
    prom_thresh = atr_a * prominence_atr_mult
    ext_flags = (
        _pivot_flags(low if bullish else high, pivot_left_bars, pivot_right_bars, not bullish).to_numpy()
        & _prominence_flags(ext_price_a, boundary_other_a, pivot_left_bars, pivot_right_bars, prom_thresh, not bullish)
    )

    neck_boundary_other_a = low_a if bullish else high_a
    neck_flags = (
        _pivot_flags(high if bullish else low, pivot_left_bars, pivot_right_bars, bullish).to_numpy()
        & _prominence_flags(neck_price_a, neck_boundary_other_a, pivot_left_bars, pivot_right_bars, prom_thresh, bullish)
    )

    # 山3(終端、ブレイクへ直結)専用: ダブルのext_flags_top2と同じく右側確認を
    # 外した左側のみのピボット判定。山1・山2・ネック1・ネック2はext_flags/
    # neck_flags(両側確認)のまま。
    plain_pivot_ext_left_only = (
        _detect_pivot_lows_left_only(low, pivot_left_bars)
        if bullish
        else _detect_pivot_highs_left_only(high, pivot_left_bars)
    ).to_numpy()
    prominence_ok_ext_left_only = _prominence_flags(ext_price_a, boundary_other_a, pivot_left_bars, 0, prom_thresh, not bullish)
    ext_flags_top3 = plain_pivot_ext_left_only & prominence_ok_ext_left_only

    pivot_confirm_lag = pivot_right_bars

    (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a,
        top1_bar_a, neck1_bar_a, top2_bar_a, neck2_bar_a, top3_bar_a,
        top1_price_a, neck1_price_a, top2_price_a, neck2_price_a, top3_price_a,
    ) = _shape_state_core3(
        high_a, low_a, close_a, atr_a,
        ext_price_a, neck_price_a,
        ext_flags, neck_flags, ext_flags_top3,
        bool(bullish),
        int(pivot_confirm_lag),
        float(pivot_spike_excess_atr_max), float(pivot_spike_window_ratio),
        int(min_bars_between_tops), int(max_bars_between_tops),
        float(symmetry_ratio_min), float(symmetry_ratio_max),
        top_tolerance_basis == "price_pct", float(top_tolerance_atr_mult), float(top_tolerance_mult),
        float(min_valley_depth_atr_mult), float(max_valley_depth_atr_mult),
        breakout_buffer_basis == "price_pct", float(breakout_buffer_atr_mult), float(breakout_buffer_mult),
        float(efficiency_ratio_min), float(efficiency_ratio_floor),
        trendline_dev_basis == "atr", float(trendline_dev_atr_mult), float(trendline_dev_pct),
        float(efficiency_ratio_min_context),
        trendline_dev_basis_context == "atr", float(trendline_dev_atr_mult_context), float(trendline_dev_pct_context),
        float(efficiency_ratio_min_breakout),
        trendline_dev_basis_breakout == "atr", float(trendline_dev_atr_mult_breakout), float(trendline_dev_pct_breakout),
        breakout_deadline_basis == "top1_top2", int(breakout_deadline_min_bars),
        float(breakout_deadline_ratio_min), float(breakout_deadline_ratio_max),
        float(interval_symmetry_ratio_min), float(interval_symmetry_ratio_max),
        float(terminal_bounce_close_mult),
        breakout_type == "close",
        float(neck_tolerance_mult),
    )

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "candidate": pd.Series(detected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "invalidated": pd.Series(invalidated_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "top1_bar": pd.Series(top1_bar_a, index=idx_index),
        "neck1_bar": pd.Series(neck1_bar_a, index=idx_index),
        "top2_bar": pd.Series(top2_bar_a, index=idx_index),
        "neck2_bar": pd.Series(neck2_bar_a, index=idx_index),
        "top3_bar": pd.Series(top3_bar_a, index=idx_index),
        "top1_price": pd.Series(top1_price_a, index=idx_index),
        "neck1_price": pd.Series(neck1_price_a, index=idx_index),
        "top2_price": pd.Series(top2_price_a, index=idx_index),
        "neck2_price": pd.Series(neck2_price_a, index=idx_index),
        "top3_price": pd.Series(top3_price_a, index=idx_index),
    }


def triple_bottom_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.25,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.05,
    efficiency_ratio_min: float = 0.1,
    efficiency_ratio_floor: float = 0.05,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.9,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.15,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.9,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.5,
    interval_symmetry_ratio_max: float = 2.0,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
    neck_tolerance_mult: float = 0.25,
    **p,
) -> np.ndarray:
    """トリプルボトム(形状判定版) - docs/pattern_spec_triple_top_bottom_shape.md
    参照。ダブルボトムST(double_bottom_shape)を土台に、谷1→ネック1→谷2→
    ネック2→谷3の5点構成へ拡張。Candidate/Confirmed/Invalidatedの3状態を
    stateパラメータで選べる(ダブルと同じ)。"""
    result = _triple_top_bottom_shape_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_mult,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_mult,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        efficiency_ratio_min_context,
        trendline_dev_basis_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
        efficiency_ratio_min_breakout,
        trendline_dev_basis_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        terminal_bounce_close_mult,
        breakout_type,
        neck_tolerance_mult,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def triple_top_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.25,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.05,
    efficiency_ratio_min: float = 0.1,
    efficiency_ratio_floor: float = 0.05,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.9,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.15,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.9,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.5,
    interval_symmetry_ratio_max: float = 2.0,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
    neck_tolerance_mult: float = 0.25,
    **p,
) -> np.ndarray:
    """Mirror image of triple_bottom_shape - トリプルトップ(形状判定版)。"""
    result = _triple_top_bottom_shape_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_mult,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_mult,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        efficiency_ratio_min_context,
        trendline_dev_basis_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
        efficiency_ratio_min_breakout,
        trendline_dev_basis_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        terminal_bounce_close_mult,
        breakout_type,
        neck_tolerance_mult,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# ヘッド・アンド・ショルダーズ(形状判定版・2026-08-14) - トリプルトップ/
# ボトムST(_shape_state_core3、直前の一連の関数)を土台に、以下の2点だけを
# 一般的なヘッド・アンド・ショルダーズの定義に合わせて変更したもの。詳細は
# docs/pattern_spec_head_and_shoulders_shape.md 参照。
#   - 山2(頭)は肩(山1・山3)より明確に高い(新パラメータhead_prominence_
#     mult)ことを要求する。トリプルの「3点まとめての値幅判定」は使わず、
#     肩1・肩3の2点だけをtop_tolerance_multで比較する(頭は比較対象外)。
#     そのためwindow2/window3の破綻判定・採用可否は、頭を含むlo12/hi12/
#     worst12ではなく、常に山1(肩1)の水準を基準にする(トリプルより前の、
#     3点統合前の単純な形に戻すのと同じ)。window2(頭探索)には価格の
#     上限を設けない(頭はいくら高くてもよい) - 破綻方向も「肩の水準を
#     割り込みすぎたら不成立」の片側だけになる。
#   - ネックライン(ブレイク判定水準)はネック1・ネック2を結ぶ直線を延長した
#     値を使う(判定バーごとに変わる)。トリプルの固定水準(min/maxネック)
#     とは異なる。neck_tolerance_mult(2ネック近接)自体の意味・既定値
#     (0=完全な同水準、無制限にする手段は無し、既定0.25)はトリプルと
#     完全に同じ(2026-08-15訂正: 傾いたネックラインは、この許容誤差の
#     範囲内でネック1・ネック2がズレることで表現される。傾きを大きく
#     許したい場合はneck_tolerance_multを大きくする)。
# 上記以外(山1前点探索・時間対称性の基準点・孤立度チェック対象・効率比・
# 直線乖離・先読み防止・3状態モデル・パラメータ命名規則)はトリプルSTと
# 完全に同じ。
# ---------------------------------------------------------------------------


@njit(cache=True)
def _shape_state_core_hs(
    high_a, low_a, close_a, atr_a,
    ext_price_a, neck_price_a,
    ext_flags, neck_flags, ext_flags_top3,
    bullish,
    pivot_confirm_lag,
    pivot_spike_excess_atr_max, pivot_spike_window_ratio,
    min_bars_between_tops, max_bars_between_tops,
    symmetry_ratio_min, symmetry_ratio_max,
    top_tolerance_is_pct, top_tolerance_atr_mult, top_tolerance_mult,
    min_valley_depth_atr_mult, max_valley_depth_atr_mult,
    breakout_buffer_is_pct, breakout_buffer_atr_mult, breakout_buffer_mult,
    efficiency_ratio_min, efficiency_ratio_floor,
    trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct,
    efficiency_ratio_min_context,
    trendline_dev_is_atr_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
    efficiency_ratio_min_breakout,
    trendline_dev_is_atr_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
    breakout_deadline_is_top1top2, breakout_deadline_min_bars,
    breakout_deadline_ratio_min, breakout_deadline_ratio_max,
    interval_symmetry_ratio_min, interval_symmetry_ratio_max,
    terminal_bounce_close_mult,
    breakout_type_is_close,
    neck_tolerance_mult,
    head_prominence_mult,
):
    n = high_a.shape[0]
    effective_breakout_deadline_min_bars = float(breakout_deadline_min_bars)
    effective_max_bars_between_tops = (
        max_bars_between_tops if max_bars_between_tops > 0 else _MAX_BARS_BETWEEN_TOPS_UNLIMITED_CAP
    )
    effective_symmetry_ratio_max = symmetry_ratio_max if symmetry_ratio_max > 0.0 else _UNLIMITED_RATIO
    effective_interval_symmetry_ratio_max = (
        interval_symmetry_ratio_max if interval_symmetry_ratio_max > 0.0 else _UNLIMITED_RATIO
    )
    effective_breakout_deadline_ratio_max = (
        breakout_deadline_ratio_max if breakout_deadline_ratio_max > 0.0 else _UNLIMITED_RATIO
    )

    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)
    resolve_a = np.zeros(n, dtype=np.bool_)
    invalidated_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    top1_bar_a = np.full(n, np.nan)
    neck1_bar_a = np.full(n, np.nan)
    top2_bar_a = np.full(n, np.nan)
    neck2_bar_a = np.full(n, np.nan)
    top3_bar_a = np.full(n, np.nan)
    top1_price_a = np.full(n, np.nan)
    neck1_price_a = np.full(n, np.nan)
    top2_price_a = np.full(n, np.nan)
    neck2_price_a = np.full(n, np.nan)
    top3_price_a = np.full(n, np.nan)

    ext_events = np.flatnonzero(ext_flags)
    neck_events = np.flatnonzero(neck_flags)
    n_neck = neck_events.shape[0]

    for ei in range(ext_events.shape[0]):
        top1_true_bar = ext_events[ei]
        top1_price = ext_price_a[top1_true_bar]
        top1_confirm_bar = top1_true_bar + pivot_confirm_lag

        neck1_true_bar = -1
        neck1_price = 0.0
        neck1_confirm_bar = -1

        start_idx1 = np.searchsorted(neck_events, top1_true_bar + 1, side="left")

        for ki1 in range(start_idx1, n_neck):
            k1 = neck_events[ki1]

            # 窓打ち切り規則A(トリプルと同じ、山1=肩1水準を基準にする)。
            if neck1_true_bar != -1:
                valley_idx = np.searchsorted(ext_events, neck1_true_bar + 1, side="left")
                next_valley_bar = ext_events[valley_idx] if valley_idx < ext_events.shape[0] else n
                if k1 >= next_valley_bar:
                    if top_tolerance_mult <= 0.0:
                        close_tol = np.inf
                    elif top_tolerance_is_pct:
                        close_tol = abs(top1_price - neck1_price) * top_tolerance_mult
                    else:
                        close_tol = atr_a[next_valley_bar] * top_tolerance_atr_mult
                    if abs(ext_price_a[next_valley_bar] - top1_price) <= close_tol:
                        break

            i1_candidate = k1 - top1_true_bar
            if i1_candidate > effective_max_bars_between_tops:
                break
            if i1_candidate < min_bars_between_tops:
                continue
            if neck1_true_bar != -1:
                i1_prev = neck1_true_bar - top1_true_bar
                prev_win_end = neck1_true_bar + int(np.floor(i1_prev * effective_symmetry_ratio_max))
                if k1 > prev_win_end:
                    break
            if bullish:
                is_better1 = (neck1_true_bar == -1) or (neck_price_a[k1] > neck1_price)
            else:
                is_better1 = (neck1_true_bar == -1) or (neck_price_a[k1] < neck1_price)
            if not is_better1:
                continue
            if not _shape_extreme_intact(high_a, low_a, top1_true_bar, k1, top1_price, bullish):
                continue
            neck1_price = neck_price_a[k1]
            neck1_true_bar = k1
            neck1_confirm_bar = neck1_true_bar + pivot_confirm_lag

            i1 = neck1_true_bar - top1_true_bar

            top1_right_window = int(round(i1 * pivot_spike_window_ratio))
            top1_right_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_right_window,
                                             True, not bullish, pivot_spike_excess_atr_max)
            neck1_left_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck1_true_bar, top1_right_window,
                                             False, bullish, pivot_spike_excess_atr_max)

            # 肩1・肩3同士の許容誤差の基準幅(山1→ネック1の値幅)。頭には
            # この許容誤差を適用しない(H&Sの核心 - 査読不要、設計時に確定)。
            base_leg = abs(top1_price - neck1_price)
            top_tolerance_value = np.inf if top_tolerance_mult <= 0.0 else base_leg * top_tolerance_mult

            win_start2 = neck1_true_bar + int(np.ceil(i1 * symmetry_ratio_min))
            win_end2 = neck1_true_bar + int(np.floor(i1 * effective_symmetry_ratio_max))
            abs_win_start2 = neck1_true_bar + min_bars_between_tops
            if abs_win_start2 > win_start2:
                win_start2 = abs_win_start2
            abs_win_end2 = neck1_true_bar + effective_max_bars_between_tops
            if abs_win_end2 < win_end2:
                win_end2 = abs_win_end2
            if win_end2 > n - 1:
                win_end2 = n - 1
            if win_start2 > win_end2:
                continue

            # ⑤⑥ 頭(山2)候補: 破綻(breach)判定は無し - ネック1へ向けて肩1
            # 水準を大きく下回るのはH&Sでは正常な動き(そこから頭へ向けて
            # 上昇する)であり、トリプルのような「肩1に近いままか」の破綻
            # チェックはここでは意味を持たない(2026-08-14、合成データの
            # テストで発覚 - 破綻判定を残していたためネック1直後に即座に
            # 窓破綻していた)。窓内で最も極端な値を正準点にする(トリプルと
            # 同じ更新規則)。異常形状の排除はdepth1・head_prominence_mult・
            # 効率比・直線乖離などの下流チェックに委ねる。
            top2_true_bar = -1
            top2_price = 0.0
            for j in range(win_start2, win_end2 + 1):
                if ext_flags[j]:
                    if bullish:
                        is_more_extreme2 = (top2_true_bar == -1) or (ext_price_a[j] < top2_price)
                    else:
                        is_more_extreme2 = (top2_true_bar == -1) or (ext_price_a[j] > top2_price)
                    if is_more_extreme2:
                        top2_true_bar = j
                        top2_price = ext_price_a[j]

            if top2_true_bar == -1:
                continue
            if not _shape_neckline_intact(high_a, low_a, neck1_true_bar, top2_true_bar, neck1_price, bullish):
                continue

            top2_confirm_bar = top2_true_bar + pivot_confirm_lag  # 頭は両側確認+lag(中間点のため)

            i2 = top2_true_bar - neck1_true_bar
            neck1_right_window = int(round(i2 * pivot_spike_window_ratio))
            # 頭自身の孤立度チェックは対象外(head_prominence_multが同じ
            # 役割を果たすため、トリプルの査読Eと同じ考え方)。
            neck1_right_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck1_true_bar, neck1_right_window,
                                              True, bullish, pivot_spike_excess_atr_max)
            if not (neck1_left_ok or neck1_right_ok):
                continue

            # ⑦ 谷1の深さ(独立判定)。
            avg1 = (top1_price + top2_price) / 2.0
            depth1 = (neck1_price - avg1) if bullish else (avg1 - neck1_price)
            depth1_min = atr_a[top2_true_bar] * min_valley_depth_atr_mult
            depth1_max = np.inf if max_valley_depth_atr_mult <= 0.0 else atr_a[top2_true_bar] * max_valley_depth_atr_mult
            if not (depth1_min <= depth1 <= depth1_max):
                continue

            # --- ネック2探索(規則Aは肩1水準基準、トリプルの3点統合前と同じ
            # 単純な形に戻す) ---
            neck2_true_bar = -1
            neck2_price = 0.0
            neck2_confirm_bar = -1
            start_idx2 = np.searchsorted(neck_events, top2_true_bar + 1, side="left")

            for ki2 in range(start_idx2, n_neck):
                k2 = neck_events[ki2]

                if neck2_true_bar != -1:
                    valley_idx2 = np.searchsorted(ext_events, neck2_true_bar + 1, side="left")
                    next_valley_bar2 = ext_events[valley_idx2] if valley_idx2 < ext_events.shape[0] else n
                    if k2 >= next_valley_bar2:
                        close_tol2 = top_tolerance_value if top_tolerance_is_pct else atr_a[next_valley_bar2] * top_tolerance_atr_mult
                        if abs(ext_price_a[next_valley_bar2] - top1_price) <= close_tol2:
                            break

                i3_candidate = k2 - top2_true_bar
                if i3_candidate > effective_max_bars_between_tops:
                    break
                if i3_candidate < min_bars_between_tops:
                    continue
                if neck2_true_bar != -1:
                    i3_prev = neck2_true_bar - top2_true_bar
                    prev_win_end2 = neck2_true_bar + int(np.floor(i3_prev * effective_symmetry_ratio_max))
                    if k2 > prev_win_end2:
                        break
                if bullish:
                    is_better2 = (neck2_true_bar == -1) or (neck_price_a[k2] > neck2_price)
                else:
                    is_better2 = (neck2_true_bar == -1) or (neck_price_a[k2] < neck2_price)
                if not is_better2:
                    continue
                if not _shape_extreme_intact(high_a, low_a, top2_true_bar, k2, top2_price, bullish):
                    continue
                neck2_price = neck_price_a[k2]
                neck2_true_bar = k2
                neck2_confirm_bar = neck2_true_bar + pivot_confirm_lag

                # 2ネック近接(2026-08-15訂正: トリプルと同じ「0=完全な
                # 同水準・無制限は禁止」の規約に統一。他の*_multパラメータ
                # の「0以下=np.inf(無制限)」という共通規約はここでは
                # 適用しない - ユーザー判断: neck_tolerance_multは0を
                # リテラルな許容誤差として使い、無制限にする手段自体を
                # 提供しない。既定値も0.25にそろえる)。
                if top_tolerance_is_pct:
                    neck_tol = base_leg * neck_tolerance_mult
                else:
                    neck_tol = atr_a[neck2_true_bar] * top_tolerance_atr_mult
                if abs(neck1_price - neck2_price) > neck_tol:
                    continue

                i3 = neck2_true_bar - top2_true_bar
                neck2_left_window = int(round(i3 * pivot_spike_window_ratio))
                neck2_left_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck2_true_bar, neck2_left_window,
                                                 False, bullish, pivot_spike_excess_atr_max)

                win_start3 = neck2_true_bar + int(np.ceil(i3 * symmetry_ratio_min))
                win_end3 = neck2_true_bar + int(np.floor(i3 * effective_symmetry_ratio_max))
                abs_win_start3 = neck2_true_bar + min_bars_between_tops
                if abs_win_start3 > win_start3:
                    win_start3 = abs_win_start3
                abs_win_end3 = neck2_true_bar + effective_max_bars_between_tops
                if abs_win_end3 < win_end3:
                    win_end3 = abs_win_end3
                if win_end3 > n - 1:
                    win_end3 = n - 1
                if win_start3 > win_end3:
                    continue

                # ⑤⑥ 肩3(山3) = 終端(左側のみ・窓内で最も極端な値)。肩1水準
                # ±tolに収まるものだけを候補にする(頭を含めない2点比較)。
                window3_invalidated = False
                top3_true_bar = -1
                top3_price = 0.0
                for j in range(win_start3, win_end3 + 1):
                    tol_j3 = top_tolerance_value if top_tolerance_is_pct else atr_a[j] * top_tolerance_atr_mult
                    if bullish:
                        breach3 = low_a[j] < (top1_price - tol_j3)
                    else:
                        breach3 = high_a[j] > (top1_price + tol_j3)
                    if breach3:
                        window3_invalidated = True
                        break
                    if top3_true_bar != -1 and terminal_bounce_close_mult > 0.0:
                        bounce_threshold3 = abs(neck2_price - top3_price) * terminal_bounce_close_mult
                        if bullish:
                            if high_a[j] > top3_price + bounce_threshold3:
                                break
                        else:
                            if low_a[j] < top3_price - bounce_threshold3:
                                break
                    if ext_flags_top3[j] and abs(ext_price_a[j] - top1_price) <= tol_j3:
                        if bullish:
                            is_more_extreme3 = (top3_true_bar == -1) or (ext_price_a[j] < top3_price)
                        else:
                            is_more_extreme3 = (top3_true_bar == -1) or (ext_price_a[j] > top3_price)
                        if is_more_extreme3:
                            top3_true_bar = j
                            top3_price = ext_price_a[j]

                if window3_invalidated or top3_true_bar == -1:
                    continue
                if not _shape_neckline_intact(high_a, low_a, neck2_true_bar, top3_true_bar, neck2_price, bullish):
                    continue

                # 頭の突出度(head_prominence_mult) - H&Sの核心。肩1・肩3の
                # うち「頭に近い方(高い方/低い方)」を基準に、それでもなお
                # head_prominence_mult×base_leg以上、頭の方が突出している
                # ことを要求する。
                if bullish:
                    shoulder_extreme = top1_price if top1_price < top3_price else top3_price
                    head_margin = shoulder_extreme - top2_price
                else:
                    shoulder_extreme = top1_price if top1_price > top3_price else top3_price
                    head_margin = top2_price - shoulder_extreme
                if head_margin < head_prominence_mult * base_leg:
                    continue

                i4 = top3_true_bar - neck2_true_bar
                top3_left_window = int(round(i4 * pivot_spike_window_ratio))
                top3_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top3_true_bar, top3_left_window,
                                                False, not bullish, pivot_spike_excess_atr_max)
                neck2_right_ok = _shape_spike_ok(neck_price_a, atr_a, n, neck2_true_bar, top3_left_window,
                                                  True, bullish, pivot_spike_excess_atr_max)
                if not (neck2_left_ok or neck2_right_ok):
                    continue

                # ⑦ 谷2の深さ(独立判定)。
                avg2 = (top2_price + top3_price) / 2.0
                depth2 = (neck2_price - avg2) if bullish else (avg2 - neck2_price)
                depth2_min = atr_a[top3_true_bar] * min_valley_depth_atr_mult
                depth2_max = np.inf if max_valley_depth_atr_mult <= 0.0 else atr_a[top3_true_bar] * max_valley_depth_atr_mult
                if not (depth2_min <= depth2 <= depth2_max):
                    continue

                # ブレイク判定余白は2つの谷の深い方を使う(neck_refという
                # 単一水準の概念がH&Sには無いため、より保守的な方を採用)。
                depth_for_buffer = depth1 if depth1 > depth2 else depth2
                breakout_buffer_value = depth_for_buffer * breakout_buffer_mult

                # ⑧ 山1前点の余白は常にdepth1(ネック1自身の深さ)を使う
                # (トリプルと同じ理由、査読A)。
                pre_buffer_value = depth1 * breakout_buffer_mult
                if breakout_buffer_is_pct:
                    pre_buf = pre_buffer_value
                else:
                    pre_buf = atr_a[top1_true_bar] * breakout_buffer_atr_mult
                pre_level = (neck1_price + pre_buf) if bullish else (neck1_price - pre_buf)

                pre_bar = -1
                for j in range(top1_true_bar - 1, -1, -1):
                    if low_a[j] <= pre_level <= high_a[j]:
                        pre_bar = j
                        break
                if pre_bar == -1:
                    continue

                top1_left_window = int(round((top1_true_bar - pre_bar) * pivot_spike_window_ratio))
                top1_left_ok = _shape_spike_ok(ext_price_a, atr_a, n, top1_true_bar, top1_left_window,
                                                False, not bullish, pivot_spike_excess_atr_max)
                if not (top1_left_ok or top1_right_ok):
                    continue

                # 事前undercut(ネック1軸) - pre_bar→ネック1の走行極値と肩1。
                if bullish:
                    seg_min_pre = low_a[pre_bar]
                    for j in range(pre_bar + 1, neck1_true_bar + 1):
                        if low_a[j] < seg_min_pre:
                            seg_min_pre = low_a[j]
                    if top1_price > seg_min_pre:
                        continue
                else:
                    seg_max_pre = high_a[pre_bar]
                    for j in range(pre_bar + 1, neck1_true_bar + 1):
                        if high_a[j] > seg_max_pre:
                            seg_max_pre = high_a[j]
                    if top1_price < seg_max_pre:
                        continue

                # 時間0(interval0) = 山1前点→頭(頭がパターンの中心、
                # トリプルと同じ考え方)。
                interval0 = top2_true_bar - pre_bar

                confirm_floor = top1_confirm_bar
                if neck1_confirm_bar > confirm_floor:
                    confirm_floor = neck1_confirm_bar
                if top2_confirm_bar > confirm_floor:
                    confirm_floor = top2_confirm_bar
                if neck2_confirm_bar > confirm_floor:
                    confirm_floor = neck2_confirm_bar
                if top3_true_bar > confirm_floor:  # 肩3は左側のみ確定、+lag無し
                    confirm_floor = top3_true_bar
                if confirm_floor >= n:
                    continue

                eff_ctx = _shape_eff_ratio(close_a, pre_bar, top1_true_bar)
                eff_a = _shape_eff_ratio(close_a, top1_true_bar, neck1_true_bar)
                eff_b = _shape_eff_ratio(close_a, neck1_true_bar, top2_true_bar)
                eff_c = _shape_eff_ratio(close_a, top2_true_bar, neck2_true_bar)
                eff_d = _shape_eff_ratio(close_a, neck2_true_bar, top3_true_bar)

                core_legs_ok = (
                    eff_a >= efficiency_ratio_floor
                    and eff_b >= efficiency_ratio_floor
                    and eff_c >= efficiency_ratio_floor
                    and eff_d >= efficiency_ratio_floor
                    and (eff_a + eff_b + eff_c + eff_d) / 4.0 >= efficiency_ratio_min
                    and _shape_dev_ok(high_a, low_a, atr_a, top1_true_bar, top1_price, neck1_true_bar, neck1_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, neck1_true_bar, neck1_price, top2_true_bar, top2_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, top2_true_bar, top2_price, neck2_true_bar, neck2_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                    and _shape_dev_ok(high_a, low_a, atr_a, neck2_true_bar, neck2_price, top3_true_bar, top3_price,
                                      trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
                )
                context_legs_ok = (
                    eff_ctx >= efficiency_ratio_min_context
                    and _shape_dev_ok(high_a, low_a, atr_a, pre_bar, pre_level, top1_true_bar, top1_price,
                                      trendline_dev_is_atr_context, trendline_dev_atr_mult_context, trendline_dev_pct_context)
                )
                if not (core_legs_ok and context_legs_ok):
                    continue

                formed_bar = confirm_floor
                detected_a[formed_bar] = True

                # worse_extreme(fail基準)は頭の価格そのもの - head_prominence_
                # multにより頭が3点中最も極端であることは構造上保証済み。
                worse_extreme = top2_price

                # expire基準の基準脚はi1(トリプルと同じ)。
                expire_bars = i1 * effective_breakout_deadline_ratio_max
                scan_start = top3_true_bar + 1
                scan_end = top3_true_bar + int(np.ceil(expire_bars))
                if scan_end > n - 1:
                    scan_end = n - 1

                outcome = 4  # expired
                outcome_bar = scan_end

                # ネックラインの傾き(1バーあたりの変化量) - ネック1→ネック2の
                # 直線を延長する。neck2_true_bar==neck1_true_barは規則上
                # 起こらない(i3>=min_bars_between_tops>=0、実質必ず正)。
                neck_span = neck2_true_bar - neck1_true_bar
                neck_slope = (neck2_price - neck1_price) / neck_span

                if scan_start <= scan_end:
                    for j in range(scan_start, scan_end + 1):
                        buf_j = breakout_buffer_value if breakout_buffer_is_pct else atr_a[j] * breakout_buffer_atr_mult
                        neckline_at_j = neck1_price + neck_slope * (j - neck1_true_bar)

                        if breakout_type_is_close:
                            if bullish:
                                confirm_j = close_a[j] > (neckline_at_j + buf_j)
                                fail_j = close_a[j] < (worse_extreme - buf_j)
                            else:
                                confirm_j = close_a[j] < (neckline_at_j - buf_j)
                                fail_j = close_a[j] > (worse_extreme + buf_j)
                        else:
                            if bullish:
                                confirm_j = high_a[j] > (neckline_at_j + buf_j)
                                fail_j = low_a[j] < (worse_extreme - buf_j)
                            else:
                                confirm_j = low_a[j] < (neckline_at_j - buf_j)
                                fail_j = high_a[j] > (worse_extreme + buf_j)

                        if not (confirm_j or fail_j):
                            continue

                        if fail_j:
                            outcome = 3  # failed
                            outcome_bar = j
                        else:
                            bars_since_top3 = j - top3_true_bar
                            if breakout_deadline_is_top1top2:
                                reject_bars = effective_breakout_deadline_min_bars
                            else:
                                reject_bars = i1 * breakout_deadline_ratio_min
                            if bars_since_top3 < reject_bars:
                                outcome = 1  # rejected
                                outcome_bar = j
                            else:
                                time1 = j - top2_true_bar
                                symmetric_ok = (
                                    time1 * interval_symmetry_ratio_min <= interval0 <= time1 * effective_interval_symmetry_ratio_max
                                )
                                eff_brk = _shape_eff_ratio(close_a, top3_true_bar, j)

                                # no_undercut: ネック2→判定バーの走行極値と
                                # 肩3を比較(単一のneck_refが無いため、より
                                # 局所的なネック2を軸にする)。
                                if bullish:
                                    seg_min2 = low_a[neck2_true_bar]
                                    for jj in range(neck2_true_bar + 1, j + 1):
                                        if low_a[jj] < seg_min2:
                                            seg_min2 = low_a[jj]
                                    no_undercut = top3_price <= seg_min2
                                else:
                                    seg_max2 = high_a[neck2_true_bar]
                                    for jj in range(neck2_true_bar + 1, j + 1):
                                        if high_a[jj] > seg_max2:
                                            seg_max2 = high_a[jj]
                                    no_undercut = top3_price >= seg_max2

                                top3_right_window = int(round((j - top3_true_bar) * pivot_spike_window_ratio))
                                max_window3 = j - top3_true_bar
                                if top3_right_window > max_window3:
                                    top3_right_window = max_window3
                                top3_right_ok = _shape_spike_ok(
                                    ext_price_a, atr_a, n, top3_true_bar, top3_right_window,
                                    True, not bullish, pivot_spike_excess_atr_max,
                                )
                                top3_isolation_ok = top3_left_ok or top3_right_ok

                                end_price_for_dev = close_a[j] if breakout_type_is_close else (high_a[j] if bullish else low_a[j])

                                breakout_leg_ok = (
                                    symmetric_ok
                                    and eff_brk >= efficiency_ratio_min_breakout
                                    and no_undercut
                                    and top3_isolation_ok
                                    and _shape_dev_ok(high_a, low_a, atr_a, top3_true_bar, top3_price, j, end_price_for_dev,
                                                       trendline_dev_is_atr_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout)
                                )
                                outcome = 2 if breakout_leg_ok else 1
                                outcome_bar = j
                        break

                if outcome_bar < formed_bar:
                    outcome_bar = formed_bar

                exists_end = outcome_bar
                for _idx in range(formed_bar, exists_end + 1):
                    if _idx == formed_bar or not detected_a[_idx]:
                        exists_a[_idx] = True
                        formed_bar_a[_idx] = formed_bar
                top1_bar_a[formed_bar] = top1_true_bar
                neck1_bar_a[formed_bar] = neck1_true_bar
                top2_bar_a[formed_bar] = top2_true_bar
                neck2_bar_a[formed_bar] = neck2_true_bar
                top3_bar_a[formed_bar] = top3_true_bar
                top1_price_a[formed_bar] = top1_price
                neck1_price_a[formed_bar] = neck1_price
                top2_price_a[formed_bar] = top2_price
                neck2_price_a[formed_bar] = neck2_price
                top3_price_a[formed_bar] = top3_price

                if outcome == 2:
                    resolve_a[outcome_bar] = True
                else:
                    invalidated_a[outcome_bar] = True

    return (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a,
        top1_bar_a, neck1_bar_a, top2_bar_a, neck2_bar_a, top3_bar_a,
        top1_price_a, neck1_price_a, top2_price_a, neck2_price_a, top3_price_a,
    )


def _hs_shape_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.25,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.05,
    efficiency_ratio_min: float = 0.1,
    efficiency_ratio_floor: float = 0.05,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.9,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.15,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.9,
    breakout_deadline_basis: str = "top1_top2",
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_min: float = 0.3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.5,
    interval_symmetry_ratio_max: float = 2.0,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
    neck_tolerance_mult: float = 0.4,
    head_prominence_mult: float = 0.5,
) -> dict[str, pd.Series]:
    """docs/pattern_spec_head_and_shoulders_shape.md 参照。bullish=Trueで
    逆ヘッド・アンド・ショルダーズ(逆三尊)、Falseでヘッド・アンド・
    ショルダーズ(三尊天井)。トリプルトップ/ボトムST(_triple_top_bottom_
    shape_state)を土台に、山2(頭)の水準判定(肩より明確に高い)とネック
    ライン(傾き許容)の2点だけを変更したもの。"""
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

    pivot_left_bars = max(0, pivot_left_bars)
    pivot_right_bars = max(0, pivot_right_bars)
    if pivot_left_bars == 0 and pivot_right_bars == 0:
        pivot_left_bars = 1

    min_bars_between_tops = pivot_right_bars

    ext_price_a = low_a if bullish else high_a
    neck_price_a = high_a if bullish else low_a

    boundary_other_a = high_a if bullish else low_a
    prom_thresh = atr_a * prominence_atr_mult
    ext_flags = (
        _pivot_flags(low if bullish else high, pivot_left_bars, pivot_right_bars, not bullish).to_numpy()
        & _prominence_flags(ext_price_a, boundary_other_a, pivot_left_bars, pivot_right_bars, prom_thresh, not bullish)
    )

    neck_boundary_other_a = low_a if bullish else high_a
    neck_flags = (
        _pivot_flags(high if bullish else low, pivot_left_bars, pivot_right_bars, bullish).to_numpy()
        & _prominence_flags(neck_price_a, neck_boundary_other_a, pivot_left_bars, pivot_right_bars, prom_thresh, bullish)
    )

    plain_pivot_ext_left_only = (
        _detect_pivot_lows_left_only(low, pivot_left_bars)
        if bullish
        else _detect_pivot_highs_left_only(high, pivot_left_bars)
    ).to_numpy()
    prominence_ok_ext_left_only = _prominence_flags(ext_price_a, boundary_other_a, pivot_left_bars, 0, prom_thresh, not bullish)
    ext_flags_top3 = plain_pivot_ext_left_only & prominence_ok_ext_left_only

    pivot_confirm_lag = pivot_right_bars

    (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a,
        top1_bar_a, neck1_bar_a, top2_bar_a, neck2_bar_a, top3_bar_a,
        top1_price_a, neck1_price_a, top2_price_a, neck2_price_a, top3_price_a,
    ) = _shape_state_core_hs(
        high_a, low_a, close_a, atr_a,
        ext_price_a, neck_price_a,
        ext_flags, neck_flags, ext_flags_top3,
        bool(bullish),
        int(pivot_confirm_lag),
        float(pivot_spike_excess_atr_max), float(pivot_spike_window_ratio),
        int(min_bars_between_tops), int(max_bars_between_tops),
        float(symmetry_ratio_min), float(symmetry_ratio_max),
        top_tolerance_basis == "price_pct", float(top_tolerance_atr_mult), float(top_tolerance_mult),
        float(min_valley_depth_atr_mult), float(max_valley_depth_atr_mult),
        breakout_buffer_basis == "price_pct", float(breakout_buffer_atr_mult), float(breakout_buffer_mult),
        float(efficiency_ratio_min), float(efficiency_ratio_floor),
        trendline_dev_basis == "atr", float(trendline_dev_atr_mult), float(trendline_dev_pct),
        float(efficiency_ratio_min_context),
        trendline_dev_basis_context == "atr", float(trendline_dev_atr_mult_context), float(trendline_dev_pct_context),
        float(efficiency_ratio_min_breakout),
        trendline_dev_basis_breakout == "atr", float(trendline_dev_atr_mult_breakout), float(trendline_dev_pct_breakout),
        breakout_deadline_basis == "top1_top2", int(breakout_deadline_min_bars),
        float(breakout_deadline_ratio_min), float(breakout_deadline_ratio_max),
        float(interval_symmetry_ratio_min), float(interval_symmetry_ratio_max),
        float(terminal_bounce_close_mult),
        breakout_type == "close",
        float(neck_tolerance_mult),
        float(head_prominence_mult),
    )

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "candidate": pd.Series(detected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "invalidated": pd.Series(invalidated_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "top1_bar": pd.Series(top1_bar_a, index=idx_index),
        "neck1_bar": pd.Series(neck1_bar_a, index=idx_index),
        "top2_bar": pd.Series(top2_bar_a, index=idx_index),
        "neck2_bar": pd.Series(neck2_bar_a, index=idx_index),
        "top3_bar": pd.Series(top3_bar_a, index=idx_index),
        "top1_price": pd.Series(top1_price_a, index=idx_index),
        "neck1_price": pd.Series(neck1_price_a, index=idx_index),
        "top2_price": pd.Series(top2_price_a, index=idx_index),
        "neck2_price": pd.Series(neck2_price_a, index=idx_index),
        "top3_price": pd.Series(top3_price_a, index=idx_index),
    }


def inverse_head_and_shoulders_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.25,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.05,
    efficiency_ratio_min: float = 0.1,
    efficiency_ratio_floor: float = 0.05,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.9,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.15,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.9,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.5,
    interval_symmetry_ratio_max: float = 2.0,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
    neck_tolerance_mult: float = 0.4,
    head_prominence_mult: float = 0.5,
    **p,
) -> np.ndarray:
    """逆ヘッド・アンド・ショルダーズ(逆三尊、形状判定版) -
    docs/pattern_spec_head_and_shoulders_shape.md 参照。"""
    result = _hs_shape_state(
        high, low, close, True,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_mult,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_mult,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        efficiency_ratio_min_context,
        trendline_dev_basis_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
        efficiency_ratio_min_breakout,
        trendline_dev_basis_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        terminal_bounce_close_mult,
        breakout_type,
        neck_tolerance_mult,
        head_prominence_mult,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def head_and_shoulders_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_tops: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    top_tolerance_basis: str = "price_pct",
    top_tolerance_atr_mult: float = 2.0,
    top_tolerance_mult: float = 0.25,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.05,
    efficiency_ratio_min: float = 0.1,
    efficiency_ratio_floor: float = 0.05,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.9,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    efficiency_ratio_min_breakout: float = 0.15,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.9,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    interval_symmetry_ratio_min: float = 0.5,
    interval_symmetry_ratio_max: float = 2.0,
    terminal_bounce_close_mult: float = 0.7,
    breakout_type: str = "close",
    neck_tolerance_mult: float = 0.4,
    head_prominence_mult: float = 0.5,
    **p,
) -> np.ndarray:
    """ヘッド・アンド・ショルダーズ(三尊天井、形状判定版) -
    docs/pattern_spec_head_and_shoulders_shape.md 参照。"""
    result = _hs_shape_state(
        high, low, close, False,
        pivot_left_bars, pivot_right_bars, prominence_atr_mult,
        pivot_spike_excess_atr_max, pivot_spike_window_ratio,
        max_bars_between_tops,
        symmetry_ratio_min, symmetry_ratio_max,
        top_tolerance_basis, top_tolerance_atr_mult, top_tolerance_mult,
        min_valley_depth_atr_mult, max_valley_depth_atr_mult,
        breakout_buffer_basis, breakout_buffer_atr_mult, breakout_buffer_mult,
        efficiency_ratio_min, efficiency_ratio_floor,
        trendline_dev_basis, trendline_dev_atr_mult, trendline_dev_pct,
        efficiency_ratio_min_context,
        trendline_dev_basis_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
        efficiency_ratio_min_breakout,
        trendline_dev_basis_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
        "top1_top2", breakout_deadline_min_bars, 0.3, breakout_deadline_ratio_max,
        interval_symmetry_ratio_min, interval_symmetry_ratio_max,
        terminal_bounce_close_mult,
        breakout_type,
        neck_tolerance_mult,
        head_prominence_mult,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# チャネル系(レクタングル/トライアングル/ウェッジ/ペナント/フラッグ)
# 共通コア - docs/pattern_spec_channel_patterns_shape.md 参照。
#
# トリプルST/H&Sの5点(山1-ネック1-山2-ネック2-山3)と違い、この6家系は
# 「4点(点1-点2-点3-点4)で2本の境界線を引き、傾きの組み合わせで模様が
# 決まる」という共通の骨格を持つ。探索・先読み防止・3状態モデルは
# 1つのnjitコアにまとめ、家系ごとの違い(水平/上昇/下降/収束/平行の分類、
# ブレイク方向)はコアの外(Pythonの後処理)で判定する - 詳しくは仕様書
# §0/§4。
# ---------------------------------------------------------------------------


@njit(cache=True)
def _shape_state_core_channel(
    high_a, low_a, close_a, atr_a,
    typeA_price_a, typeB_price_a,
    typeA_flags, typeB_flags, typeB_flags_left_only,
    start_is_low, want_upper_break,
    pivot_confirm_lag,
    pivot_spike_excess_atr_max, pivot_spike_window_ratio,
    min_bars_between_points, max_bars_between_points,
    symmetry_ratio_min, symmetry_ratio_max,
    breakout_buffer_is_pct, breakout_buffer_atr_mult, breakout_buffer_mult,
    efficiency_ratio_min, efficiency_ratio_floor,
    trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct,
    efficiency_ratio_min_context,
    trendline_dev_is_atr_context, trendline_dev_atr_mult_context, trendline_dev_pct_context,
    pole_height_min_mult, pole_lookback_ratio,
    efficiency_ratio_min_breakout,
    trendline_dev_is_atr_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout,
    breakout_deadline_min_bars, breakout_deadline_ratio_max,
    breakout_type_is_close,
):
    n = high_a.shape[0]
    effective_max_bars_between_points = (
        max_bars_between_points if max_bars_between_points > 0 else _MAX_BARS_BETWEEN_TOPS_UNLIMITED_CAP
    )
    effective_symmetry_ratio_max = symmetry_ratio_max if symmetry_ratio_max > 0.0 else _UNLIMITED_RATIO
    effective_breakout_deadline_ratio_max = (
        breakout_deadline_ratio_max if breakout_deadline_ratio_max > 0.0 else _UNLIMITED_RATIO
    )

    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)
    resolve_a = np.zeros(n, dtype=np.bool_)
    invalidated_a = np.zeros(n, dtype=np.bool_)
    broke_upper_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    p1_bar_a = np.full(n, np.nan)
    p2_bar_a = np.full(n, np.nan)
    p3_bar_a = np.full(n, np.nan)
    p4_bar_a = np.full(n, np.nan)
    p1_price_a = np.full(n, np.nan)
    p2_price_a = np.full(n, np.nan)
    p3_price_a = np.full(n, np.nan)
    p4_price_a = np.full(n, np.nan)

    typeA_events = np.flatnonzero(typeA_flags)
    typeB_events = np.flatnonzero(typeB_flags)
    typeB_events_left_only = np.flatnonzero(typeB_flags_left_only)
    n_typeB = typeB_events.shape[0]
    n_typeB_lo = typeB_events_left_only.shape[0]

    for ei in range(typeA_events.shape[0]):
        p1_bar = typeA_events[ei]
        p1_price = typeA_price_a[p1_bar]
        p1_confirm_bar = p1_bar + pivot_confirm_lag

        # --- 点2探索(typeB、両側確認、より極端な値のときだけ更新) ---
        win_start2 = p1_bar + min_bars_between_points
        win_end2 = p1_bar + effective_max_bars_between_points
        if win_end2 > n - 1:
            win_end2 = n - 1
        if win_start2 > win_end2:
            continue

        p2_bar = -1
        p2_price = 0.0
        start_idx2 = np.searchsorted(typeB_events, win_start2, side="left")
        for ki in range(start_idx2, n_typeB):
            k = typeB_events[ki]
            if k > win_end2:
                break
            cand_price = typeB_price_a[k]
            if start_is_low:
                is_more_extreme = (p2_bar == -1) or (cand_price > p2_price)
            else:
                is_more_extreme = (p2_bar == -1) or (cand_price < p2_price)
            if is_more_extreme:
                p2_bar = k
                p2_price = cand_price
        if p2_bar == -1:
            continue
        p2_confirm_bar = p2_bar + pivot_confirm_lag

        i1 = p2_bar - p1_bar
        p1_right_window = int(round(i1 * pivot_spike_window_ratio))
        p1_right_ok = _shape_spike_ok(typeA_price_a, atr_a, n, p1_bar, p1_right_window,
                                       True, not start_is_low, pivot_spike_excess_atr_max)
        p2_left_ok = _shape_spike_ok(typeB_price_a, atr_a, n, p2_bar, p1_right_window,
                                      False, start_is_low, pivot_spike_excess_atr_max)

        # --- 点3探索(typeA、両側確認) ---
        win_start3 = p2_bar + int(np.ceil(i1 * symmetry_ratio_min))
        win_end3 = p2_bar + int(np.floor(i1 * effective_symmetry_ratio_max))
        abs_win_start3 = p2_bar + min_bars_between_points
        if abs_win_start3 > win_start3:
            win_start3 = abs_win_start3
        abs_win_end3 = p2_bar + effective_max_bars_between_points
        if abs_win_end3 < win_end3:
            win_end3 = abs_win_end3
        if win_end3 > n - 1:
            win_end3 = n - 1
        if win_start3 > win_end3:
            continue

        p3_bar = -1
        p3_price = 0.0
        start_idx3 = np.searchsorted(typeA_events, win_start3, side="left")
        for ki in range(start_idx3, typeA_events.shape[0]):
            k = typeA_events[ki]
            if k > win_end3:
                break
            cand_price = typeA_price_a[k]
            if start_is_low:
                is_more_extreme = (p3_bar == -1) or (cand_price < p3_price)
            else:
                is_more_extreme = (p3_bar == -1) or (cand_price > p3_price)
            if is_more_extreme:
                p3_bar = k
                p3_price = cand_price
        if p3_bar == -1:
            continue
        p3_confirm_bar = p3_bar + pivot_confirm_lag

        i2 = p3_bar - p2_bar
        p2_right_window = int(round(i2 * pivot_spike_window_ratio))
        p2_right_ok = _shape_spike_ok(typeB_price_a, atr_a, n, p2_bar, p2_right_window,
                                       True, start_is_low, pivot_spike_excess_atr_max)
        p3_left_ok = _shape_spike_ok(typeA_price_a, atr_a, n, p3_bar, p2_right_window,
                                      False, not start_is_low, pivot_spike_excess_atr_max)
        if not (p2_left_ok or p2_right_ok):
            continue

        # --- 点4探索(typeB、左側のみ確認 - 先読み防止) ---
        win_start4 = p3_bar + int(np.ceil(i2 * symmetry_ratio_min))
        win_end4 = p3_bar + int(np.floor(i2 * effective_symmetry_ratio_max))
        abs_win_start4 = p3_bar + min_bars_between_points
        if abs_win_start4 > win_start4:
            win_start4 = abs_win_start4
        abs_win_end4 = p3_bar + effective_max_bars_between_points
        if abs_win_end4 < win_end4:
            win_end4 = abs_win_end4
        if win_end4 > n - 1:
            win_end4 = n - 1
        if win_start4 > win_end4:
            continue

        p4_bar = -1
        p4_price = 0.0
        start_idx4 = np.searchsorted(typeB_events_left_only, win_start4, side="left")
        for ki in range(start_idx4, n_typeB_lo):
            k = typeB_events_left_only[ki]
            if k > win_end4:
                break
            cand_price = typeB_price_a[k]
            if start_is_low:
                is_more_extreme = (p4_bar == -1) or (cand_price > p4_price)
            else:
                is_more_extreme = (p4_bar == -1) or (cand_price < p4_price)
            if is_more_extreme:
                p4_bar = k
                p4_price = cand_price
        if p4_bar == -1:
            continue

        i3 = p4_bar - p3_bar
        p3_right_window = int(round(i3 * pivot_spike_window_ratio))
        p3_right_ok = _shape_spike_ok(typeA_price_a, atr_a, n, p3_bar, p3_right_window,
                                       True, not start_is_low, pivot_spike_excess_atr_max)
        p4_left_ok = _shape_spike_ok(typeB_price_a, atr_a, n, p4_bar, p3_right_window,
                                      False, start_is_low, pivot_spike_excess_atr_max)
        if not (p3_left_ok or p3_right_ok):
            continue

        # --- 点1前点(旗竿の脚、§3.3、2026-08-14訂正) ---
        # トリプル/H&Sは「隣接するネックの水準を再びまたいだ地点」を
        # pre_barとして逆走査したが、この方式は点2の水準が点1から遠い
        # (箱の高さぶん離れている)チャネル系では機能しない - 逆走査が
        # 点2の水準に達する前に配列の先頭に達し、pre_barが一切見つからず
        # 候補ごと不成立になる不具合が実際に起きた(2026-08-14、合成データの
        # 単体テストで発覚)。代わりに「点1より前、直近i1×pole_lookback_
        # ratio本以内で最も反対側に振れた1本」を機械的に選ぶ(価格水準の
        # 再現を待たない分、必ず見つかる)。
        leg1_amp = abs(p2_price - p1_price)
        pole_lookback = int(i1 * pole_lookback_ratio)
        if pole_lookback < 1:
            pole_lookback = 1
        pre_win_start = p1_bar - pole_lookback
        if pre_win_start < 0:
            pre_win_start = 0
        if pre_win_start >= p1_bar:
            continue

        pre_bar = pre_win_start
        if start_is_low:
            pre_level = high_a[pre_win_start]
            for j in range(pre_win_start + 1, p1_bar):
                if high_a[j] > pre_level:
                    pre_level = high_a[j]
                    pre_bar = j
        else:
            pre_level = low_a[pre_win_start]
            for j in range(pre_win_start + 1, p1_bar):
                if low_a[j] < pre_level:
                    pre_level = low_a[j]
                    pre_bar = j

        p1_left_window = int(round((p1_bar - pre_bar) * pivot_spike_window_ratio))
        p1_left_ok = _shape_spike_ok(typeA_price_a, atr_a, n, p1_bar, p1_left_window,
                                      False, not start_is_low, pivot_spike_excess_atr_max)
        if not (p1_left_ok or p1_right_ok):
            continue

        # 旗竿の高さ下限(ペナント/フラッグのみ有効、pole_height_min_mult=0で無効)。
        if pole_height_min_mult > 0.0:
            pole_height = abs(p1_price - pre_level)
            if pole_height < atr_a[p1_bar] * pole_height_min_mult:
                continue

        confirm_floor = p1_confirm_bar
        if p2_confirm_bar > confirm_floor:
            confirm_floor = p2_confirm_bar
        if p3_confirm_bar > confirm_floor:
            confirm_floor = p3_confirm_bar
        if p4_bar > confirm_floor:  # 点4は左側のみ確定、+lag無し
            confirm_floor = p4_bar
        if confirm_floor >= n:
            continue

        eff_ctx = _shape_eff_ratio(close_a, pre_bar, p1_bar)
        eff_a = _shape_eff_ratio(close_a, p1_bar, p2_bar)
        eff_b = _shape_eff_ratio(close_a, p2_bar, p3_bar)
        eff_c = _shape_eff_ratio(close_a, p3_bar, p4_bar)

        core_legs_ok = (
            eff_a >= efficiency_ratio_floor
            and eff_b >= efficiency_ratio_floor
            and eff_c >= efficiency_ratio_floor
            and (eff_a + eff_b + eff_c) / 3.0 >= efficiency_ratio_min
            and _shape_dev_ok(high_a, low_a, atr_a, p1_bar, p1_price, p2_bar, p2_price,
                               trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
            and _shape_dev_ok(high_a, low_a, atr_a, p2_bar, p2_price, p3_bar, p3_price,
                               trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
            and _shape_dev_ok(high_a, low_a, atr_a, p3_bar, p3_price, p4_bar, p4_price,
                               trendline_dev_is_atr, trendline_dev_atr_mult, trendline_dev_pct)
        )
        context_legs_ok = (
            eff_ctx >= efficiency_ratio_min_context
            and _shape_dev_ok(high_a, low_a, atr_a, pre_bar, pre_level, p1_bar, p1_price,
                               trendline_dev_is_atr_context, trendline_dev_atr_mult_context, trendline_dev_pct_context)
        )
        if not (core_legs_ok and context_legs_ok):
            continue

        formed_bar = confirm_floor
        detected_a[formed_bar] = True

        # --- 2本の境界線をブレイク方向にかかわらず両方監視し、先に破られた
        # 方(broke_upper)を判定する(§3.1/3.2)。 ---
        typeA_slope = (p3_price - p1_price) / (p3_bar - p1_bar)
        typeB_slope = (p4_price - p2_price) / (p4_bar - p2_bar)

        expire_bars = i1 * effective_breakout_deadline_ratio_max
        scan_start = p4_bar + 1
        scan_end = p4_bar + int(np.ceil(expire_bars))
        if scan_end > n - 1:
            scan_end = n - 1

        outcome = 4  # expired
        outcome_bar = scan_end
        outcome_broke_upper = False

        if scan_start <= scan_end:
            for j in range(scan_start, scan_end + 1):
                buf_j = leg1_amp * breakout_buffer_mult if breakout_buffer_is_pct else atr_a[j] * breakout_buffer_atr_mult
                typeA_at_j = p1_price + typeA_slope * (j - p1_bar)
                typeB_at_j = p2_price + typeB_slope * (j - p2_bar)
                if start_is_low:
                    lower_at_j = typeA_at_j
                    upper_at_j = typeB_at_j
                else:
                    lower_at_j = typeB_at_j
                    upper_at_j = typeA_at_j

                if breakout_type_is_close:
                    up_j = close_a[j] > (upper_at_j + buf_j)
                    down_j = close_a[j] < (lower_at_j - buf_j)
                else:
                    up_j = high_a[j] > (upper_at_j + buf_j)
                    down_j = low_a[j] < (lower_at_j - buf_j)

                if not (up_j or down_j):
                    continue

                # 同じバーで両方破った場合は want_upper_break 側を優先
                # (どちらの向きの判定を求めているかで tie-break、§3.2)。
                if up_j and down_j:
                    broke_upper_j = want_upper_break
                else:
                    broke_upper_j = up_j

                bars_since_p4 = j - p4_bar
                if bars_since_p4 < breakout_deadline_min_bars:
                    outcome = 1  # rejected
                    outcome_bar = j
                    outcome_broke_upper = broke_upper_j
                    break

                match = (broke_upper_j == want_upper_break)
                if not match:
                    outcome = 3  # failed(逆方向のブレイク)
                    outcome_bar = j
                    outcome_broke_upper = broke_upper_j
                    break

                eff_brk = _shape_eff_ratio(close_a, p4_bar, j)
                end_price_for_dev = close_a[j] if breakout_type_is_close else (high_a[j] if broke_upper_j else low_a[j])
                p4_right_window = j - p4_bar
                if p4_right_window > int(round(i3 * pivot_spike_window_ratio)):
                    p4_right_window = int(round(i3 * pivot_spike_window_ratio))
                p4_right_ok = _shape_spike_ok(typeB_price_a, atr_a, n, p4_bar, p4_right_window,
                                               True, start_is_low, pivot_spike_excess_atr_max)
                p4_isolation_ok = p4_left_ok or p4_right_ok

                breakout_leg_ok = (
                    eff_brk >= efficiency_ratio_min_breakout
                    and p4_isolation_ok
                    and _shape_dev_ok(high_a, low_a, atr_a, p4_bar, p4_price, j, end_price_for_dev,
                                       trendline_dev_is_atr_breakout, trendline_dev_atr_mult_breakout, trendline_dev_pct_breakout)
                )
                outcome = 2 if breakout_leg_ok else 1
                outcome_bar = j
                outcome_broke_upper = broke_upper_j
                break

        if outcome_bar < formed_bar:
            outcome_bar = formed_bar

        exists_end = outcome_bar
        for _idx in range(formed_bar, exists_end + 1):
            if _idx == formed_bar or not detected_a[_idx]:
                exists_a[_idx] = True
                formed_bar_a[_idx] = formed_bar
        p1_bar_a[formed_bar] = p1_bar
        p2_bar_a[formed_bar] = p2_bar
        p3_bar_a[formed_bar] = p3_bar
        p4_bar_a[formed_bar] = p4_bar
        p1_price_a[formed_bar] = p1_price
        p2_price_a[formed_bar] = p2_price
        p3_price_a[formed_bar] = p3_price
        p4_price_a[formed_bar] = p4_price

        if outcome == 2:
            resolve_a[outcome_bar] = True
            broke_upper_a[outcome_bar] = outcome_broke_upper
        else:
            invalidated_a[outcome_bar] = True

    return (
        exists_a, detected_a, invalidated_a, resolve_a, broke_upper_a,
        formed_bar_a,
        p1_bar_a, p2_bar_a, p3_bar_a, p4_bar_a,
        p1_price_a, p2_price_a, p3_price_a, p4_price_a,
    )


# ---------------------------------------------------------------------------


def _channel_shape_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    start_is_low: bool,
    want_upper_break: bool,
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    prominence_atr_mult: float = 0.0,
    pivot_spike_excess_atr_max: float = 1.3,
    pivot_spike_window_ratio: float = 0.5,
    max_bars_between_points: int = 0,
    symmetry_ratio_min: float = 0.0,
    symmetry_ratio_max: float = 3.33,
    breakout_buffer_basis: str = "price_pct",
    breakout_buffer_atr_mult: float = 0.5,
    breakout_buffer_mult: float = 0.05,
    efficiency_ratio_min: float = 0.1,
    efficiency_ratio_floor: float = 0.05,
    trendline_dev_basis: str = "price_pct",
    trendline_dev_atr_mult: float = 0.9,
    trendline_dev_pct: float = 0.9,
    efficiency_ratio_min_context: float = 0.1,
    trendline_dev_basis_context: str = "price_pct",
    trendline_dev_atr_mult_context: float = 0.9,
    trendline_dev_pct_context: float = 0.9,
    pole_height_min_mult: float = 0.0,
    pole_lookback_ratio: float = 3.0,
    efficiency_ratio_min_breakout: float = 0.15,
    trendline_dev_basis_breakout: str = "price_pct",
    trendline_dev_atr_mult_breakout: float = 0.9,
    trendline_dev_pct_breakout: float = 0.9,
    breakout_deadline_min_bars: int = 3,
    breakout_deadline_ratio_max: float = 3.33,
    breakout_type: str = "close",
) -> dict[str, pd.Series]:
    """docs/pattern_spec_channel_patterns_shape.md 参照。start_is_low=Trueで
    点1・点3が安値(下側の線)、点2・点4が高値(上側の線)。want_upper_break=
    Trueで上側の線を上抜けたときにconfirmed。傾きの分類(水平/上昇/下降/
    収束/平行)はこの関数の外(各家系のpublic関数)で行う。"""
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

    pivot_left_bars = max(0, pivot_left_bars)
    pivot_right_bars = max(0, pivot_right_bars)
    if pivot_left_bars == 0 and pivot_right_bars == 0:
        pivot_left_bars = 1

    min_bars_between_points = pivot_right_bars

    typeA_price_a = low_a if start_is_low else high_a
    typeB_price_a = high_a if start_is_low else low_a
    typeA_boundary_other_a = high_a if start_is_low else low_a
    typeB_boundary_other_a = low_a if start_is_low else high_a

    prom_thresh = atr_a * prominence_atr_mult
    typeA_flags = (
        _pivot_flags(low if start_is_low else high, pivot_left_bars, pivot_right_bars, not start_is_low).to_numpy()
        & _prominence_flags(typeA_price_a, typeA_boundary_other_a, pivot_left_bars, pivot_right_bars, prom_thresh, not start_is_low)
    )
    typeB_flags = (
        _pivot_flags(high if start_is_low else low, pivot_left_bars, pivot_right_bars, start_is_low).to_numpy()
        & _prominence_flags(typeB_price_a, typeB_boundary_other_a, pivot_left_bars, pivot_right_bars, prom_thresh, start_is_low)
    )
    plain_pivot_typeB_left_only = (
        _detect_pivot_highs_left_only(high, pivot_left_bars)
        if start_is_low
        else _detect_pivot_lows_left_only(low, pivot_left_bars)
    ).to_numpy()
    prominence_ok_typeB_left_only = _prominence_flags(
        typeB_price_a, typeB_boundary_other_a, pivot_left_bars, 0, prom_thresh, start_is_low
    )
    typeB_flags_left_only = plain_pivot_typeB_left_only & prominence_ok_typeB_left_only

    pivot_confirm_lag = pivot_right_bars

    (
        exists_a, detected_a, invalidated_a, resolve_a, broke_upper_a,
        formed_bar_a,
        p1_bar_a, p2_bar_a, p3_bar_a, p4_bar_a,
        p1_price_a, p2_price_a, p3_price_a, p4_price_a,
    ) = _shape_state_core_channel(
        high_a, low_a, close_a, atr_a,
        typeA_price_a, typeB_price_a,
        typeA_flags, typeB_flags, typeB_flags_left_only,
        bool(start_is_low), bool(want_upper_break),
        int(pivot_confirm_lag),
        float(pivot_spike_excess_atr_max), float(pivot_spike_window_ratio),
        int(min_bars_between_points), int(max_bars_between_points),
        float(symmetry_ratio_min), float(symmetry_ratio_max),
        breakout_buffer_basis == "price_pct", float(breakout_buffer_atr_mult), float(breakout_buffer_mult),
        float(efficiency_ratio_min), float(efficiency_ratio_floor),
        trendline_dev_basis == "atr", float(trendline_dev_atr_mult), float(trendline_dev_pct),
        float(efficiency_ratio_min_context),
        trendline_dev_basis_context == "atr", float(trendline_dev_atr_mult_context), float(trendline_dev_pct_context),
        float(pole_height_min_mult), float(pole_lookback_ratio),
        float(efficiency_ratio_min_breakout),
        trendline_dev_basis_breakout == "atr", float(trendline_dev_atr_mult_breakout), float(trendline_dev_pct_breakout),
        int(breakout_deadline_min_bars), float(breakout_deadline_ratio_max),
        breakout_type == "close",
    )

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "candidate": pd.Series(detected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "invalidated": pd.Series(invalidated_a, index=idx_index),
        "broke_upper": pd.Series(broke_upper_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "p1_bar": pd.Series(p1_bar_a, index=idx_index),
        "p2_bar": pd.Series(p2_bar_a, index=idx_index),
        "p3_bar": pd.Series(p3_bar_a, index=idx_index),
        "p4_bar": pd.Series(p4_bar_a, index=idx_index),
        "p1_price": pd.Series(p1_price_a, index=idx_index),
        "p2_price": pd.Series(p2_price_a, index=idx_index),
        "p3_price": pd.Series(p3_price_a, index=idx_index),
        "p4_price": pd.Series(p4_price_a, index=idx_index),
    }


def _channel_classify_mask(
    raw: dict[str, pd.Series],
    start_is_low: bool,
    top_tolerance_mult: float,
    lower_kind: str,   # "flat" | "rising" | "falling" | "any" (物理的に下側の線)
    upper_kind: str,   # "flat" | "rising" | "falling" | "any" (物理的に上側の線)
    require_converging: bool = False,
    require_parallel: bool = False,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
) -> pd.Series:
    """docs/pattern_spec_channel_patterns_shape.md §4 の分類ロジック。
    _channel_shape_stateの生の出力(点1〜4のbar/price)から、家系ごとの
    形状条件(水平/上昇/下降/収束/平行)を満たすかをバーごとのbool Seriesで
    返す。njitコアの外(ベクトル演算)で行うことで、6家系ぶんの分類を
    共通コア1つの複製なしに実装している(仕様書§0)。

    start_is_low=Trueなら点1・点3が安値(=物理的に下側の線)、点2・点4が
    高値(=物理的に上側の線)。start_is_low=Falseはその逆(点1・点3が上側)
    - lower_kind/upper_kindは常に「物理的にどちらの線か」を指すため、
    ここで点の組をstart_is_lowに応じて入れ替える(2026-08-14訂正: 当初
    start_is_low=Falseの場合も点1・点3を無条件に「下側」として判定して
    おり、上側・下側が逆に判定される不具合があった - 単体テストでは
    lower_kind/upper_kindが対称(both flat等)な家系しか使っておらず
    見逃していた)。"""
    p1 = raw["p1_price"]
    p2 = raw["p2_price"]
    p3 = raw["p3_price"]
    p4 = raw["p4_price"]
    p1b = raw["p1_bar"]
    p2b = raw["p2_bar"]
    p3b = raw["p3_bar"]
    p4b = raw["p4_bar"]

    if start_is_low:
        lo_a, lo_b, lo_ab, lo_bb = p1, p3, p1b, p3b
        up_a, up_b, up_ab, up_bb = p2, p4, p2b, p4b
    else:
        lo_a, lo_b, lo_ab, lo_bb = p2, p4, p2b, p4b
        up_a, up_b, up_ab, up_bb = p1, p3, p1b, p3b

    base_leg = (p2 - p1).abs()
    tol = pd.Series(np.inf, index=base_leg.index) if top_tolerance_mult <= 0.0 else base_leg * top_tolerance_mult

    def _kind_ok(a: pd.Series, b: pd.Series, kind: str) -> pd.Series:
        if kind == "any":
            return pd.Series(True, index=a.index)
        diff = b - a
        if kind == "flat":
            return diff.abs() <= tol
        if kind == "rising":
            return diff > tol
        if kind == "falling":
            return (-diff) > tol
        raise ValueError(f"未対応のkindです: {kind}")

    mask = _kind_ok(lo_a, lo_b, lower_kind) & _kind_ok(up_a, up_b, upper_kind)

    if require_converging or require_parallel:
        lower_slope = (lo_b - lo_a) / (lo_bb - lo_ab)
        upper_slope = (up_b - up_a) / (up_bb - up_ab)
        # 点1は常に最初、点4は常に最後(構成点の探索順序が保証する)。
        entry_width = (up_a + upper_slope * (p1b - up_ab)) - (lo_a + lower_slope * (p1b - lo_ab))
        exit_width = (up_a + upper_slope * (p4b - up_ab)) - (lo_a + lower_slope * (p4b - lo_ab))
        if require_converging:
            mask = mask & (exit_width < entry_width * (1.0 - converge_margin))
        if require_parallel:
            mask = mask & ((exit_width - entry_width).abs() <= entry_width.abs() * width_tol)

    return mask.fillna(False)


def _channel_family_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    start_is_low: bool,
    want_upper_break: bool,
    lower_kind: str,
    upper_kind: str,
    require_converging: bool,
    require_parallel: bool,
    top_tolerance_mult: float,
    converge_margin: float,
    width_tol: float,
    **kwargs: Any,
) -> dict[str, pd.Series]:
    """_channel_shape_state + _channel_classify_mask をまとめ、家系に
    合わない候補(exists/candidate/confirmed/invalidated全て)を丸ごと
    除外する(仕様書§4 - 「そもそもこの家系の形ではなかった」ものは
    Invalidatedにもしない)。

    点1〜4のbar/priceはformed_bar(候補が確定した時点)にしか記録されて
    いない一方、confirmed/invalidatedはブレイク成立バー(formed_barより
    後)に立つ。分類判定(_channel_classify_mask)をそのままconfirmed/
    invalidatedの位置に適用すると点データがNaNの位置を読むことになり
    常にFalseになってしまう不具合があったため(2026-08-14、単体テストで
    発覚)、必ずformed_bar経由で点データの位置へ引き直してから判定する。"""
    raw = _channel_shape_state(high, low, close, start_is_low, want_upper_break, **kwargs)
    ok_at_formed = _channel_classify_mask(
        raw, start_is_low, top_tolerance_mult, lower_kind, upper_kind,
        require_converging, require_parallel, converge_margin, width_tol,
    ).to_numpy()

    formed_bar_a = raw["formed_bar"].to_numpy()
    valid = ~np.isnan(formed_bar_a)
    fb_int = np.zeros(formed_bar_a.shape[0], dtype=np.int64)
    fb_int[valid] = formed_bar_a[valid].astype(np.int64)
    ok_arr = np.zeros(formed_bar_a.shape[0], dtype=bool)
    ok_arr[valid] = ok_at_formed[fb_int[valid]]
    ok = pd.Series(ok_arr, index=raw["formed_bar"].index)

    out = dict(raw)
    for key in ("exists", "candidate", "confirmed", "invalidated"):
        out[key] = raw[key] & ok
    return out


_CHANNEL_STATE_KEYS = _SHAPE_STATE_KEYS


def _channel_indicator(
    high: pd.Series, low: pd.Series, close: pd.Series,
    start_is_low: bool,
    want_upper_break: bool,
    lower_kind: str,
    upper_kind: str,
    require_converging: bool,
    require_parallel: bool,
    state: str,
    top_tolerance_mult: float,
    converge_margin: float,
    width_tol: float,
    **kwargs: Any,
) -> np.ndarray:
    result = _channel_family_state(
        high, low, close, start_is_low, want_upper_break,
        lower_kind, upper_kind, require_converging, require_parallel,
        top_tolerance_mult, converge_margin, width_tol, **kwargs,
    )
    key = _CHANNEL_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# 上昇ボックス v2(可変タッチ方式) - docs/pattern_spec_ascending_box_shape_v2.md
#
# 旧実装(上のascending_box_shape、4点固定・共通コア方式)を置き換える。
# 2026-08-15、ユーザー判断で「タッチ回数を2回以上の可変にし、全採用点の
# 極値(平均ではない)で水準を判定する」方式に全面変更。下降ボックス以降
# 4家系(_channel_shape_state系)はこの仕様が検証されるまで旧方式のまま。
#
# 山1・谷1・山2(=最小構成の前半)は両側確認ピボット、谷2以降・山3以降は
# 左側のみ確認(先読み防止、トリプル/H&Sの「最後の1点だけ左本数」を可変
# 本数向けに拡張)。カウフマン効率比・直線乖離・孤立度チェック・事前上昇
# (旗竿)は使わない(ユーザー判断)。
#
# 実装方針: トリプル/H&Sと同じ「先読み防止の分離」戦略を採用する - 山/谷の
# 連鎖探索そのものはピボットイベントの位置を即座に分かっているものとして
# 貪欲に(ラグを気にせず)行い、探索が終わった後にconfirm_floor(両側確認点
# は+pivot_right_bars、左側のみ確認点は+0の最大値)を計算してformed_bar/
# outcome_barをそこまで繰り上げる、という形で先読みを防ぐ(triple/H&Sの
# 既存パターンと同じ考え方)。
# ---------------------------------------------------------------------------

_ASC_BOX_MAX_TOUCHES = 40  # min_touch_gap_bars(既定5)×max_box_bars(既定250)から見て十分な余裕


@njit(cache=True)
def _asc_box_find_touch(same_events, opposite_events, lo_bar, max_scan, is_high_type,
                         high_a, low_a, opposite_gap_floor):
    """同じ型のイベント配列(same_events)の中から、lo_bar以降で最も極端な点を
    extreme-wins方式で探す。緩やかな傾き区間では左側のみ確認ピボットが
    何本も連続して条件を満たしてしまう(単調に下がる区間の途中の1本を
    「谷」として拾ってしまう)ため、単純に最初の候補を採用すると本当の
    極値より手前で確定してしまう不具合があった(2026-08-15、単体テストで
    発覚)。

    「反対側の有効な候補が現れたら打ち切る」という先読みだけでは、
    max_scanがかなり先(既定250本)まで許されているため、遠い将来の
    どこかに反対側候補が存在する時点でほぼ必ず1本目で打ち切ってしまい
    修正になっていなかった(2回目のバグ、同じ単体テストで発覚)。
    「次の同型候補」と「次の有効な反対型候補」のどちらが時間的に先かを
    比較し、反対型の方が先(または同時)のときだけ打ち切る - 同型候補が
    途切れなく続く間は常により極端な値へ更新し続ける。"""
    idx = np.searchsorted(same_events, lo_bar, side="left")
    best_bar = -1
    best_price = 0.0
    while idx < same_events.shape[0]:
        cand = same_events[idx]
        if cand > max_scan:
            break
        cand_price = high_a[cand] if is_high_type else low_a[cand]
        if best_bar == -1:
            best_bar = cand
            best_price = cand_price
        elif is_high_type:
            if cand_price > best_price:
                best_bar = cand
                best_price = cand_price
        else:
            if cand_price < best_price:
                best_bar = cand
                best_price = cand_price

        next_same = same_events[idx + 1] if idx + 1 < same_events.shape[0] else max_scan + 1

        opp_lo = best_bar + 1
        if opposite_gap_floor > opp_lo:
            opp_lo = opposite_gap_floor
        opp_idx = np.searchsorted(opposite_events, opp_lo, side="left")
        next_opp = opposite_events[opp_idx] if opp_idx < opposite_events.shape[0] else max_scan + 1

        if next_opp <= next_same:
            break
        idx += 1
    return best_bar, best_price


@njit(cache=True)
def _shape_state_core_box_v2(
    high_a, low_a, close_a, atr_a,
    both_ext_flags, both_opp_flags,
    left_ext_flags, left_opp_flags,
    bullish,
    pivot_confirm_lag,
    min_touch_gap_bars,
    level_tolerance_mult,
    breakout_buffer_mult,
    breakout_type_is_close,
    max_box_bars,
    min_valley_depth_atr_mult,
    max_valley_depth_atr_mult,
):
    """bullish=Trueで上昇ボックス(山1起点、上抜けで確定)、Falseで下降
    ボックス(谷1起点、下抜けで確定)。2026-08-15、上昇/下降を1つのコアに
    まとめた(以前は上昇のみのハードコード実装だった) - ext=起点と同じ型
    (bullishなら高値、山)、opp=もう片方の型(bullishなら安値、谷)という
    一般化。"""
    n = high_a.shape[0]
    MAXT = _ASC_BOX_MAX_TOUCHES

    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)      # Candidate
    resolve_a = np.zeros(n, dtype=np.bool_)       # Confirmed
    invalidated_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    point_count_a = np.zeros(n, dtype=np.int64)
    point_bar_a = np.full((MAXT, n), np.nan)
    point_price_a = np.full((MAXT, n), np.nan)

    ext_price_a = high_a if bullish else low_a
    opp_price_a = low_a if bullish else high_a

    both_ext_events = np.flatnonzero(both_ext_flags)
    both_opp_events = np.flatnonzero(both_opp_flags)
    left_ext_events = np.flatnonzero(left_ext_flags)
    left_opp_events = np.flatnonzero(left_opp_flags)

    for ei in range(both_ext_events.shape[0]):
        p1_bar = both_ext_events[ei]
        p1_price = ext_price_a[p1_bar]

        ext_bars = np.full(MAXT, -1)
        ext_prices = np.zeros(MAXT)
        ext_lags = np.zeros(MAXT, dtype=np.int64)
        opp_bars = np.full(MAXT, -1)
        opp_prices = np.zeros(MAXT)
        opp_lags = np.zeros(MAXT, dtype=np.int64)
        ext_bars[0] = p1_bar
        ext_prices[0] = p1_price
        ext_lags[0] = pivot_confirm_lag
        n_ext = 1
        n_opp = 0

        ext_box = p1_price
        opp_box = 0.0
        last_ext_bar = p1_bar
        last_opp_bar = -1
        min_met = False
        candidate_floor = -1

        max_scan = p1_bar + max_box_bars
        if max_scan > n - 1:
            max_scan = n - 1

        # 探索フェーズ: 0=谷1(opp)探索中, 1=山2(ext)探索中,
        # 2=谷2以降/山3以降(交互、左側のみ確認)。
        phase = 0
        outcome = 4  # 1=invalidated, 2=confirmed, 4=expired(デフォルト)
        outcome_bar = max_scan

        j_cursor = p1_bar
        failed = False

        while not failed:
            have_height = n_opp >= 1

            # --- 次の候補イベントを探す(extreme-wins+先読み方式、§3) ---
            if phase == 0:
                lo = j_cursor + 1
                gap_floor = last_ext_bar + min_touch_gap_bars
                opp_cand_bar, _ = _asc_box_find_touch(
                    both_opp_events, both_ext_events, lo, max_scan, not bullish,
                    high_a, low_a, gap_floor,
                )
                # 谷1が見つかる前でも、山1を更新する新高値(確定ピボット)が
                # 出現していないか合わせて確認する(2026-08-17、ユーザー指摘で
                # 追加 - 修正前は谷1探索中は山側を一切見ておらず、山1を
                # 大きく超える新高値が出ても無視されたままConfirmedして
                # しまう不具合があった。§5「価格が新しい高値を更新する
                # たびに再チェック」の趣旨に合わせ、山1自体をその新高値に
                # 更新して探索を続ける - 谷が見つかるまでは箱の高さ自体が
                # まだ存在しないため、既存の山を「取り消す」のではなく
                # 単純に置き換える)。
                ext_cand_bar, ext_cand_price = _asc_box_find_touch(
                    both_ext_events, both_opp_events, lo, max_scan, bullish,
                    high_a, low_a, lo,
                )
                is_new_high = ext_cand_bar != -1 and (
                    (ext_cand_price > ext_box) if bullish else (ext_cand_price < ext_box)
                )
                if is_new_high and (opp_cand_bar == -1 or ext_cand_bar < opp_cand_bar):
                    p1_bar = ext_cand_bar
                    ext_bars[0] = ext_cand_bar
                    ext_prices[0] = ext_cand_price
                    ext_lags[0] = pivot_confirm_lag
                    ext_box = ext_cand_price
                    last_ext_bar = ext_cand_bar
                    new_max_scan = p1_bar + max_box_bars
                    if new_max_scan > n - 1:
                        new_max_scan = n - 1
                    max_scan = new_max_scan
                    outcome_bar = max_scan
                    j_cursor = ext_cand_bar
                    continue
                cand_bar = opp_cand_bar
                cand_is_ext = False
            elif phase == 1:
                lo = j_cursor + 1
                start_bar = last_ext_bar + min_touch_gap_bars
                if start_bar > lo:
                    lo = start_bar
                gap_floor = last_opp_bar + min_touch_gap_bars
                cand_bar, _ = _asc_box_find_touch(
                    both_ext_events, left_opp_events, lo, max_scan, bullish,
                    high_a, low_a, gap_floor,
                )
                cand_is_ext = True
            else:
                looking_for_ext = (n_ext <= n_opp)
                lo = j_cursor + 1
                if looking_for_ext:
                    start_bar = last_ext_bar + min_touch_gap_bars
                    if start_bar > lo:
                        lo = start_bar
                    gap_floor = last_opp_bar + min_touch_gap_bars
                    cand_bar, _ = _asc_box_find_touch(
                        left_ext_events, left_opp_events, lo, max_scan, bullish,
                        high_a, low_a, gap_floor,
                    )
                    cand_is_ext = True
                else:
                    start_bar = last_opp_bar + min_touch_gap_bars
                    if start_bar > lo:
                        lo = start_bar
                    gap_floor = last_ext_bar + min_touch_gap_bars
                    cand_bar, _ = _asc_box_find_touch(
                        left_opp_events, left_ext_events, lo, max_scan, not bullish,
                        high_a, low_a, gap_floor,
                    )
                    cand_is_ext = False

            if cand_bar == -1 or cand_bar > max_scan:
                break

            # --- 逸脱/ブレイクチェック(cand_barより前の区間、生の高値・安値で) ---
            if have_height:
                tol = abs(ext_box - opp_box) * level_tolerance_mult
                buf = abs(ext_box - opp_box) * breakout_buffer_mult
                scan_end = cand_bar
                if scan_end > max_scan:
                    scan_end = max_scan
                for k in range(j_cursor + 1, scan_end + 1):
                    if bullish:
                        breakout_trigger = high_a[k] > ext_box + buf
                        invalidate_trigger = low_a[k] < opp_box - buf
                    else:
                        breakout_trigger = low_a[k] < ext_box - buf
                        invalidate_trigger = high_a[k] > opp_box + buf

                    if invalidate_trigger:
                        outcome = 1  # invalidated(逆側への逸脱)
                        outcome_bar = k
                        failed = True
                        break
                    if breakout_trigger:
                        if breakout_type_is_close:
                            end_price = close_a[k]
                            confirm_ok = (end_price > ext_box + buf) if bullish else (end_price < ext_box - buf)
                        else:
                            confirm_ok = True  # ヒゲ判定モードでは既にbreakout_triggerで確定
                        if min_met and confirm_ok:
                            outcome = 2  # confirmed
                            outcome_bar = k
                        else:
                            outcome = 1  # invalidated(ヒゲのみ逸脱、または最小構成未達)
                            outcome_bar = k
                        failed = True
                        break
                if failed:
                    break

            j_cursor = cand_bar
            cand_price = ext_price_a[cand_bar] if cand_is_ext else opp_price_a[cand_bar]
            # 両側確認(山1・谷1・山2、phase<=1)か左側のみ確認(谷2以降・
            # 山3以降、phase==2)かで先読み防止用のラグが変わる。取り消し・
            # 圧縮(keep_n)で配列内の位置がずれてもラグの値自体は各点に
            # 紐づけて一緒に運ぶ(2026-08-15訂正 - 以前は「配列の先頭2/1個は
            # 両側確認」という位置ベースの前提だったが、取り消しで並びが
            # ずれるとこの前提が崩れ、本来ラグが必要な点にラグ0を割り当てて
            # しまう先読みの不具合になりうるため)。
            cur_ext_lag = pivot_confirm_lag if phase <= 1 else 0
            cur_opp_lag = pivot_confirm_lag if phase == 0 else 0

            # --- 採用/取り消し判定(§4) ---
            if cand_is_ext:
                if n_opp == 0:
                    # opp(谷)がまだ無い(山2探索前)。水準判定できないので無条件採用。
                    if n_ext < MAXT:
                        ext_bars[n_ext] = cand_bar
                        ext_prices[n_ext] = cand_price
                        ext_lags[n_ext] = cur_ext_lag
                        n_ext += 1
                        last_ext_bar = cand_bar
                        is_more_extreme0 = (cand_price > ext_box) if bullish else (cand_price < ext_box)
                        if is_more_extreme0:
                            ext_box = cand_price
                else:
                    is_new_extreme = (cand_price > ext_box) if bullish else (cand_price < ext_box)
                    if is_new_extreme:
                        new_ext_box = cand_price
                        new_tol = abs(new_ext_box - opp_box) * level_tolerance_mult
                        keep_n = 0
                        for pi in range(n_ext):
                            keep = (ext_prices[pi] >= new_ext_box - new_tol) if bullish else (ext_prices[pi] <= new_ext_box + new_tol)
                            if keep:
                                ext_bars[keep_n] = ext_bars[pi]
                                ext_prices[keep_n] = ext_prices[pi]
                                ext_lags[keep_n] = ext_lags[pi]
                                keep_n += 1
                        if keep_n < MAXT:
                            ext_bars[keep_n] = cand_bar
                            ext_prices[keep_n] = cand_price
                            ext_lags[keep_n] = cur_ext_lag
                            keep_n += 1
                        n_ext = keep_n
                        ext_box = new_ext_box
                        last_ext_bar = cand_bar
                        if min_met and (n_ext < 2 or n_opp < 2):
                            outcome = 1
                            outcome_bar = cand_bar
                            failed = True
                            break
                    else:
                        tol = abs(ext_box - opp_box) * level_tolerance_mult
                        within = (cand_price >= ext_box - tol) if bullish else (cand_price <= ext_box + tol)
                        if within:
                            if n_ext < MAXT:
                                ext_bars[n_ext] = cand_bar
                                ext_prices[n_ext] = cand_price
                                ext_lags[n_ext] = cur_ext_lag
                                n_ext += 1
                                last_ext_bar = cand_bar
                        # 条件を満たさなければ候補は不採用(何も変わらない)、探索は続行
            else:
                # 谷の深さ(ダブルトップ/ボトムと同じ考え方 - 2026-08-16追加)。
                # 本来は「直前・直後の山2点の平均」を基準にするが、可変本数
                # のボックスでは「直後の山」がこの時点でまだ見つかっていない
                # ため、代わりに現在の山側の極値(ext_box、この時点で必ず
                # 1点以上ある)を基準にする - 「レジスタンスからどれだけ
                # 押し込んだか」という趣旨は保ったまま、以降タッチが増えて
                # ext_boxが更新されても谷の採否には遡って影響しない簡略化。
                depth = (ext_box - cand_price) if bullish else (cand_price - ext_box)
                depth_min = atr_a[cand_bar] * min_valley_depth_atr_mult
                depth_max = np.inf if max_valley_depth_atr_mult <= 0.0 else atr_a[cand_bar] * max_valley_depth_atr_mult
                depth_ok = depth_min <= depth <= depth_max

                if n_ext == 0:
                    if depth_ok and n_opp < MAXT:
                        opp_bars[n_opp] = cand_bar
                        opp_prices[n_opp] = cand_price
                        opp_lags[n_opp] = cur_opp_lag
                        n_opp += 1
                        last_opp_bar = cand_bar
                        opp_box = cand_price
                elif n_opp == 0:
                    if depth_ok:
                        opp_bars[0] = cand_bar
                        opp_prices[0] = cand_price
                        opp_lags[0] = cur_opp_lag
                        n_opp = 1
                        last_opp_bar = cand_bar
                        opp_box = cand_price
                else:
                    is_new_extreme = (cand_price < opp_box) if bullish else (cand_price > opp_box)
                    if is_new_extreme:
                        if not depth_ok:
                            continue
                        new_opp_box = cand_price
                        new_tol = abs(ext_box - new_opp_box) * level_tolerance_mult
                        keep_n = 0
                        for ti in range(n_opp):
                            keep = (opp_prices[ti] <= new_opp_box + new_tol) if bullish else (opp_prices[ti] >= new_opp_box - new_tol)
                            if keep:
                                opp_bars[keep_n] = opp_bars[ti]
                                opp_prices[keep_n] = opp_prices[ti]
                                opp_lags[keep_n] = opp_lags[ti]
                                keep_n += 1
                        if keep_n < MAXT:
                            opp_bars[keep_n] = cand_bar
                            opp_prices[keep_n] = cand_price
                            opp_lags[keep_n] = cur_opp_lag
                            keep_n += 1
                        n_opp = keep_n
                        opp_box = new_opp_box
                        last_opp_bar = cand_bar
                        if min_met and (n_ext < 2 or n_opp < 2):
                            outcome = 1
                            outcome_bar = cand_bar
                            failed = True
                            break
                    else:
                        tol = abs(ext_box - opp_box) * level_tolerance_mult
                        within = (cand_price <= opp_box + tol) if bullish else (cand_price >= opp_box - tol)
                        if within and depth_ok:
                            if n_opp < MAXT:
                                opp_bars[n_opp] = cand_bar
                                opp_prices[n_opp] = cand_price
                                opp_lags[n_opp] = cur_opp_lag
                                n_opp += 1
                                last_opp_bar = cand_bar

            if not min_met and n_ext >= 2 and n_opp >= 2:
                min_met = True
                # 最小構成(山1・谷1・山2・谷2)が揃った瞬間にCandidateを
                # 確定させる(2026-08-15、ユーザー指摘で修正 - 以前は候補が
                # 最終的に決着するまでCandidateが一切出力されなかった)。
                # この時点でn_ext==2・n_opp==2ちょうど(1回の採用/取り消しで
                # 増える点数は最大1つなので、2に「到達した瞬間」は必ず
                # ちょうど2)。
                cf = p1_bar + ext_lags[0]
                for pi2 in range(2):
                    cb2 = ext_bars[pi2] + ext_lags[pi2]
                    if cb2 > cf:
                        cf = cb2
                for ti2 in range(2):
                    cb2 = opp_bars[ti2] + opp_lags[ti2]
                    if cb2 > cf:
                        cf = cb2
                if cf < n:
                    candidate_floor = cf
                    detected_a[cf] = True
                    formed_bar_a[cf] = cf
                    # 4点を時刻順に記録。
                    tmp_bars0 = ext_bars[0]
                    tmp_bars1 = ext_bars[1]
                    tmp_pricesE0 = ext_prices[0]
                    tmp_pricesE1 = ext_prices[1]
                    tmp_barsO0 = opp_bars[0]
                    tmp_barsO1 = opp_bars[1]
                    tmp_pricesO0 = opp_prices[0]
                    tmp_pricesO1 = opp_prices[1]
                    four_bars = np.array([tmp_bars0, tmp_bars1, tmp_barsO0, tmp_barsO1])
                    four_prices = np.array([tmp_pricesE0, tmp_pricesE1, tmp_pricesO0, tmp_pricesO1])
                    order = np.argsort(four_bars)
                    for qi in range(4):
                        point_bar_a[qi, cf] = four_bars[order[qi]]
                        point_price_a[qi, cf] = four_prices[order[qi]]
                    point_count_a[cf] = 4

            # --- フェーズ遷移 ---
            if phase == 0 and n_opp >= 1:
                phase = 1
            elif phase == 1 and n_ext >= 2:
                phase = 2

        if failed and outcome != 4:
            if candidate_floor == -1:
                # 最小構成(山1・谷1・山2・谷2)が一度も揃わなかった
                # (min_met=False)場合はCandidateさえ出さない、既存の仕様通り。
                continue

            # 決着(Confirmed/Invalidated)時点の全タッチ点を使ったラグ
            # (各点に紐づけたext_lags/opp_lagsを使う - candidate_floorの
            # 計算と同じ理由、2026-08-15訂正)。
            final_floor = p1_bar + ext_lags[0]
            for pi in range(n_ext):
                cb = ext_bars[pi] + ext_lags[pi]
                if cb > final_floor:
                    final_floor = cb
            for ti in range(n_opp):
                cb = opp_bars[ti] + opp_lags[ti]
                if cb > final_floor:
                    final_floor = cb
            if final_floor >= n:
                continue

            ob = outcome_bar
            if ob < final_floor:
                ob = final_floor

            # existsはCandidateが最初に確定したcandidate_floorから決着(ob)
            # までを通しで張る(2026-08-15、ユーザー指摘で修正 - 以前は
            # 「決着時点の全タッチを使ったconfirm_floor」を開始点にして
            # おり、途中で増えたタッチの分だけCandidate自体の出現が
            # 遅れて見えていた)。
            for idx2 in range(candidate_floor, ob + 1):
                if idx2 == candidate_floor or not detected_a[idx2]:
                    exists_a[idx2] = True
                    formed_bar_a[idx2] = candidate_floor

            # 決着バー(ob)には、その時点までの全タッチ点を使った別スナップ
            # ショットを自己参照で書く(候補成立時点の4点スナップショットとは
            # 別物 - タッチが増えているかもしれないため)。
            formed_bar_a[ob] = ob
            pi = 0
            ti = 0
            pt_i = 0
            while pi < n_ext and ti < n_opp and pt_i < MAXT:
                if ext_bars[pi] <= opp_bars[ti]:
                    point_bar_a[pt_i, ob] = ext_bars[pi]
                    point_price_a[pt_i, ob] = ext_prices[pi]
                    pi += 1
                else:
                    point_bar_a[pt_i, ob] = opp_bars[ti]
                    point_price_a[pt_i, ob] = opp_prices[ti]
                    ti += 1
                pt_i += 1
            while pi < n_ext and pt_i < MAXT:
                point_bar_a[pt_i, ob] = ext_bars[pi]
                point_price_a[pt_i, ob] = ext_prices[pi]
                pi += 1
                pt_i += 1
            while ti < n_opp and pt_i < MAXT:
                point_bar_a[pt_i, ob] = opp_bars[ti]
                point_price_a[pt_i, ob] = opp_prices[ti]
                ti += 1
                pt_i += 1
            point_count_a[ob] = pt_i

            if outcome == 2:
                resolve_a[ob] = True
            else:
                invalidated_a[ob] = True

    return (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a, point_count_a, point_bar_a, point_price_a,
    )


@njit(cache=True)
def _reg_flat_alternates(reg_kept_bars, n_reg_kept, flat_bars, n_flat):
    """回帰側(reg_kept)と水平側(flat)を時刻順にマージした結果が、山谷
    交互になっているかを調べる(2026-08-19、遡及フィルタが交互性を崩す
    ケースへの対応で追加)。回帰直線の当てはめ直しや水平側の高値/安値
    更新による退避フィルタは、それぞれ自分の側の点を条件に応じて個別に
    削除する。しかし「削除して良いか」の判定はターン単位の交互性までは
    見ていないため、削除後に残った点を時刻順に並べ直すと同じ種類の点が
    連続してしまうことがある(片方の側だけ削除が起きるため)。ここで
    実際にマージした結果を直接調べることで、この種の崩れを取りこぼし
    なく検出する。"""
    ri = 0
    fi = 0
    prev_is_flat = -1
    while ri < n_reg_kept or fi < n_flat:
        if fi >= n_flat or (ri < n_reg_kept and reg_kept_bars[ri] <= flat_bars[fi]):
            cur_is_flat = 0
            ri += 1
        else:
            cur_is_flat = 1
            fi += 1
        if prev_is_flat == cur_is_flat:
            return False
        prev_is_flat = cur_is_flat
    return True


@njit(cache=True)
def _shape_state_core_triangle_v2(
    high_a, low_a, close_a, atr_a,
    both_reg_flags, both_flat_flags,
    left_reg_flags, left_flat_flags,
    bullish,
    point1_is_reg,
    pivot_confirm_lag,
    min_touch_gap_bars,
    level_tolerance_mult,
    breakout_buffer_mult,
    breakout_type_is_close,
    max_box_bars,
    pivot_spike_window_ratio,
    pivot_spike_excess_atr_max,
    min_slope_rise_atr_mult,
    max_slope_rise_atr_mult,
    max_breakout_height_ratio,
):
    """docs/pattern_spec_triangle_shape_v2.md参照。bullish=Trueで上昇三角
    保ち合い(下値=回帰側(上昇)・上値=水平側)、Falseで下降三角保ち合い
    (上値=回帰側(下降)・下値=水平側)。point1_is_reg=Trueなら回帰側の
    1点目、Falseなら水平側の1点目から探索を開始する(2方向、結果は
    ラッパー側でマージ)。水平側はボックスv2の「極値+取り消し」を
    そのまま流用(ext=水平側)。回帰側は起点(点1)だけ固定し、それ以外の
    2点は「起点+既存のいずれか1点+新しい候補」の組み合わせの中から、
    傾き・当てはまり・急さがすべて条件を満たすものを都度探して採用する
    (2026-08-18、ユーザー指示で「3点固定で1回だけ計算」をやめ、常に
    引き直せる方式に変更)。"""
    n = high_a.shape[0]
    MAXT = _ASC_BOX_MAX_TOUCHES

    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)
    resolve_a = np.zeros(n, dtype=np.bool_)
    invalidated_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    point_count_a = np.zeros(n, dtype=np.int64)
    point_bar_a = np.full((MAXT, n), np.nan)
    point_price_a = np.full((MAXT, n), np.nan)
    # 判定に実際使った回帰直線(傾き・切片)と水準線(水平)の値そのものを
    # 記録しておく(2026-08-19、ユーザー報告「下値支持線が許容誤差から
    # 外れて見える」対応)。フロント側が構成点だけから最小二乗で線を
    # 引き直すと、判定に使った直線(起点+2点だけで決まる)とは別の直線に
    # なってしまい、他の構成点が許容誤差から外れているように見えてしまう
    # ため、実際に判定へ使った直線をそのまま返す。
    reg_slope_a = np.zeros(n)
    reg_intercept_a = np.zeros(n)
    flat_level_a = np.zeros(n)

    reg_price_a = low_a if bullish else high_a
    flat_price_a = high_a if bullish else low_a
    reg_is_high = not bullish
    flat_is_high = bullish

    both_reg_events = np.flatnonzero(both_reg_flags)
    both_flat_events = np.flatnonzero(both_flat_flags)
    left_reg_events = np.flatnonzero(left_reg_flags)
    left_flat_events = np.flatnonzero(left_flat_flags)

    seed_events = both_reg_events if point1_is_reg else both_flat_events

    for ei in range(seed_events.shape[0]):
        p1_bar = seed_events[ei]

        # reg_all_*: 回帰側の候補として一度でも採用された点を時刻順に
        # すべて保持するプール(取り消しなし、引き直しの材料として使う)。
        # reg_kept_*: そのうち「現在の回帰直線」に実際に沿っている点
        # (表示・本数カウント対象、ボックスの取り消し後の集合に相当)。
        reg_all_bars = np.full(MAXT, -1)
        reg_all_prices = np.zeros(MAXT)
        reg_all_lags = np.zeros(MAXT, dtype=np.int64)
        n_reg_all = 0
        reg_kept_bars = np.full(MAXT, -1)
        reg_kept_prices = np.zeros(MAXT)
        reg_kept_lags = np.zeros(MAXT, dtype=np.int64)
        n_reg_kept = 0

        flat_bars = np.full(MAXT, -1)
        flat_prices = np.zeros(MAXT)
        flat_lags = np.zeros(MAXT, dtype=np.int64)

        if point1_is_reg:
            p1_price = reg_price_a[p1_bar]
            reg_all_bars[0] = p1_bar
            reg_all_prices[0] = p1_price
            reg_all_lags[0] = pivot_confirm_lag
            n_reg_all = 1
            n_flat = 0
            last_reg_bar = p1_bar
            last_flat_bar = -1
            flat_extreme = 0.0
        else:
            p1_price = flat_price_a[p1_bar]
            flat_bars[0] = p1_bar
            flat_prices[0] = p1_price
            flat_lags[0] = pivot_confirm_lag
            n_flat = 1
            last_flat_bar = p1_bar
            last_reg_bar = -1
            flat_extreme = p1_price

        reg_slope = 0.0
        reg_intercept = 0.0
        reg_fixed = False

        # 最小構成が揃うまでは山谷交互を強制する(2026-08-19、ユーザー指示)。
        # 点1と逆の型から始める。谷始まりなら回帰側3点・水平側2点
        # (谷1・山1・谷2・山2・谷3)、山始まりなら両方3点になる
        # (山1・谷1・山2・谷2・山3・谷3 - 回帰側が3点必要な制約と交互
        # 制約を両方満たすには水平側も自然に3点必要になる、というのが
        # ユーザーが指摘した帰結)。
        next_turn_is_reg = not point1_is_reg

        min_met = False
        candidate_floor = -1

        max_scan = p1_bar + max_box_bars
        if max_scan > n - 1:
            max_scan = n - 1

        outcome = 4  # 1=invalidated, 2=confirmed, 4=expired(デフォルト、not-this-shape兼用)
        outcome_bar = max_scan
        j_cursor = p1_bar
        failed = False

        while not failed:
            have_min = reg_fixed and (n_flat >= 2)

            lo_r = j_cursor + 1
            floor_r = last_reg_bar + min_touch_gap_bars
            if floor_r > lo_r:
                lo_r = floor_r
            opp_floor_r = last_flat_bar + min_touch_gap_bars
            search_reg_now = have_min or next_turn_is_reg
            if search_reg_now:
                if have_min:
                    reg_cand_bar, reg_cand_price = _asc_box_find_touch(
                        left_reg_events, left_flat_events, lo_r, max_scan,
                        reg_is_high, high_a, low_a, opp_floor_r,
                    )
                else:
                    reg_cand_bar, reg_cand_price = _asc_box_find_touch(
                        both_reg_events, both_flat_events, lo_r, max_scan,
                        reg_is_high, high_a, low_a, opp_floor_r,
                    )
            else:
                reg_cand_bar, reg_cand_price = -1, 0.0

            lo_f = j_cursor + 1
            floor_f = last_flat_bar + min_touch_gap_bars
            if floor_f > lo_f:
                lo_f = floor_f
            opp_floor_f = last_reg_bar + min_touch_gap_bars
            search_flat_now = have_min or not next_turn_is_reg
            if search_flat_now:
                if have_min:
                    flat_cand_bar, flat_cand_price = _asc_box_find_touch(
                        left_flat_events, left_reg_events, lo_f, max_scan,
                        flat_is_high, high_a, low_a, opp_floor_f,
                    )
                else:
                    flat_cand_bar, flat_cand_price = _asc_box_find_touch(
                        both_flat_events, both_reg_events, lo_f, max_scan,
                        flat_is_high, high_a, low_a, opp_floor_f,
                    )
            else:
                flat_cand_bar, flat_cand_price = -1, 0.0

            if reg_cand_bar == -1 and flat_cand_bar == -1:
                break

            process_reg = (reg_cand_bar != -1) and (flat_cand_bar == -1 or reg_cand_bar <= flat_cand_bar)
            cand_bar = reg_cand_bar if process_reg else flat_cand_bar
            if cand_bar > max_scan:
                break
            if not have_min:
                next_turn_is_reg = not process_reg

            # --- 逸脱/ブレイクチェック(cand_barより前の区間、生の高値・安値で) ---
            if reg_fixed and n_flat >= 1:
                scan_end = cand_bar
                if scan_end > max_scan:
                    scan_end = max_scan
                for k in range(j_cursor + 1, scan_end + 1):
                    line_k = reg_slope * k + reg_intercept
                    height_k = abs(flat_extreme - line_k)
                    buf_k = height_k * breakout_buffer_mult
                    if bullish:
                        breakout_trigger = high_a[k] > flat_extreme + buf_k
                        invalidate_trigger = low_a[k] < line_k - buf_k
                    else:
                        breakout_trigger = low_a[k] < flat_extreme - buf_k
                        invalidate_trigger = high_a[k] > line_k + buf_k

                    if invalidate_trigger:
                        outcome = 1
                        outcome_bar = k
                        failed = True
                        break
                    if breakout_trigger:
                        if breakout_type_is_close:
                            end_price = close_a[k]
                            confirm_ok = (end_price > flat_extreme + buf_k) if bullish else (end_price < flat_extreme - buf_k)
                        else:
                            confirm_ok = True
                        if confirm_ok and max_breakout_height_ratio > 0.0:
                            # 谷1(起点)から上値抵抗線までの値幅と、回帰直線の
                            # 延長のブレイクしたバー(k)に対応する価格から
                            # 上値抵抗線までの値幅(height_k、上で計算済み)を
                            # 比較し、収束具合をチェックする(2026-08-19追加 -
                            # 三角保ち合いらしく本当に狭まっているかの指標)。
                            height_start = abs(flat_extreme - reg_all_prices[0])
                            if height_start > 1e-12 and (height_k / height_start) > max_breakout_height_ratio:
                                confirm_ok = False
                        if min_met and confirm_ok:
                            outcome = 2
                        else:
                            outcome = 1
                        outcome_bar = k
                        failed = True
                        break
                if failed:
                    break

            j_cursor = cand_bar

            if process_reg:
                reg_lag = pivot_confirm_lag if not have_min else 0
                # プールが満杯(MAXTタッチ)だと今回の候補は保存されない
                # (2026-08-19、`_reg_flat_alternates`のコメント参照 - 別件で
                # 発覚したバグ対応中に発見。以前はここでプールが満杯の時、
                # 引き直し後の遡及フィルタが「保存されなかった今回の候補」
                # ではなく「プールの古い40番目の点」を誤って無条件採用して
                # いたため、実際には許容誤差から外れた点が構成点に混ざる
                # ことがあった)。
                cand_stored_in_pool = n_reg_all < MAXT
                if cand_stored_in_pool:
                    reg_all_bars[n_reg_all] = cand_bar
                    reg_all_prices[n_reg_all] = reg_cand_price
                    reg_all_lags[n_reg_all] = reg_lag
                    n_reg_all += 1
                last_reg_bar = cand_bar

                fits_current = False
                if reg_fixed and n_flat >= 1:
                    line_val = reg_slope * cand_bar + reg_intercept
                    height = abs(flat_extreme - line_val)
                    tol = height * level_tolerance_mult
                    if abs(reg_cand_price - line_val) <= tol:
                        fits_current = True

                if fits_current:
                    if n_reg_kept < MAXT:
                        reg_kept_bars[n_reg_kept] = cand_bar
                        reg_kept_prices[n_reg_kept] = reg_cand_price
                        reg_kept_lags[n_reg_kept] = reg_lag
                        n_reg_kept += 1
                else:
                    # 起点+既存の点1つ+今回の候補、という組み合わせを
                    # 古い点から順に試し、条件(傾き・3点の当てはまり・
                    # 急さ)をすべて満たす最初の組み合わせを新しい回帰直線
                    # として採用する(2026-08-18追加)。
                    refit_ok = False
                    if n_flat >= 1 and n_reg_all >= 3:
                        ab = reg_all_bars[0]
                        ap = reg_all_prices[0]
                        tmp_reg_bars = np.full(MAXT, -1)
                        tmp_reg_prices = np.zeros(MAXT)
                        tmp_reg_lags = np.zeros(MAXT, dtype=np.int64)
                        tmp_flat_bars = np.full(MAXT, -1)
                        tmp_flat_prices = np.zeros(MAXT)
                        tmp_flat_lags = np.zeros(MAXT, dtype=np.int64)
                        for xi in range(1, n_reg_all - 1):
                            xb = reg_all_bars[xi]
                            xp = reg_all_prices[xi]
                            sx = float(ab + xb + cand_bar)
                            sy = ap + xp + reg_cand_price
                            sxy = float(ab) * ap + float(xb) * xp + float(cand_bar) * reg_cand_price
                            sxx = float(ab * ab + xb * xb + cand_bar * cand_bar)
                            dn = 3.0 * sxx - sx * sx
                            if dn == 0.0:
                                continue
                            new_slope = (3.0 * sxy - sx * sy) / dn
                            new_intercept = (sy - new_slope * sx) / 3.0
                            new_slope_ok = (new_slope > 0.0) if bullish else (new_slope < 0.0)
                            if not new_slope_ok:
                                continue

                            lv_a = new_slope * ab + new_intercept
                            if abs(ap - lv_a) > abs(flat_extreme - lv_a) * level_tolerance_mult:
                                continue
                            lv_x = new_slope * xb + new_intercept
                            if abs(xp - lv_x) > abs(flat_extreme - lv_x) * level_tolerance_mult:
                                continue
                            lv_c = new_slope * cand_bar + new_intercept
                            if abs(reg_cand_price - lv_c) > abs(flat_extreme - lv_c) * level_tolerance_mult:
                                continue

                            total_rise = new_slope * (cand_bar - ab)
                            rise_min = atr_a[cand_bar] * min_slope_rise_atr_mult
                            rise_max = np.inf if max_slope_rise_atr_mult <= 0.0 else atr_a[cand_bar] * max_slope_rise_atr_mult
                            if not (rise_min <= abs(total_rise) <= rise_max):
                                continue

                            # 起点〜今回の候補までの区間を、生の高値・安値で
                            # この直線に対して遡って破綻チェックする
                            # (2026-08-19、ユーザー報告「下値抵抗線が大幅に
                            # 割れてるのに無効にならない」対応)。この区間は
                            # 直線が確定する前(=§6の順方向の逸脱チェックが
                            # まだ動いていない間)なので、直線を新しく採用する
                            # 際に一度だけ遡ってチェックしないと、確定前に
                            # 大きく割り込んだ安値/高値が見過ごされてしまう。
                            breach = False
                            for kb in range(ab, cand_bar + 1):
                                line_kb = new_slope * kb + new_intercept
                                height_kb = abs(flat_extreme - line_kb)
                                buf_kb = height_kb * breakout_buffer_mult
                                if bullish:
                                    if low_a[kb] < line_kb - buf_kb:
                                        breach = True
                                        break
                                else:
                                    if high_a[kb] > line_kb + buf_kb:
                                        breach = True
                                        break
                            if breach:
                                continue

                            # 起点(zi=0)と今回のxiは、上のlv_a/lv_x判定と
                            # 全く同じ式で既に許容誤差内と確認済みなので、
                            # ここで無条件扱いにしなくても普通の判定で必ず
                            # 残る(2026-08-19、位置(先頭/末尾)で無条件採用
                            # していたのをやめた - poolが満杯で今回の候補が
                            # 保存されていない時、末尾が「今回の候補」では
                            # なく「古いプールの最後の点」を指してしまい、
                            # 許容誤差から外れた点を無条件採用するバグに
                            # なっていた)。
                            keep_n2 = 0
                            for zi in range(n_reg_all):
                                zb = reg_all_bars[zi]
                                zp = reg_all_prices[zi]
                                lvz = new_slope * zb + new_intercept
                                keep_z = abs(zp - lvz) <= abs(flat_extreme - lvz) * level_tolerance_mult
                                if keep_z and keep_n2 < MAXT:
                                    tmp_reg_bars[keep_n2] = reg_all_bars[zi]
                                    tmp_reg_prices[keep_n2] = reg_all_prices[zi]
                                    tmp_reg_lags[keep_n2] = reg_all_lags[zi]
                                    keep_n2 += 1
                            if not cand_stored_in_pool and keep_n2 < MAXT:
                                # 今回の候補はpool満杯で保存されなかったが、
                                # このxiで採用されたcand本人はlv_c判定を既に
                                # 通っているので、明示的に加える。
                                tmp_reg_bars[keep_n2] = cand_bar
                                tmp_reg_prices[keep_n2] = reg_cand_price
                                tmp_reg_lags[keep_n2] = reg_lag
                                keep_n2 += 1

                            # 水平側の既存タッチも、新しい回帰直線の許容誤差で
                            # 遡って絞り込む(2026-08-18追加 - 回帰直線がまだ
                            # 確定していない間は高さの基準が無く無条件で採用
                            # していたため、直線が確定/引き直された時点で
                            # 一度も条件をチェックされていない点が残ってしまう
                            # ギャップがあった)。
                            fkeep_n = 0
                            for ffi in range(n_flat):
                                fzb = flat_bars[ffi]
                                fzp = flat_prices[ffi]
                                flvz = new_slope * fzb + new_intercept
                                ftol = abs(flat_extreme - flvz) * level_tolerance_mult
                                fkeep = (fzp >= flat_extreme - ftol) if bullish else (fzp <= flat_extreme + ftol)
                                if fkeep:
                                    tmp_flat_bars[fkeep_n] = flat_bars[ffi]
                                    tmp_flat_prices[fkeep_n] = flat_prices[ffi]
                                    tmp_flat_lags[fkeep_n] = flat_lags[ffi]
                                    fkeep_n += 1

                            # この組み合わせを採用すると回帰側/水平側どちらかの
                            # 遡及フィルタで点が削られる。削った結果が山谷交互で
                            # なくなる場合はこの組み合わせを採用しない(2026-08-19、
                            # ユーザー報告「交互になってない」の実例調査で発覚 -
                            # 削除はそれぞれの側だけを見て判定するため、交互性
                            # まで保証していなかった)。
                            if not _reg_flat_alternates(tmp_reg_bars, keep_n2, tmp_flat_bars, fkeep_n):
                                continue

                            reg_slope = new_slope
                            reg_intercept = new_intercept
                            reg_fixed = True
                            for zi in range(keep_n2):
                                reg_kept_bars[zi] = tmp_reg_bars[zi]
                                reg_kept_prices[zi] = tmp_reg_prices[zi]
                                reg_kept_lags[zi] = tmp_reg_lags[zi]
                            n_reg_kept = keep_n2
                            for zi in range(fkeep_n):
                                flat_bars[zi] = tmp_flat_bars[zi]
                                flat_prices[zi] = tmp_flat_prices[zi]
                                flat_lags[zi] = tmp_flat_lags[zi]
                            n_flat = fkeep_n

                            refit_ok = True
                            break

                    if refit_ok and min_met and n_flat < 2:
                        outcome = 1
                        outcome_bar = cand_bar
                        failed = True
                        break

                    if not refit_ok and reg_fixed:
                        # 既にCandidateとして成立していた形が、どの組み合わせ
                        # でも直せなかった -> 窓内破綻判定と同じ扱いで打ち切り。
                        outcome = 1
                        outcome_bar = cand_bar
                        failed = True
                        break
                    # まだ一度も回帰直線が成立していない場合は罰則なし、
                    # 探索を続ける(将来の候補でいつか成立するかもしれない)。
            else:
                flat_lag = pivot_confirm_lag if not have_min else 0
                if n_flat == 0:
                    flat_bars[0] = cand_bar
                    flat_prices[0] = flat_cand_price
                    flat_lags[0] = flat_lag
                    n_flat = 1
                    last_flat_bar = cand_bar
                    flat_extreme = flat_cand_price
                elif not reg_fixed:
                    if n_flat < MAXT:
                        flat_bars[n_flat] = cand_bar
                        flat_prices[n_flat] = flat_cand_price
                        flat_lags[n_flat] = flat_lag
                        n_flat += 1
                        last_flat_bar = cand_bar
                        is_more_extreme0 = (flat_cand_price > flat_extreme) if bullish else (flat_cand_price < flat_extreme)
                        if is_more_extreme0:
                            flat_extreme = flat_cand_price
                else:
                    line_val = reg_slope * cand_bar + reg_intercept
                    is_new_extreme = (flat_cand_price > flat_extreme) if bullish else (flat_cand_price < flat_extreme)
                    if is_new_extreme:
                        new_extreme = flat_cand_price
                        height = abs(new_extreme - line_val)
                        tol = height * level_tolerance_mult
                        tmp_flat_bars2 = np.full(MAXT, -1)
                        tmp_flat_prices2 = np.zeros(MAXT)
                        tmp_flat_lags2 = np.zeros(MAXT, dtype=np.int64)
                        keep_n = 0
                        for fi in range(n_flat):
                            keep = (flat_prices[fi] >= new_extreme - tol) if bullish else (flat_prices[fi] <= new_extreme + tol)
                            if keep:
                                tmp_flat_bars2[keep_n] = flat_bars[fi]
                                tmp_flat_prices2[keep_n] = flat_prices[fi]
                                tmp_flat_lags2[keep_n] = flat_lags[fi]
                                keep_n += 1
                        if keep_n < MAXT:
                            tmp_flat_bars2[keep_n] = cand_bar
                            tmp_flat_prices2[keep_n] = flat_cand_price
                            tmp_flat_lags2[keep_n] = flat_lag
                            keep_n += 1
                        # 高値/安値の更新で古いタッチが退避された結果、回帰側と
                        # マージした時に山谷交互でなくなる場合も打ち切る
                        # (2026-08-19、_reg_flat_alternatesの説明コメント参照)。
                        # 交互性が崩れる場合は退避を確定させない(直前までの
                        # 山谷交互な状態のままにする)- 打ち切り後に表示される
                        # 最終スナップショットも壊れた状態になってしまうため。
                        alt_broken = not _reg_flat_alternates(reg_kept_bars, n_reg_kept, tmp_flat_bars2, keep_n)
                        if (min_met and ((not reg_fixed) or n_reg_kept < 3 or keep_n < 2)) or alt_broken:
                            outcome = 1
                            outcome_bar = cand_bar
                            failed = True
                            break
                        for zi in range(keep_n):
                            flat_bars[zi] = tmp_flat_bars2[zi]
                            flat_prices[zi] = tmp_flat_prices2[zi]
                            flat_lags[zi] = tmp_flat_lags2[zi]
                        n_flat = keep_n
                        flat_extreme = new_extreme
                        last_flat_bar = cand_bar
                    else:
                        height = abs(flat_extreme - line_val)
                        tol = height * level_tolerance_mult
                        within = (flat_cand_price >= flat_extreme - tol) if bullish else (flat_cand_price <= flat_extreme + tol)
                        if within:
                            if n_flat < MAXT:
                                flat_bars[n_flat] = cand_bar
                                flat_prices[n_flat] = flat_cand_price
                                flat_lags[n_flat] = flat_lag
                                n_flat += 1
                                last_flat_bar = cand_bar

            if not min_met and reg_fixed and n_flat >= 2:
                cf = p1_bar + (reg_all_lags[0] if point1_is_reg else flat_lags[0])
                for pi2 in range(n_reg_kept):
                    cb2 = reg_kept_bars[pi2] + reg_kept_lags[pi2]
                    if cb2 > cf:
                        cf = cb2
                for ti2 in range(n_flat):
                    cb2 = flat_bars[ti2] + flat_lags[ti2]
                    if cb2 > cf:
                        cf = cb2
                if cf < n:
                    # 回帰側(可変本数、reg_kept)+水平側(n_flat)を時刻順に
                    # マージ(2026-08-18、3点固定をやめたため点数は最小
                    # 5点とは限らない)。決着時点の最終スナップショットと
                    # 同じマージ方式。
                    pc_cand = n_reg_kept + n_flat
                    if pc_cand > MAXT:
                        pc_cand = MAXT
                    ok_bars = np.zeros(pc_cand, dtype=np.int64)
                    ok_prices = np.zeros(pc_cand)
                    ok_is_flat = np.zeros(pc_cand, dtype=np.bool_)
                    ri = 0
                    fi2 = 0
                    pt_c = 0
                    while ri < n_reg_kept and fi2 < n_flat and pt_c < pc_cand:
                        if reg_kept_bars[ri] <= flat_bars[fi2]:
                            ok_bars[pt_c] = reg_kept_bars[ri]
                            ok_prices[pt_c] = reg_kept_prices[ri]
                            ok_is_flat[pt_c] = False
                            ri += 1
                        else:
                            ok_bars[pt_c] = flat_bars[fi2]
                            ok_prices[pt_c] = flat_prices[fi2]
                            ok_is_flat[pt_c] = True
                            fi2 += 1
                        pt_c += 1
                    while ri < n_reg_kept and pt_c < pc_cand:
                        ok_bars[pt_c] = reg_kept_bars[ri]
                        ok_prices[pt_c] = reg_kept_prices[ri]
                        ok_is_flat[pt_c] = False
                        ri += 1
                        pt_c += 1
                    while fi2 < n_flat and pt_c < pc_cand:
                        ok_bars[pt_c] = flat_bars[fi2]
                        ok_prices[pt_c] = flat_prices[fi2]
                        ok_is_flat[pt_c] = True
                        fi2 += 1
                        pt_c += 1

                    # 孤立度チェック(2026-08-18、ユーザー指摘で例外的に残す -
                    # ボックスv2は丸ごと削除したが三角保ち合いv2はここだけ
                    # 旧実装を踏襲する)。構成点を時刻順に並べ、それぞれ
                    # 隣接する点との区間(区間本数×pivot_spike_window_ratio)
                    # を窓にして突出をチェックする(旧トリプル実装の
                    # 「隣接区間」概念を、可変な点の並びに合わせて一般化
                    # した簡略版)。
                    spike_ok = True
                    for qi in range(pc_cand):
                        bar_q = ok_bars[qi]
                        is_high_q = flat_is_high if ok_is_flat[qi] else reg_is_high
                        price_arr_q = flat_price_a if ok_is_flat[qi] else reg_price_a
                        if qi > 0:
                            interval_l = bar_q - ok_bars[qi - 1]
                            win_l = int(round(interval_l * pivot_spike_window_ratio))
                            if not _shape_spike_ok(price_arr_q, atr_a, n, bar_q, win_l, False, is_high_q, pivot_spike_excess_atr_max):
                                spike_ok = False
                                break
                        if qi < pc_cand - 1:
                            interval_r = ok_bars[qi + 1] - bar_q
                            win_r = int(round(interval_r * pivot_spike_window_ratio))
                            if not _shape_spike_ok(price_arr_q, atr_a, n, bar_q, win_r, True, is_high_q, pivot_spike_excess_atr_max):
                                spike_ok = False
                                break

                    if not spike_ok:
                        failed = True
                        break

                    min_met = True
                    candidate_floor = cf
                    detected_a[cf] = True
                    formed_bar_a[cf] = cf
                    for qi in range(pc_cand):
                        point_bar_a[qi, cf] = ok_bars[qi]
                        point_price_a[qi, cf] = ok_prices[qi]
                    point_count_a[cf] = pc_cand
                    reg_slope_a[cf] = reg_slope
                    reg_intercept_a[cf] = reg_intercept
                    flat_level_a[cf] = flat_extreme

        if failed and outcome != 4:
            if candidate_floor == -1:
                continue

            final_floor = p1_bar + (reg_all_lags[0] if point1_is_reg else flat_lags[0])
            for pi in range(n_reg_kept):
                cb = reg_kept_bars[pi] + reg_kept_lags[pi]
                if cb > final_floor:
                    final_floor = cb
            for ti in range(n_flat):
                cb = flat_bars[ti] + flat_lags[ti]
                if cb > final_floor:
                    final_floor = cb
            if final_floor >= n:
                continue

            ob = outcome_bar
            if ob < final_floor:
                ob = final_floor

            for idx2 in range(candidate_floor, ob + 1):
                if idx2 == candidate_floor or not detected_a[idx2]:
                    exists_a[idx2] = True
                    formed_bar_a[idx2] = candidate_floor

            formed_bar_a[ob] = ob
            pi = 0
            ti = 0
            pt_i = 0
            while pi < n_reg_kept and ti < n_flat and pt_i < MAXT:
                if reg_kept_bars[pi] <= flat_bars[ti]:
                    point_bar_a[pt_i, ob] = reg_kept_bars[pi]
                    point_price_a[pt_i, ob] = reg_kept_prices[pi]
                    pi += 1
                else:
                    point_bar_a[pt_i, ob] = flat_bars[ti]
                    point_price_a[pt_i, ob] = flat_prices[ti]
                    ti += 1
                pt_i += 1
            while pi < n_reg_kept and pt_i < MAXT:
                point_bar_a[pt_i, ob] = reg_kept_bars[pi]
                point_price_a[pt_i, ob] = reg_kept_prices[pi]
                pi += 1
                pt_i += 1
            while ti < n_flat and pt_i < MAXT:
                point_bar_a[pt_i, ob] = flat_bars[ti]
                point_price_a[pt_i, ob] = flat_prices[ti]
                ti += 1
                pt_i += 1
            point_count_a[ob] = pt_i
            reg_slope_a[ob] = reg_slope
            reg_intercept_a[ob] = reg_intercept
            flat_level_a[ob] = flat_extreme

            if outcome == 2:
                resolve_a[ob] = True
            else:
                invalidated_a[ob] = True

    return (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a, point_count_a, point_bar_a, point_price_a,
        reg_slope_a, reg_intercept_a, flat_level_a,
    )


def _merge_shape_dual_seed(res_a: tuple, res_b: tuple) -> tuple:
    """点1の探索方向が2通り(回帰側起点/水平側起点)ある家系向けに、2回の
    コア呼び出しの結果を1つにマージする。バーごとに「aがexistsならa、
    そうでなければb」で選ぶ(トリプル/ボックスの複数の点1候補が重なる
    ケースと同じ「衝突は許容する」方針 - a側のformed_bar参照先
    (candidate_floor/決着バー)は必ずa側のexistsにも含まれるため、この
    バー単位の選択だけで参照の整合性は保たれる)。"""
    (exists_a, detected_a, invalidated_a, resolve_a,
     formed_bar_a, point_count_a, point_bar_a, point_price_a,
     reg_slope_a, reg_intercept_a, flat_level_a) = res_a
    (exists_b, detected_b, invalidated_b, resolve_b,
     formed_bar_b, point_count_b, point_bar_b, point_price_b,
     reg_slope_b, reg_intercept_b, flat_level_b) = res_b

    use_a = exists_a
    exists = np.where(use_a, exists_a, exists_b)
    detected = np.where(use_a, detected_a, detected_b)
    invalidated = np.where(use_a, invalidated_a, invalidated_b)
    resolve = np.where(use_a, resolve_a, resolve_b)
    formed_bar = np.where(use_a, formed_bar_a, formed_bar_b)
    point_count = np.where(use_a, point_count_a, point_count_b)
    point_bar = np.where(use_a[np.newaxis, :], point_bar_a, point_bar_b)
    point_price = np.where(use_a[np.newaxis, :], point_price_a, point_price_b)
    reg_slope = np.where(use_a, reg_slope_a, reg_slope_b)
    reg_intercept = np.where(use_a, reg_intercept_a, reg_intercept_b)
    flat_level = np.where(use_a, flat_level_a, flat_level_b)
    return (
        exists, detected, invalidated, resolve, formed_bar, point_count, point_bar, point_price,
        reg_slope, reg_intercept, flat_level,
    )


def _triangle_shape_state_v2(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    pivot_spike_window_ratio: float = 0.0,
    pivot_spike_excess_atr_max: float = 0.0,
    min_slope_rise_atr_mult: float = 1.0,
    max_slope_rise_atr_mult: float = 0.0,
    max_breakout_height_ratio: float = 0.0,
) -> dict[str, Any]:
    """docs/pattern_spec_triangle_shape_v2.md参照。bullish=Trueで上昇三角
    保ち合い(下値=回帰側(上昇)・上値=水平側)、Falseで下降三角保ち合い
    (上値=回帰側(下降)・下値=水平側)。点1は回帰側・水平側どちらからでも
    探索し(2026-08-18追加)、結果を`_merge_shape_dual_seed`でマージする。
    min/max_slope_rise_atr_multは回帰直線の急さの下限/上限(起点から
    終点までの直線上の値幅をATR倍率で正規化、2026-08-18追加 - 傾きが
    プラスでありさえすれば通ってしまう緩すぎる回帰直線を弾く)。
    max_breakout_height_ratioは谷1(起点)から上値抵抗線までの値幅に対する、
    ブレイクしたバーでの回帰直線の延長〜上値抵抗線までの値幅の比率の上限
    (2026-08-19追加、0以下で無効 - 三角保ち合いらしく実際に収束している
    かのチェック)。"""
    idx_index = high.index
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_a = _atr_series(df, 14).to_numpy()

    if breakout_type not in ("close", "wick"):
        raise ValueError(f"未対応のbreakout_typeです(close/wickのみ対応): {breakout_type}")

    pivot_left_bars = max(0, pivot_left_bars)
    pivot_right_bars = max(0, pivot_right_bars)
    if pivot_left_bars == 0 and pivot_right_bars == 0:
        pivot_left_bars = 1

    both_high_flags = _pivot_flags(high, pivot_left_bars, pivot_right_bars, True).to_numpy()
    both_low_flags = _pivot_flags(low, pivot_left_bars, pivot_right_bars, False).to_numpy()
    left_high_flags = _detect_pivot_highs_left_only(high, pivot_left_bars).to_numpy()
    left_low_flags = _detect_pivot_lows_left_only(low, pivot_left_bars).to_numpy()

    both_reg_flags = both_low_flags if bullish else both_high_flags
    both_flat_flags = both_high_flags if bullish else both_low_flags
    left_reg_flags = left_low_flags if bullish else left_high_flags
    left_flat_flags = left_high_flags if bullish else left_low_flags

    res_reg_seed = _shape_state_core_triangle_v2(
        high_a, low_a, close_a, atr_a,
        both_reg_flags, both_flat_flags, left_reg_flags, left_flat_flags,
        bool(bullish), True,
        int(pivot_right_bars), int(min_touch_gap_bars),
        float(level_tolerance_mult), float(breakout_buffer_mult),
        breakout_type == "close", int(max_box_bars),
        float(pivot_spike_window_ratio), float(pivot_spike_excess_atr_max),
        float(min_slope_rise_atr_mult), float(max_slope_rise_atr_mult),
        float(max_breakout_height_ratio),
    )
    res_flat_seed = _shape_state_core_triangle_v2(
        high_a, low_a, close_a, atr_a,
        both_reg_flags, both_flat_flags, left_reg_flags, left_flat_flags,
        bool(bullish), False,
        int(pivot_right_bars), int(min_touch_gap_bars),
        float(level_tolerance_mult), float(breakout_buffer_mult),
        breakout_type == "close", int(max_box_bars),
        float(pivot_spike_window_ratio), float(pivot_spike_excess_atr_max),
        float(min_slope_rise_atr_mult), float(max_slope_rise_atr_mult),
        float(max_breakout_height_ratio),
    )

    (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a, point_count_a, point_bar_a, point_price_a,
        reg_slope_a, reg_intercept_a, flat_level_a,
    ) = _merge_shape_dual_seed(res_reg_seed, res_flat_seed)

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "candidate": pd.Series(detected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "invalidated": pd.Series(invalidated_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "point_count": point_count_a,
        "point_bar": point_bar_a,
        "point_price": point_price_a,
        "reg_slope": reg_slope_a,
        "reg_intercept": reg_intercept_a,
        "flat_level": flat_level_a,
    }


def _box_shape_state_v2(
    high: pd.Series, low: pd.Series, close: pd.Series,
    bullish: bool,
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
) -> dict[str, Any]:
    """docs/pattern_spec_ascending_box_shape_v2.md 参照。bullish=Trueで
    上昇ボックス(山1起点、上抜けで確定)、Falseで下降ボックス(谷1起点、
    下抜けで確定) - 上下反転した鏡像。

    min/max_valley_depth_atr_mult(2026-08-16追加)はダブルトップ/ボトムと
    同じ「谷の深さ」フィルター - 谷(opp)の水準が、山側の極値(ext_box)から
    ATR倍率でどれだけ離れているかを判定する。ダブル/トリプルは直前・直後の
    山2点の平均を基準にするが、この可変タッチ方式は谷の採否を判定する
    時点でまだ「直後の山」が見つかっていないため、代わりにその時点の
    ext_box(山側の現在の極値)を基準にする簡略化(docs参照)。"""
    idx_index = high.index
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_a = _atr_series(df, 14).to_numpy()

    if breakout_type not in ("close", "wick"):
        raise ValueError(f"未対応のbreakout_typeです(close/wickのみ対応): {breakout_type}")

    pivot_left_bars = max(0, pivot_left_bars)
    pivot_right_bars = max(0, pivot_right_bars)
    if pivot_left_bars == 0 and pivot_right_bars == 0:
        pivot_left_bars = 1

    both_high_flags = _pivot_flags(high, pivot_left_bars, pivot_right_bars, True).to_numpy()
    both_low_flags = _pivot_flags(low, pivot_left_bars, pivot_right_bars, False).to_numpy()
    left_high_flags = _detect_pivot_highs_left_only(high, pivot_left_bars).to_numpy()
    left_low_flags = _detect_pivot_lows_left_only(low, pivot_left_bars).to_numpy()

    both_ext_flags = both_high_flags if bullish else both_low_flags
    both_opp_flags = both_low_flags if bullish else both_high_flags
    left_ext_flags = left_high_flags if bullish else left_low_flags
    left_opp_flags = left_low_flags if bullish else left_high_flags

    (
        exists_a, detected_a, invalidated_a, resolve_a,
        formed_bar_a, point_count_a, point_bar_a, point_price_a,
    ) = _shape_state_core_box_v2(
        high_a, low_a, close_a, atr_a,
        both_ext_flags, both_opp_flags, left_ext_flags, left_opp_flags,
        bool(bullish),
        int(pivot_right_bars),
        int(min_touch_gap_bars),
        float(level_tolerance_mult),
        float(breakout_buffer_mult),
        breakout_type == "close",
        int(max_box_bars),
        float(min_valley_depth_atr_mult),
        float(max_valley_depth_atr_mult),
    )

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "candidate": pd.Series(detected_a, index=idx_index),
        "confirmed": pd.Series(resolve_a, index=idx_index),
        "invalidated": pd.Series(invalidated_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "point_count": point_count_a,
        "point_bar": point_bar_a,
        "point_price": point_price_a,
    }


def ascending_box_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
) -> np.ndarray:
    """上昇ボックス(可変タッチ方式v2) - docs/pattern_spec_ascending_box_shape_v2.md。
    高値側(山1)を起点に探索する - 安値起点だと下抜けに偏る実データ上の
    傾向が確認されたため(2026-08-14、旧仕様書§3.4参照、この傾向自体は
    v2でも変わらない)。"""
    result = _box_shape_state_v2(
        high, low, close, True,
        pivot_left_bars=pivot_left_bars, pivot_right_bars=pivot_right_bars,
        min_touch_gap_bars=min_touch_gap_bars, level_tolerance_mult=level_tolerance_mult,
        breakout_buffer_mult=breakout_buffer_mult, breakout_type=breakout_type,
        max_box_bars=max_box_bars,
        min_valley_depth_atr_mult=min_valley_depth_atr_mult,
        max_valley_depth_atr_mult=max_valley_depth_atr_mult,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def descending_box_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    min_valley_depth_atr_mult: float = 1.0,
    max_valley_depth_atr_mult: float = 0.0,
) -> np.ndarray:
    """下降ボックス(可変タッチ方式v2) - 上昇ボックスの上下反転した鏡像
    (谷1起点、下抜けで確定)。2026-08-15、上昇ボックスと同時に全面書き換え。"""
    result = _box_shape_state_v2(
        high, low, close, False,
        pivot_left_bars=pivot_left_bars, pivot_right_bars=pivot_right_bars,
        min_touch_gap_bars=min_touch_gap_bars, level_tolerance_mult=level_tolerance_mult,
        breakout_buffer_mult=breakout_buffer_mult, breakout_type=breakout_type,
        max_box_bars=max_box_bars,
        min_valley_depth_atr_mult=min_valley_depth_atr_mult,
        max_valley_depth_atr_mult=max_valley_depth_atr_mult,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def ascending_box_shape_legacy(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    **kwargs: Any,
) -> np.ndarray:
    """上昇ボックス(旧版、レクタングル、4点固定・共通チャネルコア方式)。
    両方の線が水平。2026-08-15にascending_box_shape本体は可変タッチ方式
    (v2)へ全面置き換えしたが、比較用にこの名前で旧実装を残す
    (docs/pattern_spec_channel_patterns_shape.md参照)。"""
    return _channel_indicator(
        high, low, close, False, True, "flat", "flat", False, False,
        state, top_tolerance_mult, converge_margin, width_tol, **kwargs,
    )


def descending_box_shape_legacy(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    **kwargs: Any,
) -> np.ndarray:
    """下降ボックス(旧版、レクタングル、4点固定・共通チャネルコア方式)。
    両方の線が水平。2026-08-15にdescending_box_shape本体は可変タッチ方式
    (v2)へ全面置き換えしたが、比較用にこの名前で旧実装を残す
    (docs/pattern_spec_channel_patterns_shape.md参照)。"""
    return _channel_indicator(
        high, low, close, True, False, "flat", "flat", False, False,
        state, top_tolerance_mult, converge_margin, width_tol, **kwargs,
    )


def ascending_triangle_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    pivot_spike_window_ratio: float = 0.0,
    pivot_spike_excess_atr_max: float = 0.0,
    min_slope_rise_atr_mult: float = 1.0,
    max_slope_rise_atr_mult: float = 0.0,
    max_breakout_height_ratio: float = 0.0,
) -> np.ndarray:
    """上昇三角保ち合い(可変タッチ・回帰直線方式v2) -
    docs/pattern_spec_triangle_shape_v2.md。下値=回帰側(上昇、最小二乗
    回帰直線、起点+条件を満たす2点で常に引き直し可能)、上値=水平側
    (極値+取り消し、ボックスv2と同じ)。点1は回帰側・水平側どちらからでも
    探索し、結果をマージする。"""
    result = _triangle_shape_state_v2(
        high, low, close, True,
        pivot_left_bars=pivot_left_bars, pivot_right_bars=pivot_right_bars,
        min_touch_gap_bars=min_touch_gap_bars, level_tolerance_mult=level_tolerance_mult,
        breakout_buffer_mult=breakout_buffer_mult, breakout_type=breakout_type,
        max_box_bars=max_box_bars,
        pivot_spike_window_ratio=pivot_spike_window_ratio,
        pivot_spike_excess_atr_max=pivot_spike_excess_atr_max,
        min_slope_rise_atr_mult=min_slope_rise_atr_mult,
        max_slope_rise_atr_mult=max_slope_rise_atr_mult,
        max_breakout_height_ratio=max_breakout_height_ratio,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def descending_triangle_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    pivot_spike_window_ratio: float = 0.0,
    pivot_spike_excess_atr_max: float = 0.0,
    min_slope_rise_atr_mult: float = 1.0,
    max_slope_rise_atr_mult: float = 0.0,
    max_breakout_height_ratio: float = 0.0,
) -> np.ndarray:
    """下降三角保ち合い(可変タッチ・回帰直線方式v2) - 上昇三角保ち合いの
    上下反転した鏡像(上値=回帰側(下降)、下値=水平側)。"""
    result = _triangle_shape_state_v2(
        high, low, close, False,
        pivot_left_bars=pivot_left_bars, pivot_right_bars=pivot_right_bars,
        min_touch_gap_bars=min_touch_gap_bars, level_tolerance_mult=level_tolerance_mult,
        breakout_buffer_mult=breakout_buffer_mult, breakout_type=breakout_type,
        max_box_bars=max_box_bars,
        pivot_spike_window_ratio=pivot_spike_window_ratio,
        pivot_spike_excess_atr_max=pivot_spike_excess_atr_max,
        min_slope_rise_atr_mult=min_slope_rise_atr_mult,
        max_slope_rise_atr_mult=max_slope_rise_atr_mult,
        max_breakout_height_ratio=max_breakout_height_ratio,
    )
    key = _SHAPE_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def ascending_triangle_shape_legacy(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    **kwargs: Any,
) -> np.ndarray:
    """上昇三角保ち合い(旧版、下側の線が上昇、上側の線が水平、4点固定・
    共通チャネルコア方式)。2026-08-18にascending_triangle_shape本体は
    可変タッチ・回帰直線方式(v2)へ全面置き換えしたが、比較用にこの名前で
    旧実装を残す(docs/pattern_spec_channel_patterns_shape.md参照)。"""
    return _channel_indicator(
        high, low, close, False, True, "rising", "flat", False, False,
        state, top_tolerance_mult, converge_margin, width_tol, **kwargs,
    )


def descending_triangle_shape_legacy(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    **kwargs: Any,
) -> np.ndarray:
    """下降三角保ち合い(旧版、上側の線が下降、下側の線が水平、4点固定・
    共通チャネルコア方式)。比較用にこの名前で旧実装を残す。"""
    return _channel_indicator(
        high, low, close, True, False, "flat", "falling", False, False,
        state, top_tolerance_mult, converge_margin, width_tol, **kwargs,
    )


# ---------------------------------------------------------------------------
# 上昇ウェッジ v2(可変タッチ・両側回帰直線方式) -
# docs/pattern_spec_wedge_shape_v2.md
#
# 2026-08-19、ユーザー指示で旧実装(_channel_indicator方式、4点固定)を
# 廃止し、ascending_triangle_shape v2をベースに全面書き換え。三角保ち合い
# との違いは上値抵抗線の決め方だけ - 三角保ち合いでは水平(極値+取り消し)
# だったところを、下値支持線と全く同じ「起点だけ固定、他の2点は常に
# 引き直し可能な回帰直線」方式にする(ユーザー指示「上値抵抗線の決め方は
# 上昇三角持ち合いの下値支持線と同じにして」)。両方が回帰直線になるため、
# 「高さ」(許容誤差・ブレイク余白の基準)は水平側の定数(flat_extreme)では
# なく、上値直線と下値直線の値の差(その時点の直線同士の間隔)になる。
#
# もう1つの違いは状態管理(ユーザー指示「Confirmedを2種類にして。上値抵抗線
# をブレイクと下値支持線をブレイク」)。三角保ち合いは片方向のブレイクだけ
# がConfirmedで逆方向はInvalidatedだったが、ウェッジは両方向とも正当な
# 結果として扱い、どちらの線を割ったかで種類を分ける。Invalidatedは
# 「最小構成(下値3点+上値3点)が揃う前に破綻した」場合だけに残す。
# ---------------------------------------------------------------------------


@njit(cache=True)
def _wedge_line_value(n_pts, slope, intercept, first_price, bar):
    """点数(n_pts)に応じて、そのバーでの「現在の直線の値」を返す
    (2026-08-19、ユーザー指示で再設計)。0点は未定義(0.0、実際には
    呼ばれない想定)、1点は唯一の生の価格をそのまま使う、2点以上は
    直線(2点ならその2点を結ぶ直線、3点以上なら固定済みの回帰直線)の
    値を使う。"""
    if n_pts >= 2:
        return slope * bar + intercept
    elif n_pts == 1:
        return first_price
    else:
        return 0.0


@njit(cache=True)
def _wedge_pool_refit_side(
    all_bars, all_prices, all_lags, n_all,
    opp_n, opp_slope, opp_intercept, opp_first_price, opp_kept_bars,
    is_lo_side, check_alternation,
    atr_a, high_a, low_a,
    breakout_buffer_mult, min_slope_rise_atr_mult, max_slope_rise_atr_mult,
    level_tolerance_mult,
    out_kept_bars, out_kept_prices, out_kept_lags, MAXT,
):
    """三角保ち合いv2の回帰側と同じ「起点固定+複数組み合わせ探索」を
    上昇ウェッジの片側(下値支持線 or 上値抵抗線)に適用する(2026-08-19、
    ユーザー指示で「3点目で1回だけ固定、以降は引き直さない」段階固定
    方式から、常に引き直し可能な複数組み合わせ探索に変更 - 起点(このプール
    のindex0)は固定したまま、既存プールの中間点+最新候補の組み合わせを
    古い方から順に試す)。呼び出し側でlo/up双方から呼ばれ、is_lo_sideで
    ブレイク方向・交差/収束不等号の向きを切り替える。

    傾き・許容誤差・急さ・遡及破綻に加えて、この時点の相手側の直線
    (opp_slope/opp_intercept、まだ確定していなければ1点の生値/未定義)
    に対する交差チェックと収束チェック(下値の方が急)も、組み合わせを
    試すたびに毎回やり直す(段階固定方式で交差/非収束を防いでいた§6・
    §6.1と同じ内容を、引き直しのたびに検証し直すことで代替する - ユーザー
    確認済み、2026-08-19)。

    check_alternation=True(最小構成が揃う前、`have_min`がまだFalseの間)
    のときは、この側の直線を新しいプール全体で絞り込み直したkept集合と、
    相手側の現在のkept集合を時刻順にマージした結果が山谷交互になって
    いるかも`_reg_flat_alternates`で確認する(三角保ち合いv2の回帰側の
    引き直しと同じ考え方)。フィット自体には通っても、プール全体での
    絞り込みが途中の点だけを脱落させると、表示上は交互に見えなくなる
    ことがある(2026-08-19発見・ユーザー報告「4点目と5点目どちらも安値」
    の残存原因 - 番を消費しない対応[turn_consumed]だけでは防げなかった)。
    最小構成成立後(`have_min`成立後)は交互性を要求しない仕様(§4)なので
    check_alternation=Falseで呼び、この判定はスキップする。"""
    anchor_bar = all_bars[0]
    anchor_price = all_prices[0]
    cand_bar = all_bars[n_all - 1]
    cand_price = all_prices[n_all - 1]

    for xi in range(1, n_all - 1):
        xb = all_bars[xi]
        xp = all_prices[xi]
        sx = float(anchor_bar + xb + cand_bar)
        sy = anchor_price + xp + cand_price
        sxy = float(anchor_bar) * anchor_price + float(xb) * xp + float(cand_bar) * cand_price
        sxx = float(anchor_bar * anchor_bar + xb * xb + cand_bar * cand_bar)
        dn = 3.0 * sxx - sx * sx
        if dn == 0.0:
            continue
        new_slope = (3.0 * sxy - sx * sy) / dn
        new_intercept = (sy - new_slope * sx) / 3.0
        if new_slope <= 0.0:
            continue

        opp_va = _wedge_line_value(opp_n, opp_slope, opp_intercept, opp_first_price, anchor_bar)
        lv_a = new_slope * anchor_bar + new_intercept
        if abs(anchor_price - lv_a) > abs(opp_va - lv_a) * level_tolerance_mult:
            continue
        opp_vx = _wedge_line_value(opp_n, opp_slope, opp_intercept, opp_first_price, xb)
        lv_x = new_slope * xb + new_intercept
        if abs(xp - lv_x) > abs(opp_vx - lv_x) * level_tolerance_mult:
            continue
        opp_vc = _wedge_line_value(opp_n, opp_slope, opp_intercept, opp_first_price, cand_bar)
        lv_c = new_slope * cand_bar + new_intercept
        if abs(cand_price - lv_c) > abs(opp_vc - lv_c) * level_tolerance_mult:
            continue

        total_rise = new_slope * (cand_bar - anchor_bar)
        rise_min = atr_a[cand_bar] * min_slope_rise_atr_mult
        rise_max = np.inf if max_slope_rise_atr_mult <= 0.0 else atr_a[cand_bar] * max_slope_rise_atr_mult
        if not (rise_min <= abs(total_rise) <= rise_max):
            continue

        breach = False
        for kb in range(anchor_bar, cand_bar + 1):
            line_kb = new_slope * kb + new_intercept
            opp_kb = _wedge_line_value(opp_n, opp_slope, opp_intercept, opp_first_price, kb)
            buf_kb = abs(opp_kb - line_kb) * breakout_buffer_mult
            if is_lo_side:
                if low_a[kb] < line_kb - buf_kb:
                    breach = True
                    break
            else:
                if high_a[kb] > line_kb + buf_kb:
                    breach = True
                    break
        if breach:
            continue

        keep_n = 0
        for zi in range(n_all):
            zb = all_bars[zi]
            zp = all_prices[zi]
            lvz = new_slope * zb + new_intercept
            opp_vz = _wedge_line_value(opp_n, opp_slope, opp_intercept, opp_first_price, zb)
            heightz = abs(opp_vz - lvz)
            if abs(zp - lvz) <= heightz * level_tolerance_mult:
                if keep_n < MAXT:
                    out_kept_bars[keep_n] = all_bars[zi]
                    out_kept_prices[keep_n] = all_prices[zi]
                    out_kept_lags[keep_n] = all_lags[zi]
                    keep_n += 1
        if keep_n == 0:
            continue

        crossing_ok = True
        for zi in range(keep_n):
            zb = out_kept_bars[zi]
            lv = new_slope * zb + new_intercept
            ov = _wedge_line_value(opp_n, opp_slope, opp_intercept, opp_first_price, zb)
            if is_lo_side:
                if lv >= ov:
                    crossing_ok = False
                    break
            else:
                if lv <= ov:
                    crossing_ok = False
                    break
        if crossing_ok:
            for zi in range(opp_n):
                zb = opp_kept_bars[zi]
                lv = new_slope * zb + new_intercept
                ov = _wedge_line_value(opp_n, opp_slope, opp_intercept, opp_first_price, zb)
                if is_lo_side:
                    if lv >= ov:
                        crossing_ok = False
                        break
                else:
                    if lv <= ov:
                        crossing_ok = False
                        break
        if not crossing_ok:
            continue

        if opp_n >= 2:
            if is_lo_side:
                if not (new_slope > opp_slope):
                    continue
            else:
                if not (opp_slope > new_slope):
                    continue

        if check_alternation:
            if is_lo_side:
                alt_ok = _reg_flat_alternates(out_kept_bars, keep_n, opp_kept_bars, opp_n)
            else:
                alt_ok = _reg_flat_alternates(opp_kept_bars, opp_n, out_kept_bars, keep_n)
            if not alt_ok:
                continue

        return True, new_slope, new_intercept, keep_n

    return False, 0.0, 0.0, 0


@njit(cache=True)
def _shape_state_core_wedge_v2(
    high_a, low_a, close_a, atr_a,
    both_lo_flags, both_up_flags,
    left_lo_flags, left_up_flags,
    point1_is_lo,
    pivot_confirm_lag,
    min_touch_gap_bars,
    level_tolerance_mult,
    breakout_buffer_mult,
    breakout_type_is_close,
    max_box_bars,
    pivot_spike_window_ratio,
    pivot_spike_excess_atr_max,
    min_slope_rise_atr_mult,
    max_slope_rise_atr_mult,
    max_breakout_height_ratio,
):
    """docs/pattern_spec_wedge_shape_v2.md参照(2026-08-19、ユーザー指示で
    複数組み合わせ探索方式に再設計)。下値支持線・上値抵抗線とも、最初の
    2点はそのまま結ぶ直線から始め、3点目以降は三角保ち合いv2の回帰側と
    同じ「起点(このプールの最初の点)は固定したまま、既存プールの中間点+
    最新候補の組み合わせを古い方から順に試し、条件をすべて満たす最初の
    組み合わせを採用する」方式で常に引き直し可能にする(段階固定方式
    [1回だけ固定して以降は引き直さない]から変更 - ユーザー指示「3点目で
    1回だけ固定、以降は引き直さないの意図は同一の2点を使う回帰直線は
    複数引かない、同一の1点(起点)を使う回帰直線は複数見つけて一つの
    パターンとして認識して」)。両側とも独立に何度も引き直せるため、
    引き直しのたびに相手側の直線との交差チェック・収束チェック(下値の
    方が急)をやり直す(`_wedge_pool_refit_side`内、段階固定方式時代の
    §6・§6.1と同じ内容を毎回検証する形に置き換え - ユーザー確認済み)。
    片方が2点の直線のまま(3点目がまだ出現していない)でも最小構成として
    成立しうる。
    outcome: 1=invalidated(最小構成が揃う前の破綻), 2=confirmed_lower
    (下値支持線ブレイク), 3=confirmed_upper(上値抵抗線ブレイク),
    4=expired(既定値)。"""
    n = high_a.shape[0]
    MAXT = _ASC_BOX_MAX_TOUCHES

    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)
    resolve_lower_a = np.zeros(n, dtype=np.bool_)
    resolve_upper_a = np.zeros(n, dtype=np.bool_)
    invalidated_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    point_count_a = np.zeros(n, dtype=np.int64)
    point_bar_a = np.full((MAXT, n), np.nan)
    point_price_a = np.full((MAXT, n), np.nan)
    lo_slope_a = np.zeros(n)
    lo_intercept_a = np.zeros(n)
    up_slope_a = np.zeros(n)
    up_intercept_a = np.zeros(n)

    both_lo_events = np.flatnonzero(both_lo_flags)
    both_up_events = np.flatnonzero(both_up_flags)
    left_lo_events = np.flatnonzero(left_lo_flags)
    left_up_events = np.flatnonzero(left_up_flags)

    seed_events = both_lo_events if point1_is_lo else both_up_events

    for ei in range(seed_events.shape[0]):
        p1_bar = seed_events[ei]

        # lo_bar/lo_price/lo_lag: 下値支持線の「現在の直線に沿っている」
        # 構成点(表示・本数カウント対象)。lo_all_*: 下値側の候補として
        # 一度でも採用された点を時刻順にすべて保持するプール(取り消し
        # なし、引き直しの組み合わせ探索の材料として使う - 三角保ち合い
        # v2のreg_all/reg_keptと同じ役割分担)。index0(起点)は固定、
        # 2点目まではそのまま結ぶ直線、3点目以降は`_wedge_pool_refit_side`
        # による複数組み合わせ探索(常に引き直し可能)。
        lo_bar = np.full(MAXT, -1)
        lo_price = np.zeros(MAXT)
        lo_lag = np.zeros(MAXT, dtype=np.int64)
        n_lo = 0
        lo_all_bars = np.full(MAXT, -1)
        lo_all_prices = np.zeros(MAXT)
        lo_all_lags = np.zeros(MAXT, dtype=np.int64)
        n_lo_all = 0
        lo_slope = 0.0
        lo_intercept = 0.0
        lo_reg_fixed = False
        tmp_lo_bars = np.full(MAXT, -1)
        tmp_lo_prices = np.zeros(MAXT)
        tmp_lo_lags = np.zeros(MAXT, dtype=np.int64)

        up_bar = np.full(MAXT, -1)
        up_price = np.zeros(MAXT)
        up_lag = np.zeros(MAXT, dtype=np.int64)
        n_up = 0
        up_all_bars = np.full(MAXT, -1)
        up_all_prices = np.zeros(MAXT)
        up_all_lags = np.zeros(MAXT, dtype=np.int64)
        n_up_all = 0
        up_slope = 0.0
        up_intercept = 0.0
        up_reg_fixed = False
        tmp_up_bars = np.full(MAXT, -1)
        tmp_up_prices = np.zeros(MAXT)
        tmp_up_lags = np.zeros(MAXT, dtype=np.int64)

        if point1_is_lo:
            lo_bar[0] = p1_bar
            lo_price[0] = low_a[p1_bar]
            lo_lag[0] = pivot_confirm_lag
            n_lo = 1
            lo_all_bars[0] = p1_bar
            lo_all_prices[0] = low_a[p1_bar]
            lo_all_lags[0] = pivot_confirm_lag
            n_lo_all = 1
            last_lo_bar = p1_bar
            last_up_bar = -1
        else:
            up_bar[0] = p1_bar
            up_price[0] = high_a[p1_bar]
            up_lag[0] = pivot_confirm_lag
            n_up = 1
            up_all_bars[0] = p1_bar
            up_all_prices[0] = high_a[p1_bar]
            up_all_lags[0] = pivot_confirm_lag
            n_up_all = 1
            last_up_bar = p1_bar
            last_lo_bar = -1

        # 最小構成が揃うまでは山谷交互を強制する(三角保ち合いv2と同じ
        # 考え方)。厳密な交互のもとでは、起点側が常に1ターン先行するため、
        # 起点側が3点目(回帰直線確定)に達した時点で相手側はちょうど2点
        # (直線)になっている - これがユーザー提案の「3点+2点」の最小構成
        # そのもの。
        next_turn_is_lo = not point1_is_lo

        min_met = False
        candidate_floor = -1

        max_scan = p1_bar + max_box_bars
        if max_scan > n - 1:
            max_scan = n - 1

        outcome = 4
        outcome_bar = max_scan
        j_cursor = p1_bar
        failed = False

        while not failed:
            have_min = (n_lo >= 2) and (n_up >= 2) and (lo_reg_fixed or up_reg_fixed)

            lo_r = j_cursor + 1
            floor_lo = last_lo_bar + min_touch_gap_bars
            if floor_lo > lo_r:
                lo_r = floor_lo
            opp_floor_lo = last_up_bar + min_touch_gap_bars
            search_lo_now = have_min or next_turn_is_lo
            if search_lo_now:
                if have_min:
                    lo_cand_bar, lo_cand_price = _asc_box_find_touch(
                        left_lo_events, left_up_events, lo_r, max_scan,
                        False, high_a, low_a, opp_floor_lo,
                    )
                else:
                    lo_cand_bar, lo_cand_price = _asc_box_find_touch(
                        both_lo_events, both_up_events, lo_r, max_scan,
                        False, high_a, low_a, opp_floor_lo,
                    )
            else:
                lo_cand_bar, lo_cand_price = -1, 0.0

            up_r = j_cursor + 1
            floor_up = last_up_bar + min_touch_gap_bars
            if floor_up > up_r:
                up_r = floor_up
            opp_floor_up = last_lo_bar + min_touch_gap_bars
            search_up_now = have_min or not next_turn_is_lo
            if search_up_now:
                if have_min:
                    up_cand_bar, up_cand_price = _asc_box_find_touch(
                        left_up_events, left_lo_events, up_r, max_scan,
                        True, high_a, low_a, opp_floor_up,
                    )
                else:
                    up_cand_bar, up_cand_price = _asc_box_find_touch(
                        both_up_events, both_lo_events, up_r, max_scan,
                        True, high_a, low_a, opp_floor_up,
                    )
            else:
                up_cand_bar, up_cand_price = -1, 0.0

            if lo_cand_bar == -1 and up_cand_bar == -1:
                break

            process_lo = (lo_cand_bar != -1) and (up_cand_bar == -1 or lo_cand_bar <= up_cand_bar)
            cand_bar = lo_cand_bar if process_lo else up_cand_bar
            if cand_bar > max_scan:
                break
            # フィットに失敗して静かに無視される候補(§3.2)は、その側の
            # 交互の番を消費しない(2026-08-19追加 - 消費してしまうと、
            # 失敗した候補が表示(構成点)には一切現れないまま相手側に番が
            # 渡ってしまい、表示上は同じ側が連続しているように見える
            # ケースが多発していた[ユーザー報告・実データで確認]。判定
            # 確定後にturn_consumedを見てnext_turn_is_loを更新する)。
            turn_consumed = True

            # --- 逸脱/ブレイクチェック(それぞれの側が直線を持った時点
            # [2点以上]から、生の高値・安値で独立に監視する) ---
            # 以前はhave_min(両側そろうまで)を待ってから初めて監視していた
            # ため、片方(例: 下値支持線)が先に2点で直線として成立していても、
            # もう片方(上値抵抗線)がまだ3点目を探している間は完全に無監視
            # だった。この間に既に成立している側の直線を生の値動きが大きく
            # 割り込んでいても検出できず、後から見ると「明らかに下値支持線を
            # 割っているのにConfirmedになっている」結果になっていた
            # (2026-08-19、ユーザー報告・実データで確認 - 段階固定方式の頃
            # から存在していた設計の隙間で、今回の複数組み合わせ探索方式
            # 自体が原因ではない)。
            if n_lo >= 2 or n_up >= 2:
                scan_end = cand_bar
                if scan_end > max_scan:
                    scan_end = max_scan
                for k in range(j_cursor + 1, scan_end + 1):
                    lo_val_k = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], k)
                    up_val_k = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], k)
                    height_k = abs(up_val_k - lo_val_k)
                    buf_k = height_k * breakout_buffer_mult

                    lower_break_trigger = (n_lo >= 2) and (low_a[k] < lo_val_k - buf_k)
                    upper_break_trigger = (n_up >= 2) and (high_a[k] > up_val_k + buf_k)

                    if lower_break_trigger or upper_break_trigger:
                        # 同じバーで両方トリガーする場合は下値支持線ブレイク
                        # を優先(教科書通りの上昇ウェッジの想定方向)。
                        break_is_upper = upper_break_trigger and not lower_break_trigger
                        if breakout_type_is_close:
                            end_price = close_a[k]
                            if break_is_upper:
                                confirm_ok = end_price > up_val_k + buf_k
                            else:
                                confirm_ok = end_price < lo_val_k - buf_k
                        else:
                            confirm_ok = True
                        if confirm_ok and max_breakout_height_ratio > 0.0:
                            anchor_bar_h = lo_bar[0] if point1_is_lo else up_bar[0]
                            lo_at_anchor = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], anchor_bar_h)
                            up_at_anchor = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], anchor_bar_h)
                            height_start = abs(up_at_anchor - lo_at_anchor)
                            if height_start > 1e-12 and (height_k / height_start) > max_breakout_height_ratio:
                                confirm_ok = False
                        if min_met and confirm_ok:
                            outcome = 3 if break_is_upper else 2
                        else:
                            outcome = 1
                        outcome_bar = k
                        failed = True
                        break
                if failed:
                    break

            j_cursor = cand_bar

            if process_lo:
                lo_new_lag = pivot_confirm_lag if not have_min else 0
                cand_stored_in_pool = n_lo_all < MAXT
                if cand_stored_in_pool:
                    lo_all_bars[n_lo_all] = cand_bar
                    lo_all_prices[n_lo_all] = lo_cand_price
                    lo_all_lags[n_lo_all] = lo_new_lag
                    n_lo_all += 1
                last_lo_bar = cand_bar

                if n_lo_all == 1:
                    lo_bar[0] = cand_bar
                    lo_price[0] = lo_cand_price
                    lo_lag[0] = lo_new_lag
                    n_lo = 1
                elif n_lo_all == 2 and not lo_reg_fixed:
                    # 2点目 - そのまま結んで直線にする(傾きは上昇必須)。
                    # ここは組み合わせが1通りしかない(起点+この候補だけ)ため
                    # 複数組み合わせ探索の対象外(2026-08-19、この時点では
                    # min_metは必ずFalseなので失敗時は無条件で探索全体を
                    # 打ち切ってよい)。
                    b0 = lo_all_bars[0]
                    p0 = lo_all_prices[0]
                    new_slope = (lo_cand_price - p0) / float(cand_bar - b0)
                    ok = new_slope > 0.0
                    if ok and n_up >= 1:
                        up_v0 = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], b0)
                        up_vc = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], cand_bar)
                        ok = (p0 < up_v0) and (lo_cand_price < up_vc)
                    if ok and n_up >= 2:
                        ok = new_slope > up_slope
                    if ok:
                        lo_bar[1] = cand_bar
                        lo_price[1] = lo_cand_price
                        lo_lag[1] = lo_new_lag
                        n_lo = 2
                        lo_slope = new_slope
                        lo_intercept = p0 - new_slope * b0
                    else:
                        outcome = 1
                        outcome_bar = cand_bar
                        failed = True
                        break
                else:
                    # 3点目以降 - 三角保ち合いv2の回帰側と同じ「起点固定+
                    # 複数組み合わせ探索」(2026-08-19、段階固定方式から変更)。
                    # 固定済みの直線に単純に収まるならそのまま追加するだけで
                    # 済ませ(fits_current)、収まらない場合だけ引き直しを
                    # 試す。まだ一度も回帰直線が固定されていない場合は常に
                    # 引き直しを試す。
                    fits_current = False
                    if lo_reg_fixed:
                        line_val = lo_slope * cand_bar + lo_intercept
                        hh = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], cand_bar)
                        tol = abs(hh - line_val) * level_tolerance_mult
                        fits_current = abs(lo_cand_price - line_val) <= tol

                    if fits_current:
                        if n_lo < MAXT:
                            lo_bar[n_lo] = cand_bar
                            lo_price[n_lo] = lo_cand_price
                            lo_lag[n_lo] = lo_new_lag
                            n_lo += 1
                    else:
                        refit_ok, new_slope, new_intercept, keep_n = _wedge_pool_refit_side(
                            lo_all_bars, lo_all_prices, lo_all_lags, n_lo_all,
                            n_up, up_slope, up_intercept, up_price[0], up_bar,
                            True, not have_min,
                            atr_a, high_a, low_a,
                            breakout_buffer_mult, min_slope_rise_atr_mult, max_slope_rise_atr_mult,
                            level_tolerance_mult,
                            tmp_lo_bars, tmp_lo_prices, tmp_lo_lags, MAXT,
                        )
                        if refit_ok:
                            lo_slope = new_slope
                            lo_intercept = new_intercept
                            lo_reg_fixed = True
                            for zi in range(keep_n):
                                lo_bar[zi] = tmp_lo_bars[zi]
                                lo_price[zi] = tmp_lo_prices[zi]
                                lo_lag[zi] = tmp_lo_lags[zi]
                            n_lo = keep_n
                        elif lo_reg_fixed:
                            # どの組み合わせでも引き直せなかった理由は傾き・
                            # 許容誤差・急さ・遡及破綻・交差・収束のどれか1つ
                            # でもあり得るため、失敗=本当の意味での支持線割れ
                            # とは限らない。今の(引き直し前の)直線より下に
                            # 外れている場合だけブレイク扱いにする(元の段階
                            # 固定方式時代からの向き付きチェックを踏襲)。
                            cur_lo_val = lo_slope * cand_bar + lo_intercept
                            if lo_cand_price < cur_lo_val:
                                outcome = 2 if min_met else 1
                                outcome_bar = cand_bar
                                failed = True
                                break
                            else:
                                # 直線より上に外れただけ(切り上がりが強すぎる)
                                # なら形の破綻ではないため無視するが、この側の
                                # 交互の番は消費しない(下で見るturn_consumed)。
                                turn_consumed = False
                        else:
                            # まだ一度も回帰直線が成立していない場合は罰則なし、
                            # 探索を続ける(将来の候補でいつか成立するかもしれ
                            # ない)。この側の交互の番も消費しない。
                            turn_consumed = False
            else:
                up_new_lag = pivot_confirm_lag if not have_min else 0
                cand_stored_in_pool = n_up_all < MAXT
                if cand_stored_in_pool:
                    up_all_bars[n_up_all] = cand_bar
                    up_all_prices[n_up_all] = up_cand_price
                    up_all_lags[n_up_all] = up_new_lag
                    n_up_all += 1
                last_up_bar = cand_bar

                if n_up_all == 1:
                    up_bar[0] = cand_bar
                    up_price[0] = up_cand_price
                    up_lag[0] = up_new_lag
                    n_up = 1
                elif n_up_all == 2 and not up_reg_fixed:
                    b0 = up_all_bars[0]
                    p0 = up_all_prices[0]
                    new_slope = (up_cand_price - p0) / float(cand_bar - b0)
                    ok = new_slope > 0.0
                    if ok and n_lo >= 1:
                        lo_v0 = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], b0)
                        lo_vc = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], cand_bar)
                        ok = (p0 > lo_v0) and (up_cand_price > lo_vc)
                    if ok and n_lo >= 2:
                        ok = lo_slope > new_slope
                    if ok:
                        up_bar[1] = cand_bar
                        up_price[1] = up_cand_price
                        up_lag[1] = up_new_lag
                        n_up = 2
                        up_slope = new_slope
                        up_intercept = p0 - new_slope * b0
                    else:
                        outcome = 1
                        outcome_bar = cand_bar
                        failed = True
                        break
                else:
                    # 下値側と対称。
                    fits_current = False
                    if up_reg_fixed:
                        line_val = up_slope * cand_bar + up_intercept
                        hh = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], cand_bar)
                        tol = abs(line_val - hh) * level_tolerance_mult
                        fits_current = abs(up_cand_price - line_val) <= tol

                    if fits_current:
                        if n_up < MAXT:
                            up_bar[n_up] = cand_bar
                            up_price[n_up] = up_cand_price
                            up_lag[n_up] = up_new_lag
                            n_up += 1
                    else:
                        refit_ok, new_slope, new_intercept, keep_n = _wedge_pool_refit_side(
                            up_all_bars, up_all_prices, up_all_lags, n_up_all,
                            n_lo, lo_slope, lo_intercept, lo_price[0], lo_bar,
                            False, not have_min,
                            atr_a, high_a, low_a,
                            breakout_buffer_mult, min_slope_rise_atr_mult, max_slope_rise_atr_mult,
                            level_tolerance_mult,
                            tmp_up_bars, tmp_up_prices, tmp_up_lags, MAXT,
                        )
                        if refit_ok:
                            up_slope = new_slope
                            up_intercept = new_intercept
                            up_reg_fixed = True
                            for zi in range(keep_n):
                                up_bar[zi] = tmp_up_bars[zi]
                                up_price[zi] = tmp_up_prices[zi]
                                up_lag[zi] = tmp_up_lags[zi]
                            n_up = keep_n
                        elif up_reg_fixed:
                            cur_up_val = up_slope * cand_bar + up_intercept
                            if up_cand_price > cur_up_val:
                                outcome = 3 if min_met else 1
                                outcome_bar = cand_bar
                                failed = True
                                break
                            else:
                                # 下値側と対称(直線より下に外れただけなら
                                # 無視するが、番は消費しない)。
                                turn_consumed = False
                        else:
                            # まだ一度も回帰直線が成立していない場合は罰則
                            # なし、探索を続ける。番も消費しない。
                            turn_consumed = False

            # フィットに失敗して静かに無視された候補は、その側の交互の番を
            # 消費しない(turn_consumed=False、上のprocess_lo/process_up
            # 参照)。2026-08-19追加、ユーザー報告「同じ側が連続して見える」
            # 対応。
            if not have_min and turn_consumed:
                next_turn_is_lo = not process_lo

            if not min_met and (n_lo >= 2) and (n_up >= 2) and (lo_reg_fixed or up_reg_fixed):
                cf = p1_bar + (lo_lag[0] if point1_is_lo else up_lag[0])
                for pi2 in range(n_lo):
                    cb2 = lo_bar[pi2] + lo_lag[pi2]
                    if cb2 > cf:
                        cf = cb2
                for ti2 in range(n_up):
                    cb2 = up_bar[ti2] + up_lag[ti2]
                    if cb2 > cf:
                        cf = cb2
                if cf < n:
                    pc_cand = n_lo + n_up
                    if pc_cand > MAXT:
                        pc_cand = MAXT
                    ok_bars = np.zeros(pc_cand, dtype=np.int64)
                    ok_prices = np.zeros(pc_cand)
                    ok_is_up = np.zeros(pc_cand, dtype=np.bool_)
                    ri = 0
                    fi2 = 0
                    pt_c = 0
                    while ri < n_lo and fi2 < n_up and pt_c < pc_cand:
                        if lo_bar[ri] <= up_bar[fi2]:
                            ok_bars[pt_c] = lo_bar[ri]
                            ok_prices[pt_c] = lo_price[ri]
                            ok_is_up[pt_c] = False
                            ri += 1
                        else:
                            ok_bars[pt_c] = up_bar[fi2]
                            ok_prices[pt_c] = up_price[fi2]
                            ok_is_up[pt_c] = True
                            fi2 += 1
                        pt_c += 1
                    while ri < n_lo and pt_c < pc_cand:
                        ok_bars[pt_c] = lo_bar[ri]
                        ok_prices[pt_c] = lo_price[ri]
                        ok_is_up[pt_c] = False
                        ri += 1
                        pt_c += 1
                    while fi2 < n_up and pt_c < pc_cand:
                        ok_bars[pt_c] = up_bar[fi2]
                        ok_prices[pt_c] = up_price[fi2]
                        ok_is_up[pt_c] = True
                        fi2 += 1
                        pt_c += 1

                    spike_ok = True
                    for qi in range(pc_cand):
                        bar_q = ok_bars[qi]
                        is_high_q = ok_is_up[qi]
                        price_arr_q = high_a if ok_is_up[qi] else low_a
                        if qi > 0:
                            interval_l = bar_q - ok_bars[qi - 1]
                            win_l = int(round(interval_l * pivot_spike_window_ratio))
                            if not _shape_spike_ok(price_arr_q, atr_a, n, bar_q, win_l, False, is_high_q, pivot_spike_excess_atr_max):
                                spike_ok = False
                                break
                        if qi < pc_cand - 1:
                            interval_r = ok_bars[qi + 1] - bar_q
                            win_r = int(round(interval_r * pivot_spike_window_ratio))
                            if not _shape_spike_ok(price_arr_q, atr_a, n, bar_q, win_r, True, is_high_q, pivot_spike_excess_atr_max):
                                spike_ok = False
                                break

                    if not spike_ok:
                        failed = True
                        break

                    # `_wedge_pool_refit_side`は引き直しのたびに相手側との
                    # 交差・収束チェックを行うが、最小構成成立の瞬間だけは
                    # 「今まさに固定された側」と「まだ2点結びのままの側」を
                    # 組み合わせて初めて全構成点が並ぶため、念のためここでも
                    # 同じ内容を最終防衛としてもう一度確認する(docs/
                    # pattern_spec_wedge_shape_v2.md§6参照)。
                    lines_ok = True
                    for qi in range(pc_cand):
                        bar_q = ok_bars[qi]
                        lo_val_q = lo_slope * bar_q + lo_intercept
                        up_val_q = up_slope * bar_q + up_intercept
                        if lo_val_q >= up_val_q:
                            lines_ok = False
                            break
                    # 上昇ウェッジは下値支持線の方が上値抵抗線より急な角度で
                    # 上昇していないと収束しない(docs/…§6.1参照、同じ最終
                    # 防衛)。
                    if lo_slope <= up_slope:
                        lines_ok = False
                    if not lines_ok:
                        failed = True
                        break

                    min_met = True
                    candidate_floor = cf
                    detected_a[cf] = True
                    formed_bar_a[cf] = cf
                    for qi in range(pc_cand):
                        point_bar_a[qi, cf] = ok_bars[qi]
                        point_price_a[qi, cf] = ok_prices[qi]
                    point_count_a[cf] = pc_cand
                    lo_slope_a[cf] = lo_slope
                    lo_intercept_a[cf] = lo_intercept
                    up_slope_a[cf] = up_slope
                    up_intercept_a[cf] = up_intercept

        if failed and outcome != 4:
            if candidate_floor == -1:
                continue

            final_floor = p1_bar + (lo_lag[0] if point1_is_lo else up_lag[0])
            for pi in range(n_lo):
                cb = lo_bar[pi] + lo_lag[pi]
                if cb > final_floor:
                    final_floor = cb
            for ti in range(n_up):
                cb = up_bar[ti] + up_lag[ti]
                if cb > final_floor:
                    final_floor = cb
            if final_floor >= n:
                continue

            ob = outcome_bar
            if ob < final_floor:
                ob = final_floor

            for idx2 in range(candidate_floor, ob + 1):
                if idx2 == candidate_floor or not detected_a[idx2]:
                    exists_a[idx2] = True
                    formed_bar_a[idx2] = candidate_floor

            formed_bar_a[ob] = ob
            pi = 0
            ti = 0
            pt_i = 0
            while pi < n_lo and ti < n_up and pt_i < MAXT:
                if lo_bar[pi] <= up_bar[ti]:
                    point_bar_a[pt_i, ob] = lo_bar[pi]
                    point_price_a[pt_i, ob] = lo_price[pi]
                    pi += 1
                else:
                    point_bar_a[pt_i, ob] = up_bar[ti]
                    point_price_a[pt_i, ob] = up_price[ti]
                    ti += 1
                pt_i += 1
            while pi < n_lo and pt_i < MAXT:
                point_bar_a[pt_i, ob] = lo_bar[pi]
                point_price_a[pt_i, ob] = lo_price[pi]
                pi += 1
                pt_i += 1
            while ti < n_up and pt_i < MAXT:
                point_bar_a[pt_i, ob] = up_bar[ti]
                point_price_a[pt_i, ob] = up_price[ti]
                ti += 1
                pt_i += 1
            point_count_a[ob] = pt_i
            lo_slope_a[ob] = lo_slope
            lo_intercept_a[ob] = lo_intercept
            up_slope_a[ob] = up_slope
            up_intercept_a[ob] = up_intercept

            if outcome == 2:
                resolve_lower_a[ob] = True
            elif outcome == 3:
                resolve_upper_a[ob] = True
            else:
                invalidated_a[ob] = True

    return (
        exists_a, detected_a, invalidated_a, resolve_lower_a, resolve_upper_a,
        formed_bar_a, point_count_a, point_bar_a, point_price_a,
        lo_slope_a, lo_intercept_a, up_slope_a, up_intercept_a,
    )


def _merge_shape_dual_seed_wedge(res_a: tuple, res_b: tuple) -> tuple:
    """`_merge_shape_dual_seed`のウェッジ版(状態がresolve_lower/resolve_
    upperの2つに分かれ、水準線が無くlo/up両方が回帰直線になった分だけ
    フィールドが違う。マージの考え方(バーごとにaがexistsならa)は同じ)。"""
    (exists_a, detected_a, invalidated_a, resolve_lower_a, resolve_upper_a,
     formed_bar_a, point_count_a, point_bar_a, point_price_a,
     lo_slope_a, lo_intercept_a, up_slope_a, up_intercept_a) = res_a
    (exists_b, detected_b, invalidated_b, resolve_lower_b, resolve_upper_b,
     formed_bar_b, point_count_b, point_bar_b, point_price_b,
     lo_slope_b, lo_intercept_b, up_slope_b, up_intercept_b) = res_b

    use_a = exists_a
    exists = np.where(use_a, exists_a, exists_b)
    detected = np.where(use_a, detected_a, detected_b)
    invalidated = np.where(use_a, invalidated_a, invalidated_b)
    resolve_lower = np.where(use_a, resolve_lower_a, resolve_lower_b)
    resolve_upper = np.where(use_a, resolve_upper_a, resolve_upper_b)
    formed_bar = np.where(use_a, formed_bar_a, formed_bar_b)
    point_count = np.where(use_a, point_count_a, point_count_b)
    point_bar = np.where(use_a[np.newaxis, :], point_bar_a, point_bar_b)
    point_price = np.where(use_a[np.newaxis, :], point_price_a, point_price_b)
    lo_slope = np.where(use_a, lo_slope_a, lo_slope_b)
    lo_intercept = np.where(use_a, lo_intercept_a, lo_intercept_b)
    up_slope = np.where(use_a, up_slope_a, up_slope_b)
    up_intercept = np.where(use_a, up_intercept_a, up_intercept_b)
    return (
        exists, detected, invalidated, resolve_lower, resolve_upper,
        formed_bar, point_count, point_bar, point_price,
        lo_slope, lo_intercept, up_slope, up_intercept,
    )


def _wedge_shape_state_v2(
    high: pd.Series, low: pd.Series, close: pd.Series,
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    pivot_spike_window_ratio: float = 0.0,
    pivot_spike_excess_atr_max: float = 0.0,
    min_slope_rise_atr_mult: float = 1.0,
    max_slope_rise_atr_mult: float = 0.0,
    max_breakout_height_ratio: float = 0.0,
) -> dict[str, Any]:
    """docs/pattern_spec_wedge_shape_v2.md参照。点1は下値側・上値側
    どちらからでも探索し(_triangle_shape_state_v2と同じ2方向探索)、
    結果を`_merge_shape_dual_seed_wedge`でマージする。"""
    idx_index = high.index
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_a = _atr_series(df, 14).to_numpy()

    if breakout_type not in ("close", "wick"):
        raise ValueError(f"未対応のbreakout_typeです(close/wickのみ対応): {breakout_type}")

    pivot_left_bars = max(0, pivot_left_bars)
    pivot_right_bars = max(0, pivot_right_bars)
    if pivot_left_bars == 0 and pivot_right_bars == 0:
        pivot_left_bars = 1

    both_high_flags = _pivot_flags(high, pivot_left_bars, pivot_right_bars, True).to_numpy()
    both_low_flags = _pivot_flags(low, pivot_left_bars, pivot_right_bars, False).to_numpy()
    left_high_flags = _detect_pivot_highs_left_only(high, pivot_left_bars).to_numpy()
    left_low_flags = _detect_pivot_lows_left_only(low, pivot_left_bars).to_numpy()

    res_lo_seed = _shape_state_core_wedge_v2(
        high_a, low_a, close_a, atr_a,
        both_low_flags, both_high_flags, left_low_flags, left_high_flags,
        True,
        int(pivot_right_bars), int(min_touch_gap_bars),
        float(level_tolerance_mult), float(breakout_buffer_mult),
        breakout_type == "close", int(max_box_bars),
        float(pivot_spike_window_ratio), float(pivot_spike_excess_atr_max),
        float(min_slope_rise_atr_mult), float(max_slope_rise_atr_mult),
        float(max_breakout_height_ratio),
    )
    res_up_seed = _shape_state_core_wedge_v2(
        high_a, low_a, close_a, atr_a,
        both_low_flags, both_high_flags, left_low_flags, left_high_flags,
        False,
        int(pivot_right_bars), int(min_touch_gap_bars),
        float(level_tolerance_mult), float(breakout_buffer_mult),
        breakout_type == "close", int(max_box_bars),
        float(pivot_spike_window_ratio), float(pivot_spike_excess_atr_max),
        float(min_slope_rise_atr_mult), float(max_slope_rise_atr_mult),
        float(max_breakout_height_ratio),
    )

    (
        exists_a, detected_a, invalidated_a, resolve_lower_a, resolve_upper_a,
        formed_bar_a, point_count_a, point_bar_a, point_price_a,
        lo_slope_a, lo_intercept_a, up_slope_a, up_intercept_a,
    ) = _merge_shape_dual_seed_wedge(res_lo_seed, res_up_seed)

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "candidate": pd.Series(detected_a, index=idx_index),
        "confirmed_lower": pd.Series(resolve_lower_a, index=idx_index),
        "confirmed_upper": pd.Series(resolve_upper_a, index=idx_index),
        "invalidated": pd.Series(invalidated_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "point_count": point_count_a,
        "point_bar": point_bar_a,
        "point_price": point_price_a,
        "lo_slope": lo_slope_a,
        "lo_intercept": lo_intercept_a,
        "up_slope": up_slope_a,
        "up_intercept": up_intercept_a,
    }


_WEDGE_STATE_KEYS = {
    "candidate": "candidate",
    "confirmed_lower": "confirmed_lower",
    "confirmed_upper": "confirmed_upper",
    "invalidated": "invalidated",
    "exists": "exists",
}


def rising_wedge_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed_lower",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    pivot_spike_window_ratio: float = 0.0,
    pivot_spike_excess_atr_max: float = 0.0,
    min_slope_rise_atr_mult: float = 1.0,
    max_slope_rise_atr_mult: float = 0.0,
    max_breakout_height_ratio: float = 0.0,
) -> np.ndarray:
    """上昇ウェッジ(可変タッチ・両側回帰直線方式v2) -
    docs/pattern_spec_wedge_shape_v2.md。下値支持線・上値抵抗線の両方が
    ascending_triangle_shapeの下値支持線と全く同じ方式(起点固定+常に
    引き直し可能な回帰直線、傾きは両方とも上昇必須)で決まる点が三角
    保ち合いとの違い。状態はCandidate/Invalidatedに加えてConfirmedが
    confirmed_lower(下値支持線ブレイク)/confirmed_upper(上値抵抗線
    ブレイク)の2種類(2026-08-19、ユーザー指示で旧実装から全面書き換え)。"""
    result = _wedge_shape_state_v2(
        high, low, close,
        pivot_left_bars=pivot_left_bars, pivot_right_bars=pivot_right_bars,
        min_touch_gap_bars=min_touch_gap_bars, level_tolerance_mult=level_tolerance_mult,
        breakout_buffer_mult=breakout_buffer_mult, breakout_type=breakout_type,
        max_box_bars=max_box_bars,
        pivot_spike_window_ratio=pivot_spike_window_ratio,
        pivot_spike_excess_atr_max=pivot_spike_excess_atr_max,
        min_slope_rise_atr_mult=min_slope_rise_atr_mult,
        max_slope_rise_atr_mult=max_slope_rise_atr_mult,
        max_breakout_height_ratio=max_breakout_height_ratio,
    )
    key = _WEDGE_STATE_KEYS.get(state, "confirmed_lower")
    return result[key].to_numpy(dtype=float)
# ---------------------------------------------------------------------------
# 上昇ウェッジX(2026-08-19、rising_wedge_shape[上昇ウェッジST]のこの時点の
# 実装をそのまま複製して保存 - ユーザー指示。以降rising_wedge_shapeとは
# 独立に変更しうる別の家系として扱う。ロジックはコピー元と完全に同一。
# ---------------------------------------------------------------------------


@njit(cache=True)
def _shape_state_core_wedge_x_v2(
    high_a, low_a, close_a, atr_a,
    both_lo_flags, both_up_flags,
    left_lo_flags, left_up_flags,
    point1_is_lo,
    pivot_confirm_lag,
    min_touch_gap_bars,
    level_tolerance_mult,
    breakout_buffer_mult,
    breakout_type_is_close,
    max_box_bars,
    pivot_spike_window_ratio,
    pivot_spike_excess_atr_max,
    min_slope_rise_atr_mult,
    max_slope_rise_atr_mult,
    max_breakout_height_ratio,
):
    """docs/pattern_spec_wedge_shape_v2.md参照(2026-08-19、ユーザー指示で
    再設計)。下値支持線・上値抵抗線とも、最初の2点をそのまま結ぶ直線から
    始め、3点目のピボットが出現した時点で最小二乗の回帰直線に1回だけ
    引き直し、以降は(4点目以降が出現しても)固定したままにする(三角
    保ち合いv2のような「常に引き直し可能」ではない - 両方を独立に何度も
    引き直せる方式だと、確定の瞬間に2本の直線が既に交差していることが
    あるという問題への対応、ユーザー提案)。片方が2点の直線のまま
    (3点目がまだ出現していない)でも最小構成として成立しうる。
    outcome: 1=invalidated(最小構成が揃う前の破綻), 2=confirmed_lower
    (下値支持線ブレイク), 3=confirmed_upper(上値抵抗線ブレイク),
    4=expired(既定値)。"""
    n = high_a.shape[0]
    MAXT = _ASC_BOX_MAX_TOUCHES

    exists_a = np.zeros(n, dtype=np.bool_)
    detected_a = np.zeros(n, dtype=np.bool_)
    resolve_lower_a = np.zeros(n, dtype=np.bool_)
    resolve_upper_a = np.zeros(n, dtype=np.bool_)
    invalidated_a = np.zeros(n, dtype=np.bool_)
    formed_bar_a = np.full(n, np.nan)
    point_count_a = np.zeros(n, dtype=np.int64)
    point_bar_a = np.full((MAXT, n), np.nan)
    point_price_a = np.full((MAXT, n), np.nan)
    lo_slope_a = np.zeros(n)
    lo_intercept_a = np.zeros(n)
    up_slope_a = np.zeros(n)
    up_intercept_a = np.zeros(n)

    both_lo_events = np.flatnonzero(both_lo_flags)
    both_up_events = np.flatnonzero(both_up_flags)
    left_lo_events = np.flatnonzero(left_lo_flags)
    left_up_events = np.flatnonzero(left_up_flags)

    seed_events = both_lo_events if point1_is_lo else both_up_events

    for ei in range(seed_events.shape[0]):
        p1_bar = seed_events[ei]

        # lo_bar/lo_price/lo_lag: 下値支持線の構成点(時刻順)。index 0・1は
        # 常に「最初の2点を結ぶ直線」、3点目が出現した時点でindex 2まで
        # 埋まり、以降は回帰直線として固定される(lo_reg_fixed=True)。
        # 4点目以降(index 3〜)は、固定済みの直線に対する許容誤差内なら
        # 表示用に追加されるだけで、直線自体には一切影響しない。
        lo_bar = np.full(MAXT, -1)
        lo_price = np.zeros(MAXT)
        lo_lag = np.zeros(MAXT, dtype=np.int64)
        n_lo = 0
        lo_slope = 0.0
        lo_intercept = 0.0
        lo_reg_fixed = False

        up_bar = np.full(MAXT, -1)
        up_price = np.zeros(MAXT)
        up_lag = np.zeros(MAXT, dtype=np.int64)
        n_up = 0
        up_slope = 0.0
        up_intercept = 0.0
        up_reg_fixed = False

        if point1_is_lo:
            lo_bar[0] = p1_bar
            lo_price[0] = low_a[p1_bar]
            lo_lag[0] = pivot_confirm_lag
            n_lo = 1
            last_lo_bar = p1_bar
            last_up_bar = -1
        else:
            up_bar[0] = p1_bar
            up_price[0] = high_a[p1_bar]
            up_lag[0] = pivot_confirm_lag
            n_up = 1
            last_up_bar = p1_bar
            last_lo_bar = -1

        # 最小構成が揃うまでは山谷交互を強制する(三角保ち合いv2と同じ
        # 考え方)。厳密な交互のもとでは、起点側が常に1ターン先行するため、
        # 起点側が3点目(回帰直線確定)に達した時点で相手側はちょうど2点
        # (直線)になっている - これがユーザー提案の「3点+2点」の最小構成
        # そのもの。
        next_turn_is_lo = not point1_is_lo

        min_met = False
        candidate_floor = -1

        max_scan = p1_bar + max_box_bars
        if max_scan > n - 1:
            max_scan = n - 1

        outcome = 4
        outcome_bar = max_scan
        j_cursor = p1_bar
        failed = False

        while not failed:
            have_min = (n_lo >= 2) and (n_up >= 2) and (lo_reg_fixed or up_reg_fixed)

            lo_r = j_cursor + 1
            floor_lo = last_lo_bar + min_touch_gap_bars
            if floor_lo > lo_r:
                lo_r = floor_lo
            opp_floor_lo = last_up_bar + min_touch_gap_bars
            search_lo_now = have_min or next_turn_is_lo
            if search_lo_now:
                if have_min:
                    lo_cand_bar, lo_cand_price = _asc_box_find_touch(
                        left_lo_events, left_up_events, lo_r, max_scan,
                        False, high_a, low_a, opp_floor_lo,
                    )
                else:
                    lo_cand_bar, lo_cand_price = _asc_box_find_touch(
                        both_lo_events, both_up_events, lo_r, max_scan,
                        False, high_a, low_a, opp_floor_lo,
                    )
            else:
                lo_cand_bar, lo_cand_price = -1, 0.0

            up_r = j_cursor + 1
            floor_up = last_up_bar + min_touch_gap_bars
            if floor_up > up_r:
                up_r = floor_up
            opp_floor_up = last_lo_bar + min_touch_gap_bars
            search_up_now = have_min or not next_turn_is_lo
            if search_up_now:
                if have_min:
                    up_cand_bar, up_cand_price = _asc_box_find_touch(
                        left_up_events, left_lo_events, up_r, max_scan,
                        True, high_a, low_a, opp_floor_up,
                    )
                else:
                    up_cand_bar, up_cand_price = _asc_box_find_touch(
                        both_up_events, both_lo_events, up_r, max_scan,
                        True, high_a, low_a, opp_floor_up,
                    )
            else:
                up_cand_bar, up_cand_price = -1, 0.0

            if lo_cand_bar == -1 and up_cand_bar == -1:
                break

            process_lo = (lo_cand_bar != -1) and (up_cand_bar == -1 or lo_cand_bar <= up_cand_bar)
            cand_bar = lo_cand_bar if process_lo else up_cand_bar
            if cand_bar > max_scan:
                break
            if not have_min:
                next_turn_is_lo = not process_lo

            # --- 逸脱/ブレイクチェック(両直線がそろってから、生の高値・安値で) ---
            if have_min:
                scan_end = cand_bar
                if scan_end > max_scan:
                    scan_end = max_scan
                for k in range(j_cursor + 1, scan_end + 1):
                    lo_val_k = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], k)
                    up_val_k = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], k)
                    height_k = abs(up_val_k - lo_val_k)
                    buf_k = height_k * breakout_buffer_mult

                    lower_break_trigger = low_a[k] < lo_val_k - buf_k
                    upper_break_trigger = high_a[k] > up_val_k + buf_k

                    if lower_break_trigger or upper_break_trigger:
                        # 同じバーで両方トリガーする場合は下値支持線ブレイク
                        # を優先(教科書通りの上昇ウェッジの想定方向)。
                        break_is_upper = upper_break_trigger and not lower_break_trigger
                        if breakout_type_is_close:
                            end_price = close_a[k]
                            if break_is_upper:
                                confirm_ok = end_price > up_val_k + buf_k
                            else:
                                confirm_ok = end_price < lo_val_k - buf_k
                        else:
                            confirm_ok = True
                        if confirm_ok and max_breakout_height_ratio > 0.0:
                            anchor_bar_h = lo_bar[0] if point1_is_lo else up_bar[0]
                            lo_at_anchor = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], anchor_bar_h)
                            up_at_anchor = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], anchor_bar_h)
                            height_start = abs(up_at_anchor - lo_at_anchor)
                            if height_start > 1e-12 and (height_k / height_start) > max_breakout_height_ratio:
                                confirm_ok = False
                        if min_met and confirm_ok:
                            outcome = 3 if break_is_upper else 2
                        else:
                            outcome = 1
                        outcome_bar = k
                        failed = True
                        break
                if failed:
                    break

            j_cursor = cand_bar

            if process_lo:
                lo_new_lag = pivot_confirm_lag if not have_min else 0
                if n_lo == 0:
                    lo_bar[0] = cand_bar
                    lo_price[0] = lo_cand_price
                    lo_lag[0] = lo_new_lag
                    n_lo = 1
                    last_lo_bar = cand_bar
                elif n_lo == 1:
                    # 2点目 - そのまま結んで直線にする(傾きは上昇必須)。
                    b0 = lo_bar[0]
                    p0 = lo_price[0]
                    new_slope = (lo_cand_price - p0) / float(cand_bar - b0)
                    if new_slope > 0.0:
                        lo_bar[1] = cand_bar
                        lo_price[1] = lo_cand_price
                        lo_lag[1] = lo_new_lag
                        n_lo = 2
                        lo_slope = new_slope
                        lo_intercept = p0 - new_slope * b0
                        last_lo_bar = cand_bar
                    else:
                        # この2点では上昇にならない -> この探索(p1_bar)は
                        # 不成立(引き直しの余地を持たない設計のため)。
                        outcome = 1
                        outcome_bar = cand_bar
                        failed = True
                        break
                elif n_lo == 2 and not lo_reg_fixed:
                    # 3点目 - 最小二乗の回帰直線を1回だけ引き、以降固定する。
                    b0 = lo_bar[0]
                    p0 = lo_price[0]
                    b1 = lo_bar[1]
                    p1v = lo_price[1]
                    sx = float(b0 + b1 + cand_bar)
                    sy = p0 + p1v + lo_cand_price
                    sxy = float(b0) * p0 + float(b1) * p1v + float(cand_bar) * lo_cand_price
                    sxx = float(b0 * b0 + b1 * b1 + cand_bar * cand_bar)
                    dn = 3.0 * sxx - sx * sx
                    ok = dn != 0.0
                    new_slope = 0.0
                    new_intercept = 0.0
                    if ok:
                        new_slope = (3.0 * sxy - sx * sy) / dn
                        new_intercept = (sy - new_slope * sx) / 3.0
                        ok = new_slope > 0.0
                    if ok:
                        h0 = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], b0)
                        lv0 = new_slope * b0 + new_intercept
                        ok = abs(p0 - lv0) <= abs(h0 - lv0) * level_tolerance_mult
                    if ok:
                        h1 = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], b1)
                        lv1 = new_slope * b1 + new_intercept
                        ok = abs(p1v - lv1) <= abs(h1 - lv1) * level_tolerance_mult
                    if ok:
                        hc = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], cand_bar)
                        lvc = new_slope * cand_bar + new_intercept
                        ok = abs(lo_cand_price - lvc) <= abs(hc - lvc) * level_tolerance_mult
                    if ok:
                        total_rise = new_slope * (cand_bar - b0)
                        rise_min = atr_a[cand_bar] * min_slope_rise_atr_mult
                        rise_max = np.inf if max_slope_rise_atr_mult <= 0.0 else atr_a[cand_bar] * max_slope_rise_atr_mult
                        ok = rise_min <= abs(total_rise) <= rise_max
                    if ok:
                        # 起点〜今回の候補までを生の安値でこの直線に照らして
                        # 遡ってチェックする(三角保ち合いv2§5.4と同じ)。
                        for kb in range(b0, cand_bar + 1):
                            line_kb = new_slope * kb + new_intercept
                            hkb = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], kb)
                            buf_kb = abs(hkb - line_kb) * breakout_buffer_mult
                            if low_a[kb] < line_kb - buf_kb:
                                ok = False
                                break
                    if ok:
                        lo_bar[2] = cand_bar
                        lo_price[2] = lo_cand_price
                        lo_lag[2] = lo_new_lag
                        n_lo = 3
                        lo_slope = new_slope
                        lo_intercept = new_intercept
                        lo_reg_fixed = True
                        last_lo_bar = cand_bar
                    else:
                        outcome = 2 if min_met else 1
                        outcome_bar = cand_bar
                        failed = True
                        break
                else:
                    # 4点目以降 - 固定済みの直線に対する許容誤差内かだけを
                    # チェックする(直線自体は引き直さない)。
                    line_val = lo_slope * cand_bar + lo_intercept
                    hh = _wedge_line_value(n_up, up_slope, up_intercept, up_price[0], cand_bar)
                    height = abs(hh - line_val)
                    tol = height * level_tolerance_mult
                    if abs(lo_cand_price - line_val) <= tol:
                        if n_lo < MAXT:
                            lo_bar[n_lo] = cand_bar
                            lo_price[n_lo] = lo_cand_price
                            lo_lag[n_lo] = lo_new_lag
                            n_lo += 1
                        last_lo_bar = cand_bar
                    else:
                        last_lo_bar = cand_bar
                        if lo_cand_price < line_val:
                            # 直線より下に外れた = 本当の意味での支持線割れ。
                            outcome = 2 if min_met else 1
                            outcome_bar = cand_bar
                            failed = True
                            break
                        # 直線より上に外れただけ(切り上がりが強すぎる)なら
                        # 形の破綻ではないため無視して探索を続ける。
            else:
                up_new_lag = pivot_confirm_lag if not have_min else 0
                if n_up == 0:
                    up_bar[0] = cand_bar
                    up_price[0] = up_cand_price
                    up_lag[0] = up_new_lag
                    n_up = 1
                    last_up_bar = cand_bar
                elif n_up == 1:
                    b0 = up_bar[0]
                    p0 = up_price[0]
                    new_slope = (up_cand_price - p0) / float(cand_bar - b0)
                    if new_slope > 0.0:
                        up_bar[1] = cand_bar
                        up_price[1] = up_cand_price
                        up_lag[1] = up_new_lag
                        n_up = 2
                        up_slope = new_slope
                        up_intercept = p0 - new_slope * b0
                        last_up_bar = cand_bar
                    else:
                        outcome = 1
                        outcome_bar = cand_bar
                        failed = True
                        break
                elif n_up == 2 and not up_reg_fixed:
                    b0 = up_bar[0]
                    p0 = up_price[0]
                    b1 = up_bar[1]
                    p1v = up_price[1]
                    sx = float(b0 + b1 + cand_bar)
                    sy = p0 + p1v + up_cand_price
                    sxy = float(b0) * p0 + float(b1) * p1v + float(cand_bar) * up_cand_price
                    sxx = float(b0 * b0 + b1 * b1 + cand_bar * cand_bar)
                    dn = 3.0 * sxx - sx * sx
                    ok = dn != 0.0
                    new_slope = 0.0
                    new_intercept = 0.0
                    if ok:
                        new_slope = (3.0 * sxy - sx * sy) / dn
                        new_intercept = (sy - new_slope * sx) / 3.0
                        ok = new_slope > 0.0
                    if ok:
                        h0 = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], b0)
                        lv0 = new_slope * b0 + new_intercept
                        ok = abs(p0 - lv0) <= abs(lv0 - h0) * level_tolerance_mult
                    if ok:
                        h1 = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], b1)
                        lv1 = new_slope * b1 + new_intercept
                        ok = abs(p1v - lv1) <= abs(lv1 - h1) * level_tolerance_mult
                    if ok:
                        hc = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], cand_bar)
                        lvc = new_slope * cand_bar + new_intercept
                        ok = abs(up_cand_price - lvc) <= abs(lvc - hc) * level_tolerance_mult
                    if ok:
                        total_rise = new_slope * (cand_bar - b0)
                        rise_min = atr_a[cand_bar] * min_slope_rise_atr_mult
                        rise_max = np.inf if max_slope_rise_atr_mult <= 0.0 else atr_a[cand_bar] * max_slope_rise_atr_mult
                        ok = rise_min <= abs(total_rise) <= rise_max
                    if ok:
                        for kb in range(b0, cand_bar + 1):
                            line_kb = new_slope * kb + new_intercept
                            hkb = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], kb)
                            buf_kb = abs(line_kb - hkb) * breakout_buffer_mult
                            if high_a[kb] > line_kb + buf_kb:
                                ok = False
                                break
                    if ok:
                        up_bar[2] = cand_bar
                        up_price[2] = up_cand_price
                        up_lag[2] = up_new_lag
                        n_up = 3
                        up_slope = new_slope
                        up_intercept = new_intercept
                        up_reg_fixed = True
                        last_up_bar = cand_bar
                    else:
                        outcome = 3 if min_met else 1
                        outcome_bar = cand_bar
                        failed = True
                        break
                else:
                    line_val = up_slope * cand_bar + up_intercept
                    hh = _wedge_line_value(n_lo, lo_slope, lo_intercept, lo_price[0], cand_bar)
                    height = abs(line_val - hh)
                    tol = height * level_tolerance_mult
                    if abs(up_cand_price - line_val) <= tol:
                        if n_up < MAXT:
                            up_bar[n_up] = cand_bar
                            up_price[n_up] = up_cand_price
                            up_lag[n_up] = up_new_lag
                            n_up += 1
                        last_up_bar = cand_bar
                    else:
                        last_up_bar = cand_bar
                        if up_cand_price > line_val:
                            outcome = 3 if min_met else 1
                            outcome_bar = cand_bar
                            failed = True
                            break
                        # 直線より下に外れただけ(浅い戻りが弱すぎる)なら
                        # 形の破綻ではないため無視して探索を続ける。

            if not min_met and (n_lo >= 2) and (n_up >= 2) and (lo_reg_fixed or up_reg_fixed):
                cf = p1_bar + (lo_lag[0] if point1_is_lo else up_lag[0])
                for pi2 in range(n_lo):
                    cb2 = lo_bar[pi2] + lo_lag[pi2]
                    if cb2 > cf:
                        cf = cb2
                for ti2 in range(n_up):
                    cb2 = up_bar[ti2] + up_lag[ti2]
                    if cb2 > cf:
                        cf = cb2
                if cf < n:
                    pc_cand = n_lo + n_up
                    if pc_cand > MAXT:
                        pc_cand = MAXT
                    ok_bars = np.zeros(pc_cand, dtype=np.int64)
                    ok_prices = np.zeros(pc_cand)
                    ok_is_up = np.zeros(pc_cand, dtype=np.bool_)
                    ri = 0
                    fi2 = 0
                    pt_c = 0
                    while ri < n_lo and fi2 < n_up and pt_c < pc_cand:
                        if lo_bar[ri] <= up_bar[fi2]:
                            ok_bars[pt_c] = lo_bar[ri]
                            ok_prices[pt_c] = lo_price[ri]
                            ok_is_up[pt_c] = False
                            ri += 1
                        else:
                            ok_bars[pt_c] = up_bar[fi2]
                            ok_prices[pt_c] = up_price[fi2]
                            ok_is_up[pt_c] = True
                            fi2 += 1
                        pt_c += 1
                    while ri < n_lo and pt_c < pc_cand:
                        ok_bars[pt_c] = lo_bar[ri]
                        ok_prices[pt_c] = lo_price[ri]
                        ok_is_up[pt_c] = False
                        ri += 1
                        pt_c += 1
                    while fi2 < n_up and pt_c < pc_cand:
                        ok_bars[pt_c] = up_bar[fi2]
                        ok_prices[pt_c] = up_price[fi2]
                        ok_is_up[pt_c] = True
                        fi2 += 1
                        pt_c += 1

                    spike_ok = True
                    for qi in range(pc_cand):
                        bar_q = ok_bars[qi]
                        is_high_q = ok_is_up[qi]
                        price_arr_q = high_a if ok_is_up[qi] else low_a
                        if qi > 0:
                            interval_l = bar_q - ok_bars[qi - 1]
                            win_l = int(round(interval_l * pivot_spike_window_ratio))
                            if not _shape_spike_ok(price_arr_q, atr_a, n, bar_q, win_l, False, is_high_q, pivot_spike_excess_atr_max):
                                spike_ok = False
                                break
                        if qi < pc_cand - 1:
                            interval_r = ok_bars[qi + 1] - bar_q
                            win_r = int(round(interval_r * pivot_spike_window_ratio))
                            if not _shape_spike_ok(price_arr_q, atr_a, n, bar_q, win_r, True, is_high_q, pivot_spike_excess_atr_max):
                                spike_ok = False
                                break

                    if not spike_ok:
                        failed = True
                        break

                    # 下値支持線・上値抵抗線がそれぞれ独立に決まるため、
                    # 最小構成が揃った瞬間に2本の直線を延長すると既に
                    # 交差していることがある(ユーザー報告、docs/
                    # pattern_spec_wedge_shape_v2.md§6参照)。構成点の
                    # どのバーでも下値直線が上値直線以上にならないことを
                    # 確認し、既に交差していればこの形は不採用にする
                    # (2026-08-19追加)。
                    lines_ok = True
                    for qi in range(pc_cand):
                        bar_q = ok_bars[qi]
                        lo_val_q = lo_slope * bar_q + lo_intercept
                        up_val_q = up_slope * bar_q + up_intercept
                        if lo_val_q >= up_val_q:
                            lines_ok = False
                            break
                    if not lines_ok:
                        failed = True
                        break

                    min_met = True
                    candidate_floor = cf
                    detected_a[cf] = True
                    formed_bar_a[cf] = cf
                    for qi in range(pc_cand):
                        point_bar_a[qi, cf] = ok_bars[qi]
                        point_price_a[qi, cf] = ok_prices[qi]
                    point_count_a[cf] = pc_cand
                    lo_slope_a[cf] = lo_slope
                    lo_intercept_a[cf] = lo_intercept
                    up_slope_a[cf] = up_slope
                    up_intercept_a[cf] = up_intercept

        if failed and outcome != 4:
            if candidate_floor == -1:
                continue

            final_floor = p1_bar + (lo_lag[0] if point1_is_lo else up_lag[0])
            for pi in range(n_lo):
                cb = lo_bar[pi] + lo_lag[pi]
                if cb > final_floor:
                    final_floor = cb
            for ti in range(n_up):
                cb = up_bar[ti] + up_lag[ti]
                if cb > final_floor:
                    final_floor = cb
            if final_floor >= n:
                continue

            ob = outcome_bar
            if ob < final_floor:
                ob = final_floor

            for idx2 in range(candidate_floor, ob + 1):
                if idx2 == candidate_floor or not detected_a[idx2]:
                    exists_a[idx2] = True
                    formed_bar_a[idx2] = candidate_floor

            formed_bar_a[ob] = ob
            pi = 0
            ti = 0
            pt_i = 0
            while pi < n_lo and ti < n_up and pt_i < MAXT:
                if lo_bar[pi] <= up_bar[ti]:
                    point_bar_a[pt_i, ob] = lo_bar[pi]
                    point_price_a[pt_i, ob] = lo_price[pi]
                    pi += 1
                else:
                    point_bar_a[pt_i, ob] = up_bar[ti]
                    point_price_a[pt_i, ob] = up_price[ti]
                    ti += 1
                pt_i += 1
            while pi < n_lo and pt_i < MAXT:
                point_bar_a[pt_i, ob] = lo_bar[pi]
                point_price_a[pt_i, ob] = lo_price[pi]
                pi += 1
                pt_i += 1
            while ti < n_up and pt_i < MAXT:
                point_bar_a[pt_i, ob] = up_bar[ti]
                point_price_a[pt_i, ob] = up_price[ti]
                ti += 1
                pt_i += 1
            point_count_a[ob] = pt_i
            lo_slope_a[ob] = lo_slope
            lo_intercept_a[ob] = lo_intercept
            up_slope_a[ob] = up_slope
            up_intercept_a[ob] = up_intercept

            if outcome == 2:
                resolve_lower_a[ob] = True
            elif outcome == 3:
                resolve_upper_a[ob] = True
            else:
                invalidated_a[ob] = True

    return (
        exists_a, detected_a, invalidated_a, resolve_lower_a, resolve_upper_a,
        formed_bar_a, point_count_a, point_bar_a, point_price_a,
        lo_slope_a, lo_intercept_a, up_slope_a, up_intercept_a,
    )


def _merge_shape_dual_seed_wedge_x(res_a: tuple, res_b: tuple) -> tuple:
    """`_merge_shape_dual_seed`のウェッジ版(状態がresolve_lower/resolve_
    upperの2つに分かれ、水準線が無くlo/up両方が回帰直線になった分だけ
    フィールドが違う。マージの考え方(バーごとにaがexistsならa)は同じ)。"""
    (exists_a, detected_a, invalidated_a, resolve_lower_a, resolve_upper_a,
     formed_bar_a, point_count_a, point_bar_a, point_price_a,
     lo_slope_a, lo_intercept_a, up_slope_a, up_intercept_a) = res_a
    (exists_b, detected_b, invalidated_b, resolve_lower_b, resolve_upper_b,
     formed_bar_b, point_count_b, point_bar_b, point_price_b,
     lo_slope_b, lo_intercept_b, up_slope_b, up_intercept_b) = res_b

    use_a = exists_a
    exists = np.where(use_a, exists_a, exists_b)
    detected = np.where(use_a, detected_a, detected_b)
    invalidated = np.where(use_a, invalidated_a, invalidated_b)
    resolve_lower = np.where(use_a, resolve_lower_a, resolve_lower_b)
    resolve_upper = np.where(use_a, resolve_upper_a, resolve_upper_b)
    formed_bar = np.where(use_a, formed_bar_a, formed_bar_b)
    point_count = np.where(use_a, point_count_a, point_count_b)
    point_bar = np.where(use_a[np.newaxis, :], point_bar_a, point_bar_b)
    point_price = np.where(use_a[np.newaxis, :], point_price_a, point_price_b)
    lo_slope = np.where(use_a, lo_slope_a, lo_slope_b)
    lo_intercept = np.where(use_a, lo_intercept_a, lo_intercept_b)
    up_slope = np.where(use_a, up_slope_a, up_slope_b)
    up_intercept = np.where(use_a, up_intercept_a, up_intercept_b)
    return (
        exists, detected, invalidated, resolve_lower, resolve_upper,
        formed_bar, point_count, point_bar, point_price,
        lo_slope, lo_intercept, up_slope, up_intercept,
    )


def _wedge_x_shape_state_v2(
    high: pd.Series, low: pd.Series, close: pd.Series,
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    pivot_spike_window_ratio: float = 0.0,
    pivot_spike_excess_atr_max: float = 0.0,
    min_slope_rise_atr_mult: float = 1.0,
    max_slope_rise_atr_mult: float = 0.0,
    max_breakout_height_ratio: float = 0.0,
) -> dict[str, Any]:
    """docs/pattern_spec_wedge_shape_v2.md参照。点1は下値側・上値側
    どちらからでも探索し(_triangle_shape_state_v2と同じ2方向探索)、
    結果を`_merge_shape_dual_seed_wedge_x`でマージする。"""
    idx_index = high.index
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_a = _atr_series(df, 14).to_numpy()

    if breakout_type not in ("close", "wick"):
        raise ValueError(f"未対応のbreakout_typeです(close/wickのみ対応): {breakout_type}")

    pivot_left_bars = max(0, pivot_left_bars)
    pivot_right_bars = max(0, pivot_right_bars)
    if pivot_left_bars == 0 and pivot_right_bars == 0:
        pivot_left_bars = 1

    both_high_flags = _pivot_flags(high, pivot_left_bars, pivot_right_bars, True).to_numpy()
    both_low_flags = _pivot_flags(low, pivot_left_bars, pivot_right_bars, False).to_numpy()
    left_high_flags = _detect_pivot_highs_left_only(high, pivot_left_bars).to_numpy()
    left_low_flags = _detect_pivot_lows_left_only(low, pivot_left_bars).to_numpy()

    res_lo_seed = _shape_state_core_wedge_x_v2(
        high_a, low_a, close_a, atr_a,
        both_low_flags, both_high_flags, left_low_flags, left_high_flags,
        True,
        int(pivot_right_bars), int(min_touch_gap_bars),
        float(level_tolerance_mult), float(breakout_buffer_mult),
        breakout_type == "close", int(max_box_bars),
        float(pivot_spike_window_ratio), float(pivot_spike_excess_atr_max),
        float(min_slope_rise_atr_mult), float(max_slope_rise_atr_mult),
        float(max_breakout_height_ratio),
    )
    res_up_seed = _shape_state_core_wedge_x_v2(
        high_a, low_a, close_a, atr_a,
        both_low_flags, both_high_flags, left_low_flags, left_high_flags,
        False,
        int(pivot_right_bars), int(min_touch_gap_bars),
        float(level_tolerance_mult), float(breakout_buffer_mult),
        breakout_type == "close", int(max_box_bars),
        float(pivot_spike_window_ratio), float(pivot_spike_excess_atr_max),
        float(min_slope_rise_atr_mult), float(max_slope_rise_atr_mult),
        float(max_breakout_height_ratio),
    )

    (
        exists_a, detected_a, invalidated_a, resolve_lower_a, resolve_upper_a,
        formed_bar_a, point_count_a, point_bar_a, point_price_a,
        lo_slope_a, lo_intercept_a, up_slope_a, up_intercept_a,
    ) = _merge_shape_dual_seed_wedge_x(res_lo_seed, res_up_seed)

    return {
        "exists": pd.Series(exists_a, index=idx_index),
        "candidate": pd.Series(detected_a, index=idx_index),
        "confirmed_lower": pd.Series(resolve_lower_a, index=idx_index),
        "confirmed_upper": pd.Series(resolve_upper_a, index=idx_index),
        "invalidated": pd.Series(invalidated_a, index=idx_index),
        "formed_bar": pd.Series(formed_bar_a, index=idx_index),
        "point_count": point_count_a,
        "point_bar": point_bar_a,
        "point_price": point_price_a,
        "lo_slope": lo_slope_a,
        "lo_intercept": lo_intercept_a,
        "up_slope": up_slope_a,
        "up_intercept": up_intercept_a,
    }


_WEDGE_X_STATE_KEYS = {
    "candidate": "candidate",
    "confirmed_lower": "confirmed_lower",
    "confirmed_upper": "confirmed_upper",
    "invalidated": "invalidated",
    "exists": "exists",
}


def rising_wedge_shape_x(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed_lower",
    pivot_left_bars: int = 3,
    pivot_right_bars: int = 3,
    min_touch_gap_bars: int = 5,
    level_tolerance_mult: float = 0.15,
    breakout_buffer_mult: float = 0.05,
    breakout_type: str = "close",
    max_box_bars: int = 500,
    pivot_spike_window_ratio: float = 0.0,
    pivot_spike_excess_atr_max: float = 0.0,
    min_slope_rise_atr_mult: float = 1.0,
    max_slope_rise_atr_mult: float = 0.0,
    max_breakout_height_ratio: float = 0.0,
) -> np.ndarray:
    """上昇ウェッジ(可変タッチ・両側回帰直線方式v2) -
    docs/pattern_spec_wedge_shape_v2.md。下値支持線・上値抵抗線の両方が
    ascending_triangle_shapeの下値支持線と全く同じ方式(起点固定+常に
    引き直し可能な回帰直線、傾きは両方とも上昇必須)で決まる点が三角
    保ち合いとの違い。状態はCandidate/Invalidatedに加えてConfirmedが
    confirmed_lower(下値支持線ブレイク)/confirmed_upper(上値抵抗線
    ブレイク)の2種類(2026-08-19、ユーザー指示で旧実装から全面書き換え)。"""
    result = _wedge_x_shape_state_v2(
        high, low, close,
        pivot_left_bars=pivot_left_bars, pivot_right_bars=pivot_right_bars,
        min_touch_gap_bars=min_touch_gap_bars, level_tolerance_mult=level_tolerance_mult,
        breakout_buffer_mult=breakout_buffer_mult, breakout_type=breakout_type,
        max_box_bars=max_box_bars,
        pivot_spike_window_ratio=pivot_spike_window_ratio,
        pivot_spike_excess_atr_max=pivot_spike_excess_atr_max,
        min_slope_rise_atr_mult=min_slope_rise_atr_mult,
        max_slope_rise_atr_mult=max_slope_rise_atr_mult,
        max_breakout_height_ratio=max_breakout_height_ratio,
    )
    key = _WEDGE_X_STATE_KEYS.get(state, "confirmed_lower")
    return result[key].to_numpy(dtype=float)




def falling_wedge_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    **kwargs: Any,
) -> np.ndarray:
    """下降ウェッジ(強気、両方の線が下降しつつ収束、上抜けで確定)。
    rising_wedge_shapeと対称の理由で安値起点(falling/fallingの形は
    安値起点でないと十分に出現しない)。"""
    return _channel_indicator(
        high, low, close, True, True, "falling", "falling", True, False,
        state, top_tolerance_mult, converge_margin, width_tol, **kwargs,
    )


def bullish_pennant_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    pole_height_min_mult: float = 3.0,
    **kwargs: Any,
) -> np.ndarray:
    """上昇ペナント(点1=旗竿の先端(高値)、小型の収束、上抜けで確定)。"""
    return _channel_indicator(
        high, low, close, False, True, "any", "any", True, False,
        state, top_tolerance_mult, converge_margin, width_tol,
        pole_height_min_mult=pole_height_min_mult, **kwargs,
    )


def bearish_pennant_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    pole_height_min_mult: float = 3.0,
    **kwargs: Any,
) -> np.ndarray:
    """下降ペナント(点1=旗竿の先端(安値)、小型の収束、下抜けで確定)。"""
    return _channel_indicator(
        high, low, close, True, False, "any", "any", True, False,
        state, top_tolerance_mult, converge_margin, width_tol,
        pole_height_min_mult=pole_height_min_mult, **kwargs,
    )


def bullish_flag_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    pole_height_min_mult: float = 3.0,
    **kwargs: Any,
) -> np.ndarray:
    """上昇フラッグ(点1=旗竿の先端(高値)、平行かつ下向きの保ち合い、
    上抜けで確定)。"""
    return _channel_indicator(
        high, low, close, False, True, "falling", "falling", False, True,
        state, top_tolerance_mult, converge_margin, width_tol,
        pole_height_min_mult=pole_height_min_mult, **kwargs,
    )


def bearish_flag_shape(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    top_tolerance_mult: float = 0.25,
    converge_margin: float = 0.1,
    width_tol: float = 0.3,
    pole_height_min_mult: float = 3.0,
    **kwargs: Any,
) -> np.ndarray:
    """下降フラッグ(点1=旗竿の先端(安値)、平行かつ上向きの保ち合い、
    下抜けで確定)。"""
    return _channel_indicator(
        high, low, close, True, False, "rising", "rising", False, True,
        state, top_tolerance_mult, converge_margin, width_tol,
        pole_height_min_mult=pole_height_min_mult, **kwargs,
    )


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# チャートパターン共通: pattern_id の組み立て(共通管理仕様7.1)。
#
# 「パターン種類 + 全構成点のバー位置」を _ でつないだ文字列を一意IDとする。
# 構成点が1つでも違えば別ID、全部同じなら同じパターンとして扱う(何度検出
# 処理を通っても再登録しない)。点の数を固定していないので、ダブル(3点)だけ
# でなく今後追加するヘッド&ショルダーズ(5点)・トライアングル・ウェッジ・
# フラッグ等にもそのまま使える。
#
# 例: _make_pattern_id("double_top", (100, 120, 140)) -> "double_top_100_120_140"
# ---------------------------------------------------------------------------

def _make_dedup_key(pattern_type: str, point_bars, newest_first: bool) -> str:
    """重複判定に使うキー(共通管理仕様①)。**最新の構成点は除く。**

    ZigZagの最新ピボットは右側の確定を待たずに置き換えられる = 後から動く。
    全構成点で同一性を見ると、同じ形が「最新点の位置だけ違う別パターン」として
    何度も登録されてしまう(ユーザー報告:「点6だけ位置が違うから2つのパターンと
    認識してる」。USDJPY15分足のトリプルトップでは、検出された形の48%がこの
    重複だった)。

    参考元も同じ考え方を持っている:
      - トリプルトップ系(RRCP)… index 0(最新)を比較から除外
        (docs/pattern_spec_reversal_chart_patterns_recursive.md 5.5)
      - フラッグ/ペナント・13種  … 先頭 N-1 点だけを比較(=最後の点を除外)
        (docs/pattern_spec_flags_pennants.md 6.0)
    推進波だけは参考元の規則が別の形(終点のバーだけで判定)なので、
    StrategyXでは他と揃えてこの規則を適用する(仕様書7.1に独自拡張と明記)。

    newest_first=True なら先頭が最新(RRCP)、False なら末尾が最新(その他)。
    出力する pattern_id 自体は全構成点を含んだままなので、識別性は落ちない。
    """
    bars = list(point_bars)
    rest = bars[1:] if newest_first else bars[:-1]
    return _make_pattern_id(pattern_type, rest)


def _make_pattern_id(pattern_type: str, point_bars) -> str:
    return pattern_type + "".join(f"_{int(b)}" for b in point_bars)


# ---------------------------------------------------------------------------
# ダブルトップ / ダブルボトム (ZigZag方式) - B方式実装。
#
# 検出仕様は docs/pattern_spec_double_top_bottom_zigzag.md (v2.1) に文章・
# 数式・条件として全て書き出してあり、この実装はその仕様書だけを入力として
# 書いている(参考元のPine Scriptコードを直接移植したものではない)。参考元は
# Trendoscope系「Double Top/Bottom - Ultimate (OS)」(Pine v4, MPL-2.0,
# (c) HeWhoMustNotBeNamed)。仕様の根拠・比較演算子の細部・参考元との差異は
# 全て仕様書側に書いてあるので、ロジックを追うときはまずそちらを読むこと。
#
# アルゴリズムの骨格(詳細は仕様書4〜7章):
#   1. 各バーで「直近length本(自分を含む)の最高値/最安値そのものか」を見る、
#      右側確認なしのlookback型ピボット判定(仕様書4.1)。
#   2. ピボットが出るたびにZigZag配列(先頭=最新、最大10件)を更新する。方向が
#      変わったら新規追加、同方向でより極端なら先頭を置換(仕様書4.3)。追加/
#      置換のたびに、ひとつ前の同方向ピボットと比べてHH(+2)/LH(+1)/LL(-2)/
#      HL(-1)に分類する(仕様書4.4)。
#   3. 配列が4件以上たまったら index1/2/3 を P3/P2/P1 として読み、構造条件
#      (DTならP1=HH・P2=谷型・P3=LH)と価格形状フィルター
#      (ratio = |P3-P1|×100/(|P3-P1|+|P3-P2|) < max_risk_ratio)を満たせば
#      Candidate成立(仕様書5章)。
#   4. Candidate成立後は毎バー、安値/高値がP2(ネック)またはP1をヒゲ込みで
#      クロスしたかを見てConfirmed/Invalidatedを決める。同一バーで両方成立
#      したらConfirmed優先。期限・余白・リテストは無し(仕様書6章)。
#
# StrategyX共通の管理仕様(仕様書7章)をここで適用している - パターンごとに
# 一意ID(種類+P1/P2/P3のバー位置)を振り、1パターンにつきConfirmed/Invalidated
# を一度だけ発生させ、未決着のパターンは複数同時に監視し続ける。参考元は
# 「最新1件だけを保持し、決着後も同じ水準で判定を続ける」単一スロット方式
# だったため、この点だけ意図的に異なる(仕様書7.7の差異一覧参照)。
#
# 出力は「1バー1個のBoolean」ではなく「1イベント1件のレコード」を正とする
# (仕様書8章、2026-08-12にユーザー指摘で修正)。同一バーで2件以上のパターンが
# 決着し得るため、Booleanだけだとイベント数も各パターンの3点情報も落ちる。
# Booleanの3系列は条件式(StrategyXのindicatorインターフェース)が必要と
# するので残してあるが、欠落のない情報は返り値の "events" 側にある。
# ---------------------------------------------------------------------------

# ZigZag配列の保持件数(仕様書4.3、参考元のmax_array_size)。Candidate判定は
# index1〜3しか読まないので4件あれば足りるが、参考元の分類(4.4)が「ひとつ前の
# 同方向ピボット」を index1/2 経由で参照するため、参考元と同じ10件にしてある。
_ZZ_DTDB_CAPACITY = 10

# 同時に監視できる未決着パターンの上限(仕様書7.4)。参考元には無い概念で、
# StrategyX側が複数同時保持するために必要になった実装上の枠。溢れた回数は
# 戻り値で返し、呼び出し元(_zigzag_dtdb_state)が0でなければ例外にする -
# 黙って検出を取りこぼさないため。
_ZZ_DTDB_SLOT_CAPACITY = 512

# パラメータの有効範囲(仕様書2章)。UI側のmin/max指定だけに頼らず、検出関数へ
# 直接不正値が渡された場合もこの範囲へ丸めてから計算する(保存済みJSON経由な
# ど、UIを介さない経路がありうるため)。stepはUI入力の刻み幅としてのみ扱い、
# エンジンは範囲内の任意の値を受け付ける(仕様書2章の注記参照)。
_ZZ_DTDB_LENGTH_MIN = 5
_ZZ_DTDB_MAX_RISK_RATIO_MIN = 5.0
_ZZ_DTDB_MAX_RISK_RATIO_MAX = 100.0

# イベント記録の状態コード(核内では文字列を扱えないため整数で持ち、
# _zigzag_dtdb_state側で文字列へ戻す)。
_ZZ_DTDB_STATUS_NAMES = ("candidate", "confirmed", "invalidated")


@njit(cache=True)
def _zigzag_dtdb_core(high_a, low_a, roll_high, roll_low, max_risk_ratio, slot_cap, event_cap):
    n = high_a.shape[0]

    # --- ZigZag配列(index0が最新、仕様書4.3) ---
    zz_val = np.zeros(_ZZ_DTDB_CAPACITY)
    zz_bar = np.zeros(_ZZ_DTDB_CAPACITY, dtype=np.int64)
    zz_sign = np.zeros(_ZZ_DTDB_CAPACITY, dtype=np.int64)
    zz_n = 0

    dir_state = 0
    first_bar_done = False

    # --- StrategyXのindicatorインターフェース向けのBoolean系列。同一バーに
    #     複数イベントが乗ると件数が潰れるので、欠落のない情報は下のイベント
    #     配列側を正とする(仕様書8章)。 ---
    dt_candidate = np.zeros(n, dtype=np.bool_)
    dt_confirmed = np.zeros(n, dtype=np.bool_)
    dt_invalidated = np.zeros(n, dtype=np.bool_)
    db_candidate = np.zeros(n, dtype=np.bool_)
    db_confirmed = np.zeros(n, dtype=np.bool_)
    db_invalidated = np.zeros(n, dtype=np.bool_)

    # --- イベント記録(1イベント1行、同一バーに何件でも積める) ---
    ev_type = np.zeros(event_cap, dtype=np.int64)     # +1=double_top, -1=double_bottom
    ev_status = np.zeros(event_cap, dtype=np.int64)   # 0=candidate, 1=confirmed, 2=invalidated
    ev_bar = np.zeros(event_cap, dtype=np.int64)
    ev_p1_bar = np.zeros(event_cap, dtype=np.int64)
    ev_p1_price = np.zeros(event_cap)
    ev_p2_bar = np.zeros(event_cap, dtype=np.int64)
    ev_p2_price = np.zeros(event_cap)
    ev_p3_bar = np.zeros(event_cap, dtype=np.int64)
    ev_p3_price = np.zeros(event_cap)
    ev_ratio = np.zeros(event_cap)
    n_events = 0
    event_overflow = 0

    # --- 未決着パターンのスロット(仕様書7.4) ---
    s_type = np.zeros(slot_cap, dtype=np.int64)   # +1=ダブルトップ, -1=ダブルボトム
    s_p1_bar = np.zeros(slot_cap, dtype=np.int64)
    s_p1_price = np.zeros(slot_cap)
    s_p2_bar = np.zeros(slot_cap, dtype=np.int64)
    s_p2_price = np.zeros(slot_cap)
    s_p3_bar = np.zeros(slot_cap, dtype=np.int64)
    s_p3_price = np.zeros(slot_cap)
    s_ratio = np.zeros(slot_cap)
    s_live = np.zeros(slot_cap, dtype=np.bool_)
    n_live = 0
    slot_overflow = 0
    max_live_seen = 0

    # 直前に登録したpattern_id(仕様書7.1の重複登録防止)。index1〜3の3点は
    # 新しいピボットが「追加」されるたびに1つずつ後ろへずれる一方通行なので、
    # 一度離れた組み合わせが再び index1〜3 に戻ることはない - よって種類ごとに
    # 「最後に登録した3点」だけ覚えておけば重複登録は完全に防げる。
    last_dt_b1 = -1
    last_dt_b2 = -1
    last_dt_b3 = -1
    last_db_b1 = -1
    last_db_b2 = -1
    last_db_b3 = -1

    for i in range(n):
        # ===== 仕様書4.1: lookback型ピボット候補 =====
        rh = roll_high[i]
        rl = roll_low[i]
        ph_valid = (not np.isnan(rh)) and high_a[i] == rh
        pl_valid = (not np.isnan(rl)) and low_a[i] == rl

        # ===== 仕様書4.2: 方向 =====
        prev_dir = dir_state
        new_dir = prev_dir
        if ph_valid and not pl_valid:
            new_dir = 1
        elif pl_valid and not ph_valid:
            new_dir = -1
        # 参考元のchange(dir)は初回バーでna(=偽)になるので、それに合わせる。
        dirchanged = first_bar_done and (new_dir != prev_dir)
        dir_state = new_dir
        first_bar_done = True

        # ===== 仕様書4.3/4.4: ZigZag配列の追加・置換と分類 =====
        if ph_valid or pl_valid:
            value = high_a[i] if new_dir == 1 else low_a[i]

            if zz_n == 0 or dirchanged:
                # 新規追加 - 分類の比較対象は挿入"前"のindex1(直前のindex0は
                # 反対方向なので、index1がひとつ前の同方向ピボットになる)。
                if zz_n >= 2:
                    mult = 2 if (new_dir * value > new_dir * zz_val[1]) else 1
                else:
                    mult = 1
                shift_from = zz_n if zz_n < _ZZ_DTDB_CAPACITY else _ZZ_DTDB_CAPACITY - 1
                for s in range(shift_from, 0, -1):
                    zz_val[s] = zz_val[s - 1]
                    zz_bar[s] = zz_bar[s - 1]
                    zz_sign[s] = zz_sign[s - 1]
                zz_val[0] = value
                zz_bar[0] = i
                zz_sign[0] = new_dir * mult
                if zz_n < _ZZ_DTDB_CAPACITY:
                    zz_n += 1
            else:
                is_more_extreme = (
                    (new_dir == 1 and value > zz_val[0])
                    or (new_dir == -1 and value < zz_val[0])
                )
                if is_more_extreme:
                    # 置換 - 参考元は「先頭を除去してから新規追加」なので、
                    # 分類の比較対象は除去"後"のindex1 = 除去前のindex2。
                    if zz_n - 1 >= 2:
                        mult = 2 if (new_dir * value > new_dir * zz_val[2]) else 1
                    else:
                        mult = 1
                    zz_val[0] = value
                    zz_bar[0] = i
                    zz_sign[0] = new_dir * mult

        # ===== 仕様書5章: Candidate判定 =====
        if zz_n >= 4:
            p3_price = zz_val[1]
            p3_bar = zz_bar[1]
            p3_sign = zz_sign[1]
            p2_price = zz_val[2]
            p2_bar = zz_bar[2]
            p2_sign = zz_sign[2]
            p1_price = zz_val[3]
            p1_bar = zz_bar[3]
            p1_sign = zz_sign[3]

            is_dt = (p1_sign == 2) and (p2_sign < 0) and (p3_sign == 1)
            is_db = (p1_sign == -2) and (p2_sign > 0) and (p3_sign == -1)

            if is_dt or is_db:
                risk = abs(p3_price - p1_price)
                reward = abs(p3_price - p2_price)
                total = risk + reward
                # total==0(3点が完全同値)は参考元でratioがnaになり閾値比較が
                # 偽になるため、Candidateを成立させない(仕様書5.1)。
                if total > 0.0:
                    ratio = risk * 100.0 / total
                    if ratio < max_risk_ratio:
                        if is_dt:
                            already = (p1_bar == last_dt_b1) and (p2_bar == last_dt_b2) and (p3_bar == last_dt_b3)
                        else:
                            already = (p1_bar == last_db_b1) and (p2_bar == last_db_b2) and (p3_bar == last_db_b3)
                        if not already:
                            if n_live < slot_cap:
                                s = n_live
                                s_type[s] = 1 if is_dt else -1
                                s_p1_bar[s] = p1_bar
                                s_p1_price[s] = p1_price
                                s_p2_bar[s] = p2_bar
                                s_p2_price[s] = p2_price
                                s_p3_bar[s] = p3_bar
                                s_p3_price[s] = p3_price
                                s_ratio[s] = ratio
                                s_live[s] = True
                                n_live += 1
                                if n_live > max_live_seen:
                                    max_live_seen = n_live
                                if is_dt:
                                    dt_candidate[i] = True
                                else:
                                    db_candidate[i] = True
                                if n_events < event_cap:
                                    ev_type[n_events] = 1 if is_dt else -1
                                    ev_status[n_events] = 0
                                    ev_bar[n_events] = i
                                    ev_p1_bar[n_events] = p1_bar
                                    ev_p1_price[n_events] = p1_price
                                    ev_p2_bar[n_events] = p2_bar
                                    ev_p2_price[n_events] = p2_price
                                    ev_p3_bar[n_events] = p3_bar
                                    ev_p3_price[n_events] = p3_price
                                    ev_ratio[n_events] = ratio
                                    n_events += 1
                                else:
                                    event_overflow += 1
                            else:
                                slot_overflow += 1
                            if is_dt:
                                last_dt_b1 = p1_bar
                                last_dt_b2 = p2_bar
                                last_dt_b3 = p3_bar
                            else:
                                last_db_b1 = p1_bar
                                last_db_b2 = p2_bar
                                last_db_b3 = p3_bar

        # ===== 仕様書6章: Confirmed / Invalidated判定 =====
        # Candidate成立したそのバーからの判定に含める(仕様書6.3)。前バーとの
        # 比較が要るので i>0 のバーだけ見る。同一バーで複数のパターンが決着
        # したら、その全件をイベントとして積む(Boolean側は潰れる)。
        if i > 0:
            for s in range(n_live):
                if not s_live[s]:
                    continue
                resolved_status = -1
                if s_type[s] == 1:
                    # ダブルトップ: 安値がネックを下抜け→Confirmed、
                    # 高値が第1山を上抜け→Invalidated(Confirmed優先)。
                    if low_a[i] < s_p2_price[s] and low_a[i - 1] >= s_p2_price[s]:
                        dt_confirmed[i] = True
                        resolved_status = 1
                    elif high_a[i] > s_p1_price[s] and high_a[i - 1] <= s_p1_price[s]:
                        dt_invalidated[i] = True
                        resolved_status = 2
                else:
                    if high_a[i] > s_p2_price[s] and high_a[i - 1] <= s_p2_price[s]:
                        db_confirmed[i] = True
                        resolved_status = 1
                    elif low_a[i] < s_p1_price[s] and low_a[i - 1] >= s_p1_price[s]:
                        db_invalidated[i] = True
                        resolved_status = 2

                if resolved_status >= 0:
                    s_live[s] = False
                    if n_events < event_cap:
                        ev_type[n_events] = s_type[s]
                        ev_status[n_events] = resolved_status
                        ev_bar[n_events] = i
                        ev_p1_bar[n_events] = s_p1_bar[s]
                        ev_p1_price[n_events] = s_p1_price[s]
                        ev_p2_bar[n_events] = s_p2_bar[s]
                        ev_p2_price[n_events] = s_p2_price[s]
                        ev_p3_bar[n_events] = s_p3_bar[s]
                        ev_p3_price[n_events] = s_p3_price[s]
                        ev_ratio[n_events] = s_ratio[s]
                        n_events += 1
                    else:
                        event_overflow += 1

            # 決着したスロットを詰めて空きを作る。
            w = 0
            for s in range(n_live):
                if s_live[s]:
                    if w != s:
                        s_type[w] = s_type[s]
                        s_p1_bar[w] = s_p1_bar[s]
                        s_p1_price[w] = s_p1_price[s]
                        s_p2_bar[w] = s_p2_bar[s]
                        s_p2_price[w] = s_p2_price[s]
                        s_p3_bar[w] = s_p3_bar[s]
                        s_p3_price[w] = s_p3_price[s]
                        s_ratio[w] = s_ratio[s]
                        s_live[w] = True
                    w += 1
            for s in range(w, n_live):
                s_live[s] = False
            n_live = w

    return (
        dt_candidate, dt_confirmed, dt_invalidated,
        db_candidate, db_confirmed, db_invalidated,
        ev_type, ev_status, ev_bar,
        ev_p1_bar, ev_p1_price, ev_p2_bar, ev_p2_price, ev_p3_bar, ev_p3_price, ev_ratio,
        n_events, event_overflow, slot_overflow, max_live_seen,
    )


def _zigzag_dtdb_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    length: int = 10,
    max_risk_ratio: float = 30.0,
) -> dict[str, Any]:
    """モジュール冒頭のコメントとdocs/pattern_spec_double_top_bottom_zigzag.md
    参照。ダブルトップとダブルボトムは共通の1本のZigZag(高値側/安値側の反転点を
    交互に積む配列)から同時に検出されるため、両方をまとめて1回で計算する。

    戻り値:
      "double_top" / "double_bottom" - それぞれ candidate/confirmed/invalidated
        のBoolean系列(StrategyXのindicatorインターフェース用)。同一バーに
        複数イベントが乗ると件数が潰れるので、件数や各パターンの3点が要る
        用途ではこちらではなく "events" を読むこと。
      "events" - 検出した全イベントを時系列順に1件1レコードで並べたリスト。
        pattern_id / pattern_type / status / event_bar / p1〜p3のバーと価格 /
        ratio を持つ(仕様書8章)。同一バーで2件以上決着しても全件残る。
    """
    n = len(high)
    idx_index = high.index
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)

    # 仕様書2章の有効範囲をエンジン側でも保証する(UI側のmin/max指定だけに
    # 頼らない - 保存済みJSON経由などUIを介さずに呼ばれる経路があるため)。
    length = int(length)
    if length < _ZZ_DTDB_LENGTH_MIN:
        length = _ZZ_DTDB_LENGTH_MIN
    max_risk_ratio = float(max_risk_ratio)
    if max_risk_ratio < _ZZ_DTDB_MAX_RISK_RATIO_MIN:
        max_risk_ratio = _ZZ_DTDB_MAX_RISK_RATIO_MIN
    elif max_risk_ratio > _ZZ_DTDB_MAX_RISK_RATIO_MAX:
        max_risk_ratio = _ZZ_DTDB_MAX_RISK_RATIO_MAX

    # 仕様書4.1のlookback窓。min_periods=lengthで、窓が満たない先頭は判定しない
    # (参考元のhighestbars/lowestbarsがnaを返す区間に対応)。
    roll_high = pd.Series(high_a).rolling(window=length, min_periods=length).max().to_numpy()
    roll_low = pd.Series(low_a).rolling(window=length, min_periods=length).min().to_numpy()

    # イベント配列は事前確保が要る(njit内では伸ばせない)。Candidateは1バーに
    # 最大1件・各パターンの決着も最大1件なので 2n+16 あれば絶対に足りるが、
    # 実測では数万件程度に収まるので、まず控えめに取って足りなければ広げて
    # 計算し直す(黙って件数を減らさない)。
    hard_bound = 2 * n + 16
    event_cap = min(hard_bound, max(4096, n // 8))
    while True:
        (
            dt_candidate_a, dt_confirmed_a, dt_invalidated_a,
            db_candidate_a, db_confirmed_a, db_invalidated_a,
            ev_type, ev_status, ev_bar,
            ev_p1_bar, ev_p1_price, ev_p2_bar, ev_p2_price, ev_p3_bar, ev_p3_price, ev_ratio,
            n_events, event_overflow, slot_overflow, max_live_seen,
        ) = _zigzag_dtdb_core(
            high_a, low_a, roll_high, roll_low, max_risk_ratio, _ZZ_DTDB_SLOT_CAPACITY, event_cap
        )
        if event_overflow == 0:
            break
        event_cap = min(hard_bound, event_cap * 4)

    if slot_overflow:
        # 同時監視スロットが足りず検出を取りこぼした場合、黙って件数が減った
        # 結果を返さずにここで落とす(_ZZ_DTDB_SLOT_CAPACITYのコメント参照)。
        raise RuntimeError(
            f"ダブルトップ/ボトム(ZigZag方式)の同時監視スロットが不足しました"
            f"(上限{_ZZ_DTDB_SLOT_CAPACITY}件、取りこぼし{slot_overflow}件)。"
            f"engine/chart_patterns.py::_ZZ_DTDB_SLOT_CAPACITYを増やしてください。"
        )

    events: list[dict] = []
    for k in range(n_events):
        pattern_type = "double_top" if ev_type[k] > 0 else "double_bottom"
        p1_bar = int(ev_p1_bar[k])
        p2_bar = int(ev_p2_bar[k])
        p3_bar = int(ev_p3_bar[k])
        events.append({
            "pattern_id": _make_pattern_id(pattern_type, (p1_bar, p2_bar, p3_bar)),
            "pattern_type": pattern_type,
            "status": _ZZ_DTDB_STATUS_NAMES[int(ev_status[k])],
            "event_bar": int(ev_bar[k]),
            "p1_bar": p1_bar,
            "p1_price": float(ev_p1_price[k]),
            "p2_bar": p2_bar,
            "p2_price": float(ev_p2_price[k]),
            "p3_bar": p3_bar,
            "p3_price": float(ev_p3_price[k]),
            "ratio": float(ev_ratio[k]),
        })

    return {
        "double_top": {
            "candidate": pd.Series(dt_candidate_a, index=idx_index),
            "confirmed": pd.Series(dt_confirmed_a, index=idx_index),
            "invalidated": pd.Series(dt_invalidated_a, index=idx_index),
        },
        "double_bottom": {
            "candidate": pd.Series(db_candidate_a, index=idx_index),
            "confirmed": pd.Series(db_confirmed_a, index=idx_index),
            "invalidated": pd.Series(db_invalidated_a, index=idx_index),
        },
        "events": events,
        "max_concurrent_patterns": int(max_live_seen),
    }


_ZIGZAG_DTDB_STATE_KEYS = {
    "candidate": "candidate",
    "confirmed": "confirmed",
    "invalidated": "invalidated",
}


def double_top_zigzag(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    length: int = 10,
    max_risk_ratio: float = 30.0,
    **p,
) -> np.ndarray:
    """ダブルトップ(ZigZag方式) - モジュール冒頭のコメントと
    docs/pattern_spec_double_top_bottom_zigzag.md 参照。Candidate/Confirmed/
    Invalidatedの3状態をstateパラメータで選べる。既存のdouble_top_shape
    (形状判定版)とは完全に独立した実装。

    条件式が要求するBoolean系列を返すため、同一バーに複数イベントが乗った
    場合は1つに潰れる。件数や各パターンの3点が要る用途では
    _zigzag_dtdb_state(...)["events"] を読むこと。"""
    result = _zigzag_dtdb_state(high, low, close, length, max_risk_ratio)["double_top"]
    key = _ZIGZAG_DTDB_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


def double_bottom_zigzag(
    high: pd.Series, low: pd.Series, close: pd.Series,
    state: str = "confirmed",
    length: int = 10,
    max_risk_ratio: float = 30.0,
    **p,
) -> np.ndarray:
    """ダブルボトム(ZigZag方式) - モジュール冒頭のコメントと
    docs/pattern_spec_double_top_bottom_zigzag.md 参照。Candidate/Confirmed/
    Invalidatedの3状態をstateパラメータで選べる。既存のdouble_bottom_shape
    (形状判定版)とは完全に独立した実装。

    Boolean系列の制約はdouble_top_zigzagのdocstring参照。"""
    result = _zigzag_dtdb_state(high, low, close, length, max_risk_ratio)["double_bottom"]
    key = _ZIGZAG_DTDB_STATE_KEYS.get(state, "confirmed")
    return result[key].to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# トリプルトップ/ボトム・カップ&ハンドル・ヘッド&ショルダーズ - B方式実装。
#
# 検出仕様は docs/pattern_spec_reversal_chart_patterns_recursive.md (v1.0) に
# 文章・数式・条件として全て書き出してあり、この実装はその仕様書だけを入力と
# して書いている(参考元のPine Scriptコードを直接移植したものではない)。
# 参考元は Trendoscope系「Recursive Reversal Chart Patterns [Trendoscope®]」
# (Pine v6, CC BY-NC-SA 4.0, (c) Trendoscope Pty Ltd)。参考元スクリプト単体には
# 判定条件が無く、import先の reversalchartpatterns/2 と Zigzag/11 まで辿って
# 仕様化した(依存追跡の記録は仕様書0章)。
#
# 上のダブルトップ/ボトム(ZigZag方式、_zigzag_dtdb_state)とは出典もZigZagの
# 作り方も別物なので混同しないこと。あちらはMPL-2.0の別スクリプト由来。
#
# アルゴリズムの骨格(詳細は仕様書3〜6章):
#   1. 各バーで直近zigzag_length本の最高値/最安値を見る、右側確認なしの
#      lookback型ピボット判定でレベル0のZigZagを更新する(仕様書3.1/3.2)。
#      置換①・新規追加②・強制追加③の3分岐があり、②はPineの演算子優先順位
#      由来の非対称性をそのまま再現している。
#   2. ピボットを積むたびに、直前2つと比べて ratio(直前の波に対する今の波の
#      値幅比、小数第3位で丸め)と dir(±2=新記録 / ±1=非新記録)を計算する
#      (仕様書3.3)。判定はこの ratio だけで行う。
#   3. 新しいピボットが出たバーで、レベル0から順に上位レベルへ登りながら走査
#      する。上位レベルは nextlevel(仕様書4章)で「±2のピボットだけを昇格
#      させ、±1は保留に貯める」規則で作る。
#   4. 各レベルの先頭4ピボットの ratio(r1〜r4)を見て、Tap/Shoulder/Headの
#      組み合わせでトリプル・カップ&ハンドル・ヘッド&ショルダーズを判別する
#      (仕様書5章)。上下は一番古いピボットの方向で決まる。
#   5. Confirmed/Invalidated は参考元に存在しない - 2026-08-12のユーザー決定で
#      全チャートパターンの状態モデルを揃えるため、ダブルトップと同じ
#      「ネックラインをヒゲでクロス」方式を独自拡張として被せている
#      (仕様書6章)。判定水準は参考元自身が計算しているエントリー価格
#      (= 新しい方から2番目のピボット)を使い、独自に発明していない。
#
# 実装の分け方: 参考元の重複判定(直近10件との比較)は共通管理仕様の
# pattern_id に置き換えるが、pattern_idの集合をnjit内で持つのは無理があるので
#   ① njitで走査して「生の検出ヒット」を全部吐く(_rrcp_scan_core)
#   ② Python側でpattern_idの集合を使って重複を落とす
#   ③ njitで各パターンのConfirmed/Invalidatedを追跡する(_rrcp_resolve_core)
# の3段構成にしてある。
# ---------------------------------------------------------------------------

# 走査する最大レベル数。nextlevelは「上位のピボット数 >= 元のピボット数 なら
# 空にする」で必ず縮むので、depth(既定50)からは高々50段だが、実測では10段も
# 行かない。溢れた回数は返り値で報告する。
_RRCP_MAX_LEVELS = 32

# パターン種類コード(参考元のpatternTypeと合わせてある)。1=ダブルタップは
# 別系統の実装があるため対象外(仕様書5.3)。
_RRCP_TYPE_TRIPLE = 2
_RRCP_TYPE_CUP = 3
_RRCP_TYPE_HS = 4

# パターン種類コードと方向(+1=ボトム系/強気, -1=トップ系/弱気)から名前を引く
# (仕様書5.4)。
_RRCP_PATTERN_NAMES = {
    (_RRCP_TYPE_TRIPLE, -1): "triple_top",
    (_RRCP_TYPE_TRIPLE, 1): "triple_bottom",
    (_RRCP_TYPE_CUP, -1): "inverted_cup_and_handle",
    (_RRCP_TYPE_CUP, 1): "cup_and_handle",
    (_RRCP_TYPE_HS, -1): "head_and_shoulders",
    (_RRCP_TYPE_HS, 1): "inverse_head_and_shoulders",
}

# 各パターンの構成点数(仕様書5.6)。判定自体は常に先頭4点のratioだけで行い、
# 6点使うのは構成点の記録のみ。
_RRCP_POINT_COUNTS = {
    _RRCP_TYPE_TRIPLE: 6,
    _RRCP_TYPE_CUP: 4,
    _RRCP_TYPE_HS: 6,
}

_RRCP_STATUS_NAMES = ("candidate", "confirmed", "invalidated")

# パラメータの有効範囲(仕様書1章)。UI側の指定だけに頼らず検出器内部でも保証する。
_RRCP_ZIGZAG_LENGTH_MIN = 3
_RRCP_DEPTH_MAX = 500
_RRCP_ERROR_PERCENT_MIN = 0.0
_RRCP_ERROR_PERCENT_MAX = 50.0
_RRCP_SHOULDER_START_MIN = 0.1
_RRCP_SHOULDER_START_MAX = 1.0
_RRCP_SHOULDER_END_MIN = 0.5
_RRCP_SHOULDER_END_MAX = 1.0


@njit(cache=True)
def _rrcp_push_pivot(price, bar, dirs, ratios, n, cap, new_price, new_bar, new_sign):
    """ZigZag配列(index0が最新)の先頭へピボットを1つ積み、仕様書3.3の
    ratio と dir を計算する。戻り値は積んだ後のピボット数。

    ratio は「直前の1本の波の値幅」に対する「今の1本の波の値幅」の比を
    小数第3位で丸めたもの。分母が0のときは参考元でnaになり以降の閾値比較が
    全て偽になるため、NaNを入れて同じ挙動にする。"""
    out_dir = new_sign
    out_ratio = 1.0
    if n >= 2:
        last_price = price[0]
        llast_price = price[1]
        if new_sign * new_price > new_sign * llast_price:
            out_dir = new_sign * 2
        denom = abs(llast_price - last_price)
        if denom > 0.0:
            # 参考元のmath.roundは0から遠い側へ丸める。ratioは常に0以上なので
            # floor(x*1000+0.5)/1000 で一致する(Pythonの組み込みroundは
            # 偶数丸めなので使わない)。
            out_ratio = np.floor(abs(last_price - new_price) / denom * 1000.0 + 0.5) / 1000.0
        else:
            out_ratio = np.nan
    m = n if n < cap else cap - 1
    for s in range(m, 0, -1):
        price[s] = price[s - 1]
        bar[s] = bar[s - 1]
        dirs[s] = dirs[s - 1]
        ratios[s] = ratios[s - 1]
    price[0] = new_price
    bar[0] = new_bar
    dirs[0] = out_dir
    ratios[0] = out_ratio
    if n < cap:
        n += 1
    return n


@njit(cache=True)
def _rrcp_build_next_level(sp, sb, sd, sn, dp, db, dd, dr, cap):
    """仕様書4章。レベルnのピボット列(sp/sb/sd, sn件)から、レベルn+1の
    ピボット列(dp/db/dd/dr)を作る。戻り値は (上位のピボット数, 方向不整合の回数)。

    方向不整合は参考元では実行時エラーになる条件で、本来起きないはず。
    起きた回数を数えて呼び出し元へ返し、0でなければ実装ミスとして検出できる
    ようにしてある(不整合時はその追加を見送る)。"""
    dn = 0
    mismatch = 0
    have_bull = False
    bull_p = 0.0
    bull_b = 0
    have_bear = False
    bear_p = 0.0
    bear_b = 0

    for idx in range(sn - 1, -1, -1):   # 古い順
        p_price = sp[idx]
        p_bar = sb[idx]
        p_dir = sd[idx]
        nd = 1 if p_dir > 0 else -1
        adir = p_dir if p_dir >= 0 else -p_dir

        if dn > 0:
            last_d = 1 if dd[0] > 0 else -1
            last_p = dp[0]
            if adir == 2:
                skip = False
                if last_d == nd:
                    if p_dir * last_p < p_dir * p_price:
                        # 同方向でより極端 → 先頭を取り除いてから置き換える
                        for s in range(0, dn - 1):
                            dp[s] = dp[s + 1]
                            db[s] = db[s + 1]
                            dd[s] = dd[s + 1]
                            dr[s] = dr[s + 1]
                        dn -= 1
                    else:
                        # 反対側の保留があれば先に積む。無ければこのピボットは捨てる
                        if nd > 0:
                            if have_bear:
                                if (1 if dd[0] > 0 else -1) == -1:
                                    mismatch += 1
                                else:
                                    dn = _rrcp_push_pivot(dp, db, dd, dr, dn, cap, bear_p, bear_b, -1)
                            else:
                                skip = True
                        else:
                            if have_bull:
                                if (1 if dd[0] > 0 else -1) == 1:
                                    mismatch += 1
                                else:
                                    dn = _rrcp_push_pivot(dp, db, dd, dr, dn, cap, bull_p, bull_b, 1)
                            else:
                                skip = True
                else:
                    # 同方向の保留と反対方向の保留が両方あり、保留の方がより
                    # 極端なときだけ、2つまとめて先に積む
                    if nd > 0:
                        hf = have_bull
                        fp = bull_p
                        fb = bull_b
                        hs = have_bear
                        sp2 = bear_p
                        sb2 = bear_b
                    else:
                        hf = have_bear
                        fp = bear_p
                        fb = bear_b
                        hs = have_bull
                        sp2 = bull_p
                        sb2 = bull_b
                    if hf and hs:
                        if nd * fp > nd * p_price:
                            dn = _rrcp_push_pivot(dp, db, dd, dr, dn, cap, fp, fb, nd)
                            dn = _rrcp_push_pivot(dp, db, dd, dr, dn, cap, sp2, sb2, -nd)
                if not skip:
                    if dn > 0 and (1 if dd[0] > 0 else -1) == nd:
                        mismatch += 1
                    else:
                        dn = _rrcp_push_pivot(dp, db, dd, dr, dn, cap, p_price, p_bar, nd)
                    have_bull = False
                    have_bear = False
            else:
                # |dir|==1 は上位へ昇格させず保留に貯める。同方向の保留が既に
                # あれば、より極端な方を残す。
                if nd > 0:
                    if have_bull:
                        if p_price * p_dir > bull_p * p_dir:
                            bull_p = p_price
                            bull_b = p_bar
                    else:
                        have_bull = True
                        bull_p = p_price
                        bull_b = p_bar
                else:
                    if have_bear:
                        if p_price * p_dir > bear_p * p_dir:
                            bear_p = p_price
                            bear_b = p_bar
                    else:
                        have_bear = True
                        bear_p = p_price
                        bear_b = p_bar
        else:
            if adir == 2:
                dn = _rrcp_push_pivot(dp, db, dd, dr, dn, cap, p_price, p_bar, nd)

    # それ以上細かくならないなら打ち切る(仕様書4章の最後)
    if dn >= sn:
        dn = 0
    return dn, mismatch


@njit(cache=True)
def _rrcp_scan_core(high_a, low_a, zigzag_length, depth, min_level,
                    error_percent, shoulder_start, shoulder_end, hit_cap):
    """仕様書3〜5章。ZigZagを更新しながら各レベルを走査し、条件を満たした
    「生の検出ヒット」を全て吐く。重複の除去(pattern_id)は呼び出し元の
    Python側で行うが、同じレベルで同じ形が毎バー出続けるのを防ぐため、
    レベルごとに「直前に吐いた構成点」と同じものは連続では吐かない。"""
    n = high_a.shape[0]
    cap = depth

    # レベル0のZigZag(index0が最新)
    zz_price = np.zeros(cap)
    zz_bar = np.zeros(cap, dtype=np.int64)
    zz_dir = np.zeros(cap, dtype=np.int64)
    zz_ratio = np.ones(cap)
    zz_n = 0

    # 各レベルの作業バッファ
    lv_price = np.zeros((_RRCP_MAX_LEVELS, cap))
    lv_bar = np.zeros((_RRCP_MAX_LEVELS, cap), dtype=np.int64)
    lv_dir = np.zeros((_RRCP_MAX_LEVELS, cap), dtype=np.int64)
    lv_ratio = np.ones((_RRCP_MAX_LEVELS, cap))

    # レベルごとの「直前に吐いた構成点」(連続重複の抑制用)
    last_type = np.full(_RRCP_MAX_LEVELS, -1, dtype=np.int64)
    last_bars = np.full((_RRCP_MAX_LEVELS, 6), -1, dtype=np.int64)

    hit_bar = np.zeros(hit_cap, dtype=np.int64)
    hit_level = np.zeros(hit_cap, dtype=np.int64)
    hit_type = np.zeros(hit_cap, dtype=np.int64)
    hit_dir = np.zeros(hit_cap, dtype=np.int64)
    hit_npoints = np.zeros(hit_cap, dtype=np.int64)
    hit_pbar = np.zeros((hit_cap, 6), dtype=np.int64)
    hit_pprice = np.zeros((hit_cap, 6))
    hit_ratio = np.zeros((hit_cap, 4))
    n_hits = 0
    hit_overflow = 0
    level_overflow = 0
    mismatch_total = 0
    short_level = 0

    ratio_min = 1.0 - error_percent / 100.0
    ratio_max = 1.0 + error_percent / 100.0
    head_min = 1.0 / shoulder_end
    head_max = 1.0 / shoulder_start

    for i in range(n):
        if i + 1 < zigzag_length:
            continue

        # ===== 仕様書3.1: 直近zigzag_length本の最高値/最安値とその位置 =====
        # 同値のときは最も新しい位置を採る(>= / <= を使う)。
        p_high = high_a[i]
        p_high_bar = i
        p_low = low_a[i]
        p_low_bar = i
        for k in range(i - zigzag_length + 1, i + 1):
            if high_a[k] >= p_high:
                p_high = high_a[k]
                p_high_bar = k
            if low_a[k] <= p_low:
                p_low = low_a[k]
                p_low_bar = k
        is_high_pivot = (p_high_bar == i)
        is_low_pivot = (p_low_bar == i)

        p_dir = 1
        if zz_n > 0:
            p_dir = 1 if zz_dir[0] > 0 else -1
        distance = 0
        if zz_n > 0:
            distance = i - zz_bar[0]
        overflow = (zz_n > 0) and (distance >= zigzag_length)

        force_double = False
        if zz_n > 1:
            llast_price = zz_price[1]
            if p_dir == 1 and is_low_pivot:
                force_double = p_low < llast_price
            elif p_dir == -1 and is_high_pivot:
                force_double = p_high > llast_price

        new_pivot = False

        # ===== 仕様書3.2 ①: 同方向でより極端 → 直近ピボットを置き換え =====
        if ((p_dir == 1 and is_high_pivot) or (p_dir == -1 and is_low_pivot)) and zz_n >= 1:
            value = p_high if p_dir == 1 else p_low
            last_dir = zz_dir[0]
            if value * last_dir >= zz_price[0] * last_dir:
                for s in range(0, zz_n - 1):
                    zz_price[s] = zz_price[s + 1]
                    zz_bar[s] = zz_bar[s + 1]
                    zz_dir[s] = zz_dir[s + 1]
                    zz_ratio[s] = zz_ratio[s + 1]
                zz_n -= 1
                zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, i, p_dir)
                new_pivot = True

        # ===== 仕様書3.2 ②: 反対方向のピボット → 新規追加 =====
        # 参考元はPineの演算子優先順位により p_dir==1 側にnew_pivotガードが
        # 掛からない。意図か不具合かは不明だが、そのまま再現する。
        if (p_dir == 1 and is_low_pivot) or (
            p_dir == -1 and is_high_pivot and ((not new_pivot) or force_double)
        ):
            value = p_low if p_dir == 1 else p_high
            zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, i, -p_dir)
            new_pivot = True

        # ===== 仕様書3.2 ③: length本ピボットが出ていなければ強制追加 =====
        if overflow and not new_pivot:
            value = p_low if p_dir == 1 else p_high
            value_bar = p_low_bar if p_dir == 1 else p_high_bar
            zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, value_bar, -p_dir)
            new_pivot = True

        if not new_pivot:
            continue

        # ===== 仕様書5.1: レベル0から上位へ登りながら走査 =====
        for s in range(zz_n):
            lv_price[0, s] = zz_price[s]
            lv_bar[0, s] = zz_bar[s]
            lv_dir[0, s] = zz_dir[s]
            lv_ratio[0, s] = zz_ratio[s]
        cur_n = zz_n
        level = 0

        while cur_n > 4:
            if level >= min_level:
                r1 = lv_ratio[level, 0]
                r2 = lv_ratio[level, 1]
                r3 = lv_ratio[level, 2]
                r4 = lv_ratio[level, 3]

                r1_tap = (r1 >= ratio_min) and (r1 <= ratio_max)
                r2_tap = (r2 >= ratio_min) and (r2 <= ratio_max)
                r3_tap = (r3 >= ratio_min) and (r3 <= ratio_max)
                r1_sh = (r1 >= shoulder_start) and (r1 <= shoulder_end)
                r4_sh = (r4 >= shoulder_start) and (r4 <= shoulder_end)
                r3_head = (r3 >= head_min) and (r3 <= head_max)

                is_hs = r1_sh and r2_tap and r3_head and r4_sh
                is_triple = r1_tap and r2_tap and r3_tap and r4_sh
                is_cup = (not is_hs) and r1_sh and r2_tap

                # 優先順位はトリプル → カップ&ハンドル → H&S(仕様書5.3)
                ptype = 0
                if is_triple:
                    ptype = _RRCP_TYPE_TRIPLE
                elif is_cup:
                    ptype = _RRCP_TYPE_CUP
                elif is_hs:
                    ptype = _RRCP_TYPE_HS

                if ptype != 0:
                    npoints = 4 if ptype == _RRCP_TYPE_CUP else 6
                    if cur_n < npoints:
                        # 参考元はここで配列外アクセスになる(6点必要なのに5点
                        # しか無い場合)。再現できないので登録を見送り、回数を
                        # 報告する。
                        short_level += 1
                    else:
                        same_as_last = (last_type[level] == ptype)
                        if same_as_last:
                            for q in range(npoints):
                                if last_bars[level, q] != lv_bar[level, q]:
                                    same_as_last = False
                                    break
                        if not same_as_last:
                            if n_hits < hit_cap:
                                hit_bar[n_hits] = i
                                hit_level[n_hits] = level
                                hit_type[n_hits] = ptype
                                # 上下は一番古い構成点の方向で決まる(仕様書5.4)。
                                # ピボットは必ず交互なので index3 と index5 の
                                # 符号は同じ - どちらで見ても結果は変わらない。
                                hit_dir[n_hits] = 1 if lv_dir[level, npoints - 1] > 0 else -1
                                hit_npoints[n_hits] = npoints
                                for q in range(npoints):
                                    hit_pbar[n_hits, q] = lv_bar[level, q]
                                    hit_pprice[n_hits, q] = lv_price[level, q]
                                hit_ratio[n_hits, 0] = r1
                                hit_ratio[n_hits, 1] = r2
                                hit_ratio[n_hits, 2] = r3
                                hit_ratio[n_hits, 3] = r4
                                n_hits += 1
                            else:
                                hit_overflow += 1
                            last_type[level] = ptype
                            for q in range(npoints):
                                last_bars[level, q] = lv_bar[level, q]

            if level + 1 >= _RRCP_MAX_LEVELS:
                level_overflow += 1
                break
            nxt_n, mm = _rrcp_build_next_level(
                lv_price[level], lv_bar[level], lv_dir[level], cur_n,
                lv_price[level + 1], lv_bar[level + 1], lv_dir[level + 1], lv_ratio[level + 1],
                cap,
            )
            mismatch_total += mm
            if nxt_n == 0:
                break
            cur_n = nxt_n
            level += 1

    return (
        hit_bar[:n_hits], hit_level[:n_hits], hit_type[:n_hits], hit_dir[:n_hits],
        hit_npoints[:n_hits], hit_pbar[:n_hits], hit_pprice[:n_hits], hit_ratio[:n_hits],
        hit_overflow, level_overflow, mismatch_total, short_level,
    )


@njit(cache=True)
def _rrcp_resolve_core(high_a, low_a, cand_bar, cand_dir, cand_neck, cand_extreme, slot_cap):
    """仕様書6章(StrategyX独自拡張)。Candidateごとに、ネックラインを
    ヒゲでクロスしたらConfirmed、パターン極値をヒゲでクロスしたらInvalidated
    とする。同一バーで両方成立したらConfirmed優先。1パターン1決着。

    cand_* はCandidate成立バーの昇順に並んでいる前提。戻り値は各Candidateの
    (状態コード 0=未決着/1=Confirmed/2=Invalidated, 決着バー)。"""
    n = high_a.shape[0]
    n_cand = cand_bar.shape[0]
    status = np.zeros(n_cand, dtype=np.int64)
    resolve_bar = np.full(n_cand, -1, dtype=np.int64)

    live = np.zeros(slot_cap, dtype=np.int64)   # Candidateのindexを入れる
    n_live = 0
    overflow = 0
    next_cand = 0

    for i in range(n):
        # このバーでCandidateになったものを監視に加える
        while next_cand < n_cand and cand_bar[next_cand] == i:
            if n_live < slot_cap:
                live[n_live] = next_cand
                n_live += 1
            else:
                overflow += 1
            next_cand += 1

        if i == 0:
            continue

        for s in range(n_live):
            c = live[s]
            if status[c] != 0:
                continue
            neck = cand_neck[c]
            ext = cand_extreme[c]
            if cand_dir[c] < 0:
                # トップ系: 安値がネックを下抜け→Confirmed、高値が極値を上抜け→Invalidated
                if low_a[i] < neck and low_a[i - 1] >= neck:
                    status[c] = 1
                    resolve_bar[c] = i
                elif high_a[i] > ext and high_a[i - 1] <= ext:
                    status[c] = 2
                    resolve_bar[c] = i
            else:
                if high_a[i] > neck and high_a[i - 1] <= neck:
                    status[c] = 1
                    resolve_bar[c] = i
                elif low_a[i] < ext and low_a[i - 1] >= ext:
                    status[c] = 2
                    resolve_bar[c] = i

        # 決着したものを外す
        w = 0
        for s in range(n_live):
            if status[live[s]] == 0:
                live[w] = live[s]
                w += 1
        n_live = w

    return status, resolve_bar, overflow


# 同時監視できる未決着パターンの上限。溢れたら例外にする(黙って取りこぼさない)。
_RRCP_SLOT_CAPACITY = 4096


def _rrcp_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    zigzag_length: int = 8,
    depth: int = 50,
    min_zigzag_level: int = 0,
    error_percent: float = 13.0,
    shoulder_start: float = 0.1,
    shoulder_end: float = 0.5,
) -> dict[str, Any]:
    """モジュール冒頭のコメントと
    docs/pattern_spec_reversal_chart_patterns_recursive.md 参照。
    トリプルトップ/ボトム・カップ&ハンドル・逆カップ&ハンドル・
    ヘッド&ショルダーズ・逆ヘッド&ショルダーズの6種類は、共通の多段ZigZagから
    同時に検出されるため、まとめて1回で計算する。

    戻り値:
      各パターン名 -> candidate/confirmed/invalidated のBoolean系列
        (StrategyXのindicatorインターフェース用。同一バーに複数イベントが
         乗ると件数が潰れる)
      "events" -> 検出した全イベントを時系列順に1件1レコードで並べたリスト
        (仕様書8.1。件数や構成点が要る用途はこちらを読む)
    """
    n = len(high)
    idx_index = high.index
    high_a = np.ascontiguousarray(high.to_numpy(dtype=float))
    low_a = np.ascontiguousarray(low.to_numpy(dtype=float))

    # 仕様書1章の有効範囲をエンジン側でも保証する(UI側の指定だけに頼らない -
    # 保存済みJSON経由などUIを介さずに呼ばれる経路があるため)。
    zigzag_length = max(_RRCP_ZIGZAG_LENGTH_MIN, int(zigzag_length))
    depth = min(_RRCP_DEPTH_MAX, max(6, int(depth)))
    min_zigzag_level = max(0, int(min_zigzag_level))
    error_percent = min(_RRCP_ERROR_PERCENT_MAX, max(_RRCP_ERROR_PERCENT_MIN, float(error_percent)))
    shoulder_start = min(_RRCP_SHOULDER_START_MAX, max(_RRCP_SHOULDER_START_MIN, float(shoulder_start)))
    shoulder_end = min(_RRCP_SHOULDER_END_MAX, max(_RRCP_SHOULDER_END_MIN, float(shoulder_end)))
    if shoulder_start > shoulder_end:
        shoulder_start, shoulder_end = shoulder_end, shoulder_start

    empty = {name: np.zeros(n, dtype=bool) for name in _RRCP_PATTERN_NAMES.values()}

    def _pack(flags: dict[str, dict[str, np.ndarray]], events: list[dict]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in _RRCP_PATTERN_NAMES.values():
            out[name] = {
                status: pd.Series(flags[name][status], index=idx_index)
                for status in _RRCP_STATUS_NAMES
            }
        out["events"] = events
        return out

    flags = {
        name: {status: np.zeros(n, dtype=bool) for status in _RRCP_STATUS_NAMES}
        for name in _RRCP_PATTERN_NAMES.values()
    }
    if n == 0:
        return _pack(flags, [])

    # ①njitで走査して生の検出ヒットを吐く。枠が足りなければ広げて計算し直す
    # (黙って件数を減らさない)。
    hit_cap = max(4096, n // 16)
    while True:
        (
            hit_bar, hit_level, hit_type, hit_dir, hit_npoints,
            hit_pbar, hit_pprice, hit_ratio,
            hit_overflow, level_overflow, mismatch_total, short_level,
        ) = _rrcp_scan_core(
            high_a, low_a, zigzag_length, depth, min_zigzag_level,
            error_percent, shoulder_start, shoulder_end, hit_cap,
        )
        if hit_overflow == 0:
            break
        hit_cap *= 4

    if mismatch_total:
        # 参考元では実行時エラーになる条件。0以外なら多段ZigZagの実装ミス。
        raise RuntimeError(
            f"多段ZigZagでピボットの方向が交互になりませんでした({mismatch_total}回)。"
            f"engine/chart_patterns.py::_rrcp_build_next_levelの実装を確認してください。"
        )

    # ②Python側でpattern_idの集合を使って重複を落とす(共通管理仕様7.1)。
    #   同じIDが再び現れても再登録しない。最初に現れたバーをCandidate成立バー
    #   とする。
    seen: set[str] = set()
    cand_pattern_id: list[str] = []
    cand_name: list[str] = []
    cand_rows: list[int] = []
    for k in range(len(hit_bar)):
        ptype = int(hit_type[k])
        pdir = int(hit_dir[k])
        name = _RRCP_PATTERN_NAMES[(ptype, pdir)]
        npoints = int(hit_npoints[k])
        pattern_id = _make_pattern_id(name, hit_pbar[k, :npoints])
        key = _make_dedup_key(name, hit_pbar[k, :npoints], newest_first=True)
        if key in seen:
            continue
        seen.add(key)
        cand_pattern_id.append(pattern_id)
        cand_name.append(name)
        cand_rows.append(k)

    n_cand = len(cand_rows)
    if n_cand == 0:
        return _pack(flags, [])

    rows = np.array(cand_rows, dtype=np.int64)
    cand_bar = hit_bar[rows].astype(np.int64)
    cand_dir = hit_dir[rows].astype(np.int64)

    # 判定水準(仕様書6.1) - ネックラインは参考元のエントリー価格
    # (新しい方から2番目の構成点)、極値はトップ系なら構成点の最高値、
    # ボトム系なら最安値。
    cand_neck = np.empty(n_cand, dtype=float)
    cand_extreme = np.empty(n_cand, dtype=float)
    for j, k in enumerate(cand_rows):
        npoints = int(hit_npoints[k])
        prices = hit_pprice[k, :npoints]
        cand_neck[j] = prices[1]
        cand_extreme[j] = prices.max() if hit_dir[k] < 0 else prices.min()

    # Candidate成立バーの昇順に並べ替える(_rrcp_resolve_coreの前提)。
    order = np.argsort(cand_bar, kind="stable")

    # ③njitで各パターンのConfirmed/Invalidatedを追跡する。
    status, resolve_bar, slot_overflow = _rrcp_resolve_core(
        high_a, low_a,
        np.ascontiguousarray(cand_bar[order]),
        np.ascontiguousarray(cand_dir[order]),
        np.ascontiguousarray(cand_neck[order]),
        np.ascontiguousarray(cand_extreme[order]),
        _RRCP_SLOT_CAPACITY,
    )
    if slot_overflow:
        raise RuntimeError(
            f"チャートパターンの同時監視スロットが不足しました"
            f"(上限{_RRCP_SLOT_CAPACITY}件、取りこぼし{slot_overflow}件)。"
            f"engine/chart_patterns.py::_RRCP_SLOT_CAPACITYを増やしてください。"
        )

    # 並べ替えを元に戻す
    status_by_cand = np.empty(n_cand, dtype=np.int64)
    resolve_by_cand = np.empty(n_cand, dtype=np.int64)
    status_by_cand[order] = status
    resolve_by_cand[order] = resolve_bar

    events: list[dict] = []
    for j, k in enumerate(cand_rows):
        name = cand_name[j]
        npoints = int(hit_npoints[k])
        bars = [int(b) for b in hit_pbar[k, :npoints]]
        prices = [float(p) for p in hit_pprice[k, :npoints]]
        base = {
            "pattern_id": cand_pattern_id[j],
            "pattern_type": name,
            "level": int(hit_level[k]),
            "point_bars": bars,
            "point_prices": prices,
            "neckline_price": float(cand_neck[j]),
            "extreme_price": float(cand_extreme[j]),
            "ratios": [float(r) for r in hit_ratio[k]],
        }
        cb = int(cand_bar[j])
        events.append(dict(base, status="candidate", event_bar=cb))
        flags[name]["candidate"][cb] = True

        st = int(status_by_cand[j])
        if st != 0:
            rb = int(resolve_by_cand[j])
            status_name = _RRCP_STATUS_NAMES[st]
            events.append(dict(base, status=status_name, event_bar=rb))
            flags[name][status_name][rb] = True

    events.sort(key=lambda e: (e["event_bar"], e["pattern_id"], e["status"]))
    return _pack(flags, events)


_RRCP_STATE_KEYS = {
    "candidate": "candidate",
    "confirmed": "confirmed",
    "invalidated": "invalidated",
}


def _rrcp_indicator(pattern_name: str):
    """6種類の公開関数を同じ形で作るためのファクトリ。どれを呼んでも内部では
    共通の多段ZigZagを1回計算し、該当パターンのBoolean系列だけを取り出す。"""

    def _fn(
        high: pd.Series, low: pd.Series, close: pd.Series,
        state: str = "confirmed",
        zigzag_length: int = 8,
        depth: int = 50,
        min_zigzag_level: int = 0,
        error_percent: float = 13.0,
        shoulder_start: float = 0.1,
        shoulder_end: float = 0.5,
        **p,
    ) -> np.ndarray:
        result = _rrcp_state(
            high, low, close, zigzag_length, depth, min_zigzag_level,
            error_percent, shoulder_start, shoulder_end,
        )[pattern_name]
        key = _RRCP_STATE_KEYS.get(state, "confirmed")
        return result[key].to_numpy(dtype=float)

    _fn.__name__ = pattern_name
    _fn.__qualname__ = pattern_name
    _fn.__doc__ = (
        f"{pattern_name}(多段ZigZag方式) - モジュール冒頭のコメントと\n"
        "    docs/pattern_spec_reversal_chart_patterns_recursive.md 参照。\n"
        "    Candidate/Confirmed/Invalidatedの3状態をstateパラメータで選べる。\n\n"
        "    条件式が要求するBoolean系列を返すため、同一バーに複数イベントが\n"
        "    乗った場合は1つに潰れる。件数や各パターンの構成点が要る用途では\n"
        "    _rrcp_state(...)[\"events\"] を読むこと。"
    )
    return _fn


triple_top = _rrcp_indicator("triple_top")
triple_bottom = _rrcp_indicator("triple_bottom")
cup_and_handle = _rrcp_indicator("cup_and_handle")
inverted_cup_and_handle = _rrcp_indicator("inverted_cup_and_handle")
head_and_shoulders = _rrcp_indicator("head_and_shoulders")
inverse_head_and_shoulders = _rrcp_indicator("inverse_head_and_shoulders")


# ---------------------------------------------------------------------------
# ABCDパターン(投影型) - B方式実装。
#
# 検出仕様は docs/pattern_spec_abcd_projection.md (v1.0) に文章・数式・条件として
# 全て書き出してあり、この実装はその仕様書だけを入力として書いている(参考元の
# Pine Scriptコードを直接移植したものではない)。参考元は Trendoscope系
# 「ABCD Projection [Trendoscope®]」(Pine v6, CC BY-NC-SA 4.0,
# (c) Trendoscope Pty Ltd)。
#
# 他のパターンとの関係:
#   - ZigZag部分は ZigzagLite/3 を使うが、ZigzagLite は Zigzag/11 から指標対応を
#     取り除いただけでピボット検出・ratio計算とも完全に同一(行単位で照合済み)。
#     よって _rrcp_push_pivot をそのまま流用する。
#   - ただし offset=1(確定足のみ)で、かつ多段ZigZag(nextlevel)は使わない。
#     この2点だけがトリプル等と違う。
#
# アルゴリズムの骨格(詳細は仕様書4〜8章):
#   1. ZigZag(レベル0のみ、1本前までのHigh/Lowで計算)を更新する。
#   2. 新しいピボットが出たバーで、先頭から C(index1) / B(index2) / A(index3) を
#      取り、C点のratioの逆数を使ってD点(価格とバー位置)を投影する。
#   3. 現在バーの終値S点とD点の位置関係(0〜0.382の範囲に収まっているか)、
#      ABC比率、投影距離、直前パターンとの重なりを見てCandidate成立を決める。
#   4. 参考元自身が entry(S価格) / stop(A価格) / target(D価格) を定義し、
#      毎バー High/Low の到達で決着を追跡している。Confirmed=target到達、
#      Invalidated=stop到達。この追跡は参考元由来であり独自拡張ではない。
# ---------------------------------------------------------------------------

# 参考元で定数になっている値(仕様書1章)。
_ABCD_DEPTH = 20
_ABCD_OFFSET = 1
_ABCD_PROJECTION_MAX_BARS = 500
# 成立条件①②の上限。0.382は含まない(厳密不等号)。
_ABCD_POSITION_RATIO_MAX = 0.382

# パラメータの有効範囲(仕様書1章)。UI側の指定だけに頼らず内部でも保証する。
_ABCD_ZIGZAG_LENGTH_MIN = 3
_ABCD_RATIO_MIN = 0.382
_ABCD_RATIO_MAX = 1.0

_ABCD_PATTERN_NAMES = {1: "abcd_bullish", -1: "abcd_bearish"}
_ABCD_STATUS_NAMES = ("candidate", "confirmed", "invalidated")


@njit(cache=True)
def _abcd_scan_core(high_a, low_a, close_a, zigzag_length, min_ratio, max_ratio,
                    avoid_overlap, hit_cap):
    """仕様書3〜6章。ZigZag(レベル0のみ、offset=1)を更新しながら、新しいピボットが
    出たバーでABCDの成立条件を判定し、生の検出ヒットを吐く。

    重複判定(⑤)と重なり回避(⑥)は参考元と同じく「直前に登録した1件」とだけ
    比べる。pattern_idによる厳密な重複除去は呼び出し元のPython側で行う。"""
    n = high_a.shape[0]
    cap = _ABCD_DEPTH

    zz_price = np.zeros(cap)
    zz_bar = np.zeros(cap, dtype=np.int64)
    zz_dir = np.zeros(cap, dtype=np.int64)
    zz_ratio = np.ones(cap)
    zz_n = 0

    hit_bar = np.zeros(hit_cap, dtype=np.int64)
    hit_dir = np.zeros(hit_cap, dtype=np.int64)
    hit_abar = np.zeros(hit_cap, dtype=np.int64)
    hit_aprice = np.zeros(hit_cap)
    hit_bbar = np.zeros(hit_cap, dtype=np.int64)
    hit_bprice = np.zeros(hit_cap)
    hit_cbar = np.zeros(hit_cap, dtype=np.int64)
    hit_cprice = np.zeros(hit_cap)
    hit_dbar = np.zeros(hit_cap, dtype=np.int64)
    hit_dprice = np.zeros(hit_cap)
    hit_entry = np.zeros(hit_cap)
    hit_ratio = np.zeros(hit_cap)
    n_hits = 0
    hit_overflow = 0

    # 参考元の patterns.last() 相当。直前に登録した1件のA/B/Cバー位置とDバー位置。
    last_abar = -1
    last_bbar = -1
    last_cbar = -1
    last_dbar = -1
    have_last = False

    for i in range(n):
        # ===== 仕様書3章: ZigZag(offset=1 なので1本前までのデータで計算) =====
        src = i - _ABCD_OFFSET
        if src < 0 or src + 1 < zigzag_length:
            continue

        p_high = high_a[src]
        p_high_bar = src
        p_low = low_a[src]
        p_low_bar = src
        for k in range(src - zigzag_length + 1, src + 1):
            if high_a[k] >= p_high:
                p_high = high_a[k]
                p_high_bar = k
            if low_a[k] <= p_low:
                p_low = low_a[k]
                p_low_bar = k
        is_high_pivot = (p_high_bar == src)
        is_low_pivot = (p_low_bar == src)

        p_dir = 1
        if zz_n > 0:
            p_dir = 1 if zz_dir[0] > 0 else -1
        distance = 0
        if zz_n > 0:
            distance = src - zz_bar[0]
        overflow = (zz_n > 0) and (distance >= zigzag_length)

        force_double = False
        if zz_n > 1:
            llast_price = zz_price[1]
            if p_dir == 1 and is_low_pivot:
                force_double = p_low < llast_price
            elif p_dir == -1 and is_high_pivot:
                force_double = p_high > llast_price

        new_pivot = False

        # ①同方向でより極端 → 直近ピボットを置き換え
        if ((p_dir == 1 and is_high_pivot) or (p_dir == -1 and is_low_pivot)) and zz_n >= 1:
            value = p_high if p_dir == 1 else p_low
            last_dir = zz_dir[0]
            if value * last_dir >= zz_price[0] * last_dir:
                for s in range(0, zz_n - 1):
                    zz_price[s] = zz_price[s + 1]
                    zz_bar[s] = zz_bar[s + 1]
                    zz_dir[s] = zz_dir[s + 1]
                    zz_ratio[s] = zz_ratio[s + 1]
                zz_n -= 1
                zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, src, p_dir)
                new_pivot = True

        # ②反対方向のピボット → 新規追加(Pineの演算子優先順位をそのまま再現)
        if (p_dir == 1 and is_low_pivot) or (
            p_dir == -1 and is_high_pivot and ((not new_pivot) or force_double)
        ):
            value = p_low if p_dir == 1 else p_high
            zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, src, -p_dir)
            new_pivot = True

        # ③length本ピボットが出ていなければ強制追加
        if overflow and not new_pivot:
            value = p_low if p_dir == 1 else p_high
            value_bar = p_low_bar if p_dir == 1 else p_high_bar
            zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, value_bar, -p_dir)
            new_pivot = True

        if not new_pivot or zz_n < 4:
            continue

        # ===== 仕様書4〜6章: ABCDの判定 =====
        c_price = zz_price[1]
        c_bar = zz_bar[1]
        c_ratio = zz_ratio[1]
        b_price = zz_price[2]
        b_bar = zz_bar[2]
        a_price = zz_price[3]
        a_bar = zz_bar[3]
        cur_price = zz_price[0]

        if np.isnan(c_ratio) or c_ratio == 0.0:
            continue

        # 仕様書5章: D点の投影
        bcd_ratio = 1.0 / c_ratio
        s_price = close_a[i]
        s_bar = i
        d_price = c_price + bcd_ratio * (b_price - c_price)

        denom_bar = abs(d_price - c_price)
        if denom_bar == 0.0:
            continue
        current_ratio = abs(c_price - s_price) / denom_bar
        if current_ratio == 0.0:
            continue
        # Pineのint()はゼロ方向への切り捨て
        d_bar = c_bar + int((s_bar - c_bar) / current_ratio)

        # 仕様書6章: 成立条件
        denom = c_price - d_price
        if denom == 0.0:
            continue
        current_price_ratio = (c_price - s_price) / denom
        last_pivot_ratio = (c_price - cur_price) / denom

        if not (0.0 < current_price_ratio < _ABCD_POSITION_RATIO_MAX):
            continue
        if not (0.0 < last_pivot_ratio < _ABCD_POSITION_RATIO_MAX):
            continue
        if d_bar >= i + _ABCD_PROJECTION_MAX_BARS:
            continue
        if not (min_ratio <= c_ratio <= max_ratio):
            continue

        # ⑤直前に登録したパターンとA/B/Cが完全一致なら不成立
        if have_last and a_bar == last_abar and b_bar == last_bbar and c_bar == last_cbar:
            continue
        # ⑥重なり回避
        if avoid_overlap and have_last and last_dbar >= a_bar:
            continue

        direction = 1 if d_price > a_price else -1

        if n_hits < hit_cap:
            hit_bar[n_hits] = i
            hit_dir[n_hits] = direction
            hit_abar[n_hits] = a_bar
            hit_aprice[n_hits] = a_price
            hit_bbar[n_hits] = b_bar
            hit_bprice[n_hits] = b_price
            hit_cbar[n_hits] = c_bar
            hit_cprice[n_hits] = c_price
            hit_dbar[n_hits] = d_bar
            hit_dprice[n_hits] = d_price
            hit_entry[n_hits] = s_price
            hit_ratio[n_hits] = c_ratio
            n_hits += 1
        else:
            hit_overflow += 1

        last_abar = a_bar
        last_bbar = b_bar
        last_cbar = c_bar
        last_dbar = d_bar
        have_last = True

    return (
        hit_bar[:n_hits], hit_dir[:n_hits],
        hit_abar[:n_hits], hit_aprice[:n_hits],
        hit_bbar[:n_hits], hit_bprice[:n_hits],
        hit_cbar[:n_hits], hit_cprice[:n_hits],
        hit_dbar[:n_hits], hit_dprice[:n_hits],
        hit_entry[:n_hits], hit_ratio[:n_hits],
        hit_overflow,
    )


@njit(cache=True)
def _abcd_resolve_core(high_a, low_a, cand_bar, cand_dir, cand_target, cand_stop, slot_cap):
    """仕様書8章。Candidate成立の次のバーから毎バー、High/Lowの到達(タッチ)で
    決着を判定する。target到達=Confirmed、stop到達=Invalidated、同一バーで
    両方成立したらConfirmed優先。1パターン1決着。

    cand_* はCandidate成立バーの昇順に並んでいる前提。"""
    n = high_a.shape[0]
    n_cand = cand_bar.shape[0]
    status = np.zeros(n_cand, dtype=np.int64)
    resolve_bar = np.full(n_cand, -1, dtype=np.int64)

    live = np.zeros(slot_cap, dtype=np.int64)
    n_live = 0
    overflow = 0
    next_cand = 0

    for i in range(n):
        # 評価はCandidate成立の"次の"バーからなので、まず前バーまでに成立した
        # ものを監視に入れてから判定する。
        for s in range(n_live):
            c = live[s]
            if status[c] != 0:
                continue
            d = cand_dir[c]
            if d > 0:
                target_ref = high_a[i]
                stop_ref = low_a[i]
            else:
                target_ref = low_a[i]
                stop_ref = high_a[i]
            if target_ref * d >= cand_target[c] * d:
                status[c] = 1
                resolve_bar[c] = i
            elif stop_ref * d <= cand_stop[c] * d:
                status[c] = 2
                resolve_bar[c] = i

        w = 0
        for s in range(n_live):
            if status[live[s]] == 0:
                live[w] = live[s]
                w += 1
        n_live = w

        while next_cand < n_cand and cand_bar[next_cand] == i:
            if n_live < slot_cap:
                live[n_live] = next_cand
                n_live += 1
            else:
                overflow += 1
            next_cand += 1

    return status, resolve_bar, overflow


_ABCD_SLOT_CAPACITY = 4096


def _abcd_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    zigzag_length: int = 13,
    min_abc_ratio: float = 0.5,
    max_abc_ratio: float = 1.0,
    avoid_overlap: bool = True,
) -> dict[str, Any]:
    """モジュール冒頭のコメントと docs/pattern_spec_abcd_projection.md 参照。
    強気/弱気のABCDは共通のZigZagから同時に検出されるため、まとめて計算する。

    戻り値:
      "abcd_bullish" / "abcd_bearish" -> candidate/confirmed/invalidated のBoolean系列
      "events" -> 全イベントを時系列順に1件1レコードで並べたリスト(仕様書10.1)
    """
    n = len(high)
    idx_index = high.index
    high_a = np.ascontiguousarray(high.to_numpy(dtype=float))
    low_a = np.ascontiguousarray(low.to_numpy(dtype=float))
    close_a = np.ascontiguousarray(close.to_numpy(dtype=float))

    # 仕様書1章の有効範囲をエンジン側でも保証する。
    zigzag_length = max(_ABCD_ZIGZAG_LENGTH_MIN, int(zigzag_length))
    min_abc_ratio = min(_ABCD_RATIO_MAX, max(_ABCD_RATIO_MIN, float(min_abc_ratio)))
    max_abc_ratio = min(_ABCD_RATIO_MAX, max(_ABCD_RATIO_MIN, float(max_abc_ratio)))
    if min_abc_ratio > max_abc_ratio:
        min_abc_ratio, max_abc_ratio = max_abc_ratio, min_abc_ratio
    avoid_overlap = bool(avoid_overlap)

    flags = {
        name: {status: np.zeros(n, dtype=bool) for status in _ABCD_STATUS_NAMES}
        for name in _ABCD_PATTERN_NAMES.values()
    }

    def _pack(events: list[dict]) -> dict[str, Any]:
        out: dict[str, Any] = {
            name: {s: pd.Series(flags[name][s], index=idx_index) for s in _ABCD_STATUS_NAMES}
            for name in _ABCD_PATTERN_NAMES.values()
        }
        out["events"] = events
        return out

    if n == 0:
        return _pack([])

    hit_cap = max(4096, n // 16)
    while True:
        (
            hit_bar, hit_dir, hit_abar, hit_aprice, hit_bbar, hit_bprice,
            hit_cbar, hit_cprice, hit_dbar, hit_dprice, hit_entry, hit_ratio,
            hit_overflow,
        ) = _abcd_scan_core(
            high_a, low_a, close_a, zigzag_length,
            min_abc_ratio, max_abc_ratio, avoid_overlap, hit_cap,
        )
        if hit_overflow == 0:
            break
        hit_cap *= 4

    # 共通管理仕様9.1: pattern_idで重複を落とす。参考元の⑤は「直前1件」との
    # 比較だけなので、それより過去のパターンと同一構成になる可能性が残る。
    seen: set[str] = set()
    rows: list[int] = []
    pattern_ids: list[str] = []
    names: list[str] = []
    for k in range(len(hit_bar)):
        name = _ABCD_PATTERN_NAMES[int(hit_dir[k])]
        pid = _make_pattern_id(name, (hit_cbar[k], hit_bbar[k], hit_abar[k]))
        if pid in seen:
            continue
        seen.add(pid)
        rows.append(k)
        pattern_ids.append(pid)
        names.append(name)

    if not rows:
        return _pack([])

    sel = np.array(rows, dtype=np.int64)
    cand_bar = np.ascontiguousarray(hit_bar[sel].astype(np.int64))
    cand_dir = np.ascontiguousarray(hit_dir[sel].astype(np.int64))
    cand_target = np.ascontiguousarray(hit_dprice[sel])
    cand_stop = np.ascontiguousarray(hit_aprice[sel])

    status, resolve_bar, slot_overflow = _abcd_resolve_core(
        high_a, low_a, cand_bar, cand_dir, cand_target, cand_stop, _ABCD_SLOT_CAPACITY
    )
    if slot_overflow:
        raise RuntimeError(
            f"ABCDパターンの同時監視スロットが不足しました"
            f"(上限{_ABCD_SLOT_CAPACITY}件、取りこぼし{slot_overflow}件)。"
            f"engine/chart_patterns.py::_ABCD_SLOT_CAPACITYを増やしてください。"
        )

    events: list[dict] = []
    for j, k in enumerate(rows):
        name = names[j]
        base = {
            "pattern_id": pattern_ids[j],
            "pattern_type": name,
            "a_bar": int(hit_abar[k]), "a_price": float(hit_aprice[k]),
            "b_bar": int(hit_bbar[k]), "b_price": float(hit_bprice[k]),
            "c_bar": int(hit_cbar[k]), "c_price": float(hit_cprice[k]),
            "d_bar": int(hit_dbar[k]), "d_price": float(hit_dprice[k]),
            "entry_price": float(hit_entry[k]),
            "stop_price": float(hit_aprice[k]),
            "target_price": float(hit_dprice[k]),
            "abc_ratio": float(hit_ratio[k]),
        }
        cb = int(cand_bar[j])
        events.append(dict(base, status="candidate", event_bar=cb))
        flags[name]["candidate"][cb] = True
        st = int(status[j])
        if st != 0:
            rb = int(resolve_bar[j])
            sname = _ABCD_STATUS_NAMES[st]
            events.append(dict(base, status=sname, event_bar=rb))
            flags[name][sname][rb] = True

    events.sort(key=lambda e: (e["event_bar"], e["pattern_id"], e["status"]))
    return _pack(events)


def _abcd_indicator(pattern_name: str):
    """強気/弱気の公開関数を同じ形で作るためのファクトリ。"""

    def _fn(
        high: pd.Series, low: pd.Series, close: pd.Series,
        state: str = "confirmed",
        zigzag_length: int = 13,
        min_abc_ratio: float = 0.5,
        max_abc_ratio: float = 1.0,
        avoid_overlap: bool = True,
        **p,
    ) -> np.ndarray:
        result = _abcd_state(
            high, low, close, zigzag_length, min_abc_ratio, max_abc_ratio, avoid_overlap,
        )[pattern_name]
        key = state if state in _ABCD_STATUS_NAMES else "confirmed"
        return result[key].to_numpy(dtype=float)

    _fn.__name__ = pattern_name
    _fn.__qualname__ = pattern_name
    _fn.__doc__ = (
        f"{pattern_name}(ABCD投影型) - モジュール冒頭のコメントと\n"
        "    docs/pattern_spec_abcd_projection.md 参照。Candidate/Confirmed/\n"
        "    Invalidatedの3状態をstateパラメータで選べる。\n\n"
        "    条件式が要求するBoolean系列を返すため、同一バーに複数イベントが\n"
        "    乗った場合は1つに潰れる。件数や構成点が要る用途では\n"
        "    _abcd_state(...)[\"events\"] を読むこと。"
    )
    return _fn


abcd_bullish = _abcd_indicator("abcd_bullish")
abcd_bearish = _abcd_indicator("abcd_bearish")


# ---------------------------------------------------------------------------
# ABCパターン(多段ZigZag) - B方式実装。
#
# 検出仕様は docs/pattern_spec_abc_recursive.md (v1.0) に文章・数式・条件として
# 全て書き出してあり、この実装はその仕様書だけを入力として書いている。参考元は
# Trendoscope系「ABC on Recursive Zigzag [Trendoscope]」(Pine v6,
# CC BY-NC-SA 4.0, (c) Trendoscope Pty Ltd)。
#
# 他のパターンとの関係:
#   - ZigZagとその多段化は RRCP(トリプル等)と完全に同じなので、
#     _rrcp_push_pivot / _rrcp_build_next_level をそのまま流用する。
#   - ABCDパターンとは**構成点の添字が1つずれている**(あちらは C=index1、
#     こちらは C=index0)。混同しないこと。
#
# アルゴリズムの骨格(詳細は仕様書3〜7章):
#   1. レベル0のZigZagを更新し、新しいピボットが出たバーで上位レベルへ登りながら
#      走査する(走査は Pivot数>=3 の間、判定は Pivot数>=4 のとき)。
#   2. C=index0 / B=index1 / A=index2 を取り、C点のratioが0.618〜0.786(両端含む)、
#      方向フィルター、エントリー未到達(withinEntry)の3つでCandidateを決める。
#   3. 水準は参考元の FibRatios の式で計算する(base で extension / retracement を
#      切り替え、対数スケールにも対応)。
#   4. 参考元自身が status 0(未到達)/1(エントリー到達)/2(利確到達)の遷移を
#      追跡している。利確到達=Confirmed、損切り=Invalidated。終値で見るか
#      ヒゲで見るかは参考元のパラメータどおり(初期値は終値)。
# ---------------------------------------------------------------------------

_ABC_BASE_EXTENSION = 1
_ABC_BASE_RETRACEMENT = 2
_ABC_BASE_CHOICES = {"abc_extension": _ABC_BASE_EXTENSION, "bc_retracement": _ABC_BASE_RETRACEMENT}

_ABC_CONDITION_CHOICES = {"any": 0, "trend": 1, "reverse": 2, "contracting": 3, "expanding": 4}

# 仕様書5章①のratio範囲。両端を含む。
_ABC_RATIO_MIN = 0.618
_ABC_RATIO_MAX = 0.786

# パラメータの有効範囲(仕様書1章)。
_ABC_ZIGZAG_LENGTH_MIN = 3
_ABC_DEPTH_MAX = 500
_ABC_ENTRY_RATIO_MIN = 0.1
_ABC_STOP_RATIO_MAX = 0.0

_ABC_PATTERN_NAMES = {1: "abc_bullish", -1: "abc_bearish"}
_ABC_STATUS_NAMES = ("candidate", "confirmed", "invalidated")


@njit(cache=True)
def _abc_level_price(a_price, b_price, c_price, ratio, base_code, log_scale):
    """仕様書6章。参考元のFibRatiosの式そのまま。
    base=1: extension(A, B, C, ratio)   非対数 C + (B-A)×ratio / 対数 C×(B/A)^ratio
    base=2: retracement(B, C, ratio)    非対数 C - (C-B)×ratio / 対数 C×(B/C)^ratio
    参考元の round_to_mintick は銘柄の最小刻みに依存し検出器からは分からないため
    行わない(仕様書0章)。"""
    if base_code == _ABC_BASE_EXTENSION:
        if log_scale:
            if a_price <= 0.0 or b_price <= 0.0:
                return np.nan
            return c_price * (b_price / a_price) ** ratio
        return c_price + (b_price - a_price) * ratio
    if log_scale:
        if b_price <= 0.0 or c_price <= 0.0:
            return np.nan
        return c_price * (b_price / c_price) ** ratio
    return c_price - (c_price - b_price) * ratio


@njit(cache=True)
def _abc_scan_core(high_a, low_a, close_a, zigzag_length, depth, min_level,
                   base_code, entry_ratio, target_ratio, stop_ratio, log_scale,
                   condition_code, hit_cap):
    """仕様書2〜6章。ZigZagを更新しながら各レベルを走査し、Candidate条件を満たした
    生の検出ヒットを吐く。重複除去(pattern_id)は呼び出し元のPython側で行うが、
    同じレベルで同じ形が毎バー出続けるのを防ぐため、レベルごとに直前に吐いた
    構成点と同じものは連続では吐かない。"""
    n = high_a.shape[0]
    cap = depth

    zz_price = np.zeros(cap)
    zz_bar = np.zeros(cap, dtype=np.int64)
    zz_dir = np.zeros(cap, dtype=np.int64)
    zz_ratio = np.ones(cap)
    zz_n = 0

    lv_price = np.zeros((_RRCP_MAX_LEVELS, cap))
    lv_bar = np.zeros((_RRCP_MAX_LEVELS, cap), dtype=np.int64)
    lv_dir = np.zeros((_RRCP_MAX_LEVELS, cap), dtype=np.int64)
    lv_ratio = np.ones((_RRCP_MAX_LEVELS, cap))

    last_bars = np.full((_RRCP_MAX_LEVELS, 3), -1, dtype=np.int64)

    hit_bar = np.zeros(hit_cap, dtype=np.int64)
    hit_level = np.zeros(hit_cap, dtype=np.int64)
    hit_dir = np.zeros(hit_cap, dtype=np.int64)
    hit_abar = np.zeros(hit_cap, dtype=np.int64)
    hit_aprice = np.zeros(hit_cap)
    hit_bbar = np.zeros(hit_cap, dtype=np.int64)
    hit_bprice = np.zeros(hit_cap)
    hit_cbar = np.zeros(hit_cap, dtype=np.int64)
    hit_cprice = np.zeros(hit_cap)
    hit_entry = np.zeros(hit_cap)
    hit_target = np.zeros(hit_cap)
    hit_stop = np.zeros(hit_cap)
    hit_ratio = np.zeros(hit_cap)
    n_hits = 0
    hit_overflow = 0
    mismatch_total = 0

    for i in range(n):
        if i + 1 < zigzag_length:
            continue

        p_high = high_a[i]
        p_high_bar = i
        p_low = low_a[i]
        p_low_bar = i
        for k in range(i - zigzag_length + 1, i + 1):
            if high_a[k] >= p_high:
                p_high = high_a[k]
                p_high_bar = k
            if low_a[k] <= p_low:
                p_low = low_a[k]
                p_low_bar = k
        is_high_pivot = (p_high_bar == i)
        is_low_pivot = (p_low_bar == i)

        p_dir = 1
        if zz_n > 0:
            p_dir = 1 if zz_dir[0] > 0 else -1
        distance = 0
        if zz_n > 0:
            distance = i - zz_bar[0]
        overflow = (zz_n > 0) and (distance >= zigzag_length)

        force_double = False
        if zz_n > 1:
            llast_price = zz_price[1]
            if p_dir == 1 and is_low_pivot:
                force_double = p_low < llast_price
            elif p_dir == -1 and is_high_pivot:
                force_double = p_high > llast_price

        new_pivot = False
        if ((p_dir == 1 and is_high_pivot) or (p_dir == -1 and is_low_pivot)) and zz_n >= 1:
            value = p_high if p_dir == 1 else p_low
            last_dir = zz_dir[0]
            if value * last_dir >= zz_price[0] * last_dir:
                for s in range(0, zz_n - 1):
                    zz_price[s] = zz_price[s + 1]
                    zz_bar[s] = zz_bar[s + 1]
                    zz_dir[s] = zz_dir[s + 1]
                    zz_ratio[s] = zz_ratio[s + 1]
                zz_n -= 1
                zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, i, p_dir)
                new_pivot = True

        if (p_dir == 1 and is_low_pivot) or (
            p_dir == -1 and is_high_pivot and ((not new_pivot) or force_double)
        ):
            value = p_low if p_dir == 1 else p_high
            zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, i, -p_dir)
            new_pivot = True

        if overflow and not new_pivot:
            value = p_low if p_dir == 1 else p_high
            value_bar = p_low_bar if p_dir == 1 else p_high_bar
            zz_n = _rrcp_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_n, cap, value, value_bar, -p_dir)
            new_pivot = True

        if not new_pivot:
            continue

        for s in range(zz_n):
            lv_price[0, s] = zz_price[s]
            lv_bar[0, s] = zz_bar[s]
            lv_dir[0, s] = zz_dir[s]
            lv_ratio[0, s] = zz_ratio[s]
        cur_n = zz_n
        level = 0

        # 仕様書3章: 走査は Pivot数>=3 の間、判定は Pivot数>=4 のとき
        while cur_n >= 3:
            if level >= min_level and cur_n >= 4:
                c_price = lv_price[level, 0]
                c_bar = lv_bar[level, 0]
                c_ratio = lv_ratio[level, 0]
                b_price = lv_price[level, 1]
                b_bar = lv_bar[level, 1]
                b_dir = lv_dir[level, 1]
                a_price = lv_price[level, 2]
                a_bar = lv_bar[level, 2]
                a_dir = lv_dir[level, 2]

                # ① ratio範囲(両端含む)
                ratio_ok = (c_ratio >= _ABC_RATIO_MIN) and (c_ratio <= _ABC_RATIO_MAX)

                # ② 方向フィルター
                a_abs = a_dir if a_dir >= 0 else -a_dir
                b_abs = b_dir if b_dir >= 0 else -b_dir
                if condition_code == 0:
                    cond_ok = True
                elif condition_code == 1:
                    cond_ok = (a_abs == 1) and (b_abs == 2)
                elif condition_code == 2:
                    cond_ok = (a_abs == 2) and (b_abs == 1)
                elif condition_code == 3:
                    cond_ok = (a_abs == 1) and (b_abs == 1)
                else:
                    cond_ok = (a_abs == 2) and (b_abs == 2)

                if ratio_ok and cond_ok:
                    entry_price = _abc_level_price(a_price, b_price, c_price, entry_ratio, base_code, log_scale)
                    target_price = _abc_level_price(a_price, b_price, c_price, target_ratio, base_code, log_scale)
                    stop_price = _abc_level_price(a_price, b_price, c_price, stop_ratio, base_code, log_scale)

                    direction = 1 if b_price > c_price else -1

                    # ③ エントリー未到達(withinEntry)
                    within = close_a[i] * direction < entry_price * direction

                    if within and not np.isnan(entry_price) and not np.isnan(target_price) and not np.isnan(stop_price):
                        same = (last_bars[level, 0] == c_bar
                                and last_bars[level, 1] == b_bar
                                and last_bars[level, 2] == a_bar)
                        if not same:
                            if n_hits < hit_cap:
                                hit_bar[n_hits] = i
                                hit_level[n_hits] = level
                                hit_dir[n_hits] = direction
                                hit_abar[n_hits] = a_bar
                                hit_aprice[n_hits] = a_price
                                hit_bbar[n_hits] = b_bar
                                hit_bprice[n_hits] = b_price
                                hit_cbar[n_hits] = c_bar
                                hit_cprice[n_hits] = c_price
                                hit_entry[n_hits] = entry_price
                                hit_target[n_hits] = target_price
                                hit_stop[n_hits] = stop_price
                                hit_ratio[n_hits] = c_ratio
                                n_hits += 1
                            else:
                                hit_overflow += 1
                            last_bars[level, 0] = c_bar
                            last_bars[level, 1] = b_bar
                            last_bars[level, 2] = a_bar

            if level + 1 >= _RRCP_MAX_LEVELS:
                break
            nxt_n, mm = _rrcp_build_next_level(
                lv_price[level], lv_bar[level], lv_dir[level], cur_n,
                lv_price[level + 1], lv_bar[level + 1], lv_dir[level + 1], lv_ratio[level + 1],
                cap,
            )
            mismatch_total += mm
            if nxt_n == 0:
                break
            cur_n = nxt_n
            level += 1

    return (
        hit_bar[:n_hits], hit_level[:n_hits], hit_dir[:n_hits],
        hit_abar[:n_hits], hit_aprice[:n_hits],
        hit_bbar[:n_hits], hit_bprice[:n_hits],
        hit_cbar[:n_hits], hit_cprice[:n_hits],
        hit_entry[:n_hits], hit_target[:n_hits], hit_stop[:n_hits], hit_ratio[:n_hits],
        hit_overflow, mismatch_total,
    )


@njit(cache=True)
def _abc_resolve_core(high_a, low_a, close_a, cand_bar, cand_dir,
                      cand_entry, cand_target, cand_stop,
                      use_close_entry, use_close_target, use_close_stop, slot_cap):
    """仕様書7章。参考元の status 0/1/2 の遷移をそのまま再現する。
    利確到達(状態2)=Confirmed、損切りでの終了=Invalidated。
    評価はCandidate成立の次のバーから。"""
    n = high_a.shape[0]
    n_cand = cand_bar.shape[0]
    result = np.zeros(n_cand, dtype=np.int64)      # 0=未決着, 1=Confirmed, 2=Invalidated
    resolve_bar = np.full(n_cand, -1, dtype=np.int64)
    inner = np.zeros(n_cand, dtype=np.int64)       # 参考元のstatus 0/1/2

    live = np.zeros(slot_cap, dtype=np.int64)
    n_live = 0
    overflow = 0
    next_cand = 0

    for i in range(n):
        for s in range(n_live):
            c = live[s]
            if result[c] != 0:
                continue
            d = cand_dir[c]
            if use_close_target:
                target_ref = close_a[i]
            else:
                target_ref = high_a[i] if d > 0 else low_a[i]
            if use_close_entry:
                entry_ref = close_a[i]
            else:
                entry_ref = high_a[i] if d > 0 else low_a[i]
            if use_close_stop:
                stop_ref = close_a[i]
            else:
                stop_ref = low_a[i] if d > 0 else high_a[i]

            cur = inner[c]
            if target_ref * d >= cand_target[c] * d:
                new_status = 2
            elif entry_ref * d >= cand_entry[c] * d:
                new_status = 1
            else:
                new_status = cur
            if new_status < cur:
                new_status = cur

            if new_status == 2:
                # 利確到達 - 参考元は次のバーで配列から外して集計するが、状態
                # 遷移そのものはこのバーで起きているのでここでConfirmedにする
                # (仕様書7章の差異メモ参照)。
                inner[c] = 2
                result[c] = 1
                resolve_bar[c] = i
            else:
                stopped = False
                if new_status > 0:
                    stopped = stop_ref * d <= cand_stop[c] * d
                else:
                    stopped = close_a[i] * d <= cand_stop[c] * d
                inner[c] = new_status
                if stopped:
                    result[c] = 2
                    resolve_bar[c] = i

        w = 0
        for s in range(n_live):
            if result[live[s]] == 0:
                live[w] = live[s]
                w += 1
        n_live = w

        while next_cand < n_cand and cand_bar[next_cand] == i:
            if n_live < slot_cap:
                live[n_live] = next_cand
                n_live += 1
            else:
                overflow += 1
            next_cand += 1

    return result, resolve_bar, overflow


_ABC_SLOT_CAPACITY = 4096


def _abc_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    zigzag_length: int = 13,
    depth: int = 200,
    min_zigzag_level: int = 0,
    base: str = "abc_extension",
    entry_ratio: float = 0.3,
    target_ratio: float = 1.0,
    stop_ratio: float = 0.0,
    log_scale: bool = False,
    trade_condition: str = "any",
    use_close_for_entry: bool = True,
    use_close_for_target: bool = True,
    use_close_for_stop: bool = True,
) -> dict[str, Any]:
    """モジュール冒頭のコメントと docs/pattern_spec_abc_recursive.md 参照。
    強気/弱気のABCは共通の多段ZigZagから同時に検出されるため、まとめて計算する。"""
    n = len(high)
    idx_index = high.index
    high_a = np.ascontiguousarray(high.to_numpy(dtype=float))
    low_a = np.ascontiguousarray(low.to_numpy(dtype=float))
    close_a = np.ascontiguousarray(close.to_numpy(dtype=float))

    # 仕様書1章の有効範囲をエンジン側でも保証する。
    zigzag_length = max(_ABC_ZIGZAG_LENGTH_MIN, int(zigzag_length))
    depth = min(_ABC_DEPTH_MAX, max(6, int(depth)))
    min_zigzag_level = max(0, int(min_zigzag_level))
    entry_ratio = max(_ABC_ENTRY_RATIO_MIN, float(entry_ratio))
    target_ratio = float(target_ratio)
    stop_ratio = min(_ABC_STOP_RATIO_MAX, float(stop_ratio))
    base_code = _ABC_BASE_CHOICES.get(str(base), _ABC_BASE_EXTENSION)
    condition_code = _ABC_CONDITION_CHOICES.get(str(trade_condition), 0)

    flags = {
        name: {s: np.zeros(n, dtype=bool) for s in _ABC_STATUS_NAMES}
        for name in _ABC_PATTERN_NAMES.values()
    }

    def _pack(events: list[dict]) -> dict[str, Any]:
        out: dict[str, Any] = {
            name: {s: pd.Series(flags[name][s], index=idx_index) for s in _ABC_STATUS_NAMES}
            for name in _ABC_PATTERN_NAMES.values()
        }
        out["events"] = events
        return out

    if n == 0:
        return _pack([])

    hit_cap = max(4096, n // 16)
    while True:
        (
            hit_bar, hit_level, hit_dir, hit_abar, hit_aprice, hit_bbar, hit_bprice,
            hit_cbar, hit_cprice, hit_entry, hit_target, hit_stop, hit_ratio,
            hit_overflow, mismatch_total,
        ) = _abc_scan_core(
            high_a, low_a, close_a, zigzag_length, depth, min_zigzag_level,
            base_code, entry_ratio, target_ratio, stop_ratio, bool(log_scale),
            condition_code, hit_cap,
        )
        if hit_overflow == 0:
            break
        hit_cap *= 4

    if mismatch_total:
        raise RuntimeError(
            f"多段ZigZagでピボットの方向が交互になりませんでした({mismatch_total}回)。"
            f"engine/chart_patterns.py::_rrcp_build_next_levelの実装を確認してください。"
        )

    seen: set[str] = set()
    rows: list[int] = []
    pattern_ids: list[str] = []
    names: list[str] = []
    for k in range(len(hit_bar)):
        name = _ABC_PATTERN_NAMES[int(hit_dir[k])]
        pid = _make_pattern_id(name, (hit_cbar[k], hit_bbar[k], hit_abar[k]))
        if pid in seen:
            continue
        seen.add(pid)
        rows.append(k)
        pattern_ids.append(pid)
        names.append(name)

    if not rows:
        return _pack([])

    sel = np.array(rows, dtype=np.int64)
    cand_bar = hit_bar[sel].astype(np.int64)
    order = np.argsort(cand_bar, kind="stable")

    result, resolve_bar, slot_overflow = _abc_resolve_core(
        high_a, low_a, close_a,
        np.ascontiguousarray(cand_bar[order]),
        np.ascontiguousarray(hit_dir[sel][order].astype(np.int64)),
        np.ascontiguousarray(hit_entry[sel][order]),
        np.ascontiguousarray(hit_target[sel][order]),
        np.ascontiguousarray(hit_stop[sel][order]),
        bool(use_close_for_entry), bool(use_close_for_target), bool(use_close_for_stop),
        _ABC_SLOT_CAPACITY,
    )
    if slot_overflow:
        raise RuntimeError(
            f"ABCパターンの同時監視スロットが不足しました"
            f"(上限{_ABC_SLOT_CAPACITY}件、取りこぼし{slot_overflow}件)。"
            f"engine/chart_patterns.py::_ABC_SLOT_CAPACITYを増やしてください。"
        )

    result_by_cand = np.empty(len(rows), dtype=np.int64)
    resolve_by_cand = np.empty(len(rows), dtype=np.int64)
    result_by_cand[order] = result
    resolve_by_cand[order] = resolve_bar

    events: list[dict] = []
    for j, k in enumerate(rows):
        name = names[j]
        base_rec = {
            "pattern_id": pattern_ids[j],
            "pattern_type": name,
            "level": int(hit_level[k]),
            "a_bar": int(hit_abar[k]), "a_price": float(hit_aprice[k]),
            "b_bar": int(hit_bbar[k]), "b_price": float(hit_bprice[k]),
            "c_bar": int(hit_cbar[k]), "c_price": float(hit_cprice[k]),
            "entry_price": float(hit_entry[k]),
            "target_price": float(hit_target[k]),
            "stop_price": float(hit_stop[k]),
            "bc_ratio": float(hit_ratio[k]),
        }
        cb = int(cand_bar[j])
        events.append(dict(base_rec, status="candidate", event_bar=cb))
        flags[name]["candidate"][cb] = True
        st = int(result_by_cand[j])
        if st != 0:
            rb = int(resolve_by_cand[j])
            sname = _ABC_STATUS_NAMES[st]
            events.append(dict(base_rec, status=sname, event_bar=rb))
            flags[name][sname][rb] = True

    events.sort(key=lambda e: (e["event_bar"], e["pattern_id"], e["status"]))
    return _pack(events)


def _abc_indicator(pattern_name: str):
    def _fn(
        high: pd.Series, low: pd.Series, close: pd.Series,
        state: str = "confirmed",
        zigzag_length: int = 13,
        depth: int = 200,
        min_zigzag_level: int = 0,
        base: str = "abc_extension",
        entry_ratio: float = 0.3,
        target_ratio: float = 1.0,
        stop_ratio: float = 0.0,
        log_scale: bool = False,
        trade_condition: str = "any",
        use_close_for_entry: bool = True,
        use_close_for_target: bool = True,
        use_close_for_stop: bool = True,
        **p,
    ) -> np.ndarray:
        result = _abc_state(
            high, low, close, zigzag_length, depth, min_zigzag_level, base,
            entry_ratio, target_ratio, stop_ratio, log_scale, trade_condition,
            use_close_for_entry, use_close_for_target, use_close_for_stop,
        )[pattern_name]
        key = state if state in _ABC_STATUS_NAMES else "confirmed"
        return result[key].to_numpy(dtype=float)

    _fn.__name__ = pattern_name
    _fn.__qualname__ = pattern_name
    _fn.__doc__ = (
        f"{pattern_name}(ABC・多段ZigZag) - モジュール冒頭のコメントと\n"
        "    docs/pattern_spec_abc_recursive.md 参照。Candidate/Confirmed/\n"
        "    Invalidatedの3状態をstateパラメータで選べる。\n\n"
        "    件数や構成点が要る用途では _abc_state(...)[\"events\"] を読むこと。"
    )
    return _fn


abc_bullish = _abc_indicator("abc_bullish")
abc_bearish = _abc_indicator("abc_bearish")


# ---------------------------------------------------------------------------
# 推進波 / 収束ダイアゴナル / 拡大ダイアゴナル(エリオット波動) - B方式実装。
#
# 検出仕様は docs/pattern_spec_motive_wave.md (v1.0) に文章・数式・条件として
# 全て書き出してあり、この実装はその仕様書だけを入力として書いている(参考元の
# Pine Scriptコードを直接移植したものではない)。参考元は
# 「Motive Wave Scanner [Trendoscope®]」(Pine v6, CC BY-NC-SA 4.0,
# (c) Trendoscope Pty Ltd)と、それがimportする Waves/3 / utils/1 / FibRatios/1。
#
# 【不明】参考元は Zigzag/10 を指定しているが、TradingViewは公開ライブラリの
#   最新版しか表示しないため Zigzag/10 そのものは取得できていない。3〜4章の
#   ZigZag仕様は公開版の書き起こしであり、/10 との差分は不明(仕様書0.3)。
#
# 他のパターンとの関係:
#   - ZigZagのピボット生成・ratio計算・多段化は トリプルトップ等(RRCP)と同一。
#     ただし本パターンは各ピボットが束ねる下位ピボット列(micropivots)を
#     使うため、componentIndex を追跡する専用版を別に持つ。
#   - offset=0(当バーのHigh/Lowを使う)。RRCPと同じ。ABCDだけがoffset=1。
#
# アルゴリズムの骨格(詳細は仕様書4〜6章):
#   1. レベル0のZigZagを更新する。新しいピボットが出たバーだけ走査する。
#   2. レベルを1つずつ登りながら、そのレベルの「新しい方から2番目」のピボットを
#      見る。|dir|==2(そのレベルで新高値/新安値を作った)のものだけが対象。
#   3. そのピボットが束ねる下位ピボット列(micropivots)を展開し、その中から
#      P0〜P5の6点の組み合わせを総当たりで探す。
#   4. 6点が「各波に余計な突き抜けが無い」形なら、比率で推進波/収束ダイアゴナル/
#      拡大ダイアゴナルのいずれかに分類する。
#   5. 参考元は水準を定義していないため、Confirmed/Invalidatedの判定水準は
#      StrategyX独自拡張(仕様書8.1)。P4をネックライン、P5を極値とする。
# ---------------------------------------------------------------------------

_MW_MAX_LEVELS = 32
# 1つのピボットが束ねるmicropivotsの上限。レベル2以上では境界のピボットが
# 重複するため(仕様書4.2)、depthより大きく取る。
_MW_MICRO_CAPACITY = 1024
_MW_SERIES_CAPACITY = 256

_MW_TYPE_IMPULSE = 1
_MW_TYPE_CONTRACTING = 2
_MW_TYPE_EXPANDING = 3

# キーの向きは「シグナルの向き」(仕様書8.2)。波が上昇なら完成後は下落を
# 示唆するので bearish になる。
_MW_PATTERN_NAMES = {
    (_MW_TYPE_IMPULSE, -1): "impulse_wave_bearish",
    (_MW_TYPE_IMPULSE, 1): "impulse_wave_bullish",
    # 収束/拡大ダイアゴナルは参考元のアルゴリズムでは構造上決して成立しない
    # (_mw_check のコメントと仕様書6.6)。分類コード自体は参考元どおり残して
    # あるが、常に0件になる指標をUIや自動探索のプールに並べても害しか無いので
    # 公開指標にはしない。ここに現れないコードが来たら実装ミスとして例外になる。
}
_MW_STATUS_NAMES = ("candidate", "confirmed", "invalidated")

# 仕様書1章の有効範囲。stepはUI表示上の刻みでありエンジン側では強制しない。
_MW_ZIGZAG_LENGTH_MIN = 3
_MW_DEPTH_MAX = 500
_MW_LEVEL_MIN = 1

_MW_LEVEL_TYPE_MINIMUM = 0
_MW_LEVEL_TYPE_ABSOLUTE = 1
_MW_LEVEL_TYPE_CHOICES = {"minimum": _MW_LEVEL_TYPE_MINIMUM, "absolute": _MW_LEVEL_TYPE_ABSOLUTE}


@njit(cache=True)
def _mw_push_pivot(price, bar, dirs, ratios, cis, cls, n, cap,
                   new_price, new_bar, new_sign, new_ci):
    """ZigZag配列(index0が最新)の先頭へピボットを1つ積む。_rrcp_push_pivot と
    同じ計算に加えて、仕様書4.2の componentIndex を2つ記録する。

      cis[j] … そのピボット自身の「1つ下のレベルの配列内位置」
      cls[j] … 積んだ時点で先頭にいたピボット(=1つ古い同レベルピボット)の cis。
               先頭が空だった場合は -1(micropivotsが空になるケース)。

    レベル0では cis/cls は使わないので new_ci に -1 を渡してよい。"""
    out_dir = new_sign
    out_ratio = 1.0
    if n >= 2:
        last_price = price[0]
        llast_price = price[1]
        if new_sign * new_price > new_sign * llast_price:
            out_dir = new_sign * 2
        denom = abs(llast_price - last_price)
        if denom > 0.0:
            out_ratio = np.floor(abs(last_price - new_price) / denom * 1000.0 + 0.5) / 1000.0
        else:
            out_ratio = np.nan
    new_cl = cis[0] if n > 0 else -1
    m = n if n < cap else cap - 1
    for s in range(m, 0, -1):
        price[s] = price[s - 1]
        bar[s] = bar[s - 1]
        dirs[s] = dirs[s - 1]
        ratios[s] = ratios[s - 1]
        cis[s] = cis[s - 1]
        cls[s] = cls[s - 1]
    price[0] = new_price
    bar[0] = new_bar
    dirs[0] = out_dir
    ratios[0] = out_ratio
    cis[0] = new_ci
    cls[0] = new_cl
    if n < cap:
        n += 1
    return n


@njit(cache=True)
def _mw_build_next_level(sp, sb, sd, sn, dp, db, dd, dr, dci, dcl, cap):
    """仕様書4.1。_rrcp_build_next_level と同じアルゴリズムに、各ピボットが
    下位配列のどの位置から来たか(componentIndex)の記録を足したもの。
    戻り値は (上位のピボット数, 方向不整合の回数)。"""
    dn = 0
    mismatch = 0
    have_bull = False
    bull_p = 0.0
    bull_b = 0
    bull_i = 0
    have_bear = False
    bear_p = 0.0
    bear_b = 0
    bear_i = 0

    for idx in range(sn - 1, -1, -1):   # 古い順
        p_price = sp[idx]
        p_bar = sb[idx]
        p_dir = sd[idx]
        nd = 1 if p_dir > 0 else -1
        adir = p_dir if p_dir >= 0 else -p_dir

        if dn > 0:
            last_d = 1 if dd[0] > 0 else -1
            last_p = dp[0]
            if adir == 2:
                skip = False
                if last_d == nd:
                    if p_dir * last_p < p_dir * p_price:
                        for s in range(0, dn - 1):
                            dp[s] = dp[s + 1]
                            db[s] = db[s + 1]
                            dd[s] = dd[s + 1]
                            dr[s] = dr[s + 1]
                            dci[s] = dci[s + 1]
                            dcl[s] = dcl[s + 1]
                        dn -= 1
                    else:
                        if nd > 0:
                            if have_bear:
                                if (1 if dd[0] > 0 else -1) == -1:
                                    mismatch += 1
                                else:
                                    dn = _mw_push_pivot(dp, db, dd, dr, dci, dcl, dn, cap,
                                                        bear_p, bear_b, -1, bear_i)
                            else:
                                skip = True
                        else:
                            if have_bull:
                                if (1 if dd[0] > 0 else -1) == 1:
                                    mismatch += 1
                                else:
                                    dn = _mw_push_pivot(dp, db, dd, dr, dci, dcl, dn, cap,
                                                        bull_p, bull_b, 1, bull_i)
                            else:
                                skip = True
                else:
                    if nd > 0:
                        hf = have_bull
                        fp = bull_p
                        fb = bull_b
                        fi = bull_i
                        hs = have_bear
                        sp2 = bear_p
                        sb2 = bear_b
                        si2 = bear_i
                    else:
                        hf = have_bear
                        fp = bear_p
                        fb = bear_b
                        fi = bear_i
                        hs = have_bull
                        sp2 = bull_p
                        sb2 = bull_b
                        si2 = bull_i
                    if hf and hs:
                        if nd * fp > nd * p_price:
                            dn = _mw_push_pivot(dp, db, dd, dr, dci, dcl, dn, cap, fp, fb, nd, fi)
                            dn = _mw_push_pivot(dp, db, dd, dr, dci, dcl, dn, cap, sp2, sb2, -nd, si2)
                if not skip:
                    if dn > 0 and (1 if dd[0] > 0 else -1) == nd:
                        mismatch += 1
                    else:
                        dn = _mw_push_pivot(dp, db, dd, dr, dci, dcl, dn, cap,
                                            p_price, p_bar, nd, idx)
                    have_bull = False
                    have_bear = False
            else:
                if nd > 0:
                    if have_bull:
                        if p_price * p_dir > bull_p * p_dir:
                            bull_p = p_price
                            bull_b = p_bar
                            bull_i = idx
                    else:
                        have_bull = True
                        bull_p = p_price
                        bull_b = p_bar
                        bull_i = idx
                else:
                    if have_bear:
                        if p_price * p_dir > bear_p * p_dir:
                            bear_p = p_price
                            bear_b = p_bar
                            bear_i = idx
                    else:
                        have_bear = True
                        bear_p = p_price
                        bear_b = p_bar
                        bear_i = idx
        else:
            if adir == 2:
                dn = _mw_push_pivot(dp, db, dd, dr, dci, dcl, dn, cap, p_price, p_bar, nd, idx)

    if dn >= sn:
        dn = 0
    return dn, mismatch


@njit(cache=True)
def _mw_expand_micro(lv_ci, lv_cl, level, idx, out, work_a, work_b, cap):
    """仕様書4.2。レベル`level`の`idx`番目のピボットが束ねるmicropivotsを、
    レベル0の配列内位置の列として `out` に展開する。並び順はindex0が最新。
    戻り値は件数。バッファが足りなければ -1。

    レベル1は [自分のci .. 1つ古い同レベルピボットのci] を両端含めて展開し、
    レベル2以上は下位ピボット列(最後の1つを除く)の展開結果を順に連結する。
    この連結では境界のピボットが重複するが、参考元がそうなっているので
    そのまま再現する。"""
    n_cur = 1
    work_a[0] = idx
    lv = level
    cur = work_a
    nxt = work_b

    while lv >= 2:
        n_nxt = 0
        for t in range(n_cur):
            a = cur[t]
            c0 = lv_ci[lv, a]
            c1 = lv_cl[lv, a]
            if c1 < 0:
                continue
            for j in range(c0, c1):
                if n_nxt >= cap:
                    return -1
                nxt[n_nxt] = j
                n_nxt += 1
        tmp = cur
        cur = nxt
        nxt = tmp
        n_cur = n_nxt
        lv -= 1
        if n_cur == 0:
            return 0

    n_out = 0
    for t in range(n_cur):
        a = cur[t]
        c0 = lv_ci[1, a]
        c1 = lv_cl[1, a]
        if c1 < 0:
            continue
        for k in range(c0, c1 + 1):
            if n_out >= cap:
                return -1
            out[n_out] = k
            n_out += 1
    return n_out


@njit(cache=True)
def _mw_trend_series(prices, n_prices, high_low, trend, out, cap):
    """仕様書6.1(utils/1 の get_trend_series)。戻り値は件数、溢れたら -1。

    参考元の2つの癖をそのまま再現している:
      - oTrend==1 の枝は結果の先頭へ挿入するので、返る並びは絶対indexの降順
        (= 古い順)になる。
      - oTrend!=1 の枝の endLength への代入はwindow内の相対indexであり、
        window起点 startLength を足していない(1つ余分に縮む)。"""
    start_len = 1
    end_len = n_prices
    cnt = 0
    if start_len >= end_len:
        return 0

    dir_ = 1 if prices[0] > prices[1] else -1
    guard = 1 if dir_ == high_low else 0
    o_trend = trend * high_low

    while start_len + guard < end_len:
        peak = prices[start_len]
        for j in range(start_len + 1, end_len):
            if high_low == 1:
                if prices[j] > peak:
                    peak = prices[j]
            else:
                if prices[j] < peak:
                    peak = prices[j]

        pk = -1
        if o_trend == 1:
            for j in range(start_len, end_len):
                if prices[j] == peak:
                    pk = j - start_len
                    break
        else:
            for j in range(end_len - 1, start_len - 1, -1):
                if prices[j] == peak:
                    pk = j - start_len
                    break
        if pk < 0:
            break

        if cnt >= cap:
            return -1
        if o_trend == 1:
            for s in range(cnt, 0, -1):
                out[s] = out[s - 1]
            out[0] = start_len + pk
        else:
            out[cnt] = start_len + pk
        cnt += 1

        if o_trend == 1:
            if start_len + pk == end_len:
                break
            start_len = start_len + pk + 1 + (1 if dir_ > 0 else 0)
        else:
            if pk == 0:
                break
            end_len = pk

    return cnt


@njit(cache=True)
def _mw_leg_ok(mp, newer_i, older_i):
    """仕様書6.3。区間[newer_i .. older_i]に、両端を超える中間ピボットが
    無いこと。両端は区間に含まれるので、超える要素が1つも無ければ
    参考元の max==max(端点) / min==min(端点) と同値になる。"""
    pa = mp[older_i]
    pb = mp[newer_i]
    mx = pa if pa > pb else pb
    mn = pa if pa < pb else pb
    for k in range(newer_i, older_i + 1):
        v = mp[k]
        if v > mx:
            return False
        if v < mn:
            return False
    return True


@njit(cache=True)
def _mw_round3(x):
    """参考元の retracementRatio は precision=3 が既定で math.round(value, 3) を
    通す。math.roundは0から遠い側へ丸めるので、Pythonの偶数丸めは使わない。"""
    if x >= 0.0:
        return np.floor(x * 1000.0 + 0.5) / 1000.0
    return -(np.floor(-x * 1000.0 + 0.5) / 1000.0)


@njit(cache=True)
def _mw_check(p0, p1, p2, p3, p4, p5):
    """仕様書6.4(Waves/3 の checkMotiveWave)。
    戻り値は (種類コード, w2Ratio, w3Ratio, w4Ratio, w5Ratio, mRatio)。
    種類コードは 0=該当なし / 1=推進波 / 2=収束ダイアゴナル / 3=拡大ダイアゴナル。

    分母が0になる組み合わせは参考元では na になり、以降の閾値比較が全て偽に
    なって「該当なし」に落ちるので、ここでも 0 を返す。

    ダイアゴナル2種の分岐は参考元どおり残してあるが、仕様書6.6のとおり
    構造上決して成立しない(実データでも0件であることを確認済み)。"""
    d20 = p1 - p0
    d21 = p2 - p1
    d32 = p3 - p2
    d43 = p4 - p3
    d30 = p3 - p0
    if d20 == 0.0 or d21 == 0.0 or d32 == 0.0 or d43 == 0.0 or d30 == 0.0:
        return 0, 0.0, 0.0, 0.0, 0.0, 0.0

    w2r = _mw_round3((p1 - p2) / d20)
    w3r = _mw_round3((p2 - p3) / d21)
    w4r = _mw_round3((p3 - p4) / d32)
    w5r = _mw_round3((p4 - p5) / d43)
    mr = _mw_round3((p3 - p4) / d30)

    w1_l = abs(p1 - p0)
    w2_l = abs(p2 - p1)
    w3_l = abs(p3 - p2)
    w4_l = abs(p4 - p3)
    w5_l = abs(p5 - p4)

    w3_not_shortest = (w3_l > w1_l) or (w3_l > w5_l)
    tail_intact = (w4r < 1.0) and (w5r > 0.9) and (mr < 1.0)
    motive_intact = (w2r < 1.0) and (w3r > 1.0) and tail_intact
    if not w3_not_shortest:
        return 0, w2r, w3r, w4r, w5r, mr

    direction = 0.0
    if p5 > p0:
        direction = 1.0
    elif p5 < p0:
        direction = -1.0

    # ===== 推進波(仕様書6.4) =====
    if motive_intact and (direction * p1 < direction * p4):
        n_ext = 0
        if w2r != 0.0 and 1.0 / w2r > 2.0:
            n_ext += 1
        if w3r > 2.0:
            n_ext += 1
        if w5r > 2.0:
            n_ext += 1
        if n_ext < 3:
            return _MW_TYPE_IMPULSE, w2r, w3r, w4r, w5r, mr

    # ===== ダイアゴナル2種(仕様書6.4・6.6) =====
    # 参考元どおりに書いてあるが、この分岐は決して真にならない。理由は2つ:
    #   ① 比率の矛盾: w2Ratio = w2の長さ/w1の長さ、w3Ratio = w3の長さ/w2の長さ
    #      なので isMotiveWave は「w2<w1 かつ w3>w2」を意味し、
    #      収束(w1>w2>w3)とも拡大(w1<w2<w3)とも両立しない。
    #   ② 形の矛盾: P0はmicropivots内の最安値(pullbackSeriesの先頭)、
    #      P5は対象ピボット自身=最高値。よって収束が要求する「P5<P3」も
    #      拡大が要求する「P2<P0」も起こり得ない。
    # ①②とも実データ(USDJPY15分足58万本)で0件であることを確認済み。
    # 参考元の挙動を変えないため、条件を緩める独自拡張は入れていない。
    if motive_intact and (direction * p1 > direction * p4):
        if (w1_l > w2_l) and (w2_l > w3_l) and (w3_l > w4_l) and (w4_l > w5_l):
            return _MW_TYPE_CONTRACTING, w2r, w3r, w4r, w5r, mr
        if (w1_l < w2_l) and (w2_l < w3_l) and (w3_l < w4_l) and (w4_l < w5_l):
            return _MW_TYPE_EXPANDING, w2r, w3r, w4r, w5r, mr

    return 0, w2r, w3r, w4r, w5r, mr


@njit(cache=True)
def _mw_scan_core(high_a, low_a, zigzag_length, depth, want_level, level_type,
                  repaint, hit_cap):
    """仕様書3〜6章。ZigZagを更新しながら各レベルを走査し、条件を満たした
    「生の検出ヒット」を全て吐く。pattern_idによる重複除去は呼び出し元の
    Python側で行う。

    同じピボットを毎バー走査し直すのは無駄なので、レベルごとに「直前に走査した
    対象ピボットの(バー, 価格)」を覚えておき、変わっていなければ丸ごと飛ばす。
    参考元も同じピボットに対する2度目の検出は existingPattern で弾いている。"""
    n = high_a.shape[0]
    cap = depth
    micro_cap = _MW_MICRO_CAPACITY
    series_cap = _MW_SERIES_CAPACITY

    zz_price = np.zeros(cap)
    zz_bar = np.zeros(cap, dtype=np.int64)
    zz_dir = np.zeros(cap, dtype=np.int64)
    zz_ratio = np.ones(cap)
    zz_ci = np.full(cap, -1, dtype=np.int64)
    zz_cl = np.full(cap, -1, dtype=np.int64)
    zz_n = 0

    lv_price = np.zeros((_MW_MAX_LEVELS, cap))
    lv_bar = np.zeros((_MW_MAX_LEVELS, cap), dtype=np.int64)
    lv_dir = np.zeros((_MW_MAX_LEVELS, cap), dtype=np.int64)
    lv_ratio = np.ones((_MW_MAX_LEVELS, cap))
    lv_ci = np.full((_MW_MAX_LEVELS, cap), -1, dtype=np.int64)
    lv_cl = np.full((_MW_MAX_LEVELS, cap), -1, dtype=np.int64)

    micro_idx = np.zeros(micro_cap, dtype=np.int64)
    work_a = np.zeros(micro_cap, dtype=np.int64)
    work_b = np.zeros(micro_cap, dtype=np.int64)
    mp_price = np.zeros(micro_cap)
    ts = np.zeros(series_cap, dtype=np.int64)
    ps = np.zeros(series_cap, dtype=np.int64)

    last_scan_bar = np.full(_MW_MAX_LEVELS, -1, dtype=np.int64)
    last_scan_price = np.zeros(_MW_MAX_LEVELS)

    hit_bar = np.zeros(hit_cap, dtype=np.int64)
    hit_level = np.zeros(hit_cap, dtype=np.int64)
    hit_type = np.zeros(hit_cap, dtype=np.int64)
    hit_dir = np.zeros(hit_cap, dtype=np.int64)
    hit_pbar = np.zeros((hit_cap, 6), dtype=np.int64)
    hit_pprice = np.zeros((hit_cap, 6))
    hit_ratio = np.zeros((hit_cap, 5))
    n_hits = 0
    hit_overflow = 0
    level_overflow = 0
    mismatch_total = 0
    micro_overflow = 0
    series_overflow = 0

    min_size = 3 if repaint else 4
    target_idx = 1 if repaint else 2

    for i in range(n):
        if i + 1 < zigzag_length:
            continue

        # ===== 仕様書3.1 =====
        p_high = high_a[i]
        p_high_bar = i
        p_low = low_a[i]
        p_low_bar = i
        for k in range(i - zigzag_length + 1, i + 1):
            if high_a[k] >= p_high:
                p_high = high_a[k]
                p_high_bar = k
            if low_a[k] <= p_low:
                p_low = low_a[k]
                p_low_bar = k
        is_high_pivot = (p_high_bar == i)
        is_low_pivot = (p_low_bar == i)

        p_dir = 1
        if zz_n > 0:
            p_dir = 1 if zz_dir[0] > 0 else -1
        distance = 0
        if zz_n > 0:
            distance = i - zz_bar[0]
        overflow = (zz_n > 0) and (distance >= zigzag_length)

        force_double = False
        if zz_n > 1:
            llast_price = zz_price[1]
            if p_dir == 1 and is_low_pivot:
                force_double = p_low < llast_price
            elif p_dir == -1 and is_high_pivot:
                force_double = p_high > llast_price

        new_pivot = False
        update_last = False

        # ===== 仕様書3.2 ① =====
        if ((p_dir == 1 and is_high_pivot) or (p_dir == -1 and is_low_pivot)) and zz_n >= 1:
            value = p_high if p_dir == 1 else p_low
            last_dir = zz_dir[0]
            if value * last_dir >= zz_price[0] * last_dir:
                for s in range(0, zz_n - 1):
                    zz_price[s] = zz_price[s + 1]
                    zz_bar[s] = zz_bar[s + 1]
                    zz_dir[s] = zz_dir[s + 1]
                    zz_ratio[s] = zz_ratio[s + 1]
                zz_n -= 1
                zz_n = _mw_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_ci, zz_cl,
                                      zz_n, cap, value, i, p_dir, -1)
                new_pivot = True
                update_last = True

        # ===== 仕様書3.2 ②(演算子優先順位の非対称性を含む) =====
        if (p_dir == 1 and is_low_pivot) or (
            p_dir == -1 and is_high_pivot and ((not new_pivot) or force_double)
        ):
            value = p_low if p_dir == 1 else p_high
            zz_n = _mw_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_ci, zz_cl,
                                  zz_n, cap, value, i, -p_dir, -1)
            new_pivot = True

        # ===== 仕様書3.2 ③ =====
        if overflow and not new_pivot:
            value = p_low if p_dir == 1 else p_high
            value_bar = p_low_bar if p_dir == 1 else p_high_bar
            zz_n = _mw_push_pivot(zz_price, zz_bar, zz_dir, zz_ratio, zz_ci, zz_cl,
                                  zz_n, cap, value, value_bar, -p_dir, -1)
            new_pivot = True

        # ===== 仕様書5.1: 走査のトリガ =====
        if not new_pivot:
            continue
        if (not repaint) and update_last:
            continue

        for s in range(zz_n):
            lv_price[0, s] = zz_price[s]
            lv_bar[0, s] = zz_bar[s]
            lv_dir[0, s] = zz_dir[s]
            lv_ratio[0, s] = zz_ratio[s]
            lv_ci[0, s] = -1
            lv_cl[0, s] = -1
        cur_n = zz_n
        level = 0

        # ===== 仕様書5.2: レベルを登りながら走査 =====
        while cur_n >= min_size:
            level_matches = (level >= want_level) if level_type == _MW_LEVEL_TYPE_MINIMUM \
                else (level == want_level)
            # レベル0のピボットは micropivots が空なので走査しても何も出ない。
            if level_matches and level >= 1:
                t_dir = lv_dir[level, target_idx]
                t_adir = t_dir if t_dir >= 0 else -t_dir
                t_bar = lv_bar[level, target_idx]
                t_price = lv_price[level, target_idx]
                if t_adir == 2 and not (
                    last_scan_bar[level] == t_bar and last_scan_price[level] == t_price
                ):
                    last_scan_bar[level] = t_bar
                    last_scan_price[level] = t_price

                    n_micro = _mw_expand_micro(lv_ci, lv_cl, level, target_idx,
                                               micro_idx, work_a, work_b, micro_cap)
                    if n_micro < 0:
                        micro_overflow += 1
                    elif n_micro >= 5:
                        for t in range(n_micro):
                            mp_price[t] = lv_price[0, micro_idx[t]]
                        wave_dir = 1 if t_dir > 0 else -1

                        n_ts = _mw_trend_series(mp_price, n_micro, wave_dir, wave_dir,
                                                ts, series_cap)
                        n_ps = _mw_trend_series(mp_price, n_micro, -wave_dir, wave_dir,
                                                ps, series_cap)
                        if n_ts < 0 or n_ps < 0:
                            series_overflow += 1
                        elif n_ts >= 2 and n_ps >= 3:
                            p0 = ps[0]
                            # ===== 仕様書6.2: 4重ループ =====
                            for a1 in range(0, n_ts - 1):
                                p1 = ts[a1]
                                if p0 <= p1:
                                    continue
                                if not _mw_leg_ok(mp_price, p1, p0):
                                    continue
                                for a2 in range(1, n_ps - 1):
                                    p2 = ps[a2]
                                    if p1 <= p2:
                                        continue
                                    if not _mw_leg_ok(mp_price, p2, p1):
                                        continue
                                    for a3 in range(a1 + 1, n_ts):
                                        p3 = ts[a3]
                                        if p2 <= p3:
                                            continue
                                        if not _mw_leg_ok(mp_price, p3, p2):
                                            continue
                                        for a4 in range(a2 + 1, n_ps):
                                            p4 = ps[a4]
                                            if p3 <= p4 or p4 <= 0:
                                                continue
                                            if not _mw_leg_ok(mp_price, p4, p3):
                                                continue
                                            if not _mw_leg_ok(mp_price, 0, p4):
                                                continue

                                            v0 = mp_price[p0]
                                            v1 = mp_price[p1]
                                            v2 = mp_price[p2]
                                            v3 = mp_price[p3]
                                            v4 = mp_price[p4]
                                            v5 = mp_price[0]
                                            wt, r2, r3, r4, r5, rm = _mw_check(
                                                v0, v1, v2, v3, v4, v5)
                                            if wt == 0:
                                                continue
                                            if n_hits >= hit_cap:
                                                hit_overflow += 1
                                                continue
                                            hit_bar[n_hits] = i
                                            hit_level[n_hits] = level
                                            hit_type[n_hits] = wt
                                            # 出力はシグナルの向き(仕様書8.2)。
                                            hit_dir[n_hits] = -1 if v5 > v0 else 1
                                            hit_pbar[n_hits, 0] = lv_bar[0, micro_idx[p0]]
                                            hit_pbar[n_hits, 1] = lv_bar[0, micro_idx[p1]]
                                            hit_pbar[n_hits, 2] = lv_bar[0, micro_idx[p2]]
                                            hit_pbar[n_hits, 3] = lv_bar[0, micro_idx[p3]]
                                            hit_pbar[n_hits, 4] = lv_bar[0, micro_idx[p4]]
                                            hit_pbar[n_hits, 5] = lv_bar[0, micro_idx[0]]
                                            hit_pprice[n_hits, 0] = v0
                                            hit_pprice[n_hits, 1] = v1
                                            hit_pprice[n_hits, 2] = v2
                                            hit_pprice[n_hits, 3] = v3
                                            hit_pprice[n_hits, 4] = v4
                                            hit_pprice[n_hits, 5] = v5
                                            hit_ratio[n_hits, 0] = r2
                                            hit_ratio[n_hits, 1] = r3
                                            hit_ratio[n_hits, 2] = r4
                                            hit_ratio[n_hits, 3] = r5
                                            hit_ratio[n_hits, 4] = rm
                                            n_hits += 1

            if level + 1 >= _MW_MAX_LEVELS:
                level_overflow += 1
                break
            nxt_n, mm = _mw_build_next_level(
                lv_price[level], lv_bar[level], lv_dir[level], cur_n,
                lv_price[level + 1], lv_bar[level + 1], lv_dir[level + 1],
                lv_ratio[level + 1], lv_ci[level + 1], lv_cl[level + 1], cap,
            )
            mismatch_total += mm
            if nxt_n == 0:
                break
            cur_n = nxt_n
            level += 1

    return (
        hit_bar[:n_hits], hit_level[:n_hits], hit_type[:n_hits], hit_dir[:n_hits],
        hit_pbar[:n_hits], hit_pprice[:n_hits], hit_ratio[:n_hits],
        hit_overflow, level_overflow, mismatch_total, micro_overflow, series_overflow,
    )


# 同時監視できる未決着パターンの上限。溢れたら例外にする(黙って取りこぼさない)。
_MW_SLOT_CAPACITY = 4096


def _mw_state(
    high: pd.Series, low: pd.Series, close: pd.Series,
    zigzag_length: int = 5,
    depth: int = 200,
    zigzag_level: int = 1,
    level_type: str = "minimum",
    repaint: bool = True,
) -> dict[str, Any]:
    """モジュール冒頭のコメントと docs/pattern_spec_motive_wave.md 参照。
    推進波・収束ダイアゴナル・拡大ダイアゴナルの3種類×上下の計6指標は、
    共通の多段ZigZagから同時に検出されるためまとめて1回で計算する。

    戻り値:
      各パターン名 -> candidate/confirmed/invalidated のBoolean系列
      "events" -> 検出した全イベントを時系列順に1件1レコードで並べたリスト
                  (仕様書9.1。件数や構成点が要る用途はこちらを読む)
    """
    n = len(high)
    idx_index = high.index
    high_a = np.ascontiguousarray(high.to_numpy(dtype=float))
    low_a = np.ascontiguousarray(low.to_numpy(dtype=float))

    # 仕様書8.3。UIを介さない呼び出し(保存済みJSON経由など)があるため、
    # 有効範囲はエンジン側でも保証する。
    zigzag_length = max(_MW_ZIGZAG_LENGTH_MIN, int(zigzag_length))
    depth = min(_MW_DEPTH_MAX, max(6, int(depth)))
    zigzag_level = max(_MW_LEVEL_MIN, int(zigzag_level))
    lt_code = _MW_LEVEL_TYPE_CHOICES.get(str(level_type).strip().lower(),
                                         _MW_LEVEL_TYPE_MINIMUM)
    repaint = bool(repaint)

    def _pack(flags: dict[str, dict[str, np.ndarray]], events: list[dict]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in _MW_PATTERN_NAMES.values():
            out[name] = {
                status: pd.Series(flags[name][status], index=idx_index)
                for status in _MW_STATUS_NAMES
            }
        out["events"] = events
        return out

    flags = {
        name: {status: np.zeros(n, dtype=bool) for status in _MW_STATUS_NAMES}
        for name in _MW_PATTERN_NAMES.values()
    }
    if n == 0:
        return _pack(flags, [])

    # ①njitで走査して生の検出ヒットを吐く。枠が足りなければ広げて計算し直す。
    hit_cap = max(4096, n // 16)
    while True:
        (
            hit_bar, hit_level, hit_type, hit_dir,
            hit_pbar, hit_pprice, hit_ratio,
            hit_overflow, level_overflow, mismatch_total,
            micro_overflow, series_overflow,
        ) = _mw_scan_core(high_a, low_a, zigzag_length, depth, zigzag_level,
                          lt_code, repaint, hit_cap)
        if hit_overflow == 0:
            break
        hit_cap *= 4

    if mismatch_total:
        raise RuntimeError(
            f"多段ZigZagでピボットの方向が交互になりませんでした({mismatch_total}回)。"
            f"engine/chart_patterns.py::_mw_build_next_levelの実装を確認してください。"
        )
    if micro_overflow:
        raise RuntimeError(
            f"micropivotsの展開バッファが不足しました({micro_overflow}回)。"
            f"engine/chart_patterns.py::_MW_MICRO_CAPACITYを増やしてください。"
        )
    if series_overflow:
        raise RuntimeError(
            f"trendSeries/pullbackSeriesのバッファが不足しました({series_overflow}回)。"
            f"engine/chart_patterns.py::_MW_SERIES_CAPACITYを増やしてください。"
        )

    # ②Python側でpattern_idの集合を使って重複を落とす(共通管理仕様7.1)。
    seen: set[str] = set()
    cand_pattern_id: list[str] = []
    cand_name: list[str] = []
    cand_rows: list[int] = []
    for k in range(len(hit_bar)):
        wt = int(hit_type[k])
        sdir = int(hit_dir[k])
        name = _MW_PATTERN_NAMES[(wt, sdir)]
        pattern_id = _make_pattern_id(name, hit_pbar[k])
        key = _make_dedup_key(name, hit_pbar[k], newest_first=False)
        if key in seen:
            continue
        seen.add(key)
        cand_pattern_id.append(pattern_id)
        cand_name.append(name)
        cand_rows.append(k)

    n_cand = len(cand_rows)
    if n_cand == 0:
        return _pack(flags, [])

    rows = np.array(cand_rows, dtype=np.int64)
    cand_bar = hit_bar[rows].astype(np.int64)
    cand_dir = hit_dir[rows].astype(np.int64)
    # 判定水準(仕様書8.1) - ネックラインはP4、極値はP5。
    cand_neck = np.ascontiguousarray(hit_pprice[rows, 4])
    cand_extreme = np.ascontiguousarray(hit_pprice[rows, 5])

    order = np.argsort(cand_bar, kind="stable")

    # ③njitで各パターンのConfirmed/Invalidatedを追跡する。判定の中身は
    #   トリプルトップ等と完全に同じなので _rrcp_resolve_core を流用する。
    status, resolve_bar, slot_overflow = _rrcp_resolve_core(
        high_a, low_a,
        np.ascontiguousarray(cand_bar[order]),
        np.ascontiguousarray(cand_dir[order]),
        np.ascontiguousarray(cand_neck[order]),
        np.ascontiguousarray(cand_extreme[order]),
        _MW_SLOT_CAPACITY,
    )
    if slot_overflow:
        raise RuntimeError(
            f"チャートパターンの同時監視スロットが不足しました"
            f"(上限{_MW_SLOT_CAPACITY}件、取りこぼし{slot_overflow}件)。"
            f"engine/chart_patterns.py::_MW_SLOT_CAPACITYを増やしてください。"
        )

    status_by_cand = np.empty(n_cand, dtype=np.int64)
    resolve_by_cand = np.empty(n_cand, dtype=np.int64)
    status_by_cand[order] = status
    resolve_by_cand[order] = resolve_bar

    events: list[dict] = []
    for j, k in enumerate(cand_rows):
        name = cand_name[j]
        base = {
            "pattern_id": cand_pattern_id[j],
            "pattern_type": name,
            "level": int(hit_level[k]),
            "point_bars": [int(b) for b in hit_pbar[k]],
            "point_prices": [float(p) for p in hit_pprice[k]],
            "neckline_price": float(cand_neck[j]),
            "extreme_price": float(cand_extreme[j]),
            "ratios": [float(r) for r in hit_ratio[k]],
        }
        cb = int(cand_bar[j])
        events.append(dict(base, status="candidate", event_bar=cb))
        flags[name]["candidate"][cb] = True

        st = int(status_by_cand[j])
        if st != 0:
            rb = int(resolve_by_cand[j])
            status_name = _MW_STATUS_NAMES[st]
            events.append(dict(base, status=status_name, event_bar=rb))
            flags[name][status_name][rb] = True

    events.sort(key=lambda e: (e["event_bar"], e["pattern_id"], e["status"]))
    return _pack(flags, events)


def _mw_indicator(pattern_name: str):
    """6種類の公開関数を同じ形で作るためのファクトリ。どれを呼んでも内部では
    共通の多段ZigZagを1回計算し、該当パターンのBoolean系列だけを取り出す。"""

    def _fn(
        high: pd.Series, low: pd.Series, close: pd.Series,
        state: str = "confirmed",
        zigzag_length: int = 5,
        depth: int = 200,
        zigzag_level: int = 1,
        level_type: str = "minimum",
        repaint: bool = True,
        **p,
    ) -> np.ndarray:
        result = _mw_state(
            high, low, close, zigzag_length, depth, zigzag_level, level_type, repaint,
        )[pattern_name]
        key = state if state in _MW_STATUS_NAMES else "confirmed"
        return result[key].to_numpy(dtype=float)

    _fn.__name__ = pattern_name
    _fn.__qualname__ = pattern_name
    _fn.__doc__ = (
        f"{pattern_name}(エリオット推進波/ダイアゴナル) - モジュール冒頭のコメントと\n"
        "    docs/pattern_spec_motive_wave.md 参照。\n"
        "    Candidate/Confirmed/Invalidatedの3状態をstateパラメータで選べる。\n\n"
        "    条件式が要求するBoolean系列を返すため、同一バーに複数イベントが\n"
        "    乗った場合は1つに潰れる。件数や各パターンの構成点が要る用途では\n"
        "    _mw_state(...)[\"events\"] を読むこと。"
    )
    return _fn


impulse_wave_bullish = _mw_indicator("impulse_wave_bullish")
impulse_wave_bearish = _mw_indicator("impulse_wave_bearish")


# ---------------------------------------------------------------------------
# フラッグ / ペナント(4種) - B方式実装。
#
# 検出仕様は docs/pattern_spec_flags_pennants.md (v1.0) に文章・数式・条件として
# 全て書き出してあり、この実装はその仕様書だけを入力として書いている(参考元の
# Pine Scriptコードを直接移植したものではない)。参考元は
# 「Flags and Pennants [Trendoscope®]」(Pine v6, CC BY-NC-SA 4.0,
# (c) Trendoscope Pty Ltd)と、それがimportする chartpatterns/10 /
# LineWrapper/2 / ohlc/3 / ZigzagLite/3。
#
# 【不明】参考元は ZigzagLite/3 と LineWrapper/2 を指定しているが、TradingViewは
#   公開ライブラリの最新版しか表示しないため、その版そのものは取得できていない。
#   ZigZag部分は ZigzagLite/4(= Zigzag最新版から指標対応を除いたもの、行単位で
#   照合済み)を、LineWrapperの get_price は最新版を書き起こしている。
#   指定版との差分は不明(仕様書0.3)。
#
# アルゴリズムの骨格(詳細は仕様書4〜8章):
#   1. 長さ/保持数の違う4本のZigZagを同時に走らせる(3/144, 5/89, 8/55, 13/34)。
#   2. どれかに新しいピボットが出たら、そのZigZagをレベル0から順に上位へ登り、
#      各レベルで「新しい方から5点」を取って土台パターンを探す。
#   3. 土台パターン: 5点を1つ飛ばしに結んだ2本のトレンドラインが、区間内の
#      ローソクを実体で突き抜けないこと。2本の傾きから13種類に分類する。
#   4. そのうち許可された5種類(上昇/下降チャネル、上昇/下降ウェッジ(収束)、
#      収束/上昇/下降トライアングル)だけが、フラッグ・ペナントの土台になる。
#   5. 土台の手前を遡って「旗竿」(強い一方向の動き)を探す。見つかれば成立。
#   6. Confirmed/Invalidatedの水準は参考元が findFNP 内で定義している
#      invalidationPrice / validationPrice をそのまま使う(仕様書8.1)。
# ---------------------------------------------------------------------------

_FNP_MAX_LEVELS = 32
_FNP_NUM_ZIGZAGS = 4
# 5点固定(参考元の ScanProperties.new(offset, 5, ...))。
_FNP_NUMBER_OF_PIVOTS = 5
_FNP_OFFSET = 0

# 土台パターンの13種類(仕様書6.4)。フラッグ/ペナントの土台になり得るのは
# 参考元の allowedPatterns が true にしている7種類だけ。
_FNP_BASE_PATTERN_NAMES = {
    1: "ascending_channel", 2: "descending_channel", 3: "ranging_channel",
    4: "rising_wedge_expanding", 5: "falling_wedge_expanding",
    6: "diverging_triangle",
    7: "ascending_triangle_expanding", 8: "descending_triangle_expanding",
    9: "rising_wedge_contracting", 10: "falling_wedge_contracting",
    11: "converging_triangle",
    12: "descending_triangle_contracting", 13: "ascending_triangle_contracting",
}
# index = 土台パターンの種類コード(0〜13)。参考元そのまま。
_FNP_ALLOWED_PATTERNS = np.array(
    [False, True, True, False, False, False, False, False, False,
     True, True, True, True, True], dtype=np.bool_)
_FNP_ALLOWED_LAST_DIRS = np.array(
    [0, -1, 1, 0, 0, 0, 0, 0, 0, -1, 1, 0, 1, -1], dtype=np.int64)

_FNP_TYPE_BULL_FLAG = 1
_FNP_TYPE_BEAR_FLAG = 2
_FNP_TYPE_BULL_PENNANT = 3
_FNP_TYPE_BEAR_PENNANT = 4

_FNP_PATTERN_NAMES = {
    _FNP_TYPE_BULL_FLAG: "bullish_flag",
    _FNP_TYPE_BEAR_FLAG: "bearish_flag",
    _FNP_TYPE_BULL_PENNANT: "bullish_pennant",
    _FNP_TYPE_BEAR_PENNANT: "bearish_pennant",
}
_FNP_STATUS_NAMES = ("candidate", "confirmed", "invalidated")

# 仕様書1章の有効範囲。stepはUI表示上の刻みでありエンジン側では強制しない。
_FNP_ZIGZAG_LENGTH_MIN = 1
_FNP_DEPTH_MAX = 500
_FNP_ERROR_THRESHOLD_MIN = 0.0
_FNP_ERROR_THRESHOLD_MAX = 100.0
_FNP_FLAT_THRESHOLD_MIN = 0.0
_FNP_FLAT_THRESHOLD_MAX = 30.0
_FNP_FLAG_RATIO_MIN = 0.1
_FNP_FLAG_RATIO_MAX = 1.0
_FNP_MAX_PATTERNS_MIN = 1


@njit(cache=True)
def _fnp_push_pivot(price, bar, dirs, ratios, bratios, n, cap,
                    new_price, new_bar, new_sign):
    """ZigZag配列(index0が最新)の先頭へピボットを1つ積む。_rrcp_push_pivot と
    同じ計算に加えて、仕様書3.3の barRatio(バー間隔の比)も出す。barRatio は
    checkBarRatio が有効なときだけ使われる。"""
    out_dir = new_sign
    out_ratio = 1.0
    out_bratio = 1.0
    if n >= 2:
        last_price = price[0]
        llast_price = price[1]
        last_bar = bar[0]
        llast_bar = bar[1]
        if new_sign * new_price > new_sign * llast_price:
            out_dir = new_sign * 2
        denom = abs(llast_price - last_price)
        if denom > 0.0:
            out_ratio = np.floor(abs(last_price - new_price) / denom * 1000.0 + 0.5) / 1000.0
        else:
            out_ratio = np.nan
        bdenom = abs(llast_bar - last_bar)
        if bdenom > 0:
            out_bratio = np.floor(abs(last_bar - new_bar) / bdenom * 1000.0 + 0.5) / 1000.0
        else:
            out_bratio = np.nan
    m = n if n < cap else cap - 1
    for s in range(m, 0, -1):
        price[s] = price[s - 1]
        bar[s] = bar[s - 1]
        dirs[s] = dirs[s - 1]
        ratios[s] = ratios[s - 1]
        bratios[s] = bratios[s - 1]
    price[0] = new_price
    bar[0] = new_bar
    dirs[0] = out_dir
    ratios[0] = out_ratio
    bratios[0] = out_bratio
    if n < cap:
        n += 1
    return n


@njit(cache=True)
def _fnp_build_next_level(sp, sb, sd, sn, dp, db, dd, dr, dbr, cap):
    """仕様書4章。_rrcp_build_next_level と同じアルゴリズムに barRatio を
    足したもの。戻り値は (上位のピボット数, 方向不整合の回数)。"""
    dn = 0
    mismatch = 0
    have_bull = False
    bull_p = 0.0
    bull_b = 0
    have_bear = False
    bear_p = 0.0
    bear_b = 0

    for idx in range(sn - 1, -1, -1):
        p_price = sp[idx]
        p_bar = sb[idx]
        p_dir = sd[idx]
        nd = 1 if p_dir > 0 else -1
        adir = p_dir if p_dir >= 0 else -p_dir

        if dn > 0:
            last_d = 1 if dd[0] > 0 else -1
            last_p = dp[0]
            if adir == 2:
                skip = False
                if last_d == nd:
                    if p_dir * last_p < p_dir * p_price:
                        for s in range(0, dn - 1):
                            dp[s] = dp[s + 1]
                            db[s] = db[s + 1]
                            dd[s] = dd[s + 1]
                            dr[s] = dr[s + 1]
                            dbr[s] = dbr[s + 1]
                        dn -= 1
                    else:
                        if nd > 0:
                            if have_bear:
                                if (1 if dd[0] > 0 else -1) == -1:
                                    mismatch += 1
                                else:
                                    dn = _fnp_push_pivot(dp, db, dd, dr, dbr, dn, cap,
                                                         bear_p, bear_b, -1)
                            else:
                                skip = True
                        else:
                            if have_bull:
                                if (1 if dd[0] > 0 else -1) == 1:
                                    mismatch += 1
                                else:
                                    dn = _fnp_push_pivot(dp, db, dd, dr, dbr, dn, cap,
                                                         bull_p, bull_b, 1)
                            else:
                                skip = True
                else:
                    if nd > 0:
                        hf = have_bull
                        fp = bull_p
                        fb = bull_b
                        hs = have_bear
                        sp2 = bear_p
                        sb2 = bear_b
                    else:
                        hf = have_bear
                        fp = bear_p
                        fb = bear_b
                        hs = have_bull
                        sp2 = bull_p
                        sb2 = bull_b
                    if hf and hs:
                        if nd * fp > nd * p_price:
                            dn = _fnp_push_pivot(dp, db, dd, dr, dbr, dn, cap, fp, fb, nd)
                            dn = _fnp_push_pivot(dp, db, dd, dr, dbr, dn, cap, sp2, sb2, -nd)
                if not skip:
                    if dn > 0 and (1 if dd[0] > 0 else -1) == nd:
                        mismatch += 1
                    else:
                        dn = _fnp_push_pivot(dp, db, dd, dr, dbr, dn, cap, p_price, p_bar, nd)
                    have_bull = False
                    have_bear = False
            else:
                if nd > 0:
                    if have_bull:
                        if p_price * p_dir > bull_p * p_dir:
                            bull_p = p_price
                            bull_b = p_bar
                    else:
                        have_bull = True
                        bull_p = p_price
                        bull_b = p_bar
                else:
                    if have_bear:
                        if p_price * p_dir > bear_p * p_dir:
                            bear_p = p_price
                            bear_b = p_bar
                    else:
                        have_bear = True
                        bear_p = p_price
                        bear_b = p_bar
        else:
            if adir == 2:
                dn = _fnp_push_pivot(dp, db, dd, dr, dbr, dn, cap, p_price, p_bar, nd)

    if dn >= sn:
        dn = 0
    return dn, mismatch


@njit(cache=True)
def _fnp_line_price(x1, y1, x2, y2, bar):
    """仕様書5.1(LineWrapper の get_price)。2点を通る直線のbar位置での値。"""
    return y1 + (bar - x1) * (y2 - y1) / (x2 - x1)


@njit(cache=True)
def _fnp_inspect_line(open_a, high_a, low_a, close_a, x1, y1, x2, y2,
                      start_bar, end_bar, other_bar, direction):
    """仕様書6.2。1本のトレンドラインが区間[start_bar, end_bar]のローソクに
    対して妥当かを見る。戻り値は (妥当か, スコア)。

      - 実体(始値と終値の内側)を突き抜けたら即座に不成立。
      - ラインがそのバーの値幅[安値,高値]の中を通ったらスコア+1。
      - 通らなかったバーが other_bar(トレンドラインに使わなかった方の
        構成点)なら不成立。"""
    valid = True
    score = 0.0
    for b in range(start_bar, end_bar + 1):
        o = open_a[b]
        h = high_a[b]
        l = low_a[b]
        c = close_a[b]
        if direction > 0:
            bar_price = h
            bar_out = l
        else:
            bar_price = l
            bar_out = h
        line_price = _fnp_line_price(x1, y1, x2, y2, b)
        body_min = o * direction
        cd = c * direction
        if cd < body_min:
            body_min = cd
        if line_price * direction < body_min:
            valid = False
            break
        if (line_price * direction >= bar_out * direction) and (line_price * direction <= bar_price * direction):
            score += 1.0
        elif b == other_bar:
            valid = False
            break
    return valid, score


@njit(cache=True)
def _fnp_inspect3(open_a, high_a, low_a, close_a,
                  b0, p0, b1, p1, b2, p2, start_bar, end_bar, direction):
    """仕様書6.2。3点から3通りの引き方を試し、スコアが最大のものを採る。
    戻り値は (妥当か, x1, y1, x2, y2)。"""
    v1, s1 = _fnp_inspect_line(open_a, high_a, low_a, close_a, b0, p0, b2, p2,
                               start_bar, end_bar, b1, direction)
    v2, s2 = _fnp_inspect_line(open_a, high_a, low_a, close_a, b0, p0, b1, p1,
                               start_bar, end_bar, b2, direction)
    v3, s3 = _fnp_inspect_line(open_a, high_a, low_a, close_a, b1, p1, b2, p2,
                               start_bar, end_bar, b0, direction)
    m23 = s2 if s2 > s3 else s3
    m13 = s1 if s1 > s3 else s3
    if v1 and s1 > m23:
        return v1, b0, p0, b2, p2
    if v2 and s2 > m13:
        return v2, b0, p0, b1, p1
    return v3, b1, p1, b2, p2


@njit(cache=True)
def _fnp_is_same(f_price, f_bar, s_price, s_bar, s_ratio, s_bratio,
                 t_price, t_bar, t_ratio, t_bratio,
                 error_ratio, check_bar_ratio, bar_ratio_limit):
    """仕様書6.1(chartpatterns の isSame)。3点が「同じ傾き」または
    「同じ値幅比」で並んでいるかを見る。"""
    r1 = (s_price - f_price) / (s_bar - f_bar)
    r2 = (t_price - s_price) / (t_bar - s_bar)
    rmax = r1 if r1 > r2 else r2
    rmin = r1 if r1 < r2 else r2
    ratio_max = t_ratio if t_ratio > s_ratio else s_ratio
    ratio_min = t_ratio if t_ratio < s_ratio else s_ratio

    ok = (rmin >= (1.0 - error_ratio) * rmax) or (ratio_min >= (1.0 - error_ratio) * ratio_max)
    if not ok:
        return False
    if check_bar_ratio:
        hi = 1.0 / bar_ratio_limit
        if not (bar_ratio_limit <= t_bratio <= hi):
            return False
        if not (bar_ratio_limit <= s_bratio <= hi):
            return False
    return True


@njit(cache=True)
def _fnp_resolve_pattern_type(t1p1, t1p2, t2p1, t2p2, bar_diff, flat_ratio):
    """仕様書6.4(resolvePatternName)。2本のトレンドラインの端点価格から
    13種類のどれかに分類する。0は「該当なし」。"""
    if t1p1 > t2p1:
        min_t2 = t2p1 if t2p1 < t2p2 else t2p2
        max_t1 = t1p1 if t1p1 > t1p2 else t1p2
        upper_angle = (t1p2 - min_t2) / (t1p1 - min_t2)
        lower_angle = (t2p2 - max_t1) / (t2p1 - max_t1)
    else:
        min_t1 = t1p1 if t1p1 < t1p2 else t1p2
        max_t2 = t2p1 if t2p1 > t2p2 else t2p2
        upper_angle = (t2p2 - min_t1) / (t2p1 - min_t1)
        lower_angle = (t1p2 - max_t2) / (t1p1 - max_t2)

    if upper_angle > 1.0 + flat_ratio:
        up = 1
    elif upper_angle < 1.0 - flat_ratio:
        up = -1
    else:
        up = 0
    if lower_angle > 1.0 + flat_ratio:
        low = -1
    elif lower_angle < 1.0 - flat_ratio:
        low = 1
    else:
        low = 0

    start_diff = abs(t1p1 - t2p1)
    end_diff = abs(t1p2 - t2p2)
    min_diff = start_diff if start_diff < end_diff else end_diff
    price_diff = abs(start_diff - end_diff) / bar_diff
    if price_diff > 0.0:
        probable_converging_bars = min_diff / price_diff
    else:
        probable_converging_bars = np.inf

    is_expanding = end_diff > start_diff
    is_contracting = end_diff < start_diff
    is_channel = (probable_converging_bars > 2.0 * bar_diff) \
        or ((not is_expanding) and (not is_contracting)) \
        or (up == 0 and low == 0)

    s1 = 0
    d1 = t1p1 - t2p1
    if d1 > 0.0:
        s1 = 1
    elif d1 < 0.0:
        s1 = -1
    s2 = 0
    d2 = t1p2 - t2p2
    if d2 > 0.0:
        s2 = 1
    elif d2 < 0.0:
        s2 = -1
    if s1 != s2:
        return 0

    if is_channel:
        if up > 0 and low > 0:
            return 1
        if up < 0 and low < 0:
            return 2
        return 3
    if is_expanding:
        if up > 0 and low > 0:
            return 4
        if up < 0 and low < 0:
            return 5
        if up > 0 and low < 0:
            return 6
        if up > 0 and low == 0:
            return 7
        if up == 0 and low < 0:
            return 8
        return 0
    if is_contracting:
        if up > 0 and low > 0:
            return 9
        if up < 0 and low < 0:
            return 10
        if up < 0 and low > 0:
            return 11
        if low == 0:
            return 12 if up < 0 else 1
        if up == 0:
            return 13 if low > 0 else 2
        return 0
    return 0


@njit(cache=True)
def _fnp_find_fnp(zz_price, zz_bar, zz_dir, zz_n,
                  t1x1, t1y1, t1x2, t1y2, t2x1, t2y1, t2x2, t2y2,
                  adj_price, flag_ratio):
    """仕様書7章(findFNP)。土台パターンの手前を遡って旗竿を探す。
    戻り値は (成立したか, 旗竿の起点バー, 旗竿の起点価格)。

    adj_price は土台パターンの5点をトレンドライン上に載せ直した価格
    (仕様書6.3)。参考元もこの載せ直した価格を使っている。"""
    d = zz_dir[0]                      # 参考元は符号だけでなく±2の生の値を使う
    inval = t1y1 * d
    v = t1y2 * d
    if v > inval:
        inval = v
    valid_price = t2y1 * d
    v = t2y2 * d
    if v < valid_price:
        valid_price = v

    # 5点の価格を dir>0 なら降順、dir<0 なら昇順に並べる
    srt = np.empty(5)
    for k in range(5):
        srt[k] = adj_price[k]
    for a in range(1, 5):
        key = srt[a]
        b = a - 1
        if d > 0:
            while b >= 0 and srt[b] < key:
                srt[b + 1] = srt[b]
                b -= 1
        else:
            while b >= 0 and srt[b] > key:
                srt[b + 1] = srt[b]
                b -= 1
        srt[b + 1] = key

    confirmed = False
    valid = True
    last_bar = -1
    last_price = 0.0
    price_index = 0
    iinval = inval

    for i in range(_FNP_NUMBER_OF_PIVOTS + _FNP_OFFSET, zz_n):
        pp = zz_price[i]
        pb = zz_bar[i]
        if confirmed:
            if pp * d < last_price * d:
                last_bar = pb
                last_price = pp
            if pp * d >= iinval:
                break
            if pp * d < iinval:
                iinval = pp * d
        else:
            for j in range(price_index, 5):
                pr = srt[j]
                if pp * d < pr * d:
                    price_index = j
                    iinval = pr * d
                else:
                    break
            den = abs(inval - iinval)
            if pp * d > iinval and den > 0.0:
                # 参考元は分子で iinval の絶対値を取るだけで dir による
                # 拡大(|dir|==2のとき2倍)を戻していない。そのまま踏襲する。
                # 分母が0のとき参考元は na になり比較が偽になる(=無効化しない)
                # ので、ここでも判定を飛ばす。
                inval_ratio = abs(abs(iinval) - pp) / den
                if inval_ratio > 0.5:
                    valid = False
                    break
            if pp * d < valid_price:
                confirmed = True
                last_bar = pb
                last_price = pp
                continue

    if not (valid and confirmed):
        return False, -1, 0.0

    midbar = last_bar + int((t2x1 - last_bar) * flag_ratio)
    price_at_mid = _fnp_line_price(t2x1, t2y1, t2x2, t2y2, midbar)
    flag_price_at_mid = (last_price + zz_price[0]) / 2.0
    if price_at_mid * d >= flag_price_at_mid * d:
        return True, last_bar, last_price
    return False, -1, 0.0


@njit(cache=True)
def _fnp_scan_core(open_a, high_a, low_a, close_a,
                   lengths, depths, enabled,
                   error_ratio, flat_ratio, flag_ratio,
                   check_bar_ratio, bar_ratio_limit, avoid_overlap,
                   max_patterns, hit_cap):
    """仕様書3〜7章。4本のZigZagを同時に回し、各レベルで土台パターン→
    フラッグ/ペナントの順に判定して、成立したものを全て吐く。

    参考元の「直近パターン配列」「直近フラッグ配列」による重複・重なりの
    抑制はそのまま再現する(これらは検出結果そのものを変えるため)。"""
    n = high_a.shape[0]
    nz = _FNP_NUM_ZIGZAGS
    max_depth = 0
    for z in range(nz):
        if depths[z] > max_depth:
            max_depth = depths[z]

    # レベル0のZigZag(4本分)
    zz_price = np.zeros((nz, max_depth))
    zz_bar = np.zeros((nz, max_depth), dtype=np.int64)
    zz_dir = np.zeros((nz, max_depth), dtype=np.int64)
    zz_ratio = np.ones((nz, max_depth))
    zz_bratio = np.ones((nz, max_depth))
    zz_n = np.zeros(nz, dtype=np.int64)

    # 上位レベルの作業バッファ
    lv_price = np.zeros((_FNP_MAX_LEVELS, max_depth))
    lv_bar = np.zeros((_FNP_MAX_LEVELS, max_depth), dtype=np.int64)
    lv_dir = np.zeros((_FNP_MAX_LEVELS, max_depth), dtype=np.int64)
    lv_ratio = np.ones((_FNP_MAX_LEVELS, max_depth))
    lv_bratio = np.ones((_FNP_MAX_LEVELS, max_depth))

    # 仕様書5.2の lastDBar(ZigZag×レベルごとの「最後に走査した先頭バー」)
    last_dbar = np.full((nz, _FNP_MAX_LEVELS), -1, dtype=np.int64)

    # 参考元の patterns 配列(古い順、上限 max_patterns*2)。
    pat_cap = 2 * max_patterns
    pat_bars = np.zeros((pat_cap, 5), dtype=np.int64)
    pat_n = 0
    # 参考元の fngPatterns 配列(古い順、上限 max_patterns)。
    fng_first = np.zeros(max_patterns, dtype=np.int64)
    fng_last = np.zeros(max_patterns, dtype=np.int64)
    fng_n = 0

    adj_price = np.zeros(5)
    pv_bar = np.zeros(5, dtype=np.int64)

    hit_bar = np.zeros(hit_cap, dtype=np.int64)
    hit_zz = np.zeros(hit_cap, dtype=np.int64)
    hit_level = np.zeros(hit_cap, dtype=np.int64)
    hit_base = np.zeros(hit_cap, dtype=np.int64)
    hit_type = np.zeros(hit_cap, dtype=np.int64)
    hit_dir = np.zeros(hit_cap, dtype=np.int64)
    hit_pbar = np.zeros((hit_cap, 6), dtype=np.int64)
    hit_pprice = np.zeros((hit_cap, 6))
    hit_neck = np.zeros(hit_cap)
    hit_ext = np.zeros(hit_cap)
    n_hits = 0
    hit_overflow = 0
    level_overflow = 0
    mismatch_total = 0

    for i in range(n):
        for z in range(nz):
            if not enabled[z]:
                continue
            zlen = lengths[z]
            cap = depths[z]
            if i + 1 < zlen:
                continue

            # ===== 仕様書3.1 =====
            p_high = high_a[i]
            p_high_bar = i
            p_low = low_a[i]
            p_low_bar = i
            for k in range(i - zlen + 1, i + 1):
                if high_a[k] >= p_high:
                    p_high = high_a[k]
                    p_high_bar = k
                if low_a[k] <= p_low:
                    p_low = low_a[k]
                    p_low_bar = k
            is_high_pivot = (p_high_bar == i)
            is_low_pivot = (p_low_bar == i)

            cn = zz_n[z]
            p_dir = 1
            if cn > 0:
                p_dir = 1 if zz_dir[z, 0] > 0 else -1
            distance = 0
            if cn > 0:
                distance = i - zz_bar[z, 0]
            overflow = (cn > 0) and (distance >= zlen)

            force_double = False
            if cn > 1:
                llast_price = zz_price[z, 1]
                if p_dir == 1 and is_low_pivot:
                    force_double = p_low < llast_price
                elif p_dir == -1 and is_high_pivot:
                    force_double = p_high > llast_price

            new_pivot = False

            # ===== 仕様書3.2 ① =====
            if ((p_dir == 1 and is_high_pivot) or (p_dir == -1 and is_low_pivot)) and cn >= 1:
                value = p_high if p_dir == 1 else p_low
                last_dir = zz_dir[z, 0]
                if value * last_dir >= zz_price[z, 0] * last_dir:
                    for s in range(0, cn - 1):
                        zz_price[z, s] = zz_price[z, s + 1]
                        zz_bar[z, s] = zz_bar[z, s + 1]
                        zz_dir[z, s] = zz_dir[z, s + 1]
                        zz_ratio[z, s] = zz_ratio[z, s + 1]
                        zz_bratio[z, s] = zz_bratio[z, s + 1]
                    cn -= 1
                    cn = _fnp_push_pivot(zz_price[z], zz_bar[z], zz_dir[z],
                                         zz_ratio[z], zz_bratio[z], cn, cap,
                                         value, i, p_dir)
                    new_pivot = True

            # ===== 仕様書3.2 ②(演算子優先順位の非対称性を含む) =====
            if (p_dir == 1 and is_low_pivot) or (
                p_dir == -1 and is_high_pivot and ((not new_pivot) or force_double)
            ):
                value = p_low if p_dir == 1 else p_high
                cn = _fnp_push_pivot(zz_price[z], zz_bar[z], zz_dir[z],
                                     zz_ratio[z], zz_bratio[z], cn, cap,
                                     value, i, -p_dir)
                new_pivot = True

            # ===== 仕様書3.2 ③ =====
            if overflow and not new_pivot:
                value = p_low if p_dir == 1 else p_high
                value_bar = p_low_bar if p_dir == 1 else p_high_bar
                cn = _fnp_push_pivot(zz_price[z], zz_bar[z], zz_dir[z],
                                     zz_ratio[z], zz_bratio[z], cn, cap,
                                     value, value_bar, -p_dir)
                new_pivot = True

            zz_n[z] = cn
            if not new_pivot:
                continue

            # ===== 仕様書5.2: レベルを登りながら走査 =====
            for s in range(cn):
                lv_price[0, s] = zz_price[z, s]
                lv_bar[0, s] = zz_bar[z, s]
                lv_dir[0, s] = zz_dir[z, s]
                lv_ratio[0, s] = zz_ratio[z, s]
                lv_bratio[0, s] = zz_bratio[z, s]
            cur_n = cn
            level = 0

            while cur_n >= 6 + _FNP_OFFSET:
                head_bar = lv_bar[level, 0]
                if last_dbar[z, level] >= head_bar:
                    break
                last_dbar[z, level] = head_bar

                # ----- 仕様書6章: 土台パターン -----
                # 新しい順に p6, p5, p4, p3, p2。出力は古い順に並べ替える。
                for q in range(5):
                    pv_bar[q] = lv_bar[level, 4 - q]
                first_bar = pv_bar[0]
                last_bar_p = pv_bar[4]

                ignore_pattern = False
                existing_pattern = False
                for q in range(pat_n):
                    sb = pat_bars[q, 0]
                    eb = pat_bars[q, 4]
                    if avoid_overlap and (first_bar > sb) and (first_bar < eb):
                        ignore_pattern = True
                        break
                    match = True
                    for r in range(_FNP_NUMBER_OF_PIVOTS - 1):
                        if pv_bar[r] != pat_bars[q, r]:
                            match = False
                            break
                    if match:
                        existing_pattern = True

                valid_pattern = False
                if not (ignore_pattern or existing_pattern):
                    valid_pattern = _fnp_is_same(
                        lv_price[level, 4], lv_bar[level, 4],
                        lv_price[level, 2], lv_bar[level, 2],
                        lv_ratio[level, 2], lv_bratio[level, 2],
                        lv_price[level, 0], lv_bar[level, 0],
                        lv_ratio[level, 0], lv_bratio[level, 0],
                        error_ratio, check_bar_ratio, bar_ratio_limit,
                    )

                if valid_pattern:
                    d6 = lv_dir[level, 0]
                    d5 = lv_dir[level, 1]
                    dir1 = 1.0 if d6 > 0 else -1.0
                    dir2 = 1.0 if d5 > 0 else -1.0
                    ok1, l1x1, l1y1, l1x2, l1y2 = _fnp_inspect3(
                        open_a, high_a, low_a, close_a,
                        lv_bar[level, 4], lv_price[level, 4],
                        lv_bar[level, 2], lv_price[level, 2],
                        lv_bar[level, 0], lv_price[level, 0],
                        first_bar, last_bar_p, dir1,
                    )
                    ok2 = False
                    l2x1 = 0
                    l2y1 = 0.0
                    l2x2 = 0
                    l2y2 = 0.0
                    if ok1:
                        ok2, s2 = _fnp_inspect_line(
                            open_a, high_a, low_a, close_a,
                            lv_bar[level, 3], lv_price[level, 3],
                            lv_bar[level, 1], lv_price[level, 1],
                            first_bar, last_bar_p, lv_bar[level, 3], dir2,
                        )
                        l2x1 = lv_bar[level, 3]
                        l2y1 = lv_price[level, 3]
                        l2x2 = lv_bar[level, 1]
                        l2y2 = lv_price[level, 1]

                    if ok1 and ok2:
                        # ----- 仕様書6.3: 端点を両端へ引き直す -----
                        t1y1 = _fnp_line_price(l1x1, l1y1, l1x2, l1y2, first_bar)
                        t1y2 = _fnp_line_price(l1x1, l1y1, l1x2, l1y2, last_bar_p)
                        t2y1 = _fnp_line_price(l2x1, l2y1, l2x2, l2y2, first_bar)
                        t2y2 = _fnp_line_price(l2x1, l2y1, l2x2, l2y2, last_bar_p)
                        bar_diff = last_bar_p - first_bar

                        for q in range(5):
                            if q % 2 == 0:
                                adj_price[q] = _fnp_line_price(first_bar, t1y1, last_bar_p, t1y2, pv_bar[q])
                            else:
                                adj_price[q] = _fnp_line_price(first_bar, t2y1, last_bar_p, t2y2, pv_bar[q])

                        base_type = 0
                        if bar_diff > 0:
                            base_type = _fnp_resolve_pattern_type(
                                t1y1, t1y2, t2y1, t2y2, bar_diff, flat_ratio)

                        last_dir = 1 if d6 > 0 else -1
                        allowed = False
                        if 0 <= base_type <= 13:
                            allowed = _FNP_ALLOWED_PATTERNS[base_type]
                            ald = _FNP_ALLOWED_LAST_DIRS[base_type]
                            if allowed and ald != 0 and ald != last_dir:
                                allowed = False

                        if allowed:
                            # 土台パターンとして採用 → 参考元の patterns 配列へ
                            if pat_n < pat_cap:
                                for r in range(5):
                                    pat_bars[pat_n, r] = pv_bar[r]
                                pat_n += 1
                            else:
                                for q in range(pat_cap - 1):
                                    for r in range(5):
                                        pat_bars[q, r] = pat_bars[q + 1, r]
                                for r in range(5):
                                    pat_bars[pat_cap - 1, r] = pv_bar[r]

                            # ----- 仕様書7章: 旗竿の探索 -----
                            fok, base_b, base_p = _fnp_find_fnp(
                                lv_price[level], lv_bar[level], lv_dir[level], cur_n,
                                first_bar, t1y1, last_bar_p, t1y2,
                                first_bar, t2y1, last_bar_p, t2y2,
                                adj_price, flag_ratio,
                            )
                            overlap = False
                            if fok and avoid_overlap:
                                for q in range(fng_n):
                                    st = fng_first[q]
                                    en = fng_last[q]
                                    if (first_bar >= st and first_bar <= en) or \
                                       (last_bar_p >= st and last_bar_p <= en):
                                        overlap = True
                                        break
                            if fok and not overlap:
                                if fng_n < max_patterns:
                                    fng_first[fng_n] = first_bar
                                    fng_last[fng_n] = last_bar_p
                                    fng_n += 1
                                else:
                                    for q in range(max_patterns - 1):
                                        fng_first[q] = fng_first[q + 1]
                                        fng_last[q] = fng_last[q + 1]
                                    fng_first[max_patterns - 1] = first_bar
                                    fng_last[max_patterns - 1] = last_bar_p

                                # ----- 仕様書7.3: フラッグ/ペナントの種類 -----
                                if base_type == 2 or base_type == 10:
                                    ftype = _FNP_TYPE_BULL_FLAG
                                elif base_type == 1 or base_type == 9:
                                    ftype = _FNP_TYPE_BEAR_FLAG
                                elif base_type == 11 or base_type == 12 or base_type == 13:
                                    ftype = _FNP_TYPE_BULL_PENNANT if d6 > 0 else _FNP_TYPE_BEAR_PENNANT
                                else:
                                    ftype = 0

                                if ftype != 0:
                                    if n_hits < hit_cap:
                                        # 仕様書8.1: 判定水準は参考元の
                                        # invalidationPrice / validationPrice。
                                        if last_dir > 0:
                                            neck = t1y1 if t1y1 > t1y2 else t1y2
                                            ext = t2y1 if t2y1 < t2y2 else t2y2
                                        else:
                                            neck = t1y1 if t1y1 < t1y2 else t1y2
                                            ext = t2y1 if t2y1 > t2y2 else t2y2
                                        hit_bar[n_hits] = i
                                        hit_zz[n_hits] = z
                                        hit_level[n_hits] = level
                                        hit_base[n_hits] = base_type
                                        hit_type[n_hits] = ftype
                                        hit_dir[n_hits] = last_dir
                                        hit_pbar[n_hits, 0] = base_b
                                        hit_pprice[n_hits, 0] = base_p
                                        for q in range(5):
                                            hit_pbar[n_hits, q + 1] = pv_bar[q]
                                            hit_pprice[n_hits, q + 1] = adj_price[q]
                                        hit_neck[n_hits] = neck
                                        hit_ext[n_hits] = ext
                                        n_hits += 1
                                    else:
                                        hit_overflow += 1

                if level + 1 >= _FNP_MAX_LEVELS:
                    level_overflow += 1
                    break
                nxt_n, mm = _fnp_build_next_level(
                    lv_price[level], lv_bar[level], lv_dir[level], cur_n,
                    lv_price[level + 1], lv_bar[level + 1], lv_dir[level + 1],
                    lv_ratio[level + 1], lv_bratio[level + 1], cap,
                )
                mismatch_total += mm
                if nxt_n == 0:
                    break
                cur_n = nxt_n
                level += 1

    return (
        hit_bar[:n_hits], hit_zz[:n_hits], hit_level[:n_hits], hit_base[:n_hits],
        hit_type[:n_hits], hit_dir[:n_hits], hit_pbar[:n_hits], hit_pprice[:n_hits],
        hit_neck[:n_hits], hit_ext[:n_hits],
        hit_overflow, level_overflow, mismatch_total,
    )


_FNP_SLOT_CAPACITY = 4096


def _fnp_state(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    use_zigzag1: bool = True, zigzag_length1: int = 3, depth1: int = 144,
    use_zigzag2: bool = True, zigzag_length2: int = 5, depth2: int = 89,
    use_zigzag3: bool = True, zigzag_length3: int = 8, depth3: int = 55,
    use_zigzag4: bool = True, zigzag_length4: int = 13, depth4: int = 34,
    error_threshold: float = 20.0,
    flat_threshold: float = 20.0,
    flag_ratio: float = 0.618,
    check_bar_ratio: bool = False,
    bar_ratio_limit: float = 0.382,
    avoid_overlap: bool = True,
    max_patterns: int = 20,
) -> dict[str, Any]:
    """モジュール冒頭のコメントと docs/pattern_spec_flags_pennants.md 参照。
    ブル/ベアのフラッグとペナントの4種類は共通のZigZag群から同時に検出される
    ためまとめて1回で計算する。

    戻り値:
      各パターン名 -> candidate/confirmed/invalidated のBoolean系列
      "events" -> 検出した全イベントを時系列順に1件1レコードで並べたリスト
    """
    n = len(high)
    idx_index = high.index
    open_a = np.ascontiguousarray(open_.to_numpy(dtype=float))
    high_a = np.ascontiguousarray(high.to_numpy(dtype=float))
    low_a = np.ascontiguousarray(low.to_numpy(dtype=float))
    close_a = np.ascontiguousarray(close.to_numpy(dtype=float))

    # 仕様書8.3。UIを介さない呼び出しに備えてエンジン側でも範囲を保証する。
    lengths = np.array([
        max(_FNP_ZIGZAG_LENGTH_MIN, int(zigzag_length1)),
        max(_FNP_ZIGZAG_LENGTH_MIN, int(zigzag_length2)),
        max(_FNP_ZIGZAG_LENGTH_MIN, int(zigzag_length3)),
        max(_FNP_ZIGZAG_LENGTH_MIN, int(zigzag_length4)),
    ], dtype=np.int64)
    depths = np.array([
        min(_FNP_DEPTH_MAX, max(6, int(depth1))),
        min(_FNP_DEPTH_MAX, max(6, int(depth2))),
        min(_FNP_DEPTH_MAX, max(6, int(depth3))),
        min(_FNP_DEPTH_MAX, max(6, int(depth4))),
    ], dtype=np.int64)
    enabled = np.array([bool(use_zigzag1), bool(use_zigzag2),
                        bool(use_zigzag3), bool(use_zigzag4)], dtype=np.bool_)

    error_threshold = min(_FNP_ERROR_THRESHOLD_MAX,
                          max(_FNP_ERROR_THRESHOLD_MIN, float(error_threshold)))
    flat_threshold = min(_FNP_FLAT_THRESHOLD_MAX,
                         max(_FNP_FLAT_THRESHOLD_MIN, float(flat_threshold)))
    flag_ratio = min(_FNP_FLAG_RATIO_MAX, max(_FNP_FLAG_RATIO_MIN, float(flag_ratio)))
    bar_ratio_limit = min(1.0, max(1e-6, float(bar_ratio_limit)))
    max_patterns = max(_FNP_MAX_PATTERNS_MIN, int(max_patterns))

    def _pack(flags: dict[str, dict[str, np.ndarray]], events: list[dict]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in _FNP_PATTERN_NAMES.values():
            out[name] = {
                status: pd.Series(flags[name][status], index=idx_index)
                for status in _FNP_STATUS_NAMES
            }
        out["events"] = events
        return out

    flags = {
        name: {status: np.zeros(n, dtype=bool) for status in _FNP_STATUS_NAMES}
        for name in _FNP_PATTERN_NAMES.values()
    }
    if n == 0 or not enabled.any():
        return _pack(flags, [])

    hit_cap = max(4096, n // 16)
    while True:
        (
            hit_bar, hit_zz, hit_level, hit_base, hit_type, hit_dir,
            hit_pbar, hit_pprice, hit_neck, hit_ext,
            hit_overflow, level_overflow, mismatch_total,
        ) = _fnp_scan_core(
            open_a, high_a, low_a, close_a, lengths, depths, enabled,
            error_threshold / 100.0, flat_threshold / 100.0, flag_ratio,
            bool(check_bar_ratio), bar_ratio_limit, bool(avoid_overlap),
            max_patterns, hit_cap,
        )
        if hit_overflow == 0:
            break
        hit_cap *= 4

    if mismatch_total:
        raise RuntimeError(
            f"多段ZigZagでピボットの方向が交互になりませんでした({mismatch_total}回)。"
            f"engine/chart_patterns.py::_fnp_build_next_levelの実装を確認してください。"
        )

    # pattern_idで重複を落とす(共通管理仕様7.1)。
    seen: set[str] = set()
    cand_rows: list[int] = []
    cand_pattern_id: list[str] = []
    cand_name: list[str] = []
    for k in range(len(hit_bar)):
        name = _FNP_PATTERN_NAMES[int(hit_type[k])]
        pattern_id = _make_pattern_id(name, hit_pbar[k])
        key = _make_dedup_key(name, hit_pbar[k], newest_first=False)
        if key in seen:
            continue
        seen.add(key)
        cand_rows.append(k)
        cand_pattern_id.append(pattern_id)
        cand_name.append(name)

    n_cand = len(cand_rows)
    if n_cand == 0:
        return _pack(flags, [])

    rows = np.array(cand_rows, dtype=np.int64)
    cand_bar = hit_bar[rows].astype(np.int64)
    cand_dir = hit_dir[rows].astype(np.int64)
    cand_neck = np.ascontiguousarray(hit_neck[rows])
    cand_extreme = np.ascontiguousarray(hit_ext[rows])

    order = np.argsort(cand_bar, kind="stable")

    # 決着の追い方はトリプルトップ等と完全に同じなので流用する。
    status, resolve_bar, slot_overflow = _rrcp_resolve_core(
        high_a, low_a,
        np.ascontiguousarray(cand_bar[order]),
        np.ascontiguousarray(cand_dir[order]),
        np.ascontiguousarray(cand_neck[order]),
        np.ascontiguousarray(cand_extreme[order]),
        _FNP_SLOT_CAPACITY,
    )
    if slot_overflow:
        raise RuntimeError(
            f"チャートパターンの同時監視スロットが不足しました"
            f"(上限{_FNP_SLOT_CAPACITY}件、取りこぼし{slot_overflow}件)。"
            f"engine/chart_patterns.py::_FNP_SLOT_CAPACITYを増やしてください。"
        )

    status_by_cand = np.empty(n_cand, dtype=np.int64)
    resolve_by_cand = np.empty(n_cand, dtype=np.int64)
    status_by_cand[order] = status
    resolve_by_cand[order] = resolve_bar

    events: list[dict] = []
    for j, k in enumerate(cand_rows):
        name = cand_name[j]
        base = {
            "pattern_id": cand_pattern_id[j],
            "pattern_type": name,
            "base_pattern": _FNP_BASE_PATTERN_NAMES.get(int(hit_base[k]), "unknown"),
            "zigzag_index": int(hit_zz[k]) + 1,
            "level": int(hit_level[k]),
            "point_bars": [int(b) for b in hit_pbar[k]],
            "point_prices": [float(p) for p in hit_pprice[k]],
            "neckline_price": float(cand_neck[j]),
            "extreme_price": float(cand_extreme[j]),
        }
        cb = int(cand_bar[j])
        events.append(dict(base, status="candidate", event_bar=cb))
        flags[name]["candidate"][cb] = True

        st = int(status_by_cand[j])
        if st != 0:
            rb = int(resolve_by_cand[j])
            status_name = _FNP_STATUS_NAMES[st]
            events.append(dict(base, status=status_name, event_bar=rb))
            flags[name][status_name][rb] = True

    events.sort(key=lambda e: (e["event_bar"], e["pattern_id"], e["status"]))
    return _pack(flags, events)


def _fnp_indicator(pattern_name: str):
    """4種類の公開関数を同じ形で作るためのファクトリ。"""

    def _fn(
        open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
        state: str = "confirmed",
        use_zigzag1: bool = True, zigzag_length1: int = 3, depth1: int = 144,
        use_zigzag2: bool = True, zigzag_length2: int = 5, depth2: int = 89,
        use_zigzag3: bool = True, zigzag_length3: int = 8, depth3: int = 55,
        use_zigzag4: bool = True, zigzag_length4: int = 13, depth4: int = 34,
        error_threshold: float = 20.0,
        flat_threshold: float = 20.0,
        flag_ratio: float = 0.618,
        check_bar_ratio: bool = False,
        bar_ratio_limit: float = 0.382,
        avoid_overlap: bool = True,
        max_patterns: int = 20,
        **p,
    ) -> np.ndarray:
        result = _fnp_state(
            open_, high, low, close,
            use_zigzag1, zigzag_length1, depth1,
            use_zigzag2, zigzag_length2, depth2,
            use_zigzag3, zigzag_length3, depth3,
            use_zigzag4, zigzag_length4, depth4,
            error_threshold, flat_threshold, flag_ratio,
            check_bar_ratio, bar_ratio_limit, avoid_overlap, max_patterns,
        )[pattern_name]
        key = state if state in _FNP_STATUS_NAMES else "confirmed"
        return result[key].to_numpy(dtype=float)

    _fn.__name__ = pattern_name
    _fn.__qualname__ = pattern_name
    _fn.__doc__ = (
        f"{pattern_name}(フラッグ/ペナント) - モジュール冒頭のコメントと\n"
        "    docs/pattern_spec_flags_pennants.md 参照。\n"
        "    Candidate/Confirmed/Invalidatedの3状態をstateパラメータで選べる。\n\n"
        "    条件式が要求するBoolean系列を返すため、同一バーに複数イベントが\n"
        "    乗った場合は1つに潰れる。件数や各パターンの構成点が要る用途では\n"
        "    _fnp_state(...)[\"events\"] を読むこと。"
    )
    return _fn


bullish_flag = _fnp_indicator("bullish_flag")
bearish_flag = _fnp_indicator("bearish_flag")
bullish_pennant = _fnp_indicator("bullish_pennant")
bearish_pennant = _fnp_indicator("bearish_pennant")


# ---------------------------------------------------------------------------
# チャネル / ウェッジ / トライアングル(13種) - B方式実装。
#
# 検出仕様は docs/pattern_spec_auto_chart_patterns.md (v1.0) に文章・数式・条件
# として全て書き出してあり、この実装はその仕様書だけを入力として書いている
# (参考元のPine Scriptコードを直接移植したものではない)。参考元は
# 「Auto Chart Patterns [Trendoscope®]」(Pine v6, CC BY-NC-SA 4.0,
# (c) Trendoscope Pty Ltd)と、それがimportする abstractchartpatterns/10 /
# basechartpatterns/9 / LineWrapper/2 / ohlc/3 / ZigzagLite/4。
#
# フラッグ/ペナント(_fnp_*)と土台の考え方は同じだが、**検出条件が違う**ので
# 別実装にしてある(仕様書0.4に一覧):
#   - 前提チェックが isSame ではなく checkBarRatio(バー間隔の比だけ)。
#   - トレンドラインの妥当性に「区間の2割未満しか触れていないこと」が加わる。
#   - 5点だけでなく6点のパターンも選べる。
#   - 土台13種類すべてを出力する(フラッグ/ペナントは7種類だけ使っていた)。
# 分類そのもの(resolvePatternName)は両ライブラリで完全に同一なので
# _fnp_resolve_pattern_type を共用する。
#
# 【不明】参考元は LineWrapper/2 を指定しているが公開は最新版のみ。get_price は
#   2点を通る直線の内挿という自明な式で、差分は不明だが変わりようがない。
#   ZigzagLite は指定どおり /4 が公開されていたので差分の問題は無い。
# ---------------------------------------------------------------------------

_ACP_MAX_LEVELS = 32
_ACP_NUM_ZIGZAGS = 4
_ACP_OFFSET = 0
# 参考元 abstractchartpatterns/10 の inspect が追加している条件(仕様書6.2)。
_ACP_MAX_TOUCH_RATIO = 0.2

_ACP_PATTERN_NAMES = {
    1: "ascending_channel",
    2: "descending_channel",
    3: "ranging_channel",
    4: "rising_wedge_expanding",
    5: "falling_wedge_expanding",
    6: "diverging_triangle",
    7: "ascending_triangle_expanding",
    8: "descending_triangle_expanding",
    9: "rising_wedge_contracting",
    10: "falling_wedge_contracting",
    11: "converging_triangle",
    12: "descending_triangle_contracting",
    13: "ascending_triangle_contracting",
}
_ACP_STATUS_NAMES = ("candidate", "confirmed", "invalidated")

# 仕様書1章の有効範囲。stepはUI表示上の刻みでありエンジン側では強制しない。
_ACP_ZIGZAG_LENGTH_MIN = 1
_ACP_DEPTH_MAX = 500
_ACP_ERROR_THRESHOLD_MIN = 0.0
_ACP_ERROR_THRESHOLD_MAX = 100.0
_ACP_FLAT_THRESHOLD_MIN = 0.0
_ACP_FLAT_THRESHOLD_MAX = 30.0
_ACP_MAX_PATTERNS_MIN = 1
_ACP_LAST_PIVOT_DIR_CHOICES = {"both": 0, "up": 1, "down": -1}


@njit(cache=True)
def _acp_inspect_line(open_a, high_a, low_a, close_a, x1, y1, x2, y2,
                      start_bar, end_bar, other_bar, direction):
    """仕様書6.2。フラッグ/ペナント側(_fnp_inspect_line)と同じ走査に、
    参考元 abstractchartpatterns が足している

        妥当 = 妥当 かつ (スコア / 見たバー数) < 0.2

    という条件を加えたもの。ローソクに触れすぎている線(= 実質そのへんを
    うろうろしているだけの線)を弾く。戻り値は (妥当か, スコア)。"""
    valid = True
    score = 0.0
    total = 0.0
    for b in range(start_bar, end_bar + 1):
        total += 1.0
        o = open_a[b]
        h = high_a[b]
        l = low_a[b]
        c = close_a[b]
        if direction > 0:
            bar_price = h
            bar_out = l
        else:
            bar_price = l
            bar_out = h
        line_price = _fnp_line_price(x1, y1, x2, y2, b)
        body_min = o * direction
        cd = c * direction
        if cd < body_min:
            body_min = cd
        if line_price * direction < body_min:
            valid = False
            break
        if (line_price * direction >= bar_out * direction) and (line_price * direction <= bar_price * direction):
            score += 1.0
        elif b == other_bar:
            valid = False
            break
    if total <= 0.0:
        return False, score
    return (valid and (score / total < _ACP_MAX_TOUCH_RATIO)), score


@njit(cache=True)
def _acp_inspect3(open_a, high_a, low_a, close_a,
                  b0, p0, b1, p1, b2, p2, start_bar, end_bar, direction):
    """仕様書6.2。3点から3通りの引き方を試し、スコアが最大のものを採る。
    参考元は追加の「必須接触点」設定を持つが、Auto Chart Patterns からは
    渡されない(= na)ため常にこの既定の枝が使われる。"""
    v1, s1 = _acp_inspect_line(open_a, high_a, low_a, close_a, b0, p0, b2, p2,
                               start_bar, end_bar, b1, direction)
    v2, s2 = _acp_inspect_line(open_a, high_a, low_a, close_a, b0, p0, b1, p1,
                               start_bar, end_bar, b2, direction)
    v3, s3 = _acp_inspect_line(open_a, high_a, low_a, close_a, b1, p1, b2, p2,
                               start_bar, end_bar, b0, direction)
    m23 = s2 if s2 > s3 else s3
    m13 = s1 if s1 > s3 else s3
    if v1 and s1 > m23:
        return v1, b0, p0, b2, p2
    if v2 and s2 > m13:
        return v2, b0, p0, b1, p1
    return v3, b1, p1, b2, p2


@njit(cache=True)
def _acp_bar_ratio_ok(b1, b2, b3, check_bar_ratio, bar_ratio_limit):
    """仕様書6.1(abstractchartpatterns の checkBarRatio)。3点のバー間隔の
    比が上限・下限の中に収まっているか。OFFなら常に真。"""
    if not check_bar_ratio:
        return True
    den = abs(b2 - b1)
    if den == 0:
        return False
    r = abs(b3 - b2) / den
    return (r >= bar_ratio_limit) and (r <= 1.0 / bar_ratio_limit)


@njit(cache=True)
def _acp_scan_core(open_a, high_a, low_a, close_a,
                   lengths, depths, enabled, number_of_pivots,
                   error_ratio, flat_ratio,
                   check_bar_ratio, bar_ratio_limit, avoid_overlap,
                   allowed_patterns, allowed_last_dirs,
                   max_patterns, hit_cap):
    """仕様書3〜6章。4本のZigZagを同時に回し、各レベルで13種類の
    チャートパターンを判定して、許可されたものを全て吐く。

    参考元の「直近パターン配列」による重複・重なりの抑制はそのまま再現する
    (これは検出結果そのものを変えるため)。"""
    n = high_a.shape[0]
    nz = _ACP_NUM_ZIGZAGS
    npv = number_of_pivots
    max_depth = 0
    for z in range(nz):
        if depths[z] > max_depth:
            max_depth = depths[z]

    zz_price = np.zeros((nz, max_depth))
    zz_bar = np.zeros((nz, max_depth), dtype=np.int64)
    zz_dir = np.zeros((nz, max_depth), dtype=np.int64)
    zz_ratio = np.ones((nz, max_depth))
    zz_bratio = np.ones((nz, max_depth))
    zz_n = np.zeros(nz, dtype=np.int64)

    lv_price = np.zeros((_ACP_MAX_LEVELS, max_depth))
    lv_bar = np.zeros((_ACP_MAX_LEVELS, max_depth), dtype=np.int64)
    lv_dir = np.zeros((_ACP_MAX_LEVELS, max_depth), dtype=np.int64)
    lv_ratio = np.ones((_ACP_MAX_LEVELS, max_depth))
    lv_bratio = np.ones((_ACP_MAX_LEVELS, max_depth))

    last_dbar = np.full((nz, _ACP_MAX_LEVELS), -1, dtype=np.int64)

    pat_bars = np.zeros((max_patterns, 6), dtype=np.int64)
    pat_n = 0

    pv_bar = np.zeros(6, dtype=np.int64)
    pv_price = np.zeros(6)
    adj_price = np.zeros(6)

    hit_bar = np.zeros(hit_cap, dtype=np.int64)
    hit_zz = np.zeros(hit_cap, dtype=np.int64)
    hit_level = np.zeros(hit_cap, dtype=np.int64)
    hit_type = np.zeros(hit_cap, dtype=np.int64)
    hit_dir = np.zeros(hit_cap, dtype=np.int64)
    hit_pbar = np.zeros((hit_cap, 6), dtype=np.int64)
    hit_pprice = np.zeros((hit_cap, 6))
    hit_neck = np.zeros(hit_cap)
    hit_ext = np.zeros(hit_cap)
    n_hits = 0
    hit_overflow = 0
    level_overflow = 0
    mismatch_total = 0

    for i in range(n):
        for z in range(nz):
            if not enabled[z]:
                continue
            zlen = lengths[z]
            cap = depths[z]
            if i + 1 < zlen:
                continue

            # ===== 仕様書3.1 =====
            p_high = high_a[i]
            p_high_bar = i
            p_low = low_a[i]
            p_low_bar = i
            for k in range(i - zlen + 1, i + 1):
                if high_a[k] >= p_high:
                    p_high = high_a[k]
                    p_high_bar = k
                if low_a[k] <= p_low:
                    p_low = low_a[k]
                    p_low_bar = k
            is_high_pivot = (p_high_bar == i)
            is_low_pivot = (p_low_bar == i)

            cn = zz_n[z]
            p_dir = 1
            if cn > 0:
                p_dir = 1 if zz_dir[z, 0] > 0 else -1
            distance = 0
            if cn > 0:
                distance = i - zz_bar[z, 0]
            overflow = (cn > 0) and (distance >= zlen)

            force_double = False
            if cn > 1:
                llast_price = zz_price[z, 1]
                if p_dir == 1 and is_low_pivot:
                    force_double = p_low < llast_price
                elif p_dir == -1 and is_high_pivot:
                    force_double = p_high > llast_price

            new_pivot = False

            if ((p_dir == 1 and is_high_pivot) or (p_dir == -1 and is_low_pivot)) and cn >= 1:
                value = p_high if p_dir == 1 else p_low
                last_dir0 = zz_dir[z, 0]
                if value * last_dir0 >= zz_price[z, 0] * last_dir0:
                    for s in range(0, cn - 1):
                        zz_price[z, s] = zz_price[z, s + 1]
                        zz_bar[z, s] = zz_bar[z, s + 1]
                        zz_dir[z, s] = zz_dir[z, s + 1]
                        zz_ratio[z, s] = zz_ratio[z, s + 1]
                        zz_bratio[z, s] = zz_bratio[z, s + 1]
                    cn -= 1
                    cn = _fnp_push_pivot(zz_price[z], zz_bar[z], zz_dir[z],
                                         zz_ratio[z], zz_bratio[z], cn, cap,
                                         value, i, p_dir)
                    new_pivot = True

            if (p_dir == 1 and is_low_pivot) or (
                p_dir == -1 and is_high_pivot and ((not new_pivot) or force_double)
            ):
                value = p_low if p_dir == 1 else p_high
                cn = _fnp_push_pivot(zz_price[z], zz_bar[z], zz_dir[z],
                                     zz_ratio[z], zz_bratio[z], cn, cap,
                                     value, i, -p_dir)
                new_pivot = True

            if overflow and not new_pivot:
                value = p_low if p_dir == 1 else p_high
                value_bar = p_low_bar if p_dir == 1 else p_high_bar
                cn = _fnp_push_pivot(zz_price[z], zz_bar[z], zz_dir[z],
                                     zz_ratio[z], zz_bratio[z], cn, cap,
                                     value, value_bar, -p_dir)
                new_pivot = True

            zz_n[z] = cn
            if not new_pivot:
                continue

            for s in range(cn):
                lv_price[0, s] = zz_price[z, s]
                lv_bar[0, s] = zz_bar[z, s]
                lv_dir[0, s] = zz_dir[z, s]
                lv_ratio[0, s] = zz_ratio[z, s]
                lv_bratio[0, s] = zz_bratio[z, s]
            cur_n = cn
            level = 0

            # ===== 仕様書5.2: レベルを登りながら走査 =====
            while cur_n >= 6 + _ACP_OFFSET:
                head_bar = lv_bar[level, 0]
                if last_dbar[z, level] >= head_bar:
                    break
                last_dbar[z, level] = head_bar

                # 新しい順に入っているので古い順へ並べ替える。
                for q in range(npv):
                    pv_bar[q] = lv_bar[level, npv - 1 - q]
                    pv_price[q] = lv_price[level, npv - 1 - q]
                first_bar = pv_bar[0]
                last_bar_p = pv_bar[npv - 1]

                # ----- 仕様書6.0: 既存パターンとの照合 -----
                ignore_pattern = False
                existing_pattern = False
                for q in range(pat_n):
                    sb = pat_bars[q, 0]
                    eb = pat_bars[q, npv - 1]
                    if avoid_overlap and (first_bar > sb) and (first_bar < eb):
                        ignore_pattern = True
                        break
                    match = True
                    for r in range(npv - 1):
                        if pv_bar[r] != pat_bars[q, r]:
                            match = False
                            break
                    if match:
                        existing_pattern = True

                if not (ignore_pattern or existing_pattern):
                    # ----- 仕様書6.1: バー間隔の比 -----
                    ok_ratio = _acp_bar_ratio_ok(pv_bar[0], pv_bar[2], pv_bar[4],
                                                 check_bar_ratio, bar_ratio_limit)
                    if npv == 6 and ok_ratio:
                        ok_ratio = _acp_bar_ratio_ok(pv_bar[1], pv_bar[3], pv_bar[5],
                                                     check_bar_ratio, bar_ratio_limit)

                    if ok_ratio:
                        # ----- 仕様書6.2: トレンドラインの検証 -----
                        first_direction = 1.0 if pv_price[0] > pv_price[1] else -1.0
                        ok1, l1x1, l1y1, l1x2, l1y2 = _acp_inspect3(
                            open_a, high_a, low_a, close_a,
                            pv_bar[0], pv_price[0], pv_bar[2], pv_price[2],
                            pv_bar[4], pv_price[4],
                            first_bar, last_bar_p, first_direction,
                        )
                        ok2 = False
                        l2x1 = 0
                        l2y1 = 0.0
                        l2x2 = 0
                        l2y2 = 0.0
                        if ok1:
                            if npv == 6:
                                ok2, l2x1, l2y1, l2x2, l2y2 = _acp_inspect3(
                                    open_a, high_a, low_a, close_a,
                                    pv_bar[1], pv_price[1], pv_bar[3], pv_price[3],
                                    pv_bar[5], pv_price[5],
                                    first_bar, last_bar_p, -first_direction,
                                )
                            else:
                                ok2, s2 = _acp_inspect_line(
                                    open_a, high_a, low_a, close_a,
                                    pv_bar[1], pv_price[1], pv_bar[3], pv_price[3],
                                    first_bar, last_bar_p, pv_bar[1], -first_direction,
                                )
                                l2x1 = pv_bar[1]
                                l2y1 = pv_price[1]
                                l2x2 = pv_bar[3]
                                l2y2 = pv_price[3]

                        if ok1 and ok2:
                            # ----- 仕様書6.3: 端点の引き直しと載せ直し -----
                            t1y1 = _fnp_line_price(l1x1, l1y1, l1x2, l1y2, first_bar)
                            t1y2 = _fnp_line_price(l1x1, l1y1, l1x2, l1y2, last_bar_p)
                            t2y1 = _fnp_line_price(l2x1, l2y1, l2x2, l2y2, first_bar)
                            t2y2 = _fnp_line_price(l2x1, l2y1, l2x2, l2y2, last_bar_p)
                            bar_diff = last_bar_p - first_bar

                            for q in range(npv):
                                if q % 2 == 0:
                                    adj_price[q] = _fnp_line_price(first_bar, t1y1, last_bar_p, t1y2, pv_bar[q])
                                else:
                                    adj_price[q] = _fnp_line_price(first_bar, t2y1, last_bar_p, t2y2, pv_bar[q])

                            ptype = 0
                            if bar_diff > 0:
                                ptype = _fnp_resolve_pattern_type(
                                    t1y1, t1y2, t2y1, t2y2, bar_diff, flat_ratio)

                            # ----- 仕様書6.5: 許可フィルター -----
                            dlast = adj_price[npv - 1] - adj_price[npv - 2]
                            last_dir = 0
                            if dlast > 0.0:
                                last_dir = 1
                            elif dlast < 0.0:
                                last_dir = -1

                            allowed = False
                            if 1 <= ptype <= 13:
                                allowed = allowed_patterns[ptype]
                                ald = allowed_last_dirs[ptype]
                                if allowed and ald != 0 and ald != last_dir:
                                    allowed = False

                            if allowed:
                                if pat_n < max_patterns:
                                    for r in range(npv):
                                        pat_bars[pat_n, r] = pv_bar[r]
                                    pat_n += 1
                                else:
                                    for q in range(max_patterns - 1):
                                        for r in range(6):
                                            pat_bars[q, r] = pat_bars[q + 1, r]
                                    for r in range(npv):
                                        pat_bars[max_patterns - 1, r] = pv_bar[r]

                                if n_hits < hit_cap:
                                    # 仕様書8.1(StrategyX独自拡張)。
                                    # 最後の構成点が乗っている線を「ネックライン」、
                                    # 反対側の線を「極値」にする。
                                    if npv % 2 == 1:
                                        ny1 = t1y1
                                        ny2 = t1y2
                                        ey1 = t2y1
                                        ey2 = t2y2
                                    else:
                                        ny1 = t2y1
                                        ny2 = t2y2
                                        ey1 = t1y1
                                        ey2 = t1y2
                                    if last_dir > 0:
                                        neck = ny1 if ny1 > ny2 else ny2
                                        ext = ey1 if ey1 < ey2 else ey2
                                    else:
                                        neck = ny1 if ny1 < ny2 else ny2
                                        ext = ey1 if ey1 > ey2 else ey2
                                    hit_bar[n_hits] = i
                                    hit_zz[n_hits] = z
                                    hit_level[n_hits] = level
                                    hit_type[n_hits] = ptype
                                    hit_dir[n_hits] = last_dir
                                    for q in range(npv):
                                        hit_pbar[n_hits, q] = pv_bar[q]
                                        hit_pprice[n_hits, q] = adj_price[q]
                                    for q in range(npv, 6):
                                        hit_pbar[n_hits, q] = -1
                                    hit_neck[n_hits] = neck
                                    hit_ext[n_hits] = ext
                                    n_hits += 1
                                else:
                                    hit_overflow += 1

                if level + 1 >= _ACP_MAX_LEVELS:
                    level_overflow += 1
                    break
                nxt_n, mm = _fnp_build_next_level(
                    lv_price[level], lv_bar[level], lv_dir[level], cur_n,
                    lv_price[level + 1], lv_bar[level + 1], lv_dir[level + 1],
                    lv_ratio[level + 1], lv_bratio[level + 1], cap,
                )
                mismatch_total += mm
                if nxt_n == 0:
                    break
                cur_n = nxt_n
                level += 1

    return (
        hit_bar[:n_hits], hit_zz[:n_hits], hit_level[:n_hits], hit_type[:n_hits],
        hit_dir[:n_hits], hit_pbar[:n_hits], hit_pprice[:n_hits],
        hit_neck[:n_hits], hit_ext[:n_hits],
        hit_overflow, level_overflow, mismatch_total,
    )


_ACP_SLOT_CAPACITY = 4096


def _acp_state(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    use_zigzag1: bool = True, zigzag_length1: int = 8, depth1: int = 55,
    use_zigzag2: bool = False, zigzag_length2: int = 13, depth2: int = 34,
    use_zigzag3: bool = False, zigzag_length3: int = 21, depth3: int = 21,
    use_zigzag4: bool = False, zigzag_length4: int = 34, depth4: int = 13,
    number_of_pivots: int = 5,
    error_threshold: float = 20.0,
    flat_threshold: float = 20.0,
    last_pivot_direction: str = "both",
    check_bar_ratio: bool = True,
    bar_ratio_limit: float = 0.382,
    avoid_overlap: bool = True,
    max_patterns: int = 20,
) -> dict[str, Any]:
    """モジュール冒頭のコメントと docs/pattern_spec_auto_chart_patterns.md 参照。
    チャネル3種・ウェッジ4種・トライアングル6種の計13種類は共通のZigZag群から
    同時に検出されるためまとめて1回で計算する。

    戻り値:
      各パターン名 -> candidate/confirmed/invalidated のBoolean系列
      "events" -> 検出した全イベントを時系列順に1件1レコードで並べたリスト
    """
    n = len(high)
    idx_index = high.index
    open_a = np.ascontiguousarray(open_.to_numpy(dtype=float))
    high_a = np.ascontiguousarray(high.to_numpy(dtype=float))
    low_a = np.ascontiguousarray(low.to_numpy(dtype=float))
    close_a = np.ascontiguousarray(close.to_numpy(dtype=float))

    # 仕様書8.2。UIを介さない呼び出しに備えてエンジン側でも範囲を保証する。
    lengths = np.array([
        max(_ACP_ZIGZAG_LENGTH_MIN, int(zigzag_length1)),
        max(_ACP_ZIGZAG_LENGTH_MIN, int(zigzag_length2)),
        max(_ACP_ZIGZAG_LENGTH_MIN, int(zigzag_length3)),
        max(_ACP_ZIGZAG_LENGTH_MIN, int(zigzag_length4)),
    ], dtype=np.int64)
    depths = np.array([
        min(_ACP_DEPTH_MAX, max(6, int(depth1))),
        min(_ACP_DEPTH_MAX, max(6, int(depth2))),
        min(_ACP_DEPTH_MAX, max(6, int(depth3))),
        min(_ACP_DEPTH_MAX, max(6, int(depth4))),
    ], dtype=np.int64)
    enabled = np.array([bool(use_zigzag1), bool(use_zigzag2),
                        bool(use_zigzag3), bool(use_zigzag4)], dtype=np.bool_)

    number_of_pivots = 6 if int(number_of_pivots) >= 6 else 5
    error_threshold = min(_ACP_ERROR_THRESHOLD_MAX,
                          max(_ACP_ERROR_THRESHOLD_MIN, float(error_threshold)))
    flat_threshold = min(_ACP_FLAT_THRESHOLD_MAX,
                         max(_ACP_FLAT_THRESHOLD_MIN, float(flat_threshold)))
    bar_ratio_limit = min(1.0, max(1e-6, float(bar_ratio_limit)))
    max_patterns = max(_ACP_MAX_PATTERNS_MIN, int(max_patterns))
    dir_code = _ACP_LAST_PIVOT_DIR_CHOICES.get(
        str(last_pivot_direction).strip().lower(), 0)

    # 13種類は全て有効にして1回で計算し、指標ごとに該当分だけ取り出す。
    allowed_patterns = np.zeros(14, dtype=np.bool_)
    allowed_patterns[1:] = True
    allowed_last_dirs = np.full(14, dir_code, dtype=np.int64)
    allowed_last_dirs[0] = 0

    def _pack(flags: dict[str, dict[str, np.ndarray]], events: list[dict]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in _ACP_PATTERN_NAMES.values():
            out[name] = {
                status: pd.Series(flags[name][status], index=idx_index)
                for status in _ACP_STATUS_NAMES
            }
        out["events"] = events
        return out

    flags = {
        name: {status: np.zeros(n, dtype=bool) for status in _ACP_STATUS_NAMES}
        for name in _ACP_PATTERN_NAMES.values()
    }
    if n == 0 or not enabled.any():
        return _pack(flags, [])

    hit_cap = max(4096, n // 16)
    while True:
        (
            hit_bar, hit_zz, hit_level, hit_type, hit_dir,
            hit_pbar, hit_pprice, hit_neck, hit_ext,
            hit_overflow, level_overflow, mismatch_total,
        ) = _acp_scan_core(
            open_a, high_a, low_a, close_a, lengths, depths, enabled,
            number_of_pivots, error_threshold / 100.0, flat_threshold / 100.0,
            bool(check_bar_ratio), bar_ratio_limit, bool(avoid_overlap),
            allowed_patterns, allowed_last_dirs, max_patterns, hit_cap,
        )
        if hit_overflow == 0:
            break
        hit_cap *= 4

    if mismatch_total:
        raise RuntimeError(
            f"多段ZigZagでピボットの方向が交互になりませんでした({mismatch_total}回)。"
            f"engine/chart_patterns.py::_fnp_build_next_levelの実装を確認してください。"
        )

    seen: set[str] = set()
    cand_rows: list[int] = []
    cand_pattern_id: list[str] = []
    cand_name: list[str] = []
    for k in range(len(hit_bar)):
        name = _ACP_PATTERN_NAMES[int(hit_type[k])]
        bars = [int(b) for b in hit_pbar[k] if b >= 0]
        pattern_id = _make_pattern_id(name, bars)
        key = _make_dedup_key(name, bars, newest_first=False)
        if key in seen:
            continue
        seen.add(key)
        cand_rows.append(k)
        cand_pattern_id.append(pattern_id)
        cand_name.append(name)

    n_cand = len(cand_rows)
    if n_cand == 0:
        return _pack(flags, [])

    rows = np.array(cand_rows, dtype=np.int64)
    cand_bar = hit_bar[rows].astype(np.int64)
    cand_dir = hit_dir[rows].astype(np.int64)
    cand_neck = np.ascontiguousarray(hit_neck[rows])
    cand_extreme = np.ascontiguousarray(hit_ext[rows])

    order = np.argsort(cand_bar, kind="stable")
    status, resolve_bar, slot_overflow = _rrcp_resolve_core(
        high_a, low_a,
        np.ascontiguousarray(cand_bar[order]),
        np.ascontiguousarray(cand_dir[order]),
        np.ascontiguousarray(cand_neck[order]),
        np.ascontiguousarray(cand_extreme[order]),
        _ACP_SLOT_CAPACITY,
    )
    if slot_overflow:
        raise RuntimeError(
            f"チャートパターンの同時監視スロットが不足しました"
            f"(上限{_ACP_SLOT_CAPACITY}件、取りこぼし{slot_overflow}件)。"
            f"engine/chart_patterns.py::_ACP_SLOT_CAPACITYを増やしてください。"
        )

    status_by_cand = np.empty(n_cand, dtype=np.int64)
    resolve_by_cand = np.empty(n_cand, dtype=np.int64)
    status_by_cand[order] = status
    resolve_by_cand[order] = resolve_bar

    events: list[dict] = []
    for j, k in enumerate(cand_rows):
        name = cand_name[j]
        keep = [q for q in range(6) if hit_pbar[k, q] >= 0]
        base = {
            "pattern_id": cand_pattern_id[j],
            "pattern_type": name,
            "zigzag_index": int(hit_zz[k]) + 1,
            "level": int(hit_level[k]),
            "last_pivot_direction": int(cand_dir[j]),
            "point_bars": [int(hit_pbar[k, q]) for q in keep],
            "point_prices": [float(hit_pprice[k, q]) for q in keep],
            "neckline_price": float(cand_neck[j]),
            "extreme_price": float(cand_extreme[j]),
        }
        cb = int(cand_bar[j])
        events.append(dict(base, status="candidate", event_bar=cb))
        flags[name]["candidate"][cb] = True

        st = int(status_by_cand[j])
        if st != 0:
            rb = int(resolve_by_cand[j])
            status_name = _ACP_STATUS_NAMES[st]
            events.append(dict(base, status=status_name, event_bar=rb))
            flags[name][status_name][rb] = True

    events.sort(key=lambda e: (e["event_bar"], e["pattern_id"], e["status"]))
    return _pack(flags, events)


def _acp_indicator(pattern_name: str):
    """13種類の公開関数を同じ形で作るためのファクトリ。どれを呼んでも内部では
    共通のZigZag群を1回計算し、該当パターンのBoolean系列だけを取り出す。"""

    def _fn(
        open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
        state: str = "confirmed",
        use_zigzag1: bool = True, zigzag_length1: int = 8, depth1: int = 55,
        use_zigzag2: bool = False, zigzag_length2: int = 13, depth2: int = 34,
        use_zigzag3: bool = False, zigzag_length3: int = 21, depth3: int = 21,
        use_zigzag4: bool = False, zigzag_length4: int = 34, depth4: int = 13,
        number_of_pivots: int = 5,
        error_threshold: float = 20.0,
        flat_threshold: float = 20.0,
        last_pivot_direction: str = "both",
        check_bar_ratio: bool = True,
        bar_ratio_limit: float = 0.382,
        avoid_overlap: bool = True,
        max_patterns: int = 20,
        **p,
    ) -> np.ndarray:
        result = _acp_state(
            open_, high, low, close,
            use_zigzag1, zigzag_length1, depth1,
            use_zigzag2, zigzag_length2, depth2,
            use_zigzag3, zigzag_length3, depth3,
            use_zigzag4, zigzag_length4, depth4,
            number_of_pivots, error_threshold, flat_threshold,
            last_pivot_direction, check_bar_ratio, bar_ratio_limit,
            avoid_overlap, max_patterns,
        )[pattern_name]
        key = state if state in _ACP_STATUS_NAMES else "confirmed"
        return result[key].to_numpy(dtype=float)

    _fn.__name__ = pattern_name
    _fn.__qualname__ = pattern_name
    _fn.__doc__ = (
        f"{pattern_name}(チャネル/ウェッジ/トライアングル) - モジュール冒頭の\n"
        "    コメントと docs/pattern_spec_auto_chart_patterns.md 参照。\n"
        "    Candidate/Confirmed/Invalidatedの3状態をstateパラメータで選べる。\n\n"
        "    シグナルの向きは「最後の構成点の向き」で決まる。初期値の\n"
        "    last_pivot_direction='both' では上下が混ざるので、方向を固定したい\n"
        "    場合は 'up' / 'down' を指定すること。\n\n"
        "    条件式が要求するBoolean系列を返すため、同一バーに複数イベントが\n"
        "    乗った場合は1つに潰れる。件数や各パターンの構成点が要る用途では\n"
        "    _acp_state(...)[\"events\"] を読むこと。"
    )
    return _fn


ascending_channel = _acp_indicator("ascending_channel")
descending_channel = _acp_indicator("descending_channel")
ranging_channel = _acp_indicator("ranging_channel")
rising_wedge_expanding = _acp_indicator("rising_wedge_expanding")
falling_wedge_expanding = _acp_indicator("falling_wedge_expanding")
diverging_triangle = _acp_indicator("diverging_triangle")
ascending_triangle_expanding = _acp_indicator("ascending_triangle_expanding")
descending_triangle_expanding = _acp_indicator("descending_triangle_expanding")
rising_wedge_contracting = _acp_indicator("rising_wedge_contracting")
falling_wedge_contracting = _acp_indicator("falling_wedge_contracting")
converging_triangle = _acp_indicator("converging_triangle")
descending_triangle_contracting = _acp_indicator("descending_triangle_contracting")
ascending_triangle_contracting = _acp_indicator("ascending_triangle_contracting")
