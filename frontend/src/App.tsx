import { forwardRef, useEffect, useState, type HTMLAttributes, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GridLayout, useContainerWidth, type Layout } from 'react-grid-layout'
import 'react-resizable/css/styles.css'
import {
  createBacktest,
  fetchBacktestResults,
  fetchBacktestStatus,
  fetchIndicators,
  fetchPriceData,
  fetchStrategies,
  fetchStrategyDetail,
} from './api'
import type {
  BacktestResults,
  ConditionOptimizeRange,
  Direction,
  GroupNode,
  OptimizableParam,
  ParamRangeConfig,
} from './types'
import { buildConditionTreeVariants, collectOptimizableConditions, pathIsValid } from './conditionTreeUtils'
import ConditionTreeEditor from './components/ConditionTreeEditor'
import ChartPanel from './components/ChartPanel'
import RankingTable from './components/RankingTable'
import EquityCurveChart from './components/EquityCurveChart'
import DrawdownChart from './components/DrawdownChart'
import MonthlyHeatmap from './components/MonthlyHeatmap'
import OptimizationSurface from './components/OptimizationSurface'
import TradeHistoryTable from './components/TradeHistoryTable'
import YearlyPerformanceChart from './components/YearlyPerformanceChart'
import StatsPanel from './components/StatsPanel'
import StrategySummaryPanel from './components/StrategySummaryPanel'
import SavedStrategiesPanel from './components/SavedStrategiesPanel'

const LAYOUT_STORAGE_KEY = 'strategylab-dashboard-layout-v4'

const DEFAULT_LAYOUT: Layout = [
  { i: 'builder', x: 0, y: 0, w: 3, h: 48, minW: 2, minH: 8 },
  { i: 'chart', x: 3, y: 0, w: 6, h: 16, minW: 3, minH: 8 },
  { i: 'ranking', x: 9, y: 0, w: 3, h: 16, minW: 2, minH: 4 },
  { i: 'equity', x: 3, y: 16, w: 3, h: 9, minW: 2, minH: 4 },
  { i: 'drawdown', x: 6, y: 16, w: 3, h: 9, minW: 2, minH: 4 },
  { i: 'summary', x: 9, y: 16, w: 3, h: 9, minW: 2, minH: 4 },
  { i: 'heatmap', x: 3, y: 25, w: 3, h: 9, minW: 2, minH: 4 },
  { i: 'yearly', x: 6, y: 25, w: 3, h: 9, minW: 2, minH: 4 },
  { i: 'stats', x: 9, y: 25, w: 3, h: 9, minW: 2, minH: 4 },
  { i: 'surface', x: 3, y: 34, w: 6, h: 14, minW: 4, minH: 6 },
  { i: 'trades', x: 9, y: 34, w: 3, h: 14, minW: 2, minH: 6 },
  { i: 'saved', x: 0, y: 48, w: 12, h: 10, minW: 4, minH: 4 },
]

// NOTE (2026-07-06): ema_length/rsi_min/ema_distance_pips/min_body_pips/
// max_body_pips/max_wick_pips/breakout_bars were REMOVED from this list -
// they only feed the legacy fixed-strategy signal builder
// (build_candidate_signal in engine/backtest_engine.py), which only runs
// when condition_tree is absent. This dashboard's builder ALWAYS sends a
// condition_tree (see runMutation below), so sweeping any of those old
// params silently produced N identical ranking rows - a real, confirmed
// no-op bug, not just a missing feature. Every parameter listed here
// actually affects a condition-tree strategy's result regardless of which
// other opt-in features are toggled (rr/lookahead_bars always apply; the
// rest only take effect once their own use_* checkbox above is also on -
// same as directly typing a value into that field would).
const OPTIMIZABLE_PARAMS: OptimizableParam[] = [
  { id: 'rr', label: 'リスクリワード比' },
  { id: 'lookahead_bars', label: '先読みバー数' },
  { id: 'weekend_exit_hour', label: '週末決済時刻' },
  { id: 'daily_exit_hour', label: '日次決済時刻' },
  { id: 'spread_pips', label: 'スプレッド(pips)' },
  { id: 'slippage_pips', label: 'スリッページ(pips)' },
  { id: 'commission_per_trade', label: '手数料(1取引あたり)' },
  { id: 'atr_trailing_length', label: 'ATRトレーリング期間 ※要チェックボックスON' },
  { id: 'atr_trailing_multiplier', label: 'ATRトレーリング倍率 ※要チェックボックスON' },
  { id: 'breakeven_trigger_rr', label: '建値移動トリガーRR ※要チェックボックスON' },
  { id: 'partial_tp_rr', label: '部分利確到達RR ※要チェックボックスON' },
  { id: 'partial_tp_fraction', label: '部分利確割合 ※要チェックボックスON' },
  { id: 'max_dd_stop_pips', label: '最大DDストップ(pips) ※要チェックボックスON' },
  { id: 'consecutive_loss_stop_count', label: '連敗ストップ数 ※要チェックボックスON' },
  { id: 'entry_offset_pips', label: '指値/逆指値オフセット ※要指値/逆指値選択' },
  { id: 'risk_percent', label: 'リスク%(資金管理) ※要チェックボックスON' },
]

const OPTIMIZATION_METRICS = [
  { id: 'net_profit', label: '総利益' },
  { id: 'profit_factor', label: 'PF' },
  { id: 'win_rate', label: '勝率%' },
  { id: 'recovery_factor', label: 'Recovery' },
]

const PARAM_DEFAULTS: Record<string, { min: number; max: number; step: number }> = {
  rr: { min: 1, max: 2, step: 0.2 },
  lookahead_bars: { min: 10, max: 20, step: 5 },
  weekend_exit_hour: { min: 0, max: 6, step: 1 },
  daily_exit_hour: { min: 0, max: 23, step: 1 },
  spread_pips: { min: 0, max: 2, step: 0.5 },
  slippage_pips: { min: 0, max: 2, step: 0.5 },
  commission_per_trade: { min: 0, max: 1, step: 0.1 },
  atr_trailing_length: { min: 7, max: 21, step: 7 },
  atr_trailing_multiplier: { min: 1, max: 3, step: 0.5 },
  breakeven_trigger_rr: { min: 0.3, max: 0.8, step: 0.1 },
  partial_tp_rr: { min: 0.5, max: 1.5, step: 0.25 },
  partial_tp_fraction: { min: 0.2, max: 0.7, step: 0.1 },
  max_dd_stop_pips: { min: 50, max: 150, step: 25 },
  consecutive_loss_stop_count: { min: 2, max: 5, step: 1 },
  entry_offset_pips: { min: 5, max: 20, step: 5 },
  risk_percent: { min: 0.5, max: 2, step: 0.5 },
}

function defaultParamRange(param: string): ParamRangeConfig {
  const d = PARAM_DEFAULTS[param] ?? { min: 1, max: 10, step: 1 }
  return { enabled: false, param, ...d }
}

function buildRangeValues(min: number, max: number, step: number): number[] {
  if (step <= 0 || max < min) return [min]
  const values: number[] = []
  for (let v = min; v <= max + 1e-9; v += step) {
    values.push(Math.round(v * 1000) / 1000)
  }
  return values.length > 0 ? values : [min]
}

function loadLayout(): Layout {
  try {
    const raw = localStorage.getItem(LAYOUT_STORAGE_KEY)
    if (!raw) return DEFAULT_LAYOUT
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed) && parsed.length === DEFAULT_LAYOUT.length) return parsed as Layout
  } catch {
    // ignore malformed saved layout, fall back to default
  }
  return DEFAULT_LAYOUT
}

const NAV_ITEMS = [
  'プロジェクト',
  'データ',
  'ストラテジー',
  'バックテスト',
  '最適化',
  '分析',
  'ランキング',
  'レポート',
  'ツール',
  '設定',
]

const SYMBOLS = ['USDJPY', 'EURJPY', 'GBPJPY', 'AUDJPY', 'AUDUSD', 'EURUSD', 'GBPUSD']
const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']

function defaultTree(): GroupNode {
  return {
    op: 'AND',
    children: [{ indicator: 'close', operator: '>', value: 0, params: {}, value_params: {} }],
  }
}

// react-grid-layout positions/drags/resizes a panel by cloning it with an
// injected ref, className, style, and mouse/touch handlers - they must land
// on the actual outer DOM node, so this forwards everything through instead
// of swallowing it like a plain wrapper component would.
type PanelProps = HTMLAttributes<HTMLDivElement> & { title: string; children: ReactNode }

const Panel = forwardRef<HTMLDivElement, PanelProps>(function Panel(
  { title, children, className, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={['glass-panel flex h-full flex-col', className].filter(Boolean).join(' ')} {...rest}>
      <div className="drag-handle glass-panel-header cursor-move select-none rounded-t-2xl px-3 py-2 text-sm font-semibold tracking-wide text-gray-200">
        {title}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
    </div>
  )
})

function ParamRangeRow({
  label,
  value,
  onChange,
  onRemove,
}: {
  label: string
  value: ParamRangeConfig
  onChange: (next: ParamRangeConfig) => void
  onRemove?: () => void
}) {
  return (
    <div className="space-y-1 rounded-lg border border-white/10 bg-white/[0.02] p-2">
      <label className="flex items-center gap-1.5 text-xs text-gray-300">
        <input
          type="checkbox"
          checked={value.enabled}
          onChange={(e) => onChange({ ...value, enabled: e.target.checked })}
        />
        {label}を最適化
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="ml-auto text-gray-500 hover:text-red-400"
            title="このパラメータ範囲を削除"
          >
            ✕
          </button>
        )}
      </label>
      <div className="grid grid-cols-4 gap-1">
        <select
          className="glass-input col-span-4 rounded-lg px-1.5 py-1 text-xs"
          value={value.param}
          onChange={(e) => {
            const d = PARAM_DEFAULTS[e.target.value] ?? { min: 1, max: 10, step: 1 }
            onChange({ ...value, param: e.target.value, ...d })
          }}
        >
          {OPTIMIZABLE_PARAMS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        <input
          type="number"
          title="最小値"
          className="glass-input rounded-lg px-1 py-1 text-xs"
          value={value.min}
          onChange={(e) => onChange({ ...value, min: Number(e.target.value) })}
        />
        <input
          type="number"
          title="最大値"
          className="glass-input rounded-lg px-1 py-1 text-xs"
          value={value.max}
          onChange={(e) => onChange({ ...value, max: Number(e.target.value) })}
        />
        <input
          type="number"
          title="刻み幅"
          className="glass-input rounded-lg px-1 py-1 text-xs"
          value={value.step}
          onChange={(e) => onChange({ ...value, step: Number(e.target.value) })}
        />
      </div>
    </div>
  )
}

export default function App() {
  const [direction, setDirection] = useState<Direction>('short')
  const [tree, setTree] = useState<GroupNode>(defaultTree())

  // Simultaneous Long+Short mode: evaluates two independent entry trees
  // against one shared position (no hedging). Off by default - preserves
  // the existing single-tree+direction flow exactly.
  const [dualDirectionMode, setDualDirectionMode] = useState(false)
  const [longTree, setLongTree] = useState<GroupNode>(defaultTree())
  const [shortTree, setShortTree] = useState<GroupNode>(defaultTree())

  const [symbol, setSymbol] = useState('USDJPY')
  const [timeframe, setTimeframe] = useState('15m')
  const [mode, setMode] = useState('dev')
  const [jobId, setJobId] = useState<string | null>(null)

  // Chart display timeframe is independent from the backtest timeframe above -
  // you may want to eyeball a strategy on 1h while backtesting on 15m.
  const [chartTimeframe, setChartTimeframe] = useState('15m')
  const [emaLength, setEmaLength] = useState(20)

  // Any number of parameter ranges (not capped at 2) - each independently
  // enabled/disabled, all feeding one N-dimensional grid search on the
  // backend (main.py's itertools.product-based grid was already fully
  // generic; this UI cap was the only limitation). The 3D surface below can
  // only ever plot 2 axes at once, so surfaceParamX/Y pick which 2 of the
  // currently-enabled ranges to visualize.
  const [paramRanges, setParamRanges] = useState<ParamRangeConfig[]>(() => [
    defaultParamRange('rr'),
    defaultParamRange('lookahead_bars'),
  ])
  const addParamRange = () => setParamRanges((prev) => [...prev, defaultParamRange('rr')])
  const removeParamRange = (index: number) => setParamRanges((prev) => prev.filter((_, i) => i !== index))
  const updateParamRange = (index: number, next: ParamRangeConfig) =>
    setParamRanges((prev) => prev.map((r, i) => (i === index ? next : r)))
  const [surfaceParamX, setSurfaceParamX] = useState('rr')
  const [surfaceParamY, setSurfaceParamY] = useState('lookahead_bars')
  const [optimizationMetric, setOptimizationMetric] = useState('net_profit')

  // Node-level condition-tree optimization: sweep one or more specific
  // conditions' own comparison values (e.g. "this RSI threshold, 60-80")
  // rather than a whole BacktestConfig field. Any number of rows, each
  // independently enabled - all enabled rows cross-multiply into the full
  // grid (same composition rule paramRanges already uses). Not supported
  // together with Long+Short同時 dual-direction mode (this only targets the
  // single `tree`, not longTree/shortTree) - UI hides it while
  // dualDirectionMode is on, same precedent as entryMethod.
  const [conditionOptimizeRanges, setConditionOptimizeRanges] = useState<ConditionOptimizeRange[]>(() => [
    { enabled: false, path: null, min: 60, max: 80, step: 5 },
  ])
  const addConditionOptimizeRange = () =>
    setConditionOptimizeRanges((prev) => [...prev, { enabled: false, path: null, min: 60, max: 80, step: 5 }])
  const removeConditionOptimizeRange = (index: number) =>
    setConditionOptimizeRanges((prev) => prev.filter((_, i) => i !== index))
  const updateConditionOptimizeRange = (index: number, next: ConditionOptimizeRange) =>
    setConditionOptimizeRanges((prev) => prev.map((r, i) => (i === index ? next : r)))

  const [rr, setRr] = useState(1.2)
  const [useWeekendExit, setUseWeekendExit] = useState(true)
  const [weekendExitHour, setWeekendExitHour] = useState(4)
  const [useDailyExit, setUseDailyExit] = useState(false)
  const [dailyExitHour, setDailyExitHour] = useState(4)
  const [saveAsName, setSaveAsName] = useState('')

  // Execution cost simulation - all default to 0 (frictionless fills,
  // matching the engine's default) so leaving these untouched reproduces
  // today's existing behavior exactly.
  const [spreadPips, setSpreadPips] = useState(0)
  const [slippagePips, setSlippagePips] = useState(0)
  const [commissionPerTrade, setCommissionPerTrade] = useState(0)

  // ATR trailing stop - off by default (fixed RR-based SL/TP, today's
  // existing behavior unchanged unless opted in).
  const [useAtrTrailingStop, setUseAtrTrailingStop] = useState(false)
  const [atrTrailingLength, setAtrTrailingLength] = useState(14)
  const [atrTrailingMultiplier, setAtrTrailingMultiplier] = useState(2.0)

  // Circuit breakers - both off by default (never pause, today's existing
  // behavior unchanged unless opted in). Confirmed with the user
  // 2026-07-06: both pause-and-resume rather than stopping permanently.
  const [useMaxDdStop, setUseMaxDdStop] = useState(false)
  const [maxDdStopPips, setMaxDdStopPips] = useState(100)
  const [useConsecutiveLossStop, setUseConsecutiveLossStop] = useState(false)
  const [consecutiveLossStopCount, setConsecutiveLossStopCount] = useState(3)
  const [consecutiveLossStopBars, setConsecutiveLossStopBars] = useState(100)

  // Entry order type - "market" (default) is today's unchanged behavior.
  // Not supported together with Long+Short同時 dual-direction mode - the
  // backend rejects that combination, so the UI hides this control while
  // dualDirectionMode is on rather than letting the user reach that error.
  const [entryMethod, setEntryMethod] = useState<'market' | 'limit' | 'stop'>('market')
  const [entryOffsetPips, setEntryOffsetPips] = useState(10)

  // Position sizing - off by default (results stay in raw pips, implied 1
  // lot, today's existing behavior unchanged unless opted in). Confirmed
  // with the user 2026-07-06: JPY/USD account currency switchable, default
  // 1,000,000 JPY capital, all three methods (risk%/fixed lot/compounding)
  // exposed since the user wants all three available.
  const [usePositionSizing, setUsePositionSizing] = useState(false)
  const [positionSizingMethod, setPositionSizingMethod] = useState<'risk_percent' | 'fixed_lot' | 'compounding'>('risk_percent')
  const [initialCapital, setInitialCapital] = useState(1_000_000)
  const [accountCurrency, setAccountCurrency] = useState<'JPY' | 'USD'>('JPY')
  const [riskPercent, setRiskPercent] = useState(1.0)
  const [fixedLotSize, setFixedLotSize] = useState(0.1)
  const [conversionRate, setConversionRate] = useState(150.0)

  // Breakeven stop move and partial profit-taking - both off by default
  // (SL/TP stay exactly as RR-computed at entry, today's existing behavior
  // unchanged unless opted in).
  const [useBreakevenStop, setUseBreakevenStop] = useState(false)
  const [breakevenTriggerRr, setBreakevenTriggerRr] = useState(0.5)
  const [usePartialTp, setUsePartialTp] = useState(false)
  const [partialTpRr, setPartialTpRr] = useState(1.0)
  const [partialTpFraction, setPartialTpFraction] = useState(0.5)

  const [layout, setLayout] = useState<Layout>(loadLayout)
  const { width: gridWidth, containerRef: gridContainerRef, mounted: gridMounted } = useContainerWidth()

  const handleLayoutChange = (next: Layout) => {
    setLayout(next)
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(next))
  }

  const resetLayout = () => {
    localStorage.removeItem(LAYOUT_STORAGE_KEY)
    setLayout(DEFAULT_LAYOUT)
  }

  const queryClient = useQueryClient()

  const indicatorsQuery = useQuery({ queryKey: ['indicators'], queryFn: fetchIndicators })
  const priceQuery = useQuery({
    queryKey: ['price-data', symbol, chartTimeframe],
    queryFn: () => fetchPriceData(symbol, chartTimeframe, 300),
  })
  const strategiesQuery = useQuery({ queryKey: ['strategies'], queryFn: fetchStrategies })

  const loadStrategyMutation = useMutation({
    mutationFn: fetchStrategyDetail,
    onSuccess: (detail) => {
      setSymbol(detail.symbol)
      setTimeframe(detail.timeframe)
      setMode(detail.mode)
      if (detail.params.direction) setDirection(detail.params.direction)
      if (detail.params.long_condition_tree || detail.params.short_condition_tree) {
        setDualDirectionMode(true)
        if (detail.params.long_condition_tree) setLongTree(detail.params.long_condition_tree)
        if (detail.params.short_condition_tree) setShortTree(detail.params.short_condition_tree)
      } else {
        setDualDirectionMode(false)
        if (detail.params.condition_tree) setTree(detail.params.condition_tree as GroupNode)
      }
      if (typeof detail.params.rr === 'number') setRr(detail.params.rr)
      if (typeof detail.params.use_weekend_exit === 'boolean') setUseWeekendExit(detail.params.use_weekend_exit)
      if (typeof detail.params.weekend_exit_hour === 'number') setWeekendExitHour(detail.params.weekend_exit_hour)
      if (typeof detail.params.use_daily_exit === 'boolean') setUseDailyExit(detail.params.use_daily_exit)
      if (typeof detail.params.daily_exit_hour === 'number') setDailyExitHour(detail.params.daily_exit_hour)
      if (typeof detail.params.spread_pips === 'number') setSpreadPips(detail.params.spread_pips)
      if (typeof detail.params.slippage_pips === 'number') setSlippagePips(detail.params.slippage_pips)
      if (typeof detail.params.commission_per_trade === 'number') setCommissionPerTrade(detail.params.commission_per_trade)
      if (typeof detail.params.use_atr_trailing_stop === 'boolean') setUseAtrTrailingStop(detail.params.use_atr_trailing_stop)
      if (typeof detail.params.atr_trailing_length === 'number') setAtrTrailingLength(detail.params.atr_trailing_length)
      if (typeof detail.params.atr_trailing_multiplier === 'number') setAtrTrailingMultiplier(detail.params.atr_trailing_multiplier)
      if (typeof detail.params.use_max_dd_stop === 'boolean') setUseMaxDdStop(detail.params.use_max_dd_stop)
      if (typeof detail.params.max_dd_stop_pips === 'number') setMaxDdStopPips(detail.params.max_dd_stop_pips)
      if (typeof detail.params.use_consecutive_loss_stop === 'boolean') setUseConsecutiveLossStop(detail.params.use_consecutive_loss_stop)
      if (typeof detail.params.consecutive_loss_stop_count === 'number') setConsecutiveLossStopCount(detail.params.consecutive_loss_stop_count)
      if (typeof detail.params.consecutive_loss_stop_bars === 'number') setConsecutiveLossStopBars(detail.params.consecutive_loss_stop_bars)
      if (detail.params.entry_method === 'market' || detail.params.entry_method === 'limit' || detail.params.entry_method === 'stop') {
        setEntryMethod(detail.params.entry_method)
      }
      if (typeof detail.params.entry_offset_pips === 'number') setEntryOffsetPips(detail.params.entry_offset_pips)
      if (typeof detail.params.use_position_sizing === 'boolean') setUsePositionSizing(detail.params.use_position_sizing)
      if (
        detail.params.position_sizing_method === 'risk_percent' ||
        detail.params.position_sizing_method === 'fixed_lot' ||
        detail.params.position_sizing_method === 'compounding'
      ) {
        setPositionSizingMethod(detail.params.position_sizing_method)
      }
      if (typeof detail.params.initial_capital === 'number') setInitialCapital(detail.params.initial_capital)
      if (detail.params.account_currency === 'JPY' || detail.params.account_currency === 'USD') {
        setAccountCurrency(detail.params.account_currency)
      }
      if (typeof detail.params.risk_percent === 'number') setRiskPercent(detail.params.risk_percent)
      if (typeof detail.params.fixed_lot_size === 'number') setFixedLotSize(detail.params.fixed_lot_size)
      if (typeof detail.params.conversion_rate === 'number') setConversionRate(detail.params.conversion_rate)
      if (typeof detail.params.use_breakeven_stop === 'boolean') setUseBreakevenStop(detail.params.use_breakeven_stop)
      if (typeof detail.params.breakeven_trigger_rr === 'number') setBreakevenTriggerRr(detail.params.breakeven_trigger_rr)
      if (typeof detail.params.use_partial_tp === 'boolean') setUsePartialTp(detail.params.use_partial_tp)
      if (typeof detail.params.partial_tp_rr === 'number') setPartialTpRr(detail.params.partial_tp_rr)
      if (typeof detail.params.partial_tp_fraction === 'number') setPartialTpFraction(detail.params.partial_tp_fraction)
    },
  })

  const runMutation = useMutation({
    mutationFn: () => {
      const activeRanges = paramRanges.filter((r) => r.enabled)
      const param_ranges =
        activeRanges.length > 0
          ? Object.fromEntries(activeRanges.map((r) => [r.param, buildRangeValues(r.min, r.max, r.step)]))
          : undefined
      const activeConditionRanges = dualDirectionMode
        ? []
        : conditionOptimizeRanges.filter((r) => r.enabled && r.path && pathIsValid(tree, r.path))
      const condition_tree_variants =
        activeConditionRanges.length > 0
          ? buildConditionTreeVariants(
              tree,
              activeConditionRanges.map((r) => ({
                path: r.path as number[],
                values: buildRangeValues(r.min, r.max, r.step),
              })),
            )
          : undefined
      return createBacktest({
        mode,
        timeframe,
        symbol,
        optimizer: 'grid',
        direction,
        condition_tree: dualDirectionMode ? undefined : tree,
        condition_tree_variants,
        long_condition_tree: dualDirectionMode ? longTree : undefined,
        short_condition_tree: dualDirectionMode ? shortTree : undefined,
        param_ranges,
        rr,
        use_weekend_exit: useWeekendExit,
        weekend_exit_hour: weekendExitHour,
        use_daily_exit: useDailyExit,
        daily_exit_hour: dailyExitHour,
        spread_pips: spreadPips,
        slippage_pips: slippagePips,
        commission_per_trade: commissionPerTrade,
        use_atr_trailing_stop: useAtrTrailingStop,
        atr_trailing_length: atrTrailingLength,
        atr_trailing_multiplier: atrTrailingMultiplier,
        use_max_dd_stop: useMaxDdStop,
        max_dd_stop_pips: maxDdStopPips,
        use_consecutive_loss_stop: useConsecutiveLossStop,
        consecutive_loss_stop_count: consecutiveLossStopCount,
        consecutive_loss_stop_bars: consecutiveLossStopBars,
        // limit/stop isn't supported together with dual-direction mode -
        // force "market" here too as a second safety net even though the
        // UI already hides the control in that mode.
        entry_method: dualDirectionMode ? 'market' : entryMethod,
        entry_offset_pips: entryOffsetPips,
        use_position_sizing: usePositionSizing,
        position_sizing_method: positionSizingMethod,
        initial_capital: initialCapital,
        account_currency: accountCurrency,
        risk_percent: riskPercent,
        fixed_lot_size: fixedLotSize,
        conversion_rate: conversionRate,
        use_breakeven_stop: useBreakevenStop,
        breakeven_trigger_rr: breakevenTriggerRr,
        use_partial_tp: usePartialTp,
        partial_tp_rr: partialTpRr,
        partial_tp_fraction: partialTpFraction,
        save_as: saveAsName.trim() || undefined,
      })
    },
    onSuccess: (data) => setJobId(data.job_id),
  })

  const statusQuery = useQuery({
    queryKey: ['backtest-status', jobId],
    queryFn: () => fetchBacktestStatus(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'done' || status === 'error' ? false : 1000
    },
    refetchIntervalInBackground: true,
  })

  const resultsQuery = useQuery<BacktestResults>({
    queryKey: ['backtest-results', jobId],
    queryFn: () => fetchBacktestResults(jobId as string),
    enabled: jobId !== null && statusQuery.data?.status === 'done',
  })

  useEffect(() => {
    if (statusQuery.data?.status === 'done' && saveAsName.trim() !== '') {
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
    }
  }, [statusQuery.data?.status, saveAsName, queryClient])

  // If editing the condition tree removes/restructures a condition the user
  // previously marked for optimization, drop that row's stale selection
  // rather than silently keeping a path that now points somewhere else (or
  // at a different condition entirely). Re-checked again at submit time as
  // a second safety net.
  useEffect(() => {
    setConditionOptimizeRanges((prev) => {
      let changed = false
      const next = prev.map((r) => {
        if (r.path && !pathIsValid(tree, r.path)) {
          changed = true
          return { ...r, path: null }
        }
        return r
      })
      return changed ? next : prev
    })
  }, [tree])

  const results = resultsQuery.data
  const bestRow = results?.ranking_total?.[0]
  const isRunning = statusQuery.data && !['done', 'error'].includes(statusQuery.data.status)

  return (
    <div className="min-h-screen text-gray-200">
      <nav className="glass-nav sticky top-0 z-10 flex items-center gap-5 px-4 py-3 text-sm">
        <span className="brand-text text-base font-bold tracking-wide">Strategy Lab</span>
        {NAV_ITEMS.map((item) => (
          <span key={item} className="cursor-default text-gray-400 transition-colors hover:text-gray-200">
            {item}
          </span>
        ))}
        <button
          type="button"
          onClick={resetLayout}
          className="ml-auto rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs text-gray-400 hover:bg-white/10 hover:text-gray-200"
        >
          レイアウトをリセット
        </button>
      </nav>

      <div ref={gridContainerRef} className="p-4">
        {gridMounted && (
          <GridLayout
            width={gridWidth}
            layout={layout}
            gridConfig={{ cols: 12, rowHeight: 24, margin: [16, 16] }}
            dragConfig={{ handle: '.drag-handle' }}
            onLayoutChange={handleLayoutChange}
          >
            <Panel key="builder" title="① ストラテジービルダー">
              <div className="space-y-3">
                <label className="flex items-center gap-1.5 text-xs text-gray-300">
                  <input
                    type="checkbox"
                    checked={dualDirectionMode}
                    onChange={(e) => setDualDirectionMode(e.target.checked)}
                  />
                  Long+Shortを同時に評価(同じ足で両方成立したらスキップ)
                </label>

                {!dualDirectionMode && (
                  <div className="flex gap-4 text-sm">
                    <label className="flex items-center gap-1.5">
                      <input
                        type="radio"
                        className="accent-blue-500"
                        checked={direction === 'short'}
                        onChange={() => setDirection('short')}
                      />
                      Short(売り)
                    </label>
                    <label className="flex items-center gap-1.5">
                      <input
                        type="radio"
                        className="accent-purple-500"
                        checked={direction === 'long'}
                        onChange={() => setDirection('long')}
                      />
                      Long(買い)
                    </label>
                  </div>
                )}

                {!dualDirectionMode && (
                  <div className="flex items-center gap-2 text-xs text-gray-300">
                    <span className="text-gray-400">エントリー方式</span>
                    <select
                      className="glass-input rounded-lg px-2 py-1"
                      value={entryMethod}
                      onChange={(e) => setEntryMethod(e.target.value as 'market' | 'limit' | 'stop')}
                    >
                      <option value="market">成行(条件確定の次の足で即エントリー)</option>
                      <option value="limit">指値(有利な価格まで戻ったら約定)</option>
                      <option value="stop">逆指値(さらにブレイクしたら約定)</option>
                    </select>
                    {entryMethod !== 'market' && (
                      <label className="ml-auto flex items-center gap-1">
                        オフセット
                        <input
                          type="number"
                          min={0}
                          step={0.5}
                          className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs"
                          value={entryOffsetPips}
                          onChange={(e) => setEntryOffsetPips(Number(e.target.value))}
                        />
                        pips
                      </label>
                    )}
                  </div>
                )}

                {indicatorsQuery.data && !dualDirectionMode && (
                  <ConditionTreeEditor node={tree} indicators={indicatorsQuery.data} onChange={setTree} />
                )}

                {indicatorsQuery.data && dualDirectionMode && (
                  <div className="space-y-3">
                    <div>
                      <div className="mb-1 text-xs font-semibold text-blue-300">Long条件</div>
                      <ConditionTreeEditor node={longTree} indicators={indicatorsQuery.data} onChange={setLongTree} />
                    </div>
                    <div>
                      <div className="mb-1 text-xs font-semibold text-purple-300">Short条件</div>
                      <ConditionTreeEditor node={shortTree} indicators={indicatorsQuery.data} onChange={setShortTree} />
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2 text-sm">
                  <select
                    className="glass-input rounded-lg px-2 py-1.5"
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                  >
                    {SYMBOLS.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                  <select
                    className="glass-input rounded-lg px-2 py-1.5"
                    value={timeframe}
                    onChange={(e) => setTimeframe(e.target.value)}
                  >
                    {TIMEFRAMES.map((tf) => (
                      <option key={tf} value={tf}>
                        {tf}
                      </option>
                    ))}
                  </select>
                  <select
                    className="glass-input col-span-2 rounded-lg px-2 py-1.5"
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="dev">dev(軽量)</option>
                    <option value="full">full(本番)</option>
                  </select>
                </div>
                <div className="text-xs text-gray-500">
                  ※この条件ビルダーではdev/fullの違いはレポート上の表記のみです(パラメータの範囲は下の「パラメータ最適化」で指定してください)
                </div>

                <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <div className="text-xs font-semibold text-gray-400">決済ルール</div>
                  <label className="flex items-center justify-between text-xs text-gray-300">
                    リスクリワード比(RR)
                    <input
                      type="number"
                      step={0.1}
                      min={0.1}
                      className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs"
                      value={rr}
                      onChange={(e) => setRr(Number(e.target.value))}
                    />
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useWeekendExit}
                      onChange={(e) => setUseWeekendExit(e.target.checked)}
                    />
                    週末決済を使う
                    <input
                      type="number"
                      min={0}
                      max={23}
                      disabled={!useWeekendExit}
                      className="glass-input ml-auto w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                      value={weekendExitHour}
                      onChange={(e) => setWeekendExitHour(Number(e.target.value))}
                    />
                    時
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useDailyExit}
                      onChange={(e) => setUseDailyExit(e.target.checked)}
                    />
                    日次決済を使う
                    <input
                      type="number"
                      min={0}
                      max={23}
                      disabled={!useDailyExit}
                      className="glass-input ml-auto w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                      value={dailyExitHour}
                      onChange={(e) => setDailyExitHour(Number(e.target.value))}
                    />
                    時
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useAtrTrailingStop}
                      onChange={(e) => setUseAtrTrailingStop(e.target.checked)}
                    />
                    ATRトレーリングストップを使う
                  </label>
                  <div className="grid grid-cols-2 gap-1.5 pl-5 text-xs text-gray-300">
                    <label className="flex items-center justify-between gap-1">
                      期間
                      <input
                        type="number"
                        min={1}
                        disabled={!useAtrTrailingStop}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={atrTrailingLength}
                        onChange={(e) => setAtrTrailingLength(Number(e.target.value))}
                      />
                    </label>
                    <label className="flex items-center justify-between gap-1">
                      倍率
                      <input
                        type="number"
                        step={0.1}
                        min={0.1}
                        disabled={!useAtrTrailingStop}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={atrTrailingMultiplier}
                        onChange={(e) => setAtrTrailingMultiplier(Number(e.target.value))}
                      />
                    </label>
                  </div>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useBreakevenStop}
                      onChange={(e) => setUseBreakevenStop(e.target.checked)}
                    />
                    建値移動(ブレイクイーブン)を使う
                    <span className="ml-auto flex items-center gap-1">
                      <input
                        type="number"
                        step={0.1}
                        min={0}
                        disabled={!useBreakevenStop}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={breakevenTriggerRr}
                        onChange={(e) => setBreakevenTriggerRr(Number(e.target.value))}
                      />
                      RR到達で
                    </span>
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={usePartialTp}
                      onChange={(e) => setUsePartialTp(e.target.checked)}
                    />
                    部分利確を使う
                  </label>
                  <div className="grid grid-cols-2 gap-1.5 pl-5 text-xs text-gray-300">
                    <label className="flex items-center justify-between gap-1">
                      到達RR
                      <input
                        type="number"
                        step={0.1}
                        min={0.1}
                        disabled={!usePartialTp}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={partialTpRr}
                        onChange={(e) => setPartialTpRr(Number(e.target.value))}
                      />
                    </label>
                    <label className="flex items-center justify-between gap-1">
                      決済割合
                      <input
                        type="number"
                        step={0.05}
                        min={0.05}
                        max={0.95}
                        disabled={!usePartialTp}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={partialTpFraction}
                        onChange={(e) => setPartialTpFraction(Number(e.target.value))}
                      />
                    </label>
                  </div>
                </div>

                <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <div className="text-xs font-semibold text-gray-400">リスク管理(任意・一時停止して再開)</div>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useMaxDdStop}
                      onChange={(e) => setUseMaxDdStop(e.target.checked)}
                    />
                    最大DDストップを使う
                    <input
                      type="number"
                      min={0}
                      step={1}
                      disabled={!useMaxDdStop}
                      className="glass-input ml-auto w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                      value={maxDdStopPips}
                      onChange={(e) => setMaxDdStopPips(Number(e.target.value))}
                    />
                    pips
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useConsecutiveLossStop}
                      onChange={(e) => setUseConsecutiveLossStop(e.target.checked)}
                    />
                    連敗ストップを使う
                  </label>
                  <div className="grid grid-cols-2 gap-1.5 pl-5 text-xs text-gray-300">
                    <label className="flex items-center justify-between gap-1">
                      連敗数
                      <input
                        type="number"
                        min={1}
                        disabled={!useConsecutiveLossStop}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={consecutiveLossStopCount}
                        onChange={(e) => setConsecutiveLossStopCount(Number(e.target.value))}
                      />
                    </label>
                    <label className="flex items-center justify-between gap-1">
                      停止バー数
                      <input
                        type="number"
                        min={1}
                        disabled={!useConsecutiveLossStop}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={consecutiveLossStopBars}
                        onChange={(e) => setConsecutiveLossStopBars(Number(e.target.value))}
                      />
                    </label>
                  </div>
                </div>

                <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-400">
                    <input
                      type="checkbox"
                      checked={usePositionSizing}
                      onChange={(e) => setUsePositionSizing(e.target.checked)}
                    />
                    資金管理(ポジションサイジング)を使う
                  </label>
                  <div className={`space-y-1.5 pl-5 text-xs text-gray-300 ${!usePositionSizing ? 'opacity-40' : ''}`}>
                    <label className="flex items-center justify-between gap-1">
                      方式
                      <select
                        className="glass-input w-40 rounded-lg px-1.5 py-1 text-xs"
                        disabled={!usePositionSizing}
                        value={positionSizingMethod}
                        onChange={(e) => setPositionSizingMethod(e.target.value as 'risk_percent' | 'fixed_lot' | 'compounding')}
                      >
                        <option value="risk_percent">資金%リスク(初期資金基準)</option>
                        <option value="fixed_lot">固定ロット</option>
                        <option value="compounding">複利(資金%を都度の残高で計算)</option>
                      </select>
                    </label>
                    <div className="grid grid-cols-2 gap-1.5">
                      <label className="flex items-center justify-between gap-1">
                        初期資金
                        <input
                          type="number"
                          min={0}
                          step={10000}
                          disabled={!usePositionSizing}
                          className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={initialCapital}
                          onChange={(e) => setInitialCapital(Number(e.target.value))}
                        />
                      </label>
                      <label className="flex items-center justify-between gap-1">
                        口座通貨
                        <select
                          className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs"
                          disabled={!usePositionSizing}
                          value={accountCurrency}
                          onChange={(e) => setAccountCurrency(e.target.value as 'JPY' | 'USD')}
                        >
                          <option value="JPY">JPY</option>
                          <option value="USD">USD</option>
                        </select>
                      </label>
                    </div>
                    {(positionSizingMethod === 'risk_percent' || positionSizingMethod === 'compounding') && (
                      <label className="flex items-center justify-between gap-1">
                        リスク%(1取引あたり)
                        <input
                          type="number"
                          min={0.01}
                          step={0.1}
                          disabled={!usePositionSizing}
                          className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={riskPercent}
                          onChange={(e) => setRiskPercent(Number(e.target.value))}
                        />
                      </label>
                    )}
                    {positionSizingMethod === 'fixed_lot' && (
                      <label className="flex items-center justify-between gap-1">
                        固定ロット数
                        <input
                          type="number"
                          min={0.01}
                          step={0.01}
                          disabled={!usePositionSizing}
                          className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={fixedLotSize}
                          onChange={(e) => setFixedLotSize(Number(e.target.value))}
                        />
                      </label>
                    )}
                    <label className="flex items-center justify-between gap-1">
                      為替換算レート(通貨ペア⇔口座通貨)
                      <input
                        type="number"
                        min={0.01}
                        step={0.01}
                        disabled={!usePositionSizing}
                        className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={conversionRate}
                        onChange={(e) => setConversionRate(Number(e.target.value))}
                      />
                    </label>
                    <div className="text-[11px] text-gray-500">
                      ※為替換算レートはバックテスト全期間で固定の概算値です(日々の実勢レートではありません)
                    </div>
                  </div>
                </div>

                <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <div className="text-xs font-semibold text-gray-400">設定(約定コスト・任意)</div>
                  <label className="flex items-center justify-between text-xs text-gray-300">
                    スプレッド(pips)
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs"
                      value={spreadPips}
                      onChange={(e) => setSpreadPips(Number(e.target.value))}
                    />
                  </label>
                  <label className="flex items-center justify-between text-xs text-gray-300">
                    スリッページ(pips)
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs"
                      value={slippagePips}
                      onChange={(e) => setSlippagePips(Number(e.target.value))}
                    />
                  </label>
                  <label className="flex items-center justify-between text-xs text-gray-300">
                    手数料(1取引あたり)
                    <input
                      type="number"
                      step={0.01}
                      min={0}
                      className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs"
                      value={commissionPerTrade}
                      onChange={(e) => setCommissionPerTrade(Number(e.target.value))}
                    />
                  </label>
                </div>

                <div className="space-y-2">
                  <div className="text-xs font-semibold text-gray-400">パラメータ最適化(任意・いくつでも追加可)</div>
                  {paramRanges.map((range, i) => (
                    <ParamRangeRow
                      key={i}
                      label={`パラメータ${i + 1}`}
                      value={range}
                      onChange={(next) => updateParamRange(i, next)}
                      onRemove={paramRanges.length > 1 ? () => removeParamRange(i) : undefined}
                    />
                  ))}
                  <button
                    type="button"
                    onClick={addParamRange}
                    className="w-full rounded-lg border border-dashed border-white/20 px-2 py-1 text-xs text-gray-400 hover:bg-white/5 hover:text-gray-200"
                  >
                    + パラメータ範囲を追加
                  </button>
                  <select
                    className="glass-input w-full rounded-lg px-2 py-1.5 text-xs"
                    value={optimizationMetric}
                    onChange={(e) => setOptimizationMetric(e.target.value)}
                  >
                    {OPTIMIZATION_METRICS.map((m) => (
                      <option key={m.id} value={m.id}>
                        グラフの高さ: {m.label}
                      </option>
                    ))}
                  </select>
                </div>

                {!dualDirectionMode &&
                  (() => {
                    const optimizableConditions = collectOptimizableConditions(tree)
                    return (
                      <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                        <div className="text-xs font-semibold text-gray-400">条件ツリー内の値を最適化</div>
                        {optimizableConditions.length === 0 ? (
                          <div className="text-[11px] text-gray-500">
                            固定値と比較する条件がありません(「固定値」比較の条件を1つ追加してください)
                          </div>
                        ) : (
                          <>
                            {conditionOptimizeRanges.map((range, i) => (
                              <div key={i} className="space-y-1.5 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                                <label className="flex items-center gap-1.5 text-xs text-gray-300">
                                  <input
                                    type="checkbox"
                                    checked={range.enabled}
                                    onChange={(e) => updateConditionOptimizeRange(i, { ...range, enabled: e.target.checked })}
                                  />
                                  範囲{i + 1}を最適化
                                  {conditionOptimizeRanges.length > 1 && (
                                    <button
                                      type="button"
                                      onClick={() => removeConditionOptimizeRange(i)}
                                      className="ml-auto text-gray-500 hover:text-red-400"
                                      title="この範囲を削除"
                                    >
                                      ✕
                                    </button>
                                  )}
                                </label>
                                <div className={`space-y-1.5 ${!range.enabled ? 'opacity-40' : ''}`}>
                                  <select
                                    className="glass-input w-full rounded-lg px-1.5 py-1 text-xs"
                                    disabled={!range.enabled}
                                    value={range.path ? JSON.stringify(range.path) : ''}
                                    onChange={(e) =>
                                      updateConditionOptimizeRange(i, {
                                        ...range,
                                        path: e.target.value ? JSON.parse(e.target.value) : null,
                                      })
                                    }
                                  >
                                    <option value="">対象の条件を選択</option>
                                    {optimizableConditions.map((c) => (
                                      <option key={JSON.stringify(c.path)} value={JSON.stringify(c.path)}>
                                        {c.label}
                                      </option>
                                    ))}
                                  </select>
                                  <div className="grid grid-cols-3 gap-1.5">
                                    <label className="flex items-center justify-between gap-1 text-xs text-gray-300">
                                      最小
                                      <input
                                        type="number"
                                        disabled={!range.enabled}
                                        className="glass-input w-14 rounded-lg px-1 py-1 text-xs disabled:opacity-40"
                                        value={range.min}
                                        onChange={(e) => updateConditionOptimizeRange(i, { ...range, min: Number(e.target.value) })}
                                      />
                                    </label>
                                    <label className="flex items-center justify-between gap-1 text-xs text-gray-300">
                                      最大
                                      <input
                                        type="number"
                                        disabled={!range.enabled}
                                        className="glass-input w-14 rounded-lg px-1 py-1 text-xs disabled:opacity-40"
                                        value={range.max}
                                        onChange={(e) => updateConditionOptimizeRange(i, { ...range, max: Number(e.target.value) })}
                                      />
                                    </label>
                                    <label className="flex items-center justify-between gap-1 text-xs text-gray-300">
                                      刻み
                                      <input
                                        type="number"
                                        disabled={!range.enabled}
                                        className="glass-input w-14 rounded-lg px-1 py-1 text-xs disabled:opacity-40"
                                        value={range.step}
                                        onChange={(e) => updateConditionOptimizeRange(i, { ...range, step: Number(e.target.value) })}
                                      />
                                    </label>
                                  </div>
                                </div>
                              </div>
                            ))}
                            <button
                              type="button"
                              onClick={addConditionOptimizeRange}
                              className="w-full rounded-lg border border-dashed border-white/20 px-2 py-1 text-xs text-gray-400 hover:bg-white/5 hover:text-gray-200"
                            >
                              + 範囲を追加
                            </button>
                          </>
                        )}
                      </div>
                    )
                  })()}

                <input
                  type="text"
                  placeholder="名前を付けて保存(任意)"
                  className="glass-input w-full rounded-lg px-2 py-1.5 text-xs"
                  value={saveAsName}
                  onChange={(e) => setSaveAsName(e.target.value)}
                />

                <button
                  type="button"
                  onClick={() => runMutation.mutate()}
                  disabled={runMutation.isPending || Boolean(isRunning)}
                  className="glow-button w-full rounded-lg py-2 font-semibold text-white transition-shadow disabled:opacity-40"
                >
                  {isRunning ? '実行中...' : 'バックテスト実行'}
                </button>

                {statusQuery.data?.status === 'error' && (
                  <pre className="max-h-40 overflow-auto rounded-lg border border-red-500/20 bg-red-950/40 p-2 text-xs text-red-300">
                    {statusQuery.data.error}
                  </pre>
                )}
              </div>
            </Panel>

            <Panel key="chart" title="② チャート">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                <div className="flex overflow-hidden rounded-lg border border-white/10">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf}
                      type="button"
                      onClick={() => setChartTimeframe(tf)}
                      className={
                        tf === chartTimeframe
                          ? 'bg-blue-500/30 px-2 py-1 font-semibold text-blue-100'
                          : 'px-2 py-1 text-gray-400 hover:bg-white/5 hover:text-gray-200'
                      }
                    >
                      {tf}
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-1.5 text-gray-400">
                  EMA
                  <input
                    type="number"
                    min={1}
                    className="glass-input w-16 rounded-lg px-1.5 py-1"
                    value={emaLength}
                    onChange={(e) => setEmaLength(Math.max(1, Number(e.target.value)))}
                  />
                </label>
              </div>
              {priceQuery.data && (
                <ChartPanel bars={priceQuery.data} trades={results?.trade_log ?? []} emaLength={emaLength} symbol={symbol} />
              )}
            </Panel>

            <Panel key="equity" title="⑩ エクイティカーブ">
              <EquityCurveChart points={results?.equity_curve ?? []} />
            </Panel>

            <Panel key="drawdown" title="⑨ ドローダウン推移">
              <DrawdownChart points={results?.equity_curve ?? []} />
            </Panel>

            <Panel key="ranking" title="③ ランキング一覧">
              <RankingTable rows={results?.ranking_total ?? []} />
            </Panel>

            <Panel key="summary" title="④ 戦略サマリー">
              <StrategySummaryPanel
                symbol={symbol}
                timeframe={timeframe}
                mode={mode}
                direction={direction}
                dualDirectionMode={dualDirectionMode}
                testCount={results?.ranking_total?.length ?? 0}
                row={bestRow}
              />
            </Panel>

            <Panel key="heatmap" title="⑦ 月別収益ヒートマップ">
              <MonthlyHeatmap rows={results?.monthly_analysis ?? []} />
            </Panel>

            <Panel key="yearly" title="⑥ 年別成績">
              <YearlyPerformanceChart rows={results?.yearly_analysis ?? []} />
            </Panel>

            <Panel key="stats" title="⑪ 統計情報">
              <StatsPanel row={bestRow} />
            </Panel>

            <Panel key="surface" title="⑧ 最適化サーフェス(3D)">
              {(() => {
                const enabledParams = paramRanges.filter((r) => r.enabled).map((r) => r.param)
                const effectiveX = enabledParams.includes(surfaceParamX) ? surfaceParamX : (enabledParams[0] ?? surfaceParamX)
                const effectiveY = enabledParams.includes(surfaceParamY) ? surfaceParamY : (enabledParams[1] ?? surfaceParamY)
                return (
                  <>
                    {enabledParams.length > 2 && (
                      <div className="mb-2 flex gap-2 text-xs text-gray-300">
                        <label className="flex flex-1 items-center gap-1">
                          X軸
                          <select
                            className="glass-input flex-1 rounded-lg px-1.5 py-1 text-xs"
                            value={effectiveX}
                            onChange={(e) => setSurfaceParamX(e.target.value)}
                          >
                            {enabledParams.map((param) => (
                              <option key={param} value={param}>
                                {OPTIMIZABLE_PARAMS.find((p) => p.id === param)?.label ?? param}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="flex flex-1 items-center gap-1">
                          Y軸
                          <select
                            className="glass-input flex-1 rounded-lg px-1.5 py-1 text-xs"
                            value={effectiveY}
                            onChange={(e) => setSurfaceParamY(e.target.value)}
                          >
                            {enabledParams.map((param) => (
                              <option key={param} value={param}>
                                {OPTIMIZABLE_PARAMS.find((p) => p.id === param)?.label ?? param}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                    )}
                    <OptimizationSurface
                      rows={results?.ranking_total ?? []}
                      paramX={effectiveX}
                      paramY={effectiveY}
                      metric={optimizationMetric}
                      metricLabel={OPTIMIZATION_METRICS.find((m) => m.id === optimizationMetric)?.label ?? optimizationMetric}
                    />
                  </>
                )
              })()}
            </Panel>

            <Panel key="trades" title="⑤ 取引履歴">
              <TradeHistoryTable rows={results?.trade_log ?? []} />
            </Panel>

            <Panel key="saved" title="保存済み戦略">
              <SavedStrategiesPanel
                strategies={strategiesQuery.data ?? []}
                onLoad={(id) => loadStrategyMutation.mutate(id)}
                isLoading={loadStrategyMutation.isPending}
              />
            </Panel>
          </GridLayout>
        )}
      </div>
    </div>
  )
}
