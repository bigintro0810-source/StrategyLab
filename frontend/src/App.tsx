import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createBacktest,
  deleteStrategy,
  fetchBacktestResults,
  fetchBacktestStatus,
  fetchIndicators,
  fetchSaveResult,
  fetchStrategies,
  fetchStrategyDetail,
  fetchStrategyResults,
  renameStrategy,
  rerunRankingRow,
  saveRankingRow,
  stopBacktest,
  toggleStrategyFavorite,
  type CompareEntry,
} from './api'
import type { CompositeInput } from './compositeUtils'
import type {
  BacktestResults,
  ConditionNode,
  ConditionOptimizeRange,
  Direction,
  GroupNode,
  OptimizableParam,
  OptimizeField,
  ParamRangeConfig,
  PartialTpLevel,
  RankingRow,
} from './types'
import { buildConditionTreeVariants, collectOptimizableConditions, optionIsValid } from './conditionTreeUtils'
import { buildRangeValues } from './rangeUtils'
import ConditionTreeEditor from './components/ConditionTreeEditor'
import AutoExplorationScreen from './components/AutoExplorationScreen'
import AutoExplorationHero from './components/AutoExplorationHero'
import DataScreen from './components/DataScreen'
import ReportScreen from './components/ReportScreen'
import ValidationScreen from './components/ValidationScreen'
import ResultsScreen from './components/ResultsScreen'
import type { StrategyTabData } from './components/StrategyDetailTabs'
import LibraryScreen from './components/LibraryScreen'
import LibraryDetailTabs, { type LibraryTabData } from './components/LibraryDetailTabs'
import CompareScreen from './components/CompareScreen'
import CompareView from './components/CompareView'
import CompositeDetail from './components/CompositeDetail'
import CsvImportScreen from './components/CsvImportScreen'
import DataValidatorScreen from './components/DataValidatorScreen'
import SettingsScreen from './components/SettingsScreen'
import { loadDefaultSettings } from './defaultSettings'

const defaultSettings = loadDefaultSettings()

// NOTE (2026-07-06): ema_length/rsi_min/ema_distance_pips/min_body_pips/
// max_body_pips/max_wick_pips/breakout_bars were REMOVED from this list -
// they only feed the legacy fixed-strategy signal builder
// (build_candidate_signal in engine/backtest_engine.py), which only runs
// when condition_tree is absent. This dashboard's builder ALWAYS sends a
// condition_tree (see runMutation below), so sweeping any of those old
// params silently produced N identical ranking rows - a real, confirmed
// no-op bug, not just a missing feature. Every parameter listed here
// actually affects a condition-tree strategy's result regardless of which
// other opt-in features are toggled (rr/lookahead_bars always apply; the
// rest only take effect once their own use_* checkbox above is also on -
// same as directly typing a value into that field would).
export const OPTIMIZABLE_PARAMS: OptimizableParam[] = [
  { id: 'rr', label: 'リスクリワード比' },
  { id: 'lookahead_bars', label: '先読みバー数' },
  { id: 'weekend_exit_hour', label: '週末決済時刻' },
  { id: 'daily_exit_hour', label: '日次決済時刻' },
  { id: 'spread_pips', label: 'スプレッド(pips)' },
  { id: 'slippage_pips', label: 'スリッページ(pips)' },
  { id: 'commission_per_trade', label: '手数料(1取引あたり)' },
  { id: 'atr_trailing_length', label: 'ATRトレーリング期間 ※要チェックボックスON' },
  { id: 'atr_trailing_multiplier', label: 'ATRトレーリング倍率 ※要チェックボックスON' },
  { id: 'breakeven_trigger_rr', label: '建値移動トリガーRR ※要チェックボックスON' },
  { id: 'partial_tp_rr', label: '部分利確到達RR ※要チェックボックスON' },
  { id: 'partial_tp_fraction', label: '部分利確割合 ※要チェックボックスON' },
  { id: 'max_dd_stop_pips', label: '最大DDストップ(pips) ※要チェックボックスON' },
  { id: 'consecutive_loss_stop_count', label: '連敗ストップ数 ※要チェックボックスON' },
  { id: 'entry_offset_pips', label: '指値/逆指値オフセット ※要指値/逆指値選択' },
  { id: 'risk_percent', label: 'リスク%(資金管理) ※要チェックボックスON' },
]

const PARAM_DEFAULTS: Record<string, { min: number; max: number; step: number }> = {
  rr: { min: 1, max: 2, step: 0.2 },
  lookahead_bars: { min: 10, max: 20, step: 5 },
  weekend_exit_hour: { min: 0, max: 6, step: 1 },
  daily_exit_hour: { min: 0, max: 23, step: 1 },
  spread_pips: { min: 0, max: 2, step: 0.5 },
  slippage_pips: { min: 0, max: 2, step: 0.5 },
  commission_per_trade: { min: 0, max: 1, step: 0.1 },
  atr_trailing_length: { min: 7, max: 21, step: 7 },
  atr_trailing_multiplier: { min: 1, max: 3, step: 0.5 },
  breakeven_trigger_rr: { min: 0.3, max: 0.8, step: 0.1 },
  partial_tp_rr: { min: 0.5, max: 1.5, step: 0.25 },
  partial_tp_fraction: { min: 0.2, max: 0.7, step: 0.1 },
  max_dd_stop_pips: { min: 50, max: 150, step: 25 },
  consecutive_loss_stop_count: { min: 2, max: 5, step: 1 },
  entry_offset_pips: { min: 5, max: 20, step: 5 },
  risk_percent: { min: 0.5, max: 2, step: 0.5 },
}

function defaultParamRange(param: string): ParamRangeConfig {
  const d = PARAM_DEFAULTS[param] ?? { min: 1, max: 10, step: 1 }
  return { enabled: false, param, ...d }
}

export type MainTab = 'explore' | 'results' | 'validation' | 'library' | 'data' | 'settings'

const MAIN_TABS: { id: MainTab; label: string; subTabs: { id: string; label: string }[] }[] = [
  {
    id: 'explore',
    label: '探索',
    subTabs: [
      { id: 'manual', label: '手動探索' },
      { id: 'auto', label: '自動探索' },
    ],
  },
  {
    id: 'results',
    label: '結果',
    subTabs: [
      { id: 'ranking', label: 'ランキング' },
      { id: 'detail', label: 'ストラテジー詳細' },
      { id: 'compare', label: '比較' },
      { id: 'composite', label: '合成' },
    ],
  },
  {
    id: 'validation',
    label: '検証',
    subTabs: [
      { id: 'oos', label: 'Out-of-Sample' },
      { id: 'walkforward', label: 'Walk Forward' },
      { id: 'montecarlo', label: 'Monte Carlo' },
      { id: 'sensitivity', label: 'パラメータ安定性' },
    ],
  },
  {
    id: 'library',
    label: 'ライブラリ',
    subTabs: [
      { id: 'saved', label: '保存済みストラテジー' },
      { id: 'favorites', label: 'お気に入り' },
      { id: 'detail', label: 'ストラテジー詳細' },
      { id: 'compare', label: '比較' },
      { id: 'composite', label: '合成' },
      { id: 'export', label: 'エクスポート' },
    ],
  },
  {
    id: 'data',
    label: 'データ',
    subTabs: [
      { id: 'dataset', label: 'データセット' },
      { id: 'import', label: 'CSVインポート' },
      { id: 'validator', label: 'Data Validator' },
    ],
  },
  {
    id: 'settings',
    label: '設定',
    subTabs: [
      { id: 'cost', label: 'コスト' },
      { id: 'execution', label: '約定条件' },
      { id: 'timezone', label: 'タイムゾーン' },
      { id: 'general', label: '一般設定' },
    ],
  },
]

const SYMBOLS = ['USDJPY', 'EURJPY', 'GBPJPY', 'AUDJPY', 'AUDUSD', 'EURUSD', 'GBPUSD', 'XAUUSD', 'XAGUSD']
const TIMEFRAMES = ['1m', '5m', '10m', '15m', '30m', '1h', '4h', '1d', '1w', '1mo']

// api_server.pyのJOBSは常駐プロセスのメモリ上にしかない(run.batが開く
// コンソールを閉じるまではプロセス自体は生き続ける - README参照)ため、
// ブラウザのタブ/ウィンドウだけを閉じて開き直した場合はjobIdさえ覚えて
// おけば結果はそのまま復元できる。バックエンドプロセスごと再起動された
// 場合はstatusQueryが404を返すので、その時だけ諦めてnullに戻す
// (下のuseEffect参照)。
const JOB_ID_STORAGE_KEY = 'strategylab:jobId'

// ランキング行の既定表示名: 探索を実行した日付 + rank(6桁連番)。
// 例: runDateが2026-07-14、rank=3 なら "2026/07/14-000003"。
function defaultStrategyName(rank: number, runDate: Date | null): string {
  const d = runDate ?? new Date()
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}/${mm}/${dd}-${String(rank).padStart(6, '0')}`
}

function defaultTree(): GroupNode {
  return {
    op: 'AND',
    children: [{ indicator: 'close', operator: '>', value: 0, params: {}, value_params: {} }],
  }
}

function ParamRangeRow({
  label,
  value,
  onChange,
  onRemove,
}: {
  label: string
  value: ParamRangeConfig
  onChange: (next: ParamRangeConfig) => void
  onRemove?: () => void
}) {
  return (
    <div className="space-y-1 rounded-lg border border-white/10 bg-white/[0.02] p-2">
      <label className="flex items-center gap-1.5 text-xs text-gray-300">
        <input
          type="checkbox"
          checked={value.enabled}
          onChange={(e) => onChange({ ...value, enabled: e.target.checked })}
        />
        {label}を最適化
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="ml-auto text-gray-500 hover:text-red-400"
            title="このパラメータ範囲を削除"
          >
            ✕
          </button>
        )}
      </label>
      <div className="grid grid-cols-4 gap-1">
        <select
          className="glass-input col-span-4 w-full min-w-0 rounded-lg px-1.5 py-1 text-xs"
          value={value.param}
          onChange={(e) => {
            const d = PARAM_DEFAULTS[e.target.value] ?? { min: 1, max: 10, step: 1 }
            onChange({ ...value, param: e.target.value, ...d })
          }}
        >
          {OPTIMIZABLE_PARAMS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        <input
          type="number"
          title="最小値"
          className="glass-input w-full min-w-0 rounded-lg px-1 py-1 text-xs"
          value={value.min}
          onChange={(e) => onChange({ ...value, min: Number(e.target.value) })}
        />
        <input
          type="number"
          title="最大値"
          className="glass-input w-full min-w-0 rounded-lg px-1 py-1 text-xs"
          value={value.max}
          onChange={(e) => onChange({ ...value, max: Number(e.target.value) })}
        />
        <input
          type="number"
          title="刻み幅"
          className="glass-input w-full min-w-0 rounded-lg px-1 py-1 text-xs"
          value={value.step}
          onChange={(e) => onChange({ ...value, step: Number(e.target.value) })}
        />
      </div>
    </div>
  )
}

export default function App() {
  // 'manual' = today's condition builder (a single tree the user edits).
  // 'structure'/'structure_genetic' = the auto-exploration engine
  // (engine/structure_generator.py): the backend generates and ranks many
  // condition trees itself, so the manual tree editor/direction picker
  // below are hidden and replaced with the engine's own controls. See
  // api_server.py::BacktestRequest's n_candidates/max_depth/etc comment for
  // why rr/exit-rule/position-sizing settings don't apply in these modes.
  const [explorationMode, setExplorationMode] = useState<'manual' | 'structure' | 'structure_genetic'>('manual')
  // Two-level nav: mainTab picks one of MAIN_TABS, subTab picks one of that
  // tab's own subTabs (its id, not index - independent state per mainTab
  // isn't needed since only one subTab bar is ever visible at a time).
  const [mainTab, setMainTab] = useState<MainTab>('explore')
  const [subTab, setSubTab] = useState('manual')

  // ランキング一覧は画面に収まる固定高さの枠内で自分だけスクロールする
  // (RankingTable.tsx参照)。ストラテジー詳細タブと行き来するとその枠の
  // divごとアンマウント/再マウントされるので、DOM要素自身のscrollTopでは
  // 位置を覚えていられない - 常に生き続けるApp本体側のrefにスクロール
  // 位置を持たせ、RankingTable側のref callbackで復元/継続記録する。
  const rankingScrollTopRef = useRef(0)

  const handleMainTabClick = (tab: MainTab) => {
    setMainTab(tab)
    setSubTab(MAIN_TABS.find((t) => t.id === tab)?.subTabs[0].id ?? '')
  }

  const handleSubTabClick = (id: string) => {
    setSubTab(id)
  }

  const handleExploreSubTabClick = (id: string) => {
    setSubTab(id)
    if (id === 'manual') setExplorationMode('manual')
    else setExplorationMode((m) => (m === 'manual' ? 'structure_genetic' : m))
  }

  // Strategies checked in ライブラリ for cross-comparison - lifted here (not
  // local to LibraryScreen) since ライブラリ>比較 is a separate subTab
  // (CompareScreen) that needs to read the same selection.
  const [compareIds, setCompareIds] = useState<string[]>([])
  const toggleCompareId = (id: string) => {
    setCompareIds((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]))
  }
  // Detail settings (n-candidates/max-depth/.../mutation-rate) start collapsed -
  // a first-time user shouldn't have to parse 8 unfamiliar fields just to
  // click "run"; only someone who opens this should see them.
  const [explorationAdvOpen, setExplorationAdvOpen] = useState(false)
  // 手動探索 screen's own "詳細設定" - collapsed by default so the screen
  // reads as just エントリー条件/決済条件/実行, matching the 2026-07-12
  // request to keep this screen focused on those three things; risk/money
  // management, cost overrides, and param optimization are still here,
  // just tucked away for anyone who opens it.
  const [manualAdvOpen, setManualAdvOpen] = useState(false)
  // Which indicators are eligible for generation - every category checked
  // by default reproduces today's unfiltered "every indicator eligible"
  // behavior (see engine/indicator_pool.py's CATEGORIES, the source of
  // truth this mirrors). 探索レベル(light/standard/advanced)プリセットは
  // 2026-07-13廃止 - 常にカスタム(カテゴリ+指標+数値の個別チェック)相当。
  const [categories, setCategories] = useState<string[]>([
    'indicator',
    'price_action',
    'time_filter',
    'ict',
    'chart_pattern',
  ])
  // カテゴリ内の個別指標名の絞り込み(空配列 = チェック済みカテゴリの指標が
  // 全部有効、今日と同じ挙動)。
  const [customIndicatorNames, setCustomIndicatorNames] = useState<string[]>([])
  // 指標ごとの数値(param_ranges由来)/閾値(literal_range由来)の絞り込み。
  // 空/未設定の指標はrepresentative value全部が候補になる(同じ空配列
  // センチネル方式、engine/indicator_pool.py::value_presets/literal_presets)。
  const [selectedParamValues, setSelectedParamValues] = useState<Record<string, Record<string, number[]>>>({})
  const [selectedLiteralValues, setSelectedLiteralValues] = useState<Record<string, number[]>>({})
  // 決済条件(RR)の候補リスト。空なら--mode devの1.2固定と同じ挙動
  // (api_server.py::create_backtestがexploration_config自体を書かない)。
  const [rrChoices, setRrChoices] = useState<number[]>([])
  // 探索期間(開始日〜終了日) - 手動探索・自動探索どちらのバックテストにも
  // 共通で効く(main.py::mainがload_price_data直後にフィルタする、
  // api_server.py::create_backtestがoptimizerを問わずexploration-config
  // 経由で渡す)。トップバーの共通コントロールとして表示。
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  // 生成される全候補にANDで必ず追加される条件(条件数min/max leavesの
  // カウント対象外)。
  const [mandatoryConditions, setMandatoryConditions] = useState<ConditionNode[]>([])
  const [nCandidates, setNCandidates] = useState(500)
  const [maxDepth, setMaxDepth] = useState(2)
  const [minLeaves, setMinLeaves] = useState(1)
  const [maxLeaves, setMaxLeaves] = useState(4)
  const [minTrades, setMinTrades] = useState(30)
  const [mtfProbability, setMtfProbability] = useState(0)
  const [mtfTimeframes, setMtfTimeframes] = useState('')
  const [population, setPopulation] = useState(20)
  const [mutationRate, setMutationRate] = useState(0.2)
  const [generations, setGenerations] = useState(30)

  const [direction, setDirection] = useState<Direction>('short')
  const [tree, setTree] = useState<GroupNode>(defaultTree())

  // Simultaneous Long+Short mode: evaluates two independent entry trees
  // against one shared position (no hedging). Off by default - preserves
  // the existing single-tree+direction flow exactly.
  const [dualDirectionMode, setDualDirectionMode] = useState(false)
  const [longTree, setLongTree] = useState<GroupNode>(defaultTree())
  const [shortTree, setShortTree] = useState<GroupNode>(defaultTree())

  // Shared Short/Long selector (top toolbar, used by both 手動探索 and
  // 自動探索): two independently-toggleable buttons rather than a single
  // exclusive choice - both active === dualDirectionMode, exactly one
  // active === direction/dualDirectionMode=false (the existing manual-
  // builder state, unchanged). At least one must stay active.
  const shortActive = dualDirectionMode || direction === 'short'
  const longActive = dualDirectionMode || direction === 'long'
  const toggleShortActive = () => {
    if (shortActive && !longActive) return
    if (shortActive) {
      setDualDirectionMode(false)
      setDirection('long')
    } else if (longActive) {
      setDualDirectionMode(true)
    } else {
      setDualDirectionMode(false)
      setDirection('short')
    }
  }
  const toggleLongActive = () => {
    if (longActive && !shortActive) return
    if (longActive) {
      setDualDirectionMode(false)
      setDirection('short')
    } else if (shortActive) {
      setDualDirectionMode(true)
    } else {
      setDualDirectionMode(false)
      setDirection('long')
    }
  }

  const [symbol, setSymbol] = useState('USDJPY')
  const [timeframe, setTimeframe] = useState('15m')
  const [mode, setMode] = useState('dev')
  const [jobId, setJobId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(JOB_ID_STORAGE_KEY)
    } catch {
      return null
    }
  })
  const [showStopConfirm, setShowStopConfirm] = useState(false)
  const [showRunConfirm, setShowRunConfirm] = useState(false)

  // ストラテジー詳細タブの状態。openTabRanks=開いているタブ(最大20、rank自体を
  // IDとして使う - RankingRow.rankは列ソートで表示順が変わっても値は変わらない
  // 安定したサーバー割り当てID)。visibleRanks=画面に並べて表示中のタブ(最大4、
  // openTabRanksの部分集合)。focusedRank=直近で開いた/選んだタブのrankで、
  // 検証/エクスポート画面(ValidationScreen/ReportScreen)が今まで通り単一の
  // selectedRank/bestRowとして参照できるようにするための後方互換用。
  // tabJobIdsは各タブ用の再計算ジョブ(rerunRankingRow/rerun_ranking_row.py、
  // 1行だけ再計算する既存の仕組みをタブの数だけ並列に使う)。
  // 新しいバックテストが始まったら全てリセットする(旧ランキングは消えるため)。
  const MAX_DETAIL_TABS = 20
  const MAX_VISIBLE_TABS = 4
  const [openTabRanks, setOpenTabRanks] = useState<number[]>([])
  const [visibleRanks, setVisibleRanks] = useState<number[]>([])
  const [focusedRank, setFocusedRank] = useState<number | null>(null)
  const [tabJobIds, setTabJobIds] = useState<Record<number, string>>({})

  // 結果>比較・結果>合成でチェックした行(それぞれ独立、詳細タブのチェックとは
  // 別)。どちらも比較/合成に元データ(equity_curve/trade_log)が要るため、
  // 詳細タブと同じrerunの仕組み(tabJobIds)を共有して使う - 3つのどれかで
  // 既にrerun済みのrankなら再送しない(下のtoggleCompareRank/
  // toggleCompositeRank参照)。
  const [compareRanks, setCompareRanks] = useState<number[]>([])
  const [compositeRanks, setCompositeRanks] = useState<number[]>([])

  // ライブラリ画面(保存済みストラテジー/お気に入り)版のストラテジー詳細タブ。上の
  // openTabRanks/visibleRanksと同じ仕組みだが、こちらは再計算ジョブが要らない
  // (保存時のスナップショットをそのまま読むだけ - fetchStrategyResults)ため
  // tabJobIds相当は無い。idはジョブ内limitedなrankと違って永続的な文字列
  // なので、新しいバックテストが始まってもリセットしない。
  const [libraryOpenIds, setLibraryOpenIds] = useState<string[]>([])
  const [libraryVisibleIds, setLibraryVisibleIds] = useState<string[]>([])
  // ライブラリ>合成でチェックしたid(比較は既存のcompareIds/CompareScreenを
  // そのまま使うので合成専用の状態だけ追加する)。
  const [libraryCompositeIds, setLibraryCompositeIds] = useState<string[]>([])

  // 各行の表示名。リネームした行だけcustomNamesに入り、それ以外はrunDate(この
  // ジョブの実行日時)+rank(6桁連番)から機械的に組み立てる既定名を使う
  // (例: 2026/07/14-000003)。ライブラリへの保存名にもこれをそのまま使う。
  const [customNames, setCustomNames] = useState<Record<number, string>>({})
  const [runDate, setRunDate] = useState<Date | null>(null)
  const renameRow = (rank: number, name: string) => setCustomNames((prev) => ({ ...prev, [rank]: name }))

  // 🔖/⭐によるライブラリ保存状態。rerunRankingRowと同じ「rank毎にジョブを
  // 1つ持つ」パターンで、rerun_ranking_row.py --save-asの完了を待ってから
  // SAVE_RESULT_JSON:マーカー(fetchSaveResult)で保存済みID/お気に入りを読む。
  const [saveJobIds, setSaveJobIds] = useState<Record<number, string>>({})
  // 保存ジョブは実体がバックテストの再計算(数秒かかる)なので、クリックから
  // 完了までの間だけtrueにするフラグ。これが無いと、保存中に🔖/⭐を連打した
  // 場合「まだ保存済みと判定されていない」せいで毎回新規保存が走ってしまい、
  // ライブラリに同名の重複エントリが量産される実害があったため追加した。
  const [pendingSaveRanks, setPendingSaveRanks] = useState<Set<number>>(new Set())

  // Any number of parameter ranges (not capped at 2) - each independently
  // enabled/disabled, all feeding one N-dimensional grid search on the
  // backend (main.py's itertools.product-based grid was already fully
  // generic; this UI cap was the only limitation).
  const [paramRanges, setParamRanges] = useState<ParamRangeConfig[]>(() => [
    defaultParamRange('rr'),
    defaultParamRange('lookahead_bars'),
  ])
  const addParamRange = () => setParamRanges((prev) => [...prev, defaultParamRange('rr')])
  const removeParamRange = (index: number) => setParamRanges((prev) => prev.filter((_, i) => i !== index))
  const updateParamRange = (index: number, next: ParamRangeConfig) =>
    setParamRanges((prev) => prev.map((r, i) => (i === index ? next : r)))

  // Node-level condition-tree optimization: sweep one or more specific
  // conditions' own comparison values (e.g. "this RSI threshold, 60-80")
  // rather than a whole BacktestConfig field. Any number of rows, each
  // independently enabled - all enabled rows cross-multiply into the full
  // grid (same composition rule paramRanges already uses). Not supported
  // together with Long+Short同時 dual-direction mode (this only targets the
  // single `tree`, not longTree/shortTree) - UI hides it while
  // dualDirectionMode is on, same precedent as entryMethod.
  const [conditionOptimizeRanges, setConditionOptimizeRanges] = useState<ConditionOptimizeRange[]>(() => [
    { enabled: false, path: null, field: null, min: 60, max: 80, step: 5 },
  ])
  const addConditionOptimizeRange = () =>
    setConditionOptimizeRanges((prev) => [
      ...prev,
      { enabled: false, path: null, field: null, min: 60, max: 80, step: 5 },
    ])
  const removeConditionOptimizeRange = (index: number) =>
    setConditionOptimizeRanges((prev) => prev.filter((_, i) => i !== index))
  const updateConditionOptimizeRange = (index: number, next: ConditionOptimizeRange) =>
    setConditionOptimizeRanges((prev) => prev.map((r, i) => (i === index ? next : r)))

  const [rr, setRr] = useState(1.2)
  const [useWeekendExit, setUseWeekendExit] = useState(true)
  const [weekendExitHour, setWeekendExitHour] = useState(4)
  const [useDailyExit, setUseDailyExit] = useState(false)
  const [dailyExitHour, setDailyExitHour] = useState(4)
  const [saveAsName, setSaveAsName] = useState('')

  // Execution cost simulation - defaults come from the 設定 screen's
  // localStorage-backed values (see defaultSettings.ts), which themselves
  // fall back to frictionless-fill zeros matching the engine's own default.
  const [spreadPips, setSpreadPips] = useState(defaultSettings.spreadPips)
  const [slippagePips, setSlippagePips] = useState(defaultSettings.slippagePips)
  const [commissionPerTrade, setCommissionPerTrade] = useState(defaultSettings.commissionPerTrade)

  // ATR trailing stop - off by default (fixed RR-based SL/TP, today's
  // existing behavior unchanged unless opted in).
  const [useAtrTrailingStop, setUseAtrTrailingStop] = useState(false)
  const [atrTrailingLength, setAtrTrailingLength] = useState(14)
  const [atrTrailingMultiplier, setAtrTrailingMultiplier] = useState(2.0)

  // Circuit breakers - both off by default (never pause, today's existing
  // behavior unchanged unless opted in). Confirmed with the user
  // 2026-07-06: both pause-and-resume rather than stopping permanently.
  const [useMaxDdStop, setUseMaxDdStop] = useState(false)
  const [maxDdStopPips, setMaxDdStopPips] = useState(100)
  const [useConsecutiveLossStop, setUseConsecutiveLossStop] = useState(false)
  const [consecutiveLossStopCount, setConsecutiveLossStopCount] = useState(3)
  const [consecutiveLossStopBars, setConsecutiveLossStopBars] = useState(100)

  // Entry order type - "market" (default) is today's unchanged behavior.
  // Not supported together with Long+Short同時 dual-direction mode - the
  // backend rejects that combination, so the UI hides this control while
  // dualDirectionMode is on rather than letting the user reach that error.
  const [entryMethod, setEntryMethod] = useState<'market' | 'limit' | 'stop'>('market')
  const [entryOffsetPips, setEntryOffsetPips] = useState(10)

  // Position sizing - off by default (results stay in raw pips, implied 1
  // lot, today's existing behavior unchanged unless opted in). Confirmed
  // with the user 2026-07-06: JPY/USD account currency switchable, default
  // 1,000,000 JPY capital, all three methods (risk%/fixed lot/compounding)
  // exposed since the user wants all three available.
  const [usePositionSizing, setUsePositionSizing] = useState(false)
  const [positionSizingMethod, setPositionSizingMethod] = useState<'risk_percent' | 'fixed_lot' | 'compounding'>('risk_percent')
  const [initialCapital, setInitialCapital] = useState(defaultSettings.initialCapital)
  const [accountCurrency, setAccountCurrency] = useState<'JPY' | 'USD'>(defaultSettings.accountCurrency)
  const [riskPercent, setRiskPercent] = useState(defaultSettings.riskPercent)
  const [fixedLotSize, setFixedLotSize] = useState(0.1)
  const [conversionRate, setConversionRate] = useState(defaultSettings.conversionRate)

  // Breakeven stop move and partial profit-taking - both off by default
  // (SL/TP stay exactly as RR-computed at entry, today's existing behavior
  // unchanged unless opted in).
  const [useBreakevenStop, setUseBreakevenStop] = useState(false)
  const [breakevenTriggerRr, setBreakevenTriggerRr] = useState(0.5)
  const [usePartialTp, setUsePartialTp] = useState(false)
  // Multi-stage: any number of (rr, fraction) levels, each closing
  // `fraction` of whatever REMAINS of the position at that level's rr.
  // Starts with one level (1.0RR/50%) matching this feature's original
  // single-level default.
  const [partialTpLevels, setPartialTpLevels] = useState<PartialTpLevel[]>(() => [{ rr: 1.0, fraction: 0.5 }])
  const addPartialTpLevel = () => setPartialTpLevels((prev) => [...prev, { rr: 1.0, fraction: 0.3 }])
  const removePartialTpLevel = (index: number) => setPartialTpLevels((prev) => prev.filter((_, i) => i !== index))
  const updatePartialTpLevel = (index: number, next: PartialTpLevel) =>
    setPartialTpLevels((prev) => prev.map((l, i) => (i === index ? next : l)))

  // Decoupled SL/TP basis - default to the values that reproduce the prior
  // fixed "RR from signal candle" behavior exactly.
  const [slBasis, setSlBasis] = useState<'signal_candle' | 'atr' | 'fixed_pips'>('signal_candle')
  const [slAtrLength, setSlAtrLength] = useState(14)
  const [slAtrMultiplier, setSlAtrMultiplier] = useState(2.0)
  const [slFixedPips, setSlFixedPips] = useState(20.0)
  const [tpBasis, setTpBasis] = useState<'rr' | 'fixed_pips' | 'custom'>('rr')
  const [tpFixedPips, setTpFixedPips] = useState(20.0)
  const [exitConditionTree, setExitConditionTree] = useState<GroupNode>(defaultTree())

  const queryClient = useQueryClient()

  const indicatorsQuery = useQuery({ queryKey: ['indicators'], queryFn: fetchIndicators })
  const loadStrategyMutation = useMutation({
    mutationFn: fetchStrategyDetail,
    onSuccess: (detail) => {
      setSymbol(detail.symbol)
      setTimeframe(detail.timeframe)
      setMode(detail.mode)
      if (detail.params.direction) setDirection(detail.params.direction)
      if (detail.params.long_condition_tree || detail.params.short_condition_tree) {
        setDualDirectionMode(true)
        if (detail.params.long_condition_tree) setLongTree(detail.params.long_condition_tree)
        if (detail.params.short_condition_tree) setShortTree(detail.params.short_condition_tree)
      } else {
        setDualDirectionMode(false)
        if (detail.params.condition_tree) setTree(detail.params.condition_tree as GroupNode)
      }
      if (typeof detail.params.rr === 'number') setRr(detail.params.rr)
      if (typeof detail.params.use_weekend_exit === 'boolean') setUseWeekendExit(detail.params.use_weekend_exit)
      if (typeof detail.params.weekend_exit_hour === 'number') setWeekendExitHour(detail.params.weekend_exit_hour)
      if (typeof detail.params.use_daily_exit === 'boolean') setUseDailyExit(detail.params.use_daily_exit)
      if (typeof detail.params.daily_exit_hour === 'number') setDailyExitHour(detail.params.daily_exit_hour)
      if (typeof detail.params.spread_pips === 'number') setSpreadPips(detail.params.spread_pips)
      if (typeof detail.params.slippage_pips === 'number') setSlippagePips(detail.params.slippage_pips)
      if (typeof detail.params.commission_per_trade === 'number') setCommissionPerTrade(detail.params.commission_per_trade)
      if (typeof detail.params.use_atr_trailing_stop === 'boolean') setUseAtrTrailingStop(detail.params.use_atr_trailing_stop)
      if (typeof detail.params.atr_trailing_length === 'number') setAtrTrailingLength(detail.params.atr_trailing_length)
      if (typeof detail.params.atr_trailing_multiplier === 'number') setAtrTrailingMultiplier(detail.params.atr_trailing_multiplier)
      if (typeof detail.params.use_max_dd_stop === 'boolean') setUseMaxDdStop(detail.params.use_max_dd_stop)
      if (typeof detail.params.max_dd_stop_pips === 'number') setMaxDdStopPips(detail.params.max_dd_stop_pips)
      if (typeof detail.params.use_consecutive_loss_stop === 'boolean') setUseConsecutiveLossStop(detail.params.use_consecutive_loss_stop)
      if (typeof detail.params.consecutive_loss_stop_count === 'number') setConsecutiveLossStopCount(detail.params.consecutive_loss_stop_count)
      if (typeof detail.params.consecutive_loss_stop_bars === 'number') setConsecutiveLossStopBars(detail.params.consecutive_loss_stop_bars)
      if (detail.params.entry_method === 'market' || detail.params.entry_method === 'limit' || detail.params.entry_method === 'stop') {
        setEntryMethod(detail.params.entry_method)
      }
      if (typeof detail.params.entry_offset_pips === 'number') setEntryOffsetPips(detail.params.entry_offset_pips)
      if (typeof detail.params.use_position_sizing === 'boolean') setUsePositionSizing(detail.params.use_position_sizing)
      if (
        detail.params.position_sizing_method === 'risk_percent' ||
        detail.params.position_sizing_method === 'fixed_lot' ||
        detail.params.position_sizing_method === 'compounding'
      ) {
        setPositionSizingMethod(detail.params.position_sizing_method)
      }
      if (typeof detail.params.initial_capital === 'number') setInitialCapital(detail.params.initial_capital)
      if (detail.params.account_currency === 'JPY' || detail.params.account_currency === 'USD') {
        setAccountCurrency(detail.params.account_currency)
      }
      if (typeof detail.params.risk_percent === 'number') setRiskPercent(detail.params.risk_percent)
      if (typeof detail.params.fixed_lot_size === 'number') setFixedLotSize(detail.params.fixed_lot_size)
      if (typeof detail.params.conversion_rate === 'number') setConversionRate(detail.params.conversion_rate)
      if (typeof detail.params.use_breakeven_stop === 'boolean') setUseBreakevenStop(detail.params.use_breakeven_stop)
      if (typeof detail.params.breakeven_trigger_rr === 'number') setBreakevenTriggerRr(detail.params.breakeven_trigger_rr)
      if (typeof detail.params.use_partial_tp === 'boolean') setUsePartialTp(detail.params.use_partial_tp)
      if (Array.isArray(detail.params.partial_tp_levels) && detail.params.partial_tp_levels.length > 0) {
        setPartialTpLevels(detail.params.partial_tp_levels as PartialTpLevel[])
      } else if (typeof detail.params.partial_tp_rr === 'number' && typeof detail.params.partial_tp_fraction === 'number') {
        setPartialTpLevels([{ rr: detail.params.partial_tp_rr, fraction: detail.params.partial_tp_fraction }])
      }
      if (detail.params.sl_basis === 'signal_candle' || detail.params.sl_basis === 'atr' || detail.params.sl_basis === 'fixed_pips') {
        setSlBasis(detail.params.sl_basis)
      }
      if (typeof detail.params.sl_atr_length === 'number') setSlAtrLength(detail.params.sl_atr_length)
      if (typeof detail.params.sl_atr_multiplier === 'number') setSlAtrMultiplier(detail.params.sl_atr_multiplier)
      if (typeof detail.params.sl_fixed_pips === 'number') setSlFixedPips(detail.params.sl_fixed_pips)
      if (detail.params.tp_basis === 'rr' || detail.params.tp_basis === 'fixed_pips' || detail.params.tp_basis === 'custom') {
        setTpBasis(detail.params.tp_basis)
      }
      if (typeof detail.params.tp_fixed_pips === 'number') setTpFixedPips(detail.params.tp_fixed_pips)
      if (detail.params.exit_condition_tree) setExitConditionTree(detail.params.exit_condition_tree as GroupNode)
    },
  })

  const runMutation = useMutation({
    mutationFn: () => {
      if (explorationMode !== 'manual') {
        return createBacktest({
          // dev/fullモードの差はRR(1パターンか3パターンか)だけだったが、
          // RRは下のrr_choicesで直接指定できるようになったので自動探索では
          // 常にdev固定を送る(main.py側の他フィールドは条件ツリー使用時は
          // 未使用なので実害なし、engine/backtest_engine.py参照)。
          mode: 'dev',
          timeframe,
          symbol,
          optimizer: explorationMode,
          direction: 'short', // unused by structure/structure_genetic - the engine generates its own
          n_candidates: nCandidates,
          max_depth: maxDepth,
          max_leaves: maxLeaves,
          min_trades: minTrades,
          mtf_probability: mtfProbability,
          mtf_timeframes: mtfTimeframes.trim() || undefined,
          population,
          mutation_rate: mutationRate,
          generations,
          categories,
          custom_indicator_names: customIndicatorNames,
          rr_choices: rrChoices.length > 0 ? rrChoices : undefined,
          direction_mode: dualDirectionMode ? 'both' : direction,
          start_date: startDate || undefined,
          end_date: endDate || undefined,
          min_leaves: minLeaves,
          selected_param_values: Object.keys(selectedParamValues).length > 0 ? selectedParamValues : undefined,
          selected_literal_values: Object.keys(selectedLiteralValues).length > 0 ? selectedLiteralValues : undefined,
          mandatory_conditions: mandatoryConditions.length > 0 ? mandatoryConditions : undefined,
          save_as: saveAsName.trim() || undefined,
        })
      }

      const activeRanges = paramRanges.filter((r) => r.enabled)
      const param_ranges =
        activeRanges.length > 0
          ? Object.fromEntries(activeRanges.map((r) => [r.param, buildRangeValues(r.min, r.max, r.step)]))
          : undefined
      const activeConditionRanges = dualDirectionMode
        ? []
        : conditionOptimizeRanges.filter(
            (r) => r.enabled && r.path && r.field && optionIsValid(tree, r.path, r.field),
          )
      const condition_tree_variants =
        activeConditionRanges.length > 0
          ? buildConditionTreeVariants(
              tree,
              activeConditionRanges.map((r) => ({
                path: r.path as number[],
                field: r.field as OptimizeField,
                values: buildRangeValues(r.min, r.max, r.step),
              })),
            )
          : undefined
      return createBacktest({
        mode,
        timeframe,
        symbol,
        optimizer: 'grid',
        direction,
        condition_tree: dualDirectionMode ? undefined : tree,
        condition_tree_variants,
        long_condition_tree: dualDirectionMode ? longTree : undefined,
        short_condition_tree: dualDirectionMode ? shortTree : undefined,
        param_ranges,
        rr,
        use_weekend_exit: useWeekendExit,
        weekend_exit_hour: weekendExitHour,
        use_daily_exit: useDailyExit,
        daily_exit_hour: dailyExitHour,
        spread_pips: spreadPips,
        slippage_pips: slippagePips,
        commission_per_trade: commissionPerTrade,
        use_atr_trailing_stop: useAtrTrailingStop,
        atr_trailing_length: atrTrailingLength,
        atr_trailing_multiplier: atrTrailingMultiplier,
        use_max_dd_stop: useMaxDdStop,
        max_dd_stop_pips: maxDdStopPips,
        use_consecutive_loss_stop: useConsecutiveLossStop,
        consecutive_loss_stop_count: consecutiveLossStopCount,
        consecutive_loss_stop_bars: consecutiveLossStopBars,
        // limit/stop isn't supported together with dual-direction mode -
        // force "market" here too as a second safety net even though the
        // UI already hides the control in that mode.
        entry_method: dualDirectionMode ? 'market' : entryMethod,
        entry_offset_pips: entryOffsetPips,
        use_position_sizing: usePositionSizing,
        position_sizing_method: positionSizingMethod,
        initial_capital: initialCapital,
        account_currency: accountCurrency,
        risk_percent: riskPercent,
        fixed_lot_size: fixedLotSize,
        conversion_rate: conversionRate,
        use_breakeven_stop: useBreakevenStop,
        breakeven_trigger_rr: breakevenTriggerRr,
        use_partial_tp: usePartialTp,
        partial_tp_levels: partialTpLevels,
        sl_basis: slBasis,
        sl_atr_length: slAtrLength,
        sl_atr_multiplier: slAtrMultiplier,
        sl_fixed_pips: slFixedPips,
        tp_basis: tpBasis,
        tp_fixed_pips: tpFixedPips,
        exit_condition_tree: tpBasis === 'custom' ? exitConditionTree : undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        save_as: saveAsName.trim() || undefined,
      })
    },
    onSuccess: (data) => {
      setJobId(data.job_id)
      // The old ranking (and any open strategy-detail tabs within it)
      // belongs to a run that no longer exists once a new one starts.
      setOpenTabRanks([])
      setVisibleRanks([])
      setFocusedRank(null)
      setTabJobIds({})
      setCustomNames({})
      setRunDate(new Date())
      setSaveJobIds({})
      setPendingSaveRanks(new Set())
    },
  })

  const stopMutation = useMutation({
    mutationFn: () => stopBacktest(jobId as string),
    onSuccess: () => setShowStopConfirm(false),
  })

  const statusQuery = useQuery({
    queryKey: ['backtest-status', jobId],
    queryFn: () => fetchBacktestStatus(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'done' || status === 'error' ? false : 1000
    },
    refetchIntervalInBackground: true,
  })

  useEffect(() => {
    try {
      if (jobId) localStorage.setItem(JOB_ID_STORAGE_KEY, jobId)
      else localStorage.removeItem(JOB_ID_STORAGE_KEY)
    } catch {
      // localStorageが使えない環境(プライベートモード等)でも動作自体は
      // 継続させる - このタブを閉じるまでは通常通り結果を表示できる。
    }
  }, [jobId])

  // ブラウザだけ閉じ直した場合は上のlocalStorageからjobIdが復元されるが、
  // バックエンドのプロセスごと再起動されていた場合はJOBSが空になっている
  // ため404が返る - その場合だけ諦めて待機状態に戻す(エラー表示のまま
  // 固まらないように)。マウント時に1回だけ直接fetchして確かめる
  // (statusQuery自体のリトライ/バックオフに任せると反映までに数秒〜かかる
  // ため、起動直後の一撃判定はここで済ませる)。
  useEffect(() => {
    if (jobId === null) return
    fetchBacktestStatus(jobId).catch((err: unknown) => {
      const status = (err as { response?: { status?: number } } | null)?.response?.status
      if (status === 404) setJobId(null)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const resultsQuery = useQuery<BacktestResults>({
    queryKey: ['backtest-results', jobId],
    queryFn: () => fetchBacktestResults(jobId as string),
    enabled: jobId !== null && statusQuery.data?.status === 'done',
  })

  // Re-running one ranking row the user clicked on (see RankingTable's
  // onSelectRow) - a separate job/poll/results trio mirroring the main
  // backtest's own three above, so a row selection never disturbs the
  // original ranking or the main run's own job state. One mutation is
  // enough (mutate() is called once per rank, not tied to a single
  // in-flight request), but status/results need one query PER open tab -
  // useQueries builds that array dynamically from openTabRanks.
  const rerunRowMutation = useMutation({
    mutationFn: (rank: number) => rerunRankingRow(jobId as string, rank),
    onSuccess: (data, rank) => setTabJobIds((prev) => ({ ...prev, [rank]: data.job_id })),
  })

  // 詳細タブ・比較・合成のどれかでチェックされた行はすべて同じ「1行だけ
  // 再計算」ジョブ(tabJobIds)を共有する - 同じrankを複数の用途で使っても
  // rerunは1回で済む。クエリ配列はこのunion順で構築し、strategyTabs等は
  // rankをキーにdetailRanksでの位置を引いて参照する。
  const detailRanks = Array.from(new Set([...openTabRanks, ...compareRanks, ...compositeRanks]))

  const tabStatusQueries = useQueries({
    queries: detailRanks.map((rank) => ({
      queryKey: ['backtest-status', tabJobIds[rank]],
      queryFn: () => fetchBacktestStatus(tabJobIds[rank] as string),
      enabled: tabJobIds[rank] != null,
      refetchInterval: (query: { state: { data?: { status?: string } } }) => {
        const status = query.state.data?.status
        return status === 'done' || status === 'error' ? false : 1000
      },
      refetchIntervalInBackground: true,
    })),
  })

  const tabResultsQueries = useQueries({
    queries: detailRanks.map((rank, i) => ({
      queryKey: ['backtest-results', tabJobIds[rank]],
      queryFn: () => fetchBacktestResults(tabJobIds[rank] as string),
      enabled: tabJobIds[rank] != null && tabStatusQueries[i]?.data?.status === 'done',
    })),
  })

  // Clicking a ranking row opens (or re-focuses) its tab and shows it alone
  // (replaces whatever was visible) - dragging one tab onto another is the
  // only way to build a side-by-side view (see StrategyDetailTabs.tsx).
  const openStrategyTab = (rank: number) => {
    setFocusedRank(rank)
    setOpenTabRanks((prev) => (prev.includes(rank) || prev.length >= MAX_DETAIL_TABS ? prev : [...prev, rank]))
    setVisibleRanks([rank])
    if (tabJobIds[rank] == null) rerunRowMutation.mutate(rank)
  }

  const closeStrategyTab = (rank: number) => {
    setOpenTabRanks((prev) => prev.filter((r) => r !== rank))
    setVisibleRanks((prev) => prev.filter((r) => r !== rank))
    if (focusedRank === rank) setFocusedRank(null)
  }

  const mergeStrategyTabs = (draggedRank: number, targetRank: number) => {
    if (draggedRank === targetRank) return
    setVisibleRanks((prev) => {
      const base = prev.includes(targetRank) ? prev : [targetRank]
      if (base.includes(draggedRank) || base.length >= MAX_VISIBLE_TABS) return base
      return [...base, draggedRank]
    })
  }

  // 複数並べて表示中のカード右上の×用: そのタブ自体は閉じず(タブバーには
  // 残る/ランキング一覧のチェックも外れない)、並び表示から外すだけ。
  const removeFromVisible = (rank: number) => {
    setVisibleRanks((prev) => prev.filter((r) => r !== rank))
  }

  // ランキング一覧のチェックボックス用: チェックを付けるとタブバーに追加され
  // (何も表示されていなければそのまま表示、既に何か表示中ならタブバーに
  // 追加するだけで表示は変えない)、外すとopenStrategyTab同様タブごと閉じる。
  // 従来「行クリックでタブを開く」だったonSelectRowの責務をチェックボックス
  // に統合したもの。
  const toggleRowChecked = (rank: number) => {
    if (openTabRanks.includes(rank)) {
      closeStrategyTab(rank)
      return
    }
    setFocusedRank(rank)
    setOpenTabRanks((prev) => (prev.length >= MAX_DETAIL_TABS ? prev : [...prev, rank]))
    setVisibleRanks((prev) => (prev.length === 0 ? [rank] : prev))
    if (tabJobIds[rank] == null) rerunRowMutation.mutate(rank)
  }

  const toggleCompareRank = (rank: number) => {
    setCompareRanks((prev) => (prev.includes(rank) ? prev.filter((r) => r !== rank) : [...prev, rank]))
    if (tabJobIds[rank] == null) rerunRowMutation.mutate(rank)
  }

  const toggleCompositeRank = (rank: number) => {
    setCompositeRanks((prev) => (prev.includes(rank) ? prev.filter((r) => r !== rank) : [...prev, rank]))
    if (tabJobIds[rank] == null) rerunRowMutation.mutate(rank)
  }

  // ライブラリ版ストラテジー詳細タブ(結果側のtoggleRowChecked等と同じ仕組み
  // をid文字列版で - 詳しくはlibraryOpenIds/libraryVisibleIdsの宣言部参照)。
  // 合成タブもtrade_logが要るので同じfetchStrategyResultsを共有する
  // (比較タブは/api/strategies/compareが別途equity_curveを返すので対象外)。
  const libraryDetailIds = Array.from(new Set([...libraryOpenIds, ...libraryCompositeIds]))
  const libraryResultsQueries = useQueries({
    queries: libraryDetailIds.map((id) => ({
      queryKey: ['strategy-results', id],
      queryFn: () => fetchStrategyResults(id),
    })),
  })

  const closeLibraryTab = (id: string) => {
    setLibraryOpenIds((prev) => prev.filter((x) => x !== id))
    setLibraryVisibleIds((prev) => prev.filter((x) => x !== id))
  }

  const toggleLibraryChecked = (id: string) => {
    if (libraryOpenIds.includes(id)) {
      closeLibraryTab(id)
      return
    }
    setLibraryOpenIds((prev) => (prev.length >= MAX_DETAIL_TABS ? prev : [...prev, id]))
    setLibraryVisibleIds((prev) => (prev.length === 0 ? [id] : prev))
  }

  const toggleLibraryComposite = (id: string) => {
    setLibraryCompositeIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const mergeLibraryTabs = (draggedId: string, targetId: string) => {
    if (draggedId === targetId) return
    setLibraryVisibleIds((prev) => {
      const base = prev.includes(targetId) ? prev : [targetId]
      if (base.includes(draggedId) || base.length >= MAX_VISIBLE_TABS) return base
      return [...base, draggedId]
    })
  }

  const removeLibraryFromVisible = (id: string) => {
    setLibraryVisibleIds((prev) => prev.filter((x) => x !== id))
  }

  const renameLibraryMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameStrategy(id, name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategies'] }),
  })

  // 🔖/⭐がクリックされた行をrerun_ranking_row.py --save-as経由でライブラリへ
  // 保存する(rerunRowMutationと同じ「rankごとにジョブを1つ持つ」パターン)。
  const saveRowMutation = useMutation({
    mutationFn: ({ rank, name, favorite }: { rank: number; name: string; favorite: boolean }) =>
      saveRankingRow(jobId as string, rank, name, favorite),
    onSuccess: (data, variables) => {
      setSaveJobIds((prev) => ({ ...prev, [variables.rank]: data.job_id }))
      setPendingSaveRanks((prev) => {
        const next = new Set(prev)
        next.delete(variables.rank)
        return next
      })
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
    },
    onError: (_error, variables) => {
      setPendingSaveRanks((prev) => {
        const next = new Set(prev)
        next.delete(variables.rank)
        return next
      })
    },
  })

  const favoriteToggleMutation = useMutation({
    mutationFn: (strategyId: string) => toggleStrategyFavorite(strategyId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategies'] }),
  })

  const deleteSavedMutation = useMutation({
    mutationFn: (strategyId: string) => deleteStrategy(strategyId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategies'] }),
  })

  // ライブラリ画面(LibraryScreen)がお気に入りをトグルしても、そこはApp.tsx
  // とは別のuseMutationインスタンスなので、以前はランキング一覧側の表示に
  // 一切反映されなかった(App.tsx内で完結する独自のfavoriteOverridesでしか
  // 上書きしていなかったため)。['strategies']クエリをApp.tsx側でも購読して
  // おき、そこから権威あるfavorite状態を引くようにすることで、保存/お気に
  // 入り操作がどちらの画面から行われても両方に反映されるようにする
  // (LibraryScreen/RankingTable双方の保存系ミューテーションが揃って
  // invalidateQueries({queryKey:['strategies']})を呼んでいるので、この
  // クエリは常に最新化される)。
  const strategiesQuery = useQuery({ queryKey: ['strategies', 'all'], queryFn: fetchStrategies })
  const favoriteById: Record<string, boolean> = {}
  for (const s of strategiesQuery.data ?? []) {
    favoriteById[s.id] = s.favorite
  }

  // ライブラリ版ストラテジー詳細タブの表示データ(strategyTabs/AutoExploration
  // Detailと同じ形だが、rerunジョブではなく保存済みスナップショットから読む)。
  const libraryStrategyTabs: LibraryTabData[] = libraryOpenIds.map((id) => {
    const entry = (strategiesQuery.data ?? []).find((s) => s.id === id)
    const query = libraryResultsQueries[libraryDetailIds.indexOf(id)]
    const trades = Number(entry?.metrics.trades) || 0
    const bestRow: RankingRow | undefined = entry
      ? {
          rank: 0,
          trades: entry.metrics.trades ?? 0,
          wins: 0,
          losses: 0,
          win_rate: entry.metrics.win_rate ?? 0,
          net_profit: entry.metrics.net_profit ?? 0,
          profit_factor: entry.metrics.profit_factor ?? 0,
          max_dd: entry.metrics.max_dd ?? 0,
          expected_value: trades > 0 ? (entry.metrics.net_profit ?? 0) / trades : 0,
          recovery_factor: entry.metrics.recovery_factor ?? 0,
          sharpe_ratio: entry.metrics.sharpe_ratio ?? 0,
          sortino_ratio: entry.metrics.sortino_ratio ?? 0,
          cagr: entry.metrics.cagr ?? 0,
          calmar_ratio: entry.metrics.calmar_ratio ?? 0,
          rr: 0,
          condition_tree: entry.params?.condition_tree ?? undefined,
          symbol: entry.symbol,
        }
      : undefined
    return {
      id,
      name: entry?.name ?? id,
      bestRow,
      displayResults: query?.data,
      isLoading: query?.isLoading ?? false,
      error: query?.isError ? '結果の読み込みに失敗しました。' : null,
      isFavorite: entry?.favorite ?? false,
    }
  })

  // ライブラリ>合成の表示データ(結果側のresultsCompositeInputsと同じ考え方)。
  const libraryCompositeInputs: CompositeInput[] = libraryCompositeIds
    .map((id): CompositeInput | null => {
      const entry = (strategiesQuery.data ?? []).find((s) => s.id === id)
      const query = libraryResultsQueries[libraryDetailIds.indexOf(id)]
      if (!query?.data) return null
      return {
        id,
        name: entry?.name ?? id,
        symbol: entry?.symbol,
        tradeLog: query.data.trade_log ?? [],
      }
    })
    .filter((input): input is CompositeInput => input != null)
  const libraryCompositePendingCount = libraryCompositeIds.length - libraryCompositeInputs.length

  const saveJobEntries = Object.entries(saveJobIds)

  const saveStatusQueries = useQueries({
    queries: saveJobEntries.map(([, jid]) => ({
      queryKey: ['backtest-status', jid],
      queryFn: () => fetchBacktestStatus(jid),
      refetchInterval: (query: { state: { data?: { status?: string } } }) => {
        const status = query.state.data?.status
        return status === 'done' || status === 'error' ? false : 1000
      },
      refetchIntervalInBackground: true,
    })),
  })

  const saveResultQueries = useQueries({
    queries: saveJobEntries.map(([, jid], i) => ({
      queryKey: ['save-result', jid],
      queryFn: () => fetchSaveResult(jid),
      enabled: saveStatusQueries[i]?.data?.status === 'done',
    })),
  })

  const savedMeta: Record<number, { id: string; favorite: boolean }> = {}
  const saveJobStatusByRank: Record<number, string | undefined> = {}
  saveJobEntries.forEach(([rankStr], i) => {
    const rank = Number(rankStr)
    saveJobStatusByRank[rank] = saveStatusQueries[i]?.data?.status
    const data = saveResultQueries[i]?.data
    if (!data) return
    savedMeta[rank] = { id: data.id, favorite: favoriteById[data.id] ?? data.favorite }
  })

  const resolveName = (rank: number) => customNames[rank] ?? defaultStrategyName(rank, runDate)

  // 保存ジョブ(バックテスト再計算を伴うため数秒かかる)がまだ完了して
  // いない間はtrue。この間は🔖/⭐を押しても再送しない(連打による重複保存
  // 防止)し、ボタン側にも「保存中」であることを表示する。
  const isRowSavePending = (rank: number): boolean => {
    if (pendingSaveRanks.has(rank)) return true
    const status = saveJobStatusByRank[rank]
    if (status == null) return false
    return status !== 'error' && savedMeta[rank] == null
  }

  // 🔖はチェックボックスと同じ完全なon/offトグル: オンで保存、オフでライブラリ
  // (保存済みストラテジー)から削除する。⭐はfalseに戻してもライブラリからは
  // 削除しない(favoriteはあくまで保存済みエントリの属性の一つ)。
  const handleBookmark = (rank: number) => {
    if (jobId === null || isRowSavePending(rank)) return
    const meta = savedMeta[rank]
    if (meta) {
      deleteSavedMutation.mutate(meta.id)
      setSaveJobIds((prev) => {
        const next = { ...prev }
        delete next[rank]
        return next
      })
    } else {
      setPendingSaveRanks((prev) => new Set(prev).add(rank))
      saveRowMutation.mutate({ rank, name: resolveName(rank), favorite: false })
    }
  }

  const handleFavorite = (rank: number) => {
    if (jobId === null || isRowSavePending(rank)) return
    const meta = savedMeta[rank]
    if (meta) {
      favoriteToggleMutation.mutate(meta.id)
    } else {
      setPendingSaveRanks((prev) => new Set(prev).add(rank))
      saveRowMutation.mutate({ rank, name: resolveName(rank), favorite: true })
    }
  }

  useEffect(() => {
    if (statusQuery.data?.status === 'done' && saveAsName.trim() !== '') {
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
    }
  }, [statusQuery.data?.status, saveAsName, queryClient])

  // If editing the condition tree removes/restructures a condition the user
  // previously marked for optimization, drop that row's stale selection
  // rather than silently keeping a path that now points somewhere else (or
  // at a different condition entirely). Re-checked again at submit time as
  // a second safety net.
  useEffect(() => {
    setConditionOptimizeRanges((prev) => {
      let changed = false
      const next = prev.map((r) => {
        if (r.path && r.field && !optionIsValid(tree, r.path, r.field)) {
          changed = true
          return { ...r, path: null, field: null }
        }
        return r
      })
      return changed ? next : prev
    })
  }, [tree])

  const results = resultsQuery.data

  // Per-tab display data for StrategyDetailTabs - one entry per open tab,
  // each independently resolving its own bestRow/displayResults/loading/
  // error from that tab's own rerun job (see tabStatusQueries/
  // tabResultsQueries above). ranking_total itself always comes from the
  // original `results` (a rerun doesn't recompute the whole ranking, just
  // one row's own trade_log/equity_curve - see rerun_ranking_row.py).
  const strategyTabs: StrategyTabData[] = openTabRanks.map((rank) => {
    const i = detailRanks.indexOf(rank)
    const status = tabStatusQueries[i]?.data?.status
    const isLoading = tabJobIds[rank] != null && !['done', 'error'].includes(status ?? 'queued')
    // Without this check, a failed row-rerun left isLoading permanently true
    // forever - 'error' isn't 'done', so the naive check above never stopped
    // waiting (found via a real packaging bug: rerun_ranking_row.py was
    // missing from build_package.ps1's file list, so every row click in a
    // packaged build failed invisibly behind a permanent loading spinner).
    const error = status === 'error' ? (tabStatusQueries[i]?.data?.error_summary ?? '再計算中にエラーが発生しました。') : null
    return {
      rank,
      name: resolveName(rank),
      bestRow: results?.ranking_total?.find((row) => Number(row.rank) === rank),
      displayResults: tabResultsQueries[i]?.data ?? results,
      isLoading,
      error,
      isFavorite: savedMeta[rank]?.favorite ?? false,
      isPending: isRowSavePending(rank),
    }
  })

  // RankingTableの名称セル/保存状態表示用に、全行分をまとめて解決しておく。
  const rankingNames: Record<number, string> = {}
  const rankingRowMeta: Record<
    number,
    { isChecked: boolean; isCompareChecked: boolean; isCompositeChecked: boolean; isSaved: boolean; isFavorite: boolean; isPending: boolean }
  > = {}
  for (const row of results?.ranking_total ?? []) {
    const rank = Number(row.rank)
    rankingNames[rank] = resolveName(rank)
    const meta = savedMeta[rank]
    rankingRowMeta[rank] = {
      isChecked: openTabRanks.includes(rank),
      isCompareChecked: compareRanks.includes(rank),
      isCompositeChecked: compositeRanks.includes(rank),
      isSaved: meta != null,
      isFavorite: meta?.favorite ?? false,
      isPending: isRowSavePending(rank),
    }
  }

  // 結果>比較・結果>合成の表示データ。どちらもdetailRanksの位置からtab
  // ResultsQueriesを引く(rerunが終わっていない行はequity_curve/trade_logが
  // 空のまま - CompareView/CompositeDetailはそれぞれ空配列を許容する)。
  const resultsCompareEntries: CompareEntry[] = compareRanks
    .map((rank) => results?.ranking_total?.find((row) => Number(row.rank) === rank))
    .filter((row): row is RankingRow => row != null)
    .map((row) => {
      const rank = Number(row.rank)
      const detail = tabResultsQueries[detailRanks.indexOf(rank)]?.data
      return {
        id: String(rank),
        name: rankingNames[rank] ?? `Strat${rank}`,
        symbol: (row.symbol as string) ?? symbol,
        timeframe: statusQuery.data?.timeframe ?? timeframe,
        favorite: savedMeta[rank]?.favorite ?? false,
        tags: [],
        metrics: {
          net_profit: Number(row.net_profit),
          profit_factor: Number(row.profit_factor),
          max_dd: Number(row.max_dd),
          win_rate: Number(row.win_rate),
          trades: Number(row.trades),
          recovery_factor: Number(row.recovery_factor),
          sharpe_ratio: Number(row.sharpe_ratio),
          sortino_ratio: Number(row.sortino_ratio),
          calmar_ratio: Number(row.calmar_ratio),
        },
        equity_curve: detail?.equity_curve?.map((p) => p.equity) ?? [],
      }
    })

  const resultsCompositeInputs: CompositeInput[] = compositeRanks
    .map((rank): CompositeInput | null => {
      const row = results?.ranking_total?.find((r) => Number(r.rank) === rank)
      const detail = tabResultsQueries[detailRanks.indexOf(rank)]?.data
      if (!detail) return null
      return {
        id: String(rank),
        name: rankingNames[rank] ?? `Strat${rank}`,
        symbol: (row?.symbol as string) ?? symbol,
        tradeLog: detail.trade_log ?? [],
      }
    })
    .filter((input): input is CompositeInput => input != null)
  const resultsCompositePendingCount = compositeRanks.length - resultsCompositeInputs.length

  // Back-compat scalars for ValidationScreen/ReportScreen, which only ever
  // needed "the one currently-relevant rank/row" and know nothing about
  // multiple open tabs - focusedRank (last opened/clicked tab) fills that
  // same role selectedRank used to.
  const bestRow =
    (focusedRank !== null
      ? results?.ranking_total?.find((row) => Number(row.rank) === focusedRank)
      : undefined) ?? results?.ranking_total?.[0]
  const isRunning = statusQuery.data && !['done', 'error'].includes(statusQuery.data.status)

  return (
    <div className="min-h-screen text-gray-200">
      <nav className="glass-nav sticky top-0 z-10 text-sm">
        <div className="flex items-center gap-5 px-4 py-3">
          <span className="brand-text text-base font-bold tracking-wide">Strategy Lab</span>
          {MAIN_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleMainTabClick(tab.id)}
              className={
                mainTab === tab.id
                  ? 'cursor-pointer font-semibold text-gray-100'
                  : 'cursor-pointer text-gray-400 transition-colors hover:text-gray-200'
              }
            >
              {tab.label}
            </button>
          ))}
        </div>
        {mainTab !== 'explore' && (
        <div className="flex items-center gap-4 border-t border-white/5 px-4 py-2 text-xs">
          {(MAIN_TABS.find((t) => t.id === mainTab)?.subTabs ?? []).map((st) => (
            <button
              key={st.id}
              type="button"
              onClick={() => handleSubTabClick(st.id)}
              className={
                subTab === st.id
                  ? 'rounded-full bg-blue-500/20 px-3 py-1 font-semibold text-blue-100'
                  : 'rounded-full px-3 py-1 text-gray-400 hover:bg-white/5 hover:text-gray-200'
              }
            >
              {st.label}
            </button>
          ))}
        </div>
        )}
      </nav>

      <div className="p-4">

        {mainTab === 'data' && subTab === 'dataset' && <DataScreen symbols={SYMBOLS} timeframes={TIMEFRAMES} />}
        {mainTab === 'data' && subTab === 'import' && <CsvImportScreen symbols={SYMBOLS} timeframes={TIMEFRAMES} />}
        {mainTab === 'data' && subTab === 'validator' && <DataValidatorScreen symbols={SYMBOLS} timeframes={TIMEFRAMES} />}

        {mainTab === 'library' && subTab === 'export' && (
          <ReportScreen
            jobId={jobId}
            jobDone={statusQuery.data?.status === 'done'}
            symbol={symbol}
            timeframe={timeframe}
            selectedRank={focusedRank}
            bestRow={bestRow}
            results={results}
          />
        )}
        {mainTab === 'library' && (subTab === 'saved' || subTab === 'favorites') && (
          <LibraryScreen
            favoritesOnly={subTab === 'favorites'}
            onLoad={(id) => loadStrategyMutation.mutate(id)}
            isLoading={loadStrategyMutation.isPending}
            compareIds={compareIds}
            onToggleCompare={toggleCompareId}
            onGoToCompare={() => {
              setMainTab('library')
              setSubTab('compare')
            }}
            indicators={indicatorsQuery.data ?? []}
            openIds={libraryOpenIds}
            onToggleChecked={toggleLibraryChecked}
            compositeIds={libraryCompositeIds}
            onToggleComposite={toggleLibraryComposite}
          />
        )}
        {mainTab === 'library' && subTab === 'detail' && (
          <LibraryDetailTabs
            openTabs={libraryStrategyTabs}
            visibleIds={libraryVisibleIds}
            indicators={indicatorsQuery.data ?? []}
            onSelectTab={(id) => setLibraryVisibleIds([id])}
            onCloseTab={closeLibraryTab}
            onMergeTabs={mergeLibraryTabs}
            onRemoveFromView={removeLibraryFromVisible}
            onRenameRow={(id, name) => renameLibraryMutation.mutate({ id, name })}
            onFavorite={(id) => favoriteToggleMutation.mutate(id)}
          />
        )}
        {mainTab === 'library' && subTab === 'compare' && <CompareScreen ids={compareIds} />}
        {mainTab === 'library' && subTab === 'composite' && (
          <CompositeDetail inputs={libraryCompositeInputs} pendingCount={libraryCompositePendingCount} />
        )}

        {mainTab === 'validation' && (
          <ValidationScreen
            subTab={subTab}
            symbol={symbol}
            timeframe={timeframe}
            effectiveRank={focusedRank ?? bestRow?.rank ?? null}
          />
        )}

        {mainTab === 'results' && subTab === 'compare' && (
          <CompareView
            entries={resultsCompareEntries}
            emptyMessage="比較対象がありません。ランキング一覧で「比較」のチェックを2件以上付けてください。"
          />
        )}
        {mainTab === 'results' && subTab === 'composite' && (
          <CompositeDetail inputs={resultsCompositeInputs} pendingCount={resultsCompositePendingCount} />
        )}

        {mainTab === 'results' && (subTab === 'ranking' || subTab === 'detail') && (
          <ResultsScreen
            subTab={subTab}
            results={results}
            strategyTabs={strategyTabs}
            visibleRanks={visibleRanks}
            indicators={indicatorsQuery.data ?? []}
            timeframe={statusQuery.data?.timeframe ?? timeframe}
            onSelectTab={openStrategyTab}
            onCloseTab={closeStrategyTab}
            onMergeTabs={mergeStrategyTabs}
            onRemoveFromView={removeFromVisible}
            onRenameRow={renameRow}
            jobId={jobId}
            names={rankingNames}
            rowMeta={rankingRowMeta}
            focusedRank={focusedRank}
            onToggleChecked={toggleRowChecked}
            rankingScrollTopRef={rankingScrollTopRef}
            onBookmark={handleBookmark}
            onFavorite={handleFavorite}
            onToggleCompare={toggleCompareRank}
            onToggleComposite={toggleCompositeRank}
          />
        )}

        {mainTab === 'settings' && <SettingsScreen subTab={subTab} />}

        {mainTab === 'explore' && (
          <div className="mb-3 flex flex-nowrap items-center gap-3 overflow-x-auto rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5">
            <div className="inline-flex h-9 flex-none items-stretch rounded-lg border border-white/10 bg-white/[0.03] p-0.5 text-sm font-semibold">
              <button
                type="button"
                onClick={() => handleExploreSubTabClick('manual')}
                className={
                  subTab === 'manual'
                    ? 'flex items-center rounded-md bg-blue-500/80 px-4 text-white shadow'
                    : 'flex items-center rounded-md px-4 text-gray-400 hover:text-gray-200'
                }
              >
                手動探索
              </button>
              <button
                type="button"
                onClick={() => handleExploreSubTabClick('auto')}
                className={
                  subTab === 'auto'
                    ? 'flex items-center rounded-md bg-purple-500/80 px-4 text-white shadow'
                    : 'flex items-center rounded-md px-4 text-gray-400 hover:text-gray-200'
                }
              >
                自動探索
              </button>
            </div>
            <select
              className="glass-input h-9 rounded-lg px-2 text-sm"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              className="glass-input h-9 rounded-lg px-2 text-sm"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
            <div className="inline-flex h-9 flex-none items-stretch rounded-lg border border-white/10 bg-white/[0.03] p-0.5 text-sm font-semibold">
              <button
                type="button"
                onClick={toggleShortActive}
                title="Short(売り)"
                className={
                  shortActive
                    ? 'flex items-center rounded-md bg-blue-500/80 px-4 text-white shadow'
                    : 'flex items-center rounded-md px-4 text-gray-400 hover:text-gray-200'
                }
              >
                Short
              </button>
              <button
                type="button"
                onClick={toggleLongActive}
                title="Long(買い)"
                className={
                  longActive
                    ? 'flex items-center rounded-md bg-purple-500/80 px-4 text-white shadow'
                    : 'flex items-center rounded-md px-4 text-gray-400 hover:text-gray-200'
                }
              >
                Long
              </button>
            </div>
            <div className="flex flex-none items-center gap-1.5 text-xs text-gray-400">
              <input
                type="date"
                className="glass-input h-9 w-[130px] flex-none rounded-lg px-2 text-sm"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
              <span>〜</span>
              <input
                type="date"
                className="glass-input h-9 w-[130px] flex-none rounded-lg px-2 text-sm"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            {isRunning ? (
              <button
                type="button"
                onClick={() => setShowStopConfirm(true)}
                disabled={statusQuery.data?.stop_requested}
                className="stop-button h-9 w-[136px] flex-none rounded-lg text-sm font-semibold text-white transition-shadow disabled:opacity-40"
              >
                {statusQuery.data?.stop_requested ? '停止処理中...' : '停止'}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => (jobId !== null ? setShowRunConfirm(true) : runMutation.mutate())}
                disabled={runMutation.isPending || (subTab === 'auto' && categories.length === 0)}
                className="run-button h-9 w-[136px] flex-none rounded-lg text-sm font-semibold text-white transition-shadow disabled:opacity-40"
              >
                バックテスト実行
              </button>
            )}
            <div className="ml-[35px] min-w-0 flex-1">
              <AutoExplorationHero
                progress={statusQuery.data?.progress}
                isRunning={isRunning}
                stopRequested={statusQuery.data?.stop_requested}
                compact
              />
            </div>
            {statusQuery.data?.status === 'done' && statusQuery.data.stopped && (
              <div className="flex-none rounded-lg border border-amber-500/20 bg-amber-950/30 px-2.5 py-1 text-xs text-amber-300">
                途中で停止しました(そこまでの結果を表示中)
              </div>
            )}
          </div>
        )}

        {mainTab === 'explore' && subTab === 'manual' && explorationMode === 'manual' && (
          <>
            <div className="glass-panel flex flex-col rounded-2xl">
              <div className="glass-panel-header rounded-t-2xl px-3 py-2 text-sm font-semibold tracking-wide text-gray-200">
                ストラテジービルダー
              </div>
              <div className="p-3">
              <div className="space-y-3">
                <div className="flex items-center gap-4">
                  {!dualDirectionMode && (
                    <div className="flex items-center gap-1 text-xs text-gray-300">
                      <select
                        className="glass-input rounded-lg px-2 py-1.5"
                        value={entryMethod}
                        onChange={(e) => setEntryMethod(e.target.value as 'market' | 'limit' | 'stop')}
                      >
                        <option value="market">成行(条件確定の次の足で即エントリー)</option>
                        <option value="limit">指値(有利な価格まで戻ったら約定)</option>
                        <option value="stop">逆指値(さらにブレイクしたら約定)</option>
                      </select>
                      {entryMethod !== 'market' && (
                        <label className="flex items-center gap-1">
                          オフセット
                          <input
                            type="number"
                            min={0}
                            step={0.5}
                            className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs"
                            value={entryOffsetPips}
                            onChange={(e) => setEntryOffsetPips(Number(e.target.value))}
                          />
                          pips
                        </label>
                      )}
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4 items-stretch">
                <div className="flex h-[calc(100vh-310px)] flex-col rounded-lg border border-white/10 bg-white/[0.02] p-2">
                <div className="flex-none text-sm font-semibold text-gray-200">エントリー条件</div>

                <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pt-1.5">
                {indicatorsQuery.data && !dualDirectionMode && (
                  <ConditionTreeEditor node={tree} indicators={indicatorsQuery.data} onChange={setTree} />
                )}

                {indicatorsQuery.data && dualDirectionMode && (
                  <div className="space-y-3">
                    <div>
                      <div className="mb-1 text-xs font-semibold text-blue-300">Long条件</div>
                      <ConditionTreeEditor node={longTree} indicators={indicatorsQuery.data} onChange={setLongTree} />
                    </div>
                    <div>
                      <div className="mb-1 text-xs font-semibold text-purple-300">Short条件</div>
                      <ConditionTreeEditor node={shortTree} indicators={indicatorsQuery.data} onChange={setShortTree} />
                    </div>
                  </div>
                )}
                </div>

                </div>

                <div className="space-y-3">
                {explorationMode === 'manual' && (
                <div className="flex h-[calc(100vh-310px)] flex-col rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <div className="flex-none text-sm font-semibold text-gray-200">決済条件</div>

                  <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pt-1.5">
                  <div className="space-y-1 rounded-lg border border-white/10 bg-white/[0.02] p-1.5">
                    <div className="text-xs font-semibold text-gray-300">利確(TP)</div>
                    <div className="flex flex-col gap-1 text-xs text-gray-300">
                      <label className="flex items-center gap-1.5">
                        <input type="radio" name="tp_basis" checked={tpBasis === 'rr'} onChange={() => setTpBasis('rr')} />
                        RR方式(リスクリワード比)
                        <input
                          type="number"
                          step={0.1}
                          min={0.1}
                          disabled={tpBasis !== 'rr'}
                          className="glass-input ml-auto w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={rr}
                          onChange={(e) => setRr(Number(e.target.value))}
                        />
                      </label>
                      <label className="flex items-center gap-1.5">
                        <input type="radio" name="tp_basis" checked={tpBasis === 'fixed_pips'} onChange={() => setTpBasis('fixed_pips')} />
                        固定pips
                        <input
                          type="number"
                          step={1}
                          min={0.1}
                          disabled={tpBasis !== 'fixed_pips'}
                          className="glass-input ml-auto w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={tpFixedPips}
                          onChange={(e) => setTpFixedPips(Number(e.target.value))}
                        />
                      </label>
                      <label className="flex items-center gap-1.5">
                        <input type="radio" name="tp_basis" checked={tpBasis === 'custom'} onChange={() => setTpBasis('custom')} />
                        カスタム条件
                      </label>
                    </div>
                    {tpBasis === 'custom' && indicatorsQuery.data && (
                      <div className="pl-5">
                        <ConditionTreeEditor node={exitConditionTree} indicators={indicatorsQuery.data} onChange={setExitConditionTree} />
                      </div>
                    )}
                  </div>

                  <div className="space-y-1 rounded-lg border border-white/10 bg-white/[0.02] p-1.5">
                    <div className="text-xs font-semibold text-gray-300">損切り(SL)</div>
                    <div className="flex flex-col gap-1 text-xs text-gray-300">
                      <label className="flex items-center gap-1.5">
                        <input type="radio" name="sl_basis" checked={slBasis === 'signal_candle'} onChange={() => setSlBasis('signal_candle')} />
                        直近高値/安値(シグナル足)
                      </label>
                      <label className="flex items-center gap-1.5">
                        <input type="radio" name="sl_basis" checked={slBasis === 'atr'} onChange={() => setSlBasis('atr')} />
                        ATR
                        <input
                          type="number"
                          step={1}
                          min={1}
                          disabled={slBasis !== 'atr'}
                          className="glass-input ml-auto w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={slAtrLength}
                          onChange={(e) => setSlAtrLength(Number(e.target.value))}
                        />
                        <input
                          type="number"
                          step={0.1}
                          min={0.1}
                          disabled={slBasis !== 'atr'}
                          className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={slAtrMultiplier}
                          onChange={(e) => setSlAtrMultiplier(Number(e.target.value))}
                        />
                        倍
                      </label>
                      <label className="flex items-center gap-1.5">
                        <input type="radio" name="sl_basis" checked={slBasis === 'fixed_pips'} onChange={() => setSlBasis('fixed_pips')} />
                        固定pips
                        <input
                          type="number"
                          step={1}
                          min={0.1}
                          disabled={slBasis !== 'fixed_pips'}
                          className="glass-input ml-auto w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={slFixedPips}
                          onChange={(e) => setSlFixedPips(Number(e.target.value))}
                        />
                      </label>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-1.5">
                    <label className="flex items-center gap-1 text-xs text-gray-300">
                      <input
                        type="checkbox"
                        checked={useWeekendExit}
                        onChange={(e) => setUseWeekendExit(e.target.checked)}
                      />
                      週末決済
                      <input
                        type="number"
                        min={0}
                        max={23}
                        disabled={!useWeekendExit}
                        className="glass-input ml-auto w-14 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={weekendExitHour}
                        onChange={(e) => setWeekendExitHour(Number(e.target.value))}
                      />
                      時
                    </label>
                    <label className="flex items-center gap-1 text-xs text-gray-300">
                      <input
                        type="checkbox"
                        checked={useDailyExit}
                        onChange={(e) => setUseDailyExit(e.target.checked)}
                      />
                      日次決済
                      <input
                        type="number"
                        min={0}
                        max={23}
                        disabled={!useDailyExit}
                        className="glass-input ml-auto w-14 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={dailyExitHour}
                        onChange={(e) => setDailyExitHour(Number(e.target.value))}
                      />
                      時
                    </label>
                  </div>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useAtrTrailingStop}
                      onChange={(e) => setUseAtrTrailingStop(e.target.checked)}
                    />
                    ATRトレーリングストップを使う
                  </label>
                  <div className="grid grid-cols-2 gap-1.5 pl-5 text-xs text-gray-300">
                    <label className="flex flex-col gap-1">
                      <span>期間</span>
                      <input
                        type="number"
                        min={1}
                        disabled={!useAtrTrailingStop}
                        className="glass-input w-full rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={atrTrailingLength}
                        onChange={(e) => setAtrTrailingLength(Number(e.target.value))}
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span>倍率</span>
                      <input
                        type="number"
                        step={0.1}
                        min={0.1}
                        disabled={!useAtrTrailingStop}
                        className="glass-input w-full rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={atrTrailingMultiplier}
                        onChange={(e) => setAtrTrailingMultiplier(Number(e.target.value))}
                      />
                    </label>
                  </div>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useBreakevenStop}
                      onChange={(e) => setUseBreakevenStop(e.target.checked)}
                    />
                    建値移動(ブレイクイーブン)
                    <span className="ml-auto flex items-center gap-1">
                      RR
                      <input
                        type="number"
                        step={0.1}
                        min={0}
                        disabled={!useBreakevenStop}
                        className="glass-input w-14 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={breakevenTriggerRr}
                        onChange={(e) => setBreakevenTriggerRr(Number(e.target.value))}
                      />
                    </span>
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={usePartialTp}
                      onChange={(e) => setUsePartialTp(e.target.checked)}
                    />
                    部分利確を使う(複数段階可・残りに対する割合)
                  </label>
                  <div className={`space-y-1.5 pl-5 ${!usePartialTp ? 'opacity-40' : ''}`}>
                    {partialTpLevels.map((level, i) => (
                      <div key={i} className="flex items-end gap-1.5 text-xs text-gray-300">
                        <label className="flex flex-1 flex-col gap-1">
                          <span>到達RR</span>
                          <input
                            type="number"
                            step={0.1}
                            min={0.1}
                            disabled={!usePartialTp}
                            className="glass-input w-full rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                            value={level.rr}
                            onChange={(e) => updatePartialTpLevel(i, { ...level, rr: Number(e.target.value) })}
                          />
                        </label>
                        <label className="flex flex-1 flex-col gap-1">
                          <span>決済割合</span>
                          <input
                            type="number"
                            step={0.05}
                            min={0.05}
                            max={0.95}
                            disabled={!usePartialTp}
                            className="glass-input w-full rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                            value={level.fraction}
                            onChange={(e) => updatePartialTpLevel(i, { ...level, fraction: Number(e.target.value) })}
                          />
                        </label>
                        {partialTpLevels.length > 1 && (
                          <button
                            type="button"
                            disabled={!usePartialTp}
                            onClick={() => removePartialTpLevel(i)}
                            className="text-gray-500 hover:text-red-400 disabled:opacity-40"
                            title="この段階を削除"
                          >
                            ✕
                          </button>
                        )}
                      </div>
                    ))}
                    <button
                      type="button"
                      disabled={!usePartialTp}
                      onClick={addPartialTpLevel}
                      className="w-full rounded-lg border border-dashed border-white/20 px-2 py-1 text-xs text-gray-400 hover:bg-white/5 hover:text-gray-200 disabled:opacity-40"
                    >
                      + 段階を追加
                    </button>
                  </div>
                  </div>
                </div>
                )}
                </div>
                </div>

                {explorationMode === 'manual' && (
                <>
                <button
                  type="button"
                  onClick={() => setManualAdvOpen((v) => !v)}
                  className="flex items-center gap-1.5 text-[10.5px] text-gray-400 hover:text-gray-200"
                >
                  <span className={`text-[9px] transition-transform ${manualAdvOpen ? 'rotate-90' : ''}`}>▸</span>
                  詳細設定(リスク管理・資金管理・コスト・パラメータ最適化)
                </button>

                {manualAdvOpen && (
                <>

                <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <div className="text-xs font-semibold text-gray-400">リスク管理(任意・一時停止して再開)</div>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useMaxDdStop}
                      onChange={(e) => setUseMaxDdStop(e.target.checked)}
                    />
                    最大DDストップを使う
                  </label>
                  <label className="flex items-center justify-between gap-1 pl-5 text-xs text-gray-300">
                    <span>上限</span>
                    <span className="flex items-center gap-1">
                      <input
                        type="number"
                        min={0}
                        step={1}
                        disabled={!useMaxDdStop}
                        className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={maxDdStopPips}
                        onChange={(e) => setMaxDdStopPips(Number(e.target.value))}
                      />
                      pips
                    </span>
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={useConsecutiveLossStop}
                      onChange={(e) => setUseConsecutiveLossStop(e.target.checked)}
                    />
                    連敗ストップを使う
                  </label>
                  <div className="flex flex-col gap-1.5 pl-5 text-xs text-gray-300">
                    <label className="flex items-center justify-between gap-1">
                      <span>連敗数</span>
                      <input
                        type="number"
                        min={1}
                        disabled={!useConsecutiveLossStop}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={consecutiveLossStopCount}
                        onChange={(e) => setConsecutiveLossStopCount(Number(e.target.value))}
                      />
                    </label>
                    <label className="flex items-center justify-between gap-1">
                      <span>停止バー数</span>
                      <input
                        type="number"
                        min={1}
                        disabled={!useConsecutiveLossStop}
                        className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={consecutiveLossStopBars}
                        onChange={(e) => setConsecutiveLossStopBars(Number(e.target.value))}
                      />
                    </label>
                  </div>
                </div>

                <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-400">
                    <input
                      type="checkbox"
                      checked={usePositionSizing}
                      onChange={(e) => setUsePositionSizing(e.target.checked)}
                    />
                    資金管理(ポジションサイジング)を使う
                  </label>
                  <div className={`space-y-1.5 pl-5 text-xs text-gray-300 ${!usePositionSizing ? 'opacity-40' : ''}`}>
                    <label className="flex flex-col gap-1">
                      <span>方式</span>
                      <select
                        className="glass-input w-full rounded-lg px-1.5 py-1 text-xs"
                        disabled={!usePositionSizing}
                        value={positionSizingMethod}
                        onChange={(e) => setPositionSizingMethod(e.target.value as 'risk_percent' | 'fixed_lot' | 'compounding')}
                      >
                        <option value="risk_percent">資金%リスク(初期資金基準)</option>
                        <option value="fixed_lot">固定ロット</option>
                        <option value="compounding">複利(資金%を都度の残高で計算)</option>
                      </select>
                    </label>
                    <div className="flex flex-col gap-1.5">
                      <label className="flex items-center justify-between gap-1">
                        <span>初期資金</span>
                        <input
                          type="number"
                          min={0}
                          step={10000}
                          disabled={!usePositionSizing}
                          className="glass-input w-24 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={initialCapital}
                          onChange={(e) => setInitialCapital(Number(e.target.value))}
                        />
                      </label>
                      <label className="flex items-center justify-between gap-1">
                        <span>口座通貨</span>
                        <select
                          className="glass-input w-16 rounded-lg px-1.5 py-1 text-xs"
                          disabled={!usePositionSizing}
                          value={accountCurrency}
                          onChange={(e) => setAccountCurrency(e.target.value as 'JPY' | 'USD')}
                        >
                          <option value="JPY">JPY</option>
                          <option value="USD">USD</option>
                        </select>
                      </label>
                    </div>
                    {(positionSizingMethod === 'risk_percent' || positionSizingMethod === 'compounding') && (
                      <label className="flex items-center justify-between gap-1">
                        <span>リスク%(1取引あたり)</span>
                        <input
                          type="number"
                          min={0.01}
                          step={0.1}
                          disabled={!usePositionSizing}
                          className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={riskPercent}
                          onChange={(e) => setRiskPercent(Number(e.target.value))}
                        />
                      </label>
                    )}
                    {positionSizingMethod === 'fixed_lot' && (
                      <label className="flex items-center justify-between gap-1">
                        <span>固定ロット数</span>
                        <input
                          type="number"
                          min={0.01}
                          step={0.01}
                          disabled={!usePositionSizing}
                          className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                          value={fixedLotSize}
                          onChange={(e) => setFixedLotSize(Number(e.target.value))}
                        />
                      </label>
                    )}
                    <label className="flex flex-col gap-1">
                      <span>為替換算レート(通貨ペア⇔口座通貨)</span>
                      <input
                        type="number"
                        min={0.01}
                        step={0.01}
                        disabled={!usePositionSizing}
                        className="glass-input w-full rounded-lg px-1.5 py-1 text-xs disabled:opacity-40"
                        value={conversionRate}
                        onChange={(e) => setConversionRate(Number(e.target.value))}
                      />
                    </label>
                    <div className="text-[11px] text-gray-500">
                      ※為替換算レートはバックテスト全期間で固定の概算値です(日々の実勢レートではありません)
                    </div>
                  </div>
                </div>

                <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                  <div className="text-xs font-semibold text-gray-400">設定(約定コスト・任意)</div>
                  <label className="flex items-center justify-between text-xs text-gray-300">
                    スプレッド(pips)
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs"
                      value={spreadPips}
                      onChange={(e) => setSpreadPips(Number(e.target.value))}
                    />
                  </label>
                  <label className="flex items-center justify-between text-xs text-gray-300">
                    スリッページ(pips)
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs"
                      value={slippagePips}
                      onChange={(e) => setSlippagePips(Number(e.target.value))}
                    />
                  </label>
                  <label className="flex items-center justify-between text-xs text-gray-300">
                    手数料(1取引あたり)
                    <input
                      type="number"
                      step={0.01}
                      min={0}
                      className="glass-input w-20 rounded-lg px-1.5 py-1 text-xs"
                      value={commissionPerTrade}
                      onChange={(e) => setCommissionPerTrade(Number(e.target.value))}
                    />
                  </label>
                </div>

                <div className="space-y-2">
                  <div className="text-xs font-semibold text-gray-400">パラメータ最適化(任意・いくつでも追加可)</div>
                  {paramRanges.map((range, i) => (
                    <ParamRangeRow
                      key={i}
                      label={`パラメータ${i + 1}`}
                      value={range}
                      onChange={(next) => updateParamRange(i, next)}
                      onRemove={paramRanges.length > 1 ? () => removeParamRange(i) : undefined}
                    />
                  ))}
                  <button
                    type="button"
                    onClick={addParamRange}
                    className="w-full rounded-lg border border-dashed border-white/20 px-2 py-1 text-xs text-gray-400 hover:bg-white/5 hover:text-gray-200"
                  >
                    + パラメータ範囲を追加
                  </button>
                </div>

                {!dualDirectionMode &&
                  (() => {
                    const optimizableConditions = collectOptimizableConditions(tree)
                    return (
                      <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                        <div className="text-xs font-semibold text-gray-400">条件ツリー内の値を最適化</div>
                        {optimizableConditions.length === 0 ? (
                          <div className="text-[11px] text-gray-500">最適化できる条件がありません</div>
                        ) : (
                          <>
                            {conditionOptimizeRanges.map((range, i) => (
                              <div key={i} className="space-y-1.5 rounded-lg border border-white/10 bg-white/[0.02] p-2">
                                <label className="flex items-center gap-1.5 text-xs text-gray-300">
                                  <input
                                    type="checkbox"
                                    checked={range.enabled}
                                    onChange={(e) => updateConditionOptimizeRange(i, { ...range, enabled: e.target.checked })}
                                  />
                                  範囲{i + 1}を最適化
                                  {conditionOptimizeRanges.length > 1 && (
                                    <button
                                      type="button"
                                      onClick={() => removeConditionOptimizeRange(i)}
                                      className="ml-auto text-gray-500 hover:text-red-400"
                                      title="この範囲を削除"
                                    >
                                      ✕
                                    </button>
                                  )}
                                </label>
                                <div className={`space-y-1.5 ${!range.enabled ? 'opacity-40' : ''}`}>
                                  <select
                                    className="glass-input w-full rounded-lg px-1.5 py-1 text-xs"
                                    disabled={!range.enabled}
                                    value={range.path ? JSON.stringify({ path: range.path, field: range.field }) : ''}
                                    onChange={(e) => {
                                      if (!e.target.value) {
                                        updateConditionOptimizeRange(i, { ...range, path: null, field: null })
                                        return
                                      }
                                      const selected = JSON.parse(e.target.value) as {
                                        path: number[]
                                        field: OptimizeField
                                      }
                                      updateConditionOptimizeRange(i, {
                                        ...range,
                                        path: selected.path,
                                        field: selected.field,
                                      })
                                    }}
                                  >
                                    <option value="">対象の条件を選択</option>
                                    {optimizableConditions.map((c) => (
                                      <option
                                        key={JSON.stringify({ path: c.path, field: c.field })}
                                        value={JSON.stringify({ path: c.path, field: c.field })}
                                      >
                                        {c.label}
                                      </option>
                                    ))}
                                  </select>
                                  <div className="grid grid-cols-3 gap-1.5">
                                    <label className="flex flex-col gap-1 text-xs text-gray-300">
                                      <span>最小</span>
                                      <input
                                        type="number"
                                        disabled={!range.enabled}
                                        className="glass-input w-full min-w-0 rounded-lg px-1 py-1 text-xs disabled:opacity-40"
                                        value={range.min}
                                        onChange={(e) => updateConditionOptimizeRange(i, { ...range, min: Number(e.target.value) })}
                                      />
                                    </label>
                                    <label className="flex flex-col gap-1 text-xs text-gray-300">
                                      <span>最大</span>
                                      <input
                                        type="number"
                                        disabled={!range.enabled}
                                        className="glass-input w-full min-w-0 rounded-lg px-1 py-1 text-xs disabled:opacity-40"
                                        value={range.max}
                                        onChange={(e) => updateConditionOptimizeRange(i, { ...range, max: Number(e.target.value) })}
                                      />
                                    </label>
                                    <label className="flex flex-col gap-1 text-xs text-gray-300">
                                      <span>刻み</span>
                                      <input
                                        type="number"
                                        disabled={!range.enabled}
                                        className="glass-input w-full min-w-0 rounded-lg px-1 py-1 text-xs disabled:opacity-40"
                                        value={range.step}
                                        onChange={(e) => updateConditionOptimizeRange(i, { ...range, step: Number(e.target.value) })}
                                      />
                                    </label>
                                  </div>
                                </div>
                              </div>
                            ))}
                            <button
                              type="button"
                              onClick={addConditionOptimizeRange}
                              className="w-full rounded-lg border border-dashed border-white/20 px-2 py-1 text-xs text-gray-400 hover:bg-white/5 hover:text-gray-200"
                            >
                              + 範囲を追加
                            </button>
                          </>
                        )}
                      </div>
                    )
                  })()}
                </>
                )}

                </>
                )}

                {statusQuery.data?.status === 'error' && (
                  <div className="rounded-lg border border-red-500/20 bg-red-950/40 p-2.5 text-xs text-red-200">
                    <p className="whitespace-pre-wrap leading-relaxed">
                      {statusQuery.data.error_summary ?? 'バックテストの実行中にエラーが発生しました。'}
                    </p>
                    {statusQuery.data.error && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-red-400 hover:text-red-300">詳細を見る(技術情報)</summary>
                        <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-black/30 p-2 text-[11px] text-red-300">
                          {statusQuery.data.error}
                        </pre>
                      </details>
                    )}
                  </div>
                )}
              </div>
              </div>
            </div>

          </>
        )}

        {mainTab === 'explore' && subTab === 'auto' && (
          <AutoExplorationScreen
            explorationMode={explorationMode}
            setExplorationMode={setExplorationMode}
            explorationAdvOpen={explorationAdvOpen}
            setExplorationAdvOpen={setExplorationAdvOpen}
            categories={categories}
            setCategories={setCategories}
            customIndicatorNames={customIndicatorNames}
            setCustomIndicatorNames={setCustomIndicatorNames}
            selectedParamValues={selectedParamValues}
            setSelectedParamValues={setSelectedParamValues}
            selectedLiteralValues={selectedLiteralValues}
            setSelectedLiteralValues={setSelectedLiteralValues}
            nCandidates={nCandidates}
            setNCandidates={setNCandidates}
            maxDepth={maxDepth}
            setMaxDepth={setMaxDepth}
            minLeaves={minLeaves}
            setMinLeaves={setMinLeaves}
            maxLeaves={maxLeaves}
            setMaxLeaves={setMaxLeaves}
            minTrades={minTrades}
            setMinTrades={setMinTrades}
            mtfProbability={mtfProbability}
            setMtfProbability={setMtfProbability}
            mtfTimeframes={mtfTimeframes}
            setMtfTimeframes={setMtfTimeframes}
            population={population}
            setPopulation={setPopulation}
            generations={generations}
            setGenerations={setGenerations}
            mutationRate={mutationRate}
            setMutationRate={setMutationRate}
            rrChoices={rrChoices}
            setRrChoices={setRrChoices}
            mandatoryConditions={mandatoryConditions}
            setMandatoryConditions={setMandatoryConditions}
            indicators={indicatorsQuery.data ?? []}
            saveAsName={saveAsName}
            setSaveAsName={setSaveAsName}
            statusData={statusQuery.data}
          />
        )}

        {showStopConfirm && isRunning && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
            <div className="glass-panel w-full max-w-sm rounded-2xl p-5">
              <h2 className="text-sm font-semibold text-gray-100">バックテストを停止しますか?</h2>
              <p className="mt-2 text-xs leading-relaxed text-gray-400">
                ここまでに完了した候補の結果だけが「結果」タブに反映されます。まだ実行中の候補は破棄されます。
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowStopConfirm(false)}
                  disabled={stopMutation.isPending}
                  className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200 disabled:opacity-40"
                >
                  キャンセル
                </button>
                <button
                  type="button"
                  onClick={() => stopMutation.mutate()}
                  disabled={stopMutation.isPending}
                  className="stop-button rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                >
                  {stopMutation.isPending ? '停止中...' : '停止する'}
                </button>
              </div>
            </div>
          </div>
        )}

        {showRunConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
            <div className="glass-panel w-full max-w-sm rounded-2xl p-5">
              <h2 className="text-sm font-semibold text-gray-100">バックテストを実行します</h2>
              <p className="mt-2 text-xs leading-relaxed text-gray-400">
                未保存の探索結果は破棄されますがよろしいですか?
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowRunConfirm(false)}
                  className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200"
                >
                  キャンセル
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowRunConfirm(false)
                    runMutation.mutate()
                  }}
                  className="run-button rounded-lg px-3 py-1.5 text-xs font-semibold text-white"
                >
                  実行する
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
