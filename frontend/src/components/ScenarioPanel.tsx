import type { Scenario } from '../lib/api'

interface Props {
  scenarios: Scenario[]
  activeId: string | null
  running: boolean
  onRun: (id: string) => void
  onClear: () => void
}

const SEV_COLOR: Record<string, string> = {
  moderate: 'var(--warn)',
  severe: '#fb7185',
  extreme: 'var(--crit)',
}

export default function ScenarioPanel({
  scenarios,
  activeId,
  running,
  onRun,
  onClear,
}: Props) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="panel-title">Scenario Library</span>
        {activeId && (
          <button className="btn-ghost" onClick={onClear} disabled={running}>
            clear
          </button>
        )}
      </div>
      <div className="panel-body scroll" style={{ maxHeight: 300, paddingTop: 6 }}>
        {scenarios.map((s) => (
          <div
            key={s.id}
            className={`scenario-row ${activeId === s.id ? 'sel' : ''}`}
            onClick={() => !running && onRun(s.id)}
          >
            <div className="scenario-top">
              <span className="scenario-name">{s.name}</span>
              <span
                className="scenario-sev"
                style={{ color: SEV_COLOR[s.severity_label] ?? 'var(--text-dim)' }}
              >
                {s.severity_label}
              </span>
            </div>
            <div className="scenario-sum">{s.summary}</div>
            <div className="scenario-anchor">↳ {s.historical_anchor}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
