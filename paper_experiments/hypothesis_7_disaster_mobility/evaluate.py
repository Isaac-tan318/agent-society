"""Evaluate disaster-mobility runs (AS2 paper Sec. 7.7).

    python evaluate.py [--preset paper] [--seed 0]

Daily completed moves (MovementLedgerEnv) are sum-normalized over the 11-day window,
x~_t = x_t / sum_s x_s, as in the paper (Eq. 1). If an empirical daily index is
provided at data/disaster/<scenario>_empirical.csv (columns: date,index - e.g.
de-seasonalized SafeGraph outflux), it is normalized the same way and compared by
per-phase RMSE, overall MAE and Pearson r. Paper RMSEs: Camp Fire phase 3 0.0076;
Texas phase 3 0.0188, phase 5 0.0073.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

from make_config import SCENARIOS

HERE = Path(__file__).resolve().parent
EXPERIMENTS = {"texas_winter_storm": "experiment_1_texas_winter_storm", "camp_fire": "experiment_2_camp_fire"}


def _days(start: str, n: int = 11) -> list[str]:
    d0 = datetime.fromisoformat(start).date()
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _normalize(xs: list[float]) -> list[float]:
    total = sum(xs)
    return [x / total for x in xs] if total else [0.0] * len(xs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="paper")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    for scenario, exp in EXPERIMENTS.items():
        sc = SCENARIOS[scenario]
        f = HERE / exp / "runs" / f"{args.preset}_seed{args.seed}" / "env" / "MovementLedgerEnv" / "movement_daily.json"
        if not f.is_file():
            print(f"[{scenario}] no ledger at {f}")
            continue
        daily = json.loads(f.read_text(encoding="utf-8"))["completed_moves_by_day"]
        days = _days(sc["start"])
        sim = _normalize([daily.get(d, 0) for d in days])
        # phase index per day, from the scenario's phase lengths
        phase_of = []
        for i, (_, hours, _) in enumerate(sc["phases"], start=1):
            phase_of += [i] * (hours // 24)
        print(f"\n=== {scenario} ({args.preset}_seed{args.seed}) ===")
        emp_path = HERE.parent / "data" / "disaster" / f"{scenario}_empirical.csv"
        emp = None
        if emp_path.is_file():
            rows = {r["date"]: float(r["index"]) for r in csv.DictReader(emp_path.open(encoding="utf-8"))}
            emp = _normalize([rows.get(d, 0.0) for d in days])
        print("day         phase  sim_share" + ("  emp_share" if emp else ""))
        for i, d in enumerate(days):
            print(f"{d}  {phase_of[i]:>5}  {sim[i]:9.4f}" + (f"  {emp[i]:9.4f}" if emp else ""))
        if emp:
            for ph in sorted(set(phase_of)):
                idx = [i for i, p in enumerate(phase_of) if p == ph]
                rmse = math.sqrt(sum((sim[i] - emp[i]) ** 2 for i in idx) / len(idx))
                print(f"  phase {ph} ({sc['phases'][ph - 1][0]}): RMSE {rmse:.4f}")
            mae = sum(abs(a - b) for a, b in zip(sim, emp)) / len(sim)
            ms, me = sum(sim) / len(sim), sum(emp) / len(emp)
            cov = sum((a - ms) * (b - me) for a, b in zip(sim, emp))
            den = math.sqrt(sum((a - ms) ** 2 for a in sim) * sum((b - me) ** 2 for b in emp))
            print(f"  overall MAE {mae:.4f}, Pearson r {cov / den if den else float('nan'):.3f}")
        else:
            print(f"  (no empirical index at {emp_path}; add one to compute RMSE)")


if __name__ == "__main__":
    main()
