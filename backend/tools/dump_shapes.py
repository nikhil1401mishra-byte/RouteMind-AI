#!/usr/bin/env python3
"""Print the exact keys the frontend must bind to."""
import json, os, sys
from pathlib import Path

os.environ["ROUTEMIND_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import api, simctl
from app.store import STORE

STORE.bootstrap()


def show(title, obj):
    print("\n===== " + title + " =====")
    print(json.dumps(obj, indent=1, default=str)[:1800])


_, overview = api.handle("GET", "/api/overview")
show("metrics", overview["metrics"])
show("top_risks[0]", overview["top_risks"][0])
show("provenance", overview["provenance"])
print("\noverview keys:", sorted(overview.keys()))

_, mp = api.handle("GET", "/api/map")
show("corridor[0] (geometry trimmed)", {**mp["corridors"][0], "geometry": mp["corridors"][0]["geometry"][:2]})
show("vehicle[0]", {k: v for k, v in mp["vehicles"][0].items() if k != "route_geometry"})
print("\nincident count:", len(mp["incidents"]))
if mp["incidents"]:
    show("incident[0]", mp["incidents"][0])
show("city[0]", mp["cities"][0])
show("depot[0]", mp["depots"][0])

_, dl = api.handle("GET", "/api/deliveries")
show("delivery[0]", dl["deliveries"][0])

_, tr = api.handle("GET", "/api/traffic")
show("traffic segment[0] (geom trimmed)", {**tr["segments"][0], "geometry": tr["segments"][0]["geometry"][:1]})

_, inv = api.handle("GET", "/api/inventory")
show("inventory item[0]", inv["items"][0])
if inv["suggested_transfers"]:
    show("transfer[0]", inv["suggested_transfers"][0])

sim = simctl.start(STORE, "landslide-nh306")
print("\nsimulation keys:", sorted(sim.keys()))
show("sim step[0]", sim["steps"][0])
show("sim route option[0] (geom trimmed)", {**sim["route_options"][0], "geometry": sim["route_options"][0]["geometry"][:1]})
show("sim incident", sim["incident"])
show("sim vehicle", sim.get("vehicle"))
show("sim delivery", sim.get("delivery"))

_, al = api.handle("GET", "/api/alerts")
if al["alerts"]:
    show("alert[0]", al["alerts"][0])
show("alert counts", al["counts"])

_, sc = api.handle("GET", "/api/simulation/scenarios")
show("scenario[0]", sc["scenarios"][0])

_, risk = api.handle("GET", "/api/risk/NH306-SCL-AJL")
show("risk factors", risk["risk"]["factors"][:3])
print("\nrisk keys:", sorted(risk["risk"].keys()))

simctl.reset(STORE)
