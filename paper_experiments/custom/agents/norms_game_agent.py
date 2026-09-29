"""NormsGameAgent - rule-based strategy carrier for NormsGameEnv (Axelrod 1986).

AgentSociety 2 paper Sec. 7.1: "the agents in this experiment mainly serve as
carriers of evolutionary strategies. Their behavior is controlled by explicit
rules and parameters". The rule-based moves (defect iff boldness > chance of
being seen; punish with probability vengefulness) are executed by
NormsGameEnv.step(), so this agent makes no LLM calls: step() is bookkeeping
only, and ask() answers deterministically.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class NormsGameAgent(AgentBase):
    """Rule-based population member for the Axelrod Norms / Metanorms game (no LLM calls)."""

    @classmethod
    def init_description(cls) -> str:
        return """NormsGameAgent: rule-based strategy carrier for NormsGameEnv.

**kwargs:** **id** (int, must equal agent_id) and optional **name** (str).
Strategies (boldness/vengefulness) live in NormsGameEnv, which applies the
agent's rule-based moves each step. The agent makes no LLM calls.
"""

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(config or {}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        agent_id = int(profile.get("id", 0))
        name = str(profile.get("name") or f"Agent-{agent_id}")
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {"agent_class": cls.__name__, "id": agent_id, "name": name,
                 "profile": profile, "step_count": 0, "current_time": None},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(cls, workspace_path: Path, service_proxy: Any) -> "NormsGameAgent":
        agent = cls()
        await agent._restore_game_state(workspace_path, service_proxy)
        return agent

    async def _restore_game_state(self, workspace_path: Path, service_proxy: Any) -> None:
        # Game agents skip AgentBase.restore(): no skill runtime or workspace FS needed.
        workspace_path = Path(workspace_path)
        cfg_path = workspace_path / "config.json"
        self._config = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        meta = json.loads((workspace_path / "AGENT.json").read_text(encoding="utf-8"))
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {})
        self._name = meta.get("name") or f"Agent-{self._id}"
        self._step_count = int(meta.get("step_count", 0))
        self._current_time = meta.get("current_time")
        self._bind_services(service_proxy)

    async def to_workspace(self, workspace_path: Path) -> None:
        (Path(workspace_path) / "AGENT.json").write_text(
            json.dumps(
                {"agent_class": type(self).__name__, "id": self._id, "name": self._name,
                 "profile": self.get_profile(), "step_count": self._step_count,
                 "current_time": self._current_time},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    async def ask(self, message: str, readonly: bool = True, *, t: datetime | None = None) -> str:
        return json.dumps({
            "reason": "I am a rule-based strategy carrier; my strategy is recorded by NormsGameEnv.",
            "answer": "See norms_agents.jsonl in the NormsGameEnv workspace for my boldness/vengefulness trajectory.",
        })

    async def step(self, tick: int, t: datetime) -> str:
        self._step_count += 1
        self._current_time = t.isoformat()
        return f"[{self._name}] step {self._step_count}: move resolved by NormsGameEnv"
