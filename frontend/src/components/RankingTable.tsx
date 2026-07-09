import { useState } from 'react'
import { describeConditionTree } from '../conditionTreeUtils'
import type { RankingRow } from '../types'

interface Props {
  rows: RankingRow[]
  selectedRank?: number | null
  onSelectRow?: (row: RankingRow) => void
}

const COLUMNS: {
  key: keyof RankingRow
  label: string
  format?: (v: unknown) => string
  colorClass?: (v: unknown) => string
}[] = [
  { key: 'rank', label: 'Rank' },
  { key: 'net_profit', label: '純利益', format: (v) => Number(v).toFixed(1), colorClass: (v) => (Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400') },
  { key: 'profit_factor', label: 'PF', format: (v) => Number(v).toFixed(2), colorClass: (v) => (Number(v) >= 1 ? 'text-emerald-400' : 'text-red-400') },
  { key: 'expected_value', label: '期待値', format: (v) => Number(v).toFixed(3), colorClass: (v) => (Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400') },
  { key: 'max_dd', label: 'DD', format: (v) => Number(v).toFixed(1) },
  { key: 'win_rate', label: '勝率%', format: (v) => Number(v).toFixed(1) },
  { key: 'trades', label: '取引数' },
  { key: 'sharpe_ratio', label: 'Sharpe', format: (v) => Number(v).toFixed(2) },
  { key: 'recovery_factor', label: 'Recovery', format: (v) => Number(v).toFixed(2) },
  { key: 'sortino_ratio', label: 'Sortino', format: (v) => Number(v).toFixed(2) },
  { key: 'calmar_ratio', label: 'Calmar', format: (v) => Number(v).toFixed(2) },
  { key: 'cagr', label: 'CAGR%', format: (v) => (Number(v) * 100).toFixed(1) },
  {
    key: 'condition_tree',
    label: '条件(自動探索)',
    format: (v) => (v && typeof v === 'object' ? describeConditionTree(v as Parameters<typeof describeConditionTree>[0]) : ''),
  },
]

// A genetic search that's converged (many generations, small population)
// legitimately produces many literal clones near the top - elitism carries
// the same winner forward unchanged, and mutation/crossover of a converged
// population often regenerates it. Showing the same strategy 10 times in
// the ranking isn't useful information, so rows whose entire result
// (metrics + condition tree) matches an earlier row are collapsed to the
// first (best-ranked) occurrence. Keyed on results, not on rank/param_id -
// two DIFFERENT structures that happen to trade identically are just as
// redundant to show twice as two copies of the same structure.
const DEDUP_METRIC_FIELDS: (keyof RankingRow)[] = [
  'net_profit',
  'profit_factor',
  'max_dd',
  'win_rate',
  'trades',
  'expected_value',
  'sharpe_ratio',
]

function resultKey(row: RankingRow): string {
  const metricPart = DEDUP_METRIC_FIELDS.map((f) => row[f]).join('|')
  const treePart = row.condition_tree ? JSON.stringify(row.condition_tree) : ''
  return `${metricPart}::${treePart}`
}

export default function RankingTable({ rows, selectedRank, onSelectRow }: Props) {
  const [sortKey, setSortKey] = useState<keyof RankingRow>('rank')
  const [sortAsc, setSortAsc] = useState(true)

  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const handleSort = (key: keyof RankingRow) => {
    if (key === sortKey) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(true)
    }
  }

  const deduped = (() => {
    const seen = new Set<string>()
    const out: RankingRow[] = []
    for (const row of rows) {
      const key = resultKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(row)
    }
    return out
  })()
  const duplicateCount = rows.length - deduped.length

  const sorted = deduped.slice().sort((a, b) => {
    const av = Number(a[sortKey])
    const bv = Number(b[sortKey])
    if (Number.isNaN(av) || Number.isNaN(bv)) return 0
    return sortAsc ? av - bv : bv - av
  })

  const selectedRow = selectedRank != null ? rows.find((r) => Number(r.rank) === selectedRank) : undefined

  const renderCells = (row: RankingRow) =>
    COLUMNS.map((col) => {
      const raw = row[col.key]
      const text = col.format ? col.format(raw) : String(raw ?? '')
      const colorClass = col.colorClass ? col.colorClass(raw) : ''
      return (
        <td
          key={String(col.key)}
          title={col.key === 'condition_tree' ? text : undefined}
          className={
            col.key === 'condition_tree'
              ? 'max-w-xs truncate px-2 py-1 font-mono text-[11px] text-gray-400'
              : `px-2 py-1 ${colorClass}`
          }
        >
          {text}
        </td>
      )
    })

  return (
    <div>
      {duplicateCount > 0 && (
        <div className="mb-1 px-1 text-[11px] text-gray-500">
          {`同一の結果が${duplicateCount}件あったため非表示にしています(${deduped.length}件を表示)`}
        </div>
      )}
      {/* Ranking rows can run into the thousands (a real auto-exploration batch),
          so this scrolls internally with a sticky header/footer instead of the
          old top-20-only cap - the selected row (tfoot) stays visible even when
          scrolled away from it, lined up under the exact same columns since
          it is a row of the SAME table element, not a separately-positioned one. */}
      <div className="max-h-80 overflow-auto">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 z-10 bg-[#0c0d17]">
          <tr className="border-b border-white/10 text-gray-400">
            {COLUMNS.map((col) => (
              <th
                key={String(col.key)}
                onClick={() => handleSort(col.key)}
                className="cursor-pointer select-none whitespace-nowrap px-2 py-1 font-medium hover:text-gray-200"
              >
                {col.label}
                {sortKey === col.key && <span className="ml-0.5">{sortAsc ? '▲' : '▼'}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={i}
              onClick={() => onSelectRow?.(row)}
              className={`border-b border-white/5 ${onSelectRow ? 'cursor-pointer' : ''} hover:bg-white/[0.04] ${
                selectedRank != null && Number(row.rank) === selectedRank ? 'bg-emerald-500/10' : ''
              }`}
            >
              {renderCells(row)}
            </tr>
          ))}
        </tbody>
        {selectedRow && (
          <tfoot className="sticky bottom-0 z-10 bg-[#0c0d17]">
            <tr className="border-t-2 border-emerald-500/40 bg-emerald-500/[0.06]">{renderCells(selectedRow)}</tr>
          </tfoot>
        )}
      </table>
      </div>
    </div>
  )
}
