import Plot from 'react-plotly.js'
import { toPips } from '../pipUtils'
import { buildMetricColumns, type MetricRowLike } from '../rankingColumns'
import type { CompareEntry } from '../api'
import type { IndicatorInfo } from '../types'

interface Props {
  entries: CompareEntry[]
  emptyMessage: string
  indicators: IndicatorInfo[]
}

const LINE_COLORS = ['#60a5fa', '#c084fc', '#34d399', '#fbbf24', '#f87171', '#22d3ee']

// entry.metrics(strategy_registry.pyのMETRIC_COLUMNS、あるいは結果側で
// App.tsxがrankingTotalの行から組み立てたもの)はexpected_valueを持たない
// ため、ランキング一覧/ライブラリ画面と同じ定義(net_profit÷trades)で
// ここでも計算する。
function toMetricRow(entry: CompareEntry): MetricRowLike {
  const m = entry.metrics
  const trades = Number(m.trades) || 0
  return {
    profit_factor: m.profit_factor,
    net_profit: m.net_profit,
    expected_value: trades > 0 ? Number(m.net_profit) / trades : 0,
    max_dd: m.max_dd,
    win_rate: m.win_rate,
    trades: m.trades,
    sharpe_ratio: m.sharpe_ratio,
    recovery_factor: m.recovery_factor,
    sortino_ratio: m.sortino_ratio,
    calmar_ratio: m.calmar_ratio,
    cagr: m.cagr,
    condition_tree: entry.condition_tree,
    symbol: entry.symbol,
  }
}

export default function CompareView({ entries, emptyMessage, indicators }: Props) {
  if (entries.length === 0) {
    return <div className="glass-panel rounded-2xl p-4 text-sm text-gray-500">{emptyMessage}</div>
  }

  const columns = buildMetricColumns(indicators)

  return (
    <div className="space-y-4">
      {/* ランキング一覧/ライブラリ画面と同じ並び(お気に入り〜条件)の指標
          テーブル - 1行=1ストラテジー。ここの⭐は状態表示のみで、切り替えは
          元の画面(ランキング一覧/ライブラリ)から行う。 */}
      <div className="glass-panel rounded-2xl p-4">
        <div className="overflow-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 text-gray-400">
                <th className="px-2 py-1 font-medium" />
                <th className="whitespace-nowrap px-2 py-1 font-medium">名称</th>
                <th className="whitespace-nowrap px-2 py-1 font-medium">通貨/時間足</th>
                {columns.map((col) => (
                  <th key={col.key} title={col.tooltip} className="whitespace-nowrap px-2 py-1 font-medium">
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const row = toMetricRow(entry)
                return (
                  <tr key={entry.id} className="border-b border-white/5 hover:bg-white/[0.04]">
                    <td className="px-2 py-1">
                      <span className={entry.favorite ? 'grayscale-0 opacity-100' : 'grayscale opacity-40'}>⭐</span>
                    </td>
                    <td className="whitespace-nowrap px-2 py-1">{entry.name}</td>
                    <td className="whitespace-nowrap px-2 py-1 text-gray-300">
                      {entry.symbol}/{entry.timeframe}
                    </td>
                    {columns.map((col) => {
                      const raw = row[col.key]
                      const text = col.format ? col.format(raw, row) : String(raw ?? '')
                      const colorClass = col.colorClass ? col.colorClass(raw) : ''
                      return (
                        <td
                          key={col.key}
                          title={col.key === 'condition_tree' ? text : undefined}
                          className={
                            col.key === 'condition_tree'
                              ? 'max-w-xs truncate px-2 py-1 font-mono text-[11px] text-gray-400'
                              : `whitespace-nowrap px-2 py-1 ${colorClass}`
                          }
                        >
                          {text}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-1 text-center text-lg font-semibold text-gray-300">累積Pips</div>
        <Plot
          data={entries.map((entry, i) => ({
            x: entry.equity_curve.map((p) => p.exit_time),
            y: entry.equity_curve.map((p) => toPips(p.equity, entry.symbol)),
            type: 'scatter',
            mode: 'lines',
            name: entry.name,
            line: { color: LINE_COLORS[i % LINE_COLORS.length], width: 1.5 },
          }))}
          layout={{
            autosize: true,
            height: 280,
            margin: { l: 40, r: 10, t: 10, b: 30 },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            font: { color: '#d1d5db' },
            showlegend: true,
            legend: { orientation: 'h', font: { size: 10 } },
            xaxis: {
              type: 'date',
              dtick: 'M12',
              tickformat: '%Y',
              gridcolor: 'rgba(255,255,255,0.08)',
            },
            yaxis: { gridcolor: 'rgba(255,255,255,0.08)' },
          }}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: '100%' }}
        />
      </div>
    </div>
  )
}
