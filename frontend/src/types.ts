export type Operator = '>' | '<' | '>=' | '<=' | '==' | 'crosses_above' | 'crosses_below'

// Indicator params vary per indicator (ema/rsi/etc use "length", bollinger
// uses "period"+"num_std", macd uses "fast"+"slow"+"signal", etc - see
// IndicatorInfo.params for which keys a given indicator actually reads).
export interface ConditionParams {
  // ボリンジャーバンドのsource(例: "hl2")のような文字列パラメータも
  // 数値パラメータと同じ辞書に混在する。
  [key: string]: number | string
}

// Mirrors engine/conditions.py::Condition.to_dict()
export interface ConditionNode {
  indicator: string
  operator: Operator
  value: number | string
  params: ConditionParams
  value_params: ConditionParams
  // Multi-timeframe: undefined/omitted = the backtest's own base timeframe
  // (today's existing behavior). Only meaningful when value is a string
  // (an indicator reference) for value_timeframe - a literal number has no
  // timeframe concept.
  timeframe?: string
  value_timeframe?: string
}

// Mirrors engine/conditions.py::ConditionGroup.to_dict()
export interface GroupNode {
  op: 'AND' | 'OR' | 'NOT'
  children: TreeNode[]
}

export type TreeNode = ConditionNode | GroupNode

export function isGroup(node: TreeNode): node is GroupNode {
  // 'op' in node は node がオブジェクトでない(文字列/null等)場合に
  // TypeErrorで例外を投げる - APIから来るcondition_tree系の値は型定義上は
  // 常にオブジェクトだが、実際にはバックエンド側の未パース(Python repr
  // 文字列のまま)等で壊れた値が来ることがある(実際に踏んだ不具合:
  // ランキング一覧が「条件」列のレンダリングで丸ごとクラッシュし、画面が
  // 真っ白になった)。ここで防御的にチェックすることで、この関数を使う
  // 全箇所(コンポーネントツリー全体をクラッシュさせずに済む)を一括で守る。
  return typeof node === 'object' && node !== null && 'op' in node
}

// type="choice" means only the listed `choices` are meaningful (e.g.
// Fibonacci's ratio) - the UI renders a <select> instead of a free-entry
// number input for those. type="string_choice" is the same idea but for a
// string-valued param (e.g. Bollinger Bandsのsource) - kept as a separate
// type rather than overloading "choice" because the <select> onChange must
// NOT coerce the selected value with Number() for these.
export interface IndicatorParamSpec {
  name: string
  label: string
  default: number | string
  type: 'int' | 'float' | 'choice' | 'string_choice'
  choices?: number[]
  string_choices?: { value: string; label: string }[]
}

export interface IndicatorInfo {
  id: string
  label: string
  params: IndicatorParamSpec[]
  // api_server.pyのGET /api/indicatorsが付与するジャンル("indicator"/
  // "price_action"/"chart_pattern"/"ict"/"time_filter") - conditionGenres.ts
  // でConditionRow.tsxのドロップダウンをoptgroup分けする時に使う。
  category: string
  // EMA/高値/安値などの価格系指標、ATRなどのボラティリティ系指標は、
  // シンボルごとに価格帯が違いすぎるため固定の数値と比較する意味がない
  // (指標同士の比較のみ意図された設計) - falseの時はConditionRow.tsxの
  // 「固定値」選択肢自体を出さない。
  allow_literal: boolean
  // engine/indicator_pool.pyのkind("price_level"/"oscillator_0_100"/
  // "boolean_signal"など)。ConditionRow.tsxが、kind==="price_level"の指標を
  // 終値と比較する時に「より上/より下」を価格目線(EMA200より上=価格が
  // EMA200を上回っている)で解釈するために使う。
  kind: string | null
}

export type Direction = 'short' | 'long'

export interface BacktestRequest {
  mode: string
  timeframe: string
  symbol: string
  optimizer: string
  direction: Direction
  condition_tree?: TreeNode
  // Node-level condition-tree optimization: N complete tree variants
  // (built client-side, each differing only in one node's swept value).
  // When set, this is what actually gets swept instead of condition_tree.
  condition_tree_variants?: TreeNode[]
  // When both are set, the engine evaluates Long and Short simultaneously
  // (one shared position - no hedging) instead of condition_tree+direction.
  long_condition_tree?: GroupNode
  short_condition_tree?: GroupNode
  save_as?: string
  param_ranges?: Record<string, number[]>
  rr?: number
  use_weekend_exit?: boolean
  weekend_exit_hour?: number
  use_daily_exit?: boolean
  daily_exit_hour?: number
  spread_pips?: number
  slippage_pips?: number
  commission_per_trade?: number
  use_atr_trailing_stop?: boolean
  atr_trailing_length?: number
  atr_trailing_multiplier?: number
  use_max_dd_stop?: boolean
  max_dd_stop_pips?: number
  use_consecutive_loss_stop?: boolean
  consecutive_loss_stop_count?: number
  consecutive_loss_stop_bars?: number
  entry_method?: 'market' | 'limit' | 'stop'
  entry_offset_pips?: number
  use_position_sizing?: boolean
  position_sizing_method?: 'risk_percent' | 'fixed_lot' | 'compounding'
  initial_capital?: number
  account_currency?: 'JPY' | 'USD'
  risk_percent?: number
  fixed_lot_size?: number
  contract_size?: number
  conversion_rate?: number
  use_breakeven_stop?: boolean
  breakeven_trigger_rr?: number
  use_partial_tp?: boolean
  partial_tp_rr?: number
  partial_tp_fraction?: number
  // Multi-stage partial profit-taking: when set, replaces
  // partial_tp_rr/partial_tp_fraction above. Each level closes `fraction`
  // of whatever REMAINS of the position once price reaches that level's rr.
  partial_tp_levels?: { rr: number; fraction: number }[]
  // Decoupled SL/TP basis: both default server-side to the values that
  // reproduce the prior fixed RR-from-signal-candle behavior exactly.
  sl_basis?: 'signal_candle' | 'atr' | 'fixed_pips'
  sl_atr_length?: number
  sl_atr_multiplier?: number
  sl_fixed_pips?: number
  tp_basis?: 'rr' | 'fixed_pips' | 'custom'
  tp_fixed_pips?: number
  exit_condition_tree?: GroupNode
  // Auto-exploration engine (optimizer="structure"/"structure_genetic") -
  // ignored server-side for every other optimizer value. See
  // api_server.py::BacktestRequest for the field-by-field mapping to
  // main.py's --n-candidates/--max-depth/etc CLI flags.
  n_candidates?: number
  max_depth?: number
  max_leaves?: number
  min_trades?: number
  mtf_probability?: number
  mtf_timeframes?: string
  population?: number
  mutation_rate?: number
  generations?: number
  // Which indicators are eligible for generation - see
  // api_server.py::BacktestRequest / engine/indicator_pool.py's
  // CATEGORIES/LEVEL_PRESETS. Both undefined means every indicator is
  // eligible (today's unfiltered behavior).
  categories?: string[]
  explore_level?: 'light' | 'standard' | 'advanced'
  // 探索レベル="custom"のときだけ使う、カテゴリ内の個別指標名の絞り込み。
  // explore_levelと同時指定時はexplore_level優先(main.py側と同じ)。
  custom_indicator_names?: string[]
  // 2026-07-13追加、自動探索専用画面用。全てundefinedなら今まで通りの挙動
  // (api_server.py::BacktestRequest参照)。
  rr_choices?: number[]
  direction_mode?: 'long' | 'short' | 'both'
  start_date?: string
  end_date?: string
  min_leaves?: number
  selected_param_values?: Record<string, Record<string, number[]>>
  selected_literal_values?: Record<string, number[]>
  mandatory_conditions?: ConditionNode[]
}

export interface ExplorationCategory {
  id: string
  label: string
  count: number
  names: {
    id: string
    label: string
    // 代表値リスト(engine/indicator_pool.py::_apply_value_presets) -
    // param_presetsはparam_ranges/param_choicesの各パラメータ名に対応、
    // literal_presetsは比較閾値(literal_range/literal_choices)の代表値。
    param_presets: Record<string, number[]>
    literal_presets: number[] | null
  }[]
}

export interface ExplorationCategoriesResponse {
  categories: ExplorationCategory[]
  levels: { id: string; count: number }[]
}

export interface PartialTpLevel {
  rr: number
  fraction: number
}

// Which number within a Condition node a node-level optimize range targets:
// the comparison literal itself ('value'), one of the LEFT indicator's own
// params (e.g. ema's "length"), or - only when the comparison side is also
// an indicator - one of ITS params (e.g. "close > ema" where ema's own
// length is the thing being swept, not the comparison literal since there
// isn't one).
export type OptimizeField =
  | { kind: 'value' }
  | { kind: 'params'; key: string }
  | { kind: 'value_params'; key: string }

export interface ConditionOptimizeRange {
  enabled: boolean
  path: number[] | null
  field: OptimizeField | null
  min: number
  max: number
  step: number
}

export interface ParamRangeConfig {
  enabled: boolean
  param: string
  min: number
  max: number
  step: number
}

export interface OptimizableParam {
  id: string
  label: string
}

export interface BacktestJob {
  job_id: string
}

export type JobStatus = 'queued' | 'running' | 'done' | 'error'

export interface BacktestProgress {
  completed: number
  total: number
  elapsed_seconds: number
  // Only present for --optimizer structure_genetic - null for a plain
  // structure (random) run, which has no generation concept.
  generation: number | null
  generations_total: number | null
}

export interface BacktestStatus {
  status: JobStatus
  stdout_tail: string
  // Raw traceback (Python file paths/line numbers) - useful for reporting
  // a bug, not meant to be the first thing shown.
  error: string | null
  // Short, Japanese, non-scary summary extracted from `error` - what the
  // UI should show by default.
  error_summary: string | null
  // Only populated while status is "running", and only for
  // structure/structure_genetic runs (main.py writes progress.json for
  // those two optimizers only - see main.py::write_progress_file).
  progress: BacktestProgress | null
  // True once a stop has been requested via POST .../stop, until the
  // subprocess actually exits (status becomes "done"/"error").
  stop_requested: boolean
  // Only meaningful once status is "done": true if this run was cut short
  // by a stop request, so /results reflects only the candidates that had
  // completed at that point rather than a full run.
  stopped: boolean
  // This job's own timeframe (not necessarily today's toolbar selection -
  // see api_server.py::get_backtest_status). Used for the ランキング一覧の
  // 「通貨/時間足」列 so it doesn't drift if the toolbar is changed after
  // the run finishes.
  timeframe: string
}

export interface RankingRow {
  rank: number
  trades: number
  wins: number
  losses: number
  win_rate: number
  net_profit: number
  profit_factor: number
  max_dd: number
  expected_value: number
  recovery_factor: number
  sharpe_ratio: number
  sortino_ratio: number
  cagr: number
  calmar_ratio: number
  rr: number
  // MAE/MFE(最大逆行幅/最大追い風幅) - mae/mfeは全トレード中の最悪/最良の
  // 1トレードぶんの値(最大値)、_avg/_medianはそれぞれ全トレードの平均・
  // 中央値(main.py::run_one_backtestで集計)。
  mae: number
  mfe: number
  mae_avg: number
  mfe_avg: number
  mae_median: number
  mfe_median: number
  // 勝ちトレード/負けトレードだけに絞った利益・損失の集計値(main.py::
  // run_one_backtestで集計) - 期待値(勝ち負けをならした値)とは別に、
  // 勝ち/負けそれぞれの傾向を見るためのもの。損失側は符号付き(マイナス)。
  max_win: number
  max_loss: number
  avg_win: number
  avg_loss: number
  median_win: number
  median_loss: number
  // Only present when position sizing was enabled for the run.
  final_account_balance?: number
  total_profit_currency?: number
  // Present on any run whose params carried a condition_tree (the new
  // engine echoes params back into every result row) - parsed server-side
  // from a Python repr string into a real tree, see
  // api_server.py::_read_csv_records.
  condition_tree?: TreeNode
  [key: string]: unknown
}

export interface TradeRow {
  entry_time: string
  exit_time: string
  entry_price: number
  exit_price: number
  profit: number
  // MAE(最大逆行幅)/MFE(最大追い風幅) - 保有中に価格が最も不利/有利に
  // 動いた幅(entry_priceからの絶対値、profitと同じ単位)。
  mae: number
  mfe: number
  exit_reason: string
  // Only present for trades from a simultaneous Long+Short dual-direction
  // backtest, where direction varies per trade rather than being fixed for
  // the whole run.
  direction?: 'long' | 'short'
  // Only present when position sizing was enabled for the run.
  lot_size?: number
  profit_currency?: number
  account_balance?: number
  // Only present for trades that actually took at least one partial exit
  // (use_partial_tp) - one price per triggered level, in order.
  partial_exit_prices?: number[]
  partial_exit_count?: number
  [key: string]: unknown
}

export interface EquityPoint {
  trade_number: number
  equity: number
  equity_high: number
  drawdown: number
  exit_time: string
  entry_price?: number
  exit_price?: number
  mae?: number
  mfe?: number
  [key: string]: unknown
}

export interface MonthlyRow {
  year_month: string
  trades: number
  wins: number
  losses: number
  win_rate: number
  net_profit: number
  gross_profit: number
  gross_loss: number
  profit_factor: number
  [key: string]: unknown
}

export interface YearlyRow {
  year: number
  trades: number
  wins: number
  losses: number
  win_rate: number
  net_profit: number
  gross_profit: number
  gross_loss: number
  profit_factor: number
  [key: string]: unknown
}

export interface BacktestResults {
  ranking_total: RankingRow[]
  equity_curve: EquityPoint[]
  trade_log: TradeRow[]
  monte_carlo_summary: Record<string, unknown>[]
  yearly_analysis: YearlyRow[]
  monthly_analysis: MonthlyRow[]
  stability_analysis: Record<string, unknown>[]
}

export interface StrategyListEntry {
  id: string
  name: string
  created_at: string
  mode: string
  timeframe: string
  symbol: string
  tags: string[]
  favorite: boolean
  metrics: Record<string, number>
}

export interface StrategyDetail extends StrategyListEntry {
  memo: string
  strategy_config: string | null
  params: Record<string, unknown> & {
    condition_tree?: TreeNode | null
    long_condition_tree?: GroupNode | null
    short_condition_tree?: GroupNode | null
    direction?: Direction
  }
  snapshot_dir: string
}

export interface PriceBar {
  datetime: string
  open: number
  high: number
  low: number
  close: number
  [key: string]: unknown
}
