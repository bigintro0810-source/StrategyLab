import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { validateData } from '../api'

interface Props {
  symbols: string[]
  timeframes: string[]
  // 通貨ごとに実際にインポート済みの時間足(App.tsx::symbolTimeframes参照) -
  // 選択中の通貨に無い時間足は選べなくする(ユーザー要望: 「読み込んでいな
  // いデータは選択不可能にしてほしい」)。
  symbolTimeframes: Record<string, string[]>
}

export default function DataValidatorScreen({ symbols, timeframes, symbolTimeframes }: Props) {
  const [symbol, setSymbol] = useState(symbols[0])
  const [timeframe, setTimeframe] = useState('15m')
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    const available = symbolTimeframes[symbol]
    if (available && available.length > 0 && !available.includes(timeframe)) {
      setTimeframe(available[0])
    }
  }, [symbol, symbolTimeframes, timeframe])

  const validateQuery = useQuery({
    queryKey: ['data-validate', symbol, timeframe],
    queryFn: () => validateData(symbol, timeframe),
    enabled: checked,
  })

  const report = validateQuery.data

  return (
    <div className="glass-panel max-w-2xl rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">Data Validator</div>
      <p className="mb-3 text-xs text-gray-400">
        データファイルの行数・期間・重複タイムスタンプ・四本値の整合性・大きな時間ギャップを確認します。
      </p>

      <div className="mb-3 flex items-center gap-2 text-xs text-gray-300">
        <select
          className="glass-input rounded-lg px-2 py-1.5"
          value={symbol}
          onChange={(e) => {
            setSymbol(e.target.value)
            setChecked(false)
          }}
        >
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          className="glass-input rounded-lg px-2 py-1.5"
          value={timeframe}
          onChange={(e) => {
            setTimeframe(e.target.value)
            setChecked(false)
          }}
        >
          {timeframes.map((tf) => (
            <option key={tf} value={tf} disabled={!(symbolTimeframes[symbol] ?? timeframes).includes(tf)}>
              {tf}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => (checked ? validateQuery.refetch() : setChecked(true))}
          disabled={validateQuery.isFetching}
          className="glow-button rounded-lg px-3 py-1.5 font-semibold text-white disabled:opacity-40"
        >
          検証実行
        </button>
      </div>

      {validateQuery.isError && (
        <p className="text-xs text-red-400">
          {(validateQuery.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'データが見つかりませんでした。'}
        </p>
      )}

      {report && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
            {[
              { label: '本数', value: report.rows.toLocaleString() },
              { label: '期間開始', value: report.start.slice(0, 10) },
              { label: '期間終了', value: report.end.slice(0, 10) },
              {
                label: '重複タイムスタンプ',
                value: String(report.duplicate_timestamps),
                warn: report.duplicate_timestamps > 0,
              },
              { label: '四本値の不整合', value: String(report.ohlc_violations), warn: report.ohlc_violations > 0 },
              { label: '大きな時間ギャップ', value: String(report.gap_count) },
            ].map((s) => (
              <div
                key={s.label}
                className={`rounded-lg border p-2 ${
                  s.warn ? 'border-red-500/30 bg-red-950/20' : 'border-white/10 bg-white/[0.02]'
                }`}
              >
                <div className="text-gray-400">{s.label}</div>
                <div className={`font-semibold ${s.warn ? 'text-red-300' : 'text-gray-100'}`}>{s.value}</div>
              </div>
            ))}
          </div>

          {report.gaps.length > 0 && (
            <div>
              <div className="mb-1 text-xs text-gray-400">
                時間ギャップ(通常の週末クローズも含みます。曜日を見て判断してください)
              </div>
              <div className="max-h-56 overflow-auto">
                <table className="w-full text-left text-[11px] text-gray-300">
                  <thead className="text-gray-500">
                    <tr>
                      <th className="py-1 pr-2">直前</th>
                      <th className="py-1 pr-2">直後</th>
                      <th className="py-1 pr-2 text-right">分数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.gaps.map((g, i) => (
                      <tr key={i} className="border-t border-white/5">
                        <td className="py-1 pr-2">{g.before}</td>
                        <td className="py-1 pr-2">{g.after}</td>
                        <td className="py-1 pr-2 text-right">{g.minutes.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
