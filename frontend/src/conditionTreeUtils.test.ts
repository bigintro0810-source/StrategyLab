import { describe, expect, it } from 'vitest'
import {
  buildConditionTreeVariants,
  collectOptimizableConditions,
  pathIsValid,
  setValueAtPath,
} from './conditionTreeUtils'
import type { ConditionNode, GroupNode } from './types'

function condition(overrides: Partial<ConditionNode> = {}): ConditionNode {
  return {
    indicator: 'rsi',
    operator: '>',
    value: 70,
    params: {},
    value_params: {},
    ...overrides,
  }
}

// AND(rsi > 70, OR(close < ema200 [string value, not sweepable], atr >= 14))
function sampleTree(): GroupNode {
  return {
    op: 'AND',
    children: [
      condition({ indicator: 'rsi', operator: '>', value: 70 }),
      {
        op: 'OR',
        children: [
          condition({ indicator: 'close', operator: '<', value: 'ema200' }),
          condition({ indicator: 'atr', operator: '>=', value: 14 }),
        ],
      },
    ],
  }
}

describe('collectOptimizableConditions', () => {
  it('only collects Condition nodes with a literal numeric value', () => {
    const options = collectOptimizableConditions(sampleTree())
    expect(options).toEqual([
      { path: [0], label: '条件1: rsi > [値]' },
      { path: [1, 1], label: '条件2.2: atr >= [値]' },
    ])
  })

  it('returns nothing for a tree with no numeric-valued conditions', () => {
    const tree: GroupNode = {
      op: 'AND',
      children: [condition({ value: 'ema200' })],
    }
    expect(collectOptimizableConditions(tree)).toEqual([])
  })
})

describe('setValueAtPath', () => {
  it('sets the value at the given path without mutating the original tree', () => {
    const tree = sampleTree()
    const updated = setValueAtPath(tree, [0], 80) as GroupNode
    expect((updated.children[0] as ConditionNode).value).toBe(80)
    expect((tree.children[0] as ConditionNode).value).toBe(70)
  })

  it('sets a value nested inside a subgroup', () => {
    const tree = sampleTree()
    const updated = setValueAtPath(tree, [1, 1], 20) as GroupNode
    const subgroup = updated.children[1] as GroupNode
    expect((subgroup.children[1] as ConditionNode).value).toBe(20)
  })

  it('throws when the path continues past a leaf Condition', () => {
    const tree = sampleTree()
    expect(() => setValueAtPath(tree, [0, 0], 1)).toThrow()
  })
})

describe('pathIsValid', () => {
  it('is true for a path resolving to a numeric-valued condition', () => {
    const tree = sampleTree()
    expect(pathIsValid(tree, [0])).toBe(true)
    expect(pathIsValid(tree, [1, 1])).toBe(true)
  })

  it('is false for a path resolving to a string-valued condition', () => {
    expect(pathIsValid(sampleTree(), [1, 0])).toBe(false)
  })

  it('is false for an out-of-range index', () => {
    expect(pathIsValid(sampleTree(), [5])).toBe(false)
  })

  it('is false when the path continues past a leaf Condition', () => {
    expect(pathIsValid(sampleTree(), [0, 0])).toBe(false)
  })
})

describe('buildConditionTreeVariants', () => {
  it('returns an empty array when no ranges are given', () => {
    expect(buildConditionTreeVariants(sampleTree(), [])).toEqual([])
  })

  it('builds one variant per value for a single range', () => {
    const variants = buildConditionTreeVariants(sampleTree(), [{ path: [0], values: [60, 70, 80] }])
    expect(variants).toHaveLength(3)
    const values = variants.map((v) => ((v as GroupNode).children[0] as ConditionNode).value)
    expect(values).toEqual([60, 70, 80])
  })

  it('builds the full cross product for multiple independent ranges', () => {
    const variants = buildConditionTreeVariants(sampleTree(), [
      { path: [0], values: [60, 70] },
      { path: [1, 1], values: [10, 14] },
    ])
    expect(variants).toHaveLength(4)
    const combos = variants.map((v) => {
      const g = v as GroupNode
      const first = (g.children[0] as ConditionNode).value
      const second = ((g.children[1] as GroupNode).children[1] as ConditionNode).value
      return [first, second]
    })
    expect(combos).toEqual([
      [60, 10],
      [60, 14],
      [70, 10],
      [70, 14],
    ])
  })
})
