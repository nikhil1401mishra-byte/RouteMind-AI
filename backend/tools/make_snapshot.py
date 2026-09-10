#!/usr/bin/env python3
"""Generate app/data/snapshot.json -- the bundled offline fallback.

The snapshot mimics the exact response shapes of Open-Meteo and the USGS feed,
so the parsing code paths exercised offline are identical to the live ones.
Values represent a realistic late-monsoon day in the North East.

Run:  python tools/make_snapshot.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "app" / "data" / "snapshot.json"

# Six weather profiles, reused across corridor sample points. Ordered from the
# wettest hill corridors to the drier western plains.
PROFILES = [
    {"name": "hill-monsoon-severe", "base": 5.2, "peak": 19.0, "phase": 0.2},
    {"name": "hill-monsoon-heavy",  "base": 3.4, "peak": 12.5, "phase": 0.6},
    {"name": "hill-moderate",       "base": 1.9, "peak": 7.0,  "phase": 1.1},
    {"name": "valley-moderate",     "base": 1.1, "peak": 4.5,  "phase": 1.7},
    {"name": "plains-light",        "base": 0.5, "peak": 2.4,  "phase": 2.3},
    {"name": "plains-dry",          "base": 0.1, "peak": 0.9,  "phase": 2.9},
]

HOURS = 96  # past_days=2 + forecast_days=2


def precipitation_series(profile: dict) -> list:
    """Deterministic diurnal rainfall curve with a monsoon burst."""
    out = []
    for h in range(HOURS):
        diurnal = max(0.0, math.sin((h / 24.0) * 2 * math.pi + profile["phase"]))
        burst = profile["peak"] if 52 <= h <= 58 else 0.0
        value = profile["base"] * diurnal + burst * max(0.0, math.sin((h - 52) / 6.0 * math.pi))
        out.append(round(max(0.0, value), 2))
    return out


def probability_series(precip: list) -> list:
    return [min(100, int(round(p * 12 + 18))) for p in precip]


def weather_block(profile: dict, lat: float, lng: float) -> dict:
    precip = precipitation_series(profile)
    times = [
        time.strftime("%Y-%m-%dT%H:00", time.gmtime(time.time() + (h - 48) * 3600))
        for h in range(HOURS)
    ]
    return {
        "latitude": lat,
        "longitude": lng,
        "timezone": "Asia/Kolkata",
        "snapshot_profile": profile["name"],
        "current": {
            "temperature_2m": round(22.0 + profile["base"], 1),
            "precipitation": precip[48],
            "weather_code": 63 if precip[48] > 2 else 3,
            "wind_speed_10m": round(8.0 + profile["base"] * 1.4, 1),
        },
        "hourly": {
            "time": times,
            "precipitation": precip,
            "precipitation_probability": probability_series(precip),
        },
        "daily": {
            "precipitation_sum": [
                round(sum(precip[0:24]), 1),
                round(sum(precip[24:48]), 1),
                round(sum(precip[48:72]), 1),
                round(sum(precip[72:96]), 1),
            ]
        },
    }


def build_weather() -> list:
    """36 blocks: 12 corridors x 3 sample points, cycling the profiles."""
    blocks = []
    coords = [
        (25.5, 92.1), (24.2, 92.7), (24.8, 93.2), (25.7, 94.1), (27.1, 93.6),
        (27.3, 88.6), (26.1, 91.7), (26.7, 94.2), (23.8, 91.3), (27.5, 91.9),
        (26.6, 92.8), (23.0, 92.7),
    ]
    for i in range(36):
        profile = PROFILES[i % len(PROFILES)]
        lat, lng = coords[i % len(coords)]
        blocks.append(weather_block(profile, lat, lng))
    return blocks


def build_seismic() -> dict:
    now_ms = int(time.time() * 1000)
    events = [
        (4.3, 30.0, "92 km ESE of Aizawl, India", 93.55, 23.62, 5),
        (3.8, 45.0, "Assam-Meghalaya border region, India", 91.95, 25.62, 14),
        (4.9, 62.0, "Myanmar-India border region", 94.35, 24.35, 26),
        (3.2, 18.0, "48 km NW of Imphal, India", 93.52, 25.10, 33),
        (5.1, 85.0, "Eastern Nepal-Sikkim border region", 88.15, 27.45, 41),
        (3.5, 24.0, "Arunachal Pradesh, India", 93.20, 27.35, 55),
    ]

    features = []
    for idx, (mag, depth, place, lng, lat, hours_ago) in enumerate(events):
        features.append({
            "type": "Feature",
            "id": "snapshot_eq_" + str(idx),
            "properties": {
                "mag": mag,
                "place": place,
                "time": now_ms - hours_ago * 3600 * 1000,
                "url": "https://earthquake.usgs.gov/earthquakes/",
                "type": "earthquake",
            },
            "geometry": {"type": "Point", "coordinates": [lng, lat, depth]},
        })

    return {
        "type": "FeatureCollection",
        "metadata": {
            "title": "RouteMind bundled seismic snapshot",
            "generated": now_ms,
            "count": len(features),
            "note": "Offline fallback only. Live runs use the real USGS feed.",
        },
        "features": features,
    }


def main() -> int:
    snapshot = {
        "_meta": {
            "purpose": "Offline fallback so the control room still works with no internet.",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "shapes": "Mirrors Open-Meteo forecast and USGS GeoJSON responses exactly.",
            "honesty": "Values are representative, not measured. The UI labels them "
                       "as 'offline-snapshot' whenever they are used.",
        },
        "weather": build_weather(),
        "seismic": build_seismic(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=1)

    size_kb = OUT.stat().st_size / 1024.0
    print("wrote " + str(OUT))
    print("  weather blocks : " + str(len(snapshot["weather"])))
    print("  seismic events : " + str(len(snapshot["seismic"]["features"])))
    print("  size           : " + format(size_kb, ".1f") + " KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
