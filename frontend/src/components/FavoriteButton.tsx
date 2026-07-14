interface Props {
  isFavorite: boolean
  isPending: boolean
  disabled?: boolean
  onClick: () => void
}

// ⭐はカラー絵文字グリフなのでCSSのtext-colorでは色が変わらない(常に絵文字
// 本来の色で描画される) - grayscaleフィルター+opacityで未お気に入り=
// グレーアウト、お気に入り済み=フルカラーを表現する(RankingTable.tsxの
// 🔖/⭐で確認済みの手法をランキング一覧以外でも共通で使う)。
export default function FavoriteButton({ isFavorite, isPending, disabled, onClick }: Props) {
  return (
    <button
      type="button"
      disabled={disabled || isPending}
      onClick={onClick}
      title={isPending ? '保存中…' : isFavorite ? 'お気に入り解除' : 'お気に入りに追加'}
      className={`disabled:opacity-40 transition-all ${
        isPending
          ? 'grayscale animate-pulse opacity-60'
          : isFavorite
            ? 'grayscale-0 opacity-100'
            : 'grayscale opacity-40 hover:opacity-70'
      }`}
    >
      ⭐
    </button>
  )
}
