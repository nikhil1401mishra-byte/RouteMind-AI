"""Real road geometry and routing via OSRM (OpenStreetMap data, keyless).

Two jobs:
  1. Corridor geometry -- real OSM road shapes for the map, cached on disk.
  2. Route alternatives -- risk-aware scoring of OSRM alternatives so the
     control room can recommend a safer route, not just a shorter one.

When OSRM is unreachable we fall back to the simplified reference polylines in
network.py, and every response says which one was used.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .. import config, geo, network
from ..http_client import get_json, worst_provenance

_geometry_cache: Dict[str, List[geo.Coord]] = {}
_geometry_provenance: Dict[str, str] = {}


# ------------------------------------------------------------- geometry -----
def corridor_geometry(corridor: dict) -> Tuple[List[geo.Coord], str]:
    """Real OSM geometry for a corridor, cached in-process and on disk."""
    cid = corridor["id"]
    if cid in _geometry_cache:
        return _geometry_cache[cid], _geometry_provenance.get(cid, "cache")

    pts = network.waypoints(corridor)
    coords = ";".join(f"{lng:.5f},{lat:.5f}" for lng, lat in pts)
    url = (
        f"{config.OSRM_BASE}/route/v1/driving/{coords}"
        "?overview=full&geometries=geojson&alternatives=false&steps=false"
    )

    payload, provenance = get_json(
        url,
        feed="osrm-geometry",
        ttl=config.TTL_GEOMETRY,
        snapshot_key=f"geometry:{cid}",
    )

    line = _extract_geometry(payload)
    if not line:
        line = list(network.FALLBACK_GEOMETRY.get(cid, pts))
        provenance = "fallback-geometry"
    else:
        line = geo.simplify(line, tolerance_km=0.25)

    _geometry_cache[cid] = line
    _geometry_provenance[cid] = provenance
    return line, provenance


def all_geometries() -> Tuple[Dict[str, List[geo.Coord]], str]:
    out: Dict[str, List[geo.Coord]] = {}
    provenances: List[str] = []
    for corridor in network.CORRIDORS:
        line, prov = corridor_geometry(corridor)
        out[corridor["id"]] = line
        provenances.append("live" if prov in ("live", "cache") else "offline-snapshot")
    return out, worst_provenance(*provenances) if provenances else "unavailable"


def _extract_geometry(payload) -> List[geo.Coord]:
    if not payload or payload.get("code") != "Ok":
        return []
    routes = payload.get("routes") or []
    if not routes:
        return []
    coords = (routes[0].get("geometry") or {}).get("coordinates") or []
    return [(float(c[0]), float(c[1])) for c in coords if len(c) >= 2]


# --------------------------------------------------------------- routing ----
def route_alternatives(
    origin: geo.Coord,
    destination: geo.Coord,
    *,
    max_alternatives: int = 3,
) -> Tuple[List[dict], str]:
    """Ask OSRM for route alternatives between two points.

    Returns raw route dicts: geometry, distance_km, duration_min.
    """
    url = (
        f"{config.OSRM_BASE}/route/v1/driving/"
        f"{origin[0]:.5f},{origin[1]:.5f};{destination[0]:.5f},{destination[1]:.5f}"
        "?overview=full&geometries=geojson&alternatives=true&steps=false"
    )
    payload, provenance = get_json(
        url,
        feed="osrm-route",
        ttl=config.TTL_ROUTE,
        snapshot_key="route_generic",
    )

    routes: List[dict] = []
    if payload and payload.get("code") == "Ok":
        for r in (payload.get("routes") or [])[:max_alternatives]:
            coords = (r.get("geometry") or {}).get("coordinates") or []
            line = [(float(c[0]), float(c[1])) for c in coords if len(c) >= 2]
            if not line:
                continue
            routes.append({
                "geometry": geo.simplify(line, tolerance_km=0.25),
                "distance_km": round(float(r.get("distance", 0.0)) / 1000.0, 1),
                "duration_min": round(float(r.get("duration", 0.0)) / 60.0, 1),
                "source": "osrm",
            })

    if not routes:
        provenance = "fallback-geometry"
    return routes, provenance


def corridor_route(corridor_ids: List[str]) -> Optional[dict]:
    """Stitch a route from known corridors (offline-capable path planning)."""
    line: List[geo.Coord] = []
    distance = 0.0
    duration = 0.0

    for cid in corridor_ids:
        corridor = network.CORRIDOR_BY_ID.get(cid)
        if not corridor:
            return None
        seg, _ = corridor_geometry(corridor)
        if not seg:
            return None
        if line and geo.haversine_km(line[-1], seg[0]) > geo.haversine_km(line[-1], seg[-1]):
            seg = list(reversed(seg))
        line.extend(seg if not line else seg[1:])
        seg_km = geo.line_length_km(seg)
        distance += seg_km
        duration += (seg_km / max(15.0, corridor["free_flow_kmh"])) * 60.0

    if not line:
        return None

    return {
        "geometry": geo.simplify(line, tolerance_km=0.25),
        "distance_km": round(distance, 1),
        "duration_min": round(duration, 1),
        "source": "corridor-graph",
        "corridor_ids": corridor_ids,
    }


def corridors_near_route(line: List[geo.Coord], geometries: Dict[str, List[geo.Coord]],
                         threshold_km: float = 8.0) -> List[str]:
    """Which known corridors does this route substantially follow?

    Used to attach corridor-level risk to an arbitrary route. The thresholds
    are deliberately strict: merely passing through the same city as a
    corridor's endpoint must not count as following it, or every route out of
    a hub would inherit the risk of every road into that hub.
    """
    if not line:
        return []
    probes = geo.sample_points(line, 24)
    hits: Dict[str, int] = {}
    for cid, corridor_line in geometries.items():
        if not corridor_line:
            continue
        matched = sum(
            1 for p in probes
            if geo.distance_point_to_line_km(p, corridor_line) <= threshold_km
        )
        # At least a quarter of the route must run along the corridor.
        if matched >= 6:
            hits[cid] = matched
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    return [cid for cid, _ in ranked[:4]]


# -------------------------------------------------------------- bypasses ----
KM_PER_DEG_LAT = 111.32


def _shift(point: geo.Coord, unit: Tuple[float, float], km: float) -> geo.Coord:
    """Move a point `km` along a unit vector expressed in (dx, dy) degrees."""
    lng, lat = point
    dx, dy = unit
    dlat = (km / KM_PER_DEG_LAT) * dy
    dlng = (km / (KM_PER_DEG_LAT * max(0.2, math.cos(math.radians(lat))))) * dx
    return (lng + dlng, lat + dlat)


def _unit(a: geo.Coord, b: geo.Coord) -> Tuple[float, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    norm = math.hypot(dx, dy) or 1.0
    return (dx / norm, dy / norm)


def _nearest_index(line: List[geo.Coord], point: geo.Coord) -> int:
    return min(range(len(line)), key=lambda i: geo.haversine_km(line[i], point))


def bypass_route(corridor_id: str, incident_point: geo.Coord, *,
                 offset_km: float = 18.0, span_km: float = 30.0,
                 start: Optional[geo.Coord] = None,
                 end: Optional[geo.Coord] = None) -> Optional[dict]:
    """Build a diversion that leaves the highway before a blockage and rejoins after.

    When one corridor is the only link between two towns, the useful question
    is not "which other highway?" but "how do we get around the debris?". This
    constructs that diversion from the corridor's own geometry.

    IMPORTANT: the diversion is a *modelled* alignment, not a surveyed road.
    It is returned with source "modeled-bypass" and the UI labels it as such.
    With internet access, OSRM supplies real alternatives instead and this
    path is only a fallback.
    """
    corridor = network.CORRIDOR_BY_ID.get(corridor_id)
    if not corridor or not incident_point:
        return None

    base, _ = corridor_geometry(corridor)
    if len(base) < 2:
        return None

    # Resample so trimming and offsetting behave smoothly on sparse polylines.
    line = geo.sample_points(base, 48)

    # Orient the line so it runs from `start` towards `end`.
    if start is not None and geo.haversine_km(line[0], start) > geo.haversine_km(line[-1], start):
        line = list(reversed(line))
    elif start is None and end is not None and \
            geo.haversine_km(line[-1], end) > geo.haversine_km(line[0], end):
        line = list(reversed(line))

    # Trim to the travelled portion.
    i0 = _nearest_index(line, start) if start is not None else 0
    i1 = _nearest_index(line, end) if end is not None else len(line) - 1
    if i0 > i1:
        i0, i1 = i1, i0
    line = line[i0:i1 + 1]
    if len(line) < 3:
        line = geo.sample_points(base, 48)
    if start is not None:
        line = [start] + line
    if end is not None:
        line = line + [end]

    idx = _nearest_index(line, incident_point)

    lo = idx
    while lo > 0 and geo.haversine_km(line[lo], incident_point) < span_km:
        lo -= 1
    hi = idx
    while hi < len(line) - 1 and geo.haversine_km(line[hi], incident_point) < span_km:
        hi += 1
    if hi - lo < 2:
        lo = max(0, idx - 1)
        hi = min(len(line) - 1, idx + 1)

    along = _unit(line[lo], line[hi])
    perp = (-along[1], along[0])

    def build(sign: float, distance: float) -> List[geo.Coord]:
        direction = (perp[0] * sign, perp[1] * sign)
        mid = line[idx]
        quarter_a = line[max(lo, (lo + idx) // 2)]
        quarter_b = line[min(hi, (idx + hi) // 2)]
        detour_pts = [
            _shift(quarter_a, direction, distance * 0.55),
            _shift(mid, direction, distance),
            _shift(quarter_b, direction, distance * 0.55),
        ]
        return line[:lo + 1] + detour_pts + line[hi:]

    # Choose the side (and, if needed, the width) that actually clears the
    # incident. Verify rather than assume.
    candidate: List[geo.Coord] = []
    for distance in (offset_km, offset_km * 1.6, offset_km * 2.4):
        for sign in (1.0, -1.0):
            attempt = build(sign, distance)
            if geo.distance_point_to_line_km(incident_point, attempt) >= 8.0:
                candidate = attempt
                break
        if candidate:
            break

    if not candidate:
        return None

    geometry = geo.simplify(candidate, tolerance_km=0.25)
    length_km = geo.line_length_km(geometry)
    # A diversion runs on secondary roads: assume ~60% of highway free flow.
    speed = max(15.0, corridor["free_flow_kmh"] * 0.6)

    return {
        "geometry": geometry,
        "distance_km": round(length_km, 1),
        "duration_min": round((length_km / speed) * 60.0, 1),
        "source": "modeled-bypass",
        "corridor_ids": [corridor_id],
    }
