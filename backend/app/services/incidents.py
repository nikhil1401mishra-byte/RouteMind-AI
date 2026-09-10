"""Incident derivation.

Incidents shown on the map come from three clearly-labelled origins:

  1. `usgs-live`          - real earthquakes from the USGS feed.
  2. `open-meteo-derived` - rainfall warnings computed from live forecast data.
  3. `risk-model`         - predicted disruption points from the risk engine.
  4. `field-report`       - simulated field reports (prototype stand-in for the
                            Phase 7 Flutter field app) and simulation events.

Every incident carries `source` and `verified` so the UI never presents a
simulated report as a real observation.
"""

from __future__ import annotations

import time
from typing import Dict, List

from .. import geo, network

SEVERITY_ORDER = {"critical": 0, "high": 1, "moderate": 2, "low": 3}

# Rainfall thresholds (mm over the next 24h) for warning incidents.
RAIN_WARN_MM = 64.0
RAIN_SEVERE_MM = 115.0

# Earthquakes below this magnitude are not operationally relevant.
QUAKE_MIN_MAG = 3.0


def derive_from_live(
    corridor_state: Dict[str, dict],
    geometries: Dict[str, List[geo.Coord]],
    seismic_events: List[dict],
) -> List[dict]:
    """Build the live incident set. Ids are stable so acknowledgements stick."""
    out: List[dict] = []

    # --- real earthquakes -------------------------------------------------
    for ev in seismic_events:
        if ev["magnitude"] < QUAKE_MIN_MAG:
            continue
        nearest_id, nearest_km = _nearest_corridor((ev["lng"], ev["lat"]), geometries)
        severity = "critical" if ev["magnitude"] >= 5.0 else (
            "high" if ev["magnitude"] >= 4.0 else "moderate")
        out.append({
            "id": f"EQ-{ev['id']}" if ev.get("id") else f"EQ-{int(ev['time'])}",
            "type": "earthquake",
            "severity": severity,
            "title": f"M{ev['magnitude']} earthquake",
            "description": (
                f"{ev['place']}. Depth {ev['depth_km']} km. "
                f"Nearest corridor {nearest_km:.0f} km away. "
                "Slope stability may be reduced on saturated ground."
            ),
            "lng": ev["lng"], "lat": ev["lat"],
            "corridor_id": nearest_id if nearest_km <= 60 else None,
            "blocks_road": False,
            "source": "usgs-live",
            "source_label": "USGS live feed",
            "verified": True,
            "reported_at": ev["time"],
            "status": "active",
            "external_url": ev.get("url", ""),
        })

    # --- rainfall warnings ------------------------------------------------
    for cid, state in corridor_state.items():
        weather = state.get("weather") or {}
        if not weather.get("available"):
            continue
        ahead = float(weather.get("rain_next_24h_mm") or 0.0)
        if ahead < RAIN_WARN_MM:
            continue

        line = geometries.get(cid) or []
        if not line:
            continue
        point = geo.point_at_fraction(line, 0.45)
        corridor = network.CORRIDOR_BY_ID.get(cid, {})
        severity = "critical" if ahead >= RAIN_SEVERE_MM else "high"

        out.append({
            "id": f"RAIN-{cid}",
            "type": "heavy-rain",
            "severity": severity,
            "title": f"{'Very heavy' if ahead >= RAIN_SEVERE_MM else 'Heavy'} rainfall forecast",
            "description": (
                f"{ahead:.0f} mm forecast in the next 24h on "
                f"{corridor.get('name', cid)}. Peak intensity "
                f"{weather.get('max_hourly_next_24h', 0):.0f} mm/h."
            ),
            "lng": point[0], "lat": point[1],
            "corridor_id": cid,
            "blocks_road": False,
            "source": "open-meteo-derived",
            "source_label": "Derived from Open-Meteo forecast",
            "verified": True,
            "reported_at": time.time(),
            "status": "active",
            "external_url": "",
        })

    # --- model-predicted disruption points --------------------------------
    for cid, state in corridor_state.items():
        risk = state.get("risk") or {}
        if risk.get("probability", 0) < 0.62:
            continue
        line = geometries.get(cid) or []
        if not line:
            continue
        point = geo.point_at_fraction(line, 0.62)
        corridor = network.CORRIDOR_BY_ID.get(cid, {})
        top = (risk.get("factors") or [{}])[0]

        out.append({
            "id": f"PRED-{cid}",
            "type": "predicted-disruption",
            "severity": "critical" if risk["probability"] >= 0.75 else "high",
            "title": f"Predicted disruption risk {int(risk['probability'] * 100)}%",
            "description": (
                f"{corridor.get('name', cid)}: {risk.get('headline', '')} "
                f"Primary factor: {top.get('label', 'unknown')}."
            ),
            "lng": point[0], "lat": point[1],
            "corridor_id": cid,
            "blocks_road": False,
            "source": "risk-model",
            "source_label": "RouteMind risk model (heuristic v1)",
            "verified": False,
            "reported_at": time.time(),
            "status": "active",
            "external_url": "",
        })

    out.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), -i["reported_at"]))
    return out


def seed_field_reports() -> List[dict]:
    """Simulated field reports, explicitly labelled as prototype data.

    In Phase 7 these arrive from the Flutter field app with photo evidence.
    """
    now = time.time()
    specs = [
        ("FR-3301", "NH6-GHY-SCL", 0.58, "roadblock", "moderate",
         "Debris on carriageway",
         "Field officer reports rock debris narrowing traffic to one lane near Sonapur.", True),
        ("FR-3302", "NH10-SLG-GTK", 0.40, "landslide", "high",
         "Active landslide zone",
         "Slope failure reported near Rangpo; single-lane movement with pilot vehicle.", True),
        ("FR-3303", "NH27-GHY-DBR", 0.35, "flood", "moderate",
         "Water logging on approach",
         "Brahmaputra backwater flooding a 1.2 km stretch; light vehicles advised to divert.", True),
        ("FR-3304", "NH29-DMU-IMF", 0.66, "accident", "low",
         "Cleared vehicle breakdown",
         "Truck breakdown cleared; traffic normalised.", False),
    ]

    reports = []
    for idx, (rid, cid, frac, kind, severity, title, body, active) in enumerate(specs):
        reports.append({
            "id": rid,
            "type": kind,
            "severity": severity,
            "title": title,
            "description": body,
            "corridor_id": cid,
            "fraction": frac,
            "blocks_road": False,
            "source": "field-report",
            "source_label": "Field report (simulated for prototype)",
            "verified": True,
            "reported_at": now - (idx + 1) * 5400,
            "status": "active" if active else "resolved",
            "external_url": "",
        })
    return reports


def place_field_reports(reports: List[dict], geometries: Dict[str, List[geo.Coord]]) -> List[dict]:
    """Attach coordinates to corridor-relative field reports."""
    out = []
    for r in reports:
        line = geometries.get(r.get("corridor_id")) or []
        item = dict(r)
        if line:
            point = geo.point_at_fraction(line, r.get("fraction", 0.5))
            item["lng"], item["lat"] = point[0], point[1]
        else:
            item["lng"], item["lat"] = 91.7362, 26.1445
        out.append(item)
    return out


def _nearest_corridor(point: geo.Coord, geometries: Dict[str, List[geo.Coord]]):
    best_id, best_km = None, float("inf")
    for cid, line in geometries.items():
        if not line:
            continue
        d = geo.distance_point_to_line_km(point, line)
        if d < best_km:
            best_id, best_km = cid, d
    return best_id, best_km
