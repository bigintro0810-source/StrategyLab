import { useState } from 'react'
import {
  CONDITION_GENRE_ORDER,
  INDICATOR_SUB_GENRE_ORDER,
  buildGenreItemsMap,
  buildSubGenreItemsMap,
  conditionGenreOf,
  indicatorSubGenreOf,
  type ConditionGenreKey,
  type IndicatorSubGenreKey,
} from '../conditionGenres'
import type { IndicatorInfo } from '../types'

// ジャンル/サブジャンル/指標の3つの選択欄を、見た目上は常に1つの<select>
// だけに収める(ユーザー要望:「今ジャンルのボックス×2とインジケーター
// などを決定するボックス×1があるけどこれを1つにしたい。プルダウンで
// インジケーターを選択したらそれに対する選択肢が出てくるようにしたいが、
// ボックス自体は1つ」)。
//
// 仕組み: 1つのselectが「今どの段を選んでいるか(navLevel)」に応じて中身
// (ジャンル一覧/サブジャンル一覧/指標一覧のどれか)を丸ごと入れ替える。
// 通常時(navLevel==='indicator')は現在の値が属するジャンル/サブジャンルの
// 指標一覧を表示し、その上に「インジケーター ▸ EMA」のようなパンくずを
// 出す - パンくずの各段をクリックすると、selectの中身がその段の選択肢
// (ジャンル一覧、またはサブジャンル一覧)に切り替わり、選び直せる。
// ジャンル/サブジャンルを選んだ時点ではまだ実際のvalueは変えず(選び直し
// 中に指標がコロコロ変わらないように)、指標を最終的に選んだ時だけ
// onSelectを呼ぶ。
type NavLevel = 'genre' | 'subgenre' | 'indicator'

interface Props {
  indicators: IndicatorInfo[]
  value: string
  onSelect: (id: string) => void
  className?: string
}

export default function IndicatorPicker({ indicators, value, onSelect, className }: Props) {
  const [navLevel, setNavLevel] = useState<NavLevel>('indicator')
  // ジャンル/サブジャンルを選び直している間、まだonSelectを呼ばずに
  // ここへ仮置きする(上のコメント参照)。
  const [pendingGenre, setPendingGenre] = useState<ConditionGenreKey | null>(null)

  const info = indicators.find((i) => i.id === value)
  const committedGenre: ConditionGenreKey = info ? conditionGenreOf(info) : CONDITION_GENRE_ORDER[0].key
  const committedSubGenre: IndicatorSubGenreKey | null =
    committedGenre === 'indicator' && info ? indicatorSubGenreOf(info) : null

  const genreItemsMap = buildGenreItemsMap(indicators)

  const goToGenreLevel = () => {
    setPendingGenre(null)
    setNavLevel('genre')
  }
  const goToSubGenreLevel = () => {
    setPendingGenre('indicator')
    setNavLevel('subgenre')
  }

  if (navLevel === 'genre') {
    return (
      <div className={className}>
        <select
          className="glass-input glass-select rounded-lg py-0.5 pl-2"
          value=""
          onChange={(e) => {
            const key = e.target.value as ConditionGenreKey
            if (key === 'indicator') {
              setPendingGenre('indicator')
              setNavLevel('subgenre')
            } else {
              const first = genreItemsMap.get(key)?.[0]
              if (first) onSelect(first.id)
              setPendingGenre(null)
              setNavLevel('indicator')
            }
          }}
        >
          <option value="" disabled>
            ジャンルを選択
          </option>
          {CONDITION_GENRE_ORDER.filter((g) => (genreItemsMap.get(g.key)?.length ?? 0) > 0).map((g) => (
            <option key={g.key} value={g.key}>
              {g.label}
            </option>
          ))}
        </select>
      </div>
    )
  }

  if (navLevel === 'subgenre') {
    const genreItems = genreItemsMap.get(pendingGenre ?? 'indicator') ?? []
    const subGenreItemsMap = buildSubGenreItemsMap(genreItems)
    return (
      <div className={className}>
        {/* mb-0.5 + leading-none: 他のボックスのラベル→入力欄の間隔
            (LabeledFieldのgap-0.5 + text-[9px] leading-none)と揃える
            (ユーザー報告:「チャートパターンっていう文字の隙間をそのほかの
            ボックスと同じにして」→「同じになった？もう少し下じゃない？」
            - mb-0.5だけではdiv自体の行の高さ(line-height)分の余白が文字の
            下に残ったままだったため、leading-noneも追加してその分も詰める)。 */}
        <div className="mb-0.5 text-[11px] leading-none text-blue-300">
          <button type="button" className="hover:underline" onClick={goToGenreLevel}>
            インジケーター
          </button>
          {' ▸ '}
        </div>
        <select
          className="glass-input glass-select rounded-lg py-0.5 pl-2"
          value=""
          onChange={(e) => {
            const key = e.target.value as IndicatorSubGenreKey
            const first = subGenreItemsMap.get(key)?.[0]
            if (first) onSelect(first.id)
            setPendingGenre(null)
            setNavLevel('indicator')
          }}
        >
          <option value="" disabled>
            サブジャンルを選択
          </option>
          {INDICATOR_SUB_GENRE_ORDER.filter((g) => (subGenreItemsMap.get(g.key)?.length ?? 0) > 0).map((g) => (
            <option key={g.key} value={g.key}>
              {g.label}
            </option>
          ))}
        </select>
      </div>
    )
  }

  // navLevel === 'indicator'(通常時) - 現在の値が属するジャンル/サブ
  // ジャンルの指標一覧を表示する。
  const genreItems = genreItemsMap.get(committedGenre) ?? []
  const subGenreItemsMap = committedGenre === 'indicator' ? buildSubGenreItemsMap(genreItems) : null
  let items = subGenreItemsMap && committedSubGenre ? subGenreItemsMap.get(committedSubGenre) ?? [] : genreItems
  // 現在の値がlegacy指標(一覧からは除外するが、既存の保存済みストラテジー
  // 互換のため指標自体は残しているもの)の場合、一覧からは除外済みなので
  // itemsに含まれない - そのままだと<select value={value}>
  // に対応する<option>が無く、表示が勝手に別の指標にすり替わって見えて
  // しまう(保存済みストラテジーを開いただけで中身が変わったように見える
  // 事故になる) - 現在値だけ一覧の先頭に補って表示を保つ。選び直しの
  // ためではなく現在値を壊さず見せるためだけの措置。
  if (info?.legacy && !items.some((i) => i.id === value)) {
    items = [info, ...items]
  }
  const genreLabel = CONDITION_GENRE_ORDER.find((g) => g.key === committedGenre)?.label ?? committedGenre
  const subGenreLabel = committedSubGenre
    ? INDICATOR_SUB_GENRE_ORDER.find((g) => g.key === committedSubGenre)?.label
    : null

  return (
    <div className={className}>
      {/* mb-0.5 + leading-none: 他のボックスのラベル→入力欄の間隔
          (LabeledFieldのgap-0.5 + text-[9px] leading-none)と揃える
          (ユーザー報告:「チャートパターンっていう文字の隙間をそのほかの
          ボックスと同じにして」→「同じになった？もう少し下じゃない？」
          - mb-0.5だけではdiv自体の行の高さ(line-height)分の余白が文字の
          下に残ったままだったため、leading-noneも追加してその分も詰める)。 */}
      <div className="mb-0.5 flex items-center gap-1 text-[11px] leading-none text-blue-300">
        <button type="button" className="hover:underline" onClick={goToGenreLevel}>
          {genreLabel}
        </button>
        {subGenreLabel && (
          <>
            <span>{'▸'}</span>
            <button type="button" className="hover:underline" onClick={goToSubGenreLevel}>
              {subGenreLabel}
            </button>
          </>
        )}
      </div>
      {/* 指標名(ダブルトップ等)が長いと、幅を決めずに置くと親のflex-wrap行
          いっぱいまで伸びたり、逆に狭い時は文字とネイティブ矢印の間に余白が
          目立ったりしていた(ユーザー報告:「チャートパターン名のボックスも
          …と矢印の間に空白が目立つ」)。state等のパラメータ欄と同じ
          glass-select(自前の矢印アイコン)+truncateで、幅を固定して統一する。 */}
      <select
        // text-xsを外し、数値入力欄と同じtext-sm継承にして高さを揃える
        // (ユーザー報告:「文字のボックスは数字のボックスよりも高さが少し
        // 低い」)。幅は元の280px(280÷280=1倍)から0.8倍の224pxに変更
        // (ユーザー要望:「チャートパターンのボックスを0.8倍にして」)。
        className="glass-input glass-select w-28 truncate rounded-lg py-0.5 pl-2"
        style={{ width: '224px' }}
        value={value}
        onChange={(e) => onSelect(e.target.value)}
      >
        {items.map((ind) => (
          <option key={ind.id} value={ind.id}>
            {ind.label}
          </option>
        ))}
      </select>
    </div>
  )
}
