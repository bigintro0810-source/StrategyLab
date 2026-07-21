import { useRef, useState } from 'react'
import { ascendingIsBetter, buildMetricColumns, passesFilters, type MetricColumn, type MetricRowLike } from '../rankingColumns'
import FavoriteButton from './FavoriteButton'
import type { IndicatorInfo, RankingRow } from '../types'

interface RowMeta {
  isChecked: boolean
  isReverseChecked: boolean
  // 既にこの行から反転を作成済み(このセッション中)。反転チェックボックス
  // の代わりに白塗りの印を出し、操作できないようにする(App.tsx参照)。
  isReverseCreated: boolean
  isSaved: boolean
  isFavorite: boolean
  isPending: boolean
}

interface Props {
  rows: RankingRow[]
  selectedRank?: number | null
  jobId: string | null
  names: Record<number, string>
  rowMeta: Record<number, RowMeta>
  onRenameRow: (rank: number, name: string) => void
  onToggleChecked: (rank: number) => void
  onToggleReverse: (rank: number) => void
  // 「反転ストラテジー」タブ自身の一覧ではこの列を出さない(すでに反転済みの
  // 結果を並べているだけなので、再反転する意味がない)。
  showReverseColumn?: boolean
  onBookmark: (rank: number) => void
  onFavorite: (rank: number) => void
  indicators: IndicatorInfo[]
  // ランキング全体が1回のバックテスト実行(=1つの通貨/時間足)分なので、行
  // 毎ではなくこの結果セット全体で共通の値としてApp.tsxから渡す(行データ
  // 自体は自分のsymbolしか持たない - main.pyがtimeframeを候補ごとに
  // echo-backしていないため)。ライブラリ画面の「通貨/時間足」列と揃える。
  timeframe: string
  // 画面に収まる固定高さの枠内で自分だけスクロールする(親のResultsScreen
  // が高さを決める)。ストラテジー詳細タブと行き来するとこのコンポーネント
  // 自体がアンマウント/再マウントされ、DOM自身のscrollTopは失われるため、
  // 常に生きているApp.tsx側のrefにスクロール位置を持たせ、再マウント時の
  // ref callbackで復元・継続記録する。
  scrollTopRef: React.MutableRefObject<number>
}

// 「条件」は文字列で数値ソートが効かないため並び替えを禁止する。「名称」
// (キーはrank、セルはNameTextで描画)は文字列として個別に比較する
// (下のsorted参照)。
const UNSORTABLE_KEYS: (keyof RankingRow)[] = ['symbol', 'condition_tree']

// 名称・通貨/時間足列(専用セルで描画)だけこの画面固有 - 残りの指標列は
// ライブラリ画面と共通のbuildMetricColumns(rankingColumns.ts)から取る。
function buildColumns(indicators: IndicatorInfo[]): MetricColumn[] {
  return [
    { key: 'rank', label: '名称' },
    { key: 'symbol', label: '通貨/時間足' },
    ...buildMetricColumns(indicators),
  ]
}

// A genetic search that's converged (many generations, small population)
// legitimately produces many literal clones near the top - elitism carries
// the same winner forward unchanged, and mutation/crossover of a converged
// population often regenerates it. Showing the same strategy 10 times in
// the ranking isn't useful information, so rows whose entire result
// (metrics + condition tree) matches an earlier row are collapsed to the
// first (best-ranked) occurrence. Keyed on results, not on rank/param_id -
// two DIFFERENT structures that happen to trade identically are just as
// redundant to show twice as two copies of the same structure.
const DEDUP_METRIC_FIELDS: (keyof RankingRow)[] = [
  'net_profit',
  'profit_factor',
  'max_dd',
  'win_rate',
  'trades',
  'expected_value',
  'sharpe_ratio',
]

function resultKey(row: RankingRow): string {
  const metricPart = DEDUP_METRIC_FIELDS.map((f) => row[f]).join('|')
  const treePart = row.condition_tree ? JSON.stringify(row.condition_tree) : ''
  return `${metricPart}::${treePart}`
}

// 名称セル: クリックでインライン編集できる名称のみ(詳細/比較/合成の
// チェックボックスと🔖/⭐は専用の列に分離済み - renderCells参照)。
function NameText({
  rank,
  name,
  onRename,
}: {
  rank: number
  name: string
  onRename: (rank: number, name: string) => void
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
        className="glass-input w-32 rounded px-1 py-0.5 text-xs"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          // IME変換確定のEnter(isComposing)はリネームの確定に使わない -
          // 日本語入力中に変換確定のEnterを押しただけで未完成の文字列が
          // 送信されてしまうのを防ぐ。
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

export default function RankingTable({
  rows,
  selectedRank,
  jobId,
  names,
  rowMeta,
  onRenameRow,
  onToggleChecked,
  onToggleReverse,
  showReverseColumn = true,
  onBookmark,
  onFavorite,
  indicators,
  scrollTopRef,
  timeframe,
}: Props) {
  const [sortKey, setSortKey] = useState<keyof RankingRow>('profit_factor')
  const [sortAsc, setSortAsc] = useState(false)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const scrollElRef = useRef<HTMLDivElement | null>(null)

  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  const columns = buildColumns(indicators)

  const handleSort = (key: keyof RankingRow) => {
    if (UNSORTABLE_KEYS.includes(key)) return
    if (key === sortKey) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      // 初回クリックは「良い順」で表示する - ほとんどの指標は大きい方が
      // 良い(降順)が、DDだけ小さい方が良い(昇順)。名称は良し悪しが無い
      // ので素直にA→Z(昇順)から始める。
      setSortAsc(key === 'rank' ? true : ascendingIsBetter(String(key)))
    }
  }

  const deduped = (() => {
    const seen = new Set<string>()
    const out: RankingRow[] = []
    for (const row of rows) {
      const key = resultKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(row)
    }
    return out
  })()
  const duplicateCount = rows.length - deduped.length

  const filteredRows = deduped.filter((row) => passesFilters(row as unknown as MetricRowLike, filters, columns))

  const sorted = filteredRows.slice().sort((a, b) => {
    if (sortKey === 'rank') {
      const an = names[Number(a.rank)] ?? `Strat${Number(a.rank)}`
      const bn = names[Number(b.rank)] ?? `Strat${Number(b.rank)}`
      const cmp = an.localeCompare(bn)
      return sortAsc ? cmp : -cmp
    }
    const av = Number(a[sortKey])
    const bv = Number(b[sortKey])
    if (Number.isNaN(av) || Number.isNaN(bv)) return 0
    return sortAsc ? av - bv : bv - av
  })

  const emptyMeta: RowMeta = {
    isChecked: false,
    isReverseChecked: false,
    isReverseCreated: false,
    isSaved: false,
    isFavorite: false,
    isPending: false,
  }

  const renderCells = (row: RankingRow) => {
    const rank = Number(row.rank)
    return columns.map((col) => {
      if (col.key === 'rank') {
        return (
          <td key="rank" className="whitespace-nowrap px-1 py-1">
            <NameText rank={rank} name={names[rank] ?? `Strat${rank}`} onRename={onRenameRow} />
          </td>
        )
      }
      if (col.key === 'symbol') {
        // 反転ストラテジー一覧はライブラリ由来の複数通貨/時間足が混ざり得る
        // ため、行自身がtimeframeを持っていればそちらを優先する(通常の
        // ランキング一覧は1回のバックテスト=1つの通貨/時間足なので、行に
        // timeframeが無く共通propにフォールバックする)。
        return (
          <td key="symbol" className="whitespace-nowrap px-1 py-1 text-gray-300">
            {row.symbol as string}/{(row.timeframe as string | undefined) ?? timeframe}
          </td>
        )
      }
      const raw = row[col.key]
      const text = col.format ? col.format(raw, row) : String(raw ?? '')
      const colorClass = col.colorClass ? col.colorClass(raw) : ''
      return (
        <td
          key={String(col.key)}
          title={col.key === 'condition_tree' ? text : undefined}
          className={
            col.key === 'condition_tree'
              ? `max-w-[220px] truncate ${col.headerPadLeft ?? 'pl-1'} pr-1 py-1 font-mono text-[11px] text-gray-400`
              : `whitespace-nowrap px-1 py-1 ${col.numeric ? 'text-right' : ''} ${colorClass}`
          }
        >
          {text}
        </td>
      )
    })
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {duplicateCount > 0 && (
        <div className="mb-1 flex-none px-1 text-[11px] text-gray-500">
          {`同一の結果が${duplicateCount}件あったため非表示にしています(${deduped.length}件を表示)`}
        </div>
      )}
      {Object.values(filters).some((v) => v !== '') && (
        <div className="mb-1 flex-none px-1 text-[11px] text-gray-500">
          {`絞り込み条件により${filteredRows.length}/${deduped.length}件を表示`}
        </div>
      )}
      {/* 画面に収まる固定高さの枠内で自分だけスクロールする。ストラテジー
          詳細タブと行き来するとこのdiv自体がアンマウント/再マウントされる
          ため、マウント時にApp.tsx側の永続的なref(scrollTopRef)から
          scrollTopを復元し、アンマウント時(ref callbackがnullで呼ばれる
          瞬間)にその時点のscrollTopを同じrefへ書き戻す - DOM要素の
          プロパティは要素がツリーから外れた後も読めるので、scrollイベント
          の発火有無に頼らず確実に値を拾える。 */}
      <div
        ref={(el) => {
          if (el) {
            el.scrollTop = scrollTopRef.current
            scrollElRef.current = el
          } else if (scrollElRef.current) {
            scrollTopRef.current = scrollElRef.current.scrollTop
            scrollElRef.current = null
          }
        }}
        onScroll={(e) => {
          scrollTopRef.current = e.currentTarget.scrollTop
        }}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 z-10 bg-[#0c0d17]">
            <tr className="border-b border-white/10 text-gray-400">
              <th className="whitespace-nowrap px-1 py-1 font-medium">詳細</th>
              {showReverseColumn && <th className="whitespace-nowrap px-1 py-1 font-medium">反転</th>}
              <th className="px-1 py-1 font-medium" />
              <th className="px-1 py-1 font-medium" />
              {columns.map((col) => {
                const sortable = !UNSORTABLE_KEYS.includes(col.key)
                return (
                  <th
                    key={String(col.key)}
                    onClick={sortable ? () => handleSort(col.key) : undefined}
                    title={col.tooltip}
                    className={`select-none whitespace-nowrap ${col.headerPadLeft ?? 'pl-1'} pr-1 py-1 font-medium ${col.numeric ? 'text-right' : ''} ${
                      sortable ? 'cursor-pointer hover:text-gray-200' : ''
                    } ${sortKey === col.key ? 'bg-blue-500/30 text-blue-100' : ''}`}
                  >
                    {col.label}
                    {sortable && sortKey === col.key && <span className="ml-0.5">{sortAsc ? '▲' : '▼'}</span>}
                  </th>
                )
              })}
            </tr>
            <tr className="border-b border-white/10 bg-white/[0.02]">
              <th className="px-1 py-1" colSpan={showReverseColumn ? 4 : 3} />
              {columns.map((col) => (
                <th key={String(col.key)} className={`px-1 py-0.5 font-normal ${col.numeric ? 'text-right' : ''}`}>
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
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => {
              const rank = Number(row.rank)
              const meta = rowMeta[rank] ?? emptyMeta
              const disabled = jobId === null
              return (
                <tr
                  key={i}
                  className={`border-b border-white/5 hover:bg-white/[0.04] ${
                    selectedRank != null && rank === selectedRank ? 'bg-emerald-500/10' : ''
                  }`}
                >
                  <td className="px-1 py-1">
                    <input type="checkbox" checked={meta.isChecked} disabled={disabled} onChange={() => onToggleChecked(rank)} />
                  </td>
                  {showReverseColumn && (
                    <td className="px-1 py-1">
                      {meta.isReverseCreated ? (
                        <span
                          title="既にこの行から反転を作成済みです"
                          className="inline-block h-3 w-3 rounded-sm border border-white/30 bg-white"
                        />
                      ) : (
                        <input
                          type="checkbox"
                          checked={meta.isReverseChecked}
                          disabled={disabled}
                          onChange={() => onToggleReverse(rank)}
                          title="エントリー方向を反転して再検証する対象に含める"
                        />
                      )}
                    </td>
                  )}
                  <td className="px-1 py-1">
                    {/* 🔖はカラー絵文字グリフなのでCSSのtext-colorでは色が変わらない
                        (常にその絵文字本来の色で描画される) - grayscaleフィルター+
                        opacityで未保存=グレーアウト、保存済み=フルカラーを表現する
                        (⭐側はFavoriteButton.tsxに切り出し済み)。 */}
                    <button
                      type="button"
                      disabled={disabled || meta.isPending}
                      onClick={() => onBookmark(rank)}
                      title={meta.isPending ? '保存中…' : meta.isSaved ? 'クリックしてライブラリから削除' : '保存済みストラテジーに追加'}
                      className={`disabled:opacity-40 transition-all ${
                        meta.isPending
                          ? 'grayscale animate-pulse opacity-60'
                          : meta.isSaved
                            ? 'grayscale-0 opacity-100'
                            : 'grayscale opacity-40 hover:opacity-70'
                      }`}
                    >
                      🔖
                    </button>
                  </td>
                  <td className="px-1 py-1">
                    <FavoriteButton
                      isFavorite={meta.isFavorite}
                      isPending={meta.isPending}
                      disabled={disabled}
                      onClick={() => onFavorite(rank)}
                    />
                  </td>
                  {renderCells(row)}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
