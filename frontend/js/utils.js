/* ==========================================================================
   RouteMind AI - shared helpers
   Everything hangs off a single global: window.RM
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  RM.state = {
    overview: null,
    map: null,
    vehicles: [],
    deliveries: [],
    incidents: [],
    alerts: [],
    corridors: [],
    simulation: null,
    view: "control",
    mapMode: "risk",
    layers: { vehicles: true, incidents: true, depots: true },
  };

  /* ------------------------------- DOM ---------------------------------- */

  RM.$ = (sel, root) => (root || document).querySelector(sel);
  RM.$$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  RM.esc = function (value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  };

  RM.setHTML = function (node, html) {
    if (!node) return;
    node.innerHTML = html;
  };

  /* ---------------------------- formatting ------------------------------ */

  RM.fmt = {
    pct(x, digits) {
      if (x === null || x === undefined || isNaN(x)) return "-";
      const v = x <= 1 ? x * 100 : x;
      return v.toFixed(digits === undefined ? 0 : digits) + "%";
    },
    km(x) {
      if (x === null || x === undefined) return "-";
      return Number(x).toFixed(x < 100 ? 1 : 0) + " km";
    },
    mins(x) {
      if (x === null || x === undefined) return "-";
      const m = Math.round(Number(x));
      if (m < 60) return m + " min";
      const h = Math.floor(m / 60);
      const rest = m % 60;
      return rest ? h + "h " + rest + "m" : h + "h";
    },
    num(x) {
      if (x === null || x === undefined) return "-";
      return Number(x).toLocaleString("en-IN");
    },
    title(s) {
      if (!s) return "";
      return String(s)
        .replace(/[-_]/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
    },
  };

  // Accepts epoch seconds, epoch millis or an ISO string.
  RM.toDate = function (value) {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "number") {
      return new Date(value > 1e12 ? value : value * 1000);
    }
    const asNumber = Number(value);
    if (!isNaN(asNumber) && String(value).trim() !== "") {
      return new Date(asNumber > 1e12 ? asNumber : asNumber * 1000);
    }
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  };

  RM.timeAgo = function (value) {
    const d = RM.toDate(value);
    if (!d) return "";
    const secs = Math.floor((Date.now() - d.getTime()) / 1000);
    if (secs < 5) return "just now";
    if (secs < 60) return secs + "s ago";
    const mins = Math.floor(secs / 60);
    if (mins < 60) return mins + " min ago";
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + "h ago";
    const days = Math.floor(hrs / 24);
    if (days < 30) return days + "d ago";
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  };

  RM.clockTime = function (value) {
    const d = RM.toDate(value) || new Date();
    return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
  };

  /* ------------------------------ colours -------------------------------- */

  const CSS = getComputedStyle(document.documentElement);
  const token = (name, fallback) => (CSS.getPropertyValue(name) || "").trim() || fallback;

  RM.color = {
    ok: token("--ok", "#16A34A"),
    warn: token("--warn", "#D97706"),
    crit: token("--crit", "#DC2626"),
    accent: token("--accent", "#6D28D9"),
    ink: token("--ink", "#1F2937"),
    inkSub: token("--ink-sub", "#6B7280"),
    inkFaint: token("--ink-faint", "#9CA3AF"),
    line: token("--line", "#E5E7EB"),
    road: {
      operational: token("--road-operational", "#C3CAD2"),
      "at-risk": token("--road-at-risk", "#F59E0B"),
      blocked: token("--road-blocked", "#EF4444"),
      selected: token("--road-selected", "#7C3AED"),
      alt: token("--road-alt", "#8B5CF6"),
    },
  };

  // Risk band -> colour. Bands come from the backend: low/moderate/high/critical.
  RM.bandColor = function (band) {
    switch (band) {
      case "critical": return RM.color.crit;
      case "high": return "#F97316";
      case "moderate": return RM.color.warn;
      default: return RM.color.ok;
    }
  };

  RM.bandClass = function (band) {
    switch (band) {
      case "critical": return "crit";
      case "high": return "crit";
      case "moderate": return "warn";
      default: return "ok";
    }
  };

  RM.statusColor = function (status) {
    if (status === "blocked") return RM.color.road.blocked;
    if (status === "at-risk") return RM.color.road["at-risk"];
    return RM.color.road.operational;
  };

  RM.trafficColor = function (level) {
    switch (level) {
      case "severe": return "#B91C1C";
      case "heavy": return "#EF4444";
      case "moderate": return "#F59E0B";
      case "light": return "#84CC16";
      default: return "#22C55E";
    }
  };

  RM.severityClass = function (severity) {
    if (severity === "critical") return "crit";
    if (severity === "high") return "warn";
    if (severity === "warning") return "warn";
    return "soft";
  };

  RM.priorityClass = function (priority) {
    if (priority === "critical") return "crit";
    if (priority === "high") return "warn";
    return "soft";
  };

  /* ------------------------------- toasts -------------------------------- */

  RM.toast = function (message, kind, ms) {
    const host = RM.$("#toasts");
    if (!host) return;
    const node = document.createElement("div");
    node.className = "toast" + (kind ? " " + kind : "");
    node.textContent = message;
    host.appendChild(node);
    setTimeout(() => {
      node.style.transition = "opacity .25s, transform .25s";
      node.style.opacity = "0";
      node.style.transform = "translateY(6px)";
      setTimeout(() => node.remove(), 260);
    }, ms || 3600);
  };

  /* ------------------------------- drawer -------------------------------- */

  RM.openDrawer = function (title, subtitle, html) {
    const drawer = RM.$("#drawer");
    const scrim = RM.$("#drawer-scrim");
    if (!drawer) return;
    RM.$("#drawer-title").textContent = title || "Details";
    RM.$("#drawer-sub").textContent = subtitle || "";
    RM.setHTML(RM.$("#drawer-body"), html || "");
    drawer.hidden = false;
    scrim.hidden = false;
  };

  RM.closeDrawer = function () {
    const drawer = RM.$("#drawer");
    const scrim = RM.$("#drawer-scrim");
    if (drawer) drawer.hidden = true;
    if (scrim) scrim.hidden = true;
  };

  /* ------------------------------- misc ---------------------------------- */

  RM.debounce = function (fn, wait) {
    let t = null;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), wait || 200);
    };
  };

  RM.empty = function (message) {
    return '<div class="empty">' + RM.esc(message) + "</div>";
  };

  RM.meter = function (value, color) {
    const pct = Math.max(0, Math.min(100, (value <= 1 ? value * 100 : value)));
    return (
      '<span class="bar"><i style="width:' + pct.toFixed(0) + "%;background:" +
      (color || RM.color.accent) + '"></i></span>'
    );
  };

  // Pull the incident/vehicle/etc. out of a click on a row.
  RM.byId = function (list, id) {
    return (list || []).find((item) => item && item.id === id) || null;
  };
})();
