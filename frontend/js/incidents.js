/* ==========================================================================
   RouteMind AI - incident feed and field reporting
   Backend statuses: active | acknowledged | resolved
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  const GLYPH = {
    landslide: "\u25B2",
    flood: "\u2248",
    earthquake: "\u25C6",
    roadwork: "\u25AE",
    accident: "\u2715",
    protest: "\u25CF",
    roadblock: "\u2716",
    weather: "\u2601",
  };

  const TYPE_LABEL = {
    landslide: "Landslide",
    flood: "Flooding",
    earthquake: "Seismic event",
    roadwork: "Roadwork",
    accident: "Accident",
    protest: "Blockade",
    roadblock: "Road closure",
    weather: "Weather hazard",
  };

  RM.incidents = {
    filter: "all",

    setFilter(value) {
      this.filter = value || "all";
      this.render();
    },

    visible() {
      const all = RM.state.incidents || [];
      switch (this.filter) {
        case "blocking":
          return all.filter((i) => i.blocks_road);
        case "unverified":
          return all.filter((i) => !i.verified);
        case "predicted":
          return all.filter((i) => i.source === "risk-model" || i.source === "open-meteo-derived");
        case "field":
          return all.filter((i) => i.source === "field-report");
        default:
          return all;
      }
    },

    render() {
      const host = RM.$("#incident-list");
      if (!host) return;

      const rank = { critical: 0, high: 1, severe: 1, moderate: 2, minor: 3, low: 3 };
      const items = this.visible().slice().sort((a, b) => {
        if (!!b.blocks_road !== !!a.blocks_road) return b.blocks_road ? 1 : -1;
        const ra = rank[a.severity] === undefined ? 4 : rank[a.severity];
        const rb = rank[b.severity] === undefined ? 4 : rank[b.severity];
        if (ra !== rb) return ra - rb;
        return (b.reported_at || 0) - (a.reported_at || 0);
      });

      if (!items.length) {
        host.innerHTML = RM.empty("No incidents match this filter");
        return;
      }

      host.innerHTML = items.map((incident) => this.card(incident)).join("");

      RM.$$("#incident-list .inc-item").forEach((node) => {
        node.addEventListener("click", (event) => {
          if (event.target.closest("button")) return;
          const found = (RM.state.incidents || []).find((i) => i.id === node.dataset.id);
          if (found) this.openDrawer(found);
        });
      });

      RM.$$("#incident-list [data-status]").forEach((btn) => {
        btn.addEventListener("click", () => this.setStatus(btn.dataset.id, btn.dataset.status));
      });
      RM.$$("#incident-list [data-locate]").forEach((btn) => {
        btn.addEventListener("click", () => this.locate(btn.dataset.locate));
      });
    },

    card(incident) {
      const tone = RM.severityClass(incident.severity);
      const buttons = [];
      if (incident.status === "active") {
        buttons.push(
          '<button class="btn tiny ghost" data-status="acknowledged" data-id="' +
            RM.esc(incident.id) + '">Acknowledge</button>'
        );
      }
      if (incident.status !== "resolved") {
        buttons.push(
          '<button class="btn tiny ghost" data-status="resolved" data-id="' +
            RM.esc(incident.id) + '">Resolve</button>'
        );
      }
      buttons.push(
        '<button class="btn tiny ghost" data-locate="' + RM.esc(incident.id) + '">Locate</button>'
      );

      return (
        '<div class="inc-item' + (incident.blocks_road ? " is-flagged" : "") +
        '" data-id="' + RM.esc(incident.id) + '">' +
        '<div class="inc-icon ' + tone + '">' + (GLYPH[incident.type] || "\u25CF") + "</div>" +
        '<div class="inc-main">' +
        '<div class="inc-title">' + RM.esc(incident.title) +
        (incident.blocks_road ? '<span class="pill crit">Road blocked</span>' : "") +
        (incident.verified
          ? '<span class="pill ok">Verified</span>'
          : '<span class="pill warn">Unverified</span>') +
        (incident.status !== "active"
          ? '<span class="pill soft">' + RM.esc(RM.fmt.title(incident.status)) + "</span>"
          : "") +
        "</div>" +
        '<div class="inc-desc">' + RM.esc(incident.description || "") + "</div>" +
        '<div class="inc-meta">' + RM.esc(incident.source_label || incident.source) +
        " - " + RM.esc(RM.timeAgo(incident.reported_at)) +
        (incident.corridor_id ? " - " + RM.esc(incident.corridor_id) : "") +
        "</div></div>" +
        '<div class="inc-actions">' + buttons.join("") + "</div>" +
        "</div>"
      );
    },

    locate(id) {
      const incident = (RM.state.incidents || []).find((i) => i.id === id);
      if (!incident) return;
      RM.app.go("control");
      setTimeout(() => {
        if (RM.map) RM.map.focus(incident.lng, incident.lat, 8.6);
      }, 60);
    },

    openDrawer(incident) {
      const corridor = RM.byId(RM.state.corridors, incident.corridor_id);
      const body =
        '<div class="callout ' + (incident.blocks_road ? "crit" : "plain") + '">' +
        RM.esc(incident.description || incident.title) + "</div>" +
        '<div class="section-title">Detail</div>' +
        '<dl class="dl">' +
        "<dt>Type</dt><dd>" + RM.esc(TYPE_LABEL[incident.type] || RM.fmt.title(incident.type)) + "</dd>" +
        "<dt>Severity</dt><dd>" + RM.esc(RM.fmt.title(incident.severity)) + "</dd>" +
        "<dt>Status</dt><dd>" + RM.esc(RM.fmt.title(incident.status)) + "</dd>" +
        "<dt>Blocks road</dt><dd>" + (incident.blocks_road ? "Yes" : "No") + "</dd>" +
        "<dt>Corridor</dt><dd>" + RM.esc(corridor ? corridor.name : incident.corridor_id || "Off-corridor") + "</dd>" +
        "<dt>Position</dt><dd class='mono'>" + RM.esc(Number(incident.lat).toFixed(4)) + ", " +
        RM.esc(Number(incident.lng).toFixed(4)) + "</dd>" +
        "<dt>Reported</dt><dd>" + RM.esc(RM.timeAgo(incident.reported_at)) + "</dd>" +
        "<dt>Source</dt><dd>" + RM.esc(incident.source_label || incident.source) + "</dd>" +
        "</dl>" +
        (incident.external_url
          ? '<a class="linkish" target="_blank" rel="noopener" href="' +
            RM.esc(incident.external_url) + '">Open the source record</a>'
          : "") +
        '<div class="section-title">Actions</div>' +
        '<div class="inc-actions">' +
        '<button class="btn tiny ghost" id="dr-locate">Show on map</button>' +
        (incident.status === "active"
          ? '<button class="btn tiny ghost" id="dr-ack">Acknowledge</button>'
          : "") +
        (incident.status !== "resolved"
          ? '<button class="btn tiny primary" id="dr-res">Resolve</button>'
          : "") +
        (corridor
          ? '<button class="btn tiny ghost" id="dr-risk">Corridor risk</button>'
          : "") +
        "</div>";

      RM.openDrawer(incident.title, incident.id, body);

      const locate = RM.$("#dr-locate");
      if (locate) locate.addEventListener("click", () => { RM.closeDrawer(); this.locate(incident.id); });
      const ack = RM.$("#dr-ack");
      if (ack) ack.addEventListener("click", () => { RM.closeDrawer(); this.setStatus(incident.id, "acknowledged"); });
      const res = RM.$("#dr-res");
      if (res) res.addEventListener("click", () => { RM.closeDrawer(); this.setStatus(incident.id, "resolved"); });
      const risk = RM.$("#dr-risk");
      if (risk) risk.addEventListener("click", () => RM.risk.openCorridor(incident.corridor_id));
    },

    async setStatus(id, status) {
      try {
        await RM.api.setIncidentStatus(id, status);
        RM.toast("Incident marked " + status, "ok");
        await RM.app.refresh();
      } catch (err) {
        RM.toast(err.message, "err");
      }
    },

    fillCorridors() {
      const select = RM.$("#f-corridor");
      if (!select) return;
      const corridors = RM.state.corridors || [];
      if (!corridors.length || select.options.length === corridors.length) return;
      const previous = select.value;
      select.innerHTML = corridors
        .map((c) => '<option value="' + RM.esc(c.id) + '">' + RM.esc(c.name) + "</option>")
        .join("");
      if (previous) select.value = previous;
    },

    async submit() {
      const corridorId = RM.$("#f-corridor").value;
      const type = RM.$("#f-type").value;
      const severity = RM.$("#f-severity").value;
      const description = RM.$("#f-desc").value.trim();
      const blocks = RM.$("#f-blocks").checked;
      const corridor = RM.byId(RM.state.corridors, corridorId);

      if (!corridorId) {
        RM.toast("Pick a corridor first", "err");
        return;
      }

      const payload = {
        corridor_id: corridorId,
        type: type,
        severity: severity,
        blocks_road: blocks,
        fraction: 0.5,
        title:
          (TYPE_LABEL[type] || "Incident") +
          " reported on " +
          (corridor ? corridor.name : corridorId),
        description:
          description ||
          "Reported from the control room. Location approximated to the corridor midpoint.",
      };

      try {
        await RM.api.reportIncident(payload);
        RM.$("#f-desc").value = "";
        RM.$("#f-blocks").checked = false;
        RM.toast("Report filed - corridor risk re-scored", "ok");
        await RM.app.refresh();
      } catch (err) {
        RM.toast(err.message, "err");
      }
    },
  };
})();
