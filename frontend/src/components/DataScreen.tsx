import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchPriceData } from '../api'
import ChartPanel from './ChartPanel'

interface Props {
  symbols: string[]
  timeframes: string[]
}

export default function DataScreen({ symbols, timeframes }: Props) {
  const [symbol, setSymbol] = useState(symbols[0])
  const [timeframe, setTimeframe] = useState('15m')
  const [emaLength, setEmaLength] = useState(20)

  const priceQuery = useQuery({
    queryKey: ['data-screen-price', symbol, timeframe],
    queryFn: () => fetchPriceData(symbol, timeframe, 1000),
  })

  const bars = priceQuery.data ?? []
  const first = bars[0]
  const last = bars[bars.length - 1]

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-gray-300">
        <select
          className="glass-input rounded-lg px-2 py-1.5"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
        >
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <div className="flex overflow-hidden rounded-lg border border-white/10">
          {timeframes.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              className={
                tf === timeframe
                  ? 'bg-blue-500/30 px-2 py-1.5 font-semibold text-blue-100'
                  : 'px-2 py-1.5 text-gray-400 hover:bg-white/5 hover:text-gray-200'
              }
            >
              {tf}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5">
          EMA
          <input
            type="number"
            min={1}
            className="glass-input w-16 rounded-lg px-1.5 py-1"
            value={emaLength}
            onChange={(e) => setEmaLength(Number(e.target.value))}
          />
        </label>
        {priceQuery.isFetching && <span className="text-gray-500">読み込み中…</span>}
      </div>

      <div style={{ height: 520 }}>
        <ChartPanel bars={bars} trades={[]} emaLength={emaLength} symbol={symbol} />
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-400">
        <span className="rounded-lg border border-white/10 bg-white/[0.02] px-2 py-1">
          本数 {bars.length.toLocaleString()}
        </span>
        {first && last && (
          <span className="rounded-lg border border-white/10 bg-white/[0.02] px-2 py-1">
            期間 {String(first.datetime).slice(0, 10)} 〜 {String(last.datetime).slice(0, 10)}
          </span>
        )}
      </div>
    </div>
  )
}
