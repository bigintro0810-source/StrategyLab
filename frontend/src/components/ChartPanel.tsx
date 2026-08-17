import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  createSeriesMarkers,
  CrosshairMode,
  type IChartApi,
  type UTCTimestamp,
  type BarData,
  type MouseEventParams,
} from 'lightweight-charts'
import type { ChartIndicatorSeries, PatternMarkerEvent } from '../api'
import {
  buildNecklineSegments,
  buildPatternPointMarkers,
  buildPatternReferenceLines,
  PATTERN_INSTANCE_COLORS,
  patternInstanceIdPrefix,
} from '../patternMarkers'
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

// 価格軸の桁数(priceFormatFor)と同じ桁で数値を文字列にする - クリックした
// ローソクのOHLCボックスと軸の表示がずれないようにするため。
function formatPrice(value: number, symbol: string | undefined) {
  return value.toFixed(priceFormatFor(symbol).precision)
}

// toChartTimeの逆変換。toChartTimeが「文字列の数字をそのままUTCとして扱う」
// ので、戻すときもUTCのgetterで読む(閲覧者のOS設定に影響されない)。
function formatChartTime(t: UTCTimestamp): string {
  const d = new Date((t as number) * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return (
    `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
    `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
  )
}

// OHLCボックスに出すローソク1本の内容。
interface BoxBar {
  time: UTCTimestamp
  open: number
  high: number
  low: number
  close: number
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
  // カーソルが合っている足のOHLC。チャートの外に出たらnullになり、その場合は
  // 最新足を出す(TradingViewの凡例と同じ挙動)。
  const [hoveredBar, setHoveredBar] = useState<BoxBar | null>(null)
  const [showOhlcBox, setShowOhlcBox] = useState(true)
  // 十字線の移動はマウスを動かすたびに何度も飛んでくるので、足が変わった時
  // だけstateを更新して無駄な再描画を避ける。
  const hoveredTimeRef = useRef<number | null>(null)
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
  // クリックしたパターンの上値水準線・下値回帰直線(点線)を描くための
  // シリーズ - クリックのたびに前回分を消して引き直す(2026-08-19追加、
  // ユーザー要望「点をクリックしたら上値の水準線と下値の回帰直線が
  // 点線で表示されるように」)。
  const referenceLineSeriesRef = useRef<ReturnType<IChartApi['addSeries']>[]>([])

  // カーソルがチャートの外にある時に出す足(=最新足)。
  const lastBar = useMemo<BoxBar | null>(() => {
    const b = bars[bars.length - 1]
    if (!b) return null
    return {
      time: toChartTime(b.datetime),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }
  }, [bars])
  const boxBar = hoveredBar ?? lastBar

  useEffect(() => {
    if (!containerRef.current) return

    const barsChanged = prevBarsRef.current !== bars
    prevBarsRef.current = bars
    const isFirstMount = isFirstMountRef.current
    // データがまだ0本のうちは「初回マウント」を消費しない。チャートタブを
    // 開いた直後はpriceQueryが未解決でbarsが空配列なので、そこで消費して
    // しまうと、実データが届いた回には isFirstMount=false / barsChanged=true
    // となって fitContent() に落ち、遡って見ていた位置が毎回リセットされる
    // (ユーザー報告2026-08-13:「違うタブへ移動して戻ったら最新のチャートが
    // 表示されてしまう」)。実データが入った最初の回で初めて消費する。
    const hasBars = bars.length > 0
    if (hasBars) isFirstMountRef.current = false

    const chart = createChart(containerRef.current, {
      layout: { background: { color: 'transparent' }, textColor: '#d1d5db' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.06)' }, horzLines: { color: 'rgba(255,255,255,0.06)' } },
      timeScale: { timeVisible: true, secondsVisible: false },
      // 既定のMagnetモードは十字線の横線を終値に吸着させるため、価格軸には
      // 「カーソルの位置の価格」ではなく終値が出てしまう。Normalにして
      // カーソルの高さそのものの価格を価格軸(右)に表示する。
      crosshair: {
        mode: CrosshairMode.Normal,
        horzLine: { labelVisible: true, labelBackgroundColor: '#334155' },
        vertLine: { labelVisible: true, labelBackgroundColor: '#334155' },
      },
      rightPriceScale: { visible: true },
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

    // 構成点の印の組み立ては patternMarkers.ts(純粋関数・テスト済み)に
    // 任せる - ここに直接書いていた頃、想定外の形式のイベントで例外が飛び、
    // 画面全体が落ちたことがあるため。
    const patternMarkerPoints =
      showPatternMarkers && patternMarkers
        ? patternMarkers.flatMap((e, idx) =>
            buildPatternPointMarkers(
              e,
              PATTERN_INSTANCE_COLORS[idx % PATTERN_INSTANCE_COLORS.length],
              patternInstanceIdPrefix(idx),
            ).map((p) => ({
              time: toChartTime(p.time),
              position: p.position,
              color: p.color,
              shape: p.shape,
              text: p.text,
              id: p.id,
            })),
          )
        : []

    // 山/谷とネックラインの関係を一目で追えるよう、ネックラインの実際の
    // 価格水準を、ネック確定バーからパターン成立/決着バーまでの破線で
    // つなぐ(単なる印だけだと「このライン基準で判定した」がチャートから
    // 読み取りにくいため)。トリプル版はネックが2つあるので、ネック1は
    // ネック2確定バーまで、ネック2はパターン成立/決着バーまでの2本に
    // 分けて引く。
    if (showPatternMarkers && patternMarkers) {
      const drawNeckline = (start: string, end: string, price: number) => {
        const startTime = toChartTime(start)
        const endTime = toChartTime(end)
        if (endTime <= startTime) return
        const necklineSeries = chart.addSeries(LineSeries, {
          color: '#f59e0b',
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        })
        necklineSeries.setData([
          { time: startTime, value: price },
          { time: endTime, value: price },
        ])
      }
      for (const e of patternMarkers) {
        for (const seg of buildNecklineSegments(e)) {
          drawNeckline(seg.start, seg.end, seg.price)
        }
      }
    }

    const markers = [...tradeMarkers, ...pivotMarkers, ...patternMarkerPoints].sort(
      (a, b) => (a.time as number) - (b.time as number),
    )
    if (markers.length > 0) createSeriesMarkers(candleSeries, markers)

    // パターンの構成点をクリックしたら、そのパターンの上値水準線・下値
    // 回帰直線を点線で表示する(2026-08-19追加)。前回描いた分は毎回消して
    // から引き直す。
    const clearReferenceLines = () => {
      for (const s of referenceLineSeriesRef.current) {
        chart.removeSeries(s)
      }
      referenceLineSeriesRef.current = []
    }
    const addReferenceLine = (
      line: ReturnType<typeof buildPatternReferenceLines>['upper'],
      color: string,
    ) => {
      if (!line) return
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      })
      series.setData([
        { time: toChartTime(line.start.time), value: line.start.price },
        { time: toChartTime(line.end.time), value: line.end.price },
      ])
      referenceLineSeriesRef.current.push(series)
    }
    const handlePatternClick = (param: MouseEventParams) => {
      const hovered = param.hoveredInfo
      if (hovered?.objectKind !== 'series-marker' || typeof hovered.objectId !== 'string' || !patternMarkers) {
        return
      }
      const id = hovered.objectId
      clearReferenceLines()
      const e = patternMarkers.find((_, idx) => patternInstanceIdPrefix(idx) === id)
      if (!e) return
      const { upper, lower } = buildPatternReferenceLines(e)
      addReferenceLine(upper, '#f472b6')
      addReferenceLine(lower, '#60a5fa')
    }
    chart.subscribeClick(handlePatternClick)

    // ローソクをクリックしたら、その足のOHLCをボックスに出す。
    // param.seriesDataはクリックした時刻のデータを持つので、縦位置は問わず
    // 「その足の列をクリックした」で拾える。
    const handleCrosshairMove = (param: MouseEventParams) => {
      const bar =
        param.time === undefined
          ? undefined
          : (param.seriesData.get(candleSeries) as BarData | undefined)
      if (!bar || bar.open === undefined) {
        // チャートの外へ出た。呼び出し元で最新足にフォールバックする。
        if (hoveredTimeRef.current !== null) {
          hoveredTimeRef.current = null
          setHoveredBar(null)
        }
        return
      }
      const t = bar.time as UTCTimestamp
      if (hoveredTimeRef.current === (t as number)) return
      hoveredTimeRef.current = t as number
      setHoveredBar({ time: t, open: bar.open, high: bar.high, low: bar.low, close: bar.close })
    }
    chart.subscribeCrosshairMove(handleCrosshairMove)

    if (barsChanged) {
      hoveredTimeRef.current = null
      setHoveredBar(null)
    }

    let restoreRange: { from: number; to: number } | null = null
    if (isFirstMount && savedRangeRef.current) {
      // 再マウント直後の1回目 - barsChangedは常にtrueになるが無視して
      // 前回の表示範囲(initialVisibleRange)を復元する。
      restoreRange = savedRangeRef.current
    } else if (barsChanged || !savedRangeRef.current) {
      chart.timeScale().fitContent()
    } else {
      restoreRange = savedRangeRef.current
    }
    const ts = chart.timeScale()
    // setVisibleLogicalRange は「次の描画で反映する目標値」を置くだけで、
    // 呼んだ直後に getVisibleLogicalRange() で読み戻してもまだ古い値が返る
    // (実測で確認)。チャートは指標やマーカーのデータが遅れて届くたびに
    // 作り直されるため、反映前にcleanupが走って古い範囲で記憶を上書きし、
    // 次に開いたときは最新位置に戻ってしまっていた
    // (ユーザー報告2026-08-13)。反映されたかを読み戻しで確かめ、
    // まだなら「出したかった範囲」の方を覚えておく。
    const isApplied = (want: { from: number; to: number }) => {
      const got = ts.getVisibleLogicalRange()
      return !!got && Math.abs(got.from - want.from) < 0.5 && Math.abs(got.to - want.to) < 0.5
    }
    let pendingRestore: { from: number; to: number } | null = null
    if (restoreRange) {
      ts.setVisibleLogicalRange(restoreRange)
      if (!isApplied(restoreRange)) pendingRestore = restoreRange
    }

    // チャートの幅が変わると表示できる本数が変わるため、復元した表示範囲が
    // 初回のリサイズで上書きされてしまうことがある。最初のリサイズの直後に
    // 一度だけ復元し直す(2回目以降はユーザーの操作を邪魔しないよう何もしない)。
    const resizeObserver = new ResizeObserver(() => {
      if (!containerRef.current) return
      chart.applyOptions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      })
      if (pendingRestore) {
        ts.setVisibleLogicalRange(pendingRestore)
        if (isApplied(pendingRestore)) pendingRestore = null
      }
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      // chart.remove()で破棄される前に、その時点の表示範囲を保存しておく
      // (次のeffect実行がbarsChangedでなければ、これをfitContent()の
      // 代わりに復元する)。onVisibleRangeChangeで呼び出し元(App.tsx)にも
      // 伝え、このコンポーネント自体がアンマウントされても(=savedRangeRef
      // ごと消えても)復元できるようにする。
      // 空チャートの表示範囲は保存しない(上と同じ理由 - 中身の無い範囲で
      // 覚えている位置を上書きしてしまう)。
      const current = hasBars ? ts.getVisibleLogicalRange() : null
      // 復元がまだ反映されていないなら、読み戻した古い値ではなく
      // 出したかった範囲の方を残す(上のコメント参照)。
      const keep = pendingRestore && !isApplied(pendingRestore) ? pendingRestore : current
      if (keep) {
        savedRangeRef.current = keep
        onVisibleRangeChange?.(keep)
      }
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
      chart.unsubscribeClick(handlePatternClick)
      referenceLineSeriesRef.current = []
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
          <input type="checkbox" checked={showOhlcBox} onChange={(e) => setShowOhlcBox(e.target.checked)} />
          4本値ボックスを表示
        </label>
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
      <div className="relative min-h-0 w-full flex-1">
        <div ref={containerRef} className="h-full w-full" />
        {showOhlcBox && boxBar && (
          // backdrop-blur(背景ぼかし)は使わない - Canvasの上に重ねると
          // 環境によってはチャート領域全体が真っ黒になる(ユーザー報告:
          // 「ストラテジー詳細からチャートを見ると画面がブラックアウトした」)。
          // 不透明に近い単色の背景で代用する。
          <div className="pointer-events-none absolute left-2 top-2 z-10 rounded border border-white/15 bg-gray-900/95 px-2.5 py-1.5 text-xs text-gray-200">
            <div className="mb-1 flex items-baseline gap-2">
              <span className="font-medium text-gray-300">{formatChartTime(boxBar.time)}</span>
              {!hoveredBar && <span className="text-[10px] text-gray-500">最新足</span>}
            </div>
            <div className="flex items-baseline gap-3 tabular-nums">
              <span>
                <span className="mr-1 text-gray-400">始</span>
                {formatPrice(boxBar.open, symbol)}
              </span>
              <span>
                <span className="mr-1 text-gray-400">高</span>
                <span className="text-emerald-300">{formatPrice(boxBar.high, symbol)}</span>
              </span>
              <span>
                <span className="mr-1 text-gray-400">安</span>
                <span className="text-rose-300">{formatPrice(boxBar.low, symbol)}</span>
              </span>
              <span>
                <span className="mr-1 text-gray-400">終</span>
                <span className={boxBar.close >= boxBar.open ? 'text-emerald-400' : 'text-rose-400'}>
                  {formatPrice(boxBar.close, symbol)}
                </span>
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
