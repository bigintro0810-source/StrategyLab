// Global defaults for the builder's cost/account-sizing fields. Stored in
// localStorage only (this is a single-user local app, see api_server.py's
// module docstring) - App.tsx reads these once at initial useState() so
// every new backtest starts from them; the 設定 screen writes here and
// reloads the page rather than threading live updates through props, since
// these values only ever matter at "start a new run" time.
export interface DefaultSettings {
  spreadPips: number
  slippagePips: number
  commissionPerTrade: number
  initialCapital: number
  accountCurrency: 'JPY' | 'USD'
  riskPercent: number
  conversionRate: number
  // Display-only preference - all timestamps are normalized to JST at
  // import time (see import_broker_csv.py) and stay that way internally;
  // this only affects how the chart/trade tables format datetimes on
  // screen, nothing sent to the backend.
  displayTimezone: 'JST' | 'UTC' | 'broker'
}

const STORAGE_KEY = 'strategylab-default-settings-v1'

export const FALLBACK_DEFAULTS: DefaultSettings = {
  spreadPips: 0,
  slippagePips: 0,
  commissionPerTrade: 0,
  initialCapital: 1_000_000,
  accountCurrency: 'JPY',
  riskPercent: 1.0,
  conversionRate: 150.0,
  displayTimezone: 'JST',
}

export function loadDefaultSettings(): DefaultSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return FALLBACK_DEFAULTS
    return { ...FALLBACK_DEFAULTS, ...JSON.parse(raw) }
  } catch {
    return FALLBACK_DEFAULTS
  }
}

export function saveDefaultSettings(settings: DefaultSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
}
