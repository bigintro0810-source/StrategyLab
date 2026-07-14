import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fetchBacktestStatus, importCsv } from '../api'

interface Props {
  symbols: string[]
  timeframes: string[]
}

export default function CsvImportScreen({ symbols, timeframes }: Props) {
  const [sourceRoot, setSourceRoot] = useState('')
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const [selectedTimeframes, setSelectedTimeframes] = useState<string[]>(['15m'])
  const [jobId, setJobId] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)

  const statusQuery = useQuery({
    queryKey: ['csv-import-status', jobId],
    queryFn: () => fetchBacktestStatus(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'done' || status === 'error' ? false : 1500
    },
    refetchIntervalInBackground: true,
  })
  const status = statusQuery.data?.status

  const runMutation = useMutation({
    mutationFn: () => importCsv(sourceRoot, selectedSymbols, selectedTimeframes),
    onSuccess: (data) => setJobId(data.job_id),
  })

  const toggle = (list: string[], set: (v: string[]) => void, value: string) => {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])
  }

  const canRun = sourceRoot.trim() !== '' && selectedSymbols.length > 0 && selectedTimeframes.length > 0 && confirmed

  return (
    <div className="glass-panel max-w-2xl rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">CSVインポート</div>
      <p className="mb-3 text-xs text-gray-400">
        ブローカー提供のEET(東欧時間)CSVを、通貨ペアごとのフォルダ(<code>{'{フォルダ}'}\\{'{通貨ペア}'}_Data\\</code>)から
        JST変換して取り込みます。既存の同名データファイルは上書きされます。
      </p>

      <label className="mb-3 block text-xs text-gray-300">
        <span className="mb-1 block text-gray-400">取り込み元フォルダ</span>
        <input
          type="text"
          placeholder="例: C:\Users\...\FX_Data"
          className="glass-input w-full rounded-lg px-2 py-1.5"
          value={sourceRoot}
          onChange={(e) => setSourceRoot(e.target.value)}
        />
      </label>

      <div className="mb-3">
        <div className="mb-1 text-xs text-gray-400">対象通貨ペア</div>
        <div className="flex flex-wrap gap-2 text-xs">
          {symbols.map((s) => (
            <label key={s} className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1">
              <input
                type="checkbox"
                checked={selectedSymbols.includes(s)}
                onChange={() => toggle(selectedSymbols, setSelectedSymbols, s)}
              />
              {s}
            </label>
          ))}
        </div>
      </div>

      <div className="mb-3">
        <div className="mb-1 text-xs text-gray-400">対象時間足</div>
        <div className="flex flex-wrap gap-2 text-xs">
          {timeframes.map((tf) => (
            <label key={tf} className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1">
              <input
                type="checkbox"
                checked={selectedTimeframes.includes(tf)}
                onChange={() => toggle(selectedTimeframes, setSelectedTimeframes, tf)}
              />
              {tf}
            </label>
          ))}
        </div>
      </div>

      <label className="mb-3 flex items-center gap-1.5 text-xs text-amber-300">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        既存のデータファイルを上書きすることを確認しました
      </label>

      <button
        type="button"
        onClick={() => runMutation.mutate()}
        disabled={!canRun || runMutation.isPending || (status && status !== 'done' && status !== 'error')}
        className="glow-button rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
      >
        インポート実行
      </button>

      {status && status !== 'done' && status !== 'error' && (
        <p className="mt-3 text-xs text-gray-400">実行中…(データ量によっては数分かかります)</p>
      )}
      {status === 'done' && <p className="mt-3 text-xs text-emerald-400">完了しました。</p>}
      {status === 'error' && (
        <p className="mt-3 whitespace-pre-wrap text-xs text-red-400">{statusQuery.data?.error_summary}</p>
      )}
    </div>
  )
}
