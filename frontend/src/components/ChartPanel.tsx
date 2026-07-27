import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  createSeriesMarkers,
  type IChartApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { ChartIndicatorSeries, PatternMarkerEvent } from '../api'
import { indicatorLabel, paramsLabel } from '../conditionTreeUtils'
import type { IndicatorInfo, PriceBar, TradeRow } from '../types'

interface Props {
  bars: PriceBar[]
  trades: TradeRow[]
  emaLength?: number
  symbol?: string
  // データタブでストラテジーを選んだ時だけ渡す - 指定されている間は手動EMA/
  // RSI/ATRの代わりに、そのストラテジーが実際に参照しているindicatorを描画
  // する(indicatorInfosはラベルの日本語化用、/api/indicatorsの結果)。
  indicators?: ChartIndicatorSeries[]
  indicatorInfos?: IndicatorInfo[]
  // trade.direction(双方向バックテストのみ持つ)が無い時のフォールバック -
  // 単方向ストラテジーは全トレードがこの向きで固定。
  defaultDirection?: 'long' | 'short'
  // ダブルトップ/ボトム系の条件が実際に成立/決着した回の根拠(2つの山/谷)。
  // api_server.py::_compute_pattern_markers参照。
  patternMarkers?: PatternMarkerEvent[]
  // 表示中の範囲(スクロール/ズーム位置)を呼び出し元(App.tsx)がrank/id単位で
  // 保持する - このコンポーネント自身のsavedRangeRefだけだと、タブを離れて
  // 戻った時にコンポーネント自体がアンマウントされ、遡って見ていた位置が
  // 最新足にリセットされてしまう(ユーザー報告:「チャート過去に遡ったまま
  // タブ離れたら最新のチャートに戻っちゃう」- activeTab/onTabChangeと同じ
  // 理由)。
  initialVisibleRange?: { from: number; to: number } | null
  onVisibleRangeChange?: (range: { from: number; to: number }) => void
}

const OVERLAY_COLORS = ['#f59e0b', '#22d3ee', '#e879f9', '#a3e635', '#fb7185', '#38bdf8', '#facc15', '#818cf8']

// api_server.pyの/api/price-data等はタイムゾーン情報なしの文字列
// ("2026-05-01T09:30:00.000")を返すが、中身は実際には日本時間(JST)の
// 壁時計時刻(import_broker_csv.pyがTARGET_TZ="Asia/Tokyo"に変換済み)。
// これを素の new Date(str) でパースするとブラウザのローカルタイムゾーンで
// 解釈されるが、lightweight-chartsは受け取ったUTCTimestampを常にUTC基準で
// 軸に描画する(ライブラリの既知の仕様)ため、日本時間の環境でもJST→UTCの
// 9時間分ズレて表示されてしまう(実際に確認・修正した不具合)。文字列の
// 数字をそのままUTCの数字として扱うことで、閲覧者のOS設定に関係なく常に
// 元の(=JSTの)数字通りに表示させる。
function toChartTime(dateStr: string): UTCTimestamp {
  const withZ = dateStr.endsWith('Z') ? dateStr : `${dateStr}Z`
  return Math.floor(new Date(withZ).getTime() / 1000) as UTCTimestamp
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

type PivotPoint = { time: UTCTimestamp; kind: 'high' | 'low' }

// デバッグ用: 山(高値)/谷(安値)のピボット判定を実チャート上で目視確認できる
// ようにする(エンジン側のengine/chart_patterns.py::_detect_pivot_highs/lows
// と同じ「前後leftBars/rightBars本の中で最大/最小」というロジックのJS版)。
// ダブルトップ等の検出品質を左右するleft/rightを実際に動かしながら確認する
// ための機能で、パターン検出自体の判定には使われない(表示専用)。
function detectPivots(bars: PriceBar[], left: number, right: number, times: UTCTimestamp[]): PivotPoint[] {
  const points: PivotPoint[] = []
  if (left < 1 || right < 1) return points
  for (let i = left; i < bars.length - right; i++) {
    const window = bars.slice(i - left, i + right + 1)
    const windowHigh = Math.max(...window.map((b) => b.high))
    const windowLow = Math.min(...window.map((b) => b.low))
    if (bars[i].high === windowHigh) points.push({ time: times[i], kind: 'high' })
    if (bars[i].low === windowLow) points.push({ time: times[i], kind: 'low' })
  }
  return points
}

export default function ChartPanel({
  bars,
  trades,
  emaLength = 20,
  symbol,
  indicators,
  indicatorInfos,
  defaultDirection,
  patternMarkers,
  initialVisibleRange,
  onVisibleRangeChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [showPivots, setShowPivots] = useState(false)
  const [pivotLeft, setPivotLeft] = useState(25)
  const [pivotRight, setPivotRight] = useState(25)
  const [showPatternMarkers, setShowPatternMarkers] = useState(true)
  // ピボット表示等のチェックボックスを切り替えるだけでもこのeffect全体が
  // 再実行され、チャートを作り直す(=fitContent()で最新足まで表示し直す)
  // ため、ユーザーが見ていたスクロール/ズーム位置が毎回失われていた
  // (ユーザー報告:「デバック用にチェックつけてたらチャートがいま見ている
  // 位置から一番新しいところに戻ってしまう」)。barsそのものが変わった
  // (=別のストラテジー/銘柄に切り替えた)時だけfitContent()し、表示
  // トグルだけの再実行では直前の表示範囲を保ったままにする。
  const prevBarsRef = useRef<PriceBar[] | null>(null)
  // 初期値はinitialVisibleRange(呼び出し元がrank/id単位で覚えている前回の
  // 表示範囲) - このコンポーネント自体が再マウントされた直後の最初の
  // effect実行では、prevBarsRef.currentがnullなのでbarsChangedが常にtrue
  // になり(=別データに切り替わった時と区別が付かない)、それだけで
  // fitContent()に落ちてしまう。isFirstMountRefで「再マウント直後の1回目」
  // だけ特別扱いし、initialVisibleRangeがあればbarsChangedを無視して復元
  // する。
  const savedRangeRef = useRef<{ from: number; to: number } | null>(initialVisibleRange ?? null)
  const isFirstMountRef = useRef(true)

  useEffect(() => {
    if (!containerRef.current) return

    const barsChanged = prevBarsRef.current !== bars
    prevBarsRef.current = bars
    const isFirstMount = isFirstMountRef.current
    isFirstMountRef.current = false

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

    const times = bars.map((b) => toChartTime(b.datetime))
    const data = bars.map((b, i) => ({
      time: times[i],
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }))
    candleSeries.setData(data)

    // データタブでストラテジーを選んでいる間は、そのストラテジーが実際に
    // 参照しているindicator(api_server.pyのget_strategy_chart_indicators)
    // を描画する - 手動EMA/固定RSI(14)/ATR(14)は表示しない(何を見ているか
    // 混乱するため)。選んでいなければ従来通りの手動EMA+RSI+ATRのまま。
    if (indicators && indicators.length > 0) {
      let oscillatorPaneIndex = 1
      let colorIdx = 0
      for (const series of indicators) {
        const data = series.values
          .map((v) =>
            v.value === null ? null : { time: toChartTime(v.time), value: v.value },
          )
          .filter((v): v is { time: UTCTimestamp; value: number } => v !== null)
        if (data.length === 0) continue
        const label = indicatorInfos
          ? `${indicatorLabel(indicatorInfos, series.indicator)}${paramsLabel(indicatorInfos, series.indicator, series.params)}`
          : series.indicator
        const color = OVERLAY_COLORS[colorIdx % OVERLAY_COLORS.length]
        colorIdx++
        const lineSeries = chart.addSeries(
          LineSeries,
          { color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, title: label },
          series.scale === 'price' ? 0 : oscillatorPaneIndex,
        )
        lineSeries.setData(data)
        if (series.scale === 'oscillator') oscillatorPaneIndex++
      }
    } else {
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
    }

    chart.panes().forEach((pane, i) => {
      if (i > 0) pane.setHeight(80)
    })

    const priceDecimals = priceFormatFor(symbol).precision
    const tradeMarkers = trades.flatMap((t) => {
      // ロング: エントリーはローソク足の下に上向き矢印(買い)、決済は上に
      // 下向き矢印(売り)。ショートはその逆。矢印の下(belowBar)/上
      // (aboveBar)にはそれぞれの価格を表示する - 損益ではなく実際の
      // 約定価格の方が、チャート上の実際の値動きと直接見比べられる。
      const direction = (t.direction as 'long' | 'short' | undefined) ?? defaultDirection ?? 'long'
      const isLong = direction === 'long'
      return [
        {
          time: toChartTime(t.entry_time),
          position: (isLong ? 'belowBar' : 'aboveBar') as const,
          color: '#3b82f6',
          shape: (isLong ? 'arrowUp' : 'arrowDown') as const,
          // lightweight-charts(SeriesMarkersRenderer.drawText)はマーカーの
          // textを1本のfillText呼び出しで描画するだけで、\nを改行として
          // 解釈する処理が無い(コード確認済み) - 埋め込んでも改行され
          // ないため、スペース区切りの1行で我慢する。
          text: `${Number(t.entry_price).toFixed(priceDecimals)} Entry`,
        },
        {
          time: toChartTime(t.exit_time),
          position: (isLong ? 'aboveBar' : 'belowBar') as const,
          color: t.profit >= 0 ? '#22c55e' : '#ef4444',
          shape: (isLong ? 'arrowDown' : 'arrowUp') as const,
          text: `${Number(t.exit_price).toFixed(priceDecimals)} Exit`,
        },
      ]
    })

    const pivotMarkers = showPivots
      ? detectPivots(bars, pivotLeft, pivotRight, times).map((p) => ({
          time: p.time,
          position: (p.kind === 'high' ? 'aboveBar' : 'belowBar') as const,
          color: '#ff17d1',
          shape: 'circle' as const,
          text: p.kind === 'high' ? '山' : '谷',
        }))
      : []

    const patternMarkerPoints =
      showPatternMarkers && patternMarkers
        ? patternMarkers.flatMap((e) => [
            {
              time: toChartTime(e.top1_time),
              position: (e.kind === 'top' ? 'aboveBar' : 'belowBar') as const,
              color: '#ff17d1',
              shape: 'circle' as const,
              text: e.kind === 'top' ? '山1' : '谷1',
            },
            {
              time: toChartTime(e.top2_time),
              position: (e.kind === 'top' ? 'aboveBar' : 'belowBar') as const,
              color: '#ff17d1',
              shape: 'circle' as const,
              text: e.kind === 'top' ? '山2' : '谷2',
            },
            // ネックライン(2つの山/谷の間の谷/山) - 山側パターンなら谷なので
            // belowBar、谷側パターンなら山なのでaboveBar(山/谷マーカーとは
            // 逆側)。ユーザー指摘:「ネックラインは谷がないとわからない
            // よね?谷も条件に必要でしょ」への対応。
            {
              time: toChartTime(e.neckline_time),
              position: (e.kind === 'top' ? 'belowBar' : 'aboveBar') as const,
              color: '#f59e0b',
              shape: 'circle' as const,
              text: 'ネック',
            },
          ])
        : []

    // 2つの山/谷とネックラインの関係を一目で追えるよう、ネックラインの
    // 実際の価格水準を、ネック確定バーからパターン成立/決着バーまでの
    // 破線でつなぐ(単なる印だけだと「このライン基準で判定した」がチャート
    // から読み取りにくいため)。
    if (showPatternMarkers && patternMarkers) {
      for (const e of patternMarkers) {
        const neckTime = toChartTime(e.neckline_time)
        const endTime = toChartTime(e.event_time)
        if (endTime <= neckTime) continue
        const necklineSeries = chart.addSeries(LineSeries, {
          color: '#f59e0b',
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        })
        necklineSeries.setData([
          { time: neckTime, value: e.neckline_price },
          { time: endTime, value: e.neckline_price },
        ])
      }
    }

    const markers = [...tradeMarkers, ...pivotMarkers, ...patternMarkerPoints].sort(
      (a, b) => (a.time as number) - (b.time as number),
    )
    if (markers.length > 0) createSeriesMarkers(candleSeries, markers)

    if (isFirstMount && savedRangeRef.current) {
      // 再マウント直後の1回目 - barsChangedは常にtrueになるが無視して
      // 前回の表示範囲(initialVisibleRange)を復元する。
      chart.timeScale().setVisibleLogicalRange(savedRangeRef.current)
    } else if (barsChanged || !savedRangeRef.current) {
      chart.timeScale().fitContent()
    } else {
      chart.timeScale().setVisibleLogicalRange(savedRangeRef.current)
    }

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
      // chart.remove()で破棄される前に、その時点の表示範囲を保存しておく
      // (次のeffect実行がbarsChangedでなければ、これをfitContent()の
      // 代わりに復元する)。onVisibleRangeChangeで呼び出し元(App.tsx)にも
      // 伝え、このコンポーネント自体がアンマウントされても(=savedRangeRef
      // ごと消えても)復元できるようにする。
      const range = chart.timeScale().getVisibleLogicalRange()
      if (range) {
        savedRangeRef.current = range
        onVisibleRangeChange?.(range)
      }
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [
    bars,
    trades,
    emaLength,
    symbol,
    indicators,
    indicatorInfos,
    defaultDirection,
    showPivots,
    pivotLeft,
    pivotRight,
    showPatternMarkers,
    patternMarkers,
  ])

  return (
    <div className="flex h-full min-h-[300px] w-full flex-col">
      <div className="mb-1 flex flex-none flex-wrap items-center gap-2 text-xs text-gray-400">
        {patternMarkers && patternMarkers.length > 0 && (
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={showPatternMarkers}
              onChange={(e) => setShowPatternMarkers(e.target.checked)}
            />
            エントリーに使用した山/谷のみ表示
          </label>
        )}
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={showPivots} onChange={(e) => setShowPivots(e.target.checked)} />
          山/谷ピボット全表示(デバッグ用)
        </label>
        {showPivots && (
          <>
            <label className="flex items-center gap-1">
              左
              <input
                type="number"
                min={1}
                value={pivotLeft}
                onChange={(e) => setPivotLeft(Math.max(1, Number(e.target.value) || 1))}
                className="w-12 rounded border border-white/10 bg-black/30 px-1 py-0.5 text-gray-200"
              />
              本
            </label>
            <label className="flex items-center gap-1">
              右
              <input
                type="number"
                min={1}
                value={pivotRight}
                onChange={(e) => setPivotRight(Math.max(1, Number(e.target.value) || 1))}
                className="w-12 rounded border border-white/10 bg-black/30 px-1 py-0.5 text-gray-200"
              />
              本
            </label>
          </>
        )}
      </div>
      <div ref={containerRef} className="min-h-0 w-full flex-1" />
    </div>
  )
}
