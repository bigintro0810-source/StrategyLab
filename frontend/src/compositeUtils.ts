import { toPips } from './pipUtils'
import type { EquityPoint, TradeRow } from './types'

// 合成タブ: チェックした複数ストラテジーのtrade_logを時系列でまとめて1本の
// エクイティカーブとして評価し直す(EA Studioの「ポートフォリオ結合」相当)。
// 通貨ペアが異なるストラテジー同士でも比較できるよう、各トレードはこの
// 時点でpipsへ変換してから合成する(以降は生の価格差ではなく合成後のpips
// 値として扱う)。
export interface CompositeInput {
  id: string
  name: string
  symbol: string | undefined
  tradeLog: TradeRow[]
}

export interface CompositeResult {
  trades: number
  netProfitPips: number
  expectedValuePips: number
  profitFactor: number
  maxDdPips: number
  winRate: number
  equityCurve: EquityPoint[]
  tradeLog: (TradeRow & { source: string })[]
}

export function computeComposite(inputs: CompositeInput[]): CompositeResult {
  const merged = inputs
    .flatMap((input) =>
      input.tradeLog.map((t) => ({
        ...t,
        profit: toPips(t.profit, input.symbol),
        source: input.name,
      })),
    )
    .sort((a, b) => new Date(a.exit_time).getTime() - new Date(b.exit_time).getTime())

  let cumulative = 0
  let peak = 0
  let grossProfit = 0
  let grossLoss = 0
  let wins = 0
  const equityCurve: EquityPoint[] = merged.map((t, i) => {
    cumulative += t.profit
    peak = Math.max(peak, cumulative)
    if (t.profit > 0) {
      grossProfit += t.profit
      wins += 1
    } else {
      grossLoss += Math.abs(t.profit)
    }
    return {
      trade_number: i + 1,
      equity: cumulative,
      equity_high: peak,
      drawdown: peak - cumulative,
      exit_time: t.exit_time,
    }
  })

  const trades = merged.length
  const maxDdPips = equityCurve.reduce((max, p) => Math.max(max, p.drawdown), 0)

  return {
    trades,
    netProfitPips: cumulative,
    expectedValuePips: trades > 0 ? cumulative / trades : 0,
    profitFactor: grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 999 : 0,
    maxDdPips,
    winRate: trades > 0 ? (wins / trades) * 100 : 0,
    equityCurve,
    tradeLog: merged,
  }
}
