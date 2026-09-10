/* ==========================================================================
   RouteMind AI - deliveries view
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  RM.deliveries = {
    filter: "all",

    render() {
      const body = RM.$("#delivery-table tbody");
      if (!body) return;

      const rows = (RM.state.deliveries || []).filter((delivery) => {
        if (this.filter === "at-risk") return delivery.status === "at-risk" || delivery.status === "delayed";
        if (this.filter === "critical") return delivery.priority === "critical";
        return true;
      });

      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="7">' + RM.empty("No deliveries match this filter") + "</td></tr>";
        return;
      }

      const order = { "at-risk": 0, delayed: 1, rerouted: 2, "on-track": 3, delivered: 4 };
      rows.sort((a, b) => {
        const pa = a.priority === "critical" ? 0 : 1;
        const pb = b.priority === "critical" ? 0 : 1;
        if (pa !== pb) return pa - pb;
        return (order[a.status] || 9) - (order[b.status] || 9);
      });

      body.innerHTML = rows
        .map((delivery) => {
          const reliability = delivery.reliability;
          const relColor =
            reliability >= 0.8 ? RM.color.ok : reliability >= 0.5 ? RM.color.warn : RM.color.crit;

          return (
            '<tr class="clickable' +
            (delivery.status === "at-risk" || delivery.status === "delayed" ? " is-flagged" : "") +
            '" data-delivery="' + RM.esc(delivery.id) + '">' +
            "<td><div class='cell-main'>" + RM.esc(delivery.cargo) +
            (delivery.simulated_entity ? ' <span class="pill sim">Sim</span>' : "") + "</div>" +
            "<div class='cell-sub'>" + RM.esc(delivery.id) + " - " + RM.esc(delivery.units || "") + "</div></td>" +
            "<td><div>" + RM.esc(delivery.origin) + " to " + RM.esc(delivery.destination) + "</div>" +
            "<div class='cell-sub'>" + RM.esc(delivery.corridor_name || "") +
            (delivery.rerouted ? " - rerouted" : "") + "</div></td>" +
            '<td><span class="pill ' + RM.priorityClass(delivery.priority) + '">' +
            RM.esc(RM.fmt.title(delivery.priority)) + "</span></td>" +
            "<td>" + this.statusPill(delivery.status) +
            (delivery.risk_note ? "<div class='cell-sub'>" + RM.esc(delivery.risk_note) + "</div>" : "") +
            "</td>" +
            '<td class="num"><span style="color:' + relColor + ';font-weight:600">' +
            RM.fmt.pct(reliability) + "</span> " + RM.meter(reliability || 0, relColor) + "</td>" +
            '<td class="num">' + RM.esc(RM.fmt.mins(delivery.eta_min)) +
            "<div class='cell-sub'>SLA " + RM.esc(delivery.sla_hours) + "h</div></td>" +
            '<td class="num">' +
            (delivery.delay_min
              ? '<span style="color:' + RM.color.crit + ';font-weight:600">+' +
                RM.esc(RM.fmt.mins(delivery.delay_min)) + "</span>"
              : '<span class="muted">on time</span>') +
            "</td></tr>"
          );
        })
        .join("");

      RM.$$("#delivery-table tbody tr[data-delivery]").forEach((row) => {
        row.addEventListener("click", () => {
          const delivery = RM.byId(RM.state.deliveries, row.dataset.delivery);
          if (delivery) this.openDrawer(delivery);
        });
      });
    },

    statusPill(status) {
      switch (status) {
        case "at-risk": return '<span class="pill crit">At risk</span>';
        case "delayed": return '<span class="pill warn">Delayed</span>';
        case "rerouted": return '<span class="pill accent">Rerouted</span>';
        case "delivered": return '<span class="pill ok">Delivered</span>';
        default: return '<span class="pill ok">On track</span>';
      }
    },

    setFilter(filter) {
      this.filter = filter;
      this.render();
    },

    openDrawer(delivery) {
      const vehicle = RM.byId(RM.state.vehicles, delivery.vehicle_id);
      const late = (delivery.delay_min || 0) > 0;

      RM.openDrawer(
        delivery.cargo,
        delivery.id + " - " + delivery.origin + " to " + delivery.destination,
        (delivery.risk_note
          ? '<div class="callout ' + (delivery.status === "at-risk" ? "crit" : "warn") + '">' +
            RM.esc(delivery.risk_note) + "</div>"
          : '<div class="callout plain">Running to plan with no elevated risk flagged.</div>') +
          '<div class="section-title">Consignment</div>' +
          '<dl class="dl">' +
          "<dt>Contents</dt><dd>" + RM.esc(delivery.cargo) + "</dd>" +
          "<dt>Quantity</dt><dd>" + RM.esc(delivery.units || "-") + "</dd>" +
          "<dt>Consignee</dt><dd>" + RM.esc(delivery.consignee || "-") + "</dd>" +
          "<dt>Priority</dt><dd>" + RM.esc(RM.fmt.title(delivery.priority)) + "</dd>" +
          "<dt>SLA</dt><dd>" + RM.esc(delivery.sla_hours) + " hours</dd>" +
          "</dl>" +
          '<div class="section-title">Execution</div>' +
          '<dl class="dl">' +
          "<dt>Status</dt><dd>" + RM.esc(RM.fmt.title(delivery.status)) + "</dd>" +
          "<dt>Vehicle</dt><dd>" + RM.esc(delivery.vehicle_id || "-") +
          (vehicle ? " (" + RM.esc(vehicle.driver) + ")" : "") + "</dd>" +
          "<dt>Corridor</dt><dd>" + RM.esc(delivery.corridor_name || "-") + "</dd>" +
          "<dt>Road risk</dt><dd>" + RM.fmt.pct(delivery.risk_probability) + "</dd>" +
          "<dt>Reliability</dt><dd>" + RM.fmt.pct(delivery.reliability) + " chance of arriving inside SLA</dd>" +
          "<dt>ETA</dt><dd>" + RM.esc(RM.fmt.mins(delivery.eta_min)) + "</dd>" +
          (late ? "<dt>Delay</dt><dd>+" + RM.esc(RM.fmt.mins(delivery.delay_min)) + "</dd>" : "") +
          (delivery.route_label ? "<dt>Route</dt><dd>" + RM.esc(delivery.route_label) + "</dd>" : "") +
          "</dl>" +
          (delivery.vehicle_id
            ? '<button class="btn primary wide" style="margin-top:18px" id="drawer-plan-delivery">Plan alternative routes</button>'
            : "")
      );

      const btn = RM.$("#drawer-plan-delivery");
      if (btn) {
        btn.addEventListener("click", () => {
          RM.closeDrawer();
          RM.routes.planFor(delivery.vehicle_id);
        });
      }
    },
  };
})();
