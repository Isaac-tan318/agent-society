"""Shared config generator for the Fischbacher & Gaechter (2010) replication (AS2 paper Sec. 7.2).

Paper setup: 24 agents randomly assigned to six four-person groups; P stage
(strategy method) + 10 C rounds; P->C main condition and C->P comparison.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PRESETS = {
    "paper": {"num_agents": 24, "num_rounds": 10},
    "smoke": {"num_agents": 4, "num_rounds": 2},
}


def generate(init_dir: Path, stage_order: str) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper", choices=sorted(PRESETS))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    p = PRESETS[args.preset]
    ids = list(range(1, p["num_agents"] + 1))
    init_config = {
        "env_modules": [{
            "module_type": "FGPCPublicGoodsEnv",
            "kwargs": {"agent_ids": ids, "group_size": 4, "endowment": 20, "mpcr": 0.4,
                       "num_rounds": p["num_rounds"], "stage_order": stage_order,
                       "matching": "partner", "belief_bonus": True, "seed": args.seed},
        }],
        "agents": [
            {"agent_id": i, "agent_type": "FGPCPublicGoodsLLMAgent",
             "kwargs": {"id": i, "name": f"Participant-{i}"}}
            for i in ids
        ],
        # Agents parse structured env results; skip the per-call NL summary LLM call.
        "codegen_router": {"final_summary_enabled": False},
    }
    steps = (
        'start_t: "2026-01-01T09:00:00"\n'
        "steps:\n"
        "  - type: run\n"
        f"    num_steps: {p['num_rounds'] + 1}   # P stage + C rounds\n"
        "    tick: 60\n"
    )
    init_dir.mkdir(parents=True, exist_ok=True)
    (init_dir / "init_config.json").write_text(json.dumps(init_config, indent=2), encoding="utf-8")
    (init_dir / "steps.yaml").write_text(steps, encoding="utf-8")
    print(f"[{stage_order}] preset={args.preset} seed={args.seed}: {len(ids)} agents, "
          f"{p['num_rounds']} rounds -> {init_dir}")
