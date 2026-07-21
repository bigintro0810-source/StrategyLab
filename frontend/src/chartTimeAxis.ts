// EquityCurveChart/DrawdownChart共通のx軸目盛り設定。以前は固定で
// dtick:'M12'・tickformat:'%Y'(1年ごと・年のみ表示)だったため、期間指定
// (画面上部の日付指定)で数日〜数ヶ月分しかデータが無い時でも「2026」の
// ような1つの年ラベルしか出ず、いつからいつまでの結果か分からなかった
// (ユーザー要望:「期間指定してみて時間期間しか表示されない時は年月日、
// 時間まで表示できるようにして」)。データの実際の期間の長さに応じて、
// 長期間なら年単位、短期間になるほど年月日・時刻まで出すよう切り替える。
export interface ChartXAxisConfig {
  type: 'date'
  dtick?: string
  tickformat: string
  gridcolor: string
}

const GRID_COLOR = 'rgba(255,255,255,0.08)'

export function chartXAxisConfig(times: string[]): ChartXAxisConfig {
  if (times.length < 2) {
    return { type: 'date', tickformat: '%Y-%m-%d %H:%M', gridcolor: GRID_COLOR }
  }

  const ms = times.map((t) => new Date(t).getTime())
  const spanDays = (Math.max(...ms) - Math.min(...ms)) / (1000 * 60 * 60 * 24)

  // 2年超: 年単位(以前と同じ、長期間ほどPlotly任せの自動間引きだと
  // 数年おきにしか線が出ず粗く見えるため、1年ごとを明示的に強制する)。
  if (spanDays > 730) return { type: 'date', dtick: 'M12', tickformat: '%Y', gridcolor: GRID_COLOR }
  // 2ヶ月超〜2年: 月単位。
  if (spanDays > 60) return { type: 'date', dtick: 'M1', tickformat: '%Y-%m', gridcolor: GRID_COLOR }
  // 3日超〜2ヶ月: 日単位(目盛り間隔はPlotlyの自動選択に任せる)。
  if (spanDays > 3) return { type: 'date', tickformat: '%Y-%m-%d', gridcolor: GRID_COLOR }
  // 3日以内: 年月日+時刻まで表示。
  return { type: 'date', tickformat: '%Y-%m-%d %H:%M', gridcolor: GRID_COLOR }
}
