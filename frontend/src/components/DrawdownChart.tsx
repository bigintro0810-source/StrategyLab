import Plot from 'react-plotly.js'
import type { EquityPoint } from '../types'

interface Props {
  points: EquityPoint[]
}

export default function DrawdownChart({ points }: Props) {
  if (points.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const x = points.map((p) => p.trade_number)

  return (
    <Plot
      data={[
        {
          x,
          y: points.map((p) => -p.drawdown),
          type: 'scatter',
          mode: 'lines',
          fill: 'tozeroy',
          name: 'ドローダウン',
          line: { color: '#ef4444' },
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
        yaxis: { gridcolor: 'rgba(255,255,255,0.08)', title: { text: 'ドローダウン(pips)' } },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
    />
  )
}
