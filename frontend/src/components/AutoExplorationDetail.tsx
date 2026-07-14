import { useState } from 'react'
import { describeConditionTreeJapanese } from '../conditionTreeUtils'
import { toPips } from '../pipUtils'
import EquityCurveChart from './EquityCurveChart'
import DrawdownChart from './DrawdownChart'
import TradeHistoryTable from './TradeHistoryTable'
import YearlyPerformanceChart from './YearlyPerformanceChart'
import StatsPanel from './StatsPanel'
import FavoriteButton from './FavoriteButton'
import type { BacktestResults, IndicatorInfo, RankingRow } from '../types'

interface Props {
  // Short identity label for this panel (e.g. "Strat3") - shown instead of
  // the old single-instance "選択中: rank N / 全体ベストに戻す" banner, since
  // multiple instances of this component can now be mounted side by side
  // (see StrategyDetailTabs.tsx) and "戻す" has no meaning per-panel anymore.
  title: string
  displayResults: BacktestResults | undefined
  bestRow: RankingRow | undefined
  isRowLoading: boolean
  rowError: string | null
  indicators: IndicatorInfo[]
  // ランキング一覧の⭐と同じ状態/操作(App.tsx::handleFavorite) - 共通の
  // お気に入りボタンをストラテジー詳細画面にも置いてほしいという要望対応。
  isFavorite: boolean
  isPending: boolean
  onFavorite: () => void
}

const TABS = [
  { id: 'equity', label: 'エクイティ' },
  { id: 'drawdown', label: 'ドローダウン' },
  { id: 'yearly', label: '年別成績' },
  { id: 'trades', label: '取引履歴' },
  { id: 'mc', label: 'モンテカルロ' },
  { id: 'cond', label: '条件' },
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

// モンテカルロのDD統計値(engine/monte_carlo.py)も他の"pips"表記と同じ生の
// 価格差なので、他の指標同様に通貨ペアのpip_sizeで割ってから表示する。
function fmtPips(v: unknown, symbol: string | undefined): string {
  const n = Number(v)
  if (v === undefined || Number.isNaN(n)) return '-'
  return toPips(n, symbol).toFixed(2)
}

export default function AutoExplorationDetail({
  title,
  displayResults,
  bestRow,
  isRowLoading,
  rowError,
  indicators,
  isFavorite,
  isPending,
  onFavorite,
}: Props) {
  const [tab, setTab] = useState<TabId>('equity')

  const mc = displayResults?.monte_carlo_summary?.[0] as Record<string, unknown> | undefined
  const presentParams = PARAM_FIELDS.filter((f) => bestRow && f.key in bestRow)
  const symbol = bestRow?.symbol as string | undefined

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5 font-semibold text-gray-200">
          {title}
          <FavoriteButton isFavorite={isFavorite} isPending={isPending} onClick={onFavorite} />
        </span>
        {(isRowLoading || rowError) && (
          <span className={rowError ? 'text-red-400' : 'text-gray-400'}>
            {rowError ? `エラー: ${rowError}` : '再計算中…'}
          </span>
        )}
      </div>

      <StatsPanel row={bestRow} symbol={symbol} />

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
              {describeConditionTreeJapanese(bestRow.condition_tree, indicators)}
            </p>
          ) : (
            <div className="text-sm text-gray-500">この行に条件ツリーがありません</div>
          ))}

        {tab === 'equity' && <EquityCurveChart points={displayResults?.equity_curve ?? []} symbol={symbol} />}
        {tab === 'drawdown' && <DrawdownChart points={displayResults?.equity_curve ?? []} symbol={symbol} />}
        {tab === 'trades' && <TradeHistoryTable rows={displayResults?.trade_log ?? []} symbol={symbol} />}
        {tab === 'yearly' && <YearlyPerformanceChart rows={displayResults?.yearly_analysis ?? []} />}

        {tab === 'mc' &&
          (mc ? (
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
              {[
                { label: '評価', value: String(mc.rating ?? '-') },
                { label: 'シミュレーション回数', value: String(mc.simulations ?? '-') },
                { label: '平均最大DD(pips)', value: fmtPips(mc.avg_max_dd, symbol) },
                { label: '中央値DD(pips)', value: fmtPips(mc.median_max_dd, symbol) },
                { label: 'DD95%(pips)', value: fmtPips(mc.dd_95, symbol) },
                { label: '最悪ケース最大DD(pips)', value: fmtPips(mc.worst_max_dd, symbol) },
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
