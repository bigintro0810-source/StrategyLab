import type { ConditionNode, IndicatorInfo, Operator } from '../types'

const OPERATORS: { id: Operator; label: string }[] = [
  { id: '>', label: 'より上 (>)' },
  { id: '<', label: 'より下 (<)' },
  { id: '>=', label: '以上 (>=)' },
  { id: '<=', label: '以下 (<=)' },
  { id: '==', label: '一致 (==)' },
  { id: 'crosses_above', label: '上抜け' },
  { id: 'crosses_below', label: '下抜け' },
]

interface Props {
  node: ConditionNode
  indicators: IndicatorInfo[]
  onChange: (next: ConditionNode) => void
  onRemove: () => void
}

function indicatorInfo(indicators: IndicatorInfo[], id: string): IndicatorInfo | undefined {
  return indicators.find((i) => i.id === id)
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
            params: nextInfo?.needs_period ? { length: node.params.length ?? 14 } : {},
          })
        }}
      >
        {indicators.map((ind) => (
          <option key={ind.id} value={ind.id}>
            {ind.label}
          </option>
        ))}
      </select>

      {info?.needs_period && (
        <input
          type="number"
          className="w-16 glass-input rounded-lg px-2 py-1"
          value={node.params.length ?? 14}
          onChange={(e) => onChange({ ...node, params: { length: Number(e.target.value) } })}
        />
      )}

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
              value_params: first?.needs_period ? { length: 14 } : {},
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
                value_params: nextInfo?.needs_period ? { length: 14 } : {},
              })
            }}
          >
            {indicators.map((ind) => (
              <option key={ind.id} value={ind.id}>
                {ind.label}
              </option>
            ))}
          </select>
          {valueIndicatorInfo?.needs_period && (
            <input
              type="number"
              className="w-16 glass-input rounded-lg px-2 py-1"
              value={node.value_params.length ?? 14}
              onChange={(e) => onChange({ ...node, value_params: { length: Number(e.target.value) } })}
            />
          )}
        </>
      )}

      <button
        type="button"
        onClick={onRemove}
        className="ml-auto rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-red-300 hover:bg-red-500/20"
      >
        削除
      </button>
    </div>
  )
}
