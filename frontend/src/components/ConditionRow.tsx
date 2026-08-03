import { useEffect, type ReactNode } from 'react'
import IndicatorPicker from './IndicatorPicker'
import type { ConditionNode, ConditionParams, IndicatorInfo, IndicatorParamSpec, Operator } from '../types'

// +/-○○Pipsのオフセット入力を出す指標kind(ユーザー要望:「EMA+○○Pipsや
// 終値-○○Pipsを選択できるようにしてほしい。EMAや終値以外でもできるだけ
// すべての指標でできるようにしてほしい。RSIなどできないもの以外すべてに
// 採用して」)。価格の生単位で測られる指標だけに意味を持つ
// (price_level: EMA/終値/ピボット等、volatility: ATR/各種距離等、
// signed_price_diff: MACDライン等) - RSI(oscillator_0_100)やCCI
// (unitless_ratio)等、単位が価格でない指標には出さない。
const PIP_OFFSET_KINDS = new Set(['price_level', 'volatility', 'signed_price_diff'])

type LiteralMode = 'value' | 'pips' | 'price_pct' | 'atr_pct'

// 固定値欄に入れる数字がPipsなのか生の価格なのか、単位を明示するラベル
// (ユーザー要望:「固定値にPipsを入れればいいのか価格を入れればいいのか
// わかるようにして」- 終値等のprice_level系を解除した結果、「価格データ」
// ジャンル内で単位がバラバラ(価格データそのもの/実体・ヒゲ等の価格差/
// キリ番までの距離だけPips)になり紛らわしくなったため)。dist_to_round_
// numberだけ特別扱いなのは、engine/technical_indicators.py::
// round_number_distance_pipsが結果をpip_sizeで割ってPips単位に変換して
// いる、唯一の例外だから。literalModeが"value"以外の時は、その場で選んだ
// 「Pips」「価格の%」「ATRの%」がそのままラベルになる(ユーザー要望:
// 「固定値でオフセットと同じように価格の％とATRの％を選べるようにして
// ほしい」→続けて「固定値の種類のプルダウンに価格とPips追加して。価格
// そのものが価格。価格差はPipsにして」)。
function literalUnitLabel(info: IndicatorInfo | undefined, literalMode: LiteralMode | undefined): string {
  if (literalMode === 'pips') return '固定値(Pips)'
  if (literalMode === 'price_pct') return '固定値(価格の%)'
  if (literalMode === 'atr_pct') return '固定値(ATRの%)'
  if (!info) return '固定値'
  if (info.id === 'dist_to_round_number') return '固定値(Pips)'
  if (info.kind === 'price_level') return '固定値(価格そのもの)'
  if (info.kind === 'volatility' || info.kind === 'signed_price_diff') return '固定値(価格差、Pipsではない)'
  return '固定値'
}

// 「価格差」系(volatility/signed_price_diff kind)はPipsで入力する方が
// 自然、「価格そのもの」系(price_level kind)は生の価格のまま、という
// kindごとのデフォルトmode(ユーザー要望:「価格そのものが価格。価格差は
// Pipsにして」)。price_pct/atr_ptcは両方のkindで引き続き選べるので、既に
// それらが選ばれていればそのまま維持し(kindが変わったからといって選び
// 直させない)、"value"/"pips"のどちらを既定にするかの枠だけkindに応じて
// 差し替える。バックエンドのデフォルトはliteral_mode未指定=常に"value"
// (engine/conditions.py::Condition.from_dict)なので、"pips"を意図する時は
// 必ず明示的にセットする - 見た目だけ"pips"に見えて実体は"value"のまま、
// という表示と実体のズレ(以前atr_deviationの比較先で踏んだのと同種の
// バグ)を避けるため。
function normalizedLiteralMode(mode: LiteralMode | undefined, kind: string | null | undefined): LiteralMode | undefined {
  if (mode === 'price_pct' || mode === 'atr_pct') return mode
  return kind === 'volatility' || kind === 'signed_price_diff' ? 'pips' : undefined
}

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

// 期間・オフセット等の小さな入力欄が何を表しているか、今までtitle属性の
// ホバーツールチップ(数値入力の場合はplaceholderも)だけで示していたが、
// placeholderは値を入力すると消えてしまい、何の欄か分からなくなっていた
// (ユーザー報告:「エントリー条件のそれぞれのボックスにカーソル当てたら
// 期間とかオフセットとか出るよね。それボックスの上に記載して」)。ボックス
// の上に常時ラベルを出すことで、ホバーしなくても常に分かるようにする。
function LabeledField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-0.5">
      <span className="px-0.5 text-[9px] leading-none text-gray-400">{label}</span>
      {children}
    </div>
  )
}

type OffsetMode = 'pips' | 'price_pct' | 'atr_pct'

const OFFSET_MODE_OPTIONS: { id: OffsetMode; label: string }[] = [
  { id: 'pips', label: 'Pips' },
  { id: 'price_pct', label: '価格の%' },
  { id: 'atr_pct', label: 'ATRの%' },
]

// オフセット入力(固定Pips/価格の%/ATRの%)。3種のうちどれかを選び、量を
// 入力する(ユーザー要望:「オフセットで固定値○○Pipsだけじゃなく価格の
// +○%、ATR(○)の-○%もできるようにして」)。「価格の%」は常に現在の終値
// 基準(比較対象自身の値ではない - ユーザー確認済み)。「ATRの%」の時だけ
// ATR期間の入力も追加で出す。
function OffsetField({
  amount,
  mode,
  atrLength,
  onAmountChange,
  onModeChange,
  onAtrLengthChange,
}: {
  amount: number | undefined
  mode: OffsetMode | undefined
  atrLength: number | undefined
  onAmountChange: (v: number | undefined) => void
  onModeChange: (v: OffsetMode) => void
  onAtrLengthChange: (v: number | undefined) => void
}) {
  const effectiveMode = mode ?? 'pips'
  return (
    <>
      <LabeledField label="オフセット種別">
        <select
          className="glass-input rounded-lg px-1 py-1 text-xs"
          value={effectiveMode}
          onChange={(e) => onModeChange(e.target.value as OffsetMode)}
        >
          {OFFSET_MODE_OPTIONS.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </LabeledField>
      <LabeledField label={effectiveMode === 'pips' ? 'オフセット(Pips)' : 'オフセット(%)'}>
        <input
          type="number"
          step="0.1"
          title={
            effectiveMode === 'pips'
              ? 'この指標にPips単位のオフセットを加える(例: EMA+20Pips)'
              : effectiveMode === 'price_pct'
                ? 'この指標に現在の終値のX%を加える(例: EMA+終値の2%)'
                : 'この指標にATRのX%を加える(例: EMA+ATR14の50%)'
          }
          // 上のLabeledFieldに既に「オフセット(Pips)」等の単位入りラベルが
          // 出ているので、枠内には短い"±"だけにする(以前は"±Pips"が長すぎて
          // number入力のネイティブ上下スピナーと重なっていた - ユーザー報告:
          // 「オフセットの±Pipsのsとプルダウンのマークがかぶってっる」)。
          placeholder="±"
          className="w-16 glass-input rounded-lg px-2 py-1"
          value={amount ?? ''}
          onChange={(e) => onAmountChange(e.target.value === '' ? undefined : Number(e.target.value))}
        />
      </LabeledField>
      {effectiveMode === 'atr_pct' && (
        <LabeledField label="ATR期間">
          <input
            type="number"
            step="1"
            className="w-14 glass-input rounded-lg px-2 py-1"
            value={atrLength ?? 14}
            onChange={(e) => onAtrLengthChange(e.target.value === '' ? undefined : Number(e.target.value))}
          />
        </LabeledField>
      )}
    </>
  )
}

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
// pairGroupを渡した場合はそのpair_groupが一致する指標だけを候補にする
// (ユーザー報告:「EMAの比較先でRSIとか選べるのおかしい」- 単位もスケールも
// 違う指標同士を比較しても意味がないため)。kindではなくpair_groupで絞る
// のは、同じkindでも測定単位が違う指標(RSIの移動平均からの乖離=RSI
// ポイント、キリ番までの距離=Pipsのように、kind="unitless_ratio"だが単位が
// 全く別)を比較先候補から除くため(ユーザー報告:「比較元RSIの移動平均
// からの乖離。比較先キリ番までの距離っておかしくない?」)。
// pair_groupの候補が0件(存在しない/未知のpair_group名)の時だけ全指標に
// フォールバックする - rsi_deviation/bb_width_percent/dist_to_round_number/
// candle_body/atr_deviationのように「自分自身としか比較できない」設計で
// 意図的にpair_groupを指標名自身にしているものは、候補が自分1件しかない
// のが正しい状態であり、それを「候補が足りない」とみなして全指標へ
// フォールバックしてしまうと、比較先の選択肢一覧(compatibleValueIndicators
// - 自分1件だけ)と実際にセットされる値(フォールバック先の別指標)が
// ズレてしまう(ユーザー報告:「ATRの移動平均からの乖離の比較先でATRの
// 移動平均からの乖離選んだらATR期間選択できない」- 見た目は選べているのに
// 実体は別の指標のままでパラメータ欄が対応していなかった)。
function defaultCompareIndicator(
  indicators: IndicatorInfo[],
  excludeId: string,
  pairGroup?: string | null
): IndicatorInfo | undefined {
  // 候補自身がallow_indicator_pair=falseの指標(MFI/チョピネス指数等)は、
  // 比較元にした時は「指標」モード自体を選べないのに、他の指標の比較先
  // 候補には出てしまうという非対称があった(ユーザー報告:「これ比較元に
  // 出てくるものと比較先に出てくるものは一致してる?」)。候補側もこの
  // フラグで絞り込む。
  const pairable = indicators.filter((i) => i.allow_indicator_pair)
  const scoped = pairGroup ? pairable.filter((i) => i.pair_group === pairGroup) : pairable
  const pool = scoped.length > 0 ? scoped : pairable
  const close = pool.find((i) => i.id === 'close')
  if (close && close.id !== excludeId) return close
  return pool.find((i) => i.id !== excludeId) ?? pool[0]
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
    const first = defaultCompareIndicator(indicators, indicatorId, nextInfo?.pair_group)
    next.value = first?.id ?? 'close'
    next.value_params = defaultParamsFor(first)
  } else if (nextInfo?.kind === 'price_level') {
    const first = defaultCompareIndicator(indicators, indicatorId, nextInfo?.pair_group)
    next.value = first?.id ?? 'close'
    next.value_params = defaultParamsFor(first)
  } else if (!(nextInfo?.allow_indicator_pair ?? true) && compareMode === 'indicator') {
    // 切り替え先の指標が「陽線」のような比較先を持たないboolean_signal等
    // だった場合、指標比較モードのままだと無効な状態になってしまうため
    // 固定値比較へ戻す(下のuseEffectの補正と同じ理由)。
    const choices = nextInfo?.literal_choices
    next.value = choices && choices.length === 1 ? choices[0] : 1
    next.value_params = {}
  }
  // 切り替え先の指標で選べる演算子が絞られていて(例: 陽線は「一致」のみ)、
  // 今の演算子がその中に無ければ絞り込み後の先頭の演算子に補正する
  // (ユーザー報告:「陽線＞固定値 これどういう意味?」- 「より上」等の
  // 演算子がboolean_signal系の指標では選べないようにした際の補正)。
  const allowedOps = nextInfo?.allowed_operators
  if (allowedOps && !allowedOps.includes(next.operator)) {
    next.operator = allowedOps[0]
  }
  // 方向/比較先ボックスごと隠す指標(陽線等、比較できる値が1択しかない)へ
  // 切り替えた時は、値もその1択に必ず揃える(ユーザー報告:「陽線の時
  // 比較先出す必要あるの?」)。
  const nextChoices = nextInfo?.literal_choices
  if (nextChoices && nextChoices.length === 1 && typeof next.value !== 'string') {
    next.value = nextChoices[0]
  }
  // 切り替え先の指標がPips単位のオフセットに対応しないkind(RSI等)なら、
  // 表示されなくなったoffset_pipsが値だけ残って裏で効き続けることのない
  // よう消しておく(ユーザー要望:「EMA+○○Pips...RSIなどできないもの
  // 以外すべてに採用して」の裏返し - 対応しない指標では無効化する)。
  if (!(nextInfo?.kind && PIP_OFFSET_KINDS.has(nextInfo.kind))) {
    next.offset_pips = undefined
    next.offset_mode = undefined
    next.offset_atr_length = undefined
    // 固定値の「Pips/価格の%/ATRの%」も同じ理由(対応しない指標では無効化)
    // で消す - こちらはメイン指標が固定値と比較される側なので、offset_pips
    // と同じnextInfoの判定を流用する。
    next.literal_mode = undefined
    next.literal_atr_length = undefined
  } else {
    // kindが変わった(price_level⇔volatility/signed_price_diff)場合に
    // "value"⇔"pips"の既定を切り替える(normalizedLiteralModeのdocstring
    // 参照) - price_pct/atr_pctは維持される。
    next.literal_mode = normalizedLiteralMode(next.literal_mode, nextInfo.kind)
  }
  const nextValueInfo = typeof next.value === 'string' ? indicatorInfo(indicators, next.value) : undefined
  if (!(nextValueInfo?.kind && PIP_OFFSET_KINDS.has(nextValueInfo.kind))) {
    next.value_offset_pips = undefined
    next.value_offset_mode = undefined
    next.value_offset_atr_length = undefined
  }
  return next
}

export function defaultParamsFor(info: IndicatorInfo | undefined): ConditionParams {
  if (!info) return {}
  const params: ConditionParams = {}
  for (const spec of info.params) {
    if (spec.type === 'range') {
      if (spec.name_min) params[spec.name_min] = spec.default_min
      if (spec.name_max) params[spec.name_max] = spec.default_max
    } else if (spec.name) {
      params[spec.name] = spec.default
    }
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
    // type="range"は下限〜上限の倍率ペアで、同一指標同士の比較でも「値が
    // かぶって無意味な条件になる」という問題がそもそも起きない(比較先
    // として指標同士を比べる対象ではなく、単独の数値パラメータのため)ので
    // 対象外。
    if (spec.type === 'range' || !spec.name) continue
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
  if (!spec || spec.type === 'range' || !spec.name) return params
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

// 数値入力欄にカーソルを合わせた時に出す説明文 - ラベルに加えて「設定
// できる範囲」(range、engine/indicator_pool.py::IndicatorSpec.param_ranges
// 由来)と「目安の値」(presets、同value_presets由来)の両方を出す
// (ユーザー要望:「変更できるパラメーターについても...カーソルを当てたら
// 設定できる範囲と目安の値が表示されるようにして。比較元にも比較先にも
// その機能を付けて」)。ParamInputsは比較元(node.params)・比較先
// (node.value_params)の両方から同じ呼び出し方で使われているので、ここを
// 直せば両方に自動で反映される。
function paramTooltip(spec: IndicatorParamSpec): string {
  const parts = [spec.label]
  if (spec.range) parts.push(`範囲: ${spec.range[0]}〜${spec.range[1]}`)
  if (spec.presets && spec.presets.length > 0) parts.push(`目安: ${spec.presets.join(', ')}`)
  return parts.join(' / ')
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

  // show_ifを持つパラメータ(EMA5等)は、制御元パラメータ(EMA本数等)の
  // 現在値がmin未満なら表示自体をスキップする - 選んでいない分の入力欄が
  // 常時出ていると「4本のはずなのに5本ぶん欄がある」ように見えて紛らわしい
  // ため(ユーザー要望:「パーフェクトオーダーは現在4本だけど3〜5本まで
  // 選択できるようにして」への対応)。制御元パラメータがまだparamsに
  // 無い(未変更でデフォルトのまま)場合は、そのパラメータ自身のデフォルト
  // 値で判定する。
  const visibleParams = info.params.filter((spec) => {
    if (!spec.show_if) return true
    const controllerSpec = info.params.find((s) => s.name === spec.show_if!.param)
    const controllerValue = Number(params[spec.show_if.param] ?? controllerSpec?.default ?? 0)
    return controllerValue >= spec.show_if.min
  })

  return (
    <>
      {visibleParams.map((spec: IndicatorParamSpec) => (
        <LabeledField key={spec.name ?? `${spec.name_min}_${spec.name_max}`} label={spec.label}>
          {spec.type === 'range' ? (
            // 下限〜上限のペア(例: 探索窓の倍率)を1つのラベルの下に
            // "[下限] 〜 [上限]" の2欄で表示する(ユーザー要望:「下限倍率と
            // 上限倍率合わせて記載する」)。name_min/name_maxは別々の
            // パラメータ名としてparamsに保存する(裏の値としては従来通り
            // 2つのまま、見た目だけまとめる)。
            <span className="flex items-center gap-1">
              <input
                type="number"
                step={spec.value_type === 'float' ? '0.1' : '1'}
                title={`${spec.label}(下限)`}
                className="w-16 glass-input rounded-lg px-2 py-1"
                value={params[spec.name_min!] ?? spec.default_min}
                onChange={(e) => onChange({ ...params, [spec.name_min!]: Number(e.target.value) })}
                onBlur={onBlur}
              />
              <span className="text-gray-400">〜</span>
              <input
                type="number"
                step={spec.value_type === 'float' ? '0.1' : '1'}
                title={`${spec.label}(上限)`}
                className="w-16 glass-input rounded-lg px-2 py-1"
                value={params[spec.name_max!] ?? spec.default_max}
                onChange={(e) => onChange({ ...params, [spec.name_max!]: Number(e.target.value) })}
                onBlur={onBlur}
              />
            </span>
          ) : spec.type === 'choice' ? (
            <select
              title={spec.label}
              className="glass-input w-20 rounded-lg px-2 py-1 text-xs"
              value={params[spec.name!] ?? spec.default}
              onChange={(e) => onChange({ ...params, [spec.name!]: Number(e.target.value) })}
              onBlur={onBlur}
            >
              {/* ラベルは上のLabeledFieldに既に出ているので、選択肢には値だけ
                  表示する(以前は"{spec.label}:{choice}"と重複表示していて、
                  "EMA本数:3"のような長い文字列がw-20の枠に収まらずネイティブ
                  の▼マークと重なっていた - ユーザー報告:「EMA本数の文字と
                  プルダウンのマークがかぶってる」)。 */}
              {(spec.choices ?? []).map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </select>
          ) : spec.type === 'string_choice' ? (
            <select
              title={spec.label}
              // 選択中の文字列が長いと、ネイティブのプルダウン矢印と重なって
              // 見えていた(ユーザー報告:「状態のボックス内の文字とプル
              // ダウンの矢印がかぶってる」)。ボックス幅(w-24)は変えず、矢印
              // 分の余白をpr-5で確保し、収まらない文字はtruncateで省略する
              // (ユーザー了承:「文字は今と同じで途中で切れてていい」)。
              className="glass-input w-24 truncate rounded-lg py-1 pl-2 pr-5 text-xs"
              value={params[spec.name!] ?? spec.default}
              onChange={(e) => onChange({ ...params, [spec.name!]: e.target.value })}
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
              type="number"
              step={spec.type === 'float' ? '0.1' : '1'}
              title={paramTooltip(spec)}
              placeholder={spec.label}
              className="w-16 glass-input rounded-lg px-2 py-1"
              value={params[spec.name!] ?? spec.default}
              onChange={(e) => onChange({ ...params, [spec.name!]: Number(e.target.value) })}
              onBlur={onBlur}
            />
          )}
        </LabeledField>
      ))}
    </>
  )
}

export default function ConditionRow({ node, indicators, onChange, onRemove }: Props) {
  const compareMode = typeof node.value === 'string' ? 'indicator' : 'literal'
  const info = indicatorInfo(indicators, node.indicator)
  const valueIndicatorInfo = typeof node.value === 'string' ? indicatorInfo(indicators, node.value) : undefined
  // EMA/高値/安値などの価格系指標、ATRなどのボラティリティ系指標は固定値
  // との比較に意味がないため、「固定値」の選択肢自体を出さない(ユーザー
  // 要望:「EMAなどの固定値とは比較不可能なものを選択したときも固定値を
  // 設定するボックスが出るが、これが出現しないようにしてほしい」)。
  // infoが見つからない間(データ未読込)は制限しない。
  const literalAllowed = info?.allow_literal ?? true
  // 「陽線」のようなboolean_signal・trend_binary系の指標は、常に固定値
  // (1.0等)とだけ比較する設計で他の指標と比較する意味がないため、falseの
  // 時は「比較先」で「指標」モード自体を選べないようにする(ユーザー報告:
  // 「比較元が「陽線」のときも比較先で指標を選べるのはおかしい。比較先の
  // ボックスを消して」)。
  const indicatorPairAllowed = info?.allow_indicator_pair ?? true
  // 「陽線」のようなboolean_signal・trend_binary系の指標は1.0/0.0や1/-1しか
  // 値を取らず、「一致(==)」以外の演算子(より上/より下/上抜けなど)を選んでも
  // 意味を持たない(ユーザー報告:「陽線＞固定値 これどういう意味?」)。
  // nullの間(データ未読込 or 制限なし)は全演算子を出す。
  const allowedOperators = info?.allowed_operators ?? null
  const visibleOperators = allowedOperators ? OPERATORS.filter((op) => allowedOperators.includes(op.id)) : OPERATORS
  // 演算子も比較先の値も選択肢が1つしかない指標(陽線等のboolean_signal -
  // 常に「一致(==) 1.0」の1通りしかあり得ない)は、方向/比較先のボックス
  // ごと表示する意味が無い(ユーザー報告:「陽線の時比較先出す必要あるの?」)。
  // SuperTrend方向等のtrend_binaryはliteral_choicesが複数あるため対象外
  // (「一致」以外は選べないが、1/-1のどちらと比較するかはまだ選ぶ必要が
  // ある)。
  // 「演算子が==しかない(=allowedOperatorsが==のみに絞られている)」ことも
  // 必須条件にする - MACDライン等のsigned_price_diff系はliteral_choicesが
  // [0.0]の1つだけだが、演算子自体は>/</上抜け/下抜けを含め全部使える
  // (engine/indicator_pool.pyのコメント通り、0はMACDのゼロラインクロス等
  // 銘柄をまたいで意味を持つ境界線のため、値は0固定でも演算子は絞らない
  // 設計)。この条件が無いと「EMA傾き＞0」「MACDヒストグラム＞0」のような
  // 一番よく使う比較ができず、常に「一致=0」の一択に潰れてしまっていた
  // (ユーザー報告「EMA傾きの比較先の固定値って何」で発覚した実バグ)。
  const isEqualityOnlyKind = allowedOperators !== null && allowedOperators.length === 1 && allowedOperators[0] === '=='
  const fixedLiteralValue =
    isEqualityOnlyKind && info?.literal_choices && info.literal_choices.length === 1 ? info.literal_choices[0] : null
  // MACDライン等のsigned_price_diff系(演算子は自由に選べるが固定値は0しか
  // 意味を持たない - 上のfixedLiteralValueの説明参照)は、方向ボックスは
  // 出しつつ固定値の数値入力だけ編集不可にする(ユーザー報告:「値差の固定値
  // にはどのような値を入れればいいの?」→「それなら数字変えられないように
  // してほしい」- 0以外を入れても銘柄ごとに意味が変わってしまい実質無意味な
  // ため、誤って別の値を打ち込めないようにする)。
  const lockedLiteralValue =
    info?.literal_choices && info.literal_choices.length === 1 ? info.literal_choices[0] : null

  // 比較先(指標同士で比較する場合)は、メイン指標とkind(価格水準/
  // オシレーター0-100など)が一致し、かつ候補自身もallow_indicator_pair
  // (他の指標と比較される側になれるか)がtrueの指標だけに絞り込む
  // (ユーザー報告:「EMAの比較先でRSIとか選べるのおかしいよね」に加えて
  // 「これ比較元に出てくるものと比較先に出てくるものは一致してる?」-
  // MFI/チョピネス指数のように比較元では「指標」モード自体を選べない
  // ものが、他の指標の比較先候補には出てしまう非対称があったため)。
  // pair_groupが取れない間(データ未読込)は絞り込まない。kindではなく
  // pair_groupで絞るのは、同じkindでも測定単位が違う指標(RSIの移動平均
  // からの乖離=RSIポイント、キリ番までの距離=Pips等)を比較先候補から
  // 除くため(ユーザー報告:「比較元RSIの移動平均からの乖離。比較先キリ番
  // までの距離っておかしくない?」)。
  const compatibleValueIndicators = (
    info?.pair_group ? indicators.filter((i) => i.pair_group === info.pair_group) : indicators
  ).filter((i) => i.allow_indicator_pair)

  // 保存済みのストラテジーを読み込んだ場合など、既に固定値比較になっている
  // 状態で開いた時も同様に指標比較へ補正する(選択操作をした時だけでなく)。
  // また、比較先のkindがメイン指標のkindとズレている場合(EMA vs RSIなど、
  // 保存済みストラテジーや過去の状態から持ち越された不整合)も同様に
  // kindが一致する指標へ補正する。
  useEffect(() => {
    if (!literalAllowed && compareMode === 'literal') {
      const first = defaultCompareIndicator(indicators, node.indicator, info?.pair_group)
      onChange({ ...node, value: first?.id ?? 'close', value_params: defaultParamsFor(first) })
      return
    }
    if (!indicatorPairAllowed && compareMode === 'indicator') {
      // 「陽線」等、比較先を指標にできない main指標が指標比較モードのまま
      // 保存済みストラテジーなどから読み込まれた場合の補正(手動でこの
      // モードへは切り替えられなくなったが、古いデータには残り得るため)。
      onChange({ ...node, value: fixedLiteralValue ?? 1, value_params: {} })
      return
    }
    if (
      compareMode === 'indicator' &&
      info &&
      valueIndicatorInfo &&
      (valueIndicatorInfo.pair_group !== info.pair_group || !valueIndicatorInfo.allow_indicator_pair)
    ) {
      // pair_groupがズレている場合に加え、比較先自身がallow_indicator_pair=
      // false(MFI/チョピネス指数等、比較される側にもなれない指標)のまま
      // 保存済みストラテジー等から読み込まれた場合も補正する(ユーザー報告:
      // 「これ比較元に出てくるものと比較先に出てくるものは一致してる?」)。
      const first = defaultCompareIndicator(indicators, node.indicator, info.pair_group)
      if (first && first.id !== node.value) {
        // differentiatedValueParams(defaultParamsForではなく)を使うのは、
        // atr_deviation等の「自分自身としか比較できない」pair_groupだと
        // first.id === node.indicatorになり得るため - 単純にdefaultParamsFor
        // だと比較元・比較先が同じ指標・同じパラメータのまま(ATR乖離(14,20)
        // > ATR乖離(14,20)のような常に成立しない無意味な条件)になってしまう
        // (手動選択時のonSelectハンドラでは既にdifferentiatedValueParamsで
        // 対応済みだったが、この自動補正経路が漏れていた)。
        onChange({
          ...node,
          value: first.id,
          value_params: differentiatedValueParams(first, node.indicator, node.params, first.id),
        })
      }
      return
    }
    // 保存済みストラテジー等、既に選べない演算子(例: 陽線に「より上」)の
    // まま読み込まれた場合の補正(ユーザー報告:「陽線＞固定値 これどういう
    // 意味?」)。
    if (allowedOperators && !allowedOperators.includes(node.operator)) {
      onChange({ ...node, operator: allowedOperators[0] })
      return
    }
    // 方向/比較先ボックスごと隠す指標(陽線等)で、値が唯一あり得る固定値と
    // ズレている場合の補正(ユーザー報告:「陽線の時比較先出す必要あるの?」
    // - ボックスを隠す以上、隠れた状態の値は必ずこの1択に揃えておく)。
    if (fixedLiteralValue !== null && compareMode === 'literal' && node.value !== fixedLiteralValue) {
      onChange({ ...node, value: fixedLiteralValue })
      return
    }
    // 保存済みストラテジー等、literal_modeが未設定(≒"value")のまま
    // volatility/signed_price_diff kindの指標を固定値比較しているケースを
    // 補正する - 見た目の選択肢では"Pips"が選ばれて見えるのに、実体は
    // literal_mode未指定のままだとバックエンドは"value"(そのままの数値、
    // pip変換なし)として扱ってしまう(以前atr_deviationの比較先で踏んだ
    // 表示と実体のズレと同種のバグ)。
    if (compareMode === 'literal' && info?.kind) {
      const normalized = normalizedLiteralMode(node.literal_mode, info.kind)
      if (normalized !== (node.literal_mode ?? undefined)) {
        onChange({ ...node, literal_mode: normalized })
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    literalAllowed,
    indicatorPairAllowed,
    compareMode,
    node.indicator,
    info?.pair_group,
    valueIndicatorInfo?.pair_group,
    valueIndicatorInfo?.allow_indicator_pair,
    allowedOperators,
    node.operator,
    fixedLiteralValue,
    node.value,
    info?.kind,
    node.literal_mode,
  ])

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
          ボタンやバックテスト実行ボタンと同じblue系)に統一した)。
          items-endにしているのは、IndicatorPickerのパンくず(text-[11px])と
          LabeledFieldのラベル(text-[9px])で上段の高さが違うため、items-
          centerだと各ボックスの下端が揃わなかったため(ユーザー報告:
          「チャートパターン」のボックスと「状態」と「ピボット左本数」の
          ボックスの高さがずれてる。下端でそろえて」)。 */}
      <div className="flex flex-wrap items-end gap-2 rounded-lg border-2 border-blue-400/50 bg-blue-500/20 px-2 py-1">
        <span className="rounded px-1.5 py-0.5 text-[10px] font-bold text-blue-200 bg-blue-500/40">比較元</span>
        {/* ジャンル/サブジャンル/指標の選択欄を1つのボックスにまとめた
            (ユーザー要望:「今ジャンルのボックス×2とインジケーターなどを
            決定するボックス×1があるけどこれを1つにしたい。プルダウンで
            インジケーターを選択したらそれに対する選択肢が出てくるように
            したいが、ボックス自体は1つ」)。中身は同じ1つのselectがジャンル
            →(インジケーターの時だけ)サブジャンル→指標、と段階的に入れ替わる
            (詳細はIndicatorPicker.tsx参照)。 */}
        <IndicatorPicker
          indicators={indicators}
          value={node.indicator}
          onSelect={(id) => onChange(applyMainIndicatorChange(node, indicators, id))}
        />

        <ParamInputs
          info={info}
          params={node.params}
          onChange={(next) => onChange({ ...node, params: next })}
          onBlur={nudgeIfSelfCompared}
        />

        {/* +/-○○Pips/価格%/ATR%のオフセット(ユーザー要望:「EMA+○○Pipsや
            終値-○○Pipsを選択できるようにしてほしい」→続けて「オフセットで
            固定値○○Pipsだけじゃなく価格の+○%、ATR(○)の-○%もできるように
            して」)。価格の生単位で測られる指標(EMA/終値/ATR/MACD等)にだけ
            出す - RSI等には意味が無いため出さない。 */}
        {info?.kind && PIP_OFFSET_KINDS.has(info.kind) && (
          <OffsetField
            amount={node.offset_pips}
            mode={node.offset_mode}
            atrLength={node.offset_atr_length}
            onAmountChange={(v) => onChange({ ...node, offset_pips: v })}
            onModeChange={(v) => onChange({ ...node, offset_mode: v })}
            onAtrLengthChange={(v) => onChange({ ...node, offset_atr_length: v })}
          />
        )}

        <LabeledField label="時間足">
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
        </LabeledField>
      </div>

      {fixedLiteralValue !== null ? (
        /* 「陽線」等、比較できる値が「一致(==) 1.0」の1通りしかあり得ない
           指標は、方向/比較先のボックスごと表示せず代わりにこの説明文だけ
           出す(ユーザー報告:「陽線の時比較先出す必要あるの?」- 選ぶ余地が
           無いものをドロップダウン+数値入力で見せるのはかえって紛らわしい
           ため)。SuperTrend方向等、比較先の値が複数あり得る指標は下の
           通常表示のまま。 */
        <div className="flex items-center rounded-lg border-2 border-blue-400/50 bg-blue-500/20 px-2 py-1 text-xs text-blue-100">
          この指標が発生したことを判定します(常に「一致 = {fixedLiteralValue}」)
        </div>
      ) : (
        <>
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
              {visibleOperators.map((op) => (
                <option key={op.id} value={op.id}>
                  {op.label}
                </option>
              ))}
            </select>
          </div>

          {/* 比較先(固定値、または別の指標) - 下端揃えの理由は比較元と同じ */}
          <div className="flex flex-wrap items-end gap-2 rounded-lg border-2 border-blue-400/50 bg-blue-500/20 px-2 py-1">
            <span className="rounded px-1.5 py-0.5 text-[10px] font-bold text-blue-200 bg-blue-500/40">比較先</span>
            <select
              className="glass-input rounded-lg px-2 py-1"
              value={compareMode}
              onChange={(e) => {
                if (e.target.value === 'literal') {
                  onChange({ ...node, value: 0, value_params: {}, literal_mode: normalizedLiteralMode(undefined, info?.kind) })
                } else {
                  const first = defaultCompareIndicator(indicators, node.indicator, info?.pair_group)
                  onChange({
                    ...node,
                    value: first?.id ?? 'close',
                    value_params: defaultParamsFor(first),
                  })
                }
              }}
            >
              {literalAllowed && <option value="literal">固定値</option>}
              {indicatorPairAllowed && <option value="indicator">指標</option>}
            </select>

            {compareMode === 'literal' ? (
              <>
                {/* 固定値を「価格」「Pips」「価格の%」「ATRの%」のどれとして
                    解釈するかのモード選択(ユーザー要望:「固定値でオフセット
                    と同じように価格の％とATRの％を選べるようにしてほしい」
                    →続けて「固定値の種類のプルダウンに価格とPips追加して。
                    価格そのものが価格。価格差はPipsにして」)。price_level
                    kindには「価格」(そのままの数値)、volatility/
                    signed_price_diff kindには「Pips」(数値×pipサイズ)を
                    "そのまま"枠として出し分ける(normalizedLiteralModeの
                    docstring参照)。オフセットと同じPIP_OFFSET_KINDSの指標
                    にだけ出す。固定値自体が1択に固定されている指標
                    (lockedLiteralValue)には出す意味が無い(0の%は常に0)
                    ため除外。 */}
                {lockedLiteralValue === null && info?.kind && PIP_OFFSET_KINDS.has(info.kind) && (
                  <LabeledField label="固定値の種類">
                    <select
                      className="glass-input rounded-lg px-1 py-1 text-xs"
                      value={normalizedLiteralMode(node.literal_mode, info.kind) ?? 'value'}
                      onChange={(e) => {
                        const mode = e.target.value as LiteralMode
                        onChange({ ...node, literal_mode: mode === 'value' ? undefined : mode })
                      }}
                    >
                      {info.kind === 'volatility' || info.kind === 'signed_price_diff' ? (
                        <option value="pips">Pips</option>
                      ) : (
                        <option value="value">価格</option>
                      )}
                      <option value="price_pct">価格の%</option>
                      <option value="atr_pct">ATRの%</option>
                    </select>
                  </LabeledField>
                )}
                <LabeledField label={literalUnitLabel(info, node.literal_mode)}>
                  <input
                    type="number"
                    className="w-20 glass-input rounded-lg px-2 py-1 disabled:cursor-not-allowed disabled:opacity-60"
                    title={
                      lockedLiteralValue !== null
                        ? `この指標は${lockedLiteralValue}との比較だけが銘柄をまたいで意味を持つため、値は固定されています`
                        : node.literal_mode && node.literal_mode !== 'value'
                          ? undefined
                          : [
                              info?.literal_hard_bound
                                ? `定義上 ${info.literal_hard_bound[0] ?? '下限なし'}〜${info.literal_hard_bound[1] ?? '上限なし'} の範囲`
                                : null,
                              info?.literal_presets && info.literal_presets.length > 0
                                ? `目安: ${info.literal_presets.join(', ')}`
                                : null,
                            ]
                              .filter((s): s is string => s !== null)
                              .join(' / ') || undefined
                    }
                    disabled={lockedLiteralValue !== null}
                    // literal_modeが%系の時は「絶対に超えられない範囲」の
                    // 前提(生の指標値の範囲)がそのまま%の値には当てはまら
                    // ないため、min/max・丸め込みは"value"モードの時だけ
                    // 適用する。
                    min={!node.literal_mode || node.literal_mode === 'value' ? (info?.literal_hard_bound?.[0] ?? undefined) : undefined}
                    max={!node.literal_mode || node.literal_mode === 'value' ? (info?.literal_hard_bound?.[1] ?? undefined) : undefined}
                    value={lockedLiteralValue ?? (node.value as number)}
                    onChange={(e) => onChange({ ...node, value: Number(e.target.value) })}
                    onBlur={(e) => {
                      // 定義上あり得ない値(例: EMA角度に1000)を打ち込んでも
                      // エラーにはならず、常に真/常に偽の無意味な条件が静かに
                      // できあがってしまっていた(ユーザー報告:「角度の固定値
                      // 1000とか入れたらどうなるの?」)。フォーカスを外した時点で
                      // 範囲内に丸め込むことで、そもそも打ち込めないようにする。
                      // 片側だけnull(下限0・上限なし等)の指標もあるため、
                      // Math.min/maxへそのままnullを渡さず側ごとに判定する。
                      if (node.literal_mode && node.literal_mode !== 'value') return
                      const bound = info?.literal_hard_bound
                      if (!bound) return
                      const [lo, hi] = bound
                      const v = Number(e.target.value)
                      if (Number.isNaN(v)) return
                      let clamped = v
                      if (lo !== null) clamped = Math.max(lo, clamped)
                      if (hi !== null) clamped = Math.min(hi, clamped)
                      if (clamped !== v) onChange({ ...node, value: clamped })
                    }}
                  />
                </LabeledField>
                {node.literal_mode === 'atr_pct' && (
                  <LabeledField label="ATR期間">
                    <input
                      type="number"
                      step="1"
                      className="w-14 glass-input rounded-lg px-2 py-1"
                      value={node.literal_atr_length ?? 14}
                      onChange={(e) =>
                        onChange({
                          ...node,
                          literal_atr_length: e.target.value === '' ? undefined : Number(e.target.value),
                        })
                      }
                    />
                  </LabeledField>
                )}
              </>
            ) : (
              <>
                <IndicatorPicker
                  indicators={compatibleValueIndicators}
                  value={node.value as string}
                  onSelect={(id) => {
                    const nextInfo = indicatorInfo(indicators, id)
                    onChange({
                      ...node,
                      value: id,
                      value_params: differentiatedValueParams(nextInfo, node.indicator, node.params, id),
                      // 切り替え先がPips非対応kindならoffsetを持ち越さない
                      // (上のapplyMainIndicatorChangeと同じ理由)。
                      value_offset_pips:
                        nextInfo?.kind && PIP_OFFSET_KINDS.has(nextInfo.kind) ? node.value_offset_pips : undefined,
                      value_offset_mode:
                        nextInfo?.kind && PIP_OFFSET_KINDS.has(nextInfo.kind) ? node.value_offset_mode : undefined,
                      value_offset_atr_length:
                        nextInfo?.kind && PIP_OFFSET_KINDS.has(nextInfo.kind) ? node.value_offset_atr_length : undefined,
                    })
                  }}
                />
                <ParamInputs
                  info={valueIndicatorInfo}
                  params={node.value_params}
                  onChange={(next) => onChange({ ...node, value_params: next })}
                  onBlur={nudgeIfSelfCompared}
                />

                {/* +/-○○Pips/価格%/ATR%(比較先側) - 「終値 > EMA+20Pips」
                    のような使い方(ユーザー要望の例:「EMA 200 自足 ＞ 終値
                    +20Pips 自足」)。 */}
                {valueIndicatorInfo?.kind && PIP_OFFSET_KINDS.has(valueIndicatorInfo.kind) && (
                  <OffsetField
                    amount={node.value_offset_pips}
                    mode={node.value_offset_mode}
                    atrLength={node.value_offset_atr_length}
                    onAmountChange={(v) => onChange({ ...node, value_offset_pips: v })}
                    onModeChange={(v) => onChange({ ...node, value_offset_mode: v })}
                    onAtrLengthChange={(v) => onChange({ ...node, value_offset_atr_length: v })}
                  />
                )}

                <LabeledField label="時間足">
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
                </LabeledField>
              </>
            )}
          </div>
        </>
      )}

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
