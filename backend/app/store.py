"""Central in-memory state for the control room.

Holds the live corridor assessment, the tracked fleet, deliveries, incidents,
alerts and the simulation state machine.

Refresh strategy: lazy and time-boxed. Each API request calls `ensure_fresh()`,
which re-fetches live feeds only when the TTL expires and advances vehicle
positions by the real elapsed time. No background threads, so behaviour is
deterministic and testable.

A real deployment replaces this module with PostgreSQL + PostGIS (roadmap
Phase 2) without changing the API surface.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple

from . import config, geo, network, seed
from .http_client import feed_status, worst_provenance
from .services import alerts as alerts_service
from .services import incidents as incidents_service
from .services import risk as risk_service
from .services import routing as routing_service
from .services import seismic as seismic_service
from .services import simulation as simulation_service
from .services import traffic as traffic_service
from .services import weather as weather_service

RISK_TTL = 120.0          # seconds between live risk recomputations
MAX_TICK_SECONDS = 30.0   # clamp so a long pause does not teleport vehicles


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.geometries: Dict[str, List[geo.Coord]] = {}
        self.geometry_provenance = "unavailable"
        self.corridor_state: Dict[str, dict] = {}
        self.vehicles: Dict[str, dict] = {}
        self.deliveries: Dict[str, dict] = {}
        self.live_incidents: List[dict] = []
        self.field_reports: List[dict] = []
        self.manual_incidents: Dict[str, dict] = {}
        self.incident_overrides: Dict[str, str] = {}   # id -> status
        self.alerts: Dict[str, dict] = {}
        self.simulation = simulation_service.initial_state()
        self.provenance: Dict[str, str] = {}
        self.traffic_mode = "modeled"
        self.last_risk_refresh = 0.0
        self.last_tick = time.time()
        self.bootstrapped = False
        self.seismic_events: List[dict] = []
        self.reroute_history: List[dict] = []

    # ------------------------------------------------------------ bootstrap
    def bootstrap(self) -> None:
        with self.lock:
            if self.bootstrapped:
                return
            self.geometries, self.geometry_provenance = routing_service.all_geometries()
            self.field_reports = incidents_service.seed_field_reports()
            self._init_fleet()
            self.bootstrapped = True
        self.refresh_live(force=True)

    def _init_fleet(self) -> None:
        for spec in seed.VEHICLES:
            v = dict(spec)
            corridor = network.CORRIDOR_BY_ID[v["corridor_id"]]
            v["status"] = "moving"
            v["halt_reason"] = ""
            v["speed_kmh"] = float(corridor["free_flow_kmh"]) * 0.8
            v["rerouted"] = False
            v["route_geometry"] = None
            v["origin"] = network.CITIES[corridor["from"]]["name"]
            v["destination"] = network.CITIES[corridor["to"]]["name"]
            delivery = seed.DELIVERY_BY_VEHICLE.get(v["id"])
            v["delivery_id"] = delivery["id"] if delivery else None
            self._place_vehicle(v)
            self.vehicles[v["id"]] = v

        for spec in seed.DELIVERIES:
            d = dict(spec)
            d["status"] = "on-track"
            d["risk_probability"] = 0.0
            d["reliability"] = 90
            d["risk_note"] = ""
            d["delay_min"] = 0
            d["eta_min"] = None
            d["rerouted"] = False
            self.deliveries[d["id"]] = d

    def _place_vehicle(self, v: dict) -> None:
        line = v.get("route_geometry") or self.geometries.get(v["corridor_id"]) or []
        if not line:
            v["lng"], v["lat"], v["heading"] = 91.7362, 26.1445, 0.0
            return
        frac = v["progress"] if v["direction"] >= 0 else 1.0 - v["progress"]
        point = geo.point_at_fraction(line, v["progress"])
        v["lng"], v["lat"] = round(point[0], 5), round(point[1], 5)
        heading = geo.heading_at_fraction(line, v["progress"])
        v["heading"] = round(heading if v["direction"] >= 0 else (heading + 180) % 360, 1)

    # -------------------------------------------------------------- refresh
    def ensure_fresh(self) -> None:
        if not self.bootstrapped:
            self.bootstrap()
        self.tick()
        if time.time() - self.last_risk_refresh > RISK_TTL:
            self.refresh_live()

    def refresh_live(self, force: bool = False) -> None:
        """Re-fetch live feeds and recompute risk for every corridor."""
        with self.lock:
            if not force and time.time() - self.last_risk_refresh < RISK_TTL:
                return

            corridors = network.CORRIDORS
            weather_map, weather_prov = weather_service.corridor_weather(corridors, self.geometries)
            events, seismic_prov = seismic_service.fetch_events()
            self.seismic_events = events

            fleet_speeds = self._fleet_speeds()
            traffic_map, traffic_prov, traffic_mode = traffic_service.corridor_traffic(
                corridors, self.geometries, fleet_speeds)
            self.traffic_mode = traffic_mode

            blocked = self._blocked_corridors()

            for corridor in corridors:
                cid = corridor["id"]
                line = self.geometries.get(cid) or []
                weather = weather_map.get(cid, {})
                traffic = traffic_map.get(cid, {})

                boost = 0.0
                reasons = [r for r in self._active_incidents_for(cid) if r.get("blocks_road")]
                if reasons:
                    boost = 0.30

                assessment = risk_service.score_corridor(
                    corridor, line, weather, events, traffic, active_incident_boost=boost)

                is_blocked = cid in blocked
                self.corridor_state[cid] = {
                    "corridor_id": cid,
                    "weather": weather,
                    "traffic": traffic,
                    "risk": assessment,
                    "status": risk_service.status_for(assessment["probability"], is_blocked),
                    "block_reason": blocked.get(cid, ""),
                    "length_km": round(geo.line_length_km(line), 1) if line else 0.0,
                }

            self.provenance = {
                "weather": weather_prov,
                "seismic": seismic_prov,
                "traffic": traffic_prov,
                "geometry": self.geometry_provenance,
                "overall": worst_provenance(weather_prov, seismic_prov, self.geometry_provenance),
            }

            self.live_incidents = incidents_service.derive_from_live(
                self.corridor_state, self.geometries, events)

            self._recompute_operations()
            self._recompute_alerts()
            self.last_risk_refresh = time.time()

    def _fleet_speeds(self) -> Dict[str, List[float]]:
        out: Dict[str, List[float]] = {}
        for v in self.vehicles.values():
            if v.get("status") == "moving":
                out.setdefault(v["corridor_id"], []).append(float(v.get("speed_kmh") or 0.0))
        return out

    def _blocked_corridors(self) -> Dict[str, str]:
        blocked: Dict[str, str] = {}
        for inc in self.all_incidents(include_resolved=False):
            if inc.get("blocks_road") and inc.get("corridor_id"):
                blocked[inc["corridor_id"]] = f"{inc['title']}: {inc['description']}"
        return blocked

    def _active_incidents_for(self, corridor_id: str) -> List[dict]:
        return [i for i in self.all_incidents(include_resolved=False)
                if i.get("corridor_id") == corridor_id]

    # ----------------------------------------------------------------- tick
    def tick(self) -> None:
        """Advance vehicle positions by real elapsed time."""
        with self.lock:
            now = time.time()
            dt = min(MAX_TICK_SECONDS, max(0.0, now - self.last_tick))
            self.last_tick = now
            if dt <= 0:
                return

            # Demo-time compression: 1 real second = 40 simulated seconds, so
            # movement is visible on screen without waiting hours.
            sim_seconds = dt * 40.0

            for v in self.vehicles.values():
                if v["status"] != "moving":
                    continue
                line = v.get("route_geometry") or self.geometries.get(v["corridor_id"]) or []
                if not line:
                    continue
                length_km = geo.line_length_km(line)
                if length_km <= 0:
                    continue

                state = self.corridor_state.get(v["corridor_id"]) or {}
                traffic = state.get("traffic") or {}
                corridor = network.CORRIDOR_BY_ID.get(v["corridor_id"], {})
                effective = traffic.get("observed_kmh") or (corridor.get("free_flow_kmh", 40) * 0.8)
                v["speed_kmh"] = round(float(effective), 1)

                delta = (float(effective) * (sim_seconds / 3600.0)) / length_km
                progress = v["progress"] + delta * (1 if v["direction"] >= 0 else -1)

                # Bounce at the ends so the demo fleet keeps circulating.
                if progress >= 1.0:
                    progress = 1.0 - (progress - 1.0)
                    v["direction"] = -1
                elif progress <= 0.0:
                    progress = -progress
                    v["direction"] = 1

                v["progress"] = max(0.0, min(1.0, progress))
                self._place_vehicle(v)

    # ------------------------------------------------------------ operations
    def _recompute_operations(self) -> None:
        """Propagate corridor risk into vehicles and deliveries."""
        blocked = self._blocked_corridors()

        for v in self.vehicles.values():
            cid = v["corridor_id"]
            state = self.corridor_state.get(cid) or {}
            if cid in blocked and not v.get("rerouted"):
                if v["status"] == "moving":
                    v["status"] = "halted"
                    v["halt_reason"] = "Road blocked ahead. Awaiting reroute decision."
            elif v["status"] == "halted" and cid not in blocked:
                v["status"] = "moving"
                v["halt_reason"] = ""

            v["corridor_name"] = network.CORRIDOR_BY_ID.get(cid, {}).get("name", cid)
            v["corridor_status"] = state.get("status", "operational")
            v["risk_probability"] = (state.get("risk") or {}).get("probability", 0.0)
            v["eta_min"] = self._eta_for_vehicle(v)

        for d in self.deliveries.values():
            v = self.vehicles.get(d.get("vehicle_id") or "")
            if not v:
                continue
            state = self.corridor_state.get(v["corridor_id"]) or {}
            risk = state.get("risk") or {}
            probability = float(risk.get("probability") or 0.0)

            d["risk_probability"] = probability
            d["reliability"] = risk_service.reliability_from_probability(probability)
            d["eta_min"] = v.get("eta_min")
            d["corridor_id"] = v["corridor_id"]
            d["corridor_name"] = v.get("corridor_name")

            if state.get("status") == "blocked" and not d.get("rerouted"):
                d["status"] = "at-risk"
                d["risk_note"] = state.get("block_reason", "Corridor blocked.")
            elif probability >= 0.45:
                d["status"] = "at-risk"
                d["risk_note"] = risk.get("headline", "")
            elif d.get("delay_min", 0) > 0:
                d["status"] = "delayed"
                d["risk_note"] = f"Rerouted, {d['delay_min']} min added."
            else:
                d["status"] = "on-track"
                d["risk_note"] = ""

    def _eta_for_vehicle(self, v: dict) -> Optional[int]:
        line = v.get("route_geometry") or self.geometries.get(v["corridor_id"]) or []
        if not line:
            return None
        length_km = geo.line_length_km(line)
        remaining = length_km * (1.0 - v["progress"]) if v["direction"] >= 0 else length_km * v["progress"]
        speed = float(v.get("speed_kmh") or 0.0)
        if speed <= 1:
            return None
        return int(round((remaining / speed) * 60.0))

    def _recompute_alerts(self) -> None:
        names = {c["id"]: c["name"] for c in network.CORRIDORS}
        derived = alerts_service.derive(
            self.corridor_state,
            self.all_incidents(include_resolved=False),
            list(self.deliveries.values()),
            list(self.vehicles.values()),
            names,
        )
        self.alerts = alerts_service.merge(self.alerts, derived)

    # ------------------------------------------------------------ incidents
    def all_incidents(self, include_resolved: bool = True) -> List[dict]:
        placed_reports = incidents_service.place_field_reports(self.field_reports, self.geometries)
        combined = list(self.live_incidents) + placed_reports + list(self.manual_incidents.values())

        out = []
        for inc in combined:
            item = dict(inc)
            override = self.incident_overrides.get(item["id"])
            if override:
                item["status"] = override
            if not include_resolved and item.get("status") == "resolved":
                continue
            item["corridor_name"] = network.CORRIDOR_BY_ID.get(
                item.get("corridor_id"), {}).get("name", "")
            out.append(item)

        out.sort(key=lambda i: (incidents_service.SEVERITY_ORDER.get(i["severity"], 9),
                                -i.get("reported_at", 0)))
        return out

    def set_incident_status(self, incident_id: str, status: str) -> bool:
        with self.lock:
            known = {i["id"] for i in self.all_incidents()}
            if incident_id not in known:
                return False
            self.incident_overrides[incident_id] = status
            self.refresh_live(force=True)
            return True

    def report_incident(self, payload: dict) -> dict:
        """Operator- or field-submitted incident (mirrors the Phase 7 app)."""
        with self.lock:
            cid = payload.get("corridor_id")
            line = self.geometries.get(cid) or []
            fraction = float(payload.get("fraction", 0.5))
            if line:
                point = geo.point_at_fraction(line, fraction)
            else:
                point = (float(payload.get("lng", 91.7362)), float(payload.get("lat", 26.1445)))

            incident = {
                "id": f"MAN-{int(time.time() * 1000) % 10_000_000}",
                "type": payload.get("type", "roadblock"),
                "severity": payload.get("severity", "moderate"),
                "title": payload.get("title", "Manual incident report"),
                "description": payload.get("description", ""),
                "lng": point[0], "lat": point[1],
                "corridor_id": cid,
                "blocks_road": bool(payload.get("blocks_road", False)),
                "source": "field-report",
                "source_label": "Reported from control room",
                "verified": True,
                "reported_at": time.time(),
                "status": "active",
                "external_url": "",
            }
            self.manual_incidents[incident["id"]] = incident
            self.refresh_live(force=True)
            return incident

    # --------------------------------------------------------------- alerts
    def update_alert(self, alert_id: str, action: str, assignee: Optional[str] = None) -> Optional[dict]:
        with self.lock:
            alert = self.alerts.get(alert_id)
            if not alert:
                return None
            mapping = {
                "acknowledge": "acknowledged",
                "assign": "assigned",
                "escalate": "escalated",
                "resolve": "resolved",
            }
            if action not in mapping:
                return None
            alert["status"] = mapping[action]
            alert["updated_at"] = time.time()
            if action == "assign":
                alert["assignee"] = assignee or "Dispatcher"
            if action == "escalate":
                alert["pinned"] = True
            return alert

    def acknowledge_all_alerts(self) -> int:
        with self.lock:
            n = 0
            for alert in self.alerts.values():
                if alert["status"] == "new":
                    alert["status"] = "acknowledged"
                    alert["updated_at"] = time.time()
                    n += 1
            return n

    # ------------------------------------------------------------- metrics
    def metrics(self) -> dict:
        incidents = self.all_incidents(include_resolved=False)
        deliveries = list(self.deliveries.values())
        vehicles = list(self.vehicles.values())
        states = list(self.corridor_state.values())

        at_risk_roads = sum(1 for s in states if s["status"] == "at-risk")
        blocked_roads = sum(1 for s in states if s["status"] == "blocked")
        on_time = sum(1 for d in deliveries if d["status"] == "on-track")
        avg_risk = (sum((s.get("risk") or {}).get("probability", 0) for s in states) / len(states)
                    if states else 0.0)

        return {
            "active_vehicles": sum(1 for v in vehicles if v["status"] in ("moving", "rerouting")),
            "halted_vehicles": sum(1 for v in vehicles if v["status"] == "halted"),
            "total_vehicles": len(vehicles),
            "active_deliveries": len(deliveries),
            "deliveries_at_risk": sum(1 for d in deliveries if d["status"] in ("at-risk", "delayed")),
            "on_time_pct": int(round(100.0 * on_time / len(deliveries))) if deliveries else 100,
            "at_risk_roads": at_risk_roads,
            "blocked_roads": blocked_roads,
            "operational_roads": len(states) - at_risk_roads - blocked_roads,
            "active_incidents": len(incidents),
            "critical_incidents": sum(1 for i in incidents if i["severity"] == "critical"),
            "avg_risk": round(avg_risk, 3),
            "alerts": alerts_service.counts(list(self.alerts.values())),
        }


STORE = Store()
