import { useState } from 'react'
import type { CorridorSummary } from '../lib/api'

export interface CustomShock {
  kind: string
  target: string
  severity: number
  duration_days: number
}

const CHOKEPOINTS = [
  { id: 'HORMUZ', label: 'Strait of Hormuz' },
  { id: 'BAB', label: 'Bab el-Mandeb' },
  { id: 'SUEZ', label: 'Suez Canal' },
  { id: 'MALACCA', label: 'Strait of Malacca' },
  { id: 'CAPE', label: 'Cape of Good Hope' },
]

const PORTS = ['Sikka', 'Vadinar SPM', 'Paradip', 'New Mangalore',
  'Kochi (Puthuvypeen SPM)', 'Visakhapatnam']

const SUPPLIERS = [
  { id: 'URAL', label: 'Urals (Russia)' },
  { id: 'BASM', label: 'Basrah Medium (Iraq)' },
  { id: 'ARBL', label: 'Arab Light (Saudi)' },
  { id: 'ESPO', label: 'ESPO (Russia Far East)' },
  { id: 'MURB', label: 'Murban (UAE)' },
]

interface Props {
  corridors: CorridorSummary[]
  running: boolean
  onExecute: (shocks: CustomShock[]) => void
}

/**
 * "You are the adversary." Lets a judge build their own attack and run it
 * through the same defense pipeline the scenarios use — no special casing,
 * no pre-baked answer.
 */
export default function AttackConsole({ running, onExecute }: Props) {
  const [primary, setPrimary] = useState('HORMUZ')
  const [severity, setSeverity] = useState(0.6)
  const [duration, setDuration] = useState(21)
  const [combo, setCombo] = useState<'none' | 'port' | 'supplier'>('none')
  const [comboTarget, setComboTarget] = useState(PORTS[0])
  const [comboSeverity, setComboSeverity] = useState(1.0)

  const build = (): CustomShock[] => {
    const out: CustomShock[] = [
      { kind: 'chokepoint', target: primary, severity, duration_days: duration },
    ]
    if (combo !== 'none') {
      out.push({
        kind: combo,
        target: comboTarget,
        severity: comboSeverity,
        duration_days: Math.max(7, Math.round(duration / 2)),
      })
    }
    return out
  }

  return (
    <>
      <div className="ctl-label">Primary attack — chokepoint</div>
      <select className="sel" value={primary} onChange={(e) => setPrimary(e.target.value)}>
        {CHOKEPOINTS.map((c) => (
          <option key={c.id} value={c.id}>{c.label}</option>
        ))}
      </select>

      <div className="slider-row">
        <span className="slider-label">Closure</span>
        <span className="slider-val">{Math.round(severity * 100)}%</span>
      </div>
      <input type="range" min={0.1} max={1} step={0.05} value={severity}
        onChange={(e) => setSeverity(Number(e.target.value))} />

      <div className="slider-row">
        <span className="slider-label">Duration</span>
        <span className="slider-val">{duration} days</span>
      </div>
      <input type="range" min={3} max={90} step={1} value={duration}
        onChange={(e) => setDuration(Number(e.target.value))} />

      <div className="ctl-label" style={{ marginTop: 12 }}>
        Combine with a second attack
      </div>
      <div className="chip-row">
        {(['none', 'port', 'supplier'] as const).map((k) => (
          <button
            key={k}
            className={`chip ${combo === k ? 'on' : ''}`}
            style={combo === k
              ? { borderColor: 'var(--crit)', background: 'rgba(239,68,68,.12)', color: '#fca5a5' }
              : undefined}
            onClick={() => {
              setCombo(k)
              if (k === 'port') setComboTarget(PORTS[0])
              if (k === 'supplier') setComboTarget(SUPPLIERS[0].id)
            }}
          >
            {k === 'none' ? 'single attack' : k === 'port' ? 'close a port' : 'sanction a grade'}
          </button>
        ))}
      </div>

      {combo !== 'none' && (
        <>
          <select className="sel" value={comboTarget}
            onChange={(e) => setComboTarget(e.target.value)}>
            {(combo === 'port'
              ? PORTS.map((p) => ({ id: p, label: p }))
              : SUPPLIERS
            ).map((o) => (
              <option key={o.id} value={o.id}>{o.label}</option>
            ))}
          </select>
          <div className="slider-row">
            <span className="slider-label">Second attack severity</span>
            <span className="slider-val">{Math.round(comboSeverity * 100)}%</span>
          </div>
          <input type="range" min={0.2} max={1} step={0.05} value={comboSeverity}
            onChange={(e) => setComboSeverity(Number(e.target.value))} />
        </>
      )}

      <button className="btn-execute" disabled={running}
        onClick={() => onExecute(build())}>
        {running ? 'DEFENDING…' : 'EXECUTE ATTACK'}
      </button>
      <div className="micro">
        Runs the same pipeline as the scenario library: cascade → procurement
        optimiser → SPR bridge → narration. Nothing here is pre-computed.
      </div>
    </>
  )
}
