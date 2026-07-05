import axios from 'axios'
import type {
  BacktestJob,
  BacktestRequest,
  BacktestResults,
  BacktestStatus,
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

export async function fetchBacktestResults(jobId: string): Promise<BacktestResults> {
  const res = await client.get<BacktestResults>(`/backtests/${jobId}/results`)
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
