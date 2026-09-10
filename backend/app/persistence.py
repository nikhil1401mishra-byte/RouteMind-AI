"""Bridge between the live in-memory control room state and the database.

Division of responsibility (deliberate, and documented in docs/data-model.md):

* The store keeps fast-moving derived state in memory - vehicle positions are
  recomputed on a 2 second tick and would be pure write amplification in a
  table.
* The database is the system of record for everything durable: operator
  accounts, sessions, roads, segments, depots, inventory, vehicles, deliveries,
  incidents, field reports, risk predictions, route plans, simulation runs,
  alerts and the audit log.

Everything written here carries a `data_class` of REAL, SIMULATED, DERIVED or
PREDICTED so a reader can always tell an observation from a model output.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional

from . import auth, config, network, seed
from .db import bbox_of, get_engine, line_geojson, new_id, point_geojson, repo

_accounts_ready = False
_reference_ready = False
_last_risk_sync = 0.0
_warnings: List[str] = []

SEVERITIES = ("critical", "high", "moderate", "low")
INCIDENT_STATUSES = ("active", "acknowledged", "resolved")

# How each incident source maps onto the real / simulated / derived / predicted
# vocabulary the UI shows next to every number.
SOURCE_CLASS = {
    "usgs-live": "REAL",
    "open-meteo-derived": "DERIVED",
    "risk-model": "PREDICTED",
    "field-report": "REAL",
    "simulation": "SIMULATED",
}


def classify(source: str) -> str:
    return SOURCE_CLASS.get((source or "").strip(), "DERIVED")


def _severity(value: Any) -> str:
    value = (str(value or "")).strip().lower()
    return value if value in SEVERITIES else "moderate"


def _status(value: Any) -> str:
    value = (str(value or "")).strip().lower()
    return value if value in INCIDENT_STATUSES else "active"


# The seed fixtures use operator-facing wording ("critical", "normal"); the
# schema uses supply wording. Translate rather than silently dropping rows.
INVENTORY_STATUS = {
    "critical": "shortage", "shortage": "shortage", "out": "shortage",
    "low": "watch", "watch": "watch", "warning": "watch",
    "normal": "ok", "ok": "ok", "healthy": "ok", "stable": "ok",
    "surplus": "surplus", "high": "surplus", "excess": "surplus",
}


def _inventory_status(value: Any, stock_days: Any) -> str:
    mapped = INVENTORY_STATUS.get(str(value or "").strip().lower())
    if mapped:
        return mapped
    try:
        days = float(stock_days or 0)
    except (TypeError, ValueError):
        return "ok"
    if days < 3:
        return "shortage"
    if days < 6:
        return "watch"
    if days > 12:
        return "surplus"
    return "ok"


def _note(message: str) -> None:
    """Record a persistence warning instead of taking down a read request."""
    if message not in _warnings:
        _warnings.append(message)
        del _warnings[:-50]


def warnings() -> List[str]:
    return list(_warnings)


def _coords(geometry: Any) -> List[List[float]]:
    """Accept either a raw coordinate list or a GeoJSON-ish dict."""
    if isinstance(geometry, dict):
        geometry = geometry.get("coordinates") or geometry.get("geometry") or []
    if not isinstance(geometry, (list, tuple)):
        return []
    out = []
    for point in geometry:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            out.append([float(point[0]), float(point[1])])
    return out


# ------------------------------------------------------------------ accounts
def ensure_accounts() -> None:
    """Create the four operator accounts once per process."""
    global _accounts_ready
    if _accounts_ready:
        return
    auth.ensure_seed_users()
    _accounts_ready = True


# ----------------------------------------------------------- reference data
def ensure_reference_data(store) -> None:
    """Persist the road network and fleet once the store has bootstrapped."""
    global _reference_ready
    if _reference_ready or not getattr(store, "bootstrapped", False):
        return

    ensure_accounts()

    roads = repo("roads")
    segments = repo("road_segments")
    depots = repo("depots")
    inventory = repo("inventory_items")
    vehicles = repo("vehicles")
    deliveries = repo("deliveries")

    for corridor in network.CORRIDORS:
        cid = corridor["id"]
        try:
            _write_corridor(corridor, cid, store, roads, segments)
        except Exception as exc:
            _note("roads/" + cid + ": " + str(exc))

    for depot in seed.DEPOTS:
        try:
            _write_depot(depot, depots)
        except Exception as exc:
            _note("depots/" + str(depot.get("id")) + ": " + str(exc))

    for index, item in enumerate(getattr(seed, "INVENTORY", [])):
        try:
            _write_inventory(item, index, inventory)
        except Exception as exc:
            _note("inventory/" + str(item.get("item")) + ": " + str(exc))

    for vehicle in store.vehicles.values():
        try:
            _write_vehicle(vehicle, vehicles)
        except Exception as exc:
            _note("vehicles/" + str(vehicle.get("id")) + ": " + str(exc))

    for delivery in store.deliveries.values():
        try:
            _write_delivery(delivery, deliveries)
        except Exception as exc:
            _note("deliveries/" + str(delivery.get("id")) + ": " + str(exc))

    _reference_ready = True


def _write_corridor(corridor, cid, store, roads, segments) -> None:
    if True:
        roads.upsert({
            "id": cid,
            "name": corridor["name"],
            "ref": cid.split("-")[0],
            "classification": "national-highway",
            "from_city": network.CITIES[corridor["from"]]["name"],
            "to_city": network.CITIES[corridor["to"]]["name"],
            "free_flow_kmh": float(corridor.get("free_flow_kmh") or 0),
            "condition": str(corridor.get("condition", "")),
            "data_class": "REAL",
            "source": "NER national highway network (curated)",
        })

        coords = _coords((store.geometries or {}).get(cid))
        if coords:
            box = bbox_of(coords)
            raw_prov = getattr(store, "geometry_provenance", "")
            provenance = (raw_prov.get(cid, "") if isinstance(raw_prov, dict)
                          else str(raw_prov or ""))
            segments.upsert({
                "id": cid + "-SEG-1",
                "road_id": cid,
                "seq": 1,
                "name": corridor["name"],
                "free_flow_kmh": float(corridor.get("free_flow_kmh") or 0),
                "condition": str(corridor.get("condition", "")),
                "geom_json": line_geojson(coords),
                "min_lng": box["min_lng"], "min_lat": box["min_lat"],
                "max_lng": box["max_lng"], "max_lat": box["max_lat"],
                # Straight-line fallback geometry is not survey data and is
                # labelled as such. Phase 3 replaces it with real OSM shapes.
                "data_class": "REAL" if "osrm" in str(provenance) else "DERIVED",
                "source": str(provenance or "unknown"),
            })


def _write_depot(depot, depots) -> None:
    if True:
        city = network.CITIES.get(depot["city"]) or {}
        lng = float(city.get("lng") or 0.0)
        lat = float(city.get("lat") or 0.0)
        depots.upsert({
            "id": depot["id"],
            "name": depot["name"],
            "lng": lng,
            "lat": lat,
            "geom_json": point_geojson(lng, lat),
            "capacity_pct": float(depot.get("capacity_pct") or 0),
            "data_class": "SIMULATED",
        })


def _write_inventory(item, index, inventory) -> None:
    if True:
        inventory.upsert({
            "id": item["depot_id"] + "-ITEM-" + str(index + 1),
            "depot_id": item["depot_id"],
            "item": item["item"],
            "stock_days": float(item.get("stock_days") or 0),
            "status": _inventory_status(item.get("status"), item.get("stock_days")),
            "data_class": "SIMULATED",
        })


def _write_vehicle(vehicle, vehicles) -> None:
    if True:
        vehicles.upsert({
            "id": vehicle["id"],
            "plate": vehicle.get("plate"),
            "driver": vehicle.get("driver"),
            "phone": vehicle.get("phone"),
            "cargo": vehicle.get("cargo"),
            "cargo_category": vehicle.get("type"),
            "capacity_tonnes": float(vehicle.get("payload_t") or 0),
            "cold_chain": bool(vehicle.get("cold_chain")),
            "priority": vehicle.get("priority"),
            "status": vehicle.get("status"),
            "corridor_id": vehicle.get("corridor_id"),
            "lng": vehicle.get("lng"),
            "lat": vehicle.get("lat"),
            "rerouted": bool(vehicle.get("rerouted")),
            "data_class": "SIMULATED",
        })


def _write_delivery(delivery, deliveries) -> None:
    if True:
        deliveries.upsert({
            "id": delivery["id"],
            "vehicle_id": delivery.get("vehicle_id"),
            "cargo": delivery.get("cargo"),
            "origin": delivery.get("origin"),
            "destination": delivery.get("destination"),
            "consignee": delivery.get("consignee"),
            "priority": delivery.get("priority"),
            "sla_hours": float(delivery.get("sla_hours") or 0),
            "status": delivery.get("status"),
            "data_class": "SIMULATED",
        })


# ------------------------------------------------------------------ syncing
def sync_live(store) -> bool:
    """Persist derived state after a risk refresh. Cheap no-op between refreshes."""
    global _last_risk_sync
    ensure_reference_data(store)
    stamp = float(getattr(store, "last_risk_refresh", 0.0) or 0.0)
    if stamp <= _last_risk_sync:
        return False
    _last_risk_sync = stamp

    record_incidents(store.all_incidents(include_resolved=True))
    record_alerts(store.alerts.values())
    record_risk_predictions(store.corridor_state)
    record_fleet(store)
    return True


def record_fleet(store) -> None:
    vehicles = repo("vehicles")
    deliveries = repo("deliveries")
    for vehicle in store.vehicles.values():
        vehicles.update(vehicle["id"], {
            "status": vehicle.get("status"),
            "corridor_id": vehicle.get("corridor_id"),
            "lng": vehicle.get("lng"),
            "lat": vehicle.get("lat"),
            "eta_min": int(vehicle.get("eta_min") or 0),
            "rerouted": bool(vehicle.get("rerouted")),
        })
    for delivery in store.deliveries.values():
        deliveries.update(delivery["id"], {
            "status": delivery.get("status"),
            "eta_min": int(delivery.get("eta_min") or 0),
            "delay_min": int(delivery.get("delay_min") or 0),
            "reliability": float(delivery.get("reliability") or 0),
            "risk_probability": float(delivery.get("risk_probability") or 0),
        })


# ---------------------------------------------------------------- incidents
def record_incident(incident: Dict[str, Any],
                    principal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lng = incident.get("lng")
    lat = incident.get("lat")
    row = {
        "id": incident["id"],
        "corridor_id": incident.get("corridor_id"),
        "type": incident.get("type") or "incident",
        "severity": _severity(incident.get("severity")),
        "title": incident.get("title") or "Incident",
        "description": incident.get("description"),
        "lng": lng,
        "lat": lat,
        "geom_json": point_geojson(float(lng), float(lat))
        if lng is not None and lat is not None else None,
        "blocks_road": bool(incident.get("blocks_road")),
        "status": _status(incident.get("status")),
        "verified": bool(incident.get("verified")),
        "source": incident.get("source"),
        "source_label": incident.get("source_label"),
        "data_class": classify(incident.get("source")),
        "external_url": incident.get("external_url") or None,
        "reported_at": float(incident.get("reported_at") or time.time()),
        "ingested_at": time.time(),
    }
    if principal and principal.get("user_id"):
        row["reported_by"] = principal["user_id"]
    return repo("incidents").upsert(row)


def record_incidents(incidents: Iterable[Dict[str, Any]]) -> int:
    count = 0
    for incident in incidents:
        try:
            record_incident(incident)
            count += 1
        except Exception:
            continue
    return count


def record_incident_status(incident_id: str, status: str) -> None:
    patch: Dict[str, Any] = {"status": _status(status)}
    if status == "resolved":
        patch["resolved_at"] = time.time()
    repo("incidents").update(incident_id, patch)


def record_field_report(incident: Dict[str, Any],
                        principal: Optional[Dict[str, Any]] = None,
                        client_uuid: str = "") -> Optional[Dict[str, Any]]:
    """Store the operator/field submission behind a manually reported incident.

    `client_uuid` is the field app's idempotency key: a repeat sync of the same
    report is recorded as a duplicate instead of creating a second incident.
    """
    reports = repo("field_reports")
    if client_uuid:
        existing = reports.all("client_uuid = ?", (client_uuid,))
        if existing:
            return existing[0]
    row = {
        "id": new_id("FR"),
        "client_uuid": client_uuid or None,
        "incident_id": incident.get("id"),
        "corridor_id": incident.get("corridor_id"),
        "type": incident.get("type") or "incident",
        "severity": _severity(incident.get("severity")),
        "description": incident.get("description"),
        "lng": incident.get("lng"),
        "lat": incident.get("lat"),
        "captured_at": float(incident.get("reported_at") or time.time()),
        "synced_at": time.time(),
        "sync_state": "synced",
        "data_class": "REAL",
    }
    if principal and principal.get("user_id"):
        row["reporter_id"] = principal["user_id"]
    return reports.insert(row)


# ------------------------------------------------------------------- alerts
def _alert_entity(related: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    related = related or {}
    for key, entity in (("delivery_id", "delivery"), ("vehicle_id", "vehicle"),
                        ("incident_id", "incident"), ("corridor_id", "corridor")):
        if related.get(key):
            return {"entity_type": entity, "entity_id": str(related[key])}
    return {"entity_type": None, "entity_id": None}


def record_alert(alert: Dict[str, Any],
                 principal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    related = alert.get("related") or {}
    entity = _alert_entity(related)
    row = {
        "id": alert["id"],
        "alert_key": alert["id"],           # ids are already stable dedupe keys
        "severity": _severity(alert.get("severity")),
        "status": alert.get("status") or "new",
        "title": alert.get("title") or "Alert",
        "body": alert.get("body"),
        "entity_type": entity["entity_type"],
        "entity_id": entity["entity_id"],
        "corridor_id": related.get("corridor_id"),
        "assignee_name": alert.get("assignee"),
        "source": "alert-engine",
        "data_class": "DERIVED",
        "created_at": float(alert.get("created_at") or time.time()),
    }
    if alert.get("status") in ("acknowledged", "assigned", "escalated"):
        row["acknowledged_at"] = float(alert.get("updated_at") or time.time())
    if alert.get("status") == "resolved":
        row["resolved_at"] = float(alert.get("updated_at") or time.time())
    return repo("alerts").upsert(row)


def record_alerts(alerts: Iterable[Dict[str, Any]]) -> int:
    count = 0
    for alert in alerts:
        try:
            record_alert(alert)
            count += 1
        except Exception:
            continue
    return count


# -------------------------------------------------------- risk predictions
def record_risk_predictions(corridor_state: Dict[str, Any]) -> int:
    predictions = repo("risk_predictions")
    stamp = time.time()
    bucket = str(int(stamp))
    count = 0
    for cid, state in (corridor_state or {}).items():
        risk = (state or {}).get("risk") or {}
        if not risk:
            continue
        try:
            predictions.upsert({
                "id": "RP-" + cid + "-" + bucket,
                "corridor_id": cid,
                "probability": float(risk.get("probability") or 0.0),
                "band": risk.get("band") or "low",
                "window_hours": int(risk.get("window_hours") or 24),
                "model_version": str(risk.get("model") or "heuristic-v1"),
                "model_kind": "transparent-heuristic",
                "factors_json": json.dumps(risk.get("factors") or []),
                "data_class": "PREDICTED",
                "predicted_at": stamp,
            })
            count += 1
        except Exception:
            continue
    return count


# ------------------------------------------------------------- route plans
def record_route_plan(payload: Dict[str, Any],
                      principal: Optional[Dict[str, Any]] = None,
                      store=None) -> Optional[str]:
    options = payload.get("options") or []
    if not options:
        return None

    plan_id = new_id("PLAN")
    vehicle_id = payload.get("vehicle_id")
    delivery_id = None
    if store is not None and vehicle_id:
        vehicle = store.vehicles.get(vehicle_id) or {}
        delivery_id = vehicle.get("delivery_id")

    routing_provenance = payload.get("routing_provenance")
    if not isinstance(routing_provenance, str):
        routing_provenance = json.dumps(routing_provenance or {})
    provenance = payload.get("provenance")
    if not isinstance(provenance, str):
        provenance = json.dumps(provenance or {})

    repo("route_plans").insert({
        "id": plan_id,
        "vehicle_id": vehicle_id,
        "delivery_id": delivery_id,
        "requested_by": (principal or {}).get("user_id"),
        "priority": payload.get("priority"),
        "provenance": provenance[:2000],
        "routing_provenance": routing_provenance[:2000],
    })

    rows = repo("route_options")
    for option in options:
        coords = _coords(option.get("geometry"))
        rows.insert({
            "id": plan_id + "::" + str(option.get("id") or new_id("RT")),
            "plan_id": plan_id,
            "label": option.get("label"),
            "source": option.get("source"),
            "distance_km": float(option.get("distance_km") or 0),
            "eta_min": int(option.get("duration_min") or 0),
            "risk_probability": float(option.get("risk_probability") or 0),
            "reliability": float(option.get("reliability") or 0),
            "blocked": bool(option.get("blocked")),
            "recommended": bool(option.get("recommended")),
            "score_time": float(option.get("duration_min") or 0),
            "score_risk": float(option.get("risk_probability") or 0),
            "score_reliability": float(option.get("reliability") or 0) / 100.0,
            "score_total": float(option.get("cost") or 0),
            "explanation": option.get("explanation"),
            "geom_json": line_geojson(coords) if coords else None,
        })
    return plan_id


# --------------------------------------------------------- simulation runs
def record_simulation(sim: Dict[str, Any],
                      principal: Optional[Dict[str, Any]] = None,
                      committed: bool = False) -> Optional[str]:
    if not sim or not sim.get("scenario_id"):
        return None
    run_id = sim.get("run_id") or ("SIM-" + str(sim.get("scenario_id"))
                                   + "-" + str(int(float(sim.get("started_at")
                                                          or time.time()))))
    repo("simulation_runs").upsert({
        "id": run_id,
        "scenario_id": str(sim.get("scenario_id")),
        "name": sim.get("scenario_name"),
        "phase": str(sim.get("phase") or "idle"),
        "committed": bool(committed),
        "created_by": (principal or {}).get("user_id"),
        "started_at": float(sim.get("started_at") or time.time()),
        "decided_at": time.time() if sim.get("phase") == "completed" else None,
        "accepted_route_id": sim.get("selected_route_id"),
        "impact_json": json.dumps(sim.get("impact") or {}),
        "log_json": json.dumps(sim.get("log") or []),
    })
    return run_id


# --------------------------------------------------------------- reporting
def storage_info() -> Dict[str, Any]:
    engine = get_engine()
    info: Dict[str, Any] = {
        "backend": engine.dialect,
        "spatial": "PostGIS geometry columns" if engine.dialect == "postgres"
        else "GeoJSON columns with bounding-box indexes",
        "system_of_record": [
            "users", "incidents", "field_reports", "alerts", "risk_predictions",
            "route_plans", "simulation_runs", "audit_log",
        ],
        "in_memory_only": ["vehicle tick positions", "live feed cache"],
        "warnings": warnings(),
    }
    if engine.dialect == "sqlite":
        info["path"] = str(config.SQLITE_PATH)
    return info


def counts() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for table in ("users", "roads", "road_segments", "depots", "inventory_items",
                  "vehicles", "deliveries", "incidents", "field_reports",
                  "alerts", "risk_predictions", "route_plans", "route_options",
                  "simulation_runs", "audit_log"):
        try:
            out[table] = repo(table).count()
        except Exception:
            out[table] = -1
    return out


def reset_caches() -> None:
    """Used by tests after swapping the database file."""
    global _accounts_ready, _reference_ready, _last_risk_sync
    _accounts_ready = False
    _reference_ready = False
    _last_risk_sync = 0.0
    del _warnings[:]
