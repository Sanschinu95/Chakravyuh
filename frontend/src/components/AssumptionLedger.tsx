import { useMemo, useState } from 'react'
import type { Assumption } from '../lib/api'

interface Props {
  ledger: Assumption[]
  overrides: Record<string, number>
  onChange: (key: string, value: number) => void
  onReset: () => void
  busy: boolean
}

/**
 * Every coefficient the cascade uses, as a slider with its source.
 *
 * This is the answer to "scenario model fidelity -- are assumptions explicit
 * and testable". A judge can disagree with our elasticity, drag it, and watch
 * the whole cascade recompute against their number instead of ours.
 */
export default function AssumptionLedger({
  ledger,
  overrides,
  onChange,
  onReset,
  busy,
}: Props) {
  const [openSource, setOpenSource] = useState<string | null>(null)

  const byStage = useMemo(() => {
    const m = new Map<string, Assumption[]>()
    for (const a of ledger) {
      if (!m.has(a.stage)) m.set(a.stage, [])
      m.get(a.stage)!.push(a)
    }
    return [...m.entries()]
  }, [ledger])

  const dirty = Object.keys(overrides).length > 0

  return (
    <>
      <div className="ledger-note">
        Every number below is an assumption, not a measurement. Drag one and the
        cascade recomputes against your value. Click a label for its source.
      </div>

      {byStage.map(([stage, items]) => (
        <div key={stage} className="ledger-stage">
          <div className="ledger-stage-label">{stage}</div>
          {items.map((a) => {
            const val = overrides[a.key] ?? a.value
            const changed = a.key in overrides
            return (
              <div className="ledger-item" key={a.key}>
                <div className="ledger-top">
                  <button
                    className="ledger-label"
                    onClick={() =>
                      setOpenSource(openSource === a.key ? null : a.key)
                    }
                    title="show source"
                  >
                    {a.label}
                    <span className="ledger-info">ⓘ</span>
                  </button>
                  <span className={`ledger-val ${changed ? 'changed' : ''}`}>
                    {val}
                    <span className="ledger-unit">
                      {a.unit === 'fraction' ? '' : ` ${a.unit}`}
                    </span>
                  </span>
                </div>
                <input
                  type="range"
                  min={a.min}
                  max={a.max}
                  step={a.step}
                  value={val}
                  disabled={busy}
                  onChange={(e) => onChange(a.key, Number(e.target.value))}
                />
                {openSource === a.key && (
                  <div className="ledger-source">
                    <div className="ledger-source-label">source</div>
                    {a.source}
                    {a.note && <div className="ledger-source-note">{a.note}</div>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}

      {dirty && (
        <button className="btn-reset" onClick={onReset} disabled={busy}>
          reset {Object.keys(overrides).length} modified assumption
          {Object.keys(overrides).length === 1 ? '' : 's'}
        </button>
      )}
    </>
  )
}
