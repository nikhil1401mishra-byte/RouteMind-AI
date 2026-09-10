"""The North East India road network model.

Corridor geometry is fetched from OSRM (real OpenStreetMap road shapes) at
startup and cached. When the network is unavailable we fall back to the
simplified reference polylines defined here, so the map is never empty.

Static attributes (terrain, seismic zone, historical incident density, surface
condition) are curated from public knowledge about these corridors and feed the
explainable risk model. They are documented as estimates, not measurements.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

Coord = Tuple[float, float]

# ------------------------------------------------------------------ places ---
CITIES: Dict[str, dict] = {
    "guwahati":     {"name": "Guwahati",     "state": "Assam",             "lng": 91.7362, "lat": 26.1445, "major": True},
    "shillong":     {"name": "Shillong",     "state": "Meghalaya",         "lng": 91.8933, "lat": 25.5788, "major": True},
    "silchar":      {"name": "Silchar",      "state": "Assam",             "lng": 92.7789, "lat": 24.8333, "major": True},
    "aizawl":       {"name": "Aizawl",       "state": "Mizoram",           "lng": 92.7176, "lat": 23.7271, "major": True},
    "imphal":       {"name": "Imphal",       "state": "Manipur",           "lng": 93.9368, "lat": 24.8170, "major": True},
    "kohima":       {"name": "Kohima",       "state": "Nagaland",          "lng": 94.1086, "lat": 25.6751, "major": True},
    "dimapur":      {"name": "Dimapur",      "state": "Nagaland",          "lng": 93.7270, "lat": 25.9040, "major": False},
    "agartala":     {"name": "Agartala",     "state": "Tripura",           "lng": 91.2868, "lat": 23.8315, "major": True},
    "itanagar":     {"name": "Itanagar",     "state": "Arunachal Pradesh", "lng": 93.6053, "lat": 27.0844, "major": True},
    "tawang":       {"name": "Tawang",       "state": "Arunachal Pradesh", "lng": 91.8590, "lat": 27.5860, "major": False},
    "gangtok":      {"name": "Gangtok",      "state": "Sikkim",            "lng": 88.6065, "lat": 27.3389, "major": True},
    "siliguri":     {"name": "Siliguri",     "state": "West Bengal",       "lng": 88.3950, "lat": 26.7271, "major": False},
    "jorhat":       {"name": "Jorhat",       "state": "Assam",             "lng": 94.2037, "lat": 26.7509, "major": False},
    "dibrugarh":    {"name": "Dibrugarh",    "state": "Assam",             "lng": 94.9120, "lat": 27.4728, "major": False},
    "tezpur":       {"name": "Tezpur",       "state": "Assam",             "lng": 92.8000, "lat": 26.6338, "major": False},
    "kolasib":      {"name": "Kolasib",      "state": "Mizoram",           "lng": 92.6760, "lat": 24.2260, "major": False},
    "jiribam":      {"name": "Jiribam",      "state": "Manipur",           "lng": 93.1200, "lat": 24.8000, "major": False},
    "lunglei":      {"name": "Lunglei",      "state": "Mizoram",           "lng": 92.7350, "lat": 22.8879, "major": False},
    "bongaigaon":   {"name": "Bongaigaon",   "state": "Assam",             "lng": 90.5583, "lat": 26.4769, "major": False},
    "churachandpur":{"name": "Churachandpur","state": "Manipur",           "lng": 93.6833, "lat": 24.3333, "major": False},
}


def city_coord(key: str) -> Coord:
    c = CITIES[key]
    return (c["lng"], c["lat"])


# --------------------------------------------------------------- corridors ---
# terrain: 0 = flat valley, 1 = steep mountain
# condition: 0 = excellent surface, 1 = poor / frequently damaged
# history: landslide/flood incidents per year (public reporting, approximate)
# river: 0 = away from major rivers, 1 = closely follows flood-prone river
# seismic: Bureau of Indian Standards seismic zone (IV or V across the NER)
CORRIDORS: List[dict] = [
    {
        "id": "NH27-GHY-DBR", "name": "NH-27 Guwahati \u2013 Jorhat \u2013 Dibrugarh",
        "from": "guwahati", "to": "dibrugarh", "via": ["tezpur", "jorhat"],
        "terrain": 0.15, "condition": 0.20, "history": 3, "river": 0.75, "seismic": 5,
        "lanes": 4, "free_flow_kmh": 62,
    },
    {
        "id": "NH27-GHY-SLG", "name": "NH-27 Guwahati \u2013 Bongaigaon \u2013 Siliguri",
        "from": "guwahati", "to": "siliguri", "via": ["bongaigaon"],
        "terrain": 0.10, "condition": 0.18, "history": 2, "river": 0.60, "seismic": 5,
        "lanes": 4, "free_flow_kmh": 65,
    },
    {
        "id": "NH6-GHY-SCL", "name": "NH-6 Guwahati \u2013 Shillong \u2013 Silchar",
        "from": "guwahati", "to": "silchar", "via": ["shillong"],
        "terrain": 0.62, "condition": 0.45, "history": 11, "river": 0.30, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 45,
    },
    {
        "id": "NH306-SCL-AJL", "name": "NH-306 Silchar \u2013 Kolasib \u2013 Aizawl",
        "from": "silchar", "to": "aizawl", "via": ["kolasib"],
        "terrain": 0.85, "condition": 0.62, "history": 18, "river": 0.35, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 34,
    },
    {
        "id": "NH37-SCL-IMF", "name": "NH-37 Silchar \u2013 Jiribam \u2013 Imphal",
        "from": "silchar", "to": "imphal", "via": ["jiribam"],
        "terrain": 0.72, "condition": 0.55, "history": 13, "river": 0.45, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 38,
    },
    {
        "id": "NH29-DMU-IMF", "name": "NH-29 Dimapur \u2013 Kohima \u2013 Imphal",
        "from": "dimapur", "to": "imphal", "via": ["kohima"],
        "terrain": 0.78, "condition": 0.58, "history": 15, "river": 0.20, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 36,
    },
    {
        "id": "NH39-JRH-DMU", "name": "NH-39 Jorhat \u2013 Dimapur",
        "from": "jorhat", "to": "dimapur", "via": [],
        "terrain": 0.30, "condition": 0.32, "history": 5, "river": 0.50, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 48,
    },
    {
        "id": "NH8-AGT-SCL", "name": "NH-8 Agartala \u2013 Silchar",
        "from": "agartala", "to": "silchar", "via": [],
        "terrain": 0.45, "condition": 0.42, "history": 8, "river": 0.55, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 42,
    },
    {
        "id": "NH13-ITN-TWG", "name": "NH-13 Itanagar \u2013 Tawang (Trans-Arunachal)",
        "from": "itanagar", "to": "tawang", "via": [],
        "terrain": 0.95, "condition": 0.70, "history": 22, "river": 0.25, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 28,
    },
    {
        "id": "NH10-SLG-GTK", "name": "NH-10 Siliguri \u2013 Gangtok",
        "from": "siliguri", "to": "gangtok", "via": [],
        "terrain": 0.88, "condition": 0.66, "history": 25, "river": 0.90, "seismic": 4,
        "lanes": 2, "free_flow_kmh": 30,
    },
    {
        "id": "NH15-TZP-ITN", "name": "NH-15 Tezpur \u2013 Itanagar",
        "from": "tezpur", "to": "itanagar", "via": [],
        "terrain": 0.35, "condition": 0.30, "history": 4, "river": 0.65, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 46,
    },
    {
        "id": "NH306-AJL-LGL", "name": "NH-306 Aizawl \u2013 Lunglei",
        "from": "aizawl", "to": "lunglei", "via": [],
        "terrain": 0.90, "condition": 0.68, "history": 16, "river": 0.20, "seismic": 5,
        "lanes": 2, "free_flow_kmh": 30,
    },
]

CORRIDOR_BY_ID = {c["id"]: c for c in CORRIDORS}


# --------------------------------------------- simplified fallback geometry ---
# Used only when OSRM is unreachable. Coarse but geographically sane, so the
# map still shows a coherent network offline.
FALLBACK_GEOMETRY: Dict[str, List[Coord]] = {
    "NH27-GHY-DBR": [(91.7362, 26.1445), (92.05, 26.35), (92.80, 26.6338), (93.45, 26.72),
                     (94.2037, 26.7509), (94.55, 27.05), (94.9120, 27.4728)],
    "NH27-GHY-SLG": [(91.7362, 26.1445), (91.20, 26.30), (90.5583, 26.4769), (89.50, 26.55),
                     (88.80, 26.65), (88.3950, 26.7271)],
    "NH6-GHY-SCL":  [(91.7362, 26.1445), (91.77, 25.98), (91.83, 25.78), (91.8933, 25.5788),
                     (92.10, 25.50), (92.35, 25.28), (92.60, 25.05), (92.7789, 24.8333)],
    "NH306-SCL-AJL":[(92.7789, 24.8333), (92.755, 24.635), (92.70, 24.47), (92.6760, 24.2260),
                     (92.70, 23.98), (92.7176, 23.7271)],
    "NH37-SCL-IMF": [(92.7789, 24.8333), (93.02, 24.68), (93.1200, 24.8000), (93.45, 24.70),
                     (93.75, 24.80), (93.9368, 24.8170)],
    "NH29-DMU-IMF": [(93.7270, 25.9040), (93.85, 25.80), (94.1086, 25.6751), (94.15, 25.45),
                     (94.05, 25.15), (93.9368, 24.8170)],
    "NH39-JRH-DMU": [(94.2037, 26.7509), (94.05, 26.45), (93.90, 26.15), (93.7270, 25.9040)],
    "NH8-AGT-SCL":  [(91.2868, 23.8315), (91.60, 24.00), (91.95, 24.30), (92.35, 24.55),
                     (92.7789, 24.8333)],
    "NH13-ITN-TWG": [(93.6053, 27.0844), (93.20, 27.20), (92.65, 27.25), (92.10, 27.35),
                     (91.8590, 27.5860)],
    "NH10-SLG-GTK": [(88.3950, 26.7271), (88.45, 26.95), (88.55, 27.15), (88.6065, 27.3389)],
    "NH15-TZP-ITN": [(92.8000, 26.6338), (93.05, 26.75), (93.35, 26.92), (93.6053, 27.0844)],
    "NH306-AJL-LGL":[(92.7176, 23.7271), (92.80, 23.45), (92.78, 23.15), (92.7350, 22.8879)],
}


def waypoints(corridor: dict) -> List[Coord]:
    """Ordered coordinates OSRM should route through for this corridor."""
    keys = [corridor["from"]] + list(corridor.get("via", [])) + [corridor["to"]]
    return [city_coord(k) for k in keys]


def endpoints_label(corridor: dict) -> str:
    return f"{CITIES[corridor['from']]['name']} \u2192 {CITIES[corridor['to']]['name']}"
