# Signal Divergence Monitor — Korea Validation

## Objective

Detect market deterioration that may remain hidden while the existing V1 Early Warning model and MSI are still below their operational warning thresholds.

Signal Divergence is an independent monitoring layer, not a replacement crash-prediction model and not a lowered V1 threshold.

## Blind-Spot Definition

A V1+MSI blind state is defined as:

- V1 XGBoost Risk Score < 0.50
- Korea MSI < official Stress Threshold
- Actual Target_10D = 1

Historical OOS validation period:
2016-09-13 to 2026-09-16.

## Candidate Signals

### FX Stress

USD/KRW return and level-based stress signals were tested using strictly past-only percentiles.

Result:
Rejected as a primary divergence signal due to weak incremental OOS value.

Examples:
- FX 90% >=1: 8.8% blind-day capture, 238 false-signal days
- FX 90% >=2: 5.1% capture, 61 false-signal days

FX also did not activate during the October 2026 Korea case study.

### Cross-Asset Correlation

Assets:
- KOSPI200
- SPY
- TLT
- GLD

20-trading-day rolling cross-asset correlation stress was evaluated using past-only percentiles.

Correlation produced relatively high precision under strict conditions but low event coverage.

Example:
- CORR 90% >=2: 7.4% blind-day capture, 9 false-signal days, 52.6% precision
- CORR 95% >=2: 4.4% capture, 2 false-signal days, 75.0% precision

At the event level, correlation did not identify additional blind episodes beyond those detected by breadth.

Conclusion:
Use as a confirmation / confidence layer rather than the primary divergence detector.

## Market Breadth

Breadth is calculated from the current active KOSPI/KOSDAQ stock universe.

Signals:
- 1D decline breadth
- 1D loss >2% breadth
- 5D loss >5% breadth
- drawdown >10% breadth
- high-volatility breadth
- abnormal-volume breadth

Each signal is normalized using a strictly past-only expanding percentile.

Important limitation:
The historical stock universe is based on currently active securities and therefore contains survivorship bias.

## Breadth Rule Comparison

Raw 90% >=1:
- Pre-stress blind-episode coverage: 83.3%
- Median lead: 8 trading days
- False-warning episodes/year: 19.49

90% >=1 with 2-of-3 persistence:
- Coverage: 55.6%
- Median lead: 8 trading days
- False-warning episodes/year: 8.99

Raw 90% >=2:
- Coverage: 55.6%
- Median lead: 7 trading days
- False-warning episodes/year: 10.89

90% >=2 with 2-of-3 persistence:
- Coverage: 33.3%
- Median lead: 6 trading days
- False-warning episodes/year: 4.20

95% >=1 with 2-of-3 persistence:
- Coverage: 33.3%
- Median lead: 7.5 trading days
- False-warning episodes/year: 4.60

95% >=2 with 2-of-3 persistence:
- Coverage: 11.1%
- Median lead: 9.5 trading days
- False-warning episodes/year: 1.60

## Selected Operational Candidate

Primary Breadth Divergence candidate:

1. At least 2 breadth indicators exceed their own strictly past-only 90th percentile.
2. This condition occurs on at least 2 of the most recent 3 trading days.
3. V1 Risk Score remains below 0.50.
4. MSI remains below its official Stress Threshold.

Historical OOS result:

- Eligible pre-stress blind episodes: 18
- Episodes detected before stress: 6
- Coverage: 33.3%
- Median lead time: 6 trading days
- False-warning frequency: approximately 4.2 episodes per year

This rule was selected using historical OOS evidence, not the October 2026 case.

## October 2026 Holdout Case

The selected rule was applied unchanged after rule selection.

Breadth raw deterioration:
- 2026-10-12: 2 indicators above 90th percentile
- 2026-10-13: 2 indicators above 90th percentile
- 2026-10-15: 4 indicators above 90th percentile

2-of-3 persistent divergence activated:
- 2026-10-13
- 2026-10-14
- 2026-10-15

Interpretation:

The monitor did NOT predict the initial October 12 selloff in advance.

Instead, it detected broad internal market deterioration beginning October 13 while the V1 Risk Score remained below its 0.50 warning threshold and MSI remained below its official stress threshold.

Therefore the October case supports the intended role of Signal Divergence as an independent blind-spot monitoring layer rather than as a standalone crash predictor.

## Current Architecture

- Primary divergence detector: Market Breadth
- Confirmation layer: Cross-Asset Correlation
- Rejected candidate: FX Stress
- V1 Risk threshold remains unchanged
- MSI threshold remains unchanged

The monitor is designed to complement, not overwrite, the predictive Early Warning model.
