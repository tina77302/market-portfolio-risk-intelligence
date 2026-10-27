# V1 Baseline Specification

## Purpose

V1 is the frozen benchmark from the previous Market Stress Early Warning project.

V2 experiments must be evaluated against this baseline using strictly out-of-sample methodology.

The V1 production project must not be modified.

---

## 1. Prediction Objective

Predict whether at least one market Stress Event will occur within the next 10 trading days.

Target:

Target_10D(t) = 1 if a Stress Event occurs at least once during t+1 ... t+10.

Primary model output:

Risk Score = XGBoost predicted probability for Target_10D.

Operational warning threshold:

0.50 (Risk Score 50).

This threshold is a model decision threshold, not a calibrated statement that market stress has a literal 50% probability.

---

## 2. Stress Event Definition

A Stress Event occurs when the current MSI is greater than or equal to the historical 90th percentile threshold.

The threshold for date t is calculated only from MSI observations available through t-1.

No future observations are used to determine the threshold.

---

## 3. U.S. Market Stress Index

Three equally weighted stress channels:

1. Equity Stress
   - Negative SPY 21-trading-day return

2. Volatility Stress
   - VIX level

3. Credit Stress
   - BAA-Treasury Spread

Normalization:

- Past-only rolling Z-score
- 252-trading-day rolling window
- Current observation excluded from its own normalization statistics

Composite:

MSI = (Z_Equity + Z_Volatility + Z_Credit) / 3

---

## 4. Korea Market Stress Index

Three equally weighted stress channels:

1. Equity Stress
   - Negative KOSPI200 21-trading-day return

2. Volatility Stress
   - VKOSPI level

3. Credit Stress
   - AA- 3Y corporate yield minus Korea Treasury 3Y yield

Normalization:

- Past-only rolling Z-score
- 252-trading-day rolling window
- Minimum 126 observations

Composite:

Korea_MSI = (Z_Equity + Z_Volatility + Z_Credit) / 3

Stress threshold:

- Past-only expanding 90th percentile
- Minimum 252 observations

---

## 5. U.S. V1 ML Features

17 features:

### Equity
- SPY_1D_Return
- SPY_5D_Return
- SPY_20D_Return
- SPY_20D_Vol
- SPY_60D_Vol
- SPY_Drawdown
- SPY_20D_Momentum

### Volatility
- VIX_Level
- VIX_1D_Change
- VIX_5D_Change
- VIX_20D_Momentum
- VIX_252D_ZScore

### Credit
- Credit_Level
- Credit_1D_Change
- Credit_5D_Change
- Credit_20D_Momentum
- Credit_252D_ZScore

---

## 6. XGBoost Baseline

Parameters:

- n_estimators = 100
- max_depth = 3
- learning_rate = 0.05
- subsample = 0.8
- colsample_bytree = 0.8
- eval_metric = logloss
- random_state = 42

Class imbalance:

scale_pos_weight = negative training samples / positive training samples

The value is recalculated independently for every walk-forward fold.

---

## 7. Walk-Forward OOS Validation

Method:

- Expanding-window walk-forward validation
- Initial training window: approximately 5 years (5 × 252 observations)
- OOS test step: approximately 1 month (21 observations)
- 10-trading-day embargo before every test window

Reason for embargo:

Target_10D uses information from t+1 through t+10.

Therefore, the 10 observations immediately before the OOS test window are excluded from training to reduce target leakage.

Models evaluated:

- Logistic Regression
- XGBoost

Only strictly OOS predictions are used for model performance evaluation.

---

## 8. Deployment Model Separation

After OOS validation, deployment models are trained separately using all currently available labeled observations.

Deployment models are used for current/web inference only.

Deployment-model predictions must not be used as OOS performance evidence.

---

## 9. V2 Research Rule

V1 remains frozen.

V2 must not be optimized merely to catch a known historical missed event.

Any new feature, horizon, model, or decision rule must demonstrate value under out-of-sample validation.

Primary comparison areas:

- ROC-AUC
- PR-AUC
- Recall
- Precision
- False Positive Rate
- Stress-event coverage
- Lead time
- Missed-event behavior
- False-warning behavior

Signal Divergence must use market information that provides incremental information beyond the V1 Risk Score and MSI.

It must not simply repackage the existing Equity / Volatility / Credit MSI components.

---

## 10. Korea V1 Frozen OOS Benchmark

OOS evaluation period:

- 2016-09-13 to 2026-09-16
- Total observations: 2,454
- Target positives: 617
- Target negatives: 1,837
- Decision threshold: 0.50

### Logistic Regression

- ROC-AUC: 0.8640
- PR-AUC: 0.7492
- Precision: 0.5816
- Recall: 0.7277
- F1: 0.6465
- False Positive Rate: 0.1758

Confusion matrix:

- TN: 1,514
- FP: 323
- FN: 168
- TP: 449

### XGBoost

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

### V2 Comparison Rule

The frozen V1 XGBoost result is the primary Korea benchmark.

V2 improvements must be demonstrated on strictly out-of-sample predictions using comparable validation methodology.

A V2 candidate should not be considered superior based only on ROC-AUC. Evaluation must jointly consider:

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

The October 2026 market event occurs after the frozen OOS period and must remain a later holdout case rather than a model-selection target.
