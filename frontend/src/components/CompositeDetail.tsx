import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { computeComposite, computeYearlyAnalysis, type CompositeCandidate, type CompositeInput } from '../compositeUtils'
import { deleteStrategy, fetchCompositeMonteCarlo, saveComposite, toggleStrategyFavorite } from '../api'
import { describeConditionTreeJapaneseLines } from '../conditionTreeUtils'
import AddCandidateModal from './AddCandidateModal'
import AutoExplorationDetail, { type TabId } from './AutoExplorationDetail'
import CompositeSaveDialog from './CompositeSaveDialog'
import type { BacktestResults, IndicatorInfo, RankingRow } from '../types'

export interface CompositeSavedEntry {
  id: string
  favorite: boolean
}

// 条件タブで対象を①②③...と番号付けするため(ユーザー要望:「①の条件と
// ②の条件と③の条件・・・のようにすべて記載すればよい」)。21件目以降は
// 単一文字の丸数字が無いので"(21)"のような表記にフォールバックする。
const CIRCLED_NUMBERS = [
  '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩',
  '⑪', '⑫', '⑬', '⑭', '⑮', '⑯', '⑰', '⑱', '⑲', '⑳',
]
function circledNumber(n: number): string {
  return CIRCLED_NUMBERS[n - 1] ?? `(${n})`
}

interface Props {
  inputs: CompositeInput[]
  // trade_logをまだ取得中(rerun/フェッチ待ち)のものがあれば伝える -
  // 合成結果自体は届いた分だけで計算するが、まだ足りないことを示す。
  pendingCount: number
  indicators: IndicatorInfo[]
  // どのサブタブを表示中か/直前に保存したエントリ(🔖チェック状態)は
  // App.tsx側が持つ(結果側/ライブラリ側それぞれ1つ) - このコンポーネント
  // 自身がuseStateで持つと、別画面へ移動してmainTab/subTabが変わった瞬間に
  // アンマウントされ、戻ってきた時に累積Pipsタブ/未保存状態にリセットされて
  // しまうため(AutoExplorationDetail.tsxで踏んだのと同じ不具合パターン)。
  activeTab: TabId
  onTabChange: (tab: TabId) => void
  savedEntry: CompositeSavedEntry | null
  onSavedEntryChange: (entry: CompositeSavedEntry | null) => void
  // 合成対象を追加するピッカー(AddCandidateModal.tsx)の候補一覧 - 結果側
  // (ランキング行)/ライブラリ側(保存済みストラテジー)のどちらもApp.tsx
  // 側で正規化して渡す。追加/削除は同じトグル関数(App.tsx::
  // toggleCompositeRank/toggleLibraryComposite)を使う - 既に選択済みの
  // idを渡せば削除、未選択のidを渡せば追加になる(チップの×ボタンと
  // ピッカーのチェックボックスの両方から呼ぶ)。
  candidates: CompositeCandidate[]
  onToggleInput: (id: string) => void
}

// ストラテジー詳細(AutoExplorationDetail)とほぼ同じ画面にするため、合成
// 結果(computeComposite())からRankingRow/BacktestResults相当の疑似データを
// 組み立てて同じコンポーネントに描画させる。symbolは常に"COMPOSITE"固定 -
// compositeUtils.tsが各トレードを合成時点で既にpips換算しているため、
// pipUtils.ts側でpip_size=1として扱わせ、toPips()による二重変換を防ぐ。
export default function CompositeDetail({
  inputs,
  pendingCount,
  indicators,
  activeTab: tab,
  onTabChange: setTab,
  savedEntry,
  onSavedEntryChange,
  candidates,
  onToggleInput,
}: Props) {
  const [dialog, setDialog] = useState<{ favorite: boolean } | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const queryClient = useQueryClient()

  // モンテカルロのクエリキー用 - 合成対象の組み合わせが変わったら別の
  // シミュレーション結果として扱う(保存済み表示のリセット自体はApp.tsx側
  // のtoggleCompositeRank/toggleLibraryCompositeで行う - チェックボックス
  // 操作の発生源で確実にリセットするため、こちら側では追わない)。
  const inputKey = inputs.map((i) => i.id).sort().join(',')

  const composite = computeComposite(inputs)
  const wins = composite.tradeLog.filter((t) => t.profit > 0).length

  const saveMutation = useMutation({
    mutationFn: (params: { name: string; favorite: boolean }) => {
      const metrics: Record<string, number> = {
        net_profit: composite.netProfitPips,
        profit_factor: composite.profitFactor,
        max_dd: composite.maxDdPips,
        win_rate: composite.winRate,
        trades: composite.trades,
        sharpe_ratio: composite.sharpeRatio,
        sortino_ratio: composite.sortinoRatio,
        cagr: composite.cagr,
        calmar_ratio: composite.calmarRatio,
      }
      if (composite.maxDdPips > 0) metrics.recovery_factor = composite.netProfitPips / composite.maxDdPips
      return saveComposite(
        params.name,
        params.favorite,
        composite.tradeLog,
        composite.equityCurve,
        metrics,
        inputs.map((i) => i.name),
      )
    },
    onSuccess: (result, params) => {
      onSavedEntryChange({ id: result.id, favorite: params.favorite })
      setDialog(null)
      setSaveError(null)
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
    },
    onError: (err) => {
      setSaveError(err instanceof Error ? err.message : '保存に失敗しました')
    },
  })

  // 既に🔖で保存済みの合成結果に対して⭐を押した時は、名前入力ダイアログを
  // 挟まず通常の行と同じ「その場でお気に入りを付け外し」にする(ユーザー
  // 要望: 「しおりにチェックが入っている状態で星を押したときにはダイアログ
  // ボックスは出現せずにそのままお気に入りに追加されるようにして」)。
  const favoriteToggleMutation = useMutation({
    mutationFn: (id: string) => toggleStrategyFavorite(id),
    onSuccess: (result) => {
      onSavedEntryChange({ id: result.id, favorite: result.favorite })
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
    },
  })

  // 既に🔖で保存済みの合成結果に対してもう一度🔖を押した時は、通常の行の
  // 🔖と同じ完全なon/offトグルにする(App.tsx::handleBookmark参照) -
  // ダイアログを挟まず、保存済みストラテジー(お気に入り含む)から削除する
  // (ユーザー要望:「2回目クリックしたときは保存済みストラテジーとお気に
  // 入りから消すアクションにして。ダイアログボックスはいらない」)。
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteStrategy(id),
    onSuccess: () => {
      onSavedEntryChange(null)
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
    },
  })

  // モンテカルロは1000回のシャッフルを毎回サーバーへ投げるので、タブを
  // 開いた時だけ取得する(AutoExplorationDetail.tsxのチャートタブと同じ
  // 節約方針)。
  const mcQuery = useQuery({
    queryKey: ['composite-monte-carlo', inputKey, composite.trades],
    queryFn: () => fetchCompositeMonteCarlo(composite.tradeLog),
    enabled: tab === 'mc' && composite.trades > 0,
  })

  if (inputs.length === 0 && pendingCount === 0) {
    return (
      // モーダル(position:fixed)は.glass-panel(backdrop-filter)の外側で
      // レンダリングする必要がある - backdrop-filterがfixed子要素の新しい
      // 包含ブロックを作ってしまい、モーダルが画面全体ではなくこのパネルの
      // 範囲内に切り詰められてしまうため(実際に踏んだ不具合)。
      <>
        <div className="glass-panel space-y-3 rounded-2xl p-4 text-sm text-gray-500">
          <div>
            「合成」のチェックボックスを付けるか、下のボタンから合成対象を追加すると、選んだストラテジーをまとめて1つの資金曲線として合成した結果がここに表示されます。
          </div>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200 hover:bg-white/10"
          >
            + 合成対象を追加
          </button>
        </div>
        {showAddModal && (
          <AddCandidateModal
            title="合成対象を追加"
            candidates={candidates}
            selectedIds={inputs.map((i) => i.id)}
            onToggle={onToggleInput}
            onClose={() => setShowAddModal(false)}
          />
        )}
      </>
    )
  }

  const bestRow: RankingRow = {
    rank: 0,
    trades: composite.trades,
    wins,
    losses: composite.trades - wins,
    win_rate: composite.winRate,
    net_profit: composite.netProfitPips,
    profit_factor: composite.profitFactor,
    max_dd: composite.maxDdPips,
    expected_value: composite.expectedValuePips,
    recovery_factor: composite.maxDdPips > 0 ? composite.netProfitPips / composite.maxDdPips : NaN,
    sharpe_ratio: composite.sharpeRatio,
    sortino_ratio: composite.sortinoRatio,
    cagr: composite.cagr,
    calmar_ratio: composite.calmarRatio,
    rr: NaN,
    symbol: 'COMPOSITE',
  }

  const displayResults: BacktestResults = {
    ranking_total: [],
    equity_curve: composite.equityCurve,
    trade_log: composite.tradeLog,
    monte_carlo_summary: mcQuery.data ?? [],
    yearly_analysis: computeYearlyAnalysis(composite.tradeLog),
    monthly_analysis: [],
    stability_analysis: [],
  }

  // チャートタブは実際の価格データが要る(symbol="COMPOSITE"には存在
  // しない)ので、対象全てが同じ通貨/時間足の時だけ実シンボルを渡す
  // (AutoExplorationDetail.tsxのchartSymbolで、StatsPanel等が使うpips
  // 換算用のsymbol="COMPOSITE"とは別に上書きできる)。混在時はチャート
  // タブ側の「通貨/時間足が不明なため表示できません」に委ねる。
  const chartSymbol = inputs.length > 0 && inputs.every((i) => i.symbol === inputs[0].symbol) ? inputs[0].symbol : undefined
  const chartTimeframe =
    inputs.length > 0 && inputs.every((i) => i.timeframe === inputs[0].timeframe) ? inputs[0].timeframe : undefined

  // 合成は複数ストラテジーの組み合わせで単一の条件ツリー/パラメータを
  // 持たないため、AutoExplorationDetail.tsxの条件/パラメータタブは対象
  // ごとの一覧に差し替える(showCompareComposite同様、合成専用の表示)。
  const condTabContent = (
    <div className="space-y-3">
      {inputs.map((input, i) => (
        <div key={input.id}>
          <div className="mb-1 text-xs font-semibold text-gray-300">
            {circledNumber(i + 1)} {input.name}
          </div>
          {input.conditionTree ? (
            <p className="whitespace-pre-wrap font-mono text-xs text-gray-400">
              {describeConditionTreeJapaneseLines(input.conditionTree, indicators).join('\n')}
            </p>
          ) : (
            <div className="text-xs text-gray-500">条件ツリーがありません</div>
          )}
        </div>
      ))}
    </div>
  )

  const paramsTabContent = (
    <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
      {inputs.map((input) => (
        <div key={input.id} className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
          <div className="text-xs text-gray-400">{input.name}</div>
          <div className="font-mono text-gray-100">
            {input.symbol ?? '-'}/{input.timeframe ?? '-'}
            {input.direction && ` (${input.direction === 'long' ? 'Long' : 'Short'})`}
          </div>
        </div>
      ))}
    </div>
  )

  const defaultName = `合成_${inputs.map((i) => i.name).join('+')}`.slice(0, 60)

  return (
    <div className="space-y-2">
      <div className="glass-panel rounded-2xl p-3">
        <div className="mb-1.5 flex items-center justify-between">
          <div className="text-xs font-semibold text-gray-200">合成対象({inputs.length}件)</div>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="glass-input rounded-lg px-2 py-1 text-[11px] font-semibold text-gray-200 hover:bg-white/10"
          >
            + 合成対象を追加
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5 text-xs text-gray-300">
          {inputs.map((input) => (
            <span key={input.id} className="flex items-center gap-1 rounded-full bg-white/5 px-2 py-0.5">
              <span>
                {input.name}
                {input.symbol && input.timeframe && (
                  <span className="text-gray-500">
                    {' '}
                    ({input.symbol}/{input.timeframe})
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={() => onToggleInput(input.id)}
                title="合成対象から外す"
                className="text-gray-500 hover:text-red-400"
              >
                ×
              </button>
            </span>
          ))}
          {pendingCount > 0 && (
            <span className="rounded-full bg-white/5 px-2 py-0.5 text-gray-500">読み込み中×{pendingCount}</span>
          )}
        </div>
      </div>

      <AutoExplorationDetail
        title="合成"
        timeframe={chartTimeframe}
        chartSymbol={chartSymbol}
        condTabContent={condTabContent}
        paramsTabContent={paramsTabContent}
        displayResults={displayResults}
        bestRow={bestRow}
        isRowLoading={false}
        rowError={null}
        indicators={indicators}
        isFavorite={savedEntry?.favorite ?? false}
        isPending={saveMutation.isPending || favoriteToggleMutation.isPending || deleteMutation.isPending}
        onFavorite={() => {
          if (savedEntry) {
            favoriteToggleMutation.mutate(savedEntry.id)
            return
          }
          setSaveError(null)
          setDialog({ favorite: true })
        }}
        isCompareChecked={false}
        onToggleCompare={() => {}}
        isCompositeChecked={false}
        onToggleComposite={() => {}}
        isSaved={savedEntry != null}
        onBookmark={() => {
          if (savedEntry) {
            deleteMutation.mutate(savedEntry.id)
            return
          }
          setSaveError(null)
          setDialog({ favorite: false })
        }}
        showCompareComposite={false}
        activeTab={tab}
        onTabChange={setTab}
      />

      {dialog && (
        <CompositeSaveDialog
          defaultName={defaultName}
          isSaving={saveMutation.isPending}
          error={saveError}
          onSave={(name) => saveMutation.mutate({ name, favorite: dialog.favorite })}
          onClose={() => setDialog(null)}
        />
      )}

      {showAddModal && (
        <AddCandidateModal
          title="合成対象を追加"
          candidates={candidates}
          selectedIds={inputs.map((i) => i.id)}
          onToggle={onToggleInput}
          onClose={() => setShowAddModal(false)}
        />
      )}
    </div>
  )
}
