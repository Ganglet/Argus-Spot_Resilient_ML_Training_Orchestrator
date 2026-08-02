"""Track 2 aggregation — JSON-lines (job + harness) -> CSV -> table + figures.

Reads every benchmark/results/raw/<arm>/rate_<N>s/rep_<K>/{events.jsonl,harness.jsonl}
written by job.py + harness.py, computes the metrics listed in
docs/phase6_remaining.md Track 2, and writes:

  results/summary_runs.csv   one row per (arm, rate, rep)
  results/summary_table.csv  mean +/- std per (arm, rate) -- the paper's table
  results/figures/*.png
"""
import argparse
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from metrics_logger import read_events

HERE = os.path.dirname(os.path.abspath(__file__))

# Placeholder spot hourly rate ($/hr) for cost estimation -- swap for the real
# rate of whichever instance type the final EKS run uses (see ADR-005).
SPOT_HOURLY_RATE_USD = 0.058

START_EVENTS = ("started", "resumed")


def discover_runs(results_root):
    return sorted(d for d in glob.glob(os.path.join(results_root, "*", "rate_*s", "rep_*")) if os.path.isdir(d))


def segment_job_events(job_events):
    """Split job events into per-spawn segments delimited by started/resumed."""
    segments = []
    current = None
    for ev in job_events:
        if ev["event"] in START_EVENTS:
            current = [ev]
            segments.append(current)
        elif current is not None:
            current.append(ev)
    return segments


def parse_run(run_dir):
    harness_events = read_events(os.path.join(run_dir, "harness.jsonl"))
    job_events = read_events(os.path.join(run_dir, "events.jsonl"))

    meta = next((e for e in harness_events if e["event"] == "run_meta"), None)
    if meta is None:
        return None

    exit_ev = next((e for e in harness_events if e["event"] == "job_exit"), None)
    timed_out = any(e["event"] == "timed_out" for e in harness_events)
    completed = bool(exit_ev and exit_ev.get("outcome") == "completed")

    finished_ev = next((e for e in job_events if e["event"] == "finished"), None)
    first_ev = job_events[0] if job_events else None

    makespan_sec = (finished_ev["ts"] - first_ev["ts"]) if (completed and finished_ev and first_ev) else None

    interruption_events = [e for e in harness_events if e["event"] in ("interrupted", "migrated")]
    num_interruptions = len(interruption_events)

    checkpoint_events = [e for e in job_events if e["event"] == "checkpoint"]
    num_checkpoints = len(checkpoint_events)
    checkpoint_bytes_total = sum(e.get("bytes", 0) for e in checkpoint_events)

    # Wasted compute: for each respawn segment that ends in a kill (i.e. every
    # segment except a final one that reached "finished"), the time between
    # the segment's last checkpoint (or its start, if none) and its last
    # recorded event is work that had to be redone.
    segments = segment_job_events(job_events)
    wasted_time_sec = 0.0
    for seg in segments:
        if seg[-1]["event"] == "finished":
            continue  # this segment completed the job; nothing wasted
        seg_checkpoints = [e for e in seg if e["event"] == "checkpoint"]
        last_saved_ts = seg_checkpoints[-1]["ts"] if seg_checkpoints else seg[0]["ts"]
        segment_end_ts = seg[-1]["ts"]
        wasted_time_sec += max(0.0, segment_end_ts - last_saved_ts)

    # Recovery time: interruption instant -> next started/resumed event.
    recovery_times = []
    for kill_ev in interruption_events:
        nxt = next((e for e in job_events if e["event"] in START_EVENTS and e["ts"] > kill_ev["ts"]), None)
        if nxt:
            recovery_times.append(nxt["ts"] - kill_ev["ts"])
    recovery_time_sec = sum(recovery_times) / len(recovery_times) if recovery_times else None

    lead_times = [e.get("lead_seconds") for e in harness_events if e["event"] == "risk_triggered"]
    lead_time_sec = sum(lead_times) / len(lead_times) if lead_times else None

    cost_usd = (makespan_sec / 3600.0 * SPOT_HOURLY_RATE_USD) if makespan_sec is not None else None

    return {
        "arm": meta["arm"],
        "rate_seconds": meta["rate_seconds"],
        "rep": meta["rep"],
        "step_budget": meta["step_budget"],
        "completed": completed,
        "timed_out": timed_out,
        "makespan_sec": makespan_sec,
        "num_interruptions": num_interruptions,
        "num_checkpoints": num_checkpoints,
        "checkpoint_bytes_total": checkpoint_bytes_total,
        "wasted_compute_sec": wasted_time_sec,
        "recovery_time_sec": recovery_time_sec,
        "lead_time_sec": lead_time_sec,
        "cost_usd": cost_usd,
    }


def build_summary_table(df):
    metrics = ["completed", "makespan_sec", "wasted_compute_sec", "recovery_time_sec",
               "num_checkpoints", "cost_usd", "lead_time_sec"]
    grouped = df.groupby(["arm", "rate_seconds"])
    table = grouped[metrics].agg(["mean", "std"])
    table.columns = [f"{m}_{stat}" for m, stat in table.columns]
    table["completion_rate"] = grouped["completed"].mean()
    return table.reset_index()


def make_figures(df, table, figures_dir):
    os.makedirs(figures_dir, exist_ok=True)

    fig, ax = plt.subplots()
    for arm, sub in table.groupby("arm"):
        sub = sub.sort_values("rate_seconds")
        ax.plot(sub["rate_seconds"], sub["completion_rate"], marker="o", label=arm)
    ax.set_xlabel("mean seconds between interruptions")
    ax.set_ylabel("completion rate")
    ax.set_title("Completion rate vs interruption rate")
    ax.legend()
    fig.savefig(os.path.join(figures_dir, "completion_vs_rate.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots()
    means = df.groupby("arm")["wasted_compute_sec"].mean().sort_values()
    ax.bar(means.index, means.values)
    ax.set_ylabel("mean wasted compute (sec)")
    ax.set_title("Wasted compute by arm (all rates pooled)")
    fig.savefig(os.path.join(figures_dir, "wasted_compute_by_arm.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots()
    means = df[df["completed"]].groupby("arm")["makespan_sec"].mean().sort_values()
    ax.bar(means.index, means.values)
    ax.set_ylabel("mean makespan (sec, completed runs only)")
    ax.set_title("Makespan by arm")
    fig.savefig(os.path.join(figures_dir, "makespan_by_arm.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", default=os.path.join(HERE, "results", "raw"))
    parser.add_argument("--out-dir", default=os.path.join(HERE, "results"))
    args = parser.parse_args()

    rows = []
    for run_dir in discover_runs(args.results_root):
        row = parse_run(run_dir)
        if row:
            rows.append(row)

    if not rows:
        print(f"No completed runs found under {args.results_root}. Run harness.py first.")
        return

    df = pd.DataFrame(rows)
    os.makedirs(args.out_dir, exist_ok=True)
    df.to_csv(os.path.join(args.out_dir, "summary_runs.csv"), index=False)

    table = build_summary_table(df)
    table.to_csv(os.path.join(args.out_dir, "summary_table.csv"), index=False)

    make_figures(df, table, os.path.join(args.out_dir, "figures"))

    print(f"{len(df)} runs aggregated.")
    print(f"-> {os.path.join(args.out_dir, 'summary_runs.csv')}")
    print(f"-> {os.path.join(args.out_dir, 'summary_table.csv')}")
    print(f"-> {os.path.join(args.out_dir, 'figures')}/*.png")


if __name__ == "__main__":
    main()
