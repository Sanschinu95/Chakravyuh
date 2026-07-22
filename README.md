# CHAKRAVYUH

An anticipatory energy supply-chain resilience system for India. It holds a digital twin of the country's crude import network — 21 supplier grades, 4 shipping corridors, 7 chokepoints, 12 refineries with their actual crude diets, 525 modelled voyages and 3 strategic reserve sites — and runs a deterministic five-stage cascade over it (supply gap, refinery runs, price, sector stress, macro), then defends against that cascade with two optimisers: a procurement LP that reallocates barrels subject to grade compatibility, liftability, tanker tonnage, voyage time and berth capacity, and an SPR drawdown LP that rations the reserve across the shock instead of spending it on day one. It is a war room rather than a watchtower: rather than waiting for a news feed to report a disruption, it attacks India's own supply chain nightly to find the cheapest way to hurt it, and prices the instruments to buy in peacetime against what it finds.

Four things distinguish it from a dashboard:

1. **Red team self-play.** `backend/agents/red_team.py` is given the simulator and the procurement LP as tools and a $50 mn attacker budget, and is scored on damage per dollar. It proposes; the solvers score. Damage is whatever the cascade and LP measure *after* the best defense runs, never a number the model asserted. An exhaustive-ish baseline sweep always runs and is the floor the LLM agent has to beat — the agent only "wins" if it beats the sweep on the metric.
2. **Peacetime portfolio.** `backend/solve/portfolio.py` takes the attacks the red team actually found and solves a MILP for the cheapest bundle of instruments — charter options, storage leases, term contracts, SPR tranches, refinery flex retrofits — to buy *today*. The output is a purchase list with a mechanism attached to each line, not a risk score.
3. **Self-grading.** `backend/eval/backtest.py` replays June 2025 day by day and reports the lead time and the Brier score, including when the Brier is bad. `backend/eval/calibration.py` compares the system's implied probability against a documented market proxy and flags disagreements in both directions. Both numbers are computed from the code, not asserted here.
4. **Tender as the last mile.** `backend/agents/tender.py` turns a solver line into a draft procurement tender: grade spec checked against the buying refinery's API/sulfur band, quantity from the LP, laycan window computed from the voyage, the supplier's real benchmark pricing formula, incoterm and payment terms. A recommendation a judge can read is worth less than a document a procurement officer could send.

---

## Quickstart

Python 3.13 and Node 20+. Tested on Windows with PowerShell; the shell commands are the only platform-specific part.

### 1. Environment and dependencies

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

There is **no `requirements.txt` in this repository**. Install the dependency set directly:

```powershell
pip install fastapi "uvicorn[standard]" pydantic python-dotenv duckdb pandas networkx ortools httpx yfinance groq anthropic
```

| Package | Used by |
|---|---|
| `fastapi`, `uvicorn[standard]`, `pydantic` | HTTP + WebSocket surface (`backend/app.py`, `backend/bus.py`) |
| `duckdb`, `pandas` | curated CSV store and typed accessors (`backend/data/loaders.py`) |
| `networkx` | the digital twin graph (`backend/sim/twin.py`) |
| `ortools` | GLOP (procurement LP, SPR LP) and SCIP (portfolio MILP) |
| `httpx` | GDELT and OFAC fetches; also required by `fastapi.testclient` |
| `yfinance` | Brent feed (`backend/data/market.py`) |
| `groq`, `anthropic` | optional LLM providers (`backend/agents/llm.py`) |
| `python-dotenv` | reads `.env` at import time in `backend/config.py` |

### 2. Seed the database

```powershell
python scripts/seed_db.py
```

This rebuilds `chakravyuh.duckdb` from `data_curated/*.csv`, recomputes import shares so they sum to 100, and creates the `grade_compatibility` view. It prints a sanity report: network summary, corridor exposure, graph node/edge counts, and the share of refinery-grade pairs that are feasible. **The API refuses to start without this file** — `backend/app.py` raises `chakravyuh.duckdb not found -- run python scripts/seed_db.py first` in its lifespan hook.

### 3. Run the nightly red team (recommended before any demo)

```powershell
python scripts/run_redteam.py
```

This writes `state/redteam.json`, which `/api/redteam` and `/api/portfolio` then serve **instantly**. It is deliberately a batch job: the search puts every candidate attack through the full cascade plus procurement LP, which is minutes of solver time.

**Without this artifact, the first `/api/redteam` call takes roughly 2 minutes**, and `/api/portfolio` calls `/api/redteam` internally, so it inherits the same cost. `state/` is gitignored, so a fresh clone has no artifact until you run the script. The API does not compute it at boot on purpose — even offloaded to worker threads, a multi-minute solver sweep degrades every other request while it runs.

Useful flags: `--budget` (attacker budget in $mn, default 50), `--portfolio-budget` (defender budget in $mn, default 220), `--quiet`.

### 4. Run the API

```powershell
uvicorn backend.app:app --port 8000
```

At boot it warms the graph cache and kicks off a background warm of the Corridor Risk Index (cold, that reaches three external feeds and takes ~18 s). Warm failures are logged and ignored.

### 5. Run the UI

```powershell
cd frontend
npm install
npm run dev
```

Vite serves on **port 5173** and proxies `/api` to `http://127.0.0.1:8000` and `/ws` to `ws://127.0.0.1:8000` (`frontend/vite.config.ts`), so the browser only ever talks to one origin.

### Optional: end-to-end check

```powershell
python scripts/smoke_test.py
```

Exercises every endpoint through `fastapi.testclient` and asserts the invariants that matter (grade compatibility on every recommended cargo, no instantaneous deliveries, coverage accounting reconciles, CRI bands agree with thresholds, no attack reported as fully neutralised, AIS never labelled live without a key). It runs the red team, so allow minutes if `state/redteam.json` is absent.

---

## Configuration

Create a `.env` at the repository root. It is read by `backend/config.py` at import time.

```ini
# Default LLM provider. Optional.
GROQ_API_KEY=...
LLM_PROVIDER=groq            # groq | anthropic  (default: groq)
GROQ_MODEL=openai/gpt-oss-120b        # tool-calling model, used by the red team
GROQ_FAST_MODEL=llama-3.3-70b-versatile   # bulk extraction and the tender cover note

# Alternative provider. Optional.
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-opus-4-8

# Live AIS. Optional — and not currently wired to a live reader (see below).
AISSTREAM_API_KEY=...
```

**Without any LLM key the system still runs end to end.** Every LLM call degrades to a deterministic path and the payload says which path ran:

| Component | With a key | Without a key |
|---|---|---|
| Narration (`agents/narrator.py`) | model prose over solver output, `mode: "llm"` | deterministic template over the *same* numbers, `mode: "deterministic"` |
| Red team (`agents/red_team.py`) | LLM agent proposes attacks and runs them via tools, `found_by: "llm_agent"` if it beats the sweep | brute-force candidate sweep only, `found_by: "baseline_search"` |
| Headline extraction (`intelligence/extractor.py`) | schema-guided labelling, `method: "llm"` | regex keyword rules, `method: "keyword"` — and this is the **default** even with a key, because the index must be deterministic |
| Tender cover note (`agents/tender.py`) | short covering note | omitted; the tender documents themselves are unchanged |

The tender body, every number in the narration, and every attack score are assembled deterministically in Python in all cases.

---

## API surface

All JSON. `backend/app.py` is the single source of truth.

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Status plus `llm_enabled`, `ais_enabled`, live WebSocket client count. |
| GET | `/api/legend` | The honesty legend: five provenance classes, their colours, and which are actually active this session. The UI renders it verbatim. |
| GET | `/api/summary` | Refinery count and capacity, supplier and route counts, import kbd, SPR volume and days of cover, corridor shares. |
| GET | `/api/network` | Everything the map needs: twin nodes and edges, the four corridor polylines with waypoint labels, and baseline supplier-to-port flow arcs. |
| GET | `/api/corridors` | The four corridors with kb/week, kbd, share of imports and supplier count. |
| GET | `/api/corridors/{corridor}` | Drill-down: suppliers with grade/API/sulfur/political risk, chokepoints with transit and bypass volumes plus exposure, voyage days by vessel class. 404 on an unknown corridor. |
| GET | `/api/refineries` | The 12 refineries with capacity, crude diet limits, Nelson complexity and the list of compatible grades. |
| GET | `/api/spr` | The three reserve sites, total and capacity mmbbl, days of cover, maximum aggregate drawdown rate. |
| GET | `/api/scenarios` | The named scenario library (7 entries), each with its shock list and historical anchor. |
| GET | `/api/assumptions` | The assumption ledger: every cascade coefficient with value, range, unit, stage and citation. Rendered as sliders. |
| POST | `/api/simulate` | Runs the five-stage cascade for a `scenario_id` or an arbitrary `shocks` list, with optional ledger `overrides`. Returns all five stages plus the resolved ledger. |
| GET | `/api/sourcing` | Country-level sourcing advisor: HHI concentration, spare liftable capacity, lead times, and a deterministic action per country. Pass `scenario_id` to see the picture under a disruption. |
| POST | `/api/defend` | The full defense pipeline: cascade → procurement LP → SPR bridge → narration, with a per-step timing trace. This is the path the demo stopwatch times. |
| GET | `/api/cri` | Corridor Risk Index for all four corridors, with nominal and effective weights, per-signal contributions and the evidence chain. `days` (default 7), `llm` (default false). 120 s TTL cache. |
| GET | `/api/cri/{corridor}` | One corridor with its full evidence chain, weighting rationale and input provenance. 404 on an unknown corridor. |
| GET | `/api/market` | Brent snapshot: last close, % change, 90-day series, 30/90-day realized volatility, spread against the 90-day mean, and the derived market-stress score. |
| GET | `/api/vessels` | AIS snapshot plus detected anomalies (dark near chokepoint, loitering, anchorage cluster) with the rule definitions and weights. REPLAY on this deployment. |
| GET | `/api/backtest` | June 2025 replay: lead time in hours, the daily series, the Brier score with its base-rate reference and skill score, and a plain-English interpretation. 600 s TTL cache. |
| GET | `/api/calibration` | Reliability curve for the system's probabilities against a realized-vol market proxy, with disagreement flags and the proxy's caveats. 600 s TTL cache. |
| POST | `/api/tender` | Runs the pipeline (narration skipped) and drafts procurement tenders from the largest LP lines, each with a rendered fixed-format body. |
| GET | `/api/redteam` | The latest adversarial run. Serves `state/redteam.json` instantly if present; `refresh=true` recomputes (minutes). `budget` in $mn, default 50. |
| GET | `/api/portfolio` | Peacetime instruments priced against the red team's discovered attacks. `budget` in $mn, default 220. Depends on `/api/redteam`. |
| GET | `/api/events` | The last `n` events from the in-process bus (default 100), for clients that connect late or cannot hold a socket. |
| WS | `/ws` | Live event stream. On connect the last 60 events are replayed so a late client is not blind. |

Event topics published to the bus: `pipeline.start`, `pipeline.cascade`, `pipeline.procurement`, `pipeline.spr`, `pipeline.narration`, `pipeline.complete`, `cascade.complete`, `redteam.complete`. Every event carries a `provenance` tag and, where applicable, a `run_id`.

---

## Data provenance and honesty

Rule 1 of this project: anything the UI shows carries a tag saying where it came from. The vocabulary is defined once, in `backend/config.py`, and every record that crosses the API boundary is stamped with one of these five classes.

| Class | Label | Colour | Meaning |
|---|---|---|---|
| `live` | LIVE FEED | green | Fetched from an external feed **this session**. |
| `curated` | CURATED / STATIC | amber | Static reference data loaded from `data_curated/*.csv`. |
| `replay` | REPLAYED ARCHIVE | blue | An archive replayed on a clock. Never relabelled as live, not even partially. |
| `simulated` | MODEL OUTPUT | purple | Produced by our own simulator, solvers or index arithmetic. |
| `injected` | INJECTED / TEST | red | Injected by a human operator or the red team agent. |

`/api/legend` returns which classes are *active* in the running session, so a missing key downgrades the claim rather than faking it.

### What is actually real

| Feed | Status on this deployment |
|---|---|
| **Brent** (`data/market.py`) | Genuine live fetch via `yfinance` (`BZ=F`). A successful fetch is LIVE and is written to `data_replay/brent_cache.csv`. If the fetch fails, the cache is served and tagged REPLAY with an explicit "this is NOT a live quote" note. If neither is available, `available: false` — no price is invented. |
| **OFAC SDN** (`data/sanctions.py`) | Genuine live download of the public SDN CSV export, parsed for the maritime slice. Success is LIVE; failure falls back to `data_replay/ofac_cache.json` tagged REPLAY; total failure with no cache sets `available: false`, and the CRI then **drops the sanctions component and renormalises** rather than scoring an unjustified zero. |
| **GDELT** (`data/gdelt.py`) | Fetch-first against DOC 2.0, but the public API is frequently rate-limited or blocked from lab and corporate networks, so in practice this usually falls back to the June 2025 replay archive. The payload's `provenance` is the only source of truth for which path was taken. |
| **AIS** (`data/ais_stream.py`) | REPLAY only. There is no live AIS reader wired into this build. Even with `AISSTREAM_API_KEY` set, the payload still serves the replay snapshot and says so in plain text — it does not upgrade the label. |

### The June 2025 corpus and Brent path are reconstructions

This is the most important disclosure in the project, and it is stated in the code as well as here.

* `data_replay/june2025_gdelt.jsonl` is a **reconstruction**, not a real news archive. The dates and the *sequence* of events track the real US/Israel-Iran escalation; the individual headline strings are paraphrases written for this archive, not verbatim wire copy. Every record carries `corpus: "reconstructed"`, sources are generic channel labels (`wire-agency`, `shipping-press`) rather than named outlets, and URLs use a `replay://` scheme so nothing can be mistaken for a citable source.
* `data_replay/june2025_brent.csv` is a **reconstructed daily settlement path**. It tracks the shape of the real market — a quiet May, a build through 10–12 June, a ~8% single-session gap on 13 June — but the individual closes are a reconstruction for replay, not an exchange settlement record.
* `data_replay/june2025_ais_snapshots/vessels.json` is a deterministically generated (seeded) snapshot. Positions, hull names and MMSIs are plausible but synthetic.

Everything reconstructed is tagged REPLAY, and both the backtest and the calibration payloads carry the disclosure text inline under `sources`.

### The curated dataset

`data_curated/*.csv` are **plausible approximations assembled from public sources, not audited data**. They are tagged CURATED, never LIVE.

| File | Rows | Contents |
|---|---|---|
| `suppliers.csv` | 21 | Grade, country, region, API gravity, sulfur, benchmark and pricing formula, load port and coordinates, max liftable kbd, spot premium, political risk. |
| `refineries.csv` | 12 | Operator, state, coordinates, capacity, API min/max, sulfur max, Nelson complexity, primary port, berth capacity, product shares. |
| `routes.csv` | 525 | Supplier × discharge port × vessel class, with distance, voyage days, cargo size and the chokepoints transited. |
| `chokepoints.csv` | 7 | Hormuz, Bab el-Mandeb, Suez, Cape, Malacca, Bosphorus, Danish Straits — with global transit mb/d and bypass capacity. |
| `imports_baseline.csv` | 21 | Barrels per week per supplier, corridor and typical discharge port. Shares are recomputed at seed time. |
| `spr_sites.csv` | 3 | Visakhapatnam, Mangaluru, Padur — capacity, fill, maximum drawdown rate, notional grade. |
| `freight.csv` | 16 | USD/bbl and Worldscale by route family and vessel class. |
| `tanker_availability.csv` | 16 | Prompt and 30-day hull counts by region and class, with cargo size. |
| `corridor_waypoints.csv` | 31 | Polyline geometry for the four corridors. |

Seeded, this produces a network of 4,630 kbd of crude imports across 12 refineries totalling 4,147 kbd of capacity, with 39.1 mmbbl of strategic reserve (8.4 days of import cover) and a graph of 57 nodes and 207 edges. Corridor exposure: Hormuz 42.98%, Cape 29.37%, Red Sea/Suez 20.95%, Malacca 6.70%.

---

## Known limitations

Stated plainly, because a system that only reports its good numbers is not a measurement system.

**The headline Brier score is bad, and the reason is structural.** On the June 2025 replay the full-window Brier is **0.4643** against a base-rate reference of 0.1262 — a skill score of **−2.68**, i.e. materially worse than a forecaster who predicted the period's base rate every day. The cause is a mismatch between what the index measures and what the outcome variable asks. The CRI measures the *level* of corridor risk. The outcome is "does Brent gap another 5% within 72 hours". After the 13 June gap the index correctly stays red — corridor risk really was extreme, the parliament closure vote was still ahead — but no second single-session gap follows, so every one of those high-confidence days scores as a false alarm. Restricted to the onset sub-window (through the spike day, 13 scored days) the Brier is **0.1488** against a 0.1775 reference, a skill score of **+0.16**. Both windows are in the payload; the full window is the headline number and is not hidden.

**The lead time is real but the margin is thin.** CRI(Hormuz) first closed at or above the 62.0 alert threshold on 2025-06-11 at **62.1** — a margin of **0.1 points** — and Brent posted its first ≥5% single-session move on 2025-06-13 (+7.93%). That is a 48-hour lead. A threshold moved by a fraction of a point, or a slightly different news decay half-life, would change the alert day. The threshold was not tuned to manufacture a crossing, and if the index had never crossed the payload would report a null lead time.

**The backtest runs on two of four signal classes.** There is no June 2025 AIS archive and no June 2025 OFAC snapshot on this deployment, so those components are dropped and the CRI renormalises over news (0.583) and market (0.417). Substituting today's AIS snapshot would be lookahead and a provenance lie.

**The "market-implied" probability is a realized-vol proxy, not implied vol.** Brent options surfaces are not available here, so `eval/calibration.py` models log price as driftless Brownian motion with sigma set to trailing 30-day realized volatility and applies the reflection principle for the running maximum. It has no drift term, uses realized rather than implied volatility (so it lags a repricing by construction and carries no volatility risk premium), and is symmetric in a market whose option skew is not. It is a reference point, not a market quote.

**Portfolio attack probabilities are a modelling assumption, not a forecast.** `optimise_portfolio` scales probabilities from damage-per-dollar, peaking at 12% for the cheapest-damage attack. There is no frequency estimate behind that number, and the payload says so in `probability_note`.

**The mitigation ceiling is an assumption too, and a deliberately conservative one.** No attack can be more than 45% mitigated by purchased instruments, falling with severity so a total chokepoint closure caps near 27%. That number is a judgement about what optionality can physically do, not a measurement.

**The cascade is deterministic and unmitigated by construction.** It is the "we did nothing clever" counterfactual — no probability distributions, no Monte Carlo, no confidence intervals. Its value is that dragging an assumption slider produces a real relationship rather than noise; its cost is that it reports a point estimate for something genuinely uncertain. Every coefficient it uses is in the assumption ledger with a range and a source, and every one is adjustable through `/api/simulate`.

**Instrument costs, attacker costs and instrument mitigation coefficients are indicative.** Annualised charter, storage and term-contract costs are drawn from published market ranges. Attacker costs (`ATTACK_COSTS` in `red_team.py`) encode a judgement that mining an anchorage is cheap and sustaining a naval closure is not; they are not sourced.

**`/api/legend` reports the LIVE class as active only when an AIS key is configured.** Brent and OFAC can be live independently of AIS, so on a network where those two fetches succeed the legend understates rather than overstates what is live. Each payload's own `provenance` field is exact; the legend's `active` flag is a coarse session-level summary.

---

## Data sources

All figures below are approximate and were used to build the curated dataset. None of it is audited, and none of it is a substitute for the primary source.

| Domain | Source |
|---|---|
| Chokepoint transit volumes and bypass capacity | EIA, *World Oil Transit Chokepoints* (2024). Hormuz bypass is taken as Saudi East-West 5.0 mb/d plus UAE ADCOP 1.5 mb/d; SUMED parallels Suez at 2.5 mb/d. |
| India crude import baseline, supplier mix, discharge ports | PPAC and UN Comtrade-style import statistics, approximated to a 21-grade slate. |
| Global liquids supply (103 mb/d), used to convert India's lost barrels into a world price move | IEA *Oil Market Report*. |
| Oil price elasticity and the GDP impact of an oil shock | Hamilton (2009); IMF *WEO* (Oct 2023) oil-shock box; RBI Bulletin pass-through estimates for India. |
| Refinery crude diets, turndown limits, Nelson complexity | Operator disclosures and standard refining engineering practice. |
| Freight rates and tanker availability | Published Worldscale and prompt-tonnage market ranges. |
| Re-routing response lag | Observed charterer behaviour during the Red Sea diversions, Dec 2023 – Feb 2024. |
| Chokepoint risk premium | Brent premium observed during the June 2025 US-Iran standoff and the Sep 2019 Abqaiq strike. |
| Sanctions signal | OFAC SDN public export, maritime slice. |

Every coefficient the cascade uses carries its own citation inline in `backend/sim/assumptions.py` and is exposed at `/api/assumptions`.

---

## Repository layout

```
backend/
  config.py            provenance vocabulary, keys, domain constants
  bus.py               in-process event bus + WebSocket hub
  app.py               FastAPI surface
  data/                loaders (DuckDB), gdelt, market, sanctions, ais_stream
  sim/                 twin (networkx), simulator (5-stage cascade), assumptions, scenarios
  solve/               procurement_lp (GLOP), spr (GLOP), portfolio (SCIP), pipeline, regions
  agents/              llm (provider-agnostic), narrator, red_team, tender
  intelligence/        cri, extractor, sourcing
  eval/                backtest, calibration
data_curated/          the 9 curated CSVs — CURATED
data_replay/           June 2025 reconstructions and live-feed caches — REPLAY
scripts/               seed_db, run_redteam, smoke_test, gen_routes
state/                 red team artifact (gitignored)
frontend/              React + deck.gl + MapLibre, Vite on 5173
```

See `ARCHITECTURE.md` for the component diagram, the LP and MILP formulations, the CRI weighting, and the two design rules the code enforces.

## Map boundaries

The basemap (CARTO, built on OpenStreetMap) renders Jammu & Kashmir and Ladakh
with dashed "disputed" lines, placing Aksai Chin and Pakistan-administered
Kashmir outside India. That is not the boundary recognised in India.

CHAKRAVYUH therefore **hides every administrative boundary layer** in the
basemap (`boundary_country_outline`, `boundary_country_inner`,
`boundary_state`, `boundary_county`). This is a maritime supply-chain tool —
corridors, chokepoints, ports and refineries carry the analysis, and land
borders carry none of it — so drawing no boundary is preferable to drawing an
incorrect one.

### Showing an authoritative national outline

To render India's official boundary instead, place a GeoJSON
`FeatureCollection` at:

```
frontend/public/india-boundary.geojson
```

It is picked up automatically on the next load; no code change and no rebuild
of the layer logic is needed. If the file is absent, malformed, or not served
as JSON, the map simply shows no boundary.

Source it from an authoritative publisher — Survey of India, or a dataset on
data.gov.in that carries the official depiction. **Do not** use a generic
world-countries GeoJSON from an international source: those reproduce the same
depiction the basemap does, which is the problem this setting exists to solve.
