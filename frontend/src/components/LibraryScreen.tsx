import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addStrategyTags, fetchStrategiesFiltered, removeStrategyTag, toggleStrategyFavorite } from '../api'

interface Props {
  favoritesOnly: boolean
  onLoad: (id: string) => void
  isLoading: boolean
  compareIds: string[]
  onToggleCompare: (id: string) => void
  onGoToCompare: () => void
}

export default function LibraryScreen({
  favoritesOnly,
  onLoad,
  isLoading,
  compareIds,
  onToggleCompare,
  onGoToCompare,
}: Props) {
  const queryClient = useQueryClient()
  const [tagDraft, setTagDraft] = useState<Record<string, string>>({})

  const strategiesQuery = useQuery({
    queryKey: ['strategies', favoritesOnly],
    queryFn: () => fetchStrategiesFiltered(favoritesOnly),
  })

  const favoriteMutation = useMutation({
    mutationFn: (id: string) => toggleStrategyFavorite(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategies'] }),
  })

  const addTagMutation = useMutation({
    mutationFn: ({ id, tag }: { id: string; tag: string }) => addStrategyTags(id, [tag]),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategies'] }),
  })

  const removeTagMutation = useMutation({
    mutationFn: ({ id, tag }: { id: string; tag: string }) => removeStrategyTag(id, tag),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategies'] }),
  })

  const strategies = strategiesQuery.data ?? []

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-200">
          {favoritesOnly ? 'お気に入りの戦略' : '保存済み戦略'}
        </div>
        {compareIds.length > 0 && (
          <button
            type="button"
            onClick={onGoToCompare}
            disabled={compareIds.length < 2}
            className="glow-button rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
          >
            選択した{compareIds.length}件を比較
          </button>
        )}
      </div>

      {strategies.length === 0 ? (
        <div className="p-4 text-sm text-gray-500">
          {favoritesOnly ? 'お気に入りに登録された戦略がありません' : '保存された戦略がありません'}
        </div>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 text-gray-400">
                <th className="px-2 py-1 font-medium" />
                <th className="px-2 py-1 font-medium" />
                <th className="px-2 py-1 font-medium">名前</th>
                <th className="px-2 py-1 font-medium">通貨/時間足</th>
                <th className="px-2 py-1 font-medium">PF</th>
                <th className="px-2 py-1 font-medium">総利益</th>
                <th className="px-2 py-1 font-medium">DD</th>
                <th className="px-2 py-1 font-medium">タグ</th>
                <th className="px-2 py-1 font-medium" />
              </tr>
            </thead>
            <tbody>
              {strategies
                .slice()
                .reverse()
                .map((s) => (
                  <tr key={s.id} className="border-b border-white/5 hover:bg-white/[0.04]">
                    <td className="px-2 py-1">
                      <input
                        type="checkbox"
                        checked={compareIds.includes(s.id)}
                        onChange={() => onToggleCompare(s.id)}
                      />
                    </td>
                    <td className="px-2 py-1">
                      <button
                        type="button"
                        onClick={() => favoriteMutation.mutate(s.id)}
                        className={s.favorite ? 'text-amber-400' : 'text-gray-600 hover:text-gray-400'}
                        title="お気に入り切り替え"
                      >
                        ★
                      </button>
                    </td>
                    <td className="px-2 py-1">{s.name}</td>
                    <td className="px-2 py-1">
                      {s.symbol}/{s.timeframe}
                    </td>
                    <td className="px-2 py-1">{s.metrics.profit_factor?.toFixed(2) ?? '-'}</td>
                    <td className="px-2 py-1">{s.metrics.net_profit?.toFixed(1) ?? '-'}</td>
                    <td className="px-2 py-1">{s.metrics.max_dd?.toFixed(1) ?? '-'}</td>
                    <td className="px-2 py-1">
                      <div className="flex flex-wrap items-center gap-1">
                        {s.tags.map((tag) => (
                          <span
                            key={tag}
                            className="flex items-center gap-1 rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-gray-300"
                          >
                            {tag}
                            <button
                              type="button"
                              onClick={() => removeTagMutation.mutate({ id: s.id, tag })}
                              className="text-gray-500 hover:text-red-400"
                            >
                              ×
                            </button>
                          </span>
                        ))}
                        <input
                          type="text"
                          placeholder="+タグ"
                          value={tagDraft[s.id] ?? ''}
                          onChange={(e) => setTagDraft((d) => ({ ...d, [s.id]: e.target.value }))}
                          onKeyDown={(e) => {
                            const value = tagDraft[s.id]?.trim()
                            if (e.key === 'Enter' && value) {
                              addTagMutation.mutate({ id: s.id, tag: value })
                              setTagDraft((d) => ({ ...d, [s.id]: '' }))
                            }
                          }}
                          className="glass-input w-16 rounded px-1 py-0.5 text-[10px]"
                        />
                      </div>
                    </td>
                    <td className="px-2 py-1">
                      <button
                        type="button"
                        disabled={isLoading}
                        onClick={() => onLoad(s.id)}
                        className="rounded-lg border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-gray-300 hover:bg-white/10 disabled:opacity-40"
                      >
                        読み込む
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
