import { useState } from 'react'
import Plot from 'react-plotly.js'
import { toPips } from '../pipUtils'
import { buildMetricColumns, type MetricRowLike } from '../rankingColumns'
import type { CompareEntry } from '../api'
import type { CompositeCandidate } from '../compositeUtils'
import type { IndicatorInfo } from '../types'
import AddCandidateModal from './AddCandidateModal'

interface Props {
  entries: CompareEntry[]
  emptyMessage: string
  indicators: IndicatorInfo[]
  // 「+ 比較対象を追加」ピッカー(AddCandidateModal.tsx)用 - 合成タブと同じ
  // 候補一覧/トグル関数をApp.tsx側から渡す(結果側/ライブラリ側で中身は
  // 違うが、正規化された形は共通)。
  candidates: CompositeCandidate[]
  onToggleInput: (id: string) => void
}

const LINE_COLORS = ['#60a5fa', '#c084fc', '#34d399', '#fbbf24', '#f87171', '#22d3ee']

// entry.metrics(strategy_registry.pyのMETRIC_COLUMNS、あるいは結果側で
// App.tsxがrankingTotalの行から組み立てたもの)はexpected_valueを持たない
// ため、ランキング一覧/ライブラリ画面と同じ定義(net_profit÷trades)で
// ここでも計算する。
function toMetricRow(entry: CompareEntry): MetricRowLike {
  const m = entry.metrics
  const trades = Number(m.trades) || 0
  return {
    profit_factor: m.profit_factor,
    net_profit: m.net_profit,
    expected_value: trades > 0 ? Number(m.net_profit) / trades : 0,
    max_dd: m.max_dd,
    win_rate: m.win_rate,
    trades: m.trades,
    sharpe_ratio: m.sharpe_ratio,
    recovery_factor: m.recovery_factor,
    sortino_ratio: m.sortino_ratio,
    calmar_ratio: m.calmar_ratio,
    cagr: m.cagr,
    condition_tree: entry.condition_tree,
    symbol: entry.symbol,
  }
}

export default function CompareView({ entries, emptyMessage, indicators, candidates, onToggleInput }: Props) {
  const [showAddModal, setShowAddModal] = useState(false)

  // モーダル(position:fixed)は.glass-panel(backdrop-filter)の外側で
  // レンダリングする必要がある - backdrop-filterがfixed子要素の新しい
  // 包含ブロックを作ってしまい、モーダルが画面全体ではなくこのパネルの
  // 範囲内に切り詰められてしまうため(CompositeDetail.tsxで実際に踏んだ
  // 不具合と同じ)。さらに、モーダルはentries有無の分岐の外側(常に評価
  // される側)に置く必要がある - 分岐の中だけにあると、1件目を追加した
  // 瞬間にentriesが空でなくなって別の分岐(比較テーブル側)に切り替わり、
  // モーダルごとアンマウントされて2件目以降を連続して選べなくなる
  // (実際に踏んだ不具合: 「現在は1つずつしか追加できない」)。
  if (entries.length === 0) {
    return (
      <>
        <div className="glass-panel space-y-3 rounded-2xl p-4 text-sm text-gray-500">
          <div>{emptyMessage}</div>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200 hover:bg-white/10"
          >
            + 比較対象を追加
          </button>
        </div>
        {showAddModal && (
          <AddCandidateModal
            title="比較対象を追加"
            candidates={candidates}
            selectedIds={entries.map((e) => e.id)}
            onToggle={onToggleInput}
            onClose={() => setShowAddModal(false)}
          />
        )}
      </>
    )
  }

  const columns = buildMetricColumns(indicators)

  return (
    <div className="space-y-4">
      {/* ランキング一覧/ライブラリ画面と同じ並び(お気に入り〜条件)の指標
          テーブル - 1行=1ストラテジー。ここの⭐は状態表示のみで、切り替えは
          元の画面(ランキング一覧/ライブラリ)から行う。 */}
      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-xs font-semibold text-gray-200">比較対象({entries.length}件)</div>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="glass-input rounded-lg px-2 py-1 text-[11px] font-semibold text-gray-200 hover:bg-white/10"
          >
            + 比較対象を追加
          </button>
        </div>
        <div className="overflow-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 text-gray-400">
                <th className="px-2 py-1 font-medium" />
                <th className="whitespace-nowrap px-2 py-1 font-medium">名称</th>
                <th className="whitespace-nowrap px-2 py-1 font-medium">通貨/時間足</th>
                {columns.map((col) => (
                  <th
                    key={col.key}
                    title={col.tooltip}
                    className={`whitespace-nowrap ${col.headerPadLeft ?? 'pl-2'} pr-2 py-1 font-medium ${col.numeric ? 'text-right' : ''}`}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const row = toMetricRow(entry)
                return (
                  <tr key={entry.id} className="border-b border-white/5 hover:bg-white/[0.04]">
                    <td className="px-2 py-1">
                      <span className={entry.favorite ? 'grayscale-0 opacity-100' : 'grayscale opacity-40'}>⭐</span>
                    </td>
                    <td className="whitespace-nowrap px-2 py-1">{entry.name}</td>
                    <td className="whitespace-nowrap px-2 py-1 text-gray-300">
                      {entry.symbol}/{entry.timeframe}
                    </td>
                    {columns.map((col) => {
                      const raw = row[col.key]
                      const text = col.format ? col.format(raw, row) : String(raw ?? '')
                      const colorClass = col.colorClass ? col.colorClass(raw) : ''
                      return (
                        <td
                          key={col.key}
                          title={col.key === 'condition_tree' ? text : undefined}
                          className={
                            col.key === 'condition_tree'
                              ? `max-w-xs truncate ${col.headerPadLeft ?? 'pl-2'} pr-2 py-1 font-mono text-[11px] text-gray-400`
                              : `whitespace-nowrap px-2 py-1 ${col.numeric ? 'text-right' : ''} ${colorClass}`
                          }
                        >
                          {text}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-4">
        <div className="mb-1 text-center text-lg font-semibold text-gray-300">累積Pips</div>
        <Plot
          data={entries.map((entry, i) => ({
            x: entry.equity_curve.map((p) => p.exit_time),
            y: entry.equity_curve.map((p) => toPips(p.equity, entry.symbol)),
            type: 'scatter',
            mode: 'lines',
            name: entry.name,
            line: { color: LINE_COLORS[i % LINE_COLORS.length], width: 1.5 },
          }))}
          layout={{
            autosize: true,
            height: 280,
            margin: { l: 40, r: 10, t: 10, b: 30 },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            font: { color: '#d1d5db' },
            showlegend: true,
            legend: { orientation: 'h', font: { size: 10 } },
            xaxis: {
              type: 'date',
              dtick: 'M12',
              tickformat: '%Y',
              gridcolor: 'rgba(255,255,255,0.08)',
            },
            yaxis: { gridcolor: 'rgba(255,255,255,0.08)' },
          }}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: '100%' }}
        />
      </div>

      {showAddModal && (
        <AddCandidateModal
          title="比較対象を追加"
          candidates={candidates}
          selectedIds={entries.map((e) => e.id)}
          onToggle={onToggleInput}
          onClose={() => setShowAddModal(false)}
        />
      )}
    </div>
  )
}
