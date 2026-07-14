import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { renameStrategy, toggleStrategyFavorite } from '../api'
import FavoriteButton from './FavoriteButton'
import { ascendingIsBetter, buildMetricColumns, type MetricRowLike } from '../rankingColumns'
import type { IndicatorInfo, StrategyDetail } from '../types'

interface Props {
  title: string
  emptyMessage: string
  // react-queryのキャッシュキー/取得関数を呼び出し側から渡す方式にして、
  // 保存済み/お気に入り(fetchStrategiesFiltered)とユーザー定義タブ
  // (コレクションのstrategy_idsで絞り込んだ一覧)の両方でこのコンポーネントを
  // そのまま使い回せるようにしている。
  queryKey: unknown[]
  queryFn: () => Promise<StrategyDetail[]>
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
  // 保存済み/お気に入りでは完全削除、ユーザー定義タブでは「このタブから外す」
  // だけ(ストラテジー自体はライブラリに残る)- ダイアログの文言もこれで変える。
  deleteMode: 'delete' | 'remove'
  onDelete: (ids: string[]) => Promise<unknown>
  // ユーザー定義タブだけ: ヘッダーに"+"ボタンを出してストラテジー追加picker
  // (App.tsx側のAddToCollectionModal)を開く。
  onAddClick?: () => void
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
// クリックで名称をインライン編集。詳細/比較/合成/削除のチェックボックスと
// ⭐は専用の列に分離済み(renderの各<td>参照)。
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
  title,
  emptyMessage,
  queryKey,
  queryFn,
  compareIds,
  onToggleCompare,
  onGoToCompare,
  indicators,
  openIds,
  onToggleChecked,
  compositeIds,
  onToggleComposite,
  deleteMode,
  onDelete,
  onAddClick,
}: Props) {
  const queryClient = useQueryClient()
  const [sortKey, setSortKey] = useState<string>('profit_factor')
  const [sortAsc, setSortAsc] = useState(false)
  // 一括削除用のチェック(詳細/比較/合成とは別、削除専用)。
  const [selectedForDelete, setSelectedForDelete] = useState<Set<string>>(new Set())
  const [deleteConfirm, setDeleteConfirm] = useState<{ ids: string[]; names: string[] } | null>(null)

  const toggleSelectedForDelete = (id: string) => {
    setSelectedForDelete((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const strategiesQuery = useQuery({ queryKey, queryFn })

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
    mutationFn: (ids: string[]) => onDelete(ids),
    onSuccess: () => {
      setSelectedForDelete(new Set())
      setDeleteConfirm(null)
    },
  })

  const strategies = strategiesQuery.data ?? []
  const columns = buildMetricColumns(indicators)

  const handleSort = (key: string) => {
    if (key === 'condition_tree') return
    if (key === sortKey) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      // 初回クリックは「良い順」で表示する - ほとんどの指標は大きい方が
      // 良い(降順)が、DDだけ小さい方が良い(昇順)。
      setSortAsc(ascendingIsBetter(key))
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

  const deleteColumnLabel = deleteMode === 'delete' ? '削除' : '除外'
  const deleteActionLabel = deleteMode === 'delete' ? '削除' : 'このタブから外す'

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-200">{title}</div>
        <div className="flex items-center gap-2">
          {onAddClick && (
            <button
              type="button"
              onClick={onAddClick}
              className="glow-button rounded-lg px-3 py-1.5 text-xs font-semibold text-white"
            >
              + ストラテジーを追加
            </button>
          )}
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
          {selectedForDelete.size > 0 && (
            <button
              type="button"
              onClick={() =>
                setDeleteConfirm({
                  ids: Array.from(selectedForDelete),
                  names: strategies.filter((s) => selectedForDelete.has(s.id)).map((s) => s.name),
                })
              }
              className="rounded-lg bg-red-500/80 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-500"
            >
              選択した{selectedForDelete.size}件を{deleteActionLabel}
            </button>
          )}
        </div>
      </div>

      {strategies.length === 0 ? (
        <div className="p-4 text-sm text-gray-500">{emptyMessage}</div>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/10 text-gray-400">
                <th className="whitespace-nowrap px-1 py-1 font-medium">詳細</th>
                <th className="whitespace-nowrap px-1 py-1 font-medium">比較</th>
                <th className="whitespace-nowrap px-1 py-1 font-medium">合成</th>
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
                <th className="whitespace-nowrap px-1 py-1 font-medium">{deleteColumnLabel}</th>
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
                              ? 'max-w-[160px] truncate px-1 py-1 font-mono text-[11px] text-gray-400'
                              : `whitespace-nowrap px-1 py-1 ${colorClass}`
                          }
                        >
                          {text}
                        </td>
                      )
                    })}
                    <td className="px-1 py-1">
                      <input
                        type="checkbox"
                        checked={selectedForDelete.has(s.id)}
                        onChange={() => toggleSelectedForDelete(s.id)}
                        title={`一括${deleteActionLabel}の対象に含める`}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <div className="glass-panel w-full max-w-sm rounded-2xl p-5">
            <h2 className="text-sm font-semibold text-gray-100">
              {deleteMode === 'delete'
                ? deleteConfirm.ids.length === 1
                  ? '本当に削除しますか?'
                  : `選択した${deleteConfirm.ids.length}件を本当に削除しますか?`
                : deleteConfirm.ids.length === 1
                  ? 'このタブから外しますか?'
                  : `選択した${deleteConfirm.ids.length}件をこのタブから外しますか?`}
            </h2>
            <p className="mt-2 max-h-32 overflow-y-auto text-xs leading-relaxed text-gray-400">
              {deleteConfirm.names.join('、')}
            </p>
            {deleteMode === 'delete' && <p className="mt-2 text-xs text-red-300">この操作は取り消せません。</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteConfirm(null)}
                disabled={deleteMutation.isPending}
                className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200 disabled:opacity-40"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(deleteConfirm.ids)}
                disabled={deleteMutation.isPending}
                className="rounded-lg bg-red-500/80 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-500 disabled:opacity-40"
              >
                {deleteMutation.isPending ? '処理中...' : deleteActionLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
