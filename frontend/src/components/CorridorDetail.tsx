import { useEffect, useState } from 'react'
import { api, type CorridorDetail as Detail } from '../lib/api'
import { corridorCss, corridorLabel, num } from '../lib/format'

export default function CorridorDetail({ corridor }: { corridor: string | null }) {
  const [detail, setDetail] = useState<Detail | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!corridor) {
      setDetail(null)
      return
    }
    let live = true
    setErr(null)
    api
      .corridor(corridor)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setErr(String(e)))
    return () => {
      live = false
    }
  }, [corridor])

  if (!corridor) {
    return (
      <div className="empty">
        Select a corridor to inspect the grades that move through it, the
        chokepoints they transit, and the voyage times that bound how fast a
        replacement barrel can arrive.
      </div>
    )
  }

  return (
    <>
      <div className="cascade-head">
        <div
          className="cascade-name"
          style={{ color: corridorCss(corridor) }}
        >
          {corridorLabel(corridor)}
        </div>
        {detail && (
          <div className="cascade-sum">
            {num(detail.total_kb_week / 7)} kbd across{' '}
            {detail.suppliers.length} grades
          </div>
        )}
        <span className="tag" style={{ background: 'rgba(245,158,11,.14)', color: 'var(--curated)' }}>
          curated
        </span>
      </div>

      <div>
        {err && <div className="empty">{err}</div>}
        {!detail && !err && <div className="empty">loading…</div>}

        {detail && (
          <>
            <SectionLabel>Chokepoints on this corridor</SectionLabel>
            {detail.chokepoints.map((cp) => (
              <div className="supplier-item" key={cp.chokepoint_id}>
                <div className="supplier-top">
                  <span className="supplier-name">{cp.name}</span>
                  <span className="supplier-kbd" style={{ color: 'var(--crit)' }}>
                    {num(cp.exposure.exposed_kbd)} kbd
                  </span>
                </div>
                <div className="supplier-meta">
                  <span>{cp.global_oil_transit_mbd} mb/d global</span>
                  <span>
                    {cp.bypass_capacity_mbd > 0
                      ? `${cp.bypass_capacity_mbd} mb/d bypass`
                      : 'no bypass'}
                  </span>
                </div>
              </div>
            ))}

            <SectionLabel>Voyage time to India</SectionLabel>
            {Object.entries(detail.voyage_days_by_class).map(([cls, v]) => (
              <div className="kv" key={cls}>
                <span className="kv-k">{cls}</span>
                <span className="kv-v">
                  {v.min.toFixed(1)}–{v.max.toFixed(1)} days
                </span>
              </div>
            ))}

            <SectionLabel>
              Supplier grades ({detail.suppliers.length})
            </SectionLabel>
            {detail.suppliers.map((s) => (
              <div className="supplier-item" key={s.supplier_id}>
                <div className="supplier-top">
                  <span className="supplier-name">{s.grade}</span>
                  <span className="supplier-kbd">{num(s.kbd)} kbd</span>
                </div>
                <div className="supplier-meta">
                  <span>{s.country}</span>
                  <span>API {s.api_gravity}°</span>
                  <span>S {s.sulfur_pct}%</span>
                </div>
                <div
                  className="supplier-meta"
                  style={{ color: 'var(--text-faint)', fontSize: 9.5 }}
                >
                  <span>{s.pricing_formula}</span>
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 9.5,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: 'var(--text-faint)',
        margin: '14px 0 7px',
      }}
    >
      {children}
    </div>
  )
}
