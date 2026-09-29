"""Analyze the Qi et al. (2025) self-bias tasks and compare with the AS2 paper (Sec. 7.3.3).

    python analyze.py [--preset paper] [--seed 0]

Reads each task env's state/ENV_STATE.json from experiment_*/runs/<preset>_seed<N>/.
- EE: mean WTA vs WTP (CNY), share of agents with WTA > WTP, paired t-test.
- SE: mean reverse-coded percentile (0 best, 50 median, 100 worst), t-test vs 50, per dimension.
- IAT: mean RT (ms) and accuracy in congruent vs incongruent blocks, paired t-test on RT.
- SRE: old-item / new-item recognition accuracy and old-item accuracy by encoding identity.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from scipy.stats import ttest_1samp, ttest_rel

HERE = Path(__file__).resolve().parent
TASKS = {
    "ee": ("experiment_1_endowment_effect", "EndowmentEffectEnv"),
    "se": ("experiment_2_self_enhancement", "SelfEnhancementEnv"),
    "iat": ("experiment_3_iat", "ImplicitAssociationTestEnv"),
    "sre": ("experiment_4_self_reference", "SelfReferenceEffectEnv"),
}
PAPER = {
    "ee": {"agents": {"wta": 63.32, "wtp": 48.37, "share_wta_gt_wtp": 0.978}, "humans": {"wta": 107.84, "wtp": 74.36}},
    "se": {"agents": {"overall_mean": 53.72}, "humans": {"overall_mean": 43.61}},
    "iat": {"agents": {"rt_congruent_ms": 807.7, "rt_incongruent_ms": 809.3,
                       "acc_congruent": 0.885, "acc_incongruent": 0.869}},
    "sre": {"agents": {"old_acc": 0.584, "new_acc": 0.634, "self": 0.572, "friend": 0.592, "other": 0.587}},
}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _state(task: str, preset: str, seed: int) -> dict | None:
    exp, env = TASKS[task]
    p = HERE / exp / "runs" / f"{preset}_seed{seed}" / "env" / env / "state" / "ENV_STATE.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def ee(s: dict) -> dict:
    per = [(_mean(v["wta"] for v in items.values()), _mean(v["wtp"] for v in items.values()))
           for items in s.get("evaluations", {}).values() if items]
    if not per:
        return {}
    wta, wtp = [a for a, _ in per], [b for _, b in per]
    out = {"n": len(per), "wta": _mean(wta), "wtp": _mean(wtp),
           "share_wta_gt_wtp": sum(a > b for a, b in per) / len(per)}
    if len(per) > 2:
        t = ttest_rel(wta, wtp)
        out.update(t=float(t.statistic), p=float(t.pvalue))
    return out


def se(s: dict) -> dict:
    ranks = s.get("rankings", {})
    per_agent = [_mean(r.values()) for r in ranks.values() if r]
    if not per_agent:
        return {}
    dims: dict[str, list] = {}
    for r in ranks.values():
        for d, v in r.items():
            dims.setdefault(d, []).append(v)
    out = {"n": len(per_agent), "overall_mean": _mean(per_agent),
           "by_dimension": {d: _mean(v) for d, v in sorted(dims.items())}}
    if len(per_agent) > 2:
        t = ttest_1samp(per_agent, 50)
        out.update(t=float(t.statistic), p=float(t.pvalue))
    return out


def iat(s: dict) -> dict:
    rt_c, rt_i, acc_c, acc_i = [], [], [], []
    for rows in s.get("responses", {}).values():
        con = [r for r in rows if r.get("block_code") == "congruent"]
        inc = [r for r in rows if r.get("block_code") == "incongruent"]
        if con and inc:
            rt_c.append(1000 * _mean(float(r["rt"]) for r in con))
            rt_i.append(1000 * _mean(float(r["rt"]) for r in inc))
            acc_c.append(_mean(1.0 if r.get("corr") else 0.0 for r in con))
            acc_i.append(_mean(1.0 if r.get("corr") else 0.0 for r in inc))
    if not rt_c:
        return {"completed_agents": 0, "trials_answered": sum(len(v) for v in s.get("responses", {}).values())}
    out = {"n": len(rt_c), "rt_congruent_ms": _mean(rt_c), "rt_incongruent_ms": _mean(rt_i),
           "acc_congruent": _mean(acc_c), "acc_incongruent": _mean(acc_i)}
    if len(rt_c) > 2:
        t = ttest_rel(rt_i, rt_c)
        out.update(t=float(t.statistic), p=float(t.pvalue))
    return out


def sre(s: dict) -> dict:
    enc_all = s.get("encoding_ratings", {})
    old_acc, new_acc, by_id = [], [], {"self": [], "friend": [], "other": []}
    for aid, judgments in s.get("recognition_judgments", {}).items():
        encoded = {e["trait"]: e.get("identity") for e in enc_all.get(aid, [])}
        if not judgments:
            continue
        olds = [j for j in judgments if j["trait"] in encoded]
        news = [j for j in judgments if j["trait"] not in encoded]
        if olds:
            old_acc.append(_mean(1.0 if j["judge_type"] == "old" else 0.0 for j in olds))
        if news:
            new_acc.append(_mean(1.0 if j["judge_type"] == "new" else 0.0 for j in news))
        for ident in by_id:
            sub = [j for j in olds if encoded.get(j["trait"]) == ident]
            if sub:
                by_id[ident].append(_mean(1.0 if j["judge_type"] == "old" else 0.0 for j in sub))
    if not old_acc and not new_acc:
        return {}
    return {"n": max(len(old_acc), len(new_acc)), "old_acc": _mean(old_acc), "new_acc": _mean(new_acc),
            **{k: _mean(v) for k, v in by_id.items()}}


def analyze(preset: str, seed: int) -> dict:
    fns = {"ee": ee, "se": se, "iat": iat, "sre": sre}
    out = {}
    for task, fn in fns.items():
        st = _state(task, preset, seed)
        out[task] = {"sim": fn(st) if st else None, "paper": PAPER[task]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    res = analyze(args.preset, args.seed)
    for task, r in res.items():
        print(f"\n=== {task.upper()} ===")
        if not r["sim"]:
            print("  no completed run found")
            continue
        for k, v in r["sim"].items():
            if isinstance(v, dict):
                print(f"  {k}: " + ", ".join(f"{d} {x:.1f}" for d, x in v.items()))
            else:
                print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")
        print(f"  AS2 paper: {json.dumps(r['paper'])}")
    (HERE / f"results_{args.preset}_seed{args.seed}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
