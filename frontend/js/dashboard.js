/* ==========================================================================
   RouteMind AI - control room view
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  const SOURCE_LABEL = {
    live: "Live feeds",
    "live-flow": "Live traffic flow",
    cached: "Cached feed data",
    "offline-snapshot": "Bundled snapshot",
    modeled: "Modelled",
    unavailable: "Unavailable",
    mixed: "Partly live",
  };

  /* Feed keys are technical (osrm-geometry, osrm-route, open-meteo). Several of
     them collapse to the same human name, so map them explicitly and de-dupe. */
  const FEED_LABEL = {
    "open-meteo": "Weather",
    "open-meteo-elevation": "Terrain",
    usgs: "Seismic",
    "osrm-geometry": "Roads",
    "osrm-route": "Roads",
    osrm: "Roads",
    tomtom: "Traffic",
  };

  RM.dashboard = {
    render() {
      const overview = RM.state.overview;
      if (!overview) return;
      this.kpis(overview.metrics || {});
      this.attention(overview.attention || []);
      this.topRisks(overview.top_risks || []);
      RM.charts.rainfall(RM.$("#rain-chart"), overview.rainfall_series || []);
      RM.charts.distribution(RM.$("#risk-dist"), overview.risk_distribution || {});
      this.history(overview.reroute_history || []);
      this.provenance(overview.provenance || {});
      this.legend();
    },

    /* -------------------------------- KPIs -------------------------------- */

    kpis(m) {
      const host = RM.$("#kpi-row");
      if (!host) return;

      const cards = [
        {
          label: "Vehicles moving",
          value: (m.active_vehicles || 0) + " / " + (m.total_vehicles || 0),
          foot: (m.halted_vehicles || 0) + " halted",
          tone: m.halted_vehicles ? "warn" : "ok",
          icon: "truck",
        },
        {
          label: "Deliveries at risk",
          value: String(m.deliveries_at_risk || 0),
          foot: "of " + (m.active_deliveries || 0) + " active",
          tone: m.deliveries_at_risk ? "crit" : "ok",
          icon: "box",
        },
        {
          label: "On-time outlook",
          value: (m.on_time_pct === null || m.on_time_pct === undefined ? "-" : m.on_time_pct + "%"),
          foot: "deliveries inside SLA",
          tone: (m.on_time_pct || 0) >= 80 ? "ok" : (m.on_time_pct || 0) >= 60 ? "warn" : "crit",
          icon: "clock",
        },
        {
          label: "Roads blocked",
          value: String(m.blocked_roads || 0),
          foot: (m.at_risk_roads || 0) + " at risk, " + (m.operational_roads || 0) + " clear",
          tone: m.blocked_roads ? "crit" : "ok",
          icon: "road",
        },
        {
          label: "Mean network risk",
          value: RM.fmt.pct(m.avg_risk),
          foot: "24h disruption probability",
          tone: "accent",
          icon: "gauge",
        },
        {
          label: "Open alerts",
          value: String((m.alerts && m.alerts.unread) || 0),
          foot: ((m.alerts && m.alerts.critical) || 0) + " critical",
          tone: (m.alerts && m.alerts.critical) ? "crit" : "ok",
          icon: "bell",
        },
      ];

      host.innerHTML = cards
        .map(
          (card) =>
            '<div class="kpi ' + card.tone + '">' +
            '<div class="kpi-label">' + RM.esc(card.label) + "</div>" +
            '<div class="kpi-value">' + RM.esc(card.value) + "</div>" +
            '<div class="kpi-foot">' + RM.esc(card.foot) + "</div>" +
            "</div>"
        )
        .join("");
    },

    /* ---------------------------- needs attention -------------------------- */

    attention(items) {
      const host = RM.$("#attention-list");
      if (!host) return;

      if (!items.length) {
        host.innerHTML = RM.empty("Nothing needs attention right now");
        return;
      }

      host.innerHTML = items
        .slice(0, 6)
        .map((item) => {
          const tone =
            item.priority === "critical" ? "critical"
            : item.status === "at-risk" ? "warning"
            : "info";
          const note =
            item.risk_note ||
            (item.origin ? item.origin + " to " + item.destination : "");
          const delay = item.delay_min
            ? "+" + RM.fmt.mins(item.delay_min) + " delay"
            : item.eta_min
            ? "ETA " + RM.fmt.mins(item.eta_min)
            : "";

          return (
            '<div class="attn-item" data-delivery="' + RM.esc(item.id) + '">' +
            '<span class="attn-bar ' + tone + '"></span>' +
            "<div>" +
            '<div class="attn-title">' + RM.esc(item.cargo || item.id) +
            (item.priority === "critical" ? ' <span class="pill crit">Critical</span>' : "") +
            (item.simulated_entity ? ' <span class="pill sim">Sim</span>' : "") +
            "</div>" +
            '<div class="attn-body">' + RM.esc(note) + "</div>" +
            '<div class="attn-time">' + RM.esc(item.id) +
            (delay ? " - " + RM.esc(delay) : "") + "</div>" +
            "</div></div>"
          );
        })
        .join("");

      RM.$$("#attention-list .attn-item").forEach((node) => {
        node.addEventListener("click", () => {
          const delivery = RM.byId(RM.state.deliveries, node.dataset.delivery);
          if (delivery) RM.deliveries.openDrawer(delivery);
          else RM.app.go("deliveries");
        });
      });
    },

    /* --------------------------- top risk corridors ------------------------ */

    topRisks(items) {
      const host = RM.$("#top-risk-list");
      if (!host) return;

      if (!items.length) {
        host.innerHTML = RM.empty("No corridors scored yet");
        return;
      }

      host.innerHTML = items
        .slice(0, 5)
        .map((item) => {
          const color = RM.bandColor(item.band);
          return (
            '<div class="risk-row" data-corridor="' + RM.esc(item.corridor_id) + '">' +
            '<div class="risk-row-top">' +
            '<span class="risk-name">' + RM.esc(item.name) + "</span>" +
            '<span class="risk-pct" style="color:' + color + '">' +
            RM.fmt.pct(item.probability) + "</span></div>" +
            '<div class="risk-meter"><i style="width:' +
            Math.round((item.probability || 0) * 100) + "%;background:" + color + '"></i></div>' +
            '<div class="risk-note">' + RM.esc(item.headline || "") + "</div>" +
            "</div>"
          );
        })
        .join("");

      RM.$$("#top-risk-list .risk-row").forEach((node) => {
        node.addEventListener("click", () => RM.risk.openCorridor(node.dataset.corridor));
      });
    },

    /* ----------------------------- reroute log ----------------------------- */

    history(rows) {
      const host = RM.$("#reroute-history");
      if (!host) return;

      if (!rows.length) {
        host.innerHTML =
          '<p class="muted small">No reroutes accepted yet. Run a disruption drill to see the decision trail.</p>';
        return;
      }

      host.innerHTML =
        '<h3 class="sub" style="margin-bottom:6px">Reroute decisions</h3>' +
        rows
          .slice(0, 5)
          .map(
            (row) =>
              '<div class="history-row"><b>' +
              RM.esc(row.vehicle_id || row.vehicle || "Vehicle") + "</b><span>" +
              RM.esc(row.route_label || row.label || "rerouted") + "</span><span>" +
              RM.esc(RM.timeAgo(row.at || row.timestamp || row.accepted_at)) + "</span></div>"
          )
          .join("");
    },

    /* ------------------------- feed / provenance card ---------------------- */

    provenance(prov) {
      const dot = RM.$("#feed-dot");
      const title = RM.$("#feed-title");
      const sub = RM.$("#feed-sub");
      const pill = RM.$("#live-pill");
      const label = RM.$("#live-label");
      const badge = RM.$("#map-badge");
      const rainSource = RM.$("#rain-source");
      const rainNote = RM.$("#rain-note");

      const sources = prov.sources || {};
      const overall = sources.overall || "unavailable";
      const live = overall === "live" || overall === "mixed";

      if (dot) dot.className = "dot " + (overall === "live" ? "live" : live ? "partial" : "offline");
      if (title) title.textContent = SOURCE_LABEL[overall] || RM.fmt.title(overall);

      const feeds = prov.feeds || {};
      const names = Object.keys(feeds);
      if (sub) {
        const state = {};
        const order = [];
        names.forEach((key) => {
          const name = FEED_LABEL[key] || FEED_LABEL[key.split("-")[0]] || key;
          const value = feeds[key].provenance;
          if (!(name in state)) order.push(name);
          // when two feeds share a name, report the weaker of the two states
          if (!(name in state) || value === "unavailable") state[name] = value;
        });
        sub.textContent = order.length
          ? order
              .map((name) => name + ": " + (SOURCE_LABEL[state[name]] || state[name]))
              .join(" - ")
          : "No feed information";
      }

      if (pill && label) {
        pill.className = "live-pill" + (overall === "live" ? "" : live ? " stale" : " off");
        label.textContent =
          overall === "live" ? "Live" : overall === "mixed" ? "Partly live" : "Offline data";
      }

      if (rainSource) {
        rainSource.textContent =
          (sources.weather === "live" ? "Open-Meteo live" : SOURCE_LABEL[sources.weather] || "Open-Meteo");
      }
      if (rainNote) {
        rainNote.textContent =
          sources.weather === "live"
            ? "Hourly precipitation pulled from the Open-Meteo forecast API for each corridor midpoint. Rainfall carries the largest weight in the risk score."
            : "Live weather could not be reached, so a bundled forecast snapshot is being used. Risk scoring is unchanged.";
      }

      if (badge) {
        const notes = [];
        if (prov.offline_mode) notes.push("Offline mode: bundled snapshot data.");
        else if (!live) notes.push("Live feeds unreachable - using the bundled snapshot.");
        if (prov.traffic_mode === "modeled" && prov.traffic_notice) notes.push(prov.traffic_notice);
        if (RM.state.tilesDown) notes.push("Basemap tiles unavailable - road network still plotted from live geometry.");

        if (notes.length) {
          badge.hidden = false;
          badge.textContent = notes.join(" ");
        } else {
          badge.hidden = true;
        }
      }
    },

    /* -------------------------------- legend ------------------------------- */

    legend() {
      const host = RM.$("#map-legend");
      if (!host) return;
      const mode = RM.state.mapMode;

      const roadRows =
        mode === "traffic"
          ? [
              ["Free flowing", RM.trafficColor("free")],
              ["Moderate", RM.trafficColor("moderate")],
              ["Heavy", RM.trafficColor("heavy")],
              ["Severe", RM.trafficColor("severe")],
            ]
          : [
              ["Operational", RM.color.road.operational],
              ["Elevated risk", RM.color.road["at-risk"]],
              ["Critical risk", RM.color.crit],
            ];

      let out = roadRows
        .map(
          (row) =>
            '<div class="legend-row"><span class="legend-swatch" style="background:' +
            row[1] + '"></span>' + RM.esc(row[0]) + "</div>"
        )
        .join("");

      out +=
        '<div class="legend-row"><span class="legend-swatch" style="background:repeating-linear-gradient(90deg,' +
        RM.color.crit + ' 0 5px,transparent 5px 9px)"></span>Blocked</div>';
      out +=
        '<div class="legend-row"><span class="legend-dot" style="background:' +
        RM.color.accent + '"></span>Critical cargo</div>' +
        '<div class="legend-row"><span class="legend-dot" style="background:' +
        RM.color.crit + ';border-radius:2px;transform:rotate(45deg)"></span>Incident</div>';

      host.innerHTML = out;
    },

    /* ------------------------------ model card ----------------------------- */

    async modelCard() {
      RM.openDrawer("Model card", "How RouteMind scores disruption risk", '<p class="muted">Loading...</p>');
      try {
        const card = await RM.api.modelCard();
        const weights = card.weights || card.feature_weights || {};
        const rows = Object.keys(weights)
          .sort((a, b) => weights[b] - weights[a])
          .map(
            (key) =>
              '<div class="factor"><div class="factor-top"><span class="factor-name">' +
              RM.esc(RM.fmt.title(key)) + '</span><span class="factor-val">' +
              Math.round(weights[key] * 100) + '%</span></div>' +
              '<div class="factor-bar"><i style="width:' +
              Math.round((weights[key] / Math.max.apply(null, Object.values(weights))) * 100) +
              '%"></i></div></div>'
          )
          .join("");

        const limitations = (card.limitations || []).map((x) => "<li>" + RM.esc(x) + "</li>").join("");
        const evaluation = (card.evaluation_plan || card.evaluation || []).map(
          (x) => "<li>" + RM.esc(typeof x === "string" ? x : JSON.stringify(x)) + "</li>"
        ).join("");

        RM.setHTML(
          RM.$("#drawer-body"),
          '<div class="callout warn">' +
            RM.esc(card.honest_statement || "This is not a trained ML model.") +
            "</div>" +
            '<div class="section-title">Identity</div>' +
            '<dl class="dl">' +
            "<dt>Model</dt><dd>" + RM.esc(card.name || card.model || "heuristic-v1") + "</dd>" +
            "<dt>Version</dt><dd>" + RM.esc(card.version || "1") + "</dd>" +
            "<dt>Type</dt><dd>" + RM.esc(card.model_kind || card.kind || "") + "</dd>" +
            "<dt>Output</dt><dd>" + RM.esc(card.output || "24h disruption probability per corridor") + "</dd>" +
            "</dl>" +
            (rows ? '<div class="section-title">Feature weights</div>' + rows : "") +
            (card.inputs
              ? '<div class="section-title">Inputs</div><ul class="muted" style="padding-left:18px;margin:0">' +
                (Array.isArray(card.inputs) ? card.inputs : Object.keys(card.inputs))
                  .map((x) => "<li>" + RM.esc(typeof x === "string" ? x : JSON.stringify(x)) + "</li>")
                  .join("") +
                "</ul>"
              : "") +
            (limitations
              ? '<div class="section-title">Limitations</div><ul class="muted" style="padding-left:18px;margin:0">' +
                limitations + "</ul>"
              : "") +
            (evaluation
              ? '<div class="section-title">How this would be evaluated</div><ul class="muted" style="padding-left:18px;margin:0">' +
                evaluation + "</ul>"
              : "")
        );
      } catch (err) {
        RM.setHTML(RM.$("#drawer-body"), '<div class="callout crit">' + RM.esc(err.message) + "</div>");
      }
    },
  };
})();
