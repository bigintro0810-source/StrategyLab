import { useState } from 'react'
import type { CompositeCandidate } from '../compositeUtils'

interface Props {
  title: string
  candidates: CompositeCandidate[]
  selectedIds: string[]
  onToggle: (id: string) => void
  onClose: () => void
}

// 合成タブの「+ 合成対象を追加」/比較タブの「+ 比較対象を追加」から開く
// ピッカー - AddToCollectionModal.tsxと同じ「検索付き・チェックボックスで
// その場に追加/削除」パターン(確定ボタンを別に挟まない)。結果側
// (ランキング行)/ライブラリ側(保存済みストラテジー)のどちらの候補一覧も
// 同じ形に正規化して渡されるので、このコンポーネント自体は呼び出し元の
// タブや画面を意識しない(表示するタイトルだけpropsで受け取る)。
//
// 呼び出し側は、position:fixedのこのモーダルをbackdrop-filterを持つ祖先
// (.glass-panel)の外側でレンダリングすること - backdrop-filterはfixed
// 子要素の新しい包含ブロックを作ってしまい、モーダルが画面全体ではなく
// その祖先の範囲内に切り詰められてしまう(実際に踏んだ不具合)。
export default function AddCandidateModal({ title, candidates, selectedIds, onToggle, onClose }: Props) {
  const [search, setSearch] = useState('')

  const query = search.trim().toLowerCase()
  const filtered = candidates.filter((c) => query === '' || c.name.toLowerCase().includes(query))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="glass-panel flex max-h-[80vh] w-full max-w-md flex-col rounded-2xl p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-100">{title}</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-200">
            ×
          </button>
        </div>
        <input
          type="text"
          autoFocus
          placeholder="名前で検索"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="glass-input mb-3 flex-none rounded-lg px-2 py-1.5 text-sm"
        />
        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="p-4 text-center text-sm text-gray-500">候補がありません</div>
          ) : (
            filtered.map((c) => {
              const isIn = selectedIds.includes(c.id)
              return (
                <label
                  key={c.id}
                  className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-gray-200 hover:bg-white/5"
                >
                  <input type="checkbox" checked={isIn} onChange={() => onToggle(c.id)} />
                  <span className="min-w-0 flex-1 truncate">{c.name}</span>
                  {c.symbol && c.timeframe && (
                    <span className="flex-none text-gray-500">
                      {c.symbol}/{c.timeframe}
                    </span>
                  )}
                </label>
              )
            })
          )}
        </div>
        <div className="mt-3 flex flex-none justify-end">
          <button
            type="button"
            onClick={onClose}
            className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200"
          >
            閉じる
          </button>
        </div>
      </div>
    </div>
  )
}
