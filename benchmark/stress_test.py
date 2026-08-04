"""Week 8 stress test — 3 concurrent SpotResilientJobs.

Runs 3 predictive-arm jobs at once (real subprocesses, same mechanism as
harness.py's normal sweep) and compares against the same 3 jobs run one at a
time, to isolate whether concurrency itself degrades behavior (CPU/I-O
contention inflating step times, checkpoint confirmation races) from just
"3 separate single-job runs added up."

Usage:
  python benchmark/stress_test.py --rate 300 --step-budget 500 --step-time-sec 0.3
"""
import argparse
import concurrent.futures
import json
import os
import time

from harness import run_trial
from aggregate import parse_run

HERE = os.path.dirname(os.path.abspath(__file__))


def load_arm(name):
    with open(os.path.join(HERE, "arms", f"{name}.json")) as f:
        return json.load(f)


def run_n_jobs(arm, rate, n, results_root, step_budget, step_time_sec, seed_base, concurrent_mode, rep_prefix):
    """Runs n trials of the same arm+rate, either concurrently (ThreadPoolExecutor)
    or sequentially (one at a time), each into its own run_dir so they never share
    a checkpoint file or trigger file."""
    reps = [f"{rep_prefix}{i}" for i in range(n)]
    wall_start = time.time()

    if concurrent_mode:
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
            futures = [
                pool.submit(run_trial, arm, rate, reps[i], results_root, step_budget,
                            step_time_sec, True, seed_base + i, 4.0)
                for i in range(n)
            ]
            results = [f.result() for f in futures]
    else:
        results = [
            run_trial(arm, rate, reps[i], results_root, step_budget, step_time_sec, True, seed_base + i, 4.0)
            for i in range(n)
        ]

    wall_elapsed = time.time() - wall_start
    return results, wall_elapsed


def summarize(results, results_root, arm_name, rate):
    rows = []
    for run_dir, outcome in results:
        row = parse_run(run_dir)
        if row:
            row["outcome"] = outcome
            rows.append(row)
    total_wasted = sum(r["wasted_compute_sec"] for r in rows)
    total_cost = sum(r["cost_usd"] for r in rows if r["cost_usd"] is not None)
    total_checkpoints = sum(r["num_checkpoints"] for r in rows)
    n_completed = sum(1 for r in rows if r["completed"])
    makespans = [r["makespan_sec"] for r in rows if r["makespan_sec"] is not None]
    mean_makespan = sum(makespans) / len(makespans) if makespans else None
    return {
        "n_jobs": len(rows),
        "n_completed": n_completed,
        "total_wasted_compute_sec": total_wasted,
        "total_cost_usd": total_cost,
        "total_checkpoints": total_checkpoints,
        "mean_makespan_sec": mean_makespan,
        "per_job": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", default="predictive")
    parser.add_argument("--rate", type=int, default=300, help="mean seconds between interruptions")
    parser.add_argument("--n-jobs", type=int, default=3)
    parser.add_argument("--step-budget", type=int, default=500)
    parser.add_argument("--step-time-sec", type=float, default=0.3)
    parser.add_argument("--results-dir", default=os.path.join(HERE, "results", "raw_stress"))
    args = parser.parse_args()

    arm = load_arm(args.arm)
    print(f"Stress test: {args.n_jobs}x '{args.arm}' arm, rate={args.rate}s, "
          f"step_budget={args.step_budget}, step_time_sec={args.step_time_sec}")

    print(f"\n--- Concurrent: {args.n_jobs} jobs launched at once ---")
    conc_results, conc_wall = run_n_jobs(arm, args.rate, args.n_jobs, args.results_dir,
                                          args.step_budget, args.step_time_sec,
                                          seed_base=1000, concurrent_mode=True, rep_prefix="conc_")
    conc_summary = summarize(conc_results, args.results_dir, args.arm, args.rate)
    conc_summary["wall_clock_sec"] = conc_wall
    print(f"Wall clock: {conc_wall:.1f}s | completed {conc_summary['n_completed']}/{conc_summary['n_jobs']} | "
          f"total wasted {conc_summary['total_wasted_compute_sec']:.1f}s | "
          f"mean makespan {conc_summary['mean_makespan_sec']}")

    print(f"\n--- Sequential: same {args.n_jobs} jobs, one at a time ---")
    seq_results, seq_wall = run_n_jobs(arm, args.rate, args.n_jobs, args.results_dir,
                                        args.step_budget, args.step_time_sec,
                                        seed_base=2000, concurrent_mode=False, rep_prefix="seq_")
    seq_summary = summarize(seq_results, args.results_dir, args.arm, args.rate)
    seq_summary["wall_clock_sec"] = seq_wall
    print(f"Wall clock: {seq_wall:.1f}s | completed {seq_summary['n_completed']}/{seq_summary['n_jobs']} | "
          f"total wasted {seq_summary['total_wasted_compute_sec']:.1f}s | "
          f"mean makespan {seq_summary['mean_makespan_sec']}")

    contention_pct = None
    if conc_summary["mean_makespan_sec"] and seq_summary["mean_makespan_sec"]:
        contention_pct = (conc_summary["mean_makespan_sec"] / seq_summary["mean_makespan_sec"] - 1) * 100

    print(f"\n--- Comparison ---")
    print(f"Wall-clock speedup from running concurrently: {seq_wall / conc_wall:.2f}x")
    if contention_pct is not None:
        print(f"Per-job makespan change under concurrency: {contention_pct:+.1f}%")

    out = {
        "config": vars(args),
        "concurrent": conc_summary,
        "sequential": seq_summary,
        "wall_clock_speedup": seq_wall / conc_wall if conc_wall else None,
        "per_job_makespan_change_pct": contention_pct,
    }
    out_path = os.path.join(HERE, "results", "stress_test.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
