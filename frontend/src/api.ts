import axios from 'axios'
import type {
  BacktestJob,
  BacktestRequest,
  BacktestResults,
  BacktestStatus,
  EquityPoint,
  ExplorationCategoriesResponse,
  IndicatorInfo,
  PriceBar,
  RankingRow,
  StrategyDetail,
  TradeRow,
  TreeNode,
} from './types'

const client = axios.create({ baseURL: '/api' })

export async function fetchIndicators(): Promise<IndicatorInfo[]> {
  const res = await client.get<IndicatorInfo[]>('/indicators')
  return res.data
}

export async function fetchExplorationCategories(): Promise<ExplorationCategoriesResponse> {
  const res = await client.get<ExplorationCategoriesResponse>('/exploration-categories')
  return res.data
}

export async function fetchPriceData(symbol: string, timeframe: string, limit = 500): Promise<PriceBar[]> {
  const res = await client.get<PriceBar[]>('/price-data', { params: { symbol, timeframe, limit } })
  return res.data
}

export async function createBacktest(req: BacktestRequest): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/backtests', req)
  return res.data
}

export async function fetchBacktestStatus(jobId: string): Promise<BacktestStatus> {
  const res = await client.get<BacktestStatus>(`/backtests/${jobId}`)
  return res.data
}

export async function stopBacktest(jobId: string): Promise<{ status: string }> {
  const res = await client.post<{ status: string }>(`/backtests/${jobId}/stop`)
  return res.data
}

export async function fetchBacktestResults(jobId: string): Promise<BacktestResults> {
  const res = await client.get<BacktestResults>(`/backtests/${jobId}/results`)
  return res.data
}

export async function rerunRankingRow(jobId: string, rank: number): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>(`/backtests/${jobId}/rows/${rank}`)
  return res.data
}

export interface PineScriptResult {
  script: string
  filename: string
}

export async function fetchPineScript(strategyId: string): Promise<PineScriptResult> {
  const res = await client.get<PineScriptResult>(`/strategies/${strategyId}/pine-script`)
  return res.data
}

export interface SaveRowResult {
  id: string
  name: string
  favorite: boolean
}

export async function saveRankingRow(
  jobId: string,
  rank: number,
  name: string,
  favorite: boolean,
): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>(`/backtests/${jobId}/rows/${rank}/save`, { name, favorite })
  return res.data
}

export async function fetchSaveResult(jobId: string): Promise<SaveRowResult> {
  const res = await client.get<SaveRowResult>(`/backtests/${jobId}/save-result`)
  return res.data
}

export async function fetchStrategies(): Promise<StrategyDetail[]> {
  const res = await client.get<StrategyDetail[]>('/strategies')
  return res.data
}

export async function fetchStrategyDetail(strategyId: string): Promise<StrategyDetail> {
  const res = await client.get<StrategyDetail>(`/strategies/${strategyId}`)
  return res.data
}

export async function fetchStrategyResults(strategyId: string): Promise<BacktestResults> {
  const res = await client.get<BacktestResults>(`/strategies/${strategyId}/results`)
  return res.data
}

// データタブでストラテジーを選んだ時にチャートへ重ねる指標系列。条件ツリーが
// 実際に参照しているindicatorだけをバックエンド側で計算して返す(api_server.py
// のget_strategy_chart_indicators参照) - scaleは価格軸に重ねる('price')か
// 別軸('oscillator')かの判定済みヒント。
export interface ChartIndicatorSeries {
  indicator: string
  params: Record<string, number>
  timeframe: string | null
  scale: 'price' | 'oscillator'
  values: { time: string; value: number | null }[]
}

export async function fetchStrategyChartIndicators(
  strategyId: string,
  limit = 20000,
): Promise<{ indicators: ChartIndicatorSeries[] }> {
  const res = await client.get<{ indicators: ChartIndicatorSeries[] }>(
    `/strategies/${strategyId}/chart-indicators`,
    { params: { limit } },
  )
  return res.data
}

// strategy_idを持たない行(結果のランキング一覧・反転ストラテジーなど、
// まだ保存していない候補)向け - ツリー自体をこちらから渡して計算する
// (api_server.pyのpost_chart_indicators参照)。ストラテジー詳細のチャート
// タブは未保存行でも表示したいため、fetchStrategyChartIndicatorsとは別に
// 用意している。
export async function fetchChartIndicators(params: {
  symbol: string
  timeframe: string
  condition_tree?: TreeNode | null
  long_condition_tree?: TreeNode | null
  short_condition_tree?: TreeNode | null
  limit?: number
}): Promise<{ indicators: ChartIndicatorSeries[] }> {
  const res = await client.post<{ indicators: ChartIndicatorSeries[] }>('/chart-indicators', params)
  return res.data
}

// データタブで、ストラテジーを選ばず生の価格チャートに任意の指標を重ねる
// ための版 - 条件ツリーを経由せず、ユーザーが選んだ指標の組をそのまま渡す
// (api_server.pyのpost_data_chart_indicators参照)。
export interface IndicatorSpec {
  indicator: string
  params: Record<string, number>
  timeframe?: string
}

export async function fetchDataChartIndicators(
  symbol: string,
  timeframe: string,
  indicators: IndicatorSpec[],
  limit = 20000,
): Promise<{ indicators: ChartIndicatorSeries[] }> {
  const res = await client.post<{ indicators: ChartIndicatorSeries[] }>('/data-chart-indicators', {
    symbol,
    timeframe,
    indicators,
    limit,
  })
  return res.data
}

export function reportPdfUrl(jobId: string): string {
  return `/api/backtests/${jobId}/report.pdf`
}

// 検証タブの各ツールはライブラリの保存済みストラテジー(strategy_id)を対象に
// 実行する。結果はそのストラテジー自身のsnapshot_dirに書き出されるため、
// by-strategyのGETはjob_idを介さず直接ディスクから読める - タブを切り替え
// たりソフトを再起動したりしても結果が消えない(api_server.py参照)。
export async function runWalkForward(strategyId: string): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/walk-forward', { strategy_id: strategyId })
  return res.data
}

export async function fetchWalkForwardResults(strategyId: string): Promise<{ rows: Record<string, unknown>[] }> {
  const res = await client.get<{ rows: Record<string, unknown>[] }>(`/tools/walk-forward/by-strategy/${strategyId}`)
  return res.data
}

export async function runMonteCarlo(strategyId: string, simulations: number): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/monte-carlo', { strategy_id: strategyId, simulations })
  return res.data
}

export async function fetchMonteCarloResults(strategyId: string): Promise<{ monte_carlo_summary: Record<string, unknown>[] }> {
  const res = await client.get<{ monte_carlo_summary: Record<string, unknown>[] }>(
    `/tools/monte-carlo/by-strategy/${strategyId}`,
  )
  return res.data
}

export async function runSensitivity(strategyId: string, mode: string): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/sensitivity', { strategy_id: strategyId, mode })
  return res.data
}

export async function fetchSensitivityResults(strategyId: string): Promise<{ summary: Record<string, unknown>[] }> {
  const res = await client.get<{ summary: Record<string, unknown>[] }>(`/tools/sensitivity/by-strategy/${strategyId}`)
  return res.data
}

export async function runConfidence(strategyId: string): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/confidence', { strategy_id: strategyId })
  return res.data
}

export async function fetchConfidenceResults(strategyId: string): Promise<Record<string, unknown>> {
  const res = await client.get<Record<string, unknown>>(`/tools/confidence/by-strategy/${strategyId}`)
  return res.data
}

export async function runOos(strategyId: string, splitRatio: number): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/oos', { strategy_id: strategyId, split_ratio: splitRatio })
  return res.data
}

export async function fetchOosResults(strategyId: string): Promise<{ rows: Record<string, unknown>[] }> {
  const res = await client.get<{ rows: Record<string, unknown>[] }>(`/tools/oos/by-strategy/${strategyId}`)
  return res.data
}

// 反転(Reverse Strategy): 結果のランキング一覧由来なら{type:'rank', symbol,
// timeframe, rank, name}、ライブラリ由来なら{type:'strategy', strategy_id}。
// nameは新しく保存する名前("{name}-反転")に使う - rank由来の行は
// バックエンド側に永続的な名前を持たないため、フロント側の表示名を渡す。
// 反転結果はライブラリへ自動保存しない(api_server.py参照) - 一覧は
// ジョブ専用のoutput/reversed/{job_id}/を読むだけの一時データで、行ごとに
// 🔖(saveReverseRow)を押した分だけライブラリに永続化される。
export type ReverseTarget =
  | { type: 'rank'; symbol: string; timeframe: string; rank: number; name: string }
  | { type: 'strategy'; strategy_id: string }

export async function runReverse(targets: ReverseTarget[]): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/tools/reverse', { targets })
  return res.data
}

export async function fetchReverseResults(jobId: string): Promise<{ ranking_total: RankingRow[] }> {
  const res = await client.get<{ ranking_total: RankingRow[] }>(`/tools/reverse/${jobId}/results`)
  return res.data
}

// 反転ストラテジータブが実際に表示するのはこちら - このセッション中に
// 実行した反転バッチ全て(output/_state/reverse_batches.json)をバック
// エンド側で連結し、rankを1..Nに振り直して返す。新しい反転を実行しても
// 前回分は消えず、末尾に追加される形になる。各行の_source_job_id/
// _source_rankで元のバッチ内の場所を辿れる(行ごとの詳細取得/保存用)。
// originは'results'(結果のランキング一覧由来)か'library'(保存済み
// ストラテジー/お気に入り由来)か - 結果側とライブラリ側の反転ストラテジー
// タブは別々のデータになる(api_server.pyのget_reverse_current_results参照)。
export async function fetchReverseCurrentResults(
  origin: 'results' | 'library',
): Promise<{ ranking_total: RankingRow[] }> {
  const res = await client.get<{ ranking_total: RankingRow[] }>('/tools/reverse/current/results', {
    params: { origin },
  })
  return res.data
}

export async function fetchReverseRowResults(jobId: string, rank: number): Promise<BacktestResults> {
  const res = await client.get<BacktestResults>(`/tools/reverse/${jobId}/rows/${rank}/results`)
  return res.data
}

export async function saveReverseRow(
  jobId: string,
  rank: number,
  name: string,
  favorite: boolean,
): Promise<SaveRowResult> {
  const res = await client.post<SaveRowResult>(`/tools/reverse/${jobId}/rows/${rank}/save`, { name, favorite })
  return res.data
}

export async function saveComposite(
  name: string,
  favorite: boolean,
  tradeLog: (TradeRow & { source: string })[],
  equityCurve: EquityPoint[],
  metrics: Record<string, number>,
  sourceNames: string[],
): Promise<SaveRowResult> {
  const res = await client.post<SaveRowResult>('/composite/save', {
    name,
    favorite,
    trade_log: tradeLog,
    equity_curve: equityCurve,
    metrics,
    source_names: sourceNames,
  })
  return res.data
}

export async function fetchCompositeMonteCarlo(
  tradeLog: (TradeRow & { source: string })[],
): Promise<Record<string, unknown>[]> {
  const res = await client.post<{ summary: Record<string, unknown>[] }>('/composite/monte-carlo', {
    trade_log: tradeLog,
  })
  return res.data.summary
}

export async function fetchStrategiesFiltered(favoriteOnly: boolean): Promise<StrategyDetail[]> {
  const res = await client.get<StrategyDetail[]>('/strategies', { params: { favorite_only: favoriteOnly } })
  return res.data
}

export async function toggleStrategyFavorite(strategyId: string): Promise<StrategyDetail> {
  const res = await client.post<StrategyDetail>(`/strategies/${strategyId}/favorite`)
  return res.data
}

export async function deleteStrategy(strategyId: string): Promise<void> {
  await client.delete(`/strategies/${strategyId}`)
}

export async function addStrategyTags(strategyId: string, tags: string[]): Promise<StrategyDetail> {
  const res = await client.post<StrategyDetail>(`/strategies/${strategyId}/tags`, { tags })
  return res.data
}

export async function removeStrategyTag(strategyId: string, tag: string): Promise<StrategyDetail> {
  const res = await client.delete<StrategyDetail>(`/strategies/${strategyId}/tags/${encodeURIComponent(tag)}`)
  return res.data
}

export async function setStrategyMemo(strategyId: string, text: string): Promise<StrategyDetail> {
  const res = await client.post<StrategyDetail>(`/strategies/${strategyId}/memo`, { text })
  return res.data
}

export async function renameStrategy(strategyId: string, name: string): Promise<StrategyDetail> {
  const res = await client.post<StrategyDetail>(`/strategies/${strategyId}/rename`, { name })
  return res.data
}

// ライブラリ画面のユーザー定義タブ(保存済みストラテジー/お気に入りとは別に
// 任意で分類できるフォルダ)。strategy_idsは参照のみ - ストラテジー本体は
// strategy_registry.py側の1箇所にしかない。
export interface Collection {
  id: string
  name: string
  strategy_ids: string[]
}

export async function fetchCollections(): Promise<Collection[]> {
  const res = await client.get<Collection[]>('/collections')
  return res.data
}

export async function createCollection(name: string): Promise<Collection> {
  const res = await client.post<Collection>('/collections', { name })
  return res.data
}

export async function renameCollection(collectionId: string, name: string): Promise<Collection> {
  const res = await client.post<Collection>(`/collections/${collectionId}/rename`, { name })
  return res.data
}

export async function deleteCollection(collectionId: string): Promise<void> {
  await client.delete(`/collections/${collectionId}`)
}

export async function addStrategyToCollection(collectionId: string, strategyId: string): Promise<Collection> {
  const res = await client.post<Collection>(`/collections/${collectionId}/strategies`, { strategy_id: strategyId })
  return res.data
}

export async function removeStrategyFromCollection(collectionId: string, strategyId: string): Promise<Collection> {
  const res = await client.delete<Collection>(`/collections/${collectionId}/strategies/${strategyId}`)
  return res.data
}

export interface CompareEntry {
  id: string
  name: string
  symbol: string
  timeframe: string
  favorite: boolean
  tags: string[]
  metrics: Record<string, number>
  condition_tree?: TreeNode
  equity_curve: EquityPoint[]
}

export async function compareStrategies(ids: string[]): Promise<{ entries: CompareEntry[] }> {
  const res = await client.get<{ entries: CompareEntry[] }>('/strategies/compare', { params: { ids: ids.join(',') } })
  return res.data
}

export interface DataValidationReport {
  path: string
  rows: number
  start: string
  end: string
  duplicate_timestamps: number
  ohlc_violations: number
  gap_count: number
  gaps: { before: string; after: string; minutes: number }[]
}

// 現在インポート済みの通貨/銘柄シンボル一覧(api_server.pyのget_data_symbols
// 参照) - App.tsxの通貨ピッカーはこれで動的に埋める。以前は9通貨固定の
// ハードコードリストだったため、新しい通貨ペアをCSVインポートしても
// ピッカーの選択肢に出てこない問題があった。
export async function fetchDataSymbols(): Promise<string[]> {
  const res = await client.get<string[]>('/data/symbols')
  return res.data
}

// 通貨/銘柄ごとに実際にインポート済みの時間足一覧(api_server.pyの
// get_data_symbol_timeframes参照) - 探索/データ/Data Validator画面の
// 時間足ピッカーは、選ばれている通貨にこのデータが無い時間足を選べない
// ようにする(ユーザー要望:「読み込んでいないデータは選択不可能にして
// ほしい」)。
export async function fetchDataSymbolTimeframes(): Promise<Record<string, string[]>> {
  const res = await client.get<Record<string, string[]>>('/data/symbol-timeframes')
  return res.data
}

export async function validateData(symbol: string, timeframe: string): Promise<DataValidationReport> {
  const res = await client.get<DataValidationReport>('/data/validate', { params: { symbol, timeframe } })
  return res.data
}

export async function importCsv(
  sourceRoot: string,
  symbols: string[],
  timeframes: string[],
  // エラー後の「続きから再開」ボタン用 - trueだと出力先ファイルが既に
  // あるものは再変換せずスキップする(api_server.py::CsvImportRequest.
  // skip_existing参照)。
  skipExisting = false,
  // 取り込み元CSVのタイムゾーン('EET'/'JST'/'UTC') - JST以外を選ぶと
  // 自動的にJSTへ変換される(api_server.py::CsvImportRequest.source_timezone
  // /import_broker_csv.py::SOURCE_TZ_OPTIONS参照)。
  sourceTimezone = 'EET',
  // trueだと出力先を丸ごと置き換えず、既存データは保持したまま無い日時の
  // 行だけを追加する(ユーザー要望:「23年分は残したい」- api_server.py::
  // CsvImportRequest.merge/import_broker_csv.py::merge_into_existing参照)。
  merge = false,
): Promise<BacktestJob> {
  const res = await client.post<BacktestJob>('/data/import', {
    source_root: sourceRoot,
    symbols,
    timeframes,
    skip_existing: skipExisting,
    source_timezone: sourceTimezone,
    merge,
  })
  return res.data
}

// CSVインポート画面の「参照...」ボタン用 - サーバー(フロントエンドと同じ
// PC上で動くローカル専用アプリ)側でネイティブのフォルダ選択ダイアログを
// 開き、選ばれた絶対パスを返す(api_server.pyのbrowse_folder参照)。
export async function browseFolder(): Promise<string | null> {
  const res = await client.post<{ path: string | null }>('/browse-folder')
  return res.data.path
}
