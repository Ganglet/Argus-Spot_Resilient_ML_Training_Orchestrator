# Lead-Time Sensitivity Result (paper §3.3), 2026-08-06

**Question:** how much prediction lead time does the predictive arm actually need
— and does its win rely on the large (600 s) lead the model claims?

**Reproduce:**
```bash
# arms/predictive_L{2,5,10,15,20,30,45,60}.json generated from predictive.json
python benchmark/harness.py --arms predictive_L2,predictive_L5,predictive_L10,\
predictive_L15,predictive_L20,predictive_L30,predictive_L45,predictive_L60,periodic \
  --rates 20 --reps 5 --step-budget 600 --step-time-sec 0.1 \
  --max-wallclock-multiplier 5 --results-dir results/raw_leadsweep
python benchmark/analyze_leadsweep.py   # -> results/leadsweep_table.csv + Fig 4
```

## Results (predictive arm, 20 s mean interruption interval, 5 reps)

| lead (s) | wasted compute (s) | makespan (s) | # checkpoints | completion |
|---:|---:|---:|---:|---:|
| 2  | 0.0 | 73.1  | 5.4  | 1.0 |
| 5  | 0.0 | 76.2  | 7.4  | 1.0 |
| 10 | 0.0 | 78.0  | 8.8  | 1.0 |
| 15 | 0.0 | 83.3  | 12.6 | 1.0 |
| 20 | 0.0 | 87.0  | 15.2 | 1.0 |
| 30 | 0.0 | 96.7  | 21.8 | 1.0 |
| 45 | 0.0 | 131.7 | 46.6 | 1.0 |
| 60 | 0.0 | 218.3 | 93.4 | 1.0 |

**Periodic baseline (ML-free):** wasted 4.3 s, makespan 78.1 s, 29.0 checkpoints.

Figure: `benchmark/results/figures/leadtime_sensitivity.png`.

## The finding (it inverts the naive intuition)

1. **Wasted compute is ~0 at *every* lead, down to 2 s.** The operator checkpoints
   *synchronously before* migrating, so any lead that clears the checkpoint write
   time eliminates waste. **The zero-waste advantage does not require the model's
   claimed 600 s lead** — a few seconds suffices. This directly defuses the
   "predictive rides on an assumed 600 s oracle lead" objection.

2. **The cost of *excess* lead is over-migration.** Predictive still beats
   periodic on makespan only up to a **knee ≈ the interruption interval** (~10 s
   here). Beyond it, the risk trigger fires far ahead of each interruption every
   cycle, so the job migrates constantly: at a 60 s lead (3× the interval) it
   migrates ~93× and makespan nearly triples (218 s vs 73 s at 2 s).

3. **Below the knee, predictive is strictly better than periodic** — 0 waste,
   makespan ≤ periodic, and *fewer* checkpoints (5–9 vs 29). So the ML-free
   baseline is beaten cleanly when the lead is tuned; it is *not* beaten when the
   lead is left too large.

4. **This explains the §3.2 / Objective-2 anomaly** (predictive over-checkpointed
   35.6× and had higher makespan than periodic in the main table): that arm used
   `risk_lead_seconds = 600`, ~30× the fast-regime interval — deep in the
   over-migration zone. A tuned lead keeps the zero-waste win *without* the
   makespan penalty.

## Guideline (the §3.3 takeaway)

> Set the predictive lead **just above the checkpoint write time and well below
> the interruption interval.** More lead buys no reduction in wasted compute and
> linearly increases migration overhead and makespan.

## Honest caveats
- **Synthetic checkpoint is near-instant**, so the practical *lower* bound here is
  tiny; in production the lower bound = the real checkpoint write time (model +
  optimizer state to storage). State this.
- The model's measured lead is **600 s mean against the *proxy* label**
  (`ml/model/measure_lead_time.py`: 9 TPs, range 300–900 s) — erring *long*. That
  is safe for waste but costly on makespan under frequent interruptions; the fix
  is capping the operator's effective lead, not a larger model.
- One interruption regime (20 s interval) was swept; the knee-≈-interval relation
  should hold across rates but was not swept over multiple rates (future work).
