"""Simulation controller: drives the demo cascade over the live system.

The simulated landslide is injected as a real incident object, so it flows
through exactly the same pipeline as live USGS/Open-Meteo events: it blocks a
corridor, the risk model re-scores, vehicles halt, deliveries flip to at-risk,
alerts fire, and the routing engine produces scored alternatives.

Everything it creates is tagged `source: "simulation"`.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from . import network, routes_engine, seed
from .services import simulation as simulation_service

SEED_VEHICLE_BY_ID: Dict[str, dict] = {v["id"]: v for v in seed.VEHICLES}


def state(store) -> dict:
    """Simulation state enriched with the entities it touches."""
    sim = dict(store.simulation)
    sim["scenarios"] = simulation_service.scenario_list()
    sim["is_active"] = sim["phase"] not in ("idle",)
    sim["awaiting_decision"] = sim["phase"] == "awaiting-accept"

    vehicle = store.vehicles.get(sim.get("vehicle_id") or "")
    delivery = store.deliveries.get(sim.get("delivery_id") or "")
    sim["vehicle"] = _vehicle_summary(vehicle) if vehicle else None
    sim["delivery"] = _delivery_summary(delivery) if delivery else None

    incident = None
    if sim.get("incident_id"):
        incident = store.manual_incidents.get(sim["incident_id"])
    sim["incident"] = incident
    return sim


def _vehicle_summary(v: dict) -> dict:
    return {
        "id": v["id"],
        "cargo": v.get("cargo"),
        "priority": v.get("priority"),
        "status": v.get("status"),
        "driver": v.get("driver"),
        "corridor_name": v.get("corridor_name"),
        "lng": v.get("lng"), "lat": v.get("lat"),
        "eta_min": v.get("eta_min"),
        "halt_reason": v.get("halt_reason"),
        "rerouted": v.get("rerouted", False),
    }


def _delivery_summary(d: dict) -> dict:
    return {
        "id": d["id"],
        "cargo": d.get("cargo"),
        "origin": d.get("origin"),
        "destination": d.get("destination"),
        "priority": d.get("priority"),
        "status": d.get("status"),
        "reliability": d.get("reliability"),
        "risk_probability": d.get("risk_probability"),
        "eta_min": d.get("eta_min"),
        "delay_min": d.get("delay_min", 0),
        "consignee": d.get("consignee"),
        "risk_note": d.get("risk_note", ""),
    }


def start(store, scenario_id: Optional[str] = None) -> dict:
    """Inject the disruption and run the cascade up to the decision point."""
    with store.lock:
        reset(store, refresh=False)

        scenario = simulation_service.get_scenario(scenario_id)
        incident = simulation_service.build_incident(scenario, store.geometries)
        store.manual_incidents[incident["id"]] = incident

    # Outside the lock-sensitive section: recompute everything from live data.
    store.refresh_live(force=True)

    with store.lock:
        vehicle = store.vehicles.get(scenario["vehicle_id"]) or _first_vehicle_on(
            store, scenario["corridor_id"])

        sim = simulation_service.initial_state()
        sim["scenario_id"] = scenario["id"]
        sim["scenario_name"] = scenario["name"]
        sim["incident_id"] = incident["id"]
        sim["corridor_id"] = scenario["corridor_id"]
        sim["started_at"] = time.time()

        corridor_name = network.CORRIDOR_BY_ID.get(
            scenario["corridor_id"], {}).get("name", scenario["corridor_id"])

        sim = simulation_service.advance(
            sim, "running", 0, f"{incident['title']} detected on {corridor_name}.")
        sim = simulation_service.advance(
            sim, "running", 1,
            f"{corridor_name} marked blocked. Risk model re-scored all corridors.")

        options: List[dict] = []
        if vehicle:
            sim["vehicle_id"] = vehicle["id"]
            delivery_id = vehicle.get("delivery_id") or scenario.get("delivery_id")
            sim["delivery_id"] = delivery_id
            delivery = store.deliveries.get(delivery_id or "")

            sim = simulation_service.advance(
                sim, "running", 2,
                f"{vehicle['id']} ({vehicle.get('cargo')}) halted \u2014 "
                f"delivery {delivery_id} flagged at risk.")

            sim["original_eta_min"] = vehicle.get("eta_min")
            if delivery:
                delivery["simulation_flagged"] = True

            detour = scenario.get("detour") or {}
            options, provenance = routes_engine.plan_for_vehicle(
                store, vehicle,
                detour_corridors=detour.get("corridor_ids"),
                detour_label=detour.get("label", "Alternative corridor"),
                bypass={
                    "corridor_id": scenario["corridor_id"],
                    "point": (float(incident["lng"]), float(incident["lat"])),
                    "label": detour.get("bypass_label", "Diversion around the closure"),
                },
            )
            sim["routing_provenance"] = provenance

            sim = simulation_service.advance(
                sim, "running", 3,
                f"{len(options)} alternative route(s) generated and risk-scored.")
        else:
            sim = simulation_service.advance(
                sim, "running", 2, "No tracked vehicle currently on the blocked corridor.")

        sim["route_options"] = options
        recommended = next((o for o in options if o.get("recommended")), None)
        sim["recommended_route_id"] = recommended["id"] if recommended else None

        message = (
            f"Recommendation ready: {recommended['label']}. {recommended['explanation']}"
            if recommended else "Awaiting dispatcher decision."
        )
        sim = simulation_service.advance(sim, "awaiting-accept", 4, message)

        store.simulation = sim
        return state(store)


def _first_vehicle_on(store, corridor_id: str) -> Optional[dict]:
    for v in store.vehicles.values():
        if v["corridor_id"] == corridor_id:
            return v
    return None


def accept(store, route_id: Optional[str] = None) -> dict:
    """Dispatcher accepts a reroute: apply it to the vehicle and delivery."""
    with store.lock:
        sim = dict(store.simulation)
        if sim.get("phase") not in ("awaiting-accept", "running"):
            return state(store)

        options = sim.get("route_options") or []
        if not options:
            return state(store)

        option = next((o for o in options if o["id"] == route_id), None)
        if option is None:
            option = next((o for o in options if o.get("recommended")), options[0])

        vehicle = store.vehicles.get(sim.get("vehicle_id") or "")
        delivery = store.deliveries.get(sim.get("delivery_id") or "")

        sim = simulation_service.advance(
            sim, "rerouting", 5,
            f"Reroute issued to {vehicle['id'] if vehicle else 'driver'}: {option['label']}.")

        if vehicle:
            geometry = [(float(p[0]), float(p[1])) for p in option["geometry"]]
            vehicle["route_geometry"] = geometry
            vehicle["progress"] = 0.0
            vehicle["direction"] = 1
            vehicle["status"] = "moving"
            vehicle["halt_reason"] = ""
            vehicle["rerouted"] = True
            vehicle["route_label"] = option["label"]
            vehicle["active_route_id"] = option["id"]
            if option.get("corridor_ids"):
                vehicle["corridor_id"] = option["corridor_ids"][0]
            store._place_vehicle(vehicle)

        if delivery:
            original = sim.get("original_eta_min") or option["duration_min"]
            delivery["rerouted"] = True
            delivery["delay_min"] = max(0, int(option["duration_min"]) - int(original))
            delivery["reliability"] = option["reliability"]
            delivery["active_route_id"] = option["id"]
            delivery["route_label"] = option["label"]

        store.reroute_history.append({
            "at": time.time(),
            "vehicle_id": sim.get("vehicle_id"),
            "delivery_id": sim.get("delivery_id"),
            "route_id": option["id"],
            "route_label": option["label"],
            "reliability": option["reliability"],
            "delay_min": option.get("delay_vs_fastest_min", 0),
        })

        sim["selected_route_id"] = option["id"]
        sim["selected_route"] = option
        store.simulation = sim

    store.refresh_live(force=True)

    with store.lock:
        sim = dict(store.simulation)
        option = sim.get("selected_route") or {}
        sim = simulation_service.advance(
            sim, "completed", 6,
            f"Operations updated. Delivery now routed via {option.get('label', 'alternative')} "
            f"at {option.get('reliability', 0)}% reliability.")
        sim = simulation_service.complete_steps(sim)
        sim["completed_at"] = time.time()
        store.simulation = sim
        return state(store)


def decline(store) -> dict:
    """Dispatcher holds the vehicle instead of rerouting."""
    with store.lock:
        sim = dict(store.simulation)
        if sim.get("phase") != "awaiting-accept":
            return state(store)
        sim = simulation_service.advance(
            sim, "completed", 6,
            "Reroute declined. Vehicle held at safe point pending road clearance.")
        sim["declined"] = True
        sim["completed_at"] = time.time()
        store.simulation = sim
        return state(store)


def reset(store, refresh: bool = True) -> dict:
    """Remove all simulation effects and restore the seeded fleet state."""
    with store.lock:
        sim = store.simulation or {}
        incident_id = sim.get("incident_id")
        if incident_id:
            store.manual_incidents.pop(incident_id, None)
            store.incident_overrides.pop(incident_id, None)
            store.alerts.pop(f"ALERT-INC-{incident_id}", None)

        # Drop any simulation incident left over from an earlier run.
        for key in [k for k, v in store.manual_incidents.items()
                    if v.get("source") == "simulation"]:
            store.manual_incidents.pop(key, None)

        for vid, spec in SEED_VEHICLE_BY_ID.items():
            vehicle = store.vehicles.get(vid)
            if not vehicle or not vehicle.get("rerouted"):
                continue
            vehicle["route_geometry"] = None
            vehicle["rerouted"] = False
            vehicle["route_label"] = None
            vehicle["active_route_id"] = None
            vehicle["corridor_id"] = spec["corridor_id"]
            vehicle["progress"] = spec["progress"]
            vehicle["direction"] = spec["direction"]
            vehicle["status"] = "moving"
            vehicle["halt_reason"] = ""
            store._place_vehicle(vehicle)

        for d in store.deliveries.values():
            d["rerouted"] = False
            d["delay_min"] = 0
            d["active_route_id"] = None
            d["route_label"] = None
            d.pop("simulation_flagged", None)

        store.simulation = simulation_service.initial_state()

    if refresh:
        store.refresh_live(force=True)
    return state(store)
