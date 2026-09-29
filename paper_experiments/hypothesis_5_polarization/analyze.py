"""Analyze the Levy (2021) replication and compare with the AS2 paper (Sec. 7.5, Table 8).

    python analyze.py [--preset paper] [--seed 0]

Per condition (control / pro / counter):
- subscription compliance: share of offered agents that followed >= 1 outlet, mean outlets followed
- counter-attitudinal share of the feed (post-ranking) and of the candidate pool (pre-ranking)
- cumulative counter-attitudinal reads after the last week
- affective polarization change: (own - other party thermometer gap) endline minus baseline
- issue-opinion index: mean of the 20 items on a 1 (liberal) .. 5 (conservative) scale
- exposure-gap decomposition vs control: subscription choice (candidate pool) + ranking penalty
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from pathlib import Path

from make_config import OPINION_ITEMS

HERE = Path(__file__).resolve().parent
CONDITIONS = {"control": "experiment_1_control", "pro": "experiment_2_pro_attitudinal",
              "counter": "experiment_3_counter_attitudinal"}
PAPER = {
    "compliance": {"pro": 0.59, "counter": 0.43},
    "feed_counter_share": {"control": 0.2871, "pro": 0.1921, "counter": 0.3569},
    "cumulative_counter_reads": {"control": 1.65, "pro": 0.86, "counter": 4.15},
    "affective_change": {"control": 2.36, "pro": 2.80, "counter": 1.28},
    "opinion_index": {"control": 3.01, "pro": 3.04, "counter": 2.99},
    "gap_decomposition_pp": {"pro": {"subscription": -5.23, "ranking": -4.27},
                             "counter": {"subscription": 5.24, "ranking": 1.75}},
}


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


def _survey(run: Path, qid: str, ideology: dict[int, str]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for f in glob.glob(str(run / "artifacts" / "questionnaire_step_*.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        if d.get("questionnaire_id") != qid:
            continue
        for resp in d["responses"]:
            aid = int(resp["agent_id"])
            ans = {a["question_id"]: a.get("parsed_value") for a in resp["answers"]}
            rec: dict = {}
            th = ans.get("thermometers")
            if isinstance(th, dict) and "democrats" in th and "republicans" in th:
                dem, rep = float(th["democrats"]), float(th["republicans"])
                own, other = (dem, rep) if ideology.get(aid) == "liberal" else (rep, dem)
                rec["gap"] = own - other
            op = ans.get("political_opinions")
            if isinstance(op, dict):
                vals = []
                for i, (direction, _) in enumerate(OPINION_ITEMS, start=1):
                    v = op.get(f"q{i}")
                    if v is not None:
                        v = float(v)
                        vals.append(v if direction == "C" else 6 - v)
                if vals:
                    rec["opinion_index"] = statistics.fmean(vals)
            out[aid] = rec
    return out


def analyze_condition(run: Path) -> dict | None:
    env = run / "env" / "NewsPolarizationEnv"
    weekly = _jsonl(env / "np_weekly.jsonl")
    if not weekly:
        return None
    offers = _jsonl(env / "np_offers.jsonl")
    ideology = {r["agent_id"]: r["ideology"] for r in weekly}
    last_week = max(r["week"] for r in weekly)
    offered = [o for o in offers if o["offered"]]
    base = _survey(run, "baseline_survey", ideology)
    end = _survey(run, "endline_survey", ideology)
    changes = [end[a]["gap"] - base[a]["gap"] for a in end if "gap" in end[a] and "gap" in base.get(a, {})]
    opinions = [r["opinion_index"] for r in end.values() if "opinion_index" in r]
    return {
        "n_agents": len(ideology),
        "compliance": (sum(1 for o in offered if o["accepted"]) / len(offered)) if offered else None,
        "mean_outlets_followed": statistics.fmean(len(o["accepted"]) for o in offered) if offered else None,
        "feed_counter_share": statistics.fmean(r["feed_counter_share"] for r in weekly),
        "candidate_counter_share": statistics.fmean(r["candidate_counter_share"] for r in weekly),
        "cumulative_counter_reads": statistics.fmean(r["cumulative_counter_reads"] for r in weekly
                                                     if r["week"] == last_week),
        "affective_change": statistics.fmean(changes) if changes else None,
        "baseline_gap": statistics.fmean(b["gap"] for b in base.values() if "gap" in b) if base else None,
        "opinion_index": statistics.fmean(opinions) if opinions else None,
        "weekly_submission_rate": statistics.fmean(1.0 if r["submitted"] else 0.0 for r in weekly),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    res = {}
    for cond, exp in CONDITIONS.items():
        r = analyze_condition(HERE / exp / "runs" / f"{args.preset}_seed{args.seed}")
        if r is not None:
            res[cond] = r
    if not res:
        print("no runs found")
        return
    fmt = lambda v, pct=False: "-" if v is None else (f"{v:.1%}" if pct else f"{v:.2f}")  # noqa: E731
    print(f"{'metric':28s}" + "".join(f"{c:>18s}" for c in res) + "   AS2 paper")
    rows = [("compliance", True), ("mean_outlets_followed", False), ("feed_counter_share", True),
            ("candidate_counter_share", True), ("cumulative_counter_reads", False), ("baseline_gap", False),
            ("affective_change", False), ("opinion_index", False), ("weekly_submission_rate", True)]
    for key, pct in rows:
        paper = PAPER.get(key, {})
        print(f"{key:28s}" + "".join(f"{fmt(res[c].get(key), pct):>18s}" for c in res)
              + "   " + (", ".join(f"{c} {v}" for c, v in paper.items()) if paper else ""))
    if "control" in res:
        print("\nExposure-gap decomposition vs control (percentage points):")
        ctl = res["control"]
        for cond in ("pro", "counter"):
            if cond in res:
                sub = 100 * (res[cond]["candidate_counter_share"] - ctl["candidate_counter_share"])
                total = 100 * (res[cond]["feed_counter_share"] - ctl["feed_counter_share"])
                print(f"  {cond:8s} subscription {sub:+.2f}  ranking {total - sub:+.2f}  total {total:+.2f}"
                      f"   (paper: {PAPER['gap_decomposition_pp'][cond]})")
    (HERE / f"results_{args.preset}_seed{args.seed}.json").write_text(
        json.dumps({"results": res, "paper": PAPER}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
