import { describe, expect, it } from 'vitest'
import { buildRangeValues } from './rangeUtils'

describe('buildRangeValues', () => {
  it('builds an inclusive integer step sequence', () => {
    expect(buildRangeValues(1, 5, 1)).toEqual([1, 2, 3, 4, 5])
  })

  it('builds an inclusive fractional step sequence', () => {
    expect(buildRangeValues(0.5, 2, 0.5)).toEqual([0.5, 1, 1.5, 2])
  })

  it('avoids float drift at the upper bound (0.1 + 0.2 territory)', () => {
    expect(buildRangeValues(0.1, 0.3, 0.1)).toEqual([0.1, 0.2, 0.3])
  })

  it('falls back to [min] for a non-positive step', () => {
    expect(buildRangeValues(1, 10, 0)).toEqual([1])
    expect(buildRangeValues(1, 10, -1)).toEqual([1])
  })

  it('falls back to [min] for an inverted range', () => {
    expect(buildRangeValues(10, 1, 1)).toEqual([10])
  })

  it('handles a single-point range (min === max)', () => {
    expect(buildRangeValues(5, 5, 1)).toEqual([5])
  })
})
