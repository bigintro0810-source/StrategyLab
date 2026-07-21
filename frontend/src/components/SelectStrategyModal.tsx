import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchStrategies } from '../api'

interface Props {
  onSelect: (id: string) => void
  onClose: () => void
}

// 検証タブの「対象ストラテジー」選択用 - AddToCollectionModal.tsxと似た
// 検索付き一覧だが、こちらはチェックボックスの多重選択ではなく1件クリックで
// 即選択・即クローズする単一選択ピッカー。
export default function SelectStrategyModal({ onSelect, onClose }: Props) {
  const [search, setSearch] = useState('')

  const strategiesQuery = useQuery({ queryKey: ['strategies', 'all'], queryFn: fetchStrategies })

  const query = search.trim().toLowerCase()
  const strategies = (strategiesQuery.data ?? []).filter(
    (s) => query === '' || s.name.toLowerCase().includes(query),
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="glass-panel flex max-h-[80vh] w-full max-w-md flex-col rounded-2xl p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-100">検証対象のストラテジーを選択</h2>
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
          {strategies.length === 0 ? (
            <div className="p-4 text-center text-sm text-gray-500">
              {strategiesQuery.isLoading ? '読み込み中…' : '保存済みストラテジーがありません'}
            </div>
          ) : (
            strategies.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => {
                  onSelect(s.id)
                  onClose()
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-gray-200 hover:bg-white/5"
              >
                <span className="min-w-0 flex-1 truncate">{s.name}</span>
                <span className="flex-none text-gray-500">
                  {s.symbol}/{s.timeframe}
                </span>
              </button>
            ))
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
