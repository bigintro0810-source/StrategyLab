import Plot from 'react-plotly.js'
import { computeComposite, type CompositeInput } from '../compositeUtils'

interface Props {
  inputs: CompositeInput[]
  // trade_logをまだ取得中(rerun/フェッチ待ち)のものがあれば伝える -
  // 合成結果自体は届いた分だけで計算するが、まだ足りないことを示す。
  pendingCount: number
}

function fmt(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return '-'
  return v.toFixed(digits)
}

function signedFmt(v: number, digits: number): string {
  if (!Number.isFinite(v)) return '-'
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`
}

export default function CompositeDetail({ inputs, pendingCount }: Props) {
  if (inputs.length === 0 && pendingCount === 0) {
    return (
      <div className="glass-panel rounded-2xl p-8 text-center text-sm text-gray-500">
        「合成」のチェックボックスを付けると、選んだストラテジーをまとめて1つの資金曲線として合成した結果がここに表示されます。
      </div>
    )
  }

  const composite = computeComposite(inputs)

  const stats: { label: string; value: string }[] = [
    { label: 'PF', value: fmt(composite.profitFactor) },
    { label: '純利益(pips)', value: signedFmt(composite.netProfitPips, 1) },
    { label: '期待値(pips)', value: signedFmt(composite.expectedValuePips, 3) },
    { label: 'DD(pips)', value: fmt(composite.maxDdPips, 1) },
    { label: '勝率(%)', value: fmt(composite.winRate, 1) },
    { label: '取引数(回)', value: String(composite.trades) },
  ]

  return (
    <div className="space-y-3">
      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-2 text-sm font-semibold text-gray-200">合成対象({inputs.length}件)</div>
        <div className="flex flex-wrap gap-1.5 text-xs text-gray-300">
          {inputs.map((input) => (
            <span key={input.id} className="rounded-full bg-white/5 px-2 py-0.5">
              {input.name}
              {input.symbol && input.timeframe && (
                <span className="text-gray-500"> ({input.symbol}/{input.timeframe})</span>
              )}
            </span>
          ))}
          {pendingCount > 0 && (
            <span className="rounded-full bg-white/5 px-2 py-0.5 text-gray-500">読み込み中×{pendingCount}</span>
          )}
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          {stats.map((s) => (
            <div key={s.label} className="flex items-center gap-1 whitespace-nowrap">
              <span className="text-gray-400">{s.label}</span>
              <span className="font-semibold text-gray-100">{s.value}</span>
            </div>
          ))}
        </div>
        {composite.equityCurve.length === 0 ? (
          <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
        ) : (
          <>
            <div className="mb-1 text-center text-lg font-semibold text-gray-300">累積Pips</div>
            <Plot
              data={[
                {
                  x: composite.equityCurve.map((p) => p.exit_time),
                  y: composite.equityCurve.map((p) => p.equity),
                  type: 'scatter',
                  mode: 'lines+markers',
                  name: '合成エクイティ',
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
                xaxis: { type: 'date', gridcolor: 'rgba(255,255,255,0.08)' },
                yaxis: { gridcolor: 'rgba(255,255,255,0.08)' },
              }}
              config={{ displayModeBar: false, responsive: true }}
              style={{ width: '100%' }}
            />
          </>
        )}
      </div>
    </div>
  )
}
