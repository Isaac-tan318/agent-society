/* Minimal SVG charts for AgentSociety Studio: line (<=3 series) and bar, with hover + table view. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }
  function html(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function fmt(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    return Number(v).toFixed(digits === undefined ? 2 : digits);
  }
  function niceTicks(min, max, count) {
    const span = max - min || 1;
    const step0 = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || step0;
    const ticks = [];
    for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(+t.toFixed(10));
    return ticks;
  }
  function frame(container, spec) {
    container.innerHTML = "";
    const wrap = html("div", "chart-block");
    const head = html("div", "row chart-head");
    head.appendChild(html("h3", null, spec.title));
    const toggle = html("button", "link small", "Show table");
    toggle.type = "button";
    head.appendChild(toggle);
    wrap.appendChild(head);
    container.appendChild(wrap);
    return { wrap, toggle };
  }
  function tableToggle(toggle, chartNode, tableNode) {
    tableNode.hidden = true;
    toggle.addEventListener("click", () => {
      const showTable = tableNode.hidden;
      tableNode.hidden = !showTable;
      chartNode.hidden = showTable;
      toggle.textContent = showTable ? "Show chart" : "Show table";
    });
  }

  function lineChart(container, spec) {
    const { wrap, toggle } = frame(container, spec);
    const series = (spec.series || []).slice(0, 3);
    if (series.length > 1) {
      const legend = html("div", "legend");
      series.forEach((s, i) => {
        const item = html("span");
        const sw = html("i");
        sw.style.background = COLORS[i];
        item.appendChild(sw);
        item.appendChild(document.createTextNode(s.name));
        legend.appendChild(item);
      });
      wrap.appendChild(legend);
    }
    // size the SVG to its container so text stays at its nominal pixel size
    const W = Math.max(300, Math.round(wrap.clientWidth || container.clientWidth || 640));
    const H = Math.round(Math.min(300, Math.max(220, W * 0.55)));
    const m = { l: 46, r: W < 460 ? 86 : 116, t: 12, b: 38 };
    const xs = series.flatMap((s) => s.points.map((p) => p[0]));
    const ys = series.flatMap((s) => s.points.map((p) => p[1]));
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const ymin = spec.y_min !== undefined ? spec.y_min : Math.min(0, ...ys);
    const ymax = spec.y_max !== undefined ? Math.max(spec.y_max, ...ys) : Math.max(...ys) * 1.1 || 1;
    const X = (v) => m.l + ((v - xmin) / (xmax - xmin || 1)) * (W - m.l - m.r);
    const Y = (v) => H - m.b - ((v - ymin) / (ymax - ymin || 1)) * (H - m.t - m.b);
    const box = html("div", "chart");
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": spec.title });
    const axis = el("g", { class: "axis" }, svg);
    niceTicks(ymin, ymax, 5).forEach((t) => {
      el("line", { class: "grid-line", x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t) }, axis);
      const tx = el("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end" }, axis);
      tx.textContent = fmt(t, Math.abs(ymax - ymin) < 5 ? 1 : 0);
    });
    el("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }, axis);
    niceTicks(xmin, xmax, Math.min(8, xmax - xmin || 1)).forEach((t) => {
      const tx = el("text", { x: X(t), y: H - m.b + 16, "text-anchor": "middle" }, axis);
      tx.textContent = fmt(t, 0);
    });
    const xl = el("text", { class: "lbl", x: (m.l + W - m.r) / 2, y: H - 4, "text-anchor": "middle" }, svg);
    xl.textContent = spec.x_label || "";
    if (spec.reference && spec.reference.value !== undefined) {
      const ry = Y(spec.reference.value);
      el("line", { x1: m.l, x2: W - m.r, y1: ry, y2: ry, stroke: "var(--text-muted)", "stroke-dasharray": "4 4", "stroke-width": 1 }, svg);
      const rt = el("text", { class: "lbl", x: m.l + 4, y: ry - 5 }, svg);
      rt.textContent = spec.reference.label;
    }
    const endLabels = [];
    series.forEach((s, i) => {
      const d = s.points.map((p, j) => `${j ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
      el("path", { d, fill: "none", stroke: COLORS[i], "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      if (s.points.length <= 30) {
        s.points.forEach((p) => el("circle", { cx: X(p[0]), cy: Y(p[1]), r: 4, fill: COLORS[i], stroke: "var(--surface-1)", "stroke-width": 2 }, svg));
      }
      const last = s.points[s.points.length - 1];
      if (last) endLabels.push({ x: X(last[0]) + 8, y: Y(last[1]) + 4, text: s.name.replace(/ \(.*\)$/, "") });
    });
    // direct labels at line ends, pushed apart so they never overlap
    endLabels.sort((a, b) => a.y - b.y);
    endLabels.forEach((l, k) => { if (k && l.y - endLabels[k - 1].y < 14) l.y = endLabels[k - 1].y + 14; });
    endLabels.forEach((l) => { el("text", { class: "lbl", x: l.x, y: l.y }, svg).textContent = l.text; });
    // hover: crosshair + tooltip
    const cross = el("line", { y1: m.t, y2: H - m.b, stroke: "var(--text-muted)", "stroke-width": 1, visibility: "hidden" }, svg);
    const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
    const tip = html("div", "tip");
    const allX = [...new Set(xs)].sort((a, b) => a - b);
    hit.addEventListener("mousemove", (ev) => {
      const r = svg.getBoundingClientRect();
      const vx = ((ev.clientX - r.left) / r.width) * W;
      const xv = allX.reduce((best, x) => (Math.abs(X(x) - vx) < Math.abs(X(best) - vx) ? x : best), allX[0]);
      cross.setAttribute("x1", X(xv));
      cross.setAttribute("x2", X(xv));
      cross.setAttribute("visibility", "visible");
      tip.innerHTML = "";
      tip.appendChild(html("div", null, `${spec.x_label || "x"} ${fmt(xv, 0)}`)).style.fontWeight = 600;
      series.forEach((s, i) => {
        const p = s.points.find((q) => q[0] === xv);
        if (!p) return;
        const line = html("div");
        const sw = html("i");
        Object.assign(sw.style, { display: "inline-block", width: "10px", height: "3px", background: COLORS[i], marginRight: "6px", verticalAlign: "middle" });
        line.appendChild(sw);
        line.appendChild(document.createTextNode(`${s.name}: ${fmt(p[1])}`));
        tip.appendChild(line);
      });
      tip.style.display = "block";
      const px = ((X(xv) / W) * r.width);
      tip.style.left = `${Math.min(px + 12, r.width - tip.offsetWidth - 4)}px`;
      tip.style.top = "8px";
    });
    hit.addEventListener("mouseleave", () => { tip.style.display = "none"; cross.setAttribute("visibility", "hidden"); });
    box.appendChild(svg);
    box.appendChild(tip);
    wrap.appendChild(box);
    // table view
    const tw = html("div", "table-wrap");
    const table = html("table");
    const hr = html("tr");
    hr.appendChild(html("th", null, spec.x_label || "x"));
    series.forEach((s) => hr.appendChild(html("th", "num", s.name)));
    table.appendChild(hr);
    allX.forEach((x) => {
      const tr = html("tr");
      tr.appendChild(html("td", null, fmt(x, 0)));
      series.forEach((s) => {
        const p = s.points.find((q) => q[0] === x);
        tr.appendChild(html("td", "num", p ? fmt(p[1]) : "–"));
      });
      table.appendChild(tr);
    });
    tw.appendChild(table);
    wrap.appendChild(tw);
    tableToggle(toggle, box, tw);
  }

  function barChart(container, spec) {
    const { wrap, toggle } = frame(container, spec);
    const bars = spec.bars || [];
    const W = Math.max(260, Math.round(wrap.clientWidth || container.clientWidth || 420));
    const H = 230, m = { l: 44, r: 12, t: 22, b: 34 };
    const vals = bars.flatMap((b) => [b.value, b.paper].filter((v) => v !== null && v !== undefined));
    const vmin = Math.min(0, ...vals), vmax = Math.max(0, ...vals) * 1.15 || 1;
    const Y = (v) => H - m.b - ((v - vmin) / (vmax - vmin || 1)) * (H - m.t - m.b);
    const bw = Math.min(64, (W - m.l - m.r) / bars.length - 18);
    const box = html("div", "chart");
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": spec.title });
    const axis = el("g", { class: "axis" }, svg);
    niceTicks(vmin, vmax, 4).forEach((t) => {
      el("line", { class: "grid-line", x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t) }, axis);
      const tx = el("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end" }, axis);
      tx.textContent = fmt(t, vmax - vmin < 5 ? 1 : 0);
    });
    el("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0) }, axis);
    const tip = html("div", "tip");
    const slot = (W - m.l - m.r) / bars.length;
    bars.forEach((b, i) => {
      const cx = m.l + slot * (i + 0.5);
      const y0 = Y(0), y1 = Y(b.value);
      const top = Math.min(y0, y1), h = Math.max(1, Math.abs(y1 - y0));
      const r = Math.min(4, h / 2);
      // rounded data-end, anchored to the baseline
      const up = b.value >= 0;
      const x = cx - bw / 2;
      const d = up
        ? `M${x},${y0} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${y0} Z`
        : `M${x},${y0} V${top + h - r} Q${x},${top + h} ${x + r},${top + h} H${x + bw - r} Q${x + bw},${top + h} ${x + bw},${top + h - r} V${y0} Z`;
      const bar = el("path", { d, fill: COLORS[i % 3] }, svg);
      const vt = el("text", { class: "lbl", x: cx, y: up ? top - 5 : top + h + 13, "text-anchor": "middle" }, svg);
      vt.textContent = fmt(b.value, 1);
      if (b.paper !== null && b.paper !== undefined) {
        el("line", { x1: cx - bw / 2 - 5, x2: cx + bw / 2 + 5, y1: Y(b.paper), y2: Y(b.paper), stroke: "var(--text-primary)", "stroke-width": 2, "stroke-dasharray": "3 3" }, svg);
      }
      const nt = el("text", { class: "lbl", x: cx, y: H - m.b + 16, "text-anchor": "middle" }, svg);
      nt.textContent = b.name;
      const hitArea = el("rect", { x: cx - slot / 2, y: m.t, width: slot, height: H - m.t - m.b, fill: "transparent" }, svg);
      hitArea.addEventListener("mousemove", (ev) => {
        const rr = svg.getBoundingClientRect();
        tip.innerHTML = "";
        tip.appendChild(html("div", null, b.name)).style.fontWeight = 600;
        tip.appendChild(html("div", null, `Simulation: ${fmt(b.value)} ${spec.unit || ""}`));
        if (b.paper !== null && b.paper !== undefined) tip.appendChild(html("div", null, `AS2 paper: ${fmt(b.paper)} ${spec.unit || ""}`));
        tip.style.display = "block";
        tip.style.left = `${Math.min(ev.clientX - rr.left + 12, rr.width - tip.offsetWidth - 4)}px`;
        tip.style.top = `${ev.clientY - rr.top - 10}px`;
        bar.style.filter = "brightness(1.08)";
      });
      hitArea.addEventListener("mouseleave", () => { tip.style.display = "none"; bar.style.filter = ""; });
    });
    box.appendChild(svg);
    box.appendChild(tip);
    if (bars.some((b) => b.paper !== null && b.paper !== undefined)) {
      box.appendChild(html("div", "muted small", "Dashed line = value reported in the AgentSociety 2 paper."));
    }
    wrap.appendChild(box);
    const tw = html("div", "table-wrap");
    const table = html("table");
    const hr = html("tr");
    ["Condition", `Simulation (${spec.unit || ""})`, "AS2 paper"].forEach((t, j) => hr.appendChild(html("th", j ? "num" : null, t)));
    table.appendChild(hr);
    bars.forEach((b) => {
      const tr = html("tr");
      tr.appendChild(html("td", null, b.name));
      tr.appendChild(html("td", "num", fmt(b.value)));
      tr.appendChild(html("td", "num", fmt(b.paper)));
      table.appendChild(tr);
    });
    tw.appendChild(table);
    wrap.appendChild(tw);
    tableToggle(toggle, box, tw);
  }

  window.StudioCharts = { lineChart, barChart };
})();
