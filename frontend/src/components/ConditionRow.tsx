import type { ConditionNode, ConditionParams, IndicatorInfo, IndicatorParamSpec, Operator } from '../types'

const OPERATORS: { id: Operator; label: string }[] = [
  { id: '>', label: 'より上 (>)' },
  { id: '<', label: 'より下 (<)' },
  { id: '>=', label: '以上 (>=)' },
  { id: '<=', label: '以下 (<=)' },
  { id: '==', label: '一致 (==)' },
  { id: 'crosses_above', label: '上抜け' },
  { id: 'crosses_below', label: '下抜け' },
]

// Multi-timeframe conditions: reference a different timeframe's own data
// for this indicator (e.g. a 15m strategy filtering by a 1h/4h/daily EMA).
// The empty option means "no override" (undefined - the backtest's own base
// timeframe, today's existing behavior).
const TIMEFRAME_OPTIONS = ['1m', '5m', '10m', '15m', '30m', '1h', '4h', '1d', '1w', '1mo']

interface Props {
  node: ConditionNode
  indicators: IndicatorInfo[]
  onChange: (next: ConditionNode) => void
  onRemove?: () => void
}

function indicatorInfo(indicators: IndicatorInfo[], id: string): IndicatorInfo | undefined {
  return indicators.find((i) => i.id === id)
}

export function defaultParamsFor(info: IndicatorInfo | undefined): ConditionParams {
  if (!info) return {}
  const params: ConditionParams = {}
  for (const spec of info.params) {
    params[spec.name] = spec.default
  }
  return params
}

// One input per declared param (int/float -> number input, choice -> select
// of the conventional values only, e.g. Fibonacci's ratio) - previously
// this only ever rendered a single hardcoded "length" field, so indicators
// with more than one real parameter (bollinger's num_std, macd's
// fast/slow/signal, stochastic's 3 periods, ichimoku's 3 periods, fib's
// ratio) silently kept their Python-side default for every param past the
// first.
function ParamInputs({
  info,
  params,
  onChange,
}: {
  info: IndicatorInfo | undefined
  params: ConditionParams
  onChange: (next: ConditionParams) => void
}) {
  if (!info || info.params.length === 0) return null

  return (
    <>
      {info.params.map((spec: IndicatorParamSpec) =>
        spec.type === 'choice' ? (
          <select
            key={spec.name}
            title={spec.label}
            className="glass-input w-20 rounded-lg px-2 py-1 text-xs"
            value={params[spec.name] ?? spec.default}
            onChange={(e) => onChange({ ...params, [spec.name]: Number(e.target.value) })}
          >
            {(spec.choices ?? []).map((choice) => (
              <option key={choice} value={choice}>
                {spec.label}:{choice}
              </option>
            ))}
          </select>
        ) : (
          <input
            key={spec.name}
            type="number"
            step={spec.type === 'float' ? '0.1' : '1'}
            title={spec.label}
            placeholder={spec.label}
            className="w-16 glass-input rounded-lg px-2 py-1"
            value={params[spec.name] ?? spec.default}
            onChange={(e) => onChange({ ...params, [spec.name]: Number(e.target.value) })}
          />
        )
      )}
    </>
  )
}

export default function ConditionRow({ node, indicators, onChange, onRemove }: Props) {
  const compareMode = typeof node.value === 'string' ? 'indicator' : 'literal'
  const info = indicatorInfo(indicators, node.indicator)
  const valueIndicatorInfo = typeof node.value === 'string' ? indicatorInfo(indicators, node.value) : undefined

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] p-2 text-sm">
      <select
        className="glass-input rounded-lg px-2 py-1"
        value={node.indicator}
        onChange={(e) => {
          const nextInfo = indicatorInfo(indicators, e.target.value)
          onChange({
            ...node,
            indicator: e.target.value,
            params: defaultParamsFor(nextInfo),
          })
        }}
      >
        {indicators.map((ind) => (
          <option key={ind.id} value={ind.id}>
            {ind.label}
          </option>
        ))}
      </select>

      <ParamInputs info={info} params={node.params} onChange={(next) => onChange({ ...node, params: next })} />

      <select
        className="glass-input rounded-lg px-1 py-1 text-xs"
        title="この指標を計算する時間足(未指定ならバックテスト自体の時間足)"
        value={node.timeframe ?? ''}
        onChange={(e) => onChange({ ...node, timeframe: e.target.value || undefined })}
      >
        <option value="">(自足)</option>
        {TIMEFRAME_OPTIONS.map((tf) => (
          <option key={tf} value={tf}>
            {tf}
          </option>
        ))}
      </select>

      <select
        className="glass-input rounded-lg px-2 py-1"
        value={node.operator}
        onChange={(e) => onChange({ ...node, operator: e.target.value as Operator })}
      >
        {OPERATORS.map((op) => (
          <option key={op.id} value={op.id}>
            {op.label}
          </option>
        ))}
      </select>

      <select
        className="glass-input rounded-lg px-2 py-1"
        value={compareMode}
        onChange={(e) => {
          if (e.target.value === 'literal') {
            onChange({ ...node, value: 0, value_params: {} })
          } else {
            const first = indicators[0]
            onChange({
              ...node,
              value: first?.id ?? 'close',
              value_params: defaultParamsFor(first),
            })
          }
        }}
      >
        <option value="literal">固定値</option>
        <option value="indicator">指標</option>
      </select>

      {compareMode === 'literal' ? (
        <input
          type="number"
          className="w-20 glass-input rounded-lg px-2 py-1"
          value={node.value as number}
          onChange={(e) => onChange({ ...node, value: Number(e.target.value) })}
        />
      ) : (
        <>
          <select
            className="glass-input rounded-lg px-2 py-1"
            value={node.value as string}
            onChange={(e) => {
              const nextInfo = indicatorInfo(indicators, e.target.value)
              onChange({
                ...node,
                value: e.target.value,
                value_params: defaultParamsFor(nextInfo),
              })
            }}
          >
            {indicators.map((ind) => (
              <option key={ind.id} value={ind.id}>
                {ind.label}
              </option>
            ))}
          </select>
          <ParamInputs
            info={valueIndicatorInfo}
            params={node.value_params}
            onChange={(next) => onChange({ ...node, value_params: next })}
          />
          <select
            className="glass-input rounded-lg px-1 py-1 text-xs"
            title="この指標を計算する時間足(未指定ならバックテスト自体の時間足)"
            value={node.value_timeframe ?? ''}
            onChange={(e) => onChange({ ...node, value_timeframe: e.target.value || undefined })}
          >
            <option value="">(自足)</option>
            {TIMEFRAME_OPTIONS.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </>
      )}

      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="ml-auto rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-red-300 hover:bg-red-500/20"
        >
          削除
        </button>
      )}
    </div>
  )
}
