import { useEffect, useState } from 'react'
import MapView from './components/MapView'
import TopBar from './components/TopBar'
import CorridorList from './components/CorridorList'
import CorridorDetail from './components/CorridorDetail'
import HonestyLegend from './components/HonestyLegend'
import { useEventStream } from './lib/useEventStream'
import {
  api,
  type CorridorSummary,
  type Legend,
  type NetworkPayload,
  type Summary,
} from './lib/api'

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [legend, setLegend] = useState<Legend | null>(null)
  const [network, setNetwork] = useState<NetworkPayload | null>(null)
  const [corridors, setCorridors] = useState<CorridorSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)

  const { connected } = useEventStream()

  useEffect(() => {
    Promise.all([api.summary(), api.legend(), api.network(), api.corridors()])
      .then(([s, l, n, c]) => {
        setSummary(s)
        setLegend(l)
        setNetwork(n)
        setCorridors(c)
      })
      .catch((e) => setBootError(String(e)))
  }, [])

  return (
    <div className="app">
      <TopBar summary={summary} connected={connected} />
      <div className="stage">
        <MapView
          network={network}
          selectedCorridor={selected}
          onSelectCorridor={setSelected}
        />

        <CorridorList
          corridors={corridors}
          selected={selected}
          onSelect={setSelected}
        />

        <div className="floating right-rail">
          <CorridorDetail corridor={selected} />
        </div>

        <HonestyLegend legend={legend} />

        {bootError && (
          <div
            className="panel floating"
            style={{ left: '50%', top: 90, transform: 'translateX(-50%)', width: 420 }}
          >
            <div className="panel-head">
              <span className="panel-title" style={{ color: 'var(--crit)' }}>
                Backend unreachable
              </span>
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
