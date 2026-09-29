"""NewsConsumerAgent - ideological social-media news user for NewsPolarizationEnv.

AgentSociety 2 paper Sec. 7.5: the agent "first records the response to the
subscription offer, then retrieves a personalized feed, reads a small number
of posts according to rank and ideological relevance, and shares selected
posts ... The agent then reports affective measures".

Per simulation step the agent reads its briefing from the env and makes ONE
LLM decision: in the offer step, which offered outlets to follow; in a week
step, which feed posts to read and share plus party feeling thermometers.
Survey questions (baseline / endline questionnaire steps) are answered by ask(),
which includes the agent's accumulated reading history.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import json_repair
from agentsociety2.agent.base import AgentBase


def _find_dict_with(obj: Any, key: str) -> dict | None:
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


PARTY = {"liberal": "Democratic", "conservative": "Republican"}


class NewsConsumerAgent(AgentBase):
    """Ideological news consumer: subscription choice, feed reading/sharing, affect reports (LLM)."""

    @classmethod
    def init_description(cls) -> str:
        return """NewsConsumerAgent: LLM news user for NewsPolarizationEnv.

**kwargs:** **id** (int, equals agent_id), **name**, **ideology** ("liberal"/"conservative"),
**ideology_score** (-1 very liberal .. +1 very conservative), **age**, **gender**,
**education**, **region**, **news_habits** (str). Any extra kwargs are kept in the profile.
"""

    # ------------------------------------------------------------ workspace
    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(json.dumps(config or {}, indent=2), encoding="utf-8")
        agent_id = int(profile.get("id", 0))
        meta = {"agent_class": cls.__name__, "id": agent_id,
                "name": str(profile.get("name") or f"User-{agent_id}"), "profile": profile,
                "step_count": 0, "followed_from_offer": None, "offer_reason": None, "reading_log": [], "weekly_reports": []}
        (workspace_path / "AGENT.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    async def from_workspace(cls, workspace_path: Path, service_proxy: Any) -> "NewsConsumerAgent":
        agent = cls()
        await agent._restore_user_state(workspace_path, service_proxy)
        return agent

    async def _restore_user_state(self, workspace_path: Path, service_proxy: Any) -> None:
        workspace_path = Path(workspace_path)
        cfg_path = workspace_path / "config.json"
        self._config = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        meta = json.loads((workspace_path / "AGENT.json").read_text(encoding="utf-8"))
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {})
        self._name = meta.get("name") or f"User-{self._id}"
        self._step_count = int(meta.get("step_count", 0))
        self.followed_from_offer = meta.get("followed_from_offer")
        self.offer_reason = meta.get("offer_reason")
        self.reading_log: list[dict] = list(meta.get("reading_log", []))
        self.weekly_reports: list[dict] = list(meta.get("weekly_reports", []))
        self._bind_services(service_proxy)

    async def to_workspace(self, workspace_path: Path) -> None:
        meta = {"agent_class": type(self).__name__, "id": self._id, "name": self._name,
                "profile": self.get_profile(), "step_count": self._step_count,
                "followed_from_offer": self.followed_from_offer, "offer_reason": self.offer_reason,
                "reading_log": self.reading_log, "weekly_reports": self.weekly_reports}
        (Path(workspace_path) / "AGENT.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------ prompts
    def _persona(self) -> str:
        p = self.get_profile()
        ideo = p.get("ideology", "liberal")
        return (
            f"You are {self._name}, a {p.get('age', 40)}-year-old {p.get('gender', 'person')} living in the "
            f"{p.get('region', 'United States')} with {p.get('education', 'some college')} education. "
            f"Politically you are {ideo} and identify with the {PARTY.get(ideo, 'Democratic')} Party "
            f"(ideology {float(p.get('ideology_score', 0)):+.2f} on a scale from -1 = very liberal to "
            f"+1 = very conservative). News habits: {p.get('news_habits', 'you read news on Facebook')}. "
            "The year is 2018."
        )

    def _history_summary(self) -> str:
        if not self.reading_log:
            base = "You have not read any posts in this study period yet."
        else:
            by_lean = Counter(r["lean"] for r in self.reading_log)
            recent = "; ".join(f"{r['outlet']} ({r['lean']}): \"{r['headline']}\"" for r in self.reading_log[-6:])
            base = (f"Over the past weeks you read {len(self.reading_log)} news posts on Facebook: "
                    f"{by_lean.get('liberal', 0)} from liberal outlets and {by_lean.get('conservative', 0)} "
                    f"from conservative outlets. Most recent: {recent}.")
        if self.followed_from_offer:
            base += f" Earlier you chose to follow these outlets' pages: {', '.join(self.followed_from_offer)}."
        return base

    async def _llm_json(self, prompt: str) -> dict:
        resp = await self.acompletion([{"role": "user", "content": prompt}])
        return _parse_json(resp.choices[0].message.content or "")

    # ------------------------------------------------------------ env I/O
    async def _call(self, variables: dict, instruction: str, readonly: bool, key: str) -> dict | None:
        for template_mode in (True, False):
            try:
                results, _ = await self.ask_env({"variables": variables}, instruction,
                                                 readonly=readonly, template_mode=template_mode)
            except Exception as exc:
                self._logger.warning(f"[{self._name}] ask_env failed: {exc}")
                continue
            payload = _find_dict_with(results, key)
            if payload is not None and payload.get("status", "success") == "success":
                return payload
        return None

    # ------------------------------------------------------------ lifecycle
    async def step(self, tick: int, t: datetime) -> str:
        self._step_count += 1
        brief = await self._call(
            {"agent_id": self._id},
            "Please call get_week_briefing() with agent_id from ctx['variables'], store the returned "
            "dict in results['briefing'], and set results['status'] to its 'status' value.",
            readonly=True, key="stage")
        if brief is None:
            return f"[{self._name}] could not read briefing"
        if brief.get("already_submitted") or brief["stage"] == "done":
            return f"[{self._name}] nothing to do"
        try:
            if brief["stage"] == "offer":
                return await self._handle_offer(brief)
            return await self._handle_week(brief)
        except Exception as exc:
            self._logger.error(f"[{self._name}] step failed: {exc}")
            return f"[{self._name}] step failed: {exc}"

    async def _handle_offer(self, brief: dict) -> str:
        offer = brief.get("offer") or []
        if not offer:
            self.followed_from_offer = []
            return f"[{self._name}] no subscription offer"
        listing = "\n".join(f"- {o['outlet_id']}: {o['name']} ({o['lean']} news outlet)" for o in offer)
        prompt = (
            f"{self._persona()}\n\nYou are taking part in a research survey about news on social media. "
            "The researchers ask you to subscribe to (\"like\") the Facebook pages of the news outlets "
            "below, so that their posts appear in your news feed over the next weeks. This request is "
            f"voluntary: you may like all, some, or none of them.\n{listing}\n\n"
            "Decide as this person really would. Respond with JSON only: "
            '{"reason": "<1-2 sentences>", "follow": [<outlet ids you like>]}'
        )
        d = await self._llm_json(prompt)
        self.offer_reason = str(d.get("reason", ""))
        offered = {o["outlet_id"]: o["name"] for o in offer}
        follow = [str(x) for x in (d.get("follow") or []) if str(x) in offered]
        ok = await self._call(
            {"agent_id": self._id, "accepted_outlet_ids": follow},
            "Please call respond_to_offer() using agent_id and accepted_outlet_ids from "
            "ctx['variables'], store the returned dict in results['offer_response'], and set "
            "results['status'] to its 'status' value.",
            readonly=False, key="response")
        self.followed_from_offer = [offered[o] for o in follow]
        return f"[{self._name}] followed {len(follow)}/{len(offer)} offered outlets (saved={ok is not None})"

    async def _handle_week(self, brief: dict) -> str:
        feed = brief.get("feed") or []
        lines = [f"{p['rank']}. [{p['post_id']}] {p['outlet']} ({p['lean']} outlet), {p['topic']}: "
                 f"\"{p['headline']}\" - {p['snippet']}" for p in feed]
        prompt = (
            f"{self._persona()}\n\n{self._history_summary()}\n\n"
            f"It is week {brief['week']} of the study. Your Facebook news feed this week, in the order "
            "the platform shows it:\n" + ("\n".join(lines) if lines else "(your feed is empty this week)") +
            "\n\nLike a typical user you read only a few posts (0-3) and rarely share. Choose which posts "
            "to read and which of those to share. Then, having read them, rate how you feel toward each "
            "party on a 0-100 feeling thermometer (0 = very cold/unfavorable, 100 = very warm/favorable).\n"
            'Respond with JSON only: {"reason": "<1-2 sentences>", "read": [<post ids>], '
            '"share": [<post ids>], "democrats_feeling": <0-100>, "republicans_feeling": <0-100>}'
        )
        d = await self._llm_json(prompt)
        by_id = {p["post_id"]: p for p in feed}
        reads = [str(x) for x in (d.get("read") or []) if str(x) in by_id][:5]
        shares = [str(x) for x in (d.get("share") or []) if str(x) in by_id]
        dem = int(round(float(d.get("democrats_feeling", 50))))
        rep = int(round(float(d.get("republicans_feeling", 50))))
        own, other = (dem, rep) if self.get_profile().get("ideology") == "liberal" else (rep, dem)
        ok = await self._call(
            {"agent_id": self._id, "read_post_ids": reads, "shared_post_ids": shares,
             "own_party_feeling": own, "other_party_feeling": other},
            "Please call submit_week_actions() using agent_id, read_post_ids, shared_post_ids, "
            "own_party_feeling and other_party_feeling from ctx['variables'], store the returned dict in "
            "results['week_submission'], and set results['status'] to its 'status' value.",
            readonly=False, key="response")
        for pid in reads:
            p = by_id[pid]
            self.reading_log.append({"week": brief["week"], "outlet": p["outlet"], "lean": p["lean"],
                                     "topic": p["topic"], "headline": p["headline"]})
        self.weekly_reports.append({"week": brief["week"], "reads": reads, "shares": shares,
                                    "democrats_feeling": dem, "republicans_feeling": rep,
                                    "saved": ok is not None, "reason": str(d.get("reason", ""))})
        return f"[{self._name}] week {brief['week']}: read {len(reads)}, shared {len(shares)}"

    async def ask(self, message: str, readonly: bool = True, *, t: datetime | None = None) -> str:
        prompt = f"{self._persona()}\n\n{self._history_summary()}\n\n{message}"
        resp = await self.acompletion([{"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""
