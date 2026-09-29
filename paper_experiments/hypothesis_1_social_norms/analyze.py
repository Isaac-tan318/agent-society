"""Analyze Norms vs Metanorms runs and compare with the AgentSociety 2 paper (Sec. 7.1).

    python analyze.py [--preset paper]

Reads every runs/<preset>_seed*/env/NormsGameEnv/norms_timeseries.jsonl under
experiment_1_norms and experiment_2_metanorms, and reports initial -> final mean
boldness / vengefulness (0-7 scale) per seed and averaged, next to the paper.
Writes results_<preset>.json next to this script.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER = {  # AS2 paper Sec. 7.1.3 (single run each)
    "norms": {"boldness": (1.90, 0.10), "vengefulness": (2.90, 2.55)},
    "metanorms": {"boldness": (3.35, 0.15), "vengefulness": (4.40, 6.15)},
}
EXPERIMENTS = {"norms": "experiment_1_norms", "metanorms": "experiment_2_metanorms"}


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _summarize(rows: list[dict]) -> dict:
    first, last = rows[0], rows[-1]
    return {
        "generations": last["generation"] + (0 if last["reproduced"] else 1),
        "boldness": (first["mean_boldness"], last["mean_boldness"]),
        "vengefulness": (first["mean_vengefulness"], last["mean_vengefulness"]),
        "mean_payoff_first_gen": statistics.fmean(r["mean_round_payoff"] for r in rows[:4]),
        "mean_payoff_last_gen": statistics.fmean(r["mean_round_payoff"] for r in rows[-4:]),
        "total_meta_punishments": sum(r["meta_punishments"] for r in rows),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper")
    args = ap.parse_args()
    out: dict = {}
    expected_steps = {"paper": 400, "smoke": 20}.get(args.preset)
    for mode, exp in EXPERIMENTS.items():
        runs = sorted((HERE / exp / "runs").glob(f"{args.preset}_seed*/env/NormsGameEnv/norms_timeseries.jsonl"))
        per_seed = {}
        for p in runs:
            rows = _load(p)
            if expected_steps and len(rows) < expected_steps:  # the CLI swallows step errors
                print(f"[{mode}] SKIPPING incomplete run {p.parts[-4]}: {len(rows)}/{expected_steps} steps "
                      "(see its output.log; re-run that seed)")
                continue
            per_seed[p.parts[-4]] = _summarize(rows)
        if not per_seed:
            print(f"[{mode}] no {args.preset} runs found under {exp}/runs/")
            continue
        final_b = [s["boldness"][1] for s in per_seed.values()]
        final_v = [s["vengefulness"][1] for s in per_seed.values()]
        agg = {
            "n_runs": len(per_seed),
            "final_boldness_mean": statistics.fmean(final_b),
            "final_boldness_sd": statistics.pstdev(final_b),
            "final_vengefulness_mean": statistics.fmean(final_v),
            "final_vengefulness_sd": statistics.pstdev(final_v),
            "vengefulness_change_mean": statistics.fmean(
                s["vengefulness"][1] - s["vengefulness"][0] for s in per_seed.values()),
        }
        out[mode] = {"per_seed": per_seed, "aggregate": agg, "paper": PAPER[mode]}

        print(f"\n=== {mode.upper()} ({len(per_seed)} run(s), preset={args.preset}) ===")
        print(f"{'run':14s} {'boldness init->final':>22s} {'vengefulness init->final':>26s}  payoff 1st->last gen")
        for name, s in per_seed.items():
            b, v = s["boldness"], s["vengefulness"]
            print(f"{name:14s} {b[0]:9.2f} -> {b[1]:5.2f}      {v[0]:11.2f} -> {v[1]:5.2f}      "
                  f"{s['mean_payoff_first_gen']:7.2f} -> {s['mean_payoff_last_gen']:6.2f}")
        pb, pv = PAPER[mode]["boldness"], PAPER[mode]["vengefulness"]
        print(f"{'AS2 paper':14s} {pb[0]:9.2f} -> {pb[1]:5.2f}      {pv[0]:11.2f} -> {pv[1]:5.2f}")
        print(f"mean final: boldness {agg['final_boldness_mean']:.2f} (sd {agg['final_boldness_sd']:.2f}), "
              f"vengefulness {agg['final_vengefulness_mean']:.2f} (sd {agg['final_vengefulness_sd']:.2f})")

    if {"norms", "metanorms"} <= out.keys():
        n, m = out["norms"]["aggregate"], out["metanorms"]["aggregate"]
        checks = {
            "both conditions end with low boldness (< 1.0)": n["final_boldness_mean"] < 1 and m["final_boldness_mean"] < 1,
            "metanorms ends with higher vengefulness than norms": m["final_vengefulness_mean"] > n["final_vengefulness_mean"],
            "metanorms raises vengefulness (final > initial)": m["vengefulness_change_mean"] > 0,
        }
        out["qualitative_checks_vs_paper"] = checks
        print("\n=== Qualitative patterns reported in the AS2 paper ===")
        for k, ok in checks.items():
            print(f"  [{'MATCH' if ok else 'DIFF '}] {k}")
    (HERE / f"results_{args.preset}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
