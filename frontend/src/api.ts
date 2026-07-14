import axios from 'axios'
import type {
  BacktestJob,
  BacktestRequest,
  BacktestResults,
  BacktestStatus,
  ExplorationCategoriesResponse,
  IndicatorInfo,
  PriceBar,
  StrategyDetail,
  StrategyListEntry,
} from './types'

const client = axios.create({ baseURL: '/api' })

export async function fetchIndicators(): Promise<IndicatorInfo[]> {
  const res = await client.get<IndicatorInfo[]>('/indicators')
  return res.data
}

export async function fetchExplorationCategories(): Promise<ExplorationCategoriesResponse> {
  const res = await client.get<ExplorationCategoriesResponse>('/exploration-categories')
  return res.data
}

export async function fetchPriceData(symbol: string, timeframe: string, limit = 500): Promise<PriceBar[]> {
  const res = await client.get<PriceBar[]>('/price-data', { params: { symbol, timeframe, limit } })
  return res.data
}

export async function createBacktest(req: BacktestRequest): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/backtests', req)
  return res.data
}

export async function fetchBacktestStatus(jobId: string): Promise<BacktestStatus> {
  const res = await client.get<BacktestStatus>(`/backtests/${jobId}`)
  return res.data
}

export async function stopBacktest(jobId: string): Promise<{ status: string }> {
  const res = await client.post<{ status: string }>(`/backtests/${jobId}/stop`)
  return res.data
}

export async function fetchBacktestResults(jobId: string): Promise<BacktestResults> {
  const res = await client.get<BacktestResults>(`/backtests/${jobId}/results`)
  return res.data
}

export async function rerunRankingRow(jobId: string, rank: number): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>(`/backtests/${jobId}/rows/${rank}`)
  return res.data
}

export interface SaveRowResult {
  id: string
  name: string
  favorite: boolean
}

export async function saveRankingRow(
  jobId: string,
  rank: number,
  name: string,
  favorite: boolean,
): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>(`/backtests/${jobId}/rows/${rank}/save`, { name, favorite })
  return res.data
}

export async function fetchSaveResult(jobId: string): Promise<SaveRowResult> {
  const res = await client.get<SaveRowResult>(`/backtests/${jobId}/save-result`)
  return res.data
}

export async function fetchStrategies(): Promise<StrategyListEntry[]> {
  const res = await client.get<StrategyListEntry[]>('/strategies')
  return res.data
}

export async function fetchStrategyDetail(strategyId: string): Promise<StrategyDetail> {
  const res = await client.get<StrategyDetail>(`/strategies/${strategyId}`)
  return res.data
}

export function reportPdfUrl(jobId: string): string {
  return `/api/backtests/${jobId}/report.pdf`
}

export async function runWalkForward(symbol: string, timeframe: string, rank: number): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/walk-forward', { symbol, timeframe, rank })
  return res.data
}

export async function fetchWalkForwardResults(jobId: string): Promise<{ rows: Record<string, unknown>[] }> {
  const res = await client.get<{ rows: Record<string, unknown>[] }>(`/tools/walk-forward/${jobId}/results`)
  return res.data
}

export async function runMonteCarlo(
  symbol: string,
  timeframe: string,
  rank: number,
  simulations: number,
): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/monte-carlo', { symbol, timeframe, rank, simulations })
  return res.data
}

export async function runSensitivity(
  symbol: string,
  timeframe: string,
  mode: string,
  rank: number,
): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/sensitivity', { symbol, timeframe, mode, rank })
  return res.data
}

export async function fetchSensitivityResults(jobId: string): Promise<{ summary: Record<string, unknown>[] }> {
  const res = await client.get<{ summary: Record<string, unknown>[] }>(`/tools/sensitivity/${jobId}/results`)
  return res.data
}

export async function runConfidence(symbol: string, timeframe: string): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/confidence', { symbol, timeframe })
  return res.data
}

export async function fetchConfidenceResults(jobId: string): Promise<Record<string, unknown>> {
  const res = await client.get<Record<string, unknown>>(`/tools/confidence/${jobId}/results`)
  return res.data
}

export async function runOos(symbol: string, timeframe: string, rank: number, splitRatio: number): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/oos', { symbol, timeframe, rank, split_ratio: splitRatio })
  return res.data
}

export async function fetchOosResults(jobId: string): Promise<{ rows: Record<string, unknown>[] }> {
  const res = await client.get<{ rows: Record<string, unknown>[] }>(`/tools/oos/${jobId}/results`)
  return res.data
}

export async function fetchStrategiesFiltered(favoriteOnly: boolean): Promise<StrategyListEntry[]> {
  const res = await client.get<StrategyListEntry[]>('/strategies', { params: { favorite_only: favoriteOnly } })
  return res.data
}

export async function toggleStrategyFavorite(strategyId: string): Promise<StrategyDetail> {
  const res = await client.post<StrategyDetail>(`/strategies/${strategyId}/favorite`)
  return res.data
}

export async function deleteStrategy(strategyId: string): Promise<void> {
  await client.delete(`/strategies/${strategyId}`)
}

export async function addStrategyTags(strategyId: string, tags: string[]): Promise<StrategyDetail> {
  const res = await client.post<StrategyDetail>(`/strategies/${strategyId}/tags`, { tags })
  return res.data
}

export async function removeStrategyTag(strategyId: string, tag: string): Promise<StrategyDetail> {
  const res = await client.delete<StrategyDetail>(`/strategies/${strategyId}/tags/${encodeURIComponent(tag)}`)
  return res.data
}

export async function setStrategyMemo(strategyId: string, text: string): Promise<StrategyDetail> {
  const res = await client.post<StrategyDetail>(`/strategies/${strategyId}/memo`, { text })
  return res.data
}

export async function renameStrategy(strategyId: string, name: string): Promise<StrategyDetail> {
  const res = await client.post<StrategyDetail>(`/strategies/${strategyId}/rename`, { name })
  return res.data
}

export interface CompareEntry {
  id: string
  name: string
  symbol: string
  timeframe: string
  favorite: boolean
  tags: string[]
  metrics: Record<string, number>
  equity_curve: number[]
}

export async function compareStrategies(ids: string[]): Promise<{ entries: CompareEntry[] }> {
  const res = await client.get<{ entries: CompareEntry[] }>('/strategies/compare', { params: { ids: ids.join(',') } })
  return res.data
}

export interface DataValidationReport {
  path: string
  rows: number
  start: string
  end: string
  duplicate_timestamps: number
  ohlc_violations: number
  gap_count: number
  gaps: { before: string; after: string; minutes: number }[]
}

export async function validateData(symbol: string, timeframe: string): Promise<DataValidationReport> {
  const res = await client.get<DataValidationReport>('/data/validate', { params: { symbol, timeframe } })
  return res.data
}

export async function importCsv(
  sourceRoot: string,
  symbols: string[],
  timeframes: string[],
): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/data/import', { source_root: sourceRoot, symbols, timeframes })
  return res.data
}
