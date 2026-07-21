import { useEffect } from 'react'
import { CONDITION_GENRE_ORDER, conditionGenreOf, groupIndicatorsByGenre, type ConditionGenreKey } from '../conditionGenres'
import type { ConditionNode, ConditionParams, IndicatorInfo, IndicatorParamSpec, Operator } from '../types'

const OPERATORS: { id: Operator; label: string }[] = [
  { id: '>', label: 'より上 (>)' },
  { id: '<', label: 'より下 (<)' },
  { id: '>=', label: '以上 (>=)' },
  { id: '<=', label: '以下 (<=)' },
  { id: '==', label: '一致 (==)' },
  { id: 'crosses_above', label: '上抜け' },
  { id: 'crosses_below', label: '下抜け' },
]

// Multi-timeframe conditions: reference a different timeframe's own data
// for this indicator (e.g. a 15m strategy filtering by a 1h/4h/daily EMA).
// The empty option means "no override" (undefined - the backtest's own base
// timeframe, today's existing behavior).
const TIMEFRAME_OPTIONS = ['1m', '5m', '10m', '15m', '30m', '1h', '4h', '1d', '1w', '1mo']

interface Props {
  node: ConditionNode
  indicators: IndicatorInfo[]
  onChange: (next: ConditionNode) => void
  onRemove?: () => void
}

function indicatorInfo(indicators: IndicatorInfo[], id: string): IndicatorInfo | undefined {
  return indicators.find((i) => i.id === id)
}

// 指標比較モードへ切り替える/自動補正する時の既定の比較先を選ぶ - 「終値」
// (=価格そのもの)を優先する(EMAなどを終値と比較するのが最も一般的で、
// これだけで完結した条件になるため)。ただしメイン指標自体が終値の場合は
// 「終値 vs 終値」という無意味な自己比較になってしまうため、その時だけ
// 終値以外の先頭の指標にフォールバックする(実際に踏んだ不具合)。
// kindを渡した場合はそのkind(価格水準/オシレーター0-100など)が一致する
// 指標だけを候補にする(ユーザー報告:「EMAの比較先でRSIとか選べるのおかしい」
// - 単位もスケールも違う指標同士を比較しても意味がないため)。該当kindに
// 自分以外の候補が無い場合(候補が少ないkindなど)は全指標にフォールバック。
function defaultCompareIndicator(
  indicators: IndicatorInfo[],
  excludeId: string,
  kind?: string | null
): IndicatorInfo | undefined {
  const scoped = kind ? indicators.filter((i) => i.kind === kind) : indicators
  const pool = scoped.some((i) => i.id !== excludeId) ? scoped : indicators
  const close = pool.find((i) => i.id === 'close')
  if (close && close.id !== excludeId) return close
  return pool.find((i) => i.id !== excludeId) ?? pool[0]
}

// ジャンル→指標一覧の対応表(2段階ドロップダウン用) - ジャンルを選ぶと
// その中の指標だけに絞り込まれる(ユーザー要望:「プルダウンではまず
// ジャンルを決定して、そのあとに右側に使用する指標が出てくるようにして」)。
function buildGenreItemsMap(indicators: IndicatorInfo[]): Map<ConditionGenreKey, IndicatorInfo[]> {
  const groups = groupIndicatorsByGenre(indicators)
  const byLabel = new Map(groups.map((g) => [g.label, g.items]))
  const map = new Map<ConditionGenreKey, IndicatorInfo[]>()
  for (const g of CONDITION_GENRE_ORDER) {
    const items = byLabel.get(g.label)
    if (items && items.length > 0) map.set(g.key, items)
  }
  return map
}

// メイン指標を切り替える時の副作用(固定値比較不可への切り替え/EMA等の
// 価格水準系指標への切り替え時の比較先の立て直し)をジャンル選択・指標選択の
// 両方から共通で使えるようにまとめたもの。
function applyMainIndicatorChange(
  node: ConditionNode,
  indicators: IndicatorInfo[],
  indicatorId: string
): ConditionNode {
  const nextInfo = indicatorInfo(indicators, indicatorId)
  const next: ConditionNode = {
    ...node,
    indicator: indicatorId,
    params: defaultParamsFor(nextInfo),
  }
  const compareMode = typeof node.value === 'string' ? 'indicator' : 'literal'
  if (!(nextInfo?.allow_literal ?? true) && compareMode === 'literal') {
    const first = defaultCompareIndicator(indicators, indicatorId, nextInfo?.kind)
    next.value = first?.id ?? 'close'
    next.value_params = defaultParamsFor(first)
  } else if (nextInfo?.kind === 'price_level') {
    const first = defaultCompareIndicator(indicators, indicatorId, nextInfo?.kind)
    next.value = first?.id ?? 'close'
    next.value_params = defaultParamsFor(first)
  }
  return next
}

export function defaultParamsFor(info: IndicatorInfo | undefined): ConditionParams {
  if (!info) return {}
  const params: ConditionParams = {}
  for (const spec of info.params) {
    params[spec.name] = spec.default
  }
  return params
}

// 比較先に「メイン指標と全く同じ指標」を選んだ時(EMA(50) vs EMA(200)の
// ゴールデンクロスのように、同じ種類の指標を異なる期間で比較すること自体は
// 有効な使い方なので指標の選択肢からは除外していない)、パラメータまで
// デフォルト値のまま一致してしまうと「RSI(14) > RSI(14)」のような常に
// 同じ値同士の意味のない比較になってしまう(ユーザー報告:「比較元でRSI
// 選んだ時比較先でもRSI選べるのっておかしくない?」)。選んだ指標がメイン
// 指標と同じ場合だけ、デフォルト値がメイン側と重なるパラメータを自動で
// ずらす(choiceは次の選択肢へ、それ以外は2倍にする)。
function differentiatedValueParams(
  nextInfo: IndicatorInfo | undefined,
  mainIndicator: string,
  mainParams: ConditionParams,
  selectedIndicator: string
): ConditionParams {
  const base = defaultParamsFor(nextInfo)
  if (!nextInfo || selectedIndicator !== mainIndicator) return base
  const result: ConditionParams = { ...base }
  for (const spec of nextInfo.params) {
    if (result[spec.name] !== mainParams[spec.name]) continue
    if (spec.type === 'choice' && spec.choices && spec.choices.length > 1) {
      const idx = spec.choices.indexOf(result[spec.name] as number)
      result[spec.name] = spec.choices[(idx + 1) % spec.choices.length]
    } else if (spec.type === 'string_choice' && spec.string_choices && spec.string_choices.length > 1) {
      const idx = spec.string_choices.findIndex((c) => c.value === result[spec.name])
      result[spec.name] = spec.string_choices[(idx + 1) % spec.string_choices.length].value
    } else {
      result[spec.name] = (result[spec.name] as number) * 2
    }
  }
  return result
}

function paramsEqual(a: ConditionParams, b: ConditionParams): boolean {
  const aKeys = Object.keys(a)
  const bKeys = Object.keys(b)
  if (aKeys.length !== bKeys.length) return false
  return aKeys.every((key) => a[key] === b[key])
}

// パラメータの数値入力欄を直接書き換えて、比較元と比較先を(指標もパラメータも)
// 完全に一致させることもできてしまう(ユーザー報告:「比較元RSI14の時
// 比較先でもRSI14選べる。選択できないようにできない?」- ドロップダウン
// 選択時の自動ずらしだけでは、その後の手入力までは防げなかったため)。
// フィールドからフォーカスが外れた(確定した)時だけ判定してずらす -
// 値が変わるたびに即座に判定すると、矢印キーで28→14→13と連続で下げて
// いく途中で14を通過した瞬間に28へ引き戻されてしまい、13まで到達できない
// 不具合が起きたため(ユーザー報告:「RSI28から矢印で13以下にしたいとき
// 14になった時点で28に戻ってしまい13にできない。14に決定したときだけ
// 28に戻るようにしたい」)。
function nudgeFirstParam(info: IndicatorInfo, params: ConditionParams): ConditionParams {
  const spec = info.params[0]
  if (!spec) return params
  const current = params[spec.name] ?? spec.default
  if (spec.type === 'choice' && spec.choices && spec.choices.length > 1) {
    const idx = spec.choices.indexOf(current as number)
    return { ...params, [spec.name]: spec.choices[(idx + 1) % spec.choices.length] }
  }
  if (spec.type === 'string_choice' && spec.string_choices && spec.string_choices.length > 1) {
    const idx = spec.string_choices.findIndex((c) => c.value === current)
    return { ...params, [spec.name]: spec.string_choices[(idx + 1) % spec.string_choices.length].value }
  }
  const currentNum = current as number
  return { ...params, [spec.name]: currentNum * 2 || currentNum + 1 }
}

// One input per declared param (int/float -> number input, choice -> select
// of the conventional values only, e.g. Fibonacci's ratio) - previously
// this only ever rendered a single hardcoded "length" field, so indicators
// with more than one real parameter (bollinger's num_std, macd's
// fast/slow/signal, stochastic's 3 periods, ichimoku's 3 periods, fib's
// ratio) silently kept their Python-side default for every param past the
// first.
export function ParamInputs({
  info,
  params,
  onChange,
  onBlur,
}: {
  info: IndicatorInfo | undefined
  params: ConditionParams
  onChange: (next: ConditionParams) => void
  // 値が変わるたびにではなく、フィールドから離れて確定した時だけ呼びたい
  // 補正処理(比較元/比較先の自己比較チェックなど)向けのフック - 省略可。
  onBlur?: () => void
}) {
  if (!info || info.params.length === 0) return null

  return (
    <>
      {info.params.map((spec: IndicatorParamSpec) =>
        spec.type === 'choice' ? (
          <select
            key={spec.name}
            title={spec.label}
            className="glass-input w-20 rounded-lg px-2 py-1 text-xs"
            value={params[spec.name] ?? spec.default}
            onChange={(e) => onChange({ ...params, [spec.name]: Number(e.target.value) })}
            onBlur={onBlur}
          >
            {(spec.choices ?? []).map((choice) => (
              <option key={choice} value={choice}>
                {spec.label}:{choice}
              </option>
            ))}
          </select>
        ) : spec.type === 'string_choice' ? (
          <select
            key={spec.name}
            title={spec.label}
            className="glass-input w-24 rounded-lg px-2 py-1 text-xs"
            value={params[spec.name] ?? spec.default}
            onChange={(e) => onChange({ ...params, [spec.name]: e.target.value })}
            onBlur={onBlur}
          >
            {(spec.string_choices ?? []).map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        ) : (
          <input
            key={spec.name}
            type="number"
            step={spec.type === 'float' ? '0.1' : '1'}
            title={spec.label}
            placeholder={spec.label}
            className="w-16 glass-input rounded-lg px-2 py-1"
            value={params[spec.name] ?? spec.default}
            onChange={(e) => onChange({ ...params, [spec.name]: Number(e.target.value) })}
            onBlur={onBlur}
          />
        )
      )}
    </>
  )
}

export default function ConditionRow({ node, indicators, onChange, onRemove }: Props) {
  const compareMode = typeof node.value === 'string' ? 'indicator' : 'literal'
  const info = indicatorInfo(indicators, node.indicator)
  const valueIndicatorInfo = typeof node.value === 'string' ? indicatorInfo(indicators, node.value) : undefined
  // 指標ドロップダウンを「ジャンル選択→指標選択」の2段階にする(ユーザー
  // 要望:「プルダウンではまずジャンルを決定して、そのあとに右側に使用
  // する指標が出てくるようにして」- 単一ドロップダウン内のoptgroupだと
  // ジャンルを跨いだ全指標が一覧のまま出てしまい分かりにくかったため)。
  const genreItemsMap = buildGenreItemsMap(indicators)
  const mainGenreKey: ConditionGenreKey = info ? conditionGenreOf(info) : CONDITION_GENRE_ORDER[0].key
  const mainGenreItems = genreItemsMap.get(mainGenreKey) ?? []
  // EMA/高値/安値などの価格系指標、ATRなどのボラティリティ系指標は固定値
  // との比較に意味がないため、「固定値」の選択肢自体を出さない(ユーザー
  // 要望:「EMAなどの固定値とは比較不可能なものを選択したときも固定値を
  // 設定するボックスが出るが、これが出現しないようにしてほしい」)。
  // infoが見つからない間(データ未読込)は制限しない。
  const literalAllowed = info?.allow_literal ?? true

  // 比較先(指標同士で比較する場合)は、メイン指標とkind(価格水準/
  // オシレーター0-100など)が一致する指標だけに絞り込む(ユーザー報告:
  // 「EMAの比較先でRSIとか選べるのおかしいよね」- 単位もスケールも違う
  // 指標同士を比較しても意味がないため)。kindが取れない間(データ未読込)
  // は絞り込まない。
  const compatibleValueIndicators = info?.kind ? indicators.filter((i) => i.kind === info.kind) : indicators
  const valueGenreGroups = groupIndicatorsByGenre(compatibleValueIndicators)

  // 保存済みのストラテジーを読み込んだ場合など、既に固定値比較になっている
  // 状態で開いた時も同様に指標比較へ補正する(選択操作をした時だけでなく)。
  // また、比較先のkindがメイン指標のkindとズレている場合(EMA vs RSIなど、
  // 保存済みストラテジーや過去の状態から持ち越された不整合)も同様に
  // kindが一致する指標へ補正する。
  useEffect(() => {
    if (!literalAllowed && compareMode === 'literal') {
      const first = defaultCompareIndicator(indicators, node.indicator, info?.kind)
      onChange({ ...node, value: first?.id ?? 'close', value_params: defaultParamsFor(first) })
      return
    }
    if (compareMode === 'indicator' && info && valueIndicatorInfo && valueIndicatorInfo.kind !== info.kind) {
      const first = defaultCompareIndicator(indicators, node.indicator, info.kind)
      if (first && first.id !== node.value) {
        onChange({ ...node, value: first.id, value_params: defaultParamsFor(first) })
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [literalAllowed, compareMode, node.indicator, info?.kind, valueIndicatorInfo?.kind])

  // 比較元と比較先が指標もパラメータも完全に一致した状態で確定した時だけ
  // (=フィールドから離れた時、ParamInputsのonBlur経由)どちらかを自動で
  // ずらす(ユーザー報告:「比較元RSI14の時比較先でもRSI14選べる。選択
  // できないようにできない?」)。値が変わるたびに毎回判定すると、矢印キー
  // で28→14→13と連続で下げていく途中で14を通過した瞬間に28へ引き戻され、
  // 13まで到達できなくなる不具合が起きたため、確定時(blur)だけ判定する。
  const nudgeIfSelfCompared = () => {
    if (compareMode === 'indicator' && node.value === node.indicator && paramsEqual(node.params, node.value_params) && info) {
      onChange({ ...node, value_params: nudgeFirstParam(info, node.value_params) })
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] p-2 text-sm">
      {/* 比較元(メイン指標: EMAなど) - 比較元/向き/比較先の3つの役割を枠と
          バッジで見分けられるようにする(ユーザー要望:「1つのエントリー
          条件の比較元と比較先と向きのボックスの色を分けて」→その後
          「それぞれの枠はある状態で色を統一して。このUIに合う色にして」
          - 3色に分けていたのを、アプリ全体の基調色(青系: 「+条件を追加」
          ボタンやバックテスト実行ボタンと同じblue系)に統一した)。 */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border-2 border-blue-400/50 bg-blue-500/20 px-2 py-1">
        <span className="rounded px-1.5 py-0.5 text-[10px] font-bold text-blue-200 bg-blue-500/40">比較元</span>
        <select
          className="glass-input rounded-lg px-2 py-1"
          value={mainGenreKey}
          onChange={(e) => {
            const key = e.target.value as ConditionGenreKey
            const items = genreItemsMap.get(key) ?? []
            const first = items[0]
            if (!first) return
            onChange(applyMainIndicatorChange(node, indicators, first.id))
          }}
        >
          {CONDITION_GENRE_ORDER.filter((g) => (genreItemsMap.get(g.key)?.length ?? 0) > 0).map((g) => (
            <option key={g.key} value={g.key}>
              {g.label}
            </option>
          ))}
        </select>

        <select
          className="glass-input rounded-lg px-2 py-1"
          value={node.indicator}
          onChange={(e) => onChange(applyMainIndicatorChange(node, indicators, e.target.value))}
        >
          {mainGenreItems.map((ind) => (
            <option key={ind.id} value={ind.id}>
              {ind.label}
            </option>
          ))}
        </select>

        <ParamInputs
          info={info}
          params={node.params}
          onChange={(next) => onChange({ ...node, params: next })}
          onBlur={nudgeIfSelfCompared}
        />

        <select
          className="glass-input rounded-lg px-1 py-1 text-xs"
          title="この指標を計算する時間足(未指定ならバックテスト自体の時間足)"
          value={node.timeframe ?? ''}
          onChange={(e) => onChange({ ...node, timeframe: e.target.value || undefined })}
        >
          <option value="">(自足)</option>
          {TIMEFRAME_OPTIONS.map((tf) => (
            <option key={tf} value={tf}>
              {tf}
            </option>
          ))}
        </select>
      </div>

      {/* 方向(演算子: ＜/＞/一致など) - 画面上の並び「比較元 方向 比較先」
          通りに、選んだ演算子をそのまま(反転なしで)「比較元 演算子 比較先」
          として評価する(ユーザー要望:「画面上で順番が「比較元 向き 比較先」
          になっているから、実際の動作でも「比較元＜比較先」だったらこの
          通りに動作するようにして」)。以前あった「EMAなど価格水準系の指標を
          終値と比較する時は演算子を価格目線で反転させる」処理は撤去した。 */}
      <div className="flex items-center rounded-lg border-2 border-blue-400/50 bg-blue-500/20 px-2 py-1">
        <span className="mr-2 rounded px-1.5 py-0.5 text-[10px] font-bold text-blue-200 bg-blue-500/40">方向</span>
        <select
          className="glass-input rounded-lg px-2 py-1"
          value={node.operator}
          onChange={(e) => onChange({ ...node, operator: e.target.value as Operator })}
        >
          {OPERATORS.map((op) => (
            <option key={op.id} value={op.id}>
              {op.label}
            </option>
          ))}
        </select>
      </div>

      {/* 比較先(固定値、または別の指標) */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border-2 border-blue-400/50 bg-blue-500/20 px-2 py-1">
        <span className="rounded px-1.5 py-0.5 text-[10px] font-bold text-blue-200 bg-blue-500/40">比較先</span>
        <select
          className="glass-input rounded-lg px-2 py-1"
          value={compareMode}
          onChange={(e) => {
            if (e.target.value === 'literal') {
              onChange({ ...node, value: 0, value_params: {} })
            } else {
              const first = defaultCompareIndicator(indicators, node.indicator, info?.kind)
              onChange({
                ...node,
                value: first?.id ?? 'close',
                value_params: defaultParamsFor(first),
              })
            }
          }}
        >
          {literalAllowed && <option value="literal">固定値</option>}
          <option value="indicator">指標</option>
        </select>

        {compareMode === 'literal' ? (
          <input
            type="number"
            className="w-20 glass-input rounded-lg px-2 py-1"
            value={node.value as number}
            onChange={(e) => onChange({ ...node, value: Number(e.target.value) })}
          />
        ) : (
          <>
            <select
              className="glass-input rounded-lg px-2 py-1"
              value={node.value as string}
              onChange={(e) => {
                const nextInfo = indicatorInfo(indicators, e.target.value)
                onChange({
                  ...node,
                  value: e.target.value,
                  value_params: differentiatedValueParams(nextInfo, node.indicator, node.params, e.target.value),
                })
              }}
            >
              {valueGenreGroups.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.items.map((ind) => (
                    <option key={ind.id} value={ind.id}>
                      {ind.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <ParamInputs
              info={valueIndicatorInfo}
              params={node.value_params}
              onChange={(next) => onChange({ ...node, value_params: next })}
              onBlur={nudgeIfSelfCompared}
            />
            <select
              className="glass-input rounded-lg px-1 py-1 text-xs"
              title="この指標を計算する時間足(未指定ならバックテスト自体の時間足)"
              value={node.value_timeframe ?? ''}
              onChange={(e) => onChange({ ...node, value_timeframe: e.target.value || undefined })}
            >
              <option value="">(自足)</option>
              {TIMEFRAME_OPTIONS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </>
        )}
      </div>

      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="ml-auto rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-red-300 hover:bg-red-500/20"
        >
          削除
        </button>
      )}
    </div>
  )
}
