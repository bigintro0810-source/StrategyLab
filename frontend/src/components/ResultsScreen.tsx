import RankingTable from './RankingTable'
import StrategyDetailTabs, { type StrategyTabData } from './StrategyDetailTabs'
import type { BacktestResults, IndicatorInfo } from '../types'

interface RowMeta {
  isChecked: boolean
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
  onBookmark: (rank: number) => void
  onFavorite: (rank: number) => void
  rankingScrollTopRef: React.MutableRefObject<number>
}

export default function ResultsScreen({
  subTab,
  results,
  strategyTabs,
  visibleRanks,
  indicators,
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
  onBookmark,
  onFavorite,
  rankingScrollTopRef,
}: Props) {
  if (subTab === 'detail') {
    return (
      <StrategyDetailTabs
        openTabs={strategyTabs}
        visibleRanks={visibleRanks}
        indicators={indicators}
        onSelectTab={onSelectTab}
        onCloseTab={onCloseTab}
        onMergeTabs={onMergeTabs}
        onRemoveFromView={onRemoveFromView}
        onRenameRow={onRenameRow}
        onFavorite={onFavorite}
      />
    )
  }

  // ナビバー(結果/ランキングタブ2段分、実測約90px)+外側p-4の上下パディング
  // 分を引いた高さにぴったり収め、この中だけでスクロールさせる(ページ全体
  // はスクロールしない)。
  return (
    <div className="glass-panel flex flex-col rounded-2xl p-4" style={{ height: 'calc(100vh - 122px)' }}>
      <div className="mb-3 flex-none text-sm font-semibold text-gray-200">ランキング一覧</div>
      <div className="min-h-0 flex-1">
        <RankingTable
          rows={results?.ranking_total ?? []}
          indicators={indicators}
          jobId={jobId}
          names={names}
          rowMeta={rowMeta}
          selectedRank={focusedRank}
          onRenameRow={onRenameRow}
          onToggleChecked={onToggleChecked}
          onBookmark={onBookmark}
          onFavorite={onFavorite}
          scrollTopRef={rankingScrollTopRef}
        />
      </div>
    </div>
  )
}
