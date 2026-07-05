import type { RankingRow } from '../types'

interface Props {
  rows: RankingRow[]
}

const COLUMNS: { key: keyof RankingRow; label: string; format?: (v: unknown) => string }[] = [
  { key: 'rank', label: 'Rank' },
  { key: 'profit_factor', label: 'PF', format: (v) => Number(v).toFixed(2) },
  { key: 'net_profit', label: '総利益', format: (v) => Number(v).toFixed(1) },
  { key: 'max_dd', label: 'DD', format: (v) => Number(v).toFixed(1) },
  { key: 'win_rate', label: '勝率%', format: (v) => Number(v).toFixed(1) },
  { key: 'recovery_factor', label: 'Recovery', format: (v) => Number(v).toFixed(2) },
  { key: 'trades', label: '取引数' },
]

export default function RankingTable({ rows }: Props) {
  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  return (
    <div className="overflow-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-gray-400">
            {COLUMNS.map((col) => (
              <th key={String(col.key)} className="px-2 py-1 font-medium">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 20).map((row, i) => (
            <tr key={i} className="border-b border-white/5 hover:bg-white/[0.04]">
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
