import { pipsDecimals, toPips } from '../pipUtils'
import type { RankingRow } from '../types'

interface Props {
  row: RankingRow | undefined
  symbol: string | undefined
}

function fmt(v: number | undefined, digits = 2): string {
  if (v === undefined || Number.isNaN(v)) return '-'
  return v.toFixed(digits)
}

function signedFmt(v: number | undefined, digits: number): string {
  if (v === undefined || Number.isNaN(v)) return '-'
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`
}

interface StatItem {
  label: string
  value: string
  tooltip?: string
}

// フレックス行の途中で強制的に改行させるためのマーカー(basis-fullな空要素を
// 挟むと、そこで折り返す) - ユーザー要望:「ストラテジー詳細に最大利益、
// 最大損失、平均利益、平均損失、中央値利益、中央値損失追加して。改行して
// PFの下から追加して」。
const BREAK = { label: '__break__', value: '' } as const
type StatEntry = StatItem | typeof BREAK

function isBreak(entry: StatEntry): entry is typeof BREAK {
  return entry === BREAK
}

// タブ切り替えの外側・常時表示する統計ストリップ。ランキング一覧の列と
// 同じ項目・同じ順序・同じ単位(PF,純利益(pips),期待値(pips),DD(pips),
// 勝率(%),取引数(回),Sharpe,Recovery,Sortino,Calmar,CAGR(%))で揃えてある -
// 同じ戦略の同じ指標が画面によって違う書き方をしていると混乱するため。
// Sharpe〜MAE系の各項目にはランキング一覧(rankingColumns.ts)と同じ説明文を
// ホバー時に表示する(ユーザー要望:「ストラテジー詳細のSharpe〜中央値MFE
// までカーソル当てたら何を言ってるのか説明して。ランキングと同じように」)。
export default function StatsPanel({ row, symbol }: Props) {
  if (!row) {
    return <div className="mb-2 text-xs text-gray-500">まだ結果がありません</div>
  }

  const stats: StatEntry[] = [
    // 1行目: ランキング一覧と全く同じ項目・同じ順序(ユーザー指定の並び順)。
    { label: 'PF', value: fmt(row.profit_factor), tooltip: 'プロフィットファクター(総利益÷総損失。1より大きければ黒字)' },
    { label: '純利益(pips)', value: signedFmt(toPips(row.net_profit, symbol), 1) },
    { label: '期待値(pips)', value: signedFmt(toPips(row.expected_value, symbol), pipsDecimals(symbol)) },
    { label: 'DD(pips)', value: fmt(toPips(row.max_dd, symbol), 1), tooltip: '最大ドローダウン(資金がピークからどれだけ落ち込んだか)' },
    { label: '勝率(%)', value: fmt(row.win_rate, 1) },
    { label: '取引数(回)', value: String(row.trades) },
    {
      label: 'Sharpe',
      value: fmt(row.sharpe_ratio),
      tooltip: 'シャープレシオ: リターンの大きさを値動きのブレで割った指標。値動きが安定しているほど高い',
    },
    {
      label: 'Recovery',
      value: fmt(row.recovery_factor),
      tooltip: 'リカバリーファクター: 純利益÷最大ドローダウン。ドローダウンに対してどれだけ稼げたか',
    },
    {
      label: 'Sortino',
      value: fmt(row.sortino_ratio),
      tooltip: 'ソルティノレシオ: Sharpeに似ているが、下落方向のブレだけを見る指標(上振れは減点しない)',
    },
    { label: 'Calmar', value: fmt(row.calmar_ratio), tooltip: 'カルマーレシオ: 年率リターン÷最大ドローダウン' },
    { label: 'CAGR(%)', value: fmt(row.cagr * 100, 1), tooltip: '年率換算した成長率' },
    BREAK,
    // 2行目: 勝ちトレード/負けトレードだけに絞った利益・損失、続けて
    // MAE/MFE系(ユーザー指定の並び順、CAGRの後で改行)。
    {
      label: '最大利益(pips)',
      value: signedFmt(toPips(row.max_win, symbol), pipsDecimals(symbol)),
      tooltip: '勝ちトレードの中で最も大きかった利益',
    },
    {
      label: '最大損失(pips)',
      value: signedFmt(toPips(row.max_loss, symbol), pipsDecimals(symbol)),
      tooltip: '負けトレードの中で最も大きかった損失',
    },
    {
      label: '平均利益(pips)',
      value: signedFmt(toPips(row.avg_win, symbol), pipsDecimals(symbol)),
      tooltip: '勝ちトレードだけの平均利益',
    },
    {
      label: '平均損失(pips)',
      value: signedFmt(toPips(row.avg_loss, symbol), pipsDecimals(symbol)),
      tooltip: '負けトレードだけの平均損失',
    },
    {
      label: '中央値利益(pips)',
      value: signedFmt(toPips(row.median_win, symbol), pipsDecimals(symbol)),
      tooltip: '勝ちトレードだけの利益の中央値',
    },
    {
      label: '中央値損失(pips)',
      value: signedFmt(toPips(row.median_loss, symbol), pipsDecimals(symbol)),
      tooltip: '負けトレードだけの損失の中央値',
    },
    {
      label: 'MFE(pips)',
      value: fmt(toPips(row.mfe, symbol), pipsDecimals(symbol)),
      tooltip: '最大追い風幅(MFE): 保有中に価格が最も有利に動いた幅。全トレード中の最大値',
    },
    {
      label: 'MAE(pips)',
      value: fmt(toPips(row.mae, symbol), pipsDecimals(symbol)),
      tooltip: '最大逆行幅(MAE): 保有中に価格が最も不利に動いた幅。全トレード中の最大値',
    },
    {
      label: '平均MFE(pips)',
      value: fmt(toPips(row.mfe_avg, symbol), pipsDecimals(symbol)),
      tooltip: 'MFE(最大追い風幅)の全トレード平均',
    },
    {
      label: '平均MAE(pips)',
      value: fmt(toPips(row.mae_avg, symbol), pipsDecimals(symbol)),
      tooltip: 'MAE(最大逆行幅)の全トレード平均',
    },
    {
      label: '中央値MFE(pips)',
      value: fmt(toPips(row.mfe_median, symbol), pipsDecimals(symbol)),
      tooltip: 'MFE(最大追い風幅)の全トレード中央値',
    },
    {
      label: '中央値MAE(pips)',
      value: fmt(toPips(row.mae_median, symbol), pipsDecimals(symbol)),
      tooltip: 'MAE(最大逆行幅)の全トレード中央値',
    },
  ]

  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-1.5 text-xs">
      {stats.map((s, i) =>
        isBreak(s) ? (
          <div key={`break-${i}`} className="basis-full h-0" />
        ) : (
          <div key={s.label} className="flex items-center gap-1 whitespace-nowrap" title={s.tooltip}>
            <span className="text-gray-400">{s.label}</span>
            <span className="font-semibold text-gray-100">{s.value}</span>
          </div>
        )
      )}
    </div>
  )
}
