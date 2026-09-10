/* ==========================================================================
   RouteMind AI - disruption drill
   Inject a disruption, watch detection -> impact -> options -> decision.
   Phases: idle | awaiting-accept | completed
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  const SOURCE_TEXT = {
    osrm: "Road geometry from OSRM / OpenStreetMap",
    "corridor-graph": "Built from the corridor network graph",
    "modeled-bypass": "Modelled diversion alignment - indicative, not a surveyed road",
  };

  RM.simulation = {
    scenariosLoaded: false,
    scenariosLoading: false,
    selectedId: null,
    focused: false,

    /* ------------------------------ scenarios ------------------------------ */

    async fillScenarios() {
      if (this.scenariosLoaded || this.scenariosLoading) return;
      const select = RM.$("#sim-scenario");
      if (!select) return;

      this.scenariosLoading = true;
      try {
        const result = await RM.api.scenarios();
        const scenarios = result.scenarios || [];
        select.innerHTML = scenarios
          .map(
            (s) =>
              '<option value="' + RM.esc(s.id) + '">' + RM.esc(s.name || s.id) + "</option>"
          )
          .join("");
        this.scenariosLoaded = scenarios.length > 0;
      } catch (err) {
        /* the poll loop will retry */
      } finally {
        this.scenariosLoading = false;
      }
    },

    /* -------------------------------- actions ------------------------------ */

    async load() {
      try {
        RM.state.simulation = await RM.api.simulation();
        this.render();
        this.syncMap();
      } catch (err) {
        RM.toast(err.message, "err");
      }
    },

    async run(promise, message) {
      try {
        const state = await promise;
        RM.state.simulation = state;
        this.selectedId = state.selected_route_id || state.recommended_route_id || null;
        this.render();
        this.syncMap();
        if (message) RM.toast(message, "ok");
        await RM.app.refresh();
      } catch (err) {
        RM.toast(err.message, "err");
      }
    },

    start() {
      const select = RM.$("#sim-scenario");
      const scenarioId = select ? select.value : null;
      if (!scenarioId) {
        RM.toast("No scenario available yet", "err");
        return;
      }
      this.focused = false;
      this.run(RM.api.simStart(scenarioId), "Disruption injected");
    },

    accept() {
      const sim = RM.state.simulation || {};
      const routeId = this.selectedId || sim.recommended_route_id;
      if (!routeId) {
        RM.toast("No route selected", "err");
        return;
      }
      this.run(RM.api.simAccept(routeId), "Reroute accepted - vehicle redirected");
    },

    decline() {
      this.run(RM.api.simDecline(), "Reroute declined - vehicle holding");
    },

    reset() {
      this.focused = false;
      this.selectedId = null;
      if (RM.map) RM.map.setRoutes([]);
      this.run(RM.api.simReset(), "Drill reset");
    },

    /* ------------------------------- rendering ----------------------------- */

    render() {
      const sim = RM.state.simulation || {};
      this.renderSteps(sim);
      this.renderImpact(sim);
      this.renderLog(sim);
      this.renderOptions(sim);

      const decision = RM.$("#sim-decision");
      if (decision) decision.hidden = !sim.awaiting_decision;

      const startBtn = RM.$("#sim-start");
      if (startBtn) {
        startBtn.disabled = !!sim.is_active;
        startBtn.textContent = sim.is_active ? "Drill running" : "Start drill";
      }
    },

    renderSteps(sim) {
      const host = RM.$("#sim-steps");
      if (!host) return;
      const steps = sim.steps || [];

      if (!steps.length) {
        host.innerHTML =
          '<li class="step"><span class="step-dot"></span>' +
          '<span class="step-label">Pick a scenario and start the drill</span></li>';
        return;
      }

      host.innerHTML = steps
        .map(
          (step) =>
            '<li class="step ' + RM.esc(step.status) + '">' +
            '<span class="step-dot"></span>' +
            '<span class="step-label">' + RM.esc(step.label) + "</span></li>"
        )
        .join("");
    },

    renderImpact(sim) {
      const host = RM.$("#sim-impact");
      if (!host) return;

      if (!sim.is_active && sim.phase !== "completed") {
        host.innerHTML = RM.empty("Nothing disrupted. The network is running to plan.");
        return;
      }

      const rows = [];
      const incident = sim.incident;
      const vehicle = sim.vehicle;
      const delivery = sim.delivery;

      if (incident) {
        rows.push(
          this.impactRow(
            "\u25B2",
            "crit",
            incident.title,
            (incident.description || "") +
              (incident.blocks_road ? " Carriageway impassable." : "")
          )
        );
      }

      if (vehicle) {
        rows.push(
          this.impactRow(
            "\u25A0",
            vehicle.status === "halted" ? "crit" : vehicle.rerouted ? "ok" : "warn",
            vehicle.id + " - " + vehicle.cargo,
            (vehicle.halt_reason ||
              (vehicle.rerouted ? "Rerouted and moving on the accepted alternative." : "En route.")) +
              (vehicle.eta_min ? " ETA " + RM.fmt.mins(vehicle.eta_min) + "." : "") +
              (vehicle.driver ? " Driver " + vehicle.driver + "." : "")
          )
        );
      }

      if (delivery) {
        rows.push(
          this.impactRow(
            "\u25CF",
            delivery.status === "at-risk" ? "warn" : delivery.status === "delayed" ? "crit" : "ok",
            delivery.id + " - " + delivery.cargo + " for " + delivery.consignee,
            (delivery.risk_note || "") +
              (delivery.delay_min ? " Running " + RM.fmt.mins(delivery.delay_min) + " behind plan." : "") +
              " Reliability " + RM.fmt.pct(delivery.reliability) + "."
          )
        );
      }

      if (sim.phase === "completed") {
        rows.push(
          this.impactRow(
            "\u2713",
            "ok",
            "Reroute executed",
            "The vehicle is on the accepted alternative and the delivery clock has been recalculated."
          )
        );
      }

      host.innerHTML = rows.join("");
    },

    impactRow(glyph, tone, title, text) {
      return (
        '<div class="impact-row">' +
        '<div class="impact-icon ' + tone + '">' + glyph + "</div>" +
        '<div class="impact-text"><b>' + RM.esc(title) + "</b><span>" + RM.esc(text || "") + "</span></div>" +
        "</div>"
      );
    },

    renderLog(sim) {
      const host = RM.$("#sim-log");
      if (!host) return;
      const log = sim.log || [];
      if (!log.length) {
        host.innerHTML = "";
        return;
      }
      host.innerHTML = log
        .map(
          (entry) =>
            "<li><span class='mono'>" + RM.esc(RM.clockTime(entry.at)) + "</span> " +
            RM.esc(entry.message) + "</li>"
        )
        .join("");
      host.scrollTop = host.scrollHeight;
    },

    renderOptions(sim) {
      const host = RM.$("#sim-options");
      if (!host) return;

      const options = sim.route_options || [];
      if (!options.length) {
        host.innerHTML = RM.empty("Route options appear once a disruption is detected");
        return;
      }

      if (!this.selectedId) {
        this.selectedId = sim.selected_route_id || sim.recommended_route_id || options[0].id;
      }

      const accepted = sim.phase === "completed" ? sim.selected_route_id : null;

      host.innerHTML = options
        .map((option) => this.card(option, accepted))
        .join("");

      RM.$$("#sim-options .opt").forEach((node) => {
        node.addEventListener("click", () => {
          if (node.classList.contains("is-blocked")) return;
          if (!(RM.state.simulation || {}).awaiting_decision) return;
          this.selectedId = node.dataset.option;
          this.renderOptions(RM.state.simulation || {});
          this.syncMap();
        });
      });
    },

    card(option, acceptedId) {
      const selected = acceptedId ? option.id === acceptedId : option.id === this.selectedId;
      const tags = [];
      if (acceptedId && option.id === acceptedId) tags.push('<span class="pill ok">Accepted</span>');
      else if (option.recommended) tags.push('<span class="pill accent">Recommended</span>');
      if (option.is_fastest && !option.blocked) tags.push('<span class="pill soft">Fastest</span>');
      if (option.blocked) tags.push('<span class="pill crit">Not viable</span>');

      return (
        '<div class="opt' + (selected ? " is-selected" : "") + (option.blocked ? " is-blocked" : "") +
        '" data-option="' + RM.esc(option.id) + '">' +
        '<div class="opt-head"><span class="opt-label">' + RM.esc(option.label) + "</span>" +
        '<span class="opt-tags">' + tags.join("") + "</span></div>" +
        '<div class="opt-stats">' +
        '<div class="opt-stat"><b>' + RM.esc(RM.fmt.mins(option.duration_min)) + "</b><span>travel time</span></div>" +
        '<div class="opt-stat"><b>' + RM.esc(RM.fmt.km(option.distance_km)) + "</b><span>distance</span></div>" +
        '<div class="opt-stat"><b style="color:' + RM.bandColor(option.risk_band) + '">' +
        RM.fmt.pct(option.risk_probability) + "</b><span>disruption risk</span></div>" +
        '<div class="opt-stat"><b>' + RM.fmt.pct(option.reliability) + "</b><span>reliability</span></div>" +
        "</div>" +
        '<div class="opt-why">' + RM.esc(option.explanation || "") + "</div>" +
        '<div class="opt-src">' + RM.esc(SOURCE_TEXT[option.source] || option.source || "") + "</div>" +
        "</div>"
      );
    },

    /* --------------------------- map synchronisation ------------------------ */

    syncMap() {
      if (!RM.map) return;
      const sim = RM.state.simulation || {};

      if (!sim.is_active && sim.phase !== "completed") {
        RM.map.setRoutes([]);
        return;
      }

      const accepted = sim.phase === "completed" ? sim.selected_route_id : null;
      const active = accepted || this.selectedId || sim.recommended_route_id;

      const routes = (sim.route_options || [])
        .filter((option) => option.geometry && option.geometry.length > 1)
        .map((option) => ({
          geometry: option.geometry,
          color: option.blocked
            ? RM.color.crit
            : option.id === active
            ? RM.color.road.selected
            : RM.color.road.alt,
          selected: option.id === active,
          dashed: option.source === "modeled-bypass",
          dimmed: option.id !== active,
        }));

      RM.map.setRoutes(routes);

      if (!this.focused && sim.incident) {
        this.focused = true;
        RM.map.focus(sim.incident.lng, sim.incident.lat, 7.6);
      }
    },
  };
})();
