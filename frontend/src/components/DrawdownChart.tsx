import Plot from 'react-plotly.js'
import { toPips } from '../pipUtils'
import type { EquityPoint } from '../types'

interface Props {
  points: EquityPoint[]
  symbol: string | undefined
}

export default function DrawdownChart({ points, symbol }: Props) {
  if (points.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const x = points.map((p) => p.exit_time)

  return (
    <div>
      <div className="mb-1 text-center text-lg font-semibold text-gray-300">ドローダウン</div>
      <Plot
        data={[
          {
            x,
            y: points.map((p) => -toPips(p.drawdown, symbol)),
            type: 'scatter',
            mode: 'lines+markers',
            fill: 'tozeroy',
            name: 'ドローダウン',
            line: { color: '#ef4444', width: 1.5 },
            marker: { color: '#ef4444', size: 4, line: { width: 0 } },
          },
        ]}
        layout={{
          autosize: true,
          height: 260,
          margin: { l: 40, r: 10, t: 10, b: 30 },
          paper_bgcolor: 'transparent',
          plot_bgcolor: 'transparent',
          font: { color: '#d1d5db' },
          // dtick: 'M12'で1年ごとに目盛り/グリッド線を必ず引く(EquityCurveChart
          // と同じ理由)。
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
  )
}
