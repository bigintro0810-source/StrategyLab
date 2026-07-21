import RankingTable from './RankingTable'
import StrategyDetailTabs, { type StrategyTabData } from './StrategyDetailTabs'
import type { TabId } from './AutoExplorationDetail'
import type { CompositeCandidate } from '../compositeUtils'
import type { BacktestResults, IndicatorInfo } from '../types'

interface RowMeta {
  isChecked: boolean
  isReverseChecked: boolean
  isReverseCreated: boolean
  isSaved: boolean
  isFavorite: boolean
  isPending: boolean
}

interface Props {
  subTab: string
  results: BacktestResults | undefined
  strategyTabs: StrategyTabData[]
  visibleRanks: number[]
  indicators: IndicatorInfo[]
  timeframe: string
  onSelectTab: (rank: number) => void
  onCloseTab: (rank: number) => void
  onMergeTabs: (draggedRank: number, targetRank: number) => void
  onRemoveFromView: (rank: number) => void
  onRenameRow: (rank: number, name: string) => void
  jobId: string | null
  names: Record<number, string>
  rowMeta: Record<number, RowMeta>
  focusedRank: number | null
  onToggleChecked: (rank: number) => void
  onToggleReverse: (rank: number) => void
  onBookmark: (rank: number) => void
  onFavorite: (rank: number) => void
  onToggleCompare: (rank: number) => void
  onToggleComposite: (rank: number) => void
  rankingScrollTopRef: React.MutableRefObject<number>
  reverseCount: number
  onReverseExecute: () => void
  onDetailTabChange: (rank: number, tab: TabId) => void
  // 何も開いていない時の「ストラテジー詳細を確認」ピッカー(AddCandidateModal.tsx)用。
  detailCandidates: CompositeCandidate[]
  onToggleDetailInput: (id: string) => void
}

export default function ResultsScreen({
  subTab,
  results,
  strategyTabs,
  visibleRanks,
  indicators,
  timeframe,
  onSelectTab,
  onCloseTab,
  onMergeTabs,
  onRemoveFromView,
  onRenameRow,
  jobId,
  names,
  rowMeta,
  focusedRank,
  onToggleChecked,
  onToggleReverse,
  onBookmark,
  onFavorite,
  onToggleCompare,
  onToggleComposite,
  rankingScrollTopRef,
  reverseCount,
  onReverseExecute,
  onDetailTabChange,
  detailCandidates,
  onToggleDetailInput,
}: Props) {
  if (subTab === 'detail') {
    return (
      <StrategyDetailTabs
        openTabs={strategyTabs}
        visibleRanks={visibleRanks}
        indicators={indicators}
        timeframe={timeframe}
        onSelectTab={onSelectTab}
        onCloseTab={onCloseTab}
        onMergeTabs={onMergeTabs}
        onRemoveFromView={onRemoveFromView}
        onRenameRow={onRenameRow}
        onFavorite={onFavorite}
        onToggleCompare={onToggleCompare}
        onToggleComposite={onToggleComposite}
        onBookmark={onBookmark}
        onTabChange={onDetailTabChange}
        candidates={detailCandidates}
        onToggleInput={onToggleDetailInput}
      />
    )
  }

  const rows = results?.ranking_total ?? []

  // ナビバー(結果/ランキングタブ2段分、実測約90px)+外側p-4の上下パディング
  // 分を引いた高さにぴったり収め、この中だけでスクロールさせる(ページ全体
  // はスクロールしない)。
  return (
    <div className="glass-panel flex flex-col rounded-2xl p-4" style={{ height: 'calc(100vh - 122px)' }}>
      <div className="mb-3 flex flex-none items-center justify-between">
        <div className="flex items-baseline gap-2">
          <div className="text-sm font-semibold text-gray-200">ランキング</div>
          <div className="text-xs text-gray-500">新たな探索を行うとデータが削除されます</div>
        </div>
        {reverseCount > 0 && (
          <button
            type="button"
            onClick={onReverseExecute}
            className="glow-button rounded-lg px-3 py-1.5 text-xs font-semibold text-white"
          >
            選択した{reverseCount}件を反転実行
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1">
        <RankingTable
          rows={rows}
          indicators={indicators}
          jobId={jobId}
          names={names}
          rowMeta={rowMeta}
          selectedRank={focusedRank}
          onRenameRow={onRenameRow}
          onToggleChecked={onToggleChecked}
          onToggleReverse={onToggleReverse}
          onBookmark={onBookmark}
          onFavorite={onFavorite}
          scrollTopRef={rankingScrollTopRef}
          timeframe={timeframe}
        />
      </div>
    </div>
  )
}
