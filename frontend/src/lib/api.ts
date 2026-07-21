// Typed client for the CHAKRAVYUH backend. Every payload carries `provenance`
// so the UI can never render a number without knowing where it came from.

export type Provenance = 'live' | 'curated' | 'replay' | 'simulated' | 'injected'

export const PROVENANCE_RGB: Record<Provenance, [number, number, number]> = {
  live: [34, 197, 94],
  curated: [245, 158, 11],
  replay: [59, 130, 246],
  simulated: [168, 85, 247],
  injected: [239, 68, 68],
}

export interface LegendEntry {
  key: Provenance
  label: string
  color: string
  active: boolean
}
export interface Legend {
  entries: LegendEntry[]
  disclosure: string
}

export interface Summary {
  refinery_count: number
  refining_capacity_kbd: number
  supplier_count: number
  route_count: number
  import_kbd: number
  spr_mmbbl: number
  spr_days_cover: number
  corridor_shares: Record<string, number>
  provenance: Provenance
}

export interface NetworkNode {
  id: string
  kind: 'supplier' | 'corridor' | 'chokepoint' | 'port' | 'refinery' | 'spr'
  key: string
  label: string
  lat: number
  lon: number
  provenance: Provenance
  [k: string]: unknown
}

export interface CorridorPath {
  corridor: string
  path: [number, number][]
  labels: string[]
  baseline_kb_week: number
  provenance: Provenance
}

export interface Flow {
  supplier_id: string
  grade: string
  country: string
  corridor: string
  from: [number, number]
  to: [number, number]
  kb_week: number
  share_pct: number
  provenance: Provenance
}

export interface NetworkPayload {
  nodes: NetworkNode[]
  edges: unknown[]
  corridor_paths: CorridorPath[]
  flows: Flow[]
  provenance: Provenance
}

export interface CorridorSummary {
  corridor: string
  label: string
  kb_week: number
  kbd: number
  share_pct: number
  supplier_count: number
  provenance: Provenance
}

export interface CorridorSupplier {
  supplier_id: string
  grade: string
  country: string
  api_gravity: number
  sulfur_pct: number
  kb_week: number
  kbd: number
  load_port: string
  pricing_formula: string
  political_risk: number
}

export interface ChokepointDetail {
  chokepoint_id: string
  name: string
  lat: number
  lon: number
  global_oil_transit_mbd: number
  bypass_capacity_mbd: number
  exposure: {
    chokepoint: string
    corridors: string[]
    suppliers: string[]
    exposed_kb_week: number
    exposed_kbd: number
  }
}

export interface CorridorDetail {
  corridor: string
  suppliers: CorridorSupplier[]
  chokepoints: ChokepointDetail[]
  voyage_days_by_class: Record<string, { min: number; max: number; mean: number }>
  total_kb_week: number
  provenance: Provenance
}

export interface Refinery {
  refinery_id: string
  name: string
  operator: string
  state: string
  lat: number
  lon: number
  capacity_kbd: number
  api_min: number
  api_max: number
  sulfur_max_pct: number
  nelson_complexity: number
  primary_port: string
  compatible_grades: string[]
  compatible_count: number
  provenance: Provenance
}

export interface SprPayload {
  sites: Array<{
    site_id: string
    site: string
    lat: number
    lon: number
    capacity_mmbbl: number
    fill_pct: number
    max_drawdown_kbd: number
  }>
  total_mmbbl: number
  total_capacity_mmbbl: number
  days_cover: number
  max_drawdown_kbd: number
  provenance: Provenance
}

export interface Health {
  status: string
  llm_enabled: boolean
  ais_enabled: boolean
  ws_clients: number
}

// ---------------------------------------------------------------- phase 2
export interface ShockDef {
  kind: string
  target: string
  severity: number
  duration_days: number
  start_day: number
  label: string
}

export interface Scenario {
  id: string
  name: string
  summary: string
  severity_label: string
  historical_anchor: string
  shocks: ShockDef[]
}

export interface Assumption {
  key: string
  label: string
  value: number
  min: number
  max: number
  step: number
  unit: string
  stage: string
  source: string
  note: string
  overridden: boolean
}

export interface CascadeHeadline {
  net_lost_kbd: number
  lost_pct_of_imports: number
  refinery_cut_kbd: number
  refineries_tripped: number
  brent_usd: number
  brent_delta_pct: number
  unserved_pct_of_demand: number
  gdp_loss_usd_bn: number
  total_cost_usd_bn: number
  duration_days: number
  spr_days_at_this_gap: number
  spr_exhausted: boolean
}

export interface CascadeStage {
  stage: number
  name: string
  [k: string]: unknown
}

export interface CascadeResult {
  shocks: ShockDef[]
  assumptions: Record<string, number>
  stages: CascadeStage[]
  headline: CascadeHeadline
  provenance: Provenance
  ledger: Assumption[]
  meta: {
    scenario_id: string | null
    name: string
    summary: string
    historical_anchor: string | null
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${await res.text()}`)
  return (await res.json()) as T
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${res.statusText}`)
  return (await res.json()) as T
}

export const api = {
  health: () => get<Health>('/api/health'),
  legend: () => get<Legend>('/api/legend'),
  summary: () => get<Summary>('/api/summary'),
  network: () => get<NetworkPayload>('/api/network'),
  corridors: () => get<CorridorSummary[]>('/api/corridors'),
  corridor: (id: string) => get<CorridorDetail>(`/api/corridors/${id}`),
  refineries: () => get<Refinery[]>('/api/refineries'),
  spr: () => get<SprPayload>('/api/spr'),
  scenarios: () => get<Scenario[]>('/api/scenarios'),
  assumptions: () => get<Assumption[]>('/api/assumptions'),
  simulate: (body: {
    scenario_id?: string
    shocks?: Omit<ShockDef, 'label' | 'start_day'>[]
    overrides?: Record<string, number>
  }) => post<CascadeResult>('/api/simulate', body),
}
