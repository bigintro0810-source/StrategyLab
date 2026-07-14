import { useQuery } from '@tanstack/react-query'
import { compareStrategies, type CompareEntry } from '../api'

interface Props {
  ids: string[]
}

const LINE_COLORS = ['#60a5fa', '#c084fc', '#34d399', '#fbbf24', '#f87171', '#22d3ee']

const METRIC_ROWS: { key: keyof CompareEntry['metrics']; label: string; digits: number }[] = [
  { key: 'net_profit', label: '純利益', digits: 2 },
  { key: 'profit_factor', label: 'PF', digits: 2 },
  { key: 'max_dd', label: '最大DD', digits: 2 },
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

export default function CompareScreen({ ids }: Props) {
  const compareQuery = useQuery({
    queryKey: ['compare-strategies', ids],
    queryFn: () => compareStrategies(ids),
    enabled: ids.length > 0,
  })

  if (ids.length === 0) {
    return (
      <div className="glass-panel rounded-2xl p-4 text-sm text-gray-500">
        比較対象がありません。ライブラリ画面で戦略を2件以上選んでください。
      </div>
    )
  }

  const entries = compareQuery.data?.entries ?? []
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
              d={buildPath(entry.equity_curve, width, height)}
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
                  {entries.map((entry) => (
                    <td key={entry.id} className="py-1 pr-3">
                      {typeof entry.metrics[row.key] === 'number' ? entry.metrics[row.key].toFixed(row.digits) : '-'}
                    </td>
                  ))}
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
