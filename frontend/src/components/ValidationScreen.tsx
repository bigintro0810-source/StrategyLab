import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchBacktestResults,
  fetchBacktestStatus,
  fetchConfidenceResults,
  fetchOosResults,
  fetchSensitivityResults,
  fetchWalkForwardResults,
  runConfidence,
  runMonteCarlo,
  runOos,
  runSensitivity,
  runWalkForward,
} from '../api'

interface CardProps {
  symbol: string
  timeframe: string
  effectiveRank: number | null
}

interface Props extends CardProps {
  subTab: string
}

function useJobPolling(jobId: string | null) {
  return useQuery({
    queryKey: ['tool-job-status', jobId],
    queryFn: () => fetchBacktestStatus(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'done' || status === 'error' ? false : 1000
    },
    refetchIntervalInBackground: true,
  })
}

function fmt(v: unknown, digits = 2): string {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v ?? '-')
}

function OosCard({ symbol, timeframe, effectiveRank }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [splitRatio, setSplitRatio] = useState(0.7)
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status

  const runMutation = useMutation({
    mutationFn: () => runOos(symbol, timeframe, effectiveRank as number, splitRatio),
    onSuccess: (data) => setJobId(data.job_id),
  })

  const resultsQuery = useQuery({
    queryKey: ['oos-results', jobId],
    queryFn: () => fetchOosResults(jobId as string),
    enabled: jobId !== null && status === 'done',
  })

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">Out-of-Sample テスト</div>
      <p className="mb-3 text-xs text-gray-400">
        選択中のストラテジー(rank {effectiveRank ?? '-'})を1回だけ学習期間/検証期間に分割し、再最適化なしで検証期間側の成績を確認します。
        ウォークフォワードより単純で速い、最初の当てはめ確認です。
      </p>
      <div className="mb-3 flex items-center gap-2 text-xs text-gray-300">
        <label className="flex items-center gap-1.5">
          学習期間の割合
          <input
            type="number"
            min={0.1}
            max={0.9}
            step={0.05}
            className="glass-input w-20 rounded-lg px-2 py-1"
            value={splitRatio}
            onChange={(e) => setSplitRatio(Number(e.target.value))}
          />
        </label>
        <button
          type="button"
          onClick={() => runMutation.mutate()}
          disabled={effectiveRank === null || runMutation.isPending || (status && status !== 'done' && status !== 'error')}
          className="glow-button rounded-lg px-3 py-2 font-semibold text-white disabled:opacity-40"
        >
          実行
        </button>
      </div>
      {status && status !== 'done' && status !== 'error' && <span className="text-xs text-gray-400">実行中…</span>}
      {status === 'error' && <p className="mt-2 text-xs text-red-400">{statusQuery.data?.error_summary}</p>}

      {resultsQuery.data && resultsQuery.data.rows.length > 0 && (
        <div className="mt-4 overflow-auto">
          <table className="w-full text-left text-[11px] text-gray-300">
            <thead className="text-gray-500">
              <tr>
                <th className="py-1 pr-2">期間</th>
                <th className="py-1 pr-2">範囲</th>
                <th className="py-1 pr-2">トレード数</th>
                <th className="py-1 pr-2">勝率%</th>
                <th className="py-1 pr-2">PF</th>
                <th className="py-1 pr-2">最大DD</th>
              </tr>
            </thead>
            <tbody>
              {resultsQuery.data.rows.map((row, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="py-1 pr-2">{row.period === 'in_sample' ? 'In-Sample' : 'Out-of-Sample'}</td>
                  <td className="py-1 pr-2">
                    {String(row.start).slice(0, 10)}〜{String(row.end).slice(0, 10)}
                  </td>
                  <td className="py-1 pr-2">{String(row.trades)}</td>
                  <td className="py-1 pr-2">{fmt(row.win_rate, 1)}</td>
                  <td className="py-1 pr-2">{fmt(row.profit_factor)}</td>
                  <td className="py-1 pr-2">{fmt(row.max_dd, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function WalkForwardCard({ symbol, timeframe, effectiveRank }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status

  const runMutation = useMutation({
    mutationFn: () => runWalkForward(symbol, timeframe, effectiveRank as number),
    onSuccess: (data) => setJobId(data.job_id),
  })

  const resultsQuery = useQuery({
    queryKey: ['walk-forward-results', jobId],
    queryFn: () => fetchWalkForwardResults(jobId as string),
    enabled: jobId !== null && status === 'done',
  })

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">ウォークフォワード検証</div>
      <p className="mb-3 text-xs text-gray-400">
        選択中のストラテジー(rank {effectiveRank ?? '-'})を複数の学習/検証期間に分けて、過去の局所的な数値への当てはめでないか確認します。
      </p>
      <button
        type="button"
        onClick={() => runMutation.mutate()}
        disabled={effectiveRank === null || runMutation.isPending || (status && status !== 'done' && status !== 'error')}
        className="glow-button rounded-lg px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
      >
        実行
      </button>
      {status && status !== 'done' && status !== 'error' && (
        <span className="ml-3 text-xs text-gray-400">実行中…(数分かかる場合があります)</span>
      )}
      {status === 'error' && <p className="mt-2 text-xs text-red-400">{statusQuery.data?.error_summary}</p>}

      {resultsQuery.data && resultsQuery.data.rows.length > 0 && (
        <div className="mt-4 max-h-96 overflow-auto">
          <table className="w-full text-left text-[11px] text-gray-300">
            <thead className="text-gray-500">
              <tr>
                <th className="py-1 pr-2">窓</th>
                <th className="py-1 pr-2">検証期間</th>
                <th className="py-1 pr-2">検証PF</th>
                <th className="py-1 pr-2">検証最大DD</th>
                <th className="py-1 pr-2">検証トレード数</th>
              </tr>
            </thead>
            <tbody>
              {resultsQuery.data.rows.map((row, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="py-1 pr-2">{String(row.window)}</td>
                  <td className="py-1 pr-2">
                    {String(row.test_start)}〜{String(row.test_end)}
                  </td>
                  <td className="py-1 pr-2">{fmt(row.test_profit_factor)}</td>
                  <td className="py-1 pr-2">{fmt(row.test_max_dd, 1)}</td>
                  <td className="py-1 pr-2">{String(row.test_trades)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function MonteCarloCard({ symbol, timeframe, effectiveRank }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [simulations, setSimulations] = useState(1000)
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status

  const runMutation = useMutation({
    mutationFn: () => runMonteCarlo(symbol, timeframe, effectiveRank as number, simulations),
    onSuccess: (data) => setJobId(data.job_id),
  })

  const resultsQuery = useQuery({
    queryKey: ['tool-monte-carlo-results', jobId],
    queryFn: () => fetchBacktestResults(jobId as string),
    enabled: jobId !== null && status === 'done',
  })

  const mc = resultsQuery.data?.monte_carlo_summary?.[0] as Record<string, unknown> | undefined

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">モンテカルロ・シミュレーション</div>
      <p className="mb-3 text-xs text-gray-400">
        選択中のストラテジー(rank {effectiveRank ?? '-'})のトレード順序をシャッフルして、たまたま良い順番だっただけでないか確認します。
      </p>
      <div className="mb-3 flex items-center gap-2 text-xs text-gray-300">
        <label className="flex items-center gap-1.5">
          シミュレーション回数
          <input
            type="number"
            min={100}
            step={100}
            className="glass-input w-24 rounded-lg px-2 py-1"
            value={simulations}
            onChange={(e) => setSimulations(Number(e.target.value))}
          />
        </label>
        <button
          type="button"
          onClick={() => runMutation.mutate()}
          disabled={effectiveRank === null || runMutation.isPending || (status && status !== 'done' && status !== 'error')}
          className="glow-button rounded-lg px-3 py-2 font-semibold text-white disabled:opacity-40"
        >
          実行
        </button>
      </div>
      {status && status !== 'done' && status !== 'error' && <span className="text-xs text-gray-400">実行中…</span>}
      {status === 'error' && <p className="mt-2 text-xs text-red-400">{statusQuery.data?.error_summary}</p>}

      {mc && (
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
          {[
            { label: '評価', value: String(mc.rating ?? '-') },
            { label: 'シミュレーション回数', value: String(mc.simulations ?? '-') },
            { label: '平均最大DD', value: fmt(mc.avg_max_dd) },
            { label: '中央値DD', value: fmt(mc.median_max_dd) },
            { label: 'DD95%', value: fmt(mc.dd_95) },
            { label: '最悪ケース最大DD', value: fmt(mc.worst_max_dd) },
          ].map((s) => (
            <div key={s.label} className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
              <div className="text-gray-400">{s.label}</div>
              <div className="font-semibold text-gray-100">{s.value}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SensitivityCard({ symbol, timeframe, effectiveRank }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [mode, setMode] = useState<'dev' | 'full'>('full')
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status

  const runMutation = useMutation({
    mutationFn: () => runSensitivity(symbol, timeframe, mode, effectiveRank as number),
    onSuccess: (data) => setJobId(data.job_id),
  })

  const resultsQuery = useQuery({
    queryKey: ['sensitivity-results', jobId],
    queryFn: () => fetchSensitivityResults(jobId as string),
    enabled: jobId !== null && status === 'done',
  })

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">パラメータ感度分析</div>
      <p className="mb-3 text-xs text-gray-400">
        選択中のストラテジー(rank {effectiveRank ?? '-'})の各パラメータを1つずつ動かして、特定の値に頼った過剰最適化でないか確認します。
        full(本番)モードで作った結果が対象です。
      </p>
      <div className="mb-3 flex items-center gap-2 text-xs text-gray-300">
        <label className="flex items-center gap-1.5">
          対象モード
          <select
            className="glass-input rounded-lg px-2 py-1"
            value={mode}
            onChange={(e) => setMode(e.target.value as 'dev' | 'full')}
          >
            <option value="full">full(本番)</option>
            <option value="dev">dev(軽量)</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => runMutation.mutate()}
          disabled={effectiveRank === null || runMutation.isPending || (status && status !== 'done' && status !== 'error')}
          className="glow-button rounded-lg px-3 py-2 font-semibold text-white disabled:opacity-40"
        >
          実行
        </button>
      </div>
      {status && status !== 'done' && status !== 'error' && (
        <span className="text-xs text-gray-400">実行中…(数分かかる場合があります)</span>
      )}
      {status === 'error' && <p className="mt-2 text-xs text-red-400">{statusQuery.data?.error_summary}</p>}

      {resultsQuery.data && resultsQuery.data.summary.length > 0 && (
        <div className="mt-4 max-h-64 overflow-auto">
          <table className="w-full text-left text-[11px] text-gray-300">
            <thead className="text-gray-500">
              <tr>
                <th className="py-1 pr-2">パラメータ</th>
                <th className="py-1 pr-2">検証数</th>
                <th className="py-1 pr-2">PF最小</th>
                <th className="py-1 pr-2">PF最大</th>
                <th className="py-1 pr-2">平坦度</th>
              </tr>
            </thead>
            <tbody>
              {resultsQuery.data.summary.map((row, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="py-1 pr-2">{String(row.param)}</td>
                  <td className="py-1 pr-2">{String(row.variants_tested)}</td>
                  <td className="py-1 pr-2">{fmt(row.pf_min)}</td>
                  <td className="py-1 pr-2">{fmt(row.pf_max)}</td>
                  <td className="py-1 pr-2">{fmt(row.flatness_ratio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[10px] text-gray-500">
            感度スコア: {fmt(resultsQuery.data.summary[0]?.sensitivity_score)} (
            {String(resultsQuery.data.summary[0]?.sensitivity_rating)}) - 低い/Dに近いほど過剰最適化の疑いあり
          </p>
        </div>
      )}
    </div>
  )
}

function ConfidenceCard({ symbol, timeframe }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status

  const runMutation = useMutation({
    mutationFn: () => runConfidence(symbol, timeframe),
    onSuccess: (data) => setJobId(data.job_id),
  })

  const resultsQuery = useQuery({
    queryKey: ['confidence-results', jobId],
    queryFn: () => fetchConfidenceResults(jobId as string),
    enabled: jobId !== null && status === 'done',
  })

  const result = resultsQuery.data

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">信頼度スコア(総合)</div>
      <p className="mb-3 text-xs text-gray-400">
        この通貨ペア/時間足のフォルダにある安定度・モンテカルロ・ウォークフォワード・感度分析の結果を集約した総合評価です。
        古い結果が混ざっていることがあるので、上のパラメータ感度分析やウォークフォワードを先に実行してからどうぞ。
      </p>
      <button
        type="button"
        onClick={() => runMutation.mutate()}
        disabled={runMutation.isPending || (status && status !== 'done' && status !== 'error')}
        className="glow-button rounded-lg px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
      >
        実行
      </button>
      {status && status !== 'done' && status !== 'error' && (
        <span className="ml-3 text-xs text-gray-400">実行中…</span>
      )}
      {status === 'error' && <p className="mt-2 text-xs text-red-400">{statusQuery.data?.error_summary}</p>}

      {result && Object.keys(result).length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
            <div className="text-gray-400">総合Confidence Score</div>
            <div className="font-semibold text-gray-100">
              {fmt(result.confidence_score)} ({String(result.confidence_rating)})
            </div>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-2">
            <div className="text-gray-400">使用済み内訳</div>
            <div className="text-gray-100">{String(result.components_used || '-')}</div>
          </div>
          {result.components_missing ? (
            <div className="col-span-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
              <div className="text-gray-400">未取得(未実行のため対象外)</div>
              <div className="text-gray-100">{String(result.components_missing)}</div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

export default function ValidationScreen({ subTab, symbol, timeframe, effectiveRank }: Props) {
  if (subTab === 'oos') return <OosCard symbol={symbol} timeframe={timeframe} effectiveRank={effectiveRank} />
  if (subTab === 'walkforward') return <WalkForwardCard symbol={symbol} timeframe={timeframe} effectiveRank={effectiveRank} />
  if (subTab === 'montecarlo') return <MonteCarloCard symbol={symbol} timeframe={timeframe} effectiveRank={effectiveRank} />
  return (
    <div className="space-y-4">
      <SensitivityCard symbol={symbol} timeframe={timeframe} effectiveRank={effectiveRank} />
      <ConfidenceCard symbol={symbol} timeframe={timeframe} effectiveRank={effectiveRank} />
    </div>
  )
}
