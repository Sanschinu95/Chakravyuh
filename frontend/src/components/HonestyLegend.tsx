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
        {legend.feeds && legend.feeds.length > 0 && (
          <>
            <div className="ctl-label" style={{ marginTop: 12 }}>
              Feed status this session
            </div>
            {legend.feeds.map((f) => (
              <div className="legend-row" key={f.feed}>
                <span
                  className="legend-swatch"
                  style={{ background: f.live ? 'var(--live)' : 'var(--replay)' }}
                />
                <span className="legend-label">{f.feed}</span>
                <span className={`legend-flag ${f.live ? 'active' : 'idle'}`}>
                  {f.live ? 'LIVE' : 'REPLAY'}
                </span>
              </div>
            ))}
            {legend.feeds
              .filter((f) => !f.live)
              .map((f) => (
                <div className="micro" key={f.feed}>
                  {f.feed}: {f.note}
                </div>
              ))}
          </>
        )}
        <div className="legend-note">{legend.disclosure}</div>
      </div>
    </>
  )
}
