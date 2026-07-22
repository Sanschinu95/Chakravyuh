import { useEffect, useState } from 'react'
import { api, type Backtest, type Calibration } from '../lib/api'

/**
 * The system grading itself. Shows the lead time it achieved and the Brier
 * score it earned — including when that score is bad. A self-grading system
 * that only publishes flattering numbers is marketing, not evaluation.
 */
export default function GradePanel() {
  const [bt, setBt] = useState<Backtest | null>(null)
  const [cal, setCal] = useState<Calibration | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    Promise.all([api.backtest(), api.calibration()])
      .then(([b, c]) => {
        if (!live) return
        setBt(b)
        setCal(c)
      })
      .catch((e) => live && setErr(String(e)))
    return () => { live = false }
  }, [])

  if (err) return <div className="empty">{err}</div>
  if (!bt) return <div className="empty">running backtest…</div>

  const good = (bt.brier_skill_score ?? -1) > 0

  return (
    <>
      <div className="cascade-head">
        <div className="cascade-name">Self-grading</div>
        <div className="cascade-sum">{bt.event}</div>
        <div className="cascade-anchor">
          {bt.window?.[0]} → {bt.window?.[1]}
        </div>
        <span className="tag prov-replay">replayed archive</span>
      </div>

      <div className="hero-row">
        <div className="hero">
          <div className="hero-v ok">
            {bt.lead_time_hours != null ? `${bt.lead_time_hours}h` : '—'}
          </div>
          <div className="hero-u">lead time</div>
          <div className="hero-sub">before the spike</div>
        </div>
        <div className="hero">
          <div className={`hero-v ${good ? 'ok' : 'crit'}`}>
            {bt.brier_score?.toFixed(3) ?? '—'}
          </div>
          <div className="hero-u">Brier score</div>
          <div className="hero-sub">lower is better</div>
        </div>
        <div className="hero">
          <div className="hero-v warn">
            {bt.spike_pct != null ? `${bt.spike_pct}%` : '—'}
          </div>
          <div className="hero-u">Brent spike</div>
          <div className="hero-sub">{bt.spike_day}</div>
        </div>
      </div>

      <div className="section-label">Detection</div>
      <div className="kv"><span className="kv-k">Alert raised</span>
        <span className="kv-v">{bt.alert_day} at {bt.alert_score}</span></div>
      <div className="kv"><span className="kv-k">Threshold margin</span>
        <span className="kv-v" style={{ color: (bt.alert_margin ?? 0) < 1 ? 'var(--warn)' : undefined }}>
          +{bt.alert_margin}
        </span></div>
      <div className="kv"><span className="kv-k">Spike definition</span>
        <span className="kv-v" style={{ fontSize: 9.5 }}>{bt.spike_definition}</span></div>
      <div className="micro">{bt.lead_note}</div>

      <div className="section-label">Scoring</div>
      <div className="kv"><span className="kv-k">Brier (full window)</span>
        <span className="kv-v">{bt.brier_score?.toFixed(4)}</span></div>
      <div className="kv"><span className="kv-k">Base-rate reference</span>
        <span className="kv-v">{bt.brier_reference_base_rate?.toFixed(4)}</span></div>
      <div className="kv"><span className="kv-k">Skill score</span>
        <span className="kv-v" style={{ color: good ? 'var(--ok)' : 'var(--crit)' }}>
          {bt.brier_skill_score?.toFixed(2)}
        </span></div>
      <div className="kv"><span className="kv-k">Days scored</span>
        <span className="kv-v">{bt.scored_days}</span></div>

      {bt.brier_interpretation && (
        <div className="honest-box">
          <div className="honest-label">why this number is what it is</div>
          {bt.brier_interpretation}
        </div>
      )}

      {bt.signals_excluded && bt.signals_excluded.length > 0 && (
        <div className="micro" style={{ color: 'var(--warn)' }}>
          Excluded from the backtest: {bt.signals_excluded.join(', ')} — no June
          2025 archive exists, and substituting today's snapshot would be
          lookahead.
        </div>
      )}

      {cal && (
        <>
          <div className="section-label">Calibration — predicted vs observed</div>
          <ReliabilityChart cal={cal} />
          <div className="micro">{cal.market_proxy?.formula}</div>
          {(cal.market_proxy?.caveats ?? []).map((c, i) => (
            <div className="micro" key={i}>· {c}</div>
          ))}
          {cal.flags?.length > 0 && (
            <>
              <div className="section-label">
                Disagreements with the market ({cal.flags.length})
              </div>
              {cal.flags.slice(0, 5).map((f, i) => (
                <div className="kv" key={i}>
                  <span className="kv-k">{String(f.date ?? `flag ${i + 1}`)}</span>
                  <span className="kv-v" style={{ fontSize: 9.5 }}>
                    {f.direction.replace(/_/g, ' ')}
                  </span>
                </div>
              ))}
            </>
          )}
        </>
      )}
    </>
  )
}

/** Reliability diagram: perfect calibration is the diagonal. */
function ReliabilityChart({ cal }: { cal: Calibration }) {
  const pts = (cal.reliability_curve ?? []).filter(
    (p) => p.observed != null && p.predicted != null,
  )
  const W = 240, H = 150, PAD = 26
  const x = (v: number) => PAD + v * (W - PAD - 8)
  const y = (v: number) => H - PAD - v * (H - PAD - 8)

  return (
    <svg className="relchart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label="reliability diagram">
      <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)}
        stroke="var(--border-bright)" strokeDasharray="3 3" />
      <line x1={PAD} y1={y(0)} x2={W - 8} y2={y(0)} stroke="var(--border)" />
      <line x1={PAD} y1={y(0)} x2={PAD} y2={8} stroke="var(--border)" />
      <text x={PAD} y={H - 8} fill="var(--text-faint)" fontSize="7">0</text>
      <text x={W - 16} y={H - 8} fill="var(--text-faint)" fontSize="7">1</text>
      <text x={6} y={y(1) + 4} fill="var(--text-faint)" fontSize="7">1</text>
      <text x={W / 2 - 20} y={H - 1} fill="var(--text-faint)" fontSize="7">
        predicted
      </text>
      {pts.length > 1 && (
        <polyline
          fill="none"
          stroke="var(--accent)"
          strokeWidth="1.5"
          points={pts.map((p) => `${x(p.predicted)},${y(p.observed!)}`).join(' ')}
        />
      )}
      {pts.map((p, i) => (
        <circle key={i} cx={x(p.predicted)} cy={y(p.observed!)} r="2.5"
          fill="var(--accent)" />
      ))}
    </svg>
  )
}
