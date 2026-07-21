import type { Legend } from '../lib/api'

/**
 * Rule 1 of the project. This panel is never hidden, including during the live
 * demo. `active` comes from the backend, so if a live feed's API key is absent
 * the legend downgrades the claim to IDLE rather than implying it is streaming.
 */
export default function HonestyLegend({ legend }: { legend: Legend | null }) {
  if (!legend) return null
  return (
    <>
      <div>
        {legend.entries.map((e) => (
          <div className="legend-row" key={e.key}>
            <span className="legend-swatch" style={{ background: e.color }} />
            <span className="legend-label">{e.label}</span>
            <span className={`legend-flag ${e.active ? 'active' : 'idle'}`}>
              {e.active ? 'ACTIVE' : 'IDLE'}
            </span>
          </div>
        ))}
        <div className="legend-note">{legend.disclosure}</div>
      </div>
    </>
  )
}
