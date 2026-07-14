import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addStrategyTags,
  deleteStrategy,
  fetchStrategiesFiltered,
  removeStrategyTag,
  renameStrategy,
  toggleStrategyFavorite,
} from '../api'
import FavoriteButton from './FavoriteButton'
import { buildMetricColumns, type MetricRowLike } from '../rankingColumns'
import type { IndicatorInfo, StrategyDetail } from '../types'

interface Props {
  favoritesOnly: boolean
  onLoad: (id: string) => void
  isLoading: boolean
  compareIds: string[]
  onToggleCompare: (id: string) => void
  onGoToCompare: () => void
  indicators: IndicatorInfo[]
  // ストラテジー詳細タブ(App.tsx側のlibraryOpenIds)に開いているid一覧。
  openIds: string[]
  onToggleChecked: (id: string) => void
  // 合成タブ(App.tsx側のlibraryCompositeIds)でチェックしたid一覧。
  compositeIds: string[]
  onToggleComposite: (id: string) => void
}

// entry.metrics(strategy_registry.pyのMETRIC_COLUMNS)はexpected_valueを
// 持たない(保存時点で未計算)ため、ランキング一覧と同じ定義
// (net_profit÷trades、engine/backtest_engine.py)でここで計算する。
function toMetricRow(entry: StrategyDetail): MetricRowLike {
  const m = entry.metrics
  const trades = Number(m.trades) || 0
  return {
    profit_factor: m.profit_factor,
    net_profit: m.net_profit,
    expected_value: trades > 0 ? Number(m.net_profit) / trades : 0,
    max_dd: m.max_dd,
    win_rate: m.win_rate,
    trades: m.trades,
    sharpe_ratio: m.sharpe_ratio,
    recovery_factor: m.recovery_factor,
    sortino_ratio: m.sortino_ratio,
    calmar_ratio: m.calmar_ratio,
    cagr: m.cagr,
    condition_tree: entry.params?.condition_tree ?? undefined,
    symbol: entry.symbol,
  }
}

// ランキング一覧(RankingTable.tsx)の「名称」セルと同じ見た目・操作:
// クリックで名称をインライン編集。詳細/比較/合成のチェックボックスと
// 🔖(常に保存済みなので押すとライブラリから削除)/⭐は専用の列に分離済み
// (renderの各<td>参照)。
function NameText({
  id,
  name,
  onRename,
}: {
  id: string
  name: string
  onRename: (id: string, name: string) => void
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
        className="glass-input w-32 rounded px-1 py-0.5 text-xs"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) commit()
          if (e.key === 'Escape') {
            setDraft(name)
            setEditing(false)
          }
        }}
      />
    )
  }

  return (
    <span
      className="cursor-pointer whitespace-nowrap hover:underline"
      title="クリックして名称を変更"
      onClick={() => {
        setDraft(name)
        setEditing(true)
      }}
    >
      {name}
    </span>
  )
}

export default function LibraryScreen({
  favoritesOnly,
  onLoad,
  isLoading,
  compareIds,
  onToggleCompare,
  onGoToCompare,
  indicators,
  openIds,
  onToggleChecked,
  compositeIds,
  onToggleComposite,
}: Props) {
  const queryClient = useQueryClient()
  const [tagDraft, setTagDraft] = useState<Record<string, string>>({})
  const [sortKey, setSortKey] = useState<string>('profit_factor')
  const [sortAsc, setSortAsc] = useState(false)

  const strategiesQuery = useQuery({
    queryKey: ['strategies', favoritesOnly],
    queryFn: () => fetchStrategiesFiltered(favoritesOnly),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['strategies'] })

  const favoriteMutation = useMutation({
    mutationFn: (id: string) => toggleStrategyFavorite(id),
    onSuccess: invalidate,
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameStrategy(id, name),
    onSuccess: invalidate,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteStrategy(id),
    onSuccess: invalidate,
  })

  const addTagMutation = useMutation({
    mutationFn: ({ id, tag }: { id: string; tag: string }) => addStrategyTags(id, [tag]),
    onSuccess: invalidate,
  })

  const removeTagMutation = useMutation({
    mutationFn: ({ id, tag }: { id: string; tag: string }) => removeStrategyTag(id, tag),
    onSuccess: invalidate,
  })

  const strategies = strategiesQuery.data ?? []
  const columns = buildMetricColumns(indicators)

  const handleSort = (key: string) => {
    if (key === 'condition_tree') return
    if (key === sortKey) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(true)
    }
  }

  const sorted = strategies
    .slice()
    .reverse()
    .sort((a, b) => {
      const av = Number(toMetricRow(a)[sortKey])
      const bv = Number(toMetricRow(b)[sortKey])
      if (Number.isNaN(av) || Number.isNaN(bv)) return 0
      return sortAsc ? av - bv : bv - av
    })

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-200">
          {favoritesOnly ? 'お気に入りの戦略' : '保存済みストラテジー'}
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
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/10 text-gray-400">
                <th className="whitespace-nowrap px-1 py-1 font-medium">詳細</th>
                <th className="whitespace-nowrap px-1 py-1 font-medium">比較</th>
                <th className="whitespace-nowrap px-1 py-1 font-medium">合成</th>
                <th className="px-1 py-1 font-medium" />
                <th className="px-1 py-1 font-medium" />
                <th className="whitespace-nowrap px-1 py-1 font-medium">名称</th>
                <th className="whitespace-nowrap px-1 py-1 font-medium">通貨/時間足</th>
                {columns.map((col) => (
                  <th
                    key={col.key}
                    onClick={col.key === 'condition_tree' ? undefined : () => handleSort(col.key)}
                    title={col.tooltip}
                    className={`select-none whitespace-nowrap px-1 py-1 font-medium ${
                      col.key === 'condition_tree' ? '' : 'cursor-pointer hover:text-gray-200'
                    } ${sortKey === col.key ? 'bg-blue-500/30 text-blue-100' : ''}`}
                  >
                    {col.label}
                    {sortKey === col.key && <span className="ml-0.5">{sortAsc ? '▲' : '▼'}</span>}
                  </th>
                ))}
                <th className="whitespace-nowrap px-1 py-1 font-medium">タグ</th>
                <th className="px-1 py-1 font-medium" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => {
                const row = toMetricRow(s)
                const isFavoritePending = favoriteMutation.isPending && favoriteMutation.variables === s.id
                return (
                  <tr key={s.id} className="border-b border-white/5 hover:bg-white/[0.04]">
                    <td className="px-1 py-1">
                      <input type="checkbox" checked={openIds.includes(s.id)} onChange={() => onToggleChecked(s.id)} />
                    </td>
                    <td className="px-1 py-1">
                      <input type="checkbox" checked={compareIds.includes(s.id)} onChange={() => onToggleCompare(s.id)} />
                    </td>
                    <td className="px-1 py-1">
                      <input
                        type="checkbox"
                        checked={compositeIds.includes(s.id)}
                        onChange={() => onToggleComposite(s.id)}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <button
                        type="button"
                        onClick={() => deleteMutation.mutate(s.id)}
                        title="クリックしてライブラリから削除"
                        className="grayscale-0 opacity-100 transition-all hover:opacity-70"
                      >
                        🔖
                      </button>
                    </td>
                    <td className="px-1 py-1">
                      <FavoriteButton
                        isFavorite={s.favorite}
                        isPending={isFavoritePending}
                        onClick={() => favoriteMutation.mutate(s.id)}
                      />
                    </td>
                    <td className="whitespace-nowrap px-1 py-1">
                      <NameText id={s.id} name={s.name} onRename={(id, name) => renameMutation.mutate({ id, name })} />
                    </td>
                    <td className="whitespace-nowrap px-1 py-1">
                      {s.symbol}/{s.timeframe}
                    </td>
                    {columns.map((col) => {
                      const raw = row[col.key]
                      const text = col.format ? col.format(raw, row) : String(raw ?? '')
                      const colorClass = col.colorClass ? col.colorClass(raw) : ''
                      return (
                        <td
                          key={col.key}
                          title={col.key === 'condition_tree' ? text : undefined}
                          className={
                            col.key === 'condition_tree'
                              ? 'max-w-[120px] truncate px-1 py-1 font-mono text-[11px] text-gray-400'
                              : `whitespace-nowrap px-1 py-1 ${colorClass}`
                          }
                        >
                          {text}
                        </td>
                      )
                    })}
                    <td className="px-1 py-1">
                      {/* 結果のランキング一覧と行の高さを揃えるため折り返させない
                          (タグが多い行だけ縦に伸びると表全体の行高が揃わなくなる) -
                          収まりきらない分はこのセル内だけ横スクロール。 */}
                      <div className="flex max-w-[70px] flex-nowrap items-center gap-1 overflow-x-auto">
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
                    <td className="px-1 py-1">
                      <button
                        type="button"
                        disabled={isLoading}
                        onClick={() => onLoad(s.id)}
                        className="whitespace-nowrap rounded-lg border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-gray-300 hover:bg-white/10 disabled:opacity-40"
                      >
                        読み込む
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
