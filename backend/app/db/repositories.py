"""Repository layer.

One generic `Repository` driven by a table registry, rather than 19 hand-written
classes. Gives every table the same guarantees: column whitelisting, required
field checks, enum validation, automatic timestamps, JSON encode/decode, boolean
normalisation across dialects, and paginated listing.

Services talk to repositories. Repositories talk to the engine. Nothing else
touches SQL.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .engine import BaseEngine, DatabaseError, Row

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

DATA_CLASSES = ("REAL", "SIMULATED", "DERIVED", "PREDICTED")
SEVERITIES = ("critical", "high", "moderate", "low")
PRIORITIES = ("critical", "high", "standard")
ROLES = ("admin", "dispatcher", "field_officer", "logistics_manager")


class ValidationError(ValueError):
    """Raised for bad input. The API turns this into a 400 with the message."""


def now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return prefix + "-" + uuid.uuid4().hex[:12]


class TableSpec:
    def __init__(self, name: str, pk: str, columns: Sequence[str],
                 required: Sequence[str] = (),
                 enums: Optional[Dict[str, Sequence[str]]] = None,
                 bools: Sequence[str] = (),
                 order_by: str = "") -> None:
        self.name = name
        self.pk = pk
        self.columns = tuple(columns)
        self.required = tuple(required)
        self.enums = {k: tuple(v) for k, v in (enums or {}).items()}
        self.bools = tuple(bools)
        self.json_cols = tuple(c for c in columns if c.endswith("_json"))
        self.order_by = order_by or pk


TABLES: Dict[str, TableSpec] = {
    "users": TableSpec(
        "users", "id",
        ("id", "username", "full_name", "email", "role", "password_hash",
         "password_salt", "login_enabled", "active", "created_at", "updated_at"),
        required=("id", "username", "full_name", "role"),
        enums={"role": ROLES},
        bools=("login_enabled", "active"),
        order_by="username",
    ),
    "sessions": TableSpec(
        "sessions", "token_hash",
        ("token_hash", "user_id", "created_at", "expires_at", "user_agent"),
        required=("token_hash", "user_id", "expires_at"),
        order_by="created_at",
    ),
    "districts": TableSpec(
        "districts", "id",
        ("id", "name", "state", "geom_json", "min_lng", "min_lat", "max_lng",
         "max_lat", "created_at"),
        required=("id", "name", "state"),
        order_by="name",
    ),
    "roads": TableSpec(
        "roads", "id",
        ("id", "name", "ref", "classification", "from_city", "to_city",
         "length_km", "free_flow_kmh", "condition", "data_class", "source",
         "created_at", "updated_at"),
        required=("id", "name"),
        enums={"data_class": DATA_CLASSES},
        order_by="name",
    ),
    "road_segments": TableSpec(
        "road_segments", "id",
        ("id", "road_id", "seq", "name", "length_km", "free_flow_kmh",
         "condition", "district_id", "geom_json", "min_lng", "min_lat",
         "max_lng", "max_lat", "data_class", "source", "created_at", "updated_at"),
        required=("id", "road_id"),
        enums={"data_class": DATA_CLASSES},
        order_by="road_id",
    ),
    "depots": TableSpec(
        "depots", "id",
        ("id", "name", "district_id", "lng", "lat", "geom_json", "capacity_pct",
         "data_class", "created_at", "updated_at"),
        required=("id", "name", "lng", "lat"),
        enums={"data_class": DATA_CLASSES},
        order_by="name",
    ),
    "inventory_items": TableSpec(
        "inventory_items", "id",
        ("id", "depot_id", "item", "category", "stock_units",
         "daily_consumption", "stock_days", "status", "data_class", "updated_at"),
        required=("id", "depot_id", "item"),
        enums={"status": ("shortage", "watch", "ok", "surplus"),
               "data_class": DATA_CLASSES},
        order_by="depot_id",
    ),
    "vehicles": TableSpec(
        "vehicles", "id",
        ("id", "plate", "driver", "phone", "cargo", "cargo_category",
         "capacity_tonnes", "cold_chain", "priority", "status", "corridor_id",
         "lng", "lat", "eta_min", "rerouted", "data_class", "updated_at"),
        required=("id",),
        enums={"priority": PRIORITIES, "data_class": DATA_CLASSES},
        bools=("cold_chain", "rerouted"),
    ),
    "deliveries": TableSpec(
        "deliveries", "id",
        ("id", "vehicle_id", "cargo", "category", "origin", "destination",
         "consignee", "priority", "sla_hours", "status", "eta_min", "delay_min",
         "reliability", "risk_probability", "data_class", "created_at", "updated_at"),
        required=("id",),
        enums={"priority": PRIORITIES, "data_class": DATA_CLASSES},
    ),
    "incidents": TableSpec(
        "incidents", "id",
        ("id", "corridor_id", "segment_id", "type", "severity", "title",
         "description", "lng", "lat", "geom_json", "blocks_road", "status",
         "verified", "source", "source_label", "data_class", "external_url",
         "reported_by", "reported_at", "observed_at", "ingested_at",
         "resolved_at", "updated_at"),
        required=("id", "type", "severity", "title"),
        enums={"severity": SEVERITIES,
               "status": ("active", "acknowledged", "resolved"),
               "data_class": DATA_CLASSES},
        bools=("blocks_road", "verified"),
        order_by="reported_at",
    ),
    "field_reports": TableSpec(
        "field_reports", "id",
        ("id", "client_uuid", "incident_id", "reporter_id", "corridor_id",
         "type", "severity", "description", "lng", "lat", "accuracy_m",
         "photo_path", "photo_sha256", "captured_at", "synced_at", "sync_state",
         "data_class", "created_at"),
        required=("id", "type", "severity"),
        enums={"sync_state": ("pending", "synced", "failed", "duplicate"),
               "data_class": DATA_CLASSES},
        order_by="created_at",
    ),
    "route_plans": TableSpec(
        "route_plans", "id",
        ("id", "vehicle_id", "delivery_id", "requested_by", "priority",
         "provenance", "routing_provenance", "created_at"),
        required=("id",),
        order_by="created_at",
    ),
    "route_options": TableSpec(
        "route_options", "id",
        ("id", "plan_id", "label", "source", "distance_km", "eta_min",
         "risk_probability", "reliability", "blocked", "recommended",
         "score_time", "score_risk", "score_reliability", "score_priority",
         "score_total", "explanation", "geom_json", "created_at"),
        required=("id", "plan_id"),
        bools=("blocked", "recommended"),
        order_by="score_total",
    ),
    "risk_predictions": TableSpec(
        "risk_predictions", "id",
        ("id", "corridor_id", "segment_id", "probability", "band",
         "window_hours", "model_version", "model_kind", "factors_json",
         "data_class", "predicted_at"),
        required=("id", "corridor_id", "probability", "band", "window_hours",
                  "model_version", "model_kind"),
        enums={"data_class": DATA_CLASSES},
        order_by="predicted_at",
    ),
    "simulation_runs": TableSpec(
        "simulation_runs", "id",
        ("id", "scenario_id", "name", "phase", "committed", "created_by",
         "started_at", "decided_at", "accepted_route_id", "impact_json", "log_json"),
        required=("id", "scenario_id", "phase"),
        bools=("committed",),
        order_by="started_at",
    ),
    "alerts": TableSpec(
        "alerts", "id",
        ("id", "alert_key", "severity", "status", "title", "body",
         "entity_type", "entity_id", "corridor_id", "assignee_id",
         "assignee_name", "source", "data_class", "created_at", "updated_at",
         "acknowledged_at", "resolved_at"),
        required=("id", "alert_key", "severity", "title"),
        enums={"severity": SEVERITIES,
               "status": ("new", "acknowledged", "assigned", "escalated", "resolved"),
               "data_class": DATA_CLASSES},
        order_by="created_at",
    ),
    "notifications": TableSpec(
        "notifications", "id",
        ("id", "user_id", "alert_id", "channel", "status", "created_at", "sent_at"),
        required=("id",),
        enums={"channel": ("in_app", "push", "email", "sms"),
               "status": ("queued", "sent", "failed", "read")},
        order_by="created_at",
    ),
    "audit_log": TableSpec(
        "audit_log", "id",
        ("id", "at", "actor_id", "actor_role", "action", "entity_type",
         "entity_id", "detail_json", "allowed"),
        required=("id", "at", "action"),
        bools=("allowed",),
        order_by="at",
    ),
}


class Repository:
    def __init__(self, engine: BaseEngine, spec: TableSpec) -> None:
        self.engine = engine
        self.spec = spec

    # ------------------------------------------------------------ internals
    def _clean(self, data: Dict[str, Any], partial: bool) -> Dict[str, Any]:
        spec = self.spec
        unknown = [k for k in data if k not in spec.columns]
        if unknown:
            raise ValidationError(
                spec.name + ": unknown field(s) " + ", ".join(sorted(unknown))
            )

        if not partial:
            missing = [c for c in spec.required
                       if data.get(c) is None or data.get(c) == ""]
            if missing:
                raise ValidationError(
                    spec.name + ": missing required field(s) " + ", ".join(missing)
                )

        out: Dict[str, Any] = {}
        for key, value in data.items():
            if key in spec.enums and value is not None:
                allowed = spec.enums[key]
                if value not in allowed:
                    raise ValidationError(
                        spec.name + "." + key + " must be one of " + ", ".join(allowed)
                        + " (got " + str(value) + ")"
                    )
            if key in spec.json_cols and not isinstance(value, (str, type(None))):
                value = json.dumps(value)
            if key in spec.bools and value is not None:
                value = bool(value)
            out[key] = value
        return out

    def _out(self, row: Optional[Row]) -> Optional[Row]:
        if row is None:
            return None
        spec = self.spec
        clean = dict(row)
        for col in spec.bools:
            if col in clean and clean[col] is not None:
                clean[col] = bool(clean[col])
        for col in spec.json_cols:
            if col in clean and isinstance(clean[col], str):
                try:
                    clean[col] = json.loads(clean[col])
                except ValueError:
                    pass
        return clean

    # ----------------------------------------------------------------- CRUD
    def insert(self, data: Dict[str, Any]) -> Row:
        spec = self.spec
        payload = self._clean(data, partial=False)
        stamp = now()
        if "created_at" in spec.columns and payload.get("created_at") is None:
            payload["created_at"] = stamp
        if "updated_at" in spec.columns and payload.get("updated_at") is None:
            payload["updated_at"] = stamp

        cols = list(payload.keys())
        placeholders = ", ".join(["?"] * len(cols))
        sql = ("INSERT INTO " + spec.name + " (" + ", ".join(cols) + ") "
               "VALUES (" + placeholders + ")")
        self.engine.execute(sql, [payload[c] for c in cols])
        return self.get(payload[spec.pk]) or payload

    def upsert(self, data: Dict[str, Any]) -> Row:
        spec = self.spec
        payload = self._clean(data, partial=False)
        stamp = now()
        if "created_at" in spec.columns and payload.get("created_at") is None:
            payload["created_at"] = stamp
        if "updated_at" in spec.columns:
            payload["updated_at"] = stamp

        cols = list(payload.keys())
        placeholders = ", ".join(["?"] * len(cols))
        updates = ", ".join(c + " = excluded." + c for c in cols if c != spec.pk)
        sql = ("INSERT INTO " + spec.name + " (" + ", ".join(cols) + ") "
               "VALUES (" + placeholders + ") "
               "ON CONFLICT (" + spec.pk + ") DO UPDATE SET " + updates)
        self.engine.execute(sql, [payload[c] for c in cols])
        return self.get(payload[spec.pk]) or payload

    def update(self, pk_value: Any, patch: Dict[str, Any]) -> Optional[Row]:
        spec = self.spec
        payload = self._clean(patch, partial=True)
        payload.pop(spec.pk, None)
        if "updated_at" in spec.columns:
            payload["updated_at"] = now()
        if not payload:
            return self.get(pk_value)
        assignments = ", ".join(c + " = ?" for c in payload)
        sql = ("UPDATE " + spec.name + " SET " + assignments
               + " WHERE " + spec.pk + " = ?")
        changed = self.engine.execute(sql, list(payload.values()) + [pk_value])
        if changed == 0:
            return None
        return self.get(pk_value)

    def get(self, pk_value: Any) -> Optional[Row]:
        sql = "SELECT * FROM " + self.spec.name + " WHERE " + self.spec.pk + " = ?"
        return self._out(self.engine.one(sql, (pk_value,)))

    def delete(self, pk_value: Any) -> bool:
        sql = "DELETE FROM " + self.spec.name + " WHERE " + self.spec.pk + " = ?"
        return self.engine.execute(sql, (pk_value,)) > 0

    def count(self, where: str = "", params: Sequence[Any] = ()) -> int:
        sql = "SELECT COUNT(*) AS n FROM " + self.spec.name
        if where:
            sql += " WHERE " + where
        return int(self.engine.scalar(sql, params) or 0)

    def list(self, where: str = "", params: Sequence[Any] = (),
             order_by: str = "", desc: bool = False,
             limit: int = DEFAULT_LIMIT, offset: int = 0) -> Dict[str, Any]:
        """Paginated read. Returns items plus the metadata the API exposes."""
        try:
            limit = int(limit)
            offset = int(offset)
        except (TypeError, ValueError):
            raise ValidationError("limit and offset must be integers")
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)

        column = order_by or self.spec.order_by
        if column not in self.spec.columns:
            raise ValidationError("Cannot order " + self.spec.name + " by " + column)

        sql = "SELECT * FROM " + self.spec.name
        if where:
            sql += " WHERE " + where
        sql += " ORDER BY " + column + (" DESC" if desc else " ASC")
        sql += " LIMIT ? OFFSET ?"

        rows = self.engine.query(sql, list(params) + [limit, offset])
        total = self.count(where, params)
        return {
            "items": [self._out(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(rows) < total,
        }

    def all(self, where: str = "", params: Sequence[Any] = (),
            order_by: str = "", desc: bool = False) -> List[Row]:
        """Unpaginated read for internal service use (never exposed directly)."""
        column = order_by or self.spec.order_by
        sql = "SELECT * FROM " + self.spec.name
        if where:
            sql += " WHERE " + where
        sql += " ORDER BY " + column + (" DESC" if desc else " ASC")
        return [self._out(r) for r in self.engine.query(sql, params)]


def repository(engine: BaseEngine, table: str) -> Repository:
    spec = TABLES.get(table)
    if spec is None:
        raise DatabaseError("Unknown table " + table)
    return Repository(engine, spec)
