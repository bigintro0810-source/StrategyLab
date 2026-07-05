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

1. Daily levels (pivot/R1/prev-day-high/low) use TradingView's own
   daily-bar session boundary via request.security(..., "D", ...), NOT
   the JST-midnight boundary engine/technical_indicators.py's
   daily_reference_levels() uses. Pine has no clean way to request "daily
   bars starting at an arbitrary timezone's midnight" - only the
   instrument's native session. These filters/triggers will not fire on
   exactly the same bars as the Python backtest. (ADR itself isn't wired
   to any filter/trigger in the Python engine either, so it's omitted.)
2. Bollinger uses ta.stdev() (population/biased, N denominator) while
   pandas' rolling().std() (used in engine/technical_indicators.py) is
   sample/unbiased (N-1 denominator) - a small numerical difference,
   more noticeable at short periods.
3. SMC Tier 3 (FVG/Order Block/BOS/CHoCH/Liquidity Sweep) is already
   marked "unverified, exploratory" in engine/smc_indicators.py itself -
   the Pine translations here are best-effort, not verified against any
   reference. Order Block specifically: the Python version flags the
   signal on the EARLIER bar using the NEXT bar's data (bearish_order_block
   in engine/smc_indicators.py), which is only possible because Python
   backtesting can look at the whole DataFrame at once. A live (non-
   repainting) Pine script cannot see the next bar, so this generator
   flags it one bar later than the Python engine does - the swing-point
   "collapse consecutive runs" refinement (engine/smc_indicators.py's
   _collapse_consecutive_runs) is also not replicated, so plateau/flat
   extremes may register slightly differently.
4. Entry/exit mechanics: run_backtest's SL/TP are touch-based against each
   bar's high/low, same as Pine's default historical bar-replay behavior,
   but weekend/daily-exit and SL/TP priority on the same bar is
   approximated (weekend/daily exit is evaluated and closed first if due;
   otherwise SL/TP stand) rather than an exact single-engine tie-break.
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


def generate_pine_script(
    params: dict[str, Any],
    *,
    symbol: str = "USDJPY",
    timeframe: str = "15m",
    strategy_title: str | None = None,
) -> str:
    p = dict(params)

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
strategy("{title}", overlay=true, default_qty_type=strategy.fixed_qty, default_qty_value=1, calc_on_every_tick=false)

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
