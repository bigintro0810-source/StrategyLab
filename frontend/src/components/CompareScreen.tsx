import { useQuery } from '@tanstack/react-query'
import { compareStrategies } from '../api'
import CompareView from './CompareView'

interface Props {
  ids: string[]
}

export default function CompareScreen({ ids }: Props) {
  const compareQuery = useQuery({
    queryKey: ['compare-strategies', ids],
    queryFn: () => compareStrategies(ids),
    enabled: ids.length > 0,
  })

  if (ids.length === 0) {
    return (
      <div className="glass-panel rounded-2xl p-4 text-sm text-gray-500">
        比較対象がありません。ライブラリ画面で戦略を2件以上選んでください。
      </div>
    )
  }

  return (
    <CompareView
      entries={compareQuery.data?.entries ?? []}
      emptyMessage="比較対象がありません。ライブラリ画面で戦略を2件以上選んでください。"
    />
  )
}
