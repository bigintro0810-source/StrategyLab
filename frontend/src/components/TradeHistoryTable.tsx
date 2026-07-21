import { pipsDecimals, toPips } from '../pipUtils'
import type { TradeRow } from '../types'

interface Props {
  rows: TradeRow[]
  symbol: string | undefined
}

interface Column {
  key: keyof TradeRow
  label: string
  format?: (v: unknown) => string
  numeric?: boolean
  // 直前の列との間隔(既定はpx-2相当の詰まった間隔) - 「方向-損益Pips」は
  // 3文字分、それ以外(損益Pips↔エントリー時刻、エントリー価格↔決済時刻)は
  // 8文字分で揃える。padding-leftだけで列間の間隔を作る(右側は常に0)ことで、
  // 指定の間隔をそのまま実現できる。
  padLeft?: string
  // エントリー時刻-エントリー価格/決済時刻-決済価格の間隔は、間に立つ列
  // (エントリー価格/決済価格)側のpadLeftではなく、直前の時刻列のヘッダー
  // 側だけに右パディングを付けて管理する - table-layout: fixedを使わない
  // 表では列の実際の幅はその列の中で最大のセル(ヘッダー含む)に揃うため、
  // ヘッダーだけに広い右パディングを付ければ全行がその幅に自動的にそろい、
  // 各行ごとにpadLeftを付け直す必要がない。
  headerPadRight?: string
}

const GAP_DIRECTION_PROFIT = 'pl-[3.5ch]'
const GAP_WIDE = 'pl-[8ch]'
// 全角文字は1文字=1em換算(全角グリフはほぼどのフォントでも正方形にデザ
// インされているため)。決済時刻-決済価格だけ、そこから半角1/2文字分
// (0.5ch)だけさらに広げる指定なので、calc()でem/chを混在させる
// (Tailwindの任意値はスペースを書けないため、_(アンダースコア)で表す)。
const HEADER_GAP_ENTRY = 'pr-[4em]'
const HEADER_GAP_EXIT = 'pr-[calc(7em_+_0.5ch)]'

const BASE_COLUMNS_WITHOUT_PROFIT: Column[] = [
  { key: 'entry_time', label: 'エントリー時刻', padLeft: GAP_WIDE, headerPadRight: HEADER_GAP_ENTRY },
  {
    key: 'entry_price',
    label: 'エントリー価格',
    format: (v) => Number(v).toFixed(3),
    numeric: true,
    padLeft: 'pl-0',
  },
  { key: 'exit_time', label: '決済時刻', padLeft: GAP_WIDE, headerPadRight: HEADER_GAP_EXIT },
  {
    key: 'exit_price',
    label: '決済価格',
    format: (v) => Number(v).toFixed(3),
    numeric: true,
    padLeft: 'pl-0',
  },
]

const DIRECTION_COLUMN: Column = {
  key: 'direction',
  label: '方向',
  format: (v) => (v === 'long' ? 'Long' : v === 'short' ? 'Short' : ''),
}

const POSITION_SIZING_COLUMNS: Column[] = [
  { key: 'lot_size', label: 'ロット', numeric: true },
  { key: 'profit_currency', label: '損益(通貨額)', format: (v) => Number(v).toLocaleString(), numeric: true },
  { key: 'account_balance', label: '残高', format: (v) => Number(v).toLocaleString(), numeric: true },
]

const PARTIAL_TP_COLUMN: Column = {
  key: 'partial_exit_prices',
  label: '部分利確価格',
  format: (v) => (Array.isArray(v) && v.length > 0 ? v.map((n) => Number(n).toFixed(3)).join(', ') : '-'),
  numeric: true,
}

const MAX_ROWS = 200

export default function TradeHistoryTable({ rows, symbol }: Props) {
  if (rows.length === 0) {
    return <div className="p-4 text-sm text-gray-500">まだ結果がありません</div>
  }

  // Only a dual-direction (Long+Short simultaneous) backtest's trades carry a
  // per-trade direction - a single-direction run has no need for the column.
  const hasDirection = rows.some((r) => r.direction != null)
  // Only trades from a run with position sizing enabled carry these fields.
  const hasPositionSizing = rows.some((r) => r.lot_size != null)
  // Only present when at least one trade actually took a partial profit
  // (use_partial_tp) - most trades in such a run still won't have it.
  const hasPartialTp = rows.some((r) => r.partial_exit_prices != null)
  // symbolに依存するので(main.py::pip_size_for_symbol()と同じ規則)、静的な
  // 列定義には入れられずここで組み立てる。表示順は方向の直後
  // (ユーザー指定: 方向・損益Pips・エントリー時刻・エントリー価格・
  // 決済時刻・決済価格)。
  const profitColumn: Column = {
    key: 'profit',
    label: '損益(pips)',
    format: (v: unknown) => {
      const pips = toPips(Number(v), symbol)
      return `${pips >= 0 ? '+' : ''}${pips.toFixed(pipsDecimals(symbol))}`
    },
    numeric: true,
    padLeft: GAP_DIRECTION_PROFIT,
  }
  // MAE(最大逆行幅)/MFE(最大追い風幅) - profitと同じくsymbolごとのpips
  // 換算が必要なので、静的なBASE_COLUMNS_WITHOUT_PROFITではなくここで
  // 組み立てる(ユーザー要望:「取引履歴にMAE,MFE追加してほしい。決済価格
  // の右に表示して」)。符号は常に0以上の大きさなので+は付けない。
  const maeColumn: Column = {
    key: 'mae',
    label: 'MAE(pips)',
    format: (v: unknown) => toPips(Number(v), symbol).toFixed(pipsDecimals(symbol)),
    numeric: true,
  }
  const mfeColumn: Column = {
    key: 'mfe',
    label: 'MFE(pips)',
    format: (v: unknown) => toPips(Number(v), symbol).toFixed(pipsDecimals(symbol)),
    numeric: true,
  }
  const COLUMNS = [
    ...(hasDirection ? [DIRECTION_COLUMN] : []),
    profitColumn,
    ...BASE_COLUMNS_WITHOUT_PROFIT,
    maeColumn,
    mfeColumn,
    ...(hasPositionSizing ? POSITION_SIZING_COLUMNS : []),
    ...(hasPartialTp ? [PARTIAL_TP_COLUMN] : []),
  ]

  return (
    <div className="overflow-auto">
      {rows.length > MAX_ROWS && (
        <div className="px-2 py-1 text-xs text-gray-500">
          全{rows.length}件中、直近{MAX_ROWS}件を表示
        </div>
      )}
      {/* w-fullにしない - テーブルをコンテナ幅いっぱいに伸ばすと、余った
          幅がブラウザの自動レイアウトによって列間に不均等に配られてしまい
          (特にエントリー/決済時刻列が幅を持って行きがちで、価格列との間が
          意図せず大きく開いた) - padding-leftで指定した間隔通りに表示する
          には、テーブル自体は内容分の幅だけを取るようにする必要がある。 */}
      <table className="text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-gray-400">
            {COLUMNS.map((col, i) => (
              <th
                key={String(col.key)}
                className={`${i === 0 ? 'pl-2' : (col.padLeft ?? 'pl-2')} ${col.headerPadRight ?? 'pr-0'} py-1 font-medium${col.numeric ? ' text-right' : ''}`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows
            .slice()
            .reverse()
            .slice(0, MAX_ROWS)
            .map((row, i) => (
              <tr key={i} className="border-b border-white/5 hover:bg-white/[0.04]">
                {COLUMNS.map((col, colIndex) => {
                  const raw = row[col.key]
                  const value = col.format ? col.format(raw) : String(raw ?? '')
                  const isProfit = col.key === 'profit'
                  const padClass = colIndex === 0 ? 'pl-2' : (col.padLeft ?? 'pl-2')
                  const alignClass = col.numeric ? ' text-right' : ''
                  const colorClass = isProfit ? (Number(raw) >= 0 ? ' text-green-400' : ' text-red-400') : ''
                  return (
                    <td
                      key={String(col.key)}
                      className={`${padClass} pr-0 py-1${alignClass}${colorClass}`}
                    >
                      {value}
                    </td>
                  )
                })}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}
