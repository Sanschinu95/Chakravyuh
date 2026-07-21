import { useCallback, useEffect, useRef, useState } from 'react'
import MapView from './components/MapView'
import TopBar from './components/TopBar'
import CorridorList from './components/CorridorList'
import CorridorDetail from './components/CorridorDetail'
import HonestyLegend from './components/HonestyLegend'
import ScenarioPanel from './components/ScenarioPanel'
import CascadePanel from './components/CascadePanel'
import AssumptionLedger from './components/AssumptionLedger'
import { useEventStream } from './lib/useEventStream'
import {
  api,
  type Assumption,
  type CascadeResult,
  type CorridorSummary,
  type Legend,
  type NetworkPayload,
  type Scenario,
  type Summary,
} from './lib/api'

type RightTab = 'cascade' | 'assumptions' | 'corridor'

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
  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const [running, setRunning] = useState(false)
  const [tab, setTab] = useState<RightTab>('corridor')
  const [bootError, setBootError] = useState<string | null>(null)

  const { connected } = useEventStream()

  useEffect(() => {
    Promise.all([
      api.summary(),
      api.legend(),
      api.network(),
      api.corridors(),
      api.scenarios(),
      api.assumptions(),
    ])
      .then(([s, l, n, c, sc, as]) => {
        setSummary(s)
        setLegend(l)
        setNetwork(n)
        setCorridors(c)
        setScenarios(sc)
        setLedger(as)
      })
      .catch((e) => setBootError(String(e)))
  }, [])

  // Re-running on every slider tick would hammer the backend; debounce so the
  // drag feels live but only the settled value is simulated.
  const debounce = useRef<number | undefined>(undefined)

  const runScenario = useCallback(
    (scenarioId: string, ov: Record<string, number>) => {
      setRunning(true)
      api
        .simulate({ scenario_id: scenarioId, overrides: ov })
        .then((r) => {
          setCascade(r)
          setLedger(r.ledger)
          setTab('cascade')
        })
        .catch((e) => setBootError(String(e)))
        .finally(() => setRunning(false))
    },
    [],
  )

  const onRun = (id: string) => {
    setActiveScenario(id)
    setSelected(null)
    runScenario(id, overrides)
  }

  const onClear = () => {
    setActiveScenario(null)
    setCascade(null)
    setTab('corridor')
  }

  const onAssumptionChange = (key: string, value: number) => {
    const next = { ...overrides, [key]: value }
    setOverrides(next)
    if (!activeScenario) return
    window.clearTimeout(debounce.current)
    debounce.current = window.setTimeout(() => runScenario(activeScenario, next), 220)
  }

  const onAssumptionReset = () => {
    setOverrides({})
    if (activeScenario) runScenario(activeScenario, {})
  }

  const onSelectCorridor = (c: string | null) => {
    setSelected(c)
    if (c) setTab('corridor')
  }

  return (
    <div className="app">
      <TopBar summary={summary} connected={connected} />
      <div className="stage">
        <MapView
          network={network}
          selectedCorridor={selected}
          onSelectCorridor={onSelectCorridor}
        />

        <div className="floating left-rail">
          <ScenarioPanel
            scenarios={scenarios}
            activeId={activeScenario}
            running={running}
            onRun={onRun}
            onClear={onClear}
          />
          <CorridorList
            corridors={corridors}
            selected={selected}
            onSelect={onSelectCorridor}
          />
        </div>

        <div className="floating right-rail">
          <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div className="tabs">
              <Tab id="corridor" tab={tab} set={setTab} label="Corridor" />
              <Tab id="cascade" tab={tab} set={setTab} label="Cascade" dot={!!cascade} />
              <Tab
                id="assumptions"
                tab={tab}
                set={setTab}
                label="Assumptions"
                dot={Object.keys(overrides).length > 0}
              />
              {running && <span className="tab-busy">running…</span>}
            </div>

            <div className="panel-body scroll" style={{ flex: 1, minHeight: 0 }}>
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

              {tab === 'assumptions' && (
                <AssumptionLedger
                  ledger={ledger}
                  overrides={overrides}
                  onChange={onAssumptionChange}
                  onReset={onAssumptionReset}
                  busy={running}
                />
              )}
            </div>
          </div>
        </div>

        <HonestyLegend legend={legend} />

        {bootError && (
          <div
            className="panel floating"
            style={{ left: '50%', top: 90, transform: 'translateX(-50%)', width: 440 }}
          >
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

function Tab({
  id,
  tab,
  set,
  label,
  dot,
}: {
  id: RightTab
  tab: RightTab
  set: (t: RightTab) => void
  label: string
  dot?: boolean
}) {
  return (
    <button className={`tab ${tab === id ? 'on' : ''}`} onClick={() => set(id)}>
      {label}
      {dot && <span className="tab-dot" />}
    </button>
  )
}
