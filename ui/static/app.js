/* AgentSociety Studio - single-page UI. Talks only to the local server at /api. */
(function () {
  "use strict";
  const main = document.getElementById("main");
  const state = { page: "home", timers: [], logRun: null, builder: null, lastRuns: [] };

  // ------------------------------------------------------------------ helpers
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "style") Object.assign(n.style, v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      n.appendChild(typeof kid === "string" || typeof kid === "number" ? document.createTextNode(String(kid)) : kid);
    }
    return n;
  }
  async function api(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      const err = new Error((data && (data.error || data.detail)) || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  }
  function toast(msg, kind) {
    const t = document.getElementById("toast");
    t.innerHTML = "";
    const n = h("div", { class: `notice ${kind || ""}`, style: { boxShadow: "var(--shadow)" } }, msg);
    t.appendChild(n);
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.innerHTML = ""; }, kind === "bad" ? 9000 : 5000);
  }
  function clearTimers() { state.timers.forEach(clearInterval); state.timers = []; }
  function every(ms, fn) { const id = setInterval(fn, ms); state.timers.push(id); return id; }
  function fmtTime(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso
      : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  const STATUS = {
    running: ["info", "● Running"], starting: ["info", "● Starting"], completed: ["good", "✓ Completed"],
    failed: ["bad", "✕ Failed"], stopped: ["neutral", "■ Stopped"], interrupted: ["warn", "! Interrupted"],
    incomplete: ["warn", "! Incomplete"], unknown: ["neutral", "? Unknown"],
  };
  function statusBadge(s) {
    const [cls, label] = STATUS[s] || STATUS.unknown;
    return h("span", { class: `badge ${cls}` }, label);
  }
  function progress(run) {
    const pct = run.ticks_total ? Math.min(100, (100 * run.ticks_done) / run.ticks_total) : (run.status === "completed" ? 100 : 0);
    return h("div", { class: "stack", style: { gap: "3px" } },
      h("div", { class: "progress", role: "progressbar", "aria-valuenow": Math.round(pct), "aria-valuemin": 0, "aria-valuemax": 100 },
        h("div", { style: { width: `${pct}%` } })),
      h("span", { class: "muted small" }, run.ticks_total ? `${run.ticks_done} / ${run.ticks_total} simulated steps` : ""));
  }
  function go(page, opts) {
    state.page = page;
    state.opts = opts || {};
    clearTimers();
    document.querySelectorAll("#nav button").forEach((b) => b.setAttribute("aria-current", b.dataset.page === page ? "page" : "false"));
    main.innerHTML = "";
    main.focus({ preventScroll: true });
    (PAGES[page] || PAGES.home)(state.opts);
  }

  // ------------------------------------------------------------------ run launching
  async function launch(experiment, preset, seed, label) {
    try {
      await api("POST", "/api/runs", { experiment, preset, seed });
    } catch (e) {
      if (e.status === 409 && /exists/.test(e.message)) {
        if (!confirm(`${e.message}\n\nOverwrite the previous results for ${label}?`)) return;
        try { await api("POST", "/api/runs", { experiment, preset, seed, overwrite: true }); } catch (e2) { toast(e2.message, "bad"); return; }
      } else { toast(e.message, "bad"); return; }
    }
    toast(`Started: ${label} (${preset}, seed ${seed}). Follow it on the Runs page.`, "good");
    go("runs", { openRun: `${experiment}/runs/${preset}_seed${seed}` });
  }
  async function check(experiment, preset, seed, outNode) {
    outNode.hidden = false;
    outNode.textContent = "Validating configuration (no LLM calls)…";
    try {
      const r = await api("POST", "/api/check", { experiment, preset, seed });
      outNode.textContent = (r.ok ? "✓ Configuration is valid.\n\n" : "✕ Validation failed.\n\n") + r.output;
    } catch (e) { outNode.textContent = `✕ ${e.message}`; }
  }

  // ------------------------------------------------------------------ pages
  const PAGES = {};

  PAGES.home = async function () {
    main.appendChild(h("div", { class: "page-head" },
      h("div", {}, h("h1", { text: "AgentSociety 2 Studio" }),
        h("p", { class: "secondary" }, "Run the AgentSociety 2 paper's experiments and your own simulated societies — no command line or file editing."))));
    const grid = h("div", { class: "grid three" });
    main.appendChild(grid);
    const s = await api("GET", "/api/settings").catch(() => null);
    const llmOk = s && s.api_key_set && s.model;
    grid.appendChild(h("div", { class: "card stack" },
      h("span", { class: "tag", text: "STEP 1" }), h("h3", { text: "Connect a language model" }),
      h("p", { class: "secondary" }, llmOk ? `Configured: ${s.model} via ${s.api_base}` : "Agents think with an LLM. Add an API key first."),
      llmOk ? h("span", { class: "badge good" }, "✓ Configured") : h("span", { class: "badge warn" }, "! Not configured"),
      h("button", { class: llmOk ? "" : "primary", onclick: () => go("settings") }, "Open LLM settings")));
    grid.appendChild(h("div", { class: "card stack" },
      h("span", { class: "tag", text: "STEP 2" }), h("h3", { text: "Try a free test run" }),
      h("p", { class: "secondary" }, "Axelrod's norms game (paper §7.1, 5 generations). Agents are rule-based, so it costs well under a cent and takes about a minute."),
      h("button", { class: "primary", onclick: () => launch("hypothesis_1_social_norms/experiment_1_norms", "smoke", 0, "Norms game smoke test") }, "Run the smoke test")));
    grid.appendChild(h("div", { class: "card stack" },
      h("span", { class: "tag", text: "STEP 3" }), h("h3", { text: "Build your own society" }),
      h("p", { class: "secondary" }, "Describe a few people, then a timeline: let time pass, ask questions, intervene, run surveys."),
      h("button", { onclick: () => go("custom", { new: true }) }, "New experiment")));
    const runsCard = h("div", { class: "card", style: { marginTop: "14px" } }, h("h2", { text: "Recent runs" }));
    main.appendChild(runsCard);
    const runs = await api("GET", "/api/runs").catch(() => []);
    if (!runs.length) runsCard.appendChild(h("p", { class: "muted" }, "No runs yet."));
    else runsCard.appendChild(runsTable(runs.slice(0, 5), true));
  };

  // ---- paper studies
  PAGES.studies = async function () {
    main.appendChild(h("div", { class: "page-head" },
      h("div", {}, h("h1", { text: "Paper studies" }),
        h("p", { class: "secondary" }, "The seven illustrative studies of “AgentSociety 2: An Integrated Research Environment for Executable Social Science” (arXiv 2607.11895). Start with a smoke test; paper scale reproduces the published setup."))));
    const list = h("div", { class: "grid two" });
    main.appendChild(list);
    let studies;
    try { studies = await api("GET", "/api/studies"); } catch (e) { list.appendChild(h("div", { class: "notice bad" }, e.message)); return; }
    studies.forEach((st) => list.appendChild(studyCard(st)));
  };

  function studyCard(st) {
    const blocked = !!st.blocked;
    const badge = blocked
      ? h("span", { class: "badge warn" }, st.experiments.length ? "! Needs data" : "! Not built yet")
      : h("span", { class: "badge good" }, "✓ Ready");
    const card = h("div", { class: "card stack" },
      h("div", { class: "row" }, h("span", { class: "tag", text: `PAPER §${st.section}` }), h("span", { class: "spacer" }), badge),
      h("h2", { text: st.title }),
      h("div", { class: "muted small", text: `Based on ${st.source}` }),
      h("p", { text: st.summary }),
      h("details", {}, h("summary", {}, "What the paper found"), h("p", { class: "secondary small", text: st.paper_finding })));
    if (blocked) card.appendChild(h("div", { class: "notice warn small" }, st.blocked));
    st.experiments.forEach((ex) => card.appendChild(experimentRow(st, ex, blocked)));
    if (st.results) {
      card.appendChild(h("button", { class: "link", onclick: () => go("results", { study: st.id }) }, "View results vs. the paper →"));
    }
    return card;
  }

  function experimentRow(st, ex, blocked) {
    let preset = "smoke";
    const unavailablePaper = st.unavailable && st.unavailable.paper;
    const out = h("pre", { class: "log", hidden: true });
    const cost = h("div", { class: "muted small" });
    const seedInput = h("input", { type: "number", min: 0, max: 9999, value: 0, style: { width: "84px" }, "aria-label": "Seed" });
    const segSmoke = h("button", { type: "button", "aria-pressed": "true" }, "Smoke test");
    const segPaper = h("button", { type: "button", "aria-pressed": "false" }, "Paper scale");
    const warn = h("div", { class: "notice warn small", hidden: true }, unavailablePaper || "");
    const runBtn = h("button", { class: "primary", disabled: blocked }, "Run");
    const checkBtn = h("button", { disabled: blocked }, "Check config (free)");
    function setPreset(p) {
      preset = p;
      segSmoke.setAttribute("aria-pressed", String(p === "smoke"));
      segPaper.setAttribute("aria-pressed", String(p === "paper"));
      cost.textContent = st.cost ? `Estimated: ${st.cost[p]}` : "";
      const na = p === "paper" && !!unavailablePaper;
      warn.hidden = !na;
      runBtn.disabled = blocked || na;
      checkBtn.disabled = blocked || na;
    }
    segSmoke.addEventListener("click", () => setPreset("smoke"));
    segPaper.addEventListener("click", () => setPreset("paper"));
    runBtn.addEventListener("click", () => {
      const seed = parseInt(seedInput.value || "0", 10);
      if (preset === "paper" && !confirm(`Run ${ex.label} at paper scale?\n\n${cost.textContent}\n\nThis uses your LLM API credits.`)) return;
      launch(ex.path, preset, seed, ex.label);
    });
    checkBtn.addEventListener("click", () => check(ex.path, preset, parseInt(seedInput.value || "0", 10), out));
    const last = ex.runs && ex.runs[0];
    const row = h("div", { class: "exp stack", style: { gap: "8px" } },
      h("div", { class: "row" }, h("strong", { text: ex.label }), h("span", { class: "spacer" }),
        last ? h("span", { class: "row small muted", style: { gap: "6px" } }, `last: ${last.name}`, statusBadge(last.status)) : h("span", { class: "muted small" }, "not run yet")),
      h("div", { class: "row" }, h("div", { class: "seg", role: "group", "aria-label": "Scale" }, segSmoke, segPaper),
        st.seeded ? h("label", { style: { flexDirection: "row", alignItems: "center", gap: "6px" } }, "Seed", seedInput) : null,
        h("span", { class: "spacer" }), checkBtn, runBtn),
      cost, warn, out);
    setPreset("smoke");
    return row;
  }

  // ---- runs
  function runsTable(runs, compact) {
    const table = h("table", {},
      h("tr", {}, h("th", {}, "Experiment"), h("th", {}, "Run"), h("th", {}, "Status"), h("th", {}, "Progress"),
        compact ? null : h("th", {}, "Started"), h("th", {}, "")));
    runs.forEach((r) => {
      const actions = h("div", { class: "row", style: { gap: "4px", justifyContent: "flex-end" } },
        h("button", { class: "link", onclick: () => go("runs", { openRun: r.run }) }, "Log"));
      if (r.experiment.startsWith("my_experiments/")) {
        actions.appendChild(h("button", { class: "link", onclick: () => go("results", { run: r.run }) }, r.map ? "Map & answers" : "Answers"));
      } else {
        actions.appendChild(h("button", { class: "link", onclick: () => go("results", { runPath: r.experiment, preset: r.preset, seed: r.seed }) }, "Results"));
      }
      if (!compact) {
        if (r.status === "running" || r.status === "starting") {
          actions.appendChild(h("button", { class: "link danger", onclick: async () => {
            if (!confirm(`Stop ${r.label} (${r.name})?`)) return;
            try { await api("POST", "/api/runs/stop", { run: r.run }); toast("Run stopped.", "good"); refreshRuns(); } catch (e) { toast(e.message, "bad"); }
          } }, "Stop"));
        } else {
          actions.appendChild(h("button", { class: "link danger", onclick: async () => {
            if (!confirm(`Permanently delete the results of ${r.label} (${r.name})?`)) return;
            try { await api("POST", "/api/runs/delete", { run: r.run }); toast("Run deleted.", "good"); refreshRuns(); } catch (e) { toast(e.message, "bad"); }
          } }, "Delete"));
        }
      }
      table.appendChild(h("tr", {},
        h("td", {}, h("div", { text: r.label }), h("div", { class: "muted small", text: r.experiment })),
        h("td", { class: "nowrap", text: r.name }), h("td", {}, statusBadge(r.status), r.error ? h("div", { class: "err", text: r.error }) : null),
        h("td", {}, progress(r)), compact ? null : h("td", { class: "small nowrap", text: fmtTime(r.started) }), h("td", {}, actions)));
    });
    return h("div", { class: "table-wrap" }, table);
  }

  let runsHolder = null;
  async function refreshRuns() {
    if (!runsHolder) return;
    const runs = await api("GET", "/api/runs").catch(() => null);
    if (!runs) return;
    state.lastRuns = runs;
    runsHolder.innerHTML = "";
    runsHolder.appendChild(runs.length ? runsTable(runs, false) : h("div", { class: "empty" }, "No runs yet. Start one from Paper studies or My experiments."));
  }

  PAGES.runs = async function (opts) {
    main.appendChild(h("div", { class: "page-head" },
      h("div", {}, h("h1", { text: "Runs" }), h("p", { class: "secondary" }, "Every simulation you have started. Runs keep going in the background even if you close this tab."))));
    runsHolder = h("div", { class: "card" });
    main.appendChild(runsHolder);
    const logCard = h("div", { class: "card stack", style: { marginTop: "14px" }, hidden: true });
    main.appendChild(logCard);
    await refreshRuns();
    every(3000, refreshRuns);
    if (opts.openRun) openLog(logCard, opts.openRun);
  };

  function openLog(card, run) {
    card.hidden = false;
    card.innerHTML = "";
    let raw = false;
    const title = h("h2", { text: "Log" });
    const info = h("div", { class: "row" });
    const pre = h("pre", { class: "log", text: "Loading…" });
    const rawBtn = h("button", { class: "link small" }, "Show full log");
    rawBtn.addEventListener("click", () => { raw = !raw; rawBtn.textContent = raw ? "Hide noisy lines" : "Show full log"; load(); });
    card.appendChild(h("div", { class: "row" }, title, h("span", { class: "spacer" }), rawBtn));
    card.appendChild(info);
    card.appendChild(pre);
    async function load() {
      try {
        const d = await api("GET", `/api/runs/log?run=${encodeURIComponent(run)}&raw=${raw}`);
        title.textContent = `Log — ${d.run.label} (${d.run.name})`;
        info.innerHTML = "";
        info.appendChild(statusBadge(d.run.status));
        info.appendChild(progress(d.run));
        if (d.run.sim_time) info.appendChild(h("span", { class: "muted small" }, `simulation time ${fmtTime(d.run.sim_time)}`));
        const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
        pre.textContent = d.log || "(no output yet — startup takes about a minute while Ray and the agents initialize)";
        if (atBottom) pre.scrollTop = pre.scrollHeight;
      } catch (e) { pre.textContent = e.message; }
    }
    load();
    every(2500, load);
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---- results
  PAGES.results = async function (opts) {
    main.appendChild(h("div", { class: "page-head" },
      h("div", {}, h("h1", { text: "Results" }), h("p", { class: "secondary" }, "Paper studies are compared with the numbers reported in the AgentSociety 2 paper. Your own experiments show the agents' answers."))));
    const [studies, customs] = await Promise.all([api("GET", "/api/studies").catch(() => []), api("GET", "/api/custom").catch(() => [])]);
    const withResults = studies.filter((s) => s.results);
    const pick = h("select", { "aria-label": "Study or experiment" });
    withResults.forEach((s) => pick.appendChild(h("option", { value: `study:${s.id}` }, `Paper §${s.section} — ${s.title}`)));
    customs.forEach((c) => (c.runs || []).forEach((r) => pick.appendChild(h("option", { value: `run:${r.run}` }, `${r.label} (${r.status})`))));
    const preset = h("select", { "aria-label": "Scale" }, h("option", { value: "paper" }, "Paper scale"), h("option", { value: "smoke" }, "Smoke test"));
    const seed = h("input", { type: "number", min: 0, value: 0, style: { width: "80px" }, "aria-label": "Seed" });
    const seedLabel = h("label", { style: { flexDirection: "row", alignItems: "center", gap: "6px" } }, "Seed", seed);
    const out = h("div", { class: "stack" });
    const loadBtn = h("button", { class: "primary" }, "Show results");
    main.appendChild(h("div", { class: "card row" }, pick, preset, seedLabel, loadBtn));
    main.appendChild(h("div", { style: { height: "14px" } }));
    main.appendChild(out);
    function sync() {
      const isStudy = pick.value.startsWith("study:");
      preset.hidden = !isStudy;
      seedLabel.hidden = !isStudy || ["s1"].includes(pick.value.slice(6));
    }
    pick.addEventListener("change", sync);
    loadBtn.addEventListener("click", () => show());
    async function show() {
      out.innerHTML = "";
      if (!pick.value) { out.appendChild(h("div", { class: "empty" }, "Nothing to show yet.")); return; }
      if (pick.value.startsWith("run:")) return showAnswers(out, pick.value.slice(4));
      const id = pick.value.slice(6);
      out.appendChild(h("div", { class: "muted" }, "Computing results…"));
      try {
        const r = await api("GET", `/api/results/${id}?preset=${preset.value}&seed=${seed.value || 0}`);
        out.innerHTML = "";
        if (r.charts.length) {
          const grid = h("div", { class: "grid two" });
          out.appendChild(grid);  // attach first: charts size themselves to their card
          r.charts.forEach((c) => {
            const box = h("div", { class: "card" });
            grid.appendChild(box);
            (c.type === "bar" ? StudioCharts.barChart : StudioCharts.lineChart)(box, c);
          });
        }
        out.appendChild(h("div", { class: "card stack" }, h("h2", { text: "Detailed comparison with the paper" }),
          h("pre", { class: "log", style: { maxHeight: "none" }, text: r.report || "No output." })));
      } catch (e) { out.innerHTML = ""; out.appendChild(h("div", { class: "notice bad" }, e.message)); }
    }
    // preselect from navigation
    if (opts.study) pick.value = `study:${opts.study}`;
    if (opts.run) pick.value = `run:${opts.run}`;
    if (opts.runPath) {
      const st = studies.find((s) => opts.runPath.startsWith(s.dir));
      if (st && st.results) pick.value = `study:${st.id}`;
      if (opts.preset) preset.value = opts.preset === "paper" ? "paper" : "smoke";
      if (opts.seed !== undefined && opts.seed !== null) seed.value = opts.seed;
    }
    sync();
    if (opts.study || opts.run || opts.runPath) show();
  };

  async function showMovement(out, run) {
    const card = h("div", { class: "card stack" }, h("span", { class: "tag", text: "MOVEMENT" }), h("h3", { text: "Where everyone went" }));
    out.appendChild(card);
    let d;
    try { d = await api("GET", `/api/runs/replay?run=${encodeURIComponent(run)}`); } catch (e) { card.appendChild(h("div", { class: "notice bad small" }, e.message)); return; }
    await StudioMaps.replay(card, d);
    if (!d.frames.length) return;
    const table = h("table", {}, h("tr", {}, h("th", {}, "Person"), h("th", { class: "num" }, "Trips"), h("th", { class: "num", title: "Straight-line distance between the positions recorded at each step" }, "Distance (straight line)"), h("th", {}, "Places, in order")));
    d.trips.forEach((t) => table.appendChild(h("tr", {},
      h("td", { class: "nowrap", text: t.name }), h("td", { class: "num", text: String(t.trips) }),
      h("td", { class: "num nowrap", text: `${t.km.toFixed(1)} km` }), h("td", { class: "small secondary", text: t.places.join(" → ") || "–" }))));
    card.appendChild(h("div", { class: "table-wrap" }, table));
  }

  async function showAnswers(out, run) {
    out.appendChild(h("div", { class: "muted" }, "Loading answers…"));
    try {
      const d = await api("GET", `/api/runs/artifacts?run=${encodeURIComponent(run)}`);
      out.innerHTML = "";
      out.appendChild(h("div", { class: "row" }, h("h2", { text: d.run.label }), statusBadge(d.run.status)));
      if (d.run.map) await showMovement(out, run);
      if (!d.items.length) out.appendChild(h("div", { class: "empty" }, d.run.status === "running" ? "No answers yet — the run is still in progress." : "This run produced no answers."));
      d.items.forEach((it) => {
        if (it.kind === "survey") {
          const qs = h("ul", { class: "small secondary" }, Object.entries(it.questions).map(([k, v]) => h("li", {}, `${k}: ${v}`)));
          const table = h("table", {}, h("tr", {}, h("th", {}, "Agent"), h("th", {}, "Question"), h("th", {}, "Answer"), h("th", {}, "Reason")));
          it.rows.forEach((r) => table.appendChild(h("tr", {}, h("td", { class: "nowrap", text: String(r.agent) }), h("td", { class: "nowrap", text: r.question }), h("td", { class: "nowrap", text: r.answer || "–" }), h("td", { class: "small secondary", text: r.reason || "" }))));
          out.appendChild(h("div", { class: "card stack" }, h("span", { class: "tag", text: "SURVEY" }), h("h3", { text: it.title }), qs, h("div", { class: "table-wrap" }, table)));
        } else {
          out.appendChild(h("div", { class: "card stack" }, h("span", { class: "tag", text: it.kind === "ask" ? "QUESTION" : "INTERVENTION" }),
            h("h3", { text: it.prompt }), h("p", { style: { whiteSpace: "pre-wrap" }, text: it.answer })));
        }
      });
    } catch (e) { out.innerHTML = ""; out.appendChild(h("div", { class: "notice bad" }, e.message)); }
  }

  // ---- custom experiments
  PAGES.custom = async function (opts) {
    if (opts.new || opts.edit) return builder(opts.edit, opts.map);
    main.appendChild(h("div", { class: "page-head" },
      h("div", {}, h("h1", { text: "My experiments" }), h("p", { class: "secondary" }, "Small societies of LLM agents that you design in the browser. Each agent is an AgentSociety 2 PersonAgent in a shared social space where they can message each other, optionally living on a real city map.")),
      h("button", { class: "primary", onclick: () => go("custom", { new: true }) }, "+ New experiment")));
    const list = h("div", { class: "grid two" });
    main.appendChild(list);
    const [items, mapsData] = await Promise.all([api("GET", "/api/custom").catch(() => []), api("GET", "/api/maps").catch(() => ({ maps: [] }))]);
    const mapNames = Object.fromEntries(mapsData.maps.map((m) => [m.id, m.name]));
    if (!items.length) list.appendChild(h("div", { class: "card empty" }, "No experiments yet. Click “New experiment” to design one."));
    items.forEach((x) => {
      const last = x.runs && x.runs[0];
      const out = h("pre", { class: "log", hidden: true });
      const mapNote = x.map ? ` · map: ${mapNames[x.map.id] || `${x.map.id} (missing)`}` : "";
      list.appendChild(h("div", { class: "card stack" },
        h("div", { class: "row" }, h("h2", { text: x.name }), h("span", { class: "spacer" }), last ? statusBadge(last.status) : null),
        x.description ? h("p", { class: "secondary", text: x.description }) : null,
        h("div", { class: "muted small" }, `${(x.agents || []).length} agents · ${(x.steps || []).length} timeline steps · ${(x.runs || []).length} runs${mapNote}`),
        h("div", { class: "row" },
          h("button", { class: "primary", onclick: async () => {
            try { const r = await api("POST", "/api/custom/run", { path: x.path }); toast(`Started ${r.label}.`, "good"); go("runs", { openRun: r.run }); } catch (e) { toast(e.message, "bad"); }
          } }, "Run"),
          h("button", { onclick: () => go("custom", { edit: x.path }) }, "Edit"),
          h("button", { onclick: () => check(x.path, "custom", 0, out) }, "Check"),
          last ? h("button", { onclick: () => go("results", { run: last.run }) }, x.map ? "Latest map & answers" : "Latest answers") : null,
          h("span", { class: "spacer" }),
          h("button", { class: "link danger", onclick: async () => {
            if (!confirm(`Permanently delete “${x.name}” and all of its runs?`)) return;
            try { await api("POST", "/api/custom/delete", { path: x.path }); go("custom"); } catch (e) { toast(e.message, "bad"); }
          } }, "Delete")),
        out));
    });
  };

  const EXAMPLE_AGENTS = [
    { name: "Alice", age: "28", gender: "woman", occupation: "software engineer", personality: "friendly and curious", bio: "Loves hiking and board games; recently moved to the city." },
    { name: "Bob", age: "34", gender: "man", occupation: "data analyst", personality: "reserved and analytical", bio: "Plays chess, reads science fiction, cautious about new ideas." },
    { name: "Carol", age: "45", gender: "woman", occupation: "nurse", personality: "warm, practical, outspoken", bio: "Volunteers at the community center and knows everyone on the street." },
  ];

  async function builder(path, startMap) {
    let spec = { name: "", description: "", start: "2026-01-01T09:00", agents: EXAMPLE_AGENTS.slice(0, 2).map((a) => ({ ...a })),
      steps: [{ type: "run", num_steps: 2, minutes: 60 }, { type: "ask", question: "What has each person been doing, and how do they feel about their neighbors?" }] };
    if (path) {
      try { spec = await api("GET", `/api/custom/get?path=${encodeURIComponent(path)}`); } catch (e) { toast(e.message, "bad"); }
    } else if (startMap) {
      spec.map = { id: startMap };
      spec.start = "2026-01-05T07:00";
      spec.steps = [{ type: "run", num_steps: 6, minutes: 30 },
        { type: "ask", question: "Where did each person go this morning, how did they travel, and why?" }];
    }
    spec.path = path || null;
    const mapsList = await api("GET", "/api/maps").then((d) => d.maps).catch(() => []);
    const readyMaps = mapsList.filter((m) => m.status === "ready");
    main.appendChild(h("div", { class: "page-head" },
      h("div", {}, h("h1", { text: path ? "Edit experiment" : "New experiment" }), h("p", { class: "secondary" }, "Describe the people, then what happens. Nothing here needs code.")),
      h("button", { onclick: () => go("custom") }, "← Back")));
    // basics
    const name = h("input", { value: spec.name || "", placeholder: "e.g. Neighborhood trust" });
    const desc = h("textarea", { placeholder: "What do you want to learn?" });
    desc.value = spec.description || "";
    const start = h("input", { type: "datetime-local", value: (spec.start || "2026-01-01T09:00").slice(0, 16) });
    main.appendChild(h("div", { class: "card stack" }, h("h2", { text: "1. Basics" }),
      h("div", { class: "field-row" }, h("label", {}, "Name", name), h("label", {}, "Simulation starts at", start)),
      h("label", {}, "Description (optional)", desc)));
    // agents
    const agentsBody = h("tbody");
    const agentsCard = h("div", { class: "card stack", style: { marginTop: "14px" } }, h("h2", { text: "2. People (agents)" }),
      h("p", { class: "secondary small" }, "Each person is an LLM agent. Name is required; the rest shapes how they think and act."),
      h("div", { class: "table-wrap" }, h("table", { class: "agent-table" },
        h("thead", {}, h("tr", {}, ["Name", "Age", "Gender", "Occupation", "Personality", "Background", ""].map((t) => h("th", {}, t)))), agentsBody)),
      h("div", { class: "row" },
        h("button", { onclick: () => { spec.agents.push({ name: "", age: "", gender: "", occupation: "", personality: "", bio: "" }); drawAgents(); } }, "+ Add person"),
        h("button", { onclick: () => { const have = new Set(spec.agents.map((a) => a.name)); EXAMPLE_AGENTS.filter((a) => !have.has(a.name)).forEach((a) => spec.agents.push({ ...a })); drawAgents(); } }, "Add example people")));
    main.appendChild(agentsCard);
    function drawAgents() {
      agentsBody.innerHTML = "";
      spec.agents.forEach((a, i) => {
        const cell = (k, attrs) => {
          const inp = k === "bio" ? h("textarea", attrs) : h("input", attrs);
          inp.value = a[k] || "";
          inp.addEventListener("input", () => { a[k] = inp.value; estimate(); });
          return h("td", {}, inp);
        };
        agentsBody.appendChild(h("tr", {}, cell("name", { "aria-label": "Name" }), cell("age", { "aria-label": "Age", style: { width: "60px" } }),
          cell("gender", { "aria-label": "Gender" }), cell("occupation", { "aria-label": "Occupation" }), cell("personality", { "aria-label": "Personality" }),
          cell("bio", { "aria-label": "Background" }),
          h("td", {}, h("button", { class: "link danger", "aria-label": `Remove ${a.name || "person"}`, onclick: () => { spec.agents.splice(i, 1); drawAgents(); } }, "✕"))));
      });
      estimate();
      if (typeof drawMap === "function") drawMap();
    }
    // map
    const mapSel = h("select", { "aria-label": "Map" }, h("option", { value: "" }, "No map — people only message each other"),
      readyMaps.map((m) => h("option", { value: m.id }, m.name)));
    const mapBody = h("div", { class: "stack" });
    main.appendChild(h("div", { class: "card stack", style: { marginTop: "14px" } }, h("h2", { text: "3. Map (optional)" }),
      h("p", { class: "secondary small" }, "Put everyone in a real city: each person gets a home and a workplace, and while time passes they decide where to go and walk or drive along the map's roads."),
      h("label", {}, "Map", mapSel), mapBody));
    const missingMap = spec.map && !readyMaps.some((m) => m.id === spec.map.id);
    mapSel.value = spec.map && !missingMap ? spec.map.id : "";
    const info = (p) => ({ label: p.label, lng: p.lng, lat: p.lat });
    async function place(rows) {
      if (!rows.length) return;
      const people = await api("GET", `/api/maps/${encodeURIComponent(spec.map.id)}/people?n=${rows.length}`);
      rows.forEach((a, i) => {
        a.home = people[i].home.id; a.home_info = info(people[i].home);
        a.work = people[i].work.id; a.work_info = info(people[i].work);
      });
    }
    let drawingMap = null;
    async function drawMap() {
      if (drawingMap) return drawingMap;
      drawingMap = (async () => {
        mapBody.innerHTML = "";
        if (missingMap && !spec.map) {
          mapBody.appendChild(h("div", { class: "notice warn small" }, "This experiment's map is no longer available. Pick another map or run without one."));
        }
        if (!spec.map) {
          if (!readyMaps.length) mapBody.appendChild(h("div", { class: "row" }, h("span", { class: "muted small" }, "You have no maps yet."), h("button", { onclick: () => go("maps") }, "Go to Maps")));
          return;
        }
        const missing = spec.agents.filter((a) => !a.home || !a.work);
        try { await place(missing); } catch (e) { mapBody.appendChild(h("div", { class: "notice bad small" }, e.message)); return; }
        const list = h("div", { class: "place-list" });
        spec.agents.forEach((a) => {
          list.appendChild(h("div", { class: "row" },
            h("span", {}, h("strong", { text: a.name || "(unnamed)" }), h("span", { class: "secondary small" }, ` · home ${a.home_info.label} · work ${a.work_info.label}`)),
            h("button", { class: "link", onclick: async () => { try { await place([a]); drawMap(); } catch (e) { toast(e.message, "bad"); } } }, "Re-roll")));
        });
        const pmBox = h("div", { class: "stack" });
        mapBody.append(
          h("div", { class: "row" },
            h("button", { onclick: async () => { try { await place(spec.agents); drawMap(); } catch (e) { toast(e.message, "bad"); } } }, "Place everyone randomly"),
            h("span", { class: "muted small" }, "Homes are residential buildings; workplaces are offices, shops, schools and other institutions.")),
          list, pmBox,
          h("div", { class: "notice small" }, "Tip: use “Let time pass” steps of 15–30 minutes. Each step, every person decides what to do next (one or more LLM calls), and the replay under Results shows where they went."));
        StudioMaps.peopleMap(pmBox, spec.agents.map((a) => ({ name: a.name, home: a.home_info, work: a.work_info })));
      })();
      try { await drawingMap; } finally { drawingMap = null; }
    }
    mapSel.addEventListener("change", () => {
      spec.map = mapSel.value ? { id: mapSel.value } : null;
      spec.agents.forEach((a) => { delete a.home; delete a.work; delete a.home_info; delete a.work_info; });
      drawMap();
      estimate();
    });
    if (missingMap) spec.map = null;
    // timeline
    const stepsHolder = h("div", { class: "stack" });
    const addMenu = h("div", { class: "row" },
      h("button", { onclick: () => addStep({ type: "run", num_steps: 1, minutes: 60 }) }, "+ Let time pass"),
      h("button", { onclick: () => addStep({ type: "ask", question: "" }) }, "+ Ask the society a question"),
      h("button", { onclick: () => addStep({ type: "intervene", instruction: "" }) }, "+ Intervene"),
      h("button", { onclick: () => addStep({ type: "survey", title: "Survey", questions: [{ prompt: "", response_type: "text", choices: "" }] }) }, "+ Survey everyone"));
    main.appendChild(h("div", { class: "card stack", style: { marginTop: "14px" } }, h("h2", { text: "4. Timeline" }),
      h("p", { class: "secondary small" }, "Steps run top to bottom. “Let time pass” is when agents live and interact; questions and interventions are answered by an AI analyst looking at the society; surveys ask every person directly."),
      stepsHolder, addMenu));
    function addStep(s) { spec.steps.push(s); drawSteps(); }
    function drawSteps() {
      stepsHolder.innerHTML = "";
      if (!spec.steps.length) stepsHolder.appendChild(h("div", { class: "muted" }, "No steps yet."));
      spec.steps.forEach((s, i) => {
        const tools = h("div", { class: "row", style: { gap: "2px" } },
          h("button", { class: "link", disabled: i === 0, "aria-label": "Move up", onclick: () => { [spec.steps[i - 1], spec.steps[i]] = [spec.steps[i], spec.steps[i - 1]]; drawSteps(); } }, "↑"),
          h("button", { class: "link", disabled: i === spec.steps.length - 1, "aria-label": "Move down", onclick: () => { [spec.steps[i + 1], spec.steps[i]] = [spec.steps[i], spec.steps[i + 1]]; drawSteps(); } }, "↓"),
          h("button", { class: "link danger", "aria-label": "Remove step", onclick: () => { spec.steps.splice(i, 1); drawSteps(); } }, "✕"));
        const bind = (node, key, obj) => { node.value = (obj || s)[key] ?? ""; node.addEventListener("input", () => { (obj || s)[key] = node.value; estimate(); }); return node; };
        let body;
        if (s.type === "run") {
          body = h("div", { class: "field-row" },
            h("label", {}, "Number of steps", bind(h("input", { type: "number", min: 1, max: 500 }), "num_steps")),
            h("label", {}, "Minutes per step", bind(h("input", { type: "number", min: 1, max: 1440 }), "minutes")));
        } else if (s.type === "ask") {
          body = h("label", {}, "Question", bind(h("textarea", { placeholder: "e.g. Who trusts whom, and why?" }), "question"));
        } else if (s.type === "intervene") {
          body = h("label", {}, "Instruction", bind(h("textarea", { placeholder: "e.g. Tell everyone a new park opens tomorrow." }), "instruction"));
        } else {
          const qs = h("div", { class: "stack" });
          const drawQs = () => {
            qs.innerHTML = "";
            s.questions.forEach((q, j) => {
              const type = bind(h("select", {}, h("option", { value: "text" }, "Free text"), h("option", { value: "integer" }, "Whole number"),
                h("option", { value: "float" }, "Number"), h("option", { value: "choice" }, "Multiple choice")), "response_type", q);
              const choices = bind(h("input", { placeholder: "Choices, comma-separated" }), "choices", q);
              choices.hidden = q.response_type !== "choice";
              type.addEventListener("change", () => { choices.hidden = type.value !== "choice"; });
              qs.appendChild(h("div", { class: "row" }, h("span", { class: "muted small" }, `Q${j + 1}`),
                bind(h("input", { placeholder: "Question text", style: { flex: "1", minWidth: "220px" } }), "prompt", q), type, choices,
                h("button", { class: "link danger", "aria-label": "Remove question", onclick: () => { s.questions.splice(j, 1); drawQs(); estimate(); } }, "✕")));
            });
          };
          drawQs();
          body = h("div", { class: "stack" }, h("label", {}, "Survey title", bind(h("input", {}), "title")), qs,
            h("button", { class: "link", onclick: () => { s.questions.push({ prompt: "", response_type: "text", choices: "" }); drawQs(); estimate(); } }, "+ Add question"));
        }
        const names = { run: "Let time pass", ask: "Ask the society", intervene: "Intervene", survey: "Survey everyone" };
        stepsHolder.appendChild(h("div", { class: "step-card stack" }, h("div", { class: "row" }, h("strong", { text: `${i + 1}. ${names[s.type]}` }), tools), body));
      });
      estimate();
    }
    // estimate + actions
    const est = h("div", { class: "notice small" });
    function estimate() {
      const n = spec.agents.filter((a) => (a.name || "").trim()).length;
      let calls = 0;
      spec.steps.forEach((s) => {
        if (s.type === "run") calls += n * (parseInt(s.num_steps, 10) || 0) * (spec.map ? 8 : 5);
        else if (s.type === "survey") calls += n * (s.questions || []).length * 3;
        else calls += 10;
      });
      const usd = calls * 0.0008;
      est.textContent = `Rough size: ~${calls} LLM calls ≈ $${usd < 0.01 ? "<0.01" : usd.toFixed(2)} with gpt-4o-mini (stronger models cost 10-30× more), plus about 1 minute of startup.`;
    }
    const out = h("pre", { class: "log", hidden: true });
    async function save() {
      const body = { ...spec, name: name.value.trim(), description: desc.value, start: start.value };
      const saved = await api("POST", "/api/custom", body);
      spec.path = saved.path;
      return saved;
    }
    main.appendChild(h("div", { class: "card stack", style: { marginTop: "14px" } }, est,
      h("div", { class: "row" },
        h("button", { onclick: async () => { try { await save(); toast("Saved.", "good"); } catch (e) { toast(e.message, "bad"); } } }, "Save"),
        h("button", { onclick: async () => { try { const s = await save(); check(s.path, "custom", 0, out); } catch (e) { toast(e.message, "bad"); } } }, "Save & check"),
        h("button", { class: "primary", onclick: async () => {
          try {
            const s = await save();
            const r = await api("POST", "/api/custom/run", { path: s.path });
            toast(`Started ${r.label}.`, "good");
            go("runs", { openRun: r.run });
          } catch (e) { toast(e.message, "bad"); }
        } }, "Save & run")), out));
    drawAgents();
    drawSteps();
    drawMap();
  }

  // ---- maps
  const MAP_STATUS = {
    ready: ["good", "✓ Ready"], preparing: ["info", "● Preparing"], building: ["info", "● Building"],
    copying: ["info", "● Importing"], failed: ["bad", "✕ Failed"], cancelled: ["neutral", "■ Cancelled"],
  };
  const fmtN = (n) => (n ?? 0).toLocaleString();

  PAGES.maps = async function () {
    main.appendChild(h("div", { class: "page-head" },
      h("div", {}, h("h1", { text: "Maps" }),
        h("p", { class: "secondary" }, "City maps for your experiments. People get a home and a workplace on the map, then walk or drive along its real roads while time passes."))));
    const listCard = h("div", { class: "stack" });
    const importCard = h("div", { class: "card stack", style: { marginTop: "14px" } });
    const buildCard = h("div", { class: "card stack", style: { marginTop: "14px" } });
    main.append(listCard, importCard, buildCard);
    const open = new Set(); // map ids whose preview is open
    let data = null;
    let listKey = "";
    let importKey = "";

    async function refresh() {
      const d = await api("GET", "/api/maps").catch((e) => { toast(e.message, "bad"); return null; });
      if (!d) return;
      data = d;
      // Redraw only what changed, so open previews and half-filled forms survive polling.
      const lk = JSON.stringify(d.maps);
      if (lk !== listKey) { listKey = lk; drawList(); }
      const ik = JSON.stringify(d.suggestions);
      if (ik !== importKey) { importKey = ik; drawImport(); }
      if (!d.maps.some((m) => ["building", "preparing", "copying"].includes(m.status))) clearTimers();
    }
    function poll() { clearTimers(); every(3000, refresh); }

    function drawList() {
      listCard.innerHTML = "";
      listCard.appendChild(h("h2", { text: "Your maps" }));
      if (!data.maps.length) {
        listCard.appendChild(h("div", { class: "card empty" }, "No maps yet. Import one or build one below."));
        return;
      }
      const grid = h("div", { class: "grid two" });
      listCard.appendChild(grid);
      data.maps.forEach((m) => {
        const [cls, label] = MAP_STATUS[m.status] || ["neutral", m.status || "?"];
        const c = m.counts;
        const previewBox = h("div", { class: "stack" });
        const card = h("div", { class: "card stack map-card" },
          h("div", { class: "row" }, h("h3", { text: m.name }), h("span", { class: "spacer" }), h("span", { class: `badge ${cls}` }, label)),
          c ? h("div", { class: "secondary small" }, `${fmtN(c.homes)} homes · ${fmtN(c.works)} workplaces · ${fmtN(c.reachable)} reachable of ${fmtN(c.aois)} buildings · ${fmtN(c.roads)} roads · ${fmtN(c.pois)} points of interest`) : null,
          h("div", { class: "muted small" }, m.source === "build" ? `Built from OpenStreetMap${m.area_km2 ? ` (${m.area_km2} km²)` : ""}` : `Imported from ${m.source_path || "a file"}`),
          m.progress && m.status !== "ready" ? h("div", { class: "muted small" }, `${m.progress}…`) : null,
          m.error && m.status !== "ready" ? h("div", { class: "err" }, m.error) : null,
          m.log_tail ? h("details", { open: m.status === "building" }, h("summary", {}, "Build log"), h("pre", { class: "log", text: m.log_tail })) : null,
          (m.used_by || []).length ? h("div", { class: "muted small" }, `Used by: ${m.used_by.join(", ")}`) : null,
          h("div", { class: "row" },
            m.status === "ready" ? h("button", { onclick: () => { open.has(m.id) ? open.delete(m.id) : open.add(m.id); drawList(); } }, open.has(m.id) ? "Hide map" : "Show map") : null,
            m.status === "ready" ? h("button", { onclick: () => go("custom", { new: true, map: m.id }) }, "New experiment on this map") : null,
            m.status === "building" ? h("button", { class: "danger", onclick: async () => {
              if (!confirm(`Cancel building ${m.name}?`)) return;
              try { await api("POST", "/api/maps/cancel", { id: m.id }); refresh(); } catch (e) { toast(e.message, "bad"); }
            } }, "Cancel build") : null,
            h("span", { class: "spacer" }),
            h("button", { class: "link danger", onclick: async () => {
              if (!confirm(`Delete the map ${m.name}? Experiments can't use it afterwards.`)) return;
              try { await api("POST", "/api/maps/delete", { id: m.id }); open.delete(m.id); refresh(); } catch (e) { toast(e.message, "bad"); }
            } }, "Delete")),
          previewBox);
        grid.appendChild(card);
        if (open.has(m.id)) StudioMaps.preview(previewBox, m.id, data.groups);
      });
    }

    function drawImport() {
      importCard.innerHTML = "";
      importCard.appendChild(h("h2", { text: "Import a map" }));
      importCard.appendChild(h("p", { class: "secondary small" }, "Maps are AgentSociety/MOSS .pb files, like the ones AgentSociety 1 builds from OpenStreetMap."));
      (data.suggestions || []).forEach((s) => {
        const nm = h("input", { value: s.name, "aria-label": "Map name" });
        importCard.appendChild(h("div", { class: "notice good row" },
          h("span", {}, h("strong", { text: `Found in your ${s.project} project: ` }), `${s.file} (${s.size_mb} MB)`),
          h("span", { class: "spacer" }), nm,
          h("button", { class: "primary", onclick: async (ev) => {
            ev.target.disabled = true;
            try { await api("POST", "/api/maps/import", { path: s.path, name: nm.value.trim() }); toast("Importing… preparing takes about half a minute.", "good"); await refresh(); poll(); }
            catch (e) { toast(e.message, "bad"); ev.target.disabled = false; }
          } }, "Import")));
      });
      const file = h("input", { type: "file", accept: ".pb", "aria-label": "Map file" });
      const nm = h("input", { placeholder: "Map name", "aria-label": "Map name" });
      const up = h("button", {}, "Import file");
      up.addEventListener("click", async () => {
        const f = file.files && file.files[0];
        if (!f) { toast("Choose a .pb file first.", "bad"); return; }
        up.disabled = true;
        up.textContent = `Uploading ${(f.size / 1e6).toFixed(1)} MB…`;
        try {
          const res = await fetch(`/api/maps/upload?name=${encodeURIComponent(nm.value.trim())}&filename=${encodeURIComponent(f.name)}`,
            { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: f });
          const d = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(d.error || `Upload failed (${res.status})`);
          toast("Imported. Preparing the map…", "good");
          await refresh(); poll();
        } catch (e) { toast(e.message, "bad"); }
        up.disabled = false; up.textContent = "Import file";
      });
      importCard.appendChild(h("div", { class: "row" }, h("span", { class: "secondary small" }, "Or a .pb file from this PC:"), file, nm, up));
    }

    async function drawBuild() {
      buildCard.innerHTML = "";
      buildCard.appendChild(h("h2", { text: "Build a new area from OpenStreetMap" }));
      const status = h("div", { class: "muted small" }, "Checking Docker…");
      buildCard.appendChild(status);
      buildCard.appendChild(h("p", { class: "secondary small" },
        "Uses the map builder from your AgentSociety 1 project (Docker). It downloads the area's roads, buildings and places from OpenStreetMap's public Overpass service, so keep areas modest: a district takes minutes, the whole island tens of minutes and several GB of memory."));
      const presets = h("div", { class: "row" });
      buildCard.appendChild(presets);
      const name = h("input", { placeholder: "e.g. Tiong Bahru", "aria-label": "Map name" });
      const areaText = h("span", { class: "muted small" }, "No area drawn yet.");
      let bbox = null;
      let dockerOk = false;
      const pickerBox = h("div", { class: "stack" });
      const buildBtn = h("button", { class: "primary", disabled: true }, "Build this area");
      buildCard.appendChild(pickerBox);
      buildCard.appendChild(h("div", { class: "row" }, h("label", {}, "Map name", name), areaText, h("span", { class: "spacer" }), buildBtn));
      const picker = StudioMaps.areaPicker(pickerBox, (b) => {
        bbox = b;
        const km2 = Math.abs(b[2] - b[0]) * 111.32 * Math.abs(b[3] - b[1]) * 111.32 * Math.cos(((b[0] + b[2]) / 2) * Math.PI / 180);
        areaText.textContent = `Area ${km2.toFixed(km2 < 10 ? 1 : 0)} km² (${b.map((v) => v.toFixed(4)).join(", ")})`;
        buildBtn.disabled = !dockerOk;
      });
      if (picker) pickerBox.insertBefore(h("div", { class: "row" }, picker.button, h("span", { class: "muted small" }, "Click, then drag a rectangle on the map. Scroll to zoom.")), pickerBox.firstChild);
      async function start(body, label) {
        if (!confirm(`Build ${label}? This downloads OpenStreetMap data and runs the Docker map builder.`)) return;
        try { await api("POST", "/api/maps/build", body); toast("Build started. Follow it under Your maps.", "good"); await refresh(); poll(); }
        catch (e) { toast(e.message, "bad"); }
      }
      buildBtn.addEventListener("click", () => {
        if (!name.value.trim()) { toast("Give the map a name.", "bad"); return; }
        start({ name: name.value.trim(), bbox }, `“${name.value.trim()}”`);
      });
      const d = await api("GET", "/api/maps/docker").catch(() => ({ message: "Couldn't check Docker." }));
      dockerOk = !!(d.daemon && d.image);
      status.className = dockerOk ? "badge good" : "notice warn small";
      status.textContent = dockerOk ? "✓ Docker and the map builder are ready" : d.message;
      Object.entries((data && data.presets) || {}).forEach(([id, p]) => {
        presets.appendChild(h("button", { disabled: !dockerOk, title: p.note, onclick: () => {
          if (picker) picker.setBbox(p.bbox);
          start({ preset: id }, `${p.name} (${p.note})`);
        } }, `Build ${p.name}`));
      });
      buildBtn.disabled = !(dockerOk && bbox);
    }

    await refresh();
    await drawBuild();
    if (data && data.maps.some((m) => ["building", "preparing", "copying"].includes(m.status))) poll();
  };

  // ---- settings
  const PROVIDERS = {
    openrouter: { label: "OpenRouter (one key, many models)", base: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini", hint: "Use OpenRouter model ids, e.g. openai/gpt-4o-mini, openai/gpt-4o, anthropic/claude-3.5-sonnet." },
    openai: { label: "OpenAI", base: "https://api.openai.com/v1", model: "gpt-4o-mini", hint: "Use plain OpenAI model names, e.g. gpt-4o-mini or gpt-4o." },
    ollama: { label: "Local model (Ollama / LM Studio / vLLM)", base: "http://localhost:11434/v1", model: "llama3.1", hint: "Any OpenAI-compatible local server. The key can be any non-empty text." },
    custom: { label: "Other OpenAI-compatible endpoint", base: "", model: "", hint: "The endpoint must speak the OpenAI chat-completions API." },
  };
  PAGES.settings = async function () {
    main.appendChild(h("div", { class: "page-head" },
      h("div", {}, h("h1", { text: "LLM settings" }), h("p", { class: "secondary" }, "The language model that powers the agents. Saved to this project's .env file; the key never leaves this computer except to call your provider."))));
    const s = await api("GET", "/api/settings").catch(() => ({}));
    const provider = h("select", {}, Object.entries(PROVIDERS).map(([k, p]) => h("option", { value: k }, p.label)));
    const base = h("input", { value: s.api_base || "", placeholder: "https://…/v1" });
    const model = h("input", { value: s.model || "", placeholder: "model id" });
    const key = h("input", { type: "password", autocomplete: "off", placeholder: s.api_key_set ? `saved key ${s.api_key_hint} — leave blank to keep it` : "paste your API key" });
    const hint = h("div", { class: "muted small" });
    const result = h("div", { hidden: true });
    const guess = Object.entries(PROVIDERS).find(([, p]) => p.base && s.api_base && s.api_base.startsWith(p.base));
    provider.value = guess ? guess[0] : (s.api_base ? "custom" : "openrouter");
    const syncHint = () => { hint.textContent = PROVIDERS[provider.value].hint; };
    provider.addEventListener("change", () => {
      const p = PROVIDERS[provider.value];
      if (p.base) base.value = p.base;
      if (p.model) model.value = p.model;
      syncHint();
    });
    syncHint();
    if (!s.api_base) provider.dispatchEvent(new Event("change"));
    function show(kind, text) { result.hidden = false; result.className = `notice ${kind}`; result.textContent = text; }
    const testBtn = h("button", {}, "Test connection");
    testBtn.addEventListener("click", async () => {
      testBtn.disabled = true; show("", "Sending one short test message…");
      try {
        const r = await api("POST", "/api/settings/test", { api_base: base.value.trim(), model: model.value.trim(), api_key: key.value.trim() });
        if (r.ok) { show("good", `✓ Connected. The model replied: “${r.reply}”.`); setPill(true, model.value.trim()); }
        else show("bad", `✕ ${r.error}`);
      } catch (e) { show("bad", e.message); }
      testBtn.disabled = false;
    });
    const saveBtn = h("button", { class: "primary" }, "Save");
    saveBtn.addEventListener("click", async () => {
      try {
        const r = await api("POST", "/api/settings", { api_base: base.value.trim(), model: model.value.trim(), api_key: key.value.trim() });
        key.value = ""; key.placeholder = `saved key ${r.api_key_hint} — leave blank to keep it`;
        show("good", "✓ Saved. New runs will use these settings.");
        setPill(r.api_key_set, r.model);
      } catch (e) { show("bad", e.message); }
    });
    main.appendChild(h("div", { class: "card stack", style: { maxWidth: "720px" } },
      h("label", {}, "Provider", provider),
      h("label", {}, "API base URL", base),
      h("label", {}, "Model", model), hint,
      h("label", {}, "API key", key),
      h("div", { class: "row" }, testBtn, saveBtn), result));
    main.appendChild(h("div", { class: "card stack", style: { maxWidth: "720px", marginTop: "14px" } },
      h("h2", { text: "Stop the Studio" }),
      h("p", { class: "secondary small" }, "Shuts down this local server (the window that opened when you started the Studio). Runs already in progress keep going. Start the Studio again from “Start AgentSociety Studio” on your desktop."),
      h("div", {}, h("button", { class: "danger", onclick: async () => {
        if (!confirm("Stop the AgentSociety Studio server?")) return;
        await api("POST", "/api/shutdown").catch(() => null);
        document.body.innerHTML = "";
        document.body.appendChild(h("div", { class: "empty", style: { marginTop: "20vh" } }, "The Studio has stopped. You can close this tab."));
      } }, "Stop the Studio"))));
  };

  // ------------------------------------------------------------------ shell
  function setPill(ok, modelName) {
    const pill = document.getElementById("llm-pill");
    pill.className = `badge ${ok ? "good" : "warn"}`;
    pill.textContent = ok ? `✓ LLM: ${modelName}` : "! LLM not set";
  }
  async function refreshShell() {
    const runs = await api("GET", "/api/runs").catch(() => null);
    if (runs) {
      const active = runs.filter((r) => r.status === "running" || r.status === "starting").length;
      const c = document.getElementById("active-count");
      c.hidden = !active;
      c.textContent = active;
    }
  }
  document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));
  document.getElementById("theme-btn").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("studio-theme", root.dataset.theme); } catch (_) { /* storage unavailable */ }
  });
  try { const t = localStorage.getItem("studio-theme"); if (t) document.documentElement.dataset.theme = t; } catch (_) { /* ignore */ }
  api("GET", "/api/settings").then((s) => setPill(s.api_key_set && !!s.model, s.model)).catch(() => setPill(false));
  refreshShell();
  setInterval(refreshShell, 4000);
  go("home");
})();
