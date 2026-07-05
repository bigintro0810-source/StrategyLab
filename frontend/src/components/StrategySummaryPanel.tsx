import type { Direction, RankingRow } from '../types'

interface Props {
  symbol: string
  timeframe: string
  mode: string
  direction: Direction
  dualDirectionMode: boolean
  testCount: number
  row: RankingRow | undefined
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-white/5 py-1 text-sm">
      <span className="text-gray-400">{label}</span>
      <span className="font-medium text-gray-100">{value}</span>
    </div>
  )
}

export default function StrategySummaryPanel({ symbol, timeframe, mode, direction, dualDirectionMode, testCount, row }: Props) {
  return (
    <div className="space-y-0.5">
      <Field label="通貨ペア" value={symbol} />
      <Field label="時間足" value={timeframe} />
      <Field label="モード" value={mode === 'full' ? 'full(本番)' : 'dev(軽量)'} />
      <Field
        label="方向"
        value={dualDirectionMode ? 'Long+Short(同時)' : direction === 'short' ? 'Short(売り)' : 'Long(買い)'}
      />
      <Field label="テスト数" value={String(testCount)} />
      {row ? (
        <>
          <Field label="取引数" value={String(row.trades)} />
          <Field label="PF" value={row.profit_factor.toFixed(2)} />
          <Field label="最大DD" value={row.max_dd.toFixed(1)} />
          <Field label="勝率%" value={row.win_rate.toFixed(1)} />
          <Field label="損益期待値" value={row.expected_value.toFixed(2)} />
          <Field label="RR" value={row.rr !== undefined ? String(row.rr) : '-'} />
        </>
      ) : (
        <div className="pt-2 text-sm text-gray-500">まだ結果がありません</div>
      )}
    </div>
  )
}
