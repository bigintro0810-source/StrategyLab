import Plot from 'react-plotly.js'
import { toPips } from '../pipUtils'
import type { EquityPoint } from '../types'

interface Props {
  points: EquityPoint[]
  symbol: string | undefined
}

export default function EquityCurveChart({ points, symbol }: Props) {
  if (points.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const x = points.map((p) => p.exit_time)

  return (
    <div>
      <div className="mb-1 text-center text-lg font-semibold text-gray-300">累積Pips</div>
      <Plot
        data={[
          {
            x,
            y: points.map((p) => toPips(p.equity, symbol)),
            type: 'scatter',
            mode: 'lines+markers',
            name: 'エクイティ',
            line: { color: '#22c55e', width: 1.5 },
            marker: { color: '#22c55e', size: 4, line: { width: 0 } },
          },
        ]}
        layout={{
          autosize: true,
          height: 260,
          margin: { l: 40, r: 10, t: 10, b: 30 },
          paper_bgcolor: 'transparent',
          plot_bgcolor: 'transparent',
          font: { color: '#d1d5db' },
          // dtick: 'M12'で1年ごとに目盛り/グリッド線を必ず引く(Plotly任せの
          // 自動間引きだと期間が長いほど数年おきにしか線が出ず粗く見えるため)。
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
