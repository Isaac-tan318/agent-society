"""
Run a full AgentSociety 2 experiment (init_config.json + steps.yaml).

    python run_experiment.py --config experiment\init_config.json --steps experiment\steps.yaml --run-dir experiment\run

agentsociety2.society.cli does not load .env itself (only its web backend does),
so this wrapper loads it first, then delegates straight to the real CLI --
every flag `python -m agentsociety2.society.cli --help` lists works here too.
"""
from dotenv import load_dotenv

load_dotenv()

from agentsociety2.society.cli import main

if __name__ == "__main__":
    main()
