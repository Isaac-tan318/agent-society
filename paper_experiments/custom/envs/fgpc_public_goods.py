"""FGPCPublicGoodsEnv - Fischbacher & Gaechter (2010) P/C public goods experiment.

Reproduces AgentSociety 2 paper Sec. 7.2 ("Public Goods Experiments"), based on
Fischbacher, U. & Gaechter, S. (2010) "Social preferences, beliefs, and the
dynamics of free riding in public goods experiments", AER 100(1).

Protocol:
- Linear public goods game, groups of ``group_size`` (4), endowment 20 tokens,
  marginal per-capita return ``mpcr`` 0.4: payoff_i = E - g_i + mpcr * sum_j g_j.
- P stage (one shot, strategy method): each agent submits an unconditional
  contribution and a conditional contribution table - how much it contributes
  for every possible (rounded) average contribution of the other members, 0..E.
- C stage: ``num_rounds`` (10) rounds; each round every agent submits a
  contribution and a belief about the others' average contribution. Beliefs
  earn a bonus of 3/2/1 points when off by 0/1/2 tokens (0 otherwise).
- ``stage_order`` "PC" = P stage at simulation step 1, C rounds at steps 2..11;
  "CP" = C rounds at steps 1..10, P stage at step 11.
- ``matching`` "partner" keeps groups fixed (the AS2 paper: 24 agents randomly
  assigned to six four-person groups); "stranger" re-draws groups every round.

Agents submit decisions during a simulation step; ``step()`` then resolves the
current stage. Data files in the module workspace (<run_dir>/env/FGPCPublicGoodsEnv/):
``pg_p_stage.jsonl``, ``pg_c_rounds.jsonl``, ``pg_round_summary.jsonl``.
"""

from __future__ import annotations

import ast
import json
import random
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentsociety2.env import EnvBase, tool
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_FILE = "state/ENV_STATE.json"


class FGPCPublicGoodsEnv(EnvBase):
    """Fischbacher & Gaechter (2010) two-stage (P/C) linear public goods experiment."""

    def __init__(
        self,
        agent_ids: Optional[List[int]] = None,
        group_size: int = 4,
        endowment: int = 20,
        mpcr: float = 0.4,
        num_rounds: int = 10,
        stage_order: str = "PC",
        matching: str = "partner",
        belief_bonus: bool = True,
        seed: int = 0,
    ):
        super().__init__()
        self.agent_ids = [int(a) for a in (agent_ids or range(1, 25))]
        self.group_size = int(group_size)
        if len(self.agent_ids) % self.group_size:
            raise ValueError("number of agents must be a multiple of group_size")
        if stage_order not in ("PC", "CP"):
            raise ValueError("stage_order must be 'PC' or 'CP'")
        if matching not in ("partner", "stranger"):
            raise ValueError("matching must be 'partner' or 'stranger'")
        self.endowment = int(endowment)
        self.mpcr = float(mpcr)
        self.num_rounds = int(num_rounds)
        self.stage_order = stage_order
        self.matching = matching
        self.belief_bonus = bool(belief_bonus)
        self.seed = int(seed)
        self._rng = random.Random(self.seed)
        self.schedule: List[Dict[str, Any]] = (
            [{"stage": "P"}] + [{"stage": "C", "round": r} for r in range(1, self.num_rounds + 1)]
            if stage_order == "PC"
            else [{"stage": "C", "round": r} for r in range(1, self.num_rounds + 1)] + [{"stage": "P"}]
        )
        self._cursor = 0  # index into schedule of the stage being collected
        self.groups: List[List[int]] = self._draw_groups()
        self._pending_c: Dict[int, Dict[str, Any]] = {}
        self._pending_p: Dict[int, Dict[str, Any]] = {}
        self.p_records: Dict[int, Dict[str, Any]] = {}
        self.history: Dict[int, List[Dict[str, Any]]] = {a: [] for a in self.agent_ids}
        self.cumulative_payoff: Dict[int, float] = {a: 0.0 for a in self.agent_ids}

    # ------------------------------------------------------------------ docs
    @classmethod
    def description(cls) -> str:
        return ("Fischbacher & Gaechter (2010) public goods experiment: strategy-method "
                "preference elicitation (P) and repeated contributions with beliefs (C).")

    @classmethod
    def init_description(cls) -> str:
        return """FGPCPublicGoodsEnv: two-stage (P/C) linear public goods experiment.

**Constructor kwargs (all optional):**
- **agent_ids** (list[int]): participant ids (multiple of group_size). Default 1..24.
- **group_size** (int): members per group. Default 4.
- **endowment** (int): tokens per round. Default 20.
- **mpcr** (float): marginal per-capita return of the project. Default 0.4.
- **num_rounds** (int): C-stage rounds. Default 10.
- **stage_order** (str): "PC" (P stage first) or "CP" (C stage first).
- **matching** (str): "partner" (fixed groups) or "stranger" (regrouped every round).
- **belief_bonus** (bool): pay 3/2/1 points for beliefs off by 0/1/2 tokens.
- **seed** (int): RNG seed for group assignment.

One simulation step collects one stage: the P stage or one C round.
"""

    # ------------------------------------------------------------ helpers
    def _draw_groups(self) -> List[List[int]]:
        ids = self.agent_ids[:]
        self._rng.shuffle(ids)
        return [sorted(ids[i:i + self.group_size]) for i in range(0, len(ids), self.group_size)]

    def _group_of(self, aid: int) -> List[int]:
        for g in self.groups:
            if aid in g:
                return g
        return []

    def _current(self) -> Dict[str, Any]:
        return self.schedule[self._cursor] if self._cursor < len(self.schedule) else {"stage": "done"}

    def _clip(self, x: Any) -> int:
        return max(0, min(self.endowment, int(round(float(x)))))

    # ------------------------------------------------------------------ tools
    @tool(readonly=True, kind="observe")
    async def get_pg_status(self, agent_id: int) -> Dict[str, Any]:
        """Return this participant's view of the experiment: the current **stage** ("P", "C" or "done"), the C-stage **round**, the rules (endowment, mpcr, group size, number of rounds), whether a decision was already submitted this step, and the participant's own C-stage **history** (own contribution, belief, others' average contribution, earnings per round).

        - agent_id: the participant's id.
        """
        aid = int(agent_id)
        if aid not in self.history:
            return {"status": "fail", "reason": f"unknown agent_id {aid}"}
        cur = self._current()
        submitted = aid in (self._pending_p if cur["stage"] == "P" else self._pending_c)
        return {
            "status": "success",
            "agent_id": aid,
            "stage": cur["stage"],
            "round": cur.get("round"),
            "num_rounds": self.num_rounds,
            "stage_order": self.stage_order,
            "p_stage_done": aid in self.p_records,
            "endowment": self.endowment,
            "mpcr": self.mpcr,
            "group_size": self.group_size,
            "already_submitted": submitted,
            "history": self.history[aid],
            "cumulative_payoff": round(self.cumulative_payoff[aid], 2),
        }

    @tool(readonly=False)
    async def submit_preference_schedule(
        self, agent_id: int, unconditional_contribution: int, conditional_contributions: List[int]
    ) -> Dict[str, Any]:
        """P stage only. Record a participant's **unconditional_contribution** (0..endowment tokens) and its **conditional_contributions** table: a list with one entry for every possible average contribution of the other group members (0, 1, ..., endowment), giving the tokens the participant would contribute in that case. Resubmitting in the same stage overwrites the earlier entry.

        - agent_id: the participant's id.
        - unconditional_contribution: integer tokens.
        - conditional_contributions: list of endowment+1 integers.
        """
        aid = int(agent_id)
        if self._current()["stage"] != "P":
            return {"status": "fail", "reason": "the P stage is not active in this step"}
        table = list(conditional_contributions or [])
        if len(table) != self.endowment + 1:
            return {"status": "fail",
                    "reason": f"conditional_contributions needs {self.endowment + 1} entries, got {len(table)}"}
        self._pending_p[aid] = {
            "unconditional": self._clip(unconditional_contribution),
            "conditional": [self._clip(x) for x in table],
        }
        return {"status": "success", "response": "preference schedule recorded"}

    @tool(readonly=False)
    async def submit_round_decision(
        self, agent_id: int, contribution: int, belief_others_average: float
    ) -> Dict[str, Any]:
        """C stage only. Record a participant's **contribution** to the group project this round (0..endowment tokens) and its **belief_others_average**, the expected average contribution of the other group members this round. Resubmitting in the same round overwrites the earlier entry.

        - agent_id: the participant's id.
        - contribution: integer tokens.
        - belief_others_average: number between 0 and endowment.
        """
        aid = int(agent_id)
        if self._current()["stage"] != "C":
            return {"status": "fail", "reason": "no C-stage round is active in this step"}
        belief = max(0.0, min(float(self.endowment), float(belief_others_average)))
        self._pending_c[aid] = {"contribution": self._clip(contribution), "belief": belief}
        return {"status": "success", "response": "round decision recorded"}

    @tool(readonly=True, kind="statistics")
    async def get_experiment_statistics(self) -> Dict[str, Any]:
        """Return experiment-wide statistics: current stage, number of completed C rounds, mean contribution and mean belief of the latest round, and how many P-stage schedules were collected."""
        last = [h[-1] for h in self.history.values() if h]
        return {
            "status": "success",
            "stage": self._current()["stage"],
            "completed_rounds": max((len(h) for h in self.history.values()), default=0),
            "latest_mean_contribution": statistics.fmean(r["contribution"] for r in last) if last else None,
            "latest_mean_belief": statistics.fmean(r["belief"] for r in last) if last else None,
            "p_schedules_collected": len(self.p_records),
        }

    # ------------------------------------------------------------------ step
    async def step(self, tick: int, t: datetime):
        cur = self._current()
        if cur["stage"] == "P":
            rows = []
            for aid in self.agent_ids:
                rec = self._pending_p.get(aid)
                self.p_records[aid] = rec or {"unconditional": None, "conditional": None}
                rows.append({"agent_id": aid, "stage_order": self.stage_order,
                             "submitted": rec is not None, **self.p_records[aid]})
            self._append_jsonl("pg_p_stage.jsonl", rows)
            self._pending_p = {}
            self._cursor += 1
        elif cur["stage"] == "C":
            self._resolve_round(cur["round"], t)
            self._pending_c = {}
            self._cursor += 1
            if self.matching == "stranger":
                self.groups = self._draw_groups()
        self.t = t

    def _resolve_round(self, rnd: int, t: datetime) -> None:
        rows = []
        for gi, group in enumerate(self.groups):
            decisions = {a: self._pending_c.get(a) for a in group}
            contrib = {a: (d["contribution"] if d else 0) for a, d in decisions.items()}
            total = sum(contrib.values())
            for a in group:
                others = [contrib[o] for o in group if o != a]
                others_avg = sum(others) / len(others)
                payoff = self.endowment - contrib[a] + self.mpcr * total
                belief = decisions[a]["belief"] if decisions[a] else None
                bonus = 0.0
                if self.belief_bonus and belief is not None:
                    err = abs(round(belief) - round(others_avg))
                    bonus = {0: 3.0, 1: 2.0, 2: 1.0}.get(err, 0.0)
                self.cumulative_payoff[a] += payoff + bonus
                rec = {"round": rnd, "group": gi, "contribution": contrib[a],
                       "belief": belief, "others_average": round(others_avg, 3),
                       "group_total": total, "payoff": round(payoff, 3),
                       "belief_bonus": bonus, "submitted": decisions[a] is not None}
                self.history[a].append(rec)
                rows.append({"agent_id": a, "stage_order": self.stage_order, "t": t.isoformat(), **rec})
        self._append_jsonl("pg_c_rounds.jsonl", rows)
        submitted = [r for r in rows if r["submitted"]]
        self._append_jsonl("pg_round_summary.jsonl", [{
            "round": rnd, "stage_order": self.stage_order,
            "mean_contribution": statistics.fmean(r["contribution"] for r in rows),
            "mean_belief": statistics.fmean(r["belief"] for r in submitted) if submitted else None,
            "submission_rate": len(submitted) / len(rows),
        }])

    # ----------------------------------------------------------- persistence
    def _append_jsonl(self, name: str, rows: List[Dict[str, Any]]) -> None:
        if self._workspace_root is None:
            return
        with open(Path(self._workspace_root) / name, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    async def to_workspace(self, workspace_path: Path | None = None) -> None:
        await super().to_workspace(workspace_path)
        if self._workspace_root is None:
            return
        state = {"cursor": self._cursor, "groups": self.groups, "p_records": self.p_records,
                 "history": self.history, "cumulative_payoff": self.cumulative_payoff,
                 "rng_state": repr(self._rng.getstate())}
        path = Path(self._workspace_root) / _STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(state))

    async def restore(self, workspace_path: Path) -> bool:
        await super().restore(workspace_path)
        path = Path(self._workspace_root) / _STATE_FILE
        if not path.exists():
            return False
        s = json.loads(path.read_text(encoding="utf-8"))
        self._cursor = int(s["cursor"])
        self.groups = [[int(a) for a in g] for g in s["groups"]]
        self.p_records = {int(k): v for k, v in s["p_records"].items()}
        self.history = {int(k): v for k, v in s["history"].items()}
        self.cumulative_payoff = {int(k): float(v) for k, v in s["cumulative_payoff"].items()}
        self._rng.setstate(ast.literal_eval(s["rng_state"]))
        return True
