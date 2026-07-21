import type { CorridorSummary } from '../lib/api'
import { corridorCss, corridorLabel } from '../lib/format'

export interface LayerVisibility {
  corridors: boolean
  flows: boolean
  refineries: boolean
  suppliers: boolean
  chokepoints: boolean
  spr: boolean
  labels: boolean
}

export const DEFAULT_LAYERS: LayerVisibility = {
  corridors: true,
  flows: true,
  refineries: true,
  suppliers: false,
  chokepoints: true,
  spr: true,
  labels: true,
}

const LAYER_META: Array<{ key: keyof LayerVisibility; label: string; hint: string }> = [
  { key: 'corridors', label: 'Corridor paths', hint: 'shipping lanes' },
  { key: 'flows', label: 'Import arcs', hint: 'supplier → discharge port' },
  { key: 'chokepoints', label: 'Chokepoints', hint: 'Hormuz, Bab el-Mandeb…' },
  { key: 'refineries', label: 'Refineries', hint: '12 Indian refineries' },
  { key: 'spr', label: 'Strategic reserve', hint: '3 SPR caverns' },
  { key: 'suppliers', label: 'Supplier origins', hint: '21 loading terminals' },
  { key: 'labels', label: 'Refinery labels', hint: 'text on map' },
]

interface Props {
  layers: LayerVisibility
  onLayers: (l: LayerVisibility) => void
  corridors: CorridorSummary[]
  filter: Set<string>
  /** Takes an updater so consecutive clicks compose instead of clobbering. */
  onFilter: (update: (prev: Set<string>) => Set<string>) => void
}

/**
 * Map density controls. Corridor filtering is the important one: with all four
 * corridors drawn at once the map is unreadable, so these chips isolate one
 * lane at a time and everything else on the map dims to match.
 */
export default function LayerControls({
  layers,
  onLayers,
  corridors,
  filter,
  onFilter,
}: Props) {
  const allOn = filter.size === 0

  // Clicking a corridor while everything is shown isolates it — that is what
  // "keep them distinguished" means in practice. Clicking further corridors
  // adds them back, and clearing the last one returns to showing all.
  const toggleCorridor = (c: string) => {
    onFilter((prev) => {
      if (prev.size === 0) return new Set([c])
      const next = new Set(prev)
      if (next.has(c)) next.delete(c)
      else next.add(c)
      return next
    })
  }

  const soloCorridor = (c: string) => onFilter(() => new Set([c]))

  return (
    <>
      <div className="ctl-label">
        {allOn ? 'Corridors — click to isolate' : `Showing ${filter.size} of 4`}
        {!allOn && (
          <button className="ctl-clear" onClick={() => onFilter(() => new Set())}>
            show all
          </button>
        )}
      </div>
      <div className="chip-row">
        {corridors.map((c) => {
          const on = allOn || filter.has(c.corridor)
          return (
            <button
              key={c.corridor}
              className={`chip ${on ? 'on' : ''}`}
              style={{
                borderColor: on ? corridorCss(c.corridor) : 'var(--border)',
                background: on ? `${corridorCss(c.corridor)}22` : 'transparent',
                color: on ? corridorCss(c.corridor) : 'var(--text-faint)',
              }}
              onClick={() => toggleCorridor(c.corridor)}
              onDoubleClick={() => soloCorridor(c.corridor)}
              title={`${c.share_pct}% of imports — click to toggle, double-click to isolate`}
            >
              <span
                className="chip-dot"
                style={{ background: corridorCss(c.corridor) }}
              />
              {corridorLabel(c.corridor)}
              <span className="chip-pct">{c.share_pct.toFixed(0)}%</span>
            </button>
          )
        })}
      </div>

      <div className="ctl-label" style={{ marginTop: 12 }}>
        Map layers
      </div>
      {LAYER_META.map((m) => (
        <label className="switch-row" key={m.key}>
          <input
            type="checkbox"
            checked={layers[m.key]}
            onChange={(e) => onLayers({ ...layers, [m.key]: e.target.checked })}
          />
          <span className="switch-label">{m.label}</span>
          <span className="switch-hint">{m.hint}</span>
        </label>
      ))}
    </>
  )
}
