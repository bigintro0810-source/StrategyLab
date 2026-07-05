import { useEffect, useRef } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  createSeriesMarkers,
  type IChartApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { PriceBar, TradeRow } from '../types'

interface Props {
  bars: PriceBar[]
  trades: TradeRow[]
  emaLength?: number
}

function computeEMA(closes: number[], length: number): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null)
  if (length < 1 || closes.length < length) return result

  const k = 2 / (length + 1)
  let seed = 0
  for (let i = 0; i < length; i++) seed += closes[i]
  let prevEma = seed / length
  result[length - 1] = prevEma

  for (let i = length; i < closes.length; i++) {
    prevEma = closes[i] * k + prevEma * (1 - k)
    result[i] = prevEma
  }
  return result
}

export default function ChartPanel({ bars, trades, emaLength = 20 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: { background: { color: 'transparent' }, textColor: '#d1d5db' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.06)' }, horzLines: { color: 'rgba(255,255,255,0.06)' } },
      timeScale: { timeVisible: true, secondsVisible: false },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 400,
    })
    chartRef.current = chart

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    const times = bars.map((b) => Math.floor(new Date(b.datetime).getTime() / 1000) as UTCTimestamp)
    const data = bars.map((b, i) => ({
      time: times[i],
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }))
    candleSeries.setData(data)

    const emaValues = computeEMA(
      bars.map((b) => b.close),
      emaLength,
    )
    const emaData = emaValues
      .map((v, i) => (v === null ? null : { time: times[i], value: v }))
      .filter((v): v is { time: UTCTimestamp; value: number } => v !== null)
    if (emaData.length > 0) {
      const emaSeries = chart.addSeries(LineSeries, {
        color: '#f59e0b',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        title: `EMA${emaLength}`,
      })
      emaSeries.setData(emaData)
    }

    if (trades.length > 0) {
      const markers = trades
        .flatMap((t) => [
          {
            time: Math.floor(new Date(t.entry_time).getTime() / 1000) as UTCTimestamp,
            position: 'belowBar' as const,
            color: '#3b82f6',
            shape: 'arrowUp' as const,
            text: 'Entry',
          },
          {
            time: Math.floor(new Date(t.exit_time).getTime() / 1000) as UTCTimestamp,
            position: 'aboveBar' as const,
            color: t.profit >= 0 ? '#22c55e' : '#ef4444',
            shape: 'arrowDown' as const,
            text: `${t.profit >= 0 ? '+' : ''}${t.profit.toFixed(1)}`,
          },
        ])
        .sort((a, b) => (a.time as number) - (b.time as number))
      createSeriesMarkers(candleSeries, markers)
    }

    chart.timeScale().fitContent()

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        })
      }
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [bars, trades, emaLength])

  return <div ref={containerRef} className="h-full min-h-[300px] w-full" />
}
