"""Shared config generator for the disaster-mobility study (AS2 paper Sec. 7.7).

Paper setup: 100 profile-based PersonAgents; MobilitySpace + EventSpace +
GlobalInformationEnv; eleven days with a one-hour grid; the global information
channel is updated at the start of each disaster phase. Scenarios: 2021 Texas
Winter Storm (starts 2021-02-11) and 2018 California Camp Fire (starts
2018-11-06). MovementLedgerEnv (custom, listed last) logs daily completed moves.

Data: the paper used a Houston map + ACS-based profiles, which are not public.
By default this looks for any MobilitySpace map + matching profiles at
  $DISASTER_MAP_PATH       or paper_experiments/data/disaster/map.pb
  $DISASTER_PROFILES_PATH  or paper_experiments/data/disaster/profiles.json
(e.g. the Columbia, SC map + profiles of the HuggingFace dataset
tsinghua-fib-lab/hurricane-mobility-generation-benchmark as a stand-in).
MobilitySpace needs a Linux/macOS routing binary: run under WSL (see README).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

HYP_DIR = Path(__file__).resolve().parent
WORKSPACE = HYP_DIR.parent

SCENARIOS = {
    "texas_winter_storm": {
        "start": "2021-02-11T00:00:00",
        "phases": [  # (name, hours, broadcast)
            ("Cold-wave arrival", 48,
             "WEATHER ALERT (Feb 11, 2021): An Arctic cold front is moving into Texas. Forecasters expect "
             "temperatures far below freezing later this week. Officials urge residents to stock up on "
             "supplies, protect pipes and prepare for possible power outages."),
            ("Freezing precipitation", 48,
             "WINTER STORM WARNING (Feb 13, 2021): Freezing rain, sleet and snow are falling across the region. "
             "Roads and bridges are icy and dangerous. Authorities ask residents to avoid non-essential travel."),
            ("Peak freeze", 72,
             "EMERGENCY (Feb 15, 2021): Record low temperatures. The state grid operator has ordered rolling "
             "blackouts and millions of households are without power or heat. Water systems are failing and "
             "boil-water notices are in effect. Stay home unless travel is essential; warming centers are open."),
            ("Restricted travel and restoration", 48,
             "UPDATE (Feb 18, 2021): Power is being restored gradually, but many areas still lack electricity "
             "and safe water. Roads remain icy in places and boil-water notices continue. Limit travel to "
             "essential trips for water, food or medical needs."),
            ("Recovery", 48,
             "RECOVERY (Feb 20, 2021): Temperatures are rising above freezing, roads are clearing and power is "
             "back for most customers. Stores and services are reopening; some boil-water notices remain."),
        ],
    },
    "camp_fire": {
        "start": "2018-11-06T00:00:00",
        "phases": [
            ("High fire risk", 48,
             "FIRE WEATHER WATCH (Nov 6, 2018): Very dry conditions and strong winds are forecast and red flag "
             "warnings are in effect. Avoid anything that could spark a fire and keep an evacuation plan ready."),
            ("Ignition and evacuation", 24,
             "EVACUATION ORDER (Nov 8, 2018): A fast-moving wildfire, the Camp Fire, ignited this morning and is "
             "spreading rapidly toward populated areas. Mandatory evacuations are ordered for affected "
             "communities. Follow official routes and leave immediately if told to."),
            ("Sustained wildfire", 96,
             "EMERGENCY (Nov 9, 2018): The Camp Fire has destroyed thousands of buildings and remains largely "
             "uncontained. Many roads are closed and heavy smoke is causing hazardous air quality across the "
             "region. Stay indoors when possible and stay away from the fire area."),
            ("Smoke and traffic control", 72,
             "AIR QUALITY ALERT (Nov 13, 2018): Dense smoke still blankets the region with unhealthy to "
             "hazardous air. Road closures and traffic controls remain around the burn area; schools and some "
             "businesses are closed. Limit outdoor activity and non-essential trips."),
            ("Early containment", 24,
             "UPDATE (Nov 16, 2018): Firefighters report growing containment of the Camp Fire. Some roads are "
             "reopening, but smoke persists and many evacuees remain displaced."),
        ],
    },
}
PRESETS = {"paper": {"num_agents": 100, "hours_cap": None}, "smoke": {"num_agents": 2, "hours_cap": 3}}


def _data_path(env_var: str, name: str) -> Path:
    path = Path(os.environ.get(env_var) or (WORKSPACE / "data" / "disaster" / name))
    if not path.is_file():
        raise SystemExit(f"Missing {path}. Provide a MobilitySpace map + profiles (see README).")
    return path.resolve()


def _profile_text(p: dict) -> str:
    extra = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in p.items() if k not in {"id", "home", "work"})
    return (f"Resident-{p['id']}: {extra}. Home AOI {p.get('home')}, work AOI {p.get('work')}. "
            "You live your normal life in this city, one simulation step per hour. Pay attention to the "
            "official information broadcast and decide whether and where to travel as a real person would.")


def generate(init_dir: Path, scenario: str) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper", choices=sorted(PRESETS))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    preset, sc = PRESETS[args.preset], SCENARIOS[scenario]
    map_path = _data_path("DISASTER_MAP_PATH", "map.pb")
    profiles = json.loads(_data_path("DISASTER_PROFILES_PATH", "profiles.json").read_text(encoding="utf-8"))
    use = profiles[: preset["num_agents"]]
    exp_dir = init_dir.parent
    home = exp_dir / "runs" / f"{args.preset}_seed{args.seed}" / "mobility_workspace"
    home.mkdir(parents=True, exist_ok=True)

    init_config = {
        "env_modules": [
            {"module_type": "MobilitySpace", "kwargs": {
                "file_path": str(map_path), "home_dir": str(home.resolve()),
                "persons": [{"id": p["id"], "position": {"kind": "aoi", "aoi_id": p["home"]}} for p in use]}},
            {"module_type": "EventSpace", "kwargs": {}},
            {"module_type": "GlobalInformationEnv", "kwargs": {}},
            {"module_type": "MovementLedgerEnv", "kwargs": {"source_module": "MobilitySpace"}},  # keep last
        ],
        "agents": [{
            "agent_id": p["id"], "agent_type": "PersonAgent",
            "kwargs": {"id": p["id"], "profile": _profile_text(p), "max_react_turns": 6,
                       "default_activated_skill_ids": ["built-in@daily-guidance"]},
        } for p in use],
    }
    steps = []
    phases = sc["phases"] if args.preset == "paper" else sc["phases"][:2]
    for name, hours, text in phases:
        steps.append({"type": "intervene", "instruction": (
            f"Disaster phase '{name}' begins. Update the global information broadcast: call the global "
            f"information module's set() tool with exactly this text: \"{text}\"")})
        steps.append({"type": "run", "num_steps": min(hours, preset["hours_cap"] or hours), "tick": 3600})
    init_dir.mkdir(parents=True, exist_ok=True)
    (init_dir / "init_config.json").write_text(json.dumps(init_config, indent=2, ensure_ascii=False), encoding="utf-8")
    (init_dir / "steps.yaml").write_text(yaml.safe_dump({"start_t": sc["start"], "steps": steps},
                                                        sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"[{scenario}] preset={args.preset}: {len(use)} agents, "
          f"{sum(s['num_steps'] for s in steps if s['type'] == 'run')} hourly steps -> {init_dir}")
