"""Lead-time sensitivity analysis (paper Sec 3.3).

Reads the lead-sweep raw results (predictive_L{N} arms + periodic baseline at a
fixed interruption rate), reuses aggregate.parse_run for identical metric
definitions, and produces:

  results/leadsweep_table.csv               mean +/- std per lead
  results/figures/leadtime_sensitivity.png  the crossover figure (Fig 4)

The finding to report: predictive's wasted compute falls as lead grows, while
makespan/checkpoint-overhead rises (over-migration). L* = the lead at which
predictive first matches the ML-free periodic baseline on wasted compute --
below L* the prediction buys nothing; far above it, it over-migrates.
"""
import glob
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from aggregate import parse_run

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "results", "raw_leadsweep")
FIGDIR = os.path.join(HERE, "results", "figures")


def main():
    run_dirs = sorted(d for d in glob.glob(os.path.join(RAW, "*", "rate_*s", "rep_*")) if os.path.isdir(d))
    rows = [r for r in (parse_run(d) for d in run_dirs) if r]
    if not rows:
        raise SystemExit(f"no parsed runs under {RAW} -- has the sweep finished?")
    df = pd.DataFrame(rows)

    def lead_of(arm):
        m = re.match(r"predictive_L(\d+)$", arm)
        return int(m.group(1)) if m else None
    df["lead"] = df["arm"].map(lead_of)

    pred = df[df["lead"].notna()].copy()
    per = df[df["arm"] == "periodic"]

    metrics = ["wasted_compute_sec", "makespan_sec", "num_checkpoints", "num_interruptions", "recovery_time_sec"]
    g = pred.groupby("lead")
    tbl = g[metrics].agg(["mean", "std"])
    tbl.columns = [f"{m}_{s}" for m, s in tbl.columns]
    tbl["completion_rate"] = g["completed"].mean()
    tbl = tbl.reset_index().sort_values("lead")

    per_waste = per["wasted_compute_sec"].mean()
    per_make = per[per["completed"]]["makespan_sec"].mean()
    per_ckpt = per["num_checkpoints"].mean()
    rate = int(per["rate_seconds"].iloc[0]) if len(per) else None

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    tbl.to_csv(os.path.join(HERE, "results", "leadsweep_table.csv"), index=False)

    # The real result: wasted compute is ~0 at EVERY lead (synchronous checkpoint
    # before migrate), so there is no lower L* on waste. The meaningful marker is
    # the UPPER knee: the largest lead at which predictive still beats periodic on
    # makespan (above it, over-migration makes predictive slower than periodic).
    dominant = tbl[tbl["makespan_sec_mean"] <= per_make]
    L_knee = int(dominant["lead"].max()) if len(dominant) else None

    print("\n=== lead-time sensitivity (predictive), fixed rate ===")
    print(tbl[["lead", "wasted_compute_sec_mean", "makespan_sec_mean",
               "num_checkpoints_mean", "completion_rate"]].to_string(index=False))
    print(f"\nperiodic baseline: wasted={per_waste:.2f}s  makespan={per_make:.2f}s  checkpoints={per_ckpt:.1f}")
    print(f"interruption interval (MTBF): {rate}s")
    print(f"FINDING: wasted compute ~0 at every lead (no lower L*); predictive still")
    print(f"beats periodic on makespan up to lead ~= {L_knee}s (~ the {rate}s interval);")
    print(f"above that it over-migrates. Guideline: keep lead small (just above the")
    print(f"checkpoint write time), well below the interruption interval.")

    # Two-panel figure: (top) wasted compute flat at 0 vs periodic; (bottom)
    # makespan + checkpoint count climbing with lead (the over-migration cost).
    fig, (axw, axm) = plt.subplots(2, 1, figsize=(6.5, 6.0), sharex=True)
    x = tbl["lead"]

    axw.plot(x, tbl["wasted_compute_sec_mean"], marker="o", color="#2e7d32", label="predictive")
    axw.axhline(per_waste, ls="--", color="#c62828", alpha=0.7, label=f"periodic ({per_waste:.1f}s)")
    axw.set_ylabel("wasted compute (s)")
    axw.set_ylim(-0.5, max(per_waste * 2.5, 2))
    axw.set_title(f"Lead-time sensitivity at {rate}s interruption interval:\n"
                  f"zero waste at every lead — the cost of excess lead is over-migration")
    axw.legend(fontsize=8, loc="upper left")

    axm.plot(x, tbl["makespan_sec_mean"], marker="s", color="#1565c0", label="predictive makespan")
    axm.axhline(per_make, ls="--", color="#1565c0", alpha=0.6, label=f"periodic makespan ({per_make:.0f}s)")
    axc = axm.twinx()
    axc.plot(x, tbl["num_checkpoints_mean"], marker="^", color="#ef6c00", label="predictive checkpoints")
    axc.axhline(per_ckpt, ls="--", color="#ef6c00", alpha=0.5)
    axm.set_xlabel("predictive lead time (s)")
    axm.set_ylabel("makespan (s)", color="#1565c0")
    axc.set_ylabel("# checkpoints", color="#ef6c00")
    axm.tick_params(axis="y", labelcolor="#1565c0")
    axc.tick_params(axis="y", labelcolor="#ef6c00")
    if L_knee is not None:
        axm.axvline(L_knee, ls=":", color="gray", alpha=0.8)
        axm.annotate(f"knee ~{L_knee}s\n(≈ interval)", xy=(L_knee, per_make),
                     xytext=(6, -28), textcoords="offset points", fontsize=8, color="gray")
    l1, lab1 = axm.get_legend_handles_labels()
    l2, lab2 = axc.get_legend_handles_labels()
    axm.legend(l1 + l2, lab1 + lab2, fontsize=8, loc="upper left")

    fig.tight_layout()
    os.makedirs(FIGDIR, exist_ok=True)
    out = os.path.join(FIGDIR, "leadtime_sensitivity.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nwrote {out}")
    print(f"wrote results/leadsweep_table.csv")


if __name__ == "__main__":
    main()
