"""Risk-aware route planning and comparison (roadmap Phase 6).

Classical routers optimise for time or distance. In the North East, the fastest
route is often the one most likely to be blocked by a landslide. This module
scores each candidate route on a blended cost:

    cost = duration * (1 + w(priority) * disruption_risk)

where w rises sharply for critical cargo such as emergency medicine, so the
system will happily accept 25 extra minutes to avoid a 60% chance of being
stranded. Every option returns its own explanation.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import geo, network
from .services import risk as risk_service
from .services import routing as routing_service

# How strongly disruption risk is weighted against travel time, by cargo class.
PRIORITY_WEIGHT = {"critical": 2.4, "high": 1.5, "standard": 0.8}

BLOCKED_PENALTY_MIN = 100_000.0

# A landslide or washout closes a *point* on the network, not an entire
# highway. A detour that leaves the highway before the debris and rejoins it
# afterwards is perfectly viable, so route viability is decided by distance
# from the actual incident location -- not by the parent corridor's status.
BLOCK_PROXIMITY_KM = 6.0


def _blocking_incidents(store) -> List[dict]:
    """Active incidents that physically close the carriageway."""
    out: List[dict] = []
    for incident in store.all_incidents(include_resolved=False):
        if not incident.get("blocks_road"):
            continue
        if incident.get("lng") is None or incident.get("lat") is None:
            continue
        out.append(incident)
    return out


def _route_risk(store, geometry: List[geo.Coord], blocking=None):
    """Aggregate corridor risk along a candidate route.

    Returns (probability, blocked, blocked_reason, corridor_ids, factors).
    """
    corridor_ids = routing_service.corridors_near_route(geometry, store.geometries)

    probabilities: List[float] = []
    factors: List[dict] = []

    for cid in corridor_ids:
        state = store.corridor_state.get(cid) or {}
        risk = state.get("risk") or {}
        probabilities.append(float(risk.get("probability") or 0.0))
        if risk.get("factors") and not factors:
            factors = risk["factors"][:3]

    blocked = False
    blocked_reason = ""
    candidates = blocking if blocking is not None else _blocking_incidents(store)
    for incident in candidates:
        point = (float(incident["lng"]), float(incident["lat"]))
        if geo.distance_point_to_line_km(point, geometry) <= BLOCK_PROXIMITY_KM:
            blocked = True
            blocked_reason = incident.get("title") or "a reported road closure"
            break

    if not probabilities:
        # Unknown road outside our modelled corridors: assume moderate risk
        # rather than pretending it is safe.
        return 0.30, blocked, blocked_reason, [], []

    # A route is only as reliable as its worst link, but a long stretch of
    # moderate risk still matters, so blend max with mean.
    worst = max(probabilities)
    mean = sum(probabilities) / len(probabilities)
    return (round(0.7 * worst + 0.3 * mean, 3), blocked, blocked_reason,
            corridor_ids, factors)


def build_options(
    store,
    *,
    origin: geo.Coord,
    destination: geo.Coord,
    priority: str = "standard",
    detour_corridors: Optional[List[str]] = None,
    detour_label: str = "Alternative corridor",
    bypass: Optional[dict] = None,
) -> Tuple[List[dict], str]:
    """Generate and score route options between two points."""
    raw, provenance = routing_service.route_alternatives(origin, destination)

    # Always offer an explicit safer-corridor option so the comparison is
    # meaningful even when OSRM returns a single geometry.
    if detour_corridors:
        detour = routing_service.corridor_route(detour_corridors)
        if detour:
            detour["forced_label"] = detour_label
            raw = list(raw) + [detour]

    # When a single corridor is the only link between two towns, the useful
    # alternative is a diversion around the debris rather than a different
    # highway. Marked "modeled-bypass" so it is never mistaken for a surveyed
    # road.
    if bypass and bypass.get("corridor_id") and bypass.get("point"):
        around = routing_service.bypass_route(
            bypass["corridor_id"], bypass["point"],
            start=origin, end=destination)
        if around:
            around["forced_label"] = bypass.get("label") or "Bypass around closure"
            raw = list(raw) + [around]

    if not raw:
        return [], provenance

    options: List[dict] = []
    weight = PRIORITY_WEIGHT.get(priority, 1.0)
    blocking = _blocking_incidents(store)

    for index, candidate in enumerate(raw):
        geometry = candidate["geometry"]
        probability, blocked, blocked_reason, corridor_ids, factors = _route_risk(
            store, geometry, blocking)

        duration = float(candidate["duration_min"])
        cost = duration * (1.0 + weight * probability)
        if blocked:
            cost += BLOCKED_PENALTY_MIN

        names = [network.CORRIDOR_BY_ID[c]["name"] for c in corridor_ids
                 if c in network.CORRIDOR_BY_ID]
        label = candidate.get("forced_label") or (
            names[0] if names else f"Route option {index + 1}")

        options.append({
            "id": f"RT-{4400 + index + 1}",
            "label": label,
            "geometry": [[round(p[0], 5), round(p[1], 5)] for p in geometry],
            "distance_km": candidate["distance_km"],
            "duration_min": int(round(duration)),
            "risk_probability": probability,
            "risk_band": risk_service.band_for(probability),
            "reliability": risk_service.reliability_from_probability(probability),
            "blocked": blocked,
            "blocked_reason": blocked_reason,
            "corridor_ids": corridor_ids,
            "corridor_names": names,
            "source": candidate.get("source", "osrm"),
            "factors": factors,
            "cost": round(cost, 1),
        })

    # De-duplicate near-identical geometries returned by OSRM.
    options = _dedupe(options)

    fastest = min(o["duration_min"] for o in options)
    safest_risk = min(o["risk_probability"] for o in options)

    options.sort(key=lambda o: o["cost"])
    # Never recommend a road that is physically blocked. If every option is
    # blocked, recommend nothing and say so, rather than routing a driver
    # into a landslide.
    recommended_id = next((o["id"] for o in options if not o["blocked"]), None)

    for option in options:
        option["delay_vs_fastest_min"] = int(option["duration_min"] - fastest)
        option["recommended"] = option["id"] == recommended_id
        option["is_fastest"] = option["duration_min"] == fastest
        option["is_safest"] = option["risk_probability"] == safest_risk
        option["explanation"] = _explain(option)

    return options, provenance


def _dedupe(options: List[dict]) -> List[dict]:
    kept: List[dict] = []
    for option in options:
        duplicate = False
        for existing in kept:
            same_distance = abs(existing["distance_km"] - option["distance_km"]) < 1.5
            same_time = abs(existing["duration_min"] - option["duration_min"]) < 4
            if same_distance and same_time:
                duplicate = True
                break
        if not duplicate:
            kept.append(option)
    return kept or options[:1]


def _explain(option: dict) -> str:
    if option["blocked"]:
        reason = option.get("blocked_reason") or "a reported road closure"
        return ("Not viable: this route still passes the location of "
                + reason.lower() + ".")

    parts: List[str] = []
    delay = option["delay_vs_fastest_min"]
    pct = int(round(option["risk_probability"] * 100))

    if delay <= 0:
        parts.append("Fastest available route")
    else:
        parts.append(f"Estimated delay is {delay} minutes")

    if option["is_safest"] and delay > 0:
        parts.append(f"but it carries the lowest disruption risk of the options at {pct}%")
    else:
        parts.append(f"with {pct}% disruption risk")

    sentence = ", ".join(parts) + "."

    if option["factors"]:
        top = option["factors"][0]
        detail = top.get("detail") or top.get("label", "")
        sentence += f" Main risk driver: {top.get('label', '').lower()} ({detail})."

    sentence += f" Route reliability {option['reliability']}%."
    return sentence


def plan_for_vehicle(store, vehicle: dict, *, detour_corridors=None,
                     detour_label="Alternative corridor",
                     bypass=None) -> Tuple[List[dict], str]:
    """Plan options from a vehicle's current GPS position to its destination."""
    corridor = network.CORRIDOR_BY_ID.get(vehicle["corridor_id"])
    if not corridor:
        return [], "unavailable"

    origin = (float(vehicle["lng"]), float(vehicle["lat"]))
    dest_key = corridor["to"] if vehicle.get("direction", 1) >= 0 else corridor["from"]
    destination = network.city_coord(dest_key)

    options, provenance = build_options(
        store,
        origin=origin,
        destination=destination,
        priority=vehicle.get("priority", "standard"),
        detour_corridors=detour_corridors,
        detour_label=detour_label,
        bypass=bypass,
    )

    if options:
        return options, provenance

    # Last resort: the public router was unreachable and no detour was supplied.
    # Fall back to the vehicle's own corridor geometry so the operator still
    # sees the current plan instead of an empty comparison panel.
    return build_options(
        store,
        origin=origin,
        destination=destination,
        priority=vehicle.get("priority", "standard"),
        detour_corridors=[vehicle["corridor_id"]],
        detour_label=vehicle.get("corridor_name") or corridor["name"],
        bypass=bypass,
    )
