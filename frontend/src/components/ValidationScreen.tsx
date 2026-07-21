import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchBacktestStatus,
  fetchConfidenceResults,
  fetchMonteCarloResults,
  fetchOosResults,
  fetchSensitivityResults,
  fetchStrategyDetail,
  fetchWalkForwardResults,
  runConfidence,
  runMonteCarlo,
  runOos,
  runSensitivity,
  runWalkForward,
} from '../api'
import { buildMetricColumns, type MetricRowLike } from '../rankingColumns'
import type { IndicatorInfo } from '../types'
import SelectStrategyModal from './SelectStrategyModal'

interface CardProps {
  strategyId: string | null
  indicators: IndicatorInfo[]
}

interface Props {
  subTab: string
  strategyId: string | null
  onSelectStrategy: (id: string) => void
  indicators: IndicatorInfo[]
}

// ランキング一覧/ライブラリと同じPF〜CAGRの列(条件列は除く - OOS/Walk
// Forwardの行は「期間」や「窓」であって別ストラテジーではないので、同じ
// 条件式を毎行表示しても意味がない)。
function useMetricColumns(indicators: IndicatorInfo[]) {
  return buildMetricColumns(indicators).filter((col) => col.key !== 'condition_tree')
}

function useStrategySymbol(strategyId: string | null): string | undefined {
  const detailQuery = useQuery({
    queryKey: ['strategy-detail', strategyId],
    queryFn: () => fetchStrategyDetail(strategyId as string),
    enabled: strategyId !== null,
  })
  return detailQuery.data?.symbol
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

// 検証(Out-of-Sample/Walk Forward/Monte Carlo/パラメータ安定性)の各カード
// 共通のパターン: 結果は常にstrategy_idキーのby-strategyクエリ
// (resultsQuery)から表示する - api_server.pyがsaved_strategies/{id}/に
// ファイルとして書き出すため、ジョブ完了後はタブを切り替えてもソフトを
// 再起動してもディスクから読み直せば消えない。jobId/statusQueryは「今まさに
// 実行中かどうか」の表示専用で、doneになった瞬間にresultsQueryを1回
// 再取得したらjobIdはクリアする(このカード自体が別タブへの切り替えで
// アンマウントされても、次にマウントし直したresultsQueryが最新のディスク
// 内容を取りに行くので結果は失われない)。
function NoStrategySelected() {
  return (
    <div className="glass-panel rounded-2xl p-8 text-center text-sm text-gray-500">
      上の「ライブラリから選択」から保存済みストラテジーを選んでください。
    </div>
  )
}

function OosCard({ strategyId, indicators }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [splitRatio, setSplitRatio] = useState(0.7)
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status
  const columns = useMetricColumns(indicators)
  const symbol = useStrategySymbol(strategyId)

  const resultsQuery = useQuery({
    queryKey: ['oos-results', strategyId],
    queryFn: () => fetchOosResults(strategyId as string),
    enabled: strategyId !== null,
  })

  const runMutation = useMutation({
    mutationFn: () => runOos(strategyId as string, splitRatio),
    onSuccess: (data) => setJobId(data.job_id),
  })

  useEffect(() => {
    if (status === 'done' && jobId !== null) {
      resultsQuery.refetch()
      setJobId(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, jobId])

  if (strategyId === null) return <NoStrategySelected />

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">Out-of-Sample テスト</div>
      <p className="mb-3 text-xs text-gray-400">
        選択中のストラテジーを1回だけ学習期間/検証期間に分割し、再最適化なしで検証期間側の成績を確認します。
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
          disabled={runMutation.isPending || (status && status !== 'done' && status !== 'error')}
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
                {columns.map((col) => (
                  <th
                    key={col.key}
                    title={col.tooltip}
                    className={`whitespace-nowrap py-1 pr-2 ${col.numeric ? 'text-right' : ''}`}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {resultsQuery.data.rows.map((row, i) => {
                const metricRow: MetricRowLike = { ...(row as unknown as MetricRowLike), symbol }
                return (
                  <tr key={i} className="border-t border-white/5">
                    <td className="py-1 pr-2">{row.period === 'in_sample' ? 'In-Sample' : 'Out-of-Sample'}</td>
                    <td className="whitespace-nowrap py-1 pr-2">
                      {String(row.start).slice(0, 10)}〜{String(row.end).slice(0, 10)}
                    </td>
                    {columns.map((col) => {
                      const raw = metricRow[col.key]
                      const text = col.format ? col.format(raw, metricRow) : String(raw ?? '')
                      const colorClass = col.colorClass ? col.colorClass(raw) : ''
                      return (
                        <td
                          key={col.key}
                          className={`whitespace-nowrap py-1 pr-2 ${col.numeric ? 'text-right' : ''} ${colorClass}`}
                        >
                          {text}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function WalkForwardCard({ strategyId, indicators }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status
  const columns = useMetricColumns(indicators)
  const symbol = useStrategySymbol(strategyId)

  const resultsQuery = useQuery({
    queryKey: ['walk-forward-results', strategyId],
    queryFn: () => fetchWalkForwardResults(strategyId as string),
    enabled: strategyId !== null,
  })

  const runMutation = useMutation({
    mutationFn: () => runWalkForward(strategyId as string),
    onSuccess: (data) => setJobId(data.job_id),
  })

  useEffect(() => {
    if (status === 'done' && jobId !== null) {
      resultsQuery.refetch()
      setJobId(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, jobId])

  if (strategyId === null) return <NoStrategySelected />

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">ウォークフォワード検証</div>
      <p className="mb-3 text-xs text-gray-400">
        選択中のストラテジーを複数の学習/検証期間に分けて、過去の局所的な数値への当てはめでないか確認します。
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
                {columns.map((col) => (
                  <th
                    key={col.key}
                    title={col.tooltip}
                    className={`whitespace-nowrap py-1 pr-2 ${col.numeric ? 'text-right' : ''}`}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {resultsQuery.data.rows.map((row, i) => {
                // walk_forward_results.csvはtest_プレフィックス付きの列名
                // (train_側と区別するため)なので、ランキング一覧と同じ
                // buildMetricColumns用のキー名に詰め替える。
                const metricRow: MetricRowLike = {
                  profit_factor: row.test_profit_factor,
                  net_profit: row.test_net_profit,
                  expected_value: row.test_expected_value,
                  max_dd: row.test_max_dd,
                  win_rate: row.test_win_rate,
                  trades: row.test_trades,
                  sharpe_ratio: row.test_sharpe_ratio,
                  recovery_factor: row.test_recovery_factor,
                  sortino_ratio: row.test_sortino_ratio,
                  calmar_ratio: row.test_calmar_ratio,
                  cagr: row.test_cagr,
                  symbol,
                }
                return (
                  <tr key={i} className="border-t border-white/5">
                    <td className="py-1 pr-2">{String(row.window)}</td>
                    <td className="whitespace-nowrap py-1 pr-2">
                      {String(row.test_start)}〜{String(row.test_end)}
                    </td>
                    {columns.map((col) => {
                      const raw = metricRow[col.key]
                      const text = col.format ? col.format(raw, metricRow) : String(raw ?? '')
                      const colorClass = col.colorClass ? col.colorClass(raw) : ''
                      return (
                        <td
                          key={col.key}
                          className={`whitespace-nowrap py-1 pr-2 ${col.numeric ? 'text-right' : ''} ${colorClass}`}
                        >
                          {text}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function MonteCarloCard({ strategyId }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [simulations, setSimulations] = useState(1000)
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status

  const resultsQuery = useQuery({
    queryKey: ['tool-monte-carlo-results', strategyId],
    queryFn: () => fetchMonteCarloResults(strategyId as string),
    enabled: strategyId !== null,
  })

  const runMutation = useMutation({
    mutationFn: () => runMonteCarlo(strategyId as string, simulations),
    onSuccess: (data) => setJobId(data.job_id),
  })

  useEffect(() => {
    if (status === 'done' && jobId !== null) {
      resultsQuery.refetch()
      setJobId(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, jobId])

  if (strategyId === null) return <NoStrategySelected />

  const mc = resultsQuery.data?.monte_carlo_summary?.[0] as Record<string, unknown> | undefined

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">モンテカルロ・シミュレーション</div>
      <p className="mb-3 text-xs text-gray-400">
        選択中のストラテジーのトレード順序をシャッフルして、たまたま良い順番だっただけでないか確認します。
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
          disabled={runMutation.isPending || (status && status !== 'done' && status !== 'error')}
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

function SensitivityCard({ strategyId }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [mode, setMode] = useState<'dev' | 'full'>('full')
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status

  const resultsQuery = useQuery({
    queryKey: ['sensitivity-results', strategyId],
    queryFn: () => fetchSensitivityResults(strategyId as string),
    enabled: strategyId !== null,
  })

  const runMutation = useMutation({
    mutationFn: () => runSensitivity(strategyId as string, mode),
    onSuccess: (data) => setJobId(data.job_id),
  })

  useEffect(() => {
    if (status === 'done' && jobId !== null) {
      resultsQuery.refetch()
      setJobId(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, jobId])

  if (strategyId === null) return <NoStrategySelected />

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">パラメータ感度分析</div>
      <p className="mb-3 text-xs text-gray-400">
        選択中のストラテジーの各パラメータを1つずつ動かして、特定の値に頼った過剰最適化でないか確認します。
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
          disabled={runMutation.isPending || (status && status !== 'done' && status !== 'error')}
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
                <th className="py-1 pr-2 text-right">検証数</th>
                <th className="py-1 pr-2 text-right">PF最小</th>
                <th className="py-1 pr-2 text-right">PF最大</th>
                <th className="py-1 pr-2 text-right">平坦度</th>
              </tr>
            </thead>
            <tbody>
              {resultsQuery.data.summary.map((row, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="py-1 pr-2">{String(row.param)}</td>
                  <td className="py-1 pr-2 text-right">{String(row.variants_tested)}</td>
                  <td className="py-1 pr-2 text-right">{fmt(row.pf_min)}</td>
                  <td className="py-1 pr-2 text-right">{fmt(row.pf_max)}</td>
                  <td className="py-1 pr-2 text-right">{fmt(row.flatness_ratio)}</td>
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

function ConfidenceCard({ strategyId }: CardProps) {
  const [jobId, setJobId] = useState<string | null>(null)
  const statusQuery = useJobPolling(jobId)
  const status = statusQuery.data?.status

  const resultsQuery = useQuery({
    queryKey: ['confidence-results', strategyId],
    queryFn: () => fetchConfidenceResults(strategyId as string),
    enabled: strategyId !== null,
  })

  const runMutation = useMutation({
    mutationFn: () => runConfidence(strategyId as string),
    onSuccess: (data) => setJobId(data.job_id),
  })

  useEffect(() => {
    if (status === 'done' && jobId !== null) {
      resultsQuery.refetch()
      setJobId(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, jobId])

  if (strategyId === null) return <NoStrategySelected />

  const result = resultsQuery.data

  return (
    <div className="glass-panel rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">信頼度スコア(総合)</div>
      <p className="mb-3 text-xs text-gray-400">
        このストラテジーの安定度・モンテカルロ・感度分析の結果を集約した総合評価です。
        上のパラメータ感度分析やモンテカルロを先に実行してからどうぞ。
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

// 4つの検証タブすべてで共通の対象ストラテジー選択バー。「ライブラリから選択」
// ボタンはOut-of-Sampleタブでだけ出す(Walk Forward/Monte Carlo/パラメータ
// 安定性は選択中の表示のみ - 選択自体はどのタブから見ても共通)。
function StrategySelector({
  subTab,
  strategyId,
  onSelectStrategy,
}: {
  subTab: string
  strategyId: string | null
  onSelectStrategy: (id: string) => void
}) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const canChange = subTab === 'oos'

  const detailQuery = useQuery({
    queryKey: ['strategy-detail', strategyId],
    queryFn: () => fetchStrategyDetail(strategyId as string),
    enabled: strategyId !== null,
  })

  const label =
    strategyId === null
      ? '未選択'
      : detailQuery.data
        ? `${detailQuery.data.name} (${detailQuery.data.symbol}/${detailQuery.data.timeframe})`
        : '読み込み中…'

  return (
    <>
      <div className="glass-panel mb-4 flex items-center gap-3 rounded-2xl px-4 py-2.5 text-xs">
        <span className="text-gray-400">対象ストラテジー:</span>
        <span className="font-semibold text-gray-100">{label}</span>
        {canChange ? (
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            className="glass-input ml-auto rounded-lg px-3 py-1.5 font-semibold text-gray-200"
          >
            ライブラリから選択
          </button>
        ) : (
          <span className="ml-auto text-gray-500">選択の変更はOut-of-Sampleタブから行えます</span>
        )}
      </div>
      {/* backdrop-filterを持つ.glass-panelの内側にfixedモーダルを置くと、
          backdrop-filterが新しいスタッキングコンテキストを作ってしまい、
          z-50を付けても兄弟の.glass-panel(NoStrategySelectedなど)の裏に
          隠れてしまう(実際に踏んだ不具合)。glass-panelの外側で描画する。 */}
      {pickerOpen && <SelectStrategyModal onSelect={onSelectStrategy} onClose={() => setPickerOpen(false)} />}
    </>
  )
}

export default function ValidationScreen({ subTab, strategyId, onSelectStrategy, indicators }: Props) {
  return (
    <div>
      <StrategySelector subTab={subTab} strategyId={strategyId} onSelectStrategy={onSelectStrategy} />
      {subTab === 'oos' && <OosCard strategyId={strategyId} indicators={indicators} />}
      {subTab === 'walkforward' && <WalkForwardCard strategyId={strategyId} indicators={indicators} />}
      {subTab === 'montecarlo' && <MonteCarloCard strategyId={strategyId} indicators={indicators} />}
      {subTab !== 'oos' && subTab !== 'walkforward' && subTab !== 'montecarlo' && (
        <div className="space-y-4">
          <SensitivityCard strategyId={strategyId} indicators={indicators} />
          <ConfidenceCard strategyId={strategyId} indicators={indicators} />
        </div>
      )}
    </div>
  )
}
