"""Live weather + rainfall via Open-Meteo (keyless, free).

Rainfall is the single strongest driver of road disruption in the North East,
so this feeds the risk model directly. We sample a few points along each
corridor rather than one, because a 200 km mountain corridor can have very
different weather at each end.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .. import config, geo
from ..http_client import get_json, worst_provenance

# Sampling more points costs nothing extra: Open-Meteo accepts comma-separated
# coordinate lists and returns one result block per location.
SAMPLES_PER_CORRIDOR = 3


def fetch_bulk(points: List[geo.Coord]) -> Tuple[List[dict], str]:
    """Fetch weather for many points in a single request.

    Returns (per-point dicts, provenance).
    """
    if not points:
        return [], "live"

    url = _build_url(points)
    payload, provenance = get_json(
        url,
        feed="open-meteo",
        ttl=config.TTL_WEATHER,
        snapshot_key="weather",
    )

    if payload is None:
        return [_empty_point() for _ in points], provenance

    blocks = payload if isinstance(payload, list) else [payload]

    out: List[dict] = []
    for i in range(len(points)):
        block = blocks[i] if i < len(blocks) else (blocks[0] if blocks else {})
        out.append(_summarise(block))
    return out, provenance


def _build_url(points: List[geo.Coord]) -> str:
    lats = ",".join(f"{p[1]:.4f}" for p in points)
    lngs = ",".join(f"{p[0]:.4f}" for p in points)
    return config.OPEN_METEO_FORECAST + "?" + "&".join([
        f"latitude={lats}",
        f"longitude={lngs}",
        "hourly=precipitation,precipitation_probability",
        "current=temperature_2m,precipitation,weather_code,wind_speed_10m",
        "daily=precipitation_sum",
        "past_days=2",
        "forecast_days=2",
        "timezone=Asia%2FKolkata",
    ])


def _empty_point() -> dict:
    return {
        "rain_24h_mm": 0.0,
        "rain_48h_mm": 0.0,
        "rain_next_24h_mm": 0.0,
        "max_hourly_next_24h": 0.0,
        "precip_probability_max": 0,
        "temperature_c": None,
        "wind_kmh": None,
        "available": False,
    }


def _summarise(block: dict) -> dict:
    """Reduce an Open-Meteo response to the features the risk model needs."""
    if not isinstance(block, dict) or "hourly" not in block:
        return _empty_point()

    hourly = block.get("hourly") or {}
    precip = [x for x in (hourly.get("precipitation") or []) if isinstance(x, (int, float))]
    prob = [x for x in (hourly.get("precipitation_probability") or []) if isinstance(x, (int, float))]

    # past_days=2 + forecast_days=2 => index 48 is roughly "now".
    now_idx = min(48, max(0, len(precip) - 24))

    past_24 = precip[max(0, now_idx - 24):now_idx]
    past_48 = precip[max(0, now_idx - 48):now_idx]
    next_24 = precip[now_idx:now_idx + 24]
    next_prob = prob[now_idx:now_idx + 24]

    current = block.get("current") or {}

    return {
        "rain_24h_mm": round(sum(past_24), 2),
        "rain_48h_mm": round(sum(past_48), 2),
        "rain_next_24h_mm": round(sum(next_24), 2),
        "max_hourly_next_24h": round(max(next_24), 2) if next_24 else 0.0,
        "precip_probability_max": int(max(next_prob)) if next_prob else 0,
        "temperature_c": current.get("temperature_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "available": True,
    }


def corridor_weather(corridors: List[dict], geometries: Dict[str, List[geo.Coord]]) -> Tuple[Dict[str, dict], str]:
    """Weather aggregated per corridor (worst sample wins -- one blocked
    section blocks the whole corridor)."""
    points: List[geo.Coord] = []
    index: Dict[str, Tuple[int, int]] = {}

    for c in corridors:
        line = geometries.get(c["id"]) or []
        if not line:
            continue
        samples = geo.sample_points(line, SAMPLES_PER_CORRIDOR)
        index[c["id"]] = (len(points), len(samples))
        points.extend(samples)

    results, provenance = fetch_bulk(points)

    out: Dict[str, dict] = {}
    for cid, (start, count) in index.items():
        chunk = results[start:start + count] or [_empty_point()]
        out[cid] = {
            "rain_24h_mm": max(x["rain_24h_mm"] for x in chunk),
            "rain_48h_mm": max(x["rain_48h_mm"] for x in chunk),
            "rain_next_24h_mm": max(x["rain_next_24h_mm"] for x in chunk),
            "max_hourly_next_24h": max(x["max_hourly_next_24h"] for x in chunk),
            "precip_probability_max": max(x["precip_probability_max"] for x in chunk),
            "temperature_c": next((x["temperature_c"] for x in chunk if x["temperature_c"] is not None), None),
            "wind_kmh": next((x["wind_kmh"] for x in chunk if x["wind_kmh"] is not None), None),
            "available": any(x["available"] for x in chunk),
            "samples": count,
        }
    return out, provenance


def city_weather(city_keys: List[str], cities: Dict[str, dict]) -> Tuple[Dict[str, dict], str]:
    points = [(cities[k]["lng"], cities[k]["lat"]) for k in city_keys]
    results, provenance = fetch_bulk(points)
    return {k: results[i] for i, k in enumerate(city_keys) if i < len(results)}, provenance
