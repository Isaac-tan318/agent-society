"""Generate init_config.json + steps.yaml for the DailyMobility benchmark (AS2 paper Sec. 7.6).

Adapted from tsinghua-fib-lab/AgentSociety examples/v2/daily_mobility/init/config_params.py
(Apache-2.0): PersonAgent + MobilitySpace on the Beijing road network, one simulated
weekday (2018-06-13) with 15-minute ticks and a primary-intention questionnaire every
30 minutes (48 slots), evaluated against the DailyMobility ground truth by JSD.

Data (HuggingFace dataset tsinghua-fib-lab/daily-mobility-generation-benchmark), looked up at
  $DAILY_MOBILITY_MAP_PATH       or paper_experiments/data/mobility/beijing.pb   (+ beijing.pb.cache)
  $DAILY_MOBILITY_PROFILES_PATH  or paper_experiments/data/mobility/beijing_profiles.json
MobilitySpace needs a native routing binary that exists only for Linux x86_64 and
macOS arm64, so run this experiment under WSL/Linux (see README).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
EXP_DIR = HERE.parent
HYP_DIR = EXP_DIR.parent
WORKSPACE = HYP_DIR.parent
sys.path.insert(0, str(HYP_DIR))
from daily_mobility_intentions import INTENTION_CHOICES, build_primary_intention_prompt  # noqa: E402

PRESETS = {"paper": {"num_agents": 100}, "smoke": {"num_agents": 2}}
START_T = "2018-06-13T00:00:00"  # a Wednesday, as in the released example
TICK, SLOT_MINUTES, HOURS = 900, 30, 24


def _profile_block(p: dict) -> str:
    return (
        f"Agent-{p['id']}, age {p.get('age', '?')}, gender {p.get('gender', '?')}, "
        f"education {p.get('education', '?')}, occupation {p.get('occupation', '?')}, "
        f"home AOI {p.get('home')}, work AOI {p.get('work')}. "
        "You are simulating an ordinary day in an urban mobility environment. "
        f"Each simulation step advances about {SLOT_MINUTES} minutes on the same calendar day. "
        "Use mobility tools as a real person would for commuting, errands, meals, and leisure, "
        "consistent with your profile."
    )


def _data_path(env_var: str, name: str) -> Path:
    path = Path(os.environ.get(env_var) or (WORKSPACE / "data" / "mobility" / name))
    if not path.is_file():
        raise SystemExit(f"Missing {path}. Download it from the HuggingFace dataset "
                         "tsinghua-fib-lab/daily-mobility-generation-benchmark (see README).")
    return path.resolve()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper", choices=sorted(PRESETS))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    map_path = _data_path("DAILY_MOBILITY_MAP_PATH", "beijing.pb")
    profiles = json.loads(_data_path("DAILY_MOBILITY_PROFILES_PATH", "beijing_profiles.json")
                          .read_text(encoding="utf-8"))
    use = profiles[: PRESETS[args.preset]["num_agents"]]
    ids = [p["id"] for p in use]

    run_dir = EXP_DIR / "runs" / f"{args.preset}_seed{args.seed}"  # same convention as run_study.py
    mobility_home = run_dir / "mobility_workspace"
    mobility_home.mkdir(parents=True, exist_ok=True)

    init_config = {
        "env_modules": [{
            "module_type": "MobilitySpace",
            "kwargs": {
                "file_path": str(map_path),
                "home_dir": str(mobility_home.resolve()),
                "persons": [{"id": p["id"], "position": {"kind": "aoi", "aoi_id": p["home"]}} for p in use],
            },
        }],
        "agents": [{
            "agent_id": p["id"], "agent_type": "PersonAgent",
            "kwargs": {"id": p["id"], "profile": _profile_block(p),
                       "max_react_turns": 6 if len(use) > 20 else 8,
                       "default_activated_skill_ids": ["built-in@daily-guidance"]},
        } for p in use],
    }

    if args.preset == "smoke":
        steps = [{"type": "run", "num_steps": 2, "tick": TICK}]
    else:
        total_slots = HOURS * 60 // SLOT_MINUTES
        steps = []
        for slot in range(total_slots):
            steps.append({
                "type": "questionnaire",
                "questionnaire_id": f"daily_mobility_intention_slot_{slot}",
                "title": f"Daily mobility intention ({SLOT_MINUTES} min)",
                "description": "",
                "target_agent_ids": ids,
                "questions": [{
                    "id": "primary_intention",
                    "prompt": build_primary_intention_prompt(slot, total_slots=total_slots,
                                                             slot_minutes=SLOT_MINUTES),
                    "response_type": "choice",
                    "choices": list(INTENTION_CHOICES),
                }],
            })
            steps.append({"type": "run", "num_steps": SLOT_MINUTES * 60 // TICK, "tick": TICK})

    (HERE / "init_config.json").write_text(json.dumps(init_config, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "steps.yaml").write_text(
        yaml.safe_dump({"start_t": START_T, "steps": steps}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"[daily_mobility] preset={args.preset}: {len(use)} agents -> {HERE}")


if __name__ == "__main__":
    main()
