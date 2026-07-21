"""Generates a TradingView Pine Script v5 strategy from a Strategy Lab
params dict (V5.0 Pine Script自動生成 - the only V5.0+ item in scope; see
CLAUDE_HANDOVER.md's Version5.0 section).

Every formula here is written out explicitly against Pine's most basic,
unambiguous primitives (ta.ema, ta.rma, ta.highest, ta.lowest, ta.sma,
ta.stdev) rather than higher-level built-ins like ta.macd()/ta.stoch()/
ta.supertrend()/ta.dmi() - this project has no way to execute Pine code
to verify a built-in's exact internal convention (e.g. ta.supertrend's
direction sign), so every indicator is instead a direct, auditable
translation of the same formula already implemented (and where relevant,
TradingView-verified) in engine/technical_indicators.py and
engine/backtest_engine.py.

All tunable numeric/boolean values are wired to input.*() calls (not just
declared and then ignored) so the generated script is actually adjustable
from TradingView's settings dialog, defaulting to the exact backtested
values. What's NOT tunable post-generation: which entry_trigger and which
filters are active - those are structural (which lines of Pine exist at
all), fixed at generation time, matching "this script reproduces THIS one
specific backtested strategy" rather than a fully generic multi-strategy
toolkit.

Known, deliberate departures from exact Python parity (documented in the
generated script's header comment too):

1. Daily levels (pivot/R1/S1/camarilla/woodie/fib pivot/prev-day-high/
   low/close/ADR) do NOT use request.security(..., "D", ...) - that
   would follow TradingView's own daily-bar session boundary, which a
   real strategy on this project's data was confirmed (2026-07-21, via
   a live TradingView chart check) to NOT match the JST-midnight
   boundary engine/technical_indicators.py's daily_reference_levels()
   uses (that specific feed's daily bar opens at JST 06:00), causing a
   large trade-count/timing mismatch for any strategy leaning on these
   indicators. Fixed by detecting the JST calendar-day rollover directly
   (`ta.change(dayofmonth(time, "Asia/Tokyo")) != 0`, the same technique
   already used for today_new_high/today_range_position below) and
   accumulating each day's own running high/low in `var` state instead -
   prevDayHigh/Low/Close (and every pivot/camarilla/woodie/fib level
   built from them) and adr's rolling per-day-range average now match
   the Python engine's day boundary exactly, not just its formulas.
2. Bollinger uses ta.stdev() (population/biased, N denominator) while
   pandas' rolling().std() (used in engine/technical_indicators.py) is
   sample/unbiased (N-1 denominator) - a small numerical difference,
   more noticeable at short periods.
3. ICT/SMC (FVG/Order Block/Breaker/Mitigation/BOS/CHoCH/MSS/Liquidity
   Sweep) and every chart_pattern/harmonic pattern are already marked
   "unverified, exploratory" in engine/smc_indicators.py, engine/
   chart_patterns.py and engine/harmonic_patterns.py themselves - the
   Pine translations here are best-effort, not verified against any
   reference. order_block_bullish/bearish, as registered in
   SUPPORTED_CONDITION_INDICATORS, use engine/smc_indicators.py's
   CURRENT (fixed, non-lookahead) definition, which flags the confirming
   candle's own bar using only that bar's already-closed data - safe to
   translate as-is with no timing offset needed.
4. Swing-high/low detection for every chart_pattern/ict/price_action
   indicator that needs one uses Pine's built-in ta.pivothigh()/
   ta.pivotlow() (a symmetric left/right-bar fractal, confirmed
   `lookback` bars after it forms) as a direct stand-in for engine/
   smc_indicators.py's _detect_swing_highs/_detect_swing_lows (a
   centered rolling-window max/min with the same confirmation delay).
   The two are equivalent in the normal case but engine/smc_indicators.py's
   _collapse_consecutive_runs plateau-flattening refinement isn't
   replicated, so a run of several equal-price bars at a swing may
   register a slightly different point count/timing in Pine.
5. saucer_top/saucer_bottom/cup_with_handle_breakout approximate engine/
   chart_patterns.py's rolling quadratic-fit (np.polyfit degree 2)
   concavity check - Pine has no polynomial-fit primitive - with a
   simpler proxy: the window's price extremum (via ta.highestbars/
   ta.lowestbars, which also reproduces the "is the extremum centered in
   the window" fraction check exactly) compared against the average of
   the window's two endpoints. Concave + centered still gates the
   signal, but the curve-shape check itself is looser than a true
   polyfit.
6. parabolic_sar_line/direction use Pine's built-in ta.sar() rather than
   a manual re-implementation of engine/technical_indicators.py::
   parabolic_sar()'s recursive loop - both follow the same standard
   Wilder formula with the same af_start/af_step/af_max parameters (no
   internal-convention ambiguity like ta.supertrend()'s direction sign),
   and direction here is independently re-derived by comparing close
   against the SAR value rather than trusting any hidden built-in
   convention. obv/mfi/vwap similarly use ta.obv()/ta.mfi()/ta.vwap() -
   each is a single, unambiguous industry-standard formula matching the
   Python engine's own definition, unlike the built-ins this module
   otherwise avoids. ta.vwap()'s daily reset uses Pine's own session
   boundary, not the JST-midnight boundary engine/technical_indicators.py::
   daily_vwap() uses - same category of departure as point 1's daily
   levels.
7. Entry/exit mechanics: run_backtest's SL/TP are touch-based against each
   bar's high/low, same as Pine's default historical bar-replay behavior,
   but weekend/daily-exit and SL/TP priority on the same bar is
   approximated (weekend/daily exit is evaluated and closed first if due;
   otherwise SL/TP stand) rather than an exact single-engine tie-break.

Coverage: as of this module's last update, every one of the 377
indicators/patterns in engine/conditions.py's INDICATOR_REGISTRY has a
Pine translation registered in SUPPORTED_CONDITION_INDICATORS (see the
_b_* builder functions below, grouped by category: time_filter,
indicator, price_action, chart_pattern, ict) - condition-tree-based
strategies (the only kind the manual builder/auto-exploration produce)
can always be converted, modulo the approximations documented above.
"""

from __future__ import annotations

from typing import Any

TIMEZONE = "Asia/Tokyo"

# (pine_var_name, python_key, pine_input_kind, label, default_if_missing)
INPUT_SPECS: list[tuple[str, str, str, str, Any]] = [
    ("pipSize", "pip_size", "float", "Pip size", 0.01),
    ("emaLength", "ema_length", "int", "EMA length", 200),
    ("minBodyPips", "min_body_pips", "float", "Min body (pips)", 20.0),
    ("maxBodyPips", "max_body_pips", "float", "Max body (pips, 0=off)", 0.0),
    ("maxWickPips", "max_wick_pips", "float", "Max wick (pips, 0=off)", 0.0),
    ("emaDistancePips", "ema_distance_pips", "float", "EMA distance (pips)", 50.0),
    ("rsiMin", "rsi_min", "float", "RSI minimum", 70.0),
    ("rr", "rr", "float", "Risk:Reward", 1.2),
    ("lookaheadBars", "lookahead_bars", "int", "Signal lookahead (bars)", 15),
    ("breakoutBars", "breakout_bars", "int", "Breakout lookback (bars)", 30),
    ("sessionStart", "session_start", "int", "Session start hour (JST)", 8),
    ("sessionEnd", "session_end", "int", "Session end hour (JST)", 3),
    ("useWeekendExit", "use_weekend_exit", "bool", "Weekend exit", True),
    ("weekendExitHour", "weekend_exit_hour", "int", "Weekend exit hour (JST, Sat)", 4),
    ("useDailyExit", "use_daily_exit", "bool", "Daily exit", False),
    ("dailyExitHour", "daily_exit_hour", "int", "Daily exit hour (JST)", 4),
    ("donchianPeriod", "donchian_period", "int", "Donchian period", 20),
    ("bollingerPeriod", "bollinger_period", "int", "Bollinger period", 20),
    ("bollingerStd", "bollinger_std", "float", "Bollinger std", 2.0),
    ("macdFast", "macd_fast", "int", "MACD fast", 12),
    ("macdSlow", "macd_slow", "int", "MACD slow", 26),
    ("macdSignalLen", "macd_signal", "int", "MACD signal", 9),
    ("ichimokuTenkan", "ichimoku_tenkan", "int", "Ichimoku Tenkan", 9),
    ("ichimokuKijun", "ichimoku_kijun", "int", "Ichimoku Kijun", 26),
    ("ichimokuSenkouB", "ichimoku_senkou_b", "int", "Ichimoku Senkou B", 52),
    ("stochKPeriod", "stochastic_k_period", "int", "Stochastic %K period", 14),
    ("stochDPeriod", "stochastic_d_period", "int", "Stochastic %D period", 3),
    ("stochSmooth", "stochastic_smooth", "int", "Stochastic smoothing", 3),
    ("stochLevel", "stochastic_level", "float", "Stochastic level", 80.0),
    ("roundNumberPips", "round_number_pips", "float", "Round number distance (pips)", 10.0),
    ("swingLookback", "smc_swing_lookback", "int", "SMC swing lookback", 5),
    ("supertrendPeriod", "supertrend_period", "int", "SuperTrend period", 10),
    ("supertrendMultiplier", "supertrend_multiplier", "float", "SuperTrend multiplier", 3.0),
    ("adxPeriod", "adx_period", "int", "ADX period", 14),
    ("adxThreshold", "adx_threshold", "float", "ADX threshold", 25.0),
]

WEEKDAY_INPUT_SPECS: list[tuple[str, str, str]] = [
    ("wdMonday", "weekday_monday", "Monday"),
    ("wdTuesday", "weekday_tuesday", "Tuesday"),
    ("wdWednesday", "weekday_wednesday", "Wednesday"),
    ("wdThursday", "weekday_thursday", "Thursday"),
    ("wdFriday", "weekday_friday", "Friday"),
]

# Python's df["datetime"].dt.weekday: Monday=0 ... Sunday=6.
# Pine's dayofweek(time, tz): Sunday=1 ... Saturday=7.
_WEEKDAY_TO_PINE_DOW = {
    "wdMonday": 2,
    "wdTuesday": 3,
    "wdWednesday": 4,
    "wdThursday": 5,
    "wdFriday": 6,
}


def _pine_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _pine_literal(kind: str, value: Any) -> str:
    if kind == "bool":
        return _pine_bool(value)
    if kind == "int":
        return str(int(value))
    return repr(float(value))


def _render_inputs(p: dict[str, Any]) -> str:
    lines = []
    for pine_name, py_key, kind, label, default in INPUT_SPECS:
        value = p.get(py_key, default)
        lines.append(f'{pine_name} = input.{kind}({_pine_literal(kind, value)}, "{label}")')

    for pine_name, py_key, label in WEEKDAY_INPUT_SPECS:
        value = p.get(py_key, True)
        lines.append(f'{pine_name} = input.bool({_pine_bool(value)}, "Trade on {label}")')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trigger and filter expressions. Each references only input variables
# (declared by _render_inputs) or variables defined in the indicator block
# (_INDICATOR_BLOCK below) - every indicator is always computed regardless
# of which trigger/filters are actually active, mirroring
# engine/signal_builder.py's own "always compute every Tier-1 array" design
# (the dominant cost is the per-bar state machine, not a few extra ta.*
# calls).
# ---------------------------------------------------------------------------

TRIGGER_PINE: dict[str, str] = {
    "breakout": "(close > open) and (close > prevHigh)",
    "donchian_breakout": "close > donchianUpper",
    "ema_cross": "ta.crossover(close, emaVal)",
    "macd_cross": "ta.crossover(macdLine, macdSignalLine)",
    "bollinger_touch": "close >= bbUpper",
    "ichimoku_cloud_breakout": "ta.crossover(close, cloudTop)",
    "ichimoku_tk_cross": "ta.crossover(tenkan, kijun)",
    "stochastic_kd_cross": "ta.crossover(stochK, stochD)",
    "stochastic_level_cross": "ta.crossover(stochK, stochLevel)",
    "fvg_bearish": "smcFvgBearish",
    "order_block_bearish": "smcOrderBlockBearish",
    "bos_bearish": "smcBosBearish",
    "choch_bearish": "smcChochBearish",
    "liquidity_sweep_bearish": "smcLiquiditySweepBearish",
    "supertrend_flip_bearish": "(stDirection == -1) and (stDirection[1] == 1)",
    "adx_di_cross_bearish": "ta.crossover(minusDI, plusDI)",
}

FILTER_PINE: dict[str, str] = {
    "use_session_filter": "sessionOk",
    "use_min_body_filter": "(close - open) >= minBodyPrice",
    "use_max_body_filter": "(maxBodyPips <= 0) or (math.abs(close - open) / pipSize <= maxBodyPips)",
    "use_max_wick_filter": "(maxWickPips <= 0) or ((high - low) / pipSize <= maxWickPips)",
    "use_ema_distance_filter": "(close > emaVal) and ((close - emaVal) >= emaDistancePrice)",
    "use_rsi_filter": "rsiVal > rsiMin",
    "use_donchian_filter": "close > donchianMid",
    "use_bollinger_filter": "close > bbMiddle",
    "use_macd_filter": "macdLine > macdSignalLine",
    "use_ichimoku_filter": "close > cloudTop",
    "use_stochastic_filter": "stochK > stochD",
    "use_pivot_filter": "close > pivotR1",
    "use_prev_high_filter": "close > prevDayHigh",
    "use_prev_low_filter": "close > prevDayLow",
    "use_round_number_filter": "roundNumberDistance <= roundNumberPips",
    "use_weekday_filter": "weekdayOk",
    "use_fvg_filter": "smcFvgBearish",
    "use_order_block_filter": "smcOrderBlockBearish",
    "use_bos_filter": "smcBosBearish",
    "use_choch_filter": "smcChochBearish",
    "use_liquidity_sweep_filter": "smcLiquiditySweepBearish",
    "use_supertrend_filter": "stDirection == -1",
    "use_adx_filter": "adxLine > adxThreshold",
}

# (flag key, default enabled) - same order/defaults as engine/filters.py's
# FILTER_REGISTRY, kept in sync by hand since Pine has no equivalent import.
FILTER_DEFAULTS: list[tuple[str, bool]] = [
    ("use_session_filter", True),
    ("use_min_body_filter", True),
    ("use_max_body_filter", True),
    ("use_max_wick_filter", True),
    ("use_ema_distance_filter", True),
    ("use_rsi_filter", True),
    ("use_donchian_filter", False),
    ("use_bollinger_filter", False),
    ("use_macd_filter", False),
    ("use_ichimoku_filter", False),
    ("use_stochastic_filter", False),
    ("use_pivot_filter", False),
    ("use_prev_high_filter", False),
    ("use_prev_low_filter", False),
    ("use_round_number_filter", False),
    ("use_weekday_filter", False),
    ("use_fvg_filter", False),
    ("use_order_block_filter", False),
    ("use_bos_filter", False),
    ("use_choch_filter", False),
    ("use_liquidity_sweep_filter", False),
    ("use_supertrend_filter", False),
    ("use_adx_filter", False),
]


def _build_signal_expressions(p: dict[str, Any]) -> tuple[str, list[str]]:
    entry_trigger = p.get("entry_trigger", "breakout")

    if entry_trigger not in TRIGGER_PINE:
        raise ValueError(f"未対応のentry_triggerです(Pine変換未実装): {entry_trigger}")

    trigger_expr = TRIGGER_PINE[entry_trigger]

    active_filter_exprs = []
    for flag_name, default_enabled in FILTER_DEFAULTS:
        if p.get(flag_name, default_enabled):
            active_filter_exprs.append(FILTER_PINE[flag_name])

    return trigger_expr, active_filter_exprs


_INDICATOR_BLOCK = """
// ---- Tier 1: breakout / trend-following indicators ----
emaVal = ta.ema(close, emaLength)
rsiVal = ta.rsi(close, 14)  // Wilder-smoothed, matches TradingView's built-in RSI (verified 2026-07-03, see engine/backtest_engine.py::rsi())
prevHigh = ta.highest(high[1], breakoutBars)

donchianUpper = ta.highest(high[1], donchianPeriod)
donchianLower = ta.lowest(low[1], donchianPeriod)
donchianMid = (donchianUpper + donchianLower) / 2

bbBasis = ta.sma(close, bollingerPeriod)
bbDev = bollingerStd * ta.stdev(close, bollingerPeriod)  // Pine's stdev is population (N); pandas' is sample (N-1) - minor numeric difference vs the Python backtest
bbUpper = bbBasis + bbDev
bbMiddle = bbBasis

macdFastEma = ta.ema(close, macdFast)
macdSlowEma = ta.ema(close, macdSlow)
macdLine = macdFastEma - macdSlowEma
macdSignalLine = ta.ema(macdLine, macdSignalLen)

tenkan = (ta.highest(high, ichimokuTenkan) + ta.lowest(low, ichimokuTenkan)) / 2
kijun = (ta.highest(high, ichimokuKijun) + ta.lowest(low, ichimokuKijun)) / 2
senkouARaw = (tenkan + kijun) / 2
senkouBRaw = (ta.highest(high, ichimokuSenkouB) + ta.lowest(low, ichimokuSenkouB)) / 2
senkouA = senkouARaw[ichimokuKijun]
senkouB = senkouBRaw[ichimokuKijun]
cloudTop = math.max(senkouA, senkouB)

stochLowestLow = ta.lowest(low, stochKPeriod)
stochHighestHigh = ta.highest(high, stochKPeriod)
stochRawK = 100 * (close - stochLowestLow) / (stochHighestHigh - stochLowestLow)
stochK = ta.sma(stochRawK, stochSmooth)
stochD = ta.sma(stochK, stochDPeriod)

// ---- Daily levels: uses TradingView's native daily session boundary,
// NOT the JST-midnight boundary the Python backtest's data pipeline uses
// (see this module's docstring, point 1) ----
[dHigh, dLow, dClose] = request.security(syminfo.tickerid, "D", [high[1], low[1], close[1]], lookahead=barmerge.lookahead_off)
dPivot = (dHigh + dLow + dClose) / 3
pivotR1 = 2 * dPivot - dLow
prevDayHigh = dHigh
prevDayLow = dLow

roundNumberDistance = math.abs(close - math.round(close)) / pipSize

// ---- Tier 2: SuperTrend / ADX (manual recursive translation of
// engine/technical_indicators.py::supertrend()/adx() - not using Pine's
// built-in ta.supertrend()/ta.dmi() so the direction/sign convention is
// guaranteed to match the Python engine rather than an unverified guess) ----
atrVal = ta.rma(ta.tr(true), supertrendPeriod)
hl2Val = (high + low) / 2
basicUpper = hl2Val + supertrendMultiplier * atrVal
basicLower = hl2Val - supertrendMultiplier * atrVal

var float finalUpper = na
var float finalLower = na
var int stDirection = -1

// Read before reassigning: the direction flip below must compare against
// the PREVIOUS bar's band (matches engine/technical_indicators.py::
// supertrend()'s final_upper[i-1]/final_lower[i-1]), not the band value
// just recomputed for this bar.
prevFinalUpper = finalUpper
prevFinalLower = finalLower

finalUpper := (na(prevFinalUpper) or basicUpper < prevFinalUpper or close[1] > prevFinalUpper) ? basicUpper : prevFinalUpper
finalLower := (na(prevFinalLower) or basicLower > prevFinalLower or close[1] < prevFinalLower) ? basicLower : prevFinalLower

if stDirection == -1 and close > prevFinalUpper
    stDirection := 1
else if stDirection == 1 and close < prevFinalLower
    stDirection := -1

upMove = ta.change(high)
downMove = -ta.change(low)
plusDM = (upMove > downMove and upMove > 0) ? upMove : 0.0
minusDM = (downMove > upMove and downMove > 0) ? downMove : 0.0
smoothedTR = ta.rma(ta.tr(true), adxPeriod)
smoothedPlusDM = ta.rma(plusDM, adxPeriod)
smoothedMinusDM = ta.rma(minusDM, adxPeriod)
plusDI = 100 * smoothedPlusDM / smoothedTR
minusDI = 100 * smoothedMinusDM / smoothedTR
dx = 100 * math.abs(plusDI - minusDI) / (plusDI + minusDI)
adxLine = ta.rma(dx, adxPeriod)

// ---- Tier 3 (SMC): best-effort only, unverified even in the Python
// engine itself (see this module's docstring, point 3) ----
swingWindow = 2 * swingLookback + 1
swingHighNow = high[swingLookback] == ta.highest(high, swingWindow)
swingLowNow = low[swingLookback] == ta.lowest(low, swingWindow)

var float recentSwingHigh = na
var float recentSwingLow = na
var float previousSwingLow = na

if swingHighNow
    recentSwingHigh := high[swingLookback]
if swingLowNow
    previousSwingLow := recentSwingLow
    recentSwingLow := low[swingLookback]

smcFvgBearish = low[2] > high
smcOrderBlockBearish = close[1] > open[1] and close < open and (open - close) > (close[1] - open[1])  // flagged one bar later than the Python engine - see docstring point 3
smcLiquiditySweepBearish = not na(recentSwingHigh) and high > recentSwingHigh and close < recentSwingHigh

brokeBelowRecentLow = not na(recentSwingLow) and close < recentSwingLow
freshBreakLow = brokeBelowRecentLow and not brokeBelowRecentLow[1]
wasDowntrend = not na(previousSwingLow) and recentSwingLow <= previousSwingLow
wasUptrend = not na(previousSwingLow) and recentSwingLow > previousSwingLow
smcBosBearish = freshBreakLow and wasDowntrend
smcChochBearish = freshBreakLow and wasUptrend
"""


# ---------------------------------------------------------------------------
# condition_tree(AND/OR/NOT条件エンジン)向けのPine Script変換
# (ユーザー要望:「Trading Viewコード書いてくれる機能実装できる?」/
# 確認済み:「まずは基本的なものだけ」)。以前は condition_tree を検出すると
# 即エラーにしていたが、これが今の手動条件ビルダー・自動探索が実際に
# 使う唯一の方式なので、対応しないと本機能は事実上誰も使えなかった。
#
# 対応範囲(意図的に絞ったスコープ - ハーモニックパターンやICTのオーダー
# ブロック/FVGなど、Pineで正確に再現するには非常に複雑な検出ロジックが
# 必要なものは対象外): 価格データ(終値/始値/高値/安値/実体/前日高値/
# 前日安値/前日レンジ中央値/直近高値/直近安値)、基本インジケーター
# (EMA/SMA/RSI/ATR/MACD/ボリンジャーバンド/ストキャスティクス/ADX/+DI/-DI)、
# 基本的なローソク足パターン(陽線/陰線/十字線/丸坊主/包み足/Inside Bar/
# Outside Bar/ギャップ)。対応表にない指標が条件ツリーに含まれる場合は、
# 生成前にどの指標が未対応かを明示するエラーを出す(黙って無視/誤った
# コードを生成するのが最悪なので、既存のcondition_tree拒否と同じ思想)。
# ---------------------------------------------------------------------------


def _pine_num(value: float) -> str:
    """Pine整数リテラルは末尾に.0を付けない - int値はintのまま出す。"""
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


# indicator id -> (is_boolean_pattern, builder)
# builder(suffix, params) -> (decl_lines: list[str], final_var_or_expr: str)
def _b_price(field: str):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        return [], field

    return _builder


def _b_candle_body(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    var = f"candleBody{suffix}"
    return [f"{var} = close - open"], var


def _b_prev_day_high(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    return [], "prevDayHigh"


def _b_prev_day_low(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    return [], "prevDayLow"


def _b_prev_day_mid(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    var = f"prevDayMid{suffix}"
    return [f"{var} = (prevDayHigh + prevDayLow) / 2"], var


def _b_highest_high(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    var = f"highestHigh{suffix}"
    return [f"{var} = ta.highest(high[1], {length})"], var


def _b_lowest_low(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    var = f"lowestLow{suffix}"
    return [f"{var} = ta.lowest(low[1], {length})"], var


def _b_ema(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 200))
    var = f"ema{suffix}"
    return [f"{var} = ta.ema(close, {length})"], var


def _b_sma(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 200))
    var = f"sma{suffix}"
    return [f"{var} = ta.sma(close, {length})"], var


def _b_rsi(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    # ta.rsi()はWilderスムージングでTradingView組み込みRSIと一致(検証済み、
    # engine/backtest_engine.py::rsi()参照) - 期間を問わず成り立つ。
    length = int(params.get("length", 14))
    var = f"rsi{suffix}"
    return [f"{var} = ta.rsi(close, {length})"], var


def _b_atr(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 14))
    var = f"atr{suffix}"
    return [f"{var} = ta.rma(ta.tr(true), {length})"], var


_PINE_SOURCE_VARS = ("close", "open", "high", "low", "hl2", "hlc3", "ohlc4")


def _b_bollinger(band: str):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        period = int(params.get("period", 20))
        num_std = float(params.get("num_std", 2.0))
        source = str(params.get("source", "close"))
        if source not in _PINE_SOURCE_VARS:
            raise ValueError(f"未対応のsourceです(Pine変換): {source}")
        # Pineの組み込み変数(close/open/high/low/hl2/hlc3/ohlc4)の名前が
        # engine/conditions.py::_PRICE_SOURCESのキーとそのまま一致するため、
        # 変換テーブル不要でsource文字列をそのままPine変数名として使える。
        basis = f"bbBasis{suffix}"
        dev = f"bbDev{suffix}"
        lines = [f"{basis} = ta.sma({source}, {period})", f"{dev} = {_pine_num(num_std)} * ta.stdev({source}, {period})"]
        if band == "upper":
            var = f"bbUpper{suffix}"
            lines.append(f"{var} = {basis} + {dev}")
        elif band == "lower":
            var = f"bbLower{suffix}"
            lines.append(f"{var} = {basis} - {dev}")
        else:
            var = basis
        return lines, var

    return _builder


def _b_macd_line(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    var = f"macdLine{suffix}"
    return [f"{var} = ta.ema(close, {fast}) - ta.ema(close, {slow})"], var


def _b_macd_signal(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    line_var = f"macdLineFor{suffix}"
    var = f"macdSignal{suffix}"
    return [
        f"{line_var} = ta.ema(close, {fast}) - ta.ema(close, {slow})",
        f"{var} = ta.ema({line_var}, {signal})",
    ], var


def _b_stochastic_k(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    k_period = int(params.get("k_period", 14))
    smooth = int(params.get("smooth", 3))
    ll = f"stochLL{suffix}"
    hh = f"stochHH{suffix}"
    raw = f"stochRawK{suffix}"
    var = f"stochK{suffix}"
    return [
        f"{ll} = ta.lowest(low, {k_period})",
        f"{hh} = ta.highest(high, {k_period})",
        f"{raw} = 100 * (close - {ll}) / ({hh} - {ll})",
        f"{var} = ta.sma({raw}, {smooth})",
    ], var


def _b_stochastic_d(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    k_period = int(params.get("k_period", 14))
    smooth = int(params.get("smooth", 3))
    d_period = int(params.get("d_period", 3))
    ll = f"stochLL{suffix}"
    hh = f"stochHH{suffix}"
    raw = f"stochRawK{suffix}"
    k_var = f"stochKFor{suffix}"
    var = f"stochD{suffix}"
    return [
        f"{ll} = ta.lowest(low, {k_period})",
        f"{hh} = ta.highest(high, {k_period})",
        f"{raw} = 100 * (close - {ll}) / ({hh} - {ll})",
        f"{k_var} = ta.sma({raw}, {smooth})",
        f"{var} = ta.sma({k_var}, {d_period})",
    ], var


def _b_dmi(which: str):
    # ADX/+DI/-DIは3つとも同じ平滑化(RMA)された±DM/TRから作るので、同じ
    # 中間変数を毎回再宣言している(条件ツリー内で3つ同時に使われる時の
    # 重複はPineコンパイラが未使用行を許容するので実害なし、シンプルさ優先)。
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        length = int(params.get("length", 14))
        up = f"dmiUp{suffix}"
        down = f"dmiDown{suffix}"
        plus_dm = f"dmiPlusDM{suffix}"
        minus_dm = f"dmiMinusDM{suffix}"
        tr = f"dmiTR{suffix}"
        s_plus_dm = f"dmiSPlusDM{suffix}"
        s_minus_dm = f"dmiSMinusDM{suffix}"
        plus_di = f"dmiPlusDI{suffix}"
        minus_di = f"dmiMinusDI{suffix}"
        lines = [
            f"{up} = ta.change(high)",
            f"{down} = -ta.change(low)",
            f"{plus_dm} = ({up} > {down} and {up} > 0) ? {up} : 0.0",
            f"{minus_dm} = ({down} > {up} and {down} > 0) ? {down} : 0.0",
            f"{tr} = ta.rma(ta.tr(true), {length})",
            f"{s_plus_dm} = ta.rma({plus_dm}, {length})",
            f"{s_minus_dm} = ta.rma({minus_dm}, {length})",
            f"{plus_di} = 100 * {s_plus_dm} / {tr}",
            f"{minus_di} = 100 * {s_minus_dm} / {tr}",
        ]
        if which == "adx":
            dx = f"dmiDX{suffix}"
            var = f"adx{suffix}"
            lines.append(f"{dx} = 100 * math.abs({plus_di} - {minus_di}) / ({plus_di} + {minus_di})")
            lines.append(f"{var} = ta.rma({dx}, {length})")
        elif which == "plus_di":
            var = plus_di
        else:
            var = minus_di
        return lines, var

    return _builder


def _b_bool(expr_template: str):
    """expr_templateは既に完成したPine真偽式(closeなど生の変数のみ参照)。"""

    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"pattern{suffix}"
        return [f"{var} = {expr_template}"], var

    return _builder


def _b_doji(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    threshold = float(params.get("body_ratio_threshold", 0.1))
    var = f"doji{suffix}"
    return [f"{var} = (math.abs(close - open) / (high - low)) < {_pine_num(threshold)}"], var


def _b_marubozu(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        threshold = float(params.get("body_ratio_threshold", 0.95))
        direction_expr = "close > open" if bullish else "close < open"
        var = f"marubozu{suffix}"
        return [
            f"{var} = ({direction_expr}) and ((math.abs(close - open) / (high - low)) >= {_pine_num(threshold)})"
        ], var

    return _builder


def _b_hour(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    # tzHourはスクリプト冒頭で宣言済みのグローバル変数(TIMEZONE基準の現地時)。
    return [], "tzHour"


def _b_weekday(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    # Pineのdayofweek(time, tz)はSunday=1...Saturday=7。engine/conditions.py
    # の"weekday"(pandasのdt.weekday: Monday=0...Sunday=6)に合わせて変換する。
    var = f"weekday{suffix}"
    return [f"{var} = (tzDow + 5) % 7"], var


def _b_month(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    var = f"month{suffix}"
    return [f'{var} = month(time, "{TIMEZONE}")'], var


def _b_killzone(start: int, end: int, tz: str | None):
    # tz=Noneはengine/conditions.py::_killzone_asianと同じくJST(=TIMEZONE、
    # 冒頭で宣言済みのtzHourをそのまま使う) - 4プリセットいずれも深夜を
    # またがない範囲なので単純な範囲判定でよい。
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        if tz is None:
            hour_expr = "tzHour"
            lines: list[str] = []
        else:
            hour_var = f"kzHour{suffix}"
            lines = [f'{hour_var} = hour(time, "{tz}")']
            hour_expr = hour_var
        var = f"killzone{suffix}"
        lines.append(f"{var} = ({hour_expr} >= {start}) and ({hour_expr} < {end})")
        return lines, var

    return _builder


def _b_minutes_since_open(tz: str, open_hour: int):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"minutesSince{suffix}"
        return [
            f'{var} = (hour(time, "{tz}") * 60 + minute(time, "{tz}")) - {open_hour * 60}'
        ], var

    return _builder


# ---------------------------------------------------------------------------
# 以下、indicatorカテゴリ(183件)のPine変換用builder群。engine/derived_
# indicators.py・engine/technical_indicators.py・engine/conditions.pyの
# 各実装を1件ずつPineへ移植したもの - パラメータ名/既定値はすべて元の
# Python関数のシグネチャと一致させてある。
# ---------------------------------------------------------------------------


def _b_global(var_name: str):
    """daily_levels_block(生成スクリプト冒頭で1回だけ計算)で既に宣言済みの
    グローバル変数をそのまま参照する(prevDayHigh/prevDayLowと同じ規則)。"""

    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        return [], var_name

    return _builder


def _b_vwap(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    # engine/technical_indicators.py::daily_vwap()と同じ「暦日リセット・
    # typical price(hlc3)加重」定義 - Pine組み込みのta.vwap()もセッション
    # 開始(暦日境界)でリセットされる同じ考え方なので採用(MACD/SuperTrend
    # と違い内部規約が単一・曖昧さが無いため)。
    return [], "ta.vwap(hlc3)"


def _b_obv(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    # ta.obv: 終値が前バーより高い/低い/同値でvolumeを加算/減算/据え置く
    # 標準OBV定義そのもの(engine/technical_indicators.py::on_balance_volume
    # と同一・曖昧さの無い業界標準式なので組み込みをそのまま採用)。
    return [], "ta.obv"


def _b_mfi(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    period = int(params.get("period", 14))
    var = f"mfi{suffix}"
    return [f"{var} = ta.mfi(hlc3, {period})"], var


def _b_ad_line(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    mfm = f"adMfm{suffix}"
    var = f"adLine{suffix}"
    return [
        f"{mfm} = (high == low) ? 0.0 : (((close - low) - (high - close)) / (high - low))",
        f"{var} = ta.cum({mfm} * volume)",
    ], var


def _b_cmf(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    period = int(params.get("period", 20))
    mfm = f"cmfMfm{suffix}"
    vol_sum = f"cmfVolSum{suffix}"
    var = f"cmf{suffix}"
    return [
        f"{mfm} = (high == low) ? 0.0 : (((close - low) - (high - close)) / (high - low))",
        f"{vol_sum} = math.sum(volume, {period})",
        f"{var} = {vol_sum} == 0 ? 0.0 : math.sum({mfm} * volume, {period}) / {vol_sum}",
    ], var


def _b_supertrend_state(suffix: str, params: dict[str, Any]) -> tuple[list[str], str, str]:
    """SuperTrendの再帰計算(既存の凡例テンプレート内の手動翻訳と同じロジック
    - engine/technical_indicators.py::supertrend()参照)。line用/direction用
    両方の呼び出し元がこれを共有し、(decl_lines, line_var, direction_var)を返す。"""
    length = int(params.get("length", 10))
    multiplier = float(params.get("multiplier", 3.0))
    atr_v = f"stAtr{suffix}"
    hl2_v = f"stHl2{suffix}"
    basic_upper = f"stBasicUpper{suffix}"
    basic_lower = f"stBasicLower{suffix}"
    final_upper = f"stFinalUpper{suffix}"
    final_lower = f"stFinalLower{suffix}"
    direction = f"stDirection{suffix}"
    prev_final_upper = f"stPrevFinalUpper{suffix}"
    prev_final_lower = f"stPrevFinalLower{suffix}"
    line_var = f"stLine{suffix}"
    lines = [
        f"{atr_v} = ta.rma(ta.tr(true), {length})",
        f"{hl2_v} = (high + low) / 2",
        f"{basic_upper} = {hl2_v} + {_pine_num(multiplier)} * {atr_v}",
        f"{basic_lower} = {hl2_v} - {_pine_num(multiplier)} * {atr_v}",
        f"var float {final_upper} = na",
        f"var float {final_lower} = na",
        f"var int {direction} = -1",
        f"{prev_final_upper} = {final_upper}",
        f"{prev_final_lower} = {final_lower}",
        f"{final_upper} := (na({prev_final_upper}) or {basic_upper} < {prev_final_upper} or close[1] > {prev_final_upper}) ? {basic_upper} : {prev_final_upper}",
        f"{final_lower} := (na({prev_final_lower}) or {basic_lower} > {prev_final_lower} or close[1] < {prev_final_lower}) ? {basic_lower} : {prev_final_lower}",
        f"if {direction} == -1 and close > {prev_final_upper}",
        f"    {direction} := 1",
        f"else if {direction} == 1 and close < {prev_final_lower}",
        f"    {direction} := -1",
        f"{line_var} = {direction} == 1 ? {final_lower} : {final_upper}",
    ]
    return lines, line_var, direction


def _b_supertrend_line(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, line_var, _direction = _b_supertrend_state(suffix, params)
    return lines, line_var


def _b_supertrend_direction(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, _line_var, direction = _b_supertrend_state(suffix, params)
    return lines, direction


def _b_supertrend_flip(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, _line_var, direction = _b_supertrend_state(suffix, params)
        var = f"stFlip{suffix}"
        if bullish:
            lines = lines + [f"{var} = ({direction} == 1) and ({direction}[1] == -1)"]
        else:
            lines = lines + [f"{var} = ({direction} == -1) and ({direction}[1] == 1)"]
        return lines, var

    return _builder


def _b_parabolic_sar_line(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    # engine/technical_indicators.py::parabolic_sar()と同じ標準Wilder式
    # (af_start/af_step/af_maxのパラメータ規約も同一)なので、内部規約が
    # 曖昧な他の組み込み(supertrend/dmi等)と違いta.sar()をそのまま採用。
    af_start = float(params.get("af_start", 0.02))
    af_step = float(params.get("af_step", 0.02))
    af_max = float(params.get("af_max", 0.2))
    var = f"sar{suffix}"
    return [f"{var} = ta.sar({_pine_num(af_start)}, {_pine_num(af_step)}, {_pine_num(af_max)})"], var


def _b_parabolic_sar_direction(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, sar_var = _b_parabolic_sar_line(suffix, params)
    var = f"sarDir{suffix}"
    lines = lines + [f"{var} = close > {sar_var} ? 1 : -1"]
    return lines, var


def _b_cci(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    period = int(params.get("period", 20))
    mean_v = f"cciMean{suffix}"
    dev_v = f"cciDev{suffix}"
    var = f"cci{suffix}"
    return [
        f"{mean_v} = ta.sma(hlc3, {period})",
        f"{dev_v} = ta.dev(hlc3, {period})",
        f"{var} = (hlc3 - {mean_v}) / (0.015 * {dev_v})",
    ], var


def _b_williams_r(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    period = int(params.get("period", 14))
    hh = f"wprHH{suffix}"
    ll = f"wprLL{suffix}"
    var = f"wpr{suffix}"
    return [
        f"{hh} = ta.highest(high, {period})",
        f"{ll} = ta.lowest(low, {period})",
        f"{var} = -100 * ({hh} - close) / ({hh} - {ll})",
    ], var


def _b_choppiness_index(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    period = int(params.get("period", 14))
    tr_v = f"chopTr{suffix}"
    sum_tr = f"chopSumTr{suffix}"
    rng = f"chopRange{suffix}"
    var = f"chop{suffix}"
    return [
        f"{tr_v} = ta.tr(true)",
        f"{sum_tr} = math.sum({tr_v}, {period})",
        f"{rng} = ta.highest(high, {period}) - ta.lowest(low, {period})",
        f"{var} = 100 * math.log10({sum_tr} / {rng}) / math.log10({period})",
    ], var


def _b_aroon(which: str):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        period = int(params.get("period", 14))
        hh_bars = f"aroonHHBars{suffix}"
        ll_bars = f"aroonLLBars{suffix}"
        up_var = f"aroonUp{suffix}"
        down_var = f"aroonDown{suffix}"
        lines = [
            f"{hh_bars} = ta.highestbars(high, {period + 1})",
            f"{ll_bars} = ta.lowestbars(low, {period + 1})",
            f"{up_var} = 100 * ({period} + {hh_bars}) / {period}",
            f"{down_var} = 100 * ({period} + {ll_bars}) / {period}",
        ]
        if which == "up":
            var = up_var
        elif which == "down":
            var = down_var
        else:
            var = f"aroonOsc{suffix}"
            lines.append(f"{var} = {up_var} - {down_var}")
        return lines, var

    return _builder


def _b_keltner(band: str):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        period = int(params.get("period", 20))
        atr_period = int(params.get("atr_period", 10))
        multiplier = float(params.get("multiplier", 2.0))
        mid = f"kcMiddle{suffix}"
        atr_v = f"kcAtr{suffix}"
        lines = [
            f"{mid} = ta.ema(close, {period})",
            f"{atr_v} = ta.rma(ta.tr(true), {atr_period})",
        ]
        if band == "upper":
            var = f"kcUpper{suffix}"
            lines.append(f"{var} = {mid} + {_pine_num(multiplier)} * {atr_v}")
        elif band == "lower":
            var = f"kcLower{suffix}"
            lines.append(f"{var} = {mid} - {_pine_num(multiplier)} * {atr_v}")
        else:
            var = mid
        return lines, var

    return _builder


def _b_donchian_mid(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    hh = f"donchHH{suffix}"
    ll = f"donchLL{suffix}"
    var = f"donchMid{suffix}"
    return [
        f"{hh} = ta.highest(high[1], {length})",
        f"{ll} = ta.lowest(low[1], {length})",
        f"{var} = ({hh} + {ll}) / 2",
    ], var


def _b_donchian_percent_position(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    hh = f"donchPosHH{suffix}"
    ll = f"donchPosLL{suffix}"
    var = f"donchPos{suffix}"
    return [
        f"{hh} = ta.highest(high[1], {length})",
        f"{ll} = ta.lowest(low[1], {length})",
        f"{var} = (close - {ll}) / ({hh} - {ll})",
    ], var


def _b_highest_close(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    var = f"highestClose{suffix}"
    return [f"{var} = ta.highest(close[1], {length})"], var


def _b_lowest_close(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    var = f"lowestClose{suffix}"
    return [f"{var} = ta.lowest(close[1], {length})"], var


def _b_fib_level(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    ratio = float(params.get("ratio", 0.618))
    hh_lines, hh_var = _b_highest_high(suffix, params)
    ll_lines, ll_var = _b_lowest_low(suffix, params)
    var = f"fibLevel{suffix}"
    lines = hh_lines + ll_lines + [f"{var} = {hh_var} - {_pine_num(ratio)} * ({hh_var} - {ll_var})"]
    return lines, var


def _b_dist_to_fib(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, level_var = _b_fib_level(suffix, params)
    var = f"distFib{suffix}"
    lines = lines + [f"{var} = math.abs(close - {level_var})"]
    return lines, var


def _b_bb_percent_b(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    period = int(params.get("period", 20))
    num_std = float(params.get("num_std", 2.0))
    basis = f"bbpbBasis{suffix}"
    dev = f"bbpbDev{suffix}"
    upper = f"bbpbUpper{suffix}"
    lower = f"bbpbLower{suffix}"
    var = f"bbPercentB{suffix}"
    return [
        f"{basis} = ta.sma(close, {period})",
        f"{dev} = {_pine_num(num_std)} * ta.stdev(close, {period})",
        f"{upper} = {basis} + {dev}",
        f"{lower} = {basis} - {dev}",
        f"{var} = (close - {lower}) / ({upper} - {lower})",
    ], var


def _b_bb_width(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    period = int(params.get("period", 20))
    num_std = float(params.get("num_std", 2.0))
    basis = f"bbwBasis{suffix}"
    dev = f"bbwDev{suffix}"
    upper = f"bbwUpper{suffix}"
    lower = f"bbwLower{suffix}"
    var = f"bbWidth{suffix}"
    return [
        f"{basis} = ta.sma(close, {period})",
        f"{dev} = {_pine_num(num_std)} * ta.stdev(close, {period})",
        f"{upper} = {basis} + {dev}",
        f"{lower} = {basis} - {dev}",
        f"{var} = ({upper} - {lower}) / {basis}",
    ], var


def _b_bb_width_percent(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, width_var = _b_bb_width(suffix, params)
    var = f"bbWidthPct{suffix}"
    lines = lines + [f"{var} = {width_var} * 100"]
    return lines, var


def _b_bb_squeeze(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    window = int(params.get("window", 100))
    percentile = float(params.get("percentile", 10.0))
    lines, width_var = _b_bb_width(suffix, params)
    rank_var = f"bbSqueezeRank{suffix}"
    var = f"bbSqueeze{suffix}"
    lines = lines + [
        f"{rank_var} = ta.percentrank({width_var}, {window})",
        f"{var} = {rank_var} <= {_pine_num(percentile)}",
    ]
    return lines, var


def _b_bb_expansion(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    window = int(params.get("window", 100))
    percentile = float(params.get("percentile", 10.0))
    lines, width_var = _b_bb_width(suffix, params)
    rank_var = f"bbExpRank{suffix}"
    var = f"bbExpansion{suffix}"
    lines = lines + [
        f"{rank_var} = ta.percentrank({width_var}, {window})",
        f"{var} = ({rank_var}[1] <= {_pine_num(percentile)}) and ({width_var} > {width_var}[1])",
    ]
    return lines, var


def _b_dist_to_ema_atr_ratio(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    ema_length = int(params.get("ema_length", 200))
    atr_length = int(params.get("atr_length", 14))
    ema_v = f"dtearEma{suffix}"
    atr_v = f"dtearAtr{suffix}"
    var = f"dtear{suffix}"
    return [
        f"{ema_v} = ta.ema(close, {ema_length})",
        f"{atr_v} = ta.rma(ta.tr(true), {atr_length})",
        f"{var} = math.abs(close - {ema_v}) / {atr_v}",
    ], var


def _b_dist_close_ema_pct(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 200))
    ema_v = f"dcepEma{suffix}"
    var = f"dcep{suffix}"
    return [
        f"{ema_v} = ta.ema(close, {length})",
        f"{var} = math.abs(close - {ema_v}) / close * 100",
    ], var


def _b_adr(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    """engine/technical_indicators.py::daily_reference_levels()のadr列
    (直近adr_period本の「完成した日足」レンジの平均、前日までを対象に
    翌日の全バーへ配布)と同じJST午前0時境界を、daily_levels_blockの
    prevDayHigh/Lowと同じ自前の暦日切り替わり検出で再現する - request.
    security(..., "D", ...)を使うとTradingView自身の日足セッション
    (JST0時と一致するとは限らない)になってしまうため。"""
    period = int(params.get("adr_period", 14))
    new_day = f"adrNewDay{suffix}"
    high_acc = f"adrHighAcc{suffix}"
    low_acc = f"adrLowAcc{suffix}"
    ranges_arr = f"adrRanges{suffix}"
    var = f"adr{suffix}"
    return [
        f'{new_day} = ta.change(dayofmonth(time, "{TIMEZONE}")) != 0',
        f"var float {high_acc} = na",
        f"var float {low_acc} = na",
        f"var array<float> {ranges_arr} = array.new<float>(0)",
        f"if {new_day}",
        f"    if not na({high_acc})",
        f"        array.push({ranges_arr}, {high_acc} - {low_acc})",
        f"    if array.size({ranges_arr}) > {period}",
        f"        array.shift({ranges_arr})",
        f"    {high_acc} := high",
        f"    {low_acc} := low",
        f"else",
        f"    {high_acc} := math.max(nz({high_acc}, high), high)",
        f"    {low_acc} := math.min(nz({low_acc}, low), low)",
        f"{var} = array.size({ranges_arr}) > 0 ? array.avg({ranges_arr}) : na",
    ], var


_DISTANCE_TARGET_BUILDERS: dict[str, Any] = {
    "ema": _b_ema,
    "sma": _b_sma,
    "vwap": _b_vwap,
    "supertrend": _b_supertrend_line,
    "pivot": _b_global("pivot"),
    "prev_day_high": _b_prev_day_high,
    "prev_day_low": _b_prev_day_low,
    "donchian_upper": _b_highest_high,
    "donchian_lower": _b_lowest_low,
    "bb_upper": _b_bollinger("upper"),
    "bb_lower": _b_bollinger("lower"),
}


def _b_distance(price_field: str, target_name: str):
    target_builder = _DISTANCE_TARGET_BUILDERS[target_name]

    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, target_var = target_builder(suffix, params)
        var = f"dist{suffix}"
        lines = list(lines) + [f"{var} = math.abs({price_field} - {target_var})"]
        return lines, var

    return _builder


def _b_rolling_mean_high(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    var = f"rmHigh{suffix}"
    return [f"{var} = ta.sma(high, {length})"], var


def _b_rolling_mean_low(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    var = f"rmLow{suffix}"
    return [f"{var} = ta.sma(low, {length})"], var


def _b_atr_rolling_mean(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    atr_length = int(params.get("atr_length", 14))
    window = int(params.get("window", 20))
    atr_v = f"armAtr{suffix}"
    var = f"arm{suffix}"
    return [
        f"{atr_v} = ta.rma(ta.tr(true), {atr_length})",
        f"{var} = ta.sma({atr_v}, {window})",
    ], var


def _b_atr_deviation(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    atr_length = int(params.get("atr_length", 14))
    window = int(params.get("window", 20))
    atr_v = f"adevAtr{suffix}"
    mean_v = f"adevMean{suffix}"
    var = f"adev{suffix}"
    return [
        f"{atr_v} = ta.rma(ta.tr(true), {atr_length})",
        f"{mean_v} = ta.sma({atr_v}, {window})",
        f"{var} = {atr_v} - {mean_v}",
    ], var


def _b_close_rolling_std(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    var = f"crStd{suffix}"
    return [f"{var} = ta.stdev(close, {length})"], var


def _b_historical_volatility(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    period = int(params.get("period", 20))
    annualization_factor = float(params.get("annualization_factor", 252.0))
    log_ret = f"hvLogRet{suffix}"
    std_v = f"hvStd{suffix}"
    var = f"hv{suffix}"
    return [
        f"{log_ret} = math.log(close / close[1])",
        f"{std_v} = ta.stdev({log_ret}, {period})",
        f"{var} = {std_v} * math.sqrt({_pine_num(annualization_factor)}) * 100",
    ], var


def _b_rsi_rolling_mean(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    rsi_length = int(params.get("rsi_length", 14))
    window = int(params.get("window", 20))
    rsi_v = f"rrmRsi{suffix}"
    var = f"rrm{suffix}"
    return [f"{rsi_v} = ta.rsi(close, {rsi_length})", f"{var} = ta.sma({rsi_v}, {window})"], var


def _b_rsi_deviation(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    rsi_length = int(params.get("rsi_length", 14))
    window = int(params.get("window", 20))
    rsi_v = f"rdevRsi{suffix}"
    mean_v = f"rdevMean{suffix}"
    var = f"rdev{suffix}"
    return [
        f"{rsi_v} = ta.rsi(close, {rsi_length})",
        f"{mean_v} = ta.sma({rsi_v}, {window})",
        f"{var} = {rsi_v} - {mean_v}",
    ], var


def _b_adx_rolling_mean(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    adx_length = int(params.get("adx_length", 14))
    window = int(params.get("window", 20))
    up = f"armxUp{suffix}"
    down = f"armxDown{suffix}"
    plus_dm = f"armxPlusDM{suffix}"
    minus_dm = f"armxMinusDM{suffix}"
    tr = f"armxTR{suffix}"
    s_plus_dm = f"armxSPlusDM{suffix}"
    s_minus_dm = f"armxSMinusDM{suffix}"
    plus_di = f"armxPlusDI{suffix}"
    minus_di = f"armxMinusDI{suffix}"
    dx = f"armxDX{suffix}"
    adx_v = f"armxADX{suffix}"
    var = f"arm{suffix}"
    return [
        f"{up} = ta.change(high)",
        f"{down} = -ta.change(low)",
        f"{plus_dm} = ({up} > {down} and {up} > 0) ? {up} : 0.0",
        f"{minus_dm} = ({down} > {up} and {down} > 0) ? {down} : 0.0",
        f"{tr} = ta.rma(ta.tr(true), {adx_length})",
        f"{s_plus_dm} = ta.rma({plus_dm}, {adx_length})",
        f"{s_minus_dm} = ta.rma({minus_dm}, {adx_length})",
        f"{plus_di} = 100 * {s_plus_dm} / {tr}",
        f"{minus_di} = 100 * {s_minus_dm} / {tr}",
        f"{dx} = 100 * math.abs({plus_di} - {minus_di}) / ({plus_di} + {minus_di})",
        f"{adx_v} = ta.rma({dx}, {adx_length})",
        f"{var} = ta.sma({adx_v}, {window})",
    ], var


def _b_macd_rolling_mean(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    window = int(params.get("window", 20))
    macd_v = f"mrmMacd{suffix}"
    var = f"mrm{suffix}"
    return [
        f"{macd_v} = ta.ema(close, 12) - ta.ema(close, 26)",
        f"{var} = ta.sma({macd_v}, {window})",
    ], var


def _b_percentile_rank_rsi(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    rsi_length = int(params.get("rsi_length", 14))
    window = int(params.get("window", 100))
    rsi_v = f"prRsi{suffix}"
    var = f"prRsiRank{suffix}"
    return [f"{rsi_v} = ta.rsi(close, {rsi_length})", f"{var} = ta.percentrank({rsi_v}, {window})"], var


def _b_percentile_rank_atr(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    atr_length = int(params.get("atr_length", 14))
    window = int(params.get("window", 200))
    atr_v = f"prAtr{suffix}"
    var = f"prAtrRank{suffix}"
    return [f"{atr_v} = ta.rma(ta.tr(true), {atr_length})", f"{var} = ta.percentrank({atr_v}, {window})"], var


def _b_zscore(base_kind: str):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        window = int(params.get("window", 20))
        if base_kind == "close":
            source_expr = "close"
            lines: list[str] = []
        elif base_kind == "rsi":
            rsi_length = int(params.get("rsi_length", 14))
            source_expr = f"zsRsi{suffix}"
            lines = [f"{source_expr} = ta.rsi(close, {rsi_length})"]
        else:
            atr_length = int(params.get("atr_length", 14))
            source_expr = f"zsAtr{suffix}"
            lines = [f"{source_expr} = ta.rma(ta.tr(true), {atr_length})"]
        mean_v = f"zsMean{suffix}"
        std_v = f"zsStd{suffix}"
        var = f"zscore{suffix}"
        lines = lines + [
            f"{mean_v} = ta.sma({source_expr}, {window})",
            f"{std_v} = ta.stdev({source_expr}, {window})",
            f"{var} = ({source_expr} - {mean_v}) / {std_v}",
        ]
        return lines, var

    return _builder


def _b_is_max_rsi_of_n(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    rsi_length = int(params.get("rsi_length", 14))
    window = int(params.get("window", 200))
    rsi_v = f"imrRsi{suffix}"
    max_v = f"imrMax{suffix}"
    var = f"imr{suffix}"
    return [
        f"{rsi_v} = ta.rsi(close, {rsi_length})",
        f"{max_v} = ta.highest({rsi_v}, {window})",
        f"{var} = {rsi_v} == {max_v}",
    ], var


def _b_is_min_atr_of_n(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    atr_length = int(params.get("atr_length", 14))
    window = int(params.get("window", 50))
    atr_v = f"imaAtr{suffix}"
    min_v = f"imaMin{suffix}"
    var = f"ima{suffix}"
    return [
        f"{atr_v} = ta.rma(ta.tr(true), {atr_length})",
        f"{min_v} = ta.lowest({atr_v}, {window})",
        f"{var} = {atr_v} == {min_v}",
    ], var


def _b_ema_roc(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 200))
    lookback = int(params.get("lookback", 5))
    ema_v = f"erocEma{suffix}"
    var = f"eroc{suffix}"
    return [
        f"{ema_v} = ta.ema(close, {length})",
        f"{var} = ({ema_v} - {ema_v}[{lookback}]) / math.abs({ema_v}[{lookback}]) * 100",
    ], var


def _b_ema_slope(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 200))
    lookback = int(params.get("lookback", 5))
    ema_v = f"eslEma{suffix}"
    var = f"esl{suffix}"
    return [
        f"{ema_v} = ta.ema(close, {length})",
        f"{var} = {ema_v} - {ema_v}[{lookback}]",
    ], var


def _b_ema_slope_degrees(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 200))
    lookback = int(params.get("lookback", 5))
    ema_v = f"esdEma{suffix}"
    atr_v = f"esdAtr{suffix}"
    norm_v = f"esdNorm{suffix}"
    var = f"esd{suffix}"
    return [
        f"{ema_v} = ta.ema(close, {length})",
        f"{atr_v} = ta.rma(ta.tr(true), 14)",
        f"{norm_v} = ({ema_v} - {ema_v}[{lookback}]) / ({atr_v} * {lookback})",
        f"{var} = math.todegrees(math.atan({norm_v}))",
    ], var


def _b_atr_roc(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 14))
    lookback = int(params.get("lookback", 1))
    atr_v = f"arocAtr{suffix}"
    var = f"aroc{suffix}"
    return [
        f"{atr_v} = ta.rma(ta.tr(true), {length})",
        f"{var} = ({atr_v} - {atr_v}[{lookback}]) / math.abs({atr_v}[{lookback}]) * 100",
    ], var


def _b_ema_perfect_order(bullish: bool, broken: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        l1 = int(params.get("length_1", 20))
        l2 = int(params.get("length_2", 50))
        l3 = int(params.get("length_3", 100))
        l4 = int(params.get("length_4", 200))
        e1 = f"epoE1_{suffix}"
        e2 = f"epoE2_{suffix}"
        e3 = f"epoE3_{suffix}"
        e4 = f"epoE4_{suffix}"
        state = f"epoState{suffix}"
        lines = [
            f"{e1} = ta.ema(close, {l1})",
            f"{e2} = ta.ema(close, {l2})",
            f"{e3} = ta.ema(close, {l3})",
            f"{e4} = ta.ema(close, {l4})",
        ]
        if bullish:
            lines.append(f"{state} = ({e1} > {e2}) and ({e2} > {e3}) and ({e3} > {e4})")
        else:
            lines.append(f"{state} = ({e1} < {e2}) and ({e2} < {e3}) and ({e3} < {e4})")
        if broken:
            var = f"epo{suffix}"
            lines.append(f"{var} = ({state}[1]) and (not {state})")
        else:
            var = state
        return lines, var

    return _builder


def _b_bull_power(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 13))
    ema_v = f"bpEma{suffix}"
    var = f"bullPower{suffix}"
    return [f"{ema_v} = ta.ema(close, {length})", f"{var} = high - {ema_v}"], var


def _b_bear_power(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 13))
    ema_v = f"bearpEma{suffix}"
    var = f"bearPower{suffix}"
    return [f"{ema_v} = ta.ema(close, {length})", f"{var} = low - {ema_v}"], var


def _b_chaikin_oscillator(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    short_length = int(params.get("short_length", 3))
    long_length = int(params.get("long_length", 10))
    lines, ad_var = _b_ad_line(suffix, params)
    short_v = f"coShort{suffix}"
    long_v = f"coLong{suffix}"
    var = f"co{suffix}"
    lines = lines + [
        f"{short_v} = ta.ema({ad_var}, {short_length})",
        f"{long_v} = ta.ema({ad_var}, {long_length})",
        f"{var} = {short_v} - {long_v}",
    ]
    return lines, var


def _b_cmo(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 14))
    delta = f"cmoDelta{suffix}"
    gain = f"cmoGain{suffix}"
    loss = f"cmoLoss{suffix}"
    sum_gain = f"cmoSumGain{suffix}"
    sum_loss = f"cmoSumLoss{suffix}"
    denom = f"cmoDenom{suffix}"
    var = f"cmo{suffix}"
    return [
        f"{delta} = ta.change(close)",
        f"{gain} = {delta} > 0 ? {delta} : 0.0",
        f"{loss} = {delta} < 0 ? -{delta} : 0.0",
        f"{sum_gain} = math.sum({gain}, {length})",
        f"{sum_loss} = math.sum({loss}, {length})",
        f"{denom} = {sum_gain} + {sum_loss}",
        f"{var} = {denom} == 0 ? 0.0 : 100 * ({sum_gain} - {sum_loss}) / {denom}",
    ], var


def _b_connors_rsi(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    rsi_length = int(params.get("rsi_length", 3))
    streak_length = int(params.get("streak_length", 2))
    percent_rank_length = int(params.get("percent_rank_length", 100))
    price_rsi = f"crsiPriceRsi{suffix}"
    streak_var = f"crsiStreak{suffix}"
    streak_rsi = f"crsiStreakRsi{suffix}"
    roc1 = f"crsiRoc1{suffix}"
    pr = f"crsiPr{suffix}"
    var = f"crsi{suffix}"
    return [
        f"{price_rsi} = ta.rsi(close, {rsi_length})",
        f"var float {streak_var} = 0.0",
        f"{streak_var} := close > close[1] ? (nz({streak_var}[1]) > 0 ? nz({streak_var}[1]) + 1 : 1) : "
        f"(close < close[1] ? (nz({streak_var}[1]) < 0 ? nz({streak_var}[1]) - 1 : -1) : 0.0)",
        f"{streak_rsi} = ta.rsi({streak_var}, {streak_length})",
        f"{roc1} = ta.change(close) / close[1] * 100",
        f"{pr} = ta.percentrank({roc1}, {percent_rank_length})",
        f"{var} = ({price_rsi} + {streak_rsi} + {pr}) / 3",
    ], var


def _b_coppock_curve(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    long_roc = int(params.get("long_roc", 14))
    short_roc = int(params.get("short_roc", 11))
    wma_length = int(params.get("wma_length", 10))
    roc_long = f"ccLongRoc{suffix}"
    roc_short = f"ccShortRoc{suffix}"
    roc_sum = f"ccRocSum{suffix}"
    var = f"coppock{suffix}"
    return [
        f"{roc_long} = ta.roc(close, {long_roc})",
        f"{roc_short} = ta.roc(close, {short_roc})",
        f"{roc_sum} = {roc_long} + {roc_short}",
        f"{var} = ta.wma({roc_sum}, {wma_length})",
    ], var


def _b_correlation_close_ema(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    ema_length = int(params.get("ema_length", 20))
    ema_v = f"cceEma{suffix}"
    var = f"cce{suffix}"
    return [
        f"{ema_v} = ta.ema(close, {ema_length})",
        f"{var} = ta.correlation(close, {ema_v}, {length})",
    ], var


def _b_correlation_oscillator(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    var = f"corrOsc{suffix}"
    return [f"{var} = ta.correlation(close, bar_index, {length})"], var


def _b_macd_histogram(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    line_v = f"mhLine{suffix}"
    sig_v = f"mhSignal{suffix}"
    var = f"mh{suffix}"
    return [
        f"{line_v} = ta.ema(close, {fast}) - ta.ema(close, {slow})",
        f"{sig_v} = ta.ema({line_v}, {signal})",
        f"{var} = {line_v} - {sig_v}",
    ], var


def _b_macd_divergence(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        length = int(params.get("length", 20))
        macd_v = f"mdMacd{suffix}"
        var = f"md{suffix}"
        lines = [f"{macd_v} = ta.ema(close, 12) - ta.ema(close, 26)"]
        if bullish:
            rolling_low = f"mdRollLow{suffix}"
            macd_low = f"mdMacdLow{suffix}"
            lines += [
                f"{rolling_low} = ta.lowest(low[1], {length})",
                f"{macd_low} = ta.lowest({macd_v}[1], {length})",
                f"{var} = (close < {rolling_low}) and ({macd_v} > {macd_low})",
            ]
        else:
            rolling_high = f"mdRollHigh{suffix}"
            macd_high = f"mdMacdHigh{suffix}"
            lines += [
                f"{rolling_high} = ta.highest(high[1], {length})",
                f"{macd_high} = ta.highest({macd_v}[1], {length})",
                f"{var} = (close > {rolling_high}) and ({macd_v} < {macd_high})",
            ]
        return lines, var

    return _builder


def _b_rsi_divergence(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        length = int(params.get("length", 20))
        rsi_length = int(params.get("rsi_length", 14))
        rsi_v = f"rdRsi{suffix}"
        var = f"rd{suffix}"
        lines = [f"{rsi_v} = ta.rsi(close, {rsi_length})"]
        if bullish:
            rolling_low = f"rdRollLow{suffix}"
            rsi_low = f"rdRsiLow{suffix}"
            lines += [
                f"{rolling_low} = ta.lowest(low[1], {length})",
                f"{rsi_low} = ta.lowest({rsi_v}[1], {length})",
                f"{var} = (close < {rolling_low}) and ({rsi_v} > {rsi_low})",
            ]
        else:
            rolling_high = f"rdRollHigh{suffix}"
            rsi_high = f"rdRsiHigh{suffix}"
            lines += [
                f"{rolling_high} = ta.highest(high[1], {length})",
                f"{rsi_high} = ta.highest({rsi_v}[1], {length})",
                f"{var} = (close > {rolling_high}) and ({rsi_v} < {rsi_high})",
            ]
        return lines, var

    return _builder


def _b_ichimoku_tenkan(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    tenkan_period = int(params.get("tenkan_period", 9))
    var = f"tenkan{suffix}"
    return [f"{var} = (ta.highest(high, {tenkan_period}) + ta.lowest(low, {tenkan_period})) / 2"], var


def _b_ichimoku_kijun(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    kijun_period = int(params.get("kijun_period", 26))
    var = f"kijun{suffix}"
    return [f"{var} = (ta.highest(high, {kijun_period}) + ta.lowest(low, {kijun_period})) / 2"], var


def _b_ichimoku_senkou(band: str):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tenkan_period = int(params.get("tenkan_period", 9))
        kijun_period = int(params.get("kijun_period", 26))
        senkou_b_period = int(params.get("senkou_b_period", 52))
        if band == "a":
            raw = f"senkouARaw{suffix}"
            var = f"senkouA{suffix}"
            lines = [
                f"{raw} = ((ta.highest(high, {tenkan_period}) + ta.lowest(low, {tenkan_period})) / 2 + "
                f"(ta.highest(high, {kijun_period}) + ta.lowest(low, {kijun_period})) / 2) / 2",
                f"{var} = {raw}[{kijun_period}]",
            ]
        else:
            raw = f"senkouBRaw{suffix}"
            var = f"senkouB{suffix}"
            lines = [
                f"{raw} = (ta.highest(high, {senkou_b_period}) + ta.lowest(low, {senkou_b_period})) / 2",
                f"{var} = {raw}[{kijun_period}]",
            ]
        return lines, var

    return _builder


def _b_ichimoku_price_vs_cloud(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    tenkan_period = int(params.get("tenkan_period", 9))
    kijun_period = int(params.get("kijun_period", 26))
    senkou_b_period = int(params.get("senkou_b_period", 52))
    a_raw = f"ipvcARaw{suffix}"
    b_raw = f"ipvcBRaw{suffix}"
    a_v = f"ipvcA{suffix}"
    b_v = f"ipvcB{suffix}"
    top = f"ipvcTop{suffix}"
    bottom = f"ipvcBottom{suffix}"
    var = f"ipvc{suffix}"
    return [
        f"{a_raw} = ((ta.highest(high, {tenkan_period}) + ta.lowest(low, {tenkan_period})) / 2 + "
        f"(ta.highest(high, {kijun_period}) + ta.lowest(low, {kijun_period})) / 2) / 2",
        f"{a_v} = {a_raw}[{kijun_period}]",
        f"{b_raw} = (ta.highest(high, {senkou_b_period}) + ta.lowest(low, {senkou_b_period})) / 2",
        f"{b_v} = {b_raw}[{kijun_period}]",
        f"{top} = math.max({a_v}, {b_v})",
        f"{bottom} = math.min({a_v}, {b_v})",
        f"{var} = close > {top} ? 1 : (close < {bottom} ? -1 : 0)",
    ], var


def _b_ichimoku_kumo_twist(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tenkan_period = int(params.get("tenkan_period", 9))
        kijun_period = int(params.get("kijun_period", 26))
        senkou_b_period = int(params.get("senkou_b_period", 52))
        a_v = f"twistA{suffix}"
        b_v = f"twistB{suffix}"
        var = f"twist{suffix}"
        lines = [
            f"{a_v} = ((ta.highest(high, {tenkan_period}) + ta.lowest(low, {tenkan_period})) / 2 + "
            f"(ta.highest(high, {kijun_period}) + ta.lowest(low, {kijun_period})) / 2) / 2",
            f"{b_v} = (ta.highest(high, {senkou_b_period}) + ta.lowest(low, {senkou_b_period})) / 2",
        ]
        if bullish:
            lines.append(f"{var} = ta.crossover({a_v}, {b_v})")
        else:
            lines.append(f"{var} = ta.crossunder({a_v}, {b_v})")
        return lines, var

    return _builder


def _b_ichimoku_chikou_signal(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    kijun_period = int(params.get("kijun_period", 26))
    var = f"chikou{suffix}"
    return [f"{var} = close > close[{kijun_period}] ? 1 : (close < close[{kijun_period}] ? -1 : 0)"], var


def _b_linreg_stats(suffix: str, params: dict[str, Any]) -> tuple[list[str], str, str]:
    """engine/derived_indicators.py::_rolling_linreg_stats()と同じ閉形式を
    Pineへ移植 - lengthはコンパイル時定数として扱えるため、sum_i/sum_i2/
    (n-1)/2はPython側で先に計算してリテラルとして埋め込む。"""
    n = int(params.get("length", 20))
    sum_y = f"lrSumY{suffix}"
    iy_global = f"lrIyGlobal{suffix}"
    sum_iy_global = f"lrSumIyGlobal{suffix}"
    window_start = f"lrWindowStart{suffix}"
    sum_iy_local = f"lrSumIyLocal{suffix}"
    slope_var = f"lrSlope{suffix}"
    fitted_var = f"lrFitted{suffix}"
    sum_i = n * (n - 1) / 2
    sum_i2 = (n - 1) * n * (2 * n - 1) / 6
    lines = [
        f"{sum_y} = math.sum(close, {n})",
        f"{iy_global} = bar_index * close",
        f"{sum_iy_global} = math.sum({iy_global}, {n})",
        f"{window_start} = bar_index - {n} + 1",
        f"{sum_iy_local} = {sum_iy_global} - {window_start} * {sum_y}",
        f"{slope_var} = ({n} * {sum_iy_local} - {_pine_num(sum_i)} * {sum_y}) / "
        f"({n} * {_pine_num(sum_i2)} - {_pine_num(sum_i ** 2)})",
        f"{fitted_var} = {sum_y} / {n} + {slope_var} * {_pine_num((n - 1) / 2)}",
    ]
    return lines, slope_var, fitted_var


def _b_linreg_value(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, _slope, fitted = _b_linreg_stats(suffix, params)
    return lines, fitted


def _b_linreg_slope_atr_ratio(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    atr_length = int(params.get("atr_length", 14))
    lines, slope, _fitted = _b_linreg_stats(suffix, params)
    atr_v = f"lrAtr{suffix}"
    var = f"lrSlopeRatio{suffix}"
    lines = lines + [
        f"{atr_v} = ta.rma(ta.tr(true), {atr_length})",
        f"{var} = {slope} / {atr_v}",
    ]
    return lines, var


def _b_linreg_angle_degrees(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    atr_length = int(params.get("atr_length", 14))
    lines, slope, _fitted = _b_linreg_stats(suffix, params)
    atr_v = f"lrAtrDeg{suffix}"
    norm_v = f"lrNorm{suffix}"
    var = f"lrAngle{suffix}"
    lines = lines + [
        f"{atr_v} = ta.rma(ta.tr(true), {atr_length})",
        f"{norm_v} = {slope} / {atr_v}",
        f"{var} = math.todegrees(math.atan({norm_v}))",
    ]
    return lines, var


def _b_linreg_band(sign: float):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        num_std = float(params.get("num_std", 2.0))
        length = int(params.get("length", 20))
        lines, _slope, fitted = _b_linreg_stats(suffix, params)
        std_v = f"lrStd{suffix}"
        var = f"lrBand{suffix}"
        lines = lines + [
            f"{std_v} = ta.stdev(close, {length})",
            f"{var} = {fitted} + {_pine_num(sign)} * {_pine_num(num_std)} * {std_v}",
        ]
        return lines, var

    return _builder


def _b_ttm_squeeze(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    bb_period = int(params.get("bb_period", 20))
    bb_num_std = float(params.get("bb_num_std", 2.0))
    kc_period = int(params.get("kc_period", 20))
    kc_atr_period = int(params.get("kc_atr_period", 10))
    kc_multiplier = float(params.get("kc_multiplier", 1.5))
    bb_basis = f"ttmBbBasis{suffix}"
    bb_dev = f"ttmBbDev{suffix}"
    bb_upper = f"ttmBbUpper{suffix}"
    bb_lower = f"ttmBbLower{suffix}"
    kc_mid = f"ttmKcMid{suffix}"
    kc_atr = f"ttmKcAtr{suffix}"
    kc_upper = f"ttmKcUpper{suffix}"
    kc_lower = f"ttmKcLower{suffix}"
    var = f"ttmSqueeze{suffix}"
    return [
        f"{bb_basis} = ta.sma(close, {bb_period})",
        f"{bb_dev} = {_pine_num(bb_num_std)} * ta.stdev(close, {bb_period})",
        f"{bb_upper} = {bb_basis} + {bb_dev}",
        f"{bb_lower} = {bb_basis} - {bb_dev}",
        f"{kc_mid} = ta.ema(close, {kc_period})",
        f"{kc_atr} = ta.rma(ta.tr(true), {kc_atr_period})",
        f"{kc_upper} = {kc_mid} + {_pine_num(kc_multiplier)} * {kc_atr}",
        f"{kc_lower} = {kc_mid} - {_pine_num(kc_multiplier)} * {kc_atr}",
        f"{var} = ({bb_upper} < {kc_upper}) and ({bb_lower} > {kc_lower})",
    ], var


def _b_ttm_squeeze_release(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, squeeze_var = _b_ttm_squeeze(suffix, params)
    var = f"ttmRelease{suffix}"
    lines = lines + [f"{var} = ({squeeze_var}[1]) and (not {squeeze_var})"]
    return lines, var


_PINE_LEVEL_BUILDERS: dict[str, Any] = {
    "ema": _b_ema,
    "vwap": _b_vwap,
    "supertrend": _b_supertrend_line,
    "rsi": _b_rsi,
    "adx": _b_dmi("adx"),
    "macd": _b_macd_line,
    "atr": _b_atr,
    "obv": _b_obv,
    "mfi": _b_mfi,
}


def _b_rising(base_builder):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lookback = int(params.get("lookback", 1))
        lines, base_var = base_builder(suffix, params)
        var = f"rising{suffix}"
        lines = list(lines) + [f"{var} = {base_var} > {base_var}[{lookback}]"]
        return lines, var

    return _builder


def _b_falling(base_builder):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lookback = int(params.get("lookback", 1))
        lines, base_var = base_builder(suffix, params)
        var = f"falling{suffix}"
        lines = list(lines) + [f"{var} = {base_var} < {base_var}[{lookback}]"]
        return lines, var

    return _builder


def _b_consecutive_rising(base_builder):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        n = int(params.get("n", 3))
        lines, base_var = base_builder(suffix, params)
        flag = f"risingFlag{suffix}"
        var = f"consecRising{suffix}"
        lines = list(lines) + [
            f"{flag} = {base_var} > {base_var}[1] ? 1.0 : 0.0",
            f"{var} = ta.sma({flag}, {n}) == 1.0",
        ]
        return lines, var

    return _builder


def _b_consecutive_falling(base_builder):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        n = int(params.get("n", 3))
        lines, base_var = base_builder(suffix, params)
        flag = f"fallingFlag{suffix}"
        var = f"consecFalling{suffix}"
        lines = list(lines) + [
            f"{flag} = {base_var} < {base_var}[1] ? 1.0 : 0.0",
            f"{var} = ta.sma({flag}, {n}) == 1.0",
        ]
        return lines, var

    return _builder


# ---------------------------------------------------------------------------
# 以下、price_actionカテゴリ(76件)のPine変換用builder群 - engine/
# candlestick_patterns.py・engine/heikin_ashi.py・engine/derived_
# indicators.pyの各実装を1件ずつ移植したもの。
# ---------------------------------------------------------------------------


def _b_large_candle(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lookback = int(params.get("lookback", 20))
        multiplier = float(params.get("multiplier", 1.5))
        body = f"lgBody{suffix}"
        avg = f"lgAvg{suffix}"
        var = f"lg{suffix}"
        direction_expr = "close > open" if bullish else "close < open"
        return [
            f"{body} = math.abs(close - open)",
            f"{avg} = ta.sma({body}[1], {lookback})",
            f"{var} = ({direction_expr}) and ({body} > {avg} * {_pine_num(multiplier)})",
        ], var

    return _builder


def _b_small_candle(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lookback = int(params.get("lookback", 20))
        multiplier = float(params.get("multiplier", 0.5))
        body = f"smBody{suffix}"
        avg = f"smAvg{suffix}"
        var = f"sm{suffix}"
        direction_expr = "close > open" if bullish else "close < open"
        return [
            f"{body} = math.abs(close - open)",
            f"{avg} = ta.sma({body}[1], {lookback})",
            f"{var} = ({direction_expr}) and ({body} < {avg} * {_pine_num(multiplier)}) and ({avg} > 0)",
        ], var

    return _builder


def _b_long_wick(upper: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        threshold = float(params.get("wick_ratio_threshold", 0.6))
        wick = f"lwWick{suffix}"
        var = f"lw{suffix}"
        wick_expr = "high - math.max(open, close)" if upper else "math.min(open, close) - low"
        return [
            f"{wick} = {wick_expr}",
            f"{var} = ({wick} / (high - low)) >= {_pine_num(threshold)}",
        ], var

    return _builder


def _b_no_wick(upper: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        threshold = float(params.get("threshold", 0.05))
        wick = f"nwWick{suffix}"
        var = f"nw{suffix}"
        wick_expr = "high - math.max(open, close)" if upper else "math.min(open, close) - low"
        return [
            f"{wick} = {wick_expr}",
            f"{var} = ({wick} / (high - low)) <= {_pine_num(threshold)}",
        ], var

    return _builder


def _b_pin_bar(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        body_ratio_max = float(params.get("body_ratio_max", 0.3))
        wick_ratio_min = float(params.get("wick_ratio_min", 0.6))
        body_pct = f"pbBodyPct{suffix}"
        wick_pct = f"pbWickPct{suffix}"
        var = f"pb{suffix}"
        wick_expr = "(math.min(open, close) - low)" if bullish else "(high - math.max(open, close))"
        return [
            f"{body_pct} = math.abs(close - open) / (high - low)",
            f"{wick_pct} = {wick_expr} / (high - low)",
            f"{var} = ({body_pct} <= {_pine_num(body_ratio_max)}) and ({wick_pct} >= {_pine_num(wick_ratio_min)})",
        ], var

    return _builder


def _b_hammer_shape(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    body_ratio_max = float(params.get("body_ratio_max", 0.3))
    lower_wick_ratio_min = float(params.get("lower_wick_ratio_min", 0.6))
    upper_wick_ratio_max = float(params.get("upper_wick_ratio_max", 0.1))
    body_pct = f"hsBodyPct{suffix}"
    lower_pct = f"hsLowerPct{suffix}"
    upper_pct = f"hsUpperPct{suffix}"
    var = f"hs{suffix}"
    return [
        f"{body_pct} = math.abs(close - open) / (high - low)",
        f"{lower_pct} = (math.min(open, close) - low) / (high - low)",
        f"{upper_pct} = (high - math.max(open, close)) / (high - low)",
        f"{var} = ({body_pct} <= {_pine_num(body_ratio_max)}) and ({lower_pct} >= {_pine_num(lower_wick_ratio_min)}) "
        f"and ({upper_pct} <= {_pine_num(upper_wick_ratio_max)})",
    ], var


def _b_inverted_hammer_shape(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    body_ratio_max = float(params.get("body_ratio_max", 0.3))
    upper_wick_ratio_min = float(params.get("upper_wick_ratio_min", 0.6))
    lower_wick_ratio_max = float(params.get("lower_wick_ratio_max", 0.1))
    body_pct = f"ihsBodyPct{suffix}"
    upper_pct = f"ihsUpperPct{suffix}"
    lower_pct = f"ihsLowerPct{suffix}"
    var = f"ihs{suffix}"
    return [
        f"{body_pct} = math.abs(close - open) / (high - low)",
        f"{upper_pct} = (high - math.max(open, close)) / (high - low)",
        f"{lower_pct} = (math.min(open, close) - low) / (high - low)",
        f"{var} = ({body_pct} <= {_pine_num(body_ratio_max)}) and ({upper_pct} >= {_pine_num(upper_wick_ratio_min)}) "
        f"and ({lower_pct} <= {_pine_num(lower_wick_ratio_max)})",
    ], var


def _b_long_legged_doji(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    body_ratio_threshold = float(params.get("body_ratio_threshold", 0.1))
    wick_ratio_min = float(params.get("wick_ratio_min", 0.35))
    body_pct = f"lldBodyPct{suffix}"
    upper_pct = f"lldUpperPct{suffix}"
    lower_pct = f"lldLowerPct{suffix}"
    var = f"lld{suffix}"
    return [
        f"{body_pct} = math.abs(close - open) / (high - low)",
        f"{upper_pct} = (high - math.max(open, close)) / (high - low)",
        f"{lower_pct} = (math.min(open, close) - low) / (high - low)",
        f"{var} = ({body_pct} < {_pine_num(body_ratio_threshold)}) and ({upper_pct} >= {_pine_num(wick_ratio_min)}) "
        f"and ({lower_pct} >= {_pine_num(wick_ratio_min)})",
    ], var


def _b_dragonfly_doji(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    body_ratio_threshold = float(params.get("body_ratio_threshold", 0.1))
    lower_wick_ratio_min = float(params.get("lower_wick_ratio_min", 0.6))
    upper_wick_ratio_max = float(params.get("upper_wick_ratio_max", 0.1))
    body_pct = f"ddBodyPct{suffix}"
    lower_pct = f"ddLowerPct{suffix}"
    upper_pct = f"ddUpperPct{suffix}"
    var = f"dd{suffix}"
    return [
        f"{body_pct} = math.abs(close - open) / (high - low)",
        f"{lower_pct} = (math.min(open, close) - low) / (high - low)",
        f"{upper_pct} = (high - math.max(open, close)) / (high - low)",
        f"{var} = ({body_pct} < {_pine_num(body_ratio_threshold)}) and ({lower_pct} >= {_pine_num(lower_wick_ratio_min)}) "
        f"and ({upper_pct} <= {_pine_num(upper_wick_ratio_max)})",
    ], var


def _b_gravestone_doji(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    body_ratio_threshold = float(params.get("body_ratio_threshold", 0.1))
    upper_wick_ratio_min = float(params.get("upper_wick_ratio_min", 0.6))
    lower_wick_ratio_max = float(params.get("lower_wick_ratio_max", 0.1))
    body_pct = f"gdBodyPct{suffix}"
    upper_pct = f"gdUpperPct{suffix}"
    lower_pct = f"gdLowerPct{suffix}"
    var = f"gd{suffix}"
    return [
        f"{body_pct} = math.abs(close - open) / (high - low)",
        f"{upper_pct} = (high - math.max(open, close)) / (high - low)",
        f"{lower_pct} = (math.min(open, close) - low) / (high - low)",
        f"{var} = ({body_pct} < {_pine_num(body_ratio_threshold)}) and ({upper_pct} >= {_pine_num(upper_wick_ratio_min)}) "
        f"and ({lower_pct} <= {_pine_num(lower_wick_ratio_max)})",
    ], var


def _b_spinning_top(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    body_ratio_max = float(params.get("body_ratio_max", 0.3))
    wick_ratio_min = float(params.get("wick_ratio_min", 0.3))
    body_pct = f"spBodyPct{suffix}"
    upper_pct = f"spUpperPct{suffix}"
    lower_pct = f"spLowerPct{suffix}"
    var = f"sp{suffix}"
    return [
        f"{body_pct} = math.abs(close - open) / (high - low)",
        f"{upper_pct} = (high - math.max(open, close)) / (high - low)",
        f"{lower_pct} = (math.min(open, close) - low) / (high - low)",
        f"{var} = ({body_pct} <= {_pine_num(body_ratio_max)}) and ({upper_pct} >= {_pine_num(wick_ratio_min)}) "
        f"and ({lower_pct} >= {_pine_num(wick_ratio_min)})",
    ], var


def _b_kicker(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        body_ratio_threshold = float(params.get("body_ratio_threshold", 0.7))
        require_gap = bool(params.get("require_gap", True))
        body_pct = f"kkBodyPct{suffix}"
        var = f"kk{suffix}"
        if bullish:
            prev_dir, cur_dir, no_overlap, gap = "close[1] < open[1]", "close > open", "open >= open[1]", "open > open[1]"
        else:
            prev_dir, cur_dir, no_overlap, gap = "close[1] > open[1]", "close < open", "open <= open[1]", "open < open[1]"
        gap_clause = f" and ({gap})" if require_gap else ""
        return [
            f"{body_pct} = math.abs(close - open) / (high - low)",
            f"{var} = ({prev_dir}) and ({cur_dir}) and ({no_overlap}) and ({body_pct} >= {_pine_num(body_ratio_threshold)}){gap_clause}",
        ], var

    return _builder


def _b_belt_hold(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        body_ratio_min = float(params.get("body_ratio_min", 0.7))
        body_pct = f"bhBodyPct{suffix}"
        wick_pct = f"bhWickPct{suffix}"
        var = f"bh{suffix}"
        if bullish:
            wick_ratio_max = float(params.get("lower_wick_ratio_max", 0.05))
            wick_expr = "(math.min(open, close) - low)"
            direction = "close > open"
        else:
            wick_ratio_max = float(params.get("upper_wick_ratio_max", 0.05))
            wick_expr = "(high - math.max(open, close))"
            direction = "close < open"
        return [
            f"{body_pct} = math.abs(close - open) / (high - low)",
            f"{wick_pct} = {wick_expr} / (high - low)",
            f"{var} = ({direction}) and ({wick_pct} <= {_pine_num(wick_ratio_max)}) and ({body_pct} >= {_pine_num(body_ratio_min)})",
        ], var

    return _builder


def _b_abandoned_baby(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        small_body_ratio = float(params.get("small_body_ratio", 0.1))
        body_pct = f"abBodyPct{suffix}"
        var = f"ab{suffix}"
        if bullish:
            c1_dir = "close[2] < open[2]"
            gap_into = "high[1] < low[2]"
            c3_dir = "close > open"
            gap_out = "low > high[1]"
        else:
            c1_dir = "close[2] > open[2]"
            gap_into = "low[1] > high[2]"
            c3_dir = "close < open"
            gap_out = "high < low[1]"
        return [
            f"{body_pct} = math.abs(close - open) / (high - low)",
            f"{var} = ({c1_dir}) and ({body_pct}[1] < {_pine_num(small_body_ratio)}) and ({gap_into}) and "
            f"({c3_dir}) and ({gap_out})",
        ], var

    return _builder


def _b_harami(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        containment_tolerance = float(params.get("containment_tolerance", 0.0))
        prev_top = f"hmPrevTop{suffix}"
        prev_bottom = f"hmPrevBottom{suffix}"
        slack = f"hmSlack{suffix}"
        cur_top = f"hmCurTop{suffix}"
        cur_bottom = f"hmCurBottom{suffix}"
        var = f"hm{suffix}"
        prev_dir = "close[1] < open[1]" if bullish else "close[1] > open[1]"
        cur_dir = "close > open" if bullish else "close < open"
        return [
            f"{prev_top} = math.max(open[1], close[1])",
            f"{prev_bottom} = math.min(open[1], close[1])",
            f"{slack} = ({prev_top} - {prev_bottom}) * {_pine_num(containment_tolerance)}",
            f"{cur_top} = math.max(open, close)",
            f"{cur_bottom} = math.min(open, close)",
            f"{var} = ({prev_dir}) and ({cur_dir}) and ({cur_top} <= {prev_top} + {slack}) and "
            f"({cur_bottom} >= {prev_bottom} - {slack})",
        ], var

    return _builder


def _b_engulfing(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tolerance_pct = float(params.get("tolerance_pct", 0.0))
        prev_body = f"enPrevBody{suffix}"
        slack = f"enSlack{suffix}"
        var = f"en{suffix}"
        prev_dir = "close[1] < open[1]" if bullish else "close[1] > open[1]"
        cur_dir = "close > open" if bullish else "close < open"
        if bullish:
            cond1, cond2 = f"open <= close[1] + {slack}", f"close >= open[1] - {slack}"
        else:
            cond1, cond2 = f"open >= close[1] - {slack}", f"close <= open[1] + {slack}"
        return [
            f"{prev_body} = math.abs(close[1] - open[1])",
            f"{slack} = {prev_body} * {_pine_num(tolerance_pct)}",
            f"{var} = ({prev_dir}) and ({cur_dir}) and ({cond1}) and ({cond2})",
        ], var

    return _builder


def _b_three_inside(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, harami_var = _b_harami(bullish)(suffix, params)
        var = f"ti{suffix}"
        confirm = "close > close[1]" if bullish else "close < close[1]"
        lines = lines + [f"{var} = ({harami_var}[1]) and ({confirm})"]
        return lines, var

    return _builder


def _b_three_outside(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, engulf_var = _b_engulfing(bullish)(suffix, params)
        var = f"to{suffix}"
        confirm = "close > close[1]" if bullish else "close < close[1]"
        lines = lines + [f"{var} = ({engulf_var}[1]) and ({confirm})"]
        return lines, var

    return _builder


def _b_inside_bar(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    min_mother_range_atr_mult = float(params.get("min_mother_range_atr_mult", 0.0))
    var = f"ib{suffix}"
    if min_mother_range_atr_mult <= 0:
        return [f"{var} = (high < high[1]) and (low > low[1])"], var
    atr_v = f"ibAtr{suffix}"
    mother_range = f"ibMotherRange{suffix}"
    return [
        f"{atr_v} = ta.rma(ta.tr(true), 14)",
        f"{mother_range} = high[1] - low[1]",
        f"{var} = (high < high[1]) and (low > low[1]) and ({mother_range} >= {atr_v} * {_pine_num(min_mother_range_atr_mult)})",
    ], var


def _b_gap(up: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        min_gap_atr_mult = float(params.get("min_gap_atr_mult", 0.0))
        var = f"gap{suffix}"
        base_expr = "open > high[1]" if up else "open < low[1]"
        if min_gap_atr_mult <= 0:
            return [f"{var} = {base_expr}"], var
        atr_v = f"gapAtr{suffix}"
        gap_size = f"gapSize{suffix}"
        gap_size_expr = "open - high[1]" if up else "low[1] - open"
        return [
            f"{atr_v} = ta.rma(ta.tr(true), 14)",
            f"{gap_size} = {gap_size_expr}",
            f"{var} = ({base_expr}) and ({gap_size} >= {atr_v} * {_pine_num(min_gap_atr_mult)})",
        ], var

    return _builder


def _b_morning_evening_star(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        small_body_ratio = float(params.get("small_body_ratio", 0.3))
        close_position_ratio = float(params.get("close_position_ratio", 0.5))
        require_gap = bool(params.get("require_gap", False))
        body_pct = f"msBodyPct{suffix}"
        c1_body = f"msC1Body{suffix}"
        c1_target = f"msC1Target{suffix}"
        var = f"ms{suffix}"
        if bullish:
            c1_dir = "close[2] < open[2]"
            c1_target_expr = f"close[2] + (open[2] - close[2]) * {_pine_num(close_position_ratio)}"
            c3_dir = "close > open"
            c3_target_cond = f"close > {c1_target}"
            gap_into_c2, gap_into_c3 = "high[1] < low[2]", "low < high[1]"
        else:
            c1_dir = "close[2] > open[2]"
            c1_target_expr = f"close[2] - (close[2] - open[2]) * {_pine_num(close_position_ratio)}"
            c3_dir = "close < open"
            c3_target_cond = f"close < {c1_target}"
            gap_into_c2, gap_into_c3 = "low[1] > high[2]", "high < low[1]"
        cond = (
            f"({c1_dir}) and ({body_pct}[1] < {_pine_num(small_body_ratio)}) and ({c3_dir}) and "
            f"(math.abs(close - open) > {c1_body} * 0.5) and ({c3_target_cond})"
        )
        if require_gap:
            cond += f" and ({gap_into_c2}) and ({gap_into_c3})"
        return [
            f"{body_pct} = math.abs(close - open) / (high - low)",
            f"{c1_body} = math.abs(close[2] - open[2])",
            f"{c1_target} = {c1_target_expr}",
            f"{var} = {cond}",
        ], var

    return _builder


def _b_three_soldiers_crows(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        min_body_ratio = float(params.get("min_body_ratio", 0.0))
        var = f"tsc{suffix}"
        if bullish:
            all_dir = "(close > open) and (close[1] > open[1]) and (close[2] > open[2])"
            closes_trend = "(close > close[1]) and (close[1] > close[2])"
            opens_within = "(open > open[1]) and (open < close[1]) and (open[1] > open[2]) and (open[1] < close[2])"
        else:
            all_dir = "(close < open) and (close[1] < open[1]) and (close[2] < open[2])"
            closes_trend = "(close < close[1]) and (close[1] < close[2])"
            opens_within = "(open < open[1]) and (open > close[1]) and (open[1] < open[2]) and (open[1] > close[2])"
        cond = f"({all_dir}) and ({closes_trend}) and ({opens_within})"
        lines = []
        if min_body_ratio > 0:
            body_pct = f"tscBodyPct{suffix}"
            lines.append(f"{body_pct} = math.abs(close - open) / (high - low)")
            cond += (
                f" and ({body_pct} >= {_pine_num(min_body_ratio)}) and ({body_pct}[1] >= {_pine_num(min_body_ratio)}) "
                f"and ({body_pct}[2] >= {_pine_num(min_body_ratio)})"
            )
        lines.append(f"{var} = {cond}")
        return lines, var

    return _builder


def _b_three_methods(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        max_middle_body_ratio = float(params.get("max_middle_body_ratio", 1.0))
        var = f"tm{suffix}"
        if bullish:
            c1_dir, c5_dir, c5_break = "close[4] > open[4]", "close > open", "close > high[4]"
        else:
            c1_dir, c5_dir, c5_break = "close[4] < open[4]", "close < open", "close < low[4]"
        middle_terms = " and ".join(f"(high[{k}] <= high[4]) and (low[{k}] >= low[4])" for k in (1, 2, 3))
        cond = f"({c1_dir}) and ({middle_terms}) and ({c5_dir}) and ({c5_break})"
        lines = []
        if max_middle_body_ratio < 1.0:
            body_pct = f"tmBodyPct{suffix}"
            lines.append(f"{body_pct} = math.abs(close - open) / (high - low)")
            extra = " and ".join(f"({body_pct}[{k}] <= {_pine_num(max_middle_body_ratio)})" for k in (1, 2, 3))
            cond += f" and ({extra})"
        lines.append(f"{var} = {cond}")
        return lines, var

    return _builder


def _b_three_line_strike(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"tls{suffix}"
        if bullish:
            three_dir = "(close[1] < open[1]) and (close[2] < open[2]) and (close[3] < open[3])"
            trend = "(close[1] < close[2]) and (close[2] < close[3])"
            cur_dir = "close > open"
            engulfs = "(open < close[1]) and (close > open[3])"
        else:
            three_dir = "(close[1] > open[1]) and (close[2] > open[2]) and (close[3] > open[3])"
            trend = "(close[1] > close[2]) and (close[2] > close[3])"
            cur_dir = "close < open"
            engulfs = "(open > close[1]) and (close < open[3])"
        return [f"{var} = ({three_dir}) and ({trend}) and ({cur_dir}) and ({engulfs})"], var

    return _builder


def _b_tasuki_gap(upside: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"tg{suffix}"
        bar2_top = f"tgBar2Top{suffix}"
        bar2_bottom = f"tgBar2Bottom{suffix}"
        if upside:
            bar1_dir, bar2_dir, gap = "close[2] > open[2]", "close[1] > open[1]", "open[1] > high[2]"
            bar3_dir, gap_not_closed = "close < open", "close > high[2]"
        else:
            bar1_dir, bar2_dir, gap = "close[2] < open[2]", "close[1] < open[1]", "open[1] < low[2]"
            bar3_dir, gap_not_closed = "close > open", "close < low[2]"
        return [
            f"{bar2_top} = math.max(open[1], close[1])",
            f"{bar2_bottom} = math.min(open[1], close[1])",
            f"{var} = ({bar1_dir}) and ({bar2_dir}) and ({gap}) and ({bar3_dir}) and "
            f"(open < {bar2_top}) and (open > {bar2_bottom}) and ({gap_not_closed})",
        ], var

    return _builder


def _b_tweezer(top: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tolerance_pct = float(params.get("tolerance_pct", 0.1))
        avg_rng = f"twAvgRng{suffix}"
        var = f"tw{suffix}"
        if top:
            match_expr, prev_dir, cur_dir = "math.abs(high - high[1])", "close[1] > open[1]", "close < open"
        else:
            match_expr, prev_dir, cur_dir = "math.abs(low - low[1])", "close[1] < open[1]", "close > open"
        return [
            f"{avg_rng} = ((high - low) + (high[1] - low[1])) / 2",
            f"{var} = ({match_expr} <= {avg_rng} * {_pine_num(tolerance_pct)}) and ({prev_dir}) and ({cur_dir})",
        ], var

    return _builder


def _b_consecutive_candles(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        n = int(params.get("n", 3))
        flag = f"ccFlag{suffix}"
        var = f"cc{suffix}"
        direction_expr = "close > open" if bullish else "close < open"
        return [
            f"{flag} = ({direction_expr}) ? 1.0 : 0.0",
            f"{var} = ta.sma({flag}, {n}) == 1.0",
        ], var

    return _builder


def _b_consecutive_hh_ll(higher: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        n = int(params.get("n", 3))
        flag = f"chlFlag{suffix}"
        var = f"chl{suffix}"
        expr = "high > high[1] ? 1.0 : 0.0" if higher else "low < low[1] ? 1.0 : 0.0"
        return [
            f"{flag} = {expr}",
            f"{var} = ta.sma({flag}, {n}) == 1.0",
        ], var

    return _builder


def _b_body_larger_than_average(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lookback = int(params.get("lookback", 20))
    multiplier = float(params.get("multiplier", 1.5))
    body = f"blaBody{suffix}"
    avg = f"blaAvg{suffix}"
    var = f"bla{suffix}"
    return [
        f"{body} = math.abs(close - open)",
        f"{avg} = ta.sma({body}[1], {lookback})",
        f"{var} = {body} > {avg} * {_pine_num(multiplier)}",
    ], var


def _b_wick_ratio_at_least(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    threshold_pct = float(params.get("threshold_pct", 50.0))
    upper = f"wraUpper{suffix}"
    lower = f"wraLower{suffix}"
    pct = f"wraPct{suffix}"
    var = f"wra{suffix}"
    return [
        f"{upper} = high - math.max(open, close)",
        f"{lower} = math.min(open, close) - low",
        f"{pct} = ({upper} + {lower}) / (high - low) * 100",
        f"{var} = {pct} >= {_pine_num(threshold_pct)}",
    ], var


def _b_body_ratio_at_least(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    threshold_pct = float(params.get("threshold_pct", 50.0))
    pct = f"braPct{suffix}"
    var = f"bra{suffix}"
    return [
        f"{pct} = math.abs(close - open) / (high - low) * 100",
        f"{var} = {pct} >= {_pine_num(threshold_pct)}",
    ], var


def _b_avg_body_size(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    exclude_current = int(params.get("exclude_current", 0))
    body = f"absBodyAvg{suffix}"
    var = f"avgBody{suffix}"
    src = f"{body}[1]" if exclude_current else body
    return [f"{body} = math.abs(close - open)", f"{var} = ta.sma({src}, {length})"], var


def _b_max_body_size(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    exclude_current = int(params.get("exclude_current", 0))
    body = f"absBodyMax{suffix}"
    var = f"maxBody{suffix}"
    src = f"{body}[1]" if exclude_current else body
    return [f"{body} = math.abs(close - open)", f"{var} = ta.highest({src}, {length})"], var


def _b_min_body_size(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    exclude_current = int(params.get("exclude_current", 0))
    body = f"absBodyMin{suffix}"
    var = f"minBody{suffix}"
    src = f"{body}[1]" if exclude_current else body
    return [f"{body} = math.abs(close - open)", f"{var} = ta.lowest({src}, {length})"], var


def _b_body_size_std(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    exclude_current = int(params.get("exclude_current", 0))
    body = f"absBodyStd{suffix}"
    var = f"bodyStd{suffix}"
    src = f"{body}[1]" if exclude_current else body
    return [f"{body} = math.abs(close - open)", f"{var} = ta.stdev({src}, {length})"], var


def _b_avg_upper_wick(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    wick = f"auwWick{suffix}"
    var = f"auw{suffix}"
    return [f"{wick} = high - math.max(open, close)", f"{var} = ta.sma({wick}, {length})"], var


def _b_avg_lower_wick(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    length = int(params.get("length", 20))
    wick = f"alwWick{suffix}"
    var = f"alw{suffix}"
    return [f"{wick} = math.min(open, close) - low", f"{var} = ta.sma({wick}, {length})"], var


def _b_is_max_body_of_n(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    window = int(params.get("window", 100))
    body = f"imbBody{suffix}"
    max_v = f"imbMax{suffix}"
    var = f"imb{suffix}"
    return [
        f"{body} = math.abs(close - open)",
        f"{max_v} = ta.highest({body}, {window})",
        f"{var} = {body} == {max_v}",
    ], var


def _b_nr(n: int):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        rng = f"nrRange{suffix}"
        min_v = f"nrMin{suffix}"
        var = f"nr{suffix}"
        return [
            f"{rng} = high - low",
            f"{min_v} = ta.lowest({rng}, {n})",
            f"{var} = {rng} == {min_v}",
        ], var

    return _builder


def _b_volume_climax(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lookback = int(params.get("lookback", 20))
        body_mult = float(params.get("body_mult", 2.0))
        volume_mult = float(params.get("volume_mult", 2.0))
        body = f"vcBody{suffix}"
        avg_body = f"vcAvgBody{suffix}"
        avg_vol = f"vcAvgVol{suffix}"
        var = f"vc{suffix}"
        direction_expr = "close > open" if bullish else "close < open"
        return [
            f"{body} = math.abs(close - open)",
            f"{avg_body} = ta.sma({body}[1], {lookback})",
            f"{avg_vol} = ta.sma(volume[1], {lookback})",
            f"{var} = ({direction_expr}) and ({body} > {avg_body} * {_pine_num(body_mult)}) and "
            f"(volume > {avg_vol} * {_pine_num(volume_mult)})",
        ], var

    return _builder


def _b_percentile_rank_body(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    window = int(params.get("window", 50))
    body = f"prbBody{suffix}"
    var = f"prb{suffix}"
    return [f"{body} = math.abs(close - open)", f"{var} = ta.percentrank({body}, {window})"], var


def _b_dist_to_round_number(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    pip_size = float(params.get("pip_size", 0.01))
    round_interval = float(params.get("round_interval", 1.0))
    nearest = f"drnNearest{suffix}"
    var = f"drn{suffix}"
    return [
        f"{nearest} = math.round(close / {_pine_num(round_interval)}) * {_pine_num(round_interval)}",
        f"{var} = math.abs(close - {nearest}) / {_pine_num(pip_size)}",
    ], var


def _b_swing_structure(kind: str):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lookback = int(params.get("lookback", 5))
        is_high = kind in ("higher_high", "lower_high")
        pivot_fn = "pivothigh" if is_high else "pivotlow"
        source = "high" if is_high else "low"
        raw = f"swRaw{suffix}"
        last_v = f"swLast{suffix}"
        prev_v = f"swPrev{suffix}"
        var = f"sw{suffix}"
        lines = [
            f"{raw} = ta.{pivot_fn}({source}, {lookback}, {lookback})",
            f"var float {last_v} = na",
            f"var float {prev_v} = na",
            f"if not na({raw})",
            f"    {prev_v} := {last_v}",
            f"    {last_v} := {raw}",
        ]
        if kind in ("higher_high", "higher_low"):
            lines.append(f"{var} = not na({raw}) and not na({prev_v}) and {raw} > {prev_v}")
        else:
            lines.append(f"{var} = not na({raw}) and not na({prev_v}) and {raw} < {prev_v}")
        return lines, var

    return _builder


def _b_first_pullback_after_breakout(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        length = int(params.get("length", 20))
        had_breakout = f"fpbHadBreakout{suffix}"
        had_pullback = f"fpbHadPullback{suffix}"
        breakout = f"fpbBreakout{suffix}"
        pullback_bar = f"fpbPullbackBar{suffix}"
        var = f"fpb{suffix}"
        if bullish:
            breakout_expr = f"close > ta.highest(high[1], {length})"
            pullback_expr = "close < close[1]"
        else:
            breakout_expr = f"close < ta.lowest(low[1], {length})"
            pullback_expr = "close > close[1]"
        return [
            f"var bool {had_breakout} = false",
            f"var bool {had_pullback} = false",
            f"{breakout} = {breakout_expr}",
            f"if {breakout}",
            f"    {had_breakout} := true",
            f"    {had_pullback} := false",
            f"{pullback_bar} = {pullback_expr}",
            f"{var} = {had_breakout} and (not {breakout}) and {pullback_bar} and not {had_pullback}",
            f"if {var}",
            f"    {had_pullback} := true",
        ], var

    return _builder


def _b_today_new_extreme(is_high: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        new_day = f"tneNewDay{suffix}"
        running = f"tneRunning{suffix}"
        prev_running = f"tnePrevRunning{suffix}"
        var = f"tne{suffix}"
        if is_high:
            var_type, extreme_fn, cmp_op = "float", "math.max", ">"
        else:
            var_type, extreme_fn, cmp_op = "float", "math.min", "<"
        source = "high" if is_high else "low"
        return [
            f'{new_day} = ta.change(dayofmonth(time, "{TIMEZONE}")) != 0',
            f"var {var_type} {running} = na",
            f"{prev_running} = {new_day} ? na : {running}",
            f"{var} = not na({prev_running}) and ({source} {cmp_op} {prev_running})",
            f"{running} := {new_day} ? {source} : {extreme_fn}({running}, {source})",
        ], var

    return _builder


def _b_today_range_position(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    new_day = f"trpNewDay{suffix}"
    high_inc = f"trpHigh{suffix}"
    low_inc = f"trpLow{suffix}"
    var = f"trp{suffix}"
    return [
        f'{new_day} = ta.change(dayofmonth(time, "{TIMEZONE}")) != 0',
        f"var float {high_inc} = na",
        f"var float {low_inc} = na",
        f"{high_inc} := {new_day} ? high : math.max({high_inc}, high)",
        f"{low_inc} := {new_day} ? low : math.min({low_inc}, low)",
        f"{var} = (close - {low_inc}) / ({high_inc} - {low_inc})",
    ], var


def _b_today_range_pct_of_adr(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    adr_period = int(params.get("adr_period", 14))
    new_day = f"trpaNewDay{suffix}"
    high_inc = f"trpaHigh{suffix}"
    low_inc = f"trpaLow{suffix}"
    var = f"trpa{suffix}"
    lines, adr_var = _b_adr(suffix, {"adr_period": adr_period})
    lines = lines + [
        f'{new_day} = ta.change(dayofmonth(time, "{TIMEZONE}")) != 0',
        f"var float {high_inc} = na",
        f"var float {low_inc} = na",
        f"{high_inc} := {new_day} ? high : math.max({high_inc}, high)",
        f"{low_inc} := {new_day} ? low : math.min({low_inc}, low)",
        f"{var} = ({high_inc} - {low_inc}) / {adr_var} * 100",
    ]
    return lines, var


def _b_heikin_ashi_state(suffix: str) -> tuple[list[str], str, str, str, str]:
    ha_close = f"haClose{suffix}"
    ha_open = f"haOpen{suffix}"
    ha_high = f"haHigh{suffix}"
    ha_low = f"haLow{suffix}"
    lines = [
        f"{ha_close} = (open + high + low + close) / 4",
        f"var float {ha_open} = na",
        f"{ha_open} := na({ha_open}[1]) ? (open + close) / 2 : ({ha_open}[1] + {ha_close}[1]) / 2",
        f"{ha_high} = math.max(high, math.max({ha_open}, {ha_close}))",
        f"{ha_low} = math.min(low, math.min({ha_open}, {ha_close}))",
    ]
    return lines, ha_open, ha_high, ha_low, ha_close


def _b_ha_bullish(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, ha_open, _hh, _hl, ha_close = _b_heikin_ashi_state(suffix)
    var = f"haBull{suffix}"
    lines = lines + [f"{var} = {ha_close} > {ha_open}"]
    return lines, var


def _b_ha_bearish(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    lines, ha_open, _hh, _hl, ha_close = _b_heikin_ashi_state(suffix)
    var = f"haBear{suffix}"
    lines = lines + [f"{var} = {ha_close} < {ha_open}"]
    return lines, var


def _b_ha_strong(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        threshold = float(params.get("threshold", 0.05))
        lines, ha_open, ha_high, ha_low, ha_close = _b_heikin_ashi_state(suffix)
        var = f"haStrong{suffix}"
        if bullish:
            wick_expr = f"(math.min({ha_open}, {ha_close}) - {ha_low}) / ({ha_high} - {ha_low})"
            cond = f"({ha_close} > {ha_open}) and ({wick_expr} <= {_pine_num(threshold)})"
        else:
            wick_expr = f"({ha_high} - math.max({ha_open}, {ha_close})) / ({ha_high} - {ha_low})"
            cond = f"({ha_close} < {ha_open}) and ({wick_expr} <= {_pine_num(threshold)})"
        lines = lines + [f"{var} = {cond}"]
        return lines, var

    return _builder


# ---------------------------------------------------------------------------
# 以下、chart_patternカテゴリ(46件)のPine変換用builder群 - engine/
# chart_patterns.py・engine/harmonic_patterns.pyの各実装を移植したもの。
# スイング高値/安値の追跡はPineの ta.pivothigh/ta.pivotlow(確定に
# lookback本の遅延が入る点も含め、engine/smc_indicators.pyの中央窓
# +確定遅延と同じ考え方)を使い、直近3つ分をvarで保持して再利用する
# 共有ヘルパー(_b_swing_state_full)を各パターンが個別に呼び出す
# (パターンごとに独立したsuffix付き変数になるため、重複計算はあるが
# 相互干渉なし - engine/pine_generator.py全体で既に採用されている
# 「シンプルさ優先、重複は許容」方針と同じ)。
# ---------------------------------------------------------------------------


def _b_swing_state_full(suffix: str, params: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    lookback = int(params.get("swing_lookback", 5))
    atr_v = f"csAtr{suffix}"
    hraw = f"csHRaw{suffix}"
    lraw = f"csLRaw{suffix}"
    h0, h1, h2 = f"csH0{suffix}", f"csH1{suffix}", f"csH2{suffix}"
    hb0, hb1 = f"csHB0{suffix}", f"csHB1{suffix}"
    l0, l1, l2 = f"csL0{suffix}", f"csL1{suffix}", f"csL2{suffix}"
    lb0, lb1 = f"csLB0{suffix}", f"csLB1{suffix}"
    lines = [
        f"{atr_v} = ta.rma(ta.tr(true), 14)",
        f"{hraw} = ta.pivothigh(high, {lookback}, {lookback})",
        f"{lraw} = ta.pivotlow(low, {lookback}, {lookback})",
        f"var float {h0} = na", f"var float {h1} = na", f"var float {h2} = na",
        f"var int {hb0} = na", f"var int {hb1} = na",
        f"var float {l0} = na", f"var float {l1} = na", f"var float {l2} = na",
        f"var int {lb0} = na", f"var int {lb1} = na",
        f"if not na({hraw})",
        f"    {h2} := {h1}",
        f"    {h1} := {h0}",
        f"    {h0} := {hraw}",
        f"    {hb1} := {hb0}",
        f"    {hb0} := bar_index - {lookback}",
        f"if not na({lraw})",
        f"    {l2} := {l1}",
        f"    {l1} := {l0}",
        f"    {l0} := {lraw}",
        f"    {lb1} := {lb0}",
        f"    {lb0} := bar_index - {lookback}",
    ]
    names = {
        "atr": atr_v, "hraw": hraw, "lraw": lraw,
        "h0": h0, "h1": h1, "h2": h2, "hb0": hb0, "hb1": hb1,
        "l0": l0, "l1": l1, "l2": l2, "lb0": lb0, "lb1": lb1,
    }
    return lines, names


def _b_first_occurrence_after_lines(suffix: str, formed_expr: str, trigger_expr: str) -> tuple[list[str], str]:
    """engine/chart_patterns.py::_first_occurrence_after()と同じ「formed後、
    最初にtriggerが成立した回だけ発火」をPineのvar状態機械で再現する。"""
    flag = f"foaWaiting{suffix}"
    var = f"foa{suffix}"
    lines = [
        f"var bool {flag} = false",
        f"if {formed_expr}",
        f"    {flag} := true",
        f"{var} = {flag} and (not ({formed_expr})) and ({trigger_expr})",
        f"if {var}",
        f"    {flag} := false",
    ]
    return lines, var


def _b_double_top_bottom(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tolerance_atr_mult = float(params.get("tolerance_atr_mult", 0.5))
        lines, sw = _b_swing_state_full(suffix, params)
        if bullish:
            formed = f"(not na({sw['lraw']})) and (math.abs({sw['l0']} - {sw['l1']}) <= {sw['atr']} * {_pine_num(tolerance_atr_mult)})"
            trigger = f"close > {sw['h0']}"
        else:
            formed = f"(not na({sw['hraw']})) and (math.abs({sw['h0']} - {sw['h1']}) <= {sw['atr']} * {_pine_num(tolerance_atr_mult)})"
            trigger = f"close < {sw['l0']}"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_triple_top_bottom(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tolerance_atr_mult = float(params.get("tolerance_atr_mult", 0.5))
        lines, sw = _b_swing_state_full(suffix, params)
        if bullish:
            formed = (
                f"(not na({sw['lraw']})) and (math.abs({sw['l0']} - {sw['l1']}) <= {sw['atr']} * {_pine_num(tolerance_atr_mult)}) "
                f"and (math.abs({sw['l1']} - {sw['l2']}) <= {sw['atr']} * {_pine_num(tolerance_atr_mult)})"
            )
            trigger = f"close > {sw['h0']}"
        else:
            formed = (
                f"(not na({sw['hraw']})) and (math.abs({sw['h0']} - {sw['h1']}) <= {sw['atr']} * {_pine_num(tolerance_atr_mult)}) "
                f"and (math.abs({sw['h1']} - {sw['h2']}) <= {sw['atr']} * {_pine_num(tolerance_atr_mult)})"
            )
            trigger = f"close < {sw['l0']}"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_head_shoulders(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        shoulder_tol = float(params.get("shoulder_tolerance_atr_mult", 0.75))
        head_margin_mult = float(params.get("head_margin_atr_mult", 0.5))
        lines, sw = _b_swing_state_full(suffix, params)
        if bullish:
            rs, head, ls, raw = sw["l0"], sw["l1"], sw["l2"], sw["lraw"]
            margin = f"({sw['atr']} * {_pine_num(head_margin_mult)})"
            head_extreme = f"({head} < {rs} - {margin}) and ({head} < {ls} - {margin})"
            trigger = f"close > {sw['h0']}"
        else:
            rs, head, ls, raw = sw["h0"], sw["h1"], sw["h2"], sw["hraw"]
            margin = f"({sw['atr']} * {_pine_num(head_margin_mult)})"
            head_extreme = f"({head} > {rs} + {margin}) and ({head} > {ls} + {margin})"
            trigger = f"close < {sw['l0']}"
        shoulders_similar = f"(math.abs({rs} - {ls}) <= {sw['atr']} * {_pine_num(shoulder_tol)})"
        formed = f"(not na({raw})) and ({head_extreme}) and ({shoulders_similar})"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_ascending_triangle(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    tol = float(params.get("flat_tolerance_atr_mult", 0.5))
    lines, sw = _b_swing_state_full(suffix, params)
    state = f"triAscState{suffix}"
    lines = lines + [f"{state} = (math.abs({sw['h0']} - {sw['h1']}) <= {sw['atr']} * {_pine_num(tol)}) and ({sw['l0']} > {sw['l1']})"]
    formed = f"({state}) and (not {state}[1])"
    trigger = f"close > {sw['h0']}"
    foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
    return lines + foa_lines, var


def _b_descending_triangle(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    tol = float(params.get("flat_tolerance_atr_mult", 0.5))
    lines, sw = _b_swing_state_full(suffix, params)
    state = f"triDescState{suffix}"
    lines = lines + [f"{state} = (math.abs({sw['l0']} - {sw['l1']}) <= {sw['atr']} * {_pine_num(tol)}) and ({sw['h0']} < {sw['h1']})"]
    formed = f"({state}) and (not {state}[1])"
    trigger = f"close < {sw['l0']}"
    foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
    return lines + foa_lines, var


def _b_symmetrical_triangle(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, sw = _b_swing_state_full(suffix, params)
        state = f"symTriState{suffix}"
        lines = lines + [f"{state} = ({sw['h0']} < {sw['h1']}) and ({sw['l0']} > {sw['l1']})"]
        formed = f"({state}) and (not {state}[1])"
        trigger = f"close > {sw['h0']}" if bullish else f"close < {sw['l0']}"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_wedge(rising: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, sw = _b_swing_state_full(suffix, params)
        state = f"wedgeState{suffix}"
        if rising:
            dir_cond = f"({sw['h0']} > {sw['h1']}) and ({sw['l0']} > {sw['l1']})"
            trigger = f"close < {sw['l0']}"
        else:
            dir_cond = f"({sw['h0']} < {sw['h1']}) and ({sw['l0']} < {sw['l1']})"
            trigger = f"close > {sw['h0']}"
        narrowing = f"math.abs({sw['h0']} - {sw['l0']}) < math.abs({sw['h1']} - {sw['l1']})"
        lines = lines + [f"{state} = ({dir_cond}) and ({narrowing})"]
        formed = f"({state}) and (not {state}[1])"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_broadening(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, sw = _b_swing_state_full(suffix, params)
        state = f"broadState{suffix}"
        lines = lines + [f"{state} = ({sw['h0']} > {sw['h1']}) and ({sw['l0']} < {sw['l1']})"]
        formed = f"({state}) and (not {state}[1])"
        trigger = f"close > {sw['h0']}" if bullish else f"close < {sw['l0']}"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_diamond(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, sw = _b_swing_state_full(suffix, params)
        state = f"diaState{suffix}"
        earlier = f"({sw['h1']} > {sw['h2']}) and ({sw['l1']} < {sw['l2']})"
        later = f"({sw['h0']} < {sw['h1']}) and ({sw['l0']} > {sw['l1']})"
        lines = lines + [f"{state} = ({earlier}) and ({later})"]
        formed = f"({state}) and (not {state}[1])"
        trigger = f"close > {sw['h0']}" if bullish else f"close < {sw['l0']}"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_flag_pennant(bullish: bool, require_narrowing: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        impulse_lookback = int(params.get("impulse_lookback", 10))
        impulse_atr_mult = float(params.get("impulse_atr_mult", 3.0))
        default_window = 12 if require_narrowing else 10
        default_atr_mult = 2.5 if require_narrowing else 2.0
        consolidation_window = int(params.get("consolidation_window", default_window))
        consolidation_atr_mult = float(params.get("consolidation_atr_mult", default_atr_mult))
        atr_v = f"fpAtr{suffix}"
        impulse_flag = f"fpImpulseFlag{suffix}"
        impulse_recently = f"fpImpulseRecently{suffix}"
        cons_high = f"fpConsHigh{suffix}"
        cons_low = f"fpConsLow{suffix}"
        cons_range = f"fpConsRange{suffix}"
        state = f"fpState{suffix}"
        if bullish:
            impulse_cond = f"(close - close[{impulse_lookback}]) / {atr_v} >= {_pine_num(impulse_atr_mult)}"
        else:
            impulse_cond = f"(close - close[{impulse_lookback}]) / {atr_v} <= -{_pine_num(impulse_atr_mult)}"
        lines = [
            f"{atr_v} = ta.rma(ta.tr(true), 14)",
            f"{impulse_flag} = ({impulse_cond}) ? 1.0 : 0.0",
            f"{impulse_recently} = ta.highest({impulse_flag}[1], {consolidation_window}) > 0",
            f"{cons_high} = ta.highest(high, {consolidation_window})",
            f"{cons_low} = ta.lowest(low, {consolidation_window})",
            f"{cons_range} = {cons_high} - {cons_low}",
        ]
        is_narrow_expr = f"{cons_range} <= {atr_v} * {_pine_num(consolidation_atr_mult)}"
        if require_narrowing:
            half = max(consolidation_window // 2, 1)
            first_half = f"fpFirstHalf{suffix}"
            second_half = f"fpSecondHalf{suffix}"
            lines += [
                f"{first_half} = (ta.highest(high, {half}) - ta.lowest(low, {half}))[{half}]",
                f"{second_half} = ta.highest(high, {half}) - ta.lowest(low, {half})",
            ]
            is_narrow_expr = f"({is_narrow_expr}) and ({second_half} < {first_half})"
        lines.append(f"{state} = {impulse_recently} and ({is_narrow_expr})")
        formed = f"({state}) and (not {state}[1])"
        trigger = f"close > {cons_high}[1]" if bullish else f"close < {cons_low}[1]"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_in_range_box(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    window = int(params.get("window", 20))
    box_atr_mult = float(params.get("box_atr_mult", 2.0))
    atr_v = f"irbAtr{suffix}"
    rng = f"irbRange{suffix}"
    var = f"irb{suffix}"
    return [
        f"{atr_v} = ta.rma(ta.tr(true), 14)",
        f"{rng} = ta.highest(high, {window}) - ta.lowest(low, {window})",
        f"{var} = {rng} <= {atr_v} * {_pine_num(box_atr_mult)}",
    ], var


def _b_range_box_breakout(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        window = int(params.get("window", 20))
        box_atr_mult = float(params.get("box_atr_mult", 2.0))
        atr_v = f"rbbAtr{suffix}"
        rng = f"rbbRange{suffix}"
        boxed = f"rbbBoxed{suffix}"
        extreme = f"rbbExtreme{suffix}"
        lines = [
            f"{atr_v} = ta.rma(ta.tr(true), 14)",
            f"{rng} = ta.highest(high, {window}) - ta.lowest(low, {window})",
            f"{boxed} = {rng} <= {atr_v} * {_pine_num(box_atr_mult)}",
            f"var float {extreme} = na",
        ]
        if bullish:
            lines += [f"if {boxed}", f"    {extreme} := ta.highest(high, {window})"]
        else:
            lines += [f"if {boxed}", f"    {extreme} := ta.lowest(low, {window})"]
        box_ended = f"(not {boxed}) and {boxed}[1]"
        trigger = f"close > {extreme}" if bullish else f"close < {extreme}"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, box_ended, trigger)
        return lines + foa_lines, var

    return _builder


def _b_trendline_break(uptrend: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, sw = _b_swing_state_full(suffix, params)
        if uptrend:
            v0, v1, b0, b1 = sw["l0"], sw["l1"], sw["lb0"], sw["lb1"]
            valid = f"({v0} > {v1}) and ({b0} > {b1})"
        else:
            v0, v1, b0, b1 = sw["h0"], sw["h1"], sw["hb0"], sw["hb1"]
            valid = f"({v0} < {v1}) and ({b0} > {b1})"
        valid_var = f"tlValid{suffix}"
        slope_var = f"tlSlope{suffix}"
        line_var = f"tlLine{suffix}"
        lines = lines + [
            f"{valid_var} = {valid}",
            f"{slope_var} = ({v0} - {v1}) / ({b0} - {b1})",
            f"{line_var} = {v0} + {slope_var} * (bar_index - {b0})",
        ]
        formed = f"({valid_var}) and (not {valid_var}[1])"
        trigger = f"close < {line_var}" if uptrend else f"close > {line_var}"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_channel_break(ascending: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        slope_tol = float(params.get("slope_tolerance_atr_mult", 0.02))
        lines, sw = _b_swing_state_full(suffix, params)
        support_slope = f"chSupportSlope{suffix}"
        resistance_slope = f"chResistSlope{suffix}"
        state = f"chState{suffix}"
        lines = lines + [
            f"{support_slope} = ({sw['l0']} - {sw['l1']}) / ({sw['lb0']} - {sw['lb1']})",
            f"{resistance_slope} = ({sw['h0']} - {sw['h1']}) / ({sw['hb0']} - {sw['hb1']})",
        ]
        if ascending:
            both = f"({sw['l0']} > {sw['l1']}) and ({sw['h0']} > {sw['h1']})"
        else:
            both = f"({sw['l0']} < {sw['l1']}) and ({sw['h0']} < {sw['h1']})"
        parallel = f"math.abs({support_slope} - {resistance_slope}) <= {sw['atr']} * {_pine_num(slope_tol)}"
        lines.append(f"{state} = ({both}) and ({parallel})")
        formed = f"({state}) and (not {state}[1])"
        if ascending:
            support_value = f"chSupportVal{suffix}"
            lines.append(f"{support_value} = {sw['l0']} + {support_slope} * (bar_index - {sw['lb0']})")
            trigger = f"close < {support_value}"
        else:
            resistance_value = f"chResistVal{suffix}"
            lines.append(f"{resistance_value} = {sw['h0']} + {resistance_slope} * (bar_index - {sw['hb0']})")
            trigger = f"close > {resistance_value}"
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
        return lines + foa_lines, var

    return _builder


def _b_false_breakout(bullish_reversal: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        window = int(params.get("window", 20))
        box_atr_mult = float(params.get("box_atr_mult", 2.0))
        max_bars_outside = int(params.get("max_bars_outside", 3))
        atr_v = f"fbAtr{suffix}"
        rng = f"fbRange{suffix}"
        boxed = f"fbBoxed{suffix}"
        box_high = f"fbBoxHigh{suffix}"
        box_low = f"fbBoxLow{suffix}"
        box_ended = f"fbBoxEnded{suffix}"
        broke_out = f"fbBrokeOut{suffix}"
        bars_since = f"fbBarsSince{suffix}"
        already_fired = f"fbAlreadyFired{suffix}"
        back_inside = f"fbBackInside{suffix}"
        var = f"fb{suffix}"
        lines = [
            f"{atr_v} = ta.rma(ta.tr(true), 14)",
            f"{rng} = ta.highest(high, {window}) - ta.lowest(low, {window})",
            f"{boxed} = {rng} <= {atr_v} * {_pine_num(box_atr_mult)}",
            f"var float {box_high} = na",
            f"var float {box_low} = na",
            f"if {boxed}",
            f"    {box_high} := ta.highest(high, {window})",
            f"    {box_low} := ta.lowest(low, {window})",
            f"{box_ended} = (not {boxed}) and {boxed}[1]",
            f"{broke_out} = " + (f"close < {box_low}" if bullish_reversal else f"close > {box_high}"),
            f"var int {bars_since} = 999999",
            f"var bool {already_fired} = false",
            f"if {box_ended}",
            f"    {already_fired} := false",
            f"    {bars_since} := 999999",
            f"if {broke_out} and not {box_ended}",
            f"    {bars_since} := 0",
            f"else",
            f"    {bars_since} := {bars_since} + 1",
            f"{back_inside} = (close >= {box_low}) and (close <= {box_high})",
            f"{var} = {back_inside} and ({bars_since} <= {max_bars_outside}) and (not {already_fired})",
            f"if {var}",
            f"    {already_fired} := true",
        ]
        return lines, var

    return _builder


def _b_saucer(is_top: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        window = int(params.get("window", 30))
        extreme_fn = "highestbars" if is_top else "lowestbars"
        extreme_val_fn = "ta.highest" if is_top else "ta.lowest"
        pos_var = f"sauPos{suffix}"
        frac_var = f"sauFrac{suffix}"
        extreme_var = f"sauExtreme{suffix}"
        endpoint_avg = f"sauEndAvg{suffix}"
        var = f"sau{suffix}"
        lines = [
            f"{pos_var} = ta.{extreme_fn}(close, {window})",
            f"{frac_var} = ({pos_var} + {window - 1}) / {window - 1}.0",
            f"{extreme_var} = {extreme_val_fn}(close, {window})",
            f"{endpoint_avg} = (close + close[{window - 1}]) / 2",
        ]
        centered = f"({frac_var} >= 0.3) and ({frac_var} <= 0.7)"
        concave = f"{extreme_var} > {endpoint_avg}" if is_top else f"{extreme_var} < {endpoint_avg}"
        lines.append(f"{var} = ({concave}) and ({centered})")
        return lines, var

    return _builder


def _b_rectangle(ascending: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        window = int(params.get("window", 20))
        box_atr_mult = float(params.get("box_atr_mult", 2.0))
        trend_lookback = int(params.get("trend_lookback", 30))
        atr_v = f"rectAtr{suffix}"
        rng = f"rectRange{suffix}"
        boxed = f"rectBoxed{suffix}"
        extreme = f"rectExtreme{suffix}"
        box_ended = f"rectBoxEnded{suffix}"
        prior_trend = f"rectPriorTrend{suffix}"
        formed_var = f"rectFormed{suffix}"
        lines = [
            f"{atr_v} = ta.rma(ta.tr(true), 14)",
            f"{rng} = ta.highest(high, {window}) - ta.lowest(low, {window})",
            f"{boxed} = {rng} <= {atr_v} * {_pine_num(box_atr_mult)}",
            f"var float {extreme} = na",
        ]
        if ascending:
            lines += [f"if {boxed}", f"    {extreme} := ta.highest(high, {window})"]
            lines.append(f"{prior_trend} = close[{window}] > close[{window + trend_lookback}]")
            trigger = f"close > {extreme}"
        else:
            lines += [f"if {boxed}", f"    {extreme} := ta.lowest(low, {window})"]
            lines.append(f"{prior_trend} = close[{window}] < close[{window + trend_lookback}]")
            trigger = f"close < {extreme}"
        lines.append(f"{box_ended} = (not {boxed}) and {boxed}[1]")
        lines.append(f"{formed_var} = {box_ended} and {prior_trend}")
        foa_lines, var = _b_first_occurrence_after_lines(suffix, formed_var, trigger)
        return lines + foa_lines, var

    return _builder


def _b_cup_with_handle(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
    cup_window = int(params.get("cup_window", 40))
    handle_window = int(params.get("handle_window", 10))
    handle_atr_mult = float(params.get("handle_atr_mult", 1.5))
    atr_v = f"cwhAtr{suffix}"
    pos_var = f"cwhPos{suffix}"
    frac_var = f"cwhFrac{suffix}"
    extreme_var = f"cwhExtreme{suffix}"
    endpoint_avg = f"cwhEndAvg{suffix}"
    cup_state = f"cwhCupState{suffix}"
    cup_recent = f"cwhCupRecent{suffix}"
    handle_range = f"cwhHandleRange{suffix}"
    is_handle = f"cwhIsHandle{suffix}"
    state = f"cwhState{suffix}"
    handle_high = f"cwhHandleHigh{suffix}"
    lines = [
        f"{atr_v} = ta.rma(ta.tr(true), 14)",
        f"{pos_var} = ta.lowestbars(close, {cup_window})",
        f"{frac_var} = ({pos_var} + {cup_window - 1}) / {cup_window - 1}.0",
        f"{extreme_var} = ta.lowest(close, {cup_window})",
        f"{endpoint_avg} = (close + close[{cup_window - 1}]) / 2",
        f"{cup_state} = ({extreme_var} < {endpoint_avg}) and ({frac_var} >= 0.3) and ({frac_var} <= 0.7)",
        f"{cup_recent} = ta.highest(({cup_state} ? 1.0 : 0.0)[{handle_window}], {cup_window}) > 0",
        f"{handle_range} = ta.highest(high, {handle_window}) - ta.lowest(low, {handle_window})",
        f"{is_handle} = {handle_range} <= {atr_v} * {_pine_num(handle_atr_mult)}",
        f"{state} = {cup_recent} and {is_handle}",
        f"var float {handle_high} = na",
        f"if {is_handle}",
        f"    {handle_high} := ta.highest(high, {handle_window})",
    ]
    formed = f"({state}) and (not {state}[1])"
    trigger = f"close > {handle_high}"
    foa_lines, var = _b_first_occurrence_after_lines(suffix, formed, trigger)
    return lines + foa_lines, var


def _b_harmonic_state(suffix: str, params: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """engine/harmonic_patterns.py::_merged_swing_events()と同じ「高値/安値
    どちらの確定スイングも時系列順にマージした直近6点」をPineのvar状態機械
    で再現する(p0=最新...p5=6つ前)。"""
    lookback = int(params.get("lookback", 5))
    hraw = f"hmSHRaw{suffix}"
    lraw = f"hmSLRaw{suffix}"
    levels = [f"hmP{i}{suffix}" for i in range(6)]
    ishigh = [f"hmP{i}H{suffix}" for i in range(6)]
    lines = [
        f"{hraw} = ta.pivothigh(high, {lookback}, {lookback})",
        f"{lraw} = ta.pivotlow(low, {lookback}, {lookback})",
    ]
    for lv in levels:
        lines.append(f"var float {lv} = na")
    for ih in ishigh:
        lines.append(f"var bool {ih} = na")

    def push_block(raw_var: str, is_high_literal: str) -> list[str]:
        block = []
        for i in range(5, 0, -1):
            block.append(f"    {levels[i]} := {levels[i - 1]}")
            block.append(f"    {ishigh[i]} := {ishigh[i - 1]}")
        block.append(f"    {levels[0]} := {raw_var}")
        block.append(f"    {ishigh[0]} := {is_high_literal}")
        return block

    lines.append(f"if not na({hraw})")
    lines += push_block(hraw, "true")
    lines.append(f"if not na({lraw})")
    lines += push_block(lraw, "false")
    just_confirmed = f"(not na({hraw})) or (not na({lraw}))"
    return lines, {"levels": levels, "ishigh": ishigh, "just_confirmed": just_confirmed}


def _b_harmonic_pattern(
    is_bullish: bool,
    ab_xa_range: tuple[float, float],
    d_xa_range: tuple[float, float],
    bc_ab_range: tuple[float, float] = (0.30, 0.95),
    cd_bc_range: tuple[float, float] = (1.00, 8.00),
):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tolerance = float(params.get("tolerance", 0.1))
        lines, names = _b_harmonic_state(suffix, params)
        levels, ishigh, just_confirmed = names["levels"], names["ishigh"], names["just_confirmed"]
        x, a, b, c, d = levels[4], levels[3], levels[2], levels[1], levels[0]
        xh, ah, bh, ch, dh = ishigh[4], ishigh[3], ishigh[2], ishigh[1], ishigh[0]
        var = f"harm{suffix}"
        if is_bullish:
            alternating = f"(not {xh}) and ({ah}) and (not {bh}) and ({ch}) and (not {dh})"
            xa, ab, bc, cd = f"({a} - {x})", f"({a} - {b})", f"({c} - {b})", f"({c} - {d})"
            d_retrace = f"(({a} - {d}) / {xa})"
        else:
            alternating = f"({xh}) and (not {ah}) and ({bh}) and (not {ch}) and ({dh})"
            xa, ab, bc, cd = f"({x} - {a})", f"({b} - {a})", f"({b} - {c})", f"({d} - {c})"
            d_retrace = f"(({d} - {a}) / {xa})"
        ab_xa = f"({ab} / {xa})"
        bc_ab = f"({bc} / {ab})"
        cd_bc = f"({cd} / {bc})"
        valid_legs = f"({xa} > 0) and ({ab} > 0) and ({bc} > 0) and ({cd} > 0)"

        def within(expr: str, lo: float, hi: float) -> str:
            return f"(({expr} >= {_pine_num(lo - tolerance)}) and ({expr} <= {_pine_num(hi + tolerance)}))"

        ratios_match = (
            f"{within(ab_xa, *ab_xa_range)} and {within(bc_ab, *bc_ab_range)} and "
            f"{within(cd_bc, *cd_bc_range)} and {within(d_retrace, *d_xa_range)}"
        )
        cond = f"({just_confirmed}) and ({alternating}) and ({valid_legs}) and ({ratios_match})"
        lines.append(f"{var} = {cond}")
        return lines, var

    return _builder


def _b_ab_cd(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tolerance = float(params.get("tolerance", 0.15))
        lines, names = _b_harmonic_state(suffix, params)
        levels, ishigh, just_confirmed = names["levels"], names["ishigh"], names["just_confirmed"]
        a, b, c, d = levels[3], levels[2], levels[1], levels[0]
        ah, bh, ch, dh = ishigh[3], ishigh[2], ishigh[1], ishigh[0]
        var = f"abcd{suffix}"
        if bullish:
            alternating = f"({ah}) and (not {bh}) and ({ch}) and (not {dh})"
            ab, bc, cd = f"({a} - {b})", f"({c} - {b})", f"({c} - {d})"
        else:
            alternating = f"(not {ah}) and ({bh}) and (not {ch}) and ({dh})"
            ab, bc, cd = f"({b} - {a})", f"({b} - {c})", f"({d} - {c})"
        valid = f"({ab} > 0) and ({bc} > 0) and ({cd} > 0)"
        bc_ab = f"({bc} / {ab})"
        cd_ab = f"({cd} / {ab})"

        def within(expr: str, lo: float, hi: float) -> str:
            return f"(({expr} >= {_pine_num(lo - tolerance)}) and ({expr} <= {_pine_num(hi + tolerance)}))"

        ratios_match = f"{within(bc_ab, 0.382, 0.886)} and {within(cd_ab, 0.85, 1.15)}"
        cond = f"({just_confirmed}) and ({alternating}) and ({valid}) and ({ratios_match})"
        lines.append(f"{var} = {cond}")
        return lines, var

    return _builder


def _b_three_drives(is_bearish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tolerance = float(params.get("tolerance", 0.15))
        lines, names = _b_harmonic_state(suffix, params)
        levels, ishigh, just_confirmed = names["levels"], names["ishigh"], names["just_confirmed"]
        p0, p1, p2, p3, p4, p5 = levels[5], levels[4], levels[3], levels[2], levels[1], levels[0]
        p0h, p1h, p2h, p3h, p4h, p5h = ishigh[5], ishigh[4], ishigh[3], ishigh[2], ishigh[1], ishigh[0]
        var = f"td{suffix}"
        if is_bearish:
            alternating = f"(not {p0h}) and ({p1h}) and (not {p2h}) and ({p3h}) and (not {p4h}) and ({p5h})"
            drive1, correction1 = f"({p1} - {p0})", f"({p1} - {p2})"
            drive2, correction2 = f"({p3} - {p2})", f"({p3} - {p4})"
            drive3 = f"({p5} - {p4})"
            ascending = f"({p2} > {p0}) and ({p3} > {p1}) and ({p4} > {p2}) and ({p5} > {p3})"
        else:
            alternating = f"({p0h}) and (not {p1h}) and ({p2h}) and (not {p3h}) and ({p4h}) and (not {p5h})"
            drive1, correction1 = f"({p0} - {p1})", f"({p2} - {p1})"
            drive2, correction2 = f"({p2} - {p3})", f"({p4} - {p3})"
            drive3 = f"({p4} - {p5})"
            ascending = f"({p2} < {p0}) and ({p3} < {p1}) and ({p4} < {p2}) and ({p5} < {p3})"
        valid = f"({drive1} > 0) and ({correction1} > 0) and ({drive2} > 0) and ({correction2} > 0) and ({drive3} > 0)"
        correction1_ratio = f"({correction1} / {drive1})"
        drive2_ratio = f"({drive2} / {correction1})"
        correction2_ratio = f"({correction2} / {drive2})"
        drive3_ratio = f"({drive3} / {correction2})"

        def within(expr: str, lo: float, hi: float) -> str:
            return f"(({expr} >= {_pine_num(lo - tolerance)}) and ({expr} <= {_pine_num(hi + tolerance)}))"

        ratios_match = (
            f"{within(correction1_ratio, 0.618, 0.786)} and {within(drive2_ratio, 1.13, 1.618)} and "
            f"{within(correction2_ratio, 0.618, 0.786)} and {within(drive3_ratio, 1.13, 1.618)}"
        )
        cond = f"({just_confirmed}) and ({alternating}) and ({ascending}) and ({valid}) and ({ratios_match})"
        lines.append(f"{var} = {cond}")
        return lines, var

    return _builder


# ---------------------------------------------------------------------------
# 以下、ictカテゴリ(28件)のPine変換用builder群 - engine/smc_indicators.py・
# engine/chart_patterns.py(equal_high/low)・engine/derived_indicators.py
# (dist_*/first_retest系)の各実装を移植したもの。
# ---------------------------------------------------------------------------


def _b_smc_swing_state(suffix: str, params: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """engine/smc_indicators.pyの_last_confirmed_level/_previous_confirmed_
    levelと同じ「直近の確定スイング高値/安値とその1つ前」だけを保持する
    (パラメータ名は"length"、chart_patternカテゴリの_b_swing_state_fullの
    "swing_lookback"とは異なる点に注意 - engine/conditions.pyのliquidity_
    sweep/bos_choch/mss登録がそのまま"length"を使っているため)。"""
    lookback = int(params.get("length", 5))
    hraw = f"smcHRaw{suffix}"
    lraw = f"smcLRaw{suffix}"
    h0, h1 = f"smcH0{suffix}", f"smcH1{suffix}"
    l0, l1 = f"smcL0{suffix}", f"smcL1{suffix}"
    lines = [
        f"{hraw} = ta.pivothigh(high, {lookback}, {lookback})",
        f"{lraw} = ta.pivotlow(low, {lookback}, {lookback})",
        f"var float {h0} = na", f"var float {h1} = na",
        f"var float {l0} = na", f"var float {l1} = na",
        f"if not na({hraw})",
        f"    {h1} := {h0}",
        f"    {h0} := {hraw}",
        f"if not na({lraw})",
        f"    {l1} := {l0}",
        f"    {l0} := {lraw}",
    ]
    return lines, {"hraw": hraw, "lraw": lraw, "h0": h0, "h1": h1, "l0": l0, "l1": l1}


def _b_liquidity_sweep(bearish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, sw = _b_smc_swing_state(suffix, params)
        var = f"ls{suffix}"
        if bearish:
            lines.append(f"{var} = (high > {sw['h0']}) and (close < {sw['h0']})")
        else:
            lines.append(f"{var} = (low < {sw['l0']}) and (close > {sw['l0']})")
        return lines, var

    return _builder


def _b_bos_choch(bearish: bool, is_choch: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        break_basis = str(params.get("break_basis", "close"))
        lines, sw = _b_smc_swing_state(suffix, params)
        var = f"bc{suffix}"
        broke = f"bcBroke{suffix}"
        fresh = f"bcFresh{suffix}"
        if bearish:
            break_price = "low" if break_basis == "wick" else "close"
            recent, prev = sw["l0"], sw["l1"]
            lines.append(f"{broke} = {break_price} < {recent}")
            trend_expr = f"{recent} > {prev}" if is_choch else f"{recent} <= {prev}"
        else:
            break_price = "high" if break_basis == "wick" else "close"
            recent, prev = sw["h0"], sw["h1"]
            lines.append(f"{broke} = {break_price} > {recent}")
            trend_expr = f"{recent} < {prev}" if is_choch else f"{recent} >= {prev}"
        lines.append(f"{fresh} = ({broke}) and (not {broke}[1])")
        lines.append(f"{var} = ({fresh}) and ({trend_expr}) and (not na({prev}))")
        return lines, var

    return _builder


def _b_fvg(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"fvg{suffix}"
        expr = "high[2] < low" if bullish else "low[2] > high"
        return [f"{var} = {expr}"], var

    return _builder


def _b_order_block(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"ob{suffix}"
        if bullish:
            cond = "(close[1] < open[1]) and (close > open) and ((close - open) > (open[1] - close[1]))"
        else:
            cond = "(close[1] > open[1]) and (close < open) and ((open - close) > (close[1] - open[1]))"
        return [f"{var} = {cond}"], var

    return _builder


_BULLISH_OB_EXPR = "(close[1] < open[1]) and (close > open) and ((close - open) > (open[1] - close[1]))"
_BEARISH_OB_EXPR = "(close[1] > open[1]) and (close < open) and ((open - close) > (close[1] - open[1]))"


def _b_breaker_block(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"bb{suffix}"
        tracked = f"bbTracked{suffix}"
        broken = f"bbBroken{suffix}"
        if bullish:
            ob_flag, zone_expr = _BEARISH_OB_EXPR, "math.max(open[1], close[1])"
            break_cond, retest_cond = f"close > {tracked}", f"low <= {tracked}"
        else:
            ob_flag, zone_expr = _BULLISH_OB_EXPR, "math.min(open[1], close[1])"
            break_cond, retest_cond = f"close < {tracked}", f"high >= {tracked}"
        return [
            f"var float {tracked} = na",
            f"var bool {broken} = false",
            f"if {ob_flag}",
            f"    {tracked} := {zone_expr}",
            f"    {broken} := false",
            f"if {break_cond}",
            f"    {broken} := true",
            f"{var} = {broken} and ({retest_cond})",
        ], var

    return _builder


def _b_mitigation_block(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"mb{suffix}"
        tracked = f"mbTracked{suffix}"
        broken = f"mbBroken{suffix}"
        if bullish:
            ob_flag = _BEARISH_OB_EXPR
            break_cond, retest_cond = f"close > {tracked}", f"low <= {tracked}"
        else:
            ob_flag = _BULLISH_OB_EXPR
            break_cond, retest_cond = f"close < {tracked}", f"high >= {tracked}"
        return [
            f"var float {tracked} = na",
            f"var bool {broken} = false",
            f"if {ob_flag}",
            f"    {tracked} := open[1]",
            f"    {broken} := false",
            f"if {break_cond}",
            f"    {broken} := true",
            f"{var} = {broken} and ({retest_cond})",
        ], var

    return _builder


def _b_equal_extreme(is_high: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tolerance_atr_mult = float(params.get("tolerance_atr_mult", 0.3))
        lines, sw = _b_swing_state_full(suffix, params)
        var = f"eq{suffix}"
        if is_high:
            cond = f"(not na({sw['hraw']})) and (math.abs({sw['h0']} - {sw['h1']}) <= {sw['atr']} * {_pine_num(tolerance_atr_mult)})"
        else:
            cond = f"(not na({sw['lraw']})) and (math.abs({sw['l0']} - {sw['l1']}) <= {sw['atr']} * {_pine_num(tolerance_atr_mult)})"
        lines = lines + [f"{var} = {cond}"]
        return lines, var

    return _builder


def _b_dist_order_block(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"dob{suffix}"
        tracked = f"dobTracked{suffix}"
        if bullish:
            ob_flag, zone_expr = _BULLISH_OB_EXPR, "math.min(open, close)"
        else:
            ob_flag, zone_expr = _BEARISH_OB_EXPR, "math.max(open, close)"
        return [
            f"var float {tracked} = na",
            f"if {ob_flag}",
            f"    {tracked} := {zone_expr}",
            f"{var} = math.abs(close - {tracked})",
        ], var

    return _builder


def _b_dist_fvg(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        var = f"dfvg{suffix}"
        tracked = f"dfvgTracked{suffix}"
        fvg_flag = "high[2] < low" if bullish else "low[2] > high"
        zone_expr = "high[2]" if bullish else "low[2]"
        return [
            f"var float {tracked} = na",
            f"if {fvg_flag}",
            f"    {tracked} := {zone_expr}",
            f"{var} = math.abs(close - {tracked})",
        ], var

    return _builder


def _b_dist_bos(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        lines, sw = _b_smc_swing_state(suffix, params)
        var = f"dbos{suffix}"
        level = sw["h0"] if bullish else sw["l0"]
        lines.append(f"{var} = math.abs(close - {level})")
        return lines, var

    return _builder


def _b_fvg_first_retest(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tracked = f"ffrTracked{suffix}"
        fvg_flag = "high[2] < low" if bullish else "low[2] > high"
        zone_expr = "high[2]" if bullish else "low[2]"
        touch_expr = f"low <= {tracked}" if bullish else f"high >= {tracked}"
        lines = [
            f"var float {tracked} = na",
            f"if {fvg_flag}",
            f"    {tracked} := {zone_expr}",
        ]
        foa_lines, var = _b_first_occurrence_after_lines(suffix, fvg_flag, touch_expr)
        return lines + foa_lines, var

    return _builder


def _b_order_block_first_retest(bullish: bool):
    def _builder(suffix: str, params: dict[str, Any]) -> tuple[list[str], str]:
        tracked = f"obfrTracked{suffix}"
        if bullish:
            ob_flag, zone_expr = _BULLISH_OB_EXPR, "math.min(open, close)"
            touch_expr = f"low <= {tracked}"
        else:
            ob_flag, zone_expr = _BEARISH_OB_EXPR, "math.max(open, close)"
            touch_expr = f"high >= {tracked}"
        lines = [
            f"var float {tracked} = na",
            f"if {ob_flag}",
            f"    {tracked} := {zone_expr}",
        ]
        foa_lines, var = _b_first_occurrence_after_lines(suffix, ob_flag, touch_expr)
        return lines + foa_lines, var

    return _builder


# 指標id -> (真偽系かどうか, builder)。真偽系(kind="boolean_signal")は
# 「一致」演算子で1/0と比較する規則(engine/indicator_pool.py参照、UIの
# ConditionRow.tsxも同じ規則)なので、Pineでは数値比較ではなく式そのもの/
# その否定として展開する。
SUPPORTED_CONDITION_INDICATORS: dict[str, tuple[bool, Any]] = {
    "close": (False, _b_price("close")),
    "open": (False, _b_price("open")),
    "high": (False, _b_price("high")),
    "low": (False, _b_price("low")),
    "candle_body": (False, _b_candle_body),
    "prev_day_high": (False, _b_prev_day_high),
    "prev_day_low": (False, _b_prev_day_low),
    "prev_day_mid": (False, _b_prev_day_mid),
    "highest_high": (False, _b_highest_high),
    "lowest_low": (False, _b_lowest_low),
    "ema": (False, _b_ema),
    "sma": (False, _b_sma),
    "rsi": (False, _b_rsi),
    "atr": (False, _b_atr),
    "bollinger_upper": (False, _b_bollinger("upper")),
    "bollinger_middle": (False, _b_bollinger("middle")),
    "bollinger_lower": (False, _b_bollinger("lower")),
    "macd_line": (False, _b_macd_line),
    "macd_signal": (False, _b_macd_signal),
    "stochastic_k": (False, _b_stochastic_k),
    "stochastic_d": (False, _b_stochastic_d),
    "adx": (False, _b_dmi("adx")),
    "plus_di": (False, _b_dmi("plus_di")),
    "minus_di": (False, _b_dmi("minus_di")),
    "bullish_candle": (True, _b_bool("close > open")),
    "bearish_candle": (True, _b_bool("close < open")),
    "doji": (True, _b_doji),
    "marubozu_bullish": (True, _b_marubozu(True)),
    "marubozu_bearish": (True, _b_marubozu(False)),
    "engulfing_bullish": (True, _b_engulfing(True)),
    "engulfing_bearish": (True, _b_engulfing(False)),
    "inside_bar": (True, _b_inside_bar),
    "outside_bar": (True, _b_bool("(high > high[1]) and (low < low[1])")),
    "gap_up": (True, _b_gap(True)),
    "gap_down": (True, _b_gap(False)),
    "hour": (False, _b_hour),
    "weekday": (False, _b_weekday),
    "month": (False, _b_month),
    "killzone_asian": (True, _b_killzone(8, 10, None)),
    "killzone_london": (True, _b_killzone(7, 10, "Europe/London")),
    "killzone_newyork": (True, _b_killzone(7, 10, "America/New_York")),
    "killzone_london_close": (True, _b_killzone(15, 17, "Europe/London")),
    "minutes_since_london_open": (False, _b_minutes_since_open("Europe/London", 7)),
    "minutes_since_ny_open": (False, _b_minutes_since_open("America/New_York", 7)),
    # --- indicatorカテゴリ(183件) ---
    "obv": (False, _b_obv),
    "mfi": (False, _b_mfi),
    "vwap": (False, _b_vwap),
    "ad_line": (False, _b_ad_line),
    "cmf": (False, _b_cmf),
    "supertrend_line": (False, _b_supertrend_line),
    "supertrend_direction": (False, _b_supertrend_direction),
    "supertrend_flip_bullish": (True, _b_supertrend_flip(True)),
    "supertrend_flip_bearish": (True, _b_supertrend_flip(False)),
    "parabolic_sar_line": (False, _b_parabolic_sar_line),
    "parabolic_sar_direction": (False, _b_parabolic_sar_direction),
    "cci": (False, _b_cci),
    "williams_r": (False, _b_williams_r),
    "choppiness_index": (False, _b_choppiness_index),
    "aroon_up": (False, _b_aroon("up")),
    "aroon_down": (False, _b_aroon("down")),
    "aroon_oscillator": (False, _b_aroon("oscillator")),
    "keltner_upper": (False, _b_keltner("upper")),
    "keltner_middle": (False, _b_keltner("middle")),
    "keltner_lower": (False, _b_keltner("lower")),
    "donchian_mid": (False, _b_donchian_mid),
    "donchian_percent_position": (False, _b_donchian_percent_position),
    "highest_close": (False, _b_highest_close),
    "lowest_close": (False, _b_lowest_close),
    "fib_level": (False, _b_fib_level),
    "dist_to_fib": (False, _b_dist_to_fib),
    "bb_percent_b": (False, _b_bb_percent_b),
    "bb_width": (False, _b_bb_width),
    "bb_width_percent": (False, _b_bb_width_percent),
    "bb_squeeze": (True, _b_bb_squeeze),
    "bb_expansion": (True, _b_bb_expansion),
    "dist_to_ema_atr_ratio": (False, _b_dist_to_ema_atr_ratio),
    "dist_close_ema_pct": (False, _b_dist_close_ema_pct),
    "rolling_mean_high": (False, _b_rolling_mean_high),
    "rolling_mean_low": (False, _b_rolling_mean_low),
    "atr_rolling_mean": (False, _b_atr_rolling_mean),
    "atr_deviation": (False, _b_atr_deviation),
    "close_rolling_std": (False, _b_close_rolling_std),
    "historical_volatility": (False, _b_historical_volatility),
    "rsi_rolling_mean": (False, _b_rsi_rolling_mean),
    "rsi_deviation": (False, _b_rsi_deviation),
    "adx_rolling_mean": (False, _b_adx_rolling_mean),
    "macd_rolling_mean": (False, _b_macd_rolling_mean),
    "percentile_rank_rsi": (False, _b_percentile_rank_rsi),
    "percentile_rank_atr": (False, _b_percentile_rank_atr),
    "zscore_close": (False, _b_zscore("close")),
    "zscore_rsi": (False, _b_zscore("rsi")),
    "zscore_atr": (False, _b_zscore("atr")),
    "is_max_rsi_of_n": (True, _b_is_max_rsi_of_n),
    "is_min_atr_of_n": (True, _b_is_min_atr_of_n),
    "ema_roc": (False, _b_ema_roc),
    "ema_slope": (False, _b_ema_slope),
    "ema_slope_degrees": (False, _b_ema_slope_degrees),
    "atr_roc": (False, _b_atr_roc),
    "ema_perfect_order_bullish": (True, _b_ema_perfect_order(True, False)),
    "ema_perfect_order_bearish": (True, _b_ema_perfect_order(False, False)),
    "ema_perfect_order_broken_bullish": (True, _b_ema_perfect_order(True, True)),
    "ema_perfect_order_broken_bearish": (True, _b_ema_perfect_order(False, True)),
    "bull_power": (False, _b_bull_power),
    "bear_power": (False, _b_bear_power),
    "chaikin_oscillator": (False, _b_chaikin_oscillator),
    "cmo": (False, _b_cmo),
    "connors_rsi": (False, _b_connors_rsi),
    "coppock_curve": (False, _b_coppock_curve),
    "correlation_close_ema": (False, _b_correlation_close_ema),
    "correlation_oscillator": (False, _b_correlation_oscillator),
    "macd_histogram": (False, _b_macd_histogram),
    "macd_divergence_bullish": (True, _b_macd_divergence(True)),
    "macd_divergence_bearish": (True, _b_macd_divergence(False)),
    "rsi_divergence_bullish": (True, _b_rsi_divergence(True)),
    "rsi_divergence_bearish": (True, _b_rsi_divergence(False)),
    "ichimoku_tenkan": (False, _b_ichimoku_tenkan),
    "ichimoku_kijun": (False, _b_ichimoku_kijun),
    "ichimoku_senkou_a": (False, _b_ichimoku_senkou("a")),
    "ichimoku_senkou_b": (False, _b_ichimoku_senkou("b")),
    "ichimoku_price_vs_cloud": (False, _b_ichimoku_price_vs_cloud),
    "ichimoku_kumo_twist_bullish": (True, _b_ichimoku_kumo_twist(True)),
    "ichimoku_kumo_twist_bearish": (True, _b_ichimoku_kumo_twist(False)),
    "ichimoku_chikou_signal": (False, _b_ichimoku_chikou_signal),
    "linreg_value": (False, _b_linreg_value),
    "linreg_slope_atr_ratio": (False, _b_linreg_slope_atr_ratio),
    "linreg_angle_degrees": (False, _b_linreg_angle_degrees),
    "linreg_upper": (False, _b_linreg_band(1.0)),
    "linreg_lower": (False, _b_linreg_band(-1.0)),
    "ttm_squeeze": (True, _b_ttm_squeeze),
    "ttm_squeeze_release": (True, _b_ttm_squeeze_release),
    "adr": (False, _b_adr),
    "pivot": (False, _b_global("pivot")),
    "pivot_r1": (False, _b_global("pivotR1")),
    "pivot_s1": (False, _b_global("pivotS1")),
    "camarilla_r1": (False, _b_global("camarillaR1")),
    "camarilla_r2": (False, _b_global("camarillaR2")),
    "camarilla_r3": (False, _b_global("camarillaR3")),
    "camarilla_r4": (False, _b_global("camarillaR4")),
    "camarilla_s1": (False, _b_global("camarillaS1")),
    "camarilla_s2": (False, _b_global("camarillaS2")),
    "camarilla_s3": (False, _b_global("camarillaS3")),
    "camarilla_s4": (False, _b_global("camarillaS4")),
    "woodie_pivot": (False, _b_global("woodiePivot")),
    "woodie_r1": (False, _b_global("woodieR1")),
    "woodie_r2": (False, _b_global("woodieR2")),
    "woodie_r3": (False, _b_global("woodieR3")),
    "woodie_r4": (False, _b_global("woodieR4")),
    "woodie_s1": (False, _b_global("woodieS1")),
    "woodie_s2": (False, _b_global("woodieS2")),
    "woodie_s3": (False, _b_global("woodieS3")),
    "woodie_s4": (False, _b_global("woodieS4")),
    "fib_pivot": (False, _b_global("fibPivot")),
    "fib_pivot_r1": (False, _b_global("fibR1")),
    "fib_pivot_r2": (False, _b_global("fibR2")),
    "fib_pivot_r3": (False, _b_global("fibR3")),
    "fib_pivot_s1": (False, _b_global("fibS1")),
    "fib_pivot_s2": (False, _b_global("fibS2")),
    "fib_pivot_s3": (False, _b_global("fibS3")),
    # --- price_actionカテゴリ(76件) ---
    "large_bullish_candle": (True, _b_large_candle(True)),
    "large_bearish_candle": (True, _b_large_candle(False)),
    "small_bullish_candle": (True, _b_small_candle(True)),
    "small_bearish_candle": (True, _b_small_candle(False)),
    "long_upper_wick": (True, _b_long_wick(True)),
    "long_lower_wick": (True, _b_long_wick(False)),
    "no_upper_wick": (True, _b_no_wick(True)),
    "no_lower_wick": (True, _b_no_wick(False)),
    "pin_bar_bullish": (True, _b_pin_bar(True)),
    "pin_bar_bearish": (True, _b_pin_bar(False)),
    "hammer": (True, _b_hammer_shape),
    "hanging_man": (True, _b_hammer_shape),
    "inverted_hammer": (True, _b_inverted_hammer_shape),
    "shooting_star": (True, _b_inverted_hammer_shape),
    "long_legged_doji": (True, _b_long_legged_doji),
    "dragonfly_doji": (True, _b_dragonfly_doji),
    "gravestone_doji": (True, _b_gravestone_doji),
    "spinning_top": (True, _b_spinning_top),
    "kicker_bullish": (True, _b_kicker(True)),
    "kicker_bearish": (True, _b_kicker(False)),
    "belt_hold_bullish": (True, _b_belt_hold(True)),
    "belt_hold_bearish": (True, _b_belt_hold(False)),
    "abandoned_baby_bullish": (True, _b_abandoned_baby(True)),
    "abandoned_baby_bearish": (True, _b_abandoned_baby(False)),
    "harami_bullish": (True, _b_harami(True)),
    "harami_bearish": (True, _b_harami(False)),
    "three_inside_up": (True, _b_three_inside(True)),
    "three_inside_down": (True, _b_three_inside(False)),
    "three_outside_up": (True, _b_three_outside(True)),
    "three_outside_down": (True, _b_three_outside(False)),
    "tweezer_top": (True, _b_tweezer(True)),
    "tweezer_bottom": (True, _b_tweezer(False)),
    "morning_star": (True, _b_morning_evening_star(True)),
    "evening_star": (True, _b_morning_evening_star(False)),
    "three_white_soldiers": (True, _b_three_soldiers_crows(True)),
    "three_black_crows": (True, _b_three_soldiers_crows(False)),
    "rising_three_methods": (True, _b_three_methods(True)),
    "falling_three_methods": (True, _b_three_methods(False)),
    "three_line_strike_bullish": (True, _b_three_line_strike(True)),
    "three_line_strike_bearish": (True, _b_three_line_strike(False)),
    "tasuki_gap_upside": (True, _b_tasuki_gap(True)),
    "tasuki_gap_downside": (True, _b_tasuki_gap(False)),
    "consecutive_bullish_candles": (True, _b_consecutive_candles(True)),
    "consecutive_bearish_candles": (True, _b_consecutive_candles(False)),
    "consecutive_higher_highs": (True, _b_consecutive_hh_ll(True)),
    "consecutive_lower_lows": (True, _b_consecutive_hh_ll(False)),
    "body_larger_than_average": (True, _b_body_larger_than_average),
    "wick_ratio_at_least": (True, _b_wick_ratio_at_least),
    "body_ratio_at_least": (True, _b_body_ratio_at_least),
    "avg_body_size": (False, _b_avg_body_size),
    "max_body_size": (False, _b_max_body_size),
    "min_body_size": (False, _b_min_body_size),
    "body_size_std": (False, _b_body_size_std),
    "avg_upper_wick": (False, _b_avg_upper_wick),
    "avg_lower_wick": (False, _b_avg_lower_wick),
    "is_max_body_of_n": (True, _b_is_max_body_of_n),
    "nr4": (True, _b_nr(4)),
    "nr7": (True, _b_nr(7)),
    "volume_climax_bullish": (True, _b_volume_climax(True)),
    "volume_climax_bearish": (True, _b_volume_climax(False)),
    "percentile_rank_body": (False, _b_percentile_rank_body),
    "dist_to_round_number": (False, _b_dist_to_round_number),
    "higher_high": (True, _b_swing_structure("higher_high")),
    "lower_high": (True, _b_swing_structure("lower_high")),
    "higher_low": (True, _b_swing_structure("higher_low")),
    "lower_low": (True, _b_swing_structure("lower_low")),
    "first_pullback_after_breakout_bullish": (True, _b_first_pullback_after_breakout(True)),
    "first_pullback_after_breakout_bearish": (True, _b_first_pullback_after_breakout(False)),
    "today_new_high": (True, _b_today_new_extreme(True)),
    "today_new_low": (True, _b_today_new_extreme(False)),
    "today_range_position": (False, _b_today_range_position),
    "today_range_pct_of_adr": (False, _b_today_range_pct_of_adr),
    "ha_bullish": (True, _b_ha_bullish),
    "ha_bearish": (True, _b_ha_bearish),
    "ha_strong_bullish": (True, _b_ha_strong(True)),
    "ha_strong_bearish": (True, _b_ha_strong(False)),
    # --- chart_patternカテゴリ(46件) ---
    "double_top_breakdown": (True, _b_double_top_bottom(False)),
    "double_bottom_breakout": (True, _b_double_top_bottom(True)),
    "triple_top_breakdown": (True, _b_triple_top_bottom(False)),
    "triple_bottom_breakout": (True, _b_triple_top_bottom(True)),
    "head_and_shoulders_breakdown": (True, _b_head_shoulders(False)),
    "inverse_head_and_shoulders_breakout": (True, _b_head_shoulders(True)),
    "ascending_triangle_breakout": (True, _b_ascending_triangle),
    "descending_triangle_breakdown": (True, _b_descending_triangle),
    "symmetrical_triangle_breakout_bullish": (True, _b_symmetrical_triangle(True)),
    "symmetrical_triangle_breakout_bearish": (True, _b_symmetrical_triangle(False)),
    "rising_wedge_breakdown": (True, _b_wedge(True)),
    "falling_wedge_breakout": (True, _b_wedge(False)),
    "bull_flag_breakout": (True, _b_flag_pennant(True, False)),
    "bear_flag_breakdown": (True, _b_flag_pennant(False, False)),
    "bullish_pennant_breakout": (True, _b_flag_pennant(True, True)),
    "bearish_pennant_breakdown": (True, _b_flag_pennant(False, True)),
    "in_range_box": (True, _b_in_range_box),
    "range_box_breakout_bullish": (True, _b_range_box_breakout(True)),
    "range_box_breakdown_bearish": (True, _b_range_box_breakout(False)),
    "uptrend_line_break": (True, _b_trendline_break(True)),
    "downtrend_line_break": (True, _b_trendline_break(False)),
    "ascending_channel_break": (True, _b_channel_break(True)),
    "descending_channel_break": (True, _b_channel_break(False)),
    "false_breakout_bullish_reversal": (True, _b_false_breakout(True)),
    "false_breakout_bearish_reversal": (True, _b_false_breakout(False)),
    "saucer_top": (True, _b_saucer(True)),
    "saucer_bottom": (True, _b_saucer(False)),
    "ascending_rectangle_breakout": (True, _b_rectangle(True)),
    "descending_rectangle_breakdown": (True, _b_rectangle(False)),
    "broadening_formation_breakout_bullish": (True, _b_broadening(True)),
    "broadening_formation_breakout_bearish": (True, _b_broadening(False)),
    "diamond_formation_breakout_bullish": (True, _b_diamond(True)),
    "diamond_formation_breakout_bearish": (True, _b_diamond(False)),
    "cup_with_handle_breakout": (True, _b_cup_with_handle),
    "gartley_bullish": (True, _b_harmonic_pattern(True, (0.55, 0.68), (0.70, 0.85))),
    "gartley_bearish": (True, _b_harmonic_pattern(False, (0.55, 0.68), (0.70, 0.85))),
    "bat_bullish": (True, _b_harmonic_pattern(True, (0.35, 0.55), (0.82, 0.93))),
    "bat_bearish": (True, _b_harmonic_pattern(False, (0.35, 0.55), (0.82, 0.93))),
    "butterfly_bullish": (True, _b_harmonic_pattern(True, (0.72, 0.85), (1.13, 1.71))),
    "butterfly_bearish": (True, _b_harmonic_pattern(False, (0.72, 0.85), (1.13, 1.71))),
    "crab_bullish": (True, _b_harmonic_pattern(True, (0.35, 0.68), (1.50, 1.75))),
    "crab_bearish": (True, _b_harmonic_pattern(False, (0.35, 0.68), (1.50, 1.75))),
    "ab_cd_bullish": (True, _b_ab_cd(True)),
    "ab_cd_bearish": (True, _b_ab_cd(False)),
    "three_drives_bullish": (True, _b_three_drives(False)),
    "three_drives_bearish": (True, _b_three_drives(True)),
    # --- ictカテゴリ(28件) ---
    "fvg_bullish": (True, _b_fvg(True)),
    "fvg_bearish": (True, _b_fvg(False)),
    "order_block_bullish": (True, _b_order_block(True)),
    "order_block_bearish": (True, _b_order_block(False)),
    "liquidity_sweep_bullish": (True, _b_liquidity_sweep(False)),
    "liquidity_sweep_bearish": (True, _b_liquidity_sweep(True)),
    "bos_bullish": (True, _b_bos_choch(False, False)),
    "choch_bullish": (True, _b_bos_choch(False, True)),
    "bos_bearish": (True, _b_bos_choch(True, False)),
    "choch_bearish": (True, _b_bos_choch(True, True)),
    "mss_bullish": (True, _b_bos_choch(False, True)),
    "mss_bearish": (True, _b_bos_choch(True, True)),
    "breaker_block_bullish": (True, _b_breaker_block(True)),
    "breaker_block_bearish": (True, _b_breaker_block(False)),
    "mitigation_block_bullish": (True, _b_mitigation_block(True)),
    "mitigation_block_bearish": (True, _b_mitigation_block(False)),
    "equal_high": (True, _b_equal_extreme(True)),
    "equal_low": (True, _b_equal_extreme(False)),
    "dist_order_block_bullish": (False, _b_dist_order_block(True)),
    "dist_order_block_bearish": (False, _b_dist_order_block(False)),
    "dist_fvg_bullish": (False, _b_dist_fvg(True)),
    "dist_fvg_bearish": (False, _b_dist_fvg(False)),
    "dist_bos_bullish": (False, _b_dist_bos(True)),
    "dist_bos_bearish": (False, _b_dist_bos(False)),
    "fvg_first_retest_bullish": (True, _b_fvg_first_retest(True)),
    "fvg_first_retest_bearish": (True, _b_fvg_first_retest(False)),
    "order_block_first_retest_bullish": (True, _b_order_block_first_retest(True)),
    "order_block_first_retest_bearish": (True, _b_order_block_first_retest(False)),
}

for _price_field in ("close", "high", "low"):
    for _target_name in _DISTANCE_TARGET_BUILDERS:
        SUPPORTED_CONDITION_INDICATORS[f"dist_{_price_field}_{_target_name}"] = (
            False,
            _b_distance(_price_field, _target_name),
        )

for _series_name, _base_builder in _PINE_LEVEL_BUILDERS.items():
    SUPPORTED_CONDITION_INDICATORS[f"{_series_name}_rising"] = (True, _b_rising(_base_builder))
    SUPPORTED_CONDITION_INDICATORS[f"{_series_name}_falling"] = (True, _b_falling(_base_builder))
    SUPPORTED_CONDITION_INDICATORS[f"{_series_name}_consecutive_rising"] = (True, _b_consecutive_rising(_base_builder))
    SUPPORTED_CONDITION_INDICATORS[f"{_series_name}_consecutive_falling"] = (True, _b_consecutive_falling(_base_builder))

_OPERAND_KEY = tuple[str, tuple[tuple[str, Any], ...]]


class _PineConditionTranslator:
    """condition_tree(AND/OR/NOT + Condition葉)を1つのPine真偽式に変換し、
    参照した指標の宣言行(重複排除済み)を別に集める。同じ(指標, パラメータ)
    の組み合わせが複数の条件で使われても、宣言は1回だけになる。"""

    def __init__(self) -> None:
        self._operand_cache: dict[_OPERAND_KEY, tuple[str, bool]] = {}
        self.decl_lines: list[str] = []
        self._counter = 0

    def collect_unsupported(self, node: dict[str, Any]) -> set[str]:
        if "op" in node:
            found: set[str] = set()
            for child in node["children"]:
                found |= self.collect_unsupported(child)
            return found
        found = set()
        if node["indicator"] not in SUPPORTED_CONDITION_INDICATORS:
            found.add(node["indicator"])
        if isinstance(node["value"], str) and node["value"] not in SUPPORTED_CONDITION_INDICATORS:
            found.add(node["value"])
        return found

    def _resolve_operand(self, indicator: str, params: dict[str, Any]) -> tuple[str, bool]:
        key: _OPERAND_KEY = (indicator, tuple(sorted(params.items())))
        if key in self._operand_cache:
            return self._operand_cache[key]

        is_bool, builder = SUPPORTED_CONDITION_INDICATORS[indicator]
        suffix = f"_{self._counter}"
        self._counter += 1
        lines, expr = builder(suffix, params)
        self.decl_lines.extend(lines)
        self._operand_cache[key] = (expr, is_bool)
        return expr, is_bool

    def _translate_condition(self, node: dict[str, Any]) -> str:
        left_expr, left_is_bool = self._resolve_operand(node["indicator"], node.get("params", {}))
        value = node["value"]
        operator = node["operator"]

        if left_is_bool:
            if operator != "==":
                raise ValueError(
                    f"論理系の指標「{node['indicator']}」は「一致」演算子でのみPine変換に対応しています"
                    f"(指定された演算子: {operator})"
                )
            target = float(value) if not isinstance(value, str) else None
            if target == 1.0:
                return f"({left_expr})"
            if target == 0.0:
                return f"(not {left_expr})"
            raise ValueError(f"論理系の指標「{node['indicator']}」の比較値は0か1のみ対応しています")

        if isinstance(value, str):
            right_expr, _right_is_bool = self._resolve_operand(value, node.get("value_params", {}))
        else:
            right_expr = _pine_num(float(value))

        if operator in (">", "<", ">=", "<=", "=="):
            return f"({left_expr} {operator} {right_expr})"
        if operator == "crosses_above":
            return f"ta.crossover({left_expr}, {right_expr})"
        if operator == "crosses_below":
            return f"ta.crossunder({left_expr}, {right_expr})"
        raise ValueError(f"未対応の演算子です(Pine変換): {operator}")

    def translate(self, node: dict[str, Any]) -> str:
        if "op" in node:
            child_exprs = [self.translate(child) for child in node["children"]]
            if node["op"] == "NOT":
                return f"(not {child_exprs[0]})"
            joiner = " and " if node["op"] == "AND" else " or "
            return "(" + joiner.join(child_exprs) + ")"
        return self._translate_condition(node)


def generate_pine_script_from_condition_tree(
    p: dict[str, Any],
    *,
    symbol: str = "USDJPY",
    timeframe: str = "15m",
    strategy_title: str | None = None,
) -> str:
    """condition_tree(手動条件ビルダー/自動探索が実際に使う唯一の方式)から
    Pine Scriptを生成する。対応範囲はこのモジュールの上のコメント参照。
    エントリーは engine/backtest_engine.py の即エントリー方式(条件が
    成立した足の次の足の始値でそのままエントリー)と同じ - Pineの
    strategy.entry()はcalc_on_every_tick=false時デフォルトで次の足の
    始値約定なので、確認待ちの状態機械を組む必要すらない。"""
    condition_tree = p.get("condition_tree")
    long_tree = p.get("long_condition_tree")
    short_tree = p.get("short_condition_tree")
    dual_direction = condition_tree is None and (long_tree is not None or short_tree is not None)
    if condition_tree is None and not dual_direction:
        raise ValueError(
            "condition_tree・long_condition_tree・short_condition_treeのいずれも設定されていません。"
        )

    entry_method = str(p.get("entry_method", "market")).lower()
    if entry_method != "market":
        raise ValueError(
            f"entry_method=\"{entry_method}\"のPine Script化は未対応です。成行(market)エントリーのみ対応しています。"
        )

    sl_basis = str(p.get("sl_basis", "signal_candle"))
    tp_basis = str(p.get("tp_basis", "rr"))
    if sl_basis not in ("signal_candle", "fixed_pips"):
        raise ValueError(f"sl_basis=\"{sl_basis}\"のPine Script化は未対応です(signal_candle/fixed_pipsのみ対応)。")
    if tp_basis not in ("rr", "fixed_pips"):
        raise ValueError(f"tp_basis=\"{tp_basis}\"のPine Script化は未対応です(rr/fixed_pipsのみ対応)。")

    pip_size = float(p.get("pip_size", 0.01))
    rr = float(p.get("rr", 1.2))
    sl_fixed_pips = float(p.get("sl_fixed_pips", 20.0))
    tp_fixed_pips = float(p.get("tp_fixed_pips", 20.0))
    use_weekend_exit = bool(p.get("use_weekend_exit", True))
    weekend_exit_hour = int(p.get("weekend_exit_hour", 4))
    use_daily_exit = bool(p.get("use_daily_exit", False))
    daily_exit_hour = int(p.get("daily_exit_hour", 4))

    inputs_block = f'''pipSize = input.float({_pine_num(pip_size)}, "Pip size")
rr = input.float({_pine_num(rr)}, "Risk:Reward")
slFixedPips = input.float({_pine_num(sl_fixed_pips)}, "Fixed SL (pips)")
tpFixedPips = input.float({_pine_num(tp_fixed_pips)}, "Fixed TP (pips)")
useWeekendExit = input.bool({_pine_bool(use_weekend_exit)}, "Weekend exit")
weekendExitHour = input.int({int(weekend_exit_hour)}, "Weekend exit hour (JST, Sat)")
useDailyExit = input.bool({_pine_bool(use_daily_exit)}, "Daily exit")
dailyExitHour = input.int({int(daily_exit_hour)}, "Daily exit hour (JST)")'''

    daily_levels_block = f'''// engine/technical_indicators.py::daily_reference_levels()と同じ
// JST午前0時境界の「前日」を再現する(TradingView自身の日足セッションは
// この銘柄/フィードによってJST0時と一致しない場合があり、実際に
// request.security(..., "D", ...)ベースでは前日高値/安値が食い違う
// ケースが確認されたため、暦日の切り替わりを自前でJST基準検出する
// 方式に切り替えた - このモジュールのdocstring参照)。
newDay = ta.change(dayofmonth(time, "{TIMEZONE}")) != 0
var float todayHighAcc = na
var float todayLowAcc = na
var float prevDayHigh = na
var float prevDayLow = na
var float prevDayClose = na
if newDay
    prevDayHigh := todayHighAcc
    prevDayLow := todayLowAcc
    prevDayClose := close[1]
    todayHighAcc := high
    todayLowAcc := low
else
    todayHighAcc := math.max(nz(todayHighAcc, high), high)
    todayLowAcc := math.min(nz(todayLowAcc, low), low)

dayRange = prevDayHigh - prevDayLow

pivot = (prevDayHigh + prevDayLow + prevDayClose) / 3
pivotR1 = 2 * pivot - prevDayLow
pivotS1 = 2 * pivot - prevDayHigh

camarillaR1 = prevDayClose + dayRange * 1.1 / 12
camarillaR2 = prevDayClose + dayRange * 1.1 / 6
camarillaR3 = prevDayClose + dayRange * 1.1 / 4
camarillaR4 = prevDayClose + dayRange * 1.1 / 2
camarillaS1 = prevDayClose - dayRange * 1.1 / 12
camarillaS2 = prevDayClose - dayRange * 1.1 / 6
camarillaS3 = prevDayClose - dayRange * 1.1 / 4
camarillaS4 = prevDayClose - dayRange * 1.1 / 2

woodiePivot = (prevDayHigh + prevDayLow + 2 * prevDayClose) / 4
woodieR1 = 2 * woodiePivot - prevDayLow
woodieS1 = 2 * woodiePivot - prevDayHigh
woodieR2 = woodiePivot + dayRange
woodieS2 = woodiePivot - dayRange
woodieR3 = prevDayHigh + 2 * (woodiePivot - prevDayLow)
woodieS3 = prevDayLow - 2 * (prevDayHigh - woodiePivot)
woodieR4 = woodieR3 + (woodieR2 - woodieR1)
woodieS4 = woodieS3 - (woodieS1 - woodieS2)

fibPivot = (prevDayHigh + prevDayLow + prevDayClose) / 3
fibR1 = fibPivot + 0.382 * dayRange
fibR2 = fibPivot + 0.618 * dayRange
fibR3 = fibPivot + 1.0 * dayRange
fibS1 = fibPivot - 0.382 * dayRange
fibS2 = fibPivot - 0.618 * dayRange
fibS3 = fibPivot - 1.0 * dayRange'''

    if dual_direction:
        # ユーザー要望:「ロングとショートどちらもエントリーするストラテジー
        # のコード出力ができない」 - 以前は片方向(direction=long/short固定)
        # の戦略にしか対応しておらず、long_condition_tree/short_condition_tree
        # を両方持つ戦略は問答無用でエラーにしていた。engine/backtest_engine.py
        # ::_run_dual_direction_backtestの実際の規則(両方同じ足で成立したら
        # どちらも取らない、ポジションは同時に1つだけ)をそのまま再現する。
        translator = _PineConditionTranslator()
        unsupported = set()
        if long_tree is not None:
            unsupported |= translator.collect_unsupported(long_tree)
        if short_tree is not None:
            unsupported |= translator.collect_unsupported(short_tree)
        if unsupported:
            raise ValueError(
                "次の指標/条件はPine Script変換にまだ対応していません: " + "、".join(sorted(unsupported)) + "。"
                "対応済みの指標はインジケーター(EMA/SMA/RSI/ATR/MACD/ボリンジャーバンド/"
                "ストキャスティクス/ADX)、価格データ、基本的なローソク足パターンのみです"
                "(ハーモニックパターン・チャートパターン・ICT系は未対応)。"
            )
        long_expr = translator.translate(long_tree) if long_tree is not None else "false"
        short_expr = translator.translate(short_tree) if short_tree is not None else "false"
        decl_block = "\n".join(translator.decl_lines)

        title = strategy_title or f"StrategyLab {symbol} {timeframe} (condition_tree, long+short)"

        if sl_basis == "signal_candle":
            # シグナルが出たこの足自身の高値/安値が基準 - エントリー価格に
            # 依存しないため、発注時点(シグナル足)で既に確定できる。
            sl_arm_expr_long = "low"
            sl_arm_expr_short = "high"
            # 発注済みの値をそのまま保持する(varなので何もしなくても足を
            # またいで値は残るが、下のif分岐で必ず何か代入する構造上、
            # ここでarmedSl自身を代入する - "low"/"high"と書くと決済確定
            # した"この足"自身の高安を誤って読んでしまうので注意)。
            sl_refine_expr_long = "armedSl"
            sl_refine_expr_short = "armedSl"
        else:
            # エントリー価格(=約定するまで未確定)に依存するため、発注時点
            # ではこの足の終値を仮のエントリー価格として見積もっておき、
            # 約定確定後に実際のposition_avg_priceで引き直す。
            sl_arm_expr_long = "close - slFixedPips * pipSize"
            sl_arm_expr_short = "close + slFixedPips * pipSize"
            sl_refine_expr_long = "strategy.position_avg_price - slFixedPips * pipSize"
            sl_refine_expr_short = "strategy.position_avg_price + slFixedPips * pipSize"

        if tp_basis == "rr":
            tp_arm_expr_long = "close + (close - armedSl) * rr"
            tp_arm_expr_short = "close - (armedSl - close) * rr"
            tp_refine_expr_long = "strategy.position_avg_price + (strategy.position_avg_price - armedSl) * rr"
            tp_refine_expr_short = "strategy.position_avg_price - (armedSl - strategy.position_avg_price) * rr"
        else:
            tp_arm_expr_long = "close + tpFixedPips * pipSize"
            tp_arm_expr_short = "close - tpFixedPips * pipSize"
            tp_refine_expr_long = "strategy.position_avg_price + tpFixedPips * pipSize"
            tp_refine_expr_short = "strategy.position_avg_price - tpFixedPips * pipSize"

        return f'''//@version=5
// Auto-generated by Strategy Lab (engine/pine_generator.py::generate_pine_script_from_condition_tree)
// condition_tree(AND/OR/NOT)から生成、Long+Short同時運用版 - 対応範囲・
// 既知の非互換点はengine/pine_generator.pyのモジュールdocstring/コメントを
// 参照。
// Source: {symbol} {timeframe}, long+short
strategy("{title}", overlay=true, default_qty_type=strategy.fixed, default_qty_value=1, calc_on_every_tick=false)

// ---- Inputs ----
{inputs_block}

tzHour = hour(time, "{TIMEZONE}")
tzDow = dayofweek(time, "{TIMEZONE}")

// ---- Daily levels(prev_day_high/low/mid等使用時のみ意味を持つ) - JST
// 午前0時境界の暦日切り替わりを自前検出(TradingView自身の日足セッション
// は使わない、このモジュールのdocstring参照) ----
{daily_levels_block}

// ---- 条件ツリーから変換した指標(Long/Shortで共有する指標は1回だけ宣言) ----
{decl_block}

// ---- エントリー条件(条件ビルダーの内容そのまま) ----
longSignal = {long_expr}
shortSignal = {short_expr}

// ---- 即エントリー + SL/TP同時発注: ポジションは同時に1つだけ、Long/Short
// が同じ足で両方成立した場合はどちらも取らない(engine/backtest_engine.py
// ::_run_dual_direction_backtestと同じ規則)。strategy.entry()はcalc_on_
// every_tick=false時デフォルトで次の足の始値約定するため、確認待ちの
// 状態機械は不要。bar_index>=250: エンジン側も指標のウォームアップとして
// 最初の250本はエントリー判定そのものを一切行わない(for i in range(250,
// len(df))) - ここを省くと、チャートの読み込み開始直後の未成熟な
// EMA/RSIの値で誤発注してしまう(実際に踏んだ不具合)。
// SL/TPをエントリーと同時にこの足のうちに発注しておくのが重要な点:
// strategy.exit()のstop/limit注文は、発注したその足自身の(スクリプト
// 実行時点で既に確定済みの)高値/安値には反応できず、次の足以降の値動き
// にしか反応しない。エントリーが確定するのは次の足の始値なので、SL/TPを
// 「シグナルが出たこの足」のうちに(=エントリーより1本前倒しで)発注して
// おけば、エントリーが確定する足自身の値動きにも正しく反応できる
// (実際に踏んだ不具合: エントリー確定足でSLを大きく超えていたのに数本
// 先まで決済されなかった) ----
var float armedSl = na
var float armedTp = na
var bool wasInPosition = false
var int prevClosedTrades = 0

// ---- この足の中で(直前の足までに発注済みのSL/TPが)同じ足のうちに
// 決済まで完了した場合、この足では新規シグナルの武装を一切行わない
// (engine/backtest_engine.py::_run_dual_direction_backtestの`if in_
// position: ...; continue`と同じ規則 - ポジションを持っていた足では、
// たとえその足の中で即決済されたとしても、その足でのシグナル監視自体を
// スキップし、次の足から再開する)。wasInPositionだけでは「この足の中で
// 新規発注→同じ足で即決済」というラウンドトリップを検知できない
// (position_sizeがこの足の終わりには0に戻ってしまうため)ので、
// strategy.closedtradesの増分で判定する ----
closedThisBar = strategy.closedtrades > prevClosedTrades

if strategy.position_size == 0 and not wasInPosition and not closedThisBar and bar_index >= 250
    if longSignal and not shortSignal
        candidateSlLong = {sl_arm_expr_long}
        // engine/backtest_engine.pyの`if risk_distance > 0:`と同じ安全装置
        // (シグナル足の高安がちょうど翌足の始値=このcloseと同値になる稀な
        // ケースでリスク距離0の建玉を防ぐ、実際に踏んだ不一致) - このガード
        // が無いとPine側だけリスク距離0のエントリーが成立してしまう。
        if close > candidateSlLong
            armedSl := candidateSlLong
            armedTp := {tp_arm_expr_long}
            strategy.entry("Long", strategy.long)
            strategy.exit("Exit", "Long", stop=armedSl, limit=armedTp)
    else if shortSignal and not longSignal
        candidateSlShort = {sl_arm_expr_short}
        if close < candidateSlShort
            armedSl := candidateSlShort
            armedTp := {tp_arm_expr_short}
            strategy.entry("Short", strategy.short)
            strategy.exit("Exit", "Short", stop=armedSl, limit=armedTp)

isLongPos = strategy.position_size > 0
justEntered = strategy.position_size != 0 and not wasInPosition
exitLabel = isLongPos ? "Long" : "Short"

// ---- エントリーが確定した足で、発注時点ではまだ未確定だった実際の約定
// 価格(position_avg_price)を使ってSL/TPを引き直す(この足自身の反応は
// 発注時点=1本前の足での見積もり値で既に判定済み、以降の足からはこの
// 正確な値で反応する) ----
if justEntered
    armedSl := isLongPos ? {sl_refine_expr_long} : {sl_refine_expr_short}
    armedTp := isLongPos ? {tp_refine_expr_long} : {tp_refine_expr_short}
    strategy.exit("Exit", exitLabel, stop=armedSl, limit=armedTp)

// ---- 週末/日次決済はSL/TPより優先 ----
if strategy.position_size != 0 and useWeekendExit and tzDow == 7 and tzHour >= weekendExitHour
    strategy.close(exitLabel, comment="Weekend")
else if strategy.position_size != 0 and useDailyExit and tzHour == dailyExitHour
    strategy.close(exitLabel, comment="DailyExit")

wasInPosition := strategy.position_size != 0
prevClosedTrades := strategy.closedtrades

plotshape(longSignal, title="Long Signal", style=shape.triangleup, location=location.belowbar, color=color.lime, size=size.tiny)
plotshape(shortSignal, title="Short Signal", style=shape.triangledown, location=location.abovebar, color=color.orange, size=size.tiny)
if longSignal and not shortSignal
    alert("StrategyLab: " + syminfo.ticker + " long signal", alert.freq_once_per_bar_close)
if shortSignal and not longSignal
    alert("StrategyLab: " + syminfo.ticker + " short signal", alert.freq_once_per_bar_close)
'''

    direction = str(p.get("direction", "short")).lower()
    if direction not in ("short", "long"):
        raise ValueError(f"未対応のdirectionです: {direction}")

    translator = _PineConditionTranslator()
    unsupported = translator.collect_unsupported(condition_tree)
    if unsupported:
        raise ValueError(
            "次の指標/条件はPine Script変換にまだ対応していません: " + "、".join(sorted(unsupported)) + "。"
            "対応済みの指標はインジケーター(EMA/SMA/RSI/ATR/MACD/ボリンジャーバンド/"
            "ストキャスティクス/ADX)、価格データ、基本的なローソク足パターンのみです"
            "(ハーモニックパターン・チャートパターン・ICT系は未対応)。"
        )
    signal_expr = translator.translate(condition_tree)

    title = strategy_title or f"StrategyLab {symbol} {timeframe} (condition_tree, {direction})"
    strategy_side = "strategy.long" if direction == "long" else "strategy.short"
    label = "Long" if direction == "long" else "Short"

    decl_block = "\n".join(translator.decl_lines)

    if sl_basis == "signal_candle":
        # シグナルが出たこの足自身の高値/安値が基準 - エントリー価格に
        # 依存しないため、発注時点(シグナル足)で既に確定できる。
        # engine/backtest_engine.py::_resolve_sl の signal_candle と同じ規則。
        sl_arm_expr = "low" if direction == "long" else "high"
        # 発注済みの値をそのまま保持する("low"/"high"と書くと決済確定した
        # "この足"自身の高安を誤って読んでしまうので、armedSl自身を代入。
        sl_refine_expr = "armedSl"
    else:
        sl_arm_expr = (
            "close - slFixedPips * pipSize" if direction == "long"
            else "close + slFixedPips * pipSize"
        )
        sl_refine_expr = (
            "strategy.position_avg_price - slFixedPips * pipSize" if direction == "long"
            else "strategy.position_avg_price + slFixedPips * pipSize"
        )

    # direction/tp_basisは生成時点で確定しているので、Pine側では実行時分岐
    # ("direction"というPine変数は存在しない)ではなく、ここでどちらの式を
    # 埋め込むか決めてしまう。
    if tp_basis == "rr":
        tp_arm_expr = (
            "close + (close - armedSl) * rr" if direction == "long"
            else "close - (armedSl - close) * rr"
        )
        tp_refine_expr = (
            "strategy.position_avg_price + (strategy.position_avg_price - armedSl) * rr"
            if direction == "long"
            else "strategy.position_avg_price - (armedSl - strategy.position_avg_price) * rr"
        )
    else:
        tp_arm_expr = (
            "close + tpFixedPips * pipSize" if direction == "long"
            else "close - tpFixedPips * pipSize"
        )
        tp_refine_expr = (
            "strategy.position_avg_price + tpFixedPips * pipSize"
            if direction == "long"
            else "strategy.position_avg_price - tpFixedPips * pipSize"
        )

    return f'''//@version=5
// Auto-generated by Strategy Lab (engine/pine_generator.py::generate_pine_script_from_condition_tree)
// condition_tree(AND/OR/NOT)から生成 - 対応範囲・既知の非互換点は
// engine/pine_generator.pyのモジュールdocstring/コメントを参照。
// Source: {symbol} {timeframe}, direction={direction}
strategy("{title}", overlay=true, default_qty_type=strategy.fixed, default_qty_value=1, calc_on_every_tick=false)

// ---- Inputs ----
{inputs_block}

tzHour = hour(time, "{TIMEZONE}")
tzDow = dayofweek(time, "{TIMEZONE}")

// ---- Daily levels(prev_day_high/low/mid等使用時のみ意味を持つ) - JST
// 午前0時境界の暦日切り替わりを自前検出(TradingView自身の日足セッション
// は使わない、このモジュールのdocstring参照) ----
{daily_levels_block}

// ---- 条件ツリーから変換した指標 ----
{decl_block}

// ---- エントリー条件(条件ビルダーの内容そのまま) ----
candidateSignal = {signal_expr}

// ---- 即エントリー + SL/TP同時発注: strategy.entry()はcalc_on_every_tick=
// false時デフォルトで次の足の始値で約定するため、確認待ちの状態機械は
// 不要。bar_index>=250: エンジン側も指標のウォームアップとして最初の250本
// はエントリー判定を一切行わない(for i in range(250, len(df))) - 省くと
// チャート読み込み直後の未成熟なEMA/RSIの値で誤発注する(実際に踏んだ
// 不具合)。
// SL/TPをエントリーと同時にこの足のうちに発注しておくのが重要な点:
// strategy.exit()のstop/limit注文は、発注したその足自身の(スクリプト
// 実行時点で既に確定済みの)高値/安値には反応できず、次の足以降の値動き
// にしか反応しない。エントリーが確定するのは次の足の始値なので、SL/TPを
// 「シグナルが出たこの足」のうちに(=エントリーより1本前倒しで)発注して
// おけば、エントリーが確定する足自身の値動きにも正しく反応できる
// (実際に踏んだ不具合: エントリー確定足でSLを大きく超えていたのに数本
// 先まで決済されなかった) ----
var float armedSl = na
var float armedTp = na
var bool wasInPosition = false
var int prevClosedTrades = 0

// ---- この足の中で(直前の足までに発注済みのSL/TPが)同じ足のうちに
// 決済まで完了した場合、この足では新規シグナルの武装を一切行わない
// (engine/backtest_engine.pyの`if in_position: ...; continue`と同じ規則
// - ポジションを持っていた足では、たとえその足の中で即決済されたとしても
// その足でのシグナル監視自体をスキップし、次の足から再開する)。
// wasInPositionだけでは「この足の中で新規発注→同じ足で即決済」という
// ラウンドトリップを検知できない(position_sizeがこの足の終わりには0に
// 戻ってしまうため)ので、strategy.closedtradesの増分で判定する ----
closedThisBar = strategy.closedtrades > prevClosedTrades

if candidateSignal and strategy.position_size == 0 and not wasInPosition and not closedThisBar and bar_index >= 250
    candidateSl = {sl_arm_expr}
    // engine/backtest_engine.pyの`if risk_distance > 0:`と同じ安全装置
    // (シグナル足の高安がちょうど翌足の始値=このcloseと同値になる稀な
    // ケースでリスク距離0の建玉を防ぐ、実際に踏んだ不一致)。
    if {"close > candidateSl" if direction == "long" else "close < candidateSl"}
        armedSl := candidateSl
        armedTp := {tp_arm_expr}
        strategy.entry("{label}", {strategy_side})
        strategy.exit("Exit", "{label}", stop=armedSl, limit=armedTp)

justEntered = strategy.position_size != 0 and not wasInPosition

// ---- エントリーが確定した足で、発注時点ではまだ未確定だった実際の約定
// 価格(position_avg_price)を使ってSL/TPを引き直す(この足自身の反応は
// 発注時点=1本前の足での見積もり値で既に判定済み、以降の足からはこの
// 正確な値で反応する) ----
if justEntered
    armedSl := {sl_refine_expr}
    armedTp := {tp_refine_expr}
    strategy.exit("Exit", "{label}", stop=armedSl, limit=armedTp)

// ---- 週末/日次決済はSL/TPより優先 ----
if strategy.position_size != 0 and useWeekendExit and tzDow == 7 and tzHour >= weekendExitHour
    strategy.close("{label}", comment="Weekend")
else if strategy.position_size != 0 and useDailyExit and tzHour == dailyExitHour
    strategy.close("{label}", comment="DailyExit")

wasInPosition := strategy.position_size != 0
prevClosedTrades := strategy.closedtrades

plotshape(candidateSignal, title="Signal", style=shape.triangledown, location=location.abovebar, color=color.orange, size=size.tiny)
if candidateSignal
    alert("StrategyLab: " + syminfo.ticker + " {direction} signal", alert.freq_once_per_bar_close)
'''


def generate_pine_script(
    params: dict[str, Any],
    *,
    symbol: str = "USDJPY",
    timeframe: str = "15m",
    strategy_title: str | None = None,
) -> str:
    p = dict(params)

    # condition_tree(AND/OR/NOT条件エンジン - 手動条件ビルダー/自動探索が
    # 実際に使う唯一の方式)は専用の変換関数に委譲する。以前はここで
    # 即エラーにしていたが、これでは今のアプリで組めるほぼ全ての戦略が
    # Pine Script化できなかった(実際に踏んだ不具合、ユーザー報告:
    # 「Trading Viewコード書いてくれる機能実装できる?」)。
    if p.get("condition_tree") or p.get("long_condition_tree") or p.get("short_condition_tree"):
        return generate_pine_script_from_condition_tree(
            p, symbol=symbol, timeframe=timeframe, strategy_title=strategy_title
        )

    title = strategy_title or f"StrategyLab {symbol} {timeframe} ({p.get('entry_trigger', 'breakout')})"

    trigger_expr, filter_exprs = _build_signal_expressions(p)
    # Each filter expression is parenthesized before joining - several (e.g.
    # use_max_body_filter/use_max_wick_filter) contain a top-level "or", and
    # Pine's "and" binds tighter than "or" (same as Python), so without this
    # an unparenthesized "or" would silently escape its intended filter and
    # corrupt the whole AND-chain's boolean logic.
    filters_joined = (
        "\n    and ".join(f"({expr})" for expr in filter_exprs) if filter_exprs else "true"
    )

    weekday_terms = " or ".join(
        f"({pine_name} and tzDow == {_WEEKDAY_TO_PINE_DOW[pine_name]})"
        for pine_name, _py_key, _label in WEEKDAY_INPUT_SPECS
    )

    inputs_block = _render_inputs(p)

    return f'''//@version=5
// Auto-generated by Strategy Lab (engine/pine_generator.py) from a
// backtested params dict - see that module's docstring for the known,
// deliberate departures from exact parity with the Python backtest
// (daily-level session boundary, Bollinger stdev bias, SMC Tier 3
// approximations, weekend/daily-exit vs SL/TP same-bar priority).
// Source: {symbol} {timeframe}, entry_trigger="{p.get('entry_trigger', 'breakout')}"
// Short-only strategy (matches Strategy Lab's engine/backtest_engine.py convention).
strategy("{title}", overlay=true, default_qty_type=strategy.fixed, default_qty_value=1, calc_on_every_tick=false)

// ---- Inputs (defaults = the exact backtested values, all live-adjustable) ----
{inputs_block}

minBodyPrice = minBodyPips * pipSize
emaDistancePrice = emaDistancePips * pipSize

// All hour/weekday checks use JST explicitly (matches the timezone the
// Python backtest's data pipeline runs on), independent of the chart's
// own display timezone setting.
tzHour = hour(time, "{TIMEZONE}")
tzDow = dayofweek(time, "{TIMEZONE}")

sessionOk = sessionStart < sessionEnd ? (tzHour >= sessionStart and tzHour < sessionEnd) : (tzHour >= sessionStart or tzHour < sessionEnd)
weekdayOk = {weekday_terms}
{_INDICATOR_BLOCK}
// ---- Entry trigger + filters (AND-composed, mirrors engine/signal_builder.py) ----
triggerSignal = {trigger_expr}
filtersOk = {filters_joined}
candidateSignal = triggerSignal and filtersOk

// ---- Multi-bar entry state machine (mirrors engine/backtest_engine.py::run_backtest) ----
// A candidate signal marks the bar's high/low as the setup range. If price
// closes below that signal bar's low within lookaheadBars, a short entry
// fires (Pine fills strategy.entry() at the NEXT bar's open by default,
// matching entry_price = open of the bar after the trigger condition).
var float signalLow = na
var float signalHigh = na
var int signalBarIndex = na
var float pendingSlLevel = na

if not na(signalBarIndex)
    barsFromSignal = bar_index - signalBarIndex
    withinBars = barsFromSignal > 0 and barsFromSignal <= lookaheadBars

    if withinBars and close < signalLow
        pendingSlLevel := signalHigh
        strategy.entry("Short", strategy.short)
        signalLow := na
        signalHigh := na
        signalBarIndex := na
    else if barsFromSignal > lookaheadBars
        signalLow := na
        signalHigh := na
        signalBarIndex := na

if na(signalBarIndex) and strategy.position_size == 0 and candidateSignal
    signalLow := low
    signalHigh := high
    signalBarIndex := bar_index

// ---- SL/TP: SL is fixed at the signal bar's high, TP is RR-derived from
// the actual fill price (mirrors run_backtest's stop_price/tp formula) ----
var float tradeSl = na
var float tradeTp = na
var bool wasInPosition = false

justEntered = strategy.position_size != 0 and not wasInPosition
if justEntered
    tradeSl := pendingSlLevel
    tradeTp := strategy.position_avg_price - (tradeSl - strategy.position_avg_price) * rr

// ---- Weekend / daily exit take priority over SL/TP on the same bar ----
if strategy.position_size != 0 and useWeekendExit and tzDow == 7 and tzHour >= weekendExitHour
    strategy.close("Short", comment="Weekend")
else if strategy.position_size != 0 and useDailyExit and tzHour == dailyExitHour
    strategy.close("Short", comment="DailyExit")
else if strategy.position_size != 0
    strategy.exit("Exit", "Short", stop=tradeSl, limit=tradeTp)

wasInPosition := strategy.position_size != 0

// ---- Visuals + alert (use TradingView's "Any alert() function call" option) ----
plotshape(candidateSignal, title="Signal", style=shape.triangledown, location=location.abovebar, color=color.orange, size=size.tiny)
if candidateSignal
    alert("StrategyLab: " + syminfo.ticker + " short signal", alert.freq_once_per_bar_close)
'''
