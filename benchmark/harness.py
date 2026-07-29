"""Track 2 benchmark harness — Poisson interruption injection.

For each (arm x interruption-rate x repetition), spawns job.py and kills it on
a Poisson schedule (mean = --rates seconds), respawning against the same run
dir so checkpoint state (if any) survives. The action taken at each scheduled
interruption instant T is driven entirely by the arm's config:

  no risk/notice lead configured (no-protection, periodic):
      wait until T, kill abruptly, respawn.
  notice_lead_seconds configured (reactive):
      at T - notice_lead, drop the NOTICE trigger (job checkpoints on its next
      poll); wait until T, kill, respawn.
  risk_lead_seconds + migrates_on_risk configured (predictive):
      at T - risk_lead, drop the RISK trigger and wait for the job to confirm
      a checkpoint; kill + respawn immediately (the run "migrates" ahead of T,
      so the scheduled reclaim at T never actually happens to it).

No EKS/Spot needed here by design (see docs/phase6_remaining.md Track 2) —
this runs as plain local subprocesses so hundreds of trials are cheap.
"""
import argparse
import glob
import json
import os
import random
import subprocess
import sys
import time

from metrics_logger import log_event, read_events

HERE = os.path.dirname(os.path.abspath(__file__))
JOB_SCRIPT = os.path.join(HERE, "job.py")

# Real Spot interruption frequency is minutes-scale (see Track 2 spec);
# production sweep values in seconds.
DEFAULT_RATES_SECONDS = [120, 300, 600, 1800]


def wait_until(deadline, proc):
    """Sleep until `deadline` or until proc exits, whichever first. Returns True if proc exited."""
    while True:
        if proc.poll() is not None:
            return True
        now = time.time()
        if now >= deadline:
            return False
        time.sleep(min(0.02, deadline - now))


def write_trigger(run_dir, filename):
    open(os.path.join(run_dir, filename), "a").close()


def wait_for_checkpoint(events_path, policy, timeout, since_ts):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for ev in read_events(events_path):
            if ev.get("event") == "checkpoint" and ev.get("policy") == policy and ev["ts"] >= since_ts:
                return True
        time.sleep(0.02)
    return False


def spawn_job(run_dir, arm_config_path, step_budget, step_time_sec, synthetic):
    os.makedirs(run_dir, exist_ok=True)
    log_path = os.path.join(run_dir, "stdout.log")
    log_f = open(log_path, "a")
    cmd = [
        sys.executable, JOB_SCRIPT,
        "--run-dir", run_dir,
        "--arm-config", arm_config_path,
        "--step-budget", str(step_budget),
        "--step-time-sec", str(step_time_sec),
    ]
    if synthetic:
        cmd.append("--synthetic")
    return subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)


def kill_and_respawn(proc, spawn_fn):
    if proc.poll() is None:
        proc.kill()
        proc.wait()
    return spawn_fn()


def run_cycle(arm, run_dir, proc, events_path, harness_path, rng, rate_seconds, spawn_fn):
    now = time.time()
    T = now + rng.expovariate(1.0 / rate_seconds)
    risk_lead = arm.get("risk_lead_seconds")
    notice_lead = arm.get("notice_lead_seconds")
    migrates = arm.get("migrates_on_risk", False)

    if risk_lead:
        if wait_until(T - risk_lead, proc):
            return proc, "job_exited"
        since = time.time()
        write_trigger(run_dir, arm.get("risk_trigger_file", "RISK"))
        log_event(harness_path, "risk_triggered", scheduled_kill_at=T, lead_seconds=risk_lead)
        confirmed = wait_for_checkpoint(events_path, "predictive", timeout=max(0.2, min(2.0, T - time.time())), since_ts=since)
        if migrates:
            proc = kill_and_respawn(proc, spawn_fn)
            log_event(harness_path, "migrated", risk_confirmed=confirmed)
            return proc, "migrated"

    if notice_lead:
        if wait_until(T - notice_lead, proc):
            return proc, "job_exited"
        write_trigger(run_dir, arm.get("notice_trigger_file", "NOTICE"))
        log_event(harness_path, "notice_triggered", scheduled_kill_at=T, lead_seconds=notice_lead)

    if wait_until(T, proc):
        return proc, "job_exited"
    proc = kill_and_respawn(proc, spawn_fn)
    log_event(harness_path, "interrupted")
    return proc, "interrupted"


def run_trial(arm, rate_seconds, rep, results_root, step_budget, step_time_sec, synthetic, seed, max_wallclock_multiplier):
    run_dir = os.path.join(results_root, arm["name"], f"rate_{rate_seconds}s", f"rep_{rep}")
    os.makedirs(run_dir, exist_ok=True)
    for stale in ("events.jsonl", "harness.jsonl", "checkpoint.pt", "stdout.log", "NOTICE", "RISK"):
        p = os.path.join(run_dir, stale)
        if os.path.exists(p):
            os.remove(p)

    events_path = os.path.join(run_dir, "events.jsonl")
    harness_path = os.path.join(run_dir, "harness.jsonl")
    arm_config_path = os.path.join(HERE, "arms", f"{arm['name']}.json")

    def spawn_fn():
        return spawn_job(run_dir, arm_config_path, step_budget, step_time_sec, synthetic)

    rng = random.Random(seed)
    log_event(harness_path, "run_meta", arm=arm["name"], rate_seconds=rate_seconds, rep=rep, step_budget=step_budget)

    run_start = time.time()
    max_deadline = run_start + step_budget * step_time_sec * max_wallclock_multiplier
    proc = spawn_fn()

    outcome = "unknown"
    while True:
        if proc.poll() is not None:
            outcome = "completed" if proc.returncode == 0 else f"crashed_{proc.returncode}"
            log_event(harness_path, "job_exit", outcome=outcome)
            break
        if time.time() > max_deadline:
            proc.kill()
            proc.wait()
            outcome = "timed_out"
            log_event(harness_path, "timed_out")
            break
        proc, cycle_outcome = run_cycle(arm, run_dir, proc, events_path, harness_path, rng, rate_seconds, spawn_fn)

    return run_dir, outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="all", help="comma-separated arm names, or 'all'")
    parser.add_argument("--rates", default=",".join(str(r) for r in DEFAULT_RATES_SECONDS),
                         help="comma-separated mean seconds-between-interruptions")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--step-budget", type=int, default=200)
    parser.add_argument("--step-time-sec", type=float, default=0.05)
    parser.add_argument("--synthetic", action="store_true", default=True)
    parser.add_argument("--results-dir", default=os.path.join(HERE, "results", "raw"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-wallclock-multiplier", type=float, default=4.0)
    args = parser.parse_args()

    if args.arms == "all":
        arm_paths = sorted(glob.glob(os.path.join(HERE, "arms", "*.json")))
    else:
        arm_paths = [os.path.join(HERE, "arms", f"{name}.json") for name in args.arms.split(",")]

    arms = []
    for p in arm_paths:
        with open(p) as f:
            arms.append(json.load(f))

    rates = [int(r) for r in args.rates.split(",")]

    total = len(arms) * len(rates) * args.reps
    done = 0
    for arm in arms:
        for rate in rates:
            for rep in range(args.reps):
                done += 1
                print(f"[{done}/{total}] arm={arm['name']} rate={rate}s rep={rep}")
                run_dir, outcome = run_trial(
                    arm, rate, rep, args.results_dir, args.step_budget, args.step_time_sec,
                    args.synthetic, args.seed + rep, args.max_wallclock_multiplier,
                )
                print(f"  -> {outcome} ({run_dir})")


if __name__ == "__main__":
    main()
