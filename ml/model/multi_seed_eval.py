import os
import json
import shutil
import tempfile
import statistics

from train import train_model
from calibrate_and_finalize import evaluate_checkpoint

def multi_seed_eval(seeds=(0, 1, 2, 3, 4), max_epochs=15):
    """
    Single training runs on this dataset are noisy - three runs of the identical
    13-feature config scored PR-AUC 0.0183, 0.0211, and 0.0480 (see
    docs/objective3_result.md). Reporting any one of those as "the" model
    quality is misleading. This trains N seeds from scratch, evaluates each on the
    same held-out test set, and reports mean/std - the number that actually belongs
    in the paper.

    Does NOT touch the shipped checkpoint (ml/model/spot_transformer.pt) - each
    seed trains into its own temp directory that gets cleaned up after.
    """
    results = []
    base_dir = os.path.dirname(os.path.abspath(__file__))

    for seed in seeds:
        scratch_dir = tempfile.mkdtemp(prefix=f"argus_seed{seed}_")
        try:
            print(f"\n{'='*60}\nSeed {seed} — training (scratch dir: {scratch_dir})\n{'='*60}")
            train_model(seed=seed, output_dir=scratch_dir, max_epochs=max_epochs, run_name=f"multiseed_{seed}")

            print(f"Seed {seed} — evaluating on held-out test set")
            eval_result = evaluate_checkpoint(scratch_dir, verbose=False)

            row = {
                "seed": seed,
                "pr_auc": eval_result["calibrated"]["pr_auc"],
                "brier": eval_result["calibrated"]["brier"],
                "f1": eval_result["calibrated"].get("f1"),
                "precision": eval_result["calibrated"].get("precision"),
                "recall": eval_result["calibrated"].get("recall"),
            }
            results.append(row)
            print(f"Seed {seed} -> PR-AUC {row['pr_auc']:.4f}, Brier {row['brier']:.4f}")
        finally:
            shutil.rmtree(scratch_dir, ignore_errors=True)

        # Write after every seed, not just at the end - if this process gets killed
        # mid-sweep (has happened before with long background runs in this repo),
        # whatever seeds finished are still on disk instead of lost.
        partial_path = os.path.join(base_dir, "multi_seed_results.json")
        with open(partial_path, "w") as f:
            json.dump({"seeds_completed": [r["seed"] for r in results], "runs": results}, f, indent=2)

    pr_aucs = [r["pr_auc"] for r in results]
    briers = [r["brier"] for r in results]

    summary = {
        "seeds": list(seeds),
        "runs": results,
        "pr_auc_mean": statistics.mean(pr_aucs),
        "pr_auc_std": statistics.stdev(pr_aucs) if len(pr_aucs) > 1 else 0.0,
        "pr_auc_min": min(pr_aucs),
        "pr_auc_max": max(pr_aucs),
        "brier_mean": statistics.mean(briers),
    }

    print(f"\n{'='*60}")
    print(f"MULTI-SEED SUMMARY ({len(seeds)} runs, base_rate ~0.00221)")
    print(f"{'='*60}")
    for r in results:
        print(f"  seed {r['seed']}: PR-AUC {r['pr_auc']:.4f}  Brier {r['brier']:.4f}")
    print(f"\nPR-AUC: mean={summary['pr_auc_mean']:.4f}  std={summary['pr_auc_std']:.4f}  "
          f"range=[{summary['pr_auc_min']:.4f}, {summary['pr_auc_max']:.4f}]")
    print(f"Mean lift over random: {summary['pr_auc_mean'] / 0.00221:.2f}x")
    print(f"Brier mean: {summary['brier_mean']:.4f}")

    out_path = os.path.join(base_dir, "multi_seed_results.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved summary to {out_path}")

    return summary

if __name__ == "__main__":
    multi_seed_eval()
