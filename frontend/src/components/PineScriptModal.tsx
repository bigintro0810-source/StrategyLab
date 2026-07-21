import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { fetchPineScript } from '../api'

interface Props {
  strategyId: string
  onClose: () => void
}

// レポートPDF(ReportScreen.tsx)と同じ「非対応/エラー時はサーバーの理由を
// そのまま見せる」方針 - condition_treeに未対応の指標が含まれる場合、
// engine/pine_generator.pyが投げるValueErrorの文言(どの指標が未対応か)を
// そのままdetailとして返してくる(api_server.py::get_strategy_pine_script)。
function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  return err instanceof Error ? err.message : 'Pine Scriptの生成に失敗しました'
}

export default function PineScriptModal({ strategyId, onClose }: Props) {
  const [copied, setCopied] = useState(false)
  const query = useQuery({
    queryKey: ['pine-script', strategyId],
    queryFn: () => fetchPineScript(strategyId),
    retry: false,
  })

  const handleCopy = async () => {
    if (!query.data) return
    await navigator.clipboard.writeText(query.data.script)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const handleDownload = () => {
    if (!query.data) return
    const blob = new Blob([query.data.script], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = query.data.filename
    a.click()
    URL.revokeObjectURL(url)
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 py-8"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="glass-panel flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl p-4"
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-100">TradingView Pine Script</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-200">
            ×
          </button>
        </div>

        {query.isLoading && <div className="py-8 text-center text-sm text-gray-400">生成中…</div>}

        {query.isError && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
            {errorMessage(query.error)}
          </div>
        )}

        {query.data && (
          <>
            <textarea
              readOnly
              value={query.data.script}
              className="min-h-[50vh] flex-1 resize-none rounded-lg border border-white/10 bg-black/30 p-3 font-mono text-xs text-gray-200"
              onClick={(e) => e.currentTarget.select()}
            />
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopy}
                className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200 hover:bg-white/10"
              >
                {copied ? 'コピーしました' : 'コピー'}
              </button>
              <button
                type="button"
                onClick={handleDownload}
                className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200 hover:bg-white/10"
              >
                .pineファイルをダウンロード
              </button>
              <span className="text-xs text-gray-500">TradingViewのPineエディタに貼り付けて使用してください</span>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}
