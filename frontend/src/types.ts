export type Operator = '>' | '<' | '>=' | '<=' | '==' | 'crosses_above' | 'crosses_below'

export interface ConditionParams {
  length?: number
}

// Mirrors engine/conditions.py::Condition.to_dict()
export interface ConditionNode {
  indicator: string
  operator: Operator
  value: number | string
  params: ConditionParams
  value_params: ConditionParams
}

// Mirrors engine/conditions.py::ConditionGroup.to_dict()
export interface GroupNode {
  op: 'AND' | 'OR' | 'NOT'
  children: TreeNode[]
}

export type TreeNode = ConditionNode | GroupNode

export function isGroup(node: TreeNode): node is GroupNode {
  return 'op' in node
}

export interface IndicatorInfo {
  id: string
  label: string
  needs_period: boolean
}

export type Direction = 'short' | 'long'

export interface BacktestRequest {
  mode: string
  timeframe: string
  symbol: string
  optimizer: string
  direction: Direction
  condition_tree?: TreeNode
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

export interface BacktestStatus {
  status: JobStatus
  stdout_tail: string
  error: string | null
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
  // Only present when position sizing was enabled for the run.
  final_account_balance?: number
  total_profit_currency?: number
  [key: string]: unknown
}

export interface TradeRow {
  entry_time: string
  exit_time: string
  entry_price: number
  exit_price: number
  profit: number
  exit_reason: string
  // Only present for trades from a simultaneous Long+Short dual-direction
  // backtest, where direction varies per trade rather than being fixed for
  // the whole run.
  direction?: 'long' | 'short'
  // Only present when position sizing was enabled for the run.
  lot_size?: number
  profit_currency?: number
  account_balance?: number
  [key: string]: unknown
}

export interface EquityPoint {
  trade_number: number
  equity: number
  equity_high: number
  drawdown: number
  exit_time: string
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
