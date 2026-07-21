import { describeStrategyConditionJapanese } from './conditionTreeUtils'
import { pipsDecimals, toPips } from './pipUtils'
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
  long_condition_tree?: TreeNode
  short_condition_tree?: TreeNode
  symbol?: unknown
  [key: string]: unknown
}

// + prefix on positive net_profit/expected_value so a quick scan of the
// column makes profitable vs unprofitable rows visually obvious without
// needing the color alone (color-blind friendly, and prints in black&white).
export function signedFixed(v: unknown, digits: number): string {
  const n = Number(v)
  if (Number.isNaN(n)) return '-'
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}`
}

// 合成ストラテジー(symbol="COMPOSITE")はSharpe/Sortino/Calmar/CAGR等を
// 計算しないため、metricsにそのキー自体が無い(undefined) - Number(v)が
// NaNになり、素のtoFixed()だと文字列"NaN"がそのまま表示されてしまう
// (今まで全ての行が全指標を持っていたため気づかれていなかった不具合)。
// StatsPanel.tsx側のfmt()と同じ「未定義/NaNは'-'」ルールをここでも使う。
export function safeFixed(v: unknown, digits: number): string {
  const n = Number(v)
  return Number.isNaN(n) ? '-' : n.toFixed(digits)
}

// 指標見出しを最初にクリックした時、「良い順」で並ぶようにするための方向
// 指定 - ほとんどの指標は大きいほど良い(降順が良い順)が、DDだけは小さい
// ほど良い(昇順が良い順)。RankingTable.tsx/LibraryScreen.tsxのhandleSort
// が新しい列に切り替える際、ここでtrueが返る列だけ昇順スタート、それ以外は
// 降順スタートにする。
const LOWER_IS_BETTER = new Set(['max_dd'])

export function ascendingIsBetter(key: string): boolean {
  return LOWER_IS_BETTER.has(key)
}

export function getFilterValue(col: MetricColumn, v: unknown, row: MetricRowLike): number {
  return col.filterValue ? col.filterValue(v, row) : Number(v)
}

export function passesFilters(
  row: MetricRowLike,
  filters: Record<string, string>,
  columns: MetricColumn[],
): boolean {
  for (const col of columns) {
    const threshold = filters[col.key]
    if (!threshold) continue
    const thresholdNum = Number(threshold)
    if (Number.isNaN(thresholdNum)) continue
    const value = getFilterValue(col, row[col.key], row)
    if (Number.isNaN(value)) return false
    if (ascendingIsBetter(col.key) ? value > thresholdNum : value < thresholdNum) return false
  }
  return true
}

export interface MetricColumn {
  key: string
  label: string
  tooltip?: string
  format?: (v: unknown, row: MetricRowLike) => string
  colorClass?: (v: unknown) => string
  // 見出し下のフィルター行(RankingTable.tsx/LibraryScreen.tsx)が閾値と
  // 比較する数値 - 未指定ならNumber(v)をそのまま使うが、pips換算や%換算が
  // 入る列(純利益/期待値/DD/CAGR)は表示されている数値と揃えるためここで
  // 変換する。省略した列は数値フィルター非対応(条件など)。
  filterValue?: (v: unknown, row: MetricRowLike) => number
  filterable?: boolean
  // 数値列は右揃えにする(RankingTable.tsx/LibraryScreen.tsx) - 「条件」
  // だけ文章なので左揃えのままにする。
  numeric?: boolean
  // 直前の列見出しとの間隔を広げたい列だけ指定する(既定はpx-1の詰まった
  // 間隔)。ヘッダー行と本文セル(RankingTable.tsx/LibraryScreen.tsx/
  // CompareView.tsx)の両方に同じ値を使うことで見出しと中身の位置を揃える -
  // 本文の「条件」セルはfont-mono text-[11px]でヘッダーと文字サイズが
  // 異なるため、em単位だと同じ数値でも実際の幅がずれてしまう。px固定値に
  // することでどちらのセルでも同じ実幅になるようにしている(フィルター
  // 入力行には適用しない)。
  headerPadLeft?: string
}

export function buildMetricColumns(indicators: IndicatorInfo[]): MetricColumn[] {
  return [
    {
      key: 'profit_factor',
      label: 'PF',
      tooltip: 'プロフィットファクター(総利益÷総損失。1より大きければ黒字)',
      format: (v) => safeFixed(v, 2),
      colorClass: (v) => (Number(v) >= 1 ? 'text-emerald-400' : 'text-red-400'),
      filterable: true,
      numeric: true,
    },
    {
      key: 'net_profit',
      label: '純利益(pips)',
      format: (v, row) => signedFixed(toPips(Number(v), row.symbol as string), 1),
      colorClass: (v) => (Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400'),
      filterValue: (v, row) => toPips(Number(v), row.symbol as string),
      filterable: true,
      numeric: true,
    },
    {
      key: 'expected_value',
      label: '期待値(pips)',
      format: (v, row) => signedFixed(toPips(Number(v), row.symbol as string), pipsDecimals(row.symbol as string)),
      colorClass: (v) => (Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400'),
      filterValue: (v, row) => toPips(Number(v), row.symbol as string),
      filterable: true,
      numeric: true,
    },
    {
      key: 'max_dd',
      label: 'DD(pips)',
      tooltip: '最大ドローダウン(資金がピークからどれだけ落ち込んだか)',
      format: (v, row) => safeFixed(toPips(Number(v), row.symbol as string), 1),
      filterValue: (v, row) => toPips(Number(v), row.symbol as string),
      filterable: true,
      numeric: true,
    },
    { key: 'win_rate', label: '勝率(%)', format: (v) => safeFixed(v, 1), filterable: true, numeric: true },
    { key: 'trades', label: '取引数(回)', filterable: true, numeric: true },
    {
      key: 'sharpe_ratio',
      label: 'Sharpe',
      tooltip: 'シャープレシオ: リターンの大きさを値動きのブレで割った指標。値動きが安定しているほど高い',
      format: (v) => safeFixed(v, 2),
      filterable: true,
      numeric: true,
    },
    {
      key: 'recovery_factor',
      label: 'Recovery',
      tooltip: 'リカバリーファクター: 純利益÷最大ドローダウン。ドローダウンに対してどれだけ稼げたか',
      format: (v) => safeFixed(v, 2),
      filterable: true,
      numeric: true,
    },
    {
      key: 'sortino_ratio',
      label: 'Sortino',
      tooltip: 'ソルティノレシオ: Sharpeに似ているが、下落方向のブレだけを見る指標(上振れは減点しない)',
      format: (v) => safeFixed(v, 2),
      filterable: true,
      numeric: true,
    },
    {
      key: 'calmar_ratio',
      label: 'Calmar',
      tooltip: 'カルマーレシオ: 年率リターン÷最大ドローダウン',
      format: (v) => safeFixed(v, 2),
      filterable: true,
      numeric: true,
    },
    {
      key: 'cagr',
      label: 'CAGR(%)',
      tooltip: '年率換算した成長率',
      format: (v) => safeFixed(Number(v) * 100, 1),
      filterValue: (v) => Number(v) * 100,
      filterable: true,
      numeric: true,
    },
    {
      key: 'condition_tree',
      label: '条件',
      format: (_v, row) => describeStrategyConditionJapanese(row, indicators),
      // RankingTable.tsx/LibraryScreen.tsx(text-xs=12px基準)の全角2文字分。
      headerPadLeft: 'pl-[24px]',
    },
  ]
}
