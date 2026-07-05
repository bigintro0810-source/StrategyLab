import Plot from 'react-plotly.js'
import type { YearlyRow } from '../types'

interface Props {
  rows: YearlyRow[]
}

export default function YearlyPerformanceChart({ rows }: Props) {
  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const sorted = rows.slice().sort((a, b) => a.year - b.year)

  return (
    <Plot
      data={[
        {
          x: sorted.map((r) => String(r.year)),
          y: sorted.map((r) => r.net_profit),
          type: 'bar',
          marker: {
            color: sorted.map((r) => (r.net_profit >= 0 ? '#22c55e' : '#ef4444')),
          },
        },
      ]}
      layout={{
        autosize: true,
        height: 260,
        margin: { l: 40, r: 10, t: 10, b: 30 },
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#d1d5db' },
        xaxis: { gridcolor: 'rgba(255,255,255,0.08)', title: { text: '年' } },
        yaxis: { gridcolor: 'rgba(255,255,255,0.08)', title: { text: '損益(pips)' } },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
    />
  )
}
