"""Alert generation and lifecycle (roadmap Phase 11).

Alerts are deduplicated by a stable key so a persistent condition does not
spam the operator, and they support acknowledge / assign / escalate / resolve.
"""

from __future__ import annotations

import time
from typing import Dict, List

SEVERITY_ORDER = {"critical": 0, "high": 1, "moderate": 2, "low": 3, "info": 4}


def build_alert(key: str, severity: str, title: str, body: str, **related) -> dict:
    return {
        "id": key,
        "severity": severity,
        "title": title,
        "body": body,
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "new",              # new | acknowledged | assigned | escalated | resolved
        "assignee": None,
        "related": {k: v for k, v in related.items() if v},
    }


def derive(
    corridor_state: Dict[str, dict],
    incidents: List[dict],
    deliveries: List[dict],
    vehicles: List[dict],
    corridor_names: Dict[str, str],
) -> List[dict]:
    """Compute the alert set implied by current conditions."""
    out: List[dict] = []

    # Blocked corridors are the highest priority.
    for cid, state in corridor_state.items():
        if state.get("status") == "blocked":
            out.append(build_alert(
                f"ALERT-BLOCK-{cid}", "critical",
                f"{corridor_names.get(cid, cid)} blocked",
                state.get("block_reason") or "Corridor reported impassable.",
                corridor_id=cid,
            ))
        elif (state.get("risk") or {}).get("probability", 0) >= 0.70:
            risk = state["risk"]
            out.append(build_alert(
                f"ALERT-RISK-{cid}", "high",
                f"High disruption risk on {corridor_names.get(cid, cid)}",
                risk.get("headline", ""),
                corridor_id=cid,
            ))

    # Critical-priority cargo at risk.
    for d in deliveries:
        if d.get("status") in ("at-risk", "delayed") and d.get("priority") == "critical":
            out.append(build_alert(
                f"ALERT-DLV-{d['id']}", "critical",
                f"{d['cargo']} delivery {d['id']} at risk",
                (f"{d['origin']} \u2192 {d['destination']}. "
                 f"Route reliability {d.get('reliability', 0)}%. "
                 f"{d.get('risk_note', '')}").strip(),
                delivery_id=d["id"], vehicle_id=d.get("vehicle_id"),
            ))

    # Halted vehicles.
    for v in vehicles:
        if v.get("status") == "halted":
            out.append(build_alert(
                f"ALERT-VEH-{v['id']}", "high",
                f"{v['id']} halted en route",
                f"{v.get('cargo', 'Cargo')} vehicle stopped on "
                f"{corridor_names.get(v.get('corridor_id'), 'corridor')}. "
                f"{v.get('halt_reason', '')}".strip(),
                vehicle_id=v["id"], corridor_id=v.get("corridor_id"),
            ))

    # Verified critical incidents.
    for inc in incidents:
        if inc.get("severity") == "critical" and inc.get("status") == "active":
            out.append(build_alert(
                f"ALERT-INC-{inc['id']}", "critical",
                inc["title"],
                inc["description"],
                incident_id=inc["id"], corridor_id=inc.get("corridor_id"),
            ))

    out.sort(key=lambda a: SEVERITY_ORDER.get(a["severity"], 9))
    return out


def merge(existing: Dict[str, dict], derived: List[dict]) -> Dict[str, dict]:
    """Keep operator actions (acknowledge/assign) across refreshes.

    Conditions that have cleared are dropped unless the operator resolved them,
    in which case they stay briefly for the audit trail.
    """
    merged: Dict[str, dict] = {}
    derived_ids = {a["id"] for a in derived}

    for alert in derived:
        prior = existing.get(alert["id"])
        if prior:
            alert = dict(alert)
            alert["status"] = prior["status"]
            alert["assignee"] = prior.get("assignee")
            alert["created_at"] = prior["created_at"]
            alert["updated_at"] = prior.get("updated_at", prior["created_at"])
        merged[alert["id"]] = alert

    # Retain resolved alerts for 30 minutes so the operator sees the history.
    now = time.time()
    for aid, alert in existing.items():
        if aid in derived_ids:
            continue
        if alert["status"] == "resolved" and now - alert.get("updated_at", 0) < 1800:
            merged[aid] = alert
        elif alert.get("pinned"):
            merged[aid] = alert

    return merged


def counts(alerts: List[dict]) -> dict:
    return {
        "total": len(alerts),
        "unread": sum(1 for a in alerts if a["status"] == "new"),
        "critical": sum(1 for a in alerts if a["severity"] == "critical" and a["status"] != "resolved"),
    }
