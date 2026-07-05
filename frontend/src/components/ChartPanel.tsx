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
  symbol?: string
}

// JPY pairs are quoted to 3 decimals (e.g. 154.321), everything else to 5
// (e.g. 1.14347) - lightweight-charts defaults to 2, which would truncate
// exactly the pip-level detail a strategy's conditions actually operate on.
function priceFormatFor(symbol: string | undefined) {
  const isJpyPair = (symbol ?? '').toUpperCase().includes('JPY')
  return isJpyPair
    ? { type: 'price' as const, precision: 3, minMove: 0.001 }
    : { type: 'price' as const, precision: 5, minMove: 0.00001 }
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

// Wilder smoothing, matching engine/backtest_engine.py's RSI/ATR so the chart
// overlay agrees with the values the strategy conditions actually evaluate.
function computeRSI(closes: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null)
  if (closes.length <= period) return result

  let avgGain = 0
  let avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1]
    avgGain += Math.max(diff, 0)
    avgLoss += Math.max(-diff, 0)
  }
  avgGain /= period
  avgLoss /= period
  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)

  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1]
    avgGain = (avgGain * (period - 1) + Math.max(diff, 0)) / period
    avgLoss = (avgLoss * (period - 1) + Math.max(-diff, 0)) / period
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  }
  return result
}

function computeATR(highs: number[], lows: number[], closes: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null)
  if (closes.length <= period) return result

  const trueRange = (i: number) =>
    Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1]))

  let atr = 0
  for (let i = 1; i <= period; i++) atr += trueRange(i)
  atr /= period
  result[period] = atr

  for (let i = period + 1; i < closes.length; i++) {
    atr = (atr * (period - 1) + trueRange(i)) / period
    result[i] = atr
  }
  return result
}

export default function ChartPanel({ bars, trades, emaLength = 20, symbol }: Props) {
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
      priceFormat: priceFormatFor(symbol),
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

    const rsiValues = computeRSI(
      bars.map((b) => b.close),
      14,
    )
    const rsiData = rsiValues
      .map((v, i) => (v === null ? null : { time: times[i], value: v }))
      .filter((v): v is { time: UTCTimestamp; value: number } => v !== null)
    if (rsiData.length > 0) {
      const rsiSeries = chart.addSeries(
        LineSeries,
        { color: '#a78bfa', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, title: 'RSI(14)' },
        1,
      )
      rsiSeries.setData(rsiData)
      rsiSeries.createPriceLine({ price: 70, color: 'rgba(239,68,68,0.4)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '70' })
      rsiSeries.createPriceLine({ price: 30, color: 'rgba(34,197,94,0.4)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '30' })
    }

    const atrValues = computeATR(
      bars.map((b) => b.high),
      bars.map((b) => b.low),
      bars.map((b) => b.close),
      14,
    )
    const atrData = atrValues
      .map((v, i) => (v === null ? null : { time: times[i], value: v }))
      .filter((v): v is { time: UTCTimestamp; value: number } => v !== null)
    if (atrData.length > 0) {
      const atrSeries = chart.addSeries(
        LineSeries,
        { color: '#38bdf8', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, title: 'ATR(14)' },
        2,
      )
      atrSeries.setData(atrData)
    }

    chart.panes().forEach((pane, i) => {
      if (i > 0) pane.setHeight(80)
    })

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
  }, [bars, trades, emaLength, symbol])

  return <div ref={containerRef} className="h-full min-h-[300px] w-full" />
}
