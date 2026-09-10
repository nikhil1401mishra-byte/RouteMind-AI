"""Live seismic activity from the USGS earthquake feed (keyless).

The whole North East sits in BIS seismic zones IV-V. Recent tremors measurably
raise landslide susceptibility on already-saturated slopes, so nearby quakes
act as a risk multiplier and are also surfaced as map incidents.
"""

from __future__ import annotations

import time
from typing import List, Tuple

from .. import config, geo
from ..http_client import get_json

# Quakes further away than this have no practical effect on a corridor.
INFLUENCE_RADIUS_KM = 250.0


def fetch_events() -> Tuple[List[dict], str]:
    """Recent earthquakes inside (or near) the North East bounding box."""
    payload, provenance = get_json(
        config.USGS_FEED,
        feed="usgs",
        ttl=config.TTL_SEISMIC,
        snapshot_key="seismic",
    )
    if not payload:
        return [], provenance

    events: List[dict] = []
    for feature in payload.get("features", []):
        try:
            coords = feature["geometry"]["coordinates"]
            lng, lat = float(coords[0]), float(coords[1])
            depth = float(coords[2]) if len(coords) > 2 else 0.0
            props = feature.get("properties", {})
            mag = props.get("mag")
            if mag is None:
                continue

            # Widen the box a little: a M5 across the border still matters.
            if not geo.bbox_contains(_padded_bbox(), lng, lat):
                continue

            events.append({
                "id": feature.get("id", ""),
                "magnitude": round(float(mag), 1),
                "depth_km": round(depth, 1),
                "place": props.get("place", "Unknown location"),
                "time": int(props.get("time", 0)) / 1000.0,
                "lng": lng,
                "lat": lat,
                "url": props.get("url", ""),
            })
        except (KeyError, TypeError, ValueError, IndexError):
            continue

    events.sort(key=lambda e: e["time"], reverse=True)
    return events, provenance


def _padded_bbox() -> dict:
    b = config.NER_BBOX
    pad = 2.5
    return {
        "min_lat": b["min_lat"] - pad, "max_lat": b["max_lat"] + pad,
        "min_lng": b["min_lng"] - pad, "max_lng": b["max_lng"] + pad,
    }


def corridor_seismic_factor(line: List[geo.Coord], events: List[dict]) -> Tuple[float, List[dict]]:
    """0..1 seismic stress for a corridor, plus the events responsible.

    Weighted by magnitude, distance and recency (48h decay).
    """
    if not line or not events:
        return 0.0, []

    now = time.time()
    score = 0.0
    contributors: List[dict] = []

    for ev in events:
        dist = geo.distance_point_to_line_km((ev["lng"], ev["lat"]), line)
        if dist > INFLUENCE_RADIUS_KM:
            continue

        age_h = max(0.0, (now - ev["time"]) / 3600.0)
        if age_h > 72:
            continue

        mag_term = max(0.0, (ev["magnitude"] - 2.5)) / 4.5     # M2.5 -> 0, M7 -> 1
        dist_term = 1.0 - (dist / INFLUENCE_RADIUS_KM)
        recency_term = max(0.0, 1.0 - age_h / 72.0)
        shallow_term = 1.0 if ev["depth_km"] <= 70 else 0.6    # shallow quakes shake more

        contribution = mag_term * dist_term * recency_term * shallow_term
        if contribution <= 0.01:
            continue

        score += contribution
        contributors.append({
            "magnitude": ev["magnitude"],
            "place": ev["place"],
            "distance_km": round(dist, 1),
            "hours_ago": round(age_h, 1),
        })

    contributors.sort(key=lambda c: c["magnitude"], reverse=True)
    return min(1.0, score), contributors[:3]
