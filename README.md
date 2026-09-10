# RouteMind AI

**Predictive logistics control room for India's North East.**
SIH 2026 - Problem Statement SIH26002.

RouteMind watches the road network of the eight North Eastern states, predicts
which corridors are about to be disrupted by rainfall, terrain and seismic
activity, and reroutes critical cargo *before* a delivery fails.

This repository is a **fully working website**: an HTML / CSS / JavaScript
frontend and a Python backend, wired to live public data feeds.

---

## Run it

You need **Python 3.9 or newer**. Nothing else. There is no `npm install`,
no build step, and no pip dependency to install.

### Windows

Double-click **`start.bat`**.

### macOS / Linux

```bash
chmod +x start.sh
./start.sh
```

### Any platform, manually

```bash
cd backend
python run.py
```

The server starts on <http://127.0.0.1:8000> and opens your browser. The same
Python process serves the API *and* the frontend, so there is no CORS setup and
no second terminal.

Useful flags:

| Command | What it does |
| --- | --- |
| `python run.py` | Normal start, live data, opens a browser |
| `python run.py --no-browser` | Start without opening a browser |
| `python run.py --offline` | Force the bundled snapshot, never touch the network |
| `python run.py --selftest --no-browser` | Hit all 26 endpoints and print a pass/fail table |
| `python tests/test_all.py` | Run the 46-test suite (always offline, never flaky) |

---

## What is on the screen

| View | What it gives an operator |
| --- | --- |
| **Control room** | Six KPIs, the live network map, what needs attention now, top-risk corridors, 48h rainfall vs 24h forecast, risk distribution, reroute history |
| **Road risk** | Every corridor scored 0-100% for the next 24 hours, with the exact factor breakdown behind each score |
| **Fleet** | 12 vehicles, live positions, cargo, driver, halt reasons, one-click route planning |
| **Deliveries** | Consignments against their SLA, reliability, delay, consignee |
| **Incidents** | Live hazard feed (seismic, rainfall-derived, model-predicted, field-reported) plus a form to report from the control room |
| **Route planner** | Risk-aware alternatives for any vehicle, scored on time **and** disruption probability, weighted by cargo priority |
| **Supply depots** | Stock cover per depot and suggested inter-depot transfers |
| **Disruption drill** | The end-to-end demo: inject a landslide and watch detect -> impact -> options -> decision -> reroute |
| **Alerts** | Acknowledge, assign, escalate, resolve |

### The map

The map is hand-written (`frontend/js/map.js`) - no Leaflet, no MapLibre, no CDN,
no API key. It renders OpenStreetMap raster tiles under an SVG overlay carrying:

- **12 corridors** coloured by disruption risk or by live congestion (toggle top-right)
- **Incidents** as diamonds, sized and coloured by severity, blocked roads dashed red
- **Vehicles** as dots, with a halo when the cargo is critical or the truck is halted
- **Depots**, **cities**, hover tooltips, click-to-inspect, drag, wheel zoom, and layer toggles

If the tile servers cannot be reached, tiles are dropped, the light basemap shows
through, and a badge on the map says so. **The road network, incidents and
vehicles still render**, because they are drawn from geometry, not from tiles.

---

## Live data

All feeds are keyless and free.

| Feed | Used for | Endpoint |
| --- | --- | --- |
| **Open-Meteo Forecast** | 48h observed rainfall and 24h rainfall forecast per corridor | `api.open-meteo.com` |
| **Open-Meteo Elevation** | Terrain and slope along each corridor | `api.open-meteo.com` |
| **USGS Earthquakes** | Seismic events in the region, last 24h | `earthquake.usgs.gov` |
| **OSRM** | Real road geometry and alternative routes | `router.project-osrm.org` |
| **OpenStreetMap** | Basemap tiles | `tile.openstreetmap.org` |
| **TomTom Flow** *(optional)* | Measured live traffic speeds | needs `TOMTOM_API_KEY` |

**Every response tells you where its numbers came from.** Click the source card
at the bottom of the sidebar to see each feed's state: `live`, `cached`,
`snapshot` or `unavailable`, with the time it was last checked. When a feed is
down the server falls back to a bundled snapshot and *says so* rather than
quietly inventing numbers.

---

## Honesty about the AI

Read this before you demo it.

- The risk engine is a **transparent weighted scoring model** (`heuristic-v1`),
  **not a trained ML model**. Rainfall 0.34, terrain 0.20, history 0.16,
  condition 0.12, river proximity 0.08, seismic 0.06, traffic 0.04, combined
  through a logistic curve, with an interaction term for rain falling on steep
  ground.
- Every score is explainable: the Road risk view shows the contribution of each
  factor, in millimetres and metres, for that specific corridor.
- The **Model card** (sidebar, bottom left) states this in the product itself.
- Phase 5 of the roadmap replaces this with XGBoost / LightGBM trained on
  historical disruption. `EVALUATION.md` defines how that model will be measured
  *before* it is built - precision, recall, lead time and calibration.
- The **Disruption drill** is clearly labelled a simulation. It is the only
  place where an incident is fabricated, and the injected incident is tagged
  `simulation` in the feed.

A blocked road is **never** returned as a recommended route. That rule has four
dedicated regression tests (`TestRerouteSafety`), because confidently routing an
ambulance into a landslide is the worst thing this system could do.

---

## The 90-second demo

1. Open the **Control room**. 12 vehicles moving, 6 deliveries at risk.
2. Go to **Disruption drill** and press **Start drill**.
3. A landslide is injected on **NH-306 (Silchar - Aizawl)**.
4. Watch the chain react:
   - the corridor turns red and dashed on the map
   - **TR-104**, carrying **emergency medicine**, halts
   - **DLV-2041** to Aizawl Civil Hospital goes at-risk
   - two alternatives are scored and explained
5. Press **Accept reroute**. The vehicle is redirected, the route redraws, the
   delivery clock is recalculated, and the reroute lands in history.
6. Press **Reset** to put the network back.

---

## Project layout

```
routemind-ai/
  start.bat / start.sh      one-click launchers
  README.md  EVALUATION.md
  backend/
    run.py                  entry point: serves API + frontend
    requirements.txt        (empty - stdlib only)
    app/
      api.py                26 endpoints, pure functions of the store
      server.py             stdlib HTTP server + static files
      fastapi_app.py        optional FastAPI mount for Phase 2
      store.py              in-memory state, tick loop, refresh scheduling
      network.py            the 12 corridors, 20 cities, 6 depots
      routes_engine.py      risk-aware planner, bypass generation
      simctl.py             disruption drill state machine
      geo.py http_client.py config.py seed.py
      services/             weather seismic traffic risk incidents alerts routing simulation
      data/snapshot.json    offline fallback (169 KB of real recorded feed data)
    tools/                  snapshot builder, geometry dumper
    tests/test_all.py       46 tests
  frontend/
    index.html
    css/styles.css
    js/  utils api map charts dashboard risk fleet deliveries
         incidents routes inventory simulation alerts app
```

---

## API

`GET /api` lists everything. Highlights:

```
GET  /api/overview                 everything the control room needs, one call
GET  /api/map                      corridors, vehicles, incidents, depots, cities, bbox
GET  /api/risk/{corridor_id}       full factor breakdown for one corridor
GET  /api/model-card               what the model is and is not
POST /api/routes/plan              { vehicle_id } -> scored, explained options
POST /api/incidents                report from the field
POST /api/alerts/{id}/action       acknowledge | assign | escalate | resolve
POST /api/simulation/start         { scenario_id }
POST /api/simulation/accept        { route_id }
GET  /api/system/status            per-feed provenance and freshness
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ROUTEMIND_HOST` | `127.0.0.1` | Bind address |
| `ROUTEMIND_PORT` | `8000` | Port |
| `ROUTEMIND_OFFLINE` | unset | `1` forces snapshot mode |
| `ROUTEMIND_OSRM` | public OSRM | Point at your own routing server |
| `TOMTOM_API_KEY` | unset | Enables measured live traffic flow |

---

## Where this goes next

Phase 1 (this build) is the control room on live public data. Phase 2 moves the
store into PostgreSQL + PostGIS behind FastAPI with real roles; Phase 3 swaps the
corridor graph for full OSM routing; Phase 5 replaces `heuristic-v1` with a
trained, evaluated model; Phase 7 adds the offline-first Flutter field app.
The API contract above is designed to survive all of it.
