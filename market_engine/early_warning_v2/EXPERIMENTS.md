# Early Warning V2 — Experiment Log

## 1. V1 Reproduction

The Korea V1 Early Warning pipeline was reproduced in the new project before any V2 modifications.

### Validation Design

- Target: Target_10D
- Features: 17
- Initial training window: 1,260 observations
- Test step: 21 observations
- Purge: 10 observations
- Window: expanding
- Models: Logistic Regression and XGBoost

### OOS Sample

- OOS observations: 2,454
- OOS period: 2016-09-13 to 2026-09-16
- Positive labels: 617
- Completed folds: 117

### Reproduction Check

Original V1 and reproduced V1 predictions were compared date-by-date.

Target:
- Exact match: Yes
- Maximum absolute difference: 0

XGBoost:
- Exact prediction match: Yes
- Maximum absolute difference: 0

Logistic Regression:
- Numerical match within floating-point precision
- Maximum absolute difference: 2.624e-13
- No observations differed by more than 1e-12

Conclusion:

The V1 validation pipeline has been successfully reproduced.

All subsequent V2 experiments will use this reproduced pipeline as the controlled benchmark.

---

## 2. Frozen V1 XGBoost Benchmark

- ROC-AUC: 0.8797
- PR-AUC: 0.7415
- Precision: 0.6274
- Recall: 0.7504
- F1: 0.6834
- False Positive Rate: 0.1497

Confusion matrix:

- TN: 1,562
- FP: 275
- FN: 154
- TP: 463

---

## 3. V2 Research Rules

V2 changes must be evaluated using strictly OOS predictions.

Experiments must not be selected merely because they improve the October 2026 case.

The October 2026 market shock remains a later holdout case.

Primary evaluation dimensions:

- ROC-AUC
- PR-AUC
- Precision
- Recall
- F1
- False Positive Rate
- Stress-event coverage
- Lead time
- Missed-event behavior
- False-warning behavior

New features will initially be tested through controlled ablation against the frozen 17-feature V1 benchmark.

Market Breadth and Cross-Asset Correlation remain outside the primary V2 model during initial experiments in order to preserve the independence of the Signal Divergence Monitor.

---

## 4. Experiment A — Downside / Tail Dynamics

Added four KOSPI200 features to the frozen V1 17-feature model:

- KOSPI200_Downside_Vol_20D
- KOSPI200_Negative_Return_Ratio_20D
- KOSPI200_Worst_Return_20D
- KOSPI200_Drawdown_Velocity_5D

Total features: 21

Validation design and OOS sample were kept identical to V1.

### XGBoost OOS Results

| Metric | V1 17F | Experiment A 21F |
|---|---:|---:|
| ROC-AUC | 0.8797 | 0.8827 |
| PR-AUC | 0.7415 | 0.7405 |
| Precision | 0.6274 | 0.6301 |
| Recall | 0.7504 | 0.7731 |
| F1 | 0.6834 | 0.6943 |
| FPR | 0.1497 | 0.1524 |
| FN | 154 | 140 |
| FP | 275 | 280 |

### Interpretation

Experiment A reduced false negatives by 14 observations while adding 5 false positives.

Recall and F1 improved, with a small improvement in ROC-AUC and Precision.
PR-AUC decreased slightly and FPR increased slightly.

Decision: RETAIN AS V2 CANDIDATE, NOT YET FINAL.

The four added features must next be evaluated individually / through internal ablation to determine which features provide incremental OOS value and whether redundant features can be removed.

## Experiment A — Internal Feature Ablation

All tests use the same Korea 10D purged expanding walk-forward OOS design and fixed 0.50 decision threshold.

| Model | ROC-AUC | PR-AUC | Precision | Recall | F1 | FPR | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V1 17F | 0.8797 | 0.7415 | 0.6274 | 0.7504 | 0.6834 | 0.1497 | 154 | 275 |
| + Downside Vol | 0.8804 | 0.7419 | 0.6110 | 0.7585 | 0.6768 | 0.1622 | 149 | 298 |
| + Negative Return Ratio | 0.8816 | 0.7451 | 0.6172 | 0.7553 | 0.6793 | 0.1573 | 151 | 289 |
| + Worst Return | 0.8781 | 0.7322 | 0.6192 | 0.7618 | 0.6831 | 0.1573 | 147 | 289 |
| + Drawdown Velocity | 0.8802 | 0.7417 | 0.6163 | 0.7601 | 0.6807 | 0.1590 | 148 | 292 |
| Worst Return + Drawdown Velocity 19F | 0.8791 | 0.7409 | 0.6297 | 0.7358 | 0.6786 | 0.1453 | 163 | 267 |
| Experiment A full 21F | 0.8827 | 0.7405 | 0.6301 | 0.7731 | 0.6943 | 0.1524 | 140 | 280 |

### Decision

The compact 19-feature specification is rejected because recall and F1 deteriorate relative to V1 and false negatives increase from 154 to 163.

No individual Experiment A feature provides the same trade-off as the complete feature family. The full 21-feature specification reduces false negatives from 154 to 140 while increasing false positives only from 275 to 280. It also improves ROC-AUC, precision, recall, and F1 relative to V1.

Therefore, the full Experiment A 21-feature specification is retained as the current V2 candidate. Final adoption remains conditional on event-level coverage, lead-time, and false-warning analysis.

## Final V2-A Event-Level Validation and Model Selection

The retained 21-feature Experiment A candidate was compared with the frozen V1 17-feature benchmark using the same Korea purged expanding walk-forward OOS predictions, fixed 0.50 threshold, and 10-trading-day horizon.

### Stress-Event Detection

| Metric | V1 17F | V2-A 21F |
|---|---:|---:|
| Stress Episodes | 57 | 57 |
| Detected Episodes | 52 | 54 |
| Missed Episodes | 5 | 3 |
| Event Coverage | 91.23% | 94.74% |
| Median First Warning Lead | 10.0 | 10.0 |
| Mean First Warning Lead | 8.19 | 8.48 |

V2-A newly detected two stress episodes that V1 missed, with onsets on 2018-02-06 and 2024-11-13. V2-A did not newly miss any episode previously detected by V1.

### False-Warning Trade-off

| Metric | V1 17F | V2-A 21F |
|---|---:|---:|
| Warning Episodes | 77 | 91 |
| Followed by Stress | 33 | 39 |
| False-Warning Episodes | 44 | 52 |
| Warning Precision | 42.86% | 42.86% |
| False-Warning Rate | 57.14% | 57.14% |
| Median Days to Stress | 3.0 | 3.0 |
| False-Warning Episodes / Year | 4.40 | 5.20 |

V2-A generates more warning episodes overall. This increases the absolute false-warning frequency by approximately 0.8 episodes per year, while the warning precision and false-warning rate remain unchanged.

In return, V2-A reduces observation-level false negatives from 154 to 140, improves recall from 0.7504 to 0.7731, improves F1 from 0.6834 to 0.6943, and increases event-level stress coverage from 91.23% to 94.74%.

### Final Decision

SELECT V2-A 21F AS THE FINAL V2 CHAMPION.

The selection is based on the missed-risk versus false-warning trade-off rather than ROC-AUC alone. Relative to V1, V2-A detects two additional OOS stress episodes without losing any episode previously detected by V1, while preserving median lead time and accepting a moderate increase in absolute false-warning frequency.

The fixed 0.50 threshold is retained. No threshold adjustment is made based on later observed shocks.

Experiment A model specification is now frozen. Further feature expansion or V2-B experimentation is not required for the final project unless a material implementation issue is discovered.

The October 2026 Korea shock remains a retrospective holdout case and must not be used for model selection or tuning.

## October 2026 Retrospective Holdout

The October 2026 Korea sell-off was evaluated only after the V2-A 21F specification and fixed 0.50 threshold had been selected and frozen. This period was not used for feature selection, threshold tuning, or model selection.

| Date | KOSPI200 1D Return | V1 Risk | V2 Risk |
|---|---:|---:|---:|
| 2026-10-07 | -2.03% | 3.4% | 5.2% |
| 2026-10-08 | -2.71% | 12.1% | 14.8% |
| 2026-10-12 | -3.79% | 15.6% | 14.7% |
| 2026-10-13 | -6.25% | 37.8% | 36.8% |
| 2026-10-14 | -0.56% | 32.3% | 27.2% |
| 2026-10-15 | -8.13% | 40.5% | 43.7% |

Neither V1 nor V2-A crossed the fixed 0.50 warning threshold during the holdout period.

V2-A showed somewhat higher risk than V1 on 2026-10-07, 2026-10-08, and 2026-10-15, but it did not provide a threshold-level warning before the initial 2026-10-12 sell-off.

### Holdout Interpretation

The October case demonstrates that the V2 improvement is incremental rather than universal. V2-A improves broad OOS stress-event coverage and reduces missed-risk observations, but abrupt market shocks can still occur without a threshold-level advance warning.

No model parameters, features, or thresholds are changed in response to this holdout result.

This failure mode is retained as an explicit model limitation and supports presenting the Market Monitor as a risk-monitoring and early-warning system rather than a guaranteed crash-prediction system.
