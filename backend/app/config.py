"""Central configuration for RouteMind AI.

Every live data source used here is keyless and free. Optional keys unlock
higher-fidelity feeds (real traffic flow) and are read from the environment.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
PROJECT_DIR = BASE_DIR.parent                              # routemind-ai/
FRONTEND_DIR = PROJECT_DIR / "frontend"
DATA_DIR = BASE_DIR / "app" / "data"
CACHE_DIR = BASE_DIR / ".cache"
SNAPSHOT_FILE = DATA_DIR / "snapshot.json"

HOST = os.environ.get("ROUTEMIND_HOST", "127.0.0.1")
PORT = int(os.environ.get("ROUTEMIND_PORT", "8000"))

# ---------------------------------------------------------------- live feeds
# Open-Meteo: weather + rainfall forecast. Keyless, free for non-commercial use.
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
# Open-Meteo elevation API: terrain height -> slope proxy.
OPEN_METEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"
# USGS earthquake feed: real seismic events, keyless.
USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
# OSRM public demo server: real OSM road geometry + routing + alternatives.
OSRM_BASE = os.environ.get("ROUTEMIND_OSRM", "https://router.project-osrm.org")

# Optional: real traffic flow. Without a key we model congestion instead and
# label it honestly in the API response.
TOMTOM_KEY = os.environ.get("TOMTOM_API_KEY", "").strip()
TOMTOM_FLOW = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

# Network behaviour. Short timeouts keep the UI responsive on bad venue wifi.
HTTP_TIMEOUT = float(os.environ.get("ROUTEMIND_HTTP_TIMEOUT", "6.0"))
HTTP_RETRIES = 1
OFFLINE = os.environ.get("ROUTEMIND_OFFLINE", "").lower() in {"1", "true", "yes"}

# Cache TTLs in seconds.
TTL_WEATHER = 15 * 60
TTL_SEISMIC = 10 * 60
TTL_ELEVATION = 30 * 24 * 3600     # terrain does not change
TTL_GEOMETRY = 7 * 24 * 3600       # road geometry rarely changes
TTL_ROUTE = 5 * 60
TTL_TRAFFIC = 5 * 60

# Region of interest: the eight North Eastern states.
NER_BBOX = {"min_lat": 21.9, "max_lat": 29.5, "min_lng": 87.9, "max_lng": 97.5}

# Simulated fleet tick (seconds of wall clock per movement step).
VEHICLE_TICK_SECONDS = 2.0

USER_AGENT = "RouteMindAI/1.0 (SIH26002 prototype; contact: team@routemind.local)"

# ------------------------------------------------------------------ storage
# SQLite is the default so the control room runs with zero installation.
# PostgreSQL + PostGIS is the production target and uses the same schema.
DB_BACKEND = os.environ.get("ROUTEMIND_DB", "sqlite").strip().lower()
DATABASE_URL = os.environ.get("ROUTEMIND_DATABASE_URL", "").strip()
SQLITE_PATH = os.environ.get(
    "ROUTEMIND_SQLITE_PATH", str(BASE_DIR / "data" / "routemind.db")
)

# --------------------------------------------------------------------- auth
# "demo"   -> unauthenticated requests act as the dispatcher account, but role
#             permissions are still enforced server-side.
# "strict" -> every state change requires a session token from /api/auth/login.
AUTH_MODE = os.environ.get("ROUTEMIND_AUTH", "demo").strip().lower()
if AUTH_MODE not in {"demo", "strict"}:
    AUTH_MODE = "demo"
SESSION_TTL = float(os.environ.get("ROUTEMIND_SESSION_TTL", str(12 * 3600)))

CACHE_DIR.mkdir(parents=True, exist_ok=True)
