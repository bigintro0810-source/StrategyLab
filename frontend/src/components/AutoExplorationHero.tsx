import type { BacktestProgress } from '../types'

interface Props {
  progress: BacktestProgress | null | undefined
  isRunning: boolean | undefined
}

function formatEta(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '--:--:--'
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return [h, m, sec].map((v) => String(v).padStart(2, '0')).join(':')
}

export default function AutoExplorationHero({ progress, isRunning }: Props) {
  if (!isRunning) return null

  // main.py only starts writing progress.json once the executor is set up,
  // so there's a short real window (job status "running" but no file yet)
  // where there's genuinely nothing to show - a plain "starting" state
  // beats guessing at numbers.
  if (!progress) {
    return (
      <div className="glass-panel mb-4 flex items-center gap-3 rounded-2xl px-4 py-3">
        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-emerald-400" />
        <span className="text-sm text-gray-300">準備中…(データ読み込み・並列実行の起動)</span>
      </div>
    )
  }

  const pct = progress.total > 0 ? Math.min(100, Math.round((progress.completed / progress.total) * 1000) / 10) : 0
  const speed = progress.elapsed_seconds > 0 ? progress.completed / progress.elapsed_seconds : 0
  const remaining = Math.max(0, progress.total - progress.completed)
  const etaSeconds = speed > 0 ? remaining / speed : NaN

  const radius = 25
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - pct / 100)

  return (
    <div className="glass-panel mb-4 grid grid-cols-[60px_1fr] items-center gap-4 rounded-2xl px-4 py-2.5">
      <div className="relative h-[60px] w-[60px]">
        <svg width="60" height="60" viewBox="0 0 60 60" className="-rotate-90">
          <circle cx="30" cy="30" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
          <circle
            cx="30"
            cy="30"
            r={radius}
            fill="none"
            stroke="url(#hero-ring-gradient)"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
          />
          <defs>
            <linearGradient id="hero-ring-gradient" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#3b82f6" />
              <stop offset="1" stopColor="#8b5cf6" />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 flex items-center justify-center font-mono text-[13px] tabular-nums text-gray-100">
          {pct}%
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-baseline gap-2 text-xs text-gray-300">
          {progress.generation != null && progress.generations_total != null ? (
            <b className="font-semibold text-gray-100">
              世代 {progress.generation} / {progress.generations_total} を検証中
            </b>
          ) : (
            <b className="font-semibold text-gray-100">候補を検証中</b>
          )}
          <span className="text-emerald-400">● 実行中</span>
        </div>
        <div className="grid grid-cols-4 gap-2">
          <div>
            <div className="text-[9.5px] text-gray-500">検証済み件数</div>
            <div className="font-mono text-xs tabular-nums text-gray-100">{progress.completed.toLocaleString()}</div>
          </div>
          <div>
            <div className="text-[9.5px] text-gray-500">残り件数</div>
            <div className="font-mono text-xs tabular-nums text-gray-100">{remaining.toLocaleString()}</div>
          </div>
          <div>
            <div className="text-[9.5px] text-gray-500">検証速度</div>
            <div className="font-mono text-xs tabular-nums text-gray-100">{speed > 0 ? `${speed.toFixed(1)} 件/秒` : '-'}</div>
          </div>
          <div>
            <div className="text-[9.5px] text-gray-500">推定残り時間</div>
            <div className="font-mono text-xs tabular-nums text-gray-100">{formatEta(etaSeconds)}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
