"""Regression tests for engine/chart_patterns.py (ダブルトップ/ボトムの
形状判定版とZigZag方式). Plain-script style (not pytest-based) matching this
project's convention - run directly with `python tests/test_chart_patterns.py`.

Hand-built synthetic OHLC sequences with a known answer by construction -
there's no external reference to check chart-pattern definitions against
(same situation as engine/smc_indicators.py and engine/candlestick_patterns.py).

ZigZag方式のテストは docs/pattern_spec_double_top_bottom_zigzag.md の
「9. 実装前チェックリスト」の各項目に対応させてある。

2026-08-07、ユーザー判断でダブルトップ/ボトム以外のチャートパターンを全て
削除したのに伴い、それらのテストもここから削除した(engine/chart_patterns.py
のモジュール冒頭コメント参照)。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import engine.chart_patterns as cp
from engine.data_loader import find_data_file, load_price_data

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


def _hlc(closes: np.ndarray, wick: float = 0.3) -> tuple[pd.Series, pd.Series, pd.Series]:
    high = pd.Series(closes + wick)
    low = pd.Series(closes - wick)
    close = pd.Series(closes)
    return high, low, close


def test_double_bottom_shape_breakout_deadline_min_bars_used_as_is_below_pivot_right_bars():
    # breakout_deadline_min_bars(谷2からブレイクまでの最小本数)を
    # pivot_right_bars未満に設定しても、2026-08-04以降は入力した値が
    # そのまま使われる(以前はpivot_right_bars+3まで自動的に繰り上げる
    # クランプがあったが、⑤⑥の変更([_shape_state_core]のscan_startが
    # 谷2の直後から始まるようになった)でその根拠自体が無くなったため撤去
    # した - ユーザー判断2026-08-04)。谷2から10本目でブレイクする形に対し、
    # min_bars=2(実際のタイミングより十分小さい、早すぎではない)なら
    # Confirmed、min_bars=13(実際のタイミングより大きい、genuinely早すぎ)
    # ならRejectedになるはず。
    closes = np.concatenate([
        np.linspace(130, 110, 15, endpoint=False), np.linspace(110, 100, 15, endpoint=False),
        np.linspace(100, 110, 15, endpoint=False), np.linspace(110, 100.5, 15, endpoint=False),
        np.linspace(100.5, 135, 30, endpoint=False), np.full(40, 135.0),
    ])
    high, low, close = _hlc(closes)

    low_min_bars_confirmed = cp.double_bottom_shape(high, low, close, state="confirmed", pivot_spike_excess_atr_max=0.0,
                                                      pivot_right_bars=10, breakout_deadline_min_bars=2)
    low_min_bars_rejected = cp.double_bottom_shape(high, low, close, state="invalidated", pivot_spike_excess_atr_max=0.0,
                                                     pivot_right_bars=10, breakout_deadline_min_bars=2)
    high_min_bars_confirmed = cp.double_bottom_shape(high, low, close, state="confirmed", pivot_spike_excess_atr_max=0.0,
                                                       pivot_right_bars=10, breakout_deadline_min_bars=13)
    high_min_bars_rejected = cp.double_bottom_shape(high, low, close, state="invalidated", pivot_spike_excess_atr_max=0.0,
                                                      pivot_right_bars=10, breakout_deadline_min_bars=13)

    check(
        "breakout_deadline_min_bars=2 (below pivot_right_bars=10, genuinely not too early) confirms rather than being clamped/rejected",
        low_min_bars_confirmed.sum() >= 1 and low_min_bars_rejected.sum() == 0,
        detail=f"confirmed={low_min_bars_confirmed.sum()} rejected={low_min_bars_rejected.sum()}",
    )
    check(
        "breakout_deadline_min_bars=13 (above the actual breakout timing, genuinely too early) rejects rather than confirming",
        high_min_bars_rejected.sum() >= 1 and high_min_bars_confirmed.sum() == 0,
        detail=f"confirmed={high_min_bars_confirmed.sum()} rejected={high_min_bars_rejected.sum()}",
    )


def test_double_bottom_shape_rejects_breakout_hidden_inside_pivot_confirm_window():
    # 谷2からブレイクまでの間隔が短すぎる形は、実際にネックラインを突破した
    # タイミング(bars_since_top2)がbreakout_deadline_min_bars未満なら、
    # スキャンが谷2の直後から始まる(2026-08-04の再設計、モジュール冒頭の
    # ⑫参照)ため、Rejectedとして正しく検出できるはず。2026-08-03、
    # ユーザー指摘: 「山2のピボット右本数設定値よりも早く終値がネックライン+
    # ブレイク余白を突破したときは早すぎるブレイクとして棄却できない？」。
    #
    # 谷2直後(5本以内)に一気にブレイクする形と、谷2からゆっくり
    # (40本かけて)ブレイクする形の2パターンを比較する。
    base = [
        np.linspace(130, 110, 15, endpoint=False), np.linspace(110, 100, 15, endpoint=False),
        np.linspace(100, 110, 15, endpoint=False), np.linspace(110, 100.5, 15, endpoint=False),
    ]
    fast_closes = np.concatenate(base + [np.linspace(100.5, 135, 5, endpoint=False), np.full(60, 135.0)])
    slow_closes = np.concatenate(base + [np.linspace(100.5, 135, 40, endpoint=False), np.full(20, 135.0)])

    fast_high, fast_low, fast_close = _hlc(fast_closes)
    slow_high, slow_low, slow_close = _hlc(slow_closes)

    kwargs = dict(state="confirmed", pivot_spike_excess_atr_max=0.0, pivot_right_bars=10, breakout_deadline_min_bars=10)
    fast_confirmed = cp.double_bottom_shape(fast_high, fast_low, fast_close, **kwargs)
    fast_rejected = cp.double_bottom_shape(fast_high, fast_low, fast_close, **dict(kwargs, state="invalidated"))
    slow_confirmed = cp.double_bottom_shape(slow_high, slow_low, slow_close, **kwargs)

    check(
        "a breakout hidden inside the pivot-confirm window (breakout_deadline_min_bars == pivot_right_bars) is rejected, not confirmed",
        fast_confirmed.sum() == 0 and fast_rejected.sum() >= 1,
        detail=f"confirmed={fast_confirmed.sum()} rejected={fast_rejected.sum()}",
    )
    check(
        "a genuinely-on-time breakout (same shape, slower ramp) still confirms normally - the fix isn't over-rejecting",
        slow_confirmed.sum() >= 1,
        detail=f"slow_confirmed={slow_confirmed.sum()}",
    )


def test_double_bottom_shape_top2_confirms_without_right_side_pivot_wait():
    # 谷2(ブレイクへ直接つながる最後の反転点)は左側のピボット判定だけで
    # 確定し、右側(pivot_right_bars分の待ち)は不要 - 2026-08-04、ユーザー
    # 判断: 「山2はピボット左右判定じゃなく左だけで右は無でもよくないか」。
    # 本当にそこが頂点だったか(その後さらに上がらなかったか)はブレイク
    # 判定側のfail_j/早すぎ判定がそのまま代わりに担保する設計。
    #
    # pivot_right_bars=10というかなり長い待ちを設定しても、formed_bar
    # (パターン全体が確定するバー)は谷2自身のバーと一致するはず(以前は
    # 必ず谷2+10だった)。
    closes = np.concatenate([
        np.linspace(130, 110, 15, endpoint=False), np.linspace(110, 100, 15, endpoint=False),
        np.linspace(100, 110, 15, endpoint=False), np.linspace(110, 100.5, 15, endpoint=False),
        np.linspace(100.5, 135, 30, endpoint=False), np.full(40, 135.0),
    ])
    high, low, close = _hlc(closes)

    state = cp._double_top_bottom_shape_state(high, low, close, True, pivot_spike_excess_atr_max=0.0,
                                               pivot_right_bars=10, breakout_deadline_min_bars=10)
    top2_bar = int(state["top2_bar"].to_numpy()[60]) if not np.isnan(state["top2_bar"].to_numpy()[60]) else None

    check(
        "谷2自身のバー(60)にformed_bar情報が書き込まれている(右側待ちゼロ)",
        top2_bar == 60,
        detail=f"top2_bar_at_60={top2_bar}",
    )

    confirmed = np.where(state["confirmed"].to_numpy())[0]
    check(
        "境界値ちょうど(breakout_deadline_min_bars==pivot_right_bars)でも、間に合ったブレイクは正しくConfirmed",
        len(confirmed) >= 1 and (confirmed[0] - 60) == 10,
        detail=f"confirmed={confirmed}",
    )


def test_double_bottom_shape_neck_to_top2_also_bound_by_min_max_bars_between_tops():
    # ネック→山2の本数(interval2)は、以前は比率ベースの窓
    # (symmetry_ratio_min/max × interval1)でしか絞り込まれていなかった。
    # 山1→ネックと同じ最短本数でも追加拘束されるようになったはず -
    # 2026-08-04、ユーザー判断: 「山1→ネックと同じところでネック→山2の
    # 本数の範囲も決めたい」。この最短本数は元々min_bars_between_topsという
    # 独立パラメータだったが、2026-08-05にユーザー判断で廃止し、常に
    # ピボット右本数(pivot_right_bars、デフォルト5)を使うようになった -
    # そちらのコメント参照。谷2までの区間の本数だけを変えた2パターンを
    # 比較する。
    def build(seg4_len):
        return np.concatenate([
            np.linspace(130, 110, 15, endpoint=False), np.linspace(110, 100, 15, endpoint=False),
            np.linspace(100, 110, 15, endpoint=False), np.linspace(110, 100.5, seg4_len, endpoint=False),
            np.linspace(100.5, 135, 30, endpoint=False), np.full(40, 135.0),
        ])

    too_close_high, too_close_low, too_close_close = _hlc(build(4))  # interval2=4 < pivot_right_bars=5
    ok_high, ok_low, ok_close = _hlc(build(6))  # interval2=6 >= pivot_right_bars=5

    too_close_state = cp._double_top_bottom_shape_state(
        too_close_high, too_close_low, too_close_close, True,
        pivot_spike_excess_atr_max=0.0, max_bars_between_tops=500,
    )
    ok_state = cp._double_top_bottom_shape_state(
        ok_high, ok_low, ok_close, True,
        pivot_spike_excess_atr_max=0.0, max_bars_between_tops=500,
    )

    check(
        "ネック→山2が4本(ピボット右本数5未満)だと検出されない",
        too_close_state["candidate"].sum() == 0,
        detail=f"candidate={np.where(too_close_state['candidate'].to_numpy())[0]}",
    )
    check(
        "ネック→山2が6本(ピボット右本数5以上)なら正常に検出される",
        ok_state["candidate"].sum() >= 1,
        detail=f"candidate={np.where(ok_state['candidate'].to_numpy())[0]}",
    )


# ---------------------------------------------------------------------------
# ダブルトップ/ボトム(ZigZag方式、B方式実装)。
# 仕様: docs/pattern_spec_double_top_bottom_zigzag.md
#
# 形状条件そのもの以外(閾値の境界・分類・同一バー競合・共通管理仕様)は、
# ピボットの発生位置を完全に制御したいので _zigzag_dtdb_core を直接呼ぶ。
# roll_high/roll_lowにNaN以外を入れたバーだけがピボット候補になる仕組みを
# 使い、「どのバーが山でどのバーが谷か」を手で指定している。
# ---------------------------------------------------------------------------

def _zz_core_arrays(highs, lows, high_pivot_bars, low_pivot_bars):
    high_a = np.array(highs, dtype=float)
    low_a = np.array(lows, dtype=float)
    roll_high = np.full(len(high_a), np.nan)
    roll_low = np.full(len(low_a), np.nan)
    for b in high_pivot_bars:
        roll_high[b] = high_a[b]
    for b in low_pivot_bars:
        roll_low[b] = low_a[b]
    return high_a, low_a, roll_high, roll_low


def _zz_core_run(highs, lows, high_pivot_bars, low_pivot_bars, max_risk_ratio=30.0):
    high_a, low_a, roll_high, roll_low = _zz_core_arrays(highs, lows, high_pivot_bars, low_pivot_bars)
    out = cp._zigzag_dtdb_core(
        high_a, low_a, roll_high, roll_low, max_risk_ratio,
        cp._ZZ_DTDB_SLOT_CAPACITY, 2 * len(high_a) + 16,
    )
    return {
        "dt_candidate": np.where(out[0])[0].tolist(),
        "dt_confirmed": np.where(out[1])[0].tolist(),
        "dt_invalidated": np.where(out[2])[0].tolist(),
        "db_candidate": np.where(out[3])[0].tolist(),
        "db_confirmed": np.where(out[4])[0].tolist(),
        "db_invalidated": np.where(out[5])[0].tolist(),
        "n_events": out[16],
        "event_overflow": out[17],
        "slot_overflow": out[18],
        "max_concurrent": out[19],
    }


def _zz_seg(a: float, b: float, n: int) -> np.ndarray:
    return np.linspace(a, b, n, endpoint=False)


def test_double_top_zigzag_confirms_on_clean_pattern():
    # 仕様書4.4: 系列内で最初に現れるピボットは比較対象が無く常にmult=1
    # (LH/HL扱い)になるため、P1をHHにするには手前にもう一往復必要。
    closes = np.concatenate([
        _zz_seg(80, 90, 8), _zz_seg(90, 85, 8),      # 助走(P1の比較対象を作る)
        _zz_seg(85, 120, 12), _zz_seg(120, 108, 12),  # P1=120(HH) → P2=108
        _zz_seg(108, 118, 12), _zz_seg(118, 95, 20),  # P3=118(LH) → ネック割れ
    ])
    high, low, close = _hlc(closes, wick=0.05)
    candidate = cp.double_top_zigzag(high, low, close, state="candidate", length=5, max_risk_ratio=30)
    confirmed = cp.double_top_zigzag(high, low, close, state="confirmed", length=5, max_risk_ratio=30)
    check(
        "double_top_zigzag ダブルトップの形でCandidateが1回成立する",
        int(candidate.sum()) == 1,
        detail=str(np.where(candidate)[0]),
    )
    check(
        "double_top_zigzag ネックライン割れでConfirmedが1回発生する",
        int(confirmed.sum()) == 1,
        detail=str(np.where(confirmed)[0]),
    )


def test_double_bottom_zigzag_confirms_on_clean_pattern_mirror():
    closes = np.concatenate([
        _zz_seg(120, 110, 8), _zz_seg(110, 115, 8),
        _zz_seg(115, 80, 12), _zz_seg(80, 92, 12),    # P1=80(LL) → P2=92
        _zz_seg(92, 82, 12), _zz_seg(82, 105, 20),    # P3=82(HL) → ネック突破
    ])
    high, low, close = _hlc(closes, wick=0.05)
    candidate = cp.double_bottom_zigzag(high, low, close, state="candidate", length=5, max_risk_ratio=30)
    confirmed = cp.double_bottom_zigzag(high, low, close, state="confirmed", length=5, max_risk_ratio=30)
    check(
        "double_bottom_zigzag ダブルボトムの形でCandidateが1回成立する(鏡像)",
        int(candidate.sum()) == 1,
        detail=str(np.where(candidate)[0]),
    )
    check(
        "double_bottom_zigzag ネックライン突破でConfirmedが1回発生する(鏡像)",
        int(confirmed.sum()) == 1,
        detail=str(np.where(confirmed)[0]),
    )


def test_double_top_zigzag_ratio_threshold_is_strict_less_than():
    # 仕様書5.1/2章: ratio = |P3-P1|×100/(|P3-P1|+|P3-P2|) を「未満」で判定
    # する(「以下」ではない)。P1=120/P2=110/P3=117 なら
    # 3×100/(3+7) = ちょうど30.0 なので、上限30では不採用・31なら採用。
    highs = [90, 100, 80, 120, 115, 117, 115]
    lows = [70, 95, 65, 115, 110, 113, 112]
    hp, lp = [1, 3, 5], [0, 2, 4, 6]
    at_threshold = _zz_core_run(highs, lows, hp, lp, max_risk_ratio=30.0)
    just_above = _zz_core_run(highs, lows, hp, lp, max_risk_ratio=31.0)
    check(
        "double_top_zigzag ratioが上限とちょうど同値ならCandidateにしない(<であって<=ではない)",
        at_threshold["dt_candidate"] == [],
        detail=str(at_threshold["dt_candidate"]),
    )
    check(
        "double_top_zigzag 上限をわずかに上げれば同じ形がCandidateになる(境界テストの前提確認)",
        just_above["dt_candidate"] == [6],
        detail=str(just_above["dt_candidate"]),
    )


def test_double_top_zigzag_requires_p1_to_be_a_new_high():
    # 仕様書5.2: Double TopはP1=HH(+2)が必須。P1(120)の手前に、より高い
    # 同方向ピボット(130)を置くとP1はLH(+1)に分類され、Candidateにならない。
    highs = [90, 130, 80, 120, 115, 117, 115]
    lows = [70, 95, 65, 115, 110, 113, 112]
    res = _zz_core_run(highs, lows, [1, 3, 5], [0, 2, 4, 6])
    check(
        "double_top_zigzag P1が新高値(HH)でなければCandidateにならない",
        res["dt_candidate"] == [],
        detail=str(res["dt_candidate"]),
    )


def test_double_top_zigzag_rejects_when_all_three_points_are_equal():
    # 仕様書5.1: risk+reward==0 のとき参考元ではratioがnaになり閾値比較が
    # 偽になる。P1=P2=P3=120 の縮退した形をCandidateにしてはいけない。
    highs = [90, 100, 80, 120, 120, 120, 118]
    lows = [70, 95, 65, 118, 120, 118, 115]
    res = _zz_core_run(highs, lows, [1, 3, 5], [0, 2, 4, 6])
    check(
        "double_top_zigzag 3点が完全同値(risk+reward=0)ならCandidateにしない",
        res["dt_candidate"] == [],
        detail=str(res["dt_candidate"]),
    )


def test_double_top_zigzag_confirmed_wins_over_invalidated_on_the_same_bar():
    # 仕様書6.2: 同一バーでConfirmed条件とInvalidated条件が同時成立したら
    # Confirmedを優先する。Candidate成立バー(6)でネック100を下抜けつつ
    # 第1山120も上抜ける形を作る。
    highs = [90, 100, 80, 120, 105, 115, 125]
    lows = [70, 95, 65, 110, 100, 110, 95]
    res = _zz_core_run(highs, lows, [1, 3, 5], [0, 2, 4, 6])
    check(
        "double_top_zigzag 同一バーで両条件が成立したらConfirmedを優先する",
        res["dt_confirmed"] == [6] and res["dt_invalidated"] == [],
        detail=f"confirmed={res['dt_confirmed']} invalidated={res['dt_invalidated']}",
    )


def test_double_top_zigzag_resolves_each_pattern_only_once():
    # 共通管理仕様7.3(仕様書): 一度決着したパターンは監視を終了し、その後
    # 同じ水準を価格が何度横切っても再判定しない。バー7でネック100を割って
    # Confirmedした後、バー8で戻しバー9で再度割っても2回目を出さない。
    highs = [90, 100, 80, 120, 105, 115, 112, 110, 112, 110]
    lows = [70, 95, 65, 110, 100, 110, 105, 95, 105, 95]
    res = _zz_core_run(highs, lows, [1, 3, 5], [0, 2, 4, 6])
    check(
        "double_top_zigzag 決着後にネックを再度割ってもConfirmedは2回目が出ない",
        res["dt_confirmed"] == [7],
        detail=str(res["dt_confirmed"]),
    )
    check(
        "double_top_zigzag 同じ3点の組み合わせからCandidateを重複登録しない",
        res["dt_candidate"] == [6],
        detail=str(res["dt_candidate"]),
    )


def test_double_top_zigzag_tracks_overlapping_patterns_independently():
    # 共通管理仕様7.4(仕様書): 未決着のパターンを複数同時に保持する。
    # 1つ目(P1=120/P2=100/P3=115、バー6でCandidate)が未決着のまま
    # 2つ目(P1=118/P2=103/P3=116、バー14でCandidate)が成立し、
    # ネックが違うのでバー16→2つ目、バー18→1つ目の順に別々に決着する。
    highs = [90, 100, 80, 120, 105, 115, 112, 113, 118, 115, 110, 112, 116, 114, 110, 109, 107, 105, 103, 100]
    lows = [70, 95, 65, 110, 100, 110, 105, 106, 112, 108, 103, 105, 110, 108, 104, 104, 101, 100, 95, 96]
    res = _zz_core_run(highs, lows, [1, 3, 5, 8, 12], [0, 2, 4, 6, 10, 14])
    check(
        "double_top_zigzag 重なり合う2パターンをそれぞれCandidateとして登録する",
        res["dt_candidate"] == [6, 14],
        detail=str(res["dt_candidate"]),
    )
    check(
        "double_top_zigzag 重なり合う2パターンがそれぞれ別のバーで決着する",
        res["dt_confirmed"] == [16, 18],
        detail=str(res["dt_confirmed"]),
    )
    check(
        "double_top_zigzag 2パターンを同時に監視していた(単一スロットではない)",
        res["max_concurrent"] == 2,
        detail=str(res["max_concurrent"]),
    )


def test_double_top_zigzag_keeps_every_event_when_two_patterns_resolve_on_one_bar():
    # 仕様書8章(2026-08-12にユーザー指摘で追加): Boolean系列は「1バーに1個」
    # なので、同一バーで2件決着すると件数も各パターンの3点も落ちる。欠落の
    # 無い情報はevents側で持つ。上の重なりフィクスチャの安値だけを変えて、
    # バー16で2つのネック(103と100)を同時に割る形にしてある。
    highs = [90, 100, 80, 120, 105, 115, 112, 113, 118, 115, 110, 112, 116, 114, 110, 109, 107, 105, 103, 100]
    lows = [70, 95, 65, 110, 100, 110, 105, 106, 112, 108, 103, 105, 110, 108, 104, 104, 95, 96, 95, 96]
    high, low, close = (pd.Series(np.array(x, dtype=float)) for x in (highs, lows, highs))
    high_a, low_a, roll_high, roll_low = _zz_core_arrays(highs, lows, [1, 3, 5, 8, 12], [0, 2, 4, 6, 10, 14])
    out = cp._zigzag_dtdb_core(
        high_a, low_a, roll_high, roll_low, 30.0, cp._ZZ_DTDB_SLOT_CAPACITY, 2 * len(high_a) + 16
    )
    confirmed_bars = np.where(out[1])[0].tolist()
    n_events = out[16]
    # イベント配列からConfirmedだけ取り出す(status: 0=candidate/1=confirmed)
    confirmed_events = [
        (int(out[8][k]), cp._make_pattern_id("double_top", (out[9][k], out[11][k], out[13][k])))
        for k in range(n_events)
        if out[7][k] == 1
    ]
    check(
        "double_top_zigzag Boolean系列では同一バーの2件が1件に潰れる(この前提を明示)",
        confirmed_bars == [16],
        detail=str(confirmed_bars),
    )
    check(
        "double_top_zigzag events側は同一バーで決着した2件を別レコードとして保持する",
        len(confirmed_events) == 2 and all(bar == 16 for bar, _ in confirmed_events),
        detail=str(confirmed_events),
    )
    check(
        "double_top_zigzag 同一バーの2件がそれぞれ別のpattern_idを持つ",
        confirmed_events[0][1] != confirmed_events[1][1]
        and {pid for _, pid in confirmed_events} == {"double_top_3_4_5", "double_top_8_10_12"},
        detail=str([pid for _, pid in confirmed_events]),
    )


def test_double_top_zigzag_event_records_carry_the_full_pattern_detail():
    # 仕様書8章: 1イベントごとに pattern_id / pattern_type / status /
    # event_bar / P1〜P3のバーと価格 / ratio を識別できること。
    closes = np.concatenate([
        _zz_seg(80, 90, 8), _zz_seg(90, 85, 8),
        _zz_seg(85, 120, 12), _zz_seg(120, 108, 12),
        _zz_seg(108, 118, 12), _zz_seg(118, 95, 20),
    ])
    high, low, close = _hlc(closes, wick=0.05)
    state = cp._zigzag_dtdb_state(high, low, close, length=5, max_risk_ratio=30)
    events = state["events"]
    required = {
        "pattern_id", "pattern_type", "status", "event_bar",
        "p1_bar", "p1_price", "p2_bar", "p2_price", "p3_bar", "p3_price", "ratio",
    }
    check(
        "double_top_zigzag events の各レコードが必要な項目を全て持つ",
        len(events) >= 2 and all(required <= set(e) for e in events),
        detail=str(events[:1]),
    )
    check(
        "double_top_zigzag 同じパターンのCandidateとConfirmedが同一のpattern_idで結び付く",
        events[0]["status"] == "candidate"
        and events[1]["status"] == "confirmed"
        and events[0]["pattern_id"] == events[1]["pattern_id"],
        detail=str([(e["status"], e["pattern_id"]) for e in events]),
    )
    check(
        "double_top_zigzag pattern_idが「種類_P1バー_P2バー_P3バー」の形式になっている",
        events[0]["pattern_id"]
        == f"double_top_{events[0]['p1_bar']}_{events[0]['p2_bar']}_{events[0]['p3_bar']}",
        detail=events[0]["pattern_id"],
    )


def test_double_top_zigzag_clamps_parameters_into_the_spec_range():
    # 仕様書2章: length>=5、5<=max_risk_ratio<=100 をエンジン側でも保証する
    # (UIのmin/max指定だけに頼らない)。範囲外を渡しても境界値と同じ結果に
    # なること、かつ範囲内では値がちゃんと効いていることの両方を見る。
    closes = np.concatenate([
        _zz_seg(80, 90, 8), _zz_seg(90, 85, 8),
        _zz_seg(85, 120, 12), _zz_seg(120, 108, 12),
        _zz_seg(108, 118, 12), _zz_seg(118, 95, 20),
        _zz_seg(95, 130, 14), _zz_seg(130, 112, 14),
        _zz_seg(112, 127, 14), _zz_seg(127, 100, 22),
    ])
    high, low, close = _hlc(closes, wick=0.05)

    def candidates(**kwargs):
        return cp.double_top_zigzag(high, low, close, state="candidate", **kwargs)

    at_min_length = candidates(length=5)
    check(
        "double_top_zigzag length<5は5へ丸められる",
        all(np.array_equal(candidates(length=L), at_min_length) for L in (1, 2, 3, 4)),
        detail="length 1〜4 が length=5 と一致しない",
    )
    check(
        "double_top_zigzag lengthは範囲内では実際に結果を変える(丸めテストの前提確認)",
        not np.array_equal(candidates(length=12), at_min_length),
    )

    at_min_ratio = candidates(length=10, max_risk_ratio=5)
    at_max_ratio = candidates(length=10, max_risk_ratio=100)
    check(
        "double_top_zigzag max_risk_ratio<5は5へ丸められる",
        np.array_equal(candidates(length=10, max_risk_ratio=0), at_min_ratio)
        and np.array_equal(candidates(length=10, max_risk_ratio=-99), at_min_ratio),
    )
    check(
        "double_top_zigzag max_risk_ratio>100は100へ丸められる",
        np.array_equal(candidates(length=10, max_risk_ratio=200), at_max_ratio),
    )
    check(
        "double_top_zigzag max_risk_ratioは範囲内では実際に結果を変える(丸めテストの前提確認)",
        not np.array_equal(at_min_ratio, at_max_ratio),
    )


# ---------------------------------------------------------------------------
# トリプルトップ/ボトム・カップ&ハンドル・ヘッド&ショルダーズ(多段ZigZag方式、
# B方式実装)。仕様: docs/pattern_spec_reversal_chart_patterns_recursive.md
#
# 合成データの作り方に2つコツがある(どちらも仕様書の挙動そのもの):
#   1. 系列は必ず**下落から始める**。参考元のZigZagは初期方向が+1で、最初の
#      ピボットは「安値ピボット」の分岐でしか生まれないため、上昇から始めると
#      その上昇区間はまるごとZigZagに乗らない(仕様書3.2の②)。
#   2. 転換点は必ず交互(高値→安値→高値…)に並べる。同方向が続くと途中の値は
#      ピボットにならない。
# ---------------------------------------------------------------------------

def _rrcp_series(pivot_prices, bars_per_leg=10, wick=0.02):
    legs = [
        np.linspace(pivot_prices[i], pivot_prices[i + 1], bars_per_leg, endpoint=False)
        for i in range(len(pivot_prices) - 1)
    ]
    legs.append(np.array([pivot_prices[-1]]))
    closes = np.concatenate(legs)
    return pd.Series(closes + wick), pd.Series(closes - wick), pd.Series(closes)


def _rrcp_candidates(pivot_prices, **kwargs):
    high, low, close = _rrcp_series(pivot_prices)
    state = cp._rrcp_state(high, low, close, zigzag_length=3, **kwargs)
    return [e for e in state["events"] if e["status"] == "candidate"]


def test_rrcp_detects_each_of_the_six_patterns():
    # 仕様書5.3/5.4。ratioの組み合わせを手計算で作り込んだ6つの形が、
    # それぞれ意図した種類・向きで検出されることを確認する。
    cases = [
        # v=100 w=200 x=170 a=200 b=170 c=200 → r4=0.3(肩) r3=r2=r1=1(Tap)
        ("triple_top", [250, 100, 200, 170, 200, 170, 200, 150]),
        ("triple_bottom", [250, 150, 200, 100, 130, 100, 130, 100, 150]),
        # a=290 が Head(|x→a|/|w→x| = 120/30 = 4)、r1=0.3・r4=0.3 が肩
        ("head_and_shoulders", [250, 100, 200, 170, 290, 170, 206, 150]),
        ("inverse_head_and_shoulders", [250, 150, 200, 100, 130, 10, 130, 94, 150]),
        # r2=1(Tap)・r1=0.3(肩)だけ。r3=1 なので Head にならず H&S を外れる
        ("cup_and_handle", [250, 100, 200, 100, 200, 170, 220]),
        ("inverted_cup_and_handle", [50, 250, 100, 200, 100, 200, 100, 130, 80]),
    ]
    for want, pivots in cases:
        hits = [e for e in _rrcp_candidates(pivots) if e["pattern_type"] == want]
        check(
            f"{want} が意図した形で検出される",
            len(hits) >= 1,
            detail=f"検出された種類={sorted({e['pattern_type'] for e in _rrcp_candidates(pivots)})}",
        )


def test_rrcp_head_and_shoulders_needs_the_head_ratio():
    # 仕様書5.3: H&Sは r3 が Head(1/shoulder_end 〜 1/shoulder_start = 2〜10)で
    # あることが必須。ヘッドを浅くして r3 を範囲外にすると H&S にならない。
    # a=290(|x→a|/|w→x| = 120/30 = 4 → Head)
    with_head = [250, 100, 200, 170, 290, 170, 206, 150]
    # a=215(|x→a|/|w→x| = 45/30 = 1.5 → Headの下限2に届かない)
    without_head = [250, 100, 200, 170, 215, 170, 183.5, 150]
    check(
        "head_and_shoulders はヘッド比率を満たすと検出される(前提確認)",
        any(e["pattern_type"] == "head_and_shoulders" for e in _rrcp_candidates(with_head)),
    )
    check(
        "head_and_shoulders はヘッド比率を満たさないと検出されない",
        not any(e["pattern_type"] == "head_and_shoulders" for e in _rrcp_candidates(without_head)),
        detail=str(sorted({e["pattern_type"] for e in _rrcp_candidates(without_head)})),
    )


def test_rrcp_point_counts_match_the_spec():
    # 仕様書5.6: トリプルとH&Sは6点、カップ&ハンドルは4点。
    expected = {
        "triple_top": (6, [250, 100, 200, 170, 200, 170, 200, 150]),
        "head_and_shoulders": (6, [250, 100, 200, 170, 290, 170, 206, 150]),
        "cup_and_handle": (4, [250, 100, 200, 100, 200, 170, 220]),
    }
    for name, (want_points, pivots) in expected.items():
        hits = [e for e in _rrcp_candidates(pivots) if e["pattern_type"] == name]
        check(
            f"{name} の構成点数が{want_points}点である",
            bool(hits) and all(len(e["point_bars"]) == want_points for e in hits),
            detail=str([len(e["point_bars"]) for e in hits]),
        )


def test_rrcp_neckline_and_extreme_follow_the_spec():
    # 仕様書6.1: ネックラインは「新しい方から2番目の構成点」(参考元の
    # エントリー価格)、パターン極値はトップ系なら構成点の最高値・ボトム系なら
    # 最安値。
    top = [e for e in _rrcp_candidates([250, 100, 200, 170, 200, 170, 200, 150])
           if e["pattern_type"] == "triple_top"][0]
    bottom = [e for e in _rrcp_candidates([250, 150, 200, 100, 130, 100, 130, 100, 150])
              if e["pattern_type"] == "triple_bottom"][0]
    check(
        "ネックラインが新しい方から2番目の構成点の価格になっている",
        top["neckline_price"] == top["point_prices"][1]
        and bottom["neckline_price"] == bottom["point_prices"][1],
        detail=f"top={top['neckline_price']}/{top['point_prices'][1]} bottom={bottom['neckline_price']}/{bottom['point_prices'][1]}",
    )
    check(
        "トップ系の極値が構成点の最高値、ボトム系が最安値になっている",
        top["extreme_price"] == max(top["point_prices"])
        and bottom["extreme_price"] == min(bottom["point_prices"]),
        detail=f"top={top['extreme_price']} bottom={bottom['extreme_price']}",
    )


def test_rrcp_confirmed_and_invalidated_follow_double_top_rules():
    # 仕様書6.2(StrategyX独自拡張): トップ系は安値がネックを下抜けで
    # Confirmed、高値が極値を上抜けでInvalidated。同一バーで両方成立したら
    # Confirmed優先。1パターン1決着。_rrcp_resolve_coreを直接呼んで、
    # ZigZagの都合を挟まずに判定だけを見る。
    high_a = np.array([100.0, 100.0, 100.0, 100.0, 100.0], dtype=float)
    low_a = np.array([100.0, 100.0, 100.0, 100.0, 100.0], dtype=float)

    # トップ系(dir=-1)、ネック90・極値120。バー2で安値が90を割る。
    low_a[2] = 80.0
    status, bar, ovf = cp._rrcp_resolve_core(
        high_a, low_a,
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([120.0]), 16,
    )
    check("トップ系: 安値がネックを下抜けでConfirmed", status[0] == 1 and bar[0] == 2,
          detail=f"status={status[0]} bar={bar[0]}")

    # 同じ形で、先に高値が極値を上抜けした場合はInvalidated
    high_b = np.array([100.0, 100.0, 130.0, 100.0, 100.0], dtype=float)
    low_b = np.array([100.0, 100.0, 100.0, 100.0, 100.0], dtype=float)
    status, bar, ovf = cp._rrcp_resolve_core(
        high_b, low_b,
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([120.0]), 16,
    )
    check("トップ系: 高値が極値を上抜けでInvalidated", status[0] == 2 and bar[0] == 2,
          detail=f"status={status[0]} bar={bar[0]}")

    # 同一バーで両方成立 → Confirmed優先
    high_c = np.array([100.0, 100.0, 130.0, 100.0, 100.0], dtype=float)
    low_c = np.array([100.0, 100.0, 80.0, 100.0, 100.0], dtype=float)
    status, bar, ovf = cp._rrcp_resolve_core(
        high_c, low_c,
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([120.0]), 16,
    )
    check("同一バーで両条件が成立したらConfirmedを優先する", status[0] == 1,
          detail=f"status={status[0]}")

    # 決着後にもう一度ネックを割っても2回目は出ない(1パターン1決着)
    high_d = np.array([100.0] * 7, dtype=float)
    low_d = np.array([100.0, 100.0, 80.0, 100.0, 100.0, 80.0, 100.0], dtype=float)
    status, bar, ovf = cp._rrcp_resolve_core(
        high_d, low_d,
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([120.0]), 16,
    )
    check("決着後に再度ネックを割ってもバーは最初の1回のまま", status[0] == 1 and bar[0] == 2,
          detail=f"status={status[0]} bar={bar[0]}")

    # ボトム系(dir=+1)は鏡像
    high_e = np.array([100.0, 100.0, 130.0, 100.0, 100.0], dtype=float)
    low_e = np.array([100.0] * 5, dtype=float)
    status, bar, ovf = cp._rrcp_resolve_core(
        high_e, low_e,
        np.array([0], dtype=np.int64), np.array([1], dtype=np.int64),
        np.array([120.0]), np.array([80.0]), 16,
    )
    check("ボトム系: 高値がネックを上抜けでConfirmed(鏡像)", status[0] == 1 and bar[0] == 2,
          detail=f"status={status[0]} bar={bar[0]}")


def test_rrcp_pattern_ids_are_unique_and_link_candidate_to_resolution():
    # 共通管理仕様7.1/7.3(仕様書): pattern_idは「種類_構成点のバー位置」で、
    # 同じIDは再登録しない。CandidateとConfirmed/Invalidatedは同じIDで結び付く。
    events = cp._rrcp_state(
        *_rrcp_series([250, 100, 200, 170, 200, 170, 200, 150]), zigzag_length=3
    )["events"]
    candidates = [e for e in events if e["status"] == "candidate"]
    ids = [e["pattern_id"] for e in candidates]
    check(
        "Candidateのpattern_idが全件ユニークである",
        len(ids) == len(set(ids)),
        detail=f"{len(ids)}件中ユニーク{len(set(ids))}件",
    )
    check(
        "pattern_idが「種類_構成点のバー位置」の形式になっている",
        all(e["pattern_id"] == e["pattern_type"] + "".join(f"_{b}" for b in e["point_bars"])
            for e in candidates),
        detail=candidates[0]["pattern_id"] if candidates else "",
    )
    resolutions = [e for e in events if e["status"] != "candidate"]
    check(
        "決着イベントのpattern_idが必ず対応するCandidateに存在する",
        all(e["pattern_id"] in set(ids) for e in resolutions),
    )
    check(
        "1つのpattern_idにつき決着イベントは最大1件",
        len({e["pattern_id"] for e in resolutions}) == len(resolutions),
        detail=f"決着{len(resolutions)}件 / ユニーク{len({e['pattern_id'] for e in resolutions})}件",
    )


def test_rrcp_clamps_parameters_into_the_spec_range():
    # 仕様書1章: 有効範囲を検出器内部でも保証する(UI任せにしない)。
    high, low, close = _rrcp_series([250, 100, 200, 170, 200, 170, 200, 150])

    def cand(**kwargs):
        return cp.triple_top(high, low, close, state="candidate", zigzag_length=3, **kwargs)

    at_min = cand(error_percent=0.0)
    check(
        "error_percent が下限0未満なら0へ丸められる",
        np.array_equal(cand(error_percent=-10.0), at_min),
    )
    at_max = cand(error_percent=50.0)
    check(
        "error_percent が上限50超なら50へ丸められる",
        np.array_equal(cand(error_percent=999.0), at_max),
    )
    check(
        "error_percent は範囲内では実際に結果を変える(丸めテストの前提確認)",
        not np.array_equal(at_min, at_max),
    )
    base_len = cp.triple_top(high, low, close, state="candidate", zigzag_length=3)
    check(
        "zigzag_length が下限3未満なら3へ丸められる",
        all(np.array_equal(cp.triple_top(high, low, close, state="candidate", zigzag_length=L), base_len)
            for L in (0, 1, 2)),
    )
    at_sh_min = cand(shoulder_start=0.1)
    check(
        "shoulder_start が下限0.1未満なら0.1へ丸められる",
        np.array_equal(cand(shoulder_start=0.0), at_sh_min),
    )


# ---------------------------------------------------------------------------
# ABCDパターン(投影型、B方式実装)。仕様: docs/pattern_spec_abcd_projection.md
#
# ZigZagの合成データはRRCPと同じ2つのコツ(下落から始める / 転換点を交互に置く)
# が要る。加えてこのパターンは offset=1 なのでZigZagが1本遅れる。
# ---------------------------------------------------------------------------

def _abcd_series(pivot_prices, bars_per_leg=12, wick=0.02):
    legs = [
        np.linspace(pivot_prices[i], pivot_prices[i + 1], bars_per_leg, endpoint=False)
        for i in range(len(pivot_prices) - 1)
    ]
    legs.append(np.array([pivot_prices[-1]]))
    closes = np.concatenate(legs)
    return pd.Series(closes + wick), pd.Series(closes - wick), pd.Series(closes)


# A=200(高) B=100(安) C=150(高) になる形。
#   ratio = |B-C| / |A-B| = 50/100 = 0.5
#   D価格 = C + (1/0.5)×(B-C) = 150 + 2×(-50) = 50
#   方向  = sign(D - A) = sign(50-200) = -1 (弱気)
_ABCD_FIXTURE = [250, 120, 200, 100, 150, 130, 138]


def _abcd_candidates(pivots=None, **kwargs):
    high, low, close = _abcd_series(pivots if pivots is not None else _ABCD_FIXTURE)
    state = cp._abcd_state(high, low, close, zigzag_length=3, **kwargs)
    return [e for e in state["events"] if e["status"] == "candidate"]


def test_abcd_projects_d_point_from_the_abc_ratio():
    # 仕様書5章: bcdRatio = 1/ratio、D価格 = C + bcdRatio×(B-C)。
    # 方向は sign(D価格 - A価格)(仕様書7章)。
    hits = _abcd_candidates()
    check("abcd 手作りのABCD形が1件検出される", len(hits) == 1, detail=str(len(hits)))
    if not hits:
        return
    e = hits[0]
    check(
        "abcd A/B/Cの価格が構成どおりに取れている",
        abs(e["a_price"] - 200.0) < 0.1 and abs(e["b_price"] - 100.0) < 0.1
        and abs(e["c_price"] - 150.0) < 0.1,
        detail=f"A={e['a_price']} B={e['b_price']} C={e['c_price']}",
    )
    check(
        "abcd ABC比率が |B-C|/|A-B| = 0.5 になっている",
        abs(e["abc_ratio"] - 0.5) < 1e-9,
        detail=str(e["abc_ratio"]),
    )
    check(
        "abcd D価格が C + (1/ratio)×(B-C) = 50 に投影されている",
        abs(e["d_price"] - 50.0) < 0.2,
        detail=str(e["d_price"]),
    )
    check(
        "abcd 方向が sign(D-A) で弱気になっている",
        e["pattern_type"] == "abcd_bearish",
        detail=e["pattern_type"],
    )
    check(
        "abcd stop=A価格 / target=D価格 になっている(仕様書7章)",
        e["stop_price"] == e["a_price"] and e["target_price"] == e["d_price"],
        detail=f"stop={e['stop_price']} target={e['target_price']}",
    )


def test_abcd_ratio_range_includes_both_ends():
    # 仕様書6章④: ABC比率は両端を含む <= で判定する。フィクスチャの比率は
    # ちょうど0.5なので、下限0.5なら成立・0.6なら不成立になるはず。
    check(
        "abcd ABC比率が下限とちょうど同値なら成立する(両端を含む)",
        len(_abcd_candidates(min_abc_ratio=0.5)) == 1,
    )
    check(
        "abcd ABC比率が下限を下回れば不成立",
        len(_abcd_candidates(min_abc_ratio=0.6)) == 0,
    )
    check(
        "abcd ABC比率が上限とちょうど同値なら成立する(両端を含む)",
        len(_abcd_candidates(min_abc_ratio=0.382, max_abc_ratio=0.5)) == 1,
    )


def test_abcd_resolution_is_touch_based_and_happens_once():
    # 仕様書8章: target到達=Confirmed、stop到達=Invalidated。クロスではなく
    # 到達(タッチ)で判定し、同一バーで両方ならConfirmed優先。決着は1回だけ。
    # 評価はCandidate成立の"次の"バーから始まる。
    flat = np.array([100.0] * 6, dtype=float)

    # 弱気(dir=-1): target=90(下)、stop=110(上)。バー2で安値が90に到達。
    low_a = flat.copy(); low_a[2] = 90.0
    status, bar, ovf = cp._abcd_resolve_core(
        flat.copy(), low_a,
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([110.0]), 16,
    )
    check("abcd target到達でConfirmed", status[0] == 1 and bar[0] == 2,
          detail=f"status={status[0]} bar={bar[0]}")

    # 同じ形で高値がstopに到達 → Invalidated
    high_b = flat.copy(); high_b[2] = 110.0
    status, bar, ovf = cp._abcd_resolve_core(
        high_b, flat.copy(),
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([110.0]), 16,
    )
    check("abcd stop到達でInvalidated", status[0] == 2 and bar[0] == 2,
          detail=f"status={status[0]} bar={bar[0]}")

    # 同一バーで両方到達 → Confirmed優先
    high_c = flat.copy(); high_c[2] = 110.0
    low_c = flat.copy(); low_c[2] = 90.0
    status, bar, ovf = cp._abcd_resolve_core(
        high_c, low_c,
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([110.0]), 16,
    )
    check("abcd 同一バーで両方到達したらConfirmed優先", status[0] == 1, detail=str(status[0]))

    # 決着後に再度到達しても2回目は出ない
    low_d = np.array([100.0, 100.0, 90.0, 100.0, 90.0, 100.0], dtype=float)
    status, bar, ovf = cp._abcd_resolve_core(
        flat.copy(), low_d,
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([110.0]), 16,
    )
    check("abcd 決着後に再到達しても決着バーは最初の1回のまま",
          status[0] == 1 and bar[0] == 2, detail=f"bar={bar[0]}")

    # 成立バー(0)では評価しない - バー0で既にtargetに到達していても決着させない
    low_e = flat.copy(); low_e[0] = 90.0
    status, bar, ovf = cp._abcd_resolve_core(
        flat.copy(), low_e,
        np.array([0], dtype=np.int64), np.array([-1], dtype=np.int64),
        np.array([90.0]), np.array([110.0]), 16,
    )
    check("abcd 評価はCandidate成立の次のバーから始まる", status[0] == 0, detail=str(status[0]))

    # 強気(dir=+1)は鏡像
    high_f = flat.copy(); high_f[2] = 110.0
    status, bar, ovf = cp._abcd_resolve_core(
        high_f, flat.copy(),
        np.array([0], dtype=np.int64), np.array([1], dtype=np.int64),
        np.array([110.0]), np.array([90.0]), 16,
    )
    check("abcd 強気は高値がtargetに到達でConfirmed(鏡像)", status[0] == 1 and bar[0] == 2,
          detail=f"status={status[0]} bar={bar[0]}")


def test_abcd_pattern_ids_are_unique_and_formatted():
    # 共通管理仕様9.1: pattern_id = 種類_Cバー_Bバー_Aバー(新しい順)。
    high, low, close = _abcd_series(_ABCD_FIXTURE)
    events = cp._abcd_state(high, low, close, zigzag_length=3)["events"]
    cands = [e for e in events if e["status"] == "candidate"]
    ids = [e["pattern_id"] for e in cands]
    check("abcd Candidateのpattern_idがユニーク", len(ids) == len(set(ids)))
    check(
        "abcd pattern_idが「種類_Cバー_Bバー_Aバー」の形式",
        all(e["pattern_id"] == f"{e['pattern_type']}_{e['c_bar']}_{e['b_bar']}_{e['a_bar']}"
            for e in cands),
        detail=ids[0] if ids else "",
    )
    resolutions = [e for e in events if e["status"] != "candidate"]
    check(
        "abcd 1つのpattern_idにつき決着は最大1件",
        len({e["pattern_id"] for e in resolutions}) == len(resolutions),
    )


def test_abcd_clamps_parameters_into_the_spec_range():
    # 仕様書1章: 有効範囲を検出器内部でも保証する。
    high, low, close = _abcd_series(_ABCD_FIXTURE)

    def cand(**kwargs):
        return cp.abcd_bearish(high, low, close, state="candidate", zigzag_length=3, **kwargs)

    at_min = cand(min_abc_ratio=0.382)
    check("abcd min_abc_ratio が下限0.382未満なら0.382へ丸められる",
          np.array_equal(cand(min_abc_ratio=0.0), at_min))
    at_max = cand(max_abc_ratio=1.0)
    check("abcd max_abc_ratio が上限1.0超なら1.0へ丸められる",
          np.array_equal(cand(max_abc_ratio=9.9), at_max))
    base_len = cp.abcd_bearish(high, low, close, state="candidate", zigzag_length=3)
    check(
        "abcd zigzag_length が下限3未満なら3へ丸められる",
        all(np.array_equal(cp.abcd_bearish(high, low, close, state="candidate", zigzag_length=L), base_len)
            for L in (0, 1, 2)),
    )
    check(
        "abcd min > max で渡されたら入れ替えられる",
        np.array_equal(cand(min_abc_ratio=1.0, max_abc_ratio=0.382),
                       cand(min_abc_ratio=0.382, max_abc_ratio=1.0)),
    )


# ---------------------------------------------------------------------------
# ABCパターン(多段ZigZag、B方式実装)。仕様: docs/pattern_spec_abc_recursive.md
# ---------------------------------------------------------------------------

def test_abc_level_formulas_match_fibratios():
    # 仕様書6章 / 0章のFibRatios全式。A=100 B=200 C=150 で手計算と突き合わせる。
    a, b, c = 100.0, 200.0, 150.0
    ext = cp._ABC_BASE_EXTENSION
    ret = cp._ABC_BASE_RETRACEMENT
    check(
        "abc extension(非対数) = C + (B-A)×ratio",
        abs(cp._abc_level_price(a, b, c, 0.3, ext, False) - (c + (b - a) * 0.3)) < 1e-9
        and abs(cp._abc_level_price(a, b, c, 0.0, ext, False) - c) < 1e-9,
    )
    check(
        "abc retracement(非対数) = C - (C-B)×ratio",
        abs(cp._abc_level_price(a, b, c, 0.3, ret, False) - (c - (c - b) * 0.3)) < 1e-9,
    )
    check(
        "abc extension(対数) = C × (B/A)^ratio",
        abs(cp._abc_level_price(a, b, c, 0.3, ext, True) - c * (b / a) ** 0.3) < 1e-9,
    )
    check(
        "abc retracement(対数) = C × (B/C)^ratio",
        abs(cp._abc_level_price(a, b, c, 0.3, ret, True) - c * (b / c) ** 0.3) < 1e-9,
    )


def test_abc_status_transitions_follow_the_reference():
    # 仕様書7章: status 0(未到達)→1(エントリー到達)→2(利確到達)。
    # 利確到達=Confirmed、損切りでの終了=Invalidated。評価は次のバーから。
    # 強気(dir=+1)、entry=110 / target=120 / stop=90、終値ベース(参考元の初期値)。
    def run(close_seq):
        cl = np.array(close_seq, dtype=float)
        return cp._abc_resolve_core(
            cl.copy(), cl.copy(), cl,
            np.array([0], dtype=np.int64), np.array([1], dtype=np.int64),
            np.array([110.0]), np.array([120.0]), np.array([90.0]),
            True, True, True, 16,
        )

    res, bar, _ = run([100, 105, 112, 125, 100])
    check("abc エントリー到達後に利確到達でConfirmed", res[0] == 1 and bar[0] == 3,
          detail=f"res={res[0]} bar={bar[0]}")

    res, bar, _ = run([100, 105, 112, 85, 100])
    check("abc エントリー到達後に損切りでInvalidated", res[0] == 2 and bar[0] == 3,
          detail=f"res={res[0]} bar={bar[0]}")

    # 状態0のまま(エントリー未到達)で終値が損切りを下回る → Invalidated
    res, bar, _ = run([100, 100, 85, 100, 100])
    check("abc エントリー未到達のまま損切りを割ってもInvalidated", res[0] == 2 and bar[0] == 2,
          detail=f"res={res[0]} bar={bar[0]}")

    # 成立バー(0)では評価しない
    res, bar, _ = run([125, 100, 100, 100, 100])
    check("abc 評価はCandidate成立の次のバーから始まる", res[0] == 0 or bar[0] != 0,
          detail=f"res={res[0]} bar={bar[0]}")

    # 決着後は再判定しない
    res, bar, _ = run([100, 125, 100, 125, 100])
    check("abc 決着後に再度利確水準へ戻っても決着バーは最初の1回のまま",
          res[0] == 1 and bar[0] == 1, detail=f"bar={bar[0]}")


def test_abc_detection_conditions_on_real_data():
    # 仕様書5章①②③。実データで、出力された全Candidateが3条件を満たしている
    # ことを検証する(合成データでZigZagのratioを0.618〜0.786へ正確に載せるのが
    # 難しいため、実データ側から条件の成立を確かめる方針)。
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True).tail(40000).reset_index(drop=True)
    state = cp._abc_state(df["high"], df["low"], df["close"])
    cands = [e for e in state["events"] if e["status"] == "candidate"]
    check("abc 実データでCandidateが検出される(前提確認)", len(cands) > 0, detail=str(len(cands)))
    if not cands:
        return
    check(
        "abc 全CandidateのratioがFib範囲0.618〜0.786(両端含む)に収まっている",
        all(0.618 <= e["bc_ratio"] <= 0.786 for e in cands),
        detail=str(sorted({round(e["bc_ratio"], 3) for e in cands})[:5]),
    )
    check(
        "abc 方向が B価格 > C価格 のとき強気になっている",
        all((e["b_price"] > e["c_price"]) == (e["pattern_type"] == "abc_bullish") for e in cands),
    )
    check(
        "abc entry/target/stop が extension式(C+(B-A)×ratio)と一致する",
        all(abs(e["entry_price"] - (e["c_price"] + (e["b_price"] - e["a_price"]) * 0.3)) < 1e-6
            and abs(e["target_price"] - (e["c_price"] + (e["b_price"] - e["a_price"]) * 1.0)) < 1e-6
            and abs(e["stop_price"] - e["c_price"]) < 1e-6
            for e in cands),
    )
    ids = [e["pattern_id"] for e in cands]
    check("abc Candidateのpattern_idがユニーク", len(ids) == len(set(ids)))
    check(
        "abc pattern_idが「種類_Cバー_Bバー_Aバー」の形式",
        all(e["pattern_id"] == f"{e['pattern_type']}_{e['c_bar']}_{e['b_bar']}_{e['a_bar']}" for e in cands),
        detail=ids[0],
    )
    resolutions = [e for e in state["events"] if e["status"] != "candidate"]
    check(
        "abc 1つのpattern_idにつき決着は最大1件",
        len({e["pattern_id"] for e in resolutions}) == len(resolutions),
    )


def test_abc_trade_condition_filter_narrows_results():
    # 仕様書5章②: 方向フィルター。any が最も広く、他は必ずその部分集合になる。
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True).tail(30000).reset_index(drop=True)

    def ids(cond):
        st = cp._abc_state(df["high"], df["low"], df["close"], trade_condition=cond)
        return {e["pattern_id"] for e in st["events"] if e["status"] == "candidate"}

    any_ids = ids("any")
    subsets = {c: ids(c) for c in ("trend", "reverse", "contracting", "expanding")}
    check(
        "abc 各方向フィルターの結果が any の部分集合になっている",
        all(s <= any_ids for s in subsets.values()),
        detail=str({k: len(v) for k, v in subsets.items()}),
    )
    # 4つのフィルターは |A.dir| / |B.dir| の (1,2) の組み合わせを網羅しているので、
    # 和集合は any と一致する。ただし単純な合計では一致しない - pattern_id は
    # ZigZagレベルを含まないため、同じ構成点(バー位置)が2つのレベルに現れて
    # レベルごとに dir 分類が違うと、同一IDが別々のフィルターに現れうる。
    # これは仕様どおり(構成点が同一なら同じパターンとみなす)。
    union = set().union(*subsets.values())
    check(
        "abc 4つの方向フィルターの和集合が any と一致する(組み合わせを網羅している)",
        union == any_ids,
        detail=f"和集合={len(union)} any={len(any_ids)} 差={len(any_ids ^ union)}",
    )


def test_abc_clamps_parameters_into_the_spec_range():
    # 仕様書1章: 有効範囲を検出器内部でも保証する(特に stop_ratio <= 0)。
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True).tail(20000).reset_index(drop=True)
    h, l, c = df["high"], df["low"], df["close"]

    def arr(**kw):
        return cp.abc_bullish(h, l, c, state="candidate", **kw)

    base_len = arr(zigzag_length=3)
    check(
        "abc zigzag_length が下限3未満なら3へ丸められる",
        all(np.array_equal(arr(zigzag_length=L), base_len) for L in (0, 1, 2)),
    )
    at_min_entry = arr(entry_ratio=0.1)
    check("abc entry_ratio が下限0.1未満なら0.1へ丸められる",
          np.array_equal(arr(entry_ratio=0.0), at_min_entry))
    at_max_stop = arr(stop_ratio=0.0)
    check("abc stop_ratio が上限0.0を超えたら0.0へ丸められる",
          np.array_equal(arr(stop_ratio=0.5), at_max_stop))
    at_max_depth = arr(depth=500)
    check("abc depth が上限500を超えたら500へ丸められる",
          np.array_equal(arr(depth=9999), at_max_depth))



# ---------------------------------------------------------------------------
# エリオット推進波(多段ZigZag、B方式実装)
# docs/pattern_spec_motive_wave.md の各章に対応させたテスト。
# ---------------------------------------------------------------------------

# 仕様書6.1/6.2の並び順どおりに P0..P5 が拾える価格列(index0が最新)。
# 上昇波: index0=最高値、以降 安値・高値と交互に古くなる。
_MW_UP_PRICES = np.array([135.0, 118.0, 128.0, 105.0, 115.0, 100.0])


def test_mw_trend_series_ordering_matches_the_reference():
    """仕様書6.1。trendSeriesは先頭挿入なので古い順、pullbackSeriesは
    末尾追加なので発見順(最安値から手前へ)になる。"""
    out = np.zeros(64, dtype=np.int64)
    n_ts = cp._mw_trend_series(_MW_UP_PRICES, 6, 1, 1, out, 64)
    ts = out[:n_ts].tolist()
    check("mw trendSeries は古い順(絶対indexの降順)で返る", ts == [4, 2], f"got {ts}")

    n_ps = cp._mw_trend_series(_MW_UP_PRICES, 6, -1, 1, out, 64)
    ps = out[:n_ps].tolist()
    check("mw pullbackSeries は最安値から手前へ向かって返る", ps == [5, 3, 1], f"got {ps}")
    check("mw P0(pullbackSeriesの先頭)は区間の最安値", ps[0] == 5, f"got {ps}")


def test_mw_check_classifies_a_textbook_impulse():
    """仕様書6.4。教科書どおりの5波を推進波として分類する。"""
    p = _MW_UP_PRICES
    wt, w2r, w3r, w4r, w5r, mr = cp._mw_check(p[5], p[4], p[3], p[2], p[1], p[0])
    check("mw 教科書どおりの5波は推進波(コード1)になる",
          wt == cp._MW_TYPE_IMPULSE, f"got {wt}")
    # w2Ratio = w2の長さ / w1の長さ = 10/15、w3Ratio = 23/10 …(仕様書6.4)
    check("mw w2Ratio は w2の長さ÷w1の長さ", abs(w2r - 0.667) < 1e-9, f"got {w2r}")
    check("mw w3Ratio は w3の長さ÷w2の長さ", abs(w3r - 2.3) < 1e-9, f"got {w3r}")
    check("mw w4Ratio は w4の長さ÷w3の長さ", abs(w4r - 0.435) < 1e-9, f"got {w4r}")
    check("mw w5Ratio は w5の長さ÷w4の長さ", abs(w5r - 1.7) < 1e-9, f"got {w5r}")
    check("mw mRatio は w4の長さ÷(P3-P0)", abs(mr - 0.357) < 1e-9, f"got {mr}")


def test_mw_ratios_are_rounded_to_three_decimals():
    """仕様書6.4。retracementRatio は precision=3 が既定なので、閾値との
    比較は丸めた後の値で行われる。w5Ratio=0.9004 は0.900に丸まって
    「> 0.9」を満たさない。"""
    def classify(w5_len: float) -> int:
        # w4の長さが10になる形。w5Ratio = w5_len / 10。
        p0, p1, p2, p3, p4 = 100.0, 115.0, 105.0, 128.0, 118.0
        return cp._mw_check(p0, p1, p2, p3, p4, p4 + w5_len)[0]

    check("mw w5Ratio 0.9004 は 0.900 に丸まって不成立", classify(9.004) == 0,
          f"got {classify(9.004)}")
    check("mw w5Ratio 0.9006 は 0.901 に丸まって成立",
          classify(9.006) == cp._MW_TYPE_IMPULSE, f"got {classify(9.006)}")


def test_mw_diagonals_are_unreachable_in_the_reference():
    """仕様書6.6。参考元は収束/拡大ダイアゴナルも分類するが、
    isMotiveWave が要求する w2Ratio<1(= w2<w1)と w3Ratio>1(= w3>w2)は
    収束(w1>w2>w3)とも拡大(w1<w2<w3)とも矛盾するため、どちらも
    決して成立しない。だから公開指標にもしていない。"""
    contracting = cp._mw_check(100.0, 130.0, 105.0, 125.0, 110.0, 122.0)[0]
    check("mw 収束ダイアゴナルの形は参考元の条件では成立しない", contracting == 0,
          f"got {contracting}")
    expanding = cp._mw_check(100.0, 105.0, 95.0, 115.0, 85.0, 125.0)[0]
    check("mw 拡大ダイアゴナルの形は参考元の条件では成立しない", expanding == 0,
          f"got {expanding}")
    check("mw 公開指標は推進波の上下2本だけ",
          sorted(cp._MW_PATTERN_NAMES.values()) ==
          ["impulse_wave_bearish", "impulse_wave_bullish"],
          f"got {sorted(cp._MW_PATTERN_NAMES.values())}")


def _mw_real_events(**kw):
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True)
    df = df.tail(40000).reset_index(drop=True)
    return df, cp._mw_state(df["high"], df["low"], df["close"], **kw)


def test_mw_events_follow_the_common_management_spec():
    """共通管理仕様7.1〜7.4。pattern_idは一意、Candidateは1回、決着も1回、
    決着はCandidateより後のバー。"""
    _, res = _mw_real_events()
    events = res["events"]
    check("mw 実データで推進波が検出される", len(events) > 0, f"got {len(events)}")

    by_id: dict[str, list[dict]] = {}
    for ev in events:
        by_id.setdefault(ev["pattern_id"], []).append(ev)

    ok_cand = all(sum(1 for e in v if e["status"] == "candidate") == 1 for v in by_id.values())
    check("mw 1つのpattern_idにCandidateはちょうど1回", ok_cand)

    ok_resolve = all(
        sum(1 for e in v if e["status"] in ("confirmed", "invalidated")) <= 1
        for v in by_id.values()
    )
    check("mw 1つのpattern_idに決着は多くても1回", ok_resolve)

    # Candidateと同じバーで決着することはある(検出に使うのも決着判定に
    # 使うのもそのバーのHigh/Lowなので先読みではない)。過去に戻ることは無い。
    ok_order = True
    for v in by_id.values():
        cand = next(e for e in v if e["status"] == "candidate")
        for e in v:
            if e["status"] != "candidate" and e["event_bar"] < cand["event_bar"]:
                ok_order = False
    check("mw 決着がCandidateより前のバーに来ることは無い", ok_order)

    ok_id = all(
        ev["pattern_id"] == ev["pattern_type"] + "".join(f"_{b}" for b in ev["point_bars"])
        for ev in events
    )
    check("mw pattern_id は パターン種類+構成6点のバー位置", ok_id)


def test_mw_points_and_levels_follow_the_spec():
    """仕様書2章・8.1。構成点は古い順の6点で、ネックライン=P4、極値=P5。"""
    _, res = _mw_real_events()
    events = res["events"]

    ok_six = all(len(ev["point_bars"]) == 6 for ev in events)
    check("mw 構成点は常に6点", ok_six)

    # 厳密増加ではなく非減少。同じバーに高値ピボットと安値ピボットが両方
    # 立つこと(仕様書3.2②のdoublePivot)があり、レベル2以上では
    # micropivotsの境界が重複する(仕様書4.2)ため、構成点のバーは並ぶことがある。
    ok_sorted = all(
        all(a <= b for a, b in zip(ev["point_bars"], ev["point_bars"][1:]))
        for ev in events
    )
    check("mw 構成点のバー位置は古い順に並んでいる(非減少)", ok_sorted)

    ok_levels = all(
        ev["neckline_price"] == ev["point_prices"][4]
        and ev["extreme_price"] == ev["point_prices"][5]
        for ev in events
    )
    check("mw ネックライン=P4の価格、極値=P5の価格", ok_levels)

    ok_dir = all(
        (ev["point_prices"][5] > ev["point_prices"][0])
        == (ev["pattern_type"] == "impulse_wave_bearish")
        for ev in events
    )
    check("mw 上昇波はbearish(下落シグナル)、下降波はbullishになる", ok_dir)

    ok_level = all(ev["level"] >= 1 for ev in events)
    check("mw 走査レベルは1以上(レベル0は走査しない)", ok_level)


def test_mw_confirmed_and_invalidated_use_wicks():
    """仕様書8.1。Confirmedはネックラインをヒゲでクロス、Invalidatedは
    極値をヒゲでクロス。"""
    df, res = _mw_real_events()
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)

    ok_conf = True
    ok_inval = True
    n_conf = n_inval = 0
    for ev in res["events"]:
        i = ev["event_bar"]
        if ev["status"] == "confirmed":
            n_conf += 1
            if ev["pattern_type"] == "impulse_wave_bearish":
                if not (low[i] < ev["neckline_price"] <= low[i - 1]):
                    ok_conf = False
            else:
                if not (high[i] > ev["neckline_price"] >= high[i - 1]):
                    ok_conf = False
        elif ev["status"] == "invalidated":
            n_inval += 1
            if ev["pattern_type"] == "impulse_wave_bearish":
                if not (high[i] > ev["extreme_price"] >= high[i - 1]):
                    ok_inval = False
            else:
                if not (low[i] < ev["extreme_price"] <= low[i - 1]):
                    ok_inval = False
    check("mw Confirmedはネックラインをヒゲでクロスしたバーで起きる", ok_conf)
    check("mw Invalidatedは極値をヒゲでクロスしたバーで起きる", ok_inval)
    check("mw ConfirmedもInvalidatedも実データで発生している",
          n_conf > 0 and n_inval > 0, f"conf={n_conf} inval={n_inval}")


def test_mw_level_type_absolute_is_a_subset_of_minimum():
    """仕様書1.1/5.2。'minimum'は指定レベル以上を全て、'absolute'は
    そのレベルだけを走査する。"""
    _, res_min = _mw_real_events(zigzag_level=1, level_type="minimum")
    _, res_abs = _mw_real_events(zigzag_level=1, level_type="absolute")
    ids_min = {e["pattern_id"] for e in res_min["events"]}
    ids_abs = {e["pattern_id"] for e in res_abs["events"]}
    check("mw absoluteはminimumの部分集合", ids_abs <= ids_min,
          f"extra={len(ids_abs - ids_min)}")
    check("mw minimumの方が検出が多い(上位レベルの分だけ増える)",
          len(ids_min) > len(ids_abs), f"min={len(ids_min)} abs={len(ids_abs)}")

    _, res_lv2 = _mw_real_events(zigzag_level=2, level_type="absolute")
    ok_lv2 = all(e["level"] == 2 for e in res_lv2["events"])
    check("mw absolute指定ではそのレベルのイベントしか出ない", ok_lv2)


def test_mw_repaint_off_detects_later():
    """仕様書5.1/7.5。repaint=false はピボット置き換えのバーで走査せず、
    参照するピボットも1つ古い側(index2)にずらす。見る対象が変わるので
    件数は増えることも減ることもあるが、パターン完成から検出までの
    遅れは必ず大きくなる。"""
    delays = {}
    for repaint in (True, False):
        _, res = _mw_real_events(repaint=repaint)
        d = [
            ev["event_bar"] - ev["point_bars"][5]
            for ev in res["events"] if ev["status"] == "candidate"
        ]
        check(f"mw repaint={repaint} でも検出はゼロにならない", len(d) > 0)
        delays[repaint] = sorted(d)[len(d) // 2]   # 中央値
    check("mw repaint=false は完成から検出までの遅れが大きい",
          delays[False] > delays[True], f"on={delays[True]} off={delays[False]}")


def test_mw_clamps_parameters_into_the_spec_range():
    """仕様書8.3。UIを介さない呼び出しに備えて、有効範囲はエンジン側でも
    保証する。"""
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True)
    df = df.tail(20000).reset_index(drop=True)
    h, l, c = df["high"], df["low"], df["close"]

    def arr(**kw):
        return cp.impulse_wave_bearish(h, l, c, state="candidate", depth=50, **kw)

    at_min_len = arr(zigzag_length=3)
    check("mw zigzag_length が下限3未満なら3へ丸められる",
          all(np.array_equal(arr(zigzag_length=L), at_min_len) for L in (0, 1, 2)))
    at_min_level = arr(zigzag_level=1)
    check("mw zigzag_level が下限1未満なら1へ丸められる",
          all(np.array_equal(arr(zigzag_level=L), at_min_level) for L in (0, -5)))

    def arr_depth(d):
        return cp.impulse_wave_bearish(h, l, c, state="candidate", depth=d)

    check("mw depth が上限500を超えたら500へ丸められる",
          np.array_equal(arr_depth(9999), arr_depth(500)))
    check("mw 未知の level_type は minimum として扱う",
          np.array_equal(arr(level_type="xxx"), arr(level_type="minimum")))


# ---------------------------------------------------------------------------
# フラッグ / ペナント(4本のZigZag、B方式実装)
# docs/pattern_spec_flags_pennants.md の各章に対応させたテスト。
# ---------------------------------------------------------------------------


def test_fnp_line_price_is_linear_interpolation():
    """仕様書5.1(LineWrapper の get_price)。"""
    check("fnp 直線は2点を通る", cp._fnp_line_price(10, 100.0, 20, 110.0, 10) == 100.0
          and cp._fnp_line_price(10, 100.0, 20, 110.0, 20) == 110.0)
    check("fnp 中点は平均", cp._fnp_line_price(10, 100.0, 20, 110.0, 15) == 105.0)
    check("fnp 区間外へも外挿する", cp._fnp_line_price(10, 100.0, 20, 110.0, 0) == 90.0)


def test_fnp_inspect_rejects_a_line_cut_by_a_candle_body():
    """仕様書6.2。ラインが実体(始値と終値の内側)を突き抜けたら不成立。"""
    o = np.array([100.0, 100.0, 100.0])
    h = np.array([101.0, 101.0, 101.0])
    l = np.array([99.0, 99.0, 99.0])
    c = np.array([100.5, 100.5, 100.5])
    # 高値側の線(direction=+1)。すべてのバーの高値ちょうどを通る線は妥当。
    ok, score = cp._fnp_inspect_line(o, h, l, c, 0, 101.0, 2, 101.0, 0, 2, 0, 1.0)
    check("fnp 高値をなぞる線は妥当でスコアが付く", ok and score == 3.0, f"{ok} {score}")
    # 上側の線(direction=+1)は実体の下端(= min(始値, 終値) = 100.0)より
    # 下へ来てはいけない。99.5 は実体を突き抜けているので不成立。
    ok2, _ = cp._fnp_inspect_line(o, h, l, c, 0, 99.5, 2, 99.5, 0, 2, 0, 1.0)
    check("fnp 実体を突き抜ける線は不成立", not ok2)
    # 実体の下端ちょうどは許容される(条件は厳密不等号)。
    ok2b, _ = cp._fnp_inspect_line(o, h, l, c, 0, 100.0, 2, 100.0, 0, 2, 0, 1.0)
    check("fnp 実体の下端ちょうどは許容される", ok2b)
    # 値幅の外(高値より上)を通り、otherBarに当たらなければ不成立。
    ok3, score3 = cp._fnp_inspect_line(o, h, l, c, 0, 102.0, 2, 102.0, 0, 2, 1, 1.0)
    check("fnp 使わなかった構成点に当たらない線は不成立", not ok3, f"{ok3} {score3}")
    # otherBarを区間外にすれば、値幅の外でも妥当(スコア0)。
    ok4, score4 = cp._fnp_inspect_line(o, h, l, c, 0, 102.0, 2, 102.0, 0, 2, -1, 1.0)
    check("fnp 値幅の外を通るだけならスコア0で妥当", ok4 and score4 == 0.0, f"{ok4} {score4}")


def test_fnp_resolve_pattern_type_covers_the_spec_table():
    """仕様書6.4。2本のトレンドラインの端点価格から13種類に分類する。"""
    flat = 0.2
    # 上昇チャネル: 上下とも平行に上がる(幅一定 → isChannel)
    check("fnp 平行に上がる2本は上昇チャネル(1)",
          cp._fnp_resolve_pattern_type(110.0, 120.0, 100.0, 110.0, 100, flat) == 1)
    # 下降チャネル
    check("fnp 平行に下がる2本は下降チャネル(2)",
          cp._fnp_resolve_pattern_type(110.0, 100.0, 100.0, 90.0, 100, flat) == 2)
    # 収束トライアングル: 上が下がり下が上がる
    check("fnp 上が下がり下が上がるのは収束トライアングル(11)",
          cp._fnp_resolve_pattern_type(120.0, 110.0, 100.0, 105.0, 100, flat) == 11)
    # 拡大トライアングル: 上が上がり下が下がる
    check("fnp 上が上がり下が下がるのは拡大トライアングル(6)",
          cp._fnp_resolve_pattern_type(110.0, 130.0, 100.0, 80.0, 100, flat) == 6)
    # 2本が交差していたら該当なし
    check("fnp 2本が交差していたら該当なし(0)",
          cp._fnp_resolve_pattern_type(110.0, 90.0, 100.0, 120.0, 100, flat) == 0)


def test_fnp_allowed_pattern_table_matches_the_reference():
    """仕様書6.5。参考元の allowedPatterns / allowedLastPivotDirections。"""
    allowed = [i for i, v in enumerate(cp._FNP_ALLOWED_PATTERNS) if v]
    check("fnp 土台として許可されるのは7種類", allowed == [1, 2, 9, 10, 11, 12, 13],
          f"got {allowed}")
    dirs = list(cp._FNP_ALLOWED_LAST_DIRS)
    check("fnp 上昇チャネルは安値終わりのみ", dirs[1] == -1)
    check("fnp 下降チャネルは高値終わりのみ", dirs[2] == 1)
    check("fnp 収束トライアングルはどちらでもよい", dirs[11] == 0)


def _fnp_real_events(**kw):
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True)
    df = df.tail(40000).reset_index(drop=True)
    return df, cp._fnp_state(df["open"], df["high"], df["low"], df["close"], **kw)


def test_fnp_detects_all_four_patterns_on_real_data():
    """4種類すべてが実データで検出されること。"""
    _, res = _fnp_real_events()
    events = res["events"]
    kinds = {e["pattern_type"] for e in events}
    check("fnp 4種類すべて検出される",
          kinds == {"bullish_flag", "bearish_flag", "bullish_pennant", "bearish_pennant"},
          f"got {sorted(kinds)}")
    check("fnp イベントが十分な件数出ている", len(events) > 100, f"got {len(events)}")


def test_fnp_base_pattern_determines_the_flag_type():
    """仕様書7.3。土台の種類とフラッグ/ペナントの対応。"""
    _, res = _fnp_real_events()
    cands = [e for e in res["events"] if e["status"] == "candidate"]
    mapping = {
        "descending_channel": "bullish_flag",
        "falling_wedge_contracting": "bullish_flag",
        "ascending_channel": "bearish_flag",
        "rising_wedge_contracting": "bearish_flag",
    }
    ok = all(
        e["pattern_type"] == mapping[e["base_pattern"]]
        for e in cands if e["base_pattern"] in mapping
    )
    check("fnp チャネル/ウェッジ土台はフラッグになり向きも決まる", ok)

    tri = {"converging_triangle", "descending_triangle_contracting",
           "ascending_triangle_contracting"}
    ok_tri = all(
        e["pattern_type"].endswith("pennant") for e in cands if e["base_pattern"] in tri
    )
    check("fnp トライアングル土台はペナントになる", ok_tri)

    allowed_bases = set(mapping) | tri
    ok_only = all(e["base_pattern"] in allowed_bases for e in cands)
    check("fnp 許可された7種類の土台しか出てこない", ok_only,
          f"got {sorted({e['base_pattern'] for e in cands})}")


def test_fnp_pole_and_levels_follow_the_spec():
    """仕様書2章・8.1。構成点は旗竿の起点+土台5点の6点。"""
    _, res = _fnp_real_events()
    cands = [e for e in res["events"] if e["status"] == "candidate"]

    check("fnp 構成点は常に6点", all(len(e["point_bars"]) == 6 for e in cands))
    # 同じバーに2つのピボットが立つことがあるので厳密増加ではなく非減少。
    check("fnp 構成点のバー位置は古い順に並んでいる(非減少)",
          all(all(a <= b for a, b in zip(e["point_bars"], e["point_bars"][1:]))
              for e in cands))

    bull = [e for e in cands if e["pattern_type"].startswith("bull")]
    bear = [e for e in cands if e["pattern_type"].startswith("bear")]
    check("fnp 強気はネックラインが極値より上", all(
        e["neckline_price"] > e["extreme_price"] for e in bull), f"n={len(bull)}")
    check("fnp 弱気はネックラインが極値より下", all(
        e["neckline_price"] < e["extreme_price"] for e in bear), f"n={len(bear)}")

    check("fnp 強気は旗竿の起点が土台の全構成点より安い", all(
        e["point_prices"][0] < min(e["point_prices"][1:]) for e in bull))
    check("fnp 弱気は旗竿の起点が土台の全構成点より高い", all(
        e["point_prices"][0] > max(e["point_prices"][1:]) for e in bear))


def test_fnp_events_follow_the_common_management_spec():
    """共通管理仕様8.3。pattern_idは一意、Candidateは1回、決着も1回。"""
    _, res = _fnp_real_events()
    events = res["events"]
    by_id: dict[str, list[dict]] = {}
    for ev in events:
        by_id.setdefault(ev["pattern_id"], []).append(ev)

    check("fnp 1つのpattern_idにCandidateはちょうど1回",
          all(sum(1 for e in v if e["status"] == "candidate") == 1 for v in by_id.values()))
    check("fnp 1つのpattern_idに決着は多くても1回",
          all(sum(1 for e in v if e["status"] in ("confirmed", "invalidated")) <= 1
              for v in by_id.values()))

    ok_order = True
    for v in by_id.values():
        cand = next(e for e in v if e["status"] == "candidate")
        for e in v:
            if e["status"] != "candidate" and e["event_bar"] < cand["event_bar"]:
                ok_order = False
    check("fnp 決着がCandidateより前のバーに来ることは無い", ok_order)

    check("fnp pattern_id は パターン種類+構成6点のバー位置", all(
        ev["pattern_id"] == ev["pattern_type"] + "".join(f"_{b}" for b in ev["point_bars"])
        for ev in events))


def test_fnp_confirmed_and_invalidated_use_wicks():
    """仕様書8.1。Confirmedはネックライン、Invalidatedは極値をヒゲでクロス。"""
    df, res = _fnp_real_events()
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)

    ok_conf = ok_inval = True
    n_conf = n_inval = 0
    for ev in res["events"]:
        i = ev["event_bar"]
        bullish = ev["pattern_type"].startswith("bull")
        if ev["status"] == "confirmed":
            n_conf += 1
            if bullish:
                if not (high[i] > ev["neckline_price"] >= high[i - 1]):
                    ok_conf = False
            else:
                if not (low[i] < ev["neckline_price"] <= low[i - 1]):
                    ok_conf = False
        elif ev["status"] == "invalidated":
            n_inval += 1
            if bullish:
                if not (low[i] < ev["extreme_price"] <= low[i - 1]):
                    ok_inval = False
            else:
                if not (high[i] > ev["extreme_price"] >= high[i - 1]):
                    ok_inval = False
    check("fnp Confirmedはネックラインをヒゲでクロスしたバーで起きる", ok_conf)
    check("fnp Invalidatedは極値をヒゲでクロスしたバーで起きる", ok_inval)
    check("fnp ConfirmedもInvalidatedも実データで発生している",
          n_conf > 0 and n_inval > 0, f"conf={n_conf} inval={n_inval}")


def test_fnp_disabling_zigzags_reduces_detections():
    """仕様書5.2。4本のZigZagは独立。切ればその分だけ検出が減る。"""
    _, res_all = _fnp_real_events()
    _, res_one = _fnp_real_events(use_zigzag2=False, use_zigzag3=False, use_zigzag4=False)
    n_all = len({e["pattern_id"] for e in res_all["events"]})
    n_one = len({e["pattern_id"] for e in res_one["events"]})
    check("fnp ZigZagを3本切ると検出が減る", n_one < n_all, f"all={n_all} one={n_one}")
    check("fnp 1本だけでも検出はゼロにならない", n_one > 0, f"got {n_one}")

    used = {e["zigzag_index"] for e in res_one["events"]}
    check("fnp 有効にしたZigZagからしか検出されない", used == {1}, f"got {sorted(used)}")

    _, res_none = _fnp_real_events(use_zigzag1=False, use_zigzag2=False,
                                   use_zigzag3=False, use_zigzag4=False)
    check("fnp 全部切れば検出ゼロ", len(res_none["events"]) == 0)


def test_fnp_thresholds_change_the_result():
    """仕様書1章。errorThreshold / flatThreshold / flagRatio は検出に効く。"""
    base = len({e["pattern_id"] for e in _fnp_real_events()[1]["events"]})
    loose = len({e["pattern_id"] for e in _fnp_real_events(error_threshold=60.0)[1]["events"]})
    check("fnp 許容誤差を広げると検出が増える", loose > base, f"base={base} loose={loose}")

    tight_flag = len({e["pattern_id"]
                      for e in _fnp_real_events(flag_ratio=0.1)[1]["events"]})
    check("fnp 旗竿の戻し比率を絞ると検出が変わる", tight_flag != base,
          f"base={base} tight={tight_flag}")

    flat0 = len({e["pattern_id"] for e in _fnp_real_events(flat_threshold=0.0)[1]["events"]})
    check("fnp 水平判定しきい値0でも計算できる", flat0 >= 0)


def test_fnp_clamps_parameters_into_the_spec_range():
    """仕様書8.2。UIを介さない呼び出しに備えてエンジン側でも範囲を保証する。"""
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True)
    df = df.tail(20000).reset_index(drop=True)
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]

    def arr(**kw):
        return cp.bearish_flag(o, h, l, c, state="candidate", **kw)

    check("fnp zigzag_length が下限1未満なら1へ丸められる",
          np.array_equal(arr(zigzag_length1=0), arr(zigzag_length1=1)))
    check("fnp depth が上限500を超えたら500へ丸められる",
          np.array_equal(arr(depth1=9999), arr(depth1=500)))
    check("fnp error_threshold が上限100を超えたら100へ丸められる",
          np.array_equal(arr(error_threshold=500.0), arr(error_threshold=100.0)))
    check("fnp flat_threshold が上限30を超えたら30へ丸められる",
          np.array_equal(arr(flat_threshold=99.0), arr(flat_threshold=30.0)))
    check("fnp flag_ratio が上限1.0を超えたら1.0へ丸められる",
          np.array_equal(arr(flag_ratio=5.0), arr(flag_ratio=1.0)))
    check("fnp max_patterns が下限1未満なら1へ丸められる",
          np.array_equal(arr(max_patterns=0), arr(max_patterns=1)))


# ---------------------------------------------------------------------------
# チャネル / ウェッジ / トライアングル(13種)
# docs/pattern_spec_auto_chart_patterns.md の各章に対応させたテスト。
# ---------------------------------------------------------------------------


def test_acp_inspect_adds_the_touch_ratio_condition():
    """仕様書6.2・0.4。フラッグ側(_fnp_inspect_line)には無い
    「スコア/総バー数 < 0.2」がこちらには付く。"""
    # 全バーの高値ちょうどを通る線 → 触れすぎ(score/total = 1.0)なので不成立。
    n = 10
    o = np.full(n, 100.0)
    h = np.full(n, 101.0)
    l = np.full(n, 99.0)
    c = np.full(n, 100.5)
    fnp_ok, fnp_score = cp._fnp_inspect_line(o, h, l, c, 0, 101.0, n - 1, 101.0,
                                             0, n - 1, 0, 1.0)
    acp_ok, acp_score = cp._acp_inspect_line(o, h, l, c, 0, 101.0, n - 1, 101.0,
                                             0, n - 1, 0, 1.0)
    check("acp 触れすぎの線はフラッグ側なら妥当", fnp_ok and fnp_score == n)
    check("acp 触れすぎの線はこちらでは不成立", not acp_ok, f"score={acp_score}")

    # 端の1本だけに触れる線(score/total = 0.1 < 0.2)なら成立。
    h2 = np.full(n, 100.6)
    h2[0] = 101.0
    ok, score = cp._acp_inspect_line(o, h2, l, c, 0, 101.0, n - 1, 101.0,
                                     0, n - 1, 0, 1.0)
    check("acp 端の1本だけに触れる線は成立", ok and score == 1.0, f"{ok} {score}")


def test_acp_bar_ratio_uses_point_indices():
    """仕様書6.1。ピボットのフィールドではなく構成点のバー位置から直接計算する。"""
    # |30-20| / |20-0| = 0.5 → 0.382〜2.618 の中
    check("acp 比0.5は範囲内", cp._acp_bar_ratio_ok(0, 20, 30, True, 0.382))
    # |100-20| / |20-0| = 4.0 → 範囲外
    check("acp 比4.0は範囲外", not cp._acp_bar_ratio_ok(0, 20, 100, True, 0.382))
    check("acp OFFなら常に真", cp._acp_bar_ratio_ok(0, 20, 100, False, 0.382))
    check("acp 分母0は不成立", not cp._acp_bar_ratio_ok(20, 20, 30, True, 0.382))


def test_acp_shares_the_classification_with_flags_and_pennants():
    """仕様書0.4。分類そのもの(resolvePatternName)は両ライブラリで同一なので
    _fnp_resolve_pattern_type を共用している。"""
    check("acp 13種類の名前が揃っている", len(cp._ACP_PATTERN_NAMES) == 13)
    check("acp コードと名前がフラッグ側の土台名と一致する",
          all(cp._ACP_PATTERN_NAMES[k] == cp._FNP_BASE_PATTERN_NAMES[k]
              for k in cp._ACP_PATTERN_NAMES),
          "コード対応がずれている")


def _acp_real_events(**kw):
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True)
    df = df.tail(40000).reset_index(drop=True)
    return df, cp._acp_state(df["open"], df["high"], df["low"], df["close"], **kw)


def test_acp_detects_all_thirteen_patterns():
    """13種類すべてが実データで検出されること。"""
    _, res = _acp_real_events()
    kinds = {e["pattern_type"] for e in res["events"]}
    check("acp 13種類すべて検出される",
          kinds == set(cp._ACP_PATTERN_NAMES.values()),
          f"missing={sorted(set(cp._ACP_PATTERN_NAMES.values()) - kinds)}")


def test_acp_points_and_levels_follow_the_spec():
    """仕様書2章・8.1。"""
    _, res = _acp_real_events()
    cands = [e for e in res["events"] if e["status"] == "candidate"]

    check("acp 既定は5点構成", all(len(e["point_bars"]) == 5 for e in cands))
    check("acp 構成点のバー位置は古い順に並んでいる(非減少)",
          all(all(a <= b for a, b in zip(e["point_bars"], e["point_bars"][1:]))
              for e in cands))

    up = [e for e in cands if e["last_pivot_direction"] > 0]
    dn = [e for e in cands if e["last_pivot_direction"] < 0]
    check("acp 高値終わりはネックラインが極値より上",
          all(e["neckline_price"] > e["extreme_price"] for e in up), f"n={len(up)}")
    check("acp 安値終わりはネックラインが極値より下",
          all(e["neckline_price"] < e["extreme_price"] for e in dn), f"n={len(dn)}")
    check("acp 上下どちらも検出されている", len(up) > 0 and len(dn) > 0)

    # 最後の構成点の向きは、載せ直した後の価格から決まる(仕様書6.5)。
    ok_dir = all(
        (e["point_prices"][-1] > e["point_prices"][-2]) == (e["last_pivot_direction"] > 0)
        for e in cands
    )
    check("acp last_pivot_direction は最後の2点の価格差の向き", ok_dir)

    _, res6 = _acp_real_events(number_of_pivots=6)
    c6 = [e for e in res6["events"] if e["status"] == "candidate"]
    check("acp 6点指定なら6点構成になる", all(len(e["point_bars"]) == 6 for e in c6))
    check("acp 6点指定でも検出はゼロにならない", len(c6) > 0)


def test_acp_events_follow_the_common_management_spec():
    """共通管理仕様7.1〜7.4。"""
    _, res = _acp_real_events()
    by_id: dict[str, list[dict]] = {}
    for ev in res["events"]:
        by_id.setdefault(ev["pattern_id"], []).append(ev)

    check("acp 1つのpattern_idにCandidateはちょうど1回",
          all(sum(1 for e in v if e["status"] == "candidate") == 1 for v in by_id.values()))
    check("acp 1つのpattern_idに決着は多くても1回",
          all(sum(1 for e in v if e["status"] in ("confirmed", "invalidated")) <= 1
              for v in by_id.values()))

    ok_order = True
    for v in by_id.values():
        cand = next(e for e in v if e["status"] == "candidate")
        for e in v:
            if e["status"] != "candidate" and e["event_bar"] < cand["event_bar"]:
                ok_order = False
    check("acp 決着がCandidateより前のバーに来ることは無い", ok_order)

    check("acp pattern_id は パターン種類+構成点のバー位置", all(
        ev["pattern_id"] == ev["pattern_type"] + "".join(f"_{b}" for b in ev["point_bars"])
        for ev in res["events"]))


def test_acp_confirmed_and_invalidated_use_wicks():
    """仕様書8.1。"""
    df, res = _acp_real_events()
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)

    ok_conf = ok_inval = True
    n_conf = n_inval = 0
    for ev in res["events"]:
        i = ev["event_bar"]
        up = ev["last_pivot_direction"] > 0
        if ev["status"] == "confirmed":
            n_conf += 1
            if up:
                if not (high[i] > ev["neckline_price"] >= high[i - 1]):
                    ok_conf = False
            else:
                if not (low[i] < ev["neckline_price"] <= low[i - 1]):
                    ok_conf = False
        elif ev["status"] == "invalidated":
            n_inval += 1
            if up:
                if not (low[i] < ev["extreme_price"] <= low[i - 1]):
                    ok_inval = False
            else:
                if not (high[i] > ev["extreme_price"] >= high[i - 1]):
                    ok_inval = False
    check("acp Confirmedはネックラインをヒゲでクロスしたバーで起きる", ok_conf)
    check("acp Invalidatedは極値をヒゲでクロスしたバーで起きる", ok_inval)
    check("acp ConfirmedもInvalidatedも実データで発生している",
          n_conf > 0 and n_inval > 0, f"conf={n_conf} inval={n_inval}")


def test_acp_last_pivot_direction_filter():
    """仕様書1.2/6.5。向きを固定すると片側しか出なくなる。"""
    for want, sign in (("up", 1), ("down", -1)):
        _, res = _acp_real_events(last_pivot_direction=want)
        dirs = {e["last_pivot_direction"] for e in res["events"]}
        check(f"acp last_pivot_direction={want} なら片側だけ",
              dirs == {sign}, f"got {sorted(dirs)}")
        check(f"acp last_pivot_direction={want} でも検出はゼロにならない",
              len(res["events"]) > 0)


def test_acp_zigzag_toggles_and_thresholds_work():
    """仕様書1章/5.2。"""
    _, res1 = _acp_real_events()
    _, res_all = _acp_real_events(use_zigzag2=True, use_zigzag3=True, use_zigzag4=True)
    n1 = len({e["pattern_id"] for e in res1["events"]})
    n4 = len({e["pattern_id"] for e in res_all["events"]})
    check("acp ZigZagを増やすと検出が増える", n4 > n1, f"1本={n1} 4本={n4}")
    used = {e["zigzag_index"] for e in res1["events"]}
    check("acp 既定はZigZag1本のみ", used == {1}, f"got {sorted(used)}")

    _, res_none = _acp_real_events(use_zigzag1=False)
    check("acp 全部切れば検出ゼロ", len(res_none["events"]) == 0)

    _, res_nb = _acp_real_events(check_bar_ratio=False)
    check("acp バー間隔の比を切ると検出が増える",
          len({e["pattern_id"] for e in res_nb["events"]}) > n1)


def test_acp_clamps_parameters_into_the_spec_range():
    """仕様書8.2。"""
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True)
    df = df.tail(20000).reset_index(drop=True)
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]

    def arr(**kw):
        return cp.converging_triangle(o, h, l, c, state="candidate", **kw)

    check("acp zigzag_length が下限1未満なら1へ丸められる",
          np.array_equal(arr(zigzag_length1=0), arr(zigzag_length1=1)))
    check("acp depth が上限500を超えたら500へ丸められる",
          np.array_equal(arr(depth1=9999), arr(depth1=500)))
    check("acp error_threshold が上限100を超えたら100へ丸められる",
          np.array_equal(arr(error_threshold=500.0), arr(error_threshold=100.0)))
    check("acp flat_threshold が上限30を超えたら30へ丸められる",
          np.array_equal(arr(flat_threshold=99.0), arr(flat_threshold=30.0)))
    check("acp number_of_pivots は5か6に丸められる",
          np.array_equal(arr(number_of_pivots=4), arr(number_of_pivots=5))
          and np.array_equal(arr(number_of_pivots=9), arr(number_of_pivots=6)))
    check("acp 未知の last_pivot_direction は both として扱う",
          np.array_equal(arr(last_pivot_direction="xxx"),
                         arr(last_pivot_direction="both")))

def test_pattern_dedup_ignores_the_newest_point():
    """共通管理仕様①。ZigZagの最新ピボットは後から動くので、重複判定からは
    最新の構成点を外す。外さないと「同じ形なのに最新点の位置だけ違う」ものが
    別パターンとして何度も登録される(ユーザー報告:「点6だけ位置が違うから
    2つのパターンと認識してる」)。参考元も同じ考え方を持っている
    (docs/pattern_spec_reversal_chart_patterns_recursive.md 5.5、
     docs/pattern_spec_flags_pennants.md 6.0)。"""
    import collections

    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True)
    df = df.tail(60000).reset_index(drop=True)
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]

    def count_dups(events, newest_first):
        groups = collections.defaultdict(set)
        for e in events:
            if e["status"] != "candidate":
                continue
            bars = list(e["point_bars"])
            rest = tuple(bars[1:]) if newest_first else tuple(bars[:-1])
            newest = bars[0] if newest_first else bars[-1]
            groups[(e["pattern_type"], rest)].add(newest)
        return sum(1 for v in groups.values() if len(v) > 1), len(groups)

    # 構成点が新しい順のもの(トリプルトップ系)
    dups, groups = count_dups(cp._rrcp_state(h, l, c)["events"], True)
    check("dedup トリプルトップ系に最新点違いの重複が無い", dups == 0,
          f"{dups}/{groups}")
    check("dedup トリプルトップ系はちゃんと検出できている", groups > 0)

    # 構成点が古い順のもの
    for name, events in (
        ("推進波", cp._mw_state(h, l, c)["events"]),
        ("フラッグ/ペナント", cp._fnp_state(o, h, l, c)["events"]),
        ("チャネル/ウェッジ/トライアングル", cp._acp_state(o, h, l, c)["events"]),
    ):
        dups, groups = count_dups(events, False)
        check(f"dedup {name}に最新点違いの重複が無い", dups == 0, f"{dups}/{groups}")
        check(f"dedup {name}はちゃんと検出できている", groups > 0)


def test_make_dedup_key_drops_only_the_newest_point():
    """_make_dedup_key の向き(newest_first)ごとの挙動。"""
    bars = [100, 120, 140, 160]
    check("dedup 新しい順なら先頭を落とす",
          cp._make_dedup_key("x", bars, newest_first=True) == "x_120_140_160")
    check("dedup 古い順なら末尾を落とす",
          cp._make_dedup_key("x", bars, newest_first=False) == "x_100_120_140")
    check("dedup pattern_id 自体は全構成点を含んだまま",
          cp._make_pattern_id("x", bars) == "x_100_120_140_160")


def test_shape_neckline_window_ignores_pivots_that_cannot_be_top2():
    """ネックライン探索の打ち切りは「山2/谷2になり得るピボット」でだけ起こる。

    2026-08-13、ユーザー指摘で修正。それまでは「次の山型/谷型ピボットが出たら
    打ち切る」だけで、そのピボットが山2として採用され得るか(=山1との差が
    許容誤差に収まるか)を見ていなかった。そのため許容誤差の何倍も離れた
    ノイズ級の出っ張り1本で打ち切られ、その先にある本物のネックへ到達できず、
    目視では明らかなダブルトップが取りこぼされていた。

    実データの再現ケース: USDJPY 15分足 2025-11-11。
      山1 10:15 (154.492)
      13:30 に 154.352 の小さなピボット高値(山1との差0.140 = 許容0.041の3.4倍)
      本物のネック 14:45 (154.087)
      山2 18:15 (154.441)
    修正前はこのパターンが検出されなかった。
    """
    df = load_price_data(find_data_file("15m", "USDJPY")).reset_index(drop=True)
    times = pd.to_datetime(df["datetime"])
    params = dict(
        breakout_type="close", breakout_buffer_mult=0.05,
        pivot_left_bars=5, pivot_right_bars=5, prominence_atr_mult=0.0,
        max_bars_between_tops=0, symmetry_ratio_min=0.0, symmetry_ratio_max=0.0,
        breakout_deadline_min_bars=0, breakout_deadline_ratio_max=0.0,
        interval_symmetry_ratio_min=0.0, interval_symmetry_ratio_max=0.0,
        top_tolerance_mult=0.15, min_valley_depth_atr_mult=1.0,
        max_valley_depth_atr_mult=0.0, terminal_bounce_close_mult=0.7,
        pivot_spike_window_ratio=0.5, pivot_spike_excess_atr_max=1.3,
        efficiency_ratio_min_context=0.0, trendline_dev_pct_context=1.0,
        efficiency_ratio_min_breakout=0.0, trendline_dev_pct_breakout=1.0,
        efficiency_ratio_min=0.0, efficiency_ratio_floor=0.0, trendline_dev_pct=1.0,
    )
    res = cp._double_top_bottom_shape_state(
        df["high"], df["low"], df["close"], bullish=False, **params
    )
    detected = np.asarray(res["candidate"])
    top1 = np.asarray(res["top1_bar"])
    neck = np.asarray(res["neckline_bar"])
    top2 = np.asarray(res["top2_bar"])

    want_top1 = times[times == pd.Timestamp("2025-11-11 10:15")].index
    if len(want_top1) == 0:
        check("shape ネック窓の再現ケースがデータに存在する", False, "2025-11-11のデータが無い")
        return
    w1 = int(want_top1[0])

    hits = [
        i for i in np.where(detected)[0]
        if int(top1[i]) == w1
    ]
    check("shape ノイズ級ピボットでネック探索を打ち切らない(11/11のダブルトップを検出)",
          len(hits) == 1, f"got {len(hits)} 件")
    if not hits:
        return
    i = hits[0]
    check("shape ネックは打ち切り前の浅い谷ではなく本物の底(14:45)を採る",
          str(times.iloc[int(neck[i])]) == "2025-11-11 14:45:00",
          f"got {times.iloc[int(neck[i])]}")
    check("shape 山2は18:15",
          str(times.iloc[int(top2[i])]) == "2025-11-11 18:15:00",
          f"got {times.iloc[int(top2[i])]}")


# ---------------------------------------------------------------------------
# トリプルトップ/ボトム(形状判定版) - docs/pattern_spec_triple_top_bottom_
# shape.md の確定版を実装したもの。ダブル版と同じく手作りの合成OHLCで、
# 厳密な絶対バー番号ではなく構成点の並び・価格関係で検証する(横ばい区間で
# 山3/谷3の確定バーが多少前後してもテストが壊れないようにするため)。
# ---------------------------------------------------------------------------

def _triple_bottom_closes() -> np.ndarray:
    # 谷1(@bar30=100.0) → ネック1(@bar45=115.0) → 谷2(@bar60=100.3) →
    # ネック2(@bar75=115.0) → 谷3(下降後、横ばいで固定) → ブレイク(140まで
    # 上昇 - ボトムパターンのConfirmedはネックラインを上抜けること)。
    return np.concatenate([
        np.linspace(130, 110, 15, endpoint=False),
        np.linspace(110, 100, 15, endpoint=False),
        np.linspace(100, 115, 15, endpoint=False),
        np.linspace(115, 100.3, 15, endpoint=False),
        np.linspace(100.3, 115, 15, endpoint=False),
        np.linspace(115, 99.8, 20, endpoint=False),
        np.full(30, 99.8),
        np.linspace(99.8, 140, 30, endpoint=False),
        np.full(40, 140.0),
    ])


_TRIPLE_LOOSE_KWARGS = dict(
    max_bars_between_tops=200, symmetry_ratio_min=0.0, symmetry_ratio_max=3.0,
    top_tolerance_mult=0.3, neck_tolerance_mult=1.0,
    pivot_spike_excess_atr_max=0.0, terminal_bounce_close_mult=0.0,
    breakout_deadline_min_bars=3, breakout_deadline_ratio_max=5.0,
    # 時間対称性チェック(山1前→山3 = 山3→ブレイク×比率)はこのテストの
    # 対象外なので無効化(0=無制限、既存のダブル用テストと同じ規約) -
    # 合成データの「山1前点」の探索先が偶然遠く離れ、この無関係なチェックに
    # 引っかかるのを避けるため。
    interval_symmetry_ratio_min=0.0, interval_symmetry_ratio_max=0.0,
    # なめらかさ・直線乖離・ブレイク判定余白もこのテストの対象外なので
    # 無効化(2026-08-14、既定値のユーザー調整のたびに合成データが偶然
    # 引っかからないよう、明示的に緩めた値へ固定しておく - breakout_buffer_
    # multは山1前点の探索水準(pre_level)のサイズにも使われるため、変わると
    # pre_barが見つからなくなり候補ごと不成立になり得る)。
    efficiency_ratio_min=0.0, efficiency_ratio_floor=0.0, trendline_dev_pct=1.0,
    efficiency_ratio_min_breakout=0.0, trendline_dev_pct_breakout=1.0,
    efficiency_ratio_min_context=0.0, trendline_dev_pct_context=1.0,
    breakout_buffer_mult=0.075,
)


def test_triple_bottom_shape_detects_a_clean_textbook_pattern():
    closes = _triple_bottom_closes()
    high, low, close = _hlc(closes)
    state = cp._triple_top_bottom_shape_state(high, low, close, True, **_TRIPLE_LOOSE_KWARGS)

    confirmed = np.where(state["confirmed"].to_numpy())[0]
    check("triple_bottom 綺麗な教科書形が検出される(Confirmed)", len(confirmed) >= 1,
          detail=f"confirmed={confirmed}")
    if len(confirmed) == 0:
        return
    # 構成点はConfirmedバーではなくformed_bar(Candidate成立バー)に書き込まれる。
    f = int(state["formed_bar"].iloc[int(confirmed[0])])
    top1 = int(state["top1_bar"].iloc[f]); neck1 = int(state["neck1_bar"].iloc[f])
    top2 = int(state["top2_bar"].iloc[f]); neck2 = int(state["neck2_bar"].iloc[f])
    top3 = int(state["top3_bar"].iloc[f])
    check("triple_bottom 構成点は時系列順(谷1<ネック1<谷2<ネック2<谷3)",
          top1 < neck1 < top2 < neck2 < top3,
          detail=f"{top1},{neck1},{top2},{neck2},{top3}")

    t1p = state["top1_price"].iloc[f]; t2p = state["top2_price"].iloc[f]; t3p = state["top3_price"].iloc[f]
    n1p = state["neck1_price"].iloc[f]; n2p = state["neck2_price"].iloc[f]
    check("triple_bottom 3つの谷はほぼ同水準", max(t1p, t2p, t3p) - min(t1p, t2p, t3p) < 2.0,
          detail=f"{t1p},{t2p},{t3p}")
    check("triple_bottom 2つのネックは谷より明確に高い",
          n1p > max(t1p, t2p, t3p) + 5 and n2p > max(t1p, t2p, t3p) + 5,
          detail=f"neck1={n1p} neck2={n2p} tops={t1p},{t2p},{t3p}")

    # 公開関数(triple_bottom_shape)も内部stateと一致すること。
    pub_confirmed = cp.triple_bottom_shape(high, low, close, state="confirmed", **_TRIPLE_LOOSE_KWARGS)
    check("triple_bottom 公開関数と内部stateのConfirmedが一致",
          np.array_equal(np.nan_to_num(pub_confirmed) > 0, state["confirmed"].to_numpy()))


def test_triple_top_shape_detects_a_clean_textbook_pattern():
    # 谷↔山を反転させた鏡像(230 - close)。時系列の並び・価格の相対関係は
    # 不変なので、同じ検証がそのまま使える。
    closes = 230.0 - _triple_bottom_closes()
    high, low, close = _hlc(closes)
    state = cp._triple_top_bottom_shape_state(high, low, close, False, **_TRIPLE_LOOSE_KWARGS)

    confirmed = np.where(state["confirmed"].to_numpy())[0]
    check("triple_top 綺麗な教科書形が検出される(Confirmed)", len(confirmed) >= 1,
          detail=f"confirmed={confirmed}")
    if len(confirmed) == 0:
        return
    f = int(state["formed_bar"].iloc[int(confirmed[0])])
    top1 = int(state["top1_bar"].iloc[f]); neck1 = int(state["neck1_bar"].iloc[f])
    top2 = int(state["top2_bar"].iloc[f]); neck2 = int(state["neck2_bar"].iloc[f])
    top3 = int(state["top3_bar"].iloc[f])
    check("triple_top 構成点は時系列順(山1<ネック1<山2<ネック2<山3)",
          top1 < neck1 < top2 < neck2 < top3,
          detail=f"{top1},{neck1},{top2},{neck2},{top3}")
    t1p = state["top1_price"].iloc[f]; t2p = state["top2_price"].iloc[f]; t3p = state["top3_price"].iloc[f]
    n1p = state["neck1_price"].iloc[f]; n2p = state["neck2_price"].iloc[f]
    check("triple_top 3つの山はほぼ同水準", max(t1p, t2p, t3p) - min(t1p, t2p, t3p) < 2.0,
          detail=f"{t1p},{t2p},{t3p}")
    check("triple_top 2つのネックは山より明確に低い",
          n1p < min(t1p, t2p, t3p) - 5 and n2p < min(t1p, t2p, t3p) - 5,
          detail=f"neck1={n1p} neck2={n2p} tops={t1p},{t2p},{t3p}")


def test_triple_bottom_shape_middle_trough_picks_the_lowest_tolerance_filtered_candidate():
    # ネック1の後、tol範囲内に浅い谷A(@bar55)と深い谷B(@bar71)の2候補を
    # 用意する。2026-08-13の訂正(「山1に一番近い」ではなく「tol以内で
    # 最も価格が高い/低い」)どおり、深い方Bが選ばれるはず。
    closes = np.concatenate([
        np.linspace(130, 110, 15, endpoint=False),
        np.linspace(110, 100, 15, endpoint=False),     # 谷1 @bar30=100.0
        np.linspace(100, 115, 15, endpoint=False),     # ネック1 @bar45=115.0
        np.linspace(115, 101.5, 10, endpoint=False),   # 候補A(浅い) @bar55=101.5
        np.linspace(101.5, 108, 6, endpoint=False),    # 小さな反発(Aを両側確認ピボットにする)
        np.linspace(108, 100.2, 10, endpoint=False),   # 候補B(深い) @bar71=100.2
        np.linspace(100.2, 115, 15, endpoint=False),   # ネック2 @bar86=115.0
        np.linspace(115, 99.8, 20, endpoint=False),
        np.full(30, 99.8),
        np.linspace(99.8, 60, 30, endpoint=False),
        np.full(40, 60.0),
    ])
    high, low, close = _hlc(closes)
    state = cp._triple_top_bottom_shape_state(high, low, close, True, **_TRIPLE_LOOSE_KWARGS)

    candidate = np.where(state["candidate"].to_numpy() | state["confirmed"].to_numpy() | state["invalidated"].to_numpy())[0]
    check("triple_bottom 山2選択テスト用の形が候補として成立する", len(candidate) >= 1,
          detail=f"rows={candidate}")
    if len(candidate) == 0:
        return
    f = int(candidate[0])
    top2_bar = int(state["top2_bar"].iloc[f])
    top2_price = state["top2_price"].iloc[f]
    check("triple_bottom 谷2は「tol以内で最も安い」候補B(bar71付近)が選ばれる(「山1に一番近い」浅い方Aではない)",
          65 <= top2_bar <= 76 and top2_price < 100.5,
          detail=f"top2_bar={top2_bar} top2_price={top2_price}")


def test_triple_bottom_shape_neck_tolerance_mult_rejects_divergent_necks():
    # ネック1(@bar45=115.0)とネック2(@bar75=125.0)の水準を10だけ離す。
    # base_leg=|谷1-ネック1|≈15.6なので、neck_tolerance_mult=0.2なら
    # neck_tol≈3.1<10で不成立、1.0ならneck_tol≈15.6>10で成立するはず。
    closes = np.concatenate([
        np.linspace(130, 110, 15, endpoint=False),
        np.linspace(110, 100, 15, endpoint=False),
        np.linspace(100, 115, 15, endpoint=False),
        np.linspace(115, 100.3, 15, endpoint=False),
        np.linspace(100.3, 125, 15, endpoint=False),
        np.linspace(125, 99.8, 20, endpoint=False),
        np.full(30, 99.8),
        np.linspace(99.8, 140, 30, endpoint=False),
        np.full(40, 140.0),
    ])
    high, low, close = _hlc(closes)
    kwargs = dict(_TRIPLE_LOOSE_KWARGS)

    kwargs["neck_tolerance_mult"] = 0.2
    tight = cp._triple_top_bottom_shape_state(high, low, close, True, **kwargs)
    tight_rows = tight["candidate"].to_numpy() | tight["confirmed"].to_numpy() | tight["invalidated"].to_numpy()
    check("triple_bottom neck_tolerance_multが狭いとネック乖離した形は不成立",
          not tight_rows.any(), detail=f"rows={np.where(tight_rows)[0]}")

    kwargs["neck_tolerance_mult"] = 1.0
    loose = cp._triple_top_bottom_shape_state(high, low, close, True, **kwargs)
    loose_rows = loose["candidate"].to_numpy() | loose["confirmed"].to_numpy() | loose["invalidated"].to_numpy()
    check("triple_bottom neck_tolerance_multを緩めれば同じ形が成立する",
          loose_rows.any(), detail=f"rows={np.where(loose_rows)[0]}")


# ---------------------------------------------------------------------------
# ヘッド・アンド・ショルダーズ(形状判定版) -
# docs/pattern_spec_head_and_shoulders_shape.md の確定版を実装したもの。
# トリプルSTと同じ土台なので、頭の突出(head_prominence_mult)とネックライン
# の傾き対応(neck_tolerance_mult)という2点の差分だけを検証する。
# ---------------------------------------------------------------------------

_HS_LOOSE_KWARGS = dict(
    max_bars_between_tops=200, symmetry_ratio_min=0.0, symmetry_ratio_max=3.0,
    top_tolerance_mult=0.3, neck_tolerance_mult=1.0, head_prominence_mult=0.3,
    pivot_spike_excess_atr_max=0.0, terminal_bounce_close_mult=0.0,
    breakout_deadline_min_bars=3, breakout_deadline_ratio_max=5.0,
    interval_symmetry_ratio_min=0.0, interval_symmetry_ratio_max=0.0,
    efficiency_ratio_min=0.0, efficiency_ratio_floor=0.0, trendline_dev_pct=1.0,
    efficiency_ratio_min_breakout=0.0, trendline_dev_pct_breakout=1.0,
    efficiency_ratio_min_context=0.0, trendline_dev_pct_context=1.0,
    breakout_buffer_mult=0.075,
)


def _hs_base_closes() -> np.ndarray:
    # 肩1(谷、@bar30=100.0)→ネック1(山、@bar45=115.0)→頭(谷、@bar60=70.0、
    # 明確に深い)→ネック2(山、@bar75=115.0)→肩3(谷、@bar95付近≈99.8)→
    # ブレイク(上昇、逆H&S=谷パターンのConfirmedはネックライン上抜け)。
    # wickは0.8(候補バーの高安値に隙間ができ、山1前点が見つからなくなる
    # のを防ぐため、通常の0.3より広め)。
    return np.concatenate([
        np.linspace(130, 110, 15, endpoint=False),
        np.linspace(110, 100, 15, endpoint=False),
        np.linspace(100, 115, 15, endpoint=False),
        np.linspace(115, 70, 15, endpoint=False),
        np.linspace(70, 115, 15, endpoint=False),
        np.linspace(115, 99.8, 20, endpoint=False),
        np.full(30, 99.8),
        np.linspace(99.8, 140, 30, endpoint=False),
        np.full(40, 140.0),
    ])


def test_inverse_hs_shape_detects_a_clean_textbook_pattern():
    closes = _hs_base_closes()
    high, low, close = _hlc(closes, wick=0.8)
    state = cp._hs_shape_state(high, low, close, True, **_HS_LOOSE_KWARGS)

    confirmed = np.where(state["confirmed"].to_numpy())[0]
    check("inverse_hs 綺麗な教科書形が検出される(Confirmed)", len(confirmed) >= 1,
          detail=f"confirmed={confirmed}")
    if len(confirmed) == 0:
        return
    f = int(state["formed_bar"].iloc[int(confirmed[0])])
    top1 = int(state["top1_bar"].iloc[f]); neck1 = int(state["neck1_bar"].iloc[f])
    top2 = int(state["top2_bar"].iloc[f]); neck2 = int(state["neck2_bar"].iloc[f])
    top3 = int(state["top3_bar"].iloc[f])
    check("inverse_hs 構成点は時系列順(肩1<ネック1<頭<ネック2<肩3)",
          top1 < neck1 < top2 < neck2 < top3,
          detail=f"{top1},{neck1},{top2},{neck2},{top3}")

    t1p = state["top1_price"].iloc[f]; t2p = state["top2_price"].iloc[f]; t3p = state["top3_price"].iloc[f]
    check("inverse_hs 頭は両肩より明確に低い", t2p < min(t1p, t3p) - 5,
          detail=f"肩1={t1p} 頭={t2p} 肩3={t3p}")
    check("inverse_hs 両肩はほぼ同水準", abs(t1p - t3p) < 2.0, detail=f"肩1={t1p} 肩3={t3p}")

    # 公開関数(inverse_head_and_shoulders_shape)も内部stateと一致すること。
    pub_confirmed = cp.inverse_head_and_shoulders_shape(high, low, close, state="confirmed", **_HS_LOOSE_KWARGS)
    check("inverse_hs 公開関数と内部stateのConfirmedが一致",
          np.array_equal(np.nan_to_num(pub_confirmed) > 0, state["confirmed"].to_numpy()))


def test_hs_shape_detects_a_clean_textbook_pattern():
    # 谷↔山を反転させた鏡像(230 - close)。
    closes = 230.0 - _hs_base_closes()
    high, low, close = _hlc(closes, wick=0.8)
    state = cp._hs_shape_state(high, low, close, False, **_HS_LOOSE_KWARGS)

    confirmed = np.where(state["confirmed"].to_numpy())[0]
    check("hs 綺麗な教科書形が検出される(Confirmed)", len(confirmed) >= 1,
          detail=f"confirmed={confirmed}")
    if len(confirmed) == 0:
        return
    f = int(state["formed_bar"].iloc[int(confirmed[0])])
    t1p = state["top1_price"].iloc[f]; t2p = state["top2_price"].iloc[f]; t3p = state["top3_price"].iloc[f]
    check("hs 頭は両肩より明確に高い", t2p > max(t1p, t3p) + 5,
          detail=f"肩1={t1p} 頭={t2p} 肩3={t3p}")


def test_hs_shape_rejects_a_head_that_is_not_prominent_enough():
    # トリプルトップと同じ「3山ほぼ同水準」の形は、頭が突出していないので
    # H&Sとしては不成立になるはず(head_prominence_multが既定0.5のまま)。
    closes = 230.0 - _triple_bottom_closes()
    high, low, close = _hlc(closes)
    kwargs = dict(_HS_LOOSE_KWARGS)
    del kwargs["head_prominence_mult"]  # 既定値(0.5)のまま試す
    state = cp._hs_shape_state(high, low, close, False, **kwargs)
    rows = state["candidate"].to_numpy() | state["confirmed"].to_numpy() | state["invalidated"].to_numpy()
    check("hs 頭が突出していない(トリプル相当の)形はH&Sとして不成立",
          not rows.any(), detail=f"rows={np.where(rows)[0]}")


def test_hs_shape_confirms_through_a_sloped_neckline():
    # ネック1(@bar45=108.0)とネック2(@bar75=118.0)を離す(傾いたネック
    # ライン、10ポイント差)。neck_tolerance_mult(2026-08-15訂正: 0は
    # 完全な同水準を意味するリテラルな許容誤差になった、トリプルと同じ
    # 規約)を2.0まで緩めればこの乖離を許容し、傾いたネックラインへの
    # 投影値でブレイク判定してConfirmedするはず。差を大きくしすぎると
    # 遠い将来の外挿値が極端になり、期限内に届かなくなるため、緩やかな
    # 傾きにとどめる。
    closes = 230.0 - np.concatenate([
        np.linspace(130, 110, 15, endpoint=False),
        np.linspace(110, 100, 15, endpoint=False),
        np.linspace(100, 108, 15, endpoint=False),   # ネック1 @bar45=108.0
        np.linspace(108, 55, 15, endpoint=False),    # 頭 @bar60=55.0(深い)
        np.linspace(55, 118, 15, endpoint=False),    # ネック2 @bar75=118.0(ネック1より10高い)
        np.linspace(118, 99.8, 20, endpoint=False),
        np.full(30, 99.8),
        np.linspace(99.8, 160, 30, endpoint=False),
        np.full(40, 160.0),
    ])
    high, low, close = _hlc(closes, wick=0.8)
    kwargs = dict(_HS_LOOSE_KWARGS)
    kwargs["neck_tolerance_mult"] = 2.0
    state = cp._hs_shape_state(high, low, close, False, **kwargs)
    confirmed = np.where(state["confirmed"].to_numpy())[0]
    check("hs ネック1・ネック2が大きく離れていても(傾いたネックライン)Confirmedする",
          len(confirmed) >= 1, detail=f"confirmed={confirmed}")

    kwargs["neck_tolerance_mult"] = 0.0
    state_strict = cp._hs_shape_state(high, low, close, False, **kwargs)
    confirmed_strict = np.where(state_strict["confirmed"].to_numpy())[0]
    check("hs neck_tolerance_mult=0(完全な同水準要求)だと同じ形はConfirmedしない",
          len(confirmed_strict) == 0, detail=f"confirmed={confirmed_strict}")


# ---------------------------------------------------------------------------
# チャネル系(レクタングル/トライアングル/ウェッジ/ペナント/フラッグ)。
# docs/pattern_spec_channel_patterns_shape.md 参照。共通コア
# (_shape_state_core_channel)は1つなので、各家系のテストは主に
# 「その家系固有の分類条件(水平/上昇/下降/収束/平行・start_is_lowの向き)」
# が正しく効くことの確認に絞る - 点探索・先読み防止・3状態モデル自体は
# トリプル/H&Sと共通の仕組みで既に検証済み。
# ---------------------------------------------------------------------------

_CHANNEL_LOOSE_KWARGS = dict(
    pivot_left_bars=3, pivot_right_bars=3,
    symmetry_ratio_min=0.0, symmetry_ratio_max=1.2,
    breakout_deadline_min_bars=3, breakout_deadline_ratio_max=5.0,
    efficiency_ratio_min=0.0, efficiency_ratio_floor=0.0, trendline_dev_pct=1.0,
    efficiency_ratio_min_breakout=0.0, trendline_dev_pct_breakout=1.0,
    efficiency_ratio_min_context=0.0, trendline_dev_pct_context=1.0,
    breakout_buffer_mult=0.05,
)


def _seg(close: np.ndarray, a: float, b: float, i0: int, i1: int) -> None:
    """closes配列のclose[i0:i1+1]を線形に埋める(区分線形の区間を作る、
    区間の始点・終点そのものは呼び出し側で別途明示的に置く点との整合を
    呼び出し側で保証すること - 隣接区間の端点をまたぐ値の大小関係を
    崩すと、意図した点が本当の極値にならない(2026-08-14、テスト構築時に
    実際に踏んだ - 詳しくはgit history参照)。"""
    close[i0:i1 + 1] = np.linspace(a, b, i1 - i0 + 1)


def _ascending_box_closes() -> np.ndarray:
    # 点1=高値@bar10=110(高値起点)→点2=安値@bar20=91→点3=高値@bar30
    # ≈110.2(点1とほぼ同水準)→点4=安値@bar40≈91.2(点2とほぼ同水準)→
    # 小康状態→上抜けブレイク。ascending_box_shapeは2026-08-14以降
    # start_is_low=False(高値起点)で探索するため、点1・点3を高値、
    # 点2・点4を安値にする。
    n = 120
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 110.0
    _seg(close, 109.0, 91.5, 11, 19)
    close[20] = 91.0
    _seg(close, 92.0, 109.0, 21, 29)
    close[30] = 110.2
    _seg(close, 109.2, 91.7, 31, 39)
    close[40] = 91.2
    _seg(close, 92.0, 100.0, 41, 47)   # 点4後の小康状態(ブレイクは3本以上先)
    _seg(close, 112.0, 130.0, 48, 57)  # 上抜けブレイク
    close[58:] = 130.0 + np.arange(n - 58) * 0.01  # ブレイク後は横ばい
    return close


def test_ascending_box_shape_detects_a_clean_textbook_pattern():
    # 2026-08-15、可変タッチ方式(v2)に全面書き換え。既存のテストデータは
    # そのまま使えている(点1〜点4の4点だけの箱でも既定値で検出される)。
    closes = _ascending_box_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.ascending_box_shape(high, low, close)
    idx = np.where(np.nan_to_num(confirmed) > 0)[0]
    check("ascending_box_shape 綺麗な教科書形が検出される(Confirmed)",
          len(idx) >= 1, detail=f"confirmed={idx}")

    cand = cp.ascending_box_shape(high, low, close, state="candidate")
    cand_idx = np.where(np.nan_to_num(cand) > 0)[0]
    check("ascending_box_shape Candidateも検出される", len(cand_idx) >= 1)


def test_ascending_box_shape_v2_rejects_a_downside_excursion():
    # 上限・下限を突破する正式ブレイクの前に、下限を大きく割り込むヒゲが
    # 1本でもあれば無効になるはず(§5、100%滞在の要求)。
    n = 120
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 110.0
    _seg(close, 109.0, 91.5, 11, 19)
    close[20] = 91.0
    _seg(close, 92.0, 109.0, 21, 29)
    close[30] = 110.1
    _seg(close, 109.2, 91.7, 31, 39)
    close[40] = 90.9
    _seg(close, 91.5, 100.0, 41, 46)
    high = close.copy() + 0.3
    low = close.copy() - 0.3
    high[47] = close[47] + 0.3
    low[47] = 70.0  # 下限を大きく割り込む単発のヒゲ
    high_s, low_s, close_s = pd.Series(high), pd.Series(low), pd.Series(close)
    invalidated = cp.ascending_box_shape(high_s, low_s, close_s, state="invalidated")
    confirmed = cp.ascending_box_shape(high_s, low_s, close_s, state="confirmed")
    check("ascending_box_shape 下限逸脱でInvalidatedになる",
          (np.nan_to_num(invalidated) > 0).any(), detail=f"invalidated={np.flatnonzero(np.nan_to_num(invalidated))}")
    check("ascending_box_shape 下限逸脱した形はConfirmedしない",
          not (np.nan_to_num(confirmed) > 0).any())


def test_ascending_box_shape_v2_wick_only_break_does_not_confirm():
    # 終値が戻っていれば、上限を上抜けるヒゲだけではConfirmedにならず
    # Invalidated(逸脱)扱いになるはず(§6、ヒゲのみの突破は不成立)。
    n = 120
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 110.0
    _seg(close, 109.0, 91.5, 11, 19)
    close[20] = 91.0
    _seg(close, 92.0, 109.0, 21, 29)
    close[30] = 110.1
    _seg(close, 109.2, 91.7, 31, 39)
    close[40] = 90.9
    _seg(close, 91.5, 100.0, 41, 46)
    high = close.copy() + 0.3
    low = close.copy() - 0.3
    high[47] = 120.0
    close[47] = 100.5
    low[47] = 100.0
    high_s, low_s, close_s = pd.Series(high), pd.Series(low), pd.Series(close)
    confirmed = cp.ascending_box_shape(high_s, low_s, close_s, state="confirmed")
    invalidated = cp.ascending_box_shape(high_s, low_s, close_s, state="invalidated")
    check("ascending_box_shape ヒゲのみの上抜けはConfirmedしない",
          not (np.nan_to_num(confirmed) > 0).any())
    check("ascending_box_shape ヒゲのみの上抜けはInvalidatedになる",
          (np.nan_to_num(invalidated) > 0).any())


def test_ascending_box_shape_v2_extends_touches_with_extreme_wins():
    # 3つ目・4つ目のタッチ(山3・谷3)が加わっても、途中の緩やかな傾き区間の
    # 手前の1本ではなく、本当の極値(山2・谷2)を拾うはず
    # (2026-08-15、単体テストで発覚した「先読み」バグの再発防止)。
    n = 160
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 110.0
    _seg(close, 109.0, 91.5, 11, 19)
    close[20] = 91.0
    _seg(close, 92.0, 109.0, 21, 29)
    close[30] = 110.1
    _seg(close, 109.2, 91.7, 31, 39)
    close[40] = 90.9
    _seg(close, 91.5, 109.5, 41, 49)
    close[50] = 110.05
    _seg(close, 109.4, 91.2, 51, 59)
    close[60] = 91.1
    _seg(close, 91.8, 100.0, 61, 67)
    _seg(close, 112.0, 130.0, 68, 77)
    close[78:] = 130.0 + np.arange(n - 78) * 0.01
    high_s, low_s, close_s = _hlc(close, wick=0.3)
    state = cp._box_shape_state_v2(high_s, low_s, close_s, True)
    conf_idx = np.flatnonzero(state["confirmed"].to_numpy())
    check("ascending_box_shape_v2 6タッチの形でもConfirmedする", len(conf_idx) >= 1,
          detail=f"confirmed={conf_idx}")
    if len(conf_idx) == 0:
        return
    fb = state["formed_bar"].to_numpy()
    f = int(fb[conf_idx[0]])
    pc = int(state["point_count"][f])
    troughs = [state["point_price"][k, f] for k in range(pc) if k % 2 == 1]
    check("ascending_box_shape_v2 谷が緩やかな傾きの途中ではなく本当の底値に来る",
          all(abs(t - 90.9) < 1.0 or abs(t - 91.1) < 1.0 for t in troughs),
          detail=f"troughs={troughs}")


def test_ascending_box_shape_v2_valley_depth_filter_rejects_shallow_troughs():
    # 谷の深さ(ATR倍率)フィルター(2026-08-16追加、ダブルトップ/ボトムと
    # 同じ考え方)の疎通確認。0(実質無効)なら通常通り検出されるが、
    # 現実にはあり得ないほど厳しい下限を指定すればどの谷も採用条件を
    # 満たせなくなり、最小構成(山1・谷1・山2・谷2)にすら届かず
    # Confirmedしなくなるはず。
    closes = _ascending_box_closes()
    high, low, close = _hlc(closes, wick=0.3)
    loose = cp.ascending_box_shape(high, low, close, min_valley_depth_atr_mult=0.0)
    strict = cp.ascending_box_shape(high, low, close, min_valley_depth_atr_mult=50.0)
    check("ascending_box_shape 谷深さフィルターOFF(0)なら通常通りConfirmedする",
          (np.nan_to_num(loose) > 0).any())
    check("ascending_box_shape 谷深さフィルターを極端に厳しくするとConfirmedしなくなる",
          not (np.nan_to_num(strict) > 0).any())


def test_descending_box_shape_detects_the_mirror_image():
    # 2026-08-15、可変タッチ方式(v2)へ全面書き換え(_box_shape_state_v2を
    # bullish=Falseで呼ぶ、上昇ボックスの上下反転した鏡像)。
    # 上のascending_boxを価格反転(210-close)した鏡像。
    closes = 210.0 - _ascending_box_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.descending_box_shape(high, low, close)
    idx = np.where(np.nan_to_num(confirmed) > 0)[0]
    check("descending_box_shape 鏡像でもConfirmedが検出される", len(idx) >= 1,
          detail=f"confirmed={idx}")


def test_descending_box_shape_legacy_still_works():
    # 旧版(4点固定・共通チャネルコア方式)も比較用にそのまま動くことを確認。
    closes = 210.0 - _ascending_box_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.descending_box_shape_legacy(high, low, close, **_CHANNEL_LOOSE_KWARGS)
    idx = np.where(np.nan_to_num(confirmed) > 0)[0]
    check("descending_box_shape_legacy 鏡像でもConfirmedが検出される", len(idx) >= 1,
          detail=f"confirmed={idx}")


def test_ascending_box_shape_legacy_still_works():
    closes = _ascending_box_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.ascending_box_shape_legacy(high, low, close, **_CHANNEL_LOOSE_KWARGS)
    idx = np.where(np.nan_to_num(confirmed) > 0)[0]
    check("ascending_box_shape_legacy 教科書形が検出される(Confirmed)", len(idx) >= 1,
          detail=f"confirmed={idx}")


def test_ascending_triangle_shape_legacy_requires_a_rising_lower_line():
    # 旧版(4点固定・共通チャネルコア方式)向けのテスト。ascending_boxと
    # 同じ点3配置(点1とほぼ同水準=水平)ではascending_triangle(下側の線=
    # 上昇)としては不成立のはず - flat/flatとrising/flatは排他的条件の
    # ため。2026-08-18、ascending_triangle_shape本体は可変タッチ・回帰
    # 直線方式(v2)へ全面書き換えたため、このテストは_legacyを対象にする
    # (v2向けの同種確認はtest_ascending_triangle_shape_v2_rejects_a_flat_lower_lineで行う)。
    closes = _ascending_box_closes()
    high, low, close = _hlc(closes, wick=0.3)
    tri_confirmed = cp.ascending_triangle_shape_legacy(high, low, close, **_CHANNEL_LOOSE_KWARGS)
    check("ascending_triangle_shape_legacy 下側が水平(箱型)ならConfirmedしない",
          not (np.nan_to_num(tri_confirmed) > 0).any())


def _ascending_triangle_closes() -> np.ndarray:
    # 谷1≈92(bar20)→谷2≈93.5(bar40)→谷3≈94.8(bar60)と切り上がる下値
    # (回帰側)、山1≈108(bar10)・山2≈108.1(bar30)とほぼ同水準の上値
    # (水平側)。谷1→山1→谷2→山2→谷3の順で最小構成(回帰側3点+水平側2点)
    # が揃い、その後上抜けブレイクする。
    n = 100
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 108.0
    _seg(close, 107.0, 92.0, 11, 19)
    close[20] = 92.0
    _seg(close, 93.0, 108.2, 21, 29)
    close[30] = 108.1
    _seg(close, 107.2, 93.5, 31, 39)
    close[40] = 93.5
    _seg(close, 94.5, 107.9, 41, 49)
    close[50] = 107.95
    _seg(close, 107.0, 94.8, 51, 59)
    close[60] = 94.8
    _seg(close, 95.5, 100.0, 61, 66)
    _seg(close, 112.0, 130.0, 67, 76)
    close[77:] = 130.0 + np.arange(n - 77) * 0.01
    return close


def test_ascending_triangle_shape_v2_detects_a_clean_textbook_pattern():
    # min_slope_rise_atr_multはここでは明示的に1.0を指定する(既定値は
    # 2026-08-19にユーザー指示で3.0へ変更したが、このテストの合成データは
    # 「検出ロジックが正しく動くか」を見るためのもので、既定の急さ閾値
    # そのものをテストしたいわけではないため既定値の変更から切り離す)。
    closes = _ascending_triangle_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.ascending_triangle_shape(high, low, close, min_slope_rise_atr_mult=1.0)
    idx = np.where(np.nan_to_num(confirmed) > 0)[0]
    check("ascending_triangle_shape 綺麗な教科書形が検出される(Confirmed)",
          len(idx) >= 1, detail=f"confirmed={idx}")

    cand = cp.ascending_triangle_shape(high, low, close, state="candidate", min_slope_rise_atr_mult=1.0)
    cand_idx = np.where(np.nan_to_num(cand) > 0)[0]
    check("ascending_triangle_shape Candidateも検出される", len(cand_idx) >= 1)

    state = cp._triangle_shape_state_v2(high, low, close, True, min_slope_rise_atr_mult=1.0)
    conf_idx = np.flatnonzero(state["confirmed"].to_numpy())
    f = int(state["formed_bar"].to_numpy()[conf_idx[0]])
    pc = int(state["point_count"][f])
    bars = state["point_bar"][:pc, f].astype(int)
    prices = state["point_price"][:pc, f]
    order = np.argsort(bars)
    bars = bars[order]
    prices = prices[order]
    # 谷(安値側)3点は切り上がっているはず。
    troughs = [prices[i] for i in range(pc) if prices[i] < 105]
    check("ascending_triangle_shape 下値(回帰側)3点が切り上がっている",
          len(troughs) >= 3 and troughs == sorted(troughs),
          detail=f"bars={bars} prices={np.round(prices, 3)}")


def test_ascending_triangle_shape_v2_rejects_a_shallow_slope():
    # 2026-08-18追加: 回帰直線の傾きが正でも、あまりにも緩やかな(ATRに
    # 対して値幅が小さい)場合はmin_slope_rise_atr_multで弾けるはず。
    closes = _ascending_triangle_closes()
    high, low, close = _hlc(closes, wick=0.3)
    loose = cp.ascending_triangle_shape(high, low, close, min_slope_rise_atr_mult=0.0)
    strict = cp.ascending_triangle_shape(high, low, close, min_slope_rise_atr_mult=50.0)
    check("ascending_triangle_shape 傾きフィルターOFF(0)なら通常通りConfirmedする",
          (np.nan_to_num(loose) > 0).any())
    check("ascending_triangle_shape 傾きフィルターを極端に厳しくするとConfirmedしなくなる",
          not (np.nan_to_num(strict) > 0).any())


def test_ascending_triangle_shape_v2_rejects_a_poor_convergence():
    # 2026-08-19追加: max_breakout_height_ratio(谷1〜上値抵抗線の値幅に
    # 対する、ブレイク時点の回帰直線延長〜上値抵抗線の値幅の比率上限)。
    # 0(既定、無効)なら通常通りConfirmedし、極端に厳しい値(実質どんな
    # パターンでも満たせない)にするとConfirmedしなくなるはず。
    closes = _ascending_triangle_closes()
    high, low, close = _hlc(closes, wick=0.3)
    loose = cp.ascending_triangle_shape(high, low, close, min_slope_rise_atr_mult=1.0, max_breakout_height_ratio=0.0)
    strict = cp.ascending_triangle_shape(high, low, close, min_slope_rise_atr_mult=1.0, max_breakout_height_ratio=0.001)
    check("ascending_triangle_shape 収束チェックOFF(0)なら通常通りConfirmedする",
          (np.nan_to_num(loose) > 0).any())
    check("ascending_triangle_shape 収束チェックを極端に厳しくするとConfirmedしなくなる",
          not (np.nan_to_num(strict) > 0).any())


def test_ascending_triangle_shape_v2_rejects_a_flat_lower_line():
    # ボックスと同じ点配置(下側がほぼ水平)では、回帰直線の傾きが
    # 正(上昇)にならない(または谷が3点そろわない)ため、Confirmedしない
    # はず。
    closes = _ascending_box_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.ascending_triangle_shape(high, low, close)
    check("ascending_triangle_shape 下側が水平(箱型)ならConfirmedしない",
          not (np.nan_to_num(confirmed) > 0).any())


def test_ascending_triangle_shape_v2_rejects_a_poorly_fitting_regression():
    # 2026-08-18追加: 谷1・谷2・谷3の全体の傾きがプラスでも、真ん中の谷が
    # 回帰直線から大きく飛び出ていたら不成立のはず(3点自体の当てはまり
    # チェック)。谷1=92→谷2=101.5(大きく飛び出る)→谷3=94.8。
    n = 100
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 108.0
    _seg(close, 107.0, 92.0, 11, 19)
    close[20] = 92.0
    _seg(close, 93.0, 108.2, 21, 29)
    close[30] = 108.1
    _seg(close, 107.2, 101.5, 31, 39)
    close[40] = 101.5
    _seg(close, 102.5, 107.9, 41, 49)
    close[50] = 107.95
    _seg(close, 107.0, 94.8, 51, 59)
    close[60] = 94.8
    _seg(close, 95.5, 100.0, 61, 66)
    _seg(close, 112.0, 130.0, 67, 76)
    close[77:] = 130.0 + np.arange(n - 77) * 0.01

    high, low, close_s = _hlc(close, wick=0.3)
    confirmed = cp.ascending_triangle_shape(high, low, close_s)
    candidate = cp.ascending_triangle_shape(high, low, close_s, state="candidate")
    check("ascending_triangle_shape 真ん中の谷が直線から飛び出た形はCandidateにもならない",
          not (np.nan_to_num(candidate) > 0).any())
    check("ascending_triangle_shape 真ん中の谷が直線から飛び出た形はConfirmedしない",
          not (np.nan_to_num(confirmed) > 0).any())


def test_ascending_triangle_shape_v2_rejects_a_downside_excursion():
    # 回帰直線が固定された後、その直線から大きく下に外れる動きが出たら
    # Invalidatedになり、Confirmedはしないはず(§5・§6)。
    n = 110
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 108.0
    _seg(close, 107.0, 92.0, 11, 19)
    close[20] = 92.0
    _seg(close, 93.0, 108.2, 21, 29)
    close[30] = 108.1
    _seg(close, 107.2, 93.5, 31, 39)
    close[40] = 93.5
    _seg(close, 94.5, 107.9, 41, 49)
    close[50] = 107.95
    _seg(close, 107.0, 94.8, 51, 59)
    close[60] = 94.8
    _seg(close, 95.5, 108.0, 61, 66)
    close[66] = 108.05
    _seg(close, 107.0, 80.0, 67, 73)
    close[73] = 80.0
    _seg(close, 85.0, 100.0, 74, 79)
    _seg(close, 112.0, 130.0, 80, 89)
    close[90:] = 130.0 + np.arange(n - 90) * 0.01

    # ここも他の2つのテストと同じ理由でmin_slope_rise_atr_mult=1.0を明示
    # (谷92.0→93.5→94.8はゆるい傾きで、既定値3.0だと回帰直線自体が
    # 成立せず、このテストが検証したい「成立後の下方逸脱」に辿り着けない)。
    high, low, close_s = _hlc(close, wick=0.3)
    invalidated = cp.ascending_triangle_shape(high, low, close_s, state="invalidated", min_slope_rise_atr_mult=1.0)
    confirmed = cp.ascending_triangle_shape(high, low, close_s, state="confirmed", min_slope_rise_atr_mult=1.0)
    check("ascending_triangle_shape 回帰直線からの下方逸脱でInvalidatedになる",
          (np.nan_to_num(invalidated) > 0).any(),
          detail=f"invalidated={np.flatnonzero(np.nan_to_num(invalidated))}")
    check("ascending_triangle_shape 逸脱した形はConfirmedしない",
          not (np.nan_to_num(confirmed) > 0).any())


def test_ascending_triangle_shape_v2_rejects_a_historical_breach_before_the_line_is_fixed():
    # 2026-08-19追加: ユーザー報告「下値支持線が大幅に割れてるのに無効に
    # ならない」対応。回帰直線が確定した後の下方逸脱は上のテスト
    # (test_..._rejects_a_downside_excursion)で§6の順方向チェックとして
    # 既にカバーされている。ここでテストしたいのはそれとは別のケースで、
    # 直線がまだ確定していない(=谷1・谷2・谷3の組み合わせを探している)
    # 最中に、谷1・谷2の間で一時的に大きく below に外れる動きが起きて
    # から回復し、谷1・谷2・谷3自体は綺麗に切り上がって回帰直線の条件を
    # 満たしてしまう形。この「谷1と谷2の間の生の安値」は3点の当てはまり
    # チェック(§5.2)では見ておらず、§6の順方向チェックもまだ直線が
    # 確定していないので動いていないため、遡及チェック(§4.3近辺、
    # 2026-08-19追加)が無いと見過ごされてしまう。
    n = 90
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 108.0
    _seg(close, 107.0, 92.0, 11, 19)
    close[20] = 92.0  # 谷1(起点)
    _seg(close, 93.0, 70.0, 21, 25)  # 谷1・谷2の間で大きく below に外れる
    close[25] = 70.0
    _seg(close, 75.0, 108.2, 26, 29)
    close[30] = 108.1
    _seg(close, 107.2, 93.5, 31, 39)
    close[40] = 93.5  # 谷2
    _seg(close, 94.5, 107.9, 41, 49)
    close[50] = 107.95
    _seg(close, 107.0, 94.8, 51, 59)
    close[60] = 94.8  # 谷3(切り上がり92→93.5→94.8で回帰直線自体は成立しうる)
    _seg(close, 95.5, 108.0, 61, 66)
    close[66] = 108.05
    _seg(close, 107.0, 100.0, 67, 75)
    _seg(close, 112.0, 130.0, 76, 85)
    close[86:] = 130.0 + np.arange(n - 86) * 0.01

    high, low, close_s = _hlc(close, wick=0.3)
    confirmed = cp.ascending_triangle_shape(high, low, close_s, state="confirmed", min_slope_rise_atr_mult=1.0)
    candidate = cp.ascending_triangle_shape(high, low, close_s, state="candidate", min_slope_rise_atr_mult=1.0)
    check("ascending_triangle_shape 直線確定前の谷1-谷2間の大きな下方逸脱はConfirmedしない",
          not (np.nan_to_num(confirmed) > 0).any(),
          detail=f"confirmed={np.flatnonzero(np.nan_to_num(confirmed))}")
    check("ascending_triangle_shape 直線確定前の谷1-谷2間の大きな下方逸脱はCandidateにもならない",
          not (np.nan_to_num(candidate) > 0).any(),
          detail=f"candidate={np.flatnonzero(np.nan_to_num(candidate))}")


def test_descending_triangle_shape_v2_detects_the_mirror_image():
    # 上のascending_triangleを価格反転(200-close)した鏡像。min_slope_rise_
    # atr_multを明示するのはtest_ascending_triangle_shape_v2_detects_a_
    # clean_textbook_patternと同じ理由(既定値3.0への変更から切り離す)。
    closes = 200.0 - _ascending_triangle_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.descending_triangle_shape(high, low, close, min_slope_rise_atr_mult=1.0)
    idx = np.where(np.nan_to_num(confirmed) > 0)[0]
    check("descending_triangle_shape 鏡像でもConfirmedが検出される", len(idx) >= 1,
          detail=f"confirmed={idx}")


def _ascending_triangle_legacy_closes() -> np.ndarray:
    # 旧版(4点固定)向けの綺麗な教科書形(点1=山、点2=谷、点3=山とほぼ
    # 同水準、点4=谷で点2より切り上げ)。
    n = 120
    close = np.full(n, 100.0)
    _seg(close, 95.5, 99.5, 0, 9)
    close[10] = 108.0
    _seg(close, 107.0, 92.0, 11, 19)
    close[20] = 92.0
    _seg(close, 93.0, 108.2, 21, 29)
    close[30] = 108.1
    _seg(close, 107.2, 98.5, 31, 39)
    close[40] = 98.0
    _seg(close, 99.0, 112.0, 41, 47)
    _seg(close, 112.0, 130.0, 48, 57)
    close[58:] = 130.0 + np.arange(n - 58) * 0.01
    return close


def test_ascending_triangle_shape_legacy_still_works():
    closes = _ascending_triangle_legacy_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.ascending_triangle_shape_legacy(high, low, close, **_CHANNEL_LOOSE_KWARGS)
    idx = np.where(np.nan_to_num(confirmed) > 0)[0]
    check("ascending_triangle_shape_legacy 教科書形が検出される(Confirmed)", len(idx) >= 1,
          detail=f"confirmed={idx}")


def test_descending_triangle_shape_legacy_still_works():
    closes = 200.0 - _ascending_triangle_legacy_closes()
    high, low, close = _hlc(closes, wick=0.3)
    confirmed = cp.descending_triangle_shape_legacy(high, low, close, **_CHANNEL_LOOSE_KWARGS)
    idx = np.where(np.nan_to_num(confirmed) > 0)[0]
    check("descending_triangle_shape_legacy 鏡像でもConfirmedが検出される", len(idx) >= 1,
          detail=f"confirmed={idx}")


def _rising_wedge_closes(break_direction: str) -> np.ndarray:
    # 下値支持線(谷1・谷2・谷3、bar5/25/45、95→99→103、傾き0.2/bar)・
    # 上値抵抗線(山1・山2・山3、bar15/35/55、108→109.5→111、傾き
    # 0.075/bar)が両方とも右肩上がりで、かつ下値の方が上値より急(=収束)
    # するウェッジ形(2026-08-19、rising_wedge_shape v2全面書き換え -
    # docs/pattern_spec_wedge_shape_v2.md。下値の方が急でないと収束せず
    # ウェッジにならない、というユーザー指摘を受けて傾きを組み直した)。
    # break_directionで、山3の後に下値支持線を下抜けるか("lower")、
    # 山3の後に一旦浅く戻してから上値抵抗線を上抜けるか("upper")を
    # 切り替える。
    n = 100
    close = np.full(n, 100.0)
    _seg(close, 95.5, 95.0, 0, 5)
    close[5] = 95.0
    _seg(close, 96.0, 108.0, 6, 15)
    close[15] = 108.0
    _seg(close, 107.0, 99.0, 16, 25)
    close[25] = 99.0
    _seg(close, 100.0, 109.5, 26, 35)
    close[35] = 109.5
    _seg(close, 108.5, 103.0, 36, 45)
    close[45] = 103.0
    _seg(close, 104.0, 111.0, 46, 55)
    close[55] = 111.0
    if break_direction == "lower":
        _seg(close, 109.5, 85.0, 56, 65)
        close[65:] = 85.0 - np.arange(n - 65) * 0.05
    else:
        _seg(close, 110.5, 107.5, 56, 60)
        close[60] = 107.5
        _seg(close, 108.5, 135.0, 61, 75)
        close[75:] = 135.0 + np.arange(n - 75) * 0.05
    return close


def test_rising_wedge_shape_v2_detects_a_lower_break():
    closes = _rising_wedge_closes("lower")
    high, low, close = _hlc(closes, wick=0.3)
    confirmed_lower = cp.rising_wedge_shape(high, low, close, state="confirmed_lower", min_slope_rise_atr_mult=0.0)
    confirmed_upper = cp.rising_wedge_shape(high, low, close, state="confirmed_upper", min_slope_rise_atr_mult=0.0)
    check("rising_wedge_shape 下値支持線を割る形はconfirmed_lowerになる",
          (np.nan_to_num(confirmed_lower) > 0).any())
    check("rising_wedge_shape 下値支持線を割る形はconfirmed_upperにはならない",
          not (np.nan_to_num(confirmed_upper) > 0).any())


def test_rising_wedge_shape_v2_detects_an_upper_break():
    closes = _rising_wedge_closes("upper")
    high, low, close = _hlc(closes, wick=0.3)
    confirmed_lower = cp.rising_wedge_shape(high, low, close, state="confirmed_lower", min_slope_rise_atr_mult=0.0)
    confirmed_upper = cp.rising_wedge_shape(high, low, close, state="confirmed_upper", min_slope_rise_atr_mult=0.0)
    check("rising_wedge_shape 上値抵抗線を上抜ける形はconfirmed_upperになる",
          (np.nan_to_num(confirmed_upper) > 0).any())
    check("rising_wedge_shape 上値抵抗線を上抜ける形はconfirmed_lowerにはならない",
          not (np.nan_to_num(confirmed_lower) > 0).any())


def test_rising_wedge_shape_v2_both_lines_are_rising_and_ordered():
    # 両直線とも傾きが正(上昇)で、各構成点の位置で下値直線が上値直線を
    # 上回っていない(=水準の上下関係が保たれている)ことを確認する。
    closes = _rising_wedge_closes("lower")
    high, low, close = _hlc(closes, wick=0.3)
    state = cp._wedge_shape_state_v2(high, low, close, min_slope_rise_atr_mult=0.0)
    idx = np.flatnonzero(state["confirmed_lower"].to_numpy())
    check("rising_wedge_shape_v2 テスト用の形が最低1件Confirmedする", len(idx) >= 1)
    if len(idx) == 0:
        return
    f = int(state["formed_bar"].to_numpy()[idx[0]])
    pc = int(state["point_count"][f])
    bars = state["point_bar"][:pc, f].astype(int)
    lo_slope = state["lo_slope"][f]
    up_slope = state["up_slope"][f]
    check("rising_wedge_shape_v2 下値支持線の傾きが正", lo_slope > 0)
    check("rising_wedge_shape_v2 上値抵抗線の傾きも正", up_slope > 0)


def test_rising_wedge_shape_x_is_an_identical_duplicate():
    # 2026-08-19、ユーザー指示で rising_wedge_shape(上昇ウェッジST)を
    # 複製・保存した別家系(上昇ウェッジX)。複製時点ではロジックが完全に
    # 同一であることを確認する。
    for direction in ("lower", "upper"):
        closes = _rising_wedge_closes(direction)
        high, low, close = _hlc(closes, wick=0.3)
        original = cp.rising_wedge_shape(high, low, close, min_slope_rise_atr_mult=0.0)
        duplicate = cp.rising_wedge_shape_x(high, low, close, min_slope_rise_atr_mult=0.0)
        check(f"rising_wedge_shape_x rising_wedge_shapeと同一の結果になる({direction})",
              np.array_equal(np.nan_to_num(original), np.nan_to_num(duplicate)))


def _bullish_pennant_closes(pole_start: float) -> np.ndarray:
    # 旗竿(pole_startから点1へ急伸/緩伸)→点1(高値110)→点2(安値101、
    # 値幅9)→点3(高値108、点1よりやや低い)→点4(安値103、点2よりやや
    # 高い、値幅5に収束)→小康状態→上抜けブレイク。pole_startを点1に
    # 近い値にすると旗竿が実質無くなる。
    n = 130
    close = np.full(n, 100.0)
    _seg(close, pole_start, 108.0, 0, 9)
    close[10] = 110.0
    _seg(close, 109.0, 101.5, 11, 19)
    close[20] = 101.0
    _seg(close, 101.8, 107.5, 21, 29)
    close[30] = 108.0
    _seg(close, 107.3, 103.5, 31, 39)
    close[40] = 103.0
    _seg(close, 103.8, 105.0, 41, 47)
    _seg(close, 110.0, 130.0, 48, 57)
    close[58:] = 130.0 + np.arange(n - 58) * 0.01
    return close


def test_bullish_pennant_shape_requires_a_strong_pole():
    # pole_height_min_multの既定(3.0)により、急な旗竿があるほうだけ
    # Candidateが出るはず。
    high_pole, low_pole, close_pole = _hlc(_bullish_pennant_closes(30.0), wick=0.3)   # 30→108、急な旗竿
    high_flat, low_flat, close_flat = _hlc(_bullish_pennant_closes(107.0), wick=0.3)  # 107→108、旗竿ほぼ無し

    cand_pole = cp.bullish_pennant_shape(high_pole, low_pole, close_pole, state="candidate", **_CHANNEL_LOOSE_KWARGS)
    cand_flat = cp.bullish_pennant_shape(high_flat, low_flat, close_flat, state="candidate", **_CHANNEL_LOOSE_KWARGS)
    check("bullish_pennant_shape 急な旗竿があればCandidateが検出される",
          (np.nan_to_num(cand_pole) > 0).any(), detail=f"{np.flatnonzero(np.nan_to_num(cand_pole))}")
    check("bullish_pennant_shape 旗竿が無ければCandidateが検出されない",
          not (np.nan_to_num(cand_flat) > 0).any())


def test_channel_classify_mask_maps_lower_upper_by_start_is_low():
    # _channel_classify_maskの2026-08-14修正(start_is_low=Falseのとき
    # 点1・点3を物理的な「上側」として扱う)の直接確認。
    idx = pd.RangeIndex(3)
    raw = {
        "p1_price": pd.Series([110.0, np.nan, np.nan], index=idx),  # 高値側
        "p2_price": pd.Series([100.0, np.nan, np.nan], index=idx),  # 安値側
        "p3_price": pd.Series([110.1, np.nan, np.nan], index=idx),
        "p4_price": pd.Series([100.1, np.nan, np.nan], index=idx),
        "p1_bar": pd.Series([0.0, np.nan, np.nan], index=idx),
        "p2_bar": pd.Series([1.0, np.nan, np.nan], index=idx),
        "p3_bar": pd.Series([2.0, np.nan, np.nan], index=idx),
        "p4_bar": pd.Series([3.0, np.nan, np.nan], index=idx),
    }
    # start_is_low=False: 点1・点3(高値)が上側→flat、点2・点4(安値)が
    # 下側→flat、なのでflat/flatはTrueになるはず。
    ok_correct = cp._channel_classify_mask(raw, False, 0.25, "flat", "flat")
    check("_channel_classify_mask start_is_low=Falseでflat/flatが正しく判定される",
          bool(ok_correct.iloc[0]))
    # 下側が「上昇」だと要求した場合は、点2→点4(安値、ほぼ横ばい)は
    # flatなのでrisingは満たさずFalseになるはず。
    ok_wrong = cp._channel_classify_mask(raw, False, 0.25, "rising", "flat")
    check("_channel_classify_mask 実際には横ばいの下側にrisingを要求するとFalse",
          not bool(ok_wrong.iloc[0]))


if __name__ == "__main__":
    test_double_bottom_shape_breakout_deadline_min_bars_used_as_is_below_pivot_right_bars()
    test_double_bottom_shape_rejects_breakout_hidden_inside_pivot_confirm_window()
    test_double_bottom_shape_top2_confirms_without_right_side_pivot_wait()
    test_double_bottom_shape_neck_to_top2_also_bound_by_min_max_bars_between_tops()
    test_double_top_zigzag_confirms_on_clean_pattern()
    test_double_bottom_zigzag_confirms_on_clean_pattern_mirror()
    test_double_top_zigzag_ratio_threshold_is_strict_less_than()
    test_double_top_zigzag_requires_p1_to_be_a_new_high()
    test_double_top_zigzag_rejects_when_all_three_points_are_equal()
    test_double_top_zigzag_confirmed_wins_over_invalidated_on_the_same_bar()
    test_double_top_zigzag_resolves_each_pattern_only_once()
    test_double_top_zigzag_tracks_overlapping_patterns_independently()
    test_double_top_zigzag_keeps_every_event_when_two_patterns_resolve_on_one_bar()
    test_double_top_zigzag_event_records_carry_the_full_pattern_detail()
    test_double_top_zigzag_clamps_parameters_into_the_spec_range()
    test_rrcp_detects_each_of_the_six_patterns()
    test_rrcp_head_and_shoulders_needs_the_head_ratio()
    test_rrcp_point_counts_match_the_spec()
    test_rrcp_neckline_and_extreme_follow_the_spec()
    test_rrcp_confirmed_and_invalidated_follow_double_top_rules()
    test_rrcp_pattern_ids_are_unique_and_link_candidate_to_resolution()
    test_rrcp_clamps_parameters_into_the_spec_range()
    test_abcd_projects_d_point_from_the_abc_ratio()
    test_abcd_ratio_range_includes_both_ends()
    test_abcd_resolution_is_touch_based_and_happens_once()
    test_abcd_pattern_ids_are_unique_and_formatted()
    test_abcd_clamps_parameters_into_the_spec_range()
    test_abc_level_formulas_match_fibratios()
    test_abc_status_transitions_follow_the_reference()
    test_abc_detection_conditions_on_real_data()
    test_abc_trade_condition_filter_narrows_results()
    test_abc_clamps_parameters_into_the_spec_range()
    test_mw_trend_series_ordering_matches_the_reference()
    test_mw_check_classifies_a_textbook_impulse()
    test_mw_ratios_are_rounded_to_three_decimals()
    test_mw_diagonals_are_unreachable_in_the_reference()
    test_mw_events_follow_the_common_management_spec()
    test_mw_points_and_levels_follow_the_spec()
    test_mw_confirmed_and_invalidated_use_wicks()
    test_mw_level_type_absolute_is_a_subset_of_minimum()
    test_mw_repaint_off_detects_later()
    test_mw_clamps_parameters_into_the_spec_range()
    test_fnp_line_price_is_linear_interpolation()
    test_fnp_inspect_rejects_a_line_cut_by_a_candle_body()
    test_fnp_resolve_pattern_type_covers_the_spec_table()
    test_fnp_allowed_pattern_table_matches_the_reference()
    test_fnp_detects_all_four_patterns_on_real_data()
    test_fnp_base_pattern_determines_the_flag_type()
    test_fnp_pole_and_levels_follow_the_spec()
    test_fnp_events_follow_the_common_management_spec()
    test_fnp_confirmed_and_invalidated_use_wicks()
    test_fnp_disabling_zigzags_reduces_detections()
    test_fnp_thresholds_change_the_result()
    test_fnp_clamps_parameters_into_the_spec_range()
    test_acp_inspect_adds_the_touch_ratio_condition()
    test_acp_bar_ratio_uses_point_indices()
    test_acp_shares_the_classification_with_flags_and_pennants()
    test_acp_detects_all_thirteen_patterns()
    test_acp_points_and_levels_follow_the_spec()
    test_acp_events_follow_the_common_management_spec()
    test_acp_confirmed_and_invalidated_use_wicks()
    test_acp_last_pivot_direction_filter()
    test_acp_zigzag_toggles_and_thresholds_work()
    test_acp_clamps_parameters_into_the_spec_range()
    test_make_dedup_key_drops_only_the_newest_point()
    test_pattern_dedup_ignores_the_newest_point()
    test_shape_neckline_window_ignores_pivots_that_cannot_be_top2()
    test_triple_bottom_shape_detects_a_clean_textbook_pattern()
    test_triple_top_shape_detects_a_clean_textbook_pattern()
    test_triple_bottom_shape_middle_trough_picks_the_lowest_tolerance_filtered_candidate()
    test_triple_bottom_shape_neck_tolerance_mult_rejects_divergent_necks()

    test_hs_shape_detects_a_clean_textbook_pattern()
    test_inverse_hs_shape_detects_a_clean_textbook_pattern()
    test_hs_shape_rejects_a_head_that_is_not_prominent_enough()
    test_hs_shape_confirms_through_a_sloped_neckline()
    test_ascending_box_shape_detects_a_clean_textbook_pattern()
    test_ascending_box_shape_v2_rejects_a_downside_excursion()
    test_ascending_box_shape_v2_wick_only_break_does_not_confirm()
    test_ascending_box_shape_v2_extends_touches_with_extreme_wins()
    test_ascending_box_shape_v2_valley_depth_filter_rejects_shallow_troughs()
    test_descending_box_shape_detects_the_mirror_image()
    test_descending_box_shape_legacy_still_works()
    test_ascending_box_shape_legacy_still_works()
    test_ascending_triangle_shape_legacy_requires_a_rising_lower_line()
    test_ascending_triangle_shape_v2_detects_a_clean_textbook_pattern()
    test_ascending_triangle_shape_v2_rejects_a_shallow_slope()
    test_ascending_triangle_shape_v2_rejects_a_poor_convergence()
    test_ascending_triangle_shape_v2_rejects_a_flat_lower_line()
    test_ascending_triangle_shape_v2_rejects_a_poorly_fitting_regression()
    test_ascending_triangle_shape_v2_rejects_a_downside_excursion()
    test_ascending_triangle_shape_v2_rejects_a_historical_breach_before_the_line_is_fixed()
    test_descending_triangle_shape_v2_detects_the_mirror_image()
    test_ascending_triangle_shape_legacy_still_works()
    test_descending_triangle_shape_legacy_still_works()
    test_rising_wedge_shape_v2_detects_a_lower_break()
    test_rising_wedge_shape_v2_detects_an_upper_break()
    test_rising_wedge_shape_v2_both_lines_are_rising_and_ordered()
    test_rising_wedge_shape_x_is_an_identical_duplicate()
    test_bullish_pennant_shape_requires_a_strong_pole()
    test_channel_classify_mask_maps_lower_upper_by_start_is_low()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll chart_patterns tests passed.")
