import { describeConditionTreeJapanese } from './conditionTreeUtils'
import { toPips } from './pipUtils'
import type { IndicatorInfo, TreeNode } from './types'

// Shared by RankingTable.tsx (今回の探索結果) and LibraryScreen.tsx (保存済み
// 戦略/お気に入り) so the two screens show the same metrics with the same
// formatting/色分け - the two data sources differ (RankingRow keyed by a
// numeric rank vs a saved StrategyListEntry keyed by a string id), but once
// reduced to this common shape, both can share one column definition instead
// of two copies that would silently drift apart.
export interface MetricRowLike {
  profit_factor: unknown
  net_profit: unknown
  expected_value: unknown
  max_dd: unknown
  win_rate: unknown
  trades: unknown
  sharpe_ratio: unknown
  recovery_factor: unknown
  sortino_ratio: unknown
  calmar_ratio: unknown
  cagr: unknown
  condition_tree?: TreeNode
  symbol?: unknown
  [key: string]: unknown
}

// + prefix on positive net_profit/expected_value so a quick scan of the
// column makes profitable vs unprofitable rows visually obvious without
// needing the color alone (color-blind friendly, and prints in black&white).
export function signedFixed(v: unknown, digits: number): string {
  const n = Number(v)
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}`
}

export interface MetricColumn {
  key: string
  label: string
  tooltip?: string
  format?: (v: unknown, row: MetricRowLike) => string
  colorClass?: (v: unknown) => string
}

export function buildMetricColumns(indicators: IndicatorInfo[]): MetricColumn[] {
  return [
    {
      key: 'profit_factor',
      label: 'PF',
      tooltip: 'プロフィットファクター(総利益÷総損失。1より大きければ黒字)',
      format: (v) => Number(v).toFixed(2),
      colorClass: (v) => (Number(v) >= 1 ? 'text-emerald-400' : 'text-red-400'),
    },
    {
      key: 'net_profit',
      label: '純利益(pips)',
      format: (v, row) => signedFixed(toPips(Number(v), row.symbol as string), 1),
      colorClass: (v) => (Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400'),
    },
    {
      key: 'expected_value',
      label: '期待値(pips)',
      format: (v, row) => signedFixed(toPips(Number(v), row.symbol as string), 3),
      colorClass: (v) => (Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400'),
    },
    {
      key: 'max_dd',
      label: 'DD(pips)',
      tooltip: '最大ドローダウン(資金がピークからどれだけ落ち込んだか)',
      format: (v, row) => toPips(Number(v), row.symbol as string).toFixed(1),
    },
    { key: 'win_rate', label: '勝率(%)', format: (v) => Number(v).toFixed(1) },
    { key: 'trades', label: '取引数(回)' },
    {
      key: 'sharpe_ratio',
      label: 'Sharpe',
      tooltip: 'シャープレシオ: リターンの大きさを値動きのブレで割った指標。値動きが安定しているほど高い',
      format: (v) => Number(v).toFixed(2),
    },
    {
      key: 'recovery_factor',
      label: 'Recovery',
      tooltip: 'リカバリーファクター: 純利益÷最大ドローダウン。ドローダウンに対してどれだけ稼げたか',
      format: (v) => Number(v).toFixed(2),
    },
    {
      key: 'sortino_ratio',
      label: 'Sortino',
      tooltip: 'ソルティノレシオ: Sharpeに似ているが、下落方向のブレだけを見る指標(上振れは減点しない)',
      format: (v) => Number(v).toFixed(2),
    },
    {
      key: 'calmar_ratio',
      label: 'Calmar',
      tooltip: 'カルマーレシオ: 年率リターン÷最大ドローダウン',
      format: (v) => Number(v).toFixed(2),
    },
    { key: 'cagr', label: 'CAGR(%)', tooltip: '年率換算した成長率', format: (v) => (Number(v) * 100).toFixed(1) },
    {
      key: 'condition_tree',
      label: '条件',
      format: (v) => (v && typeof v === 'object' ? describeConditionTreeJapanese(v as TreeNode, indicators) : ''),
    },
  ]
}
