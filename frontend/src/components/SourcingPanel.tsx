import { useEffect, useState } from 'react'
import { api, type SourcingView } from '../lib/api'
import { num } from '../lib/format'

const ACTION_TONE: Record<string, string> = {
  'replace now': 'crit',
  reduce: 'crit',
  'diversify route': 'warn',
  increase: 'ok',
  hold: 'dim',
}

/**
 * Country relations desk: who we depend on, how exposed that makes us, who has
 * spare barrels, and how many days ahead an order has to be placed.
 */
export default function SourcingPanel({ scenarioId }: { scenarioId: string | null }) {
  const [data, setData] = useState<SourcingView | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setErr(null)
    api
      .sourcing(scenarioId ?? undefined)
      .then((d) => live && setData(d))
      .catch((e) => live && setErr(String(e)))
    return () => {
      live = false
    }
  }, [scenarioId])

  if (err) return <div className="empty">{err}</div>
  if (!data) return <div className="empty">loading…</div>

  const c = data.concentration

  return (
    <>
      <div className="cascade-head">
        <div className="cascade-name">Country sourcing advisor</div>
        <div className="cascade-sum">
          {data.under_disruption
            ? 'Availability reduced by the active scenario — advice reflects who can actually deliver.'
            : 'Peacetime picture. Run a scenario to see this re-rank under disruption.'}
        </div>
        <span className={`tag ${data.under_disruption ? 'prov-simulated' : ''}`}
          style={
            data.under_disruption
              ? undefined
              : { background: 'rgba(245,158,11,.14)', color: 'var(--curated)' }
          }
        >
          {data.under_disruption ? 'model output' : 'curated'}
        </span>
      </div>

      <div className="hero-row">
        <div className="hero">
          <div className={`hero-v ${c.hhi > 2500 ? 'crit' : c.hhi > 1500 ? 'warn' : 'ok'}`}>
            {num(c.hhi)}
          </div>
          <div className="hero-u">HHI</div>
          <div className="hero-sub">{c.verdict}</div>
        </div>
        <div className="hero">
          <div className="hero-v warn">{c.top3_share_pct}%</div>
          <div className="hero-u">top 3 countries</div>
          <div className="hero-sub">of all imports</div>
        </div>
        <div className="hero">
          <div className="hero-v">{data.countries.length}</div>
          <div className="hero-u">counterparties</div>
          <div className="hero-sub">{num(data.total_import_kbd)} kbd</div>
        </div>
      </div>

      <div className="micro" style={{ marginBottom: 10 }}>{c.note}</div>

      <div className="section-label">Corridor concentration</div>
      {Object.entries(c.corridor_share_pct).map(([k, v]) => (
        <div className="kv" key={k}>
          <span className="kv-k">{k.replace('_', ' / ')}</span>
          <span className="kv-v" style={{ color: v > 35 ? 'var(--crit)' : undefined }}>
            {v}%
          </span>
        </div>
      ))}

      <div className="section-label">Countries — click for grades</div>
      {data.countries.map((r) => {
        const rec = r.recommendation
        const tone = ACTION_TONE[rec.action] ?? 'dim'
        const isOpen = open === r.country
        return (
          <div className="country-row" key={r.country}>
            <button
              className="country-head"
              onClick={() => setOpen(isOpen ? null : r.country)}
            >
              <span className="country-name">{r.country}</span>
              <span className={`country-action ${tone}`}>{rec.action}</span>
            </button>
            <div className="country-bar">
              <div
                className="country-fill"
                style={{ width: `${Math.min(100, r.share_pct * 2.2)}%` }}
              />
            </div>
            <div className="country-meta">
              <span>{num(r.current_kbd)} kbd</span>
              <span>{r.share_pct}%</span>
              <span>spare {num(r.spare_kbd)}</span>
              <span>risk {r.political_risk}</span>
              <span className="country-lead">D-{r.lead_time_days.toFixed(0)}</span>
            </div>
            <div className="country-why">{rec.rationale}</div>
            {r.blocked_kbd > 0 && (
              <div className="country-blocked">
                {num(r.blocked_kbd)} kbd blocked by the active shock
              </div>
            )}
            {isOpen && (
              <div className="country-grades">
                {r.grades.map((g) => (
                  <div className="grade-row" key={g.supplier_id}>
                    <span className="grade-name">{g.grade}</span>
                    <span className="grade-meta">
                      API {g.api_gravity}° · S {g.sulfur_pct}% ·{' '}
                      {g.compatible_refineries} refineries · {g.fastest_days}d ·{' '}
                      {num(g.spare_kbd)} kbd spare
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}
