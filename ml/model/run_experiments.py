"""
Driver for the two remaining "improve ML predictive power" levers:
  1. Ensemble: retrain the original (shipped) config across a few seeds, keep
     checkpoints, average their predictions.
  2. Data-config candidate: the top pick from tune_data_config.py's corrected
     (lift-ranked) grid search - spike_threshold=1.005, prediction_horizon=1,
     oversample=True.
3 seeds each (not 5) to keep this tractable - directional evidence, not the
final statistically-rigorous claim the 5-seed baseline sweep already is.
"""
import os
import json
from multi_seed_eval import multi_seed_eval
from ensemble_eval import ensemble_eval

base_dir = os.path.dirname(os.path.abspath(__file__))
ensemble_ckpt_dir = os.path.join(base_dir, "_ensemble_checkpoints")

print("\n\n########## EXPERIMENT 1: ensemble (original config, 3 seeds) ##########")
summary1 = multi_seed_eval(seeds=(0, 1, 2), max_epochs=15, keep_checkpoints_dir=ensemble_ckpt_dir)
with open(os.path.join(base_dir, "experiment_ensemble_seeds.json"), "w") as f:
    json.dump(summary1, f, indent=2)

print("\n\n########## EXPERIMENT 1b: evaluate the ensemble of those 3 seeds ##########")
ensemble_result = ensemble_eval(ensemble_ckpt_dir)
with open(os.path.join(base_dir, "experiment_ensemble_result.json"), "w") as f:
    json.dump(ensemble_result, f, indent=2)

print("\n\n########## EXPERIMENT 2: data-config candidate (threshold=1.005, horizon=1, oversample=True) ##########")
summary2 = multi_seed_eval(seeds=(0, 1, 2), max_epochs=15,
                            prediction_horizon=1, spike_threshold=1.005, oversample=True)
with open(os.path.join(base_dir, "experiment_dataconfig_seeds.json"), "w") as f:
    json.dump(summary2, f, indent=2)

print("\n\n########## ALL EXPERIMENTS DONE ##########")
print(f"Ensemble (3 seeds averaged): PR-AUC {ensemble_result['pr_auc']:.4f}, lift {ensemble_result['lift']:.2f}x")
print(f"Data-config candidate mean: PR-AUC {summary2['pr_auc_mean']:.4f}, "
      f"lift {summary2['pr_auc_mean']/summary2['base_rate']:.2f}x")
print("Baseline (original config, 5-seed, documented): PR-AUC 0.0324 mean, 14.68x lift")
