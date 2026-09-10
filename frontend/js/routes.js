/* ==========================================================================
   RouteMind AI - risk-aware route planner
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  const SOURCE_TEXT = {
    osrm: "Road geometry from OSRM / OpenStreetMap",
    "corridor-graph": "Built from the corridor network graph",
    "modeled-bypass": "Modelled diversion alignment - indicative, not a surveyed road",
  };

  RM.routes = {
    map: null,
    options: [],
    selectedId: null,
    vehicleId: null,

    fillVehicles() {
      const select = RM.$("#plan-vehicle");
      if (!select) return;
      const previous = select.value;
      const vehicles = RM.state.vehicles || [];
      select.innerHTML = vehicles
        .map(
          (vehicle) =>
            '<option value="' + RM.esc(vehicle.id) + '">' +
            RM.esc(vehicle.id + " - " + vehicle.cargo + " to " + vehicle.destination) +
            "</option>"
        )
        .join("");
      if (previous && vehicles.some((v) => v.id === previous)) select.value = previous;
      else if (this.vehicleId) select.value = this.vehicleId;
    },

    ensureMap() {
      if (!this.map) {
        const host = RM.$("#plan-map");
        if (!host) return;
        this.map = new RM.MapView(host, { center: [92.9, 25.4], zoom: 6.6 });
        this.map.setLayer("depots", false);
      }
      this.paint();
    },

    planFor(vehicleId) {
      this.vehicleId = vehicleId;
      RM.app.go("routes");
      const select = RM.$("#plan-vehicle");
      if (select) select.value = vehicleId;
      this.plan();
    },

    async plan() {
      const select = RM.$("#plan-vehicle");
      const host = RM.$("#plan-options");
      const vehicleId = (select && select.value) || this.vehicleId;
      if (!vehicleId || !host) return;

      this.vehicleId = vehicleId;
      host.innerHTML = '<p class="muted" style="padding:8px 2px">Scoring route options against live risk...</p>';

      try {
        const result = await RM.api.planRoutes(vehicleId);
        this.options = result.options || [];
        const recommended = this.options.find((o) => o.recommended);
        this.selectedId = recommended ? recommended.id : (this.options[0] && this.options[0].id) || null;
        this.renderOptions(result);
        this.ensureMap();
      } catch (err) {
        host.innerHTML = '<div class="callout crit">' + RM.esc(err.message) + "</div>";
      }
    },

    renderOptions(result) {
      const host = RM.$("#plan-options");
      if (!host) return;

      if (!this.options.length) {
        host.innerHTML = RM.empty("No route options could be generated for this vehicle");
        return;
      }

      const vehicle = RM.byId(RM.state.vehicles, this.vehicleId);
      const header =
        '<div class="callout plain" style="margin-bottom:4px">' +
        "Options are ranked by a cost that combines travel time and disruption risk, weighted by cargo priority" +
        (result && result.priority ? " (<b>" + RM.esc(result.priority) + "</b> cargo)" : "") +
        ". " +
        (vehicle ? RM.esc(vehicle.cargo + " for " + vehicle.destination + ".") : "") +
        "</div>";

      host.innerHTML = header + this.options.map((option) => this.optionCard(option)).join("");

      RM.$$("#plan-options .opt").forEach((node) => {
        node.addEventListener("click", () => {
          if (node.classList.contains("is-blocked")) return;
          this.selectedId = node.dataset.option;
          this.renderOptions(result);
          this.paint();
        });
      });

      this.paint();
    },

    optionCard(option, compact) {
      const selected = option.id === this.selectedId;
      const tags = [];
      if (option.recommended) tags.push('<span class="pill accent">Recommended</span>');
      if (option.is_fastest && !option.blocked) tags.push('<span class="pill soft">Fastest</span>');
      if (option.is_safest && !option.blocked) tags.push('<span class="pill ok">Lowest risk</span>');
      if (option.blocked) tags.push('<span class="pill crit">Not viable</span>');

      const riskColor = RM.bandColor(option.risk_band);

      return (
        '<div class="opt' + (selected ? " is-selected" : "") + (option.blocked ? " is-blocked" : "") +
        '" data-option="' + RM.esc(option.id) + '">' +
        '<div class="opt-head"><span class="opt-label">' + RM.esc(option.label) + "</span>" +
        '<span class="opt-tags">' + tags.join("") + "</span></div>" +
        '<div class="opt-stats">' +
        '<div class="opt-stat"><b>' + RM.esc(RM.fmt.mins(option.duration_min)) + "</b><span>travel time</span></div>" +
        '<div class="opt-stat"><b>' + RM.esc(RM.fmt.km(option.distance_km)) + "</b><span>distance</span></div>" +
        '<div class="opt-stat"><b style="color:' + riskColor + '">' + RM.fmt.pct(option.risk_probability) +
        "</b><span>disruption risk</span></div>" +
        '<div class="opt-stat"><b>' + RM.fmt.pct(option.reliability) + "</b><span>reliability</span></div>" +
        (option.delay_vs_fastest_min
          ? '<div class="opt-stat"><b>+' + RM.esc(RM.fmt.mins(option.delay_vs_fastest_min)) + "</b><span>vs fastest</span></div>"
          : "") +
        "</div>" +
        (compact ? "" : '<div class="opt-why">' + RM.esc(option.explanation || "") + "</div>") +
        '<div class="opt-src">' +
        RM.esc(SOURCE_TEXT[option.source] || option.source || "") +
        (option.corridor_names && option.corridor_names.length
          ? " - via " + RM.esc(option.corridor_names.slice(0, 3).join(", "))
          : "") +
        "</div></div>"
      );
    },

    paint() {
      if (!this.map) return;
      this.map.setData({
        corridors: RM.state.corridors || [],
        incidents: (RM.state.incidents || []).filter((i) => i.blocks_road),
        vehicles: (RM.state.vehicles || []).filter((v) => v.id === this.vehicleId),
        cities: (RM.state.map && RM.state.map.cities) || [],
        depots: [],
      });

      const drawn = this.options
        .filter((option) => option.geometry && option.geometry.length > 1)
        .map((option) => ({
          geometry: option.geometry,
          color: option.blocked
            ? RM.color.crit
            : option.id === this.selectedId
            ? RM.color.road.selected
            : RM.color.road.alt,
          selected: option.id === this.selectedId,
          dashed: option.source === "modeled-bypass",
          dimmed: option.id !== this.selectedId,
        }));

      this.map.setRoutes(drawn);

      const selected = this.options.find((o) => o.id === this.selectedId);
      if (selected && selected.geometry && selected.geometry.length > 1) {
        this.map.fitTo(selected.geometry, 40);
      }
    },
  };
})();
