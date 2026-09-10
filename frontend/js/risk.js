/* ==========================================================================
   RouteMind AI - corridor risk board
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  RM.risk = {
    filter: "all",

    render() {
      const body = RM.$("#risk-table tbody");
      if (!body) return;

      const corridors = (RM.state.corridors || []).slice().sort((a, b) => {
        const ra = (a.risk && a.risk.probability) || 0;
        const rb = (b.risk && b.risk.probability) || 0;
        return rb - ra;
      });

      const rows = corridors.filter((corridor) => {
        if (this.filter === "blocked") return corridor.status === "blocked";
        if (this.filter === "at-risk") return corridor.status === "at-risk" || corridor.status === "blocked";
        return true;
      });

      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="7">' + RM.empty("No corridors match this filter") + "</td></tr>";
        return;
      }

      body.innerHTML = rows
        .map((corridor) => {
          const risk = corridor.risk || {};
          const weather = corridor.weather || {};
          const traffic = corridor.traffic || {};
          const color = RM.bandColor(risk.band);
          const statusPill =
            corridor.status === "blocked"
              ? '<span class="pill crit">Blocked</span>'
              : corridor.status === "at-risk"
              ? '<span class="pill warn">At risk</span>'
              : '<span class="pill ok">Operational</span>';

          return (
            '<tr class="clickable' + (corridor.status === "blocked" ? " is-flagged" : "") +
            '" data-corridor="' + RM.esc(corridor.id) + '">' +
            "<td><div class='cell-main'>" + RM.esc(corridor.name) + "</div>" +
            "<div class='cell-sub'>" + RM.esc(corridor.from) + " to " + RM.esc(corridor.to) + "</div></td>" +
            "<td>" + statusPill + "</td>" +
            '<td class="num"><span style="color:' + color + ';font-weight:600">' +
            RM.fmt.pct(risk.probability) + "</span> " + RM.meter(risk.probability || 0, color) +
            "<div class='cell-sub'>" + RM.esc(risk.headline || "") + "</div></td>" +
            '<td class="num">' +
            (weather.rain_next_24h_mm === null || weather.rain_next_24h_mm === undefined
              ? "-"
              : weather.rain_next_24h_mm.toFixed(0) + " mm") +
            "</td>" +
            "<td><span class='pill' style='background:transparent;color:" +
            RM.trafficColor(traffic.level) + "'>" + RM.esc(RM.fmt.title(traffic.level || "-")) + "</span>" +
            (traffic.observed_kmh ? "<div class='cell-sub'>" + Math.round(traffic.observed_kmh) + " km/h</div>" : "") +
            "</td>" +
            '<td class="num">' + RM.esc(RM.fmt.km(corridor.length_km)) + "</td>" +
            '<td><button class="btn tiny ghost">Why?</button></td>' +
            "</tr>"
          );
        })
        .join("");

      RM.$$("#risk-table tbody tr[data-corridor]").forEach((row) => {
        row.addEventListener("click", () => this.openCorridor(row.dataset.corridor));
      });
    },

    setFilter(filter) {
      this.filter = filter;
      this.render();
    },

    /* --------------------------- explanation drawer ------------------------ */

    async openCorridor(corridorId) {
      const corridor = (RM.state.corridors || []).find((c) => c.id === corridorId);
      RM.openDrawer(
        corridor ? corridor.name : corridorId,
        corridor ? corridor.from + " to " + corridor.to : "",
        '<p class="muted">Loading risk breakdown...</p>'
      );

      if (RM.map) RM.map.select("corridor:" + corridorId);

      try {
        const detail = await RM.api.risk(corridorId);
        const factors = detail.factors || [];
        const probability = detail.probability !== undefined ? detail.probability : (corridor && corridor.risk.probability);
        const band = detail.band || (corridor && corridor.risk.band);
        const color = RM.bandColor(band);

        const maxShare = Math.max.apply(
          null,
          factors.map((f) => f.share || f.contribution || 0).concat([0.0001])
        );

        const factorHTML = factors
          .slice()
          .sort((a, b) => (b.share || b.contribution || 0) - (a.share || a.contribution || 0))
          .map((factor) => {
            const share = factor.share || factor.contribution || 0;
            return (
              '<div class="factor">' +
              '<div class="factor-top"><span class="factor-name">' + RM.esc(factor.label || factor.key) +
              '</span><span class="factor-val">' + Math.round(share * 100) + "% of score</span></div>" +
              '<div class="factor-bar"><i style="width:' + Math.round((share / maxShare) * 100) + '%"></i></div>' +
              (factor.detail ? '<div class="factor-detail">' + RM.esc(factor.detail) + "</div>" : "") +
              "</div>"
            );
          })
          .join("");

        const weather = (corridor && corridor.weather) || {};
        const traffic = (corridor && corridor.traffic) || {};

        RM.setHTML(
          RM.$("#drawer-body"),
          '<div class="callout" style="background:' + color + '14;color:' + color +
            ";border-color:" + color + '33">' +
            "<b>" + RM.fmt.pct(probability) + " chance of disruption in the next " +
            RM.esc(detail.window_hours || 24) + " hours.</b><br>" +
            RM.esc(detail.headline || (corridor && corridor.risk.headline) || "") +
            "</div>" +
            (corridor && corridor.status === "blocked" && corridor.block_reason
              ? '<div class="callout crit" style="margin-top:10px">Currently blocked: ' +
                RM.esc(corridor.block_reason) + "</div>"
              : "") +
            '<div class="section-title">What is driving this score</div>' +
            (factorHTML || '<p class="muted">No factor breakdown available.</p>') +
            '<div class="section-title">Corridor facts</div>' +
            '<dl class="dl">' +
            "<dt>Length</dt><dd>" + RM.esc(RM.fmt.km(corridor && corridor.length_km)) + "</dd>" +
            "<dt>Lanes</dt><dd>" + RM.esc((corridor && corridor.lanes) || "-") + "</dd>" +
            "<dt>States</dt><dd>" + RM.esc(((corridor && corridor.states) || []).join(", ")) + "</dd>" +
            "<dt>Seismic zone</dt><dd>" + RM.esc((corridor && corridor.seismic_zone) || "-") + "</dd>" +
            "<dt>Terrain index</dt><dd>" + RM.esc((corridor && corridor.terrain_index) || "-") + "</dd>" +
            "<dt>Surface condition</dt><dd>" + RM.esc((corridor && corridor.condition_index) || "-") + "</dd>" +
            "<dt>Rain last 48h</dt><dd>" +
            (weather.rain_48h_mm !== undefined && weather.rain_48h_mm !== null ? weather.rain_48h_mm.toFixed(1) + " mm" : "-") +
            "</dd>" +
            "<dt>Rain next 24h</dt><dd>" +
            (weather.rain_next_24h_mm !== undefined && weather.rain_next_24h_mm !== null ? weather.rain_next_24h_mm.toFixed(1) + " mm" : "-") +
            "</dd>" +
            "<dt>Observed speed</dt><dd>" +
            (traffic.observed_kmh ? Math.round(traffic.observed_kmh) + " km/h (" + RM.esc(traffic.source || "") + ")" : "-") +
            "</dd>" +
            "</dl>" +
            '<div class="callout plain" style="margin-top:16px">Scores come from a transparent weighted model (' +
            RM.esc(detail.model || "heuristic-v1") +
            "), not a trained ML model. Every weight is listed in the model card.</div>"
        );
      } catch (err) {
        RM.setHTML(RM.$("#drawer-body"), '<div class="callout crit">' + RM.esc(err.message) + "</div>");
      }
    },
  };
})();
