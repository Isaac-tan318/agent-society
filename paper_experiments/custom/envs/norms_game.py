"""NormsGameEnv - Axelrod (1986) Norms / Metanorms evolutionary game.

Reproduces AgentSociety 2 paper Sec. 7.1 ("Emergence of Social Norms"), which
re-implements Axelrod, R. (1986) "An Evolutionary Approach to Norms", APSR 80(4).

Model (Axelrod 1986; parameters as reported in the AS2 paper):
- Each agent carries a 6-bit strategy: 3 bits boldness B and 3 bits vengefulness
  V, each a level 0..7 (probability level/7).
- One simulation step = one interaction round. In a round every agent gets one
  opportunity to defect. A chance of being seen S ~ U(0, 1) is drawn for that
  opportunity; the agent defects iff B/7 > S.
- A defection pays the defector T=+3 and every other agent H=-1.
- Every other agent sees the defection with probability S and, if it sees it,
  punishes with probability V/7: the defector gets P=-9, the punisher pays E=-2.
- Metanorms mode only: an agent that saw a defection but did not punish it can
  itself be seen (probability S) by each remaining agent (the defector excluded),
  who meta-punishes with probability V/7: the non-punisher gets MP=-9, the
  meta-punisher pays ME=-2.
- After ``rounds_per_generation`` rounds (4 in Axelrod / the AS2 paper) payoffs
  are scored: agents >= mean + 1 SD get two offspring, <= mean - 1 SD get none,
  the rest one. The pool is trimmed/padded at random to keep the population
  size fixed, each of the 6 bits flips with probability ``mutation_rate``, and
  generation payoffs reset. 100 generations x 4 rounds = 400 steps.

Design note: agents are strategy carriers whose moves are fixed functions of
(B, V, S). Those rule-based moves are resolved here, inside ``step()``, so the
experiment makes no per-decision LLM calls. Per-agent strategy trajectories are
written to ``norms_agents.jsonl`` in this module's workspace
(``<run_dir>/env/NormsGameEnv/``); population series to ``norms_timeseries.jsonl``.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentsociety2.env import EnvBase, tool
from agentsociety2.storage.workspace_state import atomic_write_text

_LEVELS = 7  # 3-bit levels 0..7
_STATE_FILE = "state/ENV_STATE.json"


def _to_bits(level: int) -> str:
    return format(int(level), "03b")


class NormsGameEnv(EnvBase):
    """Axelrod (1986) Norms / Metanorms evolutionary game over a fixed population."""

    def __init__(
        self,
        agent_ids: Optional[List[int]] = None,
        game_mode: str = "norms",
        rounds_per_generation: int = 4,
        temptation: float = 3.0,
        hurt: float = -1.0,
        punishment: float = -9.0,
        enforcement_cost: float = -2.0,
        meta_punishment: float = -9.0,
        meta_enforcement_cost: float = -2.0,
        mutation_rate: float = 0.01,
        seed: int = 0,
    ):
        super().__init__()
        if game_mode not in ("norms", "metanorms"):
            raise ValueError("game_mode must be 'norms' or 'metanorms'")
        self.agent_ids = [int(a) for a in (agent_ids or range(1, 21))]
        if len(self.agent_ids) < 3:
            raise ValueError("NormsGameEnv needs at least 3 agents")
        self.game_mode = game_mode
        self.rounds_per_generation = int(rounds_per_generation)
        self.T, self.H = float(temptation), float(hurt)
        self.P, self.E = float(punishment), float(enforcement_cost)
        self.MP, self.ME = float(meta_punishment), float(meta_enforcement_cost)
        self.mutation_rate = float(mutation_rate)
        self.seed = int(seed)
        self._rng = random.Random(self.seed)
        # Initial strategies: B and V uniform over levels 0..7 (AS2 paper Sec. 7.1.2).
        self.boldness: Dict[int, int] = {}
        self.vengefulness: Dict[int, int] = {}
        for aid in self.agent_ids:
            self.boldness[aid] = self._rng.randint(0, _LEVELS)
            self.vengefulness[aid] = self._rng.randint(0, _LEVELS)
        self.gen_payoff: Dict[int, float] = {aid: 0.0 for aid in self.agent_ids}
        self.generation = 0
        self.round_in_generation = 0
        self._step_index = 0
        self._last_round: Dict[str, Any] = {}

    # ------------------------------------------------------------------ docs
    @classmethod
    def description(cls) -> str:
        return (
            "Axelrod (1986) Norms/Metanorms evolutionary game: boldness/vengefulness "
            "strategies, punishment, metanorm punishment, selection and mutation."
        )

    @classmethod
    def init_description(cls) -> str:
        return """NormsGameEnv: Axelrod (1986) evolutionary Norms / Metanorms game.

**Constructor kwargs (all optional):**
- **agent_ids** (list[int]): population member ids; must match the society's agent ids. Default 1..20.
- **game_mode** (str): "norms" (first-order punishment only) or "metanorms" (adds punishment of non-punishers).
- **rounds_per_generation** (int): interaction rounds (= simulation steps) per generation. Default 4.
- **temptation**, **hurt**, **punishment**, **enforcement_cost**, **meta_punishment**, **meta_enforcement_cost** (float): payoffs T=3, H=-1, P=-9, E=-2, MP=-9, ME=-2.
- **mutation_rate** (float): per-bit mutation probability at reproduction. Default 0.01.
- **seed** (int): RNG seed for strategies, visibility draws and evolution.

One simulation step runs one round; every rounds_per_generation steps the population reproduces.
"""

    # ------------------------------------------------------------------ tools
    @tool(readonly=True, kind="observe")
    async def get_agent_strategy(self, agent_id: int) -> Dict[str, Any]:
        """Return one agent's current **boldness** and **vengefulness** levels (0-7), its 6-bit strategy and its payoff accumulated in the current generation.

        - agent_id: the id of the agent to look up.
        """
        aid = int(agent_id)
        if aid not in self.boldness:
            return {"status": "fail", "reason": f"unknown agent_id {aid}"}
        return {
            "status": "success",
            "agent_id": aid,
            "boldness": self.boldness[aid],
            "vengefulness": self.vengefulness[aid],
            "strategy_bits": _to_bits(self.boldness[aid]) + _to_bits(self.vengefulness[aid]),
            "generation_payoff": round(self.gen_payoff[aid], 3),
            "generation": self.generation,
        }

    @tool(readonly=True, kind="statistics")
    async def get_population_statistics(self) -> Dict[str, Any]:
        """Return population-level **mean boldness**, **mean vengefulness** (0-7 scale), mean generation payoff, the (boldness, vengefulness) strategy distribution, and counts from the most recent round."""
        return {"status": "success", **self._population_stats(), "last_round": self._last_round}

    # ------------------------------------------------------------------ core
    def _population_stats(self) -> Dict[str, Any]:
        b = list(self.boldness.values())
        v = list(self.vengefulness.values())
        dist = Counter(f"B{x}V{y}" for x, y in zip(b, v))
        return {
            "generation": self.generation,
            "round_in_generation": self.round_in_generation,
            "mean_boldness": statistics.fmean(b),
            "mean_vengefulness": statistics.fmean(v),
            "mean_generation_payoff": statistics.fmean(self.gen_payoff.values()),
            "strategy_distribution": dict(sorted(dist.items())),
        }

    def _play_round(self) -> Dict[str, Any]:
        rng = self._rng
        ids = list(self.agent_ids)
        round_payoff = {aid: 0.0 for aid in ids}
        defections = punishments = meta_punishments = 0
        order = ids[:]
        rng.shuffle(order)
        for i in order:
            s = rng.random()  # chance of being seen for this defection opportunity
            if self.boldness[i] / _LEVELS <= s:
                continue
            defections += 1
            round_payoff[i] += self.T
            for j in ids:
                if j != i:
                    round_payoff[j] += self.H
            for j in ids:
                if j == i or rng.random() >= s:
                    continue  # j did not see the defection
                if rng.random() < self.vengefulness[j] / _LEVELS:
                    punishments += 1
                    round_payoff[i] += self.P
                    round_payoff[j] += self.E
                elif self.game_mode == "metanorms":
                    for k in ids:
                        if k in (i, j) or rng.random() >= s:
                            continue  # k did not see j's failure to punish
                        if rng.random() < self.vengefulness[k] / _LEVELS:
                            meta_punishments += 1
                            round_payoff[j] += self.MP
                            round_payoff[k] += self.ME
        for aid, p in round_payoff.items():
            self.gen_payoff[aid] += p
        return {
            "defections": defections,
            "punishments": punishments,
            "meta_punishments": meta_punishments,
            "mean_round_payoff": statistics.fmean(round_payoff.values()),
            "round_payoff": round_payoff,
        }

    def _reproduce(self) -> Dict[str, int]:
        """Axelrod's +/-1 SD selection rule, fixed-size pool, per-bit mutation."""
        rng = self._rng
        ids = list(self.agent_ids)
        scores = [self.gen_payoff[a] for a in ids]
        mean = statistics.fmean(scores)
        sd = statistics.pstdev(scores)
        pool: List[tuple] = []
        average_parents: List[tuple] = []
        for a, sc in zip(ids, scores):
            strat = (self.boldness[a], self.vengefulness[a])
            if sd > 0 and sc >= mean + sd:
                n_off = 2
            elif sd > 0 and sc <= mean - sd:
                n_off = 0
            else:
                n_off = 1
                average_parents.append(strat)
            pool.extend([strat] * n_off)
        # Keep population size fixed (Axelrod's rule does not guarantee it).
        survivors = pool or [(self.boldness[a], self.vengefulness[a]) for a in ids]
        while len(pool) > len(ids):
            pool.pop(rng.randrange(len(pool)))
        while len(pool) < len(ids):
            pool.append(rng.choice(average_parents or survivors))
        rng.shuffle(pool)
        mutations = 0
        for a, (b, v) in zip(ids, pool):
            bits = list(_to_bits(b) + _to_bits(v))
            for idx in range(6):
                if rng.random() < self.mutation_rate:
                    bits[idx] = "1" if bits[idx] == "0" else "0"
                    mutations += 1
            self.boldness[a] = int("".join(bits[:3]), 2)
            self.vengefulness[a] = int("".join(bits[3:]), 2)
        self.gen_payoff = {a: 0.0 for a in ids}
        return {"mutations": mutations}

    async def step(self, tick: int, t: datetime):
        self._step_index += 1
        self.round_in_generation += 1
        rnd = self._play_round()
        # Snapshot BEFORE reproduction so each row shows the strategies that played.
        stats = self._population_stats()
        agent_rows = [
            {
                "step": self._step_index,
                "generation": self.generation,
                "round_in_generation": self.round_in_generation,
                "agent_id": a,
                "boldness": self.boldness[a],
                "vengefulness": self.vengefulness[a],
                "strategy_bits": _to_bits(self.boldness[a]) + _to_bits(self.vengefulness[a]),
                "round_payoff": rnd["round_payoff"][a],
                "generation_payoff": self.gen_payoff[a],
            }
            for a in self.agent_ids
        ]
        reproduced = None
        if self.round_in_generation >= self.rounds_per_generation:
            reproduced = self._reproduce()
            self.generation += 1
            self.round_in_generation = 0
        self._last_round = {
            k: rnd[k] for k in ("defections", "punishments", "meta_punishments", "mean_round_payoff")
        }
        row = {
            "step": self._step_index,
            "t": t.isoformat(),
            "game_mode": self.game_mode,
            **stats,
            **self._last_round,
            "reproduced": reproduced is not None,
            "mutations": (reproduced or {}).get("mutations", 0),
        }
        self._append_jsonl("norms_timeseries.jsonl", [row])
        self._append_jsonl("norms_agents.jsonl", agent_rows)
        self.t = t

    # ----------------------------------------------------------- persistence
    def _append_jsonl(self, name: str, rows: List[Dict[str, Any]]) -> None:
        if self._workspace_root is None:
            return
        path = Path(self._workspace_root) / name
        with open(path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    async def to_workspace(self, workspace_path: Path | None = None) -> None:
        await super().to_workspace(workspace_path)
        if self._workspace_root is None:
            return
        state = {
            "boldness": self.boldness,
            "vengefulness": self.vengefulness,
            "gen_payoff": self.gen_payoff,
            "generation": self.generation,
            "round_in_generation": self.round_in_generation,
            "step_index": self._step_index,
            "rng_state": repr(self._rng.getstate()),
        }
        path = Path(self._workspace_root) / _STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(state))

    async def restore(self, workspace_path: Path) -> bool:
        await super().restore(workspace_path)
        path = Path(self._workspace_root) / _STATE_FILE
        if not path.exists():
            return False
        import ast

        state = json.loads(path.read_text(encoding="utf-8"))
        self.boldness = {int(k): int(v) for k, v in state["boldness"].items()}
        self.vengefulness = {int(k): int(v) for k, v in state["vengefulness"].items()}
        self.gen_payoff = {int(k): float(v) for k, v in state["gen_payoff"].items()}
        self.generation = int(state["generation"])
        self.round_in_generation = int(state["round_in_generation"])
        self._step_index = int(state["step_index"])
        self._rng.setstate(ast.literal_eval(state["rng_state"]))
        return True
