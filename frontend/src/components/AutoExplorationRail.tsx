import type { UseMutationResult } from '@tanstack/react-query'
import type { BacktestJob, BacktestStatus } from '../types'

type ExplorationMode = 'manual' | 'structure' | 'structure_genetic'

interface Props {
  explorationMode: ExplorationMode
  setExplorationMode: (mode: ExplorationMode) => void
  explorationAdvOpen: boolean
  setExplorationAdvOpen: (fn: (v: boolean) => boolean) => void
  nCandidates: number
  setNCandidates: (v: number) => void
  maxDepth: number
  setMaxDepth: (v: number) => void
  maxLeaves: number
  setMaxLeaves: (v: number) => void
  minTrades: number
  setMinTrades: (v: number) => void
  mtfProbability: number
  setMtfProbability: (v: number) => void
  mtfTimeframes: string
  setMtfTimeframes: (v: string) => void
  population: number
  setPopulation: (v: number) => void
  generations: number
  setGenerations: (v: number) => void
  mutationRate: number
  setMutationRate: (v: number) => void
  symbol: string
  setSymbol: (v: string) => void
  timeframe: string
  setTimeframe: (v: string) => void
  mode: string
  setMode: (v: string) => void
  saveAsName: string
  setSaveAsName: (v: string) => void
  symbols: string[]
  timeframes: string[]
  runMutation: UseMutationResult<BacktestJob, Error, void, unknown>
  isRunning: boolean | undefined
  statusData: BacktestStatus | undefined
}

export default function AutoExplorationRail({
  explorationMode,
  setExplorationMode,
  explorationAdvOpen,
  setExplorationAdvOpen,
  nCandidates,
  setNCandidates,
  maxDepth,
  setMaxDepth,
  maxLeaves,
  setMaxLeaves,
  minTrades,
  setMinTrades,
  mtfProbability,
  setMtfProbability,
  mtfTimeframes,
  setMtfTimeframes,
  population,
  setPopulation,
  generations,
  setGenerations,
  mutationRate,
  setMutationRate,
  symbol,
  setSymbol,
  timeframe,
  setTimeframe,
  mode,
  setMode,
  saveAsName,
  setSaveAsName,
  symbols,
  timeframes,
  runMutation,
  isRunning,
  statusData,
}: Props) {
  return (
    <div className="glass-panel h-fit space-y-3 rounded-2xl p-4">
      <div className="flex overflow-hidden rounded-lg border border-white/10 text-xs">
        <button
          type="button"
          onClick={() => setExplorationMode('manual')}
          className="flex-1 px-2 py-1.5 text-gray-400 hover:bg-white/5 hover:text-gray-200"
        >
          手動ビルダー
        </button>
        <button
          type="button"
          onClick={() => setExplorationMode('structure_genetic')}
          className="flex-1 bg-purple-500/30 px-2 py-1.5 font-semibold text-purple-100"
        >
          自動探索
        </button>
      </div>

      <div className="text-sm font-semibold text-gray-300">探索方法</div>
      <div className="space-y-2 text-xs text-gray-300">
        <button
          type="button"
          onClick={() => setExplorationMode('structure')}
          className={`flex w-full items-start gap-2 rounded-lg border p-2 text-left ${
            explorationMode === 'structure' ? 'border-purple-500/50 bg-purple-500/[0.08]' : 'border-white/10 hover:bg-white/5'
          }`}
        >
          <span
            className={`mt-0.5 h-3.5 w-3.5 flex-none rounded-full border ${
              explorationMode === 'structure' ? 'border-purple-400 bg-purple-400' : 'border-white/30'
            }`}
          />
          <span>
            <span className="text-[11.5px] font-semibold text-gray-100">ランダム探索</span>
            <p className="mt-0.5 text-[10px] text-gray-500">条件を無作為に大量生成して片っ端から検証する</p>
          </span>
        </button>
        <button
          type="button"
          onClick={() => setExplorationMode('structure_genetic')}
          className={`flex w-full items-start gap-2 rounded-lg border p-2 text-left ${
            explorationMode === 'structure_genetic'
              ? 'border-purple-500/50 bg-purple-500/[0.08]'
              : 'border-white/10 hover:bg-white/5'
          }`}
        >
          <span
            className={`mt-0.5 h-3.5 w-3.5 flex-none rounded-full border ${
              explorationMode === 'structure_genetic' ? 'border-purple-400 bg-purple-400' : 'border-white/30'
            }`}
          />
          <span>
            <span className="text-[11.5px] font-semibold text-gray-100">
              AI進化探索
              <span className="ml-1.5 rounded bg-emerald-500/15 px-1.5 py-0.5 align-middle text-[9px] text-emerald-300">
                推奨
              </span>
            </span>
            <p className="mt-0.5 text-[10px] text-gray-500">良い条件同士を掛け合わせながら世代を重ねて改良する</p>
          </span>
        </button>
      </div>

      <p className="text-[11px] text-gray-500">
        条件はエンジンが自動生成します(Long/Shortも両方試されます)。決済ルール・コスト・ポジションサイジングは
        下の設定は使われず、{mode === 'dev' ? 'devモードの' : 'fullモードの'}既定値で実行されます。
      </p>

      <button
        type="button"
        onClick={() => setExplorationAdvOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[10.5px] text-gray-400 hover:text-gray-200"
      >
        <span className={`text-[9px] transition-transform ${explorationAdvOpen ? 'rotate-90' : ''}`}>▸</span>
        詳細設定(条件生成・AI進化)
      </button>
      {explorationAdvOpen && (
        <div className="space-y-1.5 rounded-lg border border-white/10 bg-white/[0.02] p-2 text-xs text-gray-300">
          <label className="flex items-center justify-between gap-2">
            候補数(n-candidates)
            <input
              type="number"
              min={1}
              className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs"
              value={nCandidates}
              onChange={(e) => setNCandidates(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            条件ツリーの最大深さ(max-depth)
            <input
              type="number"
              min={0}
              className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs"
              value={maxDepth}
              onChange={(e) => setMaxDepth(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            条件数の目安上限(max-leaves)
            <input
              type="number"
              min={1}
              className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs"
              value={maxLeaves}
              onChange={(e) => setMaxLeaves(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            最低トレード数(min-trades)
            <input
              type="number"
              min={0}
              className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs"
              value={minTrades}
              onChange={(e) => setMinTrades(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            MTF条件の生成確率(mtf-probability)
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs"
              value={mtfProbability}
              onChange={(e) => setMtfProbability(Number(e.target.value))}
            />
          </label>
          {mtfProbability > 0 && (
            <label className="flex items-center justify-between gap-2">
              参照する時間足(カンマ区切り・空欄で自動)
              <input
                type="text"
                placeholder="例: 1h,4h,1d"
                className="glass-input w-32 rounded-lg px-1.5 py-1 text-xs"
                value={mtfTimeframes}
                onChange={(e) => setMtfTimeframes(e.target.value)}
              />
            </label>
          )}

          {explorationMode === 'structure_genetic' && (
            <>
              <div className="pt-1 font-semibold text-gray-400">遺伝的アルゴリズム設定</div>
              <label className="flex items-center justify-between gap-2">
                個体数(population)
                <input
                  type="number"
                  min={1}
                  className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs"
                  value={population}
                  onChange={(e) => setPopulation(Number(e.target.value))}
                />
              </label>
              <label className="flex items-center justify-between gap-2">
                世代数(generations)
                <input
                  type="number"
                  min={1}
                  className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs"
                  value={generations}
                  onChange={(e) => setGenerations(Number(e.target.value))}
                />
              </label>
              <label className="flex items-center justify-between gap-2">
                突然変異率(mutation-rate)
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs"
                  value={mutationRate}
                  onChange={(e) => setMutationRate(Number(e.target.value))}
                />
              </label>
            </>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 text-sm">
        <select className="glass-input rounded-lg px-2 py-1.5" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          className="glass-input rounded-lg px-2 py-1.5"
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
        >
          {timeframes.map((tf) => (
            <option key={tf} value={tf}>
              {tf}
            </option>
          ))}
        </select>
        <select className="glass-input col-span-2 rounded-lg px-2 py-1.5" value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="dev">dev(軽量)</option>
          <option value="full">full(本番)</option>
        </select>
      </div>

      <input
        type="text"
        placeholder="名前を付けて保存(任意)"
        className="glass-input w-full rounded-lg px-2 py-1.5 text-xs"
        value={saveAsName}
        onChange={(e) => setSaveAsName(e.target.value)}
      />

      <button
        type="button"
        onClick={() => runMutation.mutate()}
        disabled={runMutation.isPending || Boolean(isRunning)}
        className="glow-button w-full rounded-lg py-2 font-semibold text-white transition-shadow disabled:opacity-40"
      >
        {isRunning ? '実行中...' : 'バックテスト実行'}
      </button>

      {statusData?.status === 'error' && (
        <div className="rounded-lg border border-red-500/20 bg-red-950/40 p-2.5 text-xs text-red-200">
          <p className="whitespace-pre-wrap leading-relaxed">
            {statusData.error_summary ?? 'バックテストの実行中にエラーが発生しました。'}
          </p>
          {statusData.error && (
            <details className="mt-2">
              <summary className="cursor-pointer text-red-400 hover:text-red-300">詳細を見る(技術情報)</summary>
              <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-black/30 p-2 text-[11px] text-red-300">
                {statusData.error}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
