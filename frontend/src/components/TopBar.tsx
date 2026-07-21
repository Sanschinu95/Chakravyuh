import type { Summary } from '../lib/api'
import { num } from '../lib/format'

interface Props {
  summary: Summary | null
  connected: boolean
}

export default function TopBar({ summary, connected }: Props) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">CHAKRAVYUH</span>
        <span className="brand-sub">
          Anticipatory Energy Supply-Chain Resilience · India
        </span>
      </div>

      <div className="topbar-stats">
        {summary && (
          <>
            <Stat v={`${num(summary.import_kbd)}`} l="crude imports kbd" />
            <Stat v={`${num(summary.refining_capacity_kbd)}`} l="refining kbd" />
            <Stat v={`${summary.spr_mmbbl.toFixed(1)}`} l="SPR mmbbl" />
            <Stat
              v={`${summary.spr_days_cover.toFixed(1)}d`}
              l="days of cover"
            />
            <Stat
              v={`${(summary.corridor_shares['Hormuz'] ?? 0).toFixed(0)}%`}
              l="via Hormuz"
            />
          </>
        )}
        <span className="conn">
          <span className={`dot ${connected ? 'on' : 'off'}`} />
          {connected ? 'WS LIVE' : 'WS OFFLINE'}
        </span>
      </div>
    </header>
  )
}

function Stat({ v, l }: { v: string; l: string }) {
  return (
    <div className="tstat">
      <span className="tstat-v">{v}</span>
      <span className="tstat-l">{l}</span>
    </div>
  )
}
