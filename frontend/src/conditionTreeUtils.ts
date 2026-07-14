import { isGroup, type ConditionNode, type IndicatorInfo, type OptimizeField, type Operator, type TreeNode } from './types'

// Node-level condition-tree optimization helpers. These operate purely on
// the in-memory tree the builder UI already holds - a path here is just a
// sequence of child-indices from the root, only ever used transiently
// within a single render/submit (never sent to or parsed by the backend),
// so it doesn't need to survive tree edits or be validated server-side.

export interface OptimizableConditionOption {
  path: number[]
  field: OptimizeField
  label: string
}

function shortLabel(node: ConditionNode): string {
  const valueText = typeof node.value === 'number' ? '[値]' : String(node.value)
  return `${node.indicator} ${node.operator} ${valueText}`
}

/** Walks the tree collecting every sweepable number in every Condition node:
 * the comparison literal (if `value` is a plain number), every key in the
 * LEFT indicator's own `params` (e.g. ema's "length", bollinger's
 * "num_std"), and - only when the comparison side is itself an indicator -
 * every key in that side's `value_params`. Previously this only surfaced
 * the literal comparison target, so a condition like "close > ema(200)"
 * had no way to sweep ema's own length at all. Path numbering is 1-based
 * per level for display. */
export function collectOptimizableConditions(
  node: TreeNode,
  path: number[] = [],
  prefix = '',
): OptimizableConditionOption[] {
  if (isGroup(node)) {
    return node.children.flatMap((child, i) =>
      collectOptimizableConditions(child, [...path, i], `${prefix}${prefix ? '.' : ''}${i + 1}`),
    )
  }

  const options: OptimizableConditionOption[] = []
  const label = shortLabel(node)

  if (typeof node.value === 'number') {
    options.push({ path, field: { kind: 'value' }, label: `条件${prefix}: ${label}` })
  }

  for (const key of Object.keys(node.params)) {
    options.push({ path, field: { kind: 'params', key }, label: `条件${prefix}: ${node.indicator}の${key}` })
  }

  if (typeof node.value === 'string') {
    for (const key of Object.keys(node.value_params)) {
      options.push({
        path,
        field: { kind: 'value_params', key },
        label: `条件${prefix}: ${node.value}(比較先)の${key}`,
      })
    }
  }

  return options
}

/** Immutably clones `node` down to `path` and sets the number identified by
 * `field` - the comparison literal, or a specific key inside `params`/
 * `value_params`. */
export function setFieldAtPath(node: TreeNode, path: number[], field: OptimizeField, value: number): TreeNode {
  if (path.length === 0) {
    const cond = node as ConditionNode
    if (field.kind === 'value') {
      return { ...cond, value }
    }
    if (field.kind === 'params') {
      return { ...cond, params: { ...cond.params, [field.key]: value } }
    }
    return { ...cond, value_params: { ...cond.value_params, [field.key]: value } }
  }
  if (!isGroup(node)) {
    throw new Error('setFieldAtPath: path continues past a leaf Condition node')
  }
  const [head, ...rest] = path
  return {
    ...node,
    children: node.children.map((child, i) => (i === head ? setFieldAtPath(child, rest, field, value) : child)),
  }
}

/** True if `path`+`field` still resolves to a sweepable number in `node` -
 * used to detect a stale selection after the tree has been restructured
 * (e.g. the indicator at that path changed, so a param key that used to
 * exist no longer does). */
export function optionIsValid(node: TreeNode, path: number[], field: OptimizeField): boolean {
  if (path.length === 0) {
    if (isGroup(node)) return false
    if (field.kind === 'value') return typeof node.value === 'number'
    if (field.kind === 'params') return field.key in node.params
    return typeof node.value === 'string' && field.key in node.value_params
  }
  if (!isGroup(node) || path[0] >= node.children.length) {
    return false
  }
  return optionIsValid(node.children[path[0]], path.slice(1), field)
}

// Mirrors ConditionRow.tsx's OPERATORS list (kept in sync by hand - both are
// small, static, and rarely change).
const OPERATOR_LABELS: Record<Operator, string> = {
  '>': 'より上',
  '<': 'より下',
  '>=': '以上',
  '<=': '以下',
  '==': '一致',
  crosses_above: '上抜け',
  crosses_below: '下抜け',
}

function indicatorLabel(indicators: IndicatorInfo[], id: string): string {
  return indicators.find((i) => i.id === id)?.label ?? id
}

function paramsLabel(indicators: IndicatorInfo[], indicatorId: string, params: Record<string, number>): string {
  const info = indicators.find((i) => i.id === indicatorId)
  const entries = Object.entries(params)
  if (entries.length === 0) return ''
  const parts = entries.map(([key, v]) => {
    const paramLabel = info?.params.find((p) => p.name === key)?.label ?? key
    return `${paramLabel}=${v}`
  })
  return `(${parts.join(',')})`
}

/** Renders a condition tree as a compact, human-readable one-liner with
 * indicator names/params/operators translated to their Japanese labels (via
 * the /api/indicators registry) - used to show what an auto-generated
 * strategy (--optimizer structure/structure_genetic) actually consists of
 * (ランキング一覧の「条件」列, ストラテジー詳細). AND/OR/NOT are left as-is,
 * matching the manual builder's own group-operator dropdown (which also
 * never translates them). */
export function describeConditionTreeJapanese(node: TreeNode, indicators: IndicatorInfo[]): string {
  if (isGroup(node)) {
    if (node.op === 'NOT') {
      return `NOT(${node.children.map((c) => describeConditionTreeJapanese(c, indicators)).join(', ')})`
    }
    return `(${node.children.map((c) => describeConditionTreeJapanese(c, indicators)).join(` ${node.op} `)})`
  }

  const leftLabel = indicatorLabel(indicators, node.indicator)
  const leftParams = paramsLabel(indicators, node.indicator, node.params)
  const operatorLabel = OPERATOR_LABELS[node.operator] ?? node.operator

  if (typeof node.value === 'string') {
    const rightLabel = indicatorLabel(indicators, node.value)
    const rightParams = paramsLabel(indicators, node.value, node.value_params)
    return `${leftLabel}${leftParams} ${operatorLabel} ${rightLabel}${rightParams}`
  }

  const value = Number(node.value.toFixed(4))
  return `${leftLabel}${leftParams} ${operatorLabel} ${value}`
}

function cartesianProduct<T>(arrays: T[][]): T[][] {
  return arrays.reduce<T[][]>((acc, values) => acc.flatMap((combo) => values.map((v) => [...combo, v])), [[]])
}

/** Builds one condition_tree variant per combination of every enabled
 * range's values (a full cross product, same composition rule the legacy
 * BacktestConfig-field param_ranges already use) - N=1 range reduces to the
 * original single-node sweep exactly. If the same (path, field) appears in
 * more than one range, the later range's substitution wins for that
 * combination (not guarded against - a harmless, if confusing, user
 * configuration rather than something worth blocking). */
export function buildConditionTreeVariants(
  tree: TreeNode,
  ranges: { path: number[]; field: OptimizeField; values: number[] }[],
): TreeNode[] {
  if (ranges.length === 0) return []
  const combos = cartesianProduct(ranges.map((r) => r.values))
  return combos.map((combo) =>
    ranges.reduce((acc, r, i) => setFieldAtPath(acc, r.path, r.field, combo[i]), tree),
  )
}
