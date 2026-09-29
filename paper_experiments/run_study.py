"""Generate configs for and run one AgentSociety 2 paper experiment.

    python run_study.py <experiment_dir> [--preset smoke|paper] [--seed N] [--check] [--log-level INFO]

<experiment_dir> is a directory like hypothesis_1_social_norms/experiment_1_norms
containing init/config_params.py (the paper's layout, Sec. 4.4).

Steps:
1. Runs init/config_params.py --preset ... --seed ... to write init/init_config.json + init/steps.yaml.
2. --check: validates both files and instantiates every env module (no LLM calls, no Ray), then exits.
3. Otherwise runs the AgentSociety2 CLI with run dir <experiment_dir>/runs/<preset>_seed<N>/.

Custom modules in ./custom/ are made visible to Ray worker processes via the
WORKSPACE_PATH environment variable, which the module registry reads lazily in
every process. LLM credentials are loaded from the project-level .env.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
PROJECT_ROOT = WORKSPACE.parent


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    os.environ["WORKSPACE_PATH"] = str(WORKSPACE)
    os.chdir(WORKSPACE)


def _generate(exp_dir: Path, preset: str, seed: int) -> tuple[Path, Path]:
    script = exp_dir / "init" / "config_params.py"
    cfg, steps = exp_dir / "init" / "init_config.json", exp_dir / "init" / "steps.yaml"
    if not script.is_file():
        if cfg.is_file() and steps.is_file():  # hand-built experiment (e.g. from the UI)
            return cfg, steps
        sys.exit(f"missing {script}")
    proc = subprocess.run(
        [sys.executable, str(script), "--preset", preset, "--seed", str(seed)],
        cwd=str(exp_dir),
    )
    if proc.returncode != 0:  # the generator already printed why (e.g. missing data files)
        sys.exit(f"config generation failed for {exp_dir.name} (preset={preset})")
    return exp_dir / "init" / "init_config.json", exp_dir / "init" / "steps.yaml"


def _check(config_path: Path, steps_path: Path) -> None:
    import yaml
    from agentsociety2.registry import get_agent_module_class, get_env_module_class
    from agentsociety2.society.models import InitConfig, StepsConfig

    cfg = InitConfig.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    steps = StepsConfig.model_validate(yaml.safe_load(steps_path.read_text(encoding="utf-8")))
    for m in cfg.env_modules:
        cls = get_env_module_class(m.module_type)
        if cls is None:
            sys.exit(f"env module {m.module_type!r} not found in registry")
        cls(**m.kwargs)
        print(f"  env   {m.module_type}: constructed OK")
    types = {a.agent_type for a in cfg.agents}
    for t in types:
        if get_agent_module_class(t) is None:
            sys.exit(f"agent type {t!r} not found in registry")
    kinds: dict[str, int] = {}
    for s in steps.steps:
        kinds[s.type] = kinds.get(s.type, 0) + 1
    sim_steps = sum(s.num_steps for s in steps.steps if s.type == "run")
    print(f"  agents {len(cfg.agents)} x {sorted(types)}; steps {kinds}; simulated ticks {sim_steps}")
    print("CHECK PASSED")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment_dir")
    ap.add_argument("--preset", default="smoke", choices=["smoke", "paper", "custom"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--check", action="store_true", help="validate configs only (no LLM calls)")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    exp_dir = Path(args.experiment_dir).resolve()
    _load_env()
    config_path, steps_path = _generate(exp_dir, args.preset, args.seed)
    if args.check:
        _check(config_path, steps_path)
        return

    run_dir = exp_dir / "runs" / f"{args.preset}_seed{args.seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    from agentsociety2.society.cli import main as cli_main

    sys.argv = [
        "agentsociety2-cli",
        "--config", str(config_path),
        "--steps", str(steps_path),
        "--run-dir", str(run_dir),
        "--experiment-id", f"{exp_dir.parent.name}/{exp_dir.name}/{args.preset}_seed{args.seed}",
        "--log-level", args.log_level,
        "--log-file", str(run_dir / "output.log"),
    ]
    cli_main()


if __name__ == "__main__":
    main()
