import type { ConditionNode, GroupNode, IndicatorInfo, TreeNode } from '../types'
import { isGroup } from '../types'
import ConditionRow from './ConditionRow'

interface Props {
  node: GroupNode
  indicators: IndicatorInfo[]
  onChange: (next: GroupNode) => void
  onRemove?: () => void
  depth?: number
}

function defaultCondition(indicators: IndicatorInfo[]): ConditionNode {
  const first = indicators[0]
  return {
    indicator: first?.id ?? 'close',
    operator: '>',
    value: 0,
    params: first?.needs_period ? { length: 14 } : {},
    value_params: {},
  }
}

function defaultGroup(indicators: IndicatorInfo[]): GroupNode {
  return { op: 'AND', children: [defaultCondition(indicators)] }
}

export default function ConditionTreeEditor({ node, indicators, onChange, onRemove, depth = 0 }: Props) {
  const isNot = node.op === 'NOT'

  const updateChild = (index: number, child: TreeNode) => {
    const children = node.children.slice()
    children[index] = child
    onChange({ ...node, children })
  }

  const removeChild = (index: number) => {
    const children = node.children.slice()
    children.splice(index, 1)
    onChange({ ...node, children })
  }

  const addCondition = () => {
    if (isNot && node.children.length >= 1) return
    onChange({ ...node, children: [...node.children, defaultCondition(indicators)] })
  }

  const addGroup = () => {
    if (isNot && node.children.length >= 1) return
    onChange({ ...node, children: [...node.children, defaultGroup(indicators)] })
  }

  return (
    <div
      className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2"
      style={{ marginLeft: depth > 0 ? 12 : 0 }}
    >
      <div className="flex items-center gap-2">
        <select
          className="glass-input rounded-lg px-2 py-1 text-sm font-semibold"
          value={node.op}
          onChange={(e) => onChange({ ...node, op: e.target.value as GroupNode['op'] })}
        >
          <option value="AND">AND</option>
          <option value="OR">OR</option>
          <option value="NOT">NOT</option>
        </select>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-xs text-red-300 hover:bg-red-500/20"
          >
            グループ削除
          </button>
        )}
      </div>

      {node.children.map((child, i) => {
        // A group (this one) can never be left with zero children - the
        // engine rejects an empty AND/OR/NOT with a raw Python traceback
        // (engine/conditions.py's ConditionGroup.__post_init__), so hide the
        // remove button on the last remaining child instead of letting the
        // user reach that state from the UI at all.
        const canRemove = node.children.length > 1
        return isGroup(child) ? (
          <ConditionTreeEditor
            key={i}
            node={child}
            indicators={indicators}
            depth={depth + 1}
            onChange={(next) => updateChild(i, next)}
            onRemove={canRemove ? () => removeChild(i) : undefined}
          />
        ) : (
          <ConditionRow
            key={i}
            node={child}
            indicators={indicators}
            onChange={(next) => updateChild(i, next)}
            onRemove={canRemove ? () => removeChild(i) : undefined}
          />
        )
      })}

      {(!isNot || node.children.length === 0) && (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={addCondition}
            className="rounded-lg border border-blue-400/20 bg-blue-400/10 px-2 py-1 text-xs text-blue-200 hover:bg-blue-400/20"
          >
            + 条件を追加
          </button>
          <button
            type="button"
            onClick={addGroup}
            className="rounded-lg border border-purple-400/20 bg-purple-400/10 px-2 py-1 text-xs text-purple-200 hover:bg-purple-400/20"
          >
            + グループを追加
          </button>
        </div>
      )}
    </div>
  )
}
