import type { IndicatorInfo } from './types'

// ConditionRow.tsxの指標ピッカーをoptgroupでジャンル分けするための分類 -
// ユーザー作成のExcel「Strategy Lab 条件一覧.xlsx」と同じ7ジャンル
// (ユーザー要望:「このジャンル分けをStrategy Labの条件設定のところでも
// してほしい」)。api_server.pyが返すcategory("indicator"/"price_action"/
// "chart_pattern"/"ict"/"time_filter")のうち、"price_action"だけは範囲が
// 広すぎるため、id単位でさらに3つ(価格データ/ローソク足パターン/
// プライスアクション)に分ける - Excel作成時に使った分類と全く同じ内訳。

// 価格データ: 始値・高値・安値・終値・前日高値など、単発の生の価格参照/派生する数値
const PRICE_DATA_IDS = new Set([
  'close', 'open', 'high', 'low',
  'prev_day_high', 'prev_day_low', 'prev_day_mid',
  'candle_body',
  'avg_body_size', 'avg_lower_wick', 'avg_upper_wick',
  'body_size_std', 'max_body_size', 'min_body_size',
  'dist_to_round_number',
])

// プライスアクション: ブレイクアウト・初押し・レンジ・高値更新など「価格がどう動いたか」
const PRICE_ACTION_BEHAVIOR_IDS = new Set([
  'consecutive_higher_highs', 'consecutive_lower_lows',
  'first_pullback_after_breakout_bearish', 'first_pullback_after_breakout_bullish',
  'higher_high', 'higher_low', 'lower_high', 'lower_low',
  'today_new_high', 'today_new_low',
  'today_range_pct_of_adr', 'today_range_position',
])
// 残り(price_actionカテゴリのうち上記2つに該当しないもの)は「ローソク足パターン」

export type ConditionGenreKey =
  | 'indicator'
  | 'price_data'
  | 'candlestick_pattern'
  | 'price_action_behavior'
  | 'chart_pattern'
  | 'ict'
  | 'time_filter'

export const CONDITION_GENRE_ORDER: { key: ConditionGenreKey; label: string }[] = [
  { key: 'indicator', label: 'インジケーター' },
  { key: 'price_data', label: '価格データ' },
  { key: 'candlestick_pattern', label: 'ローソク足パターン' },
  { key: 'price_action_behavior', label: 'プライスアクション' },
  { key: 'chart_pattern', label: 'チャートパターン' },
  { key: 'ict', label: 'ICT' },
  { key: 'time_filter', label: '時間フィルター' },
]

export function conditionGenreOf(indicator: IndicatorInfo): ConditionGenreKey {
  if (indicator.category === 'price_action') {
    if (PRICE_DATA_IDS.has(indicator.id)) return 'price_data'
    if (PRICE_ACTION_BEHAVIOR_IDS.has(indicator.id)) return 'price_action_behavior'
    return 'candlestick_pattern'
  }
  if (indicator.category === 'chart_pattern' || indicator.category === 'ict' || indicator.category === 'time_filter') {
    return indicator.category
  }
  return 'indicator'
}

// ConditionRow.tsxの<select>用 - 元の並び順(indicators配列の順)を保ったまま
// ジャンルごとにグループ化する(表示順はCONDITION_GENRE_ORDER固定)。
export function groupIndicatorsByGenre(indicators: IndicatorInfo[]): { label: string; items: IndicatorInfo[] }[] {
  const byGenre = new Map<ConditionGenreKey, IndicatorInfo[]>()
  for (const ind of indicators) {
    const genre = conditionGenreOf(ind)
    const list = byGenre.get(genre)
    if (list) list.push(ind)
    else byGenre.set(genre, [ind])
  }
  return CONDITION_GENRE_ORDER.filter((g) => byGenre.has(g.key)).map((g) => ({
    label: g.label,
    items: byGenre.get(g.key) as IndicatorInfo[],
  }))
}
