import { useState } from 'react'
import AddCandidateModal from './AddCandidateModal'
import AutoExplorationDetail, { type TabId } from './AutoExplorationDetail'
import type { CompositeCandidate } from '../compositeUtils'
import type { BacktestResults, IndicatorInfo, RankingRow } from '../types'

export interface StrategyTabData {
  rank: number
  name: string
  bestRow: RankingRow | undefined
  displayResults: BacktestResults | undefined
  isLoading: boolean
  error: string | null
  isFavorite: boolean
  isPending: boolean
  isCompareChecked: boolean
  isCompositeChecked: boolean
  isSaved: boolean
  // どのサブタブ(累積Pips/チャート/取引履歴...)を表示中か。App.tsxが
  // rank単位で持つ(AutoExplorationDetail.tsx参照 - 別画面へ移動して
  // このコンポーネント自体がアンマウントされても復元できるようにするため)。
  activeTab: TabId
}

interface Props {
  openTabs: StrategyTabData[]
  visibleRanks: number[]
  indicators: IndicatorInfo[]
  // 全タブ、この結果セット(1回のバックテスト実行=1つの通貨/時間足)で共通。
  timeframe: string
  onSelectTab: (rank: number) => void
  onCloseTab: (rank: number) => void
  onMergeTabs: (draggedRank: number, targetRank: number) => void
  onRemoveFromView: (rank: number) => void
  onRenameRow: (rank: number, name: string) => void
  onFavorite: (rank: number) => void
  onToggleCompare: (rank: number) => void
  onToggleComposite: (rank: number) => void
  onBookmark: (rank: number) => void
  onTabChange: (rank: number, tab: TabId) => void
  // 何も開いていない時の「ストラテジー詳細確認対象を追加」ピッカー(AddCandidateModal.tsx)
  // 用 - 比較/合成タブと同じ候補一覧・トグル関数をApp.tsx側から渡す。
  candidates: CompositeCandidate[]
  onToggleInput: (id: string) => void
}

const MAX_TABS = 20

// タブピル/表示中カード共通の名称: クリックではなくダブルクリックで編集に
// 入る(シングルクリックは既にタブ選択/ドラッグ開始に使われているため)。
function EditableName({
  rank,
  name,
  onRename,
  className,
}: {
  rank: number
  name: string
  onRename: (rank: number, name: string) => void
  className?: string
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(name)

  const commit = () => {
    setEditing(false)
    const trimmed = draft.trim()
    if (trimmed && trimmed !== name) onRename(rank, trimmed)
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          // IME変換確定のEnter(isComposing)はリネームの確定に使わない。
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) commit()
          if (e.key === 'Escape') {
            setDraft(name)
            setEditing(false)
          }
        }}
        className="w-28 rounded bg-black/30 px-1 py-0.5 text-xs text-gray-100"
      />
    )
  }

  return (
    <span
      title="ダブルクリックで名称を変更"
      onDoubleClick={(e) => {
        e.stopPropagation()
        setDraft(name)
        setEditing(true)
      }}
      className={className}
    >
      {name}
    </span>
  )
}

// Tabs opened from ランキング一覧 (see RankingTable's "名称" column / App.tsx's
// openTab) - clicking a tab shows it alone; dragging one tab onto another
// (either its pill in the tab bar, or its own currently-displayed card below)
// merges them into a side-by-side view (up to MAX_VISIBLE) instead of
// replacing it. Plain HTML5 drag-and-drop (no library in this repo does
// this - see project notes) - dataTransfer just carries the dragged rank as
// a string.
export default function StrategyDetailTabs({
  openTabs,
  visibleRanks,
  indicators,
  timeframe,
  onSelectTab,
  onCloseTab,
  onMergeTabs,
  onRemoveFromView,
  onRenameRow,
  onFavorite,
  onToggleCompare,
  onToggleComposite,
  onBookmark,
  onTabChange,
  candidates,
  onToggleInput,
}: Props) {
  const [showAddModal, setShowAddModal] = useState(false)

  // モーダル(position:fixed)は.glass-panel(backdrop-filter)の外側で
  // レンダリングする必要がある - backdrop-filterがfixed子要素の新しい
  // 包含ブロックを作ってしまい、モーダルが画面全体ではなくこのパネルの
  // 範囲内に切り詰められてしまうため(CompositeDetail.tsxで実際に踏んだ
  // 不具合と同じ)。さらに、モーダルはopenTabs有無の分岐の外側(常に評価
  // される側)に置く必要がある - 分岐の中だけにあると、1件目を追加した
  // 瞬間にopenTabsが空でなくなって別の分岐(タブ表示側)に切り替わり、
  // モーダルごとアンマウントされて2件目以降を連続して選べなくなる
  // (実際に踏んだ不具合: 「現在は1つずつしか追加できない」)。
  if (openTabs.length === 0) {
    return (
      <>
        <div className="glass-panel space-y-3 rounded-2xl p-4 text-sm text-gray-500">
          <div>ランキング一覧の行のチェックボックスを付けると、ここにストラテジー詳細タブが開きます(最大{MAX_TABS}個)。</div>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200 hover:bg-white/10"
          >
            + ストラテジー詳細確認対象を追加
          </button>
        </div>
        {showAddModal && (
          <AddCandidateModal
            title="ストラテジー詳細確認対象を追加"
            candidates={candidates}
            selectedIds={openTabs.map((t) => String(t.rank))}
            onToggle={onToggleInput}
            onClose={() => setShowAddModal(false)}
          />
        )}
      </>
    )
  }

  const visible = openTabs.filter((t) => visibleRanks.includes(t.rank))

  const handleDropOnto = (e: React.DragEvent, targetRank: number) => {
    e.preventDefault()
    const draggedRank = Number(e.dataTransfer.getData('text/plain'))
    if (!Number.isNaN(draggedRank)) onMergeTabs(draggedRank, targetRank)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1 rounded-2xl border border-white/10 bg-white/[0.03] p-1.5">
        <button
          type="button"
          onClick={() => setShowAddModal(true)}
          className="glass-input rounded-lg px-2 py-1 text-[11px] font-semibold text-gray-200 hover:bg-white/10"
        >
          + ストラテジー詳細確認対象を追加
        </button>
        {openTabs.map((t) => {
          const isVisible = visibleRanks.includes(t.rank)
          return (
            <div
              key={t.rank}
              draggable
              onDragStart={(e) => e.dataTransfer.setData('text/plain', String(t.rank))}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => handleDropOnto(e, t.rank)}
              onClick={() => onSelectTab(t.rank)}
              className={`flex cursor-pointer items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-semibold ${
                isVisible ? 'bg-purple-500/30 text-purple-100' : 'text-gray-400 hover:bg-white/5 hover:text-gray-200'
              }`}
            >
              <EditableName rank={t.rank} name={t.name} onRename={onRenameRow} />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onCloseTab(t.rank)
                }}
                className="text-gray-500 hover:text-red-400"
                title="タブを閉じる"
              >
                ×
              </button>
            </div>
          )
        })}
      </div>

      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: `repeat(${Math.max(visible.length, 1)}, minmax(0, 1fr))` }}
      >
        {visible.map((t) => (
          <div
            key={t.rank}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => handleDropOnto(e, t.rank)}
            className="glass-panel relative min-w-0 rounded-2xl p-3"
          >
            {/* 複数を並べて表示している間だけ、そのカードを並び表示から
                外すための×を出す(タブ自体は閉じない - タブバーやランキング
                一覧のチェックはそのまま)。1件だけ表示中は不要なので出さない。 */}
            {visible.length > 1 && (
              <button
                type="button"
                onClick={() => onRemoveFromView(t.rank)}
                title="この表示だけ閉じる"
                className="absolute right-2 top-2 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-white/10 text-xs text-gray-400 hover:bg-white/20 hover:text-red-400"
              >
                ×
              </button>
            )}
            <AutoExplorationDetail
              title={t.name}
              timeframe={timeframe}
              bestRow={t.bestRow}
              displayResults={t.displayResults}
              isRowLoading={t.isLoading}
              rowError={t.error}
              indicators={indicators}
              isFavorite={t.isFavorite}
              isPending={t.isPending}
              onFavorite={() => onFavorite(t.rank)}
              isCompareChecked={t.isCompareChecked}
              onToggleCompare={() => onToggleCompare(t.rank)}
              isCompositeChecked={t.isCompositeChecked}
              onToggleComposite={() => onToggleComposite(t.rank)}
              isSaved={t.isSaved}
              onBookmark={() => onBookmark(t.rank)}
              activeTab={t.activeTab}
              onTabChange={(tabId) => onTabChange(t.rank, tabId)}
            />
          </div>
        ))}
      </div>

      {showAddModal && (
        <AddCandidateModal
          title="ストラテジー詳細確認対象を追加"
          candidates={candidates}
          selectedIds={openTabs.map((t) => String(t.rank))}
          onToggle={onToggleInput}
          onClose={() => setShowAddModal(false)}
        />
      )}
    </div>
  )
}
