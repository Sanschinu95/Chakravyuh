import { useEffect, useMemo, useRef, useState } from 'react'
import type { BusEvent } from '../lib/useEventStream'

const STAGES = [
  { topic: 'pipeline.cascade', label: 'Cascade', hint: 'supply gap → refinery runs → price → GDP' },
  { topic: 'pipeline.procurement', label: 'Procurement LP', hint: 'grade, tonnage, voyage, berth constraints' },
  { topic: 'pipeline.spr', label: 'SPR bridge', hint: 'rationing the reserve until cargoes land' },
  { topic: 'pipeline.narration', label: 'Justification', hint: 'explaining the solver output' },
]

interface Props {
  running: boolean
  events: BusEvent[]
  label?: string
}

/**
 * Progress while the defense pipeline runs.
 *
 * Each stage lights up from a real event the backend publishes as it finishes,
 * not a timer pretending to be progress. The stopwatch is the number the whole
 * project is judged on, so it counts actual elapsed milliseconds.
 */
export default function PipelineOverlay({ running, events, label }: Props) {
  const [ms, setMs] = useState(0)
  const startedAt = useRef<number | null>(null)
  const startIndex = useRef(0)

  useEffect(() => {
    if (!running) {
      startedAt.current = null
      return
    }
    startedAt.current = performance.now()
    startIndex.current = events.length
    setMs(0)
    const id = window.setInterval(() => {
      if (startedAt.current !== null) setMs(performance.now() - startedAt.current)
    }, 53)
    return () => window.clearInterval(id)
    // events is intentionally excluded: we only snapshot its length at start
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])

  // Only count stage events published since this run began. The bus also
  // carries pipeline.start/complete and unrelated topics; counting those would
  // drive the progress bar to 100% before the last stage had finished.
  const done = useMemo(() => {
    const topics = new Set(STAGES.map((s) => s.topic))
    const seen = new Set<string>()
    for (const e of events.slice(startIndex.current)) {
      if (topics.has(e.topic)) seen.add(e.topic)
    }
    return seen
  }, [events])

  if (!running) return null

  const current = STAGES.findIndex((s) => !done.has(s.topic))

  return (
    <div className="pipe-overlay" role="status" aria-live="polite">
      <div className="pipe-card">
        <div className="pipe-head">
          <span className="pipe-mark">CHAKRAVYUH</span>
          <span className="pipe-clock">{(ms / 1000).toFixed(1)}s</span>
        </div>
        <div className="pipe-sub">
          {label ?? 'Analysing'} — signal to executable plan
        </div>

        <div className="pipe-stages">
          {STAGES.map((s, i) => {
            const state =
              done.has(s.topic) ? 'done' : i === current ? 'active' : 'pending'
            return (
              <div className={`pipe-stage ${state}`} key={s.topic}>
                <span className="pipe-dot">
                  {state === 'done' ? '✓' : state === 'active' ? '' : ''}
                </span>
                <span className="pipe-stage-label">{s.label}</span>
                <span className="pipe-stage-hint">{s.hint}</span>
              </div>
            )
          })}
        </div>

        <div className="pipe-bar">
          <div
            className="pipe-bar-fill"
            style={{ width: `${(done.size / STAGES.length) * 100}%` }}
          />
        </div>
        <div className="pipe-foot">
          Real solvers running — OR-Tools linear programs over grade
          compatibility, tanker tonnage and voyage time.
        </div>
      </div>
    </div>
  )
}
