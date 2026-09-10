"""Framework-agnostic API router.

`handle(method, path, query, body, headers) -> (status, payload)` is the single
entry point. Both server adapters (stdlib `http.server` and optional FastAPI)
call it, so there is exactly one implementation of the API - and exactly one
place where authorization is enforced.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from . import auth, config, geo, network, persistence, routes_engine, seed, simctl
from .db import DatabaseError, ValidationError, repo
from .http_client import feed_status
from .services import risk as risk_service
from .services import traffic as traffic_service
from .store import STORE

Json = Dict[str, Any]

ENDPOINTS = [
    "GET  /api/health",
    "GET  /api/auth/me",
    "POST /api/auth/login",
    "POST /api/auth/logout",
    "GET  /api/audit",
    "GET  /api/system/status",
    "GET  /api/overview",
    "GET  /api/map",
    "GET  /api/corridors",
    "GET  /api/corridors/{id}",
    "GET  /api/risk/{corridor_id}",
    "GET  /api/model-card",
    "GET  /api/vehicles",
    "GET  /api/vehicles/{id}",
    "GET  /api/deliveries",
    "GET  /api/incidents",
    "POST /api/incidents",
    "POST /api/incidents/{id}/status",
    "GET  /api/alerts",
    "POST /api/alerts/{id}/action",
    "POST /api/alerts/acknowledge-all",
    "POST /api/routes/plan",
    "GET  /api/traffic",
    "GET  /api/inventory",
    "GET  /api/simulation",
    "GET  /api/simulation/scenarios",
    "POST /api/simulation/start",
    "POST /api/simulation/accept",
    "POST /api/simulation/decline",
    "POST /api/simulation/reset",
]


# --------------------------------------------------------------- serialisers
def _geometry(cid: str) -> List[List[float]]:
    line = STORE.geometries.get(cid) or []
    return [[round(p[0], 5), round(p[1], 5)] for p in line]


def _risk_summary(risk: Json) -> Json:
    factors = risk.get("factors") or []
    return {
        "probability": risk.get("probability", 0.0),
        "band": risk.get("band", "low"),
        "headline": risk.get("headline", ""),
        "window_hours": risk.get("window_hours", 24),
        "model": risk.get("model", "heuristic-v1"),
        "top_factor": factors[0].get("label", "") if factors else "",
    }


def _corridor_payload(cid: str, *, include_geometry: bool = True,
                      full_risk: bool = False) -> Json:
    corridor = network.CORRIDOR_BY_ID[cid]
    state = STORE.corridor_state.get(cid) or {}
    risk = state.get("risk") or {}

    payload: Json = {
        "id": cid,
        "name": corridor["name"],
        "from": network.CITIES[corridor["from"]]["name"],
        "to": network.CITIES[corridor["to"]]["name"],
        "states": sorted({network.CITIES[corridor["from"]]["state"],
                          network.CITIES[corridor["to"]]["state"]}),
        "lanes": corridor["lanes"],
        "length_km": state.get("length_km", 0.0),
        "status": state.get("status", "operational"),
        "block_reason": state.get("block_reason", ""),
        "weather": state.get("weather", {}),
        "traffic": state.get("traffic", {}),
        "terrain_index": corridor["terrain"],
        "condition_index": corridor["condition"],
        "seismic_zone": corridor["seismic"],
        "incidents_per_year": corridor["history"],
        "risk": risk if full_risk else _risk_summary(risk),
    }
    if include_geometry:
        payload["geometry"] = _geometry(cid)
    return payload


def _vehicle_payload(v: Json, *, detail: bool = False) -> Json:
    payload = {
        "id": v["id"],
        "plate": v.get("plate"),
        "type": v.get("type"),
        "cargo": v.get("cargo"),
        "priority": v.get("priority"),
        "status": v.get("status"),
        "driver": v.get("driver"),
        "phone": v.get("phone"),
        "payload_t": v.get("payload_t"),
        "cold_chain": v.get("cold_chain", False),
        "lng": v.get("lng"), "lat": v.get("lat"),
        "heading": v.get("heading", 0),
        "speed_kmh": v.get("speed_kmh"),
        "eta_min": v.get("eta_min"),
        "origin": v.get("origin"),
        "destination": v.get("destination"),
        "corridor_id": v.get("corridor_id"),
        "corridor_name": v.get("corridor_name"),
        "corridor_status": v.get("corridor_status"),
        "risk_probability": v.get("risk_probability", 0.0),
        "delivery_id": v.get("delivery_id"),
        "halt_reason": v.get("halt_reason", ""),
        "rerouted": v.get("rerouted", False),
        "route_label": v.get("route_label"),
        "progress": round(float(v.get("progress", 0.0)), 4),
        "simulated_entity": True,
    }
    if detail and v.get("route_geometry"):
        payload["route_geometry"] = [[round(p[0], 5), round(p[1], 5)]
                                     for p in v["route_geometry"]]
    return payload


def _delivery_payload(d: Json) -> Json:
    return {
        "id": d["id"],
        "cargo": d.get("cargo"),
        "origin": d.get("origin"),
        "destination": d.get("destination"),
        "priority": d.get("priority"),
        "status": d.get("status"),
        "consignee": d.get("consignee"),
        "units": d.get("units"),
        "sla_hours": d.get("sla_hours"),
        "vehicle_id": d.get("vehicle_id"),
        "corridor_id": d.get("corridor_id"),
        "corridor_name": d.get("corridor_name"),
        "risk_probability": d.get("risk_probability", 0.0),
        "reliability": d.get("reliability", 0),
        "eta_min": d.get("eta_min"),
        "delay_min": d.get("delay_min", 0),
        "risk_note": d.get("risk_note", ""),
        "rerouted": d.get("rerouted", False),
        "route_label": d.get("route_label"),
        "simulated_entity": True,
    }


def _city_payload() -> List[Json]:
    return [
        {"key": key, "name": c["name"], "state": c["state"],
         "lng": c["lng"], "lat": c["lat"], "major": c["major"]}
        for key, c in network.CITIES.items()
    ]


def _depot_payload() -> List[Json]:
    out = []
    for depot in seed.DEPOTS:
        city = network.CITIES.get(depot["city"], {})
        out.append({
            "id": depot["id"], "name": depot["name"],
            "capacity_pct": depot["capacity_pct"],
            "lng": city.get("lng"), "lat": city.get("lat"),
            "city": city.get("name", depot["city"]),
        })
    return out


def _provenance_block() -> Json:
    return {
        "sources": STORE.provenance,
        "feeds": feed_status(),
        "traffic_mode": STORE.traffic_mode,
        "traffic_notice": traffic_service.traffic_notice(STORE.traffic_mode),
        "offline_mode": config.OFFLINE,
        "last_refresh": STORE.last_risk_refresh,
        "server_time": time.time(),
    }


MODEL_CARD = {
    "name": "RouteMind disruption risk model",
    "version": "heuristic-v1",
    "kind": "Transparent weighted scoring model",
    "is_trained_ml": False,
    "honest_statement": (
        "This prototype scores disruption risk with a transparent weighted model over "
        "live rainfall, terrain, historical incident density, road condition, river "
        "proximity, recent seismic activity and congestion. It is NOT a trained "
        "machine-learning model: no labelled historical disruption dataset ships with "
        "the prototype, so every factor weight is a documented assumption rather than "
        "a learned parameter."
    ),
    "inputs": [
        {"feature": "rainfall", "source": "Open-Meteo live forecast + past 48h", "live": True},
        {"feature": "terrain", "source": "Curated slope index per corridor", "live": False},
        {"feature": "history", "source": "Public reporting of annual disruptions", "live": False},
        {"feature": "condition", "source": "Curated surface condition index", "live": False},
        {"feature": "river", "source": "Curated flood exposure index", "live": False},
        {"feature": "seismic", "source": "USGS live earthquake feed", "live": True},
        {"feature": "traffic", "source": "OSRM/fleet-derived congestion, or TomTom if keyed", "live": True},
    ],
    "weights": risk_service.WEIGHTS,
    "output": {
        "probability": "0-1 disruption probability over the prediction window",
        "window_hours": 24,
        "factors": "Ranked per-factor contributions with human-readable detail",
    },
    "phase5_plan": (
        "Replace the weighted sum with a gradient-boosted classifier (XGBoost/LightGBM) "
        "trained on historical corridor closures. Evaluation: time-based split, "
        "precision/recall at operational thresholds, PR-AUC and Brier score against a "
        "persistence baseline, with SHAP values replacing the hand-set weights. The API "
        "contract (probability, window_hours, factors) stays identical so the frontend "
        "does not change."
    ),
}


# ------------------------------------------------------------------- routing
def handle(method: str, path: str, query: Optional[Json] = None,
           body: Optional[Json] = None,
           headers: Optional[Dict[str, str]] = None) -> Tuple[int, Json]:
    """Resolve the caller, then dispatch.

    Authorization is decided here, on the server. A role sent by the browser is
    never trusted - the acting role comes from the session token, or in demo
    mode from the seeded account the request maps to.
    """
    query = query or {}
    body = body or {}
    method = method.upper()
    path = "/" + path.strip("/")

    if path in ("/api", "/api/"):
        return 200, {"service": "RouteMind AI", "endpoints": ENDPOINTS}

    if path == "/api/health":
        return 200, {"ok": True, "bootstrapped": STORE.bootstrapped,
                     "server_time": time.time()}

    try:
        persistence.ensure_accounts()
        principal = auth.principal_from_headers(headers)
        handled = _auth_routes(method, path, body, headers, principal)
        if handled is not None:
            return handled
        return _dispatch(method, path, query, body, principal)
    except auth.AuthError as exc:
        code = "forbidden" if exc.status == 403 else "unauthorized"
        return exc.status, {"error": exc.message, "code": code}
    except ValidationError as exc:
        return 400, {"error": str(exc)}
    except DatabaseError as exc:
        return 503, {"error": "Storage unavailable: " + str(exc)}


def _header(headers: Optional[Dict[str, str]], name: str) -> str:
    for key, value in (headers or {}).items():
        if str(key).lower() == name:
            return str(value)
    return ""


def _auth_routes(method: str, path: str, body: Json,
                 headers: Optional[Dict[str, str]],
                 principal: Json) -> Optional[Tuple[int, Json]]:
    if path == "/api/auth/me":
        return 200, {
            "user": principal,
            "permissions": auth.permissions_for(principal),
            "auth": auth.describe(),
        }

    if path == "/api/auth/login":
        if method != "POST":
            return 405, {"error": "POST required"}
        user = auth.authenticate(body.get("username", ""), body.get("password", ""))
        token, expires = auth.create_session(user["id"], _header(headers, "user-agent"))
        auth.audit(principal, "auth.login", "user", user["id"])
        return 200, {
            "token": token,
            "expires_at": expires,
            "user": {
                "id": user["id"], "username": user["username"],
                "full_name": user["full_name"], "role": user["role"],
                "role_label": auth.ROLE_LABEL.get(user["role"], user["role"]),
            },
        }

    if path == "/api/auth/logout":
        token = _header(headers, "x-routemind-token")
        bearer = _header(headers, "authorization")
        if bearer.lower().startswith("bearer "):
            token = bearer[7:].strip()
        auth.audit(principal, "auth.logout")
        return 200, {"ok": auth.destroy_session(token)}

    return None


def _dispatch(method: str, path: str, query: Json, body: Json,
              principal: Json) -> Tuple[int, Json]:
    # Everything below needs current state.
    STORE.ensure_fresh()
    persistence.sync_live(STORE)

    parts = [p for p in path.split("/") if p]  # parts[0] == "api"

    if path == "/api/system/status":
        payload = _provenance_block()
        payload["auth"] = auth.describe()
        payload["storage"] = persistence.storage_info()
        payload["storage"]["row_counts"] = persistence.counts()
        return 200, payload

    if path == "/api/audit":
        auth.require(principal, "user.manage")
        return 200, repo("audit_log").list(
            order_by="at", desc=True,
            limit=query.get("limit") or 50, offset=query.get("offset") or 0)

    if path == "/api/model-card":
        return 200, MODEL_CARD

    if path == "/api/overview":
        return 200, _overview()

    if path == "/api/map":
        return 200, _map_bundle(query)

    if path == "/api/corridors":
        return 200, {
            "corridors": [_corridor_payload(c["id"]) for c in network.CORRIDORS],
            "provenance": _provenance_block(),
        }

    if len(parts) == 3 and parts[1] == "corridors":
        cid = parts[2]
        if cid not in network.CORRIDOR_BY_ID:
            return 404, {"error": "Unknown corridor " + cid}
        return 200, _corridor_payload(cid, full_risk=True)

    if len(parts) == 3 and parts[1] == "risk":
        cid = parts[2]
        if cid not in network.CORRIDOR_BY_ID:
            return 404, {"error": "Unknown corridor " + cid}
        state = STORE.corridor_state.get(cid) or {}
        return 200, {
            "corridor": _corridor_payload(cid, include_geometry=False, full_risk=True),
            "risk": state.get("risk", {}),
            "model": MODEL_CARD["version"],
            "model_kind": MODEL_CARD["kind"],
            "is_trained_ml": False,
            "provenance": _provenance_block(),
        }

    if path == "/api/vehicles":
        vehicles = [_vehicle_payload(v) for v in STORE.vehicles.values()]
        status = query.get("status")
        if status:
            vehicles = [v for v in vehicles if v["status"] == status]
        priority = query.get("priority")
        if priority:
            vehicles = [v for v in vehicles if v["priority"] == priority]
        return 200, {"vehicles": vehicles, "count": len(vehicles)}

    if len(parts) == 3 and parts[1] == "vehicles":
        v = STORE.vehicles.get(parts[2])
        if not v:
            return 404, {"error": "Unknown vehicle " + parts[2]}
        payload = _vehicle_payload(v, detail=True)
        delivery = STORE.deliveries.get(v.get("delivery_id") or "")
        payload["delivery"] = _delivery_payload(delivery) if delivery else None
        state = STORE.corridor_state.get(v["corridor_id"]) or {}
        payload["corridor_risk"] = state.get("risk", {})
        return 200, payload

    if path == "/api/deliveries":
        deliveries = [_delivery_payload(d) for d in STORE.deliveries.values()]
        status = query.get("status")
        if status:
            deliveries = [d for d in deliveries if d["status"] == status]
        return 200, {"deliveries": deliveries, "count": len(deliveries)}

    if path == "/api/incidents":
        if method == "POST":
            auth.require(principal, "incident.create")
            incident = STORE.report_incident(body)
            persistence.record_incident(incident, principal)
            persistence.record_field_report(
                incident, principal, str(body.get("client_uuid") or ""))
            auth.audit(principal, "incident.create", "incident", incident["id"],
                       {"corridor_id": incident.get("corridor_id"),
                        "blocks_road": bool(incident.get("blocks_road"))})
            return 201, {"incident": incident}
        include_resolved = str(query.get("include_resolved", "false")).lower() == "true"
        items = STORE.all_incidents(include_resolved=include_resolved)
        source = query.get("source")
        if source:
            items = [i for i in items if i["source"] == source]
        return 200, {"incidents": items, "count": len(items),
                     "provenance": _provenance_block()}

    if len(parts) == 4 and parts[1] == "incidents" and parts[3] == "status":
        status = (body.get("status") or "").strip()
        if status not in ("active", "acknowledged", "resolved"):
            return 400, {"error": "status must be active, acknowledged or resolved"}
        auth.require(principal, "incident.set_status")
        if not STORE.set_incident_status(parts[2], status):
            return 404, {"error": "Unknown incident " + parts[2]}
        persistence.record_incident_status(parts[2], status)
        auth.audit(principal, "incident.set_status", "incident", parts[2],
                   {"status": status})
        return 200, {"ok": True, "id": parts[2], "status": status}

    if path == "/api/alerts":
        alerts = sorted(STORE.alerts.values(),
                        key=lambda a: (a["status"] == "resolved", -a["created_at"]))
        return 200, {"alerts": alerts, "counts": STORE.metrics()["alerts"]}

    if path == "/api/alerts/acknowledge-all":
        auth.require(principal, "alert.acknowledge_all")
        n = STORE.acknowledge_all_alerts()
        persistence.record_alerts(STORE.alerts.values())
        auth.audit(principal, "alert.acknowledge_all", "alert", "",
                   {"acknowledged": n})
        return 200, {"ok": True, "acknowledged": n}

    if len(parts) == 4 and parts[1] == "alerts" and parts[3] == "action":
        auth.require(principal, "alert.action")
        action = (body.get("action") or "").strip()
        alert = STORE.update_alert(parts[2], action, body.get("assignee"))
        if not alert:
            return 400, {"error": "Unknown alert or invalid action"}
        persistence.record_alert(alert, principal)
        auth.audit(principal, "alert." + (action or "action"), "alert", parts[2],
                   {"assignee": body.get("assignee")})
        return 200, {"alert": alert}

    if path == "/api/traffic":
        return 200, {
            "mode": STORE.traffic_mode,
            "notice": traffic_service.traffic_notice(STORE.traffic_mode),
            "segments": [
                {
                    "corridor_id": cid,
                    "name": network.CORRIDOR_BY_ID[cid]["name"],
                    **(state.get("traffic") or {}),
                    "geometry": _geometry(cid),
                }
                for cid, state in STORE.corridor_state.items()
            ],
        }

    if path == "/api/inventory":
        return 200, _inventory()

    if path == "/api/routes/plan":
        auth.require(principal, "route.plan")
        status_code, payload = _plan_routes(body)
        if status_code == 200:
            plan_id = persistence.record_route_plan(payload, principal, STORE)
            if plan_id:
                payload["plan_id"] = plan_id
            auth.audit(principal, "route.plan", "vehicle",
                       str(body.get("vehicle_id") or ""))
        return status_code, payload

    if path == "/api/simulation":
        return 200, simctl.state(STORE)

    if path == "/api/simulation/scenarios":
        from .services import simulation as simulation_service
        return 200, {"scenarios": simulation_service.scenario_list()}

    if path == "/api/simulation/start":
        auth.require(principal, "simulation.start")
        state = simctl.start(STORE, body.get("scenario_id"))
        persistence.record_simulation(STORE.simulation, principal)
        auth.audit(principal, "simulation.start", "simulation",
                   str(body.get("scenario_id") or ""))
        return 200, state

    if path == "/api/simulation/accept":
        auth.require(principal, "simulation.accept")
        state = simctl.accept(STORE, body.get("route_id"))
        persistence.record_simulation(STORE.simulation, principal, committed=True)
        persistence.record_incidents(STORE.all_incidents(include_resolved=True))
        persistence.record_alerts(STORE.alerts.values())
        auth.audit(principal, "simulation.accept", "route",
                   str(body.get("route_id") or ""))
        return 200, state

    if path == "/api/simulation/decline":
        auth.require(principal, "simulation.decline")
        state = simctl.decline(STORE)
        persistence.record_simulation(STORE.simulation, principal)
        auth.audit(principal, "simulation.decline", "simulation", "")
        return 200, state

    if path == "/api/simulation/reset":
        auth.require(principal, "simulation.reset")
        state = simctl.reset(STORE)
        auth.audit(principal, "simulation.reset", "simulation", "")
        return 200, state

    return 404, {"error": "No route for " + method + " " + path, "endpoints": ENDPOINTS}


# ---------------------------------------------------------------- composites
def _overview() -> Json:
    metrics = STORE.metrics()

    ranked = sorted(
        STORE.corridor_state.values(),
        key=lambda s: (s.get("risk") or {}).get("probability", 0.0),
        reverse=True,
    )
    top_risks = [
        {
            "corridor_id": s["corridor_id"],
            "name": network.CORRIDOR_BY_ID[s["corridor_id"]]["name"],
            "status": s["status"],
            "probability": (s.get("risk") or {}).get("probability", 0.0),
            "band": (s.get("risk") or {}).get("band", "low"),
            "headline": (s.get("risk") or {}).get("headline", ""),
            "factors": ((s.get("risk") or {}).get("factors") or [])[:3],
            "rain_next_24h_mm": (s.get("weather") or {}).get("rain_next_24h_mm", 0),
            "traffic_level": (s.get("traffic") or {}).get("level", "free"),
        }
        for s in ranked[:6]
    ]

    attention = []
    for d in STORE.deliveries.values():
        if d["status"] in ("at-risk", "delayed"):
            attention.append(_delivery_payload(d))
    attention.sort(key=lambda d: (d["priority"] != "critical", -d["risk_probability"]))

    recent_alerts = sorted(STORE.alerts.values(), key=lambda a: -a["created_at"])[:6]

    risk_distribution = {"low": 0, "moderate": 0, "high": 0, "critical": 0}
    for s in STORE.corridor_state.values():
        band = (s.get("risk") or {}).get("band", "low")
        risk_distribution[band] = risk_distribution.get(band, 0) + 1

    rainfall_series = [
        {
            "corridor_id": cid,
            "name": network.CORRIDOR_BY_ID[cid]["name"].split(" ")[0],
            "rain_48h": (s.get("weather") or {}).get("rain_48h_mm", 0),
            "rain_next_24h": (s.get("weather") or {}).get("rain_next_24h_mm", 0),
            "probability": (s.get("risk") or {}).get("probability", 0),
        }
        for cid, s in STORE.corridor_state.items()
    ]

    return {
        "metrics": metrics,
        "top_risks": top_risks,
        "attention": attention[:6],
        "recent_alerts": recent_alerts,
        "risk_distribution": risk_distribution,
        "rainfall_series": rainfall_series,
        "reroute_history": STORE.reroute_history[-5:],
        "simulation": {
            "phase": STORE.simulation.get("phase"),
            "scenario_name": STORE.simulation.get("scenario_name"),
            "awaiting_decision": STORE.simulation.get("phase") == "awaiting-accept",
        },
        "provenance": _provenance_block(),
        "model": {"version": MODEL_CARD["version"], "is_trained_ml": False,
                  "kind": MODEL_CARD["kind"]},
    }


def _map_bundle(query: Json) -> Json:
    sim = STORE.simulation or {}
    active_routes = []

    for option in (sim.get("route_options") or []):
        active_routes.append({
            "id": option["id"],
            "label": option["label"],
            "geometry": option["geometry"],
            "risk_probability": option["risk_probability"],
            "risk_band": option["risk_band"],
            "reliability": option["reliability"],
            "duration_min": option["duration_min"],
            "distance_km": option["distance_km"],
            "recommended": option.get("recommended", False),
            "blocked": option.get("blocked", False),
            "selected": option["id"] == sim.get("selected_route_id"),
        })

    return {
        "corridors": [_corridor_payload(c["id"]) for c in network.CORRIDORS],
        "vehicles": [_vehicle_payload(v, detail=True) for v in STORE.vehicles.values()],
        "incidents": STORE.all_incidents(include_resolved=False),
        "cities": _city_payload(),
        "depots": _depot_payload(),
        "routes": active_routes,
        "bbox": config.NER_BBOX,
        "metrics": STORE.metrics(),
        "provenance": _provenance_block(),
    }


def _inventory() -> Json:
    depot_lookup = {d["id"]: d for d in _depot_payload()}
    items = []
    for row in seed.INVENTORY:
        depot = depot_lookup.get(row["depot_id"], {})
        items.append({**row, "depot_name": depot.get("name", row["depot_id"]),
                      "city": depot.get("city"),
                      "lng": depot.get("lng"), "lat": depot.get("lat")})

    shortages = [i for i in items if i["status"] == "shortage"]
    surpluses = [i for i in items if i["status"] == "surplus"]

    transfers = []
    for short in shortages:
        match = next((s for s in surpluses if s["item"] == short["item"]), None)
        if not match:
            continue
        transfers.append({
            "item": short["item"],
            "from_depot": match["depot_name"],
            "to_depot": short["depot_name"],
            "reason": (short["depot_name"] + " has " + str(short["stock_days"])
                       + " days of cover; " + match["depot_name"] + " holds "
                       + str(match["stock_days"]) + " days."),
            "urgency": "critical" if short["stock_days"] < 2 else "high",
        })

    return {"items": items, "shortages": shortages, "surpluses": surpluses,
            "suggested_transfers": transfers, "depots": _depot_payload()}


def _plan_routes(body: Json) -> Tuple[int, Json]:
    vehicle_id = body.get("vehicle_id")

    if vehicle_id:
        vehicle = STORE.vehicles.get(vehicle_id)
        if not vehicle:
            return 404, {"error": "Unknown vehicle " + str(vehicle_id)}
        options, provenance = routes_engine.plan_for_vehicle(
            STORE, vehicle,
            detour_corridors=body.get("detour_corridors"),
            detour_label=body.get("detour_label", "Alternative corridor"),
        )
        return 200, {"options": options, "vehicle_id": vehicle_id,
                     "priority": vehicle.get("priority"),
                     "routing_provenance": provenance,
                     "provenance": _provenance_block()}

    origin = body.get("origin")
    destination = body.get("destination")
    if not origin or not destination:
        return 400, {"error": "Provide vehicle_id, or origin and destination "
                              "as [lng, lat] pairs or city keys"}

    try:
        o = _resolve_point(origin)
        d = _resolve_point(destination)
    except (KeyError, TypeError, ValueError) as exc:
        return 400, {"error": "Could not resolve coordinates: " + str(exc)}

    options, provenance = routes_engine.build_options(
        STORE, origin=o, destination=d,
        priority=body.get("priority", "standard"),
        detour_corridors=body.get("detour_corridors"),
        detour_label=body.get("detour_label", "Alternative corridor"),
    )
    return 200, {"options": options, "routing_provenance": provenance,
                 "provenance": _provenance_block()}


def _resolve_point(value) -> geo.Coord:
    if isinstance(value, str):
        return network.city_coord(value.strip().lower())
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (float(value[0]), float(value[1]))
    if isinstance(value, dict):
        return (float(value["lng"]), float(value["lat"]))
    raise ValueError("unsupported point " + repr(value))
