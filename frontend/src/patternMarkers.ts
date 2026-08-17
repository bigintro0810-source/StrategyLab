import type { PatternMarkerEvent } from './api'

// api_server.py::_compute_pattern_markers が返すチャートパターンの根拠点を、
// チャートに描く形へ組み立てる純粋関数群。
//
// 元はChartPanel.tsxのuseEffectの中に直接書いてあったが、2026-08-12に
// トリプルトップ等の「構成点が可変個(point1..pointN)」のパターンを追加した
// 際、旧形式(top1/top2/neckline)しか読んでいない分岐が undefined を日時
// 変換して例外を投げ、チャートどころか画面全体が落ちた(ユーザー報告:
// 「トリプルトップだとブラックアウトする」)。同じ事故を繰り返さないよう、
// 落ちうる部分だけをここへ切り出してテストで固定してある
// (tests: patternMarkers.test.ts)。

export interface PatternPoint {
  time: string
  price: number
}

export interface PatternPointMarker {
  time: string
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'circle'
  text: string
  id: string
}

export interface NecklineSegment {
  start: string
  end: string
  price: number
}

// 近接する複数のパターンを見分けられるよう、インスタンス単位で3色を
// 循環させる(2026-08-19、ユーザー報告「近接してるパターンがあると
// どちらのパターンの点かわからなくなる」対応)。以前は山/ネックという
// 役割で色分けしていた(EXTREME_COLOR/NECK_COLOR)が、役割は位置(上/下)と
// テキストラベルで既に判別できるため、色はインスタンス識別に使う。
export const PATTERN_INSTANCE_COLORS = ['#38bdf8', '#facc15', '#c084fc']

// パターンマーカーのid接頭辞からインスタンスの配列indexを復元する
// (ChartPanel.tsxのクリックハンドラ用)。
export function patternInstanceIdPrefix(idx: number): string {
  return `pattern-${idx}`
}

// 可変個の構成点(point1_time / point1_price …)を1つ取り出す。
// 片方でも欠けていたらnullを返す - 欠けた値をそのまま日時変換すると例外に
// なるため、ここで必ず止める。
export function patternPoint(e: PatternMarkerEvent, i: number): PatternPoint | null {
  const rec = e as unknown as Record<string, unknown>
  const time = rec[`point${i}_time`]
  const price = rec[`point${i}_price`]
  if (typeof time !== 'string' || typeof price !== 'number') return null
  return { time, price }
}

// point_count を持つ形式かどうか(2026-08-12以降にB方式で追加したパターン)。
export function hasVariablePoints(e: PatternMarkerEvent): boolean {
  return typeof e.point_count === 'number' && e.point_count > 0
}

// このイベントの構成点を、形式(可変point1..pointN / 旧固定top1-top2-neckline
// / 旧固定トリプル)によらず時系列順の配列として取り出す。想定外の形式・
// 欠けた値があれば空配列を返す(1件の不整合でチャート全体を落とさない
// ため、buildPatternPointMarkersと同じ方針)。
export function allPatternPoints(e: PatternMarkerEvent): PatternPoint[] {
  if (hasVariablePoints(e)) {
    const pts: PatternPoint[] = []
    for (let i = 1; i <= (e.point_count as number); i++) {
      const p = patternPoint(e, i)
      if (p) pts.push(p)
    }
    return pts
  }

  if (e.top3_time !== undefined && e.neck1_time !== undefined && e.neck2_time !== undefined) {
    if (
      e.top1_time === undefined ||
      e.top2_time === undefined ||
      e.neck1_price === undefined ||
      e.neck2_price === undefined
    ) {
      return []
    }
    return [
      { time: e.top1_time, price: e.top1_price },
      { time: e.neck1_time, price: e.neck1_price },
      { time: e.top2_time, price: e.top2_price },
      { time: e.neck2_time, price: e.neck2_price },
      { time: e.top3_time, price: e.top3_price as number },
    ]
  }

  if (e.top1_time === undefined || e.top2_time === undefined || e.neckline_time === undefined) {
    return []
  }
  if (e.neckline_price === undefined) return []
  return [
    { time: e.top1_time, price: e.top1_price },
    { time: e.neckline_time, price: e.neckline_price },
    { time: e.top2_time, price: e.top2_price },
  ]
}

// 構成点の印(山/谷の丸)を組み立てる。想定外の形式なら空配列を返す
// (握りつぶす - 1件の不整合でチャート全体を落とさないため)。
export function buildPatternPointMarkers(e: PatternMarkerEvent, color: string, id: string): PatternPointMarker[] {
  if (hasVariablePoints(e)) {
    const pts: PatternPoint[] = []
    for (let i = 1; i <= (e.point_count as number); i++) {
      const p = patternPoint(e, i)
      if (p) pts.push(p)
    }
    return pts.map((p, idx) => {
      // 構成点は高値・安値が交互に並ぶので、隣より高ければローソクの上、
      // 低ければ下に印を出す。隣が無い(1点しかない)場合だけkindで決める。
      const ref = pts[idx - 1] ?? pts[idx + 1]
      const isHigh = ref ? p.price >= ref.price : e.kind === 'top'
      return {
        time: p.time,
        position: isHigh ? 'aboveBar' : 'belowBar',
        color,
        shape: 'circle',
        text: String(idx + 1),
        id,
      }
    })
  }

  const extremePos = e.kind === 'top' ? 'aboveBar' : 'belowBar'
  const neckPos = e.kind === 'top' ? 'belowBar' : 'aboveBar'
  const extremeLabel = (n: number) => (e.kind === 'top' ? `山${n}` : `谷${n}`)

  // triple_top_shape/triple_bottom_shapeは山/谷が3つ・ネックが2つ(2026-08-01)。
  if (e.top3_time !== undefined && e.neck1_time !== undefined && e.neck2_time !== undefined) {
    if (e.top1_time === undefined || e.top2_time === undefined) return []
    return [
      { time: e.top1_time, position: extremePos, color, shape: 'circle', text: extremeLabel(1), id },
      { time: e.neck1_time, position: neckPos, color, shape: 'circle', text: 'ネック1', id },
      { time: e.top2_time, position: extremePos, color, shape: 'circle', text: extremeLabel(2), id },
      { time: e.neck2_time, position: neckPos, color, shape: 'circle', text: 'ネック2', id },
      { time: e.top3_time, position: extremePos, color, shape: 'circle', text: extremeLabel(3), id },
    ]
  }

  if (e.top1_time === undefined || e.top2_time === undefined || e.neckline_time === undefined) {
    return []
  }
  return [
    { time: e.top1_time, position: extremePos, color, shape: 'circle', text: extremeLabel(1), id },
    { time: e.top2_time, position: extremePos, color, shape: 'circle', text: extremeLabel(2), id },
    // ネックライン(2つの山/谷の間の谷/山) - 山側パターンなら谷なので
    // belowBar、谷側パターンなら山なのでaboveBar(山/谷マーカーとは逆側)。
    { time: e.neckline_time, position: neckPos, color, shape: 'circle', text: 'ネック', id },
  ]
}

export interface PatternReferenceLine {
  start: PatternPoint
  end: PatternPoint
}

function epochMs(time: string): number {
  return new Date(time.endsWith('Z') ? time : `${time}Z`).getTime()
}

// 点群を最小二乗法で1本の直線に当てはめ、その群の最初/最後の時刻での
// 直線上の値を2端点として返す(水平に近い群なら水平線、斜めの群なら
// 回帰直線になる - 側の種類ごとに特別扱いせず同じ式で済む)。
function fitReferenceLine(pts: PatternPoint[]): PatternReferenceLine | null {
  if (pts.length < 2) return null
  const xs = pts.map((p) => epochMs(p.time))
  const ys = pts.map((p) => p.price)
  const n = xs.length
  const sumX = xs.reduce((a, b) => a + b, 0)
  const sumY = ys.reduce((a, b) => a + b, 0)
  const sumXY = xs.reduce((a, x, i) => a + x * ys[i], 0)
  const sumXX = xs.reduce((a, x) => a + x * x, 0)
  const denom = n * sumXX - sumX * sumX
  let minIdx = 0
  let maxIdx = 0
  xs.forEach((x, i) => {
    if (x < xs[minIdx]) minIdx = i
    if (x > xs[maxIdx]) maxIdx = i
  })
  if (denom === 0) {
    const avg = sumY / n
    return { start: { time: pts[minIdx].time, price: avg }, end: { time: pts[maxIdx].time, price: avg } }
  }
  const slope = (n * sumXY - sumX * sumY) / denom
  const intercept = (sumY - slope * sumX) / n
  return {
    start: { time: pts[minIdx].time, price: slope * xs[minIdx] + intercept },
    end: { time: pts[maxIdx].time, price: slope * xs[maxIdx] + intercept },
  }
}

// クリックされた点が属するパターンの、上側構成点を通る水準線(または
// 回帰直線)と、下側構成点を通る回帰直線(または水準線)を組み立てる
// (2026-08-19追加)。上/下どちらが水平でどちらが斜めかはパターンごとに
// 違う(ボックスは両方水平、三角保ち合いは片方だけ斜め等)ため、
// 側を特別扱いせず同じ最小二乗フィットを両方に使う - 実際に水平な側は
// 結果的にほぼ水平の直線になる。
export function buildPatternReferenceLines(e: PatternMarkerEvent): {
  upper: PatternReferenceLine | null
  lower: PatternReferenceLine | null
} {
  const pts = allPatternPoints(e)
  if (pts.length < 2) return { upper: null, lower: null }

  // ascending/descending_triangle_shapeは、判定に実際使った回帰直線
  // (起点+2点だけで決まる)と水準線の値をAPIがそのまま返す(2026-08-19)。
  // 構成点全体から最小二乗で線を引き直すと判定基準の直線とズレて別の
  // 線になってしまう(ユーザー報告「下値支持線が許容誤差から外れて
  // 見える」)ため、この2種はそちらを優先して使う。
  if (
    (e.indicator === 'ascending_triangle_shape' || e.indicator === 'descending_triangle_shape') &&
    typeof e.reg_line_start_price === 'number' &&
    typeof e.reg_line_end_price === 'number' &&
    typeof e.flat_level_price === 'number'
  ) {
    const first = pts[0]
    // 終点はAPI側で構成点の最後のバーではなくevent_time(実際にブレイクが
    // 成立したバー)まで延ばした値になっている(2026-08-19)。ここもそれに
    // 合わせてevent_timeを使う - 構成点の最後のバーの時刻のままだと、
    // 実際のブレイクより手前で線が途切れて見えてしまう
    // (ユーザー報告「上値抵抗線を上抜けてないのにロングしている」)。
    const end = e.event_time
    const regLine: PatternReferenceLine = {
      start: { time: first.time, price: e.reg_line_start_price },
      end: { time: end, price: e.reg_line_end_price },
    }
    const flatLine: PatternReferenceLine = {
      start: { time: first.time, price: e.flat_level_price },
      end: { time: end, price: e.flat_level_price },
    }
    // 上昇三角保ち合い: 下値(回帰・右肩上がり)/上値(水準・水平)。
    // 下降三角保ち合い: 上値(回帰・右肩下がり)/下値(水準・水平)。
    return e.indicator === 'ascending_triangle_shape'
      ? { upper: flatLine, lower: regLine }
      : { upper: regLine, lower: flatLine }
  }

  // rising_wedge_shape/rising_wedge_shape_x(上値抵抗線も下値支持線と同じ
  // 回帰直線方式で水準線が無い家系)は、両方ともAPIが返した直線の値を
  // そのまま使う(2026-08-19。rising_wedge_shape_xはrising_wedge_shapeを
  // 複製した別家系で、構成点の形式は同一)。
  if (
    (e.indicator === 'rising_wedge_shape' || e.indicator === 'rising_wedge_shape_x') &&
    typeof e.lower_line_start_price === 'number' &&
    typeof e.lower_line_end_price === 'number' &&
    typeof e.upper_line_start_price === 'number' &&
    typeof e.upper_line_end_price === 'number'
  ) {
    const first = pts[0]
    // 終点はevent_time(実際にブレイクが成立したバー)まで延ばす。
    // 上の三角保ち合いの分岐と同じ理由。
    const end = e.event_time
    return {
      lower: {
        start: { time: first.time, price: e.lower_line_start_price },
        end: { time: end, price: e.lower_line_end_price },
      },
      upper: {
        start: { time: first.time, price: e.upper_line_start_price },
        end: { time: end, price: e.upper_line_end_price },
      },
    }
  }

  const upperPts: PatternPoint[] = []
  const lowerPts: PatternPoint[] = []
  pts.forEach((p, idx) => {
    const ref = pts[idx - 1] ?? pts[idx + 1]
    const isHigh = ref ? p.price >= ref.price : e.kind === 'top'
    ;(isHigh ? upperPts : lowerPts).push(p)
  })
  return {
    upper: fitReferenceLine(upperPts),
    lower: fitReferenceLine(lowerPts),
  }
}

// 「このライン基準で判定した」がチャートから読み取れるよう、ネックラインの
// 価格水準を破線でつなぐ区間を返す。トリプル(旧形式)はネックが2つあるので
// 2区間になる。
export function buildNecklineSegments(e: PatternMarkerEvent): NecklineSegment[] {
  if (hasVariablePoints(e)) {
    const first = patternPoint(e, 1)
    if (!first || typeof e.neckline_price !== 'number') return []
    return [{ start: first.time, end: e.event_time, price: e.neckline_price }]
  }

  if (e.top3_time !== undefined && e.neck1_time !== undefined && e.neck2_time !== undefined) {
    if (e.neck1_price === undefined || e.neck2_price === undefined) return []
    return [
      { start: e.neck1_time, end: e.neck2_time, price: e.neck1_price },
      { start: e.neck2_time, end: e.event_time, price: e.neck2_price },
    ]
  }

  if (e.neckline_time === undefined || e.neckline_price === undefined) return []
  return [{ start: e.neckline_time, end: e.event_time, price: e.neckline_price }]
}
