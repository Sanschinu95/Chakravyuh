import { useEffect, useState } from 'react'
import { api, type CriSnapshot } from '../lib/api'
import { corridorLabel } from '../lib/format'

const BAND_TONE: Record<string, string> = { green: 'ok', amber: 'warn', red: 'crit' }

/**
 * Corridor Risk Index with the evidence one click deep — the four fused signal
 * classes, their weights, and the actual events and anomalies driving each
 * score. The weighting is shown because an index nobody can audit is a
 * number, not intelligence.
 */
export default function IntelPanel() {
  const [d, setD] = useState<CriSnapshot | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    api.cri().then((x) => live && setD(x)).catch((e) => live && setErr(String(e)))
    return () => { live = false }
  }, [])

  if (err) return <div className="empty">{err}</div>
  if (!d) return <div className="empty">computing corridor risk…</div>

  return (
    <>
      <div className="cascade-head">
        <div className="cascade-name">Corridor Risk Index</div>
        <div className="cascade-sum">
          Four signal classes fused into a 0–100 score per corridor. Alert
          threshold {d.thresholds.red}; amber from {d.thresholds.amber}.
        </div>
        <div className="cascade-anchor">as of {d.as_of}</div>
        <span className="tag prov-replay">replay + live feeds</span>
      </div>

      <div className="section-label">Weighting</div>
      <div className="weight-row">
        {Object.entries(d.weights).map(([k, v]) => (
          <div className="weight-chip" key={k}>
            <span className="weight-k">{k}</span>
            <span className="weight-v">{(v * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
      <div className="micro">{d.weighting_rationale}</div>

      <div className="section-label">Corridors — click for evidence</div>
      {d.corridors.map((c) => {
        const isOpen = open === c.corridor
        const tone = BAND_TONE[c.band] ?? 'dim'
        return (
          <div className="cri-row" key={c.corridor}>
            <button className="cri-head" onClick={() => setOpen(isOpen ? null : c.corridor)}>
              <span className="cri-name">{corridorLabel(c.corridor)}</span>
              <span className={`cri-score ${tone}`}>{c.score.toFixed(1)}</span>
              <span className={`country-action ${tone}`}>{c.band}</span>
            </button>
            <div className="cri-bar">
              <div
                className={`cri-fill ${tone}`}
                style={{ width: `${Math.min(100, c.score)}%` }}
              />
              <div
                className="cri-threshold"
                style={{ left: `${d.thresholds.red}%` }}
                title={`alert threshold ${d.thresholds.red}`}
              />
            </div>

            {c.unavailable_signals?.length > 0 && (
              <div className="micro" style={{ color: 'var(--warn)' }}>
                {c.unavailable_signals.join(', ')} unavailable — remaining weights
                renormalised, not scored as zero risk
              </div>
            )}

            {isOpen && (
              <div className="cri-evidence">
                {c.components.map((comp) => (
                  <div className="kv" key={comp.signal}>
                    <span className="kv-k">
                      {comp.signal}{' '}
                      <span style={{ color: 'var(--text-faint)' }}>
                        ×{(comp.weight * 100).toFixed(0)}%
                      </span>
                    </span>
                    <span className="kv-v">{comp.contribution?.toFixed(1)}</span>
                  </div>
                ))}

                {!!c.evidence?.event_count && (
                  <>
                    <div className="section-label">
                      News events ({c.evidence.event_count})
                    </div>
                    {(c.evidence.events ?? []).slice(0, 5).map((e, i) => (
                      <div className="ev-row" key={i}>
                        <span className="ev-date">{e.date}</span>
                        <span className="ev-title">{e.title}</span>
                      </div>
                    ))}
                  </>
                )}

                {!!c.evidence?.anomaly_count && (
                  <>
                    <div className="section-label">
                      AIS anomalies ({c.evidence.anomaly_count})
                    </div>
                    {(c.evidence.anomalies ?? []).slice(0, 4).map((a, i) => (
                      <div className="ev-row" key={i}>
                        <span className="ev-title">
                          {String(a.kind ?? a.type ?? 'anomaly')} —{' '}
                          {String(a.name ?? a.mmsi ?? '')}
                        </span>
                      </div>
                    ))}
                  </>
                )}

                {c.supplier_disruption_prob?.length > 0 && (
                  <>
                    <div className="section-label">Supplier disruption probability</div>
                    {c.supplier_disruption_prob.slice(0, 6).map((s) => (
                      <div className="kv" key={s.supplier_id}>
                        <span className="kv-k">{s.grade ?? s.supplier_id}</span>
                        <span className="kv-v">
                          {(s.probability * 100).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}
