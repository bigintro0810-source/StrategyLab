import { toPips } from './pipUtils'
import type { EquityPoint, TradeRow, TreeNode, YearlyRow } from './types'

// 合成タブ: チェックした複数ストラテジーのtrade_logを時系列でまとめて1本の
// エクイティカーブとして評価し直す(EA Studioの「ポートフォリオ結合」相当)。
// 通貨ペアが異なるストラテジー同士でも比較できるよう、各トレードはこの
// 時点でpipsへ変換してから合成する(以降は生の価格差ではなく合成後のpips
// 値として扱う)。
export interface CompositeInput {
  id: string
  name: string
  symbol: string | undefined
  // 表示専用(合成計算はsymbolのpip換算だけで完結する)。
  timeframe: string | undefined
  tradeLog: TradeRow[]
  // 単一方向バックテストのトレードはper-trade directionを持たない
  // (TradeRow.direction参照)ため、合成後の取引履歴に方向列を出すには
  // ストラテジーごとの設定方向をここで別途持っておき、マージ時に
  // フォールバックとして使う(下のcomputeComposite参照)。
  direction?: 'long' | 'short'
  // 条件タブ(CompositeDetail.tsx)で対象ごとに一覧表示するため。
  conditionTree?: TreeNode
}

// 合成対象を追加するピッカー(AddCandidateModal.tsx)に渡す候補1件分 -
// CompositeInputと違いtradeLogを持たない(候補一覧を出す時点ではまだ
// フェッチしない・不要なため)。
export interface CompositeCandidate {
  id: string
  name: string
  symbol?: string
  timeframe?: string
}

export interface CompositeResult {
  trades: number
  netProfitPips: number
  expectedValuePips: number
  profitFactor: number
  maxDdPips: number
  winRate: number
  sharpeRatio: number
  sortinoRatio: number
  cagr: number
  calmarRatio: number
  equityCurve: EquityPoint[]
  tradeLog: (TradeRow & { source: string })[]
}

// engine/advanced_metrics.pyと同じ式のクライアント側版 - main.py::
// calculate_advanced_metricsが読む入力(トレードのentry_time/exit_time/
// profitのみ)はcomposite.tradeLogが既に持っている値だけで揃うため、
// サーバー側と同じロジックをそのまま再現できる(pip_size/口座残高等の
// 個別ストラテジー固有の情報は不要 - virtual_capitalは全ランで固定100の
// 定数)。
const MONTHS_PER_YEAR = 12
const DEFAULT_VIRTUAL_CAPITAL = 100

function mean(xs: number[]): number {
  return xs.reduce((sum, x) => sum + x, 0) / xs.length
}

// pandas Series.std()の既定(標本標準偏差、ddof=1)に合わせる。
function sampleStd(xs: number[]): number {
  if (xs.length < 2) return NaN
  const m = mean(xs)
  const variance = xs.reduce((sum, x) => sum + (x - m) ** 2, 0) / (xs.length - 1)
  return Math.sqrt(variance)
}

// main.py::build_monthly_analysisと同じ、entry_timeの年月でグルーピング
// したprofit合計の系列。
function monthlyReturns(tradeLog: (TradeRow & { source: string })[]): number[] {
  const byMonth = new Map<string, number>()
  for (const t of tradeLog) {
    const d = new Date(t.entry_time)
    const key = `${d.getFullYear()}-${d.getMonth()}`
    byMonth.set(key, (byMonth.get(key) ?? 0) + t.profit)
  }
  return Array.from(byMonth.values())
}

function sharpeRatioOf(monthlyReturnsSeries: number[]): number {
  if (monthlyReturnsSeries.length === 0) return 0
  const std = sampleStd(monthlyReturnsSeries)
  if (std === 0) return 0
  return (mean(monthlyReturnsSeries) / std) * Math.sqrt(MONTHS_PER_YEAR)
}

function sortinoRatioOf(monthlyReturnsSeries: number[]): number {
  if (monthlyReturnsSeries.length === 0) return 0
  const downside = monthlyReturnsSeries.filter((r) => r < 0)
  const downsideStd = downside.length > 1 ? sampleStd(downside) : 0
  if (!downsideStd) return 0
  return (mean(monthlyReturnsSeries) / downsideStd) * Math.sqrt(MONTHS_PER_YEAR)
}

function cagrOf(netProfit: number, years: number, virtualCapital = DEFAULT_VIRTUAL_CAPITAL): number {
  if (years <= 0 || virtualCapital <= 0) return 0
  const endingValue = virtualCapital + netProfit
  if (endingValue <= 0) return -1
  return (endingValue / virtualCapital) ** (1 / years) - 1
}

function calmarRatioOf(cagrValue: number, maxDd: number, virtualCapital = DEFAULT_VIRTUAL_CAPITAL): number {
  if (maxDd <= 0 || virtualCapital <= 0) return 0
  const maxDdPct = maxDd / virtualCapital
  return cagrValue / maxDdPct
}

export function computeComposite(inputs: CompositeInput[]): CompositeResult {
  const merged = inputs
    .flatMap((input) =>
      input.tradeLog.map((t) => ({
        ...t,
        profit: toPips(t.profit, input.symbol),
        direction: t.direction ?? input.direction,
        source: input.name,
      })),
    )
    .sort((a, b) => new Date(a.exit_time).getTime() - new Date(b.exit_time).getTime())

  let cumulative = 0
  let peak = 0
  let grossProfit = 0
  let grossLoss = 0
  let wins = 0
  const equityCurve: EquityPoint[] = merged.map((t, i) => {
    cumulative += t.profit
    peak = Math.max(peak, cumulative)
    if (t.profit > 0) {
      grossProfit += t.profit
      wins += 1
    } else {
      grossLoss += Math.abs(t.profit)
    }
    return {
      trade_number: i + 1,
      equity: cumulative,
      equity_high: peak,
      drawdown: peak - cumulative,
      exit_time: t.exit_time,
    }
  })

  const trades = merged.length
  const maxDdPips = equityCurve.reduce((max, p) => Math.max(max, p.drawdown), 0)

  // main.py::calculate_advanced_metricsと同じ、entry_time最小〜exit_time
  // 最大のスパン(日数、365.25日=1年換算)。
  const spanDays =
    trades > 0
      ? Math.floor(
          (Math.max(...merged.map((t) => new Date(t.exit_time).getTime())) -
            Math.min(...merged.map((t) => new Date(t.entry_time).getTime()))) /
            86400000,
        )
      : 0
  const years = spanDays > 0 ? spanDays / 365.25 : 0
  const cagrValue = cagrOf(cumulative, years)

  return {
    trades,
    netProfitPips: cumulative,
    expectedValuePips: trades > 0 ? cumulative / trades : 0,
    profitFactor: grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 999 : 0,
    maxDdPips,
    winRate: trades > 0 ? (wins / trades) * 100 : 0,
    sharpeRatio: sharpeRatioOf(monthlyReturns(merged)),
    sortinoRatio: sortinoRatioOf(monthlyReturns(merged)),
    cagr: cagrValue,
    calmarRatio: calmarRatioOf(cagrValue, maxDdPips),
    equityCurve,
    tradeLog: merged,
  }
}

// analyze_yearly.py(entry_timeの年でグルーピングし、pipsは既にtoPips済みの
// 値をそのまま合計)と同じロジックのクライアント側版 - 合成結果には
// yearly_analysis.csvに相当するファイルが無い(サーバー側で計算していない)
// ため、AutoExplorationDetail.tsxの年別獲得Pipsタブ用にここで作る。
export function computeYearlyAnalysis(tradeLog: (TradeRow & { source: string })[]): YearlyRow[] {
  const byYear = new Map<number, (TradeRow & { source: string })[]>()
  for (const t of tradeLog) {
    const year = new Date(t.entry_time).getFullYear()
    const group = byYear.get(year)
    if (group) group.push(t)
    else byYear.set(year, [t])
  }

  return Array.from(byYear.entries())
    .map(([year, group]) => {
      const trades = group.length
      const wins = group.filter((t) => t.profit > 0).length
      const losses = group.filter((t) => t.profit < 0).length
      const grossProfit = group.filter((t) => t.profit > 0).reduce((sum, t) => sum + t.profit, 0)
      const grossLoss = group.filter((t) => t.profit < 0).reduce((sum, t) => sum + t.profit, 0)
      const netProfit = grossProfit + grossLoss
      return {
        year,
        trades,
        wins,
        losses,
        win_rate: trades > 0 ? (wins / trades) * 100 : 0,
        net_profit: netProfit,
        gross_profit: grossProfit,
        gross_loss: grossLoss,
        profit_factor: grossLoss < 0 ? grossProfit / Math.abs(grossLoss) : grossProfit > 0 ? 999 : 0,
      }
    })
    .sort((a, b) => a.year - b.year)
}
