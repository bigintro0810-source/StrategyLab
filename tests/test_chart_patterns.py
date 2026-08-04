"""Regression tests for engine/chart_patterns.py (classic multi-swing chart
patterns, added 2026-07-08). Plain-script style (not pytest-based) matching
this project's convention - run directly with `python
tests/test_chart_patterns.py`.

Hand-built synthetic OHLC sequences with a known answer by construction -
there's no external reference to check chart-pattern definitions against
(same situation as engine/smc_indicators.py and engine/candlestick_patterns.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import engine.chart_patterns as cp

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


def test_head_and_shoulders_breakdown():
    left_shoulder_up = np.linspace(100, 120, 12)
    left_shoulder_down = np.linspace(120, 108, 12)
    head_up = np.linspace(108, 140, 12)      # head clearly higher
    head_down = np.linspace(140, 108, 12)    # trough back to a similar level
    right_shoulder_up = np.linspace(108, 120.5, 12)  # shoulder similar to the left one
    right_shoulder_down = np.linspace(120.5, 95, 20)  # breaks the neckline (~108)
    closes = np.concatenate([
        left_shoulder_up, left_shoulder_down, head_up, head_down,
        right_shoulder_up, right_shoulder_down,
    ])
    high, low, close = _hlc(closes)
    result = cp.head_and_shoulders_breakdown(high, low, close, swing_lookback=5, shoulder_tolerance_atr_mult=1.0, head_margin_atr_mult=0.5)
    check("head_and_shoulders_breakdown fires at least once on a clean H&S", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_ascending_triangle_breakout():
    # Flat resistance around 130, rising support (each trough higher than
    # the last), then a clean break above resistance.
    rng = np.random.RandomState(0)
    segments = []
    base = 100.0
    for i in range(4):
        up = np.linspace(base, 130 - rng.uniform(0, 0.3), 10)
        down = np.linspace(130 - rng.uniform(0, 0.3), base + 5, 10)
        segments.append(up)
        segments.append(down)
        base += 5
    breakout = np.linspace(base, 145, 15)
    closes = np.concatenate(segments + [breakout])
    high, low, close = _hlc(closes)
    result = cp.ascending_triangle_breakout(high, low, close, swing_lookback=4, flat_tolerance_atr_mult=1.0)
    check("ascending_triangle_breakout fires at least once", result.sum() >= 1, detail=str(result.sum()))


def test_in_range_box_and_breakout():
    rng = np.random.RandomState(1)
    boxed = 100 + rng.normal(0, 0.1, 100)
    breakout = 100 + np.cumsum(np.abs(rng.normal(0.3, 0.1, 20)))  # sustained push upward
    closes = np.concatenate([boxed, breakout])
    high, low, close = _hlc(closes, wick=0.15)
    boxed_state = cp.in_range_box(high, low, close, window=20, box_atr_mult=2.0)
    breakout_signal = cp.range_box_breakout_bullish(high, low, close, window=20, box_atr_mult=2.0)
    check("in_range_box reads True during the boxed phase", boxed_state[30:95].sum() > 0)
    check("range_box_breakout_bullish fires after the box, during the breakout run", breakout_signal[100:120].sum() > 0, detail=str(breakout_signal[95:120]))


def _seg(a: float, b: float, n: int) -> np.ndarray:
    return np.linspace(a, b, n, endpoint=False)


def _triple_bottom_closes(v2: float = 100.2, v3: float = 99.9, breakout_n: int = 30) -> np.ndarray:
    """谷1(99.7)→ネック1(110.3)→谷2→ネック2(110.5)→谷3→ブレイクの、
    手作りの「本物のトリプルボトム」に近い形。谷2/谷3の水準を変えて
    合格/不合格の境界を作れるようにパラメータ化してある。"""
    parts = [
        _seg(130, 110, 15), _seg(110, 100, 15), _seg(100, 110, 15),
        _seg(110, v2, 15), _seg(v2, 110.2, 15), _seg(110.2, v3, 15),
        _seg(v3, 135, breakout_n),
    ]
    return np.concatenate(parts)


def test_triple_bottom_shape_confirms_on_clean_pattern():
    # 3つの谷(99.7/100.2/99.9)が近い水準に並び、2つのネック(110.3/110.5)を
    # 経てブレイクする、教科書的なトリプルボトム。孤立度(スパイク)チェックは
    # 直線的な合成データだと不自然に働く(モジュール内コメント参照)ため
    # 0=無効にして、形状ロジック本体だけを検証する。
    closes = _triple_bottom_closes()
    high, low, close = _hlc(closes)
    result = cp.triple_bottom_shape(
        high, low, close, state="confirmed",
        pivot_spike_excess_atr_max=0.0,
    )
    check("triple_bottom_shape confirms on a clean W-W pattern", result.sum() >= 1, detail=str(np.where(result)[0]))

    state = cp._triple_top_bottom_shape_state(high, low, close, True, pivot_spike_excess_atr_max=0.0)
    f = np.flatnonzero(state["detected"].to_numpy())
    check("triple_bottom_shape detects exactly one formation", len(f) == 1, detail=str(f))
    if len(f) == 1:
        i = f[0]
        check(
            "triple_bottom_shape's 3 valleys land on the 3 constructed lows",
            (int(state["top1_bar"].iloc[i]), int(state["top2_bar"].iloc[i]), int(state["top3_bar"].iloc[i])) == (30, 60, 90),
            detail=str((state["top1_bar"].iloc[i], state["top2_bar"].iloc[i], state["top3_bar"].iloc[i])),
        )
        check(
            "triple_bottom_shape's 2 necks land on the 2 constructed highs",
            (int(state["neck1_bar"].iloc[i]), int(state["neck2_bar"].iloc[i])) == (45, 75),
            detail=str((state["neck1_bar"].iloc[i], state["neck2_bar"].iloc[i])),
        )


def test_triple_top_shape_confirms_on_clean_pattern_mirror():
    # ダブル/トリプルの鏡像性の検証を兼ねて、トリプルボトム用の系列を上下
    # 反転させただけの系列でトリプルトップも成立することを確認する。
    closes = 230 - _triple_bottom_closes()
    high, low, close = _hlc(closes)
    result = cp.triple_top_shape(
        high, low, close, state="confirmed",
        pivot_spike_excess_atr_max=0.0,
    )
    check("triple_top_shape confirms on the mirrored M-M pattern", result.sum() >= 1, detail=str(np.where(result)[0]))


def test_triple_bottom_shape_rejects_when_third_valley_is_deeper_downtrend():
    # 谷3が谷1・谷2よりはっきり深い(=トリプルボトムではなく単なる下落継続)
    # 場合は不成立になるべき。水準許容誤差top_tolerance_pctのデフォルト15%
    # に対し、十分外れた深さ(谷1/ネックの値幅の40%相当)まで谷3を下げる。
    closes = _triple_bottom_closes(v3=95.0)
    high, low, close = _hlc(closes)
    result = cp.triple_bottom_shape(
        high, low, close, state="confirmed",
        pivot_spike_excess_atr_max=0.0,
    )
    check("triple_bottom_shape does not confirm when the 3rd valley breaks well below the first two", result.sum() == 0, detail=str(np.where(result)[0]))


def test_triple_bottom_shape_rejects_too_early_breakout():
    # ブレイクがbreakout_deadline_min_bars未満で起きる場合はconfirmedでは
    # なくrejectedになるべき(早すぎるブレイクは無効)。breakout_deadline_
    # min_bars自体はデフォルト値ではなく明示的に大きい値を渡す
    # (2026-08-04、デフォルトが8→3に変わってこのテストの前提=「20本の
    # ゆっくりしたブレイクでもデフォルトより早い」が崩れたため、テストの
    # 意図をデフォルト値の変化に左右されないようにする)。
    closes = _triple_bottom_closes(breakout_n=20)
    high, low, close = _hlc(closes)
    confirmed = cp.triple_bottom_shape(high, low, close, state="confirmed", pivot_spike_excess_atr_max=0.0, breakout_deadline_min_bars=30)
    rejected = cp.triple_bottom_shape(high, low, close, state="rejected", pivot_spike_excess_atr_max=0.0, breakout_deadline_min_bars=30)
    check("triple_bottom_shape marks a too-fast breakout as rejected, not confirmed", confirmed.sum() == 0 and rejected.sum() >= 1, detail=f"confirmed={confirmed.sum()} rejected={rejected.sum()}")


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
    low_min_bars_rejected = cp.double_bottom_shape(high, low, close, state="rejected", pivot_spike_excess_atr_max=0.0,
                                                     pivot_right_bars=10, breakout_deadline_min_bars=2)
    high_min_bars_confirmed = cp.double_bottom_shape(high, low, close, state="confirmed", pivot_spike_excess_atr_max=0.0,
                                                       pivot_right_bars=10, breakout_deadline_min_bars=13)
    high_min_bars_rejected = cp.double_bottom_shape(high, low, close, state="rejected", pivot_spike_excess_atr_max=0.0,
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
    fast_rejected = cp.double_bottom_shape(fast_high, fast_low, fast_close, **dict(kwargs, state="rejected"))
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
    # 山1→ネックと同じmin_bars_between_tops/max_bars_between_topsでも
    # 追加拘束されるようになったはず - 2026-08-04、ユーザー判断:
    # 「山1→ネックと同じところでネック→山2の本数の範囲も決めたい」。
    # 谷2までの区間の本数だけを変えた2パターンを比較する。
    def build(seg4_len):
        return np.concatenate([
            np.linspace(130, 110, 15, endpoint=False), np.linspace(110, 100, 15, endpoint=False),
            np.linspace(100, 110, 15, endpoint=False), np.linspace(110, 100.5, seg4_len, endpoint=False),
            np.linspace(100.5, 135, 30, endpoint=False), np.full(40, 135.0),
        ])

    too_close_high, too_close_low, too_close_close = _hlc(build(4))  # interval2=4 < min_bars_between_tops=5
    ok_high, ok_low, ok_close = _hlc(build(6))  # interval2=6 >= min_bars_between_tops=5

    too_close_state = cp._double_top_bottom_shape_state(
        too_close_high, too_close_low, too_close_close, True,
        pivot_spike_excess_atr_max=0.0, min_bars_between_tops=5, max_bars_between_tops=500,
    )
    ok_state = cp._double_top_bottom_shape_state(
        ok_high, ok_low, ok_close, True,
        pivot_spike_excess_atr_max=0.0, min_bars_between_tops=5, max_bars_between_tops=500,
    )

    check(
        "ネック→山2が4本(min_bars_between_tops=5未満)だと検出されない",
        too_close_state["detected"].sum() == 0,
        detail=f"detected={np.where(too_close_state['detected'].to_numpy())[0]}",
    )
    check(
        "ネック→山2が6本(min_bars_between_tops=5以上)なら正常に検出される",
        ok_state["detected"].sum() >= 1,
        detail=f"detected={np.where(ok_state['detected'].to_numpy())[0]}",
    )


def test_first_occurrence_after_fires_once_per_epoch():
    # Two independent ascending-triangle formations back-to-back should each
    # fire once - the epoch/cumsum machinery must not get stuck after the
    # first (ascending_triangle_breakout uses the same _first_occurrence_
    # after helper as every other pattern in this module).
    def make_ascending_triangle(base):
        rng = np.random.RandomState(int(base))
        segments = []
        b = base
        for _ in range(4):
            up = np.linspace(b, base + 30 - rng.uniform(0, 0.3), 10)
            down = np.linspace(base + 30 - rng.uniform(0, 0.3), b + 5, 10)
            segments.append(up)
            segments.append(down)
            b += 5
        breakout = np.linspace(b, base + 45, 15)
        return np.concatenate(segments + [breakout])

    closes = np.concatenate([make_ascending_triangle(100), make_ascending_triangle(200)])
    high, low, close = _hlc(closes)
    result = cp.ascending_triangle_breakout(high, low, close, swing_lookback=4, flat_tolerance_atr_mult=1.0)
    check("ascending_triangle_breakout fires at least once in each of two independent formations", result[:100].sum() >= 1 and result[100:].sum() >= 1, detail=str(np.where(result)[0]))


if __name__ == "__main__":
    test_head_and_shoulders_breakdown()
    test_ascending_triangle_breakout()
    test_in_range_box_and_breakout()
    test_triple_bottom_shape_confirms_on_clean_pattern()
    test_triple_top_shape_confirms_on_clean_pattern_mirror()
    test_triple_bottom_shape_rejects_when_third_valley_is_deeper_downtrend()
    test_triple_bottom_shape_rejects_too_early_breakout()
    test_double_bottom_shape_breakout_deadline_min_bars_used_as_is_below_pivot_right_bars()
    test_double_bottom_shape_rejects_breakout_hidden_inside_pivot_confirm_window()
    test_double_bottom_shape_top2_confirms_without_right_side_pivot_wait()
    test_double_bottom_shape_neck_to_top2_also_bound_by_min_max_bars_between_tops()
    test_first_occurrence_after_fires_once_per_epoch()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print("\nAll chart_patterns tests passed.")
