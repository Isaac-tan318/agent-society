"""Analyze the Fischbacher & Gaechter (2010) replication and compare with the AS2 paper (Sec. 7.2).

    python analyze.py [--preset paper]

For every runs/<preset>_seed*/ of both orders:
- P stage: classify each conditional contribution schedule (F&G 2001/2010 scheme):
  free rider (all zeros); conditional cooperator (Spearman rho > 0, p < .01, or
  weakly increasing) - "perfect" if the OLS slope on the others' average >= 1,
  else "incomplete"; hump-shaped (rises then falls); other.
- C stage: mean contribution / belief per round.
- Mechanism: preference-predicted contribution = schedule[round(belief)]; share of
  agents contributing MORE than predicted per round.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
EXPERIMENTS = {"PC": "experiment_1_p_then_c", "CP": "experiment_2_c_then_p"}
PAPER = {  # AS2 paper Sec. 7.2.3 (P->C main condition, 24 agents)
    "incomplete_conditional_cooperators": "17/24",
    "mean_contribution_round1": 8.25, "min_mean_contribution_early": 7.79, "mean_contribution_round10": 8.04,
    "share_above_predicted_round10": 0.7083,
}


def _load(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def classify(table: list[int]) -> str:
    if table is None:
        return "missing"
    xs = list(range(len(table)))
    if all(v == 0 for v in table):
        return "free_rider"
    increasing = all(b >= a for a, b in zip(table, table[1:])) and table[-1] > table[0]
    rho, p = spearmanr(xs, table) if len(set(table)) > 1 else (0.0, 1.0)
    if increasing or (rho > 0 and p < 0.01):
        mx, my = statistics.fmean(xs), statistics.fmean(table)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, table)) / sum((x - mx) ** 2 for x in xs)
        return "conditional_cooperator_perfect" if slope >= 0.999 else "conditional_cooperator_incomplete"
    peak = table.index(max(table))
    if 0 < peak < len(table) - 1 and table[0] < table[peak] > table[-1]:
        return "hump_shaped"
    return "other"


def analyze_run(run: Path) -> dict | None:
    env = run / "env" / "FGPCPublicGoodsEnv"
    if not (env / "pg_c_rounds.jsonl").is_file() or not (env / "pg_p_stage.jsonl").is_file():
        return None
    p_rows = {r["agent_id"]: r for r in _load(env / "pg_p_stage.jsonl")}
    c_rows = _load(env / "pg_c_rounds.jsonl")
    types = {a: classify(r["conditional"]) for a, r in p_rows.items()}
    rounds = sorted({r["round"] for r in c_rows})
    by_round = {k: [r for r in c_rows if r["round"] == k] for k in rounds}
    above = {}
    for k, rows in by_round.items():
        flags = []
        for r in rows:
            sched = p_rows.get(r["agent_id"], {}).get("conditional")
            if sched and r["belief"] is not None:
                predicted = sched[max(0, min(len(sched) - 1, round(r["belief"])))]
                flags.append(r["contribution"] > predicted)
        above[k] = sum(flags) / len(flags) if flags else None
    return {
        "n_agents": len(p_rows),
        "type_counts": {t: sum(1 for v in types.values() if v == t) for t in sorted(set(types.values()))},
        "mean_contribution_by_round": {k: statistics.fmean(r["contribution"] for r in v) for k, v in by_round.items()},
        "mean_belief_by_round": {k: statistics.fmean(r["belief"] for r in v if r["belief"] is not None)
                                 for k, v in by_round.items() if any(r["belief"] is not None for r in v)},
        "share_above_predicted_by_round": above,
        "submission_rate": statistics.fmean(1.0 if r["submitted"] else 0.0 for r in c_rows),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper")
    args = ap.parse_args()
    out = {"paper": PAPER}
    for order, exp in EXPERIMENTS.items():
        for run in sorted((HERE / exp / "runs").glob(f"{args.preset}_seed*")):
            res = analyze_run(run)
            if res is None:
                continue
            out[f"{order}/{run.name}"] = res
            print(f"\n=== {order} {run.name}: {res['n_agents']} agents, submission rate {res['submission_rate']:.0%} ===")
            print("P-stage types:", res["type_counts"])
            print("round  mean_contrib  mean_belief  share_above_predicted")
            for k, c in res["mean_contribution_by_round"].items():
                b = res["mean_belief_by_round"].get(k)
                a = res["share_above_predicted_by_round"].get(k)
                print(f"{k:5d}  {c:12.2f}  {b if b is None else round(b, 2)!s:>11}  "
                      f"{'-' if a is None else f'{a:.1%}':>21}")
    print("\nAS2 paper (P->C):", json.dumps(PAPER))
    (HERE / f"results_{args.preset}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
