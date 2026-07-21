import type { CorridorSummary } from '../lib/api'
import { corridorCss, corridorLabel, num } from '../lib/format'

interface Props {
  corridors: CorridorSummary[]
  selected: string | null
  onSelect: (c: string | null) => void
}

export default function CorridorList({ corridors, selected, onSelect }: Props) {
  const max = Math.max(1, ...corridors.map((c) => c.share_pct))
  return (
    <div className="panel" style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="panel-head">
        <span className="panel-title">Corridor Exposure</span>
        <span className="tag" style={{ background: 'rgba(245,158,11,.14)', color: 'var(--curated)' }}>
          curated
        </span>
      </div>
      <div className="panel-body" style={{ paddingTop: 6 }}>
        {corridors.map((c) => (
          <div
            key={c.corridor}
            className={`corridor-row ${selected === c.corridor ? 'sel' : ''}`}
            onClick={() => onSelect(selected === c.corridor ? null : c.corridor)}
          >
            <span className="corridor-name">{corridorLabel(c.corridor)}</span>
            <span className="corridor-val">{c.share_pct.toFixed(1)}%</span>
            <span className="corridor-sub">
              {c.supplier_count} grades · {num(c.kbd)} kbd
            </span>
            <span />
            <div className="bar">
              <div
                className="bar-fill"
                style={{
                  width: `${(c.share_pct / max) * 100}%`,
                  background: corridorCss(c.corridor),
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
