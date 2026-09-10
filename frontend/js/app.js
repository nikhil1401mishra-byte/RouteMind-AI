/* ==========================================================================
   RouteMind AI - application shell
   Routing between views, the polling loop, and all control wiring.
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  const POLL_MS = 4000;

  const PAGES = {
    control: ["Control room", "Live operational picture across the eight North Eastern states"],
    risk: ["Road risk", "Disruption probability for every corridor over the next 24 hours"],
    fleet: ["Fleet", "Live vehicle positions, cargo and exposure to road risk"],
    deliveries: ["Deliveries", "Consignments tracked against their SLA"],
    incidents: ["Incidents", "Live hazard feed, model predictions and field reports"],
    routes: ["Route planner", "Risk-aware alternatives scored on time and disruption"],
    inventory: ["Supply depots", "Stock cover and suggested inter-depot transfers"],
    simulation: ["Disruption drill", "Inject a disruption and watch the whole chain react"],
    alerts: ["Alerts", "Acknowledge, assign, escalate or resolve"],
  };

  RM.app = {
    booted: false,
    timer: null,
    busy: false,

    /* -------------------------------- boot -------------------------------- */

    async init() {
      this.wire();
      this.fromHash();
      window.addEventListener("hashchange", () => this.fromHash());
      this.tickClock();
      setInterval(() => this.tickClock(), 1000);

      try {
        await this.refresh(true);
        this.finishBoot();
      } catch (err) {
        this.bootFailed(err);
        return;
      }

      this.timer = setInterval(() => {
        if (document.hidden) return;
        this.refresh().catch(() => {});
      }, POLL_MS);
    },

    finishBoot() {
      const boot = RM.$("#boot");
      if (boot) {
        boot.classList.add("hidden");
        setTimeout(() => boot.remove(), 400);
      }
      this.booted = true;
    },

    bootFailed(err) {
      const note = RM.$("#boot-note");
      const boot = RM.$("#boot");
      if (boot) {
        boot.querySelector("p").textContent = "Cannot reach the RouteMind backend";
      }
      if (note) {
        note.innerHTML =
          RM.esc(err.message) +
          "<br><br>Start it from the project folder with:<br><b>python run.py</b>";
      }
    },

    /* ------------------------------ data load ------------------------------ */

    async refresh(first) {
      if (this.busy) return;
      this.busy = true;

      try {
        const wantSim =
          RM.state.view === "simulation" ||
          (RM.state.simulation && RM.state.simulation.is_active);

        const jobs = [
          RM.api.overview(),
          RM.api.mapBundle(),
          RM.api.deliveries(),
          RM.api.alerts(),
          wantSim ? RM.api.simulation() : Promise.resolve(null),
        ];

        const [overview, mapBundle, deliveries, alerts, simulation] = await Promise.all(jobs);

        RM.state.overview = overview;
        RM.state.map = mapBundle;
        RM.state.corridors = mapBundle.corridors || [];
        RM.state.vehicles = mapBundle.vehicles || [];
        RM.state.incidents = mapBundle.incidents || [];
        RM.state.deliveries = deliveries.deliveries || [];
        RM.state.alerts = alerts.alerts || [];
        RM.state.alertCounts = alerts.counts || {};
        if (simulation) RM.state.simulation = simulation;
        else if (overview.simulation) RM.state.simulation = overview.simulation;

        this.paint(first);
        this.setOnline(true);
      } catch (err) {
        this.setOnline(false, err);
        if (first) throw err;
      } finally {
        this.busy = false;
      }
    },

    setOnline(ok, err) {
      const pill = RM.$("#live-pill");
      const label = RM.$("#live-label");
      if (!pill || !label) return;
      if (!ok) {
        pill.className = "live-pill off";
        label.textContent = "Backend unreachable";
        if (err && !this._warned) {
          this._warned = true;
          RM.toast(err.message, "err", 6000);
        }
      } else {
        this._warned = false;
      }
    },

    /* ------------------------------- painting ------------------------------ */

    paint(first) {
      RM.dashboard.render();
      this.badges();

      if (!this.mainMap) {
        this.mainMap = new RM.MapView(RM.$("#map"), { center: [92.9, 25.7], zoom: 6.2 });
        RM.map = this.mainMap;
        this.mainMap.on("select", (event) => this.onMapSelect(event));
        this.mainMap.on("tilestatus", (status) => {
          RM.state.tilesDown = !status.usable;
          RM.dashboard.provenance((RM.state.overview || {}).provenance || {});
        });
      }

      this.mainMap.setData({
        corridors: RM.state.corridors,
        vehicles: RM.state.vehicles,
        incidents: RM.state.incidents,
        depots: (RM.state.map && RM.state.map.depots) || [],
        cities: (RM.state.map && RM.state.map.cities) || [],
      });

      if (first && RM.state.map && RM.state.map.bbox) {
        const b = RM.state.map.bbox;
        this.mainMap.fitTo(
          [[b.min_lng, b.min_lat], [b.max_lng, b.max_lat]],
          30
        );
      }

      if (RM.state.view === "risk") RM.risk.render();
      if (RM.state.view === "fleet") RM.fleet.render();
      if (RM.state.view === "deliveries") RM.deliveries.render();
      if (RM.state.view === "incidents") RM.incidents.render();
      if (RM.state.view === "alerts") RM.alerts.render();
      if (RM.state.view === "simulation") RM.simulation.render();
      if (RM.state.view === "routes") RM.routes.paint();

      RM.incidents.fillCorridors();
      RM.routes.fillVehicles();
      RM.simulation.fillScenarios();
    },

    badges() {
      const metrics = (RM.state.overview && RM.state.overview.metrics) || {};
      const set = (id, value, tone) => {
        const node = RM.$(id);
        if (!node) return;
        if (!value) {
          node.hidden = true;
          return;
        }
        node.hidden = false;
        node.textContent = value;
        node.className = "nav-badge" + (tone ? " " + tone : "");
      };

      set("#badge-risk", metrics.at_risk_roads + metrics.blocked_roads, metrics.blocked_roads ? "crit" : "warn");
      set("#badge-fleet", metrics.halted_vehicles, "crit");
      set("#badge-deliveries", metrics.deliveries_at_risk, "warn");
      set("#badge-incidents", metrics.critical_incidents, "crit");
      set("#badge-alerts", (metrics.alerts && metrics.alerts.unread) || 0, "crit");
    },

    onMapSelect(event) {
      if (event.type === "corridor") RM.risk.openCorridor(event.id);
      if (event.type === "vehicle") RM.fleet.openDrawer(event.id);
      if (event.type === "incident") RM.incidents.openDrawer(event.data);
      if (event.type === "depot") this.go("inventory");
    },

    /* -------------------------------- routing ------------------------------ */

    /** Deep links, so /#simulation can be bookmarked, shared or demoed directly. */
    fromHash() {
      const view = (location.hash || "").replace("#", "");
      if (PAGES[view] && view !== RM.state.view) this.go(view);
    },

    go(view) {
      if (!PAGES[view]) return;
      RM.state.view = view;
      if (location.hash !== "#" + view) location.hash = view;

      RM.$$("#nav .nav-item").forEach((btn) =>
        btn.classList.toggle("is-active", btn.dataset.view === view)
      );
      RM.$$(".view").forEach((section) =>
        section.classList.toggle("is-active", section.id === "view-" + view)
      );

      RM.$("#page-title").textContent = PAGES[view][0];
      RM.$("#page-sub").textContent = PAGES[view][1];
      const scroll = RM.$("#scroll");
      if (scroll) scroll.scrollTop = 0;

      if (view === "risk") RM.risk.render();
      if (view === "fleet") RM.fleet.render();
      if (view === "deliveries") RM.deliveries.render();
      if (view === "incidents") RM.incidents.render();
      if (view === "inventory") RM.inventory.load();
      if (view === "alerts") RM.alerts.render();
      if (view === "routes") {
        RM.routes.ensureMap();
        if (!RM.routes.options.length) RM.routes.plan();
      }
      if (view === "simulation") {
        RM.simulation.load();
      }
      if (view === "control" && this.mainMap) {
        setTimeout(() => this.mainMap.render(), 30);
      }
    },

    /* -------------------------------- clock -------------------------------- */

    tickClock() {
      const now = new Date();
      const time = RM.$("#clock-time");
      const date = RM.$("#clock-date");
      if (time) time.textContent = now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
      if (date) {
        date.textContent = now.toLocaleDateString("en-IN", {
          weekday: "short", day: "numeric", month: "short",
        }) + " IST";
      }
    },

    /* -------------------------------- wiring ------------------------------- */

    wire() {
      RM.$$("#nav .nav-item").forEach((btn) =>
        btn.addEventListener("click", () => this.go(btn.dataset.view))
      );

      RM.$$("[data-goto]").forEach((btn) =>
        btn.addEventListener("click", () => this.go(btn.dataset.goto))
      );

      const refresh = RM.$("#btn-refresh");
      if (refresh) {
        refresh.addEventListener("click", async () => {
          refresh.disabled = true;
          await this.refresh().catch(() => {});
          refresh.disabled = false;
          RM.toast("Refreshed from live feeds", "ok", 2000);
        });
      }

      const drill = RM.$("#btn-run-drill");
      if (drill) {
        drill.addEventListener("click", () => {
          this.go("simulation");
          RM.simulation.start();
        });
      }

      // map controls
      const modeGroup = RM.$("#map-mode");
      if (modeGroup) {
        modeGroup.addEventListener("click", (event) => {
          const btn = event.target.closest(".seg-btn");
          if (!btn) return;
          RM.$$("#map-mode .seg-btn").forEach((b) => b.classList.toggle("is-on", b === btn));
          RM.state.mapMode = btn.dataset.mode;
          if (this.mainMap) this.mainMap.setMode(btn.dataset.mode);
          const caption = RM.$("#map-caption");
          if (caption) {
            caption.textContent =
              btn.dataset.mode === "traffic"
                ? "Roads coloured by observed congestion - vehicles, incidents and depots plotted live"
                : "Roads coloured by disruption risk - vehicles, incidents and depots plotted live";
          }
          RM.dashboard.legend();
        });
      }

      const layers = RM.$("#map-layers");
      if (layers) {
        layers.addEventListener("change", (event) => {
          const input = event.target;
          if (!input.dataset.layer) return;
          RM.state.layers[input.dataset.layer] = input.checked;
          if (this.mainMap) this.mainMap.setLayer(input.dataset.layer, input.checked);
        });
      }

      // filters
      const bindSeg = (selector, handler) => {
        const host = RM.$(selector);
        if (!host) return;
        host.addEventListener("click", (event) => {
          const btn = event.target.closest(".seg-btn");
          if (!btn) return;
          RM.$$(selector + " .seg-btn").forEach((b) => b.classList.toggle("is-on", b === btn));
          handler(btn.dataset.filter);
        });
      };
      bindSeg("#risk-filter", (f) => RM.risk.setFilter(f));
      bindSeg("#delivery-filter", (f) => RM.deliveries.setFilter(f));
      bindSeg("#incident-filter", (f) => RM.incidents.setFilter(f));

      const fleetSearch = RM.$("#fleet-search");
      if (fleetSearch) {
        fleetSearch.addEventListener(
          "input",
          RM.debounce(() => RM.fleet.setQuery(fleetSearch.value), 140)
        );
      }

      // route planner
      const planBtn = RM.$("#btn-plan");
      if (planBtn) planBtn.addEventListener("click", () => RM.routes.plan());
      const planSelect = RM.$("#plan-vehicle");
      if (planSelect) planSelect.addEventListener("change", () => RM.routes.plan());

      // simulation
      const simStart = RM.$("#sim-start");
      if (simStart) simStart.addEventListener("click", () => RM.simulation.start());
      const simReset = RM.$("#sim-reset");
      if (simReset) simReset.addEventListener("click", () => RM.simulation.reset());
      const simAccept = RM.$("#sim-accept");
      if (simAccept) simAccept.addEventListener("click", () => RM.simulation.accept());
      const simDecline = RM.$("#sim-decline");
      if (simDecline) simDecline.addEventListener("click", () => RM.simulation.decline());

      // alerts
      const ackAll = RM.$("#ack-all");
      if (ackAll) ackAll.addEventListener("click", () => RM.alerts.acknowledgeAll());

      // incident form
      const form = RM.$("#incident-form");
      if (form) {
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          RM.incidents.submit();
        });
      }

      // drawer + model card
      const close = RM.$("#drawer-close");
      if (close) close.addEventListener("click", () => RM.closeDrawer());
      const scrim = RM.$("#drawer-scrim");
      if (scrim) scrim.addEventListener("click", () => RM.closeDrawer());
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") RM.closeDrawer();
      });

      const modelCard = RM.$("#open-model-card");
      if (modelCard) modelCard.addEventListener("click", () => RM.dashboard.modelCard());
      const feedCard = RM.$("#feed-card");
      if (feedCard) feedCard.addEventListener("click", () => this.showFeeds());
    },

    /* ---------------------------- data provenance --------------------------- */

    async showFeeds() {
      RM.openDrawer("Data sources", "Where every number on this screen comes from", '<p class="muted">Loading...</p>');
      try {
        const status = await RM.api.systemStatus();
        const feeds = status.feeds || {};
        const rows = Object.keys(feeds)
          .map((key) => {
            const feed = feeds[key];
            const tone =
              feed.provenance === "live" ? "ok"
              : feed.provenance === "cached" ? "warn"
              : feed.provenance === "unavailable" ? "crit" : "soft";
            return (
              '<div style="display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--line-soft)">' +
              "<div><b>" + RM.esc(key) + "</b><div class='muted small'>" + RM.esc(feed.detail || "") + "</div></div>" +
              '<div style="text-align:right"><span class="pill ' + tone + '">' +
              RM.esc(feed.provenance) + "</span><div class='muted small'>" +
              RM.esc(RM.timeAgo(feed.checked_at)) + "</div></div></div>"
            );
          })
          .join("");

        RM.setHTML(
          RM.$("#drawer-body"),
          '<div class="callout plain">RouteMind pulls from keyless public APIs. When a feed cannot be reached the server falls back to a bundled snapshot and says so here, rather than silently inventing numbers.</div>' +
            '<div class="section-title">Feeds</div>' + rows +
            '<div class="section-title">Traffic</div>' +
            '<div class="callout ' + (status.traffic_mode === "live-flow" ? "" : "warn") + '">' +
            RM.esc(status.traffic_notice || "") + "</div>" +
            '<div class="section-title">Refreshed</div>' +
            '<dl class="dl"><dt>Last refresh</dt><dd>' + RM.esc(RM.timeAgo(status.last_refresh)) + "</dd>" +
            "<dt>Server time</dt><dd>" + RM.esc(RM.clockTime(status.server_time)) + "</dd>" +
            "<dt>Offline mode</dt><dd>" + (status.offline_mode ? "on" : "off") + "</dd></dl>"
        );
      } catch (err) {
        RM.setHTML(RM.$("#drawer-body"), '<div class="callout crit">' + RM.esc(err.message) + "</div>");
      }
    },
  };

  document.addEventListener("DOMContentLoaded", () => RM.app.init());
})();
