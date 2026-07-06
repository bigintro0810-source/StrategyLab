import { isGroup, type ConditionNode, type TreeNode } from './types'

// Node-level condition-tree optimization helpers. These operate purely on
// the in-memory tree the builder UI already holds - a path here is just a
// sequence of child-indices from the root, only ever used transiently
// within a single render/submit (never sent to or parsed by the backend),
// so it doesn't need to survive tree edits or be validated server-side.

export interface OptimizableConditionOption {
  path: number[]
  label: string
}

function shortLabel(node: ConditionNode): string {
  const valueText = typeof node.value === 'number' ? '[値]' : String(node.value)
  return `${node.indicator} ${node.operator} ${valueText}`
}

/** Walks the tree collecting every Condition node whose `value` is a plain
 * number (a literal comparison target) - only these have a meaningful
 * single number to sweep. Path numbering is 1-based per level for display. */
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
  if (typeof node.value === 'number') {
    return [{ path, label: `条件${prefix}: ${shortLabel(node)}` }]
  }
  return []
}

/** Immutably clones `node` down to `path` and sets that Condition's `value`. */
export function setValueAtPath(node: TreeNode, path: number[], value: number): TreeNode {
  if (path.length === 0) {
    return { ...(node as ConditionNode), value }
  }
  if (!isGroup(node)) {
    throw new Error('setValueAtPath: path continues past a leaf Condition node')
  }
  const [head, ...rest] = path
  return {
    ...node,
    children: node.children.map((child, i) => (i === head ? setValueAtPath(child, rest, value) : child)),
  }
}

/** True if `path` still resolves to a literal-valued Condition in `node` -
 * used to detect a stale selection after the tree has been restructured. */
export function pathIsValid(node: TreeNode, path: number[]): boolean {
  if (path.length === 0) {
    return !isGroup(node) && typeof node.value === 'number'
  }
  if (!isGroup(node) || path[0] >= node.children.length) {
    return false
  }
  return pathIsValid(node.children[path[0]], path.slice(1))
}

function cartesianProduct<T>(arrays: T[][]): T[][] {
  return arrays.reduce<T[][]>((acc, values) => acc.flatMap((combo) => values.map((v) => [...combo, v])), [[]])
}

/** Builds one condition_tree variant per combination of every enabled
 * range's values (a full cross product, same composition rule the legacy
 * BacktestConfig-field param_ranges already use) - N=1 range reduces to the
 * original single-node sweep exactly. If the same path appears in more than
 * one range, the later range's substitution wins for that combination
 * (not guarded against - a harmless, if confusing, user configuration
 * rather than something worth blocking). */
export function buildConditionTreeVariants(
  tree: TreeNode,
  ranges: { path: number[]; values: number[] }[],
): TreeNode[] {
  if (ranges.length === 0) return []
  const combos = cartesianProduct(ranges.map((r) => r.values))
  return combos.map((combo) => ranges.reduce((acc, r, i) => setValueAtPath(acc, r.path, combo[i]), tree))
}
