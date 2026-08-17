import { describe, expect, it } from 'vitest'
import type { PatternMarkerEvent } from './api'
import {
  allPatternPoints,
  buildNecklineSegments,
  buildPatternPointMarkers,
  buildPatternReferenceLines,
  patternPoint,
} from './patternMarkers'

// 実際に api_server.py の /api/pattern-markers が返した内容をそのまま貼って
// ある(USDJPY 15m)。形式が変わったらここが落ちる。

// 構成点が可変個(point1..pointN)の形式。2026-08-12にB方式で追加した
// トリプルトップ/カップ&ハンドル/H&S/エリオット推進波/フラッグ・ペナント/
// チャネル・ウェッジ・トライアングル13種はすべてこの形。
const TRIPLE_TOP: PatternMarkerEvent = {
  indicator: 'triple_top',
  kind: 'top',
  event_time: '2026-04-28T09:00:00',
  pattern_id: 'triple_top_14340_14337_14327_14322_14321_14311',
  level: 0,
  neckline_price: 159.333,
  point_count: 6,
  point1_time: '2026-04-27T23:45:00',
  point1_price: 159.106,
  point2_time: '2026-04-28T02:15:00',
  point2_price: 159.462,
  point3_time: '2026-04-28T02:30:00',
  point3_price: 159.345,
  point4_time: '2026-04-28T03:45:00',
  point4_price: 159.454,
  point5_time: '2026-04-28T06:15:00',
  point5_price: 159.333,
  point6_time: '2026-04-28T07:00:00',
  point6_price: 159.46,
} as unknown as PatternMarkerEvent

// ascending_triangle_shape(2026-08-19、判定に使った回帰直線/水準線の値を
// そのままAPIが返すようになった形式)。下値=谷谷谷が回帰直線(右肩上がり)、
// 上値=山山が水準線(水平)。reg_line_start/end_priceはあえて谷の実際の
// 価格(110.767等)とズレた値にしてあり、これがそのまま使われる(構成点
// から引き直されない)ことをテストで確認する。
const ASCENDING_TRIANGLE: PatternMarkerEvent = {
  indicator: 'ascending_triangle_shape',
  kind: 'top',
  event_time: '2018-07-11T21:45:00',
  point_count: 5,
  point1_time: '2018-07-11T10:00:00',
  point1_price: 110.767,
  point2_time: '2018-07-11T15:45:00',
  point2_price: 110.952,
  point3_time: '2018-07-11T20:00:00',
  point3_price: 110.9,
  point4_time: '2018-07-11T21:30:00',
  point4_price: 110.98,
  point5_time: '2018-07-11T21:45:00',
  point5_price: 110.973,
  reg_line_start_price: 110.7,
  reg_line_end_price: 110.99,
  flat_level_price: 110.96,
} as unknown as PatternMarkerEvent

// 旧来の形式(山2つ+ネック1つ)。
const DOUBLE_BOTTOM: PatternMarkerEvent = {
  indicator: 'double_bottom_zigzag',
  kind: 'bottom',
  event_time: '2025-10-21T10:30:00',
  pattern_id: 'double_bottom_1480_1490_1502',
  top1_time: '2025-10-20T18:00:00',
  top1_price: 150.273,
  top2_time: '2025-10-20T23:30:00',
  top2_price: 150.41,
  neckline_time: '2025-10-20T20:30:00',
  neckline_price: 150.854,
} as unknown as PatternMarkerEvent

describe('patternPoint', () => {
  it('連番の構成点を取り出せる', () => {
    expect(patternPoint(TRIPLE_TOP, 1)).toEqual({ time: '2026-04-27T23:45:00', price: 159.106 })
    expect(patternPoint(TRIPLE_TOP, 6)).toEqual({ time: '2026-04-28T07:00:00', price: 159.46 })
  })

  it('存在しない番号ではnullを返す(例外を投げない)', () => {
    expect(patternPoint(TRIPLE_TOP, 7)).toBeNull()
    expect(patternPoint(DOUBLE_BOTTOM, 1)).toBeNull()
  })
})

describe('buildPatternPointMarkers', () => {
  it('可変個の構成点をすべて番号付きで並べる', () => {
    const m = buildPatternPointMarkers(TRIPLE_TOP, '#38bdf8', 'pattern-0')
    expect(m).toHaveLength(6)
    expect(m.map((x) => x.text)).toEqual(['1', '2', '3', '4', '5', '6'])
    expect(m[0].time).toBe('2026-04-27T23:45:00')
    expect(m[5].time).toBe('2026-04-28T07:00:00')
  })

  it('高い方の構成点はローソクの上、安い方は下に印を出す', () => {
    const m = buildPatternPointMarkers(TRIPLE_TOP, '#38bdf8', 'pattern-0')
    // 159.106(谷) 159.462(山) 159.345(谷) 159.454(山) 159.333(谷) 159.46(山)
    expect(m.map((x) => x.position)).toEqual([
      'belowBar',
      'aboveBar',
      'belowBar',
      'aboveBar',
      'belowBar',
      'aboveBar',
    ])
  })

  it('渡された色とidがすべての点に反映される(近接パターンの見分け用)', () => {
    const m = buildPatternPointMarkers(TRIPLE_TOP, '#facc15', 'pattern-2')
    expect(m.every((x) => x.color === '#facc15')).toBe(true)
    expect(m.every((x) => x.id === 'pattern-2')).toBe(true)
  })

  it('旧形式(山2つ+ネック)はこれまでどおり3点', () => {
    const m = buildPatternPointMarkers(DOUBLE_BOTTOM, '#38bdf8', 'pattern-0')
    expect(m.map((x) => x.text)).toEqual(['谷1', '谷2', 'ネック'])
    // 谷側パターンなので山/谷はbelowBar、ネックはその逆
    expect(m.map((x) => x.position)).toEqual(['belowBar', 'belowBar', 'aboveBar'])
  })

  it('構成点が欠けていても例外を投げずに捨てる', () => {
    const broken = { indicator: 'x', kind: 'top', event_time: '2026-01-01T00:00:00' } as unknown as PatternMarkerEvent
    expect(() => buildPatternPointMarkers(broken, '#38bdf8', 'pattern-0')).not.toThrow()
    expect(buildPatternPointMarkers(broken, '#38bdf8', 'pattern-0')).toEqual([])

    // point_countだけあって中身が無い場合も落ちない
    const emptyPoints = { ...broken, point_count: 5 } as unknown as PatternMarkerEvent
    expect(buildPatternPointMarkers(emptyPoints, '#38bdf8', 'pattern-0')).toEqual([])
  })
})

describe('allPatternPoints', () => {
  it('可変個の形式は構成点をそのまま時系列順に返す', () => {
    const pts = allPatternPoints(TRIPLE_TOP)
    expect(pts).toHaveLength(6)
    expect(pts[0]).toEqual({ time: '2026-04-27T23:45:00', price: 159.106 })
    expect(pts[5]).toEqual({ time: '2026-04-28T07:00:00', price: 159.46 })
  })

  it('旧形式(山2つ+ネック)は山1・ネック・山2の順で返す', () => {
    expect(allPatternPoints(DOUBLE_BOTTOM)).toEqual([
      { time: '2025-10-20T18:00:00', price: 150.273 },
      { time: '2025-10-20T20:30:00', price: 150.854 },
      { time: '2025-10-20T23:30:00', price: 150.41 },
    ])
  })

  it('構成点が欠けていても例外を投げずに空配列を返す', () => {
    const broken = { indicator: 'x', kind: 'top', event_time: '2026-01-01T00:00:00' } as unknown as PatternMarkerEvent
    expect(() => allPatternPoints(broken)).not.toThrow()
    expect(allPatternPoints(broken)).toEqual([])
  })
})

describe('buildPatternReferenceLines', () => {
  it('上側(山)・下側(谷)それぞれに回帰直線を引ける', () => {
    const { upper, lower } = buildPatternReferenceLines(TRIPLE_TOP)
    // 上側=山2つ(159.462, 159.454, 159.46)、下側=谷3つ(159.106, 159.345, 159.333)
    expect(upper).not.toBeNull()
    expect(lower).not.toBeNull()
    expect(upper?.start.time).toBe('2026-04-28T02:15:00')
    expect(upper?.end.time).toBe('2026-04-28T07:00:00')
    expect(lower?.start.time).toBe('2026-04-27T23:45:00')
    expect(lower?.end.time).toBe('2026-04-28T06:15:00')
  })

  it('片側が1点しかない場合はその側はnull(線が引けない)', () => {
    const { upper, lower } = buildPatternReferenceLines(DOUBLE_BOTTOM)
    // 谷2点(下側)・ネック1点(上側)
    expect(lower).not.toBeNull()
    expect(upper).toBeNull()
  })

  it('ascending_triangle_shapeは構成点から引き直さず、APIが返した判定基準の直線をそのまま使う(2026-08-19)', () => {
    const { upper, lower } = buildPatternReferenceLines(ASCENDING_TRIANGLE)
    // 下値=回帰直線(reg_line_start/end_price、構成点の谷の実際の価格とは
    // あえてズラしてある) - 最小二乗で引き直していたらこの値にはならない。
    expect(lower).toEqual({
      start: { time: '2018-07-11T10:00:00', price: 110.7 },
      end: { time: '2018-07-11T21:45:00', price: 110.99 },
    })
    // 上値=水準線(flat_level_price、水平)。
    expect(upper).toEqual({
      start: { time: '2018-07-11T10:00:00', price: 110.96 },
      end: { time: '2018-07-11T21:45:00', price: 110.96 },
    })
  })

  it('構成点が欠けていても例外を投げずnullを返す', () => {
    const broken = { indicator: 'x', kind: 'top', event_time: '2026-01-01T00:00:00' } as unknown as PatternMarkerEvent
    expect(() => buildPatternReferenceLines(broken)).not.toThrow()
    expect(buildPatternReferenceLines(broken)).toEqual({ upper: null, lower: null })
  })

  it('直線の終点は最後の構成点ではなくevent_time(実際にブレイクが成立したバー)まで延ばす(2026-08-19)', () => {
    // 実際のブレイクは最後の構成点(点5)より後のバーで起きることが多い。
    // 終点が点5のままだと、チャート上で線がブレイクの手前で途切れて
    // 見えてしまう(ユーザー報告「上値抵抗線を上抜けてないのにロング
    // している」- 実際には抜けていたが、線が短くて見えなかっただけ)。
    const laterBreak: PatternMarkerEvent = {
      ...ASCENDING_TRIANGLE,
      event_time: '2018-07-12T03:00:00',
    }
    const { upper, lower } = buildPatternReferenceLines(laterBreak)
    expect(upper?.end.time).toBe('2018-07-12T03:00:00')
    expect(lower?.end.time).toBe('2018-07-12T03:00:00')
    // 始点は変わらず点1のまま。
    expect(upper?.start.time).toBe('2018-07-11T10:00:00')
    expect(lower?.start.time).toBe('2018-07-11T10:00:00')
  })
})

describe('buildNecklineSegments', () => {
  it('可変個の形式は最初の構成点から成立バーまで1本', () => {
    expect(buildNecklineSegments(TRIPLE_TOP)).toEqual([
      { start: '2026-04-27T23:45:00', end: '2026-04-28T09:00:00', price: 159.333 },
    ])
  })

  it('旧形式はネック確定バーから成立バーまで1本', () => {
    expect(buildNecklineSegments(DOUBLE_BOTTOM)).toEqual([
      { start: '2025-10-20T20:30:00', end: '2025-10-21T10:30:00', price: 150.854 },
    ])
  })

  it('必要な値が欠けていても例外を投げずに捨てる', () => {
    const broken = { indicator: 'x', kind: 'top', event_time: '2026-01-01T00:00:00' } as unknown as PatternMarkerEvent
    expect(() => buildNecklineSegments(broken)).not.toThrow()
    expect(buildNecklineSegments(broken)).toEqual([])
  })
})
