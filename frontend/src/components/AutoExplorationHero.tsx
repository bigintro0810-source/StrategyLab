import type { BacktestProgress } from '../types'

interface Props {
  progress: BacktestProgress | null | undefined
  isRunning: boolean | undefined
  // Inline single-row rendering for the 手動探索 header bar, alongside the
  // 銘柄/時間足/データセット controls - the standalone full-width block
  // below stays for the 自動探索 screen's own layout.
  compact?: boolean
}

function formatEta(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '--:--:--'
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return [h, m, sec].map((v) => String(v).padStart(2, '0')).join(':')
}

// min-w reserves enough room for the widest value each stat can show (idle
// "-"/"--:--:--" vs running "12,345"/"7.1 件/秒"/"00:01:38") plus some
// breathing room, so the box's own width - and therefore the ring's
// position, pinned to the stats block via the shared flex row - doesn't
// shift between idle and running.
function CompactStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-[64px] whitespace-nowrap">
      <div className="text-[9.5px] text-gray-500">{label}</div>
      <div className="font-mono text-xs tabular-nums text-gray-100">{value}</div>
    </div>
  )
}

// Single DOM shape for both idle and running so nothing shifts position when
// a run starts/finishes: the ring (with "-%" and an empty track when idle)
// and its status text always sit in the same fixed-width left slot, so
// 残りのブロック/検証速度/推定残り時間 always start at the same x position.
function CompactHero({ progress, isRunning }: Props) {
  const active = Boolean(isRunning && progress)
  const pct = active && progress ? (progress.total > 0 ? Math.min(100, Math.round((progress.completed / progress.total) * 1000) / 10) : 0) : 0
  const speed = active && progress && progress.elapsed_seconds > 0 ? progress.completed / progress.elapsed_seconds : 0
  const remaining = active && progress ? Math.max(0, progress.total - progress.completed) : 0
  const etaSeconds = speed > 0 ? remaining / speed : NaN

  const compactRadius = 18
  const compactCircumference = 2 * Math.PI * compactRadius
  const compactDashOffset = active ? compactCircumference * (1 - pct / 100) : compactCircumference

  return (
    <div className="flex items-center">
      <div className="flex w-56 flex-none items-center gap-2">
        <div className="relative h-11 w-11 flex-none">
          <svg width="44" height="44" viewBox="0 0 44 44" className="-rotate-90">
            <circle cx="22" cy="22" r={compactRadius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="4" />
            <circle
              cx="22"
              cy="22"
              r={compactRadius}
              fill="none"
              stroke="url(#hero-ring-gradient-compact)"
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray={compactCircumference}
              strokeDashoffset={compactDashOffset}
            />
            <defs>
              <linearGradient id="hero-ring-gradient-compact" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#3b82f6" />
                <stop offset="1" stopColor="#8b5cf6" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute inset-0 flex items-center justify-center font-mono text-[10px] tabular-nums text-gray-100">
            {active ? `${pct}%` : '-%'}
          </div>
        </div>
        <div className="flex flex-col gap-0.5 whitespace-nowrap">
          <div className="flex items-baseline gap-1.5 text-xs text-gray-300">
            {active && progress ? (
              <>
                {progress.generation != null && progress.generations_total != null ? (
                  <b className="font-semibold text-gray-100">
                    世代 {progress.generation} / {progress.generations_total} を検証中
                  </b>
                ) : (
                  <b className="font-semibold text-gray-100">候補を検証中</b>
                )}
                <span className="text-emerald-400">●実行中</span>
              </>
            ) : (
              <span className="text-gray-400">{isRunning ? '準備中…' : '待機中'}</span>
            )}
          </div>
          {active && progress && (
            <div className="text-[9.5px] text-gray-500">検証済みブロック {progress.completed.toLocaleString()}</div>
          )}
        </div>
      </div>
      <div className="ml-auto flex items-center gap-6">
        <CompactStat label="残りのブロック" value={active ? remaining.toLocaleString() : '-'} />
        <CompactStat label="検証速度" value={active && speed > 0 ? `${speed.toFixed(1)} 件/秒` : '-'} />
        <CompactStat label="推定残り時間" value={active ? formatEta(etaSeconds) : '--:--:--'} />
      </div>
    </div>
  )
}

export default function AutoExplorationHero({ progress, isRunning, compact }: Props) {
  if (compact) return <CompactHero progress={progress} isRunning={isRunning} />

  // main.py only starts writing progress.json once the executor is set up,
  // so there's a short real window (job status "running" but no file yet)
  // where there's genuinely nothing to show yet - and outside a run, this
  // panel stays visible with placeholder values instead of disappearing, so
  // 残り件数/検証速度/推定残り時間 always have a fixed spot on screen.
  if (!isRunning || !progress) {
    return (
      <div className="glass-panel mb-4 flex items-center gap-4 rounded-2xl px-4 py-3">
        <span className={`h-2.5 w-2.5 rounded-full ${isRunning ? 'animate-pulse bg-emerald-400' : 'bg-gray-600'}`} />
        <span className="text-sm text-gray-300">
          {isRunning ? '準備中…(データ読み込み・並列実行の起動)' : '待機中'}
        </span>
        <div className="ml-auto grid grid-cols-3 gap-6">
          <div>
            <div className="text-[9.5px] text-gray-500">残り件数</div>
            <div className="font-mono text-xs tabular-nums text-gray-500">-</div>
          </div>
          <div>
            <div className="text-[9.5px] text-gray-500">検証速度</div>
            <div className="font-mono text-xs tabular-nums text-gray-500">-</div>
          </div>
          <div>
            <div className="text-[9.5px] text-gray-500">推定残り時間</div>
            <div className="font-mono text-xs tabular-nums text-gray-500">--:--:--</div>
          </div>
        </div>
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
