import Plot from 'react-plotly.js'
import type { RankingRow } from '../types'

interface Props {
  rows: RankingRow[]
  paramX: string
  paramY: string
  metric: string
  metricLabel: string
}

export default function OptimizationSurface({ rows, paramX, paramY, metric, metricLabel }: Props) {
  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const xValues = Array.from(new Set(rows.map((r) => Number(r[paramX])))).sort((a, b) => a - b)
  const yValues = Array.from(new Set(rows.map((r) => Number(r[paramY])))).sort((a, b) => a - b)

  if (xValues.length < 2 || yValues.length < 2) {
    return (
      <div className="p-4 text-sm text-gray-500">
        2つのパラメータそれぞれで2値以上の範囲を指定して実行すると、ここに3Dグラフが表示されます。
      </div>
    )
  }

  const byKey = new Map(rows.map((r) => [`${r[paramX]}|${r[paramY]}`, r]))
  const z = yValues.map((y) => xValues.map((x) => Number(byKey.get(`${x}|${y}`)?.[metric] ?? null)))

  return (
    <Plot
      data={[
        {
          x: xValues,
          y: yValues,
          z,
          type: 'surface',
          colorscale: [
            [0, '#ef4444'],
            [0.5, '#111318'],
            [1, '#22c55e'],
          ],
          showscale: false,
        },
      ]}
      layout={{
        autosize: true,
        height: 340,
        margin: { l: 0, r: 0, t: 10, b: 0 },
        paper_bgcolor: 'transparent',
        font: { color: '#d1d5db', size: 10 },
        scene: {
          xaxis: { title: { text: paramX }, gridcolor: 'rgba(255,255,255,0.1)' },
          yaxis: { title: { text: paramY }, gridcolor: 'rgba(255,255,255,0.1)' },
          zaxis: { title: { text: metricLabel }, gridcolor: 'rgba(255,255,255,0.1)' },
          bgcolor: 'transparent',
        },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
    />
  )
}
