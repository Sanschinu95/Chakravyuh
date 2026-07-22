import { useEffect, useState } from 'react'
import { api, type TenderPack } from '../lib/api'
import type { CustomShock } from './AttackConsole'

interface Props {
  scenarioId: string | null
  shocks: CustomShock[] | null
}

/** The last mile: the artifact a procurement officer could actually send. */
export default function TenderPanel({ scenarioId, shocks }: Props) {
  const [pack, setPack] = useState<TenderPack | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(0)

  useEffect(() => {
    if (!scenarioId && !shocks) {
      setPack(null)
      return
    }
    let live = true
    setBusy(true)
    setErr(null)
    api
      .tender(scenarioId ? { scenario_id: scenarioId } : { shocks: shocks! })
      .then((p) => live && setPack(p))
      .catch((e) => live && setErr(String(e)))
      .finally(() => live && setBusy(false))
    return () => { live = false }
  }, [scenarioId, shocks])

  if (!scenarioId && !shocks) {
    return (
      <div className="empty">
        Run a scenario or execute an attack, then the optimiser's plan is
        converted into draft procurement tenders here — grade specs, laycan
        windows and pricing basis included.
      </div>
    )
  }
  if (err) return <div className="empty">{err}</div>
  if (busy || !pack) return <div className="empty">drafting tenders…</div>

  return (
    <>
      <div className="cascade-head">
        <div className="cascade-name">Draft tenders</div>
        <div className="cascade-sum">
          Generated from the optimiser's plan. Quantities, laycan and pricing
          basis are computed; only the covering note is written by a model.
        </div>
        <div className="cascade-anchor">
          {pack.count} documents · cover note {pack.cover_note_mode} · {pack.generator}
        </div>
        <span className="tag prov-simulated">model output</span>
      </div>

      {pack.cover_note && (
        <>
          <div className="section-label">Covering note</div>
          <div className="narration">
            <p>{pack.cover_note}</p>
          </div>
        </>
      )}

      <div className="section-label">Documents</div>
      <div className="chip-row" style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
        {pack.tenders.map((t, i) => (
          <button
            key={t.tender_no}
            className={`chip ${open === i ? 'on' : ''}`}
            style={open === i
              ? { borderColor: 'var(--accent)', background: 'rgba(56,189,248,.12)', color: 'var(--accent)', width: 'auto' }
              : { width: 'auto' }}
            onClick={() => setOpen(i)}
          >
            {t.cargo.grade}
          </button>
        ))}
      </div>

      {pack.tenders[open] && (
        <>
          {!pack.tenders[open].quality.compatible && (
            <div className="spr-verdict bad">
              This cargo fails the buyer's crude diet and must not be issued.
            </div>
          )}
          <pre className="tender-doc">{pack.tenders[open].body}</pre>
        </>
      )}
    </>
  )
}
