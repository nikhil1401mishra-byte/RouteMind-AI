#!/usr/bin/env python3
"""Offline-safe test suite.

Forces ROUTEMIND_OFFLINE=1 so tests never depend on the internet and always
exercise the snapshot/fallback paths.

Run:  python tests/test_all.py
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

os.environ["ROUTEMIND_OFFLINE"] = "1"

# Tests must never write to the shipped database file, so point the SQLite
# engine at a throwaway directory *before* the app package is imported.
import tempfile  # noqa: E402

_TEST_DB_DIR = tempfile.mkdtemp(prefix="routemind-tests-")
os.environ["ROUTEMIND_SQLITE_PATH"] = str(Path(_TEST_DB_DIR) / "test.db")
os.environ.pop("ROUTEMIND_DB", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import api, auth, config, db, geo, network  # noqa: E402
from app import persistence, routes_engine, simctl  # noqa: E402
from app.services import incidents as incidents_service  # noqa: E402
from app.services import risk as risk_service  # noqa: E402
from app.services import traffic as traffic_service  # noqa: E402
from app.store import STORE  # noqa: E402


class TestGeo(unittest.TestCase):
    def test_haversine_known_distance(self):
        guwahati = network.city_coord("guwahati")
        shillong = network.city_coord("shillong")
        km = geo.haversine_km(guwahati, shillong)
        # Straight-line distance is roughly 63 km.
        self.assertGreater(km, 55)
        self.assertLess(km, 75)

    def test_point_at_fraction_endpoints(self):
        line = [(91.0, 26.0), (92.0, 26.0), (93.0, 26.0)]
        self.assertEqual(geo.point_at_fraction(line, 0.0), line[0])
        self.assertEqual(geo.point_at_fraction(line, 1.0), line[-1])
        mid = geo.point_at_fraction(line, 0.5)
        self.assertAlmostEqual(mid[0], 92.0, places=4)

    def test_simplify_reduces_points(self):
        line = [(91.0 + i * 0.01, 26.0) for i in range(60)]
        self.assertLess(len(geo.simplify(line, 0.5)), len(line))

    def test_distance_point_to_line(self):
        line = [(91.0, 26.0), (92.0, 26.0)]
        self.assertLess(geo.distance_point_to_line_km((91.5, 26.0), line), 0.5)
        self.assertGreater(geo.distance_point_to_line_km((91.5, 27.0), line), 90)


class TestRiskModel(unittest.TestCase):
    def setUp(self):
        self.corridor = network.CORRIDOR_BY_ID["NH306-SCL-AJL"]
        self.line = network.FALLBACK_GEOMETRY["NH306-SCL-AJL"]

    def _score(self, rain_next, rain_48=0.0, peak=0.0):
        weather = {
            "rain_24h_mm": rain_48 / 2, "rain_48h_mm": rain_48,
            "rain_next_24h_mm": rain_next, "max_hourly_next_24h": peak,
            "precip_probability_max": 80, "available": True,
        }
        return risk_service.score_corridor(
            self.corridor, self.line, weather, [], {"level": "free"})

    def test_rainfall_increases_risk(self):
        dry = self._score(0.0)
        wet = self._score(150.0, rain_48=120.0, peak=22.0)
        self.assertGreater(wet["probability"], dry["probability"])

    def test_probability_is_bounded(self):
        extreme = self._score(900.0, rain_48=900.0, peak=90.0)
        self.assertLessEqual(extreme["probability"], 1.0)
        self.assertGreaterEqual(self._score(0.0)["probability"], 0.0)

    def test_factors_are_explained_and_ranked(self):
        result = self._score(120.0, rain_48=90.0, peak=15.0)
        self.assertTrue(result["factors"])
        contributions = [f["contribution"] for f in result["factors"]]
        self.assertEqual(contributions, sorted(contributions, reverse=True))
        for factor in result["factors"]:
            self.assertIn("label", factor)
            self.assertIn("share", factor)

    def test_model_is_labelled_as_not_trained_ml(self):
        result = self._score(10.0)
        self.assertIn("not a trained ML model", result["model_kind"])
        self.assertFalse(api.MODEL_CARD["is_trained_ml"])

    def test_bands_and_reliability(self):
        self.assertEqual(risk_service.band_for(0.9), "critical")
        self.assertEqual(risk_service.band_for(0.5), "high")
        self.assertEqual(risk_service.band_for(0.3), "moderate")
        self.assertEqual(risk_service.band_for(0.05), "low")
        self.assertGreater(risk_service.reliability_from_probability(0.1),
                           risk_service.reliability_from_probability(0.8))

    def test_blocked_status(self):
        self.assertEqual(risk_service.status_for(0.1, True), "blocked")
        self.assertEqual(risk_service.status_for(0.6, False), "at-risk")
        self.assertEqual(risk_service.status_for(0.1, False), "operational")


class TestTraffic(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(traffic_service.level_from_ratio(1.0), "free")
        self.assertEqual(traffic_service.level_from_ratio(0.75), "light")
        self.assertEqual(traffic_service.level_from_ratio(0.6), "moderate")
        self.assertEqual(traffic_service.level_from_ratio(0.4), "heavy")
        self.assertEqual(traffic_service.level_from_ratio(0.1), "severe")

    def test_congestion_factor_monotonic(self):
        order = ["free", "light", "moderate", "heavy", "severe"]
        values = [traffic_service.congestion_factor(x) for x in order]
        self.assertEqual(values, sorted(values))

    def test_notice_is_honest_without_key(self):
        self.assertIn("Modeled", traffic_service.traffic_notice("modeled"))


class TestStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        STORE.bootstrap()

    def test_every_corridor_assessed(self):
        self.assertEqual(len(STORE.corridor_state), len(network.CORRIDORS))
        for state in STORE.corridor_state.values():
            self.assertIn("risk", state)
            self.assertIn(state["status"], ("operational", "at-risk", "blocked"))

    def test_geometry_available_offline(self):
        for cid in network.CORRIDOR_BY_ID:
            self.assertTrue(STORE.geometries.get(cid), "no geometry for " + cid)

    def test_vehicles_are_positioned(self):
        self.assertTrue(STORE.vehicles)
        for v in STORE.vehicles.values():
            self.assertIsNotNone(v["lng"])
            self.assertIsNotNone(v["lat"])
            self.assertTrue(21.0 < v["lat"] < 30.0, "lat out of region: " + str(v["lat"]))
            self.assertTrue(87.0 < v["lng"] < 98.0, "lng out of region: " + str(v["lng"]))

    def test_vehicles_move_on_tick(self):
        vehicle = next(v for v in STORE.vehicles.values() if v["status"] == "moving")
        before = vehicle["progress"]
        STORE.last_tick -= 5.0
        STORE.tick()
        self.assertNotEqual(before, vehicle["progress"])

    def test_metrics_are_consistent(self):
        m = STORE.metrics()
        self.assertEqual(m["total_vehicles"], len(STORE.vehicles))
        self.assertEqual(
            m["operational_roads"] + m["at_risk_roads"] + m["blocked_roads"],
            len(network.CORRIDORS))
        self.assertTrue(0 <= m["on_time_pct"] <= 100)

    def test_incidents_carry_provenance(self):
        for inc in STORE.all_incidents():
            self.assertIn("source", inc)
            self.assertIn("source_label", inc)
            self.assertIn(inc["source"], (
                "usgs-live", "open-meteo-derived", "risk-model",
                "field-report", "simulation"))

    def test_manual_incident_can_block_a_corridor(self):
        incident = STORE.report_incident({
            "corridor_id": "NH8-AGT-SCL", "type": "roadblock",
            "severity": "critical", "title": "Unit test block",
            "description": "test", "blocks_road": True, "fraction": 0.5,
        })
        self.assertEqual(STORE.corridor_state["NH8-AGT-SCL"]["status"], "blocked")
        STORE.manual_incidents.pop(incident["id"], None)
        STORE.refresh_live(force=True)
        self.assertNotEqual(STORE.corridor_state["NH8-AGT-SCL"]["status"], "blocked")


class TestIncidentDerivation(unittest.TestCase):
    def test_heavy_rain_creates_incident(self):
        corridor_state = {
            "NH306-SCL-AJL": {
                "weather": {"available": True, "rain_next_24h_mm": 140.0,
                            "max_hourly_next_24h": 20.0},
                "risk": {"probability": 0.4, "factors": [], "headline": ""},
            }
        }
        geometries = {"NH306-SCL-AJL": network.FALLBACK_GEOMETRY["NH306-SCL-AJL"]}
        derived = incidents_service.derive_from_live(corridor_state, geometries, [])
        rain = [d for d in derived if d["type"] == "heavy-rain"]
        self.assertEqual(len(rain), 1)
        self.assertEqual(rain[0]["severity"], "critical")
        self.assertEqual(rain[0]["source"], "open-meteo-derived")

    def test_light_rain_creates_nothing(self):
        corridor_state = {
            "NH306-SCL-AJL": {
                "weather": {"available": True, "rain_next_24h_mm": 4.0,
                            "max_hourly_next_24h": 1.0},
                "risk": {"probability": 0.1, "factors": [], "headline": ""},
            }
        }
        geometries = {"NH306-SCL-AJL": network.FALLBACK_GEOMETRY["NH306-SCL-AJL"]}
        self.assertEqual(incidents_service.derive_from_live(corridor_state, geometries, []), [])


class TestRoutesEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        STORE.bootstrap()

    def test_options_generated_offline_via_corridor_graph(self):
        vehicle = STORE.vehicles["TR-104"]
        options, _ = routes_engine.plan_for_vehicle(
            STORE, vehicle,
            detour_corridors=["NH37-SCL-IMF"], detour_label="NH-37 via Jiribam")
        self.assertTrue(options, "no route options produced offline")
        for option in options:
            self.assertTrue(option["geometry"])
            self.assertIn(option["risk_band"], ("low", "moderate", "high", "critical"))
            self.assertTrue(0 <= option["reliability"] <= 100)
            self.assertTrue(option["explanation"])

    def test_critical_cargo_weights_risk_more(self):
        self.assertGreater(routes_engine.PRIORITY_WEIGHT["critical"],
                           routes_engine.PRIORITY_WEIGHT["standard"])


class TestSimulationFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        STORE.bootstrap()

    def setUp(self):
        simctl.reset(STORE)

    def tearDown(self):
        simctl.reset(STORE)

    def test_full_cascade(self):
        state = simctl.start(STORE, "landslide-nh306")

        self.assertEqual(state["phase"], "awaiting-accept")
        self.assertTrue(state["awaiting_decision"])

        # 1. corridor blocked
        self.assertEqual(STORE.corridor_state["NH306-SCL-AJL"]["status"], "blocked")

        # 2. incident injected and labelled as simulated
        incident = state["incident"]
        self.assertEqual(incident["source"], "simulation")
        self.assertTrue(incident["blocks_road"])

        # 3. vehicle halted
        self.assertEqual(STORE.vehicles["TR-104"]["status"], "halted")

        # 4. delivery at risk
        self.assertEqual(STORE.deliveries["DLV-2041"]["status"], "at-risk")

        # 5. alternatives scored, one recommended
        options = state["route_options"]
        self.assertTrue(options)
        self.assertEqual(sum(1 for o in options if o.get("recommended")), 1)

        # 6. alert raised
        self.assertTrue(any(a["severity"] == "critical" for a in STORE.alerts.values()))

        # 7. accept the reroute
        after = simctl.accept(STORE)
        self.assertEqual(after["phase"], "completed")
        self.assertTrue(STORE.vehicles["TR-104"]["rerouted"])
        self.assertEqual(STORE.vehicles["TR-104"]["status"], "moving")
        self.assertTrue(STORE.reroute_history)

        # 8. every step marked done
        self.assertTrue(all(s["status"] == "done" for s in after["steps"]))

    def test_decline_holds_vehicle(self):
        simctl.start(STORE, "landslide-nh306")
        state = simctl.decline(STORE)
        self.assertEqual(state["phase"], "completed")
        self.assertFalse(STORE.vehicles["TR-104"]["rerouted"])

    def test_reset_restores_baseline(self):
        simctl.start(STORE, "landslide-nh306")
        simctl.accept(STORE)
        state = simctl.reset(STORE)
        self.assertEqual(state["phase"], "idle")
        self.assertFalse(STORE.vehicles["TR-104"]["rerouted"])
        self.assertNotEqual(STORE.corridor_state["NH306-SCL-AJL"]["status"], "blocked")
        self.assertEqual(STORE.deliveries["DLV-2041"]["delay_min"], 0)

    def test_scenarios_are_listed(self):
        status, payload = api.handle("GET", "/api/simulation/scenarios")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["scenarios"]), 3)


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        STORE.bootstrap()

    def _get(self, path, query=None):
        status, payload = api.handle("GET", path, query or {}, {})
        self.assertEqual(status, 200, path + " returned " + str(status))
        # Everything must survive JSON serialisation.
        json.dumps(payload, default=str)
        return payload

    def test_health(self):
        self.assertTrue(self._get("/api/health")["ok"])

    def test_overview_shape(self):
        payload = self._get("/api/overview")
        for key in ("metrics", "top_risks", "attention", "risk_distribution",
                    "provenance", "model"):
            self.assertIn(key, payload)
        self.assertFalse(payload["model"]["is_trained_ml"])
        self.assertTrue(payload["top_risks"])

    def test_map_bundle_has_everything_the_map_needs(self):
        payload = self._get("/api/map")
        self.assertEqual(len(payload["corridors"]), len(network.CORRIDORS))
        self.assertTrue(payload["vehicles"])
        self.assertTrue(payload["cities"])
        self.assertTrue(payload["depots"])
        for corridor in payload["corridors"]:
            self.assertTrue(corridor["geometry"], corridor["id"] + " missing geometry")
            self.assertGreaterEqual(len(corridor["geometry"]), 2)
            for lng, lat in corridor["geometry"]:
                self.assertTrue(80 < lng < 100)
                self.assertTrue(20 < lat < 32)

    def test_traffic_endpoint_declares_mode(self):
        payload = self._get("/api/traffic")
        self.assertIn(payload["mode"], ("modeled", "live-flow"))
        self.assertTrue(payload["notice"])
        self.assertEqual(len(payload["segments"]), len(network.CORRIDORS))
        for seg in payload["segments"]:
            self.assertIn(seg["level"], traffic_service.LEVELS)

    def test_vehicle_detail_and_filters(self):
        payload = self._get("/api/vehicles/TR-104")
        self.assertEqual(payload["id"], "TR-104")
        self.assertIn("corridor_risk", payload)
        filtered = self._get("/api/vehicles", {"priority": "critical"})
        self.assertTrue(filtered["vehicles"])
        for v in filtered["vehicles"]:
            self.assertEqual(v["priority"], "critical")

    def test_deliveries_and_incidents(self):
        self.assertTrue(self._get("/api/deliveries")["deliveries"])
        self.assertIn("incidents", self._get("/api/incidents"))

    def test_risk_endpoint_is_explainable(self):
        payload = self._get("/api/risk/NH306-SCL-AJL")
        self.assertFalse(payload["is_trained_ml"])
        self.assertTrue(payload["risk"]["factors"])

    def test_model_card_is_honest(self):
        payload = self._get("/api/model-card")
        self.assertFalse(payload["is_trained_ml"])
        self.assertIn("NOT a trained", payload["honest_statement"])
        self.assertIn("phase5_plan", payload)

    def test_inventory_suggests_transfers(self):
        payload = self._get("/api/inventory")
        self.assertTrue(payload["shortages"])
        self.assertTrue(payload["suggested_transfers"])

    def test_system_status_reports_provenance(self):
        payload = self._get("/api/system/status")
        self.assertIn("sources", payload)
        self.assertIn("traffic_mode", payload)
        self.assertTrue(payload["offline_mode"])

    def test_alert_lifecycle(self):
        alerts = self._get("/api/alerts")["alerts"]
        if not alerts:
            self.skipTest("no alerts in current conditions")
        alert_id = alerts[0]["id"]
        status, payload = api.handle(
            "POST", "/api/alerts/" + alert_id + "/action", {}, {"action": "acknowledge"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["alert"]["status"], "acknowledged")

    def test_routes_plan_by_city_names(self):
        status, payload = api.handle("POST", "/api/routes/plan", {}, {
            "origin": "silchar", "destination": "aizawl",
            "priority": "critical",
            "detour_corridors": ["NH306-SCL-AJL"],
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["options"])

    def test_unknown_route_returns_404(self):
        status, _ = api.handle("GET", "/api/nope", {}, {})
        self.assertEqual(status, 404)

    def test_unknown_corridor_returns_404(self):
        status, _ = api.handle("GET", "/api/corridors/NOT-A-ROAD", {}, {})
        self.assertEqual(status, 404)


class TestRerouteSafety(unittest.TestCase):
    """A road we believe is blocked must never come back as the recommendation.

    This is the regression guard for the worst possible failure of this system:
    confidently routing an emergency vehicle into a closure.
    """

    def setUp(self):
        simctl.reset(STORE)

    def tearDown(self):
        simctl.reset(STORE)

    def test_recommended_option_is_never_blocked(self):
        state = simctl.start(STORE, "landslide-nh306")
        options = state["route_options"]
        self.assertTrue(options, "scenario produced no route options")
        for option in options:
            with self.subTest(option=option["id"]):
                self.assertFalse(
                    option["blocked"] and option["recommended"],
                    f"{option['id']} was recommended while blocked",
                )

    def test_scenario_yields_a_viable_recommendation(self):
        state = simctl.start(STORE, "landslide-nh306")
        viable = [o for o in state["route_options"] if not o["blocked"]]
        self.assertTrue(viable, "every option was blocked; nothing to fall back to")

        recommended_id = state["recommended_route_id"]
        self.assertIsNotNone(recommended_id)
        chosen = next(o for o in state["route_options"] if o["id"] == recommended_id)
        self.assertFalse(chosen["blocked"])

    def test_blocked_options_say_why(self):
        state = simctl.start(STORE, "landslide-nh306")
        for option in state["route_options"]:
            if option["blocked"]:
                with self.subTest(option=option["id"]):
                    self.assertTrue(
                        option["blocked_reason"],
                        "a blocked option must explain the closure",
                    )

    def test_planner_endpoint_respects_the_closure(self):
        simctl.start(STORE, "landslide-nh306")
        status, payload = api.handle(
            "POST", "/api/routes/plan", {}, {"vehicle_id": "TR-104"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["options"])
        for option in payload["options"]:
            with self.subTest(option=option["id"]):
                self.assertFalse(option["blocked"] and option["recommended"])


# --------------------------------------------------------------- PHASE 2
class TestDatabase(unittest.TestCase):
    """Schema, migrations and the geometry helpers."""

    def test_sqlite_is_the_default_backend(self):
        self.assertEqual(db.get_engine().dialect, "sqlite")

    def test_initial_migration_is_applied_and_nothing_pending(self):
        applied, pending = db.status(db.get_engine())
        self.assertIn("001_initial", applied)
        self.assertEqual(pending, [])

    def test_migrate_is_idempotent(self):
        self.assertEqual(db.migrate(db.get_engine()), [])

    def test_every_registered_table_exists(self):
        engine = db.get_engine()
        for table in db.TABLES:
            engine.query("SELECT * FROM " + table + " LIMIT 1")

    def test_geometry_helpers_round_trip(self):
        coords = [[91.7362, 26.1445], [92.7789, 24.8333]]
        decoded = db.decode_geojson(db.line_geojson(coords))
        self.assertEqual(decoded["type"], "LineString")
        self.assertEqual(len(decoded["coordinates"]), 2)
        point = db.decode_geojson(db.point_geojson(91.7362, 26.1445))
        self.assertEqual(point["type"], "Point")
        box = db.bbox_of(coords)
        self.assertAlmostEqual(box["min_lng"], 91.7362)
        self.assertAlmostEqual(box["max_lat"], 26.1445)


class TestRepositories(unittest.TestCase):
    """Validation, CRUD and pagination on the generic repository."""

    def test_crud_round_trip(self):
        roads = db.repo("roads")
        roads.upsert({"id": "TEST-ROAD", "name": "Test road", "data_class": "REAL"})
        self.assertEqual(roads.get("TEST-ROAD")["name"], "Test road")
        roads.update("TEST-ROAD", {"condition": "poor"})
        self.assertEqual(roads.get("TEST-ROAD")["condition"], "poor")
        self.assertTrue(roads.delete("TEST-ROAD"))
        self.assertIsNone(roads.get("TEST-ROAD"))

    def test_upsert_does_not_duplicate(self):
        roads = db.repo("roads")
        before = roads.count()
        roads.upsert({"id": "TEST-UPSERT", "name": "One"})
        roads.upsert({"id": "TEST-UPSERT", "name": "Two"})
        self.assertEqual(roads.count(), before + 1)
        self.assertEqual(roads.get("TEST-UPSERT")["name"], "Two")
        roads.delete("TEST-UPSERT")

    def test_unknown_column_is_rejected(self):
        with self.assertRaises(db.ValidationError):
            db.repo("roads").insert({"id": "BAD", "name": "x", "nope": 1})

    def test_missing_required_field_is_rejected(self):
        with self.assertRaises(db.ValidationError):
            db.repo("roads").insert({"id": "BAD"})

    def test_enum_value_is_rejected(self):
        with self.assertRaises(db.ValidationError):
            db.repo("incidents").insert({"id": "BAD", "type": "landslide",
                                         "title": "x", "severity": "apocalyptic"})

    def test_list_is_paginated(self):
        page = db.repo("roads").list(limit=5)
        self.assertEqual(sorted(page.keys()),
                         ["has_more", "items", "limit", "offset", "total"])
        self.assertLessEqual(len(page["items"]), 5)
        self.assertGreaterEqual(page["total"], len(page["items"]))

    def test_bad_order_by_is_rejected(self):
        with self.assertRaises(db.ValidationError):
            db.repo("roads").list(order_by="name; DROP TABLE roads")


class TestAuth(unittest.TestCase):
    """Password hashing, sessions and the server-side permission matrix."""

    def test_password_hash_is_not_reversible(self):
        hashed, salt = auth.hash_password("correct horse battery")
        self.assertTrue(auth.verify_password("correct horse battery", hashed, salt))
        self.assertFalse(auth.verify_password("wrong", hashed, salt))
        self.assertNotIn("correct horse battery", hashed)

    def test_permission_matrix(self):
        dispatcher = {"role": "dispatcher"}
        field = {"role": "field_officer"}
        logistics = {"role": "logistics_manager"}
        self.assertTrue(auth.can(dispatcher, "simulation.accept"))
        self.assertFalse(auth.can(field, "simulation.accept"))
        self.assertTrue(auth.can(field, "incident.create"))
        self.assertTrue(auth.can(logistics, "inventory.transfer"))
        self.assertFalse(auth.can(dispatcher, "user.manage"))

    def test_require_raises_for_denied_action(self):
        with self.assertRaises(auth.AuthError) as ctx:
            auth.require({"role": "field_officer"}, "simulation.accept")
        self.assertEqual(ctx.exception.status, 403)

    def test_session_lifecycle(self):
        auth.ensure_seed_users()
        user = auth.user_by_username("dispatcher")
        self.assertIsNotNone(user)
        token, expires_at = auth.create_session(user["id"], "unit-test")
        self.assertGreater(expires_at, 0)
        principal = auth.resolve_token(token)
        self.assertEqual(principal["role"], "dispatcher")
        self.assertTrue(principal["authenticated"])
        self.assertTrue(auth.destroy_session(token))
        self.assertIsNone(auth.resolve_token(token))

    def test_password_login_fails_closed_without_configured_secret(self):
        # No ROUTEMIND_PASSWORD_* variables are set in the test environment, so
        # password login must be unavailable rather than accept a default.
        self.assertFalse(auth.login_available())
        with self.assertRaises(auth.AuthError):
            auth.authenticate("dispatcher", "password")


class TestRoleEnforcement(unittest.TestCase):
    """Authorization is enforced by the API, not the browser."""

    def test_field_officer_cannot_accept_a_reroute(self):
        status, payload = api.handle("POST", "/api/simulation/accept", {},
                                     {"route_id": "RT-4401"},
                                     {"X-RouteMind-Role": "field_officer"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "forbidden")

    def test_field_officer_can_report_an_incident(self):
        status, _ = api.handle("POST", "/api/incidents", {},
                               {"corridor_id": "NH6-GHY-SCL",
                                "description": "Tree down near Nongpoh"},
                               {"X-RouteMind-Role": "field_officer"})
        self.assertEqual(status, 201)

    def test_audit_log_is_admin_only(self):
        denied, _ = api.handle("GET", "/api/audit", {}, {},
                               {"X-RouteMind-Role": "dispatcher"})
        allowed, payload = api.handle("GET", "/api/audit", {}, {},
                                      {"X-RouteMind-Role": "admin"})
        self.assertEqual(denied, 403)
        self.assertEqual(allowed, 200)
        self.assertIn("items", payload)

    def test_mutations_are_recorded_in_the_audit_log(self):
        api.handle("POST", "/api/alerts/acknowledge-all", {}, {},
                   {"X-RouteMind-Role": "dispatcher"})
        rows = db.repo("audit_log").list(order_by="at", desc=True, limit=25)["items"]
        self.assertIn("alert.acknowledge_all", [r["action"] for r in rows])

    def test_role_header_cannot_escalate_in_strict_mode(self):
        original = config.AUTH_MODE
        config.AUTH_MODE = "strict"
        try:
            status, payload = api.handle("POST", "/api/simulation/reset", {}, {},
                                         {"X-RouteMind-Role": "admin"})
        finally:
            config.AUTH_MODE = original
        self.assertEqual(status, 401)
        self.assertEqual(payload["code"], "unauthorized")

    def test_reads_stay_open_to_the_control_room(self):
        for path in ("/api/overview", "/api/map", "/api/alerts", "/api/inventory"):
            status, _ = api.handle("GET", path, {}, {},
                                   {"X-RouteMind-Role": "field_officer"})
            self.assertEqual(status, 200, path)


class TestPersistence(unittest.TestCase):
    """The database is the system of record for durable state."""

    def test_reference_data_is_persisted_without_warnings(self):
        api.handle("GET", "/api/overview", {}, {})
        counts = persistence.counts()
        self.assertEqual(counts["roads"], len(network.CORRIDORS))
        self.assertEqual(counts["vehicles"], len(STORE.vehicles))
        self.assertEqual(counts["deliveries"], len(STORE.deliveries))
        self.assertGreater(counts["risk_predictions"], 0)
        self.assertGreater(counts["users"], 0)
        self.assertEqual(persistence.warnings(), [])

    def test_reported_incident_is_stored_with_geometry_and_provenance(self):
        status, payload = api.handle("POST", "/api/incidents", {}, {
            "corridor_id": "NH306-SCL-AJL", "type": "landslide",
            "severity": "high", "description": "Slope failure at km 44",
            "blocks_road": True})
        self.assertEqual(status, 201)
        row = db.repo("incidents").get(payload["incident"]["id"])
        self.assertIsNotNone(row)
        self.assertEqual(row["data_class"], "REAL")
        self.assertTrue(row["blocks_road"])
        self.assertEqual(db.decode_geojson(row["geom_json"])["type"], "Point")
        # Leave the network as we found it so later test classes are isolated.
        api.handle("POST", "/api/incidents/" + payload["incident"]["id"] + "/status",
                   {}, {"status": "resolved"})

    def test_incident_status_change_is_persisted(self):
        _, created = api.handle("POST", "/api/incidents", {}, {
            "corridor_id": "NH37-SCL-IMF", "description": "Water on road"})
        incident_id = created["incident"]["id"]
        api.handle("POST", "/api/incidents/" + incident_id + "/status", {},
                   {"status": "resolved"})
        row = db.repo("incidents").get(incident_id)
        self.assertEqual(row["status"], "resolved")
        self.assertIsNotNone(row["resolved_at"])

    def test_route_plan_and_options_are_persisted(self):
        status, payload = api.handle("POST", "/api/routes/plan", {},
                                     {"vehicle_id": "TR-104"})
        self.assertEqual(status, 200)
        plan_id = payload["plan_id"]
        self.assertIsNotNone(db.repo("route_plans").get(plan_id))
        options = db.repo("route_options").all("plan_id = ?", (plan_id,))
        self.assertEqual(len(options), len(payload["options"]))
        expected = {o["id"] for o in payload["options"] if o.get("recommended")}
        stored = {str(o["id"]).split("::", 1)[-1] for o in options if o["recommended"]}
        self.assertEqual(stored, expected)

    def test_risk_predictions_carry_model_metadata(self):
        api.handle("GET", "/api/overview", {}, {})
        rows = db.repo("risk_predictions").list(limit=1)["items"]
        self.assertTrue(rows)
        row = rows[0]
        self.assertEqual(row["data_class"], "PREDICTED")
        self.assertEqual(row["model_kind"], "transparent-heuristic")
        self.assertTrue(row["model_version"])

    def test_field_report_sync_is_idempotent(self):
        body = {"corridor_id": "NH29-DMU-IMF", "description": "Bridge cracked",
                "client_uuid": "offline-uuid-test-1"}
        api.handle("POST", "/api/incidents", {}, dict(body))
        api.handle("POST", "/api/incidents", {}, dict(body))
        rows = db.repo("field_reports").all("client_uuid = ?", ("offline-uuid-test-1",))
        self.assertEqual(len(rows), 1)

    def test_data_class_vocabulary(self):
        self.assertEqual(persistence.classify("field-report"), "REAL")
        self.assertEqual(persistence.classify("usgs-live"), "REAL")
        self.assertEqual(persistence.classify("simulation"), "SIMULATED")
        self.assertEqual(persistence.classify("risk-model"), "PREDICTED")
        self.assertEqual(persistence.classify("open-meteo-derived"), "DERIVED")

    def test_status_endpoint_reports_storage(self):
        status, payload = api.handle("GET", "/api/system/status", {}, {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["storage"]["backend"], "sqlite")
        self.assertIn("incidents", payload["storage"]["system_of_record"])
        self.assertEqual(payload["auth"]["mode"], "demo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
