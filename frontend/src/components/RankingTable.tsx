import { useRef, useState } from 'react'
import { describeConditionTreeJapanese } from '../conditionTreeUtils'
import { toPips } from '../pipUtils'
import FavoriteButton from './FavoriteButton'
import type { IndicatorInfo, RankingRow } from '../types'

interface RowMeta {
  isChecked: boolean
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
  onBookmark: (rank: number) => void
  onFavorite: (rank: number) => void
  indicators: IndicatorInfo[]
  // 画面に収まる固定高さの枠内で自分だけスクロールする(親のResultsScreen
  // が高さを決める)。ストラテジー詳細タブと行き来するとこのコンポーネント
  // 自体がアンマウント/再マウントされ、DOM自身のscrollTopは失われるため、
  // 常に生きているApp.tsx側のrefにスクロール位置を持たせ、再マウント時の
  // ref callbackで復元・継続記録する。
  scrollTopRef: React.MutableRefObject<number>
}

// + prefix on positive net_profit/expected_value so a quick scan of the
// column makes profitable vs unprofitable rows visually obvious without
// needing the color alone (color-blind friendly, and prints in black&white).
function signedFixed(v: unknown, digits: number): string {
  const n = Number(v)
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}`
}

// 「名称」「条件」はソートしても意味がない(名称は日付+連番、条件は文字列
// なので数値ソートが効かない)ため、この2列だけクリックでの並び替えを禁止する。
const UNSORTABLE_KEYS: (keyof RankingRow)[] = ['rank', 'condition_tree']

function buildColumns(
  indicators: IndicatorInfo[],
): {
  key: keyof RankingRow
  label: string
  tooltip?: string
  format?: (v: unknown, row: RankingRow) => string
  colorClass?: (v: unknown) => string
}[] {
  return [
    { key: 'rank', label: '名称' },
    {
      key: 'profit_factor',
      label: 'PF',
      tooltip: 'プロフィットファクター(総利益÷総損失。1より大きければ黒字)',
      format: (v) => Number(v).toFixed(2),
      colorClass: (v) => (Number(v) >= 1 ? 'text-emerald-400' : 'text-red-400'),
    },
    {
      key: 'net_profit',
      label: '純利益(pips)',
      format: (v, row) => signedFixed(toPips(Number(v), row.symbol as string), 1),
      colorClass: (v) => (Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400'),
    },
    {
      key: 'expected_value',
      label: '期待値(pips)',
      format: (v, row) => signedFixed(toPips(Number(v), row.symbol as string), 3),
      colorClass: (v) => (Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400'),
    },
    {
      key: 'max_dd',
      label: 'DD(pips)',
      tooltip: '最大ドローダウン(資金がピークからどれだけ落ち込んだか)',
      format: (v, row) => toPips(Number(v), row.symbol as string).toFixed(1),
    },
    { key: 'win_rate', label: '勝率(%)', format: (v) => Number(v).toFixed(1) },
    { key: 'trades', label: '取引数(回)' },
    {
      key: 'sharpe_ratio',
      label: 'Sharpe',
      tooltip: 'シャープレシオ: リターンの大きさを値動きのブレで割った指標。値動きが安定しているほど高い',
      format: (v) => Number(v).toFixed(2),
    },
    {
      key: 'recovery_factor',
      label: 'Recovery',
      tooltip: 'リカバリーファクター: 純利益÷最大ドローダウン。ドローダウンに対してどれだけ稼げたか',
      format: (v) => Number(v).toFixed(2),
    },
    {
      key: 'sortino_ratio',
      label: 'Sortino',
      tooltip: 'ソルティノレシオ: Sharpeに似ているが、下落方向のブレだけを見る指標(上振れは減点しない)',
      format: (v) => Number(v).toFixed(2),
    },
    {
      key: 'calmar_ratio',
      label: 'Calmar',
      tooltip: 'カルマーレシオ: 年率リターン÷最大ドローダウン',
      format: (v) => Number(v).toFixed(2),
    },
    { key: 'cagr', label: 'CAGR(%)', tooltip: '年率換算した成長率', format: (v) => (Number(v) * 100).toFixed(1) },
    {
      key: 'condition_tree',
      label: '条件',
      format: (v) => (v && typeof v === 'object' ? describeConditionTreeJapanese(v as Parameters<typeof describeConditionTreeJapanese>[0], indicators) : ''),
    },
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

// 名称セル: チェックボックス(ストラテジー詳細タブに表示)+クリックで
// インライン編集できる名称+🔖(保存済みストラテジー)+⭐(お気に入り)。
function NameCell({
  rank,
  name,
  meta,
  disabled,
  onRename,
  onToggleChecked,
  onBookmark,
  onFavorite,
}: {
  rank: number
  name: string
  meta: RowMeta
  disabled: boolean
  onRename: (rank: number, name: string) => void
  onToggleChecked: (rank: number) => void
  onBookmark: (rank: number) => void
  onFavorite: (rank: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(name)

  const commit = () => {
    setEditing(false)
    const trimmed = draft.trim()
    if (trimmed && trimmed !== name) onRename(rank, trimmed)
  }

  return (
    <div className="flex items-center gap-1.5">
      <input
        type="checkbox"
        checked={meta.isChecked}
        disabled={disabled}
        onChange={() => onToggleChecked(rank)}
      />
      {editing ? (
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
      ) : (
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
      )}
      {/* 🔖はカラー絵文字グリフなのでCSSのtext-colorでは色が変わらない(常に
          その絵文字本来の色で描画される) - Tailwindのtext-amber-400/
          text-gray-600切り替えでは未保存/保存済みの見分けが一切つかなかった
          実害があったため、ピクセル単位で効くgrayscaleフィルター+opacityで
          未保存=グレーアウト、保存済み=フルカラーを表現する(⭐側は
          FavoriteButton.tsxに切り出し済み)。 */}
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
      <FavoriteButton
        isFavorite={meta.isFavorite}
        isPending={meta.isPending}
        disabled={disabled}
        onClick={() => onFavorite(rank)}
      />
    </div>
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
  onBookmark,
  onFavorite,
  indicators,
  scrollTopRef,
}: Props) {
  const [sortKey, setSortKey] = useState<keyof RankingRow>('profit_factor')
  const [sortAsc, setSortAsc] = useState(false)
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
      setSortAsc(true)
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

  const sorted = deduped.slice().sort((a, b) => {
    const av = Number(a[sortKey])
    const bv = Number(b[sortKey])
    if (Number.isNaN(av) || Number.isNaN(bv)) return 0
    return sortAsc ? av - bv : bv - av
  })

  const renderCells = (row: RankingRow) => {
    const rank = Number(row.rank)
    return columns.map((col) => {
      if (col.key === 'rank') {
        return (
          <td key="rank" className="px-2 py-1">
            <NameCell
              rank={rank}
              name={names[rank] ?? `Strat${rank}`}
              meta={rowMeta[rank] ?? { isChecked: false, isSaved: false, isFavorite: false, isPending: false }}
              disabled={jobId === null}
              onRename={onRenameRow}
              onToggleChecked={onToggleChecked}
              onBookmark={onBookmark}
              onFavorite={onFavorite}
            />
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
              ? 'max-w-xs truncate px-2 py-1 font-mono text-[11px] text-gray-400'
              : `px-2 py-1 ${colorClass}`
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
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 z-10 bg-[#0c0d17]">
            <tr className="border-b border-white/10 text-gray-400">
              {columns.map((col) => {
                const sortable = !UNSORTABLE_KEYS.includes(col.key)
                return (
                  <th
                    key={String(col.key)}
                    onClick={sortable ? () => handleSort(col.key) : undefined}
                    title={col.tooltip}
                    className={`select-none whitespace-nowrap px-2 py-1 font-medium ${
                      sortable ? 'cursor-pointer hover:text-gray-200' : ''
                    } ${sortKey === col.key ? 'bg-blue-500/30 text-blue-100' : ''}`}
                  >
                    {col.label}
                    {sortable && sortKey === col.key && <span className="ml-0.5">{sortAsc ? '▲' : '▼'}</span>}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr
                key={i}
                className={`border-b border-white/5 hover:bg-white/[0.04] ${
                  selectedRank != null && Number(row.rank) === selectedRank ? 'bg-emerald-500/10' : ''
                }`}
              >
                {renderCells(row)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
