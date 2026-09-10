# RouteMind - phase progress

**Audit date:** 2026-09-10
**Method:** repository inspection + executed tests + live HTTP probes. Nothing below is
marked complete because a file exists; each claim names the evidence.
**Checkpoint:** git `ac8ae53` - working Phase 1 preserved before any Phase 2+ change.

Status vocabulary: **DONE** / **PARTIAL** / **NOT STARTED** / **BLOCKED**.

---

## Verified baseline (what actually runs today)

| Check | Result |
| --- | --- |
| Backend unit tests | `Ran 46 tests ... OK` |
| Endpoint selftest | `24 passed, 0 failed` |
| Live server | `/api/health` 200, `/api/overview` 200 (14.3 KB), `/api/map` 200 (34.9 KB), `/api/inventory` 200, `/api/alerts` 200 |
| Frontend build / typecheck | **N/A** - no build step. Plain HTML/CSS/JS, no TypeScript, no bundler. Validated with `node --check` on all 14 JS files. |
| Codebase size | 4,778 lines Python (26 files), 3,413 lines JS (14 files), 1,131 lines HTML+CSS |

---

## Phase map

### PHASE 1 - Control room frontend --- **DONE**
Nine views, operational map with pan/zoom/click, KPIs, charts, drawer, drill.
All tests green. One caveat inherited by Phase 3 (see below): offline, the roads
drawn on the map are straight lines, not real geometry.

### PHASE 2 - Backend + database --- **NOT STARTED**
Evidence: `grep -rl 'sqlite3|psycopg|sqlalchemy|CREATE TABLE|alembic' app/` returns
**nothing**. `grep -rn 'role|auth|login|token|permission'` returns **nothing**.

- Storage is in-memory dicts on a `Store` singleton, rebuilt from `seed.py` at every start.
- **Restarting the server destroys everything**: field reports, accepted reroutes,
  alert acknowledgements, simulation history.
- No users, no roles, no authentication, no authorization.
- No migrations, no pagination, no persisted timestamps.
- `app/fastapi_app.py` exists as an optional adapter, but FastAPI is not installed.

### PHASE 3 - Real GIS + routing --- **PARTIAL (~45%)**
Working: genuine OSRM integration (`/route/v1/driving/...?alternatives=true`),
per-feed provenance, risk-aware alternative scoring, 6 km block-proximity logic.

**Problem found during audit:** `app/data/snapshot.json` contains only `_meta`,
`weather` and `seismic` keys. There is **no cached road geometry**. So whenever OSRM
is unreachable, corridors fall back to straight-line interpolation between city
coordinates (`provenance: fallback-geometry`). The map looks like a road network but
offline it is 12 straight lines. This is currently labelled in the UI, but it must be
fixed by bundling real OSM geometry.

Also missing: road-segment entities, nearest-road lookup, spatial queries, district
polygons and containment, true route/incident geometric intersection (today it is a
point-to-line distance approximation in `geo.py`).

### PHASE 4 - Real data + disruption intelligence --- **PARTIAL (~55%)**
Strong already: Open-Meteo forecast, Open-Meteo elevation, USGS earthquakes, OSRM,
optional TomTom. Every feed carries provenance, TTL caching, one retry, and a snapshot
fallback - which is exactly Phase 4's honesty requirement.

Missing: historical disaster dataset, road-condition source, real vehicle GPS (fleet
positions are simulated ticks), per-source update-frequency metadata, and a *normalized*
disruption-signal pipeline - signals are currently computed ad hoc inside
`services/incidents.py` and `store.py`.

### PHASE 5 - ML risk prediction --- **NOT STARTED**
`heuristic-v1` exists and is honestly labelled as not-ML everywhere it appears.
There is no dataset, no feature engineering, no training or evaluation code, no model
artefact. `EVALUATION.md` defines the measurement plan only.

### PHASE 6 - Intelligent route optimization --- **PARTIAL (~50%)**
Exists: cost = time + risk + reliability, cargo priority weights, blocked penalty,
explanation text, and a test that guarantees a blocked road is never recommended.

Missing: component scores are computed then discarded rather than stored and returned;
vehicle suitability (cold chain, tonnage) exists as data but does not influence scoring;
the cargo priority table is buried in code instead of configuration; closure probability
is not modelled separately from risk; there is no explicit current-vs-recommended
trade-off object.

### PHASE 7 - Flutter field app --- **NOT STARTED**
No Dart/Flutter code anywhere.

### PHASE 8 - Logistics intelligence --- **PARTIAL (~30%)**
Exists: 6 depots, per-item stock, shortage/surplus flags, suggested transfers, UI.

**But** `seed.py` hardcodes both `stock_days` **and** `status`. There is no consumption
model, no burn rate, no demand forecast, no supply-gap forecast, no cargo-compatibility
check, no vehicle selection, and suggested transfers are not routed through the risk or
routing engines. It is currently an inventory screen, not logistics intelligence.

### PHASE 9 - Digital twin + what-if --- **PARTIAL (~35%)**
Exists: 3 scenarios, 7-step cascade, accept/decline/reset, event log.

**Architectural violation:** `app/simctl.py` writes straight into production state
(`store.manual_incidents[...] = incident`, `store.simulation = sim`,
`store.refresh_live(force=True)`). Phase 9 explicitly requires that simulation must not
mutate production state unless committed. There is no sandboxed twin, no
current-vs-simulated comparison, and no apply/commit boundary. Scenario types are limited
to landslide/flood; no bridge closure, demand surge, district impact or supply impact.

### PHASE 10 - AI copilot --- **NOT STARTED**

### PHASE 11 - Alerts + command system --- **PARTIAL (~65%)**
The strongest of the partial phases: stable-key deduplication, severity ordering, merge
that preserves prior acknowledgement state, and full acknowledge/assign/escalate/resolve.

Missing: persistence (restart wipes the lifecycle), a real assigned-operator identity
(there are no users yet), escalation policy/SLA timers, any notification transport, and
first-class alert types for supply shortage and failed field sync.

### PHASE 12 - Final validation --- **PARTIAL**
The end-to-end drill works and `EVALUATION.md` exists. Missing: `/docs` set (this file
is the first), failure-case tests, and offline-sync tests.

---

## Architectural problems that must be fixed before continuing

1. **No persistence layer.** Blocks Phases 3, 5, 8, 9 and 11 - risk predictions, field
   reports, alert lifecycle and twin state all need somewhere to live.
2. **No identity or roles.** A Phase 2 requirement, and a hard dependency for alert
   assignment (11) and the field officer app (7).
3. **Simulation mutates production state.** Must be resolved before Phase 9.
4. **Offline road geometry is fake.** Must be resolved in Phase 3.
5. **`store.py` is a god object** - it owns refresh, risk recompute, operations recompute
   and alert recompute. It needs to split into repositories + domain services before more
   phases pile onto it.
6. **Policy constants are hardcoded** (cargo priority, thresholds) instead of configuration.

---

## Missing external services and credentials

| Need | Phase | Status |
| --- | --- | --- |
| PostgreSQL + PostGIS server | 2, 3 | Not installed in the dev sandbox; no `psql`, `pg_config` or `initdb` |
| pip / outbound network | 2, 5 | **Unavailable.** `fastapi`, `sqlalchemy`, `alembic`, `psycopg`, `geoalchemy2`, `shapely`, `xgboost`, `lightgbm`, `sklearn`, `scipy`, `joblib` all absent and uninstallable here |
| Flutter SDK | 7 | Absent - Dart app can be written but not compiled or tested here |
| LLM API key | 10 | Not required if the copilot is built as a grounded deterministic query engine |
| TomTom key | 4 | Optional - traffic stays labelled "Modelled" without it |
| Self-hosted OSRM | 3 | Public demo server is rate-limited and unsuitable for production |

Available and usable: Python 3.13, `sqlite3`, `pydantic`, `pandas`, `numpy`,
`matplotlib`, `requests`, `git`, `node`.

---

## Data limitations affecting Phase 5

- **There is no labelled disruption history for the Northeast.** Closure records live in
  NHIDCL / BRO / PWD notices and SDMA situation reports; none is available as a clean API.
- A usable dataset needs roughly 2 years x 12 corridors (~8,700 corridor-days) at an
  expected 4-9% positive rate.
- Consequence: the training and evaluation pipeline can be built and validated now, but a
  model trained on synthetic data must never be reported as an accuracy claim, and the
  heuristic must remain the default scorer until real labels exist.
