import { useState } from 'react'
import AddCandidateModal from './AddCandidateModal'
import AutoExplorationDetail, { type TabId } from './AutoExplorationDetail'
import type { CompositeCandidate } from '../compositeUtils'
import type { BacktestResults, IndicatorInfo, RankingRow } from '../types'

// ライブラリ版のストラテジー詳細タブ。StrategyDetailTabs.tsx(結果>ランキング
// 一覧側)とほぼ同じUI/挙動だが、あちらはRankingRow.rank(数値・ジョブ内で
// しか意味を持たない一時ID)をタブの識別子に使っているのに対し、こちらは
// 保存済みストラテジーの永続的な文字列id(strategy_registry.py発行)を使う -
// ドラッグ&ドロップのデータ受け渡し等で数値と文字列を無理に共用させると
// 型安全性が落ちるため、別コンポーネントとして分けている。
export interface LibraryTabData {
  id: string
  name: string
  timeframe: string
  bestRow: RankingRow | undefined
  displayResults: BacktestResults | undefined
  isLoading: boolean
  error: string | null
  isFavorite: boolean
  isCompareChecked: boolean
  isCompositeChecked: boolean
  // どのサブタブ(累積Pips/チャート/取引履歴...)を表示中か。App.tsxがid
  // 単位で持つ(AutoExplorationDetail.tsx参照 - 別画面へ移動してこの
  // コンポーネント自体がアンマウントされても復元できるようにするため)。
  activeTab: TabId
}

interface Props {
  openTabs: LibraryTabData[]
  visibleIds: string[]
  indicators: IndicatorInfo[]
  onSelectTab: (id: string) => void
  onCloseTab: (id: string) => void
  onMergeTabs: (draggedId: string, targetId: string) => void
  onRemoveFromView: (id: string) => void
  onRenameRow: (id: string, name: string) => void
  onFavorite: (id: string) => void
  onToggleCompare: (id: string) => void
  onToggleComposite: (id: string) => void
  onTabChange: (id: string, tab: TabId) => void
  // 何も開いていない時の「ストラテジー詳細確認対象を追加」ピッカー(AddCandidateModal.tsx)
  // 用 - 比較/合成タブと同じ候補一覧・トグル関数をApp.tsx側から渡す。
  candidates: CompositeCandidate[]
  onToggleInput: (id: string) => void
}

const MAX_TABS = 20

function EditableName({
  id,
  name,
  onRename,
  className,
}: {
  id: string
  name: string
  onRename: (id: string, name: string) => void
  className?: string
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(name)

  const commit = () => {
    setEditing(false)
    const trimmed = draft.trim()
    if (trimmed && trimmed !== name) onRename(id, trimmed)
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

export default function LibraryDetailTabs({
  openTabs,
  visibleIds,
  indicators,
  onSelectTab,
  onCloseTab,
  onMergeTabs,
  onRemoveFromView,
  onRenameRow,
  onFavorite,
  onToggleCompare,
  onToggleComposite,
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
          <div>保存済みストラテジー/お気に入りの行のチェックボックスを付けると、ここにストラテジー詳細タブが開きます(最大{MAX_TABS}個)。</div>
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
            selectedIds={openTabs.map((t) => t.id)}
            onToggle={onToggleInput}
            onClose={() => setShowAddModal(false)}
          />
        )}
      </>
    )
  }

  const visible = openTabs.filter((t) => visibleIds.includes(t.id))

  const handleDropOnto = (e: React.DragEvent, targetId: string) => {
    e.preventDefault()
    const draggedId = e.dataTransfer.getData('text/plain')
    if (draggedId) onMergeTabs(draggedId, targetId)
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
          const isVisible = visibleIds.includes(t.id)
          return (
            <div
              key={t.id}
              draggable
              onDragStart={(e) => e.dataTransfer.setData('text/plain', t.id)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => handleDropOnto(e, t.id)}
              onClick={() => onSelectTab(t.id)}
              className={`flex cursor-pointer items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-semibold ${
                isVisible ? 'bg-purple-500/30 text-purple-100' : 'text-gray-400 hover:bg-white/5 hover:text-gray-200'
              }`}
            >
              <EditableName id={t.id} name={t.name} onRename={onRenameRow} />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onCloseTab(t.id)
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
            key={t.id}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => handleDropOnto(e, t.id)}
            className="glass-panel relative min-w-0 rounded-2xl p-3"
          >
            {visible.length > 1 && (
              <button
                type="button"
                onClick={() => onRemoveFromView(t.id)}
                title="この表示だけ閉じる"
                className="absolute right-2 top-2 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-white/10 text-xs text-gray-400 hover:bg-white/20 hover:text-red-400"
              >
                ×
              </button>
            )}
            <AutoExplorationDetail
              title={t.name}
              strategyId={t.id}
              timeframe={t.timeframe}
              bestRow={t.bestRow}
              displayResults={t.displayResults}
              isRowLoading={t.isLoading}
              rowError={t.error}
              indicators={indicators}
              isFavorite={t.isFavorite}
              isPending={false}
              onFavorite={() => onFavorite(t.id)}
              isCompareChecked={t.isCompareChecked}
              onToggleCompare={() => onToggleCompare(t.id)}
              isCompositeChecked={t.isCompositeChecked}
              onToggleComposite={() => onToggleComposite(t.id)}
              activeTab={t.activeTab}
              onTabChange={(tabId) => onTabChange(t.id, tabId)}
            />
          </div>
        ))}
      </div>

      {showAddModal && (
        <AddCandidateModal
          title="ストラテジー詳細確認対象を追加"
          candidates={candidates}
          selectedIds={openTabs.map((t) => t.id)}
          onToggle={onToggleInput}
          onClose={() => setShowAddModal(false)}
        />
      )}
    </div>
  )
}
