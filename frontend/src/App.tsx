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
import type { BacktestResults, Direction, GroupNode, OptimizableParam, ParamRangeConfig } from './types'
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

const OPTIMIZABLE_PARAMS: OptimizableParam[] = [
  { id: 'ema_length', label: 'EMA期間' },
  { id: 'rr', label: 'リスクリワード比' },
  { id: 'rsi_min', label: 'RSI下限' },
  { id: 'ema_distance_pips', label: 'EMA乖離(pips)' },
  { id: 'min_body_pips', label: '実体最小(pips)' },
  { id: 'lookahead_bars', label: '先読みバー数' },
  { id: 'breakout_bars', label: 'ブレイクアウトバー数' },
]

const OPTIMIZATION_METRICS = [
  { id: 'net_profit', label: '総利益' },
  { id: 'profit_factor', label: 'PF' },
  { id: 'win_rate', label: '勝率%' },
  { id: 'recovery_factor', label: 'Recovery' },
]

const PARAM_DEFAULTS: Record<string, { min: number; max: number; step: number }> = {
  ema_length: { min: 150, max: 250, step: 20 },
  rr: { min: 1, max: 2, step: 0.2 },
  rsi_min: { min: 60, max: 80, step: 5 },
  ema_distance_pips: { min: 20, max: 80, step: 20 },
  min_body_pips: { min: 10, max: 30, step: 5 },
  lookahead_bars: { min: 10, max: 20, step: 5 },
  breakout_bars: { min: 20, max: 40, step: 5 },
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
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']

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
}: {
  label: string
  value: ParamRangeConfig
  onChange: (next: ParamRangeConfig) => void
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
  const [symbol, setSymbol] = useState('USDJPY')
  const [timeframe, setTimeframe] = useState('15m')
  const [mode, setMode] = useState('dev')
  const [jobId, setJobId] = useState<string | null>(null)

  // Chart display timeframe is independent from the backtest timeframe above -
  // you may want to eyeball a strategy on 1h while backtesting on 15m.
  const [chartTimeframe, setChartTimeframe] = useState('15m')
  const [emaLength, setEmaLength] = useState(20)

  const [paramRangeX, setParamRangeX] = useState<ParamRangeConfig>(() => defaultParamRange('ema_length'))
  const [paramRangeY, setParamRangeY] = useState<ParamRangeConfig>(() => defaultParamRange('rr'))
  const [optimizationMetric, setOptimizationMetric] = useState('net_profit')

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
      if (detail.params.condition_tree) setTree(detail.params.condition_tree as GroupNode)
      if (typeof detail.params.rr === 'number') setRr(detail.params.rr)
      if (typeof detail.params.use_weekend_exit === 'boolean') setUseWeekendExit(detail.params.use_weekend_exit)
      if (typeof detail.params.weekend_exit_hour === 'number') setWeekendExitHour(detail.params.weekend_exit_hour)
      if (typeof detail.params.use_daily_exit === 'boolean') setUseDailyExit(detail.params.use_daily_exit)
      if (typeof detail.params.daily_exit_hour === 'number') setDailyExitHour(detail.params.daily_exit_hour)
      if (typeof detail.params.spread_pips === 'number') setSpreadPips(detail.params.spread_pips)
      if (typeof detail.params.slippage_pips === 'number') setSlippagePips(detail.params.slippage_pips)
      if (typeof detail.params.commission_per_trade === 'number') setCommissionPerTrade(detail.params.commission_per_trade)
    },
  })

  const runMutation = useMutation({
    mutationFn: () => {
      const activeRanges = [paramRangeX, paramRangeY].filter((r) => r.enabled)
      const param_ranges =
        activeRanges.length > 0
          ? Object.fromEntries(activeRanges.map((r) => [r.param, buildRangeValues(r.min, r.max, r.step)]))
          : undefined
      return createBacktest({
        mode,
        timeframe,
        symbol,
        optimizer: 'grid',
        direction,
        condition_tree: tree,
        param_ranges,
        rr,
        use_weekend_exit: useWeekendExit,
        weekend_exit_hour: weekendExitHour,
        use_daily_exit: useDailyExit,
        daily_exit_hour: dailyExitHour,
        spread_pips: spreadPips,
        slippage_pips: slippagePips,
        commission_per_trade: commissionPerTrade,
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

                {indicatorsQuery.data && (
                  <ConditionTreeEditor node={tree} indicators={indicatorsQuery.data} onChange={setTree} />
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
                  <div className="text-xs font-semibold text-gray-400">パラメータ最適化(任意・3Dグラフ用)</div>
                  <ParamRangeRow label="パラメータ1" value={paramRangeX} onChange={setParamRangeX} />
                  <ParamRangeRow label="パラメータ2" value={paramRangeY} onChange={setParamRangeY} />
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
              <OptimizationSurface
                rows={results?.ranking_total ?? []}
                paramX={paramRangeX.param}
                paramY={paramRangeY.param}
                metric={optimizationMetric}
                metricLabel={OPTIMIZATION_METRICS.find((m) => m.id === optimizationMetric)?.label ?? optimizationMetric}
              />
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
