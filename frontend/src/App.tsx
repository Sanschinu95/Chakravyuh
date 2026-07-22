import { useCallback, useEffect, useRef, useState } from 'react'
import MapView from './components/MapView'
import TopBar from './components/TopBar'
import CorridorList from './components/CorridorList'
import CorridorDetail from './components/CorridorDetail'
import HonestyLegend from './components/HonestyLegend'
import ScenarioPanel from './components/ScenarioPanel'
import CascadePanel from './components/CascadePanel'
import AssumptionLedger from './components/AssumptionLedger'
import PlanPanel from './components/PlanPanel'
import SourcingPanel from './components/SourcingPanel'
import Collapsible from './components/Collapsible'
import IntelPanel from './components/IntelPanel'
import GradePanel from './components/GradePanel'
import RedTeamPanel from './components/RedTeamPanel'
import TenderPanel from './components/TenderPanel'
import AttackConsole, { type CustomShock } from './components/AttackConsole'
import LayerControls, {
  DEFAULT_LAYERS,
  type LayerVisibility,
} from './components/LayerControls'
import { useEventStream } from './lib/useEventStream'
import {
  api,
  type Assumption,
  type CascadeResult,
  type CorridorSummary,
  type DefenseResult,
  type Legend,
  type NetworkPayload,
  type Scenario,
  type Summary,
} from './lib/api'

type RightTab =
  | 'corridor' | 'cascade' | 'plan' | 'tender' | 'sourcing'
  | 'intel' | 'grade' | 'redteam' | 'assumptions'

const TABS: Array<{ id: RightTab; label: string }> = [
  { id: 'intel', label: 'Risk' },
  { id: 'corridor', label: 'Corridor' },
  { id: 'cascade', label: 'Cascade' },
  { id: 'plan', label: 'Plan' },
  { id: 'tender', label: 'Tender' },
  { id: 'sourcing', label: 'Sourcing' },
  { id: 'redteam', label: 'Red team' },
  { id: 'grade', label: 'Grade' },
  { id: 'assumptions', label: 'Assumptions' },
]

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [legend, setLegend] = useState<Legend | null>(null)
  const [network, setNetwork] = useState<NetworkPayload | null>(null)
  const [corridors, setCorridors] = useState<CorridorSummary[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [ledger, setLedger] = useState<Assumption[]>([])

  const [selected, setSelected] = useState<string | null>(null)
  const [activeScenario, setActiveScenario] = useState<string | null>(null)
  const [cascade, setCascade] = useState<CascadeResult | null>(null)
  const [defense, setDefense] = useState<DefenseResult | null>(null)
  const [customShocks, setCustomShocks] = useState<CustomShock[] | null>(null)
  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState<number | null>(null)
  const [tab, setTab] = useState<RightTab>('corridor')
  const [bootError, setBootError] = useState<string | null>(null)

  const [layers, setLayers] = useState<LayerVisibility>(DEFAULT_LAYERS)
  const [corridorFilter, setCorridorFilter] = useState<Set<string>>(new Set())
  const [railOpen, setRailOpen] = useState(true)

  const { connected } = useEventStream()

  // The backend may still be booting (or reloading) when the page first
  // paints. Without a retry the dashboard silently stays empty, so keep
  // trying with backoff before surfacing an error.
  useEffect(() => {
    let cancelled = false

    const boot = async (attempt = 0): Promise<void> => {
      try {
        const [s, l, n, c, sc, as] = await Promise.all([
          api.summary(),
          api.legend(),
          api.network(),
          api.corridors(),
          api.scenarios(),
          api.assumptions(),
        ])
        if (cancelled) return
        setSummary(s)
        setLegend(l)
        setNetwork(n)
        setCorridors(c)
        setScenarios(sc)
        setLedger(as)
        setBootError(null)
      } catch (e) {
        if (cancelled) return
        if (attempt < 6) {
          setBootError(`Backend not ready — retrying (${attempt + 1}/6)…`)
          const delay = Math.min(4000, 500 * 2 ** attempt)
          window.setTimeout(() => void boot(attempt + 1), delay)
        } else {
          setBootError(String(e))
        }
      }
    }

    void boot()
    return () => {
      cancelled = true
    }
  }, [])

  const debounce = useRef<number | undefined>(undefined)

  // Cascade only — used for the live slider drag, which must stay cheap.
  const runScenario = useCallback((id: string, ov: Record<string, number>) => {
    setRunning(true)
    api
      .simulate({ scenario_id: id, overrides: ov })
      .then((r) => {
        setCascade(r)
        setLedger(r.ledger)
      })
      .catch((e) => setBootError(String(e)))
      .finally(() => setRunning(false))
  }, [])

  // Full defense pipeline: cascade -> LP -> SPR bridge -> narration.
  const runDefense = useCallback((id: string, ov: Record<string, number>) => {
    setRunning(true)
    setElapsed(null)
    const t0 = performance.now()
    api
      .defend({ scenario_id: id, overrides: ov })
      .then((r) => {
        setDefense(r)
        setCascade(r.cascade)
        setLedger(r.ledger)
        setElapsed(performance.now() - t0)
        setTab('plan')
      })
      .catch((e) => setBootError(String(e)))
      .finally(() => setRunning(false))
  }, [])

  // Judge-as-adversary: an operator-built shock runs the identical pipeline.
  const runAttack = useCallback((shocks: CustomShock[], ov: Record<string, number>) => {
    setRunning(true)
    setElapsed(null)
    const t0 = performance.now()
    api
      .defend({ shocks, overrides: ov })
      .then((r) => {
        setDefense(r)
        setCascade(r.cascade)
        setLedger(r.ledger)
        setElapsed(performance.now() - t0)
        setTab('plan')
      })
      .catch((e) => setBootError(String(e)))
      .finally(() => setRunning(false))
  }, [])

  const onRun = (id: string) => {
    setActiveScenario(id)
    setCustomShocks(null)
    setSelected(null)
    runDefense(id, overrides)
  }

  const onExecuteAttack = (shocks: CustomShock[]) => {
    setActiveScenario(null)
    setCustomShocks(shocks)
    setSelected(null)
    runAttack(shocks, overrides)
  }

  const onClear = () => {
    setActiveScenario(null)
    setCustomShocks(null)
    setCascade(null)
    setDefense(null)
    setElapsed(null)
    setTab('corridor')
  }

  const onAssumptionChange = (key: string, value: number) => {
    const next = { ...overrides, [key]: value }
    setOverrides(next)
    if (!activeScenario) return
    window.clearTimeout(debounce.current)
    debounce.current = window.setTimeout(() => runScenario(activeScenario, next), 220)
  }

  const onSelectCorridor = (c: string | null) => {
    setSelected(c)
    if (c) setTab('corridor')
  }

  return (
    <div className="app">
      <TopBar summary={summary} connected={connected} />

      <div className={`stage ${railOpen ? '' : 'rail-collapsed'}`}>
        {/* ---------------------------------------------------- left rail */}
        <aside className="rail rail-left scroll">
          <Collapsible title="View" defaultOpen>
            <LayerControls
              layers={layers}
              onLayers={setLayers}
              corridors={corridors}
              filter={corridorFilter}
              onFilter={setCorridorFilter}
            />
          </Collapsible>

          <Collapsible
            title="Scenarios"
            badge={activeScenario ? 'active' : undefined}
            defaultOpen
          >
            <ScenarioPanel
              scenarios={scenarios}
              activeId={activeScenario}
              running={running}
              onRun={onRun}
              onClear={onClear}
            />
          </Collapsible>

          <Collapsible
            title="Attack console"
            badge={customShocks ? 'live' : undefined}
            defaultOpen={false}
          >
            <AttackConsole
              corridors={corridors}
              running={running}
              onExecute={onExecuteAttack}
            />
          </Collapsible>

          <Collapsible title="Corridor exposure" defaultOpen={false}>
            <CorridorList
              corridors={corridors}
              selected={selected}
              onSelect={onSelectCorridor}
            />
          </Collapsible>

          <Collapsible title="Honesty legend" defaultOpen={false}>
            <HonestyLegend legend={legend} />
          </Collapsible>
        </aside>

        {/* -------------------------------------------------------- map */}
        <div className="map-cell">
          <MapView
            network={network}
            selectedCorridor={selected}
            onSelectCorridor={onSelectCorridor}
            layers={layers}
            corridorFilter={corridorFilter}
          />
          <button
            className="rail-toggle"
            onClick={() => setRailOpen(!railOpen)}
            title={railOpen ? 'hide side panel' : 'show side panel'}
          >
            {railOpen ? '‹' : '›'}
          </button>
        </div>

        {/* --------------------------------------------------- right rail */}
        <aside className="rail rail-right">
          <div className="tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`tab ${tab === t.id ? 'on' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
                {t.id === 'cascade' && cascade && <span className="tab-dot" />}
                {t.id === 'plan' && defense && <span className="tab-dot" />}
                {t.id === 'assumptions' && Object.keys(overrides).length > 0 && (
                  <span className="tab-dot" />
                )}
              </button>
            ))}
            {running && <span className="tab-busy">running…</span>}
            {!running && elapsed !== null && (
              <span className="tab-clock" title="signal to executable plan">
                {(elapsed / 1000).toFixed(1)}s
              </span>
            )}
          </div>

          <div className="rail-body scroll">
            {tab === 'corridor' && <CorridorDetail corridor={selected} />}

            {tab === 'cascade' &&
              (cascade ? (
                <>
                  <div className="cascade-head">
                    <div className="cascade-name">{cascade.meta.name}</div>
                    <div className="cascade-sum">{cascade.meta.summary}</div>
                    {cascade.meta.historical_anchor && (
                      <div className="cascade-anchor">
                        ↳ {cascade.meta.historical_anchor}
                      </div>
                    )}
                    <span className="tag prov-simulated">model output</span>
                  </div>
                  <CascadePanel result={cascade} />
                </>
              ) : (
                <div className="empty">
                  Pick a scenario to propagate a shock through supply gap,
                  refinery runs, price, sector stress and GDP.
                </div>
              ))}

            {tab === 'plan' &&
              (defense ? (
                <>
                  <div className="cascade-head">
                    <div className="cascade-name">Executable procurement plan</div>
                    <div className="cascade-sum">
                      Optimiser output for {defense.meta.name}. Every line respects
                      the destination refinery's crude diet, tanker availability
                      and voyage time.
                    </div>
                    <span className="tag prov-simulated">solver output</span>
                  </div>
                  <PlanPanel result={defense} />
                </>
              ) : (
                <div className="empty">
                  Run a scenario to generate a procurement plan, an SPR bridge
                  schedule, and the binding constraint that limits them.
                </div>
              ))}

            {tab === 'tender' && (
              <TenderPanel scenarioId={activeScenario} shocks={customShocks} />
            )}

            {tab === 'sourcing' && <SourcingPanel scenarioId={activeScenario} />}

            {tab === 'intel' && <IntelPanel />}

            {tab === 'redteam' && <RedTeamPanel />}

            {tab === 'grade' && <GradePanel />}

            {tab === 'assumptions' && (
              <AssumptionLedger
                ledger={ledger}
                overrides={overrides}
                onChange={onAssumptionChange}
                onReset={() => {
                  setOverrides({})
                  if (activeScenario) runScenario(activeScenario, {})
                }}
                busy={running}
              />
            )}
          </div>
        </aside>

        {bootError && (
          <div className="boot-error panel">
            <div className="panel-head">
              <span className="panel-title" style={{ color: 'var(--crit)' }}>
                Backend error
              </span>
              <button className="btn-ghost" onClick={() => setBootError(null)}>
                dismiss
              </button>
            </div>
            <div className="panel-body" style={{ fontSize: 11.5, lineHeight: 1.6 }}>
              <div style={{ color: 'var(--text-dim)', marginBottom: 8 }}>{bootError}</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-faint)' }}>
                python scripts/seed_db.py
                <br />
                uvicorn backend.app:app --port 8000
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
