/* ==========================================================================
   RouteMind AI - map engine

   A small, dependency-free slippy map:
     * OpenStreetMap raster tiles for the basemap (real online data)
     * an SVG overlay for corridors, routes, vehicles, incidents and depots
     * drag to pan, wheel / buttons to zoom, hover tooltips, click to select

   No CDN and no bundler: if tiles cannot be reached (no internet), the
   overlay still renders the network on a plain canvas and says so.
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});
  const TILE_URL = "https://tile.openstreetmap.org/";
  const TILE_SIZE = 256;
  const MIN_ZOOM = 4;
  const MAX_ZOOM = 13;

  /* --------------------------- web mercator ------------------------------ */

  const lngToWorld = (lng) => (lng + 180) / 360;
  const latToWorld = (lat) => {
    const clamped = Math.max(-85.05, Math.min(85.05, lat));
    const s = Math.sin((clamped * Math.PI) / 180);
    return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
  };
  const worldToLng = (x) => x * 360 - 180;
  const worldToLat = (y) => {
    const n = Math.PI - 2 * Math.PI * y;
    return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  };

  const SVG_NS = "http://www.w3.org/2000/svg";
  const svgEl = (name, attrs) => {
    const node = document.createElementNS(SVG_NS, name);
    for (const key in attrs) {
      if (attrs[key] !== undefined && attrs[key] !== null) {
        node.setAttribute(key, attrs[key]);
      }
    }
    return node;
  };

  /* ------------------------------ MapView -------------------------------- */

  function MapView(container, options) {
    this.el = typeof container === "string" ? RM.$(container) : container;
    if (!this.el) throw new Error("MapView: container not found");

    const opts = options || {};
    this.center = {
      x: lngToWorld(opts.center ? opts.center[0] : 93.0),
      y: latToWorld(opts.center ? opts.center[1] : 25.7),
    };
    this.zoom = opts.zoom || 6.2;
    this.showTiles = opts.tiles !== false;
    this.interactive = opts.interactive !== false;

    this.data = { corridors: [], vehicles: [], incidents: [], depots: [], cities: [] };
    this.routes = [];
    this.mode = "risk";
    this.layers = { vehicles: true, incidents: true, depots: true, cities: true };
    this.selected = null;
    this.handlers = {};
    this.tiles = new Map();
    this.tileErrors = 0;
    this.tileLoads = 0;
    this.tilesUsable = this.showTiles;

    this._build();
    this._bind();
    this.render();
  }

  MapView.prototype._build = function () {
    this.el.classList.add("map");
    this.el.innerHTML = "";

    this.tileLayer = document.createElement("div");
    this.tileLayer.className = "map-tiles";
    this.el.appendChild(this.tileLayer);

    this.svg = svgEl("svg", { class: "map-svg" });
    this.el.appendChild(this.svg);

    this.gRoads = svgEl("g", {});
    this.gRoutes = svgEl("g", {});
    this.gMarkers = svgEl("g", {});
    this.gLabels = svgEl("g", {});
    this.svg.appendChild(this.gRoads);
    this.svg.appendChild(this.gRoutes);
    this.svg.appendChild(this.gMarkers);
    this.svg.appendChild(this.gLabels);

    if (this.interactive) {
      const zoomBox = document.createElement("div");
      zoomBox.className = "map-zoom";
      zoomBox.innerHTML =
        '<button type="button" data-z="1" aria-label="Zoom in">+</button>' +
        '<button type="button" data-z="-1" aria-label="Zoom out">&minus;</button>';
      zoomBox.addEventListener("click", (event) => {
        const btn = event.target.closest("button");
        if (!btn) return;
        this.zoomBy(Number(btn.dataset.z));
      });
      this.el.appendChild(zoomBox);
    }

    const attrib = document.createElement("div");
    attrib.className = "map-attrib";
    attrib.innerHTML = 'Basemap &copy; OpenStreetMap contributors';
    this.el.appendChild(attrib);

    this.tip = document.createElement("div");
    this.tip.className = "map-tip";
    this.el.appendChild(this.tip);
  };

  MapView.prototype._bind = function () {
    if (!this.interactive) return;
    let dragging = false;
    let last = null;
    let moved = 0;

    this.el.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".map-zoom")) return;
      dragging = true;
      moved = 0;
      last = { x: event.clientX, y: event.clientY };
      this.el.classList.add("dragging");
      this.el.setPointerCapture(event.pointerId);
    });

    this.el.addEventListener("pointermove", (event) => {
      if (!dragging) {
        this._hover(event);
        return;
      }
      const size = this.worldSize();
      const dx = event.clientX - last.x;
      const dy = event.clientY - last.y;
      moved += Math.abs(dx) + Math.abs(dy);
      this.center.x -= dx / size;
      this.center.y -= dy / size;
      this.center.y = Math.max(0, Math.min(1, this.center.y));
      last = { x: event.clientX, y: event.clientY };
      this.render();
    });

    const endDrag = (event) => {
      if (!dragging) return;
      dragging = false;
      this.el.classList.remove("dragging");
      try { this.el.releasePointerCapture(event.pointerId); } catch (err) { /* ignore */ }
    };
    this.el.addEventListener("pointerup", endDrag);
    this.el.addEventListener("pointercancel", endDrag);
    this.el.addEventListener("pointerleave", () => this._hideTip());

    this.el.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const rect = this.el.getBoundingClientRect();
        const px = event.clientX - rect.left;
        const py = event.clientY - rect.top;
        this.zoomBy(event.deltaY < 0 ? 0.5 : -0.5, px, py);
      },
      { passive: false }
    );

    this.el.addEventListener("dblclick", (event) => {
      const rect = this.el.getBoundingClientRect();
      this.zoomBy(1, event.clientX - rect.left, event.clientY - rect.top);
    });

    if (window.ResizeObserver) {
      this._ro = new ResizeObserver(RM.debounce(() => this.render(), 80));
      this._ro.observe(this.el);
    }
  };

  /* ------------------------------ geometry ------------------------------- */

  MapView.prototype.worldSize = function () {
    return TILE_SIZE * Math.pow(2, this.zoom);
  };

  MapView.prototype.size = function () {
    return { w: this.el.clientWidth || 800, h: this.el.clientHeight || 460 };
  };

  MapView.prototype.project = function (lng, lat) {
    const size = this.worldSize();
    const view = this.size();
    return {
      x: (lngToWorld(lng) - this.center.x) * size + view.w / 2,
      y: (latToWorld(lat) - this.center.y) * size + view.h / 2,
    };
  };

  MapView.prototype.unproject = function (px, py) {
    const size = this.worldSize();
    const view = this.size();
    return [
      worldToLng((px - view.w / 2) / size + this.center.x),
      worldToLat((py - view.h / 2) / size + this.center.y),
    ];
  };

  MapView.prototype.zoomBy = function (delta, px, py) {
    const view = this.size();
    const anchorX = px === undefined ? view.w / 2 : px;
    const anchorY = py === undefined ? view.h / 2 : py;
    const before = this.unproject(anchorX, anchorY);
    this.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.zoom + delta));
    const after = this.unproject(anchorX, anchorY);
    this.center.x += lngToWorld(before[0]) - lngToWorld(after[0]);
    this.center.y += latToWorld(before[1]) - latToWorld(after[1]);
    this.render();
  };

  MapView.prototype.fitTo = function (coords, padding) {
    const points = (coords || []).filter(
      (p) => p && isFinite(p[0]) && isFinite(p[1])
    );
    if (!points.length) return;

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    points.forEach((p) => {
      const x = lngToWorld(p[0]);
      const y = latToWorld(p[1]);
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    });

    const view = this.size();
    const pad = padding === undefined ? 46 : padding;
    const spanX = Math.max(maxX - minX, 1e-6);
    const spanY = Math.max(maxY - minY, 1e-6);
    const scaleX = (view.w - pad * 2) / (spanX * TILE_SIZE);
    const scaleY = (view.h - pad * 2) / (spanY * TILE_SIZE);
    const zoom = Math.log2(Math.max(1e-6, Math.min(scaleX, scaleY)));

    this.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
    this.center = { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
    this.render();
  };

  MapView.prototype.focus = function (lng, lat, zoom) {
    this.center = { x: lngToWorld(lng), y: latToWorld(lat) };
    if (zoom) this.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
    this.render();
  };

  /* -------------------------------- data --------------------------------- */

  MapView.prototype.setData = function (data) {
    this.data = Object.assign(this.data, data || {});
    this.render();
  };

  MapView.prototype.setRoutes = function (routes) {
    this.routes = routes || [];
    this.render();
  };

  MapView.prototype.setMode = function (mode) {
    this.mode = mode === "traffic" ? "traffic" : "risk";
    this.render();
  };

  MapView.prototype.setLayer = function (name, visible) {
    this.layers[name] = !!visible;
    this.render();
  };

  MapView.prototype.select = function (key) {
    this.selected = key;
    this.render();
  };

  MapView.prototype.on = function (event, handler) {
    (this.handlers[event] = this.handlers[event] || []).push(handler);
  };

  MapView.prototype.emit = function (event, payload) {
    (this.handlers[event] || []).forEach((fn) => fn(payload));
  };

  /* -------------------------------- tiles -------------------------------- */

  MapView.prototype._renderTiles = function () {
    if (!this.showTiles) return;

    const view = this.size();
    const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(this.zoom)));
    const scale = Math.pow(2, this.zoom - z);
    const tilePx = TILE_SIZE * scale;
    const count = Math.pow(2, z);

    const worldPxSize = TILE_SIZE * Math.pow(2, this.zoom);
    const originX = this.center.x * worldPxSize - view.w / 2;
    const originY = this.center.y * worldPxSize - view.h / 2;

    const first = { x: Math.floor(originX / tilePx), y: Math.floor(originY / tilePx) };
    const last = {
      x: Math.floor((originX + view.w) / tilePx),
      y: Math.floor((originY + view.h) / tilePx),
    };

    const used = new Set();

    for (let ty = first.y; ty <= last.y; ty++) {
      if (ty < 0 || ty >= count) continue;
      for (let tx = first.x; tx <= last.x; tx++) {
        const wrapped = ((tx % count) + count) % count;
        const key = z + "/" + wrapped + "/" + ty;
        used.add(key);

        let img = this.tiles.get(key);
        if (!img) {
          img = new Image();
          img.alt = "";
          img.decoding = "async";
          img.loading = "eager";
          img.addEventListener("load", () => {
            this.tileLoads += 1;
            img.style.opacity = "1";
          });
          img.addEventListener("error", () => {
            this.tileErrors += 1;
            img.style.display = "none";
            this._checkTileHealth();
          });
          img.style.opacity = "0";
          img.style.transition = "opacity .18s";
          img.src = TILE_URL + z + "/" + wrapped + "/" + ty + ".png";
          this.tiles.set(key, img);
          this.tileLayer.appendChild(img);
        }

        img.style.width = tilePx + "px";
        img.style.height = tilePx + "px";
        img.style.left = (tx * tilePx - originX) + "px";
        img.style.top = (ty * tilePx - originY) + "px";
      }
    }

    // Drop tiles that scrolled out of view so the DOM stays small.
    if (this.tiles.size > 220) {
      this.tiles.forEach((img, key) => {
        if (!used.has(key)) {
          img.remove();
          this.tiles.delete(key);
        }
      });
    }
  };

  MapView.prototype._checkTileHealth = function () {
    if (this.tileLoads === 0 && this.tileErrors >= 6 && this.tilesUsable) {
      this.tilesUsable = false;
      this.emit("tilestatus", { usable: false });
    }
  };

  /* ------------------------------- drawing -------------------------------- */

  const path = (points, project) => {
    let d = "";
    for (let i = 0; i < points.length; i++) {
      const p = project(points[i][0], points[i][1]);
      d += (i === 0 ? "M" : "L") + p.x.toFixed(1) + " " + p.y.toFixed(1);
    }
    return d;
  };

  MapView.prototype.render = function () {
    const view = this.size();
    if (!view.w || !view.h) return;

    this.svg.setAttribute("viewBox", "0 0 " + view.w + " " + view.h);
    this._renderTiles();

    const project = this.project.bind(this);
    const roads = document.createDocumentFragment();
    const routes = document.createDocumentFragment();
    const markers = document.createDocumentFragment();
    const labels = document.createDocumentFragment();

    const strokeWidth = this.zoom < 6 ? 2.6 : this.zoom < 8 ? 3.6 : 5;

    /* ---- corridors ---- */
    (this.data.corridors || []).forEach((corridor) => {
      const line = corridor.geometry;
      if (!line || line.length < 2) return;

      const isBlocked = corridor.status === "blocked";
      let color;
      if (this.mode === "traffic") {
        color = isBlocked
          ? RM.color.road.blocked
          : RM.trafficColor(corridor.traffic && corridor.traffic.level);
      } else {
        color = RM.statusColor(corridor.status);
        if (!isBlocked && corridor.risk) {
          color = corridor.risk.probability >= 0.45
            ? RM.bandColor(corridor.risk.band)
            : RM.color.road.operational;
        }
      }

      const isSelected = this.selected === "corridor:" + corridor.id;
      const d = path(line, project);

      roads.appendChild(
        svgEl("path", {
          d: d,
          fill: "none",
          stroke: "#FFFFFF",
          "stroke-width": strokeWidth + 3,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          opacity: 0.85,
        })
      );

      roads.appendChild(
        svgEl("path", {
          d: d,
          fill: "none",
          stroke: isSelected ? RM.color.road.selected : color,
          "stroke-width": isSelected ? strokeWidth + 1.6 : strokeWidth,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          "stroke-dasharray": isBlocked ? "7 5" : null,
        })
      );

      const hit = svgEl("path", {
        d: d,
        fill: "none",
        stroke: "transparent",
        "stroke-width": 16,
        class: "hit",
      });
      hit.addEventListener("click", () => this.emit("select", { type: "corridor", id: corridor.id, data: corridor }));
      hit.addEventListener("pointerenter", (event) =>
        this._showTip(event, this._corridorTip(corridor))
      );
      hit.addEventListener("pointerleave", () => this._hideTip());
      roads.appendChild(hit);
    });

    /* ---- planned / alternative routes ---- */
    (this.routes || []).forEach((route) => {
      if (!route.geometry || route.geometry.length < 2) return;
      const d = path(route.geometry, project);
      routes.appendChild(
        svgEl("path", {
          d: d,
          fill: "none",
          stroke: "#FFFFFF",
          "stroke-width": 8,
          "stroke-linecap": "round",
          opacity: 0.9,
        })
      );
      routes.appendChild(
        svgEl("path", {
          d: d,
          fill: "none",
          stroke: route.color || RM.color.road.alt,
          "stroke-width": route.selected ? 5 : 3.4,
          "stroke-linecap": "round",
          "stroke-dasharray": route.dashed ? "9 6" : null,
          opacity: route.dimmed ? 0.5 : 1,
        })
      );
    });

    /* ---- depots ---- */
    if (this.layers.depots) {
      (this.data.depots || []).forEach((depot) => {
        const p = project(depot.lng, depot.lat);
        const g = svgEl("g", { class: "hit" });
        g.appendChild(
          svgEl("rect", {
            x: p.x - 5.5, y: p.y - 5.5, width: 11, height: 11, rx: 3,
            fill: "#FFFFFF", stroke: RM.color.inkSub, "stroke-width": 2,
          })
        );
        g.addEventListener("click", () => this.emit("select", { type: "depot", id: depot.id, data: depot }));
        g.addEventListener("pointerenter", (event) =>
          this._showTip(event, "<b>" + RM.esc(depot.name) + "</b><div class='tip-sub'>Capacity " + RM.esc(depot.capacity_pct) + "%</div>")
        );
        g.addEventListener("pointerleave", () => this._hideTip());
        markers.appendChild(g);
      });
    }

    /* ---- cities ---- */
    if (this.layers.cities !== false) {
      (this.data.cities || []).forEach((city) => {
        if (!city.major && this.zoom < 7) return;
        const p = project(city.lng, city.lat);
        markers.appendChild(
          svgEl("circle", { cx: p.x, cy: p.y, r: 2.6, fill: RM.color.inkFaint })
        );
        if (city.major || this.zoom >= 7.5) {
          const text = svgEl("text", {
            x: p.x + 6, y: p.y + 3.5,
            "font-size": 10.5,
            "font-family": "Inter, system-ui, sans-serif",
            fill: RM.color.ink,
            stroke: "#FFFFFF",
            "stroke-width": 2.6,
            "paint-order": "stroke",
            "stroke-linejoin": "round",
          });
          text.textContent = city.name;
          labels.appendChild(text);
        }
      });
    }

    /* ---- incidents ---- */
    if (this.layers.incidents) {
      (this.data.incidents || []).forEach((incident) => {
        if (incident.lng === null || incident.lng === undefined) return;
        const p = project(incident.lng, incident.lat);
        const color =
          incident.severity === "critical" ? RM.color.crit
          : incident.severity === "high" ? "#F97316"
          : RM.color.warn;

        const g = svgEl("g", { class: "hit" });
        if (incident.blocks_road) {
          g.appendChild(
            svgEl("circle", { cx: p.x, cy: p.y, r: 13, fill: color, opacity: 0.16 })
          );
        }
        g.appendChild(
          svgEl("path", {
            d: "M " + p.x + " " + (p.y - 7.5) + " L " + (p.x + 7.5) + " " + p.y +
               " L " + p.x + " " + (p.y + 7.5) + " L " + (p.x - 7.5) + " " + p.y + " Z",
            fill: color,
            stroke: "#FFFFFF",
            "stroke-width": 2,
          })
        );
        g.addEventListener("click", () => this.emit("select", { type: "incident", id: incident.id, data: incident }));
        g.addEventListener("pointerenter", (event) =>
          this._showTip(
            event,
            "<b>" + RM.esc(incident.title) + "</b><div class='tip-sub'>" +
              RM.esc(RM.fmt.title(incident.severity)) + " - " +
              RM.esc(incident.source_label || incident.source) +
              (incident.blocks_road ? " - road blocked" : "") + "</div>"
          )
        );
        g.addEventListener("pointerleave", () => this._hideTip());
        markers.appendChild(g);
      });
    }

    /* ---- vehicles ---- */
    if (this.layers.vehicles) {
      (this.data.vehicles || []).forEach((vehicle) => {
        if (vehicle.lng === null || vehicle.lng === undefined) return;
        const p = project(vehicle.lng, vehicle.lat);
        const halted = vehicle.status === "halted";
        const fill =
          vehicle.priority === "critical" ? RM.color.accent
          : halted ? RM.color.crit
          : "#334155";

        const g = svgEl("g", { class: "hit" });
        if (halted) {
          g.appendChild(svgEl("circle", { cx: p.x, cy: p.y, r: 11, fill: RM.color.crit, opacity: 0.18 }));
        }
        if (vehicle.priority === "critical") {
          g.appendChild(svgEl("circle", { cx: p.x, cy: p.y, r: 10.5, fill: RM.color.accent, opacity: 0.15 }));
        }
        g.appendChild(
          svgEl("circle", {
            cx: p.x, cy: p.y, r: 5.4,
            fill: fill, stroke: "#FFFFFF", "stroke-width": 2,
          })
        );
        g.addEventListener("click", () => this.emit("select", { type: "vehicle", id: vehicle.id, data: vehicle }));
        g.addEventListener("pointerenter", (event) =>
          this._showTip(
            event,
            "<b>" + RM.esc(vehicle.id) + "</b><div class='tip-sub'>" +
              RM.esc(vehicle.cargo || "") + "<br>" +
              RM.esc(RM.fmt.title(vehicle.status)) +
              (vehicle.eta_min ? " - ETA " + RM.esc(RM.fmt.mins(vehicle.eta_min)) : "") +
              "</div>"
          )
        );
        g.addEventListener("pointerleave", () => this._hideTip());
        markers.appendChild(g);
      });
    }

    this.gRoads.replaceChildren(roads);
    this.gRoutes.replaceChildren(routes);
    this.gMarkers.replaceChildren(markers);
    this.gLabels.replaceChildren(labels);
  };

  MapView.prototype._corridorTip = function (corridor) {
    const risk = corridor.risk || {};
    const traffic = corridor.traffic || {};
    return (
      "<b>" + RM.esc(corridor.name) + "</b>" +
      "<div class='tip-sub'>" +
      RM.esc(RM.fmt.title(corridor.status)) +
      " - disruption risk " + RM.esc(RM.fmt.pct(risk.probability)) +
      (traffic.level ? "<br>Traffic: " + RM.esc(RM.fmt.title(traffic.level)) : "") +
      (traffic.observed_kmh ? " (" + Math.round(traffic.observed_kmh) + " km/h)" : "") +
      "</div>"
    );
  };

  MapView.prototype._showTip = function (event, html) {
    const rect = this.el.getBoundingClientRect();
    this.tip.innerHTML = html;
    this.tip.classList.add("on");
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const flip = x > rect.width - 190;
    this.tip.style.left = (flip ? x - 200 : x + 14) + "px";
    this.tip.style.top = Math.max(6, y - 10) + "px";
  };

  MapView.prototype._hideTip = function () {
    this.tip.classList.remove("on");
  };

  MapView.prototype._hover = function () { /* tooltips are bound per-shape */ };

  RM.MapView = MapView;
})();
