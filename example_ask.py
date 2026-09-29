"""
Minimal AgentSociety 2 example: ask one LLM-driven agent a question.

    python example_ask.py

Requires a `.env` file next to this script (copy `.env.example` -> `.env` and
fill in your LLM credentials). The Windows `fcntl`/`os.pathconf` compatibility
shim is loaded automatically by `.venv/Lib/site-packages/sitecustomize.py`.
"""
# agentsociety2 validates AGENTSOCIETY_LLM_* at IMPORT time, so credentials
# must be loaded from .env BEFORE importing the package.
from dotenv import load_dotenv

load_dotenv()

import asyncio
from datetime import datetime
from pathlib import Path

from agentsociety2.env import CodeGenRouter
from agentsociety2.contrib.env import SimpleSocialSpace
from agentsociety2.society import AgentSociety


async def main() -> None:
    agent_specs = [
        {
            "id": 1,
            "profile": {
                "name": "Alice",
                "age": 28,
                "personality": "friendly and curious",
                "bio": "A software engineer who loves hiking.",
            },
            "config": {},
        }
    ]
    names = [(s["id"], s["profile"]["name"]) for s in agent_specs]

    social_env = SimpleSocialSpace(agent_id_name_pairs=names)
    env_router = CodeGenRouter(env_modules=[social_env])

    society = AgentSociety(
        agent_specs=agent_specs,
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=datetime.now(),
        run_dir=Path("run"),
    )

    await society.init()
    try:
        response = await society.ask("What's your favorite activity?")
        print("\nAgent response:", response)
    finally:
        await society.close()


if __name__ == "__main__":
    asyncio.run(main())
