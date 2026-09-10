"""The demo scenario engine.

Drives the killer flow end to end:

    landslide -> corridor blocked -> critical vehicle affected ->
    delivery at risk -> alternative routes scored -> operator accepts ->
    vehicle reroutes and every panel updates.

Everything produced here is tagged `source: "simulation"` and the UI shows a
SIMULATION badge, so simulated events are never confused with the live USGS /
Open-Meteo data feeding the rest of the system.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from .. import geo, network

PHASES = ["idle", "running", "awaiting-accept", "rerouting", "completed"]

# The scenario the SIH demo runs: NH-306 landslide hits emergency medicine.
DEFAULT_SCENARIO = {
    "id": "landslide-nh306",
    "name": "Landslide on NH-306 (Silchar \u2013 Aizawl)",
    "corridor_id": "NH306-SCL-AJL",
    "fraction": 0.42,
    "incident_type": "landslide",
    "severity": "critical",
    "vehicle_id": "TR-104",
    "delivery_id": "DLV-2041",
    "detour": {
        "label": "NH-37 via Jiribam",
        "corridor_ids": ["NH37-SCL-IMF"],
    },
}

SCENARIOS = {
    DEFAULT_SCENARIO["id"]: DEFAULT_SCENARIO,
    "flood-nh27": {
        "id": "flood-nh27",
        "name": "Brahmaputra flooding on NH-27",
        "corridor_id": "NH27-GHY-DBR",
        "fraction": 0.38,
        "incident_type": "flood",
        "severity": "critical",
        "vehicle_id": "AS-27-4182",
        "delivery_id": "DLV-2028",
        "detour": {"label": "NH-39 via Dimapur", "corridor_ids": ["NH39-JRH-DMU"]},
    },
    "landslide-nh10": {
        "id": "landslide-nh10",
        "name": "Landslide on NH-10 (Siliguri \u2013 Gangtok)",
        "corridor_id": "NH10-SLG-GTK",
        "fraction": 0.55,
        "incident_type": "landslide",
        "severity": "critical",
        "vehicle_id": "SK-01-9042",
        "delivery_id": "DLV-2033",
        "detour": {"label": "Extended NH-717A detour", "corridor_ids": []},
    },
}

STEP_TEMPLATE = [
    ("detect", "Disruption detected"),
    ("assess", "Corridor impact assessed"),
    ("impact", "Affected vehicles and deliveries identified"),
    ("options", "Alternative routes generated and scored"),
    ("decision", "Awaiting dispatcher decision"),
    ("reroute", "Reroute issued to driver"),
    ("complete", "Operations updated"),
]


def initial_state() -> dict:
    return {
        "phase": "idle",
        "scenario_id": DEFAULT_SCENARIO["id"],
        "scenario_name": DEFAULT_SCENARIO["name"],
        "steps": [],
        "current_step": -1,
        "incident_id": None,
        "vehicle_id": None,
        "delivery_id": None,
        "corridor_id": None,
        "route_options": [],
        "selected_route_id": None,
        "started_at": None,
        "completed_at": None,
        "log": [],
    }


def make_steps(upto: int) -> List[dict]:
    steps = []
    for i, (key, label) in enumerate(STEP_TEMPLATE):
        steps.append({
            "key": key,
            "label": label,
            "status": "done" if i < upto else ("active" if i == upto else "pending"),
        })
    return steps


def build_incident(scenario: dict, geometries: Dict[str, List[geo.Coord]]) -> dict:
    cid = scenario["corridor_id"]
    line = geometries.get(cid) or []
    point = geo.point_at_fraction(line, scenario["fraction"]) if line else (92.70, 24.40)
    corridor = network.CORRIDOR_BY_ID.get(cid, {})

    kind = scenario["incident_type"]
    title = {
        "landslide": "Landslide blocking carriageway",
        "flood": "Carriageway submerged by flooding",
    }.get(kind, "Road blocked")

    return {
        "id": f"SIM-{scenario['id'].upper()}",
        "type": kind,
        "severity": scenario["severity"],
        "title": title,
        "description": (
            f"Simulated {kind} on {corridor.get('name', cid)}. "
            "Carriageway impassable in both directions; clearance estimated at 6-10 hours."
        ),
        "lng": point[0], "lat": point[1],
        "corridor_id": cid,
        "blocks_road": True,
        "source": "simulation",
        "source_label": "Simulated event (demo scenario)",
        "verified": True,
        "reported_at": time.time(),
        "status": "active",
        "external_url": "",
    }


def log_entry(message: str) -> dict:
    return {"at": time.time(), "message": message}


def advance(state: dict, phase: str, step_index: int, message: str) -> dict:
    state = dict(state)
    state["phase"] = phase
    state["current_step"] = step_index
    state["steps"] = make_steps(step_index)
    log = list(state.get("log") or [])
    log.append(log_entry(message))
    state["log"] = log[-12:]
    return state


def complete_steps(state: dict) -> dict:
    state = dict(state)
    state["steps"] = [dict(s, status="done") for s in make_steps(len(STEP_TEMPLATE))]
    state["current_step"] = len(STEP_TEMPLATE) - 1
    return state


def get_scenario(scenario_id: Optional[str]) -> dict:
    return SCENARIOS.get(scenario_id or "", DEFAULT_SCENARIO)


def scenario_list() -> List[dict]:
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "corridor_id": s["corridor_id"],
            "vehicle_id": s["vehicle_id"],
            "incident_type": s["incident_type"],
        }
        for s in SCENARIOS.values()
    ]
