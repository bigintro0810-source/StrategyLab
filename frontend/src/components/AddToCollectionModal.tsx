import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addStrategyToCollection, fetchStrategies, removeStrategyFromCollection, type Collection } from '../api'

interface Props {
  collection: Collection
  onClose: () => void
}

export default function AddToCollectionModal({ collection, onClose }: Props) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')

  const strategiesQuery = useQuery({ queryKey: ['strategies', 'all'], queryFn: fetchStrategies })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['collections'] })

  const addMutation = useMutation({
    mutationFn: (strategyId: string) => addStrategyToCollection(collection.id, strategyId),
    onSuccess: invalidate,
  })

  const removeMutation = useMutation({
    mutationFn: (strategyId: string) => removeStrategyFromCollection(collection.id, strategyId),
    onSuccess: invalidate,
  })

  const query = search.trim().toLowerCase()
  const strategies = (strategiesQuery.data ?? []).filter(
    (s) => query === '' || s.name.toLowerCase().includes(query),
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="glass-panel flex max-h-[80vh] w-full max-w-md flex-col rounded-2xl p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-100">「{collection.name}」にストラテジーを追加</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-200">
            ×
          </button>
        </div>
        <input
          type="text"
          placeholder="名前で検索"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="glass-input mb-3 flex-none rounded-lg px-2 py-1.5 text-sm"
        />
        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
          {strategies.length === 0 ? (
            <div className="p-4 text-center text-sm text-gray-500">
              {strategiesQuery.isLoading ? '読み込み中…' : 'ストラテジーがありません'}
            </div>
          ) : (
            strategies.map((s) => {
              const isIn = collection.strategy_ids.includes(s.id)
              return (
                <label
                  key={s.id}
                  className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-gray-200 hover:bg-white/5"
                >
                  <input
                    type="checkbox"
                    checked={isIn}
                    onChange={() => (isIn ? removeMutation.mutate(s.id) : addMutation.mutate(s.id))}
                  />
                  <span className="min-w-0 flex-1 truncate">{s.name}</span>
                  <span className="flex-none text-gray-500">
                    {s.symbol}/{s.timeframe}
                  </span>
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
