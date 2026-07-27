import type { IndicatorInfo } from './types'

// ConditionRow.tsxの指標ピッカーをoptgroupでジャンル分けするための分類 -
// ユーザー作成のExcel「Strategy Lab 条件一覧.xlsx」と同じジャンルにする
// (ユーザー要望:「このジャンル分けをStrategy Labの条件設定のところでも
// してほしい」)。api_server.pyが返すcategory("indicator"/"price_action"/
// "chart_pattern"/"ict"/"time_filter")のうち、"price_action"は範囲が
// 広すぎるため、id単位でさらに3つ(価格データ/ローソク足パターン/
// プライスアクション)に分ける - Excel作成時に使った分類と全く同じ内訳。
//
// "indicator"ジャンル(EMA/RSI/MACD等の技術指標199件)の中はさらに、EMA
// パーフェクトオーダーのように特定の指標に由来する派生指標(距離・傾き・
// 連続上昇下降・ダイバージェンス等)が多いため、指標系統ごとの「サブ
// ジャンル」に分ける(ユーザー要望:「EMAパーフェクトオーダーってEMAを
// ANDで合わせたら作れるよね。インジケーターの中にEMAというジャンルを
// 作ってその中にEMA関連のものを入れてほしい。そのほかの指標に関しても
// そんな感じにジャンル分けできるものはして」)。ただしEMA等を最上位の
// ジャンルにはせず、「インジケーター」を選んだ時だけ現れる第2階層にする
// (ユーザー要望:「EMA関連などすべてインジケーターの中に入れて。まず
// プルダウンでインジケーター/価格データ/...のどれかを選択。すると
// またプルダウンが開きEMA/SMA/...のどれかを選択。するとまたプルダウンが
// 開きEMA/パーフェクトオーダー/...の中から選択という形にしたい」)
// - 3段階カスケード: ジャンル→(indicatorの時だけ)サブジャンル→指標。
// 複数の指標にまたがる派生指標(dist_close_ema等)は、その"主題"となって
// いる指標のサブジャンルに寄せる(ATR等は単位として使われているだけの
// 場合は寄せない - 例: dist_to_ema_atr_ratioは「EMAからの距離」が主題
// なのでEMA、linreg_slope_atr_ratioは「線形回帰の傾き」が主題なので
// 線形回帰)。明確な系統を持たないもの(CCI/Williams %R/Choppiness Index
// 等の単独オシレーターや、前日高値/安値までの距離)は「インジケーター
// (その他)」に残す。

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
    // 統合版に置き換えられた旧指標(legacy)は、新規に条件を組む時の選択肢
    // には出さない(ユーザー要望「古い3種を選択リストから外して」) -
    // 既存の保存済みストラテジーの表示はIndicatorPicker.tsx側で別途
    // 現在値を保護しているため、ここで単純に除外して問題ない。
    if (ind.legacy) continue
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

// ジャンル→指標一覧の対応表(IndicatorPicker.tsxの1段階目用) - ジャンルを
//選ぶとその中の指標だけに絞り込まれる(ユーザー要望:「プルダウンでは
// まずジャンルを決定して、そのあとに右側に使用する指標が出てくるように
// して」)。
export function buildGenreItemsMap(indicators: IndicatorInfo[]): Map<ConditionGenreKey, IndicatorInfo[]> {
  const groups = groupIndicatorsByGenre(indicators)
  const byLabel = new Map(groups.map((g) => [g.label, g.items]))
  const map = new Map<ConditionGenreKey, IndicatorInfo[]>()
  for (const g of CONDITION_GENRE_ORDER) {
    const items = byLabel.get(g.label)
    if (items && items.length > 0) map.set(g.key, items)
  }
  return map
}

// ---------------------------------------------------------------------------
// 「インジケーター」ジャンルの中だけに存在する第2階層(サブジャンル)。
// ---------------------------------------------------------------------------

const EMA_IDS = new Set([
  'ema', 'ema_rising', 'ema_falling', 'ema_consecutive_rising', 'ema_consecutive_falling',
  'ema_slope_degrees', 'ema_slope', 'ema_roc', 'dist_close_ema', 'dist_high_ema', 'dist_low_ema',
  'dist_close_ema_pct', 'dist_to_ema_atr_ratio',
  'ema_perfect_order_bullish', 'ema_perfect_order_bearish',
  'ema_perfect_order_broken_bullish', 'ema_perfect_order_broken_bearish',
  'correlation_close_ema',
])
const SMA_IDS = new Set(['sma', 'dist_close_sma', 'dist_high_sma', 'dist_low_sma'])
const RSI_IDS = new Set([
  'rsi', 'rsi_rising', 'rsi_falling', 'rsi_consecutive_rising', 'rsi_consecutive_falling',
  'rsi_rolling_mean', 'rsi_deviation', 'percentile_rank_rsi', 'zscore_rsi', 'is_max_rsi_of_n',
  'rsi_divergence_bearish', 'rsi_divergence_bullish', 'connors_rsi',
])
const MACD_IDS = new Set([
  'macd_line', 'macd_signal', 'macd_histogram', 'macd_rising', 'macd_falling',
  'macd_consecutive_rising', 'macd_consecutive_falling', 'macd_rolling_mean',
  'macd_divergence_bearish', 'macd_divergence_bullish',
])
const ADX_DMI_IDS = new Set([
  'adx', 'plus_di', 'minus_di', 'adx_rising', 'adx_falling',
  'adx_consecutive_rising', 'adx_consecutive_falling', 'adx_rolling_mean',
])
const ATR_IDS = new Set([
  'atr', 'atr_rising', 'atr_falling', 'atr_consecutive_rising', 'atr_consecutive_falling',
  'atr_roc', 'atr_rolling_mean', 'atr_deviation', 'percentile_rank_atr', 'zscore_atr', 'is_min_atr_of_n',
])
const SUPERTREND_IDS = new Set([
  'supertrend_line', 'supertrend_direction', 'supertrend_rising', 'supertrend_falling',
  'supertrend_consecutive_rising', 'supertrend_consecutive_falling',
  'dist_close_supertrend', 'dist_high_supertrend', 'dist_low_supertrend',
  'supertrend_flip_bullish', 'supertrend_flip_bearish',
])
const VWAP_IDS = new Set([
  'vwap', 'vwap_rising', 'vwap_falling', 'vwap_consecutive_rising', 'vwap_consecutive_falling',
  'dist_close_vwap', 'dist_high_vwap', 'dist_low_vwap',
])
const BOLLINGER_IDS = new Set([
  'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
  'dist_close_bb_upper', 'dist_close_bb_lower', 'dist_high_bb_upper', 'dist_high_bb_lower',
  'dist_low_bb_upper', 'dist_low_bb_lower',
  'bb_percent_b', 'bb_width', 'bb_width_percent', 'bb_squeeze', 'bb_expansion',
])
const STOCHASTIC_IDS = new Set(['stochastic_k', 'stochastic_d'])
const ICHIMOKU_IDS = new Set([
  'ichimoku_tenkan', 'ichimoku_kijun', 'ichimoku_senkou_a', 'ichimoku_senkou_b',
  'ichimoku_price_vs_cloud', 'ichimoku_kumo_twist_bullish', 'ichimoku_kumo_twist_bearish',
  'ichimoku_chikou_signal',
])
const PIVOT_IDS = new Set([
  'pivot', 'pivot_r1', 'pivot_s1',
  'woodie_pivot', 'woodie_r1', 'woodie_s1', 'woodie_r2', 'woodie_s2', 'woodie_r3', 'woodie_s3', 'woodie_r4', 'woodie_s4',
  'camarilla_r1', 'camarilla_r2', 'camarilla_r3', 'camarilla_r4', 'camarilla_s1', 'camarilla_s2', 'camarilla_s3', 'camarilla_s4',
  'fib_pivot', 'fib_pivot_r1', 'fib_pivot_r2', 'fib_pivot_r3', 'fib_pivot_s1', 'fib_pivot_s2', 'fib_pivot_s3',
  'dist_close_pivot', 'dist_high_pivot', 'dist_low_pivot',
])
const FIBONACCI_IDS = new Set(['fib_level', 'dist_to_fib'])
const DONCHIAN_IDS = new Set([
  'highest_high', 'lowest_low', 'highest_close', 'lowest_close',
  'donchian_mid', 'donchian_percent_position',
  'dist_close_donchian_upper', 'dist_close_donchian_lower',
  'dist_high_donchian_upper', 'dist_high_donchian_lower',
  'dist_low_donchian_upper', 'dist_low_donchian_lower',
])
const VOLATILITY_IDS = new Set(['adr', 'close_rolling_std', 'historical_volatility'])
const VOLUME_IDS = new Set([
  'obv', 'obv_rising', 'obv_falling', 'obv_consecutive_rising', 'obv_consecutive_falling',
  'mfi', 'mfi_rising', 'mfi_falling', 'mfi_consecutive_rising', 'mfi_consecutive_falling',
  'cmf', 'ad_line', 'chaikin_oscillator',
])
const AROON_IDS = new Set(['aroon_up', 'aroon_down', 'aroon_oscillator'])
const PARABOLIC_SAR_IDS = new Set(['parabolic_sar_line', 'parabolic_sar_direction'])
const KELTNER_IDS = new Set(['keltner_upper', 'keltner_middle', 'keltner_lower', 'ttm_squeeze', 'ttm_squeeze_release'])
const LINREG_IDS = new Set(['linreg_slope_atr_ratio', 'linreg_angle_degrees', 'linreg_value', 'linreg_upper', 'linreg_lower'])
// 残り(indicatorカテゴリのうち上記どれにも属さないもの)は「インジケーター
// (その他)」: CCI/Williams %R/Choppiness Index/CMO/Coppock Curve/Bull・Bear
// Power/相関オシレーター(単独の独立系オシレーター)、前日高値/安値までの
// 距離6種、過去N本平均高値/安値、終値のZスコア。

export type IndicatorSubGenreKey =
  | 'ema'
  | 'sma'
  | 'rsi'
  | 'macd'
  | 'adx_dmi'
  | 'atr'
  | 'supertrend'
  | 'vwap'
  | 'bollinger'
  | 'stochastic'
  | 'ichimoku'
  | 'pivot'
  | 'fibonacci'
  | 'donchian'
  | 'volatility'
  | 'volume'
  | 'aroon'
  | 'parabolic_sar'
  | 'keltner'
  | 'linear_regression'
  | 'other'

export const INDICATOR_SUB_GENRE_ORDER: { key: IndicatorSubGenreKey; label: string }[] = [
  { key: 'ema', label: 'EMA' },
  { key: 'sma', label: 'SMA' },
  { key: 'rsi', label: 'RSI' },
  { key: 'macd', label: 'MACD' },
  { key: 'adx_dmi', label: 'ADX/DMI' },
  { key: 'atr', label: 'ATR' },
  { key: 'supertrend', label: 'SuperTrend' },
  { key: 'vwap', label: 'VWAP' },
  { key: 'bollinger', label: 'ボリンジャーバンド' },
  { key: 'stochastic', label: 'ストキャスティクス' },
  { key: 'ichimoku', label: '一目均衡表' },
  { key: 'pivot', label: 'ピボット' },
  { key: 'fibonacci', label: 'フィボナッチ' },
  { key: 'donchian', label: 'ドンチアン' },
  { key: 'volatility', label: 'ボラティリティ' },
  { key: 'volume', label: '出来高(OBV/MFI等)' },
  { key: 'aroon', label: 'Aroon' },
  { key: 'parabolic_sar', label: 'パラボリックSAR' },
  { key: 'keltner', label: 'ケルトナーチャネル' },
  { key: 'linear_regression', label: '線形回帰' },
  { key: 'other', label: 'インジケーター(その他)' },
]

const INDICATOR_SUB_GENRE_ID_SETS: [Set<string>, IndicatorSubGenreKey][] = [
  [EMA_IDS, 'ema'],
  [SMA_IDS, 'sma'],
  [RSI_IDS, 'rsi'],
  [MACD_IDS, 'macd'],
  [ADX_DMI_IDS, 'adx_dmi'],
  [ATR_IDS, 'atr'],
  [SUPERTREND_IDS, 'supertrend'],
  [VWAP_IDS, 'vwap'],
  [BOLLINGER_IDS, 'bollinger'],
  [STOCHASTIC_IDS, 'stochastic'],
  [ICHIMOKU_IDS, 'ichimoku'],
  [PIVOT_IDS, 'pivot'],
  [FIBONACCI_IDS, 'fibonacci'],
  [DONCHIAN_IDS, 'donchian'],
  [VOLATILITY_IDS, 'volatility'],
  [VOLUME_IDS, 'volume'],
  [AROON_IDS, 'aroon'],
  [PARABOLIC_SAR_IDS, 'parabolic_sar'],
  [KELTNER_IDS, 'keltner'],
  [LINREG_IDS, 'linear_regression'],
]

// conditionGenreOf(indicator)==='indicator'の指標だけに意味を持つ第2階層。
// それ以外のジャンル(価格データ等)の指標に呼んでも'other'が返るだけで、
// ConditionRow.tsx側はジャンルが'indicator'の時しかこれを使わない。
export function indicatorSubGenreOf(indicator: IndicatorInfo): IndicatorSubGenreKey {
  for (const [ids, key] of INDICATOR_SUB_GENRE_ID_SETS) {
    if (ids.has(indicator.id)) return key
  }
  return 'other'
}

// ConditionRow.tsxの「インジケーター」ジャンル選択時、2段階目(サブジャンル)
// の<select>用 - groupIndicatorsByGenre同様、元の並び順を保ったまま
// サブジャンルごとにグループ化する。
export function groupIndicatorsBySubGenre(indicators: IndicatorInfo[]): { label: string; items: IndicatorInfo[] }[] {
  const bySubGenre = new Map<IndicatorSubGenreKey, IndicatorInfo[]>()
  for (const ind of indicators) {
    const sub = indicatorSubGenreOf(ind)
    const list = bySubGenre.get(sub)
    if (list) list.push(ind)
    else bySubGenre.set(sub, [ind])
  }
  return INDICATOR_SUB_GENRE_ORDER.filter((g) => bySubGenre.has(g.key)).map((g) => ({
    label: g.label,
    items: bySubGenre.get(g.key) as IndicatorInfo[],
  }))
}

// 「インジケーター」ジャンルの中の第2階層(EMA/RSI/MACD等のサブジャンル)
// →指標一覧の対応表(IndicatorPicker.tsxの2段階目用) - buildGenreItemsMap
// と同じ理由。
export function buildSubGenreItemsMap(indicatorGenreItems: IndicatorInfo[]): Map<IndicatorSubGenreKey, IndicatorInfo[]> {
  const groups = groupIndicatorsBySubGenre(indicatorGenreItems)
  const byLabel = new Map(groups.map((g) => [g.label, g.items]))
  const map = new Map<IndicatorSubGenreKey, IndicatorInfo[]>()
  for (const g of INDICATOR_SUB_GENRE_ORDER) {
    const items = byLabel.get(g.label)
    if (items && items.length > 0) map.set(g.key, items)
  }
  return map
}
