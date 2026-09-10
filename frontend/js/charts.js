/* ==========================================================================
   RouteMind AI - hand-rolled SVG charts (no charting library)
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  function svgOpen(width, height) {
    return (
      '<svg viewBox="0 0 ' + width + " " + height +
      '" preserveAspectRatio="none" style="height:' + height + 'px">'
    );
  }

  /* --------------------- grouped bars: rainfall by corridor --------------- */

  RM.charts = {
    rainfall(host, series) {
      if (!host) return;
      const items = (series || [])
        .slice()
        .sort((a, b) => (b.rain_next_24h || 0) - (a.rain_next_24h || 0))
        .slice(0, 7);

      if (!items.length) {
        host.innerHTML = RM.empty("No rainfall data available");
        return;
      }

      const W = 640, H = 190;
      const padL = 34, padR = 8, padT = 12, padB = 34;
      const plotW = W - padL - padR;
      const plotH = H - padT - padB;
      const max = Math.max(
        20,
        ...items.map((d) => Math.max(d.rain_next_24h || 0, d.rain_48h || 0))
      );
      const niceMax = Math.ceil(max / 20) * 20;
      const slot = plotW / items.length;
      const barW = Math.min(17, slot / 3.2);

      let out = svgOpen(W, H);

      // horizontal grid + y labels
      for (let i = 0; i <= 4; i++) {
        const value = (niceMax / 4) * i;
        const y = padT + plotH - (value / niceMax) * plotH;
        out += '<line class="grid-line" x1="' + padL + '" y1="' + y.toFixed(1) +
               '" x2="' + (W - padR) + '" y2="' + y.toFixed(1) + '" />';
        out += '<text class="axis-text" x="' + (padL - 6) + '" y="' + (y + 3).toFixed(1) +
               '" text-anchor="end">' + value + "</text>";
      }

      items.forEach((item, index) => {
        const cx = padL + slot * index + slot / 2;
        const past = item.rain_48h || 0;
        const next = item.rain_next_24h || 0;
        const hPast = (past / niceMax) * plotH;
        const hNext = (next / niceMax) * plotH;
        const color = RM.bandColor(
          next >= 115 ? "critical" : next >= 64 ? "high" : next >= 25 ? "moderate" : "low"
        );

        out +=
          '<rect class="bar-rect" x="' + (cx - barW - 1.5).toFixed(1) + '" y="' +
          (padT + plotH - hPast).toFixed(1) + '" width="' + barW.toFixed(1) +
          '" height="' + Math.max(1, hPast).toFixed(1) +
          '" rx="2" fill="#D8DCE3"><title>' + RM.esc(item.name) +
          " - last 48h: " + past.toFixed(1) + " mm</title></rect>";

        out +=
          '<rect class="bar-rect" x="' + (cx + 1.5).toFixed(1) + '" y="' +
          (padT + plotH - hNext).toFixed(1) + '" width="' + barW.toFixed(1) +
          '" height="' + Math.max(1, hNext).toFixed(1) +
          '" rx="2" fill="' + color + '"><title>' + RM.esc(item.name) +
          " - next 24h: " + next.toFixed(1) + " mm (risk " +
          RM.fmt.pct(item.probability) + ")</title></rect>";

        const label = (item.name || "").replace("NH-", "NH");
        out +=
          '<text class="axis-text" x="' + cx.toFixed(1) + '" y="' + (H - 16) +
          '" text-anchor="middle">' + RM.esc(label) + "</text>";
      });

      out += "</svg>";

      out +=
        '<div style="display:flex;gap:14px;justify-content:center;margin-top:2px">' +
        '<span class="muted small"><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:#D8DCE3;margin-right:5px"></span>Last 48h</span>' +
        '<span class="muted small"><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:' +
        RM.color.warn + ';margin-right:5px"></span>Forecast next 24h</span></div>';

      host.innerHTML = out;
    },

    /* ------------------- stacked bar: risk distribution ------------------- */

    distribution(host, dist) {
      if (!host) return;
      const bands = [
        { key: "low", label: "Low", color: RM.bandColor("low") },
        { key: "moderate", label: "Moderate", color: RM.bandColor("moderate") },
        { key: "high", label: "High", color: RM.bandColor("high") },
        { key: "critical", label: "Critical", color: RM.bandColor("critical") },
      ];
      const data = dist || {};
      const total = bands.reduce((sum, b) => sum + (data[b.key] || 0), 0);

      if (!total) {
        host.innerHTML = RM.empty("No corridors scored yet");
        return;
      }

      let out = '<div style="display:flex;height:16px;border-radius:8px;overflow:hidden;gap:2px">';
      bands.forEach((band) => {
        const count = data[band.key] || 0;
        if (!count) return;
        const width = (count / total) * 100;
        out +=
          '<div title="' + band.label + ": " + count + ' corridors" style="width:' +
          width.toFixed(1) + "%;background:" + band.color + '"></div>';
      });
      out += "</div>";

      out += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px">';
      bands.forEach((band) => {
        const count = data[band.key] || 0;
        out +=
          '<div><div style="display:flex;align-items:center;gap:5px">' +
          '<span style="width:8px;height:8px;border-radius:50%;background:' + band.color + '"></span>' +
          '<span class="muted small">' + band.label + "</span></div>" +
          '<div style="font-size:19px;font-weight:650;margin-top:1px">' + count + "</div></div>";
      });
      out += "</div>";

      host.innerHTML = out;
    },

    /* ------------------------ tiny inline sparkline ----------------------- */

    sparkline(values, color) {
      const list = (values || []).filter((v) => isFinite(v));
      if (list.length < 2) return "";
      const W = 54, H = 18;
      const min = Math.min.apply(null, list);
      const max = Math.max.apply(null, list);
      const span = max - min || 1;
      const step = W / (list.length - 1);
      let d = "";
      list.forEach((value, index) => {
        const x = index * step;
        const y = H - ((value - min) / span) * (H - 3) - 1.5;
        d += (index === 0 ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1);
      });
      return (
        '<svg class="kpi-spark" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H +
        '"><path d="' + d + '" fill="none" stroke="' + (color || RM.color.inkFaint) +
        '" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
      );
    },
  };
})();
