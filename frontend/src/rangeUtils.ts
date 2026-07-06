/** Builds the inclusive [min, max] step sequence used by the optimizer's
 * parameter-range inputs, rounded to 3 decimals to avoid float drift (e.g.
 * 0.1 + 0.2). Falls back to [min] for a non-positive step or an inverted
 * range, since a range editor commit can transiently produce those. */
export function buildRangeValues(min: number, max: number, step: number): number[] {
  if (step <= 0 || max < min) return [min]
  const values: number[] = []
  for (let v = min; v <= max + 1e-9; v += step) {
    values.push(Math.round(v * 1000) / 1000)
  }
  return values.length > 0 ? values : [min]
}
