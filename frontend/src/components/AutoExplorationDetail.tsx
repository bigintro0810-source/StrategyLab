import { useState } from 'react'
import { describeConditionTree } from '../conditionTreeUtils'
import EquityCurveChart from './EquityCurveChart'
import DrawdownChart from './DrawdownChart'
import TradeHistoryTable from './TradeHistoryTable'
import YearlyPerformanceChart from './YearlyPerformanceChart'
import MonthlyHeatmap from './MonthlyHeatmap'
import StatsPanel from './StatsPanel'
import type { BacktestResults, RankingRow } from '../types'

interface Props {
  displayResults: BacktestResults | undefined
  bestRow: RankingRow | undefined
  selectedRank: number | null
  isRowLoading: boolean
  onResetSelection: () => void
}

const TABS = [
  { id: 'cond', label: '条件' },
  { id: 'equity', label: 'エクイティ' },
  { id: 'drawdown', label: 'ドローダウン' },
  { id: 'trades', label: '取引履歴' },
  { id: 'yearly', label: '年別成績' },
  { id: 'monthly', label: '月別成績' },
  { id: 'stats', label: '統計情報' },
  { id: 'mc', label: 'モンテカルロ' },
  { id: 'params', label: 'パラメータ' },
] as const

type TabId = (typeof TABS)[number]['id']

// Params worth surfacing in the パラメータ tab if the selected row happens to
// carry them - result rows echo back every field main.py's params dict had,
// which varies a lot by optimizer/strategy-config, so this is a "show if
// present" allowlist rather than a fixed schema.
const PARAM_FIELDS: { key: string; label: string }[] = [
  { key: 'rr', label: 'RR' },
  { key: 'symbol', label: '通貨ペア' },
  { key: 'lookahead_bars', label: 'lookahead_bars' },
  { key: 'direction', label: '方向' },
  { key: 'use_weekend_exit', label: '週末決済' },
  { key: 'weekend_exit_hour', label: '週末決済時刻' },
  { key: 'use_daily_exit', label: '日次決済' },
  { key: 'spread_pips', label: 'スプレッド(pips)' },
  { key: 'slippage_pips', label: 'スリッページ(pips)' },
  { key: 'pip_size', label: 'pip_size' },
]

function formatParamValue(v: unknown): string {
  if (v === undefined || v === null) return '-'
  if (typeof v === 'boolean') return v ? 'あり' : 'なし'
  return String(v)
}

export default function AutoExplorationDetail({ displayResults, bestRow, selectedRank, isRowLoading, onResetSelection }: Props) {
  const [tab, setTab] = useState<TabId>('cond')

  const mc = displayResults?.monte_carlo_summary?.[0] as Record<string, unknown> | undefined
  const presentParams = PARAM_FIELDS.filter((f) => bestRow && f.key in bestRow)

  return (
    <div className="flex h-full flex-col">
      {selectedRank !== null && (
        <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
          <span>{isRowLoading ? '再計算中…' : `選択中: rank ${selectedRank}`}</span>
          {!isRowLoading && (
            <button onClick={onResetSelection} className="text-emerald-400 hover:underline">
              全体ベストに戻す
            </button>
          )}
        </div>
      )}

      <div className="mb-2 flex gap-1 overflow-x-auto border-b border-white/10 text-xs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={
              tab === t.id
                ? 'whitespace-nowrap border-b-2 border-purple-400 px-2.5 py-1.5 font-semibold text-gray-100'
                : 'whitespace-nowrap border-b-2 border-transparent px-2.5 py-1.5 text-gray-500 hover:text-gray-300'
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {tab === 'cond' &&
          (bestRow?.condition_tree ? (
            <p className="whitespace-pre-wrap font-mono text-xs text-gray-300">
              {describeConditionTree(bestRow.condition_tree)}
            </p>
          ) : (
            <div className="text-sm text-gray-500">この行に条件ツリーがありません</div>
          ))}

        {tab === 'equity' && <EquityCurveChart points={displayResults?.equity_curve ?? []} />}
        {tab === 'drawdown' && <DrawdownChart points={displayResults?.equity_curve ?? []} />}
        {tab === 'trades' && <TradeHistoryTable rows={displayResults?.trade_log ?? []} />}
        {tab === 'yearly' && <YearlyPerformanceChart rows={displayResults?.yearly_analysis ?? []} />}
        {tab === 'monthly' && <MonthlyHeatmap rows={displayResults?.monthly_analysis ?? []} />}
        {tab === 'stats' && <StatsPanel row={bestRow} />}

        {tab === 'mc' &&
          (mc ? (
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
              {[
                { label: '評価', value: String(mc.rating ?? '-') },
                { label: 'シミュレーション回数', value: String(mc.simulations ?? '-') },
                { label: '平均最大DD', value: String(mc.avg_max_dd ?? '-') },
                { label: '中央値DD', value: String(mc.median_max_dd ?? '-') },
                { label: 'DD95%', value: String(mc.dd_95 ?? '-') },
                { label: '最悪ケース最大DD', value: String(mc.worst_max_dd ?? '-') },
              ].map((s) => (
                <div key={s.label} className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <div className="text-xs text-gray-400">{s.label}</div>
                  <div className="font-semibold text-gray-100">{s.value}</div>
                </div>
              ))}
              {typeof mc.comment === 'string' && <div className="col-span-full text-xs text-gray-400">{mc.comment}</div>}
            </div>
          ) : (
            <div className="text-sm text-gray-500">まだ結果がありません</div>
          ))}

        {tab === 'params' &&
          (presentParams.length > 0 ? (
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
              {presentParams.map((f) => (
                <div key={f.key} className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <div className="text-xs text-gray-400">{f.label}</div>
                  <div className="font-mono text-gray-100">{formatParamValue(bestRow?.[f.key])}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-gray-500">まだ結果がありません</div>
          ))}
      </div>
    </div>
  )
}
