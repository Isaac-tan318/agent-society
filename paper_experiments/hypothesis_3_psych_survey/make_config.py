"""Shared config generator for the Qi et al. (2025) self-bias survey replication (AS2 paper Sec. 7.3).

Paper setup: 134 PersonAgents, one per real participant profile from Qi et al.
(2025), unmodified agent class + profile injection + a task-completion skill,
one built-in task environment per experiment (EE, SE, IAT, SRE).

Data files (written by prepare_data.py from the OSF dataset, DOI 10.17605/OSF.IO/3H95F):
  data/qi2025/profiles.json      - required for --preset paper
  data/qi2025/iat_trials.json    - optional: full trial sequence (else the env's 132 built-in trials)
  data/qi2025/sre_stimuli.json   - optional: full 120/240 SRE stimuli (else the env's small demo set)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HYP_DIR = Path(__file__).resolve().parent
WORKSPACE = HYP_DIR.parent
DATA = HYP_DIR / "data" / "qi2025"
SKILLS_DIR = WORKSPACE / "custom" / "skills"

TASKS = {
    "ee": {"env": "EndowmentEffectEnv", "skill": "endowment-effect-task", "steps": {"paper": 3, "smoke": 2}, "turns": 10},
    "se": {"env": "SelfEnhancementEnv", "skill": "self-enhancement-task", "steps": {"paper": 3, "smoke": 2}, "turns": 10},
    "iat": {"env": "ImplicitAssociationTestEnv", "skill": "iat-task", "steps": {"paper": 20, "smoke": 4}, "turns": 24},
    "sre": {"env": "SelfReferenceEffectEnv", "skill": "self-reference-task", "steps": {"paper": 10, "smoke": 4}, "turns": 16},
}

SMOKE_PROFILES = [
    {"participant_id": "S1", "age": 21, "gender": "female",
     "big_five": {"openness": 3.8, "conscientiousness": 3.4, "extraversion": 2.9, "agreeableness": 4.0, "neuroticism": 3.1},
     "rosenberg_self_esteem": 3.0},
    {"participant_id": "S2", "age": 23, "gender": "male",
     "big_five": {"openness": 3.2, "conscientiousness": 4.1, "extraversion": 3.6, "agreeableness": 3.3, "neuroticism": 2.4},
     "rosenberg_self_esteem": 3.4},
]


def _persona(p: dict) -> str:
    """Neutral prompt fragment built from whatever profile fields are present."""
    parts = [f"You are a Tsinghua University student participating in a psychology study "
             f"(participant {p.get('participant_id')}), age {p.get('age')}, {p.get('gender')}."]
    for key, value in p.items():
        if key in {"participant_id", "age", "gender"}:
            continue
        if isinstance(value, dict):
            value = ", ".join(f"{k} {v}" for k, v in value.items())
        parts.append(f"{key.replace('_', ' ')}: {value}.")
    return " ".join(parts)


def generate(init_dir: Path, task: str) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper", choices=["paper", "smoke"])
    ap.add_argument("--seed", type=int, default=0)  # unused; kept for run_study.py
    args = ap.parse_args()
    spec = TASKS[task]

    if args.preset == "paper":
        path = DATA / "profiles.json"
        if not path.is_file():
            raise SystemExit(f"Missing {path}. Download the Qi et al. (2025) OSF data and run "
                             "hypothesis_3_psych_survey/prepare_data.py (see README).")
        profiles = json.loads(path.read_text(encoding="utf-8"))
    else:
        profiles = SMOKE_PROFILES

    ids = list(range(1, len(profiles) + 1))
    env_kwargs: dict = {"agent_ids": ids}
    if task == "iat":
        full = DATA / "iat_trials.json"
        if args.preset == "paper" and full.is_file():
            env_kwargs["trials"] = json.loads(full.read_text(encoding="utf-8"))
        elif args.preset == "smoke":
            from agentsociety2.contrib.env.implicit_association_test import ImplicitAssociationTestEnv

            env_kwargs["trials"] = ImplicitAssociationTestEnv.STANDARD_TRIALS[:6]
    if task == "sre":
        full = DATA / "sre_stimuli.json"
        if args.preset == "paper" and full.is_file():
            env_kwargs.update(json.loads(full.read_text(encoding="utf-8")))
        elif args.preset == "paper":
            print("WARNING: data/qi2025/sre_stimuli.json missing - using the env's small demo stimulus set, "
                  "not the paper's 120 encoding / 240 recognition traits.")

    agents = []
    for aid, p in zip(ids, profiles):
        agents.append({
            "agent_id": aid, "agent_type": "PersonAgent",
            "kwargs": {
                "id": aid, "name": f"Participant-{p.get('participant_id', aid)}",
                "persona": _persona(p), **{k: v for k, v in p.items() if k != "persona"},
                "max_react_turns": spec["turns"],
                "enable_memory": True,
                "extra_skill_paths": [str(SKILLS_DIR)],
                "default_activated_skill_ids": [f"custom@{spec['skill']}"],
                "disabled_skill_ids": ["built-in@daily-guidance"],
            },
        })
    init_config = {
        "env_modules": [{"module_type": spec["env"], "kwargs": env_kwargs}],
        "agents": agents,
        "codegen_router": {"final_summary_enabled": True},  # PersonAgent reads NL env answers
    }
    steps = (
        'start_t: "2026-03-02T09:00:00"\n'
        "steps:\n"
        "  - type: run\n"
        f"    num_steps: {spec['steps'][args.preset]}\n"
        "    tick: 600\n"
    )
    init_dir.mkdir(parents=True, exist_ok=True)
    (init_dir / "init_config.json").write_text(json.dumps(init_config, indent=2, ensure_ascii=False), encoding="utf-8")
    (init_dir / "steps.yaml").write_text(steps, encoding="utf-8")
    print(f"[{task}] preset={args.preset}: {len(agents)} PersonAgents, env {spec['env']}, "
          f"{spec['steps'][args.preset]} steps -> {init_dir}")
