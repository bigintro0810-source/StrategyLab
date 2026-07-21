// main.py::pip_size_for_symbol()と同じ規則(JPYクロス=0.01、貴金属は個別、
// それ以外=0.0001)。バックテストエンジン内部は生の価格差をそのまま
// "pips"と呼ぶ既存の慣習で計算しているため(engine/backtest_engine.pyの
// コメント参照)、実際の数値を画面に出す際にここで正しいpipsへ変換する。
const METAL_PIP_SIZE: Record<string, number> = {
  XAUUSD: 0.01,
  XAGUSD: 0.001,
}

// 合成(compositeUtils.ts)は複数シンボルのトレードをtoPips()で一旦pipsへ
// 変換してから合算するため、その合成後の値(既にpips)を保存/再表示する際に
// symbol="COMPOSITE"としてpip_size=1(無変換)を割り当てる - こうすることで
// StatsPanel等の既存のtoPips(value, row.symbol)呼び出しをそのまま使い回せる。
const COMPOSITE_PSEUDO_SYMBOL = 'COMPOSITE'

export function pipSizeForSymbol(symbol: string | undefined | null): number {
  if (!symbol) return 0.0001
  if (symbol === COMPOSITE_PSEUDO_SYMBOL) return 1
  if (symbol in METAL_PIP_SIZE) return METAL_PIP_SIZE[symbol]
  // endsWith('JPY')ではなくincludes - 同じ通貨ペアを複数の業者から取り込む
  // ためにユーザーが付ける別名(例: "USDJPY-FXCM")はJPYで終わらないが
  // JPYクロスであることに変わりはないため(main.py::pip_size_for_symbolと
  // 同じ規則に揃える - 実際に踏んだ不具合)。
  return symbol.includes('JPY') ? 0.01 : 0.0001
}

export function toPips(rawPriceDiff: number, symbol: string | undefined | null): number {
  return rawPriceDiff / pipSizeForSymbol(symbol)
}

// 1トレード単位のpips表示(取引履歴の損益、期待値など)の小数桁数。ドル
// ストレート(pip_size=0.0001、XAGUSD含む)は5桁、円クロス(pip_size=0.01、
// XAUUSD含む)は3桁 - pip_sizeが大きいペアほど1pipの実際の値幅が粗く、
// 少ない桁数でも十分な精度を表現できるため、pip_sizeそのものを基準に
// 判定する(通貨名のJPY判定を個別に書くより、pipSizeForSymbolの分類と
// 常に一致させられる)。
export function pipsDecimals(symbol: string | undefined | null): number {
  return pipSizeForSymbol(symbol) >= 0.01 ? 3 : 5
}
