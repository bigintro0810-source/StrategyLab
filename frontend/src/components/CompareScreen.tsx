import { useQuery } from '@tanstack/react-query'
import { compareStrategies } from '../api'
import CompareView from './CompareView'
import type { CompositeCandidate } from '../compositeUtils'
import type { IndicatorInfo } from '../types'

interface Props {
  ids: string[]
  indicators: IndicatorInfo[]
  candidates: CompositeCandidate[]
  onToggleInput: (id: string) => void
}

export default function CompareScreen({ ids, indicators, candidates, onToggleInput }: Props) {
  const compareQuery = useQuery({
    queryKey: ['compare-strategies', ids],
    queryFn: () => compareStrategies(ids),
    enabled: ids.length > 0,
  })

  return (
    <CompareView
      entries={compareQuery.data?.entries ?? []}
      emptyMessage="「比較」のチェックボックスを付けるか、下のボタンから比較対象を追加すると、選んだストラテジーをまとめて比較した結果がここに表示されます。"
      indicators={indicators}
      candidates={candidates}
      onToggleInput={onToggleInput}
    />
  )
}
