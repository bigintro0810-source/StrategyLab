import type { StrategyListEntry } from '../types'

interface Props {
  strategies: StrategyListEntry[]
  onLoad: (id: string) => void
  isLoading: boolean
}

export default function SavedStrategiesPanel({ strategies, onLoad, isLoading }: Props) {
  if (strategies.length === 0) {
    return <div className="p-4 text-sm text-gray-500">保存された戦略がありません</div>
  }

  return (
    <div className="overflow-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-gray-400">
            <th className="px-2 py-1 font-medium">名前</th>
            <th className="px-2 py-1 font-medium">通貨/時間足</th>
            <th className="px-2 py-1 font-medium">PF</th>
            <th className="px-2 py-1 font-medium">総利益</th>
            <th className="px-2 py-1 font-medium">DD</th>
            <th className="px-2 py-1 font-medium" />
          </tr>
        </thead>
        <tbody>
          {strategies
            .slice()
            .reverse()
            .map((s) => (
              <tr key={s.id} className="border-b border-white/5 hover:bg-white/[0.04]">
                <td className="px-2 py-1">{s.name}</td>
                <td className="px-2 py-1">
                  {s.symbol}/{s.timeframe}
                </td>
                <td className="px-2 py-1">{s.metrics.profit_factor?.toFixed(2) ?? '-'}</td>
                <td className="px-2 py-1">{s.metrics.net_profit?.toFixed(1) ?? '-'}</td>
                <td className="px-2 py-1">{s.metrics.max_dd?.toFixed(1) ?? '-'}</td>
                <td className="px-2 py-1">
                  <button
                    type="button"
                    disabled={isLoading}
                    onClick={() => onLoad(s.id)}
                    className="rounded-lg border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-gray-300 hover:bg-white/10 disabled:opacity-40"
                  >
                    読み込む
                  </button>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}
