"""NewsPolarizationEnv - Levy (2021) news-feed subscription field experiment.

Reproduces AgentSociety 2 paper Sec. 7.5 ("Mechanisms behind Opinion
Polarization"), based on Levy, R. (2021) "Social Media, News Consumption, and
Polarization: Evidence from a Field Experiment", AER 111(3).

Mechanisms kept separate, as in the paper:
1. Voluntary subscription. Treatment agents get an offer of up to 4 outlets
   (pro-attitudinal = own side, counter-attitudinal = other side); an offered
   primary outlet the agent already follows is swapped for a replacement outlet.
2. Algorithmic ranking. Each week every followed outlet publishes
   ``posts_per_outlet`` posts; an agent's feed holds its followed outlets' posts
   ranked by a random engagement score minus ``algorithm_filter_strength`` for
   counter-attitudinal posts, truncated to ``feed_size`` (paper: 20, 3, 0.4).

Schedule (one simulation step each): step 1 = offer step (agents answer the
offer; control agents have none), steps 2..9 = weeks 1..8 (agents read, share
and report party feeling thermometers). Feeds for week k are built at the end of
the previous step, so offer acceptances shape exposure from week 1 onward.

Outlet names are fictional; ideology scores are stylized. Data files in the
module workspace (<run_dir>/env/NewsPolarizationEnv/): ``np_offers.jsonl``,
``np_weekly.jsonl`` (per agent-week exposure/reading/affect),
``np_posts.jsonl`` (all generated posts).
"""

from __future__ import annotations

import ast
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentsociety2.env import EnvBase, tool
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_FILE = "state/ENV_STATE.json"

OUTLETS: Dict[str, Dict[str, Any]] = {
    # id: (name, lean, ideology score, role)
    "L1": {"name": "The Progressive Daily", "lean": "liberal", "score": -0.9, "role": "primary"},
    "L2": {"name": "Metro Liberal Times", "lean": "liberal", "score": -0.8, "role": "primary"},
    "L3": {"name": "Blue Horizon News", "lean": "liberal", "score": -0.7, "role": "primary"},
    "L4": {"name": "The Forward Post", "lean": "liberal", "score": -0.6, "role": "primary"},
    "L5": {"name": "Civic Voice", "lean": "liberal", "score": -0.8, "role": "replacement"},
    "L6": {"name": "People's Ledger", "lean": "liberal", "score": -0.7, "role": "replacement"},
    "L7": {"name": "Open Society Report", "lean": "liberal", "score": -0.6, "role": "replacement"},
    "L8": {"name": "The Commons Herald", "lean": "liberal", "score": -0.5, "role": "replacement"},
    "C1": {"name": "The Liberty Sentinel", "lean": "conservative", "score": 0.9, "role": "primary"},
    "C2": {"name": "Heartland Herald", "lean": "conservative", "score": 0.8, "role": "primary"},
    "C3": {"name": "Patriot Review", "lean": "conservative", "score": 0.7, "role": "primary"},
    "C4": {"name": "The American Standard", "lean": "conservative", "score": 0.6, "role": "primary"},
    "C5": {"name": "Frontier Tribune", "lean": "conservative", "score": 0.8, "role": "replacement"},
    "C6": {"name": "Main Street Journal", "lean": "conservative", "score": 0.7, "role": "replacement"},
    "C7": {"name": "Constitution Daily", "lean": "conservative", "score": 0.6, "role": "replacement"},
    "C8": {"name": "The Republic Wire", "lean": "conservative", "score": 0.5, "role": "replacement"},
}

# 2018 study-period topics with a liberal-slant and a conservative-slant headline + snippet.
TOPICS: Dict[str, Dict[str, tuple]] = {
    "gun policy": {
        "liberal": ("Students demand action on gun safety as lawmakers stall",
                    "After the Parkland shooting, survivors say inaction on background checks costs lives."),
        "conservative": ("Gun owners warn new restrictions punish the law-abiding",
                         "Second Amendment advocates say proposed bans would not have stopped recent attacks."),
    },
    "immigration": {
        "liberal": ("Dreamers face an uncertain future as the DACA deadline passes",
                    "Young immigrants brought here as children fear deportation from the only home they know."),
        "conservative": ("Border hawks push back on amnesty for illegal immigration",
                         "Supporters of tougher enforcement say rewarding illegal entry invites more of it."),
    },
    "taxes": {
        "liberal": ("Analysis: tax law's gains flow mostly to corporations and the wealthy",
                    "Critics say the new tax cuts will balloon the deficit while wages barely move."),
        "conservative": ("Workers see bigger paychecks and bonuses after tax cuts",
                         "Business owners credit the tax overhaul for new hiring and investment plans."),
    },
    "trade": {
        "liberal": ("Economists warn steel tariffs could spark a costly trade war",
                    "Manufacturers that buy steel say prices are already rising for consumers."),
        "conservative": ("New tariffs stand up for American steelworkers against unfair trade",
                         "Steel towns cheer protections they say were overdue after decades of job losses."),
    },
    "russia investigation": {
        "liberal": ("Special counsel probe widens as new indictments land",
                    "Legal experts say the investigation is uncovering serious election interference."),
        "conservative": ("Critics call the Russia probe a partisan fishing expedition",
                         "Opponents say the investigation has cost millions without evidence of collusion."),
    },
    "health care": {
        "liberal": ("Millions at risk as health-law protections erode",
                    "Patient groups warn weakened coverage rules threaten people with pre-existing conditions."),
        "conservative": ("Families say Obamacare premiums keep climbing out of reach",
                         "Small-business owners describe coverage costs that rise faster than their incomes."),
    },
    "north korea": {
        "liberal": ("Experts caution summit talk without a plan is risky",
                    "Diplomats say unpredictable threats could backfire in nuclear negotiations."),
        "conservative": ("Tough stance brings North Korea to the negotiating table",
                         "Supporters credit maximum pressure for opening a path to talks."),
    },
    "courts": {
        "liberal": ("Advocates fear court shift threatens civil rights",
                    "Civil-liberties groups say new judges could roll back hard-won protections."),
        "conservative": ("Constitutionalist judges confirmed at a record pace",
                         "Conservatives say new judges will interpret the law as written."),
    },
    "economy": {
        "liberal": ("Wage growth lags as gains concentrate at the top",
                    "Workers say rising costs eat up modest raises while profits surge."),
        "conservative": ("Unemployment hits new lows as business confidence soars",
                         "Employers report strong demand and optimism about the year ahead."),
    },
    "environment": {
        "liberal": ("EPA rollbacks threaten clean air and water, scientists say",
                    "Researchers warn loosened rules will raise pollution in vulnerable communities."),
        "conservative": ("EPA cuts red tape that strangled farmers and small firms",
                         "Rural businesses welcome relief from rules they call costly and confusing."),
    },
}


class NewsPolarizationEnv(EnvBase):
    """Levy (2021) news-feed experiment: subscription offers, ranked feeds, reading, sharing, affect."""

    def __init__(
        self,
        agent_specs: Optional[List[Dict[str, Any]]] = None,
        condition: str = "control",
        num_weeks: int = 8,
        feed_size: int = 20,
        posts_per_outlet: int = 3,
        algorithm_filter_strength: float = 0.4,
        max_offered_outlets: int = 4,
        seed: int = 0,
    ):
        super().__init__()
        if condition not in ("control", "pro", "counter"):
            raise ValueError("condition must be 'control', 'pro' or 'counter'")
        specs = agent_specs or [
            {"id": 1, "ideology": "liberal", "baseline_subscriptions": ["L1", "L6"]},
            {"id": 2, "ideology": "conservative", "baseline_subscriptions": ["C2", "C5"]},
        ]
        self.ideology: Dict[int, str] = {int(s["id"]): s["ideology"] for s in specs}
        self.subscriptions: Dict[int, List[str]] = {
            int(s["id"]): list(dict.fromkeys(s.get("baseline_subscriptions", []))) for s in specs
        }
        self.agent_ids = sorted(self.ideology)
        self.condition = condition
        self.num_weeks = int(num_weeks)
        self.feed_size = int(feed_size)
        self.posts_per_outlet = int(posts_per_outlet)
        self.filter_strength = float(algorithm_filter_strength)
        self.max_offered = int(max_offered_outlets)
        self.seed = int(seed)
        self._rng = random.Random(self.seed)
        self.offers: Dict[int, List[str]] = {a: self._make_offer(a) for a in self.agent_ids}
        self.offer_response: Dict[int, Optional[List[str]]] = {a: None for a in self.agent_ids}
        self._step_index = 0  # 0 = offer step pending; k = week k pending
        self._post_counter = 0
        self.posts: Dict[str, Dict[str, Any]] = {}
        self.feeds: Dict[int, List[Dict[str, Any]]] = {}
        self._feed_meta: Dict[int, Dict[str, Any]] = {}
        self._pending: Dict[int, Dict[str, Any]] = {}
        self.cumulative_counter_reads: Dict[int, int] = {a: 0 for a in self.agent_ids}

    # ------------------------------------------------------------------ docs
    @classmethod
    def description(cls) -> str:
        return ("Levy (2021) news-feed experiment: outlet subscription offers, algorithmically "
                "ranked weekly feeds, reading, sharing and affective reports.")

    @classmethod
    def init_description(cls) -> str:
        return """NewsPolarizationEnv: Facebook-style news feed for the Levy (2021) polarization experiment.

**Constructor kwargs:**
- **agent_specs** (list[dict]): one dict per agent with **id** (int), **ideology** ("liberal" or "conservative") and **baseline_subscriptions** (list of outlet ids L1-L8 / C1-C8).
- **condition** (str): "control" (no offer), "pro" (offer own-side outlets) or "counter" (offer other-side outlets).
- **num_weeks** (int): weekly interaction steps after the offer step. Default 8.
- **feed_size** (int): posts per weekly feed. Default 20.
- **posts_per_outlet** (int): posts each outlet publishes per week. Default 3.
- **algorithm_filter_strength** (float): ranking penalty for counter-attitudinal posts. Default 0.4.
- **max_offered_outlets** (int): outlets per offer. Default 4.
- **seed** (int): RNG seed.

Simulation step 1 is the offer step; steps 2..num_weeks+1 are weeks 1..num_weeks.
"""

    # ----------------------------------------------------------- mechanics
    def _make_offer(self, aid: int) -> List[str]:
        if self.condition == "control":
            return []
        own = self.ideology[aid]
        side = own if self.condition == "pro" else ("conservative" if own == "liberal" else "liberal")
        followed = set(self.subscriptions[aid])
        primary = [o for o, m in OUTLETS.items() if m["lean"] == side and m["role"] == "primary"]
        spare = [o for o, m in OUTLETS.items()
                 if m["lean"] == side and m["role"] == "replacement" and o not in followed]
        offer = []
        for o in primary:
            if o not in followed:
                offer.append(o)
            elif spare:
                offer.append(spare.pop(0))
        return offer[: self.max_offered]

    def _is_counter(self, aid: int, lean: str) -> bool:
        return lean != self.ideology[aid]

    def _publish_week(self, week: int) -> None:
        followed = sorted({o for subs in self.subscriptions.values() for o in subs})
        topics = list(TOPICS)
        week_posts: Dict[str, List[str]] = {}
        rows = []
        for o in followed:
            meta = OUTLETS[o]
            ids = []
            for topic in self._rng.sample(topics, k=min(self.posts_per_outlet, len(topics))):
                self._post_counter += 1
                pid = f"p{self._post_counter}"
                headline, snippet = TOPICS[topic][meta["lean"]]
                post = {"post_id": pid, "outlet_id": o, "outlet": meta["name"], "lean": meta["lean"],
                        "ideology_score": meta["score"], "topic": topic, "week": week,
                        "headline": headline, "snippet": snippet}
                self.posts[pid] = post
                ids.append(pid)
                rows.append(post)
            week_posts[o] = ids
        self._append_jsonl("np_posts.jsonl", rows)
        self.feeds, self._feed_meta = {}, {}
        for aid in self.agent_ids:
            cands = [pid for o in self.subscriptions[aid] for pid in week_posts.get(o, [])]
            scored = []
            for pid in cands:
                penalty = self.filter_strength if self._is_counter(aid, self.posts[pid]["lean"]) else 0.0
                scored.append((self._rng.random() - penalty, pid))
            scored.sort(reverse=True)
            feed_ids = [pid for _, pid in scored[: self.feed_size]]
            self.feeds[aid] = [dict(self.posts[pid], rank=r + 1) for r, pid in enumerate(feed_ids)]
            n_c = sum(self._is_counter(aid, self.posts[p]["lean"]) for p in cands)
            n_f = sum(self._is_counter(aid, self.posts[p]["lean"]) for p in feed_ids)
            self._feed_meta[aid] = {
                "n_candidates": len(cands),
                "candidate_counter_share": n_c / len(cands) if cands else 0.0,
                "feed_counter_share": n_f / len(feed_ids) if feed_ids else 0.0,
                "feed_ids": feed_ids,
            }

    def _stage(self) -> Dict[str, Any]:
        if self._step_index == 0:
            return {"stage": "offer", "week": 0}
        if self._step_index <= self.num_weeks:
            return {"stage": "week", "week": self._step_index}
        return {"stage": "done", "week": self.num_weeks}

    # ------------------------------------------------------------------ tools
    @tool(readonly=True, kind="observe")
    async def get_week_briefing(self, agent_id: int) -> Dict[str, Any]:
        """Return this user's news-feed briefing: the current **stage** ("offer", "week" or "done"), the **week** number, the outlets the user follows, any pending subscription **offer** (outlet ids, names and leanings), and in a week stage the ranked **feed** of posts (post_id, outlet, leaning, topic, headline, snippet, rank).

        - agent_id: the user's id.
        """
        aid = int(agent_id)
        if aid not in self.ideology:
            return {"status": "fail", "reason": f"unknown agent_id {aid}"}
        st = self._stage()
        offer = []
        if st["stage"] == "offer" and self.offers[aid] and self.offer_response[aid] is None:
            offer = [{"outlet_id": o, "name": OUTLETS[o]["name"], "lean": OUTLETS[o]["lean"]}
                     for o in self.offers[aid]]
        return {
            "status": "success", "agent_id": aid, **st,
            "subscriptions": [{"outlet_id": o, "name": OUTLETS[o]["name"], "lean": OUTLETS[o]["lean"]}
                              for o in self.subscriptions[aid]],
            "offer": offer,
            "feed": self.feeds.get(aid, []) if st["stage"] == "week" else [],
            "already_submitted": aid in self._pending,
        }

    @tool(readonly=False)
    async def respond_to_offer(self, agent_id: int, accepted_outlet_ids: List[str]) -> Dict[str, Any]:
        """Offer step only. Record which offered outlets the user chooses to follow (**accepted_outlet_ids**, a possibly empty list of outlet ids from the user's offer). Outlet ids outside the offer are ignored; resubmitting overwrites.

        - agent_id: the user's id.
        - accepted_outlet_ids: list of outlet id strings.
        """
        aid = int(agent_id)
        if self._stage()["stage"] != "offer":
            return {"status": "fail", "reason": "the subscription offer is no longer open"}
        accepted = [o for o in dict.fromkeys(accepted_outlet_ids or []) if o in self.offers.get(aid, [])]
        self._pending[aid] = {"accepted": accepted}
        return {"status": "success", "response": f"following {len(accepted)} new outlet(s)"}

    @tool(readonly=False)
    async def submit_week_actions(
        self, agent_id: int, read_post_ids: List[str], shared_post_ids: List[str],
        own_party_feeling: int, other_party_feeling: int,
    ) -> Dict[str, Any]:
        """Week stages only. Record the user's weekly actions: the posts from this week's feed the user reads (**read_post_ids**) and shares (**shared_post_ids**, normally a subset of the reads), and the user's current feeling-thermometer ratings (0-100) toward their **own party** and the **other party**. Resubmitting in the same week overwrites.

        - agent_id: the user's id.
        - read_post_ids: list of post id strings from the user's feed.
        - shared_post_ids: list of post id strings.
        - own_party_feeling: integer 0-100.
        - other_party_feeling: integer 0-100.
        """
        aid = int(agent_id)
        if self._stage()["stage"] != "week":
            return {"status": "fail", "reason": "no weekly feed is active"}
        feed_ids = set(self._feed_meta.get(aid, {}).get("feed_ids", []))
        reads = [p for p in dict.fromkeys(read_post_ids or []) if p in feed_ids]
        shares = [p for p in dict.fromkeys(shared_post_ids or []) if p in feed_ids]
        clip = lambda x: max(0, min(100, int(round(float(x)))))  # noqa: E731
        self._pending[aid] = {"reads": reads, "shares": shares,
                              "own": clip(own_party_feeling), "other": clip(other_party_feeling)}
        return {"status": "success", "response": f"recorded {len(reads)} read(s), {len(shares)} share(s)"}

    @tool(readonly=True, kind="statistics")
    async def get_polarization_statistics(self) -> Dict[str, Any]:
        """Return experiment-wide statistics: stage, week, condition, mean counter-attitudinal share of feeds, and mean cumulative counter-attitudinal reads."""
        metas = list(self._feed_meta.values())
        return {
            "status": "success", **self._stage(), "condition": self.condition,
            "mean_feed_counter_share": sum(m["feed_counter_share"] for m in metas) / len(metas) if metas else None,
            "mean_cumulative_counter_reads": sum(self.cumulative_counter_reads.values()) / len(self.agent_ids),
        }

    # ------------------------------------------------------------------ step
    async def step(self, tick: int, t: datetime):
        st = self._stage()
        if st["stage"] == "offer":
            rows = []
            for aid in self.agent_ids:
                acc = (self._pending.get(aid) or {}).get("accepted", [])
                self.offer_response[aid] = acc
                self.subscriptions[aid] = list(dict.fromkeys(self.subscriptions[aid] + acc))
                rows.append({"agent_id": aid, "ideology": self.ideology[aid], "condition": self.condition,
                             "offered": self.offers[aid], "accepted": acc,
                             "responded": aid in self._pending})
            self._append_jsonl("np_offers.jsonl", rows)
        elif st["stage"] == "week":
            rows = []
            for aid in self.agent_ids:
                act = self._pending.get(aid)
                meta = self._feed_meta.get(aid, {})
                reads = act["reads"] if act else []
                n_counter_reads = sum(self._is_counter(aid, self.posts[p]["lean"]) for p in reads)
                self.cumulative_counter_reads[aid] += n_counter_reads
                rows.append({
                    "agent_id": aid, "week": st["week"], "ideology": self.ideology[aid],
                    "condition": self.condition, "t": t.isoformat(),
                    "n_subscriptions": len(self.subscriptions[aid]),
                    "n_candidates": meta.get("n_candidates", 0),
                    "candidate_counter_share": meta.get("candidate_counter_share", 0.0),
                    "feed_counter_share": meta.get("feed_counter_share", 0.0),
                    "n_reads": len(reads), "n_counter_reads": n_counter_reads,
                    "cumulative_counter_reads": self.cumulative_counter_reads[aid],
                    "n_shares": len(act["shares"]) if act else 0,
                    "n_counter_shares": sum(self._is_counter(aid, self.posts[p]["lean"])
                                            for p in (act["shares"] if act else [])),
                    "own_party_feeling": act["own"] if act else None,
                    "other_party_feeling": act["other"] if act else None,
                    "submitted": act is not None,
                })
            self._append_jsonl("np_weekly.jsonl", rows)
        self._pending = {}
        self._step_index += 1
        if self._stage()["stage"] == "week":
            self._publish_week(self._stage()["week"])
        self.t = t

    # ----------------------------------------------------------- persistence
    def _append_jsonl(self, name: str, rows: List[Dict[str, Any]]) -> None:
        if self._workspace_root is None or not rows:
            return
        with open(Path(self._workspace_root) / name, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    async def to_workspace(self, workspace_path: Path | None = None) -> None:
        await super().to_workspace(workspace_path)
        if self._workspace_root is None:
            return
        state = {"step_index": self._step_index, "post_counter": self._post_counter,
                 "subscriptions": self.subscriptions, "offer_response": self.offer_response,
                 "posts": self.posts, "feeds": self.feeds, "feed_meta": self._feed_meta,
                 "cumulative_counter_reads": self.cumulative_counter_reads,
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
        self._step_index = int(s["step_index"])
        self._post_counter = int(s["post_counter"])
        self.subscriptions = {int(k): v for k, v in s["subscriptions"].items()}
        self.offer_response = {int(k): v for k, v in s["offer_response"].items()}
        self.posts = s["posts"]
        self.feeds = {int(k): v for k, v in s["feeds"].items()}
        self._feed_meta = {int(k): v for k, v in s["feed_meta"].items()}
        self.cumulative_counter_reads = {int(k): int(v) for k, v in s["cumulative_counter_reads"].items()}
        self._rng.setstate(ast.literal_eval(s["rng_state"]))
        return True
