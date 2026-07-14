import { toPips } from '../pipUtils'
import type { RankingRow } from '../types'

interface Props {
  row: RankingRow | undefined
  symbol: string | undefined
}

function fmt(v: number | undefined, digits = 2): string {
  if (v === undefined || Number.isNaN(v)) return '-'
  return v.toFixed(digits)
}

function signedFmt(v: number | undefined, digits: number): string {
  if (v === undefined || Number.isNaN(v)) return '-'
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`
}

// タブ切り替えの外側・常時表示する統計ストリップ。ランキング一覧の列と
// 同じ項目・同じ順序・同じ単位(PF,純利益(pips),期待値(pips),DD(pips),
// 勝率(%),取引数(回),Sharpe,Recovery,Sortino,Calmar,CAGR(%))で揃えてある -
// 同じ戦略の同じ指標が画面によって違う書き方をしていると混乱するため。
export default function StatsPanel({ row, symbol }: Props) {
  if (!row) {
    return <div className="mb-2 text-xs text-gray-500">まだ結果がありません</div>
  }

  const stats: { label: string; value: string }[] = [
    { label: 'PF', value: fmt(row.profit_factor) },
    { label: '純利益(pips)', value: signedFmt(toPips(row.net_profit, symbol), 1) },
    { label: '期待値(pips)', value: signedFmt(toPips(row.expected_value, symbol), 3) },
    { label: 'DD(pips)', value: fmt(toPips(row.max_dd, symbol), 1) },
    { label: '勝率(%)', value: fmt(row.win_rate, 1) },
    { label: '取引数(回)', value: String(row.trades) },
    { label: 'Sharpe', value: fmt(row.sharpe_ratio) },
    { label: 'Recovery', value: fmt(row.recovery_factor) },
    { label: 'Sortino', value: fmt(row.sortino_ratio) },
    { label: 'Calmar', value: fmt(row.calmar_ratio) },
    { label: 'CAGR(%)', value: fmt(row.cagr * 100, 1) },
  ]

  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-1.5 text-xs">
      {stats.map((s) => (
        <div key={s.label} className="flex items-center gap-1 whitespace-nowrap">
          <span className="text-gray-400">{s.label}</span>
          <span className="font-semibold text-gray-100">{s.value}</span>
        </div>
      ))}
    </div>
  )
}
