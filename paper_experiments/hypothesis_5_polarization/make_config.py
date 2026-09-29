"""Shared config generator for the Levy (2021) polarization replication (AS2 paper Sec. 7.5).

Paper setup per condition: 200 agents (100 liberal, 100 conservative); baseline
survey on Feb 28 2018; 8 weekly steps; endline survey. Conditions: control, pro-
attitudinal offer, counter-attitudinal offer (<= 4 outlets, replacements when an
outlet is already followed). Feed <= 20 posts, 3 posts/outlet/week, ranking
penalty 0.4 for counter-attitudinal posts.

Profiles are synthetic (the paper's population template is not released); the
same seed yields the same population in all three conditions.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

PRESETS = {
    "paper": {"per_side": 100, "weeks": 8},
    "smoke": {"per_side": 2, "weeks": 2},
}
OUTLET_IDS = {"liberal": [f"L{i}" for i in range(1, 9)], "conservative": [f"C{i}" for i in range(1, 9)]}
HABITS = [
    "you check news on Facebook several times a day",
    "you scroll Facebook news most days, usually in the evening",
    "you see news on Facebook a few times a week",
    "you mostly follow news through Facebook and TV",
]

# 20-item issue battery (1 = strongly disagree .. 5 = strongly agree); "C" items are
# conservative-direction statements, "L" items liberal-direction (reverse-coded in analysis).
OPINION_ITEMS = [
    ("L", "The government should do more to regulate gun sales."),
    ("C", "Building a wall on the U.S.-Mexico border is a good idea."),
    ("C", "The 2017 tax cuts will help the economy grow."),
    ("C", "Tariffs on imported steel and aluminum are good for the country."),
    ("L", "The special counsel's Russia investigation is justified."),
    ("L", "The federal government should make sure all Americans have health coverage."),
    ("L", "Immigrants brought to the U.S. illegally as children should be allowed to stay."),
    ("L", "Stricter environmental regulations are worth the cost."),
    ("L", "The federal minimum wage should be raised."),
    ("L", "Abortion should be legal in most cases."),
    ("C", "Police officers are generally treated unfairly by the media."),
    ("C", "Lower taxes on businesses create more jobs."),
    ("L", "Climate change is mostly caused by human activity."),
    ("C", "The U.S. should reduce the number of legal immigrants it admits."),
    ("L", "Same-sex marriage should be legal."),
    ("C", "Government regulation of business usually does more harm than good."),
    ("C", "Military spending should be increased."),
    ("C", "Voter ID laws are necessary to prevent fraud."),
    ("C", "The death penalty is appropriate for people convicted of murder."),
    ("L", "Wealthy Americans should pay higher taxes."),
]


def _survey(qid: str, title: str) -> dict:
    items = "\n".join(f'q{i + 1}: {text}' for i, (_, text) in enumerate(OPINION_ITEMS))
    return {
        "type": "questionnaire",
        "questionnaire_id": qid,
        "title": title,
        "description": "A short survey about politics. Answer honestly as yourself.",
        "questions": [
            {"id": "thermometers", "response_type": "json",
             "prompt": ("Rate your feelings toward the Democratic Party and the Republican Party on a "
                        "0-100 feeling thermometer (0 = very cold/unfavorable, 50 = neutral, 100 = very "
                        'warm/favorable). The answer must be JSON: {"democrats": <0-100>, "republicans": <0-100>}')},
            {"id": "affective_items", "response_type": "json",
             "prompt": ("Think about the political party you do NOT support. On 1-5 scales answer: "
                        "(a) perspective_difficulty: how difficult is it for you to see things from the "
                        "point of view of that party's supporters? (1 = not at all difficult, 5 = extremely "
                        "difficult); (b) ideas_do_not_make_sense: do that party's ideas make sense to you? "
                        "(1 = they make a lot of sense, 5 = they make no sense at all); (c) "
                        "child_marriage_upset: how upset would you be if your child married a supporter of "
                        'that party? (1 = not at all upset, 5 = extremely upset). The answer must be JSON: '
                        '{"perspective_difficulty": <1-5>, "ideas_do_not_make_sense": <1-5>, '
                        '"child_marriage_upset": <1-5>}')},
            {"id": "political_opinions", "response_type": "json",
             "prompt": ("For each statement give your agreement from 1 (strongly disagree) to 5 (strongly "
                        f"agree).\n{items}\nThe answer must be JSON mapping q1..q20 to integers 1-5.")},
        ],
    }


def generate(init_dir: Path, condition: str) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper", choices=sorted(PRESETS))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    p = PRESETS[args.preset]
    rng = random.Random(1000 + args.seed)  # population depends on seed only, not on condition

    agents, env_specs = [], []
    ideologies = ["liberal"] * p["per_side"] + ["conservative"] * p["per_side"]
    for i, ideo in enumerate(ideologies, start=1):
        score = -rng.uniform(0.2, 1.0) if ideo == "liberal" else rng.uniform(0.2, 1.0)
        other = "conservative" if ideo == "liberal" else "liberal"
        subs = set()
        for _ in range(rng.randint(2, 4)):  # baseline outlets, mostly own side
            side = ideo if rng.random() < 0.8 else other
            subs.add(rng.choice(OUTLET_IDS[side]))
        env_specs.append({"id": i, "ideology": ideo, "baseline_subscriptions": sorted(subs)})
        agents.append({
            "agent_id": i, "agent_type": "NewsConsumerAgent",
            "kwargs": {
                "id": i, "name": f"User-{i}", "ideology": ideo, "ideology_score": round(score, 2),
                "age": rng.randint(18, 75), "gender": rng.choice(["man", "woman"]),
                "education": rng.choice(["a high-school", "some college", "a bachelor's degree", "a graduate degree"]),
                "region": rng.choice(["Northeast", "Midwest", "South", "West"]),
                "news_habits": rng.choice(HABITS),
                "condition": condition,  # bookkeeping only; never shown in prompts
            },
        })
    init_config = {
        "env_modules": [{
            "module_type": "NewsPolarizationEnv",
            "kwargs": {"agent_specs": env_specs, "condition": condition, "num_weeks": p["weeks"],
                       "feed_size": 20, "posts_per_outlet": 3, "algorithm_filter_strength": 0.4,
                       "max_offered_outlets": 4, "seed": args.seed},
        }],
        "agents": agents,
        "codegen_router": {"final_summary_enabled": False},
    }
    steps = {
        "start_t": "2018-02-28T09:00:00",
        "steps": [
            _survey("baseline_survey", "Baseline survey"),
            {"type": "run", "num_steps": 1, "tick": 3600},          # subscription-offer step
            {"type": "run", "num_steps": p["weeks"], "tick": 604800},  # weekly feeds
            _survey("endline_survey", "Endline survey"),
        ],
    }
    init_dir.mkdir(parents=True, exist_ok=True)
    (init_dir / "init_config.json").write_text(json.dumps(init_config, indent=2), encoding="utf-8")
    import yaml  # available in the AgentSociety venv

    (init_dir / "steps.yaml").write_text(yaml.safe_dump(steps, sort_keys=False, allow_unicode=True),
                                         encoding="utf-8")
    print(f"[{condition}] preset={args.preset} seed={args.seed}: {len(agents)} agents, "
          f"{p['weeks']} weeks -> {init_dir}")
