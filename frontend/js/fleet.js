/* ==========================================================================
   RouteMind AI - fleet view
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  RM.fleet = {
    query: "",

    render() {
      const body = RM.$("#fleet-table tbody");
      if (!body) return;

      const term = this.query.trim().toLowerCase();
      const rows = (RM.state.vehicles || []).filter((vehicle) => {
        if (!term) return true;
        return [
          vehicle.id, vehicle.plate, vehicle.driver, vehicle.cargo,
          vehicle.destination, vehicle.corridor_name, vehicle.type,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(term);
      });

      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="8">' + RM.empty("No vehicles match that search") + "</td></tr>";
        return;
      }

      body.innerHTML = rows
        .map((vehicle) => {
          const halted = vehicle.status === "halted";
          const riskColor = RM.bandColor(
            vehicle.risk_probability >= 0.7 ? "critical"
            : vehicle.risk_probability >= 0.45 ? "high"
            : vehicle.risk_probability >= 0.22 ? "moderate" : "low"
          );

          return (
            '<tr class="clickable' + (halted ? " is-flagged" : "") + '" data-vehicle="' +
            RM.esc(vehicle.id) + '">' +
            "<td><div class='cell-main'>" + RM.esc(vehicle.id) +
            (vehicle.simulated_entity ? ' <span class="pill sim">Sim</span>' : "") + "</div>" +
            "<div class='cell-sub'>" + RM.esc(vehicle.plate || "") + " - " + RM.esc(vehicle.driver || "") + "</div></td>" +
            "<td><div>" + RM.esc(vehicle.cargo || "") + "</div>" +
            "<div class='cell-sub'>" + RM.esc(vehicle.payload_t || "-") + " t" +
            (vehicle.cold_chain ? " - cold chain" : "") + "</div></td>" +
            '<td><span class="pill ' + RM.priorityClass(vehicle.priority) + '">' +
            RM.esc(RM.fmt.title(vehicle.priority)) + "</span></td>" +
            "<td>" +
            (halted
              ? '<span class="pill crit">Halted</span>'
              : vehicle.rerouted
              ? '<span class="pill accent">Rerouted</span>'
              : '<span class="pill ok">Moving</span>') +
            (vehicle.halt_reason ? "<div class='cell-sub'>" + RM.esc(vehicle.halt_reason) + "</div>" : "") +
            "</td>" +
            "<td><div>" + RM.esc(vehicle.corridor_name || "-") + "</div>" +
            "<div class='cell-sub'>to " + RM.esc(vehicle.destination || "") + "</div></td>" +
            '<td class="num"><span style="color:' + riskColor + ';font-weight:600">' +
            RM.fmt.pct(vehicle.risk_probability) + "</span></td>" +
            '<td class="num">' + RM.esc(RM.fmt.mins(vehicle.eta_min)) + "</td>" +
            '<td><button class="btn tiny ghost" data-plan="' + RM.esc(vehicle.id) + '">Plan</button></td>' +
            "</tr>"
          );
        })
        .join("");

      RM.$$("#fleet-table tbody tr[data-vehicle]").forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest("[data-plan]")) return;
          this.openDrawer(row.dataset.vehicle);
        });
      });

      RM.$$("#fleet-table [data-plan]").forEach((btn) => {
        btn.addEventListener("click", (event) => {
          event.stopPropagation();
          RM.routes.planFor(btn.dataset.plan);
        });
      });
    },

    setQuery(value) {
      this.query = value || "";
      this.render();
    },

    async openDrawer(vehicleId) {
      const cached = RM.byId(RM.state.vehicles, vehicleId);
      RM.openDrawer(
        vehicleId,
        cached ? cached.cargo + " - " + cached.origin + " to " + cached.destination : "",
        '<p class="muted">Loading vehicle...</p>'
      );

      try {
        const vehicle = await RM.api.vehicle(vehicleId);
        const risky = (vehicle.risk_probability || 0) >= 0.45;

        if (RM.map && vehicle.lng) {
          RM.map.focus(vehicle.lng, vehicle.lat, Math.max(RM.map.zoom, 7.5));
          if (vehicle.route_geometry && vehicle.route_geometry.length > 1) {
            RM.map.setRoutes([
              { geometry: vehicle.route_geometry, color: RM.color.road.selected, selected: true },
            ]);
          }
        }

        RM.setHTML(
          RM.$("#drawer-body"),
          (vehicle.halt_reason
            ? '<div class="callout crit">Halted: ' + RM.esc(vehicle.halt_reason) + "</div>"
            : risky
            ? '<div class="callout warn">Travelling on ' + RM.esc(vehicle.corridor_name) +
              " which is scored at " + RM.fmt.pct(vehicle.risk_probability) + " disruption risk.</div>"
            : '<div class="callout plain">On schedule with no elevated road risk on the current corridor.</div>') +
            '<div class="section-title">Consignment</div>' +
            '<dl class="dl">' +
            "<dt>Cargo</dt><dd>" + RM.esc(vehicle.cargo || "-") + "</dd>" +
            "<dt>Priority</dt><dd>" + RM.esc(RM.fmt.title(vehicle.priority)) + "</dd>" +
            "<dt>Payload</dt><dd>" + RM.esc(vehicle.payload_t) + " t" +
            (vehicle.cold_chain ? " (cold chain)" : "") + "</dd>" +
            "<dt>Delivery</dt><dd>" + RM.esc(vehicle.delivery_id || "-") + "</dd>" +
            "</dl>" +
            '<div class="section-title">Movement</div>' +
            '<dl class="dl">' +
            "<dt>Status</dt><dd>" + RM.esc(RM.fmt.title(vehicle.status)) + "</dd>" +
            "<dt>Speed</dt><dd>" + RM.esc(Math.round(vehicle.speed_kmh || 0)) + " km/h</dd>" +
            "<dt>Progress</dt><dd>" + RM.fmt.pct(vehicle.progress) + " of leg</dd>" +
            "<dt>ETA</dt><dd>" + RM.esc(RM.fmt.mins(vehicle.eta_min)) + "</dd>" +
            "<dt>Corridor</dt><dd>" + RM.esc(vehicle.corridor_name || "-") + "</dd>" +
            "<dt>Route</dt><dd>" + RM.esc(vehicle.route_label || "Primary corridor") + "</dd>" +
            "</dl>" +
            '<div class="section-title">Driver</div>' +
            '<dl class="dl">' +
            "<dt>Name</dt><dd>" + RM.esc(vehicle.driver || "-") + "</dd>" +
            "<dt>Contact</dt><dd>" + RM.esc(vehicle.phone || "-") + "</dd>" +
            "<dt>Vehicle</dt><dd>" + RM.esc(vehicle.plate || "-") + " - " + RM.esc(vehicle.type || "") + "</dd>" +
            "</dl>" +
            '<button class="btn primary wide" style="margin-top:18px" id="drawer-plan">Plan risk-aware routes</button>'
        );

        const planBtn = RM.$("#drawer-plan");
        if (planBtn) {
          planBtn.addEventListener("click", () => {
            RM.closeDrawer();
            RM.routes.planFor(vehicle.id);
          });
        }
      } catch (err) {
        RM.setHTML(RM.$("#drawer-body"), '<div class="callout crit">' + RM.esc(err.message) + "</div>");
      }
    },
  };
})();
