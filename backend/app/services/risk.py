"""Explainable disruption-risk engine.

WHAT THIS IS: a transparent, weighted scoring model over live and static
features. Every prediction returns the contribution of each factor, so a
dispatcher (or a judge) can see exactly why a corridor is flagged.

WHAT THIS IS NOT: a trained machine-learning model. There is no labelled
historical disruption dataset shipped with this prototype, so claiming a
trained model would be dishonest. Phase 5 of the roadmap replaces the weights
below with a gradient-boosted classifier trained on historical incidents; the
API contract (`probability`, `window_hours`, `factors`) is designed to stay
identical so the frontend does not change.

Evaluation plan for Phase 5 is documented in EVALUATION.md.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

from .. import geo
from . import seismic as seismic_service
from . import traffic as traffic_service

# Feature weights. They sum to 1.0 and are documented in the UI's model card.
WEIGHTS = {
    "rainfall": 0.34,      # strongest driver of landslides and washouts
    "terrain": 0.20,       # slope / mountain corridors
    "history": 0.16,       # historical incident density
    "condition": 0.12,     # surface condition
    "river": 0.08,         # flood exposure near major rivers
    "seismic": 0.06,       # recent nearby earthquakes
    "traffic": 0.04,       # congestion slows evacuation / recovery
}

FACTOR_LABELS = {
    "rainfall": "Rainfall",
    "terrain": "Terrain and slope",
    "history": "Historical incidents",
    "condition": "Road surface condition",
    "river": "River proximity / flooding",
    "seismic": "Recent seismic activity",
    "traffic": "Congestion",
}


def _rain_factor(weather: dict) -> Tuple[float, str]:
    """Combine recent accumulation with forecast intensity.

    Thresholds follow IMD-style rainfall bands (mm/24h):
      light < 15, moderate 15-64, heavy 64-115, very heavy 115-204, extreme 204+
    """
    past = float(weather.get("rain_48h_mm") or 0.0)
    ahead = float(weather.get("rain_next_24h_mm") or 0.0)
    peak = float(weather.get("max_hourly_next_24h") or 0.0)

    # Saturated ground from the last 48h matters as much as what is coming.
    accumulation = past * 0.6 + ahead
    acc_term = min(1.0, accumulation / 160.0)
    burst_term = min(1.0, peak / 25.0)          # 25 mm/h is a cloudburst
    value = min(1.0, 0.72 * acc_term + 0.28 * burst_term)

    if accumulation >= 200:
        band = "extremely heavy rainfall"
    elif accumulation >= 115:
        band = "very heavy rainfall"
    elif accumulation >= 64:
        band = "heavy rainfall"
    elif accumulation >= 15:
        band = "moderate rainfall"
    else:
        band = "light or no rainfall"

    detail = f"{band} \u2014 {past:.0f} mm in last 48h, {ahead:.0f} mm forecast next 24h"
    return value, detail


def _history_factor(incidents_per_year: float) -> Tuple[float, str]:
    value = min(1.0, incidents_per_year / 25.0)
    return value, f"{incidents_per_year:.0f} recorded disruptions per year on this corridor"


def score_corridor(
    corridor: dict,
    line: List[geo.Coord],
    weather: dict,
    seismic_events: List[dict],
    traffic: dict,
    active_incident_boost: float = 0.0,
) -> dict:
    """Compute disruption probability + explanation for one corridor."""
    rain_value, rain_detail = _rain_factor(weather or {})
    hist_value, hist_detail = _history_factor(float(corridor.get("history", 0)))
    seis_value, seis_events = seismic_service.corridor_seismic_factor(line, seismic_events)
    traf_value = traffic_service.congestion_factor((traffic or {}).get("level", "free"))

    features = {
        "rainfall": rain_value,
        "terrain": float(corridor.get("terrain", 0.0)),
        "history": hist_value,
        "condition": float(corridor.get("condition", 0.0)),
        "river": float(corridor.get("river", 0.0)) * min(1.0, 0.35 + rain_value),
        "seismic": seis_value,
        "traffic": traf_value,
    }

    # Weighted sum -> logistic squash for a probability-like output.
    linear = sum(WEIGHTS[k] * features[k] for k in WEIGHTS)

    # Interaction: heavy rain on steep, poorly surfaced ground is much worse
    # than either alone. This is the dominant landslide mechanism in the NER.
    interaction = features["rainfall"] * features["terrain"] * 0.18
    linear = min(1.0, linear + interaction + active_incident_boost)

    probability = 1.0 / (1.0 + math.exp(-9.0 * (linear - 0.55)))
    probability = round(min(0.985, max(0.005, probability)), 3)

    contributions = []
    for key, weight in WEIGHTS.items():
        contrib = weight * features[key]
        if contrib <= 0.001:
            continue
        detail = ""
        if key == "rainfall":
            detail = rain_detail
        elif key == "history":
            detail = hist_detail
        elif key == "seismic" and seis_events:
            top = seis_events[0]
            detail = (f"M{top['magnitude']} {top['distance_km']} km away, "
                      f"{top['hours_ago']:.0f}h ago")
        elif key == "terrain":
            detail = f"slope index {features['terrain']:.2f}"
        elif key == "condition":
            detail = f"surface condition index {features['condition']:.2f}"
        elif key == "river":
            detail = "corridor follows a flood-prone river" if features["river"] > 0.3 else "limited river exposure"
        elif key == "traffic":
            detail = f"{(traffic or {}).get('level', 'free')} congestion"

        contributions.append({
            "key": key,
            "label": FACTOR_LABELS[key],
            "value": round(features[key], 3),
            "weight": weight,
            "contribution": round(contrib, 4),
            "detail": detail,
        })

    contributions.sort(key=lambda c: c["contribution"], reverse=True)
    total = sum(c["contribution"] for c in contributions) or 1.0
    for c in contributions:
        c["share"] = round(c["contribution"] / total, 3)

    return {
        "corridor_id": corridor["id"],
        "probability": probability,
        "band": band_for(probability),
        "score": round(linear, 3),
        "window_hours": 24,
        "factors": contributions,
        "headline": headline(corridor, contributions, probability),
        "model": "heuristic-v1",
        "model_kind": "transparent weighted scoring (not a trained ML model)",
    }


def band_for(probability: float) -> str:
    if probability >= 0.70:
        return "critical"
    if probability >= 0.45:
        return "high"
    if probability >= 0.22:
        return "moderate"
    return "low"


def status_for(probability: float, blocked: bool) -> str:
    if blocked:
        return "blocked"
    if probability >= 0.45:
        return "at-risk"
    return "operational"


def headline(corridor: dict, contributions: List[dict], probability: float) -> str:
    if not contributions:
        return "No significant disruption drivers detected."
    top = contributions[0]
    pct = int(round(probability * 100))
    second = contributions[1]["label"].lower() if len(contributions) > 1 else None
    base = f"{pct}% disruption probability in the next 24h, driven mainly by {top['label'].lower()}"
    if second:
        base += f" combined with {second}"
    return base + "."


def reliability_from_probability(probability: float) -> int:
    """Delivery-success reliability shown in route comparison."""
    return int(round(max(5.0, min(99.0, (1.0 - probability) * 100.0))))
