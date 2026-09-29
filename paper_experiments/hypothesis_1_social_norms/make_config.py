"""Shared config generator for the Axelrod Norms / Metanorms experiments (AS2 paper Sec. 7.1).

Called by experiment_*/init/config_params.py. Paper setup: 20 agents, 100
generations x 4 rounds = 400 steps, payoffs T=3 H=-1 P=-9 E=-2 MP=-9 ME=-2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PRESETS = {
    # paper: exactly the AS2 setup. smoke: same population, 5 generations.
    "paper": {"num_agents": 20, "generations": 100},
    "smoke": {"num_agents": 20, "generations": 5},
}
ROUNDS_PER_GENERATION = 4


def generate(init_dir: Path, game_mode: str) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper", choices=sorted(PRESETS))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    p = PRESETS[args.preset]
    ids = list(range(1, p["num_agents"] + 1))

    init_config = {
        "env_modules": [
            {
                "module_type": "NormsGameEnv",
                "kwargs": {
                    "agent_ids": ids,
                    "game_mode": game_mode,
                    "rounds_per_generation": ROUNDS_PER_GENERATION,
                    "temptation": 3, "hurt": -1,
                    "punishment": -9, "enforcement_cost": -2,
                    "meta_punishment": -9, "meta_enforcement_cost": -2,
                    "mutation_rate": 0.01,
                    "seed": args.seed,
                },
            }
        ],
        "agents": [
            {"agent_id": i, "agent_type": "NormsGameAgent",
             "kwargs": {"id": i, "name": f"Agent-{i}"}}
            for i in ids
        ],
        # Rule-based study: no natural-language env answers needed.
        "codegen_router": {"final_summary_enabled": False},
    }
    steps = (
        'start_t: "2026-01-01T00:00:00"\n'
        "steps:\n"
        "  - type: run\n"
        f"    num_steps: {p['generations'] * ROUNDS_PER_GENERATION}\n"
        "    tick: 60\n"
    )
    init_dir.mkdir(parents=True, exist_ok=True)
    (init_dir / "init_config.json").write_text(json.dumps(init_config, indent=2), encoding="utf-8")
    (init_dir / "steps.yaml").write_text(steps, encoding="utf-8")
    print(f"[{game_mode}] preset={args.preset} seed={args.seed}: {len(ids)} agents, "
          f"{p['generations']} generations -> {init_dir}")
