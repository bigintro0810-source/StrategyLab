import { toPips } from '../pipUtils'
import type { CompareEntry } from '../api'

interface Props {
  entries: CompareEntry[]
  emptyMessage: string
}

const LINE_COLORS = ['#60a5fa', '#c084fc', '#34d399', '#fbbf24', '#f87171', '#22d3ee']

// pips換算が要る行(net_profit/max_dd - engine/backtest_engine.pyが生の価格差
// のまま"pips"と呼ぶ既存の慣習で計算しているため、他の画面同様ここで
// entry.symbolのpip_sizeで割ってから表示する)とそのまま表示できる行を分けて
// 定義する。
const METRIC_ROWS: { key: keyof CompareEntry['metrics']; label: string; digits: number; isPips?: boolean }[] = [
  { key: 'net_profit', label: '純利益(pips)', digits: 1, isPips: true },
  { key: 'profit_factor', label: 'PF', digits: 2 },
  { key: 'max_dd', label: '最大DD(pips)', digits: 1, isPips: true },
  { key: 'win_rate', label: '勝率%', digits: 1 },
  { key: 'trades', label: 'トレード数', digits: 0 },
  { key: 'recovery_factor', label: 'Recovery', digits: 2 },
  { key: 'sharpe_ratio', label: 'Sharpe', digits: 2 },
  { key: 'sortino_ratio', label: 'Sortino', digits: 2 },
  { key: 'calmar_ratio', label: 'Calmar', digits: 2 },
]

function buildPath(series: number[], width: number, height: number): string {
  if (series.length === 0) return ''
  const min = Math.min(...series, 0)
  const max = Math.max(...series, 0)
  const range = max - min || 1
  return series
    .map((v, i) => {
      const x = (i / Math.max(series.length - 1, 1)) * width
      const y = height - ((v - min) / range) * height
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

export default function CompareView({ entries, emptyMessage }: Props) {
  if (entries.length === 0) {
    return <div className="glass-panel rounded-2xl p-4 text-sm text-gray-500">{emptyMessage}</div>
  }

  const width = 640
  const height = 220

  return (
    <div className="space-y-4">
      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-3 text-sm font-semibold text-gray-200">Equity Curve比較(トレード進捗率で正規化)</div>
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
          {entries.map((entry, i) => (
            <path
              key={entry.id}
              d={buildPath(
                entry.equity_curve.map((v) => toPips(v, entry.symbol)),
                width,
                height,
              )}
              fill="none"
              stroke={LINE_COLORS[i % LINE_COLORS.length]}
              strokeWidth={1.5}
            />
          ))}
        </svg>
        <div className="mt-2 flex flex-wrap gap-3 text-xs">
          {entries.map((entry, i) => (
            <span key={entry.id} className="flex items-center gap-1.5 text-gray-300">
              <span className="h-2 w-2 rounded-full" style={{ background: LINE_COLORS[i % LINE_COLORS.length] }} />
              {entry.name}
            </span>
          ))}
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-3 text-sm font-semibold text-gray-200">指標比較</div>
        <div className="overflow-auto">
          <table className="w-full text-left text-xs text-gray-300">
            <thead className="text-gray-500">
              <tr>
                <th className="py-1 pr-3">指標</th>
                {entries.map((entry) => (
                  <th key={entry.id} className="py-1 pr-3">
                    {entry.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRIC_ROWS.map((row) => (
                <tr key={row.key} className="border-t border-white/5">
                  <td className="py-1 pr-3 text-gray-400">{row.label}</td>
                  {entries.map((entry) => {
                    const raw = entry.metrics[row.key]
                    const value = typeof raw === 'number' ? (row.isPips ? toPips(raw, entry.symbol) : raw) : null
                    return (
                      <td key={entry.id} className="py-1 pr-3">
                        {value === null ? '-' : value.toFixed(row.digits)}
                      </td>
                    )
                  })}
                </tr>
              ))}
              <tr className="border-t border-white/5">
                <td className="py-1 pr-3 text-gray-400">タグ</td>
                {entries.map((entry) => (
                  <td key={entry.id} className="py-1 pr-3">
                    {entry.tags.join(', ') || '-'}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
