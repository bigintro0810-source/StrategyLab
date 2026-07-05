import type { TradeRow } from '../types'

interface Props {
  rows: TradeRow[]
}

const BASE_COLUMNS: { key: keyof TradeRow; label: string; format?: (v: unknown) => string }[] = [
  { key: 'entry_time', label: 'エントリー時刻' },
  { key: 'entry_price', label: 'エントリー価格', format: (v) => Number(v).toFixed(3) },
  { key: 'exit_time', label: '決済時刻' },
  { key: 'exit_price', label: '決済価格', format: (v) => Number(v).toFixed(3) },
  { key: 'profit', label: '損益(pips)', format: (v) => Number(v).toFixed(2) },
  { key: 'exit_reason', label: '決済理由' },
]

const DIRECTION_COLUMN: { key: keyof TradeRow; label: string; format?: (v: unknown) => string } = {
  key: 'direction',
  label: '方向',
  format: (v) => (v === 'long' ? 'Long' : v === 'short' ? 'Short' : ''),
}

const MAX_ROWS = 200

export default function TradeHistoryTable({ rows }: Props) {
  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  // Only a dual-direction (Long+Short simultaneous) backtest's trades carry a
  // per-trade direction - a single-direction run has no need for the column.
  const hasDirection = rows.some((r) => r.direction != null)
  const COLUMNS = hasDirection
    ? [BASE_COLUMNS[0], DIRECTION_COLUMN, ...BASE_COLUMNS.slice(1)]
    : BASE_COLUMNS

  return (
    <div className="overflow-auto">
      {rows.length > MAX_ROWS && (
        <div className="px-2 py-1 text-xs text-gray-500">
          全{rows.length}件中、直近{MAX_ROWS}件を表示
        </div>
      )}
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
          {rows
            .slice()
            .reverse()
            .slice(0, MAX_ROWS)
            .map((row, i) => (
              <tr key={i} className="border-b border-white/5 hover:bg-white/[0.04]">
                {COLUMNS.map((col) => {
                  const raw = row[col.key]
                  const value = col.format ? col.format(raw) : String(raw ?? '')
                  const isProfit = col.key === 'profit'
                  return (
                    <td
                      key={String(col.key)}
                      className={
                        isProfit
                          ? Number(raw) >= 0
                            ? 'px-2 py-1 text-green-400'
                            : 'px-2 py-1 text-red-400'
                          : 'px-2 py-1'
                      }
                    >
                      {value}
                    </td>
                  )
                })}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}
