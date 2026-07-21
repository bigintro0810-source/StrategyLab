import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { renameStrategy, toggleStrategyFavorite } from '../api'
import FavoriteButton from './FavoriteButton'
import { ascendingIsBetter, buildMetricColumns, passesFilters, type MetricRowLike } from '../rankingColumns'
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
  indicators: IndicatorInfo[]
  // ストラテジー詳細タブ(App.tsx側のlibraryOpenIds)に開いているid一覧。
  openIds: string[]
  onToggleChecked: (id: string) => void
  // 保存済み/お気に入りでは完全削除、ユーザー定義タブでは「このタブから外す」
  // だけ(ストラテジー自体はライブラリに残る)- ダイアログの文言もこれで変える。
  deleteMode: 'delete' | 'remove'
  onDelete: (ids: string[]) => Promise<unknown>
  // ユーザー定義タブだけ: ヘッダーに"+"ボタンを出してストラテジー追加picker
  // (App.tsx側のAddToCollectionModal)を開く。
  onAddClick?: () => void
  // 反転(Reverse Strategy)。「反転ストラテジー」タブ自身の一覧ではこの列を
  // 出さない(すでに反転済みの結果を並べているだけなので再反転する意味がない)。
  showReverseColumn?: boolean
  reverseIds?: string[]
  onToggleReverse?: (id: string) => void
  onReverseExecute?: (ids: string[]) => void
  // 既にこの行から反転を作成済み(このセッション中)のid一覧。反転
  // チェックボックスの代わりに白塗りの印を出し、操作できないようにする。
  alreadyReversedIds?: string[]
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
    // 双方向運用(direction固定ではなくlong_condition_tree/short_condition_tree
    // を持つ)ストラテジーだとcondition_treeがnullのため、これらも渡さないと
    // 「条件」列が空欄になってしまう不具合があった(実際に踏んだ不具合)。
    long_condition_tree: entry.params?.long_condition_tree ?? undefined,
    short_condition_tree: entry.params?.short_condition_tree ?? undefined,
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
    // 名称が長い場合、列自体を広げず(他の列を圧迫せず)省略記号で切り詰め、
    // カーソルを当てるとネイティブのtitleツールチップで全文を表示する -
    // 常時表示する幅は「2026/07/16-0000000000」(21文字)が収まる程度で
    // 十分というユーザー指定に合わせる。
    <span
      className="block max-w-[21ch] cursor-pointer truncate hover:underline"
      title={name}
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
  indicators,
  openIds,
  onToggleChecked,
  deleteMode,
  onDelete,
  onAddClick,
  showReverseColumn = true,
  reverseIds = [],
  onToggleReverse,
  onReverseExecute,
  alreadyReversedIds = [],
}: Props) {
  const queryClient = useQueryClient()
  const [sortKey, setSortKey] = useState<string>('profit_factor')
  const [sortAsc, setSortAsc] = useState(false)
  const [filters, setFilters] = useState<Record<string, string>>({})
  // 一括削除用のチェック(詳細/反転とは別、削除専用)。
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
      // 良い(降順)が、DDだけ小さい方が良い(昇順)。名称は良し悪しが無い
      // ので素直にA→Z(昇順)から始める。
      setSortAsc(key === 'name' ? true : ascendingIsBetter(key))
    }
  }

  const filtered = strategies.filter((s) => passesFilters(toMetricRow(s), filters, columns))

  const sorted = filtered
    .slice()
    .reverse()
    .sort((a, b) => {
      if (sortKey === 'name') {
        const cmp = a.name.localeCompare(b.name)
        return sortAsc ? cmp : -cmp
      }
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
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-200">
          {title}
          {Object.values(filters).some((v) => v !== '') && (
            <span className="text-xs font-normal text-gray-500">
              (絞り込み条件により{filtered.length}/{strategies.length}件を表示)
            </span>
          )}
        </div>
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
          {showReverseColumn && reverseIds.length > 0 && (
            <button
              type="button"
              onClick={() => onReverseExecute?.(reverseIds)}
              className="glow-button rounded-lg px-3 py-1.5 text-xs font-semibold text-white"
            >
              選択した{reverseIds.length}件を反転実行
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
                {showReverseColumn && <th className="whitespace-nowrap px-1 py-1 font-medium">反転</th>}
                <th className="px-1 py-1 font-medium" />
                <th
                  onClick={() => handleSort('name')}
                  className={`select-none cursor-pointer whitespace-nowrap px-1 py-1 font-medium hover:text-gray-200 ${
                    sortKey === 'name' ? 'bg-blue-500/30 text-blue-100' : ''
                  }`}
                >
                  名称
                  {sortKey === 'name' && <span className="ml-0.5">{sortAsc ? '▲' : '▼'}</span>}
                </th>
                <th className="whitespace-nowrap px-1 py-1 font-medium">通貨/時間足</th>
                {columns.map((col) => (
                  <th
                    key={col.key}
                    onClick={col.key === 'condition_tree' ? undefined : () => handleSort(col.key)}
                    title={col.tooltip}
                    className={`select-none whitespace-nowrap ${col.headerPadLeft ?? 'pl-1'} pr-1 py-1 font-medium ${col.numeric ? 'text-right' : ''} ${
                      col.key === 'condition_tree' ? '' : 'cursor-pointer hover:text-gray-200'
                    } ${sortKey === col.key ? 'bg-blue-500/30 text-blue-100' : ''}`}
                  >
                    {col.label}
                    {sortKey === col.key && <span className="ml-0.5">{sortAsc ? '▲' : '▼'}</span>}
                  </th>
                ))}
                <th className="whitespace-nowrap px-1 py-1 font-medium">{deleteColumnLabel}</th>
              </tr>
              <tr className="border-b border-white/10 bg-white/[0.02]">
                <th className="px-1 py-1" colSpan={showReverseColumn ? 5 : 4} />
                {columns.map((col) => (
                  <th key={col.key} className={`px-1 py-0.5 font-normal ${col.numeric ? 'text-right' : ''}`}>
                    {col.filterable && (
                      <input
                        type="number"
                        value={filters[col.key] ?? ''}
                        onChange={(e) => setFilters((prev) => ({ ...prev, [col.key]: e.target.value }))}
                        placeholder={ascendingIsBetter(col.key) ? '以下' : '以上'}
                        title={`${col.label} ${ascendingIsBetter(col.key) ? '以下' : '以上'}で絞り込み`}
                        className="glass-input w-14 rounded px-1 py-0.5 text-[10px]"
                      />
                    )}
                  </th>
                ))}
                <th className="px-1 py-1" />
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
                    {showReverseColumn && (
                      <td className="px-1 py-1">
                        {alreadyReversedIds.includes(s.id) ? (
                          <span
                            title="既にこの行から反転を作成済みです"
                            className="inline-block h-3 w-3 rounded-sm border border-white/30 bg-white"
                          />
                        ) : (
                          <input
                            type="checkbox"
                            checked={reverseIds.includes(s.id)}
                            onChange={() => onToggleReverse?.(s.id)}
                            title="エントリー方向を反転して再検証する対象に含める"
                          />
                        )}
                      </td>
                    )}
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
                              ? `max-w-[160px] truncate ${col.headerPadLeft ?? 'pl-1'} pr-1 py-1 font-mono text-[11px] text-gray-400`
                              : `whitespace-nowrap px-1 py-1 ${col.numeric ? 'text-right' : ''} ${colorClass}`
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
