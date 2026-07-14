// main.py::pip_size_for_symbol()と同じ規則(JPYクロス=0.01、貴金属は個別、
// それ以外=0.0001)。バックテストエンジン内部は生の価格差をそのまま
// "pips"と呼ぶ既存の慣習で計算しているため(engine/backtest_engine.pyの
// コメント参照)、実際の数値を画面に出す際にここで正しいpipsへ変換する。
const METAL_PIP_SIZE: Record<string, number> = {
  XAUUSD: 0.01,
  XAGUSD: 0.001,
}

export function pipSizeForSymbol(symbol: string | undefined | null): number {
  if (!symbol) return 0.0001
  if (symbol in METAL_PIP_SIZE) return METAL_PIP_SIZE[symbol]
  return symbol.endsWith('JPY') ? 0.01 : 0.0001
}

export function toPips(rawPriceDiff: number, symbol: string | undefined | null): number {
  return rawPriceDiff / pipSizeForSymbol(symbol)
}
