import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchChartIndicators, fetchPriceData } from '../api'
import { describeStrategyConditionJapaneseLines } from '../conditionTreeUtils'
import { toPips } from '../pipUtils'
import ChartPanel from './ChartPanel'
import EquityCurveChart from './EquityCurveChart'
import DrawdownChart from './DrawdownChart'
import TradeHistoryTable from './TradeHistoryTable'
import YearlyPerformanceChart from './YearlyPerformanceChart'
import StatsPanel from './StatsPanel'
import FavoriteButton from './FavoriteButton'
import PineScriptModal from './PineScriptModal'
import type { BacktestResults, IndicatorInfo, RankingRow, TreeNode } from '../types'

interface Props {
  // Short identity label for this panel (e.g. "Strat3") - shown instead of
  // the old single-instance "選択中: rank N / 全体ベストに戻す" banner, since
  // multiple instances of this component can now be mounted side by side
  // (see StrategyDetailTabs.tsx) and "戻す" has no meaning per-panel anymore.
  title: string
  // bestRow.symbolはあるがtimeframeは持たない(main.pyが候補ごとにecho-back
  // していないため - ランキング一覧の「通貨/時間足」列と同じ理由)ので、
  // この実行/保存ストラテジー全体で共通のtimeframeを別途渡す。
  timeframe: string | undefined
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
  // 比較/合成のチェックボックス(以前はランキング一覧/ライブラリの行に
  // あったが、⭐の隣に移設した - このパネルが「1件を選んで見る」場所なので
  // 比較/合成対象に入れる/外すのもここで完結させる)。
  isCompareChecked: boolean
  onToggleCompare: () => void
  isCompositeChecked: boolean
  onToggleComposite: () => void
  // 🔖(ライブラリへの保存)ボタン。結果側(StrategyDetailTabs)だけが渡す -
  // ライブラリ側(LibraryDetailTabs)は対象が既に保存済みなので不要
  // (省略時はボタン自体を出さない)。
  isSaved?: boolean
  onBookmark?: () => void
  // 合成タブ(CompositeDetail.tsx)からの再利用時はfalseを渡し、比較/合成の
  // チェックボックス自体を非表示にする(合成結果を更に比較/合成対象には
  // 選べない設計のため意味を持たない)。省略時は常に表示(既存動作)。
  showCompareComposite?: boolean
  // チャートタブの価格データ取得だけに使う実シンボル。bestRow.symbolは
  // pips換算(StatsPanel/取引履歴/モンテカルロ)専用の値になり得る
  // (CompositeDetail.tsxがsymbol="COMPOSITE"固定で渡すため、実際の価格
  // データはこの通貨ペアには存在しない) - 両者の意味が食い違うケース向けに
  // 別途上書きできるようにする。省略時はbestRow.symbolをそのまま使う
  // (既存動作)。
  chartSymbol?: string
  // 条件/パラメータタブの中身を丸ごと差し替える。合成結果は単一の
  // condition_tree/paramsを持たない(複数ストラテジーの合成のため)ので、
  // CompositeDetail.tsxが対象ごとの一覧をここに渡す。省略時は通常通り
  // bestRowから組み立てる(既存動作)。
  condTabContent?: ReactNode
  paramsTabContent?: ReactNode
  // 保存済みストラテジーの永続ID。渡された時だけ「TradingViewコード」ボタン
  // を出す(condition_treeをPine Scriptへ変換するにはengine側でこのIDから
  // 保存済みparamsを引く必要があり、未保存の候補行には対応できないため -
  // api_server.py::get_strategy_pine_script参照)。
  strategyId?: string
  // どのサブタブ(累積Pips/チャート/取引履歴...)を表示中かは、呼び出し元
  // (App.tsx)がrank/id単位で保持する - このコンポーネント自身が
  // useStateで持つと、別画面へ移動してmainTab/subTabが変わった瞬間に
  // ResultsScreen/StrategyDetailTabs/AutoExplorationDetail自体がアン
  // マウントされ、戻ってきた時に累積Pipsへリセットされてしまうため
  // (実際に踏んだ不具合)。
  activeTab: TabId
  onTabChange: (tab: TabId) => void
}

const TABS = [
  { id: 'equity', label: '累積Pips' },
  { id: 'drawdown', label: 'ドローダウン' },
  { id: 'yearly', label: '年別獲得Pips' },
  { id: 'chart', label: 'チャート' },
  { id: 'trades', label: '取引履歴' },
  { id: 'mc', label: 'モンテカルロ' },
  { id: 'cond', label: '条件' },
  { id: 'params', label: 'パラメータ' },
] as const

export type TabId = (typeof TABS)[number]['id']

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
  timeframe,
  displayResults,
  bestRow,
  isRowLoading,
  rowError,
  indicators,
  isFavorite,
  isPending,
  onFavorite,
  isCompareChecked,
  onToggleCompare,
  isCompositeChecked,
  onToggleComposite,
  isSaved,
  onBookmark,
  showCompareComposite = true,
  chartSymbol,
  condTabContent,
  paramsTabContent,
  strategyId,
  activeTab: tab,
  onTabChange: setTab,
}: Props) {
  const [showPineScript, setShowPineScript] = useState(false)

  const mc = displayResults?.monte_carlo_summary?.[0] as Record<string, unknown> | undefined
  const presentParams = PARAM_FIELDS.filter((f) => bestRow && f.key in bestRow)
  const symbol = bestRow?.symbol as string | undefined
  const priceSymbol = chartSymbol ?? symbol
  const direction = bestRow?.direction as 'long' | 'short' | undefined
  const conditionTree = bestRow?.condition_tree as TreeNode | undefined
  const longConditionTree = bestRow?.long_condition_tree as TreeNode | undefined
  const shortConditionTree = bestRow?.short_condition_tree as TreeNode | undefined
  // 単一方向バックテストのトレードはper-trade directionを持たない(dual
  // direction運用時だけ個別に付く)ため、取引履歴の方向列がずっと出ない
  // 不具合があった - この行自体の設定方向(direction)をフォールバックとして
  // 各トレードへ補う(compositeUtils.ts::computeCompositeと同じ考え方)。
  const tradesWithDirection = (displayResults?.trade_log ?? []).map((t) => ({
    ...t,
    direction: t.direction ?? direction,
  }))

  // チャートタブは開いた時だけ取得する - このパネル自体が最大20個同時に
  // 開ける(MAX_DETAIL_TABS)ため、全タブぶん常時フェッチすると無駄が大きい。
  // strategy_idを持たない候補行(未保存のランキング一覧・反転ストラテジー)
  // でも見られるよう、ツリー自体を渡すfetchChartIndicatorsを使う
  // (fetchStrategyChartIndicatorsは保存済み専用 - api_server.py参照)。
  const chartEnabled = tab === 'chart' && priceSymbol != null && timeframe != null
  const priceQuery = useQuery({
    queryKey: ['auto-detail-chart-price', priceSymbol, timeframe],
    queryFn: () => fetchPriceData(priceSymbol as string, timeframe as string, 20000),
    enabled: chartEnabled,
  })
  const chartIndicatorsQuery = useQuery({
    queryKey: [
      'auto-detail-chart-indicators',
      priceSymbol,
      timeframe,
      JSON.stringify(conditionTree ?? null),
      JSON.stringify(longConditionTree ?? null),
      JSON.stringify(shortConditionTree ?? null),
    ],
    queryFn: () =>
      fetchChartIndicators({
        symbol: priceSymbol as string,
        timeframe: timeframe as string,
        condition_tree: conditionTree,
        long_condition_tree: longConditionTree,
        short_condition_tree: shortConditionTree,
      }),
    enabled: chartEnabled,
  })

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5 font-semibold text-gray-200">
          {title}
          {symbol && timeframe && <span className="font-normal text-gray-400">{symbol}/{timeframe}</span>}
          {onBookmark && (
            <button
              type="button"
              disabled={isPending}
              onClick={onBookmark}
              title={isPending ? '保存中…' : isSaved ? 'クリックしてライブラリから削除' : '保存済みストラテジーに追加'}
              className={`disabled:opacity-40 transition-all ${
                isPending
                  ? 'grayscale animate-pulse opacity-60'
                  : isSaved
                    ? 'grayscale-0 opacity-100'
                    : 'grayscale opacity-40 hover:opacity-70'
              }`}
            >
              🔖
            </button>
          )}
          <FavoriteButton isFavorite={isFavorite} isPending={isPending} onClick={onFavorite} />
          {strategyId && (
            <button
              type="button"
              onClick={() => setShowPineScript(true)}
              title="TradingView(Pine Script)コードを生成"
              className="rounded border border-white/10 px-1.5 py-0.5 font-normal text-gray-300 hover:bg-white/10"
            >
              TradingViewコード
            </button>
          )}
          {showCompareComposite && (
            <>
              <label className="flex items-center gap-1 font-normal text-gray-300">
                <input type="checkbox" checked={isCompareChecked} onChange={onToggleCompare} />
                比較
              </label>
              <label className="flex items-center gap-1 font-normal text-gray-300">
                <input type="checkbox" checked={isCompositeChecked} onChange={onToggleComposite} />
                合成
              </label>
            </>
          )}
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
          (condTabContent ??
            (bestRow && (bestRow.condition_tree || longConditionTree || shortConditionTree) ? (
              <p className="whitespace-pre-wrap font-mono text-xs text-gray-300">
                {describeStrategyConditionJapaneseLines(bestRow, indicators).join('\n')}
              </p>
            ) : (
              <div className="text-sm text-gray-500">この行に条件ツリーがありません</div>
            )))}

        {tab === 'equity' && <EquityCurveChart points={displayResults?.equity_curve ?? []} symbol={symbol} />}
        {tab === 'drawdown' && <DrawdownChart points={displayResults?.equity_curve ?? []} symbol={symbol} />}
        {tab === 'chart' &&
          (priceSymbol && timeframe ? (
            <div style={{ height: 480 }}>
              <ChartPanel
                bars={priceQuery.data ?? []}
                trades={displayResults?.trade_log ?? []}
                symbol={priceSymbol}
                indicators={chartIndicatorsQuery.data?.indicators}
                indicatorInfos={indicators}
                defaultDirection={direction}
              />
            </div>
          ) : (
            <div className="text-sm text-gray-500">通貨/時間足が不明なため表示できません</div>
          ))}
        {tab === 'trades' && <TradeHistoryTable rows={tradesWithDirection} symbol={symbol} />}
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
          (paramsTabContent ??
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
            )))}
      </div>

      {showPineScript && strategyId && (
        <PineScriptModal strategyId={strategyId} onClose={() => setShowPineScript(false)} />
      )}
    </div>
  )
}
