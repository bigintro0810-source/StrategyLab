import Plot from 'react-plotly.js'
import type { EquityPoint } from '../types'

interface Props {
  points: EquityPoint[]
}

export default function EquityCurveChart({ points }: Props) {
  if (points.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const x = points.map((p) => p.trade_number)

  return (
    <Plot
      data={[
        {
          x,
          y: points.map((p) => p.equity),
          type: 'scatter',
          mode: 'lines',
          name: 'エクイティ',
          line: { color: '#22c55e' },
        },
      ]}
      layout={{
        autosize: true,
        height: 260,
        margin: { l: 40, r: 10, t: 10, b: 30 },
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#d1d5db' },
        xaxis: { gridcolor: 'rgba(255,255,255,0.08)', title: { text: '取引番号' } },
        yaxis: { gridcolor: 'rgba(255,255,255,0.08)', title: { text: '損益(pips)' } },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
    />
  )
}
