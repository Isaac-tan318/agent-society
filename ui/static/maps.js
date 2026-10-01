/* AgentSociety Studio - map views (Leaflet + OpenStreetMap tiles).
   StudioMaps.preview / areaPicker / peopleMap / replay each render into a container element.
   Colours come from CSS tokens (--series-*, --lu-other) and are re-read when the theme changes. */
(function () {
  "use strict";
  const SG_CENTER = [1.3521, 103.8198];
  const views = new Set(); // live views, restyled on theme change

  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function groupColor(i) { return cssVar(["--series-1", "--series-2", "--series-3", "--lu-other"][i] || "--lu-other"); }
  function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; }

  function available(container) {
    if (window.L) return true;
    container.appendChild(el("div", "notice warn small",
      "The map view needs an internet connection: it loads the Leaflet map library and OpenStreetMap tiles."));
    return false;
  }

  function mapView(container, opts) {
    const o = opts || {};
    const box = el("div", "map-view");
    if (o.height) box.style.height = `${o.height}px`;
    container.appendChild(box);
    const map = L.map(box, { preferCanvas: true, zoomSnap: 0.5, scrollWheelZoom: o.scrollZoom !== false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
    }).addTo(map);
    map.setView(o.center || SG_CENTER, o.zoom || 12);
    const view = { map, box, restyle: [] };
    views.add(view);
    if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(box);
    return view;
  }

  function legend(items) {
    const lg = el("div", "legend");
    items.forEach(([label, color, shape]) => {
      const sw = el("i", shape === "dot" ? "dot" : "swatch");
      sw.style.background = color;
      const span = el("span");
      span.appendChild(sw);
      span.appendChild(document.createTextNode(label));
      lg.appendChild(span);
    });
    return lg;
  }

  function landUseLegend(groups) { return legend(groups.map((g, i) => [g, groupColor(i)])); }

  /** Draw a map's roads and building footprints (from /api/maps/<id>/preview) onto a view. */
  function drawPreview(view, data, faint) {
    const renderer = L.canvas({ padding: 0.3 });
    const layer = L.layerGroup().addTo(view.map);
    const aoiLayers = [];
    data.aois.forEach(([g, ring]) => {
      const poly = L.polygon(ring.map(([lng, lat]) => [lat, lng]), {
        renderer, interactive: false, stroke: false, fillOpacity: faint ? 0.18 : 0.5, fillColor: groupColor(g),
      });
      poly._group = g;
      aoiLayers.push(poly);
      layer.addLayer(poly);
    });
    const roads = [];
    data.roads.forEach((line) => {
      const pl = L.polyline(line.map(([lng, lat]) => [lat, lng]), {
        renderer, interactive: false, weight: 1, opacity: faint ? 0.35 : 0.6, color: cssVar("--text-muted"),
      });
      roads.push(pl);
      layer.addLayer(pl);
    });
    view.restyle.push(() => {
      aoiLayers.forEach((p) => p.setStyle({ fillColor: groupColor(p._group) }));
      roads.forEach((r) => r.setStyle({ color: cssVar("--text-muted") }));
    });
    const [s, w, n, e] = data.bbox;
    view.map.fitBounds([[s, w], [n, e]], { padding: [10, 10] });
    return layer;
  }

  async function fetchPreview(mapId) {
    const res = await fetch(`/api/maps/${encodeURIComponent(mapId)}/preview`);
    if (!res.ok) throw new Error("The map preview isn't available yet.");
    return res.json();
  }

  /** Full preview of a map with a land-use legend. */
  async function preview(container, mapId, groups) {
    if (!available(container)) return null;
    const note = el("div", "muted small", "Loading the map…");
    container.appendChild(note);
    const view = mapView(container, { height: 420 });
    try {
      const data = await fetchPreview(mapId);
      drawPreview(view, data, false);
      note.replaceWith(landUseLegend(groups || data.groups));
    } catch (e) { note.textContent = e.message; }
    return view;
  }

  /** Rectangle picker for "build a new area". onChange([minLat, minLon, maxLat, maxLon]) */
  function areaPicker(container, onChange) {
    if (!available(container)) return null;
    const view = mapView(container, { height: 380, zoom: 11 });
    const map = view.map;
    const style = () => ({ color: cssVar("--series-1"), weight: 2, fillOpacity: 0.12, fillColor: cssVar("--series-1") });
    let rect = null;
    let drawing = false;
    let start = null;
    const btn = el("button", "", "Draw an area");
    btn.type = "button";
    btn.addEventListener("click", () => {
      drawing = true;
      map.dragging.disable();
      view.box.classList.add("drawing");
      btn.textContent = "Drag on the map to draw…";
    });
    map.on("mousedown", (e) => {
      if (!drawing) return;
      start = e.latlng;
      if (rect) rect.remove();
      rect = L.rectangle([start, start], style()).addTo(map);
    });
    map.on("mousemove", (e) => { if (drawing && start) rect.setBounds([start, e.latlng]); });
    map.on("mouseup", () => {
      if (!drawing || !start) return;
      drawing = false;
      start = null;
      map.dragging.enable();
      view.box.classList.remove("drawing");
      btn.textContent = "Redraw the area";
      report();
    });
    view.restyle.push(() => { if (rect) rect.setStyle(style()); });
    function report() {
      if (!rect) return;
      const b = rect.getBounds();
      onChange([b.getSouth(), b.getWest(), b.getNorth(), b.getEast()].map((v) => Math.round(v * 1e5) / 1e5));
    }
    return {
      button: btn,
      setBbox(bbox) {
        const bounds = [[bbox[0], bbox[1]], [bbox[2], bbox[3]]];
        if (rect) rect.setBounds(bounds); else rect = L.rectangle(bounds, style()).addTo(map);
        map.fitBounds(bounds, { padding: [20, 20] });
        report();
      },
    };
  }

  /** Homes (dots) and workplaces (rings) of the people in an experiment. */
  function peopleMap(container, people) {
    if (!available(container)) return null;
    const view = mapView(container, { height: 320, scrollZoom: false });
    const layer = L.layerGroup().addTo(view.map);
    function draw(list) {
      layer.clearLayers();
      const pts = [];
      list.forEach((p) => {
        if (!p.home || !p.work) return;
        const hLL = [p.home.lat, p.home.lng];
        const wLL = [p.work.lat, p.work.lng];
        pts.push(hLL, wLL);
        L.polyline([hLL, wLL], { color: cssVar("--text-muted"), weight: 1.5, dashArray: "4 4", interactive: false }).addTo(layer);
        L.circleMarker(hLL, { radius: 7, weight: 2, color: cssVar("--surface-1"), fillColor: cssVar("--series-1"), fillOpacity: 1 })
          .bindTooltip(`${p.name || "Person"} — home, ${p.home.label}`).addTo(layer);
        L.circleMarker(wLL, { radius: 7, weight: 3, color: cssVar("--series-2"), fillColor: cssVar("--surface-1"), fillOpacity: 1 })
          .bindTooltip(`${p.name || "Person"} — work, ${p.work.label}`).addTo(layer);
      });
      if (pts.length) view.map.fitBounds(pts, { padding: [30, 30], maxZoom: 15 });
    }
    draw(people);
    view.restyle.push(() => draw(view._people || people));
    container.appendChild(legend([["Home", cssVar("--series-1"), "dot"], ["Workplace", cssVar("--series-2"), "dot"]]));
    return { update(list) { view._people = list; draw(list); } };
  }

  /** Step-by-step replay of agent positions (from /api/runs/replay). */
  async function replay(container, data) {
    if (!available(container)) return null;
    const frames = data.frames || [];
    const view = mapView(container, { height: 460 });
    if (data.bbox) { // outline of the simulated area; the tiles show the city itself
      const [s, w, n, e] = data.bbox;
      const edge = L.rectangle([[s, w], [n, e]], { color: cssVar("--text-muted"), weight: 1.5, dashArray: "6 6", fill: false, interactive: false }).addTo(view.map);
      view.restyle.push(() => edge.setStyle({ color: cssVar("--text-muted") }));
    }
    if (!frames.length) {
      container.appendChild(el("div", "muted small", "No movement recorded yet. Positions appear after the first simulated step."));
      return view;
    }
    const names = data.names || {};
    const ids = [...new Set(frames.flatMap((f) => f.agents.map((a) => a[0])))];
    const showLabels = ids.length <= 12;
    const markers = {};
    const trails = {};
    const history = {};
    ids.forEach((id) => {
      history[id] = [];
      trails[id] = L.polyline([], { color: cssVar("--text-muted"), weight: 2, opacity: 0.7, dashArray: "3 5", interactive: false }).addTo(view.map);
    });
    frames.forEach((f) => f.agents.forEach(([id, lng, lat]) => history[id].push({ step: f.step, ll: [lat, lng] })));
    const statusColor = (s) => cssVar(s === "moving" ? "--series-2" : "--series-1");
    function show(k) {
      const f = frames[k];
      f.agents.forEach(([id, lng, lat, status]) => {
        const style = { radius: 7, weight: 2, color: cssVar("--surface-1"), fillColor: statusColor(status), fillOpacity: 1 };
        if (!markers[id]) {
          markers[id] = L.circleMarker([lat, lng], style).addTo(view.map);
          markers[id].bindTooltip(names[id] || `Agent ${id}`, showLabels ? { permanent: true, direction: "right", offset: [8, 0], className: "agent-label" } : {});
        } else {
          markers[id].setLatLng([lat, lng]);
          markers[id].setStyle(style);
        }
        markers[id]._status = status;
        trails[id].setLatLngs(history[id].filter((p) => p.step <= f.step).map((p) => p.ll));
      });
      label.textContent = `Step ${k + 1} of ${frames.length} · ${f.t ? new Date(f.t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}`;
      slider.value = k;
    }
    view.restyle.push(() => {
      Object.values(markers).forEach((m) => m.setStyle({ color: cssVar("--surface-1"), fillColor: statusColor(m._status) }));
      Object.values(trails).forEach((t) => t.setStyle({ color: cssVar("--text-muted") }));
    });
    const all = frames.flatMap((f) => f.agents.map((a) => [a[2], a[1]]));
    view.map.fitBounds(all, { padding: [40, 40], maxZoom: 16 });
    // controls
    const controls = el("div", "row replay-controls");
    const play = el("button", "primary", "▶ Play");
    play.type = "button";
    const slider = el("input");
    Object.assign(slider, { type: "range", min: 0, max: frames.length - 1, value: 0 });
    slider.setAttribute("aria-label", "Simulation step");
    const label = el("span", "muted small");
    controls.append(play, slider, label);
    container.appendChild(controls);
    container.appendChild(legend([["At a place (idle)", cssVar("--series-1"), "dot"], ["Travelling", cssVar("--series-2"), "dot"], ["Moves between steps (straight lines)", cssVar("--text-muted")]]));
    let timer = null;
    const stop = () => { clearInterval(timer); timer = null; play.textContent = "▶ Play"; };
    play.addEventListener("click", () => {
      if (timer) return stop();
      if (+slider.value >= frames.length - 1) show(0);
      play.textContent = "❚❚ Pause";
      timer = setInterval(() => {
        if (!document.body.contains(view.box)) return stop(); // navigated away
        const k = +slider.value + 1;
        if (k >= frames.length) return stop();
        show(k);
      }, 700);
    });
    slider.addEventListener("input", () => { stop(); show(+slider.value); });
    show(frames.length - 1);
    view.stop = stop;
    return view;
  }

  // Theme changes (toggle button or system setting): re-read colour tokens; drop views no longer on the page.
  function restyleAll() {
    views.forEach((v) => {
      if (!document.body.contains(v.box)) { views.delete(v); v.map.remove(); return; }
      v.restyle.forEach((fn) => fn());
    });
  }
  new MutationObserver(restyleAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", restyleAll);

  window.StudioMaps = { preview, areaPicker, peopleMap, replay, landUseLegend, available };
})();
