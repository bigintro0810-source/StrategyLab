import Plot from 'react-plotly.js'
import type { MonthlyRow } from '../types'

interface Props {
  rows: MonthlyRow[]
}

const MONTH_LABELS = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

export default function MonthlyHeatmap({ rows }: Props) {
  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const years = Array.from(new Set(rows.map((r) => r.year_month.slice(0, 4)))).sort()
  const byKey = new Map(rows.map((r) => [r.year_month, r]))

  const z = years.map((year) =>
    MONTH_LABELS.map((_, i) => {
      const key = `${year}-${String(i + 1).padStart(2, '0')}`
      return byKey.get(key)?.net_profit ?? null
    }),
  )
  const text = years.map((year) =>
    MONTH_LABELS.map((_, i) => {
      const key = `${year}-${String(i + 1).padStart(2, '0')}`
      const row = byKey.get(key)
      return row ? `${row.net_profit.toFixed(1)}pips\n(${row.trades}件)` : ''
    }),
  )

  return (
    <Plot
      data={[
        {
          x: MONTH_LABELS,
          y: years,
          z,
          text,
          texttemplate: '%{text}',
          type: 'heatmap',
          colorscale: [
            [0, '#ef4444'],
            [0.5, '#111318'],
            [1, '#22c55e'],
          ],
          zmid: 0,
          hoverongaps: false,
          showscale: false,
        },
      ]}
      layout={{
        autosize: true,
        height: 90 + years.length * 40,
        margin: { l: 50, r: 10, t: 10, b: 30 },
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#d1d5db', size: 10 },
        xaxis: { side: 'top' },
        yaxis: { autorange: 'reversed' },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
    />
  )
}
