"""FGPCPublicGoodsLLMAgent - LLM participant for FGPCPublicGoodsEnv.

AgentSociety 2 paper Sec. 7.2: "represents participants in preference
elicitation, belief updating, and repeated contribution decisions".

Each simulation step the agent (1) reads its status from the env, (2) makes one
LLM decision returned as JSON - a strategy-method schedule in the P stage, or a
contribution plus a belief about the others' average in a C round - and (3)
submits it through the env router (template mode, so the generated call code is
cached after first use). Decisions and reasons are kept in AGENT.json.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import json_repair
from agentsociety2.agent.base import AgentBase


def _find_dict_with(obj: Any, key: str) -> dict | None:
    """Depth-first search for the first dict containing ``key`` (router results are free-form)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj
        for v in obj.values():
            hit = _find_dict_with(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            hit = _find_dict_with(v, key)
            if hit is not None:
                return hit
    return None


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    parsed = json_repair.loads(match.group(0) if match else (text or "{}"))
    return parsed if isinstance(parsed, dict) else {}


class FGPCPublicGoodsLLMAgent(AgentBase):
    """LLM participant in the Fischbacher & Gaechter (2010) P/C public goods experiment."""

    @classmethod
    def init_description(cls) -> str:
        return """FGPCPublicGoodsLLMAgent: LLM participant for FGPCPublicGoodsEnv.

**kwargs:** **id** (int, equals agent_id), optional **name** (str) and optional
**persona** (str, prepended to every decision prompt; omit for neutral participants).
"""

    # ------------------------------------------------------------ workspace
    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(json.dumps(config or {}, indent=2), encoding="utf-8")
        agent_id = int(profile.get("id", 0))
        meta = {"agent_class": cls.__name__, "id": agent_id,
                "name": str(profile.get("name") or f"Participant-{agent_id}"),
                "profile": profile, "step_count": 0, "decisions": []}
        (workspace_path / "AGENT.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    async def from_workspace(cls, workspace_path: Path, service_proxy: Any) -> "FGPCPublicGoodsLLMAgent":
        agent = cls()
        await agent._restore_game_state(workspace_path, service_proxy)
        return agent

    async def _restore_game_state(self, workspace_path: Path, service_proxy: Any) -> None:
        workspace_path = Path(workspace_path)
        cfg_path = workspace_path / "config.json"
        self._config = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        meta = json.loads((workspace_path / "AGENT.json").read_text(encoding="utf-8"))
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {})
        self._name = meta.get("name") or f"Participant-{self._id}"
        self._step_count = int(meta.get("step_count", 0))
        self.decisions: list[dict] = list(meta.get("decisions", []))
        self._bind_services(service_proxy)

    async def to_workspace(self, workspace_path: Path) -> None:
        meta = {"agent_class": type(self).__name__, "id": self._id, "name": self._name,
                "profile": self.get_profile(), "step_count": self._step_count,
                "decisions": self.decisions}
        (Path(workspace_path) / "AGENT.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------ prompts
    def _preamble(self, s: dict) -> str:
        e, m, n = s["endowment"], s["mpcr"], s["group_size"]
        persona = self.get_profile().get("persona")
        return (
            (f"{persona}\n\n" if persona else "")
            + f"You are participant #{self._id} in an economics experiment on group decision making.\n"
            f"Rules: you are in a group of {n} people. In each decision every member has {e} tokens and "
            f"decides how many tokens (0-{e}) to contribute to a group project; the rest they keep. "
            f"Every token contributed to the project by anyone pays {m} tokens to EACH of the {n} members.\n"
            f"Your earnings = {e} - (your contribution) + {m} x (sum of all {n} contributions). "
            f"Earnings are real to you: they are your payment for taking part."
        )

    def _history_text(self, s: dict) -> str:
        rows = s.get("history") or []
        if not rows:
            return "You have not played any contribution rounds yet."
        lines = ["Your previous rounds (your contribution / your estimate of the others' average / "
                 "the others' actual average / your earnings):"]
        for r in rows:
            belief = "-" if r.get("belief") is None else f"{r['belief']:.1f}"
            lines.append(f"  round {r['round']}: {r['contribution']} / {belief} / "
                         f"{r['others_average']:.2f} / {r['payoff']:.1f}")
        return "\n".join(lines)

    async def _llm_json(self, prompt: str) -> dict:
        resp = await self.acompletion([{"role": "user", "content": prompt}])
        return _parse_json(resp.choices[0].message.content or "")

    # ------------------------------------------------------------ env I/O
    async def _call(self, variables: dict, instruction: str, readonly: bool, key: str) -> dict | None:
        for template_mode in (True, False):  # retry once without the template cache
            try:
                results, _ = await self.ask_env({"variables": variables}, instruction,
                                                 readonly=readonly, template_mode=template_mode)
            except Exception as exc:  # router/transport failure
                self._logger.warning(f"[{self._name}] ask_env failed: {exc}")
                continue
            payload = _find_dict_with(results, key)
            if payload is not None and payload.get("status", "success") == "success":
                return payload
        return None

    async def _get_status(self) -> dict | None:
        return await self._call(
            {"agent_id": self._id},
            "Please call get_pg_status() with agent_id from ctx['variables'], store the returned "
            "dict in results['pg_status'], and set results['status'] to its 'status' value.",
            readonly=True, key="stage")

    # ------------------------------------------------------------ decisions
    async def _p_stage(self, s: dict) -> dict:
        e = s["endowment"]
        prior = ("\n" + self._history_text(s) + "\n") if s.get("history") else ""
        prompt = (
            self._preamble(s) + prior + "\n\nOne-shot decision (you will make it only once):\n"
            f"(a) UNCONDITIONAL contribution: how many tokens (0-{e}) do you contribute to the project?\n"
            f"(b) CONTRIBUTION TABLE: for each possible average contribution of the other "
            f"{s['group_size'] - 1} members (0, 1, 2, ..., {e} tokens), how many tokens (0-{e}) do you contribute?\n"
            f"For {s['group_size'] - 1} randomly chosen members of your group the unconditional contribution "
            "counts; for the remaining member the contribution table counts, applied to the average "
            "unconditional contribution of the others. Both decisions can therefore determine your earnings.\n"
            "Each table entry answers: \"If the other members contribute k tokens on average, "
            "how many tokens do I contribute?\"\n\n"
            'Respond with JSON only: {"reason": "<1-2 sentences>", "unconditional": <integer>, '
            '"conditional": {"0": <your contribution if the others average 0>, '
            '"1": <... if they average 1>, ..., '
            f'"{e}": <... if they average {e}>}}}}  (all {e + 1} keys "0".."{e}")'
        )
        d = await self._llm_json(prompt)
        raw = d.get("conditional") or []
        if isinstance(raw, dict):  # keyed by the others' average (the requested format)
            filled, last = [], None
            for k in range(e + 1):  # forward-fill any key the model skipped
                v = raw.get(str(k), raw.get(k))
                last = v if v is not None else last
                filled.append(last if last is not None else 0)
            raw = filled
        table = [int(round(float(x))) for x in raw][: e + 1]
        if len(table) < e + 1:  # pad a truncated table with its last value
            table += [table[-1] if table else 0] * (e + 1 - len(table))
        decision = {"stage": "P", "unconditional": int(round(float(d.get("unconditional", 0)))),
                    "conditional": table, "reason": str(d.get("reason", ""))}
        ok = await self._call(
            {"agent_id": self._id, "unconditional_contribution": decision["unconditional"],
             "conditional_contributions": table},
            "Please call submit_preference_schedule() using agent_id, unconditional_contribution and "
            "conditional_contributions from ctx['variables'], store the returned dict in "
            "results['p_submission'], and set results['status'] to its 'status' value.",
            readonly=False, key="response")
        decision["submitted"] = ok is not None
        return decision

    async def _c_round(self, s: dict) -> dict:
        e, n = s["endowment"], s["group_size"] - 1
        prompt = (
            self._preamble(s) + f"\n\nThis is contribution round {s['round']} of {s['num_rounds']} "
            f"with the same group.\n{self._history_text(s)}\n\n"
            f"Decide (1) your contribution this round (0-{e} tokens) and (2) your estimate of the "
            f"average contribution of the other {n} members this round (0-{e}). Accurate estimates earn "
            "a bonus: 3 tokens if exact, 2 if off by 1, 1 if off by 2.\n\n"
            'Respond with JSON only: {"reason": "<1-2 sentences>", "contribution": <integer>, '
            '"belief_others_average": <number>}'
        )
        d = await self._llm_json(prompt)
        decision = {"stage": "C", "round": s["round"],
                    "contribution": int(round(float(d.get("contribution", 0)))),
                    "belief": float(d.get("belief_others_average", 0)),
                    "reason": str(d.get("reason", ""))}
        ok = await self._call(
            {"agent_id": self._id, "contribution": decision["contribution"],
             "belief_others_average": decision["belief"]},
            "Please call submit_round_decision() using agent_id, contribution and "
            "belief_others_average from ctx['variables'], store the returned dict in "
            "results['c_submission'], and set results['status'] to its 'status' value.",
            readonly=False, key="response")
        decision["submitted"] = ok is not None
        return decision

    # ------------------------------------------------------------ lifecycle
    async def step(self, tick: int, t: datetime) -> str:
        self._step_count += 1
        status = await self._get_status()
        if status is None:
            return f"[{self._name}] could not read experiment status"
        if status["stage"] == "done" or status.get("already_submitted"):
            return f"[{self._name}] nothing to do (stage {status['stage']})"
        try:
            decision = await (self._p_stage(status) if status["stage"] == "P" else self._c_round(status))
        except Exception as exc:
            self._logger.error(f"[{self._name}] decision failed: {exc}")
            return f"[{self._name}] decision failed: {exc}"
        decision["t"] = t.isoformat()
        self.decisions.append(decision)
        return f"[{self._name}] {decision['stage']} decision submitted={decision['submitted']}"

    async def ask(self, message: str, readonly: bool = True, *, t: datetime | None = None) -> str:
        memory = json.dumps(self.decisions[-12:], ensure_ascii=False)
        prompt = (f"You are participant #{self._id} in a public goods experiment. "
                  f"Your recorded decisions so far: {memory}\n\n{message}")
        resp = await self.acompletion([{"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""
