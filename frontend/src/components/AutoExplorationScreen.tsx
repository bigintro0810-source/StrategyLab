import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchExplorationCategories } from '../api'
import { groupIndicatorsByGenre } from '../conditionGenres'
import ConditionRow, { defaultParamsFor } from './ConditionRow'
import type { BacktestStatus, ConditionNode, IndicatorInfo } from '../types'

type ExplorationMode = 'manual' | 'structure' | 'structure_genetic'

const RR_PRESETS = [1.0, 1.2, 1.5, 2.0, 2.5, 3.0]

// デフォルト指標は一番上のジャンル「インジケーター」の先頭(EMAなど)にする
// (ユーザー報告:「インジケーター等ジャンルを選択する際に最初価格データが
// 選択されてる。一番上がインジケーターだからインジケーターを選択して
// いてほしい」- ConditionTreeEditor.tsxのdefaultConditionと同じ規則)。
function defaultMandatoryCondition(indicators: IndicatorInfo[]): ConditionNode {
  const first = groupIndicatorsByGenre(indicators)[0]?.items[0]
  return {
    indicator: first?.id ?? 'close',
    operator: '>',
    value: 0,
    params: defaultParamsFor(first),
    value_params: {},
  }
}

// 実測ベースの概算(dev軽量モード、structure=ランダム探索、候補500件で約
// 211秒・候補50件で約30秒だった実測から算出): 固定オーバーヘッド約10秒 +
// 候補1件あたり約0.40秒。RRを複数選ぶとその分だけバックテスト回数が
// 単純倍加する(main.py::build_grid_from_spaceのitertools.product)。
function estimateSeconds(nCandidates: number, rrCount: number): number {
  return 10 + nCandidates * 0.4 * Math.max(rrCount, 1)
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `約${Math.round(seconds)}秒`
  const minutes = seconds / 60
  if (minutes < 60) return `約${Math.round(minutes)}分`
  const hours = minutes / 60
  if (hours < 24) return `約${hours.toFixed(1)}時間`
  return `約${(hours / 24).toFixed(1)}日`
}

interface Props {
  explorationMode: ExplorationMode
  setExplorationMode: (mode: ExplorationMode) => void
  explorationAdvOpen: boolean
  setExplorationAdvOpen: (fn: (v: boolean) => boolean) => void
  categories: string[]
  setCategories: (fn: (v: string[]) => string[]) => void
  customIndicatorNames: string[]
  setCustomIndicatorNames: (fn: (v: string[]) => string[]) => void
  selectedParamValues: Record<string, Record<string, number[]>>
  setSelectedParamValues: (
    fn: (v: Record<string, Record<string, number[]>>) => Record<string, Record<string, number[]>>,
  ) => void
  selectedLiteralValues: Record<string, number[]>
  setSelectedLiteralValues: (fn: (v: Record<string, number[]>) => Record<string, number[]>) => void
  nCandidates: number
  setNCandidates: (v: number) => void
  maxDepth: number
  setMaxDepth: (v: number) => void
  minLeaves: number
  setMinLeaves: (v: number) => void
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
  rrChoices: number[]
  setRrChoices: (fn: (v: number[]) => number[]) => void
  mandatoryConditions: ConditionNode[]
  setMandatoryConditions: (fn: (v: ConditionNode[]) => ConditionNode[]) => void
  indicators: IndicatorInfo[]
  saveAsName: string
  setSaveAsName: (v: string) => void
  statusData: BacktestStatus | undefined
}

export default function AutoExplorationScreen({
  explorationMode,
  setExplorationMode,
  explorationAdvOpen,
  setExplorationAdvOpen,
  categories,
  setCategories,
  customIndicatorNames,
  setCustomIndicatorNames,
  selectedParamValues,
  setSelectedParamValues,
  selectedLiteralValues,
  setSelectedLiteralValues,
  nCandidates,
  setNCandidates,
  maxDepth,
  setMaxDepth,
  minLeaves,
  setMinLeaves,
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
  rrChoices,
  setRrChoices,
  mandatoryConditions,
  setMandatoryConditions,
  indicators,
  saveAsName,
  setSaveAsName,
  statusData,
}: Props) {
  const categoriesQuery = useQuery({
    queryKey: ['exploration-categories'],
    queryFn: fetchExplorationCategories,
  })
  const [expandedCategories, setExpandedCategories] = useState<string[]>([])
  const [valueExpandedIds, setValueExpandedIds] = useState<string[]>([])

  const toggleCategory = (id: string) => {
    const cat = categoriesQuery.data?.categories.find((c) => c.id === id)
    const isAdding = !categories.includes(id)
    setCategories((prev) => (isAdding ? [...prev, id] : prev.filter((c) => c !== id)))
    // customIndicatorNames=[] means "every indicator in every checked
    // category" (the implicit default) - only reconciled into an explicit
    // list once the user has actually narrowed something down.
    if (cat) {
      setCustomIndicatorNames((prev) => {
        if (prev.length === 0) return prev
        if (isAdding) {
          const toAdd = cat.names.map((n) => n.id).filter((n) => !prev.includes(n))
          return [...prev, ...toAdd]
        }
        return prev.filter((n) => !cat.names.some((cn) => cn.id === n))
      })
    }
  }

  const isIndicatorChecked = (id: string) => customIndicatorNames.length === 0 || customIndicatorNames.includes(id)

  const toggleIndicatorName = (id: string) => {
    setCustomIndicatorNames((prev) => {
      const base =
        prev.length === 0
          ? (categoriesQuery.data?.categories ?? [])
              .filter((c) => categories.includes(c.id))
              .flatMap((c) => c.names.map((n) => n.id))
          : prev
      return base.includes(id) ? base.filter((n) => n !== id) : [...base, id]
    })
  }

  const toggleCategoryExpanded = (id: string) =>
    setExpandedCategories((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]))

  const toggleValueExpanded = (id: string) =>
    setValueExpandedIds((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]))

  const isValueChecked = (indId: string, paramName: string, value: number) => {
    const sel = selectedParamValues[indId]?.[paramName]
    return !sel || sel.length === 0 || sel.includes(value)
  }
  const toggleParamValue = (indId: string, paramName: string, value: number, allValues: number[]) => {
    setSelectedParamValues((prev) => {
      const current = prev[indId]?.[paramName]
      const base = current && current.length > 0 ? current : allValues
      const next = base.includes(value) ? base.filter((v) => v !== value) : [...base, value]
      return { ...prev, [indId]: { ...prev[indId], [paramName]: next } }
    })
  }

  const isLiteralChecked = (indId: string, value: number) => {
    const sel = selectedLiteralValues[indId]
    return !sel || sel.length === 0 || sel.includes(value)
  }
  const toggleLiteralValue = (indId: string, value: number, allValues: number[]) => {
    setSelectedLiteralValues((prev) => {
      const current = prev[indId]
      const base = current && current.length > 0 ? current : allValues
      const next = base.includes(value) ? base.filter((v) => v !== value) : [...base, value]
      return { ...prev, [indId]: next }
    })
  }

  const estimatedSeconds = estimateSeconds(nCandidates, rrChoices.length)

  return (
    <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-4">
      {/* 左カラム: エントリー条件(カテゴリ+指標+数値) */}
      <div className="glass-panel flex flex-col rounded-2xl">
        <div className="glass-panel-header rounded-t-2xl px-3 py-2 text-sm font-semibold tracking-wide text-gray-200">
          エントリー条件(自動生成対象)
        </div>
        <div className="space-y-2 p-3">
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

          <div className="text-sm font-semibold text-gray-300">
            条件カテゴリ・指標・数値
            <span className="ml-2 text-[10px] font-normal text-gray-500">
              (チェックした指標・数値だけがランダム生成の候補プールになります)
            </span>
          </div>
          <div className="max-h-[520px] space-y-1.5 overflow-y-auto text-xs text-gray-300">
            {categoriesQuery.data?.categories.map((cat) => {
              const isChecked = categories.includes(cat.id)
              const isExpanded = expandedCategories.includes(cat.id)
              const selectedCount = cat.names.filter((n) => isIndicatorChecked(n.id)).length
              return (
                <div key={cat.id}>
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={isChecked} onChange={() => toggleCategory(cat.id)} />
                    {cat.label}
                    <span className="text-gray-500">
                      ({selectedCount < cat.count ? `${selectedCount}/${cat.count}` : cat.count})
                    </span>
                    {isChecked && cat.names.length > 0 && (
                      <button
                        type="button"
                        onClick={() => toggleCategoryExpanded(cat.id)}
                        className="ml-auto text-[10px] text-gray-500 hover:text-gray-300"
                      >
                        {isExpanded ? '個別指定を閉じる ▴' : '個別指定 ▾'}
                      </button>
                    )}
                  </label>
                  {isChecked && isExpanded && (
                    <div className="ml-5 mt-1 space-y-1 border-l border-white/10 pl-2">
                      {cat.names.map((n) => {
                        const hasValues = Object.keys(n.param_presets).length > 0 || n.literal_presets
                        const isValExpanded = valueExpandedIds.includes(n.id)
                        return (
                          <div key={n.id}>
                            <label className="flex items-center gap-1 text-[10.5px] text-gray-400">
                              <input
                                type="checkbox"
                                checked={isIndicatorChecked(n.id)}
                                onChange={() => toggleIndicatorName(n.id)}
                              />
                              {n.label}
                              {hasValues && isIndicatorChecked(n.id) && (
                                <button
                                  type="button"
                                  onClick={() => toggleValueExpanded(n.id)}
                                  className="text-[9px] text-gray-600 hover:text-gray-400"
                                >
                                  {isValExpanded ? '数値 ▴' : '数値 ▾'}
                                </button>
                              )}
                            </label>
                            {hasValues && isIndicatorChecked(n.id) && isValExpanded && (
                              <div className="ml-5 mt-0.5 space-y-0.5 border-l border-white/5 pl-2">
                                {Object.entries(n.param_presets).map(([paramName, values]) => (
                                  <div key={paramName} className="flex flex-wrap items-center gap-1 text-[9.5px]">
                                    <span className="text-gray-600">{paramName}:</span>
                                    {values.map((v) => (
                                      <label
                                        key={v}
                                        className="flex items-center gap-0.5 rounded bg-white/5 px-1 text-gray-400"
                                      >
                                        <input
                                          type="checkbox"
                                          checked={isValueChecked(n.id, paramName, v)}
                                          onChange={() => toggleParamValue(n.id, paramName, v, values)}
                                        />
                                        {v}
                                      </label>
                                    ))}
                                  </div>
                                ))}
                                {n.literal_presets && (
                                  <div className="flex flex-wrap items-center gap-1 text-[9.5px]">
                                    <span className="text-gray-600">閾値:</span>
                                    {n.literal_presets.map((v) => (
                                      <label
                                        key={v}
                                        className="flex items-center gap-0.5 rounded bg-white/5 px-1 text-gray-400"
                                      >
                                        <input
                                          type="checkbox"
                                          checked={isLiteralChecked(n.id, v)}
                                          onChange={() => toggleLiteralValue(n.id, v, n.literal_presets!)}
                                        />
                                        {v}
                                      </label>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
            {categories.length === 0 && <p className="text-[10px] text-amber-400">カテゴリを1つ以上選んでください。</p>}
          </div>
        </div>
      </div>

      {/* 右カラム: 決済条件・必須固定条件・実行設定(方向・期間は共通トップバーへ移動) */}
      <div className="space-y-4">
        <div className="glass-panel rounded-2xl p-3">
          <div className="mb-2 text-sm font-semibold text-gray-300">決済条件</div>
          <div className="mb-1 text-[10px] text-gray-500">利確/損切りのRR(リスクリワード比)の候補。複数選ぶと候補ごとに全パターン検証します。</div>
          <div className="flex flex-wrap gap-1.5 text-xs">
            {RR_PRESETS.map((rr) => (
              <label
                key={rr}
                className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.02] px-2 py-1 text-gray-300"
              >
                <input
                  type="checkbox"
                  checked={rrChoices.includes(rr)}
                  onChange={() =>
                    setRrChoices((prev) =>
                      prev.includes(rr) ? prev.filter((r) => r !== rr) : [...prev, rr].sort((a, b) => a - b),
                    )
                  }
                />
                RR {rr}
              </label>
            ))}
          </div>
          {rrChoices.length === 0 && <p className="mt-1 text-[10px] text-gray-500">未選択の場合はRR=1.2で固定されます。</p>}
        </div>

        <div className="glass-panel rounded-2xl p-3">
          <div className="mb-2 text-sm font-semibold text-gray-300">必須固定条件</div>
          <div className="mb-1 text-[10px] text-gray-500">
            生成される全ての戦略に必ずANDで追加される条件です(「条件数」のカウントには含まれません)。
          </div>
          <div className="space-y-1.5">
            {mandatoryConditions.map((cond, i) => (
              <ConditionRow
                key={i}
                node={cond}
                indicators={indicators}
                onChange={(next) =>
                  setMandatoryConditions((prev) => prev.map((c, idx) => (idx === i ? next : c)))
                }
                onRemove={() => setMandatoryConditions((prev) => prev.filter((_, idx) => idx !== i))}
              />
            ))}
            <button
              type="button"
              onClick={() => setMandatoryConditions((prev) => [...prev, defaultMandatoryCondition(indicators)])}
              className="text-xs text-purple-300 hover:underline"
            >
              + 必須条件を追加
            </button>
          </div>
        </div>

        <div className="glass-panel rounded-2xl p-3">
          <div className="mb-2 text-sm font-semibold text-gray-300">実行設定</div>
          <div className="space-y-1.5 text-xs text-gray-300">
            <label className="flex items-center justify-between gap-2">
              条件数(min〜max)
              <span className="flex items-center gap-1">
                <input
                  type="number"
                  min={1}
                  max={10}
                  className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs"
                  value={minLeaves}
                  onChange={(e) => setMinLeaves(Number(e.target.value))}
                />
                〜
                <input
                  type="number"
                  min={1}
                  max={10}
                  className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs"
                  value={maxLeaves}
                  onChange={(e) => setMaxLeaves(Number(e.target.value))}
                />
              </span>
            </label>
            <label className="flex items-center justify-between gap-2">
              候補数(n-candidates)
              <input
                type="number"
                min={1}
                max={1000000}
                className="glass-input w-28 rounded-lg px-1.5 py-1 text-xs"
                value={nCandidates}
                onChange={(e) => setNCandidates(Number(e.target.value))}
              />
            </label>
            <p className="text-[10px] text-gray-500">
              推定実行時間: {formatDuration(estimatedSeconds)}(このPCでの実測に基づく概算です)
            </p>

            <button
              type="button"
              onClick={() => setExplorationAdvOpen((v) => !v)}
              className="flex items-center gap-1.5 pt-1 text-[10.5px] text-gray-400 hover:text-gray-200"
            >
              <span className={`text-[9px] transition-transform ${explorationAdvOpen ? 'rotate-90' : ''}`}>▸</span>
              詳細設定(条件生成・AI進化)
            </button>
            {explorationAdvOpen && (
              <div className="space-y-1.5 rounded-lg border border-white/10 bg-white/[0.02] p-2">
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

            <input
              type="text"
              placeholder="名前を付けて保存(任意)"
              className="glass-input mt-1 w-full rounded-lg px-2 py-1.5 text-xs"
              value={saveAsName}
              onChange={(e) => setSaveAsName(e.target.value)}
            />

            {categories.length === 0 && (
              <p className="text-[10px] text-amber-400">カテゴリを1つ以上選んでください(実行ボタンは上部にあります)。</p>
            )}

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
        </div>
      </div>
    </div>
  )
}
