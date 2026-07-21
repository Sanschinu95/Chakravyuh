import type { DefenseResult } from '../lib/api'
import { num } from '../lib/format'

/**
 * The executable answer: what to buy, from whom, on what hull, arriving when —
 * and the constraint that actually limits the plan, taken from the LP's dual
 * values rather than asserted.
 */
export default function PlanPanel({ result }: { result: DefenseResult }) {
  const p = result.procurement
  const spr = result.spr
  const cf = spr.counterfactual

  return (
    <>
      <div className="hero-row">
        <Hero v={`${p.coverage_pct}%`} u="gap covered" sub={`${p.status} in ${p.solve_ms}ms`} tone="ok" />
        <Hero
          v={`₹${num(p.cost_delta_inr_crore)}`}
          u="crore cost delta"
          sub={`$${p.cost_delta_usd_mn}M premium`}
          tone="warn"
        />
        <Hero
          v={p.first_delivery_day ? `D+${p.first_delivery_day}` : '—'}
          u="first cargo berths"
          sub={`${p.horizon_weeks}-week horizon`}
          tone="warn"
        />
      </div>

      <SectionLabel>Binding constraints — from LP dual values</SectionLabel>
      {p.binding.length === 0 && (
        <div className="micro">The plan is unconstrained at this shock size.</div>
      )}
      {p.binding.map((b) => (
        <div className="binding-row" key={b.constraint}>
          <div className="binding-top">
            <span className="binding-label">{b.label}</span>
            <span className="binding-price">${b.shadow_price_usd_bbl}/bbl</span>
          </div>
          <div className="binding-why">{b.explanation}</div>
        </div>
      ))}

      <SectionLabel>Procurement plan ({p.lines.length} lines)</SectionLabel>
      {p.lines.length === 0 && (
        <div className="micro">No feasible replacement cargoes within the horizon.</div>
      )}
      {p.lines.slice(0, 10).map((ln, i) => (
        <div className="line-row" key={`${ln.supplier_id}-${ln.refinery_id}-${ln.vessel_class}-${i}`}>
          <div className="line-top">
            <span className="line-grade">{ln.grade}</span>
            <span className="line-vol">{num(ln.volume_kb)} kb</span>
          </div>
          <div className="line-route">
            {ln.country} → {ln.refinery} · {ln.vessel_class}
          </div>
          <div className="line-meta">
            <span className="line-day">berths D+{ln.first_delivery_day}</span>
            <span>${ln.unit_cost_usd_bbl}/bbl</span>
            <span>
              API {ln.api_gravity}° S {ln.sulfur_pct}%
            </span>
          </div>
        </div>
      ))}

      <SectionLabel>Strategic reserve bridge</SectionLabel>
      <div className="kv">
        <span className="kv-k">Drawn over the shock</span>
        <span className="kv-v">{spr.total_drawn_mmbbl} mmbbl</span>
      </div>
      <div className="kv">
        <span className="kv-k">Buffer held at the end</span>
        <span className="kv-v" style={{ color: 'var(--ok)' }}>
          {spr.end_buffer_mmbbl} mmbbl
        </span>
      </div>
      <div className="kv">
        <span className="kv-k">Peak unserved after drawdown</span>
        <span className="kv-v">{num(spr.peak_unserved_kbd)} kbd</span>
      </div>
      {spr.by_site.map((s) => (
        <div className="site-row" key={s.site_id}>
          <span className="site-name">{s.site}</span>
          <div className="site-bar">
            <div className="site-fill" style={{ width: `${s.drawn_pct}%` }} />
          </div>
          <span className="site-val">{s.drawn_pct}%</span>
        </div>
      ))}

      <div className={`spr-verdict ${cf.exhausted_on_day ? 'bad' : 'ok'}`}>
        <strong>Counterfactual:</strong> meeting the shortfall in full from day one
        {cf.exhausted_on_day
          ? ` empties the reserve on day ${cf.exhausted_on_day}, before the shock ends.`
          : ' also survives this shock — the reserve is not the binding issue here.'}
      </div>

      <SectionLabel>Justification</SectionLabel>
      <div className="narration">
        {result.narration.text.split('\n\n').map((para, i) => (
          <p key={i}>{para}</p>
        ))}
        <div className={`narration-note ${result.narration.mode}`}>
          {result.narration.mode === 'llm' ? 'LLM narration' : 'deterministic fallback'}
          {' — '}
          {result.narration.model_note}
        </div>
      </div>

      <SectionLabel>Pipeline trace</SectionLabel>
      {result.trace.map((t) => (
        <div className="trace-row" key={t.step}>
          <span className="trace-ms">{t.elapsed_ms.toFixed(0)}ms</span>
          <span className="trace-step">{t.step}</span>
          <span className="trace-detail">{t.detail}</span>
        </div>
      ))}
    </>
  )
}

function Hero({ v, u, sub, tone }: { v: string; u: string; sub: string; tone: string }) {
  return (
    <div className="hero">
      <div className={`hero-v ${tone}`}>{v}</div>
      <div className="hero-u">{u}</div>
      <div className="hero-sub">{sub}</div>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="section-label">{children}</div>
}
