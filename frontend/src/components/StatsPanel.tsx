import type { RankingRow } from '../types'

interface Props {
  row: RankingRow | undefined
}

function fmt(v: number | undefined, digits = 2): string {
  if (v === undefined || Number.isNaN(v)) return '-'
  return v.toFixed(digits)
}

export default function StatsPanel({ row }: Props) {
  if (!row) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const profitOverDd = row.max_dd > 0 ? row.net_profit / row.max_dd : 0

  const stats: { label: string; value: string }[] = [
    { label: 'PF', value: fmt(row.profit_factor) },
    { label: '勝率%', value: fmt(row.win_rate, 1) },
    { label: '損益期待値', value: fmt(row.expected_value) },
    { label: '最大DD', value: fmt(row.max_dd, 1) },
    { label: 'Recovery Factor', value: fmt(row.recovery_factor) },
    { label: 'Sharpe', value: fmt(row.sharpe_ratio) },
    { label: 'Sortino', value: fmt(row.sortino_ratio) },
    { label: 'Calmar', value: fmt(row.calmar_ratio) },
    { label: 'CAGR', value: `${fmt(row.cagr * 100, 1)}%` },
    { label: 'Profit/DD', value: fmt(profitOverDd) },
  ]

  return (
    <div className="grid grid-cols-2 gap-2 text-sm">
      {stats.map((s) => (
        <div key={s.label} className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
          <div className="text-xs text-gray-400">{s.label}</div>
          <div className="font-semibold text-gray-100">{s.value}</div>
        </div>
      ))}
    </div>
  )
}
