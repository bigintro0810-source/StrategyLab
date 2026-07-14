import { reportPdfUrl } from '../api'
import type { BacktestResults, RankingRow } from '../types'

interface Props {
  jobId: string | null
  jobDone: boolean
  symbol: string
  timeframe: string
  selectedRank: number | null
  bestRow: RankingRow | undefined
  results: BacktestResults | undefined
}

function toCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return ''
  const columns = Object.keys(rows[0])
  const escape = (v: unknown) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [columns.join(',')]
  for (const row of rows) {
    lines.push(columns.map((c) => escape(row[c])).join(','))
  }
  return lines.join('\n')
}

function downloadCsv(rows: Record<string, unknown>[], filename: string) {
  const csv = toCsv(rows)
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function fmt(v: number | undefined, digits = 2): string {
  if (v === undefined || Number.isNaN(v)) return '-'
  return v.toFixed(digits)
}

export default function ReportScreen({ jobId, jobDone, symbol, timeframe, selectedRank, bestRow, results }: Props) {
  const hasResults = Boolean(bestRow)

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-3 text-sm font-semibold text-gray-200">対象</div>
        <div className="space-y-1 text-xs text-gray-300">
          <div className="flex justify-between border-b border-white/5 py-1">
            <span className="text-gray-400">通貨ペア / 時間足</span>
            <span>
              {symbol} / {timeframe}
            </span>
          </div>
          <div className="flex justify-between border-b border-white/5 py-1">
            <span className="text-gray-400">ストラテジー</span>
            <span>{selectedRank !== null ? `rank ${selectedRank}` : '全体ベスト'}</span>
          </div>
        </div>

        {!hasResults && (
          <p className="mt-4 text-sm text-gray-500">
            まだ結果がありません。手動ビルダーか自動探索でバックテストを実行してください。
          </p>
        )}

        {hasResults && (
          <div className="mt-4 flex flex-wrap gap-2">
            <a
              href={jobId ? reportPdfUrl(jobId) : undefined}
              target="_blank"
              rel="noreferrer"
              className={
                jobId && jobDone
                  ? 'glow-button rounded-lg px-3 py-2 text-xs font-semibold text-white'
                  : 'pointer-events-none rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-gray-500'
              }
            >
              PDFで出力
            </a>
            <button
              type="button"
              onClick={() => downloadCsv(results?.trade_log ?? [], `trades_${symbol}_${timeframe}.csv`)}
              disabled={!results?.trade_log?.length}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-gray-300 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
            >
              取引履歴CSV
            </button>
            <button
              type="button"
              onClick={() => downloadCsv(results?.ranking_total ?? [], `ranking_${symbol}_${timeframe}.csv`)}
              disabled={!results?.ranking_total?.length}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-gray-300 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
            >
              ランキングCSV
            </button>
          </div>
        )}
      </div>

      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-3 text-sm font-semibold text-gray-200">プレビュー</div>
        {bestRow ? (
          <div className="grid grid-cols-2 gap-2 text-sm">
            {[
              { label: '純利益', value: fmt(bestRow.net_profit) },
              { label: '最大DD', value: fmt(bestRow.max_dd, 1) },
              { label: 'PF', value: fmt(bestRow.profit_factor) },
              { label: '勝率%', value: fmt(bestRow.win_rate, 1) },
              { label: 'トレード数', value: String(bestRow.trades) },
              { label: 'Sharpe', value: fmt(bestRow.sharpe_ratio) },
            ].map((s) => (
              <div key={s.label} className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
                <div className="text-xs text-gray-400">{s.label}</div>
                <div className="font-semibold text-gray-100">{s.value}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-gray-500">まだ結果がありません</div>
        )}
      </div>
    </div>
  )
}
