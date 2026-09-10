# Evaluation plan

> SIH demo criterion: *"Every claimed AI capability has a measurable evaluation plan."*

This document exists so that nobody - judge, mentor or teammate - has to take the
word "AI" on trust. It states what RouteMind claims today, what it does **not**
claim, and exactly how the Phase 5 model will be measured before it is allowed
to replace the current heuristic.

---

## 1. What is running today

| Component | Status | Honest description |
| --- | --- | --- |
| Corridor risk score | **Shipping** | `heuristic-v1`: transparent weighted scoring over rainfall, terrain, history, condition, river proximity, seismic and traffic, squashed by a logistic curve. **Not trained. Not fitted to outcomes.** |
| Route ranking | **Shipping** | Deterministic cost function: time + risk + reliability, weighted by cargo priority. |
| Incident derivation | **Shipping** | Rule thresholds on live rainfall (64 mm / 115 mm) and USGS magnitude (>= 3.0). |
| Disruption prediction (ML) | **Not built** | Phase 5. Everything below defines how it will be judged. |

**Current measured accuracy: none.** `heuristic-v1` has never been scored against
ground truth, because we do not yet have a labelled disruption history. Claiming
a number here would be dishonest. The plan below fixes that in order.

---

## 2. The label

All evaluation needs one crisp definition:

> A **disruption** is a corridor segment being impassable or restricted to
> single-lane/convoy movement for **>= 2 continuous hours** on a given day.

**Label sources**, in priority order:

1. NHIDCL / PWD / BRO road closure notices (authoritative, dated)
2. State Disaster Management Authority daily situation reports
3. District administration and police closure orders
4. Verified field reports from the Phase 7 app (two independent reporters)
5. Fleet telemetry: a vehicle stationary >= 90 min on an open corridor away from a
   known halt point, corroborated by (1)-(4)

Telemetry alone never creates a positive label - it only corroborates. Every
label carries its source, so we can measure how much the model depends on the
weakest evidence class.

**Target dataset:** 12 corridors x 24 months = ~8,700 corridor-days, expected
positive rate 4-9% (monsoon-skewed). This class imbalance drives every metric
choice below.

---

## 3. Splits

Random k-fold would leak weather autocorrelation and inflate every score. We use:

| Split | Purpose |
| --- | --- |
| **Temporal** - train on months 1-18, validate 19-21, test 22-24 | The real deployment condition: predict the future |
| **Monsoon holdout** - hold out one full monsoon season | Does it work when it actually matters? |
| **Spatial holdout** - hold out 2 entire corridors | Does it generalise to a road it has never seen? |

A model is only accepted if it clears thresholds on **all three**.

---

## 4. Baselines to beat

A model that cannot beat these is not worth deploying:

1. **Majority class** (always "no disruption") - exposes accuracy as a useless metric
2. **Single-threshold rainfall rule** (>= 115 mm / 24h) - the operator's mental model
3. **`heuristic-v1`** - the model shipping today
4. **Climatology** - historical disruption rate for that corridor and calendar week

---

## 5. Metrics

### Primary

| Metric | Why | Acceptance |
| --- | --- | --- |
| **PR-AUC** | Correct for 4-9% positives; ROC-AUC flatters imbalanced problems | >= 0.55, and >= +0.10 over `heuristic-v1` |
| **Recall @ 10% false-positive rate** | Operators tolerate a bounded false alarm budget | >= 0.70 |
| **Brier score + reliability curve** | We display a *percentage*. If we print 70%, it must happen ~70% of the time | Brier <= 0.08; calibration slope 0.9-1.1 |
| **Mean lead time** | "Predictive, not reactive" is the core claim | >= 6 h median before closure |

### Secondary

- ROC-AUC (reported, never headlined)
- Precision@3 - of the three corridors we surface as highest risk, how many were disrupted
- Per-state and per-corridor breakdown - no state may fall below 0.60 recall
- Cold-start performance on the spatially held-out corridors

### Operational (measured in the control room, not the notebook)

| Metric | Target |
| --- | --- |
| False alarms per corridor per week | <= 1.0 |
| Alerts acknowledged within 10 min | >= 90% |
| **Recommended-route-is-blocked rate** | **exactly 0%** - guarded by `TestRerouteSafety` |
| Critical-cargo SLA adherence vs. no-reroute control | +15 percentage points |
| Avoided delay (minutes saved vs. counterfactual original route) | reported per reroute |

---

## 6. Explainability requirements

The UI already shows a factor breakdown for every score. The trained model must
keep that promise:

- **SHAP values** per prediction, mapped back to the same seven human factors
- **Monotonicity constraints**: more rainfall must never *decrease* risk
- **Stability**: re-running on the same inputs 24h apart must not flip the top
  factor unless the inputs moved > 10%
- Any prediction the model cannot explain is not shown to an operator

---

## 7. Drift and live monitoring

Once deployed:

- **Weekly**: rolling 30-day PR-AUC and calibration, auto-posted to the control room
- **Feature drift**: population stability index on each input; PSI > 0.2 raises a flag
- **Shadow mode**: every new model runs alongside the incumbent for one full
  month, scoring silently, before it is allowed to drive alerts
- **Auto-rollback**: if live PR-AUC falls below the incumbent for 2 consecutive
  weeks, revert and page the team

---

## 8. What we will report at the SIH demo

Until the labelled dataset exists, RouteMind reports:

- **What is live**: rainfall, forecast, elevation, seismic, road geometry, and
  optional measured traffic - each with a visible per-feed provenance state
- **What is modelled**: corridor risk, congestion (without a TomTom key), bypass
  alignments - each labelled as such in the UI
- **What is synthetic**: vehicles, deliveries, depots and drivers - marked with a
  `Sim` tag in the interface, because there is no public real-time fleet feed
- **What is simulated**: the disruption drill, tagged `SIMULATION` in the header
  and `simulation` in the incident source field

That separation is the deliverable. A judge should be able to point at any number
on the screen and get a straight answer about where it came from.
