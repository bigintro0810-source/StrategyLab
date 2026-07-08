import { useState } from 'react'
import type { RankingRow } from '../types'

interface Props {
  rows: RankingRow[]
  selectedRank?: number | null
  onSelectRow?: (row: RankingRow) => void
}

const COLUMNS: { key: keyof RankingRow; label: string; format?: (v: unknown) => string }[] = [
  { key: 'rank', label: 'Rank' },
  { key: 'profit_factor', label: 'PF', format: (v) => Number(v).toFixed(2) },
  { key: 'net_profit', label: '総利益', format: (v) => Number(v).toFixed(1) },
  { key: 'max_dd', label: 'DD', format: (v) => Number(v).toFixed(1) },
  { key: 'win_rate', label: '勝率%', format: (v) => Number(v).toFixed(1) },
  { key: 'recovery_factor', label: 'Recovery', format: (v) => Number(v).toFixed(2) },
  { key: 'sharpe_ratio', label: 'Sharpe', format: (v) => Number(v).toFixed(2) },
  { key: 'sortino_ratio', label: 'Sortino', format: (v) => Number(v).toFixed(2) },
  { key: 'calmar_ratio', label: 'Calmar', format: (v) => Number(v).toFixed(2) },
  { key: 'cagr', label: 'CAGR%', format: (v) => (Number(v) * 100).toFixed(1) },
  { key: 'trades', label: '取引数' },
]

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

  const sorted = rows
    .slice()
    .sort((a, b) => {
      const av = Number(a[sortKey])
      const bv = Number(b[sortKey])
      if (Number.isNaN(av) || Number.isNaN(bv)) return 0
      return sortAsc ? av - bv : bv - av
    })
    .slice(0, 20)

  return (
    <div className="overflow-auto">
      <table className="w-full text-left text-sm">
        <thead>
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
              {COLUMNS.map((col) => (
                <td key={String(col.key)} className="px-2 py-1">
                  {col.format ? col.format(row[col.key]) : String(row[col.key] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
