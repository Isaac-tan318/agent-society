"""AgentSociety 2 Studio - local web UI for running AgentSociety 2 without a command line.

Start it by double-clicking "Start AgentSociety Studio.bat" in the project folder.
It serves http://127.0.0.1:8765 (this computer only) and opens the browser.

What it does:
- edits the LLM connection in .env (and tests it with one call),
- runs the AgentSociety 2 paper studies (paper_experiments/) and custom experiments
  built in the browser, as background processes via paper_experiments/run_study.py,
- imports and builds city maps (maps.py) so custom experiments can place people on a
  real road network (MobilitySpace), and replays their movement,
- shows live progress and logs, stops runs, and shows results next to the paper's numbers.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import maps

UI_DIR = Path(__file__).resolve().parent
PROJECT = UI_DIR.parent
WORKSPACE = PROJECT / "paper_experiments"
MY_EXPS = WORKSPACE / "my_experiments"
ENV_FILE = PROJECT / ".env"
LOG_DIR = WORKSPACE / ".studio_logs"
PORT = 8765
PY = sys.executable
IS_WINDOWS = sys.platform == "win32"

# --------------------------------------------------------------------------- studies
# Static description of the seven AS2 paper studies (arXiv 2607.11895, Sec. 7).
STUDIES: list[dict[str, Any]] = [
    {
        "id": "s1", "dir": "hypothesis_1_social_norms", "title": "Emergence of social norms",
        "section": "7.1", "source": "Axelrod (1986), An Evolutionary Approach to Norms",
        "summary": "20 rule-based agents with boldness/vengefulness strategies play Axelrod's Norms and "
                   "Metanorms games for 100 generations (400 steps).",
        "paper_finding": "Metanorms: boldness 3.35 -> 0.15, vengefulness 4.40 -> 6.15. "
                         "Norms: boldness 1.90 -> 0.10, vengefulness 2.90 -> 2.55.",
        "experiments": [("experiment_1_norms", "Norms game"), ("experiment_2_metanorms", "Metanorms game")],
        "cost": {"smoke": "~1 min, < $0.01", "paper": "~4 min per run, < $0.01 (agents are rule-based)"},
        "results": "s1", "seeded": True,
    },
    {
        "id": "s2", "dir": "hypothesis_2_public_goods", "title": "Public goods experiments",
        "section": "7.2", "source": "Fischbacher & Gaechter (2010), AER",
        "summary": "24 LLM participants in six groups of four: strategy-method preference elicitation (P) "
                   "and 10 contribution rounds with beliefs (C), in both orders.",
        "paper_finding": "17/24 incomplete conditional cooperators; mean contribution 8.25 -> 8.04 over "
                         "10 rounds (no sustained free-riding); 70.8% contribute above preference-predicted "
                         "levels in round 10.",
        "experiments": [("experiment_1_p_then_c", "P stage then C stage"), ("experiment_2_c_then_p", "C stage then P stage")],
        "cost": {"smoke": "~3 min, < $0.01", "paper": "~10 min, ~$0.10 per order (gpt-4o-mini)"},
        "results": "s2", "seeded": True,
    },
    {
        "id": "s3", "dir": "hypothesis_3_psych_survey", "title": "Psychological survey (self-bias)",
        "section": "7.3", "source": "Qi et al. (2025), Scientific Data",
        "summary": "Profile-based PersonAgents complete four self-bias tasks: endowment effect, "
                   "self-enhancement, implicit association test and self-reference memory.",
        "paper_finding": "Endowment effect reproduced (WTA 63.3 > WTP 48.4, smaller than humans); mild "
                         "self-deprecation on SE (53.7 vs humans 43.6); no IAT latency effect; no "
                         "self-reference memory advantage.",
        "experiments": [("experiment_1_endowment_effect", "Endowment effect (EE)"),
                        ("experiment_2_self_enhancement", "Self-enhancement (SE)"),
                        ("experiment_3_iat", "Implicit association test (IAT)"),
                        ("experiment_4_self_reference", "Self-reference effect (SRE)")],
        "cost": {"smoke": "~3-6 min each, < $0.05", "paper": "EE/SE ~$1 each, SRE ~$5, IAT ~$50+ (134 agents)"},
        "needs": {"paper": ["hypothesis_3_psych_survey/data/qi2025/profiles.json"]},
        "needs_text": "Paper scale needs the 134 participant profiles from the Qi et al. (2025) OSF dataset "
                      "(DOI 10.17605/OSF.IO/3H95F), converted to data/qi2025/profiles.json.",
        "results": "s3", "seeded": False,
    },
    {
        "id": "s4", "dir": "hypothesis_4_information_cocoon", "title": "Emergence of information cocoons",
        "section": "7.4", "source": "Shang et al. (2025) short-video dataset",
        "summary": "10,000 rule-based users and a DIN recommender over 86k short videos for ~6 months.",
        "paper_finding": "Viewing entropy falls for all ages; older users fall into deeper cocoons; three "
                         "quota-reranking strategies reduce deep cocoons for users 50+.",
        "experiments": [],
        "blocked": "Not built yet: needs the ShortVideo dataset download and PyTorch (for the DIN recommender).",
        "results": None, "seeded": False,
    },
    {
        "id": "s5", "dir": "hypothesis_5_polarization", "title": "Mechanisms behind opinion polarization",
        "section": "7.5", "source": "Levy (2021), AER",
        "summary": "200 liberal/conservative news users over 8 weeks: control vs. pro- vs. "
                   "counter-attitudinal outlet subscription offers, with an algorithmically ranked feed.",
        "paper_finding": "Counter offers raise cross-cutting exposure (35.7% vs 28.7%) and reading "
                         "(4.15 vs 1.65 posts) and cut the rise in affective polarization (1.28 vs 2.36); "
                         "issue opinions barely move.",
        "experiments": [("experiment_1_control", "Control"), ("experiment_2_pro_attitudinal", "Pro-attitudinal offer"),
                        ("experiment_3_counter_attitudinal", "Counter-attitudinal offer")],
        "cost": {"smoke": "~4 min, < $0.02", "paper": "~20-40 min, ~$1 per condition (gpt-4o-mini)"},
        "results": "s5", "seeded": True,
    },
    {
        "id": "s6", "dir": "hypothesis_6_daily_mobility", "title": "Daily mobility simulation",
        "section": "7.6", "source": "DailyMobility benchmark (Beijing)",
        "summary": "100 PersonAgents plan and travel through one weekday on the Beijing road network.",
        "paper_finding": "Best intention-sequence JSD of all methods (0.138); weaker spatial realism "
                         "(gyration radius JSD 0.598).",
        "experiments": [("experiment_1_beijing_day", "One weekday in Beijing")],
        "blocked": "Needs the benchmark's Beijing map (beijing.pb, 168 MB) and resident profiles from the "
                   "HuggingFace dataset tsinghua-fib-lab/daily-mobility-generation-benchmark, placed in "
                   "paper_experiments/data/mobility/. (Routing itself now works on Windows.)",
        "results": None, "seeded": False,
    },
    {
        "id": "s7", "dir": "hypothesis_7_disaster_mobility", "title": "Disaster mobility simulation",
        "section": "7.7", "source": "SafeGraph mobility, 2021 Texas Winter Storm / 2018 Camp Fire",
        "summary": "100 residents over 11 days (hourly) while official broadcasts follow each disaster's phases.",
        "paper_finding": "Normalized daily mobility tracks the empirical curve; phase RMSE 0.0073-0.0188.",
        "experiments": [("experiment_1_texas_winter_storm", "2021 Texas Winter Storm"), ("experiment_2_camp_fire", "2018 Camp Fire")],
        "blocked": "Needs a city map and resident profiles in paper_experiments/data/disaster/; the paper's "
                   "Houston map and SafeGraph mobility series are not public. (Routing itself now works on Windows.)",
        "results": None, "seeded": False,
    },
]

app = FastAPI(title="AgentSociety 2 Studio")
app.add_middleware(GZipMiddleware, minimum_size=2000)  # map previews and replays are a few MB of JSON
RUNS: dict[str, dict[str, Any]] = {}  # runs launched by this server process
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_NOISE = re.compile(r"not in built-in cost map|\(raylet\)|job_logging_config|client_mode_hook|"
                    r"Stack \(most recent call first\)|PydanticDeprecatedSince20|disconnect\n?$")


# --------------------------------------------------------------------------- helpers
def _read_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if m and not line.lstrip().startswith("#"):
                vals[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return vals


def _write_env(updates: dict[str, str]) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.is_file() else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if m and not line.lstrip().startswith("#") and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            done.add(m.group(1))
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _exp_dir(rel: str) -> Path:
    """Resolve an experiment path given relative to the workspace, refusing anything outside it."""
    p = (WORKSPACE / rel).resolve()
    try:
        p.relative_to(WORKSPACE)
    except ValueError:
        raise HTTPException(400, "invalid experiment path") from None
    if not (p / "init").is_dir():
        raise HTTPException(404, f"no experiment at {rel}")
    return p


def _run_dir(rel: str) -> Path:
    p = (WORKSPACE / rel).resolve()
    try:
        p.relative_to(WORKSPACE)
    except ValueError:
        raise HTTPException(400, "invalid run path") from None
    if p.parent.name != "runs" or not p.is_dir():
        raise HTTPException(404, "run not found")
    return p


def _rel(p: Path) -> str:
    return p.resolve().relative_to(WORKSPACE).as_posix()


def _json(p: Path, default: Any = None) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _tail(p: Path, max_bytes: int = 60000) -> str:
    if not p.is_file():
        return ""
    with open(p, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        text = f.read().decode("utf-8", "replace")
    return _ANSI.sub("", text)


def _clean_log(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _NOISE.search(line))


def _steps_totals(steps_path: Path) -> dict[str, int]:
    data = yaml.safe_load(steps_path.read_text(encoding="utf-8")) or {}
    steps = data.get("steps", [])
    return {"ticks": sum(int(s.get("num_steps", 0)) for s in steps if s.get("type") == "run"),
            "top_steps": len(steps)}


def _kill_tree(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass


def _friendly_error(err: Optional[str]) -> Optional[str]:
    """Turn a raw exception dump (ANSI codes, Ray actor reprs) into one readable line."""
    if not err:
        return None
    text = _ANSI.sub("", err)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if re.match(r"^[A-Za-z_.]*(Error|Exception)", ln):
            return ln[:240]
    return (lines[-1] if lines else text)[:240]


def _run_info(run_dir: Path) -> dict[str, Any]:
    meta = _json(run_dir / "studio_meta.json", {}) or {}
    pid = _json(run_dir / "pid.json", {}) or {}
    active = next((r for r in RUNS.values() if r["run_dir"] == run_dir and r["proc"].poll() is None), None)
    status = pid.get("status", "starting" if active else "unknown")
    if active:
        status = "running"
    elif meta.get("stopped"):
        status = "stopped"
    elif status == "running":
        status = "interrupted"  # pid.json says running but no process is alive
    total = int(meta.get("total_ticks") or 0)
    done = int(pid.get("step_count") or 0)
    if status == "completed" and total and done < total:
        status = "incomplete"
    exp_dir = run_dir.parent.parent
    m = re.match(r"(smoke|paper|custom)_seed(\d+)$", run_dir.name)  # runs made before the Studio have no meta
    return {
        "run": _rel(run_dir), "experiment": _rel(exp_dir), "name": run_dir.name,
        "label": meta.get("label") or _experiment_label(exp_dir),
        "preset": meta.get("preset") or (m.group(1) if m else None),
        "seed": meta.get("seed") if meta.get("seed") is not None else (int(m.group(2)) if m else None),
        "status": status,
        "ticks_done": done, "ticks_total": total,
        "started": meta.get("started") or pid.get("start_time"), "ended": pid.get("end_time"),
        "error": _friendly_error(pid.get("error")), "sim_time": pid.get("simulation_time"),
        "map": meta.get("map"),
    }


def _all_runs() -> list[dict[str, Any]]:
    out = [_run_info(p.parent) for p in WORKSPACE.glob("**/runs/*/studio_meta.json")]
    seen = {r["run"] for r in out}
    out += [_run_info(p.parent) for p in WORKSPACE.glob("**/runs/*/pid.json") if _rel(p.parent) not in seen]
    return sorted(out, key=lambda r: r.get("started") or "", reverse=True)


def _experiment_label(exp_dir: Path) -> str:
    for s in STUDIES:
        for eid, label in s["experiments"]:
            if exp_dir == WORKSPACE / s["dir"] / eid:
                return f"{s['title']} - {label}"
    meta = _json(exp_dir / "experiment.json", {}) or {}
    return meta.get("name") or exp_dir.name


# --------------------------------------------------------------------------- settings
@app.get("/api/settings")
def get_settings() -> dict:
    env = _read_env()
    key = env.get("AGENTSOCIETY_LLM_API_KEY", "")
    return {"api_base": env.get("AGENTSOCIETY_LLM_API_BASE", ""), "model": env.get("AGENTSOCIETY_LLM_MODEL", ""),
            "api_key_set": bool(key), "api_key_hint": ("..." + key[-4:]) if len(key) > 4 else ""}


@app.post("/api/settings")
def save_settings(body: dict = Body(...)) -> dict:
    updates = {}
    for field, var in (("api_base", "AGENTSOCIETY_LLM_API_BASE"), ("model", "AGENTSOCIETY_LLM_MODEL")):
        v = str(body.get(field, "")).strip()
        if not v:
            raise HTTPException(400, f"{field} is required")
        if field == "api_base" and v.rstrip("/").endswith("/chat/completions"):
            raise HTTPException(400, "Remove '/chat/completions' from the API base - it is added automatically.")
        updates[var] = v
    key = str(body.get("api_key", "")).strip()
    if key:
        updates["AGENTSOCIETY_LLM_API_KEY"] = key
    elif not _read_env().get("AGENTSOCIETY_LLM_API_KEY"):
        raise HTTPException(400, "an API key is required")
    _write_env(updates)
    return get_settings()


def _test_llm(base: str, model: str, key: str) -> dict:
    import litellm

    try:
        r = litellm.completion(model=f"openai/{model}", api_base=base, api_key=key, max_tokens=5,
                               messages=[{"role": "user", "content": "Reply with exactly: ok"}], timeout=45)
        return {"ok": True, "reply": (r.choices[0].message.content or "").strip()}
    except Exception as exc:  # report the provider's message, never the key
        msg = str(exc).replace(key, "***") if key else str(exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {msg[:400]}"}


@app.post("/api/settings/test")
async def test_settings(body: dict = Body(default={})) -> dict:
    env = _read_env()
    base = str(body.get("api_base") or env.get("AGENTSOCIETY_LLM_API_BASE", "")).strip()
    model = str(body.get("model") or env.get("AGENTSOCIETY_LLM_MODEL", "")).strip()
    key = str(body.get("api_key") or env.get("AGENTSOCIETY_LLM_API_KEY", "")).strip()
    if not (base and model and key):
        return {"ok": False, "error": "API base, model and key are all required."}
    return await asyncio.to_thread(_test_llm, base, model, key)


# --------------------------------------------------------------------------- studies
@app.get("/api/studies")
def list_studies() -> list[dict]:
    runs = _all_runs()
    out = []
    for s in STUDIES:
        s2 = {k: v for k, v in s.items() if k != "needs"}
        missing = {preset: [f for f in files if not (WORKSPACE / f).is_file()]
                   for preset, files in s.get("needs", {}).items()}
        s2["unavailable"] = {p: s.get("needs_text", "missing data") for p, m in missing.items() if m}
        s2["experiments"] = [{"path": f"{s['dir']}/{eid}", "label": label,
                              "runs": [r for r in runs if r["experiment"] == f"{s['dir']}/{eid}"]}
                             for eid, label in s["experiments"]]
        out.append(s2)
    return out


# --------------------------------------------------------------------------- runs
def _launch(exp_dir: Path, preset: str, seed: int, label: str) -> dict:
    run_dir = exp_dir / "runs" / f"{preset}_seed{seed}"
    # Generate configs now so the run dir gets a provenance snapshot and progress totals.
    gen = exp_dir / "init" / "config_params.py"
    if gen.is_file():
        proc = subprocess.run([PY, str(gen), "--preset", preset, "--seed", str(seed)], cwd=str(exp_dir),
                              capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            raise HTTPException(400, (proc.stdout + proc.stderr).strip()[-1500:] or "config generation failed")
    run_dir.mkdir(parents=True, exist_ok=True)
    snap = run_dir / "run_config"
    snap.mkdir(exist_ok=True)
    for f in ("init_config.json", "steps.yaml"):
        shutil.copy2(exp_dir / "init" / f, snap / f)
    totals = _steps_totals(exp_dir / "init" / "steps.yaml")
    meta = {"label": label, "preset": preset, "seed": seed, "started": datetime.now().isoformat(timespec="seconds"),
            "total_ticks": totals["ticks"], "total_steps": totals["top_steps"],
            "map": _map_of(_json(exp_dir / "init" / "init_config.json", {}) or {})}
    (run_dir / "studio_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    console = run_dir / "console.log"
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if IS_WINDOWS else 0
    with open(console, "w", encoding="utf-8") as out:
        proc = subprocess.Popen([PY, str(WORKSPACE / "run_study.py"), str(exp_dir), "--preset", preset,
                                 "--seed", str(seed)], cwd=str(WORKSPACE), stdout=out, stderr=subprocess.STDOUT,
                                env=env, creationflags=flags, start_new_session=not IS_WINDOWS)
    RUNS[_rel(run_dir)] = {"proc": proc, "run_dir": run_dir.resolve(), "started": time.time()}
    return _run_info(run_dir)


@app.post("/api/runs")
async def start_run(body: dict = Body(...)) -> dict:
    exp_dir = _exp_dir(str(body.get("experiment", "")))
    preset = str(body.get("preset", "smoke"))
    if preset not in ("smoke", "paper", "custom"):
        raise HTTPException(400, "preset must be smoke, paper or custom")
    seed = int(body.get("seed", 0))
    if not 0 <= seed <= 9999:
        raise HTTPException(400, "seed must be between 0 and 9999")
    run_dir = exp_dir / "runs" / f"{preset}_seed{seed}"
    if any(r["run_dir"] == run_dir.resolve() and r["proc"].poll() is None for r in RUNS.values()):
        raise HTTPException(409, "This run is already in progress.")
    if run_dir.exists():
        if not body.get("overwrite"):
            raise HTTPException(409, f"A previous run {preset}_seed{seed} exists. Overwrite it, or pick another seed.")
        shutil.rmtree(run_dir, ignore_errors=True)
    return await asyncio.to_thread(_launch, exp_dir, preset, seed, _experiment_label(exp_dir))


@app.post("/api/check")
async def check_experiment(body: dict = Body(...)) -> dict:
    exp_dir = _exp_dir(str(body.get("experiment", "")))
    preset = str(body.get("preset", "smoke"))
    cmd = [PY, str(WORKSPACE / "run_study.py"), str(exp_dir), "--preset", preset, "--seed",
           str(int(body.get("seed", 0))), "--check"]
    flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
    proc = await asyncio.to_thread(subprocess.run, cmd, cwd=str(WORKSPACE), capture_output=True, text=True,
                                   timeout=300, creationflags=flags,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    text = _clean_log(_ANSI.sub("", proc.stdout + proc.stderr))
    lines = [ln for ln in text.splitlines() if not re.search(r"\] INFO ", ln)]
    return {"ok": proc.returncode == 0 and "CHECK PASSED" in text, "output": "\n".join(lines[-40:])}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return _all_runs()


@app.get("/api/runs/log")
def run_log(run: str, raw: bool = False) -> dict:
    run_dir = _run_dir(run)
    text = _tail(run_dir / "console.log") or _tail(run_dir / "output.log")
    return {"run": _run_info(run_dir), "log": text if raw else _clean_log(text)}


@app.post("/api/runs/stop")
def stop_run(body: dict = Body(...)) -> dict:
    run_dir = _run_dir(str(body.get("run", "")))
    meta = _json(run_dir / "studio_meta.json", {}) or {}
    for r in RUNS.values():
        if r["run_dir"] == run_dir and r["proc"].poll() is None:
            _kill_tree(r["proc"].pid)
    meta["stopped"] = True
    (run_dir / "studio_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return _run_info(run_dir)


@app.post("/api/runs/delete")
def delete_run(body: dict = Body(...)) -> dict:
    run_dir = _run_dir(str(body.get("run", "")))
    if any(r["run_dir"] == run_dir and r["proc"].poll() is None for r in RUNS.values()):
        raise HTTPException(409, "Stop the run before deleting it.")
    shutil.rmtree(run_dir, ignore_errors=True)
    return {"deleted": _rel(run_dir) if run_dir.exists() else True}


@app.get("/api/runs/artifacts")
def run_artifacts(run: str) -> dict:
    run_dir = _run_dir(run)
    names = {a["agent_id"]: a["kwargs"].get("name", f"Agent {a['agent_id']}")
             for a in (_json(run_dir / "run_config" / "init_config.json", {}) or {}).get("agents", [])}
    items = []
    for f in sorted((run_dir / "artifacts").glob("*")):
        if f.suffix == ".md":
            text = f.read_text(encoding="utf-8")
            m = re.match(r"---\n(.*?)\n---\n\n?(.*)", text, re.DOTALL)
            header = yaml.safe_load(m.group(1)) if m else {}
            kind = "ask" if f.name.startswith("ask") else "intervene"
            items.append({"file": f.name, "kind": kind,
                          "prompt": (header or {}).get("question") or (header or {}).get("instruction", ""),
                          "answer": (m.group(2) if m else text).strip()})
        elif f.suffix == ".json" and f.name.startswith("questionnaire"):
            d = _json(f, {}) or {}
            rows = []
            for resp in d.get("responses", []):
                for a in resp.get("answers", []):
                    rows.append({"agent": resp.get("agent_name") or names.get(resp.get("agent_id")) or resp.get("agent_id"),
                                 "question": a.get("question_id"), "answer": a.get("raw_text"),
                                 "reason": a.get("reason")})
            prompts = {q["id"]: q["prompt"] for q in d.get("questions", [])}
            items.append({"file": f.name, "kind": "survey", "title": d.get("title") or d.get("questionnaire_id"),
                          "questions": prompts, "rows": rows})
    return {"run": _run_info(run_dir), "items": items}


def _map_of(init: dict) -> Optional[str]:
    """Map id of a Studio map used by a config's MobilitySpace (file_path maps/<id>/map.pb), if any."""
    for m in init.get("env_modules", []):
        if m.get("module_type") == "MobilitySpace":
            fp = str((m.get("kwargs") or {}).get("file_path", "")).replace("\\", "/")
            hit = re.search(r"(?:^|/)maps/([a-z0-9_]+)/map\.pb$", fp)
            return hit.group(1) if hit else "external"
    return None


def _km(a: list, b: list) -> float:
    (lng1, lat1), (lng2, lat2) = a, b
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6371.0 * math.hypot(x, math.radians(lat2 - lat1))


@app.get("/api/runs/replay")
def run_replay(run: str) -> dict:
    """Per-step agent positions of a MobilitySpace run (replay/mobility_agent_state.*.jsonl)."""
    run_dir = _run_dir(run)
    init = _json(run_dir / "run_config" / "init_config.json", {}) or {}
    map_id = _map_of(init)
    if map_id is None:
        raise HTTPException(404, "This run has no map.")
    names = {a["agent_id"]: a["kwargs"].get("name", f"Agent {a['agent_id']}") for a in init.get("agents", [])}
    frames: dict[int, dict] = {}
    for f in (run_dir / "replay").glob("mobility_agent_state.*.jsonl"):
        for r in _jsonl(f):
            fr = frames.setdefault(int(r["step"]), {"step": int(r["step"]), "t": r.get("t"), "agents": []})
            fr["agents"].append([r["agent_id"], round(r["lng"], 6), round(r["lat"], 6), r.get("status"), r.get("aoi_id")])
    ordered = [frames[k] for k in sorted(frames)]
    labels = maps.place_index(map_id) if map_id != "external" and (maps.MAPS / map_id).is_dir() else {}
    # A trip = arriving at a different place than the last one. (Trips usually finish within one step, so
    # "moving" is rarely seen at step boundaries.) Distance is straight-line between step positions.
    trips = {aid: {"agent": aid, "name": name, "trips": 0, "km": 0.0, "places": []} for aid, name in names.items()}
    last: dict[int, list] = {}
    last_aoi: dict[int, Any] = {}
    for fr in ordered:
        for aid, lng, lat, status, aoi in fr["agents"]:
            t = trips.setdefault(aid, {"agent": aid, "name": names.get(aid, f"Agent {aid}"), "trips": 0, "km": 0.0, "places": []})
            if aid in last:
                t["km"] += _km(last[aid], [lng, lat])
            if status == "idle" and aoi is not None:
                if aid in last_aoi and last_aoi[aid] != aoi:
                    t["trips"] += 1
                last_aoi[aid] = aoi
                place = (labels.get(aoi) or {}).get("label") or f"building {aoi}"
                if not t["places"] or t["places"][-1] != place:
                    t["places"].append(place)
            last[aid] = [lng, lat]
    for t in trips.values():
        t["km"] = round(t["km"], 2)
    bbox = None
    if map_id != "external":
        try:
            bbox = maps.get_map(map_id).get("bbox")
        except (KeyError, ValueError):
            pass
    return {"run": _run_info(run_dir), "map_id": map_id, "bbox": bbox,
            "names": {str(k): v for k, v in names.items()}, "frames": ordered, "trips": list(trips.values())}


# --------------------------------------------------------------------------- maps
def _maps_in_use() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for f in MY_EXPS.glob("*/experiment.json"):
        meta = _json(f, {}) or {}
        mid = (meta.get("map") or {}).get("id")
        if mid:
            used.setdefault(mid, []).append(meta.get("name") or f.parent.name)
    return used


def _map_or_404(map_id: str) -> dict:
    try:
        return maps.get_map(map_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "map not found") from None


@app.get("/api/maps")
def list_maps() -> dict:
    used = _maps_in_use()
    return {"maps": [{**m, "used_by": used.get(m["id"], [])} for m in maps.list_maps()],
            "suggestions": maps.suggestions(), "presets": maps.PRESETS, "groups": maps.LAND_USE_GROUPS}


@app.get("/api/maps/docker")
async def maps_docker() -> dict:
    return await asyncio.to_thread(maps.docker_status)


@app.post("/api/maps/import")
def import_map(body: dict = Body(...)) -> dict:
    path = str(body.get("path", ""))
    if path not in {s["path"] for s in maps.suggestions()}:  # arbitrary files go through the upload endpoint
        raise HTTPException(400, "That map file is no longer available to import.")
    try:
        return maps.import_path(path, str(body.get("name", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/maps/upload")
async def upload_map(request: Request, name: str = "", filename: str = "") -> dict:
    try:
        mid, target = maps.begin_upload(name, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    size = 0
    try:
        with open(target, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > maps.MAX_UPLOAD:
                    raise ValueError("That file is larger than 2 GB.")
                out.write(chunk)
        if size == 0:
            raise ValueError("The file is empty.")
    except Exception as exc:
        maps.abort_upload(mid)
        raise HTTPException(400, str(exc)) from None
    return maps.finish_upload(mid)


@app.post("/api/maps/build")
async def build_map(body: dict = Body(...)) -> dict:
    preset = body.get("preset")
    if preset:
        p = maps.PRESETS.get(str(preset))
        if not p:
            raise HTTPException(400, "unknown preset")
        bbox, name = p["bbox"], str(body.get("name") or p["name"])
    else:
        bbox, name = body.get("bbox"), str(body.get("name") or "").strip()
        if not (isinstance(bbox, list) and len(bbox) == 4):
            raise HTTPException(400, "Draw the area on the map first.")
        if not name:
            raise HTTPException(400, "Give the map a name.")
    try:
        return await asyncio.to_thread(maps.build, name, bbox, preset)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/maps/cancel")
def cancel_map(body: dict = Body(...)) -> dict:
    _map_or_404(str(body.get("id", "")))
    return maps.cancel(str(body["id"]))


@app.post("/api/maps/delete")
def delete_map(body: dict = Body(...)) -> dict:
    map_id = str(body.get("id", ""))
    _map_or_404(map_id)
    users = _maps_in_use().get(map_id)
    if users:
        raise HTTPException(409, f"Used by {', '.join(users)}. Remove the map from those experiments first.")
    try:
        maps.delete(map_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"deleted": map_id}


@app.get("/api/maps/{map_id}/preview")
def map_preview(map_id: str) -> FileResponse:
    _map_or_404(map_id)
    p = maps.map_dir(map_id) / "preview.json"
    if not p.is_file():
        raise HTTPException(404, "The map is still being prepared.")
    return FileResponse(p, media_type="application/json")


@app.get("/api/maps/{map_id}/people")
def map_people(map_id: str, n: int = 1, seed: Optional[int] = None) -> list[dict]:
    if _map_or_404(map_id).get("status") != "ready":
        raise HTTPException(409, "The map isn't ready yet.")
    try:
        return maps.sample_people(map_id, n, seed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


# --------------------------------------------------------------------------- results
def _analysis(script: Path, args: list[str]) -> str:
    flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
    proc = subprocess.run([PY, str(script), *args], cwd=str(script.parent), capture_output=True, text=True,
                          timeout=300, creationflags=flags, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return (proc.stdout + ("\n" + proc.stderr if proc.returncode else "")).strip()


def _jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _s1_series(preset: str) -> list[dict]:
    """Mean boldness / vengefulness per generation, averaged over complete seeds."""
    charts = []
    expected = {"paper": 400, "smoke": 20}.get(preset, 0)
    series: dict[str, dict[str, list]] = {"boldness": {}, "vengefulness": {}}
    for eid, label in (("experiment_1_norms", "Norms"), ("experiment_2_metanorms", "Metanorms")):
        per_gen: dict[int, dict[str, list]] = {}
        n_runs = 0
        for f in (WORKSPACE / "hypothesis_1_social_norms" / eid / "runs").glob(f"{preset}_seed*/env/NormsGameEnv/norms_timeseries.jsonl"):
            rows = _jsonl(f)
            if expected and len(rows) < expected:
                continue
            n_runs += 1
            for r in rows:
                if r.get("reproduced"):
                    g = per_gen.setdefault(r["generation"], {"b": [], "v": []})
                    g["b"].append(r["mean_boldness"])
                    g["v"].append(r["mean_vengefulness"])
        if per_gen:
            gens = sorted(per_gen)
            series["boldness"][f"{label} ({n_runs} runs)"] = [[g, sum(per_gen[g]["b"]) / len(per_gen[g]["b"])] for g in gens]
            series["vengefulness"][f"{label} ({n_runs} runs)"] = [[g, sum(per_gen[g]["v"]) / len(per_gen[g]["v"])] for g in gens]
    for measure in ("vengefulness", "boldness"):
        if series[measure]:
            charts.append({"type": "line", "title": f"Mean {measure} by generation (0-7 scale)",
                           "x_label": "Generation", "y_label": measure.capitalize(), "y_min": 0, "y_max": 7,
                           "series": [{"name": k, "points": v} for k, v in series[measure].items()]})
    return charts


def _s2_series(preset: str, seed: int) -> list[dict]:
    contrib, belief = [], []
    for eid, label in (("experiment_1_p_then_c", "P then C"), ("experiment_2_c_then_p", "C then P")):
        rows = _jsonl(WORKSPACE / "hypothesis_2_public_goods" / eid / "runs" / f"{preset}_seed{seed}" /
                      "env" / "FGPCPublicGoodsEnv" / "pg_round_summary.jsonl")
        if rows:
            contrib.append({"name": label, "points": [[r["round"], r["mean_contribution"]] for r in rows]})
            belief.append({"name": label, "points": [[r["round"], r["mean_belief"]] for r in rows if r["mean_belief"] is not None]})
    charts = []
    if contrib:
        charts.append({"type": "line", "title": "Mean contribution per round (tokens, of 20)", "x_label": "Round",
                       "y_label": "Tokens", "y_min": 0, "y_max": 20, "series": contrib,
                       "reference": {"label": "Paper, round 1 -> 10: 8.25 -> 8.04", "value": 8.04}})
    if belief:
        charts.append({"type": "line", "title": "Mean belief about others' contribution (tokens)", "x_label": "Round",
                       "y_label": "Tokens", "y_min": 0, "y_max": 20, "series": belief})
    return charts


def _s5_series(preset: str, seed: int) -> list[dict]:
    res = _json(WORKSPACE / "hypothesis_5_polarization" / f"results_{preset}_seed{seed}.json", {}) or {}
    sim, paper = res.get("results", {}), res.get("paper", {})
    charts = []
    specs = [("feed_counter_share", "Counter-attitudinal share of feed", 100, "%"),
             ("cumulative_counter_reads", "Cumulative cross-cutting posts read", 1, "posts"),
             ("affective_change", "Change in affective polarization (thermometer gap)", 1, "points")]
    for key, title, scale, unit in specs:
        bars = [{"name": c, "value": (sim[c].get(key) or 0) * scale,
                 "paper": (paper.get(key, {}).get(c) * scale) if paper.get(key, {}).get(c) is not None else None}
                for c in ("control", "pro", "counter") if c in sim]
        if bars:
            charts.append({"type": "bar", "title": title, "unit": unit, "bars": bars})
    return charts


@app.get("/api/results/{study_id}")
async def results(study_id: str, preset: str = "paper", seed: int = 0) -> dict:
    study = next((s for s in STUDIES if s["id"] == study_id), None)
    if study is None or not study.get("results"):
        raise HTTPException(404, "no results view for this study")
    if preset not in ("smoke", "paper"):
        raise HTTPException(400, "bad preset")
    script = WORKSPACE / study["dir"] / "analyze.py"
    args = ["--preset", preset] + ([] if study_id in ("s1", "s2") else ["--seed", str(int(seed))])
    text = await asyncio.to_thread(_analysis, script, args)
    charts = {"s1": lambda: _s1_series(preset), "s2": lambda: _s2_series(preset, seed),
              "s5": lambda: _s5_series(preset, seed)}.get(study_id, lambda: [])()
    return {"study": study_id, "preset": preset, "seed": seed, "report": text, "charts": charts}


# --------------------------------------------------------------------------- custom experiments
def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (s or "experiment")[:48]


def _build_custom(spec: dict) -> tuple[dict, dict]:
    agents_in = [a for a in spec.get("agents", []) if str(a.get("name", "")).strip()]
    if not agents_in:
        raise HTTPException(400, "Add at least one agent with a name.")
    if len(agents_in) > 50:
        raise HTTPException(400, "Studio experiments are limited to 50 agents.")
    agents, pairs = [], []
    for i, a in enumerate(agents_in, start=1):
        name = str(a["name"]).strip()
        kwargs = {"id": i, "name": name}
        for k in ("age", "gender", "occupation", "personality", "bio"):
            v = str(a.get(k, "")).strip()
            if v:
                kwargs[k] = int(v) if k == "age" and v.isdigit() else v
        kwargs["max_react_turns"] = 6
        agents.append({"agent_id": i, "agent_type": "PersonAgent", "kwargs": kwargs})
        pairs.append([i, name])
    steps = []
    for s in spec.get("steps", []):
        t = s.get("type")
        if t == "run":
            n, minutes = int(s.get("num_steps", 1)), int(s.get("minutes", 60))
            if not (1 <= n <= 500 and 1 <= minutes <= 1440):
                raise HTTPException(400, "Simulate steps: 1-500 steps of 1-1440 minutes.")
            steps.append({"type": "run", "num_steps": n, "tick": minutes * 60})
        elif t == "ask":
            q = str(s.get("question", "")).strip()
            if not q:
                raise HTTPException(400, "A question step is empty.")
            steps.append({"type": "ask", "question": q})
        elif t == "intervene":
            ins = str(s.get("instruction", "")).strip()
            if not ins:
                raise HTTPException(400, "An intervention step is empty.")
            steps.append({"type": "intervene", "instruction": ins})
        elif t == "survey":
            qs = []
            for j, q in enumerate(s.get("questions", []), start=1):
                prompt = str(q.get("prompt", "")).strip()
                if not prompt:
                    continue
                rt = q.get("response_type", "text")
                item = {"id": f"q{j}", "prompt": prompt, "response_type": rt}
                if rt == "choice":
                    item["choices"] = [c.strip() for c in str(q.get("choices", "")).split(",") if c.strip()]
                    if len(item["choices"]) < 2:
                        raise HTTPException(400, f"Survey question {j}: give at least two comma-separated choices.")
                qs.append(item)
            if not qs:
                raise HTTPException(400, "A survey step has no questions.")
            steps.append({"type": "questionnaire", "questionnaire_id": f"survey_{len(steps) + 1}",
                          "title": str(s.get("title") or "Survey"), "questions": qs})
        else:
            raise HTTPException(400, f"unknown step type {t!r}")
    if not steps:
        raise HTTPException(400, "Add at least one timeline step.")
    start = str(spec.get("start") or "2026-01-01T09:00")
    try:
        datetime.fromisoformat(start)
    except ValueError:
        raise HTTPException(400, "Start time must look like 2026-01-01T09:00") from None
    env_modules = [{"module_type": "SimpleSocialSpace", "kwargs": {"agent_id_name_pairs": pairs}}]
    if (spec.get("map") or {}).get("id"):
        env_modules.append(_mobility_module(spec["map"], agents, agents_in))
    init = {"env_modules": env_modules, "agents": agents, "codegen_router": {"final_summary_enabled": True}}
    return init, {"start_t": start if len(start) > 16 else start + ":00", "steps": steps}


def _mobility_module(spec_map: dict, agents: list[dict], rows: list[dict]) -> dict:
    """MobilitySpace config placing each agent at the home/workplace chosen in the builder (row["home"],
    row["work"] = AOI ids on a Studio map); also tells each agent where they live and work (profile fields)
    and turns on the daily-planning skill, as the paper's DailyMobility config does."""
    map_id = str(spec_map.get("id"))
    info = _map_or_404(map_id)
    if info.get("status") != "ready":
        raise HTTPException(409, f"The map {info.get('name', map_id)} isn't ready yet.")
    known = maps.place_index(map_id)
    city = info.get("name") or map_id
    persons = []
    for agent, p in zip(agents, rows):
        try:
            home, work = int(p["home"]), int(p["work"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, f"Place {agent['kwargs']['name']} on the map (use 'Place everyone "
                                     "randomly').") from None
        if home not in known or work not in known:
            raise HTTPException(400, f"{agent['kwargs']['name']}'s home or workplace isn't a reachable place on "
                                     "this map; re-roll it.")
        aid = agent["agent_id"]
        persons.append({"id": aid, "position": {"aoi_id": home}, "home_aoi": home, "work_aoi": work})
        kw = agent["kwargs"]
        kw["city"] = city
        kw["home"] = f"AOI {home} ({known[home]['label']})"
        kw["workplace"] = f"AOI {work} ({known[work]['label']})"
        kw["default_activated_skill_ids"] = ["built-in@daily-guidance"]
    return {"module_type": "MobilitySpace",
            "kwargs": {"file_path": f"maps/{map_id}/map.pb", "home_dir": "", "persons": persons}}


@app.get("/api/custom")
def list_custom() -> list[dict]:
    out = []
    runs = _all_runs()
    for f in sorted(MY_EXPS.glob("*/experiment.json")):
        meta = _json(f, {}) or {}
        rel = _rel(f.parent)
        out.append({**meta, "path": rel, "runs": [r for r in runs if r["experiment"] == rel]})
    return out


@app.get("/api/custom/get")
def get_custom(path: str) -> dict:
    exp = _exp_dir(path)
    return _json(exp / "experiment.json", {}) or {}


@app.post("/api/custom")
def save_custom(spec: dict = Body(...)) -> dict:
    name = str(spec.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Give the experiment a name.")
    init, steps = _build_custom(spec)
    path = spec.get("path")
    exp = _exp_dir(path) if path else MY_EXPS / _slug(name)
    if not path and exp.exists():
        exp = MY_EXPS / f"{_slug(name)}_{datetime.now():%Y%m%d_%H%M%S}"
    (exp / "init").mkdir(parents=True, exist_ok=True)
    (exp / "init" / "init_config.json").write_text(json.dumps(init, indent=2, ensure_ascii=False), encoding="utf-8")
    (exp / "init" / "steps.yaml").write_text(yaml.safe_dump(steps, sort_keys=False, allow_unicode=True), encoding="utf-8")
    meta = {"name": name, "description": str(spec.get("description", "")), "start": spec.get("start"),
            "agents": spec.get("agents", []), "steps": spec.get("steps", []),
            "map": spec.get("map") if (spec.get("map") or {}).get("id") else None,
            "updated": datetime.now().isoformat(timespec="seconds")}
    (exp / "experiment.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"path": _rel(exp), **meta}


@app.post("/api/custom/delete")
def delete_custom(body: dict = Body(...)) -> dict:
    exp = _exp_dir(str(body.get("path", "")))
    if exp.parent != MY_EXPS.resolve():
        raise HTTPException(400, "only experiments created in the Studio can be deleted here")
    if any(r["run_dir"].is_relative_to(exp) and r["proc"].poll() is None for r in RUNS.values()):
        raise HTTPException(409, "Stop its runs first.")
    shutil.rmtree(exp, ignore_errors=True)
    return {"deleted": True}


@app.post("/api/custom/run")
async def run_custom(body: dict = Body(...)) -> dict:
    exp = _exp_dir(str(body.get("path", "")))
    used = {int(m.group(1)) for p in (exp / "runs").glob("custom_seed*") if (m := re.match(r"custom_seed(\d+)$", p.name))}
    n = max(used, default=0) + 1
    label = f"{(_json(exp / 'experiment.json', {}) or {}).get('name', exp.name)} - run {n}"
    return await asyncio.to_thread(_launch, exp, "custom", n, label)


# --------------------------------------------------------------------------- misc
@app.get("/api/ping")
def ping() -> dict:
    return {"ok": True, "app": "agentsociety-studio"}


@app.post("/api/shutdown")
def shutdown() -> dict:
    def _bye():
        time.sleep(0.5)
        os._exit(0)

    threading.Thread(target=_bye, daemon=True).start()
    return {"ok": True, "active_runs_continue": sum(1 for r in RUNS.values() if r["proc"].poll() is None)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "static" / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")


@app.exception_handler(HTTPException)
async def _http_error(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


def _already_running() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/ping", timeout=1.5) as r:
            return b"agentsociety-studio" in r.read()
    except OSError:
        return False


def main() -> None:
    url = f"http://127.0.0.1:{PORT}"
    if _already_running():
        print(f"AgentSociety Studio is already running - opening {url}")
        webbrowser.open(url)
        return
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"Port {PORT} is used by another program; close it and try again.")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    MY_EXPS.mkdir(parents=True, exist_ok=True)
    print(f"AgentSociety Studio is running at {url}\nKeep this window open while you use it; close it to stop the Studio.")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
