"""Pure-stdlib geospatial helpers. No third-party dependencies."""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

Coord = Tuple[float, float]  # (lng, lat) -- GeoJSON order

EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: Coord, b: Coord) -> float:
    """Great-circle distance between two (lng, lat) points, in kilometres."""
    lng1, lat1 = a
    lng2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def line_length_km(coords: Sequence[Coord]) -> float:
    return sum(haversine_km(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def interpolate(a: Coord, b: Coord, t: float) -> Coord:
    """Linear interpolation between two coordinates (fine at corridor scale)."""
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def point_at_fraction(coords: Sequence[Coord], fraction: float) -> Coord:
    """Point at `fraction` (0..1) of the way along a polyline, by distance."""
    if not coords:
        raise ValueError("empty polyline")
    if len(coords) == 1:
        return coords[0]
    fraction = max(0.0, min(1.0, fraction))
    total = line_length_km(coords)
    if total <= 0:
        return coords[0]
    target = total * fraction
    walked = 0.0
    for i in range(len(coords) - 1):
        seg = haversine_km(coords[i], coords[i + 1])
        if walked + seg >= target:
            t = 0.0 if seg == 0 else (target - walked) / seg
            return interpolate(coords[i], coords[i + 1], t)
        walked += seg
    return coords[-1]


def distance_point_to_line_km(point: Coord, coords: Sequence[Coord]) -> float:
    """Approximate minimum distance from a point to a polyline."""
    best = float("inf")
    for i in range(len(coords) - 1):
        best = min(best, _point_seg_km(point, coords[i], coords[i + 1]))
    if len(coords) == 1:
        best = haversine_km(point, coords[0])
    return best


def _point_seg_km(p: Coord, a: Coord, b: Coord) -> float:
    """Point-to-segment distance using a local equirectangular projection."""
    lat0 = math.radians((a[1] + b[1]) / 2)
    kx = math.cos(lat0) * 111.32
    ky = 110.57

    px, py = (p[0] - a[0]) * kx, (p[1] - a[1]) * ky
    bx, by = (b[0] - a[0]) * kx, (b[1] - a[1]) * ky
    denom = bx * bx + by * by
    t = 0.0 if denom == 0 else max(0.0, min(1.0, (px * bx + py * by) / denom))
    dx, dy = px - bx * t, py - by * t
    return math.hypot(dx, dy)


def bbox_contains(bbox: dict, lng: float, lat: float) -> bool:
    return (
        bbox["min_lng"] <= lng <= bbox["max_lng"]
        and bbox["min_lat"] <= lat <= bbox["max_lat"]
    )


def simplify(coords: Sequence[Coord], tolerance_km: float = 0.35) -> List[Coord]:
    """Ramer-Douglas-Peucker simplification, keeps payloads small for the browser."""
    if len(coords) < 3:
        return list(coords)

    def rdp(pts: Sequence[Coord]) -> List[Coord]:
        if len(pts) < 3:
            return list(pts)
        dmax, index = 0.0, 0
        for i in range(1, len(pts) - 1):
            d = _point_seg_km(pts[i], pts[0], pts[-1])
            if d > dmax:
                dmax, index = d, i
        if dmax > tolerance_km:
            left = rdp(pts[: index + 1])
            right = rdp(pts[index:])
            return left[:-1] + right
        return [pts[0], pts[-1]]

    return rdp(list(coords))


def bearing_deg(a: Coord, b: Coord) -> float:
    """Initial bearing from a to b, degrees clockwise from north."""
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    dlon = math.radians(b[0] - a[0])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def heading_at_fraction(coords: Sequence[Coord], fraction: float) -> float:
    if len(coords) < 2:
        return 0.0
    total = line_length_km(coords)
    target = total * max(0.0, min(1.0, fraction))
    walked = 0.0
    for i in range(len(coords) - 1):
        seg = haversine_km(coords[i], coords[i + 1])
        if walked + seg >= target:
            return bearing_deg(coords[i], coords[i + 1])
        walked += seg
    return bearing_deg(coords[-2], coords[-1])


def densify(coords: Sequence[Coord], step_km: float = 8.0) -> List[Coord]:
    """Insert intermediate points so sampling along a corridor is even."""
    if len(coords) < 2:
        return list(coords)
    out: List[Coord] = [coords[0]]
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        seg = haversine_km(a, b)
        n = max(1, int(seg // step_km))
        for k in range(1, n):
            out.append(interpolate(a, b, k / n))
        out.append(b)
    return out


def sample_points(coords: Sequence[Coord], count: int) -> List[Coord]:
    """Evenly spaced sample points along a polyline (used for weather sampling)."""
    count = max(1, count)
    if count == 1:
        return [point_at_fraction(coords, 0.5)]
    return [point_at_fraction(coords, i / (count - 1)) for i in range(count)]


def centroid(coords: Iterable[Coord]) -> Coord:
    pts = list(coords)
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
