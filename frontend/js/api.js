/* ==========================================================================
   RouteMind AI - backend client
   Talks to the Python API. Same origin when served by run.py; falls back to
   127.0.0.1:8000 if the page was opened straight off disk.
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  const LOCAL_FALLBACK = "http" + "://127.0.0.1:8000";
  const BASE = location.protocol === "file:" ? LOCAL_FALLBACK : "";

  let consecutiveFailures = 0;

  async function request(method, path, body) {
    const url = BASE + path;
    const options = {
      method: method,
      headers: { Accept: "application/json" },
      cache: "no-store",
    };
    if (body !== undefined && body !== null) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    let response;
    try {
      response = await fetch(url, options);
    } catch (err) {
      consecutiveFailures += 1;
      RM.api.reachable = false;
      throw new Error(
        "Cannot reach the RouteMind backend. Start it with: python run.py"
      );
    }

    let payload = null;
    const text = await response.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (err) {
        payload = { error: text.slice(0, 300) };
      }
    }

    if (!response.ok) {
      consecutiveFailures += 1;
      const message =
        (payload && (payload.error || payload.detail || payload.message)) ||
        "Request failed (" + response.status + ")";
      throw new Error(message);
    }

    consecutiveFailures = 0;
    RM.api.reachable = true;
    return payload;
  }

  const get = (path) => request("GET", path);
  const post = (path, body) => request("POST", path, body || {});

  RM.api = {
    base: BASE,
    reachable: true,
    get failures() {
      return consecutiveFailures;
    },

    raw: request,

    health: () => get("/api/health"),
    systemStatus: () => get("/api/system/status"),
    overview: () => get("/api/overview"),
    mapBundle: () => get("/api/map"),

    corridors: () => get("/api/corridors"),
    corridor: (id) => get("/api/corridors/" + encodeURIComponent(id)),
    risk: (id) => get("/api/risk/" + encodeURIComponent(id)),
    modelCard: () => get("/api/model-card"),

    vehicles: () => get("/api/vehicles"),
    vehicle: (id) => get("/api/vehicles/" + encodeURIComponent(id)),
    deliveries: () => get("/api/deliveries"),
    incidents: () => get("/api/incidents"),
    alerts: () => get("/api/alerts"),
    traffic: () => get("/api/traffic"),
    inventory: () => get("/api/inventory"),

    reportIncident: (payload) => post("/api/incidents", payload),
    setIncidentStatus: (id, status) =>
      post("/api/incidents/" + encodeURIComponent(id) + "/status", { status: status }),

    alertAction: (id, action, assignee) =>
      post("/api/alerts/" + encodeURIComponent(id) + "/action", {
        action: action,
        assignee: assignee,
      }),
    acknowledgeAll: () => post("/api/alerts/acknowledge-all", {}),

    planRoutes: (vehicleId) => post("/api/routes/plan", { vehicle_id: vehicleId }),

    simulation: () => get("/api/simulation"),
    scenarios: () => get("/api/simulation/scenarios"),
    simStart: (scenarioId) => post("/api/simulation/start", { scenario_id: scenarioId }),
    simAccept: (routeId) => post("/api/simulation/accept", { route_id: routeId }),
    simDecline: () => post("/api/simulation/decline", {}),
    simReset: () => post("/api/simulation/reset", {}),
  };
})();
