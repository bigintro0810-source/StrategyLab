import { describe, expect, it } from 'vitest'
import {
  buildConditionTreeVariants,
  collectOptimizableConditions,
  optionIsValid,
  setFieldAtPath,
} from './conditionTreeUtils'
import type { ConditionNode, GroupNode, OptimizeField } from './types'

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

// AND(
//   rsi(length=14) > 70                              -- literal + own param
//   OR(
//     close < ema(length=200)  [indicator-vs-indicator, ema has its own param]
//     atr >= 14                                       -- literal, no own param
//   )
// )
function sampleTree(): GroupNode {
  return {
    op: 'AND',
    children: [
      condition({ indicator: 'rsi', operator: '>', value: 70, params: { length: 14 } }),
      {
        op: 'OR',
        children: [
          condition({
            indicator: 'close',
            operator: '<',
            value: 'ema',
            value_params: { length: 200 },
          }),
          condition({ indicator: 'atr', operator: '>=', value: 14 }),
        ],
      },
    ],
  }
}

describe('collectOptimizableConditions', () => {
  it('collects the literal value AND the indicator\'s own params', () => {
    const options = collectOptimizableConditions(sampleTree())
    expect(options).toEqual([
      { path: [0], field: { kind: 'value' }, label: '条件1: rsi > [値]' },
      { path: [0], field: { kind: 'params', key: 'length' }, label: '条件1: rsiのlength' },
      {
        path: [1, 0],
        field: { kind: 'value_params', key: 'length' },
        label: '条件2.1: ema(比較先)のlength',
      },
      { path: [1, 1], field: { kind: 'value' }, label: '条件2.2: atr >= [値]' },
    ])
  })

  it('does not surface value_params for a literal-valued condition', () => {
    const tree: GroupNode = {
      op: 'AND',
      children: [condition({ value: 14, value_params: { length: 999 } })],
    }
    const options = collectOptimizableConditions(tree)
    expect(options.some((o) => o.field.kind === 'value_params')).toBe(false)
  })

  it('returns nothing for a tree with no literal value and no params on either side', () => {
    const tree: GroupNode = {
      op: 'AND',
      children: [condition({ indicator: 'close', value: 'ema200' })],
    }
    expect(collectOptimizableConditions(tree)).toEqual([])
  })
})

describe('setFieldAtPath', () => {
  it('sets the literal value without mutating the original tree', () => {
    const tree = sampleTree()
    const updated = setFieldAtPath(tree, [0], { kind: 'value' }, 80) as GroupNode
    expect((updated.children[0] as ConditionNode).value).toBe(80)
    expect((tree.children[0] as ConditionNode).value).toBe(70)
  })

  it('sets a key inside params without disturbing other param keys', () => {
    const tree = sampleTree()
    const updated = setFieldAtPath(tree, [0], { kind: 'params', key: 'length' }, 21) as GroupNode
    const cond = updated.children[0] as ConditionNode
    expect(cond.params.length).toBe(21)
    expect(cond.value).toBe(70)
  })

  it('sets a key inside value_params nested in a subgroup', () => {
    const tree = sampleTree()
    const updated = setFieldAtPath(tree, [1, 0], { kind: 'value_params', key: 'length' }, 50) as GroupNode
    const subgroup = updated.children[1] as GroupNode
    expect((subgroup.children[0] as ConditionNode).value_params.length).toBe(50)
  })

  it('throws when the path continues past a leaf Condition', () => {
    const tree = sampleTree()
    expect(() => setFieldAtPath(tree, [0, 0], { kind: 'value' }, 1)).toThrow()
  })
})

describe('optionIsValid', () => {
  it('is true for a path/field resolving to the literal value', () => {
    const tree = sampleTree()
    expect(optionIsValid(tree, [0], { kind: 'value' })).toBe(true)
    expect(optionIsValid(tree, [1, 1], { kind: 'value' })).toBe(true)
  })

  it('is true for a path/field resolving to an existing params key', () => {
    expect(optionIsValid(sampleTree(), [0], { kind: 'params', key: 'length' })).toBe(true)
  })

  it('is true for a path/field resolving to an existing value_params key on an indicator-valued condition', () => {
    expect(optionIsValid(sampleTree(), [1, 0], { kind: 'value_params', key: 'length' })).toBe(true)
  })

  it('is false when value_params is targeted but the comparison side is a literal, not an indicator', () => {
    expect(optionIsValid(sampleTree(), [1, 1], { kind: 'value_params', key: 'length' })).toBe(false)
  })

  it('is false for a params key that does not exist on that condition', () => {
    expect(optionIsValid(sampleTree(), [1, 1], { kind: 'params', key: 'period' })).toBe(false)
  })

  it('is false for an out-of-range index', () => {
    expect(optionIsValid(sampleTree(), [5], { kind: 'value' })).toBe(false)
  })

  it('is false when the path continues past a leaf Condition', () => {
    expect(optionIsValid(sampleTree(), [0, 0], { kind: 'value' })).toBe(false)
  })
})

describe('buildConditionTreeVariants', () => {
  it('returns an empty array when no ranges are given', () => {
    expect(buildConditionTreeVariants(sampleTree(), [])).toEqual([])
  })

  it('builds one variant per value for a single literal-value range', () => {
    const variants = buildConditionTreeVariants(sampleTree(), [
      { path: [0], field: { kind: 'value' }, values: [60, 70, 80] },
    ])
    expect(variants).toHaveLength(3)
    const values = variants.map((v) => ((v as GroupNode).children[0] as ConditionNode).value)
    expect(values).toEqual([60, 70, 80])
  })

  it('sweeps an indicator\'s own param instead of the literal value', () => {
    const variants = buildConditionTreeVariants(sampleTree(), [
      { path: [0], field: { kind: 'params', key: 'length' } as OptimizeField, values: [7, 14, 21] },
    ])
    const lengths = variants.map((v) => ((v as GroupNode).children[0] as ConditionNode).params.length)
    const literalValues = variants.map((v) => ((v as GroupNode).children[0] as ConditionNode).value)
    expect(lengths).toEqual([7, 14, 21])
    expect(literalValues).toEqual([70, 70, 70]) // untouched
  })

  it('builds the full cross product for a literal range and a params range together', () => {
    const variants = buildConditionTreeVariants(sampleTree(), [
      { path: [0], field: { kind: 'value' }, values: [60, 70] },
      { path: [1, 0], field: { kind: 'value_params', key: 'length' } as OptimizeField, values: [100, 200] },
    ])
    expect(variants).toHaveLength(4)
    const combos = variants.map((v) => {
      const g = v as GroupNode
      const first = (g.children[0] as ConditionNode).value
      const second = ((g.children[1] as GroupNode).children[0] as ConditionNode).value_params.length
      return [first, second]
    })
    expect(combos).toEqual([
      [60, 100],
      [60, 200],
      [70, 100],
      [70, 200],
    ])
  })
})
