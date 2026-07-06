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

const POSITION_SIZING_COLUMNS: { key: keyof TradeRow; label: string; format?: (v: unknown) => string }[] = [
  { key: 'lot_size', label: 'ロット' },
  { key: 'profit_currency', label: '損益(通貨額)', format: (v) => Number(v).toLocaleString() },
  { key: 'account_balance', label: '残高', format: (v) => Number(v).toLocaleString() },
]

const PARTIAL_TP_COLUMN: { key: keyof TradeRow; label: string; format?: (v: unknown) => string } = {
  key: 'partial_exit_price',
  label: '部分利確価格',
  format: (v) => (v == null ? '-' : Number(v).toFixed(3)),
}

const MAX_ROWS = 200

export default function TradeHistoryTable({ rows }: Props) {
  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  // Only a dual-direction (Long+Short simultaneous) backtest's trades carry a
  // per-trade direction - a single-direction run has no need for the column.
  const hasDirection = rows.some((r) => r.direction != null)
  // Only trades from a run with position sizing enabled carry these fields.
  const hasPositionSizing = rows.some((r) => r.lot_size != null)
  // Only present when at least one trade actually took a partial profit
  // (use_partial_tp) - most trades in such a run still won't have it.
  const hasPartialTp = rows.some((r) => r.partial_exit_price != null)
  const COLUMNS = [
    BASE_COLUMNS[0],
    ...(hasDirection ? [DIRECTION_COLUMN] : []),
    ...BASE_COLUMNS.slice(1),
    ...(hasPositionSizing ? POSITION_SIZING_COLUMNS : []),
    ...(hasPartialTp ? [PARTIAL_TP_COLUMN] : []),
  ]

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
