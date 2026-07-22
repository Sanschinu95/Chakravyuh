import { useCallback, useEffect, useState } from 'react'
import { api, type AttackSet, type Portfolio, type RedTeam } from '../lib/api'
import { num } from '../lib/format'

const fmtAttack = (a: AttackSet) =>
  a.attacks
    .map((x) => `${x.target} ${Math.round(x.severity * 100)}% × ${x.duration_days}d`)
    .join('  +  ')

/**
 * The two moats in one view: what the adversary found overnight, and what it
 * costs to blunt it while nothing is wrong.
 */
export default function RedTeamPanel() {
  const [rt, setRt] = useState<RedTeam | null>(null)
  const [pf, setPf] = useState<Portfolio | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback((refresh = false) => {
    setBusy(true)
    setErr(null)
    api
      .redteam(refresh)
      .then((r) => {
        setRt(r)
        return api.portfolio()
      })
      .then(setPf)
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false))
  }, [])

  useEffect(() => { load(false) }, [load])

  if (err) return <div className="empty">{err}</div>
  if (!rt) {
    return (
      <div className="empty">
        {busy
          ? 'Running the adversarial search — this puts every candidate attack through the full defense pipeline.'
          : 'No run yet.'}
      </div>
    )
  }

  const best = rt.best_attack

  return (
    <>
      <div className="cascade-head">
        <div className="cascade-name">Red team</div>
        <div className="cascade-sum">
          An adversary with a ${rt.budget_usd_mn}M budget, searching for the
          cheapest damage. Damage is measured by our own cascade and optimiser,
          not asserted by the model.
        </div>
        <div className="cascade-anchor">
          found by {rt.found_by.replace('_', ' ')} · {rt.generator}
          {rt.computed_at ? ` · ${rt.computed_at.slice(0, 16).replace('T', ' ')}` : ''}
        </div>
        <span className="tag prov-injected">injected / adversarial</span>
      </div>

      <div className="hero-row">
        <div className="hero">
          <div className={`hero-v ${rt.resilience_score < 40 ? 'crit' : rt.resilience_score < 70 ? 'warn' : 'ok'}`}>
            {rt.resilience_score}
          </div>
          <div className="hero-u">resilience</div>
          <div className="hero-sub">out of 100</div>
        </div>
        <div className="hero">
          <div className="hero-v crit">
            {best ? `${num(best.damage_per_dollar)}×` : '—'}
          </div>
          <div className="hero-u">damage / dollar</div>
          <div className="hero-sub">worst found</div>
        </div>
        <div className="hero">
          <div className="hero-v warn">{rt.agent_tested.length}</div>
          <div className="hero-u">experiments</div>
          <div className="hero-sub">agent-run</div>
        </div>
      </div>

      {best && (
        <div className="attack-box">
          <div className="attack-label">worst attack found</div>
          <div className="attack-name">{fmtAttack(best)}</div>
          <div className="attack-econ">
            <span>costs <strong>${best.cost_usd_mn}M</strong></span>
            <span>→ <strong className="crit-text">${best.damage_usd_bn}B</strong> damage</span>
          </div>
          <div className="attack-meta">
            {num(best.lost_kbd)} kbd of crude stops · our procurement covers only{' '}
            {best.coverage_pct}% · {best.unserved_pct}% of demand unserved
          </div>
        </div>
      )}

      {rt.agent_text && (
        <>
          <div className="section-label">Agent's conclusion</div>
          <div className="narration">
            {rt.agent_text.split('\n').filter(Boolean).slice(0, 6).map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
        </>
      )}

      {rt.agent_trace?.length > 0 && (
        <>
          <div className="section-label">Agent trace ({rt.agent_trace.length} tool calls)</div>
          {rt.agent_trace.map((t, i) => (
            <div className="trace-call" key={i}>
              <div className="trace-call-head">
                <span className="trace-tool">{t.tool}</span>
                {t.error && <span className="trace-err">error</span>}
              </div>
              <div className="trace-args">{JSON.stringify(t.input).slice(0, 150)}</div>
              <div className="trace-res">{t.result_preview.slice(0, 180)}</div>
            </div>
          ))}
        </>
      )}

      <div className="section-label">Other attacks the sweep found</div>
      {rt.baseline_top.slice(0, 4).map((a, i) => (
        <div className="line-row" key={i}>
          <div className="line-top">
            <span className="line-grade">{fmtAttack(a)}</span>
            <span className="line-vol">{num(a.damage_per_dollar)}×</span>
          </div>
          <div className="line-meta">
            <span>${a.cost_usd_mn}M</span>
            <span>${a.damage_usd_bn}B damage</span>
            <span>we cover {a.coverage_pct}%</span>
          </div>
        </div>
      ))}

      {/* ------------------------------------------------ portfolio ---- */}
      {pf && pf.status === 'OPTIMAL' && (
        <>
          <div className="section-label">Peacetime portfolio</div>
          <div className="headline-box">{pf.headline}</div>

          <div className="kv"><span className="kv-k">Spend</span>
            <span className="kv-v">${pf.spend_usd_mn}M of ${pf.budget_usd_mn}M</span></div>
          <div className="kv"><span className="kv-k">Expected loss, gross</span>
            <span className="kv-v">${num(pf.expected_loss_gross_usd_mn)}M</span></div>
          <div className="kv"><span className="kv-k">Expected loss, residual</span>
            <span className="kv-v">${num(pf.expected_loss_residual_usd_mn)}M</span></div>
          <div className="kv"><span className="kv-k">Leverage</span>
            <span className="kv-v" style={{ color: 'var(--ok)' }}>{pf.leverage}×</span></div>

          {pf.holdings.map((h) => (
            <div className="line-row" key={h.instrument_id}>
              <div className="line-top">
                <span className="line-grade">{h.units} × {h.instrument}</span>
                <span className="line-vol">${h.cost_usd_mn}M</span>
              </div>
              <div className="line-route">{h.category} · {h.unit_label}</div>
              <div className="micro">{h.mechanism}</div>
              {h.defends_against[0] && (
                <div className="line-meta">
                  <span className="line-day">
                    neutralises {h.defends_against[0].share_neutralised_pct}% of{' '}
                    {h.defends_against[0].attack.slice(0, 40)}
                  </span>
                </div>
              )}
            </div>
          ))}

          <div className="section-label">Residual exposure per attack</div>
          {pf.per_attack.map((a, i) => (
            <div className="kv" key={i}>
              <span className="kv-k" style={{ fontSize: 10 }}>{a.attack.slice(0, 40)}</span>
              <span className="kv-v">
                {a.neutralised_pct}% <span style={{ color: 'var(--text-faint)' }}>
                  / max {a.max_mitigable_pct}%
                </span>
              </span>
            </div>
          ))}

          <div className="honest-box">
            <div className="honest-label">assumptions</div>
            {pf.ceiling_note}
            <br /><br />
            {pf.probability_note}
          </div>
        </>
      )}

      <button className="btn-reset" style={{ marginTop: 12 }}
        onClick={() => load(true)} disabled={busy}>
        {busy ? 'searching…' : 're-run adversarial search (~2 min)'}
      </button>
    </>
  )
}
